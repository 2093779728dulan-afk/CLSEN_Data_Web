from __future__ import annotations

import json
from datetime import timedelta
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from uuid import UUID

import pytest
from app.config import StorageSettings
from app.db.settings import DatabaseSettings
from app.maintenance.schema_compatibility import (
    SchemaCompatibilityCode,
    SchemaCompatibilityFailure,
)
from app.worker import cli


class _Engine:
    def __init__(self, events: list[str]) -> None:
        self._events = events
        self.dispose_count = 0

    def dispose(self) -> None:
        self._events.append("dispose")
        self.dispose_count += 1


def _install_successful_worker(
    monkeypatch: pytest.MonkeyPatch,
) -> tuple[list[str], _Engine]:
    events: list[str] = []
    engine = _Engine(events)
    database_settings = SimpleNamespace(
        safe_url="mysql+pymysql://worker:***@mysql/clsen_data"
    )
    storage_settings = SimpleNamespace(
        root=Path("C:/synthetic-worker-storage"),
        max_upload_bytes=1024,
        lease_ttl=timedelta(seconds=300),
    )

    def load_database_settings(name: str, **options: object) -> SimpleNamespace:
        events.append(f"database_settings:{name}:{options}")
        return database_settings

    def create_engine(settings: object) -> _Engine:
        events.append("engine")
        if settings is not database_settings:
            pytest.fail("wrong settings")
        return engine

    def load_storage_settings() -> SimpleNamespace:
        events.append("storage_settings")
        return storage_settings

    def create_content_store(*_args: object) -> object:
        events.append("content_store")
        return object()

    monkeypatch.setattr(
        cli,
        "load_dotenv",
        lambda *_args, **_kwargs: events.append("dotenv"),
    )
    monkeypatch.setattr(
        DatabaseSettings,
        "from_env",
        load_database_settings,
    )
    monkeypatch.setattr(
        cli,
        "create_database_engine",
        create_engine,
    )
    monkeypatch.setattr(
        cli,
        "assert_schema_compatible",
        lambda candidate, *, database_identity: events.append(
            f"guard:{candidate is engine}:{database_identity}"
        ),
    )
    monkeypatch.setattr(
        cli,
        "configure_logging",
        lambda _settings: events.append("logging"),
    )
    monkeypatch.setattr(
        cli,
        "Settings",
        lambda: SimpleNamespace(numeric_log_level=20),
    )
    monkeypatch.setattr(
        cli,
        "_build_id",
        lambda _root: "unit-build",
    )
    monkeypatch.setattr(
        cli,
        "uuid4",
        lambda: UUID("01234567-89ab-4def-8123-456789abcdef"),
    )

    class _HeartbeatRepository:
        def __init__(self, candidate: object) -> None:
            assert candidate is engine
            events.append("heartbeat_repository")

    class _HeartbeatController:
        def __init__(
            self,
            repository: object,
            *,
            instance_id: UUID,
            build_id: str,
        ) -> None:
            assert isinstance(repository, _HeartbeatRepository)
            assert instance_id == UUID("01234567-89ab-4def-8123-456789abcdef")
            assert build_id == "unit-build"
            events.append("heartbeat_controller")

        def start(self) -> None:
            events.append("heartbeat_start")

        def stop(self) -> None:
            events.append("heartbeat_stop")

    monkeypatch.setattr(cli, "WorkerHeartbeatRepository", _HeartbeatRepository)
    monkeypatch.setattr(cli, "WorkerHeartbeatController", _HeartbeatController)
    monkeypatch.setattr(
        StorageSettings,
        "from_env",
        load_storage_settings,
    )
    monkeypatch.setattr(
        cli,
        "LocalContentStore",
        create_content_store,
    )

    def constructor(name: str) -> Any:
        def build(*_args: object, **_kwargs: object) -> object:
            events.append(name)
            return object()

        return build

    outbox_constructor = constructor("OutboxSettings")
    for name in (
        "MySqlReturnDedupRepository",
        "ReturnDedupWorker",
        "PublicationOutboxWorker",
        "MySqlCatalogExportWorkSource",
        "MySqlCatalogExportFinalizer",
        "CatalogExportMaterializer",
        "CatalogExportWorker",
        "MySqlCatalogImportRepository",
        "CatalogImportWorker",
    ):
        monkeypatch.setattr(cli, name, constructor(name))
    monkeypatch.setattr(cli, "OutboxSettings", outbox_constructor)
    monkeypatch.setattr(
        outbox_constructor,
        "local_default",
        lambda: SimpleNamespace(worker_id="unit-worker"),
        raising=False,
    )

    class _Runner:
        def __init__(self, **workers: object) -> None:
            assert isinstance(workers["telemetry"], _HeartbeatController)
            events.append("runner")

        def run_once(self) -> SimpleNamespace:
            events.append("claim")
            return SimpleNamespace(did_work=False)

    monkeypatch.setattr(cli, "WorkerRunner", _Runner)
    return events, engine


def test_drain_worker_guards_before_storage_runner_and_claim(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    events, engine = _install_successful_worker(monkeypatch)

    exit_code = cli.main(
        [
            "--database-environment",
            "APP_TEST_RUNTIME_DATABASE_URL",
            "--poll-seconds",
            "0.2",
            "--max-attempts",
            "7",
            "--stale-seconds",
            "60",
            "--retry-seconds",
            "3",
            "--drain",
        ]
    )

    assert exit_code == 0
    assert events.index(
        "guard:True:mysql+pymysql://worker:***@mysql/clsen_data"
    ) < events.index("logging")
    assert events.index("logging") < events.index("heartbeat_start")
    assert events.index("heartbeat_start") < events.index("storage_settings")
    assert events.index("storage_settings") < events.index("runner")
    assert events.index("runner") < events.index("claim")
    assert events[-2:] == ["heartbeat_stop", "dispose"]
    assert engine.dispose_count == 1
    assert any(
        event.startswith("database_settings:APP_TEST_RUNTIME_DATABASE_URL:")
        for event in events
    )


def test_heartbeat_registration_failure_prevents_worker_construction(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    events, engine = _install_successful_worker(monkeypatch)

    class _FailingController:
        def __init__(self, *_args: object, **_kwargs: object) -> None:
            events.append("heartbeat_controller")

        def start(self) -> None:
            events.append("heartbeat_start")
            raise RuntimeError("registration unavailable")

        def stop(self) -> None:
            pytest.fail("an unstarted heartbeat was stopped")

    monkeypatch.setattr(cli, "WorkerHeartbeatController", _FailingController)

    assert cli.main(["--drain"]) == 3
    assert "storage_settings" not in events
    assert "runner" not in events
    assert "claim" not in events
    assert events[-1] == "dispose"
    assert engine.dispose_count == 1


def test_schema_refusal_disposes_engine_before_any_worker_construction(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    events: list[str] = []
    engine = _Engine(events)
    settings = SimpleNamespace(safe_url="mysql+pymysql://worker:***@mysql/clsen_data")
    failure = SchemaCompatibilityFailure(
        code=SchemaCompatibilityCode.REVISION_NEWER,
        expected_revision="0023",
        actual_revision="0024",
        database_identity=settings.safe_url,
    )
    monkeypatch.setattr(cli, "load_dotenv", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(
        DatabaseSettings,
        "from_env",
        lambda *_args, **_kwargs: settings,
    )
    monkeypatch.setattr(cli, "create_database_engine", lambda _settings: engine)
    monkeypatch.setattr(
        cli,
        "assert_schema_compatible",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(failure),
    )
    monkeypatch.setattr(
        StorageSettings,
        "from_env",
        lambda: pytest.fail("storage was constructed before schema refusal"),
    )

    exit_code = cli.main(["--drain"])

    captured = capsys.readouterr()
    assert exit_code == 2
    assert captured.out == ""
    assert captured.err.count("\n") == 1
    assert json.loads(captured.err) == {
        "event": "schema_compatibility",
        "status": "refused",
        "component": "worker",
        "code": "schema_revision_newer",
        "expected_revision": "0023",
        "actual_revision": "0024",
        "database_identity": "mysql+pymysql://worker:***@mysql/clsen_data",
    }
    assert events == ["dispose"]
    assert engine.dispose_count == 1


@pytest.mark.parametrize(
    "arguments",
    (
        ["--poll-seconds", "0.09"],
        ["--poll-seconds", "61"],
    ),
)
def test_poll_interval_validation_precedes_environment_loading(
    arguments: list[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        cli,
        "load_dotenv",
        lambda *_args, **_kwargs: pytest.fail("environment loaded for invalid input"),
    )

    with pytest.raises(SystemExit, match="poll interval"):
        cli.main(arguments)
