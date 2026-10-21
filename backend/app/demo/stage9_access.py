"""Create one password-backed account only in an isolated Stage 9 demo database."""

from __future__ import annotations

import argparse
import getpass
import re
import sys
from collections.abc import Sequence
from datetime import UTC, datetime
from pathlib import Path

import sqlalchemy as sa
from dotenv import dotenv_values
from sqlalchemy.engine import make_url
from sqlalchemy.exc import SQLAlchemyError

from app.auth.passwords import hash_password

_SAFE_DATABASE = re.compile(r"clsen_data_test(?:_[a-z0-9_]+)?\Z")
_SAFE_USERNAME = re.compile(r"[a-z0-9][a-z0-9_.-]{2,63}\Z")


def _arguments(arguments: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--environment-file", required=True, type=Path)
    parser.add_argument("--username", default="stage9-admin")
    parser.add_argument(
        "--role",
        choices=("admin", "data_manager", "viewer"),
        default="admin",
    )
    return parser.parse_args(arguments)


def _test_database_url(environment_file: Path) -> str:
    values = dotenv_values(environment_file)
    raw_url = values.get("APP_TEST_DATABASE_URL")
    if not isinstance(raw_url, str) or not raw_url.strip():
        raise ValueError("APP_TEST_DATABASE_URL must be configured")
    url = make_url(raw_url)
    if (
        url.drivername != "mysql+pymysql"
        or url.host not in {"127.0.0.1", "localhost", "::1"}
        or url.database is None
        or _SAFE_DATABASE.fullmatch(url.database) is None
    ):
        raise ValueError("the demo account tool accepts only a local test database")
    return raw_url


def main(arguments: Sequence[str] | None = None) -> int:
    options = _arguments(arguments)
    username = options.username.strip().casefold()
    if _SAFE_USERNAME.fullmatch(username) is None:
        raise ValueError("username must be 3-64 lowercase letters, digits, . _ or -")
    password = getpass.getpass("New Stage 9 demo password: ")
    if password != getpass.getpass("Confirm Stage 9 demo password: "):
        raise ValueError("password confirmation does not match")
    if len(password) < 12:
        raise ValueError("demo password must contain at least 12 characters")

    engine = sa.create_engine(_test_database_url(options.environment_file))
    with engine.begin() as connection:
        existing = connection.execute(
            sa.text(
                "SELECT id FROM users WHERE username_normalized = :username LIMIT 1"
            ),
            {"username": username},
        ).scalar_one_or_none()
        if existing is not None:
            raise ValueError(
                "the demo username already exists; choose another username"
            )
        inserted = connection.execute(
            sa.text(
                """
                INSERT INTO users (
                    username_normalized, display_name, password_hash, status,
                    created_at, updated_at
                ) VALUES (
                    :username, :display_name, :password_hash, 'active',
                    :now, :now
                )
                """
            ),
            {
                "username": username,
                "display_name": f"Stage 9 {options.role}",
                "password_hash": hash_password(password),
                "now": datetime.now(UTC).replace(tzinfo=None),
            },
        )
        if inserted.lastrowid is None:
            raise RuntimeError("database did not return the demo user ID")
        connection.execute(
            sa.text(
                """
                INSERT INTO user_roles (user_id, role_id, assigned_at)
                SELECT :user_id, id, :now FROM roles WHERE code = :role
                """
            ),
            {
                "user_id": int(inserted.lastrowid),
                "role": options.role,
                "now": datetime.now(UTC).replace(tzinfo=None),
            },
        )
    print(f"Created isolated demo account {username!r} with role {options.role!r}.")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (ValueError, SQLAlchemyError) as error:
        print(f"Stage 9 demo account was not created: {error}", file=sys.stderr)
        raise SystemExit(2) from error
