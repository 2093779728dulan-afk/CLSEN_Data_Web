"""Read-only, site-scoped prerequisites; never creates or approves business data."""

from datetime import date

import sqlalchemy as sa
from pydantic import BaseModel
from sqlalchemy.engine import Connection


class AnalyticsReadiness(BaseModel):
    source_scope_confirmed: bool
    catalog_approved: bool
    return_snapshot_present: bool
    prerequisites_present: bool
    published_reports: int
    published_business_reports: int = 0
    published_return_reports: int = 0
    coverage_from: date | None
    coverage_to: date | None


def read_readiness(connection: Connection, site_id: int) -> AnalyticsReadiness:
    row = (
        connection.execute(
            sa.text("""
        SELECT
          EXISTS(SELECT 1 FROM report_source_scopes
            WHERE site_id = :site_id) AS scope_ready,
          EXISTS(SELECT 1 FROM product_catalog_publications p
            JOIN product_catalog_versions v ON v.id = p.current_catalog_version_id
              AND v.site_id = p.site_id AND v.status = 'ready'
            WHERE p.site_id = :site_id) AS catalog_ready,
          EXISTS(SELECT 1 FROM return_dedup_publications p
            JOIN report_source_scopes s ON s.id = p.report_source_scope_id
              AND s.site_id = p.site_id
            JOIN return_dedup_snapshots v ON v.id = p.current_snapshot_id
              AND v.site_id = p.site_id AND v.report_source_scope_id = s.id
              AND v.status = 'ready'
            WHERE p.site_id = :site_id) AS dedup_ready
    """),
            {"site_id": site_id},
        )
        .mappings()
        .one()
    )
    coverage = (
        connection.execute(
            sa.text("""
        SELECT COUNT(*) AS reports,
               COALESCE(SUM(d.report_type='business_report'),0) AS business_reports,
               COALESCE(SUM(d.report_type='return_report'),0) AS return_reports,
               MIN(d.report_date) AS first_date,
               MAX(d.report_date) AS last_date
        FROM daily_datasets d
        JOIN dataset_publications p ON p.dataset_id = d.id
        JOIN dataset_versions v ON v.id = p.version_id
          AND v.dataset_id = d.id AND v.status = 'published'
        WHERE d.site_id = :site_id
          AND d.report_type IN ('business_report', 'return_report')
    """),
            {"site_id": site_id},
        )
        .mappings()
        .one()
    )
    return AnalyticsReadiness(
        source_scope_confirmed=bool(row["scope_ready"]),
        catalog_approved=bool(row["catalog_ready"]),
        return_snapshot_present=bool(row["dedup_ready"]),
        prerequisites_present=all(
            bool(row[k]) for k in ("scope_ready", "catalog_ready", "dedup_ready")
        ),
        published_reports=coverage["reports"],
        published_business_reports=int(coverage["business_reports"]),
        published_return_reports=int(coverage["return_reports"]),
        coverage_from=coverage["first_date"],
        coverage_to=coverage["last_date"],
    )
