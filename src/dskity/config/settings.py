"""Pydantic models for configuration with environment variable support.

Uses pydantic-settings to automatically discover and validate environment
variables prefixed with DSKITY_.

Examples of environment variables:
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
    """Service discovery settings (common.registry.*)"""

    enabled: bool = True
    ttl_seconds: int = 60
    heartbeat_interval_seconds: int = 30


class MQTTSettings(BaseModel):
    """MQTT transport settings (common.mqtt.*)"""

    enabled: bool = False
    broker: str = "mqtt://localhost"
    port: int = 1883
    client_id: str = "dskity-client"
    username: str | None = None
    password: str | None = None
    keepalive: int = 60
    reconnect_interval_seconds: int = 10
    protocol: str = "5.0"
    tls_secure: bool = True
    tls_version: str = "tlsv1_2"
    subscribe_topics: list[str] = Field(default_factory=list)


class CommonSettings(BaseModel):
    """Common settings (common.*)"""

    internal_base_url: str = "http://127.0.0.1:8000"
    advertise_url: str = "http://127.0.0.1:8000"
    registry: RegistrySettings = Field(default_factory=RegistrySettings)
    mqtt: MQTTSettings = Field(default_factory=MQTTSettings)


class RedisSettings(BaseModel):
    """Redis settings (kv.redis.*)"""

    url: str = "redis://127.0.0.1:6379/0"
    username: str | None = None
    password: str | None = None
    key_prefix: str = "dskity"


class ConsulSettings(BaseModel):
    """Consul settings (kv.consul.*)"""

    url: str = "http://127.0.0.1:8500"
    token: str | None = None
    dc: str | None = None
    verify: bool = True
    key_prefix: str = "dskity"


class RingSettings(BaseModel):
    """Ring settings (kv.ring.*)"""

    vnodes: int = 64


class KvSettings(BaseModel):
    """KV backend settings (kv.*)"""

    store: str = "inmemory"  # inmemory, redis, consul
    default_ttl_seconds: int = 60
    redis: RedisSettings = Field(default_factory=RedisSettings)
    consul: ConsulSettings = Field(default_factory=ConsulSettings)
    ring: RingSettings = Field(default_factory=RingSettings)


class ModuleDatabaseSettings(BaseModel):
    """Generic module database settings"""

    url: str = "sqlite:///:memory:"
    pool_size: int = 10
    max_overflow: int = 20
    pool_pre_ping: bool = True


class ModuleSettings(BaseModel):
    """Settings for an individual module"""

    __name__: str | None = None  # Module name (e.g. "echo", "person")
    enabled: bool = True
    url: str | None = None
    headers: dict[str, str] | None = None
    database: ModuleDatabaseSettings | None = None

    model_config = {"extra": "allow"}


class PersonDatabaseSettings(BaseModel):
    """Database settings for the `person` module"""

    url: str = "postgresql+psycopg2://dskity:dskity@127.0.0.1:5432/dskity_person"
    pool_size: int = 10
    max_overflow: int = 20
    pool_pre_ping: bool = True


class PersonModuleSettings(ModuleSettings):
    """Person module specific settings"""

    database: PersonDatabaseSettings = Field(default_factory=PersonDatabaseSettings)


class ModulesSettings(BaseModel):
    """Modules settings (modules.*)"""

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
        # Allow accessing extra modules as attributes and convert dicts to ModuleSettings
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
    """Full DSkity configuration.

    Loaded from, in order of precedence:
    1. Environment variables with prefix DSKITY_
    2. YAML (via load_config_from_yaml)

    Priority (highest to lowest):
    1. Environment variables (DSKITY_*)
    2. YAML override (--config)
    3. Base YAML (config/base.yaml)
    4. Defaults defined in this class

    Examples of environment variables:
    - DSKITY_COMMON__INTERNAL_BASE_URL="http://api.example.com"
    - DSKITY_KV__STORE="redis"
    - DSKITY_MODULES__PERSON__DATABASE__URL="postgresql://..."
    - DSKITY_MODULES_SEARCH_PATHS='["dskity.modules", "./services"]'

    Note: Use __ (two underscores) to separate hierarchy levels in YAML/env vars.
    """

    model_config = SettingsConfigDict(
        env_prefix="DSKITY_",
        env_nested_delimiter="__",  # Allows DSKITY_MODULE__SETTING=value
        case_sensitive=False,
        extra="allow",  # Allow extra fields from YAML/env vars
    )

    common: CommonSettings = Field(default_factory=CommonSettings)
    kv: KvSettings = Field(default_factory=KvSettings)
    modules: ModulesSettings = Field(default_factory=ModulesSettings)
    modules_search_paths: list[str] = Field(default_factory=lambda: ["modules"])

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
    """Load configuration from a YAML dict with precedence of env vars.

    If a 'name' field exists in yaml_data, it will be used as the env var prefix
    (e.g., if name='myapp', env vars like MYAPP_COMMON__SETTING will be used).
    Otherwise, defaults to 'DSKITY_'.

    Precedence (highest to lowest):
    1. Environment variables ({prefix}*)
    2. YAML data
    3. Default values

    Args:
        yaml_data: Dictionary loaded from YAML (base + merged override)
        settings_with_env: Do not use (kept for compatibility)

    Returns:
        DSkitySettings with all values validated
    """

    # Extract prefix from yaml_data if 'name' exists
    prefix = "dskity_"
    if yaml_data and isinstance(yaml_data, dict) and "name" in yaml_data:
        name = yaml_data.get("name")
        if isinstance(name, str) and name.strip():
            prefix = f"{name.strip().lower()}_"

    # If there's no YAML, just use values from the environment
    if not yaml_data:
        return DSkitySettings()

    # If YAML is present, perform an intelligent merge
    # Strategy: read env vars manually and apply precedence

    # Start with YAML
    result_dict = dict(yaml_data)

    # Now apply env vars with the extracted or default prefix over the yaml dict
    # Parse env vars using the rule: {PREFIX}KEY1__KEY2__KEY3 = common.registry.enabled
    _apply_env_vars_to_dict(result_dict, prefix=prefix)

    # Rebuilds instance
    return DSkitySettings.model_validate(result_dict)


def _apply_env_vars_to_dict(target_dict: dict[str, Any], prefix: str = "dskity_") -> None:
    """Apply env vars with given prefix to the configuration dict (in-place).

    Format: {PREFIX}SECTION__SUBSECTION__KEY = value
    Example: DSKITY_COMMON__INTERNAL_BASE_URL = "http://api.com"
    Example with custom prefix: MYAPP_COMMON__INTERNAL_BASE_URL = "http://api.com"

    Args:
        target_dict: Configuration dictionary to modify
        prefix: Environment variable prefix to look for (lowercase, with trailing _)

    Case-insensitive for the key.
    """
    import os

    prefix_lower = prefix.lower()

    for env_key, env_value in os.environ.items():
        env_key_lower = env_key.lower()

        # Case-insensitive check
        if not env_key_lower.startswith(prefix_lower):
            continue

        # Remove prefix and convert to a path in the dict
        # E.g., "DSKITY_COMMON__INTERNAL_BASE_URL" → ["common", "internal_base_url"]
        key_path = env_key_lower[len(prefix_lower) :].split("__")

        if len(key_path) == 1:
            target_dict[key_path[0]] = env_value
            continue

        # Traverse/create structure in the dict
        current = target_dict
        for i, segment in enumerate(key_path[:-1]):
            if segment not in current:
                current[segment] = {}
            elif not isinstance(current[segment], dict):
                # Already has a scalar value, cannot descend
                break
            current = current[segment]

        # Seta o valor final
        if isinstance(current, dict):
            current[key_path[-1]] = env_value


def _smart_merge(
    current_dict: dict[str, Any],
    yaml_dict: dict[str, Any],
    default_dict: dict[str, Any],
) -> dict[str, Any]:
    """Smart merge: YAML overrides defaults, but not env vars.

    Heuristic: if current == default, then it's not an env var and YAML may be used.
    If current != default, then it's an env var and should be kept.
    """
    result = dict(current_dict)

    for key, yaml_val in yaml_dict.items():
        if key not in result:
            result[key] = yaml_val
        elif isinstance(yaml_val, dict) and isinstance(result.get(key), dict):
            result[key] = _smart_merge(result[key], yaml_val, default_dict.get(key, {}))
        elif result[key] == default_dict.get(key):
            # It's the default, can be overridden by YAML
            result[key] = yaml_val
        # Otherwise it's an env var, keep it

    return result
