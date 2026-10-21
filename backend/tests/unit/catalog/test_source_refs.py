from __future__ import annotations

import json

import pytest
from app.catalog.source_refs import SafeSourceRef, make_safe_source_ref
from app.catalog.types import CatalogSourceKind
from pydantic import ValidationError


def test_safe_source_ref_contains_only_the_public_projection() -> None:
    raw = "danger\x00\n\u202evalue"
    ref = make_safe_source_ref(
        source_ref_id="src_01JTESTSAFE0000000000000000",
        raw_value=raw,
        source_kind=CatalogSourceKind.SELLER_SKU,
    )

    assert ref.model_dump() == {
        "source_ref_id": "src_01JTESTSAFE0000000000000000",
        "preview": "danger value",
        "sha256": ref.sha256,
        "is_unsafe": True,
        "is_truncated": False,
    }
    dumped = json.dumps(ref.model_dump(), ensure_ascii=False)
    assert raw not in dumped
    assert raw not in repr(ref)
    assert "\x00" not in dumped
    assert "\u202e" not in dumped


def test_source_kind_closed_set_excludes_sensitive_return_fields() -> None:
    assert {kind.value for kind in CatalogSourceKind} == {
        "seller_sku",
        "parent_asin",
        "child_asin",
        "fnsku",
        "title",
    }
    for forbidden in ("order_id", "license_plate_number", "customer_comments"):
        with pytest.raises(ValueError):
            CatalogSourceKind(forbidden)


def test_safe_source_ref_rejects_unknown_fields_without_echoing_input() -> None:
    secret = "ORDER-SECRET-123"
    with pytest.raises(ValidationError) as error:
        SafeSourceRef.model_validate(
            {
                "source_ref_id": "src_01JTESTSAFE0000000000000000",
                "preview": "safe",
                "sha256": "sha256:" + "0" * 64,
                "is_unsafe": False,
                "is_truncated": False,
                "customer_comments": secret,
            }
        )

    assert secret not in str(error.value)


def test_safe_source_ref_validates_digest_and_scalar_limit() -> None:
    with pytest.raises(ValidationError):
        SafeSourceRef(
            source_ref_id="src_valid",
            preview="x" * 256,
            sha256="not-a-digest",
            is_unsafe=False,
            is_truncated=False,
        )


def test_safe_source_ref_never_exposes_html_structural_source_text() -> None:
    raw = 'LIVE-DANGER</script>&"RAW'

    ref = make_safe_source_ref(
        source_ref_id="src_html_structural",
        raw_value=raw,
        source_kind=CatalogSourceKind.TITLE,
    )

    assert ref.preview == "LIVE-DANGER /script RAW"
    assert ref.is_unsafe is True
    assert raw not in json.dumps(ref.model_dump(), ensure_ascii=False)
