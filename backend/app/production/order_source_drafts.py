"""Two authorized order snapshots and unposted import drafts, outside business DBs."""
# ruff: noqa: RUF001 -- Chinese user-facing messages use Chinese punctuation.

from __future__ import annotations

import hashlib
import json
import os
from datetime import UTC, date, datetime
from io import BytesIO
from pathlib import Path
from threading import Lock
from typing import cast
from uuid import UUID, uuid4

import openpyxl  # type: ignore[import-untyped]
from pydantic import Field

from app.api.errors import ApiError
from app.catalog.models import StrictCatalogModel
from app.config import Settings
from app.production.catalog_reference import catalog_reference
from app.production.order_tables import parse_order_table
from app.production.source_registry import uploaded_source
from app.site_context import CurrentSiteContext

SampleId = str
SAMPLES = {
    "september-11": "CLSEN下单-20260911-2218.xlsx",
    "september-12": "CLSEN下单-20260912-2125.xlsx",
}
_SAVE_LOCK = Lock()


class SourceDraftLine(StrictCatalogModel):
    source_row: int
    expected_units: str = Field(pattern=r"^[1-9][0-9]{0,17}$")
    review_note: str = Field(default="", max_length=300)


class SaveSourceDraft(StrictCatalogModel):
    source_digest: str = Field(pattern=r"^[a-f0-9]{64}$")
    revision: int = Field(ge=0)
    business_number: str = Field(default="", max_length=120)
    business_date: str = Field(pattern=r"^\d{4}-\d{2}-\d{2}$")
    notes: str = Field(default="", max_length=2000)
    lines: list[SourceDraftLine] = Field(min_length=1, max_length=1000)


def draft_root(settings: Settings, context: CurrentSiteContext) -> Path:
    if (
        not settings.production_demo_mode
        or not settings.production_order_draft_root
        or context.site_code != "DEMO_LOCAL_ONLY"
    ):
        raise ApiError(
            404, "source_drafts_unavailable", "当前环境未开放真实下单表草稿体验。"
        )
    return Path(settings.production_order_draft_root)


def _value(value: object) -> str:
    if value is None:
        return ""
    if isinstance(value, datetime):
        return value.date().isoformat()
    if isinstance(value, date):
        return value.isoformat()
    return str(value)


def read_source(
    root: Path, sample_id: SampleId, context: CurrentSiteContext | None = None
) -> dict[str, object]:
    if sample_id not in SAMPLES:
        if context is None:
            raise ApiError(404, "source_not_found", "当前账号没有这份下单表来源。")
        return uploaded_source(root, context, sample_id, "orders")
    filename = SAMPLES[sample_id]
    path = root / "inputs" / filename
    if not path.is_file():
        raise ApiError(
            503, "order_source_missing", "本地授权下单表副本缺失，请恢复指定副本。"
        )
    return parse_order_source(path.read_bytes(), filename, sample_id)


def parse_order_source(
    raw: bytes, filename: str, sample_id: str = ""
) -> dict[str, object]:
    digest = hashlib.sha256(raw).hexdigest()
    book = openpyxl.load_workbook(
        BytesIO(raw), read_only=True, data_only=False, keep_links=False
    )
    try:
        if "9月底发货" not in book.sheetnames:
            latest = parse_order_table(raw, filename)
            if latest is not None:
                latest["sample_id"] = sample_id
                return latest
            raise ApiError(
                422,
                "source_layout_changed",
                "请使用含“9月底发货”业务页的已适配下单表。",
            )
        sheet = book["9月底发货"]
        if sheet.max_row > 1000 or sheet.max_column > 20:
            raise ApiError(
                422, "source_layout_changed", "原表结构变化，请核对主业务页。"
            )
        cells = list(sheet.iter_rows(min_col=1, max_col=9))
        if [_value(c.value) for c in cells[0][:8]] != [
            "下单日期",
            "出货日期",
            "品名",
            "款号",
            "颜色",
            "SKU",
            "IMAGE",
            "订单数量",
        ]:
            raise ApiError(
                422, "source_layout_changed", "主业务页表头与已确认样表不一致。"
            )
        rows: list[dict[str, object]] = []
        issues: list[dict[str, object]] = []
        excluded: list[int] = []
        total = 0
        seen: set[str] = set()
        for row_number, cells_row in enumerate(cells[1:], 2):
            values = [_value(c.value) for c in cells_row]
            if not any(values):
                continue
            if not any(values[i] for i in (2, 3, 4, 5, 8)):
                excluded.append(row_number)
                continue
            code, amount = values[5], values[7]
            row_issues = []
            if not code:
                row_issues.append("SKU缺失，需核对原行。")
            if (
                cells_row[7].data_type == "f"
                or not amount.isascii()
                or not amount.isdecimal()
                or len(amount) > 18
                or int(amount) <= 0
            ):
                row_issues.append("订单数量必须是明确的正整数，不能用公式代替。")
            else:
                total += int(amount)
            if code and code in seen:
                row_issues.append("原表存在重复SKU，请核对是否为独立明细；尚未合并。")
            seen.add(code)
            if code and values[3] and code.split("-", 1)[0] != values[3]:
                row_issues.append(
                    f"SKU前缀与原款号{values[3]}不一致；保留原文，需人工核对。"
                )
            for column in (0, 2, 3, 4, 5, 8):
                if cells_row[column].data_type == "f":
                    row_issues.append("业务字段包含公式，需核对明确的原始值。")
                    break
            rows.append(
                {
                    "source_row": row_number,
                    "order_date": values[0],
                    "planned_dispatch_date": values[1],
                    "product_name": values[2],
                    "style_code": values[3],
                    "color": values[4],
                    "sku_code": code,
                    "expected_units": amount,
                    "source_note": values[8],
                    "sku_id": None,
                    "mapping_status": "UNRESOLVED",
                }
            )
            issues.extend(
                {"row": row_number, "message": message} for message in row_issues
            )
        if not rows:
            raise ApiError(422, "source_empty", "原表没有可核对的商品明细。")
        dates = {row["order_date"] for row in rows}
        return {
            "sample_id": sample_id,
            "filename": filename,
            "source_digest": digest,
            "sheet": sheet.title,
            "excluded_sheets": [s for s in book.sheetnames if s != sheet.title],
            "excluded_rows": excluded,
            "rows": rows,
            "issues": issues,
            "source_units": str(total),
            "business_date": next(iter(dates)) if len(dates) == 1 else "",
            "mapping_status": "UNRESOLVED",
            "confirmation_enabled": False,
        }
    finally:
        book.close()


def _path(root: Path, context: CurrentSiteContext, sample_id: SampleId) -> Path:
    return (
        root
        / "drafts"
        / str(context.site_id)
        / str(context.principal_user_id)
        / f"{sample_id}.json"
    )


def source_detail(
    settings: Settings, context: CurrentSiteContext, sample_id: SampleId
) -> dict[str, object]:
    root = draft_root(settings, context)
    source = read_source(root, sample_id, context)
    path = _path(root, context, sample_id)
    saved = json.loads(path.read_text(encoding="utf-8")) if path.is_file() else None
    if saved and saved["source_digest"] != source["source_digest"]:
        raise ApiError(
            409, "source_snapshot_changed", "副本已改变，不能覆盖旧来源草稿。"
        )
    return {
        **source,
        "saved_draft": saved,
        "catalog_reference": catalog_reference(root, source, context),
    }


def save_source_draft(
    settings: Settings,
    context: CurrentSiteContext,
    sample_id: SampleId,
    body: SaveSourceDraft,
    key: UUID,
) -> dict[str, object]:
    root = draft_root(settings, context)
    source = read_source(root, sample_id, context)
    if body.source_digest != source["source_digest"]:
        raise ApiError(409, "source_snapshot_changed", "原表副本已变化，请重新预览。")
    try:
        date.fromisoformat(body.business_date)
    except ValueError as error:
        raise ApiError(422, "invalid_date", "请填写有效下单日期。") from error
    source_rows = cast(list[dict[str, object]], source["rows"])
    if [line.source_row for line in body.lines] != [
        row["source_row"] for row in source_rows
    ]:
        raise ApiError(
            422, "source_rows_changed", "请完整保留原表明细与顺序；不能删除或伪造原行。"
        )
    path = _path(root, context, sample_id)
    payload = body.model_dump()
    with _SAVE_LOCK:
        existing = (
            json.loads(path.read_text(encoding="utf-8")) if path.is_file() else None
        )
        if existing and existing["last_save_key"] == str(key):
            if existing["saved_input"] != payload:
                raise ApiError(
                    409, "idempotency_key_reused", "相同操作ID不能用于另一份草稿内容。"
                )
            return cast(dict[str, object], existing)
        revision = existing["revision"] if existing else 0
        if revision != body.revision:
            raise ApiError(
                409,
                "source_draft_revision_conflict",
                "草稿已被更新，请重新载入后编辑。",
            )
        saved = {
            **payload,
            "revision": revision + 1,
            "sample_id": sample_id,
            "filename": source["filename"],
            "status": "IMPORT_DRAFT",
            "updated_at": datetime.now(UTC).isoformat(),
            "actor_id": str(context.principal_user_id),
            "last_save_key": str(key),
            "saved_input": payload,
            "original_rows": source["rows"],
            "draft_units": str(sum(int(line.expected_units) for line in body.lines)),
            "confirmation_enabled": False,
        }
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary = path.with_suffix(f".{uuid4().hex}.tmp")
        try:
            temporary.write_text(
                json.dumps(saved, ensure_ascii=False), encoding="utf-8"
            )
            os.replace(temporary, path)
        finally:
            temporary.unlink(missing_ok=True)
    return saved
