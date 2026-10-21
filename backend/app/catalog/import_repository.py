"""Transactional MySQL repository for the independent catalog-import workflow."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from uuid import UUID

import sqlalchemy as sa
from sqlalchemy.engine import Connection, Engine
from sqlalchemy.exc import IntegrityError

from app.catalog.canonical_json import CanonicalValue, canonical_json_bytes
from app.catalog.commands import (
    CatalogDecisionMutation,
    semantic_command_digest,
    validate_decision_batch,
)
from app.catalog.import_service import (
    DraftProjection,
    DraftRow,
    validate_draft_rows,
)


class CatalogImportRepositoryError(RuntimeError):
    code = "catalog_import_repository_error"

    def __init__(self) -> None:
        super().__init__(self.code)


class CatalogWorkflowRevisionConflict(CatalogImportRepositoryError):
    code = "catalog_workflow_revision_conflict"


class CatalogParseAttemptStale(CatalogImportRepositoryError):
    code = "catalog_parse_attempt_stale"


class CatalogPublicationRevisionConflict(CatalogImportRepositoryError):
    code = "catalog_publication_revision_conflict"


class CatalogExportNotReady(CatalogImportRepositoryError):
    code = "catalog_export_not_ready"


class CatalogExportFailed(CatalogImportRepositoryError):
    code = "catalog_export_failed"


class CatalogIdempotencyKeyReused(CatalogImportRepositoryError):
    code = "idempotency_key_reused"


class CatalogCommandOutcomeUnknown(CatalogImportRepositoryError):
    code = "outcome_unknown"


class CatalogDraftReservationConflict(CatalogImportRepositoryError):
    code = "catalog_draft_reservation_conflict"


@dataclass(frozen=True, slots=True)
class CatalogParseLease:
    import_id: int
    site_id: int
    workflow_revision: int
    parse_attempt_revision: int
    lease_token: UUID
    lease_expires_at: datetime
    storage_key: str
    sha256_hex: str
    size_bytes: int


@dataclass(frozen=True, slots=True)
class CatalogImportPage:
    import_id: int
    section: str
    workflow_revision: int
    parse_attempt_revision: int
    rows: tuple[dict[str, object], ...]
    total_rows: int
    page: int
    page_size: int


@dataclass(frozen=True, slots=True)
class CatalogCommandResult:
    operation_token: UUID
    status_code: int
    safe_result: dict[str, CanonicalValue]


@dataclass(frozen=True, slots=True)
class CatalogImportState:
    import_id: int
    site_id: int
    source_kind: str
    owner_user_id: int
    status: str
    workflow_revision: int
    parse_attempt_revision: int
    submitted_by_user_id: int | None
    validation_run_id: int | None


def _mysql_datetime(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("database timestamp must be timezone-aware")
    return value.astimezone(UTC).replace(tzinfo=None)


def _json(value: object) -> str:
    return canonical_json_bytes(value).decode("utf-8")


def _insert_projection(
    connection: Connection,
    *,
    import_id: int,
    site_id: int,
    workflow_revision: int,
    projection: DraftProjection,
) -> None:
    for row in projection.rows:
        connection.execute(
            sa.text(
                """
                INSERT INTO catalog_import_rows (
                    import_id, site_id, workflow_revision, section, row_key,
                    row_origin, projection_state, payload_json, payload_digest
                ) VALUES (
                    :import_id, :site_id, :workflow_revision, :section, :row_key,
                    :row_origin, :projection_state,
                    CAST(:payload_json AS JSON), :payload_digest
                )
                """
            ),
            {
                "import_id": import_id,
                "site_id": site_id,
                "workflow_revision": workflow_revision,
                "section": row.section,
                "row_key": row.row_key,
                "row_origin": row.row_origin,
                "projection_state": row.projection_state,
                "payload_json": _json(row.payload),
                "payload_digest": row.payload_digest,
            },
        )
    for issue in projection.issues:
        connection.execute(
            sa.text(
                """
                INSERT INTO catalog_import_issues (
                    import_id, site_id, workflow_revision, section, row_key,
                    severity, reason_code, safe_detail_json, issue_digest
                ) VALUES (
                    :import_id, :site_id, :workflow_revision, :section, :row_key,
                    :severity, :reason_code, CAST(:safe_detail AS JSON), :digest
                )
                """
            ),
            {
                "import_id": import_id,
                "site_id": site_id,
                "workflow_revision": workflow_revision,
                "section": issue.section,
                "row_key": issue.row_key,
                "severity": issue.severity,
                "reason_code": issue.reason_code,
                "safe_detail": _json(
                    {"field": issue.field, "safe_message": issue.safe_message}
                ),
                "digest": issue.issue_digest,
            },
        )


def _decode_json(value: object) -> CanonicalValue:
    decoded = json.loads(value) if isinstance(value, str) else value
    canonical_json_bytes(decoded)
    return decoded  # type: ignore[return-value]


def _source_decision_key(
    connection: Connection,
    *,
    site_id: int,
    export_id: int,
    raw_sha256_ref: str,
) -> tuple[int, bytes, bytes]:
    if not raw_sha256_ref.startswith("sha256:") or len(raw_sha256_ref) != 71:
        raise CatalogImportRepositoryError()
    try:
        raw_digest = bytes.fromhex(raw_sha256_ref[7:])
    except ValueError as error:
        raise CatalogImportRepositoryError() from error
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
        raise CatalogImportRepositoryError()
    return next(iter(distinct))


def _reconcile_draft_reservations(
    connection: Connection,
    *,
    import_id: int,
    site_id: int,
    actor_user_id: int,
    rows: tuple[DraftRow, ...],
) -> None:
    imported = (
        connection.execute(
            sa.text(
                """
                SELECT imports.export_id,
                       publications.current_catalog_version_id
                FROM catalog_imports AS imports
                LEFT JOIN product_catalog_publications AS publications
                  ON publications.site_id = imports.site_id
                WHERE imports.id = :import_id AND imports.site_id = :site_id
                """
            ),
            {"import_id": import_id, "site_id": site_id},
        )
        .mappings()
        .one()
    )
    export_id = int(imported["export_id"])
    sku_rows = {
        row.row_key: row
        for row in rows
        if row.section == "skus" and row.projection_state == "included"
    }
    desired: list[dict[str, object]] = []
    for row in rows:
        if (
            row.section != "mappings"
            or row.projection_state != "included"
            or row.payload.get("identity_decision") not in {"mapped", "excluded"}
        ):
            continue
        target_key = row.payload.get("target_sku_row_key")
        decision = row.payload.get("identity_decision")
        if decision == "mapped" and (
            not isinstance(target_key, str) or target_key not in sku_rows
        ):
            raise CatalogImportRepositoryError()
        if (
            decision == "excluded"
            and not str(row.payload.get("exclusion_reason") or "").strip()
        ):
            raise CatalogImportRepositoryError()
        raw_sha = row.payload.get("seller_sku_sha256")
        if not isinstance(raw_sha, str):
            raise CatalogImportRepositoryError()
        scope_id, match_sha, match_bytes = _source_decision_key(
            connection,
            site_id=site_id,
            export_id=export_id,
            raw_sha256_ref=raw_sha,
        )
        target_value: CanonicalValue = None
        if decision == "mapped":
            if not isinstance(target_key, str):
                raise CatalogImportRepositoryError()
            target_value = sku_rows[target_key].payload.get("system_sku_id")
        target_sku_id = (
            int(target_value)
            if isinstance(target_value, (int, str))
            and not isinstance(target_value, bool)
            and str(target_value).isdigit()
            and int(target_value) > 0
            else None
        )
        prior_owners = {
            int(value)
            for value in connection.scalars(
                sa.text(
                    """
                    SELECT DISTINCT mappings.sku_id
                    FROM product_catalog_mappings AS mappings
                    WHERE mappings.site_id = :site_id
                      AND mappings.report_source_scope_id = :scope_id
                      AND mappings.marketplace_scope_code = 'amazon_us'
                      AND mappings.seller_sku_match_sha256 = :match_sha
                      AND mappings.seller_sku_match_bytes = :match_bytes
                    """
                ),
                {
                    "site_id": site_id,
                    "scope_id": scope_id,
                    "match_sha": match_sha,
                    "match_bytes": match_bytes,
                },
            )
        }
        excluded = connection.scalar(
            sa.text(
                """
                SELECT 1 FROM product_catalog_exclusions
                WHERE site_id = :site_id
                  AND catalog_version_id = :current_version_id
                  AND report_source_scope_id = :scope_id
                  AND marketplace_scope_code = 'amazon_us'
                  AND seller_sku_match_sha256 = :match_sha
                  AND seller_sku_match_bytes = :match_bytes
                LIMIT 1
                """
            ),
            {
                "site_id": site_id,
                "current_version_id": imported["current_catalog_version_id"],
                "scope_id": scope_id,
                "match_sha": match_sha,
                "match_bytes": match_bytes,
            },
        )
        other_draft = connection.scalar(
            sa.text(
                "SELECT import_id FROM catalog_draft_identity_reservations "
                "WHERE site_id=:site_id AND report_source_scope_id=:scope_id "
                "AND marketplace_scope_code='amazon_us' "
                "AND seller_sku_match_sha256=:match_sha "
                "AND seller_sku_match_bytes=:match_bytes "
                "AND import_id<>:import_id LIMIT 1"
            ),
            {
                "site_id": site_id,
                "scope_id": scope_id,
                "match_sha": match_sha,
                "match_bytes": match_bytes,
                "import_id": import_id,
            },
        )
        if other_draft is not None:
            raise CatalogDraftReservationConflict()
        if prior_owners and decision == "mapped":
            if target_sku_id is None or prior_owners != {target_sku_id}:
                raise CatalogDraftReservationConflict()
            continue
        if (
            excluded
            and decision == "mapped"
            and not str(row.payload.get("change_reason") or "").strip()
        ):
            raise CatalogDraftReservationConflict()
        if excluded and decision == "excluded":
            continue
        desired.append(
            {
                "site_id": site_id,
                "import_id": import_id,
                "scope_id": scope_id,
                "match_sha": match_sha,
                "match_bytes": match_bytes,
                "group_key": row.row_key,
                "target_key": target_key,
                "decision_kind": decision,
                "actor": actor_user_id,
            }
        )

    connection.execute(
        sa.text(
            "DELETE FROM catalog_draft_identity_reservations "
            "WHERE import_id=:import_id AND site_id=:site_id"
        ),
        {"import_id": import_id, "site_id": site_id},
    )
    try:
        for value in desired:
            connection.execute(
                sa.text(
                    """
                    INSERT INTO catalog_draft_identity_reservations (
                        site_id, import_id, report_source_scope_id,
                        marketplace_scope_code, seller_sku_match_sha256,
                        seller_sku_match_bytes, decision_group_key,
                        target_sku_row_key, created_by_user_id, decision_kind
                    ) VALUES (
                        :site_id, :import_id, :scope_id, 'amazon_us',
                        :match_sha, :match_bytes, :group_key, :target_key,
                        :actor, :decision_kind
                    )
                    """
                ),
                value,
            )
    except IntegrityError as error:
        raise CatalogDraftReservationConflict() from error


def _locked_import(
    connection: Connection,
    *,
    import_id: int,
    site_id: int,
) -> CatalogImportState:
    row = (
        connection.execute(
            sa.text(
                """
                SELECT id, site_id, source_kind, owner_user_id, status,
                       workflow_revision, parse_attempt_revision,
                       submitted_by_user_id, validation_run_id
                FROM catalog_imports
                WHERE id = :import_id AND site_id = :site_id
                FOR UPDATE
                """
            ),
            {"import_id": import_id, "site_id": site_id},
        )
        .mappings()
        .one_or_none()
    )
    if row is None:
        raise CatalogImportRepositoryError()
    return CatalogImportState(
        int(row["id"]),
        int(row["site_id"]),
        str(row["source_kind"]),
        int(row["owner_user_id"]),
        str(row["status"]),
        int(row["workflow_revision"]),
        int(row["parse_attempt_revision"]),
        (
            None
            if row["submitted_by_user_id"] is None
            else int(row["submitted_by_user_id"])
        ),
        None if row["validation_run_id"] is None else int(row["validation_run_id"]),
    )


def _load_projection_rows(
    connection: Connection,
    *,
    import_id: int,
    workflow_revision: int,
) -> tuple[DraftRow, ...]:
    rows = connection.execute(
        sa.text(
            """
            SELECT draft_rows.section, draft_rows.row_key,
                   draft_rows.row_origin, draft_rows.projection_state,
                   draft_rows.payload_json, draft_rows.payload_digest
            FROM catalog_import_rows AS draft_rows
            INNER JOIN (
                SELECT section, MAX(workflow_revision) AS row_revision
                FROM catalog_import_rows
                WHERE import_id = :import_id
                  AND workflow_revision <= :workflow_revision
                GROUP BY section
            ) AS revisions
              ON revisions.section = draft_rows.section
             AND revisions.row_revision = draft_rows.workflow_revision
            WHERE draft_rows.import_id = :import_id
            ORDER BY CAST(draft_rows.section AS BINARY),
                     CAST(draft_rows.row_key AS BINARY)
            """
        ),
        {"import_id": import_id, "workflow_revision": workflow_revision},
    ).mappings()
    result: list[DraftRow] = []
    for row in rows:
        payload = _decode_json(row["payload_json"])
        if not isinstance(payload, dict):
            raise CatalogImportRepositoryError()
        result.append(
            DraftRow(
                str(row["section"]),
                str(row["row_key"]),
                str(row["row_origin"]),
                str(row["projection_state"]),
                payload,
                bytes(row["payload_digest"]),
            )
        )
    return tuple(result)


def _command_result(
    token: UUID,
    status_code: int,
    safe_result: dict[str, CanonicalValue],
) -> CatalogCommandResult:
    canonical_json_bytes(safe_result)
    return CatalogCommandResult(token, status_code, safe_result)


class MySqlCatalogImportRepository:
    def __init__(self, engine: Engine) -> None:
        self._engine = engine

    @staticmethod
    def _execute_command(
        connection: Connection,
        *,
        operation_token: UUID,
        operation_kind: str,
        operation_digest: bytes,
        site_id: int,
        actor_user_id: int,
        resource_id: int | None,
        effect: Callable[[Connection], tuple[int, dict[str, CanonicalValue]]],
    ) -> CatalogCommandResult:
        if operation_token.version != 4 or len(operation_digest) != 32:
            raise ValueError("invalid catalog command identity")
        connection.execute(
            sa.text(
                """
                INSERT IGNORE INTO catalog_command_claims (
                    operation_token, operation_kind, operation_digest,
                    site_id, actor_user_id, resource_kind, resource_id, status
                ) VALUES (
                    :token, :kind, :digest, :site_id, :actor_user_id,
                    'catalog_import', :resource_id, 'claimed'
                )
                """
            ),
            {
                "token": operation_token.bytes,
                "kind": operation_kind,
                "digest": operation_digest,
                "site_id": site_id,
                "actor_user_id": actor_user_id,
                "resource_id": resource_id,
            },
        )
        claim = (
            connection.execute(
                sa.text(
                    """
                    SELECT operation_kind, operation_digest, site_id,
                           actor_user_id, resource_kind, resource_id, status
                    FROM catalog_command_claims
                    WHERE operation_token = :token
                    FOR UPDATE
                    """
                ),
                {"token": operation_token.bytes},
            )
            .mappings()
            .one()
        )
        if (
            claim["operation_kind"] != operation_kind
            or bytes(claim["operation_digest"]) != operation_digest
            or int(claim["site_id"]) != site_id
            or int(claim["actor_user_id"]) != actor_user_id
            or claim["resource_kind"] != "catalog_import"
            or (None if claim["resource_id"] is None else int(claim["resource_id"]))
            != resource_id
        ):
            raise CatalogIdempotencyKeyReused()
        saved = (
            connection.execute(
                sa.text(
                    """
                    SELECT response_status_code, safe_result_json
                    FROM catalog_command_effects
                    WHERE operation_token = :token
                    """
                ),
                {"token": operation_token.bytes},
            )
            .mappings()
            .one_or_none()
        )
        if saved is not None:
            safe_result = _decode_json(saved["safe_result_json"])
            if not isinstance(safe_result, dict):
                raise CatalogImportRepositoryError()
            return _command_result(
                operation_token,
                int(saved["response_status_code"]),
                safe_result,
            )
        if claim["status"] == "outcome_unknown":
            raise CatalogCommandOutcomeUnknown()
        if claim["status"] != "claimed":
            raise CatalogImportRepositoryError()
        status_code, safe_result = effect(connection)
        canonical = _json(safe_result)
        connection.execute(
            sa.text(
                """
                INSERT INTO catalog_command_effects (
                    operation_token, operation_kind, operation_digest,
                    site_id, actor_user_id, response_schema_version,
                    response_status_code, safe_result_json, completed_at
                ) VALUES (
                    :token, :kind, :digest, :site_id, :actor_user_id, 1,
                    :status_code, CAST(:safe_result AS JSON), UTC_TIMESTAMP(6)
                )
                """
            ),
            {
                "token": operation_token.bytes,
                "kind": operation_kind,
                "digest": operation_digest,
                "site_id": site_id,
                "actor_user_id": actor_user_id,
                "status_code": status_code,
                "safe_result": canonical,
            },
        )
        advanced = connection.execute(
            sa.text(
                "UPDATE catalog_command_claims SET status = 'completed' "
                "WHERE operation_token = :token AND status = 'claimed'"
            ),
            {"token": operation_token.bytes},
        )
        if advanced.rowcount != 1:
            raise CatalogImportRepositoryError()
        return _command_result(operation_token, status_code, safe_result)

    def get_state(self, *, import_id: int, site_id: int) -> CatalogImportState:
        with self._engine.begin() as connection:
            return _locked_import(
                connection,
                import_id=import_id,
                site_id=site_id,
            )

    def claim_next_parse(
        self,
        *,
        lease_token: UUID,
        now: datetime,
        lease_ttl: timedelta,
    ) -> CatalogParseLease | None:
        if lease_token.version != 4 or lease_ttl <= timedelta(0):
            raise ValueError("invalid catalog parse lease")
        expires = now + lease_ttl
        with self._engine.begin() as connection:
            import_id = connection.scalar(
                sa.text(
                    """
                    SELECT id FROM catalog_imports
                    WHERE status = 'uploaded' AND source_kind = 'xlsx'
                    ORDER BY id
                    LIMIT 1 FOR UPDATE SKIP LOCKED
                    """
                )
            )
            if import_id is None:
                return None
            row = (
                connection.execute(
                    sa.text(
                        """
                        SELECT imports.id, imports.site_id,
                               imports.workflow_revision,
                               imports.parse_attempt_revision,
                               files.storage_key, files.sha256, files.size_bytes
                        FROM catalog_imports AS imports
                        INNER JOIN raw_files AS files
                            ON files.id = imports.raw_file_id
                        WHERE imports.id = :import_id
                          AND imports.status = 'uploaded'
                          AND imports.source_kind = 'xlsx'
                        """
                    ),
                    {"import_id": int(import_id)},
                )
                .mappings()
                .one_or_none()
            )
            if row is None:
                raise CatalogParseAttemptStale()
            workflow_revision = int(row["workflow_revision"]) + 1
            attempt_revision = int(row["parse_attempt_revision"]) + 1
            updated = connection.execute(
                sa.text(
                    """
                    UPDATE catalog_imports
                    SET status = 'parsing',
                        workflow_revision = :workflow_revision,
                        parse_attempt_revision = :attempt_revision
                    WHERE id = :import_id AND status = 'uploaded'
                    """
                ),
                {
                    "import_id": int(row["id"]),
                    "workflow_revision": workflow_revision,
                    "attempt_revision": attempt_revision,
                },
            )
            if updated.rowcount != 1:
                raise CatalogParseAttemptStale()
            connection.execute(
                sa.text(
                    """
                    INSERT INTO catalog_parse_attempts (
                        import_id, site_id, attempt_revision,
                        workflow_revision, status, lease_token, fencing_token,
                        started_at, lease_expires_at, completed_at,
                        recoverable, failure_reason_code, result_digest
                    ) VALUES (
                        :import_id, :site_id, :attempt_revision,
                        :workflow_revision, 'running', :lease_token,
                        :attempt_revision, :started_at, :expires_at,
                        NULL, NULL, NULL, NULL
                    )
                    """
                ),
                {
                    "import_id": int(row["id"]),
                    "site_id": int(row["site_id"]),
                    "attempt_revision": attempt_revision,
                    "workflow_revision": workflow_revision,
                    "lease_token": lease_token.bytes,
                    "started_at": _mysql_datetime(now),
                    "expires_at": _mysql_datetime(expires),
                },
            )
            return CatalogParseLease(
                int(row["id"]),
                int(row["site_id"]),
                workflow_revision,
                attempt_revision,
                lease_token,
                expires,
                str(row["storage_key"]),
                bytes(row["sha256"]).hex(),
                int(row["size_bytes"]),
            )

    def renew_parse(
        self,
        lease: CatalogParseLease,
        *,
        now: datetime,
        lease_ttl: timedelta,
    ) -> CatalogParseLease:
        expires = now + lease_ttl
        with self._engine.begin() as connection:
            current = (
                connection.execute(
                    sa.text(
                        "SELECT status, workflow_revision, parse_attempt_revision "
                        "FROM catalog_imports WHERE id = :import_id FOR UPDATE"
                    ),
                    {"import_id": lease.import_id},
                )
                .mappings()
                .one_or_none()
            )
            if (
                current is None
                or current["status"] != "parsing"
                or int(current["workflow_revision"]) != lease.workflow_revision
                or int(current["parse_attempt_revision"])
                != lease.parse_attempt_revision
            ):
                raise CatalogParseAttemptStale()
            new_revision = lease.workflow_revision + 1
            attempt = connection.execute(
                sa.text(
                    """
                    UPDATE catalog_parse_attempts
                    SET workflow_revision = :new_revision,
                        lease_expires_at = :expires_at
                    WHERE import_id = :import_id
                      AND attempt_revision = :attempt_revision
                      AND workflow_revision = :old_revision
                      AND lease_token = :lease_token
                      AND status = 'running'
                      AND lease_expires_at > :now
                    """
                ),
                {
                    "new_revision": new_revision,
                    "expires_at": _mysql_datetime(expires),
                    "import_id": lease.import_id,
                    "attempt_revision": lease.parse_attempt_revision,
                    "old_revision": lease.workflow_revision,
                    "lease_token": lease.lease_token.bytes,
                    "now": _mysql_datetime(now),
                },
            )
            imported = connection.execute(
                sa.text(
                    "UPDATE catalog_imports SET workflow_revision = :new_revision "
                    "WHERE id = :import_id AND status = 'parsing' "
                    "AND workflow_revision = :old_revision"
                ),
                {
                    "new_revision": new_revision,
                    "import_id": lease.import_id,
                    "old_revision": lease.workflow_revision,
                },
            )
            if attempt.rowcount != 1 or imported.rowcount != 1:
                raise CatalogParseAttemptStale()
        return CatalogParseLease(
            lease.import_id,
            lease.site_id,
            new_revision,
            lease.parse_attempt_revision,
            lease.lease_token,
            expires,
            lease.storage_key,
            lease.sha256_hex,
            lease.size_bytes,
        )

    def complete_parse(
        self,
        lease: CatalogParseLease,
        *,
        projection: DraftProjection,
        completed_at: datetime,
    ) -> int:
        next_revision = lease.workflow_revision + 1
        result_digest = hashlib.sha256(
            canonical_json_bytes(
                {
                    "rows": [row.payload_digest.hex() for row in projection.rows],
                    "issues": [issue.issue_digest.hex() for issue in projection.issues],
                }
            )
        ).digest()
        with self._engine.begin() as connection:
            attempt = connection.execute(
                sa.text(
                    """
                    UPDATE catalog_parse_attempts
                    SET status = 'succeeded', workflow_revision = :next_revision,
                        completed_at = :completed_at, recoverable = FALSE,
                        failure_reason_code = NULL, result_digest = :result_digest
                    WHERE import_id = :import_id
                      AND attempt_revision = :attempt_revision
                      AND workflow_revision = :workflow_revision
                      AND lease_token = :lease_token AND status = 'running'
                      AND lease_expires_at >= :completed_at
                    """
                ),
                {
                    "next_revision": next_revision,
                    "completed_at": _mysql_datetime(completed_at),
                    "result_digest": result_digest,
                    "import_id": lease.import_id,
                    "attempt_revision": lease.parse_attempt_revision,
                    "workflow_revision": lease.workflow_revision,
                    "lease_token": lease.lease_token.bytes,
                },
            )
            imported = connection.execute(
                sa.text(
                    """
                    UPDATE catalog_imports
                    SET status = :status, workflow_revision = :next_revision
                    WHERE id = :import_id AND status = 'parsing'
                      AND workflow_revision = :workflow_revision
                      AND parse_attempt_revision = :attempt_revision
                    """
                ),
                {
                    "status": projection.initial_status,
                    "next_revision": next_revision,
                    "import_id": lease.import_id,
                    "workflow_revision": lease.workflow_revision,
                    "attempt_revision": lease.parse_attempt_revision,
                },
            )
            if attempt.rowcount != 1 or imported.rowcount != 1:
                raise CatalogParseAttemptStale()
            _insert_projection(
                connection,
                import_id=lease.import_id,
                site_id=lease.site_id,
                workflow_revision=next_revision,
                projection=projection,
            )
        return next_revision

    def fail_parse(
        self,
        lease: CatalogParseLease,
        *,
        completed_at: datetime,
        recoverable: bool,
        reason: str,
    ) -> int:
        next_revision = lease.workflow_revision + 1
        digest = hashlib.sha256(reason.encode("ascii")).digest()
        with self._engine.begin() as connection:
            attempt = connection.execute(
                sa.text(
                    """
                    UPDATE catalog_parse_attempts
                    SET status = 'failed', workflow_revision = :next_revision,
                        completed_at = :completed_at, recoverable = :recoverable,
                        failure_reason_code = :reason, result_digest = :digest
                    WHERE import_id = :import_id
                      AND attempt_revision = :attempt_revision
                      AND workflow_revision = :workflow_revision
                      AND lease_token = :lease_token AND status = 'running'
                    """
                ),
                {
                    "next_revision": next_revision,
                    "completed_at": _mysql_datetime(completed_at),
                    "recoverable": recoverable,
                    "reason": reason,
                    "digest": digest,
                    "import_id": lease.import_id,
                    "attempt_revision": lease.parse_attempt_revision,
                    "workflow_revision": lease.workflow_revision,
                    "lease_token": lease.lease_token.bytes,
                },
            )
            imported = connection.execute(
                sa.text(
                    """
                    UPDATE catalog_imports
                    SET status = 'parse_failed', workflow_revision = :next_revision
                    WHERE id = :import_id AND status = 'parsing'
                      AND workflow_revision = :workflow_revision
                      AND parse_attempt_revision = :attempt_revision
                    """
                ),
                {
                    "next_revision": next_revision,
                    "import_id": lease.import_id,
                    "workflow_revision": lease.workflow_revision,
                    "attempt_revision": lease.parse_attempt_revision,
                },
            )
            if attempt.rowcount != 1 or imported.rowcount != 1:
                raise CatalogParseAttemptStale()
        return next_revision

    def create_online_from_export(
        self,
        *,
        site_id: int,
        owner_user_id: int,
        operation_token: UUID,
        export_id: int,
        expected_catalog_publication_revision: int,
        projection: DraftProjection,
    ) -> int:
        with self._engine.begin() as connection:
            existing = connection.scalar(
                sa.text(
                    "SELECT id FROM catalog_imports WHERE operation_token = :token"
                ),
                {"token": operation_token.bytes},
            )
            if existing is not None:
                return int(existing)
            export = (
                connection.execute(
                    sa.text(
                        """
                        SELECT id, export_status, catalog_publication_revision,
                               base_catalog_version_id, fact_snapshot_tuple_id,
                               normalization_manifest_id
                        FROM catalog_exports
                        WHERE id = :export_id AND site_id = :site_id
                        FOR SHARE
                        """
                    ),
                    {"export_id": export_id, "site_id": site_id},
                )
                .mappings()
                .one_or_none()
            )
            if export is None or export["export_status"] == "building":
                raise CatalogExportNotReady()
            if export["export_status"] == "failed":
                raise CatalogExportFailed()
            if export["export_status"] != "ready":
                raise CatalogImportRepositoryError()
            connection.execute(
                sa.text(
                    """
                    INSERT IGNORE INTO product_catalog_publications (
                        site_id, current_catalog_version_id,
                        catalog_publication_revision
                    ) VALUES (:site_id, NULL, 0)
                    """
                ),
                {"site_id": site_id},
            )
            current_revision_value = connection.scalar(
                sa.text(
                    "SELECT catalog_publication_revision "
                    "FROM product_catalog_publications "
                    "WHERE site_id = :site_id FOR UPDATE"
                ),
                {"site_id": site_id},
            )
            if current_revision_value is None:
                raise CatalogImportRepositoryError()
            current_revision = int(current_revision_value)
            if (
                current_revision != expected_catalog_publication_revision
                or int(export["catalog_publication_revision"]) != current_revision
            ):
                raise CatalogPublicationRevisionConflict()
            inserted = connection.execute(
                sa.text(
                    """
                    INSERT INTO catalog_imports (
                        site_id, operation_token, source_kind, owner_user_id,
                        export_id, raw_file_id, original_filename,
                        declared_media_type, base_catalog_version_id,
                        fact_snapshot_tuple_id, normalization_manifest_id,
                        status, workflow_revision, parse_attempt_revision
                    ) VALUES (
                        :site_id, :token, 'online', :owner_user_id,
                        :export_id, NULL, NULL, NULL, :base_id,
                        :tuple_id, :manifest_id, :status, 0, 0
                    )
                    """
                ),
                {
                    "site_id": site_id,
                    "token": operation_token.bytes,
                    "owner_user_id": owner_user_id,
                    "export_id": export_id,
                    "base_id": export["base_catalog_version_id"],
                    "tuple_id": int(export["fact_snapshot_tuple_id"]),
                    "manifest_id": export["normalization_manifest_id"],
                    "status": projection.initial_status,
                },
            )
            if inserted.lastrowid is None:
                raise CatalogImportRepositoryError()
            import_id = int(inserted.lastrowid)
            _insert_projection(
                connection,
                import_id=import_id,
                site_id=site_id,
                workflow_revision=0,
                projection=projection,
            )
            return import_id

    def apply_decisions(
        self,
        *,
        import_id: int,
        site_id: int,
        actor_user_id: int,
        operation_token: UUID,
        expected_workflow_revision: int,
        mutations: tuple[CatalogDecisionMutation, ...],
    ) -> CatalogCommandResult:
        body: dict[str, CanonicalValue] = {
            "expected_workflow_revision": expected_workflow_revision,
            "mutations": [
                {
                    "mutation_id": str(mutation.mutation_id),
                    "type": mutation.type,
                    "row_key": mutation.row_key,
                    "decision_group_key": mutation.decision_group_key,
                    "payload": mutation.payload,
                }
                for mutation in mutations
            ],
        }
        digest = semantic_command_digest(
            route="catalog_import_decisions",
            resource_id=import_id,
            body=body,
            operation_token=operation_token,
        )

        def effect(
            connection: Connection,
        ) -> tuple[int, dict[str, CanonicalValue]]:
            state = _locked_import(
                connection,
                import_id=import_id,
                site_id=site_id,
            )
            if state.workflow_revision != expected_workflow_revision:
                raise CatalogWorkflowRevisionConflict()
            if state.status not in {
                "needs_attention",
                "validated",
                "ready_for_approval",
            }:
                raise CatalogImportRepositoryError()
            current = list(
                _load_projection_rows(
                    connection,
                    import_id=import_id,
                    workflow_revision=state.workflow_revision,
                )
            )
            existing_keys = frozenset(row.row_key for row in current)
            system_keys = frozenset(
                row.row_key for row in current if row.row_origin == "system"
            )
            validate_decision_batch(
                mutations,
                existing_row_keys=existing_keys,
                system_row_keys=system_keys,
            )
            rows: dict[tuple[str, str], DraftRow] = {
                (row.section, row.row_key): row for row in current
            }

            def replace(
                section: str,
                row_key: str,
                payload: dict[str, CanonicalValue],
                *,
                origin: str | None = None,
            ) -> None:
                previous = rows.get((section, row_key))
                if previous is None and origin is None:
                    raise CatalogImportRepositoryError()
                row_origin = origin if previous is None else previous.row_origin
                if row_origin is None:
                    raise CatalogImportRepositoryError()
                projection_state = (
                    "included" if previous is None else previous.projection_state
                )
                payload["row_key"] = row_key
                rows[(section, row_key)] = DraftRow(
                    section,
                    row_key,
                    row_origin,
                    projection_state,
                    payload,
                    hashlib.sha256(canonical_json_bytes(payload)).digest(),
                )

            for mutation in mutations:
                row_key = mutation.row_key
                if mutation.type == "create_style" and row_key is not None:
                    if ("styles", row_key) in rows:
                        raise CatalogImportRepositoryError()
                    replace(
                        "styles",
                        row_key,
                        {
                            "row_key": row_key,
                            "system_style_id": None,
                            "style_code": mutation.payload.get("style_code"),
                            "standard_name": mutation.payload.get("standard_name"),
                            "status": mutation.payload.get("status", "enabled"),
                            "candidate_seller_sku_count": None,
                            "source_title_count": None,
                            "first_seen_date": None,
                            "latest_seen_date": None,
                            "change_reason": mutation.payload.get("change_reason"),
                        },
                        origin="user_created",
                    )
                elif mutation.type == "create_sku" and row_key is not None:
                    if ("skus", row_key) in rows:
                        raise CatalogImportRepositoryError()
                    replace(
                        "skus",
                        row_key,
                        {
                            "row_key": row_key,
                            "system_sku_id": None,
                            "style_row_key": mutation.payload.get("style_row_key"),
                            "internal_display_sku": mutation.payload.get(
                                "internal_display_sku"
                            ),
                            "standard_color": mutation.payload.get("standard_color"),
                            "standard_size": mutation.payload.get("standard_size"),
                            "status": mutation.payload.get("status", "enabled"),
                            "source_color_preview": None,
                            "source_color_set_sha256": None,
                            "source_size_preview": None,
                            "source_size_set_sha256": None,
                            "first_seen_date": None,
                            "latest_seen_date": None,
                            "change_reason": mutation.payload.get("change_reason"),
                        },
                        origin="user_created",
                    )
                elif mutation.type in {"update_style", "update_sku"}:
                    if row_key is None:
                        raise CatalogImportRepositoryError()
                    section = "styles" if mutation.type == "update_style" else "skus"
                    previous = rows.get((section, row_key))
                    if previous is None:
                        raise CatalogImportRepositoryError()
                    payload = dict(previous.payload)
                    payload.update(mutation.payload)
                    replace(section, row_key, payload)
                elif mutation.type in {"delete_style", "delete_sku"}:
                    if row_key is None:
                        raise CatalogImportRepositoryError()
                    section = "styles" if mutation.type == "delete_style" else "skus"
                    previous = rows.get((section, row_key))
                    if previous is None or previous.row_origin != "user_created":
                        raise CatalogImportRepositoryError()
                    if section == "styles" and any(
                        row.section == "skus"
                        and row.payload.get("style_row_key") == row_key
                        for row in rows.values()
                    ):
                        raise CatalogImportRepositoryError()
                    if section == "skus" and any(
                        row.section in {"mappings", "exceptions"}
                        and row.payload.get("target_sku_row_key") == row_key
                        for row in rows.values()
                    ):
                        raise CatalogImportRepositoryError()
                    del rows[(section, row_key)]
                elif mutation.type in {
                    "map_seller_sku",
                    "exclude_seller_sku",
                    "clear_seller_sku_decision",
                    "restore_seller_sku_review",
                }:
                    group = mutation.decision_group_key
                    if group is None:
                        raise CatalogImportRepositoryError()
                    previous = rows.get(("mappings", group))
                    if previous is None:
                        raise CatalogImportRepositoryError()
                    payload = dict(previous.payload)
                    if mutation.type == "restore_seller_sku_review" and (
                        payload.get("identity_decision") != "excluded"
                        or not str(mutation.payload.get("change_reason") or "").strip()
                    ):
                        raise CatalogImportRepositoryError()
                    if mutation.type == "map_seller_sku":
                        payload.update(
                            {
                                "identity_decision": "mapped",
                                "target_sku_row_key": mutation.payload.get(
                                    "target_sku_row_key"
                                ),
                                "exclusion_reason": None,
                            }
                        )
                    elif mutation.type == "exclude_seller_sku":
                        if isinstance(payload.get("target_sku_row_key"), str):
                            payload["review_target_sku_row_key"] = payload[
                                "target_sku_row_key"
                            ]
                        payload.update(
                            {
                                "identity_decision": "excluded",
                                "target_sku_row_key": None,
                                "exclusion_reason": mutation.payload.get(
                                    "exclusion_reason"
                                ),
                            }
                        )
                    else:
                        payload.update(
                            {
                                "identity_decision": None,
                                "target_sku_row_key": (
                                    payload.get("review_target_sku_row_key")
                                    if mutation.type == "restore_seller_sku_review"
                                    else None
                                ),
                                "exclusion_reason": None,
                            }
                        )
                    payload["change_reason"] = mutation.payload.get("change_reason")
                    replace("mappings", group, payload)
                else:
                    self._apply_exception_mutation(rows, mutation, replace)

            ordered = tuple(
                rows[key]
                for key in sorted(
                    rows,
                    key=lambda key: (key[0].encode(), key[1].encode("utf-8")),
                )
            )
            from app.catalog.projection import compute_reachability

            ordered = compute_reachability(ordered, final=False).rows
            projection = validate_draft_rows(ordered)
            _reconcile_draft_reservations(
                connection,
                import_id=import_id,
                site_id=site_id,
                actor_user_id=actor_user_id,
                rows=ordered,
            )
            next_revision = state.workflow_revision + 1
            _insert_projection(
                connection,
                import_id=import_id,
                site_id=site_id,
                workflow_revision=next_revision,
                projection=projection,
            )
            updated = connection.execute(
                sa.text(
                    """
                    UPDATE catalog_imports
                    SET status = 'needs_attention',
                        workflow_revision = :next_revision,
                        submitted_by_user_id = NULL,
                        validation_run_id = NULL
                    WHERE id = :import_id
                      AND workflow_revision = :expected_revision
                    """
                ),
                {
                    "next_revision": next_revision,
                    "import_id": import_id,
                    "expected_revision": state.workflow_revision,
                },
            )
            if updated.rowcount != 1:
                raise CatalogWorkflowRevisionConflict()
            return 200, {
                "import_id": import_id,
                "source_kind": state.source_kind,
                "workflow_revision": next_revision,
                "parse_attempt_revision": state.parse_attempt_revision,
                "applied_mutation_count": len(mutations),
            }

        with self._engine.begin() as connection:
            return self._execute_command(
                connection,
                operation_token=operation_token,
                operation_kind="decisions",
                operation_digest=digest,
                site_id=site_id,
                actor_user_id=actor_user_id,
                resource_id=import_id,
                effect=effect,
            )

    @staticmethod
    def _apply_exception_mutation(
        rows: dict[tuple[str, str], DraftRow],
        mutation: CatalogDecisionMutation,
        replace: Callable[[str, str, dict[str, CanonicalValue]], None],
    ) -> None:
        group = mutation.decision_group_key
        if group is None and mutation.type != "update_exception_note":
            raise CatalogImportRepositoryError()
        matched = [
            row
            for row in rows.values()
            if row.section == "exceptions"
            and (row.row_key == group or row.payload.get("seller_sku_sha256") == group)
        ]
        if mutation.type == "update_exception_note":
            matched = [
                row
                for row in rows.values()
                if row.section == "exceptions" and row.row_key == mutation.row_key
            ]
        if not matched:
            raise CatalogImportRepositoryError()
        action_by_type = {
            "resolve_exception_map_existing": "map_existing_variant",
            "resolve_exception_create_new": "create_new_variant",
            "resolve_exception_correct_parse": "correct_parse",
            "resolve_exception_exclude": "exclude",
            "clear_exception_group": None,
        }
        for previous in matched:
            payload = dict(previous.payload)
            if mutation.type == "update_exception_note":
                payload["note"] = mutation.payload.get("note")
            else:
                payload["action"] = action_by_type[mutation.type]
                for field in (
                    "target_sku_row_key",
                    "corrected_style_code",
                    "corrected_standard_color",
                    "corrected_standard_size",
                    "exclusion_reason",
                ):
                    payload[field] = mutation.payload.get(field)
            replace("exceptions", previous.row_key, payload)

    def validate_import(
        self,
        *,
        import_id: int,
        site_id: int,
        actor_user_id: int,
        operation_token: UUID,
        expected_workflow_revision: int,
    ) -> CatalogCommandResult:
        body: dict[str, CanonicalValue] = {
            "expected_workflow_revision": expected_workflow_revision
        }
        digest = semantic_command_digest(
            route="catalog_import_validate",
            resource_id=import_id,
            body=body,
            operation_token=operation_token,
        )

        def effect(
            connection: Connection,
        ) -> tuple[int, dict[str, CanonicalValue]]:
            state = _locked_import(
                connection,
                import_id=import_id,
                site_id=site_id,
            )
            if state.workflow_revision != expected_workflow_revision:
                raise CatalogWorkflowRevisionConflict()
            if state.status not in {"needs_attention", "validated"}:
                raise CatalogImportRepositoryError()
            rows = _load_projection_rows(
                connection,
                import_id=import_id,
                workflow_revision=state.workflow_revision,
            )
            projection = validate_draft_rows(rows)
            next_revision = state.workflow_revision + 1
            _insert_projection(
                connection,
                import_id=import_id,
                site_id=site_id,
                workflow_revision=next_revision,
                projection=projection,
            )
            included = sorted(
                row.row_key for row in rows if row.projection_state == "included"
            )
            audit_only = sorted(
                row.row_key for row in rows if row.projection_state == "audit_only"
            )
            issues = sorted(issue.issue_digest.hex() for issue in projection.issues)
            inserted = connection.execute(
                sa.text(
                    """
                    INSERT INTO catalog_validation_runs (
                        import_id, site_id, workflow_revision, status,
                        included_row_set_digest, audit_only_row_set_digest,
                        issue_set_digest, diff_digest, created_by_user_id
                    ) VALUES (
                        :import_id, :site_id, :workflow_revision, :status,
                        :included_digest, :audit_digest, :issue_digest,
                        :diff_digest, :actor_user_id
                    )
                    """
                ),
                {
                    "import_id": import_id,
                    "site_id": site_id,
                    "workflow_revision": next_revision,
                    "status": (
                        "passed"
                        if projection.initial_status == "validated"
                        else "failed"
                    ),
                    "included_digest": hashlib.sha256(
                        canonical_json_bytes(included)
                    ).digest(),
                    "audit_digest": hashlib.sha256(
                        canonical_json_bytes(audit_only)
                    ).digest(),
                    "issue_digest": hashlib.sha256(
                        canonical_json_bytes(issues)
                    ).digest(),
                    "diff_digest": hashlib.sha256(
                        canonical_json_bytes(
                            {
                                "included": included,
                                "audit_only": audit_only,
                                "issues": issues,
                            }
                        )
                    ).digest(),
                    "actor_user_id": actor_user_id,
                },
            )
            if inserted.lastrowid is None:
                raise CatalogImportRepositoryError()
            validation_run_id = int(inserted.lastrowid)
            updated = connection.execute(
                sa.text(
                    """
                    UPDATE catalog_imports
                    SET status = :status,
                        workflow_revision = :next_revision,
                        validation_run_id = :validation_run_id,
                        submitted_by_user_id = NULL
                    WHERE id = :import_id
                      AND workflow_revision = :expected_revision
                    """
                ),
                {
                    "status": projection.initial_status,
                    "next_revision": next_revision,
                    "validation_run_id": validation_run_id,
                    "import_id": import_id,
                    "expected_revision": state.workflow_revision,
                },
            )
            if updated.rowcount != 1:
                raise CatalogWorkflowRevisionConflict()
            return 200, {
                "import_id": import_id,
                "status": projection.initial_status,
                "workflow_revision": next_revision,
                "parse_attempt_revision": state.parse_attempt_revision,
                "validation_run_id": validation_run_id,
                "blocking_issue_count": len(projection.issues),
            }

        with self._engine.begin() as connection:
            return self._execute_command(
                connection,
                operation_token=operation_token,
                operation_kind="validate",
                operation_digest=digest,
                site_id=site_id,
                actor_user_id=actor_user_id,
                resource_id=import_id,
                effect=effect,
            )

    def transition_import(
        self,
        *,
        import_id: int,
        site_id: int,
        actor_user_id: int,
        operation_token: UUID,
        expected_workflow_revision: int,
        command: str,
        reason: str | None = None,
    ) -> CatalogCommandResult:
        targets = {
            "submit": ({"validated"}, "ready_for_approval"),
            "reject": ({"ready_for_approval"}, "rejected"),
            "withdraw": (
                {
                    "uploaded",
                    "parse_failed",
                    "needs_attention",
                    "validated",
                    "ready_for_approval",
                },
                "withdrawn",
            ),
        }
        if command not in targets:
            raise ValueError("unsupported catalog transition command")
        body: dict[str, CanonicalValue] = {
            "expected_workflow_revision": expected_workflow_revision,
            "reason": reason,
        }
        digest = semantic_command_digest(
            route=f"catalog_import_{command}",
            resource_id=import_id,
            body=body,
            operation_token=operation_token,
        )

        def effect(
            connection: Connection,
        ) -> tuple[int, dict[str, CanonicalValue]]:
            state = _locked_import(
                connection,
                import_id=import_id,
                site_id=site_id,
            )
            if state.workflow_revision != expected_workflow_revision:
                raise CatalogWorkflowRevisionConflict()
            sources, target = targets[command]
            if state.status not in sources:
                raise CatalogImportRepositoryError()
            if command == "submit" and state.validation_run_id is None:
                raise CatalogImportRepositoryError()
            if command == "reject" and (reason is None or len(reason.strip()) < 10):
                raise CatalogImportRepositoryError()
            if command in {"reject", "withdraw"}:
                connection.execute(
                    sa.text(
                        "DELETE FROM catalog_draft_identity_reservations "
                        "WHERE import_id=:import_id AND site_id=:site_id"
                    ),
                    {"import_id": import_id, "site_id": site_id},
                )
            next_revision = state.workflow_revision + 1
            updated = connection.execute(
                sa.text(
                    """
                    UPDATE catalog_imports
                    SET status = :status,
                        workflow_revision = :next_revision,
                        submitted_by_user_id = :submitted_by
                    WHERE id = :import_id
                      AND workflow_revision = :expected_revision
                    """
                ),
                {
                    "status": target,
                    "next_revision": next_revision,
                    "submitted_by": (
                        actor_user_id
                        if command == "submit"
                        else state.submitted_by_user_id
                    ),
                    "import_id": import_id,
                    "expected_revision": state.workflow_revision,
                },
            )
            if updated.rowcount != 1:
                raise CatalogWorkflowRevisionConflict()
            return 200, {
                "import_id": import_id,
                "status": target,
                "workflow_revision": next_revision,
                "parse_attempt_revision": state.parse_attempt_revision,
            }

        with self._engine.begin() as connection:
            return self._execute_command(
                connection,
                operation_token=operation_token,
                operation_kind=command,
                operation_digest=digest,
                site_id=site_id,
                actor_user_id=actor_user_id,
                resource_id=import_id,
                effect=effect,
            )

    def resume_parse(
        self,
        *,
        import_id: int,
        site_id: int,
        actor_user_id: int,
        operation_token: UUID,
        expected_workflow_revision: int,
        expected_parse_attempt_revision: int,
        lease_token: UUID,
        now: datetime,
        lease_ttl: timedelta,
    ) -> CatalogCommandResult:
        if lease_token.version != 4 or lease_ttl <= timedelta(0):
            raise ValueError("invalid catalog parse lease")
        body: dict[str, CanonicalValue] = {
            "expected_workflow_revision": expected_workflow_revision,
            "expected_parse_attempt_revision": expected_parse_attempt_revision,
        }
        digest = semantic_command_digest(
            route="catalog_import_resume",
            resource_id=import_id,
            body=body,
            operation_token=operation_token,
        )

        def effect(
            connection: Connection,
        ) -> tuple[int, dict[str, CanonicalValue]]:
            state = _locked_import(
                connection,
                import_id=import_id,
                site_id=site_id,
            )
            if state.workflow_revision != expected_workflow_revision:
                raise CatalogWorkflowRevisionConflict()
            if state.parse_attempt_revision != expected_parse_attempt_revision:
                raise CatalogParseAttemptStale()
            recoverable = connection.scalar(
                sa.text(
                    """
                    SELECT recoverable FROM catalog_parse_attempts
                    WHERE import_id = :import_id
                      AND attempt_revision = :attempt_revision
                      AND status = 'failed'
                    """
                ),
                {
                    "import_id": import_id,
                    "attempt_revision": state.parse_attempt_revision,
                },
            )
            if (
                state.status != "parse_failed"
                or state.source_kind != "xlsx"
                or not bool(recoverable)
            ):
                raise CatalogImportRepositoryError()
            next_workflow = state.workflow_revision + 1
            next_attempt = state.parse_attempt_revision + 1
            connection.execute(
                sa.text(
                    """
                    INSERT INTO catalog_parse_attempts (
                        import_id, site_id, attempt_revision,
                        workflow_revision, status, lease_token, fencing_token,
                        started_at, lease_expires_at, completed_at,
                        recoverable, failure_reason_code, result_digest
                    ) VALUES (
                        :import_id, :site_id, :attempt_revision,
                        :workflow_revision, 'running', :lease_token,
                        :attempt_revision, :started_at, :expires_at,
                        NULL, NULL, NULL, NULL
                    )
                    """
                ),
                {
                    "import_id": import_id,
                    "site_id": site_id,
                    "attempt_revision": next_attempt,
                    "workflow_revision": next_workflow,
                    "lease_token": lease_token.bytes,
                    "started_at": _mysql_datetime(now),
                    "expires_at": _mysql_datetime(now + lease_ttl),
                },
            )
            updated = connection.execute(
                sa.text(
                    """
                    UPDATE catalog_imports
                    SET status = 'parsing',
                        workflow_revision = :workflow_revision,
                        parse_attempt_revision = :attempt_revision
                    WHERE id = :import_id
                      AND workflow_revision = :expected_workflow_revision
                      AND parse_attempt_revision = :expected_attempt_revision
                    """
                ),
                {
                    "workflow_revision": next_workflow,
                    "attempt_revision": next_attempt,
                    "import_id": import_id,
                    "expected_workflow_revision": state.workflow_revision,
                    "expected_attempt_revision": state.parse_attempt_revision,
                },
            )
            if updated.rowcount != 1:
                raise CatalogParseAttemptStale()
            return 200, {
                "import_id": import_id,
                "status": "parsing",
                "workflow_revision": next_workflow,
                "parse_attempt_revision": next_attempt,
            }

        with self._engine.begin() as connection:
            return self._execute_command(
                connection,
                operation_token=operation_token,
                operation_kind="resume",
                operation_digest=digest,
                site_id=site_id,
                actor_user_id=actor_user_id,
                resource_id=import_id,
                effect=effect,
            )

    def create_approval_preview(
        self,
        *,
        import_id: int,
        site_id: int,
        actor_user_id: int,
        operation_token: UUID,
        expected_workflow_revision: int,
        risk: str,
        now: datetime,
    ) -> CatalogCommandResult:
        if risk not in {"normal", "high"}:
            raise ValueError("invalid catalog approval risk")
        body: dict[str, CanonicalValue] = {
            "expected_workflow_revision": expected_workflow_revision,
            "risk": risk,
        }
        digest = semantic_command_digest(
            route="catalog_import_approval_preview",
            resource_id=import_id,
            body=body,
            operation_token=operation_token,
        )

        def effect(
            connection: Connection,
        ) -> tuple[int, dict[str, CanonicalValue]]:
            state = _locked_import(
                connection,
                import_id=import_id,
                site_id=site_id,
            )
            if state.workflow_revision != expected_workflow_revision:
                raise CatalogWorkflowRevisionConflict()
            if state.status != "ready_for_approval" or state.validation_run_id is None:
                raise CatalogImportRepositoryError()
            bindings = (
                connection.execute(
                    sa.text(
                        """
                        SELECT base_catalog_version_id, fact_snapshot_tuple_id
                        FROM catalog_imports WHERE id = :import_id
                        """
                    ),
                    {"import_id": import_id},
                )
                .mappings()
                .one()
            )
            publication_revision = connection.scalar(
                sa.text(
                    "SELECT catalog_publication_revision "
                    "FROM product_catalog_publications "
                    "WHERE site_id = :site_id FOR UPDATE"
                ),
                {"site_id": site_id},
            )
            if publication_revision is None:
                raise CatalogImportRepositoryError()
            rows = _load_projection_rows(
                connection,
                import_id=import_id,
                workflow_revision=state.workflow_revision,
            )
            diff_digest = hashlib.sha256(
                canonical_json_bytes(
                    [
                        [row.section, row.row_key, row.payload_digest.hex()]
                        for row in rows
                    ]
                )
            ).digest()
            projection_digest = hashlib.sha256(
                canonical_json_bytes(
                    {
                        # A new preview request gets its own immutable lifetime;
                        # replays of the same token return the stored result.
                        "preview_operation_token": str(operation_token),
                        "import_id": import_id,
                        "workflow_revision": state.workflow_revision,
                        "validation_run_id": state.validation_run_id,
                        "base_catalog_version_id": bindings["base_catalog_version_id"],
                        "catalog_publication_revision": int(publication_revision),
                        "fact_snapshot_tuple_id": int(
                            bindings["fact_snapshot_tuple_id"]
                        ),
                        "risk": risk,
                        "diff_digest": diff_digest.hex(),
                    }
                )
            ).digest()
            created_at = _mysql_datetime(now)
            expires_at = _mysql_datetime(now + timedelta(minutes=30))
            inserted = connection.execute(
                sa.text(
                    """
                    INSERT INTO catalog_approval_projections (
                        import_id, site_id, workflow_revision,
                        validation_run_id, base_catalog_version_id,
                        catalog_publication_revision, fact_snapshot_tuple_id,
                        risk, diff_digest, projection_digest,
                        created_by_user_id, created_at, expires_at
                    ) VALUES (
                        :import_id, :site_id, :workflow_revision,
                        :validation_run_id, :base_catalog_version_id,
                        :catalog_publication_revision, :fact_snapshot_tuple_id,
                        :risk, :diff_digest, :projection_digest,
                        :actor_user_id, :created_at, :expires_at
                    )
                    """
                ),
                {
                    "import_id": import_id,
                    "site_id": site_id,
                    "workflow_revision": state.workflow_revision,
                    "validation_run_id": state.validation_run_id,
                    "base_catalog_version_id": bindings["base_catalog_version_id"],
                    "catalog_publication_revision": int(publication_revision),
                    "fact_snapshot_tuple_id": int(bindings["fact_snapshot_tuple_id"]),
                    "risk": risk,
                    "diff_digest": diff_digest,
                    "projection_digest": projection_digest,
                    "actor_user_id": actor_user_id,
                    "created_at": created_at,
                    "expires_at": expires_at,
                },
            )
            if inserted.lastrowid is None:
                raise CatalogImportRepositoryError()
            return 200, {
                "import_id": import_id,
                "projection_id": int(inserted.lastrowid),
                "projection_digest": projection_digest.hex(),
                "workflow_revision": state.workflow_revision,
                "validation_run_id": state.validation_run_id,
                "base_catalog_version_id": bindings["base_catalog_version_id"],
                "catalog_publication_revision": int(publication_revision),
                "fact_snapshot_tuple_id": int(bindings["fact_snapshot_tuple_id"]),
                "risk": risk,
                "diff_digest": diff_digest.hex(),
                "created_at": now.astimezone(UTC).isoformat(),
                "expires_at": (now + timedelta(minutes=30)).astimezone(UTC).isoformat(),
            }

        with self._engine.begin() as connection:
            return self._execute_command(
                connection,
                operation_token=operation_token,
                operation_kind="approval_preview",
                operation_digest=digest,
                site_id=site_id,
                actor_user_id=actor_user_id,
                resource_id=import_id,
                effect=effect,
            )

    def rebase_import(
        self,
        *,
        import_id: int,
        site_id: int,
        actor_user_id: int,
        operation_token: UUID,
        expected_workflow_revision: int,
        replacement_export_id: int,
        expected_catalog_publication_revision: int,
        projection: DraftProjection,
    ) -> CatalogCommandResult:
        body: dict[str, CanonicalValue] = {
            "expected_workflow_revision": expected_workflow_revision,
            "replacement_export_id": replacement_export_id,
            "expected_catalog_publication_revision": (
                expected_catalog_publication_revision
            ),
        }
        digest = semantic_command_digest(
            route="catalog_import_rebase",
            resource_id=import_id,
            body=body,
            operation_token=operation_token,
        )

        def effect(
            connection: Connection,
        ) -> tuple[int, dict[str, CanonicalValue]]:
            state = _locked_import(
                connection,
                import_id=import_id,
                site_id=site_id,
            )
            if state.workflow_revision != expected_workflow_revision:
                raise CatalogWorkflowRevisionConflict()
            if state.status not in {
                "needs_attention",
                "validated",
                "ready_for_approval",
                "rejected",
            }:
                raise CatalogImportRepositoryError()
            current_revision = connection.scalar(
                sa.text(
                    "SELECT catalog_publication_revision "
                    "FROM product_catalog_publications "
                    "WHERE site_id = :site_id FOR UPDATE"
                ),
                {"site_id": site_id},
            )
            export = (
                connection.execute(
                    sa.text(
                        """
                        SELECT id, export_status, catalog_publication_revision,
                               base_catalog_version_id,
                               fact_snapshot_tuple_id,
                               normalization_manifest_id
                        FROM catalog_exports
                        WHERE id = :export_id AND site_id = :site_id
                        """
                    ),
                    {"export_id": replacement_export_id, "site_id": site_id},
                )
                .mappings()
                .one_or_none()
            )
            if export is None or export["export_status"] != "ready":
                raise CatalogExportNotReady()
            if (
                current_revision is None
                or int(current_revision) != expected_catalog_publication_revision
                or int(export["catalog_publication_revision"])
                != expected_catalog_publication_revision
            ):
                raise CatalogPublicationRevisionConflict()
            inserted = connection.execute(
                sa.text(
                    """
                    INSERT INTO catalog_imports (
                        site_id, operation_token, source_kind, owner_user_id,
                        export_id, raw_file_id, original_filename,
                        declared_media_type, base_catalog_version_id,
                        fact_snapshot_tuple_id, normalization_manifest_id,
                        status, workflow_revision, parse_attempt_revision
                    ) VALUES (
                        :site_id, :token, 'online', :owner_user_id,
                        :export_id, NULL, NULL, NULL, :base_id,
                        :tuple_id, :manifest_id, :status, 0, 0
                    )
                    """
                ),
                {
                    "site_id": site_id,
                    "token": operation_token.bytes,
                    "owner_user_id": state.owner_user_id,
                    "export_id": replacement_export_id,
                    "base_id": export["base_catalog_version_id"],
                    "tuple_id": int(export["fact_snapshot_tuple_id"]),
                    "manifest_id": export["normalization_manifest_id"],
                    "status": projection.initial_status,
                },
            )
            if inserted.lastrowid is None:
                raise CatalogImportRepositoryError()
            successor_id = int(inserted.lastrowid)
            _insert_projection(
                connection,
                import_id=successor_id,
                site_id=site_id,
                workflow_revision=0,
                projection=projection,
            )
            updated = connection.execute(
                sa.text(
                    """
                    UPDATE catalog_imports
                    SET status = 'superseded',
                        workflow_revision = :next_revision,
                        superseded_by_id = :successor_id
                    WHERE id = :import_id
                      AND workflow_revision = :expected_revision
                    """
                ),
                {
                    "next_revision": state.workflow_revision + 1,
                    "successor_id": successor_id,
                    "import_id": import_id,
                    "expected_revision": state.workflow_revision,
                },
            )
            if updated.rowcount != 1:
                raise CatalogWorkflowRevisionConflict()
            connection.execute(
                sa.text(
                    "DELETE FROM catalog_draft_identity_reservations "
                    "WHERE import_id=:import_id AND site_id=:site_id"
                ),
                {"import_id": import_id, "site_id": site_id},
            )
            return 201, {
                "import_id": import_id,
                "status": "superseded",
                "workflow_revision": state.workflow_revision + 1,
                "successor_import_id": successor_id,
                "successor_status": projection.initial_status,
                "successor_workflow_revision": 0,
                "successor_parse_attempt_revision": 0,
            }

        with self._engine.begin() as connection:
            return self._execute_command(
                connection,
                operation_token=operation_token,
                operation_kind="rebase",
                operation_digest=digest,
                site_id=site_id,
                actor_user_id=actor_user_id,
                resource_id=import_id,
                effect=effect,
            )

    def page_rows(
        self,
        *,
        import_id: int,
        site_id: int,
        section: str,
        page: int,
        page_size: int,
        at_workflow_revision: int | None = None,
    ) -> CatalogImportPage:
        if section not in {"styles", "skus", "mappings", "exceptions", "evidence"}:
            raise ValueError("invalid catalog section")
        if page < 1 or not 1 <= page_size <= 200:
            raise ValueError("invalid catalog page")
        with self._engine.connect() as connection:
            imported = (
                connection.execute(
                    sa.text(
                        "SELECT workflow_revision, parse_attempt_revision "
                        "FROM catalog_imports WHERE id = :id AND site_id = :site_id"
                    ),
                    {"id": import_id, "site_id": site_id},
                )
                .mappings()
                .one_or_none()
            )
            if imported is None:
                raise CatalogImportRepositoryError()
            revision = int(imported["workflow_revision"])
            if at_workflow_revision is not None and at_workflow_revision != revision:
                raise CatalogWorkflowRevisionConflict()
            row_revision = connection.scalar(
                sa.text(
                    "SELECT MAX(workflow_revision) FROM catalog_import_rows "
                    "WHERE import_id = :import_id AND section = :section "
                    "AND workflow_revision <= :revision"
                ),
                {
                    "import_id": import_id,
                    "section": section,
                    "revision": revision,
                },
            )
            if row_revision is None:
                row_revision = revision
            total = int(
                connection.scalar(
                    sa.text(
                        "SELECT COUNT(*) FROM catalog_import_rows "
                        "WHERE import_id = :import_id AND section = :section "
                        "AND workflow_revision = :row_revision"
                    ),
                    {
                        "import_id": import_id,
                        "section": section,
                        "row_revision": row_revision,
                    },
                )
                or 0
            )
            result = connection.execute(
                sa.text(
                    """
                    SELECT row_key, row_origin, projection_state, payload_json
                    FROM catalog_import_rows
                    WHERE import_id = :import_id AND section = :section
                      AND workflow_revision = :row_revision
                    ORDER BY CAST(row_key AS BINARY)
                    LIMIT :limit OFFSET :offset
                    """
                ),
                {
                    "import_id": import_id,
                    "section": section,
                    "row_revision": row_revision,
                    "limit": page_size,
                    "offset": (page - 1) * page_size,
                },
            ).mappings()
            rows = []
            for row in result:
                payload = row["payload_json"]
                if isinstance(payload, str):
                    payload = json.loads(payload)
                rows.append(
                    {
                        "row_key": row["row_key"],
                        "row_origin": row["row_origin"],
                        "projection_state": row["projection_state"],
                        "payload": payload,
                    }
                )
            return CatalogImportPage(
                import_id,
                section,
                revision,
                int(imported["parse_attempt_revision"]),
                tuple(rows),
                total,
                page,
                page_size,
            )


__all__ = (
    "CatalogCommandOutcomeUnknown",
    "CatalogCommandResult",
    "CatalogDraftReservationConflict",
    "CatalogExportFailed",
    "CatalogExportNotReady",
    "CatalogIdempotencyKeyReused",
    "CatalogImportPage",
    "CatalogImportState",
    "CatalogParseAttemptStale",
    "CatalogParseLease",
    "CatalogPublicationRevisionConflict",
    "CatalogWorkflowRevisionConflict",
    "MySqlCatalogImportRepository",
)
