# ruff: noqa: RUF001 -- Chinese user-facing punctuation.
"""Bounded extraction of explicit manual-table layouts."""

import hashlib
import re
import unicodedata
from collections import Counter
from datetime import date, datetime
from io import BytesIO
from typing import Any
from zipfile import BadZipFile, ZipFile

import openpyxl  # type: ignore[import-untyped]

from app.api.errors import ApiError
from app.catalog.errors import CatalogNormalizationError
from app.catalog.normalization import catalog_identity_key_v1
from app.catalog.source_formatting import FORMAT_REASON, format_identity_field
from app.manual_tables.schemas import FIELDS, SIZES, Kind, Options, issue
from app.production.source_registry import validate_upload

ALIASES = {
    "style": ("款号", "新款号", "style", "stylecode"),
    "color": ("颜色", "color", "colour"),
    "size": ("尺码", "size"),
    "units": ("数量", "结存数量", "预计数量", "箱内数量", "本次实际出货数量"),
    "code": ("sku", "sellersku", "卖家sku", "原商品编码"),
    "total": ("合计", "qty", "总数量", "原表合计"),
    "warehouse": ("库位", "仓库"),
    "date": ("业务日期", "下单日期", "poplaceddate", "库存日期", "实际出货日期"),
    "planned_date": ("delivery", "预计出货日期", "出货日期"),
    "number": ("来源单号", "业务单号"),
    "box": ("箱号",),
    "asin": ("asin",),
    "fnsku": ("fnsku",),
    "dispatched": ("实际已发",),
    "basis": ("结存口径",),
    "order_number": ("对应系统订单号",),
    "source_line": ("来源行标识",),
    "notes": ("备注",),
}


def text(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, (datetime, date)):
        return (
            value.date().isoformat()
            if isinstance(value, datetime)
            else value.isoformat()
        )
    if isinstance(value, float) and value.is_integer():
        return str(int(value))
    return str(value)


def header(value: Any) -> str:
    return re.sub(r"\s+", "", unicodedata.normalize("NFKC", text(value))).lower()


def read_book(content: bytes) -> Any:
    validate_upload("manual.xlsx", content)
    try:
        with ZipFile(BytesIO(content)) as archive:
            if any(
                "externallinks/" in v.lower() or v.lower().endswith("vbaproject.bin")
                for v in archive.namelist()
            ):
                raise ApiError(
                    422,
                    "manual_external_content",
                    "文件包含外部链接或宏，请提供不含这些内容的XLSX副本。",
                )
        book = openpyxl.load_workbook(
            BytesIO(content), data_only=False, keep_links=False
        )
    except (BadZipFile, ValueError, KeyError) as error:
        raise ApiError(
            422,
            "manual_unreadable",
            "无法读取表格，请提供未加密且可正常打开的XLSX文件。",
        ) from error
    if len(book.sheetnames) > 10:
        book.close()
        raise ApiError(
            413, "manual_sheet_limit", "工作表超过10张，请保留需要整理的业务页。"
        )
    return book


def columns_at(sheet: Any, row: int) -> tuple[dict[str, int], list[str]]:
    columns: dict[str, int] = {}
    duplicates = []
    for col in range(1, min(sheet.max_column, 80) + 1):
        h = header(sheet.cell(row, col).value)
        name = next((key for key, aliases in ALIASES.items() if h in aliases), "")
        if h.upper() in SIZES:
            name = h.upper()
        if re.fullmatch(r"箱\d+", h):
            name = h
        if name:
            if name in columns:
                duplicates.append(name)
            else:
                columns[name] = col
    return columns, duplicates


def extract(content: bytes, kind: Kind, options: Options) -> dict[str, Any]:
    book = read_book(content)
    try:
        return _extract(book, content, kind, options)
    finally:
        book.close()


def _extract(book: Any, content: bytes, kind: Kind, options: Options) -> dict[str, Any]:
    sheets = [
        {"name": s.title, "rows": s.max_row, "columns": s.max_column}
        for s in book
        if any(
            c.value is not None
            for row in s.iter_rows(
                max_row=min(s.max_row, 20), max_col=min(s.max_column, 80)
            )
            for c in row
        )
    ]
    candidates = []
    for info in sheets:
        sheet = book[info["name"]]
        for row in range(1, min(sheet.max_row, 20) + 1):
            cols, _ = columns_at(sheet, row)
            # A known official schema is never reclassified by its filename.
            heads = {
                header(sheet.cell(row, c).value)
                for c in range(1, min(sheet.max_column, 80) + 1)
            }
            if (
                {"return-date", "reason", "sku"} <= heads
                or {"(child)asin", "unitsordered"} <= heads
                or {"子asin", "已订购商品数量"} <= heads
                or {"(子)asin", "已订购商品数量"} <= heads
            ):
                raise ApiError(
                    422,
                    "official_report_route",
                    "识别到平台官方报表结构，请使用原经营报告或退货报告入口；人工整理不改变官方证据。",
                )
            has_quantity = (
                "units" in cols
                or any(v in cols for v in SIZES)
                or any(v.startswith("箱") for v in cols)
            )
            if has_quantity and (
                "style" in cols
                or "code" in cols
                or (
                    kind == "packing"
                    and "total" in cols
                    and any(v.startswith("箱") for v in cols)
                )
            ):
                candidates.append((sheet.title, row, cols))
    chosen = [
        (name, row, cols)
        for name, row, cols in candidates
        if (not options.sheet or name == options.sheet)
        and (options.header_row is None or row == options.header_row)
    ]
    issues: list[dict[str, Any]] = []
    result: dict[str, Any] = {
        "kind": kind,
        "sheets": sheets,
        "candidates": [{"sheet": n, "header_row": r} for n, r, _ in candidates],
        "rows": [],
        "issues": issues,
        "excluded_rows": [],
        "total_units": "0",
        "state": "NEEDS_MAPPING",
        "columns": {},
        "sheet": options.sheet,
        "header_row": options.header_row,
        "samples": [],
        "source_digest": hashlib.sha256(content).hexdigest(),
    }
    if len(chosen) != 1:
        if options.sheet in book.sheetnames and options.header_row:
            chosen = [
                (
                    options.sheet,
                    options.header_row,
                    columns_at(book[options.sheet], options.header_row)[0],
                )
            ]
        else:
            issues.append(
                issue(
                    "choose_region",
                    "请明确选择业务工作表和表头行，避免将多块资料混在一起。",
                    suggestion="在字段对应中选择工作表与表头行。",
                )
            )
            return result
    name, hrow, columns = chosen[0]
    sheet = book[name]
    _, duplicates = columns_at(sheet, hrow)
    for duplicate in duplicates:
        if duplicate not in options.columns:
            issues.append(
                issue(
                    "duplicate_header",
                    f"字段“{FIELDS.get(duplicate, duplicate)}”出现多次，请选择具体列。",
                    row=hrow,
                    sheet=name,
                )
            )
    allowed = set(FIELDS) | set(SIZES) | {f"箱{i}" for i in range(1, 81)}
    if any(k not in allowed or not 0 <= v <= 80 for k, v in options.columns.items()):
        raise ApiError(
            422,
            "manual_columns_invalid",
            "列对应无效，请选择表格中1至80列内的业务字段。",
        )
    columns.update(options.columns)
    columns = {k: v for k, v in columns.items() if v}
    if (
        "total" not in columns
        and "units" in columns
        and any(k in columns for k in (*SIZES, *(f"箱{i}" for i in range(1, 81))))
    ):
        columns["total"] = columns.pop("units")
    result.update(
        sheet=name,
        header_row=hrow,
        columns=columns,
        layout_signature=hashlib.sha256(
            (
                name
                + str(
                    [
                        (c, header(sheet.cell(hrow, c).value))
                        for c in range(1, min(80, sheet.max_column) + 1)
                    ]
                )
            ).encode()
        ).hexdigest(),
    )
    first = options.start_row or hrow + 1
    last = options.end_row or sheet.max_row
    if first == hrow + 1 and last == hrow:
        issues.append(
            issue(
                "no_rows",
                "表格只有表头，请先填写商品与数量再上传。",
                sheet=name,
                row=hrow,
            )
        )
        result["state"] = "NEEDS_REVIEW"
        return result
    if (
        first <= hrow
        or last < first
        or last - first + 1 > 2000
        or sheet.max_column > 80
        or (last - first + 1) * sheet.max_column > 100000
    ):
        raise ApiError(
            413,
            "manual_region_limit",
            "请选择表头之后、不超过2000行和100000格的业务区域；表格最多80列。",
        )
    result["samples"] = [
        [
            {
                "column": c,
                "value": text(sheet.cell(r, c).value),
                "cell": sheet.cell(r, c).coordinate,
            }
            for c in range(1, min(sheet.max_column, 80) + 1)
        ]
        for r in range(hrow, min(last, hrow + 4) + 1)
    ]
    result["region"] = {
        "first": first,
        "last": last,
        "outside_rows": max(0, first - hrow - 1) + max(0, sheet.max_row - last),
    }
    matrix = [s for s in SIZES if s in columns]
    boxes = [s for s in columns if s.startswith("箱") and s != "box"]
    unmapped_sizes = [
        c
        for c in range(1, sheet.max_column + 1)
        if re.fullmatch(r"(?:[2-9]XL|X{3,}L)", text(sheet.cell(hrow, c).value).upper())
        and c not in columns.values()
    ]
    if unmapped_sizes:
        issues.append(
            issue(
                "unsupported_size",
                "原表含未对应的尺码列，请明确对应标准尺码；不能忽略其中数量。",
                sheet=name,
                row=hrow,
                suggestion="在字段对应中为标准尺码选择原列；不支持的尺码须回原表核对。",
            )
        )
    if matrix and boxes:
        issues.append(
            issue(
                "mixed_quantity_layout",
                "尺码列与箱内数量列不能同时作为数量明细，请选择本次业务布局。",
                sheet=name,
                row=hrow,
            )
        )
        return result
    identity_ok = "code" in columns or {"style", "color"} <= columns.keys()
    if not identity_ok or not (matrix or boxes or "units" in columns):
        issues.append(
            issue(
                "missing_columns",
                "商品身份或数量列尚未对应。",
                row=hrow,
                sheet=name,
                suggestion="请选择款号与颜色，或原商品编码；再选择尺码数量列/箱内数量列。",
            )
        )
        return result

    def value(row: int, field: str) -> str:
        cell_value = ""
        if field in columns:
            col = columns[field]
            cell_value = text(sheet.cell(row, col).value)
            if not cell_value and field in {"style", "color", "size", "code"}:
                for merged in sheet.merged_cells.ranges:
                    if (
                        merged.min_row <= row <= merged.max_row
                        and merged.min_col <= col <= merged.max_col
                    ):
                        cell_value = text(
                            sheet.cell(merged.min_row, merged.min_col).value
                        )
                        break
        return cell_value or options.context.get(field, "")

    def quantity(row: int, field: str, problems: list[dict[str, Any]]) -> str | None:
        cell = sheet.cell(row, columns[field])
        raw = text(cell.value)
        if raw in ("", "/") and options.zero_policy == "blank_slash_zero":
            return "0"
        code = (
            "quantity_formula"
            if cell.data_type == "f"
            else "quantity_unknown"
            if raw in ("", "/", "—", "待核")
            else "quantity_invalid"
        )
        if (
            cell.data_type != "f"
            and raw.isascii()
            and raw.isdecimal()
            and len(raw) <= 18
        ):
            return str(int(raw))
        problems.append(
            issue(
                code,
                "数量需要明确的非负整数，当前值为“" + (raw or "空白") + "”。",
                row=row,
                cell=cell.coordinate,
                sheet=name,
                suggestion="核对实际数量；空白及斜杠为0的来源可选择明确的零值规则。",
            )
        )
        return None

    rows = result["rows"]
    for r in range(first, last + 1):
        values = [text(sheet.cell(r, c).value) for c in range(1, sheet.max_column + 1)]
        if not any(values):
            result["excluded_rows"].append({"row": r, "reason": "空行"})
            continue
        if any(
            header(v)
            in {
                "合计",
                "总计",
                "subtotal",
                "total",
                "重量kg",
                "重量磅",
                "长",
                "宽",
                "高",
            }
            for v in values[:4]
        ):
            # Numeric-only totals/notes remain visible as excluded source evidence.
            result["excluded_rows"].append(
                {"row": r, "reason": "合计/说明行，未作为商品数量", "values": values}
            )
            continue
        quantity_fields = [*matrix, *boxes, *(["units"] if "units" in columns else [])]
        if (
            not value(r, "style")
            and not value(r, "code")
            and not any(text(sheet.cell(r, columns[k]).value) for k in quantity_fields)
        ):
            result["excluded_rows"].append(
                {"row": r, "reason": "无商品及数量的说明行", "values": values}
            )
            continue
        if (
            header(value(r, "style")) in ALIASES["style"]
            or header(value(r, "code")) in ALIASES["code"]
        ):
            result["excluded_rows"].append({"row": r, "reason": "重复表头"})
            continue
        row_problems: list[dict[str, Any]] = []
        if sheet.row_dimensions[r].hidden:
            row_problems.append(
                issue(
                    "hidden_row",
                    "该商品行处于隐藏状态，请确认包含或排除并填写原因。",
                    row=r,
                    sheet=name,
                )
            )
        for merged in sheet.merged_cells.ranges:
            if merged.min_row <= r <= merged.max_row and any(
                merged.min_col <= columns[v] <= merged.max_col
                for v in [*matrix, *boxes, *(["units"] if "units" in columns else [])]
            ):
                row_problems.append(
                    issue(
                        "merged_quantity",
                        "数量格存在合并，不能确定每行数量，请核对。",
                        row=r,
                        sheet=name,
                    )
                )
        raw_fields = {k: value(r, k) for k in FIELDS}
        for date_field in ("date", "planned_date"):
            if raw_fields[date_field]:
                try:
                    if (
                        date.fromisoformat(raw_fields[date_field]).isoformat()
                        != raw_fields[date_field]
                    ):
                        raise ValueError("date format")
                except ValueError:
                    row_problems.append(
                        issue(
                            "date_invalid",
                            f"{FIELDS[date_field]}不是明确的年-月-日日期，请核对；文件日期不能替代。",
                            sheet=name,
                            row=r,
                            suggestion="重新选择日期列，或忽略该列并按批补充真实日期。",
                        )
                    )
        style, color, size = (
            raw_fields["style"],
            raw_fields["color"],
            raw_fields["size"],
        )
        code = raw_fields["code"]
        if code and "-" in code:
            pieces = code.split("-")
            if kind == "packing" and len(pieces) >= 3 and pieces[-1].upper() in SIZES:
                style = style or pieces[0]
                color = color or "-".join(pieces[1:-1])
                size = size or pieces[-1]
            elif kind == "orders":
                style = style or pieces[0]
                color = color or "-".join(pieces[1:])
        for field in ("style", "color", "code", "size", "date"):
            if field in columns and sheet.cell(r, columns[field]).data_type == "f":
                row_problems.append(
                    issue(
                        "identity_formula",
                        "商品身份或日期字段包含公式，请提供明确文字/日期。",
                        row=r,
                        cell=sheet.cell(r, columns[field]).coordinate,
                        sheet=name,
                    )
                )
        for s in matrix or [size]:
            if matrix and text(sheet.cell(r, columns[s]).value) == "不适用":
                continue
            problems = list(row_problems)
            box_values = {b: quantity(r, b, problems) for b in boxes}
            if boxes:
                amount = (
                    str(sum(int(v) for v in box_values.values() if v is not None))
                    if all(v is not None for v in box_values.values())
                    else None
                )
                field = boxes[0]
            else:
                field = s if matrix else "units"
                amount = quantity(r, field, problems)
            key = f"{name}!{r}:{s or 'row'}"
            item: dict[str, Any] = {
                **raw_fields,
                "style": style,
                "color": color,
                "size": s,
                "units": amount,
                "boxes": box_values,
                "source_line_key": key,
                "source_ref": {
                    "sheet": name,
                    "row": r,
                    "cell": sheet.cell(r, columns[field]).coordinate,
                },
                "raw": {
                    **raw_fields,
                    "quantity": text(sheet.cell(r, columns[field]).value),
                    "boxes": {b: value(r, b) for b in boxes},
                },
                "issues": problems,
                "excluded": False,
            }
            decision = options.decisions.get(key, {})
            invalid = set(decision) - {
                "style",
                "color",
                "size",
                "units",
                "sku_id",
                "reason",
                "excluded",
                "include_hidden",
                "boxes",
                "accept_total",
            }
            if invalid or (decision and not str(decision.get("reason", "")).strip()):
                raise ApiError(
                    422,
                    "manual_decision_reason",
                    "修改或排除原表明细须填写原因，并只修改允许的字段。",
                )
            item["decision"] = decision
            item.update(
                {
                    k: v
                    for k, v in decision.items()
                    if k not in {"reason", "include_hidden", "accept_total"}
                }
            )
            replaced_cells = {
                sheet.cell(r, columns[k]).coordinate
                for k in decision
                if k in {"style", "color", "size"} and k in columns
            }
            problems[:] = [
                p
                for p in problems
                if not (
                    p["code"] == "identity_formula"
                    and p["source_ref"]["cell"] in replaced_cells
                )
            ]
            if decision.get("include_hidden"):
                problems[:] = [p for p in problems if p["code"] != "hidden_row"]
            if "units" in decision or "boxes" in decision:
                problems[:] = [
                    p
                    for p in problems
                    if not p["code"].startswith("quantity_")
                    and p["code"] != "merged_quantity"
                ]
                if "boxes" in decision:
                    vals = decision["boxes"]
                    if (
                        not isinstance(vals, dict)
                        or set(vals) != set(box_values)
                        or any(
                            not isinstance(v, str)
                            or not v.isascii()
                            or not v.isdecimal()
                            or len(v) > 18
                            for v in vals.values()
                        )
                    ):
                        raise ApiError(
                            422,
                            "manual_boxes_invalid",
                            "修改后的各箱数量须为明确非负整数，且箱号保持。",
                        )
                    item["units"] = str(sum(int(v) for v in vals.values()))
                n = item["units"]
                if (
                    not isinstance(n, str)
                    or not n.isascii()
                    or not n.isdecimal()
                    or len(n) > 18
                ):
                    raise ApiError(
                        422, "manual_units_invalid", "修改后的数量须为明确非负整数。"
                    )
                if item["boxes"] and int(n) != sum(
                    int(v) for v in item["boxes"].values() if v is not None
                ):
                    problems.append(
                        issue(
                            "box_decision_mismatch",
                            "修改的商品总数量与各箱合计不一致，请修改箱内数量。",
                            row=r,
                            sheet=name,
                        )
                    )
            item["source_values"] = {k: item[k] for k in ("style", "color", "size")}
            item["format_adjustments"] = []
            for k in ("style", "color", "size"):
                before = item[k]
                if not isinstance(before, str):
                    raise ApiError(
                        422,
                        "manual_identity_invalid",
                        "款号、颜色和尺码的修改值必须为文字，请核对输入。",
                    )
                after, problem = format_identity_field(before, k)
                item[k] = after
                if problem:
                    problems.append(
                        issue("identity_format", problem, row=r, sheet=name)
                    )
                if before != after:
                    item["format_adjustments"].append(
                        {
                            "field": k,
                            "before": before,
                            "after": after,
                            "reason": FORMAT_REASON,
                        }
                    )
            if not item["size"] or item["size"] not in SIZES:
                problems.append(
                    issue(
                        "size_unknown",
                        "尺码不明确，请选择标准尺码。",
                        row=r,
                        sheet=name,
                    )
                )
            if not item["style"] or not item["color"]:
                problems.append(
                    issue(
                        "identity_incomplete",
                        "款号或颜色不明确，请核对商品身份。",
                        row=r,
                        sheet=name,
                    )
                )
            if not item["excluded"]:
                issues.extend(problems)
            rows.append(item)
        selected = [
            v for v in rows if v["source_ref"]["row"] == r and not v["excluded"]
        ]
        total = value(r, "total")
        if (
            selected
            and total
            and not total.startswith("=")
            and total.isdecimal()
            and all(v["units"] is not None for v in selected)
            and sum(int(v["units"]) for v in selected) != int(total)
        ):
            issues.append(
                issue(
                    "total_mismatch",
                    f"本行明细合计与原合计{total}不一致，请核对原表或修改依据。",
                    row=r,
                    cell=sheet.cell(r, columns["total"]).coordinate,
                    sheet=name,
                    suggestion="核实尺码/箱内数量；若原合计有误，可明确采用明细重算并填写原因。",
                    blocking=not any(
                        v.get("decision", {}).get("accept_total") for v in selected
                    ),
                )
            )
    if set(options.decisions) - {r["source_line_key"] for r in rows}:
        raise ApiError(
            422,
            "manual_unknown_line",
            "修改引用了不属于当前业务区域的原行，请刷新核对。",
        )
    if kind == "packing" and "box" in columns and not boxes:
        grouped: dict[Any, dict[str, Any]] = {}
        for r in rows:
            if not r["source_line"] or not r["box"]:
                continue
            group_key = tuple(
                r.get(k)
                for k in (
                    "source_line",
                    "style",
                    "color",
                    "size",
                    "date",
                    "warehouse",
                    "code",
                )
            ) + tuple(r["source_values"][k] for k in ("style", "color", "size"))
            group = grouped.setdefault(group_key, {**r, "boxes": {}, "source_refs": []})
            if r["box"] in group["boxes"]:
                issues.append(
                    issue(
                        "duplicate_box",
                        "同一来源商品与箱号重复，请核对，未自动合并。",
                        **r["source_ref"],
                    )
                )
            group["boxes"][r["box"]] = r["units"]
            group["source_refs"].append(r["source_ref"])
        if grouped and all(r["source_line"] and r["box"] for r in rows):
            rows = list(grouped.values())
            for r in rows:
                r["units"] = (
                    str(sum(int(v) for v in r["boxes"].values()))
                    if all(v is not None for v in r["boxes"].values())
                    else None
                )
                r["box"] = ""
            result["rows"] = rows

    def spec_key(row: dict[str, Any]) -> tuple[str, ...]:
        try:
            return tuple(
                catalog_identity_key_v1(row[k] or "?").text
                for k in ("style", "color", "size")
            )
        except CatalogNormalizationError:
            # Already blocked by identity_format; retain the row for correction.
            return tuple(row[k] for k in ("style", "color", "size"))

    seen = Counter(
        spec_key(r) for r in rows if not r["excluded"] and r["units"] not in (None, "0")
    )
    if options.aggregate_duplicates and not options.aggregation_reason.strip():
        raise ApiError(
            422, "manual_aggregate_reason", "汇总重复规格前请填写独立来源及汇总原因。"
        )
    for r in rows:
        if not r["excluded"] and seen[spec_key(r)] > 1:
            issues.append(
                issue(
                    "duplicate_spec",
                    "同一规格出现多次；请核对是否独立来源或排除错误重复行。",
                    row=r["source_ref"]["row"],
                    sheet=name,
                    blocking=not options.aggregate_duplicates,
                )
            )
    if not any(not r["excluded"] for r in rows):
        issues.append(
            issue("no_rows", "所选区域没有可核对的商品明细，请检查区域和字段对应。")
        )
    if (
        kind != "inventory"
        and rows
        and not any(not r["excluded"] and r["units"] not in (None, "0") for r in rows)
    ):
        issues.append(
            issue("no_business_units", "没有明确的正数量明细，当前只能保存整理资料。")
        )
    result.update(
        total_units=str(
            sum(
                int(r["units"])
                for r in rows
                if not r["excluded"] and r["units"] is not None
            )
        ),
        state="NEEDS_REVIEW" if any(p["blocking"] for p in issues) else "READY",
        excluded_count=sum(r["excluded"] for r in rows),
    )
    return result
