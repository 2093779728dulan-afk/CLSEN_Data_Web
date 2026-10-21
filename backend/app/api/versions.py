"""Viewer-safe dataset version history and lineage reads."""

from __future__ import annotations

from datetime import UTC, date, datetime
from typing import Annotated, Literal, cast

import sqlalchemy as sa
from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.api.dependencies import get_database_session, require_roles
from app.api.errors import ApiError
from app.auth.sessions import Principal
from app.workbench.queries import (
    DateWorkbenchQueryService,
    WorkbenchHeadResponse,
    WorkbenchQueryError,
)

router = APIRouter(prefix="/api/versions", tags=["versions"])
_Principal = Annotated[
    Principal,
    Depends(require_roles("admin", "data_manager", "viewer")),
]
_DatabaseSession = Annotated[
    Session,
    Depends(get_database_session, scope="function"),
]

type ReportType = Literal["business_report", "return_report"]
type VersionStatus = Literal[
    "draft",
    "ready_for_publish",
    "published",
    "discarded",
]
type LineageType = Literal[
    "base",
    "draft_predecessor",
    "merge_target",
    "merge_source",
    "moved_source",
]
_ReportDate = Annotated[date | None, Query()]
_ReportType = Annotated[ReportType | None, Query()]
_BatchReviewRunId = Annotated[int | None, Query(ge=1)]
_SITE_CODE = "amazon_us"


class VersionSummaryResponse(BaseModel):
    dataset_id: int
    version_id: int
    report_date: date
    report_type: ReportType
    version_no: int
    status: VersionStatus
    data_revision: int
    review_revision: int
    created_at: datetime
    sealed_at: datetime | None
    is_current_publication: bool
    published_at: datetime | None
    is_active_draft: bool
    draft_pointed_at: datetime | None
    publication_revision: int | None
    dedup_publication_revision: int | None


class VersionLineageResponse(BaseModel):
    dataset_id: int
    version_id: int
    report_date: date
    report_type: ReportType
    version_no: int
    status: VersionStatus
    lineage_type: LineageType
    lineage_ordinal: int


class ViewerVisibleNoteResponse(BaseModel):
    note_key: str
    revision_number: int
    body: str
    created_at: datetime


class VersionDetailResponse(VersionSummaryResponse):
    parents: list[VersionLineageResponse]
    children: list[VersionLineageResponse]
    viewer_visible_notes: list[ViewerVisibleNoteResponse]


@router.get("/{version_id}/rows")
def get_version_rows(
    version_id: int,
    principal: _Principal,
    database_session: _DatabaseSession,
    page: Annotated[int, Query(ge=1)] = 1,
    page_size: Annotated[int, Query(ge=1, le=100)] = 50,
) -> dict[str, object]:
    """Published snapshots only; never resolve the current publication pointer."""
    detail = get_version(version_id, principal, database_session)
    if detail.status != "published":
        raise ApiError(404, "version_not_found", "Published version not found.")
    ruleset = database_session.execute(
        sa.text("SELECT ruleset_version FROM dataset_versions WHERE id = :id"),
        {"id": version_id},
    ).scalar_one()
    head = WorkbenchHeadResponse(
        dataset_id=detail.dataset_id,
        version_id=version_id,
        version_no=detail.version_no,
        status="published",
        data_revision=detail.data_revision,
        review_revision=detail.review_revision,
        ruleset_version=str(ruleset),
        pointed_at=detail.sealed_at or detail.created_at,
    )
    try:
        result = DateWorkbenchQueryService(database_session).published_version_rows(
            head=head,
            report_type=detail.report_type,
            page=page,
            page_size=page_size,
        )
    except WorkbenchQueryError as error:
        raise ApiError(409, error.code, error.message) from error
    return {
        "version_id": version_id,
        "version_no": detail.version_no,
        "report_date": detail.report_date,
        "report_type": detail.report_type,
        **result,
    }


def _can_view_all_versions(principal: Principal) -> bool:
    return not principal.roles.isdisjoint({"admin", "data_manager"})


def _utc_timestamp(value: object) -> datetime:
    if not isinstance(value, datetime):
        raise RuntimeError("database returned an invalid version timestamp")
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    if value.utcoffset() is None:
        raise RuntimeError("database returned an invalid version timestamp")
    return value.astimezone(UTC)


def _optional_utc_timestamp(value: object) -> datetime | None:
    return None if value is None else _utc_timestamp(value)


def _version_summary(row: sa.RowMapping) -> VersionSummaryResponse:
    return VersionSummaryResponse(
        dataset_id=int(row["dataset_id"]),
        version_id=int(row["version_id"]),
        report_date=row["report_date"],
        report_type=cast(ReportType, row["report_type"]),
        version_no=int(row["version_no"]),
        status=cast(VersionStatus, row["status"]),
        data_revision=int(row["data_revision"]),
        review_revision=int(row["review_revision"]),
        created_at=_utc_timestamp(row["created_at"]),
        sealed_at=_optional_utc_timestamp(row["sealed_at"]),
        is_current_publication=row["published_version_id"] is not None,
        published_at=_optional_utc_timestamp(row["published_at"]),
        is_active_draft=row["draft_version_id"] is not None,
        draft_pointed_at=_optional_utc_timestamp(row["draft_pointed_at"]),
        publication_revision=(
            int(row["publication_revision"])
            if row["publication_revision"] is not None
            else None
        ),
        dedup_publication_revision=(
            int(row["dedup_publication_revision"])
            if row["dedup_publication_revision"] is not None
            else None
        ),
    )


def _lineage(row: sa.RowMapping) -> VersionLineageResponse:
    return VersionLineageResponse(
        dataset_id=int(row["dataset_id"]),
        version_id=int(row["version_id"]),
        report_date=row["report_date"],
        report_type=cast(ReportType, row["report_type"]),
        version_no=int(row["version_no"]),
        status=cast(VersionStatus, row["status"]),
        lineage_type=cast(LineageType, row["lineage_type"]),
        lineage_ordinal=int(row["lineage_ordinal"]),
    )


@router.get("", response_model=list[VersionSummaryResponse])
def list_versions(
    principal: _Principal,
    database_session: _DatabaseSession,
    report_date: _ReportDate = None,
    report_type: _ReportType = None,
    batch_review_run_id: _BatchReviewRunId = None,
) -> list[VersionSummaryResponse]:
    """List one date/type history without exposing row-level business data."""

    if batch_review_run_id is not None:
        if not _can_view_all_versions(principal):
            raise ApiError(
                404,
                "batch_review_not_found",
                "The batch review was not found.",
            )
        visible_run = (
            database_session.execute(
                sa.text(
                    """
                SELECT runs.id
                FROM batch_review_runs AS runs
                INNER JOIN sites ON sites.id = runs.site_id
                WHERE runs.id = :batch_review_run_id
                  AND sites.code = :site_code
                  AND sites.status = 'active'
                LIMIT 1
                """
                ),
                {"batch_review_run_id": batch_review_run_id, "site_code": _SITE_CODE},
            )
            .mappings()
            .first()
        )
        if visible_run is None:
            raise ApiError(
                404,
                "batch_review_not_found",
                "The batch review was not found.",
            )
        rows = database_session.execute(
            sa.text(
                """
                SELECT versions.dataset_id, versions.id AS version_id,
                       datasets.report_date, datasets.report_type,
                       versions.version_no, versions.status,
                       versions.data_revision, versions.review_revision,
                       versions.created_at, versions.sealed_at,
                       publications.version_id AS published_version_id,
                       publications.published_at,
                       drafts.version_id AS draft_version_id,
                       drafts.pointed_at AS draft_pointed_at,
                       (
                           SELECT revisions.publication_revision
                           FROM report_publication_revisions AS revisions
                           WHERE revisions.dataset_id = versions.dataset_id
                             AND revisions.site_id = datasets.site_id
                           LIMIT 1
                       ) AS publication_revision,
                       (
                           SELECT pointers.dedup_publication_revision
                           FROM report_dataset_scope_assignments AS assignments
                           INNER JOIN return_dedup_publications AS pointers
                               ON pointers.site_id = assignments.site_id
                              AND pointers.report_source_scope_id =
                                  assignments.report_source_scope_id
                           WHERE assignments.dataset_id = versions.dataset_id
                             AND assignments.site_id = datasets.site_id
                           LIMIT 1
                       ) AS dedup_publication_revision
                FROM batch_review_runs AS runs
                INNER JOIN sites ON sites.id = runs.site_id
                INNER JOIN batch_review_items AS items
                    ON items.run_id = runs.id AND items.site_id = runs.site_id
                INNER JOIN dataset_versions AS versions
                    ON versions.id = items.version_id
                INNER JOIN daily_datasets AS datasets
                    ON datasets.id = versions.dataset_id
                   AND datasets.site_id = runs.site_id
                LEFT JOIN dataset_publications AS publications
                    ON publications.dataset_id = versions.dataset_id
                   AND publications.version_id = versions.id
                LEFT JOIN dataset_drafts AS drafts
                    ON drafts.dataset_id = versions.dataset_id
                   AND drafts.version_id = versions.id
                WHERE runs.id = :batch_review_run_id
                  AND sites.code = :site_code
                  AND sites.status = 'active'
                  AND items.status = 'ready_for_publish'
                  AND versions.status = 'ready_for_publish'
                ORDER BY datasets.report_date DESC, datasets.report_type,
                         versions.version_no DESC, versions.id DESC
                """
            ),
            {"batch_review_run_id": batch_review_run_id, "site_code": _SITE_CODE},
        ).mappings()
        return [_version_summary(row) for row in rows]

    if report_date is None or report_type is None:
        raise ApiError(
            422,
            "version_filter_required",
            "report_date and report_type are required without a batch review filter.",
        )

    rows = database_session.execute(
        sa.text(
            """
            SELECT versions.dataset_id, versions.id AS version_id,
                   datasets.report_date, datasets.report_type,
                   versions.version_no, versions.status,
                   versions.data_revision, versions.review_revision,
                   versions.created_at, versions.sealed_at,
                   publications.version_id AS published_version_id,
                   publications.published_at,
                   drafts.version_id AS draft_version_id,
                   drafts.pointed_at AS draft_pointed_at,
                   (
                       SELECT revisions.publication_revision
                       FROM report_publication_revisions AS revisions
                       WHERE revisions.dataset_id = versions.dataset_id
                         AND revisions.site_id = datasets.site_id
                       LIMIT 1
                   ) AS publication_revision,
                   (
                       SELECT pointers.dedup_publication_revision
                       FROM report_dataset_scope_assignments AS assignments
                       INNER JOIN return_dedup_publications AS pointers
                           ON pointers.site_id = assignments.site_id
                          AND pointers.report_source_scope_id =
                              assignments.report_source_scope_id
                       WHERE assignments.dataset_id = versions.dataset_id
                         AND assignments.site_id = datasets.site_id
                       LIMIT 1
                   ) AS dedup_publication_revision
            FROM daily_datasets AS datasets
            INNER JOIN dataset_versions AS versions
                ON versions.dataset_id = datasets.id
            LEFT JOIN dataset_publications AS publications
                ON publications.dataset_id = versions.dataset_id
               AND publications.version_id = versions.id
            LEFT JOIN dataset_drafts AS drafts
                ON drafts.dataset_id = versions.dataset_id
               AND drafts.version_id = versions.id
            WHERE datasets.report_date = :report_date
              AND datasets.report_type = :report_type
              AND (:can_view_all = TRUE OR versions.status = 'published')
            ORDER BY versions.version_no DESC, versions.id DESC
            """
        ),
        {
            "report_date": report_date,
            "report_type": report_type,
            "can_view_all": _can_view_all_versions(principal),
        },
    ).mappings()
    return [_version_summary(row) for row in rows]


@router.get("/{version_id}", response_model=VersionDetailResponse)
def get_version(
    version_id: int,
    principal: _Principal,
    database_session: _DatabaseSession,
) -> VersionDetailResponse:
    """Return safe lineage and only the latest viewer-visible note revisions."""

    can_view_all = _can_view_all_versions(principal)
    row = (
        database_session.execute(
            sa.text(
                """
            SELECT versions.dataset_id, versions.id AS version_id,
                   datasets.report_date, datasets.report_type,
                   versions.version_no, versions.status,
                   versions.data_revision, versions.review_revision,
                   versions.created_at, versions.sealed_at,
                   publications.version_id AS published_version_id,
                   publications.published_at,
                   drafts.version_id AS draft_version_id,
                   drafts.pointed_at AS draft_pointed_at,
                   (
                       SELECT revisions.publication_revision
                       FROM report_publication_revisions AS revisions
                       WHERE revisions.dataset_id = versions.dataset_id
                         AND revisions.site_id = datasets.site_id
                       LIMIT 1
                   ) AS publication_revision,
                   (
                       SELECT pointers.dedup_publication_revision
                       FROM report_dataset_scope_assignments AS assignments
                       INNER JOIN return_dedup_publications AS pointers
                           ON pointers.site_id = assignments.site_id
                          AND pointers.report_source_scope_id =
                              assignments.report_source_scope_id
                       WHERE assignments.dataset_id = versions.dataset_id
                         AND assignments.site_id = datasets.site_id
                       LIMIT 1
                   ) AS dedup_publication_revision
            FROM dataset_versions AS versions
            INNER JOIN daily_datasets AS datasets
                ON datasets.id = versions.dataset_id
            LEFT JOIN dataset_publications AS publications
                ON publications.dataset_id = versions.dataset_id
               AND publications.version_id = versions.id
            LEFT JOIN dataset_drafts AS drafts
                ON drafts.dataset_id = versions.dataset_id
               AND drafts.version_id = versions.id
            WHERE versions.id = :version_id
              AND (:can_view_all = TRUE OR versions.status = 'published')
            LIMIT 1
            """
            ),
            {"version_id": version_id, "can_view_all": can_view_all},
        )
        .mappings()
        .first()
    )
    if row is None:
        raise ApiError(
            404,
            "version_not_found",
            "The requested version was not found.",
        )

    parents = database_session.execute(
        sa.text(
            """
            SELECT related.dataset_id, related.id AS version_id,
                   datasets.report_date, datasets.report_type,
                   related.version_no, related.status,
                   lineage.lineage_type,
                   lineage.parent_ordinal AS lineage_ordinal
            FROM version_parent_versions AS lineage
            INNER JOIN dataset_versions AS related
                ON related.id = lineage.parent_version_id
            INNER JOIN daily_datasets AS datasets
                ON datasets.id = related.dataset_id
            WHERE lineage.child_version_id = :version_id
              AND (:can_view_all = TRUE OR related.status = 'published')
            ORDER BY lineage.parent_ordinal, related.id
            """
        ),
        {"version_id": version_id, "can_view_all": can_view_all},
    ).mappings()
    children = database_session.execute(
        sa.text(
            """
            SELECT related.dataset_id, related.id AS version_id,
                   datasets.report_date, datasets.report_type,
                   related.version_no, related.status,
                   lineage.lineage_type,
                   lineage.parent_ordinal AS lineage_ordinal
            FROM version_parent_versions AS lineage
            INNER JOIN dataset_versions AS related
                ON related.id = lineage.child_version_id
            INNER JOIN daily_datasets AS datasets
                ON datasets.id = related.dataset_id
            WHERE lineage.parent_version_id = :version_id
              AND (:can_view_all = TRUE OR related.status = 'published')
            ORDER BY related.version_no, related.id, lineage.parent_ordinal
            """
        ),
        {"version_id": version_id, "can_view_all": can_view_all},
    ).mappings()
    note_rows = database_session.execute(
        sa.text(
            """
            SELECT notes.note_key, notes.revision_number,
                   notes.body, notes.created_at
            FROM note_threads AS threads
            INNER JOIN notes
                ON notes.note_key = threads.note_key
            INNER JOIN (
                SELECT note_key, MAX(revision_number) AS revision_number
                FROM notes
                GROUP BY note_key
            ) AS latest_notes
                ON latest_notes.note_key = notes.note_key
               AND latest_notes.revision_number = notes.revision_number
            WHERE threads.version_id = :version_id
              AND notes.visibility = 'viewer_visible'
            ORDER BY notes.created_at, notes.id
            """
        ),
        {"version_id": version_id},
    ).mappings()

    summary = _version_summary(row)
    return VersionDetailResponse(
        **summary.model_dump(),
        parents=[_lineage(parent) for parent in parents],
        children=[_lineage(child) for child in children],
        viewer_visible_notes=[
            ViewerVisibleNoteResponse(
                note_key=str(note["note_key"]),
                revision_number=int(note["revision_number"]),
                body=str(note["body"]),
                created_at=_utc_timestamp(note["created_at"]),
            )
            for note in note_rows
        ],
    )
