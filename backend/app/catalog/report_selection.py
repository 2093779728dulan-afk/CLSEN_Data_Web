# ruff: noqa: E501, RUF001 -- Localized source-selection workflow.
"""One published source identity projected into the existing catalog review."""

from __future__ import annotations

import hashlib
import json
from typing import Any, Literal, cast

import sqlalchemy as sa
from pydantic import Field
from sqlalchemy.engine import Connection, Engine

from app.api.errors import ApiError
from app.catalog.canonical_json import CanonicalValue
from app.catalog.commands import semantic_command_digest
from app.catalog.import_repository import MySqlCatalogImportRepository
from app.catalog.import_service import DraftRow, validate_draft_rows
from app.catalog.inventory import load_catalog_identity_inventory
from app.catalog.listing_sources import _insert_import
from app.catalog.listing_table import source_digest
from app.catalog.models import CatalogWireUuid, StrictCatalogModel
from app.catalog.normalization import seller_sku_match_v1
from app.catalog.platform_evidence import (
    compare_listing,
    lock_platform_scopes,
    official_evidence,
)
from app.catalog.production_sources import (
    ProductionSource,
    ProductionSourceRow,
    _key,
    _publication,
    _row,
    project_production_source,
    source_text_problem,
    validate_production_source,
)


class ReportSource(StrictCatalogModel):
    source_key: str = Field(pattern=r"^match_[0-9a-f]{64}$")
    scope_id: int = Field(gt=0)
    version_ids: list[int] = Field(min_length=1, max_length=732)


class ReportSelection(ReportSource):
    action: Literal["map", "create", "exclude"]
    selected_sku_id: int | None = Field(default=None, gt=0)
    style_code: str = Field(default="", max_length=128)
    color: str = Field(default="", max_length=128)
    size: str = Field(default="", max_length=128)
    reason: str = Field(min_length=10, max_length=1000)
    expected_catalog_publication_revision: int = Field(ge=0)
    replace_import_id: int | None = Field(default=None, gt=0)
    expected_workflow_revision: int | None = Field(default=None, ge=0)


class SaveReportSelection(ReportSelection):
    operation_token: CatalogWireUuid
    preview_digest: str = Field(pattern=r"^[0-9a-f]{64}$")


def selected_source(
    connection: Connection, site: int, command: ReportSource
) -> tuple[str, dict[str, Any]]:
    """Resolve original report text from immutable rows, never from a UI preview."""
    evidence = official_evidence(connection, site, {"已发布报表": command.scope_id}, [])
    versions = {int(m["version_id"]) for m in evidence["members"]}
    if not set(command.version_ids).issubset(versions):
        raise ApiError(
            409,
            "catalog_selection_stale",
            "所选报告版本已变化，请重新读取来源后预览；当前输入保留。",
        )
    originals: set[str] = set()
    for table in ["business_report_rows", "return_report_rows"]:
        rows = connection.execute(
            sa.text(f"""
          SELECT f.sku FROM report_source_keys k
          JOIN report_dataset_scope_assignments a ON a.dataset_id=k.dataset_id AND a.site_id=k.site_id AND a.report_source_scope_id=k.report_source_scope_id
          JOIN dataset_publications p ON p.dataset_id=k.dataset_id AND p.version_id=k.version_id
          JOIN version_rows vr ON vr.id=k.source_row_id AND vr.version_id=k.version_id AND vr.row_state='active'
          JOIN {table} f ON f.version_row_id=vr.id AND f.version_id=vr.version_id
          WHERE k.site_id=:site AND k.report_source_scope_id=:scope
            AND k.seller_sku_match_sha256=:key AND k.version_id IN :versions
        """).bindparams(sa.bindparam("versions", expanding=True)),
            {
                "site": site,
                "scope": command.scope_id,
                "key": bytes.fromhex(command.source_key[6:]),
                "versions": command.version_ids,
            },
        ).scalars()
        originals.update(str(raw) for raw in rows if raw is not None)
    if len(originals) != 1:
        raise ApiError(
            409,
            "catalog_selection_identity",
            "此来源缺失或存在多个编码原文，请查看原报告并核实，不能自动合并。",
        )
    raw = originals.pop()
    if (
        source_text_problem(raw)
        or seller_sku_match_v1(raw).sha256.hex() != command.source_key[6:]
    ):
        raise ApiError(
            422,
            "catalog_selection_format",
            "此来源编码需要先核对原始格式，请从来源详情或目录工作簿处理；不会自动改码。",
        )
    return raw, official_evidence(
        connection, site, {"已发布报表": command.scope_id}, [raw]
    )


def build_selection(
    connection: Connection, site: int, command: ReportSelection, *, lock: bool
) -> tuple[Any, dict[str, Any], dict[str, Any]]:
    if len(command.reason.strip()) < 10:
        raise ApiError(
            422,
            "catalog_selection_reason",
            "请填写至少10字的实际处理依据，不能只填空格。",
        )
    base, revision = _publication(connection, site, lock=lock)
    if revision != command.expected_catalog_publication_revision:
        raise ApiError(
            409,
            "catalog_selection_stale",
            "商品目录已变化，请保留输入并重新读取后预览。",
        )
    if lock:
        lock_platform_scopes(connection, site, [command.scope_id])
    raw, evidence = selected_source(connection, site, command)
    raw_row = {"row_id": command.source_key, "sheet": "已发布报表", "seller_sku": raw}
    assessment = compare_listing([raw_row], {"已发布报表": command.scope_id}, evidence)[
        0
    ]
    if assessment["state"] == "official_conflict":
        raise ApiError(
            409,
            "catalog_selection_conflict",
            "官方来源存在多个子ASIN，请先核对平台身份；不能通过关联或排除绕过冲突。",
        )
    current = connection.scalar(
        sa.text(
            "SELECT sku_id FROM product_catalog_mappings WHERE site_id=:site AND catalog_version_id=:base AND report_source_scope_id=:scope AND seller_sku_match_bytes=:key"
        ),
        {
            "site": site,
            "base": base,
            "scope": command.scope_id,
            "key": seller_sku_match_v1(raw).utf8,
        },
    )
    if current:
        raise ApiError(
            409,
            "catalog_selection_already_mapped",
            "此来源已有关联，请刷新查看原商品；更改归属需使用原高风险更正流程。",
        )
    excluded = connection.scalar(
        sa.text(
            "SELECT id FROM product_catalog_exclusions WHERE site_id=:site AND catalog_version_id=:base AND report_source_scope_id=:scope AND seller_sku_match_bytes=:key"
        ),
        {
            "site": site,
            "base": base,
            "scope": command.scope_id,
            "key": seller_sku_match_v1(raw).utf8,
        },
    )
    if excluded:
        raise ApiError(
            409,
            "catalog_selection_already_excluded",
            "此来源已有审核排除决定，请从原目录维护更正，不重复建立候选。",
        )
    inventory = load_catalog_identity_inventory(
        connection, site_id=site, catalog_version_id=base
    )
    target = next(
        (s for s in inventory.skus if str(s["sku_id"]) == str(command.selected_sku_id)),
        None,
    )
    enabled_styles = {
        s["style_id"] for s in inventory.styles if s["status"] == "enabled"
    }
    if command.action == "map" and (
        not target
        or target["status"] != "enabled"
        or target["style_id"] not in enabled_styles
        or target.get("code_status") != "confirmed"
    ):
        raise ApiError(
            422,
            "catalog_selection_target",
            "请选择当前工作区已启用且正式SKU已确认的实际商品规格；待补码商品请先完成原编码审核。",
        )
    if command.action != "map" and command.selected_sku_id is not None:
        raise ApiError(
            422,
            "catalog_selection_target",
            "新建规格不能同时指定已有商品，请重新选择处理方式。",
        )
    if command.action != "exclude":
        spec = {
            key: str(target[field]) if target else getattr(command, key)
            for key, field in [
                ("style_code", "style_code"),
                ("color", "standard_color"),
                ("size", "standard_size"),
            ]
        }
        record = ProductionSourceRow(
            **spec,
            formal_sku=(
                cast(str | None, target.get("internal_display_sku")) if target else raw
            ),
            selected_sku_id=command.selected_sku_id,
        )
        prod = ProductionSource(source_name="已发布报表 · 单条来源处理", rows=[record])
        validate_production_source(prod, inventory)
        projection, observations = project_production_source(prod, inventory)
        selected = (
            command.model_dump()
            | spec
            | {
                "row_id": command.source_key,
                "record_type": "variant",
                "scope_id": command.scope_id,
                "seller_sku": raw,
                "platform_mapping": assessment["can_map"],
                "sku_row_key": observations[0]["sku_row_key"],
            }
        )
    else:
        projection, observations = project_production_source(None, inventory)
        record = None
        selected = command.model_dump() | {
            "row_id": command.source_key,
            "record_type": "excluded",
            "scope_id": command.scope_id,
            "seller_sku": raw,
            "platform_mapping": True,
            "sku_row_key": None,
        }
    if command.action != "exclude" and not assessment["can_map"]:
        raise ApiError(
            409,
            "catalog_selection_evidence",
            "当前官方子ASIN依据不足，不能从待归属入口直接建立渠道关联。可以先从商品建档保存内部规格。",
        )
    rows = {r.row_key: r for r in projection.rows}
    mapping_key = _key("report-map-", str(command.scope_id), raw)
    rows[mapping_key] = _row(
        "mappings",
        mapping_key,
        {
            "row_key": mapping_key,
            "marketplace": "amazon_us",
            "seller_account": str(command.scope_id),
            "seller_sku_preview": raw,
            "seller_sku_sha256": "sha256:" + hashlib.sha256(raw.encode()).hexdigest(),
            "identity_decision": "excluded"
            if command.action == "exclude"
            else "mapped",
            "target_sku_row_key": selected["sku_row_key"],
            "source_target_sku_row_key": selected["sku_row_key"],
            "exclusion_reason": command.reason if command.action == "exclude" else None,
            "change_reason": command.reason,
        },
    )
    projection = validate_draft_rows(tuple(rows.values()))
    source = {
        "source_name": "已发布报表 · 单条来源处理",
        "rows": [record.model_dump()] if record else [],
        "bindings": {"已发布报表": command.scope_id},
        "selections": [selected],
        "report_selection": {
            "version": 1,
            "source_rows": [raw_row],
            "request": command.model_dump(),
            "evidence_digest": evidence["digest"],
        },
        "digest": source_digest(
            {
                "request": command.model_dump(),
                "evidence": evidence["digest"],
                "base": base,
            }
        ),
    }
    preview = {
        "preview_digest": source["digest"],
        "catalog_publication_revision": revision,
        "source": raw,
        "scope_id": command.scope_id,
        "report_members": evidence["members"],
        "assessment": assessment,
        "observations": observations,
        "created_style_count": sum(
            r.section == "styles" and r.payload.get("system_style_id") is None
            for r in projection.rows
        ),
        "created_sku_count": sum(
            r.section == "skus" and r.payload.get("system_sku_id") is None
            for r in projection.rows
        ),
        "mapping_count": int(command.action != "exclude"),
        "excluded_count": int(command.action == "exclude"),
        "kept_sku_count": len(inventory.skus),
        "base_catalog_version_id": base,
    }
    return projection, source, preview


def related_candidates(
    connection: Connection, site: int, scope: int, raw: str
) -> list[dict[str, Any]]:
    from app.catalog.task_queries import IMPORT_SELECT, import_metadata, source_payload

    records = connection.execute(
        sa.text(
            IMPORT_SELECT
            + " WHERE i.site_id=:site ORDER BY i.updated_at DESC,i.id DESC"
        ),
        {"site": site},
    ).mappings()
    related = []
    for record in records:
        source = source_payload(record["evidence_payload_json"])
        if any(
            str(s.get("scope_id")) == str(scope) and s.get("seller_sku") == raw
            for s in source.get("selections", [])
        ):
            related.append(import_metadata(record))
    # Workbook and online candidates are also authoritative references.
    rows = connection.execute(
        sa.text("""
      SELECT DISTINCT i.id,i.status,i.workflow_revision FROM catalog_import_rows r
      JOIN catalog_imports i ON i.id=r.import_id AND i.site_id=r.site_id
      WHERE r.site_id=:site AND r.section='mappings'
      AND r.workflow_revision=(SELECT MAX(p.workflow_revision) FROM catalog_import_rows p
        WHERE p.import_id=r.import_id AND p.section=r.section AND p.workflow_revision<=i.workflow_revision)
      AND JSON_UNQUOTE(JSON_EXTRACT(r.payload_json,'$.seller_account'))=:scope
      AND JSON_UNQUOTE(JSON_EXTRACT(r.payload_json,'$.seller_sku_preview'))=:raw
    """),
        {"site": site, "scope": str(scope), "raw": raw},
    ).mappings()
    known = {r["import_id"] for r in related}
    for row in rows:
        if row["id"] not in known:
            related.append(
                {
                    "import_id": row["id"],
                    "status": row["status"],
                    "workflow_revision": row["workflow_revision"],
                    "review_path": f"/catalog/imports/{row['id']}",
                    "source_name": "目录维护候选",
                }
            )
    return related


def selection_context(
    engine: Engine, site: int, command: ReportSource
) -> dict[str, Any]:
    with (
        engine.connect().execution_options(
            isolation_level="REPEATABLE READ"
        ) as connection,
        connection.begin(),
    ):
        base, revision = _publication(connection, site, lock=False)
        raw, evidence = selected_source(connection, site, command)
        inventory = load_catalog_identity_inventory(
            connection, site_id=site, catalog_version_id=base
        )
        enabled_styles = {
            s["style_id"] for s in inventory.styles if s["status"] == "enabled"
        }
        mapped = connection.scalar(
            sa.text(
                "SELECT sku_id FROM product_catalog_mappings WHERE site_id=:site AND catalog_version_id=:base AND report_source_scope_id=:scope AND seller_sku_match_bytes=:key"
            ),
            {
                "site": site,
                "base": base,
                "scope": command.scope_id,
                "key": seller_sku_match_v1(raw).utf8,
            },
        )
        excluded = connection.scalar(
            sa.text(
                "SELECT id FROM product_catalog_exclusions WHERE site_id=:site AND catalog_version_id=:base AND report_source_scope_id=:scope AND seller_sku_match_bytes=:key"
            ),
            {
                "site": site,
                "base": base,
                "scope": command.scope_id,
                "key": seller_sku_match_v1(raw).utf8,
            },
        )
        return {
            "source": raw,
            "scope_id": command.scope_id,
            "catalog_publication_revision": revision,
            "evidence": evidence,
            "candidates": related_candidates(connection, site, command.scope_id, raw),
            "skus": [
                s
                for s in inventory.skus
                if s["status"] == "enabled" and s["style_id"] in enabled_styles
            ],
            "mapped_sku_id": mapped,
            "mapped_style_id": next(
                (s["style_id"] for s in inventory.skus if s["sku_id"] == mapped), None
            ),
            "excluded": bool(excluded),
        }


def recheck_source(engine: Engine, site: int, import_id: int) -> dict[str, Any]:
    from app.catalog.production_sources import production_evidence

    with engine.connect() as connection:
        source = production_evidence(connection, import_id=import_id, site_id=site)
        proof = source.get("report_selection") if source else None
        if not isinstance(proof, dict) or proof.get("version") != 1:
            raise ApiError(
                409,
                "report_selection_unknown",
                "此批次不是可重新核对的报表单条候选，请从原来源入口继续。",
            )
        request = ReportSelection.model_validate(proof["request"])
        raw = proof["source_rows"][0]["seller_sku"]
        evidence = official_evidence(
            connection, site, {"已发布报表": request.scope_id}, [raw]
        )
        versions = sorted({int(r["version_id"]) for r in evidence["observations"]})
        if not versions:
            raise ApiError(
                409,
                "catalog_selection_stale",
                "当前发布范围已没有此来源，请保留原候选并核实报告状态，不能按失效来源重建。",
            )
        return {
            "source_key": request.source_key,
            "scope_id": request.scope_id,
            "version_ids": versions,
        }


def assert_selection_projection(
    source: dict[str, Any], rows: tuple[DraftRow, ...], evidence: dict[str, Any]
) -> None:
    """A review cannot change the selected scope, target or exclusion after proof."""
    selected = source["selections"][0]
    assessed = compare_listing(
        source["report_selection"]["source_rows"], source["bindings"], evidence
    )[0]
    if assessed["state"] == "official_conflict" or (
        selected["record_type"] == "variant" and not assessed["can_map"]
    ):
        raise ApiError(
            409,
            "catalog_selection_conflict",
            "本条官方依据尚有冲突或不完整，请返回来源重新核对。",
        )
    mappings = [
        r for r in rows if r.section == "mappings" and r.projection_state == "included"
    ]
    expected_decision = (
        "excluded" if selected["record_type"] == "excluded" else "mapped"
    )
    if len(mappings) != 1 or any(
        r.payload.get("identity_decision") != expected_decision
        or r.payload.get("seller_sku_preview") != selected["seller_sku"]
        or str(r.payload.get("seller_account")) != str(selected["scope_id"])
        or r.payload.get("target_sku_row_key") != selected["sku_row_key"]
        for r in mappings
    ):
        raise ApiError(
            409,
            "catalog_selection_changed",
            "本条来源、处理方式或目标已改变，请从来源重新预览；不能沿用旧核对依据。",
        )
    if selected.get("selected_sku_id"):
        target = next(
            (
                r
                for r in rows
                if r.section == "skus" and r.row_key == selected["sku_row_key"]
            ),
            None,
        )
        if not target or str(target.payload.get("system_sku_id")) != str(
            selected["selected_sku_id"]
        ):
            raise ApiError(
                409, "catalog_selection_changed", "所选实际商品身份已改变，请重新预览。"
            )


def preview_selection(
    engine: Engine, site: int, command: ReportSelection
) -> dict[str, Any]:
    with (
        engine.connect().execution_options(
            isolation_level="REPEATABLE READ"
        ) as connection,
        connection.begin(),
    ):
        return build_selection(connection, site, command, lock=False)[2]


def save_selection(
    engine: Engine, site: int, actor: int, command: SaveReportSelection
) -> dict[str, Any]:
    from datetime import UTC, datetime

    request = ReportSelection.model_validate(
        command.model_dump(exclude={"operation_token", "preview_digest"})
    )

    def effect(connection: Connection) -> tuple[int, dict[str, CanonicalValue]]:
        projection, source, preview = build_selection(
            connection, site, request, lock=True
        )
        if command.preview_digest != preview["preview_digest"]:
            raise ApiError(
                409,
                "catalog_selection_stale",
                "来源、选择或官方报告已变化，请重新预览；输入保留。",
            )
        duplicate = connection.scalar(
            sa.text(
                "SELECT i.id FROM catalog_imports i JOIN catalog_export_payloads p ON p.export_id=i.export_id AND p.site_id=i.site_id WHERE i.site_id=:site AND i.status NOT IN ('withdrawn','superseded','rejected') AND JSON_UNQUOTE(JSON_EXTRACT(p.evidence_payload_json,'$.production_source.digest'))=:digest ORDER BY i.id DESC LIMIT 1"
            ),
            {"site": site, "digest": source["digest"]},
        )
        if duplicate:
            return 200, {"import_id": int(duplicate), "duplicate": True}
        related = related_candidates(
            connection, site, request.scope_id, preview["source"]
        )
        active = [
            r
            for r in related
            if r["status"]
            in {"needs_attention", "validated", "ready_for_approval", "rejected"}
        ]
        previous = None
        if request.replace_import_id:
            previous = next(
                (r for r in active if r["import_id"] == request.replace_import_id), None
            )
            if (
                not previous
                or previous["workflow_revision"] != request.expected_workflow_revision
            ):
                raise ApiError(
                    409, "catalog_selection_stale", "原候选已变化，请重新读取后核对。"
                )
            from app.catalog.production_sources import production_evidence

            old_source = production_evidence(
                connection, import_id=request.replace_import_id, site_id=site
            )
            if (
                not old_source
                or cast(dict[str, Any], old_source.get("report_selection", {})).get(
                    "version"
                )
                != 1
            ):
                raise ApiError(
                    409,
                    "catalog_selection_existing",
                    "请先从已有候选继续原审核，不能从此入口替换其他类型的候选。",
                )
        if any(r["import_id"] != request.replace_import_id for r in active):
            raise ApiError(
                409,
                "catalog_selection_existing",
                "本条已有活跃审核候选，请重新读取并从已有候选继续，避免重复建档。",
            )
        identity = _insert_import(
            connection,
            site=site,
            actor=actor,
            token=command.operation_token,
            source=source,
            base=preview["base_catalog_version_id"],
            revision=preview["catalog_publication_revision"],
            projection=projection,
        )
        if previous:
            updated = connection.execute(
                sa.text(
                    "UPDATE catalog_imports SET status='superseded',workflow_revision=workflow_revision+1,superseded_by_id=:next WHERE site_id=:site AND id=:id AND workflow_revision=:revision AND status IN ('needs_attention','validated','ready_for_approval','rejected')"
                ),
                {
                    "next": identity,
                    "site": site,
                    "id": previous["import_id"],
                    "revision": previous["workflow_revision"],
                },
            )
            if updated.rowcount != 1:
                raise ApiError(
                    409,
                    "catalog_selection_stale",
                    "原候选已变化，请重新读取；本次保存已回滚。",
                )
            connection.execute(
                sa.text(
                    "DELETE FROM catalog_draft_identity_reservations WHERE import_id=:id AND site_id=:site"
                ),
                {"id": previous["import_id"], "site": site},
            )
        # The immutable proof uses the same evidence collection and publication locks as listing approval.
        evidence = official_evidence(
            connection, site, source["bindings"], [preview["source"]]
        )
        connection.execute(
            sa.text(
                "INSERT INTO catalog_platform_checks(site_id,import_id,workflow_revision,catalog_publication_revision,source_digest,evidence_digest,algorithm_version,result_json,created_by_user_id,created_at) VALUES(:site,:id,0,:revision,:source,:evidence,'report_selection_v1',CAST(:result AS JSON),:actor,:at)"
            ),
            {
                "site": site,
                "id": identity,
                "revision": preview["catalog_publication_revision"],
                "source": bytes.fromhex(source["digest"]),
                "evidence": bytes.fromhex(evidence["digest"]),
                "result": json.dumps(
                    {
                        "evidence": evidence,
                        "selections": source["selections"],
                        "assessments": [preview["assessment"]],
                    },
                    ensure_ascii=False,
                ),
                "actor": actor,
                "at": datetime.now(UTC).replace(tzinfo=None),
            },
        )
        return 201, {"import_id": identity, "duplicate": False}

    with engine.begin() as connection:
        # Claiming the receipt first would open an older read snapshot. Lock the
        # existing directory pointer before receipts and source reads so two
        # selected saves see each other's committed candidate. This also avoids
        # INSERT IGNORE shared-lock upgrades in _publication.
        pointer = connection.execute(
            sa.text(
                "SELECT site_id FROM product_catalog_publications WHERE site_id=:site FOR UPDATE"
            ),
            {"site": site},
        ).scalar_one_or_none()
        if pointer is None:
            raise ApiError(
                409,
                "catalog_selection_setup",
                "请先在批量维护完成当前工作区的目录初始化，再保存本条来源。",
            )
        result = MySqlCatalogImportRepository._execute_command(
            connection,
            operation_token=command.operation_token,
            operation_kind="report_selection",
            operation_digest=semantic_command_digest(
                route="report_selection",
                resource_id=None,
                body=command.model_dump(mode="json"),
                operation_token=command.operation_token,
            ),
            site_id=site,
            actor_user_id=actor,
            resource_id=None,
            effect=effect,
        )
    return result.safe_result
