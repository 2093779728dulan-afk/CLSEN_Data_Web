"""Immutable comparison snapshots for the warehouse dispatch editor."""

# ruff: noqa: RUF001 -- Chinese business messages.
import hashlib
import json
from pathlib import Path
from typing import Any, Literal, cast

from pydantic import Field

from app.api.errors import ApiError
from app.catalog.models import StrictCatalogModel
from app.production.source_registry import (
    save_upload_review,
    uploaded_bytes,
    uploaded_source,
)
from app.production.workbench_tables import preview_dispatch
from app.site_context import CurrentSiteContext


class DispatchReviewRow(StrictCatalogModel):
    source_row: int | None = Field(default=None, ge=2, le=501)
    line_id: str | None = Field(default=None, pattern=r"^[1-9][0-9]*$")
    sku_id: str = Field(pattern=r"^[1-9][0-9]*$")
    actual_units: str = Field(pattern=r"^[1-9][0-9]{0,18}$")


class DispatchSourceInput(StrictCatalogModel):
    source_id: str = Field(pattern=r"^upload-shipments-[a-f0-9]{64}$")
    layout: Literal["standard", "packing_totals"] = "standard"


class DispatchSourcesInput(StrictCatalogModel):
    sources: list[DispatchSourceInput] = Field(min_length=1, max_length=20)
    warehouse_id: str = Field(pattern=r"^[1-9][0-9]{0,18}$")
    owner_id: str = Field(pattern=r"^[1-9][0-9]{0,18}$")


class DispatchReviewInput(DispatchSourceInput):
    sources: list[DispatchSourceInput] | None = Field(
        default=None, min_length=1, max_length=20
    )
    warehouse_id: str = Field(pattern=r"^[1-9][0-9]{0,18}$")
    owner_id: str = Field(pattern=r"^[1-9][0-9]{0,18}$")
    rows: list[DispatchReviewRow] = Field(min_length=1, max_length=500)


def preview_dispatch_sources(
    root: Path,
    context: CurrentSiteContext,
    sources: list[DispatchSourceInput],
    scope: dict[str, Any],
    catalog: dict[str, Any],
) -> dict[str, Any]:
    if len({source.source_id for source in sources}) != len(sources):
        raise ApiError(
            409, "duplicate_packing_source", "同一份装箱单已导入，请移除重复文件。"
        )
    previews = []
    for source in sources:
        original = uploaded_source(root, context, source.source_id, "shipments")
        raw = uploaded_bytes(root, context, source.source_id, "shipments")
        preview = preview_dispatch(
            raw, str(original["filename"]), scope, catalog, source.layout
        )
        preview["source_id"] = source.source_id
        previews.append(preview)
    if len(previews) == 1:
        return previews[0]
    if sum(len(preview["source_rows"]) for preview in previews) > 500:
        raise ApiError(
            422, "packing_row_limit", "合并后的商品明细最多500行，请分批出货。"
        )
    result = {
        **previews[0],
        "filename": f"{len(previews)}份装箱单",
        "rows": [],
        "source_rows": [],
        "issues": [],
        "cartons": [],
        "box_count": 0,
    }
    result["source_files"] = [
        {
            "source_id": preview["source_id"],
            "source_layout": preview["source_layout"],
            "filename": preview["filename"],
            "source_digest": preview["source_digest"],
        }
        for preview in previews
    ]
    result["source_digest"] = hashlib.sha256(
        json.dumps(result["source_files"], sort_keys=True, ensure_ascii=False).encode()
    ).hexdigest()
    for preview in previews:
        positions = {}
        for row in preview["source_rows"]:
            number = len(result["source_rows"]) + 2
            positions[row["row"]] = number
            result["source_rows"].append(
                {
                    **row,
                    "row": number,
                    "source_row": row["row"],
                    "source_filename": preview["filename"],
                }
            )
        result["rows"].extend(
            {**row, "row": positions[row["row"]]} for row in preview["rows"]
        )
        result["issues"].extend(
            {
                **issue,
                "row": positions.get(issue["row"], 0),
                "source_filename": preview["filename"],
                "source_row": issue["row"],
            }
            for issue in preview["issues"]
        )
    result["total_units"] = str(
        sum(int(preview["total_units"]) for preview in previews)
    )
    totals = [preview.get("source_total_units") for preview in previews]
    result["source_total_units"] = (
        str(sum(int(cast(str, total)) for total in totals))
        if all(total is not None for total in totals)
        else None
    )
    result["source_row_count"] = len(result["source_rows"])
    if (
        int(result["source_total_units"] or result["total_units"])
        > 9_223_372_036_854_775_807
    ):
        raise ApiError(422, "review_quantity", "合并出货数量超出范围，请分批出货。")
    return result


def save_dispatch_review(
    root: Path,
    context: CurrentSiteContext,
    body: DispatchReviewInput,
    scope: dict[str, Any],
    catalog: dict[str, Any],
) -> dict[str, Any]:
    sources = body.sources or [
        DispatchSourceInput(source_id=body.source_id, layout=body.layout)
    ]
    if sources[0].source_id != body.source_id:
        raise ApiError(
            422, "review_source_changed", "装箱单来源已改变，请重新导入核对。"
        )
    baseline = preview_dispatch_sources(root, context, sources, scope, catalog)
    if any(issue.get("stage") != "business" for issue in baseline["issues"]):
        raise ApiError(422, "source_unreadable", "原表仍有读取问题，请修正后重新导入。")
    baseline["source_id"] = body.source_id
    original_rows = {row["row"] for row in baseline["source_rows"]}
    seen = set()
    rows = []
    total = 0
    for row in body.rows:
        if row.sku_id not in catalog:
            raise ApiError(422, "review_sku_scope", "修改商品不属于当前来源仓和货主。")
        if row.source_row is not None:
            if row.source_row not in original_rows or row.source_row in seen:
                raise ApiError(
                    422, "review_source_row", "原表行号缺失或重复，请重新导入。"
                )
            seen.add(row.source_row)
        total += int(row.actual_units)
        rows.append({**row.model_dump(), "sku_code": catalog[row.sku_id]["code"]})
    if total > 9_223_372_036_854_775_807:
        raise ApiError(422, "review_quantity", "本次出货合计超出数量范围。")
    review = {"baseline": baseline, "rows": rows}
    return {"review_id": save_upload_review(root, context, body.source_id, review)}
