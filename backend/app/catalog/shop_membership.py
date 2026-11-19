"""Approved shop membership, independent of external listing identifiers."""

from __future__ import annotations

import hashlib
from collections.abc import Mapping

import sqlalchemy as sa
from sqlalchemy.engine import Connection

from app.catalog.canonical_json import canonical_json_bytes
from app.catalog.production_sources import production_evidence


def copy_shop_memberships(
    connection: Connection, *, site_id: int, source_version: int, version_id: int
) -> None:
    connection.execute(
        sa.text(
            "INSERT INTO product_catalog_shop_memberships "
            "(site_id,catalog_version_id,report_source_scope_id,sku_id,"
            "source_import_id,source_row_key,evidence_digest) "
            "SELECT m.site_id,:version,m.report_source_scope_id,m.sku_id,"
            "m.source_import_id,m.source_row_key,m.evidence_digest "
            "FROM product_catalog_shop_memberships m "
            "JOIN product_catalog_sku_members s ON s.site_id=m.site_id "
            "AND s.catalog_version_id=:version AND s.sku_id=m.sku_id "
            "WHERE m.site_id=:site AND m.catalog_version_id=:source"
        ),
        {"site": site_id, "source": source_version, "version": version_id},
    )


def record_shop_memberships(
    connection: Connection,
    *,
    site_id: int,
    version_id: int,
    import_id: int,
    sku_members: Mapping[str, tuple[int, int, int]],
) -> None:
    # Mappings remain authoritative evidence of membership, but membership does
    # not manufacture a mapping for products that have not been listed.
    connection.execute(
        sa.text(
            "INSERT INTO product_catalog_shop_memberships "
            "(site_id,catalog_version_id,report_source_scope_id,sku_id,"
            "source_import_id,source_row_key,evidence_digest) "
            "SELECT m.site_id,m.catalog_version_id,m.report_source_scope_id,"
            "m.sku_id,:import_id,NULL,MIN(m.evidence_digest) "
            "FROM product_catalog_mappings m WHERE m.site_id=:site "
            "AND m.catalog_version_id=:version AND NOT EXISTS "
            "(SELECT 1 FROM product_catalog_shop_memberships g "
            "WHERE g.site_id=m.site_id AND g.catalog_version_id=m.catalog_version_id "
            "AND g.report_source_scope_id=m.report_source_scope_id AND "
            "g.sku_id=m.sku_id) "
            "GROUP BY m.site_id,m.catalog_version_id,m.report_source_scope_id,m.sku_id"
        ),
        {"site": site_id, "version": version_id, "import_id": import_id},
    )
    evidence = production_evidence(connection, import_id=import_id, site_id=site_id)
    if not evidence or not evidence.get("report_source_scope_id"):
        return
    scope_id = int(str(evidence["report_source_scope_id"]))
    excluded_keys = set(
        connection.scalars(
            sa.text("""
        SELECT COALESCE(
          NULLIF(JSON_UNQUOTE(JSON_EXTRACT(d.payload_json,
            '$.review_target_sku_row_key')),'null'),
          JSON_UNQUOTE(JSON_EXTRACT(d.payload_json,'$.source_target_sku_row_key')))
        FROM catalog_import_rows d
        WHERE d.site_id=:site AND d.import_id=:import_id AND d.section='mappings'
          AND d.projection_state='included' AND d.workflow_revision=(
            SELECT MAX(x.workflow_revision) FROM catalog_import_rows x
            WHERE x.import_id=d.import_id AND x.section='mappings')
          AND JSON_UNQUOTE(JSON_EXTRACT(d.payload_json,
            '$.identity_decision'))='excluded'
          AND JSON_UNQUOTE(JSON_EXTRACT(d.payload_json,'$.seller_account'))=:scope
    """),
            {"site": site_id, "import_id": import_id, "scope": str(scope_id)},
        )
    )
    observations = evidence.get("observations", [])
    if not isinstance(observations, list):
        return
    rows = []
    for observation in observations:
        if not isinstance(observation, dict):
            continue
        key = str(observation.get("sku_row_key", ""))
        # Only final reachable, approved SKU rows count. Preview observations
        # alone cannot add a discarded or unresolved candidate to a shop.
        if key not in sku_members or key in excluded_keys:
            continue
        rows.append(
            {
                "site": site_id,
                "version": version_id,
                "scope": scope_id,
                "sku": sku_members[key][0],
                "import_id": import_id,
                "row_key": key,
                "digest": hashlib.sha256(
                    canonical_json_bytes([import_id, scope_id, key])
                ).digest(),
            }
        )
    if rows:
        connection.execute(
            sa.text(
                "INSERT INTO product_catalog_shop_memberships "
                "(site_id,catalog_version_id,report_source_scope_id,sku_id,"
                "source_import_id,source_row_key,evidence_digest) "
                "SELECT :site,:version,:scope,:sku,:import_id,:row_key,:digest "
                "WHERE NOT EXISTS (SELECT 1 FROM product_catalog_shop_memberships "
                "WHERE site_id=:site AND catalog_version_id=:version "
                "AND report_source_scope_id=:scope AND sku_id=:sku)"
            ),
            rows,
        )
