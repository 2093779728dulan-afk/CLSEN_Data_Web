import json
from datetime import date
from pathlib import Path
from types import SimpleNamespace
from typing import Any, cast
from unittest.mock import MagicMock

import pytest
from app.api.errors import ApiError
from app.production.inventory_overview import quantity
from app.production.inventory_sheet_source import (
    apply_source_row,
    directory_evidence,
    load_sheet_source,
    reconcile_source_catalog,
    source_facts,
)


def test_new_catalog_members_do_not_hide_unchanged_stock_source(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.production import inventory_overview as overview

    original: dict[str, Any] = {
        "sku_id": "10",
        "style_id": "1",
        "style_code": "TEST",
        "standard_color": "White",
        "standard_size": "S",
        "label": "TEST-White-S",
        "code": "TEST-White-S",
        "status": "active",
        "catalog_version": "1:1",
    }
    source: dict[str, Any] = {
        "catalog_version": "1:1",
        "digest": "0" * 64,
        "stocktaken_on": "2026-11-04",
        "catalog_identity_snapshot": {
            "catalog_version": "1:1",
            "members": {"10": original},
        },
        "resolved_scope": {
            "domestic": {
                "warehouse_id": "1",
                "owner_id": "1",
                "warehouse_name": "TEST",
                "owner_name": "TEST",
                "cutoff_on": "2026-11-04",
            },
            "fba": {
                "id": "2",
                "warehouse_id": "2",
                "owner_id": "1",
                "report_source_scope_id": "1",
                "cutoff_on": "2026-09-24",
                "catalog_version": "1:1",
            },
        },
        "stock_rows": {"10": {"units": "8", "records": [], "reason": "明确整数"}},
        "packing_rows": {},
        "pending_identities": {
            "source:pending": {
                **original,
                "sku_id": "source:pending",
                "style_id": "source:pending",
                "style_code": "TEST(盘点待核)",
                "status": "pending",
            }
        },
        "review": {},
    }
    current: dict[str, Any] = {
        "10": {**original, "catalog_version": "2:2"},
        "20": {
            **original,
            "sku_id": "20",
            "standard_size": "M",
            "catalog_version": "2:2",
        },
    }
    monkeypatch.setattr(overview, "load_sheet_source", lambda *_: source)
    monkeypatch.setattr(overview, "production_skus", lambda *_: current)
    monkeypatch.setattr(
        overview,
        "production_request",
        lambda *_: {
            "revision": "0",
            "style_ids": [],
            "sku_alert_settings": {},
            "can_manage": True,
        },
    )
    repository = MagicMock()
    repository.inventory_days.return_value = overview._unavailable_reports("TEST")
    monkeypatch.setattr(
        overview, "MySqlStyleAnalyticsRepository", lambda *_: repository
    )
    result: Any = overview.read_sheet(
        SimpleNamespace(production_inventory_source_root=""),
        SimpleNamespace(reporting_timezone="UTC", site_id=1, site_config_version_id=1),
        MagicMock(),
        {
            "as_of": "2026-11-04",
            "domestic_warehouse_id": "1",
            "domestic_owner_id": "1",
            "fba_scope_id": "2",
        },
    )
    assert len(result["rows"]) == 2
    assert (
        next(row for row in result["rows"] if row["sku_id"] == "10")["values"][
            "domestic"
        ]["value"]
        == "8"
    )
    assert result["catalog_version"] == ["2:2"]
    assert source["catalog_version"] == "1:1"
    assert all(not row["sku_id"].startswith("source:") for row in result["rows"])
    assert result["display_styles"] == [
        {"id": "1", "style_code": "TEST", "sku_count": 2}
    ]
    assert result["settings"]["can_manage_styles"] is True
    assert result["settings"]["can_manage"] is False


def test_dispatch_evidence_preserves_unknown_stock() -> None:
    source: dict[str, Any] = {
        "stocktaken_on": "2026-11-04",
        "stock_rows": {},
        "packing_rows": {"1": [{"units": "8", "batch_date": "2026-09-24"}]},
        "shipping_confirmation": {"confirmed": True},
        "fba_batch_rows": {
            "1": [
                {
                    "batch_date": "2026-09-24",
                    "packed_units": "8",
                    "reference": "TEST",
                    "receipts": [
                        {"date": "2026-10-22", "units": "8"},
                        {"date": "2026-10-25", "units": "-1"},
                    ],
                }
            ]
        },
    }
    values: dict[str, Any] = {}
    records: dict[str, Any] = {}
    apply_source_row(source, "1", date(2026, 11, 4), values, records)
    assert values["available"]["value"] is None
    assert values["available"]["evidence"] == {"label": "接收累计", "units": "7"}
    assert values["transit"]["value"] is None
    assert values["transit"]["evidence"] == {"label": "待核接收", "units": "1"}
    assert values["dispatched"]["evidence"]["units"] == "8"
    assert records["source_fba"][0]["received_units"] == "7"
    assert [row["units"] for row in records["source_fba"][0]["receipts"]] == ["8", "-1"]
    apply_source_row(source, "1", date(2026, 10, 23), values, records)
    assert values["available"]["evidence"]["units"] == "8"
    assert values["transit"]["evidence"]["units"] == "0"


@pytest.mark.parametrize(
    "field", ["standard_size", "standard_color", "style_id", "removed"]
)
def test_changed_identity_only_moves_affected_source_to_pending(field: str) -> None:
    original: dict[str, Any] = {
        "sku_id": "10",
        "style_id": "1",
        "style_code": "TEST",
        "standard_color": "White",
        "standard_size": "S",
        "label": "TEST-White-S",
        "code": "TEST-White-S",
        "catalog_version": "1:1",
    }
    other: dict[str, Any] = {**original, "sku_id": "20", "standard_size": "M"}
    source: dict[str, Any] = {
        "catalog_version": "1:1",
        "catalog_identity_snapshot": {
            "catalog_version": "1:1",
            "members": {"10": original, "20": other},
        },
        "resolved_scope": {"fba": {"catalog_version": "1:1"}},
        "stock_rows": {
            "10": {"units": "8", "records": []},
            "20": {"units": "2", "records": []},
        },
        "packing_rows": {},
        "pending_identities": {},
        "review": {"stock_matched_units": "10", "stock_pending_units": "0"},
    }
    current: dict[str, Any] = {
        "10": {**original, field: "changed", "catalog_version": "2:2"},
        "20": {**other, "catalog_version": "2:2"},
    }
    if field == "removed":
        current.pop("10")
    result: Any = reconcile_source_catalog(source, current)
    assert result["stock_rows"]["20"]["units"] == "2"
    assert "10" not in result["stock_rows"]
    assert result["stock_rows"]["source:catalog:10"]["identity_pending"] is True
    assert result["review"]["stock_matched_units"] == "2"
    assert result["review"]["stock_pending_units"] == "8"
    assert result["pending_identities"]["source:catalog:10"]["catalog_version"] == "2:2"
    assert source["stock_rows"]["10"]["units"] == "8"


def test_catalog_refresh_requires_proof_for_previously_bound_skus() -> None:
    source: dict[str, Any] = {
        "catalog_version": "1:1",
        "stock_rows": {"10": {}},
        "packing_rows": {},
    }
    with pytest.raises(ApiError):
        reconcile_source_catalog(source, {"10": {"catalog_version": "2:2"}})


def test_guangzhou_stocktake_preserves_unknown_cells_and_original_references() -> None:
    from io import BytesIO

    from app.production.inventory_snapshot import parse_inventory, warehouse_1_view
    from openpyxl import Workbook  # type: ignore[import-untyped]

    book = Workbook()
    sheet = book.active
    sheet.title = "库存"
    sheet.append([None, None, "数量"])
    sheet.append(
        ["新款号", "COLOR", "XS", "S", "M", "L", "XL", "XXL", "3XL", "合计", "库位"]
    )
    sheet.append(
        [1101, "White", 0, 7, None, "/", 2, None, None, "=SUM(C3:I3)", "广州成品仓"]
    )
    output = BytesIO()
    book.save(output)
    result: Any = warehouse_1_view(parse_inventory(output.getvalue()), "SIZE_LITERALS")
    row = result["rows"][0]
    assert row["source_key"] == "库存!3"
    assert row["quantities"]["XS"]["units"] == "0"
    assert row["quantities"]["S"]["units"] == "7"
    assert row["quantities"]["M"]["units"] is None
    assert row["quantities"]["L"]["raw"] == "/"
    assert result["summary"]["literal_units"] == "9"
    assert result["summary"]["unknown_cells"] == 4
    sheet.cell(2, 4).value = "changed"
    output = BytesIO()
    book.save(output)
    with pytest.raises(ValueError, match="columns changed"):
        parse_inventory(output.getvalue())


def test_directory_evidence_requires_the_bound_warehouse_and_seller() -> None:
    source: dict[str, Any] = {
        "report_source_scope_id": "1",
        "stocktaken_on": "2026-11-04",
        "directory_evidence": {
            "bindings": {
                "domestic_warehouse_id": "1",
                "domestic_name": "广州成品仓",
                "fba_warehouse_id": "2",
            },
            "domestic": {"explicit_units": "12"},
            "fba": {"receipts": [{"units": "-1"}]},
        },
    }
    assert directory_evidence(source, {"id": "3"}) is None
    assert directory_evidence(None, {"id": "2"}) is None
    assert (
        cast(
            dict[str, Any],
            directory_evidence(
                source, {"id": "1", "type": "FACTORY", "name": "广州成品仓"}
            ),
        )["explicit_units"]
        == "12"
    )
    fba: dict[str, Any] = {
        "id": "2",
        "type": "FBA",
        "seller_account": "scope:1",
        "marketplace": "US",
    }
    assert (
        cast(dict[str, Any], directory_evidence(source, fba))["receipts"][0]["units"]
        == "-1"
    )
    with pytest.raises(ApiError):
        directory_evidence(source, {**fba, "seller_account": "scope:2"})


def test_snapshot_keeps_zero_unknown_and_unmapped_quantity_distinct() -> None:
    source: dict[str, Any] = {
        "stocktaken_on": "2026-11-04",
        "stock_rows": {
            "1": {"units": "0", "records": [], "reason": "明确0"},
            "2": {"units": None, "records": [], "reason": "原表空白"},
            "source:3": {
                "units": "7",
                "records": [],
                "reason": "待核",
                "identity_pending": True,
            },
        },
        "packing_rows": {"1": [{"units": "10", "batch_date": "2026-10-02"}]},
    }
    values: dict[str, Any] = {"domestic": quantity("999"), "units": quantity("1")}
    apply_source_row(source, "1", date(2026, 11, 4), values, {})
    assert values["domestic"]["value"] == "0"
    assert values["fba"]["value"] is None
    assert values["dispatched"]["value"] is None
    assert values["dispatched"]["known_units"] == "10"
    apply_source_row(source, "2", date(2026, 11, 4), values, {})
    assert values["domestic"]["value"] is None
    apply_source_row(source, "source:3", date(2026, 11, 4), values, {})
    assert values["domestic"]["known_units"] == "7"
    assert values["units"]["value"] is None
    apply_source_row(source, "1", date(2026, 11, 5), values, {})
    assert values["domestic"]["value"] is None
    assert values["domestic"]["state"] == "history_unavailable"


def test_confirmed_fba_ledger_is_not_overwritten_by_source_evidence() -> None:
    source: dict[str, Any] = {
        "stocktaken_on": "2026-11-04",
        "stock_rows": {},
        "packing_rows": {},
        "fba_ledger": {"scope_id": "2"},
    }
    values: dict[str, Any] = {
        "available": quantity("40"),
        "fba": quantity("42"),
        "unsellable": quantity("2"),
    }
    apply_source_row(source, "1", date(2026, 11, 4), values, {})
    assert values["available"]["value"] == "40"
    assert values["fba"]["value"] == "42"
    assert values["unsellable"]["value"] == "2"


def test_source_scope_must_match_the_selected_evidence() -> None:
    source: dict[str, Any] = {
        "resolved_scope": {
            "domestic": {"warehouse_id": "source-warehouse", "owner_id": "pending"},
            "fba": {"id": "source-fba"},
        }
    }
    query: dict[str, Any] = {
        "domestic_warehouse_id": "source-warehouse",
        "domestic_owner_id": "pending",
        "fba_scope_id": "source-fba",
    }
    assert source_facts(source, query)["report_scope_count"] == 1
    with pytest.raises(ApiError):
        source_facts(source, {**query, "fba_scope_id": "1"})


@pytest.mark.parametrize(
    "site,database", [(2, "clsen_data_test_real"), (1, "clsen_data")]
)
def test_real_source_cannot_cross_site_or_ordinary_database(
    tmp_path: Path, site: int, database: str
) -> None:
    payload: dict[str, Any] = {
        "schema": "inventory-sheet-source-v1",
        "site_id": "1",
        "database": "clsen_data_test_real",
    }
    (tmp_path / "inventory-sheet-source.json").write_text(
        json.dumps(payload), encoding="utf8"
    )
    engine = MagicMock()
    engine.url.database = database
    with pytest.raises(ApiError):
        load_sheet_source(
            cast(Any, SimpleNamespace(production_inventory_source_root=str(tmp_path))),
            cast(Any, SimpleNamespace(site_id=site)),
            engine,
        )
    engine.connect.assert_not_called()
