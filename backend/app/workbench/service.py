"""Application boundary for unified standard and extension cell writes."""

from __future__ import annotations

import re
from collections.abc import Callable
from datetime import UTC, datetime
from typing import Final, cast

import sqlalchemy as sa
from sqlalchemy.engine import Engine

from app.imports.types import ReportType
from app.review.repository import MySqlReviewRepository
from app.review.service import ReviewService
from app.review.types import SetFieldValueCommand
from app.validation.fields import FieldContractError, get_field_contract

from .commands import (
    SetWorkbenchCellCommand,
    UndoWorkbenchCellCommand,
    WorkbenchCellConflict,
    WorkbenchColumnNotFound,
)
from .repository import (
    MySqlWorkbenchMutationRepository,
    WorkbenchCellMutationResult,
    WorkbenchMutationCell,
    WorkbenchMutationHead,
)

_IDENTIFIER: Final = re.compile(r"[a-z][a-z0-9_]*", flags=re.ASCII)


def _utc_now() -> datetime:
    return datetime.now(UTC)


class WorkbenchCellMutationService:
    """Route one column identity through its authoritative storage model."""

    def __init__(
        self,
        engine: Engine,
        *,
        clock: Callable[[], datetime] = _utc_now,
    ) -> None:
        self._engine = engine
        self._clock = clock
        self._extension_repository = MySqlWorkbenchMutationRepository(engine)
        self._review_service = ReviewService(
            repository=MySqlReviewRepository(engine),
            clock=clock,
        )

    def set_cell(
        self,
        command: SetWorkbenchCellCommand,
    ) -> WorkbenchCellMutationResult:
        column = self._column(command)
        standard_field = column["standard_field_name"]
        if standard_field is None:
            return self._extension_repository.set_extension_cell(
                command,
                occurred_at=self._clock(),
            )
        field_name = str(standard_field)
        if _IDENTIFIER.fullmatch(field_name) is None:
            raise WorkbenchColumnNotFound("the standard field identity is invalid")
        report_type = cast(ReportType, str(column["report_type"]))
        ruleset_version = str(column["ruleset_version"])
        try:
            field = get_field_contract(report_type, ruleset_version, field_name)
        except FieldContractError as error:
            raise WorkbenchColumnNotFound(
                "the standard field contract is unavailable"
            ) from error
        if not field.editable:
            raise WorkbenchColumnNotFound("the selected standard field is read-only")
        review_command = SetFieldValueCommand(
            head=command.head,
            row_id=command.row_id,
            field_name=field_name,
            value=command.value,
            actor_user_id=command.actor_user_id,
            operation_token=command.operation_token,
            reason=command.reason,
        )
        if not self._review_token_exists(command):
            cell_revision = self._standard_cell_revision(
                version_id=command.head.version_id,
                row_id=command.row_id,
                field_name=field_name,
            )
            if cell_revision != command.expected_cell_revision:
                raise WorkbenchCellConflict("the standard cell revision changed")
        result = self._review_service.set_field_value(review_command)
        if (
            result.dataset_id is None
            or result.version_id is None
            or result.status is None
            or result.data_revision is None
            or result.review_revision is None
            or result.data_change_event_id is None
        ):
            raise RuntimeError("standard field mutation returned an invalid result")
        current, base, cell_revision = self._standard_cell(
            version_id=result.version_id,
            row_id=command.row_id,
            report_type=report_type,
            field_name=field_name,
        )
        return WorkbenchCellMutationResult(
            operation_token=command.operation_token,
            head=WorkbenchMutationHead(
                dataset_id=result.dataset_id,
                version_id=result.version_id,
                status=result.status,
                data_revision=result.data_revision,
                review_revision=result.review_revision,
                pointed_at=command.head.pointed_at,
            ),
            cell=WorkbenchMutationCell(
                row_id=command.row_id,
                column_id=command.column_id,
                current=current,
                base=base,
                cell_revision=cell_revision,
            ),
            change_id=result.data_change_event_id,
        )

    def undo_latest_cell(
        self,
        command: UndoWorkbenchCellCommand,
    ) -> WorkbenchCellMutationResult:
        return self._extension_repository.undo_latest_cell(
            command,
            occurred_at=self._clock(),
        )

    def _column(self, command: SetWorkbenchCellCommand) -> sa.RowMapping:
        with self._engine.connect() as connection:
            row = (
                connection.execute(
                    sa.text(
                        """
                        SELECT columns.standard_field_name,
                               versions.report_type, versions.ruleset_version
                        FROM version_table_columns AS columns
                        INNER JOIN dataset_versions AS versions
                            ON versions.id = columns.version_id
                        WHERE columns.version_id = :version_id
                          AND columns.column_id = :column_id
                        LIMIT 1
                        """
                    ),
                    {
                        "version_id": command.head.version_id,
                        "column_id": command.column_id.bytes,
                    },
                )
                .mappings()
                .first()
            )
        if row is None:
            raise WorkbenchColumnNotFound(
                "the selected column does not belong to this version"
            )
        if row["report_type"] not in {"business_report", "return_report"}:
            raise WorkbenchColumnNotFound("the selected report type is unsupported")
        return row

    def _review_token_exists(self, command: SetWorkbenchCellCommand) -> bool:
        with self._engine.connect() as connection:
            return (
                connection.scalar(
                    sa.text(
                        """
                        SELECT COUNT(*)
                        FROM review_operation_tokens
                        WHERE operation_token = :operation_token
                        """
                    ),
                    {"operation_token": command.operation_token.bytes},
                )
                or 0
            ) > 0

    def _standard_cell_revision(
        self,
        *,
        version_id: int,
        row_id: int,
        field_name: str,
    ) -> int:
        with self._engine.connect() as connection:
            value = connection.scalar(
                sa.text(
                    """
                    SELECT MAX(events.data_revision)
                    FROM field_changes AS changes
                    INNER JOIN data_change_events AS events
                        ON events.version_id = changes.version_id
                       AND events.id = changes.id
                    WHERE changes.version_id = :version_id
                      AND changes.row_id = :row_id
                      AND changes.field_name = :field_name
                    """
                ),
                {
                    "version_id": version_id,
                    "row_id": row_id,
                    "field_name": field_name,
                },
            )
        return int(value or 0)

    def _standard_cell(
        self,
        *,
        version_id: int,
        row_id: int,
        report_type: ReportType,
        field_name: str,
    ) -> tuple[str | None, str | None, int]:
        typed_table = (
            "business_report_rows"
            if report_type == "business_report"
            else "return_report_rows"
        )
        base_table = (
            "business_version_base_rows"
            if report_type == "business_report"
            else "return_version_base_rows"
        )
        with self._engine.connect() as connection:
            row = (
                connection.execute(
                    sa.text(
                        f"""
                        SELECT CAST(typed.`{field_name}` AS CHAR) AS current_value,
                               CAST(base_typed.`{field_name}` AS CHAR) AS base_value
                        FROM version_rows AS review_rows
                        INNER JOIN {typed_table} AS typed
                            ON typed.version_id = review_rows.version_id
                           AND typed.version_row_id = review_rows.id
                        LEFT JOIN version_base_rows AS base_rows
                            ON base_rows.version_id = review_rows.version_id
                           AND base_rows.id = review_rows.base_row_id
                        LEFT JOIN {base_table} AS base_typed
                            ON base_typed.version_id = base_rows.version_id
                           AND base_typed.version_base_row_id = base_rows.id
                        WHERE review_rows.version_id = :version_id
                          AND review_rows.id = :row_id
                        LIMIT 1
                        """
                    ),
                    {"version_id": version_id, "row_id": row_id},
                )
                .mappings()
                .first()
            )
        if row is None:
            raise WorkbenchCellConflict("the edited row is no longer available")
        current = (
            str(row["current_value"]) if row["current_value"] is not None else None
        )
        base = str(row["base_value"]) if row["base_value"] is not None else None
        return (
            current,
            base,
            self._standard_cell_revision(
                version_id=version_id,
                row_id=row_id,
                field_name=field_name,
            ),
        )
