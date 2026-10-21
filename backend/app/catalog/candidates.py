"""Bounded, deterministic suggestions derived only from observed Seller SKUs."""

from __future__ import annotations

import base64
import hashlib
import re
from dataclasses import dataclass
from typing import Literal

from app.catalog.canonical_json import CanonicalValue, canonical_json_bytes
from app.catalog.evidence import EvidenceObservation
from app.catalog.normalization import (
    catalog_identity_key_v1,
    is_unsafe_source_text_v1,
    seller_sku_match_v1,
)
from app.catalog.source_refs import SafeSourceRef, make_safe_source_ref
from app.catalog.types import CatalogSourceKind

type ExistingAction = Literal["mapped", "excluded"]
_STRICT_CANDIDATE = re.compile(r"^[0-9]+-[^-]+-[^-]+$")


@dataclass(frozen=True, slots=True)
class ExistingCatalogDecision:
    seller_sku_match_bytes: bytes
    action: ExistingAction
    target_sku_id: int | None
    exclusion_reason: str | None

    def __post_init__(self) -> None:
        if self.action == "mapped":
            if self.target_sku_id is None or self.exclusion_reason is not None:
                raise ValueError("mapped decision requires only a target SKU")
        elif self.action == "excluded":
            if self.target_sku_id is not None or not self.exclusion_reason:
                raise ValueError("excluded decision requires only a reason")
        else:
            raise ValueError("unsupported existing catalog decision")


@dataclass(frozen=True, slots=True)
class StyleCandidate:
    row_key: str
    style_code: str
    standard_name: None
    candidate_seller_sku_count: int
    source_title_count: int


@dataclass(frozen=True, slots=True)
class VariantCandidate:
    row_key: str
    style_row_key: str
    style_code: str
    source_color: str
    source_size: str
    observed_seller_sku_count: int


@dataclass(frozen=True, slots=True)
class MappingCandidate:
    row_key: str
    seller_sku_ref: SafeSourceRef
    report_types: tuple[str, ...]
    candidate_variant_row_key: str | None
    target_sku_id: int | None


@dataclass(frozen=True, slots=True)
class ExclusionCandidate:
    row_key: str
    seller_sku_ref: SafeSourceRef
    exclusion_reason: str


@dataclass(frozen=True, slots=True)
class CandidateException:
    row_key: str
    decision_group_key: str
    reason_code: str
    seller_sku_ref: SafeSourceRef
    source_report: Literal["business", "returns", "both"]
    candidate_style_code: str | None
    candidate_color: str | None
    candidate_size: str | None


@dataclass(frozen=True, slots=True)
class CatalogCandidatePayload:
    styles: tuple[StyleCandidate, ...]
    variants: tuple[VariantCandidate, ...]
    mappings: tuple[MappingCandidate, ...]
    exclusions: tuple[ExclusionCandidate, ...]
    exceptions: tuple[CandidateException, ...]
    payload_digest: bytes


def parse_seller_sku_candidate(value: str) -> tuple[str, str, str] | None:
    """Apply the strict release rule without creating any formal identity."""

    if not isinstance(value, str) or len(value) > 255:
        return None
    if is_unsafe_source_text_v1(value) or _STRICT_CANDIDATE.fullmatch(value) is None:
        return None
    style, color, size = value.split("-")
    if any(len(segment) > 128 for segment in (style, color, size)):
        return None
    return style, color, size


def _ref(raw_value: str) -> SafeSourceRef:
    digest = hashlib.sha256(raw_value.encode("utf-8")).hexdigest()
    return make_safe_source_ref(
        source_ref_id=f"src_{digest}",
        raw_value=raw_value,
        source_kind=CatalogSourceKind.SELLER_SKU,
    )


def _key(prefix: str, *values: bytes) -> str:
    digest = hashlib.sha256(prefix.encode("ascii") + b"\0" + b"\0".join(values))
    encoded = base64.urlsafe_b64encode(digest.digest()).rstrip(b"=").decode("ascii")
    return f"{prefix}_{encoded}"


def _source_report(values: set[str]) -> Literal["business", "returns", "both"]:
    if values == {"business_report", "return_report"}:
        return "both"
    if values == {"return_report"}:
        return "returns"
    return "business"


def build_catalog_candidates(
    observations: tuple[EvidenceObservation, ...],
    *,
    existing_decisions: tuple[ExistingCatalogDecision, ...] = (),
) -> CatalogCandidatePayload:
    decisions: dict[bytes, ExistingCatalogDecision] = {}
    for existing_decision in existing_decisions:
        if existing_decision.seller_sku_match_bytes in decisions:
            raise ValueError("duplicate existing catalog decision")
        decisions[existing_decision.seller_sku_match_bytes] = existing_decision

    by_raw: dict[bytes, list[EvidenceObservation]] = {}
    raw_values: dict[bytes, str] = {}
    for observation in observations:
        raw = observation.seller_sku.encode("utf-8")
        by_raw.setdefault(raw, []).append(observation)
        raw_values[raw] = observation.seller_sku

    match_to_raw: dict[bytes, list[bytes]] = {}
    normalized: dict[bytes, bytes] = {}
    for raw, value in raw_values.items():
        match = seller_sku_match_v1(value).utf8
        normalized[raw] = match
        match_to_raw.setdefault(match, []).append(raw)

    style_sources: dict[bytes, list[tuple[bytes, tuple[str, str, str]]]] = {}
    variant_sources: dict[
        tuple[bytes, bytes, bytes], list[tuple[bytes, tuple[str, str, str]]]
    ] = {}
    mapping_rows: list[MappingCandidate] = []
    exclusion_rows: list[ExclusionCandidate] = []
    exception_rows: list[CandidateException] = []

    for raw in sorted(by_raw):
        value = raw_values[raw]
        group = by_raw[raw]
        match = normalized[raw]
        collision_raws = match_to_raw[match]
        unsafe = is_unsafe_source_text_v1(value) or len(value) > 255
        parsed = None if unsafe else parse_seller_sku_candidate(value)
        report_types = tuple(sorted({item.report_type for item in group}))
        source_ref = _ref(value)
        matched_decision = decisions.get(match)
        if parsed is not None:
            style, color, size = parsed
            style_key = catalog_identity_key_v1(style).utf8
            variant_key = (
                style_key,
                catalog_identity_key_v1(color).utf8,
                catalog_identity_key_v1(size).utf8,
            )
            style_sources.setdefault(style_key, []).append((raw, parsed))
            variant_sources.setdefault(variant_key, []).append((raw, parsed))
            variant_row_key = _key("sku", *variant_key)
        else:
            variant_row_key = None

        mapping_key = _key("mapping", match)
        if matched_decision is not None and matched_decision.action == "excluded":
            if matched_decision.exclusion_reason is None:  # narrowed above
                raise ValueError("excluded decision has no reason")
            exclusion_rows.append(
                ExclusionCandidate(
                    row_key=_key("exclusion", match),
                    seller_sku_ref=source_ref,
                    exclusion_reason=matched_decision.exclusion_reason,
                )
            )
        mapping_rows.append(
            MappingCandidate(
                row_key=mapping_key,
                seller_sku_ref=source_ref,
                report_types=report_types,
                candidate_variant_row_key=variant_row_key,
                target_sku_id=(
                    matched_decision.target_sku_id
                    if matched_decision is not None
                    and matched_decision.action == "mapped"
                    else None
                ),
            )
        )

        if unsafe:
            reason = "unsafe_source_text"
        elif len(collision_raws) > 1:
            reason = "seller_sku_normalization_collision"
        elif parsed is None:
            reason = "seller_sku_format_unmatched"
        else:
            reason = None
        if reason is not None:
            exception_rows.append(
                CandidateException(
                    row_key=_key("exception", raw),
                    decision_group_key=_key("group", match),
                    reason_code=reason,
                    seller_sku_ref=source_ref,
                    source_report=_source_report(set(report_types)),
                    candidate_style_code=None if parsed is None else parsed[0],
                    candidate_color=None if parsed is None else parsed[1],
                    candidate_size=None if parsed is None else parsed[2],
                )
            )

    styles: list[StyleCandidate] = []
    for style_key, sources in sorted(style_sources.items()):
        style_display = min(
            (parsed[0] for _raw, parsed in sources), key=lambda value: value.encode()
        )
        source_rows = [item for raw, _parsed in sources for item in by_raw[raw]]
        styles.append(
            StyleCandidate(
                row_key=_key("style", style_key),
                style_code=style_display,
                standard_name=None,
                candidate_seller_sku_count=len({raw for raw, _parsed in sources}),
                source_title_count=len(
                    {item.title for item in source_rows if item.title is not None}
                ),
            )
        )
    variants: list[VariantCandidate] = []
    for variant_key, sources in sorted(variant_sources.items()):
        variant_display = min(
            (parsed for _raw, parsed in sources),
            key=lambda value: tuple(member.encode() for member in value),
        )
        variants.append(
            VariantCandidate(
                row_key=_key("sku", *variant_key),
                style_row_key=_key("style", variant_key[0]),
                style_code=variant_display[0],
                source_color=variant_display[1],
                source_size=variant_display[2],
                observed_seller_sku_count=len({raw for raw, _parsed in sources}),
            )
        )

    digest_value: list[CanonicalValue] = [
        [[row.row_key, row.style_code] for row in styles],
        [
            [row.row_key, row.style_row_key, row.source_color, row.source_size]
            for row in variants
        ],
        [
            [row.row_key, row.seller_sku_ref.sha256, row.target_sku_id]
            for row in mapping_rows
        ],
        [[row.row_key, row.seller_sku_ref.sha256] for row in exclusion_rows],
        [[row.row_key, row.reason_code] for row in exception_rows],
    ]
    return CatalogCandidatePayload(
        styles=tuple(styles),
        variants=tuple(variants),
        mappings=tuple(sorted(mapping_rows, key=lambda row: row.row_key)),
        exclusions=tuple(sorted(exclusion_rows, key=lambda row: row.row_key)),
        exceptions=tuple(sorted(exception_rows, key=lambda row: row.row_key)),
        payload_digest=hashlib.sha256(canonical_json_bytes(digest_value)).digest(),
    )


__all__ = (
    "CandidateException",
    "CatalogCandidatePayload",
    "ExclusionCandidate",
    "ExistingCatalogDecision",
    "MappingCandidate",
    "StyleCandidate",
    "VariantCandidate",
    "build_catalog_candidates",
    "parse_seller_sku_candidate",
)
