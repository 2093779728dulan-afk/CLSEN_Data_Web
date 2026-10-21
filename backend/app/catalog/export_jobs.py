"""Manual recovery command for durable catalog export jobs."""

from __future__ import annotations

import hashlib
import json
from uuid import UUID

import sqlalchemy as sa
from sqlalchemy.engine import Engine

from app.catalog.canonical_json import canonical_json_bytes


class CatalogExportJobError(RuntimeError):
    code = "catalog_export_job_error"

    def __init__(self) -> None:
        super().__init__(self.code)


class CatalogExportJobNotFound(CatalogExportJobError):
    code = "catalog_export_job_not_found"


class CatalogExportJobRevisionConflict(CatalogExportJobError):
    code = "catalog_job_revision_conflict"


class CatalogExportJobNotRecoverable(CatalogExportJobError):
    code = "catalog_job_not_recoverable"


class CatalogExportRecoveryKeyReused(CatalogExportJobError):
    code = "idempotency_key_reused"


class MySqlCatalogExportJobRepository:
    def __init__(self, engine: Engine) -> None:
        self._engine = engine

    def resume(
        self,
        *,
        export_id: int,
        site_id: int,
        actor_user_id: int,
        operation_token: UUID,
        expected_job_revision: int,
    ) -> dict[str, object]:
        request_payload = {
            "export_id": export_id,
            "expected_job_revision": expected_job_revision,
        }
        operation_digest = hashlib.sha256(
            canonical_json_bytes(request_payload)
        ).digest()
        with self._engine.begin() as connection:
            connection.execute(
                sa.text(
                    """
                    INSERT IGNORE INTO catalog_command_claims (
                        operation_token, operation_kind, operation_digest,
                        site_id, actor_user_id, resource_kind, resource_id, status
                    ) VALUES (
                        :token, 'catalog_export_resume', :digest,
                        :site_id, :actor_user_id, 'catalog_export', :export_id,
                        'claimed'
                    )
                    """
                ),
                {
                    "token": operation_token.bytes,
                    "digest": operation_digest,
                    "site_id": site_id,
                    "actor_user_id": actor_user_id,
                    "export_id": export_id,
                },
            )
            claim = (
                connection.execute(
                    sa.text(
                        """
                        SELECT operation_kind, operation_digest, site_id,
                               actor_user_id, resource_kind, resource_id
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
                claim["operation_kind"] != "catalog_export_resume"
                or bytes(claim["operation_digest"]) != operation_digest
                or int(claim["site_id"]) != site_id
                or int(claim["actor_user_id"]) != actor_user_id
                or claim["resource_kind"] != "catalog_export"
                or int(claim["resource_id"]) != export_id
            ):
                raise CatalogExportRecoveryKeyReused()
            saved = connection.scalar(
                sa.text(
                    "SELECT safe_result_json FROM catalog_command_effects "
                    "WHERE operation_token = :token"
                ),
                {"token": operation_token.bytes},
            )
            if saved is not None:
                value = json.loads(saved) if isinstance(saved, str) else saved
                if not isinstance(value, dict):
                    raise CatalogExportJobError()
                return value

            job = (
                connection.execute(
                    sa.text(
                        """
                        SELECT jobs.id, jobs.job_revision, jobs.status,
                               jobs.retry_allowed, jobs.lease_token,
                               jobs.lease_expires_at
                        FROM catalog_jobs AS jobs
                        INNER JOIN catalog_exports AS exports
                            ON exports.id = jobs.resource_id
                           AND exports.site_id = jobs.site_id
                        WHERE exports.id = :export_id
                          AND exports.site_id = :site_id
                          AND jobs.job_kind = 'catalog_export'
                          AND jobs.resource_kind = 'catalog_export'
                        FOR UPDATE
                        """
                    ),
                    {"export_id": export_id, "site_id": site_id},
                )
                .mappings()
                .one_or_none()
            )
            if job is None:
                raise CatalogExportJobNotFound()
            if int(job["job_revision"]) != expected_job_revision:
                raise CatalogExportJobRevisionConflict()
            if (
                job["status"] != "failed"
                or not bool(job["retry_allowed"])
                or job["lease_token"] is not None
                or job["lease_expires_at"] is not None
            ):
                raise CatalogExportJobNotRecoverable()
            updated = connection.execute(
                sa.text(
                    """
                    UPDATE catalog_jobs
                    SET status = 'queued', job_revision = job_revision + 1,
                        attempt_count = 0, next_attempt_at = NULL,
                        execution_phase = 'waiting_for_worker',
                        retry_allowed = FALSE, failure_reason_code = NULL
                    WHERE id = :job_id AND job_revision = :expected_revision
                      AND status = 'failed' AND retry_allowed = TRUE
                      AND lease_token IS NULL AND lease_expires_at IS NULL
                    """
                ),
                {
                    "job_id": int(job["id"]),
                    "expected_revision": expected_job_revision,
                },
            )
            if updated.rowcount != 1:
                raise CatalogExportJobRevisionConflict()
            safe_result: dict[str, object] = {
                "export_id": export_id,
                "job_status": "queued",
                "job_revision": expected_job_revision + 1,
            }
            safe_json = canonical_json_bytes(safe_result).decode("utf-8")
            connection.execute(
                sa.text(
                    """
                    INSERT INTO catalog_command_effects (
                        operation_token, operation_kind, operation_digest,
                        site_id, actor_user_id, response_schema_version,
                        response_status_code, safe_result_json, completed_at
                    ) VALUES (
                        :token, 'catalog_export_resume', :digest,
                        :site_id, :actor_user_id, 1, 200,
                        CAST(:safe_result AS JSON), UTC_TIMESTAMP(6)
                    )
                    """
                ),
                {
                    "token": operation_token.bytes,
                    "digest": operation_digest,
                    "site_id": site_id,
                    "actor_user_id": actor_user_id,
                    "safe_result": safe_json,
                },
            )
            connection.execute(
                sa.text(
                    "UPDATE catalog_command_claims SET status = 'completed' "
                    "WHERE operation_token = :token AND status = 'claimed'"
                ),
                {"token": operation_token.bytes},
            )
            audit_payload = {
                **safe_result,
                "previous_job_revision": expected_job_revision,
            }
            audit_bytes = canonical_json_bytes(audit_payload)
            connection.execute(
                sa.text(
                    """
                    INSERT INTO catalog_audit_events (
                        site_id, actor_user_id, event_kind, resource_kind,
                        resource_id, operation_token, safe_payload_json,
                        event_digest
                    ) VALUES (
                        :site_id, :actor_user_id, 'catalog_export_resumed',
                        'catalog_export', :export_id, :token,
                        CAST(:payload AS JSON), :event_digest
                    )
                    """
                ),
                {
                    "site_id": site_id,
                    "actor_user_id": actor_user_id,
                    "export_id": export_id,
                    "token": operation_token.bytes,
                    "payload": audit_bytes.decode("utf-8"),
                    "event_digest": hashlib.sha256(
                        operation_token.bytes + audit_bytes
                    ).digest(),
                },
            )
            return safe_result


__all__ = ("MySqlCatalogExportJobRepository",)
