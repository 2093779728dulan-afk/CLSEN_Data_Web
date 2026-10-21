"""Auditable draft-correction and ready-for-publication commands."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import asdict
from datetime import UTC, date, datetime
from decimal import Decimal, InvalidOperation
from typing import Annotated, Literal, Self, cast
from uuid import UUID

import sqlalchemy as sa
from fastapi import APIRouter, Depends, Header, Path
from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    ValidationInfo,
    field_validator,
    model_validator,
)
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session

from app.api.dependencies import (
    get_database_engine,
    get_database_session,
    require_roles,
    require_write_roles,
)
from app.api.errors import ApiError
from app.auth.sessions import Principal
from app.review.repository import MySqlReviewRepository
from app.review.service import ReviewService
from app.review.types import (
    AddRowCommand,
    ChangeRowStateCommand,
    CreateNoteCommand,
    DraftHeadExpectation,
    FieldNoteTarget,
    FieldRestoreSource,
    ImportBatchNoteTarget,
    MarkReadyCommand,
    NoteTarget,
    ParentValueSource,
    PreviousValueSource,
    RestoreFieldValueCommand,
    ReturnToDraftCommand,
    ReviewCommitOutcomeUnknown,
    ReviewError,
    ReviewIssueCommand,
    ReviewPermissionDenied,
    ReviewTransactionBusy,
    ReviseNoteCommand,
    RowNoteTarget,
    SetFieldValueCommand,
    SourceFileValueSource,
    VersionNoteTarget,
)
from app.validation.fields import FieldValue

router = APIRouter(prefix="/api", tags=["review"])
_Manager = Annotated[Principal, Depends(require_write_roles("admin", "data_manager"))]
_ManagerRead = Annotated[Principal, Depends(require_roles("admin", "data_manager"))]
_Engine = Annotated[Engine, Depends(get_database_engine)]
_DatabaseSession = Annotated[
    Session,
    Depends(get_database_session, scope="function"),
]
_IdempotencyKey = Annotated[UUID, Header(alias="Idempotency-Key")]
_PositivePathId = Annotated[int, Path(ge=1)]
_NonBlankPathText = Annotated[str, Path(pattern=r".*\S.*")]
_NoteKeyPath = Annotated[
    str,
    Path(min_length=1, max_length=64, pattern=r".*\S.*"),
]
_StrictInt = Annotated[int, Field(strict=True)]
_NONBLANK_REQUEST_FIELDS = frozenset(
    {"body", "comment", "field_name", "reason", "ruleset_version"}
)


class _ReviewRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    @field_validator("*", check_fields=False)
    @classmethod
    def reject_blank_strings(
        cls,
        value: object,
        info: ValidationInfo,
    ) -> object:
        if (
            info.field_name in _NONBLANK_REQUEST_FIELDS
            and isinstance(value, str)
            and not value.strip()
        ):
            raise ValueError(f"{info.field_name} must not be blank")
        return value


class DraftHeadRequest(_ReviewRequest):
    dataset_id: int = Field(ge=1, strict=True)
    status: Literal["draft", "ready_for_publish"]
    data_revision: int = Field(ge=0, strict=True)
    review_revision: int = Field(ge=0, strict=True)
    pointed_at: datetime

    @field_validator("pointed_at")
    @classmethod
    def require_aware_pointed_at(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("pointed_at must include a timezone offset")
        try:
            return value.astimezone(UTC)
        except (OverflowError, ValueError) as error:
            raise ValueError("pointed_at is outside the supported range") from error


class TypedFieldValueRequest(_ReviewRequest):
    """An explicit wire representation that preserves typed spreadsheet values."""

    type: Literal["text", "integer", "decimal", "utc_datetime", "null"]
    value: str | _StrictInt | None


class SetFieldRequest(DraftHeadRequest):
    row_id: int = Field(ge=1, strict=True)
    field_name: str
    value: TypedFieldValueRequest
    reason: str = Field(min_length=1, max_length=4096)


class RestoreFieldRequest(DraftHeadRequest):
    row_id: int = Field(ge=1, strict=True)
    source_kind: Literal["previous", "parent", "source"]
    field_change_id: int | None = Field(default=None, ge=1, strict=True)
    parent_version_id: int | None = Field(default=None, ge=1, strict=True)
    source_batch_id: int | None = Field(default=None, ge=1, strict=True)
    parsed_source_row_id: int | None = Field(default=None, ge=1, strict=True)
    reason: str = Field(min_length=1, max_length=4096)

    @model_validator(mode="after")
    def require_restore_source_identifier(self) -> Self:
        if self.source_kind == "previous" and self.field_change_id is None:
            raise ValueError("previous restoration requires field_change_id")
        if self.source_kind == "parent" and self.parent_version_id is None:
            raise ValueError("parent restoration requires parent_version_id")
        if self.source_kind == "source" and (
            self.source_batch_id is None or self.parsed_source_row_id is None
        ):
            raise ValueError(
                "source restoration requires source_batch_id and parsed_source_row_id"
            )
        return self


class AddRowRequest(DraftHeadRequest):
    source_batch_id: int = Field(ge=1, strict=True)
    values: dict[str, TypedFieldValueRequest] = Field(min_length=1)
    reason: str = Field(min_length=1, max_length=4096)

    @field_validator("values")
    @classmethod
    def require_named_values(
        cls,
        values: dict[str, TypedFieldValueRequest],
    ) -> dict[str, TypedFieldValueRequest]:
        if any(not field_name.strip() for field_name in values):
            raise ValueError("row value field names must not be blank")
        return values


class ChangeRowStateRequest(DraftHeadRequest):
    operation: Literal["exclude", "restore", "delete"]
    reason: str = Field(min_length=1, max_length=4096)


class CreateNoteRequest(_ReviewRequest):
    expected_review_revision: int = Field(ge=0, strict=True)
    target_type: Literal["version", "row", "field"] = "version"
    row_id: int | None = Field(default=None, ge=1, strict=True)
    field_name: str | None = None
    body: str = Field(min_length=1, max_length=4096)
    visibility: Literal["internal", "viewer_visible"] = "internal"

    @model_validator(mode="after")
    def require_note_target_fields(self) -> Self:
        if self.target_type in {"row", "field"} and self.row_id is None:
            raise ValueError("row and field notes require row_id")
        if self.target_type == "field" and self.field_name is None:
            raise ValueError("field notes require field_name")
        return self


class ReviseNoteRequest(CreateNoteRequest):
    expected_note_id: int = Field(ge=1, strict=True)
    expected_revision_number: int = Field(ge=1, strict=True)


class CreateImportBatchNoteRequest(_ReviewRequest):
    body: str = Field(min_length=1, max_length=4096)
    visibility: Literal["internal"] = "internal"


class ReviseImportBatchNoteRequest(CreateImportBatchNoteRequest):
    expected_note_id: int = Field(ge=1, strict=True)
    expected_revision_number: int = Field(ge=1, strict=True)


class ImportBatchNoteResponse(BaseModel):
    note_key: str
    note_id: int
    revision_number: int
    target_type: Literal["import_batch"] = "import_batch"
    import_batch_id: int
    visibility: Literal["internal", "viewer_visible"]
    body: str
    author_user_id: int
    author_username: str
    created_at: datetime


class ReviewIssueRequest(DraftHeadRequest):
    validation_run_id: int = Field(ge=1, strict=True)
    issue_severity: Literal["warning", "blocking"]
    issue_requires_note: bool = Field(strict=True)
    action: Literal["acknowledge", "resolve", "reopen"]
    comment: str | None = Field(default=None, max_length=4096)

    @model_validator(mode="after")
    def validate_issue_action(self) -> Self:
        if self.action == "acknowledge" and self.issue_severity != "warning":
            raise ValueError("acknowledge is only valid for a warning")
        if self.action in {"resolve", "reopen"} and self.issue_severity != "blocking":
            raise ValueError("resolve and reopen are only valid for blocking issues")
        if (
            self.action == "resolve"
            or (self.action == "acknowledge" and self.issue_requires_note)
        ) and self.comment is None:
            raise ValueError("comment is required for this issue review")
        return self


class ReturnToDraftRequest(DraftHeadRequest):
    reason: str = Field(min_length=1, max_length=4096)

    @model_validator(mode="after")
    def require_ready_status(self) -> Self:
        if self.status != "ready_for_publish":
            raise ValueError("only a ready version can return to draft")
        return self


class MarkReadyRequest(DraftHeadRequest):
    validation_run_id: int = Field(ge=1, strict=True)
    validation_data_digest: str = Field(pattern=r"^[0-9a-f]{64}$")
    ruleset_version: str = Field(min_length=1, max_length=128)
    confirmed_report_date: date
    confirmed_report_type: Literal["business_report", "return_report"]
    confirmed_row_count: int = Field(ge=0, strict=True)
    confirmed_totals: dict[str, str]
    reason: str = Field(min_length=1, max_length=4096)

    @field_validator("confirmed_totals")
    @classmethod
    def require_named_totals(cls, values: dict[str, str]) -> dict[str, str]:
        if any(not name.strip() or not value.strip() for name, value in values.items()):
            raise ValueError("confirmed total names and values must not be blank")
        return values

    @model_validator(mode="after")
    def require_draft_status(self) -> Self:
        if self.status != "draft":
            raise ValueError("only a draft can be marked ready")
        return self


def _head(version_id: int, payload: DraftHeadRequest) -> DraftHeadExpectation:
    return DraftHeadExpectation(
        dataset_id=payload.dataset_id,
        version_id=version_id,
        status=payload.status,
        data_revision=payload.data_revision,
        review_revision=payload.review_revision,
        pointed_at=payload.pointed_at,
    )


def _service(engine: Engine) -> ReviewService:
    return ReviewService(repository=MySqlReviewRepository(engine))


def _review_error(error: ReviewError) -> ApiError:
    if isinstance(error, ReviewPermissionDenied):
        return ApiError(
            403,
            "draft_forbidden",
            "Permission to edit this draft was denied.",
        )
    if isinstance(error, ReviewTransactionBusy):
        return ApiError(503, "draft_busy", "The draft is temporarily busy.")
    if isinstance(error, ReviewCommitOutcomeUnknown):
        return ApiError(
            503,
            "draft_outcome_unknown",
            "The review command outcome could not be confirmed.",
        )
    return ApiError(409, "draft_conflict", "The draft changed before this operation.")


def _request_error(message: str = "The supplied review value is invalid.") -> ApiError:
    return ApiError(422, "invalid_review_request", message)


def _request_command[CommandT](factory: Callable[[], CommandT]) -> CommandT:
    """Construct a domain command before allocating its database-backed service."""

    try:
        return factory()
    except ValueError as error:
        raise _request_error() from error


def _utc_timestamp(value: object) -> datetime:
    if not isinstance(value, datetime):
        raise RuntimeError("database timestamp is invalid")
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


def _typed_value(payload: TypedFieldValueRequest) -> FieldValue:
    if payload.type == "null":
        if payload.value is not None:
            raise _request_error("A null field value must contain null.")
        return None
    if payload.type == "text":
        if not isinstance(payload.value, str):
            raise _request_error("A text field value must contain text.")
        return payload.value
    if payload.type == "integer":
        if isinstance(payload.value, bool) or not isinstance(payload.value, int):
            raise _request_error("An integer field value must contain an integer.")
        return payload.value
    if payload.type == "decimal":
        if not isinstance(payload.value, str):
            raise _request_error("A decimal field value must contain decimal text.")
        try:
            decimal_value = Decimal(payload.value)
        except InvalidOperation as error:
            raise _request_error("The decimal field value is invalid.") from error
        if not decimal_value.is_finite():
            raise _request_error("The decimal field value must be finite.")
        return decimal_value
    if not isinstance(payload.value, str) or not payload.value.endswith("Z"):
        raise _request_error("A UTC datetime field value must end in Z.")
    try:
        timestamp = datetime.fromisoformat(payload.value[:-1] + "+00:00")
    except ValueError as error:
        raise _request_error("The UTC datetime field value is invalid.") from error
    return timestamp.astimezone(UTC)


def _restore_source(payload: RestoreFieldRequest) -> FieldRestoreSource:
    if payload.source_kind == "previous":
        if payload.field_change_id is None:
            raise _request_error("Previous-value restoration requires field_change_id.")
        return PreviousValueSource(field_change_id=payload.field_change_id)
    if payload.source_kind == "parent":
        if payload.parent_version_id is None:
            raise _request_error("Parent-value restoration requires parent_version_id.")
        return ParentValueSource(parent_version_id=payload.parent_version_id)
    if payload.source_batch_id is None or payload.parsed_source_row_id is None:
        raise _request_error(
            "Source-file restoration requires source_batch_id and parsed_source_row_id."
        )
    return SourceFileValueSource(
        source_batch_id=payload.source_batch_id,
        parsed_source_row_id=payload.parsed_source_row_id,
    )


def _note_target(version_id: int, payload: CreateNoteRequest) -> NoteTarget:
    if payload.target_type == "version":
        return VersionNoteTarget(version_id=version_id)
    if payload.row_id is None:
        raise _request_error("A row or field note requires row_id.")
    if payload.target_type == "row":
        return RowNoteTarget(version_id=version_id, row_id=payload.row_id)
    if payload.field_name is None or not payload.field_name.strip():
        raise _request_error("A field note requires field_name.")
    return FieldNoteTarget(
        version_id=version_id,
        row_id=payload.row_id,
        field_name=payload.field_name,
    )


@router.post("/drafts/{version_id}/fields")
def set_field(
    version_id: _PositivePathId,
    payload: SetFieldRequest,
    principal: _Manager,
    engine: _Engine,
    operation_token: _IdempotencyKey,
) -> dict[str, object]:
    command = _request_command(
        lambda: SetFieldValueCommand(
            head=_head(version_id, payload),
            row_id=payload.row_id,
            field_name=payload.field_name,
            value=_typed_value(payload.value),
            actor_user_id=principal.user_id,
            operation_token=operation_token,
            reason=payload.reason,
        )
    )
    try:
        result = _service(engine).set_field_value(command)
    except ReviewError as error:
        raise _review_error(error) from error
    return {"result": asdict(result)}


@router.post("/drafts/{version_id}/fields/{field_name}/restore")
def restore_field(
    version_id: _PositivePathId,
    field_name: _NonBlankPathText,
    payload: RestoreFieldRequest,
    principal: _Manager,
    engine: _Engine,
    operation_token: _IdempotencyKey,
) -> dict[str, object]:
    command = _request_command(
        lambda: RestoreFieldValueCommand(
            head=_head(version_id, payload),
            row_id=payload.row_id,
            field_name=field_name,
            source=_restore_source(payload),
            actor_user_id=principal.user_id,
            operation_token=operation_token,
            reason=payload.reason,
        )
    )
    try:
        result = _service(engine).restore_field_value(command)
    except ReviewError as error:
        raise _review_error(error) from error
    return {"result": asdict(result)}


@router.post("/drafts/{version_id}/rows")
def add_row(
    version_id: _PositivePathId,
    payload: AddRowRequest,
    principal: _Manager,
    engine: _Engine,
    operation_token: _IdempotencyKey,
) -> dict[str, object]:
    command = _request_command(
        lambda: AddRowCommand(
            head=_head(version_id, payload),
            source_batch_id=payload.source_batch_id,
            values=tuple(
                (field_name, _typed_value(value))
                for field_name, value in payload.values.items()
            ),
            actor_user_id=principal.user_id,
            operation_token=operation_token,
            reason=payload.reason,
        )
    )
    try:
        result = _service(engine).add_row(command)
    except ReviewError as error:
        raise _review_error(error) from error
    return {"result": asdict(result)}


@router.post("/drafts/{version_id}/rows/{row_id}/state")
def change_row_state(
    version_id: _PositivePathId,
    row_id: _PositivePathId,
    payload: ChangeRowStateRequest,
    principal: _Manager,
    engine: _Engine,
    operation_token: _IdempotencyKey,
) -> dict[str, object]:
    command = _request_command(
        lambda: ChangeRowStateCommand(
            head=_head(version_id, payload),
            row_id=row_id,
            operation=payload.operation,
            actor_user_id=principal.user_id,
            operation_token=operation_token,
            reason=payload.reason,
        )
    )
    try:
        result = _service(engine).change_row_state(command)
    except ReviewError as error:
        raise _review_error(error) from error
    return {"result": asdict(result)}


@router.get(
    "/imports/{batch_id}/notes",
    response_model=list[ImportBatchNoteResponse],
)
def list_import_batch_notes(
    batch_id: _PositivePathId,
    principal: _ManagerRead,
    database_session: _DatabaseSession,
) -> list[ImportBatchNoteResponse]:
    """Return only the latest immutable revision of each batch note thread."""

    del principal
    batch_exists = database_session.scalar(
        sa.text("SELECT 1 FROM import_batches WHERE id = :batch_id LIMIT 1"),
        {"batch_id": batch_id},
    )
    if batch_exists is None:
        raise ApiError(404, "import_not_found", "The requested import was not found.")
    rows = database_session.execute(
        sa.text(
            """
            SELECT ranked.note_key, ranked.note_id, ranked.revision_number,
                   ranked.import_batch_id, ranked.visibility, ranked.body,
                   ranked.author_user_id, ranked.author_username,
                   ranked.created_at
            FROM (
                SELECT threads.note_key, notes.id AS note_id,
                       notes.revision_number, threads.import_batch_id,
                       notes.visibility, notes.body, notes.author_user_id,
                       users.username_normalized AS author_username,
                       notes.created_at,
                       ROW_NUMBER() OVER (
                           PARTITION BY threads.note_key
                           ORDER BY notes.revision_number DESC, notes.id DESC
                       ) AS note_rank
                FROM note_threads AS threads
                INNER JOIN notes ON notes.note_key = threads.note_key
                INNER JOIN users ON users.id = notes.author_user_id
                WHERE threads.target_type = 'import_batch'
                  AND threads.import_batch_id = :batch_id
            ) AS ranked
            WHERE ranked.note_rank = 1
            ORDER BY ranked.note_key
            """
        ),
        {"batch_id": batch_id},
    ).mappings()
    return [
        ImportBatchNoteResponse(
            note_key=str(row["note_key"]),
            note_id=int(row["note_id"]),
            revision_number=int(row["revision_number"]),
            import_batch_id=int(row["import_batch_id"]),
            visibility=cast(Literal["internal", "viewer_visible"], row["visibility"]),
            body=str(row["body"]),
            author_user_id=int(row["author_user_id"]),
            author_username=str(row["author_username"]),
            created_at=_utc_timestamp(row["created_at"]),
        )
        for row in rows
    ]


@router.post("/imports/{batch_id}/notes")
def create_import_batch_note(
    batch_id: _PositivePathId,
    payload: CreateImportBatchNoteRequest,
    principal: _Manager,
    engine: _Engine,
    operation_token: _IdempotencyKey,
) -> dict[str, object]:
    command = _request_command(
        lambda: CreateNoteCommand(
            target=ImportBatchNoteTarget(import_batch_id=batch_id),
            expected_review_revision=None,
            body=payload.body,
            actor_user_id=principal.user_id,
            operation_token=operation_token,
            visibility=payload.visibility,
        )
    )
    try:
        result = _service(engine).create_note(command)
    except ReviewError as error:
        raise _review_error(error) from error
    return {"result": asdict(result)}


@router.post("/imports/{batch_id}/notes/{note_key}/revisions")
def revise_import_batch_note(
    batch_id: _PositivePathId,
    note_key: _NoteKeyPath,
    payload: ReviseImportBatchNoteRequest,
    principal: _Manager,
    engine: _Engine,
    operation_token: _IdempotencyKey,
) -> dict[str, object]:
    command = _request_command(
        lambda: ReviseNoteCommand(
            note_key=note_key,
            expected_note_id=payload.expected_note_id,
            expected_revision_number=payload.expected_revision_number,
            target=ImportBatchNoteTarget(import_batch_id=batch_id),
            expected_review_revision=None,
            body=payload.body,
            actor_user_id=principal.user_id,
            operation_token=operation_token,
            visibility=payload.visibility,
        )
    )
    try:
        result = _service(engine).revise_note(command)
    except ReviewError as error:
        raise _review_error(error) from error
    return {"result": asdict(result)}


@router.post("/drafts/{version_id}/notes")
def create_note(
    version_id: _PositivePathId,
    payload: CreateNoteRequest,
    principal: _Manager,
    engine: _Engine,
    operation_token: _IdempotencyKey,
) -> dict[str, object]:
    command = _request_command(
        lambda: CreateNoteCommand(
            target=_note_target(version_id, payload),
            expected_review_revision=payload.expected_review_revision,
            body=payload.body,
            actor_user_id=principal.user_id,
            operation_token=operation_token,
            visibility=payload.visibility,
        )
    )
    try:
        result = _service(engine).create_note(command)
    except ReviewError as error:
        raise _review_error(error) from error
    return {"result": asdict(result)}


@router.post("/drafts/{version_id}/notes/{note_key}/revisions")
def revise_note(
    version_id: _PositivePathId,
    note_key: _NoteKeyPath,
    payload: ReviseNoteRequest,
    principal: _Manager,
    engine: _Engine,
    operation_token: _IdempotencyKey,
) -> dict[str, object]:
    command = _request_command(
        lambda: ReviseNoteCommand(
            note_key=note_key,
            expected_note_id=payload.expected_note_id,
            expected_revision_number=payload.expected_revision_number,
            target=_note_target(version_id, payload),
            expected_review_revision=payload.expected_review_revision,
            body=payload.body,
            actor_user_id=principal.user_id,
            operation_token=operation_token,
            visibility=payload.visibility,
        )
    )
    try:
        result = _service(engine).revise_note(command)
    except ReviewError as error:
        raise _review_error(error) from error
    return {"result": asdict(result)}


@router.post("/drafts/{version_id}/issues/{issue_id}/review")
def review_issue(
    version_id: _PositivePathId,
    issue_id: _PositivePathId,
    payload: ReviewIssueRequest,
    principal: _Manager,
    engine: _Engine,
    operation_token: _IdempotencyKey,
) -> dict[str, object]:
    command = _request_command(
        lambda: ReviewIssueCommand(
            head=_head(version_id, payload),
            validation_run_id=payload.validation_run_id,
            validation_issue_id=issue_id,
            issue_severity=payload.issue_severity,
            issue_requires_note=payload.issue_requires_note,
            action=payload.action,
            comment=payload.comment,
            actor_user_id=principal.user_id,
            operation_token=operation_token,
        )
    )
    try:
        result = _service(engine).review_issue(command)
    except ReviewError as error:
        raise _review_error(error) from error
    return {"result": asdict(result)}


@router.post("/drafts/{version_id}/mark-ready")
def mark_ready(
    version_id: _PositivePathId,
    payload: MarkReadyRequest,
    principal: _Manager,
    engine: _Engine,
    operation_token: _IdempotencyKey,
) -> dict[str, object]:
    command = _request_command(
        lambda: MarkReadyCommand(
            head=_head(version_id, payload),
            validation_run_id=payload.validation_run_id,
            validation_data_digest=bytes.fromhex(payload.validation_data_digest),
            ruleset_version=payload.ruleset_version,
            confirmed_report_date=payload.confirmed_report_date,
            confirmed_report_type=payload.confirmed_report_type,
            confirmed_row_count=payload.confirmed_row_count,
            confirmed_totals=tuple(payload.confirmed_totals.items()),
            actor_user_id=principal.user_id,
            operation_token=operation_token,
            reason=payload.reason,
        )
    )
    try:
        result = _service(engine).mark_ready(command)
    except ReviewError as error:
        raise _review_error(error) from error
    return {"result": asdict(result)}


@router.post("/drafts/{version_id}/return-to-draft")
def return_to_draft(
    version_id: _PositivePathId,
    payload: ReturnToDraftRequest,
    principal: _Manager,
    engine: _Engine,
    operation_token: _IdempotencyKey,
) -> dict[str, object]:
    command = _request_command(
        lambda: ReturnToDraftCommand(
            head=_head(version_id, payload),
            actor_user_id=principal.user_id,
            operation_token=operation_token,
            reason=payload.reason,
        )
    )
    try:
        result = _service(engine).return_to_draft(command)
    except ReviewError as error:
        raise _review_error(error) from error
    return {"result": asdict(result)}
