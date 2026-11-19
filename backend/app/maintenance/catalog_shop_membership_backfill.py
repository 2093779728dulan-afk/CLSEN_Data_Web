"""Reconstruct shop projections from approved identities and version lineage."""

from __future__ import annotations

import hashlib

import sqlalchemy as sa
from sqlalchemy.engine import Connection

from app.catalog.canonical_json import canonical_json_bytes


def backfill_shop_memberships(connection: Connection) -> None:
    versions = (
        connection.execute(
            sa.text("""
        SELECT v.site_id,v.id,v.base_catalog_version_id,e.event_kind,
               c.resource_id restore_target
        FROM product_catalog_versions v
        LEFT JOIN product_catalog_publication_events e
          ON e.site_id=v.site_id AND e.catalog_version_id=v.id
        LEFT JOIN catalog_command_claims c ON c.site_id=e.site_id
          AND c.operation_token=e.operation_token AND c.operation_kind='restore'
          AND c.status='completed'
        ORDER BY v.site_id,v.version_number,v.id
    """)
        )
        .mappings()
        .all()
    )
    members: dict[tuple[int, int], set[int]] = {}
    for site, version, sku in connection.execute(
        sa.text(
            "SELECT site_id,catalog_version_id,sku_id FROM product_catalog_sku_members"
        )
    ):
        members.setdefault((site, version), set()).add(sku)

    origins = (
        connection.execute(
            sa.text("""
        SELECT DISTINCT v.site_id,v.id version_id,s.id scope_id,r.sku_id,
               i.id import_id,r.row_key,
               EXISTS (
                 SELECT 1 FROM catalog_import_rows x
                 WHERE x.site_id=i.site_id AND x.import_id=i.id
                   AND x.section='mappings' AND x.projection_state='included'
                   AND x.workflow_revision=(
                     SELECT MAX(y.workflow_revision) FROM catalog_import_rows y
                     WHERE y.import_id=i.id AND y.section='mappings'
                       AND y.workflow_revision<=i.workflow_revision)
                   AND JSON_UNQUOTE(JSON_EXTRACT(x.payload_json,
                         '$.identity_decision'))='excluded'
                   AND JSON_UNQUOTE(JSON_EXTRACT(x.payload_json,
                         '$.seller_account'))=CAST(s.id AS CHAR)
                   AND COALESCE(
                     NULLIF(JSON_UNQUOTE(JSON_EXTRACT(x.payload_json,
                         '$.review_target_sku_row_key')),'null'),
                     JSON_UNQUOTE(JSON_EXTRACT(x.payload_json,
                         '$.source_target_sku_row_key')))=r.row_key
               ) excluded_source
        FROM product_catalog_versions v
        JOIN catalog_imports i ON i.id=v.source_import_id AND i.site_id=v.site_id
          AND i.source_kind='production' AND i.status='approved'
        JOIN catalog_export_payloads p ON p.export_id=i.export_id
          AND p.site_id=i.site_id
        JOIN report_source_scopes s ON s.site_id=v.site_id AND s.id=
          JSON_EXTRACT(p.evidence_payload_json,'$.production_source.report_source_scope_id')
        JOIN JSON_TABLE(p.evidence_payload_json,'$.production_source.observations[*]'
          COLUMNS(sku_id BIGINT PATH '$.sku_id' NULL ON EMPTY,
                  row_key VARCHAR(128) PATH '$.sku_row_key' NULL ON EMPTY)) r
        JOIN catalog_import_rows d ON d.import_id=i.id AND d.site_id=i.site_id
          AND d.section='skus' AND d.row_key=r.row_key
          AND d.projection_state='included' AND d.workflow_revision=(
            SELECT MAX(x.workflow_revision) FROM catalog_import_rows x
            WHERE x.import_id=i.id AND x.section='skus'
              AND x.workflow_revision<=i.workflow_revision)
          AND JSON_UNQUOTE(JSON_EXTRACT(d.payload_json,'$.system_sku_id'))=r.sku_id
        JOIN product_catalog_sku_members m ON m.site_id=v.site_id
          AND m.catalog_version_id=v.id AND m.sku_id=r.sku_id
        WHERE r.row_key IS NOT NULL
    """)
        )
        .mappings()
        .all()
    )

    # Keep independently approved shop evidence separate from external mappings:
    # copying old mappings would resurrect the explicitly removed Wuhan goods.
    direct: dict[tuple[int, int], dict[tuple[int, int], tuple[int, str]]] = {}
    invalid_origins = set()
    for row in origins:
        origin = (row["import_id"], row["row_key"])
        if row["excluded_source"]:
            invalid_origins.add(
                (row["site_id"], row["scope_id"], row["sku_id"], *origin)
            )
        else:
            direct.setdefault((row["site_id"], row["version_id"]), {})[
                (row["scope_id"], row["sku_id"])
            ] = origin

    inherited: dict[tuple[int, int], dict[tuple[int, int], tuple[int, str]]] = {}
    additions = []
    for row in versions:
        site, version = row["site_id"], row["id"]
        parent = row["base_catalog_version_id"]
        if row["event_kind"] == "restore":
            parent = row["restore_target"]
            if parent is None:
                raise RuntimeError(
                    "Restore target evidence is required for shop backfill"
                )
        if parent is not None and (site, parent) not in inherited:
            raise RuntimeError("Catalog lineage is incomplete for shop backfill")
        proof = {
            key: value
            for key, value in inherited.get((site, parent), {}).items()
            if key[1] in members.get((site, version), set())
        }
        proof.update(direct.get((site, version), {}))
        inherited[(site, version)] = proof
        for (scope, sku), (import_id, row_key) in proof.items():
            additions.append(
                {
                    "site": site,
                    "version": version,
                    "scope": scope,
                    "sku": sku,
                    "import_id": import_id,
                    "row_key": row_key,
                    "digest": hashlib.sha256(
                        canonical_json_bytes([import_id, scope, row_key])
                    ).digest(),
                }
            )

    # Correct only memberships introduced from a rejected source association by
    # 0036. Earlier valid membership has a different origin and is retained.
    if invalid_origins:
        connection.execute(
            sa.text("""
            DELETE FROM product_catalog_shop_memberships
            WHERE site_id=:site AND report_source_scope_id=:scope AND sku_id=:sku
              AND source_import_id=:import_id AND source_row_key=:row_key
        """),
            [
                dict(
                    zip(
                        ("site", "scope", "sku", "import_id", "row_key"),
                        values,
                        strict=True,
                    )
                )
                for values in sorted(invalid_origins)
            ],
        )

    connection.execute(
        sa.text("""
        INSERT INTO product_catalog_shop_memberships
          (site_id,catalog_version_id,report_source_scope_id,sku_id,evidence_digest)
        SELECT m.site_id,m.catalog_version_id,m.report_source_scope_id,m.sku_id,
               MIN(m.evidence_digest)
        FROM product_catalog_mappings m
        WHERE NOT EXISTS (SELECT 1 FROM product_catalog_shop_memberships g
          WHERE g.site_id=m.site_id AND g.catalog_version_id=m.catalog_version_id
            AND g.report_source_scope_id=m.report_source_scope_id AND g.sku_id=m.sku_id)
        GROUP BY m.site_id,m.catalog_version_id,m.report_source_scope_id,m.sku_id
    """)
    )
    if additions:
        connection.execute(
            sa.text("""
            INSERT INTO product_catalog_shop_memberships
              (site_id,catalog_version_id,report_source_scope_id,sku_id,
               source_import_id,source_row_key,evidence_digest)
            SELECT :site,:version,:scope,:sku,:import_id,:row_key,:digest
            WHERE NOT EXISTS (SELECT 1 FROM product_catalog_shop_memberships
              WHERE site_id=:site AND catalog_version_id=:version
                AND report_source_scope_id=:scope AND sku_id=:sku)
        """),
            additions,
        )
