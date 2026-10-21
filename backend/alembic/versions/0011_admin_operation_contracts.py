"""Add immutable administrator-operation idempotency ledgers."""

from __future__ import annotations

import re
from typing import Any

import sqlalchemy as sa
from alembic import context, op
from sqlalchemy.dialects import mysql

revision = "0011"
down_revision = "0010"
branch_labels = None
depends_on = None

_TABLE_OPTIONS: dict[str, Any] = {
    "mysql_engine": "InnoDB",
    "mysql_charset": "utf8mb4",
    "mysql_collate": "utf8mb4_0900_ai_ci",
}
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
type _KeyConstraintSignature = tuple[
    str,
    str,
    str,
    int,
    str,
    str | None,
    str | None,
    str | None,
    int | None,
    str | None,
    str | None,
    str | None,
]
type _IndexSignature = tuple[
    str,
    int,
    int,
    str | None,
    int | None,
    str | None,
    str,
    str,
    str | None,
]

_TOKEN_COLUMNS: tuple[_ColumnSignature, ...] = (
    (1, "operation_token", "binary(16)", "NO", None, None, None, "", ""),
    (2, "operation_kind", "varchar(32)", "NO", None, "ascii", "ascii_bin", "", ""),
    (3, "operation_digest", "binary(32)", "NO", None, None, None, "", ""),
    (4, "actor_user_id", "bigint unsigned", "NO", None, None, None, "", ""),
    (
        5,
        "secret_verifier",
        "varchar(255)",
        "YES",
        None,
        "ascii",
        "ascii_bin",
        "",
        "",
    ),
    (6, "registered_at", "datetime(6)", "NO", None, None, None, "", ""),
)
_RESULT_COLUMNS: tuple[_ColumnSignature, ...] = (
    (1, "operation_token", "binary(16)", "NO", None, None, None, "", ""),
    (2, "operation_kind", "varchar(32)", "NO", None, "ascii", "ascii_bin", "", ""),
    (3, "operation_digest", "binary(32)", "NO", None, None, None, "", ""),
    (4, "actor_user_id", "bigint unsigned", "NO", None, None, None, "", ""),
    (
        5,
        "response_schema_version",
        "smallint unsigned",
        "NO",
        None,
        None,
        None,
        "",
        "",
    ),
    (
        6,
        "response_status_code",
        "smallint unsigned",
        "NO",
        None,
        None,
        None,
        "",
        "",
    ),
    (7, "response_payload", "json", "NO", None, None, None, "", ""),
    (8, "completed_at", "datetime(6)", "NO", None, None, None, "", ""),
)

_TOKEN_KEY_CONSTRAINTS: frozenset[_KeyConstraintSignature] = frozenset(
    {
        (
            "PRIMARY",
            "PRIMARY KEY",
            "YES",
            1,
            "operation_token",
            None,
            None,
            None,
            None,
            None,
            None,
            None,
        ),
        *(
            (
                "uq_admin_operation_tokens_identity",
                "UNIQUE",
                "YES",
                position,
                column,
                None,
                None,
                None,
                None,
                None,
                None,
                None,
            )
            for position, column in enumerate(
                (
                    "operation_token",
                    "operation_kind",
                    "operation_digest",
                    "actor_user_id",
                ),
                start=1,
            )
        ),
        (
            "fk_admin_operation_tokens_actor",
            "FOREIGN KEY",
            "YES",
            1,
            "actor_user_id",
            "<current>",
            "users",
            "id",
            1,
            "PRIMARY",
            "RESTRICT",
            "RESTRICT",
        ),
    }
)
_RESULT_KEY_CONSTRAINTS: frozenset[_KeyConstraintSignature] = frozenset(
    {
        (
            "PRIMARY",
            "PRIMARY KEY",
            "YES",
            1,
            "operation_token",
            None,
            None,
            None,
            None,
            None,
            None,
            None,
        ),
        *(
            (
                "fk_admin_operation_results_identity",
                "FOREIGN KEY",
                "YES",
                position,
                column,
                "<current>",
                "admin_operation_tokens",
                column,
                position,
                "uq_admin_operation_tokens_identity",
                "RESTRICT",
                "RESTRICT",
            )
            for position, column in enumerate(
                (
                    "operation_token",
                    "operation_kind",
                    "operation_digest",
                    "actor_user_id",
                ),
                start=1,
            )
        ),
    }
)

_TOKEN_CHECKS = {
    "ck_admin_operation_tokens_kind": (
        "(operation_kind in ('create_user','update_user','create_site_config_version'))"
    ),
    "ck_admin_operation_tokens_secret": (
        "(((operation_kind = 'create_user') and (secret_verifier is not null)) "
        "or (operation_kind = 'update_user') or "
        "((operation_kind = 'create_site_config_version') "
        "and (secret_verifier is null)))"
    ),
}
_RESULT_CHECKS = {
    "ck_admin_operation_results_schema_version": "(response_schema_version = 1)",
    "ck_admin_operation_results_status": (
        "(((operation_kind = 'update_user') and (response_status_code = 200)) "
        "or ((operation_kind in ("
        "'create_user','create_site_config_version')) "
        "and (response_status_code = 201)))"
    ),
}

_TOKEN_INDEXES: frozenset[_IndexSignature] = frozenset(
    {
        ("PRIMARY", 0, 1, "operation_token", None, "A", "BTREE", "YES", None),
        *(
            (
                "uq_admin_operation_tokens_identity",
                0,
                position,
                column,
                None,
                "A",
                "BTREE",
                "YES",
                None,
            )
            for position, column in enumerate(
                (
                    "operation_token",
                    "operation_kind",
                    "operation_digest",
                    "actor_user_id",
                ),
                start=1,
            )
        ),
        (
            "ix_admin_operation_tokens_actor_registered",
            1,
            1,
            "actor_user_id",
            None,
            "A",
            "BTREE",
            "YES",
            None,
        ),
        (
            "ix_admin_operation_tokens_actor_registered",
            1,
            2,
            "registered_at",
            None,
            "A",
            "BTREE",
            "YES",
            None,
        ),
    }
)
_RESULT_INDEXES: frozenset[_IndexSignature] = frozenset(
    {
        ("PRIMARY", 0, 1, "operation_token", None, "A", "BTREE", "YES", None),
        *(
            (
                "fk_admin_operation_results_identity",
                1,
                position,
                column,
                None,
                "A",
                "BTREE",
                "YES",
                None,
            )
            for position, column in enumerate(
                (
                    "operation_token",
                    "operation_kind",
                    "operation_digest",
                    "actor_user_id",
                ),
                start=1,
            )
        ),
        (
            "ix_admin_operation_results_actor_completed",
            1,
            1,
            "actor_user_id",
            None,
            "A",
            "BTREE",
            "YES",
            None,
        ),
        (
            "ix_admin_operation_results_actor_completed",
            1,
            2,
            "completed_at",
            None,
            "A",
            "BTREE",
            "YES",
            None,
        ),
    }
)

_TABLE_SIGNATURES = {
    "admin_operation_tokens": (
        _TOKEN_COLUMNS,
        _TOKEN_KEY_CONSTRAINTS,
        _TOKEN_CHECKS,
        _TOKEN_INDEXES,
    ),
    "admin_operation_results": (
        _RESULT_COLUMNS,
        _RESULT_KEY_CONSTRAINTS,
        _RESULT_CHECKS,
        _RESULT_INDEXES,
    ),
}


def _id_type() -> mysql.BIGINT:
    return mysql.BIGINT(unsigned=True)


def _code_type(length: int) -> mysql.VARCHAR:
    return mysql.VARCHAR(length, charset="ascii", collation="ascii_bin")


def _timestamp_type() -> mysql.DATETIME:
    return mysql.DATETIME(fsp=6)


def _assert_trigger_creation_policy() -> None:
    """Fail before MySQL's non-transactional DDL if triggers are unavailable."""

    if context.is_offline_mode():
        return
    bind = op.get_bind()
    log_bin, trust_function_creators = bind.execute(
        sa.text("SELECT @@GLOBAL.log_bin, @@GLOBAL.log_bin_trust_function_creators")
    ).one()
    if int(log_bin) != 0 and int(trust_function_creators) != 1:
        raise RuntimeError(
            "0011 migration preflight requires "
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
            "0011 migration preflight requires the migration account to have "
            "TRIGGER on this database; grant only TRIGGER on the application "
            "database and do not grant SUPER"
        )


def _create_token_table() -> None:
    op.create_table(
        "admin_operation_tokens",
        sa.Column("operation_token", mysql.BINARY(16), nullable=False),
        sa.Column("operation_kind", _code_type(32), nullable=False),
        sa.Column("operation_digest", mysql.BINARY(32), nullable=False),
        sa.Column("actor_user_id", _id_type(), nullable=False),
        sa.Column("secret_verifier", _code_type(255), nullable=True),
        sa.Column("registered_at", _timestamp_type(), nullable=False),
        sa.PrimaryKeyConstraint(
            "operation_token",
            name="pk_admin_operation_tokens",
        ),
        sa.UniqueConstraint(
            "operation_token",
            "operation_kind",
            "operation_digest",
            "actor_user_id",
            name="uq_admin_operation_tokens_identity",
        ),
        sa.ForeignKeyConstraint(
            ["actor_user_id"],
            ["users.id"],
            name="fk_admin_operation_tokens_actor",
            ondelete="RESTRICT",
            onupdate="RESTRICT",
        ),
        sa.CheckConstraint(
            "operation_kind IN ("
            "'create_user', 'update_user', 'create_site_config_version')",
            name="ck_admin_operation_tokens_kind",
        ),
        sa.CheckConstraint(
            "((operation_kind = 'create_user' "
            "AND secret_verifier IS NOT NULL) "
            "OR operation_kind = 'update_user' "
            "OR (operation_kind = 'create_site_config_version' "
            "AND secret_verifier IS NULL))",
            name="ck_admin_operation_tokens_secret",
        ),
        sa.Index(
            "ix_admin_operation_tokens_actor_registered",
            "actor_user_id",
            "registered_at",
        ),
        **_TABLE_OPTIONS,
    )


def _create_result_table() -> None:
    op.create_table(
        "admin_operation_results",
        sa.Column("operation_token", mysql.BINARY(16), nullable=False),
        sa.Column("operation_kind", _code_type(32), nullable=False),
        sa.Column("operation_digest", mysql.BINARY(32), nullable=False),
        sa.Column("actor_user_id", _id_type(), nullable=False),
        sa.Column(
            "response_schema_version",
            mysql.SMALLINT(unsigned=True),
            nullable=False,
        ),
        sa.Column(
            "response_status_code",
            mysql.SMALLINT(unsigned=True),
            nullable=False,
        ),
        sa.Column("response_payload", mysql.JSON(), nullable=False),
        sa.Column("completed_at", _timestamp_type(), nullable=False),
        sa.PrimaryKeyConstraint(
            "operation_token",
            name="pk_admin_operation_results",
        ),
        sa.ForeignKeyConstraint(
            [
                "operation_token",
                "operation_kind",
                "operation_digest",
                "actor_user_id",
            ],
            [
                "admin_operation_tokens.operation_token",
                "admin_operation_tokens.operation_kind",
                "admin_operation_tokens.operation_digest",
                "admin_operation_tokens.actor_user_id",
            ],
            name="fk_admin_operation_results_identity",
            ondelete="RESTRICT",
            onupdate="RESTRICT",
        ),
        sa.CheckConstraint(
            "response_schema_version = 1",
            name="ck_admin_operation_results_schema_version",
        ),
        sa.CheckConstraint(
            "((operation_kind = 'update_user' AND response_status_code = 200) "
            "OR (operation_kind IN ("
            "'create_user', 'create_site_config_version') "
            "AND response_status_code = 201))",
            name="ck_admin_operation_results_status",
        ),
        sa.Index(
            "ix_admin_operation_results_actor_completed",
            "actor_user_id",
            "completed_at",
        ),
        **_TABLE_OPTIONS,
    )


def _trigger_name(table_name: str, operation: str) -> str:
    return f"trg_{table_name}_no_{operation.lower()}"


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


def _create_immutable_trigger(table_name: str, operation: str) -> None:
    trigger_name = _trigger_name(table_name, operation)
    op.execute(
        sa.text(
            f"""
            CREATE TRIGGER {trigger_name}
            BEFORE {operation} ON {table_name}
            FOR EACH ROW
            {_immutable_trigger_statement(table_name)}
            """
        )
    )


def _drop_immutable_triggers() -> None:
    for table_name in ("admin_operation_results", "admin_operation_tokens"):
        for operation in ("UPDATE", "DELETE"):
            op.execute(
                sa.text(
                    f"DROP TRIGGER IF EXISTS {_trigger_name(table_name, operation)}"
                )
            )


def _create_immutable_triggers() -> None:
    for table_name in ("admin_operation_tokens", "admin_operation_results"):
        for operation in ("UPDATE", "DELETE"):
            _create_immutable_trigger(table_name, operation)


def _existing_contract_tables() -> frozenset[str]:
    if context.is_offline_mode():
        return frozenset()
    return frozenset(
        str(value)
        for value in op.get_bind().scalars(
            sa.text(
                """
                SELECT table_name
                FROM information_schema.tables
                WHERE table_schema = DATABASE()
                  AND table_name IN (
                      'admin_operation_tokens', 'admin_operation_results'
                  )
                """
            )
        )
    )


def _incompatible_partial_table(table_name: str, detail: str) -> RuntimeError:
    return RuntimeError(
        "0011 found an incompatible pre-existing administrator operation "
        f"table: {table_name} ({detail}); repair it explicitly before retrying"
    )


def _optional_string(value: object) -> str | None:
    return None if value is None else str(value)


def _normalize_check_clause(clause: str) -> str:
    normalized = clause.casefold().replace("`", "").replace("\\'", "'")
    normalized = re.sub(r"_[a-z0-9]+(?=')", "", normalized)
    return re.sub(r"\s+", "", normalized)


def _normalize_trigger_statement(statement: str) -> str:
    normalized = statement.casefold().replace("`", "").replace("\\'", "'")
    return re.sub(r"\s+", "", normalized)


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
            _optional_string(row[4]),
            None if row[5] is None else str(row[5]).casefold(),
            None if row[6] is None else str(row[6]).casefold(),
            str(row[7]).casefold(),
            str(row[8]),
        )
        for row in rows
    )


def _key_constraint_signature(
    table_name: str,
) -> frozenset[_KeyConstraintSignature]:
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
                       references_.unique_constraint_name,
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
    return frozenset(
        (
            str(row[0]),
            str(row[1]).upper(),
            str(row[2]).upper(),
            int(row[3]),
            str(row[4]),
            _optional_string(row[5]),
            _optional_string(row[6]),
            _optional_string(row[7]),
            None if row[8] is None else int(row[8]),
            _optional_string(row[9]),
            None if row[10] is None else str(row[10]).upper(),
            None if row[11] is None else str(row[11]).upper(),
        )
        for row in rows
    )


def _check_signature(table_name: str) -> dict[str, str]:
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
    signature: dict[str, str] = {}
    for row in rows:
        if str(row[1]).upper() != "CHECK" or str(row[2]).upper() != "YES":
            raise _incompatible_partial_table(
                table_name,
                f"constraint {row[0]} is not an enforced CHECK",
            )
        signature[str(row[0])] = _normalize_check_clause(str(row[3]))
    return signature


def _index_signature(table_name: str) -> frozenset[_IndexSignature]:
    rows = (
        op.get_bind()
        .execute(
            sa.text(
                """
                SELECT index_name, non_unique, seq_in_index, column_name,
                       sub_part, collation, index_type, is_visible, expression
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
    return frozenset(
        (
            str(row[0]),
            int(row[1]),
            int(row[2]),
            _optional_string(row[3]),
            None if row[4] is None else int(row[4]),
            None if row[5] is None else str(row[5]).upper(),
            str(row[6]).upper(),
            str(row[7]).upper(),
            _optional_string(row[8]),
        )
        for row in rows
    )


def _assert_partial_table_signature(table_name: str) -> None:
    bind = op.get_bind()
    metadata = (
        bind.execute(
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
        raise _incompatible_partial_table(table_name, "table metadata")

    expected_columns, expected_keys, expected_checks, expected_indexes = (
        _TABLE_SIGNATURES[table_name]
    )
    if _column_signature(table_name) != expected_columns:
        raise _incompatible_partial_table(table_name, "column signature")
    if _key_constraint_signature(table_name) != expected_keys:
        raise _incompatible_partial_table(table_name, "key constraint signature")

    normalized_expected_checks = {
        name: _normalize_check_clause(clause)
        for name, clause in expected_checks.items()
    }
    if _check_signature(table_name) != normalized_expected_checks:
        raise _incompatible_partial_table(table_name, "CHECK constraint signature")
    if _index_signature(table_name) != expected_indexes:
        raise _incompatible_partial_table(table_name, "index signature")

    row_count = int(bind.scalar(sa.text(f"SELECT COUNT(*) FROM {table_name}")) or 0)
    if row_count != 0:
        raise _incompatible_partial_table(table_name, "table is not empty")


def _expected_trigger_signatures(
    tables: frozenset[str],
) -> dict[str, tuple[str, str, str, str, str | None, str]]:
    return {
        _trigger_name(table_name, operation): (
            table_name,
            operation,
            "BEFORE",
            "ROW",
            None,
            _normalize_trigger_statement(_immutable_trigger_statement(table_name)),
        )
        for table_name in tables
        for operation in ("UPDATE", "DELETE")
    }


def _assert_partial_trigger_signatures(
    tables: frozenset[str],
    *,
    require_all: bool = False,
) -> None:
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
                  AND event_object_table IN (
                      'admin_operation_tokens', 'admin_operation_results'
                  )
                ORDER BY trigger_name
                """
            )
        )
        .tuples()
        .all()
    )
    expected = _expected_trigger_signatures(tables)
    actual = {
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
    if any(
        name not in expected or expected[name] != signature
        for name, signature in actual.items()
    ) or (require_all and actual != expected):
        raise RuntimeError(
            "0011 found an incompatible pre-existing administrator operation "
            "trigger; repair it explicitly before retrying"
        )


def _recover_partial_upgrade() -> bool:
    tables = _existing_contract_tables()
    if not tables:
        return False
    if "admin_operation_tokens" not in tables:
        raise RuntimeError(
            "0011 found admin_operation_results without its token ledger; "
            "repair the partial schema explicitly before retrying"
        )
    _assert_partial_table_signature("admin_operation_tokens")
    if "admin_operation_results" in tables:
        _assert_partial_table_signature("admin_operation_results")
    else:
        _assert_partial_trigger_signatures(tables)
        _create_result_table()
        _assert_partial_table_signature("admin_operation_results")
        tables = frozenset({*tables, "admin_operation_results"})
    _assert_partial_trigger_signatures(tables)
    _drop_immutable_triggers()
    _create_immutable_triggers()
    _assert_partial_trigger_signatures(tables, require_all=True)
    return True


def upgrade() -> None:
    _assert_trigger_creation_policy()
    if _recover_partial_upgrade():
        return
    _create_token_table()
    _create_result_table()
    _create_immutable_triggers()


def downgrade() -> None:
    _drop_immutable_triggers()
    op.drop_table("admin_operation_results")
    op.drop_table("admin_operation_tokens")
