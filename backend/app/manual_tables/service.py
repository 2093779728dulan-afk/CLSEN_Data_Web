# ruff: noqa: RUF001 -- Chinese user-facing punctuation.
"""Scoped, revisioned preparation; no direct writes to master or inventory facts."""

import hashlib
import json
from datetime import UTC, date, datetime
from io import BytesIO
from pathlib import Path
from typing import Any, cast
from uuid import UUID, uuid4

import sqlalchemy as sa
from sqlalchemy.engine import Connection, Engine
from sqlalchemy.exc import IntegrityError

from app.api.errors import ApiError
from app.catalog.normalization import catalog_identity_key_v1, seller_sku_match_v1
from app.catalog.queries import MySqlCatalogQueries
from app.catalog.source_formatting import FORMAT_REASON, format_identity_field
from app.config import Settings
from app.imports.storage import LocalContentStore
from app.manual_tables.exports import semantic
from app.manual_tables.extraction import extract, read_book
from app.manual_tables.models import batches, operations, profiles
from app.manual_tables.schemas import Command, Kind, Options, issue
from app.site_context import CurrentSiteContext


def digest(value: Any) -> str:
    return hashlib.sha256(
        json.dumps(
            value,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            default=str,
        ).encode()
    ).hexdigest()


def now() -> datetime:
    return datetime.now(UTC).replace(tzinfo=None)


class ManualTables:
    def __init__(self, engine: Engine, settings: Settings, context: CurrentSiteContext):
        self.engine, self.settings, self.context = engine, settings, context

    def require(self) -> None:
        if not self.settings.manual_tables_enabled:
            raise ApiError(
                403,
                "manual_tables_disabled",
                "当前环境未启用人工表格整理，原有导入流程可继续使用。",
            )
        if self.context.principal_roles.isdisjoint({"admin", "data_manager"}):
            raise ApiError(
                403,
                "manual_tables_forbidden",
                "人工资料仅限本站管理员或数据管理员处理。",
            )

    def store(self) -> LocalContentStore:
        if not self.settings.manual_tables_root:
            raise ApiError(
                503, "manual_storage_missing", "人工资料存储尚未配置，请联系管理员。"
            )
        return LocalContentStore(Path(self.settings.manual_tables_root), 2_000_000)

    def query(self) -> Any:
        q = sa.select(batches).where(batches.c.site_id == self.context.site_id)
        if "admin" not in self.context.principal_roles:
            q = q.where(batches.c.owner_id == self.context.principal_user_id)
        return q

    def load(
        self, connection: Connection, batch_id: str, *, lock: bool = False
    ) -> dict[str, Any]:
        self.require()
        q = self.query().where(batches.c.id == batch_id)
        row = connection.execute(q.with_for_update() if lock else q).mappings().first()
        if row is None:
            raise ApiError(404, "manual_batch_missing", "未找到可访问的人工资料批次。")
        return dict(row)

    def present(self, row: dict[str, Any]) -> dict[str, Any]:
        return {
            "id": row["id"],
            "kind": row["kind"],
            "filename": row["filename"],
            "source_digest": row["source_digest"],
            "revision": row["revision"],
            "options": row["options_json"],
            "result": row["result_json"],
            "target": row["target_json"],
            "owner_id": str(row["owner_id"]),
            "created_at": str(row["created_at"]),
            "updated_at": str(row["updated_at"]),
        }

    def get(self, batch_id: str) -> dict[str, Any]:
        with self.engine.connect() as connection:
            return self.present(self.load(connection, batch_id))

    def listing(
        self, page: int = 1, kind: Kind | None = None, target_url: str | None = None
    ) -> dict[str, Any]:
        self.require()
        query = self.query()
        if kind is not None:
            query = query.where(batches.c.kind == kind)
        if target_url is not None:
            query = query.where(batches.c.target_json["url"].as_string() == target_url)
        with self.engine.connect() as connection:
            identity_query = query.with_only_columns(batches.c.id).order_by(None)
            total = connection.scalar(
                sa.select(sa.func.count()).select_from(identity_query.subquery())
            )
            page_ids = list(
                connection.scalars(
                    identity_query.order_by(
                        batches.c.updated_at.desc(), batches.c.id.desc()
                    )
                    .limit(30)
                    .offset((page - 1) * 30)
                )
            )
            records_by_id = (
                {
                    row["id"]: row
                    for row in connection.execute(
                        sa.select(batches).where(batches.c.id.in_(page_ids))
                    ).mappings()
                }
                if page_ids
                else {}
            )
            records = [records_by_id[batch_id] for batch_id in page_ids]
            return {
                "items": [
                    {
                        k: v
                        for k, v in self.present(dict(row)).items()
                        if k not in {"result", "options"}
                    }
                    | {
                        "state": row["result_json"]["state"],
                        "total_units": row["result_json"]["total_units"],
                    }
                    for row in records
                ],
                "total": total,
                "page": page,
            }

    def source(self, row: dict[str, Any]) -> bytes:
        return self.store().read_bytes(
            row["storage_key"], row["source_digest"], row["size_bytes"]
        )

    def catalog(self, connection: Connection | None = None) -> list[dict[str, Any]]:
        current = MySqlCatalogQueries(self.engine).current_catalog(
            site_id=self.context.site_id, connection=connection
        )
        if current is None:
            return []
        styles = {s.style_id: s for s in current.styles}
        return [
            {
                "sku_id": str(s.sku_id),
                "style_id": str(s.style_id),
                "style": styles[s.style_id].style_code,
                "color": s.standard_color,
                "size": s.standard_size,
                "code": s.internal_display_sku,
                "active": s.status == "enabled"
                and styles[s.style_id].status == "enabled",
                "catalog_version": (
                    f"{current.catalog_version_id}:"
                    f"{current.catalog_publication_revision}"
                ),
            }
            for s in current.skus
            if s.style_id in styles
        ]

    def analyze(
        self,
        raw: bytes,
        kind: Kind,
        options: Options,
        connection: Connection | None = None,
    ) -> dict[str, Any]:
        result = extract(raw, kind, options)
        catalog = self.catalog(connection)
        by_id = {s["sku_id"]: s for s in catalog}

        def norm(value: Any) -> str:
            return catalog_identity_key_v1(str(value)).text

        for row in result["rows"]:
            if row["excluded"]:
                continue
            original = row["source_values"]
            chosen = row.get("sku_id")
            selected = by_id.get(str(chosen)) if chosen else None
            # An explicit, reasoned product choice may resolve legacy ambiguity,
            # but it must still agree with the entered identity, never an alias.
            if chosen and (
                selected is None
                or not selected["active"]
                or any(
                    norm(original[k] or "?") != norm(selected[k])
                    for k in ("style", "color", "size")
                )
            ):
                raise ApiError(
                    422,
                    "manual_sku_conflict",
                    "所选商品与确认的款号、颜色、尺码不一致，请重新选择。",
                )
            known = [selected] if selected else catalog
            style, problem = format_identity_field(
                original["style"], "style", (s["style"] for s in known)
            )
            format_problems = [problem] if problem else []
            scoped = [
                s
                for s in known
                if not format_problems and norm(s["style"]) == norm(style or "?")
            ]
            row["style"] = style
            for k in ("color", "size"):
                row[k], problem = format_identity_field(
                    original[k], k, (s[k] for s in scoped)
                )
                if problem:
                    format_problems.append(problem)
            row["format_adjustments"] = [
                {
                    "field": k,
                    "before": original[k],
                    "after": row[k],
                    "reason": FORMAT_REASON,
                }
                for k in ("style", "color", "size")
                if original[k] != row[k]
            ]
            for problem in format_problems:
                if not any(
                    i["code"] == "identity_format" and i["message"] == problem
                    for i in row["issues"]
                ):
                    entry = issue("identity_format", problem, **row["source_ref"])
                    row["issues"].append(entry)
                    result["issues"].append(entry)
            candidates = [
                s
                for s in catalog
                if not format_problems
                and (norm(s["style"]), norm(s["color"]), norm(s["size"]))
                == (
                    norm(row["style"] or "?"),
                    norm(row["color"] or "?"),
                    norm(row["size"] or "?"),
                )
            ]
            if chosen:
                item = by_id.get(str(chosen))
                if item is None or not item["active"] or item not in candidates:
                    raise ApiError(
                        422,
                        "manual_sku_conflict",
                        "所选商品不属于当前有效目录，或与确认的款号、颜色、尺码不一致，请重新选择。",
                    )
                candidates = [item]
            matched = len(candidates) == 1 and candidates[0]["active"]
            row["match"] = {
                "status": "matched"
                if matched
                else "not_found"
                if not candidates
                else "ambiguous",
                "sku_id": candidates[0]["sku_id"] if matched else None,
                "catalog_version": candidates[0]["catalog_version"]
                if matched
                else None,
            }
            if not matched and row["units"] != "0":
                result["issues"].append(
                    issue(
                        "sku_unresolved",
                        "商品尚未唯一对应当前主档，请从商品列表选择，或先在商品建档处理。",
                        **row["source_ref"],
                    )
                )
            if row["code"] and matched:
                other = [
                    s
                    for s in catalog
                    if s["code"]
                    and seller_sku_match_v1(s["code"]).text
                    == seller_sku_match_v1(row["code"]).text
                ]
                if other and other[0]["sku_id"] != row["match"]["sku_id"]:
                    result["issues"].append(
                        issue(
                            "code_identity_conflict",
                            "原编码对应的商品与款色尺码不同，请核实原表；尚未覆盖主档编码。",
                            **row["source_ref"],
                        )
                    )
        result["options"] = options.model_dump()
        result["catalog_version"] = catalog[0]["catalog_version"] if catalog else None
        if result["state"] != "NEEDS_MAPPING":
            result["state"] = (
                "NEEDS_REVIEW"
                if any(i["blocking"] for i in result["issues"])
                else "READY"
            )
        result["capabilities"] = {
            "can_export": True,
            "can_create_inventory_review": self.settings.manual_tables_handoff_enabled
            and self.settings.manual_tables_inventory_handoff_enabled
            and kind == "inventory"
            and bool(result["rows"]),
            "can_create_order_draft": self.settings.manual_tables_handoff_enabled
            and kind == "orders"
            and result["state"] == "READY",
            "can_create_shipment_draft": self.settings.manual_tables_handoff_enabled
            and kind == "packing"
            and result["state"] == "READY",
        }
        return result

    def _token(self, token: str) -> str:
        try:
            value = UUID(token)
        except ValueError as error:
            raise ApiError(
                422, "manual_operation_invalid", "操作编号无效，请保留输入后刷新。"
            ) from error
        if value.version != 4:
            raise ApiError(422, "manual_operation_invalid", "操作编号必须使用UUID v4。")
        return str(value)

    def replay(
        self, con: Connection, token: str, request_hash: str
    ) -> dict[str, Any] | None:
        previous = (
            con.execute(
                sa.select(operations)
                .where(
                    operations.c.site_id == self.context.site_id,
                    operations.c.token == self._token(token),
                )
                # Receipts are immutable; use the read lock supported by the
                # runtime's SELECT/INSERT-only permission on this table.
                .with_for_update(read=True)
            )
            .mappings()
            .first()
        )
        if previous:
            if (
                previous["request_hash"] != request_hash
                or previous["actor_id"] != self.context.principal_user_id
            ):
                raise ApiError(
                    409,
                    "manual_token_conflict",
                    "同一操作编号已用于不同内容，请先核对原操作结果。",
                )
            return cast(dict[str, Any] | None, previous["result_json"])
        return None

    def record(
        self,
        con: Connection,
        token: str,
        batch_id: str | None,
        action: str,
        request_hash: str,
        result: dict[str, Any],
        reason: str = "",
    ) -> None:
        con.execute(
            operations.insert().values(
                site_id=self.context.site_id,
                token=self._token(token),
                batch_id=batch_id,
                actor_id=self.context.principal_user_id,
                action=action,
                request_hash=request_hash,
                revision=result.get("revision"),
                result_json=result,
                reason=reason,
                at=now(),
            )
        )

    def create(
        self, raw: bytes, kind: Kind, filename: str, token: str
    ) -> dict[str, Any]:
        self.require()
        from app.production.source_registry import validate_upload

        filename = validate_upload(filename, raw)
        initial_options = Options()
        result = self.analyze(raw, kind, initial_options)
        # Prefill only unanimous, explicit source values, never filename dates.
        if result["rows"]:
            for field in ("warehouse", "date", "planned_date", "basis", "number"):
                values = {row[field] for row in result["rows"] if not row["excluded"]}
                if len(values) == 1 and (value := next(iter(values))):
                    if field in {"date", "planned_date"}:
                        try:
                            if date.fromisoformat(value).isoformat() != value:
                                continue
                        except ValueError:
                            continue
                    initial_options.context[field] = value
            if initial_options.context:
                result = self.analyze(raw, kind, initial_options)
        content_hash = hashlib.sha256(raw).hexdigest()
        request_hash = digest(["upload", content_hash, kind, filename])
        # Only a scoped lookup plus a complete semantic comparison can reuse
        # an exported batch reference. File-provided IDs alone grant nothing.
        book = read_book(raw)
        try:
            notes = (
                {str(r[0].value): r[1].value for r in book["说明"] if len(r) > 1}
                if "说明" in book.sheetnames
                else {}
            )
            review_origin = ""
            if "导出说明" in book.sheetnames:
                review_notes = {
                    str(r[0].value): r[1].value for r in book["导出说明"] if len(r) > 1
                }
                review_origin = str(review_notes.get("来源人工整理批次") or "")
        finally:
            book.close()
        if review_origin:
            self.get(review_origin)
            raise ApiError(
                409,
                "manual_review_export_return",
                "这是已有库存核对单的导出文件，请到原核对单核对或更正；不能作为新资料再建一单。",
            )
        if notes.get("格式版本") == "manual-tables-v1" and notes.get("批次"):
            origin = self.get(str(notes["批次"]))
            if str(origin["revision"]) != str(notes.get("修订")):
                raise ApiError(
                    409,
                    "manual_return_revision",
                    "导出文件已是旧修订，请回原批次核对最新结果。",
                )
            if origin["kind"] != kind or semantic(origin["result"]) != semantic(result):
                raise ApiError(
                    409,
                    "manual_return_changed",
                    "该文件来自已有批次且内容有修改或仅包含筛选范围。请打开原批次/原目标更正，不能当新业务导入。",
                )
            with self.engine.begin() as con:
                self.load(con, origin["id"])
                replay = self.replay(con, token, request_hash)
                if replay:
                    return replay
                self.record(
                    con,
                    token,
                    origin["id"],
                    "REIMPORT",
                    request_hash,
                    origin,
                    "导出明细回导核对；沿用原批次，不新增业务",
                )
            return origin
        store = self.store()
        staged = store.write_stream(uuid4(), BytesIO(raw))
        try:
            stored = store.promote(staged)
        finally:
            store.discard_staged(staged)
        try:
            with self.engine.begin() as con:
                prior = self.replay(con, token, request_hash)
                if prior:
                    self.load(con, prior["id"])
                    return prior
                old = (
                    con.execute(
                        sa.select(batches)
                        .where(
                            batches.c.site_id == self.context.site_id,
                            batches.c.owner_id == self.context.principal_user_id,
                            batches.c.kind == kind,
                            batches.c.source_digest == content_hash,
                        )
                        .with_for_update()
                    )
                    .mappings()
                    .first()
                )
                if old:
                    value = self.present(dict(old))
                else:
                    row = {
                        "id": str(uuid4()),
                        "site_id": self.context.site_id,
                        "owner_id": self.context.principal_user_id,
                        "kind": kind,
                        "filename": filename,
                        "source_digest": content_hash,
                        "storage_key": stored.storage_key,
                        "size_bytes": len(raw),
                        "revision": 0,
                        "options_json": initial_options.model_dump(),
                        "result_json": result,
                        "target_json": None,
                        "created_at": now(),
                        "updated_at": now(),
                    }
                    con.execute(batches.insert().values(**row))
                    value = self.present(row)
                self.record(con, token, value["id"], "UPLOAD", request_hash, value)
                return value
        except IntegrityError:
            with self.engine.connect() as con:
                replay = self.replay(con, token, request_hash)
                if replay:
                    self.load(con, replay["id"])
                    return replay
                old = (
                    con.execute(
                        self.query().where(
                            batches.c.owner_id == self.context.principal_user_id,
                            batches.c.source_digest == content_hash,
                            batches.c.kind == kind,
                        )
                    )
                    .mappings()
                    .first()
                )
                if old:
                    return self.present(dict(old))
            raise

    def preview(self, batch_id: str, command: Command) -> dict[str, Any]:
        with self.engine.connect() as con:
            row = self.load(con, batch_id)
        if row["revision"] != command.expected_revision:
            raise ApiError(
                409,
                "manual_revision_conflict",
                "资料已有新修订，请刷新后核对，当前输入尚未保存。",
            )
        result = self.analyze(
            self.source(row), cast(Kind, row["kind"]), command.options
        )
        if command.options.profile_id:
            with self.engine.connect() as con:
                profile = self.profile(
                    con, command.options.profile_id, command.options.profile_version
                )
            if (
                profile["signature"] != result.get("layout_signature")
                or profile["kind"] != row["kind"]
            ):
                raise ApiError(
                    409,
                    "manual_profile_stale",
                    "字段方案与当前表头或资料类型不同，请重新选择字段。",
                )
        return {
            "result": result,
            "preview_hash": digest(
                [batch_id, row["revision"], command.options.model_dump(), result]
            ),
            "revision": row["revision"],
        }

    def save(self, batch_id: str, command: Command) -> dict[str, Any]:
        request_hash = digest(["save", batch_id, command.model_dump()])
        # Replay before checking the old revision. A completed operation is stable.
        with self.engine.begin() as con:
            self.load(con, batch_id)
            replay = self.replay(con, command.operation_token, request_hash)
            if replay:
                return replay
        preview = self.preview(batch_id, command)
        if command.preview_hash != preview["preview_hash"]:
            raise ApiError(
                409, "manual_preview_stale", "预览或商品目录已变化，请重新预览后保存。"
            )
        with self.engine.begin() as con:
            row = self.load(con, batch_id, lock=True)
            replay = self.replay(con, command.operation_token, request_hash)
            if replay:
                return replay
            if row["revision"] != command.expected_revision or row["target_json"]:
                raise ApiError(
                    409,
                    "manual_revision_conflict",
                    "资料已有更新或已移交，请到原目标核对/更正。",
                )
            con.execute(
                sa.text(
                    "SELECT current_catalog_version_id "
                    "FROM product_catalog_publications "
                    "WHERE site_id=:site LOCK IN SHARE MODE"
                ),
                {"site": self.context.site_id},
            ).all()
            current_result = self.analyze(
                self.source(row), cast(Kind, row["kind"]), command.options, con
            )
            if current_result != preview["result"]:
                raise ApiError(
                    409, "manual_preview_stale", "保存期间商品目录已变化，请重新预览。"
                )
            row.update(
                revision=row["revision"] + 1,
                options_json=command.options.model_dump(),
                result_json=preview["result"],
                updated_at=now(),
            )
            con.execute(
                batches.update()
                .where(batches.c.id == batch_id)
                .values(
                    revision=row["revision"],
                    options_json=row["options_json"],
                    result_json=row["result_json"],
                    updated_at=row["updated_at"],
                )
            )
            value = self.present(row)
            self.record(
                con,
                command.operation_token,
                batch_id,
                "SAVE",
                request_hash,
                value,
                command.reason,
            )
            return value

    def history(self, batch_id: str) -> dict[str, Any]:
        with self.engine.connect() as con:
            self.load(con, batch_id)
            rows = (
                con.execute(
                    sa.select(
                        operations.c.token,
                        operations.c.actor_id,
                        operations.c.action,
                        operations.c.reason,
                        operations.c.revision,
                        operations.c.at,
                        operations.c.result_json,
                    ).where(
                        operations.c.site_id == self.context.site_id,
                        operations.c.batch_id == batch_id,
                    )
                )
                .mappings()
                .all()
            )
            # Sorting the complete JSON receipts can exhaust MySQL's sort buffer
            # even for a single workbook. These rows are already materialized.
            rows = sorted(rows, key=lambda row: (row["at"], row["token"]))
            names = {}
            if rows:
                actors = con.execute(
                    sa.text(
                        "SELECT id, username_normalized, display_name "
                        "FROM users WHERE id IN :ids"
                    ).bindparams(sa.bindparam("ids", expanding=True)),
                    {"ids": sorted({r["actor_id"] for r in rows})},
                ).mappings()
                names = {
                    r["id"]: f"{r['username_normalized']} · {r['display_name']}"
                    for r in actors
                }
            items = []
            previous: dict[str, Any] = {}
            for row in rows:
                value = dict(row)
                saved = value.pop("result_json")
                changes = []
                current = {
                    r["source_line_key"]: r
                    for r in saved.get("result", {}).get("rows", [])
                }
                if row["action"] == "SAVE":
                    for key, item in current.items():
                        old = previous.get(key, {})
                        if any(
                            item.get(k) != old.get(k)
                            for k in (
                                "units",
                                "style",
                                "color",
                                "size",
                                "excluded",
                                "boxes",
                                "decision",
                            )
                        ):
                            changes.append(
                                f"{key}：{old.get('units', '未知')}→"
                                f"{item['units'] or '未知'}件；"
                                f"{item['style']} / {item['color']} / {item['size']}；"
                                f"{'排除' if item['excluded'] else '保留'}；"
                                f"{item.get('decision', {}).get('reason', '')}"
                            )
                    changes.append("字段与业务口径已保存，可查询本次操作查看完整修订。")
                if current:
                    previous = current
                items.append(
                    {
                        **value,
                        "actor_id": str(row["actor_id"]),
                        "actor_name": names.get(row["actor_id"], ""),
                        "at": str(row["at"]),
                        "changes": changes,
                    }
                )
            return {"items": items}

    def operation(self, batch_id: str, token: str) -> dict[str, Any]:
        with self.engine.connect() as con:
            self.load(con, batch_id)
            row = con.execute(
                sa.select(operations.c.result_json).where(
                    operations.c.site_id == self.context.site_id,
                    operations.c.batch_id == batch_id,
                    operations.c.token == self._token(token),
                )
            ).first()
            if row is None:
                raise ApiError(
                    404,
                    "manual_operation_missing",
                    "暂未查到这次操作，请保留原操作编号继续核实。",
                )
            return cast(dict[str, Any], row[0])

    def profile(
        self, con: Connection, profile_id: str, version: int | None
    ) -> dict[str, Any]:
        q = sa.select(profiles).where(
            profiles.c.id == profile_id, profiles.c.site_id == self.context.site_id
        )
        if "admin" not in self.context.principal_roles:
            q = q.where(
                sa.or_(
                    profiles.c.owner_id == self.context.principal_user_id,
                    profiles.c.shared.is_(True),
                )
            )
        if version:
            q = q.where(profiles.c.version == version)
        row = con.execute(q.order_by(profiles.c.version.desc())).mappings().first()
        if row is None:
            raise ApiError(404, "manual_profile_missing", "没有可使用的字段对应方案。")
        return dict(row)

    def list_profiles(self) -> dict[str, Any]:
        self.require()
        with self.engine.connect() as con:
            q = sa.select(profiles).where(profiles.c.site_id == self.context.site_id)
            if "admin" not in self.context.principal_roles:
                q = q.where(
                    sa.or_(
                        profiles.c.owner_id == self.context.principal_user_id,
                        profiles.c.shared.is_(True),
                    )
                )
            return {
                "items": [
                    {
                        **dict(row),
                        "at": str(row["at"]),
                        "owner_id": str(row["owner_id"]),
                    }
                    for row in con.execute(q.order_by(profiles.c.at.desc())).mappings()
                ]
            }

    def save_profile(
        self,
        batch_id: str,
        name: str,
        shared: bool,
        token: str,
        profile_id: str | None = None,
        expected_version: int | None = None,
    ) -> dict[str, Any]:
        request_hash = digest(
            ["profile", batch_id, name, shared, profile_id, expected_version]
        )
        with self.engine.begin() as con:
            row = self.load(con, batch_id, lock=True)
            replay = self.replay(con, token, request_hash)
            if replay:
                return replay
            if (
                not row["result_json"].get("layout_signature")
                or not name.strip()
                or len(name) > 120
            ):
                raise ApiError(
                    422,
                    "manual_profile_invalid",
                    "请先确认字段，再填写不超过120字的方案名称。",
                )
            if shared and "admin" not in self.context.principal_roles:
                raise ApiError(
                    403,
                    "manual_profile_shared_forbidden",
                    "只有管理员可以发布本站共享字段方案。",
                )
            version = 1
            if profile_id:
                old = self.profile(con, profile_id, None)
                if (
                    old["owner_id"] != self.context.principal_user_id
                    and "admin" not in self.context.principal_roles
                ):
                    raise ApiError(
                        403, "manual_profile_owner", "不能修改其他用户的字段方案。"
                    )
                if old["version"] != expected_version:
                    raise ApiError(
                        409,
                        "manual_profile_version",
                        "字段方案已有新版本，请重新读取。",
                    )
                version = old["version"] + 1
            value = {
                "id": profile_id or str(uuid4()),
                "version": version,
                "site_id": self.context.site_id,
                "owner_id": self.context.principal_user_id,
                "name": name.strip(),
                "kind": row["kind"],
                "shared": shared,
                "signature": row["result_json"]["layout_signature"],
                "options_json": {
                    k: row["options_json"].get(k)
                    for k in ("sheet", "header_row", "columns")
                },
                "at": now(),
            }
            try:
                con.execute(profiles.insert().values(**value))
            except IntegrityError as error:
                raise ApiError(
                    409,
                    "manual_profile_version",
                    "字段方案已有新版本，请重新读取后再保存。",
                ) from error
            result = {"id": value["id"], "version": version, "name": name}
            self.record(con, token, batch_id, "PROFILE", request_hash, result)
            return result
