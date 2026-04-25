from __future__ import annotations

import os

from fastapi.testclient import TestClient

import dskity.bootstrap as bootstrap_mod
from dskity.app import create_app


def test_lifespan_starts_and_stops_heartbeat(monkeypatch) -> None:
    calls: list[str] = []

    def fake_start_heartbeat(app, *, cfg):  # noqa: ANN001
        calls.append(f"start:{cfg.ttl_seconds}:{cfg.interval_seconds}")

    async def fake_stop_heartbeat(app):  # noqa: ANN001
        calls.append("stop")

    monkeypatch.setattr(bootstrap_mod, "start_heartbeat", fake_start_heartbeat)
    monkeypatch.setattr(bootstrap_mod, "stop_heartbeat", fake_stop_heartbeat)

    # Ensure advertise_url exists so start_heartbeat does not return early.
    monkeypatch.setenv("DSKITY_ADVERTISE_URL", "http://127.0.0.1:8000")

    app = create_app()

    with TestClient(app) as client:
        r = client.get("/")
        assert r.status_code == 200

    assert any(c.startswith("start:") for c in calls)
    assert "stop" in calls

    # Clean env variables so they don't leak into other tests (monkeypatch already handles this, but keep explicit)
    os.environ.pop("DSKITY_ADVERTISE_URL", None)
