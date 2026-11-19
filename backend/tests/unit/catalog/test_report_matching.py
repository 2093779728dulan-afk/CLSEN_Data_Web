# ruff: noqa: E501 -- Literal test schemas.
from types import SimpleNamespace
from typing import Any

import pytest
import sqlalchemy as sa
from app.api.errors import ApiError
from app.catalog import report_matching as matching


@pytest.fixture
def fixture(monkeypatch: pytest.MonkeyPatch) -> Any:
    engine = sa.create_engine("sqlite://")
    with engine.begin() as connection:
        for sql in [
            "CREATE TABLE daily_datasets (id INTEGER,site_id INTEGER,report_type TEXT)",
            "CREATE TABLE dataset_versions (id INTEGER,dataset_id INTEGER)",
            "CREATE TABLE report_dataset_scope_assignments (dataset_id INTEGER,site_id INTEGER,report_source_scope_id INTEGER)",
            "CREATE TABLE version_rows (id INTEGER,version_id INTEGER,row_state TEXT)",
            "CREATE TABLE business_report_rows (version_row_id INTEGER,version_id INTEGER,sku TEXT,child_asin TEXT)",
            "CREATE TABLE product_catalog_mappings (site_id INTEGER,catalog_version_id INTEGER,report_source_scope_id INTEGER,seller_sku_match_bytes BLOB,sku_id INTEGER)",
            "CREATE TABLE product_catalog_exclusions (site_id INTEGER,catalog_version_id INTEGER,report_source_scope_id INTEGER,seller_sku_match_bytes BLOB)",
            "INSERT INTO daily_datasets VALUES (1,7,'business_report')",
            "INSERT INTO dataset_versions VALUES (1,1)",
            "INSERT INTO report_dataset_scope_assignments VALUES (1,7,2)",
            "INSERT INTO version_rows VALUES (1,1,'active'),(2,1,'active'),(3,1,'active'),(4,1,'removed')",
            "INSERT INTO business_report_rows VALUES (1,1,'0012-Olive-M','B000000001'),(2,1,'0012-Olive-M','B000000001'),(3,1,'New-Blue-L','B000000002'),(4,1,'Removed-Blue-L','B000000003')",
        ]:
            connection.execute(sa.text(sql))
        connection.execute(
            sa.text("INSERT INTO product_catalog_mappings VALUES (7,3,2,:key,11)"),
            {"key": b"0012-Olive-M"},
        )
    monkeypatch.setattr(matching, "_publication", lambda *args, **kwargs: (3, 5))
    inventory = SimpleNamespace(
        styles=({"style_id": 9, "status": "enabled"},),
        skus=({"sku_id": 11, "style_id": 9, "status": "enabled"},),
    )
    monkeypatch.setattr(
        matching, "load_catalog_identity_inventory", lambda *args, **kwargs: inventory
    )
    monkeypatch.setattr(
        matching, "official_evidence", lambda *args, **kwargs: {"observations": []}
    )
    yield engine, inventory
    engine.dispose()


def test_scoped_mapping_reused_and_only_new_products_need_action(fixture: Any) -> None:
    engine, _ = fixture
    with engine.connect() as connection:
        result = matching.match_report(connection, 7, 1)
    assert result["matched"] == 1
    assert result["total"] == 2
    assert [row["seller_sku"] for row in result["issues"]] == ["New-Blue-L"]


def test_other_shop_same_text_never_reuses_mapping(fixture: Any) -> None:
    engine, _ = fixture
    with engine.begin() as connection:
        connection.execute(
            sa.text(
                "UPDATE report_dataset_scope_assignments SET report_source_scope_id=4"
            )
        )
        assert matching.match_report(connection, 7, 1)["matched"] == 0
        with pytest.raises(ApiError) as error:
            matching.match_report(connection, 8, 1)
        assert error.value.status_code == 404


def test_disabled_and_excluded_products_keep_existing_decisions(fixture: Any) -> None:
    engine, inventory = fixture
    inventory.skus[0]["status"] = "disabled"
    with engine.begin() as connection:
        connection.execute(
            sa.text("INSERT INTO product_catalog_exclusions VALUES (7,3,2,:key)"),
            {"key": b"New-Blue-L"},
        )
        result = matching.match_report(connection, 7, 1)
    assert result["matched"] == 0
    assert result["excluded"] == 1
    assert len(result["issues"]) == 1


def test_official_conflict_cannot_be_reported_as_matched(
    fixture: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    engine, _ = fixture
    monkeypatch.setattr(
        matching,
        "official_evidence",
        lambda *args: {
            "observations": [
                {
                    "report_source_scope_id": 2,
                    "seller_sku": "0012-Olive-M",
                    "child_asin": asin,
                    "parent_asin": None,
                    "fnsku": None,
                    "report_type": "business_report",
                }
                for asin in ["B000000001", "B000000009"]
            ]
        },
    )
    with engine.connect() as connection:
        assert matching.match_report(connection, 7, 1)["matched"] == 0
