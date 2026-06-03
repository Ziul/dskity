from __future__ import annotations

import argparse
import os
from dotenv import load_dotenv
import uvicorn

from dskity.config.loader import resolve_config_path
from dskity.logging import configure_logging


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


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="dskity")
    parser.add_argument(
        "--config",
        "-c",
        dest="config_path",
        default=None,
        help="Path to a TOML or YAML config file that overrides the defaults",
    )
    parser.add_argument("--host", "-H", default="0.0.0.0")
    parser.add_argument("--port", "-p", type=int, default=8000)
    parser.add_argument(
        "--log-level",
        "-l",
        default="INFO",
        dest="log_level",
        help="Set log level of the application",
    )
    parser.add_argument(
        "--advertise-url",
        dest="advertise_url",
        default=None,
        help="URL advertised in service discovery (if different from listen host/port)",
    )
    parser.add_argument(
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
    parser.add_argument(
        "--reload-dir",
        "-r",
        dest="reload_dirs",
        action="append",
        default=None,
        help=(
            "Directories (comma-separated or repeated) to watch for reload when --reload is enabled. "
            "If omitted, uvicorn default watch behaviour is used. Can also be set via DSKITY_RELOAD_DIRS env var."
        ),
    )
    args = parser.parse_args(argv)

    config_path = resolve_config_path(args.config_path)
    load_dotenv()

    # Ensure the bootstrap uses the chosen YAML.
    os.environ["DSKITY_CONFIG"] = config_path
    log_level = os.environ.get("DSKITY_LOG_LEVEL", args.log_level).lower()
    # Store log level in environment so configure_logging() uses it when app is imported
    os.environ["DSKITY_LOG_LEVEL"] = log_level.upper()

    targets = _parse_targets(args.targets)
    if targets:
        os.environ["DSKITY_TARGETS"] = ",".join(targets)
    else:
        os.environ.pop("DSKITY_TARGETS", None)

    # Advertised base URL for discovery (inferred from the chosen host/port).
    host = args.host or "0.0.0.0"
    port = args.port or 8000
    if args.advertise_url:
        advertise_url = args.advertise_url
    else:
        advertise_url = f"http://{host}:{port}"
    os.environ["DSKITY_ADVERTISE_URL"] = advertise_url

    os.environ["DSKITY_PORT"] = str(port)
    os.environ["DSKITY_HOST"] = host
    log_config = configure_logging(level=log_level)

    # Determine reload directories from environment or CLI
    reload_dirs = None
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


    uvicorn.run(
        "dskity.app:app",
        host=host,
        port=port,
        reload=True,
        env_file=None,
        reload_dirs=reload_dirs,
        log_level=log_level,
        log_config=log_config,
    )
    return 0
