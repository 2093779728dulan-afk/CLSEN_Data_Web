from __future__ import annotations

import json
import logging
from types import SimpleNamespace
from typing import cast

from app.config import Settings
from app.logging import JsonFormatter, configure_logging, request_id_context


def _record(**extra: object) -> logging.LogRecord:
    return logging.makeLogRecord(
        {
            "name": "app.worker",
            "levelno": logging.INFO,
            "levelname": "INFO",
            "msg": "safe message",
            **extra,
        }
    )


def test_json_formatter_preserves_api_fields_and_ignores_arbitrary_extra() -> None:
    payload = json.loads(
        JsonFormatter().format(
            _record(
                request_id="request-7",
                method="GET",
                path="/api/status",
                status_code=200,
                duration_ms=1.25,
                raw_filename="customer-orders.xlsx",
                password="do-not-log",
            )
        )
    )

    assert payload["request_id"] == "request-7"
    assert payload["method"] == "GET"
    assert payload["path"] == "/api/status"
    assert payload["status_code"] == 200
    assert payload["duration_ms"] == 1.25
    assert "raw_filename" not in payload
    assert "password" not in payload


def test_json_formatter_emits_all_worker_fields_including_nulls() -> None:
    payload = json.loads(
        JsonFormatter().format(
            _record(
                event="worker_heartbeat_succeeded",
                worker_instance_id="0" * 32,
                queue_name=None,
                outcome="succeeded",
                duration_ms=2.5,
                attempt=1,
                failure_code=None,
            )
        )
    )

    assert {
        "timestamp",
        "level",
        "logger",
        "message",
        "event",
        "worker_instance_id",
        "queue_name",
        "outcome",
        "duration_ms",
        "attempt",
        "failure_code",
    } <= payload.keys()
    assert payload["queue_name"] is None
    assert payload["failure_code"] is None


def test_json_formatter_uses_bound_request_id_without_leaking_worker_fields() -> None:
    token = request_id_context.set("bound-request")
    try:
        payload = json.loads(JsonFormatter().format(_record()))
    finally:
        request_id_context.reset(token)

    assert payload["request_id"] == "bound-request"
    assert "event" not in payload
    assert "queue_name" not in payload


def test_configure_logging_targets_the_requested_logger() -> None:
    logger = logging.getLogger("stage2.test.logger")
    previous_handlers = list(logger.handlers)
    previous_level = logger.level
    previous_propagate = logger.propagate
    try:
        settings = cast(
            Settings,
            SimpleNamespace(numeric_log_level=logging.WARNING),
        )
        configure_logging(settings, logger_name=logger.name)

        assert logger.level == logging.WARNING
        assert logger.propagate is False
        assert len(logger.handlers) == 1
        assert isinstance(logger.handlers[0].formatter, JsonFormatter)
    finally:
        logger.handlers[:] = previous_handlers
        logger.setLevel(previous_level)
        logger.propagate = previous_propagate
