from __future__ import annotations

from app.analytics import style_sql


def test_current_resolver_is_site_scope_catalog_config_and_pointer_bounded() -> None:
    sql = style_sql.CURRENT_CONTEXT_SQL.text.lower()

    for token in (
        "product_catalog_publications",
        "current_catalog_version_id",
        "site_current_configs",
        "report_source_scopes",
        "return_dedup_publications",
        "return_dedup_snapshots",
        "status = 'ready'",
        ":site_id",
    ):
        assert token in sql


def test_snapshot_resolver_uses_exact_fact_tuple_without_current_fallback() -> None:
    sql = style_sql.SNAPSHOT_CONTEXT_SQL.text.lower()

    for token in (
        "product_catalog_versions",
        "fact_snapshot_tuples",
        "publication_snapshots",
        "return_dedup_snapshots",
        ":catalog_version_id",
        ":site_id",
    ):
        assert token in sql
    assert "product_catalog_publications" not in sql
    assert "return_dedup_publications" not in sql


def test_fact_queries_are_publication_member_date_identity_and_site_bounded() -> None:
    joined = "\n".join(
        clause.text.lower()
        for clause in (
            style_sql.BUSINESS_BUCKETS_SQL,
            style_sql.RETURN_BUCKETS_REPORT_DATE_SQL,
            style_sql.RETURN_BUCKETS_EVENT_DATE_SQL,
            style_sql.STYLE_PAGE_SQL,
            style_sql.STYLE_DAILY_SQL,
        )
    )

    for token in (
        ":site_id",
        ":catalog_version_id",
        "report_source_scope_id",
        "published_version_id",
        "seller_sku_match_sha256",
        "seller_sku_match_bytes",
        "row_state = 'active'",
    ):
        assert token in joined
    assert "parse_seller_sku" not in joined
    assert "product_identity" not in joined


def test_event_query_filters_time_before_joining_contributing_publication() -> None:
    sql = style_sql.RETURN_BUCKETS_EVENT_DATE_SQL.text.lower()

    assert "return_values.return_date >= :event_from_utc" in sql
    assert "return_values.return_date < :event_to_utc" in sql
    assert "datasets.report_date between :from_date and :to_date" not in sql


def test_style_page_performs_mysql_search_sort_page_and_aggregation() -> None:
    sql = style_sql.STYLE_PAGE_SQL.text.lower()

    assert "limit :page_size offset :offset" in sql
    assert "group by" in sql
    assert ":search_pattern" in sql
    assert "order by" in sql
    assert "published_versions.id in :business_version_ids" in sql
    assert "published_versions.id in :return_version_ids" in sql
    for shared_projection in (
        "business_source_totals as",
        "business_facts as",
        "business_buckets as",
        "return_facts as",
        "return_buckets as",
        "business_site_totals as",
        "return_site_totals as",
        "unresolved_by_style as",
    ):
        assert shared_projection in sql
    assert "sum(business_fact_rows) as business_fact_rows" in sql
    assert "group by source_keys.seller_sku_match_sha256" in sql
    assert sql.count("from business_facts") == 1
    assert sql.count("from return_facts") == 1
    assert "force index (ix_version_rows_analytics_active)" in sql
    assert "published_versions.data_revision = 0" in sql
    assert "source_keys.source_key_revision <= published_versions.data_revision" in sql
    assert "newer_source_keys.id > source_keys.id" not in sql


def test_latest_source_keys_are_publication_and_single_style_bounded() -> None:
    business = style_sql.BUSINESS_BUCKETS_SQL.text.lower()
    returns = style_sql.RETURN_BUCKETS_REPORT_DATE_SQL.text.lower()
    style_business = style_sql.STYLE_DAILY_SQL.text.lower()
    style_returns = style_sql.STYLE_RETURN_DAILY_REPORT_DATE_SQL.text.lower()

    assert "source_keys.version_id in :business_version_ids" in business
    assert "source_keys.version_id in :return_version_ids" in returns
    for sql, version_parameter in (
        (style_business, ":business_version_ids"),
        (style_returns, ":return_version_ids"),
    ):
        assert f"source_keys.version_id in {version_parameter}" in sql
        assert "style_id = :style_id" in sql
        assert "not exists" in sql
        assert "newer_source_keys.source_key_revision" in sql
        assert "partition by keyed.version_id" not in sql
        assert "partition by source_keys.version_id" not in sql
