from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Any
import logging

from dskity.registry.store import RegistryStore

logger = logging.getLogger(__name__)


def _svc_prefix(service: str) -> str:
    return f"registry/services/{service}/"


def _svc_key(service: str, instance_id: str) -> str:
    return f"registry/services/{service}/{instance_id}"


@dataclass(frozen=True)
class ServiceRegistry:
    store: RegistryStore

    def register_instance(
        self,
        *,
        service: str,
        instance_id: str,
        base_url: str,
        route: str,
        ttl_seconds: int = 60,
        now: int | None = None,
    ) -> None:
        now_ts = int(now if now is not None else time.time())
        expires_at = now_ts + int(ttl_seconds)
        self.store.put(
            _svc_key(service, instance_id),
            {
                "service": service,
                "instance_id": instance_id,
                "base_url": base_url,
                "route": route,
                "url": _join_url(base_url, route),
                "updated_at": now_ts,
                "ttl_seconds": int(ttl_seconds),
                "expires_at": expires_at,
            },
            ttl_seconds=int(ttl_seconds),
        )
        logger.debug(
            f"Registered service instance: service={service}, instance_id={instance_id}, url={
                _join_url(base_url, route)
            }, ttl_seconds={ttl_seconds}"
        )

    def list_services(self) -> list[str]:
        keys = self.store.keys(prefix="registry/services/")
        services: set[str] = set()
        now = int(time.time())
        for key in keys:
            parts = key.split("/")
            if len(parts) < 4:
                continue
            service = parts[2]
            value = self.store.get(key)
            if not isinstance(value, dict):
                continue
            if _is_expired(value, now=now):
                continue
            services.add(service)
        return sorted(services)

    def list_instances(self, service: str) -> list[dict[str, Any]]:
        keys = self.store.keys(prefix=_svc_prefix(service))
        instances: list[dict[str, Any]] = []
        now = int(time.time())
        for key in keys:
            value = self.store.get(key)
            if isinstance(value, dict):
                if _is_expired(value, now=now):
                    self.store.delete(key)
                    continue
                instances.append(value)
        # ordena pelo updated_at (mais recente primeiro)
        instances.sort(key=lambda x: int(x.get("updated_at", 0)), reverse=True)
        return instances

    def prune_expired(self, *, service: str, now: int | None = None) -> int:
        now_ts = int(now if now is not None else time.time())
        removed = 0
        keys = self.store.keys(prefix=_svc_prefix(service))
        for key in keys:
            value = self.store.get(key)
            if isinstance(value, dict) and _is_expired(value, now=now_ts):
                self.store.delete(key)
                removed += 1
        return removed

    def aggregate_services(self, *, now: int | None = None) -> list[dict[str, Any]]:
        now_ts = int(now if now is not None else time.time())
        keys = self.store.keys(prefix="registry/services/")

        agg: dict[str, dict[str, Any]] = {}
        for key in keys:
            parts = key.split("/")
            if len(parts) < 4:
                continue
            service = parts[2]
            value = self.store.get(key)
            if not isinstance(value, dict):
                continue
            if _is_expired(value, now=now_ts):
                # limpeza oportunista
                self.store.delete(key)
                continue

            updated_at = int(value.get("updated_at", 0) or 0)
            entry = agg.get(service)
            if entry is None:
                entry = {
                    "service": service,
                    "instances_count": 0,
                    "last_heartbeat": None,
                    "last_heartbeat_age_seconds": None,
                }
                agg[service] = entry

            entry["instances_count"] = int(entry["instances_count"]) + 1
            current_last = entry["last_heartbeat"]
            if current_last is None or updated_at > int(current_last):
                entry["last_heartbeat"] = updated_at

        # preenche age
        for entry in agg.values():
            hb = entry.get("last_heartbeat")
            if hb is None:
                entry["last_heartbeat_age_seconds"] = None
            else:
                entry["last_heartbeat_age_seconds"] = max(0, now_ts - int(hb))

        result = list(agg.values())
        result.sort(key=lambda x: (x.get("service") or ""))
        return result


def _join_url(base_url: str, route: str) -> str:
    base = base_url.rstrip("/")
    path = (route or "").strip()
    if not path:
        return base
    if not path.startswith("/"):
        path = "/" + path
    return base + path


def _is_expired(value: dict[str, Any], *, now: int) -> bool:
    expires_at = value.get("expires_at")
    try:
        if expires_at is None:
            return False
        return int(expires_at) <= int(now)
    except Exception:
        return False
