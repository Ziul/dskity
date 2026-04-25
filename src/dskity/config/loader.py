from __future__ import annotations

import os
import tomllib
from pathlib import Path
from typing import Any

import yaml

from .settings import DSkitySettings, load_config_from_yaml

DEFAULT_CONFIG_FILENAME = "settings.toml"
FALLBACK_CONFIG_FILENAME = "settings.yaml"


def _default_config_candidates() -> tuple[Path, Path]:
    cwd = Path.cwd()
    return (cwd / DEFAULT_CONFIG_FILENAME, cwd / FALLBACK_CONFIG_FILENAME)


def _default_config_path() -> Path:
    toml_path, yaml_path = _default_config_candidates()
    if toml_path.exists():
        return toml_path
    if yaml_path.exists():
        return yaml_path
    return toml_path


def resolve_config_path(cli_path: str | None) -> str:
    if cli_path:
        return cli_path
    env_path = os.getenv("DSKITY_CONFIG")
    if env_path:
        return env_path
    return str(_default_config_path())


def _deep_merge(base: dict[str, Any], override: dict[str, Any]) -> dict[str, Any]:
    result: dict[str, Any] = dict(base)
    for key, value in override.items():
        if key in result and isinstance(result[key], dict) and isinstance(value, dict):
            result[key] = _deep_merge(result[key], value)
        else:
            result[key] = value
    return result


def _read_config_file(path: str | Path, *, optional: bool = False) -> dict[str, Any]:
    path = Path(path)
    if not path.exists():
        if optional:
            return {}
        raise FileNotFoundError(path)

    if path.suffix.lower() == ".toml":
        with open(path, "rb") as f:
            data = tomllib.load(f) or {}
    else:
        with open(path, "r", encoding="utf-8") as f:
            data = yaml.safe_load(f) or {}

    if not isinstance(data, dict):
        raise ValueError(f"Config deve ser um objeto no topo: {path}")
    return data


def load_config(override_path: str | None = None) -> DSkitySettings:
    """Carrega configuração com suporte a TOML, YAML e variáveis de ambiente.

    Ordem de precedência (maior para menor):
    1. Variáveis de ambiente (DSKITY_*)
    2. Arquivo de override (--config)
    3. settings.toml (ou settings.yaml como fallback) no diretório atual
    4. Valores padrão

    Variáveis de ambiente:
    - Prefixo: DSKITY_
    - Separador de hierarquia: __ (dois underscores)

    Exemplos:
    - DSKITY_COMMON__INTERNAL_BASE_URL="http://api.example.com"
    - DSKITY_KV__STORE="redis"
    - DSKITY_MODULES__PERSON__DATABASE__URL="postgresql://user:pass@localhost/db"

    Args:
        override_path: Caminho opcional para YAML de override

    Returns:
        DSkitySettings com todas as configurações validadas
    """
    default_path = _default_config_path()
    base = _read_config_file(default_path, optional=True)

    # Se override fornecido, faz deep merge (override > default settings.toml/settings.yaml)
    if override_path:
        override_path_obj = Path(override_path)
        if override_path_obj.resolve() == default_path.resolve():
            config_dict = _read_config_file(override_path_obj, optional=True)
        else:
            override = _read_config_file(override_path_obj, optional=False)
            config_dict = _deep_merge(base, override)
    else:
        config_dict = base

    # Passa config_dict para load_config_from_yaml
    # que cria DSkitySettings() com env vars tendo precedência
    return load_config_from_yaml(config_dict)
