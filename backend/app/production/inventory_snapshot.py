"""Authorized local stocktake evidence, without inventory posting or SKU inference."""
# ruff: noqa: RUF001 -- Chinese user-facing messages use Chinese punctuation.

from __future__ import annotations

import hashlib
import json
import re
from datetime import date
from io import BytesIO
from pathlib import Path
from typing import Any, Literal, cast
from xml.etree.ElementTree import ParseError
from zipfile import BadZipFile, ZipFile

import openpyxl  # type: ignore[import-untyped]
from openpyxl.utils import get_column_letter  # type: ignore[import-untyped]
from pydantic import Field, ValidationError

from app.api.errors import ApiError
from app.catalog.models import StrictCatalogModel
from app.config import Settings
from app.production.order_source_drafts import draft_root
from app.site_context import CurrentSiteContext

INVENTORY_FILENAME = "花都工厂新仓库-库存明细表最新-10.10.xlsx"
INVENTORY_TABLE_FILENAME = "花都仓库1号-用户核对表-20261013.txt"
GUANGZHOU_FILENAME = "花都工厂CLSEN仓库-库存明细表最新-26.11.4.xlsx"
SIZES = ("XS", "S", "M", "L", "XL", "XXL", "3XL")


class InventorySource(StrictCatalogModel):
    schema_version: Literal["production-inventory-source-v1"] = Field(alias="schema")
    consumer_site_id: str = Field(pattern=r"^[1-9][0-9]*$")
    source_digest: str = Field(pattern=r"^[a-f0-9]{64}$")
    source_format: Literal["xlsx", "pasted_table"] = "xlsx"
    source_filename: str | None = Field(
        default=None,
        pattern=r"^(花都仓库1号-用户核对表-[0-9]{8}\.txt|花都工厂CLSEN仓库-库存明细表最新-26\.11\.4\.xlsx)$",
    )
    source_kind: Literal["FICTIONAL", "REAL_SOURCE"] = "REAL_SOURCE"
    organized_on: date | None
    stocktaken_on: date | None


def _text(value: object) -> str:
    if value is None:
        return ""
    if isinstance(value, float) and value.is_integer():
        return str(int(value))
    return str(value)


def _quantity(value: object, cell: str) -> dict[str, object]:
    raw = _text(value)
    if not isinstance(value, bool) and re.fullmatch(r"[0-9]{1,18}", raw.strip()):
        return {"cell": cell, "raw": raw, "state": "LITERAL", "units": str(int(raw))}
    # Only a bounded sequence of integer additions, never eval or Excel execution.
    if len(raw) <= 1000 and re.fullmatch(r"=\s*[0-9]+(?:\s*\+\s*[0-9]+)+\s*", raw):
        units = sum(int(term.strip()) for term in raw[1:].split("+"))
        if units < 10**18:
            return {
                "cell": cell,
                "raw": raw,
                "state": "ADDITION_REFERENCE",
                "units": str(units),
            }
    return {
        "cell": cell,
        "raw": raw,
        "state": "UNKNOWN" if raw.strip() in ("", "/") else "UNSUPPORTED",
        "units": None,
    }


def _guangzhou_rows(book: Any) -> dict[str, object]:
    sheet = book["库存"]
    if (
        sheet.max_row > 1000
        or sheet.max_column != 11
        or [_text(sheet.cell(2, column).value) for column in range(1, 12)]
        != ["新款号", "COLOR", *SIZES, "合计", "库位"]
    ):
        raise ValueError("Guangzhou stocktake columns changed")
    rows = []
    for index in range(3, sheet.max_row + 1):
        style, color = (_text(sheet.cell(index, column).value) for column in (1, 2))
        if not style and not color:
            continue
        if not style or not color:
            raise ValueError("Guangzhou stocktake identity incomplete")
        quantities = {
            size: _quantity(
                sheet.cell(index, column).value, f"{get_column_letter(column)}{index}"
            )
            for column, size in enumerate(SIZES, 3)
        }
        if any(q["state"] not in {"LITERAL", "UNKNOWN"} for q in quantities.values()):
            raise ValueError("Guangzhou size quantity unsupported")
        literal = sum(
            int(str(q["units"])) for q in quantities.values() if q["state"] == "LITERAL"
        )
        total = _quantity(sheet.cell(index, 10).value, f"J{index}")
        if total["state"] == "LITERAL" and int(str(total["units"])) != literal:
            raise ValueError("Guangzhou total differs from size quantities")
        location = _text(sheet.cell(index, 11).value)
        unknown = sum(q["state"] == "UNKNOWN" for q in quantities.values())
        rows.append(
            {
                "source_key": f"库存!{index}",
                "sheet": "库存",
                "source_row": index,
                "style_code": style,
                "color": color,
                "old_style_code": "",
                "source_sku": "",
                "color_note": "",
                "location": location,
                "location_group": "WAREHOUSE_1"
                if location == "广州成品仓"
                else "UNCONFIRMED",
                "quantities": quantities,
                "literal_units": str(literal),
                "formula_units": "0",
                "unknown_cells": unknown,
                "source_total": total,
                "notes": [],
                "issues": ["空白和斜杠尺码数量待核。"] if unknown else [],
                "sku_id": None,
            }
        )
    if not rows:
        raise ValueError("Guangzhou stocktake has no records")
    return {
        "rows": rows,
        "defects": [],
        "defect_period_note": "",
        "summary": {"defect_literal_units": "0"},
    }


def parse_inventory(content: bytes) -> dict[str, object]:
    """Preserve cell evidence without repeating totals or historic defects."""
    # This registered local original contains ~21MB of embedded images.
    # Its read-only path is independent of the existing 2MB upload contract.
    if not content or len(content) > 30_000_000:
        raise ValueError("inventory source exceeds its adapted local format")
    with ZipFile(BytesIO(content)) as archive:
        if (
            len(archive.infolist()) > 2000
            or sum(item.file_size for item in archive.infolist()) > 30_000_000
        ):
            raise ValueError("inventory workbook exceeds its expanded budget")
    book = openpyxl.load_workbook(BytesIO(content), data_only=False)
    rows: list[dict[str, object]] = []
    try:
        if book.sheetnames == ["库存"]:
            return _guangzhou_rows(book)
        layouts = {
            "主销款": (1, 2, None, 3, None, 4, 11, 12),
            "滞销款": (4, 5, 6, 10, 11, 13, 19, 21),
            "处理款": (4, 5, 6, 10, 11, 13, 19, 21),
        }
        for name, (
            style_col,
            old_col,
            sku_col,
            color_col,
            cn_col,
            size_col,
            total_col,
            location_col,
        ) in layouts.items():
            sheet = book[name]
            size_count = 7 if name == "主销款" else 6
            if sheet.max_row > 2000 or any(
                sheet.cell(2, size_col + i).value != size
                for i, size in enumerate(SIZES[:size_count])
            ):
                raise ValueError(
                    "inventory header or row count is outside the adapted format"
                )
            for row_index in range(3, sheet.max_row + 1):
                identity = [
                    style_col,
                    old_col,
                    color_col,
                    *([sku_col] if sku_col else []),
                    *([cn_col] if cn_col else []),
                ]
                if not any(
                    sheet.cell(row_index, col).value is not None
                    for col in [*identity, *range(size_col, size_col + size_count)]
                ):
                    continue
                quantities = {
                    size: _quantity(
                        sheet.cell(row_index, size_col + i).value,
                        f"{get_column_letter(size_col + i)}{row_index}",
                    )
                    for i, size in enumerate(SIZES[:size_count])
                }
                literal = sum(
                    int(str(cell["units"]))
                    for cell in quantities.values()
                    if cell["state"] == "LITERAL"
                )
                addition = sum(
                    int(str(cell["units"]))
                    for cell in quantities.values()
                    if cell["state"] == "ADDITION_REFERENCE"
                )
                unknown = sum(cell["units"] is None for cell in quantities.values())
                location = _text(sheet.cell(row_index, location_col).value)
                issues = []
                if unknown:
                    issues.append("空白、斜杠或不支持的数量待核对，不按0处理。")
                if addition:
                    issues.append(
                        "尺码中含整数加法公式，仅单列计算参考，未并入明确数字量。"
                    )
                if location != "新仓库":
                    issues.append("原库位归属待确认，未自动计入花都仓库1号。")
                style = _text(sheet.cell(row_index, style_col).value)
                if not style or style == "无款号" or "改" in style:
                    issues.append("款号待识别或含改号说明，保留原文。")
                notes = []
                note_cols = (
                    [2, 7, 8, 9, 20, 22]
                    if name == "滞销款"
                    else [2, 7, 8, 9, 20, 22, 23]
                    if name == "处理款"
                    else []
                )
                for col in note_cols:
                    raw = _text(sheet.cell(row_index, col).value)
                    if raw:
                        notes.append(
                            {"cell": f"{get_column_letter(col)}{row_index}", "raw": raw}
                        )
                if any("另有" in str(note["raw"]) for note in notes):
                    issues.append("“另有”备注数量与尺码量是否重叠待核，未追加计量。")
                total = _quantity(
                    sheet.cell(row_index, total_col).value,
                    f"{get_column_letter(total_col)}{row_index}",
                )
                if (
                    total["state"] == "LITERAL"
                    and int(str(total["units"])) != literal + addition
                ):
                    issues.append("原表合计与可读尺码量不同，需核对差额。")
                rows.append(
                    {
                        "source_key": f"{name}!{row_index}",
                        "sheet": name,
                        "source_row": row_index,
                        "style_code": style,
                        "old_style_code": _text(sheet.cell(row_index, old_col).value),
                        "source_sku": _text(sheet.cell(row_index, sku_col).value)
                        if sku_col
                        else "",
                        "color": _text(sheet.cell(row_index, color_col).value),
                        "color_note": _text(sheet.cell(row_index, cn_col).value)
                        if cn_col
                        else "",
                        "location": location,
                        "location_group": "WAREHOUSE_1"
                        if location == "新仓库"
                        else "UNCONFIRMED",
                        "quantities": quantities,
                        "literal_units": str(literal),
                        "formula_units": str(addition),
                        "unknown_cells": unknown,
                        "source_total": total,
                        "notes": notes,
                        "issues": issues,
                        "sku_id": None,
                    }
                )
        sheet = book["次品数量"]
        if sheet.max_row > 2000 or [sheet.cell(3, c).value for c in range(1, 6)] != [
            "款号",
            "颜色",
            "尺码",
            "数量",
            "备注",
        ]:
            raise ValueError("historic defect header is outside the adapted format")
        defects = []
        for row_index in range(4, sheet.max_row + 1):
            if sheet.cell(row_index, 4).value is None:
                continue
            inherited: dict[str, str] = {}

            def merged_value(
                col: int,
                row_index: int = row_index,
                inherited: dict[str, str] = inherited,
            ) -> str:
                value = sheet.cell(row_index, col).value
                if value is None:
                    for merged in sheet.merged_cells.ranges:
                        if (
                            merged.min_row <= row_index <= merged.max_row
                            and merged.min_col <= col <= merged.max_col
                        ):
                            origin = sheet.cell(merged.min_row, merged.min_col)
                            value = origin.value
                            inherited[f"{get_column_letter(col)}{row_index}"] = (
                                origin.coordinate
                            )
                            break
                return _text(value)

            style, color, size, note = (merged_value(c) for c in (1, 2, 3, 5))
            defects.append(
                {
                    "source_row": row_index,
                    "style_code": style,
                    "color": color,
                    "size": size,
                    "quantity": _quantity(
                        sheet.cell(row_index, 4).value, f"D{row_index}"
                    ),
                    "note": note,
                    "inherited_cells": inherited,
                    "identity_unresolved": not style or not color,
                    "sku_id": None,
                }
            )
        return {
            "rows": rows,
            "defects": defects,
            "defect_period_note": _text(sheet.cell(1, 1).value),
            "summary": {
                "row_count": len(rows),
                "literal_units": str(
                    sum(int(str(row["literal_units"])) for row in rows)
                ),
                "warehouse_1_literal_units": str(
                    sum(
                        int(str(row["literal_units"]))
                        for row in rows
                        if row["location_group"] == "WAREHOUSE_1"
                    )
                ),
                "location_unconfirmed_literal_units": str(
                    sum(
                        int(str(row["literal_units"]))
                        for row in rows
                        if row["location_group"] == "UNCONFIRMED"
                    )
                ),
                "formula_units": str(
                    sum(int(str(row["formula_units"])) for row in rows)
                ),
                "unknown_cells": sum(int(str(row["unknown_cells"])) for row in rows),
                "defect_literal_units": str(
                    sum(
                        int(str(cast(dict[str, object], row["quantity"])["units"]))
                        for row in defects
                        if cast(dict[str, object], row["quantity"])["state"]
                        == "LITERAL"
                    )
                ),
                "additional_note_rows": sum(
                    any(
                        "另有" in str(note["raw"])
                        for note in cast(list[dict[str, object]], row["notes"])
                    )
                    for row in rows
                ),
            },
        }
    finally:
        book.close()


def parse_inventory_table(content: bytes) -> dict[str, object]:
    """Read the user's fixed-column replacement, retaining blank size cells."""
    if not content or len(content) > 1_000_000:
        raise ValueError("inventory table exceeds its local format")
    lines = content.decode("utf-8-sig").splitlines()
    if not lines or lines[0].split("   ") != [
        "新款号",
        "COLOR",
        *SIZES,
        "合计",
        "库位",
    ]:
        raise ValueError("inventory table header is outside the adapted format")
    if len(lines) > 2001:
        raise ValueError("inventory table exceeds its row budget")
    rows: list[dict[str, object]] = []
    for line_number, line in enumerate(lines[1:], start=2):
        if not line:
            continue
        values = line.split("   ")
        if len(values) == 10:
            values.append("")  # Only the trailing warehouse field may be absent.
        if len(values) != 11 or not values[0].strip() or not values[1].strip():
            raise ValueError("inventory table fields cannot be positioned reliably")
        quantities = {
            size: _quantity(values[i + 2], f"{get_column_letter(i + 3)}{line_number}")
            for i, size in enumerate(SIZES)
        }
        if any(
            cell["state"] not in ("LITERAL", "UNKNOWN") for cell in quantities.values()
        ):
            raise ValueError("inventory table size quantity is unsupported")
        total = _quantity(values[9], f"J{line_number}")
        literal = sum(
            int(str(cell["units"]))
            for cell in quantities.values()
            if cell["state"] == "LITERAL"
        )
        if total["state"] != "LITERAL" or int(str(total["units"])) != literal:
            raise ValueError(
                "inventory table total differs from explicit size quantities"
            )
        unknown = sum(cell["state"] == "UNKNOWN" for cell in quantities.values())
        location = values[10]
        issues = []
        if unknown:
            issues.append("空白和斜杠尺码数量仍待核对，不按0处理。")
        if location != "新仓库":
            issues.append("原库位归属待确认，未计入花都仓库1号。")
        rows.append(
            {
                "source_key": f"用户核对表!{line_number}",
                "sheet": "用户核对表",
                "source_row": line_number,
                "style_code": values[0],
                "color": values[1],
                "old_style_code": "",
                "source_sku": "",
                "color_note": "",
                "location": location,
                "location_group": "WAREHOUSE_1"
                if location == "新仓库"
                else "UNCONFIRMED",
                "quantities": quantities,
                "literal_units": str(literal),
                "formula_units": "0",
                "unknown_cells": unknown,
                "source_total": total,
                "notes": [],
                "issues": issues,
                "sku_id": None,
            }
        )
    if not rows:
        raise ValueError("inventory table has no records")
    return {
        "rows": rows,
        "defects": [],
        "defect_period_note": "",
        "summary": {"defect_literal_units": "0"},
    }


def warehouse_1_view(
    parsed: dict[str, object],
    quantity_basis: Literal["DECLARED_TOTAL", "SIZE_LITERALS"],
) -> dict[str, object]:
    """Partition warehouse evidence before display aggregation; never bind SKUs."""
    source_rows = cast(list[dict[str, object]], parsed["rows"])
    rows: list[dict[str, object]] = []
    unconfirmed: list[dict[str, object]] = []
    for original in source_rows:
        total = cast(dict[str, object], original["source_total"])
        row = original | {
            "stock_units": total["units"]
            if quantity_basis == "DECLARED_TOTAL"
            else original["literal_units"]
        }
        (rows if row["location_group"] == "WAREHOUSE_1" else unconfirmed).append(row)
    literal = sum(int(str(row["literal_units"])) for row in rows)
    unknown_location_literal = sum(
        int(str(row["literal_units"])) for row in unconfirmed
    )
    return parsed | {
        "scope": "WAREHOUSE_1",
        "quantity_basis": quantity_basis,
        "rows": rows,
        "unconfirmed_rows": unconfirmed,
        "summary": cast(dict[str, object], parsed["summary"])
        | {
            "source_row_count": len(source_rows),
            "row_count": len(rows),
            "product_count": len({str(row["style_code"]) for row in rows}),
            "warehouse_1_units": str(sum(int(str(row["stock_units"])) for row in rows)),
            "location_unconfirmed_units": str(
                sum(int(str(row["stock_units"])) for row in unconfirmed)
            ),
            "literal_units": str(literal),
            "warehouse_1_literal_units": str(literal),
            "location_unconfirmed_literal_units": str(unknown_location_literal),
            "formula_units": str(sum(int(str(row["formula_units"])) for row in rows)),
            "unknown_cells": sum(int(str(row["unknown_cells"])) for row in rows),
            "additional_note_rows": sum(
                any(
                    "另有" in str(note["raw"])
                    for note in cast(list[dict[str, object]], row["notes"])
                )
                for row in rows
            ),
        },
    }


def inventory_snapshot(
    settings: Settings, context: CurrentSiteContext
) -> dict[str, object]:
    root = (
        Path(settings.production_inventory_source_root)
        if settings.production_inventory_source_root
        else draft_root(settings, context)
    )
    path = root / "inventory-source.json"
    if not path.is_file():
        raise ApiError(
            404, "inventory_snapshot_unavailable", "当前本地环境尚未配置库存快照。"
        )
    try:
        source = InventorySource.model_validate_json(path.read_bytes())
        if source.consumer_site_id != str(context.site_id):
            raise ApiError(
                404, "inventory_snapshot_unavailable", "当前站点没有已授权的库存快照。"
            )
        filename = (
            source.source_filename or INVENTORY_TABLE_FILENAME
            if source.source_format == "pasted_table"
            else source.source_filename or INVENTORY_FILENAME
        )
        content = (root / "inputs" / filename).read_bytes()
        if hashlib.sha256(content).hexdigest() != source.source_digest:
            raise ValueError("source digest changed")
        result = warehouse_1_view(
            parse_inventory_table(content)
            if source.source_format == "pasted_table"
            else parse_inventory(content),
            "DECLARED_TOTAL"
            if source.source_format == "pasted_table"
            else "SIZE_LITERALS",
        )
    except (
        OSError,
        ValueError,
        ValidationError,
        BadZipFile,
        KeyError,
        ParseError,
    ) as error:
        raise ApiError(
            422,
            "inventory_snapshot_invalid",
            "库存副本无法核对，请检查列位置、数量合计及登记的来源摘要。",
        ) from error
    return {
        **result,
        "filename": filename,
        "source_format": source.source_format,
        "source_kind": source.source_kind,
        "source_manifest_digest": hashlib.sha256(
            json.dumps(
                source.model_dump(mode="json", by_alias=True),
                sort_keys=True,
                separators=(",", ":"),
            ).encode()
        ).hexdigest(),
        "source_digest": source.source_digest,
        "organized_on": source.organized_on.isoformat()
        if source.organized_on
        else None,
        "stocktaken_on": source.stocktaken_on.isoformat()
        if source.stocktaken_on
        else None,
        "warehouse_note": "核对广州成品仓，空白和斜杠数量保留未知。"
        if filename == GUANGZHOU_FILENAME
        else "仅核对花都仓库1号；新仓库为同一仓库，空库位记录单列待确认。",
        "read_only": True,
        "posting_enabled": False,
        "historical_shipments_deducted": False,
    }
