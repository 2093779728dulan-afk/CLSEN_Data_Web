from __future__ import annotations

from dataclasses import replace
from uuid import uuid4

import pytest
from app.api.catalog_changes import StyleChangeDraftRequest
from app.catalog.change_service import CatalogStyleChangeError, _clean_name
from app.catalog.import_service import DraftRow, validate_draft_rows
from app.catalog.validation import evaluate_approval_rows


def rows(name: str | int | None = None) -> tuple[DraftRow, ...]:
    return (
        DraftRow(
            "styles",
            "s",
            "user_created",
            "included",
            {
                "style_code": "QA-NAME",
                "standard_name": name,
                "status": "enabled",
            },
            b"s" * 32,
        ),
        DraftRow(
            "skus",
            "v",
            "user_created",
            "included",
            {
                "style_row_key": "s",
                "standard_color": "Olive",
                "standard_size": "M",
                "internal_display_sku": None,
                "code_status": "pending",
                "code_evidence": "QA identity and specifications confirmed",
                "status": "enabled",
            },
            b"v" * 32,
        ),
    )


@pytest.mark.parametrize("name", [None, "", "  ", "QA confirmed name"])
def test_missing_name_does_not_block_identity_or_approval(
    name: str | int | None,
) -> None:
    assert not evaluate_approval_rows(rows(name)).issues


def test_missing_name_does_not_bypass_required_specifications_or_code_evidence() -> (
    None
):
    style, sku = rows()
    invalid = replace(
        sku, payload=sku.payload | {"standard_color": None, "code_evidence": None}
    )
    fields = {issue.field for issue in evaluate_approval_rows((style, invalid)).issues}
    assert fields == {"/standard_color", "/internal_display_sku"}


@pytest.mark.parametrize("name", ["x" * 256, 42])
def test_optional_name_keeps_its_type_and_length_contract(
    name: str | int | None,
) -> None:
    issues = validate_draft_rows(rows(name)).issues
    assert [(i.field, i.reason_code) for i in issues] == [
        ("/standard_name", "invalid_standard_name")
    ]


def test_category_maintenance_accepts_a_pending_name_without_a_fake_label() -> None:
    value = StyleChangeDraftRequest(
        operation_token=uuid4(),
        expected_catalog_publication_revision=1,
        expected_style_revision=1,
        standard_name="",
        category_action="keep",
    )
    assert value.standard_name == _clean_name("   ") == ""
    assert _clean_name("  QA confirmed name  ") == "QA confirmed name"
    with pytest.raises(CatalogStyleChangeError):
        _clean_name("x" * 256)
