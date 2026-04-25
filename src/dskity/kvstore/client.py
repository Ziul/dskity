from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import httpx

from dskity.kvstore.ring import HashRing, RingNode, ring_from_config


@dataclass(frozen=True)
class KvStoreClient:
    ring: HashRing

    def _node_for_key(self, key: str) -> RingNode:
        owner = self.ring.owner_for_key(key)
        if owner is None:
            raise RuntimeError("Ring vazio: publique instâncias via service discovery ou configure kv.ring.nodes")
        return owner

    def get(self, key: str) -> Any:
        node = self._node_for_key(key)
        with httpx.Client(base_url=node.base_url, timeout=10.0, follow_redirects=True) as client:
            resp = client.get(f"/kv/{key}")
            resp.raise_for_status()
            return resp.json().get("value")

    def put(self, key: str, value: Any) -> None:
        node = self._node_for_key(key)
        with httpx.Client(base_url=node.base_url, timeout=10.0, follow_redirects=True) as client:
            resp = client.put(f"/kv/{key}", json={"value": value})
            resp.raise_for_status()

    def delete(self, key: str) -> None:
        node = self._node_for_key(key)
        with httpx.Client(base_url=node.base_url, timeout=10.0, follow_redirects=True) as client:
            resp = client.delete(f"/kv/{key}")
            resp.raise_for_status()


def kvstore_client_from_config(config: dict) -> KvStoreClient:
    ring, _ = ring_from_config(config)
    return KvStoreClient(ring=ring)
