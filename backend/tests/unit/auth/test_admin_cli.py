from __future__ import annotations

from collections.abc import Iterator
from typing import cast
from unittest.mock import MagicMock, patch

import pytest
from app.cli import (
    assert_password_reset_schema,
    build_parser,
    create_administrator,
    normalise_username,
    prompt_new_password,
    reset_administrator_password,
)
from app.db.settings import DatabaseSettings
from app.maintenance.schema_revision import CURRENT_SCHEMA_REVISION
from sqlalchemy.engine import Connection, Engine


def _mock_engine(connection: MagicMock) -> Engine:
    engine = MagicMock(spec=Engine)
    engine.connect.return_value.__enter__.return_value = connection
    return cast(Engine, engine)


def _normalised_sql(statement: object) -> str:
    return " ".join(str(statement).split()).upper()


def test_admin_command_never_accepts_a_password_argument() -> None:
    parser = build_parser()

    create_arguments = parser.parse_args(["create-admin", "--username", "Owner"])

    assert create_arguments.command == "create-admin"
    assert create_arguments.username == "Owner"
    assert "password" not in vars(create_arguments)

    reset_arguments = parser.parse_args(
        [
            "reset-admin-password",
            "--username",
            "Owner",
            "--environment-file",
            ".env",
        ]
    )
    assert reset_arguments.command == "reset-admin-password"
    assert reset_arguments.username == "Owner"
    assert "password" not in vars(reset_arguments)

    for command in (
        ["create-admin", "--username", "Owner"],
        [
            "reset-admin-password",
            "--username",
            "Owner",
            "--environment-file",
            ".env",
        ],
    ):
        with pytest.raises(SystemExit):
            parser.parse_args([*command, "--password", "unsafe"])


def test_username_normalisation_is_stable_and_rejects_blank_values() -> None:
    assert normalise_username("  \uff21dmin  ") == "admin"

    with pytest.raises(ValueError, match="username"):
        normalise_username("   ")


def test_password_prompt_requires_confirmation_without_echoing() -> None:
    answers: Iterator[str] = iter(["first answer", "different answer"])

    with pytest.raises(ValueError, match="match"):
        prompt_new_password(lambda _prompt: next(answers))

    confirmed: Iterator[str] = iter(["same answer", "same answer"])
    assert prompt_new_password(lambda _prompt: next(confirmed)) == "same answer"


def test_create_administrator_holds_named_lock_around_admin_transaction() -> None:
    connection = MagicMock(spec=Connection)
    connection.scalar.side_effect = [1, 7, None, None, 1]
    insert_result = MagicMock()
    insert_result.lastrowid = 42
    connection.execute.return_value = insert_result

    with patch("app.cli.hash_password", return_value="stored hash") as hasher:
        user_id = create_administrator(
            _mock_engine(connection),
            username="NewOwner",
            display_name="New Owner",
            password="secret value",
        )

    assert user_id == 42
    scalar_calls = connection.scalar.call_args_list
    assert len(scalar_calls) == 5

    acquire_lock_sql = _normalised_sql(scalar_calls[0].args[0])
    assert "GET_LOCK" in acquire_lock_sql
    assert "DATABASE()" in acquire_lock_sql

    role_sql = _normalised_sql(scalar_calls[1].args[0])
    assert "FROM ROLES" in role_sql
    assert "FOR UPDATE" not in role_sql

    membership_sql = _normalised_sql(scalar_calls[2].args[0])
    assert "FROM USER_ROLES" in membership_sql
    assert "FOR UPDATE" not in membership_sql
    assert scalar_calls[2].args[1] == {"role_id": 7}

    username_sql = _normalised_sql(scalar_calls[3].args[0])
    assert "FROM USERS" in username_sql
    release_lock_sql = _normalised_sql(scalar_calls[4].args[0])
    assert "RELEASE_LOCK" in release_lock_sql
    assert connection.commit.call_count == 2
    hasher.assert_called_once_with("secret value")

    execute_parameters = [call.args[1] for call in connection.execute.call_args_list]
    assert all(
        "secret value" not in parameters.values() for parameters in execute_parameters
    )


def test_create_administrator_rejects_any_existing_admin_role_member() -> None:
    connection = MagicMock(spec=Connection)
    connection.scalar.side_effect = [1, 7, 99, 1]

    with (
        patch("app.cli.hash_password") as hasher,
        pytest.raises(ValueError, match=r"administrator.*already exists"),
    ):
        create_administrator(
            _mock_engine(connection),
            username="DifferentOwner",
            display_name=None,
            password="secret value",
        )

    hasher.assert_not_called()
    connection.execute.assert_not_called()
    assert "RELEASE_LOCK" in _normalised_sql(
        connection.scalar.call_args_list[-1].args[0]
    )


def test_reset_administrator_password_is_atomic_and_revokes_sessions() -> None:
    connection = MagicMock(spec=Connection)
    connection.scalar.return_value = 42
    connection.execute.return_value.rowcount = 1
    engine = MagicMock(spec=Engine)
    engine.begin.return_value.__enter__.return_value = connection

    with patch("app.cli.hash_password", return_value="stored hash") as hasher:
        user_id = reset_administrator_password(
            cast(Engine, engine),
            username="  \uff34\uff23\uff2a ",
            password="new secret value",
        )

    assert user_id == 42
    hasher.assert_called_once_with("new secret value")
    lookup_sql = _normalised_sql(connection.scalar.call_args.args[0])
    assert "INNER JOIN USER_ROLES" in lookup_sql
    assert "ROLES.CODE = 'ADMIN'" in lookup_sql
    assert "FOR UPDATE" not in lookup_sql
    assert connection.scalar.call_args.args[1] == {"username": "tcj"}

    execute_calls = connection.execute.call_args_list
    assert len(execute_calls) == 3
    password_sql = _normalised_sql(execute_calls[0].args[0])
    assert "UPDATE USERS" in password_sql
    assert "EXISTS" in password_sql
    assert "ROLES.CODE = 'ADMIN'" in password_sql
    assert execute_calls[0].args[1] == {
        "password_hash": "stored hash",
        "user_id": 42,
    }
    session_sql = _normalised_sql(execute_calls[1].args[0])
    assert "UPDATE AUTH_SESSIONS" in session_sql
    assert "CLI_ADMIN_PASSWORD_RESET" in session_sql
    audit_sql = _normalised_sql(execute_calls[2].args[0])
    assert "INSERT INTO AUDIT_EVENTS" in audit_sql
    assert "ADMIN.PASSWORD_RESET_CLI" in audit_sql

    all_parameters = [call.args[1] for call in execute_calls]
    assert all("new secret value" not in values.values() for values in all_parameters)


def test_reset_administrator_password_rejects_non_admin_and_short_password() -> None:
    connection = MagicMock(spec=Connection)
    connection.scalar.return_value = None
    engine = MagicMock(spec=Engine)
    engine.begin.return_value.__enter__.return_value = connection

    with (
        patch("app.cli.hash_password", return_value="stored hash"),
        pytest.raises(ValueError, match=r"administrator.*does not exist"),
    ):
        reset_administrator_password(
            cast(Engine, engine),
            username="viewer",
            password="new secret value",
        )

    connection.execute.assert_not_called()

    with (
        patch("app.cli.hash_password") as hasher,
        pytest.raises(ValueError, match="at least 12"),
    ):
        reset_administrator_password(
            cast(Engine, engine),
            username="tcj",
            password="too short",
        )
    hasher.assert_not_called()


def test_password_reset_schema_preflight_rejects_an_old_database() -> None:
    connection = MagicMock(spec=Connection)
    connection.scalar.side_effect = ["0006", 0]
    engine = MagicMock(spec=Engine)
    engine.connect.return_value.__enter__.return_value = connection
    settings = DatabaseSettings.from_url(
        "mysql+pymysql://app:secret@127.0.0.1/clsen_data?charset=utf8mb4"
    )

    with (
        patch("app.cli.sa.create_engine", return_value=engine),
        pytest.raises(
            RuntimeError,
            match=rf"revision '0006'.*expected '{CURRENT_SCHEMA_REVISION}'",
        ),
    ):
        assert_password_reset_schema(settings)

    engine.dispose.assert_called_once_with()


def test_password_reset_schema_preflight_accepts_the_current_database() -> None:
    connection = MagicMock(spec=Connection)
    connection.scalar.side_effect = [CURRENT_SCHEMA_REVISION, 1]
    engine = MagicMock(spec=Engine)
    engine.connect.return_value.__enter__.return_value = connection
    settings = DatabaseSettings.from_url(
        "mysql+pymysql://app:secret@127.0.0.1/clsen_data?charset=utf8mb4"
    )

    with patch("app.cli.sa.create_engine", return_value=engine):
        assert_password_reset_schema(settings)

    engine.dispose.assert_called_once_with()
