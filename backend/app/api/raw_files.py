"""Authorised, integrity-checked download of immutable source CSV files."""

from __future__ import annotations

from typing import Annotated, Literal, Never, cast
from urllib.parse import quote

import sqlalchemy as sa
from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel
from sqlalchemy.engine import RowMapping
from sqlalchemy.orm import Session
from starlette.responses import Response

from app.api.dependencies import get_database_session, require_roles
from app.api.errors import ApiError
from app.auth.sessions import Principal
from app.config import StorageSettings
from app.imports.storage import (
    ContentPreviewError,
    ContentStoreError,
    LocalContentStore,
)

router = APIRouter(tags=["imports"])
_Manager = Annotated[Principal, Depends(require_roles("admin", "data_manager"))]
_DatabaseSession = Annotated[
    Session,
    Depends(get_database_session, scope="function"),
]

_SAFE_MEDIA_TYPES = frozenset(
    {
        "text/csv",
        "application/csv",
        "application/vnd.ms-excel",
    }
)


class RawFilePreviewResponse(BaseModel):
    headers: list[str]
    rows: list[list[str]]
    row_count: int
    truncated: bool
    encoding: Literal["utf-8-sig", "utf-8", "windows-1252"]


def _load_raw_file(
    database_session: Session,
    batch_id: int,
) -> RowMapping:
    row = (
        database_session.execute(
            sa.text(
                """
                SELECT files.storage_key, files.sha256, files.original_filename,
                       files.media_type, files.size_bytes,
                       COALESCE(integrity.status, 'available') AS integrity_status
                FROM import_batches AS batches
                INNER JOIN raw_files AS files ON files.id = batches.raw_file_id
                LEFT JOIN raw_file_integrity_statuses AS integrity
                    ON integrity.raw_file_id = files.id
                WHERE batches.id = :batch_id
                LIMIT 1
                """
            ),
            {"batch_id": batch_id},
        )
        .mappings()
        .first()
    )
    if row is None:
        raise ApiError(404, "import_not_found", "The requested import was not found.")
    if row["integrity_status"] != "available":
        raise ApiError(
            409,
            "raw_file_unavailable",
            "The source file failed its most recent integrity check.",
        )
    return row


def _content_store() -> LocalContentStore:
    storage = StorageSettings.from_env()
    return LocalContentStore(storage.root, storage.max_upload_bytes)


def _content_identity(row: RowMapping) -> tuple[str, str, int]:
    return (
        str(row["storage_key"]),
        cast(bytes, row["sha256"]).hex(),
        cast(int, row["size_bytes"]),
    )


def _raise_unavailable(error: ContentStoreError) -> Never:
    raise ApiError(
        409,
        "raw_file_unavailable",
        "The source file is unavailable or failed its integrity check.",
    ) from error


@router.head(
    "/api/imports/{batch_id}/raw-file",
    include_in_schema=False,
    response_class=Response,
)
def check_raw_file(
    batch_id: int,
    _principal: _Manager,
    database_session: _DatabaseSession,
) -> Response:
    row = _load_raw_file(database_session, batch_id)
    try:
        _content_store().inspect(*_content_identity(row))
    except ContentStoreError as error:
        _raise_unavailable(error)
    return Response(headers={"Cache-Control": "private, no-store"})


@router.get(
    "/api/imports/{batch_id}/raw-file",
    response_class=Response,
    responses={
        200: {
            "description": "Integrity-checked immutable source file.",
            "content": {
                "text/csv": {
                    "schema": {"type": "string", "format": "binary"},
                },
                "application/octet-stream": {
                    "schema": {"type": "string", "format": "binary"},
                },
            },
        }
    },
)
def download_raw_file(
    batch_id: int,
    _principal: _Manager,
    database_session: _DatabaseSession,
) -> Response:
    row = _load_raw_file(database_session, batch_id)
    try:
        content = _content_store().read_bytes(*_content_identity(row))
    except ContentStoreError as error:
        _raise_unavailable(error)

    filename = str(row["original_filename"])
    encoded_filename = quote(filename, safe="")
    media_type = str(row["media_type"] or "").lower()
    if media_type not in _SAFE_MEDIA_TYPES:
        media_type = "application/octet-stream"
    return Response(
        content=content,
        media_type=media_type,
        headers={
            "Content-Disposition": (
                'attachment; filename="source.csv"; '
                f"filename*=UTF-8''{encoded_filename}"
            ),
            "Cache-Control": "private, no-store",
            "X-Content-Type-Options": "nosniff",
        },
    )


@router.get(
    "/api/imports/{batch_id}/raw-file/preview",
    response_model=RawFilePreviewResponse,
)
def preview_raw_file(
    batch_id: int,
    _principal: _Manager,
    database_session: _DatabaseSession,
    encoding: Literal["utf-8-sig", "utf-8", "windows-1252"] = "utf-8-sig",
    row_limit: Annotated[int, Query(ge=1, le=200)] = 200,
) -> RawFilePreviewResponse:
    row = _load_raw_file(database_session, batch_id)
    try:
        preview = _content_store().read_csv_preview(
            *_content_identity(row),
            encoding=encoding,
            row_limit=row_limit,
        )
    except ContentPreviewError as error:
        raise ApiError(
            422,
            "raw_file_preview_invalid",
            "The source file could not be previewed with the selected encoding.",
        ) from error
    except ContentStoreError as error:
        _raise_unavailable(error)
    return RawFilePreviewResponse(
        headers=list(preview.headers),
        rows=[list(item) for item in preview.rows],
        row_count=len(preview.rows),
        truncated=preview.truncated,
        encoding=encoding,
    )
