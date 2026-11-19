"""Authorized packing-list snapshot; dispatch is an assumption, never a posted fact."""
# ruff: noqa: RUF001 -- Chinese UI messages use native punctuation.

from __future__ import annotations

import hashlib
import json
import os
import re
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
from app.production.order_source_drafts import draft_root
from app.production.source_registry import uploaded_source
from app.site_context import CurrentSiteContext

PACKING_FILENAME = "CLSEN亚马逊20260904出货装箱单-武汉.xlsx"
PACKING_SAMPLE = "packing-list-20260904"
_SAVE_LOCK = Lock()


class PackingDraftLine(StrictCatalogModel):
    source_row: int
    actual_units: str = Field(pattern=r"^(0|[1-9][0-9]{0,17})$")
    order_reference_note: str = Field(default="", max_length=300)
    review_note: str = Field(default="", max_length=300)


class SavePackingDraft(StrictCatalogModel):
    source_digest: str = Field(pattern=r"^[a-f0-9]{64}$")
    revision: int = Field(ge=0)
    business_number: str = Field(default="", max_length=120)
    business_date: str = Field(default="", pattern=r"^(|\d{4}-\d{2}-\d{2})$")
    notes: str = Field(default="", max_length=2000)
    lines: list[PackingDraftLine] = Field(min_length=1, max_length=1000)


def _text(value: object) -> str:
    return "" if value is None else str(value)


def _box_units(value: object) -> int:
    if value is None:
        return 0
    text = str(value)
    if not text.isascii() or not text.isdecimal() or len(text) > 18:
        raise ApiError(
            422,
            "invalid_box_units",
            "箱内件数须是明确的非负整数，不能由公式或重量推算。",
        )
    return int(text)


def read_packing_source(
    root: Path,
    source_id: str = PACKING_SAMPLE,
    context: CurrentSiteContext | None = None,
) -> dict[str, object]:
    if source_id != PACKING_SAMPLE:
        if context is None:
            raise ApiError(404, "source_not_found", "当前账号没有这份装箱单来源。")
        return uploaded_source(root, context, source_id, "shipments")
    path = root / "inputs" / PACKING_FILENAME
    if not path.is_file():
        raise ApiError(
            503, "packing_source_missing", "指定装箱单副本缺失，请恢复已授权副本。"
        )
    return parse_packing_source(path.read_bytes(), PACKING_FILENAME)


def parse_packing_source(raw: bytes, filename: str) -> dict[str, object]:
    digest = hashlib.sha256(raw).hexdigest()
    book = openpyxl.load_workbook(
        BytesIO(raw), read_only=True, data_only=False, keep_links=False
    )
    try:
        if "Sheet1" not in book.sheetnames:
            raise ApiError(
                422, "packing_layout_changed", "装箱单缺少已确认的Sheet1页。"
            )
        sheet = book["Sheet1"]
        if sheet.max_row > 1000 or sheet.max_column != 8:
            raise ApiError(
                422, "packing_layout_changed", "装箱单结构变化，请核对已确认的原格式。"
            )
        cells = list(sheet.iter_rows(min_col=1, max_col=8))
        if [_text(cells[0][i].value) for i in (0, 1, 2, 4, 5, 7)] != [
            "SKU",
            "ASIN",
            "FNSKU",
            "箱1",
            "箱2",
            "差异",
        ]:
            raise ApiError(
                422, "packing_layout_changed", "SKU及箱数量表头与已确认样表不一致。"
            )
        rows: list[dict[str, object]] = []
        issues: list[dict[str, object]] = []
        totals = [0, 0]
        footer_row = 0
        for index, row in enumerate(cells[1:], 2):
            code = _text(row[0].value)
            if not code:
                last = index - 1
                if [_text(row[i].value) for i in (3, 4, 5)] != [
                    f"=SUM(D2:D{last})",
                    f"=SUM(E2:E{last})",
                    f"=SUM(F2:F{last})",
                ]:
                    raise ApiError(
                        422,
                        "packing_layout_changed",
                        "未找到明确的SKU明细结束行，请核对原表。",
                    )
                footer_row = index
                break
            if row[0].data_type != "s":
                raise ApiError(422, "packing_sku_invalid", "SKU必须保留原表文字编码。")
            box1, box2 = _box_units(row[4].value), _box_units(row[5].value)
            totals[0] += box1
            totals[1] += box2
            amount = box1 + box2
            original_d = _text(row[3].value)
            compare = (
                str(int(original_d) - amount)
                if original_d.isascii() and original_d.isdecimal()
                else None
            )
            if _text(row[6].value) != f"=SUM(E{index}:F{index})":
                issues.append(
                    {
                        "row": index,
                        "message": (
                            "原G列不是已确认的箱内合计公式；"
                            "预览仍仅合计明确箱内件数，请核对。"
                        ),
                    }
                )
            if compare not in {None, "0"}:
                issues.append(
                    {
                        "row": index,
                        "message": (
                            "原D列与箱内合计不一致；"
                            "D列无表头，仅供核对，不当成额外出货。"
                        ),
                    }
                )
            rows.append(
                {
                    "source_row": index,
                    "sku_code": code,
                    "asin": _text(row[1].value),
                    "fnsku": _text(row[2].value),
                    "box1_units": str(box1),
                    "box2_units": str(box2),
                    "source_units": str(amount),
                    "original_d": original_d,
                    "reference_difference": compare,
                    "sku_id": None,
                    "order_line_id": None,
                }
            )
        if not footer_row or not rows:
            raise ApiError(
                422, "packing_layout_changed", "装箱单缺少明确的商品明细/合计边界。"
            )
        return {
            "sample_id": PACKING_SAMPLE,
            "filename": filename,
            "source_digest": digest,
            "sheet": "Sheet1",
            "rows": rows,
            "issues": issues,
            "source_units": str(sum(totals)),
            "box1_units": str(totals[0]),
            "box2_units": str(totals[1]),
            "excluded_sheets": [name for name in book.sheetnames if name != "Sheet1"],
            "excluded_rows": list(range(footer_row, sheet.max_row + 1)),
            "business_date": "",
            "filename_date_hint": _filename_date_hint(filename),
            "dispatch_status": "ASSUMED_DISPATCHED",
            "date_status": "UNVERIFIED",
            "mapping_status": "UNRESOLVED",
            "order_status": "UNRESOLVED",
            "confirmation_enabled": False,
        }
    finally:
        book.close()


def _filename_date_hint(filename: str) -> str:
    match = re.search(
        r"(?<![0-9])(20[0-9]{2})([01][0-9])([0-3][0-9])(?![0-9])", filename
    )
    if match:
        try:
            return date(*map(int, match.groups())).isoformat()
        except ValueError:
            pass
    return ""


def _path(root: Path, context: CurrentSiteContext, source_id: str) -> Path:
    return (
        root
        / "drafts"
        / str(context.site_id)
        / str(context.principal_user_id)
        / f"{source_id}.json"
    )


def packing_detail(
    settings: Settings, context: CurrentSiteContext, source_id: str = PACKING_SAMPLE
) -> dict[str, object]:
    root = draft_root(settings, context)
    source = read_packing_source(root, source_id, context)
    path = _path(root, context, source_id)
    saved = json.loads(path.read_text(encoding="utf-8")) if path.is_file() else None
    if saved and saved["source_digest"] != source["source_digest"]:
        raise ApiError(
            409, "source_snapshot_changed", "装箱单副本已改变，不能覆盖旧草稿。"
        )
    return {
        **source,
        "saved_draft": saved,
        "catalog_reference": catalog_reference(root, source, context),
    }


def save_packing_draft(
    settings: Settings,
    context: CurrentSiteContext,
    body: SavePackingDraft,
    key: UUID,
    source_id: str = PACKING_SAMPLE,
) -> dict[str, object]:
    root = draft_root(settings, context)
    source = read_packing_source(root, source_id, context)
    if body.source_digest != source["source_digest"]:
        raise ApiError(409, "source_snapshot_changed", "装箱单副本已变化，请重新预览。")
    if body.business_date:
        try:
            date.fromisoformat(body.business_date)
        except ValueError as error:
            raise ApiError(
                422, "invalid_date", "请输入有效日期，或暂留空待核对。"
            ) from error
    rows = cast(list[dict[str, object]], source["rows"])
    if [line.source_row for line in body.lines] != [row["source_row"] for row in rows]:
        raise ApiError(422, "source_rows_changed", "请保留原装箱单全部明细及顺序。")
    path = _path(root, context, source_id)
    payload = body.model_dump()
    with _SAVE_LOCK:
        existing = (
            json.loads(path.read_text(encoding="utf-8")) if path.is_file() else None
        )
        if existing and existing["last_save_key"] == str(key):
            if existing["saved_input"] != payload:
                raise ApiError(
                    409, "idempotency_key_reused", "同一操作ID不能保存不同草稿内容。"
                )
            return cast(dict[str, object], existing)
        revision = existing["revision"] if existing else 0
        if body.revision != revision:
            raise ApiError(
                409, "source_draft_revision_conflict", "草稿已更新，请重新载入后核对。"
            )
        saved = {
            **payload,
            "sample_id": source_id,
            "filename": source["filename"],
            "revision": revision + 1,
            "status": "IMPORT_DRAFT",
            "updated_at": datetime.now(UTC).isoformat(),
            "actor_id": str(context.principal_user_id),
            "last_save_key": str(key),
            "saved_input": payload,
            "original_rows": rows,
            "draft_units": str(sum(int(line.actual_units) for line in body.lines)),
            "dispatch_status": "ASSUMED_DISPATCHED",
            "date_status": "USER_ENTERED_UNVERIFIED"
            if body.business_date
            else "UNVERIFIED",
            "order_status": "UNRESOLVED",
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
