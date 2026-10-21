from __future__ import annotations

from collections import deque
from collections.abc import Mapping
from datetime import UTC, date, datetime
from typing import Any, Literal, cast
from uuid import UUID

import pytest
from app.validation.repository import MySqlValidationRepository
from app.validation.types import (
    RunValidationCommand,
    ValidationCommitOutcomeUnknown,
    ValidationOperationConflict,
    ValidationRunReceipt,
    ValidationSummary,
    ValidationSummaryStage,
    ValidationTransactionBusy,
)
from sqlalchemy.engine import Connection, Engine
from sqlalchemy.exc import DBAPIError

NOW = datetime(2026, 8, 8, 9, 30, tzinfo=UTC)
DB_NOW = NOW.replace(tzinfo=None)
TOKEN = UUID("aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa")


def _command() -> RunValidationCommand:
    return RunValidationCommand(
        dataset_id=5,
        version_id=23,
        data_revision=4,
        ruleset_version="return_report_v1",
        actor_user_id=9,
        operation_token=TOKEN,
    )


def _summary() -> ValidationSummary:
    stage = ValidationSummaryStage(
        data_digest="11" * 32,
        row_count=1,
        totals=(("quantity", "2"),),
        warning_count=0,
        blocking_count=0,
    )
    return ValidationSummary(
        report_date=date(2026, 8, 8),
        report_type="return_report",
        row_count=1,
        totals=(("quantity", "2"),),
        parse_fidelity=stage,
        draft_explainability=stage,
    )


def _receipt() -> ValidationRunReceipt:
    return ValidationRunReceipt(
        operation_token=TOKEN,
        validation_run_id=31,
        dataset_id=5,
        version_id=23,
        version_status="draft",
        data_revision=4,
        review_revision=7,
        ruleset_version="return_report_v1",
        status="succeeded",
        result="passed",
        data_digest=bytes.fromhex("22" * 32),
        summary=_summary(),
        completed_at=NOW,
    )


class _Result:
    def __init__(
        self,
        row: Mapping[str, object] | None = None,
        *,
        rows: tuple[Mapping[str, object], ...] = (),
        rowcount: int = 1,
        lastrowid: int | None = None,
    ) -> None:
        self._row = row
        self._rows = rows
        self.rowcount = rowcount
        self.lastrowid = lastrowid

    def mappings(self) -> _Result:
        return self

    def first(self) -> Mapping[str, object] | None:
        return self._row

    def all(self) -> tuple[Mapping[str, object], ...]:
        return self._rows


class _RecoveryConnection:
    def __init__(self, *, stored_digest: bytes) -> None:
        self.stored_digest = stored_digest
        self.executions: list[str] = []

    def execute(
        self,
        statement: object,
        _parameters: Mapping[str, object] | None = None,
    ) -> _Result:
        sql = " ".join(str(statement).split())
        self.executions.append(sql)
        if "FROM review_operation_tokens" in sql:
            return _Result(
                {
                    "operation_kind": "run_validation",
                    "operation_digest": self.stored_digest,
                    "actor_user_id": 9,
                }
            )
        if "FROM review_operation_results" in sql:
            return _Result(
                {
                    "result_kind": "applied",
                    "result_dataset_id": 5,
                    "result_version_id": 23,
                    "result_status": "draft",
                    "result_data_revision": 4,
                    "result_review_revision": 7,
                    "validation_run_id": 31,
                    "run_type": "full",
                    "ruleset_version": "return_report_v1",
                    "validation_status": "succeeded",
                    "validation_result": "passed",
                    "data_digest": bytes.fromhex("22" * 32),
                    "summary_json": _summary().as_payload(),
                    "completed_at": DB_NOW,
                }
            )
        raise AssertionError(f"unexpected SQL: {sql}")


def _repository(engine: Engine | None = None) -> MySqlValidationRepository:
    return MySqlValidationRepository(engine or cast(Engine, object()))


def test_recovery_uses_only_the_global_claim_and_frozen_terminal_result() -> None:
    repository = _repository()
    command = _command()
    connection = _RecoveryConnection(stored_digest=command.operation_digest)

    result = repository._operation_result(
        cast(Connection, connection),
        command=command,
        require_result=True,
    )

    assert result == _receipt()
    assert all("dataset_versions" not in sql for sql in connection.executions)
    assert all("version_rows" not in sql for sql in connection.executions)


def test_recovery_rejects_global_token_reuse_with_another_digest() -> None:
    repository = _repository()
    connection = _RecoveryConnection(stored_digest=bytes.fromhex("44" * 32))

    with pytest.raises(ValidationOperationConflict, match="another command"):
        repository._operation_result(
            cast(Connection, connection),
            command=_command(),
            require_result=True,
        )


class _RetryConnection:
    def __init__(self, identity: int) -> None:
        self.identity = identity


class _BeginContext:
    def __init__(self, engine: _RetryEngine, connection: _RetryConnection) -> None:
        self.engine = engine
        self.connection = connection

    def __enter__(self) -> _RetryConnection:
        self.engine.events.append(("begin", self.connection.identity))
        return self.connection

    def __exit__(
        self,
        exception_type: type[BaseException] | None,
        _exception: BaseException | None,
        _traceback: object,
    ) -> Literal[False]:
        self.engine.events.append(
            (
                "rollback" if exception_type is not None else "commit",
                self.connection.identity,
            )
        )
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


def _mysql_error(code: int, *, invalidated: bool = False) -> DBAPIError:
    return DBAPIError(
        statement="injected validation transaction",
        params=None,
        orig=_MySqlDriverError(code, "injected MySQL failure"),
        connection_invalidated=invalidated,
    )


def _configure_retry(
    monkeypatch: Any,
    failures: tuple[DBAPIError, ...],
) -> tuple[MySqlValidationRepository, _RetryEngine, list[int], list[int]]:
    engine = _RetryEngine()
    waits: list[int] = []
    repository = MySqlValidationRepository(
        cast(Engine, engine),
        retry_waiter=waits.append,
    )
    pending = deque(failures)
    recoveries: list[int] = []

    def recover(command: RunValidationCommand) -> None:
        recoveries.append(command.version_id)
        return None

    def transaction(
        connection: object, command: RunValidationCommand, at: datetime
    ) -> ValidationRunReceipt:
        assert isinstance(connection, _RetryConnection)
        assert command == _command()
        assert at == DB_NOW
        if pending:
            raise pending.popleft()
        return _receipt()

    monkeypatch.setattr(repository, "_recover_operation", recover)
    monkeypatch.setattr(repository, "_run_transaction", transaction)
    return repository, engine, waits, recoveries


@pytest.mark.parametrize("error_code", [1205, 1213])
def test_retryable_mysql_failure_uses_a_fresh_complete_transaction(
    monkeypatch: Any,
    error_code: int,
) -> None:
    repository, engine, waits, recoveries = _configure_retry(
        monkeypatch,
        (_mysql_error(error_code),),
    )

    assert repository.run_validation(_command(), occurred_at=NOW) == _receipt()
    assert engine.events == [
        ("begin", 1),
        ("rollback", 1),
        ("begin", 2),
        ("commit", 2),
    ]
    assert waits == [1]
    assert len(recoveries) == 2


def test_retryable_mysql_failures_stop_after_four_total_attempts(
    monkeypatch: Any,
) -> None:
    repository, engine, waits, _recoveries = _configure_retry(
        monkeypatch,
        tuple(_mysql_error(1213) for _index in range(4)),
    )

    with pytest.raises(ValidationTransactionBusy, match="4 attempts"):
        repository.run_validation(_command(), occurred_at=NOW)

    assert len(engine.connections) == 4
    assert waits == [1, 2, 3]


def test_invalidated_connection_only_recovers_and_never_blindly_replays(
    monkeypatch: Any,
) -> None:
    repository, engine, waits, recoveries = _configure_retry(
        monkeypatch,
        (_mysql_error(1213, invalidated=True),),
    )

    with pytest.raises(ValidationCommitOutcomeUnknown, match="acknowledgement"):
        repository.run_validation(_command(), occurred_at=NOW)

    assert len(engine.connections) == 1
    assert waits == []
    assert len(recoveries) == 2
