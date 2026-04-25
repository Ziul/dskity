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
    """Agrupa possíveis clientes/transportes que um módulo pode usar.

    - `http`: instancia `FastAPI` (HTTP server) ou `None`.
    - `grpc`: servidor gRPC (tipo não anotado para evitar dependências diretas).
    - `mqtt`: cliente MQTT singleton (implementation-defined) ou `None`.
    """

    http: FastAPI | None = None
    grpc: Any | None = None
    mqtt: Any | None = None


class Module(Protocol):
    meta: ModuleMeta

    def register(self, clients: TransportClients, config: DSkitySettings | dict) -> None: ...
