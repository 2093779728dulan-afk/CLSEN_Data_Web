"""Allow production evidence to use the existing catalog approval workflow."""

from alembic import op
from sqlalchemy.dialects import mysql

revision = "0032"
down_revision = "0031"
branch_labels = None
depends_on = None


def upgrade():
    # Production identity evidence has no sales/return fact tuple. Report imports
    # retain their required binding through the source-specific constraints.
    for table in (
        "catalog_exports",
        "catalog_imports",
        "catalog_approval_projections",
        "product_catalog_versions",
    ):
        op.alter_column(
            table,
            "fact_snapshot_tuple_id",
            existing_type=mysql.BIGINT(unsigned=True),
            nullable=True,
        )
    for name in (
        "ck_catalog_imports_source_kind",
        "ck_catalog_imports_source_metadata",
    ):
        op.drop_constraint(name, "catalog_imports", type_="check")
    op.create_check_constraint(
        "ck_catalog_imports_source_kind",
        "catalog_imports",
        "source_kind IN ('xlsx','online','production')",
    )
    op.create_check_constraint(
        "ck_catalog_imports_source_metadata",
        "catalog_imports",
        (
            "(source_kind='xlsx' AND raw_file_id IS NOT NULL AND original_filenam"
            "e IS NOT NULL AND declared_media_type IS NOT NULL AND fact_snapshot_"
            "tuple_id IS NOT NULL) OR (source_kind='online' AND raw_file_id IS NU"
            "LL AND original_filename IS NULL AND declared_media_type IS NULL AND"
            " fact_snapshot_tuple_id IS NOT NULL) OR (source_kind='production' AN"
            "D raw_file_id IS NULL AND original_filename IS NULL AND declared_med"
            "ia_type IS NULL AND fact_snapshot_tuple_id IS NULL)"
        ),
    )
    op.drop_constraint(
        "ck_catalog_exports_workbook_status", "catalog_exports", type_="check"
    )
    op.create_check_constraint(
        "ck_catalog_exports_workbook_status",
        "catalog_exports",
        (
            "workbook_status IS NULL OR workbook_status IN ('ready','capacity_exc"
            "eeded','online_only')"
        ),
    )
    op.drop_constraint(
        "ck_catalog_exports_finalization", "catalog_exports", type_="check"
    )
    op.create_check_constraint(
        "ck_catalog_exports_finalization",
        "catalog_exports",
        (
            "(fact_snapshot_tuple_id IS NOT NULL AND ((export_status='building' A"
            "ND workbook_status IS NULL AND capacity_violations IS NULL AND artif"
            "act_sha256 IS NULL AND artifact_storage_key IS NULL AND failure_reas"
            "on_code IS NULL) OR (export_status='failed' AND workbook_status IS N"
            "ULL AND capacity_violations IS NULL AND artifact_sha256 IS NULL AND "
            "artifact_storage_key IS NULL AND failure_reason_code IS NOT NULL) OR"
            " (export_status='ready' AND workbook_status='ready' AND JSON_LENGTH("
            "capacity_violations)=0 AND artifact_sha256 IS NOT NULL AND artifact_"
            "storage_key IS NOT NULL AND failure_reason_code IS NULL) OR (export_"
            "status='ready' AND workbook_status='capacity_exceeded' AND JSON_LENG"
            "TH(capacity_violations)>0 AND artifact_sha256 IS NULL AND artifact_s"
            "torage_key IS NULL AND failure_reason_code IS NULL))) OR (fact_snaps"
            "hot_tuple_id IS NULL AND export_status='ready' AND workbook_status='"
            "online_only' AND JSON_LENGTH(capacity_violations)=0 AND artifact_sha"
            "256 IS NULL AND artifact_storage_key IS NULL AND failure_reason_code"
            " IS NULL)"
        ),
    )


def downgrade():
    raise RuntimeError(
        "Production catalog history must be retained; restore a verified back"
        "up instead."
    )
