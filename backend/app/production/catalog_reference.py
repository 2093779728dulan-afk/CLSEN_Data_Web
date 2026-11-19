"""Read-only A catalog candidates for explicitly authorized source snapshots."""

from __future__ import annotations

import re
from collections import Counter
from pathlib import Path
from typing import Literal, cast

from pydantic import Field, ValidationError

from app.catalog.models import StrictCatalogModel
from app.site_context import CurrentSiteContext


class ReferenceScope(StrictCatalogModel):
    report_source_scope_id: str = Field(pattern=r"^[1-9][0-9]*$")
    marketplace_scope_code: str = Field(max_length=64)


class ReferenceCandidate(StrictCatalogModel):
    sku_id: str = Field(pattern=r"^[1-9][0-9]*$")
    style_id: str = Field(pattern=r"^[1-9][0-9]*$")
    sku_revision: str = Field(pattern=r"^[1-9][0-9]*$")
    code: str = Field(max_length=128)
    color: str = Field(max_length=128)
    size: str = Field(max_length=128)
    status: Literal["enabled", "disabled"]
    style_status: Literal["enabled", "disabled"]
    match_routes: list[Literal["INTERNAL_IDENTITY", "SELLER_MAPPING"]]
    source_scopes: list[ReferenceScope] = Field(max_length=100)


class ReferenceMatch(StrictCatalogModel):
    status: Literal[
        "UNIQUE_CANDIDATE", "AMBIGUOUS", "DISABLED", "EXCLUDED", "UNMATCHED"
    ]
    candidates: list[ReferenceCandidate] = Field(max_length=100)
    excluded_scopes: list[ReferenceScope] = Field(max_length=100)


class ReferenceOrigin(StrictCatalogModel):
    origin: Literal["A_LOCAL_PUBLISHED_CATALOG"]
    source_run_id: str = Field(pattern=r"^[a-f0-9]{32}$")
    site_id: str = Field(pattern=r"^[1-9][0-9]*$")
    site_code: str = Field(max_length=64)
    catalog_version_id: str = Field(pattern=r"^[1-9][0-9]*$")
    catalog_publication_revision: str = Field(pattern=r"^[0-9]+$")
    version_number: str = Field(pattern=r"^[1-9][0-9]*$")
    checked_at: str
    display_match_version: Literal["catalog_identity_key_v1"]
    seller_match_version: Literal["seller_sku_match_v1"]


class ReferenceProductSku(StrictCatalogModel):
    sku_id: str = Field(pattern=r"^[1-9][0-9]*$")
    sku_revision: str = Field(pattern=r"^[1-9][0-9]*$")
    code: str = Field(max_length=128)
    color: str = Field(max_length=128)
    size: str = Field(max_length=128)
    status: Literal["enabled", "disabled"]


class ReferenceProduct(StrictCatalogModel):
    style_id: str = Field(pattern=r"^[1-9][0-9]*$")
    style_revision: str = Field(pattern=r"^[1-9][0-9]*$")
    code: str = Field(max_length=128)
    name: str = Field(max_length=300)
    status: Literal["enabled", "disabled"]
    skus: list[ReferenceProductSku] = Field(max_length=1000)


class ReferenceSnapshot(StrictCatalogModel):
    schema_version: Literal["production-catalog-reference-v1"] = Field(alias="schema")
    consumer_site_id: str = Field(pattern=r"^[1-9][0-9]*$")
    source: ReferenceOrigin
    source_digests: list[str] = Field(min_length=1, max_length=3)
    matches: dict[str, ReferenceMatch]
    products: dict[str, list[ReferenceProduct]] = Field(default_factory=dict)
    products_checked_at: str | None = None


def source_product_hint(
    line: dict[str, object],
) -> tuple[str, Literal["SOURCE_COLUMN", "SKU_PREFIX_HINT"]] | None:
    """Locate a product for review, without resolving or rewriting an SKU."""
    style = line.get("style_code")
    if isinstance(style, str) and style:
        return style, "SOURCE_COLUMN"
    code = line.get("sku_code")
    prefix = re.match(r"^([0-9]{1,18})-", code) if isinstance(code, str) else None
    return (prefix[1], "SKU_PREFIX_HINT") if prefix else None


def catalog_reference(
    root: Path, source: dict[str, object], context: CurrentSiteContext
) -> dict[str, object]:
    path = root / "catalog-reference.json"
    if not path.is_file():
        return {"status": "NOT_CONFIGURED", "confirmation_enabled": False}
    try:
        if path.stat().st_size > 2_000_000:
            raise ValueError("reference exceeds its local contract")
        snapshot = ReferenceSnapshot.model_validate_json(path.read_bytes())
    except OSError, ValueError, ValidationError:
        return {"status": "UNAVAILABLE", "confirmation_enabled": False}
    if (
        snapshot.consumer_site_id != str(context.site_id)
        or source["source_digest"] not in snapshot.source_digests
    ):
        return {"status": "OUTSIDE_SCOPE", "confirmation_enabled": False}
    rows = []
    for line in cast(list[dict[str, object]], source["rows"]):
        match = snapshot.matches.get(str(line["sku_code"]))
        hint = source_product_hint(line)
        rows.append(
            {
                "source_row": line["source_row"],
                "source_sku": line["sku_code"],
                "product_lookup": (
                    {
                        "code": hint[0],
                        "basis": hint[1],
                        "checked": hint[0] in snapshot.products,
                        "candidates": [
                            product.model_dump()
                            for product in snapshot.products.get(hint[0], [])
                        ],
                    }
                    if hint
                    else None
                ),
                **(
                    match.model_dump()
                    if match
                    else {
                        "status": "UNMATCHED",
                        "candidates": [],
                        "excluded_scopes": [],
                    }
                ),
            }
        )
    return {
        "status": "CHECKED_SNAPSHOT",
        "source": snapshot.source.model_dump(),
        "products": {
            code: [product.model_dump() for product in candidates]
            for code, candidates in snapshot.products.items()
        },
        "products_checked_at": snapshot.products_checked_at,
        "counts": dict(Counter(str(row["status"]) for row in rows)),
        "rows": rows,
        "confirmation_enabled": False,
    }
