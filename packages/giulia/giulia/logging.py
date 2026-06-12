"""Logging configuration: loguru as the single logging interface.

On GCP (detected via KUBERNETES_SERVICE_HOST or K_SERVICE), logs are formatted
as structured JSON with the "severity" field that GCP Cloud Logging expects.
Locally, loguru's default colored stderr sink is used.

Usage:
    from giulia.logging import logger
    # or
    from giulia import logger

    logger.info("Hello, world!")

Logging is configured automatically on first access via a module-level
descriptor. No explicit setup_logging() call is needed.
"""

from __future__ import annotations

import json
import logging as stdlib_logging
import os
import sys
import traceback
from datetime import UTC, datetime
from types import FrameType
from typing import Any

from loguru import logger as _loguru_logger

_LOGURU_TO_GCP_SEVERITY: dict[str, str] = {
    "TRACE": "DEBUG",
    "DEBUG": "DEBUG",
    "INFO": "INFO",
    "SUCCESS": "INFO",
    "WARNING": "WARNING",
    "ERROR": "ERROR",
    "CRITICAL": "CRITICAL",
}

_configured = False


def _is_gcp() -> bool:
    return bool(os.getenv("KUBERNETES_SERVICE_HOST") or os.getenv("K_SERVICE"))


def _gcp_sink(message: Any) -> None:
    """Sink that formats loguru records as GCP Cloud Logging-compatible JSON.

    GCP Cloud Logging on GKE automatically parses JSON logs from stderr and maps:
      - "severity" → LogEntry.severity (DEBUG, INFO, WARNING, ERROR, CRITICAL)
      - "message" → LogEntry.textPayload or jsonPayload.message
      - "time" → LogEntry.timestamp
      - "logging.googleapis.com/sourceLocation" → source location
      - "logging.googleapis.com/labels" → LogEntry.labels
    """
    record = message.record

    severity = _LOGURU_TO_GCP_SEVERITY.get(record["level"].name, "DEFAULT")

    log_entry: dict[str, Any] = {
        "severity": severity,
        "message": record["message"],
        "time": datetime.now(UTC).isoformat(),
        "logger": record["name"] or "root",
    }

    if record["function"]:
        log_entry["logging.googleapis.com/sourceLocation"] = {
            "file": record["file"].path if record["file"] else "",
            "line": str(record["line"]),
            "function": record["function"],
        }

    exc_info = record["exception"]
    if exc_info is not None:
        if exc_info.type and exc_info.value and exc_info.traceback:
            log_entry["exception"] = "".join(
                traceback.format_exception(
                    exc_info.type, exc_info.value, exc_info.traceback
                )
            )
        if severity not in ("ERROR", "CRITICAL"):
            log_entry["severity"] = "ERROR"

    extra = record.get("extra", {})
    if extra:
        log_entry["logging.googleapis.com/labels"] = {
            k: str(v) for k, v in extra.items() if v is not None
        }

    sys.stderr.write(json.dumps(log_entry, ensure_ascii=False, default=str) + "\n")
    sys.stderr.flush()


class _InterceptHandler(stdlib_logging.Handler):
    """Bridge stdlib logging → loguru so third-party libraries (uvicorn,
    google-adk, starlette, …) emit through the same pipeline."""

    def emit(self, record: stdlib_logging.LogRecord) -> None:
        try:
            level: str | int = _loguru_logger.level(record.levelname).name
        except ValueError:
            level = record.levelno
        frame: FrameType | None = stdlib_logging.currentframe()
        depth = 2
        while frame and frame.f_code.co_filename == stdlib_logging.__file__:
            frame = frame.f_back
            depth += 1
        _loguru_logger.opt(depth=depth, exception=record.exc_info).log(
            level, record.getMessage()
        )


def _configure_logging() -> None:
    """Configure loguru sinks and stdlib logging bridge.

    This function is idempotent and thread-safe via the global _configured flag.
    It's called automatically when accessing the `logger` attribute.
    """
    global _configured
    if _configured:
        return
    _configured = True

    _loguru_logger.remove()

    if _is_gcp():
        _loguru_logger.add(
            _gcp_sink,
            format="{message}",
            level="INFO",
        )
    else:
        _loguru_logger.add(
            sys.stderr,
            format=(
                "<green>{time:YYYY-MM-DD HH:mm:ss}</green> | "
                "<level>{level: <8}</level> | "
                "<cyan>{name}</cyan>:<cyan>{function}</cyan>:<cyan>{line}</cyan> - "
                "<level>{message}</level>"
            ),
            level="DEBUG",
            colorize=True,
        )

    stdlib_logging.basicConfig(
        handlers=[_InterceptHandler()], level=stdlib_logging.INFO, force=True
    )
    for name in (
        "uvicorn",
        "uvicorn.error",
        "uvicorn.access",
        "starlette",
        "google.adk",
        "a2a",
    ):
        log = stdlib_logging.getLogger(name)
        log.handlers = [_InterceptHandler()]
        log.propagate = False


class _LazyLogger:
    """Proxy that configures logging on first attribute access.

    This allows `from giulia.logging import logger` to work without
    triggering configuration at import time. Configuration happens
    on first actual use (e.g., logger.info("...")).
    """

    __slots__ = ()

    def __getattr__(self, name: str) -> Any:
        _configure_logging()
        return getattr(_loguru_logger, name)

    def __repr__(self) -> str:
        return repr(_loguru_logger)


logger = _LazyLogger()

__all__ = ["logger"]
