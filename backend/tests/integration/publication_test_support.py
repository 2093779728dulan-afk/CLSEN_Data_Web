from __future__ import annotations

from collections.abc import Iterator
from dataclasses import dataclass
from datetime import UTC, date, datetime
from typing import Any, cast
from uuid import UUID, uuid4

import pytest
import sqlalchemy as sa
from app.datasets.repository import MySqlDatasetRepository
from app.datasets.service import DatasetService
from app.datasets.types import DraftMutationResult, MaterializeBaselineCommand
from app.publications.commands import (
    DraftPointerExpectation,
    PublicationConfirmation,
    PublicationPointerExpectation,
    PublishCommand,
    ValidationExpectation,
)
from app.publications.repository import MySqlPublicationRepository
from app.publications.results import PublicationCommandResult
from app.publications.service import PublicationService
from app.review.repository import MySqlReviewRepository
from app.review.service import ReviewService
from app.review.types import DraftHeadExpectation, MarkReadyCommand
from app.validation.repository import MySqlValidationRepository
from app.validation.service import ValidationService
from app.validation.types import RunValidationCommand

from tests.integration.dataset_test_support import (
    NOW,
    DatasetIntegrationCase,
    SeededBaseline,
)
from tests.integration.dataset_test_support import (
    dataset_case as _dataset_case,  # noqa: F401 - registers the shared fixture
)


@dataclass(frozen=True, slots=True)
class ReadyPublicationDraft:
    dataset_id: int
    version_id: int
    version_no: int
    head: DraftHeadExpectation
    expectation: DraftPointerExpectation
    validation: ValidationExpectation
    confirmation: PublicationConfirmation


@dataclass(frozen=True, slots=True)
class PublishedDataset:
    dataset_id: int
    version_id: int
    version_no: int
    report_date: date
    report_type: str
    publication: PublicationPointerExpectation
    result: PublicationCommandResult


@dataclass(slots=True)
class PublicationIntegrationCase:
    dataset_case: DatasetIntegrationCase

    @property
    def owner_user_id(self) -> int:
        return self.dataset_case.owner_user_id

    @property
    def other_manager_user_id(self) -> int:
        return self.dataset_case.other_manager_user_id

    @property
    def admin_user_id(self) -> int:
        return self.dataset_case.admin_user_id

    def materialize_baseline(
        self,
        *,
        report_date: date,
        variant: str,
        report_type: str = "business_report",
        extra_columns: tuple[tuple[str, str], ...] = (),
        actor_user_id: int | None = None,
    ) -> tuple[SeededBaseline, DraftMutationResult]:
        actor_id = actor_user_id or self.owner_user_id
        baseline = self.dataset_case.seed_baseline(
            report_date=report_date,
            variant=variant,
            report_type=report_type,
            extra_columns=extra_columns,
            actor_user_id=actor_id,
        )
        engine = self.dataset_case.runtime_engine()
        try:
            result = DatasetService(
                repository=MySqlDatasetRepository(engine),
                clock=lambda: NOW,
            ).materialize_baseline(
                MaterializeBaselineCommand(
                    batch_id=baseline.batch_id,
                    parse_baseline_id=baseline.parse_baseline_id,
                    report_date=report_date,
                    strategy="replace",
                    expected_active_draft=None,
                    expected_publication_version_id=None,
                    merge_decisions=(),
                    actor_user_id=actor_id,
                    operation_token=uuid4(),
                    reason="Materialize a real parsed baseline for publication",
                )
            )
        finally:
            engine.dispose()
        return baseline, result

    def mark_ready(
        self,
        *,
        dataset_id: int,
        version_id: int,
        actor_user_id: int | None = None,
    ) -> ReadyPublicationDraft:
        actor_id = actor_user_id or self.owner_user_id
        persisted = self._draft_head(dataset_id=dataset_id, version_id=version_id)
        validation_engine = self.dataset_case.runtime_engine()
        review_engine = self.dataset_case.runtime_engine()
        try:
            receipt = ValidationService(
                repository=MySqlValidationRepository(validation_engine),
                clock=lambda: NOW,
            ).run_validation(
                RunValidationCommand(
                    dataset_id=dataset_id,
                    version_id=version_id,
                    data_revision=persisted.head.data_revision,
                    ruleset_version=persisted.ruleset_version,
                    actor_user_id=actor_id,
                    operation_token=uuid4(),
                )
            )
            assert receipt.status == "succeeded"
            assert receipt.result == "passed"
            ready = ReviewService(
                repository=MySqlReviewRepository(review_engine),
                clock=lambda: NOW,
            ).mark_ready(
                MarkReadyCommand(
                    head=persisted.head,
                    validation_run_id=receipt.validation_run_id,
                    validation_data_digest=receipt.data_digest,
                    ruleset_version=receipt.ruleset_version,
                    confirmed_report_date=receipt.summary.report_date,
                    confirmed_report_type=receipt.summary.report_type,
                    confirmed_row_count=receipt.summary.row_count,
                    confirmed_totals=receipt.summary.totals,
                    actor_user_id=actor_id,
                    operation_token=uuid4(),
                    reason="Validation and publication review are complete",
                )
            )
        finally:
            review_engine.dispose()
            validation_engine.dispose()

        assert ready.status == "ready_for_publish"
        assert ready.data_revision is not None
        assert ready.review_revision is not None
        head = DraftHeadExpectation(
            dataset_id=dataset_id,
            version_id=version_id,
            status="ready_for_publish",
            data_revision=ready.data_revision,
            review_revision=ready.review_revision,
            pointed_at=persisted.head.pointed_at,
        )
        return ReadyPublicationDraft(
            dataset_id=dataset_id,
            version_id=version_id,
            version_no=self.version_no(version_id),
            head=head,
            expectation=DraftPointerExpectation(
                version_id=version_id,
                status="ready_for_publish",
                data_revision=ready.data_revision,
                review_revision=ready.review_revision,
                pointed_at=persisted.head.pointed_at,
            ),
            validation=ValidationExpectation(
                run_id=receipt.validation_run_id,
                version_id=version_id,
                data_revision=receipt.data_revision,
                ruleset_version=receipt.ruleset_version,
                data_digest=receipt.data_digest,
            ),
            confirmation=PublicationConfirmation(
                confirmed_report_date=receipt.summary.report_date,
                report_type=receipt.summary.report_type,
                row_count=receipt.summary.row_count,
                totals=receipt.summary.totals,
            ),
        )

    def publish(
        self,
        ready: ReadyPublicationDraft,
        *,
        expected_publication: PublicationPointerExpectation | None = None,
        actor_user_id: int | None = None,
        operation_token: UUID | None = None,
        reason: str = "Publish the fully reviewed daily dataset",
    ) -> PublishedDataset:
        actor_id = actor_user_id or self.owner_user_id
        command = PublishCommand(
            dataset_id=ready.dataset_id,
            expected_draft=ready.expectation,
            expected_publication=(
                expected_publication or PublicationPointerExpectation(None, None)
            ),
            validation=ready.validation,
            confirmation=ready.confirmation,
            actor_user_id=actor_id,
            operation_token=operation_token or uuid4(),
            reason=reason,
        )
        engine = self.dataset_case.runtime_engine()
        try:
            result = PublicationService(
                repository=MySqlPublicationRepository(engine),
                clock=lambda: NOW,
            ).publish(command)
        finally:
            engine.dispose()
        publication = self.publication_pointer(ready.dataset_id)
        assert publication.is_present
        identity = self.dataset_case.rows(
            "SELECT report_date, report_type FROM daily_datasets WHERE id = :id",
            {"id": ready.dataset_id},
        )
        assert len(identity) == 1
        return PublishedDataset(
            dataset_id=ready.dataset_id,
            version_id=ready.version_id,
            version_no=ready.version_no,
            report_date=cast(date, identity[0]["report_date"]),
            report_type=str(identity[0]["report_type"]),
            publication=publication,
            result=result,
        )

    def create_published_dataset(
        self,
        *,
        report_date: date,
        variant: str,
        actor_user_id: int | None = None,
    ) -> tuple[SeededBaseline, PublishedDataset]:
        baseline, materialized = self.materialize_baseline(
            report_date=report_date,
            variant=variant,
            actor_user_id=actor_user_id,
        )
        ready = self.mark_ready(
            dataset_id=materialized.dataset_id,
            version_id=materialized.version_id,
            actor_user_id=actor_user_id,
        )
        return baseline, self.publish(ready, actor_user_id=actor_user_id)

    def publication_pointer(self, dataset_id: int) -> PublicationPointerExpectation:
        rows = self.dataset_case.rows(
            """
            SELECT version_id, published_at
            FROM dataset_publications
            WHERE dataset_id = :dataset_id
            """,
            {"dataset_id": dataset_id},
        )
        if not rows:
            return PublicationPointerExpectation(None, None)
        assert len(rows) == 1
        return PublicationPointerExpectation(
            version_id=int(rows[0]["version_id"]),
            published_at=_database_utc(rows[0]["published_at"]),
        )

    def version_no(self, version_id: int) -> int:
        value = self.dataset_case.scalar(
            "SELECT version_no FROM dataset_versions WHERE id = :version_id",
            {"version_id": version_id},
        )
        assert value is not None
        return int(value)

    def _draft_head(self, *, dataset_id: int, version_id: int) -> _PersistedDraft:
        rows = self.dataset_case.rows(
            """
            SELECT drafts.dataset_id, drafts.version_id,
                   drafts.version_status, drafts.pointed_at,
                   versions.data_revision, versions.review_revision,
                   versions.ruleset_version
            FROM dataset_drafts AS drafts
            INNER JOIN dataset_versions AS versions
                ON versions.dataset_id = drafts.dataset_id
               AND versions.id = drafts.version_id
               AND versions.status = drafts.version_status
            WHERE drafts.dataset_id = :dataset_id
              AND drafts.version_id = :version_id
            """,
            {"dataset_id": dataset_id, "version_id": version_id},
        )
        assert len(rows) == 1
        row = rows[0]
        assert row["version_status"] in {"draft", "ready_for_publish"}
        return _PersistedDraft(
            head=DraftHeadExpectation(
                dataset_id=int(row["dataset_id"]),
                version_id=int(row["version_id"]),
                status=cast(Any, row["version_status"]),
                data_revision=int(row["data_revision"]),
                review_revision=int(row["review_revision"]),
                pointed_at=_database_utc(row["pointed_at"]),
            ),
            ruleset_version=str(row["ruleset_version"]),
        )


@dataclass(frozen=True, slots=True)
class _PersistedDraft:
    head: DraftHeadExpectation
    ruleset_version: str


def _database_utc(value: object) -> datetime:
    if not isinstance(value, datetime):
        raise AssertionError("database timestamp is not a datetime")
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    if value.utcoffset() is None:
        raise AssertionError("database timestamp has an invalid timezone")
    return value.astimezone(UTC)


@pytest.fixture(name="publication_case")
def publication_case(
    dataset_case: DatasetIntegrationCase,
) -> Iterator[PublicationIntegrationCase]:
    case = PublicationIntegrationCase(dataset_case)
    try:
        yield case
    finally:
        _cleanup_publication_records(dataset_case)


def _cleanup_publication_records(case: DatasetIntegrationCase) -> None:
    user_ids = case.user_ids
    user_bind: sa.BindParameter[Any] = sa.bindparam("user_ids", expanding=True)
    parameters = {"user_ids": user_ids}
    with case.migration_engine.begin() as connection:
        command_ids = tuple(
            int(value)
            for value in connection.scalars(
                sa.text(
                    "SELECT id FROM publication_commands "
                    "WHERE actor_user_id IN :user_ids"
                ).bindparams(user_bind),
                parameters,
            )
        )
        if command_ids:
            command_bind: sa.BindParameter[Any] = sa.bindparam(
                "command_ids",
                expanding=True,
            )
            command_parameters = {"command_ids": command_ids}
            connection.execute(
                sa.text(
                    "DELETE FROM publication_outbox WHERE publication_event_id IN ("
                    "SELECT id FROM publication_events "
                    "WHERE command_id IN :command_ids)"
                ).bindparams(command_bind),
                command_parameters,
            )
            connection.execute(
                sa.text(
                    "DELETE FROM publication_command_results "
                    "WHERE command_id IN :command_ids"
                ).bindparams(command_bind),
                command_parameters,
            )
            connection.execute(
                sa.text(
                    "DELETE FROM publication_events WHERE command_id IN :command_ids"
                ).bindparams(command_bind),
                command_parameters,
            )
            connection.execute(
                sa.text(
                    "DELETE FROM publication_commands WHERE id IN :command_ids"
                ).bindparams(command_bind),
                command_parameters,
            )

        version_ids = tuple(
            int(value)
            for value in connection.scalars(
                sa.text(
                    "SELECT id FROM dataset_versions WHERE created_by IN :user_ids"
                ).bindparams(user_bind),
                parameters,
            )
        )
        connection.execute(
            sa.text(
                "DELETE FROM review_operation_results WHERE actor_user_id IN :user_ids"
            ).bindparams(user_bind),
            parameters,
        )
        if version_ids:
            version_bind: sa.BindParameter[Any] = sa.bindparam(
                "version_ids",
                expanding=True,
            )
            version_parameters = {"version_ids": version_ids}
            for table in (
                "version_review_events",
                "issue_review_events",
                "field_changes",
                "row_changes",
                "data_change_events",
            ):
                connection.execute(
                    sa.text(
                        f"DELETE FROM {table} WHERE version_id IN :version_ids"
                    ).bindparams(version_bind),
                    version_parameters,
                )
        connection.execute(
            sa.text(
                "DELETE FROM review_operation_tokens WHERE actor_user_id IN :user_ids"
            ).bindparams(user_bind),
            parameters,
        )
