"""Persistence helpers for versioned original-column snapshots."""

from __future__ import annotations

import hmac
import json
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, Literal, cast
from uuid import UUID

import sqlalchemy as sa
from sqlalchemy.engine import Connection, Engine
from sqlalchemy.exc import IntegrityError

from app.imports.types import ReportType
from app.review.repository import MySqlReviewRepository
from app.validation.codec import decode_field_value, encode_field_value
from app.validation.fields import field_value_to_database

from .commands import (
    NothingToUndo,
    SetWorkbenchCellCommand,
    UndoWorkbenchCellCommand,
    WorkbenchCellConflict,
    WorkbenchCellValueInvalid,
    WorkbenchColumnNotFound,
    WorkbenchMutationError,
    WorkbenchOperationConflict,
)
from .schema import SourceColumnMapping, SourceValueKind, compose_table_schema
from .types import TableSchema

type SchemaMemberKind = Literal["parse_baseline", "dataset_version"]
type WorkbenchOperationCommand = SetWorkbenchCellCommand | UndoWorkbenchCellCommand


LATEST_UNDOABLE_CELL_SQL = sa.text(
    """
    SELECT candidates.*
    FROM (
        SELECT 'extension' AS ledger_kind,
               changes.id AS change_id, changes.row_id,
               changes.column_id, NULL AS field_name,
               changes.before_value, changes.after_value,
               changes.cell_revision, changes.data_revision,
               changes.occurred_at
        FROM extension_cell_changes AS changes
        INNER JOIN version_extension_cells AS cells
            ON cells.version_id = changes.version_id
           AND cells.row_id = changes.row_id
           AND cells.column_id = changes.column_id
           AND cells.cell_revision = changes.cell_revision
        WHERE changes.version_id = :version_id
          AND changes.actor_user_id = :actor_user_id
          AND changes.operation = 'set'
        UNION ALL
        SELECT 'standard' AS ledger_kind,
               events.id AS change_id, changes.row_id,
               columns.column_id, changes.field_name,
               changes.before_value_json AS before_value,
               changes.after_value_json AS after_value,
               events.data_revision AS cell_revision,
               events.data_revision,
               events.occurred_at
        FROM data_change_events AS events
        INNER JOIN field_changes AS changes
            ON changes.version_id = events.version_id
           AND changes.id = events.id
        INNER JOIN version_table_columns AS columns
            ON columns.version_id = changes.version_id
           AND columns.standard_field_name = changes.field_name
        WHERE events.version_id = :version_id
          AND events.actor_user_id = :actor_user_id
          AND changes.operation = 'set'
          AND NOT EXISTS (
              SELECT 1
              FROM field_changes AS later_changes
              INNER JOIN data_change_events AS later_events
                  ON later_events.version_id =
                     later_changes.version_id
                 AND later_events.id = later_changes.id
              WHERE later_changes.version_id = changes.version_id
                AND later_changes.row_id = changes.row_id
                AND later_changes.field_name = changes.field_name
                AND later_events.data_revision >
                    events.data_revision
          )
    ) AS candidates
    ORDER BY candidates.data_revision DESC,
             candidates.occurred_at DESC,
             candidates.ledger_kind,
             candidates.change_id DESC
    LIMIT 1
    """
)


@dataclass(frozen=True, slots=True)
class SchemaMember:
    member_ordinal: int
    member_type: SchemaMemberKind
    source_id: int

    def __post_init__(self) -> None:
        if self.member_ordinal < 1 or self.source_id < 1:
            raise ValueError("schema member identifiers must be positive")


@dataclass(frozen=True, slots=True)
class SnapshotRowSource:
    version_row_id: int
    member_ordinal: int
    source_row_id: int
    original_parsed_source_row_id: int | None

    def __post_init__(self) -> None:
        if min(self.version_row_id, self.member_ordinal, self.source_row_id) < 1:
            raise ValueError("snapshot row identifiers must be positive")
        if (
            self.original_parsed_source_row_id is not None
            and self.original_parsed_source_row_id < 1
        ):
            raise ValueError("parsed source row identifier must be positive")


def _json_object(value: object, *, label: str) -> dict[str, object]:
    if isinstance(value, str):
        try:
            value = json.loads(value)
        except json.JSONDecodeError as error:
            raise ValueError(f"{label} is not valid JSON") from error
    if not isinstance(value, dict) or not all(isinstance(key, str) for key in value):
        raise ValueError(f"{label} must be an object")
    return cast(dict[str, object], value)


def decode_source_mapping(value: object) -> tuple[SourceColumnMapping, ...]:
    """Decode parser evidence while retaining unmapped original columns."""

    payload = _json_object(value, label="field mapping")
    raw_headers = payload.get("source_header")
    raw_fields = payload.get("fields")
    if (
        not isinstance(raw_headers, list)
        or not raw_headers
        or not all(isinstance(header, str) for header in raw_headers)
    ):
        raise ValueError("field mapping source_header must be a non-empty array")
    headers = cast(list[str], raw_headers)
    if len(headers) != len(set(headers)):
        raise ValueError("field mapping contains duplicate source headers")
    if not isinstance(raw_fields, list):
        raise ValueError("field mapping fields must be an array")
    mapped: dict[str, tuple[str, SourceValueKind]] = {}
    supported_kinds = {
        "text",
        "integer",
        "percentage",
        "usd",
        "event_datetime",
        "decimal",
        "utc_datetime",
    }
    for raw_field in raw_fields:
        if not isinstance(raw_field, dict):
            raise ValueError("field mapping field must be an object")
        source = raw_field.get("source")
        target = raw_field.get("target")
        kind = raw_field.get("kind")
        if (
            not isinstance(source, str)
            or source not in headers
            or source in mapped
            or not isinstance(target, str)
            or not target
            or not isinstance(kind, str)
            or kind not in supported_kinds
        ):
            raise ValueError("field mapping contains an invalid field")
        mapped[source] = (target, cast(SourceValueKind, kind))
    return tuple(
        SourceColumnMapping(
            source_header=header,
            standard_field_name=(mapped[header][0] if header in mapped else None),
            source_kind=(mapped[header][1] if header in mapped else "text"),
        )
        for header in headers
    )


def decode_source_row(value: object) -> dict[str, str | None]:
    payload = _json_object(value, label="decoded source row")
    raw_headers = payload.get("header")
    raw_values = payload.get("values")
    if not isinstance(raw_headers, list) or not all(
        isinstance(header, str) for header in raw_headers
    ):
        raise ValueError("decoded source row header must be an array")
    if len(raw_headers) != len(set(raw_headers)):
        raise ValueError("decoded source row contains duplicate headers")
    if not isinstance(raw_values, list) or not all(
        isinstance(item, str) for item in raw_values
    ):
        raise ValueError("decoded source row values must be an array")
    headers = cast(list[str], raw_headers)
    values = cast(list[str], raw_values)
    return {
        header: values[index] if index < len(values) else None
        for index, header in enumerate(headers)
    }


def _uuid(value: object) -> UUID:
    if isinstance(value, memoryview):
        value = value.tobytes()
    if not isinstance(value, bytes) or len(value) != 16:
        raise ValueError("database column ID is invalid")
    return UUID(bytes=value)


class MySqlWorkbenchSnapshotRepository:
    """Create schema and extension cells inside a dataset version transaction."""

    def materialize_version(
        self,
        connection: Connection,
        *,
        version_id: int,
        report_type: ReportType,
        ruleset_version: str,
        members: Sequence[SchemaMember],
        rows: Sequence[SnapshotRowSource],
        occurred_at: datetime,
    ) -> TableSchema:
        if version_id < 1 or not members:
            raise ValueError("version and schema members are required")
        member_by_ordinal = {member.member_ordinal: member for member in members}
        if len(member_by_ordinal) != len(members):
            raise ValueError("schema member ordinals must be unique")
        source_mappings = tuple(
            self._member_mapping(
                connection,
                member=member,
                report_type=report_type,
            )
            for member in members
        )
        schema = compose_table_schema(report_type, ruleset_version, source_mappings)
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
            [
                {
                    "version_id": version_id,
                    "column_id": column.column_id.bytes,
                    "source_header": column.source_header,
                    "display_order": column.display_order,
                    "value_kind": column.value_kind,
                    "standard_field_name": column.standard_field_name,
                    "is_key": column.is_key,
                    "participates_in_statistics": (column.participates_in_statistics),
                    "created_at": occurred_at,
                }
                for column in schema.columns
            ],
        )
        extension_columns = {
            column.column_id: column
            for column in schema.columns
            if column.standard_field_name is None
        }
        extension_columns_by_header = {
            column.source_header: column for column in extension_columns.values()
        }
        cell_parameters: list[dict[str, object]] = []
        for row in rows:
            member = member_by_ordinal.get(row.member_ordinal)
            if member is None:
                raise ValueError("snapshot row refers to an unknown schema member")
            values = self._extension_values(connection, member=member, row=row)
            for column_key, value in values.items():
                column = (
                    extension_columns.get(column_key)
                    if isinstance(column_key, UUID)
                    else extension_columns_by_header.get(column_key)
                )
                if column is None:
                    continue
                cell_parameters.append(
                    {
                        "version_id": version_id,
                        "row_id": row.version_row_id,
                        "column_id": column.column_id.bytes,
                        "base_value": value,
                        "current_value": value,
                        "cell_revision": 0,
                        "updated_at": occurred_at,
                    }
                )
        if cell_parameters:
            connection.execute(
                sa.text(
                    """
                    INSERT INTO version_extension_cells (
                        version_id, row_id, column_id, base_value,
                        current_value, cell_revision, updated_at
                    ) VALUES (
                        :version_id, :row_id, :column_id, :base_value,
                        :current_value, :cell_revision, :updated_at
                    )
                    """
                ),
                cell_parameters,
            )
        return schema

    def _member_mapping(
        self,
        connection: Connection,
        *,
        member: SchemaMember,
        report_type: ReportType,
    ) -> tuple[SourceColumnMapping, ...]:
        if member.member_type == "parse_baseline":
            value = connection.scalar(
                sa.text(
                    """
                    SELECT attempts.field_mapping
                    FROM parse_baselines AS baselines
                    INNER JOIN parse_attempts AS attempts
                        ON attempts.id = baselines.parse_attempt_id
                    WHERE baselines.id = :source_id
                      AND baselines.report_type = :report_type
                    """
                ),
                {"source_id": member.source_id, "report_type": report_type},
            )
            if value is None:
                raise ValueError("parse baseline field mapping is unavailable")
            return decode_source_mapping(value)
        rows = (
            connection.execute(
                sa.text(
                    """
                    SELECT column_id, source_header, value_kind,
                           standard_field_name
                    FROM version_table_columns
                    WHERE version_id = :source_id
                    ORDER BY display_order
                    """
                ),
                {"source_id": member.source_id},
            )
            .mappings()
            .all()
        )
        if not rows:
            raise ValueError("parent version table schema is unavailable")
        return tuple(
            SourceColumnMapping(
                source_header=str(row["source_header"]),
                standard_field_name=(
                    str(row["standard_field_name"])
                    if row["standard_field_name"] is not None
                    else None
                ),
                source_kind=cast(SourceValueKind, str(row["value_kind"])),
            )
            for row in rows
        )

    def _extension_values(
        self,
        connection: Connection,
        *,
        member: SchemaMember,
        row: SnapshotRowSource,
    ) -> Mapping[UUID | str, str | None]:
        if member.member_type == "dataset_version":
            return {
                _uuid(item["column_id"]): (
                    str(item["current_value"])
                    if item["current_value"] is not None
                    else None
                )
                for item in connection.execute(
                    sa.text(
                        """
                        SELECT column_id, current_value
                        FROM version_extension_cells
                        WHERE version_id = :version_id
                          AND row_id = :row_id
                        """
                    ),
                    {"version_id": member.source_id, "row_id": row.source_row_id},
                )
                .mappings()
                .all()
            }
        if row.original_parsed_source_row_id is None:
            return {}
        decoded = connection.scalar(
            sa.text(
                """
                SELECT decoded_fields
                FROM parsed_source_rows
                WHERE id = :row_id
                """
            ),
            {"row_id": row.original_parsed_source_row_id},
        )
        if decoded is None:
            raise ValueError("parsed source row evidence is unavailable")
        return {
            cast(UUID | str, header): value
            for header, value in decode_source_row(decoded).items()
        }


@dataclass(frozen=True, slots=True)
class WorkbenchMutationHead:
    dataset_id: int
    version_id: int
    status: Literal["draft", "ready_for_publish"]
    data_revision: int
    review_revision: int
    pointed_at: datetime


@dataclass(frozen=True, slots=True)
class WorkbenchMutationCell:
    row_id: int
    column_id: UUID
    current: str | None
    base: str | None
    cell_revision: int


@dataclass(frozen=True, slots=True)
class WorkbenchCellMutationResult:
    operation_token: UUID
    head: WorkbenchMutationHead
    cell: WorkbenchMutationCell
    change_id: int


def _mysql_datetime(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("workbench transaction timestamp must be timezone-aware")
    return value.astimezone(UTC).replace(tzinfo=None)


def _utc_datetime(value: object) -> datetime:
    if not isinstance(value, datetime):
        raise WorkbenchMutationError("database returned an invalid pointer timestamp")
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


def _json_payload(value: object) -> dict[str, object]:
    if isinstance(value, str):
        try:
            value = json.loads(value)
        except json.JSONDecodeError as error:
            raise WorkbenchMutationError(
                "stored workbench result is invalid"
            ) from error
    if not isinstance(value, dict):
        raise WorkbenchMutationError("stored workbench result is invalid")
    return {str(key): item for key, item in value.items()}


def _mutation_result_payload(result: WorkbenchCellMutationResult) -> dict[str, object]:
    return {
        "operation_token": str(result.operation_token),
        "head": {
            "dataset_id": result.head.dataset_id,
            "version_id": result.head.version_id,
            "status": result.head.status,
            "data_revision": result.head.data_revision,
            "review_revision": result.head.review_revision,
            "pointed_at": result.head.pointed_at.astimezone(UTC)
            .isoformat(timespec="microseconds")
            .replace("+00:00", "Z"),
        },
        "cell": {
            "row_id": result.cell.row_id,
            "column_id": str(result.cell.column_id),
            "current": result.cell.current,
            "base": result.cell.base,
            "cell_revision": result.cell.cell_revision,
        },
        "change_id": result.change_id,
    }


def _decode_mutation_result(payload: object) -> WorkbenchCellMutationResult:
    value = _json_payload(payload)
    head = _json_payload(value.get("head"))
    cell = _json_payload(value.get("cell"))
    try:
        pointed_at_raw = head["pointed_at"]
        if not isinstance(pointed_at_raw, str):
            raise ValueError("pointed_at must be text")
        pointed_at = datetime.fromisoformat(pointed_at_raw.replace("Z", "+00:00"))
        status = str(head["status"])
        if status not in {"draft", "ready_for_publish"}:
            raise ValueError("status is not editable")
        current = cell.get("current")
        base = cell.get("base")
        if current is not None and not isinstance(current, str):
            raise ValueError("current cell value is not text")
        if base is not None and not isinstance(base, str):
            raise ValueError("base cell value is not text")
        return WorkbenchCellMutationResult(
            operation_token=UUID(str(value["operation_token"])),
            head=WorkbenchMutationHead(
                dataset_id=int(cast(Any, head["dataset_id"])),
                version_id=int(cast(Any, head["version_id"])),
                status=cast(
                    Literal["draft", "ready_for_publish"],
                    status,
                ),
                data_revision=int(cast(Any, head["data_revision"])),
                review_revision=int(cast(Any, head["review_revision"])),
                pointed_at=_utc_datetime(pointed_at),
            ),
            cell=WorkbenchMutationCell(
                row_id=int(cast(Any, cell["row_id"])),
                column_id=UUID(str(cell["column_id"])),
                current=current,
                base=base,
                cell_revision=int(cast(Any, cell["cell_revision"])),
            ),
            change_id=int(cast(Any, value["change_id"])),
        )
    except (KeyError, TypeError, ValueError) as error:
        raise WorkbenchMutationError("stored workbench result is invalid") from error


class MySqlWorkbenchMutationRepository:
    """Persist extension-cell writes with one idempotent optimistic transaction."""

    def __init__(self, engine: Engine) -> None:
        self._engine = engine

    def set_extension_cell(
        self,
        command: SetWorkbenchCellCommand,
        *,
        occurred_at: datetime,
    ) -> WorkbenchCellMutationResult:
        if command.value is not None and not isinstance(command.value, str):
            raise WorkbenchCellValueInvalid(
                "extension cell values must be text or null"
            )
        recovered = self._recover(command)
        if recovered is not None:
            return recovered
        timestamp = _mysql_datetime(occurred_at)
        with self._engine.begin() as connection:
            recovered = self._claim(
                connection,
                command=command,
                registered_at=timestamp,
            )
            if recovered is not None:
                return recovered
            MySqlReviewRepository._load_actor(
                connection,
                actor_user_id=command.actor_user_id,
            )
            MySqlReviewRepository._lock_active_head(connection, command.head)
            selected = (
                connection.execute(
                    sa.text(
                        """
                        SELECT columns.standard_field_name, review_rows.row_state,
                               cells.base_value, cells.current_value,
                               cells.cell_revision
                        FROM version_table_columns AS columns
                        INNER JOIN version_rows AS review_rows
                            ON review_rows.version_id = columns.version_id
                           AND review_rows.id = :row_id
                        LEFT JOIN version_extension_cells AS cells
                            ON cells.version_id = review_rows.version_id
                           AND cells.row_id = review_rows.id
                           AND cells.column_id = columns.column_id
                        WHERE columns.version_id = :version_id
                          AND columns.column_id = :column_id
                        FOR UPDATE
                        """
                    ),
                    {
                        "version_id": command.head.version_id,
                        "row_id": command.row_id,
                        "column_id": command.column_id.bytes,
                    },
                )
                .mappings()
                .first()
            )
            if selected is None or selected["standard_field_name"] is not None:
                raise WorkbenchColumnNotFound(
                    "the selected extension column is unavailable"
                )
            if selected["row_state"] != "active":
                raise WorkbenchCellConflict("only an active row can be edited")
            stored_revision = (
                int(selected["cell_revision"])
                if selected["cell_revision"] is not None
                else 0
            )
            if stored_revision != command.expected_cell_revision:
                raise WorkbenchCellConflict("the extension cell revision changed")
            before_value = (
                str(selected["current_value"])
                if selected["current_value"] is not None
                else None
            )
            base_value = (
                str(selected["base_value"])
                if selected["base_value"] is not None
                else None
            )
            after_value = command.value
            if before_value == after_value:
                raise WorkbenchCellValueInvalid(
                    "the new extension value does not change the cell"
                )
            state = MySqlReviewRepository._advance_data_revision(
                connection,
                head=command.head,
                occurred_at=occurred_at,
            )
            next_cell_revision = stored_revision + 1
            if selected["cell_revision"] is None:
                connection.execute(
                    sa.text(
                        """
                        INSERT INTO version_extension_cells (
                            version_id, row_id, column_id, base_value,
                            current_value, cell_revision, updated_at
                        ) VALUES (
                            :version_id, :row_id, :column_id, NULL,
                            :current_value, :cell_revision, :updated_at
                        )
                        """
                    ),
                    {
                        "version_id": command.head.version_id,
                        "row_id": command.row_id,
                        "column_id": command.column_id.bytes,
                        "current_value": after_value,
                        "cell_revision": next_cell_revision,
                        "updated_at": timestamp,
                    },
                )
            else:
                updated = connection.execute(
                    sa.text(
                        """
                        UPDATE version_extension_cells
                        SET current_value = :current_value,
                            cell_revision = :next_cell_revision,
                            updated_at = :updated_at
                        WHERE version_id = :version_id
                          AND row_id = :row_id
                          AND column_id = :column_id
                          AND cell_revision = :expected_cell_revision
                        """
                    ),
                    {
                        "version_id": command.head.version_id,
                        "row_id": command.row_id,
                        "column_id": command.column_id.bytes,
                        "current_value": after_value,
                        "next_cell_revision": next_cell_revision,
                        "expected_cell_revision": command.expected_cell_revision,
                        "updated_at": timestamp,
                    },
                )
                if updated.rowcount != 1:
                    raise WorkbenchCellConflict(
                        "the extension cell changed before the edit"
                    )
            connection.execute(
                sa.text(
                    """
                    UPDATE version_rows
                    SET updated_at = :updated_at
                    WHERE version_id = :version_id AND id = :row_id
                    """
                ),
                {
                    "updated_at": timestamp,
                    "version_id": command.head.version_id,
                    "row_id": command.row_id,
                },
            )
            inserted = connection.execute(
                sa.text(
                    """
                    INSERT INTO extension_cell_changes (
                        operation_token, version_id, row_id, column_id,
                        data_revision, cell_revision, operation,
                        before_value, after_value, actor_user_id,
                        reason, undoes_change_id, occurred_at
                    ) VALUES (
                        :operation_token, :version_id, :row_id, :column_id,
                        :data_revision, :cell_revision, 'set',
                        :before_value, :after_value, :actor_user_id,
                        :reason, NULL, :occurred_at
                    )
                    """
                ),
                {
                    "operation_token": command.operation_token.bytes,
                    "version_id": command.head.version_id,
                    "row_id": command.row_id,
                    "column_id": command.column_id.bytes,
                    "data_revision": state.data_revision,
                    "cell_revision": next_cell_revision,
                    "before_value": before_value,
                    "after_value": after_value,
                    "actor_user_id": command.actor_user_id,
                    "reason": command.reason,
                    "occurred_at": timestamp,
                },
            )
            if inserted.lastrowid is None:
                raise WorkbenchMutationError(
                    "database did not return an extension change ID"
                )
            result = WorkbenchCellMutationResult(
                operation_token=command.operation_token,
                head=WorkbenchMutationHead(
                    dataset_id=state.dataset_id,
                    version_id=state.version_id,
                    status=state.status,
                    data_revision=state.data_revision,
                    review_revision=state.review_revision,
                    pointed_at=state.pointed_at,
                ),
                cell=WorkbenchMutationCell(
                    row_id=command.row_id,
                    column_id=command.column_id,
                    current=after_value,
                    base=base_value,
                    cell_revision=next_cell_revision,
                ),
                change_id=int(inserted.lastrowid),
            )
            self._store_result(
                connection,
                command=command,
                result=result,
                completed_at=timestamp,
            )
            return result

    def undo_latest_cell(
        self,
        command: UndoWorkbenchCellCommand,
        *,
        occurred_at: datetime,
    ) -> WorkbenchCellMutationResult:
        recovered = self._recover(command)
        if recovered is not None:
            return recovered
        timestamp = _mysql_datetime(occurred_at)
        with self._engine.begin() as connection:
            recovered = self._claim(
                connection,
                command=command,
                registered_at=timestamp,
            )
            if recovered is not None:
                return recovered
            actor = MySqlReviewRepository._load_actor(
                connection,
                actor_user_id=command.actor_user_id,
            )
            draft = MySqlReviewRepository._lock_active_head(connection, command.head)
            candidate = (
                connection.execute(
                    LATEST_UNDOABLE_CELL_SQL,
                    {
                        "version_id": command.head.version_id,
                        "actor_user_id": command.actor_user_id,
                    },
                )
                .mappings()
                .first()
            )
            if candidate is None:
                raise NothingToUndo("there is no still-current cell change to undo")
            row = MySqlReviewRepository._lock_review_row(
                connection,
                draft=draft,
                row_id=int(candidate["row_id"]),
            )
            if row.row_state != "active":
                raise NothingToUndo("the newest cell change is no longer undoable")
            state = MySqlReviewRepository._advance_data_revision(
                connection,
                head=command.head,
                occurred_at=occurred_at,
            )
            column_id = _uuid(candidate["column_id"])
            change_id = int(candidate["change_id"])
            if candidate["ledger_kind"] == "extension":
                before = (
                    str(candidate["after_value"])
                    if candidate["after_value"] is not None
                    else None
                )
                after = (
                    str(candidate["before_value"])
                    if candidate["before_value"] is not None
                    else None
                )
                locked_cell = (
                    connection.execute(
                        sa.text(
                            """
                            SELECT base_value, current_value, cell_revision
                            FROM version_extension_cells
                            WHERE version_id = :version_id
                              AND row_id = :row_id
                              AND column_id = :column_id
                            FOR UPDATE
                            """
                        ),
                        {
                            "version_id": command.head.version_id,
                            "row_id": row.row_id,
                            "column_id": column_id.bytes,
                        },
                    )
                    .mappings()
                    .first()
                )
                if locked_cell is None or int(locked_cell["cell_revision"]) != int(
                    candidate["cell_revision"]
                ):
                    raise WorkbenchCellConflict(
                        "the selected extension change is no longer current"
                    )
                next_cell_revision = int(locked_cell["cell_revision"]) + 1
                connection.execute(
                    sa.text(
                        """
                        UPDATE version_extension_cells
                        SET current_value = :current_value,
                            cell_revision = :cell_revision,
                            updated_at = :updated_at
                        WHERE version_id = :version_id
                          AND row_id = :row_id
                          AND column_id = :column_id
                        """
                    ),
                    {
                        "current_value": after,
                        "cell_revision": next_cell_revision,
                        "updated_at": timestamp,
                        "version_id": command.head.version_id,
                        "row_id": row.row_id,
                        "column_id": column_id.bytes,
                    },
                )
                inserted = connection.execute(
                    sa.text(
                        """
                        INSERT INTO extension_cell_changes (
                            operation_token, version_id, row_id, column_id,
                            data_revision, cell_revision, operation,
                            before_value, after_value, actor_user_id,
                            reason, undoes_change_id, occurred_at
                        ) VALUES (
                            :operation_token, :version_id, :row_id, :column_id,
                            :data_revision, :cell_revision, 'undo',
                            :before_value, :after_value, :actor_user_id,
                            :reason, :undoes_change_id, :occurred_at
                        )
                        """
                    ),
                    {
                        "operation_token": command.operation_token.bytes,
                        "version_id": command.head.version_id,
                        "row_id": row.row_id,
                        "column_id": column_id.bytes,
                        "data_revision": state.data_revision,
                        "cell_revision": next_cell_revision,
                        "before_value": before,
                        "after_value": after,
                        "actor_user_id": command.actor_user_id,
                        "reason": command.reason,
                        "undoes_change_id": change_id,
                        "occurred_at": timestamp,
                    },
                )
                if inserted.lastrowid is None:
                    raise WorkbenchMutationError(
                        "database did not return an undo change ID"
                    )
                result_change_id = int(inserted.lastrowid)
                base = (
                    str(locked_cell["base_value"])
                    if locked_cell["base_value"] is not None
                    else None
                )
            else:
                field_name = str(candidate["field_name"])
                current_values = dict(row.values)
                current = current_values[field_name]
                restored = decode_field_value(_json_payload(candidate["before_value"]))
                typed_table = (
                    "business_report_rows"
                    if draft.report_type == "business_report"
                    else "return_report_rows"
                )
                updated = connection.execute(
                    sa.text(
                        f"""
                        UPDATE {typed_table}
                        SET `{field_name}` = :after_value
                        WHERE version_id = :version_id
                          AND version_row_id = :row_id
                          AND `{field_name}` <=> :before_value
                        """
                    ),
                    {
                        "after_value": field_value_to_database(restored),
                        "version_id": command.head.version_id,
                        "row_id": row.row_id,
                        "before_value": field_value_to_database(current),
                    },
                )
                if updated.rowcount != 1:
                    raise WorkbenchCellConflict(
                        "the selected standard change is no longer current"
                    )
                inserted_event_id = MySqlReviewRepository._insert_data_change_event(
                    connection,
                    draft=draft,
                    state=state,
                    event_kind="field",
                    actor_user_id=actor.user_id,
                    reason=command.reason,
                    occurred_at=occurred_at,
                )
                connection.execute(
                    sa.text(
                        """
                        INSERT INTO field_changes (
                            id, version_id, row_id, field_name, operation,
                            before_value_json, after_value_json, event_kind,
                            restored_field_change_id,
                            restored_parent_version_id,
                            restored_source_row_id
                        ) VALUES (
                            :id, :version_id, :row_id, :field_name,
                            'restore_previous', :before_value_json,
                            :after_value_json, 'field', :restored_change_id,
                            NULL, NULL
                        )
                        """
                    ),
                    {
                        "id": inserted_event_id,
                        "version_id": command.head.version_id,
                        "row_id": row.row_id,
                        "field_name": field_name,
                        "before_value_json": json.dumps(
                            encode_field_value(current),
                            separators=(",", ":"),
                            sort_keys=True,
                        ),
                        "after_value_json": json.dumps(
                            encode_field_value(restored),
                            separators=(",", ":"),
                            sort_keys=True,
                        ),
                        "restored_change_id": change_id,
                    },
                )
                result_change_id = inserted_event_id
                next_cell_revision = state.data_revision
                before = str(current) if current is not None else None
                after = str(restored) if restored is not None else None
                base = None
            connection.execute(
                sa.text(
                    """
                    UPDATE version_rows SET updated_at = :updated_at
                    WHERE version_id = :version_id AND id = :row_id
                    """
                ),
                {
                    "updated_at": timestamp,
                    "version_id": command.head.version_id,
                    "row_id": row.row_id,
                },
            )
            result = WorkbenchCellMutationResult(
                operation_token=command.operation_token,
                head=WorkbenchMutationHead(
                    dataset_id=state.dataset_id,
                    version_id=state.version_id,
                    status=state.status,
                    data_revision=state.data_revision,
                    review_revision=state.review_revision,
                    pointed_at=state.pointed_at,
                ),
                cell=WorkbenchMutationCell(
                    row_id=row.row_id,
                    column_id=column_id,
                    current=after,
                    base=base,
                    cell_revision=next_cell_revision,
                ),
                change_id=result_change_id,
            )
            self._store_result(
                connection,
                command=command,
                result=result,
                completed_at=timestamp,
            )
            return result

    def _recover(
        self,
        command: WorkbenchOperationCommand,
    ) -> WorkbenchCellMutationResult | None:
        with self._engine.connect() as connection:
            return self._operation_result(
                connection,
                command=command,
                require_result=False,
            )

    def _claim(
        self,
        connection: Connection,
        *,
        command: WorkbenchOperationCommand,
        registered_at: datetime,
    ) -> WorkbenchCellMutationResult | None:
        savepoint = connection.begin_nested()
        try:
            connection.execute(
                sa.text(
                    """
                    INSERT INTO workbench_operation_tokens (
                        operation_token, operation_kind, operation_digest,
                        actor_user_id, expected_cell_revision, registered_at
                    ) VALUES (
                        :operation_token, :operation_kind, :operation_digest,
                        :actor_user_id, :expected_cell_revision, :registered_at
                    )
                    """
                ),
                {
                    "operation_token": command.operation_token.bytes,
                    "operation_kind": command.operation_kind,
                    "operation_digest": command.operation_digest,
                    "actor_user_id": command.actor_user_id,
                    "expected_cell_revision": getattr(
                        command,
                        "expected_cell_revision",
                        None,
                    ),
                    "registered_at": registered_at,
                },
            )
            savepoint.commit()
            return None
        except IntegrityError:
            savepoint.rollback()
        return self._operation_result(
            connection,
            command=command,
            require_result=True,
        )

    @staticmethod
    def _operation_result(
        connection: Connection,
        *,
        command: WorkbenchOperationCommand,
        require_result: bool,
    ) -> WorkbenchCellMutationResult | None:
        token = (
            connection.execute(
                sa.text(
                    """
                    SELECT operation_kind, operation_digest, actor_user_id
                    FROM workbench_operation_tokens
                    WHERE operation_token = :operation_token
                    LIMIT 1
                    """
                ),
                {"operation_token": command.operation_token.bytes},
            )
            .mappings()
            .first()
        )
        if token is None:
            return None
        digest = token["operation_digest"]
        if isinstance(digest, memoryview):
            digest = digest.tobytes()
        if (
            str(token["operation_kind"]) != command.operation_kind
            or int(token["actor_user_id"]) != command.actor_user_id
            or not isinstance(digest, bytes)
            or not hmac.compare_digest(digest, command.operation_digest)
        ):
            raise WorkbenchOperationConflict(
                "operation token is already bound to another workbench command"
            )
        row = (
            connection.execute(
                sa.text(
                    """
                    SELECT response_status_code, response_payload
                    FROM workbench_operation_results
                    WHERE operation_token = :operation_token
                    LIMIT 1
                    """
                ),
                {"operation_token": command.operation_token.bytes},
            )
            .mappings()
            .first()
        )
        if row is None:
            if require_result:
                raise WorkbenchMutationError(
                    "workbench operation has no recoverable result"
                )
            return None
        if int(row["response_status_code"]) != 200:
            raise WorkbenchCellConflict("stored workbench operation is a conflict")
        return _decode_mutation_result(row["response_payload"])

    @staticmethod
    def _store_result(
        connection: Connection,
        *,
        command: WorkbenchOperationCommand,
        result: WorkbenchCellMutationResult,
        completed_at: datetime,
    ) -> None:
        inserted = connection.execute(
            sa.text(
                """
                INSERT INTO workbench_operation_results (
                    operation_token, operation_kind, operation_digest,
                    actor_user_id, response_status_code,
                    response_payload, completed_at
                ) VALUES (
                    :operation_token, :operation_kind, :operation_digest,
                    :actor_user_id, 200, :response_payload, :completed_at
                )
                """
            ),
            {
                "operation_token": command.operation_token.bytes,
                "operation_kind": command.operation_kind,
                "operation_digest": command.operation_digest,
                "actor_user_id": command.actor_user_id,
                "response_payload": json.dumps(
                    _mutation_result_payload(result),
                    ensure_ascii=True,
                    separators=(",", ":"),
                    sort_keys=True,
                ),
                "completed_at": completed_at,
            },
        )
        if inserted.rowcount != 1:
            raise WorkbenchMutationError("workbench operation result was not stored")
