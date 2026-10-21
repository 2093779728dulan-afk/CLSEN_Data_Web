from __future__ import annotations

from dataclasses import replace
from uuid import uuid4

import pytest
from app.catalog.export_service import CatalogExportCommand, CatalogExportResult
from app.catalog.workbook import CatalogWorkbookData
from app.worker.catalog_exports import CatalogExportWorker, retry_delay_seconds


def _command(*, attempt_count: int = 1) -> CatalogExportCommand:
    return CatalogExportCommand(
        export_id=41,
        operation_token=uuid4(),
        payload_digest=b"p" * 32,
        workbook=CatalogWorkbookData(rows={}),
        job_id=7,
        job_revision=2,
        lease_token=uuid4(),
        fencing_token=3,
        attempt_count=attempt_count,
    )


class _Source:
    def __init__(self, command: CatalogExportCommand) -> None:
        self.command = command
        self.renewed = False
        self.failed: tuple[CatalogExportCommand, str] | None = None

    def claim_next(self) -> CatalogExportCommand | None:
        return self.command

    def renew(self, command: CatalogExportCommand) -> CatalogExportCommand:
        self.renewed = True
        return replace(command, job_revision=command.job_revision + 1)

    def fail_retryable(self, command: CatalogExportCommand, *, reason: str) -> None:
        self.failed = command, reason


class _Materializer:
    def __init__(self, *, failure: Exception | None = None) -> None:
        self.failure = failure
        self.command: CatalogExportCommand | None = None

    def materialize(self, command: CatalogExportCommand) -> CatalogExportResult:
        self.command = command
        if self.failure is not None:
            raise self.failure
        return CatalogExportResult(command.export_id, "ready", "ready", None, (), None)


def test_retry_policy_is_bounded_exponential_backoff() -> None:
    assert [retry_delay_seconds(attempt) for attempt in range(1, 6)] == [
        5,
        10,
        20,
        40,
        80,
    ]
    assert retry_delay_seconds(20) == 300


def test_worker_renews_claim_before_materialization() -> None:
    source = _Source(_command())
    materializer = _Materializer()

    result = CatalogExportWorker(source=source, materializer=materializer).run_once()

    assert result is not None
    assert source.renewed
    assert materializer.command is not None
    assert materializer.command.job_revision == 3


def test_worker_records_content_free_retryable_failure_and_reraises() -> None:
    source = _Source(_command())
    materializer = _Materializer(failure=RuntimeError("secret storage path"))

    with pytest.raises(RuntimeError, match="secret storage path"):
        CatalogExportWorker(source=source, materializer=materializer).run_once()

    assert source.failed is not None
    assert source.failed[1] == "catalog_export_worker_error"
