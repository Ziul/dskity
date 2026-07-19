from __future__ import annotations

import importlib
import logging
import pkgutil
from dataclasses import dataclass
from typing import Iterable

from dskity.config.settings import DSkitySettings
from dskity.modules.contracts import Module

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class ModuleRegistry:
    modules: tuple[Module, ...]

    @classmethod
    def from_package(cls, package: str) -> "ModuleRegistry":
        imported = importlib.import_module(package)
        discovered: list[Module] = []

        for modinfo in pkgutil.iter_modules(imported.__path__, imported.__name__ + "."):
            # Expect a subpackage per module, with a `module.py` exposing `get_module()`
            try:
                module_impl = importlib.import_module(modinfo.name + ".module")
            except ModuleNotFoundError as e:
                logger.debug(f"Module '{modinfo.name}' not able to load ... {e}")
                continue
            logger.debug(f"Discovered module '{modinfo.name}'...")
            try:
                get_module = getattr(module_impl, "get_module", None)
                if callable(get_module):
                    logger.debug(f"Discovered module '{modinfo.name}'...")
                    discovered.append(get_module())
                else:
                    logger.debug(
                        f"Module '{modinfo.name}' does not have a 'get_module' function to call..."
                    )
            except Exception as e:
                logger.error(f"Error loading module '{modinfo.name}': {e}")

        return cls(modules=tuple(discovered))

    def enabled_modules(self, config: DSkitySettings) -> Iterable[Module]:
        modules_cfg = config.modules

        for module in self.modules:
            # New pattern: modules.<name>.enabled
            module_cfg = modules_cfg.get(module.meta.name)
            enabled = bool(getattr(module_cfg, "enabled", True))

            if enabled:
                yield module
