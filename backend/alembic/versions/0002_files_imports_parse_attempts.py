"""Create immutable raw-file, import, and parse-attempt storage."""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import mysql

revision = "0002"
down_revision = "0001"
branch_labels = None
depends_on = None


_TABLE_OPTIONS = {
    "mysql_engine": "InnoDB",
    "mysql_charset": "utf8mb4",
    "mysql_collate": "utf8mb4_0900_ai_ci",
}


def _bigint() -> mysql.BIGINT:
    return mysql.BIGINT(unsigned=True)


def _utc_datetime() -> mysql.DATETIME:
    return mysql.DATETIME(fsp=6)


def upgrade() -> None:
    op.create_table(
        "raw_files",
        sa.Column("id", _bigint(), autoincrement=True, nullable=False),
        sa.Column("sha256", mysql.BINARY(length=32), nullable=False),
        sa.Column("storage_key", sa.String(length=512), nullable=False),
        sa.Column("original_filename", sa.String(length=255), nullable=False),
        sa.Column("media_type", sa.String(length=127), nullable=True),
        sa.Column("size_bytes", _bigint(), nullable=False),
        sa.Column("uploaded_by_user_id", _bigint(), nullable=False),
        sa.Column(
            "uploaded_at",
            _utc_datetime(),
            server_default=sa.text("CURRENT_TIMESTAMP(6)"),
            nullable=False,
        ),
        sa.CheckConstraint("size_bytes >= 0", name="ck_raw_files_size_nonnegative"),
        sa.ForeignKeyConstraint(
            ["uploaded_by_user_id"],
            ["users.id"],
            name="fk_raw_files_uploaded_by",
            ondelete="RESTRICT",
            onupdate="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_raw_files"),
        sa.UniqueConstraint("sha256", name="uq_raw_files_sha256"),
        sa.UniqueConstraint("storage_key", name="uq_raw_files_storage_key"),
        **_TABLE_OPTIONS,
    )

    op.create_table(
        "file_ingest_leases",
        sa.Column("id", _bigint(), autoincrement=True, nullable=False),
        sa.Column("lease_token", mysql.BINARY(length=16), nullable=False),
        sa.Column("temporary_path", sa.String(length=512), nullable=False),
        sa.Column("storage_key", sa.String(length=512), nullable=True),
        sa.Column("sha256", mysql.BINARY(length=32), nullable=True),
        sa.Column("size_bytes", _bigint(), nullable=True),
        sa.Column("raw_file_id", _bigint(), nullable=True),
        sa.Column("created_by_user_id", _bigint(), nullable=False),
        sa.Column(
            "status",
            sa.String(length=32),
            server_default=sa.text("'active'"),
            nullable=False,
        ),
        sa.Column("expires_at", _utc_datetime(), nullable=False),
        sa.Column("completed_at", _utc_datetime(), nullable=True),
        sa.Column(
            "created_at",
            _utc_datetime(),
            server_default=sa.text("CURRENT_TIMESTAMP(6)"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "size_bytes IS NULL OR size_bytes >= 0",
            name="ck_file_ingest_leases_size_nonnegative",
        ),
        sa.CheckConstraint(
            "status IN ('active', 'committing', 'completed', 'expired', 'failed')",
            name="ck_file_ingest_leases_status",
        ),
        sa.ForeignKeyConstraint(
            ["raw_file_id"],
            ["raw_files.id"],
            name="fk_file_ingest_leases_raw_file",
            ondelete="RESTRICT",
            onupdate="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["created_by_user_id"],
            ["users.id"],
            name="fk_file_ingest_leases_created_by",
            ondelete="RESTRICT",
            onupdate="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_file_ingest_leases"),
        sa.UniqueConstraint("lease_token", name="uq_file_ingest_leases_token"),
        **_TABLE_OPTIONS,
    )
    op.create_index(
        "ix_file_ingest_leases_status_expires",
        "file_ingest_leases",
        ["status", "expires_at"],
        unique=False,
    )

    # The nullable current-attempt column is created before parse_attempts, but its
    # ownership-enforcing foreign key is deliberately added only after that table.
    op.create_table(
        "import_batches",
        sa.Column("id", _bigint(), autoincrement=True, nullable=False),
        sa.Column("raw_file_id", _bigint(), nullable=False),
        sa.Column("site_config_version_id", _bigint(), nullable=False),
        sa.Column("report_type", sa.String(length=32), nullable=False),
        sa.Column("detected_report_date", sa.Date(), nullable=True),
        sa.Column("report_date", sa.Date(), nullable=False),
        sa.Column(
            "status",
            sa.String(length=32),
            server_default=sa.text("'uploaded'"),
            nullable=False,
        ),
        sa.Column("current_successful_parse_attempt_id", _bigint(), nullable=True),
        sa.Column("source_row_count", _bigint(), nullable=True),
        sa.Column("error_summary", mysql.JSON(), nullable=True),
        sa.Column("created_by_user_id", _bigint(), nullable=False),
        sa.Column(
            "created_at",
            _utc_datetime(),
            server_default=sa.text("CURRENT_TIMESTAMP(6)"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            _utc_datetime(),
            server_default=sa.text("CURRENT_TIMESTAMP(6)"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "report_type IN ('business_report', 'return_report')",
            name="ck_import_batches_report_type",
        ),
        sa.CheckConstraint(
            "status IN "
            "('uploaded', 'processing', 'staged', 'processing_failed', 'rejected')",
            name="ck_import_batches_status",
        ),
        sa.CheckConstraint(
            "source_row_count IS NULL OR source_row_count >= 0",
            name="ck_import_batches_row_count_nonnegative",
        ),
        sa.ForeignKeyConstraint(
            ["raw_file_id"],
            ["raw_files.id"],
            name="fk_import_batches_raw_file",
            ondelete="RESTRICT",
            onupdate="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["site_config_version_id"],
            ["site_config_versions.id"],
            name="fk_import_batches_site_config",
            ondelete="RESTRICT",
            onupdate="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["created_by_user_id"],
            ["users.id"],
            name="fk_import_batches_created_by",
            ondelete="RESTRICT",
            onupdate="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_import_batches"),
        sa.UniqueConstraint("raw_file_id", name="uq_import_batches_raw_file"),
        **_TABLE_OPTIONS,
    )
    op.create_index(
        "ix_import_batches_report_date_type",
        "import_batches",
        ["report_date", "report_type"],
        unique=False,
    )
    op.create_index(
        "ix_import_batches_current_parse_attempt",
        "import_batches",
        ["id", "current_successful_parse_attempt_id"],
        unique=False,
    )

    op.create_table(
        "parse_attempts",
        sa.Column("id", _bigint(), autoincrement=True, nullable=False),
        sa.Column("batch_id", _bigint(), nullable=False),
        sa.Column("site_config_version_id", _bigint(), nullable=False),
        sa.Column("attempt_number", _bigint(), nullable=False),
        sa.Column("parser_version", sa.String(length=64), nullable=False),
        sa.Column("ruleset_version", sa.String(length=64), nullable=False),
        sa.Column("encoding", sa.String(length=64), nullable=True),
        sa.Column("delimiter", sa.String(length=8), nullable=True),
        sa.Column("field_mapping", mysql.JSON(), nullable=True),
        sa.Column(
            "status",
            sa.String(length=32),
            server_default=sa.text("'running'"),
            nullable=False,
        ),
        sa.Column("source_row_count", _bigint(), nullable=True),
        sa.Column("result_summary", mysql.JSON(), nullable=True),
        sa.Column("error_summary", mysql.JSON(), nullable=True),
        sa.Column("created_by_user_id", _bigint(), nullable=False),
        sa.Column(
            "started_at",
            _utc_datetime(),
            server_default=sa.text("CURRENT_TIMESTAMP(6)"),
            nullable=False,
        ),
        sa.Column("completed_at", _utc_datetime(), nullable=True),
        sa.CheckConstraint(
            "attempt_number > 0",
            name="ck_parse_attempts_number_positive",
        ),
        sa.CheckConstraint(
            "status IN ('running', 'succeeded', 'failed')",
            name="ck_parse_attempts_status",
        ),
        sa.CheckConstraint(
            "source_row_count IS NULL OR source_row_count >= 0",
            name="ck_parse_attempts_row_count_nonnegative",
        ),
        sa.ForeignKeyConstraint(
            ["batch_id"],
            ["import_batches.id"],
            name="fk_parse_attempts_batch",
            ondelete="RESTRICT",
            onupdate="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["site_config_version_id"],
            ["site_config_versions.id"],
            name="fk_parse_attempts_site_config",
            ondelete="RESTRICT",
            onupdate="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["created_by_user_id"],
            ["users.id"],
            name="fk_parse_attempts_created_by",
            ondelete="RESTRICT",
            onupdate="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_parse_attempts"),
        sa.UniqueConstraint(
            "batch_id",
            "attempt_number",
            name="uq_parse_attempts_batch_number",
        ),
        sa.UniqueConstraint(
            "batch_id",
            "id",
            name="uq_parse_attempts_batch_id",
        ),
        **_TABLE_OPTIONS,
    )

    op.create_table(
        "parsed_source_rows",
        sa.Column("id", _bigint(), autoincrement=True, nullable=False),
        sa.Column("parse_attempt_id", _bigint(), nullable=False),
        sa.Column("source_row_number", _bigint(), nullable=False),
        sa.Column("decoded_fields", mysql.JSON(), nullable=False),
        sa.Column("row_digest", mysql.BINARY(length=32), nullable=False),
        sa.Column(
            "created_at",
            _utc_datetime(),
            server_default=sa.text("CURRENT_TIMESTAMP(6)"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "source_row_number > 0",
            name="ck_parsed_source_rows_number_positive",
        ),
        sa.ForeignKeyConstraint(
            ["parse_attempt_id"],
            ["parse_attempts.id"],
            name="fk_parsed_source_rows_attempt",
            ondelete="RESTRICT",
            onupdate="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_parsed_source_rows"),
        sa.UniqueConstraint(
            "parse_attempt_id",
            "source_row_number",
            name="uq_parsed_source_rows_attempt_number",
        ),
        sa.UniqueConstraint(
            "parse_attempt_id",
            "id",
            name="uq_parsed_source_rows_attempt_id",
        ),
        **_TABLE_OPTIONS,
    )

    op.create_foreign_key(
        "fk_import_batches_current_parse_attempt",
        "import_batches",
        "parse_attempts",
        ["id", "current_successful_parse_attempt_id"],
        ["batch_id", "id"],
        ondelete="RESTRICT",
        onupdate="RESTRICT",
    )


def downgrade() -> None:
    op.drop_constraint(
        "fk_import_batches_current_parse_attempt",
        "import_batches",
        type_="foreignkey",
    )
    op.drop_table("parsed_source_rows")
    op.drop_table("parse_attempts")
    op.drop_table("import_batches")
    op.drop_table("file_ingest_leases")
    op.drop_table("raw_files")
