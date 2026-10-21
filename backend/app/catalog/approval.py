"""Atomic catalog approval and restore transactions."""

from __future__ import annotations

import hashlib
import unicodedata
from dataclasses import dataclass, replace
from datetime import UTC, datetime
from typing import Any
from uuid import UUID

import sqlalchemy as sa
from sqlalchemy.engine import Connection, Engine
from sqlalchemy.exc import IntegrityError

from app.catalog.canonical_json import CanonicalValue, canonical_json_bytes
from app.catalog.category_service import category_parent_snapshot
from app.catalog.commands import semantic_command_digest
from app.catalog.import_repository import (
    CatalogCommandResult,
    CatalogImportRepositoryError,
    MySqlCatalogImportRepository,
    _reconcile_draft_reservations,
)
from app.catalog.import_service import DraftRow
from app.catalog.normalization import catalog_identity_key_v1
from app.catalog.repository import CatalogReservationConflict, load_import_rows
from app.catalog.validation import CatalogApprovalEvaluation, evaluate_approval_rows


class CatalogApprovalError(RuntimeError):
    code = "catalog_approval_error"

    def __init__(self) -> None:
        super().__init__(self.code)


class CatalogProjectionStale(CatalogApprovalError):
    code = "catalog_projection_stale"


class CatalogPublicationConflict(CatalogApprovalError):
    code = "catalog_publication_revision_conflict"


class CatalogApprovalForbidden(CatalogApprovalError):
    code = "catalog_admin_required"


class CatalogApprovalValidationFailed(CatalogApprovalError):
    code = "catalog_validation_failed"


@dataclass(frozen=True, slots=True)
class CatalogApprovalPreview:
    projection_id: int
    projection_digest: bytes
    workflow_revision: int
    validation_run_id: int
    base_catalog_version_id: int | None
    catalog_publication_revision: int
    fact_snapshot_tuple_id: int
    risk: str
    diff_digest: bytes
    created_at: datetime
    expires_at: datetime
    included_row_count: int
    audit_only_row_count: int


@dataclass(frozen=True, slots=True)
class CatalogApprovalResult:
    catalog_version_id: int
    catalog_version_number: int
    catalog_publication_revision: int
    workflow_revision: int
    created_style_count: int
    created_sku_count: int
    created_reservation_count: int
    audit_only_row_count: int


@dataclass(frozen=True, slots=True)
class CatalogRestoreResult:
    catalog_version_id: int
    catalog_version_number: int
    catalog_publication_revision: int


def _mysql_datetime(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("timestamp must be timezone-aware")
    return value.astimezone(UTC).replace(tzinfo=None)


def _as_utc(value: object) -> datetime:
    if not isinstance(value, datetime):
        raise CatalogProjectionStale()
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


def _text(value: object, *, required: bool = True) -> str | None:
    if value is None and not required:
        return None
    if not isinstance(value, str) or not value:
        raise CatalogApprovalValidationFailed()
    return value


def _positive_id(value: object, *, required: bool = False) -> int | None:
    if value is None and not required:
        return None
    if not isinstance(value, (int, str)) or isinstance(value, bool):
        raise CatalogApprovalValidationFailed()
    try:
        parsed = int(value)
    except (TypeError, ValueError) as error:
        raise CatalogApprovalValidationFailed() from error
    if parsed <= 0:
        raise CatalogApprovalValidationFailed()
    return parsed


def _result_int(value: CanonicalValue) -> int:
    if not isinstance(value, int) or isinstance(value, bool):
        raise CatalogApprovalError()
    return value


def _json(value: dict[str, CanonicalValue]) -> str:
    return canonical_json_bytes(value).decode("utf-8")


def _existing_identity_values(
    connection: Connection,
    *,
    site_id: int,
) -> tuple[
    dict[int, tuple[str, str, str]],
    dict[int, tuple[int, str, str, str, str]],
]:
    styles = {
        int(row["id"]): (
            str(row["style_code"]),
            str(row["standard_name"]),
            str(row["status"]),
        )
        for row in connection.execute(
            sa.text(
                "SELECT id, style_code, standard_name, status "
                "FROM product_styles WHERE site_id = :site_id"
            ),
            {"site_id": site_id},
        ).mappings()
    }
    skus = {
        int(row["id"]): (
            int(row["style_id"]),
            str(row["internal_display_sku"]),
            str(row["standard_color"]),
            str(row["standard_size"]),
            str(row["status"]),
        )
        for row in connection.execute(
            sa.text(
                "SELECT id, style_id, internal_display_sku, standard_color, "
                "standard_size, status FROM product_skus WHERE site_id = :site_id"
            ),
            {"site_id": site_id},
        ).mappings()
    }
    return styles, skus


def _assert_permission(
    *,
    risk: str,
    actor_roles: frozenset[str],
    submitted_by_user_id: int,
    actor_user_id: int,
    reason: str,
) -> None:
    if risk == "high":
        if "admin" not in actor_roles or len(reason.strip()) < 10:
            raise CatalogApprovalForbidden()
        return
    if "admin" in actor_roles:
        return
    if "data_manager" not in actor_roles or submitted_by_user_id != actor_user_id:
        raise CatalogApprovalForbidden()


def _reserve(
    connection: Connection,
    *,
    site_id: int,
    key_kind: str,
    key_sha256: bytes,
    key_bytes: bytes,
    style_id: int | None,
    sku_id: int | None,
    first_revision_id: int,
) -> bool:
    inserted = connection.execute(
        sa.text(
            """
            INSERT IGNORE INTO product_identity_key_reservations (
                site_id, key_kind, key_sha256, key_bytes,
                style_id, sku_id, first_revision_id
            ) VALUES (
                :site_id, :kind, :digest, :key_bytes,
                :style_id, :sku_id, :first_revision_id
            )
            """
        ),
        {
            "site_id": site_id,
            "kind": key_kind,
            "digest": key_sha256,
            "key_bytes": key_bytes,
            "style_id": style_id,
            "sku_id": sku_id,
            "first_revision_id": first_revision_id,
        },
    )
    row = (
        connection.execute(
            sa.text(
                "SELECT style_id, sku_id FROM product_identity_key_reservations "
                "WHERE site_id = :site_id AND key_kind = :kind "
                "AND key_sha256 = :digest AND key_bytes = :key_bytes"
            ),
            {
                "site_id": site_id,
                "kind": key_kind,
                "digest": key_sha256,
                "key_bytes": key_bytes,
            },
        )
        .mappings()
        .one_or_none()
    )
    if row is None:
        raise CatalogReservationConflict()
    owner_style = None if row["style_id"] is None else int(row["style_id"])
    owner_sku = None if row["sku_id"] is None else int(row["sku_id"])
    if owner_style != style_id or owner_sku != sku_id:
        raise CatalogReservationConflict()
    return inserted.rowcount == 1


def _source_decision_key(
    connection: Connection,
    *,
    site_id: int,
    export_id: int,
    raw_sha256_ref: str,
) -> tuple[int, bytes, bytes]:
    if not raw_sha256_ref.startswith("sha256:") or len(raw_sha256_ref) != 71:
        raise CatalogApprovalValidationFailed()
    try:
        raw_digest = bytes.fromhex(raw_sha256_ref[7:])
    except ValueError as error:
        raise CatalogApprovalValidationFailed() from error
    rows = tuple(
        connection.execute(
            sa.text(
                """
                SELECT DISTINCT evidence.report_source_scope_id,
                       source_keys.seller_sku_match_sha256,
                       source_keys.seller_sku_match_bytes
                FROM catalog_source_refs AS refs
                INNER JOIN catalog_exports AS source_export
                  ON source_export.id = :export_id
                 AND source_export.site_id = refs.site_id
                INNER JOIN fact_snapshot_tuples AS source_tuple
                  ON source_tuple.id = source_export.fact_snapshot_tuple_id
                INNER JOIN publication_snapshots AS source_snapshot
                  ON source_snapshot.id = source_tuple.publication_snapshot_id
                INNER JOIN catalog_source_refs AS evidence_refs
                  ON evidence_refs.site_id = refs.site_id
                 AND evidence_refs.source_kind = refs.source_kind
                 AND evidence_refs.raw_sha256 = refs.raw_sha256
                INNER JOIN catalog_source_evidence AS evidence
                  ON evidence.seller_sku_ref_id = evidence_refs.id
                 AND evidence.site_id = refs.site_id
                 AND evidence.report_source_scope_id =
                     source_snapshot.report_source_scope_id
                INNER JOIN report_source_keys AS source_keys
                  ON source_keys.id = evidence.source_key_id
                 AND source_keys.site_id = evidence.site_id
                 AND source_keys.report_source_scope_id =
                     evidence.report_source_scope_id
                WHERE refs.site_id = :site_id
                  AND refs.resource_kind = 'export'
                  AND refs.resource_id = :export_id
                  AND refs.source_kind = 'seller_sku'
                  AND refs.raw_sha256 = :raw_digest
                ORDER BY evidence.report_source_scope_id,
                         source_keys.seller_sku_match_bytes
                """
            ),
            {
                "site_id": site_id,
                "export_id": export_id,
                "raw_digest": raw_digest,
            },
        ).mappings()
    )
    distinct = {
        (
            int(row["report_source_scope_id"]),
            bytes(row["seller_sku_match_sha256"]),
            bytes(row["seller_sku_match_bytes"]),
        )
        for row in rows
    }
    if len(distinct) != 1:
        raise CatalogApprovalValidationFailed()
    return next(iter(distinct))


def _evaluate_with_database(
    connection: Connection,
    *,
    rows: tuple[DraftRow, ...],
    site_id: int,
    export_id: int,
    current_catalog_id: int | None,
) -> CatalogApprovalEvaluation:
    style_values, sku_values = _existing_identity_values(
        connection,
        site_id=site_id,
    )
    evaluation = evaluate_approval_rows(
        rows,
        existing_style_values=style_values,
        existing_sku_values=sku_values,
    )
    if current_catalog_id is None or evaluation.risk == "high":
        return evaluation

    sku_rows = {
        row.row_key: row
        for row in evaluation.reachability.rows
        if row.section == "skus" and row.projection_state == "included"
    }
    for row in evaluation.reachability.rows:
        if row.section != "mappings":
            continue
        raw_sha = _text(row.payload.get("seller_sku_sha256")) or ""
        scope_id, match_sha, match_bytes = _source_decision_key(
            connection,
            site_id=site_id,
            export_id=export_id,
            raw_sha256_ref=raw_sha,
        )
        prior = (
            connection.execute(
                sa.text(
                    """
                    SELECT 'mapped' AS decision, sku_id, NULL AS reason
                    FROM product_catalog_mappings
                    WHERE catalog_version_id = :version_id
                      AND report_source_scope_id = :scope_id
                      AND seller_sku_match_sha256 = :match_sha
                      AND seller_sku_match_bytes = :match_bytes
                    UNION ALL
                    SELECT 'excluded' AS decision, NULL AS sku_id, reason
                    FROM product_catalog_exclusions
                    WHERE catalog_version_id = :version_id
                      AND report_source_scope_id = :scope_id
                      AND seller_sku_match_sha256 = :match_sha
                      AND seller_sku_match_bytes = :match_bytes
                    """
                ),
                {
                    "version_id": current_catalog_id,
                    "scope_id": scope_id,
                    "match_sha": match_sha,
                    "match_bytes": match_bytes,
                },
            )
            .mappings()
            .one_or_none()
        )
        if prior is None:
            continue
        decision = row.payload.get("identity_decision")
        if decision != prior["decision"]:
            return replace(evaluation, risk="high")
        if decision == "mapped":
            target_key = _text(row.payload.get("target_sku_row_key")) or ""
            target = sku_rows.get(target_key)
            target_id = (
                None
                if target is None
                else _positive_id(target.payload.get("system_sku_id"))
            )
            if target_id != int(prior["sku_id"]):
                return replace(evaluation, risk="high")
        elif (_text(row.payload.get("exclusion_reason")) or "").strip() != str(
            prior["reason"]
        ).strip():
            return replace(evaluation, risk="high")
    return evaluation


class MySqlCatalogApprovalRepository:
    def __init__(self, engine: Engine) -> None:
        self._engine = engine

    def approve(
        self,
        *,
        import_id: int,
        site_id: int,
        actor_user_id: int,
        actor_roles: frozenset[str],
        operation_token: UUID,
        expected_workflow_revision: int,
        expected_catalog_publication_revision: int,
        projection_id: int,
        projection_digest: bytes,
        reason: str,
        now: datetime,
    ) -> CatalogApprovalResult:
        if operation_token.version != 4 or len(projection_digest) != 32:
            raise ValueError("invalid approval command identity")
        body: dict[str, CanonicalValue] = {
            "expected_workflow_revision": expected_workflow_revision,
            "expected_catalog_publication_revision": (
                expected_catalog_publication_revision
            ),
            "projection_id": projection_id,
            "projection_digest": projection_digest.hex(),
            "reason": reason,
        }
        digest = semantic_command_digest(
            route="catalog_import_approve",
            resource_id=import_id,
            body=body,
            operation_token=operation_token,
        )

        def effect(connection: Connection) -> tuple[int, dict[str, CanonicalValue]]:
            return self._approve_effect(
                connection,
                import_id=import_id,
                site_id=site_id,
                actor_user_id=actor_user_id,
                actor_roles=actor_roles,
                operation_token=operation_token,
                expected_workflow_revision=expected_workflow_revision,
                expected_catalog_publication_revision=expected_catalog_publication_revision,
                projection_id=projection_id,
                projection_digest=projection_digest,
                reason=reason,
                now=now,
            )

        try:
            with self._engine.begin() as connection:
                command = MySqlCatalogImportRepository._execute_command(
                    connection,
                    operation_token=operation_token,
                    operation_kind="approve",
                    operation_digest=digest,
                    site_id=site_id,
                    actor_user_id=actor_user_id,
                    resource_id=import_id,
                    effect=effect,
                )
        except IntegrityError as error:
            raise CatalogReservationConflict() from error
        return self._approval_result(command)

    @staticmethod
    def _approval_result(command: CatalogCommandResult) -> CatalogApprovalResult:
        value = command.safe_result
        return CatalogApprovalResult(
            _result_int(value["catalog_version_id"]),
            _result_int(value["catalog_version_number"]),
            _result_int(value["catalog_publication_revision"]),
            _result_int(value["workflow_revision"]),
            _result_int(value["created_style_count"]),
            _result_int(value["created_sku_count"]),
            _result_int(value["created_reservation_count"]),
            _result_int(value["audit_only_row_count"]),
        )

    def _approve_effect(
        self,
        connection: Connection,
        *,
        import_id: int,
        site_id: int,
        actor_user_id: int,
        actor_roles: frozenset[str],
        operation_token: UUID,
        expected_workflow_revision: int,
        expected_catalog_publication_revision: int,
        projection_id: int,
        projection_digest: bytes,
        reason: str,
        now: datetime,
    ) -> tuple[int, dict[str, CanonicalValue]]:
        pointer = (
            connection.execute(
                sa.text(
                    "SELECT current_catalog_version_id, catalog_publication_revision "
                    "FROM product_catalog_publications "
                    "WHERE site_id = :site_id FOR UPDATE"
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
        ):
            raise CatalogPublicationConflict()
        current_catalog_id = (
            None
            if pointer["current_catalog_version_id"] is None
            else int(pointer["current_catalog_version_id"])
        )
        imported = (
            connection.execute(
                sa.text(
                    """
                    SELECT status, workflow_revision, validation_run_id,
                           submitted_by_user_id, base_catalog_version_id,
                           fact_snapshot_tuple_id, normalization_manifest_id,
                           export_id
                    FROM catalog_imports
                    WHERE id = :import_id AND site_id = :site_id FOR UPDATE
                    """
                ),
                {"import_id": import_id, "site_id": site_id},
            )
            .mappings()
            .one_or_none()
        )
        if imported is None:
            raise CatalogImportRepositoryError()
        if int(imported["workflow_revision"]) != expected_workflow_revision:
            raise CatalogProjectionStale()
        if (
            imported["status"] != "ready_for_approval"
            or imported["validation_run_id"] is None
            or imported["submitted_by_user_id"] is None
        ):
            raise CatalogProjectionStale()
        base_id = (
            None
            if imported["base_catalog_version_id"] is None
            else int(imported["base_catalog_version_id"])
        )
        if base_id != current_catalog_id:
            raise CatalogProjectionStale()
        projection = (
            connection.execute(
                sa.text(
                    """
                    SELECT workflow_revision, validation_run_id,
                           base_catalog_version_id, catalog_publication_revision,
                           fact_snapshot_tuple_id, risk, diff_digest,
                           projection_digest, created_at, expires_at
                    FROM catalog_approval_projections
                    WHERE id = :projection_id AND import_id = :import_id
                      AND site_id = :site_id
                    """
                ),
                {
                    "projection_id": projection_id,
                    "import_id": import_id,
                    "site_id": site_id,
                },
            )
            .mappings()
            .one_or_none()
        )
        if (
            projection is None
            or bytes(projection["projection_digest"]) != projection_digest
        ):
            raise CatalogProjectionStale()
        transaction_at = now.astimezone(UTC)
        if transaction_at > _as_utc(projection["expires_at"]):
            raise CatalogProjectionStale()
        if (
            int(projection["workflow_revision"]) != expected_workflow_revision
            or int(projection["validation_run_id"])
            != int(imported["validation_run_id"])
            or (
                None
                if projection["base_catalog_version_id"] is None
                else int(projection["base_catalog_version_id"])
            )
            != base_id
            or int(projection["catalog_publication_revision"])
            != expected_catalog_publication_revision
            or int(projection["fact_snapshot_tuple_id"])
            != int(imported["fact_snapshot_tuple_id"])
        ):
            raise CatalogProjectionStale()

        rows = load_import_rows(
            connection,
            import_id=import_id,
            workflow_revision=expected_workflow_revision,
        )
        evaluation = _evaluate_with_database(
            connection,
            rows=rows,
            site_id=site_id,
            export_id=int(imported["export_id"]),
            current_catalog_id=current_catalog_id,
        )
        if evaluation.issues:
            raise CatalogApprovalValidationFailed()
        if evaluation.diff_digest != bytes(
            projection["diff_digest"]
        ) or evaluation.risk != str(projection["risk"]):
            raise CatalogProjectionStale()
        _assert_permission(
            risk=evaluation.risk,
            actor_roles=actor_roles,
            submitted_by_user_id=int(imported["submitted_by_user_id"]),
            actor_user_id=actor_user_id,
            reason=reason,
        )

        _reconcile_draft_reservations(
            connection,
            import_id=import_id,
            site_id=site_id,
            actor_user_id=actor_user_id,
            rows=evaluation.reachability.rows,
        )
        style_rows = [
            row
            for row in evaluation.reachability.rows
            if row.section == "styles" and row.projection_state == "included"
        ]
        sku_rows = [
            row
            for row in evaluation.reachability.rows
            if row.section == "skus" and row.projection_state == "included"
        ]
        style_members: dict[str, tuple[int, int]] = {}
        style_categories: dict[
            str, tuple[int | None, str | None, str | None, str | None]
        ] = {}
        sku_members: dict[str, tuple[int, int, int]] = {}
        created_styles = 0
        created_skus = 0
        created_reservations = 0

        for row in style_rows:
            payload = row.payload
            style_code = _text(payload.get("style_code")) or ""
            standard_name = _text(payload.get("standard_name")) or ""
            status = _text(payload.get("status")) or ""
            key = catalog_identity_key_v1(style_code)
            style_id = _positive_id(payload.get("system_style_id"))
            current_revision = 0
            prior: Any = None
            if style_id is not None:
                prior = (
                    connection.execute(
                        sa.text(
                            "SELECT style_code, standard_name, status, "
                            "current_revision FROM product_styles "
                            "WHERE id = :id AND site_id = :site_id FOR UPDATE"
                        ),
                        {"id": style_id, "site_id": site_id},
                    )
                    .mappings()
                    .one_or_none()
                )
                if prior is None:
                    raise CatalogApprovalValidationFailed()
                current_revision = int(prior["current_revision"])
            else:
                inserted = connection.execute(
                    sa.text(
                        """
                        INSERT INTO product_styles (
                            site_id, style_code, style_key_sha256,
                            style_key_bytes, standard_name, status,
                            current_revision
                        ) VALUES (
                            :site_id, :style_code, :key_sha256,
                            :key_bytes, :standard_name, :status, 1
                        )
                        """
                    ),
                    {
                        "site_id": site_id,
                        "style_code": style_code,
                        "key_sha256": key.sha256,
                        "key_bytes": key.utf8,
                        "standard_name": standard_name,
                        "status": status,
                    },
                )
                if inserted.lastrowid is None:
                    raise CatalogApprovalError()
                style_id = int(inserted.lastrowid)
                created_styles += 1
            changed = prior is None or (
                str(prior["style_code"]),
                str(prior["standard_name"]),
                str(prior["status"]),
            ) != (style_code, standard_name, status)
            revision_number = (
                1 if prior is None else current_revision + (1 if changed else 0)
            )
            if changed:
                revised = connection.execute(
                    sa.text(
                        """
                        INSERT INTO product_style_revisions (
                            site_id, style_id, revision, style_code,
                            style_key_sha256, style_key_bytes, standard_name,
                            status, change_reason, actor_user_id,
                            source_import_id, source_command_token
                        ) VALUES (
                            :site_id, :style_id, :revision, :style_code,
                            :key_sha256, :key_bytes, :standard_name,
                            :status, :reason, :actor_user_id,
                            :import_id, :token
                        )
                        """
                    ),
                    {
                        "site_id": site_id,
                        "style_id": style_id,
                        "revision": revision_number,
                        "style_code": style_code,
                        "key_sha256": key.sha256,
                        "key_bytes": key.utf8,
                        "standard_name": standard_name,
                        "status": status,
                        "reason": _text(payload.get("change_reason"), required=False)
                        or reason,
                        "actor_user_id": actor_user_id,
                        "import_id": import_id,
                        "token": operation_token.bytes,
                    },
                )
                if revised.lastrowid is None:
                    raise CatalogApprovalError()
                revision_id = int(revised.lastrowid)
                if prior is not None:
                    connection.execute(
                        sa.text(
                            """
                            UPDATE product_styles SET style_code = :style_code,
                                style_key_sha256 = :key_sha256,
                                style_key_bytes = :key_bytes,
                                standard_name = :standard_name, status = :status,
                                current_revision = :revision
                            WHERE id = :id AND site_id = :site_id
                            """
                        ),
                        {
                            "style_code": style_code,
                            "key_sha256": key.sha256,
                            "key_bytes": key.utf8,
                            "standard_name": standard_name,
                            "status": status,
                            "revision": revision_number,
                            "id": style_id,
                            "site_id": site_id,
                        },
                    )
            else:
                revision_id = int(
                    connection.scalar(
                        sa.text(
                            "SELECT id FROM product_style_revisions "
                            "WHERE site_id = :site_id AND style_id = :style_id "
                            "AND revision = :revision"
                        ),
                        {
                            "site_id": site_id,
                            "style_id": style_id,
                            "revision": revision_number,
                        },
                    )
                )
            if _reserve(
                connection,
                site_id=site_id,
                key_kind="style_code",
                key_sha256=key.sha256,
                key_bytes=key.utf8,
                style_id=style_id,
                sku_id=None,
                first_revision_id=revision_id,
            ):
                created_reservations += 1
            style_members[row.row_key] = (style_id, revision_id)
            category_action = (
                _text(payload.get("category_action"), required=False) or "keep"
            )
            category_code = _text(payload.get("category_code"), required=False)
            parent_snapshot = None
            category_value: tuple[int | None, str | None, str | None] = (
                None,
                None,
                None,
            )
            if category_action == "keep":
                if current_catalog_id is not None:
                    prior_category = (
                        connection.execute(
                            sa.text(
                                "SELECT category_id, category_code_snapshot, "
                                "category_name_snapshot, category_parent_snapshot FROM "
                                "product_catalog_style_members "
                                "WHERE catalog_version_id=:version_id "
                                "AND site_id=:site_id AND style_id=:style_id"
                            ),
                            {
                                "version_id": current_catalog_id,
                                "site_id": site_id,
                                "style_id": style_id,
                            },
                        )
                        .mappings()
                        .one_or_none()
                    )
                    if prior_category is not None:
                        parent_snapshot = prior_category["category_parent_snapshot"]
                        category_value = (
                            None
                            if prior_category["category_id"] is None
                            else int(prior_category["category_id"]),
                            None
                            if prior_category["category_code_snapshot"] is None
                            else str(prior_category["category_code_snapshot"]),
                            None
                            if prior_category["category_name_snapshot"] is None
                            else str(prior_category["category_name_snapshot"]),
                        )
            elif category_action == "set" and category_code:
                selected = (
                    connection.execute(
                        sa.text(
                            "SELECT id,code,display_name FROM product_categories "
                            "WHERE site_id=:site_id AND code=:code "
                            "AND status='enabled'"
                        ),
                        {
                            "site_id": site_id,
                            "code": unicodedata.normalize("NFKC", category_code)
                            .strip()
                            .upper(),
                        },
                    )
                    .mappings()
                    .one_or_none()
                )
                if selected is None:
                    raise CatalogApprovalValidationFailed()
                category_value = (
                    int(selected["id"]),
                    str(selected["code"]),
                    str(selected["display_name"]),
                )
            elif category_action != "clear":
                raise CatalogApprovalValidationFailed()
            if category_action == "set":
                parent_snapshot = category_parent_snapshot(
                    connection, site_id, category_value[0]
                )
            style_categories[row.row_key] = (*category_value, parent_snapshot)

        for row in sku_rows:
            payload = row.payload
            style_key = _text(payload.get("style_row_key")) or ""
            if style_key not in style_members:
                raise CatalogApprovalValidationFailed()
            style_id = style_members[style_key][0]
            display = _text(payload.get("internal_display_sku")) or ""
            color = _text(payload.get("standard_color")) or ""
            size = _text(payload.get("standard_size")) or ""
            status = _text(payload.get("status")) or ""
            display_key = catalog_identity_key_v1(display)
            color_key = catalog_identity_key_v1(color)
            size_key = catalog_identity_key_v1(size)
            variant_bytes = (
                style_members[style_key][0].to_bytes(8, "big")
                + b"\0"
                + color_key.utf8
                + b"\0"
                + size_key.utf8
            )
            variant_sha = hashlib.sha256(variant_bytes).digest()
            sku_id = _positive_id(payload.get("system_sku_id"))
            current_revision = 0
            prior = None
            if sku_id is not None:
                prior = (
                    connection.execute(
                        sa.text(
                            "SELECT style_id, internal_display_sku, standard_color, "
                            "standard_size, status, current_revision FROM product_skus "
                            "WHERE id = :id AND site_id = :site_id FOR UPDATE"
                        ),
                        {"id": sku_id, "site_id": site_id},
                    )
                    .mappings()
                    .one_or_none()
                )
                if prior is None:
                    raise CatalogApprovalValidationFailed()
                current_revision = int(prior["current_revision"])
            else:
                inserted = connection.execute(
                    sa.text(
                        """
                        INSERT INTO product_skus (
                            site_id, style_id, internal_display_sku,
                            display_key_sha256, display_key_bytes,
                            standard_color, color_key_sha256, color_key_bytes,
                            standard_size, size_key_sha256, size_key_bytes,
                            status, current_revision
                        ) VALUES (
                            :site_id, :style_id, :display,
                            :display_sha, :display_bytes,
                            :color, :color_sha, :color_bytes,
                            :size, :size_sha, :size_bytes, :status, 1
                        )
                        """
                    ),
                    {
                        "site_id": site_id,
                        "style_id": style_id,
                        "display": display,
                        "display_sha": display_key.sha256,
                        "display_bytes": display_key.utf8,
                        "color": color,
                        "color_sha": color_key.sha256,
                        "color_bytes": color_key.utf8,
                        "size": size,
                        "size_sha": size_key.sha256,
                        "size_bytes": size_key.utf8,
                        "status": status,
                    },
                )
                if inserted.lastrowid is None:
                    raise CatalogApprovalError()
                sku_id = int(inserted.lastrowid)
                created_skus += 1
            changed = prior is None or (
                int(prior["style_id"]),
                str(prior["internal_display_sku"]),
                str(prior["standard_color"]),
                str(prior["standard_size"]),
                str(prior["status"]),
            ) != (style_id, display, color, size, status)
            revision_number = (
                1 if prior is None else current_revision + (1 if changed else 0)
            )
            if changed:
                revised = connection.execute(
                    sa.text(
                        """
                        INSERT INTO product_sku_revisions (
                            site_id, sku_id, style_id, revision,
                            internal_display_sku, display_key_sha256,
                            display_key_bytes, standard_color,
                            color_key_sha256, color_key_bytes, standard_size,
                            size_key_sha256, size_key_bytes, status,
                            change_reason, actor_user_id, source_import_id,
                            source_command_token
                        ) VALUES (
                            :site_id, :sku_id, :style_id, :revision,
                            :display, :display_sha, :display_bytes, :color,
                            :color_sha, :color_bytes, :size,
                            :size_sha, :size_bytes, :status,
                            :reason, :actor_user_id, :import_id, :token
                        )
                        """
                    ),
                    {
                        "site_id": site_id,
                        "sku_id": sku_id,
                        "style_id": style_id,
                        "revision": revision_number,
                        "display": display,
                        "display_sha": display_key.sha256,
                        "display_bytes": display_key.utf8,
                        "color": color,
                        "color_sha": color_key.sha256,
                        "color_bytes": color_key.utf8,
                        "size": size,
                        "size_sha": size_key.sha256,
                        "size_bytes": size_key.utf8,
                        "status": status,
                        "reason": _text(payload.get("change_reason"), required=False)
                        or reason,
                        "actor_user_id": actor_user_id,
                        "import_id": import_id,
                        "token": operation_token.bytes,
                    },
                )
                if revised.lastrowid is None:
                    raise CatalogApprovalError()
                revision_id = int(revised.lastrowid)
                if prior is not None:
                    connection.execute(
                        sa.text(
                            """
                            UPDATE product_skus SET style_id = :style_id,
                                internal_display_sku = :display,
                                display_key_sha256 = :display_sha,
                                display_key_bytes = :display_bytes,
                                standard_color = :color,
                                color_key_sha256 = :color_sha,
                                color_key_bytes = :color_bytes,
                                standard_size = :size,
                                size_key_sha256 = :size_sha,
                                size_key_bytes = :size_bytes,
                                status = :status, current_revision = :revision
                            WHERE id = :id AND site_id = :site_id
                            """
                        ),
                        {
                            "style_id": style_id,
                            "display": display,
                            "display_sha": display_key.sha256,
                            "display_bytes": display_key.utf8,
                            "color": color,
                            "color_sha": color_key.sha256,
                            "color_bytes": color_key.utf8,
                            "size": size,
                            "size_sha": size_key.sha256,
                            "size_bytes": size_key.utf8,
                            "status": status,
                            "revision": revision_number,
                            "id": sku_id,
                            "site_id": site_id,
                        },
                    )
            else:
                revision_id = int(
                    connection.scalar(
                        sa.text(
                            "SELECT id FROM product_sku_revisions "
                            "WHERE site_id = :site_id AND sku_id = :sku_id "
                            "AND revision = :revision"
                        ),
                        {
                            "site_id": site_id,
                            "sku_id": sku_id,
                            "revision": revision_number,
                        },
                    )
                )
            for kind, digest_value, bytes_value in (
                ("display_sku", display_key.sha256, display_key.utf8),
                ("variant", variant_sha, variant_bytes),
            ):
                if _reserve(
                    connection,
                    site_id=site_id,
                    key_kind=kind,
                    key_sha256=digest_value,
                    key_bytes=bytes_value,
                    style_id=None,
                    sku_id=sku_id,
                    first_revision_id=revision_id,
                ):
                    created_reservations += 1
            sku_members[row.row_key] = (sku_id, revision_id, style_id)

        version_number = int(
            connection.scalar(
                sa.text(
                    "SELECT COALESCE(MAX(version_number), 0) + 1 "
                    "FROM product_catalog_versions WHERE site_id = :site_id"
                ),
                {"site_id": site_id},
            )
        )
        approval_digest = hashlib.sha256(
            canonical_json_bytes(
                {
                    "projection_digest": projection_digest.hex(),
                    "styles": [
                        [key, value[0], value[1]]
                        for key, value in sorted(style_members.items())
                    ],
                    "skus": [
                        [key, value[0], value[1]]
                        for key, value in sorted(sku_members.items())
                    ],
                }
            )
        ).digest()
        inserted_version = connection.execute(
            sa.text(
                """
                INSERT INTO product_catalog_versions (
                    site_id, version_number, base_catalog_version_id,
                    workbook_schema_version, normalization_manifest_id,
                    fact_snapshot_tuple_id, source_import_id,
                    validation_run_id, approval_digest, diff_digest,
                    risk, status, approved_by_user_id, approved_at,
                    approval_reason
                ) VALUES (
                    :site_id, :version_number, :base_id,
                    'product_catalog_workbook_v2', :manifest_id,
                    :tuple_id, :import_id, :validation_run_id,
                    :approval_digest, :diff_digest, :risk, 'ready',
                    :actor_user_id, :approved_at, :reason
                )
                """
            ),
            {
                "site_id": site_id,
                "version_number": version_number,
                "base_id": base_id,
                "manifest_id": str(imported["normalization_manifest_id"]),
                "tuple_id": int(imported["fact_snapshot_tuple_id"]),
                "import_id": import_id,
                "validation_run_id": int(imported["validation_run_id"]),
                "approval_digest": approval_digest,
                "diff_digest": evaluation.diff_digest,
                "risk": evaluation.risk,
                "actor_user_id": actor_user_id,
                "approved_at": _mysql_datetime(now),
                "reason": reason.strip(),
            },
        )
        if inserted_version.lastrowid is None:
            raise CatalogApprovalError()
        version_id = int(inserted_version.lastrowid)
        for row_key, (style_id, revision_id) in style_members.items():
            (
                category_id,
                category_code,
                category_name,
                parent_snapshot,
            ) = style_categories[row_key]
            connection.execute(
                sa.text(
                    "INSERT INTO product_catalog_style_members "
                    "(catalog_version_id, site_id, style_id, style_revision_id, "
                    "category_id, category_code_snapshot, category_name_snapshot, "
                    "category_parent_snapshot, category_snapshot_recorded) "
                    "VALUES (:version_id, :site_id, :style_id, :revision_id, "
                    ":category_id, :category_code, :category_name, "
                    ":parent_snapshot, TRUE)"
                ),
                {
                    "version_id": version_id,
                    "site_id": site_id,
                    "style_id": style_id,
                    "revision_id": revision_id,
                    "category_id": category_id,
                    "category_code": category_code,
                    "category_name": category_name,
                    "parent_snapshot": parent_snapshot,
                },
            )
        for sku_id, revision_id, style_id in sku_members.values():
            connection.execute(
                sa.text(
                    "INSERT INTO product_catalog_sku_members "
                    "(catalog_version_id, site_id, sku_id, sku_revision_id, style_id) "
                    "VALUES (:version_id, :site_id, :sku_id, :revision_id, :style_id)"
                ),
                {
                    "version_id": version_id,
                    "site_id": site_id,
                    "sku_id": sku_id,
                    "revision_id": revision_id,
                    "style_id": style_id,
                },
            )

        for row in evaluation.reachability.rows:
            if row.section != "mappings":
                continue
            raw_sha = _text(row.payload.get("seller_sku_sha256")) or ""
            scope_id, match_sha, match_bytes = _source_decision_key(
                connection,
                site_id=site_id,
                export_id=int(imported["export_id"]),
                raw_sha256_ref=raw_sha,
            )
            evidence_digest = hashlib.sha256(
                canonical_json_bytes([raw_sha, row.payload_digest.hex()])
            ).digest()
            decision = row.payload.get("identity_decision")
            if decision == "mapped":
                target_key = _text(row.payload.get("target_sku_row_key")) or ""
                if target_key not in sku_members:
                    raise CatalogApprovalValidationFailed()
                connection.execute(
                    sa.text(
                        """
                        INSERT INTO product_catalog_mappings (
                            catalog_version_id, site_id,
                            report_source_scope_id, marketplace_scope_code,
                            seller_sku_match_sha256, seller_sku_match_bytes,
                            sku_id, decision_source, actor_user_id,
                            evidence_digest
                        ) VALUES (
                            :version_id, :site_id, :scope_id, 'amazon_us',
                            :match_sha, :match_bytes, :sku_id,
                            'catalog_import', :actor_user_id, :evidence_digest
                        )
                        """
                    ),
                    {
                        "version_id": version_id,
                        "site_id": site_id,
                        "scope_id": scope_id,
                        "match_sha": match_sha,
                        "match_bytes": match_bytes,
                        "sku_id": sku_members[target_key][0],
                        "actor_user_id": actor_user_id,
                        "evidence_digest": evidence_digest,
                    },
                )
            else:
                connection.execute(
                    sa.text(
                        """
                        INSERT INTO product_catalog_exclusions (
                            catalog_version_id, site_id,
                            report_source_scope_id, marketplace_scope_code,
                            seller_sku_match_sha256, seller_sku_match_bytes,
                            reason, actor_user_id, evidence_digest
                        ) VALUES (
                            :version_id, :site_id, :scope_id, 'amazon_us',
                            :match_sha, :match_bytes, :reason,
                            :actor_user_id, :evidence_digest
                        )
                        """
                    ),
                    {
                        "version_id": version_id,
                        "site_id": site_id,
                        "scope_id": scope_id,
                        "match_sha": match_sha,
                        "match_bytes": match_bytes,
                        "reason": _text(row.payload.get("exclusion_reason")) or "",
                        "actor_user_id": actor_user_id,
                        "evidence_digest": evidence_digest,
                    },
                )

        next_catalog_revision = expected_catalog_publication_revision + 1
        updated_pointer = connection.execute(
            sa.text(
                """
                UPDATE product_catalog_publications
                SET current_catalog_version_id = :version_id,
                    catalog_publication_revision = :next_revision
                WHERE site_id = :site_id
                  AND catalog_publication_revision = :expected_revision
                """
            ),
            {
                "version_id": version_id,
                "next_revision": next_catalog_revision,
                "site_id": site_id,
                "expected_revision": expected_catalog_publication_revision,
            },
        )
        if updated_pointer.rowcount != 1:
            raise CatalogPublicationConflict()
        connection.execute(
            sa.text(
                """
                INSERT INTO product_catalog_publication_events (
                    site_id, catalog_publication_revision,
                    previous_catalog_version_id, catalog_version_id,
                    event_kind, operation_token, actor_user_id, reason
                ) VALUES (
                    :site_id, :revision, :previous_id, :version_id,
                    'approve', :token, :actor_user_id, :reason
                )
                """
            ),
            {
                "site_id": site_id,
                "revision": next_catalog_revision,
                "previous_id": current_catalog_id,
                "version_id": version_id,
                "token": operation_token.bytes,
                "actor_user_id": actor_user_id,
                "reason": reason.strip(),
            },
        )
        next_workflow = expected_workflow_revision + 1
        updated_import = connection.execute(
            sa.text(
                "UPDATE catalog_imports SET status = 'approved', "
                "workflow_revision = :next_revision WHERE id = :import_id "
                "AND status = 'ready_for_approval' "
                "AND workflow_revision = :expected_revision"
            ),
            {
                "next_revision": next_workflow,
                "import_id": import_id,
                "expected_revision": expected_workflow_revision,
            },
        )
        if updated_import.rowcount != 1:
            raise CatalogProjectionStale()
        connection.execute(
            sa.text(
                "DELETE FROM catalog_draft_identity_reservations "
                "WHERE import_id=:import_id AND site_id=:site_id"
            ),
            {"import_id": import_id, "site_id": site_id},
        )
        safe_audit: dict[str, CanonicalValue] = {
            "catalog_version_id": version_id,
            "catalog_publication_revision": next_catalog_revision,
            "risk": evaluation.risk,
        }
        audit_bytes = canonical_json_bytes(safe_audit)
        connection.execute(
            sa.text(
                """
                INSERT INTO catalog_audit_events (
                    site_id, actor_user_id, event_kind, resource_kind,
                    resource_id, operation_token, safe_payload_json,
                    event_digest
                ) VALUES (
                    :site_id, :actor_user_id, 'catalog_approved',
                    'catalog_import', :import_id, :token,
                    CAST(:payload AS JSON), :digest
                )
                """
            ),
            {
                "site_id": site_id,
                "actor_user_id": actor_user_id,
                "import_id": import_id,
                "token": operation_token.bytes,
                "payload": audit_bytes.decode("utf-8"),
                "digest": hashlib.sha256(operation_token.bytes + audit_bytes).digest(),
            },
        )
        return 200, {
            "import_id": import_id,
            "status": "approved",
            "workflow_revision": next_workflow,
            "catalog_version_id": version_id,
            "catalog_version_number": version_number,
            "catalog_publication_revision": next_catalog_revision,
            "created_style_count": created_styles,
            "created_sku_count": created_skus,
            "created_reservation_count": created_reservations,
            "audit_only_row_count": len(evaluation.reachability.audit_only_row_keys),
        }

    def restore(
        self,
        *,
        site_id: int,
        target_version_id: int,
        actor_user_id: int,
        actor_roles: frozenset[str],
        operation_token: UUID,
        expected_catalog_publication_revision: int,
        reason: str,
        now: datetime,
    ) -> CatalogRestoreResult:
        if "admin" not in actor_roles or len(reason.strip()) < 10:
            raise CatalogApprovalForbidden()
        body: dict[str, CanonicalValue] = {
            "target_version_id": target_version_id,
            "expected_catalog_publication_revision": (
                expected_catalog_publication_revision
            ),
            "reason": reason,
        }
        digest = semantic_command_digest(
            route="catalog_version_restore",
            resource_id=target_version_id,
            body=body,
            operation_token=operation_token,
        )

        def effect(connection: Connection) -> tuple[int, dict[str, CanonicalValue]]:
            pointer = (
                connection.execute(
                    sa.text(
                        """
                        SELECT current_catalog_version_id,
                               catalog_publication_revision
                        FROM product_catalog_publications
                        WHERE site_id = :site_id
                        FOR UPDATE
                        """
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
            ):
                raise CatalogPublicationConflict()
            target = (
                connection.execute(
                    sa.text(
                        "SELECT * FROM product_catalog_versions "
                        "WHERE id = :id AND site_id = :site_id AND status = 'ready'"
                    ),
                    {"id": target_version_id, "site_id": site_id},
                )
                .mappings()
                .one_or_none()
            )
            if target is None:
                raise CatalogApprovalValidationFailed()
            tuple_ready = connection.scalar(
                sa.text(
                    "SELECT COUNT(*) FROM fact_snapshot_tuples "
                    "WHERE id = :id AND site_id = :site_id AND status = 'ready'"
                ),
                {"id": int(target["fact_snapshot_tuple_id"]), "site_id": site_id},
            )
            if int(tuple_ready or 0) != 1:
                raise CatalogApprovalValidationFailed()
            version_number = int(
                connection.scalar(
                    sa.text(
                        "SELECT COALESCE(MAX(version_number), 0) + 1 "
                        "FROM product_catalog_versions WHERE site_id = :site_id"
                    ),
                    {"site_id": site_id},
                )
            )
            restore_digest = hashlib.sha256(
                canonical_json_bytes(
                    {
                        "target_version_id": target_version_id,
                        "expected_catalog_publication_revision": (
                            expected_catalog_publication_revision
                        ),
                    }
                )
            ).digest()
            inserted = connection.execute(
                sa.text(
                    """
                    INSERT INTO product_catalog_versions (
                        site_id, version_number, base_catalog_version_id,
                        workbook_schema_version, normalization_manifest_id,
                        fact_snapshot_tuple_id, source_import_id,
                        validation_run_id, approval_digest, diff_digest,
                        risk, status, approved_by_user_id, approved_at,
                        approval_reason
                    ) VALUES (
                        :site_id, :version_number, :base_id,
                        :workbook, :manifest, :tuple_id, :source_import_id,
                        :validation_run_id, :approval_digest, :diff_digest,
                        'high', 'ready', :actor_user_id, :approved_at, :reason
                    )
                    """
                ),
                {
                    "site_id": site_id,
                    "version_number": version_number,
                    "base_id": pointer["current_catalog_version_id"],
                    "workbook": target["workbook_schema_version"],
                    "manifest": target["normalization_manifest_id"],
                    "tuple_id": target["fact_snapshot_tuple_id"],
                    "source_import_id": target["source_import_id"],
                    "validation_run_id": target["validation_run_id"],
                    "approval_digest": restore_digest,
                    "diff_digest": target["diff_digest"],
                    "actor_user_id": actor_user_id,
                    "approved_at": _mysql_datetime(now),
                    "reason": reason.strip(),
                },
            )
            if inserted.lastrowid is None:
                raise CatalogApprovalError()
            version_id = int(inserted.lastrowid)
            for table, columns in (
                (
                    "product_catalog_style_members",
                    "site_id, style_id, style_revision_id, category_id, "
                    "category_code_snapshot, category_name_snapshot, "
                    "category_parent_snapshot, category_snapshot_recorded",
                ),
                (
                    "product_catalog_sku_members",
                    "site_id, sku_id, sku_revision_id, style_id",
                ),
                (
                    "product_catalog_mappings",
                    "site_id, report_source_scope_id, marketplace_scope_code, "
                    "seller_sku_match_sha256, seller_sku_match_bytes, sku_id, "
                    "decision_source, actor_user_id, evidence_digest",
                ),
                (
                    "product_catalog_exclusions",
                    "site_id, report_source_scope_id, marketplace_scope_code, "
                    "seller_sku_match_sha256, seller_sku_match_bytes, reason, "
                    "actor_user_id, evidence_digest",
                ),
            ):
                connection.execute(
                    sa.text(
                        f"INSERT INTO {table} (catalog_version_id, {columns}) "
                        f"SELECT :version_id, {columns} FROM {table} "
                        "WHERE catalog_version_id = :target_id"
                    ),
                    {"version_id": version_id, "target_id": target_version_id},
                )
            next_revision = expected_catalog_publication_revision + 1
            connection.execute(
                sa.text(
                    "UPDATE product_catalog_publications "
                    "SET current_catalog_version_id = :version_id, "
                    "catalog_publication_revision = :next_revision "
                    "WHERE site_id = :site_id "
                    "AND catalog_publication_revision = :expected_revision"
                ),
                {
                    "version_id": version_id,
                    "next_revision": next_revision,
                    "site_id": site_id,
                    "expected_revision": expected_catalog_publication_revision,
                },
            )
            connection.execute(
                sa.text(
                    """
                    INSERT INTO product_catalog_publication_events (
                        site_id, catalog_publication_revision,
                        previous_catalog_version_id, catalog_version_id,
                        event_kind, operation_token, actor_user_id, reason
                    ) VALUES (
                        :site_id, :revision, :previous_id, :version_id,
                        'restore', :token, :actor_user_id, :reason
                    )
                    """
                ),
                {
                    "site_id": site_id,
                    "revision": next_revision,
                    "previous_id": pointer["current_catalog_version_id"],
                    "version_id": version_id,
                    "token": operation_token.bytes,
                    "actor_user_id": actor_user_id,
                    "reason": reason.strip(),
                },
            )
            return 200, {
                "catalog_version_id": version_id,
                "catalog_version_number": version_number,
                "catalog_publication_revision": next_revision,
            }

        with self._engine.begin() as connection:
            command = MySqlCatalogImportRepository._execute_command(
                connection,
                operation_token=operation_token,
                operation_kind="restore",
                operation_digest=digest,
                site_id=site_id,
                actor_user_id=actor_user_id,
                resource_id=target_version_id,
                effect=effect,
            )
        return CatalogRestoreResult(
            _result_int(command.safe_result["catalog_version_id"]),
            _result_int(command.safe_result["catalog_version_number"]),
            _result_int(command.safe_result["catalog_publication_revision"]),
        )


__all__ = (
    "CatalogApprovalError",
    "CatalogApprovalForbidden",
    "CatalogApprovalPreview",
    "CatalogApprovalResult",
    "CatalogApprovalValidationFailed",
    "CatalogProjectionStale",
    "CatalogPublicationConflict",
    "CatalogReservationConflict",
    "CatalogRestoreResult",
    "MySqlCatalogApprovalRepository",
)
