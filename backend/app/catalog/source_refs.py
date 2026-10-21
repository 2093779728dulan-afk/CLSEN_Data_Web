"""Safe, non-reversible public references to source identifiers."""

from __future__ import annotations

from typing import Annotated

from pydantic import StringConstraints

from app.catalog.models import StrictCatalogModel
from app.catalog.normalization import safe_source_projection_v1
from app.catalog.types import CatalogSourceKind

SourceRefId = Annotated[
    str,
    StringConstraints(
        min_length=1,
        max_length=128,
        pattern=r"\A[A-Za-z0-9][A-Za-z0-9_.:-]*\z",
    ),
]
Sha256Reference = Annotated[
    str,
    StringConstraints(pattern=r"\Asha256:[0-9a-f]{64}\z"),
]
SafePreview = Annotated[str, StringConstraints(max_length=255)]


class SafeSourceRef(StrictCatalogModel):
    source_ref_id: SourceRefId
    preview: SafePreview
    sha256: Sha256Reference
    is_unsafe: bool
    is_truncated: bool


def make_safe_source_ref(
    *,
    source_ref_id: str,
    raw_value: str,
    source_kind: CatalogSourceKind,
    max_scalars: int = 255,
) -> SafeSourceRef:
    """Build a public ref without retaining the raw value in the DTO."""

    CatalogSourceKind(source_kind)
    projection = safe_source_projection_v1(raw_value, max_scalars=max_scalars)
    return SafeSourceRef(
        source_ref_id=source_ref_id,
        preview=projection.preview,
        sha256=projection.sha256,
        is_unsafe=projection.is_unsafe,
        is_truncated=projection.is_truncated,
    )


__all__ = ("SafeSourceRef", "make_safe_source_ref")
