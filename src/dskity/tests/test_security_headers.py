"""Tests for dskity.security_headers – SecurityHeadersMiddleware."""

from __future__ import annotations

import asyncio
from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from dskity.security_headers import SecurityHeadersMiddleware


# ── Helpers ───────────────────────────────────────────────────────────────────

def _make_settings(**kwargs):
    """Build a SimpleNamespace that looks like SecurityHeadersSettings."""
    defaults = {
        "enabled": True,
        "x_content_type_options": "nosniff",
        "x_frame_options": "DENY",
        "strict_transport_security": None,
        "content_security_policy": None,
        "referrer_policy": "strict-origin-when-cross-origin",
        "x_xss_protection": "1; mode=block",
        "permissions_policy": None,
        "custom_headers": {},
    }
    defaults.update(kwargs)
    return SimpleNamespace(**defaults)


def _make_app(settings) -> FastAPI:
    app = FastAPI()
    app.add_middleware(SecurityHeadersMiddleware, settings=settings)

    @app.get("/ping")
    def ping():
        return {"ok": True}

    return app


# ── Header injection ──────────────────────────────────────────────────────────

def test_injects_x_content_type_options() -> None:
    client = TestClient(_make_app(_make_settings()))
    resp = client.get("/ping")
    assert resp.headers["x-content-type-options"] == "nosniff"


def test_injects_x_frame_options() -> None:
    client = TestClient(_make_app(_make_settings()))
    resp = client.get("/ping")
    assert resp.headers["x-frame-options"] == "DENY"


def test_injects_referrer_policy() -> None:
    client = TestClient(_make_app(_make_settings()))
    resp = client.get("/ping")
    assert resp.headers["referrer-policy"] == "strict-origin-when-cross-origin"


def test_injects_x_xss_protection() -> None:
    client = TestClient(_make_app(_make_settings()))
    resp = client.get("/ping")
    assert resp.headers["x-xss-protection"] == "1; mode=block"


def test_injects_hsts_when_configured() -> None:
    settings = _make_settings(strict_transport_security="max-age=63072000; includeSubDomains")
    client = TestClient(_make_app(settings))
    resp = client.get("/ping")
    assert resp.headers["strict-transport-security"] == "max-age=63072000; includeSubDomains"


def test_injects_csp_when_configured() -> None:
    settings = _make_settings(content_security_policy="default-src 'self'")
    client = TestClient(_make_app(settings))
    resp = client.get("/ping")
    assert resp.headers["content-security-policy"] == "default-src 'self'"


def test_injects_permissions_policy_when_configured() -> None:
    settings = _make_settings(permissions_policy="geolocation=()")
    client = TestClient(_make_app(settings))
    resp = client.get("/ping")
    assert resp.headers["permissions-policy"] == "geolocation=()"


# ── Custom headers ────────────────────────────────────────────────────────────

def test_injects_custom_headers() -> None:
    settings = _make_settings(custom_headers={"X-My-Header": "my-value"})
    client = TestClient(_make_app(settings))
    resp = client.get("/ping")
    assert resp.headers["x-my-header"] == "my-value"


def test_custom_header_name_lowercased() -> None:
    settings = _make_settings(custom_headers={"X-UPPER": "val"})
    client = TestClient(_make_app(settings))
    resp = client.get("/ping")
    assert resp.headers["x-upper"] == "val"


def test_custom_header_with_empty_value_not_injected() -> None:
    settings = _make_settings(custom_headers={"X-Empty": ""})
    client = TestClient(_make_app(settings))
    resp = client.get("/ping")
    assert "x-empty" not in resp.headers


def test_custom_header_with_empty_name_not_injected() -> None:
    settings = _make_settings(custom_headers={"": "orphan"})
    client = TestClient(_make_app(settings))
    resp = client.get("/ping")
    assert "orphan" not in resp.headers.values()


# ── Null / disabled values ────────────────────────────────────────────────────

def test_null_optional_header_not_injected() -> None:
    settings = _make_settings(strict_transport_security=None, content_security_policy=None)
    client = TestClient(_make_app(settings))
    resp = client.get("/ping")
    assert "strict-transport-security" not in resp.headers
    assert "content-security-policy" not in resp.headers


def test_empty_string_optional_header_not_injected() -> None:
    settings = _make_settings(x_frame_options="")
    client = TestClient(_make_app(settings))
    resp = client.get("/ping")
    assert "x-frame-options" not in resp.headers


# ── No headers when list is empty ─────────────────────────────────────────────

def test_no_headers_injected_when_all_fields_empty_or_none() -> None:
    settings = _make_settings(
        x_content_type_options="",
        x_frame_options="",
        strict_transport_security=None,
        content_security_policy=None,
        referrer_policy="",
        x_xss_protection="",
        permissions_policy=None,
        custom_headers={},
    )
    app = _make_app(settings)
    client = TestClient(app)
    resp = client.get("/ping")
    for h in ["x-content-type-options", "x-frame-options", "referrer-policy", "x-xss-protection"]:
        assert h not in resp.headers


# ── Non-HTTP scopes are passed through untouched ──────────────────────────────

def test_non_http_scope_passes_through() -> None:
    """WebSocket/lifespan scopes must not be intercepted."""
    settings = _make_settings()
    received_scopes: list = []

    async def dummy_app(scope, receive, send):
        received_scopes.append(scope["type"])

    middleware = SecurityHeadersMiddleware(dummy_app, settings=settings)
    asyncio.run(middleware({"type": "lifespan"}, None, None))
    assert received_scopes == ["lifespan"]


# ── Headers present on every response ────────────────────────────────────────

def test_headers_present_on_404_response() -> None:
    client = TestClient(_make_app(_make_settings()), raise_server_exceptions=False)
    resp = client.get("/nonexistent")
    assert resp.headers.get("x-content-type-options") == "nosniff"


def test_headers_present_on_error_response() -> None:
    """Headers are injected on 4xx responses that go through the normal ASGI path."""
    from fastapi import HTTPException

    app = FastAPI()
    app.add_middleware(SecurityHeadersMiddleware, settings=_make_settings())

    @app.get("/err")
    def err():
        raise HTTPException(status_code=400, detail="bad request")

    client = TestClient(app, raise_server_exceptions=False)
    resp = client.get("/err")
    assert resp.status_code == 400
    assert resp.headers.get("x-content-type-options") == "nosniff"


# ── Pre-computed headers (idempotency of _build_headers) ─────────────────────

def test_headers_precomputed_at_init() -> None:
    settings = _make_settings()
    app = FastAPI()
    middleware = SecurityHeadersMiddleware(app, settings=settings)
    original_headers = list(middleware._headers)

    # Headers should not change between requests
    assert middleware._headers == original_headers
