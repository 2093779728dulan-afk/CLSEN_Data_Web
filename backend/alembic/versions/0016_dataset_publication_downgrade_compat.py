"""Restore durable child indexes required by legacy review/publication FKs."""

from __future__ import annotations

import sqlalchemy as sa
from alembic import context, op

revision = "0016"
down_revision = "0015"
branch_labels = None
depends_on = None

type _IndexSignature = tuple[tuple[int, str, int, int | None, str | None, str], ...]
type _IndexSpec = tuple[str, str, str, tuple[str, ...], _IndexSignature]


_INDEX_SPECS = (
    (
        "dataset publication",
        "dataset_publications",
        "fk_dataset_publications_version",
        ("dataset_id", "version_id"),
        (
            (1, "dataset_id", 1, None, "A", "BTREE"),
            (2, "version_id", 1, None, "A", "BTREE"),
        ),
    ),
    (
        "issue review",
        "issue_review_events",
        "fk_issue_review_events_issue_run",
        ("version_id", "validation_run_id", "validation_issue_id"),
        (
            (1, "version_id", 1, None, "A", "BTREE"),
            (2, "validation_run_id", 1, None, "A", "BTREE"),
            (3, "validation_issue_id", 1, None, "A", "BTREE"),
        ),
    ),
    (
        "field change",
        "field_changes",
        "fk_field_changes_change_event",
        ("version_id", "id"),
        (
            (1, "version_id", 1, None, "A", "BTREE"),
            (2, "id", 1, None, "A", "BTREE"),
        ),
    ),
    (
        "row change",
        "row_changes",
        "fk_row_changes_change_event",
        ("version_id", "id"),
        (
            (1, "version_id", 1, None, "A", "BTREE"),
            (2, "id", 1, None, "A", "BTREE"),
        ),
    ),
)


def _compatibility_index_exists(spec: _IndexSpec) -> bool:
    """Return whether the named index has the exact legacy FK definition."""

    label, table_name, index_name, _columns, expected_signature = spec
    rows = (
        op.get_bind()
        .execute(
            sa.text(
                """
                SELECT seq_in_index, column_name, non_unique, sub_part,
                       collation, index_type
                FROM information_schema.statistics
                WHERE table_schema = DATABASE()
                  AND table_name = :table_name
                  AND index_name = :index_name
                ORDER BY seq_in_index
                """
            ),
            {"table_name": table_name, "index_name": index_name},
        )
        .tuples()
        .all()
    )
    if not rows:
        return False

    signature = tuple(
        (
            int(row[0]),
            str(row[1]),
            int(row[2]),
            None if row[3] is None else int(row[3]),
            None if row[4] is None else str(row[4]).upper(),
            str(row[5]).upper(),
        )
        for row in rows
    )
    if signature != expected_signature:
        raise RuntimeError(
            f"0016 found an incompatible {label} downgrade "
            "compatibility index; repair it explicitly before retrying"
        )
    return True


def _ensure_compatibility_index(spec: _IndexSpec) -> None:
    if _compatibility_index_exists(spec):
        return

    label, table_name, index_name, columns, _expected_signature = spec
    op.create_index(
        index_name,
        table_name,
        list(columns),
        unique=False,
    )
    if not _compatibility_index_exists(spec):
        raise RuntimeError(
            f"0016 failed to install the {label} downgrade compatibility index"
        )


def upgrade() -> None:
    for spec in _INDEX_SPECS:
        if context.is_offline_mode():
            _label, table_name, index_name, columns, _expected_signature = spec
            op.create_index(
                index_name,
                table_name,
                list(columns),
                unique=False,
            )
        else:
            _ensure_compatibility_index(spec)


def downgrade() -> None:
    if not context.is_offline_mode():
        for spec in _INDEX_SPECS:
            _ensure_compatibility_index(spec)

    # Intentionally retain all compatibility indexes at 0015 and below. Revision 0009
    # recreates historical shorter foreign keys before removing their wider
    # replacements; without dedicated child indexes MySQL binds the old FKs to
    # the replacement indexes and then refuses to drop those indexes. These are
    # the same index shapes MySQL created implicitly before revision 0009.
