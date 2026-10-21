from __future__ import annotations

from collections.abc import Iterator, Mapping, Sequence
from datetime import UTC, date, datetime, timedelta
from typing import cast
from uuid import UUID

import pytest
from app.analytics.models import PublicationReference
from app.auth.sessions import Principal
from app.published_details.models import PublishedDetailScope
from app.published_details.scope import PublishedScopeCodec
from app.published_details.service import (
    PublicationScopeChanged,
    PublishedDetailQueryService,
    PublishedSchemaIntegrityError,
    PublishedSiteConfigurationError,
)
from sqlalchemy.orm import Session


class _Mappings:
    def __init__(self, rows: list[dict[str, object]]) -> None:
        self._rows = rows

    def all(self) -> list[dict[str, object]]:
        return self._rows


class _Result:
    def __init__(self, rows: list[dict[str, object]]) -> None:
        self._rows = rows

    def mappings(self) -> _Mappings:
        return _Mappings(self._rows)


class FakeSession:
    def __init__(self, *results: Sequence[Mapping[str, object]]) -> None:
        self._results: Iterator[list[dict[str, object]]] = iter(
            [[dict(row) for row in result] for result in results]
        )
        self.executions: list[tuple[str, dict[str, object]]] = []

    def execute(
        self,
        statement: object,
        parameters: dict[str, object] | None = None,
    ) -> _Result:
        self.executions.append((str(statement), parameters or {}))
        return _Result(next(self._results))


def _service(session: FakeSession) -> PublishedDetailQueryService:
    return PublishedDetailQueryService(cast(Session, session), _codec())


SKU = UUID("10000000-0000-0000-0000-000000000001")
TITLE = UUID("10000000-0000-0000-0000-000000000002")
CUSTOM_A = UUID("10000000-0000-0000-0000-000000000003")
CUSTOM_B = UUID("10000000-0000-0000-0000-000000000004")


def _codec() -> PublishedScopeCodec:
    return PublishedScopeCodec(
        secret="unit-test-secret",
        clock=lambda: datetime(2026, 8, 17, 12, tzinfo=UTC),
        ttl=timedelta(minutes=5),
    )


def _principal() -> Principal:
    return Principal(
        user_id=7,
        username="reader",
        display_name="Reader",
        roles=frozenset({"viewer"}),
        session_id=4,
        csrf_token_hash=b"x" * 32,
    )


def _publication(
    *,
    report_date: date,
    dataset_id: int,
    version_id: int,
    report_type: str = "business_report",
    site_id: int = 3,
    published_at: datetime | None = None,
) -> PublicationReference:
    return PublicationReference(
        dataset_id=dataset_id,
        site_id=site_id,
        report_date=report_date,
        report_type=report_type,  # type: ignore[arg-type]
        version_id=version_id,
        published_at=published_at
        or datetime.combine(report_date, datetime.min.time(), tzinfo=UTC),
    )


def _scope(
    *,
    report_type: str = "business_report",
    publications: tuple[PublicationReference, ...] | None = None,
) -> PublishedDetailScope:
    return PublishedDetailScope(
        user_id=7,
        roles=("viewer",),
        site_id=3,
        report_type=report_type,  # type: ignore[arg-type]
        from_date=date(2026, 8, 1),
        to_date=date(2026, 8, 2),
        issued_at=datetime(2026, 8, 17, 12, tzinfo=UTC),
        expires_at=datetime(2026, 8, 17, 12, 5, tzinfo=UTC),
        publications=publications
        or (
            _publication(report_date=date(2026, 8, 1), dataset_id=11, version_id=101),
            _publication(report_date=date(2026, 8, 2), dataset_id=12, version_id=102),
        ),
    )


def _column(
    *,
    report_date: date,
    version_id: int,
    column_id: UUID,
    source_header: str,
    display_order: int,
    report_type: str = "business_report",
    standard_field_name: str | None = None,
    value_kind: str = "text",
    is_key: bool = False,
    participates_in_statistics: bool = False,
) -> dict[str, object]:
    return {
        "dataset_id": 10 + report_date.day,
        "site_id": 3,
        "report_date": report_date,
        "report_type": report_type,
        "version_id": version_id,
        "column_id": column_id.bytes,
        "source_header": source_header,
        "display_order": display_order,
        "value_kind": value_kind,
        "standard_field_name": standard_field_name,
        "is_key": is_key,
        "participates_in_statistics": participates_in_statistics,
    }


def test_schema_union_uses_date_ascending_first_seen_order() -> None:
    rows = [
        _column(
            report_date=date(2026, 8, 1),
            version_id=101,
            column_id=SKU,
            source_header="SKU",
            display_order=1,
            standard_field_name="sku",
            is_key=True,
            participates_in_statistics=True,
        ),
        _column(
            report_date=date(2026, 8, 1),
            version_id=101,
            column_id=TITLE,
            source_header="Title",
            display_order=2,
            standard_field_name="title",
        ),
        _column(
            report_date=date(2026, 8, 1),
            version_id=101,
            column_id=CUSTOM_A,
            source_header="Custom A",
            display_order=3,
        ),
        _column(
            report_date=date(2026, 8, 2),
            version_id=102,
            column_id=SKU,
            source_header="SKU",
            display_order=1,
            standard_field_name="sku",
            is_key=True,
            participates_in_statistics=True,
        ),
        _column(
            report_date=date(2026, 8, 2),
            version_id=102,
            column_id=CUSTOM_B,
            source_header="Custom B",
            display_order=2,
        ),
        _column(
            report_date=date(2026, 8, 2),
            version_id=102,
            column_id=TITLE,
            source_header="Title",
            display_order=3,
            standard_field_name="title",
        ),
    ]
    session = FakeSession(rows)

    result = _service(session).compose_published_schema(_scope())

    assert [column.column_id for column in result] == [
        SKU,
        TITLE,
        CUSTOM_A,
        CUSTOM_B,
    ]
    assert [column.display_order for column in result] == [1, 2, 3, 4]
    assert "version_table_columns" in session.executions[0][0]
    assert session.executions[0][1]["version_ids"] == (101, 102)


def test_schema_union_never_merges_report_types() -> None:
    rows = [
        _column(
            report_date=date(2026, 8, 1),
            version_id=101,
            column_id=SKU,
            source_header="SKU",
            display_order=1,
            report_type="return_report",
        )
    ]

    with pytest.raises(PublishedSchemaIntegrityError):
        _service(FakeSession(rows)).compose_published_schema(_scope())


def test_schema_union_repeated_stable_id_appears_once() -> None:
    rows = [
        _column(
            report_date=date(2026, 8, day),
            version_id=100 + day,
            column_id=SKU,
            source_header="SKU",
            display_order=1,
            standard_field_name="sku",
            is_key=True,
            participates_in_statistics=True,
        )
        for day in (1, 2)
    ]

    result = _service(FakeSession(rows)).compose_published_schema(_scope())

    assert [column.column_id for column in result] == [SKU]


def test_schema_union_rejects_stable_id_metadata_conflict() -> None:
    rows = [
        _column(
            report_date=date(2026, 8, 1),
            version_id=101,
            column_id=SKU,
            source_header="SKU",
            display_order=1,
            standard_field_name="sku",
            is_key=True,
        ),
        _column(
            report_date=date(2026, 8, 2),
            version_id=102,
            column_id=SKU,
            source_header="Seller SKU",
            display_order=3,
            standard_field_name="sku",
            is_key=True,
        ),
    ]

    with pytest.raises(PublishedSchemaIntegrityError) as caught:
        _service(FakeSession(rows)).compose_published_schema(_scope())

    assert caught.value.code == "published_schema_integrity_error"


def test_resolve_scope_uses_only_current_pointer_rows_for_the_single_site() -> None:
    site_rows = [{"site_id": 3, "current_config_version_id": 31, "config_id": 31}]
    pointer_rows = [
        {
            "dataset_id": 11,
            "site_id": 3,
            "report_date": date(2026, 8, 1),
            "report_type": "business_report",
            "version_id": 201,
            "published_at": datetime(2026, 8, 3),
        },
        {
            "dataset_id": 12,
            "site_id": 3,
            "report_date": date(2026, 8, 2),
            "report_type": "business_report",
            "version_id": 102,
            "published_at": datetime(2026, 8, 2),
        },
    ]
    session = FakeSession(site_rows, pointer_rows)

    scope = _service(session).resolve_publication_scope(
        _principal(),
        "business_report",
        date(2026, 8, 1),
        date(2026, 8, 2),
    )

    assert scope.roles == ("viewer",)
    assert scope.site_id == 3
    assert [item.version_id for item in scope.publications] == [201, 102]
    pointer_sql, parameters = session.executions[1]
    assert "dataset_publications" in pointer_sql
    assert "dataset_versions" in pointer_sql
    assert "dataset_drafts" not in pointer_sql
    assert parameters == {
        "site_id": 3,
        "report_type": "business_report",
        "from_date": date(2026, 8, 1),
        "to_date": date(2026, 8, 2),
    }


def test_scope_resolution_rejects_ambiguous_active_site_configuration() -> None:
    service = _service(
        FakeSession(
            [
                {"site_id": 3, "current_config_version_id": 31, "config_id": 31},
                {"site_id": 4, "current_config_version_id": 41, "config_id": 41},
            ]
        )
    )

    with pytest.raises(PublishedSiteConfigurationError) as caught:
        service.resolve_publication_scope(
            _principal(),
            "business_report",
            date(2026, 8, 1),
            date(2026, 8, 2),
        )

    assert caught.value.code == "published_site_configuration_invalid"


def test_scope_resolution_rejects_active_site_without_current_configuration() -> None:
    service = _service(
        FakeSession(
            [
                {
                    "site_id": 3,
                    "current_config_version_id": None,
                    "config_id": None,
                }
            ]
        )
    )

    with pytest.raises(PublishedSiteConfigurationError):
        service.resolve_publication_scope(
            _principal(),
            "business_report",
            date(2026, 8, 1),
            date(2026, 8, 2),
        )


@pytest.mark.parametrize(
    ("range_rows", "expected"),
    [
        ([{"from_date": date(2026, 8, 1)}], (date(2026, 8, 1), date(2026, 8, 2))),
        ([{"from_date": None}], (None, None)),
    ],
)
def test_full_range_uses_current_pointers_and_is_empty_when_none_exist(
    range_rows: list[dict[str, object]],
    expected: tuple[date | None, date | None],
) -> None:
    session = FakeSession(
        [{"site_id": 3, "current_config_version_id": 31, "config_id": 31}],
        range_rows,
    )

    result = _service(session).resolve_full_range(
        _principal(), "business_report", date(2026, 8, 2)
    )

    assert (result.from_date, result.to_date) == expected
    range_sql = session.executions[1][0]
    assert "MIN(datasets.report_date)" in range_sql
    assert "dataset_publications" in range_sql


@pytest.mark.parametrize(
    "current_rows",
    [
        [],
        [
            {
                "dataset_id": 11,
                "site_id": 3,
                "report_date": date(2026, 8, 1),
                "report_type": "business_report",
                "version_id": 999,
                "published_at": datetime(2026, 8, 1),
            },
            {
                "dataset_id": 12,
                "site_id": 3,
                "report_date": date(2026, 8, 2),
                "report_type": "business_report",
                "version_id": 102,
                "published_at": datetime(2026, 8, 2),
            },
        ],
        [
            {
                "dataset_id": 11,
                "site_id": 3,
                "report_date": date(2026, 8, 1),
                "report_type": "business_report",
                "version_id": 101,
                "published_at": datetime(2026, 8, 1),
            },
            {
                "dataset_id": 12,
                "site_id": 3,
                "report_date": date(2026, 8, 2),
                "report_type": "business_report",
                "version_id": 102,
                "published_at": datetime(2026, 8, 2),
            },
            {
                "dataset_id": 13,
                "site_id": 3,
                "report_date": date(2026, 8, 2),
                "report_type": "business_report",
                "version_id": 103,
                "published_at": datetime(2026, 8, 2),
            },
        ],
    ],
    ids=("removed", "changed", "added"),
)
def test_assert_scope_current_rejects_any_pointer_set_change(
    current_rows: list[dict[str, object]],
) -> None:
    with pytest.raises(PublicationScopeChanged) as caught:
        _service(
            FakeSession(
                [
                    {
                        "site_id": 3,
                        "current_config_version_id": 31,
                        "config_id": 31,
                    }
                ],
                current_rows,
            )
        ).assert_scope_current(_scope())

    assert caught.value.code == "publication_scope_changed"


def test_assert_scope_current_accepts_exact_ordered_pointer_set() -> None:
    current_rows = [
        {
            "dataset_id": publication.dataset_id,
            "site_id": publication.site_id,
            "report_date": publication.report_date,
            "report_type": publication.report_type,
            "version_id": publication.version_id,
            "published_at": publication.published_at.replace(tzinfo=None),
        }
        for publication in _scope().publications
    ]

    _service(
        FakeSession(
            [
                {
                    "site_id": 3,
                    "current_config_version_id": 31,
                    "config_id": 31,
                }
            ],
            current_rows,
        )
    ).assert_scope_current(_scope())


def test_assert_scope_current_rejects_non_current_site_before_pointer_read() -> None:
    session = FakeSession(
        [{"site_id": 4, "current_config_version_id": 41, "config_id": 41}]
    )
    service = _service(session)

    with pytest.raises(PublicationScopeChanged):
        service.assert_scope_current(_scope())

    assert len(session.executions) == 1
