from datetime import date
from uuid import uuid4

import pytest
import sqlalchemy as sa
from alembic import command
from alembic.config import Config
from app.api.data_calendar import get_site_context, list_calendar_days
from app.auth.sessions import Principal
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session

pytestmark = pytest.mark.mysql


def _principal(*roles: str) -> Principal:
    return Principal(
        user_id=1,
        username="calendar-user",
        display_name="Calendar user",
        roles=frozenset(roles),
        session_id=1,
        csrf_token_hash=b"calendar-csrf",
    )


def test_daily_calendar_queries_are_valid_and_roleless_access_fails_closed(
    alembic_config: Config,
    mysql_engine: Engine,
) -> None:
    command.upgrade(alembic_config, "head")

    with Session(mysql_engine) as session:
        reviewer_days = list_calendar_days(
            _principal("data_manager"),
            session,
            date(2091, 1, 1),
            date(2091, 1, 2),
        )
        roleless_days = list_calendar_days(
            _principal(),
            session,
            date(2091, 1, 1),
            date(2091, 1, 2),
        )

    assert [day.status for day in reviewer_days] == ["gray", "gray"]
    assert [day.status for day in roleless_days] == ["gray", "gray"]
    assert all(not day.reasons for day in roleless_days)


def test_site_context_reads_the_current_versioned_configuration(
    alembic_config: Config,
    mysql_engine: Engine,
) -> None:
    command.upgrade(alembic_config, "head")

    with Session(mysql_engine) as session:
        context = get_site_context(_principal("viewer"), session)

    assert context.site_id == 1
    assert context.site_code == "amazon_us"
    assert context.display_name == "Amazon US"
    assert context.site_config_version_id == 1
    assert context.source_timezone == "America/Los_Angeles"
    assert context.reporting_timezone == "America/Los_Angeles"
    assert context.currency_code == "USD"


def test_rejected_import_is_not_reported_as_a_failed_import(
    alembic_config: Config,
    mysql_engine: Engine,
) -> None:
    command.upgrade(alembic_config, "head")
    rejected_date = date(2091, 1, 3)
    failed_date = date(2091, 1, 4)
    candidate_only_date = date(2091, 1, 5)
    username = f"calendar-import-{uuid4().hex}"
    batch_ids: list[int] = []
    raw_file_ids: list[int] = []
    user_id: int | None = None

    try:
        with mysql_engine.begin() as connection:
            user = connection.execute(
                sa.text(
                    """
                    INSERT INTO users (
                        username_normalized, display_name, password_hash, status
                    ) VALUES (
                        :username, 'Calendar import status', '$argon2id$test',
                        'active'
                    )
                    """
                ),
                {"username": username},
            )
            assert user.lastrowid is not None
            user_id = int(user.lastrowid)

            for report_date, status, confirmed in (
                (rejected_date, "rejected", False),
                (failed_date, "processing_failed", True),
                (candidate_only_date, "processing_failed", False),
            ):
                raw_file = connection.execute(
                    sa.text(
                        """
                        INSERT INTO raw_files (
                            sha256, storage_key, original_filename,
                            size_bytes, uploaded_by_user_id
                        ) VALUES (
                            :digest, :storage_key, 'calendar-status.csv',
                            1, :user_id
                        )
                        """
                    ),
                    {
                        "digest": uuid4().bytes + uuid4().bytes,
                        "storage_key": f"sha256/calendar/{uuid4().hex}",
                        "user_id": user_id,
                    },
                )
                assert raw_file.lastrowid is not None
                raw_file_id = int(raw_file.lastrowid)
                raw_file_ids.append(raw_file_id)
                batch = connection.execute(
                    sa.text(
                        """
                        INSERT INTO import_batches (
                            raw_file_id, site_id, site_config_version_id,
                            report_date, candidate_report_date, status,
                            created_by_user_id, confirmation_revision,
                            confirmed_report_type,
                            confirmed_by_user_id, confirmed_at
                        ) VALUES (
                            :raw_file_id, 1, 1, :report_date, :report_date,
                            :status, :user_id, :confirmation_revision,
                            :confirmed_report_type,
                            :confirmed_by_user_id, :confirmed_at
                        )
                        """
                    ),
                    {
                        "raw_file_id": raw_file_id,
                        "report_date": report_date,
                        "status": status,
                        "user_id": user_id,
                        "confirmation_revision": 1 if confirmed else 0,
                        "confirmed_report_type": (
                            "business_report" if confirmed else None
                        ),
                        "confirmed_by_user_id": user_id if confirmed else None,
                        "confirmed_at": "2091-01-04 08:00:00" if confirmed else None,
                    },
                )
                assert batch.lastrowid is not None
                batch_ids.append(int(batch.lastrowid))

        with Session(mysql_engine) as session:
            days = list_calendar_days(
                _principal("data_manager"),
                session,
                rejected_date,
                candidate_only_date,
            )

        assert [(day.report_date, day.status, day.reasons) for day in days] == [
            (rejected_date, "gray", []),
            (failed_date, "red", ["failed_import"]),
            (candidate_only_date, "gray", []),
        ]
    finally:
        with mysql_engine.begin() as connection:
            for batch_id in reversed(batch_ids):
                connection.execute(
                    sa.text("DELETE FROM import_batches WHERE id = :batch_id"),
                    {"batch_id": batch_id},
                )
            for raw_file_id in reversed(raw_file_ids):
                connection.execute(
                    sa.text("DELETE FROM raw_files WHERE id = :raw_file_id"),
                    {"raw_file_id": raw_file_id},
                )
            if user_id is not None:
                connection.execute(
                    sa.text("DELETE FROM users WHERE id = :user_id"),
                    {"user_id": user_id},
                )
