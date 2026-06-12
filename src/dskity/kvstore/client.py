from __future__ import annotations

import warnings
from dataclasses import dataclass
from typing import Any

import httpx

from dskity.kvstore.ring import HashRing, RingNode, ring_from_config


@dataclass(frozen=True)
class KvStoreClient:
    """Synchronous KV store client.

    .. deprecated::
        Use :class:`AsyncKvStoreClient` instead to avoid blocking the event loop.
    """

    ring: HashRing

    def _node_for_key(self, key: str) -> RingNode:
        owner = self.ring.owner_for_key(key)
        if owner is None:
            raise RuntimeError(
                "Empty ring: publish instances via service discovery or configure kv.ring.nodes"
            )
        return owner

    def get(self, key: str) -> Any:
        warnings.warn(
            "KvStoreClient is synchronous and blocks the event loop. "
            "Use AsyncKvStoreClient instead.",
            DeprecationWarning,
            stacklevel=2,
        )
        node = self._node_for_key(key)
        with httpx.Client(
            base_url=node.base_url, timeout=10.0, follow_redirects=True
        ) as client:
            resp = client.get(f"/kv/{key}")
            resp.raise_for_status()
            return resp.json().get("value")

    def put(self, key: str, value: Any) -> None:
        warnings.warn(
            "KvStoreClient is synchronous and blocks the event loop. "
            "Use AsyncKvStoreClient instead.",
            DeprecationWarning,
            stacklevel=2,
        )
        node = self._node_for_key(key)
        with httpx.Client(
            base_url=node.base_url, timeout=10.0, follow_redirects=True
        ) as client:
            resp = client.put(f"/kv/{key}", json={"value": value})
            resp.raise_for_status()

    def delete(self, key: str) -> None:
        warnings.warn(
            "KvStoreClient is synchronous and blocks the event loop. "
            "Use AsyncKvStoreClient instead.",
            DeprecationWarning,
            stacklevel=2,
        )
        node = self._node_for_key(key)
        with httpx.Client(
            base_url=node.base_url, timeout=10.0, follow_redirects=True
        ) as client:
            resp = client.delete(f"/kv/{key}")
            resp.raise_for_status()


@dataclass(frozen=True)
class AsyncKvStoreClient:
    """Async KV store client that uses a shared :class:`~dskity.transport.http_client.HttpClientManager`."""

    ring: HashRing
    http_client: Any  # HttpClientManager

    def _node_for_key(self, key: str) -> RingNode:
        owner = self.ring.owner_for_key(key)
        if owner is None:
            raise RuntimeError(
                "Empty ring: publish instances via service discovery or configure kv.ring.nodes"
            )
        return owner

    async def get(self, key: str) -> Any:
        """Fetch a key from the KV store asynchronously."""
        node = self._node_for_key(key)
        resp = await self.http_client.get(f"{node.base_url}/kv/{key}")
        resp.raise_for_status()
        return resp.json().get("value")

    async def put(self, key: str, value: Any) -> None:
        """Store a key in the KV store asynchronously."""
        node = self._node_for_key(key)
        resp = await self.http_client.put(
            f"{node.base_url}/kv/{key}", json={"value": value}
        )
        resp.raise_for_status()

    async def delete(self, key: str) -> None:
        """Delete a key from the KV store asynchronously."""
        node = self._node_for_key(key)
        resp = await self.http_client.delete(f"{node.base_url}/kv/{key}")
        resp.raise_for_status()


def kvstore_client_from_config(config: dict) -> KvStoreClient:
    ring, _ = ring_from_config(config)
    return KvStoreClient(ring=ring)
