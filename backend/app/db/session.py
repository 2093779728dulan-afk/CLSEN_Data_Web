"""Explicit transaction boundaries for synchronous SQLAlchemy services."""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager

from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker

SessionFactory = sessionmaker[Session]


def create_session_factory(engine: Engine) -> SessionFactory:
    """Bind a reusable factory without implicit commits or expiration surprises."""

    return sessionmaker(
        bind=engine,
        autoflush=False,
        expire_on_commit=False,
        class_=Session,
    )


@contextmanager
def transaction(factory: SessionFactory) -> Iterator[Session]:
    """Yield one session inside a commit-or-rollback transaction boundary."""

    with factory() as session, session.begin():
        yield session
