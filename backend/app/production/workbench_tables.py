"""Order-bound spreadsheet input for the existing receipt and packing editors.

Preview is not a business command. The normal draft/confirm services remain the
only writers and revalidate quantities, revisions, scope and availability.
"""
# ruff: noqa: RUF001 -- Chinese template and UI text.

from __future__ import annotations

import hashlib
import re
from io import BytesIO
from typing import Any, cast
from xml.etree.ElementTree import ParseError
from zipfile import BadZipFile, ZipFile

from openpyxl import Workbook, load_workbook  # type: ignore[import-untyped]
from openpyxl.styles import Alignment, Font, PatternFill  # type: ignore[import-untyped]
from openpyxl.utils import get_column_letter  # type: ignore[import-untyped]
from openpyxl.utils.exceptions import (  # type: ignore[import-untyped]
    InvalidFileException,
)

from app.api.errors import ApiError
from app.production.order_tables import (
    style_business_sheet,
    table_quantity,
)
from app.production.order_tables import (
    value as table_value,
)
from app.production.source_registry import validate_upload

HEADERS = {
    "receipt": [
        "商品规格ID（勿改）",
        "商品规格（核对用）",
        "本次合格数量",
        "本次待检数量",
        "本次次品数量",
    ],
    "packing": ["箱号", "商品规格ID（勿改）", "商品规格（核对用）", "装箱数量"],
}
SHEETS = {"receipt": "收货入库", "packing": "出货装箱"}
BATCH_HEADERS = [
    "订单明细ID（勿改）",
    "来源订单（核对用）",
    "商品规格ID（勿改）",
    "商品规格（核对用）",
    *HEADERS["receipt"][2:],
]
RECEIPT_HEADERS = ["来源订单", "款号", "SKU", *HEADERS["receipt"][2:]]
RECEIPT_VERSION = "clsen-receipt-v2"


def _receipt_references(
    order: dict[str, Any], lines: dict[str, dict[str, Any]], catalog: dict[str, Any]
) -> dict[str, tuple[str, str, str]]:
    refs = {}
    seen = set()
    for key, line in lines.items():
        identity = catalog.get(str(line["sku_id"]), {})
        reference = (
            str(line.get("order_reference") or line.get("order_label") or "")
            if order.get("receipt_batch")
            else str(order.get("business_number") or order.get("system_number") or "")
        )
        fields = (
            reference,
            str(identity.get("style_code") or ""),
            str(identity.get("code") or ""),
        )
        if not all(fields) or fields in seen:
            raise ApiError(
                409,
                "receipt_identity_unavailable",
                "来源订单号或商品款号/SKU缺失、重复，请先核对订单和商品资料；仍可沿原页面手工入库。",
            )
        refs[key] = fields
        seen.add(fields)
    return refs


def receipt_batch_order(orders: list[dict[str, Any]]) -> dict[str, Any]:
    """Bind one receipt form to explicit source lines, including repeated SKUs."""
    if not 1 <= len(orders) <= 20 or len({str(o["id"]) for o in orders}) != len(orders):
        raise ApiError(
            422, "invalid_receipt_orders", "每批请选择1至20张不同的已确认订单。"
        )
    orders = sorted(orders, key=lambda o: int(str(o["id"])))
    lines = []
    for order in orders:
        reference = order.get("business_number") or order.get("system_number") or ""
        if (
            sum(
                (other.get("business_number") or other.get("system_number") or "")
                == reference
                for other in orders
            )
            > 1
        ):
            reference = order.get("system_number") or ""
        for line in _lines(order, "receipt").values():
            lines.append(
                {
                    **line,
                    "order_label": order.get("business_number")
                    or order["system_number"],
                    "order_reference": reference,
                    "receipt_factory_name": order.get("factory_name") or "",
                }
            )
    if len(lines) > 500:
        raise ApiError(
            422, "receipt_batch_too_large", "每批最多500条订单商品明细，请分批入库。"
        )
    return {
        "id": "receipt-batch",
        "revision": ",".join(f"{o['id']}:{o['revision']}" for o in orders),
        "status": "CONFIRMED",
        "lines": lines,
        "receipt_batch": True,
    }


def _lines(order: dict[str, Any], kind: str) -> dict[str, dict[str, Any]]:
    if kind not in HEADERS:
        raise ApiError(422, "invalid_table_kind", "请选择入库或出货装箱模板。")
    if (
        order.get("status") != "CONFIRMED"
        or not order.get("id")
        or not order.get("revision")
    ):
        raise ApiError(409, "order_not_confirmed", "请先确认生产单，再登记入库或装箱。")
    lines = order.get("lines", [])
    result = {
        str(line["id"] if order.get("receipt_batch") else line["sku_id"]): line
        for line in lines
    }
    if not result or len(result) != len(lines):
        raise ApiError(
            409, "order_lines_ambiguous", "当前订单商品明细为空或重复，请先核对订单。"
        )
    return result


def operation_template(
    order: dict[str, Any], kind: str, catalog: dict[str, Any] | None = None
) -> bytes:
    lines = _lines(order, kind)
    batch = bool(order.get("receipt_batch"))
    simple = kind == "receipt" and catalog is not None
    refs = (
        _receipt_references(order, lines, catalog)
        if catalog is not None and simple
        else {}
    )
    headers = RECEIPT_HEADERS if simple else BATCH_HEADERS if batch else HEADERS[kind]
    book = Workbook()
    sheet = book.active
    sheet.title = "入库" if simple else SHEETS[kind]
    sheet.append(headers)
    for sku, line in lines.items():
        sheet.append(
            [*refs[sku], None, None, None]
            if simple
            else [
                sku,
                line["order_label"],
                str(line["sku_id"]),
                line["sku_label"],
                None,
                None,
                None,
            ]
            if batch
            else [sku, line["sku_label"], None, None, None]
            if kind == "receipt"
            else [None, sku, line["sku_label"], None]
        )
    sheet.freeze_panes = (
        "A2" if simple else "E2" if batch else "C2" if kind == "receipt" else "D2"
    )
    sheet.auto_filter.ref = sheet.dimensions
    for index, width in enumerate(
        (
            [28, 20, 40, 20, 20, 20]
            if simple
            else [24, 28, 24, 44, 20, 20, 20]
            if batch
            else [24, 44, 20, 20, 20]
            if kind == "receipt"
            else [24, 24, 44, 20]
        ),
        1,
    ):
        sheet.column_dimensions[sheet.cell(1, index).column_letter].width = width
    info = book.create_sheet("填写说明")
    for row in [
        [
            "模板版本",
            RECEIPT_VERSION
            if simple
            else "clsen-receipt-batch-v1"
            if batch
            else f"clsen-{kind}-v1",
        ],
        ["生产单ID", str(order["id"])],
        ["生产单修订", str(order["revision"])],
        [
            "生产单号",
            order.get("business_number")
            or order.get("system_number")
            or str(order["id"]),
        ],
        [
            "数量",
            "只填写本次实际数量，不能将计划量、累计量或差额当作本次实收。"
            if kind == "receipt"
            else "同箱不同规格分行填写，同规格分多箱时分别填写；同箱同规格不能重复。",
        ],
        [
            "范围",
            "按来源订单号、款号及精确SKU分别填写，同SKU跨单分行；订单号重名时使用系统单号。仓库、货主、实际入库日期沿页面选择，不以订单数量或下单日期代替实收。"
            if simple
            else (
                "按订单明细ID分别填写。同一商品来自多单时请明确分配到各订单行，"
                "不重复填写整批数量。仓库、货主、日期沿页面选择。"
            )
            if batch
            else (
                "只处理当前生产单的商品。仓库、货主、日期、目的地沿页面选择，"
                "表格不覆盖。"
            ),
        ],
        ["保存", "预览和应用只填写当前表单；保存草稿、核对、确认仍须分别操作。"],
        [
            "原件",
            "原Excel不修改。空数量行不登记，数量须为明确整数，不使用公式。最多500行、2MB。",
        ],
    ]:
        info.append(row)
    info.column_dimensions["A"].width = 20
    info.column_dimensions["B"].width = 100
    for tab in book.worksheets:
        for row in tab:
            for cell in row:
                if cell.value is not None:
                    cell.value = str(cell.value)
                    cell.data_type = "s"
                    cell.number_format = "@"
        for cell in tab[1]:
            cell.font = Font(bold=True, color="FFFFFF")
            cell.fill = PatternFill("solid", fgColor="1769AA")
    if simple:
        style_business_sheet(sheet, (28, 20, 40, 20, 20, 20))
        for row in sheet:
            for cell in row:
                cell.alignment = Alignment(horizontal="center", vertical="center")
        for row in sheet.iter_rows(min_row=2, min_col=4):
            for cell in row:
                cell.number_format = "#,##0"
    output = BytesIO()
    book.save(output)
    book.close()
    return output.getvalue()


def preview_operation(
    raw: bytes,
    filename: str,
    order: dict[str, Any],
    kind: str,
    catalog: dict[str, Any] | None = None,
) -> dict[str, Any]:
    lines = _lines(order, kind)
    batch = bool(order.get("receipt_batch"))
    headers = BATCH_HEADERS if batch else HEADERS[kind]
    amount_start = 4 if batch else 2 if kind == "receipt" else 3
    name = validate_upload(filename, raw)
    with ZipFile(BytesIO(raw)) as archive:
        if any(
            path.startswith("xl/externalLinks/") or path.endswith("vbaProject.bin")
            for path in archive.namelist()
        ):
            raise ApiError(422, "external_workbook", "模板不能包含外部链接或宏。")
    try:
        book = load_workbook(
            BytesIO(raw), read_only=kind != "receipt", data_only=False, keep_links=False
        )
    except (BadZipFile, InvalidFileException, ParseError, ValueError, OSError) as error:
        raise ApiError(
            422, "invalid_workbook", "文件无法读取，请重新下载当前订单模板。"
        ) from error
    issues: list[dict[str, Any]] = []
    rows: list[dict[str, Any]] = []
    boxes: dict[str, list[dict[str, str]]] = {}
    total = 0
    seen: set[tuple[str, str]] = set()

    def issue(row: int, message: str) -> None:
        issues.append({"row": row, "message": message})

    def text(cell: Any, row: int, label: str) -> str:
        if cell.data_type == "f":
            issue(row, f"{label}不允许公式，请粘贴明确值。")
            return ""
        value = cell.value
        if value is None:
            return ""
        if isinstance(value, bool) or not isinstance(value, (str, int, float)):
            issue(row, f"{label}须填写文字或整数。")
            return ""
        if isinstance(value, (int, float)) and (
            value != int(value) or abs(value) > 9_007_199_254_740_991
        ):
            issue(row, f"{label}须为安全整数，长编号请设置为文本。")
            return ""
        return table_value(value).strip()

    try:
        first_header = [
            text(cell, 1, "表头")
            for cell in next(book.worksheets[0].iter_rows(max_row=1))
        ]
        if kind == "receipt" and all(
            label in first_header for label in ("下单日期", "款号", "SKU", "订单数量")
        ):
            raise ApiError(
                422,
                "wrong_table_purpose",
                "这是下单表，订单数量不能当作本次实收。请下载入库模板并填写实际收到的数量。",
            )
        supported_sheets = [[SHEETS[kind], "填写说明"]]
        if kind == "receipt":
            supported_sheets.append(["入库", "填写说明"])
        if book.sheetnames not in supported_sheets:
            raise ApiError(
                422,
                "invalid_template",
                "请使用当前订单下载的模板，保留数据页和填写说明。",
            )
        sheet, info = book.worksheets
        if info.max_row > 20 or info.max_column != 2:
            raise ApiError(422, "invalid_template", "请保持原模板的填写说明。")
        metadata = {
            text(row[0], 0, "说明"): text(row[1], 0, "说明") for row in info.iter_rows()
        }
        simple = kind == "receipt" and metadata.get("模板版本") == RECEIPT_VERSION
        references = {}
        if simple:
            if catalog is None:
                raise ApiError(
                    409,
                    "receipt_catalog_unavailable",
                    "当前商品资料尚未读取，请刷新页面后重新核对入库表。",
                )
            references = {
                fields: key
                for key, fields in _receipt_references(order, lines, catalog).items()
            }
            headers = RECEIPT_HEADERS
            amount_start = 3
        if kind == "receipt" and (
            sheet.merged_cells
            or any(col.hidden for col in sheet.column_dimensions.values())
        ):
            raise ApiError(
                422,
                "invalid_template",
                "入库明细不能合并单元格或隐藏列，请使用原模板。",
            )
        if (
            sheet.max_row > 501
            or sheet.max_column != len(headers)
            or info.max_row > 20
            or info.max_column != 2
        ):
            raise ApiError(
                422, "invalid_template", "表格最多500条明细，请保持模板列数及填写说明。"
            )
        header = [text(cell, 1, "表头") for cell in next(sheet.iter_rows(max_row=1))]
        if header != headers:
            raise ApiError(
                422, "invalid_header", "模板表头不一致，请重新下载当前订单模板。"
            )
        if metadata.get("模板版本") != (
            RECEIPT_VERSION
            if simple
            else "clsen-receipt-batch-v1"
            if batch
            else f"clsen-{kind}-v1"
        ) or metadata.get("生产单ID") != str(order["id"]):
            issue(0, "表格不属于当前生产单或操作，请下载当前页面的对应模板。")
        if metadata.get("生产单修订") != str(order["revision"]):
            issue(0, "模板对应的订单修订已改变，请核对当前订单并重新下载模板。")
        for number, cells in enumerate(sheet.iter_rows(min_row=2), 2):
            before = len(issues)
            values = [
                text(cell, number, label)
                for cell, label in zip(cells, headers, strict=True)
            ]
            if simple:
                for index in range(3):
                    if (
                        isinstance(cells[index].value, str)
                        and cells[index].data_type != "f"
                    ):
                        values[index] = cells[index].value
            amounts = values[amount_start:]
            if (
                kind == "receipt"
                and sheet.row_dimensions[number].hidden
                and any(amounts)
            ):
                issue(number, "隐藏行含入库数量，请取消隐藏并核对后重新导入。")
            if not any(amounts) and len(issues) == before:
                if kind == "packing" and values[0]:
                    issue(number, "箱号已填写，请填写对应装箱数量。")
                continue
            sku, box = (
                (references.get((values[0], values[1], values[2]), ""), "")
                if simple
                else (values[0], "")
                if kind == "receipt"
                else (values[1], values[0])
            )
            if sku not in lines:
                issue(
                    number,
                    "来源订单、款号或SKU与本批订单不一致，请核对A至C列；保留原SKU大小写及前导零。"
                    if simple
                    else "订单明细ID不在本批所选订单内，请重新下载模板。"
                    if batch
                    else "商品规格ID不在当前生产单内，不能按相似名称匹配。",
                )
            elif batch and not simple and values[2] != str(lines[sku]["sku_id"]):
                issue(number, "商品规格ID与来源订单明细不一致，请勿修改身份列。")
            elif batch and not simple and values[1] != str(lines[sku]["order_label"]):
                issue(number, "来源订单名称与订单明细ID不一致，请重新下载模板核对。")
            if kind == "packing" and (not box or len(box) > 120):
                issue(number, "箱号必填，且最多120个字符。")
            identity = (box, sku)
            if identity in seen:
                issue(
                    number,
                    "同一商品规格重复。"
                    if kind == "receipt"
                    else "同箱同规格重复，请合并数量后重新上传。",
                )
            seen.add(identity)
            quantities: list[int] = []
            for index, value in enumerate(amounts):
                if not value and kind == "receipt":
                    quantities.append(0)
                elif (
                    not re.fullmatch(r"0|[1-9][0-9]{0,17}", value)
                    or table_quantity(
                        cells[index + amount_start], value, positive=False
                    )
                    is None
                ):
                    issue(
                        number,
                        f"{headers[index + amount_start]}须为不超过18位的非负整数。",
                    )
                else:
                    quantities.append(int(value))
            if len(issues) != before:
                continue
            if sum(quantities) == 0:
                if kind == "packing":
                    issue(number, "装箱数量须大于0。")
                continue
            line = lines[sku]
            row = {
                "row": number,
                "sku_id": str(line["sku_id"]) if batch else sku,
                "order_line_id": str(line["id"]),
                "sku_label": str(line["sku_label"]),
            }
            if kind == "receipt":
                row.update(
                    dict(
                        zip(
                            ["qualified_units", "pending_units", "defective_units"],
                            map(str, quantities),
                            strict=True,
                        )
                    )
                )
            else:
                row.update({"box_number": box, "units": str(quantities[0])})
                boxes.setdefault(box, []).append(
                    {"sku_id": sku, "units": str(quantities[0])}
                )
            rows.append(row)
            total += sum(quantities)
        if not rows and not issues:
            issue(0, "没有可导入的实际数量，请填写本次收到或装箱的数量。")
    finally:
        book.close()
    return {
        "kind": kind,
        "filename": name,
        "source_digest": hashlib.sha256(raw).hexdigest(),
        "order_id": str(order["id"]),
        "order_revision": str(order["revision"]),
        "rows": rows,
        "issues": issues,
        "cartons": [
            {"number": number, "items": items} for number, items in boxes.items()
        ],
        "total_units": str(total),
        "box_count": len(boxes),
    }


DISPATCH_HEADERS = ["款号", "SKU", "本次出货数量"]


def dispatch_template(scope: dict[str, Any], catalog: dict[str, Any]) -> bytes:
    book = Workbook()
    sheet = book.active
    sheet.title = "仓库出货"
    sheet.append(DISPATCH_HEADERS)
    for sku in catalog.values():
        sheet.append([sku.get("style_code", ""), sku["code"], None])
    style_business_sheet(sheet, (20, 40, 22))
    sheet.freeze_panes = "A2"
    info = book.create_sheet("填写说明")
    for row in [
        ["模板版本", "clsen-warehouse-dispatch-v2"],
        ["仓库ID", scope["warehouse_id"]],
        ["货主ID", scope["owner_id"]],
        [
            "填写",
            "按SKU填写本批实际出货数量，无需填写箱号；空数量行不登记。",
        ],
        ["范围", "仓库、货主、实际日期和目的地沿页面选择；表格不产生订单或发货事实。"],
    ]:
        info.append(row)
    for tab in book.worksheets:
        for row in tab:
            for cell in row:
                if cell.value is not None:
                    cell.value = str(cell.value)
                    cell.data_type = "s"
                cell.alignment = Alignment(horizontal="center", vertical="center")
    result = BytesIO()
    book.save(result)
    book.close()
    return result.getvalue()


def _preview_packing_totals(
    book: Any,
    name: str,
    raw: bytes,
    scope: dict[str, Any],
    catalog: dict[str, Any],
    by_code: dict[str, list[str]],
) -> dict[str, Any]:
    """Explicit original-list profile: column A is SKU, named total is authoritative."""
    sheets = []
    for tab in book.worksheets:
        if tab.max_row > 501 or tab.max_column > 30:
            raise ApiError(
                422, "invalid_template", "原装箱单最多501行、30列，请分批整理。"
            )
        if any(cell.value is not None for row in tab for cell in row):
            sheets.append(tab)
    if len(sheets) != 1:
        raise ApiError(
            422,
            "ambiguous_packing_sheet",
            "原装箱单须只有一张非空明细页，其他页可留空。",
        )
    sheet = sheets[0]
    header = [table_value(c.value).strip() for c in sheet[1]]
    if header[0] not in ("", "SKU") or header.count("总数量") != 1:
        raise ApiError(
            422, "invalid_header", "原装箱单按第一列SKU读取，并须有唯一的“总数量”列。"
        )
    if sheet.merged_cells or any(c.hidden for c in sheet.column_dimensions.values()):
        raise ApiError(422, "invalid_template", "原装箱单明细不能合并单元格或隐藏列。")
    column = header.index("总数量")
    letter = get_column_letter(column + 1)
    issues, rows, source_rows, ignored, seen = [], [], [], [], set()
    source_total, source_count, total, footer = 0, 0, 0, False
    quantity_complete = True

    def issue(number: int, cell: str, message: str, stage: str = "reading") -> None:
        issues.append(
            {
                "row": number,
                "sheet": sheet.title,
                "cell": cell,
                "message": message,
                "stage": stage,
            }
        )

    for number, cells in enumerate(sheet.iter_rows(min_row=2), 2):
        if not any(c.value is not None for c in cells):
            continue
        code = table_value(cells[0].value)
        amount_cell = cells[column]
        if footer:
            labels = {table_value(c.value).strip() for c in cells[:3]}
            if (
                code
                or amount_cell.value is not None
                or not labels.intersection({"重量KG", "重量磅", "宽", "长", "高"})
            ):
                issue(
                    number,
                    f"A{number}",
                    "合计行后存在未识别内容或商品，请将商品移回明细区后核对。",
                )
            else:
                ignored.append(number)
            continue
        if not code and amount_cell.data_type == "f":
            expected = f"=SUM({letter}2:{letter}{number - 1})"
            if re.sub(r"\s+", "", str(amount_cell.value)).upper() != expected:
                issue(
                    number,
                    f"{letter}{number}",
                    "原单合计公式范围与前方明细不一致，请核对。",
                )
            ignored.append(number)
            footer = True
            continue
        if not code:
            issue(
                number,
                f"A{number}",
                "SKU为空；请补齐商品，或保留明确的合计行后再放重量尺寸。",
            )
            continue
        source_count += 1
        amount = table_quantity(
            amount_cell, table_value(amount_cell.value), positive=True
        )
        source_rows.append(
            {
                "row": number,
                "sku_code": code,
                "sku_id": by_code[code][0] if len(by_code.get(code, [])) == 1 else "",
                "units": str(amount) if amount is not None else None,
                "source_cell": f"{letter}{number}",
            }
        )
        before = len(issues)
        if sheet.row_dimensions[number].hidden:
            issue(number, f"A{number}", "隐藏行含出货数据，请取消隐藏后核对。")
        if cells[0].data_type == "f":
            issue(number, f"A{number}", "SKU不允许公式，请填写明确的SKU。")
        if amount is None:
            quantity_complete = False
            issue(
                number,
                f"{letter}{number}",
                "出货总数量须为明确的大于0的整数，不能使用公式或空值。",
            )
        else:
            source_total += amount
        found = by_code.get(code, [])
        if len(found) != 1:
            issue(
                number,
                f"A{number}",
                f"SKU“{code}”未在当前仓库和货主下建账或不唯一；请先核对商品及库存。",
                stage="business",
            )
        if code in seen:
            issue(number, f"A{number}", f"SKU“{code}”重复，请合并本次出货总数量。")
        seen.add(code)
        if len(issues) != before:
            continue
        sku_id = found[0]
        rows.append(
            {
                "row": number,
                "sku_id": sku_id,
                "order_line_id": "",
                "sku_label": catalog[sku_id]["label"],
                "box_number": "",
                "units": str(amount),
                "source_sheet": sheet.title,
                "source_cell": f"{letter}{number}",
            }
        )
        total += cast(int, amount)
    if not source_count and not issues:
        issue(0, "", "没有可读取的SKU及总数量明细。")
    if source_total > 9_223_372_036_854_775_807:
        issue(0, "", "本批出货合计超出数量范围，请分批。")
    return {
        "kind": "packing",
        "filename": name,
        "source_digest": hashlib.sha256(raw).hexdigest(),
        "order_id": "",
        "order_revision": "",
        "warehouse_id": str(scope["warehouse_id"]),
        "owner_id": str(scope["owner_id"]),
        "rows": rows,
        "issues": issues,
        "total_units": str(total),
        "cartons": [],
        "box_count": 0,
        "source_layout": "packing_totals",
        "source_sheet": sheet.title,
        "source_row_count": source_count,
        "source_rows": source_rows,
        "source_total_units": str(source_total) if quantity_complete else None,
        "ignored_rows": ignored,
    }


def preview_dispatch(
    raw: bytes,
    filename: str,
    scope: dict[str, Any],
    catalog: dict[str, Any],
    layout: str = "standard",
) -> dict[str, Any]:
    if layout not in {"standard", "packing_totals"}:
        raise ApiError(422, "invalid_layout", "请选择标准数量表或原装箱单格式。")
    name = validate_upload(filename, raw)
    with ZipFile(BytesIO(raw)) as archive:
        if any(
            path.startswith("xl/externalLinks/") or path.endswith("vbaProject.bin")
            for path in archive.namelist()
        ):
            raise ApiError(422, "external_workbook", "出货表不能包含外部链接或宏。")
    try:
        book = load_workbook(
            BytesIO(raw), read_only=False, data_only=False, keep_links=False
        )
    except (BadZipFile, InvalidFileException, ParseError, ValueError, OSError) as error:
        raise ApiError(
            422, "invalid_workbook", "无法读取出货表，请使用XLSX出货模板。"
        ) from error
    issues, rows, source_rows = [], [], []
    boxes: dict[str, list[dict[str, Any]]] = {}
    total, source_total, seen = 0, 0, set()
    by_code: dict[str, list[str]] = {}
    for sku_id, item in catalog.items():
        if item.get("code"):
            by_code.setdefault(item["code"], []).append(sku_id)
    try:
        if layout == "packing_totals":
            return _preview_packing_totals(book, name, raw, scope, catalog, by_code)
        if len(book.worksheets) not in (1, 2) or (
            len(book.worksheets) == 2 and book.worksheets[1].title != "填写说明"
        ):
            raise ApiError(
                422, "invalid_template", "出货表只保留明细页及可选的填写说明。"
            )
        sheet = book.worksheets[0]
        if (
            sheet.max_row > 501
            or sheet.max_column > 30
            or sheet.merged_cells
            or any(c.hidden for c in sheet.column_dimensions.values())
        ):
            raise ApiError(
                422,
                "invalid_template",
                "出货表最多500行、30列，明细不能合并单元格或隐藏列。",
            )
        header = [
            table_value(c.value).strip() for c in next(sheet.iter_rows(max_row=1))
        ]
        amounts = [
            i
            for i, text in enumerate(header)
            if text in ("本次出货数量", "装箱数量", "出货数量", "数量")
        ]
        if (
            header.count("SKU") != 1
            or len(amounts) != 1
            or header.count("箱号") > 1
            or header.count("款号") > 1
        ):
            raise ApiError(
                422, "invalid_header", "请提供唯一的SKU列和出货数量列；箱号、款号可选。"
            )
        columns = {"SKU": header.index("SKU"), "数量": amounts[0]}
        for field in ("箱号", "款号"):
            if field in header:
                columns[field] = header.index(field)
        if len(book.worksheets) == 2:
            info = book.worksheets[1]
            if info.max_row > 20 or info.max_column != 2:
                raise ApiError(422, "invalid_template", "填写说明格式不正确。")
            metadata = {str(a.value): str(z.value) for a, z in info.iter_rows()}
            for field, value in (
                ("仓库ID", scope["warehouse_id"]),
                ("货主ID", scope["owner_id"]),
            ):
                if field in metadata and metadata[field] != str(value):
                    issues.append(
                        {
                            "row": 0,
                            "message": f"模板{field}与当前范围不同，请重新下载。",
                        }
                    )
        for number, cells in enumerate(sheet.iter_rows(min_row=2), 2):
            if not any(c.value is not None for c in cells):
                continue
            values = {
                field: table_value(cells[index].value)
                for field, index in columns.items()
            }
            if not values["数量"] and not values.get("箱号"):
                continue

            def issue(message: str, stage: str = "reading", row: int = number) -> None:
                issues.append({"row": row, "message": message, "stage": stage})

            before = len(issues)
            if sheet.row_dimensions[number].hidden:
                issue("隐藏行含出货数据，请取消隐藏后核对。")
            if any(cells[index].data_type == "f" for index in columns.values()):
                issue("SKU、箱号和数量不允许公式，请粘贴明确值。")
            found = by_code.get(values["SKU"], [])
            sku_id = found[0] if len(found) == 1 else ""
            if not sku_id:
                issue(
                    "SKU不属于当前仓库和货主的已建账商品，或不唯一；请核对大小写、空格及前导零。",
                    stage="business",
                )
            elif values.get("款号") and values["款号"] != str(
                catalog[sku_id].get("style_code", "")
            ):
                issue("款号与SKU不一致，请核对原表。")
            quantity = table_quantity(cells[amounts[0]], values["数量"], positive=True)
            if quantity is None:
                issue("出货数量须为大于0且不超过18位的整数。")
            else:
                source_total += quantity
            source_rows.append(
                {
                    "row": number,
                    "sku_code": values["SKU"],
                    "sku_id": sku_id,
                    "units": str(quantity) if quantity is not None else None,
                    "source_cell": f"{get_column_letter(amounts[0] + 1)}{number}",
                }
            )
            box = values.get("箱号", "").strip()
            if len(box) > 120:
                issue("箱号最多120个字符。")
            if (box, values["SKU"]) in seen:
                issue("同箱同SKU重复，请合并数量；未填写箱号时每个SKU只填一行。")
            seen.add((box, values["SKU"]))
            if len(issues) != before:
                continue
            amount = str(quantity)
            rows.append(
                {
                    "row": number,
                    "sku_id": sku_id,
                    "order_line_id": "",
                    "sku_label": catalog[sku_id]["label"],
                    "box_number": box,
                    "units": amount,
                }
            )
            if box:
                boxes.setdefault(box, []).append({"sku_id": sku_id, "units": amount})
            total += int(amount)
        if boxes and any(not row["box_number"] for row in rows):
            issues.append(
                {
                    "row": 0,
                    "message": "箱号需全部填写或全部留空，不能漏掉部分商品的装箱来源。",
                }
            )
        if not rows and not issues:
            issues.append({"row": 0, "message": "请填写本次实际出货数量。"})
        if source_total > 9_223_372_036_854_775_807:
            issues.append({"row": 0, "message": "本批出货合计超出数量范围，请分批。"})
    finally:
        book.close()
    return {
        "kind": "packing",
        "filename": name,
        "source_digest": hashlib.sha256(raw).hexdigest(),
        "order_id": "",
        "order_revision": "",
        "warehouse_id": str(scope["warehouse_id"]),
        "owner_id": str(scope["owner_id"]),
        "rows": rows,
        "issues": issues,
        "total_units": str(total),
        "cartons": [
            {"number": number, "items": items} for number, items in boxes.items()
        ],
        "box_count": len(boxes),
        "source_layout": "standard",
        "source_rows": source_rows,
        "source_row_count": len(source_rows),
        "source_total_units": (
            str(source_total)
            if all(row["units"] is not None for row in source_rows)
            else None
        ),
    }
