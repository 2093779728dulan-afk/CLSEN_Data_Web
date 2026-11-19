from __future__ import annotations

# ruff: noqa: RUF001 -- Preserve Chinese punctuation in extraction fixtures.
from io import BytesIO
from typing import Any, cast

import openpyxl  # type: ignore[import-untyped]
import pytest
from app.api.errors import ApiError
from app.manual_tables.extraction import extract
from app.manual_tables.schemas import Options


def workbook(rows: list[list[object]], title: str = "库存") -> bytes:
    book = openpyxl.Workbook()
    book.active.title = title
    for row in rows:
        book.active.append(row)
    stream = BytesIO()
    book.save(stream)
    return stream.getvalue()


def test_matrix_counts_detail_once_and_preserves_zero_unknown_and_source() -> None:
    raw = workbook(
        [
            ["人工库存"],
            ["新款号", "COLOR", "XS", "S", "M", "合计", "库位"],
            ["0099", "Blue", 2, 0, "/", "=SUM(C3:E3)", "虚构仓"],
        ]
    )
    result = extract(raw, "inventory", Options())
    assert result["total_units"] == "2"
    assert len(result["rows"]) == 3
    assert result["rows"][0]["style"] == "0099"
    assert result["rows"][0]["source_ref"]["cell"] == "C3"
    assert result["rows"][1]["units"] == "0"
    assert result["rows"][2]["units"] is None
    zero = extract(raw, "inventory", Options(zero_policy="blank_slash_zero"))
    assert zero["rows"][2]["units"] == "0"


def test_preorder_delivery_is_not_order_date() -> None:
    raw = workbook(
        [["DELIVERY", "SKU", "S", "M", "QTY"], ["2026-10-15", "0099-Blue", 3, 4, 7]],
        "Sheet1",
    )
    result = extract(raw, "orders", Options())
    assert result["total_units"] == "7"
    assert result["rows"][0]["date"] == ""
    assert result["rows"][0]["planned_date"] == "2026-10-15"


def test_missing_packing_identity_header_requires_explicit_column() -> None:
    raw = workbook(
        [
            [None, None, None, "总数量", "箱1", "箱2"],
            ["0099-Blue-M", "B0TEST", "XTEST", 5, 2, 3],
        ],
        "Sheet1",
    )
    pending = extract(raw, "packing", Options())
    assert pending["state"] == "NEEDS_MAPPING"
    result = extract(
        raw, "packing", Options(columns={"code": 1, "asin": 2, "fnsku": 3})
    )
    assert result["total_units"] == "5"
    assert result["rows"][0]["boxes"] == {"箱1": "2", "箱2": "3"}
    assert result["rows"][0]["raw"]["code"] == "0099-Blue-M"


def test_mismatch_and_formula_quantity_are_chinese_located_issues() -> None:
    raw = workbook([["款号", "颜色", "S", "M", "合计"], ["0099", "Blue", 2, "=1+2", 8]])
    result = extract(raw, "inventory", Options())
    problems = result["issues"]
    assert any(
        p["code"] == "quantity_formula" and p["source_ref"]["cell"] == "D2"
        for p in problems
    )
    assert all(p["message"] and p["suggestion"] for p in problems)


def test_official_header_cannot_become_manual_evidence() -> None:
    raw = workbook(
        [
            ["sku", "asin", "fnsku", "return-date", "reason", "quantity"],
            ["SKU", "ASIN", "FN", "2026-10-10", "defect", 1],
        ]
    )
    with pytest.raises(ApiError) as error:
        extract(raw, "packing", Options())
    assert cast(dict[str, str], error.value.detail)["code"] == "official_report_route"


def test_duplicate_aggregate_not_silently_merged() -> None:
    raw = workbook(
        [
            ["款号", "颜色", "尺码", "数量"],
            ["0099", "Blue", "M", 2],
            ["0099", "Blue", "M", 3],
        ]
    )
    result = extract(raw, "orders", Options())
    assert result["total_units"] == "5"
    assert any(p["code"] == "duplicate_spec" for p in result["issues"])


def test_missing_identity_with_quantity_is_kept_for_review() -> None:
    result = extract(
        workbook([["款号", "颜色", "M"], [None, "Blue", 3]]), "inventory", Options()
    )
    assert len(result["rows"]) == 1
    assert result["total_units"] == "3"
    assert any(p["code"] == "identity_incomplete" for p in result["issues"])


def test_ignore_override_does_not_restore_auto_detected_column() -> None:
    result = extract(
        workbook([["款号", "颜色", "M", "SKU"], ["0099", "Blue", 3, "wrong"]]),
        "inventory",
        Options(columns={"code": 0}),
    )
    assert result["rows"][0]["code"] == ""


def test_real_merged_identity_only_is_inherited() -> None:
    raw = workbook(
        [
            ["款号", "颜色", "尺码", "数量"],
            ["0099", "Blue", "M", 2],
            [None, "Blue", "L", 3],
            [None, "Blue", "S", 1],
        ]
    )
    book = openpyxl.load_workbook(BytesIO(raw))
    book.active.merge_cells("A2:A3")
    stream = BytesIO()
    book.save(stream)
    result = extract(stream.getvalue(), "inventory", Options())
    assert [r["style"] for r in result["rows"]] == ["0099", "0099", ""]


def test_incorrect_source_total_can_be_explicitly_recomputed_with_reason() -> None:
    raw = workbook([["款号", "颜色", "M", "合计"], ["0099", "Blue", 3, 99]])
    first = extract(raw, "inventory", Options())
    assert next(p for p in first["issues"] if p["code"] == "total_mismatch")["blocking"]
    key = first["rows"][0]["source_line_key"]
    fixed = extract(
        raw,
        "inventory",
        Options(
            decisions={key: {"accept_total": True, "reason": "原合计有误，已核对明细"}}
        ),
    )
    assert fixed["total_units"] == "3"
    assert not next(p for p in fixed["issues"] if p["code"] == "total_mismatch")[
        "blocking"
    ]
    assert fixed["rows"][0]["raw"]["total"] == "99"


@pytest.mark.parametrize(
    "decision", [{"excluded": "false"}, {"units": 2}, {"sku_id": None}]
)
def test_decision_types_cannot_change_meaning_silently(
    decision: dict[str, Any],
) -> None:
    from pydantic import ValidationError

    with pytest.raises(ValidationError):
        Options(decisions={"row": {**decision, "reason": "核对"}})


def test_explicit_duplicate_aggregation_preserves_source_rows() -> None:
    raw = workbook(
        [
            ["款号", "颜色", "尺码", "数量"],
            ["0099", "Blue", "M", 2],
            ["0099", "Blue", "M", 3],
        ]
    )
    result = extract(
        raw,
        "orders",
        Options(aggregate_duplicates=True, aggregation_reason="独立行分配，核对后汇总"),
    )
    assert len(result["rows"]) == 2
    assert result["total_units"] == "5"
    assert all(not p["blocking"] for p in result["issues"])


def test_case_equivalent_duplicate_specs_still_need_a_decision() -> None:
    raw = workbook(
        [
            ["款号", "颜色", "尺码", "数量"],
            ["0099", "Blue", "M", 2],
            ["0099", "BLUE", "M", 3],
        ]
    )
    result = extract(raw, "orders", Options())
    assert any(
        p["code"] == "duplicate_spec" and p["blocking"] for p in result["issues"]
    )


def test_chinese_official_report_is_routed_to_original_import() -> None:
    raw = workbook([["（子）ASIN", "已订购商品数量"], ["TEST", 2]])
    with pytest.raises(ApiError) as error:
        extract(raw, "orders", Options())
    assert cast(dict[str, str], error.value.detail)["code"] == "official_report_route"


def test_unmapped_size_and_invalid_date_are_not_silently_discarded() -> None:
    raw = workbook(
        [["款号", "颜色", "M", "4XL", "业务日期"], ["0099", "Blue", 2, 5, "10月16日"]]
    )
    result = extract(raw, "inventory", Options())
    assert {p["code"] for p in result["issues"]} >= {"unsupported_size", "date_invalid"}
