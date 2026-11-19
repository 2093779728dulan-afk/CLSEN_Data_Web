import csv
from io import BytesIO, StringIO
from typing import Any, cast

import openpyxl  # type: ignore[import-untyped]
import pytest
from app.api.errors import ApiError
from app.production.fba_receipts import (
    HEADERS,
    export_batch,
    parse_receipts,
    parse_review,
    parse_review_payload,
)


def test_unified_draft_export_reimport_preserves_sources_and_tracks_edits() -> None:
    batch = {
        "id": "20",
        "scope_id": "1",
        "revision": "2",
        "digest": "a" * 64,
        "source_kind": "MANUAL",
        "draft_payload": {
            "business_date": "2026-11-05",
            "shipment_revision": "1",
            "reference_link_id": "31",
            "reference_number": "SIM-REF",
            "reason": "SIM actual receipt",
            "lines": [
                {
                    "line_id": "1",
                    "sku_id": "1001",
                    "quantity": "10",
                    "selected": True,
                    "allocations": [{"binding_id": "5", "units": "10"}],
                    "batch_id": "9",
                    "source_row": "2",
                }
            ],
        },
    }
    book = openpyxl.load_workbook(BytesIO(export_batch(batch)))
    book["处理决定"]["B2"] = "8"
    book["处理决定"]["D2"] = '[{"binding_id":"5","units":"8"}]'
    book["处理决定"]["J2"] = "SIM actual count eight"
    out = BytesIO()
    book.save(out)
    parsed = parse_review_payload(out.getvalue(), batch)
    assert parsed["expected_revision"] == "2"
    assert parsed["draft_payload"]["reference_link_id"] == "31"
    assert parsed["draft_payload"]["reference_number"] == "SIM-REF"
    line = parsed["draft_payload"]["lines"][0]
    assert line["quantity"] == "8"
    assert line["batch_id"] == "9" and line["source_row"] == "2"
    assert line["adjustment_reason"] == "SIM actual count eight"
    reference_row = next(
        row[0].row for row in book["生成信息"] if row[0].value == "FBA货件号"
    )
    book["生成信息"].cell(reference_row, 2, "SIM-OTHER")
    out = BytesIO()
    book.save(out)
    with pytest.raises(ApiError):
        parse_review_payload(out.getvalue(), batch)
    book["生成信息"].cell(reference_row, 2, "SIM-REF")
    book["接收明细"]["B2"] = "1002"
    out = BytesIO()
    book.save(out)
    with pytest.raises(ApiError):
        parse_review_payload(out.getvalue(), batch)


def test_report_v2_preserves_effective_quantity_and_manual_coverage() -> None:
    batch = {
        "id": "7",
        "scope_id": "2",
        "revision": "3",
        "digest": "a" * 64,
        "rows": parse_receipts(report({}))["rows"],
        "decisions": [
            {
                "source_row": "2",
                "decision": "NEW",
                "quantity": "8",
                "receipt_links": [{"event_id": "4", "units": "6"}],
                "allocations": [{"binding_id": "1", "units": "2"}],
                "adjustment_reason": "SIM count eight",
            }
        ],
    }
    result = parse_review_payload(export_batch(batch), batch)
    assert result["decisions"][0]["quantity"] == "8"
    assert result["decisions"][0]["receipt_links"] == [{"event_id": "4", "units": "6"}]
    assert batch["rows"][0]["quantity"] == "10"


def test_historic_v1_review_workbook_remains_readable() -> None:
    batch = {
        "id": "7",
        "scope_id": "2",
        "revision": "3",
        "digest": "a" * 64,
        "rows": parse_receipts(report({}))["rows"],
        "decisions": [],
    }
    book = openpyxl.load_workbook(BytesIO(export_batch(batch)))
    book["生成信息"]["B1"] = "fba_receipts_review_v1"
    book["处理决定"].delete_cols(9, 3)
    out = BytesIO()
    book.save(out)
    result = parse_review_payload(out.getvalue(), batch)
    assert result["decisions"][0]["decision"] == "PENDING"
    assert "quantity" not in result["decisions"][0]


def report(*changes: dict[str, str]) -> bytes:
    out = StringIO(newline="")
    writer = csv.DictWriter(out, fieldnames=HEADERS)
    writer.writeheader()
    for change in changes:
        writer.writerow(
            {
                **dict.fromkeys(HEADERS, ""),
                "Date": "10/25/2026",
                "FNSKU": "X-TEST",
                "ASIN": "B-TEST",
                "MSKU": "test-SKU",
                "Event Type": "Receipts",
                "Reference ID": "test-ref",
                "Quantity": "10",
                "Fulfillment Center": "TEST",
                "Disposition": "SELLABLE",
                "Country": "US",
                "Date and Time": "2026-10-25T23:30:00-0700",
                **change,
            }
        )
    return out.getvalue().encode("utf-8-sig")


@pytest.mark.parametrize(
    "disposition,quality",
    [
        ("", "QUALIFIED"),
        ("SELLABLE", "QUALIFIED"),
        ("CUSTOMER_DAMAGED", "DEFECTIVE"),
        ("PENDING", "PENDING"),
    ],
)
def test_receipts_default_sellable_and_keep_explicit_quality(
    disposition: Any, quality: Any
) -> None:
    result = parse_receipts(report({"Disposition": disposition}))
    assert not result["issues"]
    assert result["rows"][0]["quality"] == quality


def test_signed_events_keep_all_rows_and_offset_without_claiming_unique_ids() -> None:
    result = parse_receipts(report({}, {}, {"Quantity": "-1"}, {"Quantity": "1"}))
    assert not result["issues"]
    assert [r["quantity"] for r in result["rows"]] == ["10", "10", "-1", "1"]
    assert result["rows"][0]["occurred_at"] == "2026-10-25T23:30:00-07:00"
    assert result["rows"][0]["business_date"] == "2026-10-25"
    assert result["rows"][0]["raw"]["Store"] == ""
    assert result["rows"][0]["raw"]["Reconciled Quantity"] == ""
    assert result["rows"][0]["fingerprint"] == result["rows"][1]["fingerprint"]
    assert result["rows"][0]["same_file_candidates"] == [3]
    assert result["rows"][1]["same_file_candidates"] == [2]
    assert [r["source_row"] for r in result["rows"]] == [2, 3, 4, 5]
    assert all("event_id" not in r for r in result["rows"])


@pytest.mark.parametrize(
    "change,column,code",
    [
        ({"Quantity": ""}, "Quantity", "fba_quantity_invalid"),
        ({"Quantity": "1.5"}, "Quantity", "fba_quantity_invalid"),
        ({"Quantity": "0"}, "Quantity", "fba_quantity_invalid"),
        ({"Date and Time": "2026-10-25T10:00:00"}, "Date and Time", "fba_time_invalid"),
        (
            {"Date and Time": "2026-10-25T10:00:00-0800"},
            "Date and Time",
            "fba_time_invalid",
        ),
        ({"Date": "10/26/2026"}, "Date", "fba_date_mismatch"),
        ({"Event Type": "Shipments"}, "Event Type", "fba_event_type_invalid"),
        ({"Country": "CA"}, "Country", "fba_country_invalid"),
        ({"Disposition": "UNKNOWN"}, "Disposition", "fba_disposition_invalid"),
    ],
)
def test_invalid_official_rows_remain_visible_with_chinese_location(
    change: Any, column: Any, code: Any
) -> None:
    result = parse_receipts(report(change))
    assert len(result["rows"]) == 1
    issue = next(i for i in result["issues"] if i["code"] == code)
    assert issue["row"] == 2 and issue["column"] == column
    assert issue["message"] and issue["raw"] == change[column]
    assert any("\u4e00" <= c <= "\u9fff" for c in issue["message"])


def test_reordering_changes_source_positions_but_not_equality_candidates() -> None:
    a = parse_receipts(report({}, {"Quantity": "8"}))
    b = parse_receipts(report({"Quantity": "8"}, {}))
    assert [r["fingerprint"] for r in a["rows"]] == [
        r["fingerprint"] for r in reversed(b["rows"])
    ]
    assert a["rows"][0]["source_row"] == b["rows"][0]["source_row"] == 2


def test_standard_review_roundtrip_preserves_original_rows_and_same_batch() -> None:
    parsed = parse_receipts(report({}, {"Quantity": "-1"}))
    batch = {
        "id": "7",
        "scope_id": "2",
        "revision": "3",
        "digest": "a" * 64,
        "rows": parsed["rows"],
        "decisions": [
            {
                "source_row": "2",
                "decision": "NEW",
                "event_key": "test-1",
                "reason": "Explicit test occurrence",
                "allocations": [{"binding_id": "5", "units": "10"}],
            },
            {"source_row": "3", "decision": "PENDING"},
        ],
    }
    decisions = parse_review(export_batch(batch), batch)
    assert len(decisions) == 2
    assert decisions[0]["event_key"] == "test-1"
    assert decisions[0]["allocations"] == [{"binding_id": "5", "units": "10"}]
    assert decisions[1]["decision"] == "PENDING"
    assert decisions[1]["correction_of"] == ""


def test_review_rejects_stale_revision_without_accepting_a_second_event() -> None:
    parsed = parse_receipts(report({}))
    batch = {
        "id": "7",
        "scope_id": "2",
        "revision": "3",
        "digest": "a" * 64,
        "rows": parsed["rows"],
        "decisions": [],
    }
    raw = export_batch(batch)
    with pytest.raises(ApiError) as failure:
        parse_review(raw, {**batch, "revision": "4"})
    assert cast(dict[str, str], failure.value.detail)["code"] == "fba_review_invalid"


def test_ledger_classification_preserves_signed_quantities_and_unknown_rows() -> None:
    parsed = parse_receipts(
        report(
            {"Quantity": "-1"},
            {"Event Type": "CustomerReturns", "Quantity": "2"},
            {"Event Type": "CustomerReturns", "Quantity": "-2"},
            {"Event Type": "Adjustments", "Quantity": "3"},
            {"Event Type": "Unrecognised", "Quantity": "4"},
        )
    )
    assert [r["ledger_kind"] for r in parsed["rows"]] == [
        "CORRECTION",
        "CUSTOMER_RETURN",
        "CORRECTION",
        "ADJUSTMENT",
        "UNKNOWN",
    ]
    assert [r["quantity"] for r in parsed["rows"]] == ["-1", "2", "-2", "3", "4"]
    assert len(parsed["issues"]) == 4


def test_snapshot_covered_rows_are_not_automatically_prepared() -> None:
    from app.production.fba_receipts import prepare_receipt_decisions

    row = {
        **parse_receipts(report({}))["rows"][0],
        "identity": {"tracked": True},
        "existing_candidates": [],
        "bindings": [{"id": "1", "received_units": "0", "units": "100"}],
        "posting_block": "SNAPSHOT_COVERED",
    }
    assert (
        prepare_receipt_decisions(
            {"id": "1", "rows": [row], "resolved": [], "decisions": [], "issues": []}
        )
        == []
    )
