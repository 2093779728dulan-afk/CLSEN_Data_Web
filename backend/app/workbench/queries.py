"""Aggregate, role-aware read model for the date data workbench."""

from __future__ import annotations

import json
import re
from datetime import UTC, date, datetime
from decimal import Decimal
from math import ceil
from types import MappingProxyType
from typing import Any, Final, Literal, cast
from uuid import UUID

import sqlalchemy as sa
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.auth.sessions import Principal
from app.imports.types import ReportType
from app.validation.fields import FieldContractError, get_report_field_contract
from app.workbench.repository import LATEST_UNDOABLE_CELL_SQL

type WorkbenchSource = Literal["draft", "published", "empty"]
type SortDirection = Literal["asc", "desc"]
type CellValue = str | int | None
type WorkbenchAction = Literal[
    "upload", "edit", "undo", "validate", "publish", "create_revision"
]

_REPORT_TYPES: Final[tuple[ReportType, ...]] = (
    "business_report",
    "return_report",
)
_ROW_TABLES: Final[MappingProxyType[ReportType, tuple[str, str]]] = MappingProxyType(
    {
        "business_report": (
            "business_report_rows",
            "business_version_base_rows",
        ),
        "return_report": (
            "return_report_rows",
            "return_version_base_rows",
        ),
    }
)
_VIEWER_REDACTED_FIELDS: Final[MappingProxyType[ReportType, frozenset[str]]] = (
    MappingProxyType(
        {
            "business_report": frozenset(),
            "return_report": frozenset(
                {"order_id", "license_plate_number", "customer_comments"}
            ),
        }
    )
)
_IDENTIFIER = re.compile(r"[a-z][a-z0-9_]*", flags=re.ASCII)


class WorkbenchQueryError(RuntimeError):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


class WorkbenchTabResponse(BaseModel):
    report_type: ReportType
    source: WorkbenchSource
    dataset_id: int | None = None
    version_id: int | None = None
    status: Literal["draft", "ready_for_publish", "published", "discarded"] | None = (
        None
    )


class WorkbenchHeadResponse(BaseModel):
    dataset_id: int
    version_id: int
    version_no: int
    status: Literal["draft", "ready_for_publish", "published", "discarded"]
    data_revision: int
    review_revision: int
    ruleset_version: str
    pointed_at: datetime


class WorkbenchColumnResponse(BaseModel):
    column_id: UUID
    source_header: str
    display_order: int
    value_kind: Literal["text", "integer", "decimal", "utc_datetime"]
    standard_field_name: str | None
    is_key: bool
    participates_in_statistics: bool
    editable: bool


class WorkbenchCellResponse(BaseModel):
    column_id: UUID
    current: CellValue
    base: CellValue
    cell_revision: int
    changed: bool
    editable: bool


class WorkbenchRowResponse(BaseModel):
    row_id: int
    row_ordinal: int
    row_state: Literal["active", "excluded", "deleted"]
    cells: list[WorkbenchCellResponse]


class WorkbenchPaginationResponse(BaseModel):
    page: int
    page_size: int
    total_rows: int
    total_pages: int


class WorkbenchValidationSummaryResponse(BaseModel):
    run_id: int
    data_revision: int
    status: Literal["succeeded", "failed"]
    result: Literal["passed", "failed", "error"]
    is_current: bool
    summary: dict[str, object]


class WorkbenchPermissionsResponse(BaseModel):
    can_upload: bool
    can_edit: bool
    can_undo: bool
    can_validate: bool
    can_publish: bool
    can_create_revision: bool


class DateWorkbenchResponse(BaseModel):
    report_date: date
    report_type: ReportType
    tabs: list[WorkbenchTabResponse]
    source: WorkbenchSource
    head: WorkbenchHeadResponse | None
    columns: list[WorkbenchColumnResponse]
    rows: list[WorkbenchRowResponse]
    validation: WorkbenchValidationSummaryResponse | None
    permissions: WorkbenchPermissionsResponse
    actions: list[WorkbenchAction]
    pending_upload_count: int = Field(ge=0)
    pagination: WorkbenchPaginationResponse


def _can_write(principal: Principal) -> bool:
    return not principal.roles.isdisjoint({"admin", "data_manager"})


def _binary_uuid(value: object) -> UUID:
    if isinstance(value, memoryview):
        value = value.tobytes()
    if isinstance(value, bytearray):
        value = bytes(value)
    if not isinstance(value, bytes) or len(value) != 16:
        raise RuntimeError("database returned an invalid workbench column ID")
    return UUID(bytes=value)


def _timestamp(value: object) -> datetime:
    if not isinstance(value, datetime):
        raise RuntimeError("database returned an invalid timestamp")
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


def _cell_value(value: object) -> CellValue:
    if value is None or isinstance(value, (str, int)):
        return value
    if isinstance(value, Decimal):
        return format(value, "f")
    if isinstance(value, datetime):
        return _timestamp(value).isoformat().replace("+00:00", "Z")
    raise RuntimeError("database returned an unsupported workbench cell value")


def _json_object(value: object) -> dict[str, object]:
    if isinstance(value, str):
        try:
            value = json.loads(value)
        except json.JSONDecodeError as error:
            raise RuntimeError("database returned invalid validation JSON") from error
    if not isinstance(value, dict):
        raise RuntimeError("database returned invalid validation JSON")
    return {str(key): item for key, item in value.items()}


def _selection(row: sa.RowMapping, *, writable: bool) -> tuple[WorkbenchSource, str]:
    if writable and row["draft_version_id"] is not None:
        return "draft", "draft"
    if row["published_version_id"] is not None:
        return "published", "published"
    return "empty", "empty"


def _head_value(row: sa.RowMapping, prefix: str, name: str) -> Any:
    return row[f"{prefix}_{name}"]


def _escaped_search(value: str) -> str:
    return (
        "%" + value.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_") + "%"
    )


def _safe_identifier(value: str) -> str:
    if _IDENTIFIER.fullmatch(value) is None:
        raise RuntimeError("unsafe frozen workbench field identifier")
    return value


class DateWorkbenchQueryService:
    """Read a complete workbench page from one request-scoped SQL session."""

    def __init__(self, database_session: Session) -> None:
        self._session = database_session

    def published_version_rows(
        self,
        *,
        head: WorkbenchHeadResponse,
        report_type: ReportType,
        page: int,
        page_size: int,
    ) -> dict[str, object]:
        """Read a fixed published version using viewer-safe, non-editable columns."""
        columns = self._load_columns(
            version_id=head.version_id,
            report_type=report_type,
            ruleset_version=head.ruleset_version,
            writable=False,
            source="published",
        )
        rows, pagination = self._load_rows(
            head=head,
            report_type=report_type,
            columns=columns,
            page=page,
            page_size=page_size,
            search=None,
            sort_column_id=None,
            direction="asc",
            changed_only=False,
            editable=False,
        )
        return {"columns": columns, "rows": rows, "pagination": pagination}

    def get(
        self,
        *,
        principal: Principal,
        report_date: date,
        report_type: ReportType,
        page: int,
        page_size: int,
        search: str | None,
        sort_column_id: UUID | None,
        direction: SortDirection,
        changed_only: bool,
    ) -> DateWorkbenchResponse:
        writable = _can_write(principal)
        state_rows = self._load_date_state(report_date)
        state_by_type = {
            cast(ReportType, str(row["report_type"])): row for row in state_rows
        }
        tabs = [
            self._tab(report_type=item, row=state_by_type.get(item), writable=writable)
            for item in _REPORT_TYPES
        ]
        selected_state = state_by_type.get(report_type)
        pending_upload_count = self._pending_upload_count() if writable else 0
        if selected_state is None:
            return self._empty_response(
                report_date=report_date,
                report_type=report_type,
                tabs=tabs,
                pending_upload_count=pending_upload_count,
                writable=writable,
                page=page,
                page_size=page_size,
            )
        source, prefix = _selection(selected_state, writable=writable)
        if source == "empty":
            return self._empty_response(
                report_date=report_date,
                report_type=report_type,
                tabs=tabs,
                pending_upload_count=pending_upload_count,
                writable=writable,
                page=page,
                page_size=page_size,
            )

        head = WorkbenchHeadResponse(
            dataset_id=int(selected_state["dataset_id"]),
            version_id=int(_head_value(selected_state, prefix, "version_id")),
            version_no=int(_head_value(selected_state, prefix, "version_no")),
            status=cast(
                Literal["draft", "ready_for_publish", "published", "discarded"],
                str(_head_value(selected_state, prefix, "status")),
            ),
            data_revision=int(_head_value(selected_state, prefix, "data_revision")),
            review_revision=int(_head_value(selected_state, prefix, "review_revision")),
            ruleset_version=str(_head_value(selected_state, prefix, "ruleset_version")),
            pointed_at=_timestamp(_head_value(selected_state, prefix, "pointed_at")),
        )
        columns = self._load_columns(
            version_id=head.version_id,
            report_type=report_type,
            ruleset_version=head.ruleset_version,
            writable=writable,
            source=source,
        )
        if sort_column_id is not None and all(
            column.column_id != sort_column_id for column in columns
        ):
            raise WorkbenchQueryError(
                "invalid_sort_column",
                "sort_column_id is not visible in this workbench.",
            )
        rows, pagination = self._load_rows(
            head=head,
            report_type=report_type,
            columns=columns,
            page=page,
            page_size=page_size,
            search=search.strip() if search and search.strip() else None,
            sort_column_id=sort_column_id,
            direction=direction,
            changed_only=changed_only,
            editable=writable and source == "draft",
        )
        permissions = self._permissions(
            source=source,
            writable=writable,
            can_undo=(
                writable
                and source == "draft"
                and self._session.execute(
                    LATEST_UNDOABLE_CELL_SQL,
                    {"version_id": head.version_id, "actor_user_id": principal.user_id},
                ).first()
                is not None
            ),
        )
        return DateWorkbenchResponse(
            report_date=report_date,
            report_type=report_type,
            tabs=tabs,
            source=source,
            head=head,
            columns=columns,
            rows=rows,
            validation=self._validation(head),
            permissions=permissions,
            actions=self._actions(permissions),
            pending_upload_count=pending_upload_count,
            pagination=pagination,
        )

    def _load_date_state(self, report_date: date) -> list[sa.RowMapping]:
        return list(
            self._session.execute(
                sa.text(
                    """
                    SELECT datasets.id AS dataset_id, datasets.report_type,
                           drafts.version_id AS draft_version_id,
                           draft_versions.version_no AS draft_version_no,
                           draft_versions.status AS draft_status,
                           draft_versions.data_revision AS draft_data_revision,
                           draft_versions.review_revision AS draft_review_revision,
                           draft_versions.ruleset_version AS draft_ruleset_version,
                           drafts.pointed_at AS draft_pointed_at,
                           publications.version_id AS published_version_id,
                           published_versions.version_no AS published_version_no,
                           published_versions.status AS published_status,
                           published_versions.data_revision AS published_data_revision,
                           published_versions.review_revision
                               AS published_review_revision,
                           published_versions.ruleset_version
                               AS published_ruleset_version,
                           publications.published_at AS published_pointed_at
                    FROM daily_datasets AS datasets
                    LEFT JOIN dataset_drafts AS drafts
                        ON drafts.dataset_id = datasets.id
                    LEFT JOIN dataset_versions AS draft_versions
                        ON draft_versions.dataset_id = drafts.dataset_id
                       AND draft_versions.id = drafts.version_id
                    LEFT JOIN dataset_publications AS publications
                        ON publications.dataset_id = datasets.id
                    LEFT JOIN dataset_versions AS published_versions
                        ON published_versions.dataset_id = publications.dataset_id
                       AND published_versions.id = publications.version_id
                    WHERE datasets.report_date = :report_date
                    ORDER BY datasets.report_type
                    """
                ),
                {"report_date": report_date},
            )
            .mappings()
            .all()
        )

    @staticmethod
    def _tab(
        *,
        report_type: ReportType,
        row: sa.RowMapping | None,
        writable: bool,
    ) -> WorkbenchTabResponse:
        if row is None:
            return WorkbenchTabResponse(report_type=report_type, source="empty")
        source, prefix = _selection(row, writable=writable)
        if source == "empty":
            return WorkbenchTabResponse(report_type=report_type, source="empty")
        return WorkbenchTabResponse(
            report_type=report_type,
            source=source,
            dataset_id=int(row["dataset_id"]),
            version_id=int(_head_value(row, prefix, "version_id")),
            status=cast(
                Literal["draft", "ready_for_publish", "published", "discarded"],
                str(_head_value(row, prefix, "status")),
            ),
        )

    def _pending_upload_count(self) -> int:
        value = self._session.scalar(
            sa.text(
                """
                SELECT COUNT(*)
                FROM import_batches
                WHERE confirmed_at IS NULL
                """
            )
        )
        return int(value or 0)

    def _load_columns(
        self,
        *,
        version_id: int,
        report_type: ReportType,
        ruleset_version: str,
        writable: bool,
        source: WorkbenchSource,
    ) -> list[WorkbenchColumnResponse]:
        try:
            contract = get_report_field_contract(report_type, ruleset_version)
        except FieldContractError as error:
            raise WorkbenchQueryError(
                "workbench_contract_unavailable",
                "The selected version has no supported field contract.",
            ) from error
        raw_columns = (
            self._session.execute(
                sa.text(
                    """
                    SELECT column_id, source_header, display_order, value_kind,
                           standard_field_name, is_key,
                           participates_in_statistics
                    FROM version_table_columns
                    WHERE version_id = :version_id
                    ORDER BY display_order
                    """
                ),
                {"version_id": version_id},
            )
            .mappings()
            .all()
        )
        if not raw_columns:
            raise WorkbenchQueryError(
                "workbench_schema_unavailable",
                "The selected version has no versioned table schema.",
            )
        redacted = _VIEWER_REDACTED_FIELDS[report_type] if not writable else frozenset()
        columns: list[WorkbenchColumnResponse] = []
        for row in raw_columns:
            standard_field = (
                str(row["standard_field_name"])
                if row["standard_field_name"] is not None
                else None
            )
            if not writable and (standard_field is None or standard_field in redacted):
                continue
            field_editable = (
                contract.field(standard_field).editable
                if standard_field is not None
                else True
            )
            columns.append(
                WorkbenchColumnResponse(
                    column_id=_binary_uuid(row["column_id"]),
                    source_header=str(row["source_header"]),
                    display_order=int(row["display_order"]),
                    value_kind=cast(
                        Literal["text", "integer", "decimal", "utc_datetime"],
                        str(row["value_kind"]),
                    ),
                    standard_field_name=standard_field,
                    is_key=bool(row["is_key"]),
                    participates_in_statistics=bool(row["participates_in_statistics"]),
                    editable=writable and source == "draft" and field_editable,
                )
            )
        return columns

    def _load_rows(
        self,
        *,
        head: WorkbenchHeadResponse,
        report_type: ReportType,
        columns: list[WorkbenchColumnResponse],
        page: int,
        page_size: int,
        search: str | None,
        sort_column_id: UUID | None,
        direction: SortDirection,
        changed_only: bool,
        editable: bool,
    ) -> tuple[list[WorkbenchRowResponse], WorkbenchPaginationResponse]:
        typed_table, base_typed_table = _ROW_TABLES[report_type]
        standard_columns = [
            column for column in columns if column.standard_field_name is not None
        ]
        extension_columns = [
            column for column in columns if column.standard_field_name is None
        ]
        standard_fields = [
            _safe_identifier(cast(str, column.standard_field_name))
            for column in standard_columns
        ]
        parameters: dict[str, object] = {"version_id": head.version_id}
        joins = ""
        search_parts: list[str] = []
        if search is not None:
            parameters["search"] = _escaped_search(search)
            search_parts.extend(
                f"CAST(typed.`{field}` AS CHAR) LIKE :search ESCAPE '\\\\'"
                for field in standard_fields
            )
            if extension_columns:
                search_parts.append(
                    "EXISTS (SELECT 1 FROM version_extension_cells AS search_cells "
                    "WHERE search_cells.version_id = review_rows.version_id "
                    "AND search_cells.row_id = review_rows.id "
                    "AND search_cells.current_value LIKE :search ESCAPE '\\\\')"
                )
        changed_parts = [
            f"NOT (typed.`{field}` <=> base_typed.`{field}`)"
            for field in standard_fields
        ]
        if extension_columns:
            changed_parts.append(
                "EXISTS (SELECT 1 FROM version_extension_cells AS changed_cells "
                "WHERE changed_cells.version_id = review_rows.version_id "
                "AND changed_cells.row_id = review_rows.id "
                "AND NOT (changed_cells.current_value <=> changed_cells.base_value))"
            )
        where_parts = [
            "review_rows.version_id = :version_id",
            "review_rows.row_state <> 'deleted'",
        ]
        if search_parts:
            where_parts.append("(" + " OR ".join(search_parts) + ")")
        if changed_only:
            where_parts.append(
                "(" + " OR ".join(changed_parts) + ")" if changed_parts else "FALSE"
            )

        sort_column = next(
            (
                column
                for column in columns
                if sort_column_id is not None and column.column_id == sort_column_id
            ),
            None,
        )
        if sort_column is None:
            order_expression = "review_rows.row_ordinal"
        elif sort_column.standard_field_name is not None:
            order_expression = (
                f"typed.`{_safe_identifier(sort_column.standard_field_name)}`"
            )
        else:
            joins = (
                " LEFT JOIN version_extension_cells AS sort_cells"
                " ON sort_cells.version_id = review_rows.version_id"
                " AND sort_cells.row_id = review_rows.id"
                " AND sort_cells.column_id = :sort_column_id"
            )
            parameters["sort_column_id"] = sort_column.column_id.bytes
            order_expression = "sort_cells.current_value"
        order_direction = "DESC" if direction == "desc" else "ASC"
        common_from = f"""
            FROM version_rows AS review_rows
            INNER JOIN {typed_table} AS typed
                ON typed.version_id = review_rows.version_id
               AND typed.version_row_id = review_rows.id
            LEFT JOIN version_base_rows AS base_rows
                ON base_rows.version_id = review_rows.version_id
               AND base_rows.id = review_rows.base_row_id
            LEFT JOIN {base_typed_table} AS base_typed
                ON base_typed.version_id = base_rows.version_id
               AND base_typed.version_base_row_id = base_rows.id
            {joins}
            WHERE {" AND ".join(where_parts)}
        """
        total_rows = int(
            self._session.scalar(sa.text("SELECT COUNT(*) " + common_from), parameters)
            or 0
        )
        selected_values = ", ".join(
            [f"typed.`{field}` AS `current_{field}`" for field in standard_fields]
            + [f"base_typed.`{field}` AS `base_{field}`" for field in standard_fields]
        )
        value_suffix = ", " + selected_values if selected_values else ""
        row_parameters = {
            **parameters,
            "limit": page_size,
            "offset": (page - 1) * page_size,
        }
        raw_rows = (
            self._session.execute(
                sa.text(
                    "SELECT review_rows.id AS row_id, review_rows.row_ordinal, "
                    "review_rows.row_state"
                    + value_suffix
                    + common_from
                    + f" ORDER BY {order_expression} {order_direction}, "
                    "review_rows.row_ordinal ASC, review_rows.id ASC "
                    "LIMIT :limit OFFSET :offset"
                ),
                row_parameters,
            )
            .mappings()
            .all()
        )
        row_ids = [int(row["row_id"]) for row in raw_rows]
        extension_values = self._extension_values(
            version_id=head.version_id,
            row_ids=row_ids,
        )
        standard_revisions = self._standard_revisions(
            version_id=head.version_id,
            row_ids=row_ids,
        )
        responses: list[WorkbenchRowResponse] = []
        for raw_row in raw_rows:
            row_id = int(raw_row["row_id"])
            cells: list[WorkbenchCellResponse] = []
            for column in columns:
                if column.standard_field_name is not None:
                    field = column.standard_field_name
                    current = _cell_value(raw_row[f"current_{field}"])
                    base = _cell_value(raw_row[f"base_{field}"])
                    revision = standard_revisions.get((row_id, field), 0)
                else:
                    current, base, revision = extension_values.get(
                        (row_id, column.column_id),
                        (None, None, 0),
                    )
                cells.append(
                    WorkbenchCellResponse(
                        column_id=column.column_id,
                        current=current,
                        base=base,
                        cell_revision=revision,
                        changed=current != base,
                        editable=editable and column.editable,
                    )
                )
            responses.append(
                WorkbenchRowResponse(
                    row_id=row_id,
                    row_ordinal=int(raw_row["row_ordinal"]),
                    row_state=cast(
                        Literal["active", "excluded", "deleted"],
                        str(raw_row["row_state"]),
                    ),
                    cells=cells,
                )
            )
        return responses, WorkbenchPaginationResponse(
            page=page,
            page_size=page_size,
            total_rows=total_rows,
            total_pages=ceil(total_rows / page_size) if total_rows else 0,
        )

    def _extension_values(
        self,
        *,
        version_id: int,
        row_ids: list[int],
    ) -> dict[tuple[int, UUID], tuple[CellValue, CellValue, int]]:
        if not row_ids:
            return {}
        parameters: dict[str, object] = {"version_id": version_id}
        placeholders: list[str] = []
        for index, row_id in enumerate(row_ids):
            key = f"row_id_{index}"
            placeholders.append(f":{key}")
            parameters[key] = row_id
        rows = (
            self._session.execute(
                sa.text(
                    "SELECT row_id, column_id, current_value, base_value, "
                    "cell_revision FROM version_extension_cells "
                    "WHERE version_id = :version_id AND row_id IN ("
                    + ", ".join(placeholders)
                    + ")"
                ),
                parameters,
            )
            .mappings()
            .all()
        )
        return {
            (int(row["row_id"]), _binary_uuid(row["column_id"])): (
                _cell_value(row["current_value"]),
                _cell_value(row["base_value"]),
                int(row["cell_revision"]),
            )
            for row in rows
        }

    def _standard_revisions(
        self,
        *,
        version_id: int,
        row_ids: list[int],
    ) -> dict[tuple[int, str], int]:
        if not row_ids:
            return {}
        parameters: dict[str, object] = {"version_id": version_id}
        placeholders: list[str] = []
        for index, row_id in enumerate(row_ids):
            key = f"revision_row_id_{index}"
            placeholders.append(f":{key}")
            parameters[key] = row_id
        rows = (
            self._session.execute(
                sa.text(
                    "SELECT changes.row_id, changes.field_name, "
                    "MAX(events.data_revision) AS cell_revision "
                    "FROM field_changes AS changes "
                    "INNER JOIN data_change_events AS events "
                    "ON events.version_id = changes.version_id "
                    "AND events.id = changes.id "
                    "WHERE changes.version_id = :version_id "
                    "AND changes.row_id IN ("
                    + ", ".join(placeholders)
                    + ") GROUP BY changes.row_id, changes.field_name"
                ),
                parameters,
            )
            .mappings()
            .all()
        )
        return {
            (int(row["row_id"]), str(row["field_name"])): int(row["cell_revision"])
            for row in rows
        }

    def _validation(
        self,
        head: WorkbenchHeadResponse,
    ) -> WorkbenchValidationSummaryResponse | None:
        row = (
            self._session.execute(
                sa.text(
                    """
                    SELECT id, data_revision, status, result, summary_json
                    FROM validation_runs
                    WHERE version_id = :version_id AND run_type = 'full'
                    ORDER BY id DESC
                    LIMIT 1
                    """
                ),
                {"version_id": head.version_id},
            )
            .mappings()
            .first()
        )
        if row is None:
            return None
        data_revision = int(row["data_revision"])
        return WorkbenchValidationSummaryResponse(
            run_id=int(row["id"]),
            data_revision=data_revision,
            status=cast(Literal["succeeded", "failed"], str(row["status"])),
            result=cast(Literal["passed", "failed", "error"], str(row["result"])),
            is_current=data_revision == head.data_revision,
            summary=_json_object(row["summary_json"]),
        )

    @staticmethod
    def _permissions(
        *,
        source: WorkbenchSource,
        writable: bool,
        can_undo: bool = False,
    ) -> WorkbenchPermissionsResponse:
        draft = writable and source == "draft"
        return WorkbenchPermissionsResponse(
            can_upload=writable and source == "empty",
            can_edit=draft,
            can_undo=draft and can_undo,
            can_validate=draft,
            can_publish=draft,
            can_create_revision=writable and source == "published",
        )

    @staticmethod
    def _actions(
        permissions: WorkbenchPermissionsResponse,
    ) -> list[WorkbenchAction]:
        actions: list[WorkbenchAction] = []
        for action, allowed in (
            ("upload", permissions.can_upload),
            ("edit", permissions.can_edit),
            ("undo", permissions.can_undo),
            ("validate", permissions.can_validate),
            ("publish", permissions.can_publish),
            ("create_revision", permissions.can_create_revision),
        ):
            if allowed:
                actions.append(cast(WorkbenchAction, action))
        return actions

    @classmethod
    def _empty_response(
        cls,
        *,
        report_date: date,
        report_type: ReportType,
        tabs: list[WorkbenchTabResponse],
        pending_upload_count: int,
        writable: bool,
        page: int,
        page_size: int,
    ) -> DateWorkbenchResponse:
        permissions = cls._permissions(source="empty", writable=writable)
        return DateWorkbenchResponse(
            report_date=report_date,
            report_type=report_type,
            tabs=tabs,
            source="empty",
            head=None,
            columns=[],
            rows=[],
            validation=None,
            permissions=permissions,
            actions=cls._actions(permissions),
            pending_upload_count=pending_upload_count,
            pagination=WorkbenchPaginationResponse(
                page=page,
                page_size=page_size,
                total_rows=0,
                total_pages=0,
            ),
        )
