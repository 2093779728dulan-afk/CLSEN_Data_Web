from __future__ import annotations

from datetime import date

import pytest
from app.analytics.style_models import (
    CoverageBlock,
    MetricValue,
    PublicationDay,
    PublicationRefs,
)
from pydantic import ValidationError


def test_metric_value_keeps_exact_decimal_strings_and_required_state_metadata() -> None:
    value = MetricValue(
        value="-12.50",
        value_state="observed",
        null_reason=None,
        is_partial=True,
        observed_days=2,
        expected_days=3,
        source_completeness="partial",
        numerator=None,
        denominator=None,
    )

    assert value.model_dump(mode="json") == {
        "value": "-12.50",
        "value_state": "observed",
        "null_reason": None,
        "is_partial": True,
        "observed_days": 2,
        "expected_days": 3,
        "source_completeness": "partial",
        "numerator": None,
        "denominator": None,
    }


def test_metric_value_rejects_inconsistent_null_and_daily_only_reason() -> None:
    with pytest.raises(ValidationError):
        MetricValue(
            value=None,
            value_state="observed",
            null_reason=None,
            is_partial=False,
            observed_days=1,
            expected_days=1,
            source_completeness="complete",
            numerator=None,
            denominator=None,
        )
    with pytest.raises(ValidationError):
        MetricValue(
            value=None,
            value_state="missing_report",
            null_reason="missing_report",
            is_partial=True,
            observed_days=0,
            expected_days=1,
            source_completeness="partial",
            numerator=None,
            denominator=None,
        )


def test_publication_refs_use_binary_ordered_jcs_members_digest() -> None:
    later = PublicationDay(
        report_type="return_report",
        report_date=date(2026, 8, 2),
        report_status="published",
        dataset_id="12",
        published_version_id="21",
        snapshot_member_id=None,
        pointer_revision=3,
    )
    earlier = PublicationDay(
        report_type="business_report",
        report_date=date(2026, 8, 1),
        report_status="missing",
        dataset_id=None,
        published_version_id=None,
        snapshot_member_id=None,
        pointer_revision=0,
    )

    refs = PublicationRefs.build(
        mode="current", snapshot_id=None, members=[later, earlier]
    )

    assert refs.members == [earlier, later]
    assert refs.members_digest_version == "publication_refs_jcs_v1"
    assert refs.members_digest == (
        "sha256:d2bc558c0886c6313947dc0ddc92ba7d38b4cf2cdbcee783cb6652e06cda0fa6"
    )


def test_coverage_block_requires_nullable_business_dedup_fields() -> None:
    block = CoverageBlock(
        report_type="business_report",
        coverage_from=date(2026, 8, 1),
        coverage_to=date(2026, 8, 2),
        expected_days=2,
        published_days=1,
        missing_days=1,
        eligible_rows=2,
        mapped_rows=1,
        unmatched_rows=0,
        excluded_rows=1,
        unique_rows=None,
        confirmed_distinct_rows=None,
        duplicate_of_rows=None,
        unresolved_rows=None,
        report_coverage_rate="0.500000",
        identity_decision_rate="1.000000",
        mapping_rate="0.500000",
        dedup_decision_rate=None,
        identity_status="complete",
        dedup_status="not_applicable",
    )

    assert block.missing_days == 1
    with pytest.raises(ValidationError):
        block.model_copy(update={"duplicate_of_rows": 0}, deep=True).__class__(
            **(block.model_dump() | {"duplicate_of_rows": 0})
        )
