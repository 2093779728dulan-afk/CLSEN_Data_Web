"""MySQL engine construction and per-connection invariants."""

from __future__ import annotations

from typing import Any

import sqlalchemy as sa
from sqlalchemy.engine import Engine

from app.db.settings import DatabaseSettings
from app.maintenance.barrier import install_maintenance_write_barrier


def configure_mysql_connection(
    dbapi_connection: Any,
    _connection_record: Any,
) -> None:
    """Set every new and recycled DBAPI connection to an explicit UTC session."""

    cursor = dbapi_connection.cursor()
    try:
        cursor.execute("SET time_zone = '+00:00'")
    finally:
        cursor.close()


def create_database_engine(settings: DatabaseSettings) -> Engine:
    """Create the bounded synchronous engine used by request handlers and workers."""

    engine = sa.create_engine(
        settings.url,
        hide_parameters=True,
        isolation_level="READ COMMITTED",
        max_overflow=settings.max_overflow,
        pool_pre_ping=True,
        pool_size=settings.pool_size,
    )
    sa.event.listen(engine, "connect", configure_mysql_connection)
    install_maintenance_write_barrier(engine)
    return engine
