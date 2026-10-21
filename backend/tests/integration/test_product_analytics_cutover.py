from __future__ import annotations

import pytest
import sqlalchemy as sa
from app.analytics.cutover import parse_product_analytics_source

from tests.integration.test_style_analytics import (
    ApprovedStyleAnalyticsCase,
    _dataset_case,  # noqa: F401
    _publication_case,  # noqa: F401
    catalog_approval_case_fixture,  # noqa: F401
    style_analytics_case_fixture,  # noqa: F401
)

pytestmark = pytest.mark.mysql

_BUSINESS_TABLES = (
    "product_styles",
    "product_style_revisions",
    "product_skus",
    "product_sku_revisions",
    "product_catalog_versions",
    "product_catalog_style_members",
    "product_catalog_sku_members",
    "product_catalog_mappings",
    "product_catalog_exclusions",
    "product_catalog_publications",
    "return_dedup_snapshots",
    "return_dedup_publications",
    "business_report_rows",
    "return_report_rows",
    "audit_events",
)


def _semantic_checksum(engine: sa.Engine) -> tuple[tuple[str, int], ...]:
    with engine.connect() as connection:
        return tuple(
            (
                table,
                int(connection.scalar(sa.text(f"SELECT COUNT(*) FROM `{table}`")) or 0),
            )
            for table in _BUSINESS_TABLES
        )


def test_legacy_p0_legacy_selector_cycle_performs_zero_business_writes(
    style_analytics_case: ApprovedStyleAnalyticsCase,
) -> None:
    before = _semantic_checksum(style_analytics_case.engine)
    assert parse_product_analytics_source("legacy_parser") == "legacy_parser"
    assert parse_product_analytics_source("p0_catalog") == "p0_catalog"
    assert parse_product_analytics_source("legacy_parser") == "legacy_parser"
    assert _semantic_checksum(style_analytics_case.engine) == before
