from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from dskity.kvstore.backends import KVBackend


@dataclass(frozen=True)
class RegistryStore:
    backend: KVBackend

    def get(self, key: str) -> Any:
        return self.backend.get(key)

    def put(self, key: str, value: Any, ttl_seconds: int | None = None) -> None:
        self.backend.put(key, value, ttl_seconds=ttl_seconds)

    def delete(self, key: str) -> None:
        self.backend.delete(key)

    def keys(self, prefix: str = "") -> list[str]:
        return self.backend.keys(prefix=prefix)
