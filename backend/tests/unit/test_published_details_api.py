from __future__ import annotations

import asyncio
import threading
from collections.abc import Generator, Iterator, MutableMapping
from contextlib import AbstractContextManager
from datetime import UTC, date, datetime, timedelta
from types import TracebackType
from typing import Any, ClassVar, cast

import pytest
from app.api import published_details as published_api
from app.api.dependencies import get_database_session, get_session_service
from app.api.errors import ApiError
from app.auth.sessions import Principal
from app.config import Settings
from app.db.session import SessionFactory
from app.imports.types import ReportType
from app.main import create_app
from app.published_details.csv_export import InvalidPublishedExportColumn
from app.published_details.models import (
    PublishedDetailPagination,
    PublishedDetailScope,
    PublishedRangeResponse,
)
from app.published_details.query_builder import InvalidPublishedSortColumn
from app.published_details.service import (
    PublicationScopeChanged,
    PublishedRowsPage,
    PublishedSchemaIntegrityError,
    PublishedSummaryPage,
)
from fastapi import APIRouter, FastAPI
from fastapi.routing import APIRoute
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session
from starlette.requests import ClientDisconnect

NOW = datetime(2026, 8, 17, 12, tzinfo=UTC)


def _principal(*roles: str) -> Principal:
    return Principal(
        user_id=7,
        username="reader",
        display_name="Reader",
        roles=frozenset(roles or ("viewer",)),
        session_id=4,
        csrf_token_hash=b"x" * 32,
    )


def _scope(
    principal: Principal,
    report_type: ReportType = "business_report",
) -> PublishedDetailScope:
    return PublishedDetailScope(
        user_id=principal.user_id,
        roles=tuple(sorted(principal.roles)),
        site_id=3,
        report_type=report_type,
        from_date=date(2026, 8, 1),
        to_date=date(2026, 8, 17),
        issued_at=NOW,
        expires_at=NOW + timedelta(minutes=5),
        publications=(),
    )


class _FakeSession:
    def __init__(self) -> None:
        self.open = True
        self.rollback_calls = 0
        self.commit_calls = 0
        self.connection_options: list[dict[str, str]] = []
        self.events: list[str] = []

    def rollback(self) -> None:
        self.rollback_calls += 1
        self.events.append("rollback")

    def commit(self) -> None:
        self.commit_calls += 1
        self.events.append("commit")

    def connection(self, *, execution_options: dict[str, str]) -> object:
        self.connection_options.append(execution_options)
        self.events.append("repeatable_read")
        return object()


class _SessionContext(AbstractContextManager[_FakeSession]):
    def __init__(self, session: _FakeSession) -> None:
        self._session = session

    def __enter__(self) -> _FakeSession:
        self._session.open = True
        return self._session

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc_value: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        self._session.open = False


class _SessionService:
    def __init__(self, principal: Principal, calls: list[_FakeSession]) -> None:
        self._principal = principal
        self._calls = calls

    def get_principal(
        self,
        database_session: _FakeSession,
        *,
        session_token: str,
    ) -> Principal:
        assert session_token == "session-proof"
        self._calls.append(database_session)
        database_session.events.append("auth_touch")
        return self._principal


class _FakeQueryService:
    sessions: ClassVar[list[_FakeSession]] = []
    last_scope: PublishedDetailScope | None = None
    failure: Exception | None = None

    def __init__(self, database_session: Session, _codec: object) -> None:
        session = cast(_FakeSession, database_session)
        self.database_session = session
        type(self).sessions.append(session)

    def resolve_full_range(
        self,
        _principal: Principal,
        _report_type: ReportType,
        today: date,
    ) -> PublishedRangeResponse:
        self.database_session.events.append("range_read")
        return PublishedRangeResponse(
            from_date=date(2026, 7, 1),
            to_date=today,
        )

    def resolve_publication_scope(
        self,
        principal: Principal,
        report_type: ReportType,
        _from_date: date,
        _to_date: date,
    ) -> PublishedDetailScope:
        self.database_session.events.append("scope_resolve")
        scope = _scope(principal, report_type)
        type(self).last_scope = scope
        return scope

    def query_date_summaries(
        self,
        scope: PublishedDetailScope,
        _search: str | None,
        page: int,
        page_size: int,
    ) -> PublishedSummaryPage:
        self.database_session.events.append("summary_read")
        self._raise_failure()
        type(self).last_scope = scope
        return PublishedSummaryPage(
            summaries=[],
            pagination=PublishedDetailPagination(
                page=page,
                page_size=page_size,
                total_items=0,
                total_pages=0,
            ),
        )

    def query_published_rows(
        self,
        scope: PublishedDetailScope,
        _search: str | None,
        _sort_column_id: object,
        _direction: str,
        page: int,
        page_size: int,
        _report_date: date | None,
    ) -> PublishedRowsPage:
        self.database_session.events.append("rows_read")
        self._raise_failure()
        type(self).last_scope = scope
        return PublishedRowsPage(
            columns=[],
            rows=[],
            pagination=PublishedDetailPagination(
                page=page,
                page_size=page_size,
                total_items=0,
                total_pages=0,
            ),
        )

    @classmethod
    def _raise_failure(cls) -> None:
        if cls.failure is not None:
            raise cls.failure


class _FakeCsvExporter:
    failure: Exception | None = None
    streamed_while_open = False
    closed_while_open = False

    def __init__(self, query_service: _FakeQueryService) -> None:
        self._query_service = query_service

    def stream_published_csv(
        self,
        scope: PublishedDetailScope,
        _query: object,
        _visible_column_ids: object,
    ) -> Generator[bytes]:
        failure = type(self).failure
        if failure is not None:
            raise failure
        self._query_service.database_session.events.append("export_prepare")

        def generate() -> Generator[bytes]:
            try:
                assert self._query_service.database_session.open
                self._query_service.database_session.events.append("stream_start")
                type(self).streamed_while_open = True
                yield b"test-csv"
            finally:
                self._query_service.database_session.events.append("stream_close")
                type(self).closed_while_open = self._query_service.database_session.open

        return generate()


class _SiteContextProbe:
    sessions: ClassVar[list[_FakeSession]] = []

    @classmethod
    def resolve(
        cls,
        _principal: Principal,
        database_session: Session,
    ) -> object:
        session = cast(_FakeSession, database_session)
        cls.sessions.append(session)
        session.events.append("site_read")
        return type(
            "SiteContext",
            (),
            {"site_id": 3, "reporting_timezone": "Asia/Shanghai"},
        )()


@pytest.fixture()
def api_client(
    monkeypatch: pytest.MonkeyPatch,
) -> Iterator[tuple[TestClient, _FakeSession, list[_FakeSession]]]:
    principal = _principal()
    session = _FakeSession()
    auth_sessions: list[_FakeSession] = []

    def session_factory() -> AbstractContextManager[_FakeSession]:
        return _SessionContext(session)

    monkeypatch.setattr(published_api, "PublishedDetailQueryService", _FakeQueryService)
    monkeypatch.setattr(published_api, "PublishedCsvExporter", _FakeCsvExporter)
    monkeypatch.setattr(published_api, "_utc_now", lambda: NOW)
    monkeypatch.setattr(published_api, "_site_context", _SiteContextProbe.resolve)
    _FakeQueryService.sessions = []
    _FakeQueryService.last_scope = None
    _FakeQueryService.failure = None
    _FakeCsvExporter.failure = None
    _FakeCsvExporter.streamed_while_open = False
    _FakeCsvExporter.closed_while_open = False
    _SiteContextProbe.sessions = []

    application = create_app(
        settings=Settings(
            environment="test",
            log_level="CRITICAL",
            cors_allowed_origins=(),
            session_secret="published-api-test-secret-0000000",
            session_cookie_secure=False,
        ),
        session_factory=cast(SessionFactory, session_factory),
    )
    application.dependency_overrides[get_session_service] = lambda: _SessionService(
        principal,
        auth_sessions,
    )
    with TestClient(application, raise_server_exceptions=False) as client:
        client.cookies.set("clsen_session", "session-proof")
        yield client, session, auth_sessions


def _get(
    client: TestClient,
    path: str,
    **params: object,
) -> Any:
    return client.get(path, params=cast(Any, params))


def _summary_params(**overrides: object) -> dict[str, object]:
    params: dict[str, object] = {
        "report_type": "business_report",
        "from": "2026-08-01",
        "to": "2026-08-17",
        "page": 1,
        "page_size": 50,
    }
    params.update(overrides)
    return params


def test_initial_summary_uses_one_repeatable_read_session_and_issues_scope(
    api_client: tuple[TestClient, _FakeSession, list[_FakeSession]],
) -> None:
    client, session, auth_sessions = api_client

    response = _get(client, "/api/published-details/summaries", **_summary_params())

    assert response.status_code == 200
    assert response.json()["scope_token"]
    assert response.json()["range"] == {
        "from_date": "2026-08-01",
        "to_date": "2026-08-17",
    }
    assert auth_sessions == [session]
    assert _FakeQueryService.sessions == [session]
    assert session.rollback_calls == 0
    assert session.connection_options == [{"isolation_level": "REPEATABLE READ"}]
    assert session.commit_calls == 2
    assert session.events == [
        "auth_touch",
        "commit",
        "repeatable_read",
        "scope_resolve",
        "summary_read",
        "commit",
    ]


def test_range_uses_the_site_reporting_day_in_the_same_snapshot(
    api_client: tuple[TestClient, _FakeSession, list[_FakeSession]],
) -> None:
    client, session, auth_sessions = api_client

    response = _get(
        client,
        "/api/published-details/range",
        report_type="business_report",
    )

    assert response.status_code == 200
    assert response.json() == {
        "from_date": "2026-07-01",
        "to_date": "2026-08-17",
    }
    assert auth_sessions == [session]
    assert _SiteContextProbe.sessions == [session]
    assert _FakeQueryService.sessions == [session]
    assert session.rollback_calls == 0
    assert session.connection_options == [{"isolation_level": "REPEATABLE READ"}]
    assert session.events == [
        "auth_touch",
        "commit",
        "repeatable_read",
        "site_read",
        "range_read",
        "commit",
    ]


def test_follow_up_rows_reuses_the_bound_scope_token(
    api_client: tuple[TestClient, _FakeSession, list[_FakeSession]],
) -> None:
    client, session, auth_sessions = api_client
    first = _get(client, "/api/published-details/summaries", **_summary_params())
    token = first.json()["scope_token"]

    response = _get(
        client,
        "/api/published-details/rows",
        **_summary_params(scope_token=token, direction="desc"),
    )

    assert response.status_code == 200
    assert response.json()["scope_token"] == token
    assert _FakeQueryService.last_scope == _scope(_principal())
    assert auth_sessions == [session, session]
    assert _SiteContextProbe.sessions == [session]
    assert _FakeQueryService.sessions == [session, session]


def test_expired_scope_token_is_a_stable_conflict(
    api_client: tuple[TestClient, _FakeSession, list[_FakeSession]],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client, _session, _auth_sessions = api_client
    first = _get(client, "/api/published-details/summaries", **_summary_params())
    monkeypatch.setattr(
        published_api,
        "_utc_now",
        lambda: NOW + timedelta(minutes=6),
    )

    response = _get(
        client,
        "/api/published-details/summaries",
        **_summary_params(scope_token=first.json()["scope_token"]),
    )

    assert response.status_code == 409
    assert response.json()["error"]["code"] == "published_scope_expired"


def test_invalid_range_and_token_return_non_leaking_public_conflicts(
    api_client: tuple[TestClient, _FakeSession, list[_FakeSession]],
) -> None:
    client, _session, _auth_sessions = api_client
    invalid_range = _get(
        client,
        "/api/published-details/summaries",
        **_summary_params(**{"from": "2026-08-18"}),
    )
    invalid_token = _get(
        client,
        "/api/published-details/summaries",
        **_summary_params(scope_token="secret-looking-token"),
    )

    assert invalid_range.status_code == 422
    assert invalid_range.json()["error"]["code"] == "invalid_date_range"
    assert invalid_token.status_code == 409
    assert invalid_token.json()["error"]["code"] == "published_scope_invalid"
    assert "secret-looking-token" not in invalid_token.text


@pytest.mark.parametrize(
    "path",
    [
        "/api/published-details/summaries",
        "/api/published-details/rows",
    ],
)
def test_empty_scope_token_is_decoded_as_an_invalid_conflict(
    api_client: tuple[TestClient, _FakeSession, list[_FakeSession]],
    path: str,
) -> None:
    client, _session, _auth_sessions = api_client

    response = _get(client, path, **_summary_params(scope_token=""))

    assert response.status_code == 409
    assert response.json()["error"]["code"] == "published_scope_invalid"


def test_export_distinguishes_missing_and_explicitly_empty_scope_token(
    api_client: tuple[TestClient, _FakeSession, list[_FakeSession]],
) -> None:
    client, _session, _auth_sessions = api_client
    params = _summary_params(column_id="00000000-0000-0000-0000-000000000001")

    missing = _get(client, "/api/published-details/export.csv", **params)
    empty = _get(
        client,
        "/api/published-details/export.csv",
        **{**params, "scope_token": ""},
    )

    assert missing.status_code == 422
    assert empty.status_code == 409
    assert empty.json()["error"]["code"] == "published_scope_invalid"


@pytest.mark.parametrize(
    ("error", "status_code", "code"),
    [
        (PublicationScopeChanged(), 409, "publication_scope_changed"),
        (InvalidPublishedSortColumn(), 403, "invalid_published_sort_column"),
        (
            PublishedSchemaIntegrityError("SELECT secret FROM private_table"),
            500,
            "published_data_integrity_error",
        ),
    ],
)
def test_rows_maps_domain_errors_without_internal_details(
    api_client: tuple[TestClient, _FakeSession, list[_FakeSession]],
    error: Exception,
    status_code: int,
    code: str,
) -> None:
    client, _session, _auth_sessions = api_client
    _FakeQueryService.failure = error

    response = _get(client, "/api/published-details/rows", **_summary_params())

    assert response.status_code == status_code
    assert response.json()["error"]["code"] == code
    assert "private_table" not in response.text


def test_export_requires_a_token_maps_hidden_columns_and_keeps_session_open(
    api_client: tuple[TestClient, _FakeSession, list[_FakeSession]],
) -> None:
    client, session, _auth_sessions = api_client
    missing = _get(
        client,
        "/api/published-details/export.csv",
        **_summary_params(column_id="00000000-0000-0000-0000-000000000001"),
    )
    initial = _get(client, "/api/published-details/summaries", **_summary_params())
    token = initial.json()["scope_token"]
    successful = _get(
        client,
        "/api/published-details/export.csv",
        **_summary_params(
            scope_token=token,
            column_id="00000000-0000-0000-0000-000000000001",
        ),
    )

    assert missing.status_code == 422
    assert successful.status_code == 200
    assert successful.headers["content-type"] == "text/csv; charset=utf-8"
    assert "attachment" in successful.headers["content-disposition"]
    assert successful.content == b"test-csv"
    assert _FakeCsvExporter.streamed_while_open
    assert _FakeCsvExporter.closed_while_open
    assert not session.open


def test_cancelled_stream_closes_before_request_session_teardown() -> None:
    _FakeCsvExporter.closed_while_open = False
    session = _FakeSession()

    def session_factory() -> AbstractContextManager[_FakeSession]:
        return _SessionContext(session)

    dependency = get_database_session(cast(SessionFactory, session_factory))
    owned_session = next(dependency)
    service = _FakeQueryService(owned_session, object())
    stream = _FakeCsvExporter(service).stream_published_csv(
        _scope(_principal()),
        object(),
        [],
    )
    response = published_api._ClosingStreamingResponse(
        stream,
        media_type="text/csv; charset=utf-8",
        headers={},
    )

    async def disconnect_during_body() -> None:
        async def receive() -> dict[str, str]:
            return {"type": "http.disconnect"}

        async def send(message: MutableMapping[str, Any]) -> None:
            if message["type"] == "http.response.body":
                raise OSError("client disconnected")

        with pytest.raises(ClientDisconnect):
            await response(
                {"type": "http", "asgi": {"spec_version": "2.4"}},
                receive,
                send,
            )

    asyncio.run(disconnect_during_body())
    assert _FakeCsvExporter.closed_while_open
    assert session.open

    dependency.close()
    assert not session.open


def _lazy_stream_with_source_events(
    session: _FakeSession,
    events: list[str],
    close_threads: list[int],
) -> Generator[bytes]:
    events.append("source_created")
    try:
        while True:
            assert session.open
            yield b"chunk"
    finally:
        events.append("source_closed")
        close_threads.append(threading.get_ident())


def test_asgi_23_disconnect_before_first_chunk_has_no_unowned_source() -> None:
    events: list[str] = []
    close_threads: list[int] = []
    session = _FakeSession()
    stream = _lazy_stream_with_source_events(session, events, close_threads)

    def session_factory() -> AbstractContextManager[_FakeSession]:
        return _SessionContext(session)

    dependency = get_database_session(cast(SessionFactory, session_factory))
    owned_session = cast(_FakeSession, next(dependency))
    assert owned_session is session
    response = published_api._ClosingStreamingResponse(
        stream,
        media_type="text/csv; charset=utf-8",
        headers={},
    )

    async def disconnect_immediately() -> None:
        async def receive() -> dict[str, str]:
            return {"type": "http.disconnect"}

        async def send(_message: MutableMapping[str, Any]) -> None:
            await asyncio.sleep(0)

        await response(
            {"type": "http", "asgi": {"spec_version": "2.3"}},
            receive,
            send,
        )

    asyncio.run(disconnect_immediately())

    assert session.open
    if "source_created" in events:
        assert events[-1] == "source_closed"
    else:
        assert events == []
    dependency.close()
    assert not session.open


def test_asgi_23_disconnect_after_start_closes_off_loop_before_teardown() -> None:
    events: list[str] = []
    close_threads: list[int] = []
    session = _FakeSession()
    stream = _lazy_stream_with_source_events(session, events, close_threads)

    def session_factory() -> AbstractContextManager[_FakeSession]:
        return _SessionContext(session)

    dependency = get_database_session(cast(SessionFactory, session_factory))
    owned_session = cast(_FakeSession, next(dependency))
    assert owned_session is session
    response = published_api._ClosingStreamingResponse(
        stream,
        media_type="text/csv; charset=utf-8",
        headers={},
    )
    event_loop_thread = threading.get_ident()

    async def disconnect_after_first_body() -> None:
        first_body = asyncio.Event()

        async def receive() -> dict[str, str]:
            await first_body.wait()
            return {"type": "http.disconnect"}

        async def send(message: MutableMapping[str, Any]) -> None:
            if message["type"] == "http.response.body":
                first_body.set()
                await asyncio.sleep(3600)

        await response(
            {"type": "http", "asgi": {"spec_version": "2.3"}},
            receive,
            send,
        )

    asyncio.run(disconnect_after_first_body())

    assert events == ["source_created", "source_closed"]
    assert close_threads and close_threads[-1] != event_loop_thread
    assert session.open
    dependency.close()
    assert not session.open


def test_outer_task_cancellation_closes_off_loop_before_teardown() -> None:
    events: list[str] = []
    close_threads: list[int] = []
    session = _FakeSession()
    stream = _lazy_stream_with_source_events(session, events, close_threads)

    def session_factory() -> AbstractContextManager[_FakeSession]:
        return _SessionContext(session)

    dependency = get_database_session(cast(SessionFactory, session_factory))
    owned_session = cast(_FakeSession, next(dependency))
    assert owned_session is session
    response = published_api._ClosingStreamingResponse(
        stream,
        media_type="text/csv; charset=utf-8",
        headers={},
    )
    event_loop_thread = threading.get_ident()

    async def cancel_after_first_body() -> None:
        first_body = asyncio.Event()

        async def receive() -> dict[str, str]:
            await asyncio.sleep(3600)
            return {"type": "http.disconnect"}

        async def send(message: MutableMapping[str, Any]) -> None:
            if message["type"] == "http.response.body":
                first_body.set()
                await asyncio.sleep(3600)

        response_task = asyncio.create_task(
            response(
                {"type": "http", "asgi": {"spec_version": "2.4"}},
                receive,
                send,
            )
        )
        await first_body.wait()
        response_task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await response_task

    asyncio.run(cancel_after_first_body())

    assert events == ["source_created", "source_closed"]
    assert close_threads and close_threads[-1] != event_loop_thread
    assert session.open
    dependency.close()
    assert not session.open


def test_stream_failure_aborts_without_a_successful_end_of_body() -> None:
    events: list[MutableMapping[str, Any]] = []
    closed = False

    def failing_stream() -> Generator[bytes]:
        nonlocal closed
        try:
            yield b"partial"
            raise RuntimeError("stream integrity failure")
        finally:
            closed = True

    response = published_api._ClosingStreamingResponse(
        failing_stream(),
        media_type="text/csv; charset=utf-8",
        headers={},
    )

    async def consume() -> None:
        async def receive() -> dict[str, str]:
            return {"type": "http.disconnect"}

        async def send(message: MutableMapping[str, Any]) -> None:
            events.append(message)

        with pytest.raises(RuntimeError, match="stream integrity failure"):
            await response(
                {"type": "http", "asgi": {"spec_version": "2.4"}},
                receive,
                send,
            )

    asyncio.run(consume())

    assert closed
    assert any(event.get("body") == b"partial" for event in events)
    assert not any(
        event.get("type") == "http.response.body" and event.get("more_body") is False
        for event in events
    )


def test_export_maps_unauthorized_column_without_starting_a_response_body(
    api_client: tuple[TestClient, _FakeSession, list[_FakeSession]],
) -> None:
    client, _session, _auth_sessions = api_client
    initial = _get(client, "/api/published-details/summaries", **_summary_params())
    _FakeCsvExporter.failure = InvalidPublishedExportColumn()

    response = _get(
        client,
        "/api/published-details/export.csv",
        **_summary_params(
            scope_token=initial.json()["scope_token"],
            column_id="00000000-0000-0000-0000-000000000001",
        ),
    )

    assert response.status_code == 403
    assert response.json()["error"]["code"] == "invalid_published_export_column"


def _published_route(application: FastAPI, path: str) -> APIRoute:
    pending = list(application.routes)
    while pending:
        route = pending.pop()
        if isinstance(route, APIRoute) and route.path == path:
            return route
        original_router = getattr(route, "original_router", None)
        if isinstance(original_router, APIRouter):
            pending.extend(original_router.routes)
    raise AssertionError(f"route not found: {path}")


def test_published_openapi_contract_is_bounded_typed_and_read_only() -> None:
    application = create_app(
        settings=Settings(
            environment="test",
            log_level="CRITICAL",
            cors_allowed_origins=(),
            session_secret="published-openapi-test-secret-00000",
            session_cookie_secure=False,
        )
    )
    schema = application.openapi()
    paths = schema["paths"]

    for path, response_model in (
        ("/api/published-details/range", "PublishedRangeResponse"),
        ("/api/published-details/summaries", "PublishedSummaryResponse"),
        ("/api/published-details/rows", "PublishedRowsResponse"),
    ):
        operation = paths[path]["get"]
        assert operation["security"] == [{"SessionCookie": []}]
        assert operation["responses"]["200"]["content"]["application/json"][
            "schema"
        ] == {"$ref": f"#/components/schemas/{response_model}"}
        assert all(
            parameter["name"] not in {"X-CSRF-Token", "Idempotency-Key"}
            for parameter in operation.get("parameters", [])
        )

    rows = paths["/api/published-details/rows"]["get"]
    parameters = {parameter["name"]: parameter for parameter in rows["parameters"]}
    report_type_schema = schema["components"]["schemas"]["ReportType"]
    assert parameters["report_type"]["schema"] == {
        "$ref": "#/components/schemas/ReportType"
    }
    assert report_type_schema["enum"] == [
        "business_report",
        "return_report",
    ]
    assert parameters["direction"]["schema"]["enum"] == ["asc", "desc"]
    assert parameters["page_size"]["schema"]["maximum"] == 100
    assert parameters["page_size"]["schema"]["minimum"] == 1
    summaries = paths["/api/published-details/summaries"]["get"]
    summary_parameters = {
        parameter["name"]: parameter for parameter in summaries["parameters"]
    }
    assert summary_parameters["page_size"]["schema"]["maximum"] == 100
    assert summary_parameters["page_size"]["schema"]["minimum"] == 1

    export = paths["/api/published-details/export.csv"]["get"]
    export_parameters = {
        parameter["name"]: parameter for parameter in export["parameters"]
    }
    assert export_parameters["scope_token"]["required"] is True
    assert "minLength" not in export_parameters["scope_token"]["schema"]
    assert "maxLength" not in export_parameters["scope_token"]["schema"]
    assert export_parameters["column_id"]["required"] is True
    assert export_parameters["column_id"]["schema"] == {
        "items": {"type": "string", "format": "uuid"},
        "type": "array",
        "title": "Column Id",
    }
    assert export["responses"]["200"]["content"] == {
        "text/csv": {"schema": {"type": "string", "format": "binary"}}
    }
    assert export["security"] == [{"SessionCookie": []}]
    assert export_parameters["direction"]["schema"]["enum"] == ["asc", "desc"]
    assert all(
        parameter["name"] not in {"X-CSRF-Token", "Idempotency-Key"}
        for parameter in export["parameters"]
    )

    for path in paths:
        if not path.startswith("/api/published-details"):
            continue
        direct_database_dependencies = [
            dependency
            for dependency in _published_route(application, path).dependant.dependencies
            if dependency.name == "database_session"
        ]
        assert len(direct_database_dependencies) == 1
        assert direct_database_dependencies[0].scope == "request"


def test_published_routes_allow_exactly_the_three_reader_roles() -> None:
    application = create_app(
        settings=Settings(
            environment="test",
            log_level="CRITICAL",
            cors_allowed_origins=(),
            session_secret="published-role-test-secret-00000000",
            session_cookie_secure=False,
        )
    )

    for path in (
        "/api/published-details/range",
        "/api/published-details/summaries",
        "/api/published-details/rows",
        "/api/published-details/export.csv",
    ):
        route = _published_route(application, path)
        role_dependency = next(
            dependency.call
            for dependency in route.dependant.dependencies
            if dependency.name == "principal"
        )
        assert role_dependency is not None
        for role in ("admin", "data_manager", "viewer"):
            assert role_dependency(_principal(role)) == _principal(role)
        with pytest.raises(ApiError) as caught:
            role_dependency(_principal("auditor"))
        assert caught.value.status_code == 403
        detail = cast(dict[str, str], caught.value.detail)
        assert detail["code"] == "role_forbidden"
