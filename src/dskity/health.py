"""Built-in health check routes for DSkity.

Provides:
  GET <path_prefix>/live   — liveness probe (always 200)
  GET <path_prefix>/ready  — readiness probe (checks infrastructure and custom checks)
"""

from __future__ import annotations

import logging
from typing import Any, Callable, Awaitable

from fastapi import FastAPI
from fastapi.responses import JSONResponse

logger = logging.getLogger(__name__)

ReadinessCheck = Callable[[], Awaitable[bool]]


def install_health_checks(app: FastAPI, *, path_prefix: str = "/health") -> None:
    """Register liveness and readiness routes on the FastAPI app."""

    prefix = path_prefix.rstrip("/")

    # Initialise the readiness checks registry in app state if absent.
    if not hasattr(app.state, "readiness_checks"):
        app.state.readiness_checks = {}

    @app.get(f"{prefix}/live", tags=["health"], include_in_schema=True)
    async def liveness() -> dict[str, str]:
        """Liveness probe — always returns 200 OK."""
        return {"status": "ok"}

    @app.get(f"{prefix}/ready", tags=["health"], include_in_schema=True)
    async def readiness() -> JSONResponse:
        """Readiness probe — checks infrastructure and custom module checks."""
        checks: dict[str, Any] = {}
        all_ok = True

        # Built-in: KV backend check
        kvstore_backend = getattr(app.state, "kvstore_backend", None)
        if kvstore_backend is not None:
            try:
                kvstore_backend.keys(prefix="__health_ping__")
                checks["kvstore"] = "ok"
            except Exception as exc:
                logger.warning("KV backend health check failed: %s", exc)
                checks["kvstore"] = "error"
                all_ok = False

        # Built-in: MQTT check
        mqtt_client = getattr(app.state, "mqtt_client", None)
        if mqtt_client is not None:
            try:
                connected = getattr(mqtt_client, "is_connected", lambda: False)()
                checks["mqtt"] = "ok" if connected else "error"
                if not connected:
                    all_ok = False
            except Exception as exc:
                logger.warning("MQTT health check failed: %s", exc)
                checks["mqtt"] = "error"
                all_ok = False

        # Custom checks registered by modules
        custom_checks: dict[str, ReadinessCheck] = getattr(app.state, "readiness_checks", {})
        for name, check_fn in custom_checks.items():
            try:
                result = await check_fn()
                checks[name] = "ok" if result else "error"
                if not result:
                    all_ok = False
            except Exception as exc:
                logger.warning("Readiness check '%s' raised: %s", name, exc)
                checks[name] = "error"
                all_ok = False

        status = "ok" if all_ok else "degraded"
        return JSONResponse(
            status_code=200 if all_ok else 503,
            content={"status": status, "checks": checks},
        )
