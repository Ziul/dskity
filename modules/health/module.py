from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from fastapi import APIRouter, FastAPI

from dskity.modules.contracts import Module, ModuleMeta

if TYPE_CHECKING:  # pragma: no cover
    import grpc  # type: ignore


@dataclass(frozen=True)
class HealthModule(Module):
    meta: ModuleMeta = ModuleMeta(name="health", base_path="/health")

    def register(self, app: FastAPI, config: dict, grpc_server: "grpc.aio.Server | None" = None) -> None:
        router = APIRouter(prefix=self.meta.base_path, tags=[self.meta.name])

        @router.get("/live")
        def live() -> dict:
            return {"status": "ok"}

        @router.get("/ready")
        def ready() -> dict:
            return {"status": "ok"}

        app.include_router(router)


def get_module() -> Module:
    return HealthModule()
