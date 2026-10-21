"""Alembic environment with explicit, redacted MySQL configuration."""

from __future__ import annotations

import os
from logging.config import fileConfig

import sqlalchemy as sa
from alembic import context
from app.db.engine import configure_mysql_connection
from app.db.settings import DatabaseSettings
from sqlalchemy import pool

config = context.config
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

target_metadata = None


def _database_settings() -> DatabaseSettings:
    return DatabaseSettings.from_env("APP_MIGRATION_DATABASE_URL")


def run_migrations_offline() -> None:
    """Render deterministic MySQL SQL without opening a network connection."""

    settings = _database_settings()
    context.configure(
        url=settings.url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        transactional_ddl=False,
    )

    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    """Apply migrations through the dedicated migration account."""

    settings = _database_settings()
    engine = sa.create_engine(
        settings.url,
        isolation_level="READ COMMITTED",
        poolclass=pool.NullPool,
    )
    sa.event.listen(engine, "connect", configure_mysql_connection)

    with engine.connect() as connection:
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
            compare_type=True,
            transactional_ddl=False,
        )
        with context.begin_transaction():
            context.run_migrations()

    engine.dispose()


if os.getenv("APP_MIGRATION_DATABASE_URL") is None:
    raise RuntimeError("APP_MIGRATION_DATABASE_URL must be configured")

if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
