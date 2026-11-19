from typing import Any
from unittest.mock import MagicMock
from uuid import uuid4

import pytest
from app.api.errors import ApiError
from app.api.production import _directory_payload
from app.site_context import CurrentSiteContext


def context(role: str = "data_manager") -> Any:
    return CurrentSiteContext(
        principal_user_id=7,
        principal_roles=frozenset({role}),
        site_id=1,
        site_code="qa",
        site_display_name="QA",
        site_config_version_id=1,
        site_config_revision=1,
        source_timezone="UTC",
        reporting_timezone="UTC",
        currency_code="USD",
    )


def test_directory_scope_selection_is_validated_in_current_site() -> None:
    engine = MagicMock()
    connection = engine.connect.return_value.__enter__.return_value
    connection.execute.return_value.scalar.return_value = 9
    key = uuid4()
    result = _directory_payload(
        {
            "operation_token": str(key),
            "seller_account": "scope:9",
            "marketplace": "US",
            "name": "FBA QA",
        },
        key,
        context(),
        engine,
    )
    assert result["seller_account"] == "scope:9"
    assert any(
        call.args[1] == {"site": 1, "id": "9"}
        for call in connection.execute.call_args_list
    )
    connection.execute.return_value.scalar.return_value = None
    with pytest.raises(ApiError):
        _directory_payload(
            {
                "operation_token": str(key),
                "seller_account": "scope:9",
                "marketplace": "US",
            },
            key,
            context(),
            engine,
        )


def test_directory_scope_cannot_be_written_by_viewer_or_wrong_market() -> None:
    key = uuid4()
    engine = MagicMock()
    with pytest.raises(ApiError):
        _directory_payload(
            {
                "operation_token": str(key),
                "seller_account": "scope:9",
                "marketplace": "US",
            },
            key,
            context("viewer"),
            engine,
        )
    with pytest.raises(ApiError):
        _directory_payload(
            {
                "operation_token": str(key),
                "seller_account": "scope:9",
                "marketplace": "JP",
            },
            key,
            context(),
            engine,
        )
