from __future__ import annotations

from datetime import date

from app.imports.types import ImportCommand


def test_upload_metadata_does_not_require_a_report_type_or_date() -> None:
    command = ImportCommand(
        original_filename="unclassified.csv",
        media_type="text/csv",
        created_by_user_id=9,
        site_config_version_id=1,
    )

    assert command.report_date is None


def test_upload_can_preserve_a_preselected_report_date() -> None:
    selected_date = date(2026, 8, 7)

    command = ImportCommand(
        original_filename="unclassified.csv",
        media_type="text/csv",
        created_by_user_id=9,
        site_config_version_id=1,
        report_date=selected_date,
    )

    assert command.report_date == selected_date
