"""Administrator-only local backup, restore, lock, and worker visibility."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Annotated, Literal, cast

import sqlalchemy as sa
from fastapi import APIRouter, Depends, Request, Response
from pydantic import BaseModel
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session

from app.api.dependencies import (
    get_database_engine,
    get_database_session,
    require_roles,
)
from app.auth.sessions import Principal
from app.maintenance.health import MaintenanceLockMonitor, probe_maintenance_lock
from app.maintenance.worker_status import (
    QueueStatusResponse,
    WorkerFleetStatusResponse,
    read_worker_observability,
)

router = APIRouter(prefix="/api/admin/maintenance", tags=["admin", "maintenance"])
_require_admin = require_roles("admin")
_AdminPrincipal = Annotated[Principal, Depends(_require_admin)]
_DatabaseSession = Annotated[
    Session,
    Depends(get_database_session, scope="function"),
]
_DatabaseEngine = Annotated[Engine, Depends(get_database_engine)]


class BackupSnapshotStatus(BaseModel):
    id: int
    backup_uuid: str
    status: Literal["running", "sealed", "succeeded", "failed"]
    database_name: str
    schema_revision: str
    key_id: str
    raw_file_count: int
    publication_count: int
    version_count: int
    audit_event_count: int
    started_at: datetime
    sealed_at: datetime | None
    completed_at: datetime | None
    failure_code: str | None
    restore_verified_at: datetime | None


class RestoreVerificationStatus(BaseModel):
    id: int
    verification_uuid: str
    backup_uuid: str
    target_database_name: str
    status: Literal["running", "succeeded", "failed"]
    started_at: datetime
    completed_at: datetime | None
    failure_code: str | None


class OutboxStatus(BaseModel):
    pending: int
    processing: int
    completed: int
    failed: int
    oldest_pending_at: datetime | None


class MaintenanceWriteLockStatus(BaseModel):
    held: bool
    owner_connection_id: int | None
    observed_seconds: float
    warning: bool


class MaintenanceStatusResponse(BaseModel):
    backups: list[BackupSnapshotStatus]
    restores: list[RestoreVerificationStatus]
    outbox: OutboxStatus
    write_lock: MaintenanceWriteLockStatus
    observed_at: datetime
    maintenance_active: bool
    worker: WorkerFleetStatusResponse
    queues: list[QueueStatusResponse]


def _utc(value: object) -> datetime | None:
    if value is None:
        return None
    if not isinstance(value, datetime):
        raise RuntimeError("maintenance timestamp has an invalid database type")
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


def _required_utc(value: object) -> datetime:
    resolved = _utc(value)
    if resolved is None:
        raise RuntimeError("required maintenance timestamp is NULL")
    return resolved


@router.get("", response_model=MaintenanceStatusResponse)
def maintenance_status(
    request: Request,
    response: Response,
    _principal: _AdminPrincipal,
    database_session: _DatabaseSession,
    database_engine: _DatabaseEngine,
) -> MaintenanceStatusResponse:
    backup_rows = database_session.execute(
        sa.text(
            """
            SELECT id, LOWER(HEX(backup_uuid)) AS backup_uuid, status,
                   database_name, schema_revision, key_id, raw_file_count,
                   publication_count, version_count, audit_event_count,
                   started_at, sealed_at, completed_at, failure_code,
                   restore_verified_at
            FROM backup_snapshots
            ORDER BY started_at DESC, id DESC
            LIMIT 20
            """
        )
    ).mappings()
    restore_rows = database_session.execute(
        sa.text(
            """
            SELECT verifications.id,
                   LOWER(HEX(verifications.verification_uuid)) AS verification_uuid,
                   LOWER(HEX(snapshots.backup_uuid)) AS backup_uuid,
                   verifications.target_database_name, verifications.status,
                   verifications.started_at, verifications.completed_at,
                   verifications.failure_code
            FROM restore_verifications AS verifications
            INNER JOIN backup_snapshots AS snapshots
                ON snapshots.id = verifications.backup_snapshot_id
            ORDER BY verifications.started_at DESC, verifications.id DESC
            LIMIT 20
            """
        )
    ).mappings()
    outbox_row = (
        database_session.execute(
            sa.text(
                """
            SELECT
                SUM(status = 'pending') AS pending_count,
                SUM(status = 'processing') AS processing_count,
                SUM(status = 'completed') AS completed_count,
                SUM(status = 'failed') AS failed_count,
                MIN(CASE WHEN status = 'pending' THEN available_at END)
                    AS oldest_pending_at
            FROM publication_outbox
            """
            )
        )
        .mappings()
        .one()
    )
    monitor = request.app.state.maintenance_lock_monitor
    if not isinstance(monitor, MaintenanceLockMonitor):
        raise RuntimeError("maintenance lock monitor is unavailable")
    request_connection_id = database_session.scalar(sa.text("SELECT CONNECTION_ID()"))
    if request_connection_id is None:
        raise RuntimeError("database connection ID is unavailable")
    lock = probe_maintenance_lock(
        database_engine,
        monitor,
        ignored_owner_connection_id=int(request_connection_id),
    )
    observed_at, worker, queues = read_worker_observability(
        database_engine,
        maintenance_active=lock.held,
    )
    response.headers["Cache-Control"] = "private, no-store"
    return MaintenanceStatusResponse(
        backups=[
            BackupSnapshotStatus(
                id=int(row["id"]),
                backup_uuid=str(row["backup_uuid"]),
                status=cast(
                    Literal["running", "sealed", "succeeded", "failed"],
                    str(row["status"]),
                ),
                database_name=str(row["database_name"]),
                schema_revision=str(row["schema_revision"]),
                key_id=str(row["key_id"]),
                raw_file_count=int(row["raw_file_count"]),
                publication_count=int(row["publication_count"]),
                version_count=int(row["version_count"]),
                audit_event_count=int(row["audit_event_count"]),
                started_at=_required_utc(row["started_at"]),
                sealed_at=_utc(row["sealed_at"]),
                completed_at=_utc(row["completed_at"]),
                failure_code=(
                    None if row["failure_code"] is None else str(row["failure_code"])
                ),
                restore_verified_at=_utc(row["restore_verified_at"]),
            )
            for row in backup_rows
        ],
        restores=[
            RestoreVerificationStatus(
                id=int(row["id"]),
                verification_uuid=str(row["verification_uuid"]),
                backup_uuid=str(row["backup_uuid"]),
                target_database_name=str(row["target_database_name"]),
                status=cast(
                    Literal["running", "succeeded", "failed"],
                    str(row["status"]),
                ),
                started_at=_required_utc(row["started_at"]),
                completed_at=_utc(row["completed_at"]),
                failure_code=(
                    None if row["failure_code"] is None else str(row["failure_code"])
                ),
            )
            for row in restore_rows
        ],
        outbox=OutboxStatus(
            pending=int(outbox_row["pending_count"] or 0),
            processing=int(outbox_row["processing_count"] or 0),
            completed=int(outbox_row["completed_count"] or 0),
            failed=int(outbox_row["failed_count"] or 0),
            oldest_pending_at=_utc(outbox_row["oldest_pending_at"]),
        ),
        write_lock=MaintenanceWriteLockStatus(
            held=lock.held,
            owner_connection_id=lock.owner_connection_id,
            observed_seconds=round(lock.observed_seconds, 3),
            warning=lock.warning,
        ),
        observed_at=observed_at,
        maintenance_active=lock.held,
        worker=worker,
        queues=queues,
    )
