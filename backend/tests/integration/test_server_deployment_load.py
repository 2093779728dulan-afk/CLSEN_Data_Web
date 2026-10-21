from __future__ import annotations

import os
import ssl
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, date, datetime
from pathlib import Path
from threading import Barrier
from typing import Any
from uuid import uuid4

import httpx2
import pytest
import sqlalchemy as sa
from app.api.dependencies import CSRF_HEADER_NAME
from app.auth.passwords import hash_password
from app.datasets.repository import MySqlDatasetRepository
from app.datasets.service import DatasetService
from app.datasets.types import MaterializeBaselineCommand
from sqlalchemy.engine import Engine

from tests.integration.dataset_test_support import (
    dataset_case as _dataset_case,  # noqa: F401 - registers shared fixture
)
from tests.integration.publication_test_support import (
    PublicationIntegrationCase,
    PublishedDataset,
    ReadyPublicationDraft,
)
from tests.integration.publication_test_support import (
    publication_case as _publication_case,  # noqa: F401 - registers fixture
)

pytestmark = pytest.mark.mysql

_VIEWER_COUNT = 20
_READS_PER_VIEWER = 5


def _deployment_target() -> tuple[str, str]:
    base_url = os.getenv("APP_DEPLOYMENT_HTTPS_BASE_URL", "").strip()
    ca_path = os.getenv("APP_DEPLOYMENT_HTTPS_CA", "").strip()
    if not base_url or not ca_path:
        pytest.skip("container HTTPS verification target is not configured")
    if not base_url.startswith("https://"):
        pytest.fail("deployment verification requires an HTTPS target")
    if not Path(ca_path).is_file():
        pytest.fail("deployment verification CA certificate is unavailable")
    return base_url, ca_path


def _client(base_url: str, ca_path: str) -> httpx2.Client:
    return httpx2.Client(
        base_url=base_url,
        verify=ssl.create_default_context(cafile=ca_path),
        trust_env=False,
        timeout=15,
    )


def _login(client: httpx2.Client, *, username: str, password: str) -> str:
    bootstrap = client.get("/api/auth/csrf")
    assert bootstrap.status_code == 200, bootstrap.text
    token = str(bootstrap.json()["csrf_token"])
    response = client.post(
        "/api/auth/login",
        json={"username": username, "password": password},
        headers={CSRF_HEADER_NAME: token},
    )
    assert response.status_code == 200, response.text
    return str(response.json()["csrf_token"])


def _create_viewers(
    engine: Engine,
    *,
    assigned_by: int,
    password: str,
) -> tuple[tuple[int, str], ...]:
    password_hash = hash_password(password)
    viewers: list[tuple[int, str]] = []
    with engine.begin() as connection:
        for index in range(_VIEWER_COUNT):
            username = f"load-viewer-{index}-{uuid4().hex}"
            inserted = connection.execute(
                sa.text(
                    """
                    INSERT INTO users (
                        username_normalized, display_name, password_hash, status,
                        created_at, updated_at
                    ) VALUES (
                        :username, :display_name, :password_hash, 'active',
                        UTC_TIMESTAMP(6), UTC_TIMESTAMP(6)
                    )
                    """
                ),
                {
                    "username": username,
                    "display_name": f"Deployment Viewer {index + 1}",
                    "password_hash": password_hash,
                },
            )
            assert inserted.lastrowid is not None
            user_id = int(inserted.lastrowid)
            connection.execute(
                sa.text(
                    """
                    INSERT INTO user_roles (user_id, role_id, assigned_by, assigned_at)
                    SELECT :user_id, id, :assigned_by, UTC_TIMESTAMP(6)
                    FROM roles WHERE code = 'viewer'
                    """
                ),
                {"user_id": user_id, "assigned_by": assigned_by},
            )
            viewers.append((user_id, username))
    return tuple(viewers)


def _prepare_manager(
    engine: Engine,
    *,
    user_id: int,
    password: str,
) -> str:
    password_hash = hash_password(password)
    with engine.begin() as connection:
        username = connection.scalar(
            sa.text("SELECT username_normalized FROM users WHERE id = :user_id"),
            {"user_id": user_id},
        )
        assert username is not None
        connection.execute(
            sa.text(
                "UPDATE users SET password_hash = :password_hash WHERE id = :user_id"
            ),
            {"password_hash": password_hash, "user_id": user_id},
        )
    return str(username)


def _cleanup_viewers(engine: Engine, user_ids: tuple[int, ...]) -> None:
    if not user_ids:
        return
    user_bind: sa.BindParameter[Any] = sa.bindparam("user_ids", expanding=True)
    parameters = {"user_ids": user_ids}
    with engine.begin() as connection:
        connection.execute(
            sa.text(
                "DELETE FROM audit_events WHERE actor_user_id IN :user_ids"
            ).bindparams(user_bind),
            parameters,
        )
        for table in ("auth_sessions", "user_roles"):
            connection.execute(
                sa.text(f"DELETE FROM {table} WHERE user_id IN :user_ids").bindparams(
                    user_bind
                ),
                parameters,
            )
        connection.execute(
            sa.text("DELETE FROM users WHERE id IN :user_ids").bindparams(user_bind),
            parameters,
        )


def _cleanup_manager_session(engine: Engine, user_id: int) -> None:
    with engine.begin() as connection:
        connection.execute(
            sa.text("DELETE FROM auth_sessions WHERE user_id = :user_id"),
            {"user_id": user_id},
        )


def _publish_initial(
    case: PublicationIntegrationCase,
    *,
    report_date: date,
) -> PublishedDataset:
    _baseline, published = case.create_published_dataset(
        report_date=report_date,
        variant="load-old",
    )
    return published


def _ready_revision(
    case: PublicationIntegrationCase,
    published: PublishedDataset,
) -> ReadyPublicationDraft:
    baseline = case.dataset_case.seed_baseline(
        report_date=published.report_date,
        report_type=published.report_type,
        variant="load-new",
    )
    engine = case.dataset_case.runtime_engine()
    try:
        draft = DatasetService(
            repository=MySqlDatasetRepository(engine),
            clock=lambda: datetime(2026, 8, 11, 8, 0, tzinfo=UTC),
        ).materialize_baseline(
            MaterializeBaselineCommand(
                batch_id=baseline.batch_id,
                parse_baseline_id=baseline.parse_baseline_id,
                report_date=published.report_date,
                strategy="replace",
                expected_active_draft=None,
                expected_publication_version_id=published.version_id,
                merge_decisions=(),
                actor_user_id=case.owner_user_id,
                operation_token=uuid4(),
                reason="Prepare the deployment publication consistency check",
            )
        )
    finally:
        engine.dispose()
    return case.mark_ready(dataset_id=draft.dataset_id, version_id=draft.version_id)


def _publication_payload(
    ready: ReadyPublicationDraft,
    published: PublishedDataset,
) -> dict[str, Any]:
    return {
        "expected_draft": {
            "version_id": ready.expectation.version_id,
            "status": ready.expectation.status,
            "data_revision": ready.expectation.data_revision,
            "review_revision": ready.expectation.review_revision,
            "pointed_at": ready.expectation.pointed_at.isoformat(),
        },
        "expected_publication": {
            "version_id": published.publication.version_id,
            "published_at": published.publication.published_at.isoformat()
            if published.publication.published_at is not None
            else None,
        },
        "validation": {
            "run_id": ready.validation.run_id,
            "version_id": ready.validation.version_id,
            "data_revision": ready.validation.data_revision,
            "ruleset_version": ready.validation.ruleset_version,
            "data_digest": ready.validation.data_digest.hex(),
        },
        "confirmation": {
            "confirmed_report_date": (
                ready.confirmation.confirmed_report_date.isoformat()
            ),
            "report_type": ready.confirmation.report_type,
            "row_count": ready.confirmation.row_count,
            "totals": [
                {"field_name": field_name, "value": value}
                for field_name, value in ready.confirmation.totals
            ],
        },
        "reason": "Publish once while twenty viewers read through HTTPS",
    }


def test_twenty_https_viewers_observe_only_complete_publications_during_publish(
    publication_case: PublicationIntegrationCase,
) -> None:
    base_url, ca_path = _deployment_target()
    report_date = date(2199, 8, 11)
    published = _publish_initial(publication_case, report_date=report_date)
    ready = _ready_revision(publication_case, published)
    password = "deployment consistency password"
    manager_username = _prepare_manager(
        publication_case.dataset_case.migration_engine,
        user_id=publication_case.owner_user_id,
        password=password,
    )
    viewers = _create_viewers(
        publication_case.dataset_case.migration_engine,
        assigned_by=publication_case.owner_user_id,
        password=password,
    )
    viewer_clients: list[httpx2.Client] = []
    manager_client = _client(base_url, ca_path)
    try:
        manager_csrf = _login(
            manager_client,
            username=manager_username,
            password=password,
        )
        for _user_id, username in viewers:
            client = _client(base_url, ca_path)
            _login(client, username=username, password=password)
            viewer_clients.append(client)

        barrier = Barrier(_VIEWER_COUNT + 1)
        expected_versions = {published.version_id, ready.version_id}

        def read_dashboard(client: httpx2.Client) -> tuple[int, ...]:
            barrier.wait(timeout=30)
            observed: list[int] = []
            for _index in range(_READS_PER_VIEWER):
                response = client.get(
                    "/api/dashboard/summary",
                    params={
                        "from": report_date.isoformat(),
                        "to": report_date.isoformat(),
                    },
                )
                assert response.status_code == 200, response.text
                payload = response.json()
                metric_version = int(payload["metrics"][0]["business_version_id"])
                reference_versions = {
                    int(item["version_id"])
                    for item in payload["publications"]
                    if item["report_type"] == "business_report"
                }
                assert reference_versions == {metric_version}
                assert metric_version in expected_versions
                observed.append(metric_version)
            return tuple(observed)

        def publish_once() -> int:
            barrier.wait(timeout=30)
            response = manager_client.post(
                f"/api/datasets/{ready.dataset_id}/publish",
                json=_publication_payload(ready, published),
                headers={
                    CSRF_HEADER_NAME: manager_csrf,
                    "Idempotency-Key": str(uuid4()),
                },
            )
            assert response.status_code == 200, response.text
            transition = response.json()["transitions"][0]
            return int(transition["next_version_id"])

        with ThreadPoolExecutor(max_workers=_VIEWER_COUNT + 1) as executor:
            read_futures = [
                executor.submit(read_dashboard, client) for client in viewer_clients
            ]
            publish_future = executor.submit(publish_once)
            observed = [
                version_id
                for future in read_futures
                for version_id in future.result(timeout=90)
            ]
            published_version = publish_future.result(timeout=90)

        assert len(observed) == _VIEWER_COUNT * _READS_PER_VIEWER
        assert set(observed).issubset(expected_versions)
        assert published_version == ready.version_id
        assert (
            publication_case.publication_pointer(ready.dataset_id).version_id
            == ready.version_id
        )
    finally:
        manager_client.close()
        for client in viewer_clients:
            client.close()
        _cleanup_manager_session(
            publication_case.dataset_case.migration_engine,
            publication_case.owner_user_id,
        )
        _cleanup_viewers(
            publication_case.dataset_case.migration_engine,
            tuple(user_id for user_id, _username in viewers),
        )
