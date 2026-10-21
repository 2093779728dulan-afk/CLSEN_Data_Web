from __future__ import annotations

from datetime import UTC, date, datetime
from typing import Any
from uuid import UUID

from app.datasets.service import DatasetService
from app.datasets.types import (
    DiscardDraftCommand,
    DraftMutationResult,
    EmptyReassignmentTarget,
    ForceRebuildDraftCommand,
    MaterializeBaselineCommand,
    ReassignUnpublishedDraftDateCommand,
    VersionExpectation,
)

NOW = datetime(2026, 8, 8, 2, 30, tzinfo=UTC)
TOKEN = UUID("aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa")
EXPECTED = VersionExpectation(17, 2, 1)


def _result(*, status: str = "draft") -> DraftMutationResult:
    return DraftMutationResult(
        operation_token=TOKEN,
        dataset_id=5,
        version_id=17,
        version_no=3,
        status=status,  # type: ignore[arg-type]
        data_revision=0,
        review_revision=0,
    )


class RecordingRepository:
    def __init__(self) -> None:
        self.calls: list[tuple[str, object, datetime]] = []

    def materialize_baseline(
        self,
        command: MaterializeBaselineCommand,
        *,
        occurred_at: datetime,
    ) -> DraftMutationResult:
        self.calls.append(("materialize_baseline", command, occurred_at))
        return _result()

    def force_rebuild_draft(
        self,
        command: ForceRebuildDraftCommand,
        *,
        occurred_at: datetime,
    ) -> DraftMutationResult:
        self.calls.append(("force_rebuild_draft", command, occurred_at))
        return _result()

    def discard_active_draft(
        self,
        command: DiscardDraftCommand,
        *,
        occurred_at: datetime,
    ) -> DraftMutationResult:
        self.calls.append(("discard_active_draft", command, occurred_at))
        return _result(status="discarded")

    def reassign_unpublished_draft_date(
        self,
        command: ReassignUnpublishedDraftDateCommand,
        *,
        occurred_at: datetime,
    ) -> DraftMutationResult:
        self.calls.append(("reassign_unpublished_draft_date", command, occurred_at))
        return _result()


def _commands() -> tuple[
    MaterializeBaselineCommand,
    ForceRebuildDraftCommand,
    DiscardDraftCommand,
    ReassignUnpublishedDraftDateCommand,
]:
    materialize = MaterializeBaselineCommand(
        batch_id=7,
        parse_baseline_id=11,
        report_date=date(2026, 8, 6),
        strategy="merge",
        expected_active_draft=EXPECTED,
        expected_publication_version_id=None,
        merge_decisions=(),
        actor_user_id=9,
        operation_token=TOKEN,
        reason="Merge the new baseline",
    )
    force = ForceRebuildDraftCommand(
        batch_id=7,
        parse_baseline_id=11,
        report_date=date(2026, 8, 6),
        expected_active_draft=EXPECTED,
        expected_publication_version_id=None,
        actor_user_id=9,
        operation_token=TOKEN,
        reason="Force a reviewed replacement",
    )
    discard = DiscardDraftCommand(
        dataset_id=5,
        expected_active_draft=EXPECTED,
        actor_user_id=9,
        operation_token=TOKEN,
        reason="Discard an invalid draft",
    )
    reassign = ReassignUnpublishedDraftDateCommand(
        source_dataset_id=5,
        source_draft=EXPECTED,
        target_report_date=date(2026, 8, 7),
        target=EmptyReassignmentTarget(),
        merge_decisions=(),
        actor_user_id=9,
        operation_token=TOKEN,
        reason="Correct the report date",
    )
    return materialize, force, discard, reassign


def test_service_delegates_each_command_with_one_clock_value() -> None:
    repository = RecordingRepository()
    clock_calls: list[None] = []

    def clock() -> datetime:
        clock_calls.append(None)
        return NOW

    service = DatasetService(repository=repository, clock=clock)
    materialize, force, discard, reassign = _commands()

    assert service.materialize_baseline(materialize) == _result()
    assert service.force_rebuild_draft(force) == _result()
    assert service.discard_active_draft(discard) == _result(status="discarded")
    assert service.reassign_unpublished_draft_date(reassign) == _result()

    assert repository.calls == [
        ("materialize_baseline", materialize, NOW),
        ("force_rebuild_draft", force, NOW),
        ("discard_active_draft", discard, NOW),
        ("reassign_unpublished_draft_date", reassign, NOW),
    ]
    assert len(clock_calls) == 4


def test_service_returns_the_exact_repository_result() -> None:
    expected_result = _result()

    class IdentityRepository(RecordingRepository):
        def materialize_baseline(
            self, *_args: Any, **_kwargs: Any
        ) -> DraftMutationResult:
            return expected_result

    service = DatasetService(repository=IdentityRepository(), clock=lambda: NOW)

    assert service.materialize_baseline(_commands()[0]) is expected_result
