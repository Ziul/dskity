"""Tests for dskity.testing – create_test_settings / create_test_app / create_test_client."""

from __future__ import annotations

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from dskity.config.settings import DSkitySettings
from dskity.testing import create_test_app, create_test_client, create_test_settings


# ── create_test_settings ──────────────────────────────────────────────────────

def test_create_test_settings_returns_dskity_settings() -> None:
    settings = create_test_settings()
    assert isinstance(settings, DSkitySettings)


def test_create_test_settings_default_name() -> None:
    assert create_test_settings().name == "test-service"


def test_create_test_settings_custom_name() -> None:
    assert create_test_settings("my-svc").name == "my-svc"


def test_create_test_settings_is_dskity_settings_subclass() -> None:
    from pydantic_settings import BaseSettings
    assert isinstance(create_test_settings(), BaseSettings)


def test_create_test_settings_modules_search_paths_has_value() -> None:
    settings = create_test_settings()
    assert isinstance(settings.modules_search_paths, list)
    assert len(settings.modules_search_paths) >= 1


# ── create_test_app ───────────────────────────────────────────────────────────

def test_create_test_app_returns_fastapi_instance() -> None:
    app = create_test_app()
    assert isinstance(app, FastAPI)


def test_create_test_app_with_settings_uses_name() -> None:
    settings = create_test_settings("billing-svc")
    app = create_test_app(settings)
    assert isinstance(app, FastAPI)
    assert app.title == "billing-svc"


def test_create_test_app_root_endpoint_responds() -> None:
    app = create_test_app()
    with TestClient(app) as client:
        resp = client.get("/")
        assert resp.status_code == 200
        assert "service" in resp.json()


def test_create_test_app_default_name_in_root() -> None:
    app = create_test_app()
    with TestClient(app) as client:
        data = client.get("/").json()
        assert data["service"] == "test-service"


def test_create_test_app_custom_name_in_root() -> None:
    app = create_test_app(name="custom-svc")
    with TestClient(app) as client:
        data = client.get("/").json()
        assert data["service"] == "custom-svc"


def test_create_test_app_none_settings_works() -> None:
    app = create_test_app(None)
    assert isinstance(app, FastAPI)


def test_create_test_app_has_health_endpoint() -> None:
    app = create_test_app()
    with TestClient(app) as client:
        assert client.get("/health/live").status_code == 200


def test_create_test_app_has_metrics_endpoint() -> None:
    app = create_test_app()
    with TestClient(app) as client:
        assert client.get("/metrics").status_code == 200


# ── create_test_client ────────────────────────────────────────────────────────

def test_create_test_client_none_returns_test_client() -> None:
    client = create_test_client()
    assert isinstance(client, TestClient)


def test_create_test_client_with_app() -> None:
    app = create_test_app()
    client = create_test_client(app)
    assert isinstance(client, TestClient)


def test_create_test_client_with_settings() -> None:
    settings = create_test_settings()
    client = create_test_client(settings)
    assert isinstance(client, TestClient)


def test_create_test_client_root_endpoint_accessible() -> None:
    with create_test_client() as client:
        assert client.get("/").status_code == 200


def test_create_test_client_health_live_accessible() -> None:
    with create_test_client() as client:
        assert client.get("/health/live").status_code == 200


def test_create_test_client_root_reports_service_name() -> None:
    settings = create_test_settings("payment-svc")
    with create_test_client(settings) as client:
        data = client.get("/").json()
        assert data["service"] == "payment-svc"


# ── dskity_settings / dskity_app / dskity_client fixtures ────────────────────

def test_dskity_settings_fixture_type(dskity_settings) -> None:
    assert isinstance(dskity_settings, DSkitySettings)


def test_dskity_settings_fixture_default_name(dskity_settings) -> None:
    assert dskity_settings.name == "test-service"


def test_dskity_app_fixture_type(dskity_app) -> None:
    assert isinstance(dskity_app, FastAPI)


def test_dskity_client_fixture_root(dskity_client) -> None:
    resp = dskity_client.get("/")
    assert resp.status_code == 200
    assert "service" in resp.json()


def test_dskity_client_health_endpoint(dskity_client) -> None:
    assert dskity_client.get("/health/live").status_code == 200


def test_dskity_client_metrics_endpoint(dskity_client) -> None:
    assert dskity_client.get("/metrics").status_code == 200
