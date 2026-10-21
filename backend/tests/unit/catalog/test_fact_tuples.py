from __future__ import annotations

from datetime import UTC, date, datetime

from app.catalog.fact_tuples import (
    BusinessFactProjection,
    PublishedFactMember,
    ReturnFactProjection,
    build_fact_snapshot_tuple,
    build_publication_snapshot,
)
from app.imports.types import ReportType

STARTED_AT = datetime(2026, 8, 21, 1, 2, 3, 456789, tzinfo=UTC)
CUTOFF_AT = datetime(2026, 8, 22, 0, 0, 0, tzinfo=UTC)


def _published_members() -> tuple[PublishedFactMember, ...]:
    return (
        PublishedFactMember(
            report_type="business_report",
            report_date=date(2026, 8, 20),
            dataset_id=10,
            published_version_id=100,
            publication_pointer_revision=4,
            version_data_revision=7,
            active_rows=(
                BusinessFactProjection(
                    source_row_id=1,
                    seller_sku="100-Red-S",
                    parent_asin="PARENT",
                    child_asin="CHILD",
                    title="Observed title",
                    sessions_total=9,
                    units_ordered=2,
                    ordered_product_sales="12.50",
                    currency_code="USD",
                ),
            ),
        ),
        PublishedFactMember(
            report_type="return_report",
            report_date=date(2026, 8, 20),
            dataset_id=11,
            published_version_id=101,
            publication_pointer_revision=5,
            version_data_revision=8,
            active_rows=(
                ReturnFactProjection(
                    source_row_id=2,
                    event_date="2026-08-20T12:00:00.000000Z",
                    seller_sku="100-Red-S",
                    asin="CHILD",
                    fnsku="FNSKU",
                    title="Observed return title",
                    quantity=1,
                ),
            ),
        ),
        PublishedFactMember(
            report_type="business_report",
            report_date=date(2026, 8, 21),
            dataset_id=12,
            published_version_id=102,
            publication_pointer_revision=1,
            version_data_revision=0,
            active_rows=(),
        ),
    )


def test_publication_snapshot_is_deterministic_and_covers_missing_and_zero() -> None:
    missing_pointer_revisions: dict[tuple[date, ReportType], int] = {
        (date(2026, 8, 21), "return_report"): 6,
    }

    first = build_publication_snapshot(
        site_id=1,
        report_source_scope_id=2,
        site_config_version_id=3,
        coverage_start_date=date(2026, 8, 20),
        coverage_end_date=date(2026, 8, 21),
        transaction_started_at=STARTED_AT,
        fact_cutoff_at=CUTOFF_AT,
        return_publication_set_digest=b"r" * 32,
        published_members=_published_members(),
        missing_pointer_revisions=missing_pointer_revisions,
    )
    second = build_publication_snapshot(
        site_id=1,
        report_source_scope_id=2,
        site_config_version_id=3,
        coverage_start_date=date(2026, 8, 20),
        coverage_end_date=date(2026, 8, 21),
        transaction_started_at=STARTED_AT,
        fact_cutoff_at=CUTOFF_AT,
        return_publication_set_digest=b"r" * 32,
        published_members=tuple(reversed(_published_members())),
        missing_pointer_revisions=missing_pointer_revisions,
    )

    assert first == second
    assert len(first.members) == 4
    zero = next(
        member
        for member in first.members
        if member.report_date == date(2026, 8, 21)
        and member.report_type == "business_report"
    )
    missing = next(
        member
        for member in first.members
        if member.report_date == date(2026, 8, 21)
        and member.report_type == "return_report"
    )
    assert (zero.member_status, zero.active_row_count) == ("published", 0)
    assert (missing.member_status, missing.active_row_count) == ("missing", 0)
    assert missing.dataset_id is None
    assert missing.publication_pointer_revision == 6
    assert len(first.snapshot_digest) == 32


def test_active_row_projection_excludes_sensitive_return_fields() -> None:
    projection = _published_members()[1].active_rows[0].digest_payload()

    assert set(projection) == {
        "source_row_id",
        "event_date",
        "seller_sku",
        "asin",
        "fnsku",
        "title",
        "quantity",
    }
    serialized = repr(projection)
    for forbidden in (
        "order_id",
        "fulfillment_center_id",
        "license_plate_number",
        "customer_comments",
    ):
        assert forbidden not in serialized


def test_fact_tuple_freezes_exact_components_and_stays_building() -> None:
    snapshot = build_publication_snapshot(
        site_id=1,
        report_source_scope_id=2,
        site_config_version_id=3,
        coverage_start_date=date(2026, 8, 20),
        coverage_end_date=date(2026, 8, 21),
        transaction_started_at=STARTED_AT,
        fact_cutoff_at=CUTOFF_AT,
        return_publication_set_digest=b"r" * 32,
        published_members=_published_members(),
    )

    first = build_fact_snapshot_tuple(
        publication_snapshot=snapshot,
        return_dedup_snapshot_id=99,
        return_dedup_decision_digest=b"d" * 32,
    )
    replay = build_fact_snapshot_tuple(
        publication_snapshot=snapshot,
        return_dedup_snapshot_id=99,
        return_dedup_decision_digest=b"d" * 32,
    )
    changed = build_fact_snapshot_tuple(
        publication_snapshot=snapshot,
        return_dedup_snapshot_id=100,
        return_dedup_decision_digest=b"d" * 32,
    )

    assert first == replay
    assert first.status == "building"
    assert first.tuple_digest != changed.tuple_digest
    assert len(first.tuple_digest) == 32
