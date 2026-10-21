"""Public models for the read-only published-detail ledger."""

from __future__ import annotations

from datetime import UTC, date, datetime
from decimal import Decimal
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, field_validator, model_validator

from app.analytics.models import PublicationReference
from app.imports.types import ReportType

_PUBLIC_MODEL_CONFIG = ConfigDict(extra="forbid", strict=True)


class PublishedDetailQuery(BaseModel):
    """The request fields bound into a published-detail consistency scope."""

    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    site_id: int
    report_type: ReportType
    from_date: date
    to_date: date

    @model_validator(mode="after")
    def _has_ordered_dates(self) -> PublishedDetailQuery:
        if self.from_date > self.to_date:
            raise ValueError("from_date must not be after to_date")
        return self


class PublishedDetailScope(BaseModel):
    """An exact, principal-bound snapshot of current publication pointers."""

    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    user_id: int
    roles: tuple[str, ...]
    site_id: int
    report_type: ReportType
    from_date: date
    to_date: date
    issued_at: datetime
    expires_at: datetime
    publications: tuple[PublicationReference, ...]

    @field_validator("roles")
    @classmethod
    def _normalise_roles(cls, roles: tuple[str, ...]) -> tuple[str, ...]:
        if any(not role for role in roles):
            raise ValueError("roles must not contain blank values")
        return tuple(sorted(set(roles)))

    @field_validator("issued_at", "expires_at")
    @classmethod
    def _normalise_utc_timestamp(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("scope timestamps must be timezone-aware")
        return value.astimezone(UTC)

    @model_validator(mode="after")
    def _has_consistent_scope(self) -> PublishedDetailScope:
        if self.user_id <= 0:
            raise ValueError("user_id must be positive")
        if self.site_id <= 0:
            raise ValueError("site_id must be positive")
        if self.from_date > self.to_date:
            raise ValueError("from_date must not be after to_date")
        if self.expires_at <= self.issued_at:
            raise ValueError("expires_at must be after issued_at")

        seen_identity: set[tuple[int, date, ReportType]] = set()
        seen_pointer: set[tuple[int, int, date, ReportType, int, datetime]] = set()
        previous_date: date | None = None
        for publication in self.publications:
            if publication.site_id != self.site_id:
                raise ValueError("publication site_id must match scope site_id")
            if publication.report_type != self.report_type:
                raise ValueError("publication report_type must match scope report_type")
            if not self.from_date <= publication.report_date <= self.to_date:
                raise ValueError("publication report_date must be inside scope range")
            if previous_date is not None and publication.report_date <= previous_date:
                raise ValueError("publications must be strictly ordered by report_date")
            previous_date = publication.report_date
            identity = (
                publication.dataset_id,
                publication.report_date,
                publication.report_type,
            )
            pointer = (
                publication.dataset_id,
                publication.site_id,
                publication.report_date,
                publication.report_type,
                publication.version_id,
                publication.published_at,
            )
            if identity in seen_identity or pointer in seen_pointer:
                raise ValueError("publications contain a duplicate pointer")
            seen_identity.add(identity)
            seen_pointer.add(pointer)
        return self


class PublishedDetailColumn(BaseModel):
    model_config = _PUBLIC_MODEL_CONFIG

    column_id: UUID
    source_header: str
    display_order: int
    value_kind: Literal["text", "integer", "decimal", "utc_datetime"]
    standard_field_name: str | None
    is_key: bool
    participates_in_statistics: bool


class PublishedDetailCell(BaseModel):
    model_config = _PUBLIC_MODEL_CONFIG

    column_id: UUID
    value: str | int | Decimal | datetime | None


class PublishedDetailRow(BaseModel):
    model_config = _PUBLIC_MODEL_CONFIG

    report_date: date
    version_id: int
    version_no: int
    published_at: datetime
    row_ordinal: int
    cells: list[PublishedDetailCell]


class PublishedDateSummary(BaseModel):
    model_config = _PUBLIC_MODEL_CONFIG

    report_date: date
    version_id: int
    version_no: int
    published_at: datetime
    total_row_count: int
    matching_row_count: int
    metric_scope: Literal["full_day"] = "full_day"
    sales: str | None
    units_ordered: int | None
    sessions: int | None
    return_quantity: int | None
    publication: PublicationReference


class PublishedDetailPermissions(BaseModel):
    model_config = _PUBLIC_MODEL_CONFIG

    can_export: bool


class PublishedDetailPagination(BaseModel):
    model_config = _PUBLIC_MODEL_CONFIG

    page: int
    page_size: int
    total_items: int
    total_pages: int


class PublishedDetailRange(BaseModel):
    model_config = _PUBLIC_MODEL_CONFIG

    from_date: date
    to_date: date


class PublishedSummaryResponse(BaseModel):
    model_config = _PUBLIC_MODEL_CONFIG

    range: PublishedDetailRange
    summaries: list[PublishedDateSummary]
    publications: list[PublicationReference]
    permissions: PublishedDetailPermissions
    pagination: PublishedDetailPagination
    scope_token: str


class PublishedRowsResponse(BaseModel):
    model_config = _PUBLIC_MODEL_CONFIG

    range: PublishedDetailRange
    columns: list[PublishedDetailColumn]
    rows: list[PublishedDetailRow]
    publications: list[PublicationReference]
    permissions: PublishedDetailPermissions
    pagination: PublishedDetailPagination
    scope_token: str


class PublishedRangeResponse(BaseModel):
    model_config = _PUBLIC_MODEL_CONFIG

    from_date: date | None
    to_date: date | None
