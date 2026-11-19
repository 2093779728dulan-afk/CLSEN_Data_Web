from copy import deepcopy
from io import BytesIO
from typing import Any, cast

import openpyxl  # type: ignore[import-untyped]
import pytest
from app.api.errors import ApiError
from app.production.fba_reconciliation import (
    export_reconciliation,
    inventory_view,
    reconcile,
)


def test_day_precision_manual_receipt_keeps_stock_and_defers_same_day_snapshot() -> (
    None
):
    state = fixture()
    receipt = state["events"][0]
    receipt.update(
        occurred_at=None,
        occurred_local="2026-10-28",
        business_date="2026-10-28",
        time_precision="DAY",
        source_kind="MANUAL",
    )
    state["actions"].append(
        {
            "id": "3",
            "scope_id": "1",
            "kind": "OBSERVATION",
            "status": "POSTED",
            "occurred_at": "2026-10-28T12:00:00-07:00",
            "payload": {
                "reason": "SIM observation",
                "lines": [
                    {
                        "sku_id": "4",
                        "sellable": "15",
                        "unsellable": "1",
                        "reserved": "0",
                        "held": "0",
                    }
                ],
            },
        }
    )
    result = reconcile(state, "1")
    assert result["rows"][0]["receipt_net"] == "18"
    assert result["rows"][0]["observation"] is None
    assert result["rows"][0]["observation_precision_pending"]
    view = inventory_view(state, "1", result)
    assert any(item["id"] == "precision:4" for item in view["issues"])
    assert any(item["occurred_at"] == "2026-10-28" for item in view["movements"])


def fixture() -> Any:
    return {
        "scopes": [
            {
                "id": "1",
                "warehouse_id": "2",
                "owner_id": "3",
                "seller_account": "SIM",
                "marketplace": "amazon_us",
                "catalog_version": "1:1",
                "cutoff_on": "2026-09-30",
                "opening_basis": "SIMULATED zero",
                "simulated": True,
            }
        ],
        "identities": [
            {
                "scope_id": "1",
                "sku_id": "4",
                "seller_sku": "=SIM-SKU",
                "asin": "SIM-AS",
                "fnsku": "SIM-FN",
                "tracked": False,
                "sellable": "15",
                "unsellable": "1",
                "pending_units": "0",
            }
        ],
        "stock": {
            "items": [
                {
                    "sku_id": "4",
                    "owner_id": "3",
                    "on_hand_units": "16",
                    "free_available_units": "15",
                    "reserved_units": "0",
                    "held_units": "0",
                }
            ]
        },
        "events": [
            {
                "id": "8",
                "scope_id": "1",
                "sku_id": "4",
                "units": "18",
                "occurred_at": "2026-10-25T17:00:00Z",
                "occurred_local": "2026-10-25T10:00:00-07:00",
                "event_key": "receipt",
                "batch_id": "1",
                "source_row": "2",
                "fulfillment_center": "SIM-FC",
                "correction_of": None,
                "evidence": "SIMULATED receipt",
            }
        ],
        "actions": [
            {
                "id": "1",
                "scope_id": "1",
                "kind": "FULFILLMENT",
                "status": "POSTED",
                "event_key": "physical",
                "occurred_at": "2026-10-27T21:00:00Z",
                "payload": {
                    "reason": "SIMULATED physical fulfillment",
                    "lines": [
                        {
                            "sku_id": "4",
                            "units": "3",
                            "source_event_ref": "SIM-1",
                            "customer_order_ref": "SIM-ORDER",
                        }
                    ],
                },
            },
            {
                "id": "2",
                "scope_id": "1",
                "kind": "RETURN",
                "status": "POSTED",
                "event_key": "return",
                "occurred_at": "2026-10-28T17:00:00Z",
                "payload": {
                    "reason": "SIMULATED physical return",
                    "lines": [{"sku_id": "4", "units": "1", "quality": "DEFECTIVE"}],
                },
            },
        ],
        "shipment_totals": [
            {"scope_id": "1", "shipped_units": "18", "received_units": "18"}
        ],
    }


def test_no_observation_keeps_unknown_and_preserves_untracked_balances() -> None:
    state = fixture()
    before = deepcopy(state)
    view = reconcile(state, "1")
    assert state == before
    assert view["unreceived_units"] == "0"
    assert view["rows"][0]["observation"] is None
    assert view["rows"][0]["expected_on_hand"] == "16"
    assert view["rows"][0]["stock_matches"] is True
    book = openpyxl.load_workbook(BytesIO(export_reconciliation(state, "1")))
    assert book["库存对账"]["B2"].value == "=SIM-SKU"
    assert book["库存对账"]["B2"].data_type == "s"
    headers = [cell.value for cell in book["库存对账"][1]]
    assert book["库存对账"].cell(2, headers.index("观察时点") + 1).value == "未知"
    assert book["库存对账"]["E2"].value == "未跟踪"
    assert book["履约与实物退回"].max_row == 3
    book.close()


def test_quality_transfers_are_included_in_historical_platform_comparison() -> None:
    state = fixture()
    state["quality_events"] = [
        {
            "scope_id": "1",
            "sku_id": "4",
            "quality": "QUALIFIED",
            "units": "-2",
            "occurred_at": "2026-10-28T18:00:00Z",
        },
        {
            "scope_id": "1",
            "sku_id": "4",
            "quality": "DEFECTIVE",
            "units": "2",
            "occurred_at": "2026-10-28T18:00:00Z",
        },
    ]
    state["actions"].append(
        {
            "id": "3",
            "scope_id": "1",
            "kind": "OBSERVATION",
            "status": "POSTED",
            "occurred_at": "2026-10-28T19:00:00Z",
            "payload": {
                "reason": "SIM comparison after quality update",
                "lines": [
                    {
                        "sku_id": "4",
                        "sellable": "13",
                        "unsellable": "3",
                        "reserved": "0",
                        "held": "0",
                    }
                ],
            },
        }
    )
    comparison = reconcile(state, "1")["rows"][0]["observation"]
    assert comparison["book_sellable"] == "13"
    assert comparison["book_unsellable"] == "3"
    assert comparison["sellable_difference"] == "0"
    assert comparison["unsellable_difference"] == "0"


def test_snapshot_compares_at_its_cutoff_and_latest_time_beats_upload_order() -> None:
    state = fixture()
    for identifier, stamp, sellable in [
        ("3", "2026-10-27T22:00:00Z", "14"),
        ("4", "2026-10-26T22:00:00Z", "18"),
    ]:
        state["actions"].insert(
            0,
            {
                "id": identifier,
                "scope_id": "1",
                "kind": "OBSERVATION",
                "status": "POSTED",
                "occurred_at": stamp,
                "payload": {
                    "reason": "SIMULATED observation only",
                    "lines": [
                        {
                            "sku_id": "4",
                            "sellable": sellable,
                            "reserved": "1",
                            "unsellable": "0",
                            "held": "0",
                        }
                    ],
                },
            },
        )
    before = deepcopy(state)
    row = reconcile(state, "1")["rows"][0]
    assert state == before
    assert row["observation"]["book_sellable"] == "15"
    assert row["observation"]["book_unsellable"] == "0"
    assert row["observation"]["sellable_difference"] == "-1"
    assert row["observation"]["occurred_at"] == "2026-10-27T22:00:00Z"
    assert row["on_hand"] == "16"


def test_other_scope_cannot_be_exported_by_a_naked_identifier() -> None:
    with pytest.raises(ApiError) as error:
        export_reconciliation(fixture(), "999")
    assert error.value.status_code == 404


def test_inventory_view_groups_confirmed_stock_and_explains_sales_and_returns() -> None:
    state = fixture()
    state["identities"][0]["unassessed_units"] = "0"
    before = deepcopy(state)
    view = inventory_view(state, "1", reconcile(state, "1"))
    assert state == before
    assert view["stock_effect"] is False
    assert view["on_hand"] == "16"
    assert view["available"] == "15"
    assert view["groups"][0]["items"][0]["fulfilled"] == "3"
    assert view["groups"][0]["items"][0]["returned"] == "1"
    assert [m["units"] for m in view["movements"]] == ["1", "-3", "18"]
    assert view["movements"][0]["quality"] == "DEFECTIVE"
    assert view["issues"] == []


def test_inventory_view_preserves_unknown_zero_and_other_owner_boundaries() -> None:
    state = fixture()
    state["stock"]["items"].insert(
        0, {**state["stock"]["items"][0], "owner_id": "999", "on_hand_units": "900"}
    )
    state["stock"]["items"][1]["on_hand_units"] = None
    view = inventory_view(state, "1", reconcile(state, "1"))
    assert view["on_hand"] is None
    assert view["groups"][0]["on_hand"] is None
    assert "库存数量待核" in [i["label"] for i in view["issues"]]
    state["stock"]["items"][1]["on_hand_units"] = "0"
    assert inventory_view(state, "1", reconcile(state, "1"))["on_hand"] == "0"


def test_inventory_view_excludes_reversed_actions_and_other_scopes() -> None:
    state = fixture()
    state["actions"][0]["status"] = "REVERSED"
    state["actions"].append({**state["actions"][1], "scope_id": "999", "id": "999"})
    state["batches"] = [
        {"id": str(i), "scope_id": scope, "status": status}
        for i, scope, status in [
            (1, "1", "DRAFT"),
            (2, "1", "PARTIAL"),
            (3, "999", "DRAFT"),
            (4, "1", "POSTED"),
        ]
    ]
    view = inventory_view(state, "1", reconcile(state, "1"))
    assert len(view["movements"]) == 2
    assert not any(m["kind"] == "FULFILLMENT" for m in view["movements"])
    assert [i["batch_id"] for i in view["issues"] if i.get("batch_id")] == ["1", "2"]


def test_state_endpoint_exposes_the_scoped_read_only_inventory_view(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from types import SimpleNamespace
    from unittest.mock import MagicMock

    from app.api import production_fba

    source: dict[str, Any] = {**fixture(), "initialized": True}
    monkeypatch.setattr(production_fba, "read", lambda *args: source)
    monkeypatch.setattr(production_fba, "load_reports", lambda *args: [])
    result = production_fba.state(
        cast(Any, None), cast(Any, SimpleNamespace(site_id=1)), 2, MagicMock()
    )
    assert result["inventory_view"]["1"]["on_hand"] == "16"
    assert result["inventory_view"]["1"]["stock_effect"] is False
    assert result["reconciliation"]["1"]["rows"][0]["fulfilled"] == "3"


def test_report_sales_movements_use_report_day_and_do_not_show_zero_markers() -> None:
    state = fixture()
    sale = state["actions"][0]
    sale["occurred_at"] = "2026-10-30T06:59:59Z"
    sale["payload"].update(
        report_sales_key="report-sales:2026-10-29:4",
        report_sales={
            "business_date": "2026-10-29",
            "occurred_at": "2026-10-29T23:59:59-07:00",
        },
    )
    zero = deepcopy(sale)
    zero["id"] = "3"
    zero["payload"]["lines"][0]["units"] = "0"
    state["actions"].append(zero)
    view = inventory_view(state, "1", reconcile(state, "1"))
    sales = [item for item in view["movements"] if item["kind"] == "FULFILLMENT"]
    assert len(sales) == 1
    assert sales[0]["occurred_at"] == "2026-10-29T23:59:59-07:00"


def count_fixture() -> Any:
    state = fixture()
    state["stocktakes"] = [
        {
            "id": "90",
            "document_id": "12",
            "scope_id": "1",
            "sku_id": "4",
            "quality": "QUALIFIED",
            "units": "5",
            "business_date": "2026-10-29",
            "reason": "SIMULATED count",
        }
    ]
    state["stock"]["items"][0].update(on_hand_units="21", free_available_units="20")
    state["identities"][0]["sellable"] = "20"
    return state


def test_count_reconciles_without_creating_receipts_and_exports_its_own_evidence() -> (
    None
):
    state = count_fixture()
    before = deepcopy(state)
    result = reconcile(state, "1")
    row = result["rows"][0]
    assert (
        row["receipt_net"],
        row["counted"],
        row["expected_on_hand"],
        row["stock_matches"],
    ) == ("18", "5", "21", True)
    movements = inventory_view(state, "1", result)["movements"]
    count = next(m for m in movements if m["kind"] == "COUNT")
    assert (count["units"], count["reason"], count["time_precision"]) == (
        "5",
        "SIMULATED count",
        "date",
    )
    assert len([m for m in movements if m["kind"] == "RECEIPT"]) == 1
    book = openpyxl.load_workbook(BytesIO(export_reconciliation(state, "1")))
    headers = [c.value for c in book["库存对账"][1]]
    assert book["库存对账"].cell(2, headers.index("盘点调整件数") + 1).value == "5"
    assert book["盘点调整"]["F2"].value == "5"
    assert book["接收事件"].max_row == 2
    book.close()
    assert state == before


@pytest.mark.parametrize(
    "observed_date,pending,book_sellable",
    [("2026-10-29", True, None), ("2026-10-30", False, "20")],
)
def test_count_date_precision_defers_same_day_observation(
    observed_date: Any, pending: Any, book_sellable: Any
) -> None:
    state = count_fixture()
    state["actions"].append(
        {
            "id": "3",
            "scope_id": "1",
            "kind": "OBSERVATION",
            "status": "POSTED",
            "occurred_at": observed_date + "T12:00:00-07:00",
            "payload": {
                "reason": "SIM observation",
                "lines": [
                    {
                        "sku_id": "4",
                        "sellable": "20",
                        "unsellable": "1",
                        "reserved": "0",
                        "held": "0",
                    }
                ],
            },
        }
    )
    row = reconcile(state, "1")["rows"][0]
    assert row["observation_precision_pending"] is pending
    if pending:
        assert row["observation"] is None
    else:
        assert row["observation"]["book_sellable"] == book_sellable
        assert row["observation"]["sellable_difference"] == "0"


@pytest.mark.parametrize("role", ["viewer", "admin", "data_manager"])
def test_stocktake_requires_manager_and_current_shop_membership(
    monkeypatch: pytest.MonkeyPatch, role: Any
) -> None:
    from types import SimpleNamespace
    from unittest.mock import Mock
    from uuid import uuid4

    from app.api import production_fba

    context: Any = SimpleNamespace(principal_roles=frozenset([role]), site_id=1)
    request: Any = SimpleNamespace(
        app=SimpleNamespace(state=SimpleNamespace(settings=object()))
    )
    send = Mock(return_value={"accepted": True})
    monkeypatch.setattr(production_fba, "production_skus", lambda *args: {"4": {}})
    monkeypatch.setattr(
        production_fba, "catalog_for_report_scope", lambda *args: {"4": {}}
    )
    monkeypatch.setattr(
        production_fba, "read", lambda *args: {"report_source_scope_id": "1"}
    )
    monkeypatch.setattr(production_fba, "send", send)
    body: dict[str, Any] = {"scope_id": "1", "lines": [{"sku_id": "999", "units": "5"}]}
    with pytest.raises(ApiError) as error:
        production_fba.command(
            "stocktake", request, context, cast(Any, object()), body, uuid4()
        )
    assert error.value.status_code == (403 if role == "viewer" else 409)
    send.assert_not_called()
    if role != "viewer":
        body["lines"][0]["sku_id"] = "4"
        assert production_fba.command(
            "stocktake", request, context, cast(Any, object()), body, uuid4()
        ) == {"accepted": True}
        send.assert_called_once()
