"""Order-scoped input previews never create receipt or shipment facts."""

from io import BytesIO
from typing import Any, cast

import openpyxl  # type: ignore[import-untyped]
import pytest
from app.api.errors import ApiError
from app.production.workbench_tables import (
    RECEIPT_HEADERS,
    operation_template,
    preview_operation,
    receipt_batch_order,
)

CATALOG = {
    "1001": {"style_code": "2301", "code": "2301-Blue-M"},
    "1002": {"style_code": "2301", "code": "2301-Blue-L"},
}


@pytest.fixture
def order() -> dict[str, Any]:
    return {
        "id": "10",
        "revision": "3",
        "status": "CONFIRMED",
        "business_number": "QA-ONLY",
        "lines": [
            {"id": "101", "sku_id": "1001", "sku_label": "2301-Blue-M"},
            {"id": "102", "sku_id": "1002", "sku_label": "2301-Blue-L"},
        ],
    }


def filled(order: dict[str, Any], kind: str, values: list[list[object]]) -> bytes:
    book = openpyxl.load_workbook(BytesIO(operation_template(order, kind)))
    sheet = book.worksheets[0]
    sheet.delete_rows(2, sheet.max_row)
    for row in values:
        sheet.append(row)
    output = BytesIO()
    book.save(output)
    book.close()
    return output.getvalue()


@pytest.mark.parametrize("kind", ["receipt", "packing"])
def test_templates_bind_the_order_and_do_not_invent_quantities(
    order: dict[str, Any], kind: str
) -> None:
    raw = operation_template(order, kind)
    result = preview_operation(raw, "empty.xlsx", order, kind)
    assert result["issues"]
    assert result["total_units"] == "0"
    assert result["order_id"] == "10"


def test_receipt_splits_actual_qualities_and_keeps_stable_line_identity(
    order: dict[str, Any],
) -> None:
    result = preview_operation(
        filled(order, "receipt", [["1001", "2301-Blue-M", "4", "2", "1"]]),
        "receipt.xlsx",
        order,
        "receipt",
    )
    assert result["issues"] == []
    assert result["rows"] == [
        {
            "row": 2,
            "sku_id": "1001",
            "order_line_id": "101",
            "sku_label": "2301-Blue-M",
            "qualified_units": "4",
            "pending_units": "2",
            "defective_units": "1",
        }
    ]
    assert result["total_units"] == "7"


def test_packing_groups_boxes_and_preserves_each_sku_quantity(
    order: dict[str, Any],
) -> None:
    result = preview_operation(
        filled(
            order,
            "packing",
            [
                ["BOX-A", "1001", "2301-Blue-M", "3"],
                ["BOX-A", "1002", "2301-Blue-L", "2"],
                ["BOX-B", "1001", "2301-Blue-M", "1"],
            ],
        ),
        "packing.xlsx",
        order,
        "packing",
    )
    assert result["issues"] == []
    assert result["total_units"] == "6"
    assert result["cartons"] == [
        {
            "number": "BOX-A",
            "items": [
                {"sku_id": "1001", "units": "3"},
                {"sku_id": "1002", "units": "2"},
            ],
        },
        {"number": "BOX-B", "items": [{"sku_id": "1001", "units": "1"}]},
    ]


@pytest.mark.parametrize(
    "quantity", ["-1", "1.5", "=1+1", "999999999999999999999999999999"]
)
def test_invalid_quantities_are_reported_with_row_and_column(
    order: dict[str, Any], quantity: str
) -> None:
    result = preview_operation(
        filled(order, "receipt", [["1001", "2301-Blue-M", quantity, "", ""]]),
        "bad.xlsx",
        order,
        "receipt",
    )
    assert any(
        issue["row"] == 2 and "合格" in issue["message"] for issue in result["issues"]
    )


@pytest.mark.parametrize(
    "kind,rows",
    [
        ("receipt", [["9999", "foreign", "1", "", ""]]),
        ("receipt", [["1001", "M", "1", "", ""], ["1001", "M", "2", "", ""]]),
        ("packing", [["BOX-A", "1001", "M", "1"], ["BOX-A", "1001", "M", "2"]]),
        ("packing", [["", "1001", "M", "1"]]),
    ],
)
def test_foreign_skus_duplicate_lines_and_missing_boxes_block_preview(
    order: dict[str, Any], kind: str, rows: list[list[object]]
) -> None:
    assert preview_operation(filled(order, kind, rows), "bad.xlsx", order, kind)[
        "issues"
    ]


def test_another_order_or_revision_cannot_reuse_the_template(
    order: dict[str, Any],
) -> None:
    raw = filled(order, "receipt", [["1001", "M", "1", "", ""]])
    for changed in [{**order, "id": "11"}, {**order, "revision": "4"}]:
        assert preview_operation(raw, "old.xlsx", changed, "receipt")["issues"]


def test_invalid_workbooks_and_unconfirmed_orders_are_rejected(
    order: dict[str, Any],
) -> None:
    with pytest.raises(ApiError):
        preview_operation(b"not an xlsx", "bad.xlsx", order, "receipt")
    with pytest.raises(ApiError):
        operation_template({**order, "status": "DRAFT"}, "receipt")


def test_batch_receipt_same_sku_is_explicitly_allocated_to_two_orders(
    order: dict[str, Any],
) -> None:
    second = {
        **order,
        "id": "11",
        "business_number": "QA-SECOND",
        "lines": [{"id": "103", "sku_id": "1001", "sku_label": "2301-Blue-M"}],
    }
    batch = receipt_batch_order([second, order])
    assert batch["revision"] == "10:3,11:3"
    raw = filled(
        batch,
        "receipt",
        [
            ["101", "QA-ONLY", "1001", "M", "3", "1", ""],
            ["103", "QA-SECOND", "1001", "M", "2", "", "1"],
        ],
    )
    result = preview_operation(raw, "batch.xlsx", batch, "receipt")
    assert result["issues"] == []
    assert result["total_units"] == "7"
    assert [
        (r["order_line_id"], r["sku_id"], r["qualified_units"]) for r in result["rows"]
    ] == [("101", "1001", "3"), ("103", "1001", "2")]
    changed = receipt_batch_order([{**second, "revision": "4"}, order])
    assert preview_operation(raw, "batch.xlsx", changed, "receipt")["issues"]


@pytest.mark.parametrize(
    "row",
    [
        ["999", "QA-ONLY", "1001", "M", "1", "", ""],
        ["101", "QA-ONLY", "999", "M", "1", "", ""],
        ["101", "OTHER", "1001", "M", "1", "", ""],
        ["101", "QA-ONLY", "1001", "M", "=1+1", "", ""],
        ["101", "QA-ONLY", "1001", "M", "-1", "", ""],
    ],
)
def test_batch_receipt_rejects_ambiguous_or_modified_source_rows(
    order: dict[str, Any], row: list[object]
) -> None:
    batch = receipt_batch_order([order])
    result = preview_operation(
        filled(batch, "receipt", [row]), "bad.xlsx", batch, "receipt"
    )
    assert result["issues"] and result["rows"] == []


def test_batch_receipt_requires_bounded_distinct_confirmed_orders(
    order: dict[str, Any],
) -> None:
    for orders in [
        [],
        [order, order],
        [{**order, "status": "DRAFT"}],
        [{**order, "id": str(i)} for i in range(1, 22)],
    ]:
        with pytest.raises(ApiError):
            receipt_batch_order(orders)
    batch = receipt_batch_order([order])
    raw = filled(
        batch,
        "receipt",
        [
            ["101", "QA-ONLY", "1001", "M", "1", "", ""],
            ["101", "QA-ONLY", "1001", "M", "1", "", ""],
        ],
    )
    assert preview_operation(raw, "repeat.xlsx", batch, "receipt")["issues"]


def test_batch_receipt_does_not_silently_post_hidden_rows(
    order: dict[str, Any],
) -> None:
    batch = receipt_batch_order([order])
    book = openpyxl.load_workbook(
        BytesIO(
            filled(batch, "receipt", [["101", "QA-ONLY", "1001", "M", "1", "", ""]])
        )
    )
    book.worksheets[0].row_dimensions[2].hidden = True
    output = BytesIO()
    book.save(output)
    book.close()
    assert preview_operation(output.getvalue(), "hidden.xlsx", batch, "receipt")[
        "issues"
    ]


def test_simple_receipt_uses_order_sheet_style_and_exact_catalog_codes(
    order: dict[str, Any],
) -> None:
    raw = operation_template(order, "receipt", CATALOG)
    book = openpyxl.load_workbook(BytesIO(raw))
    sheet = book.worksheets[0]
    assert [c.value for c in sheet[1]] == RECEIPT_HEADERS
    assert sheet.title == "入库"
    assert [c.value for c in sheet[2]] == [
        "QA-ONLY",
        "2301",
        "2301-Blue-M",
        None,
        None,
        None,
    ]
    assert sheet["A1"].fill.fgColor.rgb == "00334155"
    assert sheet.freeze_panes == "A2" and sheet.sheet_view.showGridLines is False
    assert all(
        cell.alignment.horizontal == cell.alignment.vertical == "center"
        for row in sheet
        for cell in row
    )
    sheet["D2"], sheet["E2"], sheet["F2"] = 4, 2, 1
    # Display formatting is optional on import; only business values are validated.
    sheet["C2"].alignment = openpyxl.styles.Alignment(horizontal="left")
    sheet["D2"].number_format = "0.00"
    # The previously exported v2 sheet name remains a valid alias.
    sheet.title = "收货入库"
    output = BytesIO()
    book.save(output)
    book.close()
    result = preview_operation(
        output.getvalue(), "receipt.xlsx", order, "receipt", CATALOG
    )
    assert result["issues"] == [] and result["total_units"] == "7"
    assert result["rows"][0]["order_line_id"] == "101"


def test_simple_receipt_keeps_same_sku_allocated_when_rows_reordered(
    order: dict[str, Any],
) -> None:
    second = {
        **order,
        "id": "11",
        "business_number": "QA-SECOND",
        "lines": [{"id": "103", "sku_id": "1001", "sku_label": "old verbose label"}],
    }
    batch = receipt_batch_order([order, second])
    book = openpyxl.load_workbook(
        BytesIO(operation_template(batch, "receipt", CATALOG))
    )
    sheet = book.worksheets[0]
    sheet.delete_rows(2, sheet.max_row)
    sheet.append(["QA-SECOND", "2301", "2301-Blue-M", 2, None, 1])
    sheet.append(["QA-ONLY", "2301", "2301-Blue-M", 3, 1, None])
    output = BytesIO()
    book.save(output)
    book.close()
    result = preview_operation(
        output.getvalue(), "reordered.xlsx", batch, "receipt", CATALOG
    )
    assert result["issues"] == [] and result["total_units"] == "7"
    assert [r["order_line_id"] for r in result["rows"]] == ["103", "101"]
    # v1 templates remain importable even when the current catalog is supplied.
    legacy = filled(batch, "receipt", [["101", "QA-ONLY", "1001", "old", 1, "", ""]])
    assert (
        preview_operation(legacy, "old.xlsx", batch, "receipt", CATALOG)["issues"] == []
    )


@pytest.mark.parametrize(
    "column,value",
    [
        ("A", "OTHER"),
        ("B", "02301"),
        ("C", "2301-blue-M"),
        ("C", " 2301-Blue-M"),
        ("D", "=3+1"),
        ("D", -1),
    ],
)
def test_simple_receipt_rejects_wrong_source_identity_and_quantity(
    order: dict[str, Any], column: str, value: object
) -> None:
    book = openpyxl.load_workbook(
        BytesIO(operation_template(order, "receipt", CATALOG))
    )
    sheet = book.worksheets[0]
    sheet["D2"] = 1
    sheet[f"{column}2"] = value
    output = BytesIO()
    book.save(output)
    book.close()
    result = preview_operation(output.getvalue(), "bad.xlsx", order, "receipt", CATALOG)
    assert result["issues"] and result["rows"] == []


def test_order_and_receipt_tables_are_not_interchangeable(
    order: dict[str, Any],
) -> None:
    from app.production.order_tables import parse_order_table, render_order_table

    receipt = operation_template(order, "receipt", CATALOG)
    with pytest.raises(ApiError) as rejected:
        parse_order_table(receipt, "receipt.xlsx")
    assert cast(dict[str, str], rejected.value.detail)["code"] == "wrong_table_purpose"
    original = render_order_table(
        {
            **order,
            "business_date": "2026-10-31",
            "lines": [{**order["lines"][0], "expected_units": "10"}],
        },
        CATALOG,
        site_id=1,
    )
    with pytest.raises(ApiError) as rejected:
        preview_operation(original, "order.xlsx", order, "receipt", CATALOG)
    assert cast(dict[str, str], rejected.value.detail)["code"] == "wrong_table_purpose"


def test_simple_receipt_does_not_guess_codes_from_a_verbose_label(
    order: dict[str, Any],
) -> None:
    with pytest.raises(ApiError) as rejected:
        operation_template(order, "receipt", {})
    assert (
        cast(dict[str, str], rejected.value.detail)["code"]
        == "receipt_identity_unavailable"
    )


def dispatch_file(rows: Any, headers: Any = None, metadata: Any = None) -> Any:
    book = openpyxl.Workbook()
    book.active.append(headers or ["箱号", "款号", "SKU", "装箱数量"])
    for row in rows:
        book.active.append(row)
    if metadata:
        tab = book.create_sheet("填写说明")
        for key, value in metadata.items():
            tab.append([key, value])
    output = BytesIO()
    book.save(output)
    book.close()
    return output.getvalue()


def dispatch_preview(raw: Any) -> Any:
    from app.production.workbench_tables import preview_dispatch

    catalog = {key: item | {"label": item["code"]} for key, item in CATALOG.items()}
    return preview_dispatch(
        raw, "dispatch.xlsx", {"warehouse_id": "1", "owner_id": "7"}, catalog
    )


def original_packing_file(
    quantity: int = 5, sku: str = "2301-Blue-M", footer: bool = True
) -> Any:
    book = openpyxl.Workbook()
    sheet = book.active
    sheet.title = "Sheet1"
    sheet.append([None, None, None, "总数量", "箱1", "差异"])
    sheet.append([sku, "B0TEST", "XTEST", quantity, 1, "=D2-E2"])
    if footer:
        sheet.append([None, None, None, "=SUM(D2:D2)", "=SUM(E2:E2)", "=D3-E3"])
        sheet.append([None, None, "重量KG", None, 3.2])
    book.create_sheet("Sheet2")
    book.create_sheet("Sheet3")
    out = BytesIO()
    book.save(out)
    book.close()
    return out.getvalue()


def original_packing_preview(raw: Any, catalog: Any = None) -> Any:
    from app.production.workbench_tables import preview_dispatch

    return preview_dispatch(
        raw,
        "original.xlsx",
        {"warehouse_id": "1", "owner_id": "7"},
        catalog
        if catalog is not None
        else {k: v | {"label": v["code"]} for k, v in CATALOG.items()},
        layout="packing_totals",
    )


def test_original_packing_requires_explicit_layout_and_reads_total_without_boxes() -> (
    None
):
    raw = original_packing_file()
    with pytest.raises(ApiError):
        dispatch_preview(raw)
    result = original_packing_preview(raw)
    assert result["issues"] == [] and result["total_units"] == "5"
    assert result["cartons"] == [] and result["box_count"] == 0
    assert result["source_total_units"] == "5" and result["source_row_count"] == 1
    assert result["rows"][0]["row"] == 2
    assert result["rows"][0]["source_sheet"] == "Sheet1"
    assert result["rows"][0]["source_cell"] == "D2"
    assert result["ignored_rows"] == [3, 4]


def test_original_packing_retains_unknown_sku_and_amount_in_located_issue() -> None:
    result = original_packing_preview(original_packing_file(sku="UNKNOWN-Blue-M"))
    assert not result["rows"]
    assert result["source_total_units"] == "5" and result["source_row_count"] == 1
    assert result["issues"][0]["row"] == 2
    assert "UNKNOWN-Blue-M" in result["issues"][0]["message"]
    assert result["issues"][0]["cell"] == "A2"
    assert result["issues"][0]["stage"] == "business"
    assert result["source_rows"] == [
        {
            "row": 2,
            "sku_code": "UNKNOWN-Blue-M",
            "sku_id": "",
            "units": "5",
            "source_cell": "D2",
        }
    ]


@pytest.mark.parametrize("quantity", [None, 0, -1, "=2+3", "1.5"])
def test_original_packing_does_not_fill_missing_or_formula_quantities(
    quantity: Any,
) -> None:
    result = original_packing_preview(original_packing_file(quantity=quantity))
    assert result["issues"] and not result["rows"]
    assert result["source_total_units"] is None
    assert result["source_rows"][0]["units"] is None
    assert any(issue["stage"] == "reading" for issue in result["issues"])


def test_original_packing_rejects_ambiguous_sheets_hidden_rows_and_trailing_products() -> (  # noqa: E501 -- Preserve the existing test identity.
    None
):
    for mutation in ("sheet", "hidden", "tail", "duplicate", "sum"):
        book = openpyxl.load_workbook(BytesIO(original_packing_file()))
        if mutation == "sheet":
            book["Sheet2"]["A1"] = "another table"
        elif mutation == "hidden":
            book.active.row_dimensions[2].hidden = True
        elif mutation == "tail":
            book.active.append(["2301-Blue-L", "", "", 2])
        elif mutation == "duplicate":
            book.active["E1"] = "总数量"
        else:
            book.active["D3"] = "=SUM(D2:D99)"
        out = BytesIO()
        book.save(out)
        book.close()
        try:
            result = original_packing_preview(out.getvalue())
        except ApiError:
            continue
        assert result["issues"], mutation


def test_distinct_unmatched_standard_skus_remain_distinct_rows() -> None:
    result = dispatch_preview(
        dispatch_file([["RAW-A", 2], ["RAW-B", 3]], headers=["SKU", "出货数量"])
    )
    assert [row["sku_code"] for row in result["source_rows"]] == ["RAW-A", "RAW-B"]
    assert result["source_total_units"] == "5"
    assert all(issue["stage"] == "business" for issue in result["issues"])


def test_dispatch_supports_quantity_only_or_multiple_boxes_without_orders() -> None:
    raw = dispatch_file(
        [["C1", "2301", "2301-Blue-M", 2], ["C2", "2301", "2301-Blue-M", 3]]
    )
    result = dispatch_preview(raw)
    assert result["issues"] == []
    assert result["order_id"] == ""
    assert result["warehouse_id"] == "1" and result["owner_id"] == "7"
    assert result["total_units"] == "5" and result["box_count"] == 2
    assert [row["row"] for row in result["rows"]] == [2, 3]
    result = dispatch_preview(dispatch_file([["2301-Blue-M", 2]], ["SKU", "出货数量"]))
    assert result["issues"] == [] and result["cartons"] == []


@pytest.mark.parametrize(
    "rows,metadata",
    [
        ([["C1", "2301", "2301-blue-M", 2]], None),
        ([["C1", "OTHER", "2301-Blue-M", 2]], None),
        ([["C1", "2301", "2301-Blue-M", "=1+1"]], None),
        ([["C1", "2301", "2301-Blue-M", -1]], None),
        ([["C1", "2301", "2301-Blue-M", 1], ["C1", "2301", "2301-Blue-M", 1]], None),
        ([["C1", "2301", "2301-Blue-M", 1], [None, "2301", "2301-Blue-L", 1]], None),
        ([["C1", "2301", "2301-Blue-M", 1]], {"仓库ID": "2", "货主ID": "7"}),
        ([["C1", "2301", "2301-Blue-M", 1]], {"仓库ID": "1", "货主ID": "8"}),
    ],
)
def test_dispatch_preserves_errors_and_rejects_scope_identity_or_quantity_conflicts(
    rows: Any, metadata: Any
) -> None:
    result = dispatch_preview(dispatch_file(rows, metadata=metadata))
    assert result["issues"]
    assert all("row" in issue and issue["message"] for issue in result["issues"])


def test_dispatch_template_centers_real_codes_and_round_trips_after_filling() -> None:
    from app.production.workbench_tables import dispatch_template

    scope = {"warehouse_id": "1", "owner_id": "7"}
    book = openpyxl.load_workbook(BytesIO(dispatch_template(scope, CATALOG)))
    sheet = book.worksheets[0]
    assert (
        sheet["B2"].value == "2301-Blue-M"
        and sheet["B2"].alignment.horizontal == "center"
    )
    assert [cell.value for cell in sheet[1]] == ["款号", "SKU", "本次出货数量"]
    sheet["C2"] = 1
    output = BytesIO()
    book.save(output)
    book.close()
    assert dispatch_preview(output.getvalue())["issues"] == []
