# ruff: noqa: RUF001 -- Chinese import diagnostics.
"""Read-only opening workbook adapter; preview/confirmation remains the stock writer."""

import hashlib
import re
from io import BytesIO
from pathlib import Path
from typing import Any
from xml.etree.ElementTree import ParseError
from zipfile import ZipFile

import openpyxl  # type: ignore[import-untyped]
from openpyxl.styles import Alignment  # type: ignore[import-untyped]

from app.api.errors import ApiError
from app.production.order_tables import style_business_sheet, table_quantity, value
from app.production.source_registry import validate_upload

HEADERS = ("SKU", "合格数量", "待检数量", "次品数量")
QUALITIES = ("QUALIFIED", "PENDING", "DEFECTIVE")


def source_path(root: str, site: int, actor: int, digest: str) -> Path:
    if not root or not re.fullmatch(r"[a-f0-9]{64}", digest):
        raise ApiError(422, "opening_source", "期初来源标识无效。")
    return Path(root) / "opening-uploads" / str(site) / str(actor) / f"{digest}.xlsx"


def read_source(root: str, site: int, actor: int, digest: str) -> bytes:
    path = source_path(root, site, actor, digest)
    if not path.is_file():
        raise ApiError(404, "opening_source", "本账号没有这份期初来源。")
    raw = path.read_bytes()
    if hashlib.sha256(raw).hexdigest() != digest:
        raise ApiError(
            409, "opening_source_changed", "期初来源副本已改变，请重新核对。"
        )
    return raw


def retain_source(root: str, site: int, actor: int, raw: bytes) -> str:
    digest = hashlib.sha256(raw).hexdigest()
    path = source_path(root, site, actor, digest)
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        with path.open("xb") as target:
            target.write(raw)
    except FileExistsError:
        read_source(root, site, actor, digest)
    return digest


def opening_template(catalog: dict[str, Any]) -> bytes:
    book = openpyxl.Workbook()
    sheet = book.active
    sheet.title = "期初库存"
    sheet.append(HEADERS)
    for sku in catalog.values():
        sheet.append([sku.get("code"), None, None, None])
    style_business_sheet(sheet, (28, 18, 18, 18))
    for row in sheet:
        for cell in row:
            cell.alignment = Alignment(horizontal="center", vertical="center")
    output = BytesIO()
    book.save(output)
    book.close()
    return output.getvalue()


def parse_opening(raw: bytes, filename: str, catalog: dict[str, Any]) -> dict[str, Any]:
    if len(raw) > 2 * 1024 * 1024:
        raise ApiError(413, "opening_file_large", "期初表不能超过2MiB。")
    validate_upload(filename, raw)
    with ZipFile(BytesIO(raw)) as archive:
        if any(
            any(
                part in name.lower()
                for part in ("vbaproject", "externallinks/", "embeddings/", "activex/")
            )
            for name in archive.namelist()
        ):
            raise ApiError(
                422, "opening_external", "期初表不支持宏、外部链接或嵌入对象。"
            )
    try:
        book = openpyxl.load_workbook(BytesIO(raw), data_only=False, keep_links=False)
    except (ValueError, KeyError, OSError, ParseError) as error:
        raise ApiError(
            422, "opening_workbook", "期初表无法读取，请重新另存为普通XLSX后上传。"
        ) from error
    try:
        if len(book.worksheets) != 1:
            raise ApiError(422, "opening_sheet", "期初表只保留一张工作表。")
        sheet = book.active
        if (
            sheet.max_row > 1001
            or sheet.max_column != 4
            or tuple(value(c.value) for c in sheet[1]) != HEADERS
        ):
            raise ApiError(
                422,
                "opening_header",
                "请使用期初模板：SKU、合格数量、待检数量、次品数量，最多1000条。",
            )
        codes: dict[str, list[str]] = {}
        for sku_id, sku in catalog.items():
            if sku.get("code"):
                codes.setdefault(str(sku["code"]), []).append(str(sku_id))
        lines = []
        issues = []
        seen = set()
        for n, row in enumerate(sheet.iter_rows(min_row=2), 2):
            values = [value(c.value) for c in row]
            if not any(values):
                continue
            code = values[0]
            if (
                sheet.row_dimensions[n].hidden
                or sheet.merged_cells.ranges
                or any(d.hidden for d in sheet.column_dimensions.values())
            ):
                issues.append(f"{sheet.title}!A{n}:D{n}：请取消隐藏与合并后重新上传。")
                continue
            if row[0].data_type == "f" or len(codes.get(code, [])) != 1 or code in seen:
                issues.append(
                    f"{sheet.title}!A{n}：SKU不存在、不唯一或重复；请保持正式编码的大小写及空格。"
                )
                continue
            seen.add(code)
            for index, quality in enumerate(QUALITIES, 1):
                units = table_quantity(row[index], values[index], positive=False)
                if units is None:
                    issues.append(
                        f"{sheet.title}!{chr(65 + index)}{n}：请填写非负整数；"
                        "明确没有填0，不能留空或使用公式。"
                    )
                else:
                    lines.append(
                        {
                            "sku_id": codes[code][0],
                            "quality": quality,
                            "units": str(units),
                        }
                    )
        if issues or not lines:
            raise ApiError(
                422,
                "opening_rows",
                "\n".join(issues[:30]) or "期初表没有可导入的明细。",
            )
        return {"lines": lines, "sku_count": len(seen)}
    finally:
        book.close()
