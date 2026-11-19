"""Read-only XLSX projection of inventory evidence, using the source columns."""

# ruff: noqa: RUF001 -- Chinese spreadsheet labels.
from __future__ import annotations

import re
from io import BytesIO
from typing import Any

from openpyxl import Workbook  # type: ignore[import-untyped]
from openpyxl.styles import Alignment, Font, PatternFill  # type: ignore[import-untyped]
from openpyxl.utils import get_column_letter  # type: ignore[import-untyped]

from app.api.errors import ApiError
from app.production.inventory_snapshot import SIZES

HEADERS = ("新款号", "COLOR", *SIZES, "合计", "库位")


def _needs(row: dict[str, Any]) -> set[str]:
    result = set()
    style = row["style_code"]
    color = row["color"] or row["color_note"]
    if (
        not style
        or style == "无款号"
        or re.search(r"改|\n", style)
        or not color
        or re.search(r"\n|/", color)
    ):
        result.add("identity")
    if row["location_group"] == "UNCONFIRMED":
        result.add("location")
    if row["unknown_cells"] > 0:
        result.add("quantity")
    if (
        row["formula_units"] != "0"
        or any("另有" in note["raw"] for note in row["notes"])
        or any("合计" in issue for issue in row["issues"])
    ):
        result.add("extra")
    return result


def export_rows(
    snapshot: dict[str, Any], query: str = "", focus: str = ""
) -> list[dict[str, Any]]:
    """Match the page: warehouse filters retain the whole product, all pages."""
    groups: dict[str, list[dict[str, Any]]] = {}
    for row in snapshot["rows"]:
        style = row["style_code"]
        key = (
            "source:" + row["source_key"]
            if not style or style == "无款号" or re.search(r"改|\n", style)
            else "style:" + style
        )
        groups.setdefault(key, []).append(row)
    search = query.strip().lower()
    rows = []
    for group in groups.values():
        if focus and not any(focus in _needs(row) for row in group):
            continue
        if not any(
            search
            in " ".join(
                [row["style_code"], row["color"], row["color_note"]]
                + [note["raw"] for note in row["notes"] if "另有" in note["raw"]]
            ).lower()
            for row in group
        ):
            continue
        rows.extend(group)
    for row in snapshot["unconfirmed_rows"] + snapshot.get("outside_rows", []):
        if search in " ".join(
            [row["style_code"], row["color"], row["color_note"]]
        ).lower() and (not focus or focus in _needs(row)):
            rows.append(row)
    return sorted(rows, key=lambda row: (row["sheet"], row["source_row"]))


def _quantity(quantity: dict[str, Any] | None) -> int | str:
    if quantity is not None and quantity["state"] == "LITERAL":
        units = str(quantity["units"])
        # Excel only preserves 15 significant digits in numeric cells.
        return int(units) if len(units) <= 15 else units
    if (
        quantity
        and quantity["state"] == "UNKNOWN"
        and quantity["raw"].strip() not in ("", "/")
    ):
        return "待核"
    return str(quantity["raw"]) if quantity else ""


def inventory_workbook(
    snapshot: dict[str, Any],
    *,
    review_id: str = "",
    revision: int | None = None,
    query: str = "",
    focus: str = "",
) -> bytes:
    manual = snapshot.get("source_kind") == "MANUAL"
    warehouse = (
        str(snapshot.get("warehouse_note") or "本次核对仓库")
        if manual
        else "花都仓库1号"
    )
    rows = export_rows(snapshot, query, focus)
    if not rows:
        raise ApiError(
            422, "inventory_export_empty", "当前筛选没有可导出的库存资料，请调整筛选。"
        )
    workbook = Workbook()
    sheet = workbook.active
    sheet.title = "库存表"
    sheet.append(HEADERS)
    notes: list[list[str | int]] = [
        ["说明项", "内容"],
        ["资料性质", "库存核对资料，未过账；不代表当前可发库存。"],
        ["盘点日期", snapshot.get("stocktaken_on") or "待确认"],
        ["仓库", warehouse if manual else "花都仓库1号；库位“新仓库”为同仓原文。"],
        ["截止及负责人说明", snapshot.get("cutoff_note") or "待确认"],
        ["来源文件", snapshot["filename"]],
        ["来源摘要", snapshot["source_digest"]],
        ["核对单", review_id or "尚未建立核对单，导出原始来源"],
        ["已保存修订", revision if revision is not None else "原始来源"],
        [
            "导出范围",
            f"关键词：{query or '全部'}；待补数据："
            + {
                "": "全部",
                "identity": "款号或颜色待确认",
                "quantity": "尺码数量待核",
                "extra": "公式或附加数量待核",
            }[focus]
            + "；覆盖全部分页",
        ],
        ["导出行数", len(rows)],
        [
            "数量口径",
            "数字为已确认值；空白、斜杠及待核表达式按原文保留，不自动补0，不执行公式。",
        ],
        [
            "归属范围",
            "归属待确认和本仓之外的行仍保留，详见下方逐行说明，不计入本仓汇总。",
        ],
        [
            "附表范围",
            f"历史次品附表{len(snapshot.get('defects', []))}条，不混入本次库存表。",
        ],
        ["逐行说明", "原表位置／归属／待核问题及备注"],
    ]
    for row in rows:
        total = (
            _quantity({"state": "LITERAL", "units": row["reviewed_total"]})
            if row.get("reviewed_total") is not None
            else "待核"
            if "reviewed_total" in row
            else _quantity(row["source_total"])
        )
        location = {
            "WAREHOUSE_1": warehouse if manual else "新仓库",
            "UNCONFIRMED": row["location"],
            "OUTSIDE_SCOPE": "本仓之外",
        }[row["location_group"]]
        sheet.append(
            [
                row["style_code"],
                row["color"] or row["color_note"],
                *[_quantity(row["quantities"].get(size)) for size in SIZES],
                total,
                location,
            ]
        )
        notes.append(
            [
                row["source_key"],
                "；".join(
                    [
                        {
                            "WAREHOUSE_1": warehouse,
                            "UNCONFIRMED": "仓库归属待确认",
                            "OUTSIDE_SCOPE": "本仓之外",
                        }[row["location_group"]],
                        *row["issues"],
                        *[note["raw"] for note in row["notes"]],
                    ]
                ),
            ]
        )
    if manual:
        notes.append(["来源人工整理批次", str(snapshot["manual_batch_id"])])
        notes.append(
            [
                "回导说明",
                "本文件为核对单导出；如需更正，请打开原核对单，不建立第二份业务。",
            ]
        )
    info = workbook.create_sheet("导出说明")
    for values in notes:
        info.append(values)
    for tab in workbook:
        for row in tab:
            for cell in row:
                # Source text, SKU-like codes and notes must never become formulas.
                if isinstance(cell.value, str):
                    cell.data_type = "s"
                    cell.number_format = "@"
                cell.alignment = Alignment(vertical="top", wrap_text=True)
        for cell in tab[1]:
            cell.font = Font(bold=True, color="FFFFFF")
            cell.fill = PatternFill("solid", fgColor="185C7D")
        tab.freeze_panes = "C2" if tab == sheet else "A2"
        tab.auto_filter.ref = tab.dimensions
    for index in range(1, 12):
        sheet.column_dimensions[get_column_letter(index)].width = (
            30 if index == 2 else 18 if index in (1, 11) else 10
        )
    info.column_dimensions["A"].width = 28
    info.column_dimensions["B"].width = 100
    sheet.print_options.horizontalCentered = True
    sheet.sheet_properties.pageSetUpPr.fitToPage = True
    sheet.page_setup.orientation = "landscape"
    sheet.page_setup.paperSize = sheet.PAPERSIZE_A4
    sheet.page_setup.fitToWidth = 1
    sheet.page_setup.fitToHeight = 0
    sheet.print_title_rows = "1:1"
    output = BytesIO()
    workbook.save(output)
    workbook.close()
    return output.getvalue()
