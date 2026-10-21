"""Shared structured logging for API and Worker processes."""

from __future__ import annotations

import json
import logging
from contextvars import ContextVar
from datetime import UTC, datetime
from typing import Any

from app.config import Settings

request_id_context: ContextVar[str | None] = ContextVar(
    "request_id",
    default=None,
)

_API_EXTRA_FIELDS = (
    "method",
    "path",
    "status_code",
    "duration_ms",
)
_WORKER_EXTRA_FIELDS = (
    "event",
    "worker_instance_id",
    "queue_name",
    "outcome",
    "duration_ms",
    "attempt",
    "failure_code",
)


class JsonFormatter(logging.Formatter):
    """Emit one allowlisted JSON object per application log record."""

    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, Any] = {
            "timestamp": datetime.fromtimestamp(record.created, tz=UTC).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }

        request_id = getattr(record, "request_id", None) or request_id_context.get()
        if request_id is not None:
            payload["request_id"] = request_id

        for field_name in _API_EXTRA_FIELDS:
            field_value = getattr(record, field_name, None)
            if field_value is not None:
                payload[field_name] = field_value

        if hasattr(record, "event"):
            for field_name in _WORKER_EXTRA_FIELDS:
                payload[field_name] = getattr(record, field_name, None)
            item_id = getattr(record, "item_id", None)
            if item_id is not None:
                payload["item_id"] = item_id

        if record.exc_info:
            payload["exception"] = self.formatException(record.exc_info)

        return json.dumps(payload, ensure_ascii=False, default=str)


def configure_logging(settings: Settings, *, logger_name: str = "app") -> None:
    """Configure one application logger without replacing host handlers."""

    app_logger = logging.getLogger(logger_name)
    app_logger.handlers.clear()

    handler = logging.StreamHandler()
    handler.setFormatter(JsonFormatter())
    app_logger.addHandler(handler)
    app_logger.setLevel(settings.numeric_log_level)
    app_logger.propagate = False


__all__ = ("JsonFormatter", "configure_logging", "request_id_context")
