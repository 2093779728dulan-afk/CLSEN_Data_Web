from __future__ import annotations

import json
import os
from pathlib import Path
from unittest.mock import MagicMock

import app.deployment.entrypoint as entrypoint
import pytest
from app.deployment.entrypoint import (
    DeploymentConfigurationError,
    _entry_arguments,
    build_database_url,
    load_privilege_manifest,
    privilege_statements,
    write_root_option_file,
)
from sqlalchemy.engine import make_url


def test_database_url_percent_encodes_secret_and_requires_mysql_tls() -> None:
    rendered = build_database_url(
        username="clsen_app",
        password="secret:/?#[]@ value",
        database="clsen_data",
        host="mysql",
        ssl_ca="/run/mysql-tls/ca.pem",
    )

    parsed = make_url(rendered)
    assert parsed.username == "clsen_app"
    assert parsed.password == "secret:/?#[]@ value"
    assert parsed.host == "mysql"
    assert parsed.database == "clsen_data"
    assert parsed.query["charset"] == "utf8mb4"
    assert parsed.query["ssl_ca"] == "/run/mysql-tls/ca.pem"
    assert parsed.query["ssl_check_hostname"] == "true"


def test_privilege_statements_match_manifest_and_revoke_before_granting(
    tmp_path: Path,
) -> None:
    manifest_path = tmp_path / "privileges.json"
    manifest_path.write_text(
        json.dumps(
            {
                "version": 1,
                "runtime": {
                    "insert_only": ["audit_events"],
                    "mutable_insert": ["users"],
                    "update": ["users"],
                    "update_columns": {"daily_dataset_locks": ["lock_revision"]},
                    "delete": ["user_roles"],
                },
                "backup": {
                    "schema": ["SELECT", "SHOW VIEW"],
                    "insert": ["backup_snapshots"],
                    "update": ["backup_snapshots"],
                },
            }
        ),
        encoding="utf-8",
    )

    manifest = load_privilege_manifest(manifest_path)
    statements = privilege_statements(manifest, database="clsen_data")

    assert all("REVOKE ALL PRIVILEGES" not in statement for statement in statements)
    assert "GRANT SELECT ON `clsen_data`.* TO 'clsen_app'@'%'" in statements
    assert (
        "GRANT UPDATE (`lock_revision`) ON "
        "`clsen_data`.`daily_dataset_locks` TO 'clsen_app'@'%'"
    ) in statements
    assert (
        "GRANT SELECT, SHOW VIEW ON `clsen_data`.* TO 'clsen_backup'@'%'"
    ) in statements
    assert statements[-1] == "FLUSH PRIVILEGES"


def test_privilege_manifest_rejects_unsafe_identifiers(tmp_path: Path) -> None:
    path = tmp_path / "privileges.json"
    path.write_text(
        json.dumps(
            {
                "version": 1,
                "runtime": {
                    "insert_only": ["audit_events; DROP DATABASE clsen_data"],
                    "mutable_insert": [],
                    "update": [],
                    "update_columns": {},
                    "delete": [],
                },
                "backup": {"schema": ["SELECT"], "insert": [], "update": []},
            }
        ),
        encoding="utf-8",
    )

    with pytest.raises(DeploymentConfigurationError, match="unsafe identifier"):
        load_privilege_manifest(path)


def test_root_option_file_requires_verified_internal_tls(tmp_path: Path) -> None:
    option_file = tmp_path / "root.cnf"

    write_root_option_file(option_file, "safe_url_secret_" + "x" * 32)

    content = option_file.read_text(encoding="utf-8")
    assert 'user="root"' in content
    assert 'host="mysql"' in content
    assert "ssl-mode=VERIFY_CA" in content
    assert 'ssl-ca="/run/secrets/mysql_ca_certificate"' in content
    assert "safe_url_secret_" in content


def test_passthrough_commands_preserve_leading_options() -> None:
    command, arguments = _entry_arguments(
        ["restore-verify", "--backup-directory", "/backup", "--cleanup"]
    )

    assert command == "restore-verify"
    assert arguments == ["--backup-directory", "/backup", "--cleanup"]


@pytest.mark.parametrize("empty", [False, True])
def test_reset_test_database_keeps_empty_replay_separate_from_current_head(
    monkeypatch: pytest.MonkeyPatch, empty: bool
) -> None:
    database = "clsen_data_test_migration_replay"
    monkeypatch.setenv("APP_DEPLOYMENT_DATABASE", database)
    monkeypatch.setenv("APP_DEPLOYMENT_TEST_DATABASE", database)
    monkeypatch.setenv("APP_TEST_DATABASE_URL", "test-migrator-url")
    monkeypatch.setattr(entrypoint, "_configure_process_environment", MagicMock())
    engine = MagicMock()
    monkeypatch.setattr(entrypoint, "_root_engine", MagicMock(return_value=engine))
    upgrade = MagicMock()
    grants = MagicMock()
    monkeypatch.setattr(entrypoint, "_upgrade", upgrade)
    monkeypatch.setattr(entrypoint, "_synchronise_privileges", grants)

    assert (
        entrypoint.main(["reset-test-database", *(["--empty"] if empty else [])]) == 0
    )

    connection = engine.begin.return_value.__enter__.return_value
    statements = [call.args[0] for call in connection.exec_driver_sql.call_args_list]
    assert statements == [
        f"DROP DATABASE IF EXISTS `{database}`",
        f"CREATE DATABASE `{database}` CHARACTER SET utf8mb4 "
        "COLLATE utf8mb4_0900_ai_ci",
    ]
    if empty:
        upgrade.assert_not_called()
        grants.assert_not_called()
    else:
        upgrade.assert_called_once_with("test-migrator-url")
        grants.assert_called_once_with(engine, database)
    engine.dispose.assert_called_once_with()


@pytest.mark.parametrize("empty", [False, True])
def test_reset_modes_reject_business_database_before_connecting(
    monkeypatch: pytest.MonkeyPatch, empty: bool
) -> None:
    monkeypatch.setenv("APP_DEPLOYMENT_TEST_DATABASE", "clsen_data")
    monkeypatch.setattr(entrypoint, "_configure_process_environment", MagicMock())
    root_engine = MagicMock()
    monkeypatch.setattr(entrypoint, "_root_engine", root_engine)

    with pytest.raises(DeploymentConfigurationError):
        entrypoint.main(["reset-test-database", *(["--empty"] if empty else [])])

    root_engine.assert_not_called()


def test_pytest_role_configures_distinct_schema_unreadable_url(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(entrypoint, "_read_secret", lambda _name: "x" * 64)
    monkeypatch.setenv("APP_DEPLOYMENT_DATABASE", "clsen_data_test_runner")
    monkeypatch.setenv("APP_DEPLOYMENT_TEST_DATABASE", "clsen_data_test_runner")

    entrypoint._configure_process_environment(
        accounts=frozenset(
            {"app", "backup", "migrator", "schema_unreadable", "session"}
        ),
        include_test=True,
    )

    unreadable = make_url(os.environ["APP_TEST_SCHEMA_UNREADABLE_DATABASE_URL"])
    migration = make_url(os.environ["APP_TEST_DATABASE_URL"])
    assert unreadable.username == "clsen_schema_unreadable"
    assert unreadable.password != migration.password
    assert unreadable.database == migration.database == "clsen_data_test_runner"


@pytest.mark.parametrize("command", ("api", "worker"))
def test_runtime_container_role_preflights_after_secrets_and_before_exec(
    command: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    events: list[tuple[str, object]] = []

    def configure(**keywords: object) -> None:
        events.append(("configure", keywords))

    def preflight(arguments: list[str]) -> int:
        events.append(("preflight", arguments))
        return 0

    monkeypatch.setattr(
        entrypoint,
        "_configure_process_environment",
        configure,
    )
    monkeypatch.setattr(
        entrypoint,
        "schema_preflight_main",
        preflight,
    )

    def stop_at_exec(arguments: list[str]) -> None:
        events.append(("exec", arguments))
        raise RuntimeError("exec boundary reached")

    monkeypatch.setattr(entrypoint, "_exec", stop_at_exec)

    with pytest.raises(RuntimeError, match="exec boundary reached"):
        entrypoint.main([command])

    assert events[0] == (
        "configure",
        {
            "accounts": frozenset({"app", "session"}),
            "include_test": False,
        },
    )
    assert events[1] == ("preflight", ["--component", command])
    assert events[2][0] == "exec"


@pytest.mark.parametrize("command", ("api", "worker"))
def test_runtime_container_role_never_execs_after_preflight_refusal(
    command: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    events: list[str] = []

    def configure(**_keywords: object) -> None:
        events.append("configure")

    def refuse(_arguments: list[str]) -> int:
        events.append("preflight")
        return 2

    monkeypatch.setattr(
        entrypoint,
        "_configure_process_environment",
        configure,
    )
    monkeypatch.setattr(
        entrypoint,
        "schema_preflight_main",
        refuse,
    )
    monkeypatch.setattr(
        entrypoint,
        "_exec",
        lambda _arguments: pytest.fail("exec reached after schema refusal"),
    )

    exit_code = entrypoint.main([command])

    assert exit_code == 2
    assert events == ["configure", "preflight"]
