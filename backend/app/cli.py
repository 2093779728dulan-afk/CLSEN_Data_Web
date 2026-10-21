"""One-time administrative commands that keep credentials out of argv."""

from __future__ import annotations

import argparse
import json
import sys
import unicodedata
from collections.abc import Callable, Sequence
from getpass import getpass
from pathlib import Path

import sqlalchemy as sa
from dotenv import dotenv_values
from sqlalchemy.engine import Engine
from sqlalchemy.exc import SQLAlchemyError

from app.auth.passwords import hash_password
from app.db.engine import create_database_engine
from app.db.settings import DatabaseSettings
from app.maintenance.schema_revision import CURRENT_SCHEMA_REVISION

_ADMINISTRATOR_LOCK_NAME_SQL = (
    "SHA2(CONCAT(DATABASE(), '-create-first-administrator'), 256)"
)
_ADMINISTRATOR_LOCK_TIMEOUT_SECONDS = 30
_MINIMUM_PASSWORD_LENGTH = 12
_MAXIMUM_PASSWORD_LENGTH = 4096


def normalise_username(username: str) -> str:
    """Return the stable lookup form stored by the account tables."""

    normalised = unicodedata.normalize("NFKC", username).strip().casefold()
    if not normalised:
        raise ValueError("username must not be blank")
    if len(normalised) > 191:
        raise ValueError("username must not exceed 191 characters")
    return normalised


def prompt_new_password(prompt: Callable[[str], str] = getpass) -> str:
    """Prompt twice without echoing or accepting a command-line password."""

    password = prompt("New application administrator password: ")
    confirmation = prompt("Confirm application administrator password: ")
    if password != confirmation:
        raise ValueError("password confirmation does not match")
    if not password:
        raise ValueError("password must not be empty")
    return password


def _database_settings_from_file(environment_file: Path) -> DatabaseSettings:
    """Load only the runtime database URL from one explicit environment file."""

    values = dotenv_values(environment_file)
    database_url = values.get("APP_DATABASE_URL")
    if not isinstance(database_url, str) or not database_url.strip():
        raise ValueError("APP_DATABASE_URL must be configured in the environment file")
    return DatabaseSettings.from_url(database_url)


def assert_password_reset_schema(settings: DatabaseSettings) -> None:
    """Fail clearly before prompting when the local schema is too old."""

    engine = sa.create_engine(settings.url, hide_parameters=True, pool_pre_ping=True)
    try:
        with engine.connect() as connection:
            revision = connection.scalar(
                sa.text("SELECT version_num FROM alembic_version LIMIT 1")
            )
            barrier_exists = connection.scalar(
                sa.text(
                    """
                    SELECT COUNT(*)
                    FROM information_schema.tables
                    WHERE table_schema = DATABASE()
                      AND table_name = 'maintenance_write_barrier'
                    """
                )
            )
    finally:
        engine.dispose()

    if revision != CURRENT_SCHEMA_REVISION or barrier_exists != 1:
        raise RuntimeError(
            "the application database schema is out of date "
            f"(found revision {revision!r}, expected "
            f"{CURRENT_SCHEMA_REVISION!r}); stop the application and run "
            "scripts/init-database.ps1 with -AllowExistingPrimaryDatabase, "
            "-ForceEnvironmentFile, and -SkipApplicationAdmin before resetting "
            "the password"
        )


def create_administrator(
    engine: Engine,
    *,
    username: str,
    display_name: str | None,
    password: str,
) -> int:
    """Create one active user and atomically assign the seeded admin role."""

    username_normalised = normalise_username(username)
    resolved_display_name = (display_name or username).strip()
    if not resolved_display_name:
        raise ValueError("display name must not be blank")

    with engine.connect() as connection:
        lock_acquired = connection.scalar(
            sa.text(
                f"SELECT GET_LOCK({_ADMINISTRATOR_LOCK_NAME_SQL}, :timeout_seconds)"
            ),
            {"timeout_seconds": _ADMINISTRATOR_LOCK_TIMEOUT_SECONDS},
        )
        if lock_acquired != 1:
            connection.rollback()
            raise RuntimeError("could not acquire the administrator bootstrap lock")

        try:
            connection.commit()
            with connection.begin():
                admin_role_id = connection.scalar(
                    sa.text("SELECT id FROM roles WHERE code = 'admin' LIMIT 1")
                )
                if admin_role_id is None:
                    raise RuntimeError(
                        "the admin role seed is missing; run migrations first"
                    )

                existing_admin_user_id = connection.scalar(
                    sa.text(
                        """
                        SELECT user_id
                        FROM user_roles
                        WHERE role_id = :role_id
                        LIMIT 1
                        """
                    ),
                    {"role_id": admin_role_id},
                )
                if existing_admin_user_id is not None:
                    raise ValueError("an application administrator already exists")

                existing_user_id = connection.scalar(
                    sa.text(
                        """
                        SELECT id
                        FROM users
                        WHERE username_normalized = :username
                        LIMIT 1
                        """
                    ),
                    {"username": username_normalised},
                )
                if existing_user_id is not None:
                    raise ValueError("an account with this username already exists")

                result = connection.execute(
                    sa.text(
                        """
                        INSERT INTO users (
                            username_normalized,
                            display_name,
                            password_hash,
                            status,
                            created_at,
                            updated_at
                        ) VALUES (
                            :username,
                            :display_name,
                            :password_hash,
                            'active',
                            UTC_TIMESTAMP(6),
                            UTC_TIMESTAMP(6)
                        )
                        """
                    ),
                    {
                        "username": username_normalised,
                        "display_name": resolved_display_name,
                        "password_hash": hash_password(password),
                    },
                )
                user_id = result.lastrowid
                if user_id is None:
                    raise RuntimeError(
                        "database did not return the created administrator ID"
                    )

                connection.execute(
                    sa.text(
                        """
                        INSERT INTO user_roles (
                            user_id,
                            role_id,
                            assigned_by,
                            assigned_at
                        ) VALUES (
                            :user_id,
                            :role_id,
                            :user_id,
                            UTC_TIMESTAMP(6)
                        )
                        """
                    ),
                    {"user_id": user_id, "role_id": admin_role_id},
                )
        finally:
            try:
                lock_released = connection.scalar(
                    sa.text(f"SELECT RELEASE_LOCK({_ADMINISTRATOR_LOCK_NAME_SQL})")
                )
                connection.commit()
            except BaseException:
                connection.invalidate()
                raise
            if lock_released != 1:
                connection.invalidate()
                raise RuntimeError("could not release the administrator bootstrap lock")

    return int(user_id)


def reset_administrator_password(
    engine: Engine,
    *,
    username: str,
    password: str,
) -> int:
    """Reset one existing administrator password and revoke all active sessions."""

    username_normalised = normalise_username(username)
    if len(password) < _MINIMUM_PASSWORD_LENGTH:
        raise ValueError(
            f"password must contain at least {_MINIMUM_PASSWORD_LENGTH} characters"
        )
    if len(password) > _MAXIMUM_PASSWORD_LENGTH:
        raise ValueError(
            f"password must not exceed {_MAXIMUM_PASSWORD_LENGTH} characters"
        )
    password_hash = hash_password(password)

    with engine.begin() as connection:
        user_id = connection.scalar(
            sa.text(
                """
                SELECT users.id
                FROM users
                INNER JOIN user_roles ON user_roles.user_id = users.id
                INNER JOIN roles ON roles.id = user_roles.role_id
                WHERE users.username_normalized = :username
                  AND roles.code = 'admin'
                LIMIT 1
                """
            ),
            {"username": username_normalised},
        )
        if user_id is None:
            raise ValueError("the requested application administrator does not exist")

        updated = connection.execute(
            sa.text(
                """
                UPDATE users AS account
                SET account.password_hash = :password_hash,
                    account.updated_at = GREATEST(
                        UTC_TIMESTAMP(6),
                        TIMESTAMPADD(MICROSECOND, 1, account.updated_at)
                    )
                WHERE account.id = :user_id
                  AND EXISTS (
                      SELECT 1
                      FROM user_roles
                      INNER JOIN roles ON roles.id = user_roles.role_id
                      WHERE user_roles.user_id = account.id
                        AND roles.code = 'admin'
                  )
                """
            ),
            {"password_hash": password_hash, "user_id": int(user_id)},
        )
        if updated.rowcount != 1:
            raise ValueError(
                "the requested account is no longer an application administrator"
            )
        connection.execute(
            sa.text(
                """
                UPDATE auth_sessions
                SET revoked_at = UTC_TIMESTAMP(6),
                    revoked_reason = 'cli_admin_password_reset'
                WHERE user_id = :user_id
                  AND revoked_at IS NULL
                """
            ),
            {"user_id": int(user_id)},
        )
        connection.execute(
            sa.text(
                """
                INSERT INTO audit_events (
                    site_id, actor_user_id, event_type, object_type, object_id,
                    request_id, redacted_payload, occurred_at
                ) VALUES (
                    NULL, NULL, 'admin.password_reset_cli', 'user', :object_id,
                    NULL, :redacted_payload, UTC_TIMESTAMP(6)
                )
                """
            ),
            {
                "object_id": str(user_id),
                "redacted_payload": json.dumps(
                    {"password_reset": True, "sessions_revoked": True},
                    sort_keys=True,
                ),
            },
        )

    return int(user_id)


def build_parser() -> argparse.ArgumentParser:
    """Build the command contract; passwords are intentionally absent."""

    parser = argparse.ArgumentParser(prog="python -m app.cli")
    commands = parser.add_subparsers(dest="command", required=True)
    create_admin = commands.add_parser(
        "create-admin",
        help="create the first application administrator through a secure prompt",
    )
    create_admin.add_argument("--username", required=True)
    create_admin.add_argument("--display-name")
    reset_admin_password = commands.add_parser(
        "reset-admin-password",
        help="reset an existing administrator password through a secure prompt",
    )
    reset_admin_password.add_argument("--username", required=True)
    reset_admin_password.add_argument(
        "--environment-file",
        required=True,
        type=Path,
        help="environment file containing APP_DATABASE_URL",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    """Run one administrative command and return a process exit code."""

    arguments = build_parser().parse_args(argv)
    if arguments.command == "create-admin":
        settings = DatabaseSettings.from_env("APP_DATABASE_URL")
    elif arguments.command == "reset-admin-password":
        settings = _database_settings_from_file(arguments.environment_file)
        assert_password_reset_schema(settings)
    else:
        raise RuntimeError(f"unsupported command: {arguments.command}")

    password = prompt_new_password()
    engine = create_database_engine(settings)
    try:
        if arguments.command == "create-admin":
            user_id = create_administrator(
                engine,
                username=str(arguments.username),
                display_name=arguments.display_name,
                password=password,
            )
            action = "created"
        else:
            user_id = reset_administrator_password(
                engine,
                username=str(arguments.username),
                password=password,
            )
            action = "password reset"
    finally:
        engine.dispose()

    print(f"Application administrator {action} for ID {user_id}.")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except (ValueError, RuntimeError, SQLAlchemyError) as error:
        print(f"Administrator command failed: {error}", file=sys.stderr)
        sys.exit(2)
