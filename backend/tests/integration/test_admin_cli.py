from __future__ import annotations

import json
import os
from concurrent.futures import ThreadPoolExecutor
from threading import Event
from typing import Any
from unittest.mock import patch

import pytest
import sqlalchemy as sa
from alembic import command
from alembic.config import Config
from app.auth.passwords import hash_password, verify_password
from app.cli import create_administrator, reset_administrator_password
from app.db.engine import create_database_engine
from app.db.settings import DatabaseSettings
from sqlalchemy.engine import Connection, Engine

pytestmark = pytest.mark.mysql

_TEST_USERNAME_PREFIX = "cli-concurrency-"


def _is_admin_advisory_lock(statement: str) -> bool:
    normalised = " ".join(statement.split()).upper()
    return "GET_LOCK" in normalised


@pytest.fixture()
def runtime_settings(
    mysql_settings: DatabaseSettings,
    request: pytest.FixtureRequest,
) -> DatabaseSettings:
    value = os.getenv("APP_TEST_RUNTIME_DATABASE_URL")
    if value is None or not value.strip():
        if request.config.getoption("--require-mysql"):
            raise pytest.UsageError(
                "APP_TEST_RUNTIME_DATABASE_URL is required by --require-mysql"
            )
        pytest.skip("APP_TEST_RUNTIME_DATABASE_URL is not configured")

    settings = DatabaseSettings.from_url(value, pool_size=1, max_overflow=0)
    migration_location = (
        (mysql_settings.url.host or "").casefold(),
        mysql_settings.url.port or 3306,
        mysql_settings.url.database,
    )
    runtime_location = (
        (settings.url.host or "").casefold(),
        settings.url.port or 3306,
        settings.url.database,
    )
    if runtime_location != migration_location:
        pytest.fail(
            "APP_TEST_RUNTIME_DATABASE_URL must target the configured test database",
            pytrace=False,
        )
    if settings.url.username == mysql_settings.url.username:
        pytest.fail(
            "runtime and migration test URLs must use different accounts",
            pytrace=False,
        )
    return settings


def _delete_cli_test_users(engine: Engine) -> None:
    with engine.begin() as connection:
        connection.execute(
            sa.text(
                """
                DELETE FROM audit_events
                WHERE event_type = 'admin.password_reset_cli'
                  AND object_id IN (
                      SELECT CAST(id AS CHAR)
                      FROM users
                      WHERE username_normalized LIKE :username_pattern
                  )
                """
            ),
            {"username_pattern": f"{_TEST_USERNAME_PREFIX}%"},
        )
        connection.execute(
            sa.text(
                """
                DELETE FROM auth_sessions
                WHERE user_id IN (
                    SELECT id
                    FROM users
                    WHERE username_normalized LIKE :username_pattern
                )
                """
            ),
            {"username_pattern": f"{_TEST_USERNAME_PREFIX}%"},
        )
        connection.execute(
            sa.text(
                """
                DELETE FROM user_roles
                WHERE user_id IN (
                    SELECT id
                    FROM users
                    WHERE username_normalized LIKE :username_pattern
                )
                """
            ),
            {"username_pattern": f"{_TEST_USERNAME_PREFIX}%"},
        )
        connection.execute(
            sa.text(
                "DELETE FROM users WHERE username_normalized LIKE :username_pattern"
            ),
            {"username_pattern": f"{_TEST_USERNAME_PREFIX}%"},
        )


def test_concurrent_first_admin_creation_is_serialized_by_named_lock(
    alembic_config: Config,
    mysql_engine: Engine,
    runtime_settings: DatabaseSettings,
) -> None:
    command.upgrade(alembic_config, "head")
    first_engine = create_database_engine(runtime_settings)
    second_engine = create_database_engine(runtime_settings)
    first_locked = Event()
    second_attempting_lock = Event()

    def wait_after_first_named_lock(
        _connection: Connection,
        _cursor: Any,
        statement: str,
        _parameters: Any,
        _context: Any,
        _executemany: bool,
    ) -> None:
        if _is_admin_advisory_lock(statement):
            first_locked.set()
            assert second_attempting_lock.wait(timeout=10)

    def signal_before_second_named_lock(
        _connection: Connection,
        _cursor: Any,
        statement: str,
        _parameters: Any,
        _context: Any,
        _executemany: bool,
    ) -> None:
        if _is_admin_advisory_lock(statement):
            assert first_locked.wait(timeout=10)
            second_attempting_lock.set()

    sa.event.listen(
        first_engine,
        "after_cursor_execute",
        wait_after_first_named_lock,
    )
    sa.event.listen(
        second_engine,
        "before_cursor_execute",
        signal_before_second_named_lock,
    )

    try:
        _delete_cli_test_users(mysql_engine)
        with mysql_engine.connect() as connection:
            existing_admins = connection.scalar(
                sa.text(
                    """
                    SELECT COUNT(*)
                    FROM user_roles AS assignment
                    JOIN roles AS role ON role.id = assignment.role_id
                    WHERE role.code = 'admin'
                    """
                )
            )
        assert existing_admins == 0

        with (
            patch("app.cli.hash_password", return_value="$argon2id$test-only"),
            ThreadPoolExecutor(max_workers=2) as executor,
        ):
            first = executor.submit(
                create_administrator,
                first_engine,
                username=f"{_TEST_USERNAME_PREFIX}first",
                display_name="First concurrent admin",
                password="first secret",
            )
            second = executor.submit(
                create_administrator,
                second_engine,
                username=f"{_TEST_USERNAME_PREFIX}second",
                display_name="Second concurrent admin",
                password="second secret",
            )

            assert first.result(timeout=15) > 0
            with pytest.raises(
                ValueError,
                match=r"administrator.*already exists",
            ):
                second.result(timeout=15)

        with mysql_engine.connect() as connection:
            admin_usernames = (
                connection.execute(
                    sa.text(
                        """
                    SELECT account.username_normalized
                    FROM users AS account
                    JOIN user_roles AS assignment ON assignment.user_id = account.id
                    JOIN roles AS role ON role.id = assignment.role_id
                    WHERE role.code = 'admin'
                    """
                    )
                )
                .scalars()
                .all()
            )
            lock_is_free = connection.scalar(
                sa.text(
                    """
                    SELECT IS_FREE_LOCK(
                        SHA2(
                            CONCAT(DATABASE(), '-create-first-administrator'),
                            256
                        )
                    )
                    """
                )
            )
        assert admin_usernames == [f"{_TEST_USERNAME_PREFIX}first"]
        assert lock_is_free == 1
    finally:
        _delete_cli_test_users(mysql_engine)
        first_engine.dispose()
        second_engine.dispose()


def test_runtime_account_resets_admin_password_and_revokes_sessions(
    alembic_config: Config,
    mysql_engine: Engine,
    runtime_settings: DatabaseSettings,
) -> None:
    command.upgrade(alembic_config, "head")
    runtime_engine = create_database_engine(runtime_settings)
    username = f"{_TEST_USERNAME_PREFIX}password-reset-admin"
    old_password = "old password value"
    new_password = "new password value"

    try:
        _delete_cli_test_users(mysql_engine)
        with mysql_engine.begin() as connection:
            inserted = connection.execute(
                sa.text(
                    """
                    INSERT INTO users (
                        username_normalized, display_name, password_hash, status,
                        created_at, updated_at
                    ) VALUES (
                        :username, 'CLI password reset admin', :password_hash,
                        'locked', UTC_TIMESTAMP(6), UTC_TIMESTAMP(6)
                    )
                    """
                ),
                {"username": username, "password_hash": hash_password(old_password)},
            )
            assert inserted.lastrowid is not None
            user_id = int(inserted.lastrowid)
            connection.execute(
                sa.text(
                    """
                    INSERT INTO user_roles (user_id, role_id, assigned_at)
                    SELECT :user_id, id, UTC_TIMESTAMP(6)
                    FROM roles
                    WHERE code = 'admin'
                    """
                ),
                {"user_id": user_id},
            )
            connection.execute(
                sa.text(
                    """
                    INSERT INTO auth_sessions (
                        token_hash, csrf_token_hash, user_id, created_at,
                        expires_at, last_seen_at
                    ) VALUES (
                        :token_hash, :csrf_token_hash, :user_id, UTC_TIMESTAMP(6),
                        TIMESTAMPADD(HOUR, 1, UTC_TIMESTAMP(6)), UTC_TIMESTAMP(6)
                    )
                    """
                ),
                {
                    "token_hash": bytes(range(32)),
                    "csrf_token_hash": bytes(range(32, 64)),
                    "user_id": user_id,
                },
            )

        reset_user_id = reset_administrator_password(
            runtime_engine,
            username=username,
            password=new_password,
        )
        assert reset_user_id == user_id

        with mysql_engine.connect() as connection:
            account = (
                connection.execute(
                    sa.text(
                        """
                        SELECT password_hash, status
                        FROM users
                        WHERE id = :user_id
                        """
                    ),
                    {"user_id": user_id},
                )
                .mappings()
                .one()
            )
            session = (
                connection.execute(
                    sa.text(
                        """
                        SELECT revoked_at, revoked_reason
                        FROM auth_sessions
                        WHERE user_id = :user_id
                        """
                    ),
                    {"user_id": user_id},
                )
                .mappings()
                .one()
            )
            audit_payload = connection.scalar(
                sa.text(
                    """
                    SELECT redacted_payload
                    FROM audit_events
                    WHERE event_type = 'admin.password_reset_cli'
                      AND object_id = :object_id
                    ORDER BY id DESC
                    LIMIT 1
                    """
                ),
                {"object_id": str(user_id)},
            )

        assert verify_password(str(account["password_hash"]), new_password)
        assert not verify_password(str(account["password_hash"]), old_password)
        assert account["status"] == "locked"
        assert session["revoked_at"] is not None
        assert session["revoked_reason"] == "cli_admin_password_reset"
        assert json.loads(str(audit_payload)) == {
            "password_reset": True,
            "sessions_revoked": True,
        }
    finally:
        _delete_cli_test_users(mysql_engine)
        runtime_engine.dispose()
