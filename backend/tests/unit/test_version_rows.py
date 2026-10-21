from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest
from app.api.errors import ApiError
from app.api.versions import get_version_rows
from app.workbench.queries import (
    DateWorkbenchQueryService,
    WorkbenchHeadResponse,
)


def test_unpublished_version_cannot_expose_rows() -> None:
    session = MagicMock()
    with (
        patch(
            "app.api.versions.get_version", return_value=SimpleNamespace(status="draft")
        ),
        pytest.raises(ApiError),
    ):
        get_version_rows(7, MagicMock(), session, 1, 50)
    session.execute.assert_not_called()


def test_snapshot_reader_is_fixed_and_viewer_safe() -> None:
    service = DateWorkbenchQueryService(MagicMock())
    head = WorkbenchHeadResponse(
        dataset_id=3,
        version_id=7,
        version_no=1,
        status="published",
        data_revision=0,
        review_revision=0,
        ruleset_version="test",
        pointed_at=datetime(2026, 9, 14, tzinfo=UTC),
    )
    with (
        patch.object(service, "_load_columns", return_value=[]) as columns,
        patch.object(service, "_load_rows", return_value=([], {})) as rows,
    ):
        service.published_version_rows(
            head=head, report_type="return_report", page=1, page_size=50
        )
    assert columns.call_args.kwargs["version_id"] == 7
    assert columns.call_args.kwargs["writable"] is False
    assert rows.call_args.kwargs["head"].version_id == 7
    assert rows.call_args.kwargs["editable"] is False
