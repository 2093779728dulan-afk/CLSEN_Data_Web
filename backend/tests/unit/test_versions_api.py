from __future__ import annotations

from collections import deque
from collections.abc import Iterator, Mapping
from datetime import UTC, date, datetime
from typing import cast

import pytest
from app.api.errors import ApiError
from app.api.versions import get_version, list_versions
from app.auth.sessions import Principal

NOW = datetime(2026, 8, 10, 8, 30, tzinfo=UTC)


class _Result:
    def __init__(self, rows: tuple[Mapping[str, object], ...]) -> None:
        self._rows = rows

    def mappings(self) -> _Result:
        return self

    def first(self) -> Mapping[str, object] | None:
        return self._rows[0] if self._rows else None

    def __iter__(self) -> Iterator[Mapping[str, object]]:
        return iter(self._rows)


class _Session:
    def __init__(self, *results: tuple[Mapping[str, object], ...]) -> None:
        self._results = deque(results)
        self.executions: list[tuple[str, dict[str, object]]] = []

    def execute(
        self,
        statement: object,
        parameters: Mapping[str, object] | None = None,
    ) -> _Result:
        self.executions.append((str(statement), dict(parameters or {})))
        if not self._results:
            raise AssertionError("unexpected database query")
        return _Result(self._results.popleft())


def _principal(*roles: str) -> Principal:
    return Principal(
        user_id=7,
        username="reader",
        display_name="Reader",
        roles=frozenset(roles),
        session_id=3,
        csrf_token_hash=b"csrf",
    )


def _version_row(
    *,
    version_id: int = 13,
    version_no: int = 2,
    status: str = "published",
    current_publication: bool = True,
    active_draft: bool = False,
) -> dict[str, object]:
    return {
        "dataset_id": 11,
        "version_id": version_id,
        "report_date": date(2026, 8, 9),
        "report_type": "business_report",
        "version_no": version_no,
        "status": status,
        "data_revision": 4,
        "review_revision": 6,
        "created_at": NOW,
        "sealed_at": NOW if status in {"published", "discarded"} else None,
        "published_version_id": version_id if current_publication else None,
        "published_at": NOW if current_publication else None,
        "draft_version_id": version_id if active_draft else None,
        "draft_pointed_at": NOW if active_draft else None,
        "publication_revision": None,
        "dedup_publication_revision": None,
    }


def _lineage_row(
    *,
    version_id: int,
    version_no: int,
    status: str,
    lineage_type: str,
) -> dict[str, object]:
    return {
        "dataset_id": 11,
        "version_id": version_id,
        "report_date": date(2026, 8, 9),
        "report_type": "business_report",
        "version_no": version_no,
        "status": status,
        "lineage_type": lineage_type,
        "lineage_ordinal": 1,
    }


def test_viewer_version_list_is_constrained_to_published_status() -> None:
    session = _Session((_version_row(),))

    result = list_versions(
        principal=_principal("viewer"),
        database_session=session,  # type: ignore[arg-type]
        report_date=date(2026, 8, 9),
        report_type="business_report",
    )

    assert [version.version_id for version in result] == [13]
    assert result[0].is_current_publication is True
    sql, parameters = session.executions[0]
    assert "versions.status = 'published'" in sql
    assert parameters == {
        "report_date": date(2026, 8, 9),
        "report_type": "business_report",
        "can_view_all": False,
    }


@pytest.mark.parametrize("role", ["admin", "data_manager"])
def test_management_roles_can_request_complete_version_history(role: str) -> None:
    session = _Session(
        (
            _version_row(
                version_id=14,
                version_no=3,
                status="draft",
                current_publication=False,
                active_draft=True,
            ),
        )
    )

    result = list_versions(
        principal=_principal(role),
        database_session=session,  # type: ignore[arg-type]
        report_date=date(2026, 8, 9),
        report_type="business_report",
    )

    assert result[0].status == "draft"
    assert result[0].is_active_draft is True
    assert session.executions[0][1]["can_view_all"] is True


def test_version_list_requires_date_and_type_without_batch_filter() -> None:
    session = _Session()

    with pytest.raises(ApiError) as captured:
        list_versions(
            principal=_principal("data_manager"),
            database_session=session,  # type: ignore[arg-type]
        )

    assert captured.value.status_code == 422
    assert session.executions == []


def test_batch_review_filter_returns_only_server_joined_ready_versions() -> None:
    ready = _version_row(
        version_id=21,
        version_no=4,
        status="ready_for_publish",
        current_publication=False,
        active_draft=True,
    )
    session = _Session(({"id": 81},), (ready,))

    result = list_versions(
        principal=_principal("data_manager"),
        database_session=session,  # type: ignore[arg-type]
        batch_review_run_id=81,
    )

    assert [version.version_id for version in result] == [21]
    assert len(session.executions) == 2
    existence_sql, existence_parameters = session.executions[0]
    versions_sql, versions_parameters = session.executions[1]
    assert "sites.code = :site_code" in existence_sql
    assert "items.site_id = runs.site_id" in versions_sql
    assert "datasets.site_id = runs.site_id" in versions_sql
    assert "items.status = 'ready_for_publish'" in versions_sql
    assert "versions.status = 'ready_for_publish'" in versions_sql
    assert (
        existence_parameters
        == versions_parameters
        == {
            "batch_review_run_id": 81,
            "site_code": "amazon_us",
        }
    )


@pytest.mark.parametrize("role", ["viewer"])
def test_batch_review_filter_hides_unpublished_task_from_viewer(role: str) -> None:
    session = _Session()

    with pytest.raises(ApiError) as captured:
        list_versions(
            principal=_principal(role),
            database_session=session,  # type: ignore[arg-type]
            batch_review_run_id=81,
        )

    assert captured.value.status_code == 404
    assert session.executions == []


def test_missing_or_cross_site_batch_review_uses_not_found() -> None:
    session = _Session(())

    with pytest.raises(ApiError) as captured:
        list_versions(
            principal=_principal("admin"),
            database_session=session,  # type: ignore[arg-type]
            batch_review_run_id=999,
        )

    assert captured.value.status_code == 404
    detail = cast(dict[str, str], captured.value.detail)
    assert detail == {
        "code": "batch_review_not_found",
        "message": "The batch review was not found.",
    }
    assert len(session.executions) == 1


def test_version_detail_returns_safe_lineage_and_latest_public_notes() -> None:
    session = _Session(
        (_version_row(),),
        (
            _lineage_row(
                version_id=12,
                version_no=1,
                status="published",
                lineage_type="base",
            ),
        ),
        (
            _lineage_row(
                version_id=15,
                version_no=3,
                status="published",
                lineage_type="draft_predecessor",
            ),
        ),
        (
            {
                "note_key": "release-note",
                "revision_number": 2,
                "body": "Published figures include the approved correction.",
                "created_at": NOW,
            },
        ),
    )

    result = get_version(
        version_id=13,
        principal=_principal("viewer"),
        database_session=session,  # type: ignore[arg-type]
    )

    assert [parent.version_id for parent in result.parents] == [12]
    assert [child.version_id for child in result.children] == [15]
    assert result.viewer_visible_notes[0].model_dump() == {
        "note_key": "release-note",
        "revision_number": 2,
        "body": "Published figures include the approved correction.",
        "created_at": NOW,
    }
    assert all(
        execution[1].get("can_view_all") is False
        for execution in session.executions[:3]
    )
    notes_sql = session.executions[3][0]
    assert "MAX(revision_number)" in notes_sql
    assert "notes.visibility = 'viewer_visible'" in notes_sql

    response_fields = result.model_dump()
    for forbidden_field in (
        "ruleset_version",
        "order_id",
        "license_plate_number",
        "customer_comments",
        "internal_notes",
    ):
        assert forbidden_field not in response_fields

    combined_sql = "\n".join(sql for sql, _parameters in session.executions)
    assert "business_version_rows" not in combined_sql
    assert "return_version_rows" not in combined_sql


def test_hidden_or_unknown_version_uses_the_same_not_found_response() -> None:
    session = _Session(())

    with pytest.raises(ApiError) as captured:
        get_version(
            version_id=999,
            principal=_principal("viewer"),
            database_session=session,  # type: ignore[arg-type]
        )

    assert captured.value.status_code == 404
    detail: object = captured.value.detail
    assert detail == {
        "code": "version_not_found",
        "message": "The requested version was not found.",
    }
    assert session.executions[0][1] == {
        "version_id": 999,
        "can_view_all": False,
    }
