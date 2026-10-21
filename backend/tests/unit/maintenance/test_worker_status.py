from __future__ import annotations

from datetime import UTC, datetime

import pytest
from app.maintenance import worker_status
from app.maintenance.worker_status import (
    _queue_status_from_row,
    _unknown_queue_status,
    classify_heartbeat,
)
from app.worker.observability import QueueName

OBSERVED_AT = datetime(2026, 9, 4, 8, 0, tzinfo=UTC)


@pytest.mark.parametrize(
    ("age_seconds", "expected"),
    [
        (29.999, "online"),
        (30.0, "stale"),
        (59.999, "stale"),
        (60.0, "offline"),
    ],
)
def test_heartbeat_boundaries(age_seconds: float, expected: str) -> None:
    assert (
        classify_heartbeat(
            age_seconds=age_seconds,
            lifecycle_status="running",
        )
        == expected
    )


def test_stopped_and_missing_heartbeat_classification() -> None:
    assert classify_heartbeat(age_seconds=0, lifecycle_status="stopped") == "stopped"
    assert classify_heartbeat(age_seconds=None, lifecycle_status="running") == "unknown"


def test_publication_outbox_maps_actionable_retry_and_stale_work() -> None:
    status = _queue_status_from_row(
        "publication_outbox",
        {
            "native_status_counts": {
                "pending": 3,
                "processing": 2,
                "completed": 4,
                "failed": 1,
            },
            "actionable": 2,
            "in_flight": 1,
            "retry_wait": 1,
            "stale": 1,
            "stuck": None,
            "failed": 1,
            "unresolved_building": None,
            "oldest_work_at": OBSERVED_AT,
            "next_retry_at": OBSERVED_AT,
        },
    )

    assert status.native_status_counts == {
        "pending": 3,
        "processing": 2,
        "completed": 4,
        "failed": 1,
    }
    assert status.actionable == 2
    assert status.in_flight == 1
    assert status.retry_wait == 1
    assert status.stale == 1
    assert status.stuck is None
    assert status.failed == 1
    assert status.capabilities.stuck is False


def test_return_dedup_maps_expired_lease_as_actionable_and_stale() -> None:
    status = _queue_status_from_row(
        "return_dedup",
        {
            "native_status_counts": {
                "building": 3,
                "ready": 4,
                "failed": 1,
                "superseded": 2,
            },
            "actionable": 2,
            "in_flight": 1,
            "retry_wait": None,
            "stale": 1,
            "stuck": None,
            "failed": 1,
            "unresolved_building": None,
            "oldest_work_at": OBSERVED_AT,
            "next_retry_at": None,
        },
    )

    assert status.actionable == 2
    assert status.in_flight == 1
    assert status.stale == 1
    assert status.retry_wait is None
    assert status.stuck is None
    assert status.capabilities.retry_wait is False
    assert status.capabilities.stuck is False


def test_catalog_import_maps_uploaded_and_expired_parsing_without_requeueing() -> None:
    status = _queue_status_from_row(
        "catalog_import",
        {
            "native_status_counts": {
                "uploaded": 2,
                "parsing": 3,
                "parse_failed": 1,
                "needs_attention": 4,
                "validated": 5,
                "ready_for_approval": 6,
                "approved": 7,
                "rejected": 8,
                "withdrawn": 9,
                "superseded": 10,
            },
            "actionable": 2,
            "in_flight": 1,
            "retry_wait": None,
            "stale": None,
            "stuck": 2,
            "failed": 1,
            "unresolved_building": None,
            "oldest_work_at": OBSERVED_AT,
            "next_retry_at": None,
        },
    )

    assert status.actionable == 2
    assert status.in_flight == 1
    assert status.stuck == 2
    assert status.stale is None
    assert status.capabilities.stale is False


def test_catalog_export_keeps_unprovable_metrics_null() -> None:
    status = _queue_status_from_row(
        "catalog_export",
        {
            "native_status_counts": {"building": 2, "ready": 3, "failed": 1},
            "actionable": None,
            "in_flight": None,
            "retry_wait": None,
            "stale": None,
            "stuck": None,
            "failed": 1,
            "unresolved_building": 2,
            "oldest_work_at": OBSERVED_AT,
            "next_retry_at": None,
        },
    )

    assert status.unresolved_building == 2
    assert status.actionable is None
    assert status.in_flight is None
    assert status.retry_wait is None
    assert status.stale is None
    assert status.stuck is None
    assert status.capabilities.actionable is False
    assert status.capabilities.in_flight is False
    assert status.capabilities.retry_wait is False
    assert status.capabilities.stale is False
    assert status.capabilities.stuck is False


def test_failed_queue_query_has_null_native_metrics() -> None:
    status = _unknown_queue_status(
        "catalog_import",
        failure_code="catalog_import_query_failed",
    )

    assert status.query_health == "unknown"
    assert status.failure_code == "catalog_import_query_failed"
    assert status.native_status_counts is None
    assert status.actionable is None
    assert status.in_flight is None
    assert status.retry_wait is None
    assert status.stale is None
    assert status.stuck is None
    assert status.failed is None
    assert status.oldest_work_at is None
    assert status.next_retry_at is None


def test_failed_fleet_query_is_unknown_and_maintenance_does_not_mask_it(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class _Connection:
        def __enter__(self) -> _Connection:
            return self

        def __exit__(self, *_args: object) -> None:
            return None

        def scalar(self, _statement: object) -> datetime:
            return OBSERVED_AT.replace(tzinfo=None)

    class _Engine:
        def connect(self) -> _Connection:
            return _Connection()

    def fail_workers(*_args: object, **_kwargs: object) -> object:
        raise RuntimeError("synthetic fleet query failure")

    def empty_queue(
        _engine: object,
        *,
        queue_name: QueueName,
        observed_at: datetime,
        consumer: object,
    ) -> object:
        assert observed_at == OBSERVED_AT
        return _queue_status_from_row(
            queue_name,
            {
                "native_status_counts": {},
                "actionable": 0,
                "in_flight": 0,
                "retry_wait": 0,
                "stale": 0,
                "stuck": 0,
                "failed": 0,
                "unresolved_building": 0,
                "oldest_work_at": None,
                "next_retry_at": None,
            },
            consumer,  # type: ignore[arg-type]
        )

    monkeypatch.setattr(worker_status, "_read_workers", fail_workers)
    monkeypatch.setattr(worker_status, "_read_queue", empty_queue)

    observed_at, fleet, queues = worker_status.read_worker_observability(
        _Engine(),  # type: ignore[arg-type]
        maintenance_active=True,
    )

    assert observed_at == OBSERVED_AT
    assert fleet.query_health == "unknown"
    assert fleet.failure_code == "worker_fleet_query_failed"
    assert fleet.instances == []
    assert all(queue.consumer_health == "unknown" for queue in queues)


def test_queue_consumer_health_uses_only_online_instances() -> None:
    online_consumer = worker_status.WorkerConsumerStatusResponse(
        queue_name="catalog_import",
        consumer_health="failing",
        last_poll_started_at=OBSERVED_AT,
        last_poll_completed_at=OBSERVED_AT,
        last_poll_succeeded_at=None,
        last_poll_failed_at=OBSERVED_AT,
        consecutive_failures=2,
        failure_code="consumer_unexpected_error",
    )
    offline_consumer = online_consumer.model_copy(update={"consecutive_failures": 9})
    common = {
        "role": "local_worker",
        "build_id": "unit-build",
        "supported_queues": [
            "return_dedup",
            "publication_outbox",
            "catalog_export",
            "catalog_import",
        ],
        "lifecycle_status": "running",
        "heartbeat_sequence": 1,
        "last_heartbeat_at": OBSERVED_AT,
        "last_result_code": "heartbeat_succeeded",
    }
    fleet = worker_status.WorkerFleetStatusResponse(
        query_health="healthy",
        failure_code=None,
        thresholds=worker_status.HeartbeatThresholdsResponse(
            heartbeat_seconds=10,
            stale_seconds=30,
            offline_seconds=60,
            refresh_seconds=15,
        ),
        instances=[
            worker_status.WorkerInstanceStatusResponse(
                instance_id="01" * 16,
                heartbeat_status="online",
                heartbeat_age_seconds=1,
                consumers=[online_consumer],
                **common,  # type: ignore[arg-type]
            ),
            worker_status.WorkerInstanceStatusResponse(
                instance_id="02" * 16,
                heartbeat_status="offline",
                heartbeat_age_seconds=61,
                consumers=[offline_consumer],
                **common,  # type: ignore[arg-type]
            ),
        ],
    )

    summary = worker_status._consumer_summaries(fleet)["catalog_import"]

    assert summary.health == "failing"
    assert summary.consecutive_failures == 2
    assert summary.failure_code == "consumer_unexpected_error"
