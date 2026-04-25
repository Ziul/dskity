"""Modelos Pydantic para configuração com suporte a variáveis de ambiente.

Usa pydantic-settings para automático descobrir e validar variáveis de ambiente
com prefixo DSKITY_.

Exemplos de variáveis de ambiente:
- DSKITY_COMMON__INTERNAL_BASE_URL="http://api.example.com"
- DSKITY_KV__STORE="redis"
- DSKITY_KV__REDIS__URL="redis://localhost:6379"
- DSKITY_MODULES__PERSON__DATABASE__URL="postgresql://user:pass@localhost/db"
"""

from __future__ import annotations

import json
from typing import Any

from pydantic import BaseModel, Field, field_validator
from pydantic import model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class RegistrySettings(BaseModel):
    """Configurações do service discovery (common.registry.*)"""

    enabled: bool = True
    ttl_seconds: int = 60
    heartbeat_interval_seconds: int = 30


class CommonSettings(BaseModel):
    """Configurações comuns (common.*)"""

    internal_base_url: str = "http://127.0.0.1:8000"
    advertise_url: str | None = None
    registry: RegistrySettings = Field(default_factory=RegistrySettings)


class RedisSettings(BaseModel):
    """Configurações do Redis (kv.redis.*)"""

    url: str = "redis://127.0.0.1:6379/0"
    username: str | None = None
    password: str | None = None
    key_prefix: str = "dskity"


class ConsulSettings(BaseModel):
    """Configurações do Consul (kv.consul.*)"""

    url: str = "http://127.0.0.1:8500"
    token: str | None = None
    dc: str | None = None
    verify: bool = True
    key_prefix: str = "dskity"


class RingSettings(BaseModel):
    """Configurações do ring (kv.ring.*)"""

    vnodes: int = 64


class KvSettings(BaseModel):
    """Configurações do backend KV (kv.*)"""

    store: str = "inmemory"  # inmemory, redis, consul
    default_ttl_seconds: int = 60
    redis: RedisSettings = Field(default_factory=RedisSettings)
    consul: ConsulSettings = Field(default_factory=ConsulSettings)
    ring: RingSettings = Field(default_factory=RingSettings)


class ModuleDatabaseSettings(BaseModel):
    """Configurações do banco de dados do módulo generico"""

    url: str = "sqlite:///:memory:"
    pool_size: int = 10
    max_overflow: int = 20
    pool_pre_ping: bool = True


class ModuleSettings(BaseModel):
    """Configurações de um módulo individual"""

    __name__: str | None = None  # Nome do módulo (ex.: "echo", "person")
    enabled: bool = True
    url: str | None = None
    headers: dict[str, str] | None = None
    database: ModuleDatabaseSettings | None = None

    model_config = {"extra": "allow"}


class PersonDatabaseSettings(BaseModel):
    """Configurações do banco de dados do módulo person"""

    url: str = "postgresql+psycopg2://dskity:dskity@127.0.0.1:5432/dskity_person"
    pool_size: int = 10
    max_overflow: int = 20
    pool_pre_ping: bool = True


class PersonModuleSettings(ModuleSettings):
    """Configurações específicas do módulo person"""

    database: PersonDatabaseSettings = Field(default_factory=PersonDatabaseSettings)


class ModulesSettings(BaseModel):
    """Configurações dos módulos (modules.*)"""

    model_config = {"extra": "allow"}

    @model_validator(mode="before")
    @classmethod
    def _inject_default_modules(cls, value: Any) -> Any:
        if value is None:
            data: dict[str, Any] = {}
        elif isinstance(value, dict):
            data = dict(value)
        else:
            return value

        data.setdefault("kvstore", {"enabled": True})
        return data

    @staticmethod
    def _as_module(name: str, value: Any) -> Any:
        if isinstance(value, ModuleSettings):
            module = value
        elif isinstance(value, dict):
            module = ModuleSettings.model_validate(value)
        else:
            return value

        if module.__name__ is None:
            module.__name__ = name
        return module

    def __getattr__(self, name: str):
        # Permite acessar módulos extras como atributos e converte dicts em ModuleSettings
        extra = getattr(self, "__pydantic_extra__", {}) or {}
        if name in extra:
            val = self._as_module(name, extra[name])
            extra[name] = val
            return val
        raise AttributeError(name)

    def get(self, name: str, default: Any = None) -> Any:
        extra = getattr(self, "__pydantic_extra__", {}) or {}
        if name not in extra:
            return default

        val = self._as_module(name, extra[name])
        extra[name] = val
        return val


class DSkitySettings(BaseSettings):
    """Configuração completa do Dskity.

    Carrega de:
    1. Variáveis de ambiente com prefixo DSKITY_
    2. YAML (via load_config_from_yaml)

    Hierarquia (do maior para menor prioridade):
    1. Variáveis de ambiente (DSKITY_*)
    2. YAML override (--config)
    3. YAML base (config/base.yaml)
    4. Valores padrão definidos nesta classe

    Exemplos de variáveis de ambiente:
    - DSKITY_COMMON__INTERNAL_BASE_URL="http://api.example.com"
    - DSKITY_KV__STORE="redis"
    - DSKITY_MODULES__PERSON__DATABASE__URL="postgresql://..."
    - DSKITY_MODULES_SEARCH_PATHS='["dskity.modules", "./services"]'

    Nota: Use __ (dois underscores) para separar níveis de hierarquia em YAML.
    """

    model_config = SettingsConfigDict(
        env_prefix="DSKITY_",
        env_nested_delimiter="__",  # Permite DSKITY_MODULE__SETTING=value
        case_sensitive=False,
        extra="allow",  # Permite campos extras do YAML/env vars
    )

    common: CommonSettings = Field(default_factory=CommonSettings)
    kv: KvSettings = Field(default_factory=KvSettings)
    modules: ModulesSettings = Field(default_factory=ModulesSettings)
    modules_search_paths: list[str] = Field(default_factory=lambda: ["dskity.modules"])

    @field_validator("modules_search_paths", mode="before")
    @classmethod
    def _parse_modules_search_paths(cls, value: Any) -> list[str]:
        if value is None:
            return ["dskity.modules"]

        if isinstance(value, str):
            raw = value.strip()
            if not raw:
                return ["dskity.modules"]

            try:
                parsed = json.loads(raw)
            except json.JSONDecodeError:
                parsed = None

            if isinstance(parsed, list):
                return [str(item).strip() for item in parsed if str(item).strip()]

            if "," in raw:
                return [item.strip() for item in raw.split(",") if item.strip()]

            return [raw]

        if isinstance(value, (list, tuple, set)):
            return [str(item).strip() for item in value if str(item).strip()]

        return list(value)


def load_config_from_yaml(
    yaml_data: dict[str, Any], settings_with_env: DSkitySettings | None = None
) -> DSkitySettings:
    """Carrega configuração a partir de dict YAML com precedência de env vars.

    Ordem de precedência (maior para menor):
    1. Variáveis de ambiente (DSKITY_*)
    2. Dados do YAML
    3. Valores padrão

    Args:
        yaml_data: Dicionário carregado do YAML (base + merged override)
        settings_with_env: Não usar (mantido para compatibilidade)

    Returns:
        DSkitySettings com todas as configurações validadas
    """

    # Se não há YAML, apenas passa os valores do environ
    if not yaml_data:
        return DSkitySettings()

    # Se há YAML, precisa fazer merge inteligente
    # Estratégia: ler env vars manualmente e aplicar precedência

    # Começa com YAML
    result_dict = dict(yaml_data)

    # Agora aplica env vars (DSKITY_*) sobre yaml_dict
    # Parse env vars com a regra: DSKITY_KEY1__KEY2__KEY3 = common.registry.enabled
    _apply_env_vars_to_dict(result_dict)

    # Reconstrói instância
    return DSkitySettings.model_validate(result_dict)


def _apply_env_vars_to_dict(target_dict: dict[str, Any]) -> None:
    """Aplica env vars (DSKITY_*) ao dict de configuração (in-place).

    Formato: DSKITY_SECTION__SUBSECTION__KEY = value
    Example: DSKITY_COMMON__INTERNAL_BASE_URL = "http://api.com"

    Case-insensitive para a chave (DSKITY_ funciona em qualquer case).
    """
    import os

    prefix_lower = "dskity_"

    for env_key, env_value in os.environ.items():
        env_key_lower = env_key.lower()

        # Case-insensitive check
        if not env_key_lower.startswith(prefix_lower):
            continue

        # Remove prefixo e converte para path no dict
        # E.g., "DSKITY_COMMON__INTERNAL_BASE_URL" → ["common", "internal_base_url"]
        key_path = env_key_lower[len(prefix_lower) :].split("__")

        if len(key_path) == 1:
            target_dict[key_path[0]] = env_value
            continue

        # Navega/cria estrutura no dict
        current = target_dict
        for i, segment in enumerate(key_path[:-1]):
            if segment not in current:
                current[segment] = {}
            elif not isinstance(current[segment], dict):
                # Já tem um valor escalar, não pode descer
                break
            current = current[segment]

        # Seta o valor final
        if isinstance(current, dict):
            current[key_path[-1]] = env_value


def _smart_merge(
    current_dict: dict[str, Any], yaml_dict: dict[str, Any], default_dict: dict[str, Any]
) -> dict[str, Any]:
    """Merge inteligente: YAML sobrescreve defaults, mas não env vars.

    A heurística é: se current == default, então não é env var, pode usar YAML.
    Se current != default, então é env var, mantém.
    """
    result = dict(current_dict)

    for key, yaml_val in yaml_dict.items():
        if key not in result:
            result[key] = yaml_val
        elif isinstance(yaml_val, dict) and isinstance(result.get(key), dict):
            result[key] = _smart_merge(result[key], yaml_val, default_dict.get(key, {}))
        elif result[key] == default_dict.get(key):
            # É padrão, pode sobrescrever com YAML
            result[key] = yaml_val
        # Senão é env var, mantém

    return result
