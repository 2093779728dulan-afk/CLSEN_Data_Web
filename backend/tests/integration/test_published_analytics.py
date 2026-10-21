from __future__ import annotations

from datetime import UTC, date, datetime
from uuid import uuid4

import pytest
import sqlalchemy as sa
from app.analytics.service import PublishedAnalyticsQueryService
from app.datasets.repository import MySqlDatasetRepository
from app.datasets.service import DatasetService
from app.datasets.types import DraftMutationResult, MaterializeBaselineCommand
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session

from tests.integration.dataset_test_support import (
    dataset_case as _dataset_case,  # noqa: F401 - registers shared fixture
)
from tests.integration.publication_test_support import (
    PublicationIntegrationCase,
    PublishedDataset,
)
from tests.integration.publication_test_support import (
    publication_case as _publication_case,  # noqa: F401 - registers fixture
)

pytestmark = pytest.mark.mysql


def _publish_report(
    publication_case: PublicationIntegrationCase,
    *,
    report_date: date,
    report_type: str,
    variant: str,
) -> PublishedDataset:
    baseline = publication_case.dataset_case.seed_baseline(
        report_date=report_date,
        report_type=report_type,
        variant=variant,
    )
    engine = publication_case.dataset_case.runtime_engine()
    try:
        materialized = DatasetService(
            repository=MySqlDatasetRepository(engine),
            clock=lambda: datetime(2026, 8, 9, 8, 0, tzinfo=UTC),
        ).materialize_baseline(
            MaterializeBaselineCommand(
                batch_id=baseline.batch_id,
                parse_baseline_id=baseline.parse_baseline_id,
                report_date=report_date,
                strategy="replace",
                expected_active_draft=None,
                expected_publication_version_id=None,
                merge_decisions=(),
                actor_user_id=publication_case.owner_user_id,
                operation_token=uuid4(),
                reason="Seed one reviewed publication for analytics",
            )
        )
    finally:
        engine.dispose()
    ready = publication_case.mark_ready(
        dataset_id=materialized.dataset_id,
        version_id=materialized.version_id,
    )
    return publication_case.publish(ready)


def _materialize_revision(
    publication_case: PublicationIntegrationCase,
    published: PublishedDataset,
    *,
    variant: str,
) -> DraftMutationResult:
    baseline = publication_case.dataset_case.seed_baseline(
        report_date=published.report_date,
        report_type=published.report_type,
        variant=variant,
    )
    engine = publication_case.dataset_case.runtime_engine()
    try:
        return DatasetService(
            repository=MySqlDatasetRepository(engine),
            clock=lambda: datetime(2026, 8, 9, 9, 0, tzinfo=UTC),
        ).materialize_baseline(
            MaterializeBaselineCommand(
                batch_id=baseline.batch_id,
                parse_baseline_id=baseline.parse_baseline_id,
                report_date=published.report_date,
                strategy="replace",
                expected_active_draft=None,
                expected_publication_version_id=published.version_id,
                merge_decisions=(),
                actor_user_id=publication_case.owner_user_id,
                operation_token=uuid4(),
                reason="Create an unpublished revision for analytics isolation",
            )
        )
    finally:
        engine.dispose()


def _analytics(
    publication_case: PublicationIntegrationCase,
) -> tuple[PublishedAnalyticsQueryService, Session, Engine]:
    engine = publication_case.dataset_case.runtime_engine()
    session = Session(engine)
    return PublishedAnalyticsQueryService(session), session, engine


def test_queries_ignore_drafts_and_switch_only_with_the_publication_pointer(
    publication_case: PublicationIntegrationCase,
) -> None:
    report_date = date(2088, 4, 17)
    published_business = _publish_report(
        publication_case,
        report_date=report_date,
        report_type="business_report",
        variant="analytics-first",
    )
    published_returns = _publish_report(
        publication_case,
        report_date=report_date,
        report_type="return_report",
        variant="analytics-returns",
    )
    draft = _materialize_revision(
        publication_case,
        published_business,
        variant="analytics-draft",
    )

    service, session, engine = _analytics(publication_case)
    try:
        before = service.summary(report_date, report_date)
        products = service.products(report_date, report_date, limit=25)
        returns = service.returns(
            report_date,
            report_date,
            basis="report_date",
        )

        assert before.metrics[0].business_version_id == published_business.version_id
        assert before.metrics[0].return_version_id == published_returns.version_id
        assert draft.version_id not in {
            reference.version_id for reference in before.publications
        }
        assert {reference.version_id for reference in products.publications} == {
            published_business.version_id
        }
        assert {reference.version_id for reference in returns.publications} == {
            published_returns.version_id
        }
    finally:
        session.close()
        engine.dispose()

    ready = publication_case.mark_ready(
        dataset_id=draft.dataset_id,
        version_id=draft.version_id,
    )
    replacement = publication_case.publish(
        ready,
        expected_publication=published_business.publication,
    )

    service, session, engine = _analytics(publication_case)
    try:
        after = service.summary(report_date, report_date)
        assert after.metrics[0].business_version_id == replacement.version_id
        assert published_business.version_id not in {
            reference.version_id for reference in after.publications
        }
    finally:
        session.close()
        engine.dispose()


def test_event_dates_are_recomputed_with_the_current_reporting_timezone(
    publication_case: PublicationIntegrationCase,
) -> None:
    report_date = date(2088, 5, 12)
    published = _publish_report(
        publication_case,
        report_date=report_date,
        report_type="return_report",
        variant="analytics-timezone",
    )
    site_id = int(
        publication_case.dataset_case.scalar(
            "SELECT site_id FROM daily_datasets WHERE id = :dataset_id",
            {"dataset_id": published.dataset_id},
        )
    )

    migration_engine = publication_case.dataset_case.migration_engine
    with migration_engine.begin() as connection:
        original_current = (
            connection.execute(
                sa.text(
                    "SELECT current_config_version_id, updated_by_user_id, updated_at "
                    "FROM site_current_configs "
                    "WHERE site_id = :site_id"
                ),
                {"site_id": site_id},
            )
            .mappings()
            .one()
        )
        original_config_id = int(original_current["current_config_version_id"])
        original_updated_by = original_current["updated_by_user_id"]
        original_updated_at = original_current["updated_at"]
        next_version = int(
            connection.scalar(
                sa.text(
                    "SELECT COALESCE(MAX(version_number), 0) + 1 "
                    "FROM site_config_versions WHERE site_id = :site_id"
                ),
                {"site_id": site_id},
            )
        )
        los_angeles_result = connection.execute(
            sa.text(
                """
                INSERT INTO site_config_versions (
                    site_id, version_number, source_timezone,
                    reporting_timezone, currency_code, effective_at,
                    change_reason, created_by_user_id
                ) VALUES (
                    :site_id, :version_number, 'America/Los_Angeles',
                    'America/Los_Angeles', 'USD', :effective_at,
                    'Fix analytics test timezone', :actor_user_id
                )
                """
            ),
            {
                "site_id": site_id,
                "version_number": next_version,
                "effective_at": datetime(2026, 8, 9, 10, 0),
                "actor_user_id": publication_case.admin_user_id,
            },
        )
        los_angeles_config_id = int(los_angeles_result.lastrowid)
        utc_result = connection.execute(
            sa.text(
                """
                INSERT INTO site_config_versions (
                    site_id, version_number, source_timezone,
                    reporting_timezone, currency_code, effective_at,
                    change_reason, created_by_user_id
                ) VALUES (
                    :site_id, :version_number, 'America/Los_Angeles',
                    'UTC', 'USD', :effective_at,
                    'Verify event-day recomputation', :actor_user_id
                )
                """
            ),
            {
                "site_id": site_id,
                "version_number": next_version + 1,
                "effective_at": datetime(2026, 8, 9, 10, 1),
                "actor_user_id": publication_case.admin_user_id,
            },
        )
        utc_config_id = int(utc_result.lastrowid)
        connection.execute(
            sa.text(
                """
                UPDATE site_current_configs
                SET current_config_version_id = :config_id,
                    updated_by_user_id = :actor_user_id,
                    updated_at = :updated_at
                WHERE site_id = :site_id
                """
            ),
            {
                "config_id": los_angeles_config_id,
                "actor_user_id": publication_case.admin_user_id,
                "updated_at": datetime(2026, 8, 9, 10, 0),
                "site_id": site_id,
            },
        )

    try:
        service, session, engine = _analytics(publication_case)
        try:
            los_angeles = service.returns(
                date(2026, 7, 31),
                date(2026, 8, 1),
                basis="event_date",
            )
        finally:
            session.close()
            engine.dispose()
        assert [row.bucket_date for row in los_angeles.rows] == [
            date(2026, 7, 31),
            date(2026, 7, 31),
        ]
        assert {row.site_config_version_id for row in los_angeles.rows} == {
            los_angeles_config_id
        }
        assert {(row.sku, row.asin) for row in los_angeles.rows} == {
            ("SYN-BLUE-S", "B0SYNTH001"),
            ("SYN-SAND-M", "B0SYNTH002"),
        }
        for row in los_angeles.rows:
            payload = row.model_dump()
            assert "order_id" not in payload
            assert "license_plate_number" not in payload
            assert "customer_comments" not in payload

        with migration_engine.begin() as connection:
            connection.execute(
                sa.text(
                    """
                    UPDATE site_current_configs
                    SET current_config_version_id = :config_id,
                        updated_by_user_id = :actor_user_id,
                        updated_at = :updated_at
                    WHERE site_id = :site_id
                    """
                ),
                {
                    "config_id": utc_config_id,
                    "actor_user_id": publication_case.admin_user_id,
                    "updated_at": datetime(2026, 8, 9, 10, 1),
                    "site_id": site_id,
                },
            )

        service, session, engine = _analytics(publication_case)
        try:
            utc = service.returns(
                date(2026, 7, 31),
                date(2026, 8, 1),
                basis="event_date",
            )
        finally:
            session.close()
            engine.dispose()
        assert [row.bucket_date for row in utc.rows] == [
            date(2026, 7, 31),
            date(2026, 8, 1),
        ]
        assert {row.site_config_version_id for row in utc.rows} == {utc_config_id}
        assert {item.reporting_timezone for item in utc.site_config_versions} == {"UTC"}
        assert {reference.version_id for reference in utc.publications} == {
            published.version_id
        }
    finally:
        with migration_engine.begin() as connection:
            connection.execute(
                sa.text(
                    """
                    UPDATE site_current_configs
                    SET current_config_version_id = :config_id,
                        updated_by_user_id = :actor_user_id,
                        updated_at = :updated_at
                    WHERE site_id = :site_id
                    """
                ),
                {
                    "config_id": original_config_id,
                    "actor_user_id": original_updated_by,
                    "updated_at": original_updated_at,
                    "site_id": site_id,
                },
            )
            connection.execute(
                sa.text(
                    "DELETE FROM site_config_versions "
                    "WHERE id IN (:los_angeles_config_id, :utc_config_id)"
                ),
                {
                    "los_angeles_config_id": los_angeles_config_id,
                    "utc_config_id": utc_config_id,
                },
            )


def test_event_date_query_uses_site_specific_dst_aware_sql_bounds(
    publication_case: PublicationIntegrationCase,
) -> None:
    _publish_report(
        publication_case,
        report_date=date(2088, 6, 21),
        report_type="return_report",
        variant="analytics-prefilter",
    )
    service, session, engine = _analytics(publication_case)
    captured: list[tuple[str, dict[str, object]]] = []

    def capture_statement(
        _connection: object,
        _cursor: object,
        statement: str,
        parameters: object,
        _context: object,
        _executemany: bool,
    ) -> None:
        if "INNER JOIN return_report_rows AS report_rows" in statement and isinstance(
            parameters, dict
        ):
            captured.append(
                (statement, {str(key): value for key, value in parameters.items()})
            )

    sa.event.listen(engine, "before_cursor_execute", capture_statement)
    try:
        result = service.returns(
            date(2026, 3, 8),
            date(2026, 3, 8),
            basis="event_date",
        )
    finally:
        sa.event.remove(engine, "before_cursor_execute", capture_statement)
        session.close()
        engine.dispose()

    assert result.rows == []
    assert result.publications == []
    assert result.site_config_versions == []
    assert len(captured) == 1
    statement, parameters = captured[0]
    assert "report_rows.return_date >=" in statement
    assert "report_rows.return_date <" in statement
    assert parameters["event_from_utc_0"] == datetime(2026, 3, 8, 8, 0)
    assert parameters["event_to_utc_0"] == datetime(2026, 3, 9, 7, 0)
    site_id = parameters["event_site_id_0"]
    assert isinstance(site_id, int)
    assert site_id > 0
