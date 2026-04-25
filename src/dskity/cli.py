from __future__ import annotations

import argparse
import os

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

    # mantém ordem (remove duplicados)
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
    parser.add_argument("--host", "-H", default=None)
    parser.add_argument("--port", "-p", type=int, default=None)
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
    args = parser.parse_args(argv)

    config_path = resolve_config_path(args.config_path)

    # Garante que o bootstrap use o YAML escolhido.
    os.environ["DSKITY_CONFIG"] = config_path

    targets = _parse_targets(args.targets)
    if targets:
        os.environ["DSKITY_TARGETS"] = ",".join(targets)
    else:
        os.environ.pop("DSKITY_TARGETS", None)

    # Base URL anunciada para discovery (inferida a partir do host/port escolhidos).
    host = args.host or "0.0.0.0"
    port = args.port or 8000
    if args.advertise_url:
        advertise_url = args.advertise_url or f"http://{host}:{port}"
        os.environ["DSKITY_ADVERTISE_URL"] = advertise_url

    log_config = configure_logging()

    uvicorn.run(
        "dskity.app:app",
        host=host,
        port=port,
        reload=True,
        env_file=None,
        log_level="info",
        log_config=log_config,
    )
    return 0
