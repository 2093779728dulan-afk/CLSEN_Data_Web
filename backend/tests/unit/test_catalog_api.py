from __future__ import annotations

from unittest.mock import MagicMock
from uuid import uuid4

import pytest
from app.api.catalog_admin import router as admin_router
from app.api.catalog_changes import CategoryCreateRequest, CategoryUpdateRequest
from app.api.catalog_changes import router as changes_router
from app.api.catalog_dedup import router as dedup_router
from app.api.catalog_exports import (
    CreateCatalogExportRequest,
    ResumeCatalogExportRequest,
)
from app.api.catalog_exports import router as exports_router
from app.api.catalog_imports import (
    ApplyDecisionsRequest,
    ApproveImportRequest,
    ImportRevisionRequest,
)
from app.api.catalog_imports import router as imports_router
from app.api.catalog_queries import router as queries_router
from app.api.catalog_scope import ConfirmCatalogScopeRequest
from app.site_context import CurrentSiteContext
from pydantic import ValidationError


def _context(*roles: str) -> CurrentSiteContext:
    return CurrentSiteContext(
        principal_user_id=1,
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


def test_catalog_detail_exposes_bounded_safe_revision_issues() -> None:
    from app.api.catalog_imports import _detail

    engine = MagicMock()
    connection = engine.connect.return_value.__enter__.return_value
    detail = MagicMock()
    detail.mappings.return_value.one_or_none.return_value = {
        "id": 8,
        "status": "needs_attention",
        "source_kind": "online",
        "owner_user_id": 1,
        "submitted_by_user_id": None,
        "recoverable": False,
        "workflow_revision": 3,
        "parse_attempt_revision": 0,
        "export_id": 2,
        "base_catalog_version_id": None,
        "validation_run_id": None,
        "failure_reason_code": None,
        "raw_file_id": None,
        "catalog_publication_revision": 0,
    }
    issues = MagicMock()
    issues.mappings.return_value.all.return_value = [
        {
            "section": "skus",
            "row_key": "sku:1",
            "field": "/standard_size",
            "severity": "blocking",
            "reason_code": "required",
        }
    ]
    version = MagicMock()
    version.scalar_one_or_none.return_value = None
    connection.execute.side_effect = [detail, issues, version]
    result = _detail(
        engine,
        import_id=8,
        context=_context("admin"),
    )
    assert result["issues"] == issues.mappings.return_value.all.return_value
    query, bindings = connection.execute.call_args_list[1].args
    assert bindings == {"id": 8, "site_id": 1, "revision": 3}
    assert "workflow_revision <= :revision" in str(query)
    assert "LIMIT 500" in str(query)
    assert "safe_message" not in str(query)


def _operations(*routers: object) -> set[tuple[str, str]]:
    result: set[tuple[str, str]] = set()
    for router in routers:
        for route in getattr(router, "routes"):  # noqa: B009
            for method in getattr(route, "methods", set()):
                result.add((route.path, method))
    return result


def test_catalog_routers_expose_frozen_resource_surface() -> None:
    operations = _operations(
        admin_router,
        changes_router,
        dedup_router,
        exports_router,
        imports_router,
        queries_router,
    )
    expected = {
        ("/api/catalog/source-scope", "GET"),
        ("/api/catalog/source-scope/confirm", "POST"),
        ("/api/catalog/return-dedup/groups", "GET"),
        ("/api/catalog/return-dedup/groups/{group_id}/decision", "POST"),
        ("/api/catalog/exports", "POST"),
        ("/api/catalog/exports/latest", "GET"),
        ("/api/catalog/exports/{export_id}", "GET"),
        ("/api/catalog/exports/{export_id}/resume", "POST"),
        ("/api/catalog/exports/{export_id}/file", "GET"),
        ("/api/catalog/imports", "POST"),
        ("/api/catalog/imports/from-export", "POST"),
        ("/api/catalog/imports/{import_id}", "GET"),
        ("/api/catalog/imports/{import_id}/rows/{section}", "GET"),
        ("/api/catalog/imports/{import_id}/decisions", "POST"),
        ("/api/catalog/imports/{import_id}/validate", "POST"),
        ("/api/catalog/imports/{import_id}/submit", "POST"),
        ("/api/catalog/imports/{import_id}/approval-preview", "POST"),
        ("/api/catalog/imports/{import_id}/approve", "POST"),
        ("/api/catalog/imports/{import_id}/reject", "POST"),
        ("/api/catalog/imports/{import_id}/rebase", "POST"),
        ("/api/catalog/imports/{import_id}/withdraw", "POST"),
        ("/api/catalog/imports/{import_id}/resume", "POST"),
        ("/api/catalog/imports/{import_id}/file", "GET"),
        ("/api/catalog/styles", "GET"),
        ("/api/catalog/styles/{style_id}", "GET"),
        ("/api/catalog/styles/{style_id}/pending-items", "GET"),
        ("/api/catalog/categories", "GET"),
        ("/api/catalog/categories", "POST"),
        ("/api/catalog/categories/{category_id}", "PUT"),
        ("/api/catalog/styles/{style_id}/change-drafts", "POST"),
        ("/api/catalog/style-change-drafts/{draft_id}", "GET"),
        ("/api/catalog/style-change-drafts/{draft_id}/approve", "POST"),
        ("/api/catalog/variants/{sku_id}/seller-skus", "GET"),
        ("/api/catalog/variants/{sku_id}/evidence", "GET"),
        ("/api/catalog/unmatched", "GET"),
        ("/api/catalog/versions", "GET"),
        ("/api/catalog/versions/{version_id}/diff", "GET"),
        ("/api/catalog/versions/{version_id}/restore", "POST"),
        ("/api/catalog/evidence", "GET"),
        ("/api/catalog/source-identifiers/{source_ref_id}", "GET"),
        (
            "/api/catalog/imports/{import_id}/source-identifiers/{source_ref_id}",
            "GET",
        ),
        ("/api/catalog/commands/{operation_token}", "GET"),
        ("/api/catalog/admin/commands/{operation_token}/lookup", "POST"),
    }
    assert expected <= operations


def test_catalog_models_reject_extra_fields_and_invalid_counters() -> None:
    request = CreateCatalogExportRequest.model_validate(
        {
            "operation_token": str(uuid4()),
            "expected_catalog_publication_revision": 0,
        }
    )
    assert request.operation_token.version == 4
    decision_request = ApplyDecisionsRequest.model_validate(
        {
            "operation_token": str(uuid4()),
            "expected_workflow_revision": 0,
            "mutations": [
                {
                    "mutation_id": str(uuid4()),
                    "type": "update_style",
                    "row_key": "style-1",
                    "decision_group_key": None,
                    "payload": {"standard_name": "Standard name"},
                }
            ],
        }
    )
    assert isinstance(decision_request.mutations, tuple)
    with pytest.raises(ValidationError):
        CreateCatalogExportRequest.model_validate(
            {
                "operation_token": str(uuid4()),
                "expected_catalog_publication_revision": "0",
            }
        )
    with pytest.raises(ValidationError):
        ImportRevisionRequest(
            operation_token=uuid4(),
            expected_workflow_revision=-1,
        )
    with pytest.raises(ValidationError):
        ImportRevisionRequest.model_validate(
            {
                "operation_token": str(uuid4()),
                "expected_workflow_revision": 0,
                "site_id": 1,
            }
        )
    with pytest.raises(ValidationError):
        ApproveImportRequest(
            operation_token=uuid4(),
            expected_workflow_revision=2,
            expected_catalog_publication_revision=0,
            projection_id=1,
            projection_digest="sha256:not-a-digest",
            reason="A sufficiently long approval reason",
        )

    resume = ResumeCatalogExportRequest(
        operation_token=uuid4(),
        expected_job_revision=3,
    )
    assert resume.expected_job_revision == 3
    with pytest.raises(ValidationError):
        ResumeCatalogExportRequest(
            operation_token=uuid4(),
            expected_job_revision=-1,
        )


def test_category_requests_accept_json_alias_arrays() -> None:
    operation_token = str(uuid4())

    created = CategoryCreateRequest.model_validate(
        {
            "operation_token": operation_token,
            "code": "SHORTS",
            "display_name": "短裤",
            "aliases": [],
        }
    )
    updated = CategoryUpdateRequest.model_validate(
        {
            "operation_token": operation_token,
            "display_name": "短裤",
            "aliases": ["短装裤"],
            "status": "enabled",
        }
    )

    assert created.aliases == ()
    assert updated.aliases == ("短装裤",)


def test_scope_confirmation_requires_closed_marketplace_and_uuid4() -> None:
    request = ConfirmCatalogScopeRequest(
        operation_token=uuid4(),
        expected_site_config_revision=1,
        seller_account_scope_key="account-key",
        seller_account_display_name="Primary account",
        marketplace_scope_code="amazon_us",
        reason="Confirm the only configured seller account",
    )
    assert request.marketplace_scope_code == "amazon_us"
    with pytest.raises(ValidationError):
        ConfirmCatalogScopeRequest.model_validate(
            {
                "operation_token": str(uuid4()),
                "expected_site_config_revision": 1,
                "seller_account_scope_key": "account-key",
                "seller_account_display_name": "Primary account",
                "marketplace_scope_code": "amazon_ca",
                "reason": "Confirm the only configured seller account",
            }
        )
