"""Shared httpx.AsyncClient for inter-service communication."""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any

import httpx

logger = logging.getLogger(__name__)


@dataclass
class HttpClientManager:
    """Manages a shared httpx.AsyncClient with connection pooling.

    Intended to be stored in app.state and passed to modules via TransportClients.
    Call ``start()`` during app startup and ``stop()`` during shutdown.
    """

    timeout: float = 10.0
    max_connections: int = 100
    max_keepalive_connections: int = 20
    _client: httpx.AsyncClient | None = field(default=None, init=False, repr=False)

    async def start(self) -> None:
        """Initialize the shared async client. Call during app startup."""
        if self._client is not None:
            return

        self._client = httpx.AsyncClient(
            timeout=httpx.Timeout(self.timeout),
            limits=httpx.Limits(
                max_connections=self.max_connections,
                max_keepalive_connections=self.max_keepalive_connections,
            ),
            follow_redirects=True,
        )
        logger.info(
            "Shared HTTP client started (max_connections=%d, timeout=%.1fs)",
            self.max_connections,
            self.timeout,
        )

    async def stop(self) -> None:
        """Close the shared async client. Call during app shutdown."""
        if self._client is not None:
            await self._client.aclose()
            self._client = None
            logger.info("Shared HTTP client closed")

    @property
    def client(self) -> httpx.AsyncClient:
        """Get the shared async client. Raises RuntimeError if not yet started."""
        if self._client is None:
            raise RuntimeError(
                "HTTP client not initialized. "
                "Ensure HttpClientManager.start() is called during app startup."
            )
        return self._client

    async def get(self, url: str, **kwargs: Any) -> httpx.Response:
        """Convenience: GET request via the shared client."""
        return await self.client.get(url, **kwargs)

    async def post(self, url: str, **kwargs: Any) -> httpx.Response:
        """Convenience: POST request via the shared client."""
        return await self.client.post(url, **kwargs)

    async def put(self, url: str, **kwargs: Any) -> httpx.Response:
        """Convenience: PUT request via the shared client."""
        return await self.client.put(url, **kwargs)

    async def delete(self, url: str, **kwargs: Any) -> httpx.Response:
        """Convenience: DELETE request via the shared client."""
        return await self.client.delete(url, **kwargs)
