from __future__ import annotations

from io import BytesIO
from typing import Literal

import openpyxl  # type: ignore[import-untyped]
import pytest
from app.manual_tables.examples import example
from app.manual_tables.exports import render, semantic
from app.manual_tables.extraction import extract
from app.manual_tables.schemas import Kind, Options


@pytest.mark.parametrize("kind", ["inventory", "orders", "packing"])
@pytest.mark.parametrize("mode", ["standard", "wide"])
def test_export_round_trip_preserves_business_semantics(
    kind: Kind, mode: Literal["standard", "wide"]
) -> None:
    options = (
        Options(columns={"code": 1, "asin": 2, "fnsku": 3})
        if kind == "packing"
        else Options()
    )
    result = extract(example(kind), kind, options)
    batch = {
        "id": "fictional",
        "revision": 0,
        "kind": kind,
        "filename": "fictional.xlsx",
        "source_digest": "0" * 64,
        "result": result,
    }
    raw = render(batch, mode)
    again = extract(raw, kind, Options())
    assert semantic(again) == semantic(result)
    assert again["total_units"] == result["total_units"]


def test_formula_looking_source_text_stays_text_in_exports() -> None:
    result = extract(example("inventory"), "inventory", Options())
    result["rows"][0]["code"] = "=DO-NOT-EXECUTE"
    batch = {
        "id": "fictional",
        "revision": 0,
        "kind": "inventory",
        "filename": "fictional.xlsx",
        "source_digest": "0" * 64,
        "result": result,
    }
    book = openpyxl.load_workbook(BytesIO(render(batch, "standard")), data_only=False)
    assert book.active["H2"].value == "=DO-NOT-EXECUTE"
    assert book.active["H2"].data_type == "s"
    assert book.active.freeze_panes == "A2"


def test_filtered_export_uses_all_matching_rows_and_mentions_scope() -> None:
    result = extract(example("inventory"), "inventory", Options())
    batch = {
        "id": "fictional",
        "revision": 0,
        "kind": "inventory",
        "filename": "fictional.xlsx",
        "source_digest": "0" * 64,
        "result": result,
    }
    book = openpyxl.load_workbook(BytesIO(render(batch, "standard", "99002")))
    assert book.active.max_row == 8
    assert all(book.active.cell(r, 1).value == "99002" for r in range(2, 9))
    assert any(row[1].value == "99002" for row in book["说明"] if len(row) > 1)


@pytest.mark.parametrize("mode", ["standard", "wide"])
def test_large_integer_is_exported_as_text_without_excel_rounding(
    mode: Literal["standard", "wide"],
) -> None:
    result = extract(example("inventory"), "inventory", Options())
    result["rows"][2]["units"] = "123456789012345678"
    result["total_units"] = str(sum(int(r["units"]) for r in result["rows"]))
    batch = {
        "id": "qa",
        "revision": 1,
        "kind": "inventory",
        "filename": "qa.xlsx",
        "source_digest": "a" * 64,
        "result": result,
    }
    again = extract(render(batch, mode), "inventory", Options())
    assert semantic(again) == semantic(result)
