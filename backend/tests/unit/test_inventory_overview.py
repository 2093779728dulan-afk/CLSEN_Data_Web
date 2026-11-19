from __future__ import annotations

from datetime import date
from io import BytesIO
from typing import Any

import pytest
from app.production.inventory_overview import (
    _effective_events,
    _historical_stock,
    _net,
    _production,
    _report_coverage,
    _report_quantity,
    periods,
    quantity,
    sheet_details,
    sheet_summary,
    sheet_workbook,
    sum_quantities,
)
from openpyxl import load_workbook  # type: ignore[import-untyped]


def test_prepared_sku_periods_preserve_missing_and_return_review_semantics() -> None:
    report: dict[str, Any] = {
        "state": "ready",
        "members": [
            {"report_type": kind, "report_date": day, "report_status": status}
            for kind in ("business_report", "return_report")
            for day, status in [
                ("2025-12-31", "published"),
                ("2026-01-01", "published"),
                ("2026-01-02", "withdrawn"),
            ]
        ],
        "unresolved": [
            {"sku_id": "20", "metric_date": "2026-01-01", "unresolved_rows": 1}
        ],
    }
    days: dict[tuple[str, str], dict[str, int]] = {
        ("20", "2025-12-31"): {"units": 3, "returns": 1},
        ("20", "2026-01-01"): {"units": 5, "returns": 2},
        ("21", "2026-01-01"): {"units": 90, "returns": 40},
    }
    for start, end in [("2025-12-31", "2026-01-01"), ("2026-01-02", "2026-01-02")]:
        span: dict[str, Any] = {"start": start, "end": end}
        for sku in ("20", "21", "22"):
            scoped: dict[str, Any] = {
                **report,
                "unresolved": [r for r in report["unresolved"] if r["sku_id"] == sku],
            }
            sku_days = {key: value for key, value in days.items() if key[0] == sku}
            for metric in ("units", "returns"):
                assert _report_quantity(
                    scoped,
                    sku_days,
                    sku,
                    span,
                    metric,
                    coverage=_report_coverage(report, span, metric),
                ) == _report_quantity(report, days, sku, span, metric)


def test_summary_preserves_quantities_states_and_version_without_detail_payload() -> (
    None
):
    original: dict[str, Any] = {
        "version": "same-source-version",
        "totals": {"available": quantity("454")},
        "rows": [
            {
                "sku_id": "20",
                "values": {"available": quantity(state="not_ready")},
                "records": {"stock": [{"id": "123"}]},
                "stock_explanation": {"fba": {}},
                "history_from": {"fba": "2026-09-23"},
            }
        ],
        "daily_rows": [{"sku_id": "20", "date": "2026-10-01"}],
    }
    result = sheet_summary(original)
    assert result["version"] == original["version"]
    assert result["totals"] == original["totals"]
    assert result["rows"][0]["values"] == original["rows"][0]["values"]
    assert "records" not in result["rows"][0] and "daily_rows" not in result
    assert original["rows"][0]["records"] and original["daily_rows"]


def test_compact_summary_preserves_quantities_and_source_metadata() -> None:
    values: dict[str, Any] = {
        "zero": quantity("0"),
        "missing": quantity(state="missing_report", reason="missing report"),
        "large": quantity("9007199254740993"),
        "partial": {
            **quantity("12", "partial", reason="partial report"),
            "evidence": {"label": "source", "units": "15"},
        },
    }
    original: dict[str, Any] = {
        "version": "unchanged",
        "rows": [{"sku_id": "1", "values": values}, {"sku_id": "2", "values": values}],
        "totals": values,
    }
    packed = sheet_summary(original, compact=True)
    assert len(packed["quantity_pool"]) == len(values)
    for row in packed["rows"]:
        assert {
            key: packed["quantity_pool"][index] for key, index in row["values"].items()
        } == values
    assert {
        key: packed["quantity_pool"][index] for key, index in packed["totals"].items()
    } == values
    assert packed["version"] == original["version"]
    assert original["rows"][0]["values"] == values


def production_facts() -> dict[str, Any]:
    return {
        "orders": [
            {
                "id": "1",
                "business_number": "FICTIONAL-100",
                "business_date": "2026-11-07",
                "revision": "3",
                "receipt_warehouse_id": "5",
                "receipt_owner_id": "1",
                "production_completion_state": "OPEN",
                "lines": [
                    {
                        "id": "10",
                        "sku_id": "20",
                        "expected_units": "100",
                        "produced_units": "60",
                        "received_units": "20",
                        "production_direct_units": "10",
                        "tracking_state": "OPEN",
                    }
                ],
            }
        ],
        "production_revisions": [],
        "stock_sources": [
            {
                "id": "2",
                "status": "POSTED",
                "kind": "IN",
                "business_date": "2026-11-08",
                "line_items": [
                    {
                        "purpose": "PRODUCTION_RECEIPT",
                        "production_allocations": [
                            {"order_line_id": "10", "units": "20"}
                        ],
                    }
                ],
            }
        ],
        "order_shipments": [
            {"order_line_id": "10", "units": "10", "business_date": "2026-11-08"}
        ],
    }


def test_manual_production_status_is_visible_in_details_without_changing_totals() -> (
    None
):
    facts = production_facts()
    facts["orders"][0]["lines"][0]["production_status"] = "车缝 · 缺料"
    values, records = _production(facts, "20", date(2026, 11, 8), date(2026, 11, 8))
    assert values["production.pending"]["value"] == "40"
    assert values["production.pendingReceipt"]["value"] == "30"
    assert records[0]["production_status"] == "车缝 · 缺料"
    sheet: dict[str, Any] = {
        "version": "labels-1",
        "report_provenance": {},
        "rows": [
            {
                "sku_id": "20",
                "style_id": "2",
                "sku": "QA-SKU",
                "values": values,
                "records": {"production": records},
                "stock_explanation": {"fba": {}},
                "production_statuses": [
                    {
                        "order_id": "1",
                        "order_number": "FICTIONAL-100",
                        "status": "车缝 · 缺料",
                    }
                ],
            }
        ],
    }
    grouped = sheet_details(sheet, {"metric": "production.pending", "style_id": "2"})
    assert grouped["columns"][-1] == "生产状态"
    assert grouped["rows"][0]["cells"][-1] == "车缝 · 缺料"
    detail = sheet_details(sheet, {"metric": "production.pending", "sku_id": "20"})
    assert detail["rows"][0]["cells"][-1] == "车缝 · 缺料"
    assert detail["total"]["value"] == "40"


def test_production_receipt_and_direct_are_each_deducted_once() -> None:
    facts = production_facts()
    values, records = _production(facts, "20", date(2026, 11, 9), date(2026, 11, 9))
    assert values["production.pending"]["value"] == "40"
    assert values["production.pendingReceipt"]["value"] == "30"
    assert records[0]["production.received"] == "20"
    assert records[0]["production_direct_units"] == "10"


def test_evidence_totals_preserve_unknown_actual_balance() -> None:
    values: list[Any] = [
        quantity(state="not_ready", evidence={"label": "接收累计", "units": "8"}),
        quantity(state="not_ready", evidence={"label": "接收累计", "units": "-1"}),
    ]
    total = sum_quantities(values)
    assert total["value"] is None
    assert total["evidence"] == {"label": "接收累计", "units": "7"}


def test_closing_preserves_produced_goods_and_unknown_is_not_zero() -> None:
    facts = production_facts()
    line = facts["orders"][0]["lines"][0]
    line["tracking_state"] = "CLOSED"
    line["closed_units"] = "90"
    values, _ = _production(facts, "20", date(2026, 11, 9), date(2026, 11, 9))
    assert values["production.pending"]["value"] == "0"
    assert values["production.pendingReceipt"]["value"] == "30"
    line["produced_units"] = None
    values, _ = _production(facts, "20", date(2026, 11, 9), date(2026, 11, 9))
    assert values["production.pendingReceipt"]["value"] is None
    assert values["production.completed"]["unknown_count"] == 1


def test_completed_balances_exit_without_writing_completion_decision() -> None:
    facts = production_facts()
    facts["orders"][0]["lines"][0]["produced_units"] = "100"
    facts["stock_sources"][0]["line_items"][0]["production_allocations"][0]["units"] = (
        "90"
    )
    values, records = _production(facts, "20", date(2026, 11, 9), date(2026, 11, 9))
    assert records == []
    assert values["production.ordered"]["value"] == "0"
    assert facts["orders"][0]["production_completion_state"] == "OPEN"


@pytest.mark.parametrize("today", [date(2026, 11, 12), date(2026, 11, 13)])
def test_today_stock_excludes_later_effective_dispatch_and_survives_rollover(
    today: date,
) -> None:
    scope: dict[str, Any] = {
        "warehouse_id": "5",
        "owner_id": "1",
        "cutoff_on": "2026-11-01",
    }
    stock: dict[str, Any] = {
        "items": [
            {
                "sku_id": "20",
                "owner_id": "1",
                "state": "ready",
                "on_hand_units": "8",
                "qualified_units": "8",
                "free_available_units": "8",
                "held_units": "0",
                "reserved_units": "0",
            }
        ]
    }
    base: dict[str, Any] = {
        "warehouse_id": "5",
        "owner_id": "1",
        "sku_id": "20",
        "quality": "QUALIFIED",
    }
    effective: list[Any] = [
        {**base, "business_date": "2026-11-12", "delta_units": "24"},
        {**base, "business_date": "2026-11-13", "delta_units": "-16"},
    ]
    values, records = _historical_stock(
        {"fba_state": {}},
        stock,
        scope,
        "20",
        date(2026, 11, 12),
        today,
        effective,
        set(),
    )
    assert values["on_hand_units"]["value"] == "24"
    assert values["free_available_units"]["value"] == "24"
    assert {r["business_date"] for r in records} == {"2026-11-12"}
    next_day, _ = _historical_stock(
        {"fba_state": {}},
        stock,
        scope,
        "20",
        date(2026, 11, 13),
        date(2026, 11, 13),
        effective,
        set(),
    )
    assert next_day["on_hand_units"]["value"] == "8"


def test_other_scope_future_event_keeps_today_occupancy_balance() -> None:
    values, _ = _historical_stock(
        {"fba_state": {}},
        {
            "items": [
                {
                    "sku_id": "20",
                    "owner_id": "1",
                    "state": "ready",
                    "on_hand_units": "8",
                    "free_available_units": "5",
                    "held_units": "3",
                }
            ]
        },
        {"warehouse_id": "5", "owner_id": "1", "cutoff_on": "2026-11-01"},
        "20",
        date(2026, 11, 12),
        date(2026, 11, 12),
        [
            {
                "warehouse_id": "6",
                "owner_id": "1",
                "sku_id": "20",
                "quality": "QUALIFIED",
                "business_date": "2026-11-13",
                "delta_units": "9",
            }
        ],
        set(),
    )
    assert values["free_available_units"]["value"] == "5"
    assert values["held_units"]["value"] == "3"


def test_stock_correction_moves_effective_contribution_across_days() -> None:
    base: dict[str, Any] = {
        "warehouse_id": "5",
        "owner_id": "1",
        "sku_id": "20",
        "quality": "QUALIFIED",
        "document_kind": "stock",
        "document_id": "2",
        "reason": "FICTIONAL",
    }
    facts: dict[str, Any] = {
        "events": [
            {
                **base,
                "id": "1",
                "revision": "2",
                "business_date": "2026-11-07",
                "delta_units": "10",
            },
            {
                **base,
                "id": "2",
                "revision": "3",
                "business_date": "2026-11-08",
                "delta_units": "-10",
            },
            {
                **base,
                "id": "3",
                "revision": "3",
                "business_date": "2026-11-08",
                "delta_units": "8",
            },
        ],
        "stock_sources": [{"id": "2", "business_date": "2026-11-08", "revision": "3"}],
        "shipment_sources": [],
        "identity_changes": [],
        "fba_state": {},
    }
    rows, unavailable = _effective_events(facts)
    assert not unavailable
    assert len(rows) == 1
    assert rows[0]["delta_units"] == "8"
    assert rows[0]["business_date"] == "2026-11-08"


@pytest.mark.parametrize("source_kind", ["REPORT", "MANUAL"])
def test_dated_receipt_correction_preserves_both_business_days(
    source_kind: str,
) -> None:
    facts: dict[str, Any] = {
        "stock_sources": [],
        "shipment_sources": [],
        "identity_changes": [],
        "events": [],
        "fba_state": {
            "scopes": [{"id": "1", "warehouse_id": "2", "owner_id": "1"}],
            "events": [],
        },
    }
    for event_id, day, units, parent in [
        ("10", "2026-10-22", "8", None),
        ("11", "2026-10-25", "-1", "10"),
    ]:
        facts["events"].append(
            {
                "document_kind": "fba_receipt",
                "document_id": event_id,
                "warehouse_id": "2",
                "owner_id": "1",
                "sku_id": "5",
                "business_date": day,
                "delta_units": units,
                "quality": "QUALIFIED",
            }
        )
        facts["fba_state"]["events"].append(
            {
                "id": event_id,
                "scope_id": "1",
                "sku_id": "5",
                "units": units,
                "source_kind": source_kind,
                "business_date": day,
                "time_precision": "TIMESTAMP",
                "occurred_at": day + "T07:00:00Z",
                "correction_of": parent,
            }
        )
    effective, unavailable = _effective_events(facts)
    assert not unavailable
    assert sum(int(row["delta_units"]) for row in effective) == 7
    assert (
        sum(
            int(row["delta_units"])
            for row in effective
            if row["business_date"] < "2026-10-25"
        )
        == 8
    )
    facts["fba_state"]["events"][0].pop("occurred_at")
    assert _effective_events(facts)[1] == {("2", "1", "5")}


def test_complete_calendar_periods_and_cross_year_week() -> None:
    result = periods(date(2026, 1, 1))
    assert result["week"]["current"] == {"start": "2025-12-29", "end": "2026-01-01"}
    assert result["month"]["current"] == {"start": "2025-12-01", "end": "2025-12-31"}
    assert result["quarter"]["previous"] == {"start": "2025-07-01", "end": "2025-09-30"}
    assert result["year"]["previous"] == {"start": "2024-01-01", "end": "2024-12-31"}


def test_missing_report_zero_and_event_date_completeness_are_distinct() -> None:
    reports: dict[str, Any] = {
        "state": "ready",
        "members": [
            {
                "report_type": "business_report",
                "report_date": "2026-11-08",
                "report_status": "published",
            },
            {
                "report_type": "return_report",
                "report_date": "2026-11-09",
                "report_status": "published",
            },
        ],
    }
    span: dict[str, Any] = {"start": "2026-11-08", "end": "2026-11-08"}
    units = _report_quantity(reports, {}, "20", span, "units")
    assert units["value"] == "0" and units["state"] == "ready"
    returns = _report_quantity(
        reports,
        {("20", "2026-11-08"): {"units": 0, "returns": 3}},
        "20",
        span,
        "returns",
    )
    net = _net(units, returns)
    assert net["value"] == "-3" and net["state"] == "indeterminate"
    reports["members"][0]["report_status"] = "missing"
    assert _report_quantity(reports, {}, "20", span, "units")["value"] is None


def test_partial_totals_keep_known_quantity_and_unknown_count() -> None:
    total = sum_quantities([quantity("9007199254740993"), quantity(state="not_ready")])
    assert total["value"] is None
    assert total["known_units"] == "9007199254740993"
    assert total["unknown_count"] == 1


def test_blocked_platform_identity_does_not_become_observed_zero() -> None:
    reports: dict[str, Any] = {
        "state": "ready",
        "blocked_sku_ids": ["20"],
        "members": [
            {
                "report_type": "business_report",
                "report_date": "2026-11-08",
                "report_status": "published",
            }
        ],
    }
    result = _report_quantity(
        reports, {}, "20", {"start": "2026-11-08", "end": "2026-11-08"}, "units"
    )
    assert result["value"] is None
    assert result["state"] == "identity_pending"


def test_explicit_fba_zero_history_and_other_warehouse_gap_are_separate() -> None:
    scope: dict[str, Any] = {
        "id": "1",
        "warehouse_id": "1",
        "owner_id": "1",
        "cutoff_on": "2026-10-01",
        "simulated": True,
    }
    facts: dict[str, Any] = {
        "fba_state": {"identities": [{"scope_id": "1", "sku_id": "20"}]}
    }
    stock: dict[str, Any] = {
        "items": [
            {"sku_id": "20", "owner_id": "1", "state": "ready", "on_hand_units": "0"}
        ]
    }
    values, _ = _historical_stock(
        facts,
        stock,
        scope,
        "20",
        date(2026, 10, 15),
        date(2026, 11, 9),
        [],
        {("5", "1", "20")},
    )
    assert values["on_hand_units"]["value"] == "0"
    assert values["on_hand_units"]["state"] == "ready"


def test_xlsx_preserves_large_integers_missing_state_and_literal_identifiers() -> None:
    values: dict[str, Any] = {
        "production.pending": quantity("9007199254740993"),
        "available": quantity("0"),
        "removed": quantity(state="not_connected", reason="无可靠来源"),
        "week.units": quantity(state="missing_report"),
        "week.previous.units": quantity("0"),
        "transit": quantity(
            state="unknown",
            reason="实际发出日期及后续验收待补",
            evidence={"label": "待核接收", "units": "152"},
        ),
        "dispatched": quantity(
            state="unknown",
            evidence={"label": "已发资料", "units": "601"},
        ),
    }
    sheet: dict[str, Any] = {
        "rows": [
            {
                "sku_id": "20",
                "style_id": "2",
                "style_code": "=STYLE",
                "sku": "=SKU",
                "values": values,
                "alert": {"level": "sold-out", "threshold": "20", "replenish": False},
            }
        ],
        "totals": values,
        "as_of": "2026-11-09",
        "cumulative_from": "2026-11-08",
        "periods": periods(date(2026, 11, 9)),
        "application_version": "1.1.0-SNAPSHOT",
        "version": "source-version",
        "reporting_timezone": "America/Los_Angeles",
        "filter": {},
        "resolved_scope": {},
        "catalog_version": ["8:8"],
        "report_provenance": {},
        "coverage": [],
        "settings": {"sku_alert_settings": {}},
    }
    raw = sheet_workbook(
        sheet,
        {
            "columns": (
                "production.pending,available,sku,removed,week.unitsMom,"
                "transit,dispatched"
            ),
            "expanded_styles": "2",
        },
    )
    book = load_workbook(BytesIO(raw))
    ws = book["库存变动总表"]
    assert ws.cell(5, 1).value == "9007199254740993"
    assert ws.cell(5, 3).value == "=SKU" and ws.cell(5, 3).data_type == "s"
    assert ws.cell(5, 4).comment and "无可靠来源" in ws.cell(5, 4).comment.text
    assert ws.cell(6, 1).value == ws.cell(5, 1).value
    assert ws.cell(5, 5).value is None
    assert ws.cell(5, 5).comment
    assert ws.cell(3, 6).value == "待核接收"
    assert ws.cell(3, 7).value == "装箱已发"
    assert ws.cell(5, 6).value == 152 and ws.cell(5, 6).data_type == "n"
    assert ws.cell(5, 7).value == 601 and ws.cell(5, 7).data_type == "n"
    assert ws.cell(5, 6).comment and "待补" in ws.cell(5, 6).comment.text
    assert ws.cell(5, 2).value == 0 and "售罄" not in ws.cell(5, 2).number_format


def test_catalog_missing_stock_defaults_zero_but_not_unavailable_history() -> None:
    scope: dict[str, Any] = {
        "warehouse_id": "5",
        "owner_id": "1",
        "cutoff_on": "2026-11-04",
    }
    args: tuple[Any, ...] = (
        {},
        {"items": []},
        scope,
        "20",
        date(2026, 11, 10),
        date(2026, 11, 10),
        [],
        set(),
    )
    values, records = _historical_stock(*args, catalog_default_zero=True)
    assert all(v["value"] == "0" and v["state"] == "ready" for v in values.values())
    assert records == []
    before, _ = _historical_stock(
        {},
        {"items": []},
        scope,
        "20",
        date(2026, 11, 3),
        date(2026, 11, 10),
        [],
        set(),
        catalog_default_zero=True,
    )
    assert before["on_hand_units"]["value"] is None
    assert before["on_hand_units"]["state"] == "history_unavailable"
    broken, _ = _historical_stock(
        {},
        {"items": []},
        scope,
        "20",
        date(2026, 11, 10),
        date(2026, 11, 10),
        [],
        {("5", "1", "20")},
        catalog_default_zero=True,
    )
    assert broken["on_hand_units"]["value"] is None
    unapproved, _ = _historical_stock(*args)
    assert unapproved["on_hand_units"]["value"] is None


def test_catalog_zero_does_not_replace_explicit_unknown_inventory() -> None:
    scope: dict[str, Any] = {
        "warehouse_id": "5",
        "owner_id": "1",
        "cutoff_on": "2026-11-04",
    }
    stock: dict[str, Any] = {
        "items": [
            {
                "sku_id": "20",
                "owner_id": "1",
                "state": "not_ready",
                "on_hand_units": None,
                "missing": "source could not be verified",
            }
        ]
    }
    values, _ = _historical_stock(
        {},
        stock,
        scope,
        "20",
        date(2026, 11, 10),
        date(2026, 11, 10),
        [],
        set(),
        catalog_default_zero=True,
    )
    assert values["on_hand_units"]["value"] is None
    assert values["on_hand_units"]["reason"] == "source could not be verified"


@pytest.mark.parametrize("sku_id", ["", "equal"])
def test_comparison_detail_shows_both_periods_and_filters_only_both_zero(
    sku_id: Any,
) -> None:
    rows: list[Any] = []
    for sku, now, prior in [
        ("zero", 0, 0),
        ("equal", 5, 5),
        ("up", 2, 0),
        ("down", 0, 1),
        ("unknown", None, 0),
    ]:
        rows.append(
            {
                "sku_id": sku,
                "style_id": "1",
                "sku": "SIM-" + sku,
                "values": {
                    "week.returns": quantity(now),
                    "week.previous.returns": quantity(prior),
                },
            }
        )
    rows.append(
        {
            "sku_id": "outside",
            "style_id": "2",
            "sku": "SIM-other-style",
            "values": {
                "week.returns": quantity(99),
                "week.previous.returns": quantity(99),
            },
        }
    )
    source: dict[str, Any] = {
        "version": "same-version",
        "rows": rows,
        "report_provenance": {},
    }
    query: dict[str, Any] = {
        "metric": "week.returnsMom",
        "style_id": "1",
        "page_size": "2",
    }
    if sku_id:
        query["sku_id"] = sku_id
    detail = sheet_details(source, query)
    assert detail["version"] == "same-version"
    assert detail["columns"] == ["SKU", "本期", "上期", "增减"]
    if sku_id:
        assert detail["grouped"] is False
        assert detail["rows"][0]["cells"] == ["SIM-equal", "5", "5", "0"]
        assert [q["value"] for q in detail["comparison_totals"]] == ["5", "5", "0"]
    else:
        assert detail["total_rows"] == 4
        assert [r["sku_id"] for r in detail["rows"]] == ["equal", "up"]
        second = sheet_details(source, {**query, "page": "2"})
        assert [r["sku_id"] for r in second["rows"]] == ["down", "unknown"]
        assert second["rows"][0]["cells"] == ["SIM-down", "0", "1", "-1"]
        assert second["rows"][1]["cells"] == ["SIM-unknown", None, "0", None]
        assert detail["comparison_totals"][0]["value"] is None
        assert detail["comparison_totals"][1]["value"] == "6"
        assert detail["comparison_totals"][2]["value"] is None
        assert second["comparison_totals"] == detail["comparison_totals"]
