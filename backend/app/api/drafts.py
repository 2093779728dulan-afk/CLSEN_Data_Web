"""Draft-head lookup used by optimistic review commands."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Annotated, Literal, cast

import sqlalchemy as sa
from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.api.dependencies import get_database_session, require_roles
from app.api.errors import ApiError
from app.auth.sessions import Principal

router = APIRouter(prefix="/api/drafts", tags=["drafts"])
_Manager = Annotated[Principal, Depends(require_roles("admin", "data_manager"))]
_DatabaseSession = Annotated[
    Session,
    Depends(get_database_session, scope="function"),
]


class DraftHeadResponse(BaseModel):
    dataset_id: int
    version_id: int
    version_no: int
    status: Literal["draft", "ready_for_publish"]
    data_revision: int
    review_revision: int
    pointed_at: datetime


def _utc_timestamp(value: object) -> datetime:
    if not isinstance(value, datetime):
        raise RuntimeError("database returned an invalid draft pointer timestamp")
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    if value.utcoffset() is None:
        raise RuntimeError("database returned an invalid draft pointer timestamp")
    return value.astimezone(UTC)


@router.get("/{version_id}", response_model=DraftHeadResponse)
def get_draft_head(
    version_id: int,
    _principal: _Manager,
    database_session: _DatabaseSession,
) -> DraftHeadResponse:
    row = (
        database_session.execute(
            sa.text(
                """
            SELECT drafts.dataset_id, drafts.version_id, drafts.pointed_at,
                   versions.version_no, versions.status, versions.data_revision,
                   versions.review_revision
            FROM dataset_drafts AS drafts
            INNER JOIN dataset_versions AS versions
                ON versions.dataset_id = drafts.dataset_id
               AND versions.id = drafts.version_id
            WHERE drafts.version_id = :version_id
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
    return DraftHeadResponse(
        dataset_id=int(row["dataset_id"]),
        version_id=int(row["version_id"]),
        version_no=int(row["version_no"]),
        status=cast(Literal["draft", "ready_for_publish"], row["status"]),
        data_revision=int(row["data_revision"]),
        review_revision=int(row["review_revision"]),
        pointed_at=_utc_timestamp(row["pointed_at"]),
    )
