"""Content-free catalog errors safe for logs and API error mapping."""

from __future__ import annotations


class CatalogError(Exception):
    """Base error that exposes only a stable code."""

    code = "catalog_error"

    def __init__(self) -> None:
        super().__init__(self.code)

    def __repr__(self) -> str:
        return f"{type(self).__name__}(code={self.code!r})"


class CatalogDataIntegrityError(CatalogError):
    """Raised when frozen local reference data cannot be trusted."""

    code = "catalog_reference_data_integrity_failed"


class CatalogCanonicalJsonError(CatalogError, TypeError):
    """Raised when a value is outside the canonical JSON profile."""

    code = "catalog_canonical_json_value_invalid"


class CatalogNormalizationError(CatalogError, ValueError):
    """Raised for invalid scalar input or an empty required identity key."""

    code = "catalog_normalization_input_invalid"
