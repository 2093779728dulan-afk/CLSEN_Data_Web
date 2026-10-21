from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Callable
from pathlib import Path
from typing import Any, cast

import pytest
from app.api.dependencies import (
    require_csrf_principal,
    require_principal,
    require_request_principal,
)
from app.config import Settings
from app.main import create_app
from fastapi import APIRouter, FastAPI
from fastapi.routing import APIRoute
from fastapi.testclient import TestClient

_SESSION_SECURITY: list[dict[str, list[str]]] = [{"SessionCookie": []}]
_REPOSITORY_ROOT = Path(__file__).resolve().parents[3]
_GENERATED_TYPES = _REPOSITORY_ROOT / "frontend" / "src" / "api" / "generated.ts"


@pytest.fixture(scope="module")
def application() -> FastAPI:
    return create_app(
        settings=Settings(
            environment="test",
            log_level="CRITICAL",
            cors_allowed_origins=(),
            session_secret="openapi-contract-test-secret-000000",
            session_cookie_secure=False,
        )
    )


@pytest.fixture(scope="module")
def schema(application: FastAPI) -> dict[str, Any]:
    return application.openapi()


def _operation(
    schema: dict[str, Any],
    path: str,
    method: str,
) -> dict[str, Any]:
    return cast(dict[str, Any], schema["paths"][path][method.lower()])


def _api_operations(
    schema: dict[str, Any],
) -> dict[tuple[str, str], dict[str, Any]]:
    result: dict[tuple[str, str], dict[str, Any]] = {}
    for path, path_item in schema["paths"].items():
        for method, operation in path_item.items():
            if method in {"delete", "get", "patch", "post", "put"}:
                result[(path, method)] = cast(dict[str, Any], operation)
    return result


def _parameter(
    operation: dict[str, Any],
    name: str,
    location: str,
) -> dict[str, Any]:
    matches = [
        parameter
        for parameter in operation.get("parameters", [])
        if parameter.get("name") == name and parameter.get("in") == location
    ]
    assert len(matches) == 1
    return cast(dict[str, Any], matches[0])


def _request_schema(operation: dict[str, Any]) -> dict[str, Any]:
    return cast(
        dict[str, Any],
        operation["requestBody"]["content"]["application/json"]["schema"],
    )


def _response_schema(
    operation: dict[str, Any],
    status_code: str,
) -> dict[str, Any]:
    return cast(
        dict[str, Any],
        operation["responses"][status_code]["content"]["application/json"]["schema"],
    )


def _route(application: FastAPI, path: str, method: str) -> APIRoute:
    pending = list(application.routes)
    while pending:
        route = pending.pop()
        if (
            isinstance(route, APIRoute)
            and route.path == path
            and method.upper() in (route.methods or set())
        ):
            return route
        original_router = getattr(route, "original_router", None)
        if isinstance(original_router, APIRouter):
            pending.extend(original_router.routes)
    raise AssertionError(f"route not found: {method} {path}")


def _dependency_calls(route: APIRoute) -> set[Callable[..., object]]:
    calls: set[Callable[..., object]] = set()
    pending = list(route.dependant.dependencies)
    while pending:
        dependency = pending.pop()
        if dependency.call is not None:
            calls.add(cast(Callable[..., object], dependency.call))
        pending.extend(dependency.dependencies)
    return calls


def _required_role_sets(route: APIRoute) -> set[frozenset[str]]:
    result: set[frozenset[str]] = set()
    for dependency in route.dependant.dependencies:
        call = dependency.call
        roles = getattr(call, "required_roles", None)
        if isinstance(roles, frozenset) and all(
            isinstance(role, str) for role in roles
        ):
            result.add(roles)
    return result


def test_session_authentication_is_visible_in_openapi(
    schema: dict[str, Any],
) -> None:
    assert schema["components"]["securitySchemes"] == {
        "SessionCookie": {
            "type": "apiKey",
            "description": "HttpOnly same-origin application session cookie.",
            "in": "cookie",
            "name": "clsen_session",
        }
    }

    for path, method in (
        ("/api/auth/csrf", "get"),
        ("/api/auth/login", "post"),
        ("/api/health/live", "get"),
    ):
        assert _operation(schema, path, method).get("security") is None

    for path, method in (
        ("/api/auth/me", "get"),
        ("/api/data-calendar", "get"),
        ("/api/data-calendar/days", "get"),
        ("/api/imports", "post"),
        ("/api/imports/batch-reviews", "get"),
        ("/api/imports/batch-reviews/preflight", "post"),
        ("/api/imports/batch-reviews/{run_id}", "get"),
        ("/api/imports/batch-reviews/{run_id}/confirm", "post"),
        ("/api/imports/batch-reviews/{run_id}/items/{item_id}/advance", "post"),
        ("/api/imports/batch-reviews/{run_id}/pause", "post"),
        ("/api/imports/batch-reviews/{run_id}/resume", "post"),
        ("/api/imports/batch-reviews/{run_id}/items/{item_id}/retry", "post"),
        ("/api/drafts/{version_id}/fields", "post"),
        ("/api/dashboard/summary", "get"),
    ):
        assert _operation(schema, path, method)["security"] == _SESSION_SECURITY


def test_auth_calendar_and_dashboard_shapes_are_stable(
    schema: dict[str, Any],
) -> None:
    login = _operation(schema, "/api/auth/login", "post")
    assert _request_schema(login) == {"$ref": "#/components/schemas/LoginRequest"}
    assert _response_schema(login, "200") == {
        "$ref": "#/components/schemas/LoginResponse"
    }
    assert _parameter(login, "X-CSRF-Token", "header")["schema"]["anyOf"] == [
        {"type": "string"},
        {"type": "null"},
    ]
    assert _parameter(login, "X-CSRF-Token", "header")["description"] == (
        "CSRF proof required for state-changing requests; missing or invalid values "
        "return HTTP 403."
    )

    calendar = _operation(schema, "/api/data-calendar", "get")
    for name in ("from", "to"):
        parameter = _parameter(calendar, name, "query")
        assert parameter["required"] is True
        assert parameter["schema"]["format"] == "date"
    calendar_response = _response_schema(calendar, "200")
    assert calendar_response["type"] == "array"
    assert calendar_response["items"] == {
        "$ref": "#/components/schemas/CalendarEntryResponse"
    }

    calendar_days = _operation(schema, "/api/data-calendar/days", "get")
    for name in ("from", "to"):
        parameter = _parameter(calendar_days, name, "query")
        assert parameter["required"] is True
        assert parameter["schema"]["format"] == "date"
    calendar_days_response = _response_schema(calendar_days, "200")
    assert calendar_days_response["type"] == "array"
    assert calendar_days_response["items"] == {
        "$ref": "#/components/schemas/CalendarDayResponse"
    }

    summary = _operation(schema, "/api/dashboard/summary", "get")
    assert _response_schema(summary, "200") == {
        "$ref": "#/components/schemas/DashboardSummary"
    }
    products = _operation(schema, "/api/dashboard/products", "get")
    assert _response_schema(products, "200") == {
        "$ref": "#/components/schemas/ProductDashboard"
    }
    returns = _operation(schema, "/api/dashboard/returns", "get")
    assert _response_schema(returns, "200") == {
        "$ref": "#/components/schemas/ReturnDashboard"
    }
    assert _parameter(returns, "basis", "query")["schema"]["enum"] == [
        "report_date",
        "event_date",
    ]

    dashboard_schemas = schema["components"]["schemas"]
    for name in ("DashboardSummary", "ProductDashboard", "ReturnDashboard"):
        dashboard_schema = dashboard_schemas[name]
        assert dashboard_schema["properties"]["publications"]["items"] == {
            "$ref": "#/components/schemas/PublicationReference"
        }
        assert dashboard_schema["properties"]["site_config_versions"]["items"] == {
            "$ref": "#/components/schemas/SiteConfigurationReference"
        }
        assert {"publications", "site_config_versions"} <= set(
            dashboard_schema["required"]
        )


def test_undoable_published_move_read_contract_is_complete(
    schema: dict[str, Any],
) -> None:
    operation = _operation(
        schema,
        "/api/admin/published-moves/undoable",
        "get",
    )
    assert operation["security"] == _SESSION_SECURITY
    response = _response_schema(operation, "200")
    assert response == {
        "items": {"$ref": "#/components/schemas/UndoablePublishedMoveResponse"},
        "type": "array",
        "title": (
            "Response List Undoable Published Moves Api Admin Published Moves "
            "Undoable Get"
        ),
    }
    candidate = schema["components"]["schemas"]["UndoablePublishedMoveResponse"]
    assert set(candidate["required"]) == {
        "move_command_id",
        "source_dataset_id",
        "source_report_date",
        "restore_source_version_id",
        "source_current_publication",
        "target_dataset_id",
        "target_report_date",
        "restore_target_version_id",
        "target_current_publication",
        "moved_target_version_id",
        "completed_at",
        "report_type",
    }
    pointer = schema["components"]["schemas"]["PublicationPointerSnapshotResponse"]
    assert set(pointer["required"]) == {"version_id", "published_at"}


def test_all_write_operations_expose_csrf_and_expected_idempotency(
    schema: dict[str, Any],
) -> None:
    non_idempotent_writes = {
        ("/api/auth/login", "post"),
        ("/api/auth/logout", "post"),
        ("/api/imports", "post"),
        ("/api/imports/{batch_id}/inspect", "post"),
    }
    write_methods = {"delete", "patch", "post", "put"}
    writes = {
        key: operation
        for key, operation in _api_operations(schema).items()
        if key[1] in write_methods
    }
    assert non_idempotent_writes <= writes.keys()

    for (path, method), operation in writes.items():
        csrf = _parameter(operation, "X-CSRF-Token", "header")
        assert csrf["description"] == (
            "CSRF proof required for state-changing requests; missing or invalid "
            "values return HTTP 403."
        )
        if path != "/api/auth/login":
            assert operation["security"] == _SESSION_SECURITY

        headers = {
            parameter["name"]: parameter
            for parameter in operation.get("parameters", [])
            if parameter.get("in") == "header"
        }
        if (path, method) in non_idempotent_writes:
            assert "Idempotency-Key" not in headers
            continue
        idempotency_key = headers["Idempotency-Key"]
        assert idempotency_key["required"] is True
        assert idempotency_key["schema"]["format"] == "uuid"


def test_import_and_review_payload_shapes_are_stable(
    schema: dict[str, Any],
) -> None:

    upload = _operation(schema, "/api/imports", "post")
    assert upload["requestBody"] == {
        "required": True,
        "content": {"text/csv": {"schema": {"type": "string", "format": "binary"}}},
    }
    original_filename = _parameter(upload, "X-Original-Filename", "header")
    assert original_filename["description"] == (
        "Original filename percent-encoded as UTF-8."
    )
    assert _response_schema(upload, "201") == {
        "$ref": "#/components/schemas/UploadResponse"
    }
    upload_config = _parameter(upload, "site_config_version_id", "query")
    assert upload_config["required"] is False
    assert upload_config["schema"]["anyOf"] == [
        {"type": "integer", "minimum": 1},
        {"type": "null"},
    ]

    confirm_parse = schema["components"]["schemas"]["ConfirmParseRequest"]
    assert "site_config_version_id" not in confirm_parse["required"]
    assert confirm_parse["properties"]["site_config_version_id"]["anyOf"] == [
        {"type": "integer", "minimum": 1.0},
        {"type": "null"},
    ]

    raw_file = _operation(schema, "/api/imports/{batch_id}/raw-file", "get")
    raw_file_response = raw_file["responses"]["200"]
    assert raw_file_response["description"] == (
        "Integrity-checked immutable source file."
    )
    assert raw_file_response["content"] == {
        "text/csv": {"schema": {"type": "string", "format": "binary"}},
        "application/octet-stream": {"schema": {"type": "string", "format": "binary"}},
    }

    set_field = _operation(schema, "/api/drafts/{version_id}/fields", "post")
    assert _request_schema(set_field) == {
        "$ref": "#/components/schemas/SetFieldRequest"
    }
    mark_ready = _operation(
        schema,
        "/api/drafts/{version_id}/mark-ready",
        "post",
    )
    assert _request_schema(mark_ready) == {
        "$ref": "#/components/schemas/MarkReadyRequest"
    }

    batch_note = schema["components"]["schemas"]["CreateImportBatchNoteRequest"]
    assert batch_note["properties"]["visibility"] == {
        "type": "string",
        "const": "internal",
        "title": "Visibility",
        "default": "internal",
    }
    list_batch_notes = _operation(schema, "/api/imports/{batch_id}/notes", "get")
    assert all(
        parameter.get("name") != "X-CSRF-Token"
        for parameter in list_batch_notes.get("parameters", [])
    )

    merge_preview = _operation(schema, "/api/datasets/merge-preview", "get")
    assert _response_schema(merge_preview, "200") == {
        "$ref": "#/components/schemas/MergePreviewResponse"
    }
    assert _parameter(merge_preview, "source_kind", "query")["schema"] == {
        "type": "string",
        "enum": ["parse_baseline", "dataset_version"],
        "title": "Source Kind",
    }

    workspace = _operation(
        schema,
        "/api/drafts/{version_id}/review-workspace",
        "get",
    )
    assert _response_schema(workspace, "200") == {
        "$ref": "#/components/schemas/ReviewWorkspaceResponse"
    }
    workspace_schema = schema["components"]["schemas"]["ReviewWorkspaceResponse"]
    assert "source_batches" in workspace_schema["required"]
    assert workspace_schema["properties"]["source_batches"] == {
        "items": {"$ref": "#/components/schemas/SourceBatchResponse"},
        "type": "array",
        "title": "Source Batches",
    }
    assert _parameter(workspace, "row_state", "query")["schema"]["anyOf"][0][
        "enum"
    ] == ["active", "excluded", "deleted"]
    page_size = _parameter(workspace, "page_size", "query")["schema"]
    assert page_size["minimum"] == 1
    assert page_size["maximum"] == 100
    assert page_size["default"] == 50


def test_validation_errors_use_the_shared_public_envelope(
    schema: dict[str, Any],
) -> None:
    error_detail = schema["components"]["schemas"]["ApiErrorDetail"]
    assert error_detail["required"] == [
        "code",
        "message",
        "request_id",
    ]
    assert error_detail["properties"] == {
        "code": {"type": "string", "title": "Code"},
        "message": {"type": "string", "title": "Message"},
        "request_id": {"type": "string", "title": "Request Id"},
    }
    assert schema["components"]["schemas"]["ApiErrorResponse"] == {
        "properties": {
            "error": {"$ref": "#/components/schemas/ApiErrorDetail"},
        },
        "type": "object",
        "required": ["error"],
        "title": "ApiErrorResponse",
        "description": (
            "Shared error envelope rendered by application exception handlers."
        ),
    }

    for operation in _api_operations(schema).values():
        validation_error = operation["responses"]["422"]
        assert validation_error["content"]["application/json"]["schema"] == {
            "$ref": "#/components/schemas/ApiErrorResponse"
        }


def test_runtime_validation_error_matches_the_documented_envelope(
    application: FastAPI,
) -> None:
    @application.get("/api/testing/contract-validation", include_in_schema=False)
    def validation_probe(required_integer: int) -> dict[str, int]:
        return {"required_integer": required_integer}

    with TestClient(application) as client:
        response = client.get(
            "/api/testing/contract-validation",
            params={"required_integer": "not-an-integer"},
        )

    assert response.status_code == 422
    payload = response.json()
    assert payload["error"]["code"] == "validation_error"
    assert payload["error"]["message"] == "The request data is invalid."
    assert isinstance(payload["error"]["request_id"], str)


def test_server_side_permission_dependencies_are_part_of_route_contract(
    application: FastAPI,
) -> None:
    public_routes = {
        ("/api/auth/csrf", "get"),
        ("/api/auth/login", "post"),
        ("/api/health/live", "get"),
        ("/api/health/ready", "get"),
    }
    openapi = application.openapi()
    for path, method in _api_operations(openapi):
        if (path, method) in public_routes:
            continue
        authentication_dependency = (
            require_request_principal
            if path.startswith("/api/published-details")
            else require_principal
        )
        assert authentication_dependency in _dependency_calls(
            _route(application, path, method)
        )

    write_methods = {"delete", "patch", "post", "put"}
    for path, method in _api_operations(openapi):
        if method not in write_methods or path == "/api/auth/login":
            continue
        assert require_csrf_principal in _dependency_calls(
            _route(application, path, method)
        )

    admin_routes = {
        ("/api/admin/roles", "get"),
        ("/api/admin/maintenance", "get"),
        ("/api/admin/users", "get"),
        ("/api/admin/users", "post"),
        ("/api/admin/users/{user_id}", "patch"),
        ("/api/admin/site-config-versions", "get"),
        ("/api/admin/site-config-versions", "post"),
        ("/api/admin/audit-events", "get"),
        ("/api/admin/drafts/{version_id}/force-rebuild", "post"),
        ("/api/admin/datasets/{dataset_id}/rollback", "post"),
        ("/api/admin/published-moves/undoable", "get"),
        ("/api/admin/versions/{version_id}/move-date", "post"),
        (
            "/api/admin/published-moves/{move_revision_operation_token}/finalize",
            "post",
        ),
        ("/api/admin/published-moves/{move_command_id}/undo", "post"),
    }
    manager_routes = {
        ("/api/publications/return-initialization", "get"),
        ("/api/publications/return-initialization", "post"),
        ("/api/catalog/return-dedup/groups", "get"),
        ("/api/catalog/return-dedup/groups/{group_id}/decision", "post"),
        ("/api/publications/return-dedup-staging", "post"),
        ("/api/publications/return-dedup-staging/{job_id}", "get"),
        (
            "/api/publications/return-dedup-staging/{job_id}/retry",
            "post",
        ),
        ("/api/datasets/merge-preview", "get"),
        ("/api/datasets/materialize", "post"),
        ("/api/drafts/{version_id}", "get"),
        ("/api/drafts/{version_id}/discard", "post"),
        ("/api/drafts/{version_id}/reassign-date", "post"),
        ("/api/drafts/{version_id}/review-workspace", "get"),
        ("/api/imports", "post"),
        ("/api/imports/batch-reviews", "get"),
        ("/api/imports/batch-reviews/preflight", "post"),
        ("/api/imports/batch-reviews/{run_id}", "get"),
        ("/api/imports/batch-reviews/{run_id}/confirm", "post"),
        ("/api/imports/batch-reviews/{run_id}/items/{item_id}/advance", "post"),
        ("/api/imports/batch-reviews/{run_id}/pause", "post"),
        ("/api/imports/batch-reviews/{run_id}/resume", "post"),
        ("/api/imports/batch-reviews/{run_id}/items/{item_id}/retry", "post"),
        ("/api/imports/{batch_id}/inspect", "post"),
        ("/api/imports/{batch_id}/confirm-parse", "post"),
        ("/api/imports/{batch_id}/change-date", "post"),
        ("/api/workbench/imports", "post"),
        ("/api/workbench/imports/pending", "get"),
        ("/api/workbench/imports/{batch_id}", "get"),
        ("/api/workbench/imports/{batch_id}/confirm", "post"),
        ("/api/imports/{batch_id}/notes", "get"),
        ("/api/imports/{batch_id}/notes", "post"),
        ("/api/imports/{batch_id}/notes/{note_key}/revisions", "post"),
        ("/api/datasets/{dataset_id}/publish", "post"),
        ("/api/datasets/{dataset_id}/revisions", "post"),
        ("/api/imports/{batch_id}/raw-file", "get"),
        ("/api/imports/{batch_id}/raw-file/preview", "get"),
        ("/api/drafts/{version_id}/fields", "post"),
        ("/api/drafts/{version_id}/fields/{field_name}/restore", "post"),
        ("/api/drafts/{version_id}/rows", "post"),
        ("/api/drafts/{version_id}/rows/{row_id}/state", "post"),
        ("/api/drafts/{version_id}/notes", "post"),
        ("/api/drafts/{version_id}/notes/{note_key}/revisions", "post"),
        ("/api/drafts/{version_id}/issues/{issue_id}/review", "post"),
        ("/api/drafts/{version_id}/mark-ready", "post"),
        ("/api/drafts/{version_id}/return-to-draft", "post"),
        ("/api/validation-runs/{version_id}", "post"),
        (
            "/api/workbench/versions/{version_id}/rows/{row_id}/cells/{column_id}",
            "patch",
        ),
        ("/api/workbench/versions/{version_id}/undo", "post"),
        (
            "/api/workbench/dates/{report_date}/{report_type}/revision",
            "post",
        ),
        ("/api/workbench/versions/{version_id}/changes", "get"),
    }
    viewer_safe_routes = {
        ("/api/dashboard/style-readiness", "get"),
        ("/api/data-calendar/site-context", "get"),
        ("/api/dashboard/daily-ledger", "get"),
        ("/api/dashboard/product-card/{style_code}", "get"),
        ("/api/dashboard/product-ledger", "get"),
        ("/api/dashboard/style-ledger", "get"),
        ("/api/dashboard/styles/{style_id}/card", "get"),
        ("/api/dashboard/summary", "get"),
        ("/api/dashboard/products", "get"),
        ("/api/dashboard/returns", "get"),
        ("/api/published-details/export.csv", "get"),
        ("/api/published-details/range", "get"),
        ("/api/published-details/rows", "get"),
        ("/api/published-details/summaries", "get"),
        ("/api/versions", "get"),
        ("/api/versions/{version_id}", "get"),
        ("/api/versions/{version_id}/rows", "get"),
        ("/api/workbench/dates/{report_date}", "get"),
    }
    expected_roles = {
        **{route: frozenset({"admin"}) for route in admin_routes},
        **{route: frozenset({"admin", "data_manager"}) for route in manager_routes},
        **{
            route: frozenset({"admin", "data_manager", "viewer"})
            for route in viewer_safe_routes
        },
    }
    actual_role_routes = {
        (path, method)
        for path, method in _api_operations(openapi)
        if _required_role_sets(_route(application, path, method))
    }
    assert actual_role_routes == expected_roles.keys()
    for (path, method), roles in expected_roles.items():
        assert _required_role_sets(_route(application, path, method)) == {roles}


def test_style_analytics_openapi_keeps_new_and_legacy_resources_separate(
    schema: dict[str, Any],
) -> None:
    expected = {
        "/api/dashboard/product-ledger",
        "/api/dashboard/product-card/{style_code}",
        "/api/dashboard/style-ledger",
        "/api/dashboard/styles/{style_id}/card",
    }
    assert expected <= schema["paths"].keys()

    ledger = _operation(schema, "/api/dashboard/style-ledger", "get")
    card = _operation(schema, "/api/dashboard/styles/{style_id}/card", "get")
    assert [parameter["name"] for parameter in ledger["parameters"]] == [
        "from",
        "to",
        "category_id",
        "search",
        "sort",
        "direction",
        "page",
        "page_size",
        "catalog_version",
        "fact_basis",
        "return_basis",
    ]
    assert [parameter["name"] for parameter in card["parameters"]] == [
        "style_id",
        "from",
        "to",
        "metric",
        "dimension",
        "color_key",
        "series",
        "catalog_version",
        "fact_basis",
        "return_basis",
    ]
    assert _response_schema(ledger, "200") == {
        "$ref": "#/components/schemas/StyleLedgerResponse"
    }
    assert _response_schema(card, "200") == {
        "$ref": "#/components/schemas/StyleCardResponse"
    }
    for operation in (ledger, card):
        headers = operation["responses"]["200"]["headers"]
        assert headers["X-Identity-Source"]["schema"] == {
            "type": "string",
            "const": "p0_catalog",
        }
        assert headers["X-Identity-Version"]["schema"] == {"type": "string"}


def test_style_analytics_response_models_require_explicit_nullable_fields(
    schema: dict[str, Any],
) -> None:
    components = schema["components"]["schemas"]
    models = {
        "AnalyticsProvenance",
        "AvailableSeries",
        "CoverageBlock",
        "MetricEvaluability",
        "MetricTotals",
        "MetricValue",
        "MetricValues",
        "PublicationDay",
        "PublicationRefs",
        "app__analytics__style_models__SafeSourceRef",
        "SourceReportCoverage",
        "StyleCardResponse",
        "StyleIdentity",
        "StyleLedgerResponse",
        "StyleLedgerRow",
        "StyleReconciliation",
        "StyleVariant",
        "TrendPoint",
        "TrendSeries",
    }
    for name in models:
        component = components[name]
        assert set(component["required"]) == set(component["properties"]), name

    assert (
        _parameter(
            _operation(schema, "/api/dashboard/styles/{style_id}/card", "get"),
            "style_id",
            "path",
        )["schema"]["type"]
        == "string"
    )
    for model, fields in {
        "AnalyticsProvenance": {
            "catalog_version_id",
            "identity_version_id",
            "return_dedup_snapshot_id",
            "site_config_version_id",
        },
        "StyleIdentity": {"style_id"},
        "StyleLedgerRow": {"style_id"},
        "StyleVariant": {"sku_id"},
    }.items():
        for field in fields:
            assert components[model]["properties"][field]["type"] == "string"


def test_generated_types_match_the_current_openapi_schema(
    schema: dict[str, Any],
) -> None:
    canonical = json.dumps(
        schema,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    expected_digest = hashlib.sha256(canonical.encode("utf-8")).hexdigest()
    generated = _GENERATED_TYPES.read_text(encoding="utf-8")
    match = re.search(r"^// OpenAPI SHA-256: ([0-9a-f]{64})$", generated, re.MULTILINE)
    assert match is not None
    assert match.group(1) == expected_digest


def test_maintenance_openapi_appends_worker_observability_contract(
    schema: dict[str, Any],
) -> None:
    components = schema["components"]["schemas"]
    maintenance = components["MaintenanceStatusResponse"]
    assert list(maintenance["properties"]) == [
        "backups",
        "restores",
        "outbox",
        "write_lock",
        "observed_at",
        "maintenance_active",
        "worker",
        "queues",
    ]
    assert set(maintenance["required"]) == set(maintenance["properties"])
    assert maintenance["properties"]["worker"] == {
        "$ref": "#/components/schemas/WorkerFleetStatusResponse"
    }
    assert maintenance["properties"]["queues"] == {
        "items": {"$ref": "#/components/schemas/QueueStatusResponse"},
        "type": "array",
        "title": "Queues",
    }
    assert set(components["HeartbeatThresholdsResponse"]["required"]) == {
        "heartbeat_seconds",
        "stale_seconds",
        "offline_seconds",
        "refresh_seconds",
    }
    assert set(components["QueueStatusResponse"]["required"]) == set(
        components["QueueStatusResponse"]["properties"]
    )
