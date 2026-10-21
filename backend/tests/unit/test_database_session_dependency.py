"""Request transaction lifecycle regression tests."""

from __future__ import annotations

from collections.abc import Generator
from contextlib import AbstractContextManager, suppress
from typing import Annotated, Self, cast

from app.api.dependencies import get_database_session, get_session_factory
from app.db.session import SessionFactory
from fastapi import Depends, FastAPI
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session


class _FailingCommitSession(AbstractContextManager["_FailingCommitSession"]):
    def __init__(self) -> None:
        self.commit_calls = 0
        self.rollback_calls = 0

    def __enter__(self) -> Self:
        return self

    def __exit__(self, *args: object) -> None:
        return None

    def commit(self) -> None:
        self.commit_calls += 1
        raise RuntimeError("commit failed")

    def rollback(self) -> None:
        self.rollback_calls += 1


def test_commit_failure_happens_before_success_response_is_sent() -> None:
    application = FastAPI()
    database_session = _FailingCommitSession()

    def session_factory() -> AbstractContextManager[_FailingCommitSession]:
        return database_session

    application.dependency_overrides[get_session_factory] = lambda: cast(
        SessionFactory,
        session_factory,
    )

    @application.post("/write")
    def write(
        _session: Annotated[
            Session,
            Depends(get_database_session, scope="function"),
        ],
    ) -> dict[str, bool]:
        return {"ok": True}

    with TestClient(application, raise_server_exceptions=False) as client:
        response = client.post("/write")

    assert response.status_code == 500
    assert database_session.commit_calls == 1
    assert database_session.rollback_calls == 1


def test_database_session_commits_once_before_dependency_finishes() -> None:
    events: list[str] = []

    class _Session(AbstractContextManager["_Session"]):
        def __enter__(self) -> Self:
            events.append("enter")
            return self

        def __exit__(self, *args: object) -> None:
            events.append("exit")
            return None

        def commit(self) -> None:
            events.append("commit")

        def rollback(self) -> None:
            events.append("rollback")

    def factory() -> AbstractContextManager[_Session]:
        return _Session()

    dependency: Generator[Session] = get_database_session(
        cast(SessionFactory, factory),
    )
    next(dependency)
    events.append("endpoint")
    with suppress(StopIteration):
        next(dependency)

    assert events == ["enter", "endpoint", "commit", "exit"]
