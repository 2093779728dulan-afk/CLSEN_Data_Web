from __future__ import annotations

import json

from app.analytics.cutover import build_cutover_attestation, public_attestation
from app.catalog.source_refs import make_safe_source_ref
from app.catalog.types import CatalogSourceKind


def test_release_evidence_and_safe_refs_never_emit_sensitive_raw_values() -> None:
    dangerous = 'LIVE-DANGER</script>&"RAW'
    reference = make_safe_source_ref(
        source_ref_id="src_release_test",
        raw_value=dangerous,
        source_kind=CatalogSourceKind.SELLER_SKU,
    )
    attestation = public_attestation(
        build_cutover_attestation(
            source="p0_catalog",
            release_id="candidate-local",
            artifact_digest="a" * 64,
            fact_tuple_digest="b" * 64,
            reconciliation_digest="c" * 64,
            catalog_version_id="7",
            dedup_snapshot_id="9",
        )
    )
    encoded = json.dumps(
        {"attestation": attestation, "source": reference.model_dump()},
        sort_keys=True,
    )
    assert dangerous not in encoded
    for fragment in (dangerous, "</script>", '>&"'):
        assert fragment not in encoded
    assert reference.sha256.startswith("sha256:")


def test_release_evidence_allowlist_has_no_secret_or_raw_fields() -> None:
    allowed = {
        "artifact_digest",
        "candidate_style_count",
        "consistent_as_of",
        "distinct_seller_sku_count",
        "normalization_version",
        "query_digest",
        "report_membership_counts",
        "safe_output",
        "strict_seller_sku_count",
        "anomaly_count",
    }
    forbidden_fields = {
        "password",
        "seller_sku",
        "title",
        "order_id",
        "customer_comments",
        "license_plate_number",
    }
    assert allowed.isdisjoint(forbidden_fields)
