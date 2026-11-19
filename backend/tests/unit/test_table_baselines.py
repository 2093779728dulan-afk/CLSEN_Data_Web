# ruff: noqa: RUF001 -- Business quantity labels.
from io import BytesIO
from pathlib import Path
from types import SimpleNamespace
from typing import Any, cast

import openpyxl  # type: ignore[import-untyped]
import pytest
from app.api.errors import ApiError
from app.production.count_tables import count_template, preview_count
from app.production.table_baselines import read_baseline, remember_baseline

SCOPE: dict[str, Any] = {"warehouse_id": "1", "owner_id": "7"}
CATALOG: dict[str, Any] = {"11": {"label": "SIM-Blue-M", "status": "active"}}
CONTEXT: Any = SimpleNamespace(site_id=1, principal_user_id=4)


def filled(value: int = 0, quality: str = "合格", duplicate: bool = False) -> Any:
    book = openpyxl.load_workbook(BytesIO(count_template(SCOPE, CATALOG)))
    sheet = book.worksheets[0]
    sheet["C2"] = quality
    sheet["D2"] = value
    if duplicate:
        sheet.append(["11", "SIM-Blue-M", quality, 2])
    output = BytesIO()
    book.save(output)
    book.close()
    return output.getvalue()


def test_count_zero_is_known_and_blanks_are_not_zero(tmp_path: Path) -> None:
    raw = filled()
    result = preview_count(raw, "count.xlsx", SCOPE, CATALOG)
    assert not result["issues"]
    assert len(result["rows"]) == 1
    assert result["rows"][0]["units"] == "0"
    assert result["rows"][0]["quality"] == "QUALIFIED"
    source = remember_baseline(tmp_path, CONTEXT, "count", raw, result)[
        "table_baseline"
    ]
    assert source == read_baseline(tmp_path, CONTEXT, source["id"])
    assert source["rows"][0]["values"]["实盘总数"] == "0"
    assert source["rows"][0]["row"] == 2
    assert (
        remember_baseline(tmp_path, CONTEXT, "count", raw, result)["table_baseline"]
        == source
    )
    for other in (
        SimpleNamespace(site_id=2, principal_user_id=4),
        SimpleNamespace(site_id=1, principal_user_id=5),
    ):
        with pytest.raises(ApiError):
            read_baseline(tmp_path, cast(Any, other), source["id"])
    path = tmp_path / "uploads/1/4/table-baselines" / f"{source['id']}.json"
    path.write_text("{}", encoding="utf-8")
    with pytest.raises(ApiError):
        read_baseline(tmp_path, CONTEXT, source["id"])


@pytest.mark.parametrize(
    "value,quality,duplicate",
    [
        (None, "合格", False),
        (-1, "合格", False),
        (1.5, "合格", False),
        (True, "合格", False),
        ("=1+1", "合格", False),
        (1, "未知", False),
        (1, "合格", True),
        (9007199254740992, "合格", False),
    ],
)
def test_count_rejects_ambiguous_values(
    value: Any, quality: Any, duplicate: Any, tmp_path: Path
) -> None:
    raw = filled(value, quality, duplicate)
    result = preview_count(raw, "count.xlsx", SCOPE, CATALOG)
    assert result["issues"]
    assert "table_baseline" not in remember_baseline(
        tmp_path, CONTEXT, "count", raw, result
    )


def test_count_rejects_another_scope() -> None:
    with pytest.raises(ApiError):
        preview_count(filled(), "count.xlsx", {**SCOPE, "owner_id": "8"}, CATALOG)


@pytest.mark.parametrize("kind", ["orders", "receipt", "packing"])
def test_baselines_keep_business_granularity_and_original_rows(
    kind: Any, tmp_path: Path
) -> None:
    raw = filled()
    rows = {
        "orders": [{"sku_id": "11", "sku_label": "SIM", "expected_units": "3"}],
        "receipt": [
            {
                "row": 2,
                "sku_id": "11",
                "order_line_id": "21",
                "sku_label": "SIM",
                "qualified_units": "2",
                "pending_units": "1",
                "defective_units": "0",
            },
            {
                "row": 4,
                "sku_id": "11",
                "order_line_id": "22",
                "sku_label": "SIM",
                "qualified_units": "1",
                "pending_units": "0",
                "defective_units": "0",
            },
        ],
        "packing": [
            {
                "row": 2,
                "sku_id": "11",
                "sku_label": "SIM",
                "box_number": "A",
                "units": "2",
            },
            {
                "row": 5,
                "sku_id": "11",
                "sku_label": "SIM",
                "box_number": "B",
                "units": "1",
            },
        ],
    }[kind]
    result: dict[str, Any] = {
        "filename": "source.xlsx",
        "rows": rows,
        "issues": [],
        "command": {"business_date": "2026-11-04"},
        "source_table": {"rows": [{"sku_id": "11", "source_row": 9}]},
    }
    baseline = remember_baseline(tmp_path, CONTEXT, kind, raw, result)["table_baseline"]
    if kind == "orders":
        assert baseline["rows"][1]["row"] == 9
    elif kind == "receipt":
        assert [row["key"] for row in baseline["rows"]] == ["21", "22"]
    else:
        assert baseline["rows"][0]["values"] == {
            "出货数量": "3",
            "装箱分配": "A：2；B：1",
        }
