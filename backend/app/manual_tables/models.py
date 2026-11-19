"""Manual preparation metadata, separate from official imports and business facts."""

import sqlalchemy as sa
from sqlalchemy.dialects import mysql

metadata = sa.MetaData()
sa.Table(
    "sites", metadata, sa.Column("id", mysql.BIGINT(unsigned=True), primary_key=True)
)
sa.Table(
    "users", metadata, sa.Column("id", mysql.BIGINT(unsigned=True), primary_key=True)
)

batches = sa.Table(
    "manual_table_batches",
    metadata,
    sa.Column("id", sa.String(36, collation="ascii_bin"), primary_key=True),
    sa.Column(
        "site_id",
        mysql.BIGINT(unsigned=True),
        sa.ForeignKey("sites.id"),
        nullable=False,
    ),
    sa.Column(
        "owner_id",
        mysql.BIGINT(unsigned=True),
        sa.ForeignKey("users.id"),
        nullable=False,
    ),
    sa.Column("kind", sa.String(16), nullable=False),
    sa.Column("filename", sa.String(240), nullable=False),
    sa.Column("source_digest", sa.String(64, collation="ascii_bin"), nullable=False),
    sa.Column("storage_key", sa.String(96), nullable=False),
    sa.Column("size_bytes", sa.Integer(), nullable=False),
    sa.Column("revision", sa.Integer(), nullable=False),
    sa.Column("options_json", sa.JSON(), nullable=False),
    sa.Column("result_json", sa.JSON(), nullable=False),
    sa.Column("target_json", sa.JSON(), nullable=True),
    sa.Column("created_at", mysql.DATETIME(fsp=6), nullable=False),
    sa.Column("updated_at", mysql.DATETIME(fsp=6), nullable=False),
    sa.UniqueConstraint(
        "site_id", "owner_id", "kind", "source_digest", name="uq_manual_source"
    ),
    mysql_engine="InnoDB",
    mysql_charset="utf8mb4",
)
operations = sa.Table(
    "manual_table_operations",
    metadata,
    sa.Column(
        "site_id",
        mysql.BIGINT(unsigned=True),
        sa.ForeignKey("sites.id"),
        primary_key=True,
    ),
    sa.Column("token", sa.String(36, collation="ascii_bin"), primary_key=True),
    sa.Column(
        "batch_id",
        sa.String(36, collation="ascii_bin"),
        sa.ForeignKey("manual_table_batches.id"),
        nullable=True,
    ),
    sa.Column(
        "actor_id",
        mysql.BIGINT(unsigned=True),
        sa.ForeignKey("users.id"),
        nullable=False,
    ),
    sa.Column("action", sa.String(32), nullable=False),
    sa.Column("request_hash", sa.String(64, collation="ascii_bin"), nullable=False),
    sa.Column("revision", sa.Integer(), nullable=True),
    sa.Column("result_json", sa.JSON(), nullable=True),
    sa.Column("reason", sa.String(1000), nullable=False),
    sa.Column("at", mysql.DATETIME(fsp=6), nullable=False),
    mysql_engine="InnoDB",
    mysql_charset="utf8mb4",
)
profiles = sa.Table(
    "manual_table_profiles",
    metadata,
    sa.Column("id", sa.String(36, collation="ascii_bin"), primary_key=True),
    sa.Column("version", sa.Integer(), primary_key=True),
    sa.Column(
        "site_id",
        mysql.BIGINT(unsigned=True),
        sa.ForeignKey("sites.id"),
        nullable=False,
    ),
    sa.Column(
        "owner_id",
        mysql.BIGINT(unsigned=True),
        sa.ForeignKey("users.id"),
        nullable=False,
    ),
    sa.Column("name", sa.String(120), nullable=False),
    sa.Column("kind", sa.String(16), nullable=False),
    sa.Column("shared", sa.Boolean(), nullable=False),
    sa.Column("signature", sa.String(64), nullable=False),
    sa.Column("options_json", sa.JSON(), nullable=False),
    sa.Column("at", mysql.DATETIME(fsp=6), nullable=False),
    mysql_engine="InnoDB",
    mysql_charset="utf8mb4",
)
