"""Fictional physical-identity matching; no Seller SKU parsing or stock writes."""

from copy import deepcopy
from dataclasses import replace
from typing import Any
from uuid import uuid4

import pytest
from app.api import production
from app.api.dependencies import get_current_site_context, get_database_engine
from app.api.errors import ApiError
from app.catalog.queries import (
    CatalogSkuSummary,
    CatalogSourceSummary,
    CatalogStyleSummary,
    CatalogVersionSummary,
    MySqlCatalogQueries,
)
from app.production import inventory_review as ir
from app.production.inventory_product_match import product_match
from app.site_context import CurrentSiteContext
from fastapi import FastAPI
from fastapi.testclient import TestClient


@pytest.fixture
def snapshot() -> dict[str, Any]:
    row = {
        "source_key": "QA!2",
        "style_code": "0012",
        "color": "navy",
        "color_note": "",
        "quantities": {
            "M": {"cell": "E2", "raw": "/", "state": "LITERAL", "units": "0"}
        },
    }
    return {"rows": [row], "unconfirmed_rows": [], "outside_rows": []}


@pytest.fixture
def catalog() -> CatalogVersionSummary:
    source = CatalogSourceSummary(None, None, 0, 0)
    style = CatalogStyleSummary(
        11, 1, "0012", "", "enabled", None, None, None, False, 1, 0, source
    )
    sku = CatalogSkuSummary(
        21, 11, 1, "OFFICIAL-MIXED-code", "Navy", "M", "enabled", 0, source
    )
    return CatalogVersionSummary(3, 3, 3, (style,), (sku,))


def test_case_only_physical_spec_keeps_ids_code_and_saved_zero(
    snapshot: dict[str, Any], catalog: CatalogVersionSummary
) -> None:
    before = deepcopy(snapshot)
    result = product_match(snapshot, catalog, "QA!2", "M")
    assert result["status"] == "matched"
    assert result["source"]["units"] == "0"
    assert result["candidates"][0] == {
        "style_id": "11",
        "sku_id": "21",
        "style_code": "0012",
        "standard_name": "",
        "standard_color": "Navy",
        "standard_size": "M",
        "code": "OFFICIAL-MIXED-code",
        "active": True,
    }
    assert result["catalog_version_id"] == "3"
    assert result["association_saved"] is False and result["posting_enabled"] is False
    assert snapshot == before


@pytest.mark.parametrize(
    "field,value", [("style_code", "12"), ("color", "Classic Navy")]
)
def test_no_inferred_leading_zero_or_color_alias(
    snapshot: dict[str, Any], catalog: CatalogVersionSummary, field: str, value: str
) -> None:
    snapshot["rows"][0][field] = value
    assert product_match(snapshot, catalog, "QA!2", "M")["status"] == "not_found"


def test_missing_unknown_and_disabled_are_distinct(
    snapshot: dict[str, Any], catalog: CatalogVersionSummary
) -> None:
    assert product_match(snapshot, None, "QA!2", "M")["status"] == "catalog_unavailable"
    disabled = replace(catalog, skus=(replace(catalog.skus[0], status="disabled"),))
    assert product_match(snapshot, disabled, "QA!2", "M")["status"] == "disabled"
    snapshot["rows"][0]["color"] = ""
    assert (
        product_match(snapshot, catalog, "QA!2", "M")["status"] == "source_incomplete"
    )


def test_ambiguous_and_pending_quantity_do_not_auto_bind(
    snapshot: dict[str, Any], catalog: CatalogVersionSummary
) -> None:
    duplicated = replace(
        catalog, skus=(*catalog.skus, replace(catalog.skus[0], sku_id=22))
    )
    assert product_match(snapshot, duplicated, "QA!2", "M")["status"] == "ambiguous"
    snapshot["rows"][0]["quantities"]["M"] |= {"state": "UNKNOWN", "units": None}
    result = product_match(snapshot, catalog, "QA!2", "M")
    assert result["status"] == "matched" and result["source"]["units"] is None
    assert result["association_saved"] is False


def test_source_key_is_bound_to_the_fixed_review(
    snapshot: dict[str, Any], catalog: CatalogVersionSummary
) -> None:
    with pytest.raises(ApiError):
        product_match(snapshot, catalog, "foreign!2", "M")


def test_api_pins_revision_and_passes_authenticated_site(
    snapshot: dict[str, Any],
    catalog: CatalogVersionSummary,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    app = FastAPI()
    app.include_router(production.router)
    context = CurrentSiteContext(
        1, frozenset({"viewer"}), 1, "QA", "QA", 1, 1, "UTC", "UTC", "USD"
    )
    app.dependency_overrides[get_current_site_context] = lambda: context
    app.dependency_overrides[get_database_engine] = lambda: object()
    calls: list[int] = []
    monkeypatch.setattr(
        ir,
        "detail",
        lambda *_: {"effective": snapshot, "revision": 2, "source_identity": "a" * 64},
    )

    def current(_self: object, *, site_id: int) -> CatalogVersionSummary:
        calls.append(site_id)
        return catalog

    monkeypatch.setattr(MySqlCatalogQueries, "current_catalog", current)
    identifier = str(uuid4())
    path = f"/api/production/inventory-reviews/{identifier}/product-match"
    params: dict[str, str | int] = {
        "expected_revision": 2,
        "source_key": "QA!2",
        "size": "M",
    }
    with TestClient(app) as client:
        response = client.get(path, params=params)
        assert response.status_code == 200 and calls == [1]
        assert response.json()["review_revision"] == 2
        assert response.json()["association_saved"] is False
        calls.clear()
        assert (
            client.get(path, params=params | {"expected_revision": 1}).status_code
            == 409
        )
        assert not calls


def test_saved_cell_identity_is_separate_from_live_candidate(
    snapshot: dict[str, Any], catalog: CatalogVersionSummary
) -> None:
    link = {
        "style_id": "11",
        "sku_id": "21",
        "catalog_version_id": "3",
        "catalog_publication_revision": "3",
        "code": "OFFICIAL-MIXED-code",
    }
    snapshot["rows"][0]["product_links"] = {"M": link}
    result = product_match(snapshot, catalog, "QA!2", "M")
    assert result["association_saved"] is True
    assert result["saved_association"] == link
    assert result["association_current"] is True
    disabled = replace(catalog, skus=(replace(catalog.skus[0], status="disabled"),))
    result = product_match(snapshot, disabled, "QA!2", "M")
    assert result["association_saved"] is True
    assert result["association_current"] is False
    assert result["saved_association"]["sku_id"] == "21"
    assert product_match(snapshot, catalog, "QA!2", "L")["association_saved"] is False


def test_product_change_uses_cell_granularity_and_can_unlink() -> None:
    change = ir.ProductChange.model_validate(
        {
            "type": "set_product",
            "source_key": "QA!2",
            "size": "M",
            "value": {
                "sku_id": "21",
                "catalog_version_id": "3",
                "catalog_publication_revision": "3",
            },
        }
    )
    assert ir.change_target(change) == ("QA!2", "product_M")
    unlink = ir.ProductChange(
        type="set_product", source_key="QA!2", size="M", value=None
    )
    assert unlink.value is None


@pytest.fixture
def review_header(snapshot: dict[str, Any]) -> dict[str, Any]:
    source = deepcopy(snapshot)
    source["rows"][0].update(
        {
            "location_group": "WAREHOUSE_1",
            "source_total": {"state": "LITERAL", "units": "0"},
            "notes": [],
            "stock_units": "0",
            "sku_id": None,
        }
    )
    source.update(
        {"summary": {}, "quantity_basis": "DECLARED_TOTAL", "stocktaken_on": None}
    )
    return {
        "source_identity": "a" * 64,
        "revision": 0,
        "policy_version": ir.POLICY,
        "source_snapshot_json": source,
    }


def test_link_does_not_edit_quantities_and_unlink_preserves_source(
    review_header: dict[str, Any], catalog: CatalogVersionSummary
) -> None:
    command = ir.PreviewCommand.model_validate(
        {
            "source_identity": "a" * 64,
            "expected_revision": 0,
            "changes": [
                {
                    "type": "set_product",
                    "source_key": "QA!2",
                    "size": "M",
                    "value": {
                        "sku_id": "21",
                        "catalog_version_id": "3",
                        "catalog_publication_revision": "3",
                    },
                }
            ],
            "reason": "QA",
        }
    )
    before = deepcopy(review_header)
    overrides, preview = ir.calculate(review_header, {}, command, catalog)
    assert preview["before"] == preview["after"]
    after = ir.effective(review_header["source_snapshot_json"], overrides)
    assert after["rows"][0]["product_links"]["M"]["sku_id"] == "21"
    assert after["rows"][0]["sku_id"] is None
    assert (
        after["rows"][0]["quantities"]
        == review_header["source_snapshot_json"]["rows"][0]["quantities"]
    )
    unlink = command.model_copy(
        update={
            "changes": [
                ir.ProductChange(
                    type="set_product", source_key="QA!2", size="M", value=None
                )
            ]
        }
    )
    removed, _ = ir.calculate(review_header, overrides, unlink)
    assert not ir.effective(review_header["source_snapshot_json"], removed)["rows"][
        0
    ].get("product_links")
    assert review_header == before


@pytest.mark.parametrize(
    "kind", ["disabled", "ambiguous", "foreign_sku", "catalog_changed"]
)
def test_save_rule_rechecks_identity_and_catalog(
    review_header: dict[str, Any], catalog: CatalogVersionSummary, kind: str
) -> None:
    if kind == "disabled":
        catalog = replace(catalog, skus=(replace(catalog.skus[0], status="disabled"),))
    if kind == "ambiguous":
        catalog = replace(
            catalog, skus=(*catalog.skus, replace(catalog.skus[0], sku_id=22))
        )
    if kind == "catalog_changed":
        catalog = replace(catalog, catalog_publication_revision=4)
    change = {
        "type": "set_product",
        "source_key": "QA!2",
        "size": "M",
        "value": {
            "sku_id": "99" if kind == "foreign_sku" else "21",
            "catalog_version_id": "3",
            "catalog_publication_revision": "3",
        },
    }
    command = ir.PreviewCommand.model_validate(
        {
            "source_identity": "a" * 64,
            "expected_revision": 0,
            "changes": [change],
            "reason": "QA",
        }
    )
    with pytest.raises(ApiError) as caught:
        ir.calculate(review_header, {}, command, catalog)
    assert caught.value.status_code == 409
