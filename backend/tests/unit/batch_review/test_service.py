from __future__ import annotations

from datetime import date
from typing import cast
from uuid import uuid4

import pytest
from app.batch_review.repository import (
    BatchReviewRunRecord,
    CandidateFacts,
    MySqlBatchReviewRepository,
)
from app.batch_review.service import BatchReviewService
from app.batch_review.types import (
    BatchReviewCandidate,
    BatchReviewItemStatus,
    BatchReviewPermissionDenied,
    BatchReviewRunStatus,
    BatchReviewTargetState,
    ChangeBatchReviewRunStateCommand,
    ConfirmBatchReviewCommand,
    CreatePreflightCommand,
)


class _FakeRepository:
    def __init__(self) -> None:
        self.created: tuple[CreatePreflightCommand, object] | None = None

    def load_candidates(
        self, site_id: int, batch_ids: tuple[int, ...], actor_roles: frozenset[str]
    ) -> tuple[CandidateFacts, ...]:
        return tuple(
            CandidateFacts(
                BatchReviewCandidate(
                    batch_id=batch_id,
                    site_id=site_id,
                    filename=f"{batch_id}.csv",
                    report_date=date(2026, 8, batch_id),
                    report_type="business_report",
                    encoding="utf-8-sig",
                    recognition_status="recognized",
                    source_available=True,
                    batch_status="uploaded",
                    already_materialized=False,
                    actor_roles=actor_roles,
                ),
                BatchReviewTargetState(),
                "00" * 32,
            )
            for batch_id in batch_ids
        )

    def create_preflight(
        self, command: CreatePreflightCommand, items: object
    ) -> BatchReviewRunRecord:
        self.created = (command, items)
        return BatchReviewRunRecord(
            1,
            command.site_id,
            command.actor_user_id,
            BatchReviewRunStatus.PREVIEW,
            0,
            None,
            (),
        )

    def get_run(self, run_id: int, site_id: int) -> BatchReviewRunRecord:
        return BatchReviewRunRecord(
            run_id, site_id, 2, BatchReviewRunStatus.PREVIEW, 0, None, ()
        )


def _service(repository: _FakeRepository) -> BatchReviewService:
    return BatchReviewService(cast(MySqlBatchReviewRepository, repository))


def test_create_preflight_sorts_server_facts_and_returns_summary() -> None:
    repository = _FakeRepository()
    view = _service(repository).create_preflight(
        CreatePreflightCommand(1, 2, frozenset({"admin"}), (8, 3), uuid4())
    )

    assert repository.created is not None
    assert view.status == BatchReviewRunStatus.PREVIEW
    assert view.summary.total == 0


def test_create_preflight_rejects_non_writer_even_before_repository_access() -> None:
    repository = _FakeRepository()
    with pytest.raises(BatchReviewPermissionDenied):
        _service(repository).create_preflight(
            CreatePreflightCommand(1, 2, frozenset({"viewer"}), (3,), uuid4())
        )
    assert repository.created is None


def test_confirmation_statement_version_is_fixed() -> None:
    repository = _FakeRepository()
    with pytest.raises(ValueError, match="statement version"):
        _service(repository).confirm(
            ConfirmBatchReviewCommand(1, 1, 2, 0, (1,), True, "old", uuid4())
        )


def test_pause_and_resume_have_strict_source_states() -> None:
    repository = _FakeRepository()
    service = _service(repository)
    pause = ChangeBatchReviewRunStateCommand(1, 1, 2, 0, "pause", uuid4())
    resume = ChangeBatchReviewRunStateCommand(1, 1, 2, 0, "resume", uuid4())

    assert service.requested_run_transition(pause) == (
        BatchReviewRunStatus.RUNNING,
        BatchReviewRunStatus.PAUSED,
    )
    assert service.requested_run_transition(resume) == (
        BatchReviewRunStatus.PAUSED,
        BatchReviewRunStatus.RUNNING,
    )


def test_summary_distinguishes_ready_manual_failed_and_active() -> None:
    summary = BatchReviewService.summarize_statuses(
        (
            BatchReviewItemStatus.READY_FOR_PUBLISH,
            BatchReviewItemStatus.MANUAL_REVIEW,
            BatchReviewItemStatus.FAILED,
            BatchReviewItemStatus.QUEUED,
        )
    )
    assert (
        summary.ready_for_publish,
        summary.manual_review,
        summary.failed,
        summary.active,
    ) == (1, 1, 1, 1)
