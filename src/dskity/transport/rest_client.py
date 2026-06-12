from __future__ import annotations

import warnings
from dataclasses import dataclass

import httpx


@dataclass(frozen=True)
class RestClient:
    """Synchronous HTTP client wrapper.

    .. deprecated::
        Use :class:`~dskity.transport.http_client.HttpClientManager` (async) instead
        to avoid blocking the event loop.
    """

    base_url: str

    def client(self) -> httpx.Client:
        warnings.warn(
            "RestClient.client() is synchronous and blocks the event loop. "
            "Use HttpClientManager from dskity.transport.http_client instead.",
            DeprecationWarning,
            stacklevel=2,
        )
        return httpx.Client(base_url=self.base_url, timeout=10.0)
