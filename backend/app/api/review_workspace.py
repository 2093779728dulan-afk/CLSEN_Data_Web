"""Read model for the administrator and data-manager review workspace."""

from __future__ import annotations

import json
import re
from collections import defaultdict
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, date, datetime
from types import MappingProxyType
from typing import Annotated, Any, Final, Literal, cast
from uuid import UUID

import sqlalchemy as sa
from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.api.dependencies import get_database_session, require_roles
from app.api.errors import ApiError
from app.auth.sessions import Principal
from app.imports.types import ReportType
from app.validation.codec import decode_field_value, encode_field_value
from app.validation.fields import (
    FieldContractError,
    FieldValue,
    FieldValueError,
    ReportFieldContract,
    as_field_value,
    get_report_field_contract,
    validate_field_value,
)

router = APIRouter(prefix="/api/drafts", tags=["review"])
_Manager = Annotated[Principal, Depends(require_roles("admin", "data_manager"))]
_DatabaseSession = Annotated[
    Session,
    Depends(get_database_session, scope="function"),
]
_DraftStatus = Literal["draft", "ready_for_publish"]
_RowState = Literal["active", "excluded", "deleted"]
_ValueKind = Literal["text", "integer", "decimal", "utc_datetime", "null"]
_IDENTIFIER_PATTERN = re.compile(r"[a-z][a-z0-9_]*", flags=re.ASCII)
_ROW_TABLES: Final[Mapping[ReportType, tuple[str, str, str]]] = MappingProxyType(
    {
        "business_report": (
            "business_report_rows",
            "business_version_base_rows",
            "business_parse_baseline_rows",
        ),
        "return_report": (
            "return_report_rows",
            "return_version_base_rows",
            "return_parse_baseline_rows",
        ),
    }
)


class TypedFieldValueResponse(BaseModel):
    type: _ValueKind
    value: str | int | None


class FieldContractResponse(BaseModel):
    name: str
    kind: Literal["text", "integer", "decimal", "utc_datetime"]
    nullable: bool
    editable: bool
    required_on_add: bool
    included_in_totals: bool
    max_length: int | None
    precision: int | None
    scale: int | None
    ascii_only: bool


class DraftWorkspaceHeadResponse(BaseModel):
    dataset_id: int
    version_id: int
    version_no: int
    status: _DraftStatus
    data_revision: int
    review_revision: int
    pointed_at: datetime


class ParentRestoreOptionResponse(BaseModel):
    parent_version_id: int
    value: TypedFieldValueResponse


class SourceRestoreOptionResponse(BaseModel):
    source_batch_id: int
    parsed_source_row_id: int
    value: TypedFieldValueResponse


class SourceBatchResponse(BaseModel):
    """A non-sensitive input-batch identity valid for manual row provenance."""

    batch_id: int


class FieldChangeResponse(BaseModel):
    id: int
    data_revision: int
    operation: Literal[
        "set",
        "restore_source",
        "restore_parent",
        "restore_previous",
    ]
    before: TypedFieldValueResponse
    after: TypedFieldValueResponse
    restored_field_change_id: int | None
    restored_parent_version_id: int | None
    restored_source_row_id: int | None
    actor_user_id: int
    actor_username: str
    reason: str
    occurred_at: datetime


class LatestNoteResponse(BaseModel):
    note_key: str
    note_id: int
    revision_number: int
    target_type: Literal["version", "row", "field"]
    row_id: int | None
    field_name: str | None
    visibility: Literal["internal", "viewer_visible"]
    body: str
    author_user_id: int
    author_username: str
    review_revision: int
    created_at: datetime


class CellComparisonResponse(BaseModel):
    field_name: str
    current: TypedFieldValueResponse
    base: TypedFieldValueResponse | None
    source: TypedFieldValueResponse | None
    changed_from_base: bool
    changed_from_source: bool
    parent_restore_options: list[ParentRestoreOptionResponse]
    source_restore_option: SourceRestoreOptionResponse | None
    history: list[FieldChangeResponse]
    notes: list[LatestNoteResponse]


class RowChangeResponse(BaseModel):
    id: int
    data_revision: int
    operation: Literal["add", "exclude", "restore", "delete"]
    source_batch_id: int | None
    before: dict[str, object]
    after: dict[str, object]
    actor_user_id: int
    actor_username: str
    reason: str
    occurred_at: datetime


class ReviewRowResponse(BaseModel):
    row_id: int
    logical_row_id: UUID
    row_ordinal: int
    row_state: _RowState
    base_row_id: int | None
    original_parsed_source_row_id: int | None
    cells: list[CellComparisonResponse]
    history: list[RowChangeResponse]
    notes: list[LatestNoteResponse]


class IssueReviewStateResponse(BaseModel):
    state: Literal["open", "acknowledged", "resolved"]
    event_id: int | None
    event_type: Literal["acknowledge", "resolve", "reopen"] | None
    actor_user_id: int | None
    actor_username: str | None
    comment: str | None
    occurred_at: datetime | None


class ValidationIssueResponse(BaseModel):
    id: int
    row_id: int | None
    severity: Literal["warning", "blocking"]
    rule_code: str
    field_name: str | None
    message: str
    source_value: object | None
    processed_value: object | None
    details: object | None
    requires_note: bool
    review: IssueReviewStateResponse
    created_at: datetime


class FullValidationResponse(BaseModel):
    id: int
    data_revision: int
    ruleset_version: str
    status: Literal["succeeded", "failed"]
    result: Literal["passed", "failed", "error"]
    data_digest: str
    summary: dict[str, object]
    started_at: datetime
    completed_at: datetime
    is_current: bool
    issues: list[ValidationIssueResponse]


class WorkspacePaginationResponse(BaseModel):
    page: int
    page_size: int
    total_rows: int
    total_pages: int


class PublicationPointerResponse(BaseModel):
    version_id: int | None
    published_at: datetime | None


class PublishedMoveContextResponse(BaseModel):
    revision_operation_token: UUID
    source_dataset_id: int
    source_report_date: date
    source_publication: PublicationPointerResponse
    target_publication: PublicationPointerResponse


@dataclass(frozen=True, slots=True)
class _PublishedMoveLedger:
    revision_operation_token: UUID
    source_dataset_id: int
    source_version_id: int
    target_version_id: int


class ReviewWorkspaceResponse(BaseModel):
    head: DraftWorkspaceHeadResponse
    report_date: date
    report_type: ReportType
    ruleset_version: str
    source_batches: list[SourceBatchResponse]
    fields: list[FieldContractResponse]
    rows: list[ReviewRowResponse]
    version_notes: list[LatestNoteResponse]
    latest_full_validation: FullValidationResponse | None
    publication_mode: Literal["ordinary", "published_move"]
    published_move: PublishedMoveContextResponse | None
    pagination: WorkspacePaginationResponse


def _utc_timestamp(value: object) -> datetime:
    if not isinstance(value, datetime):
        raise RuntimeError("database returned an invalid timestamp")
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


def _load_source_batches(
    database_session: Session,
    *,
    version_id: int,
) -> list[SourceBatchResponse]:
    rows = database_session.execute(
        sa.text(
            """
            SELECT batch_id
            FROM version_input_batches
            WHERE version_id = :version_id
            ORDER BY input_ordinal, batch_id
            """
        ),
        {"version_id": version_id},
    ).scalars()
    return [SourceBatchResponse(batch_id=int(batch_id)) for batch_id in rows]


def _optional_timestamp(value: object) -> datetime | None:
    if value is None:
        return None
    return _utc_timestamp(value)


def _json_value(value: object) -> object:
    if isinstance(value, str):
        return cast(object, json.loads(value))
    return value


def _json_object(value: object) -> dict[str, object]:
    decoded = _json_value(value)
    if not isinstance(decoded, dict):
        raise RuntimeError("database returned an invalid JSON object")
    return {str(key): item for key, item in decoded.items()}


def _binary(value: object, *, length: int) -> bytes:
    if isinstance(value, memoryview):
        raw = value.tobytes()
    elif isinstance(value, bytearray):
        raw = bytes(value)
    elif isinstance(value, bytes):
        raw = value
    else:
        raise RuntimeError("database returned an invalid binary value")
    if len(raw) != length:
        raise RuntimeError("database returned an invalid binary value length")
    return raw


def _database_field_value(value: object) -> FieldValue:
    if isinstance(value, datetime):
        value = _utc_timestamp(value)
    return as_field_value(value)


def _typed_value(
    *,
    report_type: ReportType,
    ruleset_version: str,
    field_name: str,
    value: object,
) -> TypedFieldValueResponse:
    try:
        canonical = validate_field_value(
            report_type,
            ruleset_version,
            field_name,
            _database_field_value(value),
        )
        encoded = encode_field_value(canonical)
    except FieldValueError as error:
        raise RuntimeError("stored value violates the frozen field contract") from error
    return TypedFieldValueResponse(
        type=cast(_ValueKind, encoded["type"]),
        value=cast(str | int | None, encoded["value"]),
    )


def _event_typed_value(
    *,
    report_type: ReportType,
    ruleset_version: str,
    field_name: str,
    payload: object,
) -> TypedFieldValueResponse:
    try:
        decoded = decode_field_value(_json_value(payload))
    except FieldValueError as error:
        raise RuntimeError("stored field history value is invalid") from error
    return _typed_value(
        report_type=report_type,
        ruleset_version=ruleset_version,
        field_name=field_name,
        value=decoded,
    )


def _contract_response(contract: ReportFieldContract) -> list[FieldContractResponse]:
    return [
        FieldContractResponse(
            name=field.name,
            kind=field.kind.value,
            nullable=field.nullable,
            editable=field.editable,
            required_on_add=field.required_on_add,
            included_in_totals=field.included_in_totals,
            max_length=field.max_length,
            precision=field.precision,
            scale=field.scale,
            ascii_only=field.ascii_only,
        )
        for field in contract.fields
    ]


def _safe_selected_columns(
    alias: str,
    prefix: str,
    contract: ReportFieldContract,
) -> str:
    if _IDENTIFIER_PATTERN.fullmatch(alias) is None:
        raise RuntimeError("unsafe SQL alias")
    columns: list[str] = []
    for field_name in contract.field_names:
        if _IDENTIFIER_PATTERN.fullmatch(field_name) is None:
            raise RuntimeError("unsafe frozen field contract")
        columns.append(f"{alias}.`{field_name}` AS `{prefix}{field_name}`")
    return ", ".join(columns)


def _row_tables(report_type: ReportType) -> tuple[str, str, str]:
    tables = _ROW_TABLES[report_type]
    if any(_IDENTIFIER_PATTERN.fullmatch(table) is None for table in tables):
        raise RuntimeError("unsafe frozen row table contract")
    return tables


def _head(
    database_session: Session,
    *,
    version_id: int,
) -> tuple[sa.RowMapping, ReportType, ReportFieldContract]:
    row = (
        database_session.execute(
            sa.text(
                """
            SELECT versions.dataset_id, versions.id AS version_id,
                   versions.version_no, versions.status,
                   versions.data_revision, versions.review_revision,
                   versions.ruleset_version, drafts.pointed_at,
                   datasets.report_date, datasets.report_type
            FROM dataset_drafts AS drafts
            INNER JOIN dataset_versions AS versions
                ON versions.dataset_id = drafts.dataset_id
               AND versions.id = drafts.version_id
            INNER JOIN daily_datasets AS datasets
                ON datasets.id = versions.dataset_id
               AND datasets.report_type = versions.report_type
            WHERE drafts.version_id = :version_id
              AND versions.id = :version_id
              AND versions.status IN ('draft', 'ready_for_publish')
              AND versions.sealed_at IS NULL
            LIMIT 1
            """
            ),
            {"version_id": version_id},
        )
        .mappings()
        .first()
    )
    if row is None:
        raise ApiError(404, "draft_not_found", "The requested draft was not found.")
    raw_report_type = str(row["report_type"])
    if raw_report_type not in {"business_report", "return_report"}:
        raise ApiError(
            409,
            "draft_contract_unavailable",
            "The draft has no supported review contract.",
        )
    report_type = cast(ReportType, raw_report_type)
    try:
        contract = get_report_field_contract(
            report_type,
            str(row["ruleset_version"]),
        )
    except FieldContractError as error:
        raise ApiError(
            409,
            "draft_contract_unavailable",
            "The draft has no supported review contract.",
        ) from error
    return row, report_type, contract


def _published_move_context_conflict() -> ApiError:
    return ApiError(
        409,
        "published_move_context_conflict",
        "The published move context conflicts with current publication state.",
    )


def _load_published_move_ledger(
    database_session: Session,
    *,
    version_id: int,
    target_dataset_id: int,
) -> _PublishedMoveLedger | None:
    result_rows = (
        database_session.execute(
            sa.text(
                """
                SELECT operation_token, operation_kind, result_kind,
                       result_dataset_id, result_version_id, result_status,
                       result_data_revision, result_review_revision,
                       source_dataset_id, source_version_id,
                       published_move_source_parent_version_id,
                       published_move_source_lineage_type
                FROM draft_operation_results
                WHERE result_version_id = :version_id
                  AND (
                      (operation_kind = 'create_published_move_revision'
                       AND result_kind = 'move_revision_created')
                      OR
                      (operation_kind = 'reassign_date'
                       AND result_kind = 'reassigned')
                  )
                ORDER BY completed_at, operation_token
                """
            ),
            {"version_id": version_id},
        )
        .mappings()
        .all()
    )
    moved_source_rows = (
        database_session.execute(
            sa.text(
                """
                SELECT parent_version_id
                FROM version_parent_versions
                WHERE child_version_id = :version_id
                  AND lineage_type = 'moved_source'
                ORDER BY parent_version_id
                """
            ),
            {"version_id": version_id},
        )
        .scalars()
        .all()
    )
    if not result_rows and not moved_source_rows:
        return None
    if len(result_rows) != 1 or len(moved_source_rows) != 1:
        raise _published_move_context_conflict()

    result = result_rows[0]
    try:
        result_dataset_id = int(result["result_dataset_id"])
        result_version_id = int(result["result_version_id"])
        result_data_revision = int(result["result_data_revision"])
        result_review_revision = int(result["result_review_revision"])
        source_dataset_id = int(result["source_dataset_id"])
        source_version_id = int(result["source_version_id"])
        moved_source_parent_version_id = int(moved_source_rows[0])
    except (RuntimeError, TypeError, ValueError, OverflowError) as error:
        raise _published_move_context_conflict() from error
    common_matches = (
        result["result_status"] == "draft"
        and result_dataset_id == target_dataset_id
        and result_version_id == version_id
        and result_data_revision == 0
        and result_review_revision == 0
        and source_dataset_id != target_dataset_id
        and moved_source_parent_version_id == source_version_id
    )
    if result["operation_kind"] == "reassign_date":
        if not (
            common_matches
            and result["result_kind"] == "reassigned"
            and result["published_move_source_parent_version_id"] is None
            and result["published_move_source_lineage_type"] is None
        ):
            raise _published_move_context_conflict()
        return None
    try:
        revision_operation_token = UUID(
            bytes=_binary(result["operation_token"], length=16)
        )
        source_parent_version_id = int(
            result["published_move_source_parent_version_id"]
        )
    except (RuntimeError, TypeError, ValueError, OverflowError) as error:
        raise _published_move_context_conflict() from error
    if (
        result["operation_kind"] != "create_published_move_revision"
        or result["result_kind"] != "move_revision_created"
        or not common_matches
        or result["published_move_source_lineage_type"] != "moved_source"
        or source_parent_version_id != source_version_id
    ):
        raise _published_move_context_conflict()
    return _PublishedMoveLedger(
        revision_operation_token=revision_operation_token,
        source_dataset_id=source_dataset_id,
        source_version_id=source_version_id,
        target_version_id=result_version_id,
    )


def _load_published_move_context(
    database_session: Session,
    *,
    ledger: _PublishedMoveLedger,
    target_dataset_id: int,
    target_report_date: date,
    target_report_type: ReportType,
) -> PublishedMoveContextResponse:
    source_dataset_id = ledger.source_dataset_id
    source_version_id = ledger.source_version_id
    audit_rows = (
        database_session.execute(
            sa.text(
                """
                SELECT redacted_payload
                FROM audit_events
                WHERE request_id = :request_id
                  AND event_type = 'published_move_revision_created'
                  AND object_type = 'dataset_version'
                  AND object_id = :version_id
                ORDER BY id
                LIMIT 2
                """
            ),
            {
                "request_id": str(ledger.revision_operation_token),
                "version_id": str(ledger.target_version_id),
            },
        )
        .scalars()
        .all()
    )
    if len(audit_rows) != 1:
        raise _published_move_context_conflict()
    try:
        frozen = _json_object(audit_rows[0])
        frozen_schema_version = int(
            cast(Any, frozen["published_move_context_schema_version"])
        )
        frozen_source_dataset_id = int(cast(Any, frozen["source_dataset_id"]))
        frozen_lineage_source_version_id = int(cast(Any, frozen["source_version_id"]))
        frozen_source_version_id = int(
            cast(Any, frozen["source_publication_version_id"])
        )
        frozen_target_dataset_id = int(cast(Any, frozen["target_dataset_id"]))
        frozen_draft_version_id = int(cast(Any, frozen["target_version_id"]))
        raw_frozen_source_published_at = frozen["source_publication_published_at"]
        raw_frozen_target_version_id = frozen["target_publication_version_id"]
        raw_frozen_target_published_at = frozen["target_publication_published_at"]
        if not isinstance(raw_frozen_source_published_at, str):
            raise ValueError("source publication timestamp is not text")
        frozen_source_published_at = _utc_timestamp(
            datetime.fromisoformat(
                raw_frozen_source_published_at.replace("Z", "+00:00")
            )
        )
        frozen_target_version_id = (
            int(cast(Any, raw_frozen_target_version_id))
            if raw_frozen_target_version_id is not None
            else None
        )
        if raw_frozen_target_published_at is not None and not isinstance(
            raw_frozen_target_published_at,
            str,
        ):
            raise ValueError("target publication timestamp is not text")
        frozen_target_published_at = (
            _utc_timestamp(
                datetime.fromisoformat(
                    raw_frozen_target_published_at.replace("Z", "+00:00")
                )
            )
            if raw_frozen_target_published_at is not None
            else None
        )
    except (
        KeyError,
        RuntimeError,
        TypeError,
        ValueError,
        OverflowError,
    ) as error:
        raise _published_move_context_conflict() from error
    if (
        frozen_schema_version != 1
        or frozen_source_dataset_id != source_dataset_id
        or frozen_lineage_source_version_id != source_version_id
        or frozen_source_version_id != source_version_id
        or frozen_target_dataset_id != target_dataset_id
        or frozen_draft_version_id != ledger.target_version_id
        or (frozen_target_version_id is None) != (frozen_target_published_at is None)
    ):
        raise _published_move_context_conflict()

    state = (
        database_session.execute(
            sa.text(
                """
                SELECT source_datasets.report_date AS source_report_date,
                       source_datasets.report_type AS source_report_type,
                       source_datasets.site_id AS source_site_id,
                       source_versions.dataset_id AS source_version_dataset_id,
                       source_versions.status AS source_version_status,
                       target_datasets.report_date AS target_report_date,
                       target_datasets.report_type AS target_report_type,
                       target_datasets.site_id AS target_site_id,
                       source_publications.version_id AS source_publication_version_id,
                       source_publications.published_at AS source_published_at,
                       target_publications.version_id AS target_publication_version_id,
                       target_publications.published_at AS target_published_at
                FROM daily_datasets AS source_datasets
                INNER JOIN dataset_versions AS source_versions
                    ON source_versions.dataset_id = source_datasets.id
                   AND source_versions.id = :source_version_id
                INNER JOIN daily_datasets AS target_datasets
                    ON target_datasets.id = :target_dataset_id
                LEFT JOIN dataset_publications AS source_publications
                    ON source_publications.dataset_id = source_datasets.id
                LEFT JOIN dataset_publications AS target_publications
                    ON target_publications.dataset_id = target_datasets.id
                WHERE source_datasets.id = :source_dataset_id
                LIMIT 1
                """
            ),
            {
                "source_dataset_id": source_dataset_id,
                "source_version_id": source_version_id,
                "target_dataset_id": target_dataset_id,
            },
        )
        .mappings()
        .first()
    )
    if state is None:
        raise _published_move_context_conflict()
    raw_source_report_date = state["source_report_date"]
    raw_target_report_date = state["target_report_date"]
    if (
        not isinstance(raw_source_report_date, date)
        or isinstance(raw_source_report_date, datetime)
        or not isinstance(raw_target_report_date, date)
        or isinstance(raw_target_report_date, datetime)
        or raw_source_report_date == raw_target_report_date
        or raw_target_report_date != target_report_date
        or state["source_report_type"] != target_report_type
        or state["target_report_type"] != target_report_type
        or int(state["source_site_id"]) != int(state["target_site_id"])
        or int(state["source_version_dataset_id"]) != source_dataset_id
        or state["source_version_status"] != "published"
        or state["source_publication_version_id"] is None
        or int(state["source_publication_version_id"]) != source_version_id
        or state["source_published_at"] is None
    ):
        raise _published_move_context_conflict()

    target_publication_version = state["target_publication_version_id"]
    target_published_at = state["target_published_at"]
    if (target_publication_version is None) != (target_published_at is None):
        raise _published_move_context_conflict()
    try:
        source_published_at = _utc_timestamp(state["source_published_at"])
        target_publication = PublicationPointerResponse(
            version_id=(
                int(target_publication_version)
                if target_publication_version is not None
                else None
            ),
            published_at=(
                _utc_timestamp(target_published_at)
                if target_published_at is not None
                else None
            ),
        )
    except (RuntimeError, TypeError, ValueError, OverflowError) as error:
        raise _published_move_context_conflict() from error
    if (
        source_published_at != frozen_source_published_at
        or target_publication.version_id != frozen_target_version_id
        or target_publication.published_at != frozen_target_published_at
    ):
        raise _published_move_context_conflict()
    return PublishedMoveContextResponse(
        revision_operation_token=ledger.revision_operation_token,
        source_dataset_id=source_dataset_id,
        source_report_date=raw_source_report_date,
        source_publication=PublicationPointerResponse(
            version_id=source_version_id,
            published_at=source_published_at,
        ),
        target_publication=target_publication,
    )


def _where_clause() -> str:
    return """
        WHERE review_rows.version_id = :version_id
          AND (:row_state IS NULL OR review_rows.row_state = :row_state)
          AND (
              :changed_only = FALSE
              OR EXISTS (
                  SELECT 1 FROM field_changes AS changed_fields
                  WHERE changed_fields.version_id = review_rows.version_id
                    AND changed_fields.row_id = review_rows.id
              )
              OR EXISTS (
                  SELECT 1 FROM row_changes AS changed_rows
                  WHERE changed_rows.version_id = review_rows.version_id
                    AND changed_rows.row_id = review_rows.id
              )
          )
    """


def _load_rows(
    database_session: Session,
    *,
    version_id: int,
    report_type: ReportType,
    contract: ReportFieldContract,
    row_state: _RowState | None,
    changed_only: bool,
    page: int,
    page_size: int,
) -> tuple[int, list[sa.RowMapping]]:
    filters = {
        "version_id": version_id,
        "row_state": row_state,
        "changed_only": changed_only,
    }
    where_clause = _where_clause()
    total_rows = int(
        database_session.scalar(
            sa.text(f"SELECT COUNT(*) FROM version_rows AS review_rows {where_clause}"),
            filters,
        )
        or 0
    )
    current_table, base_table, source_table = _row_tables(report_type)
    selected_values = ", ".join(
        (
            _safe_selected_columns("current_values", "current_", contract),
            _safe_selected_columns("base_values", "base_", contract),
            _safe_selected_columns("source_values", "source_", contract),
        )
    )
    rows = list(
        database_session.execute(
            sa.text(
                f"""
            SELECT review_rows.id, review_rows.logical_row_id,
                   review_rows.row_ordinal, review_rows.row_state,
                   review_rows.base_row_id,
                   review_rows.original_parsed_source_row_id,
                   base_rows.id AS available_base_row_id,
                   source_rows.id AS available_source_row_id,
                   source_rows.parsed_source_row_id,
                   source_attempts.batch_id AS source_batch_id,
                   {selected_values}
            FROM version_rows AS review_rows
            INNER JOIN {current_table} AS current_values
                ON current_values.version_id = review_rows.version_id
               AND current_values.version_row_id = review_rows.id
            LEFT JOIN version_base_rows AS base_rows
                ON base_rows.version_id = review_rows.version_id
               AND base_rows.id = review_rows.base_row_id
            LEFT JOIN {base_table} AS base_values
                ON base_values.version_id = base_rows.version_id
               AND base_values.version_base_row_id = base_rows.id
            LEFT JOIN parse_baseline_rows AS source_rows
                ON source_rows.id = base_rows.source_parse_baseline_row_id
               AND source_rows.parsed_source_row_id =
                   review_rows.original_parsed_source_row_id
            LEFT JOIN {source_table} AS source_values
                ON source_values.parse_baseline_id = source_rows.parse_baseline_id
               AND source_values.parse_baseline_row_id = source_rows.id
            LEFT JOIN parse_attempts AS source_attempts
                ON source_attempts.id = source_rows.parse_attempt_id
            {where_clause}
            ORDER BY review_rows.row_ordinal, review_rows.id
            LIMIT :page_size OFFSET :offset
            """
            ),
            {
                **filters,
                "page_size": page_size,
                "offset": (page - 1) * page_size,
            },
        )
        .mappings()
        .all()
    )
    return total_rows, rows


def _load_parent_values(
    database_session: Session,
    *,
    version_id: int,
    report_type: ReportType,
    contract: ReportFieldContract,
    logical_row_ids: tuple[bytes, ...],
) -> dict[bytes, list[tuple[int, sa.RowMapping]]]:
    if not logical_row_ids:
        return {}
    current_table, _base_table, _source_table = _row_tables(report_type)
    selected_values = _safe_selected_columns("parent_values", "parent_", contract)
    statement = sa.text(
        f"""
        SELECT parent_rows.logical_row_id, lineage.parent_version_id,
               {selected_values}
        FROM version_parent_versions AS lineage
        INNER JOIN version_rows AS parent_rows
            ON parent_rows.version_id = lineage.parent_version_id
           AND parent_rows.report_type = :report_type
        INNER JOIN {current_table} AS parent_values
            ON parent_values.version_id = parent_rows.version_id
           AND parent_values.version_row_id = parent_rows.id
        WHERE lineage.child_version_id = :version_id
          AND parent_rows.logical_row_id IN :logical_row_ids
        ORDER BY parent_rows.logical_row_id, lineage.parent_ordinal,
                 lineage.parent_version_id
        """
    ).bindparams(sa.bindparam("logical_row_ids", expanding=True))
    result: defaultdict[bytes, list[tuple[int, sa.RowMapping]]] = defaultdict(list)
    for row in database_session.execute(
        statement,
        {
            "version_id": version_id,
            "report_type": report_type,
            "logical_row_ids": logical_row_ids,
        },
    ).mappings():
        logical_row_id = _binary(row["logical_row_id"], length=16)
        result[logical_row_id].append((int(row["parent_version_id"]), row))
    return dict(result)


def _load_field_history(
    database_session: Session,
    *,
    version_id: int,
    row_ids: tuple[int, ...],
    report_type: ReportType,
    ruleset_version: str,
    field_names: frozenset[str],
) -> dict[tuple[int, str], list[FieldChangeResponse]]:
    if not row_ids:
        return {}
    statement = sa.text(
        """
        SELECT changes.id, changes.row_id, changes.field_name,
               changes.operation, changes.before_value_json,
               changes.after_value_json, changes.restored_field_change_id,
               changes.restored_parent_version_id,
               changes.restored_source_row_id, events.data_revision,
               events.actor_user_id, users.username_normalized AS actor_username,
               events.reason, events.occurred_at
        FROM field_changes AS changes
        INNER JOIN data_change_events AS events
            ON events.version_id = changes.version_id
           AND events.id = changes.id
        INNER JOIN users ON users.id = events.actor_user_id
        WHERE changes.version_id = :version_id
          AND changes.row_id IN :row_ids
        ORDER BY changes.row_id, changes.field_name,
                 events.data_revision DESC, changes.id DESC
        """
    ).bindparams(sa.bindparam("row_ids", expanding=True))
    result: defaultdict[tuple[int, str], list[FieldChangeResponse]] = defaultdict(list)
    for row in database_session.execute(
        statement,
        {"version_id": version_id, "row_ids": row_ids},
    ).mappings():
        field_name = str(row["field_name"])
        if field_name not in field_names:
            raise RuntimeError("field history violates the frozen field contract")
        result[(int(row["row_id"]), field_name)].append(
            FieldChangeResponse(
                id=int(row["id"]),
                data_revision=int(row["data_revision"]),
                operation=cast(
                    Literal[
                        "set",
                        "restore_source",
                        "restore_parent",
                        "restore_previous",
                    ],
                    row["operation"],
                ),
                before=_event_typed_value(
                    report_type=report_type,
                    ruleset_version=ruleset_version,
                    field_name=field_name,
                    payload=row["before_value_json"],
                ),
                after=_event_typed_value(
                    report_type=report_type,
                    ruleset_version=ruleset_version,
                    field_name=field_name,
                    payload=row["after_value_json"],
                ),
                restored_field_change_id=(
                    int(row["restored_field_change_id"])
                    if row["restored_field_change_id"] is not None
                    else None
                ),
                restored_parent_version_id=(
                    int(row["restored_parent_version_id"])
                    if row["restored_parent_version_id"] is not None
                    else None
                ),
                restored_source_row_id=(
                    int(row["restored_source_row_id"])
                    if row["restored_source_row_id"] is not None
                    else None
                ),
                actor_user_id=int(row["actor_user_id"]),
                actor_username=str(row["actor_username"]),
                reason=str(row["reason"]),
                occurred_at=_utc_timestamp(row["occurred_at"]),
            )
        )
    return dict(result)


def _load_row_history(
    database_session: Session,
    *,
    version_id: int,
    row_ids: tuple[int, ...],
) -> dict[int, list[RowChangeResponse]]:
    if not row_ids:
        return {}
    statement = sa.text(
        """
        SELECT changes.id, changes.row_id, changes.operation,
               changes.source_batch_id, changes.before_value_json,
               changes.after_value_json, events.data_revision,
               events.actor_user_id, users.username_normalized AS actor_username,
               events.reason, events.occurred_at
        FROM row_changes AS changes
        INNER JOIN data_change_events AS events
            ON events.version_id = changes.version_id
           AND events.id = changes.id
        INNER JOIN users ON users.id = events.actor_user_id
        WHERE changes.version_id = :version_id
          AND changes.row_id IN :row_ids
        ORDER BY changes.row_id, events.data_revision DESC, changes.id DESC
        """
    ).bindparams(sa.bindparam("row_ids", expanding=True))
    result: defaultdict[int, list[RowChangeResponse]] = defaultdict(list)
    for row in database_session.execute(
        statement,
        {"version_id": version_id, "row_ids": row_ids},
    ).mappings():
        result[int(row["row_id"])].append(
            RowChangeResponse(
                id=int(row["id"]),
                data_revision=int(row["data_revision"]),
                operation=cast(
                    Literal["add", "exclude", "restore", "delete"],
                    row["operation"],
                ),
                source_batch_id=(
                    int(row["source_batch_id"])
                    if row["source_batch_id"] is not None
                    else None
                ),
                before=_json_object(row["before_value_json"]),
                after=_json_object(row["after_value_json"]),
                actor_user_id=int(row["actor_user_id"]),
                actor_username=str(row["actor_username"]),
                reason=str(row["reason"]),
                occurred_at=_utc_timestamp(row["occurred_at"]),
            )
        )
    return dict(result)


def _load_latest_notes(
    database_session: Session,
    *,
    version_id: int,
    row_ids: tuple[int, ...],
) -> list[LatestNoteResponse]:
    row_filter = (
        "threads.row_id IS NULL OR threads.row_id IN :row_ids"
        if row_ids
        else "threads.row_id IS NULL"
    )
    statement = sa.text(
        f"""
        SELECT ranked.note_key, ranked.note_id, ranked.revision_number,
               ranked.target_type, ranked.row_id, ranked.field_name,
               ranked.visibility, ranked.body, ranked.author_user_id,
               ranked.author_username, ranked.review_revision,
               ranked.created_at
        FROM (
            SELECT threads.note_key, notes.id AS note_id,
                   notes.revision_number, threads.target_type,
                   threads.row_id, threads.field_name, notes.visibility,
                   notes.body, notes.author_user_id,
                   users.username_normalized AS author_username,
                   notes.review_revision, notes.created_at,
                   ROW_NUMBER() OVER (
                       PARTITION BY threads.note_key
                       ORDER BY notes.revision_number DESC, notes.id DESC
                   ) AS note_rank
            FROM note_threads AS threads
            INNER JOIN notes ON notes.note_key = threads.note_key
            INNER JOIN users ON users.id = notes.author_user_id
            WHERE threads.version_id = :version_id
              AND ({row_filter})
        ) AS ranked
        WHERE ranked.note_rank = 1
        ORDER BY ranked.target_type, ranked.row_id,
                 ranked.field_name, ranked.note_key
        """
    )
    parameters: dict[str, object] = {"version_id": version_id}
    if row_ids:
        statement = statement.bindparams(sa.bindparam("row_ids", expanding=True))
        parameters["row_ids"] = row_ids
    notes: list[LatestNoteResponse] = []
    for row in database_session.execute(statement, parameters).mappings():
        review_revision = row["review_revision"]
        if review_revision is None:
            raise RuntimeError("version note has no review revision")
        notes.append(
            LatestNoteResponse(
                note_key=str(row["note_key"]),
                note_id=int(row["note_id"]),
                revision_number=int(row["revision_number"]),
                target_type=cast(
                    Literal["version", "row", "field"],
                    row["target_type"],
                ),
                row_id=int(row["row_id"]) if row["row_id"] is not None else None,
                field_name=(
                    str(row["field_name"]) if row["field_name"] is not None else None
                ),
                visibility=cast(
                    Literal["internal", "viewer_visible"],
                    row["visibility"],
                ),
                body=str(row["body"]),
                author_user_id=int(row["author_user_id"]),
                author_username=str(row["author_username"]),
                review_revision=int(review_revision),
                created_at=_utc_timestamp(row["created_at"]),
            )
        )
    return notes


def _issue_review_state(row: sa.RowMapping) -> IssueReviewStateResponse:
    event_type = row["review_event_type"]
    if event_type == "acknowledge":
        state: Literal["open", "acknowledged", "resolved"] = "acknowledged"
    elif event_type == "resolve":
        state = "resolved"
    else:
        state = "open"
    return IssueReviewStateResponse(
        state=state,
        event_id=(
            int(row["review_event_id"]) if row["review_event_id"] is not None else None
        ),
        event_type=cast(
            Literal["acknowledge", "resolve", "reopen"] | None,
            event_type,
        ),
        actor_user_id=(
            int(row["review_actor_user_id"])
            if row["review_actor_user_id"] is not None
            else None
        ),
        actor_username=(
            str(row["review_actor_username"])
            if row["review_actor_username"] is not None
            else None
        ),
        comment=(
            str(row["review_comment"]) if row["review_comment"] is not None else None
        ),
        occurred_at=_optional_timestamp(row["review_occurred_at"]),
    )


def _load_latest_full_validation(
    database_session: Session,
    *,
    version_id: int,
    current_data_revision: int,
) -> FullValidationResponse | None:
    run = (
        database_session.execute(
            sa.text(
                """
            SELECT id, data_revision, ruleset_version, status, result,
                   data_digest, summary_json, started_at, completed_at
            FROM validation_runs
            WHERE version_id = :version_id AND run_type = 'full'
            ORDER BY id DESC
            LIMIT 1
            """
            ),
            {"version_id": version_id},
        )
        .mappings()
        .first()
    )
    if run is None:
        return None
    run_id = int(run["id"])
    issues = database_session.execute(
        sa.text(
            """
            SELECT issues.id, issues.row_id, issues.severity,
                   issues.rule_code, issues.field_name, issues.message,
                   issues.source_value_json, issues.processed_value_json,
                   issues.details_json, issues.requires_note,
                   issues.created_at,
                   latest_review.id AS review_event_id,
                   latest_review.event_type AS review_event_type,
                   latest_review.actor_user_id AS review_actor_user_id,
                   users.username_normalized AS review_actor_username,
                   latest_review.comment AS review_comment,
                   latest_review.occurred_at AS review_occurred_at
            FROM validation_issues AS issues
            LEFT JOIN (
                SELECT ranked_reviews.*
                FROM (
                    SELECT reviews.*,
                           ROW_NUMBER() OVER (
                               PARTITION BY reviews.validation_issue_id
                               ORDER BY reviews.sequence_number DESC,
                                        reviews.id DESC
                           ) AS review_rank
                    FROM issue_review_events AS reviews
                    WHERE reviews.version_id = :version_id
                      AND reviews.validation_run_id = :validation_run_id
                ) AS ranked_reviews
                WHERE ranked_reviews.review_rank = 1
            ) AS latest_review
                ON latest_review.version_id = issues.version_id
               AND latest_review.validation_run_id = issues.validation_run_id
               AND latest_review.validation_issue_id = issues.id
            LEFT JOIN users ON users.id = latest_review.actor_user_id
            WHERE issues.version_id = :version_id
              AND issues.validation_run_id = :validation_run_id
            ORDER BY CASE issues.severity WHEN 'blocking' THEN 0 ELSE 1 END,
                     issues.id
            """
        ),
        {"version_id": version_id, "validation_run_id": run_id},
    ).mappings()
    issue_responses = [
        ValidationIssueResponse(
            id=int(row["id"]),
            row_id=int(row["row_id"]) if row["row_id"] is not None else None,
            severity=cast(Literal["warning", "blocking"], row["severity"]),
            rule_code=str(row["rule_code"]),
            field_name=(
                str(row["field_name"]) if row["field_name"] is not None else None
            ),
            message=str(row["message"]),
            source_value=(
                _json_value(row["source_value_json"])
                if row["source_value_json"] is not None
                else None
            ),
            processed_value=(
                _json_value(row["processed_value_json"])
                if row["processed_value_json"] is not None
                else None
            ),
            details=(
                _json_value(row["details_json"])
                if row["details_json"] is not None
                else None
            ),
            requires_note=bool(row["requires_note"]),
            review=_issue_review_state(row),
            created_at=_utc_timestamp(row["created_at"]),
        )
        for row in issues
    ]
    run_data_revision = int(run["data_revision"])
    return FullValidationResponse(
        id=run_id,
        data_revision=run_data_revision,
        ruleset_version=str(run["ruleset_version"]),
        status=cast(Literal["succeeded", "failed"], run["status"]),
        result=cast(Literal["passed", "failed", "error"], run["result"]),
        data_digest=_binary(run["data_digest"], length=32).hex(),
        summary=_json_object(run["summary_json"]),
        started_at=_utc_timestamp(run["started_at"]),
        completed_at=_utc_timestamp(run["completed_at"]),
        is_current=run_data_revision == current_data_revision,
        issues=issue_responses,
    )


def _notes_by_target(
    notes: list[LatestNoteResponse],
) -> tuple[
    list[LatestNoteResponse],
    dict[int, list[LatestNoteResponse]],
    dict[tuple[int, str], list[LatestNoteResponse]],
]:
    version_notes: list[LatestNoteResponse] = []
    row_notes: defaultdict[int, list[LatestNoteResponse]] = defaultdict(list)
    field_notes: defaultdict[tuple[int, str], list[LatestNoteResponse]] = defaultdict(
        list
    )
    for note in notes:
        if note.target_type == "version":
            version_notes.append(note)
        elif note.target_type == "row":
            if note.row_id is None:
                raise RuntimeError("row note has no row identity")
            row_notes[note.row_id].append(note)
        else:
            if note.row_id is None or note.field_name is None:
                raise RuntimeError("field note has no field identity")
            field_notes[(note.row_id, note.field_name)].append(note)
    return version_notes, dict(row_notes), dict(field_notes)


@router.get(
    "/{version_id}/review-workspace",
    response_model=ReviewWorkspaceResponse,
)
def get_review_workspace(
    version_id: int,
    principal: _Manager,
    database_session: _DatabaseSession,
    changed_only: bool = False,
    row_state: Annotated[_RowState | None, Query()] = None,
    page: Annotated[int, Query(ge=1, le=1_000_000)] = 1,
    page_size: Annotated[int, Query(ge=1, le=100)] = 50,
) -> ReviewWorkspaceResponse:
    head_row, report_type, contract = _head(
        database_session,
        version_id=version_id,
    )
    raw_report_date = head_row["report_date"]
    if not isinstance(raw_report_date, date) or isinstance(raw_report_date, datetime):
        raise RuntimeError("database returned an invalid report date")
    target_dataset_id = int(head_row["dataset_id"])
    published_move_ledger = _load_published_move_ledger(
        database_session,
        version_id=version_id,
        target_dataset_id=target_dataset_id,
    )
    publication_mode: Literal["ordinary", "published_move"] = (
        "published_move" if published_move_ledger is not None else "ordinary"
    )
    published_move = (
        _load_published_move_context(
            database_session,
            ledger=published_move_ledger,
            target_dataset_id=target_dataset_id,
            target_report_date=raw_report_date,
            target_report_type=report_type,
        )
        if "admin" in principal.roles and published_move_ledger is not None
        else None
    )
    ruleset_version = str(head_row["ruleset_version"])
    total_rows, stored_rows = _load_rows(
        database_session,
        version_id=version_id,
        report_type=report_type,
        contract=contract,
        row_state=row_state,
        changed_only=changed_only,
        page=page,
        page_size=page_size,
    )
    logical_row_ids = tuple(
        _binary(row["logical_row_id"], length=16) for row in stored_rows
    )
    row_ids = tuple(int(row["id"]) for row in stored_rows)
    parent_values = _load_parent_values(
        database_session,
        version_id=version_id,
        report_type=report_type,
        contract=contract,
        logical_row_ids=logical_row_ids,
    )
    field_history = _load_field_history(
        database_session,
        version_id=version_id,
        row_ids=row_ids,
        report_type=report_type,
        ruleset_version=ruleset_version,
        field_names=frozenset(contract.field_names),
    )
    row_history = _load_row_history(
        database_session,
        version_id=version_id,
        row_ids=row_ids,
    )
    notes = _load_latest_notes(
        database_session,
        version_id=version_id,
        row_ids=row_ids,
    )
    version_notes, row_notes, field_notes = _notes_by_target(notes)

    response_rows: list[ReviewRowResponse] = []
    for row in stored_rows:
        row_id = int(row["id"])
        logical_row_id = _binary(row["logical_row_id"], length=16)
        has_base = row["available_base_row_id"] is not None
        has_source = row["available_source_row_id"] is not None
        source_batch_id = (
            int(row["source_batch_id"]) if row["source_batch_id"] is not None else None
        )
        parsed_source_row_id = (
            int(row["parsed_source_row_id"])
            if row["parsed_source_row_id"] is not None
            else None
        )
        cells: list[CellComparisonResponse] = []
        for field in contract.fields:
            current = _typed_value(
                report_type=report_type,
                ruleset_version=ruleset_version,
                field_name=field.name,
                value=row[f"current_{field.name}"],
            )
            base = (
                _typed_value(
                    report_type=report_type,
                    ruleset_version=ruleset_version,
                    field_name=field.name,
                    value=row[f"base_{field.name}"],
                )
                if has_base
                else None
            )
            source = (
                _typed_value(
                    report_type=report_type,
                    ruleset_version=ruleset_version,
                    field_name=field.name,
                    value=row[f"source_{field.name}"],
                )
                if has_source
                else None
            )
            parent_options = [
                ParentRestoreOptionResponse(
                    parent_version_id=parent_version_id,
                    value=_typed_value(
                        report_type=report_type,
                        ruleset_version=ruleset_version,
                        field_name=field.name,
                        value=parent_row[f"parent_{field.name}"],
                    ),
                )
                for parent_version_id, parent_row in parent_values.get(
                    logical_row_id,
                    [],
                )
            ]
            source_option = (
                SourceRestoreOptionResponse(
                    source_batch_id=source_batch_id,
                    parsed_source_row_id=parsed_source_row_id,
                    value=source,
                )
                if source is not None
                and source_batch_id is not None
                and parsed_source_row_id is not None
                else None
            )
            cells.append(
                CellComparisonResponse(
                    field_name=field.name,
                    current=current,
                    base=base,
                    source=source,
                    changed_from_base=base is None or current != base,
                    changed_from_source=source is not None and current != source,
                    parent_restore_options=parent_options,
                    source_restore_option=source_option,
                    history=field_history.get((row_id, field.name), []),
                    notes=field_notes.get((row_id, field.name), []),
                )
            )
        response_rows.append(
            ReviewRowResponse(
                row_id=row_id,
                logical_row_id=UUID(bytes=logical_row_id),
                row_ordinal=int(row["row_ordinal"]),
                row_state=cast(_RowState, row["row_state"]),
                base_row_id=(
                    int(row["base_row_id"]) if row["base_row_id"] is not None else None
                ),
                original_parsed_source_row_id=(
                    int(row["original_parsed_source_row_id"])
                    if row["original_parsed_source_row_id"] is not None
                    else None
                ),
                cells=cells,
                history=row_history.get(row_id, []),
                notes=row_notes.get(row_id, []),
            )
        )

    raw_status = str(head_row["status"])
    if raw_status not in {"draft", "ready_for_publish"}:
        raise RuntimeError("database returned an invalid draft status")
    total_pages = (total_rows + page_size - 1) // page_size
    return ReviewWorkspaceResponse(
        head=DraftWorkspaceHeadResponse(
            dataset_id=int(head_row["dataset_id"]),
            version_id=int(head_row["version_id"]),
            version_no=int(head_row["version_no"]),
            status=cast(_DraftStatus, raw_status),
            data_revision=int(head_row["data_revision"]),
            review_revision=int(head_row["review_revision"]),
            pointed_at=_utc_timestamp(head_row["pointed_at"]),
        ),
        report_date=raw_report_date,
        report_type=report_type,
        ruleset_version=ruleset_version,
        source_batches=_load_source_batches(
            database_session,
            version_id=version_id,
        ),
        fields=_contract_response(contract),
        rows=response_rows,
        version_notes=version_notes,
        latest_full_validation=_load_latest_full_validation(
            database_session,
            version_id=version_id,
            current_data_revision=int(head_row["data_revision"]),
        ),
        publication_mode=publication_mode,
        published_move=published_move,
        pagination=WorkspacePaginationResponse(
            page=page,
            page_size=page_size,
            total_rows=total_rows,
            total_pages=total_pages,
        ),
    )
