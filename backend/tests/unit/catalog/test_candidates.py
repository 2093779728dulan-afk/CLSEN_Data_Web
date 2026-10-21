from __future__ import annotations

from datetime import date, timedelta
from typing import Literal

from app.catalog.candidates import (
    ExistingCatalogDecision,
    build_catalog_candidates,
    parse_seller_sku_candidate,
)
from app.catalog.evidence import EvidenceObservation


def _observation(
    seller_sku: str,
    *,
    source_key_id: int,
    report_type: Literal["business_report", "return_report"] = "business_report",
) -> EvidenceObservation:
    return EvidenceObservation(
        report_source_scope_id=7,
        source_key_id=source_key_id,
        report_type=report_type,
        report_date=date(2026, 1, 1) + timedelta(days=source_key_id),
        event_date=None,
        dataset_id=source_key_id * 10,
        published_version_id=source_key_id * 100,
        source_row_id=source_key_id * 1000,
        seller_sku=seller_sku,
        title=f"title-{source_key_id}",
        parent_asin=None,
        child_asin=f"ASIN-{source_key_id}",
        fnsku=None,
        source_locator=f"row:{source_key_id}",
    )


def test_strict_three_segment_rule_is_suggestion_only() -> None:
    assert parse_seller_sku_candidate("123-Red-S") == ("123", "Red", "S")
    for invalid in (
        "ABC-Red-S",
        "123-Red-S-extra",
        "123--S",
        "123-Red-",
        "123-Red",
        " 123-Red-S ",
    ):
        assert parse_seller_sku_candidate(invalid) is None


def test_strict_three_segment_rule_allows_internal_plain_spaces() -> None:
    value = "123-Red White-Size L"

    assert parse_seller_sku_candidate(value) == ("123", "Red White", "Size L")

    payload = build_catalog_candidates((_observation(value, source_key_id=1),))

    assert len(payload.variants) == 1
    assert payload.exceptions == ()


def test_candidates_preserve_observed_variants_without_cartesian_products() -> None:
    payload = build_catalog_candidates(
        (
            _observation("100-Red-S", source_key_id=1),
            _observation("100-Blue-M", source_key_id=2),
            _observation("100-Red-S", source_key_id=3, report_type="return_report"),
        )
    )

    observed = {
        (row.style_code, row.source_color, row.source_size) for row in payload.variants
    }
    assert observed == {
        ("100", "Blue", "M"),
        ("100", "Red", "S"),
    }
    assert ("100", "Red", "M") not in {
        (row.style_code, row.source_color, row.source_size) for row in payload.variants
    }
    assert payload.styles[0].standard_name is None


def test_collisions_unmatched_existing_aliases_and_exclusions_are_preserved() -> None:
    payload = build_catalog_candidates(
        (
            _observation("200-Red-S", source_key_id=1),
            _observation("\uff12\uff10\uff10-Red-S", source_key_id=2),
            _observation("bad-format", source_key_id=3),
            _observation("300-Blue-M", source_key_id=4),
            _observation("400-Green-L", source_key_id=5),
        ),
        existing_decisions=(
            ExistingCatalogDecision(
                seller_sku_match_bytes=b"300-Blue-M",
                action="mapped",
                target_sku_id=88,
                exclusion_reason=None,
            ),
            ExistingCatalogDecision(
                seller_sku_match_bytes=b"400-Green-L",
                action="excluded",
                target_sku_id=None,
                exclusion_reason="Known non-product source identifier",
            ),
        ),
    )

    reasons = {issue.reason_code for issue in payload.exceptions}
    assert reasons == {
        "seller_sku_normalization_collision",
        "seller_sku_format_unmatched",
    }
    assert {row.target_sku_id for row in payload.mappings if row.target_sku_id} == {88}
    assert len(payload.exclusions) == 1
    assert payload.exclusions[0].exclusion_reason == (
        "Known non-product source identifier"
    )
    restored_candidate = next(
        row for row in payload.mappings if row.seller_sku_ref.preview == "400-Green-L"
    )
    assert restored_candidate.target_sku_id is None


def test_unsafe_source_text_never_runs_candidate_parser() -> None:
    payload = build_catalog_candidates(
        (_observation("500-Red-\u202eS", source_key_id=1),)
    )

    assert payload.variants == ()
    assert payload.exceptions[0].reason_code == "unsafe_source_text"
    assert payload.exceptions[0].candidate_style_code is None


def test_candidate_capacity_fixture_classifies_34_variants_and_224_unmatched() -> None:
    valid = tuple(
        _observation(f"{1000 + index}-Color-Size", source_key_id=index + 1)
        for index in range(34)
    )
    unmatched = tuple(
        _observation(f"unmatched-{index}", source_key_id=index + 35)
        for index in range(224)
    )

    payload = build_catalog_candidates(valid + unmatched)

    assert len(payload.styles) == 34
    assert len(payload.variants) == 34
    assert len(payload.exceptions) == 224
    assert {row.reason_code for row in payload.exceptions} == {
        "seller_sku_format_unmatched"
    }
