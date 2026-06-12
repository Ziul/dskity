from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass

from fastapi import FastAPI

from dskity.registry.service_registry import ServiceRegistry


@dataclass(frozen=True)
class HeartbeatConfig:
    ttl_seconds: int
    interval_seconds: int


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
    """Stop the heartbeat task and deregister all modules from the registry."""
    # Deregister all modules before stopping the heartbeat task
    store = getattr(app.state, "registry_store", None)
    instance_id = getattr(app.state, "instance_id", None)
    enabled = getattr(app.state, "enabled_modules", None)

    if store is not None and instance_id and enabled:
        reg = ServiceRegistry(store=store)
        for mod in enabled:
            try:
                reg.deregister_instance(service=mod.name, instance_id=instance_id)
            except Exception as exc:
                import logging as _logging
                _logging.getLogger(__name__).warning(
                    "Failed to deregister service=%s instance=%s: %s",
                    mod.name,
                    instance_id,
                    exc,
                )

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
