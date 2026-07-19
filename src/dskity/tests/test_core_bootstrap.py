from __future__ import annotations

import sys
from pathlib import Path

from fastapi.testclient import TestClient
from pydantic import BaseModel, Field

from dskity.config.settings import DSkitySettings
from dskity.modules.registry import ModuleRegistry
import dskity.bootstrap as bootstrap_mod
from dskity.bootstrap import (
    _install_modules_search_paths,
    _resolve_modules_import_packages,
    _resolve_modules_search_paths,
)
from dskity.app import create_app


class HealthAdditionalSettings(BaseModel):
    enabled_checks: list[str] = Field(default_factory=lambda: ["live", "ready"])


class FakeModuleWithAdditionalSettings:
    def __init__(self, name: str, base_path: str) -> None:
        self.meta = type("Meta", (), {"name": name, "base_path": base_path})()

    def additional_settings_model(self):
        return HealthAdditionalSettings

    def register(self, clients, config):  # noqa: ANN001
        return None


class FakeModuleWithoutAdditionalSettings:
    def __init__(self, name: str, base_path: str) -> None:
        self.meta = type("Meta", (), {"name": name, "base_path": base_path})()

    def register(self, clients, config):  # noqa: ANN001
        return None


def test_bootstrap_exposes_root_metrics_and_request_id_and_service_name() -> None:
    app = create_app()
    client = TestClient(app)

    r_root = client.get("/")
    assert "service" in r_root.json()
    assert r_root.json()["service"] == app.state.config.name == app.title
    assert r_root.status_code == 200
    assert "enabled_modules" in r_root.json()
    assert "X-Request-Id" in r_root.headers

    r_metrics = client.get("/metrics")
    assert r_metrics.status_code == 200
    assert "http_requests_total" in r_metrics.text
    assert "X-Request-Id" in r_metrics.headers


def test_resolve_modules_search_paths_includes_cwd_app_dir_and_extras(
    tmp_path: Path, monkeypatch
) -> None:
    run_dir = tmp_path / "run"
    app_dir = tmp_path / "app"
    run_dir.mkdir()
    app_dir.mkdir()

    monkeypatch.chdir(run_dir)

    cfg = DSkitySettings.model_validate(
        {"modules_search_paths": ["dskity.modules", "./services", "./plugins"]}
    )
    config_path = str(app_dir / "settings.yaml")

    paths = _resolve_modules_search_paths(cfg, config_path)
    path_strs = [str(p) for p in paths]

    assert str(run_dir.resolve()) in path_strs
    assert str(app_dir.resolve()) in path_strs
    assert str((app_dir / "services").resolve()) in path_strs
    assert str((app_dir / "plugins").resolve()) in path_strs


def test_resolve_modules_import_packages_extracts_only_package_entries() -> None:
    cfg = DSkitySettings.model_validate(
        {
            "modules_search_paths": [
                "dskity.modules",
                "custom_app.modules",
                "./services",
                "/tmp/plugins",
            ]
        }
    )

    packages = _resolve_modules_import_packages(cfg)

    assert packages == ["dskity.modules", "custom_app.modules"]


def test_install_modules_search_paths_adds_paths_to_syspath(
    tmp_path: Path, monkeypatch
) -> None:
    p1 = str((tmp_path / "p1").resolve())
    p2 = str((tmp_path / "p2").resolve())

    original = list(sys.path)
    monkeypatch.setattr(sys, "path", list(original))

    inserted = _install_modules_search_paths([Path(p1), Path(p2)])

    assert inserted == [p1, p2]
    assert p1 in sys.path
    assert p2 in sys.path


def test_bootstrap_does_not_fail_when_no_modules_are_discovered(monkeypatch) -> None:
    monkeypatch.setattr(
        bootstrap_mod.ModuleRegistry,
        "from_package",
        lambda _pkg: ModuleRegistry(modules=()),
    )

    app = create_app()
    client = TestClient(app)

    resp = client.get("/")
    assert resp.status_code == 200
    assert resp.json().get("enabled_modules") == []


def test_bootstrap_logs_loaded_modules(caplog, monkeypatch) -> None:
    class FakeModule:
        def __init__(self, name: str, base_path: str) -> None:
            self.meta = type("Meta", (), {"name": name, "base_path": base_path})()

        def register(self, clients, config):  # noqa: ANN001
            return None

    fake_registry = ModuleRegistry(
        modules=(FakeModule("health", "/health"), FakeModule("echo", "/echo"))
    )
    monkeypatch.setattr(
        bootstrap_mod.ModuleRegistry, "from_package", lambda _pkg: fake_registry
    )

    logged_messages: list[str] = []

    def fake_info(message: str, *args, **kwargs) -> None:  # noqa: ANN001
        logged_messages.append(message % args if args else message)

    monkeypatch.setattr(bootstrap_mod.logger, "info", fake_info)

    app = create_app()

    assert hasattr(app.state, "enabled_modules")
    assert [m.name for m in app.state.enabled_modules] == ["health", "echo"]


def test_bootstrap_hydrates_module_specific_additional_settings(monkeypatch) -> None:
    fake_registry = ModuleRegistry(
        modules=(FakeModuleWithAdditionalSettings("health", "/health"),)
    )
    monkeypatch.setattr(
        bootstrap_mod.ModuleRegistry, "from_package", lambda _pkg: fake_registry
    )
    monkeypatch.setattr(
        bootstrap_mod,
        "load_config",
        lambda override_path=None: DSkitySettings.model_validate(
            {
                "modules": {
                    "health": {
                        "enabled": True,
                        "additional_settings": {"enabled_checks": ["ping"]},
                    }
                }
            }
        ),
    )

    app = create_app()

    health_cfg = app.state.config.modules.health
    assert isinstance(health_cfg.additional_settings, HealthAdditionalSettings)
    assert health_cfg.additional_settings.enabled_checks == ["ping"]


def test_bootstrap_keeps_legacy_additional_settings_raw(monkeypatch) -> None:
    fake_registry = ModuleRegistry(
        modules=(FakeModuleWithoutAdditionalSettings("health", "/health"),)
    )
    monkeypatch.setattr(
        bootstrap_mod.ModuleRegistry, "from_package", lambda _pkg: fake_registry
    )
    monkeypatch.setattr(
        bootstrap_mod,
        "load_config",
        lambda override_path=None: DSkitySettings.model_validate(
            {
                "modules": {
                    "health": {
                        "enabled": True,
                        "additional_settings": {"feature_flag": True},
                    }
                }
            }
        ),
    )

    app = create_app()

    health_cfg = app.state.config.modules.health
    assert health_cfg.additional_settings == {"feature_flag": True}


def test_core_config_json_omits_none_values() -> None:
    app = create_app()
    client = TestClient(app)

    resp = client.get("/_core/config.json")

    assert resp.status_code == 200
    body = resp.json()
    assert "modules_import_path" not in body or body["modules_import_path"] is not None
    assert "modules_search_paths" in body
    assert "null" not in resp.text


def test_bootstrap_exposes_generic_module_clients_in_state() -> None:
    app = create_app()

    assert isinstance(app.state.module_clients, dict)
    enabled_names = {mod.name for mod in app.state.enabled_modules}

    for name in enabled_names:
        assert name in app.state.module_clients
        assert hasattr(app.state, f"{name}_modules")

    if "examples" in enabled_names:
        assert hasattr(app.state.examples_modules, "factorial")
