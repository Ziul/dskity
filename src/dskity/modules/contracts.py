from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol

from fastapi import FastAPI
from pydantic import BaseModel
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

    @property
    def logger(self) -> Any:
        """Convenience property to access the logger from the HTTP client if available."""
        if self.http and hasattr(self.http.state, "logger"):
            return self.http.state.logger
        import logging

        return logging.getLogger(__name__)

    def get_logger(self, module_name: str) -> Any:
        """Get a logger for a specific module, namespaced under the main logger."""
        base_logger = self.logger
        if base_logger:
            return base_logger.getChild(module_name)
        import logging

        return logging.getLogger(module_name)


class Module(Protocol):
    meta: ModuleMeta

    def additional_settings_model(self) -> type[BaseModel] | None: ...

    def register(
        self, clients: TransportClients, config: DSkitySettings | dict
    ) -> None: ...

