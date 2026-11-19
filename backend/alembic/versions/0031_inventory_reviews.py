# ruff: noqa: E501
"""Persist inventory source reconciliation without posting inventory."""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import mysql

metadata = sa.MetaData()
# Reference-only metadata; these existing tables are not created by this module.
sa.Table(
    "sites", metadata, sa.Column("id", mysql.BIGINT(unsigned=True), primary_key=True)
)
sa.Table(
    "users", metadata, sa.Column("id", mysql.BIGINT(unsigned=True), primary_key=True)
)
reviews = sa.Table(
    "production_inventory_reviews",
    metadata,
    sa.Column("review_id", mysql.BINARY(16), primary_key=True),
    sa.Column("site_id", mysql.BIGINT(unsigned=True), nullable=False),
    sa.Column("source_identity", sa.String(64, collation="ascii_bin"), nullable=False),
    sa.Column("source_digest", sa.String(64, collation="ascii_bin"), nullable=False),
    sa.Column(
        "source_manifest_digest", sa.String(64, collation="ascii_bin"), nullable=False
    ),
    sa.Column("source_format", sa.String(32), nullable=False),
    sa.Column("source_name", sa.String(240), nullable=False),
    sa.Column("parser_version", sa.String(40), nullable=False),
    sa.Column("policy_version", sa.String(40), nullable=False),
    sa.Column("source_snapshot_json", sa.JSON(), nullable=False),
    sa.Column("revision", sa.Integer(), nullable=False),
    sa.Column(
        "created_by",
        mysql.BIGINT(unsigned=True),
        sa.ForeignKey("users.id"),
        nullable=False,
    ),
    sa.Column(
        "updated_by",
        mysql.BIGINT(unsigned=True),
        sa.ForeignKey("users.id"),
        nullable=False,
    ),
    sa.Column("created_at", mysql.DATETIME(fsp=6), nullable=False),
    sa.Column("updated_at", mysql.DATETIME(fsp=6), nullable=False),
    sa.ForeignKeyConstraint(["site_id"], ["sites.id"], ondelete="RESTRICT"),
    sa.UniqueConstraint(
        "site_id", "source_identity", name="uq_inventory_review_source"
    ),
    sa.UniqueConstraint("site_id", "review_id", name="uq_inventory_review_site"),
    mysql_engine="InnoDB",
    mysql_charset="utf8mb4",
)
revisions = sa.Table(
    "production_inventory_review_revisions",
    metadata,
    sa.Column("site_id", mysql.BIGINT(unsigned=True), primary_key=True),
    sa.Column("review_id", mysql.BINARY(16), primary_key=True),
    sa.Column("revision", sa.Integer(), primary_key=True),
    sa.Column("operation_id", mysql.BINARY(16), nullable=False),
    sa.Column("request_hash", sa.String(64, collation="ascii_bin"), nullable=False),
    sa.Column("command_json", sa.JSON(), nullable=False),
    sa.Column("effective_overrides_json", sa.JSON(), nullable=False),
    sa.Column("result_json", sa.JSON(), nullable=False),
    sa.Column(
        "actor_id",
        mysql.BIGINT(unsigned=True),
        sa.ForeignKey("users.id"),
        nullable=False,
    ),
    sa.Column("at", mysql.DATETIME(fsp=6), nullable=False),
    sa.Column("reason", sa.String(1000), nullable=False),
    sa.UniqueConstraint(
        "site_id", "operation_id", name="uq_inventory_review_operation"
    ),
    sa.ForeignKeyConstraint(
        ["site_id", "review_id"],
        [
            "production_inventory_reviews.site_id",
            "production_inventory_reviews.review_id",
        ],
        ondelete="RESTRICT",
    ),
    mysql_engine="InnoDB",
    mysql_charset="utf8mb4",
)

revision = "0031"
down_revision = "0030"
branch_labels = None
depends_on = None


def upgrade():
    reviews.create(op.get_bind())
    revisions.create(op.get_bind())
    for event in ("UPDATE", "DELETE"):
        op.execute(
            f"CREATE TRIGGER inventory_revision_no_{event.lower()} BEFORE {event} ON production_inventory_review_revisions FOR EACH ROW BEGIN SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT='inventory review revision is immutable'; END"
        )
    op.execute(
        """CREATE TRIGGER inventory_source_immutable BEFORE UPDATE ON production_inventory_reviews FOR EACH ROW BEGIN IF NOT (OLD.site_id <=> NEW.site_id) OR NOT (OLD.review_id <=> NEW.review_id) OR NOT (OLD.source_identity <=> NEW.source_identity) OR NOT (OLD.source_digest <=> NEW.source_digest) OR NOT (OLD.source_manifest_digest <=> NEW.source_manifest_digest) OR NOT (OLD.source_snapshot_json <=> NEW.source_snapshot_json) OR NOT (OLD.parser_version <=> NEW.parser_version) OR NOT (OLD.policy_version <=> NEW.policy_version) OR NOT (OLD.source_format <=> NEW.source_format) OR NOT (OLD.source_name <=> NEW.source_name) OR NOT (OLD.created_by <=> NEW.created_by) OR NOT (OLD.created_at <=> NEW.created_at) THEN SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT='inventory source is immutable'; END IF; END"""
    )


def downgrade():
    raise RuntimeError("Inventory reconciliation history must be retained")
