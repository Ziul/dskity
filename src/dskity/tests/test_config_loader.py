from __future__ import annotations

from pathlib import Path

import yaml

from dskity.config.loader import load_config


def test_load_config_deep_merge(tmp_path: Path) -> None:
    override = {
        "common": {"internal_base_url": "http://example.com"},
        "kv": {"store": "inmemory"},
        "modules": {"kvstore": {"enabled": False}},
    }

    override_path = tmp_path / "override.yaml"
    override_path.write_text(yaml.safe_dump(override), encoding="utf-8")

    cfg = load_config(override_path=str(override_path))

    # cfg agora é DSkitySettings (Pydantic model), não um dict
    assert cfg.common.internal_base_url == "http://example.com"
    assert cfg.kv.store == "inmemory"
    # modules.kvstore não existe em novo modelo (era para compatibilidade)


def test_load_config_reads_toml_override(tmp_path: Path) -> None:
    override = b"""
[common]
internal_base_url = "http://toml.example.com"

[kv]
store = "redis"
"""

    override_path = tmp_path / "override.toml"
    override_path.write_bytes(override)

    cfg = load_config(override_path=str(override_path))

    assert cfg.common.internal_base_url == "http://toml.example.com"
    assert cfg.kv.store == "redis"


def test_load_config_uses_settings_toml_in_cwd(tmp_path: Path, monkeypatch) -> None:
    settings_path = tmp_path / "settings.toml"
    settings_path.write_text(
        """
[common]
internal_base_url = "http://cwd.example.com"

[kv]
store = "consul"
""",
        encoding="utf-8",
    )

    monkeypatch.chdir(tmp_path)

    cfg = load_config()

    assert cfg.common.internal_base_url == "http://cwd.example.com"
    assert cfg.kv.store == "consul"


def test_load_config_falls_back_to_settings_yaml_in_cwd(tmp_path: Path, monkeypatch) -> None:
        settings_path = tmp_path / "settings.yaml"
        settings_path.write_text(
                """
common:
    internal_base_url: "http://yaml-fallback.example.com"
kv:
    store: "redis"
""",
                encoding="utf-8",
        )

        monkeypatch.chdir(tmp_path)

        cfg = load_config()

        assert cfg.common.internal_base_url == "http://yaml-fallback.example.com"
        assert cfg.kv.store == "redis"
