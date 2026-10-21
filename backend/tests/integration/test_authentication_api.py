from __future__ import annotations

from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from typing import Any, cast
from uuid import uuid4

import pytest
import sqlalchemy as sa
from alembic import command
from alembic.config import Config
from app.api.dependencies import CSRF_HEADER_NAME, SESSION_COOKIE_NAME
from app.auth.passwords import hash_password
from app.auth.sessions import LoginRateLimiter, SessionService
from app.config import Settings
from app.db.session import create_session_factory
from app.main import create_app
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy.engine import Engine

pytestmark = pytest.mark.mysql


def _create_user(engine: Engine, *, role: str, password: str) -> tuple[int, str]:
    username = f"api-{role}-{uuid4().hex}"
    with engine.begin() as connection:
        result = connection.execute(
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
                "display_name": f"API {role}",
                "password_hash": hash_password(password),
            },
        )
        assert result.lastrowid is not None
        user_id = int(result.lastrowid)
        connection.execute(
            sa.text(
                """
                INSERT INTO user_roles (user_id, role_id, assigned_at)
                SELECT :user_id, id, UTC_TIMESTAMP(6)
                FROM roles
                WHERE code = :role
                """
            ),
            {"user_id": user_id, "role": role},
        )
    return user_id, username


@pytest.fixture()
def api_settings() -> Settings:
    return Settings(
        environment="test",
        log_level="WARNING",
        cors_allowed_origins=("https://review.example.test",),
        session_secret="test-session-secret-that-is-long-enough-for-authentication",
        session_ttl=timedelta(hours=1),
        login_rate_limit_attempts=2,
        login_rate_limit_window=timedelta(minutes=1),
    )


@pytest.fixture()
def api_client(
    alembic_config: Config,
    mysql_engine: Engine,
    api_settings: Settings,
) -> Iterator[TestClient]:
    command.upgrade(alembic_config, "head")
    session_factory = create_session_factory(mysql_engine)
    with TestClient(
        create_app(settings=api_settings, session_factory=session_factory)
    ) as client:
        yield client


def _login(
    client: TestClient,
    *,
    username: str,
    password: str,
) -> tuple[dict[str, Any], str, Any]:
    csrf_response = client.get("/api/auth/csrf")
    assert csrf_response.status_code == 200
    bootstrap_csrf = str(csrf_response.json()["csrf_token"])
    response = client.post(
        "/api/auth/login",
        json={"username": username, "password": password},
        headers={CSRF_HEADER_NAME: bootstrap_csrf},
    )
    assert response.status_code == 200, response.text
    response_payload: dict[str, Any] = response.json()
    return response_payload, str(response_payload["csrf_token"]), response


def test_login_session_csrf_and_logout_contract(
    api_client: TestClient,
    mysql_engine: Engine,
) -> None:
    _, username = _create_user(mysql_engine, role="admin", password="correct horse")

    response_payload, csrf_token, login_response = _login(
        api_client,
        username=username,
        password="correct horse",
    )

    set_cookie_headers = login_response.headers.get_list("set-cookie")
    assert any(
        header.startswith(f"{SESSION_COOKIE_NAME}=")
        and "HttpOnly" in header
        and "SameSite=lax" in header
        for header in set_cookie_headers
    )
    assert response_payload["user"] == {
        "id": response_payload["user"]["id"],
        "username": username,
        "display_name": "API admin",
        "roles": ["admin"],
    }

    assert api_client.get("/api/auth/me").status_code == 200
    old_session_token = api_client.cookies[SESSION_COOKIE_NAME]
    missing_csrf = api_client.post("/api/auth/logout")
    assert missing_csrf.status_code == 403
    assert missing_csrf.json()["error"]["code"] == "csrf_invalid"

    logged_out = api_client.post(
        "/api/auth/logout",
        headers={CSRF_HEADER_NAME: csrf_token},
    )
    assert logged_out.status_code == 204
    unauthenticated = api_client.get("/api/auth/me")
    assert unauthenticated.status_code == 401
    assert unauthenticated.json()["error"]["code"] == "authentication_required"
    api_client.cookies.set(SESSION_COOKIE_NAME, old_session_token)
    revoked_session = api_client.get("/api/auth/me")
    assert revoked_session.status_code == 401
    assert revoked_session.json()["error"]["code"] == "session_invalid"


@pytest.mark.parametrize("role", ["viewer", "data_manager"])
def test_non_administrators_cannot_read_administrator_role_catalogue(
    api_client: TestClient,
    mysql_engine: Engine,
    role: str,
) -> None:
    _, username = _create_user(mysql_engine, role=role, password="correct horse")
    _payload, _csrf_token, _login_response = _login(
        api_client,
        username=username,
        password="correct horse",
    )

    response = api_client.get("/api/admin/roles")

    assert response.status_code == 403
    assert response.json()["error"]["code"] == "role_forbidden"

    undoable_moves = api_client.get("/api/admin/published-moves/undoable")
    assert undoable_moves.status_code == 403
    assert undoable_moves.json()["error"]["code"] == "role_forbidden"


def test_administrator_can_read_role_catalogue(
    api_client: TestClient,
    mysql_engine: Engine,
) -> None:
    _, username = _create_user(mysql_engine, role="admin", password="correct horse")
    _payload, _csrf_token, _login_response = _login(
        api_client,
        username=username,
        password="correct horse",
    )

    response = api_client.get("/api/admin/roles")

    assert response.status_code == 200
    assert [item["code"] for item in response.json()] == [
        "admin",
        "data_manager",
        "viewer",
    ]

    undoable_moves = api_client.get("/api/admin/published-moves/undoable")
    assert undoable_moves.status_code == 200
    assert isinstance(undoable_moves.json(), list)


def test_viewer_can_read_only_the_calendar_contract(
    api_client: TestClient,
    mysql_engine: Engine,
) -> None:
    _, username = _create_user(mysql_engine, role="viewer", password="correct horse")
    _payload, csrf_token, _login_response = _login(
        api_client,
        username=username,
        password="correct horse",
    )

    response = api_client.get(
        "/api/data-calendar",
        params={"from": "2090-01-01", "to": "2090-01-31"},
    )
    invalid_range = api_client.get(
        "/api/data-calendar",
        params={"from": "2090-01-31", "to": "2090-01-01"},
    )

    assert response.status_code == 200
    assert invalid_range.status_code == 422
    assert invalid_range.json()["error"]["code"] == "invalid_date_range"
    rejected_write = api_client.post(
        "/api/imports/1/inspect",
        headers={CSRF_HEADER_NAME: csrf_token},
    )
    assert rejected_write.status_code == 403
    assert rejected_write.json()["error"]["code"] == "role_forbidden"
    rejected_draft = api_client.get("/api/drafts/1")
    assert rejected_draft.status_code == 403
    assert rejected_draft.json()["error"]["code"] == "role_forbidden"


def test_viewer_can_read_redacted_published_dashboard_contract(
    api_client: TestClient,
    mysql_engine: Engine,
) -> None:
    _, username = _create_user(mysql_engine, role="viewer", password="correct horse")
    _payload, _csrf_token, _login_response = _login(
        api_client,
        username=username,
        password="correct horse",
    )

    summary = api_client.get(
        "/api/dashboard/summary",
        params={"from": "2090-01-01", "to": "2090-01-02"},
    )
    products = api_client.get(
        "/api/dashboard/products",
        params={"from": "2090-01-01", "to": "2090-01-02"},
    )
    returns = api_client.get(
        "/api/dashboard/returns",
        params={"from": "2090-01-01", "to": "2090-01-02"},
    )

    assert summary.status_code == products.status_code == returns.status_code == 200
    assert summary.json()["metrics"] == [
        {
            "report_date": "2090-01-01",
            "sales": "0",
            "units_ordered": 0,
            "sessions": 0,
            "conversion_rate": None,
            "return_quantity": 0,
            "business_version_id": None,
            "return_version_id": None,
        },
        {
            "report_date": "2090-01-02",
            "sales": "0",
            "units_ordered": 0,
            "sessions": 0,
            "conversion_rate": None,
            "return_quantity": 0,
            "business_version_id": None,
            "return_version_id": None,
        },
    ]
    assert products.json()["rows"] == []
    assert products.json()["publications"] == []
    assert returns.json()["rows"] == []
    assert summary.json()["publications"] == []
    assert summary.json()["site_config_versions"] == []
    assert products.json()["site_config_versions"] == []
    assert returns.json()["publications"] == []
    assert returns.json()["site_config_versions"] == []
    assert (
        api_client.get(
            "/api/dashboard/summary",
            params={"from": "2090-01-02", "to": "2090-01-01"},
        ).json()["error"]["code"]
        == "invalid_date_range"
    )

    for path in (
        "/api/dashboard/summary",
        "/api/dashboard/products",
        "/api/dashboard/returns",
    ):
        oversized = api_client.get(
            path,
            params={"from": "2090-01-01", "to": "2091-01-02"},
        )
        assert oversized.status_code == 422
        error = oversized.json()["error"]
        assert error["code"] == "date_range_too_large"
        assert error["message"] == "Date range must not exceed 366 calendar days."


def test_login_does_not_disclose_account_existence_and_is_rate_limited(
    api_client: TestClient,
    mysql_engine: Engine,
) -> None:
    _, username = _create_user(mysql_engine, role="viewer", password="correct horse")
    bootstrap_csrf = str(api_client.get("/api/auth/csrf").json()["csrf_token"])
    bad_password = api_client.post(
        "/api/auth/login",
        json={"username": username, "password": "wrong password"},
        headers={CSRF_HEADER_NAME: bootstrap_csrf},
    )
    unknown_account = api_client.post(
        "/api/auth/login",
        json={"username": "does-not-exist", "password": "wrong password"},
        headers={CSRF_HEADER_NAME: bootstrap_csrf},
    )
    rate_limited = api_client.post(
        "/api/auth/login",
        json={"username": username, "password": "wrong password"},
        headers={CSRF_HEADER_NAME: bootstrap_csrf},
    )
    rate_limited = api_client.post(
        "/api/auth/login",
        json={"username": username, "password": "wrong password"},
        headers={CSRF_HEADER_NAME: bootstrap_csrf},
    )

    assert bad_password.status_code == unknown_account.status_code == 401
    assert (
        bad_password.json()["error"]["message"]
        == unknown_account.json()["error"]["message"]
    )
    assert rate_limited.status_code == 429
    assert rate_limited.headers["Retry-After"]


def test_login_rate_limit_uses_the_account_lookup_username_normalisation(
    api_client: TestClient,
    mysql_engine: Engine,
) -> None:
    _, username = _create_user(mysql_engine, role="viewer", password="correct horse")
    fullwidth_alias = "".join(
        chr(ord(character) + 0xFEE0) if "!" <= character <= "~" else character
        for character in username
    )
    bootstrap_csrf = str(api_client.get("/api/auth/csrf").json()["csrf_token"])

    first_failure = api_client.post(
        "/api/auth/login",
        json={"username": username, "password": "wrong password"},
        headers={CSRF_HEADER_NAME: bootstrap_csrf},
    )
    second_failure = api_client.post(
        "/api/auth/login",
        json={"username": fullwidth_alias, "password": "wrong password"},
        headers={CSRF_HEADER_NAME: bootstrap_csrf},
    )
    rate_limited = api_client.post(
        "/api/auth/login",
        json={"username": f"  {username.upper()}  ", "password": "wrong password"},
        headers={CSRF_HEADER_NAME: bootstrap_csrf},
    )

    assert first_failure.status_code == second_failure.status_code == 401
    assert rate_limited.status_code == 429


def test_login_rate_limit_caps_failures_across_usernames_from_one_ip(
    api_client: TestClient,
) -> None:
    cast(FastAPI, api_client.app).state.login_rate_limiter = LoginRateLimiter(
        maximum_attempts=2,
        maximum_source_attempts=3,
        maximum_tracked_keys=20,
        window=timedelta(minutes=1),
    )
    bootstrap_csrf = str(api_client.get("/api/auth/csrf").json()["csrf_token"])

    failures = [
        api_client.post(
            "/api/auth/login",
            json={
                "username": f"unknown-account-{index}",
                "password": "wrong password",
            },
            headers={CSRF_HEADER_NAME: bootstrap_csrf},
        )
        for index in range(3)
    ]
    rate_limited = api_client.post(
        "/api/auth/login",
        json={"username": "unknown-account-4", "password": "wrong password"},
        headers={CSRF_HEADER_NAME: bootstrap_csrf},
    )

    assert [response.status_code for response in failures] == [401, 401, 401]
    assert rate_limited.status_code == 429
    assert rate_limited.headers["Retry-After"]


def test_expired_session_is_rejected(
    api_client: TestClient,
    api_settings: Settings,
    mysql_engine: Engine,
) -> None:
    _, username = _create_user(mysql_engine, role="viewer", password="correct horse")
    session_factory = create_session_factory(mysql_engine)
    service = SessionService(api_settings)
    with session_factory() as database_session, database_session.begin():
        login = service.authenticate(
            database_session,
            username=username,
            password="correct horse",
            request_id="expired-session-test",
            now=datetime.now(tz=UTC).replace(tzinfo=None) - timedelta(hours=2),
        )
    assert login is not None
    api_client.cookies.set(SESSION_COOKIE_NAME, login.session_token)

    response = api_client.get("/api/auth/me")

    assert response.status_code == 401
    assert response.json()["error"]["code"] == "session_invalid"


def _stage_seven_write_requests() -> list[tuple[str, dict[str, Any], bool]]:
    missing_id = 2_147_483_000
    published_pointer = {
        "version_id": missing_id,
        "published_at": "2090-01-01T00:00:00Z",
    }
    empty_pointer = {"version_id": None, "published_at": None}
    draft_pointer = {
        "version_id": missing_id,
        "status": "ready_for_publish",
        "data_revision": 0,
        "review_revision": 1,
        "pointed_at": "2090-01-01T00:00:00Z",
    }
    draft_version = {
        "version_id": missing_id,
        "data_revision": 0,
        "review_revision": 0,
    }
    validation = {
        "run_id": missing_id,
        "version_id": missing_id,
        "data_revision": 0,
        "ruleset_version": "stage-seven-contract-v1",
        "data_digest": "11" * 32,
    }
    confirmation = {
        "confirmed_report_date": "2090-01-01",
        "report_type": "business_report",
        "row_count": 0,
        "totals": [],
    }
    reason = "Verify the server-side role boundary"
    return [
        (
            "/api/datasets/materialize",
            {
                "batch_id": missing_id,
                "parse_baseline_id": missing_id,
                "report_date": "2090-01-01",
                "strategy": "replace",
                "expected_active_draft": None,
                "expected_publication_version_id": None,
                "merge_decisions": [],
                "reason": reason,
            },
            False,
        ),
        (
            f"/api/drafts/{missing_id}/discard",
            {
                "dataset_id": missing_id,
                "expected_active_draft": draft_version,
                "reason": reason,
            },
            False,
        ),
        (
            f"/api/drafts/{missing_id}/reassign-date",
            {
                "source_dataset_id": missing_id,
                "source_draft": draft_version,
                "target_report_date": "2090-01-02",
                "target": {"target_kind": "empty"},
                "merge_decisions": [],
                "reason": reason,
            },
            False,
        ),
        (
            f"/api/datasets/{missing_id}/publish",
            {
                "expected_draft": draft_pointer,
                "expected_publication": empty_pointer,
                "validation": validation,
                "confirmation": confirmation,
                "reason": reason,
            },
            False,
        ),
        (
            f"/api/datasets/{missing_id}/revisions",
            {"expected_publication": published_pointer, "reason": reason},
            False,
        ),
        (
            f"/api/admin/drafts/{missing_id}/force-rebuild",
            {
                "batch_id": missing_id,
                "parse_baseline_id": missing_id,
                "report_date": "2090-01-01",
                "expected_active_draft": draft_version,
                "expected_publication_version_id": None,
                "reason": reason,
            },
            True,
        ),
        (
            f"/api/admin/datasets/{missing_id}/rollback",
            {
                "expected_publication": published_pointer,
                "target_version_id": missing_id - 1,
                "reason": reason,
            },
            True,
        ),
        (
            f"/api/admin/versions/{missing_id}/move-date",
            {
                "source_dataset_id": missing_id,
                "expected_source_publication": published_pointer,
                "target_report_date": "2090-01-02",
                "target": {"target_kind": "empty"},
                "merge_decisions": [],
                "reason": reason,
            },
            True,
        ),
        (
            f"/api/admin/published-moves/{uuid4()}/finalize",
            {
                "source_dataset_id": missing_id,
                "expected_source_publication": published_pointer,
                "target_dataset_id": missing_id - 1,
                "expected_target_draft": draft_pointer,
                "expected_target_publication": empty_pointer,
                "validation": validation,
                "confirmation": confirmation,
                "reason": reason,
            },
            True,
        ),
        (
            f"/api/admin/published-moves/{missing_id}/undo",
            {
                "source_dataset_id": missing_id,
                "expected_source_publication": empty_pointer,
                "restore_source_version_id": missing_id,
                "target_dataset_id": missing_id - 1,
                "expected_target_publication": published_pointer,
                "restore_target_version_id": None,
                "reason": reason,
            },
            True,
        ),
    ]


@pytest.mark.parametrize("role", ["admin", "data_manager", "viewer"])
def test_stage_seven_write_routes_enforce_the_three_role_matrix(
    api_client: TestClient,
    mysql_engine: Engine,
    role: str,
) -> None:
    _, username = _create_user(mysql_engine, role=role, password="correct horse")
    _payload, csrf_token, _login_response = _login(
        api_client,
        username=username,
        password="correct horse",
    )

    for path, payload, admin_only in _stage_seven_write_requests():
        response = api_client.post(
            path,
            json=payload,
            headers={
                CSRF_HEADER_NAME: csrf_token,
                "Idempotency-Key": str(uuid4()),
            },
        )
        should_be_allowed = role == "admin" or (
            role == "data_manager" and not admin_only
        )
        if should_be_allowed:
            assert response.status_code in {404, 409, 503}, (path, response.text)
            assert response.json()["error"]["code"] != "role_forbidden"
        else:
            assert response.status_code == 403, (path, response.text)
            assert response.json()["error"]["code"] == "role_forbidden"

    raw_file_response = api_client.get("/api/imports/2147483000/raw-file")
    if role in {"admin", "data_manager"}:
        assert raw_file_response.status_code == 404
        assert raw_file_response.json()["error"]["code"] == "import_not_found"
    else:
        assert raw_file_response.status_code == 403
        assert raw_file_response.json()["error"]["code"] == "role_forbidden"

    raw_file_head = api_client.head("/api/imports/2147483000/raw-file")
    if role in {"admin", "data_manager"}:
        assert raw_file_head.status_code == 404
    else:
        assert raw_file_head.status_code == 403
