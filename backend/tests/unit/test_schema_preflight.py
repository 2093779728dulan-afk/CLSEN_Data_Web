from __future__ import annotations

import json
from pathlib import Path
from typing import Any, cast

import pytest
from app.maintenance.schema_compatibility import (
    SchemaCompatibilityCode,
    SchemaCompatibilityFailure,
)
from app.maintenance.schema_revision import CURRENT_SCHEMA_REVISION
from app.schema_preflight import main, run_preflight
from sqlalchemy.engine import Engine


class _DisposableEngine:
    def __init__(self) -> None:
        self.dispose_count = 0

    def dispose(self) -> None:
        self.dispose_count += 1


def test_run_preflight_uses_safe_identity_and_always_disposes_engine(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    engine = _DisposableEngine()
    observed: dict[str, Any] = {}
    monkeypatch.setenv(
        "APP_DATABASE_URL",
        "mysql+pymysql://app:do-not-log-me@mysql:3306/clsen_data?charset=utf8mb4",
    )

    def create_engine(settings: object) -> _DisposableEngine:
        observed["settings"] = settings
        return engine

    monkeypatch.setattr(
        "app.schema_preflight.create_database_engine",
        create_engine,
    )

    def compatible(candidate: Engine, *, database_identity: str) -> None:
        observed["engine"] = candidate
        observed["database_identity"] = database_identity

    monkeypatch.setattr("app.schema_preflight.assert_schema_compatible", compatible)

    run_preflight(component="api")

    assert observed["engine"] is engine
    assert observed["database_identity"] == (
        "mysql+pymysql://app:***@mysql:3306/clsen_data?charset=utf8mb4"
    )
    assert "do-not-log-me" not in str(observed)
    assert engine.dispose_count == 1


def test_environment_file_is_optional_and_process_environment_wins(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    environment_file = tmp_path / ".env"
    environment_file.write_text(
        "ALT_DATABASE_URL=mysql+pymysql://file:file-secret@file-db:3306/file_db?charset=utf8mb4\n",
        encoding="utf-8",
    )
    monkeypatch.setenv(
        "ALT_DATABASE_URL",
        "mysql+pymysql://process:process-secret@process-db:3306/process_db?charset=utf8mb4",
    )
    engine = _DisposableEngine()
    identities: list[str] = []
    monkeypatch.setattr(
        "app.schema_preflight.create_database_engine",
        lambda _settings: cast(Engine, engine),
    )
    monkeypatch.setattr(
        "app.schema_preflight.assert_schema_compatible",
        lambda _engine, *, database_identity: identities.append(database_identity),
    )

    run_preflight(
        database_environment="ALT_DATABASE_URL",
        environment_file=environment_file,
        component="worker",
    )

    assert identities == [
        "mysql+pymysql://process:***@process-db:3306/process_db?charset=utf8mb4"
    ]
    assert engine.dispose_count == 1


def test_environment_file_supplies_the_named_database_variable(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    environment_file = tmp_path / ".env"
    environment_file.write_text(
        "ALT_DATABASE_URL=mysql+pymysql://file:file-secret@file-db:3306/file_db?charset=utf8mb4\n",
        encoding="utf-8",
    )
    monkeypatch.delenv("ALT_DATABASE_URL", raising=False)
    engine = _DisposableEngine()
    identities: list[str] = []
    monkeypatch.setattr(
        "app.schema_preflight.create_database_engine",
        lambda _settings: cast(Engine, engine),
    )
    monkeypatch.setattr(
        "app.schema_preflight.assert_schema_compatible",
        lambda _engine, *, database_identity: identities.append(database_identity),
    )

    run_preflight(
        database_environment="ALT_DATABASE_URL",
        environment_file=environment_file,
        component="worker",
    )

    assert identities == [
        "mysql+pymysql://file:***@file-db:3306/file_db?charset=utf8mb4"
    ]


def test_run_preflight_disposes_engine_after_schema_refusal(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    engine = _DisposableEngine()
    failure = SchemaCompatibilityFailure(
        code=SchemaCompatibilityCode.REVISION_OLDER,
        expected_revision="0022",
        actual_revision="0021",
        database_identity="mysql+pymysql://app:***@mysql/schema",
    )
    monkeypatch.setenv(
        "APP_DATABASE_URL",
        "mysql+pymysql://app:secret@mysql:3306/clsen_data?charset=utf8mb4",
    )
    monkeypatch.setattr(
        "app.schema_preflight.create_database_engine",
        lambda _settings: cast(Engine, engine),
    )
    monkeypatch.setattr(
        "app.schema_preflight.assert_schema_compatible",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(failure),
    )

    with pytest.raises(SchemaCompatibilityFailure) as captured:
        run_preflight(component="api")

    assert captured.value is failure
    assert engine.dispose_count == 1


def test_cli_success_emits_exactly_one_json_event(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    calls: list[dict[str, object]] = []
    monkeypatch.setattr(
        "app.schema_preflight.run_preflight",
        lambda **keywords: calls.append(keywords),
    )

    exit_code = main(["--component", "worker"])

    captured = capsys.readouterr()
    assert exit_code == 0
    assert captured.err == ""
    assert captured.out.count("\n") == 1
    assert json.loads(captured.out) == {
        "event": "schema_compatibility",
        "status": "compatible",
        "component": "worker",
        "code": None,
        "expected_revision": CURRENT_SCHEMA_REVISION,
        "actual_revision": CURRENT_SCHEMA_REVISION,
        "database_identity": None,
    }
    assert calls == [
        {
            "database_environment": "APP_DATABASE_URL",
            "environment_file": None,
            "component": "worker",
        }
    ]


def test_cli_schema_refusal_emits_one_safe_json_event(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    failure = SchemaCompatibilityFailure(
        code=SchemaCompatibilityCode.REVISION_OLDER,
        expected_revision="0022",
        actual_revision="0021",
        database_identity="mysql+pymysql://app:***@mysql/clsen_data",
    )
    monkeypatch.setattr(
        "app.schema_preflight.run_preflight",
        lambda **_keywords: (_ for _ in ()).throw(failure),
    )

    exit_code = main(["--component", "api"])

    captured = capsys.readouterr()
    assert exit_code == 2
    assert captured.out == ""
    assert captured.err.count("\n") == 1
    assert json.loads(captured.err)["code"] == "schema_revision_older"
    assert "***" in captured.err
    assert "do-not-log-me" not in captured.err


def test_cli_configuration_failure_is_safe_and_does_not_create_an_engine(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.delenv("MISSING_DATABASE_URL", raising=False)

    exit_code = main(
        [
            "--component",
            "api",
            "--database-environment",
            "MISSING_DATABASE_URL",
        ]
    )

    captured = capsys.readouterr()
    assert exit_code == 2
    assert captured.out == ""
    assert captured.err.count("\n") == 1
    event = json.loads(captured.err)
    assert event == {
        "event": "schema_compatibility",
        "status": "refused",
        "component": "api",
        "code": "schema_configuration_invalid",
        "expected_revision": CURRENT_SCHEMA_REVISION,
        "actual_revision": None,
        "database_identity": None,
    }
    assert "MISSING_DATABASE_URL" not in captured.err


@pytest.mark.parametrize(
    "arguments",
    (
        ["--component", "other"],
        ["--component", "api", "--unknown"],
    ),
)
def test_cli_rejects_unsupported_arguments(arguments: list[str]) -> None:
    with pytest.raises(SystemExit) as captured:
        main(arguments)

    assert captured.value.code == 2
