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

        # Apenas entradas com aparência de caminho de filesystem entram no sys.path.
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

    # Salva config no app.state para acesso posterior
    app.state.config = config

    targets_env = os.getenv("DSKITY_TARGETS")
    target_modules: set[str] | None = None
    if isinstance(targets_env, str) and targets_env.strip():
        parts = [p.strip() for p in targets_env.split(",")]
        target_modules = {p for p in parts if p}

    # Disponibiliza a configuração completa em runtime.
    # Útil para handlers/middlewares e módulos que precisem consultar settings depois do bootstrap.
    app.state.config = config
    app.state.config_path = config_path

    # Métricas Prometheus (HTTP) + endpoint /metrics.
    install_metrics(app)

    # Resolver de módulos: permite obter URL de um módulo por nome.
    # Ex.: request.app.modules.get("echo") -> URL (random entre instâncias)
    app.modules = ModulesResolver(app)  # type: ignore[attr-defined]

    @app.middleware("http")
    async def _modules_resolver_middleware(request, call_next):
        # Garante que o resolver exista na instância do app em runtime.
        if not hasattr(request.app, "modules"):
            request.app.modules = ModulesResolver(request.app)  # type: ignore[attr-defined]
        return await call_next(request)

    # advertise_url: URL publicada no discovery (separada do listen host/port).
    # config agora é DSkitySettings (Pydantic model), não um dict
    # NOTA: Se não configurado explicitamente, não definimos advertise_url com fallback de porta.
    # O heartbeat e middleware cuidam do registro com a porta correta.
    if config.common.advertise_url:
        advertise_url = config.common.advertise_url
    else:
        # s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        # s.connect(("8.8.8.8", 80))
        # ip = s.getsockname()[0]
        # port = app.state.listen_port if hasattr(app.state, "listen_port") else 8000
        # advertise_url = f"http://{ip}:{port}".rstrip("/")
        advertise_url = None
    app.state.advertise_url = advertise_url.rstrip("/") if isinstance(advertise_url, str) and advertise_url else None

    # Acessa registry config via atributos do Pydantic model
    if config and config.common.registry:
        app.state.registry_ttl_seconds = config.common.registry.ttl_seconds or 60
        app.state.registry_heartbeat_interval_seconds = config.common.registry.heartbeat_interval_seconds or max(
            10, app.state.registry_ttl_seconds // 2
        )
    else:
        app.state.registry_ttl_seconds = 60
        app.state.registry_heartbeat_interval_seconds = 30

    # Identidade desta instância (processo) para discovery.
    app.state.instance_id = generate_node_id()

    # Inicializa um store compartilhável para service discovery (registry).
    # Padrão desejado (estilo Loki/Cortex): o registry é um recurso de core e pode estar
    # habilitado mesmo que o módulo `kvstore` (API HTTP /kv) esteja desabilitado.
    #
    # Compat: se `common.registry.enabled` não estiver setado, usamos o valor antigo de `kvstore.enabled`.
    # config agora é DSkitySettings (Pydantic model)

    # Para compatibilidade com código antigo que usava modules["kvstore"],
    # verifica se há config e acessa via atributos Pydantic
    registry_cfg = config.common.registry if config and config.common else None
    legacy_registry_enabled = False  # Já não há módulo 'kvstore' em novo código

    registry_enabled = bool(registry_cfg.enabled) if registry_cfg else legacy_registry_enabled
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
            "Nenhum módulo encontrado em modules_search_paths=%s.",
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
        logger.info("Módulos carregados com sucesso na API: %s", loaded_module_names)
    else:
        logger.warning(
            "Nenhum módulo habilitado foi carregado na API; modules_search_paths=%s",
            app.state.modules_import_packages,
        )

    app.state.enabled_modules = [
        EnabledModuleInfo(name=m.meta.name, base_path=m.meta.base_path) for m in enabled_modules
    ]

    for module in enabled_modules:
        # Preparação para gRPC: quando habilitarmos gRPC no core, passaremos um
        # grpc.aio.Server real aqui. Por enquanto, mantém None.
        module.register(app=app, config=config, grpc_server=None)

    # Se houver um store compartilhável (kvstore habilitado), expõe endpoints de discovery
    # e auto-registra os módulos usando base_url inferido a partir das requests.
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

    # Correlation id por request (X-Request-Id).
    # Precisa ser o último middleware adicionado para ficar mais externo e cobrir
    # também os middlewares HTTP (BaseHTTPMiddleware), garantindo request_id nos access logs.
    install_request_id(app)
