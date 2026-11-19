import copy
import json
from datetime import date
from pathlib import Path
from types import SimpleNamespace
from typing import Any, cast

import pytest
from app.api.errors import ApiError
from app.production.inventory_workbook_metrics import (
    load_workbook_metrics,
    merge_workbook_reports,
    workbook_adjustments,
    workbook_quantity,
)


@pytest.fixture
def loaded(tmp_path: Path) -> Any:
    identity = dict(
        style_id="8", style_code="TEST", standard_color="Navy", standard_size="M"
    )
    source: dict[str, Any] = {
        "schema": "inventory-metric-source-v1",
        "database": "clsen_data_test_metrics",
        "site_id": "1",
        "scope": dict(
            id="1", warehouse_id="2", owner_id="1", report_source_scope_id="1"
        ),
        "source_filename": "manual.xlsx",
        "source_sha256": "source-hash",
        "sheet": "GZ总数据",
        "cutoff_on": "2026-11-14",
        "source_kind": "manual_workbook",
        "calendar": {
            "units": ["2026-11-13", "2026-11-14"],
            "returns": ["2026-11-13", "2026-11-14"],
        },
        "rows": {
            "1": {
                "identity": identity,
                "daily": {
                    "2026-11-13": {"units": 3, "returns": 1},
                    "2026-11-14": {"units": 2, "returns": 0},
                },
                "adjustments": {"removed": -2},
                "adjustment_records": [
                    {
                        "metric": "removed",
                        "units": "-2",
                        "cell": "ALR5",
                        "heading": "移除订单",
                    }
                ],
            }
        },
    }
    (tmp_path / "inventory-metric-source.json").write_text(
        json.dumps(source), encoding="utf-8"
    )
    settings: Any = SimpleNamespace(production_inventory_source_root=tmp_path)
    context: Any = SimpleNamespace(site_id=1)
    engine: Any = SimpleNamespace(
        url=SimpleNamespace(database="clsen_data_test_metrics")
    )
    catalog: dict[str, Any] = {
        "1": {**identity, "status": "active", "catalog_version": "51:51"}
    }
    return source, settings, context, engine, catalog


def load(args: Any) -> Any:
    source, settings, context, engine, catalog = args
    return load_workbook_metrics(settings, context, engine, catalog, source["scope"])


def reports() -> Any:
    return {
        "business": [
            {"sku_id": "1", "metric_date": "2026-11-13", "units": 99},
            {"sku_id": "2", "metric_date": "2026-11-13", "units": 7},
        ],
        "returns": [{"sku_id": "1", "metric_date": "2026-11-13", "returns": 40}],
        "provenance": {"published_version_ids": [10]},
        "members": [],
        "unresolved": [
            {"sku_id": "1", "metric_date": "2026-11-13", "unresolved_rows": 3}
        ],
        "read_from": "2026-11-13",
    }


def test_replaces_same_sku_day_without_adding_to_published_reports(loaded: Any) -> None:
    original = reports()
    before = copy.deepcopy(original)
    result = merge_workbook_reports(original, load(loaded), date(2026, 11, 13))
    assert result["business"] == [
        {"sku_id": "2", "metric_date": "2026-11-13", "units": 7},
        {"sku_id": "1", "metric_date": "2026-11-13", "units": 3},
    ]
    assert result["returns"] == [
        {"sku_id": "1", "metric_date": "2026-11-13", "returns": 1}
    ]
    assert result["unresolved"] == []
    assert result["provenance"]["published_version_ids"] == [10]
    assert result["provenance"]["manual_workbook"]["source_kind"] == "manual_workbook"
    assert original == before


def test_coverage_does_not_invent_dates_after_source_cutoff(loaded: Any) -> None:
    result = merge_workbook_reports(reports(), load(loaded), date(2026, 11, 16))
    days: dict[tuple[str, str], dict[str, int]] = {
        ("1", "2026-11-13"): {"units": 3, "returns": 1},
        ("1", "2026-11-14"): {"units": 2, "returns": 0},
    }
    span = dict(start="2026-11-13", end="2026-11-16")
    value = workbook_quantity(result, days, "1", span, "units")
    assert value is not None
    assert (
        value["value"],
        value["observed_days"],
        value["expected_days"],
        value["state"],
    ) == ("5", 2, 4, "partial")
    assert (
        cast(dict[str, Any], workbook_quantity(result, days, "1", span, "returns"))[
            "state"
        ]
        == "indeterminate"
    )
    assert workbook_quantity(result, days, "2", span, "units") is None


def test_current_platform_conflict_remains_blocking(loaded: Any) -> None:
    result = merge_workbook_reports(reports(), load(loaded), date(2026, 11, 14))
    result["blocked_sku_ids"] = ["1"]
    assert (
        workbook_quantity(
            result, {}, "1", dict(start="2026-11-13", end="2026-11-14"), "units"
        )
        is None
    )


def test_adjustment_snapshot_is_not_backdated_and_preserves_source_cells(
    loaded: Any,
) -> None:
    source = load(loaded)
    values: dict[str, Any] = {"removed": "not-connected"}
    records: dict[str, Any] = {}
    workbook_adjustments(source, "1", date(2026, 11, 13), values, records)
    assert values == {"removed": "not-connected"}
    workbook_adjustments(source, "1", date(2026, 11, 14), values, records)
    assert values["removed"]["value"] == "-2"
    assert records["workbook_adjustments"][0]["cell"] == "ALR5"


def test_catalog_revision_can_advance_without_rebinding_stable_identity(
    loaded: Any,
) -> None:
    assert load(loaded)["rows"]["1"]["identity"]["standard_size"] == "M"
    loaded[-1]["1"]["standard_size"] = "L"
    with pytest.raises(ApiError):
        load(loaded)


def test_scope_and_database_boundaries(loaded: Any) -> None:
    source, settings, context, engine, catalog = loaded
    assert (
        load_workbook_metrics(
            settings, context, engine, catalog, {**source["scope"], "owner_id": "9"}
        )
        is None
    )
    engine.url.database = "real_business"
    with pytest.raises(ApiError):
        load(loaded)


def test_absent_source_keeps_original_reads(tmp_path: Path) -> None:
    settings: Any = SimpleNamespace(production_inventory_source_root=tmp_path)
    assert load_workbook_metrics(settings, None, None, {}, {}) is None
    original = reports()
    assert merge_workbook_reports(original, None, date(2026, 11, 14)) is original


def test_source_cutoff_excludes_later_workbook_cells_even_when_viewing_today(
    loaded: Any,
) -> None:
    source, settings, *_ = loaded
    source["calendar"]["units"].append("2026-11-15")
    source["rows"]["1"]["daily"]["2026-11-15"] = {"units": 10, "returns": 0}
    (
        settings.production_inventory_source_root / "inventory-metric-source.json"
    ).write_text(json.dumps(source), encoding="utf-8")
    result = merge_workbook_reports(reports(), load(loaded), date(2026, 11, 17))
    assert not any(str(r["metric_date"]) == "2026-11-15" for r in result["business"])
