import json
from typing import Any

import pytest
import sqlalchemy as sa
from app.api.errors import ApiError
from app.production import fba_catalog_products as products


@pytest.fixture
def fixture(monkeypatch: pytest.MonkeyPatch) -> Any:
    engine = sa.create_engine("sqlite://")
    monkeypatch.setattr(products, "SCOPES_WITH_DISPLAY_NAMES", "report_source_scopes")
    with engine.begin() as con:
        for sql in [
            (
                "CREATE TABLE report_source_scopes (id INTEGER,site_id "
                "INTEGER,seller_account_display_name TEXT,marketplace_scope_code "
                "TEXT)"
            ),
            "INSERT INTO report_source_scopes VALUES (1,1,'广州店','amazon_us')",
            (
                "CREATE TABLE product_catalog_versions (id INTEGER,site_id "
                "INTEGER,base_catalog_version_id INTEGER,source_import_id INTEGER)"
            ),
            (
                "INSERT INTO product_catalog_versions VALUES "
                "(1,1,NULL,1),(2,1,1,2),(3,1,1,3)"
            ),
            (
                "CREATE TABLE catalog_imports (id INTEGER,site_id INTEGER,export_id "
                "INTEGER,status TEXT)"
            ),
            (
                "INSERT INTO catalog_imports VALUES "
                "(1,1,1,'approved'),(2,1,2,'approved'),(3,1,3,'approved')"
            ),
            (
                "CREATE TABLE catalog_export_payloads (export_id INTEGER,site_id "
                "INTEGER,evidence_payload_json TEXT)"
            ),
            (
                "CREATE TABLE product_catalog_mappings (site_id "
                "INTEGER,catalog_version_id INTEGER,report_source_scope_id "
                "INTEGER,seller_sku_match_bytes BLOB,sku_id INTEGER)"
            ),
        ]:
            con.execute(sa.text(sql))
        raw = {
            "row_id": "r1",
            "seller_sku": "1112-Black-L",
            "asin": "B000000001",
            "fnsku": "X000000001",
            "issues": [],
        }
        choice = {
            "row_id": "r1",
            "record_type": "variant",
            "scope_id": 1,
            "style_code": "1112",
            "color": "Black",
            "size": "L",
            "selected_sku_id": None,
        }
        source = {
            "source_schema": "amazon_listing_v1",
            "listing_rows": [raw],
            "selections": [choice],
        }
        for index, value in [
            (1, source),
            (2, {**source, "listing_rows": [{**raw, "asin": "B000000009"}]}),
            (3, {}),
        ]:
            con.execute(
                sa.text("INSERT INTO catalog_export_payloads VALUES (:id,1,:payload)"),
                {"id": index, "payload": json.dumps({"production_source": value})},
            )
    catalog = {
        "7": {
            "code": "1112-Black-L",
            "label": "1112 Black L",
            "status": "active",
            "catalog_version": "3:3",
            "style_code": "1112",
            "standard_color": "Black",
            "standard_size": "L",
        }
    }
    yield engine, catalog, source
    engine.dispose()


def resolve(fixture: Any) -> Any:
    engine, catalog, _ = fixture
    with engine.connect() as con:
        return products.catalog_products(con, 1, 1, catalog)


def replace_source(fixture: Any, value: Any) -> Any:
    with fixture[0].begin() as con:
        con.execute(
            sa.text(
                "UPDATE catalog_export_payloads SET evidence_payload_json=:value "
                "WHERE export_id=1"
            ),
            {"value": json.dumps({"production_source": value})},
        )


def test_reuses_approved_listing_without_reports_or_duplicate_upload(
    fixture: Any,
) -> None:
    result = resolve(fixture)
    assert result["identities"][0]["sku_id"] == "7"
    assert result["identities"][0]["asin"] == "B000000001"
    assert result["identities"][0]["store"] == "广州店"
    assert result["issues"] == []


@pytest.mark.parametrize(
    "change",
    [
        "draft",
        "scope",
        "missing",
        "conflict",
        "disabled",
        "wrong-spec",
        "official-override",
        "other-owner",
    ],
)
def test_unapproved_or_ambiguous_evidence_never_auto_enables(
    fixture: Any, change: Any
) -> None:
    engine, catalog, source = fixture
    if change == "draft":
        with engine.begin() as con:
            con.execute(sa.text("UPDATE catalog_imports SET status='draft' WHERE id=1"))
    elif change == "disabled":
        catalog["7"]["status"] = "disabled"
    elif change == "wrong-spec":
        catalog["7"]["standard_color"] = "Brown"
    elif change == "other-owner":
        with engine.begin() as con:
            con.execute(
                sa.text("INSERT INTO product_catalog_mappings VALUES (1,3,1,:key,8)"),
                {"key": b"1112-Black-L"},
            )
    else:
        if change == "scope":
            source["selections"][0]["scope_id"] = 2
        elif change == "missing":
            source["listing_rows"][0]["fnsku"] = ""
        elif change == "official-override":
            source["selections"][0]["use_official"] = True
        else:
            source["listing_rows"].append(
                {**source["listing_rows"][0], "row_id": "r2", "fnsku": "X000000002"}
            )
            source["selections"].append({**source["selections"][0], "row_id": "r2"})
        replace_source(fixture, source)
    assert resolve(fixture)["identities"] == []


def test_wrong_site_cannot_read_shop_evidence(fixture: Any) -> None:
    with fixture[0].connect() as con, pytest.raises(ApiError):
        products.catalog_products(con, 2, 1, fixture[1])
