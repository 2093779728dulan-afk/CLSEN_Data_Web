"""Add durable retry and recovery state for catalog export jobs."""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import mysql

revision = "0024"
down_revision = "0023"
branch_labels = None
depends_on = None


def _code(length: int) -> mysql.VARCHAR:
    return mysql.VARCHAR(length, charset="ascii", collation="ascii_bin")


def upgrade() -> None:
    op.add_column(
        "catalog_jobs",
        sa.Column(
            "attempt_count",
            mysql.BIGINT(unsigned=True),
            server_default=sa.text("0"),
            nullable=False,
        ),
    )
    op.add_column(
        "catalog_jobs",
        sa.Column("next_attempt_at", mysql.DATETIME(fsp=6), nullable=True),
    )
    op.add_column(
        "catalog_jobs",
        sa.Column(
            "execution_phase",
            _code(32),
            server_default=sa.text("'waiting_for_worker'"),
            nullable=False,
        ),
    )
    op.add_column(
        "catalog_jobs",
        sa.Column("last_attempt_started_at", mysql.DATETIME(fsp=6), nullable=True),
    )
    op.add_column(
        "catalog_jobs",
        sa.Column("last_attempt_completed_at", mysql.DATETIME(fsp=6), nullable=True),
    )
    op.execute(
        sa.text(
            """
            INSERT IGNORE INTO catalog_jobs (
                site_id, job_kind, resource_kind, resource_id, status,
                retry_allowed, failure_reason_code, execution_phase
            )
            SELECT site_id, 'catalog_export', 'catalog_export', id,
                   CASE export_status
                     WHEN 'building' THEN 'queued'
                     WHEN 'ready' THEN 'succeeded'
                     ELSE 'failed'
                   END,
                   FALSE, failure_reason_code,
                   CASE export_status
                     WHEN 'building' THEN 'waiting_for_worker'
                     WHEN 'ready' THEN 'completed'
                     ELSE 'failed'
                   END
            FROM catalog_exports
            """
        )
    )
    op.execute(
        sa.text(
            """
            UPDATE catalog_jobs AS jobs
            INNER JOIN catalog_exports AS exports
                ON exports.id = jobs.resource_id
               AND exports.site_id = jobs.site_id
            SET jobs.status = CASE exports.export_status
                    WHEN 'building' THEN 'queued'
                    WHEN 'ready' THEN 'succeeded'
                    ELSE 'failed'
                END,
                jobs.lease_token = NULL,
                jobs.lease_expires_at = NULL,
                jobs.next_attempt_at = NULL,
                jobs.retry_allowed = FALSE,
                jobs.failure_reason_code = exports.failure_reason_code,
                jobs.execution_phase = CASE exports.export_status
                    WHEN 'building' THEN 'waiting_for_worker'
                    WHEN 'ready' THEN 'completed'
                    ELSE 'failed'
                END
            WHERE jobs.job_kind = 'catalog_export'
              AND jobs.resource_kind = 'catalog_export'
            """
        )
    )
    op.create_check_constraint(
        "ck_catalog_jobs_execution_phase",
        "catalog_jobs",
        "execution_phase IN ('waiting_for_worker','materializing',"
        "'retry_scheduled','awaiting_manual_recovery','completed','failed')",
    )
    op.create_check_constraint(
        "ck_catalog_jobs_attempt_schedule",
        "catalog_jobs",
        "next_attempt_at IS NULL OR status = 'queued'",
    )
    op.create_index(
        "ix_catalog_jobs_due",
        "catalog_jobs",
        ["job_kind", "status", "next_attempt_at", "lease_expires_at", "id"],
    )


def downgrade() -> None:
    op.drop_index("ix_catalog_jobs_due", table_name="catalog_jobs")
    op.drop_constraint(
        "ck_catalog_jobs_attempt_schedule", "catalog_jobs", type_="check"
    )
    op.drop_constraint("ck_catalog_jobs_execution_phase", "catalog_jobs", type_="check")
    op.drop_column("catalog_jobs", "last_attempt_completed_at")
    op.drop_column("catalog_jobs", "last_attempt_started_at")
    op.drop_column("catalog_jobs", "execution_phase")
    op.drop_column("catalog_jobs", "next_attempt_at")
    op.drop_column("catalog_jobs", "attempt_count")
