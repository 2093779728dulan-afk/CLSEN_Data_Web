"""Authoritative persistent batch-review workflow API."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Annotated, Literal
from uuid import UUID

import sqlalchemy as sa
from fastapi import APIRouter, Depends, Header, Path, Query
from pydantic import BaseModel, ConfigDict, Field, field_validator
from sqlalchemy.engine import Engine

from app.api.dependencies import (
    get_database_engine,
    require_roles,
    require_write_roles,
)
from app.api.errors import ApiError
from app.auth.sessions import Principal
from app.batch_review.repository import (
    BatchReviewItemRecord,
    MySqlBatchReviewRepository,
)
from app.batch_review.service import (
    CONFIRMATION_STATEMENT_VERSION,
    BatchReviewRunView,
    BatchReviewService,
)
from app.batch_review.types import (
    AdvanceBatchReviewItemCommand,
    BatchReviewBusy,
    BatchReviewError,
    BatchReviewItemStatus,
    BatchReviewNotFound,
    BatchReviewOperationConflict,
    BatchReviewOutcomeUnknown,
    BatchReviewPermissionDenied,
    BatchReviewRevisionConflict,
    BatchReviewStateConflict,
    ChangeBatchReviewRunStateCommand,
    ConfirmBatchReviewCommand,
    CreatePreflightCommand,
    RetryBatchReviewItemCommand,
)
from app.config import StorageSettings
from app.imports.storage import LocalContentStore
from app.parsers.repository import MySqlParseRepository
from app.parsers.workflow import ParseWorkflow
from app.review.repository import MySqlReviewRepository
from app.review.service import ReviewService
from app.validation.repository import MySqlValidationRepository
from app.validation.service import ValidationService
from app.workbench.import_orchestration import WorkbenchImportOrchestrator

router = APIRouter(prefix="/api/imports/batch-reviews", tags=["batch-reviews"])
_ManagerRead = Annotated[
    Principal,
    Depends(require_roles("admin", "data_manager")),
]
_ManagerWrite = Annotated[
    Principal,
    Depends(require_write_roles("admin", "data_manager")),
]
_Engine = Annotated[Engine, Depends(get_database_engine)]
_IdempotencyKey = Annotated[UUID, Header(alias="Idempotency-Key")]
_PositivePathId = Annotated[int, Path(ge=1)]
_SITE_CODE = "amazon_us"


class _BatchRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")


class PreflightRequest(_BatchRequest):
    batch_ids: list[int] = Field(min_length=1, max_length=100)

    @field_validator("batch_ids")
    @classmethod
    def require_positive_unique_ids(cls, values: list[int]) -> list[int]:
        if any(
            not isinstance(value, int) or isinstance(value, bool) or value < 1
            for value in values
        ):
            raise ValueError("batch_ids must contain positive integers")
        if len(values) != len(set(values)):
            raise ValueError("batch_ids must not contain duplicates")
        return values


class ConfirmRequest(_BatchRequest):
    expected_revision: int = Field(ge=0, strict=True)
    selected_item_ids: list[int] = Field(min_length=1, max_length=100)
    confirmation_accepted: Literal[True]
    confirmation_statement_version: str = Field(min_length=1, max_length=64)

    @field_validator("selected_item_ids")
    @classmethod
    def require_unique_item_ids(cls, values: list[int]) -> list[int]:
        if any(value < 1 for value in values) or len(values) != len(set(values)):
            raise ValueError("selected_item_ids must be positive and unique")
        return values


class RevisionRequest(_BatchRequest):
    expected_revision: int = Field(ge=0, strict=True)


class BatchReviewSummaryResponse(BaseModel):
    total: int
    eligible: int
    active: int
    ready_for_publish: int
    manual_review: int
    failed: int
    skipped: int


class BatchReviewItemResponse(BaseModel):
    id: int
    batch_id: int
    filename: str
    report_date: str | None
    report_type: str | None
    encoding: str | None
    recognition_status: str
    selected: bool
    status: str
    reason_code: str | None
    reason_message: str | None
    manual_review_url: str | None
    dataset_id: int | None
    version_id: int | None
    validation_run_id: int | None
    operation_token: str | None
    attempt_count: int
    retry_allowed: bool
    outcome_unknown: bool
    recovery_available: bool


class BatchReviewRunResponse(BaseModel):
    id: int
    status: str
    revision: int
    summary: BatchReviewSummaryResponse
    items: list[BatchReviewItemResponse]
    allowed_actions: list[str]


def _site_id(engine: Engine) -> int:
    with engine.connect() as connection:
        value = connection.scalar(
            sa.text(
                """
                SELECT id FROM sites
                WHERE code = :site_code AND status = 'active'
                """
            ),
            {"site_code": _SITE_CODE},
        )
    if value is None:
        raise ApiError(
            503,
            "site_unavailable",
            "The current site is unavailable.",
        )
    return int(value)


def _workflow(engine: Engine) -> ParseWorkflow:
    settings = StorageSettings.from_env()
    return ParseWorkflow(
        repository=MySqlParseRepository(engine),
        store=LocalContentStore(settings.root, settings.max_upload_bytes),
    )


def _service(engine: Engine, *, advance: bool = False) -> BatchReviewService:
    repository = MySqlBatchReviewRepository(engine)
    if not advance:
        return BatchReviewService(repository)
    return BatchReviewService(
        repository,
        orchestrator=WorkbenchImportOrchestrator(engine, workflow=_workflow(engine)),
        validation=ValidationService(repository=MySqlValidationRepository(engine)),
        review=ReviewService(repository=MySqlReviewRepository(engine)),
    )


def _item_response(item: BatchReviewItemRecord) -> BatchReviewItemResponse:
    active_statuses = {
        BatchReviewItemStatus.PARSING,
        BatchReviewItemStatus.MATERIALIZING,
        BatchReviewItemStatus.VALIDATING,
    }
    recovery_available = item.status is BatchReviewItemStatus.QUEUED
    if item.status in active_statuses:
        lease_expires_at = item.lease_expires_at
        if lease_expires_at is None:
            recovery_available = True
        else:
            now = datetime.now(UTC)
            if lease_expires_at.tzinfo is None:
                now = now.replace(tzinfo=None)
            recovery_available = lease_expires_at <= now
    return BatchReviewItemResponse(
        id=item.id,
        batch_id=item.batch_id,
        filename=item.filename,
        report_date=(
            item.detected_report_date.isoformat()
            if item.detected_report_date is not None
            else None
        ),
        report_type=item.detected_report_type,
        encoding=item.detected_encoding,
        recognition_status=item.recognition_status,
        selected=item.selected,
        status=item.status.value,
        reason_code=item.reason_code.value if item.reason_code else None,
        reason_message=item.reason_message,
        manual_review_url=item.manual_review_url,
        dataset_id=item.dataset_id,
        version_id=item.version_id,
        validation_run_id=item.validation_run_id,
        operation_token=str(item.operation_token) if item.operation_token else None,
        attempt_count=item.attempt_count,
        retry_allowed=item.retry_allowed,
        outcome_unknown=item.outcome_unknown,
        recovery_available=recovery_available,
    )


def _run_response(view: BatchReviewRunView) -> BatchReviewRunResponse:
    return BatchReviewRunResponse(
        id=view.id,
        status=view.status.value,
        revision=view.revision,
        summary=BatchReviewSummaryResponse(
            total=view.summary.total,
            eligible=view.summary.eligible,
            active=view.summary.active,
            ready_for_publish=view.summary.ready_for_publish,
            manual_review=view.summary.manual_review,
            failed=view.summary.failed,
            skipped=view.summary.skipped,
        ),
        items=[_item_response(item) for item in view.items],
        allowed_actions=list(view.allowed_actions),
    )


def _api_error(error: Exception) -> ApiError:
    if isinstance(error, BatchReviewNotFound):
        return ApiError(
            404, "batch_review_not_found", "The batch review was not found."
        )
    if isinstance(error, BatchReviewPermissionDenied):
        return ApiError(
            403, "batch_review_forbidden", "Batch review permission was denied."
        )
    if isinstance(error, BatchReviewBusy):
        return ApiError(503, "batch_review_busy", "Batch review is temporarily busy.")
    if isinstance(error, BatchReviewOutcomeUnknown):
        return ApiError(503, "outcome_unknown", "The server result must be reloaded.")
    if isinstance(
        error,
        (
            BatchReviewRevisionConflict,
            BatchReviewOperationConflict,
            BatchReviewStateConflict,
        ),
    ):
        return ApiError(409, "batch_review_conflict", "Batch review state changed.")
    if isinstance(error, ValueError):
        return ApiError(
            422, "batch_review_invalid", "The batch review request is invalid."
        )
    if isinstance(error, BatchReviewError):
        return ApiError(
            409, "batch_review_conflict", "Batch review could not continue."
        )
    raise error


@router.post("/preflight", response_model=BatchReviewRunResponse, status_code=201)
def create_preflight(
    payload: PreflightRequest,
    principal: _ManagerWrite,
    engine: _Engine,
    operation_token: _IdempotencyKey,
) -> BatchReviewRunResponse:
    try:
        view = _service(engine).create_preflight(
            CreatePreflightCommand(
                site_id=_site_id(engine),
                actor_user_id=principal.user_id,
                actor_roles=principal.roles,
                batch_ids=tuple(payload.batch_ids),
                operation_token=operation_token,
            )
        )
    except Exception as error:
        raise _api_error(error) from error
    return _run_response(view)


@router.get("")
def list_batch_reviews(
    principal: _ManagerRead,
    engine: _Engine,
    page: Annotated[int, Query(ge=1)] = 1,
) -> dict[str, object]:
    del principal
    site_id = _site_id(engine)
    with engine.connect() as connection:
        rows = (
            connection.execute(
                sa.text(
                    "SELECT id, status, revision, created_at FROM batch_review_runs "
                    "WHERE site_id = :site_id ORDER BY id DESC LIMIT 21 OFFSET :offset"
                ),
                {"site_id": site_id, "offset": (page - 1) * 20},
            )
            .mappings()
            .all()
        )
    return {"items": [dict(row) for row in rows[:20]], "has_next": len(rows) > 20}


@router.get("/{run_id}", response_model=BatchReviewRunResponse)
def get_batch_review(
    run_id: _PositivePathId,
    principal: _ManagerRead,
    engine: _Engine,
) -> BatchReviewRunResponse:
    del principal
    try:
        return _run_response(_service(engine).get_run(run_id, _site_id(engine)))
    except Exception as error:
        raise _api_error(error) from error


@router.post("/{run_id}/confirm", response_model=BatchReviewRunResponse)
def confirm_batch_review(
    run_id: _PositivePathId,
    payload: ConfirmRequest,
    principal: _ManagerWrite,
    engine: _Engine,
    operation_token: _IdempotencyKey,
) -> BatchReviewRunResponse:
    try:
        view = _service(engine).confirm(
            ConfirmBatchReviewCommand(
                run_id,
                _site_id(engine),
                principal.user_id,
                payload.expected_revision,
                tuple(payload.selected_item_ids),
                payload.confirmation_accepted,
                payload.confirmation_statement_version,
                operation_token,
            )
        )
    except Exception as error:
        raise _api_error(error) from error
    return _run_response(view)


@router.post(
    "/{run_id}/items/{item_id}/advance",
    response_model=BatchReviewItemResponse,
)
def advance_batch_review_item(
    run_id: _PositivePathId,
    item_id: _PositivePathId,
    principal: _ManagerWrite,
    engine: _Engine,
    operation_token: _IdempotencyKey,
) -> BatchReviewItemResponse:
    try:
        item = _service(engine, advance=True).advance_item(
            AdvanceBatchReviewItemCommand(
                run_id,
                item_id,
                _site_id(engine),
                principal.user_id,
                operation_token,
            )
        )
        if item.outcome_unknown:
            raise BatchReviewOutcomeUnknown("advance outcome is unknown")
    except Exception as error:
        raise _api_error(error) from error
    return _item_response(item)


def _change_run(
    *,
    action: Literal["pause", "resume"],
    run_id: int,
    payload: RevisionRequest,
    principal: Principal,
    engine: Engine,
    operation_token: UUID,
) -> BatchReviewRunResponse:
    try:
        command = ChangeBatchReviewRunStateCommand(
            run_id,
            _site_id(engine),
            principal.user_id,
            payload.expected_revision,
            action,
            operation_token,
        )
        service = _service(engine)
        view = service.pause(command) if action == "pause" else service.resume(command)
    except Exception as error:
        raise _api_error(error) from error
    return _run_response(view)


@router.post("/{run_id}/pause", response_model=BatchReviewRunResponse)
def pause_batch_review(
    run_id: _PositivePathId,
    payload: RevisionRequest,
    principal: _ManagerWrite,
    engine: _Engine,
    operation_token: _IdempotencyKey,
) -> BatchReviewRunResponse:
    return _change_run(
        action="pause",
        run_id=run_id,
        payload=payload,
        principal=principal,
        engine=engine,
        operation_token=operation_token,
    )


@router.post("/{run_id}/resume", response_model=BatchReviewRunResponse)
def resume_batch_review(
    run_id: _PositivePathId,
    payload: RevisionRequest,
    principal: _ManagerWrite,
    engine: _Engine,
    operation_token: _IdempotencyKey,
) -> BatchReviewRunResponse:
    return _change_run(
        action="resume",
        run_id=run_id,
        payload=payload,
        principal=principal,
        engine=engine,
        operation_token=operation_token,
    )


@router.post(
    "/{run_id}/items/{item_id}/retry",
    response_model=BatchReviewRunResponse,
)
def retry_batch_review_item(
    run_id: _PositivePathId,
    item_id: _PositivePathId,
    payload: RevisionRequest,
    principal: _ManagerWrite,
    engine: _Engine,
    operation_token: _IdempotencyKey,
) -> BatchReviewRunResponse:
    try:
        view = _service(engine).retry_item(
            RetryBatchReviewItemCommand(
                run_id,
                item_id,
                _site_id(engine),
                principal.user_id,
                payload.expected_revision,
                operation_token,
            )
        )
    except Exception as error:
        raise _api_error(error) from error
    return _run_response(view)


__all__ = ["CONFIRMATION_STATEMENT_VERSION", "router"]
