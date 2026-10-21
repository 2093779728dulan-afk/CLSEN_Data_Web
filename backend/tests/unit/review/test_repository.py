from __future__ import annotations

from collections.abc import Mapping
from datetime import UTC, date, datetime
from typing import cast

import pytest
from app.review.repository import MySqlReviewRepository
from app.review.types import (
    DraftHeadExpectation,
    DraftPointerConflict,
    ReviewPermissionDenied,
    ReviewRevisionConflict,
)
from sqlalchemy.engine import Connection

POINTED_AT = datetime(2026, 8, 8, 8, 0, tzinfo=UTC)
OCCURRED_AT = datetime(2026, 8, 8, 8, 30, tzinfo=UTC)


class _Result:
    def __init__(self, rowcount: int = 1) -> None:
        self.rowcount = rowcount


class _MappingResult(_Result):
    def __init__(self, row: Mapping[str, object] | None) -> None:
        super().__init__()
        self.row = row

    def mappings(self) -> _MappingResult:
        return self

    def first(self) -> Mapping[str, object] | None:
        return self.row


class _RecordingConnection:
    def __init__(self, rowcounts: tuple[int, ...] = ()) -> None:
        self.rowcounts = list(rowcounts)
        self.executions: list[tuple[str, dict[str, object]]] = []

    def execute(
        self,
        statement: object,
        parameters: Mapping[str, object] | None = None,
    ) -> _Result:
        self.executions.append((str(statement), dict(parameters or {})))
        rowcount = self.rowcounts.pop(0) if self.rowcounts else 1
        return _Result(rowcount)


class _HeadConnection:
    def __init__(self, *, pointed_at: datetime | None = None) -> None:
        self.executions: list[str] = []
        self.pointed_at = pointed_at or POINTED_AT.replace(tzinfo=None)

    def execute(
        self,
        statement: object,
        _parameters: Mapping[str, object] | None = None,
    ) -> _Result:
        sql = str(statement)
        self.executions.append(sql)
        if "UPDATE daily_dataset_locks" in sql:
            return _Result()
        if "FROM daily_datasets" in sql:
            return _MappingResult(
                {
                    "id": 10,
                    "site_id": 1,
                    "report_date": date(2026, 8, 8),
                    "report_type": "business_report",
                }
            )
        if "FROM dataset_drafts" in sql:
            return _MappingResult(
                {
                    "dataset_id": 10,
                    "version_id": 20,
                    "version_status": "draft",
                    "pointed_at": self.pointed_at,
                }
            )
        if "FROM dataset_versions" in sql:
            return _MappingResult(
                {
                    "dataset_id": 10,
                    "id": 20,
                    "report_type": "business_report",
                    "status": "draft",
                    "data_revision": 3,
                    "review_revision": 4,
                    "ruleset_version": "business_report_v1",
                    "sealed_at": None,
                }
            )
        raise AssertionError(f"unexpected SQL: {sql}")


class _ActorConnection:
    def __init__(self, roles: tuple[str, ...]) -> None:
        self.roles = roles
        self.executions: list[str] = []

    def execute(
        self,
        statement: object,
        _parameters: Mapping[str, object] | None = None,
    ) -> _MappingResult:
        sql = str(statement)
        self.executions.append(sql)
        return _MappingResult({"id": 5, "status": "active"})

    def scalars(
        self,
        statement: object,
        _parameters: Mapping[str, object] | None = None,
    ) -> tuple[str, ...]:
        self.executions.append(str(statement))
        return self.roles


def _head(status: str) -> DraftHeadExpectation:
    return DraftHeadExpectation(
        dataset_id=10,
        version_id=20,
        status=cast(object, status),  # type: ignore[arg-type]
        data_revision=3,
        review_revision=4,
        pointed_at=POINTED_AT,
    )


def test_data_edit_on_draft_conditionally_advances_only_data_revision() -> None:
    connection = _RecordingConnection()

    result = MySqlReviewRepository._advance_data_revision(
        cast(Connection, connection),
        head=_head("draft"),
        occurred_at=OCCURRED_AT,
    )

    assert result.status == "draft"
    assert result.data_revision == 4
    assert result.review_revision == 4
    assert len(connection.executions) == 1
    sql, parameters = connection.executions[0]
    assert "UPDATE dataset_versions" in sql
    assert "data_revision = :new_data_revision" in sql
    assert "review_revision = :review_revision" in sql
    assert parameters["new_data_revision"] == 4


def test_data_edit_on_ready_uses_delete_update_reinsert_pointer_dance() -> None:
    connection = _RecordingConnection()

    result = MySqlReviewRepository._advance_data_revision(
        cast(Connection, connection),
        head=_head("ready_for_publish"),
        occurred_at=OCCURRED_AT,
    )

    assert result.status == "draft"
    assert result.data_revision == 4
    assert [
        next(
            marker
            for marker in (
                "DELETE FROM dataset_drafts",
                "UPDATE dataset_versions",
                "INSERT INTO dataset_drafts",
            )
            if marker in sql
        )
        for sql, _parameters in connection.executions
    ] == [
        "DELETE FROM dataset_drafts",
        "UPDATE dataset_versions",
        "INSERT INTO dataset_drafts",
    ]
    assert connection.executions[-1][1]["pointed_at"] == POINTED_AT.replace(tzinfo=None)


@pytest.mark.parametrize("failed_step", [0, 1, 2])
def test_ready_pointer_dance_rejects_any_conditional_rowcount_failure(
    failed_step: int,
) -> None:
    rowcounts = [1, 1, 1]
    rowcounts[failed_step] = 0
    connection = _RecordingConnection(tuple(rowcounts))

    with pytest.raises(ReviewRevisionConflict):
        MySqlReviewRepository._advance_data_revision(
            cast(Connection, connection),
            head=_head("ready_for_publish"),
            occurred_at=OCCURRED_AT,
        )


def test_review_only_change_advances_review_revision_without_pointer_rewrite() -> None:
    connection = _RecordingConnection()

    result = MySqlReviewRepository._advance_review_revision(
        cast(Connection, connection),
        head=_head("draft"),
        new_status="draft",
    )

    assert result.data_revision == 3
    assert result.review_revision == 5
    assert len(connection.executions) == 1
    assert "UPDATE dataset_versions" in connection.executions[0][0]


def test_mark_ready_review_transition_preserves_pointer_timestamp() -> None:
    connection = _RecordingConnection()

    result = MySqlReviewRepository._advance_review_revision(
        cast(Connection, connection),
        head=_head("draft"),
        new_status="ready_for_publish",
    )

    assert result.status == "ready_for_publish"
    assert result.data_revision == 3
    assert result.review_revision == 5
    assert connection.executions[-1][1]["pointed_at"] == POINTED_AT.replace(tzinfo=None)
    assert "'ready_for_publish'" not in connection.executions[-1][0]
    assert connection.executions[-1][1]["new_status"] == "ready_for_publish"


def test_lock_active_head_uses_dataset_then_pointer_then_version_order() -> None:
    connection = _HeadConnection()

    locked = MySqlReviewRepository._lock_active_head(
        cast(Connection, connection),
        _head("draft"),
    )

    assert locked.report_type == "business_report"
    assert locked.ruleset_version == "business_report_v1"
    assert [
        next(
            marker
            for marker in (
                "UPDATE daily_dataset_locks",
                "FROM daily_datasets",
                "FROM dataset_drafts",
                "FROM dataset_versions",
            )
            if marker in sql
        )
        for sql in connection.executions
    ] == [
        "UPDATE daily_dataset_locks",
        "FROM daily_datasets",
        "FROM dataset_drafts",
        "FROM dataset_versions",
    ]
    assert "FOR UPDATE" in connection.executions[2]
    assert "FOR UPDATE" in connection.executions[3]


def test_lock_active_head_rejects_pointer_timestamp_aba() -> None:
    connection = _HeadConnection(
        pointed_at=datetime(2026, 8, 8, 8, 1),
    )

    with pytest.raises(DraftPointerConflict):
        MySqlReviewRepository._lock_active_head(
            cast(Connection, connection),
            _head("draft"),
        )


def test_load_actor_freezes_user_and_role_rows_with_shared_locks() -> None:
    connection = _ActorConnection(("data_manager",))

    actor = MySqlReviewRepository._load_actor(
        cast(Connection, connection),
        actor_user_id=5,
    )

    assert actor.user_id == 5
    assert actor.roles == frozenset({"data_manager"})
    assert all("FOR SHARE" in sql for sql in connection.executions)
    assert "ORDER BY roles.code" in connection.executions[1]


def test_load_actor_rejects_viewer() -> None:
    connection = _ActorConnection(("viewer",))

    with pytest.raises(ReviewPermissionDenied):
        MySqlReviewRepository._load_actor(
            cast(Connection, connection),
            actor_user_id=5,
        )
