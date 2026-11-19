"""Fixed source inventory reconciliation; never an inventory ledger."""

# ruff: noqa: RUF001, E501
from __future__ import annotations

import hashlib
import json
from collections.abc import Callable
from copy import deepcopy
from datetime import UTC, date, datetime
from typing import Annotated, Any, Literal, Never, Self, cast
from uuid import UUID, uuid4

import sqlalchemy as sa
from pydantic import Field, model_validator
from sqlalchemy.dialects import mysql
from sqlalchemy.engine import Connection, Engine
from sqlalchemy.exc import IntegrityError, SQLAlchemyError

from app.api.errors import ApiError
from app.catalog.models import StrictCatalogModel
from app.catalog.queries import CatalogVersionSummary, MySqlCatalogQueries
from app.config import Settings
from app.production.inventory_product_match import product_match
from app.production.inventory_snapshot import SIZES, inventory_snapshot
from app.site_context import CurrentSiteContext

PARSER = "inventory-snapshot-v1"
POLICY = "inventory-review-v1"
metadata = sa.MetaData()
# Reference-only metadata; these existing tables are not created by this module.
sa.Table(
    "sites", metadata, sa.Column("id", mysql.BIGINT(unsigned=True), primary_key=True)
)
sa.Table(
    "users", metadata, sa.Column("id", mysql.BIGINT(unsigned=True), primary_key=True)
)
reviews = sa.Table(
    "production_inventory_reviews",
    metadata,
    sa.Column("review_id", mysql.BINARY(16), primary_key=True),
    sa.Column("site_id", mysql.BIGINT(unsigned=True), nullable=False),
    sa.Column("source_identity", sa.String(64, collation="ascii_bin"), nullable=False),
    sa.Column("source_digest", sa.String(64, collation="ascii_bin"), nullable=False),
    sa.Column(
        "source_manifest_digest", sa.String(64, collation="ascii_bin"), nullable=False
    ),
    sa.Column("source_format", sa.String(32), nullable=False),
    sa.Column("source_name", sa.String(240), nullable=False),
    sa.Column("parser_version", sa.String(40), nullable=False),
    sa.Column("policy_version", sa.String(40), nullable=False),
    sa.Column("source_snapshot_json", sa.JSON(), nullable=False),
    sa.Column("revision", sa.Integer(), nullable=False),
    sa.Column(
        "created_by",
        mysql.BIGINT(unsigned=True),
        sa.ForeignKey("users.id"),
        nullable=False,
    ),
    sa.Column(
        "updated_by",
        mysql.BIGINT(unsigned=True),
        sa.ForeignKey("users.id"),
        nullable=False,
    ),
    sa.Column("created_at", mysql.DATETIME(fsp=6), nullable=False),
    sa.Column("updated_at", mysql.DATETIME(fsp=6), nullable=False),
    sa.ForeignKeyConstraint(["site_id"], ["sites.id"], ondelete="RESTRICT"),
    sa.UniqueConstraint(
        "site_id", "source_identity", name="uq_inventory_review_source"
    ),
    sa.UniqueConstraint("site_id", "review_id", name="uq_inventory_review_site"),
    mysql_engine="InnoDB",
    mysql_charset="utf8mb4",
)
revisions = sa.Table(
    "production_inventory_review_revisions",
    metadata,
    sa.Column("site_id", mysql.BIGINT(unsigned=True), primary_key=True),
    sa.Column("review_id", mysql.BINARY(16), primary_key=True),
    sa.Column("revision", sa.Integer(), primary_key=True),
    sa.Column("operation_id", mysql.BINARY(16), nullable=False),
    sa.Column("request_hash", sa.String(64, collation="ascii_bin"), nullable=False),
    sa.Column("command_json", sa.JSON(), nullable=False),
    sa.Column("effective_overrides_json", sa.JSON(), nullable=False),
    sa.Column("result_json", sa.JSON(), nullable=False),
    sa.Column(
        "actor_id",
        mysql.BIGINT(unsigned=True),
        sa.ForeignKey("users.id"),
        nullable=False,
    ),
    sa.Column("at", mysql.DATETIME(fsp=6), nullable=False),
    sa.Column("reason", sa.String(1000), nullable=False),
    sa.UniqueConstraint(
        "site_id", "operation_id", name="uq_inventory_review_operation"
    ),
    sa.ForeignKeyConstraint(
        ["site_id", "review_id"],
        [
            "production_inventory_reviews.site_id",
            "production_inventory_reviews.review_id",
        ],
        ondelete="RESTRICT",
    ),
    mysql_engine="InnoDB",
    mysql_charset="utf8mb4",
)
Digest = Annotated[str, Field(pattern=r"^[a-f0-9]{64}$")]
Quantity = Annotated[str, Field(pattern=r"^(0|[1-9][0-9]{0,17})$")]
Key = Annotated[str, Field(min_length=1, max_length=240)]


class StartReview(StrictCatalogModel):
    source_digest: Digest
    source_manifest_digest: Digest


class LocationChange(StrictCatalogModel):
    type: Literal["set_location"]
    source_key: Key
    value: Literal["WAREHOUSE_1", "OUTSIDE_SCOPE", "UNCONFIRMED"]


class DateChange(StrictCatalogModel):
    type: Literal["set_stocktake_date"]
    value: Annotated[str, Field(pattern=r"^[0-9]{4}-[0-9]{2}-[0-9]{2}$")] | None

    @model_validator(mode="after")
    def valid_calendar_date(self) -> Self:
        if self.value is not None:
            date.fromisoformat(self.value)
        return self


class CutoffChange(StrictCatalogModel):
    type: Literal["set_cutoff_note"]
    value: Annotated[str, Field(max_length=1000)]


class SizeChange(StrictCatalogModel):
    type: Literal["set_size_quantity"]
    source_key: Key
    size: Literal["XS", "S", "M", "L", "XL", "XXL", "3XL"]
    value: Quantity | None


class TotalChange(StrictCatalogModel):
    type: Literal["set_reviewed_total"]
    source_key: Key
    value: Quantity | None


class ProductReference(StrictCatalogModel):
    sku_id: Annotated[str, Field(pattern=r"^[1-9][0-9]{0,19}$")]
    catalog_version_id: Annotated[str, Field(pattern=r"^[1-9][0-9]{0,19}$")]
    catalog_publication_revision: Annotated[str, Field(pattern=r"^[1-9][0-9]{0,19}$")]


class ProductChange(StrictCatalogModel):
    type: Literal["set_product"]
    source_key: Key
    size: Literal["XS", "S", "M", "L", "XL", "XXL", "3XL"]
    value: ProductReference | None


class RestoreChange(StrictCatalogModel):
    type: Literal["restore_source_field"]
    source_key: Key | None = None
    field: Literal[
        "location",
        "stocktaken_on",
        "cutoff_note",
        "reviewed_total",
        "XS",
        "S",
        "M",
        "L",
        "XL",
        "XXL",
        "3XL",
    ]


Change = Annotated[
    LocationChange
    | DateChange
    | CutoffChange
    | SizeChange
    | TotalChange
    | ProductChange
    | RestoreChange,
    Field(discriminator="type"),
]


class PreviewCommand(StrictCatalogModel):
    source_identity: Digest
    expected_revision: Annotated[int, Field(strict=True, ge=0)]
    changes: Annotated[list[Change], Field(min_length=1, max_length=902)]
    reason: Annotated[str, Field(min_length=1, max_length=1000)]

    @model_validator(mode="after")
    def validate_changes(self) -> Self:
        if not self.reason.strip():
            raise ValueError("核对依据不能为空")
        keys = set()
        rows = set()
        for change in self.changes:
            key, field = change_target(change)
            if (key, field) in keys:
                raise ValueError("同一行字段不能重复修改")
            keys.add((key, field))
            if key is not None:
                rows.add(key)
        if len(rows) > 100:
            raise ValueError("一次最多处理100条来源行")
        return self


class SaveCommand(PreviewCommand):
    preview_hash: Digest


def change_target(change: Any) -> tuple[str | None, str]:
    field = {
        "set_location": "location",
        "set_stocktake_date": "stocktaken_on",
        "set_cutoff_note": "cutoff_note",
        "set_reviewed_total": "reviewed_total",
    }.get(change.type)
    if isinstance(change, SizeChange):
        field = change.size
    if isinstance(change, ProductChange):
        field = "product_" + change.size
    if isinstance(change, RestoreChange):
        field = change.field
        if (field in ("stocktaken_on", "cutoff_note")) != (change.source_key is None):
            raise ValueError("恢复原值的记录范围不匹配")
    return getattr(change, "source_key", None), cast(str, field)


def digest(value: Any) -> str:
    return hashlib.sha256(
        json.dumps(
            value, ensure_ascii=False, sort_keys=True, separators=(",", ":")
        ).encode()
    ).hexdigest()


def source_identity(snapshot: dict[str, Any]) -> str:
    return digest(
        [snapshot["source_digest"], snapshot["source_manifest_digest"], PARSER, POLICY]
    )


def fail(code: str, message: str, status: int = 422) -> Never:
    raise ApiError(status, code, message)


def source_quantity_changed(values: dict[str, Any]) -> bool:
    return any(size in values for size in SIZES)


def product_key(row: dict[str, Any]) -> tuple[str, str]:
    style = str(row["style_code"])
    return (
        ("source", str(row["source_key"]))
        if not style or style == "无款号" or "改" in style or "\n" in style
        else ("style", style)
    )


def color_key(row: dict[str, Any]) -> tuple[tuple[str, str], str]:
    color = str(row["color"] or row["color_note"])
    return product_key(row), str(
        row["source_key"]
    ) if not color or "\n" in color or "/" in color else color.lower()


def effective(snapshot: dict[str, Any], overrides: dict[str, Any]) -> dict[str, Any]:
    result = deepcopy(snapshot)
    rows = result["rows"] + result["unconfirmed_rows"]
    partitions: dict[str, list[dict[str, Any]]] = {
        "WAREHOUSE_1": [],
        "UNCONFIRMED": [],
        "OUTSIDE_SCOPE": [],
    }
    for row in rows:
        values = overrides.get("rows", {}).get(row["source_key"], {})
        links = overrides.get("products", {}).get(row["source_key"], {})
        if links:
            row["product_links"] = deepcopy(links)
        row["location_group"] = values.get("location", row["location_group"])
        for size in SIZES:
            if size in values:
                original = row["quantities"].get(size, {"cell": "", "raw": ""})
                row["quantities"][size] = original | {
                    "units": values[size],
                    "state": "UNKNOWN" if values[size] is None else "LITERAL",
                }
        quantities = row["quantities"]
        row["literal_units"] = str(
            sum(int(q["units"]) for q in quantities.values() if q["state"] == "LITERAL")
        )
        row["formula_units"] = str(
            sum(
                int(q["units"])
                for q in quantities.values()
                if q["state"] == "ADDITION_REFERENCE"
            )
        )
        row["unknown_cells"] = sum(
            quantities.get(size, {}).get("state") != "LITERAL" for size in SIZES
        )
        total = values.get(
            "reviewed_total",
            row["source_total"]["units"]
            if row["source_total"]["state"] == "LITERAL"
            else None,
        )
        row["reviewed_total"] = total
        row["quantity_complete"] = total is not None
        row["stock_units"] = (
            (total if total is not None else row["literal_units"])
            if "reviewed_total" in values
            or source_quantity_changed(values)
            or snapshot["quantity_basis"] == "DECLARED_TOTAL"
            else row["stock_units"]
        )
        row["issues"] = []
        if total is not None and (
            int(row["literal_units"]) > int(total)
            or (row["unknown_cells"] == 0 and int(row["literal_units"]) != int(total))
        ):
            row["issues"].append("已知尺码量超过合计，需核对合计。")
        if row["unknown_cells"]:
            row["issues"].append("尺码数量仍待核，不自动补0。")
        partitions[row["location_group"]].append(row)
    for group in partitions.values():
        if sum(int(row["stock_units"]) for row in group) >= 10**18:
            fail(
                "inventory_review_quantity_conflict",
                "汇总超过18位数量上限，请缩小资料范围。",
            )
    result["rows"] = partitions["WAREHOUSE_1"]
    result["unconfirmed_rows"] = partitions["UNCONFIRMED"]
    result["outside_rows"] = partitions["OUTSIDE_SCOPE"]
    result["stocktaken_on"] = overrides.get("stocktaken_on", snapshot["stocktaken_on"])
    result["cutoff_note"] = overrides.get(
        "cutoff_note",
        snapshot.get("cutoff_note", "")
        if snapshot.get("source_kind") == "MANUAL"
        else "",
    )
    result["summary"].update(
        {
            "literal_units": str(
                sum(int(row["literal_units"]) for row in result["rows"])
            ),
            "warehouse_1_literal_units": str(
                sum(int(row["literal_units"]) for row in result["rows"])
            ),
            "location_unconfirmed_literal_units": str(
                sum(int(row["literal_units"]) for row in result["unconfirmed_rows"])
            ),
            "formula_units": str(
                sum(int(row["formula_units"]) for row in result["rows"])
            ),
            "additional_note_rows": sum(
                any("另有" in note["raw"] for note in row["notes"])
                for row in result["rows"]
            ),
            "row_count": len(result["rows"]),
            "product_count": len({product_key(row) for row in result["rows"]}),
            "warehouse_1_units": str(
                sum(int(row["stock_units"]) for row in result["rows"])
            ),
            "location_unconfirmed_units": str(
                sum(int(row["stock_units"]) for row in result["unconfirmed_rows"])
            ),
            "outside_units": str(
                sum(int(row["stock_units"]) for row in result["outside_rows"])
            ),
            "color_count": len({color_key(row) for row in result["rows"]}),
            "unknown_cells": sum(row["unknown_cells"] for row in rows),
            "warehouse_pending": len(result["unconfirmed_rows"]),
            "incomplete_total_rows": sum(not row["quantity_complete"] for row in rows),
        }
    )
    return result


def calculate(
    header: dict[str, Any],
    previous: dict[str, Any],
    command: PreviewCommand,
    catalog: CatalogVersionSummary | None = None,
) -> tuple[dict[str, Any], dict[str, Any]]:
    if header["source_identity"] != command.source_identity:
        fail(
            "inventory_review_source_mismatch",
            "来源已不同，请返回所选固定核对单。",
            409,
        )
    if header["revision"] != command.expected_revision:
        fail(
            "inventory_review_revision_conflict",
            "核对版本已变化，请读取最新结果并比较输入后重新预览。",
            409,
        )
    overrides = deepcopy(previous)
    source = header["source_snapshot_json"]
    keys = {row["source_key"] for row in source["rows"] + source["unconfirmed_rows"]}
    quantity_keys = set()
    differences = []
    before = effective(source, previous)
    for change in command.changes:
        key, field = change_target(change)
        if key is not None and key not in keys:
            fail("inventory_review_row_unknown", "来源行不存在，整批未保存。")
        target = (
            overrides
            if key is None
            else overrides.setdefault("rows", {}).setdefault(key, {})
        )
        if isinstance(change, ProductChange):
            links = overrides.setdefault("products", {}).setdefault(key, {})
            if change.value is None:
                if change.size not in links:
                    fail(
                        "inventory_product_not_saved",
                        "此尺码尚未保存商品对应，无需解除。",
                    )
                links.pop(change.size)
            else:
                match = product_match(before, catalog, change.source_key, change.size)
                reference = change.value
                if (
                    match["catalog_version_id"] != reference.catalog_version_id
                    or match["catalog_publication_revision"]
                    != reference.catalog_publication_revision
                ):
                    fail(
                        "inventory_product_catalog_stale",
                        "商品目录已变化，请重新查看商品对应后预览。",
                        409,
                    )
                if (
                    match["status"] != "matched"
                    or match["candidates"][0]["sku_id"] != reference.sku_id
                ):
                    fail(
                        "inventory_product_invalid",
                        "所选商品已停用、规格不符或对应不唯一，请重新核对。",
                        409,
                    )
                if (
                    change.size
                    not in next(
                        row
                        for row in before["rows"]
                        + before["unconfirmed_rows"]
                        + before["outside_rows"]
                        if row["source_key"] == key
                    )["quantities"]
                ):
                    fail(
                        "inventory_product_cell_missing",
                        "来源没有此尺码格，不能保存对应。",
                    )
                candidate = match["candidates"][0]
                links[change.size] = (
                    candidate
                    | reference.model_dump()
                    | {"cell": match["source"]["cell"]}
                )
        elif isinstance(change, RestoreChange):
            target.pop(field, None)
        else:
            value = (
                change.value.isoformat()
                if isinstance(change.value, date)
                else change.value
            )
            target[field] = value
        overrides.setdefault("notes", {})[key or "review"] = command.reason
        if (
            key is not None
            and field != "location"
            and not isinstance(change, ProductChange)
        ):
            quantity_keys.add(key)
        differences.append(change.model_dump(mode="json"))
    after = effective(source, overrides)
    for row in after["rows"] + after["unconfirmed_rows"] + after["outside_rows"]:
        if row["source_key"] not in quantity_keys:
            continue
        known = int(row["literal_units"])
        total = row["reviewed_total"]
        if total is not None and (
            known > int(total) or (row["unknown_cells"] == 0 and known != int(total))
        ):
            fail(
                "inventory_review_quantity_conflict",
                row["source_key"]
                + "：已知尺码量超过合计或完整尺码和不等于合计，请一并核对；整批未保存。",
            )
    if previous == overrides:
        fail("inventory_review_no_changes", "没有需要保存的变更。")
    preview = {
        "before": before["summary"],
        "after": after["summary"],
        "differences": differences,
        "stocktaken_on": after["stocktaken_on"],
        "cutoff_note": after["cutoff_note"],
    }
    preview["preview_hash"] = digest(
        [
            header["source_identity"],
            header["revision"],
            header["policy_version"],
            command.model_dump(mode="json", exclude={"preview_hash"}),
            overrides,
            preview,
        ]
    )
    return overrides, preview


def header_for(
    connection: Connection,
    context: CurrentSiteContext,
    review_id: UUID,
    lock: bool = False,
) -> dict[str, Any]:
    statement = sa.select(reviews).where(
        reviews.c.site_id == context.site_id, reviews.c.review_id == review_id.bytes
    )
    if lock:
        statement = statement.with_for_update()
    row = connection.execute(statement).mappings().first()
    if row is None:
        fail("inventory_review_not_found", "当前站点没有此核对单。", 404)
    return dict(row)


def current_overrides(
    connection: Connection, header: dict[str, Any], *, lock: bool = False
) -> dict[str, Any]:
    if header["revision"] == 0:
        return {}
    statement = sa.select(revisions.c.effective_overrides_json).where(
        revisions.c.site_id == header["site_id"],
        revisions.c.review_id == header["review_id"],
        revisions.c.revision == header["revision"],
    )
    if lock:
        statement = statement.with_for_update(read=True)
    value = connection.execute(statement).scalar_one()
    return cast(dict[str, Any], value)


def capability(context: CurrentSiteContext) -> bool:
    return not context.principal_roles.isdisjoint({"admin", "data_manager"})


def detail(
    engine: Engine, context: CurrentSiteContext, review_id: UUID
) -> dict[str, Any]:
    with engine.begin() as connection:
        header = header_for(connection, context, review_id)
        overrides = current_overrides(connection, header)
    return {
        "review_id": str(review_id),
        "source_identity": header["source_identity"],
        "revision": header["revision"],
        "can_manage": capability(context),
        "source": header["source_snapshot_json"],
        "effective": effective(header["source_snapshot_json"], overrides),
        "overrides": overrides,
    }


def current(
    engine: Engine, settings: Settings, context: CurrentSiteContext
) -> dict[str, Any]:
    snapshot = inventory_snapshot(settings, context)
    identity = source_identity(snapshot)
    with engine.connect() as connection:
        review_id = connection.execute(
            sa.select(reviews.c.review_id).where(
                reviews.c.site_id == context.site_id,
                reviews.c.source_identity == identity,
            )
        ).scalar_one_or_none()
    return {
        "source_identity": identity,
        "source": snapshot,
        "review_id": str(UUID(bytes=review_id)) if review_id else None,
        "can_manage": capability(context),
    }


def start(
    engine: Engine, settings: Settings, context: CurrentSiteContext, body: StartReview
) -> tuple[dict[str, Any], bool]:
    snapshot = inventory_snapshot(settings, context)
    if any(
        snapshot[key] != getattr(body, key)
        for key in ("source_digest", "source_manifest_digest")
    ):
        fail(
            "inventory_review_source_mismatch",
            "来源摘要已变化，请重新读取并开始核对。",
            409,
        )
    identity = source_identity(snapshot)
    now = datetime.now(UTC).replace(tzinfo=None)
    review_id = uuid4()
    try:
        with engine.begin() as connection:
            connection.execute(
                reviews.insert().values(
                    review_id=review_id.bytes,
                    site_id=context.site_id,
                    source_identity=identity,
                    source_digest=snapshot["source_digest"],
                    source_manifest_digest=snapshot["source_manifest_digest"],
                    source_format=snapshot["source_format"],
                    source_name=snapshot["filename"],
                    parser_version=PARSER,
                    policy_version=POLICY,
                    source_snapshot_json=snapshot,
                    revision=0,
                    created_by=context.principal_user_id,
                    updated_by=context.principal_user_id,
                    created_at=now,
                    updated_at=now,
                )
            )
        created = True
    except IntegrityError:
        with engine.connect() as connection:
            existing = connection.execute(
                sa.select(reviews.c.review_id).where(
                    reviews.c.site_id == context.site_id,
                    reviews.c.source_identity == identity,
                )
            ).scalar_one_or_none()
        if existing is None:
            raise
        review_id = UUID(bytes=existing)
        created = False
    return detail(engine, context, review_id), created


def start_from_manual_snapshot(
    engine: Engine, context: CurrentSiteContext, snapshot: dict[str, Any]
) -> dict[str, Any]:
    """Explicit new manual-source entry; configured-source start stays unchanged."""
    if not capability(context) or snapshot.get("source_kind") != "MANUAL":
        fail("manual_inventory_forbidden", "当前来源或账号不能创建人工库存核对。", 403)
    identity = source_identity(snapshot)
    stamp = datetime.now(UTC).replace(tzinfo=None)
    review_id = uuid4()
    try:
        with engine.begin() as connection:
            connection.execute(
                reviews.insert().values(
                    review_id=review_id.bytes,
                    site_id=context.site_id,
                    source_identity=identity,
                    source_digest=snapshot["source_digest"],
                    source_manifest_digest=snapshot["source_manifest_digest"],
                    source_format=snapshot["source_format"],
                    source_name=snapshot["filename"],
                    parser_version=PARSER,
                    policy_version=POLICY,
                    source_snapshot_json=snapshot,
                    revision=0,
                    created_by=context.principal_user_id,
                    updated_by=context.principal_user_id,
                    created_at=stamp,
                    updated_at=stamp,
                )
            )
    except IntegrityError:
        with engine.connect() as connection:
            value = connection.execute(
                sa.select(reviews.c.review_id).where(
                    reviews.c.site_id == context.site_id,
                    reviews.c.source_identity == identity,
                )
            ).scalar_one()
        review_id = UUID(bytes=value)
    return detail(engine, context, review_id)


def command_catalog(
    connection: Connection,
    engine: Engine,
    context: CurrentSiteContext,
    body: PreviewCommand,
) -> CatalogVersionSummary | None:
    if not any(
        isinstance(change, ProductChange) and change.value is not None
        for change in body.changes
    ):
        return None
    # Catalog publication uses this same pointer as its first write lock. Keep
    # the approved directory fixed through matching and the review commit.
    connection.execute(
        sa.text(
            "SELECT current_catalog_version_id FROM product_catalog_publications "
            "WHERE site_id = :site_id LOCK IN SHARE MODE"
        ),
        {"site_id": context.site_id},
    ).all()
    return MySqlCatalogQueries(engine).current_catalog(
        site_id=context.site_id, connection=connection
    )


def preview(
    engine: Engine, context: CurrentSiteContext, review_id: UUID, body: PreviewCommand
) -> dict[str, Any]:
    with engine.begin() as connection:
        catalog = command_catalog(connection, engine, context, body)
        header = header_for(connection, context, review_id)
        return calculate(header, current_overrides(connection, header), body, catalog)[
            1
        ]


def request_hash(review_id: UUID, command: SaveCommand) -> str:
    return digest([str(review_id), command.model_dump(mode="json")])


def replay(row: Any, review_id: UUID, hashed: str) -> dict[str, Any]:
    if row["review_id"] != review_id.bytes or row["request_hash"] != hashed:
        fail("idempotency_key_reused", "此操作ID已用于不同内容，不能再次使用。", 409)
    return dict(row["result_json"]) | {"replayed": True}


def receipt_row(
    connection: Connection,
    context: CurrentSiteContext,
    operation_id: UUID,
    *,
    lock: bool = False,
) -> Any:
    statement = sa.select(revisions).where(
        revisions.c.site_id == context.site_id,
        revisions.c.operation_id == operation_id.bytes,
    )
    if lock:
        statement = statement.with_for_update(read=True)
    return connection.execute(statement).mappings().first()


def save(
    engine: Engine,
    context: CurrentSiteContext,
    review_id: UUID,
    command: SaveCommand,
    operation_id: UUID,
) -> dict[str, Any]:
    hashed = request_hash(review_id, command)
    # Check a prior receipt in a separate read transaction, before catalog locks.
    with engine.connect() as connection:
        existing = receipt_row(connection, context, operation_id)
        if existing:
            header_for(connection, context, review_id)
            return replay(existing, review_id, hashed)
    try:
        with engine.begin() as connection:
            catalog = command_catalog(connection, engine, context, command)
            header = header_for(connection, context, review_id, lock=True)
            existing = receipt_row(connection, context, operation_id, lock=True)
            if existing:
                return replay(existing, review_id, hashed)
            overrides, calculated = calculate(
                header,
                current_overrides(connection, header, lock=True),
                command,
                catalog,
            )
            if calculated["preview_hash"] != command.preview_hash:
                fail(
                    "inventory_review_preview_stale",
                    "预览已不一致，请重新核对后预览。",
                    409,
                )
            revision = header["revision"] + 1
            result = {
                "operation_id": str(operation_id),
                "review_id": str(review_id),
                "saved_revision": revision,
                "before": calculated["before"],
                "after": calculated["after"],
                "replayed": False,
            }
            now = datetime.now(UTC).replace(tzinfo=None)
            connection.execute(
                revisions.insert().values(
                    site_id=context.site_id,
                    review_id=review_id.bytes,
                    revision=revision,
                    operation_id=operation_id.bytes,
                    request_hash=hashed,
                    command_json=command.model_dump(mode="json"),
                    effective_overrides_json=overrides,
                    result_json=result,
                    actor_id=context.principal_user_id,
                    at=now,
                    reason=command.reason,
                )
            )
            connection.execute(
                reviews.update()
                .where(
                    reviews.c.site_id == context.site_id,
                    reviews.c.review_id == review_id.bytes,
                )
                .values(
                    revision=revision,
                    updated_at=now,
                    updated_by=context.principal_user_id,
                )
            )
        return result
    except IntegrityError:
        with engine.connect() as connection:
            existing = receipt_row(connection, context, operation_id)
            if existing:
                return replay(existing, review_id, hashed)
        raise


def operation(
    engine: Engine, context: CurrentSiteContext, review_id: UUID, operation_id: UUID
) -> dict[str, Any]:
    with engine.begin() as connection:
        header_for(connection, context, review_id)
        row = receipt_row(connection, context, operation_id)
        if not row or row["review_id"] != review_id.bytes:
            fail(
                "inventory_review_operation_not_found",
                "尚未查到原操作；可保留同一操作ID与内容重试。",
                404,
            )
        return dict(row["result_json"])


def history(
    engine: Engine,
    context: CurrentSiteContext,
    review_id: UUID,
    before: int,
    limit: int,
) -> dict[str, Any]:
    with engine.begin() as connection:
        header_for(connection, context, review_id)
        rows = (
            connection.execute(
                sa.select(revisions)
                .where(
                    revisions.c.site_id == context.site_id,
                    revisions.c.review_id == review_id.bytes,
                    revisions.c.revision < before,
                )
                .order_by(revisions.c.revision.desc())
                .limit(limit + 1)
            )
            .mappings()
            .all()
        )
        actor_names: dict[int, str] = {}
        if rows:
            actors = connection.execute(
                sa.text(
                    "SELECT id, username_normalized AS username, display_name FROM users WHERE id IN :ids"
                ).bindparams(sa.bindparam("ids", expanding=True)),
                {"ids": sorted({row["actor_id"] for row in rows})},
            ).mappings()
            actor_names = {
                row["id"]: f"{row['username']} · {row['display_name']}"
                for row in actors
            }
    return {
        "items": [
            {
                "revision": row["revision"],
                "operation_id": str(UUID(bytes=row["operation_id"])),
                "actor_id": str(row["actor_id"]),
                "actor_name": actor_names.get(row["actor_id"], ""),
                "actor_name_basis": "current_account",
                "at": row["at"].isoformat() + "Z",
                "reason": row["reason"],
                "changes": row["command_json"]["changes"],
                "result": row["result_json"],
            }
            for row in rows[:limit]
        ],
        "next_before_revision": rows[limit - 1]["revision"]
        if len(rows) > limit
        else None,
    }


def storage_call[T](function: Callable[..., T], *args: Any) -> T:
    try:
        return function(*args)
    except SQLAlchemyError as error:
        raise ApiError(
            503,
            "inventory_review_storage_unavailable",
            "核对存储尚未启用或暂不可用；未确认保存结果，请查询原操作。",
        ) from error
