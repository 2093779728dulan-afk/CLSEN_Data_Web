"""Database helpers for tests that replay historical schema revisions."""

from __future__ import annotations

import sqlalchemy as sa
from app.db.engine import configure_mysql_connection
from app.db.settings import DatabaseSettings
from sqlalchemy.engine import Engine


def create_historical_schema_engine(settings: DatabaseSettings) -> Engine:
    """Create an engine that remains usable before the runtime barrier exists."""

    engine = sa.create_engine(
        settings.url,
        hide_parameters=True,
        isolation_level="READ COMMITTED",
        max_overflow=settings.max_overflow,
        pool_pre_ping=True,
        pool_size=settings.pool_size,
    )
    sa.event.listen(engine, "connect", configure_mysql_connection)
    return engine
