"""Catalog workbook materialization and fixed download metadata."""

from __future__ import annotations

import hashlib
import io
import json
import re
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Protocol
from uuid import UUID, uuid4

import sqlalchemy as sa
from sqlalchemy.engine import Connection, Engine, RowMapping

from app.catalog.canonical_json import canonical_json_bytes
from app.catalog.ooxml import (
    CapacityViolation,
    CatalogWorkbookCapacityError,
    CatalogWorkbookUnsafeError,
)
from app.catalog.workbook import (
    CatalogWorkbookData,
    parse_catalog_workbook,
    render_catalog_workbook,
)
from app.imports.storage import BinaryReadStream, StagedContent, StoredContent

CATALOG_WORKBOOK_MEDIA_TYPE = (
    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
)
_REASON = re.compile(r"[a-z][a-z0-9_]{0,63}\Z", re.ASCII)


class CatalogExportFinalizationError(RuntimeError):
    code = "catalog_export_finalization_conflict"

    def __init__(self) -> None:
        super().__init__(self.code)


@dataclass(frozen=True, slots=True)
class CatalogExportCommand:
    export_id: int
    operation_token: UUID
    payload_digest: bytes
    workbook: CatalogWorkbookData
    job_id: int | None = None
    job_revision: int = 0
    lease_token: UUID | None = None
    fencing_token: int = 0
    attempt_count: int = 0

    def __post_init__(self) -> None:
        if isinstance(self.export_id, bool) or self.export_id < 1:
            raise ValueError("export_id must be positive")
        if self.operation_token.version != 4:
            raise ValueError("operation_token must be UUID v4")
        if len(self.payload_digest) != 32:
            raise ValueError("payload_digest must contain 32 bytes")
        if self.job_id is not None and self.job_id < 1:
            raise ValueError("job_id must be positive")
        if self.job_id is not None and self.lease_token is None:
            raise ValueError("leased commands require a lease token")
        if min(self.job_revision, self.fencing_token, self.attempt_count) < 0:
            raise ValueError("job counters must not be negative")


@dataclass(frozen=True, slots=True)
class CatalogExportResult:
    export_id: int
    export_status: str
    workbook_status: str | None
    artifact: StoredContent | None
    capacity_violations: tuple[CapacityViolation, ...]
    failure_reason: str | None


class CatalogExportStore(Protocol):
    def write_stream(self, token: UUID, source: BinaryReadStream) -> StagedContent: ...

    def promote(self, staged: StagedContent) -> StoredContent: ...

    def discard_staged(self, staged: StagedContent) -> None: ...


class CatalogExportFinalizer(Protocol):
    def finalize_ready(
        self,
        command: CatalogExportCommand,
        *,
        artifact: StoredContent | None,
        capacity_violations: tuple[CapacityViolation, ...],
    ) -> None: ...

    def finalize_failed(
        self,
        command: CatalogExportCommand,
        *,
        reason: str,
    ) -> None: ...


def catalog_download_filename(export_id: int) -> str:
    if isinstance(export_id, bool) or not isinstance(export_id, int) or export_id < 1:
        raise ValueError("export_id must be a positive integer")
    suffix = hashlib.sha256(str(export_id).encode("utf-8")).hexdigest()[:16]
    return f"product-catalog-{suffix}.xlsx"


def catalog_download_headers(export_id: int) -> dict[str, str]:
    filename = catalog_download_filename(export_id)
    return {
        "Content-Type": CATALOG_WORKBOOK_MEDIA_TYPE,
        "Content-Disposition": f'attachment; filename="{filename}"',
        "X-Content-Type-Options": "nosniff",
        "Cache-Control": "private, no-store",
    }


class CatalogExportMaterializer:
    """Render, uploader-round-trip, publish, and atomically finalize an export."""

    def __init__(
        self,
        *,
        store: CatalogExportStore,
        finalizer: CatalogExportFinalizer,
    ) -> None:
        self._store = store
        self._finalizer = finalizer

    def materialize(self, command: CatalogExportCommand) -> CatalogExportResult:
        try:
            content = render_catalog_workbook(command.workbook)
        except CatalogWorkbookCapacityError as error:
            self._finalizer.finalize_ready(
                command,
                artifact=None,
                capacity_violations=error.violations,
            )
            return CatalogExportResult(
                command.export_id,
                "ready",
                "capacity_exceeded",
                None,
                error.violations,
                None,
            )
        except CatalogWorkbookUnsafeError as error:
            self._finalizer.finalize_failed(command, reason=error.reason)
            return CatalogExportResult(
                command.export_id, "failed", None, None, (), error.reason
            )

        staged = self._store.write_stream(uuid4(), io.BytesIO(content))
        try:
            parsed = parse_catalog_workbook(content)
            if parsed.rows != command.workbook.rows:
                raise CatalogWorkbookUnsafeError("generator_round_trip_mismatch")
            artifact = self._store.promote(staged)
            self._finalizer.finalize_ready(
                command,
                artifact=artifact,
                capacity_violations=(),
            )
        except CatalogWorkbookCapacityError as error:
            self._finalizer.finalize_ready(
                command,
                artifact=None,
                capacity_violations=error.violations,
            )
            return CatalogExportResult(
                command.export_id,
                "ready",
                "capacity_exceeded",
                None,
                error.violations,
                None,
            )
        except CatalogWorkbookUnsafeError as error:
            self._finalizer.finalize_failed(command, reason=error.reason)
            return CatalogExportResult(
                command.export_id, "failed", None, None, (), error.reason
            )
        finally:
            self._store.discard_staged(staged)

        return CatalogExportResult(
            command.export_id, "ready", "ready", artifact, (), None
        )


def _violation_payload(
    violations: tuple[CapacityViolation, ...],
) -> list[dict[str, str | None]]:
    return [
        {
            "code": row.code,
            "sheet_or_member": row.sheet_or_member,
            "actual": row.actual,
            "limit": row.limit,
            "unit": row.unit,
        }
        for row in violations
    ]


class MySqlCatalogExportFinalizer:
    """Advance only the frozen building group supplied by Task 6."""

    def __init__(self, engine: Engine) -> None:
        self._engine = engine

    @staticmethod
    def _locked(connection: Connection, command: CatalogExportCommand) -> RowMapping:
        locked_export = connection.scalar(
            sa.text("SELECT id FROM catalog_exports WHERE id = :export_id FOR UPDATE"),
            {"export_id": command.export_id},
        )
        if locked_export is None:
            raise CatalogExportFinalizationError()
        row = (
            connection.execute(
                sa.text(
                    """
                    SELECT exports.id, exports.site_id, exports.operation_token,
                           exports.export_status, exports.workbook_status,
                           exports.capacity_violations, exports.artifact_sha256,
                           exports.artifact_storage_key,
                           exports.failure_reason_code,
                           payloads.payload_digest,
                           tuples.id AS fact_tuple_id,
                           tuples.status AS fact_tuple_status,
                           snapshots.id AS publication_snapshot_id,
                           snapshots.status AS publication_snapshot_status
                    FROM catalog_exports AS exports
                    INNER JOIN catalog_export_payloads AS payloads
                        ON payloads.export_id = exports.id
                       AND payloads.site_id = exports.site_id
                    INNER JOIN fact_snapshot_tuples AS tuples
                        ON tuples.id = exports.fact_snapshot_tuple_id
                       AND tuples.site_id = exports.site_id
                    INNER JOIN publication_snapshots AS snapshots
                        ON snapshots.id = tuples.publication_snapshot_id
                       AND snapshots.site_id = tuples.site_id
                    WHERE exports.id = :export_id
                    """
                ),
                {"export_id": command.export_id},
            )
            .mappings()
            .one_or_none()
        )
        if (
            row is None
            or bytes(row["operation_token"]) != command.operation_token.bytes
            or bytes(row["payload_digest"]) != command.payload_digest
        ):
            raise CatalogExportFinalizationError()
        locked_snapshot = connection.execute(
            sa.text(
                "SELECT id, status FROM publication_snapshots "
                "WHERE id = :snapshot_id FOR UPDATE"
            ),
            {"snapshot_id": int(row["publication_snapshot_id"])},
        ).one_or_none()
        if (
            locked_snapshot is None
            or locked_snapshot.status != row["publication_snapshot_status"]
        ):
            raise CatalogExportFinalizationError()
        return row

    @staticmethod
    def _terminal_group_is(row: RowMapping, status: str) -> bool:
        return all(
            value == status
            for value in (
                row["export_status"],
                row["publication_snapshot_status"],
                row["fact_tuple_status"],
            )
        )

    @staticmethod
    def _require_active_job(
        connection: Connection, command: CatalogExportCommand
    ) -> None:
        if command.job_id is None:
            return
        if command.lease_token is None:
            raise CatalogExportFinalizationError()
        row = (
            connection.execute(
                sa.text(
                    """
                    SELECT resource_id, status, job_revision, lease_token,
                           fencing_token, lease_expires_at
                    FROM catalog_jobs
                    WHERE id = :job_id
                    FOR UPDATE
                    """
                ),
                {"job_id": command.job_id},
            )
            .mappings()
            .one_or_none()
        )
        if (
            row is None
            or int(row["resource_id"]) != command.export_id
            or row["status"] != "running"
            or int(row["job_revision"]) != command.job_revision
            or bytes(row["lease_token"]) != command.lease_token.bytes
            or int(row["fencing_token"]) != command.fencing_token
            or row["lease_expires_at"] is None
            or row["lease_expires_at"] <= datetime.now(UTC).replace(tzinfo=None)
        ):
            raise CatalogExportFinalizationError()

    @staticmethod
    def _finish_job(
        connection: Connection,
        command: CatalogExportCommand,
        *,
        status: str,
        phase: str,
        retry_allowed: bool,
        reason: str | None,
        result_digest: bytes | None,
    ) -> None:
        if command.job_id is None or command.lease_token is None:
            return
        updated = connection.execute(
            sa.text(
                """
                UPDATE catalog_jobs
                SET status = :status, job_revision = job_revision + 1,
                    lease_token = NULL, lease_expires_at = NULL,
                    retry_allowed = :retry_allowed,
                    failure_reason_code = :reason,
                    result_digest = :result_digest,
                    execution_phase = :phase,
                    last_attempt_completed_at = UTC_TIMESTAMP(6)
                WHERE id = :job_id AND status = 'running'
                  AND job_revision = :job_revision
                  AND lease_token = :lease_token
                  AND fencing_token = :fencing_token
                """
            ),
            {
                "status": status,
                "retry_allowed": retry_allowed,
                "reason": reason,
                "result_digest": result_digest,
                "phase": phase,
                "job_id": command.job_id,
                "job_revision": command.job_revision,
                "lease_token": command.lease_token.bytes,
                "fencing_token": command.fencing_token,
            },
        )
        if updated.rowcount != 1:
            raise CatalogExportFinalizationError()

    def finalize_ready(
        self,
        command: CatalogExportCommand,
        *,
        artifact: StoredContent | None,
        capacity_violations: tuple[CapacityViolation, ...],
    ) -> None:
        if (artifact is None) == (not capacity_violations):
            raise ValueError(
                "ready artifact and capacity violations must be mutually exclusive"
            )
        workbook_status = "ready" if artifact is not None else "capacity_exceeded"
        payload = _violation_payload(capacity_violations)
        payload_json = canonical_json_bytes(payload).decode("utf-8")
        with self._engine.begin() as connection:
            row = self._locked(connection, command)
            self._require_active_job(connection, command)
            if self._terminal_group_is(row, "ready"):
                existing_payload = row["capacity_violations"]
                if isinstance(existing_payload, str):
                    existing_payload = json.loads(existing_payload)
                if (
                    row["workbook_status"] != workbook_status
                    or existing_payload != payload
                    or (
                        artifact is not None
                        and (
                            bytes(row["artifact_sha256"])
                            != bytes.fromhex(artifact.sha256_hex)
                            or row["artifact_storage_key"] != artifact.storage_key
                        )
                    )
                ):
                    raise CatalogExportFinalizationError()
                return
            if not self._terminal_group_is(row, "building"):
                raise CatalogExportFinalizationError()
            updated = connection.execute(
                sa.text(
                    """
                    UPDATE catalog_exports
                    SET export_status = 'ready',
                        workbook_status = :workbook_status,
                        capacity_violations = CAST(:violations AS JSON),
                        artifact_sha256 = :artifact_sha256,
                        artifact_storage_key = :artifact_storage_key,
                        failure_reason_code = NULL
                    WHERE id = :export_id AND export_status = 'building'
                    """
                ),
                {
                    "export_id": command.export_id,
                    "workbook_status": workbook_status,
                    "violations": payload_json,
                    "artifact_sha256": (
                        None if artifact is None else bytes.fromhex(artifact.sha256_hex)
                    ),
                    "artifact_storage_key": (
                        None if artifact is None else artifact.storage_key
                    ),
                },
            )
            advanced = connection.execute(
                sa.text(
                    """
                    UPDATE publication_snapshots
                    SET status = 'ready'
                    WHERE id = :snapshot_id AND status = 'building'
                    """
                ),
                {"snapshot_id": int(row["publication_snapshot_id"])},
            )
            if updated.rowcount != 1 or advanced.rowcount != 1:
                raise CatalogExportFinalizationError()
            self._finish_job(
                connection,
                command,
                status="succeeded",
                phase="completed",
                retry_allowed=False,
                reason=None,
                result_digest=(
                    command.payload_digest
                    if artifact is None
                    else bytes.fromhex(artifact.sha256_hex)
                ),
            )

    def finalize_failed(
        self,
        command: CatalogExportCommand,
        *,
        reason: str,
    ) -> None:
        if not isinstance(reason, str) or _REASON.fullmatch(reason) is None:
            raise ValueError("failure reason must be a stable content-free code")
        with self._engine.begin() as connection:
            row = self._locked(connection, command)
            self._require_active_job(connection, command)
            if self._terminal_group_is(row, "failed"):
                if row["failure_reason_code"] != reason:
                    raise CatalogExportFinalizationError()
                return
            if not self._terminal_group_is(row, "building"):
                raise CatalogExportFinalizationError()
            updated = connection.execute(
                sa.text(
                    """
                    UPDATE catalog_exports
                    SET export_status = 'failed', failure_reason_code = :reason
                    WHERE id = :export_id AND export_status = 'building'
                    """
                ),
                {"export_id": command.export_id, "reason": reason},
            )
            advanced = connection.execute(
                sa.text(
                    """
                    UPDATE publication_snapshots
                    SET status = 'failed'
                    WHERE id = :snapshot_id AND status = 'building'
                    """
                ),
                {"snapshot_id": int(row["publication_snapshot_id"])},
            )
            if updated.rowcount != 1 or advanced.rowcount != 1:
                raise CatalogExportFinalizationError()
            self._finish_job(
                connection,
                command,
                status="failed",
                phase="failed",
                retry_allowed=False,
                reason=reason,
                result_digest=None,
            )


__all__ = (
    "CATALOG_WORKBOOK_MEDIA_TYPE",
    "CatalogExportCommand",
    "CatalogExportFinalizationError",
    "CatalogExportMaterializer",
    "CatalogExportResult",
    "MySqlCatalogExportFinalizer",
    "catalog_download_filename",
    "catalog_download_headers",
)
