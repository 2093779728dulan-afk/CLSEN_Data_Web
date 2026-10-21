from __future__ import annotations

import csv
import os
from collections.abc import Iterator, Sequence
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, timedelta
from io import BytesIO, StringIO
from pathlib import Path
from typing import Any, cast
from uuid import uuid4

import pytest
import sqlalchemy as sa
from alembic import command
from alembic.config import Config
from app.db.engine import create_database_engine
from app.db.settings import DatabaseSettings
from app.imports.repository import MySqlIngestRepository
from app.imports.service import IngestService
from app.imports.storage import LocalContentStore
from app.imports.types import ImportCommand, ImportCreated, ReportType
from app.parsers.repository import MySqlParseRepository
from app.parsers.workflow import (
    ConfirmAndParseCommand,
    ParseWorkflow,
    SuccessfulParse,
)
from sqlalchemy.engine import Connection, Engine

NOW = datetime(2026, 8, 8, 8, 0, tzinfo=UTC)
FIXTURE_ROOT = Path(__file__).resolve().parents[1] / "fixtures" / "synthetic"


@dataclass(frozen=True, slots=True)
class SeededBaseline:
    batch_id: int
    raw_file_id: int
    parse_attempt_id: int
    parse_baseline_id: int
    report_date: date
    report_type: str


@dataclass(slots=True)
class DatasetIntegrationCase:
    migration_engine: Engine
    runtime_settings: DatabaseSettings
    store: LocalContentStore
    owner_user_id: int
    other_manager_user_id: int
    admin_user_id: int
    user_ids: tuple[int, ...]
    baselines: list[SeededBaseline] = field(default_factory=list)
    tracked_dates: set[date] = field(default_factory=set)

    def runtime_engine(self) -> Engine:
        """Return a one-connection runtime-account engine for one actor thread."""

        return create_database_engine(self.runtime_settings)

    def seed_baseline(
        self,
        *,
        report_date: date,
        variant: str,
        report_type: str = "business_report",
        actor_user_id: int | None = None,
        extra_columns: tuple[tuple[str, str], ...] = (),
        inspect_before_parse: bool = False,
    ) -> SeededBaseline:
        actor_id = actor_user_id or self.owner_user_id
        source = _variant_report(report_type, variant, extra_columns=extra_columns)
        ingest = IngestService(
            repository=MySqlIngestRepository(
                self.migration_engine,
                lock_timeout_seconds=5,
            ),
            store=self.store,
            lease_ttl=timedelta(minutes=30),
            lease_renew_interval=timedelta(minutes=5),
            clock=lambda: NOW,
        )
        label = "BusinessReport" if report_type == "business_report" else "Returns"
        created = ingest.ingest(
            BytesIO(source),
            ImportCommand(
                original_filename=(
                    f"{report_date:%Y%m%d}-{label}-{variant}-{uuid4().hex}.csv"
                ),
                media_type="text/csv",
                created_by_user_id=actor_id,
                site_config_version_id=1,
                report_date=report_date,
            ),
        )
        assert isinstance(created, ImportCreated)

        workflow = ParseWorkflow(
            repository=MySqlParseRepository(self.migration_engine),
            store=self.store,
            clock=lambda: NOW,
        )
        if inspect_before_parse:
            recognition = workflow.inspect(created.batch_id)
            assert recognition.status == "suggested"

        parsed = workflow.confirm_and_parse(
            ConfirmAndParseCommand(
                batch_id=created.batch_id,
                report_type=cast(ReportType, report_type),
                report_date=report_date,
                encoding=(
                    "utf-8-sig" if report_type == "business_report" else "windows-1252"
                ),
                site_config_version_id=1,
                actor_user_id=actor_id,
                operation_token=uuid4(),
            )
        )
        assert isinstance(parsed, SuccessfulParse)
        seeded = SeededBaseline(
            batch_id=created.batch_id,
            raw_file_id=created.raw_file_id,
            parse_attempt_id=parsed.parse_attempt_id,
            parse_baseline_id=parsed.parse_baseline_id,
            report_date=report_date,
            report_type=report_type,
        )
        self.baselines.append(seeded)
        self.tracked_dates.add(report_date)
        return seeded

    def track_dates(self, *report_dates: date) -> None:
        self.tracked_dates.update(report_dates)

    def scalar(self, statement: str, parameters: dict[str, Any] | None = None) -> Any:
        with self.migration_engine.connect() as connection:
            return connection.scalar(sa.text(statement), parameters or {})

    def rows(
        self,
        statement: str,
        parameters: dict[str, Any] | None = None,
    ) -> list[dict[str, Any]]:
        with self.migration_engine.connect() as connection:
            return [
                dict(row)
                for row in connection.execute(
                    sa.text(statement),
                    parameters or {},
                )
                .mappings()
                .all()
            ]

    def mark_published(self, dataset_id: int, version_id: int) -> None:
        """Seed an immutable publication; publication behavior belongs to stage 6."""

        with self.migration_engine.begin() as connection:
            connection.execute(
                sa.text(
                    """
                    DELETE FROM dataset_drafts
                    WHERE dataset_id = :dataset_id
                      AND version_id = :version_id
                    """
                ),
                {"dataset_id": dataset_id, "version_id": version_id},
            )
            connection.execute(
                sa.text(
                    """
                    UPDATE dataset_versions
                    SET status = 'published', sealed_at = :sealed_at
                    WHERE id = :version_id AND dataset_id = :dataset_id
                    """
                ),
                {
                    "dataset_id": dataset_id,
                    "version_id": version_id,
                    "sealed_at": NOW.replace(tzinfo=None),
                },
            )
            connection.execute(
                sa.text(
                    """
                    INSERT INTO dataset_publications (
                        dataset_id, version_id, version_status, published_at
                    ) VALUES (
                        :dataset_id, :version_id, 'published', :published_at
                    )
                    """
                ),
                {
                    "dataset_id": dataset_id,
                    "version_id": version_id,
                    "published_at": NOW.replace(tzinfo=None),
                },
            )

    def dataset_graph(self, report_dates: Sequence[date]) -> dict[str, Any]:
        """Return stable relational state; auto-increment counters are excluded."""

        date_values = tuple(report_dates)
        if not date_values:
            raise ValueError("at least one report date is required")
        self.track_dates(*date_values)
        dates: sa.BindParameter[Any] = sa.bindparam(
            "report_dates",
            expanding=True,
        )
        dataset_query = sa.text(
            """
            SELECT id, report_date, report_type
            FROM daily_datasets
            WHERE report_date IN :report_dates
            ORDER BY report_date, report_type, id
            """
        ).bindparams(dates)
        with self.migration_engine.connect() as connection:
            datasets = [
                dict(row)
                for row in connection.execute(
                    dataset_query,
                    {"report_dates": date_values},
                )
                .mappings()
                .all()
            ]
            dataset_ids = tuple(int(row["id"]) for row in datasets)
            if not dataset_ids:
                return {
                    "datasets": [],
                    "dataset_locks": [],
                    "versions": [],
                    "drafts": [],
                    "publications": [],
                    "parents": [],
                    "inputs": [],
                    "snapshots": [],
                    "members": [],
                    "base_rows": [],
                    "version_rows": [],
                    "business_rows": [],
                    "return_rows": [],
                    "dispositions": [],
                }
            return _read_dataset_graph(connection, datasets, dataset_ids)


def _variant_report(
    report_type: str,
    variant: str,
    *,
    extra_columns: tuple[tuple[str, str], ...] = (),
) -> bytes:
    if not variant or not variant.replace("-", "").isalnum():
        raise ValueError("variant must contain only letters, digits, and hyphens")
    filename = (
        "business-report.csv"
        if report_type == "business_report"
        else "return-report.csv"
    )
    encoding = "utf-8" if report_type == "business_report" else "windows-1252"
    text = (FIXTURE_ROOT / filename).read_text(encoding=encoding)
    if report_type == "business_report":
        text = text.replace("SYN-BLUE-S", f"SYN-BLUE-{variant}")
        text = text.replace("SYN-SAND-M", f"SYN-SAND-{variant}")
    elif report_type == "return_report":
        text = text.replace("000-0000000-0000000", f"000-0000000-{variant}0")
        text = text.replace("000-0000000-0000001", f"000-0000000-{variant}1")
    else:
        raise ValueError(f"unsupported report type: {report_type}")
    if extra_columns:
        if any(not header.strip() for header, _value in extra_columns):
            raise ValueError("extra column headers must not be blank")
        rows = list(csv.reader(StringIO(text, newline=""), strict=True))
        if not rows:
            raise ValueError("synthetic fixture must contain a header")
        rows[0].extend(header for header, _value in extra_columns)
        for row in rows[1:]:
            row.extend(value for _header, value in extra_columns)
        rendered = StringIO(newline="")
        writer = csv.writer(rendered, lineterminator="\r\n")
        writer.writerows(rows)
        text = rendered.getvalue()
    return text.encode(
        "utf-8-sig" if report_type == "business_report" else "windows-1252"
    )


def _runtime_settings(
    mysql_settings: DatabaseSettings,
    request: pytest.FixtureRequest,
) -> DatabaseSettings:
    value = os.getenv("APP_TEST_RUNTIME_DATABASE_URL")
    if value is None or not value.strip():
        if request.config.getoption("--require-mysql"):
            raise pytest.UsageError(
                "APP_TEST_RUNTIME_DATABASE_URL is required by --require-mysql"
            )
        pytest.skip("APP_TEST_RUNTIME_DATABASE_URL is not configured")
    runtime_settings = DatabaseSettings.from_url(
        value,
        pool_size=1,
        max_overflow=0,
    )
    migration_location = (
        (mysql_settings.url.host or "").casefold(),
        mysql_settings.url.port or 3306,
        mysql_settings.url.database,
    )
    runtime_location = (
        (runtime_settings.url.host or "").casefold(),
        runtime_settings.url.port or 3306,
        runtime_settings.url.database,
    )
    if runtime_location != migration_location:
        pytest.fail(
            "runtime and migration URLs must target the same test database",
            pytrace=False,
        )
    if runtime_settings.url.username == mysql_settings.url.username:
        pytest.fail(
            "runtime and migration test URLs must use different accounts",
            pytrace=False,
        )
    return runtime_settings


@pytest.fixture(name="dataset_case")
def dataset_case(
    alembic_config: Config,
    mysql_engine: Engine,
    mysql_settings: DatabaseSettings,
    request: pytest.FixtureRequest,
    tmp_path: Path,
) -> Iterator[DatasetIntegrationCase]:
    command.upgrade(alembic_config, "head")
    runtime_settings = _runtime_settings(mysql_settings, request)
    with mysql_engine.begin() as connection:
        owner_user_id = _insert_user(connection, "owner", "data_manager")
        other_manager_user_id = _insert_user(connection, "other", "data_manager")
        admin_user_id = _insert_user(connection, "admin", "admin")
    case = DatasetIntegrationCase(
        migration_engine=mysql_engine,
        runtime_settings=runtime_settings,
        store=LocalContentStore(tmp_path / "storage", max_upload_bytes=1024 * 1024),
        owner_user_id=owner_user_id,
        other_manager_user_id=other_manager_user_id,
        admin_user_id=admin_user_id,
        user_ids=(owner_user_id, other_manager_user_id, admin_user_id),
    )
    _assert_database_accounts(case, mysql_settings)
    try:
        yield case
    finally:
        _cleanup_case(case)


def _insert_user(connection: Connection, label: str, role_code: str) -> int:
    inserted = connection.execute(
        sa.text(
            """
            INSERT INTO users (
                username_normalized, display_name, password_hash, status
            ) VALUES (:username, :display_name, '$argon2id$test', 'active')
            """
        ),
        {
            "username": f"draft-{label}-{uuid4().hex}",
            "display_name": f"Draft {label.title()} Test",
        },
    )
    assert inserted.lastrowid is not None
    user_id = int(inserted.lastrowid)
    connection.execute(
        sa.text(
            """
            INSERT INTO user_roles (user_id, role_id, assigned_by)
            SELECT :user_id, id, :user_id FROM roles WHERE code = :role_code
            """
        ),
        {"user_id": user_id, "role_code": role_code},
    )
    return user_id


def _assert_database_accounts(
    case: DatasetIntegrationCase,
    mysql_settings: DatabaseSettings,
) -> None:
    runtime_engine = case.runtime_engine()
    try:
        with (
            case.migration_engine.connect() as migration,
            runtime_engine.connect() as runtime,
        ):
            migration_identity = str(migration.scalar(sa.text("SELECT CURRENT_USER()")))
            runtime_identity = str(runtime.scalar(sa.text("SELECT CURRENT_USER()")))
            assert migration_identity.partition("@")[0] == mysql_settings.url.username
            assert (
                runtime_identity.partition("@")[0] == case.runtime_settings.url.username
            )
            assert (
                migration_identity.partition("@")[0]
                != runtime_identity.partition("@")[0]
            )
            assert migration.scalar(sa.text("SELECT DATABASE()")) == runtime.scalar(
                sa.text("SELECT DATABASE()")
            )
    finally:
        runtime_engine.dispose()


def _read_dataset_graph(
    connection: Connection,
    datasets: list[dict[str, Any]],
    dataset_ids: tuple[int, ...],
) -> dict[str, Any]:
    dataset_bind: sa.BindParameter[Any] = sa.bindparam(
        "dataset_ids",
        expanding=True,
    )
    version_rows = _mapping_rows(
        connection,
        """
        SELECT id, dataset_id, report_type, version_no, status,
               data_revision, review_revision, created_by, sealed_at
        FROM dataset_versions
        WHERE dataset_id IN :dataset_ids
        ORDER BY dataset_id, version_no, id
        """,
        {"dataset_ids": dataset_ids},
        dataset_bind,
    )
    version_ids = tuple(int(row["id"]) for row in version_rows)
    graph: dict[str, Any] = {
        "datasets": datasets,
        "dataset_locks": _mapping_rows(
            connection,
            "SELECT dataset_id FROM daily_dataset_locks "
            "WHERE dataset_id IN :dataset_ids ORDER BY dataset_id",
            {"dataset_ids": dataset_ids},
            dataset_bind,
        ),
        "versions": version_rows,
        "drafts": _mapping_rows(
            connection,
            "SELECT * FROM dataset_drafts WHERE dataset_id IN :dataset_ids "
            "ORDER BY dataset_id",
            {"dataset_ids": dataset_ids},
            dataset_bind,
        ),
        "publications": _mapping_rows(
            connection,
            "SELECT * FROM dataset_publications WHERE dataset_id IN :dataset_ids "
            "ORDER BY dataset_id",
            {"dataset_ids": dataset_ids},
            dataset_bind,
        ),
    }
    if not version_ids:
        for key in (
            "parents",
            "inputs",
            "snapshots",
            "members",
            "base_rows",
            "version_rows",
            "business_rows",
            "return_rows",
            "dispositions",
        ):
            graph[key] = []
        return graph
    version_bind: sa.BindParameter[Any] = sa.bindparam(
        "version_ids",
        expanding=True,
    )
    version_parameters = {"version_ids": version_ids}
    graph.update(
        {
            "parents": _mapping_rows(
                connection,
                "SELECT * FROM version_parent_versions "
                "WHERE child_version_id IN :version_ids "
                "OR parent_version_id IN :version_ids "
                "ORDER BY child_version_id, parent_ordinal, parent_version_id",
                version_parameters,
                version_bind,
            ),
            "inputs": _mapping_rows(
                connection,
                "SELECT * FROM version_input_batches "
                "WHERE version_id IN :version_ids "
                "ORDER BY version_id, input_ordinal, batch_id",
                version_parameters,
                version_bind,
            ),
            "snapshots": _mapping_rows(
                connection,
                "SELECT * FROM version_base_snapshots "
                "WHERE version_id IN :version_ids ORDER BY version_id, id",
                version_parameters,
                version_bind,
            ),
            "base_rows": _mapping_rows(
                connection,
                "SELECT * FROM version_base_rows "
                "WHERE version_id IN :version_ids "
                "ORDER BY version_id, row_ordinal, id",
                version_parameters,
                version_bind,
            ),
            "version_rows": _mapping_rows(
                connection,
                "SELECT * FROM version_rows WHERE version_id IN :version_ids "
                "ORDER BY version_id, row_ordinal, id",
                version_parameters,
                version_bind,
            ),
            "business_rows": _mapping_rows(
                connection,
                "SELECT * FROM business_report_rows "
                "WHERE version_id IN :version_ids "
                "ORDER BY version_id, version_row_id",
                version_parameters,
                version_bind,
            ),
            "return_rows": _mapping_rows(
                connection,
                "SELECT * FROM return_report_rows "
                "WHERE version_id IN :version_ids "
                "ORDER BY version_id, version_row_id",
                version_parameters,
                version_bind,
            ),
        }
    )
    snapshot_ids = tuple(int(row["id"]) for row in graph["snapshots"])
    graph["members"] = (
        _mapping_rows(
            connection,
            "SELECT * FROM version_base_snapshot_members "
            "WHERE snapshot_id IN :snapshot_ids "
            "ORDER BY snapshot_id, member_ordinal, id",
            {"snapshot_ids": snapshot_ids},
            sa.bindparam("snapshot_ids", expanding=True),
        )
        if snapshot_ids
        else []
    )
    inspector = sa.inspect(connection)
    graph["dispositions"] = (
        _mapping_rows(
            connection,
            "SELECT * FROM draft_disposition_events "
            "WHERE dataset_id IN :dataset_ids "
            "OR successor_dataset_id IN :dataset_ids "
            "ORDER BY id",
            {"dataset_ids": dataset_ids},
            dataset_bind,
        )
        if inspector.has_table("draft_disposition_events")
        else []
    )
    return graph


def _mapping_rows(
    connection: Connection,
    sql: str,
    parameters: dict[str, Any],
    *binds: sa.BindParameter[Any],
) -> list[dict[str, Any]]:
    statement = sa.text(sql)
    if binds:
        statement = statement.bindparams(*binds)
    return [
        dict(row) for row in connection.execute(statement, parameters).mappings().all()
    ]


def _cleanup_case(case: DatasetIntegrationCase) -> None:
    user_ids = case.user_ids
    batch_ids = tuple(item.batch_id for item in case.baselines)
    raw_file_ids = tuple(item.raw_file_id for item in case.baselines)
    with case.migration_engine.begin() as connection:
        user_bind: sa.BindParameter[Any] = sa.bindparam(
            "user_ids",
            expanding=True,
        )
        dataset_statement = sa.text(
            "SELECT id FROM daily_datasets WHERE id IN ("
            "SELECT DISTINCT dataset_id FROM dataset_versions "
            "WHERE created_by IN :user_ids)"
        ).bindparams(user_bind)
        dataset_parameters: dict[str, Any] = {"user_ids": user_ids}
        if case.tracked_dates:
            dataset_statement = sa.text(
                "SELECT id FROM daily_datasets WHERE report_date IN :report_dates "
                "OR id IN (SELECT DISTINCT dataset_id FROM dataset_versions "
                "WHERE created_by IN :user_ids)"
            ).bindparams(
                user_bind,
                sa.bindparam("report_dates", expanding=True),
            )
            dataset_parameters["report_dates"] = tuple(case.tracked_dates)
        dataset_ids = tuple(
            int(value)
            for value in connection.scalars(
                dataset_statement,
                dataset_parameters,
            )
        )
        version_ids: tuple[int, ...] = ()
        if dataset_ids:
            dataset_bind: sa.BindParameter[Any] = sa.bindparam(
                "dataset_ids",
                expanding=True,
            )
            version_ids = tuple(
                int(value)
                for value in connection.scalars(
                    sa.text(
                        "SELECT id FROM dataset_versions "
                        "WHERE dataset_id IN :dataset_ids"
                    ).bindparams(dataset_bind),
                    {"dataset_ids": dataset_ids},
                )
            )
            _delete_dataset_graph(connection, dataset_ids, version_ids, user_ids)
        _delete_actor_records(connection, user_ids)
        if batch_ids:
            _delete_parse_graph(connection, batch_ids, raw_file_ids)
        connection.execute(
            sa.text("DELETE FROM user_roles WHERE user_id IN :user_ids").bindparams(
                user_bind
            ),
            {"user_ids": user_ids},
        )
        connection.execute(
            sa.text("DELETE FROM users WHERE id IN :user_ids").bindparams(user_bind),
            {"user_ids": user_ids},
        )


def _delete_dataset_graph(
    connection: Connection,
    dataset_ids: tuple[int, ...],
    version_ids: tuple[int, ...],
    user_ids: tuple[int, ...],
) -> None:
    dataset_bind: sa.BindParameter[Any] = sa.bindparam(
        "dataset_ids",
        expanding=True,
    )
    dataset_params = {"dataset_ids": dataset_ids}
    inspector = sa.inspect(connection)
    if inspector.has_table("draft_operation_results"):
        connection.execute(
            sa.text(
                "DELETE FROM draft_operation_results WHERE actor_user_id IN :user_ids"
            ).bindparams(sa.bindparam("user_ids", expanding=True)),
            {"user_ids": user_ids},
        )
    if inspector.has_table("draft_disposition_events"):
        connection.execute(
            sa.text(
                "DELETE FROM draft_disposition_events "
                "WHERE dataset_id IN :dataset_ids "
                "OR successor_dataset_id IN :dataset_ids"
            ).bindparams(dataset_bind),
            dataset_params,
        )
    connection.execute(
        sa.text(
            "DELETE FROM dataset_drafts WHERE dataset_id IN :dataset_ids"
        ).bindparams(dataset_bind),
        dataset_params,
    )
    connection.execute(
        sa.text(
            "DELETE FROM dataset_publications WHERE dataset_id IN :dataset_ids"
        ).bindparams(dataset_bind),
        dataset_params,
    )
    if version_ids:
        version_bind: sa.BindParameter[Any] = sa.bindparam(
            "version_ids",
            expanding=True,
        )
        params = {"version_ids": version_ids}
        if inspector.has_table("workbench_operation_results"):
            connection.execute(
                sa.text(
                    "DELETE FROM workbench_operation_results "
                    "WHERE actor_user_id IN :user_ids"
                ).bindparams(sa.bindparam("user_ids", expanding=True)),
                {"user_ids": user_ids},
            )
        if inspector.has_table("extension_cell_changes"):
            connection.execute(
                sa.text(
                    "DELETE FROM extension_cell_changes "
                    "WHERE version_id IN :version_ids "
                    "AND undoes_change_id IS NOT NULL"
                ).bindparams(version_bind),
                params,
            )
            connection.execute(
                sa.text(
                    "DELETE FROM extension_cell_changes "
                    "WHERE version_id IN :version_ids"
                ).bindparams(version_bind),
                params,
            )
        if inspector.has_table("workbench_operation_tokens"):
            connection.execute(
                sa.text(
                    "DELETE FROM workbench_operation_tokens "
                    "WHERE actor_user_id IN :user_ids"
                ).bindparams(sa.bindparam("user_ids", expanding=True)),
                {"user_ids": user_ids},
            )
        if inspector.has_table("version_extension_cells"):
            connection.execute(
                sa.text(
                    "DELETE FROM version_extension_cells "
                    "WHERE version_id IN :version_ids"
                ).bindparams(version_bind),
                params,
            )
        if inspector.has_table("version_table_columns"):
            connection.execute(
                sa.text(
                    "DELETE FROM version_table_columns WHERE version_id IN :version_ids"
                ).bindparams(version_bind),
                params,
            )
        if inspector.has_table("review_operation_results"):
            connection.execute(
                sa.text(
                    "DELETE FROM review_operation_results "
                    "WHERE actor_user_id IN :user_ids"
                ).bindparams(sa.bindparam("user_ids", expanding=True)),
                {"user_ids": user_ids},
            )
        connection.execute(
            sa.text(
                "DELETE FROM field_changes WHERE version_id IN :version_ids "
                "AND restored_field_change_id IS NOT NULL"
            ).bindparams(version_bind),
            params,
        )
        for table in ("field_changes", "row_changes"):
            connection.execute(
                sa.text(
                    f"DELETE FROM {table} WHERE version_id IN :version_ids"
                ).bindparams(version_bind),
                params,
            )
        connection.execute(
            sa.text(
                "DELETE FROM data_change_events WHERE version_id IN :version_ids"
            ).bindparams(version_bind),
            params,
        )
        if inspector.has_table("review_operation_tokens"):
            connection.execute(
                sa.text(
                    "DELETE FROM review_operation_tokens "
                    "WHERE actor_user_id IN :user_ids"
                ).bindparams(sa.bindparam("user_ids", expanding=True)),
                {"user_ids": user_ids},
            )
        connection.execute(
            sa.text(
                "DELETE FROM issue_review_events WHERE validation_issue_id IN ("
                "SELECT id FROM validation_issues WHERE version_id IN :version_ids)"
            ).bindparams(version_bind),
            params,
        )
        connection.execute(
            sa.text(
                "DELETE FROM validation_issues WHERE version_id IN :version_ids"
            ).bindparams(version_bind),
            params,
        )
        connection.execute(
            sa.text(
                "DELETE FROM validation_runs WHERE version_id IN :version_ids"
            ).bindparams(version_bind),
            params,
        )
        for table in (
            "business_report_rows",
            "return_report_rows",
            "version_rows",
            "business_version_base_rows",
            "return_version_base_rows",
            "version_base_rows",
        ):
            connection.execute(
                sa.text(
                    f"DELETE FROM {table} WHERE version_id IN :version_ids"
                ).bindparams(version_bind),
                params,
            )
        snapshot_ids = tuple(
            int(value)
            for value in connection.scalars(
                sa.text(
                    "SELECT id FROM version_base_snapshots "
                    "WHERE version_id IN :version_ids"
                ).bindparams(version_bind),
                params,
            )
        )
        if snapshot_ids:
            snapshot_bind: sa.BindParameter[Any] = sa.bindparam(
                "snapshot_ids",
                expanding=True,
            )
            connection.execute(
                sa.text(
                    "DELETE FROM version_base_snapshot_members "
                    "WHERE snapshot_id IN :snapshot_ids"
                ).bindparams(snapshot_bind),
                {"snapshot_ids": snapshot_ids},
            )
        connection.execute(
            sa.text(
                "DELETE FROM version_base_snapshots WHERE version_id IN :version_ids"
            ).bindparams(version_bind),
            params,
        )
        connection.execute(
            sa.text(
                "DELETE FROM version_parent_versions "
                "WHERE child_version_id IN :version_ids "
                "OR parent_version_id IN :version_ids"
            ).bindparams(version_bind),
            params,
        )
        connection.execute(
            sa.text(
                "DELETE FROM version_input_batches WHERE version_id IN :version_ids"
            ).bindparams(version_bind),
            params,
        )
        connection.execute(
            sa.text("DELETE FROM dataset_versions WHERE id IN :version_ids").bindparams(
                version_bind
            ),
            params,
        )
    if inspector.has_table("daily_dataset_locks"):
        connection.execute(
            sa.text(
                "DELETE FROM daily_dataset_locks WHERE dataset_id IN :dataset_ids"
            ).bindparams(dataset_bind),
            dataset_params,
        )
    connection.execute(
        sa.text("DELETE FROM daily_datasets WHERE id IN :dataset_ids").bindparams(
            dataset_bind
        ),
        dataset_params,
    )


def _delete_actor_records(connection: Connection, user_ids: tuple[int, ...]) -> None:
    user_bind: sa.BindParameter[Any] = sa.bindparam(
        "user_ids",
        expanding=True,
    )
    params = {"user_ids": user_ids}
    inspector = sa.inspect(connection)
    connection.execute(
        sa.text(
            "DELETE FROM file_ingest_leases WHERE created_by_user_id IN :user_ids"
        ).bindparams(user_bind),
        params,
    )
    for table in (
        "draft_operation_results",
        "draft_operation_tokens",
        "workbench_operation_results",
        "workbench_operation_tokens",
    ):
        if inspector.has_table(table):
            connection.execute(
                sa.text(
                    f"DELETE FROM {table} WHERE actor_user_id IN :user_ids"
                ).bindparams(user_bind),
                params,
            )
    for table, column in (
        ("notes", "author_user_id"),
        ("audit_events", "actor_user_id"),
        ("publication_commands", "actor_user_id"),
    ):
        connection.execute(
            sa.text(f"DELETE FROM {table} WHERE {column} IN :user_ids").bindparams(
                user_bind
            ),
            params,
        )


def _delete_parse_graph(
    connection: Connection,
    batch_ids: tuple[int, ...],
    raw_file_ids: tuple[int, ...],
) -> None:
    batch_bind: sa.BindParameter[Any] = sa.bindparam(
        "batch_ids",
        expanding=True,
    )
    batch_params = {"batch_ids": batch_ids}
    attempt_ids = tuple(
        int(value)
        for value in connection.scalars(
            sa.text(
                "SELECT id FROM parse_attempts WHERE batch_id IN :batch_ids"
            ).bindparams(batch_bind),
            batch_params,
        )
    )
    connection.execute(
        sa.text(
            """
            UPDATE import_batches
            SET status = 'uploaded',
                current_successful_parse_attempt_id = NULL,
                report_type = NULL,
                source_row_count = NULL,
                processing_token = NULL,
                processing_operation_digest = NULL,
                processing_started_at = NULL,
                error_summary = NULL
            WHERE id IN :batch_ids
            """
        ).bindparams(batch_bind),
        batch_params,
    )
    if attempt_ids:
        attempt_bind: sa.BindParameter[Any] = sa.bindparam(
            "attempt_ids",
            expanding=True,
        )
        params = {"attempt_ids": attempt_ids}
        baseline_ids = tuple(
            int(value)
            for value in connection.scalars(
                sa.text(
                    "SELECT id FROM parse_baselines "
                    "WHERE parse_attempt_id IN :attempt_ids"
                ).bindparams(attempt_bind),
                params,
            )
        )
        if baseline_ids:
            baseline_bind: sa.BindParameter[Any] = sa.bindparam(
                "baseline_ids",
                expanding=True,
            )
            baseline_params = {"baseline_ids": baseline_ids}
            for table in (
                "business_parse_baseline_rows",
                "return_parse_baseline_rows",
                "parse_baseline_rows",
            ):
                connection.execute(
                    sa.text(
                        f"DELETE FROM {table} WHERE parse_baseline_id IN :baseline_ids"
                    ).bindparams(baseline_bind),
                    baseline_params,
                )
            connection.execute(
                sa.text(
                    "DELETE FROM parse_baselines WHERE id IN :baseline_ids"
                ).bindparams(baseline_bind),
                baseline_params,
            )
        connection.execute(
            sa.text(
                "DELETE FROM parsed_source_rows WHERE parse_attempt_id IN :attempt_ids"
            ).bindparams(attempt_bind),
            params,
        )
    connection.execute(
        sa.text("DELETE FROM parse_attempts WHERE batch_id IN :batch_ids").bindparams(
            batch_bind
        ),
        batch_params,
    )
    for table in ("parse_operation_tokens", "report_date_operation_tokens"):
        connection.execute(
            sa.text(f"DELETE FROM {table} WHERE batch_id IN :batch_ids").bindparams(
                batch_bind
            ),
            batch_params,
        )
    connection.execute(
        sa.text("DELETE FROM import_batches WHERE id IN :batch_ids").bindparams(
            batch_bind
        ),
        batch_params,
    )
    if raw_file_ids:
        raw_bind: sa.BindParameter[Any] = sa.bindparam(
            "raw_file_ids",
            expanding=True,
        )
        raw_params = {"raw_file_ids": raw_file_ids}
        for table in ("file_ingest_leases", "raw_file_integrity_statuses"):
            connection.execute(
                sa.text(
                    f"DELETE FROM {table} WHERE raw_file_id IN :raw_file_ids"
                ).bindparams(raw_bind),
                raw_params,
            )
        connection.execute(
            sa.text("DELETE FROM raw_files WHERE id IN :raw_file_ids").bindparams(
                raw_bind
            ),
            raw_params,
        )
