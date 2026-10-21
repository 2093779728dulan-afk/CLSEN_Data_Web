from __future__ import annotations

from datetime import date

import pytest
from app.batch_review.eligibility import evaluate_candidate
from app.batch_review.types import (
    BatchReviewCandidate,
    BatchReviewReasonCode,
    BatchReviewTargetState,
    TargetKey,
)


def _candidate(**overrides: object) -> BatchReviewCandidate:
    values: dict[str, object] = {
        "batch_id": 7,
        "site_id": 1,
        "filename": "business.csv",
        "report_date": date(2026, 8, 17),
        "report_type": "business_report",
        "encoding": "utf-8-sig",
        "recognition_status": "recognized",
        "source_available": True,
        "batch_status": "uploaded",
        "already_materialized": False,
        "actor_roles": frozenset({"data_manager"}),
    }
    values.update(overrides)
    return BatchReviewCandidate(**values)  # type: ignore[arg-type]


@pytest.mark.parametrize(
    ("candidate_overrides", "target", "seen", "reason"),
    [
        ({"recognition_status": "uncertain"}, None, set(), "recognition_uncertain"),
        ({"source_available": False}, None, set(), "source_unavailable"),
        ({"batch_status": "processing"}, None, set(), "batch_state_conflict"),
        ({}, None, {(date(2026, 8, 17), "business_report")}, "duplicate_target_in_run"),
        (
            {},
            BatchReviewTargetState(active_draft_exists=True),
            set(),
            "active_draft_exists",
        ),
        (
            {},
            BatchReviewTargetState(publication_exists=True),
            set(),
            "publication_exists",
        ),
        ({"already_materialized": True}, None, set(), "already_materialized"),
        ({"actor_roles": frozenset({"viewer"})}, None, set(), "permission_denied"),
    ],
)
def test_all_stable_ineligibility_reasons_are_safe(
    candidate_overrides: dict[str, object],
    target: BatchReviewTargetState | None,
    seen: set[TargetKey],
    reason: str,
) -> None:
    decision = evaluate_candidate(
        _candidate(**candidate_overrides),
        target or BatchReviewTargetState(),
        seen,
    )

    assert decision.eligible is False
    assert decision.reason_code == BatchReviewReasonCode(reason)
    assert decision.reason_message
    assert (
        decision.manual_review_url == "/review/2026-08-17?report_type=business_report"
    )
    unsafe = ("SELECT ", "Traceback", "cell=", "原始单元格")
    assert not any(value in decision.reason_message for value in unsafe)


def test_candidate_is_eligible_only_when_every_rule_passes() -> None:
    decision = evaluate_candidate(_candidate(), BatchReviewTargetState(), set())

    assert decision.eligible is True
    assert decision.reason_code is None
    assert decision.reason_message == "可安全推进至待发布。"
    assert decision.target_key == (date(2026, 8, 17), "business_report")


def test_unsupported_encoding_is_rejected_at_the_domain_boundary() -> None:
    with pytest.raises(ValueError, match="unsupported encoding"):
        _candidate(encoding="utf-16")


def test_duplicate_target_resolution_is_independent_of_browser_order() -> None:
    candidates = (
        _candidate(batch_id=9),
        _candidate(batch_id=3),
        _candidate(batch_id=6),
    )
    seen: set[TargetKey] = set()
    decisions = []
    for candidate in sorted(candidates, key=lambda item: item.batch_id):
        decision = evaluate_candidate(candidate, BatchReviewTargetState(), seen)
        decisions.append((candidate.batch_id, decision.eligible))
        if decision.eligible and decision.target_key is not None:
            seen.add(decision.target_key)

    assert decisions == [(3, True), (6, False), (9, False)]
