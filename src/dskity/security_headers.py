"""Pure ASGI middleware that injects configurable security headers into HTTP responses."""

from __future__ import annotations

from typing import Any


class SecurityHeadersMiddleware:
    """Pure ASGI middleware that adds security headers to all HTTP responses.

    Headers are pre-computed once at startup for performance. Configure via
    ``common.security_headers`` in settings or environment variables.
    """

    def __init__(self, app: Any, *, settings: Any) -> None:
        self.app = app
        self._headers: list[tuple[bytes, bytes]] = []
        self._build_headers(settings)

    def _build_headers(self, settings: Any) -> None:
        """Pre-compute header byte-tuples from settings."""
        header_map = {
            "x-content-type-options": getattr(settings, "x_content_type_options", None),
            "x-frame-options": getattr(settings, "x_frame_options", None),
            "strict-transport-security": getattr(settings, "strict_transport_security", None),
            "content-security-policy": getattr(settings, "content_security_policy", None),
            "referrer-policy": getattr(settings, "referrer_policy", None),
            "x-xss-protection": getattr(settings, "x_xss_protection", None),
            "permissions-policy": getattr(settings, "permissions_policy", None),
        }

        for name, value in header_map.items():
            if value:
                self._headers.append(
                    (name.encode("latin-1"), value.encode("latin-1"))
                )

        for name, value in (getattr(settings, "custom_headers", None) or {}).items():
            if name and value:
                self._headers.append(
                    (name.lower().encode("latin-1"), value.encode("latin-1"))
                )

    async def __call__(self, scope: dict, receive: Any, send: Any) -> None:
        if scope["type"] != "http" or not self._headers:
            await self.app(scope, receive, send)
            return

        async def send_wrapper(message: dict) -> None:
            if message["type"] == "http.response.start":
                headers = list(message.get("headers") or [])
                headers.extend(self._headers)
                message = {**message, "headers": headers}
            await send(message)

        await self.app(scope, receive, send_wrapper)
