# ruff: noqa: RUF001, E501 -- Chinese cell diagnostics.
"""Bounded text-only reader for Amazon listing workbooks; never decodes images."""

from __future__ import annotations

import hashlib
import re
from pathlib import Path, PurePosixPath
from typing import Any
from zipfile import ZIP_DEFLATED, ZIP_STORED, BadZipFile, ZipFile

import openpyxl  # type: ignore[import-untyped]
from defusedxml import ElementTree as SafeET  # type: ignore[import-untyped]
from defusedxml.common import DefusedXmlException  # type: ignore[import-untyped]
from openpyxl.utils.exceptions import (  # type: ignore[import-untyped]
    InvalidFileException,
)

from app.catalog.candidates import parse_seller_sku_candidate
from app.catalog.listing_registration import SKU_POLICY, check_source_rows
from app.catalog.production_sources import (
    ProductionSourceInputError,
    source_text_problem,
)

MAX_LISTING_BYTES = 64 * 1024 * 1024
LISTING_SCHEMA = "amazon_listing_v1"
_FIELDS = {
    "SKU": "seller_sku",
    "sku": "seller_sku",
    "卖家SKU": "seller_sku",
    "Seller SKU": "seller_sku",
    "Seller SKU（卖家SKU）": "seller_sku",
    "ASIN": "asin",
    "父ASIN": "parent_asin",
    "子ASIN": "child_asin",
    "FNSKU": "fnsku",
    "记录类型": "record_type",
    "款号": "style_code",
    "颜色": "color",
    "标准颜色": "color",
    "尺码": "size",
    "标准尺码": "size",
}
_ASIN = re.compile(r"[A-Z0-9]{10}\Z", re.ASCII)


def read_listing_workbook(path: Path, *, strict_skus: bool = False) -> dict[str, Any]:
    """Return original text and physical locations, keeping unsafe rows as pending."""
    try:
        worksheet_merges: dict[str, tuple[str, ...]] = {}
        if path.stat().st_size > MAX_LISTING_BYTES:
            raise ProductionSourceInputError(
                ["亚马逊商品清单最多64MiB，请缩小文件后上传。"]
            )
        with path.open("rb") as signature:
            if signature.read(4) != b"PK\x03\x04":
                raise ProductionSourceInputError(
                    [
                        "文件实际格式不是XLSX，请用Excel或WPS另存为.xlsx，不要只修改扩展名。"
                    ]
                )
        with ZipFile(path) as archive:
            entries = archive.infolist()
            names = [entry.filename for entry in entries]
            if len(entries) > 5000 or len(set(names)) != len(names):
                raise ProductionSourceInputError(
                    ["工作簿部件过多或重名，请重新另存为XLSX。"]
                )
            if not {"[Content_Types].xml", "_rels/.rels", "xl/workbook.xml"}.issubset(
                names
            ):
                raise ProductionSourceInputError(
                    ["文件不是有效的XLSX工作簿，请另存为.xlsx后上传。"]
                )
            expanded = 0
            # Check the complete directory and budgets before decompressing any XML.
            for entry in entries:
                name = entry.filename
                if (
                    "\\" in name
                    or PurePosixPath(name).is_absolute()
                    or ".." in PurePosixPath(name).parts
                    or entry.flag_bits & 1
                    or entry.compress_type not in {ZIP_STORED, ZIP_DEFLATED}
                ):
                    raise ProductionSourceInputError(
                        ["工作簿包含不安全的路径或加密内容。"]
                    )
                if any(
                    part in name.lower()
                    for part in (
                        "vbaproject",
                        "externallinks/",
                        "embeddings/",
                        "activex/",
                    )
                ):
                    raise ProductionSourceInputError(
                        ["工作簿包含宏、外部链接或嵌入对象，请移除后另存为XLSX。"]
                    )
                if name.lower().endswith((".xml", ".rels")):
                    expanded += entry.file_size
                    if expanded > 32 * 1024 * 1024:
                        raise ProductionSourceInputError(
                            ["工作簿文字内容解压后超过32MiB，请拆分清单。"]
                        )
            for entry in entries:
                name = entry.filename
                if name.lower().endswith((".xml", ".rels")):
                    root = SafeET.fromstring(archive.read(entry), forbid_dtd=True)
                    if name == "[Content_Types].xml" and not any(
                        node.attrib.get("PartName") == "/xl/workbook.xml"
                        and node.attrib.get("ContentType")
                        == "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml"
                        for node in root
                    ):
                        raise ProductionSourceInputError(
                            ["仅支持普通XLSX工作簿，不支持宏工作簿、模板或二进制表格。"]
                        )
                    if any(
                        marker in value.lower()
                        for node in root
                        for value in [
                            node.attrib.get("ContentType", ""),
                            node.attrib.get("Type", ""),
                        ]
                        for marker in (
                            "macroenabled",
                            "vbaproject",
                            "oleobject",
                            "activex",
                        )
                    ):
                        raise ProductionSourceInputError(
                            ["工作簿包含宏或嵌入对象，请移除后另存为XLSX。"]
                        )
                    if name.lower().endswith(".rels") and any(
                        node.attrib.get("TargetMode") != "External"
                        and node.attrib.get("Type", "").rsplit("/", 1)[-1]
                        in {"worksheet", "sharedStrings", "styles", "theme"}
                        and not node.attrib.get("Target", "").lower().endswith(".xml")
                        for node in root
                    ):
                        raise ProductionSourceInputError(
                            ["工作簿数据部件格式异常，请另存为标准XLSX后上传。"]
                        )
                    if name.endswith(".rels") and any(
                        n.attrib.get("TargetMode") == "External"
                        and not (
                            name.startswith("xl/worksheets/_rels/")
                            and n.attrib.get("Type", "").endswith("/hyperlink")
                        )
                        and not (
                            name.startswith("xl/drawings/_rels/")
                            and n.attrib.get("Type", "").endswith("/image")
                        )
                        for n in root
                    ):
                        raise ProductionSourceInputError(
                            ["工作簿含外部链接，请移除后上传。"]
                        )
                    if name.startswith("xl/worksheets/"):
                        worksheet_merges[name] = tuple(
                            node.attrib.get("ref", "")
                            for node in root.iter()
                            if node.tag.rsplit("}", 1)[-1] == "mergeCell"
                        )
                        for node in root.iter():
                            tag = node.tag.rsplit("}", 1)[-1]
                            if (
                                tag in {"row", "col"}
                                and node.attrib.get("hidden") in {"1", "true"}
                                and (
                                    tag == "row"
                                    or int(node.attrib.get("max", "2")) >= 2
                                )
                            ):
                                raise ProductionSourceInputError(
                                    [
                                        f"工作表隐藏{('行' if tag == 'row' else '列')}{node.attrib.get('r', node.attrib.get('min', ''))}：请取消隐藏后核对。"
                                    ]
                                )
        input_stream = path.open("rb")
        try:
            book = openpyxl.load_workbook(
                input_stream, read_only=True, data_only=False, keep_links=False
            )
        except Exception:
            input_stream.close()
            raise
        try:
            if not 1 <= len(book.worksheets) <= 10 or any(
                w.sheet_state != "visible" for w in book
            ):
                raise ProductionSourceInputError(
                    ["请保留1至10张可见的商品清单工作表。"]
                )
            rows, sheets = [], []
            for sheet_index, sheet in enumerate(book, 1):
                if sheet.max_column > 16 or sheet.max_row > 1010:
                    raise ProductionSourceInputError(
                        [
                            f"工作表“{sheet.title}”：业务范围最多16列、1000条清单记录，请移除多余格式或拆分。"
                        ]
                    )
                headers = []
                for cells in sheet.iter_rows(min_row=1, max_row=min(10, sheet.max_row)):
                    fields = {
                        i: _FIELDS[c.value]
                        for i, c in enumerate(cells)
                        if isinstance(c.value, str) and c.value in _FIELDS
                    }
                    if "seller_sku" in fields.values() and (
                        strict_skus
                        or {"asin", "child_asin", "parent_asin"} & set(fields.values())
                    ):
                        headers.append(
                            (next(c.row for c in cells if hasattr(c, "row")), fields)
                        )
                if len(headers) != 1:
                    raise ProductionSourceInputError(
                        [
                            f"工作表“{sheet.title}”：前10行须有唯一的卖家SKU及ASIN表头，请检查表头或重复标题。"
                        ]
                    )
                header_row, fields = headers[0]
                for merged in worksheet_merges.get(sheet._worksheet_path, ()):
                    if re.fullmatch(r"A\d+:A\d+", merged):
                        continue
                    try:
                        _, _, _, max_row = openpyxl.utils.range_boundaries(merged)
                    except ValueError as error:
                        raise ProductionSourceInputError(
                            [
                                f"工作表“{sheet.title}”：合并区域{merged}无法识别，请取消合并。"
                            ]
                        ) from error
                    if max_row >= header_row:
                        raise ProductionSourceInputError(
                            [
                                f"工作表“{sheet.title}”：合并区域{merged}涉及表头或业务数据，请取消合并。"
                            ]
                        )
                if len(set(fields.values())) != len(fields):
                    raise ProductionSourceInputError(
                        [
                            f"工作表“{sheet.title}”：存在重复业务列，请每个字段只保留一列。"
                        ]
                    )
                count = 0
                for cells in sheet.iter_rows(min_row=header_row + 1):
                    if not any(cells[i].value is not None for i in fields):
                        continue
                    number = next(c.row for c in cells if hasattr(c, "row"))
                    row = {
                        "row_id": f"s{sheet_index}-r{number}",
                        "sheet": sheet.title,
                        "row": number,
                        "issues": [],
                        "cell_types": {},
                        "cell_locations": {},
                    }
                    for col, field in fields.items():
                        cell = cells[col]
                        value = cell.value
                        row["cell_types"][field] = cell.data_type
                        row["cell_locations"][field] = (
                            f"{openpyxl.utils.get_column_letter(col + 1)}{number}"
                        )
                        row[field] = "" if value is None else str(value)
                        place = f"工作表“{sheet.title}”，第{number}行{openpyxl.utils.get_column_letter(col + 1)}列"
                        if value is not None and (
                            not isinstance(value, str) or cell.data_type in {"f", "e"}
                        ):
                            row["issues"].append(
                                f"{place}：须核对原值及前导零，设为文本并重新输入；数字型父级候选可在页面明确确认类型和原码。"
                            )
                        elif isinstance(value, str) and value:
                            problem = source_text_problem(value)
                            if problem:
                                row["issues"].append(f"{place}：{problem}")
                        if (
                            field in {"asin", "parent_asin", "child_asin"}
                            and value
                            and not _ASIN.fullmatch(str(value))
                        ):
                            row["issues"].append(
                                f"{place}：ASIN须为10位半角大写字母或数字，请核对原值。"
                            )
                    raw = row.get("seller_sku", "")
                    if not raw:
                        row["issues"].append(
                            f"工作表“{sheet.title}”，第{number}行：卖家SKU不能为空。"
                        )
                    candidate = parse_seller_sku_candidate(raw)
                    explicit_specs = any(
                        row.get(field) for field in ("style_code", "color", "size")
                    )
                    row["suggestion"] = (
                        {
                            field: row.get(field, "")
                            for field in ("style_code", "color", "size")
                        }
                        if explicit_specs
                        else (
                            {
                                "style_code": candidate[0],
                                "color": candidate[1],
                                "size": candidate[2],
                            }
                            if candidate
                            else None
                        )
                    )
                    row["suggested_type"] = (
                        "parent"
                        if row.get("record_type")
                        in {"parent", "父级", "父级／款式记录"}
                        else "variant"
                        if candidate
                        or explicit_specs
                        or row.get("record_type") in {"variant", "具体商品规格"}
                        else "unknown"
                    )
                    if candidate and candidate[2] == "XLL":
                        row["issues"].append(
                            f"工作表“{sheet.title}”，第{number}行：尺码XLL需核对，不会自动改为XL或XXL。"
                        )
                    rows.append(row)
                    count += 1
                    if len(rows) > 1000:
                        raise ProductionSourceInputError(
                            ["每批最多1000条非空商品记录，请拆分清单。"]
                        )
                sheets.append({"name": sheet.title, "count": count})
            if not rows:
                raise ProductionSourceInputError(
                    ["清单没有商品编码记录，请填写后上传。"]
                )
            if strict_skus:
                check_source_rows(rows)
            return {
                **({"sku_format_policy": SKU_POLICY} if strict_skus else {}),
                "source_schema": LISTING_SCHEMA,
                "sheets": sheets,
                "listing_rows": rows,
            }
        finally:
            book.close()
            input_stream.close()
    except ProductionSourceInputError:
        raise
    except (
        BadZipFile,
        InvalidFileException,
        OSError,
        ValueError,
        KeyError,
        DefusedXmlException,
        SafeET.ParseError,
    ) as error:
        raise ProductionSourceInputError(
            [
                "文件无法读取，请使用未加密的XLSX商品清单。图片可以保留，业务列须为明确文本。"
            ]
        ) from error


def source_digest(value: dict[str, Any]) -> str:
    from app.catalog.canonical_json import canonical_json_bytes

    return hashlib.sha256(canonical_json_bytes(value)).hexdigest()
