from __future__ import annotations

import logging
from datetime import UTC, datetime
from typing import Any, cast
from unittest.mock import Mock

from app.catalog.return_dedup_repository import ReturnDedupIntegrityError
from app.worker.observability import PollOutcome, QueueName
from app.worker.return_dedup import ReturnDedupWorker
from app.worker.runner import WorkerRunner

NOW = datetime(2026, 8, 27, tzinfo=UTC)


class _FakeTelemetry:
    def __init__(self) -> None:
        self.calls: list[str] = []
        self.claimable = True
        self.start_failures: set[QueueName] = set()
        self.completion_failures: set[QueueName] = set()

    def can_claim(self) -> bool:
        self.calls.append("can_claim")
        return self.claimable

    def poll_started(self, queue_name: QueueName) -> None:
        self.calls.append(f"poll_started:{queue_name}")
        if queue_name in self.start_failures:
            raise RuntimeError("synthetic state-start write failure")

    def poll_succeeded(self, queue_name: QueueName, outcome: PollOutcome) -> None:
        self.calls.append(
            f"poll_succeeded:{queue_name}:{outcome.result_code}:{outcome.did_work}"
        )
        if queue_name in self.completion_failures:
            raise RuntimeError("synthetic state-completion write failure")

    def poll_failed(self, queue_name: QueueName, failure_code: str) -> None:
        self.calls.append(f"poll_failed:{queue_name}:{failure_code}")
        if queue_name in self.completion_failures:
            raise RuntimeError("synthetic state-completion write failure")


def _worker(name: QueueName, calls: list[str], result: object | None) -> Mock:
    worker = Mock()

    def run_once() -> object | None:
        calls.append(f"run:{name}")
        return result

    worker.run_once.side_effect = run_once
    return worker


def test_return_dedup_domain_error_archives_claimed_job() -> None:
    repository = Mock()
    lease = object()
    failed_job = object()
    repository.next_claimable.return_value = (7, 2)
    repository.claim.return_value = lease
    repository.load_frozen_input.side_effect = ReturnDedupIntegrityError()
    repository.fail.return_value = failed_job
    worker = ReturnDedupWorker(cast(Any, repository), clock=lambda: NOW)

    assert worker.run_once() is failed_job
    repository.fail.assert_called_once_with(
        lease,
        reason_code="return_dedup_integrity_error",
        retry_allowed=False,
        occurred_at=NOW,
    )


def test_runner_isolates_queue_failures_and_continues_pass() -> None:
    calls: list[str] = []
    telemetry = _FakeTelemetry()
    outbox_item = object()
    import_result = object()
    return_dedup = _worker("return_dedup", calls, None)
    outbox = _worker("publication_outbox", calls, outbox_item)
    catalog_exports = _worker("catalog_export", calls, None)
    catalog_imports = _worker("catalog_import", calls, import_result)
    return_dedup.run_once.side_effect = RuntimeError("secret dedup payload")
    catalog_exports.run_once.side_effect = RuntimeError("secret export payload")
    runner = WorkerRunner(
        return_dedup=cast(Any, return_dedup),
        outbox=cast(Any, outbox),
        catalog_exports=cast(Any, catalog_exports),
        catalog_imports=cast(Any, catalog_imports),
        telemetry=telemetry,
    )

    result = runner.run_once()

    assert result.return_dedup is None
    assert result.outbox is outbox_item
    assert result.catalog_export is None
    assert result.catalog_import is import_result
    assert result.did_work
    outbox.run_once.assert_called_once_with()
    catalog_imports.run_once.assert_called_once_with()
    assert telemetry.calls == [
        "can_claim",
        "poll_started:return_dedup",
        "poll_failed:return_dedup:consumer_unexpected_error",
        "can_claim",
        "poll_started:publication_outbox",
        "poll_succeeded:publication_outbox:queue_work_completed:True",
        "can_claim",
        "poll_started:catalog_export",
        "poll_failed:catalog_export:consumer_unexpected_error",
        "can_claim",
        "poll_started:catalog_import",
        "poll_succeeded:catalog_import:queue_work_completed:True",
    ]


def test_runner_records_order_and_idle_or_work_outcomes_for_all_queues() -> None:
    calls: list[str] = []
    telemetry = _FakeTelemetry()
    results = {
        "return_dedup": None,
        "publication_outbox": object(),
        "catalog_export": None,
        "catalog_import": object(),
    }
    runner = WorkerRunner(
        return_dedup=cast(Any, _worker("return_dedup", calls, results["return_dedup"])),
        outbox=cast(
            Any, _worker("publication_outbox", calls, results["publication_outbox"])
        ),
        catalog_exports=cast(
            Any, _worker("catalog_export", calls, results["catalog_export"])
        ),
        catalog_imports=cast(
            Any, _worker("catalog_import", calls, results["catalog_import"])
        ),
        telemetry=telemetry,
    )

    worker_pass = runner.run_once()

    assert calls == [
        "run:return_dedup",
        "run:publication_outbox",
        "run:catalog_export",
        "run:catalog_import",
    ]
    assert telemetry.calls == [
        "can_claim",
        "poll_started:return_dedup",
        "poll_succeeded:return_dedup:queue_idle:False",
        "can_claim",
        "poll_started:publication_outbox",
        "poll_succeeded:publication_outbox:queue_work_completed:True",
        "can_claim",
        "poll_started:catalog_export",
        "poll_succeeded:catalog_export:queue_idle:False",
        "can_claim",
        "poll_started:catalog_import",
        "poll_succeeded:catalog_import:queue_work_completed:True",
    ]
    assert worker_pass.return_dedup is None
    assert worker_pass.outbox is results["publication_outbox"]
    assert worker_pass.catalog_export is None
    assert worker_pass.catalog_import is results["catalog_import"]


def test_runner_does_not_call_consumer_when_claim_gate_is_closed() -> None:
    telemetry = _FakeTelemetry()
    telemetry.claimable = False
    return_dedup = Mock()
    outbox = Mock()
    runner = WorkerRunner(
        return_dedup=cast(Any, return_dedup),
        outbox=cast(Any, outbox),
        telemetry=telemetry,
    )

    result = runner.run_once()

    assert not result.did_work
    return_dedup.run_once.assert_not_called()
    outbox.run_once.assert_not_called()
    assert telemetry.calls == ["can_claim", "can_claim"]


def test_runner_does_not_call_consumer_when_poll_start_write_fails() -> None:
    calls: list[str] = []
    telemetry = _FakeTelemetry()
    telemetry.start_failures.add("return_dedup")
    return_dedup = _worker("return_dedup", calls, object())
    outbox_result = object()
    outbox = _worker("publication_outbox", calls, outbox_result)
    runner = WorkerRunner(
        return_dedup=cast(Any, return_dedup),
        outbox=cast(Any, outbox),
        telemetry=telemetry,
    )

    result = runner.run_once()

    assert result.return_dedup is None
    assert result.outbox is outbox_result
    assert calls == ["run:publication_outbox"]
    assert telemetry.calls == [
        "can_claim",
        "poll_started:return_dedup",
        "can_claim",
        "poll_started:publication_outbox",
        "poll_succeeded:publication_outbox:queue_work_completed:True",
    ]


def test_post_work_telemetry_failure_does_not_repeat_business_work(
    caplog: Any,
) -> None:
    calls: list[str] = []
    telemetry = _FakeTelemetry()
    telemetry.completion_failures.add("return_dedup")
    completed = object()
    return_dedup = _worker("return_dedup", calls, completed)
    outbox = _worker("publication_outbox", calls, None)
    runner = WorkerRunner(
        return_dedup=cast(Any, return_dedup),
        outbox=cast(Any, outbox),
        telemetry=telemetry,
    )

    with caplog.at_level(logging.ERROR, logger="app.worker.runner"):
        result = runner.run_once()

    assert result.return_dedup is completed
    assert calls.count("run:return_dedup") == 1
    assert "run:publication_outbox" in calls
    record = next(
        item
        for item in caplog.records
        if getattr(item, "failure_code", None) == "consumer_state_write_failed"
    )
    assert record.queue_name == "return_dedup"
    assert "synthetic state-completion write failure" not in record.failure_code
