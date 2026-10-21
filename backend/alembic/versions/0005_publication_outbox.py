"""Add idempotent publication commands, events, and transactional outbox."""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import mysql

revision = "0005"
down_revision = "0004"
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
        "publication_commands",
        sa.Column("id", _bigint(), autoincrement=True, nullable=False),
        sa.Column("actor_user_id", _bigint(), nullable=False),
        sa.Column("command_type", sa.String(length=32), nullable=False),
        sa.Column("idempotency_key", sa.String(length=128), nullable=False),
        sa.Column(
            "status",
            sa.String(length=24),
            server_default=sa.text("'in_progress'"),
            nullable=False,
        ),
        sa.Column("redacted_request_payload", mysql.JSON(), nullable=False),
        sa.Column("redacted_result_payload", mysql.JSON(), nullable=True),
        sa.Column(
            "created_at",
            _utc_datetime(),
            server_default=sa.text("CURRENT_TIMESTAMP(6)"),
            nullable=False,
        ),
        sa.Column("completed_at", _utc_datetime(), nullable=True),
        sa.PrimaryKeyConstraint("id", name="pk_publication_commands"),
        sa.UniqueConstraint(
            "actor_user_id",
            "command_type",
            "idempotency_key",
            name="uq_publication_commands_actor_type_key",
        ),
        sa.ForeignKeyConstraint(
            ["actor_user_id"],
            ["users.id"],
            name="fk_publication_commands_actor",
            ondelete="RESTRICT",
            onupdate="RESTRICT",
        ),
        sa.CheckConstraint(
            "command_type IN "
            "('publish', 'replace', 'rollback', 'withdraw', "
            "'move', 'reverse_move')",
            name="ck_publication_commands_type",
        ),
        sa.CheckConstraint(
            "status IN ('in_progress', 'succeeded', 'failed')",
            name="ck_publication_commands_status",
        ),
        **_TABLE_OPTIONS,
    )

    op.create_table(
        "publication_events",
        sa.Column("id", _bigint(), autoincrement=True, nullable=False),
        sa.Column("command_id", _bigint(), nullable=False),
        sa.Column("sequence_number", _bigint(), nullable=False),
        sa.Column("event_type", sa.String(length=32), nullable=False),
        sa.Column("dataset_id", _bigint(), nullable=False),
        sa.Column("peer_dataset_id", _bigint(), nullable=True),
        sa.Column(
            "previous_version_id",
            _bigint(),
            nullable=True,
        ),
        sa.Column("next_version_id", _bigint(), nullable=True),
        sa.Column("reason", mysql.LONGTEXT(), nullable=True),
        sa.Column("redacted_payload", mysql.JSON(), nullable=False),
        sa.Column(
            "occurred_at",
            _utc_datetime(),
            server_default=sa.text("CURRENT_TIMESTAMP(6)"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id", name="pk_publication_events"),
        sa.UniqueConstraint(
            "command_id",
            "sequence_number",
            name="uq_publication_events_command_sequence",
        ),
        sa.ForeignKeyConstraint(
            ["command_id"],
            ["publication_commands.id"],
            name="fk_publication_events_command",
            ondelete="RESTRICT",
            onupdate="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["peer_dataset_id"],
            ["daily_datasets.id"],
            name="fk_publication_events_peer_dataset",
            ondelete="RESTRICT",
            onupdate="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["dataset_id", "previous_version_id"],
            ["dataset_versions.dataset_id", "dataset_versions.id"],
            name="fk_publication_events_previous_version",
            ondelete="RESTRICT",
            onupdate="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["dataset_id", "next_version_id"],
            ["dataset_versions.dataset_id", "dataset_versions.id"],
            name="fk_publication_events_next_version",
            ondelete="RESTRICT",
            onupdate="RESTRICT",
        ),
        sa.CheckConstraint(
            "previous_version_id IS NOT NULL OR next_version_id IS NOT NULL",
            name="ck_publication_events_has_version",
        ),
        sa.CheckConstraint(
            "event_type IN "
            "('published', 'replaced', 'rolled_back', 'withdrawn', "
            "'moved_out', 'moved_in', 'move_reversed')",
            name="ck_publication_events_type",
        ),
        sa.Index(
            "ix_publication_events_dataset_occurred",
            "dataset_id",
            "occurred_at",
            "id",
        ),
        sa.Index(
            "ix_publication_events_peer_dataset",
            "peer_dataset_id",
            "id",
        ),
        **_TABLE_OPTIONS,
    )

    op.create_table(
        "publication_outbox",
        sa.Column("id", _bigint(), autoincrement=True, nullable=False),
        sa.Column(
            "publication_event_id",
            _bigint(),
            nullable=True,
        ),
        sa.Column(
            "site_config_version_id",
            _bigint(),
            nullable=True,
        ),
        sa.Column("topic", sa.String(length=64), nullable=False),
        sa.Column("dedupe_key", sa.String(length=191), nullable=False),
        sa.Column("redacted_payload", mysql.JSON(), nullable=False),
        sa.Column(
            "status",
            sa.String(length=24),
            server_default=sa.text("'pending'"),
            nullable=False,
        ),
        sa.Column(
            "attempt_count",
            _bigint(),
            server_default=sa.text("0"),
            nullable=False,
        ),
        sa.Column("available_at", _utc_datetime(), nullable=False),
        sa.Column("locked_at", _utc_datetime(), nullable=True),
        sa.Column("locked_by", sa.String(length=128), nullable=True),
        sa.Column("processed_at", _utc_datetime(), nullable=True),
        sa.Column("last_error", mysql.LONGTEXT(), nullable=True),
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
        sa.PrimaryKeyConstraint("id", name="pk_publication_outbox"),
        sa.UniqueConstraint(
            "dedupe_key",
            name="uq_publication_outbox_dedupe_key",
        ),
        sa.ForeignKeyConstraint(
            ["publication_event_id"],
            ["publication_events.id"],
            name="fk_publication_outbox_event",
            ondelete="RESTRICT",
            onupdate="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["site_config_version_id"],
            ["site_config_versions.id"],
            name="fk_publication_outbox_site_config",
            ondelete="RESTRICT",
            onupdate="RESTRICT",
        ),
        sa.CheckConstraint(
            "((publication_event_id IS NOT NULL "
            "AND site_config_version_id IS NULL) OR "
            "(publication_event_id IS NULL "
            "AND site_config_version_id IS NOT NULL))",
            name="ck_publication_outbox_one_source",
        ),
        sa.CheckConstraint(
            "status IN ('pending', 'processing', 'completed', 'failed')",
            name="ck_publication_outbox_status",
        ),
        sa.Index(
            "ix_publication_outbox_status_available_id",
            "status",
            "available_at",
            "id",
        ),
        **_TABLE_OPTIONS,
    )


def downgrade() -> None:
    op.drop_table("publication_outbox")
    op.drop_table("publication_events")
    op.drop_table("publication_commands")
