# ruff: noqa: E501
"""Add governed categories and isolated single-style catalog changes."""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import mysql

revision = "0025"
down_revision = "0024"
branch_labels = None
depends_on = None


def _id() -> mysql.BIGINT:
    return mysql.BIGINT(unsigned=True)


def _code(length: int) -> mysql.VARCHAR:
    return mysql.VARCHAR(length, charset="ascii", collation="ascii_bin")


def _text(length: int) -> mysql.VARCHAR:
    return mysql.VARCHAR(length, charset="utf8mb4", collation="utf8mb4_bin")


def upgrade() -> None:
    op.drop_constraint(
        "ck_product_catalog_versions_workbook",
        "product_catalog_versions",
        type_="check",
    )
    op.create_check_constraint(
        "ck_product_catalog_versions_workbook",
        "product_catalog_versions",
        "workbook_schema_version IN ('product_catalog_workbook_v1','product_catalog_workbook_v2')",
    )
    op.drop_constraint(
        "ck_catalog_exports_workbook_version", "catalog_exports", type_="check"
    )
    op.create_check_constraint(
        "ck_catalog_exports_workbook_version",
        "catalog_exports",
        "workbook_schema_version IN ('product_catalog_workbook_v1','product_catalog_workbook_v2')",
    )
    op.create_table(
        "product_categories",
        sa.Column("id", _id(), autoincrement=True, nullable=False),
        sa.Column("site_id", _id(), nullable=False),
        sa.Column("code", _code(64), nullable=False),
        sa.Column("display_name", _text(128), nullable=False),
        sa.Column("status", _code(16), nullable=False, server_default="enabled"),
        sa.Column("created_by_user_id", _id(), nullable=True),
        sa.Column("updated_by_user_id", _id(), nullable=True),
        sa.Column(
            "created_at",
            mysql.DATETIME(fsp=6),
            nullable=False,
            server_default=sa.text("UTC_TIMESTAMP(6)"),
        ),
        sa.Column(
            "updated_at",
            mysql.DATETIME(fsp=6),
            nullable=False,
            server_default=sa.text("UTC_TIMESTAMP(6)"),
            server_onupdate=sa.text("UTC_TIMESTAMP(6)"),
        ),
        sa.PrimaryKeyConstraint("id", name="pk_product_categories"),
        sa.UniqueConstraint("id", "site_id", name="uq_product_categories_id_site"),
        sa.UniqueConstraint("site_id", "code", name="uq_product_categories_code"),
        sa.ForeignKeyConstraint(
            ["site_id"],
            ["sites.id"],
            name="fk_product_categories_site",
            ondelete="RESTRICT",
            onupdate="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["created_by_user_id"],
            ["users.id"],
            name="fk_product_categories_creator",
            ondelete="RESTRICT",
            onupdate="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["updated_by_user_id"],
            ["users.id"],
            name="fk_product_categories_updater",
            ondelete="RESTRICT",
            onupdate="RESTRICT",
        ),
        sa.CheckConstraint(
            "status IN ('enabled','disabled')", name="ck_product_categories_status"
        ),
        sa.Index("ix_product_categories_site_status", "site_id", "status", "id"),
        mysql_engine="InnoDB",
        mysql_charset="utf8mb4",
        mysql_collate="utf8mb4_bin",
    )
    op.create_table(
        "product_category_aliases",
        sa.Column("id", _id(), autoincrement=True, nullable=False),
        sa.Column("site_id", _id(), nullable=False),
        sa.Column("category_id", _id(), nullable=False),
        sa.Column("alias", _text(128), nullable=False),
        sa.Column("alias_key", _text(128), nullable=False),
        sa.Column("created_by_user_id", _id(), nullable=False),
        sa.Column(
            "created_at",
            mysql.DATETIME(fsp=6),
            nullable=False,
            server_default=sa.text("UTC_TIMESTAMP(6)"),
        ),
        sa.PrimaryKeyConstraint("id", name="pk_product_category_aliases"),
        sa.UniqueConstraint(
            "site_id", "alias_key", name="uq_product_category_aliases_key"
        ),
        sa.ForeignKeyConstraint(
            ["category_id", "site_id"],
            ["product_categories.id", "product_categories.site_id"],
            name="fk_product_category_aliases_category",
            ondelete="RESTRICT",
            onupdate="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["created_by_user_id"],
            ["users.id"],
            name="fk_product_category_aliases_creator",
            ondelete="RESTRICT",
            onupdate="RESTRICT",
        ),
        mysql_engine="InnoDB",
        mysql_charset="utf8mb4",
        mysql_collate="utf8mb4_bin",
    )
    op.add_column(
        "product_catalog_style_members", sa.Column("category_id", _id(), nullable=True)
    )
    op.add_column(
        "product_catalog_style_members",
        sa.Column("category_code_snapshot", _code(64), nullable=True),
    )
    op.add_column(
        "product_catalog_style_members",
        sa.Column("category_name_snapshot", _text(128), nullable=True),
    )
    op.add_column(
        "product_catalog_style_members",
        sa.Column(
            "category_snapshot_recorded",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("FALSE"),
        ),
    )
    op.create_index(
        "ix_product_catalog_style_members_category",
        "product_catalog_style_members",
        ["category_id", "site_id"],
    )
    op.create_foreign_key(
        "fk_product_catalog_style_members_category",
        "product_catalog_style_members",
        "product_categories",
        ["category_id", "site_id"],
        ["id", "site_id"],
        ondelete="RESTRICT",
        onupdate="RESTRICT",
    )
    op.create_check_constraint(
        "ck_product_catalog_style_members_category_snapshot",
        "product_catalog_style_members",
        "(category_id IS NULL AND category_code_snapshot IS NULL AND category_name_snapshot IS NULL) OR (category_id IS NOT NULL AND category_code_snapshot IS NOT NULL AND category_name_snapshot IS NOT NULL)",
    )
    op.create_table(
        "catalog_style_change_drafts",
        sa.Column("id", _id(), autoincrement=True, nullable=False),
        sa.Column("site_id", _id(), nullable=False),
        sa.Column("style_id", _id(), nullable=False),
        sa.Column("base_catalog_version_id", _id(), nullable=False),
        sa.Column("base_style_revision", _id(), nullable=False),
        sa.Column("base_catalog_publication_revision", _id(), nullable=False),
        sa.Column("draft_revision", _id(), nullable=False, server_default=sa.text("1")),
        sa.Column("proposed_standard_name", _text(255), nullable=False),
        sa.Column("category_action", _code(8), nullable=False),
        sa.Column("proposed_category_id", _id(), nullable=True),
        sa.Column("status", _code(16), nullable=False, server_default="draft"),
        sa.Column("created_by_user_id", _id(), nullable=False),
        sa.Column("approved_catalog_version_id", _id(), nullable=True),
        sa.Column(
            "created_at",
            mysql.DATETIME(fsp=6),
            nullable=False,
            server_default=sa.text("UTC_TIMESTAMP(6)"),
        ),
        sa.Column(
            "updated_at",
            mysql.DATETIME(fsp=6),
            nullable=False,
            server_default=sa.text("UTC_TIMESTAMP(6)"),
            server_onupdate=sa.text("UTC_TIMESTAMP(6)"),
        ),
        sa.PrimaryKeyConstraint("id", name="pk_catalog_style_change_drafts"),
        sa.UniqueConstraint(
            "id", "site_id", name="uq_catalog_style_change_drafts_id_site"
        ),
        sa.ForeignKeyConstraint(
            ["style_id", "site_id"],
            ["product_styles.id", "product_styles.site_id"],
            name="fk_catalog_style_change_drafts_style",
            ondelete="RESTRICT",
            onupdate="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["base_catalog_version_id", "site_id"],
            ["product_catalog_versions.id", "product_catalog_versions.site_id"],
            name="fk_catalog_style_change_drafts_base",
            ondelete="RESTRICT",
            onupdate="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["proposed_category_id", "site_id"],
            ["product_categories.id", "product_categories.site_id"],
            name="fk_catalog_style_change_drafts_category",
            ondelete="RESTRICT",
            onupdate="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["created_by_user_id"],
            ["users.id"],
            name="fk_catalog_style_change_drafts_creator",
            ondelete="RESTRICT",
            onupdate="RESTRICT",
        ),
        sa.CheckConstraint(
            "category_action IN ('keep','clear','set')",
            name="ck_catalog_style_change_drafts_action",
        ),
        sa.CheckConstraint(
            "status IN ('draft','approved')",
            name="ck_catalog_style_change_drafts_status",
        ),
        sa.CheckConstraint(
            "(category_action='set' AND proposed_category_id IS NOT NULL) OR (category_action IN ('keep','clear') AND proposed_category_id IS NULL)",
            name="ck_catalog_style_change_drafts_category",
        ),
        sa.Index(
            "ix_catalog_style_change_drafts_style",
            "site_id",
            "style_id",
            "status",
            "id",
        ),
        mysql_engine="InnoDB",
        mysql_charset="utf8mb4",
        mysql_collate="utf8mb4_bin",
    )
    op.drop_constraint(
        "ck_product_catalog_publication_events_kind",
        "product_catalog_publication_events",
        type_="check",
    )
    op.create_check_constraint(
        "ck_product_catalog_publication_events_kind",
        "product_catalog_publication_events",
        "event_kind IN ('approve','restore','style_change')",
    )
    op.execute(
        sa.text(
            "INSERT INTO product_categories (site_id, code, display_name, status) SELECT id, 'SHIRT', '衬衫', 'enabled' FROM sites"
        )
    )
    op.execute(
        sa.text(
            "INSERT INTO product_categories (site_id, code, display_name, status) SELECT id, 'BLAZER', '西装外套', 'enabled' FROM sites"
        )
    )


def downgrade() -> None:
    op.drop_constraint(
        "ck_product_catalog_publication_events_kind",
        "product_catalog_publication_events",
        type_="check",
    )
    op.create_check_constraint(
        "ck_product_catalog_publication_events_kind",
        "product_catalog_publication_events",
        "event_kind IN (_ascii'approve',_ascii'restore')",
    )
    op.drop_table("catalog_style_change_drafts")
    op.drop_constraint(
        "ck_product_catalog_style_members_category_snapshot",
        "product_catalog_style_members",
        type_="check",
    )
    op.drop_constraint(
        "fk_product_catalog_style_members_category",
        "product_catalog_style_members",
        type_="foreignkey",
    )
    op.drop_index(
        "ix_product_catalog_style_members_category",
        table_name="product_catalog_style_members",
    )
    op.drop_column("product_catalog_style_members", "category_name_snapshot")
    op.drop_column("product_catalog_style_members", "category_code_snapshot")
    op.drop_column("product_catalog_style_members", "category_id")
    op.drop_column("product_catalog_style_members", "category_snapshot_recorded")
    op.drop_table("product_category_aliases")
    op.drop_table("product_categories")
    op.drop_constraint(
        "ck_catalog_exports_workbook_version", "catalog_exports", type_="check"
    )
    op.create_check_constraint(
        "ck_catalog_exports_workbook_version",
        "catalog_exports",
        "workbook_schema_version=_ascii'product_catalog_workbook_v1'",
    )
    op.drop_constraint(
        "ck_product_catalog_versions_workbook",
        "product_catalog_versions",
        type_="check",
    )
    op.create_check_constraint(
        "ck_product_catalog_versions_workbook",
        "product_catalog_versions",
        "workbook_schema_version=_ascii'product_catalog_workbook_v1'",
    )
