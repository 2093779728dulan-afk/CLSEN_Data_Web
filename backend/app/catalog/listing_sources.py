# ruff: noqa: RUF001, E501 -- Chinese workflow messages.
"""Amazon listing sources reuse catalog drafts, stable identities and approval."""

from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime
from typing import Any, Literal, cast
from uuid import UUID

import sqlalchemy as sa
from pydantic import Field
from sqlalchemy.engine import Connection, Engine

from app.api.errors import ApiError
from app.catalog.commands import semantic_command_digest
from app.catalog.fact_tuples import NORMALIZATION_MANIFEST_ID
from app.catalog.import_repository import (
    MySqlCatalogImportRepository,
    _insert_projection,
)
from app.catalog.import_service import DraftProjection, DraftRow, validate_draft_rows
from app.catalog.inventory import load_catalog_identity_inventory
from app.catalog.listing_registration import (
    SKU_POLICY,
    assert_strict_source,
    prefill_source_code,
    registration_status,
)
from app.catalog.listing_table import LISTING_SCHEMA, source_digest
from app.catalog.models import CatalogWireUuid, StrictCatalogModel
from app.catalog.normalization import seller_sku_match_v1
from app.catalog.platform_evidence import (
    compare_listing,
    listing_payload,
    lock_platform_scopes,
    official_evidence,
)
from app.catalog.production_sources import (
    ProductionSource,
    ProductionSourceRow,
    _create_export,
    _publication,
    _row,
    project_production_source,
    source_text_problem,
    validate_production_source,
)
from app.imports.storage import StoredContent


class ListingSelection(StrictCatalogModel):
    row_id: str = Field(min_length=1, max_length=64)
    include: bool = False
    record_type: Literal["unknown", "parent", "variant"] = "unknown"
    style_code: str = ""
    color: str = ""
    size: str = ""
    selected_sku_id: int | None = Field(default=None, gt=0)
    use_official: bool = False
    confirm_raw_parent: bool = False
    note: str = Field(default="", max_length=1000)


class ListingPreviewRequest(StrictCatalogModel):
    operation_token: CatalogWireUuid
    expected_workflow_revision: int = Field(ge=0)
    expected_catalog_publication_revision: int = Field(ge=0)
    bindings: dict[str, int]
    selections: list[ListingSelection] = Field(max_length=1000)


def _insert_import(
    connection: Connection,
    *,
    site: int,
    actor: int,
    token: UUID,
    source: dict[str, Any],
    base: int | None,
    revision: int,
    projection: DraftProjection,
    stored: StoredContent | None = None,
) -> int:
    export = _create_export(
        connection,
        site_id=site,
        actor_id=actor,
        token=token,
        source=source,
        base=base,
        revision=revision,
        observations=[],
    )
    raw_id = None
    if stored:
        connection.execute(
            sa.text(
                "INSERT IGNORE INTO raw_files(sha256,storage_key,original_filename,media_type,size_bytes,uploaded_by_user_id,uploaded_at) VALUES(:sha,:key,:name,:media,:size,:actor,:at)"
            ),
            {
                "sha": bytes.fromhex(stored.sha256_hex),
                "key": stored.storage_key,
                "name": source["source_name"],
                "media": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                "size": stored.size_bytes,
                "actor": actor,
                "at": datetime.now(UTC).replace(tzinfo=None),
            },
        )
        raw_id = connection.scalar(
            sa.text("SELECT id FROM raw_files WHERE sha256=:sha"),
            {"sha": bytes.fromhex(stored.sha256_hex)},
        )
    if raw_id is None and source.get("file_sha256"):
        raw_id = connection.scalar(
            sa.text("SELECT id FROM raw_files WHERE sha256=:sha"),
            {"sha": bytes.fromhex(source["file_sha256"])},
        )
    row = connection.execute(
        sa.text(
            """INSERT INTO catalog_imports(site_id,operation_token,source_kind,owner_user_id,export_id,base_catalog_version_id,fact_snapshot_tuple_id,normalization_manifest_id,status,workflow_revision,parse_attempt_revision,raw_file_id,original_filename,declared_media_type) VALUES(:site,:token,'production',:actor,:export,:base,NULL,:manifest,:status,0,0,:raw,:filename,:media)"""
        ),
        {
            "site": site,
            "token": token.bytes,
            "actor": actor,
            "export": export,
            "base": base,
            "manifest": NORMALIZATION_MANIFEST_ID,
            "status": projection.initial_status,
            "raw": raw_id,
            "filename": source["source_name"] if raw_id else None,
            "media": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
            if raw_id
            else None,
        },
    )
    import_id = int(row.lastrowid)
    _insert_projection(
        connection,
        import_id=import_id,
        site_id=site,
        workflow_revision=0,
        projection=projection,
    )
    return import_id


def register_listing(
    engine: Engine,
    *,
    site: int,
    actor: int,
    token: UUID,
    parsed: dict[str, Any],
    stored: StoredContent,
    filename: str,
) -> dict[str, Any]:
    from app.catalog.fact_tuples import NORMALIZATION_MANIFEST_ID

    source = parsed | {
        "source_name": filename,
        "file_sha256": stored.sha256_hex,
        "rows": [],
        "bindings": {},
        "selections": [],
        "raw_storage_key": stored.storage_key,
        "raw_size": stored.size_bytes,
    }
    source["digest"] = source_digest(source)

    def effect(connection: Connection) -> tuple[int, dict[str, Any]]:
        base, revision = _publication(connection, site, lock=True)
        found = connection.scalar(
            sa.text(
                "SELECT i.id FROM catalog_imports i JOIN catalog_export_payloads p ON p.export_id=i.export_id AND p.site_id=i.site_id WHERE i.site_id=:site AND i.status NOT IN ('withdrawn','superseded') AND JSON_UNQUOTE(JSON_EXTRACT(p.evidence_payload_json,'$.production_source.file_sha256'))=:sha AND COALESCE(JSON_UNQUOTE(JSON_EXTRACT(p.evidence_payload_json,'$.production_source.sku_format_policy')),'')=:policy ORDER BY i.id LIMIT 1"
            ),
            {
                "site": site,
                "sha": stored.sha256_hex,
                "policy": parsed.get("sku_format_policy", ""),
            },
        )
        if found:
            return 200, {"import_id": int(found), "duplicate": True}
        projection, _ = project_production_source(
            None,
            load_catalog_identity_inventory(
                connection, site_id=site, catalog_version_id=base
            ),
        )
        identity = _insert_import(
            connection,
            site=site,
            actor=actor,
            token=token,
            source=source,
            base=base,
            revision=revision,
            projection=projection,
            stored=stored,
        )
        return 201, {"import_id": identity, "duplicate": False}

    with engine.begin() as connection:
        result = MySqlCatalogImportRepository._execute_command(
            connection,
            operation_token=token,
            operation_kind="listing_upload",
            operation_digest=semantic_command_digest(
                route="listing_upload",
                resource_id=None,
                body={
                    "sha256": stored.sha256_hex,
                    "filename": filename,
                    "manifest": NORMALIZATION_MANIFEST_ID,
                },
                operation_token=token,
            ),
            site_id=site,
            actor_user_id=actor,
            resource_id=None,
            effect=effect,
        )
    return result.safe_result


def _mapped_inventory(
    connection: Connection, site: int, base: int | None
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    inventory = load_catalog_identity_inventory(
        connection, site_id=site, catalog_version_id=base
    )
    mapped = (
        [
            dict(row)
            for row in connection.execute(
                sa.text(
                    "SELECT report_source_scope_id, seller_sku_match_bytes,sku_id FROM product_catalog_mappings WHERE site_id=:site AND catalog_version_id=:base"
                ),
                {"site": site, "base": base},
            ).mappings()
        ]
        if base
        else []
    )
    for row in mapped:
        row["seller_sku"] = bytes(row.pop("seller_sku_match_bytes")).decode()
    return list(inventory.skus), mapped


def read_listing(
    engine: Engine,
    *,
    site: int,
    import_id: int,
    bindings_override: dict[str, int] | None = None,
    history_page: int = 1,
) -> dict[str, Any]:
    with (
        engine.connect().execution_options(
            isolation_level="REPEATABLE READ"
        ) as connection,
        connection.begin(),
    ):
        imported, source = listing_payload(connection, site, import_id)
        if bindings_override is not None:
            if not set(bindings_override).issubset(
                {w["name"] for w in source["sheets"]}
            ):
                raise ApiError(422, "listing_sheet_unknown", "店铺选择包含未知工作表。")
            source = source | {"bindings": bindings_override}
        checkpoint = connection.scalar(
            sa.text(
                "SELECT result_json FROM catalog_platform_checks WHERE site_id=:site AND import_id=:id ORDER BY id DESC LIMIT 1"
            ),
            {"site": site, "id": import_id},
        )
        checkpoint = (
            json.loads(checkpoint) if isinstance(checkpoint, str) else checkpoint
        )
        if checkpoint and checkpoint.get("source_only") and bindings_override is None:
            source = source | {
                "bindings": checkpoint["bindings"],
                "selections": checkpoint["selections"],
            }
        base, revision = _publication(connection, site, lock=False)
        evidence = official_evidence(
            connection,
            site,
            source.get("bindings", {}),
            [
                r["seller_sku"]
                for r in source["listing_rows"]
                if r.get("seller_sku") and not source_text_problem(r["seller_sku"])
            ],
        )
        compared = compare_listing(
            source["listing_rows"], source.get("bindings", {}), evidence
        )
        inventory, mappings = _mapped_inventory(connection, site, base)
        source = source | {
            "listing_rows": registration_status(
                source["listing_rows"], inventory, mappings, source.get("bindings", {})
            )
        }
        check = (
            connection.execute(
                sa.text(
                    "SELECT id,evidence_digest,result_json,created_at FROM catalog_platform_checks WHERE site_id=:site AND import_id=:id ORDER BY (JSON_EXTRACT(result_json,'$.source_only') IS NULL) DESC,id DESC LIMIT 1"
                ),
                {"site": site, "id": import_id},
            )
            .mappings()
            .one_or_none()
        )
        latest = connection.scalar(
            sa.text(
                "SELECT i.id FROM catalog_imports i JOIN catalog_export_payloads p ON p.export_id=i.export_id WHERE i.site_id=:site AND JSON_UNQUOTE(JSON_EXTRACT(p.evidence_payload_json,'$.production_source.parent_import_id'))=:parent ORDER BY i.id DESC LIMIT 1"
            ),
            {"site": site, "parent": str(source.get("parent_import_id", import_id))},
        )
        history_scope = """
                FROM catalog_platform_checks checks
                JOIN catalog_imports imports ON imports.id=checks.import_id
                    AND imports.site_id=checks.site_id
                JOIN catalog_export_payloads payload ON payload.export_id=imports.export_id
                    AND payload.site_id=imports.site_id
                WHERE checks.site_id=:site AND (imports.id=:root OR
                    JSON_UNQUOTE(JSON_EXTRACT(payload.evidence_payload_json,
                    '$.production_source.parent_import_id'))=:root_text)
            """
        history_parameters = {
            "site": site,
            "root": source.get("parent_import_id", import_id),
            "root_text": str(source.get("parent_import_id", import_id)),
        }
        history_total = int(
            connection.scalar(
                sa.text("SELECT COUNT(*) " + history_scope), history_parameters
            )
            or 0
        )
        # Sort/page only IDs: sorting full check JSON can exhaust MySQL sort memory.
        history_ids = list(
            connection.scalars(
                sa.text(
                    "SELECT checks.id "
                    + history_scope
                    + " ORDER BY checks.id DESC LIMIT 20 OFFSET :offset"
                ),
                history_parameters | {"offset": (history_page - 1) * 20},
            )
        )
        history_records = (
            list(
                connection.execute(
                    sa.text("""
                SELECT checks.id,checks.import_id,checks.created_at,
                       checks.created_by_user_id,users.username_normalized,checks.result_json
                FROM catalog_platform_checks checks
                JOIN users ON users.id=checks.created_by_user_id
                WHERE checks.site_id=:site AND checks.id IN :ids
            """).bindparams(sa.bindparam("ids", expanding=True)),
                    {"site": site, "ids": history_ids},
                ).mappings()
            )
            if history_ids
            else []
        )
        history = []
        for saved in sorted(
            history_records, key=lambda row: int(row["id"]), reverse=True
        ):
            snapshot = (
                json.loads(saved["result_json"])
                if isinstance(saved["result_json"], str)
                else saved["result_json"]
            )
            history.append(
                {
                    "check_id": str(saved["id"]),
                    "import_id": int(saved["import_id"]),
                    "actor_id": str(saved["created_by_user_id"]),
                    "actor": saved["username_normalized"],
                    "created_at": saved["created_at"].replace(tzinfo=UTC).isoformat(),
                    "source_only": bool(snapshot.get("source_only")),
                    "selections": snapshot.get("selections", []),
                }
            )
        from app.catalog.task_queries import listing_progress, unprocessed_groups

        progress = listing_progress(
            connection, site, [int(source.get("parent_import_id") or import_id)]
        )
        processing = progress[int(source.get("parent_import_id") or import_id)]
        processing["remaining_count"] = unprocessed_groups(
            source["listing_rows"], processing["rows"]
        )
        return {
            "processing": processing,
            "import_id": import_id,
            "status": imported["status"],
            "workflow_revision": int(imported["workflow_revision"]),
            "catalog_publication_revision": revision,
            "source": source,
            "assessments": compared,
            "inventory": inventory,
            "mappings": mappings,
            "check_id": str(check["id"]) if check else None,
            "stale": bool(
                check and bytes(check["evidence_digest"]).hex() != evidence["digest"]
            ),
            "coverage": {
                "members": evidence["members"],
                "message": "仅比较当前工作区、所选账号和站点的已发布报告。未出现的报告或历史关系不视为已核实。",
            },
            "latest_candidate_id": int(latest) if latest else None,
            "check_history": history,
            "history_total": history_total,
            "history_page": history_page,
            "history_has_next": history_total > history_page * 20,
        }


def preview_listing(
    engine: Engine,
    *,
    site: int,
    actor: int,
    import_id: int,
    command: ListingPreviewRequest,
) -> dict[str, Any]:
    def effect(connection: Connection) -> tuple[int, dict[str, Any]]:
        base, revision = _publication(connection, site, lock=True)
        imported, original = listing_payload(connection, site, import_id)
        if (
            revision != command.expected_catalog_publication_revision
            or int(imported["workflow_revision"]) != command.expected_workflow_revision
        ):
            raise ApiError(
                409, "listing_stale", "商品目录或草稿已变化，请重新读取后核对。"
            )
        assert_strict_source(original, command.selections)
        if not set(command.bindings).issubset(
            {sheet["name"] for sheet in original["sheets"]}
        ):
            raise ApiError(422, "listing_binding_invalid", "店铺选择包含未知工作表。")
        lock_platform_scopes(connection, site, list(command.bindings.values()))
        raw_rows = {r["row_id"]: r for r in original["listing_rows"]}
        if len({r.row_id for r in command.selections}) != len(
            command.selections
        ) or not {r.row_id for r in command.selections}.issubset(raw_rows):
            raise ApiError(
                422, "listing_row_invalid", "清单行重复或已变化，请重新读取。"
            )
        evidence = official_evidence(
            connection,
            site,
            command.bindings,
            [
                r["seller_sku"]
                for r in raw_rows.values()
                if r.get("seller_sku") and not source_text_problem(r["seller_sku"])
            ],
        )
        assessments = {
            r["row_id"]: r
            for r in compare_listing(
                list(raw_rows.values()), command.bindings, evidence
            )
        }
        inventory = load_catalog_identity_inventory(
            connection, site_id=site, catalog_version_id=base
        )
        skus = {int(str(r["sku_id"])): r for r in inventory.skus}
        _, mappings = _mapped_inventory(connection, site, base)
        existing_mapping = {
            (int(r["report_source_scope_id"]), r["seller_sku"]): int(r["sku_id"])
            for r in mappings
        }
        records: list[ProductionSourceRow] = []
        chosen: list[dict[str, Any]] = []
        processed: set[str] = set()
        for selection in command.selections:
            if not selection.include:
                continue
            raw = raw_rows[selection.row_id]
            check = assessments[selection.row_id]
            place = f"工作表“{raw['sheet']}”，第{raw['row']}行"
            if not check["scope_id"]:
                raise ApiError(
                    422, "listing_scope_required", f"{place}：请先选择店铺账号和站点。"
                )
            if selection.record_type == "parent":
                if any(
                    kind in {"f", "e", "n"}
                    for field, kind in raw.get("cell_types", {}).items()
                    if field != "seller_sku" and raw.get(field)
                ):
                    raise ApiError(
                        422,
                        "listing_parent_invalid",
                        f"{place}：父级平台标识也须为明确文本，不能是公式或数字。",
                    )
                parent_issues = raw.get("issues", [])
                numeric_parent = (
                    raw.get("cell_types", {}).get("seller_sku") == "n"
                    and raw.get("seller_sku", "").isdigit()
                )
                if parent_issues and not (numeric_parent and len(parent_issues) == 1):
                    raise ApiError(
                        422, "listing_parent_invalid", f"{place}：{parent_issues[0]}"
                    )
                if not selection.confirm_raw_parent:
                    raise ApiError(
                        422,
                        "listing_parent_required",
                        f"{place}：请核对父级编码及前导零并明确确认。",
                    )
                chosen.append(
                    selection.model_dump()
                    | {"scope_id": check["scope_id"], "platform_mapping": False}
                )
                continue
            if selection.record_type != "variant":
                raise ApiError(
                    422, "listing_type_required", f"{place}：请明确父级或具体规格类型。"
                )
            if check["state"] in {"official_conflict", "source_conflict"}:
                raise ApiError(
                    422,
                    "listing_identity_conflict",
                    f"{place}：{check['message']} 本行保留待核，其他明确行可以继续。",
                )
            if check["state"] == "source_difference" and not selection.use_official:
                raise ApiError(
                    422,
                    "listing_official_confirmation",
                    f"{place}：请核对差异并明确采用官方依据。",
                )
            if raw.get("cell_types", {}).get(
                "seller_sku"
            ) != "s" or source_text_problem(raw["seller_sku"]):
                raise ApiError(
                    422,
                    "listing_source_invalid",
                    f"{place}：卖家SKU须为规范文本，不能改写原码。",
                )
            if any(
                kind in {"f", "e", "n"}
                for field, kind in raw.get("cell_types", {}).items()
                if raw.get(field)
            ):
                raise ApiError(
                    422,
                    "listing_source_invalid",
                    f"{place}：业务列含数字、公式或错误值，请在原表核对后改为文本。",
                )
            if raw.get("issues") and not all(
                "尺码XLL" in issue
                and selection.size != "XLL"
                and selection.note.strip()
                for issue in raw["issues"]
            ):
                raise ApiError(
                    422, "listing_source_invalid", f"{place}：{raw['issues'][0]}"
                )
            target = (
                skus.get(selection.selected_sku_id)
                if selection.selected_sku_id
                else None
            )
            if selection.selected_sku_id and target is None:
                raise ApiError(
                    422, "listing_sku_invalid", f"{place}：请选择当前主档中存在的商品。"
                )
            mapped_id = existing_mapping.get(
                (
                    int(check["scope_id"]),
                    seller_sku_match_v1(raw["seller_sku"]).utf8.decode(),
                )
            )
            excluded = connection.scalar(
                sa.text(
                    "SELECT id FROM product_catalog_exclusions WHERE site_id=:site AND catalog_version_id=:base AND report_source_scope_id=:scope AND seller_sku_match_bytes=:match"
                ),
                {
                    "site": site,
                    "base": base,
                    "scope": check["scope_id"],
                    "match": seller_sku_match_v1(raw["seller_sku"]).utf8,
                },
            )
            if excluded:
                raise ApiError(
                    409,
                    "listing_source_excluded",
                    f"{place}：此店铺编码已有排除决定，请从原目录维护更正。",
                )
            if mapped_id and selection.selected_sku_id != mapped_id:
                raise ApiError(
                    422,
                    "listing_sku_conflict",
                    f"{place}：此店铺Seller SKU已关联商品#{mapped_id}，请选择原商品；改归属需原高风险更正流程。",
                )
            if target and any(
                selection.model_dump()[key] != str(target[field])
                for key, field in [
                    ("style_code", "style_code"),
                    ("color", "standard_color"),
                    ("size", "standard_size"),
                ]
            ):
                raise ApiError(
                    422,
                    "listing_spec_conflict",
                    f"{place}：所选商品与款号、颜色或尺码不一致，请重新选择。",
                )
            if selection.size == "XLL":
                raise ApiError(
                    422,
                    "listing_size_required",
                    f"{place}：请核实XLL对应的标准尺码并填写依据；Seller SKU原码保留。",
                )
            for field, label in (
                ("style_code", "款号"),
                ("color", "标准颜色"),
                ("size", "标准尺码"),
            ):
                problem = source_text_problem(getattr(selection, field))
                if problem:
                    raise ApiError(
                        422, "listing_spec_required", f"{place}（{label}）：{problem}"
                    )
            record = ProductionSourceRow(
                style_code=selection.style_code,
                color=selection.color,
                size=selection.size,
                formal_sku=(
                    cast(str, target["internal_display_sku"])
                    if target and target["internal_display_sku"]
                    else raw["seller_sku"]
                ),
                selected_sku_id=selection.selected_sku_id,
            )
            identity = (record.style_code, record.color, record.size)
            prior = next(
                (r for r in records if (r.style_code, r.color, r.size) == identity),
                None,
            )
            if prior and prior.formal_sku != record.formal_sku:
                raise ApiError(
                    422,
                    "listing_primary_code_required",
                    f"{place}：同一新规格存在多个正式码候选，请先确认一个主要编码，其余保留后续关联。",
                )
            if check["primary_row"] in processed:
                continue
            processed.add(check["primary_row"])
            if not prior:
                records.append(record)
            chosen.append(
                selection.model_dump()
                | {
                    "scope_id": check["scope_id"],
                    "platform_mapping": check["can_map"],
                    "seller_sku": raw["seller_sku"],
                }
            )
        if not records:
            if not chosen:
                raise ApiError(
                    422, "listing_no_records", "请选择至少一条已明确类型的记录。"
                )
            snapshot = {
                "source_only": True,
                "bindings": command.bindings,
                "selections": chosen,
                "evidence": evidence,
                "assessments": list(assessments.values()),
            }
            inserted = connection.execute(
                sa.text(
                    "INSERT INTO catalog_platform_checks(site_id,import_id,workflow_revision,catalog_publication_revision,source_digest,evidence_digest,algorithm_version,result_json,created_by_user_id,created_at) VALUES(:site,:id,:workflow,:revision,:source,:evidence,'listing_check_v1',CAST(:result AS JSON),:actor,:at)"
                ),
                {
                    "site": site,
                    "id": import_id,
                    "workflow": command.expected_workflow_revision,
                    "revision": revision,
                    "source": bytes.fromhex(original["digest"]),
                    "evidence": bytes.fromhex(evidence["digest"]),
                    "result": json.dumps(snapshot, ensure_ascii=False),
                    "actor": actor,
                    "at": datetime.now(UTC).replace(tzinfo=None),
                },
            )
            return 200, {
                "import_id": import_id,
                "check_id": str(inserted.lastrowid),
                "source_only": True,
            }
        prod = ProductionSource(source_name=original["source_name"], rows=records)
        validate_production_source(prod, inventory)
        projection, observations = project_production_source(prod, inventory)
        rows = {r.row_key: r for r in projection.rows}
        for selected in chosen:
            if selected["record_type"] != "variant":
                continue
            obs = next(
                o
                for o in observations
                if (o["style_code"], o["color"], o["size"])
                == (selected["style_code"], selected["color"], selected["size"])
            )
            selected["sku_row_key"] = obs["sku_row_key"]
            if original.get("sku_format_policy") == SKU_POLICY:
                sku_row = rows[str(obs["sku_row_key"])]
                rows[sku_row.row_key] = _row(
                    "skus",
                    sku_row.row_key,
                    prefill_source_code(
                        dict(sku_row.payload),
                        selected["seller_sku"],
                        original["source_name"],
                    ),
                )
            if selected["platform_mapping"]:
                raw = selected["seller_sku"]
                scope = selected["scope_id"]
                row_key = (
                    "listing-map-"
                    + hashlib.sha256(f"{scope}\0{raw}".encode()).hexdigest()[:40]
                )
                rows[row_key] = _row(
                    "mappings",
                    row_key,
                    {
                        "seller_sku_preview": raw,
                        "seller_sku_sha256": "sha256:"
                        + hashlib.sha256(raw.encode()).hexdigest(),
                        "seller_account": str(scope),
                        "marketplace": "amazon_us",
                        "identity_decision": "mapped",
                        "target_sku_row_key": obs["sku_row_key"],
                        "source_target_sku_row_key": obs["sku_row_key"],
                    },
                )
        # Retain name/code-provenance edits on a successor; raw identity decisions are rechecked.
        if original.get("selections"):
            from app.catalog.repository import load_import_rows

            previous = {
                r.row_key: r
                for r in load_import_rows(
                    connection,
                    import_id=import_id,
                    workflow_revision=int(imported["workflow_revision"]),
                )
            }
            for key, row in list(rows.items()):
                old = previous.get(key)
                if old and row.section in {"styles", "skus"}:
                    payload = dict(row.payload)
                    for field in (
                        ("standard_name", "category_action", "category_code")
                        if row.section == "styles"
                        else ("code_status", "code_evidence")
                    ):
                        if old.payload.get(field) is not None:
                            payload[field] = old.payload[field]
                    rows[key] = _row(row.section, key, payload)
        projection = validate_draft_rows(tuple(rows.values()))
        source = dict(original)
        source.update(
            rows=[r.model_dump() for r in records],
            bindings=command.bindings,
            selections=chosen,
            parent_import_id=original.get("parent_import_id", import_id),
            evidence_digest=evidence["digest"],
        )
        source["digest"] = source_digest(
            {
                "file": source["file_sha256"],
                "schema": LISTING_SCHEMA,
                "bindings": command.bindings,
                "selections": chosen,
                "base": base,
                "evidence": evidence["digest"],
            }
        )
        duplicate = connection.scalar(
            sa.text(
                "SELECT i.id FROM catalog_imports i JOIN catalog_export_payloads p ON p.export_id=i.export_id AND p.site_id=i.site_id WHERE i.site_id=:site AND i.workflow_revision=0 AND i.status NOT IN ('withdrawn','superseded','rejected') AND JSON_UNQUOTE(JSON_EXTRACT(p.evidence_payload_json,'$.production_source.digest'))=:digest ORDER BY i.id DESC LIMIT 1"
            ),
            {"site": site, "digest": source["digest"]},
        )
        if duplicate:
            return 200, {"import_id": int(duplicate), "duplicate": True}

        candidate = _insert_import(
            connection,
            site=site,
            actor=actor,
            token=command.operation_token,
            source=source,
            base=base,
            revision=revision,
            projection=projection,
        )
        frozen = {
            "evidence": evidence,
            "assessments": list(assessments.values()),
            "selections": chosen,
            "source_schema": LISTING_SCHEMA,
        }
        check_id = connection.execute(
            sa.text(
                "INSERT INTO catalog_platform_checks(site_id,import_id,workflow_revision,catalog_publication_revision,source_digest,evidence_digest,algorithm_version,result_json,created_by_user_id,created_at) VALUES(:site,:id,0,:revision,:source,:evidence,'listing_check_v1',CAST(:result AS JSON),:actor,:at)"
            ),
            {
                "site": site,
                "id": candidate,
                "revision": revision,
                "source": bytes.fromhex(source["digest"]),
                "evidence": bytes.fromhex(evidence["digest"]),
                "result": json.dumps(frozen, ensure_ascii=False),
                "actor": actor,
                "at": datetime.now(UTC).replace(tzinfo=None),
            },
        ).lastrowid
        return 201, {
            "import_id": candidate,
            "check_id": str(check_id),
            "selected_variants": len(records),
        }

    with engine.begin() as connection:
        result = MySqlCatalogImportRepository._execute_command(
            connection,
            operation_token=command.operation_token,
            operation_kind="listing_preview",
            operation_digest=semantic_command_digest(
                route="listing_preview",
                resource_id=import_id,
                body=command.model_dump(mode="json"),
                operation_token=command.operation_token,
            ),
            site_id=site,
            actor_user_id=actor,
            resource_id=import_id,
            effect=effect,
        )
    return result.safe_result


def assert_listing_approval(
    connection: Connection,
    *,
    site_id: int,
    import_id: int,
    rows: tuple[DraftRow, ...],
    lock: bool,
) -> bool:
    value = connection.scalar(
        sa.text(
            "SELECT p.evidence_payload_json FROM catalog_imports i JOIN catalog_export_payloads p ON p.export_id=i.export_id WHERE i.id=:id AND i.site_id=:site AND i.source_kind='production'"
        ),
        {"id": import_id, "site": site_id},
    )
    if value is None:
        return False
    payload = json.loads(value) if isinstance(value, str) else value
    source = payload.get("production_source", {})
    schema = source.get("source_schema")
    selection = source.get("report_selection")
    if selection is not None and (schema is not None or selection.get("version") != 1):
        raise ApiError(
            409, "report_selection_unknown", "此报表来源格式版本不能由当前程序批准。"
        )
    if schema is None and selection is None:
        return False
    if selection is None and schema != LISTING_SCHEMA:
        raise ApiError(
            409, "listing_schema_unknown", "此来源格式版本不能由当前程序批准。"
        )
    frozen = (
        connection.execute(
            sa.text(
                "SELECT result_json,evidence_digest FROM catalog_platform_checks WHERE site_id=:site AND import_id=:id AND JSON_EXTRACT(result_json,'$.source_only') IS NULL ORDER BY id DESC LIMIT 1"
            ),
            {"site": site_id, "id": import_id},
        )
        .mappings()
        .one_or_none()
    )
    if not frozen:
        raise ApiError(
            409,
            "listing_check_required",
            "商品清单尚未核对，请返回亚马逊商品清单选择店铺、规格并预览。",
        )
    if not selection and not any(
        r.get("record_type") == "variant" for r in source.get("selections", [])
    ):
        raise ApiError(
            409,
            "listing_source_only",
            "父级核对或原始清单无需批准目录；请返回清单选择具体规格后继续。",
        )
    if lock:
        lock_platform_scopes(connection, site_id, list(source["bindings"].values()))
    evidence = official_evidence(
        connection,
        site_id,
        source["bindings"],
        [
            r["seller_sku"]
            for r in (selection["source_rows"] if selection else source["listing_rows"])
            if r.get("seller_sku") and not source_text_problem(r["seller_sku"])
        ],
    )
    if bytes(frozen["evidence_digest"]).hex() != evidence["digest"]:
        raise ApiError(
            409,
            "listing_evidence_stale",
            "官方报表或店铺范围已更新，请返回对应来源重新核对；当前草稿和历史已保留。",
        )
    by_key = {r.row_key: r for r in rows}
    if selection:
        from app.catalog.report_selection import assert_selection_projection

        assert_selection_projection(source, rows, evidence)
    for selected in source["selections"]:
        if selected["record_type"] != "variant":
            continue
        row = by_key.get(selected["sku_row_key"])
        if (
            row is None
            or row.payload.get("standard_color") != selected["color"]
            or row.payload.get("standard_size") != selected["size"]
        ):
            raise ApiError(
                409,
                "listing_identity_stale",
                "审核中的规格已改变，请返回清单重新核对。",
            )
        style = by_key.get(str(row.payload.get("style_row_key")))
        if style is None or style.payload.get("style_code") != selected["style_code"]:
            raise ApiError(
                409,
                "listing_identity_stale",
                "审核中的款号已改变，请返回清单重新核对。",
            )

    return True
