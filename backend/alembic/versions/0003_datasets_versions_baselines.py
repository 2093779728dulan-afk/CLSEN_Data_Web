"""Create datasets, immutable baselines, snapshots, and typed version rows."""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import mysql

revision = "0003"
down_revision = "0002"
branch_labels = None
depends_on = None


_TABLE_OPTIONS = {
    "mysql_engine": "InnoDB",
    "mysql_charset": "utf8mb4",
    "mysql_collate": "utf8mb4_0900_ai_ci",
}


def _id_type() -> mysql.BIGINT:
    return mysql.BIGINT(unsigned=True)


def _count_type() -> mysql.BIGINT:
    return mysql.BIGINT(unsigned=True)


def _code_type(length: int) -> mysql.VARCHAR:
    return mysql.VARCHAR(length, charset="ascii", collation="ascii_bin")


def _timestamp_type() -> mysql.DATETIME:
    return mysql.DATETIME(fsp=6)


def _business_columns() -> list[sa.Column]:
    return [
        sa.Column("parent_asin", sa.String(length=32), nullable=True),
        sa.Column("child_asin", sa.String(length=32), nullable=True),
        sa.Column("title", mysql.LONGTEXT(), nullable=True),
        sa.Column("sku", sa.String(length=255), nullable=True),
        sa.Column("sessions_total", sa.BigInteger(), nullable=True),
        sa.Column("sessions_b2b", sa.BigInteger(), nullable=True),
        sa.Column(
            "session_percentage_total",
            mysql.DECIMAL(precision=12, scale=9),
            nullable=True,
        ),
        sa.Column(
            "session_percentage_b2b",
            mysql.DECIMAL(precision=12, scale=9),
            nullable=True,
        ),
        sa.Column("page_views_total", sa.BigInteger(), nullable=True),
        sa.Column("page_views_b2b", sa.BigInteger(), nullable=True),
        sa.Column(
            "page_view_percentage_total",
            mysql.DECIMAL(precision=12, scale=9),
            nullable=True,
        ),
        sa.Column(
            "page_view_percentage_b2b",
            mysql.DECIMAL(precision=12, scale=9),
            nullable=True,
        ),
        sa.Column(
            "featured_offer_percentage",
            mysql.DECIMAL(precision=12, scale=9),
            nullable=True,
        ),
        sa.Column(
            "featured_offer_percentage_b2b",
            mysql.DECIMAL(precision=12, scale=9),
            nullable=True,
        ),
        sa.Column("units_ordered", sa.BigInteger(), nullable=True),
        sa.Column("units_ordered_b2b", sa.BigInteger(), nullable=True),
        sa.Column(
            "unit_session_percentage",
            mysql.DECIMAL(precision=12, scale=9),
            nullable=True,
        ),
        sa.Column(
            "unit_session_percentage_b2b",
            mysql.DECIMAL(precision=12, scale=9),
            nullable=True,
        ),
        sa.Column(
            "ordered_product_sales",
            mysql.DECIMAL(precision=20, scale=6),
            nullable=True,
        ),
        sa.Column(
            "ordered_product_sales_b2b",
            mysql.DECIMAL(precision=20, scale=6),
            nullable=True,
        ),
        sa.Column(
            "currency_code",
            mysql.CHAR(3, charset="ascii", collation="ascii_bin"),
            nullable=True,
        ),
        sa.Column("total_order_items", sa.BigInteger(), nullable=True),
        sa.Column("total_order_items_b2b", sa.BigInteger(), nullable=True),
    ]


def _return_columns() -> list[sa.Column]:
    return [
        sa.Column("return_date", _timestamp_type(), nullable=True),
        sa.Column("order_id", sa.String(length=128), nullable=True),
        sa.Column("sku", sa.String(length=255), nullable=True),
        sa.Column("asin", sa.String(length=32), nullable=True),
        sa.Column("fnsku", sa.String(length=64), nullable=True),
        sa.Column("product_name", mysql.LONGTEXT(), nullable=True),
        sa.Column("quantity", sa.BigInteger(), nullable=True),
        sa.Column("fulfillment_center_id", sa.String(length=64), nullable=True),
        sa.Column("detailed_disposition", sa.String(length=128), nullable=True),
        sa.Column("reason", sa.String(length=255), nullable=True),
        sa.Column("status", sa.String(length=128), nullable=True),
        sa.Column("license_plate_number", sa.String(length=255), nullable=True),
        sa.Column("customer_comments", mysql.LONGTEXT(), nullable=True),
    ]


def upgrade() -> None:
    op.create_table(
        "daily_datasets",
        sa.Column("id", _id_type(), autoincrement=True, nullable=False),
        sa.Column("site_id", _id_type(), nullable=False),
        sa.Column("report_date", sa.Date(), nullable=False),
        sa.Column("report_type", _code_type(32), nullable=False),
        sa.Column(
            "created_at",
            _timestamp_type(),
            server_default=sa.text("CURRENT_TIMESTAMP(6)"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id", name="pk_daily_datasets"),
        sa.ForeignKeyConstraint(
            ["site_id"],
            ["sites.id"],
            name="fk_daily_datasets_site",
            ondelete="RESTRICT",
        ),
        sa.UniqueConstraint(
            "report_date",
            "report_type",
            name="uq_daily_datasets_business",
        ),
        sa.UniqueConstraint("id", "report_type", name="uq_daily_datasets_id_type"),
        sa.CheckConstraint(
            "report_type IN ('business_report', 'return_report')",
            name="ck_daily_datasets_type",
        ),
        **_TABLE_OPTIONS,
    )

    op.create_table(
        "dataset_versions",
        sa.Column("id", _id_type(), autoincrement=True, nullable=False),
        sa.Column("dataset_id", _id_type(), nullable=False),
        sa.Column("report_type", _code_type(32), nullable=False),
        sa.Column("version_no", _id_type(), nullable=False),
        sa.Column(
            "status",
            _code_type(32),
            server_default=sa.text("'draft'"),
            nullable=False,
        ),
        sa.Column(
            "data_revision",
            _id_type(),
            server_default=sa.text("0"),
            nullable=False,
        ),
        sa.Column(
            "review_revision",
            _id_type(),
            server_default=sa.text("0"),
            nullable=False,
        ),
        sa.Column("ruleset_version", _code_type(128), nullable=False),
        sa.Column("created_by", _id_type(), nullable=False),
        sa.Column(
            "created_at",
            _timestamp_type(),
            server_default=sa.text("CURRENT_TIMESTAMP(6)"),
            nullable=False,
        ),
        sa.Column("sealed_at", _timestamp_type(), nullable=True),
        sa.PrimaryKeyConstraint("id", name="pk_dataset_versions"),
        sa.ForeignKeyConstraint(
            ["dataset_id", "report_type"],
            ["daily_datasets.id", "daily_datasets.report_type"],
            name="fk_dataset_versions_dataset_type",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["created_by"],
            ["users.id"],
            name="fk_dataset_versions_created_by",
            ondelete="RESTRICT",
        ),
        sa.UniqueConstraint(
            "dataset_id",
            "version_no",
            name="uq_dataset_versions_no",
        ),
        sa.UniqueConstraint(
            "dataset_id",
            "id",
            name="uq_dataset_versions_dataset_id",
        ),
        sa.UniqueConstraint(
            "id",
            "report_type",
            name="uq_dataset_versions_id_type",
        ),
        sa.CheckConstraint(
            "status IN ('draft', 'ready_for_publish', 'published', 'discarded')",
            name="ck_dataset_versions_status",
        ),
        **_TABLE_OPTIONS,
    )

    op.create_table(
        "version_parent_versions",
        sa.Column("child_version_id", _id_type(), nullable=False),
        sa.Column("parent_version_id", _id_type(), nullable=False),
        sa.Column("parent_ordinal", _count_type(), nullable=False),
        sa.Column("lineage_type", _code_type(32), nullable=False),
        sa.Column(
            "created_at",
            _timestamp_type(),
            server_default=sa.text("CURRENT_TIMESTAMP(6)"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint(
            "child_version_id",
            "parent_version_id",
            "lineage_type",
            name="pk_version_parent_versions",
        ),
        sa.ForeignKeyConstraint(
            ["child_version_id"],
            ["dataset_versions.id"],
            name="fk_vpv_child",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["parent_version_id"],
            ["dataset_versions.id"],
            name="fk_vpv_parent",
            ondelete="RESTRICT",
        ),
        sa.UniqueConstraint(
            "child_version_id",
            "parent_ordinal",
            name="uq_vpv_child_ordinal",
        ),
        sa.CheckConstraint(
            "child_version_id <> parent_version_id",
            name="ck_vpv_not_self",
        ),
        sa.CheckConstraint(
            "lineage_type IN ('base', 'draft_predecessor', 'merge_target', "
            "'merge_source', 'moved_source')",
            name="ck_vpv_type",
        ),
        **_TABLE_OPTIONS,
    )

    op.create_table(
        "version_input_batches",
        sa.Column("version_id", _id_type(), nullable=False),
        sa.Column("batch_id", _id_type(), nullable=False),
        sa.Column("input_ordinal", _count_type(), nullable=False),
        sa.Column("input_role", _code_type(32), nullable=False),
        sa.Column(
            "created_at",
            _timestamp_type(),
            server_default=sa.text("CURRENT_TIMESTAMP(6)"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint(
            "version_id",
            "batch_id",
            name="pk_version_input_batches",
        ),
        sa.ForeignKeyConstraint(
            ["version_id"],
            ["dataset_versions.id"],
            name="fk_vib_version",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["batch_id"],
            ["import_batches.id"],
            name="fk_vib_batch",
            ondelete="RESTRICT",
        ),
        sa.UniqueConstraint(
            "version_id",
            "input_ordinal",
            name="uq_vib_version_ordinal",
        ),
        sa.CheckConstraint(
            "input_role IN ('primary', 'merge_source', 'replacement', 'moved_source')",
            name="ck_vib_role",
        ),
        **_TABLE_OPTIONS,
    )

    op.create_table(
        "dataset_drafts",
        sa.Column("dataset_id", _id_type(), nullable=False),
        sa.Column("version_id", _id_type(), nullable=False),
        sa.Column(
            "pointed_at",
            _timestamp_type(),
            server_default=sa.text("CURRENT_TIMESTAMP(6)"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("dataset_id", name="pk_dataset_drafts"),
        sa.ForeignKeyConstraint(
            ["dataset_id", "version_id"],
            ["dataset_versions.dataset_id", "dataset_versions.id"],
            name="fk_dataset_drafts_version",
            ondelete="RESTRICT",
        ),
        **_TABLE_OPTIONS,
    )

    op.create_table(
        "dataset_publications",
        sa.Column("dataset_id", _id_type(), nullable=False),
        sa.Column("version_id", _id_type(), nullable=False),
        sa.Column(
            "published_at",
            _timestamp_type(),
            server_default=sa.text("CURRENT_TIMESTAMP(6)"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("dataset_id", name="pk_dataset_publications"),
        sa.ForeignKeyConstraint(
            ["dataset_id", "version_id"],
            ["dataset_versions.dataset_id", "dataset_versions.id"],
            name="fk_dataset_publications_version",
            ondelete="RESTRICT",
        ),
        **_TABLE_OPTIONS,
    )

    op.create_table(
        "parse_baselines",
        sa.Column("id", _id_type(), autoincrement=True, nullable=False),
        sa.Column("parse_attempt_id", _id_type(), nullable=False),
        sa.Column("report_type", _code_type(32), nullable=False),
        sa.Column("parser_version", _code_type(128), nullable=False),
        sa.Column("ruleset_version", _code_type(128), nullable=False),
        sa.Column("data_digest", mysql.BINARY(32), nullable=False),
        sa.Column("row_count", _count_type(), nullable=False),
        sa.Column("totals_json", mysql.JSON(), nullable=False),
        sa.Column(
            "created_at",
            _timestamp_type(),
            server_default=sa.text("CURRENT_TIMESTAMP(6)"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id", name="pk_parse_baselines"),
        sa.ForeignKeyConstraint(
            ["parse_attempt_id"],
            ["parse_attempts.id"],
            name="fk_parse_baselines_attempt",
            ondelete="RESTRICT",
        ),
        sa.UniqueConstraint(
            "parse_attempt_id",
            name="uq_parse_baselines_attempt",
        ),
        sa.UniqueConstraint(
            "parse_attempt_id",
            "id",
            "report_type",
            name="uq_parse_baselines_attempt_id_type",
        ),
        sa.UniqueConstraint(
            "id",
            "report_type",
            name="uq_parse_baselines_id_type",
        ),
        sa.CheckConstraint(
            "report_type IN ('business_report', 'return_report')",
            name="ck_parse_baselines_type",
        ),
        **_TABLE_OPTIONS,
    )

    op.create_table(
        "parse_baseline_rows",
        sa.Column("id", _id_type(), autoincrement=True, nullable=False),
        sa.Column("parse_baseline_id", _id_type(), nullable=False),
        sa.Column("parse_attempt_id", _id_type(), nullable=False),
        sa.Column("parsed_source_row_id", _id_type(), nullable=False),
        sa.Column("report_type", _code_type(32), nullable=False),
        sa.Column("row_ordinal", _count_type(), nullable=False),
        sa.Column("row_digest", mysql.BINARY(32), nullable=False),
        sa.Column(
            "created_at",
            _timestamp_type(),
            server_default=sa.text("CURRENT_TIMESTAMP(6)"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id", name="pk_parse_baseline_rows"),
        sa.ForeignKeyConstraint(
            ["parse_attempt_id", "parse_baseline_id", "report_type"],
            [
                "parse_baselines.parse_attempt_id",
                "parse_baselines.id",
                "parse_baselines.report_type",
            ],
            name="fk_pbr_baseline",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["parse_attempt_id", "parsed_source_row_id"],
            ["parsed_source_rows.parse_attempt_id", "parsed_source_rows.id"],
            name="fk_pbr_source_row",
            ondelete="RESTRICT",
        ),
        sa.UniqueConstraint(
            "parse_baseline_id",
            "row_ordinal",
            name="uq_pbr_baseline_ordinal",
        ),
        sa.UniqueConstraint(
            "parse_baseline_id",
            "parsed_source_row_id",
            name="uq_pbr_baseline_source",
        ),
        sa.UniqueConstraint(
            "parse_baseline_id",
            "id",
            "report_type",
            name="uq_pbr_baseline_id_type",
        ),
        sa.CheckConstraint(
            "report_type IN ('business_report', 'return_report')",
            name="ck_pbr_type",
        ),
        **_TABLE_OPTIONS,
    )

    op.create_table(
        "business_parse_baseline_rows",
        sa.Column("parse_baseline_row_id", _id_type(), nullable=False),
        sa.Column("parse_baseline_id", _id_type(), nullable=False),
        sa.Column(
            "report_type",
            _code_type(32),
            server_default=sa.text("'business_report'"),
            nullable=False,
        ),
        *_business_columns(),
        sa.PrimaryKeyConstraint(
            "parse_baseline_row_id",
            name="pk_business_parse_rows",
        ),
        sa.ForeignKeyConstraint(
            ["parse_baseline_id", "parse_baseline_row_id", "report_type"],
            [
                "parse_baseline_rows.parse_baseline_id",
                "parse_baseline_rows.id",
                "parse_baseline_rows.report_type",
            ],
            name="fk_business_parse_rows_parent",
            ondelete="RESTRICT",
        ),
        sa.CheckConstraint(
            "report_type = 'business_report'",
            name="ck_business_parse_rows_type",
        ),
        **_TABLE_OPTIONS,
    )

    op.create_table(
        "return_parse_baseline_rows",
        sa.Column("parse_baseline_row_id", _id_type(), nullable=False),
        sa.Column("parse_baseline_id", _id_type(), nullable=False),
        sa.Column(
            "report_type",
            _code_type(32),
            server_default=sa.text("'return_report'"),
            nullable=False,
        ),
        *_return_columns(),
        sa.PrimaryKeyConstraint(
            "parse_baseline_row_id",
            name="pk_return_parse_rows",
        ),
        sa.ForeignKeyConstraint(
            ["parse_baseline_id", "parse_baseline_row_id", "report_type"],
            [
                "parse_baseline_rows.parse_baseline_id",
                "parse_baseline_rows.id",
                "parse_baseline_rows.report_type",
            ],
            name="fk_return_parse_rows_parent",
            ondelete="RESTRICT",
        ),
        sa.CheckConstraint(
            "report_type = 'return_report'",
            name="ck_return_parse_rows_type",
        ),
        **_TABLE_OPTIONS,
    )

    op.create_table(
        "version_base_snapshots",
        sa.Column("id", _id_type(), autoincrement=True, nullable=False),
        sa.Column("version_id", _id_type(), nullable=False),
        sa.Column("report_type", _code_type(32), nullable=False),
        sa.Column("snapshot_kind", _code_type(32), nullable=False),
        sa.Column("data_digest", mysql.BINARY(32), nullable=False),
        sa.Column("row_count", _count_type(), nullable=False),
        sa.Column("totals_json", mysql.JSON(), nullable=False),
        sa.Column(
            "created_at",
            _timestamp_type(),
            server_default=sa.text("CURRENT_TIMESTAMP(6)"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id", name="pk_version_base_snapshots"),
        sa.ForeignKeyConstraint(
            ["version_id", "report_type"],
            ["dataset_versions.id", "dataset_versions.report_type"],
            name="fk_vbs_version_type",
            ondelete="RESTRICT",
        ),
        sa.UniqueConstraint("version_id", name="uq_vbs_version"),
        sa.UniqueConstraint(
            "version_id",
            "id",
            "report_type",
            name="uq_vbs_version_id_type",
        ),
        sa.CheckConstraint(
            "report_type IN ('business_report', 'return_report')",
            name="ck_vbs_type",
        ),
        sa.CheckConstraint(
            "snapshot_kind IN ('replacement', 'revision', 'merge', "
            "'date_reassignment', 'published_move')",
            name="ck_vbs_kind",
        ),
        **_TABLE_OPTIONS,
    )

    op.create_table(
        "version_base_snapshot_members",
        sa.Column("id", _id_type(), autoincrement=True, nullable=False),
        sa.Column("snapshot_id", _id_type(), nullable=False),
        sa.Column("member_ordinal", _count_type(), nullable=False),
        sa.Column("member_type", _code_type(32), nullable=False),
        sa.Column("member_role", _code_type(32), nullable=False),
        sa.Column("parse_baseline_id", _id_type(), nullable=True),
        sa.Column("parent_version_id", _id_type(), nullable=True),
        sa.Column("decision_json", mysql.JSON(), nullable=True),
        sa.Column(
            "created_at",
            _timestamp_type(),
            server_default=sa.text("CURRENT_TIMESTAMP(6)"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id", name="pk_vbs_members"),
        sa.ForeignKeyConstraint(
            ["snapshot_id"],
            ["version_base_snapshots.id"],
            name="fk_vbsm_snapshot",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["parse_baseline_id"],
            ["parse_baselines.id"],
            name="fk_vbsm_parse_baseline",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["parent_version_id"],
            ["dataset_versions.id"],
            name="fk_vbsm_parent_version",
            ondelete="RESTRICT",
        ),
        sa.UniqueConstraint(
            "snapshot_id",
            "member_ordinal",
            name="uq_vbsm_snapshot_ordinal",
        ),
        sa.UniqueConstraint(
            "snapshot_id",
            "id",
            name="uq_vbsm_snapshot_id",
        ),
        sa.CheckConstraint(
            "((member_type = 'parse_baseline' AND parse_baseline_id IS NOT NULL "
            "AND parent_version_id IS NULL) OR (member_type = 'dataset_version' "
            "AND parse_baseline_id IS NULL AND parent_version_id IS NOT NULL))",
            name="ck_vbsm_member",
        ),
        sa.CheckConstraint(
            "member_role IN ('base', 'parse_input', 'draft_predecessor', "
            "'merge_target', 'merge_source', 'moved_source')",
            name="ck_vbsm_role",
        ),
        **_TABLE_OPTIONS,
    )

    op.create_table(
        "version_base_rows",
        sa.Column("id", _id_type(), autoincrement=True, nullable=False),
        sa.Column("version_id", _id_type(), nullable=False),
        sa.Column("snapshot_id", _id_type(), nullable=False),
        sa.Column("report_type", _code_type(32), nullable=False),
        sa.Column("logical_row_id", mysql.BINARY(16), nullable=False),
        sa.Column("row_ordinal", _count_type(), nullable=False),
        sa.Column("source_member_id", _id_type(), nullable=False),
        sa.Column("source_parse_baseline_row_id", _id_type(), nullable=True),
        sa.Column("original_parsed_source_row_id", _id_type(), nullable=True),
        sa.Column("merge_action", _code_type(32), nullable=True),
        sa.Column("merge_reason", mysql.LONGTEXT(), nullable=True),
        sa.Column("provenance_json", mysql.JSON(), nullable=True),
        sa.Column(
            "created_at",
            _timestamp_type(),
            server_default=sa.text("CURRENT_TIMESTAMP(6)"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id", name="pk_version_base_rows"),
        sa.ForeignKeyConstraint(
            ["version_id", "snapshot_id", "report_type"],
            [
                "version_base_snapshots.version_id",
                "version_base_snapshots.id",
                "version_base_snapshots.report_type",
            ],
            name="fk_vbr_snapshot",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["snapshot_id", "source_member_id"],
            [
                "version_base_snapshot_members.snapshot_id",
                "version_base_snapshot_members.id",
            ],
            name="fk_vbr_member",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["source_parse_baseline_row_id"],
            ["parse_baseline_rows.id"],
            name="fk_vbr_source_parse_row",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["original_parsed_source_row_id"],
            ["parsed_source_rows.id"],
            name="fk_vbr_original_source",
            ondelete="RESTRICT",
        ),
        sa.UniqueConstraint(
            "snapshot_id",
            "row_ordinal",
            name="uq_vbr_snapshot_ordinal",
        ),
        sa.UniqueConstraint(
            "snapshot_id",
            "logical_row_id",
            name="uq_vbr_snapshot_logical",
        ),
        sa.UniqueConstraint(
            "version_id",
            "id",
            "report_type",
            name="uq_vbr_version_id_type",
        ),
        sa.CheckConstraint(
            "report_type IN ('business_report', 'return_report')",
            name="ck_vbr_type",
        ),
        sa.CheckConstraint(
            "merge_action IS NULL OR merge_action IN "
            "('keep_source', 'keep_target', 'keep_both')",
            name="ck_vbr_merge_action",
        ),
        **_TABLE_OPTIONS,
    )

    op.create_table(
        "business_version_base_rows",
        sa.Column("version_base_row_id", _id_type(), nullable=False),
        sa.Column("version_id", _id_type(), nullable=False),
        sa.Column(
            "report_type",
            _code_type(32),
            server_default=sa.text("'business_report'"),
            nullable=False,
        ),
        *_business_columns(),
        sa.PrimaryKeyConstraint(
            "version_base_row_id",
            name="pk_business_version_base_rows",
        ),
        sa.ForeignKeyConstraint(
            ["version_id", "version_base_row_id", "report_type"],
            [
                "version_base_rows.version_id",
                "version_base_rows.id",
                "version_base_rows.report_type",
            ],
            name="fk_business_base_rows_parent",
            ondelete="RESTRICT",
        ),
        sa.CheckConstraint(
            "report_type = 'business_report'",
            name="ck_business_base_rows_type",
        ),
        **_TABLE_OPTIONS,
    )

    op.create_table(
        "return_version_base_rows",
        sa.Column("version_base_row_id", _id_type(), nullable=False),
        sa.Column("version_id", _id_type(), nullable=False),
        sa.Column(
            "report_type",
            _code_type(32),
            server_default=sa.text("'return_report'"),
            nullable=False,
        ),
        *_return_columns(),
        sa.PrimaryKeyConstraint(
            "version_base_row_id",
            name="pk_return_version_base_rows",
        ),
        sa.ForeignKeyConstraint(
            ["version_id", "version_base_row_id", "report_type"],
            [
                "version_base_rows.version_id",
                "version_base_rows.id",
                "version_base_rows.report_type",
            ],
            name="fk_return_base_rows_parent",
            ondelete="RESTRICT",
        ),
        sa.CheckConstraint(
            "report_type = 'return_report'",
            name="ck_return_base_rows_type",
        ),
        **_TABLE_OPTIONS,
    )

    op.create_table(
        "version_rows",
        sa.Column("id", _id_type(), autoincrement=True, nullable=False),
        sa.Column("version_id", _id_type(), nullable=False),
        sa.Column("report_type", _code_type(32), nullable=False),
        sa.Column("logical_row_id", mysql.BINARY(16), nullable=False),
        sa.Column("row_ordinal", _count_type(), nullable=False),
        sa.Column(
            "row_state",
            _code_type(32),
            server_default=sa.text("'active'"),
            nullable=False,
        ),
        sa.Column("base_row_id", _id_type(), nullable=True),
        sa.Column("original_parsed_source_row_id", _id_type(), nullable=True),
        sa.Column(
            "created_at",
            _timestamp_type(),
            server_default=sa.text("CURRENT_TIMESTAMP(6)"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            _timestamp_type(),
            server_default=sa.text("CURRENT_TIMESTAMP(6)"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id", name="pk_version_rows"),
        sa.ForeignKeyConstraint(
            ["version_id", "report_type"],
            ["dataset_versions.id", "dataset_versions.report_type"],
            name="fk_version_rows_version_type",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["version_id", "base_row_id", "report_type"],
            [
                "version_base_rows.version_id",
                "version_base_rows.id",
                "version_base_rows.report_type",
            ],
            name="fk_version_rows_base_row",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["original_parsed_source_row_id"],
            ["parsed_source_rows.id"],
            name="fk_version_rows_original_source",
            ondelete="RESTRICT",
        ),
        sa.UniqueConstraint(
            "version_id",
            "logical_row_id",
            name="uq_version_rows_version_logical",
        ),
        sa.UniqueConstraint(
            "version_id",
            "row_ordinal",
            name="uq_version_rows_version_ordinal",
        ),
        sa.UniqueConstraint(
            "version_id",
            "id",
            name="uq_version_rows_version_id",
        ),
        sa.UniqueConstraint(
            "version_id",
            "id",
            "report_type",
            name="uq_version_rows_version_id_type",
        ),
        sa.CheckConstraint(
            "report_type IN ('business_report', 'return_report')",
            name="ck_version_rows_type",
        ),
        sa.CheckConstraint(
            "row_state IN ('active', 'excluded', 'deleted')",
            name="ck_version_rows_state",
        ),
        **_TABLE_OPTIONS,
    )

    op.create_table(
        "business_report_rows",
        sa.Column("version_row_id", _id_type(), nullable=False),
        sa.Column("version_id", _id_type(), nullable=False),
        sa.Column(
            "report_type",
            _code_type(32),
            server_default=sa.text("'business_report'"),
            nullable=False,
        ),
        *_business_columns(),
        sa.PrimaryKeyConstraint("version_row_id", name="pk_business_report_rows"),
        sa.ForeignKeyConstraint(
            ["version_id", "version_row_id", "report_type"],
            [
                "version_rows.version_id",
                "version_rows.id",
                "version_rows.report_type",
            ],
            name="fk_business_report_rows_parent",
            ondelete="RESTRICT",
        ),
        sa.CheckConstraint(
            "report_type = 'business_report'",
            name="ck_business_report_rows_type",
        ),
        **_TABLE_OPTIONS,
    )

    op.create_table(
        "return_report_rows",
        sa.Column("version_row_id", _id_type(), nullable=False),
        sa.Column("version_id", _id_type(), nullable=False),
        sa.Column(
            "report_type",
            _code_type(32),
            server_default=sa.text("'return_report'"),
            nullable=False,
        ),
        *_return_columns(),
        sa.PrimaryKeyConstraint("version_row_id", name="pk_return_report_rows"),
        sa.ForeignKeyConstraint(
            ["version_id", "version_row_id", "report_type"],
            [
                "version_rows.version_id",
                "version_rows.id",
                "version_rows.report_type",
            ],
            name="fk_return_report_rows_parent",
            ondelete="RESTRICT",
        ),
        sa.CheckConstraint(
            "report_type = 'return_report'",
            name="ck_return_report_rows_type",
        ),
        **_TABLE_OPTIONS,
    )

    op.create_index(
        "ix_dataset_versions_status",
        "dataset_versions",
        ["dataset_id", "status"],
    )
    op.create_index(
        "ix_vpv_parent",
        "version_parent_versions",
        ["parent_version_id"],
    )
    op.create_index("ix_vib_batch", "version_input_batches", ["batch_id"])
    op.create_index("ix_drafts_version", "dataset_drafts", ["version_id"])
    op.create_index(
        "ix_publications_version",
        "dataset_publications",
        ["version_id"],
    )
    op.create_index(
        "ix_pbr_source_row",
        "parse_baseline_rows",
        ["parsed_source_row_id"],
    )
    op.create_index(
        "ix_bpr_baseline_sku",
        "business_parse_baseline_rows",
        ["parse_baseline_id", "sku"],
    )
    op.create_index(
        "ix_bpr_baseline_asin",
        "business_parse_baseline_rows",
        ["parse_baseline_id", "child_asin"],
    )
    op.create_index(
        "ix_rpr_baseline_sku",
        "return_parse_baseline_rows",
        ["parse_baseline_id", "sku"],
    )
    op.create_index(
        "ix_rpr_baseline_asin",
        "return_parse_baseline_rows",
        ["parse_baseline_id", "asin"],
    )
    op.create_index(
        "ix_rpr_baseline_order",
        "return_parse_baseline_rows",
        ["parse_baseline_id", "order_id"],
    )
    op.create_index(
        "ix_rpr_baseline_return_date",
        "return_parse_baseline_rows",
        ["parse_baseline_id", "return_date"],
    )
    op.create_index(
        "ix_vbr_source_parse_row",
        "version_base_rows",
        ["source_parse_baseline_row_id"],
    )
    op.create_index(
        "ix_bvbr_version_sku",
        "business_version_base_rows",
        ["version_id", "sku"],
    )
    op.create_index(
        "ix_bvbr_version_asin",
        "business_version_base_rows",
        ["version_id", "child_asin"],
    )
    op.create_index(
        "ix_rvbr_version_sku",
        "return_version_base_rows",
        ["version_id", "sku"],
    )
    op.create_index(
        "ix_rvbr_version_asin",
        "return_version_base_rows",
        ["version_id", "asin"],
    )
    op.create_index(
        "ix_rvbr_version_order",
        "return_version_base_rows",
        ["version_id", "order_id"],
    )
    op.create_index(
        "ix_rvbr_version_return_date",
        "return_version_base_rows",
        ["version_id", "return_date"],
    )
    op.create_index(
        "ix_version_rows_source",
        "version_rows",
        ["original_parsed_source_row_id"],
    )
    op.create_index(
        "ix_br_rows_version_sku",
        "business_report_rows",
        ["version_id", "sku"],
    )
    op.create_index(
        "ix_br_rows_version_asin",
        "business_report_rows",
        ["version_id", "child_asin"],
    )
    op.create_index(
        "ix_rr_rows_version_sku",
        "return_report_rows",
        ["version_id", "sku"],
    )
    op.create_index(
        "ix_rr_rows_version_asin",
        "return_report_rows",
        ["version_id", "asin"],
    )
    op.create_index(
        "ix_rr_rows_version_order",
        "return_report_rows",
        ["version_id", "order_id"],
    )
    op.create_index(
        "ix_rr_rows_version_return_date",
        "return_report_rows",
        ["version_id", "return_date"],
    )


def downgrade() -> None:
    # MySQL may use an explicitly named index to support a foreign key. Dropping
    # the tables in dependency order removes their indexes and constraints
    # together, without first invalidating a live foreign key.
    op.drop_table("return_report_rows")
    op.drop_table("business_report_rows")
    op.drop_table("version_rows")
    op.drop_table("return_version_base_rows")
    op.drop_table("business_version_base_rows")
    op.drop_table("version_base_rows")
    op.drop_table("version_base_snapshot_members")
    op.drop_table("version_base_snapshots")
    op.drop_table("return_parse_baseline_rows")
    op.drop_table("business_parse_baseline_rows")
    op.drop_table("parse_baseline_rows")
    op.drop_table("parse_baselines")
    op.drop_table("dataset_publications")
    op.drop_table("dataset_drafts")
    op.drop_table("version_input_batches")
    op.drop_table("version_parent_versions")
    op.drop_table("dataset_versions")
    op.drop_table("daily_datasets")
