"""Add database-authoritative Worker instance and consumer observations."""

from __future__ import annotations

from typing import Any

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import mysql

revision = "0023"
down_revision = "0022"
branch_labels = None
depends_on = None

_TABLE_OPTIONS: dict[str, Any] = {
    "mysql_engine": "InnoDB",
    "mysql_charset": "utf8mb4",
    "mysql_collate": "utf8mb4_0900_ai_ci",
}


def _code_type(length: int) -> mysql.VARCHAR:
    return mysql.VARCHAR(length, charset="ascii", collation="ascii_bin")


def _timestamp_type() -> mysql.DATETIME:
    return mysql.DATETIME(fsp=6)


def _counter_type() -> mysql.BIGINT:
    return mysql.BIGINT(unsigned=True)


def upgrade() -> None:
    op.create_table(
        "worker_instances",
        sa.Column("instance_id", mysql.BINARY(16), nullable=False),
        sa.Column("role", _code_type(32), nullable=False),
        sa.Column("build_id", _code_type(64), nullable=False),
        sa.Column("supported_queues", mysql.JSON(), nullable=False),
        sa.Column("lifecycle_status", _code_type(16), nullable=False),
        sa.Column(
            "heartbeat_sequence",
            _counter_type(),
            server_default=sa.text("0"),
            nullable=False,
        ),
        sa.Column(
            "started_at",
            _timestamp_type(),
            server_default=sa.text("CURRENT_TIMESTAMP(6)"),
            nullable=False,
        ),
        sa.Column(
            "last_heartbeat_at",
            _timestamp_type(),
            server_default=sa.text("CURRENT_TIMESTAMP(6)"),
            nullable=False,
        ),
        sa.Column("stopped_at", _timestamp_type(), nullable=True),
        sa.Column("last_result_code", _code_type(64), nullable=True),
        sa.PrimaryKeyConstraint("instance_id", name="pk_worker_instances"),
        sa.CheckConstraint(
            "role = 'local_worker'",
            name="ck_worker_instances_role",
        ),
        sa.CheckConstraint(
            "lifecycle_status IN ('running','stopped')",
            name="ck_worker_instances_lifecycle",
        ),
        sa.CheckConstraint(
            "JSON_TYPE(supported_queues) = 'ARRAY' "
            "AND JSON_LENGTH(supported_queues) = 4 "
            "AND JSON_CONTAINS(supported_queues, JSON_QUOTE('return_dedup')) "
            "AND JSON_CONTAINS(supported_queues, JSON_QUOTE('publication_outbox')) "
            "AND JSON_CONTAINS(supported_queues, JSON_QUOTE('catalog_export')) "
            "AND JSON_CONTAINS(supported_queues, JSON_QUOTE('catalog_import'))",
            name="ck_worker_instances_supported_queues",
        ),
        sa.CheckConstraint(
            "last_heartbeat_at >= started_at",
            name="ck_worker_instances_heartbeat_order",
        ),
        sa.CheckConstraint(
            "((lifecycle_status = 'running' AND stopped_at IS NULL) OR "
            "(lifecycle_status = 'stopped' AND stopped_at IS NOT NULL "
            "AND stopped_at >= last_heartbeat_at))",
            name="ck_worker_instances_stopped_state",
        ),
        sa.CheckConstraint(
            "last_result_code IS NULL OR "
            "last_result_code REGEXP '^[a-z][a-z0-9_]{0,63}$'",
            name="ck_worker_instances_result_code",
        ),
        sa.Index(
            "ix_worker_instances_lifecycle_heartbeat",
            "lifecycle_status",
            "last_heartbeat_at",
            "instance_id",
        ),
        sa.Index(
            "ix_worker_instances_retention",
            "stopped_at",
            "last_heartbeat_at",
            "instance_id",
        ),
        **_TABLE_OPTIONS,
    )

    op.create_table(
        "worker_consumer_states",
        sa.Column("worker_instance_id", mysql.BINARY(16), nullable=False),
        sa.Column("queue_name", _code_type(32), nullable=False),
        sa.Column("last_poll_started_at", _timestamp_type(), nullable=True),
        sa.Column("last_poll_completed_at", _timestamp_type(), nullable=True),
        sa.Column("last_poll_succeeded_at", _timestamp_type(), nullable=True),
        sa.Column("last_poll_failed_at", _timestamp_type(), nullable=True),
        sa.Column(
            "consecutive_failures",
            _counter_type(),
            server_default=sa.text("0"),
            nullable=False,
        ),
        sa.Column("last_result_code", _code_type(64), nullable=True),
        sa.Column("last_failure_code", _code_type(64), nullable=True),
        sa.PrimaryKeyConstraint(
            "worker_instance_id",
            "queue_name",
            name="pk_worker_consumer_states",
        ),
        sa.ForeignKeyConstraint(
            ["worker_instance_id"],
            ["worker_instances.instance_id"],
            name="fk_worker_consumer_states_instance",
            ondelete="CASCADE",
            onupdate="RESTRICT",
        ),
        sa.CheckConstraint(
            "queue_name IN "
            "('return_dedup','publication_outbox','catalog_export','catalog_import')",
            name="ck_worker_consumer_states_queue",
        ),
        sa.CheckConstraint(
            "((consecutive_failures = 0 AND last_failure_code IS NULL) OR "
            "(consecutive_failures > 0 AND last_failure_code IS NOT NULL))",
            name="ck_worker_consumer_states_failure_state",
        ),
        sa.CheckConstraint(
            "last_result_code IS NULL OR "
            "last_result_code REGEXP '^[a-z][a-z0-9_]{0,63}$'",
            name="ck_worker_consumer_states_result_code",
        ),
        sa.CheckConstraint(
            "last_failure_code IS NULL OR "
            "last_failure_code REGEXP '^[a-z][a-z0-9_]{0,63}$'",
            name="ck_worker_consumer_states_failure_code",
        ),
        sa.Index(
            "ix_worker_consumer_states_queue_completed",
            "queue_name",
            "last_poll_completed_at",
            "worker_instance_id",
        ),
        **_TABLE_OPTIONS,
    )


def downgrade() -> None:
    op.drop_table("worker_consumer_states")
    op.drop_table("worker_instances")
