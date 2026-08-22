"""Global pytest configuration for all tests."""

from __future__ import annotations

import os

# IMPORTANT: Set environment variables BEFORE any imports
# to avoid modules attempting to connect to real databases
if not os.getenv("BIOSTATION_PERSON_DATABASE_URL"):
    os.environ["BIOSTATION_PERSON_DATABASE_URL"] = "sqlite:///:memory:"

import pytest


@pytest.fixture(scope="session", autouse=True)
def setup_test_environment():
    """
    Set up the test environment.

    Environment variable configuration is performed at module level
    to ensure it runs before any imports.
    """
    yield

    # Cleanup OpenTelemetry tracer provider after all tests
    # This prevents threads from trying to export/log after pytest shuts down
    try:
        from opentelemetry import trace
        from opentelemetry.sdk.trace import TracerProvider
        
        provider = trace.get_tracer_provider()
        if isinstance(provider, TracerProvider):
            # Force flush and shutdown to stop the batch processor thread
            provider.force_flush(timeout_millis=1000)
            provider.shutdown()
    except Exception:
        # Silently ignore any cleanup errors
        pass
