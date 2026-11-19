# ruff: noqa: RUF001 -- Chinese user-facing punctuation.
"""Field definitions shared by extraction, templates and round-trip exports."""

import json
from datetime import date
from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

Kind = Literal["inventory", "orders", "packing"]
SIZES = ("XS", "S", "M", "L", "XL", "XXL", "3XL")
TITLES = {"inventory": "库存结存", "orders": "预下单", "packing": "装箱资料"}
VERSION = "manual-tables-v1"
FIELDS = {
    "style": "款号",
    "color": "颜色",
    "size": "尺码",
    "units": "数量",
    "code": "原商品编码",
    "warehouse": "仓库",
    "date": "业务日期",
    "planned_date": "预计出货日期",
    "basis": "结存口径",
    "number": "来源单号",
    "box": "箱号",
    "asin": "ASIN",
    "fnsku": "FNSKU",
    "dispatched": "实际已发",
    "order_number": "对应系统订单号",
    "source_line": "来源行标识",
    "notes": "备注",
    "total": "原表合计",
}
EXPORT_FIELDS = {
    "inventory": (
        "style",
        "color",
        "size",
        "units",
        "warehouse",
        "date",
        "basis",
        "code",
        "source_line",
        "notes",
    ),
    "orders": (
        "style",
        "color",
        "size",
        "units",
        "date",
        "planned_date",
        "number",
        "code",
        "source_line",
        "notes",
    ),
    "packing": (
        "code",
        "style",
        "color",
        "size",
        "box",
        "units",
        "date",
        "dispatched",
        "warehouse",
        "order_number",
        "asin",
        "fnsku",
        "source_line",
        "notes",
    ),
}
SHEET_TITLES = {
    "inventory": "库存明细_v1",
    "orders": "预下单明细_v1",
    "packing": "装箱明细_v1",
}


class Options(BaseModel):
    model_config = ConfigDict(extra="forbid")
    sheet: str = Field(default="", max_length=100)
    header_row: int | None = Field(default=None, ge=1, le=20)
    start_row: int | None = Field(default=None, ge=1, le=20000)
    end_row: int | None = Field(default=None, ge=1, le=20000)
    columns: dict[str, Annotated[int, Field(strict=True, ge=0, le=80)]] = Field(
        default_factory=dict, max_length=80
    )
    context: dict[str, str] = Field(default_factory=dict, max_length=16)
    zero_policy: Literal["unknown", "blank_slash_zero"] = "unknown"
    decisions: dict[str, dict[str, Any]] = Field(default_factory=dict, max_length=2000)
    profile_id: str | None = None
    profile_version: int | None = Field(default=None, ge=1)
    aggregate_duplicates: bool = False
    aggregation_reason: str = Field(default="", max_length=1000)

    @field_validator("context")
    @classmethod
    def validate_context(cls, value: dict[str, str]) -> dict[str, str]:
        for key, item in value.items():
            if len(item) > (
                100000 if key in {"order_lines", "fulfillment_modes"} else 1000
            ):
                raise ValueError("业务口径文字过长，请缩小本次资料范围")
            if (
                key in {"date", "planned_date"}
                and item
                and date.fromisoformat(item).isoformat() != item
            ):
                raise ValueError("业务日期请使用年-月-日格式")
            if key in {"dispatched", "already_in_snapshot"} and item not in {
                "true",
                "false",
                "",
            }:
                raise ValueError("业务状态请选择是或否")
            if key == "fulfillment_modes" and item:
                try:
                    modes = json.loads(item)
                except (TypeError, ValueError) as error:
                    raise ValueError("出货来源选择无效，请重新选择") from error
                if not isinstance(modes, dict) or any(
                    not isinstance(sku, str)
                    or mode not in {"WAREHOUSE_STOCK", "PRODUCTION_DIRECT"}
                    for sku, mode in modes.items()
                ):
                    raise ValueError("出货来源请选择仓库库存出货或生产完成后直接出货")
        return value

    @field_validator("decisions")
    @classmethod
    def validate_decisions(
        cls, value: dict[str, dict[str, Any]]
    ) -> dict[str, dict[str, Any]]:
        strings = {"style", "color", "size", "units", "sku_id", "reason"}
        booleans = {"excluded", "include_hidden", "accept_total"}
        for decision in value.values():
            if set(decision) - strings - booleans - {"boxes"}:
                raise ValueError("只允许修改商品、数量、排除决定及核对原因")
            for key, item in decision.items():
                if key in strings and (not isinstance(item, str) or len(item) > 1000):
                    raise ValueError("商品字段、数量及原因应为不超过1000字的文字")
                if key in booleans and type(item) is not bool:
                    raise ValueError("包含、排除及合计确认必须选择是或否")
                if key == "boxes" and (not isinstance(item, dict) or len(item) > 80):
                    raise ValueError("箱内数量格式无效")
            if decision and not decision.get("reason", "").strip():
                raise ValueError("修改或排除原表明细须填写原因")
        return value


class Command(BaseModel):
    model_config = ConfigDict(extra="forbid")
    expected_revision: int = Field(ge=0)
    operation_token: str = Field(min_length=36, max_length=36)
    options: Options = Field(default_factory=Options)
    preview_hash: str = ""
    reason: str = Field(default="", max_length=1000)
    target: Literal["inventory_review", "order", "shipment"] | None = None


class HandoffCommand(Command):
    handoff_preview_hash: str = Field(default="", pattern=r"^([0-9a-f]{64})?$")


def issue(
    code: str,
    message: str,
    *,
    row: int = 0,
    cell: str = "",
    sheet: str = "",
    suggestion: str = "请核对原表并补充明确值。",
    blocking: bool = True,
) -> dict[str, Any]:
    return {
        "code": code,
        "message": message,
        "source_ref": {"sheet": sheet, "row": row, "cell": cell},
        "suggestion": suggestion,
        "blocking": blocking,
    }
