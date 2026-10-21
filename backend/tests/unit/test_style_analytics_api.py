from __future__ import annotations

from datetime import date
from typing import cast

import pytest
from app.analytics.style_repository import (
    AnalyticsCatalogVersionRequired,
    AnalyticsDateRangeInvalid,
    AnalyticsDimensionParameterInvalid,
    AnalyticsIdentityFactCombinationInvalid,
    AnalyticsSeriesInvalid,
    CatalogColorNotFound,
    CatalogSnapshotRangeOutOfBounds,
    CatalogStyleNotFound,
)
from app.api.errors import ApiError
from app.api.style_analytics import (
    _analytics_error,
    _analytics_permissions,
    _parse_card_query,
    _parse_ledger_query,
    router,
)
from app.site_context import CurrentSiteContext
from fastapi.routing import APIRoute


def _context(*roles: str) -> CurrentSiteContext:
    return CurrentSiteContext(
        principal_user_id=7,
        principal_roles=frozenset(roles),
        site_id=1,
        site_code="primary",
        site_display_name="Primary",
        site_config_version_id=3,
        site_config_revision=2,
        source_timezone="UTC",
        reporting_timezone="UTC",
        currency_code="USD",
    )


def _error_detail(error: ApiError) -> dict[str, str]:
    return cast(dict[str, str], cast(object, error.detail))


def test_new_style_routes_have_unambiguous_paths() -> None:
    operations = {
        (route.path, method)
        for route in router.routes
        if isinstance(route, APIRoute)
        for method in (route.methods or set())
    }
    assert operations == {
        ("/api/dashboard/style-ledger", "GET"),
        ("/api/dashboard/style-readiness", "GET"),
        ("/api/dashboard/styles/{style_id}/card", "GET"),
    }


@pytest.mark.parametrize(
    ("overrides", "expected"),
    [
        ({}, ("units", "desc", 1, 50, "current", "event_date")),
        (
            {
                "search": "  jacket  ",
                "sort": "sales",
                "direction": "asc",
                "page": "2",
                "page_size": "100",
                "catalog_version": "19",
                "fact_basis": "catalog_snapshot",
                "return_basis": "report_date",
            },
            ("sales", "asc", 2, 100, "catalog_snapshot", "report_date"),
        ),
    ],
)
def test_ledger_query_parser_preserves_the_frozen_parameter_table(
    overrides: dict[str, str], expected: tuple[object, ...]
) -> None:
    query = _parse_ledger_query(
        context=_context("data_manager"),
        from_value="2026-08-01",
        to_value="2026-08-24",
        search=overrides.get("search"),
        sort=overrides.get("sort", "units"),
        direction=overrides.get("direction", "desc"),
        page=overrides.get("page", "1"),
        page_size=overrides.get("page_size", "50"),
        catalog_version=overrides.get("catalog_version"),
        fact_basis=overrides.get("fact_basis", "current"),
        return_basis=overrides.get("return_basis", "event_date"),
    )
    assert (
        query.sort,
        query.direction,
        query.page,
        query.page_size,
        query.fact_basis,
        query.return_basis,
    ) == expected
    assert query.search == ("jacket" if overrides else None)
    assert query.catalog_version_id == (19 if overrides else None)


@pytest.mark.parametrize(
    "overrides",
    [
        {"from_value": "not-a-date"},
        {"from_value": "2026-08-24", "to_value": "2026-08-01"},
        {"search": "x" * 101},
        {"sort": "unknown"},
        {"direction": "sideways"},
        {"page": "0"},
        {"page_size": "101"},
        {"catalog_version": "0"},
        {"fact_basis": "unknown"},
        {"return_basis": "unknown"},
    ],
)
def test_invalid_ledger_parameters_use_stable_analytics_errors(
    overrides: dict[str, str],
) -> None:
    with pytest.raises(ApiError) as caught:
        _parse_ledger_query(
            context=_context("data_manager"),
            from_value=overrides.get("from_value", "2026-08-01"),
            to_value=overrides.get("to_value", "2026-08-24"),
            search=overrides.get("search"),
            sort=overrides.get("sort", "units"),
            direction=overrides.get("direction", "desc"),
            page=overrides.get("page", "1"),
            page_size=overrides.get("page_size", "50"),
            catalog_version=overrides.get("catalog_version"),
            fact_basis=overrides.get("fact_basis", "current"),
            return_basis=overrides.get("return_basis", "event_date"),
        )
    assert caught.value.status_code == 422
    assert _error_detail(caught.value)["code"] in {
        "analytics_date_range_invalid",
        "analytics_parameter_invalid",
    }


def test_card_parser_rejects_empty_duplicate_and_overflow_series() -> None:
    for series in ("", "same,same", ",", ",".join(f"k{i}" for i in range(9))):
        with pytest.raises(ApiError) as caught:
            _parse_card_query(
                context=_context("viewer"),
                style_id="7",
                from_value="2026-08-01",
                to_value="2026-08-24",
                series=series,
            )
        assert _error_detail(caught.value)["code"] == "analytics_series_invalid"


def test_history_permission_is_derived_only_from_current_site_context() -> None:
    viewer = _analytics_permissions(_context("viewer"))
    manager = _analytics_permissions(_context("data_manager"))
    admin = _analytics_permissions(_context("admin"))
    assert viewer.can_view_catalog_history is False
    assert manager.can_view_catalog_history is True
    assert manager.can_approve_high_risk is False
    assert admin.can_approve_high_risk is True


def test_viewer_catalog_snapshot_is_forbidden_before_repository_access() -> None:
    with pytest.raises(ApiError) as caught:
        _parse_ledger_query(
            context=_context("viewer"),
            from_value="2026-08-01",
            to_value="2026-08-24",
            catalog_version="19",
            fact_basis="catalog_snapshot",
        )
    assert caught.value.status_code == 403
    assert _error_detail(caught.value)["code"] == "catalog_history_forbidden"


@pytest.mark.parametrize(
    ("error", "status", "code"),
    [
        (AnalyticsDateRangeInvalid(), 422, "analytics_date_range_invalid"),
        (AnalyticsCatalogVersionRequired(), 422, "analytics_catalog_version_required"),
        (
            AnalyticsIdentityFactCombinationInvalid(),
            409,
            "analytics_identity_fact_combination_invalid",
        ),
        (
            CatalogSnapshotRangeOutOfBounds(),
            409,
            "catalog_snapshot_range_out_of_bounds",
        ),
        (CatalogStyleNotFound(), 404, "catalog_style_not_found"),
        (
            AnalyticsDimensionParameterInvalid(),
            422,
            "analytics_dimension_parameter_invalid",
        ),
        (CatalogColorNotFound(), 404, "catalog_color_not_found"),
        (AnalyticsSeriesInvalid(), 422, "analytics_series_invalid"),
    ],
)
def test_repository_errors_have_safe_stable_http_mapping(
    error: Exception, status: int, code: str
) -> None:
    mapped = _analytics_error(error)
    assert mapped.status_code == status
    assert _error_detail(mapped)["code"] == code


def test_card_parser_uses_stable_id_as_string_input_without_style_code_guessing() -> (
    None
):
    query = _parse_card_query(
        context=_context("viewer"),
        style_id="2301",
        from_value=date(2026, 8, 1).isoformat(),
        to_value=date(2026, 8, 24).isoformat(),
    )
    assert query.style_id == 2301
