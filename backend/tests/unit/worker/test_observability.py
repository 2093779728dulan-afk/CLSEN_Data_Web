from __future__ import annotations

from uuid import UUID

import pytest
from app.catalog.export_service import CatalogExportFinalizationError
from app.catalog.import_repository import CatalogImportRepositoryError
from app.catalog.return_dedup_repository import ReturnDedupError
from app.worker.observability import (
    HEARTBEAT_SECONDS,
    OFFLINE_SECONDS,
    QUEUE_NAMES,
    REFRESH_SECONDS,
    RETENTION_DAYS,
    RETENTION_DELETE_LIMIT,
    STALE_SECONDS,
    PollOutcome,
    safe_failure_code,
    worker_log_extra,
)
from app.worker.outbox import OutboxError


def test_frozen_thresholds_and_queue_order_match_stage_zero_approval() -> None:
    assert (HEARTBEAT_SECONDS, STALE_SECONDS, OFFLINE_SECONDS, REFRESH_SECONDS) == (
        10,
        30,
        60,
        15,
    )
    assert RETENTION_DAYS == 30
    assert RETENTION_DELETE_LIMIT == 500
    assert QUEUE_NAMES == (
        "return_dedup",
        "publication_outbox",
        "catalog_export",
        "catalog_import",
    )


@pytest.mark.parametrize(
    ("queue_name", "error", "expected"),
    (
        ("return_dedup", ReturnDedupError(), "return_dedup_error"),
        ("publication_outbox", OutboxError(), "publication_outbox_error"),
        (
            "catalog_export",
            CatalogExportFinalizationError(),
            "catalog_export_error",
        ),
        (
            "catalog_import",
            CatalogImportRepositoryError(),
            "catalog_import_error",
        ),
    ),
)
def test_known_domain_errors_map_to_closed_codes(
    queue_name: str,
    error: BaseException,
    expected: str,
) -> None:
    assert safe_failure_code(error, queue_name) == expected  # type: ignore[arg-type]


def test_unknown_error_never_returns_exception_text() -> None:
    error = RuntimeError("customer@example.com secret order 123")

    assert safe_failure_code(error, "catalog_import") == "consumer_unexpected_error"


def test_worker_log_extra_contains_only_fixed_safe_fields() -> None:
    payload = worker_log_extra(
        event="worker_poll_failed",
        instance_id=UUID(int=1),
        queue_name="catalog_import",
        outcome="failed",
        duration_ms=2.5,
        attempt=3,
        failure_code="consumer_unexpected_error",
    )

    assert set(payload) == {
        "event",
        "worker_instance_id",
        "queue_name",
        "outcome",
        "duration_ms",
        "attempt",
        "failure_code",
    }
    assert payload["worker_instance_id"] == UUID(int=1).hex


def test_worker_log_extra_rejects_unsafe_values() -> None:
    with pytest.raises(ValueError, match="duration"):
        worker_log_extra(
            event="worker_poll_failed",
            instance_id=UUID(int=1),
            queue_name="catalog_import",
            outcome="failed",
            duration_ms=-1,
            attempt=1,
            failure_code="consumer_unexpected_error",
        )
    with pytest.raises(ValueError, match="failure code"):
        worker_log_extra(
            event="worker_poll_failed",
            instance_id=UUID(int=1),
            queue_name="catalog_import",
            outcome="failed",
            duration_ms=1,
            attempt=1,
            failure_code="raw customer detail",
        )


def test_poll_outcome_is_immutable() -> None:
    outcome = PollOutcome(result_code="queue_idle", did_work=False)

    with pytest.raises(AttributeError):
        outcome.did_work = True  # type: ignore[misc]
