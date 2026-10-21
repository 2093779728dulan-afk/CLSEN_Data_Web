"""Release-scoped product analytics source selection and safe attestation."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from dataclasses import asdict, dataclass
from typing import Literal, cast

ProductAnalyticsSource = Literal["legacy_parser", "p0_catalog"]
_SOURCES = frozenset({"legacy_parser", "p0_catalog"})


def parse_product_analytics_source(value: str | None) -> ProductAnalyticsSource:
    """Accept only the two release-scoped modes; never infer or fall back."""
    if value not in _SOURCES:
        raise ValueError(
            "APP_PRODUCT_ANALYTICS_SOURCE must be legacy_parser or p0_catalog"
        )
    return cast(ProductAnalyticsSource, value)


def _digest(value: str, *, name: str) -> str:
    if len(value) != 64 or any(
        character not in "0123456789abcdef" for character in value
    ):
        raise ValueError(f"{name} must be a lowercase SHA-256 hex digest")
    return value


@dataclass(frozen=True, slots=True)
class CutoverAttestation:
    source: ProductAnalyticsSource
    release_id: str
    artifact_digest: str
    fact_tuple_digest: str
    catalog_version_id: str | None
    dedup_snapshot_id: str | None
    provenance_source: str
    reconciliation_digest: str
    manifest_digest: str


def build_cutover_attestation(
    *,
    source: ProductAnalyticsSource,
    release_id: str,
    artifact_digest: str,
    fact_tuple_digest: str,
    reconciliation_digest: str,
    catalog_version_id: str | None,
    dedup_snapshot_id: str | None,
) -> CutoverAttestation:
    if not release_id or len(release_id) > 128:
        raise ValueError("release_id must contain 1 to 128 characters")
    checked_artifact_digest = _digest(artifact_digest, name="artifact_digest")
    checked_fact_tuple_digest = _digest(fact_tuple_digest, name="fact_tuple_digest")
    checked_reconciliation_digest = _digest(
        reconciliation_digest, name="reconciliation_digest"
    )
    payload = {
        "artifact_digest": checked_artifact_digest,
        "catalog_version_id": catalog_version_id,
        "dedup_snapshot_id": dedup_snapshot_id,
        "fact_tuple_digest": checked_fact_tuple_digest,
        "provenance_source": source,
        "reconciliation_digest": checked_reconciliation_digest,
        "release_id": release_id,
        "source": source,
    }
    encoded = json.dumps(
        payload, ensure_ascii=True, separators=(",", ":"), sort_keys=True
    ).encode("ascii")
    return CutoverAttestation(
        source=source,
        release_id=release_id,
        artifact_digest=checked_artifact_digest,
        fact_tuple_digest=checked_fact_tuple_digest,
        catalog_version_id=catalog_version_id,
        dedup_snapshot_id=dedup_snapshot_id,
        provenance_source=source,
        reconciliation_digest=checked_reconciliation_digest,
        manifest_digest=hashlib.sha256(encoded).hexdigest(),
    )


def attestation_from_environment(
    environment: Mapping[str, str],
    *,
    catalog_version_id: str | None = None,
    dedup_snapshot_id: str | None = None,
) -> CutoverAttestation:
    return build_cutover_attestation(
        source=parse_product_analytics_source(
            environment.get("APP_PRODUCT_ANALYTICS_SOURCE")
        ),
        release_id=environment.get("APP_RELEASE_ID", ""),
        artifact_digest=environment.get("APP_ARTIFACT_DIGEST", ""),
        fact_tuple_digest=environment.get("APP_FACT_TUPLE_DIGEST", ""),
        reconciliation_digest=environment.get("APP_RECONCILIATION_DIGEST", ""),
        catalog_version_id=catalog_version_id,
        dedup_snapshot_id=dedup_snapshot_id,
    )


def public_attestation(attestation: CutoverAttestation) -> dict[str, str | None]:
    """Return only non-sensitive release evidence fields."""
    return asdict(attestation)


__all__ = [
    "CutoverAttestation",
    "ProductAnalyticsSource",
    "attestation_from_environment",
    "build_cutover_attestation",
    "parse_product_analytics_source",
    "public_attestation",
]
