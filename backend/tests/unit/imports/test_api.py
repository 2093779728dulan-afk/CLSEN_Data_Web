from __future__ import annotations

import asyncio
from datetime import date, timedelta
from pathlib import Path
from typing import cast
from uuid import UUID

import pytest
from app.api import imports as imports_api
from app.api.errors import ApiError
from app.api.imports import _decode_original_filename
from app.auth.sessions import Principal
from app.config import StorageSettings
from app.imports.storage import BinaryReadStream
from app.imports.types import DuplicateBatchConflict, ImportCommand, ImportCreated
from app.parsers.workflow import ConfirmAndParseCommand, SuccessfulParse
from fastapi import Request
from fastapi.responses import JSONResponse
from sqlalchemy.engine import Engine
from starlette.types import Message, Scope


class _CapturingIngestService:
    def __init__(self) -> None:
        self.command: ImportCommand | None = None
        self.content = b""

    def ingest(
        self,
        source: BinaryReadStream,
        command: ImportCommand,
    ) -> ImportCreated:
        self.command = command
        self.content = source.read()
        return ImportCreated(
            raw_file_id=3,
            batch_id=5,
            sha256_hex="11" * 32,
            storage_key=f"sha256/11/{'11' * 32}",
            size_bytes=len(self.content),
            content_reused=False,
        )


class _DuplicateIngestService:
    def ingest(
        self,
        source: BinaryReadStream,
        command: ImportCommand,
    ) -> DuplicateBatchConflict:
        del source, command
        return DuplicateBatchConflict(
            existing_batch_id=92,
            raw_file_id=91,
            sha256_hex="95" * 32,
        )


class _ExistingBatchResult:
    def mappings(self) -> _ExistingBatchResult:
        return self

    def first(self) -> dict[str, object]:
        return {
            "report_date": date(2026, 7, 5),
            "report_type": "return_report",
            "stage": "uploaded",
        }


class _ExistingBatchConnection:
    def __init__(self) -> None:
        self.statement = ""

    def __enter__(self) -> _ExistingBatchConnection:
        return self

    def __exit__(self, *_args: object) -> None:
        return None

    def execute(self, statement: object, parameters: object) -> _ExistingBatchResult:
        del parameters
        self.statement = str(statement)
        return _ExistingBatchResult()


class _ExistingBatchEngine:
    def __init__(self) -> None:
        self.connection = _ExistingBatchConnection()

    def connect(self) -> _ExistingBatchConnection:
        return self.connection


class _CapturingParseWorkflow:
    def __init__(self) -> None:
        self.command: ConfirmAndParseCommand | None = None

    def confirm_and_parse(
        self,
        command: ConfirmAndParseCommand,
    ) -> SuccessfulParse:
        self.command = command
        return SuccessfulParse(
            batch_id=command.batch_id,
            parse_attempt_id=7,
            parse_baseline_id=11,
            confirmation_revision=1,
            report_type=command.report_type,
            source_row_count=2,
        )


def _principal() -> Principal:
    return Principal(
        user_id=13,
        username="operator",
        display_name="Operator",
        roles=frozenset({"data_manager"}),
        session_id=17,
        csrf_token_hash=b"x" * 32,
    )


def _request(body: bytes) -> Request:
    messages = iter(
        [
            {
                "type": "http.request",
                "body": body,
                "more_body": False,
            }
        ]
    )

    async def receive() -> Message:
        try:
            return cast(Message, next(messages))
        except StopIteration:
            return {"type": "http.disconnect"}

    scope: Scope = {
        "type": "http",
        "asgi": {"version": "3.0"},
        "http_version": "1.1",
        "method": "POST",
        "scheme": "http",
        "path": "/api/imports",
        "raw_path": b"/api/imports",
        "query_string": b"",
        "headers": [(b"content-type", b"text/csv")],
        "client": ("127.0.0.1", 12345),
        "server": ("127.0.0.1", 80),
    }
    return Request(scope, receive)


def test_original_filename_decodes_percent_encoded_utf8() -> None:
    assert (
        _decode_original_filename("%E9%80%80%E8%B4%A7%E6%8A%A5%E5%91%8A-2026-08-10.csv")
        == "退货报告-2026-08-10.csv"
    )


@pytest.mark.parametrize(
    ("value", "expected_message"),
    [
        ("%ff.csv", "X-Original-Filename must be percent-encoded UTF-8."),
        (
            "report%0d%0a.csv",
            "The original filename contains a control character.",
        ),
    ],
)
def test_original_filename_rejects_invalid_or_unsafe_encoded_values(
    value: str,
    expected_message: str,
) -> None:
    with pytest.raises(ApiError) as captured:
        _decode_original_filename(value)

    assert captured.value.status_code == 422
    detail = cast(dict[str, str], captured.value.detail)
    assert detail == {
        "code": "invalid_original_filename",
        "message": expected_message,
    }


def test_upload_freezes_the_server_resolved_current_site_configuration(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    ingest = _CapturingIngestService()
    storage = StorageSettings(
        root=tmp_path / "storage",
        max_upload_bytes=1024,
        lease_ttl=timedelta(minutes=30),
        lease_renew_interval=timedelta(minutes=5),
        orphan_age=timedelta(hours=24),
    )
    engine = cast(Engine, object())
    monkeypatch.setattr(StorageSettings, "from_env", lambda: storage)
    monkeypatch.setattr(imports_api, "_ingest_service", lambda _engine: ingest)
    monkeypatch.setattr(
        imports_api,
        "_resolve_current_site_config_version_id",
        lambda _engine, requested: 23 if requested is None else requested,
        raising=False,
    )

    response = asyncio.run(
        imports_api.upload_import(
            _request(b"header\nvalue\n"),
            _principal(),
            engine,
            report_date=date(2026, 8, 10),
            site_config_version_id=None,
            original_filename="report.csv",
        )
    )

    assert isinstance(response, imports_api.UploadResponse)
    assert response.batch_id == 5
    assert ingest.content == b"header\nvalue\n"
    assert ingest.command is not None
    assert ingest.command.site_config_version_id == 23


def test_duplicate_upload_prefers_detected_date_until_the_batch_is_confirmed(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    engine = _ExistingBatchEngine()
    storage = StorageSettings(
        root=tmp_path / "storage",
        max_upload_bytes=1024,
        lease_ttl=timedelta(minutes=30),
        lease_renew_interval=timedelta(minutes=5),
        orphan_age=timedelta(hours=24),
    )
    monkeypatch.setattr(StorageSettings, "from_env", lambda: storage)
    monkeypatch.setattr(
        imports_api,
        "_ingest_service",
        lambda _engine: _DuplicateIngestService(),
    )
    monkeypatch.setattr(
        imports_api,
        "_resolve_current_site_config_version_id",
        lambda _engine, _requested: 23,
        raising=False,
    )

    response = asyncio.run(
        imports_api.upload_import(
            _request(b"header\nvalue\n"),
            _principal(),
            cast(Engine, engine),
            report_date=date(2026, 8, 16),
            site_config_version_id=None,
            original_filename="return.csv",
        )
    )

    assert isinstance(response, JSONResponse)
    assert response.status_code == 409
    assert b'"report_date":"2026-07-05"' in response.body
    assert b'"existing_batch_id":92' in response.body
    assert (
        b'"workspace_url":"/review/2026-07-05?report_type=return_report"'
        in response.body
    )
    normalized_sql = " ".join(engine.connection.statement.split())
    assert (
        "WHEN batches.confirmed_at IS NULL THEN COALESCE( "
        "batches.detected_report_date, batches.candidate_report_date, "
        "batches.report_date )"
    ) in normalized_sql


def test_confirm_parse_uses_the_batch_frozen_site_configuration(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    workflow = _CapturingParseWorkflow()
    engine = cast(Engine, object())
    monkeypatch.setattr(imports_api, "_workflow", lambda _engine: workflow)
    monkeypatch.setattr(
        imports_api,
        "_resolve_batch_site_config_version_id",
        lambda _engine, batch_id, requested: 29,
        raising=False,
    )

    response = imports_api.confirm_parse(
        19,
        imports_api.ConfirmParseRequest(
            report_type="business_report",
            report_date=date(2026, 8, 10),
            encoding="utf-8-sig",
        ),
        _principal(),
        engine,
        UUID("aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"),
    )

    assert response["result"] == {
        "batch_id": 19,
        "parse_attempt_id": 7,
        "parse_baseline_id": 11,
        "confirmation_revision": 1,
        "report_type": "business_report",
        "source_row_count": 2,
    }
    assert workflow.command is not None
    assert workflow.command.site_config_version_id == 29
