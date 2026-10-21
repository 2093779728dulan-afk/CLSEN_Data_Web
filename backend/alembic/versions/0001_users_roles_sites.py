"""Create users, roles, sites, and versioned site configuration."""

from datetime import datetime

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import mysql

revision = "0001"
down_revision = None
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
        "users",
        sa.Column("id", _bigint(), autoincrement=True, nullable=False),
        sa.Column("username_normalized", sa.String(length=191), nullable=False),
        sa.Column("display_name", sa.String(length=255), nullable=False),
        sa.Column("email", sa.String(length=255), nullable=True),
        sa.Column("password_hash", sa.String(length=255), nullable=False),
        sa.Column(
            "status",
            sa.String(length=32),
            server_default=sa.text("'active'"),
            nullable=False,
        ),
        sa.Column("last_login_at", _utc_datetime(), nullable=True),
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
        sa.PrimaryKeyConstraint("id", name="pk_users"),
        sa.UniqueConstraint(
            "username_normalized",
            name="uq_users_username_normalized",
        ),
        sa.UniqueConstraint("email", name="uq_users_email"),
        sa.CheckConstraint(
            "status IN ('active', 'disabled', 'locked')",
            name="ck_users_status",
        ),
        **_TABLE_OPTIONS,
    )

    op.create_table(
        "roles",
        sa.Column("id", _bigint(), autoincrement=True, nullable=False),
        sa.Column("code", sa.String(length=32), nullable=False),
        sa.Column("description", sa.String(length=255), nullable=False),
        sa.Column(
            "created_at",
            _utc_datetime(),
            server_default=sa.text("CURRENT_TIMESTAMP(6)"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id", name="pk_roles"),
        sa.UniqueConstraint("code", name="uq_roles_code"),
        **_TABLE_OPTIONS,
    )

    op.create_table(
        "user_roles",
        sa.Column("user_id", _bigint(), nullable=False),
        sa.Column("role_id", _bigint(), nullable=False),
        sa.Column("assigned_by", _bigint(), nullable=True),
        sa.Column(
            "assigned_at",
            _utc_datetime(),
            server_default=sa.text("CURRENT_TIMESTAMP(6)"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["users.id"],
            name="fk_user_roles_user",
            ondelete="RESTRICT",
            onupdate="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["role_id"],
            ["roles.id"],
            name="fk_user_roles_role",
            ondelete="RESTRICT",
            onupdate="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["assigned_by"],
            ["users.id"],
            name="fk_user_roles_assigned_by",
            ondelete="RESTRICT",
            onupdate="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("user_id", "role_id", name="pk_user_roles"),
        **_TABLE_OPTIONS,
    )

    op.create_table(
        "sites",
        sa.Column("id", _bigint(), autoincrement=True, nullable=False),
        sa.Column("code", sa.String(length=64), nullable=False),
        sa.Column("display_name", sa.String(length=255), nullable=False),
        sa.Column(
            "status",
            sa.String(length=32),
            server_default=sa.text("'active'"),
            nullable=False,
        ),
        sa.Column(
            "created_at",
            _utc_datetime(),
            server_default=sa.text("CURRENT_TIMESTAMP(6)"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id", name="pk_sites"),
        sa.UniqueConstraint("code", name="uq_sites_code"),
        sa.CheckConstraint(
            "status IN ('active', 'inactive')",
            name="ck_sites_status",
        ),
        **_TABLE_OPTIONS,
    )

    op.create_table(
        "site_config_versions",
        sa.Column("id", _bigint(), autoincrement=True, nullable=False),
        sa.Column("site_id", _bigint(), nullable=False),
        sa.Column("version_number", _bigint(), nullable=False),
        sa.Column("source_timezone", sa.String(length=64), nullable=False),
        sa.Column("reporting_timezone", sa.String(length=64), nullable=False),
        sa.Column("currency_code", sa.String(length=3), nullable=False),
        sa.Column("effective_at", _utc_datetime(), nullable=False),
        sa.Column("change_reason", sa.Text(), nullable=True),
        sa.Column("created_by_user_id", _bigint(), nullable=True),
        sa.Column(
            "created_at",
            _utc_datetime(),
            server_default=sa.text("CURRENT_TIMESTAMP(6)"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "version_number > 0",
            name="ck_site_config_versions_version_positive",
        ),
        sa.CheckConstraint(
            "CHAR_LENGTH(currency_code) = 3",
            name="ck_site_config_versions_currency_length",
        ),
        sa.ForeignKeyConstraint(
            ["site_id"],
            ["sites.id"],
            name="fk_site_config_versions_site",
            ondelete="RESTRICT",
            onupdate="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["created_by_user_id"],
            ["users.id"],
            name="fk_site_config_versions_created_by",
            ondelete="RESTRICT",
            onupdate="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_site_config_versions"),
        sa.UniqueConstraint(
            "site_id",
            "version_number",
            name="uq_site_config_versions_site_version",
        ),
        sa.UniqueConstraint(
            "site_id",
            "id",
            name="uq_site_config_versions_site_id",
        ),
        **_TABLE_OPTIONS,
    )

    op.create_table(
        "site_current_configs",
        sa.Column("site_id", _bigint(), nullable=False),
        sa.Column("current_config_version_id", _bigint(), nullable=False),
        sa.Column("updated_by_user_id", _bigint(), nullable=True),
        sa.Column(
            "updated_at",
            _utc_datetime(),
            server_default=sa.text("CURRENT_TIMESTAMP(6)"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["site_id"],
            ["sites.id"],
            name="fk_site_current_configs_site",
            ondelete="RESTRICT",
            onupdate="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["site_id", "current_config_version_id"],
            ["site_config_versions.site_id", "site_config_versions.id"],
            name="fk_site_current_configs_config",
            ondelete="RESTRICT",
            onupdate="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["updated_by_user_id"],
            ["users.id"],
            name="fk_site_current_configs_updated_by",
            ondelete="RESTRICT",
            onupdate="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("site_id", name="pk_site_current_configs"),
        **_TABLE_OPTIONS,
    )

    roles = sa.table(
        "roles",
        sa.column("id", _bigint()),
        sa.column("code", sa.String(length=32)),
        sa.column("description", sa.String(length=255)),
    )
    op.bulk_insert(
        roles,
        [
            {
                "id": 1,
                "code": "admin",
                "description": "Full system administration",
            },
            {
                "id": 2,
                "code": "data_manager",
                "description": "Data import, review, correction, and publication",
            },
            {
                "id": 3,
                "code": "viewer",
                "description": "Published and redacted data access",
            },
        ],
    )

    sites = sa.table(
        "sites",
        sa.column("id", _bigint()),
        sa.column("code", sa.String(length=64)),
        sa.column("display_name", sa.String(length=255)),
        sa.column("status", sa.String(length=32)),
    )
    op.bulk_insert(
        sites,
        [
            {
                "id": 1,
                "code": "amazon_us",
                "display_name": "Amazon US",
                "status": "active",
            }
        ],
    )

    site_config_versions = sa.table(
        "site_config_versions",
        sa.column("id", _bigint()),
        sa.column("site_id", _bigint()),
        sa.column("version_number", _bigint()),
        sa.column("source_timezone", sa.String(length=64)),
        sa.column("reporting_timezone", sa.String(length=64)),
        sa.column("currency_code", sa.String(length=3)),
        sa.column("effective_at", _utc_datetime()),
        sa.column("change_reason", sa.Text()),
        sa.column("created_by_user_id", _bigint()),
    )
    op.bulk_insert(
        site_config_versions,
        [
            {
                "id": 1,
                "site_id": 1,
                "version_number": 1,
                "source_timezone": "America/Los_Angeles",
                "reporting_timezone": "America/Los_Angeles",
                "currency_code": "USD",
                "effective_at": datetime(1970, 1, 1),
                "change_reason": "Initial Amazon US configuration",
                "created_by_user_id": None,
            }
        ],
    )

    site_current_configs = sa.table(
        "site_current_configs",
        sa.column("site_id", _bigint()),
        sa.column("current_config_version_id", _bigint()),
        sa.column("updated_by_user_id", _bigint()),
    )
    op.bulk_insert(
        site_current_configs,
        [
            {
                "site_id": 1,
                "current_config_version_id": 1,
                "updated_by_user_id": None,
            }
        ],
    )


def downgrade() -> None:
    op.drop_table("site_current_configs")
    op.drop_table("site_config_versions")
    op.drop_table("sites")
    op.drop_table("user_roles")
    op.drop_table("roles")
    op.drop_table("users")
