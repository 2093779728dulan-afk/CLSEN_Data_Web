"""MySQL transactions for isolated daily datasets and immutable draft lineage."""

from __future__ import annotations

import hashlib
import hmac
import json
import random
import time
from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, date, datetime
from decimal import Decimal
from typing import Any, Literal, cast
from uuid import UUID, uuid4

import sqlalchemy as sa
from sqlalchemy.engine import Connection, Engine, RowMapping
from sqlalchemy.exc import DBAPIError, IntegrityError, SQLAlchemyError

from app.catalog.scope_repository import (
    append_report_source_key,
    ensure_dataset_scope_assignment,
)
from app.imports.types import ReportType
from app.workbench.repository import (
    MySqlWorkbenchSnapshotRepository,
    SchemaMember,
    SnapshotRowSource,
)

from .merge import (
    MergedSnapshotRow,
    MergeRow,
    SnapshotMember,
    SnapshotScalar,
    canonical_snapshot_digest,
    merge_conflict_pairs,
    merge_rows,
    order_snapshot_members,
)
from .types import (
    ActiveDraftConflict,
    BaselineAlreadyMaterialized,
    BaselineConflict,
    BaselineNotCurrent,
    BaselineNotFound,
    DatasetCommitOutcomeUnknown,
    DatasetError,
    DatasetPermissionDenied,
    DatasetTransactionBusy,
    DiscardDraftCommand,
    DraftMutationResult,
    EmptyReassignmentTarget,
    ForceRebuildDraftCommand,
    MaterializeBaselineCommand,
    MergeDecision,
    OperationConflict,
    PublishedLineageConflict,
    PublishedReassignmentTarget,
    ReassignUnpublishedDraftDateCommand,
    RevisionConflict,
    SealedVersionConflict,
    TargetConflict,
    VersionExpectation,
    canonical_merge_decisions,
)

type _OperationKind = Literal[
    "materialize_baseline",
    "force_rebuild",
    "discard_draft",
    "reassign_date",
]
type _ResultKind = Literal[
    "created",
    "merged",
    "replaced",
    "discarded",
    "force_discarded",
    "reassigned",
    "force_rebuilt",
    "cancelled",
]
type _DispositionKind = Literal[
    "discarded",
    "force_discarded",
    "superseded",
    "date_reassigned",
    "force_rebuilt",
]

_OPERATION_RESULT_SEMANTICS = {
    "materialize_baseline": frozenset(
        {
            ("created", "draft"),
            ("merged", "draft"),
            ("replaced", "draft"),
        }
    ),
    "force_rebuild": frozenset({("force_rebuilt", "draft")}),
    "discard_draft": frozenset(
        {
            ("discarded", "discarded"),
            ("force_discarded", "discarded"),
        }
    ),
    "reassign_date": frozenset(
        {
            ("reassigned", "draft"),
            ("cancelled", "cancelled"),
        }
    ),
}

_MAX_TRANSACTION_RETRIES = 3
_RETRYABLE_MYSQL_ERROR_CODES = frozenset({1205, 1213})
_RETRY_BASE_DELAY_SECONDS = 0.005
_RETRY_MAX_DELAY_SECONDS = 0.04


_BUSINESS_COLUMNS = (
    "parent_asin",
    "child_asin",
    "title",
    "sku",
    "sessions_total",
    "sessions_b2b",
    "conversion_rate_total",
    "session_percentage_b2b",
    "page_views_total",
    "page_views_b2b",
    "page_view_percentage_total",
    "page_view_percentage_b2b",
    "featured_offer_percentage",
    "featured_offer_percentage_b2b",
    "units_ordered",
    "units_ordered_b2b",
    "unit_session_percentage",
    "unit_session_percentage_b2b",
    "ordered_product_sales",
    "ordered_product_sales_b2b",
    "currency_code",
    "total_order_items",
    "total_order_items_b2b",
)
_BUSINESS_TOTAL_COLUMNS = (
    "sessions_total",
    "sessions_b2b",
    "page_views_total",
    "page_views_b2b",
    "units_ordered",
    "units_ordered_b2b",
    "ordered_product_sales",
    "ordered_product_sales_b2b",
    "total_order_items",
    "total_order_items_b2b",
)
_RETURN_COLUMNS = (
    "return_date",
    "order_id",
    "sku",
    "asin",
    "fnsku",
    "product_name",
    "quantity",
    "fulfillment_center_id",
    "detailed_disposition",
    "reason",
    "status",
    "license_plate_number",
    "customer_comments",
)


@dataclass(frozen=True, slots=True)
class _Actor:
    user_id: int
    roles: frozenset[str]

    @property
    def is_admin(self) -> bool:
        return "admin" in self.roles


@dataclass(frozen=True, slots=True)
class _Dataset:
    dataset_id: int
    site_id: int
    report_date: date
    report_type: ReportType


@dataclass(frozen=True, slots=True)
class _Version:
    dataset_id: int
    version_id: int
    report_type: ReportType
    version_no: int
    status: str
    data_revision: int
    review_revision: int
    ruleset_version: str
    created_by: int

    @property
    def expectation(self) -> VersionExpectation:
        return VersionExpectation(
            version_id=self.version_id,
            data_revision=self.data_revision,
            review_revision=self.review_revision,
        )


@dataclass(frozen=True, slots=True)
class _StoredRow:
    source_row_id: int
    source_ordinal: int
    logical_row_id: UUID | None
    row_state: Literal["active", "excluded", "deleted"]
    original_parsed_source_row_id: int | None
    source_parse_baseline_row_id: int | None
    values: tuple[tuple[str, SnapshotScalar], ...]

    def as_merge_row(
        self,
        *,
        member_ordinal: int,
        report_type: ReportType,
    ) -> MergeRow:
        return MergeRow(
            member_ordinal=member_ordinal,
            source_row_id=self.source_row_id,
            source_ordinal=self.source_ordinal,
            logical_row_id=self.logical_row_id,
            row_state=self.row_state,
            conflict_key=_conflict_key(report_type, self.values),
            values=self.values,
        )


@dataclass(frozen=True, slots=True)
class _Baseline:
    batch_id: int
    baseline_id: int
    site_id: int
    report_date: date
    report_type: ReportType
    ruleset_version: str
    rows: tuple[_StoredRow, ...]


@dataclass(frozen=True, slots=True)
class _MemberPlan:
    member: SnapshotMember
    rows: tuple[_StoredRow, ...]


@dataclass(frozen=True, slots=True)
class _SnapshotPlan:
    members: tuple[_MemberPlan, ...]
    rows: tuple[MergedSnapshotRow, ...]
    source_rows: Mapping[tuple[int, int], _StoredRow]
    decisions: tuple[MergeDecision, ...]
    digest: bytes
    totals_json: str


@dataclass(frozen=True, slots=True)
class MergeConflictPreview:
    """One exact target/source row pair requiring a human decision."""

    target_row_id: int
    target_row_ordinal: int
    target_values: tuple[tuple[str, SnapshotScalar], ...]
    source_row_id: int
    source_row_ordinal: int
    source_values: tuple[tuple[str, SnapshotScalar], ...]


@dataclass(frozen=True, slots=True)
class MergePreview:
    """Validated members and their complete row-conflict matrix."""

    report_type: ReportType
    conflicts: tuple[MergeConflictPreview, ...]


def _mysql_datetime(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("database timestamps must be timezone-aware")
    return value.astimezone(UTC).replace(tzinfo=None)


def _canonical_json(value: object) -> str:
    return json.dumps(
        value,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    )


def _merge_decisions_json(decisions: Iterable[MergeDecision]) -> str | None:
    canonical = canonical_merge_decisions(decisions)
    if not canonical:
        return None
    return _canonical_json([decision.as_payload() for decision in canonical])


def _validate_operation_result_semantics(
    *,
    operation_kind: str,
    result_kind: str,
    result_status: str,
) -> None:
    allowed = _OPERATION_RESULT_SEMANTICS.get(operation_kind)
    if allowed is None or (result_kind, result_status) not in allowed:
        raise DatasetError(
            "draft operation terminal result does not match its operation kind"
        )


def _single_merge_decisions_by_row(
    decisions: Iterable[MergeDecision],
) -> tuple[dict[int, MergeDecision], dict[int, MergeDecision]]:
    """Return only pair decisions that are unambiguous at row granularity."""

    decisions_by_target: dict[int, list[MergeDecision]] = {}
    decisions_by_source: dict[int, list[MergeDecision]] = {}
    for decision in decisions:
        decisions_by_target.setdefault(decision.target_row_id, []).append(decision)
        decisions_by_source.setdefault(decision.source_row_id, []).append(decision)
    return (
        {
            row_id: row_decisions[0]
            for row_id, row_decisions in decisions_by_target.items()
            if len(row_decisions) == 1
        },
        {
            row_id: row_decisions[0]
            for row_id, row_decisions in decisions_by_source.items()
            if len(row_decisions) == 1
        },
    )


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


def _as_bytes(value: object, *, length: int, label: str) -> bytes:
    if not isinstance(value, (bytes, bytearray, memoryview)):
        raise DatasetError(f"{label} is not binary")
    result = bytes(value)
    if len(result) != length:
        raise DatasetError(f"{label} has an invalid length")
    return result


def _as_report_type(value: object) -> ReportType:
    if value not in {"business_report", "return_report"}:
        raise DatasetError("database contains an unsupported report type")
    return cast(ReportType, value)


class MySqlDatasetRepository:
    """Own complete MySQL transactions for every stage-five write command."""

    def __init__(
        self,
        engine: Engine,
        *,
        retry_waiter: Callable[[int], None] | None = None,
    ) -> None:
        self._engine = engine
        self._retry_waiter = retry_waiter or _wait_for_transaction_retry
        self._workbench_snapshots = MySqlWorkbenchSnapshotRepository()

    def preview_merge_conflicts(
        self,
        *,
        target_version_id: int,
        source_kind: Literal["parse_baseline", "dataset_version"],
        source_id: int,
    ) -> MergePreview:
        """Read the complete immutable row-conflict matrix for a proposed merge."""

        if target_version_id < 1 or source_id < 1:
            raise ValueError("merge preview identifiers must be positive")
        if source_kind not in {"parse_baseline", "dataset_version"}:
            raise ValueError("merge preview source kind is not supported")
        try:
            with self._engine.connect() as connection:
                target = self._version_by_global_id(
                    connection,
                    version_id=target_version_id,
                )
                target_rows = self._version_rows(connection, target, lock=False)
                if source_kind == "dataset_version":
                    source_version = self._version_by_global_id(
                        connection,
                        version_id=source_id,
                    )
                    if source_version.report_type != target.report_type:
                        raise TargetConflict(
                            "merge preview versions use different report types"
                        )
                    source_rows = self._version_rows(
                        connection,
                        source_version,
                        lock=False,
                    )
                else:
                    baseline_report_type = connection.scalar(
                        sa.text(
                            """
                            SELECT report_type
                            FROM parse_baselines
                            WHERE id = :baseline_id
                            LIMIT 1
                            """
                        ),
                        {"baseline_id": source_id},
                    )
                    if baseline_report_type is None:
                        raise BaselineNotFound("parse baseline does not exist")
                    report_type = _as_report_type(baseline_report_type)
                    if report_type != target.report_type:
                        raise TargetConflict(
                            "merge preview members use different report types"
                        )
                    source_rows = self._baseline_rows(
                        connection,
                        baseline_id=source_id,
                        report_type=report_type,
                    )
                pairs = merge_conflict_pairs(
                    target_rows=tuple(
                        row.as_merge_row(
                            member_ordinal=1,
                            report_type=target.report_type,
                        )
                        for row in target_rows
                    ),
                    source_rows=tuple(
                        row.as_merge_row(
                            member_ordinal=2,
                            report_type=target.report_type,
                        )
                        for row in source_rows
                    ),
                )
                return MergePreview(
                    report_type=target.report_type,
                    conflicts=tuple(
                        MergeConflictPreview(
                            target_row_id=target_row.source_row_id,
                            target_row_ordinal=target_row.source_ordinal,
                            target_values=target_row.values,
                            source_row_id=source_row.source_row_id,
                            source_row_ordinal=source_row.source_ordinal,
                            source_values=source_row.values,
                        )
                        for target_row, source_row in pairs
                    ),
                )
        except DatasetError:
            raise
        except SQLAlchemyError as error:
            raise DatasetError("merge preview query failed") from error

    def materialize_baseline(
        self,
        command: MaterializeBaselineCommand,
        *,
        occurred_at: datetime,
    ) -> DraftMutationResult:
        return self._execute_operation(
            operation_kind="materialize_baseline",
            operation_token=command.operation_token,
            operation_digest=command.operation_digest,
            actor_user_id=command.actor_user_id,
            occurred_at=occurred_at,
            work=lambda connection, actor, timestamp: self._materialize_baseline(
                connection,
                actor=actor,
                command=command,
                occurred_at=timestamp,
                force=False,
            ),
        )

    def force_rebuild_draft(
        self,
        command: ForceRebuildDraftCommand,
        *,
        occurred_at: datetime,
    ) -> DraftMutationResult:
        return self._execute_operation(
            operation_kind="force_rebuild",
            operation_token=command.operation_token,
            operation_digest=command.operation_digest,
            actor_user_id=command.actor_user_id,
            occurred_at=occurred_at,
            work=lambda connection, actor, timestamp: self._materialize_baseline(
                connection,
                actor=actor,
                command=command,
                occurred_at=timestamp,
                force=True,
            ),
        )

    def discard_active_draft(
        self,
        command: DiscardDraftCommand,
        *,
        occurred_at: datetime,
    ) -> DraftMutationResult:
        return self._execute_operation(
            operation_kind="discard_draft",
            operation_token=command.operation_token,
            operation_digest=command.operation_digest,
            actor_user_id=command.actor_user_id,
            occurred_at=occurred_at,
            work=lambda connection, actor, timestamp: self._discard_active_draft(
                connection,
                actor=actor,
                command=command,
                occurred_at=timestamp,
            ),
        )

    def reassign_unpublished_draft_date(
        self,
        command: ReassignUnpublishedDraftDateCommand,
        *,
        occurred_at: datetime,
    ) -> DraftMutationResult:
        return self._execute_operation(
            operation_kind="reassign_date",
            operation_token=command.operation_token,
            operation_digest=command.operation_digest,
            actor_user_id=command.actor_user_id,
            occurred_at=occurred_at,
            work=lambda connection, actor, timestamp: self._reassign_date(
                connection,
                actor=actor,
                command=command,
                occurred_at=timestamp,
            ),
        )

    def _execute_operation(
        self,
        *,
        operation_kind: _OperationKind,
        operation_token: UUID,
        operation_digest: bytes,
        actor_user_id: int,
        occurred_at: datetime,
        work: Callable[[Connection, _Actor, datetime], DraftMutationResult],
    ) -> DraftMutationResult:
        timestamp = _mysql_datetime(occurred_at)

        def recover_known_outcome() -> DraftMutationResult | None:
            try:
                return self._recover_operation(
                    operation_token=operation_token,
                    operation_kind=operation_kind,
                    operation_digest=operation_digest,
                    actor_user_id=actor_user_id,
                )
            except DatasetError:
                raise
            except SQLAlchemyError as error:
                raise DatasetError("draft operation recovery failed") from error

        recovered = recover_known_outcome()
        if recovered is not None:
            return recovered

        retry_count = 0
        while True:
            try:
                with self._engine.begin() as connection:
                    recovered = self._claim_operation(
                        connection,
                        operation_token=operation_token,
                        operation_kind=operation_kind,
                        operation_digest=operation_digest,
                        actor_user_id=actor_user_id,
                        registered_at=timestamp,
                    )
                    if recovered is not None:
                        return recovered
                    actor = self._load_actor(connection, actor_user_id)
                    return work(connection, actor, timestamp)
            except DBAPIError as error:
                if error.connection_invalidated:
                    try:
                        recovered = self._recover_operation(
                            operation_token=operation_token,
                            operation_kind=operation_kind,
                            operation_digest=operation_digest,
                            actor_user_id=actor_user_id,
                        )
                    except Exception as recovery_error:
                        raise DatasetCommitOutcomeUnknown(
                            "draft transaction commit acknowledgement was lost "
                            "and recovery failed"
                        ) from recovery_error
                    if recovered is not None:
                        return recovered
                    raise DatasetCommitOutcomeUnknown(
                        "draft transaction commit acknowledgement was lost"
                    ) from error
                if _mysql_error_code(error) not in _RETRYABLE_MYSQL_ERROR_CODES:
                    raise DatasetError("draft transaction failed") from error
                if retry_count >= _MAX_TRANSACTION_RETRIES:
                    raise DatasetTransactionBusy(
                        "draft transaction remained busy after 3 retries"
                    ) from error
                retry_count += 1
                recovered = recover_known_outcome()
                if recovered is not None:
                    return recovered
                self._retry_waiter(retry_count)
                continue
            except DatasetError:
                raise
            except SQLAlchemyError as error:
                raise DatasetError("draft transaction failed") from error

    def _claim_operation(
        self,
        connection: Connection,
        *,
        operation_token: UUID,
        operation_kind: _OperationKind,
        operation_digest: bytes,
        actor_user_id: int,
        registered_at: datetime,
    ) -> DraftMutationResult | None:
        savepoint = connection.begin_nested()
        try:
            connection.execute(
                sa.text(
                    """
                    INSERT INTO draft_operation_tokens (
                        operation_token, operation_kind, operation_digest,
                        actor_user_id, registered_at
                    ) VALUES (
                        :operation_token, :operation_kind, :operation_digest,
                        :actor_user_id, :registered_at
                    )
                    """
                ),
                {
                    "operation_token": operation_token.bytes,
                    "operation_kind": operation_kind,
                    "operation_digest": operation_digest,
                    "actor_user_id": actor_user_id,
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
            operation_token=operation_token,
            operation_kind=operation_kind,
            operation_digest=operation_digest,
            actor_user_id=actor_user_id,
            require_result=True,
        )

    def _recover_operation(
        self,
        *,
        operation_token: UUID,
        operation_kind: _OperationKind,
        operation_digest: bytes,
        actor_user_id: int,
    ) -> DraftMutationResult | None:
        with self._engine.connect() as connection:
            return self._operation_result(
                connection,
                operation_token=operation_token,
                operation_kind=operation_kind,
                operation_digest=operation_digest,
                actor_user_id=actor_user_id,
                require_result=False,
            )

    def _operation_result(
        self,
        connection: Connection,
        *,
        operation_token: UUID,
        operation_kind: _OperationKind,
        operation_digest: bytes,
        actor_user_id: int,
        require_result: bool,
    ) -> DraftMutationResult | None:
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
                {"operation_token": operation_token.bytes},
            )
            .mappings()
            .first()
        )
        if token_row is None:
            return None
        stored_digest = _as_bytes(
            token_row["operation_digest"],
            length=32,
            label="draft operation digest",
        )
        if (
            token_row["operation_kind"] != operation_kind
            or int(token_row["actor_user_id"]) != actor_user_id
            or not hmac.compare_digest(stored_digest, operation_digest)
        ):
            raise OperationConflict(
                "operation token is already bound to another draft command"
            )

        result = (
            connection.execute(
                sa.text(
                    """
                    SELECT results.result_kind,
                           results.result_dataset_id,
                           results.result_version_id,
                           results.result_version_no,
                           results.result_status,
                           results.result_data_revision,
                           results.result_review_revision,
                           results.superseded_version_id_1,
                           results.superseded_version_id_2,
                           results.source_dataset_id,
                           results.source_version_id
                    FROM draft_operation_results AS results
                    WHERE results.operation_token = :operation_token
                    LIMIT 1
                    """
                ),
                {"operation_token": operation_token.bytes},
            )
            .mappings()
            .first()
        )
        if result is None:
            if require_result:
                raise DatasetCommitOutcomeUnknown(
                    "draft operation token has no terminal result"
                )
            return None
        result_dataset_id = int(result["result_dataset_id"])
        result_version_id = int(result["result_version_id"])
        superseded_ids = tuple(
            int(value)
            for value in (
                result["superseded_version_id_1"],
                result["superseded_version_id_2"],
            )
            if value is not None
        )
        result_kind = str(result["result_kind"])
        status = str(result["result_status"])
        _validate_operation_result_semantics(
            operation_kind=operation_kind,
            result_kind=result_kind,
            result_status=status,
        )
        if result_kind == "cancelled" and (
            superseded_ids
            or result["source_dataset_id"] is not None
            or result["source_version_id"] is not None
        ):
            raise DatasetError(
                "cancelled draft operation terminal result cannot contain lineage"
            )
        return DraftMutationResult(
            operation_token=operation_token,
            dataset_id=result_dataset_id,
            version_id=result_version_id,
            version_no=int(result["result_version_no"]),
            status=cast(Any, status),
            data_revision=int(result["result_data_revision"]),
            review_revision=int(result["result_review_revision"]),
            superseded_version_ids=superseded_ids,
            source_dataset_id=(
                int(result["source_dataset_id"])
                if result["source_dataset_id"] is not None
                else None
            ),
            source_version_id=(
                int(result["source_version_id"])
                if result["source_version_id"] is not None
                else None
            ),
        )

    @staticmethod
    def _load_actor(connection: Connection, actor_user_id: int) -> _Actor:
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
            raise DatasetPermissionDenied("actor is not an active user")
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
            raise DatasetPermissionDenied(
                "only administrators and data managers may mutate drafts"
            )
        return _Actor(user_id=actor_user_id, roles=roles)

    def _materialize_baseline(
        self,
        connection: Connection,
        *,
        actor: _Actor,
        command: MaterializeBaselineCommand | ForceRebuildDraftCommand,
        occurred_at: datetime,
        force: bool,
    ) -> DraftMutationResult:
        if force and not actor.is_admin:
            raise DatasetPermissionDenied(
                "only an administrator may force-rebuild an active draft"
            )
        baseline = self._lock_current_baseline(
            connection,
            batch_id=command.batch_id,
            baseline_id=command.parse_baseline_id,
            expected_report_date=command.report_date,
        )
        dataset, dataset_created = self._lock_or_create_dataset(
            connection,
            site_id=baseline.site_id,
            report_date=baseline.report_date,
            report_type=baseline.report_type,
            occurred_at=occurred_at,
        )
        active = self._active_version(connection, dataset.dataset_id)
        publication_version_id = self._publication_version_id(
            connection,
            dataset.dataset_id,
        )
        expected_active = command.expected_active_draft
        self._assert_expected_active(expected_active, active)
        if publication_version_id != command.expected_publication_version_id:
            raise TargetConflict(
                "current publication differs from the caller's preview"
            )
        if active is not None:
            self._assert_no_unfinalized_published_move_ancestry(
                connection,
                version_id=active.version_id,
            )

        input_batches: tuple[tuple[int, str], ...]
        parents: tuple[tuple[_Version, str], ...]
        if force:
            if active is None:  # guarded above, retained for type narrowing
                raise ActiveDraftConflict("force rebuild requires an active draft")
            target_version: _Version | None = None
            target_rows: tuple[_StoredRow, ...] = ()
            target_role = "base"
            decisions: tuple[MergeDecision, ...] = ()
            snapshot_kind = "replacement"
            result_kind: _ResultKind = "force_rebuilt"
            input_batches = ((baseline.batch_id, "replacement"),)
            parents = ()
        else:
            materialize = cast(MaterializeBaselineCommand, command)
            decisions = materialize.merge_decisions
            target_version = None
            target_rows = ()
            target_role = "base"
            parents = ()
            inherited_inputs: tuple[tuple[int, str], ...] = ()
            if active is not None:
                if materialize.strategy != "merge":
                    raise ActiveDraftConflict(
                        "an active draft may only be merged through the ordinary path"
                    )
                target_version = active
                target_role = "draft_predecessor"
                parents = ((active, "draft_predecessor"),)
            elif publication_version_id is not None and materialize.strategy == "merge":
                target_version = self._version_by_id(
                    connection,
                    dataset_id=dataset.dataset_id,
                    version_id=publication_version_id,
                    lock=True,
                )
                if target_version.status != "published":
                    raise SealedVersionConflict(
                        "publication pointer does not reference a published version"
                    )
                target_role = "merge_target"
                parents = ((target_version, "merge_target"),)

            if target_version is not None:
                self._lock_input_batches_for_versions(
                    connection,
                    (target_version.version_id,),
                )
                target_rows = self._version_rows(connection, target_version)
                inherited_inputs = self._version_inputs(
                    connection,
                    target_version.version_id,
                )

            if target_version is None:
                snapshot_kind = "replacement"
                input_role = (
                    "replacement" if materialize.strategy == "replace" else "primary"
                )
                input_batches = ((baseline.batch_id, input_role),)
                result_kind = (
                    "replaced"
                    if materialize.strategy == "replace"
                    and publication_version_id is not None
                    else "created"
                )
            else:
                snapshot_kind = "merge"
                input_batches = self._merge_inputs(
                    inherited_inputs,
                    ((baseline.batch_id, "merge_source"),),
                )
                result_kind = "merged"

        members: list[_MemberPlan] = []
        if target_version is not None:
            members.append(
                _MemberPlan(
                    member=SnapshotMember(
                        "dataset_version",
                        cast(Any, target_role),
                        target_version.version_id,
                    ),
                    rows=target_rows,
                )
            )
        members.append(
            _MemberPlan(
                member=SnapshotMember(
                    "parse_baseline",
                    "parse_input",
                    baseline.baseline_id,
                ),
                rows=baseline.rows,
            )
        )
        plan = self._snapshot_plan(
            report_type=baseline.report_type,
            ruleset_version=baseline.ruleset_version,
            members=members,
            decisions=decisions,
            preserve_source_logical_ids=False,
        )
        new_version = self._create_draft_version(
            connection,
            dataset=dataset,
            ruleset_version=baseline.ruleset_version,
            snapshot_kind=snapshot_kind,
            plan=plan,
            actor_user_id=actor.user_id,
            occurred_at=occurred_at,
            parents=parents,
            input_batches=input_batches,
        )

        superseded: tuple[int, ...] = ()
        source_dataset_id: int | None = None
        source_version_id: int | None = None
        if active is None:
            self._insert_draft_pointer(
                connection,
                dataset_id=dataset.dataset_id,
                version_id=new_version.version_id,
                occurred_at=occurred_at,
            )
        else:
            self._switch_draft_pointer(
                connection,
                dataset_id=dataset.dataset_id,
                old_version=active,
                new_version_id=new_version.version_id,
                occurred_at=occurred_at,
            )
            disposition: _DispositionKind = "force_rebuilt" if force else "superseded"
            self._discard_version(
                connection,
                version=active,
                operation_token=command.operation_token,
                operation_kind=("force_rebuild" if force else "materialize_baseline"),
                operation_digest=command.operation_digest,
                actor_user_id=actor.user_id,
                event_type=disposition,
                reason=command.reason,
                occurred_at=occurred_at,
                successor_dataset_id=dataset.dataset_id,
                successor_version_id=new_version.version_id,
            )
            superseded = (active.version_id,)
            source_dataset_id = active.dataset_id
            source_version_id = active.version_id

        self._insert_audit(
            connection,
            site_id=dataset.site_id,
            actor_user_id=actor.user_id,
            event_type=("draft_force_rebuilt" if force else "draft_materialized"),
            object_type="dataset_version",
            object_id=str(new_version.version_id),
            operation_token=command.operation_token,
            payload={
                "dataset_id": dataset.dataset_id,
                "version_id": new_version.version_id,
                "batch_id": baseline.batch_id,
                "baseline_id": baseline.baseline_id,
                "result": result_kind,
                "dataset_created": dataset_created,
                "reason": command.reason,
            },
            occurred_at=occurred_at,
        )
        return self._record_result(
            connection,
            operation_token=command.operation_token,
            operation_kind=("force_rebuild" if force else "materialize_baseline"),
            operation_digest=command.operation_digest,
            actor_user_id=actor.user_id,
            result_kind=result_kind,
            version=new_version,
            occurred_at=occurred_at,
            superseded_version_ids=superseded,
            source_dataset_id=source_dataset_id,
            source_version_id=source_version_id,
        )

    def _discard_active_draft(
        self,
        connection: Connection,
        *,
        actor: _Actor,
        command: DiscardDraftCommand,
        occurred_at: datetime,
    ) -> DraftMutationResult:
        dataset = self._dataset_by_id(
            connection,
            dataset_id=command.dataset_id,
            lock=True,
        )
        if dataset is None:
            raise ActiveDraftConflict("dataset has no active draft")
        active = self._active_version(connection, dataset.dataset_id)
        self._assert_expected_active(command.expected_active_draft, active)
        if active is None:  # guarded above, retained for type narrowing
            raise ActiveDraftConflict("dataset has no active draft")
        if not actor.is_admin and active.created_by != actor.user_id:
            raise DatasetPermissionDenied(
                "a data manager may only discard their own active draft"
            )

        deleted = connection.execute(
            sa.text(
                """
                DELETE FROM dataset_drafts
                WHERE dataset_id = :dataset_id
                  AND version_id = :version_id
                  AND version_status = :version_status
                """
            ),
            {
                "dataset_id": dataset.dataset_id,
                "version_id": active.version_id,
                "version_status": active.status,
            },
        )
        if deleted.rowcount != 1:
            raise ActiveDraftConflict("active draft pointer changed before discard")
        disposition: _DispositionKind = (
            "force_discarded" if actor.is_admin else "discarded"
        )
        self._discard_version(
            connection,
            version=active,
            operation_token=command.operation_token,
            operation_kind="discard_draft",
            operation_digest=command.operation_digest,
            actor_user_id=actor.user_id,
            event_type=disposition,
            reason=command.reason,
            occurred_at=occurred_at,
            successor_dataset_id=None,
            successor_version_id=None,
        )
        self._insert_audit(
            connection,
            site_id=dataset.site_id,
            actor_user_id=actor.user_id,
            event_type=(
                "draft_force_discarded" if actor.is_admin else "draft_discarded"
            ),
            object_type="dataset_version",
            object_id=str(active.version_id),
            operation_token=command.operation_token,
            payload={
                "dataset_id": dataset.dataset_id,
                "version_id": active.version_id,
                "result": disposition,
                "reason": command.reason,
            },
            occurred_at=occurred_at,
        )
        discarded = _Version(
            dataset_id=active.dataset_id,
            version_id=active.version_id,
            report_type=active.report_type,
            version_no=active.version_no,
            status="discarded",
            data_revision=active.data_revision,
            review_revision=active.review_revision,
            ruleset_version=active.ruleset_version,
            created_by=active.created_by,
        )
        return self._record_result(
            connection,
            operation_token=command.operation_token,
            operation_kind="discard_draft",
            operation_digest=command.operation_digest,
            actor_user_id=actor.user_id,
            result_kind=cast(_ResultKind, disposition),
            version=discarded,
            occurred_at=occurred_at,
            superseded_version_ids=(),
            source_dataset_id=None,
            source_version_id=None,
        )

    def _reassign_date(
        self,
        connection: Connection,
        *,
        actor: _Actor,
        command: ReassignUnpublishedDraftDateCommand,
        occurred_at: datetime,
    ) -> DraftMutationResult:
        source_preview = self._dataset_by_id(
            connection,
            dataset_id=command.source_dataset_id,
            lock=False,
        )
        if source_preview is None:
            raise ActiveDraftConflict("source dataset does not exist")
        if source_preview.report_date == command.target_report_date:
            raise TargetConflict("target report date must differ from source date")
        target_preview = self._dataset_for_key(
            connection,
            report_date=command.target_report_date,
            report_type=source_preview.report_type,
            lock=False,
        )
        expected_target_id = command.target.expected_dataset_id
        if expected_target_id is None:
            if target_preview is not None:
                raise TargetConflict("target dataset appeared after the caller preview")
        elif target_preview is None or target_preview.dataset_id != expected_target_id:
            raise TargetConflict("target dataset differs from the caller preview")

        if target_preview is not None:
            locked = self._lock_datasets(
                connection,
                (source_preview.dataset_id, target_preview.dataset_id),
            )
            source_dataset = locked[source_preview.dataset_id]
            target_dataset = locked[target_preview.dataset_id]
            target_created = False
        else:
            locked = self._lock_datasets(
                connection,
                (source_preview.dataset_id,),
            )
            source_dataset = locked[source_preview.dataset_id]
            target_dataset, target_created = self._lock_or_create_dataset(
                connection,
                site_id=source_dataset.site_id,
                report_date=command.target_report_date,
                report_type=source_dataset.report_type,
                occurred_at=occurred_at,
            )
            if not target_created:
                raise TargetConflict(
                    "empty target preview became stale before date reassignment"
                )

        if (
            target_dataset.site_id != source_dataset.site_id
            or target_dataset.report_type != source_dataset.report_type
        ):
            self._raise_site_conflict(
                expected_site_id=source_dataset.site_id,
                actual_site_id=target_dataset.site_id,
            )
        if (
            expected_target_id is not None
            and target_dataset.dataset_id != expected_target_id
        ):
            raise TargetConflict("locked target dataset differs from the preview")

        source_active = self._active_version(
            connection,
            source_dataset.dataset_id,
        )
        self._assert_expected_active(command.source_draft, source_active)
        if source_active is None:  # guarded above, retained for type narrowing
            raise ActiveDraftConflict("source dataset has no active draft")
        if not actor.is_admin and source_active.created_by != actor.user_id:
            raise DatasetPermissionDenied(
                "a data manager may only reassign their own active draft"
            )
        if self._has_published_ancestry(connection, source_active.version_id):
            raise PublishedLineageConflict(
                "published lineage requires the administrator move workflow"
            )

        target_active = self._active_version(
            connection,
            target_dataset.dataset_id,
        )
        target_publication = self._publication_version_id(
            connection,
            target_dataset.dataset_id,
        )
        target_version: _Version | None = None
        target_rows: tuple[_StoredRow, ...] = ()
        if isinstance(command.target, EmptyReassignmentTarget):
            if (
                not target_created
                or target_active is not None
                or target_publication is not None
            ):
                raise TargetConflict("target is no longer empty")
        elif isinstance(command.target, PublishedReassignmentTarget):
            if (
                target_active is not None
                or target_publication != command.target.expected_publication_version_id
            ):
                raise TargetConflict("published target shape changed")
            if command.target.strategy == "merge":
                target_version = self._version_by_id(
                    connection,
                    dataset_id=target_dataset.dataset_id,
                    version_id=command.target.expected_publication_version_id,
                    lock=True,
                )
                if target_version.status != "published":
                    raise SealedVersionConflict(
                        "target publication is not a sealed published version"
                    )
        else:
            active_target = command.target
            if target_publication != active_target.expected_publication_version_id:
                raise TargetConflict("target publication changed")
            self._assert_expected_active(
                active_target.expected_active_draft,
                target_active,
            )
            if target_active is None:  # guarded above
                raise TargetConflict("target active draft disappeared")
            if active_target.action == "cancel":
                self._insert_audit(
                    connection,
                    site_id=source_dataset.site_id,
                    actor_user_id=actor.user_id,
                    event_type="draft_date_reassignment_cancelled",
                    object_type="dataset_version",
                    object_id=str(source_active.version_id),
                    operation_token=command.operation_token,
                    payload={
                        "source_dataset_id": source_dataset.dataset_id,
                        "source_version_id": source_active.version_id,
                        "target_dataset_id": target_dataset.dataset_id,
                        "reason": command.reason,
                    },
                    occurred_at=occurred_at,
                )
                return self._record_result(
                    connection,
                    operation_token=command.operation_token,
                    operation_kind="reassign_date",
                    operation_digest=command.operation_digest,
                    actor_user_id=actor.user_id,
                    result_kind="cancelled",
                    version=source_active,
                    occurred_at=occurred_at,
                    superseded_version_ids=(),
                    source_dataset_id=None,
                    source_version_id=None,
                    status_override="cancelled",
                )
            target_version = target_active

        versions_with_inputs = [source_active.version_id]
        if target_version is not None:
            versions_with_inputs.append(target_version.version_id)
        self._lock_input_batches_for_versions(connection, versions_with_inputs)
        if target_version is not None:
            target_rows = self._version_rows(connection, target_version)
        source_rows = self._version_rows(connection, source_active)
        members: list[_MemberPlan] = []
        parents: list[tuple[_Version, str]] = []
        input_groups: list[tuple[tuple[int, str], ...]] = []
        if target_version is not None:
            members.append(
                _MemberPlan(
                    member=SnapshotMember(
                        "dataset_version",
                        "merge_target",
                        target_version.version_id,
                    ),
                    rows=target_rows,
                )
            )
            parents.append((target_version, "merge_target"))
            input_groups.append(
                self._version_inputs(connection, target_version.version_id)
            )
        members.append(
            _MemberPlan(
                member=SnapshotMember(
                    "dataset_version",
                    "moved_source",
                    source_active.version_id,
                ),
                rows=source_rows,
            )
        )
        parents.append((source_active, "moved_source"))
        source_inputs = tuple(
            (batch_id, "moved_source")
            for batch_id, _role in self._version_inputs(
                connection,
                source_active.version_id,
            )
        )
        input_groups.append(source_inputs)
        plan = self._snapshot_plan(
            report_type=source_dataset.report_type,
            ruleset_version=source_active.ruleset_version,
            members=members,
            decisions=command.merge_decisions,
            preserve_source_logical_ids=True,
        )
        new_version = self._create_draft_version(
            connection,
            dataset=target_dataset,
            ruleset_version=source_active.ruleset_version,
            snapshot_kind="date_reassignment",
            plan=plan,
            actor_user_id=actor.user_id,
            occurred_at=occurred_at,
            parents=parents,
            input_batches=self._merge_inputs(*input_groups),
        )

        superseded: list[int] = []
        if target_active is None:
            self._insert_draft_pointer(
                connection,
                dataset_id=target_dataset.dataset_id,
                version_id=new_version.version_id,
                occurred_at=occurred_at,
            )
        else:
            self._switch_draft_pointer(
                connection,
                dataset_id=target_dataset.dataset_id,
                old_version=target_active,
                new_version_id=new_version.version_id,
                occurred_at=occurred_at,
            )
            self._discard_version(
                connection,
                version=target_active,
                operation_token=command.operation_token,
                operation_kind="reassign_date",
                operation_digest=command.operation_digest,
                actor_user_id=actor.user_id,
                event_type="superseded",
                reason=command.reason,
                occurred_at=occurred_at,
                successor_dataset_id=target_dataset.dataset_id,
                successor_version_id=new_version.version_id,
            )
            superseded.append(target_active.version_id)

        removed_source = connection.execute(
            sa.text(
                """
                DELETE FROM dataset_drafts
                WHERE dataset_id = :dataset_id
                  AND version_id = :version_id
                  AND version_status = :version_status
                """
            ),
            {
                "dataset_id": source_dataset.dataset_id,
                "version_id": source_active.version_id,
                "version_status": source_active.status,
            },
        )
        if removed_source.rowcount != 1:
            raise ActiveDraftConflict(
                "source active draft pointer changed during reassignment"
            )
        self._discard_version(
            connection,
            version=source_active,
            operation_token=command.operation_token,
            operation_kind="reassign_date",
            operation_digest=command.operation_digest,
            actor_user_id=actor.user_id,
            event_type="date_reassigned",
            reason=command.reason,
            occurred_at=occurred_at,
            successor_dataset_id=target_dataset.dataset_id,
            successor_version_id=new_version.version_id,
        )
        superseded.append(source_active.version_id)
        self._insert_audit(
            connection,
            site_id=source_dataset.site_id,
            actor_user_id=actor.user_id,
            event_type="draft_date_reassigned",
            object_type="dataset_version",
            object_id=str(new_version.version_id),
            operation_token=command.operation_token,
            payload={
                "source_dataset_id": source_dataset.dataset_id,
                "source_version_id": source_active.version_id,
                "target_dataset_id": target_dataset.dataset_id,
                "target_version_id": new_version.version_id,
                "reason": command.reason,
            },
            occurred_at=occurred_at,
        )
        return self._record_result(
            connection,
            operation_token=command.operation_token,
            operation_kind="reassign_date",
            operation_digest=command.operation_digest,
            actor_user_id=actor.user_id,
            result_kind="reassigned",
            version=new_version,
            occurred_at=occurred_at,
            superseded_version_ids=tuple(superseded),
            source_dataset_id=source_dataset.dataset_id,
            source_version_id=source_active.version_id,
        )

    @staticmethod
    def _lock_input_batches_for_versions(
        connection: Connection,
        version_ids: Sequence[int],
    ) -> None:
        unique_versions = tuple(sorted(set(version_ids)))
        if not unique_versions:
            return
        version_bind: sa.BindParameter[Any] = sa.bindparam(
            "version_ids",
            expanding=True,
        )
        batch_ids = tuple(
            int(value)
            for value in connection.scalars(
                sa.text(
                    """
                    SELECT DISTINCT batch_id
                    FROM version_input_batches
                    WHERE version_id IN :version_ids
                    ORDER BY batch_id
                    """
                ).bindparams(version_bind),
                {"version_ids": unique_versions},
            )
        )
        if not batch_ids:
            return
        batch_bind: sa.BindParameter[Any] = sa.bindparam(
            "batch_ids",
            expanding=True,
        )
        tuple(
            connection.scalars(
                sa.text(
                    """
                    SELECT id
                    FROM import_batches
                    WHERE id IN :batch_ids
                    ORDER BY id
                    FOR UPDATE
                    """
                ).bindparams(batch_bind),
                {"batch_ids": batch_ids},
            )
        )

    def _lock_datasets(
        self,
        connection: Connection,
        dataset_ids: Sequence[int],
    ) -> dict[int, _Dataset]:
        identities = tuple(sorted(set(dataset_ids)))
        if not identities:
            raise ValueError("at least one dataset must be locked")
        self._lock_dataset_rows(connection, identities)
        identity_bind: sa.BindParameter[Any] = sa.bindparam(
            "dataset_ids",
            expanding=True,
        )
        rows = (
            connection.execute(
                sa.text(
                    """
                    SELECT id, site_id, report_date, report_type
                    FROM daily_datasets
                    WHERE id IN :dataset_ids
                    ORDER BY id
                    """
                ).bindparams(identity_bind),
                {"dataset_ids": identities},
            )
            .mappings()
            .all()
        )
        locked = {
            dataset.dataset_id: dataset
            for dataset in (self._dataset_from_row(row) for row in rows)
            if dataset is not None
        }
        if set(locked) != set(identities):
            raise TargetConflict("one of the daily datasets disappeared")
        return locked

    @staticmethod
    def _lock_dataset_rows(
        connection: Connection,
        dataset_ids: Sequence[int],
    ) -> None:
        """Lock synchronization rows without making daily datasets mutable."""

        identities = tuple(sorted(set(dataset_ids)))
        if not identities:
            raise ValueError("at least one dataset lock must be acquired")
        identity_bind: sa.BindParameter[Any] = sa.bindparam(
            "dataset_ids",
            expanding=True,
        )
        locked = connection.execute(
            sa.text(
                """
                UPDATE daily_dataset_locks
                SET lock_revision = CASE
                    WHEN lock_revision = 18446744073709551615 THEN 0
                    ELSE lock_revision + 1
                END
                WHERE dataset_id IN :dataset_ids
                ORDER BY dataset_id
                """
            ).bindparams(identity_bind),
            {"dataset_ids": identities},
        )
        if locked.rowcount != len(identities):
            raise DatasetError("one of the daily dataset lock rows is missing")

    @staticmethod
    def _has_published_ancestry(
        connection: Connection,
        version_id: int,
    ) -> bool:
        value = connection.scalar(
            sa.text(
                """
                WITH RECURSIVE ancestors (version_id) AS (
                    SELECT :version_id
                    UNION DISTINCT
                    SELECT parents.parent_version_id
                    FROM version_parent_versions AS parents
                    INNER JOIN ancestors
                        ON ancestors.version_id = parents.child_version_id
                )
                SELECT EXISTS(
                    SELECT 1
                    FROM ancestors
                    INNER JOIN dataset_versions AS versions
                        ON versions.id = ancestors.version_id
                    WHERE versions.status = 'published'
                )
                """
            ),
            {"version_id": version_id},
        )
        return bool(value)

    @staticmethod
    def _assert_no_unfinalized_published_move_ancestry(
        connection: Connection,
        *,
        version_id: int,
    ) -> None:
        """Keep a pending move token bound to its original active target draft."""

        pending_move_exists = connection.scalar(
            sa.text(
                """
                WITH RECURSIVE ancestors (version_id) AS (
                    SELECT :version_id
                    UNION DISTINCT
                    SELECT parents.parent_version_id
                    FROM version_parent_versions AS parents
                    INNER JOIN ancestors
                        ON ancestors.version_id = parents.child_version_id
                )
                SELECT EXISTS(
                    SELECT 1
                    FROM ancestors
                    INNER JOIN draft_operation_results AS move_revisions
                        ON move_revisions.result_version_id = ancestors.version_id
                       AND move_revisions.operation_kind =
                           'create_published_move_revision'
                       AND move_revisions.result_kind = 'move_revision_created'
                    INNER JOIN dataset_versions AS move_versions
                        ON move_versions.id = move_revisions.result_version_id
                    WHERE move_versions.status <> 'published'
                )
                """
            ),
            {"version_id": version_id},
        )
        if bool(pending_move_exists):
            raise PublishedLineageConflict(
                "a pending published move draft cannot be superseded; "
                "discard it explicitly or use atomic published-move finalization"
            )

    def _lock_current_baseline(
        self,
        connection: Connection,
        *,
        batch_id: int,
        baseline_id: int,
        expected_report_date: date,
    ) -> _Baseline:
        batch = (
            connection.execute(
                sa.text(
                    """
                    SELECT id, site_id, report_date, report_type, status,
                           current_successful_parse_attempt_id
                    FROM import_batches
                    WHERE id = :batch_id
                    FOR UPDATE
                    """
                ),
                {"batch_id": batch_id},
            )
            .mappings()
            .first()
        )
        if batch is None:
            raise BaselineNotFound("import batch does not exist")
        baseline = (
            connection.execute(
                sa.text(
                    """
                    SELECT id, parse_attempt_id, report_type, attempt_status,
                           ruleset_version
                    FROM parse_baselines
                    WHERE id = :baseline_id
                    LIMIT 1
                    """
                ),
                {"baseline_id": baseline_id},
            )
            .mappings()
            .first()
        )
        if baseline is None:
            raise BaselineNotFound("parse baseline does not exist")
        report_type = _as_report_type(batch["report_type"])
        baseline_report_type = _as_report_type(baseline["report_type"])
        if (
            batch["status"] != "staged"
            or baseline["attempt_status"] != "succeeded"
            or batch["current_successful_parse_attempt_id"] is None
            or int(batch["current_successful_parse_attempt_id"])
            != int(baseline["parse_attempt_id"])
            or baseline_report_type != report_type
        ):
            raise BaselineNotCurrent(
                "baseline is not the batch's current successful parse result"
            )
        report_date = batch["report_date"]
        if not isinstance(report_date, date):
            raise BaselineConflict("import batch has no confirmed report date")
        if report_date != expected_report_date:
            raise BaselineConflict(
                "import batch report date differs from the command preview"
            )
        if batch["site_id"] is None:
            raise BaselineConflict("import batch has no confirmed site")
        already_used = connection.scalar(
            sa.text(
                """
                SELECT EXISTS(
                    SELECT 1
                    FROM version_base_snapshot_members
                    WHERE member_type = 'parse_baseline'
                      AND parse_baseline_id = :baseline_id
                )
                """
            ),
            {"baseline_id": baseline_id},
        )
        if already_used == 1:
            raise BaselineAlreadyMaterialized(
                "parse baseline has already been materialized"
            )
        rows = self._baseline_rows(
            connection,
            baseline_id=baseline_id,
            report_type=report_type,
        )
        return _Baseline(
            batch_id=batch_id,
            baseline_id=baseline_id,
            site_id=int(batch["site_id"]),
            report_date=report_date,
            report_type=report_type,
            ruleset_version=str(baseline["ruleset_version"]),
            rows=rows,
        )

    def _lock_or_create_dataset(
        self,
        connection: Connection,
        *,
        site_id: int,
        report_date: date,
        report_type: ReportType,
        occurred_at: datetime,
    ) -> tuple[_Dataset, bool]:
        existing = self._dataset_for_key(
            connection,
            report_date=report_date,
            report_type=report_type,
            lock=True,
        )
        created = False
        if existing is None:
            savepoint = connection.begin_nested()
            dataset_inserted = False
            inserted_dataset_id: int | None = None
            try:
                inserted = connection.execute(
                    sa.text(
                        """
                        INSERT INTO daily_datasets (
                            site_id, report_date, report_type, created_at
                        ) VALUES (
                            :site_id, :report_date, :report_type, :created_at
                        )
                        """
                    ),
                    {
                        "site_id": site_id,
                        "report_date": report_date,
                        "report_type": report_type,
                        "created_at": occurred_at,
                    },
                )
                if inserted.lastrowid is None:
                    raise DatasetError("database did not return a dataset ID")
                dataset_inserted = True
                inserted_dataset_id = int(inserted.lastrowid)
                connection.execute(
                    sa.text(
                        """
                        INSERT INTO daily_dataset_locks (
                            dataset_id, lock_revision
                        ) VALUES (:dataset_id, 0)
                        """
                    ),
                    {"dataset_id": inserted_dataset_id},
                )
                savepoint.commit()
                created = True
            except IntegrityError as error:
                savepoint.rollback()
                if dataset_inserted or _mysql_error_code(error) != 1062:
                    raise
            if created:
                if inserted_dataset_id is None:  # pragma: no cover - defensive only
                    raise DatasetError("database did not retain the new dataset ID")
                existing = self._dataset_by_id(
                    connection,
                    dataset_id=inserted_dataset_id,
                    lock=True,
                )
            else:
                # A normal consistent read may have established a repeatable-read
                # snapshot before the competing insert committed. FOR SHARE is a
                # current read, so it can discover the winner without granting
                # UPDATE on the immutable daily_datasets table.
                existing = self._current_dataset_for_key(
                    connection,
                    report_date=report_date,
                    report_type=report_type,
                )
                if existing is not None:
                    self._lock_dataset_rows(connection, (existing.dataset_id,))
        if existing is None:
            raise DatasetError("daily dataset could not be created or locked")
        if existing.site_id != site_id:
            self._raise_site_conflict(
                expected_site_id=site_id,
                actual_site_id=existing.site_id,
            )
        ensure_dataset_scope_assignment(
            connection,
            dataset_id=existing.dataset_id,
            site_id=existing.site_id,
            occurred_at=occurred_at,
        )
        return existing, created

    @staticmethod
    def _raise_site_conflict(*, expected_site_id: int, actual_site_id: int) -> None:
        # Imported lazily so this repository remains usable while older callers
        # transition from the original TargetConflict-only exception surface.
        from .types import DatasetSiteConflict

        raise DatasetSiteConflict(
            "daily dataset belongs to another site",
            expected_site_id=expected_site_id,
            actual_site_id=actual_site_id,
        )

    def _dataset_for_key(
        self,
        connection: Connection,
        *,
        report_date: date,
        report_type: ReportType,
        lock: bool,
    ) -> _Dataset | None:
        if lock:
            dataset_id = connection.scalar(
                sa.text(
                    """
                    SELECT id
                    FROM daily_datasets
                    WHERE report_date = :report_date
                      AND report_type = :report_type
                    LIMIT 1
                    """
                ),
                {"report_date": report_date, "report_type": report_type},
            )
            if dataset_id is None:
                return None
            identity = int(dataset_id)
            self._lock_dataset_rows(connection, (identity,))
            dataset = self._dataset_by_id(
                connection,
                dataset_id=identity,
                lock=False,
            )
            if dataset is None:
                raise TargetConflict("daily dataset disappeared after its lock")
            if dataset.report_date != report_date or dataset.report_type != report_type:
                raise TargetConflict("daily dataset key changed after its lock")
            return dataset

        row = (
            connection.execute(
                sa.text(
                    """
                    SELECT id, site_id, report_date, report_type
                    FROM daily_datasets
                    WHERE report_date = :report_date
                      AND report_type = :report_type
                    LIMIT 1
                    """
                ),
                {"report_date": report_date, "report_type": report_type},
            )
            .mappings()
            .first()
        )
        return self._dataset_from_row(row)

    def _current_dataset_for_key(
        self,
        connection: Connection,
        *,
        report_date: date,
        report_type: ReportType,
    ) -> _Dataset | None:
        row = (
            connection.execute(
                sa.text(
                    """
                    SELECT id, site_id, report_date, report_type
                    FROM daily_datasets
                    WHERE report_date = :report_date
                      AND report_type = :report_type
                    LIMIT 1
                    FOR SHARE
                    """
                ),
                {"report_date": report_date, "report_type": report_type},
            )
            .mappings()
            .first()
        )
        return self._dataset_from_row(row)

    def _dataset_by_id(
        self,
        connection: Connection,
        *,
        dataset_id: int,
        lock: bool,
    ) -> _Dataset | None:
        if lock:
            existing_id = connection.scalar(
                sa.text(
                    """
                    SELECT id
                    FROM daily_datasets
                    WHERE id = :dataset_id
                    LIMIT 1
                    """
                ),
                {"dataset_id": dataset_id},
            )
            if existing_id is None:
                return None
            self._lock_dataset_rows(connection, (dataset_id,))

        row = (
            connection.execute(
                sa.text(
                    """
                    SELECT id, site_id, report_date, report_type
                    FROM daily_datasets
                    WHERE id = :dataset_id
                    LIMIT 1
                    """
                ),
                {"dataset_id": dataset_id},
            )
            .mappings()
            .first()
        )
        dataset = self._dataset_from_row(row)
        if lock and dataset is None:
            raise TargetConflict("daily dataset disappeared after its lock")
        return dataset

    @staticmethod
    def _dataset_from_row(
        row: Mapping[str, Any] | RowMapping | None,
    ) -> _Dataset | None:
        if row is None:
            return None
        report_date = row["report_date"]
        if not isinstance(report_date, date):
            raise DatasetError("daily dataset contains an invalid report date")
        return _Dataset(
            dataset_id=int(cast(Any, row["id"])),
            site_id=int(cast(Any, row["site_id"])),
            report_date=report_date,
            report_type=_as_report_type(row["report_type"]),
        )

    def _active_version(
        self,
        connection: Connection,
        dataset_id: int,
    ) -> _Version | None:
        pointer = (
            connection.execute(
                sa.text(
                    """
                    SELECT version_id, version_status
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
        if pointer is None:
            return None
        version = self._version_by_id(
            connection,
            dataset_id=dataset_id,
            version_id=int(pointer["version_id"]),
            lock=True,
        )
        if version.status != pointer["version_status"]:
            raise DatasetError("active draft pointer status is inconsistent")
        if version.status not in {"draft", "ready_for_publish"}:
            raise SealedVersionConflict("active draft points to a sealed version")
        return version

    @staticmethod
    def _publication_version_id(
        connection: Connection,
        dataset_id: int,
    ) -> int | None:
        value = connection.scalar(
            sa.text(
                """
                SELECT version_id
                FROM dataset_publications
                WHERE dataset_id = :dataset_id
                FOR UPDATE
                """
            ),
            {"dataset_id": dataset_id},
        )
        return int(value) if value is not None else None

    def _version_by_id(
        self,
        connection: Connection,
        *,
        dataset_id: int,
        version_id: int,
        lock: bool,
    ) -> _Version:
        suffix = " FOR UPDATE" if lock else ""
        row = (
            connection.execute(
                sa.text(
                    """
                    SELECT dataset_id, id, report_type, version_no, status,
                           data_revision, review_revision, ruleset_version,
                           created_by
                    FROM dataset_versions
                    WHERE dataset_id = :dataset_id
                      AND id = :version_id
                    LIMIT 1
                    """
                    + suffix
                ),
                {"dataset_id": dataset_id, "version_id": version_id},
            )
            .mappings()
            .first()
        )
        if row is None:
            raise ActiveDraftConflict("expected dataset version does not exist")
        return _Version(
            dataset_id=int(row["dataset_id"]),
            version_id=int(row["id"]),
            report_type=_as_report_type(row["report_type"]),
            version_no=int(row["version_no"]),
            status=str(row["status"]),
            data_revision=int(row["data_revision"]),
            review_revision=int(row["review_revision"]),
            ruleset_version=str(row["ruleset_version"]),
            created_by=int(row["created_by"]),
        )

    def _version_by_global_id(
        self,
        connection: Connection,
        *,
        version_id: int,
    ) -> _Version:
        dataset_id = connection.scalar(
            sa.text(
                """
                SELECT dataset_id
                FROM dataset_versions
                WHERE id = :version_id
                LIMIT 1
                """
            ),
            {"version_id": version_id},
        )
        if dataset_id is None:
            raise ActiveDraftConflict("expected dataset version does not exist")
        return self._version_by_id(
            connection,
            dataset_id=int(dataset_id),
            version_id=version_id,
            lock=False,
        )

    @staticmethod
    def _assert_expected_active(
        expected: VersionExpectation | None,
        actual: _Version | None,
    ) -> None:
        if expected is None:
            if actual is not None:
                raise ActiveDraftConflict(
                    expected=None,
                    actual=actual.expectation,
                )
            return
        if actual is None or actual.version_id != expected.version_id:
            raise ActiveDraftConflict(
                expected=expected,
                actual=actual.expectation if actual is not None else None,
            )
        if actual.status not in {"draft", "ready_for_publish"}:
            raise SealedVersionConflict("expected active draft is already sealed")
        if (
            actual.data_revision != expected.data_revision
            or actual.review_revision != expected.review_revision
        ):
            raise RevisionConflict(expected=expected, actual=actual.expectation)

    def _baseline_rows(
        self,
        connection: Connection,
        *,
        baseline_id: int,
        report_type: ReportType,
    ) -> tuple[_StoredRow, ...]:
        columns = (
            _BUSINESS_COLUMNS if report_type == "business_report" else _RETURN_COLUMNS
        )
        typed_table = (
            "business_parse_baseline_rows"
            if report_type == "business_report"
            else "return_parse_baseline_rows"
        )
        selected_columns = ", ".join(f"typed.{name}" for name in columns)
        rows = (
            connection.execute(
                sa.text(
                    f"""
                    SELECT base.id AS source_row_id,
                           base.row_ordinal AS source_ordinal,
                           base.parsed_source_row_id AS original_source_row_id,
                           {selected_columns}
                    FROM parse_baseline_rows AS base
                    INNER JOIN {typed_table} AS typed
                        ON typed.parse_baseline_row_id = base.id
                       AND typed.parse_baseline_id = base.parse_baseline_id
                    WHERE base.parse_baseline_id = :baseline_id
                      AND base.report_type = :report_type
                    ORDER BY base.row_ordinal, base.id
                    """
                ),
                {"baseline_id": baseline_id, "report_type": report_type},
            )
            .mappings()
            .all()
        )
        return tuple(
            _StoredRow(
                source_row_id=int(row["source_row_id"]),
                source_ordinal=int(row["source_ordinal"]),
                logical_row_id=None,
                row_state="active",
                original_parsed_source_row_id=int(row["original_source_row_id"]),
                source_parse_baseline_row_id=int(row["source_row_id"]),
                values=_row_values(row, columns),
            )
            for row in rows
        )

    def _version_rows(
        self,
        connection: Connection,
        version: _Version,
        *,
        lock: bool = True,
    ) -> tuple[_StoredRow, ...]:
        columns = (
            _BUSINESS_COLUMNS
            if version.report_type == "business_report"
            else _RETURN_COLUMNS
        )
        typed_table = (
            "business_report_rows"
            if version.report_type == "business_report"
            else "return_report_rows"
        )
        selected_columns = ", ".join(f"typed.{name}" for name in columns)
        parameters = {
            "version_id": version.version_id,
            "report_type": version.report_type,
        }
        if lock:
            tuple(
                connection.scalars(
                    sa.text(
                        f"""
                        SELECT row_records.id
                        FROM version_rows AS row_records
                        INNER JOIN {typed_table} AS typed
                            ON typed.version_row_id = row_records.id
                           AND typed.version_id = row_records.version_id
                        WHERE row_records.version_id = :version_id
                          AND row_records.report_type = :report_type
                        ORDER BY row_records.row_ordinal, row_records.id
                        FOR UPDATE
                        """
                    ),
                    parameters,
                )
            )
        rows = (
            connection.execute(
                sa.text(
                    f"""
                    SELECT row_records.id AS source_row_id,
                           row_records.row_ordinal AS source_ordinal,
                           row_records.logical_row_id, row_records.row_state,
                           row_records.original_parsed_source_row_id,
                           base.source_parse_baseline_row_id,
                           {selected_columns}
                    FROM version_rows AS row_records
                    INNER JOIN {typed_table} AS typed
                        ON typed.version_row_id = row_records.id
                       AND typed.version_id = row_records.version_id
                    LEFT JOIN version_base_rows AS base
                        ON base.id = row_records.base_row_id
                       AND base.version_id = row_records.version_id
                    WHERE row_records.version_id = :version_id
                      AND row_records.report_type = :report_type
                    ORDER BY row_records.row_ordinal, row_records.id
                    """
                ),
                parameters,
            )
            .mappings()
            .all()
        )
        stored: list[_StoredRow] = []
        for row in rows:
            logical = _as_bytes(
                row["logical_row_id"],
                length=16,
                label="logical row ID",
            )
            row_state = str(row["row_state"])
            if row_state not in {"active", "excluded", "deleted"}:
                raise DatasetError("version row contains an invalid state")
            stored.append(
                _StoredRow(
                    source_row_id=int(row["source_row_id"]),
                    source_ordinal=int(row["source_ordinal"]),
                    logical_row_id=UUID(bytes=logical),
                    row_state=cast(Any, row_state),
                    original_parsed_source_row_id=(
                        int(row["original_parsed_source_row_id"])
                        if row["original_parsed_source_row_id"] is not None
                        else None
                    ),
                    source_parse_baseline_row_id=(
                        int(row["source_parse_baseline_row_id"])
                        if row["source_parse_baseline_row_id"] is not None
                        else None
                    ),
                    values=_row_values(row, columns),
                )
            )
        return tuple(stored)

    @staticmethod
    def _version_inputs(
        connection: Connection,
        version_id: int,
    ) -> tuple[tuple[int, str], ...]:
        return tuple(
            (int(row["batch_id"]), str(row["input_role"]))
            for row in connection.execute(
                sa.text(
                    """
                    SELECT batch_id, input_role
                    FROM version_input_batches
                    WHERE version_id = :version_id
                    ORDER BY input_ordinal, batch_id
                    """
                ),
                {"version_id": version_id},
            )
            .mappings()
            .all()
        )

    @staticmethod
    def _merge_inputs(
        *groups: Iterable[tuple[int, str]],
    ) -> tuple[tuple[int, str], ...]:
        merged: list[tuple[int, str]] = []
        seen: set[int] = set()
        for group in groups:
            for batch_id, role in group:
                if batch_id in seen:
                    continue
                seen.add(batch_id)
                merged.append((batch_id, role))
        return tuple(merged)

    def _snapshot_plan(
        self,
        *,
        report_type: ReportType,
        ruleset_version: str,
        members: Sequence[_MemberPlan],
        decisions: tuple[MergeDecision, ...],
        preserve_source_logical_ids: bool,
    ) -> _SnapshotPlan:
        if not members or len(members) > 2:
            raise DatasetError("stage-five snapshots require one or two members")
        by_identity = {
            (plan.member.member_type, plan.member.source_id): plan for plan in members
        }
        ordered_members = order_snapshot_members(plan.member for plan in members)
        ordered_plans = tuple(
            by_identity[(member.member_type, member.source_id)]
            for member in ordered_members
        )
        target_rows: tuple[MergeRow, ...] = ()
        source_rows: tuple[MergeRow, ...] = ()
        row_lookup: dict[tuple[int, int], _StoredRow] = {}

        if len(ordered_plans) == 1:
            only = ordered_plans[0]
            converted = tuple(
                row.as_merge_row(member_ordinal=1, report_type=report_type)
                for row in only.rows
            )
            for row in only.rows:
                row_lookup[(1, row.source_row_id)] = row
            if only.member.member_type == "dataset_version":
                target_rows = converted
            else:
                source_rows = converted
        else:
            target_plan, source_plan = ordered_plans
            if target_plan.member.member_type != "dataset_version":
                raise DatasetError("the first merge member must be a dataset version")
            target_rows = tuple(
                row.as_merge_row(member_ordinal=1, report_type=report_type)
                for row in target_plan.rows
            )
            source_rows = tuple(
                row.as_merge_row(member_ordinal=2, report_type=report_type)
                for row in source_plan.rows
            )
            for row in target_plan.rows:
                row_lookup[(1, row.source_row_id)] = row
            for row in source_plan.rows:
                row_lookup[(2, row.source_row_id)] = row

        allocated = {
            row.logical_row_id for row in target_rows if row.logical_row_id is not None
        }

        def source_id_factory(row: MergeRow) -> UUID:
            candidate = row.logical_row_id if preserve_source_logical_ids else None
            if candidate is None or candidate in allocated:
                candidate = uuid4()
                while candidate in allocated:
                    candidate = uuid4()
            allocated.add(candidate)
            return candidate

        merged = merge_rows(
            target_rows=target_rows,
            source_rows=source_rows,
            decisions=decisions,
            source_logical_id_factory=source_id_factory,
        )
        digest = canonical_snapshot_digest(
            report_type=report_type,
            ruleset_version=ruleset_version,
            rows=merged,
        )
        return _SnapshotPlan(
            members=ordered_plans,
            rows=merged,
            source_rows=row_lookup,
            decisions=decisions,
            digest=digest,
            totals_json=_snapshot_totals(report_type, merged),
        )

    def _create_draft_version(
        self,
        connection: Connection,
        *,
        dataset: _Dataset,
        ruleset_version: str,
        snapshot_kind: str,
        plan: _SnapshotPlan,
        actor_user_id: int,
        occurred_at: datetime,
        parents: Sequence[tuple[_Version, str]],
        input_batches: Sequence[tuple[int, str]],
    ) -> _Version:
        next_version = connection.scalar(
            sa.text(
                """
                SELECT COALESCE(MAX(version_no), 0) + 1
                FROM dataset_versions
                WHERE dataset_id = :dataset_id
                """
            ),
            {"dataset_id": dataset.dataset_id},
        )
        if next_version is None:
            raise DatasetError("could not allocate a dataset version number")
        version_no = int(next_version)
        inserted = connection.execute(
            sa.text(
                """
                INSERT INTO dataset_versions (
                    dataset_id, report_type, version_no, status,
                    data_revision, review_revision, ruleset_version,
                    created_by, created_at, sealed_at
                ) VALUES (
                    :dataset_id, :report_type, :version_no, 'draft',
                    0, 0, :ruleset_version,
                    :created_by, :created_at, NULL
                )
                """
            ),
            {
                "dataset_id": dataset.dataset_id,
                "report_type": dataset.report_type,
                "version_no": version_no,
                "ruleset_version": ruleset_version,
                "created_by": actor_user_id,
                "created_at": occurred_at,
            },
        )
        if inserted.lastrowid is None:
            raise DatasetError("database did not return a dataset version ID")
        version_id = int(inserted.lastrowid)
        snapshot = connection.execute(
            sa.text(
                """
                INSERT INTO version_base_snapshots (
                    version_id, report_type, snapshot_kind, data_digest,
                    row_count, totals_json, created_at
                ) VALUES (
                    :version_id, :report_type, :snapshot_kind, :data_digest,
                    :row_count, :totals_json, :created_at
                )
                """
            ),
            {
                "version_id": version_id,
                "report_type": dataset.report_type,
                "snapshot_kind": snapshot_kind,
                "data_digest": plan.digest,
                "row_count": len(plan.rows),
                "totals_json": plan.totals_json,
                "created_at": occurred_at,
            },
        )
        if snapshot.lastrowid is None:
            raise DatasetError("database did not return a base snapshot ID")
        snapshot_id = int(snapshot.lastrowid)

        member_ids: dict[int, int] = {}
        decisions_json = _merge_decisions_json(plan.decisions)
        for ordinal, member_plan in enumerate(plan.members, start=1):
            member = member_plan.member
            inserted_member = connection.execute(
                sa.text(
                    """
                    INSERT INTO version_base_snapshot_members (
                        snapshot_id, member_ordinal, member_type, member_role,
                        parse_baseline_id, parent_version_id, decision_json,
                        report_type, created_at
                    ) VALUES (
                        :snapshot_id, :member_ordinal, :member_type, :member_role,
                        :parse_baseline_id, :parent_version_id, :decision_json,
                        :report_type, :created_at
                    )
                    """
                ),
                {
                    "snapshot_id": snapshot_id,
                    "member_ordinal": ordinal,
                    "member_type": member.member_type,
                    "member_role": member.member_role,
                    "parse_baseline_id": (
                        member.source_id
                        if member.member_type == "parse_baseline"
                        else None
                    ),
                    "parent_version_id": (
                        member.source_id
                        if member.member_type == "dataset_version"
                        else None
                    ),
                    "decision_json": (
                        decisions_json if ordinal == len(plan.members) else None
                    ),
                    "report_type": dataset.report_type,
                    "created_at": occurred_at,
                },
            )
            if inserted_member.lastrowid is None:
                raise DatasetError("database did not return a snapshot member ID")
            member_ids[ordinal] = int(inserted_member.lastrowid)

        # Row columns are only a convenience projection. The complete pair-level
        # record remains the snapshot member's decision_json for multi-row conflicts.
        decision_by_target, decision_by_source = _single_merge_decisions_by_row(
            plan.decisions
        )
        workbench_rows: list[SnapshotRowSource] = []
        for row in plan.rows:
            source = plan.source_rows[(row.member_ordinal, row.source_row_id)]
            decision = (
                decision_by_target.get(row.source_row_id)
                if row.origin == "target"
                else decision_by_source.get(row.source_row_id)
            )
            base = connection.execute(
                sa.text(
                    """
                    INSERT INTO version_base_rows (
                        version_id, snapshot_id, report_type, logical_row_id,
                        row_ordinal, source_member_id,
                        source_parse_baseline_row_id,
                        original_parsed_source_row_id, row_state,
                        merge_action, merge_reason, provenance_json, created_at
                    ) VALUES (
                        :version_id, :snapshot_id, :report_type, :logical_row_id,
                        :row_ordinal, :source_member_id,
                        :source_parse_baseline_row_id,
                        :original_parsed_source_row_id, :row_state,
                        :merge_action, :merge_reason, :provenance_json, :created_at
                    )
                    """
                ),
                {
                    "version_id": version_id,
                    "snapshot_id": snapshot_id,
                    "report_type": dataset.report_type,
                    "logical_row_id": row.logical_row_id.bytes,
                    "row_ordinal": row.row_ordinal,
                    "source_member_id": member_ids[row.member_ordinal],
                    "source_parse_baseline_row_id": (
                        source.source_parse_baseline_row_id
                    ),
                    "original_parsed_source_row_id": (
                        source.original_parsed_source_row_id
                    ),
                    "row_state": row.row_state,
                    "merge_action": decision.action if decision is not None else None,
                    "merge_reason": decision.reason if decision is not None else None,
                    "provenance_json": _canonical_json(
                        {
                            "member_ordinal": row.member_ordinal,
                            "origin": row.origin,
                            "source_row_id": row.source_row_id,
                        }
                    ),
                    "created_at": occurred_at,
                },
            )
            if base.lastrowid is None:
                raise DatasetError("database did not return a version base row ID")
            base_row_id = int(base.lastrowid)
            self._insert_typed_base_row(
                connection,
                report_type=dataset.report_type,
                version_id=version_id,
                base_row_id=base_row_id,
                values=dict(row.values),
            )
            current = connection.execute(
                sa.text(
                    """
                    INSERT INTO version_rows (
                        version_id, report_type, logical_row_id, row_ordinal,
                        row_state, base_row_id, original_parsed_source_row_id,
                        created_at, updated_at
                    ) VALUES (
                        :version_id, :report_type, :logical_row_id, :row_ordinal,
                        :row_state, :base_row_id, :original_source_row_id,
                        :created_at, :updated_at
                    )
                    """
                ),
                {
                    "version_id": version_id,
                    "report_type": dataset.report_type,
                    "logical_row_id": row.logical_row_id.bytes,
                    "row_ordinal": row.row_ordinal,
                    "row_state": row.row_state,
                    "base_row_id": base_row_id,
                    "original_source_row_id": source.original_parsed_source_row_id,
                    "created_at": occurred_at,
                    "updated_at": occurred_at,
                },
            )
            if current.lastrowid is None:
                raise DatasetError("database did not return a version row ID")
            version_row_id = int(current.lastrowid)
            self._insert_typed_version_row(
                connection,
                report_type=dataset.report_type,
                version_id=version_id,
                version_row_id=version_row_id,
                values=dict(row.values),
            )
            if row.row_state == "active":
                seller_sku = dict(row.values).get("sku")
                if not isinstance(seller_sku, str):
                    raise DatasetError("active report row has no Seller SKU")
                append_report_source_key(
                    connection,
                    dataset_id=dataset.dataset_id,
                    version_id=version_id,
                    source_row_id=version_row_id,
                    report_type=dataset.report_type,
                    seller_sku_raw=seller_sku,
                    source_key_revision=0,
                    occurred_at=occurred_at,
                )
            workbench_rows.append(
                SnapshotRowSource(
                    version_row_id=version_row_id,
                    member_ordinal=row.member_ordinal,
                    source_row_id=source.source_row_id,
                    original_parsed_source_row_id=(
                        source.original_parsed_source_row_id
                    ),
                )
            )

        self._workbench_snapshots.materialize_version(
            connection,
            version_id=version_id,
            report_type=dataset.report_type,
            ruleset_version=ruleset_version,
            members=tuple(
                SchemaMember(
                    member_ordinal=ordinal,
                    member_type=member_plan.member.member_type,
                    source_id=member_plan.member.source_id,
                )
                for ordinal, member_plan in enumerate(plan.members, start=1)
            ),
            rows=workbench_rows,
            occurred_at=occurred_at,
        )

        for ordinal, (parent, lineage_type) in enumerate(parents, start=1):
            connection.execute(
                sa.text(
                    """
                    INSERT INTO version_parent_versions (
                        child_version_id, parent_version_id, parent_ordinal,
                        lineage_type, report_type, created_at
                    ) VALUES (
                        :child_version_id, :parent_version_id, :parent_ordinal,
                        :lineage_type, :report_type, :created_at
                    )
                    """
                ),
                {
                    "child_version_id": version_id,
                    "parent_version_id": parent.version_id,
                    "parent_ordinal": ordinal,
                    "lineage_type": lineage_type,
                    "report_type": dataset.report_type,
                    "created_at": occurred_at,
                },
            )
        for ordinal, (batch_id, input_role) in enumerate(input_batches, start=1):
            connection.execute(
                sa.text(
                    """
                    INSERT INTO version_input_batches (
                        version_id, batch_id, input_ordinal, input_role, created_at
                    ) VALUES (
                        :version_id, :batch_id, :input_ordinal,
                        :input_role, :created_at
                    )
                    """
                ),
                {
                    "version_id": version_id,
                    "batch_id": batch_id,
                    "input_ordinal": ordinal,
                    "input_role": input_role,
                    "created_at": occurred_at,
                },
            )
        return _Version(
            dataset_id=dataset.dataset_id,
            version_id=version_id,
            report_type=dataset.report_type,
            version_no=version_no,
            status="draft",
            data_revision=0,
            review_revision=0,
            ruleset_version=ruleset_version,
            created_by=actor_user_id,
        )

    @staticmethod
    def _insert_typed_base_row(
        connection: Connection,
        *,
        report_type: ReportType,
        version_id: int,
        base_row_id: int,
        values: Mapping[str, SnapshotScalar],
    ) -> None:
        columns = (
            _BUSINESS_COLUMNS if report_type == "business_report" else _RETURN_COLUMNS
        )
        table = (
            "business_version_base_rows"
            if report_type == "business_report"
            else "return_version_base_rows"
        )
        column_sql = ", ".join(columns)
        value_sql = ", ".join(f":{name}" for name in columns)
        parameters = {name: _database_value(values[name]) for name in columns}
        connection.execute(
            sa.text(
                f"""
                INSERT INTO {table} (
                    version_base_row_id, version_id, {column_sql}
                ) VALUES (
                    :base_row_id, :version_id, {value_sql}
                )
                """
            ),
            {
                "base_row_id": base_row_id,
                "version_id": version_id,
                **parameters,
            },
        )

    @staticmethod
    def _insert_typed_version_row(
        connection: Connection,
        *,
        report_type: ReportType,
        version_id: int,
        version_row_id: int,
        values: Mapping[str, SnapshotScalar],
    ) -> None:
        columns = (
            _BUSINESS_COLUMNS if report_type == "business_report" else _RETURN_COLUMNS
        )
        table = (
            "business_report_rows"
            if report_type == "business_report"
            else "return_report_rows"
        )
        column_sql = ", ".join(columns)
        value_sql = ", ".join(f":{name}" for name in columns)
        parameters = {name: _database_value(values[name]) for name in columns}
        connection.execute(
            sa.text(
                f"""
                INSERT INTO {table} (
                    version_row_id, version_id, {column_sql}
                ) VALUES (
                    :version_row_id, :version_id, {value_sql}
                )
                """
            ),
            {
                "version_row_id": version_row_id,
                "version_id": version_id,
                **parameters,
            },
        )

    @staticmethod
    def _insert_draft_pointer(
        connection: Connection,
        *,
        dataset_id: int,
        version_id: int,
        occurred_at: datetime,
    ) -> None:
        try:
            connection.execute(
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
                    "dataset_id": dataset_id,
                    "version_id": version_id,
                    "pointed_at": occurred_at,
                },
            )
        except IntegrityError as error:
            if _mysql_error_code(error) == 1062:
                raise ActiveDraftConflict(
                    "another transaction created an active draft"
                ) from error
            raise

    @staticmethod
    def _switch_draft_pointer(
        connection: Connection,
        *,
        dataset_id: int,
        old_version: _Version,
        new_version_id: int,
        occurred_at: datetime,
    ) -> None:
        updated = connection.execute(
            sa.text(
                """
                UPDATE dataset_drafts
                SET version_id = :new_version_id,
                    version_status = 'draft',
                    pointed_at = :pointed_at
                WHERE dataset_id = :dataset_id
                  AND version_id = :old_version_id
                  AND version_status = :old_status
                """
            ),
            {
                "dataset_id": dataset_id,
                "old_version_id": old_version.version_id,
                "old_status": old_version.status,
                "new_version_id": new_version_id,
                "pointed_at": occurred_at,
            },
        )
        if updated.rowcount != 1:
            raise ActiveDraftConflict(
                "active draft pointer changed before successor switch"
            )

    @staticmethod
    def _discard_version(
        connection: Connection,
        *,
        version: _Version,
        operation_token: UUID,
        operation_kind: _OperationKind,
        operation_digest: bytes,
        actor_user_id: int,
        event_type: _DispositionKind,
        reason: str,
        occurred_at: datetime,
        successor_dataset_id: int | None,
        successor_version_id: int | None,
    ) -> None:
        updated = connection.execute(
            sa.text(
                """
                UPDATE dataset_versions
                SET status = 'discarded', sealed_at = :sealed_at
                WHERE dataset_id = :dataset_id
                  AND id = :version_id
                  AND status = :status
                  AND data_revision = :data_revision
                  AND review_revision = :review_revision
                  AND sealed_at IS NULL
                """
            ),
            {
                "sealed_at": occurred_at,
                "dataset_id": version.dataset_id,
                "version_id": version.version_id,
                "status": version.status,
                "data_revision": version.data_revision,
                "review_revision": version.review_revision,
            },
        )
        if updated.rowcount != 1:
            raise RevisionConflict(
                "draft changed before it could be sealed",
                expected=version.expectation,
            )
        connection.execute(
            sa.text(
                """
                INSERT INTO draft_disposition_events (
                    operation_token, operation_kind, operation_digest,
                    dataset_id, version_id, event_type,
                    successor_dataset_id, successor_version_id,
                    actor_user_id, terminal_data_revision,
                    terminal_review_revision, reason, occurred_at
                ) VALUES (
                    :operation_token, :operation_kind, :operation_digest,
                    :dataset_id, :version_id, :event_type,
                    :successor_dataset_id, :successor_version_id,
                    :actor_user_id, :data_revision,
                    :review_revision, :reason, :occurred_at
                )
                """
            ),
            {
                "operation_token": operation_token.bytes,
                "operation_kind": operation_kind,
                "operation_digest": operation_digest,
                "dataset_id": version.dataset_id,
                "version_id": version.version_id,
                "event_type": event_type,
                "successor_dataset_id": successor_dataset_id,
                "successor_version_id": successor_version_id,
                "actor_user_id": actor_user_id,
                "data_revision": version.data_revision,
                "review_revision": version.review_revision,
                "reason": reason,
                "occurred_at": occurred_at,
            },
        )

    @staticmethod
    def _insert_audit(
        connection: Connection,
        *,
        site_id: int,
        actor_user_id: int,
        event_type: str,
        object_type: str,
        object_id: str,
        operation_token: UUID,
        payload: Mapping[str, object],
        occurred_at: datetime,
    ) -> None:
        connection.execute(
            sa.text(
                """
                INSERT INTO audit_events (
                    site_id, actor_user_id, event_type, object_type,
                    object_id, request_id, redacted_payload, occurred_at
                ) VALUES (
                    :site_id, :actor_user_id, :event_type, :object_type,
                    :object_id, :request_id, :payload, :occurred_at
                )
                """
            ),
            {
                "site_id": site_id,
                "actor_user_id": actor_user_id,
                "event_type": event_type,
                "object_type": object_type,
                "object_id": object_id,
                "request_id": str(operation_token),
                "payload": _canonical_json(dict(payload)),
                "occurred_at": occurred_at,
            },
        )

    def _record_result(
        self,
        connection: Connection,
        *,
        operation_token: UUID,
        operation_kind: _OperationKind,
        operation_digest: bytes,
        actor_user_id: int,
        result_kind: _ResultKind,
        version: _Version,
        occurred_at: datetime,
        superseded_version_ids: tuple[int, ...],
        source_dataset_id: int | None,
        source_version_id: int | None,
        status_override: Literal["cancelled"] | None = None,
    ) -> DraftMutationResult:
        result_status = status_override or version.status
        if result_status not in {"draft", "discarded", "cancelled"}:
            raise DatasetError("draft operation produced an invalid result status")
        _validate_operation_result_semantics(
            operation_kind=operation_kind,
            result_kind=result_kind,
            result_status=result_status,
        )
        result = DraftMutationResult(
            operation_token=operation_token,
            dataset_id=version.dataset_id,
            version_id=version.version_id,
            version_no=version.version_no,
            status=cast(Any, result_status),
            data_revision=version.data_revision,
            review_revision=version.review_revision,
            superseded_version_ids=superseded_version_ids,
            source_dataset_id=source_dataset_id,
            source_version_id=source_version_id,
        )
        superseded_1 = (
            result.superseded_version_ids[0]
            if len(result.superseded_version_ids) >= 1
            else None
        )
        superseded_2 = (
            result.superseded_version_ids[1]
            if len(result.superseded_version_ids) >= 2
            else None
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
                    source_dataset_id, source_version_id, completed_at
                ) VALUES (
                    :operation_token, :operation_kind, :operation_digest,
                    :actor_user_id, :result_kind,
                    :result_dataset_id, :result_version_id,
                    :result_version_no, :result_status,
                    :result_data_revision, :result_review_revision,
                    :superseded_version_id_1, :superseded_version_id_2,
                    :source_dataset_id, :source_version_id, :completed_at
                )
                """
            ),
            {
                "operation_token": operation_token.bytes,
                "operation_kind": operation_kind,
                "operation_digest": operation_digest,
                "actor_user_id": actor_user_id,
                "result_kind": result_kind,
                "result_dataset_id": version.dataset_id,
                "result_version_id": version.version_id,
                "result_version_no": version.version_no,
                "result_status": result_status,
                "result_data_revision": version.data_revision,
                "result_review_revision": version.review_revision,
                "superseded_version_id_1": superseded_1,
                "superseded_version_id_2": superseded_2,
                "source_dataset_id": source_dataset_id,
                "source_version_id": source_version_id,
                "completed_at": occurred_at,
            },
        )
        return result


def _snapshot_value(value: object) -> SnapshotScalar:
    if value is None or isinstance(value, (bool, int, str, Decimal, UUID)):
        return value
    if isinstance(value, datetime):
        if value.tzinfo is None or value.utcoffset() is None:
            return value.replace(tzinfo=UTC)
        return value.astimezone(UTC)
    if isinstance(value, date):
        return value
    raise DatasetError("typed row contains an unsupported database value")


def _row_values(
    row: Mapping[str, Any] | RowMapping,
    columns: Sequence[str],
) -> tuple[tuple[str, SnapshotScalar], ...]:
    return tuple((name, _snapshot_value(row[name])) for name in columns)


def _database_value(value: SnapshotScalar) -> object:
    if isinstance(value, datetime):
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("snapshot datetimes must be timezone-aware")
        return value.astimezone(UTC).replace(tzinfo=None)
    if isinstance(value, UUID):
        return value.bytes
    return value


def _fingerprint_value(value: SnapshotScalar) -> object:
    if isinstance(value, datetime):
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("fingerprint datetimes must be timezone-aware")
        return value.astimezone(UTC).isoformat(timespec="microseconds")
    if isinstance(value, date):
        return value.isoformat()
    if isinstance(value, Decimal):
        return format(value.normalize(), "f")
    if isinstance(value, UUID):
        return str(value)
    return value


def _conflict_key(
    report_type: ReportType,
    values: Sequence[tuple[str, SnapshotScalar]],
) -> str | None:
    row = dict(values)
    names: tuple[str, ...]
    if report_type == "business_report":
        names = ("child_asin", "sku")
    else:
        names = (
            "return_date",
            "order_id",
            "sku",
            "asin",
            "fnsku",
            "quantity",
            "license_plate_number",
        )
    selected = [row.get(name) for name in names]
    if any(value is None or value == "" for value in selected):
        return None
    encoded = _canonical_json([_fingerprint_value(value) for value in selected]).encode(
        "utf-8"
    )
    return hashlib.sha256(encoded).hexdigest()


def _canonical_decimal(value: Decimal) -> str:
    if value == 0:
        return "0"
    return format(value.normalize(), "f")


def _snapshot_totals(
    report_type: ReportType,
    rows: Sequence[MergedSnapshotRow],
) -> str:
    total_columns = (
        _BUSINESS_TOTAL_COLUMNS if report_type == "business_report" else ("quantity",)
    )
    totals = {name: Decimal(0) for name in total_columns}
    for row in rows:
        if row.row_state != "active":
            continue
        values = dict(row.values)
        for name in total_columns:
            value = values.get(name)
            if value is None:
                continue
            if isinstance(value, bool) or not isinstance(value, (int, Decimal)):
                raise DatasetError(f"snapshot total field {name} is not numeric")
            totals[name] += Decimal(value)
    return _canonical_json(
        {name: _canonical_decimal(totals[name]) for name in sorted(totals)}
    )
