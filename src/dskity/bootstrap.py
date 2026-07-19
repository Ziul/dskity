from __future__ import annotations

import os
import sys
import logging
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any
from uuid import uuid4

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from dskity.config.loader import load_config
from dskity.config.settings import DSkitySettings, hydrate_module_additional_settings
from dskity.errors import install_error_handlers
from dskity.health import install_health_checks
from dskity.kvstore.backends import backend_from_config, generate_node_id
from dskity.security_headers import SecurityHeadersMiddleware
from dskity.transport.http_client import HttpClientManager
from dskity.events import EventBus
from dskity.metrics import install_metrics
from dskity.modules.registry import ModuleRegistry
from dskity.modules.contracts import TransportClients
from dskity.transport.mqtt import get_mqtt_client, shutdown_mqtt_client
from dskity.transport.grpc import GRPCClient
from dskity.modules.modules_resolver import ModulesResolver
from dskity.network import update_runtime_host_port
from dskity.request_id import install_request_id
from dskity.registry.api import router as registry_router
from dskity.registry.heartbeat import HeartbeatConfig, start_heartbeat, stop_heartbeat
from dskity.registry.middleware import EnabledModuleInfo, RegistryAdvertiseASGIMiddleware
from dskity.registry.store import RegistryStore


logger = logging.getLogger(__name__)


def _topological_sort(modules: list) -> list:
    """Sort modules by depends_on, raising RuntimeError on cycles.

    Modules without depends_on or with unknown dependencies maintain
    their relative discovery order.
    """
    by_name = {m.meta.name: m for m in modules}
    enabled_names = set(by_name)

    # Warn about missing dependencies (not enabled / not discovered).
    for mod in modules:
        for dep in getattr(mod.meta, "depends_on", ()):
            if dep not in enabled_names:
                logger.warning(
                    "Module '%s' depends on '%s' which is not enabled; skipping dependency.",
                    mod.meta.name,
                    dep,
                )

    # Kahn's algorithm for topological ordering.
    in_degree: dict[str, int] = {m.meta.name: 0 for m in modules}
    adjacency: dict[str, list[str]] = {m.meta.name: [] for m in modules}

    for mod in modules:
        for dep in getattr(mod.meta, "depends_on", ()):
            if dep in enabled_names:
                adjacency[dep].append(mod.meta.name)
                in_degree[mod.meta.name] += 1

    queue = [name for name, deg in in_degree.items() if deg == 0]
    sorted_names: list[str] = []

    while queue:
        name = queue.pop(0)
        sorted_names.append(name)
        for dependent in adjacency[name]:
            in_degree[dependent] -= 1
            if in_degree[dependent] == 0:
                queue.append(dependent)

    if len(sorted_names) != len(modules):
        cycle_nodes = {n for n, d in in_degree.items() if d > 0}
        raise RuntimeError(
            f"Circular dependency detected among modules: {sorted(cycle_nodes)}"
        )

    return [by_name[name] for name in sorted_names]


def _resolve_app_init_dir(config_path: str | None) -> Path:
    if not config_path:
        return Path.cwd().resolve()

    cfg_path = Path(config_path).expanduser()
    if not cfg_path.is_absolute():
        cfg_path = Path.cwd() / cfg_path
    return cfg_path.resolve().parent


def _resolve_modules_search_paths(config: DSkitySettings, config_path: str | None) -> list[Path]:
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


def _resolve_modules_import_packages(config: DSkitySettings) -> list[str]:
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
    app.title = config.name if config and config.name else app.title

    # Make MQTT client_id unique by appending UUID
    if config and config.common and config.common.mqtt and config.common.mqtt.enabled:
        config.common.mqtt.client_id = (
            f"{config.common.mqtt.client_id}-{uuid4().hex[:8]}"
        )
        app.state.logger.debug(
            "Generated unique MQTT client_id: %s", config.common.mqtt.client_id
        )

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

    # RFC 7807 global error handlers.
    install_error_handlers(app)

    # Built-in health checks (/health/live, /health/ready).
    health_cfg = config.common.health if config and config.common else None
    if health_cfg is None or health_cfg.enabled:
        path_prefix = health_cfg.path_prefix if health_cfg else "/health"
        install_health_checks(app, path_prefix=path_prefix)

    # CORS middleware (optional, based on config).
    if config and config.common and config.common.cors and config.common.cors.enabled:
        cors = config.common.cors
        app.add_middleware(
            CORSMiddleware,
            allow_origins=cors.allow_origins,
            allow_methods=cors.allow_methods,
            allow_headers=cors.allow_headers,
            allow_credentials=cors.allow_credentials,
            max_age=cors.max_age,
        )
        logger.debug("CORS middleware enabled with origins: %s", cors.allow_origins)

    # Security headers middleware (optional, based on config).
    if config and config.common and config.common.security_headers.enabled:
        app.add_middleware(
            SecurityHeadersMiddleware,
            settings=config.common.security_headers,
        )
        logger.debug("Security headers middleware enabled")

    # Module resolver: allows getting the URL of a module by name.
    # E.g.: request.app.modules.get("echo") -> URL (random among instances)
    app.modules = ModulesResolver(app)  # type: ignore[attr-defined]

    # Initialize MQTT client singleton (optional, based on config)
    async def _initialize_mqtt():
        """Initialize MQTT client based on configuration."""
        if (
            config
            and config.common
            and config.common.mqtt
            and config.common.mqtt.enabled
        ):
            try:
                logger.debug("MQTT enabled in config; initializing MQTT client...")
                mqtt_client = await get_mqtt_client(config.common.mqtt)
                await mqtt_client.start()
                app.state.mqtt_client = mqtt_client

                post_start_hooks = getattr(app.state, "mqtt_post_start_hooks", [])
                for hook in post_start_hooks:
                    await hook(mqtt_client)
            except ImportError:
                # MQTT habilitado, mas dependência ausente.
                raise
            except Exception as e:
                # O loop de reconexão roda no cliente; aqui registramos falha inicial.
                logger.error("Failed to initialize MQTT client: %s", e)
            logger.info("MQTT client initialization complete.")

    async def _shutdown_mqtt():
        """Shutdown MQTT client on app shutdown."""
        if hasattr(app.state, "mqtt_client"):
            logger.info("Shutting down MQTT client...")
            await shutdown_mqtt_client()

    @app.middleware("http")
    async def _modules_resolver_middleware(request, call_next):
        update_runtime_host_port(request.app, request.scope)
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
        advertise_url = None
    app.state.advertise_url = (
        advertise_url.rstrip("/")
        if isinstance(advertise_url, str) and advertise_url
        else None
    )

    # Cache local IP once during bootstrap to avoid per-request socket creation.
    if not app.state.advertise_url:
        from dskity.network import get_local_ip
        app.state.local_ip = get_local_ip()
    else:
        app.state.local_ip = None

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
            app.state.logger.debug(
                f"Attempting to discover modules in package '{package}'..."
            )
            package_registry = ModuleRegistry.from_package(package)
        except ModuleNotFoundError:
            app.state.logger.debug(f"Module not found in package '{package}'...")
            continue

        for module in package_registry.modules:
            discovered_by_name.setdefault(module.meta.name, module)

    if not discovered_by_name:
        app.state.logger.debug(
            "No modules found in modules_search_paths=%s.",
            modules_import_packages,
        )

    registry = ModuleRegistry(modules=tuple(discovered_by_name.values()))
    if target_modules:
        # Include dependencies of requested targets (transitive closure).
        # Even if a dependency is disabled in settings, honor it when explicitly
        # requested as part of a target dependency chain.
        desired: set[str] = set(target_modules)
        # Map for quick lookup
        by_name = {m.meta.name: m for m in registry.modules}
        # Expand closure
        added = True
        while added:
            added = False
            for name in list(desired):
                mod = by_name.get(name)
                if not mod:
                    continue
                for dep in getattr(mod.meta, "depends_on", ()):  # type: ignore[attr-defined]
                    if dep and dep not in desired:
                        desired.add(dep)
                        added = True

        # Warn about missing dependencies not discovered
        for name in list(desired):
            if name not in by_name:
                logger.warning(
                    "Requested module '%s' or its dependency was not discovered; skipping: %s",
                    name,
                    name,
                )

        enabled_modules = [m for m in registry.modules if m.meta.name in desired]
        app.state.target_modules = sorted(desired)
    else:
        enabled_modules = list(registry.enabled_modules(config))

    # Topological sort: respect depends_on declarations.
    enabled_modules = _topological_sort(enabled_modules)

    loaded_module_names = [m.meta.name for m in enabled_modules]
    if loaded_module_names:
        app.state.logger.info(
            "Modules loaded successfully in API: %s", loaded_module_names
        )
    else:
        app.state.logger.warning(
            "No enabled modules were loaded into the API; modules_search_paths=%s",
            app.state.modules_import_packages,
        )

    app.state.enabled_modules = [
        EnabledModuleInfo(name=m.meta.name, base_path=m.meta.base_path)
        for m in enabled_modules
    ]

    # Create an object grouping transport clients available to modules.
    # Ensure an in-process EventBus exists early so modules can use it during register().
    if not hasattr(app.state, "event_bus") or getattr(app.state, "event_bus") is None:
        app.state.event_bus = EventBus()
    _event_bus_early = getattr(app.state, "event_bus")

    # Note: mqtt_client will be initialized in lifespan, so use getattr for safety
    mqtt_client = getattr(app.state, "mqtt_client", None)
    grpc_client = GRPCClient()
    clients = TransportClients(http=app, grpc=grpc_client, mqtt=mqtt_client, events=_event_bus_early)

    for module in enabled_modules:
        module_cfg = config.modules.ensure(module.meta.name)
        hydrate_module_additional_settings(module, module_cfg)
        module.register(clients=clients, config=config)

    # Store enabled module instances for lifecycle hooks.
    app.state.enabled_modules_instances = enabled_modules

    # Setup combined lifespan: MQTT initialization + Registry heartbeat (if enabled)
    registry_enabled = getattr(app.state, "registry_store", None) is not None

    if registry_enabled:
        app.include_router(registry_router)
        app.add_middleware(RegistryAdvertiseASGIMiddleware, interval_seconds=10.0)

    @asynccontextmanager
    async def _combined_lifespan(inner_app: FastAPI):
        """
        Combined lifespan handler:
        1. Initialize MQTT client (if enabled) - will auto-reconnect if disconnected
        2. Call on_startup() for modules that define it (in registration order)
        3. Start registry heartbeat (if registry enabled)
        4. Clean up on shutdown (reverse order for on_shutdown)
        """
        import time as _time

        logger.info(
            "Starting application lifespan: initializing MQTT and registry heartbeat..."
        )
        await _initialize_mqtt()

        # Start shared HTTP client
        _http_client_settings = (
            config.common.http_client if config and config.common else None
        )
        _http_client_manager = HttpClientManager(
            timeout=_http_client_settings.timeout_seconds if _http_client_settings else 10.0,
            max_connections=_http_client_settings.max_connections if _http_client_settings else 100,
            max_keepalive_connections=_http_client_settings.max_keepalive_connections if _http_client_settings else 20,
        )
        await _http_client_manager.start()
        inner_app.state.http_client = _http_client_manager

        # Initialize or reuse in-process event bus
        _event_bus = getattr(inner_app.state, "event_bus", None)
        if _event_bus is None:
            _event_bus = EventBus()
            inner_app.state.event_bus = _event_bus

        # Rebuild clients with potentially initialized MQTT client and http client manager
        _mqtt = getattr(inner_app.state, "mqtt_client", None)
        _startup_clients = TransportClients(
            http=inner_app,
            grpc=grpc_client,
            mqtt=_mqtt,
            http_client=_http_client_manager,
            events=_event_bus,
        )

        # Call on_startup hooks in registration order
        for _mod in enabled_modules:
            if hasattr(_mod, "on_startup"):
                _t0 = _time.monotonic()
                try:
                    await _mod.on_startup(_startup_clients)
                    logger.info(
                        "on_startup(%s) completed in %.3fs",
                        _mod.meta.name,
                        _time.monotonic() - _t0,
                    )
                except Exception as _exc:
                    logger.exception(
                        "on_startup(%s) raised an error (continuing): %s",
                        _mod.meta.name,
                        _exc,
                    )

        try:
            # Start registry heartbeat if enabled
            if registry_enabled:
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
                # Stop registry heartbeat
                if registry_enabled:
                    await stop_heartbeat(inner_app)
        finally:
            # Call on_shutdown hooks in reverse registration order
            for _mod in reversed(enabled_modules):
                if hasattr(_mod, "on_shutdown"):
                    _t0 = _time.monotonic()
                    try:
                        await _mod.on_shutdown(_startup_clients)
                        logger.info(
                            "on_shutdown(%s) completed in %.3fs",
                            _mod.meta.name,
                            _time.monotonic() - _t0,
                        )
                    except Exception as _exc:
                        logger.exception(
                            "on_shutdown(%s) raised an error (continuing): %s",
                            _mod.meta.name,
                            _exc,
                        )

            # Shutdown MQTT last
            await _shutdown_mqtt()

            # Shutdown shared HTTP client
            await _http_client_manager.stop()

    app.router.lifespan_context = _combined_lifespan

    @app.get("/")
    def root() -> dict:
        enabled = [m.meta.name for m in enabled_modules]
        return {"service": config.name, "enabled_modules": enabled}

    # Correlation id per request (X-Request-Id).
    # Must be the last middleware added to be the outermost and cover
    # HTTP middlewares (BaseHTTPMiddleware), ensuring request_id in access logs.
    install_request_id(app)
