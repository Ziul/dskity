from __future__ import annotations

import os
import sys
import logging
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

from fastapi import FastAPI

from dskity.config.loader import load_config
from dskity.kvstore.backends import backend_from_config, generate_node_id
from dskity.metrics import install_metrics
from dskity.modules.registry import ModuleRegistry
from dskity.modules.contracts import TransportClients
from dskity.transport.mqtt import MQTTClient
from dskity.transport.grpc import GRPCClient
from dskity.modules.modules_resolver import ModulesResolver
from dskity.request_id import install_request_id
from dskity.registry.api import router as registry_router
from dskity.registry.heartbeat import HeartbeatConfig, start_heartbeat, stop_heartbeat
from dskity.registry.middleware import EnabledModuleInfo, RegistryAdvertiseMiddleware
from dskity.registry.store import RegistryStore


logger = logging.getLogger(__name__)


def _resolve_app_init_dir(config_path: str | None) -> Path:
    if not config_path:
        return Path.cwd().resolve()

    cfg_path = Path(config_path).expanduser()
    if not cfg_path.is_absolute():
        cfg_path = Path.cwd() / cfg_path
    return cfg_path.resolve().parent


def _resolve_modules_search_paths(config, config_path: str | None) -> list[Path]:
    app_init_dir = _resolve_app_init_dir(config_path)

    candidates: list[Path] = [
        Path.cwd().resolve(),
        app_init_dir,
    ]

    configured_paths = getattr(config, "modules_search_paths", []) or []
    for raw_path in configured_paths:
        if not isinstance(raw_path, str):
            continue

        entry = raw_path.strip()
        if not entry:
            continue

        # Only filesystem-like entries should be added to sys.path.
        if "/" not in entry and "\\" not in entry and not entry.startswith((".", "~")):
            continue

        path = Path(entry).expanduser()
        if not path.is_absolute():
            path = app_init_dir / path
        candidates.append(path.resolve())

    seen: set[str] = set()
    resolved: list[Path] = []
    for path in candidates:
        key = str(path)
        if key in seen:
            continue
        seen.add(key)
        resolved.append(path)
    return resolved


def _install_modules_search_paths(paths: list[Path]) -> list[str]:
    ordered = [str(path) for path in paths]
    for path_str in reversed(ordered):
        if path_str not in sys.path:
            sys.path.insert(0, path_str)
    return ordered


def _is_probably_package_path(value: str) -> bool:
    if not value or "/" in value or "\\" in value or value.startswith((".", "~")):
        return False

    parts = value.split(".")
    return bool(parts) and all(part.isidentifier() for part in parts)


def _resolve_modules_import_packages(config: Any) -> list[str]:
    configured_paths = getattr(config, "modules_search_paths", []) or []
    candidates: list[str] = []
    for item in configured_paths:
        if not isinstance(item, str):
            continue
        entry = item.strip()
        if not entry or not _is_probably_package_path(entry):
            continue
        candidates.append(entry)

    seen: set[str] = set()
    packages: list[str] = []
    for package in candidates:
        if package in seen:
            continue
        seen.add(package)
        packages.append(package)
    return packages


def bootstrap(app: FastAPI) -> None:
    config_path = os.getenv("DSKITY_CONFIG")
    config = load_config(override_path=config_path)

    # Store config in app.state for later access
    app.state.config = config

    targets_env = os.getenv("DSKITY_TARGETS")
    target_modules: set[str] | None = None
    if isinstance(targets_env, str) and targets_env.strip():
        parts = [p.strip() for p in targets_env.split(",")]
        target_modules = {p for p in parts if p}

    # Make the full configuration available at runtime.
    # Useful for handlers/middlewares and modules that need to query settings after bootstrap.
    app.state.config = config
    app.state.config_path = config_path

    # Prometheus metrics (HTTP) + /metrics endpoint.
    install_metrics(app)

    # Module resolver: allows getting the URL of a module by name.
    # E.g.: request.app.modules.get("echo") -> URL (random among instances)
    app.modules = ModulesResolver(app)  # type: ignore[attr-defined]

    @app.middleware("http")
    async def _modules_resolver_middleware(request, call_next):
        # Ensure the resolver exists in the app instance at runtime.
        if not hasattr(request.app, "modules"):
            request.app.modules = ModulesResolver(request.app)  # type: ignore[attr-defined]
        return await call_next(request)

    # advertise_url: URL published to discovery (separate from listen host/port).
    # config is now DSkitySettings (Pydantic model), not a dict
    # NOTE: If not explicitly configured, we don't set advertise_url with port fallback.
    # The heartbeat and middleware handle registration with the correct port.
    if config.common.advertise_url:
        advertise_url = config.common.advertise_url
    else:
        # s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        # s.connect(("8.8.8.8", 80))
        # ip = s.getsockname()[0]
        # port = app.state.listen_port if hasattr(app.state, "listen_port") else 8000
        # advertise_url = f"http://{ip}:{port}".rstrip("/")
        advertise_url = None
    app.state.advertise_url = (
        advertise_url.rstrip("/")
        if isinstance(advertise_url, str) and advertise_url
        else None
    )

    # Access registry config via Pydantic model attributes
    if config and config.common.registry:
        app.state.registry_ttl_seconds = config.common.registry.ttl_seconds or 60
        app.state.registry_heartbeat_interval_seconds = (
            config.common.registry.heartbeat_interval_seconds
            or max(10, app.state.registry_ttl_seconds // 2)
        )
    else:
        app.state.registry_ttl_seconds = 60
        app.state.registry_heartbeat_interval_seconds = 30

    # Identity of this instance (process) for discovery.
    app.state.instance_id = generate_node_id()

    # Initialize a shareable store for service discovery (registry).
    # Desired pattern (Loki/Cortex style): registry is a core resource and can be
    # enabled even if the `kvstore` module (HTTP API /kv) is disabled.
    #
    # Compat: if `common.registry.enabled` is not set, we use the old `kvstore.enabled` value.
    # config is now DSkitySettings (Pydantic model)

    # For backward compatibility with code that used modules["kvstore"],
    # check if there is config and access via Pydantic attributes
    registry_cfg = config.common.registry if config and config.common else None
    legacy_registry_enabled = False  # No 'kvstore' module in new code

    registry_enabled = (
        bool(registry_cfg.enabled) if registry_cfg else legacy_registry_enabled
    )
    if registry_enabled:
        try:
            store_name, backend = backend_from_config(config)
        except (ValueError, NotImplementedError) as e:
            raise RuntimeError(str(e)) from e
        app.state.kvstore_backend = backend
        app.state.kvstore_store = store_name
        app.state.registry_store = RegistryStore(backend=backend)

    modules_search_paths = _resolve_modules_search_paths(config, config_path)
    app.state.modules_search_paths = _install_modules_search_paths(modules_search_paths)

    modules_import_packages = _resolve_modules_import_packages(config)
    if not modules_import_packages:
        modules_import_packages = ["dskity.modules"]
    app.state.modules_import_packages = modules_import_packages

    discovered_by_name: dict[str, Any] = {}
    for package in modules_import_packages:
        try:
            package_registry = ModuleRegistry.from_package(package)
        except ModuleNotFoundError:
            continue

        for module in package_registry.modules:
            discovered_by_name.setdefault(module.meta.name, module)

    if not discovered_by_name:
        logger.debug(
            "No modules found in modules_search_paths=%s.",
            modules_import_packages,
        )

    registry = ModuleRegistry(modules=tuple(discovered_by_name.values()))
    if target_modules:
        enabled_modules = [m for m in registry.modules if m.meta.name in target_modules]
        app.state.target_modules = sorted(target_modules)
    else:
        enabled_modules = list(registry.enabled_modules(config))

    loaded_module_names = [m.meta.name for m in enabled_modules]
    if loaded_module_names:
        logger.info("Modules loaded successfully in API: %s", loaded_module_names)
    else:
        logger.warning(
            "No enabled modules were loaded into the API; modules_search_paths=%s",
            app.state.modules_import_packages,
        )

    app.state.enabled_modules = [
        EnabledModuleInfo(name=m.meta.name, base_path=m.meta.base_path)
        for m in enabled_modules
    ]

    # Create an object grouping transport clients available to modules.
    mqtt_client = MQTTClient()  # lightweight singleton — does not auto-connect
    grpc_client = GRPCClient()
    clients = TransportClients(http=app, grpc=grpc_client, mqtt=mqtt_client)

    for module in enabled_modules:
        module.register(clients=clients, config=config)

    # If there is a shared store (kvstore enabled), expose discovery endpoints
    # and auto-register modules using a base_url inferred from requests.
    if getattr(app.state, "registry_store", None) is not None:
        app.include_router(registry_router)
        app.add_middleware(RegistryAdvertiseMiddleware)

        existing_lifespan = getattr(app.router, "lifespan_context", None)

        @asynccontextmanager
        async def _lifespan(inner_app: FastAPI):
            if callable(existing_lifespan):
                async with existing_lifespan(inner_app):
                    start_heartbeat(
                        inner_app,
                        cfg=HeartbeatConfig(
                            ttl_seconds=inner_app.state.registry_ttl_seconds,
                            interval_seconds=inner_app.state.registry_heartbeat_interval_seconds,
                        ),
                    )
                    try:
                        yield
                    finally:
                        await stop_heartbeat(inner_app)
            else:
                start_heartbeat(
                    inner_app,
                    cfg=HeartbeatConfig(
                        ttl_seconds=inner_app.state.registry_ttl_seconds,
                        interval_seconds=inner_app.state.registry_heartbeat_interval_seconds,
                    ),
                )
                try:
                    yield
                finally:
                    await stop_heartbeat(inner_app)

        app.router.lifespan_context = _lifespan

    @app.get("/")
    def root() -> dict:
        enabled = [m.meta.name for m in enabled_modules]
        return {"service": "dskity", "enabled_modules": enabled}

    # Correlation id per request (X-Request-Id).
    # Must be the last middleware added to be the outermost and cover
    # HTTP middlewares (BaseHTTPMiddleware), ensuring request_id in access logs.
    install_request_id(app)
