from __future__ import annotations

from collections import deque
from collections.abc import Mapping
from datetime import UTC, date, datetime
from typing import Any, Literal, cast
from uuid import UUID

import pytest
from app.datasets.repository import (
    MySqlDatasetRepository,
    _Actor,
    _Baseline,
    _Dataset,
    _merge_decisions_json,
    _single_merge_decisions_by_row,
    _Version,
)
from app.datasets.types import (
    ActiveDraftReassignmentTarget,
    DatasetCommitOutcomeUnknown,
    DatasetError,
    DatasetTransactionBusy,
    DraftMutationResult,
    MaterializeBaselineCommand,
    MergeDecision,
    ReassignUnpublishedDraftDateCommand,
)
from sqlalchemy.engine import Connection, Engine
from sqlalchemy.exc import DBAPIError

TOKEN = UUID("aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa")
DIGEST = bytes.fromhex("11" * 32)
OCCURRED_AT = datetime(2026, 8, 8, 3, 15, tzinfo=UTC)
NOW = OCCURRED_AT.replace(tzinfo=None)


class _MappingResult:
    def __init__(
        self,
        row: Mapping[str, object] | None = None,
        *,
        rowcount: int = 1,
    ) -> None:
        self._row = row
        self.rowcount = rowcount

    def mappings(self) -> _MappingResult:
        return self

    def first(self) -> Mapping[str, object] | None:
        return self._row


class _RowsResult(_MappingResult):
    def __init__(self, rows: tuple[Mapping[str, object], ...]) -> None:
        super().__init__()
        self._rows = rows

    def all(self) -> tuple[Mapping[str, object], ...]:
        return self._rows


class _InsertResult(_MappingResult):
    def __init__(self, lastrowid: int) -> None:
        super().__init__()
        self.lastrowid = lastrowid


class _RecoveryConnection:
    def __init__(
        self,
        *,
        result_row: Mapping[str, object],
        operation_kind: str = "materialize_baseline",
        historical_successor_ids: tuple[int, ...] = (),
    ) -> None:
        self.result_row = result_row
        self.operation_kind = operation_kind
        self.historical_successor_ids = historical_successor_ids
        self.executions: list[tuple[str, dict[str, object]]] = []
        self.disposition_queries: list[tuple[str, dict[str, object]]] = []

    def execute(
        self,
        statement: object,
        parameters: Mapping[str, object] | None = None,
    ) -> _MappingResult:
        sql = str(statement)
        bound = dict(parameters or {})
        self.executions.append((sql, bound))
        if "FROM draft_operation_tokens" in sql:
            return _MappingResult(
                {
                    "operation_kind": self.operation_kind,
                    "operation_digest": DIGEST,
                    "actor_user_id": 9,
                }
            )
        if "FROM draft_operation_results" in sql:
            return _MappingResult(self.result_row)
        raise AssertionError(f"unexpected execute statement: {sql}")

    def scalars(
        self,
        statement: object,
        parameters: Mapping[str, object] | None = None,
    ) -> tuple[int, ...]:
        sql = str(statement)
        bound = dict(parameters or {})
        self.disposition_queries.append((sql, bound))
        if bound.get("operation_token") == TOKEN.bytes:
            return ()
        return self.historical_successor_ids


class _RecordingConnection:
    def __init__(self) -> None:
        self.executions: list[tuple[str, dict[str, object]]] = []

    def execute(
        self,
        statement: object,
        parameters: Mapping[str, object] | None = None,
    ) -> _MappingResult:
        self.executions.append((str(statement), dict(parameters or {})))
        return _MappingResult(rowcount=1)


class _ActorConnection:
    def __init__(self) -> None:
        self.executions: list[str] = []

    def execute(
        self,
        statement: object,
        _parameters: Mapping[str, object] | None = None,
    ) -> _MappingResult:
        sql = str(statement)
        self.executions.append(sql)
        if "FROM users" not in sql:
            raise AssertionError(f"unexpected execute statement: {sql}")
        return _MappingResult({"id": 9, "status": "active"})

    def scalars(
        self,
        statement: object,
        _parameters: Mapping[str, object] | None = None,
    ) -> tuple[str, ...]:
        sql = str(statement)
        self.executions.append(sql)
        if "FROM user_roles" not in sql:
            raise AssertionError(f"unexpected scalar statement: {sql}")
        return ("data_manager",)


class _RetryConnection:
    def __init__(self, identity: int) -> None:
        self.identity = identity


class _BeginContext:
    def __init__(self, engine: _RetryEngine, connection: _RetryConnection) -> None:
        self._engine = engine
        self._connection = connection

    def __enter__(self) -> _RetryConnection:
        self._engine.events.append(("begin", self._connection.identity))
        return self._connection

    def __exit__(
        self,
        exception_type: type[BaseException] | None,
        _exception: BaseException | None,
        _traceback: object,
    ) -> Literal[False]:
        outcome = "rollback" if exception_type is not None else "commit"
        self._engine.events.append((outcome, self._connection.identity))
        return False


class _RetryEngine:
    def __init__(self) -> None:
        self.connections: list[_RetryConnection] = []
        self.events: list[tuple[str, int]] = []

    def begin(self) -> _BeginContext:
        connection = _RetryConnection(len(self.connections) + 1)
        self.connections.append(connection)
        return _BeginContext(self, connection)


class _MySqlDriverError(RuntimeError):
    pass


class _StopAfterRowLock(RuntimeError):
    pass


def _repository() -> MySqlDatasetRepository:
    return MySqlDatasetRepository(cast(Engine, object()))


def _frozen_result_row(
    *,
    result_kind: str = "merged",
    result_status: str | None = None,
) -> dict[str, object]:
    status = result_status or ("cancelled" if result_kind == "cancelled" else "draft")
    return {
        "result_kind": result_kind,
        "result_dataset_id": 5,
        "result_version_id": 17,
        "source_dataset_id": 5 if result_kind != "cancelled" else None,
        "source_version_id": 11 if result_kind != "cancelled" else None,
        "result_version_no": 4,
        "result_status": status,
        "result_data_revision": 2,
        "result_review_revision": 3,
        "superseded_version_id_1": 11 if result_kind != "cancelled" else None,
        "superseded_version_id_2": None,
    }


def _draft_result() -> DraftMutationResult:
    return DraftMutationResult(
        operation_token=TOKEN,
        dataset_id=5,
        version_id=17,
        version_no=4,
        status="draft",
        data_revision=2,
        review_revision=3,
    )


def test_merge_decision_row_projection_preserves_only_single_pair_rows() -> None:
    decisions = (
        MergeDecision(101, 201, "keep_both", "Both rows are valid"),
        MergeDecision(102, 201, "keep_both", "Both rows are valid"),
    )

    projected = _single_merge_decisions_by_row(decisions)
    reordered = _single_merge_decisions_by_row(reversed(decisions))

    assert projected == ({101: decisions[0], 102: decisions[1]}, {})
    assert reordered == projected


def test_merge_decision_audit_json_is_stable_across_input_order() -> None:
    decisions = (
        MergeDecision(102, 202, "keep_both", "Both rows are valid"),
        MergeDecision(101, 201, "keep_target"),
    )

    assert _merge_decisions_json(decisions) == _merge_decisions_json(
        reversed(decisions)
    )


def test_merge_decision_row_projection_omits_many_to_many_rows() -> None:
    decisions = (
        MergeDecision(101, 201, "keep_both", "Both rows are valid"),
        MergeDecision(101, 202, "keep_both", "Both rows are valid"),
        MergeDecision(102, 201, "keep_both", "Both rows are valid"),
        MergeDecision(102, 202, "keep_both", "Both rows are valid"),
    )

    projected = _single_merge_decisions_by_row(decisions)
    reordered = _single_merge_decisions_by_row(reversed(decisions))

    assert projected == ({}, {})
    assert reordered == projected


def _mysql_error(
    code: int,
    *,
    connection_invalidated: bool = False,
) -> DBAPIError:
    return DBAPIError(
        statement="injected stage-five transaction",
        params=None,
        orig=_MySqlDriverError(code, "injected MySQL failure"),
        connection_invalidated=connection_invalidated,
    )


def _configure_retry_scenario(
    monkeypatch: Any,
    *,
    failures: tuple[DBAPIError, ...],
    recovery_results: tuple[DraftMutationResult | Exception | None, ...] = (),
) -> tuple[
    MySqlDatasetRepository,
    _RetryEngine,
    list[int],
    list[int],
    list[int],
    list[int],
    list[UUID],
]:
    engine = _RetryEngine()
    waits: list[int] = []

    def record_wait(retry_number: int) -> None:
        assert engine.events[-1][0] == "rollback"
        waits.append(retry_number)

    repository = MySqlDatasetRepository(
        cast(Engine, engine),
        retry_waiter=record_wait,
    )
    pending_failures = deque(failures)
    pending_recoveries = deque(recovery_results)
    claimed_connections: list[int] = []
    actor_connections: list[int] = []
    work_connections: list[int] = []
    recovery_calls: list[UUID] = []

    def recover_operation(**keywords: object) -> DraftMutationResult | None:
        operation_token = cast(UUID, keywords["operation_token"])
        recovery_calls.append(operation_token)
        if pending_recoveries:
            outcome = pending_recoveries.popleft()
            if isinstance(outcome, Exception):
                raise outcome
            return outcome
        return None

    def claim_operation(
        connection: _RetryConnection,
        **_keywords: object,
    ) -> None:
        claimed_connections.append(connection.identity)

    def load_actor(
        connection: _RetryConnection,
        actor_user_id: int,
    ) -> _Actor:
        actor_connections.append(connection.identity)
        return _Actor(actor_user_id, frozenset({"data_manager"}))

    def work(
        connection: Connection,
        _actor: _Actor,
        _timestamp: datetime,
    ) -> DraftMutationResult:
        retry_connection = cast(_RetryConnection, connection)
        work_connections.append(retry_connection.identity)
        if pending_failures:
            raise pending_failures.popleft()
        return _draft_result()

    monkeypatch.setattr(repository, "_recover_operation", recover_operation)
    monkeypatch.setattr(repository, "_claim_operation", claim_operation)
    monkeypatch.setattr(repository, "_load_actor", load_actor)
    monkeypatch.setattr(repository, "_retry_test_work", work, raising=False)
    return (
        repository,
        engine,
        waits,
        claimed_connections,
        actor_connections,
        work_connections,
        recovery_calls,
    )


def _execute_retry_scenario(
    repository: MySqlDatasetRepository,
) -> DraftMutationResult:
    work = cast(Any, repository)._retry_test_work
    return repository._execute_operation(
        operation_kind="materialize_baseline",
        operation_token=TOKEN,
        operation_digest=DIGEST,
        actor_user_id=9,
        occurred_at=OCCURRED_AT,
        work=work,
    )


def test_operation_recovery_uses_the_frozen_result_snapshot() -> None:
    connection = _RecoveryConnection(result_row=_frozen_result_row())

    result = _repository()._operation_result(
        cast(Connection, connection),
        operation_token=TOKEN,
        operation_kind="materialize_baseline",
        operation_digest=DIGEST,
        actor_user_id=9,
        require_result=True,
    )

    assert result is not None
    assert result.version_no == 4
    assert result.status == "draft"
    assert result.data_revision == 2
    assert result.review_revision == 3
    assert result.superseded_version_ids == (11,)
    result_query = next(
        sql
        for sql, _parameters in connection.executions
        if "draft_operation_results" in sql
    )
    assert "JOIN dataset_versions" not in result_query


def test_cancelled_recovery_ignores_dispositions_from_older_operations() -> None:
    connection = _RecoveryConnection(
        result_row=_frozen_result_row(result_kind="cancelled"),
        operation_kind="reassign_date",
        historical_successor_ids=(11,),
    )

    result = _repository()._operation_result(
        cast(Connection, connection),
        operation_token=TOKEN,
        operation_kind="reassign_date",
        operation_digest=DIGEST,
        actor_user_id=9,
        require_result=True,
    )

    assert result is not None
    assert result.status == "cancelled"
    assert result.superseded_version_ids == ()
    assert connection.disposition_queries == []


def test_cancelled_recovery_rejects_frozen_lineage_fields() -> None:
    frozen = _frozen_result_row(result_kind="cancelled")
    frozen["superseded_version_id_1"] = 11
    frozen["source_dataset_id"] = 5
    frozen["source_version_id"] = 11
    connection = _RecoveryConnection(
        result_row=frozen,
        operation_kind="reassign_date",
    )

    with pytest.raises(DatasetError, match="cannot contain lineage"):
        _repository()._operation_result(
            cast(Connection, connection),
            operation_token=TOKEN,
            operation_kind="reassign_date",
            operation_digest=DIGEST,
            actor_user_id=9,
            require_result=True,
        )


@pytest.mark.parametrize(
    ("operation_kind", "result_kind", "result_status"),
    (
        ("materialize_baseline", "force_rebuilt", "draft"),
        ("materialize_baseline", "created", "discarded"),
        ("force_rebuild", "created", "draft"),
        ("discard_draft", "discarded", "draft"),
        ("reassign_date", "cancelled", "draft"),
        ("reassign_date", "reassigned", "cancelled"),
    ),
)
def test_operation_recovery_rejects_inconsistent_terminal_semantics(
    operation_kind: Any,
    result_kind: str,
    result_status: str,
) -> None:
    connection = _RecoveryConnection(
        result_row=_frozen_result_row(
            result_kind=result_kind,
            result_status=result_status,
        ),
        operation_kind=operation_kind,
    )

    with pytest.raises(DatasetError, match="terminal result does not match"):
        _repository()._operation_result(
            cast(Connection, connection),
            operation_token=TOKEN,
            operation_kind=operation_kind,
            operation_digest=DIGEST,
            actor_user_id=9,
            require_result=True,
        )


def test_recovery_uses_two_frozen_superseded_ids_without_querying_events() -> None:
    frozen = _frozen_result_row()
    frozen["superseded_version_id_2"] = 13
    connection = _RecoveryConnection(
        result_row=frozen,
        historical_successor_ids=(99,),
    )

    result = _repository()._operation_result(
        cast(Connection, connection),
        operation_token=TOKEN,
        operation_kind="materialize_baseline",
        operation_digest=DIGEST,
        actor_user_id=9,
        require_result=True,
    )

    assert result is not None
    assert result.superseded_version_ids == (11, 13)
    assert connection.disposition_queries == []


def test_record_result_persists_every_returned_snapshot_field() -> None:
    connection = _RecordingConnection()
    version = _Version(
        dataset_id=5,
        version_id=17,
        report_type="business_report",
        version_no=4,
        status="draft",
        data_revision=2,
        review_revision=3,
        ruleset_version="rules-v1",
        created_by=9,
    )

    result = _repository()._record_result(
        cast(Connection, connection),
        operation_token=TOKEN,
        operation_kind="materialize_baseline",
        operation_digest=DIGEST,
        actor_user_id=9,
        result_kind="merged",
        version=version,
        occurred_at=NOW,
        superseded_version_ids=(11, 13),
        source_dataset_id=5,
        source_version_id=11,
    )

    assert result.version_no == 4
    sql, parameters = connection.executions[-1]
    for column_name in (
        "result_version_no",
        "result_status",
        "result_data_revision",
        "result_review_revision",
        "superseded_version_id_1",
        "superseded_version_id_2",
    ):
        assert column_name in sql
    assert parameters["result_version_no"] == result.version_no
    assert parameters["result_status"] == result.status
    assert parameters["result_data_revision"] == result.data_revision
    assert parameters["result_review_revision"] == result.review_revision
    assert parameters["superseded_version_id_1"] == 11
    assert parameters["superseded_version_id_2"] == 13


def test_disposition_event_is_bound_to_the_claimed_operation_token() -> None:
    connection = _RecordingConnection()
    version = _Version(
        dataset_id=5,
        version_id=11,
        report_type="business_report",
        version_no=3,
        status="draft",
        data_revision=2,
        review_revision=1,
        ruleset_version="rules-v1",
        created_by=9,
    )

    _repository()._discard_version(
        cast(Connection, connection),
        version=version,
        operation_token=TOKEN,
        operation_kind="materialize_baseline",
        operation_digest=DIGEST,
        actor_user_id=9,
        event_type="superseded",
        reason="Create a successor",
        occurred_at=NOW,
        successor_dataset_id=5,
        successor_version_id=17,
    )

    sql, parameters = connection.executions[-1]
    assert "operation_token" in sql
    assert parameters["operation_token"] == TOKEN.bytes
    assert parameters["operation_kind"] == "materialize_baseline"
    assert parameters["operation_digest"] == DIGEST


def test_actor_and_role_snapshot_use_shared_locks() -> None:
    connection = _ActorConnection()

    actor = _repository()._load_actor(cast(Connection, connection), 9)

    assert actor == _Actor(9, frozenset({"data_manager"}))
    assert len(connection.executions) == 2
    assert all("FOR SHARE" in sql for sql in connection.executions)
    assert all("FOR UPDATE" not in sql for sql in connection.executions)


def test_dataset_lock_rows_are_acquired_before_immutable_metadata_is_read() -> None:
    events: list[tuple[str, str, dict[str, object]]] = []

    class DatasetConnection:
        def execute(
            self,
            statement: object,
            parameters: Mapping[str, object] | None = None,
        ) -> _MappingResult:
            sql = str(statement)
            if "UPDATE daily_dataset_locks" in sql:
                events.append(("lock", sql, dict(parameters or {})))
                return _MappingResult(rowcount=2)
            events.append(("read", sql, dict(parameters or {})))
            return _RowsResult(
                (
                    {
                        "id": 5,
                        "site_id": 1,
                        "report_date": date(2026, 8, 7),
                        "report_type": "business_report",
                    },
                    {
                        "id": 7,
                        "site_id": 1,
                        "report_date": date(2026, 8, 8),
                        "report_type": "business_report",
                    },
                )
            )

    locked = _repository()._lock_datasets(
        cast(Connection, DatasetConnection()),
        (7, 5, 7),
    )

    assert tuple(locked) == (5, 7)
    assert [event[0] for event in events] == ["lock", "read"]
    assert "UPDATE daily_dataset_locks" in events[0][1]
    assert "SET lock_revision" in events[0][1]
    assert "ORDER BY dataset_id" in events[0][1]
    assert events[0][2]["dataset_ids"] == (5, 7)
    assert "FROM daily_datasets" in events[1][1]
    assert "FOR UPDATE" not in events[1][1]


def test_missing_dataset_lock_row_is_rejected_before_metadata_read() -> None:
    class MissingLockConnection:
        def execute(
            self,
            statement: object,
            _parameters: Mapping[str, object] | None = None,
        ) -> _MappingResult:
            if "UPDATE daily_dataset_locks" in str(statement):
                return _MappingResult(rowcount=1)
            raise AssertionError(
                "dataset metadata must not be read after a missing lock"
            )

    with pytest.raises(DatasetError, match="lock rows is missing"):
        _repository()._lock_datasets(
            cast(Connection, MissingLockConnection()),
            (5, 7),
        )


def test_new_dataset_creates_its_lock_row_in_the_same_savepoint() -> None:
    events: list[str] = []

    class Savepoint:
        def commit(self) -> None:
            events.append("savepoint_commit")

        def rollback(self) -> None:
            events.append("savepoint_rollback")

    class CreateConnection:
        def begin_nested(self) -> Savepoint:
            events.append("savepoint_begin")
            return Savepoint()

        def scalar(
            self,
            statement: object,
            _parameters: Mapping[str, object] | None = None,
        ) -> int | None:
            sql = str(statement)
            if "report_date =" in sql:
                events.append("dataset_preview")
                return None
            if "WHERE id =" in sql:
                events.append("dataset_id_preview")
                return 12
            raise AssertionError(f"unexpected scalar SQL: {sql}")

        def execute(
            self,
            statement: object,
            _parameters: Mapping[str, object] | None = None,
        ) -> _MappingResult:
            sql = str(statement)
            if "INSERT INTO daily_datasets" in sql:
                events.append("dataset_insert")
                return _InsertResult(12)
            if "INSERT INTO daily_dataset_locks" in sql:
                events.append("lock_insert")
                return _MappingResult()
            if "UPDATE daily_dataset_locks" in sql:
                events.append("lock_acquire")
                return _MappingResult()
            if "SELECT id, site_id" in sql and "WHERE id =" in sql:
                events.append("dataset_read")
                return _MappingResult(
                    {
                        "id": 12,
                        "site_id": 1,
                        "report_date": date(2026, 8, 9),
                        "report_type": "business_report",
                    }
                )
            if "FROM report_source_scopes" in sql:
                events.append("scope_preview")
                return _RowsResult(())
            raise AssertionError(f"unexpected SQL: {sql}")

    dataset, created = _repository()._lock_or_create_dataset(
        cast(Connection, CreateConnection()),
        site_id=1,
        report_date=date(2026, 8, 9),
        report_type="business_report",
        occurred_at=NOW,
    )

    assert created is True
    assert dataset.dataset_id == 12
    assert events == [
        "dataset_preview",
        "savepoint_begin",
        "dataset_insert",
        "lock_insert",
        "savepoint_commit",
        "dataset_id_preview",
        "lock_acquire",
        "dataset_read",
        "scope_preview",
    ]


def test_existing_key_is_re_read_only_after_its_sync_row_is_locked() -> None:
    events: list[str] = []

    class ExistingKeyConnection:
        def scalar(
            self,
            statement: object,
            _parameters: Mapping[str, object] | None = None,
        ) -> int:
            assert "SELECT id" in str(statement)
            events.append("identity_preview")
            return 12

        def execute(
            self,
            statement: object,
            _parameters: Mapping[str, object] | None = None,
        ) -> _MappingResult:
            sql = str(statement)
            if "UPDATE daily_dataset_locks" in sql:
                events.append("lock_acquire")
                return _MappingResult()
            if "SELECT id, site_id" in sql and "WHERE id =" in sql:
                events.append("metadata_read")
                return _MappingResult(
                    {
                        "id": 12,
                        "site_id": 1,
                        "report_date": date(2026, 8, 9),
                        "report_type": "business_report",
                    }
                )
            raise AssertionError(f"unexpected SQL: {sql}")

    dataset = _repository()._dataset_for_key(
        cast(Connection, ExistingKeyConnection()),
        report_date=date(2026, 8, 9),
        report_type="business_report",
        lock=True,
    )

    assert dataset is not None
    assert dataset.dataset_id == 12
    assert events == ["identity_preview", "lock_acquire", "metadata_read"]


def test_duplicate_dataset_recovery_uses_a_select_only_current_read() -> None:
    class CurrentReadConnection:
        def execute(
            self,
            statement: object,
            _parameters: Mapping[str, object] | None = None,
        ) -> _MappingResult:
            sql = str(statement)
            assert "FROM daily_datasets" in sql
            assert "FOR SHARE" in sql
            assert "FOR UPDATE" not in sql
            return _MappingResult(
                {
                    "id": 12,
                    "site_id": 1,
                    "report_date": date(2026, 8, 9),
                    "report_type": "business_report",
                }
            )

    dataset = _repository()._current_dataset_for_key(
        cast(Connection, CurrentReadConnection()),
        report_date=date(2026, 8, 9),
        report_type="business_report",
    )

    assert dataset is not None
    assert dataset.dataset_id == 12


def test_version_rows_lock_only_mutable_row_tables_before_reading_base() -> None:
    statements: list[str] = []

    class VersionRowsConnection:
        def scalars(
            self,
            statement: object,
            _parameters: Mapping[str, object] | None = None,
        ) -> tuple[int, ...]:
            statements.append(str(statement))
            return ()

        def execute(
            self,
            statement: object,
            _parameters: Mapping[str, object] | None = None,
        ) -> _RowsResult:
            statements.append(str(statement))
            return _RowsResult(())

    rows = _repository()._version_rows(
        cast(Connection, VersionRowsConnection()),
        _Version(
            dataset_id=5,
            version_id=17,
            report_type="business_report",
            version_no=3,
            status="draft",
            data_revision=0,
            review_revision=0,
            ruleset_version="rules-v1",
            created_by=9,
        ),
    )

    assert rows == ()
    assert len(statements) == 2
    lock_sql, read_sql = statements
    assert "FROM version_rows AS row_records" in lock_sql
    assert "INNER JOIN business_report_rows AS typed" in lock_sql
    assert "version_base_rows" not in lock_sql
    assert "FOR UPDATE" in lock_sql
    assert "LEFT JOIN version_base_rows AS base" in read_sql
    assert "FOR UPDATE" not in read_sql


@pytest.mark.parametrize("error_code", [1213, 1205], ids=["deadlock", "lock-timeout"])
def test_retryable_mysql_failure_restarts_the_complete_transaction(
    monkeypatch: Any,
    error_code: int,
) -> None:
    (
        repository,
        engine,
        waits,
        claimed_connections,
        actor_connections,
        work_connections,
        recovery_calls,
    ) = _configure_retry_scenario(
        monkeypatch,
        failures=(_mysql_error(error_code),),
    )

    result = _execute_retry_scenario(repository)

    assert result == _draft_result()
    assert engine.events == [
        ("begin", 1),
        ("rollback", 1),
        ("begin", 2),
        ("commit", 2),
    ]
    assert claimed_connections == [1, 2]
    assert actor_connections == [1, 2]
    assert work_connections == [1, 2]
    assert recovery_calls == [TOKEN, TOKEN]
    assert waits == [1]


def test_retryable_failure_recovers_a_terminal_result_before_replay(
    monkeypatch: Any,
) -> None:
    frozen = _draft_result()
    (
        repository,
        engine,
        waits,
        claimed_connections,
        actor_connections,
        work_connections,
        recovery_calls,
    ) = _configure_retry_scenario(
        monkeypatch,
        failures=(_mysql_error(1213),),
        recovery_results=(None, frozen),
    )

    result = _execute_retry_scenario(repository)

    assert result is frozen
    assert engine.events == [("begin", 1), ("rollback", 1)]
    assert claimed_connections == [1]
    assert actor_connections == [1]
    assert work_connections == [1]
    assert recovery_calls == [TOKEN, TOKEN]
    assert waits == []


def test_retryable_failures_exhaust_into_a_dataset_busy_error(
    monkeypatch: Any,
) -> None:
    failures = tuple(_mysql_error(1213) for _index in range(4))
    (
        repository,
        engine,
        waits,
        claimed_connections,
        actor_connections,
        work_connections,
        recovery_calls,
    ) = _configure_retry_scenario(monkeypatch, failures=failures)

    with pytest.raises(DatasetTransactionBusy, match="3 retries"):
        _execute_retry_scenario(repository)

    assert engine.events == [
        ("begin", 1),
        ("rollback", 1),
        ("begin", 2),
        ("rollback", 2),
        ("begin", 3),
        ("rollback", 3),
        ("begin", 4),
        ("rollback", 4),
    ]
    assert claimed_connections == [1, 2, 3, 4]
    assert actor_connections == [1, 2, 3, 4]
    assert work_connections == [1, 2, 3, 4]
    assert recovery_calls == [TOKEN, TOKEN, TOKEN, TOKEN]
    assert waits == [1, 2, 3]


def test_non_retryable_database_failure_is_wrapped_without_replay(
    monkeypatch: Any,
) -> None:
    failure = _mysql_error(1048)
    (
        repository,
        engine,
        waits,
        claimed_connections,
        actor_connections,
        work_connections,
        recovery_calls,
    ) = _configure_retry_scenario(monkeypatch, failures=(failure,))

    with pytest.raises(DatasetError, match="draft transaction failed") as raised:
        _execute_retry_scenario(repository)

    assert raised.value.__cause__ is failure
    assert engine.events == [("begin", 1), ("rollback", 1)]
    assert claimed_connections == [1]
    assert actor_connections == [1]
    assert work_connections == [1]
    assert recovery_calls == [TOKEN]
    assert waits == []


def test_invalidated_connection_is_recovered_once_without_replay(
    monkeypatch: Any,
) -> None:
    failure = _mysql_error(1213, connection_invalidated=True)
    (
        repository,
        engine,
        waits,
        claimed_connections,
        actor_connections,
        work_connections,
        recovery_calls,
    ) = _configure_retry_scenario(monkeypatch, failures=(failure,))

    with pytest.raises(DatasetCommitOutcomeUnknown, match="acknowledgement"):
        _execute_retry_scenario(repository)

    assert engine.events == [("begin", 1), ("rollback", 1)]
    assert claimed_connections == [1]
    assert actor_connections == [1]
    assert work_connections == [1]
    assert recovery_calls == [TOKEN, TOKEN]
    assert waits == []


def test_invalidated_connection_recovery_failure_stays_in_unknown_outcome_domain(
    monkeypatch: Any,
) -> None:
    failure = _mysql_error(1213, connection_invalidated=True)
    recovery_failure = _mysql_error(2006, connection_invalidated=True)
    (
        repository,
        engine,
        waits,
        claimed_connections,
        actor_connections,
        work_connections,
        recovery_calls,
    ) = _configure_retry_scenario(
        monkeypatch,
        failures=(failure,),
        recovery_results=(None, recovery_failure),
    )

    with pytest.raises(DatasetCommitOutcomeUnknown, match="recovery failed") as raised:
        _execute_retry_scenario(repository)

    assert raised.value.__cause__ is recovery_failure
    assert engine.events == [("begin", 1), ("rollback", 1)]
    assert claimed_connections == [1]
    assert actor_connections == [1]
    assert work_connections == [1]
    assert recovery_calls == [TOKEN, TOKEN]
    assert waits == []


def test_materialize_locks_inherited_batches_before_parent_rows(
    monkeypatch: Any,
) -> None:
    repository = _repository()
    actor = _Actor(9, frozenset({"data_manager"}))
    baseline = _Baseline(
        batch_id=31,
        baseline_id=41,
        site_id=1,
        report_date=date(2026, 8, 7),
        report_type="business_report",
        ruleset_version="rules-v1",
        rows=(),
    )
    dataset = _Dataset(
        dataset_id=5,
        site_id=1,
        report_date=baseline.report_date,
        report_type=baseline.report_type,
    )
    active = _Version(
        dataset_id=5,
        version_id=17,
        report_type="business_report",
        version_no=4,
        status="draft",
        data_revision=2,
        review_revision=3,
        ruleset_version="rules-v1",
        created_by=9,
    )
    command = MaterializeBaselineCommand(
        batch_id=baseline.batch_id,
        parse_baseline_id=baseline.baseline_id,
        report_date=baseline.report_date,
        strategy="merge",
        expected_active_draft=active.expectation,
        expected_publication_version_id=None,
        merge_decisions=(),
        actor_user_id=actor.user_id,
        operation_token=TOKEN,
        reason="Merge a new baseline",
    )
    calls: list[tuple[str, object]] = []

    def lock_baseline(*_args: object, **_keywords: object) -> _Baseline:
        calls.append(("direct_batch_and_baseline", baseline.batch_id))
        return baseline

    def lock_dataset(*_args: object, **_keywords: object) -> tuple[_Dataset, bool]:
        calls.append(("dataset", dataset.dataset_id))
        return dataset, False

    def active_version(*_args: object, **_keywords: object) -> _Version:
        calls.append(("version", active.version_id))
        return active

    def lock_batches(
        _connection: Connection,
        version_ids: object,
    ) -> None:
        calls.append(("inherited_batches", tuple(cast(Any, version_ids))))

    def guard_pending_move(
        _connection: Connection,
        *,
        version_id: int,
    ) -> None:
        calls.append(("pending_move_ancestry", version_id))

    def stop_at_rows(*_args: object, **_keywords: object) -> tuple[()]:
        calls.append(("rows", active.version_id))
        raise _StopAfterRowLock

    monkeypatch.setattr(repository, "_lock_current_baseline", lock_baseline)
    monkeypatch.setattr(repository, "_lock_or_create_dataset", lock_dataset)
    monkeypatch.setattr(repository, "_active_version", active_version)
    monkeypatch.setattr(repository, "_publication_version_id", lambda *_args: None)
    monkeypatch.setattr(
        repository,
        "_assert_no_unfinalized_published_move_ancestry",
        guard_pending_move,
    )
    monkeypatch.setattr(repository, "_lock_input_batches_for_versions", lock_batches)
    monkeypatch.setattr(repository, "_version_rows", stop_at_rows)

    with pytest.raises(_StopAfterRowLock):
        repository._materialize_baseline(
            cast(Connection, object()),
            actor=actor,
            command=command,
            occurred_at=NOW,
            force=False,
        )

    assert calls == [
        ("direct_batch_and_baseline", 31),
        ("dataset", 5),
        ("version", 17),
        ("pending_move_ancestry", 17),
        ("inherited_batches", (17,)),
        ("rows", 17),
    ]


def test_reassign_locks_datasets_and_actual_versions_before_input_batches(
    monkeypatch: Any,
) -> None:
    repository = _repository()
    actor = _Actor(9, frozenset({"data_manager"}))
    source_dataset = _Dataset(
        dataset_id=5,
        site_id=1,
        report_date=date(2026, 8, 7),
        report_type="business_report",
    )
    target_dataset = _Dataset(
        dataset_id=7,
        site_id=1,
        report_date=date(2026, 8, 8),
        report_type="business_report",
    )
    source_version = _Version(
        dataset_id=5,
        version_id=17,
        report_type="business_report",
        version_no=4,
        status="draft",
        data_revision=2,
        review_revision=3,
        ruleset_version="rules-v1",
        created_by=9,
    )
    target_version = _Version(
        dataset_id=7,
        version_id=19,
        report_type="business_report",
        version_no=2,
        status="draft",
        data_revision=1,
        review_revision=1,
        ruleset_version="rules-v1",
        created_by=9,
    )
    command = ReassignUnpublishedDraftDateCommand(
        source_dataset_id=source_dataset.dataset_id,
        source_draft=source_version.expectation,
        target_report_date=target_dataset.report_date,
        target=ActiveDraftReassignmentTarget(
            expected_dataset_id=target_dataset.dataset_id,
            expected_active_draft=target_version.expectation,
            expected_publication_version_id=None,
            action="merge",
        ),
        merge_decisions=(),
        actor_user_id=actor.user_id,
        operation_token=TOKEN,
        reason="Move the unpublished draft",
    )
    calls: list[tuple[str, object]] = []

    def dataset_by_id(*_args: object, **_keywords: object) -> _Dataset:
        calls.append(("source_preview", source_dataset.dataset_id))
        return source_dataset

    def dataset_for_key(*_args: object, **_keywords: object) -> _Dataset:
        calls.append(("target_preview", target_dataset.dataset_id))
        return target_dataset

    def lock_datasets(
        _connection: Connection,
        dataset_ids: object,
    ) -> dict[int, _Dataset]:
        identities = tuple(cast(Any, dataset_ids))
        calls.append(("datasets", identities))
        return {
            source_dataset.dataset_id: source_dataset,
            target_dataset.dataset_id: target_dataset,
        }

    def active_version(
        _connection: Connection,
        dataset_id: int,
    ) -> _Version:
        version = (
            source_version
            if dataset_id == source_dataset.dataset_id
            else target_version
        )
        calls.append(("version", version.version_id))
        return version

    def lock_batches(
        _connection: Connection,
        version_ids: object,
    ) -> None:
        calls.append(("inherited_batches", tuple(cast(Any, version_ids))))

    def stop_at_rows(
        _connection: Connection,
        version: _Version,
    ) -> tuple[()]:
        calls.append(("rows", version.version_id))
        raise _StopAfterRowLock

    monkeypatch.setattr(repository, "_dataset_by_id", dataset_by_id)
    monkeypatch.setattr(repository, "_dataset_for_key", dataset_for_key)
    monkeypatch.setattr(repository, "_lock_datasets", lock_datasets)
    monkeypatch.setattr(repository, "_active_version", active_version)
    monkeypatch.setattr(repository, "_has_published_ancestry", lambda *_args: False)
    monkeypatch.setattr(repository, "_publication_version_id", lambda *_args: None)
    monkeypatch.setattr(repository, "_lock_input_batches_for_versions", lock_batches)
    monkeypatch.setattr(repository, "_version_rows", stop_at_rows)

    with pytest.raises(_StopAfterRowLock):
        repository._reassign_date(
            cast(Connection, object()),
            actor=actor,
            command=command,
            occurred_at=NOW,
        )

    assert calls == [
        ("source_preview", 5),
        ("target_preview", 7),
        ("datasets", (5, 7)),
        ("version", 17),
        ("version", 19),
        ("inherited_batches", (17, 19)),
        ("rows", 19),
    ]
