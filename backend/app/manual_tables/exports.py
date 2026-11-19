# ruff: noqa: RUF001 -- Chinese user-facing punctuation.
"""Typed, formula-safe output generated from the same fields as extraction."""

from collections import OrderedDict
from io import BytesIO
from typing import Any

import openpyxl  # type: ignore[import-untyped]
from openpyxl.styles import Font, PatternFill  # type: ignore[import-untyped]

from app.manual_tables.schemas import (
    EXPORT_FIELDS,
    FIELDS,
    SHEET_TITLES,
    SIZES,
    VERSION,
)


def semantic(result: dict[str, Any]) -> list[Any]:
    fields = (
        "style",
        "color",
        "size",
        "units",
        "code",
        "date",
        "warehouse",
        "planned_date",
        "basis",
        "dispatched",
        "order_number",
        "asin",
        "fnsku",
        "number",
    )
    return sorted(
        [
            [
                *(str(row.get(k) or "") for k in fields),
                sorted(
                    (
                        row.get("boxes")
                        or ({str(row["box"]): row["units"]} if row.get("box") else {})
                    ).items()
                ),
            ]
            for row in result["rows"]
            if not row["excluded"]
        ],
        key=str,
    )


def excel_number(value: str) -> int | str:
    """Excel numeric cells preserve only fifteen significant decimal digits."""
    return int(value) if len(value) <= 15 else value


def render(batch: dict[str, Any], mode: str, query: str = "") -> bytes:
    result = batch["result"]
    kind = batch["kind"]
    selected = [
        r
        for r in result["rows"]
        if not r["excluded"]
        and (
            not query
            or query.casefold()
            in " ".join(
                str(r.get(v, "")) for v in ("style", "color", "size", "code")
            ).casefold()
        )
    ]
    book = openpyxl.Workbook()
    sheet = book.active
    notes = [
        ("格式版本", VERSION),
        ("批次", batch["id"]),
        ("修订", str(batch["revision"])),
        ("资料性质", "人工整理资料，未过账；业务事实以对应业务单据为准。"),
        ("来源文件", batch["filename"]),
        ("来源摘要", batch["source_digest"]),
        ("筛选", query or "全部；覆盖全部分页"),
        ("资料总数量", result["total_units"]),
        (
            "本次导出已知数量",
            str(sum(int(r["units"]) for r in selected if r["units"] is not None)),
        ),
        ("本次导出未知数量格", str(sum(r["units"] is None for r in selected))),
        (
            "当前数量口径",
            result.get("options", {}).get("context", {}).get("basis", "待确认"),
        ),
        ("目标", str(batch.get("target") or "尚未移交")),
    ]
    if mode == "issues":
        sheet.title = "问题清单"
        sheet.append(["工作表", "行", "单元格", "问题", "处理建议", "阻塞业务"])
        for problem in result["issues"]:
            ref = problem["source_ref"]
            sheet.append(
                [
                    ref["sheet"],
                    ref["row"],
                    ref["cell"],
                    problem["message"],
                    problem["suggestion"],
                    "是" if problem["blocking"] else "否",
                ]
            )
    elif mode == "wide" and kind in {"inventory", "orders"}:
        sheet.title = "人工库存宽表" if kind == "inventory" else "人工预下单宽表"
        sheet.append(
            [
                "款号",
                "颜色",
                *SIZES,
                "合计",
                "仓库",
                "业务日期",
                "预计出货日期",
                "结存口径",
                "原商品编码",
                "来源单号",
            ]
        )
        groups: dict[Any, dict[str, Any]] = OrderedDict()
        for row in selected:
            key = tuple(
                row.get(k, "")
                for k in (
                    "style",
                    "color",
                    "warehouse",
                    "date",
                    "planned_date",
                    "basis",
                    "code",
                    "number",
                )
            )
            group = groups.setdefault(key, {})
            if row["size"] in group:
                # Keep colliding rows separately, never silently aggregate originals.
                key = (*key, row["source_line_key"])
                group = groups.setdefault(key, {})
            group[row["size"]] = row["units"]
        for key, sizes in groups.items():
            values = [sizes.get(size) for size in SIZES]
            sheet.append(
                [
                    key[0],
                    key[1],
                    *[
                        excel_number(sizes[s])
                        if s in sizes and sizes[s] is not None
                        else None
                        if s in sizes
                        else "不适用"
                        for s in SIZES
                    ],
                    excel_number(str(sum(int(v) for v in values if v is not None)))
                    if all(v is not None for v in sizes.values())
                    else None,
                    *key[2:8],
                ]
            )
    else:
        if mode not in {"standard", "wide", "template"}:
            raise ValueError("unknown manual export mode")
        sheet.title = SHEET_TITLES[kind]
        fields = EXPORT_FIELDS[kind]
        sheet.append([FIELDS[k] for k in fields])
        for row in [] if mode == "template" else selected:
            box_rows = (
                list(row["boxes"].items())
                if row["boxes"]
                else [(row.get("box", ""), row["units"])]
            )
            for box, amount in box_rows:
                record = row | {
                    "source_line": row.get("source_line") or row["source_line_key"],
                    "box": box,
                    "units": amount,
                }
                sheet.append(
                    [
                        excel_number(str(record[k]))
                        if k == "units" and record.get(k) is not None
                        else record.get(k, "")
                        for k in fields
                    ]
                )
    if mode == "template":
        notes = [
            (key, value)
            for key, value in notes
            if key not in {"批次", "修订", "来源文件", "来源摘要", "资料总数量", "目标"}
        ]
    info = book.create_sheet("说明")
    for entry in notes:
        info.append(entry)
    for source in result.get("excluded_rows", []):
        info.append(("原表排除行", f"第{source['row']}行：{source['reason']}"))
    for row in result["rows"]:
        if row["excluded"] or row["issues"]:
            info.append(
                (
                    "待核/排除",
                    f"{row['source_ref']}；{row.get('decision', {}).get('reason', '')}",
                )
            )
    if mode not in {"template", "issues"}:
        sources = book.create_sheet("来源引用")
        sources.append(
            ["款号", "颜色", "尺码", "来源行标识", "原工作表", "原行", "原数量格"]
        )
        for row in selected:
            ref = row["source_ref"]
            sources.append(
                [
                    row["style"],
                    row["color"],
                    row["size"],
                    row.get("source_line") or row["source_line_key"],
                    ref["sheet"],
                    ref["row"],
                    ref["cell"],
                ]
            )
    if mode not in {"template", "issues"}:
        changes = [
            (row, change)
            for row in selected
            for change in row.get("format_adjustments", [])
        ]
        if changes:
            formatted = book.create_sheet("格式整理")
            formatted.append(["原工作表", "原行", "字段", "整理前", "整理后", "依据"])
            for row, change in changes:
                formatted.append(
                    [
                        row["source_ref"]["sheet"],
                        row["source_ref"]["row"],
                        FIELDS[change["field"]],
                        change["before"],
                        change["after"],
                        change["reason"],
                    ]
                )
    for page in book:
        page.freeze_panes = "A2"
        page.auto_filter.ref = page.dimensions
        for row in page:
            for cell in row:
                if isinstance(cell.value, str):
                    cell.data_type = "s"
                    cell.number_format = "@"
                if cell.row == 1:
                    cell.font = Font(name="Microsoft YaHei", bold=True, color="FFFFFF")
                    cell.fill = PatternFill("solid", fgColor="244F58")
        for cells in page.columns:
            page.column_dimensions[cells[0].column_letter].width = (
                24 if page == sheet else 44
            )
    stream = BytesIO()
    book.save(stream)
    return stream.getvalue()
