from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from typing import cast
from uuid import UUID

from app.review.service import ReviewRepository, ReviewService
from app.review.types import (
    DraftHeadExpectation,
    ReviewMutationResult,
    SetFieldValueCommand,
)

NOW = datetime(2026, 8, 8, 8, 30, tzinfo=UTC)
TOKEN = UUID("aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa")


class _Repository:
    def __init__(self, result: ReviewMutationResult) -> None:
        self.result = result
        self.calls: list[tuple[SetFieldValueCommand, datetime]] = []

    def set_field_value(
        self,
        command: SetFieldValueCommand,
        *,
        occurred_at: datetime,
    ) -> ReviewMutationResult:
        self.calls.append((command, occurred_at))
        return self.result


def test_service_attaches_one_timestamp_and_delegates_atomic_write() -> None:
    command = SetFieldValueCommand(
        head=DraftHeadExpectation(
            dataset_id=1,
            version_id=2,
            status="draft",
            data_revision=0,
            review_revision=0,
            pointed_at=NOW,
        ),
        row_id=3,
        field_name="ordered_product_sales",
        value=Decimal("2.500000"),
        actor_user_id=4,
        operation_token=TOKEN,
        reason="修正导入错误",
    )
    result = ReviewMutationResult(
        operation_token=TOKEN,
        operation_kind="set_field",
        dataset_id=1,
        version_id=2,
        status="draft",
        data_revision=1,
        review_revision=0,
        affected_row_id=3,
        data_change_event_id=5,
    )
    repository = _Repository(result)
    service = ReviewService(
        repository=cast(ReviewRepository, repository),
        clock=lambda: NOW,
    )

    assert service.set_field_value(command) == result
    assert repository.calls == [(command, NOW)]
