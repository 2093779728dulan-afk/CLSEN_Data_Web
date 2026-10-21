"""Authenticated parse inspection and human confirmation API."""

from __future__ import annotations

from dataclasses import asdict
from datetime import date
from tempfile import SpooledTemporaryFile
from typing import Annotated, Literal
from unicodedata import normalize
from urllib.parse import unquote_to_bytes
from uuid import UUID

import sqlalchemy as sa
from fastapi import APIRouter, Depends, Header, Query, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field
from sqlalchemy.engine import Engine

from app.api.dependencies import get_database_engine, require_write_roles
from app.api.errors import ApiError
from app.auth.sessions import Principal
from app.config import StorageSettings
from app.imports.repository import MySqlIngestRepository
from app.imports.service import IngestService
from app.imports.storage import (
    ContentStoreError,
    LocalContentStore,
    UploadTooLargeError,
)
from app.imports.types import (
    CommitOutcomeUnknown,
    DuplicateBatchConflict,
    ImportCommand,
    ImportCreated,
    IngestError,
)
from app.parsers.repository import (
    BatchNotFound,
    MySqlParseRepository,
    ParseAlreadyRunning,
    ParseCommitOutcomeUnknown,
    ParseRepositoryError,
    ParseStateConflict,
)
from app.parsers.workflow import (
    ChangeReportDateCommand,
    ConfirmAndParseCommand,
    ParseWorkflow,
)

router = APIRouter(prefix="/api/imports", tags=["imports"])
_AMAZON_US_SITE_CODE = "amazon_us"
_Manager = Annotated[Principal, Depends(require_write_roles("admin", "data_manager"))]
_Engine = Annotated[Engine, Depends(get_database_engine)]
_IdempotencyKey = Annotated[UUID, Header(alias="Idempotency-Key")]


class InspectionResponse(BaseModel):
    status: str
    report_type: Literal["business_report", "return_report"] | None
    report_date: date | None
    encoding: str | None
    ruleset_version: str
    issue_codes: list[str]


class ConfirmParseRequest(BaseModel):
    report_type: Literal["business_report", "return_report"]
    report_date: date
    encoding: Literal["utf-8-sig", "utf-8", "windows-1252"]
    site_config_version_id: int | None = Field(
        default=None,
        ge=1,
        description=(
            "Legacy compatibility assertion; parsing always uses the batch's "
            "server-frozen configuration."
        ),
    )


class ChangeDateRequest(BaseModel):
    report_date: date


class UploadResponse(BaseModel):
    batch_id: int
    raw_file_id: int
    sha256_hex: str
    content_reused: bool
    duplicate: bool


def _decode_original_filename(value: str | None) -> str:
    if value is None:
        return "uploaded-report.csv"
    try:
        filename = unquote_to_bytes(value).decode("utf-8", errors="strict")
    except UnicodeDecodeError as error:
        raise ApiError(
            422,
            "invalid_original_filename",
            "X-Original-Filename must be percent-encoded UTF-8.",
        ) from error
    filename = normalize("NFC", filename)
    if any(ord(character) < 32 or ord(character) == 127 for character in filename):
        raise ApiError(
            422,
            "invalid_original_filename",
            "The original filename contains a control character.",
        )
    return filename


def _workflow(engine: Engine) -> ParseWorkflow:
    storage = StorageSettings.from_env()
    return ParseWorkflow(
        repository=MySqlParseRepository(engine),
        store=LocalContentStore(storage.root, storage.max_upload_bytes),
    )


def _ingest_service(engine: Engine) -> IngestService:
    storage = StorageSettings.from_env()
    return IngestService(
        repository=MySqlIngestRepository(engine),
        store=LocalContentStore(storage.root, storage.max_upload_bytes),
        lease_ttl=storage.lease_ttl,
        lease_renew_interval=storage.lease_renew_interval,
    )


def _validate_legacy_site_config_selection(
    requested_config_id: int | None,
    frozen_config_id: int,
) -> int:
    if requested_config_id is not None and requested_config_id != frozen_config_id:
        raise ApiError(
            409,
            "site_config_version_conflict",
            "The supplied site configuration is not the server-selected version.",
        )
    return frozen_config_id


def _resolve_current_site_config_version_id(
    engine: Engine,
    requested_config_id: int | None,
) -> int:
    with engine.connect() as connection:
        current_config_id = connection.scalar(
            sa.text(
                """
                SELECT current.current_config_version_id
                FROM sites
                INNER JOIN site_current_configs AS current
                    ON current.site_id = sites.id
                INNER JOIN site_config_versions AS configs
                    ON configs.site_id = current.site_id
                   AND configs.id = current.current_config_version_id
                WHERE sites.code = :site_code
                  AND sites.status = 'active'
                """
            ),
            {"site_code": _AMAZON_US_SITE_CODE},
        )
    if current_config_id is None:
        raise ApiError(
            503,
            "site_configuration_unavailable",
            "The current site configuration is unavailable.",
        )
    return _validate_legacy_site_config_selection(
        requested_config_id,
        int(current_config_id),
    )


def _resolve_batch_site_config_version_id(
    engine: Engine,
    batch_id: int,
    requested_config_id: int | None,
) -> int:
    with engine.connect() as connection:
        frozen_config_id = connection.scalar(
            sa.text(
                """
                SELECT batches.site_config_version_id
                FROM import_batches AS batches
                INNER JOIN sites ON sites.id = batches.site_id
                WHERE batches.id = :batch_id
                  AND sites.code = :site_code
                """
            ),
            {"batch_id": batch_id, "site_code": _AMAZON_US_SITE_CODE},
        )
    if frozen_config_id is None:
        raise ApiError(404, "import_not_found", "The requested import was not found.")
    return _validate_legacy_site_config_selection(
        requested_config_id,
        int(frozen_config_id),
    )


@router.post(
    "",
    response_model=UploadResponse,
    status_code=201,
    openapi_extra={
        "requestBody": {
            "required": True,
            "content": {
                "text/csv": {
                    "schema": {"type": "string", "format": "binary"},
                }
            },
        }
    },
)
async def upload_import(
    request: Request,
    principal: _Manager,
    engine: _Engine,
    report_date: date | None = None,
    site_config_version_id: Annotated[
        int | None,
        Query(
            ge=1,
            description=(
                "Legacy compatibility assertion; new batches always freeze the "
                "server-selected current configuration."
            ),
        ),
    ] = None,
    original_filename: Annotated[
        str | None,
        Header(
            alias="X-Original-Filename",
            description="Original filename percent-encoded as UTF-8.",
        ),
    ] = None,
) -> UploadResponse | JSONResponse:
    """Stream a CSV request body into the immutable ingest service.

    A browser sends the selected File as the request body and its untrusted display
    name in ``X-Original-Filename``.  Multipart parsing is intentionally avoided:
    it would add a second buffering layer in front of the storage size limit.
    """

    storage = StorageSettings.from_env()
    frozen_site_config_version_id = _resolve_current_site_config_version_id(
        engine,
        site_config_version_id,
    )
    declared_length = request.headers.get("Content-Length")
    if declared_length is not None:
        try:
            if int(declared_length) > storage.max_upload_bytes:
                raise ApiError(413, "upload_too_large", "The upload exceeds the limit.")
        except ValueError as error:
            raise ApiError(
                422,
                "invalid_upload_length",
                "Content-Length is invalid.",
            ) from error
    filename = _decode_original_filename(original_filename)
    size = 0
    with SpooledTemporaryFile(max_size=storage.max_upload_bytes, mode="w+b") as source:
        async for chunk in request.stream():
            size += len(chunk)
            if size > storage.max_upload_bytes:
                raise ApiError(413, "upload_too_large", "The upload exceeds the limit.")
            source.write(chunk)
        if size == 0:
            raise ApiError(422, "empty_upload", "The upload must not be empty.")
        source.seek(0)
        try:
            result = _ingest_service(engine).ingest(
                source,
                ImportCommand(
                    original_filename=filename,
                    media_type=request.headers.get("Content-Type"),
                    created_by_user_id=principal.user_id,
                    site_config_version_id=frozen_site_config_version_id,
                    report_date=report_date,
                ),
            )
        except UploadTooLargeError as error:
            raise ApiError(
                413,
                "upload_too_large",
                "The upload exceeds the limit.",
            ) from error
        except CommitOutcomeUnknown as error:
            raise ApiError(
                503,
                "upload_outcome_unknown",
                "The upload completed with an uncertain database outcome.",
            ) from error
        except (IngestError, ContentStoreError) as error:
            raise ApiError(
                503,
                "upload_unavailable",
                "The upload could not be completed.",
            ) from error
        except ValueError as error:
            raise ApiError(
                422,
                "invalid_upload",
                "The upload metadata is invalid.",
            ) from error
    if isinstance(result, DuplicateBatchConflict):
        with engine.connect() as connection:
            existing = (
                connection.execute(
                    sa.text(
                        """
                        SELECT COALESCE(
                                   datasets.report_date,
                                   CASE
                                       WHEN batches.confirmed_at IS NULL THEN COALESCE(
                                           batches.detected_report_date,
                                           batches.candidate_report_date,
                                           batches.report_date
                                       )
                                       ELSE batches.report_date
                                   END
                               ) AS report_date,
                               COALESCE(
                                   datasets.report_type,
                                   batches.confirmed_report_type,
                                   batches.detected_report_type
                               ) AS report_type,
                               COALESCE(versions.status, batches.status) AS stage
                        FROM import_batches AS batches
                        LEFT JOIN version_input_batches AS inputs
                            ON inputs.batch_id = batches.id
                        LEFT JOIN dataset_versions AS versions
                            ON versions.id = inputs.version_id
                        LEFT JOIN daily_datasets AS datasets
                            ON datasets.id = versions.dataset_id
                        WHERE batches.id = :batch_id
                        ORDER BY versions.id DESC
                        LIMIT 1
                        """
                    ),
                    {"batch_id": result.existing_batch_id},
                )
                .mappings()
                .first()
            )
        existing_date = existing["report_date"] if existing is not None else None
        existing_type = existing["report_type"] if existing is not None else None
        workspace_url = (
            f"/review/{existing_date.isoformat()}?report_type={existing_type}"
            if isinstance(existing_date, date) and isinstance(existing_type, str)
            else None
        )
        return JSONResponse(
            status_code=409,
            content={
                "error": {
                    "code": "duplicate_import",
                    "message": "This file is already available.",
                    "request_id": str(getattr(request.state, "request_id", "unknown")),
                    "existing_batch_id": result.existing_batch_id,
                    "report_date": (
                        existing_date.isoformat()
                        if isinstance(existing_date, date)
                        else None
                    ),
                    "report_type": existing_type,
                    "stage": existing["stage"] if existing is not None else "uploaded",
                    "workspace_url": workspace_url,
                }
            },
        )
    if not isinstance(result, ImportCreated):
        raise ApiError(
            503,
            "upload_outcome_unknown",
            "The upload completed with an uncertain database outcome.",
        )
    return UploadResponse(
        batch_id=result.batch_id,
        raw_file_id=result.raw_file_id,
        sha256_hex=result.sha256_hex,
        content_reused=result.content_reused,
        duplicate=False,
    )


def _parse_api_error(error: ParseRepositoryError) -> ApiError:
    if isinstance(error, BatchNotFound):
        return ApiError(404, "import_not_found", "The requested import was not found.")
    if isinstance(error, (ParseAlreadyRunning, ParseStateConflict)):
        return ApiError(409, "import_state_conflict", "The import state has changed.")
    if isinstance(error, ParseCommitOutcomeUnknown):
        return ApiError(
            503,
            "parse_outcome_unknown",
            "The parse command outcome could not be confirmed.",
        )
    return ApiError(409, "import_conflict", "The import could not be processed.")


@router.post("/{batch_id}/inspect", response_model=InspectionResponse)
def inspect_import(
    batch_id: int,
    _principal: _Manager,
    engine: _Engine,
) -> InspectionResponse:
    try:
        result = _workflow(engine).inspect(batch_id)
    except ParseRepositoryError as error:
        raise _parse_api_error(error) from error
    return InspectionResponse(
        status=result.status,
        report_type=result.report_type,
        report_date=result.detected_report_date,
        encoding=result.encoding,
        ruleset_version=result.ruleset_version or "unknown",
        issue_codes=[issue.code for issue in result.issues],
    )


@router.post("/{batch_id}/confirm-parse")
def confirm_parse(
    batch_id: int,
    payload: ConfirmParseRequest,
    principal: _Manager,
    engine: _Engine,
    operation_token: _IdempotencyKey,
) -> dict[str, object]:
    frozen_site_config_version_id = _resolve_batch_site_config_version_id(
        engine,
        batch_id,
        payload.site_config_version_id,
    )
    try:
        result = _workflow(engine).confirm_and_parse(
            ConfirmAndParseCommand(
                batch_id=batch_id,
                report_type=payload.report_type,
                report_date=payload.report_date,
                encoding=payload.encoding,
                site_config_version_id=frozen_site_config_version_id,
                actor_user_id=principal.user_id,
                operation_token=operation_token,
            )
        )
    except ParseRepositoryError as error:
        raise _parse_api_error(error) from error
    return {"result": asdict(result)}


@router.post("/{batch_id}/change-date", status_code=204)
def change_import_date(
    batch_id: int,
    payload: ChangeDateRequest,
    principal: _Manager,
    engine: _Engine,
    operation_token: _IdempotencyKey,
) -> None:
    try:
        _workflow(engine).change_report_date(
            ChangeReportDateCommand(
                batch_id=batch_id,
                report_date=payload.report_date,
                actor_user_id=principal.user_id,
                operation_token=operation_token,
            )
        )
    except ParseRepositoryError as error:
        raise _parse_api_error(error) from error
