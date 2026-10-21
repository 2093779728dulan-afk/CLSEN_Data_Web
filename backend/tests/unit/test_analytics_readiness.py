from datetime import UTC, date, datetime
from unittest.mock import Mock

import pytest
import sqlalchemy as sa
from app.analytics.readiness import read_readiness
from app.analytics.style_repository import (
    AnalyticsCatalogRequired,
    AnalyticsReturnSnapshotRequired,
    AnalyticsSnapshotStale,
    AnalyticsSourceScopeRequired,
    MySqlStyleAnalyticsRepository,
    StyleAnalyticsError,
)
from app.api.style_analytics import _analytics_error


def test_empty_to_initialized_readiness_preserves_site_boundary() -> None:
    engine = sa.create_engine("sqlite://")
    with engine.begin() as connection:
        for statement in (
            "CREATE TABLE report_source_scopes (id INTEGER, site_id INTEGER)",
            "CREATE TABLE product_catalog_publications "
            "(site_id INTEGER, current_catalog_version_id INTEGER)",
            "CREATE TABLE product_catalog_versions "
            "(id INTEGER, site_id INTEGER, status TEXT)",
            "CREATE TABLE return_dedup_publications "
            "(site_id INTEGER, report_source_scope_id INTEGER, "
            "current_snapshot_id INTEGER)",
            "CREATE TABLE return_dedup_snapshots "
            "(id INTEGER, site_id INTEGER, report_source_scope_id INTEGER, "
            "status TEXT)",
            "CREATE TABLE daily_datasets "
            "(id INTEGER, site_id INTEGER, report_date TEXT, report_type TEXT)",
            "CREATE TABLE dataset_publications "
            "(dataset_id INTEGER, version_id INTEGER)",
            "CREATE TABLE dataset_versions "
            "(id INTEGER, dataset_id INTEGER, status TEXT)",
        ):
            connection.exec_driver_sql(statement)
        empty = read_readiness(connection, 1)
        assert not empty.prerequisites_present
        assert empty.published_reports == 0
        assert empty.coverage_from is None
        for statement in (
            "INSERT INTO daily_datasets VALUES (1, 1, '2026-07-01', 'business_report')",
            "INSERT INTO dataset_publications VALUES (1, 1)",
            "INSERT INTO dataset_versions VALUES (1, 1, 'published')",
        ):
            connection.exec_driver_sql(statement)
        imported = read_readiness(connection, 1)
        assert imported.published_reports == 1
        assert imported.coverage_from == date(2026, 7, 1)
        assert not imported.prerequisites_present
        for statement in (
            "INSERT INTO report_source_scopes VALUES (1, 1)",
            "INSERT INTO product_catalog_publications VALUES (1, 1)",
            "INSERT INTO product_catalog_versions VALUES (1, 1, 'ready')",
            "INSERT INTO return_dedup_publications VALUES (1, 1, 1)",
            "INSERT INTO return_dedup_snapshots VALUES (1, 1, 1, 'ready')",
        ):
            connection.exec_driver_sql(statement)
        assert read_readiness(connection, 1).prerequisites_present
        assert read_readiness(connection, 2) == empty
        connection.exec_driver_sql("UPDATE return_dedup_snapshots SET site_id = 2")
        assert not read_readiness(connection, 1).return_snapshot_present
    engine.dispose()


@pytest.mark.parametrize(
    "scope,catalog,dedup,expected",
    [
        (False, False, False, AnalyticsSourceScopeRequired),
        (True, False, False, AnalyticsCatalogRequired),
        (True, True, False, AnalyticsReturnSnapshotRequired),
        (True, True, True, StyleAnalyticsError),
    ],
)
def test_missing_context_is_classified_in_the_same_connection(
    monkeypatch: pytest.MonkeyPatch,
    scope: bool,
    catalog: bool,
    dedup: bool,
    expected: type[StyleAnalyticsError],
) -> None:
    connection = Mock()
    connection.scalar.return_value = datetime(2026, 9, 22, tzinfo=UTC)
    connection.execute.return_value.mappings.return_value.one_or_none.return_value = (
        None
    )
    readiness = Mock(
        source_scope_confirmed=scope,
        catalog_approved=catalog,
        return_snapshot_present=dedup,
    )
    reader = Mock(return_value=readiness)
    monkeypatch.setattr("app.analytics.style_repository.read_readiness", reader)
    repository = MySqlStyleAnalyticsRepository(Mock())
    with pytest.raises(expected) as caught:
        repository._resolve(
            connection,
            site_id=7,
            from_date=date(2026, 7, 1),
            to_date=date(2026, 7, 2),
            catalog_version_id=None,
            fact_basis="current",
            return_basis="event_date",
        )
    assert type(caught.value) is expected
    reader.assert_called_once_with(connection, 7)
    response = _analytics_error(caught.value)
    assert response.status_code == 409
    detail: object = response.detail
    assert isinstance(detail, dict)
    assert detail["code"] == expected.code


def test_stale_snapshot_is_not_an_initialization_error() -> None:
    response = _analytics_error(AnalyticsSnapshotStale())
    detail: object = response.detail
    assert isinstance(detail, dict)
    assert detail["code"] == "analytics_snapshot_stale"
