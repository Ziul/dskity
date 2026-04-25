from __future__ import annotations

import uuid
from contextvars import ContextVar
from typing import Final

from fastapi import FastAPI


REQUEST_ID_HEADER: Final[str] = "X-Request-Id"

_request_id_ctx: ContextVar[str | None] = ContextVar("request_id", default=None)


def get_request_id() -> str | None:
    return _request_id_ctx.get()


class RequestIdASGIMiddleware:
    def __init__(self, app, header_name: str = REQUEST_ID_HEADER):
        self.app = app
        self.header_name = header_name
        self._header_name_lower = header_name.lower().encode("latin-1")

    async def __call__(self, scope, receive, send):
        if scope.get("type") != "http":
            await self.app(scope, receive, send)
            return

        headers = scope.get("headers") or []
        request_id: str | None = None
        for k, v in headers:
            if k == self._header_name_lower:
                try:
                    request_id = v.decode("latin-1").strip()
                except Exception:
                    request_id = None
                break

        if not request_id:
            request_id = str(uuid.uuid4())

        token = _request_id_ctx.set(request_id)

        # Deixa disponível via request.state.request_id (Starlette usa scope['state']).
        state = scope.setdefault("state", {})
        state["request_id"] = request_id

        async def send_wrapper(message):
            if message.get("type") == "http.response.start":
                hdrs = list(message.get("headers") or [])
                if not any(k == self._header_name_lower for k, _ in hdrs):
                    hdrs.append((self._header_name_lower, request_id.encode("latin-1")))
                    message["headers"] = hdrs
            await send(message)

        try:
            await self.app(scope, receive, send_wrapper)
        finally:
            _request_id_ctx.reset(token)


def install_request_id(app: FastAPI) -> None:
    app.add_middleware(RequestIdASGIMiddleware)
