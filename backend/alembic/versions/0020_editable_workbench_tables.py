"""Add versioned original columns and editable extension-cell ledgers."""

import json
from typing import cast
from unicodedata import normalize
from uuid import UUID, uuid5

import sqlalchemy as sa
from alembic import context, op
from sqlalchemy.dialects import mysql

revision = "0020"
down_revision = "0019"
branch_labels = None
depends_on = None

_TABLE_OPTIONS = {
    "mysql_engine": "InnoDB",
    "mysql_charset": "utf8mb4",
    "mysql_collate": "utf8mb4_0900_ai_ci",
}
_COLUMN_NAMESPACE = UUID("e88da32a-c824-4cac-87bc-3dc47f042ceb")
_KEY_FIELDS = {
    "business_report": {"child_asin", "sku"},
    "return_report": {
        "return_date",
        "order_id",
        "sku",
        "asin",
        "quantity",
        "detailed_disposition",
        "reason",
        "status",
    },
}


def _id_type() -> sa.BigInteger:
    return sa.BigInteger().with_variant(mysql.BIGINT(unsigned=True), "mysql")


def _count_type() -> sa.Integer:
    return sa.Integer().with_variant(mysql.INTEGER(unsigned=True), "mysql")


def _timestamp_type() -> sa.DateTime:
    return sa.DateTime().with_variant(mysql.DATETIME(fsp=6), "mysql")


def _code_type(length: int) -> sa.String:
    return sa.String(length=length).with_variant(
        mysql.VARCHAR(length=length, charset="ascii", collation="ascii_bin"),
        "mysql",
    )


def _create_immutable_triggers(table_name: str, message: str) -> None:
    for operation in ("UPDATE", "DELETE"):
        trigger_name = f"trg_{table_name}_immutable_{operation.lower()}"
        op.execute(
            sa.text(
                f"""
                CREATE TRIGGER {trigger_name}
                BEFORE {operation} ON {table_name}
                FOR EACH ROW
                BEGIN
                    IF NOT EXISTS (
                        SELECT 1
                        FROM terminal_write_guard_bypass_accounts
                        WHERE account_identity = USER()
                    ) THEN
                        SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = '{message}';
                    END IF;
                END
                """
            )
        )


def _drop_trigger(name: str) -> None:
    op.execute(sa.text(f"DROP TRIGGER IF EXISTS {name}"))


def _json_object(value: object, *, label: str) -> dict[str, object]:
    if isinstance(value, str):
        value = json.loads(value)
    if not isinstance(value, dict) or not all(isinstance(key, str) for key in value):
        raise RuntimeError(f"0020 cannot decode {label}")
    return cast(dict[str, object], value)


def _mapping_columns(value: object) -> list[dict[str, object]]:
    payload = _json_object(value, label="parse field mapping")
    raw_headers = payload.get("source_header")
    raw_fields = payload.get("fields")
    if not isinstance(raw_headers, list) or not all(
        isinstance(header, str) for header in raw_headers
    ):
        raise RuntimeError("0020 parse field mapping has invalid headers")
    if not isinstance(raw_fields, list):
        raise RuntimeError("0020 parse field mapping has invalid fields")
    fields: dict[str, tuple[str, str]] = {}
    for value in raw_fields:
        if not isinstance(value, dict):
            raise RuntimeError("0020 parse field mapping contains an invalid field")
        source = value.get("source")
        target = value.get("target")
        kind = value.get("kind")
        if not all(isinstance(item, str) for item in (source, target, kind)):
            raise RuntimeError("0020 parse field mapping field is incomplete")
        fields[cast(str, source)] = (cast(str, target), cast(str, kind))
    kind_map = {
        "text": "text",
        "integer": "integer",
        "percentage": "decimal",
        "usd": "decimal",
        "event_datetime": "utc_datetime",
    }
    return [
        {
            "source_header": normalize("NFC", cast(str, header)),
            "standard_field_name": fields.get(cast(str, header), (None, "text"))[0],
            "value_kind": kind_map.get(
                fields.get(cast(str, header), (None, "text"))[1],
                "text",
            ),
        }
        for header in raw_headers
    ]


def _backfill_existing_versions() -> None:
    if context.is_offline_mode():
        return
    connection = op.get_bind()
    versions = (
        connection.execute(
            sa.text(
                """
                SELECT id, report_type, created_at
                FROM dataset_versions
                ORDER BY created_at, id
                """
            )
        )
        .mappings()
        .all()
    )
    schemas: dict[int, list[dict[str, object]]] = {}
    for version in versions:
        version_id = int(version["id"])
        report_type = str(version["report_type"])
        members = (
            connection.execute(
                sa.text(
                    """
                    SELECT members.member_type, members.parse_baseline_id,
                           members.parent_version_id, attempts.field_mapping
                    FROM version_base_snapshots AS snapshots
                    INNER JOIN version_base_snapshot_members AS members
                        ON members.snapshot_id = snapshots.id
                    LEFT JOIN parse_baselines AS baselines
                        ON baselines.id = members.parse_baseline_id
                    LEFT JOIN parse_attempts AS attempts
                        ON attempts.id = baselines.parse_attempt_id
                    WHERE snapshots.version_id = :version_id
                    ORDER BY members.member_ordinal, members.id
                    """
                ),
                {"version_id": version_id},
            )
            .mappings()
            .all()
        )
        columns: list[dict[str, object]] = []
        seen_headers: set[str] = set()
        for member in members:
            if str(member["member_type"]) == "parse_baseline":
                if member["field_mapping"] is None:
                    raise RuntimeError("0020 parse member has no field mapping")
                member_columns = _mapping_columns(member["field_mapping"])
            else:
                parent_id = int(member["parent_version_id"])
                try:
                    member_columns = schemas[parent_id]
                except KeyError as error:
                    raise RuntimeError(
                        "0020 parent table schema is not available"
                    ) from error
            for column in member_columns:
                header = cast(str, column["source_header"])
                if header in seen_headers:
                    continue
                seen_headers.add(header)
                columns.append(dict(column))
        if not columns:
            continue
        schemas[version_id] = columns
        column_ids: dict[str, bytes] = {}
        extension_headers: set[str] = set()
        for display_order, column in enumerate(columns, start=1):
            header = cast(str, column["source_header"])
            standard = column["standard_field_name"]
            column_id = uuid5(
                _COLUMN_NAMESPACE,
                f"{report_type}\0{header}",
            ).bytes
            column_ids[header] = column_id
            if standard is None:
                extension_headers.add(header)
            connection.execute(
                sa.text(
                    """
                    INSERT INTO version_table_columns (
                        version_id, column_id, source_header, display_order,
                        value_kind, standard_field_name, is_key,
                        participates_in_statistics, created_at
                    ) VALUES (
                        :version_id, :column_id, :source_header, :display_order,
                        :value_kind, :standard_field_name, :is_key,
                        :participates_in_statistics, :created_at
                    )
                    """
                ),
                {
                    "version_id": version_id,
                    "column_id": column_id,
                    "source_header": header,
                    "display_order": display_order,
                    "value_kind": column["value_kind"],
                    "standard_field_name": standard,
                    "is_key": standard in _KEY_FIELDS.get(report_type, set()),
                    "participates_in_statistics": standard is not None,
                    "created_at": version["created_at"],
                },
            )
        if not extension_headers:
            continue
        source_rows = (
            connection.execute(
                sa.text(
                    """
                    SELECT rows.id AS version_row_id, sources.decoded_fields
                    FROM version_rows AS rows
                    INNER JOIN parsed_source_rows AS sources
                        ON sources.id = rows.original_parsed_source_row_id
                    WHERE rows.version_id = :version_id
                    ORDER BY rows.row_ordinal, rows.id
                    """
                ),
                {"version_id": version_id},
            )
            .mappings()
            .all()
        )
        for source_row in source_rows:
            decoded = _json_object(
                source_row["decoded_fields"],
                label="parsed source row",
            )
            headers = decoded.get("header")
            values = decoded.get("values")
            if not isinstance(headers, list) or not isinstance(values, list):
                raise RuntimeError("0020 parsed source row has invalid arrays")
            for index, header_value in enumerate(headers):
                if not isinstance(header_value, str):
                    raise RuntimeError("0020 parsed source header is invalid")
                header = normalize("NFC", header_value)
                if header not in extension_headers:
                    continue
                value = values[index] if index < len(values) else None
                if value is not None and not isinstance(value, str):
                    raise RuntimeError("0020 parsed source value is invalid")
                connection.execute(
                    sa.text(
                        """
                        INSERT INTO version_extension_cells (
                            version_id, row_id, column_id, base_value,
                            current_value, cell_revision, updated_at
                        ) VALUES (
                            :version_id, :row_id, :column_id, :base_value,
                            :current_value, 0, :updated_at
                        )
                        """
                    ),
                    {
                        "version_id": version_id,
                        "row_id": int(source_row["version_row_id"]),
                        "column_id": column_ids[header],
                        "base_value": value,
                        "current_value": value,
                        "updated_at": version["created_at"],
                    },
                )


def upgrade() -> None:
    op.add_column(
        "import_batches",
        sa.Column("candidate_report_date", sa.Date(), nullable=True),
    )
    op.execute(
        sa.text(
            """
            UPDATE import_batches
            SET candidate_report_date = COALESCE(detected_report_date, report_date)
            WHERE confirmed_at IS NULL
            """
        )
    )
    op.create_index(
        "ix_import_batches_pending_ownership",
        "import_batches",
        ["site_id", "confirmed_at", "candidate_report_date", "id"],
    )

    op.create_table(
        "version_table_columns",
        sa.Column("version_id", _id_type(), nullable=False),
        sa.Column("column_id", mysql.BINARY(16), nullable=False),
        sa.Column(
            "source_header",
            mysql.VARCHAR(
                length=255,
                charset="utf8mb4",
                collation="utf8mb4_0900_as_cs",
            ),
            nullable=False,
        ),
        sa.Column("display_order", _count_type(), nullable=False),
        sa.Column("value_kind", _code_type(24), nullable=False),
        sa.Column("standard_field_name", _code_type(128), nullable=True),
        sa.Column("is_key", sa.Boolean(), nullable=False),
        sa.Column("participates_in_statistics", sa.Boolean(), nullable=False),
        sa.Column(
            "created_at",
            _timestamp_type(),
            server_default=sa.text("CURRENT_TIMESTAMP(6)"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint(
            "version_id",
            "column_id",
            name="pk_version_table_columns",
        ),
        sa.ForeignKeyConstraint(
            ["version_id"],
            ["dataset_versions.id"],
            name="fk_version_table_columns_version",
            ondelete="RESTRICT",
            onupdate="RESTRICT",
        ),
        sa.UniqueConstraint(
            "version_id",
            "display_order",
            name="uq_version_table_columns_order",
        ),
        sa.UniqueConstraint(
            "version_id",
            "source_header",
            name="uq_version_table_columns_header",
        ),
        sa.CheckConstraint(
            "display_order > 0",
            name="ck_version_table_columns_order_positive",
        ),
        sa.CheckConstraint(
            "value_kind IN ('text', 'integer', 'decimal', 'utc_datetime')",
            name="ck_version_table_columns_kind",
        ),
        sa.CheckConstraint(
            "CHAR_LENGTH(source_header) > 0",
            name="ck_version_table_columns_header_nonempty",
        ),
        **_TABLE_OPTIONS,
    )

    op.create_table(
        "version_extension_cells",
        sa.Column("version_id", _id_type(), nullable=False),
        sa.Column("row_id", _id_type(), nullable=False),
        sa.Column("column_id", mysql.BINARY(16), nullable=False),
        sa.Column("base_value", mysql.LONGTEXT(), nullable=True),
        sa.Column("current_value", mysql.LONGTEXT(), nullable=True),
        sa.Column(
            "cell_revision",
            _id_type(),
            server_default=sa.text("0"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            _timestamp_type(),
            server_default=sa.text("CURRENT_TIMESTAMP(6)"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint(
            "version_id",
            "row_id",
            "column_id",
            name="pk_version_extension_cells",
        ),
        sa.UniqueConstraint(
            "version_id",
            "row_id",
            "column_id",
            "cell_revision",
            name="uq_version_extension_cells_identity",
        ),
        sa.ForeignKeyConstraint(
            ["version_id", "row_id"],
            ["version_rows.version_id", "version_rows.id"],
            name="fk_version_extension_cells_row",
            ondelete="RESTRICT",
            onupdate="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["version_id", "column_id"],
            ["version_table_columns.version_id", "version_table_columns.column_id"],
            name="fk_version_extension_cells_column",
            ondelete="RESTRICT",
            onupdate="RESTRICT",
        ),
        **_TABLE_OPTIONS,
    )

    op.create_table(
        "extension_cell_changes",
        sa.Column("id", _id_type(), autoincrement=True, nullable=False),
        sa.Column("operation_token", mysql.BINARY(16), nullable=False),
        sa.Column("version_id", _id_type(), nullable=False),
        sa.Column("row_id", _id_type(), nullable=False),
        sa.Column("column_id", mysql.BINARY(16), nullable=False),
        sa.Column("data_revision", _id_type(), nullable=False),
        sa.Column("cell_revision", _id_type(), nullable=False),
        sa.Column("operation", _code_type(16), nullable=False),
        sa.Column("before_value", mysql.LONGTEXT(), nullable=True),
        sa.Column("after_value", mysql.LONGTEXT(), nullable=True),
        sa.Column("actor_user_id", _id_type(), nullable=False),
        sa.Column("reason", mysql.LONGTEXT(), nullable=False),
        sa.Column("undoes_change_id", _id_type(), nullable=True),
        sa.Column(
            "occurred_at",
            _timestamp_type(),
            server_default=sa.text("CURRENT_TIMESTAMP(6)"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id", name="pk_extension_cell_changes"),
        sa.UniqueConstraint(
            "version_id",
            "row_id",
            "column_id",
            "cell_revision",
            name="uq_extension_cell_changes_revision",
        ),
        sa.UniqueConstraint(
            "operation_token",
            name="uq_extension_cell_changes_operation",
        ),
        sa.ForeignKeyConstraint(
            ["version_id", "row_id"],
            ["version_rows.version_id", "version_rows.id"],
            name="fk_extension_cell_changes_row",
            ondelete="RESTRICT",
            onupdate="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["version_id", "column_id"],
            ["version_table_columns.version_id", "version_table_columns.column_id"],
            name="fk_extension_cell_changes_column",
            ondelete="RESTRICT",
            onupdate="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["actor_user_id"],
            ["users.id"],
            name="fk_extension_cell_changes_actor",
            ondelete="RESTRICT",
            onupdate="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["undoes_change_id"],
            ["extension_cell_changes.id"],
            name="fk_extension_cell_changes_undone_change",
            ondelete="RESTRICT",
            onupdate="RESTRICT",
        ),
        sa.CheckConstraint(
            "operation IN ('set', 'undo')",
            name="ck_extension_cell_changes_operation",
        ),
        sa.CheckConstraint(
            "((operation = 'set' AND undoes_change_id IS NULL) OR "
            "(operation = 'undo' AND undoes_change_id IS NOT NULL))",
            name="ck_extension_cell_changes_undo",
        ),
        sa.CheckConstraint(
            "cell_revision > 0 AND data_revision > 0",
            name="ck_extension_cell_changes_revisions_positive",
        ),
        sa.Index(
            "ix_extension_cell_changes_actor_time",
            "version_id",
            "actor_user_id",
            "occurred_at",
            "id",
        ),
        **_TABLE_OPTIONS,
    )

    op.create_table(
        "workbench_operation_tokens",
        sa.Column("operation_token", mysql.BINARY(16), nullable=False),
        sa.Column("operation_kind", _code_type(32), nullable=False),
        sa.Column("operation_digest", mysql.BINARY(32), nullable=False),
        sa.Column("actor_user_id", _id_type(), nullable=False),
        sa.Column("expected_cell_revision", _id_type(), nullable=True),
        sa.Column("registered_at", _timestamp_type(), nullable=False),
        sa.PrimaryKeyConstraint(
            "operation_token",
            name="pk_workbench_operation_tokens",
        ),
        sa.UniqueConstraint(
            "operation_token",
            "operation_kind",
            "operation_digest",
            "actor_user_id",
            name="uq_workbench_operation_tokens_identity",
        ),
        sa.ForeignKeyConstraint(
            ["actor_user_id"],
            ["users.id"],
            name="fk_workbench_operation_tokens_actor",
            ondelete="RESTRICT",
            onupdate="RESTRICT",
        ),
        sa.CheckConstraint(
            "operation_kind IN ('set_cell', 'undo_cell', 'orchestrate_import')",
            name="ck_workbench_operation_tokens_kind",
        ),
        **_TABLE_OPTIONS,
    )

    op.create_foreign_key(
        "fk_extension_cell_changes_operation",
        "extension_cell_changes",
        "workbench_operation_tokens",
        ["operation_token"],
        ["operation_token"],
        ondelete="RESTRICT",
        onupdate="RESTRICT",
    )

    op.create_table(
        "workbench_operation_results",
        sa.Column("operation_token", mysql.BINARY(16), nullable=False),
        sa.Column("operation_kind", _code_type(32), nullable=False),
        sa.Column("operation_digest", mysql.BINARY(32), nullable=False),
        sa.Column("actor_user_id", _id_type(), nullable=False),
        sa.Column("response_status_code", sa.SmallInteger(), nullable=False),
        sa.Column("response_payload", mysql.JSON(), nullable=False),
        sa.Column("completed_at", _timestamp_type(), nullable=False),
        sa.PrimaryKeyConstraint(
            "operation_token",
            name="pk_workbench_operation_results",
        ),
        sa.ForeignKeyConstraint(
            [
                "operation_token",
                "operation_kind",
                "operation_digest",
                "actor_user_id",
            ],
            [
                "workbench_operation_tokens.operation_token",
                "workbench_operation_tokens.operation_kind",
                "workbench_operation_tokens.operation_digest",
                "workbench_operation_tokens.actor_user_id",
            ],
            name="fk_workbench_operation_results_identity",
            ondelete="RESTRICT",
            onupdate="RESTRICT",
        ),
        sa.CheckConstraint(
            "response_status_code IN (200, 201, 409)",
            name="ck_workbench_operation_results_status",
        ),
        **_TABLE_OPTIONS,
    )

    _backfill_existing_versions()

    _create_immutable_triggers(
        "version_table_columns",
        "version table columns are immutable",
    )
    _create_immutable_triggers(
        "extension_cell_changes",
        "extension cell changes are immutable",
    )
    _create_immutable_triggers(
        "workbench_operation_tokens",
        "workbench operation tokens are immutable",
    )
    _create_immutable_triggers(
        "workbench_operation_results",
        "workbench operation results are immutable",
    )
    op.execute(
        sa.text(
            """
            CREATE TRIGGER trg_version_extension_cells_editable_update
            BEFORE UPDATE ON version_extension_cells
            FOR EACH ROW
            BEGIN
                IF NOT EXISTS (
                    SELECT 1
                    FROM terminal_write_guard_bypass_accounts
                    WHERE account_identity = USER()
                ) AND NOT EXISTS (
                    SELECT 1
                    FROM dataset_versions AS versions
                    INNER JOIN dataset_drafts AS drafts
                        ON drafts.dataset_id = versions.dataset_id
                       AND drafts.version_id = versions.id
                    WHERE versions.id = OLD.version_id
                      AND versions.status IN ('draft', 'ready_for_publish')
                ) THEN
                    SIGNAL SQLSTATE '45000'
                        SET MESSAGE_TEXT = 'extension cell is not editable';
                END IF;
            END
            """
        )
    )
    op.execute(
        sa.text(
            """
            CREATE TRIGGER trg_version_extension_cells_immutable_delete
            BEFORE DELETE ON version_extension_cells
            FOR EACH ROW
            BEGIN
                IF NOT EXISTS (
                    SELECT 1
                    FROM terminal_write_guard_bypass_accounts
                    WHERE account_identity = USER()
                ) THEN
                    SIGNAL SQLSTATE '45000'
                        SET MESSAGE_TEXT = 'extension cell snapshots cannot be deleted';
                END IF;
            END
            """
        )
    )


def downgrade() -> None:
    connection = op.get_bind()
    for table_name in (
        "workbench_operation_results",
        "extension_cell_changes",
        "workbench_operation_tokens",
        "version_extension_cells",
        "version_table_columns",
    ):
        count = connection.scalar(sa.text(f"SELECT COUNT(*) FROM {table_name}"))
        if count:
            raise RuntimeError(
                "0020 downgrade refused because editable workbench data exists"
            )

    _drop_trigger("trg_version_extension_cells_immutable_delete")
    _drop_trigger("trg_version_extension_cells_editable_update")
    for table_name in (
        "workbench_operation_results",
        "workbench_operation_tokens",
        "extension_cell_changes",
        "version_table_columns",
    ):
        for operation in ("delete", "update"):
            _drop_trigger(f"trg_{table_name}_immutable_{operation}")

    op.drop_table("workbench_operation_results")
    op.drop_constraint(
        "fk_extension_cell_changes_operation",
        "extension_cell_changes",
        type_="foreignkey",
    )
    op.drop_table("workbench_operation_tokens")
    op.drop_table("extension_cell_changes")
    op.drop_table("version_extension_cells")
    op.drop_table("version_table_columns")
    op.drop_index("ix_import_batches_pending_ownership", table_name="import_batches")
    op.drop_column("import_batches", "candidate_report_date")
