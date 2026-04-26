from __future__ import annotations

import time
from types import SimpleNamespace

from dskity.kvstore.backends import InMemoryKVBackend
from dskity.kvstore.ring import ring_from_runtime
from dskity.registry.service_registry import ServiceRegistry
from dskity.registry.store import RegistryStore


def test_ring_from_runtime_uses_registry_instances() -> None:
    now = int(time.time())
    backend = InMemoryKVBackend()
    store = RegistryStore(backend=backend)

    reg = ServiceRegistry(store=store)
    reg.register_instance(
        service="kvstore",
        instance_id="node-a",
        base_url="http://127.0.0.1:9001",
        route="",
        ttl_seconds=60,
        now=now,
    )
    reg.register_instance(
        service="kvstore",
        instance_id="node-b",
        base_url="http://127.0.0.1:9002",
        route="",
        ttl_seconds=60,
        now=now,
    )

    from dskity.config.settings import DSkitySettings

    app = SimpleNamespace(
        state=SimpleNamespace(registry_store=store, instance_id="node-a")
    )
    cfg = DSkitySettings.model_validate({"kv": {"ring": {"vnodes": 8}}})

    ring, node_id = ring_from_runtime(app, cfg)

    assert node_id == "node-a"
    assert sorted(n.id for n in ring.nodes) == ["node-a", "node-b"]
    assert {n.base_url for n in ring.nodes} == {
        "http://127.0.0.1:9001",
        "http://127.0.0.1:9002",
    }

    owner = ring.owner_for_key("some-key")
    assert owner is not None
    assert owner.id in {"node-a", "node-b"}
