from __future__ import annotations

import hashlib
from dataclasses import dataclass
from typing import Any

from dskity.config.settings import DSkitySettings
from dskity.kvstore.backends import generate_node_id
from dskity.registry.service_registry import ServiceRegistry


@dataclass(frozen=True)
class RingNode:
    id: str
    base_url: str


class HashRing:
    def __init__(self, nodes: list[RingNode], vnodes: int = 64) -> None:
        if vnodes <= 0:
            raise ValueError("vnodes must be > 0")
        self._nodes = nodes
        self._vnodes = vnodes
        self._points: list[tuple[int, RingNode]] = []
        self._build()

    @property
    def nodes(self) -> list[RingNode]:
        return list(self._nodes)

    @property
    def vnodes(self) -> int:
        return self._vnodes

    def _build(self) -> None:
        points: list[tuple[int, RingNode]] = []
        for node in self._nodes:
            for i in range(self._vnodes):
                points.append((self._hash_int(f"{node.id}:{i}"), node))
        points.sort(key=lambda p: p[0])
        self._points = points

    @staticmethod
    def _hash_int(value: str) -> int:
        # sha1 is sufficient for distribution; keep 32 bits to simplify.
        digest = hashlib.sha1(value.encode("utf-8")).digest()
        return int.from_bytes(digest[:4], byteorder="big", signed=False)

    def owner_for_key(self, key: str) -> RingNode | None:
        if not self._points:
            return None

        key_hash = self._hash_int(key)
        lo, hi = 0, len(self._points)
        while lo < hi:
            mid = (lo + hi) // 2
            if self._points[mid][0] < key_hash:
                lo = mid + 1
            else:
                hi = mid

        if lo == len(self._points):
            return self._points[0][1]
        return self._points[lo][1]


def ring_from_config(config: DSkitySettings) -> tuple[HashRing, str]:
    kv_cfg = config.kv
    node_id = getattr(kv_cfg, "node_id", None)
    if not node_id:
        node_id = generate_node_id()
    ring_cfg = kv_cfg.ring

    vnodes = int(getattr(ring_cfg, "vnodes", 64))
    raw_nodes = getattr(ring_cfg, "nodes", []) or []

    nodes: list[RingNode] = []
    for raw in raw_nodes:
        if not isinstance(raw, dict):
            continue
        node = RingNode(
            id=str(raw.get("id", "")), base_url=str(raw.get("base_url", ""))
        )
        if node.id and node.base_url:
            nodes.append(node)

    return HashRing(nodes=nodes, vnodes=vnodes), str(node_id)


def ring_from_runtime(
    app: Any, config: DSkitySettings, *, service: str = "kvstore"
) -> tuple[HashRing, str]:
    """Build the ring from service discovery (registry) when available.

    Loki/Cortex-style pattern: the set of instances comes from the KV (service discovery),
    not from a static list in config.

    - Uses `app.state.registry_store` if present.
    - Fallback: `kv.ring.nodes` (static config).
    """

    # Prefer the global process instance_id (published in the registry), if present.
    instance_id = getattr(getattr(app, "state", None), "instance_id", None)

    kv_cfg = config.kv
    node_id = instance_id
    if not node_id:
        # Try to get node_id from config (if available)
        node_id = getattr(kv_cfg, "node_id", None)
    if not node_id:
        node_id = generate_node_id()

    vnodes = kv_cfg.ring.vnodes if kv_cfg and kv_cfg.ring else 64

    nodes: list[RingNode] = []

    store = getattr(getattr(app, "state", None), "registry_store", None)
    if store is not None:
        try:
            reg = ServiceRegistry(store=store)
            instances = reg.list_instances(service)
            seen: set[str] = set()
            for inst in instances:
                if not isinstance(inst, dict):
                    continue
                iid = inst.get("instance_id")
                base_url = inst.get("base_url")
                if not isinstance(iid, str) or not iid:
                    continue
                if not isinstance(base_url, str) or not base_url:
                    continue
                if iid in seen:
                    continue
                seen.add(iid)
                nodes.append(RingNode(id=iid, base_url=base_url.rstrip("/")))
        except Exception:
            # Silent fallback to static config.
            nodes = []

    if not nodes:
        # Try reading nodes from static config (ring.nodes)
        raw_nodes = []
        if kv_cfg and kv_cfg.ring:
            raw_nodes = getattr(kv_cfg.ring, "nodes", []) or []

        for raw in raw_nodes:
            if not isinstance(raw, dict):
                continue
            node = RingNode(
                id=str(raw.get("id", "")), base_url=str(raw.get("base_url", ""))
            )
            if node.id and node.base_url:
                nodes.append(node)

    return HashRing(nodes=nodes, vnodes=vnodes), str(node_id)
