from __future__ import annotations

from dataclasses import FrozenInstanceError, replace
from datetime import UTC, datetime
from uuid import UUID

import pytest
from app.publications import (
    DraftCommandResult,
    DraftPointerExpectation,
    EligibilityFailure,
    PublicationCommandResult,
    PublicationEligibilityFacts,
    PublicationIneligible,
    PublicationTransition,
    ValidationExpectation,
    publication_ineligibility_reasons,
    require_publication_eligible,
)

TOKEN = UUID("aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa")
NOW = datetime(2026, 8, 8, 5, 6, 7, 890123, tzinfo=UTC)
DRAFT = DraftPointerExpectation(23, "ready_for_publish", 4, 7, NOW)
VALIDATION = ValidationExpectation(
    run_id=31,
    version_id=23,
    data_revision=4,
    ruleset_version="rules-v3",
    data_digest=bytes.fromhex("11" * 32),
)
ELIGIBLE = PublicationEligibilityFacts(
    version_id=23,
    version_status="ready_for_publish",
    data_revision=4,
    review_revision=7,
    ruleset_version="rules-v3",
    validation_run_id=31,
    latest_full_validation_run_id=31,
    validation_run_type="full",
    validation_status="succeeded",
    validation_result="passed",
    validation_data_revision=4,
    validation_ruleset_version="rules-v3",
    validation_data_digest=bytes.fromhex("11" * 32),
    blocking_issue_count=0,
    unacknowledged_warning_count=0,
    missing_required_note_count=0,
    confirmation_matches=True,
)


def test_publish_eligibility_accepts_only_the_exact_reviewed_head() -> None:
    assert publication_ineligibility_reasons(DRAFT, VALIDATION, ELIGIBLE) == ()
    require_publication_eligible(DRAFT, VALIDATION, ELIGIBLE)


@pytest.mark.parametrize(
    ("facts", "failure"),
    [
        (
            replace(ELIGIBLE, version_status="draft"),
            EligibilityFailure.VERSION_NOT_READY,
        ),
        (
            replace(ELIGIBLE, data_revision=5),
            EligibilityFailure.VERSION_CHANGED,
        ),
        (
            replace(ELIGIBLE, review_revision=8),
            EligibilityFailure.REVIEW_CHANGED,
        ),
        (
            replace(ELIGIBLE, validation_run_id=32),
            EligibilityFailure.VALIDATION_CHANGED,
        ),
        (
            replace(ELIGIBLE, latest_full_validation_run_id=32),
            EligibilityFailure.VALIDATION_CHANGED,
        ),
        (
            replace(ELIGIBLE, latest_full_validation_run_id=None),
            EligibilityFailure.VALIDATION_CHANGED,
        ),
        (
            replace(ELIGIBLE, validation_run_type="parse_fidelity"),
            EligibilityFailure.FULL_VALIDATION_REQUIRED,
        ),
        (
            replace(ELIGIBLE, validation_status="failed"),
            EligibilityFailure.VALIDATION_NOT_SUCCESSFUL,
        ),
        (
            replace(ELIGIBLE, validation_result="failed"),
            EligibilityFailure.VALIDATION_NOT_PASSED,
        ),
        (
            replace(ELIGIBLE, validation_data_revision=3),
            EligibilityFailure.VALIDATION_STALE,
        ),
        (
            replace(ELIGIBLE, validation_ruleset_version="rules-v2"),
            EligibilityFailure.RULESET_CHANGED,
        ),
        (
            replace(ELIGIBLE, validation_data_digest=bytes.fromhex("22" * 32)),
            EligibilityFailure.DATA_DIGEST_CHANGED,
        ),
        (
            replace(ELIGIBLE, blocking_issue_count=1),
            EligibilityFailure.BLOCKING_ISSUES,
        ),
        (
            replace(ELIGIBLE, unacknowledged_warning_count=1),
            EligibilityFailure.UNACKNOWLEDGED_WARNINGS,
        ),
        (
            replace(ELIGIBLE, missing_required_note_count=1),
            EligibilityFailure.MISSING_REQUIRED_NOTES,
        ),
        (
            replace(ELIGIBLE, confirmation_matches=False),
            EligibilityFailure.CONFIRMATION_CHANGED,
        ),
    ],
)
def test_publish_eligibility_reports_stable_failure_codes(
    facts: PublicationEligibilityFacts,
    failure: EligibilityFailure,
) -> None:
    failures = publication_ineligibility_reasons(DRAFT, VALIDATION, facts)

    assert failure in failures
    with pytest.raises(PublicationIneligible) as raised:
        require_publication_eligible(DRAFT, VALIDATION, facts)
    assert failure in raised.value.failures


def test_validation_status_accepts_only_terminal_states() -> None:
    with pytest.raises(ValueError, match="validation_status"):
        replace(ELIGIBLE, validation_status="running")  # type: ignore[arg-type]


def _transition(
    sequence_number: int,
    event_type: str,
    dataset_id: int,
    previous_version_id: int | None,
    next_version_id: int | None,
    peer_dataset_id: int | None = None,
) -> PublicationTransition:
    return PublicationTransition(
        event_id=100 + sequence_number,
        sequence_number=sequence_number,
        event_type=event_type,  # type: ignore[arg-type]
        dataset_id=dataset_id,
        peer_dataset_id=peer_dataset_id,
        previous_version_id=previous_version_id,
        next_version_id=next_version_id,
    )


@pytest.mark.parametrize(
    ("command_type", "transitions"),
    [
        ("publish", (_transition(1, "published", 5, None, 17),)),
        ("publish", (_transition(1, "replaced", 5, 13, 17),)),
        ("rollback", (_transition(1, "rolled_back", 5, 17, 13),)),
        (
            "move",
            (
                _transition(1, "moved_out", 5, 17, None, 6),
                _transition(2, "moved_in", 6, 19, 23, 5),
            ),
        ),
        (
            "reverse_move",
            (
                _transition(1, "move_reversed", 5, None, 17, 6),
                _transition(2, "move_reversed", 6, 23, 19, 5),
            ),
        ),
    ],
)
def test_publication_result_accepts_only_command_specific_event_shapes(
    command_type: str,
    transitions: tuple[PublicationTransition, ...],
) -> None:
    result = PublicationCommandResult(
        operation_token=TOKEN,
        command_id=41,
        command_type=command_type,  # type: ignore[arg-type]
        transitions=transitions,
        completed_at=NOW,
    )

    assert result.transitions == transitions
    with pytest.raises(FrozenInstanceError):
        result.command_id = 42  # type: ignore[misc]


@pytest.mark.parametrize(
    ("command_type", "transitions"),
    [
        ("publish", (_transition(1, "published", 5, 13, 17),)),
        ("rollback", (_transition(1, "rolled_back", 5, None, 13),)),
        (
            "move",
            (
                _transition(1, "moved_out", 5, 17, None, 6),
                _transition(2, "moved_in", 6, 19, 23, 7),
            ),
        ),
        (
            "move",
            (
                _transition(1, "moved_out", 5, 17, None, 6),
                _transition(2, "moved_in", 6, 23, 23, 5),
            ),
        ),
        (
            "reverse_move",
            (
                _transition(1, "move_reversed", 5, 17, None, 6),
                _transition(2, "move_reversed", 6, 23, 19, 5),
            ),
        ),
    ],
)
def test_publication_result_rejects_malformed_or_nonreciprocal_events(
    command_type: str,
    transitions: tuple[PublicationTransition, ...],
) -> None:
    with pytest.raises(ValueError, match="event shape"):
        PublicationCommandResult(
            operation_token=TOKEN,
            command_id=41,
            command_type=command_type,  # type: ignore[arg-type]
            transitions=transitions,
            completed_at=NOW,
        )


def test_draft_result_is_an_immutable_snapshot_not_a_live_version_view() -> None:
    result = DraftCommandResult(
        operation_token=TOKEN,
        result_kind="revision_created",
        dataset_id=5,
        version_id=23,
        version_no=4,
        status="draft",
        data_revision=0,
        review_revision=0,
        source_dataset_id=5,
        source_version_id=17,
        completed_at=NOW,
    )

    assert result.data_revision == 0
    with pytest.raises(FrozenInstanceError):
        result.status = "published"  # type: ignore[misc,assignment]
