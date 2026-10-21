"""Task-oriented HTTP API for the date data workbench."""

from __future__ import annotations

import json
from datetime import UTC, date, datetime
from decimal import Decimal, InvalidOperation
from tempfile import SpooledTemporaryFile
from typing import Annotated, Any, Literal, cast
from uuid import UUID

import sqlalchemy as sa
from fastapi import APIRouter, Depends, Header, Path, Query, Request
from pydantic import BaseModel, ConfigDict, Field, field_validator
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session

from app.api.dependencies import (
    get_database_engine,
    get_database_session,
    require_roles,
    require_write_roles,
)
from app.api.errors import ApiError
from app.api.imports import (
    _decode_original_filename,
    _ingest_service,
    _resolve_current_site_config_version_id,
    _workflow,
)
from app.auth.sessions import Principal
from app.config import StorageSettings
from app.imports.storage import ContentStoreError, UploadTooLargeError
from app.imports.types import (
    CommitOutcomeUnknown,
    DuplicateBatchConflict,
    ImportCommand,
    ImportCreated,
    IngestError,
    RecoveredImport,
    ReportType,
)
from app.parsers.repository import ParseRepositoryError
from app.parsers.types import SupportedEncoding
from app.publications.commands import (
    CreateRevisionCommand,
    PublicationPointerExpectation,
)
from app.publications.repository import MySqlPublicationRepository, PublicationError
from app.publications.rules import PublicationIneligible
from app.publications.service import PublicationService
from app.review.types import (
    DraftHeadExpectation,
    FieldValueInvalid,
    ReviewCommitOutcomeUnknown,
    ReviewError,
    ReviewOperationConflict,
    ReviewPermissionDenied,
    ReviewTransactionBusy,
)
from app.validation.fields import FieldValue
from app.workbench.commands import (
    NothingToUndo,
    SetWorkbenchCellCommand,
    UndoWorkbenchCellCommand,
    WorkbenchCellConflict,
    WorkbenchCellValueInvalid,
    WorkbenchMutationError,
    WorkbenchOperationConflict,
)
from app.workbench.import_orchestration import (
    MySqlWorkbenchImportRepository,
    OrchestrateImportCommand,
    WorkbenchImportError,
    WorkbenchImportNotFound,
    WorkbenchImportOperationConflict,
    WorkbenchImportOrchestrator,
    WorkbenchImportResult,
)
from app.workbench.queries import (
    DateWorkbenchQueryService,
    DateWorkbenchResponse,
    WorkbenchQueryError,
)
from app.workbench.repository import WorkbenchCellMutationResult
from app.workbench.service import WorkbenchCellMutationService

router = APIRouter(prefix="/api/workbench", tags=["workbench"])
_Reader = Annotated[
    Principal,
    Depends(require_roles("admin", "data_manager", "viewer")),
]
_DatabaseSession = Annotated[
    Session,
    Depends(get_database_session, scope="function"),
]
_Writer = Annotated[
    Principal,
    Depends(require_write_roles("admin", "data_manager")),
]
_ManagerReader = Annotated[
    Principal,
    Depends(require_roles("admin", "data_manager")),
]
_Engine = Annotated[Engine, Depends(get_database_engine)]
_IdempotencyKey = Annotated[UUID, Header(alias="Idempotency-Key")]
_PositivePathId = Annotated[int, Path(ge=1)]
_ReportType = Annotated[ReportType, Query()]
_Page = Annotated[int, Query(ge=1)]
_PageSize = Annotated[int, Query(ge=1, le=100)]
_Search = Annotated[str | None, Query(max_length=200)]
_SortColumnId = Annotated[UUID | None, Query()]


class _WorkbenchWriteRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")


class WorkbenchExpectedHeadRequest(_WorkbenchWriteRequest):
    dataset_id: int = Field(ge=1, strict=True)
    status: Literal["draft", "ready_for_publish"]
    data_revision: int = Field(ge=0, strict=True)
    review_revision: int = Field(ge=0, strict=True)
    pointed_at: datetime

    @field_validator("pointed_at")
    @classmethod
    def require_aware_timestamp(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("pointed_at must be timezone-aware")
        return value.astimezone(UTC)


class WorkbenchCellValueRequest(_WorkbenchWriteRequest):
    type: Literal["text", "integer", "decimal", "utc_datetime", "null"]
    value: str | int | None


class SetWorkbenchCellRequest(_WorkbenchWriteRequest):
    head: WorkbenchExpectedHeadRequest
    value: WorkbenchCellValueRequest
    expected_cell_revision: int = Field(ge=0, strict=True)
    reason: str = Field(min_length=1, max_length=2000)

    @field_validator("reason")
    @classmethod
    def reject_blank_reason(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("reason must not be blank")
        return value.strip()


class UndoWorkbenchCellRequest(_WorkbenchWriteRequest):
    head: WorkbenchExpectedHeadRequest
    reason: str = Field(default="Undo latest workbench cell change", max_length=2000)

    @field_validator("reason")
    @classmethod
    def reject_blank_reason(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("reason must not be blank")
        return value.strip()


class CreateWorkbenchRevisionRequest(_WorkbenchWriteRequest):
    published_version_id: int = Field(ge=1, strict=True)
    reason: str = Field(min_length=1, max_length=1000)


class WorkbenchRevisionResponse(BaseModel):
    result_kind: Literal["revision_created", "existing_revision"]
    dataset_id: int
    version_id: int
    version_no: int
    status: Literal["draft", "ready_for_publish"]
    data_revision: int
    review_revision: int
    pointed_at: datetime


class WorkbenchChangeResponse(BaseModel):
    ledger_kind: Literal["standard", "extension"]
    change_id: int
    data_revision: int
    cell_revision: int
    row_id: int
    column_id: UUID
    operation: str
    before: Any
    after: Any
    actor_user_id: int
    actor_username: str
    reason: str
    occurred_at: datetime
    undoes_change_id: int | None


class WorkbenchChangePageResponse(BaseModel):
    changes: list[WorkbenchChangeResponse]
    page: int
    page_size: int
    total_changes: int
    total_pages: int


class WorkbenchMutationHeadResponse(BaseModel):
    dataset_id: int
    version_id: int
    status: Literal["draft", "ready_for_publish"]
    data_revision: int
    review_revision: int
    pointed_at: datetime


class WorkbenchMutationCellResponse(BaseModel):
    row_id: int
    column_id: UUID
    current: str | None
    base: str | None
    cell_revision: int
    changed: bool


class WorkbenchCellMutationResponse(BaseModel):
    operation_token: UUID
    head: WorkbenchMutationHeadResponse
    cell: WorkbenchMutationCellResponse
    change_id: int


class WorkbenchImportResponse(BaseModel):
    batch_id: int
    status: Literal[
        "workspace_ready",
        "confirmation_required",
        "conflict_required",
        "duplicate",
        "failed",
        "processing",
    ]
    stage: str
    report_date: date | None
    report_type: ReportType | None
    encoding: SupportedEncoding | None
    issue_codes: list[str]
    workspace_url: str | None
    dataset_id: int | None
    version_id: int | None
    duplicate: bool
    message: str | None

    @classmethod
    def from_domain(cls, result: WorkbenchImportResult) -> WorkbenchImportResponse:
        return cls(
            batch_id=result.batch_id,
            status=result.status,
            stage=result.stage,
            report_date=result.report_date,
            report_type=result.report_type,
            encoding=result.encoding,
            issue_codes=list(result.issue_codes),
            workspace_url=result.workspace_url,
            dataset_id=result.dataset_id,
            version_id=result.version_id,
            duplicate=result.duplicate,
            message=result.message,
        )


class ConfirmWorkbenchImportRequest(_WorkbenchWriteRequest):
    report_type: ReportType
    report_date: date
    encoding: SupportedEncoding


def _field_value(payload: WorkbenchCellValueRequest) -> FieldValue:
    if payload.type == "null":
        if payload.value is not None:
            raise ApiError(422, "invalid_cell_value", "A null value must be null.")
        return None
    if payload.type == "text":
        if not isinstance(payload.value, str):
            raise ApiError(422, "invalid_cell_value", "A text value must be text.")
        return payload.value
    if payload.type == "integer":
        if isinstance(payload.value, bool) or not isinstance(payload.value, int):
            raise ApiError(
                422,
                "invalid_cell_value",
                "An integer value must be an integer.",
            )
        return payload.value
    if payload.type == "decimal":
        if not isinstance(payload.value, str):
            raise ApiError(
                422,
                "invalid_cell_value",
                "A decimal value must be decimal text.",
            )
        try:
            value = Decimal(payload.value)
        except InvalidOperation as error:
            raise ApiError(
                422,
                "invalid_cell_value",
                "The decimal value is invalid.",
            ) from error
        if not value.is_finite():
            raise ApiError(
                422,
                "invalid_cell_value",
                "The decimal value must be finite.",
            )
        return value
    if not isinstance(payload.value, str) or not payload.value.endswith("Z"):
        raise ApiError(
            422,
            "invalid_cell_value",
            "A UTC datetime value must end in Z.",
        )
    try:
        return datetime.fromisoformat(payload.value[:-1] + "+00:00").astimezone(UTC)
    except ValueError as error:
        raise ApiError(
            422,
            "invalid_cell_value",
            "The UTC datetime value is invalid.",
        ) from error


def _mutation_response(
    result: WorkbenchCellMutationResult,
) -> WorkbenchCellMutationResponse:
    return WorkbenchCellMutationResponse(
        operation_token=result.operation_token,
        head=WorkbenchMutationHeadResponse(
            dataset_id=result.head.dataset_id,
            version_id=result.head.version_id,
            status=result.head.status,
            data_revision=result.head.data_revision,
            review_revision=result.head.review_revision,
            pointed_at=result.head.pointed_at,
        ),
        cell=WorkbenchMutationCellResponse(
            row_id=result.cell.row_id,
            column_id=result.cell.column_id,
            current=result.cell.current,
            base=result.cell.base,
            cell_revision=result.cell.cell_revision,
            changed=result.cell.current != result.cell.base,
        ),
        change_id=result.change_id,
    )


def _import_orchestrator(engine: Engine) -> WorkbenchImportOrchestrator:
    return WorkbenchImportOrchestrator(engine, workflow=_workflow(engine))


def _import_api_error(error: Exception) -> ApiError:
    if isinstance(error, WorkbenchImportNotFound):
        return ApiError(404, "import_not_found", "The requested import was not found.")
    if isinstance(error, WorkbenchImportOperationConflict):
        return ApiError(
            409,
            "workbench_operation_conflict",
            "The idempotency key is already bound to another operation.",
        )
    if isinstance(error, ParseRepositoryError):
        return ApiError(409, "import_state_conflict", "The import state has changed.")
    return ApiError(
        503,
        "workbench_import_unavailable",
        "The workbench import could not be completed.",
    )


@router.post(
    "/imports",
    response_model=WorkbenchImportResponse,
    openapi_extra={
        "requestBody": {
            "required": True,
            "content": {"text/csv": {"schema": {"type": "string", "format": "binary"}}},
        }
    },
)
async def upload_workbench_import(
    request: Request,
    principal: _Writer,
    engine: _Engine,
    operation_token: _IdempotencyKey,
    report_date: date | None = None,
    expected_report_type: ReportType | None = None,
    original_filename: Annotated[
        str | None,
        Header(alias="X-Original-Filename"),
    ] = None,
) -> WorkbenchImportResponse:
    """Upload, inspect, parse, and materialize every conflict-free CSV."""

    storage = StorageSettings.from_env()
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
                    site_config_version_id=(
                        _resolve_current_site_config_version_id(engine, None)
                    ),
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

    repository = MySqlWorkbenchImportRepository(engine)
    orchestrator = _import_orchestrator(engine)
    if isinstance(result, DuplicateBatchConflict):
        retry_command = OrchestrateImportCommand(
            batch_id=result.existing_batch_id,
            sha256_hex=result.sha256_hex,
            actor_user_id=principal.user_id,
            operation_token=operation_token,
            requested_report_date=report_date,
            requested_report_type=expected_report_type,
        )
        try:
            recovered = repository.recover_registered(retry_command)
        except WorkbenchImportError as error:
            raise _import_api_error(error) from error
        if recovered is not None:
            return WorkbenchImportResponse.from_domain(recovered)
        return WorkbenchImportResponse.from_domain(
            orchestrator.describe(result.existing_batch_id, duplicate=True)
        )
    if isinstance(result, ImportCreated):
        batch_id = result.batch_id
        sha256_hex = result.sha256_hex
    elif isinstance(result, RecoveredImport):
        batch_id = result.batch_id
        sha256_hex = repository.sha256_hex(batch_id)
    else:
        raise ApiError(
            503,
            "upload_outcome_unknown",
            "The upload completed with an uncertain database outcome.",
        )
    try:
        response = orchestrator.run(
            OrchestrateImportCommand(
                batch_id=batch_id,
                sha256_hex=sha256_hex,
                actor_user_id=principal.user_id,
                operation_token=operation_token,
                requested_report_date=report_date,
                requested_report_type=expected_report_type,
            )
        )
    except (WorkbenchImportError, ParseRepositoryError) as error:
        raise _import_api_error(error) from error
    return WorkbenchImportResponse.from_domain(response)


@router.post(
    "/imports/{batch_id}/confirm",
    response_model=WorkbenchImportResponse,
)
def confirm_workbench_import(
    batch_id: _PositivePathId,
    payload: ConfirmWorkbenchImportRequest,
    principal: _Writer,
    engine: _Engine,
    operation_token: _IdempotencyKey,
) -> WorkbenchImportResponse:
    repository = MySqlWorkbenchImportRepository(engine)
    try:
        result = _import_orchestrator(engine).run(
            OrchestrateImportCommand(
                batch_id=batch_id,
                sha256_hex=repository.sha256_hex(batch_id),
                actor_user_id=principal.user_id,
                operation_token=operation_token,
                confirmed_report_type=payload.report_type,
                confirmed_report_date=payload.report_date,
                confirmed_encoding=payload.encoding,
            )
        )
    except (WorkbenchImportError, ParseRepositoryError) as error:
        raise _import_api_error(error) from error
    return WorkbenchImportResponse.from_domain(result)


@router.get("/imports/pending", response_model=list[WorkbenchImportResponse])
def list_pending_workbench_imports(
    _principal: _ManagerReader,
    engine: _Engine,
) -> list[WorkbenchImportResponse]:
    try:
        return [
            WorkbenchImportResponse.from_domain(result)
            for result in _import_orchestrator(engine).pending()
        ]
    except WorkbenchImportError as error:
        raise _import_api_error(error) from error


@router.get("/imports/{batch_id}", response_model=WorkbenchImportResponse)
def get_workbench_import(
    batch_id: _PositivePathId,
    _principal: _ManagerReader,
    engine: _Engine,
) -> WorkbenchImportResponse:
    try:
        return WorkbenchImportResponse.from_domain(
            _import_orchestrator(engine).describe(batch_id)
        )
    except WorkbenchImportError as error:
        raise _import_api_error(error) from error


@router.get("/dates/{report_date}", response_model=DateWorkbenchResponse)
def get_date_workbench(
    report_date: date,
    principal: _Reader,
    database_session: _DatabaseSession,
    report_type: _ReportType,
    page: _Page = 1,
    page_size: _PageSize = 50,
    search: _Search = None,
    sort_column_id: _SortColumnId = None,
    direction: Literal["asc", "desc"] = Query(default="asc"),
    changed_only: bool = Query(default=False),
) -> DateWorkbenchResponse:
    try:
        return DateWorkbenchQueryService(database_session).get(
            principal=principal,
            report_date=report_date,
            report_type=report_type,
            page=page,
            page_size=page_size,
            search=search,
            sort_column_id=sort_column_id,
            direction=direction,
            changed_only=changed_only,
        )
    except WorkbenchQueryError as error:
        raise ApiError(422, error.code, error.message) from error


@router.patch(
    "/versions/{version_id}/rows/{row_id}/cells/{column_id}",
    response_model=WorkbenchCellMutationResponse,
)
def set_workbench_cell(
    version_id: _PositivePathId,
    row_id: _PositivePathId,
    column_id: UUID,
    payload: SetWorkbenchCellRequest,
    principal: _Writer,
    engine: _Engine,
    operation_token: _IdempotencyKey,
) -> WorkbenchCellMutationResponse:
    try:
        command = SetWorkbenchCellCommand(
            head=DraftHeadExpectation(
                dataset_id=payload.head.dataset_id,
                version_id=version_id,
                status=payload.head.status,
                data_revision=payload.head.data_revision,
                review_revision=payload.head.review_revision,
                pointed_at=payload.head.pointed_at,
            ),
            row_id=row_id,
            column_id=column_id,
            value=_field_value(payload.value),
            expected_cell_revision=payload.expected_cell_revision,
            actor_user_id=principal.user_id,
            operation_token=operation_token,
            reason=payload.reason,
        )
        return _mutation_response(
            WorkbenchCellMutationService(engine).set_cell(command)
        )
    except (ValueError, FieldValueInvalid, WorkbenchCellValueInvalid) as error:
        raise ApiError(
            422,
            "invalid_cell_value",
            "The supplied workbench cell value is invalid.",
        ) from error
    except (WorkbenchOperationConflict, ReviewOperationConflict) as error:
        raise ApiError(
            409,
            "workbench_operation_conflict",
            "The idempotency key is already bound to another operation.",
        ) from error
    except (WorkbenchCellConflict, WorkbenchMutationError) as error:
        raise ApiError(
            409,
            "workbench_cell_conflict",
            "The workbench cell changed before this edit.",
        ) from error
    except ReviewPermissionDenied as error:
        raise ApiError(
            403,
            "workbench_forbidden",
            "Permission to edit this workbench was denied.",
        ) from error
    except ReviewTransactionBusy as error:
        raise ApiError(
            503,
            "workbench_busy",
            "The workbench is temporarily busy.",
        ) from error
    except ReviewCommitOutcomeUnknown as error:
        raise ApiError(
            503,
            "workbench_outcome_unknown",
            "The workbench command outcome could not be confirmed.",
        ) from error
    except ReviewError as error:
        raise ApiError(
            409,
            "workbench_cell_conflict",
            "The workbench changed before this edit.",
        ) from error


@router.post(
    "/versions/{version_id}/undo",
    response_model=WorkbenchCellMutationResponse,
)
def undo_workbench_cell(
    version_id: _PositivePathId,
    payload: UndoWorkbenchCellRequest,
    principal: _Writer,
    engine: _Engine,
    operation_token: _IdempotencyKey,
) -> WorkbenchCellMutationResponse:
    try:
        command = UndoWorkbenchCellCommand(
            head=DraftHeadExpectation(
                dataset_id=payload.head.dataset_id,
                version_id=version_id,
                status=payload.head.status,
                data_revision=payload.head.data_revision,
                review_revision=payload.head.review_revision,
                pointed_at=payload.head.pointed_at,
            ),
            actor_user_id=principal.user_id,
            operation_token=operation_token,
            reason=payload.reason,
        )
        return _mutation_response(
            WorkbenchCellMutationService(engine).undo_latest_cell(command)
        )
    except NothingToUndo as error:
        raise ApiError(
            409,
            "nothing_to_undo",
            "There is no still-current workbench change to undo.",
        ) from error
    except (WorkbenchOperationConflict, ReviewOperationConflict) as error:
        raise ApiError(
            409,
            "workbench_operation_conflict",
            "The idempotency key is already bound to another operation.",
        ) from error
    except (WorkbenchCellConflict, WorkbenchMutationError, ReviewError) as error:
        raise ApiError(
            409,
            "workbench_cell_conflict",
            "The workbench changed before this undo.",
        ) from error


@router.post(
    "/dates/{report_date}/{report_type}/revision",
    response_model=WorkbenchRevisionResponse,
    status_code=201,
)
def create_workbench_revision(
    report_date: date,
    report_type: ReportType,
    payload: CreateWorkbenchRevisionRequest,
    principal: _Writer,
    engine: _Engine,
    operation_token: _IdempotencyKey,
) -> WorkbenchRevisionResponse:
    with engine.connect() as connection:
        state = (
            connection.execute(
                sa.text(
                    """
                    SELECT datasets.id AS dataset_id,
                           publications.version_id AS published_version_id,
                           publications.published_at,
                           drafts.version_id AS draft_version_id,
                           draft_versions.version_no AS draft_version_no,
                           draft_versions.status AS draft_status,
                           draft_versions.data_revision AS draft_data_revision,
                           draft_versions.review_revision AS draft_review_revision,
                           drafts.pointed_at AS draft_pointed_at,
                           lineage.parent_version_id
                    FROM daily_datasets AS datasets
                    LEFT JOIN dataset_publications AS publications
                        ON publications.dataset_id = datasets.id
                    LEFT JOIN dataset_drafts AS drafts
                        ON drafts.dataset_id = datasets.id
                    LEFT JOIN dataset_versions AS draft_versions
                        ON draft_versions.id = drafts.version_id
                    LEFT JOIN version_parent_versions AS lineage
                        ON lineage.child_version_id = drafts.version_id
                       AND lineage.parent_version_id = publications.version_id
                    WHERE datasets.report_date = :report_date
                      AND datasets.report_type = :report_type
                    LIMIT 1
                    """
                ),
                {"report_date": report_date, "report_type": report_type},
            )
            .mappings()
            .first()
        )
    if (
        state is None
        or state["published_version_id"] is None
        or int(state["published_version_id"]) != payload.published_version_id
        or state["published_at"] is None
    ):
        raise ApiError(
            409,
            "workbench_publication_conflict",
            "The current publication changed before the revision was created.",
        )
    if state["draft_version_id"] is not None:
        if state["parent_version_id"] is None:
            raise ApiError(
                409,
                "workbench_draft_conflict",
                "An unrelated active draft already exists for this report.",
            )
        return WorkbenchRevisionResponse(
            result_kind="existing_revision",
            dataset_id=int(state["dataset_id"]),
            version_id=int(state["draft_version_id"]),
            version_no=int(state["draft_version_no"]),
            status=cast(
                Literal["draft", "ready_for_publish"],
                str(state["draft_status"]),
            ),
            data_revision=int(state["draft_data_revision"]),
            review_revision=int(state["draft_review_revision"]),
            pointed_at=_utc_database_timestamp(state["draft_pointed_at"]),
        )
    try:
        result = PublicationService(
            repository=MySqlPublicationRepository(engine)
        ).create_revision(
            CreateRevisionCommand(
                dataset_id=int(state["dataset_id"]),
                expected_publication=PublicationPointerExpectation(
                    version_id=payload.published_version_id,
                    published_at=_utc_database_timestamp(state["published_at"]),
                ),
                actor_user_id=principal.user_id,
                operation_token=operation_token,
                reason=payload.reason,
            )
        )
    except (PublicationError, PublicationIneligible) as error:
        raise ApiError(
            409,
            "workbench_revision_conflict",
            "The revision could not be created from the current publication.",
        ) from error
    with engine.connect() as connection:
        pointed_at = connection.scalar(
            sa.text(
                """
                SELECT pointed_at FROM dataset_drafts
                WHERE dataset_id = :dataset_id AND version_id = :version_id
                """
            ),
            {"dataset_id": result.dataset_id, "version_id": result.version_id},
        )
    return WorkbenchRevisionResponse(
        result_kind="revision_created",
        dataset_id=result.dataset_id,
        version_id=result.version_id,
        version_no=result.version_no,
        status="draft",
        data_revision=result.data_revision,
        review_revision=result.review_revision,
        pointed_at=_utc_database_timestamp(pointed_at),
    )


def _utc_database_timestamp(value: object) -> datetime:
    if not isinstance(value, datetime):
        raise ApiError(
            409,
            "workbench_pointer_invalid",
            "The workbench pointer timestamp is unavailable.",
        )
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


@router.get(
    "/versions/{version_id}/changes",
    response_model=WorkbenchChangePageResponse,
)
def get_workbench_changes(
    version_id: _PositivePathId,
    _principal: _ManagerReader,
    database_session: _DatabaseSession,
    page: _Page = 1,
    page_size: _PageSize = 50,
) -> WorkbenchChangePageResponse:
    parameters = {
        "version_id": version_id,
        "limit": page_size,
        "offset": (page - 1) * page_size,
    }
    union_sql = """
        SELECT 'standard' AS ledger_kind, events.id AS change_id,
               events.data_revision, events.data_revision AS cell_revision,
               changes.row_id, columns.column_id, changes.operation,
               changes.before_value_json AS before_value,
               changes.after_value_json AS after_value,
               events.actor_user_id, users.username_normalized AS actor_username,
               events.reason, events.occurred_at,
               changes.restored_field_change_id AS undoes_change_id
        FROM data_change_events AS events
        INNER JOIN field_changes AS changes
            ON changes.version_id = events.version_id AND changes.id = events.id
        INNER JOIN version_table_columns AS columns
            ON columns.version_id = changes.version_id
           AND columns.standard_field_name = changes.field_name
        INNER JOIN users ON users.id = events.actor_user_id
        WHERE events.version_id = :version_id
        UNION ALL
        SELECT 'extension' AS ledger_kind, changes.id AS change_id,
               changes.data_revision, changes.cell_revision,
               changes.row_id, changes.column_id, changes.operation,
               changes.before_value, changes.after_value,
               changes.actor_user_id, users.username_normalized AS actor_username,
               changes.reason, changes.occurred_at, changes.undoes_change_id
        FROM extension_cell_changes AS changes
        INNER JOIN users ON users.id = changes.actor_user_id
        WHERE changes.version_id = :version_id
    """
    total_changes = int(
        database_session.scalar(
            sa.text("SELECT COUNT(*) FROM (" + union_sql + ") AS history"),
            {"version_id": version_id},
        )
        or 0
    )
    rows = (
        database_session.execute(
            sa.text(
                "SELECT * FROM ("
                + union_sql
                + ") AS history ORDER BY data_revision DESC, ledger_kind, "
                "change_id DESC LIMIT :limit OFFSET :offset"
            ),
            parameters,
        )
        .mappings()
        .all()
    )
    changes: list[WorkbenchChangeResponse] = []
    for row in rows:
        before: object = row["before_value"]
        after: object = row["after_value"]
        if row["ledger_kind"] == "standard":
            before = _decode_json_value(before)
            after = _decode_json_value(after)
        changes.append(
            WorkbenchChangeResponse(
                ledger_kind=cast(
                    Literal["standard", "extension"],
                    str(row["ledger_kind"]),
                ),
                change_id=int(row["change_id"]),
                data_revision=int(row["data_revision"]),
                cell_revision=int(row["cell_revision"]),
                row_id=int(row["row_id"]),
                column_id=_database_uuid(row["column_id"]),
                operation=str(row["operation"]),
                before=before,
                after=after,
                actor_user_id=int(row["actor_user_id"]),
                actor_username=str(row["actor_username"]),
                reason=str(row["reason"]),
                occurred_at=_utc_database_timestamp(row["occurred_at"]),
                undoes_change_id=(
                    int(row["undoes_change_id"])
                    if row["undoes_change_id"] is not None
                    else None
                ),
            )
        )
    return WorkbenchChangePageResponse(
        changes=changes,
        page=page,
        page_size=page_size,
        total_changes=total_changes,
        total_pages=(total_changes + page_size - 1) // page_size,
    )


def _decode_json_value(value: object) -> object:
    if isinstance(value, str):
        try:
            return json.loads(value)
        except json.JSONDecodeError:
            return value
    return value


def _database_uuid(value: object) -> UUID:
    if isinstance(value, memoryview):
        value = value.tobytes()
    if isinstance(value, bytearray):
        value = bytes(value)
    if not isinstance(value, bytes) or len(value) != 16:
        raise RuntimeError("database returned an invalid workbench column ID")
    return UUID(bytes=value)
