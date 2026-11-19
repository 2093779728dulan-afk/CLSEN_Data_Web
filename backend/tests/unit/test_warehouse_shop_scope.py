from __future__ import annotations

import json
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock

import pytest
from app.api.errors import ApiError
from app.production.identity import (
    configured_warehouse_product_scope,
    warehouse_product_scope,
)


def test_local_binding_does_not_classify_another_site_or_warehouse(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    settings: Any = MagicMock(production_inventory_source_root=str(tmp_path))
    context: Any = MagicMock(site_id=1)
    engine: Any = MagicMock()
    engine.url.database = "clsen_data_test_shop_scope"
    binding = {
        "schema": "warehouse-product-scope-v1",
        "site_id": "1",
        "database": engine.url.database,
        "warehouse_id": "23",
        "warehouse_type": "FACTORY",
        "report_source_scope_id": "7",
    }
    path = tmp_path / "warehouse-product-scope.json"
    path.write_text(json.dumps(binding), encoding="utf8")
    read = MagicMock(return_value={"sku_ids": ["29"]})
    monkeypatch.setattr("app.production.identity.warehouse_product_scope", read)
    assert (
        configured_warehouse_product_scope(
            settings, context, engine, {"id": "24", "type": "FACTORY"}
        )
        is None
    )
    context.site_id = 2
    assert (
        configured_warehouse_product_scope(
            settings, context, engine, {"id": "23", "type": "FACTORY"}
        )
        is None
    )
    read.assert_not_called()
    context.site_id = 1
    with pytest.raises(ApiError):
        configured_warehouse_product_scope(
            settings, context, engine, {"id": "23", "type": "FBA"}
        )
    assert configured_warehouse_product_scope(
        settings, context, engine, {"id": "23", "type": "FACTORY"}
    ) == {"sku_ids": ["29"]}
    read.assert_called_once_with(
        engine, context, warehouse_id="23", report_source_scope_id=7
    )


def test_unready_publication_cannot_be_treated_as_an_approved_empty_shop() -> None:
    engine: Any = MagicMock()
    rows = engine.connect.return_value.__enter__.return_value.execute.return_value
    context: Any = MagicMock(site_id=1)
    for missing in ([], [{"current_catalog_version_id": None}]):
        rows.mappings.return_value.all.return_value = missing
        with pytest.raises(ApiError):
            warehouse_product_scope(
                engine, context, warehouse_id="23", report_source_scope_id=7
            )
    rows.mappings.return_value.all.return_value = [
        {
            "current_catalog_version_id": 8,
            "catalog_publication_revision": 12,
            "sku_id": None,
        }
    ]
    scope = warehouse_product_scope(
        engine, context, warehouse_id="23", report_source_scope_id=7
    )
    assert scope["sku_ids"] == []
    assert scope["catalog_version"] == "8:12"
    assert scope["state"] == "ready"
