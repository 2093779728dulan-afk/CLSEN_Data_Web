from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from datetime import date, timedelta
from threading import Barrier
from typing import cast
from uuid import UUID, uuid4

import pytest
import sqlalchemy as sa
from app.publications.commands import (
    CreatePublishedMoveRevisionCommand,
    EmptyMoveTarget,
    PublicationPointerExpectation,
    PublishCommand,
)
from app.publications.repository import (
    MySqlPublicationRepository,
    PublicationPointerConflict,
)
from app.publications.results import DraftCommandResult, PublicationCommandResult
from app.publications.service import PublicationService
from sqlalchemy.engine import Engine

from tests.integration.dataset_test_support import NOW
from tests.integration.dataset_test_support import (
    dataset_case as _dataset_case,  # noqa: F401 - registers the shared fixture
)
from tests.integration.publication_test_support import (
    PublicationIntegrationCase,
    ReadyPublicationDraft,
)
from tests.integration.publication_test_support import (
    publication_case as _publication_case,  # noqa: F401 - registers fixture
)

pytestmark = pytest.mark.mysql


def _isolated_date() -> date:
    return date(2400, 1, 1) + timedelta(days=uuid4().int % 20000)


def _publish_command(
    ready: ReadyPublicationDraft,
    *,
    actor_user_id: int,
    operation_token: UUID,
) -> PublishCommand:
    return PublishCommand(
        dataset_id=ready.dataset_id,
        expected_draft=ready.expectation,
        expected_publication=PublicationPointerExpectation(None, None),
        validation=ready.validation,
        confirmation=ready.confirmation,
        actor_user_id=actor_user_id,
        operation_token=operation_token,
        reason="Race two callers against the same reviewed draft",
    )


def _connection_id(engine: Engine) -> int:
    with engine.connect() as connection:
        value = connection.scalar(sa.text("SELECT CONNECTION_ID()"))
    assert value is not None
    return int(value)


def _run_at_barrier(
    *,
    engines: tuple[Engine, Engine],
    commands: tuple[object, object],
    operation: str,
) -> tuple[object, object, tuple[int, int]]:
    barrier = Barrier(2)
    connection_ids = (_connection_id(engines[0]), _connection_id(engines[1]))

    def execute(index: int) -> object:
        barrier.wait(timeout=15)
        service = PublicationService(
            repository=MySqlPublicationRepository(
                engines[index],
                retry_waiter=lambda _attempt: None,
            ),
            clock=lambda: NOW,
        )
        try:
            if operation == "publish":
                return service.publish(cast(PublishCommand, commands[index]))
            return service.create_published_move_revision(
                cast(CreatePublishedMoveRevisionCommand, commands[index])
            )
        except Exception as error:  # result shape is asserted by each caller.
            return error

    with ThreadPoolExecutor(max_workers=2) as executor:
        futures = tuple(executor.submit(execute, index) for index in range(2))
        results = tuple(future.result(timeout=30) for future in futures)
    return results[0], results[1], connection_ids


def test_two_independent_mysql_connections_publish_one_reviewed_draft_once(
    publication_case: PublicationIntegrationCase,
) -> None:
    case = publication_case
    report_date = _isolated_date()
    _baseline, draft = case.materialize_baseline(
        report_date=report_date,
        variant="publish-concurrency",
    )
    ready = case.mark_ready(dataset_id=draft.dataset_id, version_id=draft.version_id)
    commands = (
        _publish_command(
            ready,
            actor_user_id=case.owner_user_id,
            operation_token=uuid4(),
        ),
        _publish_command(
            ready,
            actor_user_id=case.owner_user_id,
            operation_token=uuid4(),
        ),
    )
    engines = (case.dataset_case.runtime_engine(), case.dataset_case.runtime_engine())
    try:
        first, second, connection_ids = _run_at_barrier(
            engines=engines,
            commands=commands,
            operation="publish",
        )
    finally:
        for engine in engines:
            engine.dispose()

    assert connection_ids[0] != connection_ids[1]
    outcomes = (first, second)
    successes = [
        outcome for outcome in outcomes if isinstance(outcome, PublicationCommandResult)
    ]
    conflicts = [
        outcome
        for outcome in outcomes
        if isinstance(outcome, PublicationPointerConflict)
    ]
    assert len(successes) == 1
    assert len(conflicts) == 1
    assert case.publication_pointer(draft.dataset_id).version_id == draft.version_id
    assert (
        case.dataset_case.scalar(
            "SELECT COUNT(*) FROM publication_commands "
            "WHERE operation_token IN (:first, :second)",
            {
                "first": commands[0].operation_token.bytes,
                "second": commands[1].operation_token.bytes,
            },
        )
        == 1
    )
    assert (
        case.dataset_case.scalar(
            "SELECT COUNT(*) FROM publication_events WHERE dataset_id = :dataset_id",
            {"dataset_id": draft.dataset_id},
        )
        == 1
    )


def test_two_independent_mysql_connections_create_one_cross_date_move_draft(
    publication_case: PublicationIntegrationCase,
) -> None:
    case = publication_case
    source_date = _isolated_date()
    target_date = source_date + timedelta(days=1)
    _baseline, source = case.create_published_dataset(
        report_date=source_date,
        variant="move-concurrency-source",
    )

    def move_command() -> CreatePublishedMoveRevisionCommand:
        return CreatePublishedMoveRevisionCommand(
            source_dataset_id=source.dataset_id,
            expected_source_publication=source.publication,
            target_report_date=target_date,
            target=EmptyMoveTarget(),
            merge_decisions=(),
            actor_user_id=case.admin_user_id,
            operation_token=uuid4(),
            reason="Race two administrators creating the same move review draft",
        )

    commands = (
        move_command(),
        move_command(),
    )
    engines = (case.dataset_case.runtime_engine(), case.dataset_case.runtime_engine())
    try:
        first, second, connection_ids = _run_at_barrier(
            engines=engines,
            commands=commands,
            operation="create_move",
        )
    finally:
        for engine in engines:
            engine.dispose()

    assert connection_ids[0] != connection_ids[1]
    outcomes = (first, second)
    successes = [
        outcome for outcome in outcomes if isinstance(outcome, DraftCommandResult)
    ]
    conflicts = [
        outcome
        for outcome in outcomes
        if isinstance(outcome, PublicationPointerConflict)
    ]
    assert len(successes) == 1
    assert len(conflicts) == 1
    created = successes[0]
    assert case.publication_pointer(source.dataset_id) == source.publication
    assert case.publication_pointer(
        created.dataset_id
    ) == PublicationPointerExpectation(None, None)
    assert (
        case.dataset_case.scalar(
            "SELECT COUNT(*) FROM dataset_drafts WHERE dataset_id = :dataset_id",
            {"dataset_id": created.dataset_id},
        )
        == 1
    )
