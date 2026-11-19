"""Editable destination receipt workbook, scoped to server-verified bindings."""

import re
from io import BytesIO
from typing import Any
from zipfile import BadZipFile, ZipFile

import openpyxl  # type: ignore[import-untyped]
from openpyxl.utils.exceptions import (  # type: ignore[import-untyped]
    InvalidFileException,
)

SHEET = "目的仓实收_v1"
HEADERS = (
    "箱来源ID",
    "出货来源行ID",
    "订单分配ID",
    "箱ID",
    "SKU ID",
    "目录版本",
    "合格件数",
    "待检件数",
    "次品件数",
)
MAX_ROWS = 5000


def workbook(
    bindings: list[dict[str, Any]], lines: list[dict[str, Any]] | None = None
) -> bytes:
    by_binding = {str(line["binding_id"]): line for line in lines or []}
    book = openpyxl.Workbook()
    sheet = book.active
    sheet.title = SHEET
    sheet.append(HEADERS)
    for binding in bindings:
        current = by_binding.get(str(binding["id"]), {})
        sheet.append(
            [
                str(binding["id"]),
                str(binding["source_line_id"]),
                str(binding.get("allocation_id") or ""),
                str(binding["carton_id"]),
                str(binding["sku_id"]),
                str(binding["catalog_version"]),
                str(current.get("qualified_units", "0")),
                str(current.get("pending_units", "0")),
                str(current.get("defective_units", "0")),
            ]
        )
    sheet.freeze_panes = "A2"
    for column in sheet.columns:
        sheet.column_dimensions[column[0].column_letter].width = 22
        for cell in column:
            cell.number_format = "@"
    out = BytesIO()
    book.save(out)
    book.close()
    return out.getvalue()


def preview(raw: bytes, bindings: list[dict[str, Any]]) -> dict[str, Any]:
    allowed = {str(item["id"]): item for item in bindings}
    issues: list[dict[str, Any]] = []
    lines: list[dict[str, str]] = []
    seen: set[str] = set()
    try:
        with ZipFile(BytesIO(raw)) as archive:
            if (
                len(archive.infolist()) > 1000
                or sum(x.file_size for x in archive.infolist()) > 20_000_000
            ):
                raise ValueError("workbook size")
        book = openpyxl.load_workbook(BytesIO(raw), read_only=True, data_only=False)
        try:
            if (
                len(book.worksheets) != 1
                or book.active.title != SHEET
                or book.active.max_row > MAX_ROWS + 1
            ):
                raise ValueError("workbook shape")
            sheet = book.active
            if (
                tuple(
                    cell.value
                    for cell in next(
                        sheet.iter_rows(min_row=1, max_row=1, max_col=len(HEADERS))
                    )
                )
                != HEADERS
            ):
                raise ValueError("workbook headers")
            for index, cells in enumerate(
                sheet.iter_rows(min_row=2, max_col=len(HEADERS)), start=2
            ):
                if all(cell.value is None for cell in cells):
                    continue
                if any(cell.data_type == "f" for cell in cells):
                    issues.append(
                        {
                            "sheet": SHEET,
                            "row": index,
                            "column": "整行",
                            "message": "不能使用公式,请填写实际值。",
                        }
                    )
                    continue
                values = [
                    "" if cell.value is None else str(cell.value).strip()
                    for cell in cells
                ]
                if any(
                    cell.value is not None and not isinstance(cell.value, str)
                    for cell in cells[:6]
                ):
                    issues.append(
                        {
                            "sheet": SHEET,
                            "row": index,
                            "column": "来源身份",
                            "message": "来源身份必须保持模板中的文本格式。",
                        }
                    )
                    continue
                binding = allowed.get(values[0])
                if not binding or values[0] in seen:
                    issues.append(
                        {
                            "sheet": SHEET,
                            "row": index,
                            "column": HEADERS[0],
                            "message": "箱来源不存在、已变化或重复,请重新下载模板。",
                        }
                    )
                    continue
                seen.add(values[0])
                expected = [
                    str(binding["source_line_id"]),
                    str(binding.get("allocation_id") or ""),
                    str(binding["carton_id"]),
                    str(binding["sku_id"]),
                    str(binding["catalog_version"]),
                ]
                if values[1:6] != expected:
                    issues.append(
                        {
                            "sheet": SHEET,
                            "row": index,
                            "column": "来源身份",
                            "message": "来源、箱、SKU或目录版本不一致,请重新核对。",
                        }
                    )
                    continue
                bad = False
                for column in range(6, 9):
                    if (
                        not re.fullmatch(r"0|[1-9][0-9]{0,18}", values[column])
                        or int(values[column]) > 9223372036854775807
                    ):
                        issues.append(
                            {
                                "sheet": SHEET,
                                "row": index,
                                "column": HEADERS[column],
                                "message": "请填写非负整数件数。",
                            }
                        )
                        bad = True
                if not bad:
                    lines.append(
                        {
                            "binding_id": values[0],
                            "sku_id": values[4],
                            "catalog_version": values[5],
                            "qualified_units": values[6],
                            "pending_units": values[7],
                            "defective_units": values[8],
                        }
                    )
        finally:
            book.close()
    except (
        BadZipFile,
        InvalidFileException,
        ValueError,
        KeyError,
        StopIteration,
    ) as error:
        raise ValueError("无法读取目的仓标准表,请使用当前模板。") from error
    return {"lines": lines, "issues": issues}
