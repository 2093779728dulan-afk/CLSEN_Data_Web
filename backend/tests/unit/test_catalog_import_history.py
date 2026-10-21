from unittest.mock import MagicMock

import pytest
from app.api.catalog_imports import list_catalog_imports
from app.api.errors import ApiError
from app.site_context import CurrentSiteContext


def _context(*roles: str, site_id: int = 1) -> CurrentSiteContext:
    return CurrentSiteContext(
        principal_user_id=7,
        principal_roles=frozenset(roles),
        site_id=site_id,
        site_code="primary",
        site_display_name="Primary",
        site_config_version_id=3,
        site_config_revision=2,
        source_timezone="UTC",
        reporting_timezone="UTC",
        currency_code="USD",
    )


def test_viewer_cannot_list_imports() -> None:
    engine = MagicMock()
    context = _context("viewer")
    with pytest.raises(ApiError):
        list_catalog_imports(context, engine, 1)
    engine.connect.assert_not_called()


def test_import_history_is_site_scoped_and_paginated() -> None:
    engine = MagicMock()
    connection = engine.connect.return_value.__enter__.return_value
    connection.execute.return_value.mappings.return_value.all.return_value = []
    context = _context("data_manager", site_id=5)
    list_catalog_imports(context, engine, 2)
    query, parameters = connection.execute.call_args.args
    assert "WHERE site_id = :site_id" in str(query)
    assert parameters == {"site_id": 5, "offset": 20}
