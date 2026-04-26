from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol

from fastapi import FastAPI
from dskity import DSkitySettings


@dataclass(frozen=True)
class ModuleMeta:
    name: str
    base_path: str


@dataclass(frozen=True)
class TransportClients:
    """Group possible transport clients a module may use.

    - `http`: the `FastAPI` instance (HTTP server) or `None`.
    - `grpc`: gRPC client/server wrapper (untyped to avoid direct dependency).
    - `mqtt`: singleton MQTT client (implementation-defined) or `None`.
    """

    http: FastAPI | None = None
    grpc: Any | None = None
    mqtt: Any | None = None


class Module(Protocol):
    meta: ModuleMeta

    def register(
        self, clients: TransportClients, config: DSkitySettings | dict
    ) -> None: ...
