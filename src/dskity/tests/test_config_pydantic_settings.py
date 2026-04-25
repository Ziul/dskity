"""Testes para configuração com pydantic-settings."""

from __future__ import annotations

import os
from pathlib import Path

import yaml

from dskity.config.loader import load_config


def test_load_config_basic() -> None:
    """Testa carregamento básico da configuração."""
    cfg = load_config()

    assert cfg.common.internal_base_url == "http://127.0.0.1:8000"
    assert cfg.kv.store == "inmemory"
    assert cfg.modules_search_paths == ["dskity.modules", "modules"]
    assert cfg.modules.kvstore.enabled is True
    assert cfg.modules.kvstore.__name__ == "kvstore"
    assert cfg.modules.get("person") is None


def test_load_config_env_var_modules_search_paths() -> None:
    """Testa override da lista de caminhos de import de módulos via env var."""
    os.environ["DSKITY_MODULES_SEARCH_PATHS"] = '["custom_app.modules", "./services"]'

    try:
        cfg = load_config()
        assert cfg.modules_search_paths == ["custom_app.modules", "./services"]
    finally:
        del os.environ["DSKITY_MODULES_SEARCH_PATHS"]


def test_load_config_deep_merge(tmp_path: Path) -> None:
    """Testa deep merge de YAML override."""
    override = {
        "common": {"internal_base_url": "http://example.com"},
        "kv": {"store": "inmemory"},
        "modules": {"kvstore": {"enabled": False}},
    }

    override_path = tmp_path / "override.yaml"
    override_path.write_text(yaml.safe_dump(override), encoding="utf-8")

    cfg = load_config(override_path=str(override_path))

    assert cfg.common.internal_base_url == "http://example.com"
    assert cfg.kv.store == "inmemory"
    assert cfg.modules.kvstore.enabled is False
    assert cfg.modules.kvstore.__name__ == "kvstore"
    # Não há módulos fixos por padrão
    assert cfg.modules.get("person") is None


def test_load_config_env_var_override() -> None:
    """Testa override via variável de ambiente."""
    os.environ["DSKITY_COMMON__INTERNAL_BASE_URL"] = "http://env.example.com"

    try:
        cfg = load_config()
        assert cfg.common.internal_base_url == "http://env.example.com"
    finally:
        del os.environ["DSKITY_COMMON__INTERNAL_BASE_URL"]


def test_load_config_env_var_kv_store() -> None:
    """Testa override de kv.store via env var."""
    os.environ["DSKITY_KV__STORE"] = "redis"

    try:
        cfg = load_config()
        assert cfg.kv.store == "redis"
    finally:
        del os.environ["DSKITY_KV__STORE"]


def test_load_config_env_var_nested_person_database() -> None:
    """Testa override aninhado para person.database."""
    test_url = "postgresql://custom:pass@custom-host:5432/custom_db"
    os.environ["DSKITY_MODULES__PERSON__DATABASE__URL"] = test_url

    try:
        cfg = load_config()
        assert cfg.modules.person.database.url == test_url
        assert cfg.modules.person.__name__ == "person"
    finally:
        del os.environ["DSKITY_MODULES__PERSON__DATABASE__URL"]


def test_load_config_multiple_env_vars() -> None:
    """Testa múltiplas variáveis de ambiente simultâneamente."""
    os.environ["DSKITY_COMMON__INTERNAL_BASE_URL"] = "http://multi.test"
    os.environ["DSKITY_KV__STORE"] = "consul"
    os.environ["DSKITY_KV__REDIS__KEY_PREFIX"] = "custom_prefix"

    try:
        cfg = load_config()
        assert cfg.common.internal_base_url == "http://multi.test"
        assert cfg.kv.store == "consul"
        assert cfg.kv.redis.key_prefix == "custom_prefix"
    finally:
        del os.environ["DSKITY_COMMON__INTERNAL_BASE_URL"]
        del os.environ["DSKITY_KV__STORE"]
        del os.environ["DSKITY_KV__REDIS__KEY_PREFIX"]


def test_load_config_env_var_precedence(tmp_path: Path) -> None:
    """Testa que env vars têm precedência sobre YAML."""
    override = {
        "common": {"internal_base_url": "http://yaml.example.com"},
    }

    override_path = tmp_path / "override.yaml"
    override_path.write_text(yaml.safe_dump(override), encoding="utf-8")

    os.environ["DSKITY_COMMON__INTERNAL_BASE_URL"] = "http://env.example.com"

    try:
        cfg = load_config(override_path=str(override_path))
        # Env var deve ter precedência sobre YAML
        assert cfg.common.internal_base_url == "http://env.example.com"
    finally:
        del os.environ["DSKITY_COMMON__INTERNAL_BASE_URL"]


def test_load_config_boolean_env_var() -> None:
    """Testa variáveis booleanas."""
    os.environ["DSKITY_COMMON__REGISTRY__ENABLED"] = "false"

    try:
        cfg = load_config()
        assert cfg.common.registry.enabled is False
    finally:
        del os.environ["DSKITY_COMMON__REGISTRY__ENABLED"]


def test_load_config_integer_env_var() -> None:
    """Testa variáveis inteiras."""
    os.environ["DSKITY_KV__DEFAULT_TTL_SECONDS"] = "120"
    os.environ["DSKITY_KV__RING__VNODES"] = "128"

    try:
        cfg = load_config()
        assert cfg.kv.default_ttl_seconds == 120
        assert cfg.kv.ring.vnodes == 128
    finally:
        del os.environ["DSKITY_KV__DEFAULT_TTL_SECONDS"]
        del os.environ["DSKITY_KV__RING__VNODES"]


def test_load_config_case_insensitive() -> None:
    """Testa que configuração é case-insensitive."""
    os.environ["DSKITY_COMMON__INTERNAL_BASE_URL"] = "http://test1.com"
    os.environ["dskity_kv__store"] = "redis"  # minúscula

    try:
        cfg = load_config()
        assert cfg.common.internal_base_url == "http://test1.com"
        assert cfg.kv.store == "redis"
    finally:
        del os.environ["DSKITY_COMMON__INTERNAL_BASE_URL"]
        del os.environ["dskity_kv__store"]
