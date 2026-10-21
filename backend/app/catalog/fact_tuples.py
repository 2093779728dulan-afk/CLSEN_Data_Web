"""Deterministic publication-snapshot and fact-tuple payloads.

The types in this module intentionally expose only the P0 identity and metric
projection. Sensitive return-report columns cannot be supplied to the digest
builder because they are absent from the closed projection model.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, field, replace
from datetime import UTC, date, datetime, timedelta
from typing import Final, Literal

from app.catalog.canonical_json import CanonicalValue, canonical_json_bytes

type ReportType = Literal["business_report", "return_report"]
type MemberStatus = Literal["published", "missing"]

CANDIDATE_RULE_VERSION: Final = "seller_sku_three_segment_v1"
NORMALIZATION_MANIFEST_ID: Final = "product_catalog_normalization_manifest_v1"
_REPORT_TYPES: Final[tuple[ReportType, ...]] = (
    "business_report",
    "return_report",
)


def _positive(value: int, label: str) -> None:
    if isinstance(value, bool) or not isinstance(value, int) or value < 1:
        raise ValueError(f"{label} must be positive")


def _nonnegative(value: int, label: str) -> None:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise ValueError(f"{label} must be nonnegative")


def _digest(value: bytes, label: str) -> bytes:
    if not isinstance(value, bytes) or len(value) != 32:
        raise ValueError(f"{label} must be 32 bytes")
    return value


def _timestamp(value: datetime) -> str:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("fact timestamps must be timezone-aware")
    return value.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%S.%fZ")


@dataclass(frozen=True, slots=True)
class BusinessFactProjection:
    source_row_id: int
    seller_sku: str | None = field(repr=False)
    parent_asin: str | None = field(default=None, repr=False)
    child_asin: str | None = field(default=None, repr=False)
    title: str | None = field(default=None, repr=False)
    sessions_total: int | None = None
    sessions_b2b: int | None = None
    conversion_rate_total: str | None = None
    session_percentage_b2b: str | None = None
    page_views_total: int | None = None
    page_views_b2b: int | None = None
    page_view_percentage_total: str | None = None
    page_view_percentage_b2b: str | None = None
    featured_offer_percentage: str | None = None
    featured_offer_percentage_b2b: str | None = None
    units_ordered: int | None = None
    units_ordered_b2b: int | None = None
    unit_session_percentage: str | None = None
    unit_session_percentage_b2b: str | None = None
    ordered_product_sales: str | None = None
    ordered_product_sales_b2b: str | None = None
    currency_code: str | None = None
    total_order_items: int | None = None
    total_order_items_b2b: int | None = None

    def __post_init__(self) -> None:
        _positive(self.source_row_id, "source_row_id")

    def digest_payload(self) -> dict[str, CanonicalValue]:
        return {
            "source_row_id": self.source_row_id,
            "seller_sku": self.seller_sku,
            "parent_asin": self.parent_asin,
            "child_asin": self.child_asin,
            "title": self.title,
            "sessions_total": self.sessions_total,
            "sessions_b2b": self.sessions_b2b,
            "conversion_rate_total": self.conversion_rate_total,
            "session_percentage_b2b": self.session_percentage_b2b,
            "page_views_total": self.page_views_total,
            "page_views_b2b": self.page_views_b2b,
            "page_view_percentage_total": self.page_view_percentage_total,
            "page_view_percentage_b2b": self.page_view_percentage_b2b,
            "featured_offer_percentage": self.featured_offer_percentage,
            "featured_offer_percentage_b2b": self.featured_offer_percentage_b2b,
            "units_ordered": self.units_ordered,
            "units_ordered_b2b": self.units_ordered_b2b,
            "unit_session_percentage": self.unit_session_percentage,
            "unit_session_percentage_b2b": self.unit_session_percentage_b2b,
            "ordered_product_sales": self.ordered_product_sales,
            "ordered_product_sales_b2b": self.ordered_product_sales_b2b,
            "currency_code": self.currency_code,
            "total_order_items": self.total_order_items,
            "total_order_items_b2b": self.total_order_items_b2b,
        }


@dataclass(frozen=True, slots=True)
class ReturnFactProjection:
    source_row_id: int
    event_date: str | None
    seller_sku: str | None = field(repr=False)
    asin: str | None = field(default=None, repr=False)
    fnsku: str | None = field(default=None, repr=False)
    title: str | None = field(default=None, repr=False)
    quantity: int | None = None

    def __post_init__(self) -> None:
        _positive(self.source_row_id, "source_row_id")

    def digest_payload(self) -> dict[str, CanonicalValue]:
        return {
            "source_row_id": self.source_row_id,
            "event_date": self.event_date,
            "seller_sku": self.seller_sku,
            "asin": self.asin,
            "fnsku": self.fnsku,
            "title": self.title,
            "quantity": self.quantity,
        }


type FactProjection = BusinessFactProjection | ReturnFactProjection


@dataclass(frozen=True, slots=True)
class PublishedFactMember:
    report_type: ReportType
    report_date: date
    dataset_id: int
    published_version_id: int
    publication_pointer_revision: int
    version_data_revision: int
    active_rows: tuple[FactProjection, ...]

    def __post_init__(self) -> None:
        if self.report_type not in _REPORT_TYPES:
            raise ValueError("unsupported report type")
        if not isinstance(self.report_date, date):
            raise ValueError("report_date must be a date")
        _positive(self.dataset_id, "dataset_id")
        _positive(self.published_version_id, "published_version_id")
        _nonnegative(self.publication_pointer_revision, "publication revision")
        _nonnegative(self.version_data_revision, "version data revision")
        expected = (
            BusinessFactProjection
            if self.report_type == "business_report"
            else ReturnFactProjection
        )
        if any(not isinstance(row, expected) for row in self.active_rows):
            raise ValueError("active projection does not match report type")
        row_ids = [row.source_row_id for row in self.active_rows]
        if len(row_ids) != len(set(row_ids)):
            raise ValueError("active projection contains duplicate source rows")


@dataclass(frozen=True, slots=True)
class PublicationSnapshotMemberPayload:
    report_type: ReportType
    report_date: date
    dataset_id: int | None
    published_version_id: int | None
    publication_pointer_revision: int
    version_data_revision: int | None
    member_status: MemberStatus
    active_row_count: int
    active_row_projection_digest: bytes

    def digest_payload(self) -> list[CanonicalValue]:
        return [
            self.report_date.isoformat(),
            self.report_type,
            self.member_status,
            self.dataset_id,
            self.published_version_id,
            self.publication_pointer_revision,
            self.version_data_revision,
            self.active_row_count,
            self.active_row_projection_digest.hex(),
        ]


@dataclass(frozen=True, slots=True)
class PublicationSnapshotPayload:
    site_id: int
    report_source_scope_id: int
    site_config_version_id: int
    candidate_rule_version: str
    normalization_manifest_id: str
    coverage_start_date: date
    coverage_end_date: date
    transaction_started_at: datetime
    fact_cutoff_at: datetime
    return_publication_set_digest: bytes
    members: tuple[PublicationSnapshotMemberPayload, ...]
    snapshot_digest: bytes
    status: Literal["building"] = "building"

    def identity_payload(self) -> dict[str, CanonicalValue]:
        return {
            "site_id": self.site_id,
            "report_source_scope_id": self.report_source_scope_id,
            "site_config_version_id": self.site_config_version_id,
            "candidate_rule_version": self.candidate_rule_version,
            "normalization_manifest_id": self.normalization_manifest_id,
            "coverage_start_date": self.coverage_start_date.isoformat(),
            "coverage_end_date": self.coverage_end_date.isoformat(),
            "transaction_started_at": _timestamp(self.transaction_started_at),
            "fact_cutoff_at": _timestamp(self.fact_cutoff_at),
            "return_publication_set_digest": (self.return_publication_set_digest.hex()),
            "members": [member.digest_payload() for member in self.members],
        }


@dataclass(frozen=True, slots=True)
class FactSnapshotTuplePayload:
    site_id: int
    report_source_scope_id: int
    site_config_version_id: int
    fact_cutoff_at: datetime
    publication_snapshot_digest: bytes
    return_dedup_snapshot_id: int
    return_publication_set_digest: bytes
    return_dedup_decision_digest: bytes
    tuple_digest: bytes
    status: Literal["building"] = "building"


def _projection_digest(member: PublishedFactMember) -> bytes:
    rows = sorted(member.active_rows, key=lambda row: row.source_row_id)
    return hashlib.sha256(
        canonical_json_bytes([row.digest_payload() for row in rows])
    ).digest()


def build_publication_snapshot(
    *,
    site_id: int,
    report_source_scope_id: int,
    site_config_version_id: int,
    coverage_start_date: date,
    coverage_end_date: date,
    transaction_started_at: datetime,
    fact_cutoff_at: datetime,
    return_publication_set_digest: bytes,
    published_members: tuple[PublishedFactMember, ...],
    missing_pointer_revisions: dict[tuple[date, ReportType], int] | None = None,
    candidate_rule_version: str = CANDIDATE_RULE_VERSION,
    normalization_manifest_id: str = NORMALIZATION_MANIFEST_ID,
) -> PublicationSnapshotPayload:
    """Build every day x report member, including explicit missing members."""

    for label, value in (
        ("site_id", site_id),
        ("report_source_scope_id", report_source_scope_id),
        ("site_config_version_id", site_config_version_id),
    ):
        _positive(value, label)
    if coverage_start_date > coverage_end_date:
        raise ValueError("snapshot coverage is inverted")
    if fact_cutoff_at < transaction_started_at:
        raise ValueError("fact cutoff precedes the transaction")
    _timestamp(transaction_started_at)
    _timestamp(fact_cutoff_at)
    return_digest = _digest(
        return_publication_set_digest, "return publication set digest"
    )
    sources: dict[tuple[date, ReportType], PublishedFactMember] = {}
    for member in published_members:
        key = (member.report_date, member.report_type)
        if not coverage_start_date <= member.report_date <= coverage_end_date:
            raise ValueError("published member is outside coverage")
        if key in sources:
            raise ValueError("duplicate publication member")
        sources[key] = member
    revisions = missing_pointer_revisions or {}
    result: list[PublicationSnapshotMemberPayload] = []
    current = coverage_start_date
    while current <= coverage_end_date:
        for report_type in _REPORT_TYPES:
            source = sources.get((current, report_type))
            if source is None:
                revision = revisions.get((current, report_type), 0)
                _nonnegative(revision, "missing pointer revision")
                result.append(
                    PublicationSnapshotMemberPayload(
                        report_type=report_type,
                        report_date=current,
                        dataset_id=None,
                        published_version_id=None,
                        publication_pointer_revision=revision,
                        version_data_revision=None,
                        member_status="missing",
                        active_row_count=0,
                        active_row_projection_digest=hashlib.sha256(b"[]").digest(),
                    )
                )
            else:
                result.append(
                    PublicationSnapshotMemberPayload(
                        report_type=report_type,
                        report_date=current,
                        dataset_id=source.dataset_id,
                        published_version_id=source.published_version_id,
                        publication_pointer_revision=(
                            source.publication_pointer_revision
                        ),
                        version_data_revision=source.version_data_revision,
                        member_status="published",
                        active_row_count=len(source.active_rows),
                        active_row_projection_digest=_projection_digest(source),
                    )
                )
        current += timedelta(days=1)
    provisional = PublicationSnapshotPayload(
        site_id=site_id,
        report_source_scope_id=report_source_scope_id,
        site_config_version_id=site_config_version_id,
        candidate_rule_version=candidate_rule_version,
        normalization_manifest_id=normalization_manifest_id,
        coverage_start_date=coverage_start_date,
        coverage_end_date=coverage_end_date,
        transaction_started_at=transaction_started_at,
        fact_cutoff_at=fact_cutoff_at,
        return_publication_set_digest=return_digest,
        members=tuple(result),
        snapshot_digest=b"\0" * 32,
    )
    return replace(
        provisional,
        snapshot_digest=hashlib.sha256(
            canonical_json_bytes(provisional.identity_payload())
        ).digest(),
    )


def build_fact_snapshot_tuple(
    *,
    publication_snapshot: PublicationSnapshotPayload,
    return_dedup_snapshot_id: int,
    return_dedup_decision_digest: bytes,
) -> FactSnapshotTuplePayload:
    _positive(return_dedup_snapshot_id, "return_dedup_snapshot_id")
    decision_digest = _digest(
        return_dedup_decision_digest, "return dedup decision digest"
    )
    payload: dict[str, CanonicalValue] = {
        "site_id": publication_snapshot.site_id,
        "report_source_scope_id": publication_snapshot.report_source_scope_id,
        "site_config_version_id": publication_snapshot.site_config_version_id,
        "fact_cutoff_at": _timestamp(publication_snapshot.fact_cutoff_at),
        "publication_snapshot_digest": publication_snapshot.snapshot_digest.hex(),
        "return_dedup_snapshot_id": return_dedup_snapshot_id,
        "return_publication_set_digest": (
            publication_snapshot.return_publication_set_digest.hex()
        ),
        "return_dedup_decision_digest": decision_digest.hex(),
    }
    return FactSnapshotTuplePayload(
        site_id=publication_snapshot.site_id,
        report_source_scope_id=publication_snapshot.report_source_scope_id,
        site_config_version_id=publication_snapshot.site_config_version_id,
        fact_cutoff_at=publication_snapshot.fact_cutoff_at,
        publication_snapshot_digest=publication_snapshot.snapshot_digest,
        return_dedup_snapshot_id=return_dedup_snapshot_id,
        return_publication_set_digest=(
            publication_snapshot.return_publication_set_digest
        ),
        return_dedup_decision_digest=decision_digest,
        tuple_digest=hashlib.sha256(canonical_json_bytes(payload)).digest(),
    )


__all__ = (
    "CANDIDATE_RULE_VERSION",
    "NORMALIZATION_MANIFEST_ID",
    "BusinessFactProjection",
    "FactSnapshotTuplePayload",
    "PublicationSnapshotMemberPayload",
    "PublicationSnapshotPayload",
    "PublishedFactMember",
    "ReturnFactProjection",
    "build_fact_snapshot_tuple",
    "build_publication_snapshot",
)
