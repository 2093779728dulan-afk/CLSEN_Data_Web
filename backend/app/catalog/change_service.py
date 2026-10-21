# ruff: noqa: E501
"""Isolated draft, preview, and approval flow for ordinary style changes."""

from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime
from uuid import UUID

import sqlalchemy as sa
from sqlalchemy.engine import Connection, Engine

from app.catalog.approval import CatalogPublicationConflict
from app.catalog.canonical_json import CanonicalValue, canonical_json_bytes
from app.catalog.category_service import category_parent_snapshot
from app.catalog.commands import semantic_command_digest
from app.catalog.import_repository import (
    CatalogCommandResult,
    MySqlCatalogImportRepository,
)


class CatalogStyleChangeError(RuntimeError):
    code = "catalog_style_change_invalid"

    def __init__(self, code: str | None = None) -> None:
        if code is not None:
            self.code = code
        super().__init__(self.code)


def _clean_name(value: str) -> str:
    result = value.strip()
    if not result or len(result) > 255:
        raise CatalogStyleChangeError()
    return result


def _result(command: CatalogCommandResult) -> dict[str, CanonicalValue]:
    return command.safe_result


class MySqlCatalogStyleChangeService:
    def __init__(self, engine: Engine) -> None:
        self._engine = engine

    def create_draft(
        self,
        *,
        site_id: int,
        style_id: int,
        actor_user_id: int,
        operation_token: UUID,
        expected_catalog_publication_revision: int,
        expected_style_revision: int,
        standard_name: str,
        category_action: str,
        category_id: int | None,
    ) -> dict[str, CanonicalValue]:
        name = _clean_name(standard_name)
        if category_action not in {"keep", "clear", "set"}:
            raise CatalogStyleChangeError()
        if (category_action == "set") != (category_id is not None):
            raise CatalogStyleChangeError()
        body: dict[str, CanonicalValue] = {
            "expected_catalog_publication_revision": expected_catalog_publication_revision,
            "expected_style_revision": expected_style_revision,
            "standard_name": name,
            "category_action": category_action,
            "category_id": category_id,
        }
        digest = semantic_command_digest(
            route="catalog_style_change_create",
            resource_id=style_id,
            body=body,
            operation_token=operation_token,
        )

        def effect(connection: Connection) -> tuple[int, dict[str, CanonicalValue]]:
            pointer = (
                connection.execute(
                    sa.text(
                        "SELECT current_catalog_version_id, catalog_publication_revision FROM product_catalog_publications WHERE site_id=:site_id FOR UPDATE"
                    ),
                    {"site_id": site_id},
                )
                .mappings()
                .one_or_none()
            )
            if (
                pointer is None
                or int(pointer["catalog_publication_revision"])
                != expected_catalog_publication_revision
                or pointer["current_catalog_version_id"] is None
            ):
                raise CatalogPublicationConflict()
            version_id = int(pointer["current_catalog_version_id"])
            current = (
                connection.execute(
                    sa.text("""
                SELECT revisions.revision, revisions.standard_name,
                       members.category_id, members.category_code_snapshot,
                       members.category_name_snapshot
                FROM product_catalog_style_members AS members
                INNER JOIN product_style_revisions AS revisions ON revisions.id=members.style_revision_id
                WHERE members.catalog_version_id=:version_id AND members.site_id=:site_id
                  AND members.style_id=:style_id
            """),
                    {
                        "version_id": version_id,
                        "site_id": site_id,
                        "style_id": style_id,
                    },
                )
                .mappings()
                .one_or_none()
            )
            if current is None:
                raise CatalogStyleChangeError("catalog_style_not_found")
            if int(current["revision"]) != expected_style_revision:
                raise CatalogStyleChangeError("catalog_style_revision_conflict")
            if category_action == "set":
                category = (
                    connection.execute(
                        sa.text(
                            "SELECT id, code, display_name FROM product_categories WHERE id=:id AND site_id=:site_id AND status='enabled'"
                        ),
                        {"id": category_id, "site_id": site_id},
                    )
                    .mappings()
                    .one_or_none()
                )
                if category is None:
                    raise CatalogStyleChangeError("catalog_category_not_selectable")
            inserted = connection.execute(
                sa.text("""
                INSERT INTO catalog_style_change_drafts (
                    site_id, style_id, base_catalog_version_id, base_style_revision,
                    base_catalog_publication_revision, proposed_standard_name,
                    category_action, proposed_category_id, created_by_user_id
                ) VALUES (:site_id,:style_id,:version_id,:style_revision,
                    :publication_revision,:name,:action,:category_id,:actor)
            """),
                {
                    "site_id": site_id,
                    "style_id": style_id,
                    "version_id": version_id,
                    "style_revision": expected_style_revision,
                    "publication_revision": expected_catalog_publication_revision,
                    "name": name,
                    "action": category_action,
                    "category_id": category_id,
                    "actor": actor_user_id,
                },
            )
            draft_id = int(inserted.lastrowid or 0)
            return 201, {"draft_id": draft_id, "draft_revision": 1, "status": "draft"}

        with self._engine.begin() as connection:
            command = MySqlCatalogImportRepository._execute_command(
                connection,
                operation_token=operation_token,
                operation_kind="style_change_create",
                operation_digest=digest,
                site_id=site_id,
                actor_user_id=actor_user_id,
                resource_id=style_id,
                effect=effect,
            )
        return _result(command)

    def preview(self, *, site_id: int, draft_id: int) -> dict[str, object]:
        with self._engine.connect() as connection:
            row = (
                connection.execute(
                    sa.text("""
                SELECT drafts.id, drafts.style_id, drafts.base_catalog_version_id,
                       drafts.base_catalog_publication_revision, drafts.base_style_revision,
                       drafts.draft_revision, drafts.proposed_standard_name,
                       drafts.category_action, drafts.proposed_category_id, drafts.status,
                       revisions.style_code, revisions.standard_name AS old_standard_name,
                       members.category_id AS old_category_id,
                       members.category_code_snapshot AS old_category_code,
                       members.category_name_snapshot AS old_category_name,
                       members.category_parent_snapshot AS old_parent_snapshot,
                       categories.code AS proposed_category_code,
                       categories.display_name AS proposed_category_name,
                       parent.code AS parent_code, parent.display_name AS parent_name
                FROM catalog_style_change_drafts AS drafts
                INNER JOIN product_catalog_style_members AS members
                  ON members.catalog_version_id=drafts.base_catalog_version_id
                 AND members.site_id=drafts.site_id AND members.style_id=drafts.style_id
                INNER JOIN product_style_revisions AS revisions ON revisions.id=members.style_revision_id
                LEFT JOIN product_categories AS categories
                  ON categories.id=drafts.proposed_category_id AND categories.site_id=drafts.site_id
                LEFT JOIN product_categories AS parent ON parent.id=categories.parent_category_id AND parent.site_id=categories.site_id
                WHERE drafts.id=:draft_id AND drafts.site_id=:site_id
            """),
                    {"draft_id": draft_id, "site_id": site_id},
                )
                .mappings()
                .one_or_none()
            )
        if row is None:
            raise CatalogStyleChangeError("catalog_style_change_not_found")
        old_parent = row["old_parent_snapshot"]
        if isinstance(old_parent, str):
            old_parent = json.loads(old_parent)
        old_parent_name = old_parent.get("display_name") if old_parent else None
        action = str(row["category_action"])
        if action == "keep":
            new_category = {
                "category_id": row["old_category_id"],
                "code": row["old_category_code"],
                "display_name": row["old_category_name"],
                "parent_name": old_parent_name,
            }
        elif action == "clear":
            new_category = {"category_id": None, "code": None, "display_name": None}
        else:
            new_category = {
                "category_id": row["proposed_category_id"],
                "code": row["proposed_category_code"],
                "display_name": row["proposed_category_name"],
                "parent_name": row["parent_name"],
            }
        return {
            "draft_id": int(row["id"]),
            "draft_revision": int(row["draft_revision"]),
            "status": str(row["status"]),
            "style_id": int(row["style_id"]),
            "style_code": str(row["style_code"]),
            "base_catalog_version_id": int(row["base_catalog_version_id"]),
            "base_catalog_publication_revision": int(
                row["base_catalog_publication_revision"]
            ),
            "base_style_revision": int(row["base_style_revision"]),
            "before": {
                "standard_name": str(row["old_standard_name"]),
                "category": {
                    "category_id": row["old_category_id"],
                    "code": row["old_category_code"],
                    "display_name": row["old_category_name"],
                    "parent_name": old_parent_name,
                },
            },
            "after": {
                "standard_name": str(row["proposed_standard_name"]),
                "category": new_category,
            },
        }

    def approve(
        self,
        *,
        site_id: int,
        draft_id: int,
        actor_user_id: int,
        operation_token: UUID,
        expected_draft_revision: int,
        expected_catalog_publication_revision: int,
        reason: str,
    ) -> dict[str, CanonicalValue]:
        reason = reason.strip()
        if len(reason) < 3 or len(reason) > 500:
            raise CatalogStyleChangeError()
        body: dict[str, CanonicalValue] = {
            "expected_draft_revision": expected_draft_revision,
            "expected_catalog_publication_revision": expected_catalog_publication_revision,
            "reason": reason,
        }
        digest = semantic_command_digest(
            route="catalog_style_change_approve",
            resource_id=draft_id,
            body=body,
            operation_token=operation_token,
        )

        def effect(connection: Connection) -> tuple[int, dict[str, CanonicalValue]]:
            pointer = (
                connection.execute(
                    sa.text(
                        "SELECT current_catalog_version_id,catalog_publication_revision FROM product_catalog_publications WHERE site_id=:site_id FOR UPDATE"
                    ),
                    {"site_id": site_id},
                )
                .mappings()
                .one_or_none()
            )
            draft = (
                connection.execute(
                    sa.text(
                        "SELECT * FROM catalog_style_change_drafts WHERE id=:draft_id AND site_id=:site_id FOR UPDATE"
                    ),
                    {"draft_id": draft_id, "site_id": site_id},
                )
                .mappings()
                .one_or_none()
            )
            if draft is None:
                raise CatalogStyleChangeError("catalog_style_change_not_found")
            if (
                draft["status"] != "draft"
                or int(draft["draft_revision"]) != expected_draft_revision
            ):
                raise CatalogStyleChangeError("catalog_style_change_revision_conflict")
            if (
                pointer is None
                or pointer["current_catalog_version_id"] is None
                or int(pointer["catalog_publication_revision"])
                != expected_catalog_publication_revision
                or int(pointer["current_catalog_version_id"])
                != int(draft["base_catalog_version_id"])
                or int(draft["base_catalog_publication_revision"])
                != expected_catalog_publication_revision
            ):
                raise CatalogPublicationConflict()
            base_id, style_id = (
                int(draft["base_catalog_version_id"]),
                int(draft["style_id"]),
            )
            member = (
                connection.execute(
                    sa.text("""
                SELECT members.style_revision_id, members.category_id,
                       members.category_code_snapshot, members.category_name_snapshot, members.category_parent_snapshot,
                       revisions.revision, revisions.style_code, revisions.style_key_sha256,
                       revisions.style_key_bytes, revisions.standard_name, revisions.status
                FROM product_catalog_style_members AS members
                INNER JOIN product_style_revisions AS revisions ON revisions.id=members.style_revision_id
                WHERE members.catalog_version_id=:version_id AND members.site_id=:site_id AND members.style_id=:style_id
            """),
                    {"version_id": base_id, "site_id": site_id, "style_id": style_id},
                )
                .mappings()
                .one()
            )
            if int(member["revision"]) != int(draft["base_style_revision"]):
                raise CatalogStyleChangeError("catalog_style_change_revision_conflict")
            action = str(draft["category_action"])
            category_id, category_code, category_name = (
                member["category_id"],
                member["category_code_snapshot"],
                member["category_name_snapshot"],
            )
            parent_snapshot = member["category_parent_snapshot"]
            if action == "clear":
                parent_snapshot = None
                category_id = category_code = category_name = None
            elif action == "set":
                category = (
                    connection.execute(
                        sa.text(
                            "SELECT id,code,display_name FROM product_categories WHERE id=:id AND site_id=:site_id AND status='enabled' FOR UPDATE"
                        ),
                        {"id": draft["proposed_category_id"], "site_id": site_id},
                    )
                    .mappings()
                    .one_or_none()
                )
                if category is None:
                    raise CatalogStyleChangeError("catalog_category_not_selectable")
                category_id, category_code, category_name = (
                    int(category["id"]),
                    str(category["code"]),
                    str(category["display_name"]),
                )
            if action == "set":
                parent_snapshot = category_parent_snapshot(
                    connection, site_id, category_id
                )
            new_name = str(draft["proposed_standard_name"])
            style_revision_id = int(member["style_revision_id"])
            style_revision = int(member["revision"])
            if new_name != str(member["standard_name"]):
                style_revision += 1
                inserted_revision = connection.execute(
                    sa.text("""
                    INSERT INTO product_style_revisions (
                        site_id,style_id,revision,style_code,style_key_sha256,style_key_bytes,
                        standard_name,status,change_reason,actor_user_id,source_import_id,source_command_token
                    ) VALUES (:site_id,:style_id,:revision,:style_code,:key_sha,:key_bytes,
                        :name,:status,:reason,:actor,NULL,:token)
                """),
                    {
                        "site_id": site_id,
                        "style_id": style_id,
                        "revision": style_revision,
                        "style_code": member["style_code"],
                        "key_sha": member["style_key_sha256"],
                        "key_bytes": member["style_key_bytes"],
                        "name": new_name,
                        "status": member["status"],
                        "reason": reason,
                        "actor": actor_user_id,
                        "token": operation_token.bytes,
                    },
                )
                style_revision_id = int(inserted_revision.lastrowid or 0)
                updated = connection.execute(
                    sa.text(
                        "UPDATE product_styles SET standard_name=:name,current_revision=:next WHERE id=:style_id AND site_id=:site_id AND current_revision=:expected"
                    ),
                    {
                        "name": new_name,
                        "next": style_revision,
                        "style_id": style_id,
                        "site_id": site_id,
                        "expected": int(member["revision"]),
                    },
                )
                if updated.rowcount != 1:
                    raise CatalogStyleChangeError(
                        "catalog_style_change_revision_conflict"
                    )
            base = (
                connection.execute(
                    sa.text(
                        "SELECT * FROM product_catalog_versions WHERE id=:id AND site_id=:site_id"
                    ),
                    {"id": base_id, "site_id": site_id},
                )
                .mappings()
                .one()
            )
            version_number = int(
                connection.scalar(
                    sa.text(
                        "SELECT COALESCE(MAX(version_number),0)+1 FROM product_catalog_versions WHERE site_id=:site_id"
                    ),
                    {"site_id": site_id},
                )
            )
            diff_payload = {
                "style_id": style_id,
                "before_name": str(member["standard_name"]),
                "after_name": new_name,
                "category_id": category_id,
                "category_code": category_code,
                "category_name": category_name,
                "parent_snapshot": parent_snapshot,
            }
            diff_digest = hashlib.sha256(canonical_json_bytes(diff_payload)).digest()
            approval_digest = hashlib.sha256(
                diff_digest + operation_token.bytes
            ).digest()
            inserted_version = connection.execute(
                sa.text("""
                INSERT INTO product_catalog_versions (
                    site_id,version_number,base_catalog_version_id,workbook_schema_version,
                    normalization_manifest_id,fact_snapshot_tuple_id,source_import_id,
                    validation_run_id,approval_digest,diff_digest,risk,status,
                    approved_by_user_id,approved_at,approval_reason
                ) VALUES (:site_id,:number,:base_id,:workbook,:manifest,:fact,:source_import,
                    :validation,:approval_digest,:diff_digest,'normal','ready',:actor,:approved_at,:reason)
            """),
                {
                    "site_id": site_id,
                    "number": version_number,
                    "base_id": base_id,
                    "workbook": base["workbook_schema_version"],
                    "manifest": base["normalization_manifest_id"],
                    "fact": base["fact_snapshot_tuple_id"],
                    "source_import": base["source_import_id"],
                    "validation": base["validation_run_id"],
                    "approval_digest": approval_digest,
                    "diff_digest": diff_digest,
                    "actor": actor_user_id,
                    "approved_at": datetime.now(UTC).replace(tzinfo=None),
                    "reason": reason,
                },
            )
            version_id = int(inserted_version.lastrowid or 0)
            connection.execute(
                sa.text("""
                INSERT INTO product_catalog_style_members (catalog_version_id,site_id,style_id,style_revision_id,category_id,category_code_snapshot,category_name_snapshot,category_parent_snapshot,category_snapshot_recorded)
                SELECT :new_id,site_id,style_id,style_revision_id,category_id,category_code_snapshot,category_name_snapshot,category_parent_snapshot,TRUE
                FROM product_catalog_style_members WHERE catalog_version_id=:base_id AND style_id<>:style_id
            """),
                {"new_id": version_id, "base_id": base_id, "style_id": style_id},
            )
            connection.execute(
                sa.text(
                    "INSERT INTO product_catalog_style_members (catalog_version_id,site_id,style_id,style_revision_id,category_id,category_code_snapshot,category_name_snapshot,category_parent_snapshot,category_snapshot_recorded) VALUES (:version_id,:site_id,:style_id,:revision_id,:category_id,:category_code,:category_name,:parent_snapshot,TRUE)"
                ),
                {
                    "version_id": version_id,
                    "site_id": site_id,
                    "style_id": style_id,
                    "revision_id": style_revision_id,
                    "category_id": category_id,
                    "category_code": category_code,
                    "category_name": category_name,
                    "parent_snapshot": parent_snapshot,
                },
            )
            connection.execute(
                sa.text(
                    "INSERT INTO product_catalog_sku_members (catalog_version_id,site_id,sku_id,sku_revision_id,style_id) SELECT :new_id,site_id,sku_id,sku_revision_id,style_id FROM product_catalog_sku_members WHERE catalog_version_id=:base_id"
                ),
                {"new_id": version_id, "base_id": base_id},
            )
            connection.execute(
                sa.text(
                    "INSERT INTO product_catalog_mappings (catalog_version_id,site_id,report_source_scope_id,marketplace_scope_code,seller_sku_match_sha256,seller_sku_match_bytes,sku_id,decision_source,actor_user_id,evidence_digest) SELECT :new_id,site_id,report_source_scope_id,marketplace_scope_code,seller_sku_match_sha256,seller_sku_match_bytes,sku_id,decision_source,actor_user_id,evidence_digest FROM product_catalog_mappings WHERE catalog_version_id=:base_id"
                ),
                {"new_id": version_id, "base_id": base_id},
            )
            connection.execute(
                sa.text(
                    "INSERT INTO product_catalog_exclusions (catalog_version_id,site_id,report_source_scope_id,marketplace_scope_code,seller_sku_match_sha256,seller_sku_match_bytes,reason,actor_user_id,evidence_digest) SELECT :new_id,site_id,report_source_scope_id,marketplace_scope_code,seller_sku_match_sha256,seller_sku_match_bytes,reason,actor_user_id,evidence_digest FROM product_catalog_exclusions WHERE catalog_version_id=:base_id"
                ),
                {"new_id": version_id, "base_id": base_id},
            )
            next_publication = expected_catalog_publication_revision + 1
            updated_pointer = connection.execute(
                sa.text(
                    "UPDATE product_catalog_publications SET current_catalog_version_id=:version_id,catalog_publication_revision=:next WHERE site_id=:site_id AND catalog_publication_revision=:expected"
                ),
                {
                    "version_id": version_id,
                    "next": next_publication,
                    "site_id": site_id,
                    "expected": expected_catalog_publication_revision,
                },
            )
            if updated_pointer.rowcount != 1:
                raise CatalogPublicationConflict()
            connection.execute(
                sa.text(
                    "INSERT INTO product_catalog_publication_events (site_id,catalog_publication_revision,previous_catalog_version_id,catalog_version_id,event_kind,operation_token,actor_user_id,reason) VALUES (:site_id,:revision,:base_id,:version_id,'style_change',:token,:actor,:reason)"
                ),
                {
                    "site_id": site_id,
                    "revision": next_publication,
                    "base_id": base_id,
                    "version_id": version_id,
                    "token": operation_token.bytes,
                    "actor": actor_user_id,
                    "reason": reason,
                },
            )
            connection.execute(
                sa.text(
                    "UPDATE catalog_style_change_drafts SET status='approved',approved_catalog_version_id=:version_id,draft_revision=draft_revision+1 WHERE id=:draft_id AND site_id=:site_id AND draft_revision=:expected AND status='draft'"
                ),
                {
                    "version_id": version_id,
                    "draft_id": draft_id,
                    "site_id": site_id,
                    "expected": expected_draft_revision,
                },
            )
            safe: dict[str, CanonicalValue] = {
                "draft_id": draft_id,
                "draft_revision": expected_draft_revision + 1,
                "status": "approved",
                "catalog_version_id": version_id,
                "catalog_version_number": version_number,
                "catalog_publication_revision": next_publication,
            }
            audit = canonical_json_bytes(
                {"catalog_version_id": version_id, "style_id": style_id}
            )
            connection.execute(
                sa.text(
                    "INSERT INTO catalog_audit_events (site_id,actor_user_id,event_kind,resource_kind,resource_id,operation_token,safe_payload_json,event_digest) VALUES (:site_id,:actor,'catalog_style_changed','style',:style_id,:token,CAST(:payload AS JSON),:digest)"
                ),
                {
                    "site_id": site_id,
                    "actor": actor_user_id,
                    "style_id": style_id,
                    "token": operation_token.bytes,
                    "payload": audit.decode("utf-8"),
                    "digest": hashlib.sha256(operation_token.bytes + audit).digest(),
                },
            )
            return 200, safe

        with self._engine.begin() as connection:
            command = MySqlCatalogImportRepository._execute_command(
                connection,
                operation_token=operation_token,
                operation_kind="style_change_approve",
                operation_digest=digest,
                site_id=site_id,
                actor_user_id=actor_user_id,
                resource_id=draft_id,
                effect=effect,
            )
        return _result(command)


__all__ = ("CatalogStyleChangeError", "MySqlCatalogStyleChangeService")
