"""Add human-confirmed report parsing ownership and success contracts."""

from __future__ import annotations

from typing import Any

import sqlalchemy as sa
from alembic import context, op
from sqlalchemy.dialects import mysql

revision = "0007"
down_revision = "0006"
branch_labels = None
depends_on = None

_TABLE_OPTIONS: dict[str, Any] = {
    "mysql_engine": "InnoDB",
    "mysql_charset": "utf8mb4",
    "mysql_collate": "utf8mb4_0900_ai_ci",
}


def _id_type() -> mysql.BIGINT:
    return mysql.BIGINT(unsigned=True)


def _code_type(length: int) -> mysql.VARCHAR:
    return mysql.VARCHAR(length, charset="ascii", collation="ascii_bin")


def _timestamp_type() -> mysql.DATETIME:
    return mysql.DATETIME(fsp=6)


def _assert_no_rows(*, label: str, query: str) -> None:
    if context.is_offline_mode():
        return
    count = op.get_bind().scalar(sa.text(query))
    if count:
        raise RuntimeError(
            f"0007 migration preflight rejected {count} {label}; "
            "repair the 0006 data before retrying"
        )


def _assert_upgrade_preconditions() -> None:
    """Fail before MySQL's first auto-committing DDL statement."""

    _assert_no_rows(
        label="import batch(es) still marked processing without a recovery token",
        query="SELECT COUNT(*) FROM import_batches WHERE status = 'processing'",
    )
    _assert_no_rows(
        label="parse attempt(s) using a site different from their batch",
        query="""
            SELECT COUNT(*)
            FROM parse_attempts AS attempts
            INNER JOIN import_batches AS batches
                ON batches.id = attempts.batch_id
            INNER JOIN site_config_versions AS attempt_configs
                ON attempt_configs.id = attempts.site_config_version_id
            INNER JOIN site_config_versions AS batch_configs
                ON batch_configs.id = batches.site_config_version_id
            WHERE attempt_configs.site_id <> batch_configs.site_id
        """,
    )
    _assert_no_rows(
        label="non-terminal parse attempt(s)",
        query="""
            SELECT COUNT(*)
            FROM parse_attempts
            WHERE status NOT IN ('succeeded', 'failed')
        """,
    )
    _assert_no_rows(
        label="parse baseline(s) attached to a non-successful attempt",
        query="""
            SELECT COUNT(*)
            FROM parse_baselines AS baselines
            INNER JOIN parse_attempts AS attempts
                ON attempts.id = baselines.parse_attempt_id
            WHERE attempts.status <> 'succeeded'
        """,
    )
    _assert_no_rows(
        label="current parse pointer(s) without a matching successful baseline",
        query="""
            SELECT COUNT(*)
            FROM import_batches AS batches
            INNER JOIN parse_attempts AS attempts
                ON attempts.id = batches.current_successful_parse_attempt_id
            LEFT JOIN parse_baselines AS baselines
                ON baselines.parse_attempt_id = attempts.id
            WHERE batches.current_successful_parse_attempt_id IS NOT NULL
              AND (
                  attempts.status <> 'succeeded'
                  OR baselines.id IS NULL
                  OR baselines.report_type <> batches.report_type
              )
        """,
    )


def _assert_downgrade_preconditions() -> None:
    """Refuse to invent values required by the older non-null schema."""

    _assert_no_rows(
        label="active parse lease(s) that would lose recovery identity",
        query="""
            SELECT COUNT(*)
            FROM import_batches
            WHERE status = 'processing'
               OR processing_token IS NOT NULL
               OR processing_operation_digest IS NOT NULL
               OR processing_started_at IS NOT NULL
        """,
    )
    _assert_no_rows(
        label="batch(es) that cannot be represented by the 0006 downgrade",
        query="""
            SELECT COUNT(*)
            FROM import_batches
            WHERE report_date IS NULL
               OR COALESCE(report_type, confirmed_report_type) IS NULL
        """,
    )
    _assert_no_rows(
        label=(
            "failed parse attempt(s) whose report type cannot be represented "
            "by the 0006 downgrade"
        ),
        query="""
            SELECT COUNT(*)
            FROM parse_attempts AS attempts
            INNER JOIN import_batches AS batches
                ON batches.id = attempts.batch_id
            WHERE attempts.status = 'failed'
              AND attempts.report_type <>
                  COALESCE(batches.report_type, batches.confirmed_report_type)
        """,
    )


def upgrade() -> None:
    _assert_upgrade_preconditions()

    op.add_column("import_batches", sa.Column("site_id", _id_type(), nullable=True))
    op.add_column(
        "import_batches",
        sa.Column("detected_report_type", _code_type(32), nullable=True),
    )
    op.add_column(
        "import_batches",
        sa.Column("detector_version", _code_type(64), nullable=True),
    )
    op.add_column(
        "import_batches",
        sa.Column("detection_summary", mysql.JSON(), nullable=True),
    )
    op.add_column(
        "import_batches",
        sa.Column("detected_at", _timestamp_type(), nullable=True),
    )
    op.add_column(
        "import_batches",
        sa.Column("confirmed_report_type", _code_type(32), nullable=True),
    )
    op.add_column(
        "import_batches",
        sa.Column("confirmation_revision", _id_type(), nullable=True),
    )
    op.add_column(
        "import_batches",
        sa.Column("confirmed_by_user_id", _id_type(), nullable=True),
    )
    op.add_column(
        "import_batches",
        sa.Column("confirmed_at", _timestamp_type(), nullable=True),
    )
    op.add_column(
        "import_batches",
        sa.Column("processing_token", mysql.BINARY(16), nullable=True),
    )
    op.add_column(
        "import_batches",
        sa.Column("processing_operation_digest", mysql.BINARY(32), nullable=True),
    )
    op.add_column(
        "import_batches",
        sa.Column("processing_started_at", _timestamp_type(), nullable=True),
    )

    op.add_column("parse_attempts", sa.Column("site_id", _id_type(), nullable=True))
    op.add_column(
        "parse_attempts",
        sa.Column("processing_token", mysql.BINARY(16), nullable=True),
    )
    op.add_column(
        "parse_attempts",
        sa.Column("operation_digest", mysql.BINARY(32), nullable=True),
    )
    op.add_column(
        "parse_attempts",
        sa.Column("report_type", _code_type(32), nullable=True),
    )
    op.add_column(
        "parse_attempts",
        sa.Column("confirmation_revision", _id_type(), nullable=True),
    )
    op.add_column(
        "parse_baselines",
        sa.Column("attempt_status", sa.String(length=32), nullable=True),
    )

    op.create_table(
        "parse_operation_tokens",
        sa.Column("operation_token", mysql.BINARY(16), nullable=False),
        sa.Column("batch_id", _id_type(), nullable=False),
        sa.Column("operation_digest", mysql.BINARY(32), nullable=False),
        sa.Column("registered_at", _timestamp_type(), nullable=False),
        sa.PrimaryKeyConstraint(
            "operation_token",
            name="pk_parse_operation_tokens",
        ),
        sa.UniqueConstraint(
            "operation_token",
            "batch_id",
            "operation_digest",
            name="uq_parse_operation_tokens_identity",
        ),
        sa.ForeignKeyConstraint(
            ["batch_id"],
            ["import_batches.id"],
            name="fk_parse_operation_tokens_batch",
            ondelete="RESTRICT",
            onupdate="RESTRICT",
        ),
        **_TABLE_OPTIONS,
    )
    op.create_table(
        "report_date_operation_tokens",
        sa.Column("operation_token", mysql.BINARY(16), nullable=False),
        sa.Column("batch_id", _id_type(), nullable=False),
        sa.Column("operation_digest", mysql.BINARY(32), nullable=False),
        sa.Column("registered_at", _timestamp_type(), nullable=False),
        sa.PrimaryKeyConstraint(
            "operation_token",
            name="pk_report_date_operation_tokens",
        ),
        sa.UniqueConstraint(
            "operation_token",
            "batch_id",
            "operation_digest",
            name="uq_report_date_operation_tokens_identity",
        ),
        sa.ForeignKeyConstraint(
            ["batch_id"],
            ["import_batches.id"],
            name="fk_report_date_operation_tokens_batch",
            ondelete="RESTRICT",
            onupdate="RESTRICT",
        ),
        **_TABLE_OPTIONS,
    )

    op.execute(
        sa.text(
            """
            UPDATE import_batches AS batches
            INNER JOIN site_config_versions AS configs
                ON configs.id = batches.site_config_version_id
            SET batches.site_id = configs.site_id,
                batches.confirmed_report_type = batches.report_type,
                batches.confirmation_revision = 1,
                batches.confirmed_by_user_id = batches.created_by_user_id,
                batches.confirmed_at = batches.created_at
            """
        )
    )
    op.execute(
        sa.text(
            """
            UPDATE parse_attempts AS attempts
            INNER JOIN import_batches AS batches
                ON batches.id = attempts.batch_id
            INNER JOIN site_config_versions AS configs
                ON configs.id = attempts.site_config_version_id
            LEFT JOIN parse_baselines AS baselines
                ON baselines.parse_attempt_id = attempts.id
            SET attempts.site_id = configs.site_id,
                attempts.report_type = COALESCE(
                    baselines.report_type,
                    batches.report_type
                ),
                attempts.confirmation_revision = batches.confirmation_revision,
                attempts.completed_at = CASE
                    WHEN attempts.status IN ('succeeded', 'failed')
                        THEN COALESCE(attempts.completed_at, attempts.started_at)
                    ELSE attempts.completed_at
                END
            """
        )
    )
    op.execute(
        sa.text(
            """
            UPDATE parse_attempts
            SET processing_token = UNHEX(LPAD(HEX(id), 32, '0')),
                operation_digest = UNHEX(
                    SHA2(CONCAT('legacy-parse-attempt:', id), 256)
                )
            """
        )
    )
    op.execute(
        sa.text(
            """
            INSERT INTO parse_operation_tokens (
                operation_token, batch_id, operation_digest, registered_at
            )
            SELECT processing_token, batch_id, operation_digest, started_at
            FROM parse_attempts
            """
        )
    )
    op.execute(
        sa.text(
            """
            UPDATE parse_attempts AS attempts
            LEFT JOIN (
                SELECT parse_attempt_id, COUNT(*) AS row_count
                FROM parsed_source_rows
                GROUP BY parse_attempt_id
            ) AS source_counts
                ON source_counts.parse_attempt_id = attempts.id
            SET attempts.source_row_count = COALESCE(
                attempts.source_row_count,
                source_counts.row_count,
                0
            )
            WHERE attempts.status = 'succeeded'
            """
        )
    )
    op.execute(
        sa.text(
            """
            UPDATE parse_baselines
            SET attempt_status = 'succeeded'
            """
        )
    )
    op.execute(
        sa.text(
            """
            UPDATE import_batches AS batches
            INNER JOIN parse_baselines AS baselines
                ON baselines.parse_attempt_id =
                    batches.current_successful_parse_attempt_id
            SET batches.source_row_count = COALESCE(
                batches.source_row_count,
                baselines.row_count
            )
            WHERE batches.current_successful_parse_attempt_id IS NOT NULL
            """
        )
    )
    op.alter_column(
        "import_batches",
        "report_type",
        existing_type=sa.String(length=32),
        type_=_code_type(32),
        existing_nullable=False,
        nullable=True,
    )
    op.execute(
        sa.text(
            """
            UPDATE import_batches
            SET report_type = NULL,
                source_row_count = NULL
            WHERE current_successful_parse_attempt_id IS NULL
            """
        )
    )

    op.alter_column(
        "import_batches",
        "confirmation_revision",
        existing_type=_id_type(),
        nullable=False,
        server_default=sa.text("0"),
    )
    op.alter_column(
        "import_batches",
        "site_id",
        existing_type=_id_type(),
        nullable=False,
    )
    op.alter_column(
        "import_batches",
        "report_date",
        existing_type=sa.Date(),
        existing_nullable=False,
        nullable=True,
    )
    op.alter_column(
        "parse_attempts",
        "site_id",
        existing_type=_id_type(),
        nullable=False,
    )
    op.alter_column(
        "parse_attempts",
        "processing_token",
        existing_type=mysql.BINARY(16),
        nullable=False,
    )
    op.alter_column(
        "parse_attempts",
        "operation_digest",
        existing_type=mysql.BINARY(32),
        nullable=False,
    )
    op.alter_column(
        "parse_attempts",
        "report_type",
        existing_type=_code_type(32),
        nullable=False,
    )
    op.alter_column(
        "parse_attempts",
        "confirmation_revision",
        existing_type=_id_type(),
        nullable=False,
    )
    op.alter_column(
        "parse_baselines",
        "attempt_status",
        existing_type=sa.String(length=32),
        nullable=False,
        server_default=sa.text("'succeeded'"),
    )

    op.alter_column(
        "business_parse_baseline_rows",
        "session_percentage_total",
        new_column_name="conversion_rate_total",
        existing_type=mysql.DECIMAL(precision=12, scale=9),
        existing_nullable=True,
    )
    op.alter_column(
        "business_version_base_rows",
        "session_percentage_total",
        new_column_name="conversion_rate_total",
        existing_type=mysql.DECIMAL(precision=12, scale=9),
        existing_nullable=True,
    )
    op.alter_column(
        "business_report_rows",
        "session_percentage_total",
        new_column_name="conversion_rate_total",
        existing_type=mysql.DECIMAL(precision=12, scale=9),
        existing_nullable=True,
    )

    op.create_check_constraint(
        "ck_import_batches_detected_report_type",
        "import_batches",
        "detected_report_type IS NULL OR "
        "detected_report_type IN ('business_report', 'return_report')",
    )
    op.create_check_constraint(
        "ck_import_batches_confirmed_report_type",
        "import_batches",
        "confirmed_report_type IS NULL OR "
        "confirmed_report_type IN ('business_report', 'return_report')",
    )
    op.create_check_constraint(
        "ck_import_batches_detection_metadata",
        "import_batches",
        "((detected_at IS NULL AND detector_version IS NULL "
        "AND detection_summary IS NULL AND detected_report_type IS NULL) OR "
        "(detected_at IS NOT NULL AND detector_version IS NOT NULL "
        "AND detection_summary IS NOT NULL))",
    )
    op.create_check_constraint(
        "ck_import_batches_confirmation",
        "import_batches",
        "((confirmation_revision = 0 AND confirmed_report_type IS NULL "
        "AND confirmed_by_user_id IS NULL AND confirmed_at IS NULL) OR "
        "(confirmation_revision > 0 AND confirmed_report_type IS NOT NULL "
        "AND report_date IS NOT NULL AND confirmed_by_user_id IS NOT NULL "
        "AND confirmed_at IS NOT NULL))",
    )
    op.create_check_constraint(
        "ck_import_batches_current_parse_metadata",
        "import_batches",
        "((current_successful_parse_attempt_id IS NULL "
        "AND report_type IS NULL AND source_row_count IS NULL) OR "
        "(current_successful_parse_attempt_id IS NOT NULL "
        "AND report_type IS NOT NULL AND source_row_count IS NOT NULL))",
    )
    op.create_check_constraint(
        "ck_import_batches_processing_lease",
        "import_batches",
        "((status = 'processing' AND processing_token IS NOT NULL "
        "AND processing_operation_digest IS NOT NULL "
        "AND confirmation_revision > 0 "
        "AND processing_started_at IS NOT NULL) OR "
        "(status <> 'processing' AND processing_token IS NULL "
        "AND processing_operation_digest IS NULL "
        "AND processing_started_at IS NULL))",
    )
    op.create_check_constraint(
        "ck_parse_attempts_report_type",
        "parse_attempts",
        "report_type IN ('business_report', 'return_report')",
    )
    op.create_check_constraint(
        "ck_parse_attempts_confirmation_revision",
        "parse_attempts",
        "confirmation_revision > 0",
    )
    op.create_check_constraint(
        "ck_parse_attempts_lifecycle",
        "parse_attempts",
        "status IN ('succeeded', 'failed') AND completed_at IS NOT NULL",
    )
    op.create_check_constraint(
        "ck_parse_attempts_success_count",
        "parse_attempts",
        "status <> 'succeeded' OR source_row_count IS NOT NULL",
    )
    op.create_check_constraint(
        "ck_parse_baselines_attempt_status",
        "parse_baselines",
        "attempt_status = 'succeeded'",
    )

    op.create_unique_constraint(
        "uq_import_batches_id_site",
        "import_batches",
        ["id", "site_id"],
    )
    op.create_unique_constraint(
        "uq_import_batches_processing_token",
        "import_batches",
        ["processing_token"],
    )
    op.create_unique_constraint(
        "uq_parse_attempts_id_type_status",
        "parse_attempts",
        ["id", "report_type", "status"],
    )
    op.create_unique_constraint(
        "uq_parse_attempts_processing_token",
        "parse_attempts",
        ["processing_token"],
    )
    op.create_unique_constraint(
        "uq_parse_baselines_attempt_type",
        "parse_baselines",
        ["parse_attempt_id", "report_type"],
    )

    op.create_index(
        "ix_import_batches_confirmation_queue",
        "import_batches",
        ["status", "confirmed_at", "created_at", "id"],
    )
    op.create_index(
        "ix_import_batches_processing_recovery",
        "import_batches",
        ["status", "processing_started_at", "id"],
    )
    op.create_index(
        "ix_import_batches_site_config_owner",
        "import_batches",
        ["site_id", "site_config_version_id"],
    )
    op.create_index(
        "ix_import_batches_current_parse_baseline",
        "import_batches",
        ["current_successful_parse_attempt_id", "report_type"],
    )
    op.create_index(
        "ix_parse_attempts_batch_site",
        "parse_attempts",
        ["batch_id", "site_id"],
    )
    op.create_index(
        "ix_parse_attempts_site_config_owner",
        "parse_attempts",
        ["site_id", "site_config_version_id"],
    )
    op.create_index(
        "ix_parse_baselines_attempt_type_status",
        "parse_baselines",
        ["parse_attempt_id", "report_type", "attempt_status"],
    )

    op.create_foreign_key(
        "fk_import_batches_site_config_owner",
        "import_batches",
        "site_config_versions",
        ["site_id", "site_config_version_id"],
        ["site_id", "id"],
        ondelete="RESTRICT",
        onupdate="RESTRICT",
    )
    op.create_foreign_key(
        "fk_import_batches_confirmed_by",
        "import_batches",
        "users",
        ["confirmed_by_user_id"],
        ["id"],
        ondelete="RESTRICT",
        onupdate="RESTRICT",
    )
    op.create_foreign_key(
        "fk_import_batches_parse_operation_token",
        "import_batches",
        "parse_operation_tokens",
        ["processing_token", "id", "processing_operation_digest"],
        ["operation_token", "batch_id", "operation_digest"],
        ondelete="RESTRICT",
        onupdate="RESTRICT",
    )
    op.create_foreign_key(
        "fk_parse_attempts_batch_site",
        "parse_attempts",
        "import_batches",
        ["batch_id", "site_id"],
        ["id", "site_id"],
        ondelete="RESTRICT",
        onupdate="RESTRICT",
    )
    op.create_foreign_key(
        "fk_parse_attempts_operation_token",
        "parse_attempts",
        "parse_operation_tokens",
        ["processing_token", "batch_id", "operation_digest"],
        ["operation_token", "batch_id", "operation_digest"],
        ondelete="RESTRICT",
        onupdate="RESTRICT",
    )
    op.create_foreign_key(
        "fk_parse_attempts_site_config_owner",
        "parse_attempts",
        "site_config_versions",
        ["site_id", "site_config_version_id"],
        ["site_id", "id"],
        ondelete="RESTRICT",
        onupdate="RESTRICT",
    )
    op.create_foreign_key(
        "fk_parse_baselines_successful_attempt",
        "parse_baselines",
        "parse_attempts",
        ["parse_attempt_id", "report_type", "attempt_status"],
        ["id", "report_type", "status"],
        ondelete="RESTRICT",
        onupdate="RESTRICT",
    )
    op.create_foreign_key(
        "fk_import_batches_current_parse_baseline",
        "import_batches",
        "parse_baselines",
        ["current_successful_parse_attempt_id", "report_type"],
        ["parse_attempt_id", "report_type"],
        ondelete="RESTRICT",
        onupdate="RESTRICT",
    )


def downgrade() -> None:
    _assert_downgrade_preconditions()

    op.drop_constraint(
        "fk_import_batches_parse_operation_token",
        "import_batches",
        type_="foreignkey",
    )
    op.drop_constraint(
        "fk_parse_attempts_operation_token",
        "parse_attempts",
        type_="foreignkey",
    )
    op.drop_table("report_date_operation_tokens")
    op.drop_table("parse_operation_tokens")

    op.drop_constraint(
        "fk_import_batches_current_parse_baseline",
        "import_batches",
        type_="foreignkey",
    )
    op.drop_constraint(
        "fk_parse_baselines_successful_attempt",
        "parse_baselines",
        type_="foreignkey",
    )
    op.drop_constraint(
        "fk_parse_attempts_site_config_owner",
        "parse_attempts",
        type_="foreignkey",
    )
    op.drop_constraint(
        "fk_parse_attempts_batch_site",
        "parse_attempts",
        type_="foreignkey",
    )
    op.drop_constraint(
        "fk_import_batches_confirmed_by",
        "import_batches",
        type_="foreignkey",
    )
    op.drop_constraint(
        "fk_import_batches_site_config_owner",
        "import_batches",
        type_="foreignkey",
    )

    op.drop_index(
        "ix_parse_baselines_attempt_type_status",
        table_name="parse_baselines",
    )
    op.drop_index(
        "ix_parse_attempts_site_config_owner",
        table_name="parse_attempts",
    )
    op.drop_index("ix_parse_attempts_batch_site", table_name="parse_attempts")
    op.drop_index(
        "ix_import_batches_current_parse_baseline",
        table_name="import_batches",
    )
    op.drop_index(
        "ix_import_batches_site_config_owner",
        table_name="import_batches",
    )
    op.drop_index(
        "ix_import_batches_processing_recovery",
        table_name="import_batches",
    )
    op.drop_index(
        "ix_import_batches_confirmation_queue",
        table_name="import_batches",
    )

    op.drop_constraint(
        "uq_parse_baselines_attempt_type",
        "parse_baselines",
        type_="unique",
    )
    op.drop_constraint(
        "uq_parse_attempts_processing_token",
        "parse_attempts",
        type_="unique",
    )
    op.drop_constraint(
        "uq_parse_attempts_id_type_status",
        "parse_attempts",
        type_="unique",
    )
    op.drop_constraint(
        "uq_import_batches_processing_token",
        "import_batches",
        type_="unique",
    )
    op.drop_constraint(
        "uq_import_batches_id_site",
        "import_batches",
        type_="unique",
    )

    for constraint_name, table_name in (
        ("ck_parse_baselines_attempt_status", "parse_baselines"),
        ("ck_parse_attempts_success_count", "parse_attempts"),
        ("ck_parse_attempts_lifecycle", "parse_attempts"),
        ("ck_parse_attempts_confirmation_revision", "parse_attempts"),
        ("ck_parse_attempts_report_type", "parse_attempts"),
        ("ck_import_batches_processing_lease", "import_batches"),
        ("ck_import_batches_current_parse_metadata", "import_batches"),
        ("ck_import_batches_confirmation", "import_batches"),
        ("ck_import_batches_detection_metadata", "import_batches"),
        ("ck_import_batches_confirmed_report_type", "import_batches"),
        ("ck_import_batches_detected_report_type", "import_batches"),
    ):
        op.drop_constraint(constraint_name, table_name, type_="check")

    op.alter_column(
        "business_report_rows",
        "conversion_rate_total",
        new_column_name="session_percentage_total",
        existing_type=mysql.DECIMAL(precision=12, scale=9),
        existing_nullable=True,
    )
    op.alter_column(
        "business_version_base_rows",
        "conversion_rate_total",
        new_column_name="session_percentage_total",
        existing_type=mysql.DECIMAL(precision=12, scale=9),
        existing_nullable=True,
    )
    op.alter_column(
        "business_parse_baseline_rows",
        "conversion_rate_total",
        new_column_name="session_percentage_total",
        existing_type=mysql.DECIMAL(precision=12, scale=9),
        existing_nullable=True,
    )

    op.execute(
        sa.text(
            """
            UPDATE import_batches
            SET report_type = COALESCE(report_type, confirmed_report_type)
            """
        )
    )
    op.alter_column(
        "import_batches",
        "report_type",
        existing_type=_code_type(32),
        type_=sa.String(length=32),
        existing_nullable=True,
        nullable=False,
    )
    op.alter_column(
        "import_batches",
        "report_date",
        existing_type=sa.Date(),
        existing_nullable=True,
        nullable=False,
    )

    op.drop_column("parse_baselines", "attempt_status")
    op.drop_column("parse_attempts", "confirmation_revision")
    op.drop_column("parse_attempts", "report_type")
    op.drop_column("parse_attempts", "operation_digest")
    op.drop_column("parse_attempts", "processing_token")
    op.drop_column("parse_attempts", "site_id")
    op.drop_column("import_batches", "processing_started_at")
    op.drop_column("import_batches", "processing_operation_digest")
    op.drop_column("import_batches", "processing_token")
    op.drop_column("import_batches", "confirmed_at")
    op.drop_column("import_batches", "confirmed_by_user_id")
    op.drop_column("import_batches", "confirmation_revision")
    op.drop_column("import_batches", "confirmed_report_type")
    op.drop_column("import_batches", "detected_at")
    op.drop_column("import_batches", "detection_summary")
    op.drop_column("import_batches", "detector_version")
    op.drop_column("import_batches", "detected_report_type")
    op.drop_column("import_batches", "site_id")
