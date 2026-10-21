from __future__ import annotations

import ast
import os
import re
import subprocess
import sys
from pathlib import Path

BACKEND_ROOT = Path(__file__).resolve().parents[2]
VERSIONS_DIRECTORY = BACKEND_ROOT / "alembic" / "versions"
ADMIN_MANAGEMENT_MODULE = BACKEND_ROOT / "app" / "api" / "admin_management.py"
EXPECTED_MIGRATIONS = (
    ("0001", None, "0001_users_roles_sites.py"),
    ("0002", "0001", "0002_files_imports_parse_attempts.py"),
    ("0003", "0002", "0003_datasets_versions_baselines.py"),
    ("0004", "0003", "0004_validation_changes_audit.py"),
    ("0005", "0004", "0005_publication_outbox.py"),
    ("0006", "0005", "0006_raw_file_integrity_status.py"),
    ("0007", "0006", "0007_report_parsing_contracts.py"),
    ("0008", "0007", "0008_draft_versioning_contracts.py"),
    ("0009", "0008", "0009_review_publication_contracts.py"),
    ("0010", "0009", "0010_authentication_sessions.py"),
    ("0011", "0010", "0011_admin_operation_contracts.py"),
    ("0012", "0011", "0012_admin_operation_secret_tags.py"),
    ("0013", "0012", "0013_scrub_public_admin_operation_tags.py"),
    ("0014", "0013", "0014_remove_admin_operation_secret_verifiers.py"),
    ("0015", "0014", "0015_enforce_admin_operation_secret_marker.py"),
    ("0016", "0015", "0016_dataset_publication_downgrade_compat.py"),
    ("0017", "0016", "0017_restore_review_note_contracts.py"),
    ("0018", "0017", "0018_backup_recovery_records.py"),
    ("0019", "0018", "0019_maintenance_write_barrier.py"),
    ("0020", "0019", "0020_editable_workbench_tables.py"),
    ("0021", "0020", "0021_batch_review_workflow.py"),
    ("0022", "0021", "0022_product_catalog_foundation.py"),
    ("0023", "0022", "0023_worker_observability.py"),
    ("0024", "0023", "0024_catalog_export_job_recovery.py"),
    ("0025", "0024", "0025_catalog_categories_and_style_changes.py"),
    ("0026", "0025", "0026_catalog_draft_identity_reservations.py"),
    ("0027", "0026", "0027_catalog_draft_exclusion_reservations.py"),
    ("0028", "0027", "0028_category_hierarchy.py"),
    ("0029", "0028", "0029_source_scope_correction.py"),
    ("0030", "0029", "0030_return_initialization.py"),
)


def _assignment(module: ast.Module, name: str) -> str | None:
    for statement in module.body:
        value_node: ast.expr | None = None
        if (
            isinstance(statement, ast.Assign)
            and any(
                isinstance(target, ast.Name) and target.id == name
                for target in statement.targets
            )
        ) or (
            isinstance(statement, ast.AnnAssign)
            and isinstance(statement.target, ast.Name)
            and statement.target.id == name
        ):
            value_node = statement.value

        if value_node is not None:
            value = ast.literal_eval(value_node)
            if value is None or isinstance(value, str):
                return value
    raise AssertionError(f"Migration does not define a literal {name!r}")


def _create_table_position(source: str, table_name: str) -> int:
    match = re.search(
        rf"op\.create_table\(\s*[\"']{re.escape(table_name)}[\"']",
        source,
    )
    assert match is not None, f"Migration does not create {table_name}"
    return match.start()


def test_migrations_form_one_reviewable_linear_history() -> None:
    assert VERSIONS_DIRECTORY.is_dir()
    assert sorted(path.name for path in VERSIONS_DIRECTORY.glob("*.py")) == [
        migration[2] for migration in EXPECTED_MIGRATIONS
    ]

    for revision, down_revision, filename in EXPECTED_MIGRATIONS:
        module = ast.parse((VERSIONS_DIRECTORY / filename).read_text(encoding="utf-8"))
        assert _assignment(module, "revision") == revision
        assert _assignment(module, "down_revision") == down_revision


def test_import_batch_parse_attempt_cycle_is_created_in_safe_order() -> None:
    source = (VERSIONS_DIRECTORY / EXPECTED_MIGRATIONS[1][2]).read_text(
        encoding="utf-8"
    )

    batches = _create_table_position(source, "import_batches")
    attempts = _create_table_position(source, "parse_attempts")
    back_pointer = source.index("fk_import_batches_current_parse_attempt")

    assert batches < attempts < back_pointer


def test_migrations_never_seed_a_default_application_user_or_password() -> None:
    source = "\n".join(
        path.read_text(encoding="utf-8")
        for path in sorted(VERSIONS_DIRECTORY.glob("*.py"))
    ).lower()

    assert "insert into users" not in source
    assert "bulk_insert(users" not in source
    assert "default_password" not in source


def test_worker_observability_migration_is_additive_and_bounded() -> None:
    source = (VERSIONS_DIRECTORY / "0023_worker_observability.py").read_text(
        encoding="utf-8"
    )

    instances = _create_table_position(source, "worker_instances")
    consumers = _create_table_position(source, "worker_consumer_states")
    assert instances < consumers
    assert 'revision = "0023"' in source
    assert 'down_revision = "0022"' in source
    assert 'ondelete="CASCADE"' in source
    assert "ck_worker_instances_role" in source
    assert "ck_worker_instances_lifecycle" in source
    assert "ck_worker_instances_supported_queues" in source
    assert "ck_worker_consumer_states_queue" in source
    assert "ix_worker_instances_lifecycle_heartbeat" in source
    assert "ix_worker_instances_retention" in source
    assert "INSERT INTO" not in source.upper()
    assert "UPDATE " not in source.upper()
    assert "DELETE FROM" not in source.upper()
    downgrade = source[source.index("def downgrade()") :]
    assert downgrade.index('op.drop_table("worker_consumer_states")') < (
        downgrade.index('op.drop_table("worker_instances")')
    )


def test_catalog_export_job_recovery_migration_is_additive_and_backfills_jobs() -> None:
    source = (VERSIONS_DIRECTORY / "0024_catalog_export_job_recovery.py").read_text(
        encoding="utf-8"
    )

    assert 'revision = "0024"' in source
    assert 'down_revision = "0023"' in source
    assert "attempt_count" in source
    assert "next_attempt_at" in source
    assert "execution_phase" in source
    assert "INSERT IGNORE INTO catalog_jobs" in source
    assert "FROM catalog_exports" in source
    assert "ck_catalog_jobs_execution_phase" in source
    assert "ck_catalog_jobs_attempt_schedule" in source


def test_backup_recovery_migration_preserves_auditable_evidence() -> None:
    source = (VERSIONS_DIRECTORY / EXPECTED_MIGRATIONS[17][2]).read_text(
        encoding="utf-8"
    )

    snapshots = _create_table_position(source, "backup_snapshots")
    objects = _create_table_position(source, "backup_snapshot_objects")
    verifications = _create_table_position(source, "restore_verifications")
    first_trigger = source.index(
        "trg_backup_snapshot_objects_immutable_update",
        verifications,
    )

    assert snapshots < objects < verifications < first_trigger
    assert "AES" not in source
    assert "target_storage_root_sha256" in source
    assert "0018 downgrade refused" in source
    assert "backup snapshot objects are immutable" in source
    assert 'sa.Column("sealed_at"' in source
    assert "status IN ('running', 'sealed', 'succeeded', 'failed')" in source


def test_maintenance_write_barrier_migration_creates_a_constrained_singleton() -> None:
    source = (VERSIONS_DIRECTORY / EXPECTED_MIGRATIONS[18][2]).read_text(
        encoding="utf-8"
    )

    _create_table_position(source, "maintenance_write_barrier")
    assert "autoincrement=False" in source
    assert '"id = 1 AND sentinel = 1"' in source
    assert 'op.bulk_insert(barrier, [{"id": 1, "sentinel": 1}])' in source
    assert "0019 downgrade refused" in source


def test_editable_workbench_migration_versions_original_columns_and_changes() -> None:
    source = (VERSIONS_DIRECTORY / EXPECTED_MIGRATIONS[19][2]).read_text(
        encoding="utf-8"
    )

    columns = _create_table_position(source, "version_table_columns")
    cells = _create_table_position(source, "version_extension_cells")
    changes = _create_table_position(source, "extension_cell_changes")
    tokens = _create_table_position(source, "workbench_operation_tokens")
    results = _create_table_position(source, "workbench_operation_results")

    assert columns < cells < changes < tokens < results
    assert "candidate_report_date" in source
    assert "uq_version_table_columns_order" in source
    assert "uq_version_extension_cells_identity" in source
    assert "undoes_change_id" in source
    assert "expected_cell_revision" in source
    assert "trg_version_extension_cells_editable_update" in source
    assert "extension cell changes are immutable" in source
    assert "0020 downgrade refused" in source


def test_batch_review_migration_persists_only_orchestration_state() -> None:
    source = (VERSIONS_DIRECTORY / EXPECTED_MIGRATIONS[20][2]).read_text(
        encoding="utf-8"
    )

    runs = _create_table_position(source, "batch_review_runs")
    items = _create_table_position(source, "batch_review_items")
    commands = _create_table_position(source, "batch_review_commands")

    assert runs < items < commands
    assert "ck_batch_review_runs_status" in source
    assert "ck_batch_review_runs_revision_nonnegative" in source
    assert "ck_batch_review_items_status" in source
    assert "ck_batch_review_items_attempt_count_nonnegative" in source
    assert "uq_batch_review_items_run_batch" in source
    assert "ix_batch_review_items_run_target" in source
    assert "mysql.BINARY(16)" in source
    assert "mysql.BINARY(32)" in source
    assert "fk_batch_review_items_run" in source
    assert 'ondelete="CASCADE"' in source
    assert "fk_batch_review_items_batch" in source
    assert "fk_batch_review_items_version" in source
    assert "lease_token" in source
    assert "lease_expires_at" in source
    assert "lease_fence" in source
    assert "pk_batch_review_commands" in source
    assert "0021 downgrade refused" in source


def test_product_catalog_foundation_is_complete_and_retry_safe() -> None:
    source = (VERSIONS_DIRECTORY / EXPECTED_MIGRATIONS[21][2]).read_text(
        encoding="utf-8"
    )

    required_tables = (
        "report_source_scopes",
        "report_dataset_scope_assignments",
        "report_source_keys",
        "publication_snapshots",
        "publication_snapshot_members",
        "return_dedup_group_revisions",
        "return_dedup_group_members",
        "return_dedup_snapshots",
        "return_dedup_snapshot_groups",
        "return_dedup_publications",
        "return_dedup_staging_jobs",
        "fact_snapshot_tuples",
        "product_styles",
        "product_style_revisions",
        "product_skus",
        "product_sku_revisions",
        "product_identity_key_reservations",
        "product_catalog_versions",
        "product_catalog_style_members",
        "product_catalog_sku_members",
        "product_catalog_mappings",
        "product_catalog_exclusions",
        "product_catalog_publications",
        "product_catalog_publication_events",
        "catalog_source_refs",
        "catalog_source_evidence",
        "catalog_exports",
        "catalog_export_payloads",
        "catalog_imports",
        "catalog_parse_attempts",
        "catalog_import_rows",
        "catalog_import_issues",
        "catalog_validation_runs",
        "catalog_approval_projections",
        "catalog_command_claims",
        "catalog_command_effects",
        "catalog_audit_events",
        "catalog_jobs",
    )
    positions = [_create_table_position(source, table) for table in required_tables]

    assert positions == sorted(positions)
    assert "_assert_trigger_creation_policy" in source
    assert "_assert_recoverable_partial_upgrade" in source
    assert "information_schema.columns" in source
    assert "information_schema.table_constraints" in source
    assert "information_schema.statistics" in source
    assert "information_schema.triggers" in source
    assert "terminal_write_guard_bypass_accounts" in source
    assert "incompatible pre-existing 0022 catalog schema" in source
    assert "0022 downgrade refused" in source


def test_migration_catalog_queries_avoid_mysql_reserved_aliases() -> None:
    for path in sorted(VERSIONS_DIRECTORY.glob("*.py")):
        source = path.read_text(encoding="utf-8")
        assert re.search(r"\bAS\s+keys\b", source, re.IGNORECASE) is None, path.name


def test_admin_operation_migration_defines_immutable_frozen_results() -> None:
    source = (VERSIONS_DIRECTORY / EXPECTED_MIGRATIONS[10][2]).read_text(
        encoding="utf-8"
    )

    tokens = _create_table_position(source, "admin_operation_tokens")
    results = _create_table_position(source, "admin_operation_results")
    first_trigger = source.index("_create_immutable_triggers()", results)
    assert tokens < results < first_trigger
    assert '"uq_admin_operation_tokens_identity"' in source
    assert '"fk_admin_operation_results_identity"' in source
    assert 'sa.Column("response_payload", mysql.JSON(), nullable=False)' in source
    assert 'sa.Column("secret_verifier", _code_type(255), nullable=True)' in source
    assert "response_schema_version = 1" in source
    assert "response_status_code = 200" in source
    assert "response_status_code = 201" in source
    assert "terminal_write_guard_bypass_accounts" in source
    assert source.index(
        "_assert_trigger_creation_policy()", source.index("def upgrade")
    ) < (source.index("_create_token_table()", source.index("def upgrade")))


def test_admin_operation_partial_recovery_validates_the_complete_schema() -> None:
    source = (VERSIONS_DIRECTORY / EXPECTED_MIGRATIONS[10][2]).read_text(
        encoding="utf-8"
    )

    for catalog in (
        "information_schema.tables",
        "information_schema.columns",
        "information_schema.table_constraints",
        "information_schema.key_column_usage",
        "information_schema.referential_constraints",
        "information_schema.check_constraints",
        "information_schema.statistics",
        "information_schema.triggers",
    ):
        assert catalog in source
    for signature_field in (
        "column_type",
        "is_nullable",
        "character_set_name",
        "collation_name",
        "constraint_type",
        "referenced_table_name",
        "delete_rule",
        "update_rule",
        "check_clause",
        "enforced",
        "non_unique",
        "seq_in_index",
        "index_type",
        "is_visible",
    ):
        assert signature_field in source
    assert "_assert_partial_table_signature" in source
    assert "_assert_partial_trigger_signatures" in source
    assert "SELECT COUNT(*)" in source
    assert "repair it explicitly before retrying" in source


def test_admin_operation_secret_migration_scrubs_legacy_password_verifiers() -> None:
    source = (VERSIONS_DIRECTORY / EXPECTED_MIGRATIONS[11][2]).read_text(
        encoding="utf-8"
    )

    assert "terminal_write_guard_bypass_accounts" in source
    assert "trg_admin_operation_tokens_no_update" in source
    assert "trg_admin_operation_tokens_no_delete" in source
    assert "$legacy-untrusted$v1$" in source
    assert "LIKE '$argon2%'" in source
    assert "DROP TRIGGER" not in source.upper()
    downgrade = source[source.index("def downgrade") :]
    assert "UPDATE admin_operation_tokens" not in downgrade


def test_admin_operation_tag_migration_scrubs_public_key_v1_tags() -> None:
    source = (VERSIONS_DIRECTORY / EXPECTED_MIGRATIONS[12][2]).read_text(
        encoding="utf-8"
    )

    assert "terminal_write_guard_bypass_accounts" in source
    assert "$legacy-untrusted$v1$" in source
    assert "LIKE '$hmac-sha256$v1$%'" in source
    assert "DROP TRIGGER" not in source.upper()
    downgrade = source[source.index("def downgrade") :]
    assert "UPDATE admin_operation_tokens" not in downgrade


def test_admin_operation_verifier_removal_migration_scrubs_every_secret_value() -> None:
    source = (VERSIONS_DIRECTORY / EXPECTED_MIGRATIONS[13][2]).read_text(
        encoding="utf-8"
    )

    assert "terminal_write_guard_bypass_accounts" in source
    assert "$secret-not-stored$v1$" in source
    assert "WHERE secret_verifier IS NOT NULL" in source
    assert "DROP TRIGGER" not in source.upper()
    downgrade = source[source.index("def downgrade") :]
    assert "UPDATE admin_operation_tokens" not in downgrade


def test_admin_operation_marker_migration_enforces_the_non_secret_domain() -> None:
    source = (VERSIONS_DIRECTORY / EXPECTED_MIGRATIONS[14][2]).read_text(
        encoding="utf-8"
    )

    assert "terminal_write_guard_bypass_accounts" in source
    assert "ck_admin_operation_tokens_secret" in source
    assert "ck_admin_operation_tokens_secret_marker" in source
    assert "information_schema.check_constraints" in source
    assert "enforced" in source
    assert "$secret-not-stored$v1$" in source
    assert "secret_verifier IS NULL" in source
    assert "WHERE secret_verifier IS NOT NULL" in source
    assert "DROP TRIGGER" not in source.upper()
    cleanup = source.index("UPDATE admin_operation_tokens")
    constraint = source.index("op.create_check_constraint")
    assert cleanup < constraint
    downgrade = source[source.index("def downgrade") :]
    assert "UPDATE admin_operation_tokens" not in downgrade


def test_admin_operation_runtime_uses_only_a_non_verifying_secret_marker() -> None:
    source = ADMIN_MANAGEMENT_MODULE.read_text(encoding="utf-8")

    assert '_SECRET_NOT_STORED = "$secret-not-stored$v1$"' in source
    assert "admin_operation_secret_tag" not in source
    assert "admin_operation_secret_matches" not in source
    assert "session_secret" not in source


def test_stage_four_migration_checks_data_before_nontransactional_ddl() -> None:
    source = (VERSIONS_DIRECTORY / EXPECTED_MIGRATIONS[6][2]).read_text(
        encoding="utf-8"
    )

    preflight = source.index("_assert_upgrade_preconditions()")
    first_ddl = source.index("op.add_column(", preflight)

    assert "context.is_offline_mode()" in source
    assert preflight < first_ddl


def test_stage_four_migration_makes_effective_type_nullable_before_clearing_it() -> (
    None
):
    source = (VERSIONS_DIRECTORY / EXPECTED_MIGRATIONS[6][2]).read_text(
        encoding="utf-8"
    )

    upgrade = source.index("def upgrade()")
    nullable_alter = source.index(
        '"import_batches",\n        "report_type",',
        upgrade,
    )
    clear_unparsed_type = source.index("SET report_type = NULL", upgrade)

    assert nullable_alter < clear_unparsed_type


def test_stage_four_migration_renames_conversion_rate_columns_symmetrically() -> None:
    source = (VERSIONS_DIRECTORY / EXPECTED_MIGRATIONS[6][2]).read_text(
        encoding="utf-8"
    )

    for table_name in (
        "business_parse_baseline_rows",
        "business_version_base_rows",
        "business_report_rows",
    ):
        assert source.count(f'"{table_name}"') >= 2
    assert source.count('new_column_name="conversion_rate_total"') == 3
    assert source.count('new_column_name="session_percentage_total"') == 3


def test_stage_four_operation_token_registries_follow_safe_migration_order() -> None:
    source = (VERSIONS_DIRECTORY / EXPECTED_MIGRATIONS[6][2]).read_text(
        encoding="utf-8"
    )

    upgrade = source.index("def upgrade()")
    parse_registry = source.index(
        'op.create_table(\n        "parse_operation_tokens"',
        upgrade,
    )
    date_registry = source.index(
        'op.create_table(\n        "report_date_operation_tokens"',
        upgrade,
    )
    legacy_token_backfill = source.index(
        "SET processing_token = UNHEX",
        upgrade,
    )
    registry_backfill = source.index(
        "INSERT INTO parse_operation_tokens",
        legacy_token_backfill,
    )
    batch_identity_fk = source.index(
        '"fk_import_batches_parse_operation_token"',
        registry_backfill,
    )
    attempt_identity_fk = source.index(
        '"fk_parse_attempts_operation_token"',
        registry_backfill,
    )

    assert parse_registry < legacy_token_backfill < registry_backfill
    assert date_registry < registry_backfill
    assert registry_backfill < batch_identity_fk
    assert registry_backfill < attempt_identity_fk

    downgrade = source.index("def downgrade()")
    drop_batch_identity_fk = source.index(
        '"fk_import_batches_parse_operation_token"',
        downgrade,
    )
    drop_attempt_identity_fk = source.index(
        '"fk_parse_attempts_operation_token"',
        downgrade,
    )
    drop_date_registry = source.index(
        'op.drop_table("report_date_operation_tokens")',
        downgrade,
    )
    drop_parse_registry = source.index(
        'op.drop_table("parse_operation_tokens")',
        downgrade,
    )

    assert drop_batch_identity_fk < drop_date_registry
    assert drop_attempt_identity_fk < drop_date_registry
    assert drop_batch_identity_fk < drop_parse_registry
    assert drop_attempt_identity_fk < drop_parse_registry


def test_stage_five_migration_preflights_before_nontransactional_ddl() -> None:
    source = (VERSIONS_DIRECTORY / EXPECTED_MIGRATIONS[7][2]).read_text(
        encoding="utf-8"
    )

    upgrade = source.index("def upgrade()")
    upgrade_preflight = source.index("_assert_upgrade_preconditions()", upgrade)
    first_upgrade_ddl = min(
        source.index("op.create_", upgrade_preflight),
        source.index("op.add_column(", upgrade_preflight),
    )
    downgrade = source.index("def downgrade()")
    downgrade_preflight = source.index("_assert_downgrade_preconditions()", downgrade)
    first_downgrade_ddl = source.index("op.drop_table(", downgrade_preflight)

    assert "context.is_offline_mode()" in source
    assert "WHERE row_state <> 'active'" in source
    assert upgrade_preflight < first_upgrade_ddl
    assert downgrade_preflight < first_downgrade_ddl


def test_stage_five_migration_defines_immutable_operation_and_disposition_ledgers() -> (
    None
):
    source = (VERSIONS_DIRECTORY / EXPECTED_MIGRATIONS[7][2]).read_text(
        encoding="utf-8"
    )

    for table_name in (
        "draft_operation_tokens",
        "draft_operation_results",
        "draft_disposition_events",
    ):
        _create_table_position(source, table_name)

    assert "mysql.BINARY(16)" in source
    assert "mysql.BINARY(32)" in source
    assert '"uq_draft_operation_tokens_identity"' in source
    assert '"fk_draft_operation_results_identity"' in source
    assert '"uq_draft_disposition_events_version"' in source
    assert "'cancelled'" in source
    for frozen_column in (
        "result_version_no",
        "result_status",
        "result_data_revision",
        "result_review_revision",
        "superseded_version_id_1",
        "superseded_version_id_2",
    ):
        assert frozen_column in source
    assert '"fk_draft_disposition_events_identity"' in source
    assert '"ck_draft_disposition_events_operation_kind"' in source
    assert '"ck_draft_operation_results_semantics"' in source
    assert '"ck_draft_operation_results_cancelled_lineage"' in source


def test_stage_five_migration_defines_and_backfills_dedicated_dataset_locks() -> None:
    source = (VERSIONS_DIRECTORY / EXPECTED_MIGRATIONS[7][2]).read_text(
        encoding="utf-8"
    )

    create_lock_table = _create_table_position(source, "daily_dataset_locks")
    backfill_lock_rows = source.index(
        "INSERT INTO daily_dataset_locks (dataset_id, lock_revision)",
        create_lock_table,
    )
    first_other_stage_five_ddl = source.index(
        'op.create_check_constraint(\n        "ck_dataset_versions_version_no_positive"'
    )
    downgrade = source.index("def downgrade()")
    drop_lock_table = source.index(
        'op.drop_table("daily_dataset_locks")',
        downgrade,
    )
    drop_immutable_ledgers = source.index(
        'op.drop_table("draft_disposition_events")',
        downgrade,
    )

    assert create_lock_table < backfill_lock_rows < first_other_stage_five_ddl
    assert '"pk_daily_dataset_locks"' in source
    assert '"fk_daily_dataset_locks_dataset"' in source
    assert '["daily_datasets.id"]' in source
    assert "SELECT id, 0" in source
    assert source.index("op.drop_table(", downgrade) == drop_lock_table
    assert drop_lock_table < drop_immutable_ledgers


def test_stage_five_upgrade_removes_downgrade_only_restore_indexes() -> None:
    source = (VERSIONS_DIRECTORY / EXPECTED_MIGRATIONS[7][2]).read_text(
        encoding="utf-8"
    )

    assert "def _drop_index_if_exists_online(" in source
    for index_name in (
        "ix_vbsm_parent_version_restore",
        "ix_vbsm_parse_baseline_restore",
        "ix_dataset_drafts_dataset_version_restore",
    ):
        assert (
            source.count(f'_drop_index_if_exists_online(\n        "{index_name}"') == 1
        )


def test_stage_five_replaces_draft_foreign_keys_without_an_unprotected_gap() -> None:
    source = (VERSIONS_DIRECTORY / EXPECTED_MIGRATIONS[7][2]).read_text(
        encoding="utf-8"
    )

    upgrade = source.index("def upgrade()")
    downgrade = source.index("def downgrade()")
    add_editable_fk = source.index(
        'op.create_foreign_key(\n        "fk_dataset_drafts_editable_version"',
        upgrade,
    )
    drop_original_fk = source.index(
        'op.drop_constraint(\n        "fk_dataset_drafts_version"',
        add_editable_fk,
    )

    create_restore_index = source.index(
        'op.create_index(\n        "ix_dataset_drafts_dataset_version_restore"',
        downgrade,
    )
    add_original_fk = source.index(
        'op.create_foreign_key(\n        "fk_dataset_drafts_version"',
        create_restore_index,
    )
    drop_editable_fk = source.index(
        'op.drop_constraint(\n        "fk_dataset_drafts_editable_version"',
        add_original_fk,
    )

    assert upgrade < add_editable_fk < drop_original_fk < downgrade
    assert downgrade < create_restore_index < add_original_fk < drop_editable_fk


def test_stage_six_migration_preflights_before_nontransactional_ddl() -> None:
    source = (VERSIONS_DIRECTORY / EXPECTED_MIGRATIONS[8][2]).read_text(
        encoding="utf-8"
    )

    upgrade = source.index("def upgrade()")
    upgrade_preflight = source.index("_assert_upgrade_preconditions()", upgrade)
    first_upgrade_ddl = min(
        source.index("op.create_", upgrade_preflight),
        source.index("op.add_column(", upgrade_preflight),
    )
    downgrade = source.index("def downgrade()")
    downgrade_preflight = source.index("_assert_downgrade_preconditions()", downgrade)
    first_downgrade_ddl = source.index("op.execute(", downgrade_preflight)

    assert "context.is_offline_mode()" in source
    trigger_policy_check = source.index("_assert_trigger_creation_policy()", upgrade)
    assert "@@GLOBAL.log_bin_trust_function_creators" in source
    assert trigger_policy_check < upgrade_preflight
    assert upgrade_preflight < first_upgrade_ddl
    assert downgrade_preflight < first_downgrade_ddl


def test_stage_six_migration_hardens_review_and_publication_contracts() -> None:
    source = (VERSIONS_DIRECTORY / EXPECTED_MIGRATIONS[8][2]).read_text(
        encoding="utf-8"
    )

    for required_contract in (
        "uq_dce_version_id_kind",
        "fk_field_changes_event_kind",
        "fk_row_changes_event_kind",
        "fk_field_changes_restore_previous",
        "fk_field_changes_restore_parent",
        "fk_field_changes_restore_source",
        "ck_field_changes_restore_lineage",
        "ck_validation_runs_terminal",
        "fk_validation_issues_attempt",
        "fk_issue_review_events_issue_kind",
        "publication_command_results",
        "review_operation_tokens",
        "review_operation_results",
        "version_review_events",
        "note_threads",
        "supersedes_revision_number",
        "result_import_batch_id",
        "create_revision_parent_version_id",
        "create_published_move_revision",
        "move_revision_created",
        "published_move_source_parent_version_id",
        "published_move_source_lineage_type",
        "fk_draft_operation_results_published_move_source",
        "move_revision_operation_token",
        "reversed_move_command_id",
        "fk_publication_command_results_move_revision",
        "fk_publication_command_results_reversed_move",
        "validation_run_id",
        "terminal_write_guard_bypass_accounts",
        "uq_publication_commands_token",
        "ck_draft_operation_results_create_revision_parent",
        "fk_draft_operation_results_create_revision_parent",
        "fk_dataset_publications_published_version",
        "trg_dataset_versions_terminal_update",
        '("business_rows", "business_report_rows")',
        '("return_rows", "return_report_rows")',
    ):
        assert required_contract in source

    upgrade = source.index("def upgrade()")
    add_field_kind_fk = source.index('"fk_field_changes_event_kind"', upgrade)
    drop_old_field_fk = source.index(
        '"fk_field_changes_change_event"', add_field_kind_fk
    )
    add_row_kind_fk = source.index('"fk_row_changes_event_kind"', upgrade)
    drop_old_row_fk = source.index('"fk_row_changes_change_event"', add_row_kind_fk)
    create_triggers = source.rindex("_create_write_guard_triggers()")

    assert add_field_kind_fk < drop_old_field_fk < create_triggers
    assert add_row_kind_fk < drop_old_row_fk < create_triggers
    assert "WHERE operation_kind = 'create_revision'" in source
    assert "AND result_kind = 'created' AND result_status = 'draft'" in source
    assert "AND source_dataset_id = result_dataset_id" in source
    assert "AND source_version_id <> result_version_id" in source
    assert "AND create_revision_parent_version_id = source_version_id" in source
    assert '["child_version_id", "parent_version_id"]' in source
    assert "information_schema.schema_privileges" in source
    assert "privilege_type = 'TRIGGER'" in source
    assert "_has_recoverable_partial_upgrade()" in source


def test_publication_downgrade_compatibility_index_is_durable_and_fail_closed() -> None:
    source = (VERSIONS_DIRECTORY / EXPECTED_MIGRATIONS[15][2]).read_text(
        encoding="utf-8"
    )

    assert 'revision = "0016"' in source
    assert 'down_revision = "0015"' in source
    assert '"fk_dataset_publications_version"' in source
    assert '("dataset_id", "version_id")' in source
    assert '"fk_issue_review_events_issue_run"' in source
    assert '("version_id", "validation_run_id", "validation_issue_id")' in source
    assert '"fk_field_changes_change_event"' in source
    assert '"fk_row_changes_change_event"' in source
    assert "information_schema.statistics" in source
    assert "incompatible {label} downgrade" in source
    assert "for spec in _INDEX_SPECS" in source
    downgrade = source[source.index("def downgrade()") :]
    assert "op.drop_index" not in downgrade
    assert "_ensure_compatibility_index(spec)" in downgrade


def test_review_note_forward_repair_is_narrow_complete_and_fail_closed() -> None:
    source = (VERSIONS_DIRECTORY / EXPECTED_MIGRATIONS[16][2]).read_text(
        encoding="utf-8"
    )

    assert 'revision = "0017"' in source
    assert 'down_revision = "0016"' in source
    for table_name in (
        "note_threads",
        "publication_command_results",
        "review_operation_tokens",
        "review_operation_results",
        "version_review_events",
    ):
        assert table_name in source
    for catalog in (
        "information_schema.tables",
        "information_schema.columns",
        "information_schema.table_constraints",
        "information_schema.key_column_usage",
        "information_schema.referential_constraints",
        "information_schema.check_constraints",
        "information_schema.statistics",
        "information_schema.triggers",
    ):
        assert catalog in source
    assert "_assert_complete_table_signature" in source
    assert "_assert_legacy_notes_signature" in source
    assert "INSERT INTO note_threads" in source
    assert "FROM notes" in source
    assert "revision_number = 1" in source
    assert "supersedes_revision_number" in source
    assert "publication-history evidence" in source
    assert "review-state evidence" in source
    assert "data_revision <> 0 OR review_revision <> 0" in source
    assert "_create_publication_command_results" in source
    assert "_create_version_review_events" in source
    assert "incompatible pre-existing review/note contract" in source
    assert "context.is_offline_mode()" in source
    assert "0017 requires an online migration connection" in source
    downgrade = source[source.index("def downgrade()") :]
    assert "drop_table" not in downgrade


def test_offline_mysql_ddl_uses_utf8mb4_through_revision_sixteen() -> None:
    environment = os.environ.copy()
    environment["APP_MIGRATION_DATABASE_URL"] = (
        "mysql+pymysql://migration:placeholder@127.0.0.1:3306/"
        "clsen_contract?charset=utf8mb4"
    )
    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "alembic",
            "-c",
            str(BACKEND_ROOT / "alembic.ini"),
            "upgrade",
            "0016",
            "--sql",
        ],
        cwd=BACKEND_ROOT,
        env=environment,
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr
    ddl = result.stdout.lower()
    assert ddl.count("insert into alembic_version") == 1
    assert ddl.count("update alembic_version") == 15
    assert "charset=utf8mb4" in ddl
    assert ddl.index("create table import_batches") < ddl.index(
        "create table parse_attempts"
    )
    assert ddl.index("create table parse_attempts") < ddl.index(
        "fk_import_batches_current_parse_attempt"
    )
    assert "create table raw_file_integrity_statuses" in ddl
    assert "ix_file_ingest_leases_storage_key_status_expires" in ddl
    assert "ix_file_ingest_leases_sha256_status_expires" in ddl
    assert "detected_report_type" in ddl
    assert "confirmed_report_type" in ddl
    assert "processing_token" in ddl
    assert "processing_operation_digest" in ddl
    assert "operation_digest" in ddl
    assert "uq_parse_attempts_processing_token" in ddl
    assert "create table parse_operation_tokens" in ddl
    assert "create table report_date_operation_tokens" in ddl
    assert "uq_parse_operation_tokens_identity" in ddl
    assert "uq_report_date_operation_tokens_identity" in ddl
    assert "fk_import_batches_parse_operation_token" in ddl
    assert "fk_parse_attempts_operation_token" in ddl
    assert "fk_import_batches_current_parse_baseline" in ddl
    assert "fk_parse_baselines_successful_attempt" in ddl
    assert ddl.count("conversion_rate_total") >= 3
    assert "create table draft_operation_tokens" in ddl
    assert "create table admin_operation_tokens" in ddl
    assert "create table admin_operation_results" in ddl
    assert ddl.count("update admin_operation_tokens") == 4
    assert "ck_admin_operation_tokens_secret_marker" in ddl
    assert "create table draft_operation_results" in ddl
    assert "create table draft_disposition_events" in ddl
    assert "create table daily_dataset_locks" in ddl
    assert "insert into daily_dataset_locks" in ddl
    assert "version_status" in ddl
    assert "row_state" in ddl
    assert "create table publication_command_results" in ddl
    assert "fk_field_changes_event_kind" in ddl
    assert "fk_row_changes_event_kind" in ddl
    assert "fk_dataset_publications_published_version" in ddl
    assert "create index fk_dataset_publications_version" in ddl
    assert "create trigger trg_dataset_versions_terminal_update" in ddl
    assert "create table auth_sessions" in ddl
    assert "uq_auth_sessions_token_hash" in ddl


def test_review_note_repair_refuses_offline_revision_stamping() -> None:
    environment = os.environ.copy()
    environment["APP_MIGRATION_DATABASE_URL"] = (
        "mysql+pymysql://migration:placeholder@127.0.0.1:3306/"
        "clsen_contract?charset=utf8mb4"
    )
    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "alembic",
            "-c",
            str(BACKEND_ROOT / "alembic.ini"),
            "upgrade",
            "head",
            "--sql",
        ],
        cwd=BACKEND_ROOT,
        env=environment,
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode != 0
    assert "0017 requires an online migration connection" in result.stderr
    assert "SET version_num='0017'" not in result.stdout
