from __future__ import annotations

import ast
import json
import re
from collections import Counter
from pathlib import Path
from typing import TypedDict, cast

REPOSITORY_ROOT = Path(__file__).resolve().parents[3]
BOOTSTRAP_SCRIPT = REPOSITORY_ROOT / "scripts" / "init-database.ps1"
SESSION_SECRET_SCRIPT = REPOSITORY_ROOT / "scripts" / "ensure-local-session-secret.ps1"
AUTHENTICATION_GUIDE = REPOSITORY_ROOT / "docs" / "operations" / "authentication.md"
MYSQL_MATRIX_SCRIPT = REPOSITORY_ROOT / "scripts" / "test-mysql-matrix.ps1"
PRIVILEGE_MANIFEST = REPOSITORY_ROOT / "scripts" / "database-privileges.json"
COMPATIBILITY_WORKFLOW = REPOSITORY_ROOT / ".github" / "workflows" / "compatibility.yml"
CI_SUITE_MANIFEST = REPOSITORY_ROOT / "scripts" / "ci-suite-manifest.json"
CI_PROFILE_RUNNER = REPOSITORY_ROOT / "scripts" / "run-ci-profile.ps1"
DATABASE_CONTRACT = REPOSITORY_ROOT / "scripts" / "DatabaseContract.psm1"
MIGRATION_DIRECTORY = REPOSITORY_ROOT / "backend" / "alembic" / "versions"
IDENTIFIER_PATTERN = re.compile(r"[a-z][a-z0-9_]{0,63}\Z")
MIGRATOR_ONLY_TABLES = {
    "terminal_write_guard_bypass_accounts",
    "report_source_scope_corrections",  # Offline correction uses the migrator.
}
FORWARD_REPAIR_TABLES = {
    "note_threads",
    "publication_command_results",
    "review_operation_results",
    "review_operation_tokens",
    "version_review_events",
}


class RuntimePrivileges(TypedDict):
    insert_only: list[str]
    mutable_insert: list[str]
    update: list[str]
    update_columns: dict[str, list[str]]
    delete: list[str]


class BackupPrivileges(TypedDict):
    schema: list[str]
    insert: list[str]
    update: list[str]


class DatabasePrivilegeManifest(TypedDict):
    version: int
    runtime: RuntimePrivileges
    backup: BackupPrivileges


def _load_and_validate_privilege_manifest() -> DatabasePrivilegeManifest:
    raw_value: object = json.loads(PRIVILEGE_MANIFEST.read_text(encoding="utf-8"))
    assert isinstance(raw_value, dict)
    assert all(isinstance(key, str) for key in raw_value)
    manifest = cast(dict[str, object], raw_value)
    assert set(manifest) == {"version", "runtime", "backup"}
    assert type(manifest["version"]) is int
    assert manifest["version"] == 5

    runtime_value = manifest["runtime"]
    assert isinstance(runtime_value, dict)
    assert all(isinstance(key, str) for key in runtime_value)
    runtime = cast(dict[str, object], runtime_value)
    table_categories = {"insert_only", "mutable_insert", "update", "delete"}
    categories = table_categories | {"update_columns"}
    assert set(runtime) == categories
    for category in table_categories:
        tables = runtime[category]
        assert isinstance(tables, list)
        assert tables
        assert all(
            type(table) is str and IDENTIFIER_PATTERN.fullmatch(table) is not None
            for table in tables
        )
        assert len(tables) == len(set(tables))

    update_columns_value = runtime["update_columns"]
    assert isinstance(update_columns_value, dict)
    assert update_columns_value
    assert all(isinstance(key, str) for key in update_columns_value)
    update_columns = cast(dict[str, object], update_columns_value)
    for table, columns in update_columns.items():
        assert IDENTIFIER_PATTERN.fullmatch(table) is not None
        assert isinstance(columns, list)
        assert columns
        assert all(
            type(column) is str and IDENTIFIER_PATTERN.fullmatch(column) is not None
            for column in columns
        )
        assert len(columns) == len(set(columns))

    typed_runtime = cast(RuntimePrivileges, runtime)
    insert_only = set(typed_runtime["insert_only"])
    mutable_insert = set(typed_runtime["mutable_insert"])
    assert insert_only.isdisjoint(mutable_insert)
    assert set(typed_runtime["update"]) <= mutable_insert
    assert set(typed_runtime["delete"]) <= mutable_insert
    assert set(typed_runtime["update_columns"]) <= mutable_insert
    assert set(typed_runtime["update_columns"]).isdisjoint(typed_runtime["update"])

    backup_value = manifest["backup"]
    assert isinstance(backup_value, dict)
    assert set(backup_value) == {"schema", "insert", "update"}
    backup = cast(dict[str, object], backup_value)
    assert backup["schema"] == ["SELECT", "SHOW VIEW", "TRIGGER", "EVENT"]
    for category in ("insert", "update"):
        tables = backup[category]
        assert isinstance(tables, list)
        assert tables
        assert all(
            type(table) is str and IDENTIFIER_PATTERN.fullmatch(table) is not None
            for table in tables
        )
        assert len(tables) == len(set(tables))
    typed_backup = cast(BackupPrivileges, backup)
    assert set(typed_backup["update"]) <= set(typed_backup["insert"])
    return cast(DatabasePrivilegeManifest, manifest)


def _migration_created_table_names() -> set[str]:
    table_names: list[str] = []
    migration_files = sorted(MIGRATION_DIRECTORY.glob("*.py"))
    assert migration_files
    for migration_file in migration_files:
        module = ast.parse(
            migration_file.read_text(encoding="utf-8"),
            filename=str(migration_file),
        )
        for node in ast.walk(module):
            if not (
                isinstance(node, ast.Call)
                and isinstance(node.func, ast.Attribute)
                and node.func.attr == "create_table"
                and isinstance(node.func.value, ast.Name)
                and node.func.value.id == "op"
            ):
                continue
            assert node.args
            table_name = node.args[0]
            assert isinstance(table_name, ast.Constant)
            assert isinstance(table_name.value, str)
            table_names.append(table_name.value)
    counts = Counter(table_names)
    assert {
        table_name: count for table_name, count in counts.items() if count != 1
    } == {table_name: 2 for table_name in FORWARD_REPAIR_TABLES}
    return set(counts)


def test_database_privilege_manifest_is_strict_and_protects_event_history() -> None:
    manifest = _load_and_validate_privilege_manifest()
    protected_tables = {
        "parse_operation_tokens",
        "report_date_operation_tokens",
        "issue_review_events",
        "data_change_events",
        "field_changes",
        "row_changes",
        "note_threads",
        "notes",
        "audit_events",
        "publication_events",
        "draft_operation_tokens",
        "draft_operation_results",
        "draft_disposition_events",
        "validation_runs",
        "validation_issues",
        "publication_commands",
        "publication_command_results",
        "review_operation_tokens",
        "review_operation_results",
        "admin_operation_tokens",
        "admin_operation_results",
        "version_review_events",
        "version_table_columns",
        "extension_cell_changes",
        "workbench_operation_tokens",
        "workbench_operation_results",
    }

    runtime = manifest["runtime"]
    assert protected_tables <= set(runtime["insert_only"])
    assert protected_tables.isdisjoint(runtime["update"])
    assert protected_tables.isdisjoint(runtime["update_columns"])
    assert protected_tables.isdisjoint(runtime["delete"])


def test_runtime_can_reconcile_raw_file_integrity_without_deleting_history() -> None:
    runtime = _load_and_validate_privilege_manifest()["runtime"]

    assert "raw_file_integrity_statuses" in runtime["mutable_insert"]
    assert "raw_file_integrity_statuses" in runtime["update"]
    assert "raw_file_integrity_statuses" not in runtime["delete"]


def test_runtime_can_insert_and_lock_dataset_lock_rows_without_deleting_them() -> None:
    runtime = _load_and_validate_privilege_manifest()["runtime"]

    assert "daily_dataset_locks" in runtime["mutable_insert"]
    assert "daily_dataset_locks" not in runtime["update"]
    assert runtime["update_columns"] == {
        "daily_dataset_locks": ["lock_revision"],
        "report_publication_revisions": [
            "publication_revision",
            "updated_at",
        ],
        "return_dedup_publications": [
            "current_snapshot_id",
            "dedup_publication_revision",
            "updated_at",
        ],
        "publication_snapshots": ["status"],
        "catalog_parse_attempts": [
            "status",
            "workflow_revision",
            "lease_expires_at",
            "completed_at",
            "recoverable",
            "failure_reason_code",
            "result_digest",
        ],
        "catalog_command_claims": ["status"],
        "product_catalog_publications": [
            "current_catalog_version_id",
            "catalog_publication_revision",
            "updated_at",
        ],
    }
    assert "daily_dataset_locks" not in runtime["insert_only"]
    assert "daily_dataset_locks" not in runtime["delete"]


def test_runtime_can_update_extension_snapshots_without_rewriting_history() -> None:
    runtime = _load_and_validate_privilege_manifest()["runtime"]

    assert "version_extension_cells" in runtime["mutable_insert"]
    assert "version_extension_cells" in runtime["update"]
    assert "version_extension_cells" not in runtime["delete"]
    for table in (
        "version_table_columns",
        "extension_cell_changes",
        "workbench_operation_tokens",
        "workbench_operation_results",
    ):
        assert table in runtime["insert_only"]
        assert table not in runtime["update"]
        assert table not in runtime["delete"]


def test_runtime_can_update_batch_review_orchestration_without_deleting_it() -> None:
    runtime = _load_and_validate_privilege_manifest()["runtime"]

    for table in (
        "batch_review_runs",
        "batch_review_items",
        "batch_review_commands",
    ):
        assert table in runtime["mutable_insert"]
        assert table in runtime["update"]
        assert table not in runtime["delete"]


def test_every_migration_table_has_exactly_one_insert_classification() -> None:
    manifest = _load_and_validate_privilege_manifest()
    runtime = manifest["runtime"]
    backup = manifest["backup"]
    insert_only = set(runtime["insert_only"])
    mutable_insert = set(runtime["mutable_insert"])
    read_only_seed_tables = {"roles", "sites"}

    assert insert_only.isdisjoint(mutable_insert)
    assert insert_only.isdisjoint(read_only_seed_tables)
    assert mutable_insert.isdisjoint(read_only_seed_tables)
    classified_tables = (
        insert_only
        | mutable_insert
        | read_only_seed_tables
        | MIGRATOR_ONLY_TABLES
        | set(backup["insert"])
    )
    created_tables = _migration_created_table_names()
    assert created_tables == classified_tables
    assert len(created_tables) == 115


def test_all_database_privilege_consumers_load_and_validate_the_manifest() -> None:
    bootstrap_source = BOOTSTRAP_SCRIPT.read_text(encoding="utf-8")
    matrix_source = MYSQL_MATRIX_SCRIPT.read_text(encoding="utf-8")
    workflow_source = COMPATIBILITY_WORKFLOW.read_text(encoding="utf-8")
    contract_source = DATABASE_CONTRACT.read_text(encoding="utf-8")

    for source in (bootstrap_source, matrix_source):
        assert "database-privileges.json" in source
        assert "DatabaseContract.psm1" in source
        assert "Import-StrictDatabasePrivilegeManifest" in source

    for category in (
        "insert_only",
        "mutable_insert",
        "update",
        "update_columns",
        "delete",
        "backup",
    ):
        assert category in contract_source
    assert "ConvertFrom-Json -AsHashtable" in contract_source
    assert "System.Text.Json.JsonDocument" in contract_source
    assert "Assert-NoDuplicateJsonObjectKeys" in contract_source
    assert "Duplicate JSON object key" in contract_source
    assert "[a-z][a-z0-9_]{0,63}" in contract_source
    assert "mutually exclusive" in contract_source
    assert "subset" in contract_source

    for powershell_source in (bootstrap_source, matrix_source):
        assert "GRANT UPDATE ($columnList)" in powershell_source or (
            "GRANT UPDATE ($($columnIdentifiers -join ', '))" in powershell_source
        )
    assert "database-privileges.json" not in workflow_source
    assert "scripts/run-ci-profile.ps1" in workflow_source
    assert "test-mysql-matrix.ps1" in CI_PROFILE_RUNNER.read_text(encoding="utf-8")


def test_mysql_suites_apply_grants_only_after_migration_tests() -> None:
    matrix_source = MYSQL_MATRIX_SCRIPT.read_text(encoding="utf-8")
    manifest = json.loads(CI_SUITE_MANIFEST.read_text(encoding="utf-8"))
    assert manifest["profiles"]["mysql-compatibility"]["suites"] == [
        "mysql-migrations",
        "mysql-legacy",
        "mysql-p0",
        "mysql-schema-startup",
        "mysql-worker-observability",
    ]
    pytest_invocation = (
        "& $pythonExecutable -u -m pytest @testTargets "
        "--require-mysql -x -vv --durations=20 "
        "@formalSelectionArguments"
    )
    assert "[string[]]$testTargets = if ($diagnosticMode)" in matrix_source
    assert "else { @($remainingPaths) }" in matrix_source
    assert "$quickDiagnosticNode =" in matrix_source
    assert (
        '$formalSelectionArguments += @("--deselect", $quickDiagnosticNode)'
        in matrix_source
    )
    assert "@formalSelectionArguments" in matrix_source
    assert "mysql-historical-nodeids.txt" in matrix_source
    assert "mysql-historical-nodeids.txt" in CI_PROFILE_RUNNER.read_text(
        encoding="utf-8"
    )
    assert "@selectedHistoricalNodes --require-mysql -x" in matrix_source
    assert "--deselect=$_" in matrix_source
    assert (
        matrix_source.index("@selectedHistoricalNodes --require-mysql -x")
        < matrix_source.index(
            "& $pythonExecutable -m alembic -c alembic.ini upgrade head"
        )
        < matrix_source.index('Operation "apply least-privilege runtime grants"')
        < matrix_source.index(pytest_invocation)
    )

    workflow_source = COMPATIBILITY_WORKFLOW.read_text(encoding="utf-8")
    assert "-Profile mysql-compatibility" in workflow_source
    assert "tests/integration/test_migrations.py" not in workflow_source


def test_stage_five_and_six_mysql84_suites_run_serially_after_runtime_grants() -> None:
    expected_files = (
        "tests/integration/test_stage_five_schema.py",
        "tests/integration/test_stage_six_schema.py",
        "tests/integration/test_draft_transactions.py",
        "tests/integration/test_draft_date_reassignment.py",
    )

    manifest = json.loads(CI_SUITE_MANIFEST.read_text(encoding="utf-8"))
    legacy = manifest["mysql_suites"]["mysql-legacy"]
    positions = tuple(
        legacy.index(f"backend/{test_file}") for test_file in expected_files
    )
    assert positions == tuple(sorted(positions))
    matrix_source = MYSQL_MATRIX_SCRIPT.read_text(encoding="utf-8")
    matrix_grant = matrix_source.index(
        'Operation "apply least-privilege runtime grants"'
    )
    pytest_invocation = "& $pythonExecutable -u -m pytest @testTargets --require-mysql"
    assert "[string[]]$testTargets = if ($diagnosticMode)" in matrix_source
    assert "else { @($remainingPaths) }" in matrix_source
    matrix_invocation = matrix_source.index(pytest_invocation, matrix_grant)
    assert matrix_invocation > matrix_grant
    assert "Start-Job" not in matrix_source
    assert "ForEach-Object -Parallel" not in matrix_source
    assert "APP_TEST_RUNTIME_DATABASE_URL" in matrix_source
    assert "test-runtime-matrix.ps1" not in matrix_source

    workflow_source = COMPATIBILITY_WORKFLOW.read_text(encoding="utf-8")
    assert all(test_file not in workflow_source for test_file in expected_files)
    assert workflow_source.count("-Profile mysql-compatibility") == 1
    assert "test-runtime-matrix.ps1" not in workflow_source


def test_stage_seven_through_nine_mysql_suites_run_in_mysql84_ci() -> None:
    expected_files = (
        "tests/integration/test_admin_management_api.py",
        "tests/integration/test_admin_operation_permissions.py",
        "tests/integration/test_authentication_api.py",
        "tests/integration/test_data_calendar_api.py",
        "tests/integration/test_review_workspace_api.py",
        "tests/integration/test_review_workflow.py",
        "tests/integration/test_publication_transactions.py",
        "tests/integration/test_publication_concurrency.py",
        "tests/integration/test_published_analytics.py",
    )
    manifest = json.loads(CI_SUITE_MANIFEST.read_text(encoding="utf-8"))
    legacy = manifest["mysql_suites"]["mysql-legacy"]
    for test_file in expected_files:
        assert legacy.count(f"backend/{test_file}") == 1
    workflow_source = COMPATIBILITY_WORKFLOW.read_text(encoding="utf-8")
    assert all(test_file not in workflow_source for test_file in expected_files)
    assert workflow_source.count("-Profile mysql-compatibility") == 1


def test_p0_catalog_and_product_suites_run_serially_in_mysql84_ci() -> None:
    expected_files = (
        "tests/integration/test_catalog_approval.py",
        "tests/integration/test_catalog_command_recovery.py",
        "tests/integration/test_catalog_concurrency.py",
        "tests/integration/test_catalog_evidence_reveal.py",
        "tests/integration/test_catalog_export_finalization.py",
        "tests/integration/test_catalog_grants.py",
        "tests/integration/test_catalog_identity_reservations.py",
        "tests/integration/test_catalog_import_workflow.py",
        "tests/integration/test_catalog_projection_expiry.py",
        "tests/integration/test_catalog_repository.py",
        "tests/integration/test_catalog_schema.py",
        "tests/integration/test_catalog_scope.py",
        "tests/integration/test_catalog_security.py",
        "tests/integration/test_catalog_snapshot_consistency.py",
        "tests/integration/test_catalog_source_keys.py",
        "tests/integration/test_catalog_worker.py",
        "tests/integration/test_return_dedup.py",
        "tests/integration/test_style_analytics.py",
        "tests/integration/test_style_analytics_api.py",
        "tests/integration/test_style_analytics_consistency.py",
        "tests/integration/test_style_analytics_reconciliation.py",
        "tests/integration/test_legacy_product_analytics_compatibility.py",
        "tests/integration/test_product_analytics_cutover.py",
        "tests/integration/test_product_analytics_reconciliation.py",
        "tests/integration/test_product_catalog_permissions.py",
    )
    manifest = json.loads(CI_SUITE_MANIFEST.read_text(encoding="utf-8"))
    p0 = manifest["mysql_suites"]["mysql-p0"]
    for test_file in expected_files:
        assert p0.count(f"backend/{test_file}") == 1
    workflow_source = COMPATIBILITY_WORKFLOW.read_text(encoding="utf-8")
    assert all(test_file not in workflow_source for test_file in expected_files)
    assert workflow_source.count("-Profile mysql-compatibility") == 1


def test_bootstrap_fails_closed_when_dataset_lock_coverage_is_incomplete() -> None:
    source = BOOTSTRAP_SCRIPT.read_text(encoding="utf-8")

    migration = source.index("-m alembic -c $alembicConfiguration upgrade head")
    coverage_query = source.index(
        "LEFT JOIN ``$($migrationTarget.Database)``.``daily_dataset_locks``",
        migration,
    )
    reverse_query = source.index(
        "LEFT JOIN ``$($migrationTarget.Database)``.``daily_datasets``",
        coverage_query,
    )
    fail_closed = source.index(
        '"Dataset lock coverage verification failed for database "',
        reverse_query,
    )
    runtime_grants = source.index('-Name "runtime-grants"', fail_closed)
    environment_write = source.index(
        "[System.IO.File]::WriteAllText(\n        $environmentFile",
        runtime_grants,
    )

    assert migration < coverage_query < reverse_query < fail_closed
    assert fail_closed < runtime_grants < environment_write
    assert "$datasetCount -ne $lockCount" in source
    assert "$missingLockCount -ne 0" in source
    assert "$orphanLockCount -ne 0" in source


def test_database_bootstrap_keeps_secrets_out_of_process_arguments() -> None:
    source = BOOTSTRAP_SCRIPT.read_text(encoding="utf-8")
    executable_source = "\n".join(
        line for line in source.splitlines() if not line.lstrip().startswith("#")
    )

    assert re.search(
        r"(?m)^\s*\$adminCredential\s*=\s*Get-Credential\b",
        executable_source,
    )
    assert (
        "[Security.Cryptography.RandomNumberGenerator]::Fill($bytes)"
        in executable_source
    )
    assert "--defaults-extra-file=$optionFile" in executable_source
    assert not re.search(
        r"(?:--password|-p)\s*[=$]",
        executable_source,
        flags=re.IGNORECASE,
    )


def test_database_bootstrap_generates_a_persistent_random_session_secret() -> None:
    source = BOOTSTRAP_SCRIPT.read_text(encoding="utf-8")

    generation = source.index("$sessionSecret = New-RandomSecret")
    environment_entry = source.index("APP_SESSION_SECRET=$sessionSecret", generation)
    environment_write = source.index(
        "[System.IO.File]::WriteAllText(\n        $environmentFile",
        environment_entry,
    )
    cleanup = source.index("$sessionSecret = $null", environment_write)

    assert generation < environment_entry < environment_write < cleanup
    assert "function New-RandomSecret" in source
    assert "$sessionSecret -ceq $migrationPassword" in source


def test_local_session_secret_upgrade_is_idempotent_private_and_atomic() -> None:
    source = SESSION_SECRET_SCRIPT.read_text(encoding="utf-8")
    executable_source = "\n".join(
        line for line in source.splitlines() if not line.lstrip().startswith("#")
    )

    assert "#Requires -Version 7.0" in source
    assert "[switch]$Rotate" in source
    assert "RandomNumberGenerator]::Fill($secretBytes)" in source
    assert "Duplicate APP_SESSION_SECRET entries" in source
    assert "must not be a reparse point" in source
    assert "Set-PrivatePathAcl -LiteralPath $temporaryFile" in source
    assert "[IO.File]::Move($temporaryFile, $environmentFile, $true)" in source
    assert "Test-PrivatePathAcl -LiteralPath $environmentFile" in source
    assert "$PSCmdlet.ShouldProcess($environmentFile" in source
    assert (
        "Unused pre-authentication CSRF tokens issued with the previous secret "
        "become invalid "
    ) in source
    assert "when the application loads this value." in source
    assert "Existing database-backed login sessions remain valid" in source
    assert "revoke them separately only when authorized" in source
    assert "Existing login sessions are now invalid" not in source
    assert not re.search(r"Write-(?:Host|Output).*\$sessionSecret", executable_source)


def test_session_secret_rotation_scope_does_not_claim_session_revocation() -> None:
    guide = AUTHENTICATION_GUIDE.read_text(encoding="utf-8")

    assert "正在运行的应用进程需重启" in guide
    assert "轮换前签发且尚未使用的登录前 CSRF 令牌失效" in guide
    assert "不会自动撤销数据库中已有的登录会话" in guide
    assert "必须另行按授权执行服务端会话撤销流程" in guide
    assert "轮换会使现有登录会话失效" not in guide


def test_database_bootstrap_creates_fail_closed_dedicated_accounts() -> None:
    source = BOOTSTRAP_SCRIPT.read_text(encoding="utf-8")

    for expected_value in (
        "clsen_data",
        "clsen_data_test",
        "clsen_migrator",
        "clsen_app",
        "clsen_backup",
        "caching_sha2_password",
        "APP_BACKUP_DATABASE_URL=$backupUrl",
    ):
        assert expected_value in source

    for account in ("migrationUser", "runtimeUser", "backupUser"):
        assert (
            "REVOKE IF EXISTS ALL PRIVILEGES, GRANT OPTION "
            f"FROM '${account}'@'$accountHost';"
        ) in source
        assert f"SET DEFAULT ROLE NONE TO '${account}'@'$accountHost';" in source

    assert "FROM mysql.role_edges" in source
    assert "$existingRoleAssignments -ne 0" in source
    assert "cannot guarantee least privilege while roles remain" in source
    assert "FROM mysql.proxies_priv" in source
    assert "$existingProxyGrants -ne 0" in source
    assert (
        "GRANT SELECT, INSERT, UPDATE, DELETE, CREATE, ALTER, DROP, "
        "INDEX, REFERENCES, TRIGGER"
    ) in source
    assert "$backupSchemaPrivilegeList = (" in source
    assert "GRANT $backupSchemaPrivilegeList" in source
    assert '$backupPrivileges = $databasePrivileges["backup"]' in source
    assert (
        "\"GRANT INSERT ON ``$database``.``$table`` TO '$backupUser'@'$accountHost';\""
    ) in source
    assert (
        "\"GRANT UPDATE ON ``$database``.``$table`` TO '$backupUser'@'$accountHost';\""
    ) in source


def test_trigger_creation_precondition_is_configured_without_super_grants() -> None:
    bootstrap_source = BOOTSTRAP_SCRIPT.read_text(encoding="utf-8")
    matrix_source = MYSQL_MATRIX_SCRIPT.read_text(encoding="utf-8")
    workflow_source = COMPATIBILITY_WORKFLOW.read_text(encoding="utf-8")

    assert "SET PERSIST log_bin_trust_function_creators = ON" in bootstrap_source
    assert "@@GLOBAL.log_bin_trust_function_creators" in bootstrap_source
    assert "SET GLOBAL log_bin_trust_function_creators = ON" in matrix_source
    assert "-Profile mysql-compatibility" in workflow_source

    for source in (bootstrap_source, matrix_source):
        executable_source = "\n".join(
            line for line in source.splitlines() if not line.lstrip().startswith("#")
        )
        assert not re.search(r"\bGRANT\s+SUPER\b", executable_source, re.IGNORECASE)


def test_database_bootstrap_writes_explicit_storage_configuration() -> None:
    source = BOOTSTRAP_SCRIPT.read_text(encoding="utf-8")

    assert 'Join-Path -Path $repositoryRoot -ChildPath "data\\raw"' in source
    for variable_name in (
        "APP_STORAGE_ROOT",
        "APP_STORAGE_MAX_UPLOAD_BYTES",
        "APP_STORAGE_LEASE_TTL_SECONDS",
        "APP_STORAGE_LEASE_RENEW_INTERVAL_SECONDS",
        "APP_STORAGE_ORPHAN_AGE_SECONDS",
    ):
        assert f"{variable_name}=" in source


def test_database_bootstrap_creates_private_storage_root_before_config() -> None:
    source = BOOTSTRAP_SCRIPT.read_text(encoding="utf-8")

    create_root = source.index("[IO.Directory]::CreateDirectory($storageRoot)")
    protect_root = source.index(
        "Set-PrivatePathAcl -LiteralPath $storageRoot -Directory"
    )
    write_environment = source.index("$environmentContent,", protect_root)

    assert create_root < protect_root < write_environment
    assert "$acl.SetAccessRuleProtection($true, $false)" in source
    assert "FileSystemAclExtensions]::SetAccessControl" in source
    assert "Set-Acl" not in source
    assert "Storage root must not be a reparse point." in source
