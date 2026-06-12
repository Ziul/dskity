"""Tests for dskity.transport.http_client – HttpClientManager."""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock

import httpx
import pytest

from dskity.transport.http_client import HttpClientManager


def _run(coro):
    return asyncio.run(coro)


# ── Lifecycle ─────────────────────────────────────────────────────────────────

def test_start_creates_client() -> None:
    async def _t():
        m = HttpClientManager()
        assert m._client is None
        await m.start()
        assert m._client is not None
        await m.stop()
    _run(_t())


def test_start_idempotent() -> None:
    async def _t():
        m = HttpClientManager()
        await m.start()
        first = m._client
        await m.start()
        assert m._client is first
        await m.stop()
    _run(_t())


def test_stop_closes_client() -> None:
    async def _t():
        m = HttpClientManager()
        await m.start()
        await m.stop()
        assert m._client is None
    _run(_t())


def test_stop_noop_if_never_started() -> None:
    async def _t():
        m = HttpClientManager()
        await m.stop()  # should not raise
        assert m._client is None
    _run(_t())


def test_start_after_stop_creates_new_client() -> None:
    async def _t():
        m = HttpClientManager()
        await m.start()
        first = m._client
        await m.stop()
        await m.start()
        assert m._client is not None
        assert m._client is not first
        await m.stop()
    _run(_t())


# ── .client property ──────────────────────────────────────────────────────────

def test_client_property_raises_before_start() -> None:
    m = HttpClientManager()
    with pytest.raises(RuntimeError, match="not initialized"):
        _ = m.client


def test_client_property_returns_async_client_after_start() -> None:
    async def _t():
        m = HttpClientManager()
        await m.start()
        assert isinstance(m.client, httpx.AsyncClient)
        await m.stop()
    _run(_t())


def test_client_property_raises_after_stop() -> None:
    async def _t():
        m = HttpClientManager()
        await m.start()
        await m.stop()
        with pytest.raises(RuntimeError, match="not initialized"):
            _ = m.client
    _run(_t())


# ── Configuration ─────────────────────────────────────────────────────────────

def test_custom_timeout_applied() -> None:
    async def _t():
        m = HttpClientManager(timeout=5.0)
        await m.start()
        assert m.client.timeout.connect == 5.0
        await m.stop()
    _run(_t())


def test_default_timeout() -> None:
    async def _t():
        m = HttpClientManager()
        await m.start()
        assert m.client.timeout.read == 10.0
        await m.stop()
    _run(_t())


# ── Convenience methods (patched AsyncClient) ─────────────────────────────────

def test_get_delegates_to_client() -> None:
    async def _t():
        m = HttpClientManager()
        await m.start()
        mock_resp = MagicMock(spec=httpx.Response)
        m._client.get = AsyncMock(return_value=mock_resp)
        result = await m.get("http://svc/path", params={"q": 1})
        m._client.get.assert_awaited_once_with("http://svc/path", params={"q": 1})
        assert result is mock_resp
        await m.stop()
    _run(_t())


def test_post_delegates_to_client() -> None:
    async def _t():
        m = HttpClientManager()
        await m.start()
        mock_resp = MagicMock(spec=httpx.Response)
        m._client.post = AsyncMock(return_value=mock_resp)
        result = await m.post("http://svc/path", json={"data": 1})
        m._client.post.assert_awaited_once_with("http://svc/path", json={"data": 1})
        assert result is mock_resp
        await m.stop()
    _run(_t())


def test_put_delegates_to_client() -> None:
    async def _t():
        m = HttpClientManager()
        await m.start()
        mock_resp = MagicMock(spec=httpx.Response)
        m._client.put = AsyncMock(return_value=mock_resp)
        result = await m.put("http://svc/path", json={"val": 42})
        m._client.put.assert_awaited_once_with("http://svc/path", json={"val": 42})
        assert result is mock_resp
        await m.stop()
    _run(_t())


def test_delete_delegates_to_client() -> None:
    async def _t():
        m = HttpClientManager()
        await m.start()
        mock_resp = MagicMock(spec=httpx.Response)
        m._client.delete = AsyncMock(return_value=mock_resp)
        result = await m.delete("http://svc/path")
        m._client.delete.assert_awaited_once_with("http://svc/path")
        assert result is mock_resp
        await m.stop()
    _run(_t())


# ── Same client instance reused ───────────────────────────────────────────────

def test_same_client_instance_across_calls() -> None:
    async def _t():
        m = HttpClientManager()
        await m.start()
        ref = m.client
        mock_resp = MagicMock(spec=httpx.Response)
        m._client.get = AsyncMock(return_value=mock_resp)
        await m.get("http://a/")
        await m.get("http://b/")
        assert m.client is ref
        await m.stop()
    _run(_t())
