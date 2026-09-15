"""DSkity module: second_module."""

from __future__ import annotations

from dataclasses import dataclass

from fastapi import APIRouter

from dskity import DSkitySettings, Module, ModuleMeta, TransportClients

from .config import SecondModuleSettings


@dataclass(frozen=True)
class SecondModuleModule(Module):
    meta: ModuleMeta = ModuleMeta(name="second_module", base_path="/second_module")

    def additional_settings_model(self):
        return SecondModuleSettings

    def register(self, clients: TransportClients, config: DSkitySettings) -> None:
        logger = clients.get_logger(self.meta.name)
        router = APIRouter(prefix=self.meta.base_path, tags=[self.meta.name])

        @router.get("/")
        def root():
            return {"module": self.meta.name}

        clients.http.include_router(router)
        logger.info("Module '%s' registered.", self.meta.name)


def get_module() -> Module:
    return SecondModuleModule()
