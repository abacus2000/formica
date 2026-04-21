"""Structured logging. Emits JSON with fields Fluent Bit can route on."""

from __future__ import annotations

import logging
import os
import sys

_LOG_DRIVER_PREFIXES = (
    "neo4j",
    "strands",
    "kubernetes",
    "urllib3",
    "botocore",
    "boto3",
    "aws",
    "mcp",
    "cuda",
    "nvidia",
)


def _is_driver(logger_name: str) -> bool:
    low = logger_name.lower()
    return any(low.startswith(p) for p in _LOG_DRIVER_PREFIXES)


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        import json
        from datetime import UTC, datetime

        payload = {
            "time": datetime.now(UTC).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
            "component": os.environ.get("FORMICA_COMPONENT", "unknown"),
            "env": os.environ.get("FORMICA_ENV", "dev"),
            "region": os.environ.get("FORMICA_REGION", "us-east-1"),
            "run_id": getattr(record, "run_id", None),
            "trace_id": getattr(record, "trace_id", None),
            "is_driver": _is_driver(record.name),
        }
        # Attach any extra fields the caller set.
        for k, v in record.__dict__.items():
            if k not in payload and k not in (
                "args", "asctime", "created", "exc_info", "exc_text", "filename",
                "funcName", "levelname", "levelno", "lineno", "message", "module",
                "msecs", "msg", "name", "pathname", "process", "processName",
                "relativeCreated", "stack_info", "thread", "threadName",
            ):
                payload[k] = v
        if record.exc_info:
            payload["exc"] = self.formatException(record.exc_info)
        return json.dumps(payload, default=str)


# Noisy third-party loggers that should be quieter than the root level.
# neo4j.notifications emits a WARNING for every Cypher query whose properties
# or relationship types don't yet exist in the graph. While the colony is
# bootstrapping (or running with an empty graph) this floods the controller
# log with a new entry every ~10s per query. See issue #14.
_QUIET_LOGGERS: dict[str, int] = {
    "neo4j.notifications": logging.ERROR,
}


def configure_logging(level: int = logging.INFO) -> None:
    """Configure root logger for JSON output. Idempotent."""
    root = logging.getLogger()
    if getattr(root, "_formica_configured", False):
        return
    root.handlers.clear()
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(JsonFormatter())
    root.addHandler(handler)
    root.setLevel(level)
    for name, lvl in _QUIET_LOGGERS.items():
        logging.getLogger(name).setLevel(lvl)
    setattr(root, "_formica_configured", True)


def get_logger(name: str) -> logging.Logger:
    configure_logging()
    return logging.getLogger(name)
