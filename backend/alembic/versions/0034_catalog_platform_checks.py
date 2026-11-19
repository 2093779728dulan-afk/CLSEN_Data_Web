"""Immutable listing comparison snapshots and original-file metadata."""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import mysql

revision = "0034"
down_revision = "0033"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "catalog_platform_checks",
        sa.Column(
            "id", mysql.BIGINT(unsigned=True), primary_key=True, autoincrement=True
        ),
        sa.Column("site_id", mysql.BIGINT(unsigned=True), nullable=False),
        sa.Column("import_id", mysql.BIGINT(unsigned=True), nullable=False),
        sa.Column("workflow_revision", mysql.BIGINT(unsigned=True), nullable=False),
        sa.Column(
            "catalog_publication_revision", mysql.BIGINT(unsigned=True), nullable=False
        ),
        sa.Column("source_digest", mysql.BINARY(32), nullable=False),
        sa.Column("evidence_digest", mysql.BINARY(32), nullable=False),
        sa.Column("algorithm_version", sa.String(32), nullable=False),
        sa.Column("result_json", mysql.JSON(), nullable=False),
        sa.Column("created_by_user_id", mysql.BIGINT(unsigned=True), nullable=False),
        sa.Column("created_at", mysql.DATETIME(fsp=6), nullable=False),
        sa.ForeignKeyConstraint(
            ["import_id"], ["catalog_imports.id"], name="fk_platform_checks_import"
        ),
        sa.ForeignKeyConstraint(
            ["site_id"], ["sites.id"], name="fk_platform_checks_site"
        ),
        sa.Index("ix_platform_checks_import", "site_id", "import_id", "id"),
        mysql_engine="InnoDB",
    )
    for action in ("UPDATE", "DELETE"):
        op.execute(
            f"CREATE TRIGGER catalog_platform_checks_no_{action.lower()} "
            f"BEFORE {action} ON catalog_platform_checks FOR EACH ROW "
            "SIGNAL SQLSTATE '45000' "
            "SET MESSAGE_TEXT='platform check history is immutable'"
        )
    op.drop_constraint(
        "ck_catalog_imports_source_metadata", "catalog_imports", type_="check"
    )
    op.create_check_constraint(
        "ck_catalog_imports_source_metadata",
        "catalog_imports",
        "(source_kind='xlsx' AND raw_file_id IS NOT NULL "
        "AND original_filename IS NOT NULL AND declared_media_type IS NOT NULL "
        "AND fact_snapshot_tuple_id IS NOT NULL) "
        "OR (source_kind='online' AND raw_file_id IS NULL "
        "AND original_filename IS NULL AND declared_media_type IS NULL "
        "AND fact_snapshot_tuple_id IS NOT NULL) "
        "OR (source_kind='production' AND fact_snapshot_tuple_id IS NULL "
        "AND ((raw_file_id IS NULL AND original_filename IS NULL "
        "AND declared_media_type IS NULL) OR (raw_file_id IS NOT NULL "
        "AND original_filename IS NOT NULL AND declared_media_type IS NOT NULL)))",
    )


def downgrade():
    raise RuntimeError("Listing evidence and approved history must be retained.")
