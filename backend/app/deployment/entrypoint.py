"""Container entry point with secret-file and least-privilege handling."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import subprocess
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any, NoReturn, cast

import sqlalchemy as sa
from alembic import command
from alembic.config import Config
from sqlalchemy.engine import URL, Connection, Engine

from app.db.settings import DatabaseSettings
from app.schema_preflight import main as schema_preflight_main

_IDENTIFIER = re.compile(r"[A-Za-z_][A-Za-z0-9_]{0,63}\Z", re.ASCII)
_PRIVILEGE = re.compile(r"[A-Z][A-Z ]{0,63}\Z", re.ASCII)
_SCHEMA_PRIVILEGES = frozenset({"SELECT", "SHOW VIEW", "TRIGGER", "EVENT"})
_SECRET_NAMES = {
    "app": "mysql_app_password",
    "backup": "mysql_backup_password",
    "migrator": "mysql_migrator_password",
    "root": "mysql_root_password",
    "session": "session_secret",
}
_ACCOUNTS = {
    "app": "clsen_app",
    "backup": "clsen_backup",
    "migrator": "clsen_migrator",
    "schema_unreadable": "clsen_schema_unreadable",
}


class DeploymentConfigurationError(ValueError):
    """Deployment assets or secrets violate the server contract."""


@dataclass(frozen=True, slots=True)
class RuntimePrivileges:
    insert_only: tuple[str, ...]
    mutable_insert: tuple[str, ...]
    update: tuple[str, ...]
    update_columns: dict[str, tuple[str, ...]]
    delete: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class BackupPrivileges:
    schema: tuple[str, ...]
    insert: tuple[str, ...]
    update: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class PrivilegeManifest:
    version: int
    runtime: RuntimePrivileges
    backup: BackupPrivileges


def _identifier(value: object) -> str:
    if not isinstance(value, str) or _IDENTIFIER.fullmatch(value) is None:
        raise DeploymentConfigurationError(
            f"unsafe identifier in privilege manifest: {value!r}"
        )
    return value


def _identifier_list(value: object) -> tuple[str, ...]:
    if not isinstance(value, list):
        raise DeploymentConfigurationError("privilege manifest list is invalid")
    return tuple(_identifier(item) for item in value)


def _schema_privilege_list(value: object) -> tuple[str, ...]:
    if not isinstance(value, list) or not value:
        raise DeploymentConfigurationError("backup schema privileges are invalid")
    privileges: list[str] = []
    for item in value:
        if not isinstance(item, str) or item not in _SCHEMA_PRIVILEGES:
            raise DeploymentConfigurationError(
                f"unsafe schema privilege in manifest: {item!r}"
            )
        privileges.append(item)
    return tuple(privileges)


def _mapping(value: object, label: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise DeploymentConfigurationError(f"{label} must be an object")
    return cast(dict[str, Any], value)


def load_privilege_manifest(path: Path) -> PrivilegeManifest:
    """Load and validate the tracked table-level privilege manifest."""

    try:
        payload = _mapping(json.loads(path.read_text(encoding="utf-8")), "manifest")
        runtime = _mapping(payload["runtime"], "runtime")
        backup = _mapping(payload["backup"], "backup")
        update_columns_source = _mapping(runtime["update_columns"], "update_columns")
        update_columns = {
            _identifier(table): _identifier_list(columns)
            for table, columns in update_columns_source.items()
        }
        version = payload["version"]
        if not isinstance(version, int) or version < 1:
            raise DeploymentConfigurationError("privilege manifest version is invalid")
        return PrivilegeManifest(
            version=version,
            runtime=RuntimePrivileges(
                insert_only=_identifier_list(runtime["insert_only"]),
                mutable_insert=_identifier_list(runtime["mutable_insert"]),
                update=_identifier_list(runtime["update"]),
                update_columns=update_columns,
                delete=_identifier_list(runtime["delete"]),
            ),
            backup=BackupPrivileges(
                schema=_schema_privilege_list(backup["schema"]),
                insert=_identifier_list(backup["insert"]),
                update=_identifier_list(backup["update"]),
            ),
        )
    except (KeyError, json.JSONDecodeError) as error:
        raise DeploymentConfigurationError("privilege manifest is invalid") from error


def _quoted_identifier(value: str) -> str:
    return f"`{_identifier(value)}`"


def _unique(values: tuple[str, ...]) -> tuple[str, ...]:
    return tuple(dict.fromkeys(values))


def privilege_statements(
    manifest: PrivilegeManifest,
    *,
    database: str,
) -> tuple[str, ...]:
    """Render the exact runtime and backup grants for one migrated schema."""

    schema = _quoted_identifier(database)
    app = "'clsen_app'@'%'"
    backup = "'clsen_backup'@'%'"
    statements = [
        f"GRANT SELECT ON {schema}.* TO {app}",
    ]
    for table in _unique(
        manifest.runtime.insert_only + manifest.runtime.mutable_insert
    ):
        statements.append(
            f"GRANT INSERT ON {schema}.{_quoted_identifier(table)} TO {app}"
        )
    for table in _unique(manifest.runtime.update):
        statements.append(
            f"GRANT UPDATE ON {schema}.{_quoted_identifier(table)} TO {app}"
        )
    for table, columns in manifest.runtime.update_columns.items():
        column_list = ", ".join(_quoted_identifier(column) for column in columns)
        statements.append(
            f"GRANT UPDATE ({column_list}) ON {schema}.{_quoted_identifier(table)} "
            f"TO {app}"
        )
    for table in _unique(manifest.runtime.delete):
        statements.append(
            f"GRANT DELETE ON {schema}.{_quoted_identifier(table)} TO {app}"
        )
    schema_privileges = ", ".join(manifest.backup.schema)
    statements.append(f"GRANT {schema_privileges} ON {schema}.* TO {backup}")
    for table in _unique(manifest.backup.insert):
        statements.append(
            f"GRANT INSERT ON {schema}.{_quoted_identifier(table)} TO {backup}"
        )
    for table in _unique(manifest.backup.update):
        statements.append(
            f"GRANT UPDATE ON {schema}.{_quoted_identifier(table)} TO {backup}"
        )
    statements.append("FLUSH PRIVILEGES")
    return tuple(statements)


def _privilege(value: object) -> str:
    if not isinstance(value, str) or _PRIVILEGE.fullmatch(value) is None:
        raise DeploymentConfigurationError(
            f"unsafe privilege returned by MySQL: {value!r}"
        )
    return value


def _target_revoke_statements(
    connection: Connection,
    *,
    database: str,
    account: str,
) -> tuple[str, ...]:
    """Revoke explicit grants on one schema without touching other databases."""

    if account not in _ACCOUNTS.values():
        raise DeploymentConfigurationError("unsupported deployment account")
    schema = _quoted_identifier(database)
    grantee = f"'{account}'@'%'"
    parameters = {"database": database, "grantee": grantee}
    statements: list[str] = []

    column_rows = connection.execute(
        sa.text(
            """
            SELECT table_name, column_name, privilege_type
            FROM information_schema.column_privileges
            WHERE table_schema = :database AND grantee = :grantee
            ORDER BY table_name, privilege_type, column_name
            """
        ),
        parameters,
    ).mappings()
    column_groups: dict[tuple[str, str], list[str]] = {}
    for row in column_rows:
        key = (_identifier(row["table_name"]), _privilege(row["privilege_type"]))
        column_groups.setdefault(key, []).append(_identifier(row["column_name"]))
    for (table, privilege), columns in column_groups.items():
        column_list = ", ".join(_quoted_identifier(column) for column in columns)
        statements.append(
            f"REVOKE {privilege} ({column_list}) ON "
            f"{schema}.{_quoted_identifier(table)} FROM {grantee}"
        )

    table_rows = connection.execute(
        sa.text(
            """
            SELECT table_name, privilege_type
            FROM information_schema.table_privileges
            WHERE table_schema = :database AND grantee = :grantee
            ORDER BY table_name, privilege_type
            """
        ),
        parameters,
    ).mappings()
    table_groups: dict[str, list[str]] = {}
    for row in table_rows:
        table_groups.setdefault(_identifier(row["table_name"]), []).append(
            _privilege(row["privilege_type"])
        )
    for table, privileges in table_groups.items():
        statements.append(
            f"REVOKE {', '.join(privileges)} ON "
            f"{schema}.{_quoted_identifier(table)} FROM {grantee}"
        )

    schema_privileges = tuple(
        _privilege(value)
        for value in connection.scalars(
            sa.text(
                """
                SELECT privilege_type
                FROM information_schema.schema_privileges
                WHERE table_schema = :database AND grantee = :grantee
                ORDER BY privilege_type
                """
            ),
            parameters,
        )
    )
    if schema_privileges:
        statements.append(
            f"REVOKE {', '.join(schema_privileges)} ON {schema}.* FROM {grantee}"
        )
    return tuple(statements)


def build_database_url(
    *,
    username: str,
    password: str,
    database: str,
    host: str = "mysql",
    ssl_ca: str = "/run/secrets/mysql_ca_certificate",
) -> str:
    """Build a correctly escaped PyMySQL URL that verifies the server CA."""

    for value in (username, database, host):
        if not value.strip():
            raise DeploymentConfigurationError("database URL component is blank")
    return URL.create(
        "mysql+pymysql",
        username=username,
        password=password,
        host=host,
        port=3306,
        database=database,
        query={
            "charset": "utf8mb4",
            "ssl_ca": ssl_ca,
            "ssl_check_hostname": "true",
        },
    ).render_as_string(hide_password=False)


def write_root_option_file(path: Path, password: str) -> None:
    """Write a private MySQL client file for one isolated restore process."""

    if len(password) < 32 or re.fullmatch(r"[A-Za-z0-9_-]+", password) is None:
        raise DeploymentConfigurationError("root deployment secret is invalid")
    path.write_text(
        "\n".join(
            (
                "[client]",
                'user="root"',
                f'password="{password}"',
                'host="mysql"',
                "port=3306",
                "protocol=TCP",
                "default-character-set=utf8mb4",
                "ssl-mode=VERIFY_CA",
                'ssl-ca="/run/secrets/mysql_ca_certificate"',
                "",
            )
        ),
        encoding="utf-8",
    )
    path.chmod(0o600)


def _secret_directory() -> Path:
    return Path(os.getenv("DEPLOYMENT_SECRETS_DIR", "/run/secrets"))


def _read_secret(logical_name: str) -> str:
    filename = _SECRET_NAMES[logical_name]
    path = _secret_directory() / filename
    try:
        value = path.read_text(encoding="utf-8").strip()
    except OSError as error:
        raise DeploymentConfigurationError(
            f"required deployment secret is unavailable: {filename}"
        ) from error
    if len(value) < 32 or any(character in value for character in "\r\n\0"):
        raise DeploymentConfigurationError(f"deployment secret is invalid: {filename}")
    return value


def _schema_unreadable_password() -> str:
    source = _read_secret("migrator")
    return hashlib.sha256(f"schema-unreadable:{source}".encode()).hexdigest()


def _database_name(test_database: bool = False) -> str:
    variable = (
        "APP_DEPLOYMENT_TEST_DATABASE" if test_database else "APP_DEPLOYMENT_DATABASE"
    )
    default = "clsen_data_test_container" if test_database else "clsen_data"
    return _identifier(os.getenv(variable, default))


def _configure_process_environment(
    *,
    accounts: frozenset[str],
    include_test: bool = False,
) -> None:
    database = _database_name()
    if "app" in accounts:
        os.environ["APP_DATABASE_URL"] = build_database_url(
            username=_ACCOUNTS["app"],
            password=_read_secret("app"),
            database=database,
        )
    if "migrator" in accounts:
        os.environ["APP_MIGRATION_DATABASE_URL"] = build_database_url(
            username=_ACCOUNTS["migrator"],
            password=_read_secret("migrator"),
            database=database,
        )
    if "backup" in accounts:
        os.environ["APP_BACKUP_DATABASE_URL"] = build_database_url(
            username=_ACCOUNTS["backup"],
            password=_read_secret("backup"),
            database=database,
        )
    if include_test:
        test_database = _database_name(test_database=True)
        if "migrator" in accounts:
            os.environ["APP_TEST_DATABASE_URL"] = build_database_url(
                username=_ACCOUNTS["migrator"],
                password=_read_secret("migrator"),
                database=test_database,
            )
        if "app" in accounts:
            os.environ["APP_TEST_RUNTIME_DATABASE_URL"] = build_database_url(
                username=_ACCOUNTS["app"],
                password=_read_secret("app"),
                database=test_database,
            )
        if "backup" in accounts:
            os.environ["APP_TEST_BACKUP_DATABASE_URL"] = build_database_url(
                username=_ACCOUNTS["backup"],
                password=_read_secret("backup"),
                database=test_database,
            )
        if "schema_unreadable" in accounts:
            os.environ["APP_TEST_SCHEMA_UNREADABLE_DATABASE_URL"] = build_database_url(
                username=_ACCOUNTS["schema_unreadable"],
                password=_schema_unreadable_password(),
                database=test_database,
            )
    if "session" in accounts:
        os.environ["APP_SESSION_SECRET"] = _read_secret("session")


def _root_engine(database: str) -> Engine:
    settings = DatabaseSettings.from_url(
        build_database_url(
            username="root",
            password=_read_secret("root"),
            database=database,
        ),
        pool_size=1,
        max_overflow=0,
    )
    return sa.create_engine(
        settings.url,
        pool_pre_ping=True,
        pool_recycle=1800,
        pool_size=1,
        max_overflow=0,
    )


def _synchronise_credentials(engine: Engine) -> None:
    with engine.begin() as connection:
        for logical_name, account in _ACCOUNTS.items():
            password = (
                _schema_unreadable_password()
                if logical_name == "schema_unreadable"
                else _read_secret(logical_name)
            )
            connection.exec_driver_sql(
                f"ALTER USER '{account}'@'%%' IDENTIFIED WITH "
                "caching_sha2_password BY %s REQUIRE SSL",
                (password,),
            )


def _synchronise_privileges(engine: Engine, database: str) -> None:
    manifest_path = Path(
        os.getenv(
            "APP_PRIVILEGE_MANIFEST",
            "/app/scripts/database-privileges.json",
        )
    )
    manifest = load_privilege_manifest(manifest_path)
    with engine.begin() as connection:
        managed_accounts = [_ACCOUNTS["app"], _ACCOUNTS["backup"]]
        if database == "clsen_data_test" or database.startswith("clsen_data_test_"):
            managed_accounts.append(_ACCOUNTS["schema_unreadable"])
        revoke_statements = tuple(
            statement
            for account in managed_accounts
            for statement in _target_revoke_statements(
                connection,
                database=database,
                account=account,
            )
        )
        statements = [
            *revoke_statements,
            *privilege_statements(manifest, database=database),
        ]
        if database == "clsen_data_test" or database.startswith("clsen_data_test_"):
            statements.insert(
                -1,
                f"GRANT SELECT ON {_quoted_identifier(database)}.`sites` TO "
                "'clsen_schema_unreadable'@'%'",
            )
        for statement in statements:
            connection.exec_driver_sql(statement.replace("%", "%%"))


def _upgrade(database_url: str) -> None:
    previous = os.environ.get("APP_MIGRATION_DATABASE_URL")
    os.environ["APP_MIGRATION_DATABASE_URL"] = database_url
    try:
        configuration = Config("/app/backend/alembic.ini")
        command.upgrade(configuration, "head")
    finally:
        if previous is None:
            os.environ.pop("APP_MIGRATION_DATABASE_URL", None)
        else:
            os.environ["APP_MIGRATION_DATABASE_URL"] = previous


def _activate_migration_bypass(database_url: str) -> None:
    """Bind immutable-row cleanup to this migrator container's MySQL identity."""

    settings = DatabaseSettings.from_url(database_url, pool_size=1, max_overflow=0)
    engine = sa.create_engine(
        settings.url,
        pool_pre_ping=True,
        pool_size=1,
        max_overflow=0,
    )
    try:
        with engine.begin() as connection:
            table_exists = int(
                connection.scalar(
                    sa.text(
                        """
                        SELECT COUNT(*)
                        FROM information_schema.tables
                        WHERE table_schema = DATABASE()
                          AND table_name = 'terminal_write_guard_bypass_accounts'
                        """
                    )
                )
                or 0
            )
            if table_exists == 0:
                return
            bypass_count = int(
                connection.scalar(
                    sa.text("SELECT COUNT(*) FROM terminal_write_guard_bypass_accounts")
                )
                or 0
            )
            if bypass_count != 1:
                raise DeploymentConfigurationError(
                    "migration write-guard bypass must contain exactly one account"
                )
            connection.execute(
                sa.text("DELETE FROM terminal_write_guard_bypass_accounts")
            )
            connection.execute(
                sa.text(
                    "INSERT INTO terminal_write_guard_bypass_accounts "
                    "(account_identity) VALUES (USER())"
                )
            )
    finally:
        engine.dispose()


def _migrate() -> None:
    _configure_process_environment(
        accounts=frozenset({"app", "backup", "migrator"}),
        include_test=True,
    )
    database = _database_name()
    root_engine = _root_engine(database)
    try:
        _synchronise_credentials(root_engine)
        _activate_migration_bypass(os.environ["APP_MIGRATION_DATABASE_URL"])
        _upgrade(os.environ["APP_MIGRATION_DATABASE_URL"])
        _synchronise_privileges(root_engine, database)
    finally:
        root_engine.dispose()


def _sync_test_grants() -> None:
    _configure_process_environment(
        accounts=frozenset({"app", "backup", "migrator"}),
        include_test=True,
    )
    database = _database_name(test_database=True)
    root_engine = _root_engine(database)
    try:
        _synchronise_privileges(root_engine, database)
    finally:
        root_engine.dispose()


def _reset_test_database(*, empty: bool = False) -> None:
    """Recreate only the name-gated disposable container test database."""

    _configure_process_environment(
        accounts=frozenset({"app", "backup", "migrator"}),
        include_test=True,
    )
    database = _database_name(test_database=True)
    if database != "clsen_data_test" and not database.startswith("clsen_data_test_"):
        raise DeploymentConfigurationError(
            "deployment test reset refuses a database outside clsen_data_test*"
        )
    root_engine = _root_engine(_database_name())
    try:
        quoted_database = _quoted_identifier(database)
        with root_engine.begin() as connection:
            connection.exec_driver_sql(f"DROP DATABASE IF EXISTS {quoted_database}")
            connection.exec_driver_sql(
                f"CREATE DATABASE {quoted_database} CHARACTER SET utf8mb4 "
                "COLLATE utf8mb4_0900_ai_ci"
            )
        if not empty:
            _upgrade(os.environ["APP_TEST_DATABASE_URL"])
            _synchronise_privileges(root_engine, database)
    finally:
        root_engine.dispose()


def _exec(arguments: list[str]) -> NoReturn:
    os.execvp(arguments[0], arguments)


def _restore_verify(arguments: list[str]) -> int:
    with tempfile.TemporaryDirectory(prefix="clsen-restore-option-") as temporary:
        option_file = Path(temporary) / "root.cnf"
        write_root_option_file(option_file, _read_secret("root"))
        completed = subprocess.run(
            [
                sys.executable,
                "-m",
                "app.maintenance.cli",
                "restore-verify",
                "--administrator-option-file",
                os.fspath(option_file),
                "--mysql",
                "mysql",
                *arguments,
            ],
            check=False,
        )
        return completed.returncode


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="clsen-container")
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("api")
    commands.add_parser("worker")
    commands.add_parser("migrate")
    commands.add_parser("sync-test-grants")
    reset = commands.add_parser("reset-test-database")
    reset.add_argument(
        "--empty",
        action="store_true",
        help="Leave the disposable schema empty for migration tests.",
    )
    pytest_parser = commands.add_parser("pytest")
    pytest_parser.add_argument("arguments", nargs=argparse.REMAINDER)
    administrator = commands.add_parser("admin")
    administrator.add_argument("arguments", nargs=argparse.REMAINDER)
    maintenance = commands.add_parser("maintenance")
    maintenance.add_argument("arguments", nargs=argparse.REMAINDER)
    restore = commands.add_parser("restore-verify")
    restore.add_argument("arguments", nargs=argparse.REMAINDER)
    return parser


def _entry_arguments(arguments: list[str] | None) -> tuple[str, list[str]]:
    values = list(sys.argv[1:] if arguments is None else arguments)
    if values and values[0] in {
        "pytest",
        "admin",
        "maintenance",
        "restore-verify",
    }:
        return values[0], values[1:]
    options = _parser().parse_args(values)
    if options.command == "reset-test-database" and options.empty:
        return str(options.command), ["--empty"]
    return str(options.command), []


def main(arguments: list[str] | None = None) -> int:
    """Dispatch one hardened container role without exposing secret values."""

    command, passthrough_arguments = _entry_arguments(arguments)
    if command == "migrate":
        _migrate()
        return 0
    if command == "sync-test-grants":
        _sync_test_grants()
        return 0
    if command == "reset-test-database":
        _reset_test_database(empty="--empty" in passthrough_arguments)
        return 0
    if command == "api" or command == "worker":
        accounts = frozenset({"app", "session"})
    elif command == "pytest":
        accounts = frozenset(
            {"app", "backup", "migrator", "schema_unreadable", "session"}
        )
    elif command == "admin":
        accounts = frozenset({"app"})
    elif command == "restore-verify":
        accounts = frozenset({"backup"})
    else:
        accounts = frozenset({"backup"})
    _configure_process_environment(
        accounts=accounts,
        include_test=command == "pytest",
    )
    if command in {"api", "worker"}:
        preflight_exit_code = schema_preflight_main(["--component", command])
        if preflight_exit_code != 0:
            return preflight_exit_code
    if command == "api":
        _exec(
            [
                "uvicorn",
                "app.main:app",
                "--host",
                "0.0.0.0",
                "--port",
                "8000",
                "--workers",
                os.getenv("APP_WEB_CONCURRENCY", "2"),
                "--proxy-headers",
                "--forwarded-allow-ips",
                os.getenv("APP_TRUSTED_PROXY", "nginx"),
            ]
        )
    if command == "worker":
        _exec([sys.executable, "-m", "app.worker.cli"])
    if command == "pytest":
        _activate_migration_bypass(os.environ["APP_TEST_DATABASE_URL"])
        _exec([sys.executable, "-m", "pytest", *passthrough_arguments])
    if command == "admin":
        completed = subprocess.run(
            [sys.executable, "-m", "app.cli", *passthrough_arguments],
            check=False,
        )
        return completed.returncode
    if command == "maintenance":
        completed = subprocess.run(
            [sys.executable, "-m", "app.maintenance.cli", *passthrough_arguments],
            check=False,
        )
        return completed.returncode
    if command == "restore-verify":
        return _restore_verify(passthrough_arguments)
    raise DeploymentConfigurationError("unsupported container command")


if __name__ == "__main__":
    raise SystemExit(main())
