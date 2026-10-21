import json
from pathlib import Path

REPOSITORY_ROOT = Path(__file__).resolve().parents[3]
SCRIPT = REPOSITORY_ROOT / "scripts" / "sync-test-runtime-grants.ps1"
CATALOG_RUNNER = REPOSITORY_ROOT / "scripts" / "run-product-catalog-mysql-tests.ps1"
MYSQL_MATRIX = REPOSITORY_ROOT / "scripts" / "test-mysql-matrix.ps1"
PRIVILEGES = REPOSITORY_ROOT / "scripts" / "database-privileges.json"
ROOT_CONFTEST = REPOSITORY_ROOT / "backend" / "tests" / "conftest.py"


def test_test_grant_sync_is_narrow_and_does_not_run_migrations() -> None:
    source = SCRIPT.read_text(encoding="utf-8")

    assert "#Requires -Version 7.0" in source
    assert "clsen_data_test(?:_[a-z0-9_]+)?" in source
    assert "database-privileges.json" in source
    assert "Get-Credential" in source
    assert "--defaults-extra-file" in source
    assert "SupportsShouldProcess" in source
    assert "GRANT SELECT" in source
    assert "GRANT INSERT" in source
    assert "GRANT UPDATE" in source
    assert "GRANT DELETE" in source
    lowered = source.casefold()
    assert "alembic_version" in lowered
    assert "-m alembic" not in lowered
    assert "alembic upgrade" not in lowered
    assert "alembic stamp" not in lowered
    assert "APP_MIGRATION_DATABASE_URL" not in source
    assert "DROP DATABASE" not in source.upper()


def test_test_grant_sync_protects_temporary_credentials() -> None:
    source = SCRIPT.read_text(encoding="utf-8")

    assert "Set-PrivatePathAcl" in source
    assert "FileSystemAclExtensions]::SetAccessControl" in source
    assert "Set-Acl" not in source
    assert "SecureStringToBSTR" in source
    assert "ZeroFreeBSTR" in source
    assert "clsen-test-grants-" in source
    assert "StartsWith" in source
    assert "Remove-Item" in source


def test_test_grant_sync_reconciles_only_target_object_privileges() -> None:
    source = SCRIPT.read_text(encoding="utf-8")

    assert "REVOKE" in source
    assert "information_schema.schema_privileges" in source
    assert "information_schema.table_privileges" in source
    assert "information_schema.column_privileges" in source
    assert "mysql.procs_priv" in source
    assert "information_schema.routine_privileges" not in source
    assert "FIND_IN_SET" in source
    assert "'EXECUTE' AS privilege_type" in source
    assert "'ALTER ROUTINE', 'Alter Routine'" in source
    assert "'GRANT OPTION', 'Grant'" in source
    assert "information_schema.user_privileges" in source
    assert "expectedPrivilegeSignatures" in source
    assert "actualPrivilegeSignatures" in source
    assert "untargetedPrivilegeSnapshot" in source
    assert "Assert-EquivalentStringSets" in source
    assert source.count("table_schema = '$DatabaseName'") >= 6
    assert source.count("table_schema <> '$DatabaseName'") >= 6
    assert "Global and non-target runtime privileges" in source
    assert "Target test-database runtime privileges" in source
    assert "Target test-database backup privileges" in source
    assert "expectedBackupPrivilegeSignatures" in source
    assert "actualBackupPrivilegeSignatures" in source
    assert "GRANT $backupSchemaPrivilegeList" in source
    assert source.index('Name "column-preflight"') < source.index(
        'Name "target-revokes"'
    )
    assert "REVOKE ALL PRIVILEGES, GRANT OPTION" not in source
    assert "DROP USER" not in source.upper()
    assert " ON *.* " not in source.upper()


def test_product_catalog_runner_owns_random_database_and_account_inputs() -> None:
    runner = CATALOG_RUNNER.read_text(encoding="utf-8")
    matrix = MYSQL_MATRIX.read_text(encoding="utf-8")

    assert "APP_TEST_RUN_ID" in runner
    assert "must not be supplied externally" in runner
    assert "test-mysql-matrix.ps1" in runner
    assert "-Suites" in runner
    assert "-PythonExecutable" in runner
    assert "-PytestPaths" not in runner
    assert (
        '$testDatabaseName = "clsen_data_test_$($runIdentifier.Substring(0, 16))"'
        in matrix
    )
    assert '[Environment]::SetEnvironmentVariable("APP_TEST_RUN_ID"' in matrix
    assert "clsen.mysql-matrix.run=$runIdentifier" in matrix
    assert "Get-MySqlSuitePaths" in matrix
    assert "At least one allowlisted MySQL suite is required" in matrix

    conftest = ROOT_CONFTEST.read_text(encoding="utf-8")
    for marker in (
        "APP_TEST_RUN_ID",
        "APP_TEST_RUNTIME_DATABASE_URL",
        "APP_TEST_BACKUP_DATABASE_URL",
        "APP_TEST_SCHEMA_UNREADABLE_DATABASE_URL",
        'url.host == "127.0.0.1"',
        'database_scope == "disposable-compose"',
        "compose_project == expected_compose_project",
        'url.host == "mysql"',
        "url.port == 3306",
        "clsen_data_test_{run_id[:16]}",
        "@@version_comment",
        "@@character_set_database",
        "migration, runtime, backup, and unreadable test accounts must be distinct",
    ):
        assert marker in conftest


def test_product_catalog_privileges_are_closed_and_pointer_updates_are_narrow() -> None:
    manifest = json.loads(PRIVILEGES.read_text(encoding="utf-8"))
    runtime = manifest["runtime"]
    insert_only = set(runtime["insert_only"])
    mutable_insert = set(runtime["mutable_insert"])

    assert {
        "product_catalog_versions",
        "product_catalog_mappings",
        "product_catalog_exclusions",
        "fact_snapshot_tuples",
        "return_dedup_snapshots",
        "catalog_command_effects",
        "catalog_audit_events",
    } <= insert_only
    assert {
        "product_styles",
        "product_skus",
        "product_catalog_publications",
        "return_dedup_publications",
        "catalog_imports",
        "catalog_jobs",
    } <= mutable_insert
    assert runtime["update_columns"]["product_catalog_publications"] == [
        "current_catalog_version_id",
        "catalog_publication_revision",
        "updated_at",
    ]
    assert runtime["update_columns"]["return_dedup_publications"] == [
        "current_snapshot_id",
        "dedup_publication_revision",
        "updated_at",
    ]
    assert not (insert_only & mutable_insert)


def test_worker_observability_privileges_are_minimal_and_bounded() -> None:
    manifest = json.loads(PRIVILEGES.read_text(encoding="utf-8"))
    runtime = manifest["runtime"]

    assert {"worker_instances", "worker_consumer_states"} <= set(
        runtime["mutable_insert"]
    )
    assert {"worker_instances", "worker_consumer_states"} <= set(runtime["update"])
    assert "worker_instances" in runtime["delete"]
    assert "worker_consumer_states" not in runtime["delete"]
