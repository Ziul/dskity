from __future__ import annotations

from fastapi import FastAPI, Request
from fastapi.testclient import TestClient

from dskity.request_id import REQUEST_ID_HEADER, get_request_id, install_request_id


def test_request_id_is_generated_and_returned_in_header() -> None:
    app = FastAPI()
    install_request_id(app)

    @app.get("/rid")
    def rid(request: Request) -> dict:
        return {
            "state": getattr(request.state, "request_id", None),
            "ctx": get_request_id(),
        }

    client = TestClient(app)
    resp = client.get("/rid")

    assert resp.status_code == 200
    assert REQUEST_ID_HEADER in resp.headers
    data = resp.json()
    assert data["state"]
    assert data["ctx"]
    assert data["state"] == data["ctx"]
    assert resp.headers[REQUEST_ID_HEADER] == data["state"]


def test_request_id_propagates_when_provided_by_client() -> None:
    app = FastAPI()
    install_request_id(app)

    @app.get("/rid")
    def rid(request: Request) -> dict:
        return {"rid": request.state.request_id, "ctx": get_request_id()}

    client = TestClient(app)
    resp = client.get("/rid", headers={REQUEST_ID_HEADER: "rid-abc-123"})

    assert resp.status_code == 200
    assert resp.headers[REQUEST_ID_HEADER] == "rid-abc-123"
    assert resp.json() == {"rid": "rid-abc-123", "ctx": "rid-abc-123"}


def test_request_id_is_available_during_response_start() -> None:
    app = FastAPI()
    install_request_id(app)

    @app.get("/ok")
    def ok() -> dict:
        # Ensure the ContextVar is also present during handler execution.
        assert get_request_id() == "rid-abc-123"
        return {"ok": True}

    captured: dict[str, str | None] = {"rid": None}

    async def asgi_call() -> None:
        scope = {
            "type": "http",
            "asgi": {"version": "3.0"},
            "http_version": "1.1",
            "method": "GET",
            "scheme": "http",
            "path": "/ok",
            "raw_path": b"/ok",
            "query_string": b"",
            "headers": [(b"x-request-id", b"rid-abc-123")],
            "client": ("127.0.0.1", 12345),
            "server": ("testserver", 80),
        }

        async def receive():
            return {"type": "http.request", "body": b"", "more_body": False}

        async def send(message):
            if message.get("type") == "http.response.start":
                # This is the moment when uvicorn.access usually logs.
                captured["rid"] = get_request_id()

        await app(scope, receive, send)

    import asyncio

    asyncio.run(asgi_call())
    assert captured["rid"] == "rid-abc-123"
