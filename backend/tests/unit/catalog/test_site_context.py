from __future__ import annotations

import pytest
from app.auth.sessions import Principal
from app.site_context import (
    CurrentSiteContext,
    SiteContextUnavailable,
    resolve_current_site_context,
)


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


class _Session:
    def __init__(self, rows: list[dict[str, object]]) -> None:
        self.rows = rows
        self.statement = ""
        self.parameters: dict[str, object] = {}

    def execute(
        self,
        statement: object,
        parameters: dict[str, object] | None = None,
    ) -> _Result:
        self.statement = str(statement)
        self.parameters = parameters or {}
        return _Result(self.rows)


def _principal() -> Principal:
    return Principal(
        user_id=17,
        username="catalog-admin",
        display_name="Catalog Admin",
        roles=frozenset({"admin"}),
        session_id=23,
        csrf_token_hash=b"x" * 32,
    )


def _row() -> dict[str, object]:
    return {
        "site_id": 1,
        "site_code": "amazon_us",
        "site_display_name": "Amazon US",
        "site_config_version_id": 7,
        "site_config_revision": 4,
        "source_timezone": "America/Los_Angeles",
        "reporting_timezone": "America/Los_Angeles",
        "currency_code": "USD",
    }


@pytest.mark.parametrize("rows", [[], [_row(), {**_row(), "site_id": 2}]])
def test_current_site_context_fails_closed_without_exactly_one_active_site(
    rows: list[dict[str, object]],
) -> None:
    with pytest.raises(SiteContextUnavailable):
        resolve_current_site_context(_Session(rows), _principal())


def test_current_site_context_fails_closed_for_incomplete_or_inactive_config() -> None:
    incomplete = _row()
    incomplete["site_config_version_id"] = None
    with pytest.raises(SiteContextUnavailable):
        resolve_current_site_context(_Session([incomplete]), _principal())


def test_current_site_context_is_server_derived_and_immutable() -> None:
    session = _Session([_row()])
    context = resolve_current_site_context(session, _principal())

    assert context == CurrentSiteContext(
        principal_user_id=17,
        principal_roles=frozenset({"admin"}),
        site_id=1,
        site_code="amazon_us",
        site_display_name="Amazon US",
        site_config_version_id=7,
        site_config_revision=4,
        source_timezone="America/Los_Angeles",
        reporting_timezone="America/Los_Angeles",
        currency_code="USD",
    )
    assert "WHERE sites.status = 'active'" in session.statement
    assert "LIMIT 2" in session.statement
    assert "site_id" not in session.parameters
    with pytest.raises((AttributeError, TypeError)):
        context.site_id = 999  # type: ignore[misc]


def test_resolver_does_not_accept_a_client_site_override() -> None:
    with pytest.raises(TypeError):
        resolve_current_site_context(  # type: ignore[call-arg]
            _Session([_row()]),
            _principal(),
            site_id=999,
        )
