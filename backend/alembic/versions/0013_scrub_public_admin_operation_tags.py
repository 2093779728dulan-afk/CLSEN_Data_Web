"""Invalidate administrator operation tags created with the public local key."""

from __future__ import annotations

import sqlalchemy as sa
from alembic import context, op

revision = "0013"
down_revision = "0012"
branch_labels = None
depends_on = None

_EXPECTED_WRITE_GUARD_TRIGGERS = frozenset(
    {
        "trg_admin_operation_tokens_no_update",
        "trg_admin_operation_tokens_no_delete",
        "trg_admin_operation_results_no_update",
        "trg_admin_operation_results_no_delete",
    }
)


def _assert_write_guard_contract() -> None:
    """Require the immutable ledger contract before invalidating unsafe tags."""

    if context.is_offline_mode():
        return
    bind = op.get_bind()
    triggers = frozenset(
        str(value)
        for value in bind.scalars(
            sa.text(
                """
                SELECT trigger_name
                FROM information_schema.triggers
                WHERE trigger_schema = DATABASE()
                  AND event_object_table IN (
                      'admin_operation_tokens', 'admin_operation_results'
                  )
                """
            )
        )
    )
    if triggers != _EXPECTED_WRITE_GUARD_TRIGGERS:
        raise RuntimeError(
            "0013 requires all administrator operation ledger write guards; "
            "repair the 0011 contract before retrying"
        )
    bypass_count = bind.scalar(
        sa.text(
            """
            SELECT COUNT(*)
            FROM terminal_write_guard_bypass_accounts
            WHERE account_identity = USER()
            """
        )
    )
    if int(bypass_count or 0) != 1:
        raise RuntimeError(
            "0013 requires the registered migration account write-guard bypass; "
            "do not drop the immutable triggers"
        )


def upgrade() -> None:
    _assert_write_guard_contract()
    op.execute(
        sa.text(
            """
            UPDATE admin_operation_tokens
            SET secret_verifier = '$legacy-untrusted$v1$'
            WHERE secret_verifier LIKE '$hmac-sha256$v1$%'
            """
        )
    )


def downgrade() -> None:
    # Tags created with the public development key must never become trusted
    # again. Existing v2 tags and the sentinel are both rejected by v1 code.
    pass
