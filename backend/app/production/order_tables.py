# ruff: noqa: RUF001 -- Chinese business labels and validation messages.
"""Four-field order tables. Source formatting never supplies business identity."""

from __future__ import annotations

import hashlib
from datetime import date, datetime
from io import BytesIO
from typing import Any
from zipfile import ZipFile

import openpyxl  # type: ignore[import-untyped]
from openpyxl.styles import Font, PatternFill  # type: ignore[import-untyped]
from openpyxl.utils import get_column_letter  # type: ignore[import-untyped]

from app.api.errors import ApiError
from app.production.source_registry import validate_upload

HEADERS = ("下单日期", "款号", "SKU", "订单数量")
FIELDS = ("order_date", "style_code", "sku_code", "expected_units")
VERSION = "order-table-v4"


def value(raw: Any) -> str:
    if raw is None:
        return ""
    if isinstance(raw, datetime):
        return raw.date().isoformat()
    if isinstance(raw, date):
        return raw.isoformat()
    if isinstance(raw, float) and raw.is_integer():
        return str(int(raw))
    return str(raw)


def table_quantity(cell: Any, amount: str, *, positive: bool) -> int | None:
    """Shared integer/Excel-precision check; each business owns blank/zero semantics."""
    if (
        cell.data_type == "f"
        or not amount.isascii()
        or not amount.isdecimal()
        or len(amount) > 18
        or (positive and int(amount) == 0)
        or (cell.data_type == "n" and abs(cell.value) > 9007199254740991)
    ):
        return None
    return int(amount)


def style_business_sheet(sheet: Any, widths: tuple[int, ...]) -> None:
    """One plain header and readable columns for order and receipt tables."""
    for cell in sheet[1]:
        cell.font = Font(bold=True, color="FFFFFF")
        cell.fill = PatternFill("solid", fgColor="334155")
    for index, width in enumerate(widths, 1):
        sheet.column_dimensions[get_column_letter(index)].width = width
    sheet.freeze_panes = "A2"
    sheet.auto_filter.ref = sheet.dimensions
    sheet.sheet_view.showGridLines = False


def parse_order_table(raw: bytes, filename: str) -> dict[str, Any] | None:
    """Return None only for an unrelated layout, so old templates keep their parser."""
    validate_upload(filename, raw)
    with ZipFile(BytesIO(raw)) as archive:
        if any(p.lower().endswith("vbaproject.bin") for p in archive.namelist()):
            raise ApiError(
                422,
                "order_external_content",
                "下单表不支持宏。请提供不含宏的XLSX副本。",
            )
    # keep_links=False discards stale links in auxiliary sheets without opening them.
    # Only the four explicit business cells below can supply values; formulas fail.
    book = openpyxl.load_workbook(BytesIO(raw), data_only=False, keep_links=False)
    try:
        candidates = []
        if len(book.worksheets) > 10:
            raise ApiError(
                422, "order_sheet_limit", "工作表超过10张，请只保留需要核对的资料。"
            )
        for sheet in book:
            heads = [
                value(c.value)
                for c in next(sheet.iter_rows(min_row=1, max_row=1, max_col=80))
            ]
            if "本次合格数量" in heads and "SKU" in heads:
                raise ApiError(
                    422,
                    "wrong_table_purpose",
                    "这是入库表，请到入库页面导入；下单表使用订单数量。",
                )
            if all(h in heads for h in HEADERS):
                if any(heads.count(h) != 1 for h in HEADERS):
                    raise ApiError(
                        422,
                        "order_duplicate_header",
                        "下单表有效表头重复，请每个字段只保留一列。",
                    )
                candidates.append((sheet, [heads.index(h) + 1 for h in HEADERS]))
        if not candidates:
            return None
        if len(candidates) != 1:
            raise ApiError(
                422,
                "order_sheet_ambiguous",
                "找到多个下单业务页，请每份文件只保留一张下单明细页，避免混单。",
            )
        sheet, columns = candidates[0]
        if sheet.max_row > 1001 or sheet.max_column > 80:
            raise ApiError(
                422, "order_region_limit", "下单表最多1000行明细、80列，请拆分文件。"
            )
        rows: list[dict[str, Any]] = []
        issues: list[dict[str, Any]] = []
        excluded: list[int] = []
        total = 0
        seen = set()
        last_field_row = max(
            (
                n
                for n in range(2, sheet.max_row + 1)
                if any(value(sheet.cell(n, c).value) for c in columns)
            ),
            default=1,
        )
        qty_column = get_column_letter(columns[3])
        for n in range(2, sheet.max_row + 1):
            cells = [sheet.cell(n, c) for c in columns]
            vals = [value(c.value) for c in cells]
            dt, style, code, amount = vals
            if not any(vals):
                continue
            footer = (
                not style
                and not code
                and not dt
                and n == last_field_row
                and bool(rows)
                and (
                    amount.upper().replace(" ", "")
                    == f"=SUM({qty_column}2:{qty_column}{n - 1})"
                    or amount == str(total)
                )
            )
            if (
                footer
                or style in {"合计", "总计"}
                or code in {"合计", "总计"}
                or tuple(vals) == HEADERS
            ):
                excluded.append(n)
                continue
            problems = []
            if any(c.data_type == "f" for c in cells[:3]):
                problems.append("下单日期、款号和SKU不能使用公式，请提供明确原值。")
            if not style or not code or cells[2].data_type != "s":
                problems.append("款号及文字SKU必须填写完整；不根据编码猜测商品身份。")
            try:
                if date.fromisoformat(dt).isoformat() != dt:
                    raise ValueError
            except ValueError:
                problems.append(
                    "下单日期须为明确的年月日，不能用出货日期或文件名代替。"
                )
            quantity = table_quantity(cells[3], amount, positive=True)
            if quantity is not None:
                total += quantity
            else:
                problems.append(
                    "订单数量须为明确的正整数，不能使用空白、0、负数或公式。"
                    "超出Excel安全精度的大整数请使用文字单元格。"
                )
            if code in seen:
                problems.append(
                    "同一张下单表存在重复SKU，请核对明确数量；不会自动合并。"
                )
            seen.add(code)
            if sheet.row_dimensions[n].hidden:
                problems.append("该明细行被隐藏，请核对后取消隐藏再导入。")
            if any(
                m.min_row <= n <= m.max_row
                and any(m.min_col <= c <= m.max_col for c in columns)
                for m in sheet.merged_cells.ranges
            ):
                problems.append(
                    "有效业务字段存在合并单元格，请明确每行的日期、款号、SKU及数量。"
                )
            ref = {
                "sheet": sheet.title,
                "row": n,
                "cells": dict(zip(FIELDS, [c.coordinate for c in cells], strict=True)),
            }
            row: dict[str, Any] = dict(zip(FIELDS, vals, strict=True))
            row.update(
                source_row=n,
                source_ref=ref,
                planned_dispatch_date="",
                product_name="",
                color="",
                source_note="",
                sku_id=None,
                mapping_status="UNRESOLVED",
            )
            rows.append(row)
            issues.extend(
                {"row": n, "sheet": sheet.title, "message": p} for p in problems
            )
        if not rows:
            raise ApiError(422, "source_empty", "下单表没有可核对的商品明细。")
        dates = {r["order_date"] for r in rows}
        if len(dates) > 1:
            issues.append(
                {
                    "row": 0,
                    "message": "一份下单表只能对应一个下单日期，请按实际订单拆分。",
                }
            )
        export_source = {}
        if "说明" in book.sheetnames:
            metadata = {
                value(r[0].value): value(r[1].value)
                for r in book["说明"].iter_rows(max_row=8, max_col=2)
            }
            if metadata.get("格式版本") == VERSION:
                export_source = {
                    "site_id": metadata.get("来源站点", ""),
                    "order_id": metadata.get("来源订单ID", ""),
                    "revision": metadata.get("来源修订", ""),
                }
        return {
            "sample_id": "",
            "filename": filename,
            "format_version": VERSION,
            "source_digest": hashlib.sha256(raw).hexdigest(),
            "sheet": sheet.title,
            "excluded_sheets": [s for s in book.sheetnames if s != sheet.title],
            "excluded_rows": excluded,
            "rows": rows,
            "issues": issues,
            "source_units": str(total),
            "business_date": next(iter(dates)) if len(dates) == 1 else "",
            "mapping_status": "UNRESOLVED",
            "confirmation_enabled": False,
            "export_source": export_source,
        }
    finally:
        book.close()


def standard_order_workbook(source: dict[str, Any]) -> bytes:
    """Feed the existing Java preview while retaining the original attachment."""
    book = openpyxl.Workbook()
    sheet = book.active
    sheet.title = "预计订单_v1"
    sheet.append(["业务订单号（可选）", "下单日期", "SKU", "预计数量", "备注"])
    for row in source["rows"]:
        sheet.append(
            ["", row["order_date"], row["sku_code"], row["expected_units"], ""]
        )
        for cell in sheet[sheet.max_row]:
            cell.data_type = "s"
    out = BytesIO()
    book.save(out)
    book.close()
    return out.getvalue()


def render_order_table(
    document: dict[str, Any] | None, catalog: dict[str, Any], *, site_id: int
) -> bytes:
    book = openpyxl.Workbook()
    sheet = book.active
    sheet.title = "下单明细_v4"
    sheet.append(HEADERS)
    missing = []
    for line in (document or {}).get("lines", []):
        identity = catalog.get(str(line["sku_id"]), {})
        dt = (document or {}).get("business_date")
        qty = str(line["expected_units"])
        values = [
            date.fromisoformat(dt) if dt else None,
            identity.get("style_code", ""),
            identity.get("code", ""),
            int(qty) if len(qty) <= 15 else qty,
        ]
        sheet.append(values)
        for c in (2, 3):
            sheet.cell(sheet.max_row, c).data_type = "s"
            sheet.cell(sheet.max_row, c).number_format = "@"
        sheet.cell(sheet.max_row, 1).number_format = "yyyy-mm-dd"
        sheet.cell(sheet.max_row, 4).number_format = "#,##0" if len(qty) <= 15 else "@"
        if not identity.get("style_code") or not identity.get("code") or not dt:
            missing.append(
                f"第{sheet.max_row}行（商品规格ID {line['sku_id']}）"
                "身份编码或日期待核，保留原数量"
            )
    if document:
        note = book.create_sheet("说明")
        for row in [
            ("格式版本", VERSION),
            ("来源站点", str(site_id)),
            ("来源订单ID", str(document["id"])),
            ("来源修订", str(document["revision"])),
            ("系统订单号", document.get("system_number", "")),
            ("订单状态", document.get("status", "")),
            (
                "资料用途",
                "本单全部规格的计划下单数量；不是库存、实际出货或待办差额。回导先核对原单，不新增第二笔订单；更改请回原订单更正。",
            ),
            ("待核事项", "；".join(missing) or "无"),
        ]:
            note.append(row)
        note.column_dimensions["A"].width = 20
        note.column_dimensions["B"].width = 95
        for row in note:
            for cell in row:
                cell.data_type = "s"
    style_business_sheet(sheet, (18, 20, 40, 18))
    out = BytesIO()
    book.save(out)
    book.close()
    return out.getvalue()
