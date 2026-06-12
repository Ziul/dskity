from __future__ import annotations

import json
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


class JsonFormatter(logging.Formatter):
    """Structured JSON log formatter."""

    def format(self, record: logging.LogRecord) -> str:
        return json.dumps(
            {
                "timestamp": self.formatTime(record, datefmt="%Y-%m-%dT%H:%M:%S.%fZ"),
                "level": record.levelname,
                "logger": record.name,
                "message": record.getMessage(),
                "request_id": getattr(record, "request_id", None),
                "module": record.module,
                "function": record.funcName,
                "line": record.lineno,
            },
            default=str,
        )


def _level_from_env(default: str = "INFO") -> str:
    return (
        os.getenv("DSKITY_COMMON__LOGGING__LEVEL")
        or os.getenv("LOG_LEVEL")
        or default
    ).upper()


def _format_from_env(default: str = "text") -> str:
    return (os.getenv("DSKITY_COMMON__LOGGING__FORMAT") or default).lower()


def build_logging_config(*, level: str | None = None, log_format: str | None = None) -> dict[str, Any]:
    lvl = (level or _level_from_env()).upper()
    fmt = (log_format or _format_from_env()).lower()

    use_json = fmt == "json"

    default_fmt = (
        "%(asctime)s %(levelname)s %(name)s request_id=%(request_id)s - %(message)s"
    )
    access_fmt = (
        "%(asctime)s %(levelname)s %(name)s request_id=%(request_id)s - %(message)s"
    )

    if use_json:
        formatters: dict[str, Any] = {
            "default": {
                "()": "dskity.logging.JsonFormatter",
            },
            "access": {
                "()": "dskity.logging.JsonFormatter",
            },
        }
    else:
        formatters = {
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
        }

    return {
        "version": 1,
        "disable_existing_loggers": False,
        "filters": {
            "request_id": {"()": "dskity.logging.RequestIdFilter"},
        },
        "formatters": formatters,
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


def configure_logging(*, level: str | None = None, log_format: str | None = None) -> dict[str, Any]:
    cfg = build_logging_config(level=level, log_format=log_format)
    logging.config.dictConfig(cfg)
    return cfg
