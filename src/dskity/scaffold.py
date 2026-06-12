"""Module scaffolding logic for the ``dskity init`` command."""

from __future__ import annotations

from pathlib import Path

_MODULE_TEMPLATE = '''\
"""DSkity module: {module_name}."""

from __future__ import annotations

from dataclasses import dataclass

from fastapi import APIRouter

from dskity import DSkitySettings, Module, ModuleMeta, TransportClients

from .config import {class_name}Settings


@dataclass(frozen=True)
class {class_name}Module(Module):
    meta: ModuleMeta = ModuleMeta(name="{module_name}", base_path="/{module_name}")

    def additional_settings_model(self):
        return {class_name}Settings

    def register(self, clients: TransportClients, config: DSkitySettings) -> None:
        logger = clients.get_logger(self.meta.name)
        router = APIRouter(prefix=self.meta.base_path, tags=[self.meta.name])

        @router.get("/")
        def root():
            return {{"module": self.meta.name}}

        clients.http.include_router(router)
        logger.info("Module \'%s\' registered.", self.meta.name)


def get_module() -> Module:
    return {class_name}Module()
'''

_CONFIG_TEMPLATE = '''\
"""Configuration for the {module_name} module."""

from __future__ import annotations

from pydantic import BaseModel


class {class_name}Settings(BaseModel):
    pass
'''

_INIT_TEMPLATE = '''\
"""DSkity module package: {module_name}."""

from .module import get_module

__all__ = ["get_module"]
'''


def _to_pascal_case(name: str) -> str:
    """Convert snake_case (or kebab-case) module name to PascalCase class prefix."""
    return "".join(part.capitalize() for part in name.replace("-", "_").split("_"))


def scaffold_module(module_name: str, target_dir: Path) -> Path:
    """Generate a new module skeleton at ``target_dir / module_name``.

    Returns the path to the created directory.
    Raises ``FileExistsError`` if the target directory already exists.
    """
    dest = target_dir / module_name
    if dest.exists():
        raise FileExistsError(
            f"Directory '{dest}' already exists. Remove it first or choose a different name."
        )

    class_name = _to_pascal_case(module_name)

    dest.mkdir(parents=True)

    (dest / "__init__.py").write_text(
        _INIT_TEMPLATE.format(module_name=module_name), encoding="utf-8"
    )
    (dest / "module.py").write_text(
        _MODULE_TEMPLATE.format(module_name=module_name, class_name=class_name),
        encoding="utf-8",
    )
    (dest / "config.py").write_text(
        _CONFIG_TEMPLATE.format(module_name=module_name, class_name=class_name),
        encoding="utf-8",
    )

    return dest
