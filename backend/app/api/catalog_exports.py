"""Catalog snapshot export creation, status, and immutable workbook download."""

from __future__ import annotations

import json

import sqlalchemy as sa
from fastapi import APIRouter, Depends
from pydantic import Field
from starlette.responses import Response

from app.api.catalog_common import (
    CatalogEngine,
    CatalogIdempotencyKey,
    CatalogReadContext,
    CatalogWriteContext,
    catalog_json,
    raise_catalog_error,
    require_catalog_manager,
    require_catalog_session,
    require_matching_token,
)
from app.api.catalog_scope import router as scope_router
from app.api.errors import ApiError
from app.catalog.export_jobs import MySqlCatalogExportJobRepository
from app.catalog.export_service import (
    CATALOG_WORKBOOK_MEDIA_TYPE,
    catalog_download_headers,
)
from app.catalog.models import CatalogWireUuid, StrictCatalogModel
from app.catalog.snapshots import (
    MySqlCatalogSnapshotCoordinator,
    MySqlCatalogSnapshotWriter,
)
from app.config import StorageSettings
from app.imports.storage import ContentStoreError, LocalContentStore

router = APIRouter(
    prefix="/api/catalog",
    tags=["catalog"],
    dependencies=[Depends(require_catalog_session)],
)
router.routes.extend(scope_router.routes)


class CreateCatalogExportRequest(StrictCatalogModel):
    operation_token: CatalogWireUuid
    expected_catalog_publication_revision: int = Field(ge=0)


class ResumeCatalogExportRequest(StrictCatalogModel):
    operation_token: CatalogWireUuid
    expected_job_revision: int = Field(ge=0)


def _status(
    engine: CatalogEngine, *, export_id: int, site_id: int
) -> dict[str, object]:
    with engine.connect() as connection:
        row = (
            connection.execute(
                sa.text(
                    """
                    SELECT exports.id, exports.base_catalog_version_id,
                           exports.catalog_publication_revision,
                           exports.export_status, exports.workbook_status,
                           exports.capacity_violations,
                           exports.artifact_sha256,
                           COALESCE(jobs.failure_reason_code,
                                    exports.failure_reason_code)
                               AS failure_reason_code,
                           exports.created_at, exports.updated_at,
                           jobs.status AS job_status,
                           jobs.job_revision, jobs.execution_phase,
                           jobs.attempt_count, jobs.next_attempt_at,
                           jobs.retry_allowed, jobs.lease_token,
                           jobs.lease_expires_at,
                           EXISTS (
                               SELECT 1
                               FROM worker_instances AS workers
                               WHERE workers.lifecycle_status = 'running'
                                 AND workers.last_heartbeat_at >=
                                     UTC_TIMESTAMP(6) - INTERVAL 30 SECOND
                                 AND JSON_CONTAINS(
                                     workers.supported_queues,
                                     JSON_QUOTE('catalog_export')
                                 )
                           ) AS worker_available
                    FROM catalog_exports AS exports
                    INNER JOIN catalog_jobs AS jobs
                        ON jobs.resource_id = exports.id
                       AND jobs.site_id = exports.site_id
                       AND jobs.job_kind = 'catalog_export'
                       AND jobs.resource_kind = 'catalog_export'
                    WHERE exports.id = :id AND exports.site_id = :site_id
                    """
                ),
                {"id": export_id, "site_id": site_id},
            )
            .mappings()
            .one_or_none()
        )
    if row is None:
        raise ApiError(404, "catalog_export_not_found", "Export was not found.")
    violations = row["capacity_violations"]
    if isinstance(violations, str):
        violations = json.loads(violations)
    return {
        "export_id": int(row["id"]),
        "base_catalog_version_id": row["base_catalog_version_id"],
        "catalog_publication_revision": int(row["catalog_publication_revision"]),
        "export_status": str(row["export_status"]),
        "workbook_status": row["workbook_status"],
        "capacity_violations": violations,
        "artifact_digest": (
            None
            if row["artifact_sha256"] is None
            else "sha256:" + bytes(row["artifact_sha256"]).hex()
        ),
        "failure_reason_code": row["failure_reason_code"],
        "job_status": str(row["job_status"]),
        "job_revision": int(row["job_revision"]),
        "execution_phase": str(row["execution_phase"]),
        "attempt_count": int(row["attempt_count"]),
        "max_attempts": 3,
        "next_attempt_at": row["next_attempt_at"],
        "retry_allowed": bool(row["retry_allowed"]),
        "worker_available": bool(row["worker_available"]),
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
        "permissions": {
            "can_download": row["workbook_status"] == "ready",
            "can_resume": (
                row["job_status"] == "failed"
                and bool(row["retry_allowed"])
                and row["lease_token"] is None
                and row["lease_expires_at"] is None
            ),
        },
    }


@router.post("/exports", status_code=202)
def create_catalog_export(
    request: CreateCatalogExportRequest,
    context: CatalogWriteContext,
    engine: CatalogEngine,
    idempotency_key: CatalogIdempotencyKey,
) -> Response:
    require_catalog_manager(context)
    require_matching_token(idempotency_key, request.operation_token)
    try:
        frozen = MySqlCatalogSnapshotCoordinator(engine).freeze(site_id=context.site_id)
        if (
            frozen.catalog_publication_revision
            != request.expected_catalog_publication_revision
        ):
            raise ApiError(
                409,
                "catalog_publication_revision_conflict",
                "The current catalog changed; reload and retry.",
            )
        created = MySqlCatalogSnapshotWriter(engine).persist_building(
            frozen,
            operation_token=request.operation_token,
            created_by_user_id=context.principal_user_id,
        )
        return catalog_json(
            _status(engine, export_id=created.export_id, site_id=context.site_id),
            status_code=202,
        )
    except ApiError:
        raise
    except Exception as error:
        raise_catalog_error(error)


@router.get("/exports/latest")
def get_latest_catalog_export(
    context: CatalogReadContext,
    engine: CatalogEngine,
) -> Response:
    require_catalog_manager(context)
    try:
        with engine.connect() as connection:
            export_id = connection.scalar(
                sa.text("SELECT MAX(id) FROM catalog_exports WHERE site_id = :site_id"),
                {"site_id": context.site_id},
            )
        return catalog_json(
            {
                "export": (
                    None
                    if export_id is None
                    else _status(
                        engine,
                        export_id=int(export_id),
                        site_id=context.site_id,
                    )
                )
            }
        )
    except Exception as error:
        raise_catalog_error(error)


@router.get("/exports/{export_id}")
def get_catalog_export(
    export_id: int,
    context: CatalogReadContext,
    engine: CatalogEngine,
) -> Response:
    require_catalog_manager(context)
    try:
        return catalog_json(
            _status(engine, export_id=export_id, site_id=context.site_id)
        )
    except ApiError:
        raise
    except Exception as error:
        raise_catalog_error(error)


@router.post("/exports/{export_id}/resume")
def resume_catalog_export(
    export_id: int,
    request: ResumeCatalogExportRequest,
    context: CatalogWriteContext,
    engine: CatalogEngine,
    idempotency_key: CatalogIdempotencyKey,
) -> Response:
    require_catalog_manager(context)
    require_matching_token(idempotency_key, request.operation_token)
    try:
        result = MySqlCatalogExportJobRepository(engine).resume(
            export_id=export_id,
            site_id=context.site_id,
            actor_user_id=context.principal_user_id,
            operation_token=request.operation_token,
            expected_job_revision=request.expected_job_revision,
        )
        return catalog_json(result)
    except Exception as error:
        raise_catalog_error(error)


@router.get("/exports/{export_id}/file", response_class=Response)
def download_catalog_export(
    export_id: int,
    context: CatalogReadContext,
    engine: CatalogEngine,
) -> Response:
    require_catalog_manager(context)
    try:
        with engine.connect() as connection:
            row = (
                connection.execute(
                    sa.text(
                        """
                        SELECT artifact_storage_key, artifact_sha256
                        FROM catalog_exports
                        WHERE id = :id AND site_id = :site_id
                          AND export_status = 'ready'
                          AND workbook_status = 'ready'
                        """
                    ),
                    {"id": export_id, "site_id": context.site_id},
                )
                .mappings()
                .one_or_none()
            )
        if row is None:
            raise ApiError(409, "catalog_export_not_ready", "Export is not ready.")
        storage = StorageSettings.from_env()
        store = LocalContentStore(storage.root, storage.max_upload_bytes)
        storage_key = str(row["artifact_storage_key"])
        expected_size = (storage.root / storage_key).stat().st_size
        content = store.read_bytes(
            storage_key,
            bytes(row["artifact_sha256"]).hex(),
            expected_size,
        )
        headers = catalog_download_headers(export_id)
        headers.update(
            {
                "Cache-Control": "private, no-store",
                "X-Content-Type-Options": "nosniff",
            }
        )
        return Response(
            content=content, media_type=CATALOG_WORKBOOK_MEDIA_TYPE, headers=headers
        )
    except ApiError:
        raise
    except ContentStoreError as error:
        raise ApiError(
            409,
            "catalog_export_file_unavailable",
            "The export file is unavailable.",
        ) from error
    except Exception as error:
        raise_catalog_error(error)


__all__ = (
    "CreateCatalogExportRequest",
    "ResumeCatalogExportRequest",
    "router",
)
