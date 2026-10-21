from __future__ import annotations

from datetime import date, datetime, timedelta
from uuid import uuid4

import pytest
import sqlalchemy as sa
from app.auth.sessions import Principal
from app.datasets.repository import MySqlDatasetRepository
from app.datasets.service import DatasetService
from app.datasets.types import MaterializeBaselineCommand
from app.published_details.models import PublishedDetailScope
from app.published_details.scope import PublishedScopeCodec
from app.published_details.service import (
    PublicationScopeChanged,
    PublishedDetailQueryService,
)
from sqlalchemy.orm import Session

from tests.integration.dataset_test_support import NOW, DatasetIntegrationCase
from tests.integration.dataset_test_support import (
    dataset_case as _dataset_case,  # noqa: F401 - registers the shared fixture
)

pytestmark = pytest.mark.mysql


def _isolated_date() -> date:
    return date(2220, 1, 1) + timedelta(days=uuid4().int % 20000)


def _principal(case: DatasetIntegrationCase) -> Principal:
    return Principal(
        user_id=case.owner_user_id,
        username="published-viewer",
        display_name="Published viewer",
        roles=frozenset({"viewer"}),
        session_id=1,
        csrf_token_hash=b"published-detail-csrf",
    )


def _codec() -> PublishedScopeCodec:
    return PublishedScopeCodec(
        secret="published-detail-integration-secret",
        clock=lambda: NOW,
        ttl=timedelta(minutes=5),
    )


def _materialize(
    case: DatasetIntegrationCase,
    *,
    report_date: date,
    report_type: str,
    variant: str,
    expected_publication_version_id: int | None,
) -> tuple[int, int]:
    baseline = case.seed_baseline(
        report_date=report_date,
        report_type=report_type,
        variant=variant,
    )
    result = DatasetService(
        repository=MySqlDatasetRepository(case.migration_engine),
        clock=lambda: NOW,
    ).materialize_baseline(
        MaterializeBaselineCommand(
            batch_id=baseline.batch_id,
            parse_baseline_id=baseline.parse_baseline_id,
            report_date=report_date,
            strategy="replace",
            expected_active_draft=None,
            expected_publication_version_id=expected_publication_version_id,
            merge_decisions=(),
            actor_user_id=case.owner_user_id,
            operation_token=uuid4(),
            reason="Seed a published-detail scope integration version",
        )
    )
    return result.dataset_id, result.version_id


def _repoint_publication(
    case: DatasetIntegrationCase,
    *,
    dataset_id: int,
    version_id: int,
    published_at: datetime,
) -> None:
    with case.migration_engine.begin() as connection:
        connection.execute(
            sa.text(
                """
                DELETE FROM dataset_drafts
                WHERE dataset_id = :dataset_id
                  AND version_id = :version_id
                """
            ),
            {"dataset_id": dataset_id, "version_id": version_id},
        )
        connection.execute(
            sa.text(
                """
                UPDATE dataset_versions
                SET status = 'published', sealed_at = :published_at
                WHERE dataset_id = :dataset_id AND id = :version_id
                """
            ),
            {
                "dataset_id": dataset_id,
                "version_id": version_id,
                "published_at": published_at.replace(tzinfo=None),
            },
        )
        connection.execute(
            sa.text(
                """
                UPDATE dataset_publications
                SET version_id = :version_id, published_at = :published_at
                WHERE dataset_id = :dataset_id
                """
            ),
            {
                "dataset_id": dataset_id,
                "version_id": version_id,
                "published_at": published_at.replace(tzinfo=None),
            },
        )


def test_scope_uses_only_current_type_and_site_pointers_and_detects_republish(
    dataset_case: DatasetIntegrationCase,
) -> None:
    day_one = _isolated_date()
    day_two = day_one + timedelta(days=1)
    old_dataset_id, old_version_id = _materialize(
        dataset_case,
        report_date=day_one,
        report_type="business_report",
        variant="scope-old",
        expected_publication_version_id=None,
    )
    dataset_case.mark_published(old_dataset_id, old_version_id)
    day_two_dataset_id, day_two_version_id = _materialize(
        dataset_case,
        report_date=day_two,
        report_type="business_report",
        variant="scope-day-two",
        expected_publication_version_id=None,
    )
    dataset_case.mark_published(day_two_dataset_id, day_two_version_id)
    return_dataset_id, return_version_id = _materialize(
        dataset_case,
        report_date=day_one,
        report_type="return_report",
        variant="scope-return",
        expected_publication_version_id=None,
    )
    dataset_case.mark_published(return_dataset_id, return_version_id)
    revised_dataset_id, revised_version_id = _materialize(
        dataset_case,
        report_date=day_one,
        report_type="business_report",
        variant="scope-revised",
        expected_publication_version_id=old_version_id,
    )
    assert revised_dataset_id == old_dataset_id
    republished_at = NOW + timedelta(minutes=1)
    _repoint_publication(
        dataset_case,
        dataset_id=revised_dataset_id,
        version_id=revised_version_id,
        published_at=republished_at,
    )

    with Session(dataset_case.migration_engine) as session:
        service = PublishedDetailQueryService(session, _codec())
        scope = service.resolve_publication_scope(
            _principal(dataset_case),
            "business_report",
            day_one,
            day_two,
        )

        assert scope.roles == ("viewer",)
        assert [item.report_date for item in scope.publications] == [day_one, day_two]
        assert [item.version_id for item in scope.publications] == [
            revised_version_id,
            day_two_version_id,
        ]
        assert old_version_id not in {item.version_id for item in scope.publications}
        assert return_version_id not in {item.version_id for item in scope.publications}
        assert (
            service.resolve_full_range(
                _principal(dataset_case), "business_report", day_two
            ).from_date
            == day_one
        )
        assert service.compose_published_schema(scope)
        service.assert_scope_current(scope)

        foreign_site_scope = PublishedDetailScope(
            user_id=scope.user_id,
            roles=scope.roles,
            site_id=scope.site_id + 1,
            report_type=scope.report_type,
            from_date=scope.from_date,
            to_date=scope.to_date,
            issued_at=scope.issued_at,
            expires_at=scope.expires_at,
            publications=tuple(
                item.model_copy(update={"site_id": scope.site_id + 1})
                for item in scope.publications
            ),
        )
        with pytest.raises(PublicationScopeChanged):
            service.assert_scope_current(foreign_site_scope)

    _repoint_publication(
        dataset_case,
        dataset_id=old_dataset_id,
        version_id=old_version_id,
        published_at=NOW + timedelta(minutes=2),
    )
    with (
        Session(dataset_case.migration_engine) as session,
        pytest.raises(PublicationScopeChanged) as caught,
    ):
        PublishedDetailQueryService(session, _codec()).assert_scope_current(scope)
    assert caught.value.code == "publication_scope_changed"
