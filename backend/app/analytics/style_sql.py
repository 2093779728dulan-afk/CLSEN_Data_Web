"""Bounded MySQL statements for stable catalog-backed style analytics.

Every fact statement starts from a caller-frozen publication member set and the
selected catalog version.  The statements deliberately never import or invoke
the legacy Seller SKU parser.
"""

from __future__ import annotations

from typing import Final, Literal

import sqlalchemy as sa
from sqlalchemy.sql.elements import TextClause

CURRENT_CONTEXT_SQL: Final = sa.text(
    """
    SELECT catalogs.id AS catalog_version_id,
           catalogs.version_number AS catalog_version,
           scopes.id AS report_source_scope_id,
           configs.id AS site_config_version_id,
           configs.reporting_timezone,
           dedup.current_snapshot_id AS return_dedup_snapshot_id,
           snapshots.return_publication_set_digest,
           snapshots.decision_digest
    FROM product_catalog_publications AS catalog_pointer
    INNER JOIN product_catalog_versions AS catalogs
        ON catalogs.id = catalog_pointer.current_catalog_version_id
       AND catalogs.site_id = catalog_pointer.site_id
       AND catalogs.status = 'ready'
    INNER JOIN report_source_scopes AS scopes
        ON scopes.site_id = catalogs.site_id
    INNER JOIN site_current_configs AS current_configs
        ON current_configs.site_id = catalogs.site_id
    INNER JOIN site_config_versions AS configs
        ON configs.id = current_configs.current_config_version_id
       AND configs.site_id = catalogs.site_id
    INNER JOIN return_dedup_publications AS dedup
        ON dedup.site_id = catalogs.site_id
       AND dedup.report_source_scope_id = scopes.id
    INNER JOIN return_dedup_snapshots AS snapshots
        ON snapshots.id = dedup.current_snapshot_id
       AND snapshots.site_id = catalogs.site_id
       AND snapshots.report_source_scope_id = scopes.id
       AND snapshots.status = 'ready'
    WHERE catalog_pointer.site_id = :site_id
    """
)


SNAPSHOT_CONTEXT_SQL: Final = sa.text(
    """
    SELECT catalogs.id AS catalog_version_id,
           catalogs.version_number AS catalog_version,
           tuples.report_source_scope_id,
           tuples.publication_snapshot_id,
           tuples.return_dedup_snapshot_id,
           tuples.site_config_version_id,
           tuples.fact_cutoff_at,
           tuples.return_publication_set_digest,
           configs.reporting_timezone,
           snapshots.coverage_start_date,
           snapshots.coverage_end_date
    FROM product_catalog_versions AS catalogs
    INNER JOIN fact_snapshot_tuples AS tuples
        ON tuples.id = catalogs.fact_snapshot_tuple_id
       AND tuples.site_id = catalogs.site_id
       AND tuples.status = 'ready'
    INNER JOIN publication_snapshots AS snapshots
        ON snapshots.id = tuples.publication_snapshot_id
       AND snapshots.site_id = tuples.site_id
       AND snapshots.status = 'ready'
    INNER JOIN return_dedup_snapshots AS dedup_snapshots
        ON dedup_snapshots.id = tuples.return_dedup_snapshot_id
       AND dedup_snapshots.site_id = tuples.site_id
       AND dedup_snapshots.status = 'ready'
       AND dedup_snapshots.return_publication_set_digest =
           tuples.return_publication_set_digest
    INNER JOIN site_config_versions AS configs
        ON configs.id = tuples.site_config_version_id
       AND configs.site_id = tuples.site_id
    WHERE catalogs.site_id = :site_id
      AND catalogs.id = :catalog_version_id
      AND catalogs.status = 'ready'
    """
)


CURRENT_MEMBERS_SQL: Final = sa.text(
    """
    SELECT datasets.report_type, datasets.report_date,
           CASE WHEN publications.version_id IS NULL
                THEN 'missing' ELSE 'published' END AS report_status,
           CASE WHEN publications.version_id IS NULL
                THEN NULL ELSE datasets.id END AS dataset_id,
           publications.version_id AS published_version_id,
           NULL AS snapshot_member_id,
           revisions.publication_revision AS pointer_revision
    FROM report_dataset_scope_assignments AS assignments
    INNER JOIN daily_datasets AS datasets
        ON datasets.id = assignments.dataset_id
       AND datasets.site_id = assignments.site_id
    INNER JOIN report_publication_revisions AS revisions
        ON revisions.dataset_id = datasets.id
       AND revisions.site_id = assignments.site_id
       AND revisions.report_source_scope_id = assignments.report_source_scope_id
    LEFT JOIN dataset_publications AS publications
        ON publications.dataset_id = datasets.id
    WHERE assignments.site_id = :site_id
      AND assignments.report_source_scope_id = :report_source_scope_id
      AND datasets.report_date BETWEEN :member_from_date AND :member_to_date
    ORDER BY datasets.report_type, datasets.report_date
    """
)


SNAPSHOT_MEMBERS_SQL: Final = sa.text(
    """
    SELECT members.report_type, members.report_date,
           members.member_status AS report_status,
           members.dataset_id, members.published_version_id,
           members.id AS snapshot_member_id,
           members.publication_pointer_revision AS pointer_revision
    FROM publication_snapshot_members AS members
    WHERE members.site_id = :site_id
      AND members.publication_snapshot_id = :publication_snapshot_id
      AND members.report_date BETWEEN :member_from_date AND :member_to_date
    ORDER BY members.report_type, members.report_date
    """
)


ALL_CURRENT_RETURN_MEMBERS_SQL: Final = sa.text(
    """
    SELECT datasets.id AS dataset_id, publications.version_id AS published_version_id,
           revisions.publication_revision AS pointer_revision,
           versions.data_revision, datasets.report_date
    FROM report_dataset_scope_assignments AS assignments
    INNER JOIN daily_datasets AS datasets
        ON datasets.id = assignments.dataset_id
       AND datasets.site_id = assignments.site_id
       AND datasets.report_type = 'return_report'
    INNER JOIN report_publication_revisions AS revisions
        ON revisions.dataset_id = datasets.id
       AND revisions.site_id = assignments.site_id
       AND revisions.report_source_scope_id = assignments.report_source_scope_id
    INNER JOIN dataset_publications AS publications
        ON publications.dataset_id = datasets.id
    INNER JOIN dataset_versions AS versions
        ON versions.id = publications.version_id
       AND versions.dataset_id = datasets.id
       AND versions.status = 'published'
    WHERE assignments.site_id = :site_id
      AND assignments.report_source_scope_id = :report_source_scope_id
    ORDER BY datasets.report_date, datasets.id
    """
)


_LATEST_KEY_PREDICATE = """
(
    source_keys.source_key_revision <= published_versions.data_revision
    AND (
        published_versions.data_revision = 0
        OR NOT EXISTS (
            SELECT 1
            FROM report_source_keys AS newer_source_keys
            WHERE newer_source_keys.version_id = source_keys.version_id
              AND newer_source_keys.source_row_id = source_keys.source_row_id
              AND newer_source_keys.source_key_revision >
                  source_keys.source_key_revision
        )
    )
)"""


_DEDUP_STATE = """
snapshot_chain AS (
    SELECT snapshots.id, snapshots.base_snapshot_id, 0 AS chain_rank
    FROM return_dedup_snapshots AS snapshots
    WHERE snapshots.id = :return_dedup_snapshot_id
      AND snapshots.site_id = :site_id
      AND snapshots.report_source_scope_id = :report_source_scope_id
      AND snapshots.status = 'ready'
    UNION ALL
    SELECT prior.id, prior.base_snapshot_id, chain.chain_rank + 1
    FROM snapshot_chain AS chain
    INNER JOIN return_dedup_snapshots AS prior
        ON prior.id = chain.base_snapshot_id
       AND prior.site_id = :site_id
       AND prior.status = 'ready'
    WHERE chain.chain_rank < 32
),
ranked_group_entries AS (
    SELECT revisions.id AS group_revision_id,
           revisions.decision, revisions.canonical_source_key_id,
           revisions.group_key_sha256, entries.entry_kind,
           ROW_NUMBER() OVER (
               PARTITION BY revisions.group_key_sha256
               ORDER BY chain.chain_rank, entries.id DESC
           ) AS entry_rank
    FROM snapshot_chain AS chain
    INNER JOIN return_dedup_snapshot_groups AS entries
        ON entries.snapshot_id = chain.id
    INNER JOIN return_dedup_group_revisions AS revisions
        ON revisions.id = entries.group_revision_id
       AND revisions.site_id = :site_id
       AND revisions.report_source_scope_id = :report_source_scope_id
),
effective_groups AS (
    SELECT group_revision_id, decision, canonical_source_key_id
    FROM ranked_group_entries
    WHERE entry_rank = 1 AND entry_kind <> 'remove'
),
effective_members AS (
    SELECT members.source_key_id, effective.decision,
           effective.canonical_source_key_id
    FROM effective_groups AS effective
    INNER JOIN return_dedup_group_members AS members
        ON members.group_revision_id = effective.group_revision_id
)"""


BUSINESS_BUCKETS_SQL: Final = sa.text(
    f"""
    WITH classified AS (
        SELECT row_records.version_id AS published_version_id,
               report_rows.units_ordered, report_rows.ordered_product_sales,
               report_rows.sessions_total,
               CASE WHEN mappings.id IS NOT NULL THEN 'mapped'
                    WHEN exclusions.id IS NOT NULL THEN 'excluded'
                    ELSE 'unmatched' END AS result_bucket
        FROM version_rows AS row_records
        INNER JOIN business_report_rows AS report_rows
            ON report_rows.version_row_id = row_records.id
           AND report_rows.version_id = row_records.version_id
        INNER JOIN report_source_keys AS source_keys
            ON source_keys.version_id = row_records.version_id
           AND source_keys.source_row_id = row_records.id
           AND source_keys.site_id = :site_id
           AND source_keys.report_source_scope_id = :report_source_scope_id
           AND source_keys.report_type = 'business_report'
           AND source_keys.version_id IN :business_version_ids
        INNER JOIN daily_datasets AS datasets
            ON datasets.id = source_keys.dataset_id
           AND datasets.site_id = :site_id
           AND datasets.report_date BETWEEN :from_date AND :to_date
        INNER JOIN dataset_versions AS published_versions
            ON published_versions.id = row_records.version_id
           AND published_versions.id IN :business_version_ids
           AND published_versions.status = 'published'
        LEFT JOIN product_catalog_mappings AS mappings
            ON mappings.catalog_version_id = :catalog_version_id
           AND mappings.site_id = :site_id
           AND mappings.report_source_scope_id = :report_source_scope_id
           AND mappings.seller_sku_match_sha256 =
               source_keys.seller_sku_match_sha256
           AND mappings.seller_sku_match_bytes = source_keys.seller_sku_match_bytes
        LEFT JOIN product_catalog_exclusions AS exclusions
            ON exclusions.catalog_version_id = :catalog_version_id
           AND exclusions.site_id = :site_id
           AND exclusions.report_source_scope_id = :report_source_scope_id
           AND exclusions.seller_sku_match_sha256 =
               source_keys.seller_sku_match_sha256
           AND exclusions.seller_sku_match_bytes = source_keys.seller_sku_match_bytes
        WHERE row_records.row_state = 'active'
          AND source_keys.seller_sku_match_bytes IS NOT NULL
          AND {_LATEST_KEY_PREDICATE}
    )
    SELECT result_bucket, COUNT(*) AS fact_rows,
           COALESCE(SUM(units_ordered), 0) AS units,
           COALESCE(SUM(ordered_product_sales), 0) AS sales,
           COALESCE(SUM(sessions_total), 0) AS sessions
    FROM classified
    GROUP BY result_bucket
    """
).bindparams(sa.bindparam("business_version_ids", expanding=True))


_RETURN_CLASSIFIED = f"""
WITH RECURSIVE {_DEDUP_STATE},
qualified_returns AS (
    SELECT row_records.id AS active_row_id, row_records.version_id,
           source_keys.id AS source_key_id, source_keys.dataset_id,
           source_keys.seller_sku_match_sha256,
           source_keys.seller_sku_match_bytes,
           return_values.return_date, return_values.quantity
    FROM version_rows AS row_records
    INNER JOIN return_report_rows AS return_values
        ON return_values.version_row_id = row_records.id
       AND return_values.version_id = row_records.version_id
    INNER JOIN report_source_keys AS source_keys
        ON source_keys.version_id = row_records.version_id
       AND source_keys.source_row_id = row_records.id
       AND source_keys.site_id = :site_id
       AND source_keys.report_source_scope_id = :report_source_scope_id
       AND source_keys.report_type = 'return_report'
       AND source_keys.version_id IN :return_version_ids
    INNER JOIN dataset_versions AS published_versions
        ON published_versions.id = row_records.version_id
       AND published_versions.id IN :return_version_ids
       AND published_versions.status = 'published'
    INNER JOIN daily_datasets AS datasets
        ON datasets.id = source_keys.dataset_id
       AND datasets.site_id = :site_id
       {{date_predicate}}
    WHERE row_records.row_state = 'active'
      AND {_LATEST_KEY_PREDICATE}
      {{event_predicate}}
),
classified AS (
    SELECT facts.quantity,
           CASE WHEN mappings.id IS NOT NULL THEN 'mapped'
                WHEN exclusions.id IS NOT NULL THEN 'excluded'
                ELSE 'unmatched' END AS identity_bucket,
           CASE
             WHEN dedup.decision = 'unresolved' THEN 'unresolved'
             WHEN dedup.decision = 'duplicate_of'
              AND dedup.canonical_source_key_id <> facts.source_key_id
               THEN 'duplicate'
             WHEN mappings.id IS NOT NULL THEN 'mapped'
             WHEN exclusions.id IS NOT NULL THEN 'excluded'
             ELSE 'unmatched'
           END AS result_bucket,
           CASE WHEN dedup.source_key_id IS NULL THEN 'unique'
                WHEN dedup.decision = 'confirmed_distinct' THEN 'confirmed_distinct'
                WHEN dedup.decision = 'unresolved' THEN 'unresolved'
                WHEN dedup.canonical_source_key_id = facts.source_key_id THEN 'unique'
                ELSE 'duplicate_of' END AS dedup_bucket
    FROM qualified_returns AS facts
    LEFT JOIN effective_members AS dedup ON dedup.source_key_id = facts.source_key_id
    LEFT JOIN product_catalog_mappings AS mappings
        ON mappings.catalog_version_id = :catalog_version_id
       AND mappings.site_id = :site_id
       AND mappings.report_source_scope_id = :report_source_scope_id
       AND mappings.seller_sku_match_sha256 = facts.seller_sku_match_sha256
       AND mappings.seller_sku_match_bytes = facts.seller_sku_match_bytes
    LEFT JOIN product_catalog_exclusions AS exclusions
        ON exclusions.catalog_version_id = :catalog_version_id
       AND exclusions.site_id = :site_id
       AND exclusions.report_source_scope_id = :report_source_scope_id
       AND exclusions.seller_sku_match_sha256 = facts.seller_sku_match_sha256
       AND exclusions.seller_sku_match_bytes = facts.seller_sku_match_bytes
)
SELECT result_bucket, identity_bucket, dedup_bucket, COUNT(*) AS fact_rows,
       COALESCE(SUM(quantity), 0) AS returns
FROM classified
GROUP BY result_bucket, identity_bucket, dedup_bucket
"""


RETURN_BUCKETS_REPORT_DATE_SQL: Final = sa.text(
    _RETURN_CLASSIFIED.format(
        date_predicate="AND datasets.report_date BETWEEN :from_date AND :to_date",
        event_predicate="",
    )
).bindparams(sa.bindparam("return_version_ids", expanding=True))


RETURN_BUCKETS_EVENT_DATE_SQL: Final = sa.text(
    _RETURN_CLASSIFIED.format(
        date_predicate="",
        event_predicate=(
            "AND return_values.return_date >= :event_from_utc "
            "AND return_values.return_date < :event_to_utc"
        ),
    )
).bindparams(sa.bindparam("return_version_ids", expanding=True))


def _style_page_statement(
    *,
    sort: Literal[
        "style_code",
        "standard_name",
        "units",
        "sales",
        "returns",
        "sessions",
        "conversion",
    ],
    direction: Literal["asc", "desc"],
    return_basis: Literal["event_date", "report_date"] = "report_date",
) -> TextClause:
    sort_sql = {
        "style_code": "revisions.style_code",
        "standard_name": "revisions.standard_name",
        "units": "units",
        "sales": "sales",
        "returns": "returns",
        "sessions": "sessions",
        "conversion": "conversion_sort",
    }[sort]
    return_date_predicate = (
        "AND report_rows.return_date >= :event_from_utc "
        "AND report_rows.return_date < :event_to_utc"
        if return_basis == "event_date"
        else "AND datasets.report_date BETWEEN :from_date AND :to_date"
    )
    return sa.text(
        f"""
        WITH RECURSIVE {_DEDUP_STATE},
        business_source_totals AS (
            SELECT source_keys.seller_sku_match_sha256,
                   source_keys.seller_sku_match_bytes,
                   SUM(report_rows.units_ordered) AS units,
                   SUM(report_rows.ordered_product_sales) AS sales,
                   SUM(report_rows.sessions_total) AS sessions,
                   COUNT(*) AS business_fact_rows,
                   MAX(datasets.report_date) AS latest_business_date
            FROM daily_datasets AS datasets
            STRAIGHT_JOIN dataset_versions AS published_versions
                ON published_versions.dataset_id = datasets.id
               AND published_versions.id IN :business_version_ids
               AND published_versions.status = 'published'
            STRAIGHT_JOIN version_rows AS row_records
                FORCE INDEX (ix_version_rows_analytics_active)
                ON row_records.version_id = published_versions.id
               AND row_records.row_state = 'active'
            STRAIGHT_JOIN report_source_keys AS source_keys
                ON source_keys.version_id = row_records.version_id
               AND source_keys.source_row_id = row_records.id
               AND source_keys.dataset_id = datasets.id
               AND source_keys.site_id = :site_id
               AND source_keys.report_source_scope_id = :report_source_scope_id
               AND source_keys.report_type = 'business_report'
            STRAIGHT_JOIN business_report_rows AS report_rows
                ON report_rows.version_row_id = row_records.id
               AND report_rows.version_id = row_records.version_id
            WHERE datasets.site_id = :site_id
              AND datasets.report_date BETWEEN :from_date AND :to_date
              AND {_LATEST_KEY_PREDICATE}
            GROUP BY source_keys.seller_sku_match_sha256,
                     source_keys.seller_sku_match_bytes
        ),
        business_facts AS (
            SELECT sku_members.style_id, source_totals.units,
                   source_totals.sales, source_totals.sessions,
                   source_totals.business_fact_rows,
                   source_totals.latest_business_date,
                   CASE WHEN mappings.id IS NOT NULL THEN 'mapped'
                        WHEN exclusions.id IS NOT NULL THEN 'excluded'
                        ELSE 'unmatched' END AS result_bucket
            FROM business_source_totals AS source_totals
            LEFT JOIN product_catalog_mappings AS mappings
                ON mappings.catalog_version_id = :catalog_version_id
               AND mappings.site_id = :site_id
               AND mappings.report_source_scope_id = :report_source_scope_id
               AND mappings.seller_sku_match_sha256 =
                   source_totals.seller_sku_match_sha256
               AND mappings.seller_sku_match_bytes =
                   source_totals.seller_sku_match_bytes
            LEFT JOIN product_catalog_sku_members AS sku_members
                ON sku_members.catalog_version_id = :catalog_version_id
               AND sku_members.site_id = :site_id
               AND sku_members.sku_id = mappings.sku_id
            LEFT JOIN product_catalog_exclusions AS exclusions
                ON exclusions.catalog_version_id = :catalog_version_id
               AND exclusions.site_id = :site_id
               AND exclusions.report_source_scope_id = :report_source_scope_id
               AND exclusions.seller_sku_match_sha256 =
                   source_totals.seller_sku_match_sha256
               AND exclusions.seller_sku_match_bytes =
                   source_totals.seller_sku_match_bytes
        ),
        business_buckets AS (
            SELECT style_id, result_bucket, SUM(units) AS units,
                   SUM(sales) AS sales, SUM(sessions) AS sessions,
                   SUM(business_fact_rows) AS business_fact_rows,
                   MAX(latest_business_date) AS latest_business_date
            FROM business_facts
            GROUP BY style_id, result_bucket
        ),
        mapped_business AS (
            SELECT style_id, units, sales, sessions, business_fact_rows,
                   latest_business_date
            FROM business_buckets
            WHERE result_bucket = 'mapped'
        ),
        business_site_totals AS (
            SELECT
                COALESCE(SUM(IF(result_bucket = 'mapped',
                                business_fact_rows, 0)), 0)
                    AS business_mapped_rows,
                COALESCE(SUM(IF(result_bucket = 'unmatched',
                                business_fact_rows, 0)), 0)
                    AS business_unmatched_rows,
                COALESCE(SUM(IF(result_bucket = 'excluded',
                                business_fact_rows, 0)), 0)
                    AS business_excluded_rows,
                COALESCE(SUM(IF(result_bucket = 'mapped', units, 0)), 0)
                    AS business_mapped_units,
                COALESCE(SUM(IF(result_bucket = 'unmatched', units, 0)), 0)
                    AS business_unmatched_units,
                COALESCE(SUM(IF(result_bucket = 'excluded', units, 0)), 0)
                    AS business_excluded_units,
                COALESCE(SUM(IF(result_bucket = 'mapped', sales, 0)), 0)
                    AS business_mapped_sales,
                COALESCE(SUM(IF(result_bucket = 'unmatched', sales, 0)), 0)
                    AS business_unmatched_sales,
                COALESCE(SUM(IF(result_bucket = 'excluded', sales, 0)), 0)
                    AS business_excluded_sales,
                COALESCE(SUM(IF(result_bucket = 'mapped', sessions, 0)), 0)
                    AS business_mapped_sessions,
                COALESCE(SUM(IF(result_bucket = 'unmatched', sessions, 0)), 0)
                    AS business_unmatched_sessions,
                COALESCE(SUM(IF(result_bucket = 'excluded', sessions, 0)), 0)
                    AS business_excluded_sessions
            FROM business_buckets
        ),
        return_facts AS (
            SELECT sku_members.style_id, sku_members.sku_id,
                   source_keys.id AS source_key_id,
                   report_rows.quantity AS returns, datasets.report_date,
                   CASE WHEN mappings.id IS NOT NULL THEN 'mapped'
                        WHEN exclusions.id IS NOT NULL THEN 'excluded'
                        ELSE 'unmatched' END AS identity_bucket,
                   CASE
                     WHEN dedup.decision = 'unresolved' THEN 'unresolved'
                     WHEN dedup.decision = 'duplicate_of'
                      AND dedup.canonical_source_key_id <> source_keys.id
                       THEN 'duplicate'
                     WHEN mappings.id IS NOT NULL THEN 'mapped'
                     WHEN exclusions.id IS NOT NULL THEN 'excluded'
                     ELSE 'unmatched'
                   END AS result_bucket,
                   CASE WHEN dedup.source_key_id IS NULL THEN 'unique'
                        WHEN dedup.decision = 'confirmed_distinct'
                          THEN 'confirmed_distinct'
                        WHEN dedup.decision = 'unresolved' THEN 'unresolved'
                        WHEN dedup.canonical_source_key_id = source_keys.id
                          THEN 'unique'
                        ELSE 'duplicate_of' END AS dedup_bucket
            FROM daily_datasets AS datasets
            STRAIGHT_JOIN dataset_versions AS published_versions
                ON published_versions.dataset_id = datasets.id
               AND published_versions.id IN :return_version_ids
               AND published_versions.status = 'published'
            STRAIGHT_JOIN version_rows AS row_records
                FORCE INDEX (ix_version_rows_analytics_active)
                ON row_records.version_id = published_versions.id
               AND row_records.row_state = 'active'
            STRAIGHT_JOIN report_source_keys AS source_keys
                ON source_keys.version_id = row_records.version_id
               AND source_keys.source_row_id = row_records.id
               AND source_keys.dataset_id = datasets.id
               AND source_keys.site_id = :site_id
               AND source_keys.report_source_scope_id = :report_source_scope_id
               AND source_keys.report_type = 'return_report'
            STRAIGHT_JOIN return_report_rows AS report_rows
                ON report_rows.version_row_id = row_records.id
               AND report_rows.version_id = row_records.version_id
            LEFT JOIN product_catalog_mappings AS mappings
                ON mappings.catalog_version_id = :catalog_version_id
               AND mappings.site_id = :site_id
               AND mappings.report_source_scope_id = :report_source_scope_id
               AND mappings.seller_sku_match_sha256 =
                   source_keys.seller_sku_match_sha256
               AND mappings.seller_sku_match_bytes = source_keys.seller_sku_match_bytes
            LEFT JOIN product_catalog_sku_members AS sku_members
                ON sku_members.catalog_version_id = :catalog_version_id
               AND sku_members.site_id = :site_id
               AND sku_members.sku_id = mappings.sku_id
            LEFT JOIN product_catalog_exclusions AS exclusions
                ON exclusions.catalog_version_id = :catalog_version_id
               AND exclusions.site_id = :site_id
               AND exclusions.report_source_scope_id = :report_source_scope_id
               AND exclusions.seller_sku_match_sha256 =
                   source_keys.seller_sku_match_sha256
               AND exclusions.seller_sku_match_bytes =
                   source_keys.seller_sku_match_bytes
            LEFT JOIN effective_members AS dedup
                ON dedup.source_key_id = source_keys.id
            WHERE datasets.site_id = :site_id
              {return_date_predicate}
              AND {_LATEST_KEY_PREDICATE}
        ),
        return_buckets AS (
            SELECT style_id, identity_bucket, result_bucket, dedup_bucket,
                   SUM(returns) AS returns, COUNT(*) AS return_fact_rows,
                   MAX(report_date) AS latest_return_date
            FROM return_facts
            GROUP BY style_id, identity_bucket, result_bucket, dedup_bucket
        ),
        mapped_returns AS (
            SELECT style_id, SUM(returns) AS returns,
                   SUM(return_fact_rows) AS return_fact_rows,
                   MAX(latest_return_date) AS latest_return_date
            FROM return_buckets
            WHERE result_bucket = 'mapped'
            GROUP BY style_id
        ),
        unresolved_by_style AS (
            SELECT style_id,
                   SUM(return_fact_rows) AS unresolved_return_rows
            FROM return_buckets
            WHERE result_bucket = 'unresolved' AND identity_bucket = 'mapped'
            GROUP BY style_id
        ),
        return_site_totals AS (
            SELECT
                COALESCE(SUM(IF(identity_bucket = 'mapped',
                                return_fact_rows, 0)), 0)
                    AS return_identity_mapped_rows,
                COALESCE(SUM(IF(identity_bucket = 'unmatched',
                                return_fact_rows, 0)), 0)
                    AS return_identity_unmatched_rows,
                COALESCE(SUM(IF(identity_bucket = 'excluded',
                                return_fact_rows, 0)), 0)
                    AS return_identity_excluded_rows,
                COALESCE(SUM(IF(dedup_bucket = 'unique',
                                return_fact_rows, 0)), 0)
                    AS return_unique_rows,
                COALESCE(SUM(IF(dedup_bucket = 'confirmed_distinct',
                                return_fact_rows, 0)), 0)
                    AS return_confirmed_distinct_rows,
                COALESCE(SUM(IF(dedup_bucket = 'duplicate_of',
                                return_fact_rows, 0)), 0)
                    AS return_duplicate_of_rows,
                COALESCE(SUM(IF(dedup_bucket = 'unresolved',
                                return_fact_rows, 0)), 0)
                    AS return_unresolved_rows,
                COALESCE(SUM(IF(result_bucket = 'unresolved'
                                AND identity_bucket = 'mapped',
                                return_fact_rows, 0)), 0)
                    AS unresolved_mapped_rows,
                COALESCE(SUM(IF(result_bucket = 'mapped',
                                return_fact_rows, 0)), 0)
                    AS return_mapped_rows,
                COALESCE(SUM(IF(result_bucket = 'unmatched',
                                return_fact_rows, 0)), 0)
                    AS return_unmatched_rows,
                COALESCE(SUM(IF(result_bucket = 'excluded',
                                return_fact_rows, 0)), 0)
                    AS return_excluded_rows,
                COALESCE(SUM(IF(result_bucket = 'duplicate',
                                return_fact_rows, 0)), 0)
                    AS return_duplicate_rows,
                COALESCE(SUM(IF(result_bucket = 'unresolved',
                                return_fact_rows, 0)), 0)
                    AS return_unresolved_bucket_rows,
                COALESCE(SUM(IF(result_bucket = 'mapped', returns, 0)), 0)
                    AS return_mapped_quantity,
                COALESCE(SUM(IF(result_bucket = 'unmatched', returns, 0)), 0)
                    AS return_unmatched_quantity,
                COALESCE(SUM(IF(result_bucket = 'excluded', returns, 0)), 0)
                    AS return_excluded_quantity,
                COALESCE(SUM(IF(result_bucket = 'duplicate', returns, 0)), 0)
                    AS return_duplicate_quantity,
                COALESCE(SUM(IF(result_bucket = 'unresolved', returns, 0)), 0)
                    AS return_unresolved_quantity
            FROM return_buckets
        ),
        source_titles AS (
            SELECT sku_members.style_id,
                   COUNT(DISTINCT refs.raw_sha256) AS source_title_count
            FROM catalog_source_evidence AS evidence
            INNER JOIN report_source_keys AS source_keys
                ON source_keys.id = evidence.source_key_id
               AND evidence.site_id = source_keys.site_id
               AND evidence.report_source_scope_id =
                   source_keys.report_source_scope_id
               AND evidence.title_ref_id IS NOT NULL
            INNER JOIN product_catalog_mappings AS mappings
                ON mappings.catalog_version_id = :catalog_version_id
               AND mappings.site_id = source_keys.site_id
               AND mappings.report_source_scope_id =
                   source_keys.report_source_scope_id
               AND mappings.seller_sku_match_sha256 =
                   source_keys.seller_sku_match_sha256
               AND mappings.seller_sku_match_bytes =
                   source_keys.seller_sku_match_bytes
            INNER JOIN product_catalog_sku_members AS sku_members
                ON sku_members.catalog_version_id = mappings.catalog_version_id
               AND sku_members.site_id = mappings.site_id
               AND sku_members.sku_id = mappings.sku_id
            INNER JOIN catalog_source_refs AS refs
                ON refs.id = evidence.title_ref_id
               AND refs.site_id = evidence.site_id
            WHERE evidence.site_id = :site_id
              AND evidence.report_source_scope_id = :report_source_scope_id
            GROUP BY sku_members.style_id
        )
        SELECT styles.style_id, revisions.style_code, revisions.standard_name,
               revisions.status, COUNT(DISTINCT skus.sku_id) AS sku_count,
               COUNT(DISTINCT sku_revisions.color_key_bytes) AS color_count,
               COUNT(DISTINCT sku_revisions.size_key_bytes) AS size_count,
               COALESCE(titles.source_title_count, 0) AS source_title_count,
               CASE WHEN business.latest_business_date IS NULL
                         THEN returns.latest_return_date
                    WHEN returns.latest_return_date IS NULL
                         THEN business.latest_business_date
                    ELSE GREATEST(business.latest_business_date,
                                  returns.latest_return_date)
               END AS latest_report_date,
               COALESCE(business.units, 0) AS units,
               COALESCE(business.sales, 0) AS sales,
               SUM(COALESCE(business.sales, 0)) OVER () AS filtered_sales_total,
               COALESCE(returns.returns, 0) AS returns,
               COALESCE(business.sessions, 0) AS sessions,
               COALESCE(business.business_fact_rows, 0) AS business_fact_rows,
               COALESCE(returns.return_fact_rows, 0) AS return_fact_rows,
               CASE WHEN COALESCE(business.sessions, 0) <= 0 THEN NULL
                    ELSE business.units / business.sessions END AS conversion_sort,
               COALESCE(MAX(unresolved.unresolved_return_rows), 0)
                    AS unresolved_return_rows,
               MAX(business_totals.business_mapped_rows)
                    AS business_mapped_rows,
               MAX(business_totals.business_unmatched_rows)
                    AS business_unmatched_rows,
               MAX(business_totals.business_excluded_rows)
                    AS business_excluded_rows,
               MAX(business_totals.business_mapped_units)
                    AS business_mapped_units,
               MAX(business_totals.business_unmatched_units)
                    AS business_unmatched_units,
               MAX(business_totals.business_excluded_units)
                    AS business_excluded_units,
               MAX(business_totals.business_mapped_sales)
                    AS business_mapped_sales,
               MAX(business_totals.business_unmatched_sales)
                    AS business_unmatched_sales,
               MAX(business_totals.business_excluded_sales)
                    AS business_excluded_sales,
               MAX(business_totals.business_mapped_sessions)
                    AS business_mapped_sessions,
               MAX(business_totals.business_unmatched_sessions)
                    AS business_unmatched_sessions,
               MAX(business_totals.business_excluded_sessions)
                    AS business_excluded_sessions,
               MAX(return_totals.return_identity_mapped_rows)
                    AS return_identity_mapped_rows,
               MAX(return_totals.return_identity_unmatched_rows)
                    AS return_identity_unmatched_rows,
               MAX(return_totals.return_identity_excluded_rows)
                    AS return_identity_excluded_rows,
               MAX(return_totals.return_unique_rows) AS return_unique_rows,
               MAX(return_totals.return_confirmed_distinct_rows)
                    AS return_confirmed_distinct_rows,
               MAX(return_totals.return_duplicate_of_rows)
                    AS return_duplicate_of_rows,
               MAX(return_totals.return_unresolved_rows)
                    AS return_unresolved_rows,
               MAX(return_totals.unresolved_mapped_rows)
                    AS unresolved_mapped_rows,
               MAX(return_totals.return_mapped_rows) AS return_mapped_rows,
               MAX(return_totals.return_unmatched_rows) AS return_unmatched_rows,
               MAX(return_totals.return_excluded_rows) AS return_excluded_rows,
               MAX(return_totals.return_duplicate_rows) AS return_duplicate_rows,
               MAX(return_totals.return_unresolved_bucket_rows)
                    AS return_unresolved_bucket_rows,
               MAX(return_totals.return_mapped_quantity)
                    AS return_mapped_quantity,
               MAX(return_totals.return_unmatched_quantity)
                    AS return_unmatched_quantity,
               MAX(return_totals.return_excluded_quantity)
                    AS return_excluded_quantity,
               MAX(return_totals.return_duplicate_quantity)
                    AS return_duplicate_quantity,
               MAX(return_totals.return_unresolved_quantity)
                    AS return_unresolved_quantity
        FROM product_catalog_style_members AS styles
        INNER JOIN product_style_revisions AS revisions
            ON revisions.id = styles.style_revision_id
           AND revisions.site_id = styles.site_id
           AND revisions.style_id = styles.style_id
        LEFT JOIN product_catalog_sku_members AS skus
            ON skus.catalog_version_id = styles.catalog_version_id
           AND skus.site_id = styles.site_id
           AND skus.style_id = styles.style_id
        LEFT JOIN product_sku_revisions AS sku_revisions
            ON sku_revisions.id = skus.sku_revision_id
           AND sku_revisions.site_id = skus.site_id
           AND sku_revisions.sku_id = skus.sku_id
        LEFT JOIN mapped_business AS business ON business.style_id = styles.style_id
        LEFT JOIN mapped_returns AS returns ON returns.style_id = styles.style_id
        LEFT JOIN unresolved_by_style AS unresolved
            ON unresolved.style_id = styles.style_id
        LEFT JOIN source_titles AS titles ON titles.style_id = styles.style_id
        CROSS JOIN business_site_totals AS business_totals
        CROSS JOIN return_site_totals AS return_totals
        WHERE styles.catalog_version_id = :catalog_version_id
          AND styles.site_id = :site_id
          AND (
              :category_id IS NULL
              OR styles.category_id = :category_id
              OR CAST(
                  JSON_UNQUOTE(
                      JSON_EXTRACT(styles.category_parent_snapshot, '$.id')
                  ) AS UNSIGNED
              ) = :category_id
          )
          AND (:search_pattern IS NULL
               OR revisions.style_code LIKE :search_pattern
               OR revisions.standard_name LIKE :search_pattern
               OR EXISTS (
                   SELECT 1
                   FROM product_catalog_sku_members AS search_members
                   INNER JOIN product_sku_revisions AS search_revisions
                       ON search_revisions.id = search_members.sku_revision_id
                      AND search_revisions.site_id = search_members.site_id
                      AND search_revisions.sku_id = search_members.sku_id
                   WHERE search_members.catalog_version_id =
                         styles.catalog_version_id
                     AND search_members.site_id = styles.site_id
                     AND search_members.style_id = styles.style_id
                     AND search_revisions.internal_display_sku LIKE
                         :search_pattern
               ))
        GROUP BY styles.style_id, revisions.style_code, revisions.standard_name,
                 revisions.status, business.units, business.sales,
                 business.sessions, business.business_fact_rows,
                 business.latest_business_date, returns.returns,
                 returns.return_fact_rows, returns.latest_return_date,
                 titles.source_title_count
        ORDER BY {sort_sql} {direction.upper()}, styles.style_id ASC
        LIMIT :page_size OFFSET :offset
        """
    ).bindparams(
        sa.bindparam("business_version_ids", expanding=True),
        sa.bindparam("return_version_ids", expanding=True),
    )


STYLE_PAGE_SQL: Final = _style_page_statement(
    sort="units",
    direction="desc",
    return_basis="report_date",
)


STYLE_COUNT_SQL: Final = sa.text(
    """
    SELECT COUNT(*)
    FROM product_catalog_style_members AS styles
    INNER JOIN product_style_revisions AS revisions
        ON revisions.id = styles.style_revision_id
       AND revisions.site_id = styles.site_id
       AND revisions.style_id = styles.style_id
    WHERE styles.catalog_version_id = :catalog_version_id
      AND styles.site_id = :site_id
      AND (
          :category_id IS NULL
          OR styles.category_id = :category_id
          OR CAST(
              JSON_UNQUOTE(
                  JSON_EXTRACT(styles.category_parent_snapshot, '$.id')
              ) AS UNSIGNED
          ) = :category_id
      )
          AND (:search_pattern IS NULL
           OR revisions.style_code LIKE :search_pattern
           OR revisions.standard_name LIKE :search_pattern
           OR EXISTS (
               SELECT 1
               FROM product_catalog_sku_members AS search_members
               INNER JOIN product_sku_revisions AS search_revisions
                   ON search_revisions.id = search_members.sku_revision_id
                  AND search_revisions.site_id = search_members.site_id
                  AND search_revisions.sku_id = search_members.sku_id
               WHERE search_members.catalog_version_id = styles.catalog_version_id
                 AND search_members.site_id = styles.site_id
                 AND search_members.style_id = styles.style_id
                 AND search_revisions.internal_display_sku LIKE :search_pattern
           ))
    """
)


STYLE_DAILY_SQL: Final = sa.text(
    f"""
    SELECT sku_members.style_id, sku_members.sku_id,
           datasets.report_date AS metric_date,
           SUM(report_rows.units_ordered) AS units,
           SUM(report_rows.ordered_product_sales) AS sales,
           SUM(report_rows.sessions_total) AS sessions,
           COUNT(*) AS business_fact_rows,
           0 AS returns, 0 AS return_fact_rows
    FROM product_catalog_sku_members AS sku_members
    INNER JOIN product_catalog_mappings AS mappings
        ON mappings.catalog_version_id = sku_members.catalog_version_id
       AND mappings.site_id = sku_members.site_id
       AND mappings.sku_id = sku_members.sku_id
       AND mappings.report_source_scope_id = :report_source_scope_id
    INNER JOIN report_source_keys AS source_keys
        ON source_keys.seller_sku_match_sha256 = mappings.seller_sku_match_sha256
       AND source_keys.seller_sku_match_bytes = mappings.seller_sku_match_bytes
       AND source_keys.site_id = :site_id
       AND source_keys.report_source_scope_id = :report_source_scope_id
       AND source_keys.report_type = 'business_report'
       AND source_keys.version_id IN :business_version_ids
    INNER JOIN version_rows AS row_records
        ON row_records.version_id = source_keys.version_id
       AND row_records.id = source_keys.source_row_id
       AND row_records.row_state = 'active'
    INNER JOIN business_report_rows AS report_rows
        ON report_rows.version_id = row_records.version_id
       AND report_rows.version_row_id = row_records.id
    INNER JOIN daily_datasets AS datasets
        ON datasets.id = source_keys.dataset_id
       AND datasets.site_id = :site_id
       AND datasets.report_date BETWEEN :from_date AND :to_date
    INNER JOIN dataset_versions AS published_versions
        ON published_versions.id = row_records.version_id
       AND published_versions.id IN :business_version_ids
       AND published_versions.status = 'published'
    WHERE sku_members.catalog_version_id = :catalog_version_id
      AND sku_members.site_id = :site_id
      AND sku_members.style_id = :style_id
      AND {_LATEST_KEY_PREDICATE}
    GROUP BY sku_members.style_id, sku_members.sku_id, datasets.report_date
    """
).bindparams(sa.bindparam("business_version_ids", expanding=True))


STYLE_IDENTITY_SQL: Final = sa.text(
    """
    SELECT styles.style_id, revisions.style_code, revisions.standard_name,
           revisions.status, COUNT(DISTINCT skus.sku_id) AS sku_count,
           COUNT(DISTINCT sku_revisions.color_key_bytes) AS color_count,
           COUNT(DISTINCT sku_revisions.size_key_bytes) AS size_count
    FROM product_catalog_style_members AS styles
    INNER JOIN product_style_revisions AS revisions
        ON revisions.id = styles.style_revision_id
       AND revisions.site_id = styles.site_id
       AND revisions.style_id = styles.style_id
    LEFT JOIN product_catalog_sku_members AS skus
        ON skus.catalog_version_id = styles.catalog_version_id
       AND skus.site_id = styles.site_id
       AND skus.style_id = styles.style_id
    LEFT JOIN product_sku_revisions AS sku_revisions
        ON sku_revisions.id = skus.sku_revision_id
       AND sku_revisions.site_id = skus.site_id
       AND sku_revisions.sku_id = skus.sku_id
    WHERE styles.catalog_version_id = :catalog_version_id
      AND styles.site_id = :site_id
      AND styles.style_id = :style_id
    GROUP BY styles.style_id, revisions.style_code, revisions.standard_name,
             revisions.status
    """
)


STYLE_VARIANTS_SQL: Final = sa.text(
    """
    SELECT members.sku_id, revisions.standard_color, revisions.standard_size,
           revisions.internal_display_sku, revisions.status,
           revisions.color_key_bytes, revisions.size_key_bytes,
           revisions.display_key_bytes
    FROM product_catalog_sku_members AS members
    INNER JOIN product_sku_revisions AS revisions
        ON revisions.id = members.sku_revision_id
       AND revisions.site_id = members.site_id
       AND revisions.sku_id = members.sku_id
       AND revisions.style_id = members.style_id
    WHERE members.catalog_version_id = :catalog_version_id
      AND members.site_id = :site_id
      AND members.style_id = :style_id
    ORDER BY revisions.color_key_bytes, revisions.size_key_bytes,
             revisions.display_key_bytes, members.sku_id
    """
)


STYLE_ALIASES_SQL: Final = sa.text(
    """
    SELECT DISTINCT mappings.sku_id, refs.id AS source_ref_id,
           refs.safe_preview, refs.raw_sha256, refs.is_unsafe,
           refs.is_truncated, mappings.seller_sku_match_bytes
    FROM product_catalog_mappings AS mappings
    INNER JOIN product_catalog_sku_members AS members
        ON members.catalog_version_id = mappings.catalog_version_id
       AND members.site_id = mappings.site_id
       AND members.sku_id = mappings.sku_id
       AND members.style_id = :style_id
    INNER JOIN report_source_keys AS source_keys
        ON source_keys.site_id = mappings.site_id
       AND source_keys.report_source_scope_id = mappings.report_source_scope_id
       AND source_keys.seller_sku_match_sha256 = mappings.seller_sku_match_sha256
       AND source_keys.seller_sku_match_bytes = mappings.seller_sku_match_bytes
    INNER JOIN catalog_source_evidence AS evidence
        ON evidence.source_key_id = source_keys.id
       AND evidence.site_id = source_keys.site_id
       AND evidence.report_source_scope_id = source_keys.report_source_scope_id
    INNER JOIN catalog_source_refs AS refs
        ON refs.id = evidence.seller_sku_ref_id
       AND refs.site_id = evidence.site_id
    WHERE mappings.catalog_version_id = :catalog_version_id
      AND mappings.site_id = :site_id
      AND mappings.report_source_scope_id = :report_source_scope_id
    ORDER BY mappings.sku_id, mappings.seller_sku_match_bytes, refs.id
    """
)


_STYLE_RETURN_DAILY = f"""
WITH RECURSIVE {_DEDUP_STATE}
SELECT members.style_id, members.sku_id,
       {{metric_date}} AS metric_date,
       SUM(report_rows.quantity) AS returns,
       COUNT(*) AS return_fact_rows,
       MIN(datasets.report_date) AS contributing_report_date_from,
       MAX(datasets.report_date) AS contributing_report_date_to
FROM product_catalog_sku_members AS members
INNER JOIN product_catalog_mappings AS mappings
    ON mappings.catalog_version_id = members.catalog_version_id
   AND mappings.site_id = members.site_id
   AND mappings.sku_id = members.sku_id
   AND mappings.report_source_scope_id = :report_source_scope_id
INNER JOIN report_source_keys AS source_keys
    ON source_keys.seller_sku_match_sha256 = mappings.seller_sku_match_sha256
   AND source_keys.seller_sku_match_bytes = mappings.seller_sku_match_bytes
   AND source_keys.site_id = :site_id
   AND source_keys.report_source_scope_id = :report_source_scope_id
   AND source_keys.report_type = 'return_report'
   AND source_keys.version_id IN :return_version_ids
INNER JOIN version_rows AS row_records
    ON row_records.version_id = source_keys.version_id
   AND row_records.id = source_keys.source_row_id
   AND row_records.row_state = 'active'
INNER JOIN return_report_rows AS report_rows
    ON report_rows.version_id = row_records.version_id
   AND report_rows.version_row_id = row_records.id
INNER JOIN daily_datasets AS datasets
    ON datasets.id = source_keys.dataset_id
   AND datasets.site_id = :site_id
   {{date_predicate}}
INNER JOIN dataset_versions AS published_versions
    ON published_versions.id = row_records.version_id
   AND published_versions.id IN :return_version_ids
   AND published_versions.status = 'published'
LEFT JOIN effective_members AS dedup ON dedup.source_key_id = source_keys.id
WHERE members.catalog_version_id = :catalog_version_id
  AND members.site_id = :site_id
  AND members.style_id = :style_id
  AND {_LATEST_KEY_PREDICATE}
  AND (dedup.source_key_id IS NULL
       OR dedup.decision = 'confirmed_distinct'
       OR (dedup.decision = 'duplicate_of'
           AND dedup.canonical_source_key_id = source_keys.id))
GROUP BY members.style_id, members.sku_id, {{metric_date}}
"""


STYLE_RETURN_DAILY_REPORT_DATE_SQL: Final = sa.text(
    _STYLE_RETURN_DAILY.format(
        metric_date="datasets.report_date",
        date_predicate="AND datasets.report_date BETWEEN :from_date AND :to_date",
    )
).bindparams(sa.bindparam("return_version_ids", expanding=True))


STYLE_RETURN_DAILY_EVENT_DATE_SQL: Final = sa.text(
    _STYLE_RETURN_DAILY.format(
        metric_date=(
            "DATE(CONVERT_TZ(report_rows.return_date, '+00:00', :reporting_timezone))"
        ),
        date_predicate=(
            "AND report_rows.return_date >= :event_from_utc "
            "AND report_rows.return_date < :event_to_utc"
        ),
    )
).bindparams(sa.bindparam("return_version_ids", expanding=True))


_STYLE_UNRESOLVED = f"""
WITH RECURSIVE {_DEDUP_STATE}
SELECT sku_members.style_id, sku_members.sku_id,
       COUNT(*) AS unresolved_rows
FROM version_rows AS row_records
INNER JOIN return_report_rows AS report_rows
    ON report_rows.version_row_id = row_records.id
   AND report_rows.version_id = row_records.version_id
INNER JOIN report_source_keys AS source_keys
    ON source_keys.version_id = row_records.version_id
   AND source_keys.source_row_id = row_records.id
   AND source_keys.site_id = :site_id
   AND source_keys.report_source_scope_id = :report_source_scope_id
   AND source_keys.report_type = 'return_report'
   AND source_keys.version_id IN :return_version_ids
INNER JOIN effective_members AS dedup
    ON dedup.source_key_id = source_keys.id
   AND dedup.decision = 'unresolved'
INNER JOIN product_catalog_mappings AS mappings
    ON mappings.catalog_version_id = :catalog_version_id
   AND mappings.site_id = :site_id
   AND mappings.report_source_scope_id = :report_source_scope_id
   AND mappings.seller_sku_match_sha256 = source_keys.seller_sku_match_sha256
   AND mappings.seller_sku_match_bytes = source_keys.seller_sku_match_bytes
INNER JOIN product_catalog_sku_members AS sku_members
    ON sku_members.catalog_version_id = mappings.catalog_version_id
   AND sku_members.site_id = mappings.site_id
   AND sku_members.sku_id = mappings.sku_id
INNER JOIN daily_datasets AS datasets
    ON datasets.id = source_keys.dataset_id
   AND datasets.site_id = :site_id
   {{date_predicate}}
INNER JOIN dataset_versions AS published_versions
    ON published_versions.id = row_records.version_id
   AND published_versions.id IN :return_version_ids
   AND published_versions.status = 'published'
WHERE row_records.row_state = 'active'
  AND {_LATEST_KEY_PREDICATE}
GROUP BY sku_members.style_id, sku_members.sku_id
"""


STYLE_UNRESOLVED_REPORT_DATE_SQL: Final = sa.text(
    _STYLE_UNRESOLVED.format(
        date_predicate="AND datasets.report_date BETWEEN :from_date AND :to_date"
    )
).bindparams(sa.bindparam("return_version_ids", expanding=True))


STYLE_UNRESOLVED_EVENT_DATE_SQL: Final = sa.text(
    _STYLE_UNRESOLVED.format(
        date_predicate=(
            "AND report_rows.return_date >= :event_from_utc "
            "AND report_rows.return_date < :event_to_utc"
        )
    )
).bindparams(sa.bindparam("return_version_ids", expanding=True))


CONTRIBUTING_RETURN_DATES_SQL: Final = sa.text(
    f"""
    SELECT DISTINCT datasets.report_date
    FROM version_rows AS row_records
    INNER JOIN return_report_rows AS return_values
        ON return_values.version_row_id = row_records.id
       AND return_values.version_id = row_records.version_id
    INNER JOIN report_source_keys AS source_keys
        ON source_keys.version_id = row_records.version_id
       AND source_keys.source_row_id = row_records.id
       AND source_keys.site_id = :site_id
       AND source_keys.report_source_scope_id = :report_source_scope_id
       AND source_keys.report_type = 'return_report'
       AND source_keys.version_id IN :return_version_ids
    INNER JOIN daily_datasets AS datasets
        ON datasets.id = source_keys.dataset_id
       AND datasets.site_id = :site_id
    INNER JOIN dataset_versions AS published_versions
        ON published_versions.id = row_records.version_id
       AND published_versions.id IN :return_version_ids
       AND published_versions.status = 'published'
    WHERE row_records.row_state = 'active'
      AND {_LATEST_KEY_PREDICATE}
      AND return_values.return_date >= :event_from_utc
      AND return_values.return_date < :event_to_utc
    ORDER BY datasets.report_date
    """
).bindparams(sa.bindparam("return_version_ids", expanding=True))


def style_page_sql(
    *,
    sort: Literal[
        "style_code",
        "standard_name",
        "units",
        "sales",
        "returns",
        "sessions",
        "conversion",
    ],
    direction: Literal["asc", "desc"],
    return_basis: Literal["event_date", "report_date"] = "report_date",
) -> TextClause:
    return _style_page_statement(
        sort=sort,
        direction=direction,
        return_basis=return_basis,
    )


__all__ = (
    "ALL_CURRENT_RETURN_MEMBERS_SQL",
    "BUSINESS_BUCKETS_SQL",
    "CONTRIBUTING_RETURN_DATES_SQL",
    "CURRENT_CONTEXT_SQL",
    "CURRENT_MEMBERS_SQL",
    "RETURN_BUCKETS_EVENT_DATE_SQL",
    "RETURN_BUCKETS_REPORT_DATE_SQL",
    "SNAPSHOT_CONTEXT_SQL",
    "SNAPSHOT_MEMBERS_SQL",
    "STYLE_ALIASES_SQL",
    "STYLE_COUNT_SQL",
    "STYLE_DAILY_SQL",
    "STYLE_IDENTITY_SQL",
    "STYLE_PAGE_SQL",
    "STYLE_RETURN_DAILY_EVENT_DATE_SQL",
    "STYLE_RETURN_DAILY_REPORT_DATE_SQL",
    "STYLE_UNRESOLVED_EVENT_DATE_SQL",
    "STYLE_UNRESOLVED_REPORT_DATE_SQL",
    "STYLE_VARIANTS_SQL",
    "style_page_sql",
)
