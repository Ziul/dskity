from __future__ import annotations

import asyncio
import socket
import time
from dataclasses import dataclass

from fastapi import FastAPI

from dskity.registry.service_registry import ServiceRegistry


@dataclass(frozen=True)
class HeartbeatConfig:
    ttl_seconds: int
    interval_seconds: int


def _get_advertise_base_url() -> str | None:
    """
    Determine the base IP via socket discovery.
    DOES NOT use a port fallback - the middleware should use request.url.port
    """
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        ip = s.getsockname()[0]
        s.close()
        return ip
    except Exception:
        return None


def start_heartbeat(app: FastAPI, *, cfg: HeartbeatConfig) -> None:
    if getattr(app.state, "registry_store", None) is None:
        return

    task: asyncio.Task | None = getattr(app.state, "_registry_heartbeat_task", None)
    if task is not None and not task.done():
        return

    async def loop() -> None:
        reg = ServiceRegistry(store=app.state.registry_store)
        # Try to use advertise_url if explicitly configured
        advertise_url = str(getattr(app.state, "advertise_url", None))

        # If there's no advertise_url, the per-request middleware will handle registration
        if not advertise_url:
            return

        while True:
            now = int(time.time())
            for mod in getattr(app.state, "enabled_modules", []):
                reg.register_instance(
                    service=mod.name,
                    instance_id=app.state.instance_id,
                    base_url=advertise_url,
                    route=mod.base_path,
                    ttl_seconds=cfg.ttl_seconds,
                    now=now,
                )
                reg.prune_expired(service=mod.name, now=now)

            await asyncio.sleep(cfg.interval_seconds)

    app.state._registry_heartbeat_task = asyncio.create_task(loop())


async def stop_heartbeat(app: FastAPI) -> None:
    task: asyncio.Task | None = getattr(app.state, "_registry_heartbeat_task", None)
    if task is None:
        return

    task.cancel()
    try:
        await task
    except asyncio.CancelledError:
        pass
    finally:
        app.state._registry_heartbeat_task = None
