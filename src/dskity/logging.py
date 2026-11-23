from __future__ import annotations

import json
import logging
import logging.config
import os
import sys
from datetime import UTC, datetime
from typing import Any

from rich.console import ConsoleRenderable, Group
from rich.logging import RichHandler
from rich.scope import render_scope
from rich.text import Text

from dskity.request_id import get_request_id


class RequestIdFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        request_id = get_request_id()
        record.request_id = request_id or "-"  # type: ignore[attr-defined]
        return True


class RichConsoleHandler(RichHandler):
    """Rich-based console handler, the default for the ``text`` log format.

    Behaves like ``rich.logging.RichHandler`` (colored levels, aligned columns,
    pretty tracebacks) and prefixes the message with the current request id
    when there is one.
    """

    def __init__(self, *, log_locals: bool = False, **kwargs: Any) -> None:
        kwargs.setdefault("rich_tracebacks", True)
        kwargs.setdefault("omit_repeated_times", False)
        super().__init__(**kwargs)
        self.log_locals = log_locals

    def render_message(self, record: logging.LogRecord, message: str) -> ConsoleRenderable:
        renderable = super().render_message(record, message)
        request_id = getattr(record, "request_id", None)
        if request_id and request_id != "-" and isinstance(renderable, Text):
            renderable = Text.assemble((f"[{request_id}] ", "dim cyan"), renderable)
        if self.log_locals and record.levelno <= logging.DEBUG:
            local_vars = _caller_locals(record)
            if local_vars:
                return Group(renderable, render_scope(local_vars, title="locals"))
        return renderable


def _caller_locals(record: logging.LogRecord) -> dict[str, Any] | None:
    """Locals of the frame that emitted ``record`` (handlers run synchronously)."""
    frame = sys._getframe(1)
    while frame is not None:
        if frame.f_code.co_filename == record.pathname and frame.f_lineno == record.lineno:
            return {k: v for k, v in frame.f_locals.items() if not k.startswith("__")}
        frame = frame.f_back  # type: ignore[assignment]
    return None


class JsonFormatter(logging.Formatter):
    """Structured JSON log formatter."""

    def format(self, record: logging.LogRecord) -> str:
        # Format timestamp with milliseconds
        dt = datetime.fromtimestamp(record.created, tz=UTC)
        timestamp = dt.strftime("%Y-%m-%dT%H:%M:%S") + f".{int(record.msecs):03d}Z"

        return json.dumps(
            {
                "timestamp": timestamp,
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


class LogfmtFormatter(logging.Formatter):
    """Logfmt (key=value) log formatter."""

    @staticmethod
    def _quote_value(value: str) -> str:
        """Quote value if it contains spaces or special characters."""
        if not value or " " in value or "=" in value or '"' in value:
            # Escape quotes and wrap in quotes
            escaped = value.replace('"', '\\"')
            return f'"{escaped}"'
        return value

    def format(self, record: logging.LogRecord) -> str:
        # Format timestamp with milliseconds
        dt = datetime.fromtimestamp(record.created, tz=UTC)
        timestamp = dt.strftime("%Y-%m-%dT%H:%M:%S") + f".{int(record.msecs):03d}Z"

        message = record.getMessage()
        request_id = getattr(record, "request_id", None) or "-"
        
        parts = [
            f"timestamp={self._quote_value(timestamp)}",
            f"level={record.levelname}",
            f"logger={record.name}",
            f"message={self._quote_value(message)}",
            f"request_id={request_id}",
            f"module={record.module}",
            f"function={record.funcName}",
            f"line={record.lineno}",
        ]
        
        return " ".join(parts)


def _level_from_env(default: str = "INFO") -> str:
    return (
        os.getenv("DSKITY_COMMON__LOGGING__LEVEL")
        or os.getenv("LOG_LEVEL")
        or default
    ).upper()


def _format_from_env(default: str = "text") -> str:
    return (os.getenv("DSKITY_COMMON__LOGGING__FORMAT") or default).lower()


def _locals_from_env() -> bool:
    return (os.getenv("DSKITY_COMMON__LOGGING__LOCALS") or "").strip().lower() in {"1", "true", "yes", "on"}


def build_logging_config(
    *, level: str | None = None, log_format: str | None = None, log_locals: bool | None = None
) -> dict[str, Any]:
    lvl = (level or _level_from_env()).upper()
    show_locals = _locals_from_env() if log_locals is None else log_locals
    fmt = (log_format or _format_from_env()).lower()

    use_json = fmt == "json"
    use_logfmt = fmt == "logfmt"

    if use_json:
        formatters: dict[str, Any] = {
            "default": {
                "()": "dskity.logging.JsonFormatter",
            },
            "access": {
                "()": "dskity.logging.JsonFormatter",
            },
        }
    elif use_logfmt:
        formatters = {
            "default": {
                "()": "dskity.logging.LogfmtFormatter",
            },
            "access": {
                "()": "dskity.logging.LogfmtFormatter",
            },
        }
    else:
        # Rich handlers render the whole record themselves, so no formatter is needed.
        formatters = {}

    if use_json or use_logfmt:
        handlers: dict[str, Any] = {
            name: {
                "class": "logging.StreamHandler",
                "formatter": formatter,
                "filters": ["request_id"],
                "stream": "ext://sys.stdout",
            }
            for name, formatter in (("console", "default"), ("access_console", "access"))
        }
    else:
        handlers = {
            name: {
                "class": "dskity.logging.RichConsoleHandler",
                "filters": ["request_id"],
                "log_locals": show_locals,
            }
            for name in ("console", "access_console")
        }

    return {
        "version": 1,
        "disable_existing_loggers": False,
        "filters": {
            "request_id": {"()": "dskity.logging.RequestIdFilter"},
        },
        "formatters": formatters,
        "handlers": handlers,
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


def configure_logging(
    *, level: str | None = None, log_format: str | None = None, log_locals: bool | None = None
) -> dict[str, Any]:
    cfg = build_logging_config(level=level, log_format=log_format, log_locals=log_locals)
    logging.config.dictConfig(cfg)
    return cfg
