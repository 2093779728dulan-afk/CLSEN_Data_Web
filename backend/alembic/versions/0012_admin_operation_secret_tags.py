"""Replace legacy administrator password verifiers with an untrusted sentinel."""

from __future__ import annotations

import sqlalchemy as sa
from alembic import context, op

revision = "0012"
down_revision = "0011"
branch_labels = None
depends_on = None

_LEGACY_SENTINEL = "$legacy-untrusted$v1$"
_EXPECTED_WRITE_GUARD_TRIGGERS = frozenset(
    {
        "trg_admin_operation_tokens_no_update",
        "trg_admin_operation_tokens_no_delete",
        "trg_admin_operation_results_no_update",
        "trg_admin_operation_results_no_delete",
    }
)


def _assert_write_guard_contract() -> None:
    """Require 0011's immutable ledger contract before scrubbing its rows."""

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
            "0012 requires all administrator operation ledger write guards; "
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
            "0012 requires the registered migration account write-guard bypass; "
            "do not drop the immutable triggers"
        )


def upgrade() -> None:
    _assert_write_guard_contract()
    op.execute(
        sa.text(
            """
            UPDATE admin_operation_tokens
            SET secret_verifier = '$legacy-untrusted$v1$'
            WHERE secret_verifier LIKE '$argon2%'
            """
        )
    )


def downgrade() -> None:
    # The original Argon2 values are deliberately unrecoverable.  HMAC tags and
    # the legacy sentinel are both rejected by the 0011 application verifier,
    # so retaining them is the only safe downgrade for existing ledger rows.
    pass
