from __future__ import annotations

from dataclasses import dataclass
from typing import Callable

import socket
from fastapi import Request
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import Response

from dskity.registry.service_registry import ServiceRegistry


@dataclass(frozen=True)
class EnabledModuleInfo:
    name: str
    base_path: str


class RegistryAdvertiseMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next: Callable) -> Response:
        response = await call_next(request)

        store = getattr(request.app.state, "registry_store", None)
        enabled = getattr(request.app.state, "enabled_modules", None)
        instance_id = getattr(request.app.state, "instance_id", None)
        logger = getattr(request.app.state, "logger", None)
        if store is None or enabled is None or not instance_id:
            return response

        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        ip = s.getsockname()[0]
        port = request.url.port or 80
        base_url = f"http://{ip}:{port}".rstrip("/")
        if logger:
            logger.debug(
                f"Determined base_url as {base_url} for service registry advertisement with id {request.state.request_id}."
            )

        registry = ServiceRegistry(store=store)

        ttl_seconds = int(getattr(request.app.state, "registry_ttl_seconds", 60))

        for mod in enabled:
            registry.register_instance(
                service=mod.name,
                instance_id=instance_id,
                base_url=base_url,
                route=mod.base_path,
                ttl_seconds=ttl_seconds,
            )

        return response
