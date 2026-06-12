"""pytest plugin providing built-in fixtures for dskity module developers.

Registered as a pytest11 entry-point so it is auto-discovered when dskity
is installed in a project that uses pytest.

Fixtures
--------
dskity_settings
    A :class:`~dskity.config.settings.DSkitySettings` suitable for unit tests.
dskity_app
    A fully bootstrapped :class:`~fastapi.FastAPI` app.
dskity_client
    A :class:`~fastapi.testclient.TestClient` wrapping ``dskity_app``.
"""

from __future__ import annotations

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from dskity.config.settings import DSkitySettings
from dskity.testing import create_test_app, create_test_settings


@pytest.fixture(scope="session")
def dskity_settings() -> DSkitySettings:
    """Session-scoped settings with all external services disabled.

    Override in your conftest.py to provide custom settings::

        @pytest.fixture(scope="session")
        def dskity_settings():
            return create_test_settings(name="my-service")
    """
    return create_test_settings()


@pytest.fixture(scope="session")
def dskity_app(dskity_settings: DSkitySettings) -> FastAPI:
    """Session-scoped bootstrapped FastAPI app."""
    return create_test_app(dskity_settings)


@pytest.fixture
def dskity_client(dskity_app: FastAPI) -> TestClient:
    """Function-scoped test client for the bootstrapped app."""
    with TestClient(dskity_app, raise_server_exceptions=True) as client:
        yield client  # type: ignore[misc]
