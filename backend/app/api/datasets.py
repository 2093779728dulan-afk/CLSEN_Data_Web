"""Secured HTTP commands for daily-dataset draft transactions."""

from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, date, datetime
from decimal import Decimal
from typing import Annotated, Literal
from uuid import UUID

from fastapi import APIRouter, Depends, Header
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.engine import Engine

from app.api.dependencies import get_database_engine, require_roles, require_write_roles
from app.api.errors import ApiError
from app.auth.sessions import Principal
from app.datasets.repository import MySqlDatasetRepository
from app.datasets.service import DatasetService
from app.datasets.types import (
    ActiveDraftConflict,
    ActiveDraftReassignmentTarget,
    BaselineConflict,
    BaselineNotFound,
    DatasetCommitOutcomeUnknown,
    DatasetError,
    DatasetPermissionDenied,
    DatasetSiteConflict,
    DatasetTransactionBusy,
    DiscardDraftCommand,
    DraftMutationResult,
    EmptyReassignmentTarget,
    ForceRebuildDraftCommand,
    MaterializeBaselineCommand,
    MergeConflict,
    MergeDecision,
    OperationConflict,
    PublishedLineageConflict,
    PublishedReassignmentTarget,
    ReassignmentTarget,
    ReassignUnpublishedDraftDateCommand,
    RevisionConflict,
    SealedVersionConflict,
    TargetConflict,
    VersionExpectation,
)

router = APIRouter(tags=["datasets"])
_Manager = Annotated[Principal, Depends(require_write_roles("admin", "data_manager"))]
_Administrator = Annotated[Principal, Depends(require_write_roles("admin"))]
_Reviewer = Annotated[Principal, Depends(require_roles("admin", "data_manager"))]
_Engine = Annotated[Engine, Depends(get_database_engine)]
_IdempotencyKey = Annotated[UUID, Header(alias="Idempotency-Key")]


class _StrictRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")


class VersionExpectationRequest(_StrictRequest):
    version_id: int = Field(gt=0)
    data_revision: int = Field(ge=0)
    review_revision: int = Field(ge=0)

    def to_domain(self) -> VersionExpectation:
        return VersionExpectation(
            version_id=self.version_id,
            data_revision=self.data_revision,
            review_revision=self.review_revision,
        )


class MergeDecisionRequest(_StrictRequest):
    target_row_id: int = Field(gt=0)
    source_row_id: int = Field(gt=0)
    action: Literal["keep_target", "keep_source", "keep_both"]
    reason: str | None = None

    def to_domain(self) -> MergeDecision:
        return MergeDecision(
            target_row_id=self.target_row_id,
            source_row_id=self.source_row_id,
            action=self.action,
            reason=self.reason,
        )


class MergeConflictPreviewResponse(BaseModel):
    target_row_id: int
    target_row_ordinal: int
    target_values: dict[str, str | None]
    source_row_id: int
    source_row_ordinal: int
    source_values: dict[str, str | None]


class MergePreviewResponse(BaseModel):
    report_type: Literal["business_report", "return_report"]
    target_version_id: int
    source_kind: Literal["parse_baseline", "dataset_version"]
    source_id: int
    conflicts: list[MergeConflictPreviewResponse]


class MaterializeBaselineRequest(_StrictRequest):
    batch_id: int = Field(gt=0)
    parse_baseline_id: int = Field(gt=0)
    report_date: date
    strategy: Literal["merge", "replace"]
    expected_active_draft: VersionExpectationRequest | None = None
    expected_publication_version_id: int | None = Field(default=None, gt=0)
    merge_decisions: list[MergeDecisionRequest] = Field(default_factory=list)
    reason: str = Field(min_length=1, max_length=1000)


class ForceRebuildDraftRequest(_StrictRequest):
    batch_id: int = Field(gt=0)
    parse_baseline_id: int = Field(gt=0)
    report_date: date
    expected_active_draft: VersionExpectationRequest
    expected_publication_version_id: int | None = Field(default=None, gt=0)
    reason: str = Field(min_length=1, max_length=1000)


class DiscardDraftRequest(_StrictRequest):
    dataset_id: int = Field(gt=0)
    expected_active_draft: VersionExpectationRequest
    reason: str = Field(min_length=1, max_length=1000)


class EmptyReassignmentTargetRequest(_StrictRequest):
    target_kind: Literal["empty"]
    expected_dataset_id: None = None


class PublishedReassignmentTargetRequest(_StrictRequest):
    target_kind: Literal["published"]
    expected_dataset_id: int = Field(gt=0)
    expected_publication_version_id: int = Field(gt=0)
    strategy: Literal["merge", "replace"]


class ActiveDraftReassignmentTargetRequest(_StrictRequest):
    target_kind: Literal["active_draft"]
    expected_dataset_id: int = Field(gt=0)
    expected_active_draft: VersionExpectationRequest
    expected_publication_version_id: int | None = Field(default=None, gt=0)
    action: Literal["merge", "cancel"]


type ReassignmentTargetRequest = Annotated[
    EmptyReassignmentTargetRequest
    | PublishedReassignmentTargetRequest
    | ActiveDraftReassignmentTargetRequest,
    Field(discriminator="target_kind"),
]


class ReassignDraftDateRequest(_StrictRequest):
    source_dataset_id: int = Field(gt=0)
    source_draft: VersionExpectationRequest
    target_report_date: date
    target: ReassignmentTargetRequest
    merge_decisions: list[MergeDecisionRequest] = Field(default_factory=list)
    reason: str = Field(min_length=1, max_length=1000)


class DraftMutationResponse(BaseModel):
    operation_token: UUID
    dataset_id: int
    version_id: int
    version_no: int
    status: Literal["draft", "discarded", "cancelled"]
    data_revision: int
    review_revision: int
    superseded_version_ids: list[int]
    source_dataset_id: int | None
    source_version_id: int | None

    @classmethod
    def from_domain(cls, result: DraftMutationResult) -> DraftMutationResponse:
        return cls(
            operation_token=result.operation_token,
            dataset_id=result.dataset_id,
            version_id=result.version_id,
            version_no=result.version_no,
            status=result.status,
            data_revision=result.data_revision,
            review_revision=result.review_revision,
            superseded_version_ids=list(result.superseded_version_ids),
            source_dataset_id=result.source_dataset_id,
            source_version_id=result.source_version_id,
        )


def _service(engine: Engine) -> DatasetService:
    return DatasetService(repository=MySqlDatasetRepository(engine))


def _dataset_error(error: DatasetError) -> ApiError:
    if isinstance(error, DatasetPermissionDenied):
        return ApiError(
            403,
            "dataset_forbidden",
            "Permission to change this dataset was denied.",
        )
    if isinstance(error, BaselineNotFound):
        return ApiError(404, "baseline_not_found", "The parse baseline was not found.")
    if isinstance(error, DatasetTransactionBusy):
        return ApiError(503, "dataset_busy", "The dataset is temporarily busy.")
    if isinstance(error, DatasetCommitOutcomeUnknown):
        return ApiError(
            503,
            "dataset_outcome_unknown",
            "The dataset command outcome could not be confirmed.",
        )
    if isinstance(error, (ActiveDraftConflict, RevisionConflict)):
        return ApiError(
            409,
            "draft_head_conflict",
            "The active draft changed. Refresh it before retrying.",
        )
    if isinstance(
        error,
        (
            BaselineConflict,
            DatasetSiteConflict,
            MergeConflict,
            OperationConflict,
            PublishedLineageConflict,
            SealedVersionConflict,
            TargetConflict,
        ),
    ):
        return ApiError(
            409,
            "dataset_conflict",
            "The dataset command conflicts with current state.",
        )
    return ApiError(
        503,
        "dataset_unavailable",
        "The dataset command could not be completed.",
    )


def _preview_value(value: object) -> str | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        if value.tzinfo is None or value.utcoffset() is None:
            value = value.replace(tzinfo=UTC)
        return value.astimezone(UTC).isoformat().replace("+00:00", "Z")
    if isinstance(value, date):
        return value.isoformat()
    if isinstance(value, Decimal):
        return format(value, "f")
    if isinstance(value, bool):
        return "true" if value else "false"
    return str(value)


@router.get(
    "/api/datasets/merge-preview",
    response_model=MergePreviewResponse,
)
def preview_merge_conflicts(
    target_version_id: int,
    source_kind: Literal["parse_baseline", "dataset_version"],
    source_id: int,
    _principal: _Reviewer,
    engine: _Engine,
) -> MergePreviewResponse:
    try:
        preview = MySqlDatasetRepository(engine).preview_merge_conflicts(
            target_version_id=target_version_id,
            source_kind=source_kind,
            source_id=source_id,
        )
    except ValueError as error:
        raise ApiError(
            422,
            "invalid_merge_preview",
            "The merge preview request is invalid.",
        ) from error
    except DatasetError as error:
        raise _dataset_error(error) from error
    return MergePreviewResponse(
        report_type=preview.report_type,
        target_version_id=target_version_id,
        source_kind=source_kind,
        source_id=source_id,
        conflicts=[
            MergeConflictPreviewResponse(
                target_row_id=item.target_row_id,
                target_row_ordinal=item.target_row_ordinal,
                target_values={
                    name: _preview_value(value) for name, value in item.target_values
                },
                source_row_id=item.source_row_id,
                source_row_ordinal=item.source_row_ordinal,
                source_values={
                    name: _preview_value(value) for name, value in item.source_values
                },
            )
            for item in preview.conflicts
        ],
    )


def _target(payload: ReassignmentTargetRequest) -> ReassignmentTarget:
    if isinstance(payload, EmptyReassignmentTargetRequest):
        return EmptyReassignmentTarget()
    if isinstance(payload, PublishedReassignmentTargetRequest):
        return PublishedReassignmentTarget(
            expected_dataset_id=payload.expected_dataset_id,
            expected_publication_version_id=(payload.expected_publication_version_id),
            strategy=payload.strategy,
        )
    return ActiveDraftReassignmentTarget(
        expected_dataset_id=payload.expected_dataset_id,
        expected_active_draft=payload.expected_active_draft.to_domain(),
        expected_publication_version_id=payload.expected_publication_version_id,
        action=payload.action,
    )


def _run_dataset_command(
    command_call: Callable[[], DraftMutationResult],
) -> DraftMutationResponse:
    try:
        return DraftMutationResponse.from_domain(command_call())
    except ValueError as error:
        raise ApiError(
            422,
            "invalid_dataset_command",
            "The dataset command is invalid.",
        ) from error
    except DatasetError as error:
        raise _dataset_error(error) from error


@router.post(
    "/api/datasets/materialize",
    response_model=DraftMutationResponse,
    status_code=201,
)
def materialize_baseline(
    payload: MaterializeBaselineRequest,
    principal: _Manager,
    engine: _Engine,
    operation_token: _IdempotencyKey,
) -> DraftMutationResponse:
    return _run_dataset_command(
        lambda: _service(engine).materialize_baseline(
            MaterializeBaselineCommand(
                batch_id=payload.batch_id,
                parse_baseline_id=payload.parse_baseline_id,
                report_date=payload.report_date,
                strategy=payload.strategy,
                expected_active_draft=(
                    payload.expected_active_draft.to_domain()
                    if payload.expected_active_draft is not None
                    else None
                ),
                expected_publication_version_id=(
                    payload.expected_publication_version_id
                ),
                merge_decisions=tuple(
                    decision.to_domain() for decision in payload.merge_decisions
                ),
                actor_user_id=principal.user_id,
                operation_token=operation_token,
                reason=payload.reason,
            )
        )
    )


@router.post(
    "/api/admin/drafts/{version_id}/force-rebuild",
    response_model=DraftMutationResponse,
    status_code=201,
)
def force_rebuild_draft(
    version_id: int,
    payload: ForceRebuildDraftRequest,
    principal: _Administrator,
    engine: _Engine,
    operation_token: _IdempotencyKey,
) -> DraftMutationResponse:
    if payload.expected_active_draft.version_id != version_id:
        raise ApiError(
            422,
            "draft_identity_mismatch",
            "The path and expected draft identify different versions.",
        )
    return _run_dataset_command(
        lambda: _service(engine).force_rebuild_draft(
            ForceRebuildDraftCommand(
                batch_id=payload.batch_id,
                parse_baseline_id=payload.parse_baseline_id,
                report_date=payload.report_date,
                expected_active_draft=payload.expected_active_draft.to_domain(),
                expected_publication_version_id=(
                    payload.expected_publication_version_id
                ),
                actor_user_id=principal.user_id,
                operation_token=operation_token,
                reason=payload.reason,
            )
        )
    )


@router.post(
    "/api/drafts/{version_id}/discard",
    response_model=DraftMutationResponse,
)
def discard_draft(
    version_id: int,
    payload: DiscardDraftRequest,
    principal: _Manager,
    engine: _Engine,
    operation_token: _IdempotencyKey,
) -> DraftMutationResponse:
    if payload.expected_active_draft.version_id != version_id:
        raise ApiError(
            422,
            "draft_identity_mismatch",
            "The path and expected draft identify different versions.",
        )
    return _run_dataset_command(
        lambda: _service(engine).discard_active_draft(
            DiscardDraftCommand(
                dataset_id=payload.dataset_id,
                expected_active_draft=payload.expected_active_draft.to_domain(),
                actor_user_id=principal.user_id,
                operation_token=operation_token,
                reason=payload.reason,
            )
        )
    )


@router.post(
    "/api/drafts/{version_id}/reassign-date",
    response_model=DraftMutationResponse,
)
def reassign_draft_date(
    version_id: int,
    payload: ReassignDraftDateRequest,
    principal: _Manager,
    engine: _Engine,
    operation_token: _IdempotencyKey,
) -> DraftMutationResponse:
    if payload.source_draft.version_id != version_id:
        raise ApiError(
            422,
            "draft_identity_mismatch",
            "The path and expected draft identify different versions.",
        )
    return _run_dataset_command(
        lambda: _service(engine).reassign_unpublished_draft_date(
            ReassignUnpublishedDraftDateCommand(
                source_dataset_id=payload.source_dataset_id,
                source_draft=payload.source_draft.to_domain(),
                target_report_date=payload.target_report_date,
                target=_target(payload.target),
                merge_decisions=tuple(
                    decision.to_domain() for decision in payload.merge_decisions
                ),
                actor_user_id=principal.user_id,
                operation_token=operation_token,
                reason=payload.reason,
            )
        )
    )
