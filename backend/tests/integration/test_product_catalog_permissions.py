from __future__ import annotations

import os

import pytest
import sqlalchemy as sa
from app.db.settings import DatabaseSettings

pytestmark = pytest.mark.mysql


def _engine(name: str) -> sa.Engine:
    return sa.create_engine(
        DatabaseSettings.from_env(name, pool_size=1, max_overflow=0).url,
        pool_pre_ping=True,
    )


def _grants(engine: sa.Engine) -> str:
    with engine.connect() as connection:
        return "\n".join(
            str(row[0]) for row in connection.execute(sa.text("SHOW GRANTS"))
        )


def test_runtime_and_backup_accounts_have_no_ddl_or_grant_option() -> None:
    runtime = _engine("APP_TEST_RUNTIME_DATABASE_URL")
    backup = _engine("APP_TEST_BACKUP_DATABASE_URL")
    try:
        runtime_grants = _grants(runtime).upper()
        backup_grants = _grants(backup).upper()
    finally:
        runtime.dispose()
        backup.dispose()
    for grants in (runtime_grants, backup_grants):
        assert "CREATE" not in grants
        assert "ALTER" not in grants
        assert "DROP" not in grants
        assert "GRANT OPTION" not in grants
    assert "SELECT" in runtime_grants
    assert "SELECT" in backup_grants


def test_runtime_and_backup_negative_writes_fail_closed() -> None:
    runtime = _engine("APP_TEST_RUNTIME_DATABASE_URL")
    backup = _engine("APP_TEST_BACKUP_DATABASE_URL")
    try:
        with pytest.raises(sa.exc.DBAPIError), runtime.begin() as connection:
            connection.exec_driver_sql(
                "CREATE TABLE product_catalog_forbidden_runtime (id BIGINT)"
            )
        with pytest.raises(sa.exc.DBAPIError), backup.begin() as connection:
            connection.exec_driver_sql(
                "INSERT INTO product_styles (site_id) VALUES (1)"
            )
    finally:
        runtime.dispose()
        backup.dispose()


def test_canary_identity_is_select_only_when_configured() -> None:
    value = os.getenv("APP_PRODUCT_CATALOG_CANARY_DATABASE_URL", "").strip()
    if not value:
        pytest.skip("current database canary is verified only by its canonical runner")
    engine = sa.create_engine(DatabaseSettings.from_url(value).url)
    try:
        grants = _grants(engine).upper()
    finally:
        engine.dispose()
    assert "SELECT" in grants
    for forbidden in ("INSERT", "UPDATE", "DELETE", "CREATE", "ALTER", "DROP"):
        assert forbidden not in grants
