"""Scope-bound count totals for the existing ADJUST draft/preview/confirm path."""

# ruff: noqa: RUF001
from io import BytesIO
from typing import Any
from xml.etree.ElementTree import ParseError
from zipfile import BadZipFile, ZipFile

from openpyxl import Workbook, load_workbook  # type: ignore[import-untyped]
from openpyxl.utils.exceptions import (  # type: ignore[import-untyped]
    InvalidFileException,
)

from app.api.errors import ApiError
from app.production.order_tables import table_quantity
from app.production.source_registry import validate_upload

HEADERS = ["商品规格ID（勿改）", "商品规格（核对用）", "货品状态", "实盘总数"]
QUALITIES = {"合格": "QUALIFIED", "待检": "PENDING", "次品": "DEFECTIVE"}


def count_template(scope: dict[str, Any], catalog: dict[str, Any]) -> bytes:
    book = Workbook()
    sheet = book.active
    sheet.title = "库存盘点"
    sheet.append(HEADERS)
    for sku, item in catalog.items():
        for quality in QUALITIES:
            sheet.append([str(sku), item["label"], quality, None])
    sheet.freeze_panes = "C2"
    for row in sheet.iter_rows(min_row=2):
        row[0].number_format = "@"
    for column, width in zip("ABCD", (26, 44, 16, 18), strict=True):
        sheet.column_dimensions[column].width = width
    meta = book.create_sheet("模板说明")
    meta.append(["模板版本", "clsen-count-v1"])
    meta.append(["仓库ID", str(scope["warehouse_id"])])
    meta.append(["货主ID", str(scope["owner_id"])])
    meta.append(
        [
            "数量说明",
            "填写该状态实际清点的总数，0有效；空白不登记，不是增减差额。每批最多500条。",
        ]
    )
    output = BytesIO()
    book.save(output)
    book.close()
    return output.getvalue()


def preview_count(
    raw: bytes, filename: str, scope: dict[str, Any], catalog: dict[str, Any]
) -> dict[str, Any]:
    name = validate_upload(filename, raw)
    with ZipFile(BytesIO(raw)) as archive:
        if any(
            path.startswith("xl/externalLinks/") or path.endswith("vbaProject.bin")
            for path in archive.namelist()
        ):
            raise ApiError(422, "external_workbook", "盘点表不能包含外部链接或宏。")
    try:
        book = load_workbook(
            BytesIO(raw), read_only=False, data_only=False, keep_links=False
        )
    except (
        ValueError,
        OSError,
        KeyError,
        ParseError,
        BadZipFile,
        InvalidFileException,
    ) as error:
        raise ApiError(
            422, "invalid_workbook", "盘点表无法读取，请重新下载当前仓库模板。"
        ) from error
    issues, rows, seen = [], [], set()
    try:
        if book.sheetnames != ["库存盘点", "模板说明"]:
            raise ApiError(
                422,
                "invalid_header",
                "请使用当前仓库的盘点模板；其他排版原表仍从原表整理入口办理。",
            )
        sheet = book["库存盘点"]
        if sheet.max_column != 4 or sheet.max_row > 1501:
            raise ApiError(
                422, "count_table_size", "盘点表列数或行数超出模板范围，请拆分导入。"
            )
        if [cell.value for cell in sheet[1]] != HEADERS:
            raise ApiError(422, "invalid_header", "盘点模板表头不一致，请重新下载。")
        meta = book["模板说明"]
        if meta.max_row > 10 or meta.max_column != 2:
            raise ApiError(422, "invalid_scope", "盘点模板说明已改变，请重新下载。")
        metadata = {row[0].value: str(row[1].value) for row in meta.iter_rows()}
        if any(
            metadata.get(key) != expected
            for key, expected in {
                "模板版本": "clsen-count-v1",
                "仓库ID": str(scope["warehouse_id"]),
                "货主ID": str(scope["owner_id"]),
            }.items()
        ):
            raise ApiError(
                422, "invalid_scope", "盘点表不属于当前仓库及货主，请重新下载。"
            )
        for number, cells in enumerate(sheet.iter_rows(min_row=2), 2):
            if cells[3].value is None or cells[3].value == "":
                continue
            sku, _, quality, amount = [cell.value for cell in cells]
            text = str(amount)
            quantity = table_quantity(cells[3], text, positive=False)
            message = None
            if (
                any(cell.data_type == "f" for cell in cells)
                or sheet.row_dimensions[number].hidden
            ):
                message = "含公式或隐藏的实盘行，请改为明确值并取消隐藏。"
            elif str(sku) not in catalog or catalog[str(sku)].get("status") != "active":
                message = "商品不属于当前仓库可操作范围，请勿修改规格ID。"
            elif quality not in QUALITIES:
                message = "货品状态须为合格、待检或次品。"
            elif quantity is None or quantity > 999_999_999_999_999_999:
                message = "实盘总数须为不超过18位的非负整数；空白未填，0表示实际没有。"
            elif (str(sku), quality) in seen:
                message = "同一商品同一状态重复，请只保留一条实盘总数。"
            if message:
                issues.append({"row": number, "message": message})
                continue
            seen.add((str(sku), quality))
            rows.append(
                {
                    "row": number,
                    "sku_id": str(sku),
                    "sku_label": catalog[str(sku)]["label"],
                    "quality": QUALITIES[quality],
                    "quality_label": quality,
                    "units": str(quantity),
                    "purpose": "COUNT",
                }
            )
        if not rows and not issues:
            issues.append(
                {"row": 0, "message": "请填写至少一条实盘总数；空白不会当作0。"}
            )
        if len(rows) > 500:
            issues.append({"row": 0, "message": "本批超过500条实盘明细，请分批导入。"})
    finally:
        book.close()
    return {"filename": name, "rows": rows, "issues": issues, "kind": "count"}
