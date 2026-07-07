from __future__ import annotations

import argparse
import importlib
import logging
import os
import sys
from pathlib import Path

from dotenv import load_dotenv
import uvicorn

from dskity.config.loader import resolve_config_path, _read_config_file
from dskity.logging import configure_logging

logger = logging.getLogger(__name__)


def _parse_targets(values: list[str] | None) -> list[str]:
    if not values:
        return []

    parts: list[str] = []
    for v in values:
        if not isinstance(v, str):
            continue
        for p in v.split(","):
            p = p.strip()
            if p:
                parts.append(p)

    # Keep order (removes duplicates)
    seen: set[str] = set()
    ordered: list[str] = []
    for p in parts:
        if p in seen:
            continue
        seen.add(p)
        ordered.append(p)
    return ordered


def _compute_reload(cli_flag: bool | None, config_file_value: bool | None = None) -> bool:
    """Determine whether reload should be enabled.

    Precedence (highest to lowest):
    1. CLI flag (--reload / --no-reload)
    2. Env var DSKITY_RELOAD
    3. Config file field ``reload``
    4. Smart default: True unless DSKITY_ENV == 'production'
    """
    if cli_flag is not None:
        return cli_flag
    env_val = os.environ.get("DSKITY_RELOAD", "").strip().lower()
    if env_val in ("true", "1", "yes"):
        return True
    if env_val in ("false", "0", "no"):
        return False
    if config_file_value is not None:
        return config_file_value
    return os.environ.get("DSKITY_ENV", "").strip().lower() != "production"


def _compute_reload_dirs(config_path: str) -> list[str]:
    """Compute reload directories from config's modules_search_paths."""
    config_data = _read_config_file(config_path, optional=True)
    raw_paths = config_data.get("modules_search_paths", ["modules"])

    dirs: list[str] = []
    config_dir = str(Path(config_path).resolve().parent)

    for entry in raw_paths:
        if not isinstance(entry, str) or not entry.strip():
            continue

        entry = entry.strip()

        # Filesystem path (contains / or \ or starts with . or ~)
        if "/" in entry or "\\" in entry or entry.startswith((".", "~")):
            path = Path(entry).expanduser()
            if not path.is_absolute():
                path = Path(config_dir) / path
            resolved = str(path.resolve())
            if resolved not in dirs:
                dirs.append(resolved)
            continue

        # Plain name that looks like a local directory (e.g., "modules")
        local_candidate = Path(config_dir) / entry
        if local_candidate.is_dir():
            resolved = str(local_candidate.resolve())
            if resolved not in dirs:
                dirs.append(resolved)
            continue

        # Python package name (e.g., "dskity.modules") — resolve filesystem path
        if all(part.isidentifier() for part in entry.split(".")):
            try:
                mod = importlib.import_module(entry)
                if hasattr(mod, "__path__"):
                    for p in mod.__path__:
                        resolved = str(Path(p).resolve())
                        if resolved not in dirs:
                            dirs.append(resolved)
            except (ImportError, ModuleNotFoundError):
                pass

    return dirs


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="dskity")
    subparsers = parser.add_subparsers(dest="command")

    # ── run (default) ───────────────────────────────────────────────────────
    run_parser = subparsers.add_parser("run", help="Start the dskity server (default).")
    _add_run_args(run_parser)

    # ── init ────────────────────────────────────────────────────────────────
    init_parser = subparsers.add_parser("init", help="Scaffold a new module skeleton.")
    init_parser.add_argument("module_name", help="Name of the module to create (snake_case).")
    init_parser.add_argument(
        "--path",
        dest="target_path",
        default="modules",
        help="Directory under which the module folder will be created (default: modules/).",
    )

    # ── list ────────────────────────────────────────────────────────────────
    list_parser = subparsers.add_parser("list", help="List discovered modules and their status.")
    list_parser.add_argument(
        "--config",
        "-c",
        dest="config_path",
        default=None,
        help="Path to a TOML or YAML config file.",
    )
    list_parser.add_argument(
        "--json",
        dest="output_json",
        action="store_true",
        default=False,
        help="Output in machine-readable JSON format.",
    )

    # ── validate ─────────────────────────────────────────────────────────────
    validate_parser = subparsers.add_parser(
        "validate", help="Validate configuration and module discovery."
    )
    validate_parser.add_argument(
        "--config",
        "-c",
        dest="config_path",
        default=None,
        help="Path to a TOML or YAML config file.",
    )
    validate_parser.add_argument(
        "--strict",
        action="store_true",
        default=False,
        help="Also run live connectivity checks (e.g. KV store ping).",
    )
    validate_parser.add_argument(
        "--json",
        dest="output_json",
        action="store_true",
        default=False,
        help="Output results in JSON format.",
    )

    # If no sub-command was given, treat the entire argv as arguments to `run`.
    args, remaining = parser.parse_known_args(argv)

    # Build token list from provided argv or sys.argv when argv is None.
    tokens = list(argv) if argv is not None else sys.argv[1:]

    if args.command is None:
        # No explicit subcommand: treat entire token list as run args.
        run_tokens = tokens
        run_args = run_parser.parse_args(run_tokens)
        return _cmd_run(run_args)

    if args.command == "run":
        # Locate the 'run' token and parse the following tokens as run args.
        try:
            idx = tokens.index("run")
            run_tokens = tokens[idx + 1 :]
        except ValueError:
            # Fallback: use remaining tokens (may be empty) or everything after first token.
            run_tokens = remaining or tokens[1:]
        run_args = run_parser.parse_args(run_tokens)
        return _cmd_run(run_args)

    if args.command == "init":
        return _cmd_init(args)

    if args.command == "list":
        return _cmd_list(args)

    if args.command == "validate":
        return _cmd_validate(args)

    parser.print_help()
    return 1


def _add_run_args(p: argparse.ArgumentParser) -> None:
    """Attach all server-run arguments to an ArgumentParser (or sub-parser)."""
    p.add_argument(
        "--config",
        "-c",
        dest="config_path",
        default=None,
        help="Path to a TOML or YAML config file that overrides the defaults",
    )
    p.add_argument("--host", "-H", default="0.0.0.0")
    p.add_argument("--port", "-p", type=int, default=8000)
    p.add_argument(
        "--log-level",
        "-l",
        default="INFO",
        dest="log_level",
        help="Set log level of the application",
    )
    p.add_argument(
        "--advertise-url",
        dest="advertise_url",
        default=None,
        help="URL advertised in service discovery (if different from listen host/port)",
    )
    p.add_argument(
        "--target",
        "-t",
        dest="targets",
        action="append",
        default=None,
        help=(
            "List of modules to enable (overrides YAML). "
            "Accepts CSV (e.g. echo,health) and can be repeated (e.g. -t echo -t health)."
        ),
    )
    p.add_argument(
        "--reload-dir",
        "-r",
        dest="reload_dirs",
        action="append",
        default=None,
        help=(
            "Directories (comma-separated or repeated) to watch for reload. "
            "If omitted, auto-computed from modules_search_paths. "
            "Can also be set via DSKITY_RELOAD_DIRS env var."
        ),
    )
    p.add_argument(
        "--reload",
        dest="reload",
        action=argparse.BooleanOptionalAction,
        default=None,
        help="Enable or disable auto-reload (default: True unless DSKITY_ENV=production).",
    )


def _cmd_run(args: argparse.Namespace) -> int:
    config_path = resolve_config_path(args.config_path)
    load_dotenv()

    # Ensure the bootstrap uses the chosen YAML.
    os.environ["DSKITY_CONFIG"] = config_path
    # CLI flag > env var > config file value (read below)
    _env_level = os.environ.get("DSKITY_COMMON__LOGGING__LEVEL", "").strip()
    log_level = (_env_level or args.log_level or "INFO").lower()

    targets = _parse_targets(args.targets)
    if targets:
        os.environ["DSKITY_TARGETS"] = ",".join(targets)
    else:
        os.environ.pop("DSKITY_TARGETS", None)

    host = args.host or "0.0.0.0"
    port = args.port or 8000
    if args.advertise_url:
        advertise_url = args.advertise_url
    else:
        advertise_url = f"http://{host}:{port}"
    os.environ["DSKITY_ADVERTISE_URL"] = advertise_url

    os.environ["DSKITY_PORT"] = str(port)
    os.environ["DSKITY_HOST"] = host

    # Read logging format from config file (before app is loaded)
    _config_data = _read_config_file(config_path, optional=True)
    _logging_cfg = _config_data.get("common", {}).get("logging", {})
    # If no CLI/env override, fall back to config file value
    if not os.environ.get("DSKITY_COMMON__LOGGING__LEVEL", "").strip() and not args.log_level:
        log_level = (_logging_cfg.get("level", "INFO") or "INFO").lower()
    _log_format = (
        _logging_cfg.get("format", "text")
        or os.environ.get("DSKITY_COMMON__LOGGING__FORMAT", "text")
    )
    # Publish resolved level so that bootstrap/modules read the same value
    os.environ["DSKITY_COMMON__LOGGING__LEVEL"] = log_level.upper()
    log_config = configure_logging(level=log_level, log_format=_log_format)

    # Determine reload directories from environment or CLI
    reload_dirs = None
    reload_includes: list[str] | None = None
    env_reload = os.environ.get("DSKITY_RELOAD_DIRS")
    if env_reload:
        reload_dirs = [p.strip() for p in env_reload.split(",") if p.strip()]
    elif getattr(args, "reload_dirs", None):
        parts: list[str] = []
        for v in args.reload_dirs:
            if not isinstance(v, str):
                continue
            for p in v.split(","):
                p = p.strip()
                if p:
                    parts.append(p)
        reload_dirs = parts or None

    reload = _compute_reload(
        args.reload,
        config_file_value=_config_data.get("reload"),
    )

    if reload and reload_dirs is None:
        reload_dirs = _compute_reload_dirs(config_path) or None
        config_filename = Path(config_path).name
        reload_includes = [config_filename]

    if reload:
        logger.info("Reload enabled. Watching directories: %s", reload_dirs)
        logger.info("Reload includes: %s", reload_includes)

    uvicorn.run(
        "dskity.app:app",
        host=host,
        port=port,
        reload=reload,
        reload_dirs=reload_dirs,
        reload_includes=reload_includes,
        env_file=None,
        log_level=log_level,
        log_config=log_config,
    )
    return 0


def _cmd_init(args: argparse.Namespace) -> int:
    """Scaffold a new module under the given path."""
    from dskity.scaffold import scaffold_module, _to_pascal_case

    module_name: str = args.module_name.strip()
    target_path = Path(args.target_path)

    try:
        created = scaffold_module(module_name, target_path)
    except FileExistsError as exc:
        print(f"Error: {exc}")
        return 1

    class_name = _to_pascal_case(module_name)
    print(f"Module '{module_name}' created at {created}")
    print(f"  Class name: {class_name}Module")
    print()
    print("Next steps:")
    print(f"  1. Add '{target_path}/{module_name}' to modules_search_paths in settings.yaml")
    print(f"  2. Enable it under modules.{module_name}.enabled: true")
    return 0


def _cmd_list(args: argparse.Namespace) -> int:
    """List discovered modules and their status."""
    import json as _json

    from dskity.config.loader import load_config, resolve_config_path
    from dskity.modules.registry import ModuleRegistry

    config_path = resolve_config_path(getattr(args, "config_path", None))
    config = load_config(override_path=config_path)

    # Resolve module search packages (reuse bootstrap logic)
    from dskity.bootstrap import (
        _resolve_modules_import_packages,
        _resolve_modules_search_paths,
        _install_modules_search_paths,
    )

    search_paths = _resolve_modules_search_paths(config, config_path)
    _install_modules_search_paths(search_paths)

    packages = _resolve_modules_import_packages(config)
    if not packages:
        packages = ["dskity.modules"]

    discovered: dict[str, object] = {}
    for package in packages:
        try:
            registry = ModuleRegistry.from_package(package)
        except ModuleNotFoundError:
            continue
        for mod in registry.modules:
            discovered.setdefault(mod.meta.name, mod)

    # Determine enabled status
    enabled_set: set[str] = set()
    for mod in discovered.values():
        cfg = config.modules.ensure(mod.meta.name)  # type: ignore[attr-defined]
        if getattr(cfg, "enabled", True):
            enabled_set.add(mod.meta.name)  # type: ignore[attr-defined]

    output_json: bool = getattr(args, "output_json", False)

    if output_json:
        rows = []
        for name, mod in sorted(discovered.items()):
            rows.append({
                "name": name,
                "enabled": name in enabled_set,
                "base_path": mod.meta.base_path,  # type: ignore[attr-defined]
                "depends_on": list(getattr(mod.meta, "depends_on", ())),  # type: ignore[attr-defined]
            })
        print(_json.dumps(rows, indent=2))
        return 0

    # Pretty table
    col_widths = [16, 8, 14, 12]
    header = (
        f"{'Module':<{col_widths[0]}}  {'Enabled':<{col_widths[1]}}  "
        f"{'Base Path':<{col_widths[2]}}  {'Depends On'}"
    )
    sep = (
        f"{'─' * col_widths[0]}  {'─' * col_widths[1]}  "
        f"{'─' * col_widths[2]}  {'─' * col_widths[3]}"
    )
    print(header)
    print(sep)
    for name in sorted(discovered):
        mod = discovered[name]
        enabled_mark = "✓" if name in enabled_set else "✗"
        base = mod.meta.base_path  # type: ignore[attr-defined]
        depends = ", ".join(getattr(mod.meta, "depends_on", ())) or ""  # type: ignore[attr-defined]
        print(
            f"{name:<{col_widths[0]}}  {enabled_mark:<{col_widths[1]}}  "
            f"{base:<{col_widths[2]}}  {depends}"
        )

    return 0


def _cmd_validate(args: argparse.Namespace) -> int:
    """Validate configuration and module discovery."""
    import json as _json

    from dskity.validate import validate_config, CheckStatus

    config_path = getattr(args, "config_path", None)
    strict = getattr(args, "strict", False)
    output_json = getattr(args, "output_json", False)

    report, exit_code = validate_config(config_path, strict=strict)

    _STATUS_ICON = {
        CheckStatus.OK: "✓",
        CheckStatus.WARNING: "⚠",
        CheckStatus.ERROR: "✗",
        CheckStatus.SKIPPED: "–",
    }

    if output_json:
        rows = [
            {
                "name": r.name,
                "status": r.status.value,
                "message": r.message,
                "detail": r.detail,
            }
            for r in report.results
        ]
        print(_json.dumps({"results": rows, "summary": report.summary()}, indent=2))
        return exit_code

    for result in report.results:
        icon = _STATUS_ICON.get(result.status, "?")
        print(f"  {icon}  [{result.status.value.upper():7s}] {result.name}: {result.message}")
        if result.detail:
            for line in result.detail.splitlines():
                print(f"          {line}")

    print()
    print(f"  Summary: {report.summary()}")
    print()

    if exit_code == 0:
        print("  Validation passed.")
    else:
        print("  Validation FAILED.")

    return exit_code
