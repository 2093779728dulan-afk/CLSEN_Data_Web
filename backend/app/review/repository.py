"""MySQL transaction adapter for auditable draft review operations."""

from __future__ import annotations

import hashlib
import hmac
import json
import random
import time
from collections.abc import Callable, Mapping
from dataclasses import dataclass, replace
from datetime import UTC, date, datetime
from decimal import Decimal
from typing import Any, Literal, cast
from uuid import UUID

import sqlalchemy as sa
from sqlalchemy.engine import Connection, Engine
from sqlalchemy.exc import DBAPIError, IntegrityError, SQLAlchemyError

from app.catalog.scope_repository import append_report_source_key
from app.imports.types import ReportType
from app.validation.codec import decode_field_value, encode_field_value
from app.validation.fields import (
    FieldContractError,
    FieldValue,
    FieldValueError,
    as_field_value,
    field_value_to_database,
    get_field_contract,
    get_report_field_contract,
    validate_added_row_values,
    validate_field_value,
)

from .types import (
    AddRowCommand,
    ChangeRowStateCommand,
    CreateNoteCommand,
    DraftHeadExpectation,
    DraftPointerConflict,
    FieldNotEditable,
    FieldNoteTarget,
    FieldValueInvalid,
    ImportBatchNoteTarget,
    IssueReviewConflict,
    MarkReadyCommand,
    NoteRevisionConflict,
    ParentValueSource,
    RestoreFieldValueCommand,
    RestoreValueUnavailable,
    ReturnToDraftCommand,
    ReviewCommitOutcomeUnknown,
    ReviewError,
    ReviewIssueCommand,
    ReviewMutationResult,
    ReviewOperationConflict,
    ReviewPermissionDenied,
    ReviewRevisionConflict,
    ReviewTransactionBusy,
    ReviseNoteCommand,
    RowNoteTarget,
    RowNotFound,
    RowStateConflict,
    SetFieldValueCommand,
    SourceFileValueSource,
    StaleValidationRun,
    VersionNotEditable,
    VersionNoteTarget,
)

type _ReviewCommand = (
    SetFieldValueCommand
    | RestoreFieldValueCommand
    | AddRowCommand
    | ChangeRowStateCommand
    | CreateNoteCommand
    | ReviseNoteCommand
    | ReviewIssueCommand
    | MarkReadyCommand
    | ReturnToDraftCommand
)
type _OperationWork = Callable[
    [Connection, "_Actor", datetime],
    ReviewMutationResult,
]

_MAX_TRANSACTION_RETRIES = 3
_RETRYABLE_MYSQL_ERROR_CODES = frozenset({1205, 1213})
_RETRY_BASE_DELAY_SECONDS = 0.005
_RETRY_MAX_DELAY_SECONDS = 0.04


@dataclass(frozen=True, slots=True)
class _Actor:
    user_id: int
    roles: frozenset[str]

    @property
    def is_admin(self) -> bool:
        return "admin" in self.roles


@dataclass(frozen=True, slots=True)
class _EditableVersionState:
    dataset_id: int
    version_id: int
    status: Literal["draft", "ready_for_publish"]
    data_revision: int
    review_revision: int
    pointed_at: datetime


@dataclass(frozen=True, slots=True)
class _LockedDraft(_EditableVersionState):
    site_id: int
    report_date: date
    report_type: ReportType
    ruleset_version: str


@dataclass(frozen=True, slots=True)
class _StoredReviewRow:
    row_id: int
    logical_row_id: UUID
    row_ordinal: int
    row_state: Literal["active", "excluded", "deleted"]
    base_row_id: int | None
    original_parsed_source_row_id: int | None
    source_batch_id: int | None
    values: tuple[tuple[str, FieldValue], ...]


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


def _binary(value: object, *, length: int, label: str) -> bytes:
    if not isinstance(value, (bytes, bytearray, memoryview)):
        raise ReviewError(f"database returned a non-binary {label}")
    result = bytes(value)
    if len(result) != length:
        raise ReviewError(f"database returned an invalid {label}")
    return result


def _canonical_json(payload: object) -> str:
    return json.dumps(
        payload,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    )


def _json_object(value: object, *, label: str) -> Mapping[str, object]:
    decoded: object = value
    if isinstance(value, str):
        try:
            decoded = json.loads(value)
        except json.JSONDecodeError as error:
            raise ReviewError(f"database returned invalid {label} JSON") from error
    if not isinstance(decoded, Mapping):
        raise ReviewError(f"database returned invalid {label} JSON")
    return cast(Mapping[str, object], decoded)


def _canonical_decimal(value: object, *, label: str) -> str:
    try:
        parsed = Decimal(str(value))
    except Exception as error:
        raise StaleValidationRun(f"validation summary has invalid {label}") from error
    if not parsed.is_finite():
        raise StaleValidationRun(f"validation summary has invalid {label}")
    if parsed == 0:
        return "0"
    return format(parsed.normalize(), "f")


def _mysql_datetime(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("transaction timestamps must be timezone-aware")
    return value.astimezone(UTC).replace(tzinfo=None)


def _database_utc(value: object) -> datetime:
    if not isinstance(value, datetime):
        raise ReviewError("database returned an invalid pointer timestamp")
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    if value.utcoffset() is None:
        raise ReviewError("database returned an invalid pointer timestamp")
    return value.astimezone(UTC)


class MySqlReviewRepository:
    """Own complete transactions for stage-six edit and review commands."""

    def __init__(
        self,
        engine: Engine,
        *,
        retry_waiter: Callable[[int], None] | None = None,
    ) -> None:
        self._engine = engine
        self._retry_waiter = retry_waiter or _wait_for_transaction_retry

    def set_field_value(
        self,
        command: SetFieldValueCommand,
        *,
        occurred_at: datetime,
    ) -> ReviewMutationResult:
        return self._execute_operation(
            command,
            occurred_at=occurred_at,
            work=lambda connection, actor, timestamp: self._change_field(
                connection,
                actor=actor,
                command=command,
                occurred_at=timestamp,
                restore=False,
            ),
        )

    def restore_field_value(
        self,
        command: RestoreFieldValueCommand,
        *,
        occurred_at: datetime,
    ) -> ReviewMutationResult:
        return self._execute_operation(
            command,
            occurred_at=occurred_at,
            work=lambda connection, actor, timestamp: self._change_field(
                connection,
                actor=actor,
                command=command,
                occurred_at=timestamp,
                restore=True,
            ),
        )

    def add_row(
        self,
        command: AddRowCommand,
        *,
        occurred_at: datetime,
    ) -> ReviewMutationResult:
        return self._execute_operation(
            command,
            occurred_at=occurred_at,
            work=lambda connection, actor, timestamp: self._add_row(
                connection,
                actor=actor,
                command=command,
                occurred_at=timestamp,
            ),
        )

    def change_row_state(
        self,
        command: ChangeRowStateCommand,
        *,
        occurred_at: datetime,
    ) -> ReviewMutationResult:
        return self._execute_operation(
            command,
            occurred_at=occurred_at,
            work=lambda connection, actor, timestamp: self._change_row_state(
                connection,
                actor=actor,
                command=command,
                occurred_at=timestamp,
            ),
        )

    def create_note(
        self,
        command: CreateNoteCommand,
        *,
        occurred_at: datetime,
    ) -> ReviewMutationResult:
        return self._execute_operation(
            command,
            occurred_at=occurred_at,
            work=lambda connection, actor, timestamp: self._create_note(
                connection,
                actor=actor,
                command=command,
                occurred_at=timestamp,
            ),
        )

    def revise_note(
        self,
        command: ReviseNoteCommand,
        *,
        occurred_at: datetime,
    ) -> ReviewMutationResult:
        return self._execute_operation(
            command,
            occurred_at=occurred_at,
            work=lambda connection, actor, timestamp: self._revise_note(
                connection,
                actor=actor,
                command=command,
                occurred_at=timestamp,
            ),
        )

    def review_issue(
        self,
        command: ReviewIssueCommand,
        *,
        occurred_at: datetime,
    ) -> ReviewMutationResult:
        return self._execute_operation(
            command,
            occurred_at=occurred_at,
            work=lambda connection, actor, timestamp: self._review_issue(
                connection,
                actor=actor,
                command=command,
                occurred_at=timestamp,
            ),
        )

    def mark_ready(
        self,
        command: MarkReadyCommand,
        *,
        occurred_at: datetime,
    ) -> ReviewMutationResult:
        return self._execute_operation(
            command,
            occurred_at=occurred_at,
            work=lambda connection, actor, timestamp: self._mark_ready(
                connection,
                actor=actor,
                command=command,
                occurred_at=timestamp,
            ),
        )

    def return_to_draft(
        self,
        command: ReturnToDraftCommand,
        *,
        occurred_at: datetime,
    ) -> ReviewMutationResult:
        return self._execute_operation(
            command,
            occurred_at=occurred_at,
            work=lambda connection, actor, timestamp: self._return_to_draft(
                connection,
                actor=actor,
                command=command,
                occurred_at=timestamp,
            ),
        )

    def _execute_operation(
        self,
        command: _ReviewCommand,
        *,
        occurred_at: datetime,
        work: _OperationWork,
    ) -> ReviewMutationResult:
        timestamp = _mysql_datetime(occurred_at)
        transaction_time = occurred_at.astimezone(UTC)

        def recover_known_outcome() -> ReviewMutationResult | None:
            try:
                return self._recover_operation(command)
            except ReviewError:
                raise
            except SQLAlchemyError as error:
                raise ReviewError("review operation recovery failed") from error

        recovered = recover_known_outcome()
        if recovered is not None:
            return recovered

        retry_count = 0
        while True:
            try:
                with self._engine.begin() as connection:
                    recovered = self._claim_operation(
                        connection,
                        command=command,
                        registered_at=timestamp,
                    )
                    if recovered is not None:
                        return recovered
                    actor = self._load_actor(
                        connection,
                        actor_user_id=command.actor_user_id,
                    )
                    return work(connection, actor, transaction_time)
            except DBAPIError as error:
                if error.connection_invalidated:
                    try:
                        recovered = self._recover_operation(command)
                    except Exception as recovery_error:
                        raise ReviewCommitOutcomeUnknown(
                            "review transaction commit acknowledgement was lost "
                            "and recovery failed"
                        ) from recovery_error
                    if recovered is not None:
                        return recovered
                    raise ReviewCommitOutcomeUnknown(
                        "review transaction commit acknowledgement was lost"
                    ) from error
                if _mysql_error_code(error) not in _RETRYABLE_MYSQL_ERROR_CODES:
                    raise ReviewError("review transaction failed") from error
                if retry_count >= _MAX_TRANSACTION_RETRIES:
                    raise ReviewTransactionBusy(
                        "review transaction remained busy after 3 retries"
                    ) from error
                retry_count += 1
                recovered = recover_known_outcome()
                if recovered is not None:
                    return recovered
                self._retry_waiter(retry_count)
            except ReviewError:
                raise
            except SQLAlchemyError as error:
                raise ReviewError("review transaction failed") from error

    def _claim_operation(
        self,
        connection: Connection,
        *,
        command: _ReviewCommand,
        registered_at: datetime,
    ) -> ReviewMutationResult | None:
        savepoint = connection.begin_nested()
        try:
            connection.execute(
                sa.text(
                    """
                    INSERT INTO review_operation_tokens (
                        operation_token, operation_kind, operation_digest,
                        actor_user_id, registered_at
                    ) VALUES (
                        :operation_token, :operation_kind, :operation_digest,
                        :actor_user_id, :registered_at
                    )
                    """
                ),
                {
                    "operation_token": command.operation_token.bytes,
                    "operation_kind": command.operation_kind,
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
        return self._operation_result(
            connection,
            command=command,
            require_result=True,
        )

    def _recover_operation(
        self,
        command: _ReviewCommand,
    ) -> ReviewMutationResult | None:
        with self._engine.connect() as connection:
            return self._operation_result(
                connection,
                command=command,
                require_result=False,
            )

    @staticmethod
    def _operation_result(
        connection: Connection,
        *,
        command: _ReviewCommand,
        require_result: bool,
    ) -> ReviewMutationResult | None:
        token = (
            connection.execute(
                sa.text(
                    """
                    SELECT operation_kind, operation_digest, actor_user_id
                    FROM review_operation_tokens
                    WHERE operation_token = :operation_token
                    LIMIT 1
                    """
                ),
                {"operation_token": command.operation_token.bytes},
            )
            .mappings()
            .first()
        )
        if token is None:
            return None
        stored_digest = _binary(
            token["operation_digest"],
            length=32,
            label="review operation digest",
        )
        if (
            str(token["operation_kind"]) != command.operation_kind
            or int(token["actor_user_id"]) != command.actor_user_id
            or not hmac.compare_digest(stored_digest, command.operation_digest)
        ):
            raise ReviewOperationConflict(
                "operation token is already bound to another review command"
            )

        row = (
            connection.execute(
                sa.text(
                    """
                    SELECT result_kind, result_import_batch_id,
                           result_dataset_id, result_version_id, result_status,
                           result_data_revision, result_review_revision,
                           affected_row_id, data_change_event_id,
                           issue_review_event_id, validation_run_id,
                           version_review_event_id, note_id
                    FROM review_operation_results
                    WHERE operation_token = :operation_token
                    LIMIT 1
                    """
                ),
                {"operation_token": command.operation_token.bytes},
            )
            .mappings()
            .first()
        )
        if row is None:
            if require_result:
                raise ReviewCommitOutcomeUnknown(
                    "review operation token has no terminal result"
                )
            return None
        if row["result_kind"] != "applied":
            raise ReviewError("review operation contains an unsupported result")

        def optional_int(name: str) -> int | None:
            value = row[name]
            return int(value) if value is not None else None

        status_value = row["result_status"]
        status = str(status_value) if status_value is not None else None
        if status not in {None, "draft", "ready_for_publish"}:
            raise ReviewError("review result contains an invalid status")
        return ReviewMutationResult(
            operation_token=command.operation_token,
            operation_kind=command.operation_kind,
            import_batch_id=optional_int("result_import_batch_id"),
            dataset_id=optional_int("result_dataset_id"),
            version_id=optional_int("result_version_id"),
            status=cast(Any, status),
            data_revision=optional_int("result_data_revision"),
            review_revision=optional_int("result_review_revision"),
            affected_row_id=optional_int("affected_row_id"),
            data_change_event_id=optional_int("data_change_event_id"),
            issue_review_event_id=optional_int("issue_review_event_id"),
            validation_run_id=optional_int("validation_run_id"),
            version_review_event_id=optional_int("version_review_event_id"),
            note_id=optional_int("note_id"),
        )

    @staticmethod
    def _load_actor(connection: Connection, *, actor_user_id: int) -> _Actor:
        user = (
            connection.execute(
                sa.text(
                    """
                    SELECT id, status
                    FROM users
                    WHERE id = :actor_user_id
                    FOR SHARE
                    """
                ),
                {"actor_user_id": actor_user_id},
            )
            .mappings()
            .first()
        )
        if user is None or user["status"] != "active":
            raise ReviewPermissionDenied("actor is not an active user")
        roles = frozenset(
            str(value)
            for value in connection.scalars(
                sa.text(
                    """
                    SELECT roles.code
                    FROM user_roles
                    INNER JOIN roles ON roles.id = user_roles.role_id
                    WHERE user_roles.user_id = :actor_user_id
                    ORDER BY roles.code
                    FOR SHARE
                    """
                ),
                {"actor_user_id": actor_user_id},
            )
        )
        if not roles.intersection({"admin", "data_manager"}):
            raise ReviewPermissionDenied(
                "only administrators and data managers may review drafts"
            )
        return _Actor(user_id=actor_user_id, roles=roles)

    @staticmethod
    def _lock_active_head(
        connection: Connection,
        head: DraftHeadExpectation,
    ) -> _LockedDraft:
        locked = connection.execute(
            sa.text(
                """
                UPDATE daily_dataset_locks
                SET lock_revision = CASE
                    WHEN lock_revision = 18446744073709551615 THEN 0
                    ELSE lock_revision + 1
                END
                WHERE dataset_id = :dataset_id
                """
            ),
            {"dataset_id": head.dataset_id},
        )
        if locked.rowcount != 1:
            raise DraftPointerConflict("daily dataset lock row is missing")

        dataset = (
            connection.execute(
                sa.text(
                    """
                    SELECT id, site_id, report_date, report_type
                    FROM daily_datasets
                    WHERE id = :dataset_id
                    """
                ),
                {"dataset_id": head.dataset_id},
            )
            .mappings()
            .first()
        )
        if dataset is None:
            raise DraftPointerConflict("daily dataset does not exist")

        pointer = (
            connection.execute(
                sa.text(
                    """
                    SELECT dataset_id, version_id, version_status, pointed_at
                    FROM dataset_drafts
                    WHERE dataset_id = :dataset_id
                    FOR UPDATE
                    """
                ),
                {"dataset_id": head.dataset_id},
            )
            .mappings()
            .first()
        )
        if pointer is None:
            raise DraftPointerConflict("daily dataset has no active draft")
        pointed_at = _database_utc(pointer["pointed_at"])
        if (
            int(pointer["dataset_id"]) != head.dataset_id
            or int(pointer["version_id"]) != head.version_id
            or pointer["version_status"] != head.status
            or pointed_at != head.pointed_at
        ):
            raise DraftPointerConflict("active draft pointer changed")

        version = (
            connection.execute(
                sa.text(
                    """
                    SELECT dataset_id, id, report_type, status,
                           data_revision, review_revision,
                           ruleset_version, sealed_at
                    FROM dataset_versions
                    WHERE dataset_id = :dataset_id
                      AND id = :version_id
                    FOR UPDATE
                    """
                ),
                {
                    "dataset_id": head.dataset_id,
                    "version_id": head.version_id,
                },
            )
            .mappings()
            .first()
        )
        if version is None:
            raise DraftPointerConflict("active draft version does not exist")
        if (
            version["status"] not in {"draft", "ready_for_publish"}
            or version["sealed_at"] is not None
        ):
            raise VersionNotEditable("active version is sealed")
        if version["status"] != head.status:
            raise DraftPointerConflict("draft pointer and version status differ")
        if (
            int(version["data_revision"]) != head.data_revision
            or int(version["review_revision"]) != head.review_revision
        ):
            raise ReviewRevisionConflict("draft revisions changed")
        if version["report_type"] != dataset["report_type"]:
            raise ReviewError("dataset and version report types differ")
        report_date = dataset["report_date"]
        if not isinstance(report_date, date):
            raise ReviewError("database returned an invalid report date")
        report_type = str(version["report_type"])
        if report_type not in {"business_report", "return_report"}:
            raise ReviewError("database returned an unsupported report type")
        ruleset_version = str(version["ruleset_version"])
        if not ruleset_version:
            raise ReviewError("database returned an empty ruleset version")
        return _LockedDraft(
            dataset_id=head.dataset_id,
            version_id=head.version_id,
            status=head.status,
            data_revision=head.data_revision,
            review_revision=head.review_revision,
            pointed_at=pointed_at,
            site_id=int(dataset["site_id"]),
            report_date=report_date,
            report_type=cast(ReportType, report_type),
            ruleset_version=ruleset_version,
        )

    @staticmethod
    def _advance_data_revision(
        connection: Connection,
        *,
        head: DraftHeadExpectation,
        occurred_at: datetime,
    ) -> _EditableVersionState:
        """Advance one data revision and demote ready state atomically.

        The caller already owns the dataset and version locks.  A ready pointer uses
        delete/update/reinsert because its redundant status foreign key is RESTRICT.
        """

        _mysql_datetime(occurred_at)
        pointed_at = _mysql_datetime(head.pointed_at)
        new_data_revision = head.data_revision + 1

        if head.status == "ready_for_publish":
            deleted = connection.execute(
                sa.text(
                    """
                    DELETE FROM dataset_drafts
                    WHERE dataset_id = :dataset_id
                      AND version_id = :version_id
                      AND version_status = :status
                      AND pointed_at = :pointed_at
                    """
                ),
                {
                    "dataset_id": head.dataset_id,
                    "version_id": head.version_id,
                    "status": head.status,
                    "pointed_at": pointed_at,
                },
            )
            if deleted.rowcount != 1:
                raise ReviewRevisionConflict(
                    "active draft pointer changed before data edit"
                )

        updated = connection.execute(
            sa.text(
                """
                UPDATE dataset_versions
                SET status = 'draft',
                    data_revision = :new_data_revision
                WHERE dataset_id = :dataset_id
                  AND id = :version_id
                  AND status = :status
                  AND data_revision = :data_revision
                  AND review_revision = :review_revision
                  AND sealed_at IS NULL
                """
            ),
            {
                "dataset_id": head.dataset_id,
                "version_id": head.version_id,
                "status": head.status,
                "data_revision": head.data_revision,
                "new_data_revision": new_data_revision,
                "review_revision": head.review_revision,
            },
        )
        if updated.rowcount != 1:
            raise ReviewRevisionConflict("draft changed before data edit")

        if head.status == "ready_for_publish":
            inserted = connection.execute(
                sa.text(
                    """
                    INSERT INTO dataset_drafts (
                        dataset_id, version_id, version_status, pointed_at
                    ) VALUES (
                        :dataset_id, :version_id, 'draft', :pointed_at
                    )
                    """
                ),
                {
                    "dataset_id": head.dataset_id,
                    "version_id": head.version_id,
                    "pointed_at": pointed_at,
                },
            )
            if inserted.rowcount != 1:
                raise ReviewRevisionConflict(
                    "active draft pointer could not be restored after data edit"
                )

        return _EditableVersionState(
            dataset_id=head.dataset_id,
            version_id=head.version_id,
            status="draft",
            data_revision=new_data_revision,
            review_revision=head.review_revision,
            pointed_at=head.pointed_at,
        )

    @staticmethod
    def _advance_review_revision(
        connection: Connection,
        *,
        head: DraftHeadExpectation,
        new_status: Literal["draft", "ready_for_publish"],
    ) -> _EditableVersionState:
        """Advance review state, rewriting the pointer only for a status change."""

        if new_status not in {"draft", "ready_for_publish"}:
            raise ValueError("new_status must be editable")
        pointed_at = _mysql_datetime(head.pointed_at)
        new_review_revision = head.review_revision + 1
        status_changes = new_status != head.status

        if status_changes:
            deleted = connection.execute(
                sa.text(
                    """
                    DELETE FROM dataset_drafts
                    WHERE dataset_id = :dataset_id
                      AND version_id = :version_id
                      AND version_status = :status
                      AND pointed_at = :pointed_at
                    """
                ),
                {
                    "dataset_id": head.dataset_id,
                    "version_id": head.version_id,
                    "status": head.status,
                    "pointed_at": pointed_at,
                },
            )
            if deleted.rowcount != 1:
                raise ReviewRevisionConflict(
                    "active draft pointer changed before review update"
                )

        updated = connection.execute(
            sa.text(
                """
                UPDATE dataset_versions
                SET status = :new_status,
                    review_revision = :new_review_revision
                WHERE dataset_id = :dataset_id
                  AND id = :version_id
                  AND status = :status
                  AND data_revision = :data_revision
                  AND review_revision = :review_revision
                  AND sealed_at IS NULL
                """
            ),
            {
                "dataset_id": head.dataset_id,
                "version_id": head.version_id,
                "status": head.status,
                "new_status": new_status,
                "data_revision": head.data_revision,
                "review_revision": head.review_revision,
                "new_review_revision": new_review_revision,
            },
        )
        if updated.rowcount != 1:
            raise ReviewRevisionConflict("draft changed before review update")

        if status_changes:
            inserted = connection.execute(
                sa.text(
                    """
                    INSERT INTO dataset_drafts (
                        dataset_id, version_id, version_status, pointed_at
                    ) VALUES (
                        :dataset_id, :version_id, :new_status, :pointed_at
                    )
                    """
                ),
                {
                    "dataset_id": head.dataset_id,
                    "version_id": head.version_id,
                    "new_status": new_status,
                    "pointed_at": pointed_at,
                },
            )
            if inserted.rowcount != 1:
                raise ReviewRevisionConflict(
                    "active draft pointer could not be restored after review update"
                )

        return _EditableVersionState(
            dataset_id=head.dataset_id,
            version_id=head.version_id,
            status=new_status,
            data_revision=head.data_revision,
            review_revision=new_review_revision,
            pointed_at=head.pointed_at,
        )

    @staticmethod
    def _store_result(
        connection: Connection,
        *,
        command: _ReviewCommand,
        result: ReviewMutationResult,
        completed_at: datetime,
    ) -> ReviewMutationResult:
        inserted = connection.execute(
            sa.text(
                """
                INSERT INTO review_operation_results (
                    operation_token, operation_kind, operation_digest,
                    actor_user_id, result_kind, result_import_batch_id,
                    result_dataset_id, result_version_id, result_status,
                    result_data_revision, result_review_revision,
                    affected_row_id, data_change_event_id,
                    issue_review_event_id, validation_run_id,
                    version_review_event_id, note_id, completed_at
                ) VALUES (
                    :operation_token, :operation_kind, :operation_digest,
                    :actor_user_id, 'applied', :result_import_batch_id,
                    :result_dataset_id, :result_version_id, :result_status,
                    :result_data_revision, :result_review_revision,
                    :affected_row_id, :data_change_event_id,
                    :issue_review_event_id, :validation_run_id,
                    :version_review_event_id, :note_id, :completed_at
                )
                """
            ),
            {
                "operation_token": command.operation_token.bytes,
                "operation_kind": command.operation_kind,
                "operation_digest": command.operation_digest,
                "actor_user_id": command.actor_user_id,
                "result_import_batch_id": result.import_batch_id,
                "result_dataset_id": result.dataset_id,
                "result_version_id": result.version_id,
                "result_status": result.status,
                "result_data_revision": result.data_revision,
                "result_review_revision": result.review_revision,
                "affected_row_id": result.affected_row_id,
                "data_change_event_id": result.data_change_event_id,
                "issue_review_event_id": result.issue_review_event_id,
                "validation_run_id": result.validation_run_id,
                "version_review_event_id": result.version_review_event_id,
                "note_id": result.note_id,
                "completed_at": _mysql_datetime(completed_at),
            },
        )
        if inserted.rowcount != 1:
            raise ReviewError("review operation result was not stored")
        return result

    @staticmethod
    def _state_result(
        *,
        command: _ReviewCommand,
        state: _EditableVersionState,
        affected_row_id: int | None = None,
        data_change_event_id: int | None = None,
        issue_review_event_id: int | None = None,
        version_review_event_id: int | None = None,
        note_id: int | None = None,
    ) -> ReviewMutationResult:
        return ReviewMutationResult(
            operation_token=command.operation_token,
            operation_kind=command.operation_kind,
            dataset_id=state.dataset_id,
            version_id=state.version_id,
            status=state.status,
            data_revision=state.data_revision,
            review_revision=state.review_revision,
            affected_row_id=affected_row_id,
            data_change_event_id=data_change_event_id,
            issue_review_event_id=issue_review_event_id,
            version_review_event_id=version_review_event_id,
            note_id=note_id,
        )

    @staticmethod
    def _database_field_value(value: object) -> FieldValue:
        if isinstance(value, datetime):
            value = _database_utc(value)
        return as_field_value(value)

    @classmethod
    def _lock_review_row(
        cls,
        connection: Connection,
        *,
        draft: _LockedDraft,
        row_id: int,
    ) -> _StoredReviewRow:
        contract = get_report_field_contract(
            draft.report_type,
            draft.ruleset_version,
        )
        typed_table = (
            "business_report_rows"
            if draft.report_type == "business_report"
            else "return_report_rows"
        )
        selected_values = ", ".join(
            f"typed.{field_name} AS value_{field_name}"
            for field_name in contract.field_names
        )
        row = (
            connection.execute(
                sa.text(
                    f"""
                    SELECT review_rows.id, review_rows.logical_row_id,
                           review_rows.row_ordinal, review_rows.row_state,
                           review_rows.base_row_id,
                           review_rows.original_parsed_source_row_id,
                           COALESCE(
                               source_attempt.batch_id,
                               (
                                   SELECT additions.source_batch_id
                                   FROM row_changes AS additions
                                   WHERE additions.version_id = review_rows.version_id
                                     AND additions.row_id = review_rows.id
                                     AND additions.operation = 'add'
                                   ORDER BY additions.id
                                   LIMIT 1
                               )
                           ) AS source_batch_id,
                           {selected_values}
                    FROM version_rows AS review_rows
                    INNER JOIN {typed_table} AS typed
                        ON typed.version_id = review_rows.version_id
                       AND typed.version_row_id = review_rows.id
                    LEFT JOIN version_base_rows AS base_rows
                        ON base_rows.version_id = review_rows.version_id
                       AND base_rows.id = review_rows.base_row_id
                    LEFT JOIN parse_baseline_rows AS source_baseline_rows
                        ON source_baseline_rows.id =
                           base_rows.source_parse_baseline_row_id
                    LEFT JOIN parse_attempts AS source_attempt
                        ON source_attempt.id = source_baseline_rows.parse_attempt_id
                    WHERE review_rows.version_id = :version_id
                      AND review_rows.id = :row_id
                      AND review_rows.report_type = :report_type
                    FOR UPDATE OF review_rows, typed
                    """
                ),
                {
                    "version_id": draft.version_id,
                    "row_id": row_id,
                    "report_type": draft.report_type,
                },
            )
            .mappings()
            .first()
        )
        if row is None:
            raise RowNotFound("processed row does not belong to the active version")
        logical_raw = _binary(
            row["logical_row_id"],
            length=16,
            label="logical row identity",
        )
        row_state = str(row["row_state"])
        if row_state not in {"active", "excluded", "deleted"}:
            raise ReviewError("database returned an unsupported row state")
        values: list[tuple[str, FieldValue]] = []
        for field in contract.fields:
            raw_value = cls._database_field_value(row[f"value_{field.name}"])
            try:
                value = validate_field_value(
                    draft.report_type,
                    draft.ruleset_version,
                    field.name,
                    raw_value,
                )
            except FieldValueError as error:
                raise ReviewError(
                    "stored row violates the frozen field contract"
                ) from error
            values.append((field.name, value))
        return _StoredReviewRow(
            row_id=int(row["id"]),
            logical_row_id=UUID(bytes=logical_raw),
            row_ordinal=int(row["row_ordinal"]),
            row_state=cast(Any, row_state),
            base_row_id=(
                int(row["base_row_id"]) if row["base_row_id"] is not None else None
            ),
            original_parsed_source_row_id=(
                int(row["original_parsed_source_row_id"])
                if row["original_parsed_source_row_id"] is not None
                else None
            ),
            source_batch_id=(
                int(row["source_batch_id"])
                if row["source_batch_id"] is not None
                else None
            ),
            values=tuple(values),
        )

    @staticmethod
    def _row_payload(row: _StoredReviewRow) -> dict[str, object]:
        return {
            "row_id": row.row_id,
            "logical_row_id": str(row.logical_row_id),
            "row_ordinal": row.row_ordinal,
            "row_state": row.row_state,
            "base_row_id": row.base_row_id,
            "source_parse_baseline_row_id": (row.original_parsed_source_row_id),
            "source_batch_id": row.source_batch_id,
            "values": {name: encode_field_value(value) for name, value in row.values},
        }

    @staticmethod
    def _insert_data_change_event(
        connection: Connection,
        *,
        draft: _LockedDraft,
        state: _EditableVersionState,
        event_kind: Literal["field", "row"],
        actor_user_id: int,
        reason: str,
        occurred_at: datetime,
    ) -> int:
        inserted = connection.execute(
            sa.text(
                """
                INSERT INTO data_change_events (
                    version_id, sequence_number, data_revision, event_kind,
                    actor_user_id, reason, occurred_at
                ) VALUES (
                    :version_id, :sequence_number, :data_revision, :event_kind,
                    :actor_user_id, :reason, :occurred_at
                )
                """
            ),
            {
                "version_id": draft.version_id,
                "sequence_number": state.data_revision,
                "data_revision": state.data_revision,
                "event_kind": event_kind,
                "actor_user_id": actor_user_id,
                "reason": reason,
                "occurred_at": _mysql_datetime(occurred_at),
            },
        )
        if inserted.lastrowid is None:
            raise ReviewError("database did not return a data change event ID")
        return int(inserted.lastrowid)

    @classmethod
    def _restore_field_value(
        cls,
        connection: Connection,
        *,
        draft: _LockedDraft,
        row: _StoredReviewRow,
        command: RestoreFieldValueCommand,
    ) -> tuple[FieldValue, int | None, int | None, int | None, str]:
        field_name = command.field_name
        source = command.source
        reference_columns: tuple[int | None, int | None, int | None]
        if isinstance(source, ParentValueSource):
            typed_table = (
                "business_report_rows"
                if draft.report_type == "business_report"
                else "return_report_rows"
            )
            found = (
                connection.execute(
                    sa.text(
                        f"""
                        SELECT typed.{field_name} AS restore_value
                        FROM version_parent_versions AS lineage
                        INNER JOIN version_rows AS parent_rows
                            ON parent_rows.version_id = lineage.parent_version_id
                           AND parent_rows.logical_row_id = :logical_row_id
                           AND parent_rows.report_type = :report_type
                        INNER JOIN {typed_table} AS typed
                            ON typed.version_id = parent_rows.version_id
                           AND typed.version_row_id = parent_rows.id
                        WHERE lineage.child_version_id = :version_id
                          AND lineage.parent_version_id = :parent_version_id
                        LIMIT 1
                        """
                    ),
                    {
                        "logical_row_id": row.logical_row_id.bytes,
                        "report_type": draft.report_type,
                        "version_id": draft.version_id,
                        "parent_version_id": source.parent_version_id,
                    },
                )
                .mappings()
                .first()
            )
            if found is None:
                raise RestoreValueUnavailable(
                    "selected parent version has no matching row value"
                )
            raw_value = cls._database_field_value(found["restore_value"])
            reference_columns = (None, source.parent_version_id, None)
            operation = "restore_parent"
        elif isinstance(source, SourceFileValueSource):
            if (
                row.original_parsed_source_row_id is None
                or row.original_parsed_source_row_id != source.parsed_source_row_id
                or row.source_batch_id != source.source_batch_id
            ):
                raise RestoreValueUnavailable(
                    "selected source row does not match row provenance"
                )
            typed_table = (
                "business_parse_baseline_rows"
                if draft.report_type == "business_report"
                else "return_parse_baseline_rows"
            )
            found = (
                connection.execute(
                    sa.text(
                        f"""
                        SELECT typed.{field_name} AS restore_value
                        FROM version_rows AS current_rows
                        INNER JOIN version_base_rows AS base_rows
                            ON base_rows.version_id = current_rows.version_id
                           AND base_rows.id = current_rows.base_row_id
                        INNER JOIN parse_baseline_rows AS source_rows
                            ON source_rows.id =
                               base_rows.source_parse_baseline_row_id
                        INNER JOIN parse_attempts AS attempts
                            ON attempts.id = source_rows.parse_attempt_id
                        INNER JOIN {typed_table} AS typed
                            ON typed.parse_baseline_id =
                               source_rows.parse_baseline_id
                           AND typed.parse_baseline_row_id = source_rows.id
                        WHERE current_rows.version_id = :version_id
                          AND current_rows.id = :row_id
                          AND current_rows.original_parsed_source_row_id =
                              :parsed_source_row_id
                          AND source_rows.parsed_source_row_id =
                              :parsed_source_row_id
                          AND attempts.batch_id = :source_batch_id
                        LIMIT 1
                        """
                    ),
                    {
                        "version_id": draft.version_id,
                        "row_id": row.row_id,
                        "parsed_source_row_id": source.parsed_source_row_id,
                        "source_batch_id": source.source_batch_id,
                    },
                )
                .mappings()
                .first()
            )
            if found is None:
                raise RestoreValueUnavailable(
                    "selected source file value is unavailable"
                )
            raw_value = cls._database_field_value(found["restore_value"])
            reference_columns = (None, None, source.parsed_source_row_id)
            operation = "restore_source"
        else:
            found = (
                connection.execute(
                    sa.text(
                        """
                        SELECT changes.before_value_json
                        FROM field_changes AS changes
                        INNER JOIN data_change_events AS events
                            ON events.version_id = changes.version_id
                           AND events.id = changes.id
                        WHERE changes.version_id = :version_id
                          AND changes.id = :field_change_id
                          AND changes.row_id = :row_id
                          AND changes.field_name = :field_name
                          AND events.data_revision <= :data_revision
                        LIMIT 1
                        """
                    ),
                    {
                        "version_id": draft.version_id,
                        "field_change_id": source.field_change_id,
                        "row_id": row.row_id,
                        "field_name": field_name,
                        "data_revision": draft.data_revision,
                    },
                )
                .mappings()
                .first()
            )
            if found is None:
                raise RestoreValueUnavailable(
                    "selected previous field change is unavailable"
                )
            try:
                raw_value = decode_field_value(
                    _json_object(
                        found["before_value_json"],
                        label="previous field value",
                    )
                )
            except FieldValueError as error:
                raise ReviewError("stored previous field value is invalid") from error
            reference_columns = (source.field_change_id, None, None)
            operation = "restore_previous"

        try:
            value = validate_field_value(
                draft.report_type,
                draft.ruleset_version,
                field_name,
                raw_value,
            )
        except FieldValueError as error:
            raise RestoreValueUnavailable(
                "selected restore value violates the field contract"
            ) from error
        previous_id, parent_id, source_row_id = reference_columns
        return value, previous_id, parent_id, source_row_id, operation

    @classmethod
    def _change_field(
        cls,
        connection: Connection,
        *,
        actor: _Actor,
        command: SetFieldValueCommand | RestoreFieldValueCommand,
        occurred_at: datetime,
        restore: bool,
    ) -> ReviewMutationResult:
        draft = cls._lock_active_head(connection, command.head)
        row = cls._lock_review_row(
            connection,
            draft=draft,
            row_id=command.row_id,
        )
        if row.row_state != "active":
            raise RowStateConflict("only an active row can be edited")
        try:
            field_contract = get_field_contract(
                draft.report_type,
                draft.ruleset_version,
                command.field_name,
            )
        except FieldContractError as error:
            raise FieldNotEditable("field is not part of this report") from error
        if not field_contract.editable:
            raise FieldNotEditable("field is derived and cannot be edited")
        before_value = dict(row.values)[command.field_name]

        restored_field_change_id: int | None = None
        restored_parent_version_id: int | None = None
        restored_source_row_id: int | None = None
        operation = "set"
        if restore:
            if not isinstance(command, RestoreFieldValueCommand):
                raise ReviewError("restore command shape is invalid")
            (
                after_value,
                restored_field_change_id,
                restored_parent_version_id,
                restored_source_row_id,
                operation,
            ) = cls._restore_field_value(
                connection,
                draft=draft,
                row=row,
                command=command,
            )
        else:
            if not isinstance(command, SetFieldValueCommand):
                raise ReviewError("set command shape is invalid")
            try:
                after_value = validate_field_value(
                    draft.report_type,
                    draft.ruleset_version,
                    command.field_name,
                    command.value,
                )
            except FieldValueError as error:
                raise FieldValueInvalid("new field value is invalid") from error

        if encode_field_value(before_value) == encode_field_value(after_value):
            raise FieldValueInvalid("new field value does not change the row")

        state = cls._advance_data_revision(
            connection,
            head=command.head,
            occurred_at=occurred_at,
        )
        typed_table = (
            "business_report_rows"
            if draft.report_type == "business_report"
            else "return_report_rows"
        )
        updated = connection.execute(
            sa.text(
                f"""
                UPDATE {typed_table}
                SET {command.field_name} = :after_value
                WHERE version_id = :version_id
                  AND version_row_id = :row_id
                  AND {command.field_name} <=> :before_value
                """
            ),
            {
                "after_value": field_value_to_database(after_value),
                "version_id": draft.version_id,
                "row_id": row.row_id,
                "before_value": field_value_to_database(before_value),
            },
        )
        if updated.rowcount != 1:
            raise ReviewRevisionConflict("row value changed before the edit")
        if command.field_name == "sku":
            if not isinstance(after_value, str):
                raise ReviewError("Seller SKU field is not text")
            append_report_source_key(
                connection,
                dataset_id=draft.dataset_id,
                version_id=draft.version_id,
                source_row_id=row.row_id,
                report_type=draft.report_type,
                seller_sku_raw=after_value,
                source_key_revision=state.data_revision,
                occurred_at=occurred_at,
            )
        connection.execute(
            sa.text(
                """
                UPDATE version_rows
                SET updated_at = :updated_at
                WHERE version_id = :version_id AND id = :row_id
                """
            ),
            {
                "updated_at": _mysql_datetime(occurred_at),
                "version_id": draft.version_id,
                "row_id": row.row_id,
            },
        )
        event_id = cls._insert_data_change_event(
            connection,
            draft=draft,
            state=state,
            event_kind="field",
            actor_user_id=actor.user_id,
            reason=command.reason,
            occurred_at=occurred_at,
        )
        inserted = connection.execute(
            sa.text(
                """
                INSERT INTO field_changes (
                    id, version_id, row_id, field_name, operation,
                    before_value_json, after_value_json, event_kind,
                    restored_field_change_id, restored_parent_version_id,
                    restored_source_row_id
                ) VALUES (
                    :id, :version_id, :row_id, :field_name, :operation,
                    :before_value_json, :after_value_json, 'field',
                    :restored_field_change_id, :restored_parent_version_id,
                    :restored_source_row_id
                )
                """
            ),
            {
                "id": event_id,
                "version_id": draft.version_id,
                "row_id": row.row_id,
                "field_name": command.field_name,
                "operation": operation,
                "before_value_json": _canonical_json(encode_field_value(before_value)),
                "after_value_json": _canonical_json(encode_field_value(after_value)),
                "restored_field_change_id": restored_field_change_id,
                "restored_parent_version_id": restored_parent_version_id,
                "restored_source_row_id": restored_source_row_id,
            },
        )
        if inserted.rowcount != 1:
            raise ReviewError("field change event was not stored")
        result = cls._state_result(
            command=command,
            state=state,
            affected_row_id=row.row_id,
            data_change_event_id=event_id,
        )
        return cls._store_result(
            connection,
            command=command,
            result=result,
            completed_at=occurred_at,
        )

    @classmethod
    def _add_row(
        cls,
        connection: Connection,
        *,
        actor: _Actor,
        command: AddRowCommand,
        occurred_at: datetime,
    ) -> ReviewMutationResult:
        draft = cls._lock_active_head(connection, command.head)
        batch = connection.execute(
            sa.text(
                """
                SELECT batch_id
                FROM version_input_batches
                WHERE version_id = :version_id AND batch_id = :batch_id
                FOR SHARE
                """
            ),
            {
                "version_id": draft.version_id,
                "batch_id": command.source_batch_id,
            },
        ).first()
        if batch is None:
            raise RowStateConflict(
                "manual row source batch is not an input to this version"
            )
        try:
            validated = validate_added_row_values(
                draft.report_type,
                draft.ruleset_version,
                command.values,
            )
        except (FieldContractError, FieldValueError) as error:
            raise FieldValueInvalid("manual row values are invalid") from error

        max_ordinal = connection.scalar(
            sa.text(
                """
                SELECT COALESCE(MAX(row_ordinal), 0)
                FROM version_rows
                WHERE version_id = :version_id
                """
            ),
            {"version_id": draft.version_id},
        )
        if isinstance(max_ordinal, bool) or not isinstance(max_ordinal, (int, Decimal)):
            raise ReviewError("database returned an invalid row ordinal")
        ordinal_value = Decimal(max_ordinal)
        if ordinal_value < 0 or ordinal_value != ordinal_value.to_integral_value():
            raise ReviewError("database returned an invalid row ordinal")
        state = cls._advance_data_revision(
            connection,
            head=command.head,
            occurred_at=occurred_at,
        )
        row_ordinal = int(ordinal_value) + 1
        inserted_row = connection.execute(
            sa.text(
                """
                INSERT INTO version_rows (
                    version_id, report_type, logical_row_id, row_ordinal,
                    row_state, base_row_id, original_parsed_source_row_id,
                    created_at, updated_at
                ) VALUES (
                    :version_id, :report_type, :logical_row_id, :row_ordinal,
                    'active', NULL, NULL, :created_at, :updated_at
                )
                """
            ),
            {
                "version_id": draft.version_id,
                "report_type": draft.report_type,
                "logical_row_id": command.operation_token.bytes,
                "row_ordinal": row_ordinal,
                "created_at": _mysql_datetime(occurred_at),
                "updated_at": _mysql_datetime(occurred_at),
            },
        )
        if inserted_row.lastrowid is None:
            raise ReviewError("database did not return a version row ID")
        row_id = int(inserted_row.lastrowid)
        contract = get_report_field_contract(
            draft.report_type,
            draft.ruleset_version,
        )
        typed_table = (
            "business_report_rows"
            if draft.report_type == "business_report"
            else "return_report_rows"
        )
        columns = ", ".join(contract.field_names)
        placeholders = ", ".join(f":value_{name}" for name in contract.field_names)
        values = dict(validated)
        inserted_typed = connection.execute(
            sa.text(
                f"""
                INSERT INTO {typed_table} (
                    version_row_id, version_id, {columns}
                ) VALUES (
                    :row_id, :version_id, {placeholders}
                )
                """
            ),
            {
                "row_id": row_id,
                "version_id": draft.version_id,
                **{
                    f"value_{name}": field_value_to_database(values[name])
                    for name in contract.field_names
                },
            },
        )
        if inserted_typed.rowcount != 1:
            raise ReviewError("typed manual row was not stored")
        seller_sku = values.get("sku")
        if not isinstance(seller_sku, str):
            raise ReviewError("manual report row has no Seller SKU")
        append_report_source_key(
            connection,
            dataset_id=draft.dataset_id,
            version_id=draft.version_id,
            source_row_id=row_id,
            report_type=draft.report_type,
            seller_sku_raw=seller_sku,
            source_key_revision=state.data_revision,
            occurred_at=occurred_at,
        )
        stored_row = _StoredReviewRow(
            row_id=row_id,
            logical_row_id=command.operation_token,
            row_ordinal=row_ordinal,
            row_state="active",
            base_row_id=None,
            original_parsed_source_row_id=None,
            source_batch_id=command.source_batch_id,
            values=tuple(validated),
        )
        event_id = cls._insert_data_change_event(
            connection,
            draft=draft,
            state=state,
            event_kind="row",
            actor_user_id=actor.user_id,
            reason=command.reason,
            occurred_at=occurred_at,
        )
        inserted_change = connection.execute(
            sa.text(
                """
                INSERT INTO row_changes (
                    id, version_id, row_id, operation, source_batch_id,
                    before_value_json, after_value_json, event_kind
                ) VALUES (
                    :id, :version_id, :row_id, 'add', :source_batch_id,
                    :before_value_json, :after_value_json, 'row'
                )
                """
            ),
            {
                "id": event_id,
                "version_id": draft.version_id,
                "row_id": row_id,
                "source_batch_id": command.source_batch_id,
                "before_value_json": _canonical_json(None),
                "after_value_json": _canonical_json(cls._row_payload(stored_row)),
            },
        )
        if inserted_change.rowcount != 1:
            raise ReviewError("manual row change event was not stored")
        result = cls._state_result(
            command=command,
            state=state,
            affected_row_id=row_id,
            data_change_event_id=event_id,
        )
        return cls._store_result(
            connection,
            command=command,
            result=result,
            completed_at=occurred_at,
        )

    @classmethod
    def _change_row_state(
        cls,
        connection: Connection,
        *,
        actor: _Actor,
        command: ChangeRowStateCommand,
        occurred_at: datetime,
    ) -> ReviewMutationResult:
        draft = cls._lock_active_head(connection, command.head)
        row = cls._lock_review_row(
            connection,
            draft=draft,
            row_id=command.row_id,
        )
        if command.operation == "exclude":
            if row.row_state != "active":
                raise RowStateConflict("only an active row can be excluded")
            new_state: Literal["active", "excluded", "deleted"] = "excluded"
        elif command.operation == "restore":
            if row.row_state not in {"excluded", "deleted"}:
                raise RowStateConflict(
                    "only an excluded or deleted row can be restored"
                )
            if row.row_state == "deleted" and row.base_row_id is not None:
                raise RowStateConflict("source rows cannot be restored from deleted")
            new_state = "active"
        else:
            if row.base_row_id is not None:
                raise RowStateConflict(
                    "source-derived rows must be excluded rather than deleted"
                )
            if row.row_state not in {"active", "excluded"}:
                raise RowStateConflict(
                    "only an active or excluded manual row can be deleted"
                )
            new_state = "deleted"

        state = cls._advance_data_revision(
            connection,
            head=command.head,
            occurred_at=occurred_at,
        )
        changed = connection.execute(
            sa.text(
                """
                UPDATE version_rows
                SET row_state = :new_state, updated_at = :updated_at
                WHERE version_id = :version_id
                  AND id = :row_id
                  AND row_state = :old_state
                """
            ),
            {
                "new_state": new_state,
                "updated_at": _mysql_datetime(occurred_at),
                "version_id": draft.version_id,
                "row_id": row.row_id,
                "old_state": row.row_state,
            },
        )
        if changed.rowcount != 1:
            raise ReviewRevisionConflict("row state changed before the edit")
        if new_state == "active":
            seller_sku = dict(row.values).get("sku")
            if not isinstance(seller_sku, str):
                raise ReviewError("restored report row has no Seller SKU")
            append_report_source_key(
                connection,
                dataset_id=draft.dataset_id,
                version_id=draft.version_id,
                source_row_id=row.row_id,
                report_type=draft.report_type,
                seller_sku_raw=seller_sku,
                source_key_revision=state.data_revision,
                occurred_at=occurred_at,
            )
        after_row = replace(row, row_state=new_state)
        event_id = cls._insert_data_change_event(
            connection,
            draft=draft,
            state=state,
            event_kind="row",
            actor_user_id=actor.user_id,
            reason=command.reason,
            occurred_at=occurred_at,
        )
        inserted = connection.execute(
            sa.text(
                """
                INSERT INTO row_changes (
                    id, version_id, row_id, operation, source_batch_id,
                    before_value_json, after_value_json, event_kind
                ) VALUES (
                    :id, :version_id, :row_id, :operation, NULL,
                    :before_value_json, :after_value_json, 'row'
                )
                """
            ),
            {
                "id": event_id,
                "version_id": draft.version_id,
                "row_id": row.row_id,
                "operation": command.operation,
                "before_value_json": _canonical_json(cls._row_payload(row)),
                "after_value_json": _canonical_json(cls._row_payload(after_row)),
            },
        )
        if inserted.rowcount != 1:
            raise ReviewError("row state change event was not stored")
        result = cls._state_result(
            command=command,
            state=state,
            affected_row_id=row.row_id,
            data_change_event_id=event_id,
        )
        return cls._store_result(
            connection,
            command=command,
            result=result,
            completed_at=occurred_at,
        )

    @staticmethod
    def _note_target_columns(
        target: (
            ImportBatchNoteTarget | VersionNoteTarget | RowNoteTarget | FieldNoteTarget
        ),
    ) -> dict[str, object]:
        if isinstance(target, ImportBatchNoteTarget):
            return {
                "target_type": "import_batch",
                "import_batch_id": target.import_batch_id,
                "version_id": None,
                "row_id": None,
                "field_name": None,
            }
        if isinstance(target, VersionNoteTarget):
            return {
                "target_type": "version",
                "import_batch_id": None,
                "version_id": target.version_id,
                "row_id": None,
                "field_name": None,
            }
        if isinstance(target, RowNoteTarget):
            return {
                "target_type": "row",
                "import_batch_id": None,
                "version_id": target.version_id,
                "row_id": target.row_id,
                "field_name": None,
            }
        return {
            "target_type": "field",
            "import_batch_id": None,
            "version_id": target.version_id,
            "row_id": target.row_id,
            "field_name": target.field_name,
        }

    @classmethod
    def _lock_note_version(
        cls,
        connection: Connection,
        *,
        target: VersionNoteTarget | RowNoteTarget | FieldNoteTarget,
        expected_review_revision: int,
    ) -> tuple[_LockedDraft, DraftHeadExpectation]:
        candidate = (
            connection.execute(
                sa.text(
                    """
                    SELECT versions.dataset_id, versions.id AS version_id,
                           versions.status, versions.data_revision,
                           versions.review_revision, drafts.pointed_at
                    FROM dataset_versions AS versions
                    INNER JOIN dataset_drafts AS drafts
                        ON drafts.dataset_id = versions.dataset_id
                       AND drafts.version_id = versions.id
                       AND drafts.version_status = versions.status
                    WHERE versions.id = :version_id
                    LIMIT 1
                    """
                ),
                {"version_id": target.version_id},
            )
            .mappings()
            .first()
        )
        if candidate is None:
            raise VersionNotEditable("note target is not an active draft")
        status = str(candidate["status"])
        if status not in {"draft", "ready_for_publish"}:
            raise VersionNotEditable("note target is not editable")
        actual_review_revision = int(candidate["review_revision"])
        if actual_review_revision != expected_review_revision:
            raise ReviewRevisionConflict("note target review revision changed")
        head = DraftHeadExpectation(
            dataset_id=int(candidate["dataset_id"]),
            version_id=int(candidate["version_id"]),
            status=cast(Any, status),
            data_revision=int(candidate["data_revision"]),
            review_revision=actual_review_revision,
            pointed_at=_database_utc(candidate["pointed_at"]),
        )
        draft = cls._lock_active_head(connection, head)
        if isinstance(target, (RowNoteTarget, FieldNoteTarget)):
            cls._lock_review_row(
                connection,
                draft=draft,
                row_id=target.row_id,
            )
        if isinstance(target, FieldNoteTarget):
            try:
                get_field_contract(
                    draft.report_type,
                    draft.ruleset_version,
                    target.field_name,
                )
            except FieldContractError as error:
                raise FieldNotEditable(
                    "note field is not part of this report"
                ) from error
        return draft, head

    @staticmethod
    def _insert_note_revision(
        connection: Connection,
        *,
        note_key: str,
        revision_number: int,
        supersedes_note_id: int | None,
        supersedes_revision_number: int | None,
        visibility: str,
        body: str,
        actor_user_id: int,
        review_revision: int | None,
        occurred_at: datetime,
    ) -> int:
        inserted = connection.execute(
            sa.text(
                """
                INSERT INTO notes (
                    note_key, revision_number, supersedes_note_id,
                    supersedes_revision_number, visibility, body,
                    author_user_id, review_revision, created_at
                ) VALUES (
                    :note_key, :revision_number, :supersedes_note_id,
                    :supersedes_revision_number, :visibility, :body,
                    :actor_user_id, :review_revision, :created_at
                )
                """
            ),
            {
                "note_key": note_key,
                "revision_number": revision_number,
                "supersedes_note_id": supersedes_note_id,
                "supersedes_revision_number": supersedes_revision_number,
                "visibility": visibility,
                "body": body,
                "actor_user_id": actor_user_id,
                "review_revision": review_revision,
                "created_at": _mysql_datetime(occurred_at),
            },
        )
        if inserted.lastrowid is None:
            raise ReviewError("database did not return a note ID")
        return int(inserted.lastrowid)

    @classmethod
    def _create_note(
        cls,
        connection: Connection,
        *,
        actor: _Actor,
        command: CreateNoteCommand,
        occurred_at: datetime,
    ) -> ReviewMutationResult:
        columns = cls._note_target_columns(command.target)
        state: _EditableVersionState | None = None
        if isinstance(command.target, ImportBatchNoteTarget):
            exists = connection.execute(
                sa.text(
                    """
                    SELECT id
                    FROM import_batches
                    WHERE id = :import_batch_id
                    FOR SHARE
                    """
                ),
                {"import_batch_id": command.target.import_batch_id},
            ).first()
            if exists is None:
                raise RowNotFound("note import batch does not exist")
        else:
            assert command.expected_review_revision is not None
            _draft, head = cls._lock_note_version(
                connection,
                target=command.target,
                expected_review_revision=command.expected_review_revision,
            )
            state = cls._advance_review_revision(
                connection,
                head=head,
                new_status=head.status,
            )

        note_key = f"review-{command.operation_token.hex}"
        inserted_thread = connection.execute(
            sa.text(
                """
                INSERT INTO note_threads (
                    note_key, target_type, import_batch_id, version_id,
                    row_id, field_name, created_at
                ) VALUES (
                    :note_key, :target_type, :import_batch_id, :version_id,
                    :row_id, :field_name, :created_at
                )
                """
            ),
            {
                "note_key": note_key,
                **columns,
                "created_at": _mysql_datetime(occurred_at),
            },
        )
        if inserted_thread.rowcount != 1:
            raise ReviewError("note thread was not stored")
        note_id = cls._insert_note_revision(
            connection,
            note_key=note_key,
            revision_number=1,
            supersedes_note_id=None,
            supersedes_revision_number=None,
            visibility=command.visibility,
            body=command.body,
            actor_user_id=actor.user_id,
            review_revision=(state.review_revision if state is not None else None),
            occurred_at=occurred_at,
        )
        if state is None:
            assert isinstance(command.target, ImportBatchNoteTarget)
            result = ReviewMutationResult(
                operation_token=command.operation_token,
                operation_kind=command.operation_kind,
                import_batch_id=command.target.import_batch_id,
                dataset_id=None,
                version_id=None,
                status=None,
                data_revision=None,
                review_revision=None,
                note_id=note_id,
            )
        else:
            result = cls._state_result(
                command=command,
                state=state,
                note_id=note_id,
            )
        return cls._store_result(
            connection,
            command=command,
            result=result,
            completed_at=occurred_at,
        )

    @classmethod
    def _revise_note(
        cls,
        connection: Connection,
        *,
        actor: _Actor,
        command: ReviseNoteCommand,
        occurred_at: datetime,
    ) -> ReviewMutationResult:
        columns = cls._note_target_columns(command.target)
        state: _EditableVersionState | None = None
        if not isinstance(command.target, ImportBatchNoteTarget):
            assert command.expected_review_revision is not None
            _draft, head = cls._lock_note_version(
                connection,
                target=command.target,
                expected_review_revision=command.expected_review_revision,
            )
        else:
            head = None
        thread = (
            connection.execute(
                sa.text(
                    """
                    SELECT target_type, import_batch_id, version_id,
                           row_id, field_name
                    FROM note_threads
                    WHERE note_key = :note_key
                    FOR SHARE
                    """
                ),
                {"note_key": command.note_key},
            )
            .mappings()
            .first()
        )
        if thread is None:
            raise NoteRevisionConflict("note thread does not exist")
        for name, expected in columns.items():
            actual = thread[name]
            if actual is not None and name in {
                "import_batch_id",
                "version_id",
                "row_id",
            }:
                actual = int(actual)
            if actual != expected:
                raise NoteRevisionConflict("note thread target changed")
        latest = (
            connection.execute(
                sa.text(
                    """
                    SELECT id, revision_number
                    FROM notes
                    WHERE note_key = :note_key
                    ORDER BY revision_number DESC, id DESC
                    LIMIT 1
                    FOR SHARE
                    """
                ),
                {"note_key": command.note_key},
            )
            .mappings()
            .first()
        )
        if latest is None or (
            int(latest["id"]) != command.expected_note_id
            or int(latest["revision_number"]) != command.expected_revision_number
        ):
            raise NoteRevisionConflict("note thread head changed")
        if head is not None:
            state = cls._advance_review_revision(
                connection,
                head=head,
                new_status=head.status,
            )
        note_id = cls._insert_note_revision(
            connection,
            note_key=command.note_key,
            revision_number=command.expected_revision_number + 1,
            supersedes_note_id=command.expected_note_id,
            supersedes_revision_number=command.expected_revision_number,
            visibility=command.visibility,
            body=command.body,
            actor_user_id=actor.user_id,
            review_revision=(state.review_revision if state is not None else None),
            occurred_at=occurred_at,
        )
        if state is None:
            assert isinstance(command.target, ImportBatchNoteTarget)
            result = ReviewMutationResult(
                operation_token=command.operation_token,
                operation_kind=command.operation_kind,
                import_batch_id=command.target.import_batch_id,
                dataset_id=None,
                version_id=None,
                status=None,
                data_revision=None,
                review_revision=None,
                note_id=note_id,
            )
        else:
            result = cls._state_result(
                command=command,
                state=state,
                note_id=note_id,
            )
        return cls._store_result(
            connection,
            command=command,
            result=result,
            completed_at=occurred_at,
        )

    @classmethod
    def _review_issue(
        cls,
        connection: Connection,
        *,
        actor: _Actor,
        command: ReviewIssueCommand,
        occurred_at: datetime,
    ) -> ReviewMutationResult:
        draft = cls._lock_active_head(connection, command.head)
        issue = (
            connection.execute(
                sa.text(
                    """
                    SELECT runs.run_type, runs.data_revision,
                           runs.ruleset_version, runs.status AS run_status,
                           issues.severity, issues.requires_note
                    FROM validation_runs AS runs
                    INNER JOIN validation_issues AS issues
                        ON issues.version_id = runs.version_id
                       AND issues.validation_run_id = runs.id
                    WHERE runs.version_id = :version_id
                      AND runs.id = :validation_run_id
                      AND issues.id = :validation_issue_id
                    FOR SHARE
                    """
                ),
                {
                    "version_id": draft.version_id,
                    "validation_run_id": command.validation_run_id,
                    "validation_issue_id": command.validation_issue_id,
                },
            )
            .mappings()
            .first()
        )
        if issue is None:
            raise IssueReviewConflict("validation issue does not exist")
        if (
            issue["run_type"] != "full"
            or issue["run_status"] != "succeeded"
            or int(issue["data_revision"]) != draft.data_revision
            or str(issue["ruleset_version"]) != draft.ruleset_version
        ):
            raise StaleValidationRun("validation issue is not from the current run")
        if (
            str(issue["severity"]) != command.issue_severity
            or bool(issue["requires_note"]) is not command.issue_requires_note
        ):
            raise IssueReviewConflict("validation issue shape changed")
        previous = (
            connection.execute(
                sa.text(
                    """
                    SELECT sequence_number, event_type
                    FROM issue_review_events
                    WHERE version_id = :version_id
                      AND validation_run_id = :validation_run_id
                      AND validation_issue_id = :validation_issue_id
                    ORDER BY sequence_number DESC, id DESC
                    LIMIT 1
                    FOR SHARE
                    """
                ),
                {
                    "version_id": draft.version_id,
                    "validation_run_id": command.validation_run_id,
                    "validation_issue_id": command.validation_issue_id,
                },
            )
            .mappings()
            .first()
        )
        previous_type = str(previous["event_type"]) if previous is not None else None
        if command.action == "acknowledge" and previous is not None:
            raise IssueReviewConflict("warning has already been acknowledged")
        if command.action == "resolve" and previous_type not in {None, "reopen"}:
            raise IssueReviewConflict("blocking issue is not open")
        if command.action == "reopen" and previous_type != "resolve":
            raise IssueReviewConflict("only a resolved issue can be reopened")
        sequence_number = (
            int(previous["sequence_number"]) + 1 if previous is not None else 1
        )
        state = cls._advance_review_revision(
            connection,
            head=command.head,
            new_status=command.head.status,
        )
        inserted = connection.execute(
            sa.text(
                """
                INSERT INTO issue_review_events (
                    version_id, validation_run_id, validation_issue_id,
                    sequence_number, review_revision, event_type,
                    actor_user_id, comment, redacted_payload, occurred_at,
                    issue_severity, issue_requires_note
                ) VALUES (
                    :version_id, :validation_run_id, :validation_issue_id,
                    :sequence_number, :review_revision, :event_type,
                    :actor_user_id, :comment, NULL, :occurred_at,
                    :issue_severity, :issue_requires_note
                )
                """
            ),
            {
                "version_id": draft.version_id,
                "validation_run_id": command.validation_run_id,
                "validation_issue_id": command.validation_issue_id,
                "sequence_number": sequence_number,
                "review_revision": state.review_revision,
                "event_type": command.action,
                "actor_user_id": actor.user_id,
                "comment": command.comment,
                "occurred_at": _mysql_datetime(occurred_at),
                "issue_severity": command.issue_severity,
                "issue_requires_note": command.issue_requires_note,
            },
        )
        if inserted.lastrowid is None:
            raise ReviewError("database did not return an issue review event ID")
        event_id = int(inserted.lastrowid)
        result = cls._state_result(
            command=command,
            state=state,
            issue_review_event_id=event_id,
        )
        return cls._store_result(
            connection,
            command=command,
            result=result,
            completed_at=occurred_at,
        )

    @staticmethod
    def _validation_confirmation(
        *,
        draft: _LockedDraft,
        command: MarkReadyCommand,
        run: Mapping[str, object],
    ) -> tuple[str, bytes]:
        if (
            run["run_type"] != "full"
            or run["status"] != "succeeded"
            or run["result"] != "passed"
            or int(cast(Any, run["data_revision"])) != draft.data_revision
            or str(run["ruleset_version"]) != draft.ruleset_version
        ):
            raise StaleValidationRun("selected validation run is not publishable")
        data_digest = _binary(
            run["data_digest"],
            length=32,
            label="validation data digest",
        )
        if not hmac.compare_digest(data_digest, command.validation_data_digest):
            raise StaleValidationRun("validation data digest changed")
        summary = _json_object(run["summary_json"], label="validation summary")
        if summary.get("schema_version") != 1:
            raise StaleValidationRun("validation summary schema is unsupported")
        if (
            summary.get("report_date") != draft.report_date.isoformat()
            or summary.get("report_type") != draft.report_type
            or command.confirmed_report_date != draft.report_date
            or command.confirmed_report_type != draft.report_type
        ):
            raise StaleValidationRun("report identity confirmation does not match")
        row_count = summary.get("row_count")
        if isinstance(row_count, bool) or not isinstance(row_count, int):
            raise StaleValidationRun("validation row count is invalid")
        if row_count != command.confirmed_row_count:
            raise StaleValidationRun("confirmed row count does not match validation")
        raw_totals = summary.get("totals")
        if not isinstance(raw_totals, Mapping):
            raise StaleValidationRun("validation totals are invalid")
        totals: list[tuple[str, str]] = []
        for raw_name, raw_value in raw_totals.items():
            if not isinstance(raw_name, str) or not raw_name:
                raise StaleValidationRun("validation total name is invalid")
            totals.append(
                (
                    raw_name,
                    _canonical_decimal(raw_value, label=f"total {raw_name}"),
                )
            )
        canonical_totals = tuple(sorted(totals))
        if canonical_totals != command.confirmed_totals:
            raise StaleValidationRun("confirmed totals do not match validation")
        confirmation = {
            "validation_run_id": command.validation_run_id,
            "validation_data_digest": command.validation_data_digest.hex(),
            "ruleset_version": command.ruleset_version,
            "confirmed_report_date": command.confirmed_report_date.isoformat(),
            "confirmed_report_type": command.confirmed_report_type,
            "confirmed_row_count": command.confirmed_row_count,
            "confirmed_totals": {
                name: value for name, value in command.confirmed_totals
            },
        }
        serialised = _canonical_json(confirmation)
        return serialised, hashlib.sha256(serialised.encode("utf-8")).digest()

    @classmethod
    def _mark_ready(
        cls,
        connection: Connection,
        *,
        actor: _Actor,
        command: MarkReadyCommand,
        occurred_at: datetime,
    ) -> ReviewMutationResult:
        draft = cls._lock_active_head(connection, command.head)
        if draft.status != "draft":
            raise VersionNotEditable("only a draft can be marked ready")
        latest = (
            connection.execute(
                sa.text(
                    """
                    SELECT id, run_type, data_revision, ruleset_version,
                           status, result, data_digest, summary_json
                    FROM validation_runs
                    WHERE version_id = :version_id AND run_type = 'full'
                    ORDER BY id DESC
                    LIMIT 1
                    FOR SHARE
                    """
                ),
                {"version_id": draft.version_id},
            )
            .mappings()
            .first()
        )
        if latest is None or int(latest["id"]) != command.validation_run_id:
            raise StaleValidationRun("selected validation is not the latest full run")
        if command.ruleset_version != draft.ruleset_version:
            raise StaleValidationRun("confirmed ruleset does not match the version")
        confirmation_json, confirmation_digest = cls._validation_confirmation(
            draft=draft,
            command=command,
            run=cast(Mapping[str, object], latest),
        )
        blocking_count = connection.scalar(
            sa.text(
                """
                SELECT COUNT(*)
                FROM validation_issues
                WHERE version_id = :version_id
                  AND validation_run_id = :validation_run_id
                  AND severity = 'blocking'
                """
            ),
            {
                "version_id": draft.version_id,
                "validation_run_id": command.validation_run_id,
            },
        )
        if int(blocking_count or 0) != 0:
            raise StaleValidationRun("blocking validation issues cannot be waived")
        unacknowledged = connection.scalar(
            sa.text(
                """
                SELECT COUNT(*)
                FROM validation_issues AS issues
                WHERE issues.version_id = :version_id
                  AND issues.validation_run_id = :validation_run_id
                  AND issues.severity = 'warning'
                  AND NOT EXISTS (
                      SELECT 1
                      FROM issue_review_events AS reviews
                      WHERE reviews.version_id = issues.version_id
                        AND reviews.validation_run_id = issues.validation_run_id
                        AND reviews.validation_issue_id = issues.id
                        AND reviews.event_type = 'acknowledge'
                  )
                """
            ),
            {
                "version_id": draft.version_id,
                "validation_run_id": command.validation_run_id,
            },
        )
        if int(unacknowledged or 0) != 0:
            raise StaleValidationRun("all validation warnings must be acknowledged")

        state = cls._advance_review_revision(
            connection,
            head=command.head,
            new_status="ready_for_publish",
        )
        inserted = connection.execute(
            sa.text(
                """
                INSERT INTO version_review_events (
                    operation_token, operation_kind, operation_digest,
                    actor_user_id, dataset_id, version_id,
                    from_status, to_status, data_revision,
                    from_review_revision, to_review_revision,
                    selected_validation_run_id, confirmation_digest,
                    confirmation_json, reason, occurred_at
                ) VALUES (
                    :operation_token, :operation_kind, :operation_digest,
                    :actor_user_id, :dataset_id, :version_id,
                    'draft', 'ready_for_publish', :data_revision,
                    :from_review_revision, :to_review_revision,
                    :selected_validation_run_id, :confirmation_digest,
                    :confirmation_json, :reason, :occurred_at
                )
                """
            ),
            {
                "operation_token": command.operation_token.bytes,
                "operation_kind": command.operation_kind,
                "operation_digest": command.operation_digest,
                "actor_user_id": actor.user_id,
                "dataset_id": draft.dataset_id,
                "version_id": draft.version_id,
                "data_revision": draft.data_revision,
                "from_review_revision": draft.review_revision,
                "to_review_revision": state.review_revision,
                "selected_validation_run_id": command.validation_run_id,
                "confirmation_digest": confirmation_digest,
                "confirmation_json": confirmation_json,
                "reason": command.reason,
                "occurred_at": _mysql_datetime(occurred_at),
            },
        )
        if inserted.lastrowid is None:
            raise ReviewError("database did not return a version review event ID")
        event_id = int(inserted.lastrowid)
        result = cls._state_result(
            command=command,
            state=state,
            version_review_event_id=event_id,
        )
        return cls._store_result(
            connection,
            command=command,
            result=result,
            completed_at=occurred_at,
        )

    @classmethod
    def _return_to_draft(
        cls,
        connection: Connection,
        *,
        actor: _Actor,
        command: ReturnToDraftCommand,
        occurred_at: datetime,
    ) -> ReviewMutationResult:
        draft = cls._lock_active_head(connection, command.head)
        if draft.status != "ready_for_publish":
            raise VersionNotEditable("only a ready version can return to draft")
        state = cls._advance_review_revision(
            connection,
            head=command.head,
            new_status="draft",
        )
        inserted = connection.execute(
            sa.text(
                """
                INSERT INTO version_review_events (
                    operation_token, operation_kind, operation_digest,
                    actor_user_id, dataset_id, version_id,
                    from_status, to_status, data_revision,
                    from_review_revision, to_review_revision,
                    selected_validation_run_id, confirmation_digest,
                    confirmation_json, reason, occurred_at
                ) VALUES (
                    :operation_token, :operation_kind, :operation_digest,
                    :actor_user_id, :dataset_id, :version_id,
                    'ready_for_publish', 'draft', :data_revision,
                    :from_review_revision, :to_review_revision,
                    NULL, NULL, NULL, :reason, :occurred_at
                )
                """
            ),
            {
                "operation_token": command.operation_token.bytes,
                "operation_kind": command.operation_kind,
                "operation_digest": command.operation_digest,
                "actor_user_id": actor.user_id,
                "dataset_id": draft.dataset_id,
                "version_id": draft.version_id,
                "data_revision": draft.data_revision,
                "from_review_revision": draft.review_revision,
                "to_review_revision": state.review_revision,
                "reason": command.reason,
                "occurred_at": _mysql_datetime(occurred_at),
            },
        )
        if inserted.lastrowid is None:
            raise ReviewError("database did not return a version review event ID")
        event_id = int(inserted.lastrowid)
        result = cls._state_result(
            command=command,
            state=state,
            version_review_event_id=event_id,
        )
        return cls._store_result(
            connection,
            command=command,
            result=result,
            completed_at=occurred_at,
        )
