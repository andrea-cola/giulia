"""
Google Cloud Logging configuration for structured JSON logging.

When running on GKE or Cloud Run, Cloud Logging automatically ingests
container logs. This module configures Python logging to emit structured
JSON that Cloud Logging parses into proper LogEntry fields.

Usage:
    from giulia_gateway.logging_config import setup_logging
    setup_logging()
"""

import json
import logging
import os
import sys
from datetime import UTC, datetime
from typing import Any


class CloudLoggingFormatter(logging.Formatter):
    """Formats log records as JSON for Google Cloud Logging.

    Cloud Logging automatically parses JSON logs and maps fields:
      - "severity" -> LogEntry.severity
      - "message" -> LogEntry.textPayload or jsonPayload.message
      - "time" -> LogEntry.timestamp
      - "logging.googleapis.com/labels" -> LogEntry.labels
      - "logging.googleapis.com/trace" -> LogEntry.trace
    """

    SEVERITY_MAP = {
        logging.DEBUG: "DEBUG",
        logging.INFO: "INFO",
        logging.WARNING: "WARNING",
        logging.ERROR: "ERROR",
        logging.CRITICAL: "CRITICAL",
    }

    def __init__(
        self, service_name: str = "llm-gateway", project_id: str | None = None
    ):
        super().__init__()
        self.service_name = service_name
        self.project_id = project_id or os.environ.get("GOOGLE_CLOUD_PROJECT", "")

    def format(self, record: logging.LogRecord) -> str:
        log_entry: dict[str, Any] = {
            "severity": self.SEVERITY_MAP.get(record.levelno, "DEFAULT"),
            "message": record.getMessage(),
            "time": datetime.now(UTC).isoformat(),
            "logging.googleapis.com/labels": {
                "service": self.service_name,
                "logger": record.name,
            },
        }

        if record.name:
            log_entry["logger"] = record.name

        if record.funcName and record.funcName != "<module>":
            log_entry["function"] = record.funcName

        if record.pathname:
            log_entry["logging.googleapis.com/sourceLocation"] = {
                "file": record.pathname,
                "line": str(record.lineno),
                "function": record.funcName,
            }

        if record.exc_info:
            log_entry["exception"] = self.formatException(record.exc_info)
            log_entry["severity"] = "ERROR"

        request_id: str = getattr(record, "request_id", "")
        if request_id:
            log_entry["logging.googleapis.com/labels"]["request_id"] = request_id
            if self.project_id:
                log_entry["logging.googleapis.com/trace"] = (
                    f"projects/{self.project_id}/traces/{request_id}"
                )

        model: str = getattr(record, "model", "")
        if model:
            log_entry["logging.googleapis.com/labels"]["model"] = model

        extra_fields: Any = getattr(record, "extra_fields", None)
        if isinstance(extra_fields, dict):
            log_entry.update(extra_fields)

        return json.dumps(log_entry, ensure_ascii=False, default=str)


class LocalFormatter(logging.Formatter):
    """Human-readable formatter for local development."""

    COLORS = {
        logging.DEBUG: "\033[36m",  # Cyan
        logging.INFO: "\033[32m",  # Green
        logging.WARNING: "\033[33m",  # Yellow
        logging.ERROR: "\033[31m",  # Red
        logging.CRITICAL: "\033[35m",  # Magenta
    }
    RESET = "\033[0m"

    def format(self, record: logging.LogRecord) -> str:
        color = self.COLORS.get(record.levelno, "")
        timestamp = datetime.now().strftime("%H:%M:%S.%f")[:-3]
        level = record.levelname[:4]
        message = record.getMessage()

        formatted = f"{color}{timestamp} [{level}] {record.name}: {message}{self.RESET}"

        if record.exc_info:
            formatted += f"\n{self.formatException(record.exc_info)}"

        return formatted


def setup_logging(
    level: int = logging.INFO,
    service_name: str = "llm-gateway",
) -> None:
    """Configure logging for the application.

    Uses JSON structured logging in production (GKE/Cloud Run) and
    human-readable colored output for local development.
    """
    on_cloud = bool(
        os.environ.get("KUBERNETES_SERVICE_HOST") or os.environ.get("K_SERVICE")
    )

    root_logger = logging.getLogger()
    root_logger.setLevel(level)

    for handler in root_logger.handlers[:]:
        root_logger.removeHandler(handler)

    handler = logging.StreamHandler(sys.stderr)
    handler.setLevel(level)

    if on_cloud:
        handler.setFormatter(CloudLoggingFormatter(service_name=service_name))
    else:
        handler.setFormatter(LocalFormatter())

    root_logger.addHandler(handler)

    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("httpcore").setLevel(logging.WARNING)
    logging.getLogger("asyncpg").setLevel(logging.WARNING)
    logging.getLogger("google").setLevel(logging.WARNING)
    logging.getLogger("urllib3").setLevel(logging.WARNING)

    logging.getLogger("LiteLLM").setLevel(logging.WARNING)
    logging.getLogger("litellm").setLevel(logging.WARNING)

    os.environ.setdefault("LITELLM_LOG", "WARNING")


def get_logger(name: str) -> logging.Logger:
    """Get a logger with the given name, prefixed with 'llm-gateway.'"""
    if not name.startswith("llm-gateway"):
        name = f"llm-gateway.{name}"
    return logging.getLogger(name)
