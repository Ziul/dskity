from __future__ import annotations

from fastapi import FastAPI
import pytest

from dskity.config.settings import DSkitySettings
from dskity.kvstore.backends import InMemoryKVBackend
from dskity.modules.modules_resolver import ModulesResolver
from dskity.registry.middleware import EnabledModuleInfo
from dskity.registry.service_registry import ServiceRegistry
from dskity.registry.store import RegistryStore

import dskity.registry.service_registry as service_registry_mod


def test_modules_resolver_fallback_uses_internal_base_url_and_base_path() -> None:
    app = FastAPI()
    app.state.config = {"common": {"internal_base_url": "http://127.0.0.1:8000"}}
    app.state.enabled_modules = [
        EnabledModuleInfo(name="health", base_path="/health"),
    ]

    resolver = ModulesResolver(app)

    assert resolver.urls("health")[0][:7] == "http://"


def test_modules_resolver_fallback_uses_configured_module_url_when_registry_is_empty() -> (
    None
):
    app = FastAPI()
    app.state.config = {
        "modules": {
            "echo": {
                "url": "http://10.0.0.10:8000/echo",
            }
        }
    }

    store = RegistryStore(backend=InMemoryKVBackend())
    app.state.registry_store = store

    resolver = ModulesResolver(app)
    assert resolver.urls("echo") == ["http://10.0.0.10:8000/echo"]
    assert resolver.get("echo") == "http://10.0.0.10:8000/echo"


def test_modules_resolver_prefers_registry_store_instances() -> None:
    app = FastAPI()
    app.state.config = {"common": {"internal_base_url": "http://127.0.0.1:8000"}}
    app.state.enabled_modules = [
        EnabledModuleInfo(name="health", base_path="/health"),
    ]

    store = RegistryStore(backend=InMemoryKVBackend())
    app.state.registry_store = store

    fixed_now = 1_700_000_000
    service_registry_mod.time.time = lambda: float(fixed_now)  # type: ignore[assignment]

    reg = ServiceRegistry(store=store)
    reg.register_instance(
        service="health",
        instance_id="node-1",
        base_url="http://10.0.0.1:9000",
        route="/health",
        ttl_seconds=60,
        now=fixed_now,
    )

    resolver = ModulesResolver(app)
    assert resolver.urls("health") == ["http://10.0.0.1:9000/health"]


def test_modules_resolver_get_is_stochastic_but_returns_valid_instance() -> None:
    app = FastAPI()
    app.state.config = {"common": {"internal_base_url": "http://127.0.0.1:8000"}}
    app.state.enabled_modules = [EnabledModuleInfo(name="health", base_path="/health")]

    store = RegistryStore(backend=InMemoryKVBackend())
    app.state.registry_store = store

    fixed_now = 1_700_000_000
    service_registry_mod.time.time = lambda: float(fixed_now)  # type: ignore[assignment]

    reg = ServiceRegistry(store=store)
    reg.register_instance(
        service="health",
        instance_id="node-1",
        base_url="http://10.0.0.1:9000",
        route="/health",
        ttl_seconds=60,
        now=fixed_now,
    )
    reg.register_instance(
        service="health",
        instance_id="node-2",
        base_url="http://10.0.0.2:9000",
        route="/health",
        ttl_seconds=60,
        now=fixed_now,
    )

    resolver = ModulesResolver(app)
    urls = resolver.urls("health")
    chosen = resolver.get("health")

    assert urls == ["http://10.0.0.1:9000/health", "http://10.0.0.2:9000/health"]
    assert chosen in urls


def test_modules_resolver_fallback_prefers_runtime_state_over_env(monkeypatch: pytest.MonkeyPatch) -> None:
    app = FastAPI()
    app.state.config = {}
    app.state.runtime_host = "127.0.0.1"
    app.state.runtime_port = 9123

    monkeypatch.setenv("DSKITY_HOST", "10.1.1.10")
    monkeypatch.setenv("DSKITY_PORT", "4555")

    resolver = ModulesResolver(app)
    assert resolver.urls("echo") == ["http://127.0.0.1:9123"]


def test_modules_resolver_prefers_dskity_settings_module_url_as_first_priority() -> None:
    app = FastAPI()
    app.state.config = DSkitySettings.model_validate(
        {
            "modules": {
                "echo": {
                    "url": "http://10.9.9.9:8000/echo",
                }
            }
        }
    )

    store = RegistryStore(backend=InMemoryKVBackend())
    app.state.registry_store = store

    fixed_now = 1_700_000_000
    service_registry_mod.time.time = lambda: float(fixed_now)  # type: ignore[assignment]

    reg = ServiceRegistry(store=store)
    reg.register_instance(
        service="echo",
        instance_id="node-1",
        base_url="http://10.0.0.1:9000",
        route="/echo",
        ttl_seconds=60,
        now=fixed_now,
    )

    resolver = ModulesResolver(app)
    assert resolver.urls("echo") == ["http://10.9.9.9:8000/echo"]


def test_modules_resolver_normalizes_app_state_config_to_dskity_settings() -> None:
    app = FastAPI()
    app.state.config = {"modules": {"echo": {"url": "http://127.0.0.1:8001/echo"}}}

    resolver = ModulesResolver(app)
    _ = resolver.urls("echo")

    assert isinstance(app.state.config, DSkitySettings)
