from __future__ import annotations

from dataclasses import replace
from datetime import UTC, date, datetime, timedelta
from types import SimpleNamespace
from typing import cast
from uuid import UUID, uuid4

from app.api.batch_reviews import _item_response
from app.batch_review.repository import (
    BatchReviewItemRecord,
    BatchReviewRunRecord,
    CandidateFacts,
    ClaimedItem,
    DraftState,
)
from app.batch_review.service import (
    BatchReviewService,
    _Repository,
    child_operation_token,
    validation_is_clean,
)
from app.batch_review.types import (
    AdvanceBatchReviewItemCommand,
    BatchReviewCandidate,
    BatchReviewItemStatus,
    BatchReviewRunStatus,
    BatchReviewTargetState,
)
from app.review.types import DraftHeadExpectation
from app.validation.types import (
    ValidationRunReceipt,
    ValidationSummary,
    ValidationSummaryStage,
)
from app.workbench.import_orchestration import WorkbenchImportResult


def _item(
    status: BatchReviewItemStatus = BatchReviewItemStatus.QUEUED,
) -> BatchReviewItemRecord:
    return BatchReviewItemRecord(
        2,
        1,
        1,
        7,
        "batch.csv",
        date(2026, 8, 17),
        "business_report",
        "utf-8-sig",
        "recognized",
        True,
        status,
        None,
        None,
        "/review/2026-08-17?report_type=business_report",
        None,
        None,
        None,
        None,
        None,
        None,
        None,
        0,
        False,
        False,
        None,
        0,
    )


def _receipt(*, warnings: int = 0) -> ValidationRunReceipt:
    stage = ValidationSummaryStage("00" * 32, 1, (), warnings, 0)
    summary = ValidationSummary(
        date(2026, 8, 17),
        "business_report",
        1,
        (),
        stage,
        ValidationSummaryStage("00" * 32, 1, (), 0, 0),
    )
    return ValidationRunReceipt(
        uuid4(),
        31,
        11,
        12,
        "draft",
        0,
        0,
        "rules-v1",
        "succeeded",
        "passed",
        bytes(32),
        summary,
        datetime.now(UTC),
    )


class _AdvanceRepository:
    def __init__(self) -> None:
        self.item = _item()
        self.stages: list[BatchReviewItemStatus] = []
        self.finished: dict[str, object] | None = None
        self.head = DraftState(
            DraftHeadExpectation(11, 12, "draft", 0, 0, datetime.now(UTC)),
            "rules-v1",
            date(2026, 8, 17),
            "business_report",
        )

    def claim_item(self, **kwargs: object) -> ClaimedItem:
        return ClaimedItem(self.item, UUID(int=4), 1, False)

    def load_candidates(
        self, site_id: int, batch_ids: tuple[int, ...], actor_roles: frozenset[str]
    ) -> tuple[CandidateFacts, ...]:
        return (
            CandidateFacts(
                BatchReviewCandidate(
                    7,
                    1,
                    "batch.csv",
                    date(2026, 8, 17),
                    "business_report",
                    "utf-8-sig",
                    "recognized",
                    True,
                    "uploaded",
                    False,
                    actor_roles,
                ),
                BatchReviewTargetState(),
                "00" * 32,
            ),
        )

    def record_item_stage(self, **kwargs: object) -> BatchReviewItemRecord:
        status = cast(BatchReviewItemStatus, kwargs["status"])
        self.stages.append(status)
        self.item = replace(self.item, status=status)
        return self.item

    def load_draft_state(self, **kwargs: object) -> DraftState:
        return self.head

    def finish_item(self, **kwargs: object) -> BatchReviewRunRecord:
        self.finished = dict(kwargs)
        self.item = replace(
            self.item, status=cast(BatchReviewItemStatus, kwargs["status"])
        )
        return BatchReviewRunRecord(
            1, 1, 3, BatchReviewRunStatus.COMPLETED, 1, "v1", (self.item,)
        )


class _Orchestrator:
    def run(self, command: object, *, on_stage: object = None) -> WorkbenchImportResult:
        callback = on_stage
        assert callable(callback)
        callback("parsing", {})
        callback("materializing", {"parse_attempt_id": 20, "parse_baseline_id": 21})
        return WorkbenchImportResult(
            7,
            "workspace_ready",
            "draft",
            date(2026, 8, 17),
            "business_report",
            "utf-8-sig",
            dataset_id=11,
            version_id=12,
            parse_attempt_id=20,
            parse_baseline_id=21,
        )


class _Validation:
    def __init__(self, receipt: ValidationRunReceipt) -> None:
        self.receipt = receipt

    def run_validation(self, command: object) -> ValidationRunReceipt:
        return self.receipt


class _Review:
    def __init__(self) -> None:
        self.calls = 0

    def mark_ready(self, command: object) -> object:
        self.calls += 1
        return SimpleNamespace(status="ready_for_publish")


def test_clean_advance_records_real_stages_and_marks_ready() -> None:
    repository = _AdvanceRepository()
    review = _Review()
    service = BatchReviewService(
        cast(_Repository, repository),
        orchestrator=cast(object, _Orchestrator()),  # type: ignore[arg-type]
        validation=cast(object, _Validation(_receipt())),  # type: ignore[arg-type]
        review=review,
    )

    result = service.advance_item(AdvanceBatchReviewItemCommand(1, 2, 1, 3, uuid4()))

    assert repository.stages == [
        BatchReviewItemStatus.PARSING,
        BatchReviewItemStatus.MATERIALIZING,
        BatchReviewItemStatus.VALIDATING,
    ]
    assert result.status is BatchReviewItemStatus.READY_FOR_PUBLISH
    assert review.calls == 1


def test_passed_validation_with_one_warning_is_not_clean() -> None:
    assert validation_is_clean(_receipt()) is True
    assert validation_is_clean(_receipt(warnings=1)) is False


def test_child_tokens_are_stable_and_stage_specific() -> None:
    parent = uuid4()
    assert child_operation_token(parent, "import") == child_operation_token(
        parent, "import"
    )
    assert child_operation_token(parent, "import") != child_operation_token(
        parent, "validation"
    )


def test_item_response_exposes_only_expired_active_lease_for_recovery() -> None:
    active = _item(BatchReviewItemStatus.VALIDATING)

    assert not _item_response(
        replace(active, lease_expires_at=datetime.now(UTC) + timedelta(minutes=1))
    ).recovery_available
    assert _item_response(
        replace(active, lease_expires_at=datetime.now(UTC) - timedelta(seconds=1))
    ).recovery_available
    assert _item_response(_item(BatchReviewItemStatus.QUEUED)).recovery_available
