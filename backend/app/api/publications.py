"""Secured publication, revision, rollback, and published-date move API."""

from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, date, datetime
from typing import Annotated, Literal
from uuid import UUID

from fastapi import APIRouter, Depends, Header, Path, Query
from pydantic import UUID4, BaseModel, ConfigDict, Field
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session

from app.api.datasets import MergeDecisionRequest
from app.api.dependencies import (
    get_current_site_context,
    get_database_engine,
    get_database_session,
    require_roles,
    require_write_roles,
)
from app.api.errors import ApiError
from app.auth.sessions import Principal
from app.catalog.return_dedup_repository import (
    CreateReturnDedupStaging,
    DecideReturnDedupGroup,
    MySqlReturnDedupRepository,
    RetryReturnDedupStaging,
    ReturnDedupDecisionInvalid,
    ReturnDedupError,
    ReturnDedupGroupPage,
    ReturnDedupGroupView,
    ReturnDedupIdempotencyConflict,
    ReturnDedupJobRevisionConflict,
    ReturnDedupNotFound,
    ReturnDedupPermissionDenied,
    ReturnDedupPublicationRevisionConflict,
    ReturnDedupStagingConflict,
    ReturnDedupStagingFailed,
    ReturnDedupStagingNotReady,
    ReturnDedupStagingSuperseded,
)
from app.catalog.source_refs import SafeSourceRef
from app.publications.commands import (
    ActiveDraftMoveTarget,
    CreatePublishedMoveRevisionCommand,
    CreateRevisionCommand,
    DraftPointerExpectation,
    EmptyMoveTarget,
    FinalizePublishedMoveCommand,
    PublicationConfirmation,
    PublicationPointerExpectation,
    PublishCommand,
    PublishedMoveTarget,
    RollbackCommand,
    UndoPublishedMoveCommand,
    ValidationExpectation,
)
from app.publications.queries import (
    UndoablePublishedMove,
    UndoablePublishedMoveQueryService,
)
from app.publications.repository import (
    MySqlPublicationRepository,
    PublicationCommitOutcomeUnknown,
    PublicationError,
    PublicationOperationConflict,
    PublicationPermissionDenied,
    PublicationPointerConflict,
    PublicationStateConflict,
    PublicationTransactionBusy,
)
from app.publications.results import (
    DraftCommandResult,
    PublicationCommandResult,
    PublicationTransition,
)
from app.publications.rules import PublicationIneligible
from app.publications.service import PublicationService
from app.site_context import CurrentSiteContext

router = APIRouter(tags=["publications"])
_Manager = Annotated[Principal, Depends(require_write_roles("admin", "data_manager"))]
_ManagerRead = Annotated[Principal, Depends(require_roles("admin", "data_manager"))]
_Administrator = Annotated[Principal, Depends(require_write_roles("admin"))]
_AdministratorRead = Annotated[Principal, Depends(require_roles("admin"))]
_Engine = Annotated[Engine, Depends(get_database_engine)]
_DatabaseSession = Annotated[
    Session,
    Depends(get_database_session, scope="function"),
]
_IdempotencyKey = Annotated[UUID, Header(alias="Idempotency-Key")]
_SiteContext = Annotated[CurrentSiteContext, Depends(get_current_site_context)]


class _StrictRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")


class ReturnDedupStagingRequest(_StrictRequest):
    operation_token: UUID
    dataset_id: int = Field(gt=0)
    proposed_version_id: int = Field(gt=0)
    expected_publication_revision: int = Field(ge=0)
    expected_dedup_publication_revision: int = Field(ge=0)


class ReturnInitializationPreview(BaseModel):
    existing_job_id: int | None = None
    dataset_id: int
    proposed_version_id: int
    expected_publication_revision: int
    expected_dedup_publication_revision: int
    initialization_revision: int
    expected_set_digest: str
    published_return_reports: int
    coverage_from: date
    coverage_to: date


class ReturnInitializationRequest(ReturnDedupStagingRequest):
    operation_token: UUID4
    initialization_revision: int = Field(gt=0)
    expected_set_digest: str = Field(pattern=r"^[0-9a-f]{64}$")


class ReturnDedupRetryRequest(_StrictRequest):
    operation_token: UUID
    expected_job_revision: int = Field(ge=0)
    proposed_set_digest: str = Field(pattern=r"^[0-9a-f]{64}$")


class ReturnDedupStagingResponse(BaseModel):
    job_id: int
    status: Literal["building", "ready", "failed", "superseded"]
    job_revision: int
    proposed_set_digest: str
    failure_reason: str | None
    retry_allowed: bool
    next_job_revision: int
    result_snapshot_id: int | None
    command_url: str
    status_url: str


class ReturnDedupGroupMemberResponse(BaseModel):
    source_key_id: int
    source_ref: SafeSourceRef
    report_date: date
    dataset_id: int
    published_version_id: int


class ReturnDedupGroupResponse(BaseModel):
    group_id: str
    group_revision: int
    decision: Literal["unresolved", "confirmed_distinct", "duplicate_of"]
    canonical_member_id: int | None
    member_count: int
    members: list[ReturnDedupGroupMemberResponse]


class ReturnDedupGroupPageResponse(BaseModel):
    dedup_publication_revision: int
    snapshot_id: int
    page: int
    page_size: int
    total_items: int
    groups: list[ReturnDedupGroupResponse]


class ReturnDedupDecisionRequest(_StrictRequest):
    operation_token: UUID
    expected_dedup_publication_revision: int = Field(ge=0)
    expected_group_revision: int = Field(ge=1)
    decision: Literal["confirmed_distinct", "duplicate_of"]
    canonical_member_id: int | None = Field(default=None, gt=0)
    reason: str = Field(min_length=1, max_length=500)


class ReturnDedupDecisionResponse(BaseModel):
    group_id: str
    group_revision: int
    dedup_publication_revision: int
    snapshot_id: int
    decision: Literal["confirmed_distinct", "duplicate_of"]
    canonical_member_id: int | None


def _group_response(group: ReturnDedupGroupView) -> ReturnDedupGroupResponse:
    return ReturnDedupGroupResponse(
        group_id=group.group_id,
        group_revision=group.group_revision,
        decision=group.decision,
        canonical_member_id=group.canonical_member_id,
        member_count=group.member_count,
        members=[
            ReturnDedupGroupMemberResponse(
                source_key_id=member.source_key_id,
                source_ref=member.source_ref,
                report_date=member.report_date,
                dataset_id=member.dataset_id,
                published_version_id=member.published_version_id,
            )
            for member in group.members
        ],
    )


def _group_page_response(page: ReturnDedupGroupPage) -> ReturnDedupGroupPageResponse:
    return ReturnDedupGroupPageResponse(
        dedup_publication_revision=page.dedup_publication_revision,
        snapshot_id=page.snapshot_id,
        page=page.page,
        page_size=page.page_size,
        total_items=page.total_items,
        groups=[_group_response(group) for group in page.groups],
    )


def _staging_response(job: object) -> ReturnDedupStagingResponse:
    from app.catalog.return_dedup_repository import ReturnDedupStagingJob

    if not isinstance(job, ReturnDedupStagingJob):
        raise TypeError("return dedup staging result is invalid")
    return ReturnDedupStagingResponse(
        job_id=job.job_id,
        status=job.status,
        job_revision=job.job_revision,
        proposed_set_digest=job.proposed_set_digest.hex(),
        failure_reason=job.failure_reason,
        retry_allowed=job.retry_allowed,
        next_job_revision=job.job_revision,
        result_snapshot_id=job.result_snapshot_id,
        command_url=f"/api/publications/commands/{job.operation_token}",
        status_url=f"/api/publications/return-dedup-staging/{job.job_id}",
    )


def _return_dedup_error(error: ReturnDedupError) -> ApiError:
    if isinstance(error, ReturnDedupPermissionDenied):
        return ApiError(403, error.code, "Permission to stage return dedup was denied.")
    if isinstance(error, ReturnDedupNotFound):
        return ApiError(404, error.code, "The return dedup staging job was not found.")
    if isinstance(error, ReturnDedupIdempotencyConflict):
        return ApiError(409, error.code, "The operation token is already in use.")
    if isinstance(error, ReturnDedupDecisionInvalid):
        return ApiError(422, error.code, "The return dedup decision is invalid.")
    if isinstance(error, ReturnDedupStagingNotReady):
        return ApiError(409, error.code, "The return dedup snapshot is not ready.")
    if isinstance(error, ReturnDedupStagingFailed):
        return ApiError(409, error.code, "The return dedup staging job failed.")
    if isinstance(error, ReturnDedupStagingConflict):
        return ApiError(
            409,
            error.code,
            "The same publication set is already being staged by another operation.",
        )
    if isinstance(error, ReturnDedupStagingSuperseded):
        return ApiError(409, error.code, "The return dedup staging job is stale.")
    if isinstance(
        error,
        (ReturnDedupJobRevisionConflict, ReturnDedupPublicationRevisionConflict),
    ):
        return ApiError(409, error.code, "The return dedup revision changed.")
    return ApiError(503, error.code, "Return dedup is temporarily unavailable.")


class PublicationPointerRequest(_StrictRequest):
    version_id: int | None = Field(default=None, gt=0)
    published_at: datetime | None = None

    def to_domain(self) -> PublicationPointerExpectation:
        return PublicationPointerExpectation(
            version_id=self.version_id,
            published_at=self.published_at,
        )


class DraftPointerRequest(_StrictRequest):
    version_id: int = Field(gt=0)
    status: Literal["draft", "ready_for_publish"]
    data_revision: int = Field(ge=0)
    review_revision: int = Field(ge=0)
    pointed_at: datetime

    def to_domain(self) -> DraftPointerExpectation:
        return DraftPointerExpectation(
            version_id=self.version_id,
            status=self.status,
            data_revision=self.data_revision,
            review_revision=self.review_revision,
            pointed_at=self.pointed_at,
        )


class ValidationExpectationRequest(_StrictRequest):
    run_id: int = Field(gt=0)
    version_id: int = Field(gt=0)
    data_revision: int = Field(ge=0)
    ruleset_version: str = Field(min_length=1, max_length=255)
    data_digest: str = Field(pattern=r"^[0-9a-fA-F]{64}$")

    def to_domain(self) -> ValidationExpectation:
        return ValidationExpectation(
            run_id=self.run_id,
            version_id=self.version_id,
            data_revision=self.data_revision,
            ruleset_version=self.ruleset_version,
            data_digest=bytes.fromhex(self.data_digest),
        )


class ConfirmationTotalRequest(_StrictRequest):
    field_name: str = Field(min_length=1, max_length=255)
    value: str = Field(min_length=1, max_length=255)


class PublicationConfirmationRequest(_StrictRequest):
    confirmed_report_date: date
    report_type: Literal["business_report", "return_report"]
    row_count: int = Field(ge=0)
    totals: list[ConfirmationTotalRequest] = Field(default_factory=list)

    def to_domain(self) -> PublicationConfirmation:
        return PublicationConfirmation(
            confirmed_report_date=self.confirmed_report_date,
            report_type=self.report_type,
            row_count=self.row_count,
            totals=tuple((item.field_name, item.value) for item in self.totals),
        )


class PublishRequest(_StrictRequest):
    expected_draft: DraftPointerRequest
    expected_publication: PublicationPointerRequest
    validation: ValidationExpectationRequest
    confirmation: PublicationConfirmationRequest
    reason: str = Field(min_length=1, max_length=1000)


class CreateRevisionRequest(_StrictRequest):
    expected_publication: PublicationPointerRequest
    reason: str = Field(min_length=1, max_length=1000)


class RollbackRequest(_StrictRequest):
    expected_publication: PublicationPointerRequest
    target_version_id: int = Field(gt=0)
    reason: str = Field(min_length=1, max_length=1000)


class EmptyMoveTargetRequest(_StrictRequest):
    target_kind: Literal["empty"]
    dataset_id: None = None


class PublishedMoveTargetRequest(_StrictRequest):
    target_kind: Literal["published"]
    dataset_id: int = Field(gt=0)
    publication: PublicationPointerRequest
    strategy: Literal["merge", "replace"]


class ActiveDraftMoveTargetRequest(_StrictRequest):
    target_kind: Literal["active_draft"]
    dataset_id: int = Field(gt=0)
    draft: DraftPointerRequest
    publication: PublicationPointerRequest
    action: Literal["merge", "cancel", "force_rebuild"]
    rebuild_strategy: Literal["merge", "replace"] | None = None


type MoveTargetRequest = Annotated[
    EmptyMoveTargetRequest | PublishedMoveTargetRequest | ActiveDraftMoveTargetRequest,
    Field(discriminator="target_kind"),
]


class CreatePublishedMoveRequest(_StrictRequest):
    source_dataset_id: int = Field(gt=0)
    expected_source_publication: PublicationPointerRequest
    target_report_date: date
    target: MoveTargetRequest
    merge_decisions: list[MergeDecisionRequest] = Field(default_factory=list)
    reason: str = Field(min_length=1, max_length=1000)


class FinalizePublishedMoveRequest(_StrictRequest):
    source_dataset_id: int = Field(gt=0)
    expected_source_publication: PublicationPointerRequest
    target_dataset_id: int = Field(gt=0)
    expected_target_draft: DraftPointerRequest
    expected_target_publication: PublicationPointerRequest
    validation: ValidationExpectationRequest
    confirmation: PublicationConfirmationRequest
    reason: str = Field(min_length=1, max_length=1000)


class UndoPublishedMoveRequest(_StrictRequest):
    source_dataset_id: int = Field(gt=0)
    expected_source_publication: PublicationPointerRequest
    restore_source_version_id: int = Field(gt=0)
    target_dataset_id: int = Field(gt=0)
    expected_target_publication: PublicationPointerRequest
    restore_target_version_id: int | None = Field(default=None, gt=0)
    reason: str = Field(min_length=1, max_length=1000)


class DraftCommandResponse(BaseModel):
    operation_token: UUID
    result_kind: Literal[
        "revision_created",
        "published_move_revision_created",
        "published_move_revision_cancelled",
    ]
    dataset_id: int
    version_id: int
    version_no: int
    status: Literal["draft", "cancelled"]
    data_revision: int
    review_revision: int
    source_dataset_id: int | None
    source_version_id: int | None
    completed_at: datetime

    @classmethod
    def from_domain(cls, result: DraftCommandResult) -> DraftCommandResponse:
        return cls(
            operation_token=result.operation_token,
            result_kind=result.result_kind,
            dataset_id=result.dataset_id,
            version_id=result.version_id,
            version_no=result.version_no,
            status=result.status,
            data_revision=result.data_revision,
            review_revision=result.review_revision,
            source_dataset_id=result.source_dataset_id,
            source_version_id=result.source_version_id,
            completed_at=result.completed_at,
        )


class PublicationTransitionResponse(BaseModel):
    event_id: int
    sequence_number: int
    event_type: Literal[
        "published",
        "replaced",
        "rolled_back",
        "moved_out",
        "moved_in",
        "move_reversed",
    ]
    dataset_id: int
    peer_dataset_id: int | None
    previous_version_id: int | None
    next_version_id: int | None

    @classmethod
    def from_domain(
        cls,
        transition: PublicationTransition,
    ) -> PublicationTransitionResponse:
        return cls(
            event_id=transition.event_id,
            sequence_number=transition.sequence_number,
            event_type=transition.event_type,
            dataset_id=transition.dataset_id,
            peer_dataset_id=transition.peer_dataset_id,
            previous_version_id=transition.previous_version_id,
            next_version_id=transition.next_version_id,
        )


class PublicationCommandResponse(BaseModel):
    operation_token: UUID
    command_id: int
    command_type: Literal["publish", "rollback", "move", "reverse_move"]
    transitions: list[PublicationTransitionResponse]
    completed_at: datetime

    @classmethod
    def from_domain(
        cls,
        result: PublicationCommandResult,
    ) -> PublicationCommandResponse:
        return cls(
            operation_token=result.operation_token,
            command_id=result.command_id,
            command_type=result.command_type,
            transitions=[
                PublicationTransitionResponse.from_domain(item)
                for item in result.transitions
            ],
            completed_at=result.completed_at,
        )


class PublicationPointerSnapshotResponse(BaseModel):
    version_id: int | None
    published_at: datetime | None


class UndoablePublishedMoveResponse(BaseModel):
    move_command_id: int
    source_dataset_id: int
    source_report_date: date
    restore_source_version_id: int
    source_current_publication: PublicationPointerSnapshotResponse
    target_dataset_id: int
    target_report_date: date
    restore_target_version_id: int | None
    target_current_publication: PublicationPointerSnapshotResponse
    moved_target_version_id: int
    completed_at: datetime
    report_type: Literal["business_report", "return_report"]

    @classmethod
    def from_domain(
        cls,
        move: UndoablePublishedMove,
    ) -> UndoablePublishedMoveResponse:
        return cls(
            move_command_id=move.move_command_id,
            source_dataset_id=move.source_dataset_id,
            source_report_date=move.source_report_date,
            restore_source_version_id=move.restore_source_version_id,
            source_current_publication=PublicationPointerSnapshotResponse(
                version_id=move.source_current_publication.version_id,
                published_at=move.source_current_publication.published_at,
            ),
            target_dataset_id=move.target_dataset_id,
            target_report_date=move.target_report_date,
            restore_target_version_id=move.restore_target_version_id,
            target_current_publication=PublicationPointerSnapshotResponse(
                version_id=move.target_current_publication.version_id,
                published_at=move.target_current_publication.published_at,
            ),
            moved_target_version_id=move.moved_target_version_id,
            completed_at=move.completed_at,
            report_type=move.report_type,
        )


def _service(engine: Engine) -> PublicationService:
    return PublicationService(repository=MySqlPublicationRepository(engine))


def _publication_error(error: PublicationError | PublicationIneligible) -> ApiError:
    if isinstance(error, PublicationPermissionDenied):
        return ApiError(
            403,
            "publication_forbidden",
            "Permission to perform this publication command was denied.",
        )
    if isinstance(error, PublicationTransactionBusy):
        return ApiError(
            503,
            "publication_busy",
            "Publication is temporarily busy.",
        )
    if isinstance(error, PublicationCommitOutcomeUnknown):
        return ApiError(
            503,
            "publication_outcome_unknown",
            "The publication command outcome could not be confirmed.",
        )
    if isinstance(error, PublicationIneligible):
        return ApiError(
            409,
            "publication_ineligible",
            "The draft no longer satisfies publication requirements.",
        )
    if isinstance(
        error,
        (
            PublicationPointerConflict,
            PublicationStateConflict,
            PublicationOperationConflict,
        ),
    ):
        return ApiError(
            409,
            "publication_conflict",
            "The publication command conflicts with current state.",
        )
    return ApiError(
        503,
        "publication_unavailable",
        "The publication command could not be completed.",
    )


def _run_draft_command(
    command_call: Callable[[], DraftCommandResult],
) -> DraftCommandResponse:
    try:
        return DraftCommandResponse.from_domain(command_call())
    except ValueError as error:
        raise ApiError(
            422,
            "invalid_publication_command",
            "The publication command is invalid.",
        ) from error
    except (PublicationError, PublicationIneligible) as error:
        raise _publication_error(error) from error


def _run_publication_command(
    command_call: Callable[[], PublicationCommandResult],
) -> PublicationCommandResponse:
    try:
        return PublicationCommandResponse.from_domain(command_call())
    except ValueError as error:
        raise ApiError(
            422,
            "invalid_publication_command",
            "The publication command is invalid.",
        ) from error
    except ReturnDedupError as error:
        raise _return_dedup_error(error) from error
    except (PublicationError, PublicationIneligible) as error:
        raise _publication_error(error) from error


def _move_target(
    payload: MoveTargetRequest,
) -> EmptyMoveTarget | PublishedMoveTarget | ActiveDraftMoveTarget:
    if isinstance(payload, EmptyMoveTargetRequest):
        return EmptyMoveTarget()
    if isinstance(payload, PublishedMoveTargetRequest):
        return PublishedMoveTarget(
            dataset_id=payload.dataset_id,
            publication=payload.publication.to_domain(),
            strategy=payload.strategy,
        )
    return ActiveDraftMoveTarget(
        dataset_id=payload.dataset_id,
        draft=payload.draft.to_domain(),
        publication=payload.publication.to_domain(),
        action=payload.action,
        rebuild_strategy=payload.rebuild_strategy,
    )


@router.get(
    "/api/catalog/return-dedup/groups",
    response_model=ReturnDedupGroupPageResponse,
)
def list_return_dedup_groups(
    _principal: _ManagerRead,
    context: _SiteContext,
    engine: _Engine,
    status: Annotated[Literal["unresolved", "resolved", "all"], Query()] = "unresolved",
    page: Annotated[int, Query(ge=1)] = 1,
    page_size: Annotated[int, Query(ge=1, le=100)] = 50,
) -> ReturnDedupGroupPageResponse:
    try:
        result = MySqlReturnDedupRepository(engine).list_groups(
            context,
            status=status,
            page=page,
            page_size=page_size,
        )
    except (ValueError, ReturnDedupError) as error:
        if isinstance(error, ReturnDedupError):
            raise _return_dedup_error(error) from error
        raise ApiError(
            422,
            "return_dedup_parameter_invalid",
            "The return dedup group query is invalid.",
        ) from error
    return _group_page_response(result)


@router.post(
    "/api/catalog/return-dedup/groups/{group_id}/decision",
    response_model=ReturnDedupDecisionResponse,
)
def decide_return_dedup_group(
    group_id: Annotated[str, Path(pattern=r"^[0-9a-f]{64}$")],
    payload: ReturnDedupDecisionRequest,
    _principal: _Manager,
    context: _SiteContext,
    engine: _Engine,
    operation_token: _IdempotencyKey,
) -> ReturnDedupDecisionResponse:
    if payload.operation_token != operation_token:
        raise ApiError(
            422,
            "idempotency_key_mismatch",
            "Idempotency-Key must match operation_token.",
        )
    try:
        result = MySqlReturnDedupRepository(engine).decide_group(
            context,
            DecideReturnDedupGroup(
                operation_token=payload.operation_token,
                group_id=group_id,
                expected_dedup_publication_revision=(
                    payload.expected_dedup_publication_revision
                ),
                expected_group_revision=payload.expected_group_revision,
                decision=payload.decision,
                canonical_member_id=payload.canonical_member_id,
                reason=payload.reason,
            ),
            occurred_at=datetime.now(UTC),
        )
    except (ValueError, ReturnDedupError) as error:
        if isinstance(error, ReturnDedupError):
            raise _return_dedup_error(error) from error
        raise ApiError(
            422,
            "return_dedup_decision_invalid",
            "The return dedup decision is invalid.",
        ) from error
    return ReturnDedupDecisionResponse(
        group_id=result.group_id,
        group_revision=result.group_revision,
        dedup_publication_revision=result.dedup_publication_revision,
        snapshot_id=result.snapshot_id,
        decision=result.decision,
        canonical_member_id=result.canonical_member_id,
    )


@router.get(
    "/api/publications/return-initialization",
    response_model=ReturnInitializationPreview,
)
def preview_return_initialization(
    _principal: _ManagerRead, context: _SiteContext, engine: _Engine
) -> object:
    try:
        return MySqlReturnDedupRepository(engine).initialization_preview(context)
    except ReturnDedupError as error:
        raise _return_dedup_error(error) from error


@router.post(
    "/api/publications/return-initialization",
    response_model=ReturnDedupStagingResponse,
    status_code=202,
)
def initialize_returns(
    payload: ReturnInitializationRequest,
    _principal: _Manager,
    context: _SiteContext,
    engine: _Engine,
    operation_token: _IdempotencyKey,
) -> ReturnDedupStagingResponse:
    if payload.operation_token != operation_token:
        raise ApiError(
            422,
            "idempotency_key_mismatch",
            "Idempotency-Key must match operation_token.",
        )
    try:
        command = CreateReturnDedupStaging(
            operation_token=operation_token,
            dataset_id=payload.dataset_id,
            proposed_version_id=payload.proposed_version_id,
            expected_publication_revision=payload.expected_publication_revision,
            expected_dedup_publication_revision=payload.expected_dedup_publication_revision,
            initialization_revision=payload.initialization_revision,
            expected_set_digest=bytes.fromhex(payload.expected_set_digest),
        )
        return _staging_response(
            MySqlReturnDedupRepository(engine).create_staging(
                context, command, occurred_at=datetime.now(UTC)
            )
        )
    except ReturnDedupError as error:
        raise _return_dedup_error(error) from error


@router.post(
    "/api/publications/return-dedup-staging",
    response_model=ReturnDedupStagingResponse,
    status_code=202,
)
def create_return_dedup_staging(
    payload: ReturnDedupStagingRequest,
    _principal: _Manager,
    context: _SiteContext,
    engine: _Engine,
    operation_token: _IdempotencyKey,
) -> ReturnDedupStagingResponse:
    if payload.operation_token != operation_token:
        raise ApiError(
            422,
            "idempotency_key_mismatch",
            "Idempotency-Key must match operation_token.",
        )
    try:
        job = MySqlReturnDedupRepository(engine).create_staging(
            context,
            CreateReturnDedupStaging(
                operation_token=payload.operation_token,
                dataset_id=payload.dataset_id,
                proposed_version_id=payload.proposed_version_id,
                expected_publication_revision=(payload.expected_publication_revision),
                expected_dedup_publication_revision=(
                    payload.expected_dedup_publication_revision
                ),
            ),
            occurred_at=datetime.now(UTC),
        )
    except (ValueError, ReturnDedupError) as error:
        if isinstance(error, ReturnDedupError):
            raise _return_dedup_error(error) from error
        raise ApiError(
            422,
            "invalid_return_dedup_staging",
            "The return dedup staging request is invalid.",
        ) from error
    return _staging_response(job)


@router.get(
    "/api/publications/return-dedup-staging/{job_id}",
    response_model=ReturnDedupStagingResponse,
)
def get_return_dedup_staging(
    job_id: int,
    _principal: _ManagerRead,
    context: _SiteContext,
    engine: _Engine,
) -> ReturnDedupStagingResponse:
    try:
        return _staging_response(
            MySqlReturnDedupRepository(engine).get_job(context, job_id)
        )
    except ReturnDedupError as error:
        raise _return_dedup_error(error) from error


@router.post(
    "/api/publications/return-dedup-staging/{job_id}/retry",
    response_model=ReturnDedupStagingResponse,
)
def retry_return_dedup_staging(
    job_id: int,
    payload: ReturnDedupRetryRequest,
    _principal: _Manager,
    context: _SiteContext,
    engine: _Engine,
    operation_token: _IdempotencyKey,
) -> ReturnDedupStagingResponse:
    if payload.operation_token != operation_token:
        raise ApiError(
            422,
            "idempotency_key_mismatch",
            "Idempotency-Key must match operation_token.",
        )
    try:
        job = MySqlReturnDedupRepository(engine).retry(
            context,
            job_id,
            RetryReturnDedupStaging(
                operation_token=payload.operation_token,
                expected_job_revision=payload.expected_job_revision,
                proposed_set_digest=bytes.fromhex(payload.proposed_set_digest),
            ),
            occurred_at=datetime.now(UTC),
        )
    except (ValueError, ReturnDedupError) as error:
        if isinstance(error, ReturnDedupError):
            raise _return_dedup_error(error) from error
        raise ApiError(
            422,
            "invalid_return_dedup_retry",
            "The return dedup retry request is invalid.",
        ) from error
    return _staging_response(job)


@router.post(
    "/api/datasets/{dataset_id}/publish",
    response_model=PublicationCommandResponse,
)
def publish_dataset(
    dataset_id: int,
    payload: PublishRequest,
    principal: _Manager,
    engine: _Engine,
    operation_token: _IdempotencyKey,
) -> PublicationCommandResponse:
    return _run_publication_command(
        lambda: _service(engine).publish(
            PublishCommand(
                dataset_id=dataset_id,
                expected_draft=payload.expected_draft.to_domain(),
                expected_publication=payload.expected_publication.to_domain(),
                validation=payload.validation.to_domain(),
                confirmation=payload.confirmation.to_domain(),
                actor_user_id=principal.user_id,
                operation_token=operation_token,
                reason=payload.reason,
            )
        )
    )


@router.post(
    "/api/datasets/{dataset_id}/revisions",
    response_model=DraftCommandResponse,
    status_code=201,
)
def create_revision(
    dataset_id: int,
    payload: CreateRevisionRequest,
    principal: _Manager,
    engine: _Engine,
    operation_token: _IdempotencyKey,
) -> DraftCommandResponse:
    return _run_draft_command(
        lambda: _service(engine).create_revision(
            CreateRevisionCommand(
                dataset_id=dataset_id,
                expected_publication=payload.expected_publication.to_domain(),
                actor_user_id=principal.user_id,
                operation_token=operation_token,
                reason=payload.reason,
            )
        )
    )


@router.post(
    "/api/admin/datasets/{dataset_id}/rollback",
    response_model=PublicationCommandResponse,
)
def rollback_dataset(
    dataset_id: int,
    payload: RollbackRequest,
    principal: _Administrator,
    engine: _Engine,
    operation_token: _IdempotencyKey,
) -> PublicationCommandResponse:
    return _run_publication_command(
        lambda: _service(engine).rollback(
            RollbackCommand(
                dataset_id=dataset_id,
                expected_publication=payload.expected_publication.to_domain(),
                target_version_id=payload.target_version_id,
                actor_user_id=principal.user_id,
                operation_token=operation_token,
                reason=payload.reason,
            )
        )
    )


@router.post(
    "/api/admin/versions/{version_id}/move-date",
    response_model=DraftCommandResponse,
    status_code=201,
)
def create_published_move_revision(
    version_id: int,
    payload: CreatePublishedMoveRequest,
    principal: _Administrator,
    engine: _Engine,
    operation_token: _IdempotencyKey,
) -> DraftCommandResponse:
    if payload.expected_source_publication.version_id != version_id:
        raise ApiError(
            422,
            "publication_identity_mismatch",
            "The path and expected publication identify different versions.",
        )
    return _run_draft_command(
        lambda: _service(engine).create_published_move_revision(
            CreatePublishedMoveRevisionCommand(
                source_dataset_id=payload.source_dataset_id,
                expected_source_publication=(
                    payload.expected_source_publication.to_domain()
                ),
                target_report_date=payload.target_report_date,
                target=_move_target(payload.target),
                merge_decisions=tuple(
                    decision.to_domain() for decision in payload.merge_decisions
                ),
                actor_user_id=principal.user_id,
                operation_token=operation_token,
                reason=payload.reason,
            )
        )
    )


@router.get(
    "/api/admin/published-moves/undoable",
    response_model=list[UndoablePublishedMoveResponse],
)
def list_undoable_published_moves(
    _principal: _AdministratorRead,
    database_session: _DatabaseSession,
) -> list[UndoablePublishedMoveResponse]:
    """Return complete recovery snapshots only while reversal remains safe."""

    moves = UndoablePublishedMoveQueryService(database_session).list_moves()
    return [UndoablePublishedMoveResponse.from_domain(move) for move in moves]


@router.post(
    "/api/admin/published-moves/{move_revision_operation_token}/finalize",
    response_model=PublicationCommandResponse,
)
def finalize_published_move(
    move_revision_operation_token: UUID,
    payload: FinalizePublishedMoveRequest,
    principal: _Administrator,
    engine: _Engine,
    operation_token: _IdempotencyKey,
) -> PublicationCommandResponse:
    return _run_publication_command(
        lambda: _service(engine).finalize_published_move(
            FinalizePublishedMoveCommand(
                move_revision_operation_token=move_revision_operation_token,
                source_dataset_id=payload.source_dataset_id,
                expected_source_publication=(
                    payload.expected_source_publication.to_domain()
                ),
                target_dataset_id=payload.target_dataset_id,
                expected_target_draft=payload.expected_target_draft.to_domain(),
                expected_target_publication=(
                    payload.expected_target_publication.to_domain()
                ),
                validation=payload.validation.to_domain(),
                confirmation=payload.confirmation.to_domain(),
                actor_user_id=principal.user_id,
                operation_token=operation_token,
                reason=payload.reason,
            )
        )
    )


@router.post(
    "/api/admin/published-moves/{move_command_id}/undo",
    response_model=PublicationCommandResponse,
)
def undo_published_move(
    move_command_id: int,
    payload: UndoPublishedMoveRequest,
    principal: _Administrator,
    engine: _Engine,
    operation_token: _IdempotencyKey,
) -> PublicationCommandResponse:
    return _run_publication_command(
        lambda: _service(engine).undo_published_move(
            UndoPublishedMoveCommand(
                move_command_id=move_command_id,
                source_dataset_id=payload.source_dataset_id,
                expected_source_publication=(
                    payload.expected_source_publication.to_domain()
                ),
                restore_source_version_id=payload.restore_source_version_id,
                target_dataset_id=payload.target_dataset_id,
                expected_target_publication=(
                    payload.expected_target_publication.to_domain()
                ),
                restore_target_version_id=payload.restore_target_version_id,
                actor_user_id=principal.user_id,
                operation_token=operation_token,
                reason=payload.reason,
            )
        )
    )
