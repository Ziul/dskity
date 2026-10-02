from __future__ import annotations

import asyncio
from types import SimpleNamespace

from dskity.kvstore.backends import InMemoryKVBackend
from dskity.registry.heartbeat import HeartbeatConfig, start_heartbeat, stop_heartbeat
from dskity.registry.middleware import EnabledModuleInfo
from dskity.registry.service_registry import ServiceRegistry
from dskity.registry.store import RegistryStore


def test_heartbeat_registers_without_explicit_advertise_url(monkeypatch):
    """Regression test.

    When no `advertise_url` is explicitly configured (the recommended setup
    for Kubernetes, where `--host 0.0.0.0` is a wildcard bind address), the
    heartbeat loop used to bail out immediately, relying entirely on the
    per-request middleware to register the instance reactively. That left
    replicas that never happen to receive an inbound HTTP request (e.g.
    idle pods behind a Service that hasn't routed traffic to them yet)
    permanently absent from the registry — invisible to other replicas
    doing service discovery, even though they are healthy and running.

    The heartbeat must proactively register using the same auto-detected
    host (cached `app.state.local_ip`) used elsewhere, regardless of
    whether this instance has ever served a request.
    """

    monkeypatch.setenv("DSKITY_HOST", "0.0.0.0")
    monkeypatch.setenv("DSKITY_PORT", "8000")

    backend = InMemoryKVBackend()
    store = RegistryStore(backend=backend)

    app = SimpleNamespace(
        state=SimpleNamespace(
            registry_store=store,
            enabled_modules=[EnabledModuleInfo(name="examples", base_path="/examples")],
            instance_id="pod-never-hit-by-a-request:1",
            advertise_url=None,
            local_ip="10.20.12.200",
        )
    )

    async def _scenario() -> None:
        start_heartbeat(app, cfg=HeartbeatConfig(ttl_seconds=60, interval_seconds=0.05))
        try:
            # Give the background loop a moment to run at least one iteration.
            await asyncio.sleep(0.1)

            reg = ServiceRegistry(store=store)
            instances = reg.list_instances("examples")
            assert len(instances) == 1
            assert instances[0]["base_url"] == "http://10.20.12.200:8000"
        finally:
            await stop_heartbeat(app)

    asyncio.run(_scenario())
