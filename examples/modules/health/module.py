from __future__ import annotations

from dataclasses import dataclass

from fastapi import APIRouter

from dskity import Module, ModuleMeta, DSkitySettings, TransportClients

@dataclass(frozen=True)
class HealthModule(Module):
    meta: ModuleMeta = ModuleMeta(name="health", base_path="/health")

    def register(self, clients: TransportClients, config: DSkitySettings ) -> None:
        router = APIRouter(prefix=self.meta.base_path, tags=[self.meta.name])

        @router.get("/live")
        def live() -> dict:
            return {"status": "ok"}

        @router.get("/ready")
        def ready() -> dict:
            return {"status": "ok"}

        clients.http.include_router(router)


def get_module() -> Module:
    return HealthModule()
