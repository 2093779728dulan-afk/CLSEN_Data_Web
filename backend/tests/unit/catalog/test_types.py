from __future__ import annotations

from uuid import uuid4

import pytest
from app.catalog.models import StrictCatalogModel
from app.catalog.types import (
    CatalogCommandEnvelope,
    CatalogImportStatus,
    CatalogPermissions,
    CatalogReasonCode,
    CatalogSourceKind,
)
from pydantic import ValidationError


def test_catalog_enums_are_closed_and_stable() -> None:
    assert CatalogImportStatus.NEEDS_ATTENTION.value == "needs_attention"
    assert CatalogReasonCode.UNSAFE_SOURCE_TEXT.value == "unsafe_source_text"
    assert CatalogSourceKind.SELLER_SKU.value == "seller_sku"


def test_permissions_require_every_boolean_and_forbid_unknown_fields() -> None:
    permissions = CatalogPermissions(
        can_view_catalog_history=True,
        can_manage_catalog=False,
        can_view_evidence_history=True,
        can_download_original=False,
        can_submit=True,
        can_approve_normal=False,
        can_approve_high_risk=False,
    )

    assert permissions.model_dump()["can_submit"] is True
    with pytest.raises(ValidationError):
        CatalogPermissions.model_validate(
            {**permissions.model_dump(), "unexpected_permission": True}
        )
    with pytest.raises(ValidationError):
        CatalogPermissions.model_validate(
            {
                key: value
                for key, value in permissions.model_dump().items()
                if key != "can_submit"
            }
        )


def test_command_envelope_requires_uuid4_nonnegative_revision_and_strict_input() -> (
    None
):
    command = CatalogCommandEnvelope(
        operation_token=uuid4(),
        expected_revision=0,
    )

    assert command.expected_revision == 0
    with pytest.raises(ValidationError):
        CatalogCommandEnvelope(operation_token=uuid4(), expected_revision=-1)
    with pytest.raises(ValidationError):
        CatalogCommandEnvelope.model_validate(
            {"operation_token": str(uuid4()), "expected_revision": "0"}
        )


def test_all_catalog_models_share_the_fail_closed_configuration() -> None:
    assert StrictCatalogModel.model_config["extra"] == "forbid"
    assert StrictCatalogModel.model_config["frozen"] is True
    assert StrictCatalogModel.model_config["strict"] is True
    assert StrictCatalogModel.model_config["hide_input_in_errors"] is True
