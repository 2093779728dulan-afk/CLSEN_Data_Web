"""Immutable source-evidence members and deterministic XLSX summaries."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from datetime import date
from typing import Literal

from app.catalog.canonical_json import CanonicalValue, canonical_json_bytes
from app.catalog.source_refs import SafeSourceRef, make_safe_source_ref
from app.catalog.types import CatalogSourceKind

type EvidenceReportType = Literal["business_report", "return_report"]
type EvidenceTuple = tuple[str | None, str | None, str | None, str | None]


def _positive(value: int, label: str) -> None:
    if isinstance(value, bool) or not isinstance(value, int) or value < 1:
        raise ValueError(f"{label} must be positive")


@dataclass(frozen=True, slots=True)
class EvidenceObservation:
    """Closed allowed evidence projection; sensitive return fields are absent."""

    report_source_scope_id: int
    source_key_id: int
    report_type: EvidenceReportType
    report_date: date
    event_date: date | None
    dataset_id: int
    published_version_id: int
    source_row_id: int
    seller_sku: str = field(repr=False)
    title: str | None = field(repr=False)
    parent_asin: str | None = field(repr=False)
    child_asin: str | None = field(repr=False)
    fnsku: str | None = field(repr=False)
    source_locator: str = field(repr=False)

    def __post_init__(self) -> None:
        for label in (
            "report_source_scope_id",
            "source_key_id",
            "dataset_id",
            "published_version_id",
            "source_row_id",
        ):
            _positive(getattr(self, label), label)
        if self.report_type not in {"business_report", "return_report"}:
            raise ValueError("unsupported evidence report type")
        if self.report_type == "business_report" and self.event_date is not None:
            raise ValueError("business evidence cannot carry a return event date")
        if not isinstance(self.seller_sku, str):
            raise ValueError("seller SKU must be text")

    @property
    def distinct_tuple(self) -> EvidenceTuple:
        return (self.title, self.parent_asin, self.child_asin, self.fnsku)


@dataclass(frozen=True, slots=True)
class SourceEvidenceMember:
    observation: EvidenceObservation = field(repr=False)
    seller_sku_ref: SafeSourceRef
    title_ref: SafeSourceRef | None
    parent_asin_ref: SafeSourceRef | None
    child_asin_ref: SafeSourceRef | None
    fnsku_ref: SafeSourceRef | None
    source_locator_ref: SafeSourceRef
    evidence_tuple_digest: bytes


@dataclass(frozen=True, slots=True)
class SourceEvidenceSummary:
    report_source_scope_id: int
    report_type: EvidenceReportType
    source_key_ids: tuple[int, ...]
    seller_sku_ref: SafeSourceRef
    first_seen_date: date
    latest_seen_date: date
    occurrence_count: int
    title_distinct_count: int
    parent_asin_distinct_count: int
    child_asin_distinct_count: int
    fnsku_distinct_count: int
    latest_title: SafeSourceRef | None
    evidence_set_digest: str


@dataclass(frozen=True, slots=True)
class SourceEvidencePayload:
    members: tuple[SourceEvidenceMember, ...]
    summaries: tuple[SourceEvidenceSummary, ...]
    payload_digest: bytes


def _nullable_utf8_key(value: str | None) -> tuple[int, bytes]:
    return (0, b"") if value is None else (1, value.encode("utf-8"))


def _tuple_key(value: EvidenceTuple) -> tuple[tuple[int, bytes], ...]:
    return tuple(_nullable_utf8_key(member) for member in value)


def evidence_set_payload(
    observations: tuple[EvidenceObservation, ...],
) -> list[CanonicalValue]:
    """Return distinct tuples ordered null-first and by raw UTF-8 bytes."""

    distinct = sorted({item.distinct_tuple for item in observations}, key=_tuple_key)
    return [list(item) for item in distinct]


def _source_ref_id(kind: str, raw_value: str) -> str:
    digest = hashlib.sha256(
        kind.encode("ascii") + b"\0" + raw_value.encode("utf-8")
    ).hexdigest()
    return f"src_{digest}"


def _ref(raw_value: str, kind: CatalogSourceKind) -> SafeSourceRef:
    return make_safe_source_ref(
        source_ref_id=_source_ref_id(kind.value, raw_value),
        raw_value=raw_value,
        source_kind=kind,
    )


def _optional_ref(
    raw_value: str | None, kind: CatalogSourceKind
) -> SafeSourceRef | None:
    return None if raw_value is None else _ref(raw_value, kind)


def _locator_ref(raw_value: str) -> SafeSourceRef:
    # Locator is database-only. It deliberately reuses the hardened projection
    # primitive without widening the public CatalogSourceKind enum.
    projection = make_safe_source_ref(
        source_ref_id=_source_ref_id("source_locator", raw_value),
        raw_value=raw_value,
        source_kind=CatalogSourceKind.SELLER_SKU,
    )
    return projection


def _member(observation: EvidenceObservation) -> SourceEvidenceMember:
    tuple_digest = hashlib.sha256(
        canonical_json_bytes(list(observation.distinct_tuple))
    ).digest()
    return SourceEvidenceMember(
        observation=observation,
        seller_sku_ref=_ref(observation.seller_sku, CatalogSourceKind.SELLER_SKU),
        title_ref=_optional_ref(observation.title, CatalogSourceKind.TITLE),
        parent_asin_ref=_optional_ref(
            observation.parent_asin, CatalogSourceKind.PARENT_ASIN
        ),
        child_asin_ref=_optional_ref(
            observation.child_asin, CatalogSourceKind.CHILD_ASIN
        ),
        fnsku_ref=_optional_ref(observation.fnsku, CatalogSourceKind.FNSKU),
        source_locator_ref=_locator_ref(observation.source_locator),
        evidence_tuple_digest=tuple_digest,
    )


def aggregate_source_evidence(
    observations: tuple[EvidenceObservation, ...],
) -> SourceEvidencePayload:
    """Aggregate by scope + exact Seller SKU original value + report type."""

    ordered_observations = tuple(
        sorted(
            observations,
            key=lambda item: (
                item.report_source_scope_id,
                item.seller_sku.encode("utf-8"),
                item.report_type,
                item.report_date,
                item.dataset_id,
                item.published_version_id,
                item.source_row_id,
            ),
        )
    )
    members = tuple(_member(item) for item in ordered_observations)
    groups: dict[tuple[int, bytes, str], list[EvidenceObservation]] = {}
    for item in ordered_observations:
        groups.setdefault(
            (
                item.report_source_scope_id,
                item.seller_sku.encode("utf-8"),
                item.report_type,
            ),
            [],
        ).append(item)
    summaries: list[SourceEvidenceSummary] = []
    for (scope_id, _seller_bytes, report_type), group in sorted(groups.items()):
        latest = max(
            group,
            key=lambda item: (
                item.report_date,
                item.dataset_id,
                item.published_version_id,
                item.source_row_id,
            ),
        )
        distinct_payload = evidence_set_payload(tuple(group))
        summaries.append(
            SourceEvidenceSummary(
                report_source_scope_id=scope_id,
                report_type=report_type,  # type: ignore[arg-type]
                source_key_ids=tuple(sorted({item.source_key_id for item in group})),
                seller_sku_ref=_ref(group[0].seller_sku, CatalogSourceKind.SELLER_SKU),
                first_seen_date=min(item.report_date for item in group),
                latest_seen_date=max(item.report_date for item in group),
                occurrence_count=len(group),
                title_distinct_count=len(
                    {item.title for item in group if item.title is not None}
                ),
                parent_asin_distinct_count=len(
                    {item.parent_asin for item in group if item.parent_asin is not None}
                ),
                child_asin_distinct_count=len(
                    {item.child_asin for item in group if item.child_asin is not None}
                ),
                fnsku_distinct_count=len(
                    {item.fnsku for item in group if item.fnsku is not None}
                ),
                latest_title=_optional_ref(latest.title, CatalogSourceKind.TITLE),
                evidence_set_digest=(
                    "sha256:"
                    + hashlib.sha256(canonical_json_bytes(distinct_payload)).hexdigest()
                ),
            )
        )
    digest_payload: list[CanonicalValue] = [
        [
            summary.report_source_scope_id,
            summary.seller_sku_ref.sha256,
            summary.report_type,
            summary.first_seen_date.isoformat(),
            summary.latest_seen_date.isoformat(),
            summary.occurrence_count,
            summary.evidence_set_digest,
        ]
        for summary in summaries
    ]
    return SourceEvidencePayload(
        members=members,
        summaries=tuple(summaries),
        payload_digest=hashlib.sha256(canonical_json_bytes(digest_payload)).digest(),
    )


__all__ = (
    "EvidenceObservation",
    "SourceEvidenceMember",
    "SourceEvidencePayload",
    "SourceEvidenceSummary",
    "aggregate_source_evidence",
    "evidence_set_payload",
)
