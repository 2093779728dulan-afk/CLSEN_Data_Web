"""Pure publication eligibility checks over facts loaded by an adapter."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import Literal

from ._common import (
    nonnegative,
    optional_positive,
    positive,
    require_nonblank,
    require_sha256,
)
from .commands import DraftPointerExpectation, ValidationExpectation

type VersionStatus = Literal["draft", "ready_for_publish", "published", "discarded"]
type ValidationRunType = Literal["parse_fidelity", "draft_explainability", "full"]
type ValidationStatus = Literal["succeeded", "failed"]
type ValidationResult = Literal["passed", "failed", "error"] | None


class EligibilityFailure(StrEnum):
    VERSION_NOT_READY = "version_not_ready"
    VERSION_CHANGED = "version_changed"
    REVIEW_CHANGED = "review_changed"
    VALIDATION_CHANGED = "validation_changed"
    FULL_VALIDATION_REQUIRED = "full_validation_required"
    VALIDATION_NOT_SUCCESSFUL = "validation_not_successful"
    VALIDATION_NOT_PASSED = "validation_not_passed"
    VALIDATION_STALE = "validation_stale"
    RULESET_CHANGED = "ruleset_changed"
    DATA_DIGEST_CHANGED = "data_digest_changed"
    BLOCKING_ISSUES = "blocking_issues"
    UNACKNOWLEDGED_WARNINGS = "unacknowledged_warnings"
    MISSING_REQUIRED_NOTES = "missing_required_notes"
    CONFIRMATION_CHANGED = "confirmation_changed"


class PublicationIneligible(RuntimeError):
    def __init__(self, failures: tuple[EligibilityFailure, ...]) -> None:
        if not failures:
            raise ValueError("publication failure list must not be empty")
        self.failures = failures
        super().__init__(
            "publication is ineligible: "
            + ", ".join(failure.value for failure in failures)
        )


@dataclass(frozen=True, slots=True)
class PublicationEligibilityFacts:
    version_id: int
    version_status: VersionStatus
    data_revision: int
    review_revision: int
    ruleset_version: str
    validation_run_id: int
    latest_full_validation_run_id: int | None
    validation_run_type: ValidationRunType
    validation_status: ValidationStatus
    validation_result: ValidationResult
    validation_data_revision: int
    validation_ruleset_version: str
    validation_data_digest: bytes
    blocking_issue_count: int
    unacknowledged_warning_count: int
    missing_required_note_count: int
    confirmation_matches: bool

    def __post_init__(self) -> None:
        positive(self.version_id, "version_id")
        nonnegative(self.data_revision, "data_revision")
        nonnegative(self.review_revision, "review_revision")
        object.__setattr__(
            self,
            "ruleset_version",
            require_nonblank(self.ruleset_version, "ruleset_version"),
        )
        positive(self.validation_run_id, "validation_run_id")
        optional_positive(
            self.latest_full_validation_run_id,
            "latest_full_validation_run_id",
        )
        if self.validation_status not in {"succeeded", "failed"}:
            raise ValueError("validation_status must be succeeded or failed")
        nonnegative(self.validation_data_revision, "validation_data_revision")
        object.__setattr__(
            self,
            "validation_ruleset_version",
            require_nonblank(
                self.validation_ruleset_version,
                "validation_ruleset_version",
            ),
        )
        require_sha256(self.validation_data_digest, "validation_data_digest")
        nonnegative(self.blocking_issue_count, "blocking_issue_count")
        nonnegative(
            self.unacknowledged_warning_count,
            "unacknowledged_warning_count",
        )
        nonnegative(
            self.missing_required_note_count,
            "missing_required_note_count",
        )
        if not isinstance(self.confirmation_matches, bool):
            raise ValueError("confirmation_matches must be a bool")


def publication_ineligibility_reasons(
    draft: DraftPointerExpectation,
    validation: ValidationExpectation,
    facts: PublicationEligibilityFacts,
) -> tuple[EligibilityFailure, ...]:
    failures: list[EligibilityFailure] = []

    def add(failure: EligibilityFailure) -> None:
        if failure not in failures:
            failures.append(failure)

    if facts.version_status != "ready_for_publish":
        add(EligibilityFailure.VERSION_NOT_READY)
    if (
        facts.version_id != draft.version_id
        or facts.data_revision != draft.data_revision
    ):
        add(EligibilityFailure.VERSION_CHANGED)
    if facts.review_revision != draft.review_revision:
        add(EligibilityFailure.REVIEW_CHANGED)
    if (
        facts.validation_run_id != validation.run_id
        or facts.latest_full_validation_run_id != facts.validation_run_id
        or validation.version_id != draft.version_id
    ):
        add(EligibilityFailure.VALIDATION_CHANGED)
    if facts.validation_run_type != "full":
        add(EligibilityFailure.FULL_VALIDATION_REQUIRED)
    if facts.validation_status != "succeeded":
        add(EligibilityFailure.VALIDATION_NOT_SUCCESSFUL)
    if facts.validation_result != "passed":
        add(EligibilityFailure.VALIDATION_NOT_PASSED)
    if (
        facts.validation_data_revision != validation.data_revision
        or facts.validation_data_revision != facts.data_revision
    ):
        add(EligibilityFailure.VALIDATION_STALE)
    if (
        facts.ruleset_version != validation.ruleset_version
        or facts.validation_ruleset_version != validation.ruleset_version
    ):
        add(EligibilityFailure.RULESET_CHANGED)
    if facts.validation_data_digest != validation.data_digest:
        add(EligibilityFailure.DATA_DIGEST_CHANGED)
    if facts.blocking_issue_count:
        add(EligibilityFailure.BLOCKING_ISSUES)
    if facts.unacknowledged_warning_count:
        add(EligibilityFailure.UNACKNOWLEDGED_WARNINGS)
    if facts.missing_required_note_count:
        add(EligibilityFailure.MISSING_REQUIRED_NOTES)
    if not facts.confirmation_matches:
        add(EligibilityFailure.CONFIRMATION_CHANGED)
    return tuple(failures)


def require_publication_eligible(
    draft: DraftPointerExpectation,
    validation: ValidationExpectation,
    facts: PublicationEligibilityFacts,
) -> None:
    failures = publication_ineligibility_reasons(draft, validation, facts)
    if failures:
        raise PublicationIneligible(failures)
