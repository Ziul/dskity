from __future__ import annotations

import json
import os
import socket
import time
import urllib.parse
from dataclasses import dataclass
from threading import RLock
from typing import Any, Protocol
import logging
from dskity.config.settings import DSkitySettings

try:
    import redis  # type: ignore
except Exception:  # pragma: no cover
    redis = None  # type: ignore

try:
    import consul  # type: ignore
except Exception:  # pragma: no cover
    consul = None  # type: ignore

logger = logging.getLogger(__name__)


class KVBackend(Protocol):
    def get(self, key: str) -> Any: ...

    def put(self, key: str, value: Any, ttl_seconds: int | None = None) -> None: ...

    def delete(self, key: str) -> None: ...

    def keys(self, prefix: str = "") -> list[str]: ...


def _kv_cfg(config: dict) -> dict[str, Any]:
    cfg = config or {}
    kv = cfg.get("kv") if isinstance(cfg, dict) else None
    if isinstance(kv, dict):
        return kv
    legacy = cfg.get("kvstore") if isinstance(cfg, dict) else None
    if isinstance(legacy, dict):
        return legacy
    return {}


@dataclass
class InMemoryKVBackend(KVBackend):
    _lock: RLock
    _data: dict[str, tuple[Any, int | None]]
    default_ttl_seconds: int | None = None

    def __init__(self, *, default_ttl_seconds: int | None = None) -> None:
        self._lock = RLock()
        self._data = {}
        self.default_ttl_seconds = default_ttl_seconds

    def _effective_ttl(self, ttl_seconds: int | None) -> int | None:
        ttl = ttl_seconds if ttl_seconds is not None else self.default_ttl_seconds
        if ttl is None:
            return None
        ttl_int = int(ttl)
        if ttl_int <= 0:
            return None
        return ttl_int

    def get(self, key: str) -> Any:
        with self._lock:
            item = self._data.get(key)
            if item is None:
                return None
            value, expires_at = item
            if expires_at is not None and int(time.time()) >= int(expires_at):
                self._data.pop(key, None)
                return None
            return value

    def put(self, key: str, value: Any, ttl_seconds: int | None = None) -> None:
        ttl = self._effective_ttl(ttl_seconds)
        expires_at = int(time.time()) + int(ttl) if ttl is not None else None
        with self._lock:
            self._data[key] = (value, expires_at)

    def delete(self, key: str) -> None:
        with self._lock:
            self._data.pop(key, None)

    def keys(self, prefix: str = "") -> list[str]:
        with self._lock:
            now = int(time.time())
            expired: list[str] = []
            for k, (_, expires_at) in self._data.items():
                if expires_at is not None and now >= int(expires_at):
                    expired.append(k)
            for k in expired:
                self._data.pop(k, None)

            if not prefix:
                return sorted(self._data.keys())
            return sorted(k for k in self._data.keys() if k.startswith(prefix))


@dataclass
class RedisKVBackend(KVBackend):
    client: Any
    key_prefix: str = ""
    default_ttl_seconds: int | None = None

    @staticmethod
    def _normalize_prefix(value: str) -> str:
        prefix = (value or "").strip()
        if not prefix:
            return ""
        # Keep prefix as a namespace (avoid collisions between apps).
        if not prefix.endswith(":"):
            prefix += ":"
        return prefix

    @classmethod
    def from_config(cls, config: dict) -> "RedisKVBackend":
        if redis is None:
            raise RuntimeError("Redis dependency not installed. Install with: uv sync --extra kvstore-redis")

        kv_cfg = _kv_cfg(config)
        redis_cfg = (kv_cfg or {}).get("redis", {}) if isinstance(kv_cfg, dict) else {}

        url = (
            os.getenv("DSKITY_REDIS_URL")
            or os.getenv("REDIS_URL")
            or (redis_cfg.get("url") if isinstance(redis_cfg, dict) else None)
            or "redis://127.0.0.1:6379/0"
        )

        username = os.getenv("DSKITY_REDIS_USERNAME") or (
            redis_cfg.get("username") if isinstance(redis_cfg, dict) else None
        )
        password = os.getenv("DSKITY_REDIS_PASSWORD") or (
            redis_cfg.get("password") if isinstance(redis_cfg, dict) else None
        )
        key_prefix = cls._normalize_prefix(
            str(redis_cfg.get("key_prefix") or "") if isinstance(redis_cfg, dict) else ""
        )

        default_ttl_seconds = None
        if isinstance(kv_cfg, dict) and kv_cfg.get("default_ttl_seconds") is not None:
            default_ttl_seconds = int(kv_cfg.get("default_ttl_seconds"))

        kwargs: dict[str, Any] = {"decode_responses": True}
        if username:
            kwargs["username"] = str(username)
        if password:
            kwargs["password"] = str(password)

        client = redis.Redis.from_url(str(url), **kwargs)
        return cls(client=client, key_prefix=key_prefix, default_ttl_seconds=default_ttl_seconds)

    def _effective_ttl(self, ttl_seconds: int | None) -> int | None:
        ttl = ttl_seconds if ttl_seconds is not None else self.default_ttl_seconds
        if ttl is None:
            return None
        ttl_int = int(ttl)
        if ttl_int <= 0:
            return None
        return ttl_int

    def _k(self, key: str) -> str:
        return f"{self.key_prefix}{key}" if self.key_prefix else key

    def get(self, key: str) -> Any:
        raw = self.client.get(self._k(key))
        if raw is None:
            return None
        try:
            return json.loads(raw)
        except Exception:
            # Compat: if someone wrote a raw string, return it as-is.
            return raw

    def put(self, key: str, value: Any, ttl_seconds: int | None = None) -> None:
        try:
            payload = json.dumps(value, ensure_ascii=False, separators=(",", ":"))
        except TypeError as e:
            raise TypeError("Value not JSON-serializable for storage in Redis") from e
        ttl = self._effective_ttl(ttl_seconds)
        if ttl is None:
            self.client.set(self._k(key), payload)
        else:
            self.client.set(self._k(key), payload, ex=int(ttl))

    def delete(self, key: str) -> None:
        self.client.delete(self._k(key))

    def keys(self, prefix: str = "") -> list[str]:
        # `SCAN` avoids blocking Redis (unlike KEYS).
        full_prefix = f"{self.key_prefix}{prefix}" if self.key_prefix else prefix
        match = f"{full_prefix}*" if full_prefix else "*"

        results: list[str] = []
        for k in self.client.scan_iter(match=match, count=1000):
            # decode_responses=True → k is already a str
            if self.key_prefix and k.startswith(self.key_prefix):
                k = k[len(self.key_prefix) :]
            if prefix and not k.startswith(prefix):
                continue
            results.append(k)
        return sorted(set(results))


@dataclass
class ConsulKVBackend(KVBackend):
    client: Any
    key_prefix: str = ""
    default_ttl_seconds: int | None = None

    @staticmethod
    def _normalize_prefix(value: str) -> str:
        prefix = (value or "").strip().strip("/")
        if not prefix:
            return ""
        return prefix + "/"

    @classmethod
    def from_config(cls, config: dict) -> "ConsulKVBackend":
        if consul is None:
            raise RuntimeError(
                "Consul client dependency 'python-consul2' not installed. Install with: uv sync --extra kvstore-consul"
            )

        kv_cfg = _kv_cfg(config)
        consul_cfg = (kv_cfg or {}).get("consul", {}) if isinstance(kv_cfg, dict) else {}

        url = (
            os.getenv("DSKITY_CONSUL_URL")
            or os.getenv("CONSUL_HTTP_ADDR")
            or (consul_cfg.get("url") if isinstance(consul_cfg, dict) else None)
            or "http://127.0.0.1:8500"
        )

        token = (
            os.getenv("DSKITY_CONSUL_TOKEN")
            or os.getenv("CONSUL_HTTP_TOKEN")
            or (consul_cfg.get("token") if isinstance(consul_cfg, dict) else None)
        )

        dc = os.getenv("DSKITY_CONSUL_DC") or (consul_cfg.get("dc") if isinstance(consul_cfg, dict) else None)

        verify = consul_cfg.get("verify", True) if isinstance(consul_cfg, dict) else True

        parsed = urllib.parse.urlparse(str(url))
        scheme = parsed.scheme or "http"
        host = parsed.hostname or "127.0.0.1"
        port = int(parsed.port or (8501 if scheme == "https" else 8500))

        key_prefix = cls._normalize_prefix(
            str(consul_cfg.get("key_prefix") or "") if isinstance(consul_cfg, dict) else ""
        )

        default_ttl_seconds = None
        if isinstance(kv_cfg, dict) and kv_cfg.get("default_ttl_seconds") is not None:
            default_ttl_seconds = int(kv_cfg.get("default_ttl_seconds"))

        client = consul.Consul(host=host, port=port, scheme=scheme, token=token, dc=dc, verify=verify)
        return cls(client=client, key_prefix=key_prefix, default_ttl_seconds=default_ttl_seconds)

    def _k(self, key: str) -> str:
        # Consul KV uses path-style keys. Keep prefix as a namespace.
        return f"{self.key_prefix}{key}" if self.key_prefix else key

    def get(self, key: str) -> Any:
        _, data = self.client.kv.get(self._k(key))
        if not data:
            return None
        raw = data.get("Value")
        if raw is None:
            return None
        if isinstance(raw, (bytes, bytearray)):
            raw_str = raw.decode("utf-8", errors="replace")
        else:
            raw_str = str(raw)

        try:
            return json.loads(raw_str)
        except Exception:
            return raw_str

    def put(self, key: str, value: Any, ttl_seconds: int | None = None) -> None:
        # Consul KV does not have per-key TTL like Redis.
        # We keep logical TTL in the payload (registry) and ignore ttl_seconds here.
        try:
            payload = json.dumps(value, ensure_ascii=False, separators=(",", ":"))
        except TypeError as e:
            raise TypeError("Value not JSON-serializable for storage in Consul") from e

        self.client.kv.put(self._k(key), payload)

    def delete(self, key: str) -> None:
        self.client.kv.delete(self._k(key))

    def keys(self, prefix: str = "") -> list[str]:
        full_prefix = self._k(prefix) if prefix else (self.key_prefix or "")

        # keys=True returns only the list of keys, recurse=True includes subpaths.
        _, keys = self.client.kv.get(full_prefix, keys=True, recurse=True)
        if not keys:
            return []

        results: list[str] = []
        for k in keys:
            if not isinstance(k, str):
                k = str(k)
            if self.key_prefix and k.startswith(self.key_prefix):
                k = k[len(self.key_prefix) :]
            if prefix and not k.startswith(prefix):
                continue
            results.append(k)
        return sorted(set(results))


def generate_node_id() -> str:
    hostname = socket.gethostname()
    pid = os.getpid()
    return f"{hostname}:{pid}"


def backend_from_config(config: dict | DSkitySettings) -> tuple[str, KVBackend]:
    if isinstance(config, DSkitySettings):
        store = config.kv.store or "inmemory"
        store = store.lower().strip()
        default_ttl_seconds = config.kv.default_ttl_seconds
    else:
        kv_cfg = _kv_cfg(config)
        logger.debug("KV config: %s", kv_cfg)
        store = str(kv_cfg.get("store") or "inmemory").lower().strip()
        default_ttl_seconds = None
        if isinstance(kv_cfg, dict) and kv_cfg.get("default_ttl_seconds") is not None:
            default_ttl_seconds = int(kv_cfg.get("default_ttl_seconds"))

    logger.info("Detected kv.store='%s'", store)
    logger.debug("KV: %s", str(config))
    if store == "inmemory":
        return store, InMemoryKVBackend(default_ttl_seconds=default_ttl_seconds)

    if store == "redis":
        # Redis backend also reads default_ttl_seconds from the config.
        return store, RedisKVBackend.from_config(
            config.model_dump() if isinstance(config, DSkitySettings) else config
        )

    if store == "consul":
        return store, ConsulKVBackend.from_config(
            config.model_dump() if isinstance(config, DSkitySettings) else config
        )

    # Keep names aligned with ecosystem (Cortex) and fail with explicit errors.
    if store in {"etcd"}:
        raise NotImplementedError(f"kv.store='{store}' is not implemented yet. Use 'inmemory' for now.")

    raise ValueError(f"invalid kv.store: {store}")
