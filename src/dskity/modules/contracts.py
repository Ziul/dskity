from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any, Protocol

from fastapi import FastAPI
from fastapi.routing import APIRoute
from pydantic import BaseModel

from dskity import DSkitySettings


@dataclass(frozen=True)
class ModuleMeta:
    name: str
    base_path: str
    depends_on: tuple[str, ...] = ()


@dataclass(frozen=True)
class TransportClients:
    """Group possible transport clients a module may use.

    - `http`: the `FastAPI` instance (HTTP server) or `None`.
    - `grpc`: gRPC client/server wrapper (untyped to avoid direct dependency).
    - `mqtt`: singleton MQTT client (implementation-defined) or `None`.
    - `http_client`: shared async HTTP client manager or `None`.
    - `events`: in-process event bus or `None`.
    """

    http: FastAPI | None = None
    grpc: Any | None = None
    mqtt: Any | None = None
    http_client: Any | None = None  # HttpClientManager instance
    events: Any | None = None  # EventBus instance

    @property
    def logger(self) -> Any:
        """Convenience property to access the logger from the HTTP client if available."""
        if self.http and hasattr(self.http.state, "logger"):
            return self.http.state.logger
        import logging

        return logging.getLogger(__name__)

    def get_logger(self, module_name: str) -> Any:
        """Get a logger for a specific module, namespaced under the main logger."""
        base_logger = self.logger
        if base_logger:
            return base_logger.getChild(module_name)
        import logging

        return logging.getLogger(module_name)


class Module(Protocol):
    meta: ModuleMeta

    def additional_settings_model(self) -> type[BaseModel] | None: ...

    def register(
        self, clients: TransportClients, config: DSkitySettings
    ) -> None: ...

    def get_client(self, app: FastAPI) -> Any:
        """Build a generic async HTTP client based on this module routes."""
        return _ModuleHttpClient.from_module(app, self.meta)

    async def on_startup(self, clients: TransportClients) -> None: ...

    async def on_shutdown(self, clients: TransportClients) -> None: ...


def _iter_effective_api_routes(app: FastAPI) -> list[tuple[str, list[str], set[str]]]:
    """Yield (path, tags, methods) for every `APIRoute` registered on `app`.

    Newer FastAPI/Starlette releases (FastAPI >= ~0.142, Starlette >= ~1.7)
    include sub-routers "lazily": `app.router.routes` ends up containing
    internal `_IncludedRouter` wrapper objects instead of flattened
    `APIRoute`s, and the effective (prefixed) path/methods/tags for a route
    are only resolved on demand. `fastapi.routing.iter_route_contexts` is the
    same helper FastAPI's own OpenAPI generator uses to flatten these
    wrappers, so we reuse it here when available and fall back to the
    historical flat-list behavior on older FastAPI versions that don't have
    it (and therefore never wrap routes in the first place).
    """

    try:
        from fastapi.routing import iter_route_contexts
    except ImportError:
        iter_route_contexts = None

    if iter_route_contexts is None:
        return [
            (route.path, list(route.tags or []), set(route.methods or set()))
            for route in app.router.routes
            if isinstance(route, APIRoute)
        ]

    results: list[tuple[str, list[str], set[str]]] = []
    for route_context in iter_route_contexts(app.router.routes):
        original_route = route_context.original_route
        if not isinstance(original_route, APIRoute):
            continue
        path = route_context.path or original_route.path
        tags = list(getattr(route_context, "tags", None) or original_route.tags or [])
        methods = set(getattr(route_context, "methods", None) or original_route.methods or set())
        results.append((path, tags, methods))
    return results


@dataclass(frozen=True)
class _RouteSpec:
    name: str
    method: str
    relative_path: str
    path_params: tuple[str, ...]


@dataclass
class _ModuleHttpClient:
    app: FastAPI
    meta: ModuleMeta
    routes: tuple[_RouteSpec, ...]

    @classmethod
    def from_module(cls, app: FastAPI, meta: ModuleMeta) -> _ModuleHttpClient:
        specs: list[_RouteSpec] = []
        used_names: set[str] = set()
        method_priority = ["GET", "POST", "PUT", "PATCH", "DELETE"]

        for path, tags, route_methods in _iter_effective_api_routes(app):
            if meta.name not in tags:
                continue

            if not path.startswith(meta.base_path):
                continue

            relative_path = path[len(meta.base_path) :] or "/"
            if not relative_path.startswith("/"):
                relative_path = "/" + relative_path

            methods = [m for m in route_methods if m not in {"HEAD", "OPTIONS"}]
            if not methods:
                continue

            methods = sorted(
                methods,
                key=lambda m: method_priority.index(m) if m in method_priority else len(method_priority),
            )
            method = methods[0]

            path_params = tuple(re.findall(r"\{([^}:]+)(?::[^}]+)?\}", relative_path))
            name = _route_name(relative_path)
            if name in used_names:
                name = f"{name}_{method.lower()}"
            used_names.add(name)

            specs.append(
                _RouteSpec(
                    name=name,
                    method=method,
                    relative_path=relative_path,
                    path_params=path_params,
                )
            )

        client = cls(app=app, meta=meta, routes=tuple(specs))
        for spec in specs:
            setattr(client, spec.name, client._build_method(spec))
        return client

    def _base_url(self) -> str:
        resolver = getattr(self.app, "modules", None)
        if resolver is None:
            raise RuntimeError("Modules resolver is not available in app")

        base_url = resolver.get(self.meta.name)
        if not base_url:
            raise RuntimeError(f"Could not resolve base URL for module '{self.meta.name}'")
        return str(base_url).rstrip("/")

    def _http_client(self) -> Any:
        http_client = getattr(self.app.state, "http_client", None)
        if http_client is None:
            raise RuntimeError("Shared HTTP client is not available")
        return http_client

    def _build_method(self, spec: _RouteSpec):
        async def _method(*args: Any, headers: dict[str, str] | None = None, query: dict[str, Any] | None = None, json: Any = None, **kwargs: Any) -> Any:
            path_values: dict[str, Any] = {}
            for i, param_name in enumerate(spec.path_params):
                if i < len(args):
                    path_values[param_name] = args[i]
                    continue
                if param_name in kwargs:
                    path_values[param_name] = kwargs.pop(param_name)
                    continue
                raise TypeError(f"Missing path parameter '{param_name}' for route '{spec.name}'")

            relative_path = spec.relative_path
            for key, value in path_values.items():
                relative_path = relative_path.replace(f"{{{key}}}", str(value))

            url = f"{self._base_url()}{relative_path}"
            request_kwargs: dict[str, Any] = {}
            if headers:
                request_kwargs["headers"] = headers
            if query:
                request_kwargs["params"] = query
            if json is not None:
                request_kwargs["json"] = json

            response = await getattr(self._http_client(), spec.method.lower())(
                url,
                **request_kwargs,
            )
            response.raise_for_status()

            content_type = response.headers.get("content-type", "")
            if "application/json" in content_type:
                return response.json()
            return {"status_code": response.status_code, "text": response.text}

        _method.__name__ = spec.name
        return _method


def _route_name(relative_path: str) -> str:
    parts = [p for p in relative_path.strip("/").split("/") if p]
    if not parts:
        return "root"

    filtered = [p for p in parts if not (p.startswith("{") and p.endswith("}"))]
    if not filtered:
        filtered = ["by_path"]

    return "_".join(p.replace("-", "_") for p in filtered)

