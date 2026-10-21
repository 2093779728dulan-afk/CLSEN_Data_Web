from __future__ import annotations

from datetime import UTC, datetime
from typing import cast
from uuid import UUID

from app.validation.service import ValidationRepository, ValidationService
from app.validation.types import (
    RunValidationCommand,
    ValidationRunReceipt,
    ValidationSummary,
    ValidationSummaryStage,
)

NOW = datetime(2026, 8, 8, 9, 30, tzinfo=UTC)
TOKEN = UUID("aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa")


def _summary() -> ValidationSummary:
    stage = ValidationSummaryStage(
        data_digest="11" * 32,
        row_count=1,
        totals=(("quantity", "2"),),
        warning_count=0,
        blocking_count=0,
    )
    return ValidationSummary(
        report_date=NOW.date(),
        report_type="return_report",
        row_count=1,
        totals=(("quantity", "2"),),
        parse_fidelity=stage,
        draft_explainability=stage,
    )


def _receipt() -> ValidationRunReceipt:
    return ValidationRunReceipt(
        operation_token=TOKEN,
        validation_run_id=31,
        dataset_id=5,
        version_id=23,
        version_status="draft",
        data_revision=4,
        review_revision=7,
        ruleset_version="return_report_v1",
        status="succeeded",
        result="passed",
        data_digest=bytes.fromhex("22" * 32),
        summary=_summary(),
        completed_at=NOW,
    )


class _Repository:
    def __init__(self) -> None:
        self.calls: list[tuple[RunValidationCommand, datetime]] = []

    def run_validation(
        self,
        command: RunValidationCommand,
        *,
        occurred_at: datetime,
    ) -> ValidationRunReceipt:
        self.calls.append((command, occurred_at))
        return _receipt()


def test_validation_service_attaches_one_clock_value() -> None:
    repository = _Repository()
    service = ValidationService(
        repository=cast(ValidationRepository, repository),
        clock=lambda: NOW,
    )
    command = RunValidationCommand(
        dataset_id=5,
        version_id=23,
        data_revision=4,
        ruleset_version="return_report_v1",
        actor_user_id=9,
        operation_token=TOKEN,
    )

    assert service.run_validation(command) == _receipt()
    assert repository.calls == [(command, NOW)]
