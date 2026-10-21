"""MySQL adapter for atomic ordinary publication and rollback commands."""

from __future__ import annotations

import hashlib
import hmac
import json
import random
import time
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, Literal, cast
from uuid import UUID

import sqlalchemy as sa
from sqlalchemy.engine import Connection, Engine, RowMapping
from sqlalchemy.exc import DBAPIError, IntegrityError, SQLAlchemyError

from app.datasets.merge import SnapshotMember
from app.datasets.repository import (
    MySqlDatasetRepository,
    _Actor,
    _Dataset,
    _MemberPlan,
    _Version,
)
from app.datasets.types import (
    ActiveDraftConflict,
    DatasetError,
    DatasetPermissionDenied,
    MergeDecision,
)

from .commands import (
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
from .coordination import (
    MySqlTransactionRetryPolicy,
    advance_return_publication_guard,
    lock_return_publication_guard,
    ordered_dataset_ids,
)
from .results import (
    DraftCommandResult,
    PublicationCommandResult,
    PublicationTransition,
    validate_publication_event_shape,
)
from .rules import (
    EligibilityFailure,
    PublicationEligibilityFacts,
    PublicationIneligible,
    require_publication_eligible,
)

type _OperationKind = Literal[
    "publish",
    "replace",
    "rollback",
    "move",
    "reverse_move",
]
type _ResultKind = Literal[
    "published",
    "replaced",
    "rolled_back",
    "moved",
    "move_reversed",
]
type _EventKind = Literal[
    "published",
    "replaced",
    "rolled_back",
    "moved_out",
    "moved_in",
    "move_reversed",
]
type _CommandType = Literal["publish", "rollback", "move", "reverse_move"]

_RESULT_KIND_BY_OPERATION: dict[_OperationKind, _ResultKind] = {
    "publish": "published",
    "replace": "replaced",
    "rollback": "rolled_back",
    "move": "moved",
    "reverse_move": "move_reversed",
}
_COMMAND_TYPE_BY_OPERATION: dict[_OperationKind, _CommandType] = {
    "publish": "publish",
    "replace": "publish",
    "rollback": "rollback",
    "move": "move",
    "reverse_move": "reverse_move",
}
_RETRY_BASE_DELAY_SECONDS = 0.005
_RETRY_MAX_DELAY_SECONDS = 0.04


class PublicationError(RuntimeError):
    """Base class for expected publication persistence failures."""


class PublicationPermissionDenied(PublicationError):
    """The actor lacks the role required for the publication command."""


class PublicationPointerConflict(PublicationError):
    """A draft or publication pointer differs from the caller snapshot."""


class PublicationStateConflict(PublicationError):
    """A locked dataset version is not eligible for the requested transition."""


class PublicationOperationConflict(PublicationError):
    """An operation token is already bound to another command identity."""


class PublicationCommitOutcomeUnknown(PublicationError):
    """Commit acknowledgement was lost without a recoverable frozen result."""


class PublicationTransactionBusy(PublicationError):
    """Required MySQL locks stayed unavailable after four total attempts."""


@dataclass(frozen=True, slots=True)
class _DraftPointer:
    version_id: int
    status: str
    pointed_at: datetime


@dataclass(frozen=True, slots=True)
class _PublicationPointer:
    version_id: int
    status: str
    published_at: datetime


@dataclass(frozen=True, slots=True)
class _ValidationRun:
    run_id: int
    version_id: int
    run_type: str
    data_revision: int
    ruleset_version: str
    status: str
    result: str
    data_digest: bytes


@dataclass(frozen=True, slots=True)
class _ReviewIssue:
    issue_id: int
    severity: str
    requires_note: bool


@dataclass(frozen=True, slots=True)
class _IssueReview:
    issue_id: int
    sequence_number: int
    event_type: str
    comment: str | None


def _mysql_datetime(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("database timestamps must be timezone-aware")
    return value.astimezone(UTC).replace(tzinfo=None)


def _utc_datetime(value: object, label: str) -> datetime:
    if not isinstance(value, datetime):
        raise PublicationError(f"{label} is not a database timestamp")
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    if value.utcoffset() is None:
        raise PublicationError(f"{label} is not a valid database timestamp")
    return value.astimezone(UTC)


def _as_bytes(value: object, *, length: int, label: str) -> bytes:
    if not isinstance(value, (bytes, bytearray, memoryview)):
        raise PublicationError(f"{label} is not binary")
    result = bytes(value)
    if len(result) != length:
        raise PublicationError(f"{label} has an invalid length")
    return result


def _canonical_json(value: object) -> str:
    return json.dumps(
        value,
        ensure_ascii=True,
        separators=(",", ":"),
        sort_keys=True,
    )


def _normalised_json(value: object, label: str) -> str:
    candidate = value
    if isinstance(candidate, (bytes, bytearray, memoryview)):
        try:
            candidate = bytes(candidate).decode("utf-8")
        except UnicodeDecodeError as error:
            raise PublicationError(f"{label} is not valid JSON") from error
    if isinstance(candidate, str):
        try:
            candidate = json.loads(candidate)
        except json.JSONDecodeError as error:
            raise PublicationError(f"{label} is not valid JSON") from error
    try:
        return _canonical_json(candidate)
    except (TypeError, ValueError) as error:
        raise PublicationError(f"{label} is not valid JSON") from error


def _confirmation_payload(
    validation: ValidationExpectation,
    confirmation: PublicationConfirmation,
) -> dict[str, object]:
    return {
        "validation_run_id": validation.run_id,
        "validation_data_digest": validation.data_digest.hex(),
        "ruleset_version": validation.ruleset_version,
        "confirmed_report_date": confirmation.confirmed_report_date.isoformat(),
        "confirmed_report_type": confirmation.report_type,
        "confirmed_row_count": confirmation.row_count,
        # This must be byte-for-byte compatible with the frozen confirmation
        # snapshot recorded when review marks the version ready.
        "confirmed_totals": {name: value for name, value in confirmation.totals},
    }


def _confirmation_snapshot(
    validation: ValidationExpectation,
    confirmation: PublicationConfirmation,
) -> tuple[str, bytes]:
    payload = _canonical_json(_confirmation_payload(validation, confirmation))
    return payload, hashlib.sha256(payload.encode("ascii")).digest()


def _mysql_error_code(error: DBAPIError) -> int | None:
    arguments = getattr(error.orig, "args", ())
    if arguments and isinstance(arguments[0], int):
        return arguments[0]
    return None


def _wait_for_transaction_retry(retry_number: int) -> None:
    if retry_number < 1:
        raise ValueError("retry_number must be positive")
    ceiling = min(
        _RETRY_BASE_DELAY_SECONDS * (2 ** (retry_number - 1)),
        _RETRY_MAX_DELAY_SECONDS,
    )
    time.sleep(random.uniform(ceiling / 2, ceiling))


class _PublishedRevisionCloner:
    """Clone one locked published version into a new immutable draft snapshot."""

    def __init__(self, repository: MySqlDatasetRepository) -> None:
        self._repository = repository

    def clone(
        self,
        connection: Connection,
        *,
        dataset: _Dataset,
        parent: _Version,
        actor_user_id: int,
        occurred_at: datetime,
    ) -> _Version:
        self._repository._lock_input_batches_for_versions(
            connection,
            (parent.version_id,),
        )
        parent_rows = self._repository._version_rows(connection, parent)
        inherited_inputs = self._repository._version_inputs(
            connection,
            parent.version_id,
        )
        plan = self._repository._snapshot_plan(
            report_type=dataset.report_type,
            ruleset_version=parent.ruleset_version,
            members=(
                _MemberPlan(
                    member=SnapshotMember(
                        "dataset_version",
                        "base",
                        parent.version_id,
                    ),
                    rows=parent_rows,
                ),
            ),
            decisions=(),
            preserve_source_logical_ids=True,
        )
        return self._repository._create_draft_version(
            connection,
            dataset=dataset,
            ruleset_version=parent.ruleset_version,
            snapshot_kind="revision",
            plan=plan,
            actor_user_id=actor_user_id,
            occurred_at=occurred_at,
            parents=((parent, "base"),),
            input_batches=inherited_inputs,
        )


class _PublishedMoveRevisionCloner:
    """Build a reviewed target draft without mutating either publication."""

    def __init__(self, repository: MySqlDatasetRepository) -> None:
        self._repository = repository

    def clone(
        self,
        connection: Connection,
        *,
        dataset: _Dataset,
        source: _Version,
        target: _Version | None,
        decisions: tuple[MergeDecision, ...],
        actor_user_id: int,
        occurred_at: datetime,
    ) -> _Version:
        version_ids = [source.version_id]
        if target is not None:
            version_ids.append(target.version_id)
        self._repository._lock_input_batches_for_versions(connection, version_ids)

        members: list[_MemberPlan] = []
        parents: list[tuple[_Version, str]] = []
        input_groups: list[tuple[tuple[int, str], ...]] = []
        if target is not None:
            members.append(
                _MemberPlan(
                    member=SnapshotMember(
                        "dataset_version",
                        "merge_target",
                        target.version_id,
                    ),
                    rows=self._repository._version_rows(connection, target),
                )
            )
            parents.append((target, "merge_target"))
            input_groups.append(
                self._repository._version_inputs(connection, target.version_id)
            )

        members.append(
            _MemberPlan(
                member=SnapshotMember(
                    "dataset_version",
                    "moved_source",
                    source.version_id,
                ),
                rows=self._repository._version_rows(connection, source),
            )
        )
        parents.append((source, "moved_source"))
        input_groups.append(
            tuple(
                (batch_id, "moved_source")
                for batch_id, _role in self._repository._version_inputs(
                    connection,
                    source.version_id,
                )
            )
        )
        plan = self._repository._snapshot_plan(
            report_type=source.report_type,
            ruleset_version=source.ruleset_version,
            members=members,
            decisions=decisions,
            preserve_source_logical_ids=True,
        )
        return self._repository._create_draft_version(
            connection,
            dataset=dataset,
            ruleset_version=source.ruleset_version,
            snapshot_kind="published_move",
            plan=plan,
            actor_user_id=actor_user_id,
            occurred_at=occurred_at,
            parents=parents,
            input_batches=self._repository._merge_inputs(*input_groups),
        )


class MySqlPublicationRepository(MySqlDatasetRepository):
    """Own one complete MySQL transaction per publish or rollback command."""

    def __init__(
        self,
        engine: Engine,
        *,
        retry_waiter: Callable[[int], None] | None = None,
    ) -> None:
        super().__init__(engine, retry_waiter=retry_waiter)
        self._publication_retry_waiter = retry_waiter or _wait_for_transaction_retry
        self._retry_policy = MySqlTransactionRetryPolicy()
        self._revision_cloner = _PublishedRevisionCloner(self)
        self._published_move_cloner = _PublishedMoveRevisionCloner(self)

    def create_revision(
        self,
        command: CreateRevisionCommand,
        *,
        occurred_at: datetime,
    ) -> DraftCommandResult:
        return self._execute_revision_command(command, occurred_at=occurred_at)

    def publish(
        self,
        command: PublishCommand,
        *,
        occurred_at: datetime,
    ) -> PublicationCommandResult:
        operation_kind: Literal["publish", "replace"] = (
            "replace" if command.expected_publication.is_present else "publish"
        )
        return self._execute_command(
            operation_kind=operation_kind,
            operation_token=command.operation_token,
            operation_digest=command.operation_digest,
            actor_user_id=command.actor_user_id,
            occurred_at=occurred_at,
            request_payload={
                "dataset_id": command.dataset_id,
                "draft_version_id": command.expected_draft.version_id,
                "validation_run_id": command.validation.run_id,
            },
            work=lambda connection, actor, timestamp, command_id: self._publish(
                connection,
                actor=actor,
                command=command,
                occurred_at=timestamp,
                command_id=command_id,
                operation_kind=operation_kind,
            ),
        )

    def rollback(
        self,
        command: RollbackCommand,
        *,
        occurred_at: datetime,
    ) -> PublicationCommandResult:
        return self._execute_command(
            operation_kind="rollback",
            operation_token=command.operation_token,
            operation_digest=command.operation_digest,
            actor_user_id=command.actor_user_id,
            occurred_at=occurred_at,
            request_payload={
                "dataset_id": command.dataset_id,
                "target_version_id": command.target_version_id,
            },
            work=lambda connection, actor, timestamp, command_id: self._rollback(
                connection,
                actor=actor,
                command=command,
                occurred_at=timestamp,
                command_id=command_id,
            ),
        )

    def create_published_move_revision(
        self,
        command: CreatePublishedMoveRevisionCommand,
        *,
        occurred_at: datetime,
    ) -> DraftCommandResult:
        return self._execute_published_move_revision_command(
            command,
            occurred_at=occurred_at,
        )

    def finalize_published_move(
        self,
        command: FinalizePublishedMoveCommand,
        *,
        occurred_at: datetime,
    ) -> PublicationCommandResult:
        return self._execute_command(
            operation_kind="move",
            operation_token=command.operation_token,
            operation_digest=command.operation_digest,
            actor_user_id=command.actor_user_id,
            occurred_at=occurred_at,
            request_payload={
                "source_dataset_id": command.source_dataset_id,
                "target_dataset_id": command.target_dataset_id,
                "target_draft_version_id": command.expected_target_draft.version_id,
                "move_revision_operation_token": str(
                    command.move_revision_operation_token
                ),
            },
            work=lambda connection, actor, timestamp, command_id: (
                self._finalize_published_move(
                    connection,
                    actor=actor,
                    command=command,
                    occurred_at=timestamp,
                    command_id=command_id,
                )
            ),
        )

    def undo_published_move(
        self,
        command: UndoPublishedMoveCommand,
        *,
        occurred_at: datetime,
    ) -> PublicationCommandResult:
        return self._execute_command(
            operation_kind="reverse_move",
            operation_token=command.operation_token,
            operation_digest=command.operation_digest,
            actor_user_id=command.actor_user_id,
            occurred_at=occurred_at,
            request_payload={
                "move_command_id": command.move_command_id,
                "source_dataset_id": command.source_dataset_id,
                "target_dataset_id": command.target_dataset_id,
            },
            work=lambda connection, actor, timestamp, command_id: (
                self._undo_published_move(
                    connection,
                    actor=actor,
                    command=command,
                    occurred_at=timestamp,
                    command_id=command_id,
                )
            ),
        )

    def _execute_revision_command(
        self,
        command: CreateRevisionCommand,
        *,
        occurred_at: datetime,
    ) -> DraftCommandResult:
        timestamp = _mysql_datetime(occurred_at)

        def recover_known_outcome() -> DraftCommandResult | None:
            try:
                return self._recover_revision_operation(command)
            except PublicationError:
                raise
            except SQLAlchemyError as error:
                raise PublicationError("revision recovery failed") from error

        recovered = recover_known_outcome()
        if recovered is not None:
            return recovered

        failed_attempt = 0
        while True:
            failed_attempt += 1
            try:
                with self._engine.begin() as connection:
                    claimed = self._claim_revision_operation(
                        connection,
                        command=command,
                        registered_at=timestamp,
                    )
                    if claimed is not None:
                        return claimed
                    try:
                        actor = self._load_actor(connection, command.actor_user_id)
                    except DatasetPermissionDenied as error:
                        raise PublicationPermissionDenied(str(error)) from error
                    return self._create_revision(
                        connection,
                        actor=actor,
                        command=command,
                        occurred_at=timestamp,
                    )
            except DBAPIError as error:
                if error.connection_invalidated:
                    try:
                        recovered = self._recover_revision_operation(command)
                    except PublicationOperationConflict:
                        raise
                    except Exception as recovery_error:
                        raise PublicationCommitOutcomeUnknown(
                            "revision commit acknowledgement was lost and "
                            "recovery failed"
                        ) from recovery_error
                    if recovered is not None:
                        return recovered
                    raise PublicationCommitOutcomeUnknown(
                        "revision commit acknowledgement was lost"
                    ) from error
                error_code = _mysql_error_code(error)
                if self._retry_policy.should_retry(error_code, failed_attempt):
                    recovered = recover_known_outcome()
                    if recovered is not None:
                        return recovered
                    self._publication_retry_waiter(failed_attempt)
                    continue
                if error_code in self._retry_policy.retryable_error_codes:
                    raise PublicationTransactionBusy(
                        "revision transaction remained busy after 4 attempts"
                    ) from error
                raise PublicationError("revision transaction failed") from error
            except PublicationError:
                raise
            except DatasetPermissionDenied as error:
                raise PublicationPermissionDenied(str(error)) from error
            except DatasetError as error:
                raise PublicationError("revision transaction failed") from error
            except SQLAlchemyError as error:
                raise PublicationError("revision transaction failed") from error

    def _execute_published_move_revision_command(
        self,
        command: CreatePublishedMoveRevisionCommand,
        *,
        occurred_at: datetime,
    ) -> DraftCommandResult:
        timestamp = _mysql_datetime(occurred_at)

        def recover_known_outcome() -> DraftCommandResult | None:
            try:
                return self._recover_published_move_revision_operation(command)
            except PublicationError:
                raise
            except SQLAlchemyError as error:
                raise PublicationError(
                    "published move revision recovery failed"
                ) from error

        recovered = recover_known_outcome()
        if recovered is not None:
            return recovered

        failed_attempt = 0
        while True:
            failed_attempt += 1
            try:
                with self._engine.begin() as connection:
                    claimed = self._claim_published_move_revision_operation(
                        connection,
                        command=command,
                        registered_at=timestamp,
                    )
                    if claimed is not None:
                        return claimed
                    try:
                        actor = self._load_actor(connection, command.actor_user_id)
                    except DatasetPermissionDenied as error:
                        raise PublicationPermissionDenied(str(error)) from error
                    return self._create_published_move_revision(
                        connection,
                        actor=actor,
                        command=command,
                        occurred_at=timestamp,
                    )
            except DBAPIError as error:
                if error.connection_invalidated:
                    try:
                        recovered = self._recover_published_move_revision_operation(
                            command
                        )
                    except PublicationOperationConflict:
                        raise
                    except Exception as recovery_error:
                        raise PublicationCommitOutcomeUnknown(
                            "published move revision commit acknowledgement was "
                            "lost and recovery failed"
                        ) from recovery_error
                    if recovered is not None:
                        return recovered
                    raise PublicationCommitOutcomeUnknown(
                        "published move revision commit acknowledgement was lost"
                    ) from error
                error_code = _mysql_error_code(error)
                if self._retry_policy.should_retry(error_code, failed_attempt):
                    recovered = recover_known_outcome()
                    if recovered is not None:
                        return recovered
                    self._publication_retry_waiter(failed_attempt)
                    continue
                if error_code in self._retry_policy.retryable_error_codes:
                    raise PublicationTransactionBusy(
                        "published move revision transaction remained busy after "
                        "4 attempts"
                    ) from error
                raise PublicationError(
                    "published move revision transaction failed"
                ) from error
            except PublicationError:
                raise
            except DatasetPermissionDenied as error:
                raise PublicationPermissionDenied(str(error)) from error
            except DatasetError as error:
                raise PublicationError(
                    "published move revision transaction failed"
                ) from error
            except SQLAlchemyError as error:
                raise PublicationError(
                    "published move revision transaction failed"
                ) from error

    def _claim_published_move_revision_operation(
        self,
        connection: Connection,
        *,
        command: CreatePublishedMoveRevisionCommand,
        registered_at: datetime,
    ) -> DraftCommandResult | None:
        savepoint = connection.begin_nested()
        try:
            connection.execute(
                sa.text(
                    """
                    INSERT INTO draft_operation_tokens (
                        operation_token, operation_kind, operation_digest,
                        actor_user_id, registered_at
                    ) VALUES (
                        :operation_token, 'create_published_move_revision',
                        :operation_digest, :actor_user_id, :registered_at
                    )
                    """
                ),
                {
                    "operation_token": command.operation_token.bytes,
                    "operation_digest": command.operation_digest,
                    "actor_user_id": command.actor_user_id,
                    "registered_at": registered_at,
                },
            )
            savepoint.commit()
            return None
        except IntegrityError as error:
            savepoint.rollback()
            if _mysql_error_code(error) != 1062:
                raise
        return self._published_move_revision_result(
            connection,
            command=command,
            require_result=True,
        )

    def _recover_published_move_revision_operation(
        self,
        command: CreatePublishedMoveRevisionCommand,
    ) -> DraftCommandResult | None:
        with self._engine.connect() as connection:
            return self._published_move_revision_result(
                connection,
                command=command,
                require_result=False,
            )

    def _published_move_revision_result(
        self,
        connection: Connection,
        *,
        command: CreatePublishedMoveRevisionCommand,
        require_result: bool,
    ) -> DraftCommandResult | None:
        token_row = (
            connection.execute(
                sa.text(
                    """
                    SELECT operation_kind, operation_digest, actor_user_id
                    FROM draft_operation_tokens
                    WHERE operation_token = :operation_token
                    LIMIT 1
                    """
                ),
                {"operation_token": command.operation_token.bytes},
            )
            .mappings()
            .first()
        )
        if token_row is None:
            return None
        stored_digest = _as_bytes(
            token_row["operation_digest"],
            length=32,
            label="published move revision operation digest",
        )
        if (
            token_row["operation_kind"] != "create_published_move_revision"
            or int(token_row["actor_user_id"]) != command.actor_user_id
            or not hmac.compare_digest(stored_digest, command.operation_digest)
        ):
            raise PublicationOperationConflict(
                "operation token is already bound to another draft command"
            )

        result = (
            connection.execute(
                sa.text(
                    """
                    SELECT result_kind, result_dataset_id, result_version_id,
                           result_version_no, result_status,
                           result_data_revision, result_review_revision,
                           superseded_version_id_1, superseded_version_id_2,
                           source_dataset_id, source_version_id,
                           create_revision_parent_version_id,
                           published_move_source_parent_version_id,
                           published_move_source_lineage_type, completed_at
                    FROM draft_operation_results
                    WHERE operation_token = :operation_token
                    LIMIT 1
                    """
                ),
                {"operation_token": command.operation_token.bytes},
            )
            .mappings()
            .first()
        )
        if result is None:
            if require_result:
                raise PublicationCommitOutcomeUnknown(
                    "published move revision token has no terminal result"
                )
            return None

        dataset_id = int(result["result_dataset_id"])
        version_id = int(result["result_version_id"])
        result_kind = str(result["result_kind"])
        if result_kind == "cancelled":
            if (
                not isinstance(command.target, ActiveDraftMoveTarget)
                or command.target.action != "cancel"
                or result["result_status"] != "cancelled"
                or dataset_id != command.source_dataset_id
                or version_id != command.expected_source_publication.version_id
                or result["superseded_version_id_1"] is not None
                or result["superseded_version_id_2"] is not None
                or result["source_dataset_id"] is not None
                or result["source_version_id"] is not None
                or result["create_revision_parent_version_id"] is not None
                or result["published_move_source_parent_version_id"] is not None
                or result["published_move_source_lineage_type"] is not None
            ):
                raise PublicationError(
                    "published move cancellation has invalid frozen lineage"
                )
            return DraftCommandResult(
                operation_token=command.operation_token,
                result_kind="published_move_revision_cancelled",
                dataset_id=dataset_id,
                version_id=version_id,
                version_no=int(result["result_version_no"]),
                status="cancelled",
                data_revision=int(result["result_data_revision"]),
                review_revision=int(result["result_review_revision"]),
                source_dataset_id=None,
                source_version_id=None,
                completed_at=_utc_datetime(result["completed_at"], "completed_at"),
            )

        if (
            isinstance(command.target, ActiveDraftMoveTarget)
            and command.target.action == "cancel"
        ):
            raise PublicationError(
                "published move cancellation has a non-cancelled result"
            )
        expected_target_id = command.target.dataset_id
        source_dataset_id = int(result["source_dataset_id"])
        source_version_id = int(result["source_version_id"])
        expected_superseded = (
            command.target.draft.version_id
            if isinstance(command.target, ActiveDraftMoveTarget)
            else None
        )
        if (
            result_kind != "move_revision_created"
            or result["result_status"] != "draft"
            or int(result["result_data_revision"]) != 0
            or int(result["result_review_revision"]) != 0
            or result["superseded_version_id_2"] is not None
            or (
                int(result["superseded_version_id_1"])
                if result["superseded_version_id_1"] is not None
                else None
            )
            != expected_superseded
            or result["create_revision_parent_version_id"] is not None
            or source_dataset_id != command.source_dataset_id
            or source_version_id != command.expected_source_publication.version_id
            or dataset_id == source_dataset_id
            or (expected_target_id is not None and dataset_id != expected_target_id)
            or int(result["published_move_source_parent_version_id"])
            != source_version_id
            or result["published_move_source_lineage_type"] != "moved_source"
        ):
            raise PublicationError("published move revision has invalid frozen lineage")
        return DraftCommandResult(
            operation_token=command.operation_token,
            result_kind="published_move_revision_created",
            dataset_id=dataset_id,
            version_id=version_id,
            version_no=int(result["result_version_no"]),
            status="draft",
            data_revision=0,
            review_revision=0,
            source_dataset_id=source_dataset_id,
            source_version_id=source_version_id,
            completed_at=_utc_datetime(result["completed_at"], "completed_at"),
        )

    def _claim_revision_operation(
        self,
        connection: Connection,
        *,
        command: CreateRevisionCommand,
        registered_at: datetime,
    ) -> DraftCommandResult | None:
        savepoint = connection.begin_nested()
        try:
            connection.execute(
                sa.text(
                    """
                    INSERT INTO draft_operation_tokens (
                        operation_token, operation_kind, operation_digest,
                        actor_user_id, registered_at
                    ) VALUES (
                        :operation_token, 'create_revision', :operation_digest,
                        :actor_user_id, :registered_at
                    )
                    """
                ),
                {
                    "operation_token": command.operation_token.bytes,
                    "operation_digest": command.operation_digest,
                    "actor_user_id": command.actor_user_id,
                    "registered_at": registered_at,
                },
            )
            savepoint.commit()
            return None
        except IntegrityError as error:
            savepoint.rollback()
            if _mysql_error_code(error) != 1062:
                raise
        return self._revision_result(
            connection,
            command=command,
            require_result=True,
        )

    def _recover_revision_operation(
        self,
        command: CreateRevisionCommand,
    ) -> DraftCommandResult | None:
        with self._engine.connect() as connection:
            return self._revision_result(
                connection,
                command=command,
                require_result=False,
            )

    def _revision_result(
        self,
        connection: Connection,
        *,
        command: CreateRevisionCommand,
        require_result: bool,
    ) -> DraftCommandResult | None:
        token_row = (
            connection.execute(
                sa.text(
                    """
                    SELECT operation_kind, operation_digest, actor_user_id
                    FROM draft_operation_tokens
                    WHERE operation_token = :operation_token
                    LIMIT 1
                    """
                ),
                {"operation_token": command.operation_token.bytes},
            )
            .mappings()
            .first()
        )
        if token_row is None:
            return None
        stored_digest = _as_bytes(
            token_row["operation_digest"],
            length=32,
            label="revision operation digest",
        )
        if (
            token_row["operation_kind"] != "create_revision"
            or int(token_row["actor_user_id"]) != command.actor_user_id
            or not hmac.compare_digest(stored_digest, command.operation_digest)
        ):
            raise PublicationOperationConflict(
                "operation token is already bound to another draft command"
            )

        result = (
            connection.execute(
                sa.text(
                    """
                    SELECT result_kind, result_dataset_id, result_version_id,
                           result_version_no, result_status,
                           result_data_revision, result_review_revision,
                           superseded_version_id_1, superseded_version_id_2,
                           source_dataset_id, source_version_id,
                           create_revision_parent_version_id, completed_at
                    FROM draft_operation_results
                    WHERE operation_token = :operation_token
                    LIMIT 1
                    """
                ),
                {"operation_token": command.operation_token.bytes},
            )
            .mappings()
            .first()
        )
        if result is None:
            if require_result:
                raise PublicationCommitOutcomeUnknown(
                    "revision operation token has no terminal result"
                )
            return None

        dataset_id = int(result["result_dataset_id"])
        version_id = int(result["result_version_id"])
        source_dataset_id = int(result["source_dataset_id"])
        source_version_id = int(result["source_version_id"])
        parent_version_id = int(result["create_revision_parent_version_id"])
        if (
            result["result_kind"] != "created"
            or result["result_status"] != "draft"
            or int(result["result_data_revision"]) != 0
            or int(result["result_review_revision"]) != 0
            or result["superseded_version_id_1"] is not None
            or result["superseded_version_id_2"] is not None
            or dataset_id != command.dataset_id
            or source_dataset_id != dataset_id
            or source_version_id != command.expected_publication.version_id
            or parent_version_id != source_version_id
            or version_id == source_version_id
        ):
            raise PublicationError(
                "revision terminal result has invalid frozen lineage"
            )
        return DraftCommandResult(
            operation_token=command.operation_token,
            result_kind="revision_created",
            dataset_id=dataset_id,
            version_id=version_id,
            version_no=int(result["result_version_no"]),
            status="draft",
            data_revision=0,
            review_revision=0,
            source_dataset_id=source_dataset_id,
            source_version_id=source_version_id,
            completed_at=_utc_datetime(result["completed_at"], "completed_at"),
        )

    def _execute_command(
        self,
        *,
        operation_kind: _OperationKind,
        operation_token: UUID,
        operation_digest: bytes,
        actor_user_id: int,
        occurred_at: datetime,
        request_payload: Mapping[str, object],
        work: Callable[
            [Connection, _Actor, datetime, int],
            PublicationCommandResult,
        ],
    ) -> PublicationCommandResult:
        timestamp = _mysql_datetime(occurred_at)

        def recover_known_outcome() -> PublicationCommandResult | None:
            try:
                return self._recover_command(
                    operation_token=operation_token,
                    operation_kind=operation_kind,
                    operation_digest=operation_digest,
                    actor_user_id=actor_user_id,
                )
            except PublicationError:
                raise
            except SQLAlchemyError as error:
                raise PublicationError("publication recovery failed") from error

        recovered = recover_known_outcome()
        if recovered is not None:
            return recovered

        failed_attempt = 0
        while True:
            failed_attempt += 1
            try:
                with self._engine.begin() as connection:
                    claim = self._claim_command(
                        connection,
                        operation_token=operation_token,
                        operation_kind=operation_kind,
                        operation_digest=operation_digest,
                        actor_user_id=actor_user_id,
                        registered_at=timestamp,
                        request_payload=request_payload,
                    )
                    if isinstance(claim, PublicationCommandResult):
                        return claim
                    try:
                        actor = self._load_actor(connection, actor_user_id)
                    except DatasetPermissionDenied as error:
                        raise PublicationPermissionDenied(str(error)) from error
                    return work(connection, actor, timestamp, claim)
            except DBAPIError as error:
                if error.connection_invalidated:
                    try:
                        recovered = self._recover_command(
                            operation_token=operation_token,
                            operation_kind=operation_kind,
                            operation_digest=operation_digest,
                            actor_user_id=actor_user_id,
                        )
                    except PublicationOperationConflict:
                        raise
                    except Exception as recovery_error:
                        raise PublicationCommitOutcomeUnknown(
                            "publication commit acknowledgement was lost and "
                            "recovery failed"
                        ) from recovery_error
                    if recovered is not None:
                        return recovered
                    raise PublicationCommitOutcomeUnknown(
                        "publication commit acknowledgement was lost"
                    ) from error
                error_code = _mysql_error_code(error)
                if self._retry_policy.should_retry(error_code, failed_attempt):
                    recovered = recover_known_outcome()
                    if recovered is not None:
                        return recovered
                    self._publication_retry_waiter(failed_attempt)
                    continue
                if error_code in self._retry_policy.retryable_error_codes:
                    raise PublicationTransactionBusy(
                        "publication transaction remained busy after 4 attempts"
                    ) from error
                raise PublicationError("publication transaction failed") from error
            except PublicationError:
                raise
            except DatasetPermissionDenied as error:
                raise PublicationPermissionDenied(str(error)) from error
            except DatasetError as error:
                raise PublicationError("publication transaction failed") from error
            except SQLAlchemyError as error:
                raise PublicationError("publication transaction failed") from error

    def _claim_command(
        self,
        connection: Connection,
        *,
        operation_token: UUID,
        operation_kind: _OperationKind,
        operation_digest: bytes,
        actor_user_id: int,
        registered_at: datetime,
        request_payload: Mapping[str, object],
    ) -> int | PublicationCommandResult:
        savepoint = connection.begin_nested()
        try:
            inserted = connection.execute(
                sa.text(
                    """
                    INSERT INTO publication_commands (
                        actor_user_id, operation_kind, operation_token,
                        operation_digest, redacted_request_payload, registered_at
                    ) VALUES (
                        :actor_user_id, :operation_kind, :operation_token,
                        :operation_digest, :request_payload, :registered_at
                    )
                    """
                ),
                {
                    "actor_user_id": actor_user_id,
                    "operation_kind": operation_kind,
                    "operation_token": operation_token.bytes,
                    "operation_digest": operation_digest,
                    "request_payload": _canonical_json(dict(request_payload)),
                    "registered_at": registered_at,
                },
            )
            if inserted.lastrowid is None:
                raise PublicationError(
                    "database did not return a publication command ID"
                )
            command_id = int(inserted.lastrowid)
            savepoint.commit()
            return command_id
        except IntegrityError as error:
            savepoint.rollback()
            if _mysql_error_code(error) != 1062:
                raise
        result = self._command_result(
            connection,
            operation_token=operation_token,
            operation_kind=operation_kind,
            operation_digest=operation_digest,
            actor_user_id=actor_user_id,
            require_result=True,
        )
        if result is None:  # pragma: no cover - require_result guarantees this
            raise PublicationCommitOutcomeUnknown(
                "publication command token has no terminal result"
            )
        return result

    def _recover_command(
        self,
        *,
        operation_token: UUID,
        operation_kind: _OperationKind,
        operation_digest: bytes,
        actor_user_id: int,
    ) -> PublicationCommandResult | None:
        with self._engine.connect() as connection:
            return self._command_result(
                connection,
                operation_token=operation_token,
                operation_kind=operation_kind,
                operation_digest=operation_digest,
                actor_user_id=actor_user_id,
                require_result=False,
            )

    def _command_result(
        self,
        connection: Connection,
        *,
        operation_token: UUID,
        operation_kind: _OperationKind,
        operation_digest: bytes,
        actor_user_id: int,
        require_result: bool,
    ) -> PublicationCommandResult | None:
        token_row = (
            connection.execute(
                sa.text(
                    """
                    SELECT id, operation_kind, operation_digest, actor_user_id
                    FROM publication_commands
                    WHERE operation_token = :operation_token
                    LIMIT 1
                    """
                ),
                {"operation_token": operation_token.bytes},
            )
            .mappings()
            .first()
        )
        if token_row is None:
            return None
        command_id = int(token_row["id"])
        stored_digest = _as_bytes(
            token_row["operation_digest"],
            length=32,
            label="publication operation digest",
        )
        if (
            token_row["operation_kind"] != operation_kind
            or int(token_row["actor_user_id"]) != actor_user_id
            or not hmac.compare_digest(stored_digest, operation_digest)
        ):
            raise PublicationOperationConflict(
                "operation token is already bound to another publication command"
            )

        result_row = (
            connection.execute(
                sa.text(
                    """
                    SELECT result_kind, result_dataset_id, result_version_id,
                           result_status, result_data_revision,
                           result_review_revision, validation_run_id,
                           publication_event_id,
                           move_revision_operation_token,
                           reversed_move_command_id, completed_at
                    FROM publication_command_results
                    WHERE command_id = :command_id
                      AND operation_token = :operation_token
                    LIMIT 1
                    """
                ),
                {
                    "command_id": command_id,
                    "operation_token": operation_token.bytes,
                },
            )
            .mappings()
            .first()
        )
        if result_row is None:
            if require_result:
                raise PublicationCommitOutcomeUnknown(
                    "publication command token has no terminal result"
                )
            return None
        event_rows = (
            connection.execute(
                sa.text(
                    """
                    SELECT id, sequence_number, event_type, dataset_id,
                           peer_dataset_id, previous_version_id, next_version_id
                    FROM publication_events
                    WHERE command_id = :command_id
                    ORDER BY sequence_number, id
                    """
                ),
                {"command_id": command_id},
            )
            .mappings()
            .all()
        )
        transitions = tuple(self._transition_from_row(row) for row in event_rows)
        self._validate_frozen_result(
            operation_kind=operation_kind,
            result_row=result_row,
            transitions=transitions,
        )
        return PublicationCommandResult(
            operation_token=operation_token,
            command_id=command_id,
            command_type=_COMMAND_TYPE_BY_OPERATION[operation_kind],
            transitions=transitions,
            completed_at=_utc_datetime(result_row["completed_at"], "completed_at"),
        )

    @staticmethod
    def _transition_from_row(
        row: Mapping[str, Any] | RowMapping,
    ) -> PublicationTransition:
        return PublicationTransition(
            event_id=int(row["id"]),
            sequence_number=int(row["sequence_number"]),
            event_type=cast(Any, str(row["event_type"])),
            dataset_id=int(row["dataset_id"]),
            peer_dataset_id=(
                int(row["peer_dataset_id"])
                if row["peer_dataset_id"] is not None
                else None
            ),
            previous_version_id=(
                int(row["previous_version_id"])
                if row["previous_version_id"] is not None
                else None
            ),
            next_version_id=(
                int(row["next_version_id"])
                if row["next_version_id"] is not None
                else None
            ),
        )

    @staticmethod
    def _validate_frozen_result(
        *,
        operation_kind: _OperationKind,
        result_row: Mapping[str, Any] | RowMapping,
        transitions: tuple[PublicationTransition, ...],
    ) -> None:
        expected_kind = _RESULT_KIND_BY_OPERATION[operation_kind]
        if result_row["result_kind"] != expected_kind:
            raise PublicationError(
                "publication terminal result does not match its operation kind"
            )
        if result_row["result_status"] != "published":
            raise PublicationError("publication terminal result has an invalid status")
        if operation_kind in {"publish", "replace", "rollback"}:
            if len(transitions) != 1:
                raise PublicationError("publication terminal result has invalid events")
            transition = transitions[0]
            if (
                result_row.get("move_revision_operation_token") is not None
                or result_row.get("reversed_move_command_id") is not None
            ):
                raise PublicationError(
                    "ordinary publication result contains move lineage"
                )
        else:
            try:
                validate_publication_event_shape(
                    _COMMAND_TYPE_BY_OPERATION[operation_kind],
                    transitions,
                )
            except ValueError as error:
                raise PublicationError(
                    "publication terminal result has invalid events"
                ) from error
            transition = transitions[1] if operation_kind == "move" else transitions[0]
        if (
            int(result_row["result_dataset_id"]) != transition.dataset_id
            or int(result_row["result_version_id"]) != transition.next_version_id
            or int(result_row["publication_event_id"]) != transition.event_id
        ):
            raise PublicationError(
                "publication terminal result does not match its frozen event"
            )
        validation_run_id = result_row["validation_run_id"]
        if operation_kind in {"rollback", "reverse_move"}:
            if validation_run_id is not None:
                raise PublicationError(
                    "rollback terminal result cannot contain validation lineage"
                )
        elif validation_run_id is None:
            raise PublicationError(
                "publish terminal result is missing validation lineage"
            )
        move_revision_token = result_row.get("move_revision_operation_token")
        reversed_move_command_id = result_row.get("reversed_move_command_id")
        if operation_kind == "move":
            _as_bytes(
                move_revision_token,
                length=16,
                label="move revision operation token",
            )
            if reversed_move_command_id is not None:
                raise PublicationError("move result contains reversal lineage")
        elif operation_kind == "reverse_move":
            if move_revision_token is not None or reversed_move_command_id is None:
                raise PublicationError("move reversal result lineage is incomplete")

    def _create_revision(
        self,
        connection: Connection,
        *,
        actor: _Actor,
        command: CreateRevisionCommand,
        occurred_at: datetime,
    ) -> DraftCommandResult:
        dataset = self._lock_datasets(connection, (command.dataset_id,))[
            command.dataset_id
        ]
        draft_pointer, publication_pointer = self._lock_pointers(
            connection,
            command.dataset_id,
        )
        if draft_pointer is not None:
            raise PublicationStateConflict(
                "create revision is not allowed while an active draft exists"
            )
        self._assert_publication_pointer(
            command.expected_publication,
            publication_pointer,
        )
        if publication_pointer is None:  # constructor requires it; defensive only
            raise PublicationPointerConflict("current publication pointer is absent")
        parent = self._lock_versions(
            connection,
            dataset_id=command.dataset_id,
            version_ids=(publication_pointer.version_id,),
        )[publication_pointer.version_id]
        if parent.status != "published":
            raise PublicationStateConflict(
                "current publication version is not published"
            )
        revision = self._revision_cloner.clone(
            connection,
            dataset=dataset,
            parent=parent,
            actor_user_id=actor.user_id,
            occurred_at=occurred_at,
        )
        try:
            self._insert_draft_pointer(
                connection,
                dataset_id=dataset.dataset_id,
                version_id=revision.version_id,
                occurred_at=occurred_at,
            )
        except ActiveDraftConflict as error:
            raise PublicationStateConflict(
                "another transaction created an active draft"
            ) from error
        self._insert_audit(
            connection,
            site_id=dataset.site_id,
            actor_user_id=actor.user_id,
            event_type="draft_revision_created",
            object_type="dataset_version",
            object_id=str(revision.version_id),
            operation_token=command.operation_token,
            payload={
                "dataset_id": dataset.dataset_id,
                "version_id": revision.version_id,
                "parent_version_id": parent.version_id,
                "reason": command.reason,
            },
            occurred_at=occurred_at,
        )
        return self._record_revision_result(
            connection,
            command=command,
            version=revision,
            parent=parent,
            occurred_at=occurred_at,
        )

    def _create_published_move_revision(
        self,
        connection: Connection,
        *,
        actor: _Actor,
        command: CreatePublishedMoveRevisionCommand,
        occurred_at: datetime,
    ) -> DraftCommandResult:
        if not actor.is_admin:
            raise PublicationPermissionDenied(
                "only an administrator may create a published move revision"
            )
        source_preview = self._dataset_by_id(
            connection,
            dataset_id=command.source_dataset_id,
            lock=False,
        )
        if source_preview is None:
            raise PublicationStateConflict("source dataset does not exist")
        if source_preview.report_date == command.target_report_date:
            raise PublicationStateConflict(
                "target report date must differ from the source date"
            )
        target_preview = self._dataset_for_key(
            connection,
            report_date=command.target_report_date,
            report_type=source_preview.report_type,
            lock=False,
        )
        expected_target_id = command.target.dataset_id
        if expected_target_id is None:
            if target_preview is not None:
                raise PublicationPointerConflict(
                    "target dataset appeared after the caller preview"
                )
        elif target_preview is None or target_preview.dataset_id != expected_target_id:
            raise PublicationPointerConflict(
                "target dataset differs from the caller preview"
            )

        if target_preview is None:
            locked = self._lock_datasets(connection, (source_preview.dataset_id,))
            source_dataset = locked[source_preview.dataset_id]
            target_dataset, target_created = self._lock_or_create_dataset(
                connection,
                site_id=source_dataset.site_id,
                report_date=command.target_report_date,
                report_type=source_dataset.report_type,
                occurred_at=occurred_at,
            )
            if not target_created:
                raise PublicationPointerConflict(
                    "empty target preview became stale before move revision creation"
                )
        else:
            locked = self._lock_datasets(
                connection,
                (source_preview.dataset_id, target_preview.dataset_id),
            )
            source_dataset = locked[source_preview.dataset_id]
            target_dataset = locked[target_preview.dataset_id]
            target_created = False

        if (
            source_dataset.site_id != target_dataset.site_id
            or source_dataset.report_type != target_dataset.report_type
            or target_dataset.report_date != command.target_report_date
        ):
            raise PublicationStateConflict(
                "source and target datasets do not share one site and report type"
            )
        if (
            expected_target_id is not None
            and target_dataset.dataset_id != expected_target_id
        ):
            raise PublicationPointerConflict("locked target dataset changed")

        pointers = self._lock_pointers_for_datasets(
            connection,
            (source_dataset.dataset_id, target_dataset.dataset_id),
        )
        source_draft, source_publication = pointers[source_dataset.dataset_id]
        target_draft, target_publication = pointers[target_dataset.dataset_id]
        if source_draft is not None:
            raise PublicationStateConflict(
                "source dataset has an active draft during published move review"
            )
        self._assert_publication_pointer(
            command.expected_source_publication,
            source_publication,
        )
        if source_publication is None:  # command constructor guarantees presence
            raise PublicationPointerConflict("source publication pointer is absent")

        if isinstance(command.target, EmptyMoveTarget):
            if (
                not target_created
                or target_draft is not None
                or target_publication is not None
            ):
                raise PublicationPointerConflict("target is no longer empty")
        elif isinstance(command.target, PublishedMoveTarget):
            if target_draft is not None:
                raise PublicationStateConflict(
                    "published move target acquired an active draft"
                )
            self._assert_publication_pointer(
                command.target.publication,
                target_publication,
            )
        else:
            self._assert_draft_pointer(command.target.draft, target_draft)
            self._assert_publication_pointer(
                command.target.publication,
                target_publication,
            )

        version_ids: dict[int, list[int]] = {
            source_dataset.dataset_id: [source_publication.version_id],
            target_dataset.dataset_id: [],
        }
        if target_draft is not None:
            version_ids[target_dataset.dataset_id].append(target_draft.version_id)
        if target_publication is not None:
            version_ids[target_dataset.dataset_id].append(target_publication.version_id)
        versions = self._lock_versions_for_datasets(
            connection,
            version_ids,
        )
        source_version = versions[source_dataset.dataset_id][
            source_publication.version_id
        ]
        if source_version.status != "published":
            raise PublicationStateConflict(
                "source publication version is not sealed as published"
            )

        target_active_version = (
            versions[target_dataset.dataset_id][target_draft.version_id]
            if target_draft is not None
            else None
        )
        target_publication_version = (
            versions[target_dataset.dataset_id][target_publication.version_id]
            if target_publication is not None
            else None
        )
        if target_active_version is not None:
            if not isinstance(command.target, ActiveDraftMoveTarget):
                raise PublicationStateConflict("unexpected target active draft")
            self._assert_editable_version(
                command.target.draft,
                target_active_version,
            )
        if (
            target_publication_version is not None
            and target_publication_version.status != "published"
        ):
            raise PublicationStateConflict(
                "target publication version is not sealed as published"
            )

        if (
            isinstance(command.target, ActiveDraftMoveTarget)
            and command.target.action == "cancel"
        ):
            if target_active_version is None:  # pragma: no cover - pointer guarded
                raise PublicationPointerConflict("target active draft disappeared")
            self._insert_audit(
                connection,
                site_id=source_dataset.site_id,
                actor_user_id=actor.user_id,
                event_type="published_move_revision_cancelled",
                object_type="dataset_version",
                object_id=str(source_version.version_id),
                operation_token=command.operation_token,
                payload={
                    "source_dataset_id": source_dataset.dataset_id,
                    "source_version_id": source_version.version_id,
                    "target_dataset_id": target_dataset.dataset_id,
                    "target_draft_version_id": target_active_version.version_id,
                    "reason": command.reason,
                },
                occurred_at=occurred_at,
            )
            return self._record_published_move_revision_result(
                connection,
                command=command,
                version=source_version,
                source=None,
                superseded_version_id=None,
                cancelled=True,
                occurred_at=occurred_at,
            )

        merge_target: _Version | None = None
        if isinstance(command.target, PublishedMoveTarget):
            if command.target.strategy == "merge":
                merge_target = target_publication_version
        elif isinstance(command.target, ActiveDraftMoveTarget):
            if command.target.action == "merge":
                merge_target = target_active_version
            elif command.target.rebuild_strategy == "merge":
                merge_target = target_publication_version
        new_version = self._published_move_cloner.clone(
            connection,
            dataset=target_dataset,
            source=source_version,
            target=merge_target,
            decisions=command.merge_decisions,
            actor_user_id=actor.user_id,
            occurred_at=occurred_at,
        )

        superseded_version_id: int | None = None
        if target_active_version is None:
            try:
                self._insert_draft_pointer(
                    connection,
                    dataset_id=target_dataset.dataset_id,
                    version_id=new_version.version_id,
                    occurred_at=occurred_at,
                )
            except ActiveDraftConflict as error:
                raise PublicationStateConflict(
                    "another transaction created a target active draft"
                ) from error
        else:
            self._switch_draft_pointer(
                connection,
                dataset_id=target_dataset.dataset_id,
                old_version=target_active_version,
                new_version_id=new_version.version_id,
                occurred_at=occurred_at,
            )
            event_type = (
                "force_rebuilt"
                if isinstance(command.target, ActiveDraftMoveTarget)
                and command.target.action == "force_rebuild"
                else "superseded"
            )
            self._discard_version(
                connection,
                version=target_active_version,
                operation_token=command.operation_token,
                operation_kind=cast(Any, "create_published_move_revision"),
                operation_digest=command.operation_digest,
                actor_user_id=actor.user_id,
                event_type=cast(Any, event_type),
                reason=command.reason,
                occurred_at=occurred_at,
                successor_dataset_id=target_dataset.dataset_id,
                successor_version_id=new_version.version_id,
            )
            superseded_version_id = target_active_version.version_id

        self._insert_audit(
            connection,
            site_id=source_dataset.site_id,
            actor_user_id=actor.user_id,
            event_type="published_move_revision_created",
            object_type="dataset_version",
            object_id=str(new_version.version_id),
            operation_token=command.operation_token,
            payload={
                "source_dataset_id": source_dataset.dataset_id,
                "source_version_id": source_version.version_id,
                "target_dataset_id": target_dataset.dataset_id,
                "target_version_id": new_version.version_id,
                "published_move_context_schema_version": 1,
                "source_publication_version_id": source_publication.version_id,
                "source_publication_published_at": (
                    source_publication.published_at.isoformat()
                ),
                "target_publication_version_id": (
                    target_publication.version_id
                    if target_publication is not None
                    else None
                ),
                "target_publication_published_at": (
                    target_publication.published_at.isoformat()
                    if target_publication is not None
                    else None
                ),
                "superseded_target_draft_version_id": superseded_version_id,
                "reason": command.reason,
            },
            occurred_at=occurred_at,
        )
        return self._record_published_move_revision_result(
            connection,
            command=command,
            version=new_version,
            source=source_version,
            superseded_version_id=superseded_version_id,
            cancelled=False,
            occurred_at=occurred_at,
        )

    def _publish(
        self,
        connection: Connection,
        *,
        actor: _Actor,
        command: PublishCommand,
        occurred_at: datetime,
        command_id: int,
        operation_kind: Literal["publish", "replace"],
    ) -> PublicationCommandResult:
        dataset = self._lock_datasets(connection, (command.dataset_id,))[
            command.dataset_id
        ]
        return_guard = lock_return_publication_guard(
            connection,
            operation_token=command.operation_token,
            proposed_versions={command.dataset_id: command.expected_draft.version_id},
        )
        draft_pointer, publication_pointer = self._lock_pointers(
            connection,
            command.dataset_id,
        )
        self._assert_draft_pointer(command.expected_draft, draft_pointer)
        self._assert_publication_pointer(
            command.expected_publication,
            publication_pointer,
        )
        version_ids = [command.expected_draft.version_id]
        if publication_pointer is not None:
            version_ids.append(publication_pointer.version_id)
        versions = self._lock_versions(
            connection,
            dataset_id=command.dataset_id,
            version_ids=version_ids,
        )
        draft = versions[command.expected_draft.version_id]
        self._assert_publish_draft(command.expected_draft, draft)
        self._assert_ordinary_publishable_lineage(
            connection,
            version_id=draft.version_id,
        )
        if publication_pointer is not None:
            current = versions[publication_pointer.version_id]
            if current.status != "published":
                raise PublicationStateConflict(
                    "current publication version is not published"
                )

        validation, latest_full_run_id = self._lock_validation(
            connection,
            command.validation,
            current_data_revision=draft.data_revision,
        )
        blocking, unacknowledged, missing_notes = self._lock_issue_review_state(
            connection,
            version_id=draft.version_id,
            validation_run_id=command.validation.run_id,
        )
        confirmation_matches = self._lock_and_match_confirmation(
            connection,
            dataset=dataset,
            draft=draft,
            validation=command.validation,
            confirmation=command.confirmation,
        )
        if validation is None:
            raise PublicationIneligible((EligibilityFailure.VALIDATION_CHANGED,))
        if validation.status not in {"succeeded", "failed"}:
            raise PublicationStateConflict("validation run is not terminal")
        facts = PublicationEligibilityFacts(
            version_id=draft.version_id,
            version_status=cast(Any, draft.status),
            data_revision=draft.data_revision,
            review_revision=draft.review_revision,
            ruleset_version=draft.ruleset_version,
            validation_run_id=validation.run_id,
            latest_full_validation_run_id=latest_full_run_id,
            validation_run_type=cast(Any, validation.run_type),
            validation_status=cast(Any, validation.status),
            validation_result=cast(Any, validation.result),
            validation_data_revision=validation.data_revision,
            validation_ruleset_version=validation.ruleset_version,
            validation_data_digest=validation.data_digest,
            blocking_issue_count=blocking,
            unacknowledged_warning_count=unacknowledged,
            missing_required_note_count=missing_notes,
            confirmation_matches=confirmation_matches,
        )
        require_publication_eligible(command.expected_draft, command.validation, facts)

        self._delete_expected_draft(
            connection, command.expected_draft, command.dataset_id
        )
        self._publish_ready_version(connection, draft, occurred_at)
        event_kind: Literal["published", "replaced"] = (
            "replaced" if publication_pointer is not None else "published"
        )
        transition = self._insert_event(
            connection,
            command_id=command_id,
            event_type=event_kind,
            dataset_id=command.dataset_id,
            previous_version_id=(
                publication_pointer.version_id
                if publication_pointer is not None
                else None
            ),
            next_version_id=draft.version_id,
            reason=command.reason,
            payload={"validation_run_id": command.validation.run_id},
            occurred_at=occurred_at,
        )
        self._insert_outbox(connection, transition, occurred_at)
        self._write_publication_pointer(
            connection,
            dataset_id=command.dataset_id,
            next_version_id=draft.version_id,
            expected=publication_pointer,
            occurred_at=occurred_at,
        )
        advance_return_publication_guard(
            connection, return_guard, occurred_at=occurred_at
        )
        self._insert_audit(
            connection,
            site_id=dataset.site_id,
            actor_user_id=actor.user_id,
            event_type=f"publication.{event_kind}",
            object_type="daily_dataset",
            object_id=str(dataset.dataset_id),
            operation_token=command.operation_token,
            payload={
                "command_id": command_id,
                "event_id": transition.event_id,
                "previous_version_id": transition.previous_version_id,
                "next_version_id": transition.next_version_id,
                "validation_run_id": command.validation.run_id,
            },
            occurred_at=occurred_at,
        )
        return self._record_publication_result(
            connection,
            command_id=command_id,
            operation_token=command.operation_token,
            operation_kind=operation_kind,
            operation_digest=command.operation_digest,
            actor_user_id=actor.user_id,
            result_kind=event_kind,
            version=draft,
            validation_run_id=command.validation.run_id,
            transition=transition,
            occurred_at=occurred_at,
        )

    def _finalize_published_move(
        self,
        connection: Connection,
        *,
        actor: _Actor,
        command: FinalizePublishedMoveCommand,
        occurred_at: datetime,
        command_id: int,
    ) -> PublicationCommandResult:
        if not actor.is_admin:
            raise PublicationPermissionDenied(
                "only an administrator may finalize a published move"
            )
        datasets = self._lock_datasets(
            connection,
            (command.source_dataset_id, command.target_dataset_id),
        )
        source_dataset = datasets[command.source_dataset_id]
        target_dataset = datasets[command.target_dataset_id]
        self._assert_move_dataset_pair(source_dataset, target_dataset)
        return_guard = lock_return_publication_guard(
            connection,
            operation_token=command.operation_token,
            proposed_versions={
                command.source_dataset_id: None,
                command.target_dataset_id: command.expected_target_draft.version_id,
            },
        )

        pointers = self._lock_pointers_for_datasets(
            connection,
            (command.source_dataset_id, command.target_dataset_id),
        )
        source_draft, source_publication = pointers[command.source_dataset_id]
        target_draft, target_publication = pointers[command.target_dataset_id]
        if source_draft is not None:
            raise PublicationStateConflict(
                "source dataset has an active draft during move finalization"
            )
        self._assert_publication_pointer(
            command.expected_source_publication,
            source_publication,
        )
        self._assert_draft_pointer(command.expected_target_draft, target_draft)
        self._assert_publication_pointer(
            command.expected_target_publication,
            target_publication,
        )
        if source_publication is None or target_draft is None:
            raise PublicationPointerConflict(
                "published move pointers disappeared before finalization"
            )

        version_ids: dict[int, list[int]] = {
            command.source_dataset_id: [source_publication.version_id],
            command.target_dataset_id: [target_draft.version_id],
        }
        if target_publication is not None:
            version_ids[command.target_dataset_id].append(target_publication.version_id)
        versions = self._lock_versions_for_datasets(connection, version_ids)
        source_version = versions[command.source_dataset_id][
            source_publication.version_id
        ]
        target_version = versions[command.target_dataset_id][target_draft.version_id]
        if source_version.status != "published":
            raise PublicationStateConflict(
                "source publication version is not sealed as published"
            )
        self._assert_publish_draft(command.expected_target_draft, target_version)
        if target_publication is not None:
            current_target = versions[command.target_dataset_id][
                target_publication.version_id
            ]
            if current_target.status != "published":
                raise PublicationStateConflict(
                    "target publication version is not sealed as published"
                )

        self._lock_and_validate_move_revision_lineage(
            connection,
            move_revision_operation_token=command.move_revision_operation_token,
            source_dataset_id=command.source_dataset_id,
            source_version_id=source_version.version_id,
            target_dataset_id=command.target_dataset_id,
            target_version_id=target_version.version_id,
        )
        validation, latest_full_run_id = self._lock_validation(
            connection,
            command.validation,
            current_data_revision=target_version.data_revision,
        )
        blocking, unacknowledged, missing_notes = self._lock_issue_review_state(
            connection,
            version_id=target_version.version_id,
            validation_run_id=command.validation.run_id,
        )
        confirmation_matches = self._lock_and_match_confirmation(
            connection,
            dataset=target_dataset,
            draft=target_version,
            validation=command.validation,
            confirmation=command.confirmation,
        )
        if validation is None:
            raise PublicationIneligible((EligibilityFailure.VALIDATION_CHANGED,))
        if validation.status not in {"succeeded", "failed"}:
            raise PublicationStateConflict("validation run is not terminal")
        require_publication_eligible(
            command.expected_target_draft,
            command.validation,
            PublicationEligibilityFacts(
                version_id=target_version.version_id,
                version_status=cast(Any, target_version.status),
                data_revision=target_version.data_revision,
                review_revision=target_version.review_revision,
                ruleset_version=target_version.ruleset_version,
                validation_run_id=validation.run_id,
                latest_full_validation_run_id=latest_full_run_id,
                validation_run_type=cast(Any, validation.run_type),
                validation_status=cast(Any, validation.status),
                validation_result=cast(Any, validation.result),
                validation_data_revision=validation.data_revision,
                validation_ruleset_version=validation.ruleset_version,
                validation_data_digest=validation.data_digest,
                blocking_issue_count=blocking,
                unacknowledged_warning_count=unacknowledged,
                missing_required_note_count=missing_notes,
                confirmation_matches=confirmation_matches,
            ),
        )

        self._delete_expected_draft(
            connection,
            command.expected_target_draft,
            command.target_dataset_id,
        )
        self._publish_ready_version(connection, target_version, occurred_at)
        self._delete_expected_publication(
            connection,
            dataset_id=command.source_dataset_id,
            expected=source_publication,
        )
        source_transition = self._insert_event(
            connection,
            command_id=command_id,
            sequence_number=1,
            event_type="moved_out",
            dataset_id=command.source_dataset_id,
            peer_dataset_id=command.target_dataset_id,
            previous_version_id=source_version.version_id,
            next_version_id=None,
            reason=command.reason,
            payload={
                "move_revision_operation_token": str(
                    command.move_revision_operation_token
                )
            },
            occurred_at=occurred_at,
        )
        target_transition = self._insert_event(
            connection,
            command_id=command_id,
            sequence_number=2,
            event_type="moved_in",
            dataset_id=command.target_dataset_id,
            peer_dataset_id=command.source_dataset_id,
            previous_version_id=(
                target_publication.version_id
                if target_publication is not None
                else None
            ),
            next_version_id=target_version.version_id,
            reason=command.reason,
            payload={
                "move_revision_operation_token": str(
                    command.move_revision_operation_token
                ),
                "validation_run_id": command.validation.run_id,
            },
            occurred_at=occurred_at,
        )
        self._insert_outbox(connection, source_transition, occurred_at)
        self._insert_outbox(connection, target_transition, occurred_at)
        self._write_publication_pointer(
            connection,
            dataset_id=command.target_dataset_id,
            next_version_id=target_version.version_id,
            expected=target_publication,
            occurred_at=occurred_at,
        )
        advance_return_publication_guard(
            connection, return_guard, occurred_at=occurred_at
        )
        self._insert_audit(
            connection,
            site_id=source_dataset.site_id,
            actor_user_id=actor.user_id,
            event_type="publication.moved",
            object_type="daily_dataset",
            object_id=str(command.source_dataset_id),
            operation_token=command.operation_token,
            payload={
                "command_id": command_id,
                "source_event_id": source_transition.event_id,
                "target_event_id": target_transition.event_id,
                "source_dataset_id": command.source_dataset_id,
                "target_dataset_id": command.target_dataset_id,
                "source_version_id": source_version.version_id,
                "target_version_id": target_version.version_id,
                "validation_run_id": command.validation.run_id,
            },
            occurred_at=occurred_at,
        )
        return self._record_cross_dataset_publication_result(
            connection,
            command_id=command_id,
            operation_token=command.operation_token,
            operation_kind="move",
            operation_digest=command.operation_digest,
            actor_user_id=actor.user_id,
            result_kind="moved",
            version=target_version,
            validation_run_id=command.validation.run_id,
            transitions=(source_transition, target_transition),
            primary_transition=target_transition,
            move_revision_operation_token=command.move_revision_operation_token,
            reversed_move_command_id=None,
            occurred_at=occurred_at,
        )

    def _rollback(
        self,
        connection: Connection,
        *,
        actor: _Actor,
        command: RollbackCommand,
        occurred_at: datetime,
        command_id: int,
    ) -> PublicationCommandResult:
        if not actor.is_admin:
            raise PublicationPermissionDenied(
                "only an administrator may roll back a publication"
            )
        dataset = self._lock_datasets(connection, (command.dataset_id,))[
            command.dataset_id
        ]
        return_guard = lock_return_publication_guard(
            connection,
            operation_token=command.operation_token,
            proposed_versions={command.dataset_id: command.target_version_id},
        )
        draft_pointer, publication_pointer = self._lock_pointers(
            connection,
            command.dataset_id,
        )
        if draft_pointer is not None:
            raise PublicationStateConflict(
                "rollback is not allowed while an active draft exists"
            )
        self._assert_publication_pointer(
            command.expected_publication,
            publication_pointer,
        )
        if publication_pointer is None:  # constructor requires it; defensive only
            raise PublicationPointerConflict("current publication pointer is absent")
        versions = self._lock_versions(
            connection,
            dataset_id=command.dataset_id,
            version_ids=(publication_pointer.version_id, command.target_version_id),
        )
        current = versions[publication_pointer.version_id]
        target = versions[command.target_version_id]
        if current.status != "published" or target.status != "published":
            raise PublicationStateConflict(
                "rollback versions must have published status"
            )
        if not self._has_successful_publication_history(
            connection,
            dataset_id=command.dataset_id,
            target_version_id=command.target_version_id,
        ):
            raise PublicationStateConflict(
                "rollback target has no historical successful publication event"
            )

        transition = self._insert_event(
            connection,
            command_id=command_id,
            event_type="rolled_back",
            dataset_id=command.dataset_id,
            previous_version_id=current.version_id,
            next_version_id=target.version_id,
            reason=command.reason,
            payload={"target_version_id": target.version_id},
            occurred_at=occurred_at,
        )
        self._insert_outbox(connection, transition, occurred_at)
        self._write_publication_pointer(
            connection,
            dataset_id=command.dataset_id,
            next_version_id=target.version_id,
            expected=publication_pointer,
            occurred_at=occurred_at,
        )
        advance_return_publication_guard(
            connection, return_guard, occurred_at=occurred_at
        )
        self._insert_audit(
            connection,
            site_id=dataset.site_id,
            actor_user_id=actor.user_id,
            event_type="publication.rolled_back",
            object_type="daily_dataset",
            object_id=str(dataset.dataset_id),
            operation_token=command.operation_token,
            payload={
                "command_id": command_id,
                "event_id": transition.event_id,
                "previous_version_id": current.version_id,
                "next_version_id": target.version_id,
            },
            occurred_at=occurred_at,
        )
        return self._record_publication_result(
            connection,
            command_id=command_id,
            operation_token=command.operation_token,
            operation_kind="rollback",
            operation_digest=command.operation_digest,
            actor_user_id=actor.user_id,
            result_kind="rolled_back",
            version=target,
            validation_run_id=None,
            transition=transition,
            occurred_at=occurred_at,
        )

    def _undo_published_move(
        self,
        connection: Connection,
        *,
        actor: _Actor,
        command: UndoPublishedMoveCommand,
        occurred_at: datetime,
        command_id: int,
    ) -> PublicationCommandResult:
        if not actor.is_admin:
            raise PublicationPermissionDenied(
                "only an administrator may reverse a published move"
            )
        datasets = self._lock_datasets(
            connection,
            (command.source_dataset_id, command.target_dataset_id),
        )
        source_dataset = datasets[command.source_dataset_id]
        target_dataset = datasets[command.target_dataset_id]
        self._assert_move_dataset_pair(source_dataset, target_dataset)
        return_guard = lock_return_publication_guard(
            connection,
            operation_token=command.operation_token,
            proposed_versions={
                command.source_dataset_id: command.restore_source_version_id,
                command.target_dataset_id: command.restore_target_version_id,
            },
        )
        pointers = self._lock_pointers_for_datasets(
            connection,
            (command.source_dataset_id, command.target_dataset_id),
        )
        source_draft, source_publication = pointers[command.source_dataset_id]
        target_draft, target_publication = pointers[command.target_dataset_id]
        if source_draft is not None or target_draft is not None:
            raise PublicationStateConflict(
                "move reversal is not allowed while either dataset has an active draft"
            )
        self._assert_publication_pointer(
            command.expected_source_publication,
            source_publication,
        )
        self._assert_publication_pointer(
            command.expected_target_publication,
            target_publication,
        )
        if target_publication is None:
            raise PublicationPointerConflict(
                "target publication pointer disappeared before move reversal"
            )

        original_transitions = self._lock_move_command_to_reverse(
            connection,
            command=command,
        )
        source_move, target_move = original_transitions
        for dataset_id, expected_event in (
            (command.source_dataset_id, "moved_out"),
            (command.target_dataset_id, "moved_in"),
        ):
            if not self._is_latest_successful_publication_event(
                connection,
                dataset_id=dataset_id,
                command_id=command.move_command_id,
                event_type=expected_event,
            ):
                raise PublicationStateConflict(
                    "the selected move is not the latest publication event"
                )

        version_ids: dict[int, list[int]] = {
            command.source_dataset_id: [command.restore_source_version_id],
            command.target_dataset_id: [target_publication.version_id],
        }
        if command.restore_target_version_id is not None:
            version_ids[command.target_dataset_id].append(
                command.restore_target_version_id
            )
        versions = self._lock_versions_for_datasets(connection, version_ids)
        restore_source = versions[command.source_dataset_id][
            command.restore_source_version_id
        ]
        current_target = versions[command.target_dataset_id][
            target_publication.version_id
        ]
        restore_target = (
            versions[command.target_dataset_id][command.restore_target_version_id]
            if command.restore_target_version_id is not None
            else None
        )
        if restore_source.status != "published" or current_target.status != "published":
            raise PublicationStateConflict(
                "move reversal versions must have published status"
            )
        if restore_target is not None and restore_target.status != "published":
            raise PublicationStateConflict(
                "target restore version must have published status"
            )
        if (
            source_move.previous_version_id != restore_source.version_id
            or target_move.next_version_id != current_target.version_id
            or target_move.previous_version_id
            != (restore_target.version_id if restore_target is not None else None)
        ):
            raise PublicationStateConflict(
                "move reversal versions do not match the original move"
            )

        source_transition = self._insert_event(
            connection,
            command_id=command_id,
            sequence_number=1,
            event_type="move_reversed",
            dataset_id=command.source_dataset_id,
            peer_dataset_id=command.target_dataset_id,
            previous_version_id=None,
            next_version_id=restore_source.version_id,
            reason=command.reason,
            payload={"reversed_move_command_id": command.move_command_id},
            occurred_at=occurred_at,
        )
        target_transition = self._insert_event(
            connection,
            command_id=command_id,
            sequence_number=2,
            event_type="move_reversed",
            dataset_id=command.target_dataset_id,
            peer_dataset_id=command.source_dataset_id,
            previous_version_id=current_target.version_id,
            next_version_id=(
                restore_target.version_id if restore_target is not None else None
            ),
            reason=command.reason,
            payload={"reversed_move_command_id": command.move_command_id},
            occurred_at=occurred_at,
        )
        self._insert_outbox(connection, source_transition, occurred_at)
        self._insert_outbox(connection, target_transition, occurred_at)
        self._write_publication_pointer(
            connection,
            dataset_id=command.source_dataset_id,
            next_version_id=restore_source.version_id,
            expected=None,
            occurred_at=occurred_at,
        )
        if restore_target is None:
            self._delete_expected_publication(
                connection,
                dataset_id=command.target_dataset_id,
                expected=target_publication,
            )
        else:
            self._write_publication_pointer(
                connection,
                dataset_id=command.target_dataset_id,
                next_version_id=restore_target.version_id,
                expected=target_publication,
                occurred_at=occurred_at,
            )
        advance_return_publication_guard(
            connection, return_guard, occurred_at=occurred_at
        )
        self._insert_audit(
            connection,
            site_id=source_dataset.site_id,
            actor_user_id=actor.user_id,
            event_type="publication.move_reversed",
            object_type="daily_dataset",
            object_id=str(command.source_dataset_id),
            operation_token=command.operation_token,
            payload={
                "command_id": command_id,
                "reversed_move_command_id": command.move_command_id,
                "source_event_id": source_transition.event_id,
                "target_event_id": target_transition.event_id,
                "source_dataset_id": command.source_dataset_id,
                "target_dataset_id": command.target_dataset_id,
                "restore_source_version_id": restore_source.version_id,
                "restore_target_version_id": (
                    restore_target.version_id if restore_target is not None else None
                ),
            },
            occurred_at=occurred_at,
        )
        return self._record_cross_dataset_publication_result(
            connection,
            command_id=command_id,
            operation_token=command.operation_token,
            operation_kind="reverse_move",
            operation_digest=command.operation_digest,
            actor_user_id=actor.user_id,
            result_kind="move_reversed",
            version=restore_source,
            validation_run_id=None,
            transitions=(source_transition, target_transition),
            primary_transition=source_transition,
            move_revision_operation_token=None,
            reversed_move_command_id=command.move_command_id,
            occurred_at=occurred_at,
        )

    @staticmethod
    def _assert_move_dataset_pair(source: _Dataset, target: _Dataset) -> None:
        if source.dataset_id == target.dataset_id:
            raise PublicationStateConflict(
                "source and target datasets must be different"
            )
        if source.site_id != target.site_id or source.report_type != target.report_type:
            raise PublicationStateConflict(
                "source and target datasets must share one site and report type"
            )
        if source.report_date == target.report_date:
            raise PublicationStateConflict(
                "source and target datasets must have different report dates"
            )

    def _lock_pointers_for_datasets(
        self,
        connection: Connection,
        dataset_ids: Sequence[int],
    ) -> dict[int, tuple[_DraftPointer | None, _PublicationPointer | None]]:
        return {
            dataset_id: self._lock_pointers(connection, dataset_id)
            for dataset_id in ordered_dataset_ids(dataset_ids)
        }

    def _lock_versions_for_datasets(
        self,
        connection: Connection,
        version_ids: Mapping[int, Sequence[int]],
    ) -> dict[int, dict[int, _Version]]:
        return {
            dataset_id: self._lock_versions(
                connection,
                dataset_id=dataset_id,
                version_ids=version_ids[dataset_id],
            )
            for dataset_id in ordered_dataset_ids(version_ids)
        }

    @staticmethod
    def _assert_editable_version(
        expected: DraftPointerExpectation,
        actual: _Version,
    ) -> None:
        if actual.status not in {"draft", "ready_for_publish"}:
            raise PublicationStateConflict("target draft version is not editable")
        if (
            actual.version_id != expected.version_id
            or actual.status != expected.status
            or actual.data_revision != expected.data_revision
            or actual.review_revision != expected.review_revision
        ):
            raise PublicationPointerConflict("target draft revision changed")

    @staticmethod
    def _assert_ordinary_publishable_lineage(
        connection: Connection,
        *,
        version_id: int,
    ) -> None:
        """Fail closed on every moved-source edge in the complete ancestry."""

        lineage_rows = (
            connection.execute(
                sa.text(
                    """
                    WITH RECURSIVE lineage_versions (version_id) AS (
                        SELECT :version_id
                        UNION DISTINCT
                        SELECT parents.parent_version_id
                        FROM version_parent_versions AS parents
                        INNER JOIN lineage_versions
                            ON lineage_versions.version_id =
                               parents.child_version_id
                    ),
                    moved_edges AS (
                        SELECT parents.child_version_id,
                               parents.parent_version_id
                        FROM version_parent_versions AS parents
                        INNER JOIN lineage_versions
                            ON lineage_versions.version_id =
                               parents.child_version_id
                        WHERE parents.lineage_type = 'moved_source'
                    )
                    SELECT moved_edges.child_version_id,
                           child_versions.dataset_id AS child_dataset_id,
                           moved_edges.parent_version_id,
                           parent_versions.dataset_id AS parent_dataset_id,
                           operations.operation_token,
                           operations.operation_kind,
                           operations.result_kind,
                           operations.result_dataset_id,
                           operations.result_version_id,
                           operations.result_status,
                           operations.result_data_revision,
                           operations.result_review_revision,
                           operations.source_dataset_id,
                           operations.source_version_id,
                           operations.published_move_source_parent_version_id,
                           operations.published_move_source_lineage_type,
                           CASE
                               WHEN operations.operation_token IS NULL THEN 0
                               ELSE (
                                   SELECT COUNT(*)
                                   FROM publication_command_results AS move_results
                                   WHERE move_results.move_revision_operation_token =
                                         operations.operation_token
                                     AND move_results.operation_kind = 'move'
                                     AND move_results.result_kind = 'moved'
                                     AND move_results.result_dataset_id =
                                         operations.result_dataset_id
                                     AND move_results.result_version_id =
                                         operations.result_version_id
                               )
                           END AS completed_move_count
                    FROM moved_edges
                    INNER JOIN dataset_versions AS child_versions
                        ON child_versions.id = moved_edges.child_version_id
                    INNER JOIN dataset_versions AS parent_versions
                        ON parent_versions.id = moved_edges.parent_version_id
                    LEFT JOIN draft_operation_results AS operations
                        ON operations.result_version_id =
                           moved_edges.child_version_id
                       AND operations.source_version_id =
                           moved_edges.parent_version_id
                       AND (
                           (operations.operation_kind =
                                'create_published_move_revision'
                            AND operations.result_kind =
                                'move_revision_created')
                           OR
                           (operations.operation_kind = 'reassign_date'
                            AND operations.result_kind = 'reassigned')
                       )
                    ORDER BY moved_edges.child_version_id,
                             moved_edges.parent_version_id,
                             operations.completed_at,
                             operations.operation_token
                    """
                ),
                {"version_id": version_id},
            )
            .mappings()
            .all()
        )
        if not lineage_rows:
            return

        rows_by_edge: dict[tuple[int, int], list[RowMapping]] = {}
        for row in lineage_rows:
            try:
                edge = (
                    int(row["child_version_id"]),
                    int(row["parent_version_id"]),
                )
            except (TypeError, ValueError, OverflowError) as error:
                raise PublicationStateConflict(
                    "moved-source ancestry is invalid for ordinary publication"
                ) from error
            rows_by_edge.setdefault(edge, []).append(row)

        for (child_version_id, parent_version_id), edge_rows in rows_by_edge.items():
            if len(edge_rows) != 1 or edge_rows[0]["operation_kind"] is None:
                raise PublicationStateConflict(
                    "moved-source ancestry is ambiguous for ordinary publication"
                )
            operation = edge_rows[0]
            try:
                child_dataset_id = int(operation["child_dataset_id"])
                parent_dataset_id = int(operation["parent_dataset_id"])
                result_dataset_id = int(operation["result_dataset_id"])
                result_version_id = int(operation["result_version_id"])
                result_data_revision = int(operation["result_data_revision"])
                result_review_revision = int(operation["result_review_revision"])
                source_dataset_id = int(operation["source_dataset_id"])
                source_version_id = int(operation["source_version_id"])
                completed_move_count = int(operation["completed_move_count"])
            except (TypeError, ValueError, OverflowError) as error:
                raise PublicationStateConflict(
                    "moved-source ancestry ledger is invalid for ordinary publication"
                ) from error
            common_matches = (
                result_dataset_id == child_dataset_id
                and result_version_id == child_version_id
                and operation["result_status"] == "draft"
                and result_data_revision == 0
                and result_review_revision == 0
                and source_dataset_id == parent_dataset_id
                and source_dataset_id != child_dataset_id
                and source_version_id == parent_version_id
            )
            if operation["operation_kind"] == "create_published_move_revision":
                try:
                    published_move_parent_id = int(
                        operation["published_move_source_parent_version_id"]
                    )
                    _as_bytes(
                        operation["operation_token"],
                        length=16,
                        label="published move operation token",
                    )
                except (
                    PublicationError,
                    TypeError,
                    ValueError,
                    OverflowError,
                ) as error:
                    raise PublicationStateConflict(
                        "published move ancestry ledger is invalid for "
                        "ordinary publication"
                    ) from error
                if not (
                    common_matches
                    and operation["result_kind"] == "move_revision_created"
                    and published_move_parent_id == parent_version_id
                    and operation["published_move_source_lineage_type"]
                    == "moved_source"
                    and completed_move_count in {0, 1}
                ):
                    raise PublicationStateConflict(
                        "published move ancestry ledger is invalid for "
                        "ordinary publication"
                    )
                if completed_move_count == 0:
                    raise PublicationStateConflict(
                        "pending published move ancestry requires atomic "
                        "published-move finalization"
                    )
                continue
            if not (
                operation["operation_kind"] == "reassign_date"
                and operation["result_kind"] == "reassigned"
                and common_matches
                and operation["published_move_source_parent_version_id"] is None
                and operation["published_move_source_lineage_type"] is None
                and completed_move_count == 0
            ):
                raise PublicationStateConflict(
                    "moved-source ancestry ledger is invalid for ordinary publication"
                )

    @staticmethod
    def _lock_and_validate_move_revision_lineage(
        connection: Connection,
        *,
        move_revision_operation_token: UUID,
        source_dataset_id: int,
        source_version_id: int,
        target_dataset_id: int,
        target_version_id: int,
    ) -> None:
        result = (
            connection.execute(
                sa.text(
                    """
                    SELECT operation_kind, result_kind, result_dataset_id,
                           result_version_id, result_status,
                           source_dataset_id, source_version_id,
                           published_move_source_parent_version_id,
                           published_move_source_lineage_type
                    FROM draft_operation_results
                    WHERE operation_token = :operation_token
                    LIMIT 1
                    FOR SHARE
                    """
                ),
                {"operation_token": move_revision_operation_token.bytes},
            )
            .mappings()
            .first()
        )
        if result is None or (
            result["operation_kind"] != "create_published_move_revision"
            or result["result_kind"] != "move_revision_created"
            or result["result_status"] != "draft"
            or int(result["result_dataset_id"]) != target_dataset_id
            or int(result["result_version_id"]) != target_version_id
            or int(result["source_dataset_id"]) != source_dataset_id
            or int(result["source_version_id"]) != source_version_id
            or int(result["published_move_source_parent_version_id"])
            != source_version_id
            or result["published_move_source_lineage_type"] != "moved_source"
        ):
            raise PublicationStateConflict(
                "move revision token does not identify the expected moved_source draft"
            )
        lineage = (
            connection.execute(
                sa.text(
                    """
                    SELECT lineage_type
                    FROM version_parent_versions
                    WHERE child_version_id = :target_version_id
                      AND parent_version_id = :source_version_id
                      AND lineage_type = 'moved_source'
                    LIMIT 1
                    FOR SHARE
                    """
                ),
                {
                    "target_version_id": target_version_id,
                    "source_version_id": source_version_id,
                },
            )
            .mappings()
            .first()
        )
        if lineage is None:
            raise PublicationStateConflict(
                "target draft is missing its moved_source parent lineage"
            )

    def _lock_move_command_to_reverse(
        self,
        connection: Connection,
        *,
        command: UndoPublishedMoveCommand,
    ) -> tuple[PublicationTransition, PublicationTransition]:
        result = (
            connection.execute(
                sa.text(
                    """
                    SELECT commands.id AS command_id, commands.operation_kind,
                           results.result_kind, results.result_dataset_id,
                           results.result_version_id,
                           results.move_revision_operation_token
                    FROM publication_commands AS commands
                    INNER JOIN publication_command_results AS results
                        ON results.command_id = commands.id
                    WHERE commands.id = :move_command_id
                    LIMIT 1
                    FOR SHARE
                    """
                ),
                {"move_command_id": command.move_command_id},
            )
            .mappings()
            .first()
        )
        if result is None or (
            result["operation_kind"] != "move"
            or result["result_kind"] != "moved"
            or int(result["result_dataset_id"]) != command.target_dataset_id
            or int(result["result_version_id"])
            != command.expected_target_publication.version_id
            or result["move_revision_operation_token"] is None
        ):
            raise PublicationStateConflict(
                "referenced command is not the expected successful move"
            )
        rows = (
            connection.execute(
                sa.text(
                    """
                    SELECT id, sequence_number, event_type, dataset_id,
                           peer_dataset_id, previous_version_id, next_version_id
                    FROM publication_events
                    WHERE command_id = :move_command_id
                    ORDER BY sequence_number, id
                    FOR SHARE
                    """
                ),
                {"move_command_id": command.move_command_id},
            )
            .mappings()
            .all()
        )
        transitions = tuple(self._transition_from_row(row) for row in rows)
        try:
            validate_publication_event_shape("move", transitions)
        except ValueError as error:
            raise PublicationStateConflict(
                "referenced move has invalid frozen publication events"
            ) from error
        source, target = transitions
        if (
            source.dataset_id != command.source_dataset_id
            or source.peer_dataset_id != command.target_dataset_id
            or source.previous_version_id != command.restore_source_version_id
            or target.dataset_id != command.target_dataset_id
            or target.peer_dataset_id != command.source_dataset_id
            or target.previous_version_id != command.restore_target_version_id
            or target.next_version_id != command.expected_target_publication.version_id
        ):
            raise PublicationStateConflict(
                "requested reversal does not match the original move"
            )
        return source, target

    @staticmethod
    def _is_latest_successful_publication_event(
        connection: Connection,
        *,
        dataset_id: int,
        command_id: int,
        event_type: str,
    ) -> bool:
        row = (
            connection.execute(
                sa.text(
                    """
                    SELECT events.command_id, events.event_type
                    FROM publication_events AS events
                    INNER JOIN publication_command_results AS results
                        ON results.command_id = events.command_id
                    WHERE events.dataset_id = :dataset_id
                      AND results.result_kind <> 'cancelled'
                    /* latest successful publication event */
                    ORDER BY events.id DESC
                    LIMIT 1
                    FOR SHARE
                    """
                ),
                {"dataset_id": dataset_id},
            )
            .mappings()
            .first()
        )
        return row is not None and (
            int(row["command_id"]) == command_id and row["event_type"] == event_type
        )

    @staticmethod
    def _lock_pointers(
        connection: Connection,
        dataset_id: int,
    ) -> tuple[_DraftPointer | None, _PublicationPointer | None]:
        draft_row = (
            connection.execute(
                sa.text(
                    """
                    SELECT version_id, version_status, pointed_at
                    FROM dataset_drafts
                    WHERE dataset_id = :dataset_id
                    FOR UPDATE
                    """
                ),
                {"dataset_id": dataset_id},
            )
            .mappings()
            .first()
        )
        publication_row = (
            connection.execute(
                sa.text(
                    """
                    SELECT version_id, version_status, published_at
                    FROM dataset_publications
                    WHERE dataset_id = :dataset_id
                    FOR UPDATE
                    """
                ),
                {"dataset_id": dataset_id},
            )
            .mappings()
            .first()
        )
        draft = (
            _DraftPointer(
                version_id=int(draft_row["version_id"]),
                status=str(draft_row["version_status"]),
                pointed_at=_utc_datetime(draft_row["pointed_at"], "draft pointed_at"),
            )
            if draft_row is not None
            else None
        )
        publication = (
            _PublicationPointer(
                version_id=int(publication_row["version_id"]),
                status=str(publication_row["version_status"]),
                published_at=_utc_datetime(
                    publication_row["published_at"],
                    "publication published_at",
                ),
            )
            if publication_row is not None
            else None
        )
        return draft, publication

    @staticmethod
    def _assert_draft_pointer(
        expected: DraftPointerExpectation,
        actual: _DraftPointer | None,
    ) -> None:
        if actual is None or (
            actual.version_id != expected.version_id
            or actual.status != expected.status
            or actual.pointed_at != expected.pointed_at
        ):
            raise PublicationPointerConflict("active draft pointer changed")

    @staticmethod
    def _assert_publication_pointer(
        expected: PublicationPointerExpectation,
        actual: _PublicationPointer | None,
    ) -> None:
        if not expected.is_present:
            if actual is not None:
                raise PublicationPointerConflict("publication pointer changed")
            return
        if (
            actual is None
            or actual.version_id != expected.version_id
            or actual.published_at != expected.published_at
            or actual.status != "published"
        ):
            raise PublicationPointerConflict("publication pointer changed")

    def _lock_versions(
        self,
        connection: Connection,
        *,
        dataset_id: int,
        version_ids: Sequence[int],
    ) -> dict[int, _Version]:
        # An empty target dataset has no draft or publication version to lock
        # while a cross-date move revision is being created.  It is still
        # protected by the dataset/pointer locks acquired by the caller.
        if not version_ids:
            return {}
        return {
            version_id: self._version_by_id(
                connection,
                dataset_id=dataset_id,
                version_id=version_id,
                lock=True,
            )
            for version_id in ordered_dataset_ids(version_ids)
        }

    @staticmethod
    def _assert_publish_draft(
        expected: DraftPointerExpectation,
        actual: _Version,
    ) -> None:
        if actual.status != "ready_for_publish":
            raise PublicationStateConflict("draft version is not ready for publication")
        if (
            actual.version_id != expected.version_id
            or actual.data_revision != expected.data_revision
            or actual.review_revision != expected.review_revision
        ):
            raise PublicationPointerConflict("ready draft revision changed")

    @staticmethod
    def _lock_validation(
        connection: Connection,
        expected: ValidationExpectation,
        *,
        current_data_revision: int,
    ) -> tuple[_ValidationRun | None, int | None]:
        rows = (
            connection.execute(
                sa.text(
                    """
                    SELECT id, version_id, run_type, data_revision,
                           ruleset_version, status, result, data_digest
                    FROM validation_runs
                    WHERE version_id = :version_id
                      AND (
                          id = :validation_run_id
                          OR (run_type = 'full'
                              AND data_revision = :data_revision)
                      )
                    ORDER BY id
                    FOR SHARE
                    """
                ),
                {
                    "version_id": expected.version_id,
                    "validation_run_id": expected.run_id,
                    "data_revision": current_data_revision,
                },
            )
            .mappings()
            .all()
        )
        runs = tuple(
            _ValidationRun(
                run_id=int(row["id"]),
                version_id=int(row["version_id"]),
                run_type=str(row["run_type"]),
                data_revision=int(row["data_revision"]),
                ruleset_version=str(row["ruleset_version"]),
                status=str(row["status"]),
                result=str(row["result"]),
                data_digest=_as_bytes(
                    row["data_digest"],
                    length=32,
                    label="validation data digest",
                ),
            )
            for row in rows
        )
        selected = next((run for run in runs if run.run_id == expected.run_id), None)
        full_ids = tuple(
            run.run_id
            for run in runs
            if run.run_type == "full" and run.data_revision == current_data_revision
        )
        return selected, max(full_ids, default=None)

    @staticmethod
    def _lock_issue_review_state(
        connection: Connection,
        *,
        version_id: int,
        validation_run_id: int,
    ) -> tuple[int, int, int]:
        issue_rows = (
            connection.execute(
                sa.text(
                    """
                    SELECT id, severity, requires_note
                    FROM validation_issues
                    WHERE version_id = :version_id
                      AND validation_run_id = :validation_run_id
                    ORDER BY id
                    FOR SHARE
                    """
                ),
                {
                    "version_id": version_id,
                    "validation_run_id": validation_run_id,
                },
            )
            .mappings()
            .all()
        )
        issues = tuple(
            _ReviewIssue(
                issue_id=int(row["id"]),
                severity=str(row["severity"]),
                requires_note=bool(row["requires_note"]),
            )
            for row in issue_rows
        )
        review_rows = (
            connection.execute(
                sa.text(
                    """
                    SELECT validation_issue_id, sequence_number,
                           event_type, comment
                    FROM issue_review_events
                    WHERE version_id = :version_id
                      AND validation_run_id = :validation_run_id
                    ORDER BY validation_issue_id, sequence_number, id
                    FOR SHARE
                    """
                ),
                {
                    "version_id": version_id,
                    "validation_run_id": validation_run_id,
                },
            )
            .mappings()
            .all()
        )
        latest: dict[int, _IssueReview] = {}
        for row in review_rows:
            review = _IssueReview(
                issue_id=int(row["validation_issue_id"]),
                sequence_number=int(row["sequence_number"]),
                event_type=str(row["event_type"]),
                comment=(str(row["comment"]) if row["comment"] is not None else None),
            )
            latest[review.issue_id] = review

        blocking = 0
        unacknowledged = 0
        missing_notes = 0
        for issue in issues:
            latest_review = latest.get(issue.issue_id)
            terminal_event = (
                "resolve" if issue.severity == "blocking" else "acknowledge"
            )
            complete = (
                latest_review is not None and latest_review.event_type == terminal_event
            )
            if issue.severity == "blocking" and not complete:
                blocking += 1
            if issue.severity == "warning" and not complete:
                unacknowledged += 1
            if issue.requires_note and (
                not complete
                or latest_review is None
                or latest_review.comment is None
                or not latest_review.comment.strip()
            ):
                missing_notes += 1
        return blocking, unacknowledged, missing_notes

    @staticmethod
    def _lock_and_match_confirmation(
        connection: Connection,
        *,
        dataset: _Dataset,
        draft: _Version,
        validation: ValidationExpectation,
        confirmation: PublicationConfirmation,
    ) -> bool:
        row = (
            connection.execute(
                sa.text(
                    """
                    SELECT to_status, data_revision, to_review_revision,
                           selected_validation_run_id, confirmation_digest,
                           confirmation_json
                    FROM version_review_events
                    WHERE version_id = :version_id
                      AND to_review_revision = :review_revision
                    ORDER BY id DESC
                    LIMIT 1
                    FOR SHARE
                    """
                ),
                {
                    "version_id": draft.version_id,
                    "review_revision": draft.review_revision,
                },
            )
            .mappings()
            .first()
        )
        if row is None:
            return False
        expected_json, expected_digest = _confirmation_snapshot(
            validation,
            confirmation,
        )
        try:
            stored_digest = _as_bytes(
                row["confirmation_digest"],
                length=32,
                label="confirmation digest",
            )
            stored_json = _normalised_json(
                row["confirmation_json"],
                "confirmation snapshot",
            )
        except PublicationError:
            return False
        return (
            confirmation.confirmed_report_date == dataset.report_date
            and confirmation.report_type == dataset.report_type
            and row["to_status"] == "ready_for_publish"
            and int(row["data_revision"]) == draft.data_revision
            and int(row["to_review_revision"]) == draft.review_revision
            and int(row["selected_validation_run_id"]) == validation.run_id
            and hmac.compare_digest(stored_digest, expected_digest)
            and stored_json == expected_json
        )

    @staticmethod
    def _delete_expected_draft(
        connection: Connection,
        expected: DraftPointerExpectation,
        dataset_id: int,
    ) -> None:
        deleted = connection.execute(
            sa.text(
                """
                DELETE FROM dataset_drafts
                WHERE dataset_id = :dataset_id
                  AND version_id = :draft_version_id
                  AND version_status = :draft_status
                  AND pointed_at = :draft_pointed_at
                """
            ),
            {
                "dataset_id": dataset_id,
                "draft_version_id": expected.version_id,
                "draft_status": expected.status,
                "draft_pointed_at": _mysql_datetime(expected.pointed_at),
            },
        )
        if deleted.rowcount != 1:
            raise PublicationPointerConflict(
                "active draft pointer changed before publication"
            )

    @staticmethod
    def _publish_ready_version(
        connection: Connection,
        version: _Version,
        occurred_at: datetime,
    ) -> None:
        updated = connection.execute(
            sa.text(
                """
                UPDATE dataset_versions
                SET status = 'published', sealed_at = :sealed_at
                WHERE dataset_id = :dataset_id
                  AND id = :version_id
                  AND status = 'ready_for_publish'
                  AND data_revision = :data_revision
                  AND review_revision = :review_revision
                  AND sealed_at IS NULL
                """
            ),
            {
                "sealed_at": occurred_at,
                "dataset_id": version.dataset_id,
                "version_id": version.version_id,
                "data_revision": version.data_revision,
                "review_revision": version.review_revision,
            },
        )
        if updated.rowcount != 1:
            raise PublicationStateConflict(
                "ready version changed before it could be published"
            )

    @staticmethod
    def _insert_event(
        connection: Connection,
        *,
        command_id: int,
        sequence_number: int = 1,
        event_type: _EventKind,
        dataset_id: int,
        peer_dataset_id: int | None = None,
        previous_version_id: int | None,
        next_version_id: int | None,
        reason: str,
        payload: Mapping[str, object],
        occurred_at: datetime,
    ) -> PublicationTransition:
        inserted = connection.execute(
            sa.text(
                """
                INSERT INTO publication_events (
                    command_id, sequence_number, event_type, dataset_id,
                    peer_dataset_id, previous_version_id, next_version_id,
                    reason, redacted_payload, occurred_at
                ) VALUES (
                    :command_id, :sequence_number, :event_type, :dataset_id,
                    :peer_dataset_id, :previous_version_id, :next_version_id,
                    :reason, :payload, :occurred_at
                )
                """
            ),
            {
                "command_id": command_id,
                "sequence_number": sequence_number,
                "event_type": event_type,
                "dataset_id": dataset_id,
                "peer_dataset_id": peer_dataset_id,
                "previous_version_id": previous_version_id,
                "next_version_id": next_version_id,
                "reason": reason,
                "payload": _canonical_json(dict(payload)),
                "occurred_at": occurred_at,
            },
        )
        if inserted.lastrowid is None:
            raise PublicationError("database did not return a publication event ID")
        return PublicationTransition(
            event_id=int(inserted.lastrowid),
            sequence_number=sequence_number,
            event_type=event_type,
            dataset_id=dataset_id,
            peer_dataset_id=peer_dataset_id,
            previous_version_id=previous_version_id,
            next_version_id=next_version_id,
        )

    @staticmethod
    def _insert_outbox(
        connection: Connection,
        transition: PublicationTransition,
        occurred_at: datetime,
    ) -> None:
        connection.execute(
            sa.text(
                """
                INSERT INTO publication_outbox (
                    publication_event_id, site_config_version_id, topic,
                    dedupe_key, redacted_payload, status, attempt_count,
                    available_at, locked_at, locked_by, processed_at,
                    last_error, created_at, updated_at
                ) VALUES (
                    :publication_event_id, NULL, 'publication.event',
                    :dedupe_key, :payload, 'pending', 0,
                    :available_at, NULL, NULL, NULL,
                    NULL, :created_at, :updated_at
                )
                """
            ),
            {
                "publication_event_id": transition.event_id,
                "dedupe_key": f"publication-event:{transition.event_id}",
                "payload": _canonical_json(
                    {
                        "event_id": transition.event_id,
                        "event_type": transition.event_type,
                        "dataset_id": transition.dataset_id,
                        "peer_dataset_id": transition.peer_dataset_id,
                        "previous_version_id": transition.previous_version_id,
                        "next_version_id": transition.next_version_id,
                    }
                ),
                "available_at": occurred_at,
                "created_at": occurred_at,
                "updated_at": occurred_at,
            },
        )

    @staticmethod
    def _write_publication_pointer(
        connection: Connection,
        *,
        dataset_id: int,
        next_version_id: int,
        expected: _PublicationPointer | None,
        occurred_at: datetime,
    ) -> None:
        if expected is None:
            connection.execute(
                sa.text(
                    """
                    INSERT INTO dataset_publications (
                        dataset_id, version_id, version_status, published_at
                    ) VALUES (
                        :dataset_id, :next_version_id, 'published', :published_at
                    )
                    """
                ),
                {
                    "dataset_id": dataset_id,
                    "next_version_id": next_version_id,
                    "published_at": occurred_at,
                },
            )
            return
        updated = connection.execute(
            sa.text(
                """
                UPDATE dataset_publications
                SET version_id = :next_version_id,
                    version_status = 'published',
                    published_at = :published_at
                WHERE dataset_id = :dataset_id
                  AND version_id = :expected_version_id
                  AND version_status = 'published'
                  AND published_at = :expected_published_at
                """
            ),
            {
                "next_version_id": next_version_id,
                "published_at": occurred_at,
                "dataset_id": dataset_id,
                "expected_version_id": expected.version_id,
                "expected_published_at": _mysql_datetime(expected.published_at),
            },
        )
        if updated.rowcount != 1:
            raise PublicationPointerConflict(
                "publication pointer changed before it could be updated"
            )

    @staticmethod
    def _delete_expected_publication(
        connection: Connection,
        *,
        dataset_id: int,
        expected: _PublicationPointer,
    ) -> None:
        deleted = connection.execute(
            sa.text(
                """
                DELETE FROM dataset_publications
                WHERE dataset_id = :dataset_id
                  AND version_id = :expected_version_id
                  AND version_status = 'published'
                  AND published_at = :expected_published_at
                """
            ),
            {
                "dataset_id": dataset_id,
                "expected_version_id": expected.version_id,
                "expected_published_at": _mysql_datetime(expected.published_at),
            },
        )
        if deleted.rowcount != 1:
            raise PublicationPointerConflict(
                "publication pointer changed before it could be removed"
            )

    @staticmethod
    def _has_successful_publication_history(
        connection: Connection,
        *,
        dataset_id: int,
        target_version_id: int,
    ) -> bool:
        row = (
            connection.execute(
                sa.text(
                    """
                    SELECT events.id
                    FROM publication_events AS events
                    INNER JOIN publication_command_results AS results
                        ON results.command_id = events.command_id
                    WHERE events.dataset_id = :dataset_id
                      AND events.next_version_id = :target_version_id
                      AND events.event_type IN (
                          'published', 'replaced', 'rolled_back',
                          'moved_in', 'move_reversed'
                      )
                      AND results.result_kind <> 'cancelled'
                    ORDER BY events.id DESC
                    LIMIT 1
                    FOR SHARE
                    """
                ),
                {
                    "dataset_id": dataset_id,
                    "target_version_id": target_version_id,
                },
            )
            .mappings()
            .first()
        )
        return row is not None

    @staticmethod
    def _record_revision_result(
        connection: Connection,
        *,
        command: CreateRevisionCommand,
        version: _Version,
        parent: _Version,
        occurred_at: datetime,
    ) -> DraftCommandResult:
        if (
            version.dataset_id != parent.dataset_id
            or version.version_id == parent.version_id
            or version.status != "draft"
            or version.data_revision != 0
            or version.review_revision != 0
        ):
            raise PublicationError("revision produced an invalid draft result")
        result = DraftCommandResult(
            operation_token=command.operation_token,
            result_kind="revision_created",
            dataset_id=version.dataset_id,
            version_id=version.version_id,
            version_no=version.version_no,
            status="draft",
            data_revision=version.data_revision,
            review_revision=version.review_revision,
            source_dataset_id=parent.dataset_id,
            source_version_id=parent.version_id,
            completed_at=_utc_datetime(occurred_at, "completed_at"),
        )
        connection.execute(
            sa.text(
                """
                INSERT INTO draft_operation_results (
                    operation_token, operation_kind, operation_digest,
                    actor_user_id, result_kind,
                    result_dataset_id, result_version_id,
                    result_version_no, result_status,
                    result_data_revision, result_review_revision,
                    superseded_version_id_1, superseded_version_id_2,
                    source_dataset_id, source_version_id,
                    create_revision_parent_version_id, completed_at
                ) VALUES (
                    :operation_token, :operation_kind, :operation_digest,
                    :actor_user_id, :result_kind,
                    :result_dataset_id, :result_version_id,
                    :result_version_no, :result_status,
                    :result_data_revision, :result_review_revision,
                    :superseded_version_id_1, :superseded_version_id_2,
                    :source_dataset_id, :source_version_id,
                    :create_revision_parent_version_id, :completed_at
                )
                """
            ),
            {
                "operation_token": command.operation_token.bytes,
                "operation_kind": "create_revision",
                "operation_digest": command.operation_digest,
                "actor_user_id": command.actor_user_id,
                "result_kind": "created",
                "result_dataset_id": result.dataset_id,
                "result_version_id": result.version_id,
                "result_version_no": result.version_no,
                "result_status": result.status,
                "result_data_revision": result.data_revision,
                "result_review_revision": result.review_revision,
                "superseded_version_id_1": None,
                "superseded_version_id_2": None,
                "source_dataset_id": result.source_dataset_id,
                "source_version_id": result.source_version_id,
                "create_revision_parent_version_id": parent.version_id,
                "completed_at": occurred_at,
            },
        )
        return result

    @staticmethod
    def _record_published_move_revision_result(
        connection: Connection,
        *,
        command: CreatePublishedMoveRevisionCommand,
        version: _Version,
        source: _Version | None,
        superseded_version_id: int | None,
        cancelled: bool,
        occurred_at: datetime,
    ) -> DraftCommandResult:
        if cancelled:
            if source is not None or superseded_version_id is not None:
                raise PublicationError(
                    "cancelled move revision cannot contain successor lineage"
                )
            result = DraftCommandResult(
                operation_token=command.operation_token,
                result_kind="published_move_revision_cancelled",
                dataset_id=version.dataset_id,
                version_id=version.version_id,
                version_no=version.version_no,
                status="cancelled",
                data_revision=version.data_revision,
                review_revision=version.review_revision,
                source_dataset_id=None,
                source_version_id=None,
                completed_at=_utc_datetime(occurred_at, "completed_at"),
            )
            persisted_kind = "cancelled"
            persisted_source_dataset_id = None
            persisted_source_version_id = None
            source_parent_version_id = None
            source_lineage_type = None
        else:
            if (
                source is None
                or version.status != "draft"
                or version.data_revision != 0
                or version.review_revision != 0
                or source.status != "published"
                or source.dataset_id == version.dataset_id
            ):
                raise PublicationError(
                    "published move revision produced an invalid draft result"
                )
            result = DraftCommandResult(
                operation_token=command.operation_token,
                result_kind="published_move_revision_created",
                dataset_id=version.dataset_id,
                version_id=version.version_id,
                version_no=version.version_no,
                status="draft",
                data_revision=0,
                review_revision=0,
                source_dataset_id=source.dataset_id,
                source_version_id=source.version_id,
                completed_at=_utc_datetime(occurred_at, "completed_at"),
            )
            persisted_kind = "move_revision_created"
            persisted_source_dataset_id = source.dataset_id
            persisted_source_version_id = source.version_id
            source_parent_version_id = source.version_id
            source_lineage_type = "moved_source"

        connection.execute(
            sa.text(
                """
                INSERT INTO draft_operation_results (
                    operation_token, operation_kind, operation_digest,
                    actor_user_id, result_kind,
                    result_dataset_id, result_version_id,
                    result_version_no, result_status,
                    result_data_revision, result_review_revision,
                    superseded_version_id_1, superseded_version_id_2,
                    source_dataset_id, source_version_id,
                    create_revision_parent_version_id,
                    published_move_source_parent_version_id,
                    published_move_source_lineage_type, completed_at
                ) VALUES (
                    :operation_token, :operation_kind, :operation_digest,
                    :actor_user_id, :result_kind,
                    :result_dataset_id, :result_version_id,
                    :result_version_no, :result_status,
                    :result_data_revision, :result_review_revision,
                    :superseded_version_id_1, :superseded_version_id_2,
                    :source_dataset_id, :source_version_id,
                    NULL, :published_move_source_parent_version_id,
                    :published_move_source_lineage_type, :completed_at
                )
                """
            ),
            {
                "operation_token": command.operation_token.bytes,
                "operation_kind": "create_published_move_revision",
                "operation_digest": command.operation_digest,
                "actor_user_id": command.actor_user_id,
                "result_kind": persisted_kind,
                "result_dataset_id": result.dataset_id,
                "result_version_id": result.version_id,
                "result_version_no": result.version_no,
                "result_status": result.status,
                "result_data_revision": result.data_revision,
                "result_review_revision": result.review_revision,
                "superseded_version_id_1": superseded_version_id,
                "superseded_version_id_2": None,
                "source_dataset_id": persisted_source_dataset_id,
                "source_version_id": persisted_source_version_id,
                "published_move_source_parent_version_id": (source_parent_version_id),
                "published_move_source_lineage_type": source_lineage_type,
                "completed_at": occurred_at,
            },
        )
        return result

    @staticmethod
    def _record_cross_dataset_publication_result(
        connection: Connection,
        *,
        command_id: int,
        operation_token: UUID,
        operation_kind: Literal["move", "reverse_move"],
        operation_digest: bytes,
        actor_user_id: int,
        result_kind: Literal["moved", "move_reversed"],
        version: _Version,
        validation_run_id: int | None,
        transitions: tuple[PublicationTransition, PublicationTransition],
        primary_transition: PublicationTransition,
        move_revision_operation_token: UUID | None,
        reversed_move_command_id: int | None,
        occurred_at: datetime,
    ) -> PublicationCommandResult:
        command_type: Literal["move", "reverse_move"] = operation_kind
        validate_publication_event_shape(command_type, transitions)
        if (
            primary_transition not in transitions
            or primary_transition.dataset_id != version.dataset_id
            or primary_transition.next_version_id != version.version_id
        ):
            raise PublicationError(
                "cross-dataset result does not match its primary transition"
            )
        if operation_kind == "move":
            if (
                result_kind != "moved"
                or validation_run_id is None
                or move_revision_operation_token is None
                or reversed_move_command_id is not None
            ):
                raise PublicationError("move result lineage is incomplete")
        elif (
            result_kind != "move_reversed"
            or validation_run_id is not None
            or move_revision_operation_token is not None
            or reversed_move_command_id is None
        ):
            raise PublicationError("move reversal result lineage is incomplete")
        result_payload = {
            "transitions": [
                {
                    "event_id": transition.event_id,
                    "sequence_number": transition.sequence_number,
                    "event_type": transition.event_type,
                    "dataset_id": transition.dataset_id,
                    "peer_dataset_id": transition.peer_dataset_id,
                    "previous_version_id": transition.previous_version_id,
                    "next_version_id": transition.next_version_id,
                }
                for transition in transitions
            ],
            "move_revision_operation_token": (
                str(move_revision_operation_token)
                if move_revision_operation_token is not None
                else None
            ),
            "reversed_move_command_id": reversed_move_command_id,
        }
        connection.execute(
            sa.text(
                """
                INSERT INTO publication_command_results (
                    command_id, operation_token, operation_kind,
                    operation_digest, actor_user_id, result_kind,
                    result_dataset_id, result_version_id, result_status,
                    result_data_revision, result_review_revision,
                    validation_run_id, publication_event_id,
                    move_revision_operation_token, reversed_move_command_id,
                    redacted_result_payload, completed_at
                ) VALUES (
                    :command_id, :operation_token, :operation_kind,
                    :operation_digest, :actor_user_id, :result_kind,
                    :result_dataset_id, :result_version_id, 'published',
                    :result_data_revision, :result_review_revision,
                    :validation_run_id, :publication_event_id,
                    :move_revision_operation_token, :reversed_move_command_id,
                    :result_payload, :completed_at
                )
                """
            ),
            {
                "command_id": command_id,
                "operation_token": operation_token.bytes,
                "operation_kind": operation_kind,
                "operation_digest": operation_digest,
                "actor_user_id": actor_user_id,
                "result_kind": result_kind,
                "result_dataset_id": version.dataset_id,
                "result_version_id": version.version_id,
                "result_data_revision": version.data_revision,
                "result_review_revision": version.review_revision,
                "validation_run_id": validation_run_id,
                "publication_event_id": primary_transition.event_id,
                "move_revision_operation_token": (
                    move_revision_operation_token.bytes
                    if move_revision_operation_token is not None
                    else None
                ),
                "reversed_move_command_id": reversed_move_command_id,
                "result_payload": _canonical_json(result_payload),
                "completed_at": occurred_at,
            },
        )
        return PublicationCommandResult(
            operation_token=operation_token,
            command_id=command_id,
            command_type=command_type,
            transitions=transitions,
            completed_at=_utc_datetime(occurred_at, "completed_at"),
        )

    @staticmethod
    def _record_publication_result(
        connection: Connection,
        *,
        command_id: int,
        operation_token: UUID,
        operation_kind: _OperationKind,
        operation_digest: bytes,
        actor_user_id: int,
        result_kind: _ResultKind,
        version: _Version,
        validation_run_id: int | None,
        transition: PublicationTransition,
        occurred_at: datetime,
    ) -> PublicationCommandResult:
        result_payload = {
            "event_id": transition.event_id,
            "event_type": transition.event_type,
            "dataset_id": transition.dataset_id,
            "previous_version_id": transition.previous_version_id,
            "next_version_id": transition.next_version_id,
        }
        connection.execute(
            sa.text(
                """
                INSERT INTO publication_command_results (
                    command_id, operation_token, operation_kind,
                    operation_digest, actor_user_id, result_kind,
                    result_dataset_id, result_version_id, result_status,
                    result_data_revision, result_review_revision,
                    validation_run_id, publication_event_id,
                    redacted_result_payload, completed_at
                ) VALUES (
                    :command_id, :operation_token, :operation_kind,
                    :operation_digest, :actor_user_id, :result_kind,
                    :result_dataset_id, :result_version_id, 'published',
                    :result_data_revision, :result_review_revision,
                    :validation_run_id, :publication_event_id,
                    :result_payload, :completed_at
                )
                """
            ),
            {
                "command_id": command_id,
                "operation_token": operation_token.bytes,
                "operation_kind": operation_kind,
                "operation_digest": operation_digest,
                "actor_user_id": actor_user_id,
                "result_kind": result_kind,
                "result_dataset_id": version.dataset_id,
                "result_version_id": version.version_id,
                "result_data_revision": version.data_revision,
                "result_review_revision": version.review_revision,
                "validation_run_id": validation_run_id,
                "publication_event_id": transition.event_id,
                "result_payload": _canonical_json(result_payload),
                "completed_at": occurred_at,
            },
        )
        return PublicationCommandResult(
            operation_token=operation_token,
            command_id=command_id,
            command_type=_COMMAND_TYPE_BY_OPERATION[operation_kind],
            transitions=(transition,),
            completed_at=_utc_datetime(occurred_at, "completed_at"),
        )
