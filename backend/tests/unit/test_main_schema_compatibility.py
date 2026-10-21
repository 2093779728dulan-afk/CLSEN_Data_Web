from __future__ import annotations

from typing import cast

import pytest
import sqlalchemy as sa
from app.config import Settings
from app.db.session import SessionFactory
from app.main import create_app, create_runtime_app
from app.maintenance.schema_compatibility import (
    SchemaCompatibilityCode,
    SchemaCompatibilityFailure,
)
from fastapi import FastAPI
from fastapi.testclient import TestClient


def _settings() -> Settings:
    return Settings(
        environment="server",
        log_level="CRITICAL",
        cors_allowed_origins=("https://review.example.test",),
        session_secret="runtime-schema-test-secret-0000000",
        session_cookie_secure=True,
    )


def _state_value(application: FastAPI, name: str) -> object:
    return cast(object, getattr(application.state, name))


def test_runtime_lifespan_guards_and_shares_one_engine(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    engine = sa.create_engine("sqlite+pysqlite:///:memory:")
    disposed = 0
    identities: list[str] = []
    original_dispose = engine.dispose

    def dispose() -> None:
        nonlocal disposed
        disposed += 1
        original_dispose()

    monkeypatch.setenv(
        "APP_DATABASE_URL",
        "mysql+pymysql://app:runtime-secret@mysql:3306/clsen_data?charset=utf8mb4",
    )
    monkeypatch.setattr("app.main.create_database_engine", lambda _settings: engine)
    monkeypatch.setattr(engine, "dispose", dispose)
    monkeypatch.setattr(
        "app.main.assert_schema_compatible",
        lambda candidate, *, database_identity: (
            identities.append(database_identity)
            if candidate is engine
            else pytest.fail("lifespan guarded a different engine")
        ),
    )
    application = create_runtime_app(_settings())

    with TestClient(application) as client:
        assert application.state.database_engine is engine
        factory = application.state.session_factory
        assert factory.kw["bind"] is engine
        response = client.get("/api/health/ready")
        assert response.status_code == 200
        assert response.json() == {"status": "ok"}
        assert disposed == 0

    assert identities == [
        "mysql+pymysql://app:***@mysql:3306/clsen_data?charset=utf8mb4"
    ]
    assert disposed == 1
    assert _state_value(application, "database_engine") is None
    assert _state_value(application, "session_factory") is None


def test_runtime_schema_refusal_prevents_startup_and_disposes_engine(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    engine = sa.create_engine("sqlite+pysqlite:///:memory:")
    disposed = 0
    original_dispose = engine.dispose
    failure = SchemaCompatibilityFailure(
        code=SchemaCompatibilityCode.REVISION_OLDER,
        expected_revision="0022",
        actual_revision="0021",
        database_identity="mysql+pymysql://app:***@mysql/clsen_data",
    )

    def dispose() -> None:
        nonlocal disposed
        disposed += 1
        original_dispose()

    monkeypatch.setenv(
        "APP_DATABASE_URL",
        "mysql+pymysql://app:secret@mysql:3306/clsen_data?charset=utf8mb4",
    )
    monkeypatch.setattr("app.main.create_database_engine", lambda _settings: engine)
    monkeypatch.setattr(engine, "dispose", dispose)
    monkeypatch.setattr(
        "app.main.assert_schema_compatible",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(failure),
    )
    application = create_runtime_app(_settings())

    with (
        pytest.raises(SchemaCompatibilityFailure) as captured,
        TestClient(application),
    ):
        pytest.fail("a mismatched runtime application completed startup")

    assert captured.value is failure
    assert disposed == 1


def test_runtime_readiness_uses_guarded_engine_and_reports_later_outage(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    engine = sa.create_engine("sqlite+pysqlite:///:memory:")
    monkeypatch.setattr(engine.dialect, "name", "mysql")
    monkeypatch.setenv(
        "APP_DATABASE_URL",
        "mysql+pymysql://app:secret@mysql:3306/clsen_data?charset=utf8mb4",
    )
    monkeypatch.setattr("app.main.create_database_engine", lambda _settings: engine)
    monkeypatch.setattr(
        "app.main.assert_schema_compatible",
        lambda _engine, *, database_identity: None,
    )
    monkeypatch.setattr(
        "app.main.probe_maintenance_lock",
        lambda *_args: (_ for _ in ()).throw(
            sa.exc.OperationalError("SELECT", {}, RuntimeError("offline"))
        ),
    )

    with TestClient(create_runtime_app(_settings())) as client:
        response = client.get("/api/health/ready")

    assert response.status_code == 503
    assert response.json() == {
        "status": "unavailable",
        "reason": "database_unavailable",
    }


def test_offline_factory_does_not_discover_or_connect_to_a_database(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def unexpected(*_args: object, **_kwargs: object) -> None:
        pytest.fail("offline application factory touched database configuration")

    monkeypatch.setattr("app.main.DatabaseSettings.from_env", unexpected)
    monkeypatch.setattr("app.main.create_database_engine", unexpected)
    monkeypatch.setattr("app.main.assert_schema_compatible", unexpected)

    application = create_app(settings=_settings())
    schema = application.openapi()

    assert "/api/health/ready" in schema["paths"]
    assert application.state.database_engine is None
    assert application.state.session_factory is None


def test_injected_factory_remains_offline_and_engine_can_be_resolved_from_it(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    engine = sa.create_engine("sqlite+pysqlite:///:memory:")
    factory = SessionFactory(bind=engine)

    def unexpected(*_args: object, **_kwargs: object) -> None:
        pytest.fail("injected application attempted database discovery")

    monkeypatch.setattr("app.main.create_database_engine", unexpected)
    application = create_app(
        settings=_settings(),
        session_factory=factory,
    )

    with TestClient(application) as client:
        response = client.get("/api/health/ready")

    assert response.status_code == 200
    assert application.state.session_factory is factory
    engine.dispose()
