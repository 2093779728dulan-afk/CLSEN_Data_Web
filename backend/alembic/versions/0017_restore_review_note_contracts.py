"""Restore and verify review idempotency and note-thread contracts."""

from __future__ import annotations

import re
from typing import Any

import sqlalchemy as sa
from alembic import context, op
from sqlalchemy.dialects import mysql

revision = "0017"
down_revision = "0016"
branch_labels = None
depends_on = None

_TABLE_OPTIONS: dict[str, Any] = {
    "mysql_engine": "InnoDB",
    "mysql_charset": "utf8mb4",
    "mysql_collate": "utf8mb4_0900_ai_ci",
}
_REPAIRED_TABLES = frozenset(
    {
        "note_threads",
        "publication_command_results",
        "review_operation_tokens",
        "review_operation_results",
        "version_review_events",
    }
)

type _ColumnSignature = tuple[
    int,
    str,
    str,
    str,
    str | None,
    str | None,
    str | None,
    str,
    str,
]
type _KeyColumn = tuple[
    int,
    str,
    str | None,
    str | None,
    str | None,
    int | None,
]
type _KeySignature = tuple[
    str,
    str,
    tuple[_KeyColumn, ...],
    str | None,
    str | None,
]
type _IndexSignature = tuple[
    int,
    str,
    str,
    tuple[tuple[int, str | None, int | None, str | None], ...],
]


def _column(
    position: int,
    name: str,
    column_type: str,
    nullable: bool,
    *,
    default: str | None = None,
    charset: str | None = None,
    collation: str | None = None,
    extra: str = "",
) -> _ColumnSignature:
    return (
        position,
        name,
        column_type,
        "YES" if nullable else "NO",
        default,
        charset,
        collation,
        extra,
        "",
    )


_NOTE_THREAD_COLUMNS = (
    _column(
        1,
        "note_key",
        "varchar(64)",
        False,
        charset="utf8mb4",
        collation="utf8mb4_0900_ai_ci",
    ),
    _column(
        2,
        "target_type",
        "varchar(24)",
        False,
        charset="utf8mb4",
        collation="utf8mb4_0900_ai_ci",
    ),
    _column(3, "import_batch_id", "bigint unsigned", True),
    _column(4, "version_id", "bigint unsigned", True),
    _column(5, "row_id", "bigint unsigned", True),
    _column(
        6,
        "field_name",
        "varchar(128)",
        True,
        charset="utf8mb4",
        collation="utf8mb4_0900_ai_ci",
    ),
    _column(7, "created_at", "datetime(6)", False),
)
_REVIEW_TOKEN_COLUMNS = (
    _column(1, "operation_token", "binary(16)", False),
    _column(
        2,
        "operation_kind",
        "varchar(32)",
        False,
        charset="ascii",
        collation="ascii_bin",
    ),
    _column(3, "operation_digest", "binary(32)", False),
    _column(4, "actor_user_id", "bigint unsigned", False),
    _column(5, "registered_at", "datetime(6)", False),
)
_VERSION_REVIEW_EVENT_COLUMNS = (
    _column(1, "id", "bigint unsigned", False, extra="auto_increment"),
    _column(2, "operation_token", "binary(16)", False),
    _column(
        3,
        "operation_kind",
        "varchar(32)",
        False,
        charset="ascii",
        collation="ascii_bin",
    ),
    _column(4, "operation_digest", "binary(32)", False),
    _column(5, "actor_user_id", "bigint unsigned", False),
    _column(6, "dataset_id", "bigint unsigned", False),
    _column(7, "version_id", "bigint unsigned", False),
    _column(
        8,
        "from_status",
        "varchar(32)",
        False,
        charset="ascii",
        collation="ascii_bin",
    ),
    _column(
        9,
        "to_status",
        "varchar(32)",
        False,
        charset="ascii",
        collation="ascii_bin",
    ),
    _column(10, "data_revision", "bigint unsigned", False),
    _column(11, "from_review_revision", "bigint unsigned", False),
    _column(12, "to_review_revision", "bigint unsigned", False),
    _column(13, "selected_validation_run_id", "bigint unsigned", True),
    _column(14, "confirmation_digest", "binary(32)", True),
    _column(15, "confirmation_json", "json", True),
    _column(
        16,
        "reason",
        "longtext",
        False,
        charset="utf8mb4",
        collation="utf8mb4_0900_ai_ci",
    ),
    _column(17, "occurred_at", "datetime(6)", False),
)
_REVIEW_RESULT_COLUMNS = (
    _column(1, "operation_token", "binary(16)", False),
    _column(
        2,
        "operation_kind",
        "varchar(32)",
        False,
        charset="ascii",
        collation="ascii_bin",
    ),
    _column(3, "operation_digest", "binary(32)", False),
    _column(4, "actor_user_id", "bigint unsigned", False),
    _column(
        5, "result_kind", "varchar(32)", False, charset="ascii", collation="ascii_bin"
    ),
    _column(6, "result_import_batch_id", "bigint unsigned", True),
    _column(7, "result_dataset_id", "bigint unsigned", True),
    _column(8, "result_version_id", "bigint unsigned", True),
    _column(
        9, "result_status", "varchar(32)", True, charset="ascii", collation="ascii_bin"
    ),
    _column(10, "result_data_revision", "bigint unsigned", True),
    _column(11, "result_review_revision", "bigint unsigned", True),
    _column(12, "affected_row_id", "bigint unsigned", True),
    _column(13, "data_change_event_id", "bigint unsigned", True),
    _column(14, "issue_review_event_id", "bigint unsigned", True),
    _column(15, "validation_run_id", "bigint unsigned", True),
    _column(16, "version_review_event_id", "bigint unsigned", True),
    _column(17, "note_id", "bigint unsigned", True),
    _column(18, "completed_at", "datetime(6)", False),
)
_PUBLICATION_RESULT_COLUMNS = (
    _column(1, "command_id", "bigint unsigned", False),
    _column(2, "operation_token", "binary(16)", False),
    _column(
        3,
        "operation_kind",
        "varchar(32)",
        False,
        charset="ascii",
        collation="ascii_bin",
    ),
    _column(4, "operation_digest", "binary(32)", False),
    _column(5, "actor_user_id", "bigint unsigned", False),
    _column(
        6,
        "result_kind",
        "varchar(32)",
        False,
        charset="ascii",
        collation="ascii_bin",
    ),
    _column(7, "result_dataset_id", "bigint unsigned", True),
    _column(8, "result_version_id", "bigint unsigned", True),
    _column(
        9,
        "result_status",
        "varchar(32)",
        True,
        charset="ascii",
        collation="ascii_bin",
    ),
    _column(10, "result_data_revision", "bigint unsigned", True),
    _column(11, "result_review_revision", "bigint unsigned", True),
    _column(12, "validation_run_id", "bigint unsigned", True),
    _column(13, "publication_event_id", "bigint unsigned", True),
    _column(14, "move_revision_operation_token", "binary(16)", True),
    _column(15, "reversed_move_command_id", "bigint unsigned", True),
    _column(16, "redacted_result_payload", "json", False),
    _column(17, "completed_at", "datetime(6)", False),
)

_LEGACY_NOTE_COLUMNS = (
    _column(1, "id", "bigint unsigned", False, extra="auto_increment"),
    _column(
        2,
        "note_key",
        "varchar(64)",
        False,
        charset="utf8mb4",
        collation="utf8mb4_0900_ai_ci",
    ),
    _column(3, "revision_number", "bigint unsigned", False),
    _column(4, "supersedes_note_id", "bigint unsigned", True),
    _column(
        5,
        "target_type",
        "varchar(24)",
        False,
        charset="utf8mb4",
        collation="utf8mb4_0900_ai_ci",
    ),
    _column(6, "import_batch_id", "bigint unsigned", True),
    _column(7, "version_id", "bigint unsigned", True),
    _column(8, "row_id", "bigint unsigned", True),
    _column(
        9,
        "field_name",
        "varchar(128)",
        True,
        charset="utf8mb4",
        collation="utf8mb4_0900_ai_ci",
    ),
    _column(
        10,
        "visibility",
        "varchar(24)",
        False,
        charset="utf8mb4",
        collation="utf8mb4_0900_ai_ci",
    ),
    _column(
        11, "body", "longtext", False, charset="utf8mb4", collation="utf8mb4_0900_ai_ci"
    ),
    _column(12, "author_user_id", "bigint unsigned", False),
    _column(13, "review_revision", "bigint unsigned", True),
    _column(
        14,
        "created_at",
        "datetime(6)",
        False,
        default="current_timestamp(6)",
        extra="default_generated",
    ),
)
_ROUNDTRIP_LEGACY_NOTE_COLUMNS = (
    _column(1, "id", "bigint unsigned", False, extra="auto_increment"),
    _column(
        2,
        "note_key",
        "varchar(64)",
        False,
        charset="utf8mb4",
        collation="utf8mb4_0900_ai_ci",
    ),
    _column(3, "revision_number", "bigint unsigned", False),
    _column(4, "supersedes_note_id", "bigint unsigned", True),
    _column(
        5,
        "visibility",
        "varchar(24)",
        False,
        charset="utf8mb4",
        collation="utf8mb4_0900_ai_ci",
    ),
    _column(
        6, "body", "longtext", False, charset="utf8mb4", collation="utf8mb4_0900_ai_ci"
    ),
    _column(7, "author_user_id", "bigint unsigned", False),
    _column(8, "review_revision", "bigint unsigned", True),
    _column(
        9,
        "created_at",
        "datetime(6)",
        False,
        default="current_timestamp(6)",
        extra="default_generated",
    ),
    _column(
        10,
        "target_type",
        "varchar(24)",
        False,
        charset="utf8mb4",
        collation="utf8mb4_0900_ai_ci",
    ),
    _column(11, "import_batch_id", "bigint unsigned", True),
    _column(12, "version_id", "bigint unsigned", True),
    _column(13, "row_id", "bigint unsigned", True),
    _column(
        14,
        "field_name",
        "varchar(128)",
        True,
        charset="utf8mb4",
        collation="utf8mb4_0900_ai_ci",
    ),
)
_FINAL_NOTE_COLUMN_NAMES = frozenset(
    {
        "id",
        "note_key",
        "revision_number",
        "supersedes_note_id",
        "supersedes_revision_number",
        "visibility",
        "body",
        "author_user_id",
        "review_revision",
        "created_at",
    }
)
_FINAL_NOTE_COLUMNS = (
    _column(1, "id", "bigint unsigned", False, extra="auto_increment"),
    _column(
        2,
        "note_key",
        "varchar(64)",
        False,
        charset="utf8mb4",
        collation="utf8mb4_0900_ai_ci",
    ),
    _column(3, "revision_number", "bigint unsigned", False),
    _column(4, "supersedes_note_id", "bigint unsigned", True),
    _column(
        5,
        "visibility",
        "varchar(24)",
        False,
        default="internal",
        charset="utf8mb4",
        collation="utf8mb4_0900_ai_ci",
    ),
    _column(
        6, "body", "longtext", False, charset="utf8mb4", collation="utf8mb4_0900_ai_ci"
    ),
    _column(7, "author_user_id", "bigint unsigned", False),
    _column(8, "review_revision", "bigint unsigned", True),
    _column(
        9,
        "created_at",
        "datetime(6)",
        False,
        default="current_timestamp(6)",
        extra="default_generated",
    ),
    _column(10, "supersedes_revision_number", "bigint unsigned", True),
)


def _key(
    constraint_type: str,
    columns: tuple[str, ...],
    *,
    referenced_table: str | None = None,
    referenced_columns: tuple[str, ...] = (),
    update_rule: str | None = None,
    delete_rule: str | None = None,
) -> _KeySignature:
    return (
        constraint_type,
        "YES",
        tuple(
            (
                position,
                column,
                "<current>" if referenced_table is not None else None,
                referenced_table,
                referenced_columns[position - 1] if referenced_table else None,
                position if referenced_table else None,
            )
            for position, column in enumerate(columns, start=1)
        ),
        update_rule,
        delete_rule,
    )


_NOTE_THREAD_KEYS = {
    "PRIMARY": _key("PRIMARY KEY", ("note_key",)),
    "fk_note_threads_import_batch": _key(
        "FOREIGN KEY",
        ("import_batch_id",),
        referenced_table="import_batches",
        referenced_columns=("id",),
        update_rule="RESTRICT",
        delete_rule="RESTRICT",
    ),
    "fk_note_threads_version": _key(
        "FOREIGN KEY",
        ("version_id",),
        referenced_table="dataset_versions",
        referenced_columns=("id",),
        update_rule="RESTRICT",
        delete_rule="RESTRICT",
    ),
    "fk_note_threads_version_row": _key(
        "FOREIGN KEY",
        ("version_id", "row_id"),
        referenced_table="version_rows",
        referenced_columns=("version_id", "id"),
        update_rule="RESTRICT",
        delete_rule="RESTRICT",
    ),
}
_REVIEW_TOKEN_KEYS = {
    "PRIMARY": _key("PRIMARY KEY", ("operation_token",)),
    "uq_review_operation_tokens_identity": _key(
        "UNIQUE",
        (
            "operation_token",
            "operation_kind",
            "operation_digest",
            "actor_user_id",
        ),
    ),
    "fk_review_operation_tokens_actor": _key(
        "FOREIGN KEY",
        ("actor_user_id",),
        referenced_table="users",
        referenced_columns=("id",),
        update_rule="RESTRICT",
        delete_rule="RESTRICT",
    ),
}
_VERSION_REVIEW_EVENT_KEYS = {
    "PRIMARY": _key("PRIMARY KEY", ("id",)),
    "uq_version_review_events_token": _key("UNIQUE", ("operation_token",)),
    "uq_version_review_events_result_identity": _key(
        "UNIQUE",
        (
            "operation_token",
            "operation_kind",
            "operation_digest",
            "actor_user_id",
            "dataset_id",
            "version_id",
            "id",
        ),
    ),
    "fk_version_review_events_token_identity": _key(
        "FOREIGN KEY",
        (
            "operation_token",
            "operation_kind",
            "operation_digest",
            "actor_user_id",
        ),
        referenced_table="review_operation_tokens",
        referenced_columns=(
            "operation_token",
            "operation_kind",
            "operation_digest",
            "actor_user_id",
        ),
        update_rule="RESTRICT",
        delete_rule="RESTRICT",
    ),
    "fk_version_review_events_version": _key(
        "FOREIGN KEY",
        ("dataset_id", "version_id"),
        referenced_table="dataset_versions",
        referenced_columns=("dataset_id", "id"),
        update_rule="RESTRICT",
        delete_rule="RESTRICT",
    ),
    "fk_version_review_events_validation": _key(
        "FOREIGN KEY",
        ("version_id", "selected_validation_run_id"),
        referenced_table="validation_runs",
        referenced_columns=("version_id", "id"),
        update_rule="RESTRICT",
        delete_rule="RESTRICT",
    ),
}
_REVIEW_RESULT_KEYS = {
    "PRIMARY": _key("PRIMARY KEY", ("operation_token",)),
    "fk_review_operation_results_identity": _key(
        "FOREIGN KEY",
        ("operation_token", "operation_kind", "operation_digest", "actor_user_id"),
        referenced_table="review_operation_tokens",
        referenced_columns=(
            "operation_token",
            "operation_kind",
            "operation_digest",
            "actor_user_id",
        ),
        update_rule="RESTRICT",
        delete_rule="RESTRICT",
    ),
    "fk_review_operation_results_import_batch": _key(
        "FOREIGN KEY",
        ("result_import_batch_id",),
        referenced_table="import_batches",
        referenced_columns=("id",),
        update_rule="RESTRICT",
        delete_rule="RESTRICT",
    ),
    "fk_review_operation_results_version": _key(
        "FOREIGN KEY",
        ("result_dataset_id", "result_version_id"),
        referenced_table="dataset_versions",
        referenced_columns=("dataset_id", "id"),
        update_rule="RESTRICT",
        delete_rule="RESTRICT",
    ),
    "fk_review_operation_results_row": _key(
        "FOREIGN KEY",
        ("result_version_id", "affected_row_id"),
        referenced_table="version_rows",
        referenced_columns=("version_id", "id"),
        update_rule="RESTRICT",
        delete_rule="RESTRICT",
    ),
    "fk_review_operation_results_change": _key(
        "FOREIGN KEY",
        ("result_version_id", "data_change_event_id"),
        referenced_table="data_change_events",
        referenced_columns=("version_id", "id"),
        update_rule="RESTRICT",
        delete_rule="RESTRICT",
    ),
    "fk_review_operation_results_issue_review": _key(
        "FOREIGN KEY",
        ("result_version_id", "issue_review_event_id"),
        referenced_table="issue_review_events",
        referenced_columns=("version_id", "id"),
        update_rule="RESTRICT",
        delete_rule="RESTRICT",
    ),
    "fk_review_operation_results_validation": _key(
        "FOREIGN KEY",
        ("result_version_id", "validation_run_id"),
        referenced_table="validation_runs",
        referenced_columns=("version_id", "id"),
        update_rule="RESTRICT",
        delete_rule="RESTRICT",
    ),
    "fk_review_operation_results_version_review": _key(
        "FOREIGN KEY",
        (
            "operation_token",
            "operation_kind",
            "operation_digest",
            "actor_user_id",
            "result_dataset_id",
            "result_version_id",
            "version_review_event_id",
        ),
        referenced_table="version_review_events",
        referenced_columns=(
            "operation_token",
            "operation_kind",
            "operation_digest",
            "actor_user_id",
            "dataset_id",
            "version_id",
            "id",
        ),
        update_rule="RESTRICT",
        delete_rule="RESTRICT",
    ),
    "fk_review_operation_results_note": _key(
        "FOREIGN KEY",
        ("note_id",),
        referenced_table="notes",
        referenced_columns=("id",),
        update_rule="RESTRICT",
        delete_rule="RESTRICT",
    ),
}
_PUBLICATION_RESULT_KEYS = {
    "PRIMARY": _key("PRIMARY KEY", ("command_id",)),
    "uq_publication_command_results_token": _key("UNIQUE", ("operation_token",)),
    "fk_publication_command_results_identity": _key(
        "FOREIGN KEY",
        (
            "command_id",
            "operation_token",
            "operation_kind",
            "operation_digest",
            "actor_user_id",
        ),
        referenced_table="publication_commands",
        referenced_columns=(
            "id",
            "operation_token",
            "operation_kind",
            "operation_digest",
            "actor_user_id",
        ),
        update_rule="RESTRICT",
        delete_rule="RESTRICT",
    ),
    "fk_publication_command_results_version": _key(
        "FOREIGN KEY",
        ("result_dataset_id", "result_version_id"),
        referenced_table="dataset_versions",
        referenced_columns=("dataset_id", "id"),
        update_rule="RESTRICT",
        delete_rule="RESTRICT",
    ),
    "fk_publication_command_results_validation": _key(
        "FOREIGN KEY",
        ("result_version_id", "validation_run_id"),
        referenced_table="validation_runs",
        referenced_columns=("version_id", "id"),
        update_rule="RESTRICT",
        delete_rule="RESTRICT",
    ),
    "fk_publication_command_results_event": _key(
        "FOREIGN KEY",
        ("command_id", "publication_event_id"),
        referenced_table="publication_events",
        referenced_columns=("command_id", "id"),
        update_rule="RESTRICT",
        delete_rule="RESTRICT",
    ),
    "fk_publication_command_results_move_revision": _key(
        "FOREIGN KEY",
        (
            "move_revision_operation_token",
            "result_dataset_id",
            "result_version_id",
        ),
        referenced_table="draft_operation_results",
        referenced_columns=(
            "operation_token",
            "result_dataset_id",
            "result_version_id",
        ),
        update_rule="RESTRICT",
        delete_rule="RESTRICT",
    ),
    "fk_publication_command_results_reversed_move": _key(
        "FOREIGN KEY",
        ("reversed_move_command_id",),
        referenced_table="publication_commands",
        referenced_columns=("id",),
        update_rule="RESTRICT",
        delete_rule="RESTRICT",
    ),
}
_LEGACY_NOTE_KEYS = {
    "PRIMARY": _key("PRIMARY KEY", ("id",)),
    "uq_notes_key_revision": _key("UNIQUE", ("note_key", "revision_number")),
    "uq_notes_key_id": _key("UNIQUE", ("note_key", "id")),
    "uq_notes_supersedes_note": _key("UNIQUE", ("supersedes_note_id",)),
    "fk_notes_previous_revision": _key(
        "FOREIGN KEY",
        ("note_key", "supersedes_note_id"),
        referenced_table="notes",
        referenced_columns=("note_key", "id"),
        update_rule="RESTRICT",
        delete_rule="RESTRICT",
    ),
    "fk_notes_import_batch": _key(
        "FOREIGN KEY",
        ("import_batch_id",),
        referenced_table="import_batches",
        referenced_columns=("id",),
        update_rule="RESTRICT",
        delete_rule="RESTRICT",
    ),
    "fk_notes_version": _key(
        "FOREIGN KEY",
        ("version_id",),
        referenced_table="dataset_versions",
        referenced_columns=("id",),
        update_rule="RESTRICT",
        delete_rule="RESTRICT",
    ),
    "fk_notes_version_row": _key(
        "FOREIGN KEY",
        ("version_id", "row_id"),
        referenced_table="version_rows",
        referenced_columns=("version_id", "id"),
        update_rule="RESTRICT",
        delete_rule="RESTRICT",
    ),
    "fk_notes_author": _key(
        "FOREIGN KEY",
        ("author_user_id",),
        referenced_table="users",
        referenced_columns=("id",),
        update_rule="RESTRICT",
        delete_rule="RESTRICT",
    ),
}
_FINAL_NOTE_KEYS = {
    "PRIMARY": _key("PRIMARY KEY", ("id",)),
    "uq_notes_key_revision": _key("UNIQUE", ("note_key", "revision_number")),
    "uq_notes_key_id": _key("UNIQUE", ("note_key", "id")),
    "uq_notes_supersedes_note": _key("UNIQUE", ("supersedes_note_id",)),
    "uq_notes_key_revision_id": _key("UNIQUE", ("note_key", "revision_number", "id")),
    "fk_notes_previous_revision": _key(
        "FOREIGN KEY",
        ("note_key", "supersedes_revision_number", "supersedes_note_id"),
        referenced_table="notes",
        referenced_columns=("note_key", "revision_number", "id"),
        update_rule="RESTRICT",
        delete_rule="RESTRICT",
    ),
    "fk_notes_thread": _key(
        "FOREIGN KEY",
        ("note_key",),
        referenced_table="note_threads",
        referenced_columns=("note_key",),
        update_rule="RESTRICT",
        delete_rule="RESTRICT",
    ),
    "fk_notes_author": _key(
        "FOREIGN KEY",
        ("author_user_id",),
        referenced_table="users",
        referenced_columns=("id",),
        update_rule="RESTRICT",
        delete_rule="RESTRICT",
    ),
}

_NOTE_THREAD_CHECKS = {
    "ck_note_threads_target": (
        "((target_type = 'import_batch' "
        "AND import_batch_id IS NOT NULL AND version_id IS NULL "
        "AND row_id IS NULL AND field_name IS NULL) OR "
        "(target_type = 'version' "
        "AND import_batch_id IS NULL AND version_id IS NOT NULL "
        "AND row_id IS NULL AND field_name IS NULL) OR "
        "(target_type = 'row' "
        "AND import_batch_id IS NULL AND version_id IS NOT NULL "
        "AND row_id IS NOT NULL AND field_name IS NULL) OR "
        "(target_type = 'field' "
        "AND import_batch_id IS NULL AND version_id IS NOT NULL "
        "AND row_id IS NOT NULL AND field_name IS NOT NULL))"
    )
}
_REVIEW_TOKEN_CHECKS = {
    "ck_review_operation_tokens_kind": (
        "operation_kind IN "
        "('set_field', 'restore_previous_field', 'restore_parent_field', "
        "'restore_source_field', 'add_row', 'exclude_row', 'restore_row', "
        "'delete_row', 'create_note', 'revise_note', 'review_issue', "
        "'run_validation', 'mark_ready', 'return_to_draft')"
    )
}
_VERSION_REVIEW_EVENT_CHECKS = {
    "ck_version_review_events_revision": (
        "to_review_revision = (from_review_revision + 1)"
    ),
    "ck_version_review_events_reason": "CHAR_LENGTH(TRIM(reason)) > 0",
    "ck_version_review_events_transition": (
        "((operation_kind = 'mark_ready' "
        "AND from_status = 'draft' AND to_status = 'ready_for_publish' "
        "AND selected_validation_run_id IS NOT NULL "
        "AND confirmation_digest IS NOT NULL "
        "AND confirmation_json IS NOT NULL "
        "AND JSON_TYPE(confirmation_json) = 'OBJECT' "
        "AND JSON_LENGTH(confirmation_json) = 7 "
        "AND JSON_CONTAINS_PATH(confirmation_json, 'all', "
        "'$.validation_run_id', '$.validation_data_digest', "
        "'$.ruleset_version', '$.confirmed_report_date', "
        "'$.confirmed_report_type', '$.confirmed_row_count', "
        "'$.confirmed_totals') = 1) OR "
        "(operation_kind = 'return_to_draft' "
        "AND from_status = 'ready_for_publish' AND to_status = 'draft' "
        "AND selected_validation_run_id IS NULL "
        "AND confirmation_digest IS NULL AND confirmation_json IS NULL))"
    ),
}
_REVIEW_RESULT_CHECKS = {
    "ck_review_operation_results_kind": "result_kind IN ('applied', 'cancelled')",
    "ck_review_operation_results_status": (
        "result_status IS NULL OR result_status IN ('draft', 'ready_for_publish')"
    ),
    "ck_review_operation_results_scope": (
        "((result_kind = 'cancelled' "
        "AND result_import_batch_id IS NULL "
        "AND result_dataset_id IS NULL AND result_version_id IS NULL "
        "AND result_status IS NULL AND result_data_revision IS NULL "
        "AND result_review_revision IS NULL) OR "
        "(result_kind = 'applied' AND "
        "((operation_kind IN ('create_note', 'revise_note') AND "
        "((result_import_batch_id IS NOT NULL "
        "AND result_dataset_id IS NULL AND result_version_id IS NULL "
        "AND result_status IS NULL AND result_data_revision IS NULL "
        "AND result_review_revision IS NULL) OR "
        "(result_import_batch_id IS NULL "
        "AND result_dataset_id IS NOT NULL "
        "AND result_version_id IS NOT NULL "
        "AND result_status IS NOT NULL "
        "AND result_data_revision IS NOT NULL "
        "AND result_review_revision IS NOT NULL))) OR "
        "(operation_kind NOT IN ('create_note', 'revise_note') "
        "AND result_import_batch_id IS NULL "
        "AND result_dataset_id IS NOT NULL "
        "AND result_version_id IS NOT NULL "
        "AND result_status IS NOT NULL "
        "AND result_data_revision IS NOT NULL "
        "AND result_review_revision IS NOT NULL))))"
    ),
    "ck_review_operation_results_semantics": (
        "((result_kind = 'cancelled' "
        "AND affected_row_id IS NULL AND data_change_event_id IS NULL "
        "AND issue_review_event_id IS NULL AND validation_run_id IS NULL "
        "AND version_review_event_id IS NULL AND note_id IS NULL) OR "
        "(result_kind = 'applied' AND "
        "((operation_kind IN ("
        "'set_field', 'restore_previous_field', 'restore_parent_field', "
        "'restore_source_field', 'add_row', 'exclude_row', "
        "'restore_row', 'delete_row') "
        "AND affected_row_id IS NOT NULL AND data_change_event_id IS NOT NULL "
        "AND issue_review_event_id IS NULL AND validation_run_id IS NULL "
        "AND version_review_event_id IS NULL AND note_id IS NULL) OR "
        "(operation_kind IN ('create_note', 'revise_note') "
        "AND affected_row_id IS NULL AND data_change_event_id IS NULL "
        "AND issue_review_event_id IS NULL AND validation_run_id IS NULL "
        "AND version_review_event_id IS NULL AND note_id IS NOT NULL) OR "
        "(operation_kind = 'review_issue' "
        "AND affected_row_id IS NULL AND data_change_event_id IS NULL "
        "AND issue_review_event_id IS NOT NULL "
        "AND validation_run_id IS NULL "
        "AND version_review_event_id IS NULL AND note_id IS NULL) OR "
        "(operation_kind = 'run_validation' "
        "AND affected_row_id IS NULL AND data_change_event_id IS NULL "
        "AND issue_review_event_id IS NULL "
        "AND validation_run_id IS NOT NULL "
        "AND version_review_event_id IS NULL AND note_id IS NULL) OR "
        "(operation_kind IN ('mark_ready', 'return_to_draft') "
        "AND affected_row_id IS NULL AND data_change_event_id IS NULL "
        "AND issue_review_event_id IS NULL AND validation_run_id IS NULL "
        "AND version_review_event_id IS NOT NULL "
        "AND note_id IS NULL))))"
    ),
}
_PUBLICATION_RESULT_CHECKS = {
    "ck_publication_command_results_kind": (
        "result_kind IN "
        "('published', 'replaced', 'rolled_back', 'withdrawn', "
        "'moved', 'move_reversed', 'cancelled')"
    ),
    "ck_publication_command_results_semantics": (
        "((operation_kind = 'publish' "
        "AND result_kind IN ('published', 'cancelled')) "
        "OR (operation_kind = 'replace' "
        "AND result_kind IN ('replaced', 'cancelled')) "
        "OR (operation_kind = 'rollback' "
        "AND result_kind IN ('rolled_back', 'cancelled')) "
        "OR (operation_kind = 'withdraw' "
        "AND result_kind IN ('withdrawn', 'cancelled')) "
        "OR (operation_kind = 'move' AND result_kind IN ('moved', 'cancelled')) "
        "OR (operation_kind = 'reverse_move' "
        "AND result_kind IN ('move_reversed', 'cancelled')))"
    ),
    "ck_publication_command_results_lineage": (
        "((result_kind = 'cancelled' "
        "AND result_dataset_id IS NULL AND result_version_id IS NULL "
        "AND result_status IS NULL AND result_data_revision IS NULL "
        "AND result_review_revision IS NULL AND validation_run_id IS NULL "
        "AND publication_event_id IS NULL) OR "
        "(result_kind <> 'cancelled' "
        "AND result_dataset_id IS NOT NULL AND result_version_id IS NOT NULL "
        "AND result_status IS NOT NULL AND result_data_revision IS NOT NULL "
        "AND result_review_revision IS NOT NULL "
        "AND publication_event_id IS NOT NULL "
        "AND ((result_kind IN ('published', 'replaced', 'moved') "
        "AND validation_run_id IS NOT NULL) OR "
        "(result_kind NOT IN ('published', 'replaced', 'moved') "
        "AND validation_run_id IS NULL))))"
    ),
    "ck_publication_command_results_move_lineage": (
        "((operation_kind = 'move' AND result_kind = 'moved' "
        "AND move_revision_operation_token IS NOT NULL "
        "AND reversed_move_command_id IS NULL) OR "
        "(operation_kind = 'reverse_move' "
        "AND result_kind = 'move_reversed' "
        "AND move_revision_operation_token IS NULL "
        "AND reversed_move_command_id IS NOT NULL "
        "AND reversed_move_command_id <> command_id) OR "
        "(result_kind = 'cancelled' "
        "AND move_revision_operation_token IS NULL "
        "AND reversed_move_command_id IS NULL) OR "
        "(operation_kind NOT IN ('move', 'reverse_move') "
        "AND move_revision_operation_token IS NULL "
        "AND reversed_move_command_id IS NULL))"
    ),
}
_LEGACY_NOTE_CHECKS = {
    "ck_notes_positive_revision": "revision_number > 0",
    "ck_notes_revision_chain": (
        "((revision_number = 1 AND supersedes_note_id IS NULL) OR "
        "(revision_number > 1 AND supersedes_note_id IS NOT NULL))"
    ),
    "ck_notes_visibility": "visibility IN ('internal', 'viewer_visible')",
    "ck_notes_target": _NOTE_THREAD_CHECKS["ck_note_threads_target"],
}
_FINAL_NOTE_CHECKS = {
    "ck_notes_positive_revision": "revision_number > 0",
    "ck_notes_revision_chain": (
        "((revision_number = 1 AND supersedes_note_id IS NULL "
        "AND supersedes_revision_number IS NULL) OR "
        "(revision_number > 1 AND supersedes_note_id IS NOT NULL "
        "AND supersedes_revision_number = (revision_number - 1)))"
    ),
    "ck_notes_visibility": "visibility IN ('internal', 'viewer_visible')",
    "ck_notes_body_nonempty": "CHAR_LENGTH(TRIM(body)) > 0",
}


def _index(
    non_unique: int,
    columns: tuple[str, ...],
) -> _IndexSignature:
    return (
        non_unique,
        "BTREE",
        "YES",
        tuple(
            (position, column, None, "A")
            for position, column in enumerate(columns, start=1)
        ),
    )


_NOTE_THREAD_INDEXES = {
    "PRIMARY": _index(0, ("note_key",)),
    "fk_note_threads_import_batch": _index(1, ("import_batch_id",)),
    "ix_note_threads_target_version_row": _index(
        1, ("version_id", "row_id", "note_key")
    ),
}
_REVIEW_TOKEN_INDEXES = {
    "PRIMARY": _index(0, ("operation_token",)),
    "uq_review_operation_tokens_identity": _index(
        0,
        (
            "operation_token",
            "operation_kind",
            "operation_digest",
            "actor_user_id",
        ),
    ),
    "fk_review_operation_tokens_actor": _index(1, ("actor_user_id",)),
}
_VERSION_REVIEW_EVENT_INDEXES = {
    "PRIMARY": _index(0, ("id",)),
    "uq_version_review_events_token": _index(0, ("operation_token",)),
    "uq_version_review_events_result_identity": _index(
        0,
        (
            "operation_token",
            "operation_kind",
            "operation_digest",
            "actor_user_id",
            "dataset_id",
            "version_id",
            "id",
        ),
    ),
    "fk_version_review_events_version": _index(1, ("dataset_id", "version_id")),
    "fk_version_review_events_validation": _index(
        1, ("version_id", "selected_validation_run_id")
    ),
    "ix_version_review_events_version_revision": _index(
        1, ("version_id", "to_review_revision", "id")
    ),
}
_REVIEW_RESULT_INDEXES = {
    "PRIMARY": _index(0, ("operation_token",)),
    "fk_review_operation_results_import_batch": _index(1, ("result_import_batch_id",)),
    "fk_review_operation_results_version": _index(
        1, ("result_dataset_id", "result_version_id")
    ),
    "fk_review_operation_results_row": _index(
        1, ("result_version_id", "affected_row_id")
    ),
    "fk_review_operation_results_change": _index(
        1, ("result_version_id", "data_change_event_id")
    ),
    "fk_review_operation_results_issue_review": _index(
        1, ("result_version_id", "issue_review_event_id")
    ),
    "fk_review_operation_results_validation": _index(
        1, ("result_version_id", "validation_run_id")
    ),
    "fk_review_operation_results_version_review": _index(
        1,
        (
            "operation_token",
            "operation_kind",
            "operation_digest",
            "actor_user_id",
            "result_dataset_id",
            "result_version_id",
            "version_review_event_id",
        ),
    ),
    "fk_review_operation_results_note": _index(1, ("note_id",)),
}
_PUBLICATION_RESULT_INDEXES = {
    "PRIMARY": _index(0, ("command_id",)),
    "uq_publication_command_results_token": _index(0, ("operation_token",)),
    "fk_publication_command_results_identity": _index(
        1,
        (
            "command_id",
            "operation_token",
            "operation_kind",
            "operation_digest",
            "actor_user_id",
        ),
    ),
    "fk_publication_command_results_version": _index(
        1, ("result_dataset_id", "result_version_id")
    ),
    "fk_publication_command_results_validation": _index(
        1, ("result_version_id", "validation_run_id")
    ),
    "fk_publication_command_results_event": _index(
        1, ("command_id", "publication_event_id")
    ),
    "fk_publication_command_results_move_revision": _index(
        1,
        (
            "move_revision_operation_token",
            "result_dataset_id",
            "result_version_id",
        ),
    ),
    "fk_publication_command_results_reversed_move": _index(
        1, ("reversed_move_command_id",)
    ),
}
_LEGACY_NOTE_INDEXES = {
    "PRIMARY": _index(0, ("id",)),
    "uq_notes_key_revision": _index(0, ("note_key", "revision_number")),
    "uq_notes_key_id": _index(0, ("note_key", "id")),
    "uq_notes_supersedes_note": _index(0, ("supersedes_note_id",)),
    "fk_notes_previous_revision": _index(1, ("note_key", "supersedes_note_id")),
    "fk_notes_import_batch": _index(1, ("import_batch_id",)),
    "fk_notes_version": _index(1, ("version_id",)),
    "fk_notes_version_row": _index(1, ("version_id", "row_id")),
    "fk_notes_author": _index(1, ("author_user_id",)),
    "ix_notes_target_version_row": _index(1, ("version_id", "row_id", "id")),
}
_ROUNDTRIP_LEGACY_NOTE_INDEXES = {
    name: signature
    for name, signature in _LEGACY_NOTE_INDEXES.items()
    if name not in {"fk_notes_version", "fk_notes_version_row"}
}
_FINAL_NOTE_INDEXES = {
    "PRIMARY": _index(0, ("id",)),
    "uq_notes_key_revision": _index(0, ("note_key", "revision_number")),
    "uq_notes_key_id": _index(0, ("note_key", "id")),
    "uq_notes_supersedes_note": _index(0, ("supersedes_note_id",)),
    "uq_notes_key_revision_id": _index(0, ("note_key", "revision_number", "id")),
    "fk_notes_previous_revision": _index(
        1, ("note_key", "supersedes_revision_number", "supersedes_note_id")
    ),
    "fk_notes_author": _index(1, ("author_user_id",)),
}

_TABLE_SIGNATURES = {
    "note_threads": (
        _NOTE_THREAD_COLUMNS,
        _NOTE_THREAD_KEYS,
        _NOTE_THREAD_CHECKS,
        _NOTE_THREAD_INDEXES,
    ),
    "review_operation_tokens": (
        _REVIEW_TOKEN_COLUMNS,
        _REVIEW_TOKEN_KEYS,
        _REVIEW_TOKEN_CHECKS,
        _REVIEW_TOKEN_INDEXES,
    ),
    "version_review_events": (
        _VERSION_REVIEW_EVENT_COLUMNS,
        _VERSION_REVIEW_EVENT_KEYS,
        _VERSION_REVIEW_EVENT_CHECKS,
        _VERSION_REVIEW_EVENT_INDEXES,
    ),
    "review_operation_results": (
        _REVIEW_RESULT_COLUMNS,
        _REVIEW_RESULT_KEYS,
        _REVIEW_RESULT_CHECKS,
        _REVIEW_RESULT_INDEXES,
    ),
    "publication_command_results": (
        _PUBLICATION_RESULT_COLUMNS,
        _PUBLICATION_RESULT_KEYS,
        _PUBLICATION_RESULT_CHECKS,
        _PUBLICATION_RESULT_INDEXES,
    ),
}


def _id_type() -> mysql.BIGINT:
    return mysql.BIGINT(unsigned=True)


def _code_type(length: int) -> mysql.VARCHAR:
    return mysql.VARCHAR(length, charset="ascii", collation="ascii_bin")


def _timestamp_type() -> mysql.DATETIME:
    return mysql.DATETIME(fsp=6)


def _incompatible(detail: str) -> RuntimeError:
    return RuntimeError(
        "0017 found an incompatible pre-existing review/note contract "
        f"({detail}); repair it explicitly before retrying"
    )


def _optional_string(value: object, *, casefold: bool = False) -> str | None:
    if value is None:
        return None
    result = str(value)
    return result.casefold() if casefold else result


def _as_int(value: object) -> int:
    return int(str(value))


_CHECK_TOKEN = re.compile(
    r"'(?:''|[^'])*'|<>|<=|>=|=|<|>|[a-z_][a-z0-9_]*|\d+|[(),+\-]",
    re.IGNORECASE,
)


def _check_tokens(clause: str) -> tuple[str, ...]:
    normalized = clause.casefold().replace("`", "").replace("\\'", "'")
    normalized = re.sub(r"_[a-z0-9]+(?=')", "", normalized)
    tokens = tuple(match.group(0) for match in _CHECK_TOKEN.finditer(normalized))
    residue = _CHECK_TOKEN.sub("", normalized)
    if not residue.isspace() and residue:
        raise _incompatible("unrecognized CHECK expression syntax")
    return tokens


def _check_ast(clause: str) -> tuple[object, ...]:
    tokens = _check_tokens(clause)
    position = 0

    def parse_or() -> tuple[object, ...]:
        nonlocal position
        nodes = [parse_and()]
        while position < len(tokens) and tokens[position] == "or":
            position += 1
            nodes.append(parse_and())
        flattened: list[tuple[object, ...]] = []
        for node in nodes:
            if node[0] == "or":
                flattened.extend(node[1:])  # type: ignore[arg-type]
            else:
                flattened.append(node)
        return (
            flattened[0]
            if len(flattened) == 1
            else ("or", *sorted(flattened, key=repr))
        )

    def parse_and() -> tuple[object, ...]:
        nonlocal position
        nodes = [parse_not()]
        while position < len(tokens) and tokens[position] == "and":
            position += 1
            nodes.append(parse_not())
        flattened: list[tuple[object, ...]] = []
        for node in nodes:
            if node[0] == "and":
                flattened.extend(node[1:])  # type: ignore[arg-type]
            else:
                flattened.append(node)
        return (
            flattened[0]
            if len(flattened) == 1
            else ("and", *sorted(flattened, key=repr))
        )

    def parse_not() -> tuple[object, ...]:
        nonlocal position
        if position < len(tokens) and tokens[position] == "not":
            position += 1
            return ("not", parse_not())
        return parse_primary()

    def parse_primary() -> tuple[object, ...]:
        nonlocal position
        if position < len(tokens) and tokens[position] == "(":
            position += 1
            node = parse_or()
            if position >= len(tokens) or tokens[position] != ")":
                raise _incompatible("unbalanced CHECK expression")
            position += 1
            return node

        atom: list[str] = []
        nested = 0
        while position < len(tokens):
            token = tokens[position]
            if token == "(":
                nested += 1
            elif token == ")":
                if nested == 0:
                    break
                nested -= 1
            elif nested == 0 and token in {"and", "or"}:
                break
            atom.append(token)
            position += 1
        if not atom or nested != 0:
            raise _incompatible("malformed CHECK expression")
        return ("atom", "".join(atom))

    result = parse_or()
    if position != len(tokens):
        raise _incompatible("trailing CHECK expression tokens")
    return result


def _column_signature(table_name: str) -> tuple[_ColumnSignature, ...]:
    rows = (
        op.get_bind()
        .execute(
            sa.text(
                """
                SELECT ordinal_position, column_name, column_type,
                       is_nullable, column_default, character_set_name,
                       collation_name, extra, generation_expression
                FROM information_schema.columns
                WHERE table_schema = DATABASE()
                  AND table_name = :table_name
                ORDER BY ordinal_position
                """
            ),
            {"table_name": table_name},
        )
        .tuples()
        .all()
    )
    return tuple(
        (
            int(row[0]),
            str(row[1]),
            str(row[2]).casefold(),
            str(row[3]).upper(),
            _optional_string(row[4], casefold=True),
            _optional_string(row[5], casefold=True),
            _optional_string(row[6], casefold=True),
            str(row[7]).casefold(),
            str(row[8]),
        )
        for row in rows
    )


def _key_signature(table_name: str) -> dict[str, _KeySignature]:
    rows = (
        op.get_bind()
        .execute(
            sa.text(
                """
                SELECT constraints.constraint_name,
                       constraints.constraint_type,
                       constraints.enforced,
                       key_columns.ordinal_position,
                       key_columns.column_name,
                       CASE
                           WHEN key_columns.referenced_table_schema = DATABASE()
                           THEN '<current>'
                           ELSE key_columns.referenced_table_schema
                       END AS referenced_table_schema,
                       key_columns.referenced_table_name,
                       key_columns.referenced_column_name,
                       key_columns.position_in_unique_constraint,
                       references_.update_rule,
                       references_.delete_rule
                FROM information_schema.table_constraints AS constraints
                JOIN information_schema.key_column_usage AS key_columns
                  ON key_columns.constraint_schema = constraints.constraint_schema
                 AND key_columns.table_name = constraints.table_name
                 AND key_columns.constraint_name = constraints.constraint_name
                LEFT JOIN information_schema.referential_constraints AS references_
                  ON references_.constraint_schema = constraints.constraint_schema
                 AND references_.table_name = constraints.table_name
                 AND references_.constraint_name = constraints.constraint_name
                WHERE constraints.constraint_schema = DATABASE()
                  AND constraints.table_name = :table_name
                  AND constraints.constraint_type IN (
                      'PRIMARY KEY', 'UNIQUE', 'FOREIGN KEY'
                  )
                ORDER BY constraints.constraint_name, key_columns.ordinal_position
                """
            ),
            {"table_name": table_name},
        )
        .tuples()
        .all()
    )
    grouped: dict[str, list[tuple[object, ...]]] = {}
    for row in rows:
        grouped.setdefault(str(row[0]), []).append(tuple(row[1:]))

    result: dict[str, _KeySignature] = {}
    for name, constraint_rows in grouped.items():
        first = constraint_rows[0]
        result[name] = (
            str(first[0]).upper(),
            str(first[1]).upper(),
            tuple(
                (
                    _as_int(row[2]),
                    str(row[3]),
                    _optional_string(row[4]),
                    _optional_string(row[5]),
                    _optional_string(row[6]),
                    None if row[7] is None else _as_int(row[7]),
                )
                for row in constraint_rows
            ),
            None if first[8] is None else str(first[8]).upper(),
            None if first[9] is None else str(first[9]).upper(),
        )
    return result


def _check_signature(table_name: str) -> dict[str, tuple[object, ...]]:
    rows = (
        op.get_bind()
        .execute(
            sa.text(
                """
                SELECT constraints.constraint_name,
                       constraints.constraint_type,
                       constraints.enforced,
                       checks.check_clause
                FROM information_schema.table_constraints AS constraints
                JOIN information_schema.check_constraints AS checks
                  ON checks.constraint_schema = constraints.constraint_schema
                 AND checks.constraint_name = constraints.constraint_name
                WHERE constraints.constraint_schema = DATABASE()
                  AND constraints.table_name = :table_name
                  AND constraints.constraint_type = 'CHECK'
                ORDER BY constraints.constraint_name
                """
            ),
            {"table_name": table_name},
        )
        .tuples()
        .all()
    )
    result: dict[str, tuple[object, ...]] = {}
    for name, constraint_type, enforced, check_clause in rows:
        if str(constraint_type).upper() != "CHECK" or str(enforced).upper() != "YES":
            raise _incompatible(f"{table_name}.{name} is not an enforced CHECK")
        result[str(name)] = _check_ast(str(check_clause))
    return result


def _index_signature(table_name: str) -> dict[str, _IndexSignature]:
    rows = (
        op.get_bind()
        .execute(
            sa.text(
                """
                SELECT index_name, non_unique, index_type, is_visible,
                       seq_in_index, column_name, sub_part, collation,
                       expression
                FROM information_schema.statistics
                WHERE table_schema = DATABASE()
                  AND table_name = :table_name
                ORDER BY index_name, seq_in_index
                """
            ),
            {"table_name": table_name},
        )
        .tuples()
        .all()
    )
    grouped: dict[str, list[tuple[object, ...]]] = {}
    for row in rows:
        grouped.setdefault(str(row[0]), []).append(tuple(row[1:]))

    result: dict[str, _IndexSignature] = {}
    for name, index_rows in grouped.items():
        first = index_rows[0]
        if any(row[7] is not None for row in index_rows):
            raise _incompatible(f"{table_name}.{name} uses an expression index")
        result[name] = (
            _as_int(first[0]),
            str(first[1]).upper(),
            str(first[2]).upper(),
            tuple(
                (
                    _as_int(row[3]),
                    _optional_string(row[4]),
                    None if row[5] is None else _as_int(row[5]),
                    None if row[6] is None else str(row[6]).upper(),
                )
                for row in index_rows
            ),
        )
    return result


def _assert_table_metadata(table_name: str) -> None:
    metadata = (
        op.get_bind()
        .execute(
            sa.text(
                """
                SELECT table_type, engine, table_collation
                FROM information_schema.tables
                WHERE table_schema = DATABASE()
                  AND table_name = :table_name
                """
            ),
            {"table_name": table_name},
        )
        .tuples()
        .one_or_none()
    )
    if metadata is None or tuple(str(value).upper() for value in metadata) != (
        "BASE TABLE",
        "INNODB",
        "UTF8MB4_0900_AI_CI",
    ):
        raise _incompatible(f"{table_name} table metadata")


def _assert_complete_table_signature(table_name: str) -> None:
    _assert_table_metadata(table_name)
    expected_columns, expected_keys, expected_checks, expected_indexes = (
        _TABLE_SIGNATURES[table_name]
    )
    if _column_signature(table_name) != expected_columns:
        raise _incompatible(f"{table_name} column signature")
    if _key_signature(table_name) != expected_keys:
        raise _incompatible(f"{table_name} key signature")
    if _check_signature(table_name) != {
        name: _check_ast(clause) for name, clause in expected_checks.items()
    }:
        raise _incompatible(f"{table_name} CHECK signature")
    if _index_signature(table_name) != expected_indexes:
        raise _incompatible(f"{table_name} index signature")


def _assert_legacy_notes_signature() -> None:
    _assert_table_metadata("notes")
    columns = _column_signature("notes")
    if columns not in {
        _LEGACY_NOTE_COLUMNS,
        _ROUNDTRIP_LEGACY_NOTE_COLUMNS,
    }:
        raise _incompatible("legacy notes column signature")
    if _key_signature("notes") != _LEGACY_NOTE_KEYS:
        raise _incompatible("legacy notes key signature")
    if _check_signature("notes") != {
        name: _check_ast(clause) for name, clause in _LEGACY_NOTE_CHECKS.items()
    }:
        raise _incompatible("legacy notes CHECK signature")
    expected_indexes = (
        _ROUNDTRIP_LEGACY_NOTE_INDEXES
        if columns == _ROUNDTRIP_LEGACY_NOTE_COLUMNS
        else _LEGACY_NOTE_INDEXES
    )
    if _index_signature("notes") != expected_indexes:
        raise _incompatible("legacy notes index signature")


def _assert_final_notes_signature() -> None:
    _assert_table_metadata("notes")
    if _column_signature("notes") != _FINAL_NOTE_COLUMNS:
        raise _incompatible("final notes column signature")
    if _key_signature("notes") != _FINAL_NOTE_KEYS:
        raise _incompatible("final notes key signature")
    if _check_signature("notes") != {
        name: _check_ast(clause) for name, clause in _FINAL_NOTE_CHECKS.items()
    }:
        raise _incompatible("final notes CHECK signature")
    if _index_signature("notes") != _FINAL_NOTE_INDEXES:
        raise _incompatible("final notes index signature")


def _create_note_threads() -> None:
    op.create_table(
        "note_threads",
        sa.Column("note_key", sa.String(length=64), nullable=False),
        sa.Column("target_type", sa.String(length=24), nullable=False),
        sa.Column("import_batch_id", _id_type(), nullable=True),
        sa.Column("version_id", _id_type(), nullable=True),
        sa.Column("row_id", _id_type(), nullable=True),
        sa.Column("field_name", sa.String(length=128), nullable=True),
        sa.Column("created_at", _timestamp_type(), nullable=False),
        sa.PrimaryKeyConstraint("note_key", name="pk_note_threads"),
        sa.ForeignKeyConstraint(
            ["import_batch_id"],
            ["import_batches.id"],
            name="fk_note_threads_import_batch",
            ondelete="RESTRICT",
            onupdate="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["version_id"],
            ["dataset_versions.id"],
            name="fk_note_threads_version",
            ondelete="RESTRICT",
            onupdate="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["version_id", "row_id"],
            ["version_rows.version_id", "version_rows.id"],
            name="fk_note_threads_version_row",
            ondelete="RESTRICT",
            onupdate="RESTRICT",
        ),
        sa.CheckConstraint(
            _NOTE_THREAD_CHECKS["ck_note_threads_target"],
            name="ck_note_threads_target",
        ),
        sa.Index(
            "ix_note_threads_target_version_row",
            "version_id",
            "row_id",
            "note_key",
        ),
        **_TABLE_OPTIONS,
    )


def _create_publication_command_results() -> None:
    op.create_table(
        "publication_command_results",
        sa.Column("command_id", _id_type(), nullable=False),
        sa.Column("operation_token", mysql.BINARY(16), nullable=False),
        sa.Column("operation_kind", _code_type(32), nullable=False),
        sa.Column("operation_digest", mysql.BINARY(32), nullable=False),
        sa.Column("actor_user_id", _id_type(), nullable=False),
        sa.Column("result_kind", _code_type(32), nullable=False),
        sa.Column("result_dataset_id", _id_type(), nullable=True),
        sa.Column("result_version_id", _id_type(), nullable=True),
        sa.Column("result_status", _code_type(32), nullable=True),
        sa.Column("result_data_revision", _id_type(), nullable=True),
        sa.Column("result_review_revision", _id_type(), nullable=True),
        sa.Column("validation_run_id", _id_type(), nullable=True),
        sa.Column("publication_event_id", _id_type(), nullable=True),
        sa.Column("move_revision_operation_token", mysql.BINARY(16), nullable=True),
        sa.Column("reversed_move_command_id", _id_type(), nullable=True),
        sa.Column("redacted_result_payload", mysql.JSON(), nullable=False),
        sa.Column("completed_at", _timestamp_type(), nullable=False),
        sa.PrimaryKeyConstraint(
            "command_id",
            name="pk_publication_command_results",
        ),
        sa.UniqueConstraint(
            "operation_token",
            name="uq_publication_command_results_token",
        ),
        sa.ForeignKeyConstraint(
            [
                "command_id",
                "operation_token",
                "operation_kind",
                "operation_digest",
                "actor_user_id",
            ],
            [
                "publication_commands.id",
                "publication_commands.operation_token",
                "publication_commands.operation_kind",
                "publication_commands.operation_digest",
                "publication_commands.actor_user_id",
            ],
            name="fk_publication_command_results_identity",
            ondelete="RESTRICT",
            onupdate="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["result_dataset_id", "result_version_id"],
            ["dataset_versions.dataset_id", "dataset_versions.id"],
            name="fk_publication_command_results_version",
            ondelete="RESTRICT",
            onupdate="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["result_version_id", "validation_run_id"],
            ["validation_runs.version_id", "validation_runs.id"],
            name="fk_publication_command_results_validation",
            ondelete="RESTRICT",
            onupdate="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["command_id", "publication_event_id"],
            ["publication_events.command_id", "publication_events.id"],
            name="fk_publication_command_results_event",
            ondelete="RESTRICT",
            onupdate="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            [
                "move_revision_operation_token",
                "result_dataset_id",
                "result_version_id",
            ],
            [
                "draft_operation_results.operation_token",
                "draft_operation_results.result_dataset_id",
                "draft_operation_results.result_version_id",
            ],
            name="fk_publication_command_results_move_revision",
            ondelete="RESTRICT",
            onupdate="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["reversed_move_command_id"],
            ["publication_commands.id"],
            name="fk_publication_command_results_reversed_move",
            ondelete="RESTRICT",
            onupdate="RESTRICT",
        ),
        *(
            sa.CheckConstraint(clause, name=name)
            for name, clause in _PUBLICATION_RESULT_CHECKS.items()
        ),
        **_TABLE_OPTIONS,
    )


def _create_review_operation_tokens() -> None:
    op.create_table(
        "review_operation_tokens",
        sa.Column("operation_token", mysql.BINARY(16), nullable=False),
        sa.Column("operation_kind", _code_type(32), nullable=False),
        sa.Column("operation_digest", mysql.BINARY(32), nullable=False),
        sa.Column("actor_user_id", _id_type(), nullable=False),
        sa.Column("registered_at", _timestamp_type(), nullable=False),
        sa.PrimaryKeyConstraint(
            "operation_token",
            name="pk_review_operation_tokens",
        ),
        sa.UniqueConstraint(
            "operation_token",
            "operation_kind",
            "operation_digest",
            "actor_user_id",
            name="uq_review_operation_tokens_identity",
        ),
        sa.ForeignKeyConstraint(
            ["actor_user_id"],
            ["users.id"],
            name="fk_review_operation_tokens_actor",
            ondelete="RESTRICT",
            onupdate="RESTRICT",
        ),
        sa.CheckConstraint(
            _REVIEW_TOKEN_CHECKS["ck_review_operation_tokens_kind"],
            name="ck_review_operation_tokens_kind",
        ),
        **_TABLE_OPTIONS,
    )


def _create_version_review_events() -> None:
    op.create_table(
        "version_review_events",
        sa.Column("id", _id_type(), autoincrement=True, nullable=False),
        sa.Column("operation_token", mysql.BINARY(16), nullable=False),
        sa.Column("operation_kind", _code_type(32), nullable=False),
        sa.Column("operation_digest", mysql.BINARY(32), nullable=False),
        sa.Column("actor_user_id", _id_type(), nullable=False),
        sa.Column("dataset_id", _id_type(), nullable=False),
        sa.Column("version_id", _id_type(), nullable=False),
        sa.Column("from_status", _code_type(32), nullable=False),
        sa.Column("to_status", _code_type(32), nullable=False),
        sa.Column("data_revision", _id_type(), nullable=False),
        sa.Column("from_review_revision", _id_type(), nullable=False),
        sa.Column("to_review_revision", _id_type(), nullable=False),
        sa.Column("selected_validation_run_id", _id_type(), nullable=True),
        sa.Column("confirmation_digest", mysql.BINARY(32), nullable=True),
        sa.Column("confirmation_json", mysql.JSON(), nullable=True),
        sa.Column("reason", mysql.LONGTEXT(), nullable=False),
        sa.Column("occurred_at", _timestamp_type(), nullable=False),
        sa.PrimaryKeyConstraint("id", name="pk_version_review_events"),
        sa.UniqueConstraint(
            "operation_token",
            name="uq_version_review_events_token",
        ),
        sa.UniqueConstraint(
            "operation_token",
            "operation_kind",
            "operation_digest",
            "actor_user_id",
            "dataset_id",
            "version_id",
            "id",
            name="uq_version_review_events_result_identity",
        ),
        sa.ForeignKeyConstraint(
            [
                "operation_token",
                "operation_kind",
                "operation_digest",
                "actor_user_id",
            ],
            [
                "review_operation_tokens.operation_token",
                "review_operation_tokens.operation_kind",
                "review_operation_tokens.operation_digest",
                "review_operation_tokens.actor_user_id",
            ],
            name="fk_version_review_events_token_identity",
            ondelete="RESTRICT",
            onupdate="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["dataset_id", "version_id"],
            ["dataset_versions.dataset_id", "dataset_versions.id"],
            name="fk_version_review_events_version",
            ondelete="RESTRICT",
            onupdate="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["version_id", "selected_validation_run_id"],
            ["validation_runs.version_id", "validation_runs.id"],
            name="fk_version_review_events_validation",
            ondelete="RESTRICT",
            onupdate="RESTRICT",
        ),
        *(
            sa.CheckConstraint(clause, name=name)
            for name, clause in _VERSION_REVIEW_EVENT_CHECKS.items()
        ),
        sa.Index(
            "ix_version_review_events_version_revision",
            "version_id",
            "to_review_revision",
            "id",
        ),
        **_TABLE_OPTIONS,
    )


def _create_review_operation_results() -> None:
    op.create_table(
        "review_operation_results",
        sa.Column("operation_token", mysql.BINARY(16), nullable=False),
        sa.Column("operation_kind", _code_type(32), nullable=False),
        sa.Column("operation_digest", mysql.BINARY(32), nullable=False),
        sa.Column("actor_user_id", _id_type(), nullable=False),
        sa.Column("result_kind", _code_type(32), nullable=False),
        sa.Column("result_import_batch_id", _id_type(), nullable=True),
        sa.Column("result_dataset_id", _id_type(), nullable=True),
        sa.Column("result_version_id", _id_type(), nullable=True),
        sa.Column("result_status", _code_type(32), nullable=True),
        sa.Column("result_data_revision", _id_type(), nullable=True),
        sa.Column("result_review_revision", _id_type(), nullable=True),
        sa.Column("affected_row_id", _id_type(), nullable=True),
        sa.Column("data_change_event_id", _id_type(), nullable=True),
        sa.Column("issue_review_event_id", _id_type(), nullable=True),
        sa.Column("validation_run_id", _id_type(), nullable=True),
        sa.Column("version_review_event_id", _id_type(), nullable=True),
        sa.Column("note_id", _id_type(), nullable=True),
        sa.Column("completed_at", _timestamp_type(), nullable=False),
        sa.PrimaryKeyConstraint(
            "operation_token",
            name="pk_review_operation_results",
        ),
        sa.ForeignKeyConstraint(
            [
                "operation_token",
                "operation_kind",
                "operation_digest",
                "actor_user_id",
            ],
            [
                "review_operation_tokens.operation_token",
                "review_operation_tokens.operation_kind",
                "review_operation_tokens.operation_digest",
                "review_operation_tokens.actor_user_id",
            ],
            name="fk_review_operation_results_identity",
            ondelete="RESTRICT",
            onupdate="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["result_import_batch_id"],
            ["import_batches.id"],
            name="fk_review_operation_results_import_batch",
            ondelete="RESTRICT",
            onupdate="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["result_dataset_id", "result_version_id"],
            ["dataset_versions.dataset_id", "dataset_versions.id"],
            name="fk_review_operation_results_version",
            ondelete="RESTRICT",
            onupdate="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["result_version_id", "affected_row_id"],
            ["version_rows.version_id", "version_rows.id"],
            name="fk_review_operation_results_row",
            ondelete="RESTRICT",
            onupdate="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["result_version_id", "data_change_event_id"],
            ["data_change_events.version_id", "data_change_events.id"],
            name="fk_review_operation_results_change",
            ondelete="RESTRICT",
            onupdate="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["result_version_id", "issue_review_event_id"],
            ["issue_review_events.version_id", "issue_review_events.id"],
            name="fk_review_operation_results_issue_review",
            ondelete="RESTRICT",
            onupdate="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["result_version_id", "validation_run_id"],
            ["validation_runs.version_id", "validation_runs.id"],
            name="fk_review_operation_results_validation",
            ondelete="RESTRICT",
            onupdate="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            [
                "operation_token",
                "operation_kind",
                "operation_digest",
                "actor_user_id",
                "result_dataset_id",
                "result_version_id",
                "version_review_event_id",
            ],
            [
                "version_review_events.operation_token",
                "version_review_events.operation_kind",
                "version_review_events.operation_digest",
                "version_review_events.actor_user_id",
                "version_review_events.dataset_id",
                "version_review_events.version_id",
                "version_review_events.id",
            ],
            name="fk_review_operation_results_version_review",
            ondelete="RESTRICT",
            onupdate="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["note_id"],
            ["notes.id"],
            name="fk_review_operation_results_note",
            ondelete="RESTRICT",
            onupdate="RESTRICT",
        ),
        *(
            sa.CheckConstraint(clause, name=name)
            for name, clause in _REVIEW_RESULT_CHECKS.items()
        ),
        **_TABLE_OPTIONS,
    )


def _table_names() -> frozenset[str]:
    return frozenset(
        str(value)
        for value in op.get_bind().scalars(
            sa.text(
                """
                SELECT table_name
                FROM information_schema.tables
                WHERE table_schema = DATABASE()
                """
            )
        )
    )


def _assert_trigger_creation_policy() -> None:
    bind = op.get_bind()
    log_bin, trust_function_creators = bind.execute(
        sa.text("SELECT @@GLOBAL.log_bin, @@GLOBAL.log_bin_trust_function_creators")
    ).one()
    if int(log_bin) != 0 and int(trust_function_creators) != 1:
        raise RuntimeError(
            "0017 migration preflight requires "
            "log_bin_trust_function_creators=ON while binary logging is enabled; "
            "ask a MySQL administrator to configure the server and do not grant "
            "SUPER to the migration account"
        )
    trigger_privileges = bind.scalar(
        sa.text(
            """
            SELECT COUNT(*)
            FROM information_schema.schema_privileges
            WHERE table_schema = DATABASE()
              AND privilege_type = 'TRIGGER'
              AND grantee = CONCAT(
                  CHAR(39), SUBSTRING_INDEX(CURRENT_USER(), '@', 1),
                  CHAR(39), '@', CHAR(39),
                  SUBSTRING_INDEX(CURRENT_USER(), '@', -1), CHAR(39)
              )
            """
        )
    )
    if int(trigger_privileges or 0) == 0:
        raise RuntimeError(
            "0017 migration preflight requires the migration account to have "
            "TRIGGER on this database; grant only TRIGGER on the application "
            "database and do not grant SUPER"
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
            "0017 requires the registered migration-account write-guard bypass"
        )


def _immutable_trigger_statement(table_name: str) -> str:
    return f"""
        BEGIN
            IF NOT EXISTS (
                SELECT 1
                FROM terminal_write_guard_bypass_accounts
                WHERE account_identity = USER()
            ) THEN
                SIGNAL SQLSTATE '45000'
                    SET MESSAGE_TEXT = '{table_name} is immutable';
            END IF;
        END
    """


def _normalize_trigger_statement(statement: str) -> str:
    normalized = statement.casefold().replace("`", "").replace("\\'", "'")
    return re.sub(r"\s+", "", normalized)


def _trigger_name(table_name: str, operation: str) -> str:
    return f"trg_{table_name}_no_{operation.casefold()}"


def _expected_trigger_signatures() -> dict[
    str,
    tuple[str, str, str, str, str | None, str],
]:
    return {
        _trigger_name(table_name, operation): (
            table_name,
            operation,
            "BEFORE",
            "ROW",
            None,
            _normalize_trigger_statement(_immutable_trigger_statement(table_name)),
        )
        for table_name in {
            "notes",
            "note_threads",
            "publication_command_results",
            "review_operation_tokens",
            "review_operation_results",
            "version_review_events",
        }
        for operation in ("UPDATE", "DELETE")
    }


def _actual_trigger_signatures() -> dict[
    str,
    tuple[str, str, str, str, str | None, str],
]:
    rows = (
        op.get_bind()
        .execute(
            sa.text(
                """
                SELECT trigger_name, event_object_table, event_manipulation,
                       action_timing, action_orientation, action_condition,
                       action_statement
                FROM information_schema.triggers
                WHERE trigger_schema = DATABASE()
                  AND (
                      event_object_table IN (
                          'notes', 'note_threads',
                          'publication_command_results',
                          'review_operation_tokens', 'review_operation_results',
                          'version_review_events'
                      )
                      OR trigger_name IN (
                          'trg_notes_no_update', 'trg_notes_no_delete',
                          'trg_note_threads_no_update',
                          'trg_note_threads_no_delete',
                          'trg_publication_command_results_no_update',
                          'trg_publication_command_results_no_delete',
                          'trg_review_operation_tokens_no_update',
                          'trg_review_operation_tokens_no_delete',
                          'trg_review_operation_results_no_update',
                          'trg_review_operation_results_no_delete',
                          'trg_version_review_events_no_update',
                          'trg_version_review_events_no_delete'
                      )
                  )
                ORDER BY trigger_name
                """
            )
        )
        .tuples()
        .all()
    )
    return {
        str(row[0]): (
            str(row[1]),
            str(row[2]).upper(),
            str(row[3]).upper(),
            str(row[4]).upper(),
            _optional_string(row[5]),
            _normalize_trigger_statement(str(row[6])),
        )
        for row in rows
    }


def _assert_existing_trigger_signatures() -> None:
    expected = _expected_trigger_signatures()
    for name, signature in _actual_trigger_signatures().items():
        if name not in expected or expected[name] != signature:
            raise _incompatible(f"trigger {name}")


def _ensure_immutable_triggers() -> None:
    expected = _expected_trigger_signatures()
    actual = _actual_trigger_signatures()
    for name, signature in expected.items():
        if name in actual:
            if actual[name] != signature:
                raise _incompatible(f"trigger {name}")
            continue
        table_name, operation, _timing, _orientation, _condition, statement = signature
        del statement
        op.execute(
            sa.text(
                f"""
                CREATE TRIGGER {name}
                BEFORE {operation} ON {table_name}
                FOR EACH ROW
                {_immutable_trigger_statement(table_name)}
                """
            )
        )
    if _actual_trigger_signatures() != expected:
        raise _incompatible("immutable trigger set after repair")


def _note_thread_mismatch_count() -> int:
    return int(
        op.get_bind().scalar(
            sa.text(
                """
                SELECT COUNT(*)
                FROM (
                    SELECT source.note_key
                    FROM notes AS source
                    LEFT JOIN note_threads AS threads
                      ON threads.note_key = source.note_key
                    WHERE source.revision_number = 1
                      AND (
                          threads.note_key IS NULL
                          OR NOT (threads.target_type <=> source.target_type)
                          OR NOT (
                              threads.import_batch_id <=> source.import_batch_id
                          )
                          OR NOT (threads.version_id <=> source.version_id)
                          OR NOT (threads.row_id <=> source.row_id)
                          OR NOT (threads.field_name <=> source.field_name)
                          OR threads.created_at <> source.created_at
                      )
                    UNION ALL
                    SELECT threads.note_key
                    FROM note_threads AS threads
                    LEFT JOIN notes AS source
                      ON source.note_key = threads.note_key
                     AND source.revision_number = 1
                    WHERE source.id IS NULL
                ) AS mismatches
                """
            )
        )
        or 0
    )


def _note_thread_conflict_count() -> int:
    return int(
        op.get_bind().scalar(
            sa.text(
                """
                SELECT COUNT(*)
                FROM (
                    SELECT source.note_key
                    FROM notes AS source
                    INNER JOIN note_threads AS threads
                      ON threads.note_key = source.note_key
                    WHERE source.revision_number = 1
                      AND (
                          NOT (threads.target_type <=> source.target_type)
                          OR NOT (
                              threads.import_batch_id <=> source.import_batch_id
                          )
                          OR NOT (threads.version_id <=> source.version_id)
                          OR NOT (threads.row_id <=> source.row_id)
                          OR NOT (threads.field_name <=> source.field_name)
                          OR threads.created_at <> source.created_at
                      )
                    UNION ALL
                    SELECT threads.note_key
                    FROM note_threads AS threads
                    LEFT JOIN notes AS source
                      ON source.note_key = threads.note_key
                     AND source.revision_number = 1
                    WHERE source.id IS NULL
                ) AS conflicts
                """
            )
        )
        or 0
    )


def _synchronize_note_threads_from_legacy_notes() -> None:
    if _note_thread_conflict_count() != 0:
        raise _incompatible("note_threads conflict with legacy note roots")
    op.execute(
        sa.text(
            """
            INSERT INTO note_threads (
                note_key, target_type, import_batch_id, version_id,
                row_id, field_name, created_at
            )
            SELECT notes.note_key, notes.target_type, notes.import_batch_id,
                   notes.version_id, notes.row_id, notes.field_name,
                   notes.created_at
            FROM notes
            LEFT JOIN note_threads
              ON note_threads.note_key = notes.note_key
            WHERE notes.revision_number = 1
              AND note_threads.note_key IS NULL
            """
        )
    )
    if _note_thread_mismatch_count() != 0:
        raise _incompatible("note_threads failed legacy-note reconciliation")


def _assert_legacy_note_data() -> None:
    bind = op.get_bind()
    empty_bodies = bind.scalar(
        sa.text("SELECT COUNT(*) FROM notes WHERE CHAR_LENGTH(TRIM(body)) = 0")
    )
    if int(empty_bodies or 0) != 0:
        raise _incompatible("legacy notes contain an empty body")
    invalid_chains = bind.scalar(
        sa.text(
            """
            SELECT COUNT(*)
            FROM notes AS current_notes
            LEFT JOIN notes AS previous_notes
              ON previous_notes.note_key = current_notes.note_key
             AND previous_notes.id = current_notes.supersedes_note_id
            WHERE current_notes.revision_number > 1
              AND (
                  previous_notes.id IS NULL
                  OR previous_notes.revision_number + 1 <>
                     current_notes.revision_number
                  OR NOT (
                      previous_notes.target_type <=> current_notes.target_type
                  )
                  OR NOT (
                      previous_notes.import_batch_id <=>
                      current_notes.import_batch_id
                  )
                  OR NOT (
                      previous_notes.version_id <=> current_notes.version_id
                  )
                  OR NOT (previous_notes.row_id <=> current_notes.row_id)
                  OR NOT (
                      previous_notes.field_name <=> current_notes.field_name
                  )
              )
            """
        )
    )
    if int(invalid_chains or 0) != 0:
        raise _incompatible("legacy notes contain a discontinuous or retargeted chain")


def _signature_without_position(signature: _ColumnSignature) -> tuple[object, ...]:
    return tuple(signature[1:])


def _assert_allowed_notes_transition_state() -> None:
    columns = _column_signature("notes")
    actual_by_name = {
        signature[1]: _signature_without_position(signature) for signature in columns
    }
    expected_by_name = {
        signature[1]: _signature_without_position(signature)
        for signature in _FINAL_NOTE_COLUMNS
    }
    for signature in _LEGACY_NOTE_COLUMNS:
        expected_by_name.setdefault(
            signature[1], _signature_without_position(signature)
        )
    expected_names = _FINAL_NOTE_COLUMN_NAMES | {
        "target_type",
        "import_batch_id",
        "version_id",
        "row_id",
        "field_name",
    }
    if not actual_by_name.keys() >= _FINAL_NOTE_COLUMN_NAMES:
        raise _incompatible("notes transition is missing a final column")
    if not actual_by_name.keys() <= expected_names:
        raise _incompatible("notes transition has an unexpected column")
    for name, actual in actual_by_name.items():
        if name == "visibility":
            legacy_visibility = list(expected_by_name[name])
            legacy_visibility[3] = None
            if actual not in {expected_by_name[name], tuple(legacy_visibility)}:
                raise _incompatible("notes visibility column during transition")
        elif actual != expected_by_name[name]:
            raise _incompatible(f"notes transition column {name}")

    keys = _key_signature("notes")
    allowed_keys: dict[str, set[_KeySignature]] = {
        name: {signature} for name, signature in _LEGACY_NOTE_KEYS.items()
    }
    for name, key_signature in _FINAL_NOTE_KEYS.items():
        allowed_keys.setdefault(name, set()).add(key_signature)
    required_keys = {
        "PRIMARY",
        "uq_notes_key_revision",
        "uq_notes_key_id",
        "uq_notes_supersedes_note",
        "fk_notes_author",
    }
    if not required_keys <= keys.keys() or not keys.keys() <= allowed_keys.keys():
        raise _incompatible("notes transition key set")
    if any(signature not in allowed_keys[name] for name, signature in keys.items()):
        raise _incompatible("notes transition key definition")

    checks = _check_signature("notes")
    allowed_checks = {
        name: {_check_ast(clause)} for name, clause in _LEGACY_NOTE_CHECKS.items()
    }
    for name, clause in _FINAL_NOTE_CHECKS.items():
        allowed_checks.setdefault(name, set()).add(_check_ast(clause))
    if not {"ck_notes_positive_revision", "ck_notes_visibility"} <= checks.keys():
        raise _incompatible("notes transition required CHECK set")
    if not checks.keys() <= allowed_checks.keys():
        raise _incompatible("notes transition CHECK set")
    if any(signature not in allowed_checks[name] for name, signature in checks.items()):
        raise _incompatible("notes transition CHECK definition")

    indexes = _index_signature("notes")
    allowed_indexes: dict[str, set[_IndexSignature]] = {
        name: {signature} for name, signature in _LEGACY_NOTE_INDEXES.items()
    }
    for name, index_signature in _ROUNDTRIP_LEGACY_NOTE_INDEXES.items():
        allowed_indexes.setdefault(name, set()).add(index_signature)
    for name, index_signature in _FINAL_NOTE_INDEXES.items():
        allowed_indexes.setdefault(name, set()).add(index_signature)
    required_indexes = {
        "PRIMARY",
        "uq_notes_key_revision",
        "uq_notes_key_id",
        "uq_notes_supersedes_note",
        "fk_notes_author",
    }
    if (
        not required_indexes <= indexes.keys()
        or not indexes.keys() <= allowed_indexes.keys()
    ):
        raise _incompatible("notes transition index set")
    if any(
        signature not in allowed_indexes[name] for name, signature in indexes.items()
    ):
        raise _incompatible("notes transition index definition")


def _ensure_unique(name: str, columns: tuple[str, ...]) -> None:
    expected = _key("UNIQUE", columns)
    existing = _key_signature("notes").get(name)
    if existing is not None:
        if existing != expected:
            raise _incompatible(f"notes unique constraint {name}")
        return
    op.create_unique_constraint(name, "notes", list(columns))


def _ensure_foreign_key(
    name: str,
    columns: tuple[str, ...],
    referred_table: str,
    referred_columns: tuple[str, ...],
) -> None:
    expected = _key(
        "FOREIGN KEY",
        columns,
        referenced_table=referred_table,
        referenced_columns=referred_columns,
        update_rule="RESTRICT",
        delete_rule="RESTRICT",
    )
    existing = _key_signature("notes").get(name)
    if existing is not None:
        if existing != expected:
            raise _incompatible(f"notes foreign key {name}")
        return
    op.create_foreign_key(
        name,
        "notes",
        referred_table,
        list(columns),
        list(referred_columns),
        ondelete="RESTRICT",
        onupdate="RESTRICT",
    )


def _drop_foreign_key_if_exact(name: str, expected: _KeySignature) -> None:
    existing = _key_signature("notes").get(name)
    if existing is None:
        return
    if existing != expected:
        raise _incompatible(f"notes foreign key {name}")
    op.drop_constraint(name, "notes", type_="foreignkey")


def _ensure_check(name: str, clause: str) -> None:
    expected = _check_ast(clause)
    existing = _check_signature("notes").get(name)
    if existing is not None:
        if existing != expected:
            raise _incompatible(f"notes CHECK {name}")
        return
    op.create_check_constraint(name, "notes", clause)


def _drop_check_if_exact(name: str, clause: str) -> None:
    existing = _check_signature("notes").get(name)
    if existing is None:
        return
    if existing != _check_ast(clause):
        raise _incompatible(f"notes CHECK {name}")
    op.drop_constraint(name, "notes", type_="check")


def _drop_index_if_exact(name: str, expected: _IndexSignature) -> None:
    existing = _index_signature("notes").get(name)
    if existing is None:
        return
    if existing != expected:
        raise _incompatible(f"notes index {name}")
    op.drop_index(name, table_name="notes")


def _backfill_supersedes_revision_number() -> None:
    invalid_existing = op.get_bind().scalar(
        sa.text(
            """
            SELECT COUNT(*)
            FROM notes
            WHERE (revision_number = 1
                   AND supersedes_revision_number IS NOT NULL)
               OR (revision_number > 1
                   AND supersedes_revision_number IS NOT NULL
                   AND supersedes_revision_number <> revision_number - 1)
            """
        )
    )
    if int(invalid_existing or 0) != 0:
        raise _incompatible("notes supersedes revision values")
    op.execute(
        sa.text(
            """
            UPDATE notes AS current_notes
            INNER JOIN notes AS previous_notes
              ON previous_notes.note_key = current_notes.note_key
             AND previous_notes.id = current_notes.supersedes_note_id
            SET current_notes.supersedes_revision_number =
                previous_notes.revision_number
            WHERE current_notes.revision_number > 1
              AND current_notes.supersedes_revision_number IS NULL
            """
        )
    )
    incomplete = op.get_bind().scalar(
        sa.text(
            """
            SELECT COUNT(*)
            FROM notes
            WHERE (revision_number = 1
                   AND supersedes_revision_number IS NOT NULL)
               OR (revision_number > 1
                   AND supersedes_revision_number <> revision_number - 1)
               OR (revision_number > 1
                   AND supersedes_revision_number IS NULL)
            """
        )
    )
    if int(incomplete or 0) != 0:
        raise _incompatible("notes supersedes revision backfill")


def _reconcile_notes(tables: frozenset[str]) -> None:
    columns = _column_signature("notes")
    legacy = columns in {_LEGACY_NOTE_COLUMNS, _ROUNDTRIP_LEGACY_NOTE_COLUMNS}
    final = columns == _FINAL_NOTE_COLUMNS
    thread_exists = "note_threads" in tables

    if final:
        _assert_final_notes_signature()
        if not thread_exists:
            note_count = int(
                op.get_bind().scalar(sa.text("SELECT COUNT(*) FROM notes")) or 0
            )
            if note_count != 0:
                raise _incompatible(
                    "note_threads are missing after note targets were removed"
                )
            _create_note_threads()
            _assert_complete_table_signature("note_threads")
        return

    if legacy:
        _assert_legacy_notes_signature()
        _assert_legacy_note_data()
        if not thread_exists:
            _create_note_threads()
            _assert_complete_table_signature("note_threads")
        _synchronize_note_threads_from_legacy_notes()
        op.add_column(
            "notes",
            sa.Column(
                "supersedes_revision_number",
                _id_type(),
                nullable=True,
            ),
        )
    else:
        if not thread_exists:
            raise _incompatible("notes transition has no durable note_threads")
        _assert_allowed_notes_transition_state()

    _backfill_supersedes_revision_number()
    _assert_allowed_notes_transition_state()

    visibility = {signature[1]: signature for signature in _column_signature("notes")}[
        "visibility"
    ]
    if visibility[4] is None:
        op.alter_column(
            "notes",
            "visibility",
            existing_type=sa.String(length=24),
            server_default=sa.text("'internal'"),
            existing_nullable=False,
            nullable=False,
        )
    elif str(visibility[4]).casefold() != "internal":
        raise _incompatible("notes visibility default")

    _ensure_check(
        "ck_notes_body_nonempty",
        _FINAL_NOTE_CHECKS["ck_notes_body_nonempty"],
    )
    _ensure_unique(
        "uq_notes_key_revision_id",
        ("note_key", "revision_number", "id"),
    )

    previous_key = _key_signature("notes").get("fk_notes_previous_revision")
    legacy_previous_key = _LEGACY_NOTE_KEYS["fk_notes_previous_revision"]
    final_previous_key = _FINAL_NOTE_KEYS["fk_notes_previous_revision"]
    if previous_key == legacy_previous_key:
        op.drop_constraint(
            "fk_notes_previous_revision",
            "notes",
            type_="foreignkey",
        )
        _drop_index_if_exact(
            "fk_notes_previous_revision",
            _LEGACY_NOTE_INDEXES["fk_notes_previous_revision"],
        )
    elif previous_key not in {None, final_previous_key}:
        raise _incompatible("notes previous-revision foreign key")
    elif previous_key is None:
        existing_previous_index = _index_signature("notes").get(
            "fk_notes_previous_revision"
        )
        if (
            existing_previous_index
            == _LEGACY_NOTE_INDEXES["fk_notes_previous_revision"]
        ):
            _drop_index_if_exact(
                "fk_notes_previous_revision",
                _LEGACY_NOTE_INDEXES["fk_notes_previous_revision"],
            )
        elif existing_previous_index is not None:
            raise _incompatible("notes previous-revision index")

    _ensure_foreign_key(
        "fk_notes_previous_revision",
        ("note_key", "supersedes_revision_number", "supersedes_note_id"),
        "notes",
        ("note_key", "revision_number", "id"),
    )
    _ensure_foreign_key(
        "fk_notes_thread",
        ("note_key",),
        "note_threads",
        ("note_key",),
    )

    revision_check = _check_signature("notes").get("ck_notes_revision_chain")
    legacy_revision_check = _check_ast(_LEGACY_NOTE_CHECKS["ck_notes_revision_chain"])
    final_revision_check = _check_ast(_FINAL_NOTE_CHECKS["ck_notes_revision_chain"])
    if revision_check == legacy_revision_check:
        op.drop_constraint("ck_notes_revision_chain", "notes", type_="check")
        revision_check = None
    elif revision_check not in {None, final_revision_check}:
        raise _incompatible("notes revision-chain CHECK")
    if revision_check is None:
        op.create_check_constraint(
            "ck_notes_revision_chain",
            "notes",
            _FINAL_NOTE_CHECKS["ck_notes_revision_chain"],
        )

    for name in (
        "fk_notes_version_row",
        "fk_notes_version",
        "fk_notes_import_batch",
    ):
        _drop_foreign_key_if_exact(name, _LEGACY_NOTE_KEYS[name])
    _drop_check_if_exact("ck_notes_target", _LEGACY_NOTE_CHECKS["ck_notes_target"])
    _drop_index_if_exact(
        "ix_notes_target_version_row",
        _LEGACY_NOTE_INDEXES["ix_notes_target_version_row"],
    )

    target_columns = (
        "field_name",
        "row_id",
        "version_id",
        "import_batch_id",
        "target_type",
    )
    present_targets = {signature[1] for signature in _column_signature("notes")} & set(
        target_columns
    )
    if present_targets:
        if present_targets != set(target_columns):
            raise _incompatible("notes has a partially removed target column set")
        op.execute(
            sa.text(
                "ALTER TABLE notes "
                + ", ".join(f"DROP COLUMN {name}" for name in target_columns)
            )
        )

    _assert_final_notes_signature()


def _assert_no_history_rows(*, label: str, query: str) -> None:
    count = int(op.get_bind().scalar(sa.text(query)) or 0)
    if count != 0:
        raise _incompatible(f"{label} contain {count} row(s)")


def _assert_review_repair_has_provably_empty_history(
    existing_repaired: frozenset[str],
) -> None:
    review_tables = frozenset(
        {
            "review_operation_tokens",
            "version_review_events",
            "review_operation_results",
        }
    )
    if review_tables <= existing_repaired:
        return

    for table_name in sorted(review_tables & existing_repaired):
        _assert_no_history_rows(
            label=f"existing {table_name}",
            query=f"SELECT COUNT(*) FROM {table_name}",
        )
    _assert_no_history_rows(
        label="dataset versions with review-state evidence",
        query=(
            "SELECT COUNT(*) FROM dataset_versions "
            "WHERE status <> 'draft' "
            "OR data_revision <> 0 OR review_revision <> 0"
        ),
    )
    for table_name in (
        "data_change_events",
        "issue_review_events",
        "validation_runs",
        "notes",
    ):
        _assert_no_history_rows(
            label=f"{table_name} review-history evidence",
            query=f"SELECT COUNT(*) FROM {table_name}",
        )
    if "note_threads" in existing_repaired:
        _assert_no_history_rows(
            label="note_threads review-history evidence",
            query="SELECT COUNT(*) FROM note_threads",
        )


def _assert_publication_result_repair_has_provably_empty_history(
    existing_repaired: frozenset[str],
) -> None:
    if "publication_command_results" in existing_repaired:
        return
    for table_name in (
        "publication_commands",
        "publication_events",
        "publication_outbox",
    ):
        _assert_no_history_rows(
            label=f"{table_name} publication-history evidence",
            query=f"SELECT COUNT(*) FROM {table_name}",
        )


def _preflight() -> tuple[frozenset[str], frozenset[str]]:
    tables = _table_names()
    prerequisites = {
        "data_change_events",
        "dataset_versions",
        "draft_operation_results",
        "import_batches",
        "issue_review_events",
        "notes",
        "publication_commands",
        "publication_events",
        "publication_outbox",
        "terminal_write_guard_bypass_accounts",
        "users",
        "validation_runs",
        "version_rows",
    }
    missing_prerequisites = prerequisites - tables
    if missing_prerequisites:
        raise _incompatible(
            "missing prerequisite table(s): " + ", ".join(sorted(missing_prerequisites))
        )

    existing_repaired = tables & _REPAIRED_TABLES
    if (
        "review_operation_results" in existing_repaired
        and "review_operation_tokens" not in existing_repaired
    ):
        raise _incompatible("review results exist without their token ledger")
    if (
        "version_review_events" in existing_repaired
        and "review_operation_tokens" not in existing_repaired
    ):
        raise _incompatible("version review events exist without their token ledger")
    if (
        "review_operation_results" in existing_repaired
        and "version_review_events" not in existing_repaired
    ):
        raise _incompatible("review results exist without version review events")
    for table_name in existing_repaired:
        _assert_complete_table_signature(table_name)

    notes_columns = _column_signature("notes")
    if notes_columns in {_LEGACY_NOTE_COLUMNS, _ROUNDTRIP_LEGACY_NOTE_COLUMNS}:
        _assert_legacy_notes_signature()
        _assert_legacy_note_data()
    elif notes_columns == _FINAL_NOTE_COLUMNS:
        _assert_final_notes_signature()
    else:
        _assert_allowed_notes_transition_state()

    _assert_review_repair_has_provably_empty_history(existing_repaired)
    _assert_publication_result_repair_has_provably_empty_history(existing_repaired)
    _assert_existing_trigger_signatures()
    return tables, existing_repaired


def upgrade() -> None:
    if context.is_offline_mode():
        raise RuntimeError(
            "0017 requires an online migration connection so every repaired "
            "schema signature can be verified before the revision is recorded"
        )

    tables, existing_repaired = _preflight()
    _assert_trigger_creation_policy()
    _reconcile_notes(tables)

    if "publication_command_results" not in existing_repaired:
        _create_publication_command_results()
        _assert_complete_table_signature("publication_command_results")
    if "review_operation_tokens" not in existing_repaired:
        _create_review_operation_tokens()
        _assert_complete_table_signature("review_operation_tokens")
    if "version_review_events" not in existing_repaired:
        _create_version_review_events()
        _assert_complete_table_signature("version_review_events")
    if "review_operation_results" not in existing_repaired:
        _create_review_operation_results()
        _assert_complete_table_signature("review_operation_results")

    _assert_complete_table_signature("note_threads")
    _assert_complete_table_signature("publication_command_results")
    _assert_complete_table_signature("review_operation_tokens")
    _assert_complete_table_signature("version_review_events")
    _assert_complete_table_signature("review_operation_results")
    _ensure_immutable_triggers()


def downgrade() -> None:
    # The repaired contracts predate 0017 and are deliberately durable. Dropping
    # them would recreate the historical corruption this forward repair fixes.
    pass
