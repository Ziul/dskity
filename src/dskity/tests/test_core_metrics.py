from __future__ import annotations

from fastapi import FastAPI
from fastapi.testclient import TestClient

from dskity.metrics import install_metrics


def test_metrics_endpoint_is_exposed() -> None:
    app = FastAPI()
    install_metrics(app)

    client = TestClient(app)
    resp = client.get("/metrics")

    assert resp.status_code == 200
    # prometheus_client defines the full content type
    assert resp.headers.get("content-type", "").startswith("text/plain")


def test_http_request_metrics_are_recorded_for_routes() -> None:
    app = FastAPI()

    @app.get("/hello")
    def hello() -> dict:
        return {"ok": True}

    install_metrics(app)

    client = TestClient(app)

    r1 = client.get("/hello")
    assert r1.status_code == 200

    r2 = client.get("/does-not-exist")
    assert r2.status_code == 404

    metrics = client.get("/metrics").text

    # Confirm custom metrics exist and that there was a count for /hello.
    assert "http_requests_total" in metrics
    assert "http_request_duration_seconds" in metrics
    assert 'route="/hello"' in metrics
    assert 'status="200"' in metrics
    # For 404, since there's no registered route, we use the scope path.
    assert 'route="/does-not-exist"' in metrics
    assert 'status="404"' in metrics
