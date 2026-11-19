"""Resolve only immutable production evidence, never invented report facts."""

from __future__ import annotations

import hashlib
import json

import sqlalchemy as sa
from sqlalchemy.engine import Connection

from app.catalog.normalization import seller_sku_match_v1


class ProductionCodeEvidenceInvalid(ValueError):
    code = "catalog_validation_failed"


def production_source_key(
    connection: Connection,
    *,
    site_id: int,
    export_id: int,
    raw_sha256_ref: str,
    scope_ref: str | None = None,
) -> tuple[int, bytes, bytes] | None:
    value = connection.scalar(
        sa.text(
            "SELECT evidence_payload_json FROM catalog_export_payloads WHERE "
            "site_id=:site AND export_id=:id"
        ),
        {"site": site_id, "id": export_id},
    )
    if value is None:
        return None
    payload = json.loads(value) if isinstance(value, str) else value
    source = payload.get("production_source")
    if source is None:
        return None
    schema = source.get("source_schema")
    report_selection = source.get("report_selection")
    if schema is not None or report_selection is not None:
        if report_selection is not None and (
            schema is not None or report_selection.get("version") != 1
        ):
            raise ProductionCodeEvidenceInvalid(
                "Unknown report selection evidence version."
            )
        if report_selection is None and schema != "amazon_listing_v1":
            raise ProductionCodeEvidenceInvalid("Unknown production source schema.")
        listing_matches = [
            r
            for r in source.get("selections", [])
            if r.get("record_type")
            in ({"variant", "excluded"} if report_selection else {"variant"})
            and r.get("platform_mapping")
            and str(r.get("scope_id")) == scope_ref
            and "sha256:" + hashlib.sha256(r["seller_sku"].encode()).hexdigest()
            == raw_sha256_ref
        ]
        identities = {(int(r["scope_id"]), r["seller_sku"]) for r in listing_matches}
        if len(identities) != 1:
            raise ProductionCodeEvidenceInvalid(
                "Listing scope and raw source key do not match."
            )
        scope, raw = next(iter(identities))
        key = seller_sku_match_v1(raw)
        return scope, key.sha256, key.utf8
    scope = source.get("report_source_scope_id")
    if scope is None or not source.get("channel_evidence"):
        raise ProductionCodeEvidenceInvalid("Production channel evidence is missing.")
    valid = connection.scalar(
        sa.text(
            "SELECT id FROM report_source_scopes WHERE id=:scope AND site_id=:site "
            "AND marketplace_scope_code='amazon_us'"
        ),
        {"scope": scope, "site": site_id},
    )
    if valid is None:
        raise ProductionCodeEvidenceInvalid("Production source scope is invalid.")
    matches = {
        row["formal_sku"]
        for row in source["rows"]
        if row.get("formal_sku")
        and "sha256:" + hashlib.sha256(row["formal_sku"].encode("utf-8")).hexdigest()
        == raw_sha256_ref
    }
    if len(matches) != 1:
        raise ProductionCodeEvidenceInvalid(
            "Production source key is not supported by its evidence."
        )
    key = seller_sku_match_v1(next(iter(matches)))
    return int(scope), key.sha256, key.utf8
