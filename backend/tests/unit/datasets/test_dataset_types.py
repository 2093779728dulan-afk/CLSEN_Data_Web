from __future__ import annotations

from dataclasses import fields, replace
from datetime import date
from typing import Any
from uuid import UUID

import pytest
from app.datasets.types import (
    ActiveDraftConflict,
    ActiveDraftReassignmentTarget,
    DatasetCommitOutcomeUnknown,
    DatasetError,
    DatasetSiteConflict,
    DiscardDraftCommand,
    DraftCommitOutcomeUnknown,
    DraftMutationResult,
    DraftOperationConflict,
    DraftPointerConflict,
    DraftRevisionConflict,
    DraftSealedConflict,
    EmptyReassignmentTarget,
    ForceRebuildDraftCommand,
    MaterializeBaselineCommand,
    MergeDecision,
    OperationConflict,
    PublishedLineageConflict,
    PublishedLineageMoveRequired,
    PublishedReassignmentTarget,
    ReassignUnpublishedDraftDateCommand,
    RevisionConflict,
    SealedVersionConflict,
    TargetConflict,
    TargetDraftConflict,
    VersionExpectation,
)

TOKEN = UUID("aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa")
OTHER_TOKEN = UUID("bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb")
EXPECTED_DRAFT = VersionExpectation(
    version_id=17,
    data_revision=3,
    review_revision=2,
)
DECISION_ONE = MergeDecision(
    target_row_id=101,
    source_row_id=201,
    action="keep_target",
)
DECISION_TWO = MergeDecision(
    target_row_id=102,
    source_row_id=202,
    action="keep_both",
    reason="Both rows are legitimate orders",
)


def _materialize_command() -> MaterializeBaselineCommand:
    return MaterializeBaselineCommand(
        batch_id=7,
        parse_baseline_id=11,
        report_date=date(2026, 8, 6),
        strategy="merge",
        expected_active_draft=EXPECTED_DRAFT,
        expected_publication_version_id=13,
        merge_decisions=(DECISION_ONE, DECISION_TWO),
        actor_user_id=9,
        operation_token=TOKEN,
        reason="Merge the newly confirmed report",
    )


def _reassign_command() -> ReassignUnpublishedDraftDateCommand:
    return ReassignUnpublishedDraftDateCommand(
        source_dataset_id=5,
        source_draft=EXPECTED_DRAFT,
        target_report_date=date(2026, 8, 7),
        target=PublishedReassignmentTarget(
            expected_dataset_id=6,
            expected_publication_version_id=19,
            strategy="merge",
        ),
        merge_decisions=(DECISION_ONE,),
        actor_user_id=9,
        operation_token=TOKEN,
        reason="The upload belongs to the following report date",
    )


def test_version_expectation_requires_positive_id_and_nonnegative_revisions() -> None:
    with pytest.raises(ValueError, match="version_id must be positive"):
        VersionExpectation(version_id=0, data_revision=0, review_revision=0)
    with pytest.raises(ValueError, match="data_revision must not be negative"):
        VersionExpectation(version_id=1, data_revision=-1, review_revision=0)
    with pytest.raises(ValueError, match="review_revision must not be negative"):
        VersionExpectation(version_id=1, data_revision=0, review_revision=-1)


def test_dataset_site_conflict_is_an_expected_domain_failure() -> None:
    conflict = DatasetSiteConflict(
        "dataset belongs to another site",
        expected_site_id=3,
        actual_site_id=4,
    )

    assert isinstance(conflict, DatasetError)
    assert conflict.expected_site_id == 3
    assert conflict.actual_site_id == 4


def test_review_exception_names_preserve_existing_runtime_contracts() -> None:
    assert DraftPointerConflict is ActiveDraftConflict
    assert DraftRevisionConflict is RevisionConflict
    assert DraftSealedConflict is SealedVersionConflict
    assert PublishedLineageMoveRequired is PublishedLineageConflict
    assert TargetDraftConflict is TargetConflict
    assert DraftOperationConflict is OperationConflict
    assert DraftCommitOutcomeUnknown is DatasetCommitOutcomeUnknown


@pytest.mark.parametrize(
    "command_type",
    [
        MaterializeBaselineCommand,
        ForceRebuildDraftCommand,
        DiscardDraftCommand,
        ReassignUnpublishedDraftDateCommand,
    ],
)
def test_write_commands_never_accept_an_is_admin_field(command_type: type[Any]) -> None:
    assert "is_admin" not in {field.name for field in fields(command_type)}


def test_every_write_command_requires_a_uuid_operation_token() -> None:
    with pytest.raises(ValueError, match="operation_token must be a UUID"):
        replace(_materialize_command(), operation_token=None)  # type: ignore[arg-type]

    force = ForceRebuildDraftCommand(
        batch_id=7,
        parse_baseline_id=11,
        report_date=date(2026, 8, 6),
        expected_active_draft=EXPECTED_DRAFT,
        expected_publication_version_id=13,
        actor_user_id=9,
        operation_token=TOKEN,
        reason="Administrator-approved rebuild",
    )
    with pytest.raises(ValueError, match="operation_token must be a UUID"):
        replace(force, operation_token=None)  # type: ignore[arg-type]

    discard = DiscardDraftCommand(
        dataset_id=5,
        expected_active_draft=EXPECTED_DRAFT,
        actor_user_id=9,
        operation_token=TOKEN,
        reason="Discard an incorrect draft",
    )
    with pytest.raises(ValueError, match="operation_token must be a UUID"):
        replace(discard, operation_token=None)  # type: ignore[arg-type]

    with pytest.raises(ValueError, match="operation_token must be a UUID"):
        replace(_reassign_command(), operation_token=None)  # type: ignore[arg-type]


def test_materialize_digest_is_stable_and_excludes_only_the_token() -> None:
    command = _materialize_command()

    assert len(command.operation_digest) == 32
    assert command.operation_digest == _materialize_command().operation_digest
    assert (
        replace(command, operation_token=OTHER_TOKEN).operation_digest
        == command.operation_digest
    )


def test_materialize_digest_binds_every_business_field_and_decision_content() -> None:
    command = _materialize_command()
    reordered = replace(
        command,
        merge_decisions=(DECISION_TWO, DECISION_ONE),
    )
    variants = (
        replace(command, batch_id=8),
        replace(command, parse_baseline_id=12),
        replace(command, report_date=date(2026, 8, 5)),
        replace(
            command, strategy="replace", expected_active_draft=None, merge_decisions=()
        ),
        replace(
            command,
            expected_active_draft=replace(EXPECTED_DRAFT, version_id=18),
        ),
        replace(
            command,
            expected_active_draft=replace(EXPECTED_DRAFT, data_revision=4),
        ),
        replace(
            command,
            expected_active_draft=replace(EXPECTED_DRAFT, review_revision=3),
        ),
        replace(command, expected_publication_version_id=14),
        replace(
            command,
            merge_decisions=(replace(DECISION_ONE, source_row_id=203), DECISION_TWO),
        ),
        replace(command, actor_user_id=10),
        replace(command, reason="A different reviewed reason"),
    )

    assert all(
        variant.operation_digest != command.operation_digest for variant in variants
    )
    assert reordered.operation_digest == command.operation_digest
    assert reordered.merge_decisions == command.merge_decisions


def test_materialize_replace_cannot_silently_overwrite_an_active_draft() -> None:
    with pytest.raises(ValueError, match="force rebuild"):
        replace(_materialize_command(), strategy="replace", merge_decisions=())

    with pytest.raises(ValueError, match="merge_decisions must be empty"):
        replace(
            _materialize_command(),
            strategy="replace",
            expected_active_draft=None,
        )


def test_force_rebuild_has_a_distinct_digest_and_requires_an_expected_draft() -> None:
    force = ForceRebuildDraftCommand(
        batch_id=7,
        parse_baseline_id=11,
        report_date=date(2026, 8, 6),
        expected_active_draft=EXPECTED_DRAFT,
        expected_publication_version_id=13,
        actor_user_id=9,
        operation_token=TOKEN,
        reason="Administrator-approved rebuild",
    )

    assert force.operation_digest != _materialize_command().operation_digest
    with pytest.raises(ValueError, match="expected_active_draft is required"):
        replace(force, expected_active_draft=None)  # type: ignore[arg-type]


def test_discard_digest_binds_expected_revisions_actor_and_reason() -> None:
    command = DiscardDraftCommand(
        dataset_id=5,
        expected_active_draft=EXPECTED_DRAFT,
        actor_user_id=9,
        operation_token=TOKEN,
        reason="Discard an incorrect draft",
    )

    assert (
        replace(command, operation_token=OTHER_TOKEN).operation_digest
        == command.operation_digest
    )
    assert replace(command, dataset_id=6).operation_digest != command.operation_digest
    assert (
        replace(
            command,
            expected_active_draft=replace(EXPECTED_DRAFT, data_revision=4),
        ).operation_digest
        != command.operation_digest
    )
    assert (
        replace(command, actor_user_id=10).operation_digest != command.operation_digest
    )
    assert (
        replace(command, reason="Another reason").operation_digest
        != command.operation_digest
    )


def test_reassignment_targets_are_mutually_explicit() -> None:
    empty = EmptyReassignmentTarget()
    published_merge = PublishedReassignmentTarget(
        expected_dataset_id=6,
        expected_publication_version_id=19,
        strategy="merge",
    )
    published_replace = replace(published_merge, strategy="replace")
    active_merge = ActiveDraftReassignmentTarget(
        expected_dataset_id=6,
        expected_active_draft=VersionExpectation(20, 2, 1),
        expected_publication_version_id=19,
        action="merge",
    )
    active_cancel = replace(active_merge, action="cancel")

    assert empty.expected_dataset_id is None
    assert {published_merge.strategy, published_replace.strategy} == {
        "merge",
        "replace",
    }
    assert {active_merge.action, active_cancel.action} == {"merge", "cancel"}

    with pytest.raises(ValueError, match="strategy is not supported"):
        replace(published_merge, strategy="cancel")  # type: ignore[arg-type]
    with pytest.raises(ValueError, match="action is not supported"):
        replace(active_merge, action="replace")  # type: ignore[arg-type]
    with pytest.raises(ValueError, match="empty target cannot have a dataset"):
        EmptyReassignmentTarget(expected_dataset_id=6)  # type: ignore[arg-type]


def test_reassignment_never_silently_changes_a_previewed_target_shape() -> None:
    command = _reassign_command()
    variants = (
        replace(command, source_dataset_id=8),
        replace(command, source_draft=replace(EXPECTED_DRAFT, data_revision=4)),
        replace(command, target_report_date=date(2026, 8, 8)),
        replace(
            command,
            target=EmptyReassignmentTarget(),
            merge_decisions=(),
        ),
        replace(
            command,
            target=PublishedReassignmentTarget(
                expected_dataset_id=6,
                expected_publication_version_id=19,
                strategy="replace",
            ),
            merge_decisions=(),
        ),
        replace(
            command,
            target=ActiveDraftReassignmentTarget(
                expected_dataset_id=6,
                expected_active_draft=VersionExpectation(20, 2, 1),
                expected_publication_version_id=19,
                action="merge",
            ),
        ),
        replace(
            command, merge_decisions=(replace(DECISION_ONE, action="keep_source"),)
        ),
        replace(command, actor_user_id=10),
        replace(command, reason="A different date correction"),
    )

    assert (
        replace(command, operation_token=OTHER_TOKEN).operation_digest
        == command.operation_digest
    )
    assert all(
        variant.operation_digest != command.operation_digest for variant in variants
    )


def test_reassignment_canonicalises_merge_decisions_before_digesting() -> None:
    command = replace(
        _reassign_command(),
        merge_decisions=(DECISION_TWO, DECISION_ONE),
    )
    reordered = replace(
        command,
        merge_decisions=(DECISION_ONE, DECISION_TWO),
    )

    assert command.merge_decisions == (DECISION_ONE, DECISION_TWO)
    assert reordered.merge_decisions == command.merge_decisions
    assert reordered.operation_digest == command.operation_digest


def test_reassignment_rejects_decisions_for_nonmerge_target_choices() -> None:
    command = _reassign_command()

    with pytest.raises(ValueError, match="merge_decisions must be empty"):
        replace(command, target=EmptyReassignmentTarget())
    with pytest.raises(ValueError, match="merge_decisions must be empty"):
        replace(
            command,
            target=PublishedReassignmentTarget(
                expected_dataset_id=6,
                expected_publication_version_id=19,
                strategy="replace",
            ),
        )
    with pytest.raises(ValueError, match="merge_decisions must be empty"):
        replace(
            command,
            target=ActiveDraftReassignmentTarget(
                expected_dataset_id=6,
                expected_active_draft=VersionExpectation(20, 2, 1),
                expected_publication_version_id=19,
                action="cancel",
            ),
        )


def test_command_reasons_are_required_and_normalised() -> None:
    with pytest.raises(ValueError, match="reason must not be blank"):
        replace(_materialize_command(), reason="  ")

    command = replace(_materialize_command(), reason="  reviewed reason  ")

    assert command.reason == "reviewed reason"


def test_draft_mutation_result_validates_recovery_identity() -> None:
    result = DraftMutationResult(
        operation_token=TOKEN,
        dataset_id=5,
        version_id=17,
        version_no=3,
        status="draft",
        data_revision=0,
        review_revision=0,
        superseded_version_ids=(11, 13),
        source_dataset_id=4,
        source_version_id=9,
    )

    assert result.superseded_version_ids == (11, 13)
    with pytest.raises(ValueError, match="source dataset and version"):
        replace(result, source_version_id=None)
    with pytest.raises(ValueError, match="superseded_version_ids must be unique"):
        replace(result, superseded_version_ids=(11, 11))
    with pytest.raises(ValueError, match="at most two"):
        replace(result, superseded_version_ids=(11, 13, 15))


def test_cancelled_result_cannot_imply_a_lineage_change() -> None:
    cancelled = DraftMutationResult(
        operation_token=TOKEN,
        dataset_id=5,
        version_id=17,
        version_no=3,
        status="cancelled",
        data_revision=3,
        review_revision=2,
    )

    assert cancelled.source_dataset_id is None
    assert cancelled.source_version_id is None
    assert cancelled.superseded_version_ids == ()
    with pytest.raises(ValueError, match="cancelled result cannot supersede"):
        replace(cancelled, superseded_version_ids=(17,))
    with pytest.raises(ValueError, match="cancelled result cannot have source"):
        replace(cancelled, source_dataset_id=5, source_version_id=17)
