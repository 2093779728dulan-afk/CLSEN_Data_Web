"""Pure six-sheet catalog workbook codec built on the hardened envelope."""

from __future__ import annotations

import hashlib
import io
import json
import re
import unicodedata
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from types import MappingProxyType
from typing import Final, Never, cast

from openpyxl import Workbook, load_workbook  # type: ignore[import-untyped]
from openpyxl.cell import Cell  # type: ignore[import-untyped]

from app.catalog.normalization import catalog_identity_key_v1
from app.catalog.ooxml import (
    SHEET_NAMES,
    CapacityViolation,
    CatalogWorkbookCapacityError,
    CatalogWorkbookUnsafeError,
    validate_catalog_ooxml,
)

type CellValue = str | int | datetime | None
type StoredCellValue = str | int | None

SHEET_HEADERS: Final = MappingProxyType(
    {
        "生成信息": ("字段", "值"),
        "款式主档": (
            "工作簿款式键",
            "系统款式ID",
            "款号",
            "标准商品名称",
            "启用状态",
            "候选SellerSKU数",
            "来源标题数",
            "首次出现日期",
            "最近出现日期",
            "变更原因",
        ),
        "SKU变体": (
            "工作簿变体键",
            "系统SKUID",
            "工作簿款式键",
            "内部展示SKU",
            "标准颜色",
            "标准尺码",
            "启用状态",
            "来源颜色候选预览",
            "来源颜色候选集SHA256",
            "来源尺码候选预览",
            "来源尺码候选集SHA256",
            "首次出现日期",
            "最近出现日期",
            "变更原因",
        ),
        "SellerSKU映射": (
            "系统映射行ID",
            "Seller Account",
            "Marketplace",
            "Seller SKU预览",
            "Seller SKU SHA256",
            "身份决定",
            "目标工作簿变体键",
            "目标内部展示SKU",
            "首次出现日期",
            "最近出现日期",
            "经营出现次数",
            "退货出现次数",
            "排除理由",
            "变更原因",
        ),
        "待处理异常": (
            "异常行ID",
            "原因代码",
            "Seller SKU预览",
            "Seller SKU SHA256",
            "来源报表",
            "候选款号",
            "候选颜色",
            "候选尺码",
            "处理动作",
            "目标工作簿变体键",
            "修正款号",
            "修正标准颜色",
            "修正标准尺码",
            "排除理由",
            "备注",
        ),
        "来源证据": (
            "证据汇总行ID",
            "Seller SKU预览",
            "Seller SKU SHA256",
            "报表类型",
            "首次出现日期",
            "最近出现日期",
            "出现次数",
            "不同标题数",
            "最近标题预览",
            "最近标题SHA256",
            "不同父ASIN数",
            "不同子ASIN数",
            "不同FNSKU数",
            "证据集合SHA256",
        ),
    }
)

SHEET_HEADERS_V2: Final = MappingProxyType(
    {
        **SHEET_HEADERS,
        "款式主档": (
            "工作簿款式键",
            "系统款式ID",
            "款式编号",
            "标准商品名称",
            "分类操作",
            "分类代码",
            "启用状态",
            "候选SellerSKU数",
            "来源标题数",
            "首次出现日期",
            "最近出现日期",
            "变更原因",
        ),
    }
)

_METADATA_KEYS: Final = (
    "模板版本",
    "目录导出ID",
    "站点代码",
    "Seller Account",
    "Marketplace",
    "基础目录版本",
    "来源快照摘要",
    "规范化规则版本",
    "生成时间",
)

_SPECS: Final = MappingProxyType(
    {
        "生成信息": (("T", 64), ("T", 128)),
        "款式主档": (
            ("T", 64),
            ("T", 64),
            ("T", 128),
            ("T", 255),
            ("T", 16),
            ("I", 0),
            ("I", 0),
            ("T", 10),
            ("T", 10),
            ("T", 500),
        ),
        "SKU变体": (
            ("T", 64),
            ("T", 64),
            ("T", 64),
            ("T", 128),
            ("T", 128),
            ("T", 128),
            ("T", 16),
            ("T", 1000),
            ("T", 71),
            ("T", 1000),
            ("T", 71),
            ("T", 10),
            ("T", 10),
            ("T", 500),
        ),
        "SellerSKU映射": (
            ("T", 64),
            ("T", 128),
            ("T", 32),
            ("T", 255),
            ("T", 71),
            ("T", 16),
            ("T", 64),
            ("T", 128),
            ("T", 10),
            ("T", 10),
            ("I", 0),
            ("I", 0),
            ("T", 500),
            ("T", 500),
        ),
        "待处理异常": (
            ("T", 64),
            ("T", 64),
            ("T", 255),
            ("T", 71),
            ("T", 16),
            ("T", 128),
            ("T", 128),
            ("T", 128),
            ("T", 32),
            ("T", 64),
            ("T", 128),
            ("T", 128),
            ("T", 128),
            ("T", 500),
            ("T", 1000),
        ),
        "来源证据": (
            ("T", 64),
            ("T", 255),
            ("T", 71),
            ("T", 16),
            ("T", 10),
            ("T", 10),
            ("I", 0),
            ("I", 0),
            ("T", 255),
            ("T", 71),
            ("I", 0),
            ("I", 0),
            ("I", 0),
            ("T", 71),
        ),
    }
)

_SPECS_V2: Final = MappingProxyType(
    {
        **_SPECS,
        "款式主档": (
            ("T", 64),
            ("T", 64),
            ("T", 128),
            ("T", 255),
            ("T", 16),
            ("T", 64),
            ("T", 16),
            ("I", 0),
            ("I", 0),
            ("T", 10),
            ("T", 10),
            ("T", 500),
        ),
    }
)

MAX_SHEET_DATA_ROWS: Final = 30_000
MAX_WORKBOOK_DATA_ROWS: Final = 75_000
MAX_COLUMNS: Final = 16
_DATE = re.compile(r"\d{4}-\d{2}-\d{2}\Z", re.ASCII)
_GENERATED_AT = re.compile(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z\Z", re.ASCII)
_DIGEST = re.compile(r"sha256:[0-9a-f]{64}\Z", re.ASCII)


class CatalogWorkbookRowLimitError(CatalogWorkbookCapacityError):
    """The exact candidate payload exceeds a sheet or workbook row limit."""


@dataclass(frozen=True, slots=True)
class CatalogWorkbookData:
    rows: Mapping[str, Sequence[Sequence[CellValue]]]


def _template_version(rows: Sequence[Sequence[CellValue]]) -> str:
    if not rows or len(rows[0]) != 2 or rows[0][0] != "模板版本":
        _unsafe()
    version = rows[0][1]
    if version not in {"product_catalog_workbook_v1", "product_catalog_workbook_v2"}:
        _unsafe()
    return str(version)


def _contract(
    version: str,
) -> tuple[Mapping[str, tuple[str, ...]], Mapping[str, tuple[tuple[str, int], ...]]]:
    if version == "product_catalog_workbook_v1":
        return SHEET_HEADERS, _SPECS
    if version == "product_catalog_workbook_v2":
        return SHEET_HEADERS_V2, _SPECS_V2
    _unsafe()


def _unsafe() -> Never:
    raise CatalogWorkbookUnsafeError("catalog_sheet_contract_mismatch")


def _format_timestamp(value: datetime) -> str:
    if value.tzinfo is None or value.utcoffset() is None:
        _unsafe()
    return value.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def _valid_xml_text(value: str) -> bool:
    for character in value:
        scalar = ord(character)
        if (
            scalar == 0
            or character in "\r\n"
            or unicodedata.category(character) in {"Cc", "Cf", "Zl", "Zp"}
            or not (
                scalar in {0x9}
                or 0x20 <= scalar <= 0xD7FF
                or 0xE000 <= scalar <= 0xFFFD
                or 0x10000 <= scalar <= 0x10FFFF
            )
        ):
            return False
    return True


def _normalize_cell(
    value: CellValue,
    *,
    kind: str,
    limit: int,
    allow_datetime: bool = False,
) -> StoredCellValue:
    if value is None:
        return None
    if kind == "I":
        if isinstance(value, bool) or not isinstance(value, int) or value < 0:
            _unsafe()
        return value
    if allow_datetime and isinstance(value, datetime):
        value = _format_timestamp(value)
    if not isinstance(value, str) or not _valid_xml_text(value):
        _unsafe()
    if len(value) > limit:
        _unsafe()
    return value


def _normalize_rows(
    source: CatalogWorkbookData,
) -> dict[str, tuple[tuple[StoredCellValue, ...], ...]]:
    if tuple(source.rows) != SHEET_NAMES or set(source.rows) != set(SHEET_NAMES):
        _unsafe()
    version = _template_version(source.rows["生成信息"])
    _, contract_specs = _contract(version)
    normalized: dict[str, tuple[tuple[StoredCellValue, ...], ...]] = {}
    total = 0
    violations: list[CapacityViolation] = []
    for name in SHEET_NAMES:
        rows = source.rows[name]
        if isinstance(rows, (str, bytes)):
            _unsafe()
        expected_count = 9 if name == "生成信息" else None
        if expected_count is not None and len(rows) != expected_count:
            _unsafe()
        if name != "生成信息" and len(rows) > MAX_SHEET_DATA_ROWS:
            violations.append(
                CapacityViolation(
                    code="sheet_row_limit",
                    sheet_or_member=name,
                    actual=str(len(rows)),
                    limit=str(MAX_SHEET_DATA_ROWS),
                    unit="rows",
                )
            )
        total += len(rows)
        sheet_rows: list[tuple[StoredCellValue, ...]] = []
        specs = contract_specs[name]
        for row_index, row in enumerate(rows):
            if isinstance(row, (str, bytes)) or len(row) != len(specs):
                _unsafe()
            values = tuple(
                _normalize_cell(
                    value,
                    kind=kind,
                    limit=limit,
                    allow_datetime=(
                        name == "生成信息" and row_index == 8 and column == 1
                    ),
                )
                for column, (value, (kind, limit)) in enumerate(
                    zip(row, specs, strict=True)
                )
            )
            sheet_rows.append(values)
        normalized[name] = tuple(sheet_rows)
    if total > MAX_WORKBOOK_DATA_ROWS:
        violations.append(
            CapacityViolation(
                code="workbook_row_limit",
                sheet_or_member=None,
                actual=str(total),
                limit=str(MAX_WORKBOOK_DATA_ROWS),
                unit="rows",
            )
        )
    if violations:
        raise CatalogWorkbookRowLimitError(tuple(violations))
    _validate_metadata(normalized["生成信息"])
    return normalized


def _validate_metadata(rows: tuple[tuple[CellValue, ...], ...]) -> None:
    if tuple(row[0] for row in rows) != _METADATA_KEYS:
        _unsafe()
    values = {str(row[0]): row[1] for row in rows}
    if (
        values["模板版本"]
        not in {"product_catalog_workbook_v1", "product_catalog_workbook_v2"}
        or values["Marketplace"] != "amazon_us"
        or not isinstance(values["目录导出ID"], str)
        or not values["目录导出ID"]
        or not isinstance(values["站点代码"], str)
        or not values["站点代码"]
        or not isinstance(values["Seller Account"], str)
        or not values["Seller Account"]
        or not isinstance(values["来源快照摘要"], str)
        or _DIGEST.fullmatch(values["来源快照摘要"]) is None
        or not isinstance(values["规范化规则版本"], str)
        or not values["规范化规则版本"]
        or not isinstance(values["生成时间"], str)
        or _GENERATED_AT.fullmatch(values["生成时间"]) is None
    ):
        _unsafe()


def _write_string(cell: Cell, value: str) -> None:
    cell.value = value
    cell.data_type = "s"


def render_catalog_workbook(source: CatalogWorkbookData) -> bytes:
    """Render a deterministic-contract workbook and validate its own output."""

    rows = _normalize_rows(source)
    headers, _ = _contract(_template_version(rows["生成信息"]))
    workbook = Workbook(write_only=False)
    workbook.remove(workbook.active)
    for name in SHEET_NAMES:
        worksheet = workbook.create_sheet(name)
        for column, header_value in enumerate(headers[name], start=1):
            _write_string(worksheet.cell(row=1, column=column), header_value)
        for row_index, row in enumerate(rows[name], start=2):
            for column, value in enumerate(row, start=1):
                if value is None:
                    continue
                cell = worksheet.cell(row=row_index, column=column)
                if isinstance(value, int):
                    cell.value = value
                    cell.data_type = "n"
                else:
                    _write_string(cell, value)
    output = io.BytesIO()
    workbook.save(output)
    workbook.close()
    content = output.getvalue()
    validate_catalog_ooxml(content)
    return content


def _read_sheet_rows(
    worksheet: object,
    name: str,
    *,
    headers: Mapping[str, tuple[str, ...]],
    specs_by_sheet: Mapping[str, tuple[tuple[str, int], ...]],
) -> tuple[tuple[CellValue, ...], ...]:
    sheet_headers = headers[name]
    values = list(
        worksheet.iter_rows(  # type: ignore[attr-defined]
            min_row=1,
            max_row=(11 if name == "生成信息" else MAX_SHEET_DATA_ROWS + 2),
            min_col=1,
            max_col=len(sheet_headers) + 1,
            values_only=False,
        )
    )
    if not values:
        _unsafe()
    actual_headers = tuple(cell.value for cell in values[0][: len(sheet_headers)])
    if (
        actual_headers != sheet_headers
        or values[0][len(sheet_headers)].value is not None
    ):
        _unsafe()
    result: list[tuple[CellValue, ...]] = []
    ended = False
    specs = specs_by_sheet[name]
    for cells in values[1:]:
        if any(cell.data_type == "f" for cell in cells):
            _unsafe()
        raw = tuple(cell.value for cell in cells)
        if all(value is None for value in raw):
            ended = True
            continue
        if ended or raw[len(sheet_headers)] is not None:
            _unsafe()
        row: list[CellValue] = []
        for cell, (kind, limit) in zip(cells[: len(sheet_headers)], specs, strict=True):
            value = cell.value
            if value is None:
                row.append(None)
            elif kind == "I":
                if (
                    cell.data_type != "n"
                    or isinstance(value, bool)
                    or not isinstance(value, int)
                ):
                    _unsafe()
                row.append(_normalize_cell(value, kind=kind, limit=limit))
            else:
                if cell.data_type == "n" and isinstance(value, (int, float)):
                    raise CatalogWorkbookUnsafeError("catalog_text_cell_numeric")
                if cell.data_type not in {"s", "inlineStr"} or not isinstance(
                    value, str
                ):
                    _unsafe()
                row.append(_normalize_cell(value, kind=kind, limit=limit))
        result.append(tuple(row))
    return tuple(result)


def parse_catalog_workbook(
    source: bytes | bytearray | memoryview,
    *,
    max_archive_bytes: int | None = None,
) -> CatalogWorkbookData:
    """Validate the envelope, then parse read-only with formula visibility on."""

    content = bytes(source)
    options = (
        {} if max_archive_bytes is None else {"max_archive_bytes": max_archive_bytes}
    )
    validate_catalog_ooxml(content, **options)
    try:
        workbook = load_workbook(
            io.BytesIO(content),
            read_only=True,
            data_only=False,
            keep_links=False,
        )
    except Exception as error:
        raise CatalogWorkbookUnsafeError("catalog_workbook_parse_failed") from error
    try:
        if tuple(workbook.sheetnames) != SHEET_NAMES:
            _unsafe()
        metadata = _read_sheet_rows(
            workbook["生成信息"],
            "生成信息",
            headers=SHEET_HEADERS,
            specs_by_sheet=_SPECS,
        )
        _validate_metadata(metadata)
        headers, specs = _contract(_template_version(metadata))
        rows = {"生成信息": metadata}
        rows.update(
            {
                name: _read_sheet_rows(
                    workbook[name], name, headers=headers, specs_by_sheet=specs
                )
                for name in SHEET_NAMES
                if name != "生成信息"
            }
        )
        normalized = _normalize_rows(CatalogWorkbookData(rows=rows))
        return CatalogWorkbookData(rows=MappingProxyType(normalized))
    finally:
        workbook.close()


def _candidate_set_projection(values: Sequence[str]) -> tuple[str | None, str | None]:
    distinct = sorted(set(values), key=lambda value: value.encode("utf-8"))
    if not distinct:
        return None, None
    encoded = json.dumps(distinct, ensure_ascii=False, separators=(",", ":"))
    preview = encoded[:1000]
    digest = hashlib.sha256(encoded.encode("utf-8")).hexdigest()
    return preview, f"sha256:{digest}"


def _mapping_list(value: object) -> list[Mapping[str, object]]:
    if not isinstance(value, (list, tuple)) or not all(
        isinstance(item, Mapping) for item in value
    ):
        raise CatalogWorkbookUnsafeError("catalog_export_payload_invalid")
    return [item for item in value if isinstance(item, Mapping)]


def _integer(value: object) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise CatalogWorkbookUnsafeError("catalog_export_payload_invalid")
    return value


def _cells(*values: object) -> tuple[CellValue, ...]:
    if not all(
        value is None or isinstance(value, (str, int, datetime)) for value in values
    ) or any(isinstance(value, bool) for value in values):
        raise CatalogWorkbookUnsafeError("catalog_export_payload_invalid")
    return tuple(cast(CellValue, value) for value in values)


def workbook_from_export_payload(
    *,
    export_id: int,
    site_code: str,
    seller_account_display_name: str,
    base_catalog_version_id: int | None,
    snapshot_digest: bytes,
    normalization_manifest_id: str,
    generated_at: datetime,
    candidates: Mapping[str, object],
    evidence: Mapping[str, object],
    existing_styles: Sequence[Mapping[str, object]] = (),
    existing_skus: Sequence[Mapping[str, object]] = (),
) -> CatalogWorkbookData:
    """Project Task 6's exact immutable JSON payload into the v1 six-sheet codec."""

    if len(snapshot_digest) != 32:
        _unsafe()
    try:
        style_items = _mapping_list(candidates["styles"])
        variant_items = _mapping_list(candidates["variants"])
        mapping_items = _mapping_list(candidates["mappings"])
        exclusion_items = _mapping_list(candidates["exclusions"])
        exception_items = _mapping_list(candidates["exceptions"])
        summary_items = _mapping_list(evidence["summaries"])
    except (KeyError, TypeError) as error:
        raise CatalogWorkbookUnsafeError("catalog_export_payload_invalid") from error
    styles_by_code = {
        catalog_identity_key_v1(str(row["style_code"])).utf8: row
        for row in existing_styles
    }
    skus_by_variant = {
        (
            catalog_identity_key_v1(str(row["style_code"])).utf8,
            catalog_identity_key_v1(str(row["standard_color"])).utf8,
            catalog_identity_key_v1(str(row["standard_size"])).utf8,
        ): row
        for row in existing_skus
    }
    existing_skus_by_id = {
        int(cast(int | str, row["sku_id"])): row for row in existing_skus
    }
    style_keys_by_code = {
        catalog_identity_key_v1(str(row["style_code"])).utf8: str(row["row_key"])
        for row in style_items
    }
    variant_keys_by_identity = {
        (
            catalog_identity_key_v1(str(row["style_code"])).utf8,
            catalog_identity_key_v1(str(row["source_color"])).utf8,
            catalog_identity_key_v1(str(row["source_size"])).utf8,
        ): str(row["row_key"])
        for row in variant_items
    }
    target_variant_keys: dict[int, str] = {}
    for mapping in mapping_items:
        target_value = mapping.get("target_sku_id")
        if target_value is None:
            continue
        if isinstance(target_value, bool) or not isinstance(target_value, int):
            raise CatalogWorkbookUnsafeError("catalog_export_payload_invalid")
        existing_sku = existing_skus_by_id.get(target_value)
        if existing_sku is None:
            raise CatalogWorkbookUnsafeError("catalog_export_payload_invalid")
        style_code = str(existing_sku["style_code"])
        style_identity = catalog_identity_key_v1(style_code).utf8
        style_row_key = style_keys_by_code.get(style_identity)
        if style_row_key is None:
            existing_style = styles_by_code.get(style_identity)
            if existing_style is None:
                raise CatalogWorkbookUnsafeError("catalog_export_payload_invalid")
            style_row_key = f"catalog-style-{existing_style['style_id']}"
            style_items.append(
                {
                    "row_key": style_row_key,
                    "style_code": style_code,
                    "standard_name": existing_style["standard_name"],
                    "candidate_seller_sku_count": 0,
                    "source_title_count": 0,
                }
            )
            style_keys_by_code[style_identity] = style_row_key
        variant_identity = (
            style_identity,
            catalog_identity_key_v1(str(existing_sku["standard_color"])).utf8,
            catalog_identity_key_v1(str(existing_sku["standard_size"])).utf8,
        )
        variant_row_key = variant_keys_by_identity.get(variant_identity)
        if variant_row_key is None:
            variant_row_key = f"catalog-sku-{target_value}"
            variant_items.append(
                {
                    "row_key": variant_row_key,
                    "style_row_key": style_row_key,
                    "style_code": style_code,
                    "source_color": existing_sku["standard_color"],
                    "source_size": existing_sku["standard_size"],
                    "observed_seller_sku_count": 0,
                }
            )
            variant_keys_by_identity[variant_identity] = variant_row_key
        target_variant_keys[target_value] = variant_row_key
    summaries_by_seller: dict[str, list[Mapping[str, object]]] = {}
    for summary in summary_items:
        seller = summary.get("seller_sku")
        if not isinstance(seller, Mapping) or not isinstance(seller.get("sha256"), str):
            raise CatalogWorkbookUnsafeError("catalog_export_payload_invalid")
        summaries_by_seller.setdefault(seller["sha256"], []).append(summary)

    mappings_by_variant: dict[str, list[Mapping[str, object]]] = {}
    for mapping in mapping_items:
        target_value = mapping.get("target_sku_id")
        mapped_variant_key = (
            target_variant_keys.get(target_value)
            if isinstance(target_value, int) and not isinstance(target_value, bool)
            else mapping.get("candidate_variant_row_key")
        )
        if isinstance(mapped_variant_key, str):
            mappings_by_variant.setdefault(mapped_variant_key, []).append(mapping)
    variants_by_style: dict[str, list[Mapping[str, object]]] = {}
    for variant in variant_items:
        variant_style_key = variant.get("style_row_key")
        if not isinstance(variant_style_key, str):
            raise CatalogWorkbookUnsafeError("catalog_export_payload_invalid")
        variants_by_style.setdefault(variant_style_key, []).append(variant)

    def dates_for_mappings(
        mappings: Sequence[Mapping[str, object]],
    ) -> tuple[str | None, str | None]:
        summaries: list[Mapping[str, object]] = []
        for mapping in mappings:
            seller = mapping.get("seller_sku")
            if isinstance(seller, Mapping) and isinstance(seller.get("sha256"), str):
                summaries.extend(summaries_by_seller.get(seller["sha256"], ()))
        first = sorted(
            value
            for row in summaries
            if isinstance((value := row.get("first_seen_date")), str)
        )
        latest = sorted(
            value
            for row in summaries
            if isinstance((value := row.get("latest_seen_date")), str)
        )
        return (first[0] if first else None, latest[-1] if latest else None)

    style_rows: list[tuple[CellValue, ...]] = []
    for style in style_items:
        output_style_key = style.get("row_key")
        style_code_value = style.get("style_code")
        if not isinstance(output_style_key, str) or not isinstance(
            style_code_value, str
        ):
            raise CatalogWorkbookUnsafeError("catalog_export_payload_invalid")
        existing_style = styles_by_code.get(
            catalog_identity_key_v1(style_code_value).utf8
        )
        related_mappings = [
            mapping
            for variant in variants_by_style.get(output_style_key, ())
            for mapping in mappings_by_variant.get(str(variant.get("row_key")), ())
        ]
        first, latest = dates_for_mappings(related_mappings)
        style_rows.append(
            _cells(
                output_style_key,
                (
                    None
                    if existing_style is None
                    else str(existing_style.get("style_id"))
                ),
                style_code_value,
                (
                    style.get("standard_name")
                    if existing_style is None
                    else existing_style.get("standard_name")
                ),
                "保持原值",
                None,
                "enabled" if existing_style is None else existing_style.get("status"),
                style.get("candidate_seller_sku_count"),
                style.get("source_title_count"),
                first,
                latest,
                None,
            )
        )

    variant_rows: list[tuple[CellValue, ...]] = []
    for variant in variant_items:
        output_variant_key = variant.get("row_key")
        if not isinstance(output_variant_key, str):
            raise CatalogWorkbookUnsafeError("catalog_export_payload_invalid")
        first, latest = dates_for_mappings(
            mappings_by_variant.get(output_variant_key, ())
        )
        color = variant.get("source_color")
        size = variant.get("source_size")
        variant_style_code = variant.get("style_code")
        if (
            not isinstance(color, str)
            or not isinstance(size, str)
            or not isinstance(variant_style_code, str)
        ):
            raise CatalogWorkbookUnsafeError("catalog_export_payload_invalid")
        existing_sku = skus_by_variant.get(
            (
                catalog_identity_key_v1(variant_style_code).utf8,
                catalog_identity_key_v1(color).utf8,
                catalog_identity_key_v1(size).utf8,
            )
        )
        color_preview, color_digest = _candidate_set_projection((color,))
        size_preview, size_digest = _candidate_set_projection((size,))
        variant_rows.append(
            _cells(
                output_variant_key,
                None if existing_sku is None else str(existing_sku.get("sku_id")),
                variant.get("style_row_key"),
                (
                    None
                    if existing_sku is None
                    else existing_sku.get("internal_display_sku")
                ),
                color if existing_sku is None else existing_sku.get("standard_color"),
                size if existing_sku is None else existing_sku.get("standard_size"),
                "enabled" if existing_sku is None else existing_sku.get("status"),
                color_preview,
                color_digest,
                size_preview,
                size_digest,
                first,
                latest,
                None,
            )
        )

    exclusions_by_sha: dict[str, Mapping[str, object]] = {}
    for exclusion in exclusion_items:
        seller = exclusion.get("seller_sku")
        if isinstance(seller, Mapping) and isinstance(seller.get("sha256"), str):
            exclusions_by_sha[seller["sha256"]] = exclusion

    mapping_rows: list[tuple[CellValue, ...]] = []
    for mapping in mapping_items:
        seller = mapping.get("seller_sku")
        if not isinstance(seller, Mapping):
            raise CatalogWorkbookUnsafeError("catalog_export_payload_invalid")
        seller_sha = seller.get("sha256")
        if not isinstance(seller_sha, str):
            raise CatalogWorkbookUnsafeError("catalog_export_payload_invalid")
        summaries = summaries_by_seller.get(seller_sha, ())
        first = min(str(row["first_seen_date"]) for row in summaries)
        latest = max(str(row["latest_seen_date"]) for row in summaries)
        business = sum(
            _integer(row["occurrence_count"])
            for row in summaries
            if row.get("report_type") == "business_report"
        )
        returns = sum(
            _integer(row["occurrence_count"])
            for row in summaries
            if row.get("report_type") == "return_report"
        )
        matched_exclusion = exclusions_by_sha.get(seller_sha)
        target_value = mapping.get("target_sku_id")
        target_key = (
            target_variant_keys.get(target_value)
            if isinstance(target_value, int) and not isinstance(target_value, bool)
            else mapping.get("candidate_variant_row_key")
        )
        decision = None
        exclusion_reason = None
        if matched_exclusion is not None:
            decision = "excluded"
            target_key = None
            exclusion_reason = matched_exclusion.get("exclusion_reason")
        elif mapping.get("target_sku_id") is not None:
            decision = "mapped"
        mapping_rows.append(
            _cells(
                mapping.get("row_key"),
                seller_account_display_name,
                "amazon_us",
                seller.get("preview"),
                seller_sha,
                decision,
                target_key,
                None,
                first,
                latest,
                business,
                returns,
                exclusion_reason,
                None,
            )
        )

    exception_rows: list[tuple[CellValue, ...]] = []
    for exception in exception_items:
        seller = exception.get("seller_sku")
        if not isinstance(seller, Mapping):
            raise CatalogWorkbookUnsafeError("catalog_export_payload_invalid")
        seller_sha = seller.get("sha256")
        matched_exclusion = (
            exclusions_by_sha.get(seller_sha) if isinstance(seller_sha, str) else None
        )
        exception_rows.append(
            _cells(
                exception.get("row_key"),
                exception.get("reason_code"),
                seller.get("preview"),
                seller_sha,
                exception.get("source_report"),
                exception.get("candidate_style_code"),
                exception.get("candidate_color"),
                exception.get("candidate_size"),
                "明确排除" if matched_exclusion is not None else None,
                None,
                None,
                None,
                None,
                (
                    None
                    if matched_exclusion is None
                    else matched_exclusion.get("exclusion_reason")
                ),
                None,
            )
        )

    evidence_rows: list[tuple[CellValue, ...]] = []
    for summary in summary_items:
        seller = summary.get("seller_sku")
        if not isinstance(seller, Mapping):
            raise CatalogWorkbookUnsafeError("catalog_export_payload_invalid")
        latest_title = summary.get("latest_title")
        title_preview = None
        title_digest = None
        if isinstance(latest_title, Mapping):
            title_preview = latest_title.get("preview")
            title_digest = latest_title.get("sha256")
        identity = hashlib.sha256(
            (str(seller.get("sha256")) + "\0" + str(summary.get("report_type"))).encode(
                "utf-8"
            )
        ).hexdigest()
        evidence_rows.append(
            _cells(
                f"ev_{identity[:61]}",
                seller.get("preview"),
                seller.get("sha256"),
                (
                    "business"
                    if summary.get("report_type") == "business_report"
                    else "returns"
                ),
                summary.get("first_seen_date"),
                summary.get("latest_seen_date"),
                summary.get("occurrence_count"),
                summary.get("title_distinct_count"),
                title_preview,
                title_digest,
                summary.get("parent_asin_distinct_count"),
                summary.get("child_asin_distinct_count"),
                summary.get("fnsku_distinct_count"),
                summary.get("evidence_set_digest"),
            )
        )

    return CatalogWorkbookData(
        rows={
            "生成信息": (
                ("模板版本", "product_catalog_workbook_v2"),
                ("目录导出ID", str(export_id)),
                ("站点代码", site_code),
                ("Seller Account", seller_account_display_name),
                ("Marketplace", "amazon_us"),
                (
                    "基础目录版本",
                    None
                    if base_catalog_version_id is None
                    else str(base_catalog_version_id),
                ),
                ("来源快照摘要", f"sha256:{snapshot_digest.hex()}"),
                ("规范化规则版本", normalization_manifest_id),
                ("生成时间", _format_timestamp(generated_at)),
            ),
            "款式主档": tuple(style_rows),
            "SKU变体": tuple(variant_rows),
            "SellerSKU映射": tuple(mapping_rows),
            "待处理异常": tuple(exception_rows),
            "来源证据": tuple(evidence_rows),
        }
    )


__all__ = (
    "MAX_COLUMNS",
    "MAX_SHEET_DATA_ROWS",
    "MAX_WORKBOOK_DATA_ROWS",
    "SHEET_HEADERS",
    "SHEET_NAMES",
    "CatalogWorkbookData",
    "CatalogWorkbookRowLimitError",
    "parse_catalog_workbook",
    "render_catalog_workbook",
    "workbook_from_export_payload",
)
