from __future__ import annotations

import logging
import logging.config
import os
from typing import Any

from dskity.request_id import get_request_id


class RequestIdFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        request_id = get_request_id()
        record.request_id = request_id or "-"  # type: ignore[attr-defined]
        return True


def _level_from_env(default: str = "INFO") -> str:
    return (os.getenv("DSKITY_LOG_LEVEL") or os.getenv("LOG_LEVEL") or default).upper()


def build_logging_config(*, level: str | None = None) -> dict[str, Any]:
    lvl = (level or _level_from_env()).upper()

    default_fmt = (
        "%(asctime)s %(levelname)s %(name)s request_id=%(request_id)s - %(message)s"
    )
    # For uvicorn.access, using %(message)s is more robust: Uvicorn already formats
    # the access line and not every LogRecord will have client_addr/request_line/status_code.
    access_fmt = (
        "%(asctime)s %(levelname)s %(name)s request_id=%(request_id)s - %(message)s"
    )

    return {
        "version": 1,
        "disable_existing_loggers": False,
        "filters": {
            "request_id": {"()": "dskity.logging.RequestIdFilter"},
        },
        "formatters": {
            # Important: uvicorn.access does not populate client_addr/request_line/status_code
            # in a standard formatter; it requires Uvicorn's AccessFormatter.
            "default": {
                "()": "uvicorn.logging.DefaultFormatter",
                "fmt": default_fmt,
                "use_colors": None,
            },
            "access": {
                "()": "uvicorn.logging.AccessFormatter",
                "fmt": access_fmt,
                "use_colors": None,
            },
        },
        "handlers": {
            "console": {
                "class": "logging.StreamHandler",
                "formatter": "default",
                "filters": ["request_id"],
                "stream": "ext://sys.stdout",
            },
            "access_console": {
                "class": "logging.StreamHandler",
                "formatter": "access",
                "filters": ["request_id"],
                "stream": "ext://sys.stdout",
            },
        },
        "root": {
            "level": lvl,
            "handlers": ["console"],
        },
        "loggers": {
            # Uvicorn
            "uvicorn": {"level": lvl, "handlers": ["console"], "propagate": False},
            "uvicorn.error": {
                "level": lvl,
                "handlers": ["console"],
                "propagate": False,
            },
            "uvicorn.access": {
                "level": lvl,
                "handlers": ["access_console"],
                "propagate": False,
            },
            # FastAPI
            "fastapi": {"level": lvl, "handlers": ["console"], "propagate": False},
            # fastapi-cli (common names)
            "fastapi_cli": {"level": lvl, "handlers": ["console"], "propagate": False},
            "fastapi-cli": {"level": lvl, "handlers": ["console"], "propagate": False},
            # App
            "dskity": {"level": lvl, "handlers": ["console"], "propagate": False},
        },
    }


def configure_logging(*, level: str | None = None) -> dict[str, Any]:
    cfg = build_logging_config(level=level)
    logging.config.dictConfig(cfg)
    return cfg
