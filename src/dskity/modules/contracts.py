from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Protocol

from fastapi import FastAPI
from dskity import DSkitySettings

if TYPE_CHECKING:  # pragma: no cover
    import grpc  # type: ignore


@dataclass(frozen=True)
class ModuleMeta:
    name: str
    base_path: str


class Module(Protocol):
    meta: ModuleMeta

    def register(
        self,
        app: FastAPI,
        config: DSkitySettings|dict,
        grpc_server: "grpc.aio.Server | None" = None,
    ) -> None: ...
