from __future__ import annotations

from uuid import UUID, uuid4

import pytest
from app.batch_review.types import (
    AdvanceBatchReviewItemCommand,
    BatchReviewItemStatus,
    BatchReviewRunStatus,
    BatchReviewStateConflict,
    ChangeBatchReviewRunStateCommand,
    ConfirmBatchReviewCommand,
    CreatePreflightCommand,
    RetryBatchReviewItemCommand,
    aggregate_run_status,
    ensure_item_transition,
    ensure_run_transition,
)


def test_commands_require_positive_ids_uuid_v4_and_unique_lists() -> None:
    token = uuid4()
    command = CreatePreflightCommand(
        site_id=1,
        actor_user_id=2,
        actor_roles=frozenset({"admin"}),
        batch_ids=(9, 3),
        operation_token=token,
    )
    assert command.batch_ids == (3, 9)

    with pytest.raises(ValueError, match="unique"):
        CreatePreflightCommand(1, 2, frozenset({"admin"}), (3, 3), token)
    with pytest.raises(ValueError, match="positive"):
        CreatePreflightCommand(0, 2, frozenset({"admin"}), (3,), token)
    with pytest.raises(ValueError, match="UUID v4"):
        CreatePreflightCommand(
            1,
            2,
            frozenset({"admin"}),
            (3,),
            UUID("00000000-0000-0000-0000-000000000000"),
        )


def test_confirmation_requires_statement_acceptance_version_and_items() -> None:
    with pytest.raises(ValueError, match="accepted"):
        ConfirmBatchReviewCommand(
            run_id=1,
            site_id=1,
            actor_user_id=2,
            expected_revision=0,
            selected_item_ids=(5,),
            confirmation_accepted=False,
            confirmation_statement_version="v1",
            operation_token=uuid4(),
        )
    with pytest.raises(ValueError, match="statement"):
        ConfirmBatchReviewCommand(1, 1, 2, 0, (5,), True, " ", uuid4())
    with pytest.raises(ValueError, match="selected_item_ids"):
        ConfirmBatchReviewCommand(1, 1, 2, 0, (), True, "v1", uuid4())


def test_command_digest_is_canonical_and_excludes_time() -> None:
    token = uuid4()
    first = CreatePreflightCommand(1, 2, frozenset({"admin"}), (8, 3), token)
    second = CreatePreflightCommand(1, 2, frozenset({"admin"}), (3, 8), token)

    assert first.operation_digest == second.operation_digest
    assert len(first.operation_digest) == 32


def test_all_command_contracts_validate_their_identity() -> None:
    token = uuid4()
    advance = AdvanceBatchReviewItemCommand(1, 2, 3, 4, token)
    change = ChangeBatchReviewRunStateCommand(1, 3, 4, 7, "pause", token)
    retry = RetryBatchReviewItemCommand(1, 2, 3, 4, 7, token)

    assert len(advance.operation_digest) == 32
    assert len(change.operation_digest) == 32
    assert len(retry.operation_digest) == 32


@pytest.mark.parametrize(
    ("current", "target"),
    [
        ("preview", "confirmed"),
        ("confirmed", "running"),
        ("running", "paused"),
        ("paused", "running"),
        ("running", "completed"),
        ("running", "completed_with_exceptions"),
    ],
)
def test_run_state_machine_allows_only_forward_or_pause_transitions(
    current: str,
    target: str,
) -> None:
    assert ensure_run_transition(
        BatchReviewRunStatus(current), BatchReviewRunStatus(target)
    ) == BatchReviewRunStatus(target)


def test_terminal_run_cannot_reopen() -> None:
    with pytest.raises(BatchReviewStateConflict):
        ensure_run_transition(
            BatchReviewRunStatus.COMPLETED, BatchReviewRunStatus.RUNNING
        )


def test_item_state_machine_and_retry_boundary() -> None:
    assert (
        ensure_item_transition(
            BatchReviewItemStatus.QUEUED, BatchReviewItemStatus.PARSING
        )
        == BatchReviewItemStatus.PARSING
    )
    assert (
        ensure_item_transition(
            BatchReviewItemStatus.PARSING, BatchReviewItemStatus.MATERIALIZING
        )
        == BatchReviewItemStatus.MATERIALIZING
    )
    assert (
        ensure_item_transition(
            BatchReviewItemStatus.MATERIALIZING, BatchReviewItemStatus.VALIDATING
        )
        == BatchReviewItemStatus.VALIDATING
    )
    assert (
        ensure_item_transition(
            BatchReviewItemStatus.VALIDATING, BatchReviewItemStatus.READY_FOR_PUBLISH
        )
        == BatchReviewItemStatus.READY_FOR_PUBLISH
    )
    assert (
        ensure_item_transition(
            BatchReviewItemStatus.FAILED,
            BatchReviewItemStatus.QUEUED,
            retry_allowed=True,
        )
        == BatchReviewItemStatus.QUEUED
    )
    with pytest.raises(BatchReviewStateConflict):
        ensure_item_transition(
            BatchReviewItemStatus.FAILED, BatchReviewItemStatus.QUEUED
        )


def test_run_aggregation_handles_empty_and_exception_sets() -> None:
    assert aggregate_run_status(()) == BatchReviewRunStatus.COMPLETED_WITH_EXCEPTIONS
    assert (
        aggregate_run_status((BatchReviewItemStatus.READY_FOR_PUBLISH,))
        == BatchReviewRunStatus.COMPLETED
    )
    assert (
        aggregate_run_status(
            (BatchReviewItemStatus.SKIPPED, BatchReviewItemStatus.READY_FOR_PUBLISH)
        )
        == BatchReviewRunStatus.COMPLETED
    )
    assert (
        aggregate_run_status((BatchReviewItemStatus.MANUAL_REVIEW,))
        == BatchReviewRunStatus.COMPLETED_WITH_EXCEPTIONS
    )
    assert (
        aggregate_run_status((BatchReviewItemStatus.QUEUED,))
        == BatchReviewRunStatus.RUNNING
    )
