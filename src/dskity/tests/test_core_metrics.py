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
    # prometheus_client define o content type completo
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

    # Confirma que as métricas customizadas existem e que houve contagem para /hello.
    assert "http_requests_total" in metrics
    assert "http_request_duration_seconds" in metrics
    assert 'route="/hello"' in metrics
    assert 'status="200"' in metrics
    # Para 404, como não há rota registrada, usamos o path do scope.
    assert 'route="/does-not-exist"' in metrics
    assert 'status="404"' in metrics
