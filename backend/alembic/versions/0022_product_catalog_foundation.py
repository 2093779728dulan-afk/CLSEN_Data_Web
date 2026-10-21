"""Add the P0 product catalog, frozen fact tuple, and review ledgers."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Callable
from typing import Any

import sqlalchemy as sa
from alembic import context, op
from sqlalchemy.dialects import mysql

revision = "0022"
down_revision = "0021"
branch_labels = None
depends_on = None

_TABLE_OPTIONS: dict[str, Any] = {
    "mysql_engine": "InnoDB",
    "mysql_charset": "utf8mb4",
    "mysql_collate": "utf8mb4_0900_ai_ci",
}


def _id_type() -> mysql.BIGINT:
    return mysql.BIGINT(unsigned=True)


def _counter_type() -> mysql.BIGINT:
    return mysql.BIGINT(unsigned=True)


def _code_type(length: int) -> mysql.VARCHAR:
    return mysql.VARCHAR(length, charset="ascii", collation="ascii_bin")


def _binary_text_type(length: int) -> mysql.VARBINARY:
    return mysql.VARBINARY(length)


def _timestamp_type() -> mysql.DATETIME:
    return mysql.DATETIME(fsp=6)


def _created_at() -> sa.Column[Any]:
    return sa.Column(
        "created_at",
        _timestamp_type(),
        server_default=sa.text("CURRENT_TIMESTAMP(6)"),
        nullable=False,
    )


def _updated_at() -> sa.Column[Any]:
    return sa.Column(
        "updated_at",
        _timestamp_type(),
        server_default=sa.text("CURRENT_TIMESTAMP(6)"),
        nullable=False,
    )


_CATALOG_TABLE_ORDER = (
    "report_source_scopes",
    "report_dataset_scope_assignments",
    "report_source_keys",
    "report_publication_revisions",
    "publication_snapshots",
    "publication_snapshot_members",
    "return_dedup_group_revisions",
    "return_dedup_group_members",
    "return_dedup_snapshots",
    "return_dedup_snapshot_groups",
    "return_dedup_publications",
    "return_dedup_staging_jobs",
    "return_dedup_staging_members",
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

_IMMUTABLE_TABLES = frozenset(
    {
        "report_source_scopes",
        "report_dataset_scope_assignments",
        "report_source_keys",
        "return_dedup_staging_members",
        "publication_snapshot_members",
        "return_dedup_group_revisions",
        "return_dedup_group_members",
        "return_dedup_snapshots",
        "return_dedup_snapshot_groups",
        "fact_snapshot_tuples",
        "product_style_revisions",
        "product_sku_revisions",
        "product_identity_key_reservations",
        "product_catalog_versions",
        "product_catalog_style_members",
        "product_catalog_sku_members",
        "product_catalog_mappings",
        "product_catalog_exclusions",
        "product_catalog_publication_events",
        "catalog_source_refs",
        "catalog_source_evidence",
        "catalog_export_payloads",
        "catalog_import_rows",
        "catalog_import_issues",
        "catalog_validation_runs",
        "catalog_approval_projections",
        "catalog_command_effects",
        "catalog_audit_events",
    }
)

_TRANSITION_TABLES = frozenset(
    {"catalog_parse_attempts", "catalog_command_claims", "publication_snapshots"}
)

_EXPECTED_COLUMNS: dict[str, tuple[str, ...]] = {
    "report_source_scopes": (
        "id",
        "site_id",
        "seller_account_scope_key",
        "seller_account_display_name",
        "marketplace_scope_code",
        "confirmed_by_user_id",
        "confirmed_at",
        "created_at",
    ),
    "report_dataset_scope_assignments": (
        "id",
        "dataset_id",
        "site_id",
        "report_source_scope_id",
        "assigned_at",
    ),
    "report_source_keys": (
        "id",
        "dataset_id",
        "version_id",
        "source_row_id",
        "site_id",
        "report_source_scope_id",
        "report_type",
        "source_key_revision",
        "seller_sku_raw_sha256",
        "seller_sku_match_sha256",
        "seller_sku_match_bytes",
        "normalization_version",
        "collision_group_sha256",
        "created_at",
    ),
    "report_publication_revisions": (
        "dataset_id",
        "site_id",
        "report_source_scope_id",
        "publication_revision",
        "updated_at",
    ),
    "publication_snapshots": (
        "id",
        "site_id",
        "report_source_scope_id",
        "site_config_version_id",
        "candidate_rule_version",
        "normalization_manifest_id",
        "coverage_start_date",
        "coverage_end_date",
        "transaction_started_at",
        "fact_cutoff_at",
        "return_publication_set_digest",
        "status",
        "snapshot_digest",
        "created_at",
    ),
    "publication_snapshot_members": (
        "id",
        "publication_snapshot_id",
        "site_id",
        "report_type",
        "report_date",
        "dataset_id",
        "published_version_id",
        "publication_pointer_revision",
        "member_status",
        "active_row_count",
        "active_row_projection_digest",
        "created_at",
    ),
    "return_dedup_group_revisions": (
        "id",
        "site_id",
        "report_source_scope_id",
        "group_key_sha256",
        "revision",
        "member_set_digest",
        "decision",
        "canonical_source_key_id",
        "reason_code",
        "decided_by_user_id",
        "created_at",
    ),
    "return_dedup_group_members": (
        "id",
        "group_revision_id",
        "source_key_id",
        "member_order",
        "created_at",
    ),
    "return_dedup_snapshots": (
        "id",
        "site_id",
        "report_source_scope_id",
        "return_publication_set_digest",
        "rule_version",
        "base_snapshot_id",
        "checkpoint_snapshot_id",
        "delta_depth",
        "snapshot_kind",
        "status",
        "decision_digest",
        "created_at",
    ),
    "return_dedup_snapshot_groups": (
        "id",
        "snapshot_id",
        "group_revision_id",
        "entry_kind",
        "created_at",
    ),
    "return_dedup_publications": (
        "site_id",
        "report_source_scope_id",
        "current_snapshot_id",
        "dedup_publication_revision",
        "updated_at",
    ),
    "return_dedup_staging_jobs": (
        "id",
        "site_id",
        "report_source_scope_id",
        "operation_token",
        "operation_digest",
        "retry_operation_token",
        "retry_operation_digest",
        "actor_user_id",
        "dataset_id",
        "proposed_version_id",
        "proposed_set_digest",
        "rule_version",
        "expected_publication_revision",
        "expected_dedup_publication_revision",
        "status",
        "job_revision",
        "retry_allowed",
        "failure_reason_code",
        "lease_token",
        "fencing_token",
        "lease_expires_at",
        "result_snapshot_id",
        "created_at",
        "updated_at",
    ),
    "return_dedup_staging_members": (
        "id",
        "job_id",
        "dataset_id",
        "published_version_id",
        "publication_revision",
        "version_data_revision",
        "report_date",
        "member_order",
        "created_at",
    ),
    "fact_snapshot_tuples": (
        "id",
        "site_id",
        "report_source_scope_id",
        "publication_snapshot_id",
        "return_dedup_snapshot_id",
        "return_dedup_snapshot_status",
        "site_config_version_id",
        "fact_cutoff_at",
        "return_publication_set_digest",
        "tuple_digest",
        "status",
        "created_at",
    ),
    "product_styles": (
        "id",
        "site_id",
        "style_code",
        "style_key_sha256",
        "style_key_bytes",
        "standard_name",
        "status",
        "current_revision",
        "created_at",
        "updated_at",
    ),
    "product_style_revisions": (
        "id",
        "site_id",
        "style_id",
        "revision",
        "style_code",
        "style_key_sha256",
        "style_key_bytes",
        "standard_name",
        "status",
        "change_reason",
        "actor_user_id",
        "source_import_id",
        "source_command_token",
        "created_at",
    ),
    "product_skus": (
        "id",
        "site_id",
        "style_id",
        "internal_display_sku",
        "display_key_sha256",
        "display_key_bytes",
        "standard_color",
        "color_key_sha256",
        "color_key_bytes",
        "standard_size",
        "size_key_sha256",
        "size_key_bytes",
        "status",
        "current_revision",
        "created_at",
        "updated_at",
    ),
    "product_sku_revisions": (
        "id",
        "site_id",
        "sku_id",
        "style_id",
        "revision",
        "internal_display_sku",
        "display_key_sha256",
        "display_key_bytes",
        "standard_color",
        "color_key_sha256",
        "color_key_bytes",
        "standard_size",
        "size_key_sha256",
        "size_key_bytes",
        "status",
        "change_reason",
        "actor_user_id",
        "source_import_id",
        "source_command_token",
        "created_at",
    ),
    "product_identity_key_reservations": (
        "id",
        "site_id",
        "key_kind",
        "key_sha256",
        "key_bytes",
        "style_id",
        "sku_id",
        "first_revision_id",
        "created_at",
    ),
    "product_catalog_versions": (
        "id",
        "site_id",
        "version_number",
        "base_catalog_version_id",
        "workbook_schema_version",
        "normalization_manifest_id",
        "fact_snapshot_tuple_id",
        "source_import_id",
        "validation_run_id",
        "approval_digest",
        "diff_digest",
        "risk",
        "status",
        "approved_by_user_id",
        "approved_at",
        "approval_reason",
        "created_at",
    ),
    "product_catalog_style_members": (
        "id",
        "catalog_version_id",
        "site_id",
        "style_id",
        "style_revision_id",
        "created_at",
    ),
    "product_catalog_sku_members": (
        "id",
        "catalog_version_id",
        "site_id",
        "sku_id",
        "sku_revision_id",
        "style_id",
        "created_at",
    ),
    "product_catalog_mappings": (
        "id",
        "catalog_version_id",
        "site_id",
        "report_source_scope_id",
        "marketplace_scope_code",
        "seller_sku_match_sha256",
        "seller_sku_match_bytes",
        "sku_id",
        "decision_source",
        "actor_user_id",
        "evidence_digest",
        "created_at",
    ),
    "product_catalog_exclusions": (
        "id",
        "catalog_version_id",
        "site_id",
        "report_source_scope_id",
        "marketplace_scope_code",
        "seller_sku_match_sha256",
        "seller_sku_match_bytes",
        "reason",
        "actor_user_id",
        "evidence_digest",
        "created_at",
    ),
    "product_catalog_publications": (
        "site_id",
        "current_catalog_version_id",
        "catalog_publication_revision",
        "updated_at",
    ),
    "product_catalog_publication_events": (
        "id",
        "site_id",
        "catalog_publication_revision",
        "previous_catalog_version_id",
        "catalog_version_id",
        "event_kind",
        "operation_token",
        "actor_user_id",
        "reason",
        "created_at",
    ),
    "catalog_source_refs": (
        "id",
        "site_id",
        "resource_kind",
        "resource_id",
        "source_kind",
        "raw_value",
        "raw_sha256",
        "safe_preview",
        "is_unsafe",
        "is_truncated",
        "created_at",
    ),
    "catalog_source_evidence": (
        "id",
        "site_id",
        "report_source_scope_id",
        "source_key_id",
        "report_type",
        "report_date",
        "event_date",
        "dataset_id",
        "published_version_id",
        "source_row_id",
        "seller_sku_ref_id",
        "title_ref_id",
        "parent_asin_ref_id",
        "child_asin_ref_id",
        "fnsku_ref_id",
        "source_locator_ref_id",
        "evidence_tuple_digest",
        "created_at",
    ),
    "catalog_exports": (
        "id",
        "site_id",
        "operation_token",
        "fact_snapshot_tuple_id",
        "base_catalog_version_id",
        "catalog_publication_revision",
        "workbook_schema_version",
        "normalization_manifest_id",
        "export_status",
        "workbook_status",
        "capacity_violations",
        "artifact_sha256",
        "artifact_storage_key",
        "failure_reason_code",
        "created_by_user_id",
        "created_at",
        "updated_at",
    ),
    "catalog_export_payloads": (
        "export_id",
        "site_id",
        "candidate_payload_json",
        "candidate_payload_digest",
        "evidence_payload_json",
        "evidence_payload_digest",
        "payload_digest",
        "created_at",
    ),
    "catalog_imports": (
        "id",
        "site_id",
        "operation_token",
        "source_kind",
        "owner_user_id",
        "export_id",
        "raw_file_id",
        "original_filename",
        "declared_media_type",
        "base_catalog_version_id",
        "fact_snapshot_tuple_id",
        "normalization_manifest_id",
        "status",
        "workflow_revision",
        "parse_attempt_revision",
        "submitted_by_user_id",
        "validation_run_id",
        "superseded_by_id",
        "created_at",
        "updated_at",
    ),
    "catalog_parse_attempts": (
        "id",
        "import_id",
        "site_id",
        "attempt_revision",
        "workflow_revision",
        "status",
        "lease_token",
        "fencing_token",
        "started_at",
        "lease_expires_at",
        "completed_at",
        "recoverable",
        "failure_reason_code",
        "result_digest",
        "created_at",
    ),
    "catalog_import_rows": (
        "id",
        "import_id",
        "site_id",
        "workflow_revision",
        "section",
        "row_key",
        "row_origin",
        "projection_state",
        "payload_json",
        "payload_digest",
        "created_at",
    ),
    "catalog_import_issues": (
        "id",
        "import_id",
        "site_id",
        "workflow_revision",
        "section",
        "row_key",
        "severity",
        "reason_code",
        "safe_detail_json",
        "issue_digest",
        "created_at",
    ),
    "catalog_validation_runs": (
        "id",
        "import_id",
        "site_id",
        "workflow_revision",
        "status",
        "included_row_set_digest",
        "audit_only_row_set_digest",
        "issue_set_digest",
        "diff_digest",
        "created_by_user_id",
        "created_at",
    ),
    "catalog_approval_projections": (
        "id",
        "import_id",
        "site_id",
        "workflow_revision",
        "validation_run_id",
        "base_catalog_version_id",
        "catalog_publication_revision",
        "fact_snapshot_tuple_id",
        "risk",
        "diff_digest",
        "projection_digest",
        "created_by_user_id",
        "created_at",
        "expires_at",
    ),
    "catalog_command_claims": (
        "operation_token",
        "operation_kind",
        "operation_digest",
        "site_id",
        "actor_user_id",
        "resource_kind",
        "resource_id",
        "status",
        "created_at",
    ),
    "catalog_command_effects": (
        "operation_token",
        "operation_kind",
        "operation_digest",
        "site_id",
        "actor_user_id",
        "response_schema_version",
        "response_status_code",
        "safe_result_json",
        "completed_at",
    ),
    "catalog_audit_events": (
        "id",
        "site_id",
        "actor_user_id",
        "event_kind",
        "resource_kind",
        "resource_id",
        "operation_token",
        "safe_payload_json",
        "event_digest",
        "created_at",
    ),
    "catalog_jobs": (
        "id",
        "site_id",
        "job_kind",
        "resource_kind",
        "resource_id",
        "status",
        "job_revision",
        "lease_token",
        "fencing_token",
        "lease_expires_at",
        "retry_allowed",
        "failure_reason_code",
        "result_digest",
        "created_at",
        "updated_at",
    ),
}


def _trigger_name(table_name: str, operation: str) -> str:
    return f"trg_{table_name}_no_{operation.casefold()}"


def _immutable_trigger_statement(table_name: str) -> str:
    return f"""
        BEGIN
            IF NOT EXISTS (
                SELECT 1 FROM terminal_write_guard_bypass_accounts
                WHERE account_identity = USER()
            ) THEN
                SIGNAL SQLSTATE '45000'
                    SET MESSAGE_TEXT = '{table_name} is immutable';
            END IF;
        END
    """


def _assert_trigger_creation_policy() -> None:
    if context.is_offline_mode():
        raise RuntimeError("0022 requires an online migration connection")
    bind = op.get_bind()
    log_bin, trust = bind.execute(
        sa.text("SELECT @@GLOBAL.log_bin, @@GLOBAL.log_bin_trust_function_creators")
    ).one()
    if int(log_bin) != 0 and int(trust) != 1:
        raise RuntimeError(
            "0022 migration requires log_bin_trust_function_creators=ON "
            "while binary logging is enabled"
        )
    trigger_grants = bind.scalar(
        sa.text(
            """
            SELECT COUNT(*) FROM information_schema.schema_privileges
            WHERE table_schema = DATABASE() AND privilege_type = 'TRIGGER'
              AND grantee = CONCAT(
                  CHAR(39), SUBSTRING_INDEX(CURRENT_USER(), '@', 1),
                  CHAR(39), '@', CHAR(39),
                  SUBSTRING_INDEX(CURRENT_USER(), '@', -1), CHAR(39)
              )
            """
        )
    )
    if int(trigger_grants or 0) == 0:
        raise RuntimeError("0022 migration account requires TRIGGER on this database")


def _existing_catalog_tables() -> frozenset[str]:
    return frozenset(
        str(value)
        for value in op.get_bind().scalars(
            sa.text(
                """
                SELECT table_name FROM information_schema.tables
                WHERE table_schema = DATABASE() AND table_name IN :table_names
                """
            ).bindparams(sa.bindparam("table_names", expanding=True)),
            {"table_names": _CATALOG_TABLE_ORDER},
        )
    )


def _schema_signature(table_name: str) -> str:
    bind = op.get_bind()
    columns = bind.execute(
        sa.text(
            """
            SELECT ordinal_position, column_name, column_type, is_nullable,
                   column_default, character_set_name, collation_name,
                   extra, generation_expression
            FROM information_schema.columns
            WHERE table_schema = DATABASE() AND table_name = :table_name
            ORDER BY ordinal_position
            """
        ),
        {"table_name": table_name},
    ).tuples()
    constraints = bind.execute(
        sa.text(
            """
            SELECT constraints.constraint_name, constraints.constraint_type,
                   constraints.enforced, key_columns.ordinal_position,
                   key_columns.column_name,
                   key_columns.referenced_table_name,
                   key_columns.referenced_column_name,
                   references_.update_rule, references_.delete_rule,
                   checks.check_clause
            FROM information_schema.table_constraints AS constraints
            LEFT JOIN information_schema.key_column_usage AS key_columns
              ON key_columns.constraint_schema = constraints.constraint_schema
             AND key_columns.table_name = constraints.table_name
             AND key_columns.constraint_name = constraints.constraint_name
            LEFT JOIN information_schema.referential_constraints AS references_
              ON references_.constraint_schema = constraints.constraint_schema
             AND references_.table_name = constraints.table_name
             AND references_.constraint_name = constraints.constraint_name
            LEFT JOIN information_schema.check_constraints AS checks
              ON checks.constraint_schema = constraints.constraint_schema
             AND checks.constraint_name = constraints.constraint_name
            WHERE constraints.table_schema = DATABASE()
              AND constraints.table_name = :table_name
            ORDER BY constraints.constraint_name, key_columns.ordinal_position
            """
        ),
        {"table_name": table_name},
    ).tuples()
    indexes = bind.execute(
        sa.text(
            """
            SELECT index_name, non_unique, seq_in_index, column_name,
                   sub_part, collation, index_type, is_visible, expression
            FROM information_schema.statistics
            WHERE table_schema = DATABASE() AND table_name = :table_name
            ORDER BY index_name, seq_in_index
            """
        ),
        {"table_name": table_name},
    ).tuples()
    payload = {
        "columns": [
            [None if value is None else str(value) for value in row] for row in columns
        ],
        "constraints": [
            [None if value is None else str(value) for value in row]
            for row in constraints
        ],
        "indexes": [
            [None if value is None else str(value) for value in row] for row in indexes
        ],
    }
    encoded = json.dumps(
        payload,
        ensure_ascii=True,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("ascii")
    return hashlib.sha256(encoded).hexdigest()


def _seal_table_signature(table_name: str) -> None:
    bind = op.get_bind()
    for _attempt in range(3):
        digest = _schema_signature(table_name)
        expected_comment = f"clsen-0022:{digest}"
        table_comment = str(
            bind.scalar(
                sa.text(
                    """
                    SELECT table_comment FROM information_schema.tables
                    WHERE table_schema = DATABASE() AND table_name = :table_name
                    """
                ),
                {"table_name": table_name},
            )
            or ""
        )
        if table_comment == expected_comment:
            return
        op.execute(
            sa.text(f"ALTER TABLE `{table_name}` COMMENT = 'clsen-0022:{digest}'")
        )
    if (
        str(
            bind.scalar(
                sa.text(
                    """
                SELECT table_comment FROM information_schema.tables
                WHERE table_schema = DATABASE() AND table_name = :table_name
                """
                ),
                {"table_name": table_name},
            )
            or ""
        )
        != f"clsen-0022:{_schema_signature(table_name)}"
    ):
        raise RuntimeError(f"could not stabilize 0022 schema seal: {table_name}")


def _assert_partial_table_signature(table_name: str) -> bool:
    bind = op.get_bind()
    metadata = bind.execute(
        sa.text(
            """
            SELECT table_type, engine, table_collation
            FROM information_schema.tables
            WHERE table_schema = DATABASE() AND table_name = :table_name
            """
        ),
        {"table_name": table_name},
    ).one_or_none()
    if metadata is None or tuple(str(value).upper() for value in metadata) != (
        "BASE TABLE",
        "INNODB",
        "UTF8MB4_0900_AI_CI",
    ):
        raise RuntimeError(
            f"incompatible pre-existing 0022 catalog schema: {table_name} metadata"
        )
    columns = tuple(
        str(value)
        for value in bind.scalars(
            sa.text(
                """
                SELECT column_name FROM information_schema.columns
                WHERE table_schema = DATABASE() AND table_name = :table_name
                ORDER BY ordinal_position
                """
            ),
            {"table_name": table_name},
        )
    )
    if columns != _EXPECTED_COLUMNS[table_name]:
        raise RuntimeError(
            f"incompatible pre-existing 0022 catalog schema: {table_name} columns"
        )
    unexpected_indexes = tuple(
        str(value)
        for value in bind.scalars(
            sa.text(
                """
                SELECT DISTINCT index_name FROM information_schema.statistics
                WHERE table_schema = DATABASE() AND table_name = :table_name
                  AND index_name LIKE '%unexpected%'
                """
            ),
            {"table_name": table_name},
        )
    )
    if unexpected_indexes:
        raise RuntimeError(
            f"incompatible pre-existing 0022 catalog schema: {table_name} indexes"
        )
    table_comment = str(
        bind.scalar(
            sa.text(
                """
                SELECT table_comment FROM information_schema.tables
                WHERE table_schema = DATABASE() AND table_name = :table_name
                """
            ),
            {"table_name": table_name},
        )
        or ""
    )
    if table_comment:
        expected_comment = f"clsen-0022:{_schema_signature(table_name)}"
        if table_comment != expected_comment:
            raise RuntimeError(
                "incompatible pre-existing 0022 catalog schema: "
                f"{table_name} sealed signature"
            )
    row_count = int(bind.scalar(sa.text(f"SELECT COUNT(*) FROM `{table_name}`")) or 0)
    if row_count != 0:
        raise RuntimeError(
            f"incompatible pre-existing 0022 catalog schema: {table_name} is not empty"
        )
    return not table_comment


def _assert_partial_trigger_signatures(existing: frozenset[str]) -> None:
    rows = (
        op.get_bind()
        .execute(
            sa.text(
                """
            SELECT trigger_name, event_object_table, event_manipulation,
                   action_timing, action_statement
            FROM information_schema.triggers
            WHERE trigger_schema = DATABASE() AND event_object_table IN :table_names
            """
            ).bindparams(sa.bindparam("table_names", expanding=True)),
            {
                "table_names": tuple(
                    existing & (_IMMUTABLE_TABLES | _TRANSITION_TABLES)
                )
                or ("",)
            },
        )
        .tuples()
    )
    for name, table_name, operation, timing, statement in rows:
        table_name = str(table_name)
        operation = str(operation).upper()
        expected_name = _trigger_name(table_name, operation)
        normalized = "".join(str(statement).casefold().split())
        immutable = table_name in _IMMUTABLE_TABLES or (
            operation == "DELETE" and table_name in _TRANSITION_TABLES
        )
        valid = (
            str(name) != expected_name
            or str(timing).upper() != "BEFORE"
            or "terminal_write_guard_bypass_accounts" not in normalized
        )
        if immutable:
            valid = valid or f"{table_name}isimmutable" not in normalized
        elif table_name == "publication_snapshots":
            valid = valid or "publicationsnapshottransitionisinvalid" not in normalized
        elif table_name == "catalog_parse_attempts":
            valid = valid or "catalogparseattempttransitionisinvalid" not in normalized
        elif table_name == "catalog_command_claims":
            valid = valid or "catalogcommandclaimtransitionisinvalid" not in normalized
        else:
            valid = True
        if valid:
            raise RuntimeError(
                "incompatible pre-existing 0022 catalog schema: guarded trigger"
            )


def _assert_recoverable_partial_upgrade() -> frozenset[str]:
    existing = _existing_catalog_tables()
    expected_prefix = frozenset(_CATALOG_TABLE_ORDER[: len(existing)])
    if existing != expected_prefix:
        raise RuntimeError(
            "incompatible pre-existing 0022 catalog schema: tables are not a prefix"
        )
    unsealed: list[str] = []
    for table_name in _CATALOG_TABLE_ORDER[: len(existing)]:
        if _assert_partial_table_signature(table_name):
            unsealed.append(table_name)
    _assert_partial_trigger_signatures(existing)
    for table_name in unsealed:
        _seal_table_signature(table_name)
    return existing


def _create_immutable_trigger(table_name: str, operation: str) -> None:
    op.execute(
        sa.text(
            f"""
            CREATE TRIGGER {_trigger_name(table_name, operation)}
            BEFORE {operation} ON {table_name}
            FOR EACH ROW {_immutable_trigger_statement(table_name)}
            """
        )
    )


def _ensure_immutable_triggers() -> None:
    bind = op.get_bind()
    existing = frozenset(
        str(value)
        for value in bind.scalars(
            sa.text(
                """
                SELECT trigger_name FROM information_schema.triggers
                WHERE trigger_schema = DATABASE() AND event_object_table IN :table_names
                """
            ).bindparams(sa.bindparam("table_names", expanding=True)),
            {"table_names": tuple(_IMMUTABLE_TABLES)},
        )
    )
    for table_name in sorted(_IMMUTABLE_TABLES):
        for operation in ("UPDATE", "DELETE"):
            if _trigger_name(table_name, operation) not in existing:
                _create_immutable_trigger(table_name, operation)


def _ensure_publication_snapshot_transition_triggers() -> None:
    """Allow exactly one terminal status transition and reject every other write."""

    bind = op.get_bind()
    existing = frozenset(
        str(value)
        for value in bind.scalars(
            sa.text(
                "SELECT trigger_name FROM information_schema.triggers "
                "WHERE trigger_schema = DATABASE() "
                "AND event_object_table = 'publication_snapshots'"
            )
        )
    )
    update_trigger = _trigger_name("publication_snapshots", "UPDATE")
    if update_trigger not in existing:
        op.execute(
            sa.text(
                f"""
                CREATE TRIGGER {update_trigger}
                BEFORE UPDATE ON publication_snapshots
                FOR EACH ROW
                BEGIN
                    IF NOT EXISTS (
                        SELECT 1 FROM terminal_write_guard_bypass_accounts
                        WHERE account_identity = USER()
                    ) AND (
                        OLD.status <> 'building'
                        OR NEW.status NOT IN ('ready','failed')
                        OR NOT (NEW.id <=> OLD.id)
                        OR NOT (NEW.site_id <=> OLD.site_id)
                        OR NOT (NEW.report_source_scope_id
                                <=> OLD.report_source_scope_id)
                        OR NOT (NEW.site_config_version_id
                                <=> OLD.site_config_version_id)
                        OR NOT (NEW.candidate_rule_version
                                <=> OLD.candidate_rule_version)
                        OR NOT (NEW.normalization_manifest_id
                                <=> OLD.normalization_manifest_id)
                        OR NOT (NEW.coverage_start_date
                                <=> OLD.coverage_start_date)
                        OR NOT (NEW.coverage_end_date
                                <=> OLD.coverage_end_date)
                        OR NOT (NEW.transaction_started_at
                                <=> OLD.transaction_started_at)
                        OR NOT (NEW.fact_cutoff_at <=> OLD.fact_cutoff_at)
                        OR NOT (NEW.return_publication_set_digest
                                <=> OLD.return_publication_set_digest)
                        OR NOT (NEW.snapshot_digest <=> OLD.snapshot_digest)
                        OR NOT (NEW.created_at <=> OLD.created_at)
                    ) THEN
                        SIGNAL SQLSTATE '45000'
                            SET MESSAGE_TEXT =
                                'publication snapshot transition is invalid';
                    END IF;
                END
                """
            )
        )
    delete_trigger = _trigger_name("publication_snapshots", "DELETE")
    if delete_trigger not in existing:
        _create_immutable_trigger("publication_snapshots", "DELETE")


def _ensure_catalog_parse_attempt_transition_triggers() -> None:
    """Fence renewals and allow one running-to-terminal transition."""

    bind = op.get_bind()
    existing = frozenset(
        str(value)
        for value in bind.scalars(
            sa.text(
                "SELECT trigger_name FROM information_schema.triggers "
                "WHERE trigger_schema = DATABASE() "
                "AND event_object_table = 'catalog_parse_attempts'"
            )
        )
    )
    update_trigger = _trigger_name("catalog_parse_attempts", "UPDATE")
    if update_trigger not in existing:
        op.execute(
            sa.text(
                f"""
                CREATE TRIGGER {update_trigger}
                BEFORE UPDATE ON catalog_parse_attempts
                FOR EACH ROW
                BEGIN
                    IF NOT EXISTS (
                        SELECT 1 FROM terminal_write_guard_bypass_accounts
                        WHERE account_identity = USER()
                    ) AND (
                        OLD.status <> 'running'
                        OR NEW.status NOT IN ('running','succeeded','failed')
                        OR NEW.workflow_revision <> OLD.workflow_revision + 1
                        OR NOT (NEW.id <=> OLD.id)
                        OR NOT (NEW.import_id <=> OLD.import_id)
                        OR NOT (NEW.site_id <=> OLD.site_id)
                        OR NOT (NEW.attempt_revision <=> OLD.attempt_revision)
                        OR NOT (NEW.lease_token <=> OLD.lease_token)
                        OR NOT (NEW.fencing_token <=> OLD.fencing_token)
                        OR NOT (NEW.started_at <=> OLD.started_at)
                        OR NOT (NEW.created_at <=> OLD.created_at)
                        OR (
                            NEW.status = 'running'
                            AND (
                                NEW.lease_expires_at <= OLD.lease_expires_at
                                OR NOT (NEW.completed_at <=> OLD.completed_at)
                                OR NOT (NEW.recoverable <=> OLD.recoverable)
                                OR NOT (NEW.failure_reason_code
                                        <=> OLD.failure_reason_code)
                                OR NOT (NEW.result_digest <=> OLD.result_digest)
                            )
                        )
                        OR (
                            NEW.status IN ('succeeded','failed')
                            AND NOT (NEW.lease_expires_at
                                     <=> OLD.lease_expires_at)
                        )
                    ) THEN
                        SIGNAL SQLSTATE '45000'
                            SET MESSAGE_TEXT =
                                'catalog parse attempt transition is invalid';
                    END IF;
                END
                """
            )
        )
    delete_trigger = _trigger_name("catalog_parse_attempts", "DELETE")
    if delete_trigger not in existing:
        _create_immutable_trigger("catalog_parse_attempts", "DELETE")


def _ensure_catalog_command_claim_transition_triggers() -> None:
    """Allow a claim to reach one terminal result and reject all other writes."""

    bind = op.get_bind()
    existing = frozenset(
        str(value)
        for value in bind.scalars(
            sa.text(
                "SELECT trigger_name FROM information_schema.triggers "
                "WHERE trigger_schema = DATABASE() "
                "AND event_object_table = 'catalog_command_claims'"
            )
        )
    )
    update_trigger = _trigger_name("catalog_command_claims", "UPDATE")
    if update_trigger not in existing:
        op.execute(
            sa.text(
                f"""
                CREATE TRIGGER {update_trigger}
                BEFORE UPDATE ON catalog_command_claims
                FOR EACH ROW
                BEGIN
                    IF NOT EXISTS (
                        SELECT 1 FROM terminal_write_guard_bypass_accounts
                        WHERE account_identity = USER()
                    ) AND (
                        OLD.status <> 'claimed'
                        OR NEW.status NOT IN ('completed','outcome_unknown')
                        OR NOT (NEW.operation_token <=> OLD.operation_token)
                        OR NOT (NEW.operation_kind <=> OLD.operation_kind)
                        OR NOT (NEW.operation_digest <=> OLD.operation_digest)
                        OR NOT (NEW.site_id <=> OLD.site_id)
                        OR NOT (NEW.actor_user_id <=> OLD.actor_user_id)
                        OR NOT (NEW.resource_kind <=> OLD.resource_kind)
                        OR NOT (NEW.resource_id <=> OLD.resource_id)
                        OR NOT (NEW.created_at <=> OLD.created_at)
                    ) THEN
                        SIGNAL SQLSTATE '45000'
                            SET MESSAGE_TEXT =
                                'catalog command claim transition is invalid';
                    END IF;
                END
                """
            )
        )
    delete_trigger = _trigger_name("catalog_command_claims", "DELETE")
    if delete_trigger not in existing:
        _create_immutable_trigger("catalog_command_claims", "DELETE")


def _drop_immutable_triggers() -> None:
    for table_name in sorted(_TRANSITION_TABLES, reverse=True):
        for operation in ("UPDATE", "DELETE"):
            op.execute(
                sa.text(
                    f"DROP TRIGGER IF EXISTS {_trigger_name(table_name, operation)}"
                )
            )
    for table_name in sorted(_IMMUTABLE_TABLES, reverse=True):
        for operation in ("UPDATE", "DELETE"):
            op.execute(
                sa.text(
                    f"DROP TRIGGER IF EXISTS {_trigger_name(table_name, operation)}"
                )
            )


_LATE_FOREIGN_KEYS = (
    (
        "fk_product_style_revisions_source_import",
        "product_style_revisions",
        ["source_import_id"],
        "catalog_imports",
        ["id"],
    ),
    (
        "fk_product_sku_revisions_source_import",
        "product_sku_revisions",
        ["source_import_id"],
        "catalog_imports",
        ["id"],
    ),
    (
        "fk_product_catalog_versions_source_import",
        "product_catalog_versions",
        ["source_import_id"],
        "catalog_imports",
        ["id"],
    ),
    (
        "fk_product_catalog_versions_validation",
        "product_catalog_versions",
        ["validation_run_id"],
        "catalog_validation_runs",
        ["id"],
    ),
    (
        "fk_catalog_imports_validation",
        "catalog_imports",
        ["validation_run_id"],
        "catalog_validation_runs",
        ["id"],
    ),
)


def _ensure_late_foreign_keys() -> None:
    existing = frozenset(
        str(value)
        for value in op.get_bind().scalars(
            sa.text(
                """
                SELECT constraint_name
                FROM information_schema.table_constraints
                WHERE constraint_schema = DATABASE()
                  AND constraint_type = 'FOREIGN KEY'
                  AND constraint_name IN :constraint_names
                """
            ).bindparams(sa.bindparam("constraint_names", expanding=True)),
            {"constraint_names": tuple(item[0] for item in _LATE_FOREIGN_KEYS)},
        )
    )
    for (
        name,
        source_table,
        local_columns,
        target_table,
        remote_columns,
    ) in _LATE_FOREIGN_KEYS:
        if name in existing:
            continue
        op.create_foreign_key(
            name,
            source_table,
            target_table,
            local_columns,
            remote_columns,
            ondelete="RESTRICT",
            onupdate="RESTRICT",
        )
        _seal_table_signature(source_table)


def _drop_late_foreign_keys() -> None:
    for name, source_table, *_unused in reversed(_LATE_FOREIGN_KEYS):
        op.drop_constraint(name, source_table, type_="foreignkey")


def _if_missing(
    existing: frozenset[str], table_name: str, creator: Callable[[], None]
) -> None:
    if table_name not in existing:
        creator()
        _seal_table_signature(table_name)


def _ensure_version_rows_analytics_index() -> None:
    index_name = "ix_version_rows_analytics_active"
    rows = tuple(
        op.get_bind().execute(
            sa.text(
                """
                SELECT non_unique, seq_in_index, column_name
                FROM information_schema.statistics
                WHERE table_schema = DATABASE()
                  AND table_name = 'version_rows'
                  AND index_name = :index_name
                ORDER BY seq_in_index
                """
            ),
            {"index_name": index_name},
        )
    )
    if not rows:
        op.create_index(
            index_name,
            "version_rows",
            ["version_id", "row_state", "id"],
        )
        return
    signature = tuple((int(row[0]), int(row[1]), str(row[2])) for row in rows)
    if signature != (
        (1, 1, "version_id"),
        (1, 2, "row_state"),
        (1, 3, "id"),
    ):
        raise RuntimeError("incompatible version_rows analytics index")


def upgrade() -> None:
    _assert_trigger_creation_policy()
    existing = _assert_recoverable_partial_upgrade()
    _ensure_version_rows_analytics_index()

    def create_report_source_scopes() -> None:
        op.create_table(
            "report_source_scopes",
            sa.Column("id", _id_type(), autoincrement=True, nullable=False),
            sa.Column("site_id", _id_type(), nullable=False),
            sa.Column("seller_account_scope_key", mysql.BINARY(32), nullable=False),
            sa.Column("seller_account_display_name", sa.String(128), nullable=False),
            sa.Column("marketplace_scope_code", _code_type(32), nullable=False),
            sa.Column("confirmed_by_user_id", _id_type(), nullable=False),
            sa.Column("confirmed_at", _timestamp_type(), nullable=False),
            _created_at(),
            sa.PrimaryKeyConstraint("id", name="pk_report_source_scopes"),
            sa.UniqueConstraint("site_id", name="uq_report_source_scopes_site"),
            sa.UniqueConstraint(
                "id", "site_id", name="uq_report_source_scopes_id_site"
            ),
            sa.ForeignKeyConstraint(
                ["site_id"],
                ["sites.id"],
                name="fk_report_source_scopes_site",
                ondelete="RESTRICT",
                onupdate="RESTRICT",
            ),
            sa.ForeignKeyConstraint(
                ["confirmed_by_user_id"],
                ["users.id"],
                name="fk_report_source_scopes_confirmer",
                ondelete="RESTRICT",
                onupdate="RESTRICT",
            ),
            sa.CheckConstraint(
                "marketplace_scope_code = 'amazon_us'",
                name="ck_report_source_scopes_marketplace",
            ),
            **_TABLE_OPTIONS,
        )

    _if_missing(existing, "report_source_scopes", create_report_source_scopes)

    def create_report_dataset_scope_assignments() -> None:
        op.create_table(
            "report_dataset_scope_assignments",
            sa.Column("id", _id_type(), autoincrement=True, nullable=False),
            sa.Column("dataset_id", _id_type(), nullable=False),
            sa.Column("site_id", _id_type(), nullable=False),
            sa.Column("report_source_scope_id", _id_type(), nullable=False),
            sa.Column("assigned_at", _timestamp_type(), nullable=False),
            sa.PrimaryKeyConstraint("id", name="pk_report_dataset_scope_assignments"),
            sa.UniqueConstraint(
                "dataset_id", name="uq_report_dataset_scope_assignments_dataset"
            ),
            sa.UniqueConstraint(
                "dataset_id",
                "site_id",
                "report_source_scope_id",
                name="uq_report_dataset_scope_assignments_identity",
            ),
            sa.ForeignKeyConstraint(
                ["dataset_id"],
                ["daily_datasets.id"],
                name="fk_report_dataset_scope_assignments_dataset",
                ondelete="RESTRICT",
                onupdate="RESTRICT",
            ),
            sa.ForeignKeyConstraint(
                ["report_source_scope_id", "site_id"],
                ["report_source_scopes.id", "report_source_scopes.site_id"],
                name="fk_report_dataset_scope_assignments_scope",
                ondelete="RESTRICT",
                onupdate="RESTRICT",
            ),
            sa.Index(
                "ix_report_dataset_scope_assignments_scope_dataset",
                "report_source_scope_id",
                "dataset_id",
            ),
            **_TABLE_OPTIONS,
        )

    _if_missing(
        existing,
        "report_dataset_scope_assignments",
        create_report_dataset_scope_assignments,
    )

    def create_report_source_keys() -> None:
        op.create_table(
            "report_source_keys",
            sa.Column("id", _id_type(), autoincrement=True, nullable=False),
            sa.Column("dataset_id", _id_type(), nullable=False),
            sa.Column("version_id", _id_type(), nullable=False),
            sa.Column("source_row_id", _id_type(), nullable=False),
            sa.Column("site_id", _id_type(), nullable=False),
            sa.Column("report_source_scope_id", _id_type(), nullable=False),
            sa.Column("report_type", _code_type(24), nullable=False),
            sa.Column(
                "source_key_revision", mysql.BIGINT(unsigned=True), nullable=False
            ),
            sa.Column("seller_sku_raw_sha256", mysql.BINARY(32), nullable=False),
            sa.Column("seller_sku_match_sha256", mysql.BINARY(32), nullable=False),
            sa.Column(
                "seller_sku_match_bytes", _binary_text_type(1020), nullable=False
            ),
            sa.Column("normalization_version", _code_type(64), nullable=False),
            sa.Column("collision_group_sha256", mysql.BINARY(32), nullable=True),
            _created_at(),
            sa.PrimaryKeyConstraint("id", name="pk_report_source_keys"),
            sa.UniqueConstraint(
                "version_id",
                "source_row_id",
                "source_key_revision",
                name="uq_report_source_keys_row_revision",
            ),
            sa.UniqueConstraint(
                "id",
                "site_id",
                "report_source_scope_id",
                name="uq_report_source_keys_scope",
            ),
            sa.ForeignKeyConstraint(
                ["dataset_id"],
                ["daily_datasets.id"],
                name="fk_report_source_keys_dataset",
                ondelete="RESTRICT",
                onupdate="RESTRICT",
            ),
            sa.ForeignKeyConstraint(
                ["version_id"],
                ["dataset_versions.id"],
                name="fk_report_source_keys_version",
                ondelete="RESTRICT",
                onupdate="RESTRICT",
            ),
            sa.ForeignKeyConstraint(
                ["report_source_scope_id", "site_id"],
                ["report_source_scopes.id", "report_source_scopes.site_id"],
                name="fk_report_source_keys_scope",
                ondelete="RESTRICT",
                onupdate="RESTRICT",
            ),
            sa.CheckConstraint(
                "report_type IN ('business_report','return_report')",
                name="ck_report_source_keys_report_type",
            ),
            sa.CheckConstraint(
                "normalization_version = 'seller_sku_match_v1'",
                name="ck_report_source_keys_normalization",
            ),
            sa.Index(
                "ix_report_source_keys_scope_match",
                "report_source_scope_id",
                "seller_sku_match_sha256",
                "id",
            ),
            sa.Index(
                "ix_report_source_keys_dataset_version",
                "dataset_id",
                "version_id",
                "id",
            ),
            **_TABLE_OPTIONS,
        )

    _if_missing(existing, "report_source_keys", create_report_source_keys)

    def create_report_publication_revisions() -> None:
        op.create_table(
            "report_publication_revisions",
            sa.Column("dataset_id", _id_type(), nullable=False),
            sa.Column("site_id", _id_type(), nullable=False),
            sa.Column("report_source_scope_id", _id_type(), nullable=False),
            sa.Column(
                "publication_revision",
                _counter_type(),
                server_default=sa.text("0"),
                nullable=False,
            ),
            _updated_at(),
            sa.PrimaryKeyConstraint(
                "dataset_id", name="pk_report_publication_revisions"
            ),
            sa.ForeignKeyConstraint(
                ["dataset_id", "site_id", "report_source_scope_id"],
                [
                    "report_dataset_scope_assignments.dataset_id",
                    "report_dataset_scope_assignments.site_id",
                    "report_dataset_scope_assignments.report_source_scope_id",
                ],
                name="fk_report_publication_revisions_assignment",
                ondelete="RESTRICT",
                onupdate="RESTRICT",
            ),
            sa.Index(
                "ix_report_publication_revisions_scope_dataset",
                "report_source_scope_id",
                "dataset_id",
            ),
            **_TABLE_OPTIONS,
        )

    _if_missing(
        existing,
        "report_publication_revisions",
        create_report_publication_revisions,
    )

    def create_publication_snapshots() -> None:
        op.create_table(
            "publication_snapshots",
            sa.Column("id", _id_type(), autoincrement=True, nullable=False),
            sa.Column("site_id", _id_type(), nullable=False),
            sa.Column("report_source_scope_id", _id_type(), nullable=False),
            sa.Column("site_config_version_id", _id_type(), nullable=False),
            sa.Column("candidate_rule_version", _code_type(64), nullable=False),
            sa.Column("normalization_manifest_id", _code_type(64), nullable=False),
            sa.Column("coverage_start_date", sa.Date(), nullable=False),
            sa.Column("coverage_end_date", sa.Date(), nullable=False),
            sa.Column("transaction_started_at", _timestamp_type(), nullable=False),
            sa.Column("fact_cutoff_at", _timestamp_type(), nullable=False),
            sa.Column(
                "return_publication_set_digest", mysql.BINARY(32), nullable=False
            ),
            sa.Column("status", _code_type(16), nullable=False),
            sa.Column("snapshot_digest", mysql.BINARY(32), nullable=False),
            _created_at(),
            sa.PrimaryKeyConstraint("id", name="pk_publication_snapshots"),
            sa.UniqueConstraint(
                "id", "site_id", name="uq_publication_snapshots_id_site"
            ),
            sa.UniqueConstraint(
                "id",
                "site_id",
                "report_source_scope_id",
                "site_config_version_id",
                "return_publication_set_digest",
                "status",
                name="uq_publication_snapshots_fact_identity",
            ),
            sa.ForeignKeyConstraint(
                ["report_source_scope_id", "site_id"],
                ["report_source_scopes.id", "report_source_scopes.site_id"],
                name="fk_publication_snapshots_scope",
                ondelete="RESTRICT",
                onupdate="RESTRICT",
            ),
            sa.ForeignKeyConstraint(
                ["site_config_version_id"],
                ["site_config_versions.id"],
                name="fk_publication_snapshots_site_config",
                ondelete="RESTRICT",
                onupdate="RESTRICT",
            ),
            sa.CheckConstraint(
                "coverage_start_date <= coverage_end_date",
                name="ck_publication_snapshots_coverage",
            ),
            sa.CheckConstraint(
                "fact_cutoff_at >= transaction_started_at",
                name="ck_publication_snapshots_cutoff",
            ),
            sa.CheckConstraint(
                "status IN ('building','ready','failed')",
                name="ck_publication_snapshots_status",
            ),
            sa.Index(
                "ix_publication_snapshots_scope_cutoff",
                "report_source_scope_id",
                "fact_cutoff_at",
                "id",
            ),
            **_TABLE_OPTIONS,
        )

    _if_missing(existing, "publication_snapshots", create_publication_snapshots)

    def create_publication_snapshot_members() -> None:
        op.create_table(
            "publication_snapshot_members",
            sa.Column("id", _id_type(), autoincrement=True, nullable=False),
            sa.Column("publication_snapshot_id", _id_type(), nullable=False),
            sa.Column("site_id", _id_type(), nullable=False),
            sa.Column("report_type", _code_type(24), nullable=False),
            sa.Column("report_date", sa.Date(), nullable=False),
            sa.Column("dataset_id", _id_type(), nullable=True),
            sa.Column("published_version_id", _id_type(), nullable=True),
            sa.Column("publication_pointer_revision", _counter_type(), nullable=False),
            sa.Column("member_status", _code_type(16), nullable=False),
            sa.Column("active_row_count", _counter_type(), nullable=False),
            sa.Column("active_row_projection_digest", mysql.BINARY(32), nullable=False),
            _created_at(),
            sa.PrimaryKeyConstraint("id", name="pk_publication_snapshot_members"),
            sa.UniqueConstraint(
                "publication_snapshot_id",
                "report_type",
                "report_date",
                name="uq_publication_snapshot_members_day",
            ),
            sa.ForeignKeyConstraint(
                ["publication_snapshot_id", "site_id"],
                ["publication_snapshots.id", "publication_snapshots.site_id"],
                name="fk_publication_snapshot_members_snapshot",
                ondelete="RESTRICT",
                onupdate="RESTRICT",
            ),
            sa.ForeignKeyConstraint(
                ["dataset_id"],
                ["daily_datasets.id"],
                name="fk_publication_snapshot_members_dataset",
                ondelete="RESTRICT",
                onupdate="RESTRICT",
            ),
            sa.ForeignKeyConstraint(
                ["published_version_id"],
                ["dataset_versions.id"],
                name="fk_publication_snapshot_members_version",
                ondelete="RESTRICT",
                onupdate="RESTRICT",
            ),
            sa.CheckConstraint(
                "report_type IN ('business_report','return_report')",
                name="ck_publication_snapshot_members_report_type",
            ),
            sa.CheckConstraint(
                "member_status IN ('published','missing')",
                name="ck_publication_snapshot_members_status",
            ),
            sa.CheckConstraint(
                "((member_status='published' AND dataset_id IS NOT NULL "
                "AND published_version_id IS NOT NULL) OR "
                "(member_status='missing' AND dataset_id IS NULL "
                "AND published_version_id IS NULL AND active_row_count=0))",
                name="ck_publication_snapshot_members_identity",
            ),
            sa.Index(
                "ix_publication_snapshot_members_lookup",
                "publication_snapshot_id",
                "report_date",
                "report_type",
            ),
            **_TABLE_OPTIONS,
        )

    _if_missing(
        existing, "publication_snapshot_members", create_publication_snapshot_members
    )

    def create_return_dedup_group_revisions() -> None:
        op.create_table(
            "return_dedup_group_revisions",
            sa.Column("id", _id_type(), autoincrement=True, nullable=False),
            sa.Column("site_id", _id_type(), nullable=False),
            sa.Column("report_source_scope_id", _id_type(), nullable=False),
            sa.Column("group_key_sha256", mysql.BINARY(32), nullable=False),
            sa.Column("revision", _counter_type(), nullable=False),
            sa.Column("member_set_digest", mysql.BINARY(32), nullable=False),
            sa.Column("decision", _code_type(24), nullable=False),
            sa.Column("canonical_source_key_id", _id_type(), nullable=True),
            sa.Column("reason_code", _code_type(64), nullable=True),
            sa.Column("decided_by_user_id", _id_type(), nullable=True),
            _created_at(),
            sa.PrimaryKeyConstraint("id", name="pk_return_dedup_group_revisions"),
            sa.UniqueConstraint(
                "site_id",
                "report_source_scope_id",
                "group_key_sha256",
                "revision",
                name="uq_return_dedup_group_revisions_key",
            ),
            sa.UniqueConstraint(
                "id",
                "site_id",
                "report_source_scope_id",
                name="uq_return_dedup_group_revisions_scope",
            ),
            sa.ForeignKeyConstraint(
                ["report_source_scope_id", "site_id"],
                ["report_source_scopes.id", "report_source_scopes.site_id"],
                name="fk_return_dedup_group_revisions_scope",
                ondelete="RESTRICT",
                onupdate="RESTRICT",
            ),
            sa.ForeignKeyConstraint(
                ["canonical_source_key_id", "site_id", "report_source_scope_id"],
                [
                    "report_source_keys.id",
                    "report_source_keys.site_id",
                    "report_source_keys.report_source_scope_id",
                ],
                name="fk_return_dedup_group_revisions_canonical",
                ondelete="RESTRICT",
                onupdate="RESTRICT",
            ),
            sa.ForeignKeyConstraint(
                ["decided_by_user_id"],
                ["users.id"],
                name="fk_return_dedup_group_revisions_actor",
                ondelete="RESTRICT",
                onupdate="RESTRICT",
            ),
            sa.CheckConstraint(
                "revision >= 1", name="ck_return_dedup_group_revisions_revision"
            ),
            sa.CheckConstraint(
                "decision IN ('unresolved','confirmed_distinct','duplicate_of')",
                name="ck_return_dedup_group_revisions_decision",
            ),
            sa.CheckConstraint(
                "((decision='duplicate_of' "
                "AND canonical_source_key_id IS NOT NULL) OR "
                "(decision<>'duplicate_of' "
                "AND canonical_source_key_id IS NULL))",
                name="ck_return_dedup_group_revisions_canonical",
            ),
            sa.Index(
                "ix_return_dedup_group_revisions_scope_group",
                "report_source_scope_id",
                "group_key_sha256",
                "revision",
            ),
            **_TABLE_OPTIONS,
        )

    _if_missing(
        existing, "return_dedup_group_revisions", create_return_dedup_group_revisions
    )

    def create_return_dedup_group_members() -> None:
        op.create_table(
            "return_dedup_group_members",
            sa.Column("id", _id_type(), autoincrement=True, nullable=False),
            sa.Column("group_revision_id", _id_type(), nullable=False),
            sa.Column("source_key_id", _id_type(), nullable=False),
            sa.Column("member_order", _counter_type(), nullable=False),
            _created_at(),
            sa.PrimaryKeyConstraint("id", name="pk_return_dedup_group_members"),
            sa.UniqueConstraint(
                "group_revision_id",
                "source_key_id",
                name="uq_return_dedup_group_members_member",
            ),
            sa.UniqueConstraint(
                "group_revision_id",
                "member_order",
                name="uq_return_dedup_group_members_order",
            ),
            sa.ForeignKeyConstraint(
                ["group_revision_id"],
                ["return_dedup_group_revisions.id"],
                name="fk_return_dedup_group_members_group",
                ondelete="RESTRICT",
                onupdate="RESTRICT",
            ),
            sa.ForeignKeyConstraint(
                ["source_key_id"],
                ["report_source_keys.id"],
                name="fk_return_dedup_group_members_source",
                ondelete="RESTRICT",
                onupdate="RESTRICT",
            ),
            sa.Index(
                "ix_return_dedup_group_members_source",
                "source_key_id",
                "group_revision_id",
            ),
            **_TABLE_OPTIONS,
        )

    _if_missing(
        existing, "return_dedup_group_members", create_return_dedup_group_members
    )

    def create_return_dedup_snapshots() -> None:
        op.create_table(
            "return_dedup_snapshots",
            sa.Column("id", _id_type(), autoincrement=True, nullable=False),
            sa.Column("site_id", _id_type(), nullable=False),
            sa.Column("report_source_scope_id", _id_type(), nullable=False),
            sa.Column(
                "return_publication_set_digest", mysql.BINARY(32), nullable=False
            ),
            sa.Column("rule_version", _code_type(64), nullable=False),
            sa.Column("base_snapshot_id", _id_type(), nullable=True),
            sa.Column("checkpoint_snapshot_id", _id_type(), nullable=True),
            sa.Column("delta_depth", mysql.SMALLINT(unsigned=True), nullable=False),
            sa.Column("snapshot_kind", _code_type(16), nullable=False),
            sa.Column("status", _code_type(16), nullable=False),
            sa.Column("decision_digest", mysql.BINARY(32), nullable=False),
            _created_at(),
            sa.PrimaryKeyConstraint("id", name="pk_return_dedup_snapshots"),
            sa.UniqueConstraint(
                "id",
                "site_id",
                "report_source_scope_id",
                name="uq_return_dedup_snapshots_scope",
            ),
            sa.UniqueConstraint(
                "id",
                "site_id",
                "report_source_scope_id",
                "return_publication_set_digest",
                "status",
                name="uq_return_dedup_snapshots_fact_identity",
            ),
            sa.ForeignKeyConstraint(
                ["report_source_scope_id", "site_id"],
                ["report_source_scopes.id", "report_source_scopes.site_id"],
                name="fk_return_dedup_snapshots_scope",
                ondelete="RESTRICT",
                onupdate="RESTRICT",
            ),
            sa.ForeignKeyConstraint(
                ["base_snapshot_id"],
                ["return_dedup_snapshots.id"],
                name="fk_return_dedup_snapshots_base",
                ondelete="RESTRICT",
                onupdate="RESTRICT",
            ),
            sa.ForeignKeyConstraint(
                ["checkpoint_snapshot_id"],
                ["return_dedup_snapshots.id"],
                name="fk_return_dedup_snapshots_checkpoint",
                ondelete="RESTRICT",
                onupdate="RESTRICT",
            ),
            sa.CheckConstraint(
                "delta_depth <= 32", name="ck_return_dedup_snapshots_depth"
            ),
            sa.CheckConstraint(
                "snapshot_kind IN ('checkpoint','delta')",
                name="ck_return_dedup_snapshots_kind",
            ),
            sa.CheckConstraint(
                "status IN ('building','ready','failed','superseded')",
                name="ck_return_dedup_snapshots_status",
            ),
            sa.CheckConstraint(
                "((snapshot_kind='checkpoint' AND base_snapshot_id IS NULL "
                "AND checkpoint_snapshot_id IS NULL AND delta_depth=0) OR "
                "(snapshot_kind='delta' AND base_snapshot_id IS NOT NULL "
                "AND checkpoint_snapshot_id IS NOT NULL "
                "AND delta_depth BETWEEN 1 AND 32))",
                name="ck_return_dedup_snapshots_lineage",
            ),
            sa.Index(
                "ix_return_dedup_snapshots_scope_publication",
                "report_source_scope_id",
                "return_publication_set_digest",
                "status",
                "id",
            ),
            **_TABLE_OPTIONS,
        )

    _if_missing(existing, "return_dedup_snapshots", create_return_dedup_snapshots)

    def create_return_dedup_snapshot_groups() -> None:
        op.create_table(
            "return_dedup_snapshot_groups",
            sa.Column("id", _id_type(), autoincrement=True, nullable=False),
            sa.Column("snapshot_id", _id_type(), nullable=False),
            sa.Column("group_revision_id", _id_type(), nullable=False),
            sa.Column("entry_kind", _code_type(16), nullable=False),
            _created_at(),
            sa.PrimaryKeyConstraint("id", name="pk_return_dedup_snapshot_groups"),
            sa.UniqueConstraint(
                "snapshot_id",
                "group_revision_id",
                name="uq_return_dedup_snapshot_groups_member",
            ),
            sa.ForeignKeyConstraint(
                ["snapshot_id"],
                ["return_dedup_snapshots.id"],
                name="fk_return_dedup_snapshot_groups_snapshot",
                ondelete="RESTRICT",
                onupdate="RESTRICT",
            ),
            sa.ForeignKeyConstraint(
                ["group_revision_id"],
                ["return_dedup_group_revisions.id"],
                name="fk_return_dedup_snapshot_groups_group",
                ondelete="RESTRICT",
                onupdate="RESTRICT",
            ),
            sa.CheckConstraint(
                "entry_kind IN ('checkpoint','upsert','remove')",
                name="ck_return_dedup_snapshot_groups_kind",
            ),
            sa.Index("ix_return_dedup_snapshot_groups_snapshot", "snapshot_id", "id"),
            **_TABLE_OPTIONS,
        )

    _if_missing(
        existing, "return_dedup_snapshot_groups", create_return_dedup_snapshot_groups
    )

    def create_return_dedup_publications() -> None:
        op.create_table(
            "return_dedup_publications",
            sa.Column("site_id", _id_type(), nullable=False),
            sa.Column("report_source_scope_id", _id_type(), nullable=False),
            sa.Column("current_snapshot_id", _id_type(), nullable=True),
            sa.Column(
                "dedup_publication_revision",
                _counter_type(),
                server_default=sa.text("0"),
                nullable=False,
            ),
            _updated_at(),
            sa.PrimaryKeyConstraint("site_id", name="pk_return_dedup_publications"),
            sa.UniqueConstraint(
                "report_source_scope_id", name="uq_return_dedup_publications_scope"
            ),
            sa.ForeignKeyConstraint(
                ["report_source_scope_id", "site_id"],
                ["report_source_scopes.id", "report_source_scopes.site_id"],
                name="fk_return_dedup_publications_scope",
                ondelete="RESTRICT",
                onupdate="RESTRICT",
            ),
            sa.ForeignKeyConstraint(
                ["current_snapshot_id", "site_id", "report_source_scope_id"],
                [
                    "return_dedup_snapshots.id",
                    "return_dedup_snapshots.site_id",
                    "return_dedup_snapshots.report_source_scope_id",
                ],
                name="fk_return_dedup_publications_snapshot",
                ondelete="RESTRICT",
                onupdate="RESTRICT",
            ),
            **_TABLE_OPTIONS,
        )

    _if_missing(existing, "return_dedup_publications", create_return_dedup_publications)

    def create_return_dedup_staging_jobs() -> None:
        op.create_table(
            "return_dedup_staging_jobs",
            sa.Column("id", _id_type(), autoincrement=True, nullable=False),
            sa.Column("site_id", _id_type(), nullable=False),
            sa.Column("report_source_scope_id", _id_type(), nullable=False),
            sa.Column("operation_token", mysql.BINARY(16), nullable=False),
            sa.Column("operation_digest", mysql.BINARY(32), nullable=False),
            sa.Column("retry_operation_token", mysql.BINARY(16), nullable=True),
            sa.Column("retry_operation_digest", mysql.BINARY(32), nullable=True),
            sa.Column("actor_user_id", _id_type(), nullable=False),
            sa.Column("dataset_id", _id_type(), nullable=False),
            sa.Column("proposed_version_id", _id_type(), nullable=False),
            sa.Column("proposed_set_digest", mysql.BINARY(32), nullable=False),
            sa.Column("rule_version", _code_type(64), nullable=False),
            sa.Column("expected_publication_revision", _counter_type(), nullable=False),
            sa.Column(
                "expected_dedup_publication_revision", _counter_type(), nullable=False
            ),
            sa.Column("status", _code_type(16), nullable=False),
            sa.Column(
                "job_revision",
                _counter_type(),
                server_default=sa.text("0"),
                nullable=False,
            ),
            sa.Column(
                "retry_allowed", sa.Boolean(), server_default=sa.false(), nullable=False
            ),
            sa.Column("failure_reason_code", _code_type(64), nullable=True),
            sa.Column("lease_token", mysql.BINARY(16), nullable=True),
            sa.Column(
                "fencing_token",
                _counter_type(),
                server_default=sa.text("0"),
                nullable=False,
            ),
            sa.Column("lease_expires_at", _timestamp_type(), nullable=True),
            sa.Column("result_snapshot_id", _id_type(), nullable=True),
            _created_at(),
            _updated_at(),
            sa.PrimaryKeyConstraint("id", name="pk_return_dedup_staging_jobs"),
            sa.UniqueConstraint(
                "site_id",
                "proposed_set_digest",
                name="uq_return_dedup_staging_jobs_set",
            ),
            sa.UniqueConstraint(
                "operation_token",
                name="uq_return_dedup_staging_jobs_operation",
            ),
            sa.UniqueConstraint(
                "retry_operation_token",
                name="uq_return_dedup_staging_jobs_retry_operation",
            ),
            sa.ForeignKeyConstraint(
                ["report_source_scope_id", "site_id"],
                ["report_source_scopes.id", "report_source_scopes.site_id"],
                name="fk_return_dedup_staging_jobs_scope",
                ondelete="RESTRICT",
                onupdate="RESTRICT",
            ),
            sa.ForeignKeyConstraint(
                ["dataset_id"],
                ["daily_datasets.id"],
                name="fk_return_dedup_staging_jobs_dataset",
                ondelete="RESTRICT",
                onupdate="RESTRICT",
            ),
            sa.ForeignKeyConstraint(
                ["actor_user_id"],
                ["users.id"],
                name="fk_return_dedup_staging_jobs_actor",
                ondelete="RESTRICT",
                onupdate="RESTRICT",
            ),
            sa.ForeignKeyConstraint(
                ["proposed_version_id"],
                ["dataset_versions.id"],
                name="fk_return_dedup_staging_jobs_version",
                ondelete="RESTRICT",
                onupdate="RESTRICT",
            ),
            sa.ForeignKeyConstraint(
                ["result_snapshot_id"],
                ["return_dedup_snapshots.id"],
                name="fk_return_dedup_staging_jobs_result",
                ondelete="RESTRICT",
                onupdate="RESTRICT",
            ),
            sa.CheckConstraint(
                "status IN ('building','ready','failed','superseded')",
                name="ck_return_dedup_staging_jobs_status",
            ),
            sa.CheckConstraint(
                "(lease_token IS NULL) = (lease_expires_at IS NULL)",
                name="ck_return_dedup_staging_jobs_lease",
            ),
            sa.CheckConstraint(
                "NOT retry_allowed OR status='failed'",
                name="ck_return_dedup_staging_jobs_retry",
            ),
            sa.CheckConstraint(
                "(retry_operation_token IS NULL) = (retry_operation_digest IS NULL)",
                name="ck_return_dedup_staging_jobs_retry_operation",
            ),
            sa.CheckConstraint(
                "rule_version = 'return_event_fingerprint_v1'",
                name="ck_return_dedup_staging_jobs_rule",
            ),
            sa.Index(
                "ix_return_dedup_staging_jobs_status",
                "status",
                "lease_expires_at",
                "id",
            ),
            **_TABLE_OPTIONS,
        )

    _if_missing(existing, "return_dedup_staging_jobs", create_return_dedup_staging_jobs)

    def create_return_dedup_staging_members() -> None:
        op.create_table(
            "return_dedup_staging_members",
            sa.Column("id", _id_type(), autoincrement=True, nullable=False),
            sa.Column("job_id", _id_type(), nullable=False),
            sa.Column("dataset_id", _id_type(), nullable=False),
            sa.Column("published_version_id", _id_type(), nullable=False),
            sa.Column("publication_revision", _counter_type(), nullable=False),
            sa.Column("version_data_revision", _counter_type(), nullable=False),
            sa.Column("report_date", sa.Date(), nullable=False),
            sa.Column("member_order", _counter_type(), nullable=False),
            _created_at(),
            sa.PrimaryKeyConstraint("id", name="pk_return_dedup_staging_members"),
            sa.UniqueConstraint(
                "job_id",
                "dataset_id",
                name="uq_return_dedup_staging_members_dataset",
            ),
            sa.UniqueConstraint(
                "job_id",
                "member_order",
                name="uq_return_dedup_staging_members_order",
            ),
            sa.ForeignKeyConstraint(
                ["job_id"],
                ["return_dedup_staging_jobs.id"],
                name="fk_return_dedup_staging_members_job",
                ondelete="RESTRICT",
                onupdate="RESTRICT",
            ),
            sa.ForeignKeyConstraint(
                ["dataset_id"],
                ["daily_datasets.id"],
                name="fk_return_dedup_staging_members_dataset",
                ondelete="RESTRICT",
                onupdate="RESTRICT",
            ),
            sa.ForeignKeyConstraint(
                ["published_version_id"],
                ["dataset_versions.id"],
                name="fk_return_dedup_staging_members_version",
                ondelete="RESTRICT",
                onupdate="RESTRICT",
            ),
            sa.Index(
                "ix_return_dedup_staging_members_job_order",
                "job_id",
                "member_order",
            ),
            **_TABLE_OPTIONS,
        )

    _if_missing(
        existing,
        "return_dedup_staging_members",
        create_return_dedup_staging_members,
    )

    def create_fact_snapshot_tuples() -> None:
        op.create_table(
            "fact_snapshot_tuples",
            sa.Column("id", _id_type(), autoincrement=True, nullable=False),
            sa.Column("site_id", _id_type(), nullable=False),
            sa.Column("report_source_scope_id", _id_type(), nullable=False),
            sa.Column("publication_snapshot_id", _id_type(), nullable=False),
            sa.Column("return_dedup_snapshot_id", _id_type(), nullable=False),
            sa.Column(
                "return_dedup_snapshot_status",
                _code_type(16),
                server_default=sa.text("'ready'"),
                nullable=False,
            ),
            sa.Column("site_config_version_id", _id_type(), nullable=False),
            sa.Column("fact_cutoff_at", _timestamp_type(), nullable=False),
            sa.Column(
                "return_publication_set_digest", mysql.BINARY(32), nullable=False
            ),
            sa.Column("tuple_digest", mysql.BINARY(32), nullable=False),
            sa.Column("status", _code_type(16), nullable=False),
            _created_at(),
            sa.PrimaryKeyConstraint("id", name="pk_fact_snapshot_tuples"),
            sa.UniqueConstraint("tuple_digest", name="uq_fact_snapshot_tuples_digest"),
            sa.UniqueConstraint(
                "id", "site_id", name="uq_fact_snapshot_tuples_id_site"
            ),
            sa.UniqueConstraint(
                "id", "site_id", "status", name="uq_fact_snapshot_tuples_catalog_ref"
            ),
            sa.ForeignKeyConstraint(
                [
                    "publication_snapshot_id",
                    "site_id",
                    "report_source_scope_id",
                    "site_config_version_id",
                    "return_publication_set_digest",
                    "status",
                ],
                [
                    "publication_snapshots.id",
                    "publication_snapshots.site_id",
                    "publication_snapshots.report_source_scope_id",
                    "publication_snapshots.site_config_version_id",
                    "publication_snapshots.return_publication_set_digest",
                    "publication_snapshots.status",
                ],
                name="fk_fact_snapshot_tuples_publication",
                ondelete="RESTRICT",
                onupdate="CASCADE",
            ),
            sa.ForeignKeyConstraint(
                [
                    "return_dedup_snapshot_id",
                    "site_id",
                    "report_source_scope_id",
                    "return_publication_set_digest",
                    "return_dedup_snapshot_status",
                ],
                [
                    "return_dedup_snapshots.id",
                    "return_dedup_snapshots.site_id",
                    "return_dedup_snapshots.report_source_scope_id",
                    "return_dedup_snapshots.return_publication_set_digest",
                    "return_dedup_snapshots.status",
                ],
                name="fk_fact_snapshot_tuples_dedup",
                ondelete="RESTRICT",
                onupdate="RESTRICT",
            ),
            sa.ForeignKeyConstraint(
                ["site_config_version_id"],
                ["site_config_versions.id"],
                name="fk_fact_snapshot_tuples_site_config",
                ondelete="RESTRICT",
                onupdate="RESTRICT",
            ),
            # ``status`` is constrained by the composite FK to the checked
            # publication snapshot status.  MySQL rejects a redundant local
            # CHECK on a column participating in ON UPDATE CASCADE.
            sa.CheckConstraint(
                "return_dedup_snapshot_status='ready'",
                name="ck_fact_snapshot_tuples_dedup_status",
            ),
            sa.Index(
                "ix_fact_snapshot_tuples_scope_cutoff",
                "report_source_scope_id",
                "fact_cutoff_at",
                "id",
            ),
            **_TABLE_OPTIONS,
        )

    _if_missing(existing, "fact_snapshot_tuples", create_fact_snapshot_tuples)

    def create_product_styles() -> None:
        op.create_table(
            "product_styles",
            sa.Column("id", _id_type(), autoincrement=True, nullable=False),
            sa.Column("site_id", _id_type(), nullable=False),
            sa.Column("style_code", sa.String(128), nullable=False),
            sa.Column("style_key_sha256", mysql.BINARY(32), nullable=False),
            sa.Column("style_key_bytes", _binary_text_type(512), nullable=False),
            sa.Column("standard_name", sa.String(255), nullable=False),
            sa.Column("status", _code_type(16), nullable=False),
            sa.Column("current_revision", _counter_type(), nullable=False),
            _created_at(),
            _updated_at(),
            sa.PrimaryKeyConstraint("id", name="pk_product_styles"),
            sa.UniqueConstraint("id", "site_id", name="uq_product_styles_id_site"),
            sa.UniqueConstraint(
                "site_id",
                "style_key_sha256",
                "style_key_bytes",
                name="uq_product_styles_identity",
            ),
            sa.ForeignKeyConstraint(
                ["site_id"],
                ["sites.id"],
                name="fk_product_styles_site",
                ondelete="RESTRICT",
                onupdate="RESTRICT",
            ),
            sa.CheckConstraint(
                "status IN ('enabled','disabled')", name="ck_product_styles_status"
            ),
            sa.CheckConstraint(
                "current_revision >= 1", name="ck_product_styles_revision"
            ),
            sa.Index("ix_product_styles_site_status", "site_id", "status", "id"),
            **_TABLE_OPTIONS,
        )

    _if_missing(existing, "product_styles", create_product_styles)

    def create_product_style_revisions() -> None:
        op.create_table(
            "product_style_revisions",
            sa.Column("id", _id_type(), autoincrement=True, nullable=False),
            sa.Column("site_id", _id_type(), nullable=False),
            sa.Column("style_id", _id_type(), nullable=False),
            sa.Column("revision", _counter_type(), nullable=False),
            sa.Column("style_code", sa.String(128), nullable=False),
            sa.Column("style_key_sha256", mysql.BINARY(32), nullable=False),
            sa.Column("style_key_bytes", _binary_text_type(512), nullable=False),
            sa.Column("standard_name", sa.String(255), nullable=False),
            sa.Column("status", _code_type(16), nullable=False),
            sa.Column("change_reason", sa.String(500), nullable=False),
            sa.Column("actor_user_id", _id_type(), nullable=False),
            sa.Column("source_import_id", _id_type(), nullable=True),
            sa.Column("source_command_token", mysql.BINARY(16), nullable=False),
            _created_at(),
            sa.PrimaryKeyConstraint("id", name="pk_product_style_revisions"),
            sa.UniqueConstraint(
                "site_id",
                "style_id",
                "revision",
                name="uq_product_style_revisions_number",
            ),
            sa.UniqueConstraint(
                "id", "site_id", "style_id", name="uq_product_style_revisions_member"
            ),
            sa.ForeignKeyConstraint(
                ["style_id", "site_id"],
                ["product_styles.id", "product_styles.site_id"],
                name="fk_product_style_revisions_style",
                ondelete="RESTRICT",
                onupdate="RESTRICT",
            ),
            sa.ForeignKeyConstraint(
                ["actor_user_id"],
                ["users.id"],
                name="fk_product_style_revisions_actor",
                ondelete="RESTRICT",
                onupdate="RESTRICT",
            ),
            sa.CheckConstraint(
                "revision >= 1", name="ck_product_style_revisions_revision"
            ),
            sa.CheckConstraint(
                "status IN ('enabled','disabled')",
                name="ck_product_style_revisions_status",
            ),
            **_TABLE_OPTIONS,
        )

    _if_missing(existing, "product_style_revisions", create_product_style_revisions)

    def create_product_skus() -> None:
        op.create_table(
            "product_skus",
            sa.Column("id", _id_type(), autoincrement=True, nullable=False),
            sa.Column("site_id", _id_type(), nullable=False),
            sa.Column("style_id", _id_type(), nullable=False),
            sa.Column("internal_display_sku", sa.String(128), nullable=False),
            sa.Column("display_key_sha256", mysql.BINARY(32), nullable=False),
            sa.Column("display_key_bytes", _binary_text_type(512), nullable=False),
            sa.Column("standard_color", sa.String(128), nullable=False),
            sa.Column("color_key_sha256", mysql.BINARY(32), nullable=False),
            sa.Column("color_key_bytes", _binary_text_type(512), nullable=False),
            sa.Column("standard_size", sa.String(128), nullable=False),
            sa.Column("size_key_sha256", mysql.BINARY(32), nullable=False),
            sa.Column("size_key_bytes", _binary_text_type(512), nullable=False),
            sa.Column("status", _code_type(16), nullable=False),
            sa.Column("current_revision", _counter_type(), nullable=False),
            _created_at(),
            _updated_at(),
            sa.PrimaryKeyConstraint("id", name="pk_product_skus"),
            sa.UniqueConstraint(
                "id", "site_id", "style_id", name="uq_product_skus_member"
            ),
            sa.UniqueConstraint(
                "site_id",
                "display_key_sha256",
                "display_key_bytes",
                name="uq_product_skus_display",
            ),
            sa.UniqueConstraint(
                "site_id",
                "style_id",
                "color_key_sha256",
                "color_key_bytes",
                "size_key_sha256",
                "size_key_bytes",
                name="uq_product_skus_variant",
            ),
            sa.ForeignKeyConstraint(
                ["style_id", "site_id"],
                ["product_styles.id", "product_styles.site_id"],
                name="fk_product_skus_style",
                ondelete="RESTRICT",
                onupdate="RESTRICT",
            ),
            sa.CheckConstraint(
                "status IN ('enabled','disabled')", name="ck_product_skus_status"
            ),
            sa.CheckConstraint(
                "current_revision >= 1", name="ck_product_skus_revision"
            ),
            sa.Index(
                "ix_product_skus_style_status", "site_id", "style_id", "status", "id"
            ),
            **_TABLE_OPTIONS,
        )

    _if_missing(existing, "product_skus", create_product_skus)

    def create_product_sku_revisions() -> None:
        op.create_table(
            "product_sku_revisions",
            sa.Column("id", _id_type(), autoincrement=True, nullable=False),
            sa.Column("site_id", _id_type(), nullable=False),
            sa.Column("sku_id", _id_type(), nullable=False),
            sa.Column("style_id", _id_type(), nullable=False),
            sa.Column("revision", _counter_type(), nullable=False),
            sa.Column("internal_display_sku", sa.String(128), nullable=False),
            sa.Column("display_key_sha256", mysql.BINARY(32), nullable=False),
            sa.Column("display_key_bytes", _binary_text_type(512), nullable=False),
            sa.Column("standard_color", sa.String(128), nullable=False),
            sa.Column("color_key_sha256", mysql.BINARY(32), nullable=False),
            sa.Column("color_key_bytes", _binary_text_type(512), nullable=False),
            sa.Column("standard_size", sa.String(128), nullable=False),
            sa.Column("size_key_sha256", mysql.BINARY(32), nullable=False),
            sa.Column("size_key_bytes", _binary_text_type(512), nullable=False),
            sa.Column("status", _code_type(16), nullable=False),
            sa.Column("change_reason", sa.String(500), nullable=False),
            sa.Column("actor_user_id", _id_type(), nullable=False),
            sa.Column("source_import_id", _id_type(), nullable=True),
            sa.Column("source_command_token", mysql.BINARY(16), nullable=False),
            _created_at(),
            sa.PrimaryKeyConstraint("id", name="pk_product_sku_revisions"),
            sa.UniqueConstraint(
                "site_id", "sku_id", "revision", name="uq_product_sku_revisions_number"
            ),
            sa.UniqueConstraint(
                "id",
                "site_id",
                "sku_id",
                "style_id",
                name="uq_product_sku_revisions_member",
            ),
            sa.ForeignKeyConstraint(
                ["sku_id", "site_id", "style_id"],
                ["product_skus.id", "product_skus.site_id", "product_skus.style_id"],
                name="fk_product_sku_revisions_sku",
                ondelete="RESTRICT",
                onupdate="RESTRICT",
            ),
            sa.ForeignKeyConstraint(
                ["actor_user_id"],
                ["users.id"],
                name="fk_product_sku_revisions_actor",
                ondelete="RESTRICT",
                onupdate="RESTRICT",
            ),
            sa.CheckConstraint(
                "revision >= 1", name="ck_product_sku_revisions_revision"
            ),
            sa.CheckConstraint(
                "status IN ('enabled','disabled')",
                name="ck_product_sku_revisions_status",
            ),
            **_TABLE_OPTIONS,
        )

    _if_missing(existing, "product_sku_revisions", create_product_sku_revisions)

    def create_product_identity_key_reservations() -> None:
        op.create_table(
            "product_identity_key_reservations",
            sa.Column("id", _id_type(), autoincrement=True, nullable=False),
            sa.Column("site_id", _id_type(), nullable=False),
            sa.Column("key_kind", _code_type(24), nullable=False),
            sa.Column("key_sha256", mysql.BINARY(32), nullable=False),
            sa.Column("key_bytes", _binary_text_type(512), nullable=False),
            sa.Column("style_id", _id_type(), nullable=True),
            sa.Column("sku_id", _id_type(), nullable=True),
            sa.Column("first_revision_id", _id_type(), nullable=False),
            _created_at(),
            sa.PrimaryKeyConstraint("id", name="pk_product_identity_key_reservations"),
            sa.UniqueConstraint(
                "site_id",
                "key_kind",
                "key_sha256",
                "key_bytes",
                name="uq_product_identity_key_reservations_key",
            ),
            sa.ForeignKeyConstraint(
                ["style_id"],
                ["product_styles.id"],
                name="fk_product_identity_key_reservations_style",
                ondelete="RESTRICT",
                onupdate="RESTRICT",
            ),
            sa.ForeignKeyConstraint(
                ["sku_id"],
                ["product_skus.id"],
                name="fk_product_identity_key_reservations_sku",
                ondelete="RESTRICT",
                onupdate="RESTRICT",
            ),
            sa.CheckConstraint(
                "key_kind IN ('style_code','display_sku','variant')",
                name="ck_product_identity_key_reservations_kind",
            ),
            sa.CheckConstraint(
                "((key_kind='style_code' AND style_id IS NOT NULL "
                "AND sku_id IS NULL) OR (key_kind<>'style_code' "
                "AND style_id IS NULL AND sku_id IS NOT NULL))",
                name="ck_product_identity_key_reservations_owner",
            ),
            sa.Index(
                "ix_product_identity_key_reservations_owner",
                "site_id",
                "style_id",
                "sku_id",
            ),
            **_TABLE_OPTIONS,
        )

    _if_missing(
        existing,
        "product_identity_key_reservations",
        create_product_identity_key_reservations,
    )

    def create_product_catalog_versions() -> None:
        op.create_table(
            "product_catalog_versions",
            sa.Column("id", _id_type(), autoincrement=True, nullable=False),
            sa.Column("site_id", _id_type(), nullable=False),
            sa.Column("version_number", _counter_type(), nullable=False),
            sa.Column("base_catalog_version_id", _id_type(), nullable=True),
            sa.Column("workbook_schema_version", _code_type(64), nullable=False),
            sa.Column("normalization_manifest_id", _code_type(64), nullable=False),
            sa.Column("fact_snapshot_tuple_id", _id_type(), nullable=False),
            sa.Column("source_import_id", _id_type(), nullable=False),
            sa.Column("validation_run_id", _id_type(), nullable=False),
            sa.Column("approval_digest", mysql.BINARY(32), nullable=False),
            sa.Column("diff_digest", mysql.BINARY(32), nullable=False),
            sa.Column("risk", _code_type(16), nullable=False),
            sa.Column("status", _code_type(16), nullable=False),
            sa.Column("approved_by_user_id", _id_type(), nullable=False),
            sa.Column("approved_at", _timestamp_type(), nullable=False),
            sa.Column("approval_reason", sa.String(500), nullable=False),
            _created_at(),
            sa.PrimaryKeyConstraint("id", name="pk_product_catalog_versions"),
            sa.UniqueConstraint(
                "site_id", "version_number", name="uq_product_catalog_versions_number"
            ),
            sa.UniqueConstraint(
                "id", "site_id", name="uq_product_catalog_versions_id_site"
            ),
            sa.ForeignKeyConstraint(
                ["site_id"],
                ["sites.id"],
                name="fk_product_catalog_versions_site",
                ondelete="RESTRICT",
                onupdate="RESTRICT",
            ),
            sa.ForeignKeyConstraint(
                ["base_catalog_version_id"],
                ["product_catalog_versions.id"],
                name="fk_product_catalog_versions_base",
                ondelete="RESTRICT",
                onupdate="RESTRICT",
            ),
            sa.ForeignKeyConstraint(
                ["fact_snapshot_tuple_id", "site_id", "status"],
                [
                    "fact_snapshot_tuples.id",
                    "fact_snapshot_tuples.site_id",
                    "fact_snapshot_tuples.status",
                ],
                name="fk_product_catalog_versions_fact_tuple",
                ondelete="RESTRICT",
                onupdate="RESTRICT",
            ),
            sa.ForeignKeyConstraint(
                ["approved_by_user_id"],
                ["users.id"],
                name="fk_product_catalog_versions_approver",
                ondelete="RESTRICT",
                onupdate="RESTRICT",
            ),
            sa.CheckConstraint(
                "version_number >= 1", name="ck_product_catalog_versions_number"
            ),
            sa.CheckConstraint(
                "workbook_schema_version='product_catalog_workbook_v1'",
                name="ck_product_catalog_versions_workbook",
            ),
            sa.CheckConstraint(
                "risk IN ('normal','high')", name="ck_product_catalog_versions_risk"
            ),
            sa.CheckConstraint(
                "status='ready'", name="ck_product_catalog_versions_status"
            ),
            **_TABLE_OPTIONS,
        )

    _if_missing(existing, "product_catalog_versions", create_product_catalog_versions)

    def create_product_catalog_style_members() -> None:
        op.create_table(
            "product_catalog_style_members",
            sa.Column("id", _id_type(), autoincrement=True, nullable=False),
            sa.Column("catalog_version_id", _id_type(), nullable=False),
            sa.Column("site_id", _id_type(), nullable=False),
            sa.Column("style_id", _id_type(), nullable=False),
            sa.Column("style_revision_id", _id_type(), nullable=False),
            _created_at(),
            sa.PrimaryKeyConstraint("id", name="pk_product_catalog_style_members"),
            sa.UniqueConstraint(
                "catalog_version_id",
                "style_id",
                name="uq_product_catalog_style_members_style",
            ),
            sa.UniqueConstraint(
                "catalog_version_id",
                "site_id",
                "style_id",
                name="uq_product_catalog_style_members_ref",
            ),
            sa.ForeignKeyConstraint(
                ["catalog_version_id", "site_id"],
                ["product_catalog_versions.id", "product_catalog_versions.site_id"],
                name="fk_product_catalog_style_members_catalog",
                ondelete="RESTRICT",
                onupdate="RESTRICT",
            ),
            sa.ForeignKeyConstraint(
                ["style_revision_id", "site_id", "style_id"],
                [
                    "product_style_revisions.id",
                    "product_style_revisions.site_id",
                    "product_style_revisions.style_id",
                ],
                name="fk_product_catalog_style_members_revision",
                ondelete="RESTRICT",
                onupdate="RESTRICT",
            ),
            sa.Index(
                "ix_product_catalog_style_members_catalog_revision",
                "catalog_version_id",
                "style_revision_id",
            ),
            **_TABLE_OPTIONS,
        )

    _if_missing(
        existing, "product_catalog_style_members", create_product_catalog_style_members
    )

    def create_product_catalog_sku_members() -> None:
        op.create_table(
            "product_catalog_sku_members",
            sa.Column("id", _id_type(), autoincrement=True, nullable=False),
            sa.Column("catalog_version_id", _id_type(), nullable=False),
            sa.Column("site_id", _id_type(), nullable=False),
            sa.Column("sku_id", _id_type(), nullable=False),
            sa.Column("sku_revision_id", _id_type(), nullable=False),
            sa.Column("style_id", _id_type(), nullable=False),
            _created_at(),
            sa.PrimaryKeyConstraint("id", name="pk_product_catalog_sku_members"),
            sa.UniqueConstraint(
                "catalog_version_id",
                "sku_id",
                name="uq_product_catalog_sku_members_sku",
            ),
            sa.UniqueConstraint(
                "catalog_version_id",
                "site_id",
                "sku_id",
                name="uq_product_catalog_sku_members_ref",
            ),
            sa.ForeignKeyConstraint(
                ["catalog_version_id", "site_id"],
                ["product_catalog_versions.id", "product_catalog_versions.site_id"],
                name="fk_product_catalog_sku_members_catalog",
                ondelete="RESTRICT",
                onupdate="RESTRICT",
            ),
            sa.ForeignKeyConstraint(
                ["sku_revision_id", "site_id", "sku_id", "style_id"],
                [
                    "product_sku_revisions.id",
                    "product_sku_revisions.site_id",
                    "product_sku_revisions.sku_id",
                    "product_sku_revisions.style_id",
                ],
                name="fk_product_catalog_sku_members_revision",
                ondelete="RESTRICT",
                onupdate="RESTRICT",
            ),
            sa.ForeignKeyConstraint(
                ["catalog_version_id", "site_id", "style_id"],
                [
                    "product_catalog_style_members.catalog_version_id",
                    "product_catalog_style_members.site_id",
                    "product_catalog_style_members.style_id",
                ],
                name="fk_product_catalog_sku_members_style",
                ondelete="RESTRICT",
                onupdate="RESTRICT",
            ),
            sa.Index(
                "ix_product_catalog_sku_members_catalog_style",
                "catalog_version_id",
                "style_id",
                "sku_id",
            ),
            **_TABLE_OPTIONS,
        )

    _if_missing(
        existing, "product_catalog_sku_members", create_product_catalog_sku_members
    )

    def create_product_catalog_mappings() -> None:
        op.create_table(
            "product_catalog_mappings",
            sa.Column("id", _id_type(), autoincrement=True, nullable=False),
            sa.Column("catalog_version_id", _id_type(), nullable=False),
            sa.Column("site_id", _id_type(), nullable=False),
            sa.Column("report_source_scope_id", _id_type(), nullable=False),
            sa.Column("marketplace_scope_code", _code_type(32), nullable=False),
            sa.Column("seller_sku_match_sha256", mysql.BINARY(32), nullable=False),
            sa.Column(
                "seller_sku_match_bytes", _binary_text_type(1020), nullable=False
            ),
            sa.Column("sku_id", _id_type(), nullable=False),
            sa.Column("decision_source", _code_type(32), nullable=False),
            sa.Column("actor_user_id", _id_type(), nullable=False),
            sa.Column("evidence_digest", mysql.BINARY(32), nullable=False),
            _created_at(),
            sa.PrimaryKeyConstraint("id", name="pk_product_catalog_mappings"),
            sa.UniqueConstraint(
                "catalog_version_id",
                "report_source_scope_id",
                "seller_sku_match_sha256",
                "seller_sku_match_bytes",
                name="uq_product_catalog_mappings_key",
            ),
            sa.ForeignKeyConstraint(
                ["catalog_version_id", "site_id", "sku_id"],
                [
                    "product_catalog_sku_members.catalog_version_id",
                    "product_catalog_sku_members.site_id",
                    "product_catalog_sku_members.sku_id",
                ],
                name="fk_product_catalog_mappings_member",
                ondelete="RESTRICT",
                onupdate="RESTRICT",
            ),
            sa.ForeignKeyConstraint(
                ["report_source_scope_id", "site_id"],
                ["report_source_scopes.id", "report_source_scopes.site_id"],
                name="fk_product_catalog_mappings_scope",
                ondelete="RESTRICT",
                onupdate="RESTRICT",
            ),
            sa.ForeignKeyConstraint(
                ["actor_user_id"],
                ["users.id"],
                name="fk_product_catalog_mappings_actor",
                ondelete="RESTRICT",
                onupdate="RESTRICT",
            ),
            sa.CheckConstraint(
                "marketplace_scope_code='amazon_us'",
                name="ck_product_catalog_mappings_marketplace",
            ),
            sa.Index(
                "ix_product_catalog_mappings_lookup",
                "catalog_version_id",
                "report_source_scope_id",
                "seller_sku_match_sha256",
            ),
            **_TABLE_OPTIONS,
        )

    _if_missing(existing, "product_catalog_mappings", create_product_catalog_mappings)

    def create_product_catalog_exclusions() -> None:
        op.create_table(
            "product_catalog_exclusions",
            sa.Column("id", _id_type(), autoincrement=True, nullable=False),
            sa.Column("catalog_version_id", _id_type(), nullable=False),
            sa.Column("site_id", _id_type(), nullable=False),
            sa.Column("report_source_scope_id", _id_type(), nullable=False),
            sa.Column("marketplace_scope_code", _code_type(32), nullable=False),
            sa.Column("seller_sku_match_sha256", mysql.BINARY(32), nullable=False),
            sa.Column(
                "seller_sku_match_bytes", _binary_text_type(1020), nullable=False
            ),
            sa.Column("reason", sa.String(500), nullable=False),
            sa.Column("actor_user_id", _id_type(), nullable=False),
            sa.Column("evidence_digest", mysql.BINARY(32), nullable=False),
            _created_at(),
            sa.PrimaryKeyConstraint("id", name="pk_product_catalog_exclusions"),
            sa.UniqueConstraint(
                "catalog_version_id",
                "report_source_scope_id",
                "seller_sku_match_sha256",
                "seller_sku_match_bytes",
                name="uq_product_catalog_exclusions_key",
            ),
            sa.ForeignKeyConstraint(
                ["catalog_version_id", "site_id"],
                ["product_catalog_versions.id", "product_catalog_versions.site_id"],
                name="fk_product_catalog_exclusions_catalog",
                ondelete="RESTRICT",
                onupdate="RESTRICT",
            ),
            sa.ForeignKeyConstraint(
                ["report_source_scope_id", "site_id"],
                ["report_source_scopes.id", "report_source_scopes.site_id"],
                name="fk_product_catalog_exclusions_scope",
                ondelete="RESTRICT",
                onupdate="RESTRICT",
            ),
            sa.ForeignKeyConstraint(
                ["actor_user_id"],
                ["users.id"],
                name="fk_product_catalog_exclusions_actor",
                ondelete="RESTRICT",
                onupdate="RESTRICT",
            ),
            sa.CheckConstraint(
                "marketplace_scope_code='amazon_us'",
                name="ck_product_catalog_exclusions_marketplace",
            ),
            sa.CheckConstraint(
                "CHAR_LENGTH(TRIM(reason)) >= 10",
                name="ck_product_catalog_exclusions_reason",
            ),
            sa.Index(
                "ix_product_catalog_exclusions_lookup",
                "catalog_version_id",
                "report_source_scope_id",
                "seller_sku_match_sha256",
            ),
            **_TABLE_OPTIONS,
        )

    _if_missing(
        existing, "product_catalog_exclusions", create_product_catalog_exclusions
    )

    def create_product_catalog_publications() -> None:
        op.create_table(
            "product_catalog_publications",
            sa.Column("site_id", _id_type(), nullable=False),
            sa.Column("current_catalog_version_id", _id_type(), nullable=True),
            sa.Column(
                "catalog_publication_revision",
                _counter_type(),
                server_default=sa.text("0"),
                nullable=False,
            ),
            _updated_at(),
            sa.PrimaryKeyConstraint("site_id", name="pk_product_catalog_publications"),
            sa.ForeignKeyConstraint(
                ["site_id"],
                ["sites.id"],
                name="fk_product_catalog_publications_site",
                ondelete="RESTRICT",
                onupdate="RESTRICT",
            ),
            sa.ForeignKeyConstraint(
                ["current_catalog_version_id", "site_id"],
                ["product_catalog_versions.id", "product_catalog_versions.site_id"],
                name="fk_product_catalog_publications_current",
                ondelete="RESTRICT",
                onupdate="RESTRICT",
            ),
            **_TABLE_OPTIONS,
        )

    _if_missing(
        existing, "product_catalog_publications", create_product_catalog_publications
    )

    def create_product_catalog_publication_events() -> None:
        op.create_table(
            "product_catalog_publication_events",
            sa.Column("id", _id_type(), autoincrement=True, nullable=False),
            sa.Column("site_id", _id_type(), nullable=False),
            sa.Column("catalog_publication_revision", _counter_type(), nullable=False),
            sa.Column("previous_catalog_version_id", _id_type(), nullable=True),
            sa.Column("catalog_version_id", _id_type(), nullable=False),
            sa.Column("event_kind", _code_type(16), nullable=False),
            sa.Column("operation_token", mysql.BINARY(16), nullable=False),
            sa.Column("actor_user_id", _id_type(), nullable=False),
            sa.Column("reason", sa.String(500), nullable=False),
            _created_at(),
            sa.PrimaryKeyConstraint("id", name="pk_product_catalog_publication_events"),
            sa.UniqueConstraint(
                "site_id",
                "catalog_publication_revision",
                name="uq_product_catalog_publication_events_revision",
            ),
            sa.UniqueConstraint(
                "operation_token", name="uq_product_catalog_publication_events_token"
            ),
            sa.ForeignKeyConstraint(
                ["catalog_version_id", "site_id"],
                ["product_catalog_versions.id", "product_catalog_versions.site_id"],
                name="fk_product_catalog_publication_events_catalog",
                ondelete="RESTRICT",
                onupdate="RESTRICT",
            ),
            sa.ForeignKeyConstraint(
                ["previous_catalog_version_id"],
                ["product_catalog_versions.id"],
                name="fk_product_catalog_publication_events_previous",
                ondelete="RESTRICT",
                onupdate="RESTRICT",
            ),
            sa.ForeignKeyConstraint(
                ["actor_user_id"],
                ["users.id"],
                name="fk_product_catalog_publication_events_actor",
                ondelete="RESTRICT",
                onupdate="RESTRICT",
            ),
            sa.CheckConstraint(
                "catalog_publication_revision >= 1",
                name="ck_product_catalog_publication_events_revision",
            ),
            sa.CheckConstraint(
                "event_kind IN ('approve','restore')",
                name="ck_product_catalog_publication_events_kind",
            ),
            **_TABLE_OPTIONS,
        )

    _if_missing(
        existing,
        "product_catalog_publication_events",
        create_product_catalog_publication_events,
    )

    def create_catalog_source_refs() -> None:
        op.create_table(
            "catalog_source_refs",
            sa.Column("id", _id_type(), autoincrement=True, nullable=False),
            sa.Column("site_id", _id_type(), nullable=False),
            sa.Column("resource_kind", _code_type(24), nullable=False),
            sa.Column("resource_id", _id_type(), nullable=False),
            sa.Column("source_kind", _code_type(24), nullable=False),
            sa.Column("raw_value", sa.Text(), nullable=False),
            sa.Column("raw_sha256", mysql.BINARY(32), nullable=False),
            sa.Column("safe_preview", sa.String(255), nullable=False),
            sa.Column("is_unsafe", sa.Boolean(), nullable=False),
            sa.Column("is_truncated", sa.Boolean(), nullable=False),
            _created_at(),
            sa.PrimaryKeyConstraint("id", name="pk_catalog_source_refs"),
            sa.UniqueConstraint(
                "site_id",
                "resource_kind",
                "resource_id",
                "source_kind",
                "raw_sha256",
                name="uq_catalog_source_refs_resource",
            ),
            sa.ForeignKeyConstraint(
                ["site_id"],
                ["sites.id"],
                name="fk_catalog_source_refs_site",
                ondelete="RESTRICT",
                onupdate="RESTRICT",
            ),
            sa.CheckConstraint(
                "resource_kind IN ('catalog','export','import')",
                name="ck_catalog_source_refs_resource_kind",
            ),
            sa.CheckConstraint(
                "source_kind IN "
                "('seller_sku','title','parent_asin','child_asin','fnsku',"
                "'source_locator')",
                name="ck_catalog_source_refs_source_kind",
            ),
            sa.Index(
                "ix_catalog_source_refs_resource",
                "site_id",
                "resource_kind",
                "resource_id",
                "id",
            ),
            **_TABLE_OPTIONS,
        )

    _if_missing(existing, "catalog_source_refs", create_catalog_source_refs)

    def create_catalog_source_evidence() -> None:
        op.create_table(
            "catalog_source_evidence",
            sa.Column("id", _id_type(), autoincrement=True, nullable=False),
            sa.Column("site_id", _id_type(), nullable=False),
            sa.Column("report_source_scope_id", _id_type(), nullable=False),
            sa.Column("source_key_id", _id_type(), nullable=False),
            sa.Column("report_type", _code_type(24), nullable=False),
            sa.Column("report_date", sa.Date(), nullable=False),
            sa.Column("event_date", sa.Date(), nullable=True),
            sa.Column("dataset_id", _id_type(), nullable=False),
            sa.Column("published_version_id", _id_type(), nullable=False),
            sa.Column("source_row_id", _id_type(), nullable=False),
            sa.Column("seller_sku_ref_id", _id_type(), nullable=False),
            sa.Column("title_ref_id", _id_type(), nullable=True),
            sa.Column("parent_asin_ref_id", _id_type(), nullable=True),
            sa.Column("child_asin_ref_id", _id_type(), nullable=True),
            sa.Column("fnsku_ref_id", _id_type(), nullable=True),
            sa.Column("source_locator_ref_id", _id_type(), nullable=True),
            sa.Column("evidence_tuple_digest", mysql.BINARY(32), nullable=False),
            _created_at(),
            sa.PrimaryKeyConstraint("id", name="pk_catalog_source_evidence"),
            sa.UniqueConstraint(
                "source_key_id",
                "dataset_id",
                "published_version_id",
                "source_row_id",
                name="uq_catalog_source_evidence_source_row",
            ),
            sa.ForeignKeyConstraint(
                ["source_key_id", "site_id", "report_source_scope_id"],
                [
                    "report_source_keys.id",
                    "report_source_keys.site_id",
                    "report_source_keys.report_source_scope_id",
                ],
                name="fk_catalog_source_evidence_source_key",
                ondelete="RESTRICT",
                onupdate="RESTRICT",
            ),
            sa.ForeignKeyConstraint(
                ["dataset_id"],
                ["daily_datasets.id"],
                name="fk_catalog_source_evidence_dataset",
                ondelete="RESTRICT",
                onupdate="RESTRICT",
            ),
            sa.ForeignKeyConstraint(
                ["published_version_id"],
                ["dataset_versions.id"],
                name="fk_catalog_source_evidence_version",
                ondelete="RESTRICT",
                onupdate="RESTRICT",
            ),
            sa.ForeignKeyConstraint(
                ["seller_sku_ref_id"],
                ["catalog_source_refs.id"],
                name="fk_catalog_source_evidence_seller_sku",
                ondelete="RESTRICT",
                onupdate="RESTRICT",
            ),
            sa.ForeignKeyConstraint(
                ["title_ref_id"],
                ["catalog_source_refs.id"],
                name="fk_catalog_source_evidence_title",
                ondelete="RESTRICT",
                onupdate="RESTRICT",
            ),
            sa.ForeignKeyConstraint(
                ["parent_asin_ref_id"],
                ["catalog_source_refs.id"],
                name="fk_catalog_source_evidence_parent_asin",
                ondelete="RESTRICT",
                onupdate="RESTRICT",
            ),
            sa.ForeignKeyConstraint(
                ["child_asin_ref_id"],
                ["catalog_source_refs.id"],
                name="fk_catalog_source_evidence_child_asin",
                ondelete="RESTRICT",
                onupdate="RESTRICT",
            ),
            sa.ForeignKeyConstraint(
                ["fnsku_ref_id"],
                ["catalog_source_refs.id"],
                name="fk_catalog_source_evidence_fnsku",
                ondelete="RESTRICT",
                onupdate="RESTRICT",
            ),
            sa.ForeignKeyConstraint(
                ["source_locator_ref_id"],
                ["catalog_source_refs.id"],
                name="fk_catalog_source_evidence_locator",
                ondelete="RESTRICT",
                onupdate="RESTRICT",
            ),
            sa.CheckConstraint(
                "report_type IN ('business_report','return_report')",
                name="ck_catalog_source_evidence_report_type",
            ),
            sa.Index(
                "ix_catalog_source_evidence_scope_date",
                "report_source_scope_id",
                "report_type",
                "report_date",
                "id",
            ),
            **_TABLE_OPTIONS,
        )

    _if_missing(existing, "catalog_source_evidence", create_catalog_source_evidence)

    def create_catalog_exports() -> None:
        op.create_table(
            "catalog_exports",
            sa.Column("id", _id_type(), autoincrement=True, nullable=False),
            sa.Column("site_id", _id_type(), nullable=False),
            sa.Column("operation_token", mysql.BINARY(16), nullable=False),
            sa.Column("fact_snapshot_tuple_id", _id_type(), nullable=False),
            sa.Column("base_catalog_version_id", _id_type(), nullable=True),
            sa.Column("catalog_publication_revision", _counter_type(), nullable=False),
            sa.Column("workbook_schema_version", _code_type(64), nullable=False),
            sa.Column("normalization_manifest_id", _code_type(64), nullable=False),
            sa.Column("export_status", _code_type(16), nullable=False),
            sa.Column("workbook_status", _code_type(24), nullable=True),
            sa.Column("capacity_violations", mysql.JSON(), nullable=True),
            sa.Column("artifact_sha256", mysql.BINARY(32), nullable=True),
            sa.Column("artifact_storage_key", sa.String(512), nullable=True),
            sa.Column("failure_reason_code", _code_type(64), nullable=True),
            sa.Column("created_by_user_id", _id_type(), nullable=False),
            _created_at(),
            _updated_at(),
            sa.PrimaryKeyConstraint("id", name="pk_catalog_exports"),
            sa.UniqueConstraint("operation_token", name="uq_catalog_exports_token"),
            sa.UniqueConstraint("id", "site_id", name="uq_catalog_exports_id_site"),
            sa.ForeignKeyConstraint(
                ["fact_snapshot_tuple_id", "site_id"],
                ["fact_snapshot_tuples.id", "fact_snapshot_tuples.site_id"],
                name="fk_catalog_exports_fact_tuple",
                ondelete="RESTRICT",
                onupdate="RESTRICT",
            ),
            sa.ForeignKeyConstraint(
                ["base_catalog_version_id"],
                ["product_catalog_versions.id"],
                name="fk_catalog_exports_base",
                ondelete="RESTRICT",
                onupdate="RESTRICT",
            ),
            sa.ForeignKeyConstraint(
                ["created_by_user_id"],
                ["users.id"],
                name="fk_catalog_exports_creator",
                ondelete="RESTRICT",
                onupdate="RESTRICT",
            ),
            sa.CheckConstraint(
                "export_status IN ('building','ready','failed')",
                name="ck_catalog_exports_status",
            ),
            sa.CheckConstraint(
                "workbook_status IS NULL OR "
                "workbook_status IN ('ready','capacity_exceeded')",
                name="ck_catalog_exports_workbook_status",
            ),
            sa.CheckConstraint(
                "workbook_schema_version='product_catalog_workbook_v1'",
                name="ck_catalog_exports_workbook_version",
            ),
            sa.CheckConstraint(
                "((export_status='building' AND workbook_status IS NULL "
                "AND capacity_violations IS NULL AND artifact_sha256 IS NULL "
                "AND artifact_storage_key IS NULL AND failure_reason_code IS NULL) "
                "OR (export_status='failed' AND workbook_status IS NULL "
                "AND capacity_violations IS NULL AND artifact_sha256 IS NULL "
                "AND artifact_storage_key IS NULL AND failure_reason_code IS NOT NULL) "
                "OR (export_status='ready' AND workbook_status='ready' "
                "AND JSON_LENGTH(capacity_violations)=0 "
                "AND artifact_sha256 IS NOT NULL "
                "AND artifact_storage_key IS NOT NULL "
                "AND failure_reason_code IS NULL) "
                "OR (export_status='ready' "
                "AND workbook_status='capacity_exceeded' "
                "AND JSON_LENGTH(capacity_violations)>0 "
                "AND artifact_sha256 IS NULL AND artifact_storage_key IS NULL "
                "AND failure_reason_code IS NULL))",
                name="ck_catalog_exports_finalization",
            ),
            sa.Index("ix_catalog_exports_site_created", "site_id", "created_at", "id"),
            **_TABLE_OPTIONS,
        )

    _if_missing(existing, "catalog_exports", create_catalog_exports)

    def create_catalog_export_payloads() -> None:
        op.create_table(
            "catalog_export_payloads",
            sa.Column("export_id", _id_type(), nullable=False),
            sa.Column("site_id", _id_type(), nullable=False),
            sa.Column("candidate_payload_json", mysql.JSON(), nullable=False),
            sa.Column("candidate_payload_digest", mysql.BINARY(32), nullable=False),
            sa.Column("evidence_payload_json", mysql.JSON(), nullable=False),
            sa.Column("evidence_payload_digest", mysql.BINARY(32), nullable=False),
            sa.Column("payload_digest", mysql.BINARY(32), nullable=False),
            _created_at(),
            sa.PrimaryKeyConstraint("export_id", name="pk_catalog_export_payloads"),
            sa.ForeignKeyConstraint(
                ["export_id", "site_id"],
                ["catalog_exports.id", "catalog_exports.site_id"],
                name="fk_catalog_export_payloads_export",
                ondelete="RESTRICT",
                onupdate="RESTRICT",
            ),
            **_TABLE_OPTIONS,
        )

    _if_missing(existing, "catalog_export_payloads", create_catalog_export_payloads)

    def create_catalog_imports() -> None:
        op.create_table(
            "catalog_imports",
            sa.Column("id", _id_type(), autoincrement=True, nullable=False),
            sa.Column("site_id", _id_type(), nullable=False),
            sa.Column("operation_token", mysql.BINARY(16), nullable=False),
            sa.Column("source_kind", _code_type(16), nullable=False),
            sa.Column("owner_user_id", _id_type(), nullable=False),
            sa.Column("export_id", _id_type(), nullable=False),
            sa.Column("raw_file_id", _id_type(), nullable=True),
            sa.Column("original_filename", sa.String(512), nullable=True),
            sa.Column("declared_media_type", _code_type(128), nullable=True),
            sa.Column("base_catalog_version_id", _id_type(), nullable=True),
            sa.Column("fact_snapshot_tuple_id", _id_type(), nullable=False),
            sa.Column("normalization_manifest_id", _code_type(64), nullable=False),
            sa.Column("status", _code_type(24), nullable=False),
            sa.Column(
                "workflow_revision",
                _counter_type(),
                server_default=sa.text("0"),
                nullable=False,
            ),
            sa.Column(
                "parse_attempt_revision",
                _counter_type(),
                server_default=sa.text("0"),
                nullable=False,
            ),
            sa.Column("submitted_by_user_id", _id_type(), nullable=True),
            sa.Column("validation_run_id", _id_type(), nullable=True),
            sa.Column("superseded_by_id", _id_type(), nullable=True),
            _created_at(),
            _updated_at(),
            sa.PrimaryKeyConstraint("id", name="pk_catalog_imports"),
            sa.UniqueConstraint("id", "site_id", name="uq_catalog_imports_id_site"),
            sa.UniqueConstraint(
                "operation_token", name="uq_catalog_imports_operation_token"
            ),
            sa.ForeignKeyConstraint(
                ["site_id"],
                ["sites.id"],
                name="fk_catalog_imports_site",
                ondelete="RESTRICT",
                onupdate="RESTRICT",
            ),
            sa.ForeignKeyConstraint(
                ["owner_user_id"],
                ["users.id"],
                name="fk_catalog_imports_owner",
                ondelete="RESTRICT",
                onupdate="RESTRICT",
            ),
            sa.ForeignKeyConstraint(
                ["export_id"],
                ["catalog_exports.id"],
                name="fk_catalog_imports_export",
                ondelete="RESTRICT",
                onupdate="RESTRICT",
            ),
            sa.ForeignKeyConstraint(
                ["raw_file_id"],
                ["raw_files.id"],
                name="fk_catalog_imports_raw_file",
                ondelete="RESTRICT",
                onupdate="RESTRICT",
            ),
            sa.ForeignKeyConstraint(
                ["base_catalog_version_id"],
                ["product_catalog_versions.id"],
                name="fk_catalog_imports_base",
                ondelete="RESTRICT",
                onupdate="RESTRICT",
            ),
            sa.ForeignKeyConstraint(
                ["fact_snapshot_tuple_id"],
                ["fact_snapshot_tuples.id"],
                name="fk_catalog_imports_fact_tuple",
                ondelete="RESTRICT",
                onupdate="RESTRICT",
            ),
            sa.ForeignKeyConstraint(
                ["submitted_by_user_id"],
                ["users.id"],
                name="fk_catalog_imports_submitter",
                ondelete="RESTRICT",
                onupdate="RESTRICT",
            ),
            sa.ForeignKeyConstraint(
                ["superseded_by_id"],
                ["catalog_imports.id"],
                name="fk_catalog_imports_superseded",
                ondelete="RESTRICT",
                onupdate="RESTRICT",
            ),
            sa.CheckConstraint(
                "source_kind IN ('xlsx','online')",
                name="ck_catalog_imports_source_kind",
            ),
            sa.CheckConstraint(
                "status IN ('uploaded','parsing','parse_failed','needs_attention',"
                "'validated','ready_for_approval','approved','rejected',"
                "'withdrawn','superseded')",
                name="ck_catalog_imports_status",
            ),
            sa.CheckConstraint(
                "((source_kind='xlsx' AND raw_file_id IS NOT NULL "
                "AND original_filename IS NOT NULL "
                "AND declared_media_type IS NOT NULL) OR "
                "(source_kind='online' AND raw_file_id IS NULL "
                "AND original_filename IS NULL "
                "AND declared_media_type IS NULL))",
                name="ck_catalog_imports_source_metadata",
            ),
            sa.Index(
                "ix_catalog_imports_site_status",
                "site_id",
                "status",
                "updated_at",
                "id",
            ),
            **_TABLE_OPTIONS,
        )

    _if_missing(existing, "catalog_imports", create_catalog_imports)

    def create_catalog_parse_attempts() -> None:
        op.create_table(
            "catalog_parse_attempts",
            sa.Column("id", _id_type(), autoincrement=True, nullable=False),
            sa.Column("import_id", _id_type(), nullable=False),
            sa.Column("site_id", _id_type(), nullable=False),
            sa.Column("attempt_revision", _counter_type(), nullable=False),
            sa.Column("workflow_revision", _counter_type(), nullable=False),
            sa.Column("status", _code_type(16), nullable=False),
            sa.Column("lease_token", mysql.BINARY(16), nullable=False),
            sa.Column("fencing_token", _counter_type(), nullable=False),
            sa.Column("started_at", _timestamp_type(), nullable=False),
            sa.Column("lease_expires_at", _timestamp_type(), nullable=False),
            sa.Column("completed_at", _timestamp_type(), nullable=True),
            sa.Column("recoverable", sa.Boolean(), nullable=True),
            sa.Column("failure_reason_code", _code_type(64), nullable=True),
            sa.Column("result_digest", mysql.BINARY(32), nullable=True),
            _created_at(),
            sa.PrimaryKeyConstraint("id", name="pk_catalog_parse_attempts"),
            sa.UniqueConstraint(
                "import_id",
                "attempt_revision",
                name="uq_catalog_parse_attempts_revision",
            ),
            sa.ForeignKeyConstraint(
                ["import_id", "site_id"],
                ["catalog_imports.id", "catalog_imports.site_id"],
                name="fk_catalog_parse_attempts_import",
                ondelete="RESTRICT",
                onupdate="RESTRICT",
            ),
            sa.CheckConstraint(
                "attempt_revision >= 1", name="ck_catalog_parse_attempts_revision"
            ),
            sa.CheckConstraint(
                "status IN ('running','succeeded','failed')",
                name="ck_catalog_parse_attempts_status",
            ),
            sa.CheckConstraint(
                "((status='running' AND completed_at IS NULL "
                "AND recoverable IS NULL AND failure_reason_code IS NULL "
                "AND lease_expires_at > started_at "
                "AND result_digest IS NULL) OR "
                "(status='succeeded' AND completed_at IS NOT NULL "
                "AND recoverable=0 AND failure_reason_code IS NULL "
                "AND result_digest IS NOT NULL) OR "
                "(status='failed' AND completed_at IS NOT NULL "
                "AND recoverable IS NOT NULL "
                "AND failure_reason_code IS NOT NULL))",
                name="ck_catalog_parse_attempts_terminal",
            ),
            **_TABLE_OPTIONS,
        )

    _if_missing(existing, "catalog_parse_attempts", create_catalog_parse_attempts)

    def create_catalog_import_rows() -> None:
        op.create_table(
            "catalog_import_rows",
            sa.Column("id", _id_type(), autoincrement=True, nullable=False),
            sa.Column("import_id", _id_type(), nullable=False),
            sa.Column("site_id", _id_type(), nullable=False),
            sa.Column("workflow_revision", _counter_type(), nullable=False),
            sa.Column("section", _code_type(24), nullable=False),
            sa.Column("row_key", _code_type(64), nullable=False),
            sa.Column("row_origin", _code_type(16), nullable=False),
            sa.Column("projection_state", _code_type(16), nullable=False),
            sa.Column("payload_json", mysql.JSON(), nullable=False),
            sa.Column("payload_digest", mysql.BINARY(32), nullable=False),
            _created_at(),
            sa.PrimaryKeyConstraint("id", name="pk_catalog_import_rows"),
            sa.UniqueConstraint(
                "import_id",
                "workflow_revision",
                "section",
                "row_key",
                name="uq_catalog_import_rows_revision",
            ),
            sa.ForeignKeyConstraint(
                ["import_id", "site_id"],
                ["catalog_imports.id", "catalog_imports.site_id"],
                name="fk_catalog_import_rows_import",
                ondelete="RESTRICT",
                onupdate="RESTRICT",
            ),
            sa.CheckConstraint(
                "section IN ('styles','skus','mappings','exceptions','evidence')",
                name="ck_catalog_import_rows_section",
            ),
            sa.CheckConstraint(
                "row_origin IN ('system','user_created')",
                name="ck_catalog_import_rows_origin",
            ),
            sa.CheckConstraint(
                "projection_state IN ('included','audit_only')",
                name="ck_catalog_import_rows_projection",
            ),
            sa.Index(
                "ix_catalog_import_rows_page",
                "import_id",
                "workflow_revision",
                "section",
                "id",
            ),
            **_TABLE_OPTIONS,
        )

    _if_missing(existing, "catalog_import_rows", create_catalog_import_rows)

    def create_catalog_import_issues() -> None:
        op.create_table(
            "catalog_import_issues",
            sa.Column("id", _id_type(), autoincrement=True, nullable=False),
            sa.Column("import_id", _id_type(), nullable=False),
            sa.Column("site_id", _id_type(), nullable=False),
            sa.Column("workflow_revision", _counter_type(), nullable=False),
            sa.Column("section", _code_type(24), nullable=False),
            sa.Column("row_key", _code_type(64), nullable=True),
            sa.Column("severity", _code_type(16), nullable=False),
            sa.Column("reason_code", _code_type(64), nullable=False),
            sa.Column("safe_detail_json", mysql.JSON(), nullable=False),
            sa.Column("issue_digest", mysql.BINARY(32), nullable=False),
            _created_at(),
            sa.PrimaryKeyConstraint("id", name="pk_catalog_import_issues"),
            sa.UniqueConstraint(
                "import_id",
                "workflow_revision",
                "issue_digest",
                name="uq_catalog_import_issues_digest",
            ),
            sa.ForeignKeyConstraint(
                ["import_id", "site_id"],
                ["catalog_imports.id", "catalog_imports.site_id"],
                name="fk_catalog_import_issues_import",
                ondelete="RESTRICT",
                onupdate="RESTRICT",
            ),
            sa.CheckConstraint(
                "severity IN ('blocking','warning')",
                name="ck_catalog_import_issues_severity",
            ),
            sa.Index(
                "ix_catalog_import_issues_page",
                "import_id",
                "workflow_revision",
                "severity",
                "id",
            ),
            **_TABLE_OPTIONS,
        )

    _if_missing(existing, "catalog_import_issues", create_catalog_import_issues)

    def create_catalog_validation_runs() -> None:
        op.create_table(
            "catalog_validation_runs",
            sa.Column("id", _id_type(), autoincrement=True, nullable=False),
            sa.Column("import_id", _id_type(), nullable=False),
            sa.Column("site_id", _id_type(), nullable=False),
            sa.Column("workflow_revision", _counter_type(), nullable=False),
            sa.Column("status", _code_type(16), nullable=False),
            sa.Column("included_row_set_digest", mysql.BINARY(32), nullable=False),
            sa.Column("audit_only_row_set_digest", mysql.BINARY(32), nullable=False),
            sa.Column("issue_set_digest", mysql.BINARY(32), nullable=False),
            sa.Column("diff_digest", mysql.BINARY(32), nullable=False),
            sa.Column("created_by_user_id", _id_type(), nullable=False),
            _created_at(),
            sa.PrimaryKeyConstraint("id", name="pk_catalog_validation_runs"),
            sa.UniqueConstraint(
                "import_id",
                "workflow_revision",
                name="uq_catalog_validation_runs_revision",
            ),
            sa.ForeignKeyConstraint(
                ["import_id", "site_id"],
                ["catalog_imports.id", "catalog_imports.site_id"],
                name="fk_catalog_validation_runs_import",
                ondelete="RESTRICT",
                onupdate="RESTRICT",
            ),
            sa.ForeignKeyConstraint(
                ["created_by_user_id"],
                ["users.id"],
                name="fk_catalog_validation_runs_creator",
                ondelete="RESTRICT",
                onupdate="RESTRICT",
            ),
            sa.CheckConstraint(
                "status IN ('passed','failed')",
                name="ck_catalog_validation_runs_status",
            ),
            **_TABLE_OPTIONS,
        )

    _if_missing(existing, "catalog_validation_runs", create_catalog_validation_runs)

    def create_catalog_approval_projections() -> None:
        op.create_table(
            "catalog_approval_projections",
            sa.Column("id", _id_type(), autoincrement=True, nullable=False),
            sa.Column("import_id", _id_type(), nullable=False),
            sa.Column("site_id", _id_type(), nullable=False),
            sa.Column("workflow_revision", _counter_type(), nullable=False),
            sa.Column("validation_run_id", _id_type(), nullable=False),
            sa.Column("base_catalog_version_id", _id_type(), nullable=True),
            sa.Column("catalog_publication_revision", _counter_type(), nullable=False),
            sa.Column("fact_snapshot_tuple_id", _id_type(), nullable=False),
            sa.Column("risk", _code_type(16), nullable=False),
            sa.Column("diff_digest", mysql.BINARY(32), nullable=False),
            sa.Column("projection_digest", mysql.BINARY(32), nullable=False),
            sa.Column("created_by_user_id", _id_type(), nullable=False),
            _created_at(),
            sa.Column("expires_at", _timestamp_type(), nullable=False),
            sa.PrimaryKeyConstraint("id", name="pk_catalog_approval_projections"),
            sa.UniqueConstraint(
                "import_id",
                "workflow_revision",
                "projection_digest",
                "created_by_user_id",
                name="uq_catalog_approval_projections_digest",
            ),
            sa.ForeignKeyConstraint(
                ["import_id", "site_id"],
                ["catalog_imports.id", "catalog_imports.site_id"],
                name="fk_catalog_approval_projections_import",
                ondelete="RESTRICT",
                onupdate="RESTRICT",
            ),
            sa.ForeignKeyConstraint(
                ["validation_run_id"],
                ["catalog_validation_runs.id"],
                name="fk_catalog_approval_projections_validation",
                ondelete="RESTRICT",
                onupdate="RESTRICT",
            ),
            sa.ForeignKeyConstraint(
                ["base_catalog_version_id"],
                ["product_catalog_versions.id"],
                name="fk_catalog_approval_projections_base",
                ondelete="RESTRICT",
                onupdate="RESTRICT",
            ),
            sa.ForeignKeyConstraint(
                ["fact_snapshot_tuple_id"],
                ["fact_snapshot_tuples.id"],
                name="fk_catalog_approval_projections_fact",
                ondelete="RESTRICT",
                onupdate="RESTRICT",
            ),
            sa.ForeignKeyConstraint(
                ["created_by_user_id"],
                ["users.id"],
                name="fk_catalog_approval_projections_creator",
                ondelete="RESTRICT",
                onupdate="RESTRICT",
            ),
            sa.CheckConstraint(
                "risk IN ('normal','high')", name="ck_catalog_approval_projections_risk"
            ),
            sa.CheckConstraint(
                "expires_at = created_at + INTERVAL 30 MINUTE",
                name="ck_catalog_approval_projections_expiry",
            ),
            sa.Index(
                "ix_catalog_approval_projections_import_expiry",
                "import_id",
                "expires_at",
                "id",
            ),
            **_TABLE_OPTIONS,
        )

    _if_missing(
        existing, "catalog_approval_projections", create_catalog_approval_projections
    )

    def create_catalog_command_claims() -> None:
        op.create_table(
            "catalog_command_claims",
            sa.Column("operation_token", mysql.BINARY(16), nullable=False),
            sa.Column("operation_kind", _code_type(32), nullable=False),
            sa.Column("operation_digest", mysql.BINARY(32), nullable=False),
            sa.Column("site_id", _id_type(), nullable=False),
            sa.Column("actor_user_id", _id_type(), nullable=False),
            sa.Column("resource_kind", _code_type(24), nullable=False),
            sa.Column("resource_id", _id_type(), nullable=True),
            sa.Column("status", _code_type(16), nullable=False),
            _created_at(),
            sa.PrimaryKeyConstraint(
                "operation_token", name="pk_catalog_command_claims"
            ),
            sa.UniqueConstraint(
                "operation_token",
                "operation_kind",
                "operation_digest",
                "actor_user_id",
                name="uq_catalog_command_claims_identity",
            ),
            sa.ForeignKeyConstraint(
                ["site_id"],
                ["sites.id"],
                name="fk_catalog_command_claims_site",
                ondelete="RESTRICT",
                onupdate="RESTRICT",
            ),
            sa.ForeignKeyConstraint(
                ["actor_user_id"],
                ["users.id"],
                name="fk_catalog_command_claims_actor",
                ondelete="RESTRICT",
                onupdate="RESTRICT",
            ),
            sa.CheckConstraint(
                "status IN ('claimed','completed','outcome_unknown')",
                name="ck_catalog_command_claims_status",
            ),
            sa.Index(
                "ix_catalog_command_claims_resource",
                "site_id",
                "resource_kind",
                "resource_id",
                "created_at",
            ),
            **_TABLE_OPTIONS,
        )

    _if_missing(existing, "catalog_command_claims", create_catalog_command_claims)

    def create_catalog_command_effects() -> None:
        op.create_table(
            "catalog_command_effects",
            sa.Column("operation_token", mysql.BINARY(16), nullable=False),
            sa.Column("operation_kind", _code_type(32), nullable=False),
            sa.Column("operation_digest", mysql.BINARY(32), nullable=False),
            sa.Column("site_id", _id_type(), nullable=False),
            sa.Column("actor_user_id", _id_type(), nullable=False),
            sa.Column(
                "response_schema_version", mysql.SMALLINT(unsigned=True), nullable=False
            ),
            sa.Column(
                "response_status_code", mysql.SMALLINT(unsigned=True), nullable=False
            ),
            sa.Column("safe_result_json", mysql.JSON(), nullable=False),
            sa.Column("completed_at", _timestamp_type(), nullable=False),
            sa.PrimaryKeyConstraint(
                "operation_token", name="pk_catalog_command_effects"
            ),
            sa.ForeignKeyConstraint(
                [
                    "operation_token",
                    "operation_kind",
                    "operation_digest",
                    "actor_user_id",
                ],
                [
                    "catalog_command_claims.operation_token",
                    "catalog_command_claims.operation_kind",
                    "catalog_command_claims.operation_digest",
                    "catalog_command_claims.actor_user_id",
                ],
                name="fk_catalog_command_effects_claim",
                ondelete="RESTRICT",
                onupdate="RESTRICT",
            ),
            sa.ForeignKeyConstraint(
                ["site_id"],
                ["sites.id"],
                name="fk_catalog_command_effects_site",
                ondelete="RESTRICT",
                onupdate="RESTRICT",
            ),
            sa.CheckConstraint(
                "response_schema_version = 1", name="ck_catalog_command_effects_schema"
            ),
            sa.CheckConstraint(
                "response_status_code BETWEEN 200 AND 299",
                name="ck_catalog_command_effects_status",
            ),
            **_TABLE_OPTIONS,
        )

    _if_missing(existing, "catalog_command_effects", create_catalog_command_effects)

    def create_catalog_audit_events() -> None:
        op.create_table(
            "catalog_audit_events",
            sa.Column("id", _id_type(), autoincrement=True, nullable=False),
            sa.Column("site_id", _id_type(), nullable=False),
            sa.Column("actor_user_id", _id_type(), nullable=True),
            sa.Column("event_kind", _code_type(64), nullable=False),
            sa.Column("resource_kind", _code_type(24), nullable=False),
            sa.Column("resource_id", _id_type(), nullable=True),
            sa.Column("operation_token", mysql.BINARY(16), nullable=True),
            sa.Column("safe_payload_json", mysql.JSON(), nullable=False),
            sa.Column("event_digest", mysql.BINARY(32), nullable=False),
            _created_at(),
            sa.PrimaryKeyConstraint("id", name="pk_catalog_audit_events"),
            sa.UniqueConstraint(
                "site_id", "event_digest", name="uq_catalog_audit_events_digest"
            ),
            sa.ForeignKeyConstraint(
                ["site_id"],
                ["sites.id"],
                name="fk_catalog_audit_events_site",
                ondelete="RESTRICT",
                onupdate="RESTRICT",
            ),
            sa.ForeignKeyConstraint(
                ["actor_user_id"],
                ["users.id"],
                name="fk_catalog_audit_events_actor",
                ondelete="RESTRICT",
                onupdate="RESTRICT",
            ),
            sa.Index(
                "ix_catalog_audit_events_resource",
                "site_id",
                "resource_kind",
                "resource_id",
                "id",
            ),
            **_TABLE_OPTIONS,
        )

    _if_missing(existing, "catalog_audit_events", create_catalog_audit_events)

    def create_catalog_jobs() -> None:
        op.create_table(
            "catalog_jobs",
            sa.Column("id", _id_type(), autoincrement=True, nullable=False),
            sa.Column("site_id", _id_type(), nullable=False),
            sa.Column("job_kind", _code_type(32), nullable=False),
            sa.Column("resource_kind", _code_type(24), nullable=False),
            sa.Column("resource_id", _id_type(), nullable=False),
            sa.Column("status", _code_type(16), nullable=False),
            sa.Column(
                "job_revision",
                _counter_type(),
                server_default=sa.text("0"),
                nullable=False,
            ),
            sa.Column("lease_token", mysql.BINARY(16), nullable=True),
            sa.Column(
                "fencing_token",
                _counter_type(),
                server_default=sa.text("0"),
                nullable=False,
            ),
            sa.Column("lease_expires_at", _timestamp_type(), nullable=True),
            sa.Column(
                "retry_allowed", sa.Boolean(), server_default=sa.false(), nullable=False
            ),
            sa.Column("failure_reason_code", _code_type(64), nullable=True),
            sa.Column("result_digest", mysql.BINARY(32), nullable=True),
            _created_at(),
            _updated_at(),
            sa.PrimaryKeyConstraint("id", name="pk_catalog_jobs"),
            sa.UniqueConstraint(
                "site_id",
                "job_kind",
                "resource_kind",
                "resource_id",
                name="uq_catalog_jobs_resource",
            ),
            sa.ForeignKeyConstraint(
                ["site_id"],
                ["sites.id"],
                name="fk_catalog_jobs_site",
                ondelete="RESTRICT",
                onupdate="RESTRICT",
            ),
            sa.CheckConstraint(
                "status IN ('queued','running','succeeded','failed','superseded')",
                name="ck_catalog_jobs_status",
            ),
            sa.CheckConstraint(
                "(lease_token IS NULL) = (lease_expires_at IS NULL)",
                name="ck_catalog_jobs_lease",
            ),
            sa.CheckConstraint(
                "NOT retry_allowed OR status='failed'", name="ck_catalog_jobs_retry"
            ),
            sa.Index("ix_catalog_jobs_claim", "status", "lease_expires_at", "id"),
            **_TABLE_OPTIONS,
        )

    _if_missing(existing, "catalog_jobs", create_catalog_jobs)
    _ensure_late_foreign_keys()
    _ensure_immutable_triggers()
    _ensure_publication_snapshot_transition_triggers()
    _ensure_catalog_parse_attempt_transition_triggers()
    _ensure_catalog_command_claim_transition_triggers()


def _assert_downgrade_preconditions() -> None:
    if context.is_offline_mode():
        raise RuntimeError("0022 downgrade requires an online migration connection")
    existing = _existing_catalog_tables()
    if existing:
        union = " UNION ALL ".join(
            f"SELECT COUNT(*) AS count_ FROM `{table_name}`"
            for table_name in _CATALOG_TABLE_ORDER
            if table_name in existing
        )
        total = sum(int(value) for value in op.get_bind().scalars(sa.text(union)))
        if total != 0:
            raise RuntimeError(
                "0022 downgrade refused: product catalog rows still exist"
            )


def downgrade() -> None:
    _assert_downgrade_preconditions()
    _drop_immutable_triggers()
    _drop_late_foreign_keys()
    for table_name in reversed(_CATALOG_TABLE_ORDER):
        op.drop_table(table_name)
    op.drop_index("ix_version_rows_analytics_active", table_name="version_rows")
