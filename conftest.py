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

    # Optional cleanup after all tests
