from __future__ import annotations

from pathlib import Path

import pytest
from app.batch_review.repository import validate_candidate_rows
from app.batch_review.types import BatchReviewNotFound


def test_candidate_sql_is_site_scoped_unique_and_uses_exists() -> None:
    source = (
        Path(__file__).resolve().parents[3] / "app" / "batch_review" / "repository.py"
    ).read_text(encoding="utf-8")

    assert "batches.site_id = :site_id" in source
    assert 'bindparam("batch_ids", expanding=True)' in source
    assert "EXISTS(" in source
    assert "LEFT JOIN version_input_batches" not in source


def test_candidate_row_set_must_exactly_match_request() -> None:
    rows = ({"batch_id": 2}, {"batch_id": 5})
    assert validate_candidate_rows((5, 2), rows) == rows

    with pytest.raises(BatchReviewNotFound):
        validate_candidate_rows((2, 5, 8), rows)
    with pytest.raises(ValueError, match="unique"):
        validate_candidate_rows((2, 2), rows)


def test_repository_locks_run_before_items_and_enforces_three_leases() -> None:
    source = (
        Path(__file__).resolve().parents[3] / "app" / "batch_review" / "repository.py"
    ).read_text(encoding="utf-8")

    claim = source[
        source.index("def claim_item") : source.index("def record_item_stage")
    ]
    assert claim.index("FROM batch_review_runs") < claim.index(
        "FROM batch_review_items"
    )
    assert "lease_expires_at > :now" in claim
    assert "active_lease_count >= 3" in claim
    assert "ORDER BY id" in source


def test_audit_payload_is_allowlisted_not_exception_text() -> None:
    source = (
        Path(__file__).resolve().parents[3] / "app" / "batch_review" / "repository.py"
    ).read_text(encoding="utf-8")

    assert "redacted_payload" in source
    assert "traceback" not in source.lower()
    assert "cell_value" not in source
