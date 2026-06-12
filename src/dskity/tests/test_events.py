"""Tests for dskity.events – in-process event bus."""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock

import pytest

from dskity.events import EventBus


def _run(coro):
    """Helper: run a coroutine in a new event loop."""
    return asyncio.run(coro)


# ── Registration ──────────────────────────────────────────────────────────────

def test_on_registers_handler() -> None:
    bus = EventBus()
    handler = AsyncMock()
    bus.on("evt", handler)
    assert bus.handler_count("evt") == 1


def test_on_idempotent_same_handler() -> None:
    bus = EventBus()
    handler = AsyncMock()
    bus.on("evt", handler)
    bus.on("evt", handler)
    assert bus.handler_count("evt") == 1


def test_on_allows_multiple_different_handlers() -> None:
    bus = EventBus()
    bus.on("evt", AsyncMock())
    bus.on("evt", AsyncMock())
    assert bus.handler_count("evt") == 2


def test_off_removes_handler() -> None:
    bus = EventBus()
    handler = AsyncMock()
    bus.on("evt", handler)
    bus.off("evt", handler)
    assert bus.handler_count("evt") == 0


def test_off_noop_for_unregistered_handler() -> None:
    bus = EventBus()
    bus.off("evt", AsyncMock())
    assert bus.handler_count("evt") == 0


def test_off_noop_for_unknown_event() -> None:
    bus = EventBus()
    bus.off("nonexistent", AsyncMock())


# ── Emit ──────────────────────────────────────────────────────────────────────

def test_emit_calls_handler_with_data() -> None:
    bus = EventBus()
    received = []

    async def handler(data):
        received.append(data)

    bus.on("order.created", handler)
    count = _run(bus.emit("order.created", {"id": 1}))

    assert count == 1
    assert received == [{"id": 1}]


def test_emit_returns_zero_for_no_handlers() -> None:
    bus = EventBus()
    assert _run(bus.emit("ghost.event", "data")) == 0


def test_emit_returns_handler_count() -> None:
    bus = EventBus()
    bus.on("x", AsyncMock())
    bus.on("x", AsyncMock())
    assert _run(bus.emit("x", None)) == 2


def test_emit_passes_none_data_by_default() -> None:
    bus = EventBus()
    received = []

    async def handler(data):
        received.append(data)

    bus.on("ping", handler)
    _run(bus.emit("ping"))
    assert received == [None]


def test_emit_calls_all_handlers() -> None:
    bus = EventBus()
    order = []

    async def h1(data): order.append("h1")
    async def h2(data): order.append("h2")

    bus.on("tick", h1)
    bus.on("tick", h2)
    _run(bus.emit("tick", None))

    assert set(order) == {"h1", "h2"}


def test_emit_isolates_handler_errors() -> None:
    """A failing handler must not prevent other handlers from running."""
    bus = EventBus()
    called = []

    async def bad_handler(data):
        raise ValueError("boom")

    async def good_handler(data):
        called.append(data)

    bus.on("evt", bad_handler)
    bus.on("evt", good_handler)

    count = _run(bus.emit("evt", "payload"))

    assert count == 2
    assert called == ["payload"]


def test_emit_does_not_affect_other_event_handlers() -> None:
    bus = EventBus()
    received_a: list = []
    received_b: list = []

    async def ha(data): received_a.append(data)
    async def hb(data): received_b.append(data)

    bus.on("a", ha)
    bus.on("b", hb)

    _run(bus.emit("a", 1))
    assert received_a == [1]
    assert received_b == []

    _run(bus.emit("b", 2))
    assert received_b == [2]
    assert received_a == [1]


# ── list_events ───────────────────────────────────────────────────────────────

def test_list_events_empty_on_new_bus() -> None:
    assert EventBus().list_events() == []


def test_list_events_shows_registered_events() -> None:
    bus = EventBus()
    bus.on("alpha", AsyncMock())
    bus.on("beta", AsyncMock())
    assert set(bus.list_events()) == {"alpha", "beta"}


def test_list_events_excludes_event_after_all_handlers_removed() -> None:
    bus = EventBus()
    handler = AsyncMock()
    bus.on("evt", handler)
    bus.off("evt", handler)
    assert "evt" not in bus.list_events()


# ── handler_count ─────────────────────────────────────────────────────────────

def test_handler_count_zero_for_unknown_event() -> None:
    assert EventBus().handler_count("nope") == 0


def test_handler_count_increments_and_decrements() -> None:
    bus = EventBus()
    h1, h2 = AsyncMock(), AsyncMock()
    bus.on("e", h1)
    assert bus.handler_count("e") == 1
    bus.on("e", h2)
    assert bus.handler_count("e") == 2
    bus.off("e", h1)
    assert bus.handler_count("e") == 1


# ── Edge cases ────────────────────────────────────────────────────────────────

def test_emit_snapshot_prevents_reentrancy() -> None:
    """Handlers added DURING emit are not called in the same cycle."""
    bus = EventBus()
    secondary_called: list = []

    async def secondary(data):
        secondary_called.append(data)

    async def primary(data):
        bus.on("evt", secondary)

    bus.on("evt", primary)
    _run(bus.emit("evt", "hello"))
    assert secondary_called == []

    _run(bus.emit("evt", "world"))
    assert secondary_called == ["world"]


def test_emit_with_complex_payload() -> None:
    bus = EventBus()
    received: list = []

    async def handler(data): received.append(data)

    bus.on("complex", handler)
    payload = {"nested": {"list": [1, 2, 3]}, "flag": True}
    _run(bus.emit("complex", payload))
    assert received[0] == payload


def test_multiple_emits_accumulate_results() -> None:
    bus = EventBus()
    counts: list = []

    async def counter(data): counts.append(data)

    bus.on("inc", counter)
    _run(bus.emit("inc", 1))
    _run(bus.emit("inc", 2))
    _run(bus.emit("inc", 3))
    assert counts == [1, 2, 3]


def test_emit_on_empty_bus_is_safe() -> None:
    bus = EventBus()
    for event in ("a", "b", "c"):
        assert _run(bus.emit(event, None)) == 0


def test_all_handlers_raise_does_not_propagate() -> None:
    bus = EventBus()

    async def fail_a(data):
        raise RuntimeError("always a")

    async def fail_b(data):
        raise RuntimeError("always b")

    bus.on("bad", fail_a)
    bus.on("bad", fail_b)

    count = _run(bus.emit("bad", "x"))
    assert count == 2
