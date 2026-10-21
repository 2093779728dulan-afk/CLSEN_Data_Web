"""Strict catalog import upload, review, and approval workflow routes."""

from __future__ import annotations

import io
import json
import tempfile
from datetime import UTC, datetime, timedelta
from typing import Annotated, Literal, cast
from uuid import uuid4

import sqlalchemy as sa
from fastapi import APIRouter, Depends, Header, Query, Request
from pydantic import Field, JsonValue, StringConstraints
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
from app.api.errors import ApiError
from app.catalog.commands import CatalogDecisionMutation
from app.catalog.export_service import CATALOG_WORKBOOK_MEDIA_TYPE
from app.catalog.import_repository import MySqlCatalogImportRepository
from app.catalog.import_service import DraftProjection, project_catalog_workbook
from app.catalog.inventory import load_catalog_identity_inventory
from app.catalog.models import CatalogWireUuid, StrictCatalogModel
from app.catalog.service import CatalogService
from app.catalog.upload_service import (
    CatalogRawUploadCommand,
    CatalogRawUploadService,
    CatalogUploadStore,
    MySqlCatalogUploadRepository,
    parse_catalog_upload_metadata,
)
from app.catalog.workbook import workbook_from_export_payload
from app.catalog.workflow import (
    CatalogWorkflowState,
    WorkflowActor,
    permissions_for,
)
from app.config import StorageSettings
from app.imports.storage import ContentStoreError, LocalContentStore

router = APIRouter(
    prefix="/api/catalog",
    tags=["catalog"],
    dependencies=[Depends(require_catalog_session)],
)
Digest = Annotated[str, StringConstraints(pattern=r"^sha256:[0-9a-f]{64}$")]


class ImportRevisionRequest(StrictCatalogModel):
    operation_token: CatalogWireUuid
    expected_workflow_revision: int = Field(ge=0)


class ImportReasonRequest(ImportRevisionRequest):
    reason: str = Field(min_length=10, max_length=1000)


class FromExportImportRequest(StrictCatalogModel):
    operation_token: CatalogWireUuid
    export_id: int = Field(ge=1)
    expected_catalog_publication_revision: int = Field(ge=0)


class DecisionMutationRequest(StrictCatalogModel):
    mutation_id: CatalogWireUuid
    type: str = Field(min_length=1, max_length=64)
    row_key: str | None = Field(default=None, min_length=1, max_length=64)
    decision_group_key: str | None = Field(default=None, min_length=1, max_length=64)
    payload: dict[str, JsonValue]


class ApplyDecisionsRequest(ImportRevisionRequest):
    mutations: tuple[DecisionMutationRequest, ...] = Field(
        min_length=1,
        max_length=500,
        strict=False,
    )


class ApproveImportRequest(ImportRevisionRequest):
    expected_catalog_publication_revision: int = Field(ge=0)
    projection_id: int = Field(ge=1)
    projection_digest: Digest
    reason: str = Field(min_length=10, max_length=1000)


class RebaseImportRequest(ImportRevisionRequest):
    replacement_export_id: int = Field(ge=1)
    expected_catalog_publication_revision: int = Field(ge=0)


class ResumeImportRequest(ImportRevisionRequest):
    expected_parse_attempt_revision: int = Field(ge=0)


def _load_json(value: object) -> object:
    return json.loads(value) if isinstance(value, str) else value


def _projection_for_export(
    engine: CatalogEngine, *, export_id: int, site_id: int
) -> DraftProjection:
    with engine.connect() as connection:
        row = (
            connection.execute(
                sa.text(
                    """
                    SELECT exports.id, exports.base_catalog_version_id,
                           exports.normalization_manifest_id, exports.created_at,
                           exports.export_status, payloads.candidate_payload_json,
                           JSON_EXTRACT(
                               payloads.evidence_payload_json,
                               '$.summaries'
                           ) AS evidence_summaries_json,
                           snapshots.snapshot_digest,
                           sites.code AS site_code,
                           scopes.seller_account_display_name
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
                    INNER JOIN report_source_scopes AS scopes
                      ON scopes.id = tuples.report_source_scope_id
                     AND scopes.site_id = tuples.site_id
                    INNER JOIN sites ON sites.id = exports.site_id
                    WHERE exports.id = :id AND exports.site_id = :site_id
                    """
                ),
                {"id": export_id, "site_id": site_id},
            )
            .mappings()
            .one_or_none()
        )
    if row is None or row["export_status"] != "ready":
        raise ApiError(409, "catalog_export_not_ready", "Export is not ready.")
    generated_at = row["created_at"]
    if not isinstance(generated_at, datetime):
        raise RuntimeError("catalog export timestamp is invalid")
    if generated_at.tzinfo is None:
        generated_at = generated_at.replace(tzinfo=UTC)
    candidates = _load_json(row["candidate_payload_json"])
    evidence_summaries = _load_json(row["evidence_summaries_json"])
    if not isinstance(candidates, dict) or not isinstance(evidence_summaries, list):
        raise RuntimeError("catalog export payload is invalid")
    evidence = {"summaries": evidence_summaries}
    base_catalog_version_id = (
        None
        if row["base_catalog_version_id"] is None
        else int(row["base_catalog_version_id"])
    )
    with engine.connect() as connection:
        inventory = load_catalog_identity_inventory(
            connection,
            site_id=site_id,
            catalog_version_id=base_catalog_version_id,
        )
    workbook = workbook_from_export_payload(
        export_id=export_id,
        site_code=str(row["site_code"]),
        seller_account_display_name=str(row["seller_account_display_name"]),
        base_catalog_version_id=base_catalog_version_id,
        snapshot_digest=bytes(row["snapshot_digest"]),
        normalization_manifest_id=str(row["normalization_manifest_id"]),
        generated_at=generated_at,
        candidates=candidates,
        evidence=evidence,
        existing_styles=inventory.styles,
        existing_skus=inventory.skus,
    )
    return project_catalog_workbook(workbook)


def _detail(
    engine: CatalogEngine, *, import_id: int, context: CatalogReadContext
) -> dict[str, object]:
    with engine.connect() as connection:
        row = (
            connection.execute(
                sa.text(
                    """
                    SELECT imports.*, attempts.recoverable,
                           attempts.failure_reason_code,
                           publications.catalog_publication_revision
                    FROM catalog_imports AS imports
                    LEFT JOIN catalog_parse_attempts AS attempts
                      ON attempts.import_id = imports.id
                     AND attempts.attempt_revision = imports.parse_attempt_revision
                    LEFT JOIN product_catalog_publications AS publications
                      ON publications.site_id = imports.site_id
                    WHERE imports.id = :id AND imports.site_id = :site_id
                    """
                ),
                {"id": import_id, "site_id": context.site_id},
            )
            .mappings()
            .one_or_none()
        )
    if row is None:
        raise ApiError(404, "catalog_import_not_found", "Import was not found.")
    state = CatalogWorkflowState(
        status=str(row["status"]),
        source_kind=str(row["source_kind"]),
        owner_user_id=int(row["owner_user_id"]),
        submitted_by_user_id=(
            None
            if row["submitted_by_user_id"] is None
            else int(row["submitted_by_user_id"])
        ),
        recoverable=bool(row["recoverable"]),
        active_parse_lease=str(row["status"]) == "parsing",
    )
    permissions = permissions_for(
        state,
        WorkflowActor(context.principal_user_id, context.principal_roles),
    )
    if not permissions.can_view:
        raise ApiError(403, "role_forbidden", "Permission was denied.")
    permission_payload = {
        field: getattr(permissions, field) for field in permissions.__slots__
    }
    permission_payload["can_submit"] = (
        permissions.can_submit and row["validation_run_id"] is not None
    )
    permission_payload["can_resume"] = (
        state.status == "parse_failed"
        and state.recoverable
        and (context.is_admin or context.principal_user_id == state.owner_user_id)
    )
    with engine.connect() as connection:
        issues = (
            connection.execute(
                sa.text("""
                SELECT section, row_key, severity, reason_code,
                       JSON_UNQUOTE(JSON_EXTRACT(safe_detail_json, '$.field'))
                         AS field
                FROM catalog_import_issues
                WHERE import_id = :id AND site_id = :site_id
                  AND workflow_revision = (
                    SELECT MAX(workflow_revision) FROM catalog_import_rows
                    WHERE import_id = :id AND site_id = :site_id
                      AND workflow_revision <= :revision
                  )
                ORDER BY section, row_key, reason_code LIMIT 500
            """),
                {
                    "id": import_id,
                    "site_id": context.site_id,
                    "revision": row["workflow_revision"],
                },
            )
            .mappings()
            .all()
        )
        approved_version = connection.execute(
            sa.text("""
                SELECT version_number FROM product_catalog_versions
                WHERE source_import_id = :id AND site_id = :site_id
                ORDER BY version_number LIMIT 1
            """),
            {"id": import_id, "site_id": context.site_id},
        ).scalar_one_or_none()
    return {
        "issues": [dict(issue) for issue in issues],
        "approved_catalog_version_number": approved_version,
        "import_id": int(row["id"]),
        "source_kind": str(row["source_kind"]),
        "status": str(row["status"]),
        "workflow_revision": int(row["workflow_revision"]),
        "parse_attempt_revision": int(row["parse_attempt_revision"]),
        "export_id": int(row["export_id"]),
        "base_catalog_version_id": row["base_catalog_version_id"],
        "validation_run_id": row["validation_run_id"],
        "submitted_by_user_id": row["submitted_by_user_id"],
        "failure_reason_code": row["failure_reason_code"],
        "has_original_file": row["raw_file_id"] is not None,
        "catalog_publication_revision": int(row["catalog_publication_revision"] or 0),
        "permissions": permission_payload,
    }


@router.post("/imports", status_code=202)
async def upload_catalog_import(
    request: Request,
    context: CatalogWriteContext,
    engine: CatalogEngine,
    idempotency_key: CatalogIdempotencyKey,
    original_filename: Annotated[str, Header(alias="X-Original-Filename")],
    content_length: Annotated[str, Header(alias="Content-Length")],
) -> Response:
    require_catalog_manager(context)
    storage = StorageSettings.from_env()
    try:
        metadata = parse_catalog_upload_metadata(
            idempotency_key=str(idempotency_key),
            original_filename=original_filename,
            content_type=request.headers.get("Content-Type", ""),
            content_length=content_length,
            configured_max_upload_bytes=storage.max_upload_bytes,
        )
        with tempfile.SpooledTemporaryFile(
            max_size=min(metadata.effective_max_upload_bytes, 1_048_576)
        ) as spool:
            received = 0
            async for chunk in request.stream():
                received += len(chunk)
                if received > metadata.effective_max_upload_bytes:
                    raise ApiError(
                        413,
                        "catalog_upload_too_large",
                        "The upload is too large.",
                    )
                spool.write(chunk)
            spool.seek(0)
            service = CatalogRawUploadService(
                store=cast(
                    CatalogUploadStore,
                    LocalContentStore(storage.root, storage.max_upload_bytes),
                ),
                repository=MySqlCatalogUploadRepository(engine),
                configured_max_upload_bytes=storage.max_upload_bytes,
            )
            result = service.upload(
                cast(io.BufferedIOBase, spool),
                CatalogRawUploadCommand(
                    metadata.operation_token,
                    metadata.original_filename,
                    metadata.declared_media_type,
                    metadata.declared_content_length,
                    context.site_id,
                    context.principal_user_id,
                ),
            )
        return catalog_json(result, status_code=202)
    except ApiError:
        raise
    except Exception as error:
        raise_catalog_error(error)


@router.post("/imports/from-export", status_code=201)
def create_import_from_export(
    request: FromExportImportRequest,
    context: CatalogWriteContext,
    engine: CatalogEngine,
    idempotency_key: CatalogIdempotencyKey,
) -> Response:
    require_catalog_manager(context)
    require_matching_token(idempotency_key, request.operation_token)
    try:
        projection = _projection_for_export(
            engine, export_id=request.export_id, site_id=context.site_id
        )
        import_id = MySqlCatalogImportRepository(engine).create_online_from_export(
            site_id=context.site_id,
            owner_user_id=context.principal_user_id,
            operation_token=request.operation_token,
            export_id=request.export_id,
            expected_catalog_publication_revision=request.expected_catalog_publication_revision,
            projection=projection,
        )
        return catalog_json(
            _detail(engine, import_id=import_id, context=context), status_code=201
        )
    except ApiError:
        raise
    except Exception as error:
        raise_catalog_error(error)


@router.get("/imports")
def list_catalog_imports(
    context: CatalogReadContext,
    engine: CatalogEngine,
    page: Annotated[int, Query(ge=1)] = 1,
) -> Response:
    """Recover existing review batches without creating new candidates."""
    require_catalog_manager(context)
    with engine.connect() as connection:
        rows = (
            connection.execute(
                sa.text(
                    "SELECT id AS import_id, source_kind, status, workflow_revision "
                    "FROM catalog_imports WHERE site_id = :site_id "
                    "ORDER BY id DESC LIMIT 21 OFFSET :offset"
                ),
                {"site_id": context.site_id, "offset": (page - 1) * 20},
            )
            .mappings()
            .all()
        )
    return catalog_json(
        {
            "items": [dict(row) for row in rows[:20]],
            "page": page,
            "has_next": len(rows) > 20,
        }
    )


@router.get("/imports/{import_id}")
def get_catalog_import(
    import_id: int, context: CatalogReadContext, engine: CatalogEngine
) -> Response:
    require_catalog_manager(context)
    try:
        return catalog_json(_detail(engine, import_id=import_id, context=context))
    except ApiError:
        raise
    except Exception as error:
        raise_catalog_error(error)


@router.get("/imports/{import_id}/rows/{section}")
def get_catalog_import_rows(
    import_id: int,
    section: Literal["styles", "skus", "mappings", "exceptions", "evidence"],
    context: CatalogReadContext,
    engine: CatalogEngine,
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=50, ge=1, le=200),
    workflow_revision: int | None = Query(default=None, ge=0),
) -> Response:
    require_catalog_manager(context)
    try:
        return catalog_json(
            MySqlCatalogImportRepository(engine).page_rows(
                import_id=import_id,
                site_id=context.site_id,
                section=section,
                page=page,
                page_size=page_size,
                at_workflow_revision=workflow_revision,
            )
        )
    except Exception as error:
        raise_catalog_error(error)


@router.get("/imports/{import_id}/identity-owners/{row_key}")
def get_catalog_identity_owners(
    import_id: int, row_key: str, context: CatalogReadContext, engine: CatalogEngine
) -> Response:
    require_catalog_manager(context)
    from app.catalog.identity_conflicts import identity_owners

    try:
        return catalog_json(
            identity_owners(
                engine, site_id=context.site_id, import_id=import_id, row_key=row_key
            )
        )
    except Exception as error:
        raise_catalog_error(error)


def _command_response(command: object) -> Response:
    return catalog_json(command, status_code=getattr(command, "status_code", 200))


@router.post("/imports/{import_id}/decisions")
def apply_catalog_decisions(
    import_id: int,
    request: ApplyDecisionsRequest,
    context: CatalogWriteContext,
    engine: CatalogEngine,
    idempotency_key: CatalogIdempotencyKey,
) -> Response:
    require_catalog_manager(context)
    require_matching_token(idempotency_key, request.operation_token)
    try:
        mutations = tuple(
            CatalogDecisionMutation(
                mutation.mutation_id,
                mutation.type,
                mutation.row_key,
                mutation.decision_group_key,
                mutation.payload,
            )
            for mutation in request.mutations
        )
        return _command_response(
            MySqlCatalogImportRepository(engine).apply_decisions(
                import_id=import_id,
                site_id=context.site_id,
                actor_user_id=context.principal_user_id,
                operation_token=request.operation_token,
                expected_workflow_revision=request.expected_workflow_revision,
                mutations=mutations,
            )
        )
    except Exception as error:
        raise_catalog_error(error)


@router.post("/imports/{import_id}/validate")
def validate_catalog_import(
    import_id: int,
    request: ImportRevisionRequest,
    context: CatalogWriteContext,
    engine: CatalogEngine,
    idempotency_key: CatalogIdempotencyKey,
) -> Response:
    require_catalog_manager(context)
    require_matching_token(idempotency_key, request.operation_token)
    try:
        return _command_response(
            MySqlCatalogImportRepository(engine).validate_import(
                import_id=import_id,
                site_id=context.site_id,
                actor_user_id=context.principal_user_id,
                operation_token=request.operation_token,
                expected_workflow_revision=request.expected_workflow_revision,
            )
        )
    except Exception as error:
        raise_catalog_error(error)


def _transition(
    command: str,
    import_id: int,
    request: ImportRevisionRequest,
    context: CatalogWriteContext,
    engine: CatalogEngine,
    *,
    reason: str | None = None,
) -> Response:
    require_catalog_manager(context)
    try:
        return _command_response(
            MySqlCatalogImportRepository(engine).transition_import(
                import_id=import_id,
                site_id=context.site_id,
                actor_user_id=context.principal_user_id,
                operation_token=request.operation_token,
                expected_workflow_revision=request.expected_workflow_revision,
                command=command,
                reason=reason,
            )
        )
    except Exception as error:
        raise_catalog_error(error)


@router.post("/imports/{import_id}/submit")
def submit_catalog_import(
    import_id: int,
    request: ImportRevisionRequest,
    context: CatalogWriteContext,
    engine: CatalogEngine,
    idempotency_key: CatalogIdempotencyKey,
) -> Response:
    require_matching_token(idempotency_key, request.operation_token)
    return _transition("submit", import_id, request, context, engine)


@router.post("/imports/{import_id}/approval-preview")
def preview_catalog_import(
    import_id: int,
    request: ImportRevisionRequest,
    context: CatalogWriteContext,
    engine: CatalogEngine,
    idempotency_key: CatalogIdempotencyKey,
) -> Response:
    require_catalog_manager(context)
    require_matching_token(idempotency_key, request.operation_token)
    try:
        value = CatalogService(engine).preview_import(
            import_id=import_id,
            site_id=context.site_id,
            actor_user_id=context.principal_user_id,
            actor_roles=context.principal_roles,
            operation_token=request.operation_token,
            expected_workflow_revision=request.expected_workflow_revision,
            now=datetime.now(UTC),
        )
        return catalog_json(value)
    except Exception as error:
        raise_catalog_error(error)


@router.post("/imports/{import_id}/approve")
def approve_catalog_import(
    import_id: int,
    request: ApproveImportRequest,
    context: CatalogWriteContext,
    engine: CatalogEngine,
    idempotency_key: CatalogIdempotencyKey,
) -> Response:
    require_catalog_manager(context)
    require_matching_token(idempotency_key, request.operation_token)
    try:
        result = CatalogService(engine).approve_import(
            import_id=import_id,
            site_id=context.site_id,
            actor_user_id=context.principal_user_id,
            actor_roles=context.principal_roles,
            operation_token=request.operation_token,
            expected_workflow_revision=request.expected_workflow_revision,
            expected_catalog_publication_revision=request.expected_catalog_publication_revision,
            projection_id=request.projection_id,
            projection_digest=bytes.fromhex(
                request.projection_digest.removeprefix("sha256:")
            ),
            reason=request.reason,
            now=datetime.now(UTC),
        )
        return catalog_json(result)
    except Exception as error:
        raise_catalog_error(error)


@router.post("/imports/{import_id}/reject")
def reject_catalog_import(
    import_id: int,
    request: ImportReasonRequest,
    context: CatalogWriteContext,
    engine: CatalogEngine,
    idempotency_key: CatalogIdempotencyKey,
) -> Response:
    require_matching_token(idempotency_key, request.operation_token)
    return _transition(
        "reject", import_id, request, context, engine, reason=request.reason
    )


@router.post("/imports/{import_id}/withdraw")
def withdraw_catalog_import(
    import_id: int,
    request: ImportReasonRequest,
    context: CatalogWriteContext,
    engine: CatalogEngine,
    idempotency_key: CatalogIdempotencyKey,
) -> Response:
    require_matching_token(idempotency_key, request.operation_token)
    return _transition(
        "withdraw", import_id, request, context, engine, reason=request.reason
    )


@router.post("/imports/{import_id}/rebase", status_code=201)
def rebase_catalog_import(
    import_id: int,
    request: RebaseImportRequest,
    context: CatalogWriteContext,
    engine: CatalogEngine,
    idempotency_key: CatalogIdempotencyKey,
) -> Response:
    require_catalog_manager(context)
    require_matching_token(idempotency_key, request.operation_token)
    try:
        projection = _projection_for_export(
            engine, export_id=request.replacement_export_id, site_id=context.site_id
        )
        command = MySqlCatalogImportRepository(engine).rebase_import(
            import_id=import_id,
            site_id=context.site_id,
            actor_user_id=context.principal_user_id,
            operation_token=request.operation_token,
            expected_workflow_revision=request.expected_workflow_revision,
            replacement_export_id=request.replacement_export_id,
            expected_catalog_publication_revision=request.expected_catalog_publication_revision,
            projection=projection,
        )
        return _command_response(command)
    except Exception as error:
        raise_catalog_error(error)


@router.post("/imports/{import_id}/resume")
def resume_catalog_import(
    import_id: int,
    request: ResumeImportRequest,
    context: CatalogWriteContext,
    engine: CatalogEngine,
    idempotency_key: CatalogIdempotencyKey,
) -> Response:
    require_catalog_manager(context)
    require_matching_token(idempotency_key, request.operation_token)
    try:
        command = MySqlCatalogImportRepository(engine).resume_parse(
            import_id=import_id,
            site_id=context.site_id,
            actor_user_id=context.principal_user_id,
            operation_token=request.operation_token,
            expected_workflow_revision=request.expected_workflow_revision,
            expected_parse_attempt_revision=request.expected_parse_attempt_revision,
            lease_token=uuid4(),
            now=datetime.now(UTC),
            lease_ttl=timedelta(minutes=5),
        )
        return _command_response(command)
    except Exception as error:
        raise_catalog_error(error)


@router.get("/imports/{import_id}/file", response_class=Response)
def download_catalog_import_file(
    import_id: int, context: CatalogReadContext, engine: CatalogEngine
) -> Response:
    require_catalog_manager(context)
    try:
        with engine.connect() as connection:
            row = (
                connection.execute(
                    sa.text(
                        """
                    SELECT files.storage_key, files.sha256, files.size_bytes,
                           files.original_filename
                    FROM catalog_imports AS imports
                    INNER JOIN raw_files AS files ON files.id = imports.raw_file_id
                    WHERE imports.id = :id AND imports.site_id = :site_id
                    """
                    ),
                    {"id": import_id, "site_id": context.site_id},
                )
                .mappings()
                .one_or_none()
            )
        if row is None:
            raise ApiError(404, "catalog_import_file_not_found", "File was not found.")
        storage = StorageSettings.from_env()
        content = LocalContentStore(storage.root, storage.max_upload_bytes).read_bytes(
            str(row["storage_key"]), bytes(row["sha256"]).hex(), int(row["size_bytes"])
        )
        return Response(
            content=content,
            media_type=CATALOG_WORKBOOK_MEDIA_TYPE,
            headers={
                "Content-Disposition": 'attachment; filename="catalog-source.xlsx"',
                "Cache-Control": "private, no-store",
                "X-Content-Type-Options": "nosniff",
            },
        )
    except ApiError:
        raise
    except ContentStoreError as error:
        raise ApiError(
            409, "catalog_import_file_unavailable", "The file is unavailable."
        ) from error
    except Exception as error:
        raise_catalog_error(error)


__all__ = ("ApproveImportRequest", "ImportRevisionRequest", "router")
