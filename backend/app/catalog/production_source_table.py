# ruff: noqa: RUF001 -- Chinese user-facing punctuation.
"""Bounded production specification parsing with actionable cell diagnostics."""

from __future__ import annotations

import base64
import csv
import io
from typing import cast
from zipfile import BadZipFile, ZipFile

import openpyxl  # type: ignore[import-untyped]
from defusedxml import ElementTree as SafeElementTree  # type: ignore[import-untyped]
from defusedxml.common import DefusedXmlException  # type: ignore[import-untyped]
from pydantic import ValidationError

from app.catalog.production_sources import (
    ProductionSource,
    ProductionSourceInputError,
    ProductionSourceRow,
    source_text_problem,
)
from app.catalog.source_formatting import format_identity_field

HEADERS = ["款号", "颜色", "尺码", "正式SKU"]


def render_production_source_template() -> bytes:
    """Blank registration template; text cells preserve business identifiers."""
    book = openpyxl.Workbook()
    sheet = book.active
    sheet.title = "商品建档"
    sheet.append(HEADERS)
    sheet.freeze_panes = "A2"
    for column, width in zip("ABCD", (24, 28, 16, 40), strict=True):
        sheet.column_dimensions[column].width = width
    for row in sheet.iter_rows(min_row=2, max_row=1001, max_col=4):
        for cell in row:
            cell.number_format = "@"
    output = io.BytesIO()
    book.save(output)
    book.close()
    return output.getvalue()


def parse_production_table(
    source_name: str, kind: str, content: str
) -> tuple[ProductionSource, list[str]]:
    issues: list[str] = []
    problem: str | None
    table: list[tuple[int, list[object]]] = []
    sheet = "文本表格"
    try:
        if kind == "xlsx":
            raw = base64.b64decode(content, validate=True)
            if len(raw) > 1_000_000:
                raise ProductionSourceInputError(["文件超过1MB，请拆分后上传。"])
            with ZipFile(io.BytesIO(raw)) as package:
                members = package.infolist()
                if len(members) > 1000 or sum(m.file_size for m in members) > 8_000_000:
                    raise ProductionSourceInputError(
                        ["工作簿内容过大，请仅保留本批规格表。"]
                    )
                for member in members:
                    if member.filename.endswith(".rels"):
                        root = SafeElementTree.fromstring(package.read(member))
                        if any(n.attrib.get("TargetMode") == "External" for n in root):
                            raise ProductionSourceInputError(
                                ["工作簿含外部链接，请移除链接并粘贴明确文本。"]
                            )
                    if member.filename.startswith(
                        "xl/worksheets/"
                    ) and member.filename.endswith(".xml"):
                        root = SafeElementTree.fromstring(package.read(member))
                        for node in root.iter():
                            tag = node.tag.rsplit("}", 1)[-1]
                            if tag == "mergeCell":
                                issues.append(
                                    f"工作表合并区域{node.attrib.get('ref', '')}："
                                    "请取消合并，每行填写完整规格。"
                                )
                            if tag in {"row", "col"} and node.attrib.get("hidden") in {
                                "1",
                                "true",
                            }:
                                position = node.attrib.get(
                                    "r", node.attrib.get("min", "")
                                )
                                issues.append(
                                    f"工作表隐藏{('行' if tag == 'row' else '列')}"
                                    f"{position}："
                                    "请取消隐藏后核对内容。"
                                )
            book = openpyxl.load_workbook(
                io.BytesIO(raw), read_only=True, data_only=False
            )
            try:
                if len(book.worksheets) != 1 or book.active.sheet_state != "visible":
                    raise ProductionSourceInputError(["请仅保留一张可见的规格工作表。"])
                ws = book.active
                sheet = ws.title
                if ws.max_column not in (3, 4) or ws.max_row > 1001:
                    raise ProductionSourceInputError(
                        [
                            f"工作表“{sheet}”：最多1000行数据、3或4列；请使用款号、颜色、尺码及可选的正式SKU列。"
                        ]
                    )
                for cells in ws.iter_rows():
                    row = cells[0].row if hasattr(cells[0], "row") else len(table) + 1
                    values: list[object] = []
                    for col, cell in enumerate(cells):
                        value = cell.value
                        if cell.data_type == "f" or (
                            value is not None
                            and (not isinstance(value, str) or cell.data_type == "e")
                        ):
                            problem = (
                                "不允许公式"
                                if cell.data_type == "f"
                                else "必须为文本，不能是数字、日期或错误值"
                            )
                            issues.append(
                                f"工作表“{sheet}”，第{row}行{chr(65 + col)}列："
                                f"{problem}；"
                                "请核对原值（含前导零），设为文本并重新输入。"
                            )
                        values.append(value if value is not None else "")
                    table.append((row, values))
            finally:
                book.close()
        else:
            if len(content) > 256_000:
                raise ProductionSourceInputError(
                    ["文本表格过大，请拆分为每批最多1000行。"]
                )
            reader = csv.reader(
                io.StringIO(content.removeprefix("\ufeff")),
                delimiter="\t" if kind == "tsv" else ",",
                strict=True,
            )
            while True:
                row = reader.line_num + 1
                try:
                    table.append((row, list(next(reader))))
                except StopIteration:
                    break
                if len(table) > 1001:
                    raise ProductionSourceInputError(["最多1000行数据，请拆分后上传。"])
    except ProductionSourceInputError:
        raise
    except (
        ValueError,
        BadZipFile,
        KeyError,
        OSError,
        csv.Error,
        DefusedXmlException,
        SafeElementTree.ParseError,
    ) as error:
        raise ProductionSourceInputError(
            [
                "文件无法读取，请使用未加密的单页XLSX，或UTF-8编码的CSV/TSV；检查分隔符和引号是否完整。"
            ]
        ) from error
    if not table:
        raise ProductionSourceInputError(["表格为空，请添加表头和至少一行规格。"])
    header = table[0][1]
    if header not in (HEADERS[:3], HEADERS):
        for col in range(max(3, len(header))):
            expected = HEADERS[col] if col < 4 else None
            actual = header[col] if col < len(header) else None
            if actual != expected:
                issues.append(
                    f"工作表“{sheet}”，第1行{chr(65 + col)}列："
                    + (
                        f"表头必须为“{expected}”，请按模板顺序填写，不加空格。"
                        if expected
                        else "多余列，请移除；库存数量不在商品规格表中登记。"
                    )
                )
        raise ProductionSourceInputError(issues)
    rows: list[ProductionSourceRow] = []
    locations: list[str] = []
    for number, values in table[1:]:
        if all(value == "" for value in values):
            continue
        place = f"工作表“{sheet}”，第{number}行"
        if len(values) != len(header):
            issues.append(f"{place}：应有{len(header)}列，请检查分隔符或多余列。")
            continue
        valid = True
        for col, value in enumerate(values):
            if not isinstance(value, str):
                valid = False
                continue
            checked = (
                format_identity_field(value, ("style", "color", "size")[col])[0]
                if col < 3
                else value
            )
            problem = source_text_problem(checked) if col < 3 or value else None
            if problem:
                issues.append(f"{place}{chr(65 + col)}列（{HEADERS[col]}）：{problem}")
                valid = False
        if valid:
            try:
                texts = cast(list[str], values)
                rows.append(
                    ProductionSourceRow(
                        style_code=texts[0],
                        color=texts[1],
                        size=texts[2],
                        formal_sku=(texts[3] or None) if len(texts) == 4 else None,
                        source_location=place,
                    )
                )
                locations.append(place)
            except ValidationError:
                issues.append(
                    f"{place}：规格不是有效文本，请核对款号、颜色、尺码和正式SKU。"
                )
    if not rows and not issues:
        issues.append("没有数据行，请在表头下填写至少一行规格。")
    if issues:
        raise ProductionSourceInputError(issues)
    return ProductionSource(source_name=source_name, rows=rows), locations
