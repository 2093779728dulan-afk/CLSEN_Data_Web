from __future__ import annotations

from typing import cast

from app.api.catalog_common import catalog_error
from app.catalog.approval import CatalogProjectionStale
from app.catalog.import_repository import CatalogWorkflowRevisionConflict


def test_catalog_domain_errors_map_to_stable_safe_http_codes() -> None:
    workflow = catalog_error(CatalogWorkflowRevisionConflict())
    assert workflow.status_code == 409
    workflow_detail = cast(dict[str, str], cast(object, workflow.detail))
    assert workflow_detail["code"] == "catalog_workflow_revision_conflict"
    projection = catalog_error(CatalogProjectionStale())
    assert projection.status_code == 409
    projection_detail = cast(dict[str, str], cast(object, projection.detail))
    assert projection_detail["code"] == "catalog_projection_stale"
    unknown = catalog_error(RuntimeError("raw database detail"))
    assert unknown.status_code == 500
    unknown_detail = cast(dict[str, str], cast(object, unknown.detail))
    assert unknown_detail == {
        "code": "catalog_internal_error",
        "message": "The catalog request could not be completed.",
    }
