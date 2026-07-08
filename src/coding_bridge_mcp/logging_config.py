"""Structured JSON logging configuration for Coding Bridge MCP."""

from __future__ import annotations

import json
import logging
import os
import sys
from typing import Any


class JSONFormatter(logging.Formatter):
    """Emit log records as single-line JSON objects."""

    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, Any] = {
            "timestamp": self.formatTime(record),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }

        if record.exc_info:
            payload["exception"] = self.formatException(record.exc_info)

        # Include any custom extra fields passed via logger.bind()/extra=.
        reserved = {
            "name",
            "msg",
            "args",
            "levelname",
            "levelno",
            "pathname",
            "filename",
            "module",
            "exc_info",
            "exc_text",
            "stack_info",
            "lineno",
            "funcName",
            "created",
            "msecs",
            "relativeCreated",
            "thread",
            "threadName",
            "processName",
            "process",
            "message",
            "asctime",
        }
        for key, value in record.__dict__.items():
            if key not in reserved:
                payload[key] = value

        return json.dumps(payload, ensure_ascii=False, default=str)


def configure_logging(level: str | None = None) -> None:
    """Configure root logger with JSON output to stderr.

    Idempotent: if our ``JSONFormatter`` is already attached, only the level
    is refreshed; any pre-existing non-JSON handlers are removed so the
    structured-log contract holds even when a host (e.g. pytest capture,
    third-party plugins) has already attached its own handler.
    """
    root = logging.getLogger()
    effective_level = (level or os.environ.get("LOG_LEVEL", "INFO")).upper()

    # Drop any handlers that don't carry our JSONFormatter so structured
    # logging always takes effect, but never remove our own (avoids duplicate
    # output on repeated calls within the same process).
    root.handlers = [h for h in root.handlers if isinstance(h.formatter, JSONFormatter)]

    if not root.handlers:
        handler = logging.StreamHandler(sys.stderr)
        handler.setFormatter(JSONFormatter())
        root.addHandler(handler)

    root.setLevel(effective_level)

    # Keep noisy HTTP libraries quiet so they don't pollute MCP stdio.
    for noisy in ("httpx", "httpcore"):
        logging.getLogger(noisy).setLevel(logging.WARNING)


class StructuredLogger:
    """Convenience wrapper that turns keyword arguments into `extra` fields."""

    def __init__(self, name: str):
        self._logger = logging.getLogger(name)

    def _dispatch(self, level_method: str, msg: str, **kwargs: Any) -> None:
        reserved = {"exc_info", "stack_info", "stacklevel"}
        extra = {k: v for k, v in kwargs.items() if k not in reserved}
        call_kwargs: dict[str, Any] = {"extra": extra}
        for key in reserved:
            if key in kwargs:
                call_kwargs[key] = kwargs[key]
        getattr(self._logger, level_method)(msg, **call_kwargs)

    def debug(self, msg: str, **kwargs: Any) -> None:
        self._dispatch("debug", msg, **kwargs)

    def info(self, msg: str, **kwargs: Any) -> None:
        self._dispatch("info", msg, **kwargs)

    def warning(self, msg: str, **kwargs: Any) -> None:
        self._dispatch("warning", msg, **kwargs)

    def error(self, msg: str, **kwargs: Any) -> None:
        self._dispatch("error", msg, **kwargs)

    def exception(self, msg: str, **kwargs: Any) -> None:
        self._dispatch("exception", msg, **kwargs)


def get_logger(name: str) -> StructuredLogger:
    """Return a structured logger that emits JSON when configured."""
    return StructuredLogger(name)
