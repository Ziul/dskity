"""Testing utilities for dskity module developers.

Provides helpers for creating test apps, settings, and test clients
without needing a real YAML config file or external services.
"""

from __future__ import annotations

import os
import tempfile
import textwrap
from contextlib import contextmanager
from typing import Any

import yaml
from fastapi import FastAPI
from fastapi.testclient import TestClient as _TestClient

from dskity.config.settings import DSkitySettings


def create_test_settings(
    name: str = "test-service",
    **extra: Any,
) -> DSkitySettings:
    """Create a :class:`~dskity.config.settings.DSkitySettings` for tests.

    All external services are disabled by default so tests require no
    running KV store, MQTT broker, or service registry.

    Args:
        name: Service name.
        **extra: Additional keyword arguments forwarded to :class:`DSkitySettings`.

    Returns:
        A ready-to-use settings object.
    """
    return DSkitySettings(
        name=name,
        modules_search_paths=["dskity.modules"],
        **extra,
    )


@contextmanager
def _temp_config_file(name: str = "test-service", extra_yaml: str = ""):
    """Context manager that writes a minimal config YAML to a temp file."""
    content = textwrap.dedent(f"""\
        name: {name}
        modules_search_paths:
          - dskity.modules
        common:
          registry:
            enabled: false
        {extra_yaml}
    """)
    with tempfile.NamedTemporaryFile(
        mode="w", suffix=".yaml", delete=False
    ) as f:
        f.write(content)
        path = f.name
    try:
        yield path
    finally:
        try:
            os.unlink(path)
        except FileNotFoundError:
            pass


def create_test_app(
    settings: DSkitySettings | None = None,
    *,
    name: str = "test-service",
    extra_yaml: str = "",
) -> FastAPI:
    """Create a fully bootstrapped :class:`~fastapi.FastAPI` application for tests.

    Points ``DSKITY_CONFIG`` at a minimal in-memory YAML config so that
    bootstrap succeeds without any external services.

    Args:
        settings: Ignored (kept for API compatibility). The app is always
            bootstrapped from a minimal generated config.
        name: Service name to embed in the generated config.
        extra_yaml: Additional YAML text appended to the generated config.

    Returns:
        A bootstrapped FastAPI app.
    """
    import logging
    from dskity.bootstrap import bootstrap
    from dskity.logging import configure_logging

    svc_name = (settings.name if settings is not None else None) or name

    with _temp_config_file(svc_name, extra_yaml) as cfg_path:
        old_cfg = os.environ.get("DSKITY_CONFIG")
        os.environ["DSKITY_CONFIG"] = cfg_path
        try:
            configure_logging(level="WARNING", log_format="text")
            app = FastAPI(title=svc_name)
            app.state.logger = logging.getLogger("dskity")
            bootstrap(app)
        finally:
            if old_cfg is None:
                os.environ.pop("DSKITY_CONFIG", None)
            else:
                os.environ["DSKITY_CONFIG"] = old_cfg

    return app


def create_test_client(
    app_or_settings: "FastAPI | DSkitySettings | None" = None,
    **client_kwargs: Any,
) -> _TestClient:
    """Create a :class:`~fastapi.testclient.TestClient` for a dskity app.

    Args:
        app_or_settings: An already-bootstrapped app, a settings object
            (app will be created), or *None* (a minimal default app is created).
        **client_kwargs: Keyword arguments forwarded to :class:`~fastapi.testclient.TestClient`.

    Returns:
        A configured ``TestClient``.
    """
    if isinstance(app_or_settings, FastAPI):
        app = app_or_settings
    elif isinstance(app_or_settings, DSkitySettings):
        app = create_test_app(app_or_settings)
    else:
        app = create_test_app()

    return _TestClient(app, **client_kwargs)
