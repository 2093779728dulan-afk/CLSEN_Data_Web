"""Closed catalog enums and common command/permission DTOs."""

from __future__ import annotations

from enum import StrEnum
from typing import Annotated

from pydantic import UUID4, Field

from app.catalog.models import StrictCatalogModel

CatalogId = Annotated[str, Field(min_length=1, max_length=128)]
CatalogRevision = Annotated[int, Field(strict=True, ge=0)]


class CatalogSourceKind(StrEnum):
    SELLER_SKU = "seller_sku"
    PARENT_ASIN = "parent_asin"
    CHILD_ASIN = "child_asin"
    FNSKU = "fnsku"
    TITLE = "title"


class CatalogImportStatus(StrEnum):
    UPLOADED = "uploaded"
    PARSING = "parsing"
    PARSE_FAILED = "parse_failed"
    NEEDS_ATTENTION = "needs_attention"
    VALIDATED = "validated"
    SUBMITTED = "submitted"
    APPROVED = "approved"
    REJECTED = "rejected"
    SUPERSEDED = "superseded"


class CatalogReasonCode(StrEnum):
    UNSAFE_SOURCE_TEXT = "unsafe_source_text"
    NORMALIZATION_COLLISION = "seller_sku_normalization_collision"
    IDENTITY_CONFLICT = "catalog_identity_conflict"
    STALE_REVISION = "catalog_revision_conflict"


class CatalogPermissions(StrictCatalogModel):
    can_view_catalog_history: bool
    can_manage_catalog: bool
    can_view_evidence_history: bool
    can_download_original: bool
    can_submit: bool
    can_approve_normal: bool
    can_approve_high_risk: bool


class CatalogCommandEnvelope(StrictCatalogModel):
    operation_token: UUID4
    expected_revision: CatalogRevision
