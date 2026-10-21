from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from uuid import uuid4

import pytest
import sqlalchemy as sa
from app.auth.sessions import Principal
from app.catalog.return_dedup_repository import (
    CreateReturnDedupStaging,
    DecideReturnDedupGroup,
    FrozenPublicationMember,
    MySqlReturnDedupRepository,
    ReturnDedupJobRevisionConflict,
    build_frozen_groups,
    publication_set_digest,
)
from app.catalog.scope_repository import MySqlCatalogScopeRepository
from app.catalog.scope_service import (
    CatalogScopeService,
    ConfirmScopeCommand,
)
from app.publications.commands import (
    CreatePublishedMoveRevisionCommand,
    EmptyMoveTarget,
    FinalizePublishedMoveCommand,
    PublicationPointerExpectation,
    UndoPublishedMoveCommand,
)
from app.publications.repository import MySqlPublicationRepository
from app.publications.service import PublicationService
from app.site_context import CurrentSiteContext, resolve_current_site_context
from sqlalchemy.orm import Session

from tests.integration.dataset_test_support import (
    dataset_case as _dataset_case,  # noqa: F401
)
from tests.integration.publication_test_support import PublicationIntegrationCase
from tests.integration.publication_test_support import (
    publication_case as _publication_case,  # noqa: F401
)


def _current_return_publication_digest(
    case: PublicationIntegrationCase,
) -> bytes:
    rows = case.dataset_case.rows(
        """
        SELECT datasets.id AS dataset_id, datasets.report_date,
               publications.version_id, revisions.publication_revision,
               versions.data_revision
        FROM daily_datasets AS datasets
        INNER JOIN report_dataset_scope_assignments AS assignments
            ON assignments.dataset_id = datasets.id
           AND assignments.site_id = datasets.site_id
        INNER JOIN report_publication_revisions AS revisions
            ON revisions.dataset_id = datasets.id
           AND revisions.site_id = datasets.site_id
           AND revisions.report_source_scope_id =
               assignments.report_source_scope_id
        INNER JOIN dataset_publications AS publications
            ON publications.dataset_id = datasets.id
        INNER JOIN dataset_versions AS versions
            ON versions.id = publications.version_id
           AND versions.dataset_id = datasets.id
           AND versions.status = 'published'
        WHERE datasets.site_id = 1
          AND datasets.report_type = 'return_report'
        ORDER BY datasets.report_date, datasets.id
        """
    )
    return publication_set_digest(
        tuple(
            FrozenPublicationMember(
                dataset_id=int(row["dataset_id"]),
                published_version_id=int(row["version_id"]),
                publication_revision=int(row["publication_revision"]),
                version_data_revision=int(row["data_revision"]),
                report_date=row["report_date"],
            )
            for row in rows
        )
    )


def _current_return_snapshot_digest(
    case: PublicationIntegrationCase,
) -> bytes:
    value = case.dataset_case.scalar(
        """
        SELECT snapshots.return_publication_set_digest
        FROM return_dedup_publications AS pointers
        INNER JOIN return_dedup_snapshots AS snapshots
            ON snapshots.id = pointers.current_snapshot_id
        WHERE pointers.site_id = 1
        """
    )
    assert value is not None
    return bytes(value)


pytestmark = pytest.mark.mysql

NOW = datetime(2026, 8, 21, 8, 0, tzinfo=UTC)


def _confirm_scope(case: PublicationIntegrationCase) -> None:
    engine = case.dataset_case.runtime_engine()
    try:
        principal = Principal(
            user_id=case.admin_user_id,
            username="return-dedup-admin",
            display_name="Return Dedup Admin",
            roles=frozenset({"admin"}),
            session_id=case.admin_user_id,
            csrf_token_hash=b"x" * 32,
        )
        with Session(engine) as session:
            context = resolve_current_site_context(session, principal)
        CatalogScopeService(
            MySqlCatalogScopeRepository(engine), clock=lambda: NOW
        ).confirm(
            context,
            ConfirmScopeCommand(
                operation_token=uuid4(),
                expected_site_config_revision=context.site_config_revision,
                seller_account_scope_key="return-dedup-test-account",
                seller_account_display_name="Return Dedup Test Account",
                marketplace_scope_code="amazon_us",
                reason="Confirm scope for return dedup integration coverage",
            ),
        )
    finally:
        engine.dispose()


def _context(case: PublicationIntegrationCase) -> CurrentSiteContext:
    engine = case.dataset_case.runtime_engine()
    principal = Principal(
        user_id=case.owner_user_id,
        username="return-dedup-manager",
        display_name="Return Dedup Manager",
        roles=frozenset({"data_manager"}),
        session_id=case.owner_user_id,
        csrf_token_hash=b"x" * 32,
    )
    try:
        with Session(engine) as session:
            return resolve_current_site_context(session, principal)
    finally:
        engine.dispose()


def _materialize_return(
    case: PublicationIntegrationCase, report_date: date
) -> tuple[int, int]:
    _baseline, result = case.materialize_baseline(
        report_date=report_date,
        variant="123456789012",
        report_type="return_report",
        extra_columns=(("dedup-test-date", report_date.isoformat()),),
    )
    return result.dataset_id, result.version_id


def _publication_service(case: PublicationIntegrationCase) -> PublicationService:
    return PublicationService(
        repository=MySqlPublicationRepository(
            case.dataset_case.runtime_engine(),
            retry_waiter=lambda _attempt: None,
        ),
        clock=lambda: NOW,
    )


def _cleanup(case: PublicationIntegrationCase) -> None:
    with case.dataset_case.migration_engine.begin() as connection:
        for statement in (
            "DELETE FROM return_dedup_snapshot_groups",
            "DELETE FROM return_dedup_staging_members",
            "DELETE FROM return_dedup_staging_jobs",
            "DELETE FROM return_dedup_publications WHERE site_id = 1",
            "DELETE FROM return_dedup_group_members",
            "__delete_return_dedup_snapshots__",
            "DELETE FROM return_dedup_group_revisions",
            "DELETE FROM report_source_keys WHERE site_id = 1",
            "DELETE FROM report_publication_revisions WHERE site_id = 1",
            "DELETE FROM report_dataset_scope_assignments WHERE site_id = 1",
            "DELETE FROM catalog_audit_events WHERE site_id = 1",
            "DELETE FROM catalog_command_effects WHERE site_id = 1",
            "DELETE FROM catalog_command_claims WHERE site_id = 1",
            "DELETE FROM report_source_scopes WHERE site_id = 1",
        ):
            if statement == "__delete_return_dedup_snapshots__":
                while connection.scalar(
                    sa.text("SELECT COUNT(*) FROM return_dedup_snapshots")
                ):
                    deleted = connection.execute(
                        sa.text(
                            """
                            DELETE snapshots
                            FROM return_dedup_snapshots AS snapshots
                            LEFT JOIN return_dedup_snapshots AS children
                                ON children.base_snapshot_id = snapshots.id
                            WHERE children.id IS NULL
                            """
                        )
                    )
                    if deleted.rowcount < 1:
                        raise AssertionError("dedup snapshot cleanup made no progress")
                continue
            connection.execute(sa.text(statement))
        connection.execute(
            sa.text(
                """
                UPDATE site_current_configs
                SET current_config_version_id = 1, updated_by_user_id = NULL
                WHERE site_id = 1
                """
            )
        )
        connection.execute(
            sa.text(
                "DELETE FROM site_config_versions "
                "WHERE site_id = 1 AND version_number > 1"
            )
        )


def test_staging_freezes_publications_builds_snapshot_and_fences_old_worker(
    publication_case: PublicationIntegrationCase,
) -> None:
    case = publication_case
    _cleanup(case)
    try:
        _confirm_scope(case)
        first_dataset, first_version = _materialize_return(case, date(2097, 1, 1))
        second_dataset, second_version = _materialize_return(case, date(2097, 1, 2))
        proposed_dataset, proposed_version = _materialize_return(case, date(2097, 1, 3))
        proposed_ready = case.mark_ready(
            dataset_id=proposed_dataset, version_id=proposed_version
        )
        case.dataset_case.mark_published(first_dataset, first_version)
        case.dataset_case.mark_published(second_dataset, second_version)

        engine = case.dataset_case.runtime_engine()
        try:
            repository = MySqlReturnDedupRepository(engine)
            context = _context(case)
            command = CreateReturnDedupStaging(
                operation_token=uuid4(),
                dataset_id=proposed_dataset,
                proposed_version_id=proposed_version,
                expected_publication_revision=0,
                expected_dedup_publication_revision=0,
            )
            job = repository.create_staging(context, command, occurred_at=NOW)
            assert repository.create_staging(context, command, occurred_at=NOW) == job
            assert job.status == "building"
            assert (
                len(
                    case.dataset_case.rows(
                        "SELECT id FROM return_dedup_staging_members "
                        "WHERE job_id = :job_id",
                        {"job_id": job.job_id},
                    )
                )
                == 3
            )

            build_lease = repository.claim(
                job_id=job.job_id,
                expected_job_revision=job.job_revision,
                lease_token=uuid4(),
                occurred_at=NOW + timedelta(seconds=1),
                lease_ttl=timedelta(minutes=1),
            )
            frozen = repository.load_frozen_input(build_lease)
            completed = repository.complete(
                build_lease,
                frozen=frozen,
                groups=build_frozen_groups(frozen),
                occurred_at=NOW + timedelta(seconds=2),
            )
            assert completed.status == "ready"
            assert completed.result_snapshot_id is not None
            assert (
                case.dataset_case.scalar(
                    "SELECT status FROM return_dedup_snapshots WHERE id = :id",
                    {"id": completed.result_snapshot_id},
                )
                == "ready"
            )
            assert (
                case.dataset_case.scalar(
                    "SELECT COUNT(*) FROM return_dedup_group_revisions"
                )
                >= 1
            )

            published = case.publish(
                proposed_ready,
                operation_token=command.operation_token,
            )
            assert published.version_id == proposed_version
            assert (
                case.dataset_case.scalar(
                    "SELECT publication_revision "
                    "FROM report_publication_revisions "
                    "WHERE dataset_id = :dataset_id",
                    {"dataset_id": proposed_dataset},
                )
                == 1
            )
            pointer = case.dataset_case.rows(
                "SELECT current_snapshot_id, dedup_publication_revision "
                "FROM return_dedup_publications WHERE site_id = 1"
            )
            assert pointer == [
                {
                    "current_snapshot_id": completed.result_snapshot_id,
                    "dedup_publication_revision": 1,
                }
            ]
            assert _current_return_snapshot_digest(
                case
            ) == _current_return_publication_digest(case)

            groups = repository.list_groups(
                context,
                status="all",
                page=1,
                page_size=50,
            )
            assert groups.dedup_publication_revision == 1
            assert groups.total_items >= 1
            group = groups.groups[0]
            decision_command = DecideReturnDedupGroup(
                operation_token=uuid4(),
                group_id=group.group_id,
                expected_dedup_publication_revision=1,
                expected_group_revision=group.group_revision,
                decision="confirmed_distinct",
                canonical_member_id=None,
                reason="Confirmed as distinct return events",
            )
            decision = repository.decide_group(
                context,
                decision_command,
                occurred_at=NOW + timedelta(seconds=3),
            )
            assert decision.group_revision == group.group_revision + 1
            assert decision.dedup_publication_revision == 2
            assert (
                repository.decide_group(
                    context,
                    decision_command,
                    occurred_at=NOW + timedelta(seconds=4),
                )
                == decision
            )
            assert case.dataset_case.rows(
                "SELECT current_snapshot_id, dedup_publication_revision "
                "FROM return_dedup_publications WHERE site_id = 1"
            ) == [
                {
                    "current_snapshot_id": decision.snapshot_id,
                    "dedup_publication_revision": 2,
                }
            ]
            assert (
                case.dataset_case.scalar(
                    "SELECT publication_revision "
                    "FROM report_publication_revisions "
                    "WHERE dataset_id = :dataset_id",
                    {"dataset_id": proposed_dataset},
                )
                == 1
            )

            latest_decision = decision
            for index in range(32):
                latest_decision = repository.decide_group(
                    context,
                    DecideReturnDedupGroup(
                        operation_token=uuid4(),
                        group_id=group.group_id,
                        expected_dedup_publication_revision=(
                            latest_decision.dedup_publication_revision
                        ),
                        expected_group_revision=latest_decision.group_revision,
                        decision="confirmed_distinct",
                        canonical_member_id=None,
                        reason=f"Checkpoint boundary decision {index + 1}",
                    ),
                    occurred_at=NOW + timedelta(seconds=5 + index),
                )
            assert latest_decision.dedup_publication_revision == 34
            assert (
                case.dataset_case.scalar(
                    "SELECT COUNT(*) FROM return_dedup_snapshots "
                    "WHERE snapshot_kind = 'checkpoint'"
                )
                >= 2
            )
            assert (
                case.dataset_case.scalar(
                    "SELECT MAX(delta_depth) FROM return_dedup_snapshots"
                )
                <= 31
            )
            replayed_groups = repository.list_groups(
                context,
                status="resolved",
                page=1,
                page_size=50,
            )
            assert replayed_groups.dedup_publication_revision == 34
            assert replayed_groups.groups[0].group_revision == (
                latest_decision.group_revision
            )

            fourth_dataset, fourth_version = _materialize_return(case, date(2097, 1, 4))
            case.mark_ready(dataset_id=fourth_dataset, version_id=fourth_version)
            other = repository.create_staging(
                context,
                CreateReturnDedupStaging(
                    operation_token=uuid4(),
                    dataset_id=fourth_dataset,
                    proposed_version_id=fourth_version,
                    expected_publication_revision=0,
                    expected_dedup_publication_revision=34,
                ),
                occurred_at=NOW + timedelta(seconds=2),
            )
            old = repository.claim(
                job_id=other.job_id,
                expected_job_revision=other.job_revision,
                lease_token=uuid4(),
                occurred_at=NOW + timedelta(seconds=3),
                lease_ttl=timedelta(seconds=5),
            )
            replacement = repository.claim(
                job_id=other.job_id,
                expected_job_revision=old.job_revision,
                lease_token=uuid4(),
                occurred_at=NOW + timedelta(seconds=9),
                lease_ttl=timedelta(seconds=5),
            )
            assert replacement.fencing_token == old.fencing_token + 1
            with pytest.raises(ReturnDedupJobRevisionConflict):
                repository.renew(
                    old,
                    occurred_at=NOW + timedelta(seconds=10),
                    lease_ttl=timedelta(seconds=5),
                )
        finally:
            engine.dispose()
    finally:
        _cleanup(case)


def test_return_move_and_undo_stage_the_exact_two_dataset_successor(
    publication_case: PublicationIntegrationCase,
) -> None:
    case = publication_case
    _cleanup(case)
    try:
        _confirm_scope(case)
        source_dataset, source_version = _materialize_return(case, date(2097, 2, 1))
        case.dataset_case.mark_published(source_dataset, source_version)
        source_publication = case.publication_pointer(source_dataset)
        service = _publication_service(case)
        move_review = CreatePublishedMoveRevisionCommand(
            source_dataset_id=source_dataset,
            expected_source_publication=source_publication,
            target_report_date=date(2097, 2, 2),
            target=EmptyMoveTarget(),
            merge_decisions=(),
            actor_user_id=case.admin_user_id,
            operation_token=uuid4(),
            reason="Review the corrected return report date",
        )
        move_draft = service.create_published_move_revision(move_review)
        reviewed_target = case.mark_ready(
            dataset_id=move_draft.dataset_id,
            version_id=move_draft.version_id,
            actor_user_id=case.admin_user_id,
        )
        repository = MySqlReturnDedupRepository(case.dataset_case.runtime_engine())
        context = _context(case)
        finalize_token = uuid4()
        finalize_job = repository.create_staging(
            context,
            CreateReturnDedupStaging(
                operation_token=finalize_token,
                dataset_id=source_dataset,
                proposed_version_id=move_draft.version_id,
                expected_publication_revision=0,
                expected_dedup_publication_revision=0,
            ),
            occurred_at=NOW,
        )
        finalize_lease = repository.claim(
            job_id=finalize_job.job_id,
            expected_job_revision=finalize_job.job_revision,
            lease_token=uuid4(),
            occurred_at=NOW + timedelta(seconds=1),
            lease_ttl=timedelta(minutes=1),
        )
        frozen_finalize = repository.load_frozen_input(finalize_lease)
        assert {member.dataset_id for member in frozen_finalize.members} == {
            move_draft.dataset_id
        }
        repository.complete(
            finalize_lease,
            frozen=frozen_finalize,
            groups=build_frozen_groups(frozen_finalize),
            occurred_at=NOW + timedelta(seconds=2),
        )
        moved = service.finalize_published_move(
            FinalizePublishedMoveCommand(
                move_revision_operation_token=move_review.operation_token,
                source_dataset_id=source_dataset,
                expected_source_publication=source_publication,
                target_dataset_id=move_draft.dataset_id,
                expected_target_draft=reviewed_target.expectation,
                expected_target_publication=PublicationPointerExpectation(None, None),
                validation=reviewed_target.validation,
                confirmation=reviewed_target.confirmation,
                actor_user_id=case.admin_user_id,
                operation_token=finalize_token,
                reason="Finalize the corrected return report date",
            )
        )
        target_publication = case.publication_pointer(move_draft.dataset_id)
        assert case.publication_pointer(source_dataset).version_id is None
        assert _current_return_snapshot_digest(
            case
        ) == _current_return_publication_digest(case)

        undo_token = uuid4()
        undo_job = repository.create_staging(
            context,
            CreateReturnDedupStaging(
                operation_token=undo_token,
                dataset_id=source_dataset,
                proposed_version_id=source_version,
                expected_publication_revision=1,
                expected_dedup_publication_revision=1,
            ),
            occurred_at=NOW + timedelta(seconds=3),
        )
        undo_lease = repository.claim(
            job_id=undo_job.job_id,
            expected_job_revision=undo_job.job_revision,
            lease_token=uuid4(),
            occurred_at=NOW + timedelta(seconds=4),
            lease_ttl=timedelta(minutes=1),
        )
        frozen_undo = repository.load_frozen_input(undo_lease)
        assert {member.dataset_id for member in frozen_undo.members} == {source_dataset}
        repository.complete(
            undo_lease,
            frozen=frozen_undo,
            groups=build_frozen_groups(frozen_undo),
            occurred_at=NOW + timedelta(seconds=5),
        )
        reversed_move = service.undo_published_move(
            UndoPublishedMoveCommand(
                move_command_id=moved.command_id,
                source_dataset_id=source_dataset,
                expected_source_publication=PublicationPointerExpectation(None, None),
                restore_source_version_id=source_version,
                target_dataset_id=move_draft.dataset_id,
                expected_target_publication=target_publication,
                restore_target_version_id=None,
                actor_user_id=case.admin_user_id,
                operation_token=undo_token,
                reason="Reverse the corrected return report date",
            )
        )
        assert reversed_move.command_type == "reverse_move"
        assert case.publication_pointer(source_dataset).version_id == source_version
        assert case.publication_pointer(move_draft.dataset_id).version_id is None
        assert _current_return_snapshot_digest(
            case
        ) == _current_return_publication_digest(case)
        assert case.dataset_case.rows(
            "SELECT dataset_id, publication_revision "
            "FROM report_publication_revisions "
            "WHERE dataset_id IN (:source_id, :target_id) ORDER BY dataset_id",
            {"source_id": source_dataset, "target_id": move_draft.dataset_id},
        ) == [
            {"dataset_id": source_dataset, "publication_revision": 2},
            {"dataset_id": move_draft.dataset_id, "publication_revision": 2},
        ]
        assert (
            case.dataset_case.scalar(
                "SELECT dedup_publication_revision "
                "FROM return_dedup_publications WHERE site_id = 1"
            )
            == 2
        )
    finally:
        _cleanup(case)
