from __future__ import annotations

from typing import Any

# ruff: noqa: RUF001 -- Chinese user-facing text.
import pytest
from app.catalog.source_formatting import format_identity_field


@pytest.mark.parametrize(
    ("field", "raw", "expected"),
    [
        ("style", " ００１２ ", "0012"),
        ("color", " ＬＩＧＨＴ\u00a0  blue ", "Light Blue"),
        ("size", " ｘｌ ", "XL"),
        ("color", "象牙白", "象牙白"),
    ],
)
def test_safe_formatting(field: str, raw: str, expected: str) -> None:
    assert format_identity_field(raw, field) == (expected, None)


def test_catalog_spelling_wins_without_guessing_color_synonyms() -> None:
    assert format_identity_field(" NAVY ", "color", ["navy"]) == ("navy", None)
    assert format_identity_field("White", "color", ["Ivory White"]) == ("White", None)


def test_multiple_catalog_identities_are_not_silently_merged() -> None:
    value, problem = format_identity_field(
        "light   blue", "color", ["Light Blue", "Light  Blue"]
    )
    assert value == "light   blue"
    assert problem is not None and "多个" in problem


def test_control_characters_are_not_deleted_to_hide_invalid_input() -> None:
    assert format_identity_field("Blue\n", "color")[0] == "Blue\n"
    assert format_identity_field("Blue\u200b", "color")[0] == "Blue\u200b"


@pytest.mark.parametrize("raw", ["XXXL", " xxxl ", " ｘｘｘｌ ", "3XL"])
def test_confirmed_3xl_standard(raw: str) -> None:
    assert format_identity_field(raw, "size", ["3XL"]) == ("3XL", None)


def test_legacy_size_needs_correction_before_intake() -> None:
    value, problem = format_identity_field("XXXL", "size", ["XXXL"])
    assert value == "XXXL"
    assert problem is not None and "3XL" in problem


@pytest.mark.parametrize("size", ["XXXL", "xxxl", " xxxl ", "ｘｘｘｌ", "3xl"])
def test_maintenance_draft_cannot_reintroduce_xxxl_standard(size: str) -> None:
    from app.catalog.import_service import DraftRow, validate_draft_rows

    payload: dict[str, Any] = {
        "standard_color": "Navy",
        "standard_size": size,
        "internal_display_sku": "1115-Navy-XXXL",
        "code_status": "legacy",
        "status": "disabled",
    }
    row = DraftRow("skus", "sku-test", "user_created", "included", payload, bytes(32))
    assert any(
        issue.reason_code == "noncanonical_standard_size"
        for issue in validate_draft_rows((row,)).issues
    )


def test_unconfirmed_size_aliases_and_original_codes_are_unchanged() -> None:
    assert format_identity_field("XXXXL", "size") == ("XXXXL", None)
    assert format_identity_field("2XL", "size") == ("2XL", None)
    assert format_identity_field("1115-Navy-XXXL", "style") == ("1115-Navy-XXXL", None)
