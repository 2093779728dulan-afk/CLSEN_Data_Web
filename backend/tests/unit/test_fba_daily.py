from typing import Any

from app.production.fba_daily import report_projection
from app.production.fba_receipts import prepare_receipt_decisions

SCOPE: dict[str, Any] = {"id": "1", "cutoff_on": "2026-10-01"}
IDENTITIES: list[Any] = [
    {
        "scope_id": "1",
        "sku_id": "2",
        "seller_sku": "TEST-SKU",
        "tracked": True,
        "asin": "ASIN",
        "fnsku": "FN",
    }
]


def returned(**changes: Any) -> Any:
    return {
        "version_id": 1,
        "report_date": "2026-11-04",
        "source_row": 2,
        "report_type": "return_report",
        "sku": "TEST-SKU",
        "quantity": 1,
        "status": "Unit returned to inventory",
        "license_plate_number": "LPN1",
        "order_id": "ORDER1",
        "asin": "ASIN",
        "fnsku": "FN",
        "return_date": "2026-11-04T03:00:00-08:00",
        "detailed_disposition": "",
        **changes,
    }


def project(rows: Any, actions: Any = None) -> Any:
    return report_projection(rows, SCOPE, IDENTITIES, actions or [])


def test_returns_default_sellable_and_honor_explicit_damage_without_double_counting() -> (  # noqa: E501 -- Preserve the existing test identity.
    None
):
    row = returned()
    result = project([row, row])
    assert len(result["returns"]) == 1
    assert result["returns"][0]["quality"] == "QUALIFIED"
    changed = project([returned(detailed_disposition="CUSTOMER_DAMAGED")])
    assert changed["returns"][0]["quality"] == "DEFECTIVE"
    assert (
        changed["returns"][0]["source_event_ref"]
        == result["returns"][0]["source_event_ref"]
    )
    assert (
        project([returned(return_date="2026-11-04T11:00:00+00:00")])["returns"]
        == result["returns"]
    )


def test_conflicting_third_copy_cannot_reintroduce_return() -> None:
    result = project([returned(), returned(quantity=2), returned()])
    assert not result["returns"]
    assert len(result["issues"]) == 1


def test_return_requires_physical_evidence_identity_tracking_and_after_cutoff() -> None:
    changes: dict[str, Any]
    for changes in (
        {"status": "Pending"},
        {"license_plate_number": ""},
        {"asin": "WRONG"},
        {"fnsku": "WRONG"},
        {"sku": "test-sku"},
        {"detailed_disposition": "UNKNOWN"},
    ):
        result = project([returned(**changes)])
        assert not result["returns"] and result["issues"]
    assert not project([returned(return_date="2026-10-01T03:00:00-07:00")])["returns"]


def test_sales_totals_keep_report_basis_for_atomic_manual_offset() -> None:
    sale: dict[str, Any] = {
        "version_id": 3,
        "report_date": "2026-11-04",
        "source_row": 2,
        "report_type": "business_report",
        "sku": "TEST-SKU",
        "units_ordered": 20,
    }
    action: dict[str, Any] = {
        "scope_id": "1",
        "kind": "FULFILLMENT",
        "status": "POSTED",
        "occurred_at": "2026-11-04T11:00:00Z",
        "payload": {"lines": [{"sku_id": "2", "units": "6"}]},
    }
    result = project(
        [sale], [action, {**action, "scope_id": "9"}, {**action, "status": "REVERSED"}]
    )
    assert result["sales"] == [
        {
            "sku_id": "2",
            "report_units": "20",
            "business_date": "2026-11-04",
            "occurred_at": "2026-11-04T23:59:59-08:00",
            "report_version_ids": ["3"],
        }
    ]
    assert result["sales_units"] == "20"
    assert not result["returns"]


def test_prepare_reserves_later_manual_rows_and_keeps_ambiguous_rows_pending() -> None:
    row: dict[str, Any] = {
        "source_row": 2,
        "quantity": "6",
        "existing_candidates": [],
        "same_file_candidates": [],
        "bindings": [{"id": "3", "received_units": "0", "units": "10"}],
        "identity": {"tracked": True},
    }
    manual: dict[str, Any] = {
        "source_row": "3",
        "decision": "NEW",
        "allocations": [{"binding_id": "3", "units": "5"}],
    }
    batch: dict[str, Any] = {
        "id": "1",
        "resolved": [],
        "decisions": [manual],
        "rows": [row, {**row, "source_row": 3}],
        "issues": [],
    }
    assert prepare_receipt_decisions(batch) == [manual]
    batch["decisions"] = []
    result = prepare_receipt_decisions(batch)
    assert len(result) == 1 and result[0]["source_row"] == "2"
    changes: dict[str, Any]
    for changes in (
        {"quantity": "-1"},
        {"existing_candidates": [1]},
        {"same_file_candidates": [3]},
        {"bindings": []},
    ):
        assert not prepare_receipt_decisions({**batch, "rows": [{**row, **changes}]})


def test_return_reasons_preserve_raw_disposition_and_reject_conflicting_causes() -> (
    None
):
    for code in (
        "WAREHOUSE_DAMAGED",
        "CARRIER_DAMAGED",
        "DEFECTIVE",
        "CUSTOMER_DAMAGED",
    ):
        result = project([returned(detailed_disposition=code)])
        assert result["returns"][0]["reason_code"] == code
        assert result["returns"][0]["raw_disposition"] == code
    result = project([returned(detailed_disposition="EXPIRED")])
    assert result["returns"][0]["reason_code"] == "OTHER"
    assert result["returns"][0]["raw_disposition"] == "EXPIRED"
    result = project(
        [
            returned(detailed_disposition="DEFECTIVE"),
            returned(detailed_disposition="CUSTOMER_DAMAGED"),
        ]
    )
    assert not result["returns"] and result["issues"]


def test_sales_aggregate_daily_sku_and_keep_zero_for_report_corrections() -> None:
    sale: dict[str, Any] = {
        "version_id": 4,
        "report_date": "2026-11-04",
        "source_row": 2,
        "report_type": "business_report",
        "sku": "TEST-SKU",
        "units_ordered": 2,
    }
    result = project([sale, {**sale, "source_row": 3, "units_ordered": 3}])
    assert result["sales"][0]["report_units"] == "5"
    assert project([{**sale, "units_ordered": 0}])["sales"][0]["report_units"] == "0"
    invalid = project([{**sale, "units_ordered": -1}])
    assert not invalid["sales"] and invalid["issues"]


def test_sales_sync_pending_is_visible_without_preventing_withdrawal_reconciliation() -> (  # noqa: E501 -- Preserve the existing test identity.
    None
):
    sale: dict[str, Any] = {
        "version_id": 4,
        "report_date": "2026-11-04",
        "source_row": 2,
        "report_type": "business_report",
        "sku": "TEST-SKU",
        "units_ordered": 5,
    }
    action: dict[str, Any] = {
        "scope_id": "1",
        "kind": "FULFILLMENT",
        "status": "POSTED",
        "occurred_at": "2026-11-05T07:59:59Z",
        "payload": {
            "report_sales_key": "report-sales:2026-11-04:2",
            "lines": [{"sku_id": "2", "units": "5"}],
        },
    }
    assert project([sale])["sync_issues"]
    assert not project([sale], [action])["sync_issues"]
    withdrawn = project([], [action])
    assert withdrawn["sync_issues"] and not withdrawn["issues"]


def test_failed_return_update_and_withdrawal_are_visible_in_stock_status() -> None:
    row = returned()
    projection = project([row])
    assert projection["sync_issues"]
    line = projection["returns"][0]
    action: dict[str, Any] = {
        "scope_id": "1",
        "kind": "RETURN",
        "status": "POSTED",
        "occurred_at": line["occurred_at"],
        "payload": {"report_return_key": line["source_event_ref"], "lines": [line]},
    }
    assert not project([row], [action])["sync_issues"]
    assert project([returned(quantity=2)], [action])["sync_issues"]
    assert project([], [action])["sync_issues"]


def test_daily_issue_metadata_preserves_original_location_for_grouped_review() -> None:
    result = project([returned(status="Pending"), returned(sku="UNKNOWN")])
    issue = result["issues"][0]
    assert issue == {
        "code": "return_status",
        "message": "实物退回状态待核",
        "label": "2026-11-04 第2行 TEST-SKU 实物退回状态待核",
        "seller_sku": "TEST-SKU",
        "sku_id": "2",
        "report_date": "2026-11-04",
        "source_row": 2,
        "report_version_id": "1",
    }
    assert result["issues"][1]["sku_id"] is None
    assert result["issues"][1]["code"] == "unmatched_product"
    assert not result["returns"]
