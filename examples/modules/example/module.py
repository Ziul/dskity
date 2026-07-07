"""Example module: demonstrates dskity features in one self-contained unit.

Shows:
- Module registration with typed per-module settings
- Lifecycle hooks (on_startup / on_shutdown)
- In-process EventBus: emit and subscribe between modules
- Shared async HTTP client via request.app.state.http_client
- ProblemDetail for structured error responses
- Module-to-module URL resolution via request.app.modules (with local fallback)
- Request-ID propagation through downstream calls

Design note
-----------
``clients`` passed to ``register()`` is built *before* the app lifespan runs, so
``clients.http_client`` and ``clients.events`` are always ``None`` at that point.
Route handlers run *after* lifespan, so they must read live resources from
``request.app.state``:

    http_client → request.app.state.http_client
    events      → request.app.state.event_bus

Lifecycle hooks (on_startup / on_shutdown) receive a fully-initialised
``TransportClients`` with both fields set, so they can use ``clients.events``
directly.
"""

from __future__ import annotations

import logging
import math
from dataclasses import dataclass, field

from fastapi import APIRouter, Request
from pydantic import BaseModel, Field

from dskity import DSkitySettings, Module, ModuleMeta, ProblemDetail, TransportClients

logger = logging.getLogger(__name__)


# ── Per-module typed configuration ────────────────────────────────────────────

class ExamplesSettings(BaseModel):
    """Additional settings for the examples module (examples.* in settings.yaml)."""

    factorial_max: int = Field(
        default=200,
        description="Maximum n allowed for the factorial endpoint.",
    )
    emit_events: bool = Field(
        default=True,
        description="Publish events to the bus after each computation.",
    )


# ── Module ────────────────────────────────────────────────────────────────────

@dataclass(frozen=True)
class ExamplesModule(Module):
    """Example module showcasing dskity's transport clients and event bus."""

    meta: ModuleMeta = field(
        default_factory=lambda: ModuleMeta(name="examples", base_path="/examples")
    )

    # ── Settings ──────────────────────────────────────────────────────────────

    def additional_settings_model(self):
        return ExamplesSettings

    # ── Lifecycle ─────────────────────────────────────────────────────────────

    async def on_startup(self, clients: TransportClients) -> None:
        """Subscribe to bus events and announce module readiness.

        ``clients`` here is the fully-initialised one from lifespan —
        ``clients.events`` is never None in this method.
        """
        log = clients.get_logger(self.meta.name)

        if clients.events is not None:
            clients.events.on("examples.factorial_computed", _on_factorial_requested)
            log.info("examples: subscribed to 'examples.factorial_computed'")
            await clients.events.emit("examples.started", {"module": self.meta.name})

    async def on_shutdown(self, clients: TransportClients) -> None:
        """Deregister event handlers and announce shutdown."""
        log = clients.get_logger(self.meta.name)

        if clients.events is not None:
            clients.events.off("examples.factorial_computed", _on_factorial_requested)
            await clients.events.emit("examples.stopped", {"module": self.meta.name})
            log.info("examples: deregistered event handlers")

    # ── Routes ────────────────────────────────────────────────────────────────

    def register(self, clients: TransportClients, config: DSkitySettings) -> None:
        router = APIRouter(prefix=self.meta.base_path, tags=[self.meta.name])
        log = clients.get_logger(self.meta.name)

        module_cfg = config.modules.ensure(self.meta.name)
        settings: ExamplesSettings = getattr(
            module_cfg, "additional_settings", ExamplesSettings()
        )

        # ------------------------------------------------------------------
        # GET /examples/factorial/{n}
        #
        # Tries to call itself recursively through the service registry.
        # Falls back to local (in-process) computation when:
        #   - The service is not yet registered (no URL resolved), or
        #   - No shared HTTP client is available (e.g. running in tests).
        # ------------------------------------------------------------------
        @router.get("/factorial/{n}", summary="Compute n! (with service-discovery demo)")
        async def factorial(n: int, request: Request) -> dict:
            if n < 0:
                raise ProblemDetail(
                    status=422,
                    title="Invalid input",
                    detail=f"n must be >= 0, got {n}",
                    instance=str(request.url),
                )

            if n > settings.factorial_max:
                raise ProblemDetail(
                    status=422,
                    title="Input too large",
                    detail=(
                        f"n={n} exceeds the configured maximum of {settings.factorial_max}. "
                        "Adjust examples.factorial_max in settings.yaml."
                    ),
                    instance=str(request.url),
                )

            # Read live resources from app.state — NOT from `clients`,
            # which was frozen before the lifespan ran.
            http_client = getattr(request.app.state, "http_client", None)
            event_bus = getattr(request.app.state, "event_bus", None)

            result, via = await _compute_factorial(
                n=n,
                request=request,
                http_client=http_client,
                log=log,
            )

            # Emit a bus event so other modules can react (caching, analytics, …)
            if event_bus is not None and settings.emit_events:
                await event_bus.emit(
                    "examples.factorial_computed", {"n": n, "result": result}
                )
                log.debug("emitted examples.factorial_computed for n=%d", n)

            return {"n": n, "result": result, "via": via}

        # ------------------------------------------------------------------
        # POST /examples/events/emit
        # Emit an arbitrary event on the bus — useful for integration tests
        # and demonstrating module-to-module messaging.
        # ------------------------------------------------------------------
        @router.post("/events/emit", summary="Emit an event on the in-process event bus")
        async def emit_event(body: _EmitRequest, request: Request) -> dict:
            event_bus = getattr(request.app.state, "event_bus", None)
            if event_bus is None:
                raise ProblemDetail(
                    status=503,
                    title="Event bus unavailable",
                    detail="The in-process event bus has not been initialised.",
                )

            count = await event_bus.emit(body.event, body.data)
            log.info("event '%s' emitted, %d handler(s) called", body.event, count)
            return {"event": body.event, "handlers_called": count}

        # ------------------------------------------------------------------
        # GET /examples/events
        # Introspect which events have registered handlers.
        # ------------------------------------------------------------------
        @router.get("/events", summary="List events with registered handlers on the bus")
        async def list_events(request: Request) -> dict:
            event_bus = getattr(request.app.state, "event_bus", None)
            if event_bus is None:
                return {"events": []}

            return {
                "events": [
                    {"name": e, "handler_count": event_bus.handler_count(e)}
                    for e in sorted(event_bus.list_events())
                ]
            }

        clients.http.include_router(router)  # type: ignore[union-attr]
        log.info("examples module registered routes under %s", self.meta.base_path)


# ── Helpers ───────────────────────────────────────────────────────────────────

async def _compute_factorial(
    n: int,
    request: Request,
    http_client,
    log: logging.Logger,
) -> tuple[int, str]:
    """Compute n! — tries remote (service-discovery) first, falls back to local.

    Returns a tuple of (result, via) where via is "remote" or "local".
    """
    if n <= 1:
        return 1, "local"

    # Attempt remote recursive call only when we have both a shared HTTP client
    # and a resolvable service URL. This demonstrates service discovery; the
    # local fallback ensures the route still works in development and tests.
    self_url: str | None = None
    try:
        self_url = request.app.modules.get("examples")  # type: ignore[attr-defined]
    except Exception:
        pass

    if http_client is not None and self_url:
        next_url = f"{self_url}/factorial/{n - 1}"
        request_id = getattr(request.state, "request_id", "-")
        headers = {"x-request-id": request_id}
        log.debug("remote call → %s", next_url)

        try:
            resp = await http_client.get(next_url, headers=headers)
            resp.raise_for_status()
            sub = resp.json()
            return n * sub["result"], "remote"
        except Exception as exc:
            log.warning("remote call failed (%s); falling back to local computation", exc)

    # Local iterative fallback — always correct, no external dependencies.
    log.debug("computing factorial(%d) locally", n)
    return math.factorial(n), "local"


# ── Event handler ─────────────────────────────────────────────────────────────

async def _on_factorial_requested(data: dict) -> None:
    """Handle factorial computation requests emitted by other modules."""
    logger.info("examples: received 'examples.factorial_requested' for n=%s", data.get("n"))


# ── Schemas ───────────────────────────────────────────────────────────────────

class _EmitRequest(BaseModel):
    event: str = Field(..., description="Event name to emit.")
    data: dict = Field(default_factory=dict, description="Payload forwarded to all handlers.")


# ── Entry-point ───────────────────────────────────────────────────────────────

def get_module() -> Module:
    return ExamplesModule()
