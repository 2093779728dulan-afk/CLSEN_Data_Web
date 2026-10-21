"""Constrain administrator operation ledgers to a fixed non-secret marker."""

from __future__ import annotations

import re

import sqlalchemy as sa
from alembic import context, op

revision = "0015"
down_revision = "0014"
branch_labels = None
depends_on = None

_SECRET_NOT_STORED = "$secret-not-stored$v1$"
_MARKER_CONSTRAINT = "ck_admin_operation_tokens_secret_marker"
_LEGACY_SECRET_CONSTRAINT = "ck_admin_operation_tokens_secret"
_MARKER_CHECK_SQL = (
    f"secret_verifier IS NULL OR secret_verifier = '{_SECRET_NOT_STORED}'"
)
_EXPECTED_WRITE_GUARD_TRIGGERS = frozenset(
    {
        "trg_admin_operation_tokens_no_update",
        "trg_admin_operation_tokens_no_delete",
        "trg_admin_operation_results_no_update",
        "trg_admin_operation_results_no_delete",
    }
)


def _normalize_check_clause(clause: str) -> str:
    normalized = clause.casefold().replace("`", "").replace("\\'", "'")
    normalized = re.sub(r"_[a-z0-9]+(?=')", "", normalized)
    return re.sub(r"[\s()]", "", normalized)


_NORMALIZED_MARKER_CHECK = _normalize_check_clause(_MARKER_CHECK_SQL)


def _assert_write_guard_contract() -> None:
    """Require 0011's operation semantics and immutable-ledger guards."""

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
            "0015 requires all administrator operation ledger write guards; "
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
            "0015 requires the registered migration account write-guard bypass; "
            "do not drop the immutable triggers"
        )

    legacy_contract = (
        bind.execute(
            sa.text(
                """
                SELECT constraint_type AS constraint_kind,
                       enforced AS enforcement
                FROM information_schema.table_constraints
                WHERE constraint_schema = DATABASE()
                  AND table_name = 'admin_operation_tokens'
                  AND constraint_name = :constraint_name
                """
            ),
            {"constraint_name": _LEGACY_SECRET_CONSTRAINT},
        )
        .mappings()
        .one_or_none()
    )
    if (
        legacy_contract is None
        or str(legacy_contract["constraint_kind"]).upper() != "CHECK"
        or str(legacy_contract["enforcement"]).upper() != "YES"
    ):
        raise RuntimeError(
            "0015 requires the enforced 0011 create_user/update_user secret "
            "operation contract; repair it before retrying"
        )


def _marker_constraint_exists() -> bool:
    """Return whether the exact enforced marker CHECK already exists."""

    bind = op.get_bind()
    row = (
        bind.execute(
            sa.text(
                """
                SELECT constraints.constraint_type AS constraint_kind,
                       constraints.enforced AS enforcement,
                       checks.check_clause AS check_clause
                FROM information_schema.table_constraints AS constraints
                LEFT JOIN information_schema.check_constraints AS checks
                  ON checks.constraint_schema = constraints.constraint_schema
                 AND checks.constraint_name = constraints.constraint_name
                WHERE constraints.constraint_schema = DATABASE()
                  AND constraints.table_name = 'admin_operation_tokens'
                  AND constraints.constraint_name = :constraint_name
                """
            ),
            {"constraint_name": _MARKER_CONSTRAINT},
        )
        .mappings()
        .one_or_none()
    )
    if row is None:
        return False

    check_clause = row["check_clause"]
    if (
        str(row["constraint_kind"]).upper() != "CHECK"
        or str(row["enforcement"]).upper() != "YES"
        or not isinstance(check_clause, str)
        or _normalize_check_clause(check_clause) != _NORMALIZED_MARKER_CHECK
    ):
        raise RuntimeError(
            "0015 found an incompatible admin operation secret marker "
            "constraint; repair it explicitly before retrying"
        )
    return True


def upgrade() -> None:
    _assert_write_guard_contract()
    marker_constraint_exists = (
        False if context.is_offline_mode() else _marker_constraint_exists()
    )

    op.execute(
        sa.text(
            """
            UPDATE admin_operation_tokens
            SET secret_verifier = '$secret-not-stored$v1$'
            WHERE secret_verifier IS NOT NULL
            """
        )
    )
    if not marker_constraint_exists:
        op.create_check_constraint(
            _MARKER_CONSTRAINT,
            "admin_operation_tokens",
            _MARKER_CHECK_SQL,
        )

    if not context.is_offline_mode() and not _marker_constraint_exists():
        raise RuntimeError(
            "0015 failed to install the admin operation secret marker constraint"
        )


def downgrade() -> None:
    _assert_write_guard_contract()
    if context.is_offline_mode() or _marker_constraint_exists():
        op.drop_constraint(
            _MARKER_CONSTRAINT,
            "admin_operation_tokens",
            type_="check",
        )

    if not context.is_offline_mode() and _marker_constraint_exists():
        raise RuntimeError(
            "0015 failed to remove the admin operation secret marker constraint"
        )

    # Secret material removed by 0012-0015 is deliberately unrecoverable.
    # Retaining NULL/fixed markers preserves every 0014 application behavior.
