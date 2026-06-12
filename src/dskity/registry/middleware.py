from __future__ import annotations

import logging
import time
from dataclasses import dataclass
from typing import Any

from dskity.network import get_local_ip
from dskity.registry.service_registry import ServiceRegistry

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class EnabledModuleInfo:
    """Lightweight descriptor for a registered module instance."""

    name: str
    base_path: str


class RegistryAdvertiseASGIMiddleware:
    """Pure ASGI middleware that advertises this instance in the service registry.

    Throttled to avoid re-registering on every request (at most once per
    ``interval_seconds`` seconds). Handles WebSocket and non-HTTP scopes
    transparently, without buffering response bodies.
    """

    def __init__(self, app: Any, *, interval_seconds: float = 10.0) -> None:
        self.app = app
        self._interval = interval_seconds
        self._last_advertise: float = 0

    async def __call__(self, scope: dict, receive: Any, send: Any) -> None:
        # Pass through all non-HTTP scopes unchanged (e.g. WebSocket, lifespan)
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        # Serve the request first — never delay the response
        await self.app(scope, receive, send)

        # Throttle: only advertise at most once per interval
        now = time.monotonic()
        if now - self._last_advertise < self._interval:
            return
        self._last_advertise = now

        # Best-effort registration — never fail the request
        try:
            app_obj = scope.get("app")
            if app_obj is None:
                return

            state = getattr(app_obj, "state", None)
            if state is None:
                return

            store = getattr(state, "registry_store", None)
            enabled = getattr(state, "enabled_modules", None)
            instance_id = getattr(state, "instance_id", None)
            if store is None or enabled is None or not instance_id:
                return

            advertise_url = getattr(state, "advertise_url", None)
            if not advertise_url:
                local_ip = getattr(state, "local_ip", None)
                if not local_ip:
                    local_ip = get_local_ip()
                    state.local_ip = local_ip
                server = scope.get("server")
                port = server[1] if server else 8000
                advertise_url = f"http://{local_ip}:{port}"

            registry = ServiceRegistry(store=store)
            ttl_seconds = int(getattr(state, "registry_ttl_seconds", 60))

            for mod in enabled:
                registry.register_instance(
                    service=mod.name,
                    instance_id=instance_id,
                    base_url=advertise_url,
                    route=mod.base_path,
                    ttl_seconds=ttl_seconds,
                )
        except Exception:
            logger.debug("Registry advertise failed (best-effort)", exc_info=True)


# Backward-compatible alias (kept for any existing code referencing the old name)
RegistryAdvertiseMiddleware = RegistryAdvertiseASGIMiddleware
