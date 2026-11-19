"""Latest order sheets use four explicit fields, independent of decorative columns."""

from datetime import datetime
from io import BytesIO
from typing import cast

import openpyxl  # type: ignore[import-untyped]
import pytest
from app.api.errors import ApiError
from app.production.order_tables import parse_order_table, render_order_table


def source(*, four: bool = False, second: bool = False, bad: bool = False) -> bytes:
    book = openpyxl.Workbook()
    ws = book.active
    ws.title = "11月-12月"
    if four:
        ws.append(["下单日期", "款号", "SKU", "订单数量"])
        ws.append([datetime(2026, 10, 30), "0012", "0012-sand beige-M", 7])
        ws.append([None, None, None, "=SUM(D2:D2)"])
    else:
        ws.append(
            ["下单日期", "出货日期", "品名", "款号", "颜色", "SKU", "IMAGE", "订单数量"]
        )
        ws.append(
            [
                datetime(2026, 10, 30),
                "=1/0",
                "ignored",
                "0012",
                "wrong color",
                "0012-sand beige-M",
                None,
                "=7" if bad else 7,
            ]
        )
        ws.append([None, None, None, None, None, None, None, "=SUM(H2:H2)"])
        ws.merge_cells("G2:G3")
    book.create_sheet("Sheet1").append(["旧库存测算", -999])
    if second:
        clone = book.copy_worksheet(ws)
        clone.title = "另一张订单"
    out = BytesIO()
    book.save(out)
    book.close()
    return out.getvalue()


@pytest.mark.parametrize("four", [False, True])
def test_four_fields_only_keep_exact_codes_dates_locations_and_exclude_totals(
    four: bool,
) -> None:
    result = parse_order_table(source(four=four), "original.xlsx")
    assert result is not None
    assert result["business_date"] == "2026-10-30"
    assert result["source_units"] == "7"
    assert result["excluded_rows"] == [3]
    assert result["excluded_sheets"] == ["Sheet1"]
    assert result["issues"] == []
    row = result["rows"][0]
    assert row["sku_code"] == "0012-sand beige-M"
    assert row["style_code"] == "0012"
    assert row["source_ref"]["cells"]["expected_units"] == ("D2" if four else "H2")
    assert row["color"] == row["planned_dispatch_date"] == ""


def test_quantity_formula_is_not_executed_or_trusted() -> None:
    result = parse_order_table(source(bad=True), "original.xlsx")
    assert result is not None
    assert result["source_units"] == "0"
    assert any(p["row"] == 2 and "正整数" in p["message"] for p in result["issues"])


def test_footer_before_formatted_empty_rows_and_missing_identity_are_distinct() -> None:
    book = openpyxl.load_workbook(BytesIO(source(four=True)))
    ws = book.active
    ws["A7"].number_format = "yyyy-mm-dd"
    out = BytesIO()
    book.save(out)
    result = parse_order_table(out.getvalue(), "qa.xlsx")
    assert result is not None
    assert result["excluded_rows"] == [3]
    assert result["issues"] == []
    ws["A3"] = datetime(2026, 10, 30)
    ws["D3"] = 7
    out = BytesIO()
    book.save(out)
    book.close()
    result = parse_order_table(out.getvalue(), "qa.xlsx")
    assert result is not None
    assert len(result["rows"]) == 2
    assert any(p["row"] == 3 for p in result["issues"])


def test_two_business_sheets_are_not_silently_combined() -> None:
    with pytest.raises(ApiError) as error:
        parse_order_table(source(second=True), "original.xlsx")
    assert error.value.status_code == 422
    assert (
        cast(dict[str, object], error.value.detail)["code"] == "order_sheet_ambiguous"
    )


def test_unsafe_numeric_quantity_requires_text_without_changing_its_value() -> None:
    book = openpyxl.load_workbook(BytesIO(source(four=True)))
    ws = book.active
    ws["D2"] = 9007199254740992
    out = BytesIO()
    book.save(out)
    result = parse_order_table(out.getvalue(), "qa.xlsx")
    assert result is not None
    assert result["source_units"] == "0"
    assert any("安全精度" in p["message"] for p in result["issues"])
    ws["D2"] = "9007199254740992"
    out = BytesIO()
    book.save(out)
    book.close()
    result = parse_order_table(out.getvalue(), "qa.xlsx")
    assert result is not None
    assert result["source_units"] == "9007199254740992"
    assert not result["issues"]


def test_export_is_four_typed_fields_and_roundtrips_without_rewriting_identifiers() -> (
    None
):
    document = {
        "id": "18",
        "revision": "3",
        "business_date": "2026-10-30",
        "system_number": "QA-ORDER",
        "status": "CONFIRMED",
        "lines": [{"sku_id": "9", "expected_units": "7"}],
    }
    catalog = {"9": {"style_code": "0012", "code": "0012-sand beige-M"}}
    raw = render_order_table(document, catalog, site_id=4)
    book = openpyxl.load_workbook(BytesIO(raw))
    ws = book.worksheets[0]
    assert [c.value for c in ws[1]] == ["下单日期", "款号", "SKU", "订单数量"]
    assert ws["D2"].data_type == "n"
    assert ws["A2"].is_date
    assert ws.freeze_panes == "A2"
    book.close()
    result = parse_order_table(raw, "export.xlsx")
    assert result is not None
    assert result["source_units"] == "7"
    assert result["rows"][0]["style_code"] == "0012"
    assert result["export_source"]["order_id"] == "18"
    assert result["export_source"]["site_id"] == "4"


def test_export_retains_unknown_rows_and_never_emits_codes_as_formulas() -> None:
    doc = {
        "id": "1",
        "revision": "1",
        "business_date": "",
        "lines": [
            {"sku_id": "1", "expected_units": "7"},
            {"sku_id": "2", "expected_units": "15000000000000001"},
        ],
    }
    raw = render_order_table(
        doc, {"1": {"style_code": "=a", "code": "+SKU"}}, site_id=4
    )
    book = openpyxl.load_workbook(BytesIO(raw))
    ws = book.worksheets[0]
    assert ws.max_row == 3
    assert ws["B2"].data_type == ws["C2"].data_type == "s"
    assert ws["D3"].value == "15000000000000001"
    assert "待核" in str(book["说明"]["B8"].value)
    book.close()
