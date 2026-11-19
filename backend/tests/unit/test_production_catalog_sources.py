from __future__ import annotations

from typing import cast

import pytest
from app.catalog.inventory import CatalogIdentityInventory
from app.catalog.production_sources import (
    ProductionSource,
    ProductionSourceRow,
    production_sku_choices,
    project_production_source,
)
from pydantic import ValidationError


def source(*rows: tuple[str, str, str]) -> ProductionSource:
    return ProductionSource(
        source_name="QA factory specification",
        rows=[
            ProductionSourceRow(style_code=style, color=color, size=size)
            for style, color, size in rows
        ],
    )


def test_no_sales_product_has_explicit_missing_decisions_and_no_fake_mapping() -> None:
    projection, observations = project_production_source(
        source(("QA-NEW", "Olive", "M")), CatalogIdentityInventory((), ())
    )
    assert projection.initial_status == "needs_attention"
    assert {issue.field for issue in projection.issues} == {
        "/internal_display_sku",
    }
    assert {row.section for row in projection.rows} == {"styles", "skus"}
    assert observations[0]["action"] == "REVIEW_NEW_PRODUCT"


def test_normalized_duplicates_keep_raw_evidence_but_one_candidate() -> None:
    projection, observations = project_production_source(
        source(("QA-01", "BLACK", "M"), ("qa-01", "black", "m")),
        CatalogIdentityInventory((), ()),
    )
    assert len(projection.rows) == 2
    assert observations[1]["action"] == "DUPLICATE_SOURCE_ROW"
    assert observations[0]["color"] == "BLACK"


def test_exact_reuse_preserves_all_unrelated_identities_and_does_not_guess_alias() -> (
    None
):
    inventory = CatalogIdentityInventory(
        (
            {
                "style_id": 17,
                "style_code": "QA-01",
                "standard_name": "QA Shirt",
                "status": "enabled",
            },
        ),
        (
            {
                "sku_id": 23,
                "style_id": 17,
                "style_code": "QA-01",
                "internal_display_sku": "QA-BROWN-M",
                "standard_color": "Brown",
                "standard_size": "M",
                "status": "enabled",
            },
        ),
    )
    projection, observations = project_production_source(
        source(("qa-01", "BROWN", "m"), ("QA-01", "light brown", "M")), inventory
    )
    assert [item["action"] for item in observations] == [
        "REUSE_EXISTING",
        "ADD_SPECIFICATION",
    ]
    assert len(projection.rows) == 3
    assert (
        next(row for row in projection.rows if row.row_key == "sku-23").payload[
            "system_sku_id"
        ]
        == "23"
    )
    assert (
        next(
            row for row in projection.rows if row.row_key.startswith("new-sku")
        ).payload["standard_color"]
        == "light brown"
    )


@pytest.mark.parametrize("value", ["", " ", "/"])
def test_unknown_specifications_are_not_variants(value: str) -> None:
    with pytest.raises(ValidationError):
        source(("QA-01", "Black", value))


def test_quantity_is_not_accepted_as_catalog_identity_input() -> None:
    with pytest.raises(ValidationError):
        ProductionSourceRow.model_validate(
            {"style_code": "QA-01", "color": "Black", "size": "M", "quantity": 10}
        )


def test_source_digest_is_bound_to_original_order_and_spelling() -> None:
    assert (
        source(("QA-01", "Black", "M")).evidence()["digest"]
        != source(("QA-01", "BLACK", "M")).evidence()["digest"]
    )


def test_no_generated_formal_codes_are_offered() -> None:
    projection, _ = project_production_source(
        source(("QA-01", "Light Brown", "M"), ("QA-01", "Sand", "L")),
        CatalogIdentityInventory((), ()),
    )
    choices = production_sku_choices(projection.rows)
    assert all(not choice["options"] for choice in choices.values())
    assert all(
        row.payload["internal_display_sku"] is None
        for row in projection.rows
        if row.section == "skus"
    )


def test_display_choices_preserve_existing_code_and_reject_normalized_collision() -> (
    None
):
    from dataclasses import replace

    projection, _ = project_production_source(
        source(("QA-01", "Black", "M"), ("QA-02", "Sand", "M")),
        CatalogIdentityInventory((), ()),
    )
    sku_rows = [row for row in projection.rows if row.section == "skus"]
    existing = replace(
        sku_rows[1],
        payload={
            **sku_rows[1].payload,
            "system_sku_id": "12",
            "internal_display_sku": "qa-01-black-m",
            "approved_formal_sku": "qa-01-black-m",
        },
    )
    other = replace(
        sku_rows[0],
        payload={**sku_rows[0].payload, "source_formal_sku": "QA-01-BLACK-M"},
    )
    rows = tuple(
        existing
        if row.row_key == existing.row_key
        else other
        if row.row_key == other.row_key
        else row
        for row in projection.rows
    )
    for item in production_sku_choices(rows).values():
        message = item["message"]
        assert not item["options"]
        assert isinstance(message, str) and "冲突" in message
    existing = replace(
        existing,
        payload={
            **existing.payload,
            "internal_display_sku": "LEGACY-CODE",
            "approved_formal_sku": "LEGACY-CODE",
        },
    )
    rows = tuple(existing if row.row_key == existing.row_key else row for row in rows)
    legacy_options = production_sku_choices(rows)[existing.row_key]["options"]
    assert isinstance(legacy_options, list) and isinstance(legacy_options[0], dict)
    assert legacy_options[0]["value"] == "LEGACY-CODE"


def test_ambiguous_joined_codes_are_not_offered_to_two_variants() -> None:
    projection, _ = project_production_source(
        source(("QA-A", "B", "M"), ("QA", "A-B", "M")),
        CatalogIdentityInventory((), ()),
    )
    assert all(
        not choice["options"]
        for choice in production_sku_choices(projection.rows).values()
    )


@pytest.mark.parametrize("color", [None, "/", "a" * 128])
def test_incomplete_or_overlong_display_code_is_not_offered(color: str) -> None:
    from dataclasses import replace

    projection, _ = project_production_source(
        source(("QA-01", "Olive", "M")), CatalogIdentityInventory((), ())
    )
    rows = tuple(
        replace(row, payload={**row.payload, "standard_color": color})
        if row.section == "skus"
        else row
        for row in projection.rows
    )
    assert all(
        not choice["options"] and choice["message"]
        for choice in production_sku_choices(rows).values()
    )


def test_pending_requires_explicit_evidence_and_still_checks_variant_uniqueness() -> (
    None
):
    from dataclasses import replace

    from app.catalog.validation import evaluate_approval_rows

    projection, _ = project_production_source(
        source(("QA-01", "Black", "M")), CatalogIdentityInventory((), ())
    )
    sku = next(row for row in projection.rows if row.section == "skus")
    pending = replace(
        sku,
        payload={
            **sku.payload,
            "code_status": "pending",
            "code_evidence": "Physical specification verified",
        },
    )
    rows = tuple(
        pending
        if row.section == "skus"
        else replace(row, payload={**row.payload, "standard_name": "QA shirt"})
        for row in projection.rows
    )
    assert not evaluate_approval_rows(rows).issues
    duplicate = replace(pending, row_key="another")
    assert any(
        issue.reason_code == "duplicate_variant"
        for issue in evaluate_approval_rows((*rows, duplicate)).issues
    )
    invalid = replace(pending, payload={**pending.payload, "code_evidence": None})
    assert any(
        issue.reason_code == "formal_code_decision_required"
        for issue in evaluate_approval_rows((rows[0], invalid)).issues
    )


def test_mapped_listing_target_must_have_a_confirmed_source_code_before_approval() -> (
    None
):
    from dataclasses import replace

    from app.catalog.import_service import DraftRow, validate_production_approval_rows

    projection, _ = project_production_source(
        source(("2301", "White", "S")), CatalogIdentityInventory((), ())
    )
    sku = next(row for row in projection.rows if row.section == "skus")
    pending = replace(
        sku,
        payload={
            **sku.payload,
            "source_formal_sku": "2301-White-S",
            "internal_display_sku": None,
            "code_status": "pending",
            "code_evidence": "Warehouse specification confirmed; formal code pending",
        },
    )
    mapping = DraftRow(
        "mappings",
        "listing-map-1",
        "system",
        "included",
        {
            "identity_decision": "mapped",
            "target_sku_row_key": pending.row_key,
            "source_target_sku_row_key": pending.row_key,
            "seller_sku_preview": "2301-White-S",
        },
        b"m" * 32,
    )
    rows = tuple(
        pending if row.row_key == sku.row_key else row for row in projection.rows
    )

    issues = validate_production_approval_rows(
        (*rows, mapping), listing_source=True
    ).issues

    assert [
        (issue.section, issue.row_key, issue.field, issue.reason_code)
        for issue in issues
        if issue.reason_code == "mapped_target_formal_code_required"
    ] == [
        (
            "skus",
            pending.row_key,
            "/internal_display_sku",
            "mapped_target_formal_code_required",
        )
    ]

    confirmed = replace(
        pending,
        payload={
            **pending.payload,
            "internal_display_sku": "2301-White-S",
            "code_status": "confirmed",
            "code_evidence": "CLSEN product listing source",
        },
    )
    confirmed_rows = tuple(
        confirmed if row.row_key == pending.row_key else row for row in rows
    )
    assert not validate_production_approval_rows(
        (*confirmed_rows, mapping), listing_source=True
    ).issues


def test_qa_catalog_mode_rejects_non_task_database() -> None:
    from types import SimpleNamespace
    from unittest.mock import Mock

    from app.api.errors import ApiError
    from app.config import Settings
    from app.production.identity import production_skus
    from app.site_context import CurrentSiteContext
    from sqlalchemy.engine import Engine

    with pytest.raises(ApiError) as error:
        production_skus(
            Mock(
                spec=Settings,
                production_demo_mode=False,
                production_qa_catalog_mode=True,
            ),
            Mock(spec=CurrentSiteContext, site_code="QA_PRODUCTION_CATALOG"),
            Mock(spec=Engine, url=SimpleNamespace(database="ordinary_database")),
        )
    assert (
        cast(dict[str, str], error.value.detail)["code"] == "qa_catalog_scope_invalid"
    )


def test_formal_code_empty_or_control_is_invalid_input() -> None:
    from app.catalog.production_sources import ProductionSourceRow
    from pydantic import ValidationError

    for code in ("   ", "code\x00"):
        with pytest.raises(ValidationError):
            ProductionSourceRow(
                style_code="QA", color="Olive", size="M", formal_sku=code
            )


def test_explicit_store_source_confirms_mapping_with_same_registration() -> None:
    original = ProductionSource(
        source_name="Confirmed shop product list",
        report_source_scope_id=7,
        channel_evidence="Confirmed seller SKU belongs to this shop",
        rows=[
            ProductionSourceRow(
                style_code="0012", color="Olive", size="M", formal_sku="0012-Olive-M"
            )
        ],
    )
    projection, _ = project_production_source(
        original, CatalogIdentityInventory((), ())
    )
    mapping = next(row for row in projection.rows if row.section == "mappings")
    assert mapping.payload["identity_decision"] == "mapped"
    sku = next(row for row in projection.rows if row.section == "skus")
    assert sku.payload["internal_display_sku"] == "0012-Olive-M"
    assert sku.payload["code_status"] == "confirmed"
    assert mapping.payload["seller_account"] == "7"
    assert mapping.payload["seller_sku_preview"] == "0012-Olive-M"
    internal_only = original.model_copy(
        update={"report_source_scope_id": None, "channel_evidence": None}
    )
    internal, _ = project_production_source(
        internal_only, CatalogIdentityInventory((), ())
    )
    assert not any(row.section == "mappings" for row in internal.rows)
