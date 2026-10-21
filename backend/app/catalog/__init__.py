"""Product catalog primitives with frozen identity semantics."""

from app.catalog.canonical_json import canonical_json_bytes, canonical_sha256
from app.catalog.normalization import (
    UCD_VERSION,
    catalog_identity_key_v1,
    safe_source_projection_v1,
    seller_sku_match_v1,
)
from app.catalog.source_refs import SafeSourceRef, make_safe_source_ref

__all__ = (
    "UCD_VERSION",
    "SafeSourceRef",
    "canonical_json_bytes",
    "canonical_sha256",
    "catalog_identity_key_v1",
    "make_safe_source_ref",
    "safe_source_projection_v1",
    "seller_sku_match_v1",
)
