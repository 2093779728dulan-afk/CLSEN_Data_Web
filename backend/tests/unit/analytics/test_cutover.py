from __future__ import annotations

import pytest
from app.analytics.cutover import (
    attestation_from_environment,
    build_cutover_attestation,
    parse_product_analytics_source,
    public_attestation,
)


@pytest.mark.parametrize("value", [None, "", "P0_catalog", "mixed", "legacy_parser "])
def test_source_selector_fails_closed(value: str | None) -> None:
    with pytest.raises(ValueError, match="APP_PRODUCT_ANALYTICS_SOURCE"):
        parse_product_analytics_source(value)


def test_source_selector_accepts_only_release_modes() -> None:
    assert parse_product_analytics_source("legacy_parser") == "legacy_parser"
    assert parse_product_analytics_source("p0_catalog") == "p0_catalog"


def test_attestation_is_deterministic_and_redacted() -> None:
    digest = "a" * 64
    attestation = build_cutover_attestation(
        source="p0_catalog",
        release_id="candidate-1",
        artifact_digest=digest,
        fact_tuple_digest="b" * 64,
        reconciliation_digest="c" * 64,
        catalog_version_id="7",
        dedup_snapshot_id="9",
    )
    assert attestation == build_cutover_attestation(
        source="p0_catalog",
        release_id="candidate-1",
        artifact_digest=digest,
        fact_tuple_digest="b" * 64,
        reconciliation_digest="c" * 64,
        catalog_version_id="7",
        dedup_snapshot_id="9",
    )
    assert len(attestation.manifest_digest) == 64
    assert "password" not in public_attestation(attestation)


def test_environment_requires_every_release_evidence_field() -> None:
    with pytest.raises(ValueError):
        attestation_from_environment({"APP_PRODUCT_ANALYTICS_SOURCE": "p0_catalog"})
