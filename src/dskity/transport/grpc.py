from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class GRPCClient:
    """Lightweight gRPC client placeholder.

    Avoids importing `grpc` at module import time; the actual grpc package is
    imported lazily when `channel()` is called. This keeps the core library
    free of a hard dependency on `grpcio` while still providing a convenient
    client wrapper for modules that do use gRPC.
    """

    target: str | None = None
    _channel: Any | None = None

    def channel(self) -> Any:
        if self._channel is not None:
            return self._channel

        if self.target is None:
            raise RuntimeError("gRPC target not configured")

        try:
            import grpc  # type: ignore
        except Exception as exc:  # pragma: no cover - runtime error if grpc missing
            raise RuntimeError("grpc package is required to create a channel") from exc

        # Cria um channel inseguro por padrão; módulos podem trocar/fechar.
        self._channel = grpc.insecure_channel(self.target)
        return self._channel

    def close(self) -> None:
        ch = self._channel
        if ch is None:
            return
        try:
            ch.close()
        except Exception:
            pass
