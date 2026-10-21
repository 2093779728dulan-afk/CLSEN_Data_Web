from __future__ import annotations

import os

import pytest
import sqlalchemy as sa
from alembic import command
from alembic.config import Config
from app.db.engine import create_database_engine
from app.db.settings import DatabaseSettings
from sqlalchemy.exc import DBAPIError

pytestmark = pytest.mark.mysql


def _engine(variable_name: str) -> sa.Engine:
    return create_database_engine(DatabaseSettings.from_url(os.environ[variable_name]))


def test_catalog_runtime_grants_are_insert_only_or_narrowly_mutable(
    alembic_config: Config,
) -> None:
    command.upgrade(alembic_config, "head")
    engine = _engine("APP_TEST_RUNTIME_DATABASE_URL")
    try:
        with engine.connect() as connection:
            with pytest.raises(DBAPIError):
                connection.execute(
                    sa.text(
                        "UPDATE report_source_scopes "
                        "SET seller_account_display_name = "
                        "seller_account_display_name WHERE 1 = 0"
                    )
                )
            connection.execute(
                sa.text(
                    "UPDATE product_catalog_publications "
                    "SET catalog_publication_revision = "
                    "catalog_publication_revision WHERE 1 = 0"
                )
            )
            with pytest.raises(DBAPIError):
                connection.execute(
                    sa.text(
                        "UPDATE product_catalog_publications "
                        "SET site_id = site_id WHERE 1 = 0"
                    )
                )
            with pytest.raises(DBAPIError):
                connection.execute(sa.text("DROP TABLE catalog_jobs"))
    finally:
        engine.dispose()


def test_catalog_backup_identity_remains_select_only_for_business_tables(
    alembic_config: Config,
) -> None:
    command.upgrade(alembic_config, "head")
    engine = _engine("APP_TEST_BACKUP_DATABASE_URL")
    try:
        with engine.connect() as connection:
            assert (
                connection.scalar(sa.text("SELECT COUNT(*) FROM product_styles")) == 0
            )
            with pytest.raises(DBAPIError):
                connection.execute(
                    sa.text(
                        "INSERT INTO product_styles "
                        "(site_id, style_code, style_key_sha256, style_key_bytes, "
                        "standard_name, status, current_revision) "
                        "VALUES (1, 'x', REPEAT(0x00, 32), 0x78, 'x', "
                        "'enabled', 1)"
                    )
                )
    finally:
        engine.dispose()
