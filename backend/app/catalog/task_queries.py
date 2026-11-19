# ruff: noqa: E501, RUF001 -- Scoped workflow queries and Chinese labels.
"""Read projections of catalog sources and reviews, never a second task store."""

from __future__ import annotations

import json
from datetime import UTC, date, datetime
from typing import Any

import sqlalchemy as sa
from sqlalchemy.engine import Connection, Engine

ACTIVE = {
    "uploaded",
    "parsing",
    "parse_failed",
    "needs_attention",
    "validated",
    "ready_for_approval",
    "rejected",
}
IMPORT_SELECT = """
SELECT i.id AS import_id,i.source_kind,i.status,i.workflow_revision,i.created_at,i.updated_at,
       COALESCE((SELECT last_user.username_normalized FROM catalog_command_claims c
         JOIN catalog_command_effects e ON e.operation_token=c.operation_token
         JOIN users last_user ON last_user.id=c.actor_user_id
         WHERE c.site_id=i.site_id AND c.resource_kind='catalog_import' AND c.resource_id=i.id
           AND c.operation_kind NOT IN ('style_change_create','style_change_approve')
         ORDER BY e.completed_at DESC,c.operation_token DESC LIMIT 1),u.username_normalized) AS actor,
       p.evidence_payload_json,
       t.report_source_scope_id AS fact_scope_id,
       (SELECT v.version_number FROM product_catalog_versions v
        WHERE v.source_import_id=i.id AND v.site_id=i.site_id ORDER BY v.id LIMIT 1)
        AS approved_catalog_version_number
FROM catalog_imports i
LEFT JOIN users u ON u.id=i.owner_user_id
LEFT JOIN catalog_export_payloads p ON p.export_id=i.export_id AND p.site_id=i.site_id
LEFT JOIN fact_snapshot_tuples t ON t.id=i.fact_snapshot_tuple_id AND t.site_id=i.site_id
"""


def source_payload(value: Any) -> dict[str, Any]:
    payload = json.loads(value) if isinstance(value, str) else value
    source = (payload or {}).get("production_source", {})
    return dict(source) if isinstance(source, dict) else {}


def import_metadata(row: Any) -> dict[str, Any]:
    source = source_payload(row.get("evidence_payload_json"))
    identity = int(row.get("import_id", row.get("id", 0)))
    schema = source.get("source_schema")
    report = source.get("report_selection")
    root = int(source.get("parent_import_id") or identity)
    listing = schema == "amazon_listing_v1"
    source_only = (
        listing
        and not any(
            s.get("record_type") == "variant" and s.get("sku_row_key")
            for s in source.get("selections", [])
        )
        and row["status"] != "approved"
    )
    path = (
        f"/catalog/production-sources?entry=amazon-listing&listing={identity}"
        if source_only
        else f"/catalog/imports/{identity}"
    )
    scopes = set(source.get("bindings", {}).values())
    if source.get("report_source_scope_id"):
        scopes.add(source["report_source_scope_id"])
    if row.get("fact_scope_id"):
        scopes.add(row["fact_scope_id"])
    updated = row.get("updated_at")
    if isinstance(updated, datetime):
        updated = updated.replace(tzinfo=UTC).isoformat()
    return {
        "import_id": identity,
        "source_kind": row["source_kind"],
        "status": row["status"],
        "workflow_revision": int(row["workflow_revision"]),
        "record_kind": "listing_source" if source_only else "catalog_review",
        "source_schema": schema,
        "source_name": source.get("source_name") or f"审核批次 #{identity}",
        "root_source_import_id": root if listing else None,
        "parent_import_id": source.get("parent_import_id"),
        "review_path": path,
        "source_path": f"/catalog/production-sources?entry=amazon-listing&listing={root}"
        if listing
        else None,
        "approved_catalog_version_number": row.get("approved_catalog_version_number"),
        "report_selection": bool(report),
        "scope_ids": sorted(int(s) for s in scopes),
        "actor": row.get("actor"),
        "updated_at": updated,
    }


def require_review_candidate(
    connection: Connection, site_id: int, import_id: int
) -> None:
    from app.api.errors import ApiError

    payload = connection.scalar(
        sa.text(
            "SELECT p.evidence_payload_json FROM catalog_imports i JOIN catalog_export_payloads p ON p.export_id=i.export_id AND p.site_id=i.site_id WHERE i.id=:id AND i.site_id=:site"
        ),
        {"id": import_id, "site": site_id},
    )
    source = source_payload(payload)
    if (
        source.get("report_selection") is not None
        and source["report_selection"].get("version") != 1
    ):
        raise ApiError(
            409,
            "report_selection_unknown",
            "此报表来源格式版本不能由当前程序修改，请保留原批次并联系管理员。",
        )
    if source.get("source_schema") not in {None, "amazon_listing_v1"}:
        raise ApiError(
            409,
            "catalog_source_unknown",
            "此来源格式版本尚不支持修改，请保留原批次并联系管理员。",
        )
    if source.get("source_schema") == "amazon_listing_v1" and not any(
        s.get("record_type") == "variant" and s.get("sku_row_key")
        for s in source.get("selections", [])
    ):
        raise ApiError(
            409,
            "catalog_source_requires_selection",
            "这是原始商品清单，请先打开清单选择具体规格并保存审核候选；原始清单不能直接提交或批准。",
        )


def listing_progress(
    connection: Connection, site_id: int, root_ids: list[int]
) -> dict[int, dict[str, Any]]:
    if not root_ids:
        return {}
    checks = (
        connection.execute(
            sa.text("""
        SELECT c.id,c.import_id,c.result_json,i.status,v.version_number,
               p.evidence_payload_json
        FROM catalog_platform_checks c JOIN catalog_imports i ON i.id=c.import_id AND i.site_id=c.site_id
        JOIN catalog_export_payloads p ON p.export_id=i.export_id AND p.site_id=i.site_id
        LEFT JOIN product_catalog_versions v ON v.source_import_id=i.id AND v.site_id=i.site_id
        WHERE c.site_id=:site AND (i.id IN :roots OR
          CAST(JSON_UNQUOTE(JSON_EXTRACT(p.evidence_payload_json,'$.production_source.parent_import_id')) AS UNSIGNED) IN :roots)
    """).bindparams(sa.bindparam("roots", expanding=True)),
            {"site": site_id, "roots": root_ids},
        )
        .mappings()
        .all()
    )
    approved = [int(c["import_id"]) for c in checks if c["status"] == "approved"]
    decisions: dict[int, list[dict[str, Any]]] = {}
    if approved:
        for row in connection.execute(
            sa.text("""
          SELECT r.import_id,r.section,r.row_key,r.projection_state,r.payload_json
          FROM catalog_import_rows r JOIN catalog_imports i ON i.id=r.import_id AND i.site_id=r.site_id
          WHERE r.site_id=:site AND r.import_id IN :ids AND r.section IN ('skus','mappings')
          AND r.workflow_revision=(SELECT MAX(p.workflow_revision) FROM catalog_import_rows p
              WHERE p.import_id=r.import_id AND p.section=r.section AND p.workflow_revision<=i.workflow_revision)
        """).bindparams(sa.bindparam("ids", expanding=True)),
            {"site": site_id, "ids": approved},
        ).mappings():
            value = dict(row)
            value["payload"] = (
                json.loads(value.pop("payload_json"))
                if isinstance(row["payload_json"], str)
                else value.pop("payload_json")
            )
            decisions.setdefault(int(row["import_id"]), []).append(value)
    result: dict[int, dict[str, Any]] = {
        root: {"rows": {}, "candidates": []} for root in root_ids
    }
    # Preserve chronological decisions without sorting large JSON payloads in MySQL.
    for check in sorted(checks, key=lambda row: int(row["id"])):
        source = source_payload(check["evidence_payload_json"])
        root = int(source.get("parent_import_id") or check["import_id"])
        if root not in result:
            continue
        candidate = {
            "import_id": int(check["import_id"]),
            "status": check["status"],
            "version_number": check["version_number"],
            "review_path": f"/catalog/imports/{check['import_id']}",
        }
        if (
            any(s.get("sku_row_key") for s in source.get("selections", []))
            and candidate not in result[root]["candidates"]
        ):
            result[root]["candidates"].append(candidate)
        if check["status"] in {"withdrawn", "rejected", "superseded"}:
            continue
        snapshot = (
            json.loads(check["result_json"])
            if isinstance(check["result_json"], str)
            else check["result_json"]
        )
        for selection in snapshot.get("selections", []):
            row_id = selection.get("row_id")
            if not row_id:
                continue
            state = "in_candidate"
            if snapshot.get("source_only") and selection.get("record_type") == "parent":
                state = "parent_confirmed"
            elif check["status"] == "approved":
                rows = decisions.get(int(check["import_id"]), [])
                sku = next(
                    (
                        r
                        for r in rows
                        if r["section"] == "skus"
                        and r["row_key"] == selection.get("sku_row_key")
                        and r["projection_state"] == "included"
                    ),
                    None,
                )
                maps = [
                    r["payload"]
                    for r in rows
                    if r["section"] == "mappings"
                    and r["projection_state"] == "included"
                    and str(r["payload"].get("seller_account"))
                    == str(selection.get("scope_id"))
                    and r["payload"].get("seller_sku_preview")
                    == selection.get("seller_sku")
                ]
                state = "identity_approved" if sku else "needs_attention"
                if any(m.get("identity_decision") == "excluded" for m in maps):
                    state = "excluded"
                elif sku and any(
                    m.get("identity_decision") == "mapped"
                    and m.get("target_sku_row_key") == sku["row_key"]
                    for m in maps
                ):
                    state = "channel_approved"
            value = {
                "state": state,
                "import_id": int(check["import_id"]),
                "status": check["status"],
                "version_number": check["version_number"],
            }
            previous = result[root]["rows"].get(row_id)
            # A newer draft never erases a prior approval; both links remain in history.
            if (
                previous is None
                or previous["state"]
                not in {
                    "identity_approved",
                    "channel_approved",
                    "excluded",
                    "parent_confirmed",
                }
                or state in {"channel_approved", "excluded"}
            ):
                result[root]["rows"][row_id] = value
                raw = next(
                    (
                        r
                        for r in source.get("listing_rows", [])
                        if r["row_id"] == row_id
                    ),
                    None,
                )
                if raw:
                    for duplicate in source["listing_rows"]:
                        if listing_group(duplicate) == listing_group(raw):
                            result[root]["rows"][duplicate["row_id"]] = value
        candidate = {
            "import_id": int(check["import_id"]),
            "status": check["status"],
            "version_number": check["version_number"],
            "review_path": f"/catalog/imports/{check['import_id']}",
        }
        if (
            not snapshot.get("source_only")
            and candidate not in result[root]["candidates"]
        ):
            result[root]["candidates"].append(candidate)
    return result


def listing_group(row: dict[str, Any]) -> tuple[str, ...]:
    return tuple(
        str(row.get(key, ""))
        for key in ("sheet", "seller_sku", "asin", "child_asin", "parent_asin", "fnsku")
    )


def unprocessed_groups(rows: list[dict[str, Any]], states: dict[str, Any]) -> int:
    return len(
        {
            listing_group(r)
            for r in rows
            if states.get(r["row_id"], {}).get("state") in {None, "needs_attention"}
        }
    )


def select_tasks(
    records: list[dict[str, Any]],
    *,
    kind: str,
    status: str | None,
    scope_id: int | None,
    query: str,
    page: int,
    page_size: int,
) -> dict[str, Any]:
    """Filter before pagination; every saved review is independent of style membership."""
    tasks = []
    for record in records:
        if record.get("record_kind") in {"generation_job", "style_change"}:
            item = dict(record)
            if isinstance(item.get("updated_at"), datetime):
                item["updated_at"] = item["updated_at"].replace(tzinfo=UTC).isoformat()
        elif record["status"] not in ACTIVE:
            continue
        else:
            item = import_metadata(record)
        item["remaining_group_count"] = record.get("source_remaining", 0)
        if (
            item["record_kind"] == "listing_source"
            and record.get("source_remaining") == 0
        ):
            continue
        item["kind"] = (
            "attention"
            if item["record_kind"] in {"listing_source", "generation_job"}
            or item.get("stale")
            or item["status"] in {"uploaded", "parsing", "parse_failed", "rejected"}
            else "review"
        )
        if status and item["status"] != status:
            continue
        if scope_id is not None and scope_id not in item["scope_ids"]:
            continue
        if (
            query
            and query.casefold()
            not in f"{item['source_name']} {item.get('import_id', '')} {record.get('search_text', '')}".casefold()
        ):
            continue
        item.setdefault("task_id", f"import:{item.get('import_id')}")
        tasks.append(item)
    tasks.sort(
        key=lambda t: (str(t.get("updated_at") or ""), t["task_id"]), reverse=True
    )
    counts = {
        key: sum(t["kind"] == key for t in tasks) for key in ["review", "attention"]
    }
    groups = {
        "review_batches": sum(
            t["record_kind"] == "catalog_review" and t["kind"] == "review"
            for t in tasks
        ),
        "style_change_drafts": sum(t["record_kind"] == "style_change" for t in tasks),
        "listing_groups": sum(
            int(t["remaining_group_count"])
            for t in tasks
            if t["record_kind"] == "listing_source"
        ),
        "generation_jobs": sum(t["record_kind"] == "generation_job" for t in tasks),
        "failed_batches": sum(
            t["record_kind"] == "catalog_review" and t["kind"] == "attention"
            for t in tasks
        ),
    }
    chosen = [t for t in tasks if kind == "all" or t["kind"] == kind]
    offset = (page - 1) * page_size
    return {
        "items": chosen[offset : offset + page_size],
        "total_items": len(chosen),
        "counts": counts,
        "group_counts": groups,
        "page": page,
        "page_size": page_size,
        "has_next": len(chosen) > offset + page_size,
    }


def list_tasks(
    engine: Engine,
    *,
    site_id: int,
    kind: str,
    status: str | None,
    scope_id: int | None,
    query: str,
    page: int,
    page_size: int,
    updated_from: date | None = None,
    updated_to: date | None = None,
) -> dict[str, Any]:
    with (
        engine.connect().execution_options(
            isolation_level="REPEATABLE READ"
        ) as connection,
        connection.begin(),
    ):
        records = [
            dict(r)
            for r in connection.execute(
                sa.text(
                    IMPORT_SELECT
                    + " WHERE i.site_id=:site_id AND i.status IN ('uploaded','parsing','parse_failed','needs_attention','validated','ready_for_approval','rejected') ORDER BY i.updated_at DESC,i.id DESC"
                ),
                {"site_id": site_id},
            ).mappings()
        ]
        row_search: dict[int, list[str]] = {}
        if records:
            for row in connection.execute(
                sa.text("""
              SELECT r.import_id,r.payload_json FROM catalog_import_rows r
              JOIN catalog_imports i ON i.id=r.import_id AND i.site_id=r.site_id
              WHERE r.site_id=:site AND r.import_id IN :ids
              AND r.workflow_revision=(SELECT MAX(p.workflow_revision) FROM catalog_import_rows p
                  WHERE p.import_id=r.import_id AND p.section=r.section AND p.workflow_revision<=i.workflow_revision)
            """).bindparams(sa.bindparam("ids", expanding=True)),
                {"site": site_id, "ids": [r["import_id"] for r in records]},
            ).mappings():
                row_search.setdefault(int(row["import_id"]), []).append(
                    str(row["payload_json"])
                )
        roots = [
            r["import_id"]
            for r in records
            if import_metadata(r)["record_kind"] == "listing_source"
        ]
        progress = listing_progress(connection, site_id, roots)
        # JSON payloads are existing evidence. Search is restricted to this site's authorized batch metadata.
        for record in records:
            source = source_payload(record.get("evidence_payload_json"))
            record["search_text"] = " ".join(
                row_search.get(record["import_id"], [])
            ) + json.dumps(
                source.get("rows", []) + source.get("listing_rows", []),
                ensure_ascii=False,
            )
            if record["import_id"] in progress:
                states = progress[record["import_id"]]["rows"]
                record["source_remaining"] = unprocessed_groups(
                    source.get("listing_rows", []), states
                )
        jobs = connection.execute(
            sa.text("""
          SELECT j.id,j.resource_id,j.status,j.job_revision,j.updated_at,u.username_normalized AS actor,
                 t.report_source_scope_id AS scope_id
          FROM catalog_jobs j JOIN catalog_exports e ON e.id=j.resource_id AND e.site_id=j.site_id
          LEFT JOIN fact_snapshot_tuples t ON t.id=e.fact_snapshot_tuple_id AND t.site_id=e.site_id
          LEFT JOIN users u ON u.id=e.created_by_user_id
          WHERE j.site_id=:site AND j.job_kind='catalog_export' AND j.resource_kind='catalog_export'
            AND j.status IN ('queued','running','failed')
        """),
            {"site": site_id},
        ).mappings()
        for job in jobs:
            records.append(
                {
                    "record_kind": "generation_job",
                    "task_id": f"job:{job['id']}",
                    "source_name": f"目录生成任务 #{job['id']}",
                    "status": job["status"],
                    "scope_ids": [int(job["scope_id"])] if job["scope_id"] else [],
                    "actor": job["actor"],
                    "updated_at": job["updated_at"],
                    "workflow_revision": int(job["job_revision"]),
                    "review_path": f"/catalog/maintenance?export_id={job['resource_id']}",
                    "source_kind": "job",
                }
            )
        drafts = connection.execute(
            sa.text("""
            SELECT d.id,d.style_id,d.draft_revision,d.updated_at,d.proposed_standard_name,
                   s.style_code,c.display_name AS category_name,u.username_normalized AS actor,
                   d.base_catalog_publication_revision<>p.catalog_publication_revision AS stale
            FROM catalog_style_change_drafts d
            JOIN product_catalog_style_members m ON m.catalog_version_id=d.base_catalog_version_id
                AND m.site_id=d.site_id AND m.style_id=d.style_id
            JOIN product_style_revisions s ON s.id=m.style_revision_id AND s.site_id=m.site_id
            JOIN users u ON u.id=d.created_by_user_id
            LEFT JOIN product_categories c ON c.id=d.proposed_category_id AND c.site_id=d.site_id
            JOIN product_catalog_publications p ON p.site_id=d.site_id
            WHERE d.site_id=:site AND d.status='draft'
        """),
            {"site": site_id},
        ).mappings()
        for draft in drafts:
            records.append(
                {
                    "record_kind": "style_change",
                    "task_id": f"style-change:{draft['id']}",
                    "source_name": f"名称／分类 · {draft['style_code']} · 草稿#{draft['id']}",
                    "search_text": f"{draft['proposed_standard_name']} {draft['category_name'] or ''}",
                    "status": "draft",
                    "scope_ids": [],
                    "actor": draft["actor"],
                    "updated_at": draft["updated_at"],
                    "workflow_revision": int(draft["draft_revision"]),
                    "stale": bool(draft["stale"]),
                    "review_path": f"/catalog/styles/{draft['style_id']}?change_draft={draft['id']}",
                    "source_kind": "style_change",
                }
            )
        if updated_from or updated_to:
            records = [
                r
                for r in records
                if (not updated_from or r["updated_at"].date() >= updated_from)
                and (not updated_to or r["updated_at"].date() <= updated_to)
            ]
        result = select_tasks(
            records,
            kind=kind,
            status=status,
            scope_id=scope_id,
            query=query.strip(),
            page=page,
            page_size=page_size,
        )
        pointer = (
            connection.execute(
                sa.text(
                    "SELECT current_catalog_version_id,catalog_publication_revision FROM product_catalog_publications WHERE site_id=:site"
                ),
                {"site": site_id},
            )
            .mappings()
            .one_or_none()
        )
        result["baseline"] = (
            dict(pointer)
            if pointer
            else {"current_catalog_version_id": None, "catalog_publication_revision": 0}
        )
        result["complete"] = True
        return result
