from __future__ import annotations

import time

from dskity.kvstore.backends import InMemoryKVBackend


def test_inmemory_ttl_expires(monkeypatch) -> None:
    now = 1_700_000_000

    def fake_time() -> float:
        return float(now)

    monkeypatch.setattr(time, "time", fake_time)

    kv = InMemoryKVBackend()
    kv.put("k", {"v": 1}, ttl_seconds=10)
    assert kv.get("k") == {"v": 1}

    now += 11
    assert kv.get("k") is None


def test_inmemory_keys_prunes_expired(monkeypatch) -> None:
    now = 1_700_000_000

    def fake_time() -> float:
        return float(now)

    monkeypatch.setattr(time, "time", fake_time)

    kv = InMemoryKVBackend()
    kv.put("a", 1, ttl_seconds=5)
    kv.put("b", 2, ttl_seconds=None)

    now += 6
    assert kv.keys() == ["b"]
