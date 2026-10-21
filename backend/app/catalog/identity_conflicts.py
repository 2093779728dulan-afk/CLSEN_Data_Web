# ruff: noqa: E501
"""Read the shared identity owners without exposing raw source identifiers."""

import hashlib
import json

import sqlalchemy as sa
from sqlalchemy.engine import Engine

from app.catalog.import_repository import (
    CatalogImportRepositoryError,
    _source_decision_key,
)


def identity_owners(
    engine: Engine, *, site_id: int, import_id: int, row_key: str
) -> dict[str, object]:
    with engine.connect() as connection:
        imported = (
            connection.execute(
                sa.text(
                    "SELECT export_id, workflow_revision FROM catalog_imports WHERE id=:id AND site_id=:site"
                ),
                {"id": import_id, "site": site_id},
            )
            .mappings()
            .one_or_none()
        )
        if imported is None:
            raise CatalogImportRepositoryError()
        row = connection.execute(
            sa.text(
                "SELECT payload_json FROM catalog_import_rows WHERE import_id=:id AND site_id=:site "
                "AND section='mappings' AND row_key=:key AND workflow_revision<=:revision "
                "ORDER BY workflow_revision DESC LIMIT 1"
            ),
            {
                "id": import_id,
                "site": site_id,
                "key": row_key,
                "revision": imported["workflow_revision"],
            },
        ).scalar_one_or_none()
        payload = json.loads(row) if isinstance(row, str) else row
        if not isinstance(payload, dict):
            raise CatalogImportRepositoryError()
        scope, digest, key_bytes = _source_decision_key(
            connection,
            site_id=site_id,
            export_id=int(imported["export_id"]),
            raw_sha256_ref=payload["seller_sku_sha256"],
        )
        params = {"site": site_id, "scope": scope, "digest": digest, "key": key_bytes}
        predicate = (
            "site_id=:site AND report_source_scope_id=:scope AND marketplace_scope_code='amazon_us' "
            "AND seller_sku_match_sha256=:digest AND seller_sku_match_bytes=:key"
        )
        drafts = [
            dict(item)
            for item in connection.execute(
                sa.text(
                    "SELECT import_id, decision_kind, target_sku_row_key FROM catalog_draft_identity_reservations WHERE "
                    + predicate
                ),
                params,
            ).mappings()
        ]
        formal = [
            dict(item)
            for item in connection.execute(
                sa.text(
                    "SELECT DISTINCT sku_id, (SELECT style_id FROM product_skus WHERE id=sku_id) AS style_id FROM product_catalog_mappings WHERE "
                    + predicate
                ),
                params,
            ).mappings()
        ]
        ignored = [
            dict(item)
            for item in connection.execute(
                sa.text(
                    "SELECT catalog_version_id, reason FROM product_catalog_exclusions WHERE "
                    + predicate
                    + " AND catalog_version_id=(SELECT current_catalog_version_id FROM product_catalog_publications WHERE site_id=:site)"
                ),
                params,
            ).mappings()
        ]
        return {
            "identity_key": hashlib.sha256(
                f"{site_id}:{scope}:amazon_us:".encode() + key_bytes
            ).hexdigest(),
            "drafts": drafts,
            "formal": formal,
            "ignored": ignored,
            "workflow_revision": imported["workflow_revision"],
        }
