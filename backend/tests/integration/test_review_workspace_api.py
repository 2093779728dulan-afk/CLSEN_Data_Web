from __future__ import annotations

import json
from collections.abc import Iterator
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from typing import Any, cast
from uuid import uuid4

import pytest
import sqlalchemy as sa
from app.api.dependencies import CSRF_HEADER_NAME
from app.auth.passwords import hash_password
from app.config import Settings
from app.datasets.repository import MySqlDatasetRepository
from app.datasets.service import DatasetService
from app.datasets.types import (
    EmptyReassignmentTarget,
    MaterializeBaselineCommand,
    ReassignUnpublishedDraftDateCommand,
    VersionExpectation,
)
from app.db.session import create_session_factory
from app.main import create_app
from app.publications.commands import (
    CreatePublishedMoveRevisionCommand,
    PublishedMoveTarget,
)
from app.publications.repository import MySqlPublicationRepository
from app.publications.results import DraftCommandResult
from app.publications.service import PublicationService
from app.review.repository import MySqlReviewRepository
from app.review.service import ReviewService
from app.review.types import (
    ChangeRowStateCommand,
    CreateNoteCommand,
    DraftHeadExpectation,
    FieldNoteTarget,
    ReviewIssueCommand,
    ReviewMutationResult,
    ReviseNoteCommand,
    SetFieldValueCommand,
)
from app.validation.repository import MySqlValidationRepository
from app.validation.service import ValidationService
from app.validation.types import RunValidationCommand
from fastapi.testclient import TestClient

from tests.integration.dataset_test_support import (
    NOW,
    DatasetIntegrationCase,
)
from tests.integration.dataset_test_support import (
    dataset_case as _dataset_case,  # noqa: F401 - registers the shared fixture
)
from tests.integration.publication_test_support import (
    PublicationIntegrationCase,
    PublishedDataset,
)
from tests.integration.publication_test_support import (
    publication_case as _publication_case,  # noqa: F401 - registers fixture
)

pytestmark = pytest.mark.mysql

_PASSWORD = "correct horse battery staple"


@dataclass(slots=True)
class ReviewWorkspaceCase:
    dataset_case: DatasetIntegrationCase
    client: TestClient
    dataset_id: int
    version_id: int
    row_id: int
    source_batch_id: int
    parsed_source_row_id: int
    original_comment: str
    corrected_comment: str
    owner_username: str
    admin_username: str
    viewer_username: str
    validation_run_id: int
    validation_issue_id: int

    def login(self, username: str) -> str:
        bootstrap = self.client.get("/api/auth/csrf")
        assert bootstrap.status_code == 200
        bootstrap_token = str(bootstrap.json()["csrf_token"])
        response = self.client.post(
            "/api/auth/login",
            json={"username": username, "password": _PASSWORD},
            headers={CSRF_HEADER_NAME: bootstrap_token},
        )
        assert response.status_code == 200, response.text
        return str(response.json()["csrf_token"])


@dataclass(slots=True)
class PublishedMoveWorkspaceCase:
    publication_case: PublicationIntegrationCase
    client: TestClient
    source: PublishedDataset
    target: PublishedDataset
    move_command: CreatePublishedMoveRevisionCommand
    move_draft: DraftCommandResult
    admin_username: str
    owner_username: str

    def login(self, username: str) -> None:
        bootstrap = self.client.get("/api/auth/csrf")
        assert bootstrap.status_code == 200
        response = self.client.post(
            "/api/auth/login",
            json={"username": username, "password": _PASSWORD},
            headers={CSRF_HEADER_NAME: str(bootstrap.json()["csrf_token"])},
        )
        assert response.status_code == 200, response.text


def _isolated_date() -> date:
    return date(2180, 1, 1) + timedelta(days=uuid4().int % 10000)


def _database_utc(value: object) -> datetime:
    assert isinstance(value, datetime)
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


def _read_head(
    case: DatasetIntegrationCase,
    *,
    dataset_id: int,
    version_id: int,
) -> tuple[DraftHeadExpectation, str]:
    rows = case.rows(
        """
        SELECT drafts.dataset_id, drafts.version_id, drafts.pointed_at,
               versions.status, versions.data_revision,
               versions.review_revision, versions.ruleset_version
        FROM dataset_drafts AS drafts
        INNER JOIN dataset_versions AS versions
            ON versions.dataset_id = drafts.dataset_id
           AND versions.id = drafts.version_id
        WHERE drafts.dataset_id = :dataset_id
          AND drafts.version_id = :version_id
        """,
        {"dataset_id": dataset_id, "version_id": version_id},
    )
    assert len(rows) == 1
    row = rows[0]
    return (
        DraftHeadExpectation(
            dataset_id=int(row["dataset_id"]),
            version_id=int(row["version_id"]),
            status=cast(Any, row["status"]),
            data_revision=int(row["data_revision"]),
            review_revision=int(row["review_revision"]),
            pointed_at=_database_utc(row["pointed_at"]),
        ),
        str(row["ruleset_version"]),
    )


def _head_after(
    prior: DraftHeadExpectation,
    result: ReviewMutationResult,
) -> DraftHeadExpectation:
    assert result.status in {"draft", "ready_for_publish"}
    assert result.data_revision is not None
    assert result.review_revision is not None
    return DraftHeadExpectation(
        dataset_id=prior.dataset_id,
        version_id=prior.version_id,
        status=result.status,
        data_revision=result.data_revision,
        review_revision=result.review_revision,
        pointed_at=prior.pointed_at,
    )


def _insert_viewer(case: DatasetIntegrationCase) -> tuple[int, str]:
    username = f"review-workspace-viewer-{uuid4().hex}"
    with case.migration_engine.begin() as connection:
        inserted = connection.execute(
            sa.text(
                """
                INSERT INTO users (
                    username_normalized, display_name, password_hash, status,
                    created_at, updated_at
                ) VALUES (
                    :username, 'Review Workspace Viewer', :password_hash,
                    'active', UTC_TIMESTAMP(6), UTC_TIMESTAMP(6)
                )
                """
            ),
            {"username": username, "password_hash": hash_password(_PASSWORD)},
        )
        assert inserted.lastrowid is not None
        user_id = int(inserted.lastrowid)
        connection.execute(
            sa.text(
                """
                INSERT INTO user_roles (user_id, role_id, assigned_by)
                SELECT :user_id, id, :user_id
                FROM roles WHERE code = 'viewer'
                """
            ),
            {"user_id": user_id},
        )
    case.user_ids = (*case.user_ids, user_id)
    return user_id, username


def _prepare_credentials(case: DatasetIntegrationCase) -> tuple[str, str, str]:
    viewer_id, viewer_username = _insert_viewer(case)
    del viewer_id
    with case.migration_engine.begin() as connection:
        connection.execute(
            sa.text(
                """
                UPDATE users
                SET password_hash = :password_hash, updated_at = UTC_TIMESTAMP(6)
                WHERE id IN (:owner_user_id, :admin_user_id)
                """
            ),
            {
                "password_hash": hash_password(_PASSWORD),
                "owner_user_id": case.owner_user_id,
                "admin_user_id": case.admin_user_id,
            },
        )
        usernames: dict[int, str] = {
            int(row["id"]): str(row["username_normalized"])
            for row in connection.execute(
                sa.text(
                    """
                    SELECT id, username_normalized
                    FROM users
                    WHERE id IN (:owner_user_id, :admin_user_id)
                    """
                ),
                {
                    "owner_user_id": case.owner_user_id,
                    "admin_user_id": case.admin_user_id,
                },
            )
            .mappings()
            .all()
        }
    return (
        str(usernames[case.owner_user_id]),
        str(usernames[case.admin_user_id]),
        viewer_username,
    )


def _cleanup_review_workspace(case: DatasetIntegrationCase, version_id: int) -> None:
    with case.migration_engine.begin() as connection:
        parameters = {"version_id": version_id, "user_ids": case.user_ids}
        user_bind: sa.BindParameter[Any] = sa.bindparam("user_ids", expanding=True)
        connection.execute(
            sa.text(
                "DELETE FROM review_operation_results "
                "WHERE result_version_id = :version_id "
                "OR actor_user_id IN :user_ids"
            ).bindparams(user_bind),
            parameters,
        )
        connection.execute(
            sa.text("DELETE FROM issue_review_events WHERE version_id = :version_id"),
            parameters,
        )
        connection.execute(
            sa.text("DELETE FROM validation_issues WHERE version_id = :version_id"),
            parameters,
        )
        connection.execute(
            sa.text("DELETE FROM validation_runs WHERE version_id = :version_id"),
            parameters,
        )
        note_ids = tuple(
            int(note_id)
            for note_id in connection.scalars(
                sa.text(
                    "SELECT notes.id FROM notes "
                    "INNER JOIN note_threads "
                    "ON note_threads.note_key = notes.note_key "
                    "WHERE note_threads.version_id = :version_id "
                    "ORDER BY notes.revision_number DESC, notes.id DESC"
                ),
                parameters,
            )
        )
        # Notes form a RESTRICT self-referencing revision chain, so revisions
        # must be removed newest-first during isolated test cleanup.
        for note_id in note_ids:
            connection.execute(
                sa.text("DELETE FROM notes WHERE id = :note_id"),
                {"note_id": note_id},
            )
        connection.execute(
            sa.text("DELETE FROM note_threads WHERE version_id = :version_id"),
            parameters,
        )
        connection.execute(
            sa.text("DELETE FROM field_changes WHERE version_id = :version_id"),
            parameters,
        )
        connection.execute(
            sa.text("DELETE FROM row_changes WHERE version_id = :version_id"),
            parameters,
        )
        connection.execute(
            sa.text("DELETE FROM data_change_events WHERE version_id = :version_id"),
            parameters,
        )
        connection.execute(
            sa.text(
                "DELETE FROM review_operation_tokens WHERE actor_user_id IN :user_ids"
            ).bindparams(user_bind),
            parameters,
        )
        connection.execute(
            sa.text("DELETE FROM auth_sessions WHERE user_id IN :user_ids").bindparams(
                user_bind
            ),
            parameters,
        )


@pytest.fixture()
def review_workspace_case(
    dataset_case: DatasetIntegrationCase,
) -> Iterator[ReviewWorkspaceCase]:
    report_date = _isolated_date()
    baseline = dataset_case.seed_baseline(
        report_date=report_date,
        report_type="return_report",
        variant=uuid4().hex[:12],
    )
    materialize_engine = dataset_case.runtime_engine()
    try:
        materialized = DatasetService(
            repository=MySqlDatasetRepository(materialize_engine),
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
                actor_user_id=dataset_case.owner_user_id,
                operation_token=uuid4(),
                reason="Materialize return data for workspace API testing",
            )
        )
    finally:
        materialize_engine.dispose()

    head, ruleset_version = _read_head(
        dataset_case,
        dataset_id=materialized.dataset_id,
        version_id=materialized.version_id,
    )
    source_row = dataset_case.rows(
        """
        SELECT review_rows.id, review_rows.original_parsed_source_row_id,
               typed.customer_comments
        FROM version_rows AS review_rows
        INNER JOIN return_report_rows AS typed
            ON typed.version_id = review_rows.version_id
           AND typed.version_row_id = review_rows.id
        WHERE review_rows.version_id = :version_id
        ORDER BY review_rows.row_ordinal, review_rows.id
        LIMIT 1
        """,
        {"version_id": materialized.version_id},
    )[0]
    row_id = int(source_row["id"])
    parsed_source_row_id = int(source_row["original_parsed_source_row_id"])
    original_comment = str(source_row["customer_comments"])
    corrected_comment = "Corrected private customer comment"

    review_engine = dataset_case.runtime_engine()
    validation_engine = dataset_case.runtime_engine()
    try:
        review = ReviewService(
            repository=MySqlReviewRepository(review_engine),
            clock=lambda: NOW,
        )
        changed = review.set_field_value(
            SetFieldValueCommand(
                head=head,
                row_id=row_id,
                field_name="customer_comments",
                value=corrected_comment,
                actor_user_id=dataset_case.owner_user_id,
                operation_token=uuid4(),
                reason="Correct a deliberately selected private comment",
            )
        )
        head = _head_after(head, changed)
        for operation in ("exclude", "restore"):
            result = review.change_row_state(
                ChangeRowStateCommand(
                    head=head,
                    row_id=row_id,
                    operation=cast(Any, operation),
                    actor_user_id=dataset_case.owner_user_id,
                    operation_token=uuid4(),
                    reason=f"Exercise {operation} history in the workspace",
                )
            )
            head = _head_after(head, result)

        note_token = uuid4()
        note_target = FieldNoteTarget(
            version_id=materialized.version_id,
            row_id=row_id,
            field_name="customer_comments",
        )
        note = review.create_note(
            CreateNoteCommand(
                target=note_target,
                expected_review_revision=head.review_revision,
                body="Initial review note",
                visibility="internal",
                actor_user_id=dataset_case.owner_user_id,
                operation_token=note_token,
            )
        )
        head = _head_after(head, note)
        assert note.note_id is not None
        revised_note = review.revise_note(
            ReviseNoteCommand(
                note_key=f"review-{note_token.hex}",
                expected_note_id=note.note_id,
                expected_revision_number=1,
                target=note_target,
                expected_review_revision=head.review_revision,
                body="Latest review note for the corrected private comment",
                visibility="internal",
                actor_user_id=dataset_case.owner_user_id,
                operation_token=uuid4(),
            )
        )
        head = _head_after(head, revised_note)

        validation = ValidationService(
            repository=MySqlValidationRepository(validation_engine),
            clock=lambda: NOW,
        ).run_validation(
            RunValidationCommand(
                dataset_id=head.dataset_id,
                version_id=head.version_id,
                data_revision=head.data_revision,
                ruleset_version=ruleset_version,
                actor_user_id=dataset_case.owner_user_id,
                operation_token=uuid4(),
            )
        )
        with dataset_case.migration_engine.begin() as connection:
            inserted_issue = connection.execute(
                sa.text(
                    """
                    INSERT INTO validation_issues (
                        validation_run_id, version_id, row_id, severity,
                        rule_code, field_name, message, source_value_json,
                        processed_value_json, details_json, requires_note,
                        created_at
                    ) VALUES (
                        :validation_run_id, :version_id, :row_id, 'warning',
                        'workspace.private_comment_review', 'customer_comments',
                        'Confirm the corrected private comment.',
                        :source_value, :processed_value, :details, FALSE,
                        UTC_TIMESTAMP(6)
                    )
                    """
                ),
                {
                    "validation_run_id": validation.validation_run_id,
                    "version_id": head.version_id,
                    "row_id": row_id,
                    "source_value": json.dumps(
                        {"type": "text", "value": original_comment}
                    ),
                    "processed_value": json.dumps(
                        {"type": "text", "value": corrected_comment}
                    ),
                    "details": json.dumps({"test_fixture": True}),
                },
            )
            assert inserted_issue.lastrowid is not None
            validation_issue_id = int(inserted_issue.lastrowid)
        reviewed_issue = review.review_issue(
            ReviewIssueCommand(
                head=head,
                validation_run_id=validation.validation_run_id,
                validation_issue_id=validation_issue_id,
                issue_severity="warning",
                issue_requires_note=False,
                action="acknowledge",
                comment=None,
                actor_user_id=dataset_case.owner_user_id,
                operation_token=uuid4(),
            )
        )
        head = _head_after(head, reviewed_issue)
        assert head.review_revision == 3

        owner_username, admin_username, viewer_username = _prepare_credentials(
            dataset_case
        )
        settings = Settings(
            environment="test",
            log_level="WARNING",
            session_secret="test-session-secret-long-enough-for-review-workspace",
            session_ttl=timedelta(hours=1),
        )
        application = create_app(
            settings=settings,
            session_factory=create_session_factory(dataset_case.migration_engine),
        )
        with TestClient(application) as client:
            yield ReviewWorkspaceCase(
                dataset_case=dataset_case,
                client=client,
                dataset_id=materialized.dataset_id,
                version_id=materialized.version_id,
                row_id=row_id,
                source_batch_id=baseline.batch_id,
                parsed_source_row_id=parsed_source_row_id,
                original_comment=original_comment,
                corrected_comment=corrected_comment,
                owner_username=owner_username,
                admin_username=admin_username,
                viewer_username=viewer_username,
                validation_run_id=validation.validation_run_id,
                validation_issue_id=validation_issue_id,
            )
    finally:
        review_engine.dispose()
        validation_engine.dispose()
        _cleanup_review_workspace(dataset_case, materialized.version_id)


@pytest.fixture()
def published_move_workspace_case(
    publication_case: PublicationIntegrationCase,
) -> Iterator[PublishedMoveWorkspaceCase]:
    source_date = _isolated_date()
    target_date = source_date + timedelta(days=1)
    variant = uuid4().hex[:12]
    _source_baseline, source = publication_case.create_published_dataset(
        report_date=source_date,
        variant=f"workspace-move-source-{variant}",
    )
    _target_baseline, target = publication_case.create_published_dataset(
        report_date=target_date,
        variant=f"workspace-move-target-{variant}",
    )
    move_command = CreatePublishedMoveRevisionCommand(
        source_dataset_id=source.dataset_id,
        expected_source_publication=source.publication,
        target_report_date=target_date,
        target=PublishedMoveTarget(
            dataset_id=target.dataset_id,
            publication=target.publication,
            strategy="replace",
        ),
        merge_decisions=(),
        actor_user_id=publication_case.admin_user_id,
        operation_token=uuid4(),
        reason="Create a move draft whose context must survive a browser reload",
    )
    runtime_engine = publication_case.dataset_case.runtime_engine()
    try:
        move_draft = PublicationService(
            repository=MySqlPublicationRepository(runtime_engine),
            clock=lambda: NOW,
        ).create_published_move_revision(move_command)
    finally:
        runtime_engine.dispose()

    owner_username, admin_username, _viewer_username = _prepare_credentials(
        publication_case.dataset_case
    )
    settings = Settings(
        environment="test",
        log_level="WARNING",
        session_secret="test-session-secret-for-published-move-workspace",
        session_ttl=timedelta(hours=1),
    )
    application = create_app(
        settings=settings,
        session_factory=create_session_factory(
            publication_case.dataset_case.migration_engine
        ),
    )
    try:
        with TestClient(application) as client:
            yield PublishedMoveWorkspaceCase(
                publication_case=publication_case,
                client=client,
                source=source,
                target=target,
                move_command=move_command,
                move_draft=move_draft,
                admin_username=admin_username,
                owner_username=owner_username,
            )
    finally:
        user_bind: sa.BindParameter[Any] = sa.bindparam("user_ids", expanding=True)
        with publication_case.dataset_case.migration_engine.begin() as connection:
            connection.execute(
                sa.text(
                    "DELETE FROM auth_sessions WHERE user_id IN :user_ids"
                ).bindparams(user_bind),
                {"user_ids": publication_case.dataset_case.user_ids},
            )


def _cell(row: dict[str, Any], field_name: str) -> dict[str, Any]:
    return next(cell for cell in row["cells"] if cell["field_name"] == field_name)


def test_review_workspace_returns_three_way_values_history_notes_and_validation(
    review_workspace_case: ReviewWorkspaceCase,
) -> None:
    case = review_workspace_case
    case.login(case.owner_username)
    response = case.client.get(
        f"/api/drafts/{case.version_id}/review-workspace",
        params={"changed_only": True, "row_state": "active", "page_size": 1},
    )

    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["publication_mode"] == "ordinary"
    assert payload["published_move"] is None
    assert payload["report_type"] == "return_report"
    assert payload["source_batches"] == [{"batch_id": case.source_batch_id}]
    assert payload["pagination"] == {
        "page": 1,
        "page_size": 1,
        "total_rows": 1,
        "total_pages": 1,
    }
    assert payload["head"]["pointed_at"].endswith("Z")
    assert len(payload["rows"]) == 1
    row = payload["rows"][0]
    assert row["row_id"] == case.row_id
    assert [item["operation"] for item in row["history"]] == [
        "restore",
        "exclude",
    ]

    comments = _cell(row, "customer_comments")
    assert comments["source"] == {"type": "text", "value": case.original_comment}
    assert comments["base"] == {"type": "text", "value": case.original_comment}
    assert comments["current"] == {
        "type": "text",
        "value": case.corrected_comment,
    }
    assert comments["changed_from_base"] is True
    assert comments["changed_from_source"] is True
    assert comments["source_restore_option"] == {
        "source_batch_id": case.source_batch_id,
        "parsed_source_row_id": case.parsed_source_row_id,
        "value": {"type": "text", "value": case.original_comment},
    }
    assert comments["history"][0]["operation"] == "set"
    assert comments["history"][0]["before"]["value"] == case.original_comment
    assert comments["history"][0]["after"]["value"] == case.corrected_comment
    assert comments["notes"] == [
        {
            **comments["notes"][0],
            "revision_number": 2,
            "body": "Latest review note for the corrected private comment",
        }
    ]

    validation = payload["latest_full_validation"]
    assert validation["id"] == case.validation_run_id
    assert validation["is_current"] is True
    issue = next(
        item for item in validation["issues"] if item["id"] == case.validation_issue_id
    )
    assert issue["field_name"] == "customer_comments"
    assert issue["review"]["state"] == "acknowledged"
    assert issue["review"]["event_type"] == "acknowledge"
    assert issue["review"]["occurred_at"].endswith("Z")


def test_import_batch_notes_can_be_created_listed_and_revised(
    review_workspace_case: ReviewWorkspaceCase,
) -> None:
    case = review_workspace_case
    csrf_token = case.login(case.owner_username)
    create_token = uuid4()
    revise_token = uuid4()
    note_key = f"review-{create_token.hex}"
    operation_tokens = (create_token.bytes, revise_token.bytes)

    try:
        public_batch_note = case.client.post(
            f"/api/imports/{case.source_batch_id}/notes",
            json={
                "body": "Batch notes do not have a frozen viewer publication contract.",
                "visibility": "viewer_visible",
            },
            headers={
                CSRF_HEADER_NAME: csrf_token,
                "Idempotency-Key": str(uuid4()),
            },
        )
        assert public_batch_note.status_code == 422, public_batch_note.text

        created = case.client.post(
            f"/api/imports/{case.source_batch_id}/notes",
            json={
                "body": "The source file needs a batch-level handling note.",
                "visibility": "internal",
            },
            headers={
                CSRF_HEADER_NAME: csrf_token,
                "Idempotency-Key": str(create_token),
            },
        )
        assert created.status_code == 200, created.text

        listed = case.client.get(f"/api/imports/{case.source_batch_id}/notes")
        assert listed.status_code == 200, listed.text
        assert listed.json() == [
            {
                **listed.json()[0],
                "note_key": note_key,
                "revision_number": 1,
                "target_type": "import_batch",
                "import_batch_id": case.source_batch_id,
                "body": "The source file needs a batch-level handling note.",
                "visibility": "internal",
            }
        ]

        current = listed.json()[0]
        revised = case.client.post(
            f"/api/imports/{case.source_batch_id}/notes/{note_key}/revisions",
            json={
                "expected_note_id": current["note_id"],
                "expected_revision_number": 1,
                "body": "The batch-level note was checked again.",
                "visibility": "internal",
            },
            headers={
                CSRF_HEADER_NAME: csrf_token,
                "Idempotency-Key": str(revise_token),
            },
        )
        assert revised.status_code == 200, revised.text

        latest = case.client.get(f"/api/imports/{case.source_batch_id}/notes")
        assert latest.status_code == 200, latest.text
        assert latest.json() == [
            {
                **latest.json()[0],
                "note_key": note_key,
                "revision_number": 2,
                "body": "The batch-level note was checked again.",
                "visibility": "internal",
            }
        ]
    finally:
        token_bind: sa.BindParameter[Any] = sa.bindparam(
            "operation_tokens", expanding=True
        )
        with case.dataset_case.migration_engine.begin() as connection:
            connection.execute(
                sa.text(
                    "DELETE FROM review_operation_results "
                    "WHERE operation_token IN :operation_tokens"
                ).bindparams(token_bind),
                {"operation_tokens": operation_tokens},
            )
            note_ids = tuple(
                int(note_id)
                for note_id in connection.scalars(
                    sa.text(
                        "SELECT id FROM notes WHERE note_key = :note_key "
                        "ORDER BY revision_number DESC, id DESC"
                    ),
                    {"note_key": note_key},
                )
            )
            for note_id in note_ids:
                connection.execute(
                    sa.text("DELETE FROM notes WHERE id = :note_id"),
                    {"note_id": note_id},
                )
            connection.execute(
                sa.text("DELETE FROM note_threads WHERE note_key = :note_key"),
                {"note_key": note_key},
            )
            connection.execute(
                sa.text(
                    "DELETE FROM review_operation_tokens "
                    "WHERE operation_token IN :operation_tokens"
                ).bindparams(token_bind),
                {"operation_tokens": operation_tokens},
            )


def test_review_workspace_supports_the_business_report_field_contract(
    dataset_case: DatasetIntegrationCase,
) -> None:
    report_date = _isolated_date()
    baseline = dataset_case.seed_baseline(
        report_date=report_date,
        report_type="business_report",
        variant=uuid4().hex[:12],
    )
    runtime_engine = dataset_case.runtime_engine()
    try:
        materialized = DatasetService(
            repository=MySqlDatasetRepository(runtime_engine),
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
                actor_user_id=dataset_case.owner_user_id,
                operation_token=uuid4(),
                reason="Materialize business data for workspace API testing",
            )
        )
    finally:
        runtime_engine.dispose()

    with dataset_case.migration_engine.begin() as connection:
        connection.execute(
            sa.text(
                """
                UPDATE users
                SET password_hash = :password_hash, updated_at = UTC_TIMESTAMP(6)
                WHERE id = :user_id
                """
            ),
            {
                "password_hash": hash_password(_PASSWORD),
                "user_id": dataset_case.owner_user_id,
            },
        )
        owner_username = connection.scalar(
            sa.text("SELECT username_normalized FROM users WHERE id = :user_id"),
            {"user_id": dataset_case.owner_user_id},
        )
    assert isinstance(owner_username, str)
    settings = Settings(
        environment="test",
        log_level="WARNING",
        session_secret="test-session-secret-long-enough-for-business-workspace",
        session_ttl=timedelta(hours=1),
    )
    application = create_app(
        settings=settings,
        session_factory=create_session_factory(dataset_case.migration_engine),
    )
    try:
        with TestClient(application) as client:
            bootstrap = client.get("/api/auth/csrf")
            assert bootstrap.status_code == 200
            login = client.post(
                "/api/auth/login",
                json={"username": owner_username, "password": _PASSWORD},
                headers={CSRF_HEADER_NAME: str(bootstrap.json()["csrf_token"])},
            )
            assert login.status_code == 200, login.text
            response = client.get(
                f"/api/drafts/{materialized.version_id}/review-workspace",
                params={"page_size": 1},
            )
        assert response.status_code == 200, response.text
        payload = response.json()
        assert payload["report_type"] == "business_report"
        assert payload["source_batches"] == [{"batch_id": baseline.batch_id}]
        assert len(payload["fields"]) == 23
        assert payload["pagination"]["total_rows"] >= 1
        assert len(payload["rows"]) == 1
        row = payload["rows"][0]
        sku = _cell(row, "sku")
        assert sku["current"] == sku["base"] == sku["source"]
        assert sku["changed_from_base"] is False
        assert sku["changed_from_source"] is False
        sales = _cell(row, "ordered_product_sales")
        assert sales["current"]["type"] == "decimal"
        assert isinstance(sales["current"]["value"], str)
        assert _cell(row, "currency_code")["current"] == {
            "type": "text",
            "value": "USD",
        }
        assert payload["latest_full_validation"] is None
    finally:
        with dataset_case.migration_engine.begin() as connection:
            connection.execute(
                sa.text("DELETE FROM auth_sessions WHERE user_id = :user_id"),
                {"user_id": dataset_case.owner_user_id},
            )


def test_review_workspace_sensitive_values_are_isolated_by_server_role(
    review_workspace_case: ReviewWorkspaceCase,
) -> None:
    case = review_workspace_case
    path = f"/api/drafts/{case.version_id}/review-workspace"

    case.login(case.viewer_username)
    viewer = case.client.get(path)
    assert viewer.status_code == 403
    assert viewer.json()["error"]["code"] == "role_forbidden"
    assert case.corrected_comment not in viewer.text

    case.login(case.admin_username)
    administrator = case.client.get(path, params={"page_size": 1})
    assert administrator.status_code == 200
    first_row = administrator.json()["rows"][0]
    assert _cell(first_row, "order_id")["current"]["value"].startswith("000-")
    assert _cell(first_row, "license_plate_number")["current"]["value"].startswith(
        "LPN"
    )
    assert _cell(first_row, "customer_comments")["current"]["value"] == (
        case.corrected_comment
    )

    missing = case.client.get("/api/drafts/9223372036854775807/review-workspace")
    assert missing.status_code == 404
    assert missing.json()["error"]["code"] == "draft_not_found"


def test_administrator_recovers_published_move_context_from_server_ledger(
    published_move_workspace_case: PublishedMoveWorkspaceCase,
) -> None:
    case = published_move_workspace_case
    case.login(case.admin_username)

    response = case.client.get(
        f"/api/drafts/{case.move_draft.version_id}/review-workspace",
        params={"page_size": 1},
    )

    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["publication_mode"] == "published_move"
    context = payload["published_move"]
    assert context["revision_operation_token"] == str(case.move_command.operation_token)
    assert context["source_dataset_id"] == case.source.dataset_id
    assert context["source_report_date"] == case.source.report_date.isoformat()
    assert context["source_publication"]["version_id"] == case.source.version_id
    assert (
        _database_utc(
            datetime.fromisoformat(
                str(context["source_publication"]["published_at"]).replace(
                    "Z", "+00:00"
                )
            )
        )
        == case.source.publication.published_at
    )
    assert context["target_publication"]["version_id"] == case.target.version_id
    assert (
        _database_utc(
            datetime.fromisoformat(
                str(context["target_publication"]["published_at"]).replace(
                    "Z", "+00:00"
                )
            )
        )
        == case.target.publication.published_at
    )


def test_data_manager_does_not_receive_published_move_context(
    published_move_workspace_case: PublishedMoveWorkspaceCase,
) -> None:
    case = published_move_workspace_case
    case.login(case.owner_username)

    response = case.client.get(
        f"/api/drafts/{case.move_draft.version_id}/review-workspace",
        params={"page_size": 1},
    )

    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["publication_mode"] == "published_move"
    assert payload["published_move"] is None


def test_unpublished_date_reassignment_remains_ordinary_publication_mode(
    publication_case: PublicationIntegrationCase,
) -> None:
    source_date = _isolated_date()
    target_date = source_date + timedelta(days=1)
    _baseline, source = publication_case.materialize_baseline(
        report_date=source_date,
        variant=f"workspace-unpublished-move-{uuid4().hex[:12]}",
    )
    command = ReassignUnpublishedDraftDateCommand(
        source_dataset_id=source.dataset_id,
        source_draft=VersionExpectation(
            source.version_id,
            source.data_revision,
            source.review_revision,
        ),
        target_report_date=target_date,
        target=EmptyReassignmentTarget(),
        merge_decisions=(),
        actor_user_id=publication_case.owner_user_id,
        operation_token=uuid4(),
        reason="Correct an unpublished report date before review",
    )
    runtime_engine = publication_case.dataset_case.runtime_engine()
    try:
        moved = DatasetService(
            repository=MySqlDatasetRepository(runtime_engine),
            clock=lambda: NOW,
        ).reassign_unpublished_draft_date(command)
    finally:
        runtime_engine.dispose()

    owner_username, _admin_username, _viewer_username = _prepare_credentials(
        publication_case.dataset_case
    )
    application = create_app(
        settings=Settings(
            environment="test",
            log_level="WARNING",
            session_secret="test-session-secret-for-unpublished-move-workspace",
            session_ttl=timedelta(hours=1),
        ),
        session_factory=create_session_factory(
            publication_case.dataset_case.migration_engine
        ),
    )
    try:
        with TestClient(application) as client:
            bootstrap = client.get("/api/auth/csrf")
            assert bootstrap.status_code == 200
            login = client.post(
                "/api/auth/login",
                json={"username": owner_username, "password": _PASSWORD},
                headers={
                    CSRF_HEADER_NAME: str(bootstrap.json()["csrf_token"]),
                },
            )
            assert login.status_code == 200, login.text
            response = client.get(
                f"/api/drafts/{moved.version_id}/review-workspace",
                params={"page_size": 1},
            )
    finally:
        user_bind: sa.BindParameter[Any] = sa.bindparam("user_ids", expanding=True)
        with publication_case.dataset_case.migration_engine.begin() as connection:
            connection.execute(
                sa.text(
                    "DELETE FROM auth_sessions WHERE user_id IN :user_ids"
                ).bindparams(user_bind),
                {"user_ids": publication_case.dataset_case.user_ids},
            )

    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["publication_mode"] == "ordinary"
    assert payload["published_move"] is None


def test_administrator_gets_explicit_conflict_when_move_source_pointer_drifted(
    published_move_workspace_case: PublishedMoveWorkspaceCase,
) -> None:
    case = published_move_workspace_case
    with case.publication_case.dataset_case.migration_engine.begin() as connection:
        deleted = connection.execute(
            sa.text(
                "DELETE FROM dataset_publications "
                "WHERE dataset_id = :dataset_id AND version_id = :version_id"
            ),
            {
                "dataset_id": case.source.dataset_id,
                "version_id": case.source.version_id,
            },
        )
        assert deleted.rowcount == 1
    case.login(case.admin_username)

    response = case.client.get(
        f"/api/drafts/{case.move_draft.version_id}/review-workspace",
        params={"page_size": 1},
    )

    assert response.status_code == 409, response.text
    assert response.json()["error"]["code"] == "published_move_context_conflict"


def test_administrator_gets_explicit_conflict_when_move_target_pointer_drifted(
    published_move_workspace_case: PublishedMoveWorkspaceCase,
) -> None:
    case = published_move_workspace_case
    with case.publication_case.dataset_case.migration_engine.begin() as connection:
        deleted = connection.execute(
            sa.text(
                "DELETE FROM dataset_publications "
                "WHERE dataset_id = :dataset_id AND version_id = :version_id"
            ),
            {
                "dataset_id": case.target.dataset_id,
                "version_id": case.target.version_id,
            },
        )
        assert deleted.rowcount == 1
    case.login(case.admin_username)

    response = case.client.get(
        f"/api/drafts/{case.move_draft.version_id}/review-workspace",
        params={"page_size": 1},
    )

    assert response.status_code == 409, response.text
    assert response.json()["error"]["code"] == "published_move_context_conflict"


def test_administrator_gets_explicit_conflict_for_unledgered_moved_source_draft(
    published_move_workspace_case: PublishedMoveWorkspaceCase,
) -> None:
    case = published_move_workspace_case
    with case.publication_case.dataset_case.migration_engine.begin() as connection:
        deleted = connection.execute(
            sa.text(
                "DELETE FROM draft_operation_results "
                "WHERE operation_token = :operation_token"
            ),
            {"operation_token": case.move_command.operation_token.bytes},
        )
        assert deleted.rowcount == 1
    case.login(case.admin_username)

    response = case.client.get(
        f"/api/drafts/{case.move_draft.version_id}/review-workspace",
        params={"page_size": 1},
    )

    assert response.status_code == 409, response.text
    assert response.json()["error"]["code"] == "published_move_context_conflict"
