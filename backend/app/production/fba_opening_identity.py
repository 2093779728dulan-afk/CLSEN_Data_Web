"""Explicit FBA-local identity evidence; never publishes a platform catalog map."""

# ruff: noqa: RUF001 -- Chinese row-level import diagnostics.
import base64
import csv
import hashlib
import re
from io import StringIO
from pathlib import Path
from typing import Any

from app.api.errors import ApiError
from app.catalog.normalization import seller_sku_match_v1


def parse_identity_source(raw: bytes) -> list[dict[str, Any]]:
    if not raw or len(raw) > 2_000_000:
        raise ApiError(422, "fba_mapping_invalid", "请选择2MB以内的非空身份核对CSV。")
    try:
        reader = csv.DictReader(StringIO(raw.decode("utf-8-sig")), strict=True)
        if not {"Seller SKU", "ASIN", "FNSKU", "来源店铺"}.issubset(
            reader.fieldnames or []
        ):
            raise ValueError("headers")
        rows = []
        seen = set()
        fnskus = set()
        stores = set()
        for row in reader:
            location = f"CSV第{reader.line_num}行"
            sku = row.get("Seller SKU") or ""
            asin, fnsku, store = (
                row.get(key) or "" for key in ("ASIN", "FNSKU", "来源店铺")
            )
            if (
                None in row
                or not sku
                or len(sku) > 255
                or not store.strip()
                or len(store) > 255
                or any(ord(c) < 32 for c in sku + store)
            ):
                raise ApiError(
                    422,
                    "fba_mapping_invalid",
                    f"{location}：Seller SKU或来源店铺为空、过长或含控制字符。",
                )
            for key, value in (("ASIN", asin), ("FNSKU", fnsku)):
                if not re.fullmatch(r"[A-Z0-9]{10}", value):
                    raise ApiError(
                        422,
                        "fba_mapping_invalid",
                        f"{location}：{key}应为10位大写字母或数字，请修改原表后上传。",
                    )
            match = seller_sku_match_v1(sku).utf8
            if match in seen or fnsku in fnskus:
                raise ApiError(
                    422,
                    "fba_mapping_duplicate",
                    f"{location}：Seller SKU或FNSKU重复，请核对原表。",
                )
            seen.add(match)
            fnskus.add(fnsku)
            stores.add(store)
            rows.append(
                {
                    "source_row": reader.line_num,
                    "seller_sku": sku,
                    "asin": asin,
                    "fnsku": fnsku,
                    "store": store,
                }
            )
            if len(rows) > 5000:
                raise ValueError("rows")
        if not rows or len(stores) != 1:
            raise ApiError(
                422,
                "fba_mapping_scope",
                "CSV须包含同一个来源店铺的商品，不能混用多个店铺。",
            )
        return rows
    except (UnicodeError, csv.Error, ValueError) as exc:
        raise ApiError(
            422,
            "fba_mapping_invalid",
            "请选择含Seller SKU、ASIN、FNSKU和来源店铺的UTF-8 CSV，最多5000行。",
        ) from exc


def _source_path(root: str, site: int, actor: int, scope: int, digest: str) -> Path:
    if not root or not re.fullmatch(r"[a-f0-9]{64}", digest):
        raise ApiError(
            422, "fba_identity_source", "请重新读取身份核对CSV，再确认期初。"
        )
    return (
        Path(root)
        / "fba-identity-uploads"
        / str(site)
        / str(actor)
        / str(scope)
        / f"{digest}.csv"
    )


def read_identity_source(
    root: str, site: int, actor: int, scope: int, digest: str
) -> bytes:
    path = _source_path(root, site, actor, scope, digest)
    if not path.is_file():
        raise ApiError(
            404, "fba_identity_source", "当前账号下没有这份身份原表，请重新读取文件。"
        )
    raw = path.read_bytes()
    if hashlib.sha256(raw).hexdigest() != digest:
        raise ApiError(
            409, "fba_identity_source_changed", "身份原表副本已变化，请重新上传核对。"
        )
    return raw


def retain_identity_source(
    root: str, site: int, actor: int, scope: int, raw: bytes
) -> str:
    digest = hashlib.sha256(raw).hexdigest()
    path = _source_path(root, site, actor, scope, digest)
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        with path.open("xb") as stream:
            stream.write(raw)
    except FileExistsError:
        read_identity_source(root, site, actor, scope, digest)
    return digest


def verify_identity(
    line: dict[str, Any], catalog: dict[str, Any], mapped_sku_ids: list[str]
) -> dict[str, Any]:
    sku_id, raw = str(line.get("sku_id", "")), line.get("seller_sku", "")
    sku = catalog.get(sku_id)
    location = f"CSV第{line.get('source_row', '?')}行 · {raw}"
    if not sku or sku.get("status") != "active":
        raise ApiError(
            409,
            "fba_identity_unmatched",
            f"{location}：请选择当前目录已启用的商品规格。",
        )
    if mapped_sku_ids:
        if set(mapped_sku_ids) != {sku_id}:
            raise ApiError(
                409,
                "fba_identity_conflict",
                f"{location}：已有店铺商品关联与所选规格冲突，请先更正关联。",
            )
        basis = "approved_catalog_mapping"
    else:
        exact = [key for key, item in catalog.items() if item.get("code") == raw]
        if exact != [sku_id]:
            raise ApiError(
                409,
                "fba_identity_unmatched",
                f"{location}：未建立店铺关联时，须与唯一正式SKU完全一致（含大小写、空格）；不能按相似名称确认。",
            )
        basis = "confirmed_fba_identity_source"
    return {
        "seller_sku": raw,
        "match": base64.b64encode(seller_sku_match_v1(raw).utf8).decode("ascii"),
        "basis": basis,
    }
