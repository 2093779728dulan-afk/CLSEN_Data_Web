from __future__ import annotations

from app.validation.types import (
    PublicationEligibility,
    StageValidationResult,
    ValidationIssue,
    ValidationRunResult,
    ValidationStage,
)


def _stage(
    stage: ValidationStage,
    *issues: ValidationIssue,
) -> StageValidationResult:
    return StageValidationResult(
        stage=stage,
        data_digest="11" * 32,
        row_count=1,
        totals=(("quantity", "1"),),
        issues=issues,
    )


def test_validation_result_is_publishable_with_warnings_but_not_blockers() -> None:
    warning = ValidationIssue(
        stage="draft_explainability",
        code="draft.warning",
        severity="warning",
        message="review this warning",
        requires_note=False,
    )
    run = ValidationRunResult(
        version_id=10,
        data_revision=4,
        ruleset_version="return_report_v1",
        parse_fidelity=_stage("parse_fidelity"),
        draft_explainability=_stage("draft_explainability", warning),
        data_digest="22" * 32,
    )

    assert run.passed
    assert run.warning_count == 1
    assert run.blocking_count == 0


def test_publication_eligibility_requires_current_revision_rules_and_reviews() -> None:
    run = ValidationRunResult(
        version_id=10,
        data_revision=4,
        ruleset_version="return_report_v1",
        parse_fidelity=_stage("parse_fidelity"),
        draft_explainability=_stage("draft_explainability"),
        data_digest="22" * 32,
    )
    ready = PublicationEligibility(
        validation=run,
        current_data_revision=4,
        current_ruleset_version="return_report_v1",
        unacknowledged_warning_count=0,
        missing_required_note_count=0,
    )
    stale = PublicationEligibility(
        validation=run,
        current_data_revision=5,
        current_ruleset_version="return_report_v1",
        unacknowledged_warning_count=0,
        missing_required_note_count=0,
    )

    assert ready.eligible
    assert ready.reasons == ()
    assert not stale.eligible
    assert stale.reasons == ("stale_data_revision",)
