"""Shared fail-closed Pydantic configuration for catalog wire models."""

from __future__ import annotations

from typing import Annotated
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

CatalogWireUuid = Annotated[UUID, Field(strict=False)]


class StrictCatalogModel(BaseModel):
    """Forbid schema drift and suppress raw values in validation messages."""

    model_config = ConfigDict(
        extra="forbid",
        frozen=True,
        strict=True,
        hide_input_in_errors=True,
    )
