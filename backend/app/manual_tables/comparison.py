# ruff: noqa: RUF001 -- Chinese user-facing punctuation.
"""Compare only explicitly selected, scoped revisions; never infer stock events."""

from typing import Any

from app.api.errors import ApiError
from app.catalog.normalization import catalog_identity_key_v1
from app.manual_tables.service import ManualTables


def totals(batch: dict[str, Any]) -> dict[tuple[str, ...], dict[str, Any]]:
    result: dict[tuple[str, ...], dict[str, Any]] = {}
    for row in batch["result"]["rows"]:
        if row["excluded"]:
            continue
        key = tuple(
            catalog_identity_key_v1(row[k] or "?").text
            for k in ("style", "color", "size")
        )
        item = result.setdefault(
            key,
            {
                "style": row["style"],
                "color": row["color"],
                "size": row["size"],
                "units": 0,
                "unknown": False,
                "sources": [],
            },
        )
        item["unknown"] |= row["units"] is None
        item["units"] += int(row["units"] or "0")
        item["sources"].append(row["source_ref"])
    return result


def selected(
    svc: ManualTables, references: dict[str, dict[str, Any]]
) -> dict[str, dict[str, Any]]:
    result = {}
    for role, ref in references.items():
        batch = svc.get(str(ref["id"]))
        if batch["revision"] != ref["revision"]:
            raise ApiError(
                409, "manual_compare_stale", "所选资料已有新修订，请刷新后重新选择。"
            )
        expected = "inventory" if role in {"before", "inventory"} else role
        if batch["kind"] != expected:
            raise ApiError(
                422,
                "manual_compare_kind",
                "所选资料类型不符，请分别选择库存、预下单和装箱资料。",
            )
        result[role] = batch
    return result


def compare(svc: ManualTables, references: dict[str, dict[str, Any]]) -> dict[str, Any]:
    batches = selected(svc, references)
    values = {role: totals(batch) for role, batch in batches.items()}
    keys = sorted({key for table in values.values() for key in table})
    rows = []
    for key in keys:
        exemplar = next(table[key] for table in values.values() if key in table)
        row = {k: exemplar[k] for k in ("style", "color", "size")}
        for role, table in values.items():
            row[role] = (
                str(table[key]["units"])
                if key in table and not table[key]["unknown"]
                else None
            )
        row["unexplained_difference"] = None
        if all(row.get(k) is not None for k in ("before", "inventory", "packing")):
            row["unexplained_difference"] = str(
                int(row["inventory"]) - (int(row["before"]) - int(row["packing"]))
            )
        row["unshipped_planned"] = (
            str(int(row["orders"]) - int(row["packing"]))
            if row.get("orders") is not None and row.get("packing") is not None
            else None
        )
        rows.append(row)
    warnings = [
        "只比较选定修订；未列规格显示未提供，不当作0。预计订单不增加实物，差额不自动过账。"
    ]
    warehouses = {
        b["options"]["context"].get("warehouse", "")
        for role, b in batches.items()
        if role != "orders"
    }
    if "" in warehouses or len(warehouses) != 1:
        warnings.append(
            "仓库尚未明确一致，数量仅供逐项核对，不能据此认定库存覆盖了出货。"
        )
    if "inventory" in batches:
        warnings.append(
            "库存口径："
            + (batches["inventory"]["options"]["context"].get("basis") or "待确认")
        )
    return {"references": references, "rows": rows, "warnings": warnings}
