from __future__ import annotations

from dataclasses import dataclass

import httpx


@dataclass(frozen=True)
class RestClient:
    base_url: str

    def client(self) -> httpx.Client:
        return httpx.Client(base_url=self.base_url, timeout=10.0)
