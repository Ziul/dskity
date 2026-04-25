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

    # Garante que advertise_url exista para o start_heartbeat não retornar cedo.
    monkeypatch.setenv("DSKITY_ADVERTISE_URL", "http://127.0.0.1:8000")

    app = create_app()

    with TestClient(app) as client:
        r = client.get("/")
        assert r.status_code == 200

    assert any(c.startswith("start:") for c in calls)
    assert "stop" in calls

    # limpeza do env para não vazar em outros testes (monkeypatch já faz isso, mas mantém explícito)
    os.environ.pop("DSKITY_ADVERTISE_URL", None)
