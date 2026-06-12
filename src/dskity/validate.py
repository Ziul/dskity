"""Config and environment validation for dskity services.

Provides ``validate_config()`` which performs a series of checks and returns
a :class:`ValidationReport` describing what passed, failed, or was skipped.

Exit codes (used by the CLI)
----------------------------
0 — all checks passed (or non-critical warnings only)
1 — one or more validation errors
2 — config file not found or failed to parse
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from enum import Enum
from typing import Any

logger = logging.getLogger(__name__)


class CheckStatus(str, Enum):
    OK = "ok"
    WARNING = "warn"
    ERROR = "error"
    SKIPPED = "skipped"


@dataclass
class ValidationResult:
    """Result of a single validation check."""

    name: str
    status: CheckStatus
    message: str
    detail: str = ""


@dataclass
class ValidationReport:
    """Aggregated report from all validation checks."""

    results: list[ValidationResult] = field(default_factory=list)

    def add(
        self,
        name: str,
        status: CheckStatus,
        message: str,
        detail: str = "",
    ) -> None:
        self.results.append(
            ValidationResult(name=name, status=status, message=message, detail=detail)
        )

    @property
    def has_errors(self) -> bool:
        return any(r.status == CheckStatus.ERROR for r in self.results)

    @property
    def has_warnings(self) -> bool:
        return any(r.status == CheckStatus.WARNING for r in self.results)

    def exit_code(self, parse_exit: int = 0) -> int:
        """Return appropriate shell exit code.

        Uses *parse_exit* (2) when called after a parse/file-not-found failure.
        """
        if parse_exit != 0:
            return parse_exit
        return 1 if self.has_errors else 0

    def summary(self) -> str:
        ok = sum(1 for r in self.results if r.status == CheckStatus.OK)
        warn = sum(1 for r in self.results if r.status == CheckStatus.WARNING)
        err = sum(1 for r in self.results if r.status == CheckStatus.ERROR)
        skip = sum(1 for r in self.results if r.status == CheckStatus.SKIPPED)
        return f"{ok} passed, {warn} warnings, {err} errors, {skip} skipped"


def validate_config(
    config_path: str | None = None,
    *,
    strict: bool = False,
) -> tuple[ValidationReport, int]:
    """Run all validation checks and return a report plus an exit code.

    Args:
        config_path: Path to config file. Auto-detected when *None*.
        strict: When *True*, also attempt live connectivity probes (KV store).

    Returns:
        A tuple of (:class:`ValidationReport`, exit_code) where exit_code is
        0 on success, 1 on validation errors, 2 on parse/file errors.
    """
    report = ValidationReport()
    parse_exit = 0

    # ── Step 1: Locate and parse the config file ──────────────────────────
    try:
        from dskity.config.loader import resolve_config_path, _read_config_file

        resolved = resolve_config_path(config_path)
        _ = _read_config_file(resolved, optional=False)
        report.add(
            "config.parse",
            CheckStatus.OK,
            f"Config file parsed successfully: {resolved}",
        )
    except FileNotFoundError as exc:
        report.add("config.parse", CheckStatus.ERROR, str(exc))
        parse_exit = 2
        return report, parse_exit
    except Exception as exc:
        report.add("config.parse", CheckStatus.ERROR, f"Failed to parse config: {exc}", str(exc))
        parse_exit = 2
        return report, parse_exit

    # ── Step 2: Validate settings via Pydantic ────────────────────────────
    config: Any = None
    try:
        from dskity.config.loader import load_config

        config = load_config(override_path=resolved)
        report.add("config.settings", CheckStatus.OK, "Settings validated successfully.")
    except Exception as exc:
        report.add(
            "config.settings",
            CheckStatus.ERROR,
            "Settings validation failed.",
            str(exc),
        )
        return report, 1

    # ── Step 3: Module discovery ──────────────────────────────────────────
    try:
        from dskity.bootstrap import (
            _resolve_modules_import_packages,
            _resolve_modules_search_paths,
            _install_modules_search_paths,
        )
        from dskity.modules.registry import ModuleRegistry

        search_paths = _resolve_modules_search_paths(config, resolved)
        _install_modules_search_paths(search_paths)

        packages = _resolve_modules_import_packages(config)
        if not packages:
            packages = ["dskity.modules"]

        discovered: dict[str, Any] = {}
        load_errors: list[str] = []
        for pkg in packages:
            try:
                reg = ModuleRegistry.from_package(pkg)
            except ModuleNotFoundError as exc:
                load_errors.append(f"Package '{pkg}' not found: {exc}")
                continue
            except Exception as exc:
                load_errors.append(f"Package '{pkg}' failed to load: {exc}")
                continue
            for mod in reg.modules:
                discovered.setdefault(mod.meta.name, mod)

        if load_errors:
            for msg in load_errors:
                report.add("modules.discovery", CheckStatus.WARNING, msg)

        if discovered:
            names = sorted(discovered.keys())
            report.add(
                "modules.discovery",
                CheckStatus.OK,
                f"Discovered {len(discovered)} module(s): {', '.join(names)}",
            )
        else:
            report.add(
                "modules.discovery",
                CheckStatus.WARNING,
                "No modules discovered. Is the modules_search_paths configured correctly?",
            )
    except Exception as exc:
        report.add(
            "modules.discovery",
            CheckStatus.ERROR,
            "Module discovery failed.",
            str(exc),
        )

    # ── Step 4: Module config validation ─────────────────────────────────
    try:
        for name, mod in discovered.items():
            cfg = config.modules.ensure(name)
            enabled = getattr(cfg, "enabled", True)
            if enabled:
                report.add(
                    f"modules.config.{name}",
                    CheckStatus.OK,
                    f"Module '{name}' is enabled.",
                )
            else:
                report.add(
                    f"modules.config.{name}",
                    CheckStatus.SKIPPED,
                    f"Module '{name}' is disabled.",
                )
    except Exception as exc:
        report.add(
            "modules.config",
            CheckStatus.ERROR,
            "Module config validation failed.",
            str(exc),
        )

    # ── Step 5: KV store connectivity (strict mode only) ─────────────────
    if strict:
        _check_kv_connectivity(report, config)

    return report, report.exit_code(parse_exit)


def _check_kv_connectivity(report: ValidationReport, config: Any) -> None:
    """Attempt a live ping to the configured KV store backend."""
    try:
        from dskity.kvstore.backends import backend_from_config

        kv_config = getattr(config, "kv", None) or getattr(
            getattr(config, "common", None), "kv", None
        )
        backend = backend_from_config(kv_config)
        # A simple set/delete roundtrip to validate connectivity
        backend.set("__dskity_validate__", "ok")
        backend.delete("__dskity_validate__")
        report.add("kv.connectivity", CheckStatus.OK, "KV store connectivity check passed.")
    except Exception as exc:
        report.add(
            "kv.connectivity",
            CheckStatus.ERROR,
            "KV store connectivity check failed.",
            str(exc),
        )
