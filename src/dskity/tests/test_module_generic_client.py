from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import Any

from fastapi import APIRouter, FastAPI

from dskity.config.settings import DSkitySettings
from dskity.modules.contracts import Module, ModuleMeta, TransportClients


class _FakeResponse:
    def __init__(self, payload: dict[str, Any], *, status_code: int = 200) -> None:
        self._payload = payload
        self.status_code = status_code
        self.text = str(payload)
        self.headers = {"content-type": "application/json"}

    def raise_for_status(self) -> None:
        if self.status_code >= 400:
            raise RuntimeError(f"HTTP {self.status_code}")

    def json(self) -> dict[str, Any]:
        return self._payload


class _FakeHttpClient:
    def __init__(self) -> None:
        self.calls: list[tuple[str, str, dict[str, Any]]] = []

    async def get(self, url: str, **kwargs: Any) -> _FakeResponse:
        self.calls.append(("get", url, kwargs))
        if "/factorial/" in url:
            n = int(url.rsplit("/", 1)[-1])
            return _FakeResponse({"result": n})
        return _FakeResponse({"ok": True})

    async def post(self, url: str, **kwargs: Any) -> _FakeResponse:
        self.calls.append(("post", url, kwargs))
        return _FakeResponse({"ok": True, "url": url})

    async def put(self, url: str, **kwargs: Any) -> _FakeResponse:
        self.calls.append(("put", url, kwargs))
        return _FakeResponse({"ok": True})

    async def patch(self, url: str, **kwargs: Any) -> _FakeResponse:
        self.calls.append(("patch", url, kwargs))
        return _FakeResponse({"ok": True})

    async def delete(self, url: str, **kwargs: Any) -> _FakeResponse:
        self.calls.append(("delete", url, kwargs))
        return _FakeResponse({"ok": True})


class _FakeResolver:
    def __init__(self, base_url: str) -> None:
        self.base_url = base_url.rstrip("/")

    def get(self, service: str) -> str:
        return self.base_url


@dataclass(frozen=True)
class DemoModule(Module):
    meta: ModuleMeta = ModuleMeta(name="demo", base_path="/demo")

    def additional_settings_model(self):
        return None

    def register(self, clients: TransportClients, config: DSkitySettings) -> None:
        router = APIRouter(prefix=self.meta.base_path, tags=[self.meta.name])

        @router.get("/factorial/{n}")
        async def factorial(n: int) -> dict[str, int]:
            return {"result": n}

        @router.post("/events/emit")
        async def emit_event() -> dict[str, bool]:
            return {"ok": True}

        @router.get("/events")
        async def events() -> dict[str, list[str]]:
            return {"events": []}

        clients.http.include_router(router)  # type: ignore[union-attr]

    async def on_startup(self, clients: TransportClients) -> None:
        return None

    async def on_shutdown(self, clients: TransportClients) -> None:
        return None


@dataclass(frozen=True)
class CollisionModule(Module):
    meta: ModuleMeta = ModuleMeta(name="collision", base_path="/collision")

    def additional_settings_model(self):
        return None

    def register(self, clients: TransportClients, config: DSkitySettings) -> None:
        router = APIRouter(prefix=self.meta.base_path, tags=[self.meta.name])

        @router.get("/items")
        async def list_items() -> dict[str, list[str]]:
            return {"items": []}

        @router.post("/items")
        async def create_item() -> dict[str, bool]:
            return {"ok": True}

        clients.http.include_router(router)  # type: ignore[union-attr]

    async def on_startup(self, clients: TransportClients) -> None:
        return None

    async def on_shutdown(self, clients: TransportClients) -> None:
        return None


def test_module_get_client_generates_methods_from_routes() -> None:
    app = FastAPI()
    module = DemoModule()
    module.register(TransportClients(http=app), DSkitySettings())

    fake_http = _FakeHttpClient()
    app.state.http_client = fake_http
    app.modules = _FakeResolver("http://service.local/demo")  # type: ignore[attr-defined]

    client = module.get_client(app)

    assert hasattr(client, "factorial")
    assert hasattr(client, "events_emit")
    assert hasattr(client, "events")

    payload = asyncio.run(client.factorial(5, headers={"x-request-id": "abc"}))
    assert payload["result"] == 5

    emit_payload = asyncio.run(client.events_emit(json={"event": "x", "data": {}}))
    assert emit_payload["ok"] is True

    method, url, kwargs = fake_http.calls[0]
    assert method == "get"
    assert url == "http://service.local/demo/factorial/5"
    assert kwargs["headers"]["x-request-id"] == "abc"


def test_module_get_client_raises_for_missing_path_param() -> None:
    app = FastAPI()
    module = DemoModule()
    module.register(TransportClients(http=app), DSkitySettings())

    app.state.http_client = _FakeHttpClient()
    app.modules = _FakeResolver("http://service.local/demo")  # type: ignore[attr-defined]

    client = module.get_client(app)
    try:
        asyncio.run(client.factorial())
    except TypeError as exc:
        assert "Missing path parameter 'n'" in str(exc)
    else:
        raise AssertionError("Expected TypeError for missing path parameter")


def test_module_get_client_adds_method_suffix_for_name_collisions() -> None:
    app = FastAPI()
    module = CollisionModule()
    module.register(TransportClients(http=app), DSkitySettings())

    fake_http = _FakeHttpClient()
    app.state.http_client = fake_http
    app.modules = _FakeResolver("http://service.local/collision")  # type: ignore[attr-defined]

    client = module.get_client(app)

    assert hasattr(client, "items")
    assert hasattr(client, "items_post")

    asyncio.run(client.items())
    asyncio.run(client.items_post(json={"name": "x"}))

    assert fake_http.calls[0][0] == "get"
    assert fake_http.calls[1][0] == "post"
