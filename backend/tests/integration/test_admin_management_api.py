from __future__ import annotations

import json
import os
from collections.abc import Iterator
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from threading import Event, Lock
from typing import Any
from uuid import UUID, uuid4

import pytest
import sqlalchemy as sa
from alembic import command
from alembic.config import Config
from app.api.admin_management import _command_digest
from app.api.dependencies import CSRF_HEADER_NAME
from app.auth.passwords import hash_password, verify_password
from app.config import Settings
from app.db.engine import create_database_engine
from app.db.session import create_session_factory
from app.db.settings import DatabaseSettings
from app.main import create_app
from app.maintenance.barrier import hold_maintenance_write_barrier
from fastapi.testclient import TestClient
from sqlalchemy.engine import Engine

pytestmark = pytest.mark.mysql


@dataclass(slots=True)
class AdminApiContext:
    client: TestClient
    engine: Engine
    api_engine: Engine
    admin_user_id: int
    admin_username: str
    csrf_token: str
    created_user_ids: list[int] = field(default_factory=list)
    created_site_ids: list[int] = field(default_factory=list)


def _create_user(
    engine: Engine,
    *,
    role: str,
    password: str,
) -> tuple[int, str]:
    username = f"admin-api-{role}-{uuid4().hex}"
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
                "display_name": f"Admin API {role}",
                "password_hash": hash_password(password),
            },
        )
        assert result.lastrowid is not None
        user_id = int(result.lastrowid)
        connection.execute(
            sa.text(
                """
                INSERT INTO user_roles (
                    user_id, role_id, assigned_by, assigned_at
                )
                SELECT :user_id, id, :user_id, UTC_TIMESTAMP(6)
                FROM roles
                WHERE code = :role
                """
            ),
            {"user_id": user_id, "role": role},
        )
    return user_id, username


def _login(
    client: TestClient,
    *,
    username: str,
    password: str,
) -> str:
    bootstrap = client.get("/api/auth/csrf")
    assert bootstrap.status_code == 200
    bootstrap_token = str(bootstrap.json()["csrf_token"])
    response = client.post(
        "/api/auth/login",
        json={"username": username, "password": password},
        headers={CSRF_HEADER_NAME: bootstrap_token},
    )
    assert response.status_code == 200, response.text
    return str(response.json()["csrf_token"])


def _write_headers(
    context: AdminApiContext,
    *,
    operation_token: UUID | None = None,
) -> dict[str, str]:
    token = operation_token or uuid4()
    return {
        CSRF_HEADER_NAME: context.csrf_token,
        "Idempotency-Key": str(token),
    }


def _cleanup(context: AdminApiContext) -> None:
    with context.engine.begin() as connection:
        if context.created_user_ids:
            user_bind: sa.BindParameter[Any] = sa.bindparam("user_ids", expanding=True)
            parameters = {"user_ids": tuple(context.created_user_ids)}
            connection.execute(
                sa.text(
                    "DELETE FROM admin_operation_results "
                    "WHERE actor_user_id IN :user_ids"
                ).bindparams(user_bind),
                parameters,
            )
            connection.execute(
                sa.text(
                    "DELETE FROM admin_operation_tokens "
                    "WHERE actor_user_id IN :user_ids"
                ).bindparams(user_bind),
                parameters,
            )
        for site_id in context.created_site_ids:
            connection.execute(
                sa.text("DELETE FROM audit_events WHERE site_id = :site_id"),
                {"site_id": site_id},
            )
            connection.execute(
                sa.text("DELETE FROM site_current_configs WHERE site_id = :site_id"),
                {"site_id": site_id},
            )
            connection.execute(
                sa.text("DELETE FROM site_config_versions WHERE site_id = :site_id"),
                {"site_id": site_id},
            )
            connection.execute(
                sa.text("DELETE FROM sites WHERE id = :site_id"),
                {"site_id": site_id},
            )

        for user_id in context.created_user_ids:
            connection.execute(
                sa.text("DELETE FROM audit_events WHERE actor_user_id = :user_id"),
                {"user_id": user_id},
            )
        for user_id in context.created_user_ids:
            connection.execute(
                sa.text("DELETE FROM auth_sessions WHERE user_id = :user_id"),
                {"user_id": user_id},
            )
            connection.execute(
                sa.text("DELETE FROM user_roles WHERE user_id = :user_id"),
                {"user_id": user_id},
            )
        for user_id in reversed(context.created_user_ids):
            connection.execute(
                sa.text("DELETE FROM users WHERE id = :user_id"),
                {"user_id": user_id},
            )


@pytest.fixture()
def admin_runtime_engine(mysql_engine: Engine) -> Iterator[Engine]:
    runtime_url = os.environ.get("APP_TEST_RUNTIME_DATABASE_URL")
    if not runtime_url:
        pytest.fail("Admin API tests require the least-privilege runtime database URL")
    engine = create_database_engine(DatabaseSettings.from_url(runtime_url))
    assert engine.url.database == mysql_engine.url.database
    assert engine.url.username != mysql_engine.url.username
    try:
        yield engine
    finally:
        engine.dispose()


@contextmanager
def _admin_api_context(
    alembic_config: Config,
    mysql_engine: Engine,
    api_engine: Engine,
) -> Iterator[AdminApiContext]:
    command.upgrade(alembic_config, "head")
    password = "correct horse battery staple"
    admin_user_id, admin_username = _create_user(
        mysql_engine,
        role="admin",
        password=password,
    )
    settings = Settings(
        environment="test",
        log_level="WARNING",
        session_secret="test-session-secret-long-enough-for-admin-management",
        session_ttl=timedelta(hours=1),
    )
    application = create_app(
        settings=settings,
        session_factory=create_session_factory(api_engine),
    )
    with TestClient(application) as client:
        context = AdminApiContext(
            client=client,
            engine=mysql_engine,
            api_engine=api_engine,
            admin_user_id=admin_user_id,
            admin_username=admin_username,
            csrf_token=_login(
                client,
                username=admin_username,
                password=password,
            ),
            created_user_ids=[admin_user_id],
        )
        try:
            yield context
        finally:
            _cleanup(context)


@pytest.fixture()
def admin_api(
    alembic_config: Config,
    mysql_engine: Engine,
) -> Iterator[AdminApiContext]:
    # Preserve the existing fixture for unrelated legacy management tests.
    with _admin_api_context(alembic_config, mysql_engine, mysql_engine) as context:
        yield context


@pytest.fixture()
def runtime_admin_api(
    alembic_config: Config,
    mysql_engine: Engine,
    admin_runtime_engine: Engine,
) -> Iterator[AdminApiContext]:
    with _admin_api_context(
        alembic_config, mysql_engine, admin_runtime_engine
    ) as context:
        yield context


def _create_site(context: AdminApiContext) -> int:
    with context.engine.begin() as connection:
        result = connection.execute(
            sa.text(
                """
                INSERT INTO sites (code, display_name, status, created_at)
                VALUES (:code, 'Management API Test', 'active', UTC_TIMESTAMP(6))
                """
            ),
            {"code": f"admin-api-{uuid4().hex}"},
        )
        assert result.lastrowid is not None
        site_id = int(result.lastrowid)
    context.created_site_ids.append(site_id)
    return site_id


def _create_managed_user(
    context: AdminApiContext,
    *,
    username: str,
    roles: list[str],
    operation_token: UUID | None = None,
) -> dict[str, Any]:
    response = context.client.post(
        "/api/admin/users",
        json={
            "username": username,
            "display_name": "Managed User",
            "email": f"{username}@example.test",
            "password": "managed user password",
            "roles": roles,
        },
        headers=_write_headers(context, operation_token=operation_token),
    )
    assert response.status_code == 201, response.text
    payload: dict[str, Any] = response.json()
    context.created_user_ids.append(int(payload["id"]))
    return payload


def _database_timestamp_wire(value: object) -> str:
    assert isinstance(value, datetime)
    aware = value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)
    return aware.isoformat().replace("+00:00", "Z")


def test_administrator_creates_and_lists_a_multi_role_user(
    runtime_admin_api: AdminApiContext,
) -> None:
    admin_api = runtime_admin_api
    raw_username = f"  MANAGED-{uuid4().hex}  "
    expected_username = raw_username.strip().casefold()
    created = _create_managed_user(
        admin_api,
        username=raw_username,
        roles=["data_manager", "viewer"],
    )

    assert created["username"] == expected_username
    assert created["roles"] == ["data_manager", "viewer"]
    assert created["status"] == "active"
    listed = admin_api.client.get("/api/admin/users")
    assert listed.status_code == 200
    assert any(item["id"] == created["id"] for item in listed.json())

    with admin_api.engine.connect() as connection:
        password_hash = connection.scalar(
            sa.text("SELECT password_hash FROM users WHERE id = :user_id"),
            {"user_id": created["id"]},
        )
        audit_payload = connection.scalar(
            sa.text(
                """
                SELECT redacted_payload
                FROM audit_events
                WHERE event_type = 'admin.user_created'
                  AND object_id = :object_id
                """
            ),
            {"object_id": str(created["id"])},
        )
    assert isinstance(password_hash, str)
    assert password_hash != "managed user password"
    assert verify_password(password_hash, "managed user password")
    assert "managed user password" not in str(audit_payload)
    assert "password_hash" not in str(audit_payload)


def test_user_creation_rejects_duplicates_unknown_roles_and_missing_csrf(
    admin_api: AdminApiContext,
) -> None:
    username = f"managed-{uuid4().hex}"
    _create_managed_user(admin_api, username=username, roles=["viewer"])
    duplicate = admin_api.client.post(
        "/api/admin/users",
        json={
            "username": username.upper(),
            "display_name": "Duplicate User",
            "password": "managed user password",
            "roles": ["viewer"],
        },
        headers=_write_headers(admin_api),
    )
    invalid_role = admin_api.client.post(
        "/api/admin/users",
        json={
            "username": f"managed-{uuid4().hex}",
            "display_name": "Invalid Role",
            "password": "managed user password",
            "roles": ["not_a_role"],
        },
        headers=_write_headers(admin_api),
    )
    missing_csrf = admin_api.client.post(
        "/api/admin/users",
        json={
            "username": f"managed-{uuid4().hex}",
            "display_name": "No CSRF",
            "password": "managed user password",
            "roles": ["viewer"],
        },
        headers={"Idempotency-Key": str(uuid4())},
    )

    assert duplicate.status_code == 409
    assert duplicate.json()["error"]["code"] == "user_conflict"
    assert invalid_role.status_code == 422
    assert invalid_role.json()["error"]["code"] == "invalid_roles"
    assert missing_csrf.status_code == 403
    assert missing_csrf.json()["error"]["code"] == "csrf_invalid"


def test_user_and_site_creation_freeze_results_and_bind_idempotency_to_actor(
    admin_api: AdminApiContext,
) -> None:
    user_token = uuid4()
    username = f"idempotent-{uuid4().hex}"
    user_payload = {
        "username": username,
        "display_name": "Idempotent User",
        "email": f"{username}@example.test",
        "password": "idempotent managed password",
        "roles": ["viewer"],
    }
    first_user = admin_api.client.post(
        "/api/admin/users",
        json=user_payload,
        headers=_write_headers(admin_api, operation_token=user_token),
    )
    replayed_user = admin_api.client.post(
        "/api/admin/users",
        json={
            **user_payload,
            "username": f"  {username.upper()}  ",
            "email": f"  {str(user_payload['email']).upper()}  ",
        },
        headers=_write_headers(admin_api, operation_token=user_token),
    )
    changed_user = admin_api.client.post(
        "/api/admin/users",
        json={**user_payload, "display_name": "Changed command"},
        headers=_write_headers(admin_api, operation_token=user_token),
    )
    changed_user_secret = admin_api.client.post(
        "/api/admin/users",
        json={**user_payload, "password": "different idempotent password"},
        headers=_write_headers(admin_api, operation_token=user_token),
    )

    assert first_user.status_code == replayed_user.status_code == 201
    assert replayed_user.json() == first_user.json()
    assert changed_user.status_code == 409
    assert changed_user.json()["error"]["code"] == "idempotency_conflict"
    assert changed_user_secret.status_code == 201
    assert changed_user_secret.json() == first_user.json()
    created_user_id = int(first_user.json()["id"])
    admin_api.created_user_ids.append(created_user_id)

    site_id = _create_site(admin_api)
    site_token = uuid4()
    site_payload = {
        "site_id": site_id,
        "source_timezone": "America/Los_Angeles",
        "reporting_timezone": "UTC",
        "currency_code": "USD",
        "effective_at": "2026-08-10T00:00:00Z",
        "change_reason": "Idempotent site configuration",
    }
    first_site = admin_api.client.post(
        "/api/admin/site-config-versions",
        json=site_payload,
        headers=_write_headers(admin_api, operation_token=site_token),
    )
    replayed_site = admin_api.client.post(
        "/api/admin/site-config-versions",
        json={
            **site_payload,
            "currency_code": "usd",
            "effective_at": "2026-08-10T08:00:00+08:00",
            "change_reason": "  Idempotent site configuration  ",
        },
        headers=_write_headers(admin_api, operation_token=site_token),
    )
    changed_site = admin_api.client.post(
        "/api/admin/site-config-versions",
        json={**site_payload, "change_reason": "Changed command"},
        headers=_write_headers(admin_api, operation_token=site_token),
    )

    assert first_site.status_code == replayed_site.status_code == 201
    assert replayed_site.json() == first_site.json()
    assert changed_site.status_code == 409
    assert changed_site.json()["error"]["code"] == "idempotency_conflict"

    with admin_api.engine.connect() as connection:
        assert (
            connection.scalar(
                sa.text(
                    "SELECT COUNT(*) FROM users WHERE username_normalized = :username"
                ),
                {"username": username},
            )
            == 1
        )
        assert (
            connection.scalar(
                sa.text(
                    "SELECT COUNT(*) FROM site_config_versions WHERE site_id = :site_id"
                ),
                {"site_id": site_id},
            )
            == 1
        )
        assert (
            connection.scalar(
                sa.text(
                    "SELECT COUNT(*) FROM audit_events "
                    "WHERE event_type = 'admin.user_created' "
                    "AND object_id = :object_id"
                ),
                {"object_id": str(created_user_id)},
            )
            == 1
        )
        assert (
            connection.scalar(
                sa.text(
                    "SELECT COUNT(*) FROM admin_operation_results "
                    "WHERE operation_token IN (:user_token, :site_token)"
                ),
                {"user_token": user_token.bytes, "site_token": site_token.bytes},
            )
            == 2
        )
        stored_secret_marker = connection.scalar(
            sa.text(
                "SELECT secret_verifier FROM admin_operation_tokens "
                "WHERE operation_token = :operation_token"
            ),
            {"operation_token": user_token.bytes},
        )
        stored_password_hash = connection.scalar(
            sa.text("SELECT password_hash FROM users WHERE id = :user_id"),
            {"user_id": created_user_id},
        )
    assert stored_secret_marker == "$secret-not-stored$v1$"
    assert isinstance(stored_password_hash, str)
    assert verify_password(stored_password_hash, str(user_payload["password"]))
    assert not verify_password(stored_password_hash, "different idempotent password")

    second_admin_id, second_admin_username = _create_user(
        admin_api.engine,
        role="admin",
        password="second administrator password",
    )
    admin_api.created_user_ids.append(second_admin_id)
    second_admin_csrf = _login(
        admin_api.client,
        username=second_admin_username,
        password="second administrator password",
    )
    changed_actor = admin_api.client.post(
        "/api/admin/users",
        json=user_payload,
        headers={
            CSRF_HEADER_NAME: second_admin_csrf,
            "Idempotency-Key": str(user_token),
        },
    )
    assert changed_actor.status_code == 409
    assert changed_actor.json()["error"]["code"] == "idempotency_conflict"


def test_administrator_updates_user_atomically_with_concurrency_and_redaction(
    runtime_admin_api: AdminApiContext,
) -> None:
    admin_api = runtime_admin_api
    username = f"patch-{uuid4().hex}"
    created = _create_managed_user(
        admin_api,
        username=username,
        roles=["viewer"],
    )
    operation_token = uuid4()
    new_password = "corrected managed password"
    patched_email = f"PATCHED-{uuid4().hex}@Example.Test"
    patch_payload = {
        "expected_updated_at": created["updated_at"],
        "display_name": "  Corrected Managed User  ",
        "email": f"  {patched_email}  ",
        "status": "active",
        "roles": ["viewer", "data_manager"],
        "new_password": new_password,
    }
    first = admin_api.client.patch(
        f"/api/admin/users/{created['id']}",
        json=patch_payload,
        headers=_write_headers(admin_api, operation_token=operation_token),
    )
    replayed = admin_api.client.patch(
        f"/api/admin/users/{created['id']}",
        json=patch_payload,
        headers=_write_headers(admin_api, operation_token=operation_token),
    )
    changed_secret = admin_api.client.patch(
        f"/api/admin/users/{created['id']}",
        json={**patch_payload, "new_password": "different managed password"},
        headers=_write_headers(admin_api, operation_token=operation_token),
    )

    assert first.status_code == replayed.status_code == 200
    assert replayed.json() == first.json()
    updated = first.json()
    assert updated["display_name"] == "Corrected Managed User"
    assert updated["email"] == patched_email.casefold()
    assert updated["roles"] == ["data_manager", "viewer"]
    assert updated["updated_at"].endswith("Z")
    assert updated["updated_at"] != created["updated_at"]
    assert changed_secret.status_code == 200
    assert changed_secret.json() == first.json()
    refreshed = admin_api.client.get("/api/admin/users")
    assert refreshed.status_code == 200
    refreshed_user = next(
        item for item in refreshed.json() if item["id"] == created["id"]
    )
    assert refreshed_user == updated

    stale = admin_api.client.patch(
        f"/api/admin/users/{created['id']}",
        json={
            "expected_updated_at": created["updated_at"],
            "display_name": "Stale update",
        },
        headers=_write_headers(admin_api),
    )
    empty_change = admin_api.client.patch(
        f"/api/admin/users/{created['id']}",
        json={"expected_updated_at": updated["updated_at"]},
        headers=_write_headers(admin_api),
    )
    unknown_role = admin_api.client.patch(
        f"/api/admin/users/{created['id']}",
        json={
            "expected_updated_at": updated["updated_at"],
            "roles": ["not_a_role"],
        },
        headers=_write_headers(admin_api),
    )
    assert stale.status_code == 409
    assert stale.json()["error"]["code"] == "user_version_conflict"
    assert empty_change.status_code == 422
    assert empty_change.json()["error"]["code"] == "validation_error"
    assert unknown_role.status_code == 422
    assert unknown_role.json()["error"]["code"] == "invalid_roles"

    conflicting_user = _create_managed_user(
        admin_api,
        username=f"patch-conflict-{uuid4().hex}",
        roles=["viewer"],
    )
    duplicate_email = admin_api.client.patch(
        f"/api/admin/users/{conflicting_user['id']}",
        json={
            "expected_updated_at": conflicting_user["updated_at"],
            "email": updated["email"],
        },
        headers=_write_headers(admin_api),
    )
    assert duplicate_email.status_code == 409
    assert duplicate_email.json()["error"]["code"] == "user_conflict"

    with admin_api.engine.connect() as connection:
        password_hash = connection.scalar(
            sa.text("SELECT password_hash FROM users WHERE id = :user_id"),
            {"user_id": created["id"]},
        )
        operation = (
            connection.execute(
                sa.text(
                    """
                    SELECT tokens.secret_verifier, results.response_payload
                    FROM admin_operation_tokens AS tokens
                    INNER JOIN admin_operation_results AS results
                        ON results.operation_token = tokens.operation_token
                    WHERE tokens.operation_token = :operation_token
                    """
                ),
                {"operation_token": operation_token.bytes},
            )
            .mappings()
            .one()
        )
        audit_payload = connection.scalar(
            sa.text(
                """
                SELECT redacted_payload
                FROM audit_events
                WHERE event_type = 'admin.user_updated'
                  AND object_id = :object_id
                """
            ),
            {"object_id": str(created["id"])},
        )
        audit_count = connection.scalar(
            sa.text(
                """
                SELECT COUNT(*)
                FROM audit_events
                WHERE event_type = 'admin.user_updated'
                  AND object_id = :object_id
                """
            ),
            {"object_id": str(created["id"])},
        )
    assert isinstance(password_hash, str)
    assert verify_password(password_hash, new_password)
    assert operation["secret_verifier"] == "$secret-not-stored$v1$"
    assert password_hash != operation["secret_verifier"]
    assert not verify_password(str(operation["secret_verifier"]), new_password)
    frozen_payload = str(operation["response_payload"])
    assert new_password not in frozen_payload
    assert password_hash not in frozen_payload
    audit_text = str(audit_payload)
    assert new_password not in audit_text
    assert password_hash not in audit_text
    assert updated["email"] not in audit_text
    assert audit_count == 1


def test_admin_operation_secret_marker_does_not_control_replay(
    runtime_admin_api: AdminApiContext,
) -> None:
    admin_api = runtime_admin_api
    operation_token = uuid4()
    username = f"legacy-replay-{uuid4().hex}"
    payload = {
        "username": username,
        "display_name": "Legacy Replay User",
        "email": None,
        "password": "legacy replay password",
        "roles": ["viewer"],
        "status": "active",
    }
    operation_digest = _command_digest(
        "create_user",
        {
            "username": username,
            "display_name": payload["display_name"],
            "email": None,
            "roles": ["viewer"],
            "status": "active",
            "password_present": True,
        },
    )
    frozen_payload = {
        "id": 999_999,
        "username": username,
        "display_name": payload["display_name"],
        "email": None,
        "status": "active",
        "roles": ["viewer"],
        "last_login_at": None,
        "created_at": "2026-08-10T00:00:00Z",
        "updated_at": "2026-08-10T00:00:00Z",
    }
    with admin_api.engine.begin() as connection:
        connection.execute(
            sa.text(
                """
                INSERT INTO admin_operation_tokens (
                    operation_token, operation_kind, operation_digest,
                    actor_user_id, secret_verifier, registered_at
                ) VALUES (
                    :operation_token, 'create_user', :operation_digest,
                    :actor_user_id, '$secret-not-stored$v1$', UTC_TIMESTAMP(6)
                )
                """
            ),
            {
                "operation_token": operation_token.bytes,
                "operation_digest": operation_digest,
                "actor_user_id": admin_api.admin_user_id,
            },
        )
        connection.execute(
            sa.text(
                """
                INSERT INTO admin_operation_results (
                    operation_token, operation_kind, operation_digest,
                    actor_user_id, response_schema_version,
                    response_status_code, response_payload, completed_at
                ) VALUES (
                    :operation_token, 'create_user', :operation_digest,
                    :actor_user_id, 1, 201, :response_payload, UTC_TIMESTAMP(6)
                )
                """
            ),
            {
                "operation_token": operation_token.bytes,
                "operation_digest": operation_digest,
                "actor_user_id": admin_api.admin_user_id,
                "response_payload": json.dumps(frozen_payload),
            },
        )

    replays = [
        admin_api.client.post(
            "/api/admin/users",
            json=payload,
            headers=_write_headers(admin_api, operation_token=operation_token),
        )
        for _ in range(2)
    ]
    assert [response.status_code for response in replays] == [201, 201]
    assert [response.json() for response in replays] == [frozen_payload, frozen_payload]


def test_concurrent_user_creation_replays_immutable_operation_result(
    runtime_admin_api: AdminApiContext,
) -> None:
    admin_api = runtime_admin_api
    token = uuid4()
    payload = {
        "username": f"concurrent-create-{uuid4().hex}",
        "display_name": "Concurrent User",
        "password": "managed user password",
        "roles": ["viewer"],
    }
    first_inserted, second_attempted, release_first = Event(), Event(), Event()
    counter_lock = Lock()
    attempts = 0

    def before_insert(
        connection: Any,
        cursor: Any,
        statement: str,
        parameters: Any,
        context: Any,
        executemany: bool,
    ) -> None:
        nonlocal attempts
        if "INSERT IGNORE INTO admin_operation_tokens" not in statement:
            return
        with counter_lock:
            attempts += 1
            connection.info["token_test_order"] = attempts
            if attempts == 2:
                second_attempted.set()

    def after_insert(
        connection: Any,
        cursor: Any,
        statement: str,
        parameters: Any,
        context: Any,
        executemany: bool,
    ) -> None:
        if "INSERT IGNORE INTO admin_operation_tokens" not in statement:
            return
        if connection.info.pop("token_test_order") == 1:
            first_inserted.set()
            assert release_first.wait(15), "first creation was not released"

    with TestClient(admin_api.client.app) as other_client:
        other_csrf = _login(
            other_client,
            username=admin_api.admin_username,
            password="correct horse battery staple",
        )
        sa.event.listen(admin_api.api_engine, "before_cursor_execute", before_insert)
        sa.event.listen(admin_api.api_engine, "after_cursor_execute", after_insert)
        try:
            with ThreadPoolExecutor(max_workers=2) as executor:
                first = executor.submit(
                    admin_api.client.post,
                    "/api/admin/users",
                    json=payload,
                    headers=_write_headers(admin_api, operation_token=token),
                )
                try:
                    assert first_inserted.wait(10), "first token was not inserted"
                    other = executor.submit(
                        other_client.post,
                        "/api/admin/users",
                        json=payload,
                        headers={
                            CSRF_HEADER_NAME: other_csrf,
                            "Idempotency-Key": str(token),
                        },
                    )
                    assert second_attempted.wait(10), "second insert was not attempted"
                    assert not other.done()
                finally:
                    release_first.set()
                first_response = first.result(timeout=15)
                other_response = other.result(timeout=15)
        finally:
            sa.event.remove(
                admin_api.api_engine, "before_cursor_execute", before_insert
            )
            sa.event.remove(admin_api.api_engine, "after_cursor_execute", after_insert)
            with admin_api.engine.connect() as connection:
                user_id = connection.scalar(
                    sa.text(
                        "SELECT id FROM users WHERE username_normalized = :username"
                    ),
                    {"username": payload["username"]},
                )
            if user_id is not None:
                admin_api.created_user_ids.append(int(user_id))

    assert first_response.status_code == other_response.status_code == 201
    assert first_response.json() == other_response.json()
    with admin_api.engine.connect() as connection:
        assert (
            connection.scalar(
                sa.text(
                    "SELECT COUNT(*) FROM audit_events "
                    "WHERE event_type = 'admin.user_created' "
                    "AND object_id = :id"
                ),
                {"id": str(first_response.json()["id"])},
            )
            == 1
        )


def test_runtime_cannot_lock_or_mutate_role_seed_data(
    runtime_admin_api: AdminApiContext,
) -> None:
    admin_api = runtime_admin_api
    with admin_api.api_engine.connect() as connection:
        assert connection.scalar(sa.text("SELECT code FROM roles WHERE code = 'admin'"))
        for statement in (
            "SELECT id FROM roles WHERE code = 'admin' FOR UPDATE",
            "UPDATE roles SET code = code WHERE code = 'admin'",
        ):
            with pytest.raises(sa.exc.OperationalError) as denied:
                connection.execute(sa.text(statement))
            assert denied.value.orig is not None
            assert denied.value.orig.args[0] == 1142
            connection.rollback()


@pytest.mark.parametrize("change", [{"roles": ["viewer"]}, {"status": "disabled"}])
def test_concurrent_administrators_cannot_remove_the_last_active_administrator(
    runtime_admin_api: AdminApiContext,
    change: dict[str, object],
) -> None:
    admin_api = runtime_admin_api
    second = _create_managed_user(
        admin_api, username=f"second-admin-{uuid4().hex}", roles=["admin"]
    )
    with TestClient(admin_api.client.app) as second_client:
        second_csrf = _login(
            second_client,
            username=second["username"],
            password="managed user password",
        )
        with admin_api.engine.connect() as connection:
            active_ids = tuple(
                connection.scalars(
                    sa.text(
                        "SELECT users.id FROM users JOIN user_roles "
                        "ON user_roles.user_id = users.id "
                        "JOIN roles ON roles.id = user_roles.role_id "
                        "WHERE roles.code = 'admin' AND users.status = 'active' "
                        "ORDER BY users.id"
                    )
                )
            )
            assert active_ids == (admin_api.admin_user_id, second["id"])
            first_timestamp = _database_timestamp_wire(
                connection.scalar(
                    sa.text("SELECT updated_at FROM users WHERE id = :id"),
                    {"id": admin_api.admin_user_id},
                )
            )
            second_timestamp = _database_timestamp_wire(
                connection.scalar(
                    sa.text("SELECT updated_at FROM users WHERE id = :id"),
                    {"id": second["id"]},
                )
            )

        first_locked, second_attempted, second_locked, release_first = (
            Event(),
            Event(),
            Event(),
            Event(),
        )
        counter_lock = Lock()
        lock_attempts = 0
        connection_ids: set[int] = set()

        def before_lock(
            connection: Any,
            cursor: Any,
            statement: str,
            parameters: Any,
            context: Any,
            executemany: bool,
        ) -> None:
            nonlocal lock_attempts
            if (
                "WHERE assignments.role_id" not in statement
                or "FOR UPDATE" not in statement
            ):
                return
            with counter_lock:
                lock_attempts += 1
                connection.info["admin_lock_test_order"] = lock_attempts
                connection_ids.add(id(connection))
                if lock_attempts == 2:
                    second_attempted.set()

        def after_lock(
            connection: Any,
            cursor: Any,
            statement: str,
            parameters: Any,
            context: Any,
            executemany: bool,
        ) -> None:
            if (
                "WHERE assignments.role_id" not in statement
                or "FOR UPDATE" not in statement
            ):
                return
            order = connection.info.pop("admin_lock_test_order")
            if order == 1:
                first_locked.set()
                assert release_first.wait(15), (
                    "first administrator transaction was not released"
                )
            else:
                second_locked.set()

        sa.event.listen(admin_api.api_engine, "before_cursor_execute", before_lock)
        sa.event.listen(admin_api.api_engine, "after_cursor_execute", after_lock)
        try:
            with ThreadPoolExecutor(max_workers=2) as executor:
                first = executor.submit(
                    admin_api.client.patch,
                    f"/api/admin/users/{admin_api.admin_user_id}",
                    json={"expected_updated_at": first_timestamp, **change},
                    headers=_write_headers(admin_api),
                )
                try:
                    assert first_locked.wait(10), (
                        "first request did not acquire administrator locks"
                    )
                    other = executor.submit(
                        second_client.patch,
                        f"/api/admin/users/{second['id']}",
                        json={"expected_updated_at": second_timestamp, **change},
                        headers={
                            CSRF_HEADER_NAME: second_csrf,
                            "Idempotency-Key": str(uuid4()),
                        },
                    )
                    assert second_attempted.wait(10), (
                        "second request did not reach the locking read"
                    )
                    assert not second_locked.is_set()
                finally:
                    release_first.set()
                first_response = first.result(timeout=15)
                other_response = other.result(timeout=15)
        finally:
            sa.event.remove(admin_api.api_engine, "before_cursor_execute", before_lock)
            sa.event.remove(admin_api.api_engine, "after_cursor_execute", after_lock)

    assert len(connection_ids) == 2
    assert second_locked.is_set()
    assert first_response.status_code == 200
    assert other_response.status_code == 409
    assert other_response.json()["error"]["code"] == "last_active_admin"
    with admin_api.engine.connect() as connection:
        assert tuple(
            connection.scalars(
                sa.text(
                    "SELECT users.id FROM users JOIN user_roles "
                    "ON user_roles.user_id = users.id "
                    "JOIN roles ON roles.id = user_roles.role_id "
                    "WHERE roles.code = 'admin' AND users.status = 'active' "
                    "ORDER BY users.id"
                )
            )
        ) == (second["id"],)
        assert (
            connection.scalar(
                sa.text(
                    "SELECT COUNT(*) FROM audit_events "
                    "WHERE event_type = 'admin.user_updated' "
                    "AND actor_user_id IN (:first, :second)"
                ),
                {"first": admin_api.admin_user_id, "second": second["id"]},
            )
            == 1
        )


def test_final_active_administrator_cannot_be_disabled_or_demoted(
    runtime_admin_api: AdminApiContext,
) -> None:
    admin_api = runtime_admin_api
    with admin_api.engine.connect() as connection:
        active_admin_ids = tuple(
            int(value)
            for value in connection.scalars(
                sa.text(
                    """
                    SELECT users.id
                    FROM users
                    INNER JOIN user_roles AS assignments
                        ON assignments.user_id = users.id
                    INNER JOIN roles ON roles.id = assignments.role_id
                    WHERE users.status = 'active' AND roles.code = 'admin'
                    ORDER BY users.id
                    """
                )
            )
        )
        updated_at = _database_timestamp_wire(
            connection.scalar(
                sa.text("SELECT updated_at FROM users WHERE id = :user_id"),
                {"user_id": admin_api.admin_user_id},
            )
        )
    if active_admin_ids != (admin_api.admin_user_id,):
        pytest.skip("last-administrator test requires an isolated test user set")

    disabled = admin_api.client.patch(
        f"/api/admin/users/{admin_api.admin_user_id}",
        json={"expected_updated_at": updated_at, "status": "disabled"},
        headers=_write_headers(admin_api),
    )
    demoted = admin_api.client.patch(
        f"/api/admin/users/{admin_api.admin_user_id}",
        json={"expected_updated_at": updated_at, "roles": ["viewer"]},
        headers=_write_headers(admin_api),
    )

    assert disabled.status_code == demoted.status_code == 409
    assert disabled.json()["error"]["code"] == "last_active_admin"
    assert demoted.json()["error"]["code"] == "last_active_admin"
    with admin_api.engine.connect() as connection:
        assert (
            connection.scalar(
                sa.text("SELECT status FROM users WHERE id = :user_id"),
                {"user_id": admin_api.admin_user_id},
            )
            == "active"
        )
        assert (
            connection.scalar(
                sa.text(
                    """
                    SELECT COUNT(*)
                    FROM user_roles AS assignments
                    INNER JOIN roles ON roles.id = assignments.role_id
                    WHERE assignments.user_id = :user_id
                      AND roles.code = 'admin'
                    """
                ),
                {"user_id": admin_api.admin_user_id},
            )
            == 1
        )


@pytest.mark.parametrize("role", ["data_manager", "viewer"])
def test_non_administrator_cannot_access_management_endpoints(
    runtime_admin_api: AdminApiContext,
    role: str,
) -> None:
    admin_api = runtime_admin_api
    user_id, username = _create_user(
        admin_api.engine,
        role=role,
        password="correct horse battery staple",
    )
    admin_api.created_user_ids.append(user_id)
    csrf_token = _login(
        admin_api.client,
        username=username,
        password="correct horse battery staple",
    )
    with admin_api.engine.connect() as connection:
        expected_updated_at = _database_timestamp_wire(
            connection.scalar(
                sa.text("SELECT updated_at FROM users WHERE id = :user_id"),
                {"user_id": user_id},
            )
        )

    responses = [
        admin_api.client.get("/api/admin/users"),
        admin_api.client.get("/api/admin/site-config-versions"),
        admin_api.client.get("/api/admin/audit-events"),
        admin_api.client.get("/api/admin/maintenance"),
        admin_api.client.post(
            "/api/admin/users",
            json={
                "username": f"forbidden-{uuid4().hex}",
                "display_name": "Forbidden",
                "password": "managed user password",
                "roles": ["viewer"],
            },
            headers={
                CSRF_HEADER_NAME: csrf_token,
                "Idempotency-Key": str(uuid4()),
            },
        ),
        admin_api.client.patch(
            f"/api/admin/users/{user_id}",
            json={
                "expected_updated_at": expected_updated_at,
                "display_name": "Forbidden update",
            },
            headers={
                CSRF_HEADER_NAME: csrf_token,
                "Idempotency-Key": str(uuid4()),
            },
        ),
    ]

    assert all(response.status_code == 403 for response in responses)
    assert all(
        response.json()["error"]["code"] == "role_forbidden" for response in responses
    )


def test_administrator_reads_backup_restore_lock_and_worker_status(
    admin_api: AdminApiContext,
) -> None:
    response = admin_api.client.get("/api/admin/maintenance")

    assert response.status_code == 200, response.text
    payload = response.json()
    assert list(payload) == [
        "backups",
        "restores",
        "outbox",
        "write_lock",
        "observed_at",
        "maintenance_active",
        "worker",
        "queues",
    ]
    assert set(payload["outbox"]) == {
        "pending",
        "processing",
        "completed",
        "failed",
        "oldest_pending_at",
    }
    assert all(
        value >= 0
        for key, value in payload["outbox"].items()
        if key != "oldest_pending_at"
    )
    assert payload["write_lock"]["held"] is False
    assert payload["write_lock"]["owner_connection_id"] is None
    assert payload["write_lock"]["warning"] is False
    assert payload["maintenance_active"] is False
    assert [queue["queue_name"] for queue in payload["queues"]] == [
        "return_dedup",
        "publication_outbox",
        "catalog_export",
        "catalog_import",
    ]
    assert response.headers["cache-control"] == "private, no-store"


def test_administrator_read_remains_available_during_backup_barrier(
    admin_api: AdminApiContext,
) -> None:
    with hold_maintenance_write_barrier(admin_api.engine, timeout_seconds=0):
        response = admin_api.client.get("/api/admin/maintenance")

    assert response.status_code == 200, response.text
    assert response.json()["write_lock"]["held"] is True
    assert response.json()["write_lock"]["owner_connection_id"] is not None
    assert response.json()["maintenance_active"] is True


def test_site_configuration_is_append_only_and_switches_current_pointer(
    admin_api: AdminApiContext,
) -> None:
    site_id = _create_site(admin_api)
    first = admin_api.client.post(
        "/api/admin/site-config-versions",
        json={
            "site_id": site_id,
            "source_timezone": "America/Los_Angeles",
            "reporting_timezone": "America/New_York",
            "currency_code": "usd",
            "effective_at": "2026-08-10T00:00:00+08:00",
            "change_reason": "Initial test configuration",
        },
        headers=_write_headers(admin_api),
    )
    second = admin_api.client.post(
        "/api/admin/site-config-versions",
        json={
            "site_id": site_id,
            "source_timezone": "America/Los_Angeles",
            "reporting_timezone": "UTC",
            "currency_code": "USD",
            "effective_at": "2026-09-01T00:00:00Z",
            "change_reason": "Switch reporting timezone",
        },
        headers=_write_headers(admin_api),
    )

    assert first.status_code == second.status_code == 201
    assert first.json()["version_number"] == 1
    assert second.json()["version_number"] == 2
    assert first.json()["currency_code"] == "USD"
    assert second.json()["is_current"] is True

    listed = admin_api.client.get(
        "/api/admin/site-config-versions",
        params={"site_id": site_id},
    )
    assert listed.status_code == 200
    assert [item["version_number"] for item in listed.json()] == [2, 1]
    assert [item["is_current"] for item in listed.json()] == [True, False]
    with admin_api.engine.connect() as connection:
        audit_count = connection.scalar(
            sa.text(
                """
                SELECT COUNT(*)
                FROM audit_events
                WHERE site_id = :site_id
                  AND event_type = 'admin.site_config_created'
                """
            ),
            {"site_id": site_id},
        )
    assert audit_count == 2


def test_site_configuration_rejects_invalid_timezone_and_unknown_site(
    admin_api: AdminApiContext,
) -> None:
    invalid_timezone = admin_api.client.post(
        "/api/admin/site-config-versions",
        json={
            "site_id": 1,
            "source_timezone": "Not/A_Timezone",
            "reporting_timezone": "UTC",
            "currency_code": "USD",
            "effective_at": "2026-08-10T00:00:00Z",
            "change_reason": "Invalid timezone test",
        },
        headers=_write_headers(admin_api),
    )
    unknown_site = admin_api.client.post(
        "/api/admin/site-config-versions",
        json={
            "site_id": 9223372036854775807,
            "source_timezone": "UTC",
            "reporting_timezone": "UTC",
            "currency_code": "USD",
            "effective_at": "2026-08-10T00:00:00Z",
            "change_reason": "Unknown site test",
        },
        headers=_write_headers(admin_api),
    )

    assert invalid_timezone.status_code == 422
    assert invalid_timezone.json()["error"]["code"] == "validation_error"
    assert unknown_site.status_code == 404
    assert unknown_site.json()["error"]["code"] == "site_not_found"


def test_administrator_reads_filtered_paginated_redacted_audit_events(
    admin_api: AdminApiContext,
) -> None:
    first = _create_managed_user(
        admin_api,
        username=f"audit-{uuid4().hex}",
        roles=["viewer"],
    )
    second = _create_managed_user(
        admin_api,
        username=f"audit-{uuid4().hex}",
        roles=["data_manager"],
    )

    first_page = admin_api.client.get(
        "/api/admin/audit-events",
        params={
            "event_type": "admin.user_created",
            "actor_user_id": admin_api.admin_user_id,
            "limit": 1,
            "offset": 0,
        },
    )
    second_page = admin_api.client.get(
        "/api/admin/audit-events",
        params={
            "event_type": "admin.user_created",
            "actor_user_id": admin_api.admin_user_id,
            "limit": 1,
            "offset": 1,
        },
    )

    assert first_page.status_code == second_page.status_code == 200
    assert first_page.json()["total"] == 2
    assert first_page.json()["next_offset"] == 1
    assert second_page.json()["next_offset"] is None
    returned_ids = {
        int(first_page.json()["items"][0]["object_id"]),
        int(second_page.json()["items"][0]["object_id"]),
    }
    assert returned_ids == {int(first["id"]), int(second["id"])}
    for page in (first_page.json(), second_page.json()):
        payload_text = str(page["items"][0]["redacted_payload"])
        assert "password" not in payload_text
        assert "@example.test" not in payload_text
