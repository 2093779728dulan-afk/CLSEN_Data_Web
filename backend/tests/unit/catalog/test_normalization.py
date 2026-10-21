from __future__ import annotations

import hashlib
import json
import unicodedata
from importlib.resources import files
from pathlib import Path

import pytest
from app.catalog.normalization import (
    UCD_VERSION,
    catalog_identity_key_v1,
    is_unsafe_source_text_v1,
    nfkc_15_1,
    safe_source_projection_v1,
    seller_sku_match_v1,
    verify_ucd_manifest,
)


def _codepoints(field: str) -> str:
    return "".join(chr(int(value, 16)) for value in field.split())


def test_ucd_manifest_is_complete_and_matches_packaged_bytes() -> None:
    data_root = Path(str(files("app.catalog").joinpath("data/ucd_15_1")))
    manifest = verify_ucd_manifest(data_root)

    assert UCD_VERSION == "15.1.0"
    assert manifest["unicode_version"] == UCD_VERSION
    assert set(manifest["files"]) == {
        "CaseFolding.txt",
        "CompositionExclusions.txt",
        "DerivedNormalizationProps.txt",
        "LICENSE.txt",
        "NormalizationTest.txt",
        "PropList.txt",
        "UnicodeData.txt",
    }
    for filename, record in manifest["files"].items():
        payload = (data_root / filename).read_bytes()
        assert record == {
            "bytes": len(payload),
            "sha256": hashlib.sha256(payload).hexdigest(),
        }


def test_ucd_manifest_fails_closed_on_tampering(tmp_path: Path) -> None:
    (tmp_path / "manifest.json").write_text(
        json.dumps(
            {
                "format": "clsen-ucd-manifest-v1",
                "unicode_version": "15.1.0",
                "files": {"UnicodeData.txt": {"bytes": 1, "sha256": "0" * 64}},
            }
        ),
        encoding="utf-8",
    )
    (tmp_path / "UnicodeData.txt").write_bytes(b"x")

    with pytest.raises(RuntimeError, match="UCD data integrity check failed"):
        verify_ucd_manifest(tmp_path)


def test_nfkc_matches_every_ucd_15_1_normalization_vector() -> None:
    test_data = files("app.catalog").joinpath("data/ucd_15_1/NormalizationTest.txt")
    vectors = 0
    with test_data.open("r", encoding="utf-8") as handle:
        for raw_line in handle:
            line = raw_line.split("#", 1)[0].strip()
            if not line or line.startswith("@"):
                continue
            fields = [field.strip() for field in line.split(";")]
            c1, c2, c3, c4, c5 = map(_codepoints, fields[:5])
            for value in (c1, c2, c3, c4, c5):
                assert nfkc_15_1(value) == c4
            vectors += 1

    assert vectors > 18_000


def test_frozen_casefold_differs_from_the_unicode_16_host() -> None:
    assert unicodedata.unidata_version.startswith("16.")
    unicode_16_cyrillic_tje = "\u1c89"
    assert unicode_16_cyrillic_tje.casefold() == "\u1c8a"

    frozen = catalog_identity_key_v1(unicode_16_cyrillic_tje)

    assert frozen.text == unicode_16_cyrillic_tje
    assert frozen.utf8 == unicode_16_cyrillic_tje.encode()


def test_seller_sku_nfkc_trim_preserves_case_and_detects_collisions() -> None:
    left = seller_sku_match_v1("\u2007\uff21bc-01\u3000")
    right = seller_sku_match_v1("Abc-01")

    assert left.text == "Abc-01"
    assert left.utf8 == right.utf8
    assert left.sha256 == right.sha256
    assert left.version == "seller_sku_match_v1"


def test_catalog_identity_uses_default_non_turkic_full_casefold() -> None:
    assert catalog_identity_key_v1(" Straße ").text == "strasse"
    assert catalog_identity_key_v1("İ").text == "i\u0307"
    assert catalog_identity_key_v1("I").text == "i"
    assert catalog_identity_key_v1("\u0131").text == "\u0131"


@pytest.mark.parametrize("value", ("", "\u2007", "\u3000"))
def test_empty_normalized_keys_are_rejected_without_echoing_input(value: str) -> None:
    with pytest.raises(ValueError, match="normalized key must not be empty") as error:
        catalog_identity_key_v1(value)

    if value:
        assert value not in str(error.value)


@pytest.mark.parametrize(
    "value",
    (
        "ok\x00bad",
        "ok\nbad",
        "ok\u202ebad",
        "ok\u2028bad",
        "ok\ufffebad",
        "ok\ufdd0bad",
    ),
)
def test_unsafe_source_text_uses_frozen_xml_and_category_rules(value: str) -> None:
    assert is_unsafe_source_text_v1(value) is True


@pytest.mark.parametrize("value", ("123-Red White-S", "123-A&B-S"))
def test_unsafe_source_text_does_not_apply_projection_only_separators(
    value: str,
) -> None:
    assert is_unsafe_source_text_v1(value) is False


def test_safe_projection_replaces_runs_trims_and_truncates_by_scalar() -> None:
    projected = safe_source_projection_v1(
        " \x00\n\uff21\u202e B  ",
        max_scalars=2,
    )

    assert projected.preview == "\uff21 "
    assert projected.sha256.startswith("sha256:")
    assert projected.is_unsafe is True
    assert projected.is_truncated is True
    assert "\x00" not in repr(projected)
    assert "\u202e" not in repr(projected)


def test_safe_projection_uses_fixed_fallback_when_nothing_is_displayable() -> None:
    projected = safe_source_projection_v1("\x00\u202e\n")

    assert projected.preview == "[不可显示]"
    assert projected.is_unsafe is True
    assert projected.is_truncated is False


def test_safe_projection_removes_html_structural_characters() -> None:
    raw = 'LIVE-DANGER</script>&"RAW'

    projected = safe_source_projection_v1(raw)

    assert projected.preview == "LIVE-DANGER /script RAW"
    assert projected.is_unsafe is True
    assert raw not in repr(projected)
