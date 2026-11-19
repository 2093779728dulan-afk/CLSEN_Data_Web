"""Original values for the four editable business tables; never a business writer."""

# ruff: noqa: RUF001 -- Chinese business labels.
import hashlib
import json
import re
from pathlib import Path
from typing import Any, Literal

from app.api.errors import ApiError
from app.production.source_registry import (
    _UPLOAD_LOCK,
    _area,
    register_upload,
    uploaded_bytes,
)
from app.site_context import CurrentSiteContext


def remember_baseline(
    root: Path,
    context: CurrentSiteContext,
    kind: str,
    raw: bytes,
    result: dict[str, Any],
) -> dict[str, Any]:
    if result.get("issues") or not result.get("rows"):
        return result
    rows = []
    if kind == "orders":
        command = result["command"]
        rows.append(
            {
                "key": "document",
                "label": "订单信息",
                "values": {
                    "下单日期": command.get("business_date") or "",
                    "业务订单号": command.get("business_number") or "",
                },
            }
        )
        positions = {
            str(row.get("sku_id")): row["source_row"]
            for row in (result.get("source_table") or {}).get("rows", [])
        }
        for i, row in enumerate(result["rows"], 2):
            rows.append(
                {
                    "key": str(row["sku_id"]),
                    "label": row["sku_label"],
                    "values": {"下单数量": str(row["expected_units"])},
                    "row": positions.get(str(row["sku_id"]), i),
                }
            )
    elif kind == "receipt":
        for row in result["rows"]:
            rows.append(
                {
                    "key": str(row["order_line_id"]),
                    "label": row["sku_label"],
                    "row": row["row"],
                    "values": {
                        "合格": row["qualified_units"],
                        "待检": row["pending_units"],
                        "次品": row["defective_units"],
                    },
                }
            )
    elif kind == "packing":
        for sku in dict.fromkeys(row["sku_id"] for row in result["rows"]):
            items = [row for row in result["rows"] if row["sku_id"] == sku]
            rows.append(
                {
                    "key": sku,
                    "label": items[0]["sku_label"],
                    "row": items[0]["row"],
                    "values": {
                        "出货数量": str(sum(int(row["units"]) for row in items)),
                        "装箱分配": "；".join(
                            sorted(
                                f"{row['box_number']}：{row['units']}" for row in items
                            )
                        ),
                    },
                }
            )
    else:
        for row in result["rows"]:
            rows.append(
                {
                    "key": f"{row['sku_id']}:{row['quality']}",
                    "label": row["sku_label"],
                    "row": row["row"],
                    "values": {"状态": row["quality_label"], "实盘总数": row["units"]},
                }
            )
    source_kind: Literal["orders", "shipments"] = (
        "orders" if kind == "orders" else "shipments"
    )
    original, _ = register_upload(
        root,
        context,
        source_kind,
        result["filename"],
        raw,
        {"source_digest": hashlib.sha256(raw).hexdigest()},
    )
    baseline = {
        "kind": kind,
        "filename": result["filename"],
        "rows": rows,
        "source_id": original["sample_id"],
        "source_kind": source_kind,
    }
    if kind == "orders":
        baseline["command_source"] = {
            key: result["command"].get(key)
            for key in (
                "source_system",
                "source_event_kind",
                "external_event_id",
                "source_batch",
            )
        }
    content = json.dumps(baseline, ensure_ascii=False, sort_keys=True).encode("utf-8")
    baseline_id = f"table-baseline-{hashlib.sha256(content).hexdigest()}"
    directory = _area(root, context) / "table-baselines"
    with _UPLOAD_LOCK:
        directory.mkdir(parents=True, exist_ok=True)
        path = directory / f"{baseline_id}.json"
        if not path.exists():
            temporary = path.with_suffix(".tmp")
            try:
                temporary.write_bytes(content)
                temporary.replace(path)
            finally:
                temporary.unlink(missing_ok=True)
    result["table_baseline"] = {**baseline, "id": baseline_id}
    return result


def read_baseline(
    root: Path, context: CurrentSiteContext, baseline_id: str
) -> dict[str, Any]:
    if not re.fullmatch(r"table-baseline-[a-f0-9]{64}", baseline_id):
        raise ApiError(404, "baseline_missing", "当前账号没有这份原表核对记录。")
    path = _area(root, context) / "table-baselines" / f"{baseline_id}.json"
    if not path.is_file():
        raise ApiError(404, "baseline_missing", "当前账号没有这份原表核对记录。")
    raw = path.read_bytes()
    if hashlib.sha256(raw).hexdigest() != baseline_id.removeprefix("table-baseline-"):
        raise ApiError(409, "baseline_changed", "原表核对记录已改变，请重新核对。")
    baseline = json.loads(raw)
    uploaded_bytes(root, context, baseline["source_id"], baseline["source_kind"])
    return {**baseline, "id": baseline_id}
