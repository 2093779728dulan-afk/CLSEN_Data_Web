"""Repeatable stage 6 backend demo, deliberately restricted to local test DBs.

This is not an API or UI.  It wires the same application services used by the
future API into one explicit local smoke workflow so stage 6 can be exercised
before stages 7 and 8 exist.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import sys
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, date, datetime, time, timedelta
from decimal import Decimal
from io import BytesIO
from pathlib import Path
from typing import Any, cast
from uuid import UUID, uuid4, uuid5

import sqlalchemy as sa
from dotenv import dotenv_values
from sqlalchemy.engine import URL, Connection, Engine

from app.datasets.repository import MySqlDatasetRepository
from app.datasets.service import DatasetService
from app.datasets.types import MaterializeBaselineCommand
from app.db.engine import create_database_engine
from app.db.settings import DatabaseSettings
from app.imports.repository import MySqlIngestRepository
from app.imports.service import IngestService
from app.imports.storage import LocalContentStore, StorageConfigurationError
from app.imports.types import (
    DuplicateBatchConflict,
    ImportCommand,
    ImportCreated,
    RecoveredImport,
)
from app.parsers.repository import MySqlParseRepository
from app.parsers.workflow import (
    ConfirmAndParseCommand,
    ParseWorkflow,
    SuccessfulParse,
)
from app.publications.commands import (
    CreateRevisionCommand,
    DraftPointerExpectation,
    PublicationConfirmation,
    PublicationPointerExpectation,
    PublishCommand,
    RollbackCommand,
    ValidationExpectation,
)
from app.publications.repository import MySqlPublicationRepository
from app.publications.service import PublicationService
from app.review.repository import MySqlReviewRepository
from app.review.service import ReviewService
from app.review.types import (
    CreateNoteCommand,
    DraftHeadExpectation,
    MarkReadyCommand,
    ReviewMutationResult,
    SetFieldValueCommand,
    VersionNoteTarget,
)
from app.validation.repository import MySqlValidationRepository
from app.validation.service import ValidationService
from app.validation.types import RunValidationCommand, ValidationRunReceipt

_SAFE_DATABASE_PATTERN = re.compile(r"clsen_data_test(?:_[a-z0-9_]+)?\Z")
_LOCAL_HOSTS = frozenset({"127.0.0.1", "::1", "localhost"})
_REQUIRED_STAGE6_TABLES = frozenset(
    {
        "audit_events",
        "business_parse_baseline_rows",
        "business_report_rows",
        "business_version_base_rows",
        "data_change_events",
        "daily_dataset_locks",
        "daily_datasets",
        "dataset_drafts",
        "dataset_publications",
        "dataset_versions",
        "draft_operation_results",
        "draft_operation_tokens",
        "field_changes",
        "file_ingest_leases",
        "import_batches",
        "note_threads",
        "notes",
        "parse_attempts",
        "parse_baseline_rows",
        "parse_baselines",
        "parse_operation_tokens",
        "parsed_source_rows",
        "publication_command_results",
        "publication_commands",
        "publication_events",
        "publication_outbox",
        "raw_files",
        "review_operation_results",
        "review_operation_tokens",
        "roles",
        "site_config_versions",
        "user_roles",
        "users",
        "validation_issues",
        "validation_runs",
        "version_base_rows",
        "version_base_snapshot_members",
        "version_base_snapshots",
        "version_input_batches",
        "version_parent_versions",
        "version_review_events",
        "version_rows",
    }
)
_DEMO_MANAGER_USERNAME = "stage6-demo-manager"
_DEMO_MANAGER_DISPLAY_NAME = "Stage 6 Demo Data Manager"
_DEMO_ADMIN_USERNAME = "stage6-demo-admin"
_DEMO_ADMIN_DISPLAY_NAME = "Stage 6 Demo Administrator"
_TOKEN_NAMESPACE = UUID("967b0644-6984-52c7-b75e-6c350e2ce94f")
_FIXTURE_PATH = Path(__file__).resolve().parent / "fixtures" / "business-report.csv"


class Stage6DemoError(RuntimeError):
    """A safe, user-facing demo failure."""


class Stage6DemoPreconditionError(Stage6DemoError):
    """The demo refused to write because a prerequisite was not met."""


@dataclass(frozen=True, slots=True)
class DemoDatabaseTargets:
    """Validated migration/runtime targets for one local disposable test DB."""

    migration: DatabaseSettings
    runtime: DatabaseSettings

    @classmethod
    def from_mapping(cls, environment: Mapping[str, str]) -> DemoDatabaseTargets:
        migration_value = environment.get("APP_TEST_DATABASE_URL", "").strip()
        runtime_value = environment.get("APP_TEST_RUNTIME_DATABASE_URL", "").strip()
        if not migration_value:
            raise Stage6DemoPreconditionError(
                "APP_TEST_DATABASE_URL must be configured; the demo never falls "
                "back to APP_DATABASE_URL"
            )
        if not runtime_value:
            raise Stage6DemoPreconditionError(
                "APP_TEST_RUNTIME_DATABASE_URL must be configured; the demo never "
                "falls back to APP_DATABASE_URL"
            )

        try:
            migration = DatabaseSettings.from_url(
                migration_value,
                pool_size=1,
                max_overflow=0,
            )
            runtime = DatabaseSettings.from_url(
                runtime_value,
                pool_size=2,
                max_overflow=0,
            )
        except ValueError as error:
            raise Stage6DemoPreconditionError(str(error)) from error

        for variable_name, settings in (
            ("APP_TEST_DATABASE_URL", migration),
            ("APP_TEST_RUNTIME_DATABASE_URL", runtime),
        ):
            _assert_safe_local_test_url(variable_name, settings.url)

        if _database_location(migration.url) != _database_location(runtime.url):
            raise Stage6DemoPreconditionError(
                "APP_TEST_DATABASE_URL and APP_TEST_RUNTIME_DATABASE_URL must "
                "target the same local test database"
            )
        if migration.url.username == runtime.url.username:
            raise Stage6DemoPreconditionError(
                "migration and runtime test URLs must use different database accounts"
            )
        return cls(migration=migration, runtime=runtime)

    @property
    def database_name(self) -> str:
        database_name = self.migration.url.database
        if database_name is None:  # DatabaseSettings already rejects this.
            raise Stage6DemoPreconditionError("test database name is missing")
        return database_name


@dataclass(frozen=True, slots=True)
class DemoActors:
    manager_user_id: int
    admin_user_id: int


@dataclass(frozen=True, slots=True)
class DemoImport:
    batch_id: int
    raw_file_id: int
    parse_attempt_id: int
    parse_baseline_id: int
    filename: str
    sha256_hex: str


@dataclass(frozen=True, slots=True)
class Stage6DemoSummary:
    database_name: str
    primary_date: date
    isolation_date: date
    primary_dataset_id: int
    isolation_dataset_id: int
    initial_publication_version_id: int
    revision_publication_version_id: int
    final_publication_version_id: int
    initial_validation_run_id: int
    revision_validation_run_id: int
    isolation_fingerprint: str

    def as_payload(self) -> dict[str, object]:
        return {
            "database_name": self.database_name,
            "primary_date": self.primary_date.isoformat(),
            "isolation_date": self.isolation_date.isoformat(),
            "primary_dataset_id": self.primary_dataset_id,
            "isolation_dataset_id": self.isolation_dataset_id,
            "initial_publication_version_id": self.initial_publication_version_id,
            "revision_publication_version_id": self.revision_publication_version_id,
            "final_publication_version_id": self.final_publication_version_id,
            "initial_validation_run_id": self.initial_validation_run_id,
            "revision_validation_run_id": self.revision_validation_run_id,
            "isolation_fingerprint": self.isolation_fingerprint,
            "final_state": "rolled_back_to_initial_publication",
            "stage7_api_available": False,
            "stage8_ui_available": False,
        }


def _normalised_host(url: URL) -> str:
    host = (url.host or "").casefold()
    return "127.0.0.1" if host == "localhost" else host


def _database_location(url: URL) -> tuple[str, int, str | None]:
    return (_normalised_host(url), url.port or 3306, url.database)


def _assert_safe_local_test_url(variable_name: str, url: URL) -> None:
    database_name = url.database or ""
    if _SAFE_DATABASE_PATTERN.fullmatch(database_name) is None:
        raise Stage6DemoPreconditionError(
            f"{variable_name} refuses database {database_name!r}; the name must "
            "match clsen_data_test or clsen_data_test_<suffix>"
        )
    host = (url.host or "").casefold()
    if host not in _LOCAL_HOSTS:
        raise Stage6DemoPreconditionError(
            f"{variable_name} refuses non-local MySQL host {host!r}"
        )


def load_demo_environment(environment_file: Path | None) -> dict[str, str]:
    """Load only APP_TEST_* database values; production URLs are ignored."""

    loaded: dict[str, str] = {}
    if environment_file is not None:
        if not environment_file.is_file():
            raise Stage6DemoPreconditionError(
                f"environment file was not found: {environment_file}"
            )
        for name, value in dotenv_values(environment_file).items():
            if name.startswith("APP_TEST_") and value is not None:
                loaded[name] = value
    for name in ("APP_TEST_DATABASE_URL", "APP_TEST_RUNTIME_DATABASE_URL"):
        process_value = os.environ.get(name)
        if process_value is not None:
            loaded[name] = process_value
    return loaded


def stable_operation_token(
    *,
    database_name: str,
    primary_date: date,
    isolation_date: date,
    operation_name: str,
) -> UUID:
    """Return the same command token for every retry of one selected date pair."""

    material = "|".join(
        (
            database_name,
            primary_date.isoformat(),
            isolation_date.isoformat(),
            operation_name,
        )
    )
    return uuid5(_TOKEN_NAMESPACE, material)


def _fixture_filename(
    primary_date: date,
    isolation_date: date,
    role: str,
) -> str:
    if role not in {"primary", "isolation"}:
        raise ValueError("fixture role must be primary or isolation")
    return f"stage6-demo-p{primary_date:%Y%m%d}-i{isolation_date:%Y%m%d}-{role}.csv"


def build_fixture_bytes(
    *,
    primary_date: date,
    isolation_date: date,
    role: str,
) -> bytes:
    """Render a recognizable, date-pair-specific synthetic business report."""

    if role not in {"primary", "isolation"}:
        raise ValueError("fixture role must be primary or isolation")
    template = _FIXTURE_PATH.read_text(encoding="utf-8")
    pair = f"{primary_date:%Y%m%d}-{isolation_date:%Y%m%d}"
    marker = "P" if role == "primary" else "I"
    rendered = (
        template.replace("__SKU_A__", f"S6{marker}-{pair}-A")
        .replace("__SKU_B__", f"S6{marker}-{pair}-B")
        .replace("__TITLE_MARKER__", f"[Stage6 Demo {marker} {pair}]")
    )
    if "__" in rendered:
        raise Stage6DemoError("stage 6 CSV fixture contains an unresolved placeholder")
    return rendered.encode("utf-8-sig")


def _clock_at(value: datetime) -> Callable[[], datetime]:
    return lambda: value


def _as_utc(value: object, label: str) -> datetime:
    if not isinstance(value, datetime):
        raise Stage6DemoError(f"database returned an invalid {label}")
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


def _required_int(value: int | None, label: str) -> int:
    if value is None or value < 1:
        raise Stage6DemoError(f"{label} was not returned")
    return value


def _review_head(
    *,
    dataset_id: int,
    version_id: int,
    status: str,
    data_revision: int,
    review_revision: int,
    pointed_at: datetime,
) -> DraftHeadExpectation:
    return DraftHeadExpectation(
        dataset_id=dataset_id,
        version_id=version_id,
        status=cast(Any, status),
        data_revision=data_revision,
        review_revision=review_revision,
        pointed_at=pointed_at,
    )


def _head_from_review_result(
    result: ReviewMutationResult,
    *,
    pointed_at: datetime,
) -> DraftHeadExpectation:
    return _review_head(
        dataset_id=_required_int(result.dataset_id, "review dataset ID"),
        version_id=_required_int(result.version_id, "review version ID"),
        status=result.status or "",
        data_revision=(
            result.data_revision
            if result.data_revision is not None
            else _raise_missing("review data revision")
        ),
        review_revision=(
            result.review_revision
            if result.review_revision is not None
            else _raise_missing("review revision")
        ),
        pointed_at=pointed_at,
    )


def _raise_missing(label: str) -> Any:
    raise Stage6DemoError(f"{label} was not returned")


class Stage6DemoRunner:
    """Wire production repositories into one safe, resumable local demo."""

    def __init__(
        self,
        *,
        targets: DemoDatabaseTargets,
        storage_root: Path,
        emit: Callable[[str], None] = print,
    ) -> None:
        self._targets = targets
        self._storage_root = storage_root.resolve()
        self._emit = emit
        try:
            self._store = LocalContentStore(
                self._storage_root,
                max_upload_bytes=1024 * 1024,
            )
        except StorageConfigurationError as error:
            raise Stage6DemoPreconditionError(str(error)) from error

    def run(self, *, primary_date: date, isolation_date: date) -> Stage6DemoSummary:
        if primary_date == isolation_date:
            raise Stage6DemoPreconditionError(
                "primary and isolation dates must be different"
            )
        if primary_date.year < 1000 or isolation_date.year < 1000:
            raise Stage6DemoPreconditionError(
                "MySQL demo dates must be in the supported year range 1000-9999"
            )

        migration_engine = create_database_engine(self._targets.migration)
        runtime_engine = create_database_engine(self._targets.runtime)
        try:
            self._preflight(migration_engine, runtime_engine)
            self._assert_reserved_date_scope(
                migration_engine,
                report_date=primary_date,
                expected_filename=_fixture_filename(
                    primary_date,
                    isolation_date,
                    "primary",
                ),
            )
            self._assert_reserved_date_scope(
                migration_engine,
                report_date=isolation_date,
                expected_filename=_fixture_filename(
                    primary_date,
                    isolation_date,
                    "isolation",
                ),
            )
            self._store.assert_ready()
            actors = self._ensure_demo_actors(migration_engine)
            return self._run_workflow(
                migration_engine=migration_engine,
                runtime_engine=runtime_engine,
                actors=actors,
                primary_date=primary_date,
                isolation_date=isolation_date,
            )
        finally:
            runtime_engine.dispose()
            migration_engine.dispose()

    def _preflight(self, migration_engine: Engine, runtime_engine: Engine) -> None:
        self._emit("[preflight] validating schema and isolated database accounts")
        with migration_engine.connect() as migration:
            revisions = tuple(
                str(value)
                for value in migration.scalars(
                    sa.text("SELECT version_num FROM alembic_version")
                )
            )
            if len(revisions) != 1:
                raise Stage6DemoPreconditionError(
                    "test database must have exactly one Alembic head; no demo "
                    "writes were performed"
                )
            revision = revisions[0]
            match = re.fullmatch(r"(\d{4})(?:_.+)?", revision)
            if match is not None and int(match.group(1)) < 9:
                raise Stage6DemoPreconditionError(
                    f"test database schema is at {revision!r}; stage 6 demo "
                    "requires migration 0009 or newer and never runs migrations"
                )
            table_names = frozenset(sa.inspect(migration).get_table_names())
            missing_tables = sorted(_REQUIRED_STAGE6_TABLES - table_names)
            if missing_tables:
                raise Stage6DemoPreconditionError(
                    "stage 6 schema is incomplete; missing table(s): "
                    + ", ".join(missing_tables)
                )

            migration_database = str(migration.scalar(sa.text("SELECT DATABASE()")))
            migration_identity = str(migration.scalar(sa.text("SELECT CURRENT_USER()")))
        with runtime_engine.connect() as runtime:
            runtime_database = str(runtime.scalar(sa.text("SELECT DATABASE()")))
            runtime_identity = str(runtime.scalar(sa.text("SELECT CURRENT_USER()")))

        expected_database = self._targets.database_name
        if (
            migration_database != expected_database
            or runtime_database != expected_database
        ):
            raise Stage6DemoPreconditionError(
                "connected database identity differs from the validated test URLs"
            )
        if (
            migration_identity.partition("@")[0] != self._targets.migration.url.username
            or runtime_identity.partition("@")[0] != self._targets.runtime.url.username
        ):
            raise Stage6DemoPreconditionError(
                "connected MySQL account differs from the validated test URL"
            )
        if migration_identity == runtime_identity:
            raise Stage6DemoPreconditionError(
                "migration and runtime connections resolved to the same MySQL account"
            )

    def _ensure_demo_actors(self, engine: Engine) -> DemoActors:
        self._emit("[setup] ensuring fixed, non-login demo actors")
        with engine.begin() as connection:
            manager_id = self._ensure_actor(
                connection,
                username=_DEMO_MANAGER_USERNAME,
                display_name=_DEMO_MANAGER_DISPLAY_NAME,
                role_code="data_manager",
            )
            admin_id = self._ensure_actor(
                connection,
                username=_DEMO_ADMIN_USERNAME,
                display_name=_DEMO_ADMIN_DISPLAY_NAME,
                role_code="admin",
            )
            site_exists = connection.scalar(
                sa.text("SELECT id FROM site_config_versions WHERE id = 1")
            )
            if site_exists is None:
                raise Stage6DemoPreconditionError(
                    "seeded site_config_version 1 is missing"
                )
        return DemoActors(manager_user_id=manager_id, admin_user_id=admin_id)

    @staticmethod
    def _ensure_actor(
        connection: Connection,
        *,
        username: str,
        display_name: str,
        role_code: str,
    ) -> int:
        row = (
            connection.execute(
                sa.text(
                    """
                    SELECT id, display_name, status
                    FROM users
                    WHERE username_normalized = :username
                    FOR UPDATE
                    """
                ),
                {"username": username},
            )
            .mappings()
            .first()
        )
        if row is None:
            inserted = connection.execute(
                sa.text(
                    """
                    INSERT INTO users (
                        username_normalized, display_name, password_hash, status
                    ) VALUES (
                        :username, :display_name, '$argon2id$stage6-demo-no-login',
                        'active'
                    )
                    """
                ),
                {"username": username, "display_name": display_name},
            )
            if inserted.lastrowid is None:
                raise Stage6DemoError("database did not return the demo actor ID")
            user_id = int(inserted.lastrowid)
            assigned = connection.execute(
                sa.text(
                    """
                    INSERT INTO user_roles (user_id, role_id, assigned_by)
                    SELECT :user_id, id, :user_id
                    FROM roles
                    WHERE code = :role_code
                    """
                ),
                {"user_id": user_id, "role_code": role_code},
            )
            if assigned.rowcount != 1:
                raise Stage6DemoPreconditionError(
                    f"seeded application role {role_code!r} is missing"
                )
            return user_id

        user_id = int(row["id"])
        if row["display_name"] != display_name or row["status"] != "active":
            raise Stage6DemoPreconditionError(
                f"reserved demo account {username!r} exists with unexpected metadata"
            )
        roles = tuple(
            str(value)
            for value in connection.scalars(
                sa.text(
                    """
                    SELECT roles.code
                    FROM user_roles
                    INNER JOIN roles ON roles.id = user_roles.role_id
                    WHERE user_roles.user_id = :user_id
                    ORDER BY roles.code
                    FOR SHARE
                    """
                ),
                {"user_id": user_id},
            )
        )
        if roles != (role_code,):
            raise Stage6DemoPreconditionError(
                f"reserved demo account {username!r} has unexpected roles: {roles!r}"
            )
        return user_id

    def _assert_reserved_date_scope(
        self,
        engine: Engine,
        *,
        report_date: date,
        expected_filename: str,
    ) -> None:
        with engine.connect() as connection:
            dataset_id = connection.scalar(
                sa.text(
                    """
                    SELECT id
                    FROM daily_datasets
                    WHERE report_date = :report_date
                      AND report_type = 'business_report'
                    """
                ),
                {"report_date": report_date},
            )
            if dataset_id is None:
                return
            owners = tuple(
                str(value)
                for value in connection.scalars(
                    sa.text(
                        """
                        SELECT DISTINCT users.username_normalized
                        FROM dataset_versions
                        INNER JOIN users ON users.id = dataset_versions.created_by
                        WHERE dataset_versions.dataset_id = :dataset_id
                        ORDER BY users.username_normalized
                        """
                    ),
                    {"dataset_id": dataset_id},
                )
            )
            filenames = tuple(
                str(value)
                for value in connection.scalars(
                    sa.text(
                        """
                        SELECT DISTINCT raw_files.original_filename
                        FROM version_input_batches
                        INNER JOIN dataset_versions
                            ON dataset_versions.id = version_input_batches.version_id
                        INNER JOIN import_batches
                            ON import_batches.id = version_input_batches.batch_id
                        INNER JOIN raw_files
                            ON raw_files.id = import_batches.raw_file_id
                        WHERE dataset_versions.dataset_id = :dataset_id
                        ORDER BY raw_files.original_filename
                        """
                    ),
                    {"dataset_id": dataset_id},
                )
            )
        if not owners or not set(owners).issubset(
            {_DEMO_MANAGER_USERNAME, _DEMO_ADMIN_USERNAME}
        ):
            raise Stage6DemoPreconditionError(
                f"{report_date} already contains a non-demo business dataset; "
                "choose two reserved test dates"
            )
        if filenames != (expected_filename,):
            raise Stage6DemoPreconditionError(
                f"{report_date} belongs to another demo date pair or contains "
                "unexpected inputs; choose two other reserved test dates"
            )

    def _run_workflow(
        self,
        *,
        migration_engine: Engine,
        runtime_engine: Engine,
        actors: DemoActors,
        primary_date: date,
        isolation_date: date,
    ) -> Stage6DemoSummary:
        database_name = self._targets.database_name
        base_time = datetime.combine(primary_date, time(12, 0), tzinfo=UTC)
        ingest_repository = MySqlIngestRepository(runtime_engine)
        parse_repository = MySqlParseRepository(runtime_engine)
        dataset_repository = MySqlDatasetRepository(runtime_engine)
        review_repository = MySqlReviewRepository(runtime_engine)
        validation_repository = MySqlValidationRepository(runtime_engine)
        publication_repository = MySqlPublicationRepository(runtime_engine)

        primary_import = self._import_and_parse(
            runtime_engine=runtime_engine,
            ingest_repository=ingest_repository,
            parse_repository=parse_repository,
            store=self._store,
            actors=actors,
            primary_date=primary_date,
            isolation_date=isolation_date,
            report_date=primary_date,
            role="primary",
            parse_time=base_time + timedelta(seconds=1),
        )
        isolation_import = self._import_and_parse(
            runtime_engine=runtime_engine,
            ingest_repository=ingest_repository,
            parse_repository=parse_repository,
            store=self._store,
            actors=actors,
            primary_date=primary_date,
            isolation_date=isolation_date,
            report_date=isolation_date,
            role="isolation",
            parse_time=base_time + timedelta(seconds=2),
        )

        primary_pointed_at = base_time + timedelta(seconds=3)
        primary_draft = DatasetService(
            repository=dataset_repository,
            clock=_clock_at(primary_pointed_at),
        ).materialize_baseline(
            MaterializeBaselineCommand(
                batch_id=primary_import.batch_id,
                parse_baseline_id=primary_import.parse_baseline_id,
                report_date=primary_date,
                strategy="merge",
                expected_active_draft=None,
                expected_publication_version_id=None,
                merge_decisions=(),
                actor_user_id=actors.manager_user_id,
                operation_token=stable_operation_token(
                    database_name=database_name,
                    primary_date=primary_date,
                    isolation_date=isolation_date,
                    operation_name="materialize-primary",
                ),
                reason="Stage 6 demo: materialize primary synthetic CSV",
            )
        )
        isolation_pointed_at = base_time + timedelta(seconds=4)
        isolation_draft = DatasetService(
            repository=dataset_repository,
            clock=_clock_at(isolation_pointed_at),
        ).materialize_baseline(
            MaterializeBaselineCommand(
                batch_id=isolation_import.batch_id,
                parse_baseline_id=isolation_import.parse_baseline_id,
                report_date=isolation_date,
                strategy="merge",
                expected_active_draft=None,
                expected_publication_version_id=None,
                merge_decisions=(),
                actor_user_id=actors.manager_user_id,
                operation_token=stable_operation_token(
                    database_name=database_name,
                    primary_date=primary_date,
                    isolation_date=isolation_date,
                    operation_name="materialize-isolation",
                ),
                reason="Stage 6 demo: materialize isolation synthetic CSV",
            )
        )
        self._emit(
            "[draft] primary and isolation drafts materialized/recovered "
            f"(datasets {primary_draft.dataset_id}, {isolation_draft.dataset_id})"
        )
        self._assert_dataset_binding(
            migration_engine,
            dataset_id=primary_draft.dataset_id,
            report_date=primary_date,
        )
        self._assert_dataset_binding(
            migration_engine,
            dataset_id=isolation_draft.dataset_id,
            report_date=isolation_date,
        )
        self._assert_pointer_when_present(
            migration_engine,
            dataset_id=primary_draft.dataset_id,
            version_id=primary_draft.version_id,
            expected_pointed_at=primary_pointed_at,
        )
        self._assert_pointer_when_present(
            migration_engine,
            dataset_id=isolation_draft.dataset_id,
            version_id=isolation_draft.version_id,
            expected_pointed_at=isolation_pointed_at,
        )
        isolation_before = self._dataset_fingerprint(
            migration_engine,
            isolation_draft.dataset_id,
        )

        primary_row_id = self._first_row_id(
            migration_engine,
            primary_draft.version_id,
        )
        ruleset_version = self._ruleset_version(
            migration_engine,
            primary_draft.version_id,
        )
        corrected = ReviewService(
            repository=review_repository,
            clock=_clock_at(base_time + timedelta(seconds=5)),
        ).set_field_value(
            SetFieldValueCommand(
                head=_review_head(
                    dataset_id=primary_draft.dataset_id,
                    version_id=primary_draft.version_id,
                    status="draft",
                    data_revision=primary_draft.data_revision,
                    review_revision=primary_draft.review_revision,
                    pointed_at=primary_pointed_at,
                ),
                row_id=primary_row_id,
                field_name="ordered_product_sales",
                value=Decimal("120.000000"),
                actor_user_id=actors.manager_user_id,
                operation_token=stable_operation_token(
                    database_name=database_name,
                    primary_date=primary_date,
                    isolation_date=isolation_date,
                    operation_name="correct-initial-sales",
                ),
                reason="Stage 6 demo: correct the first-row sales amount",
            )
        )
        noted = ReviewService(
            repository=review_repository,
            clock=_clock_at(base_time + timedelta(seconds=6)),
        ).create_note(
            CreateNoteCommand(
                target=VersionNoteTarget(primary_draft.version_id),
                expected_review_revision=_required_int_or_zero(
                    corrected.review_revision,
                    "corrected review revision",
                ),
                body=(
                    "Stage 6 demo note: synthetic sales correction reviewed "
                    "against the source CSV."
                ),
                actor_user_id=actors.manager_user_id,
                operation_token=stable_operation_token(
                    database_name=database_name,
                    primary_date=primary_date,
                    isolation_date=isolation_date,
                    operation_name="note-initial-correction",
                ),
                visibility="internal",
            )
        )
        self._emit("[review] field correction and internal version note recorded")

        initial_validation = self._validate(
            validation_repository=validation_repository,
            dataset_id=primary_draft.dataset_id,
            version_id=primary_draft.version_id,
            data_revision=_required_int_or_zero(
                noted.data_revision,
                "noted data revision",
            ),
            ruleset_version=ruleset_version,
            actor_user_id=actors.manager_user_id,
            operation_token=stable_operation_token(
                database_name=database_name,
                primary_date=primary_date,
                isolation_date=isolation_date,
                operation_name="validate-initial",
            ),
            occurred_at=base_time + timedelta(seconds=7),
        )
        initial_ready = self._mark_ready(
            review_repository=review_repository,
            head=_head_from_review_result(noted, pointed_at=primary_pointed_at),
            validation=initial_validation,
            actor_user_id=actors.manager_user_id,
            operation_token=stable_operation_token(
                database_name=database_name,
                primary_date=primary_date,
                isolation_date=isolation_date,
                operation_name="ready-initial",
            ),
            occurred_at=base_time + timedelta(seconds=8),
        )
        initial_published_at = base_time + timedelta(seconds=9)
        PublicationService(
            repository=publication_repository,
            clock=_clock_at(initial_published_at),
        ).publish(
            self._publish_command(
                dataset_id=primary_draft.dataset_id,
                ready=initial_ready,
                pointed_at=primary_pointed_at,
                validation=initial_validation,
                expected_publication=PublicationPointerExpectation(None, None),
                actor_user_id=actors.manager_user_id,
                operation_token=stable_operation_token(
                    database_name=database_name,
                    primary_date=primary_date,
                    isolation_date=isolation_date,
                    operation_name="publish-initial",
                ),
                reason="Stage 6 demo: publish the reviewed initial version",
            )
        )
        self._emit(
            "[publish] initial validated version published/recovered "
            f"(version {primary_draft.version_id})"
        )

        revision_pointed_at = base_time + timedelta(seconds=10)
        revision = PublicationService(
            repository=publication_repository,
            clock=_clock_at(revision_pointed_at),
        ).create_revision(
            CreateRevisionCommand(
                dataset_id=primary_draft.dataset_id,
                expected_publication=PublicationPointerExpectation(
                    primary_draft.version_id,
                    initial_published_at,
                ),
                actor_user_id=actors.manager_user_id,
                operation_token=stable_operation_token(
                    database_name=database_name,
                    primary_date=primary_date,
                    isolation_date=isolation_date,
                    operation_name="create-ordinary-revision",
                ),
                reason="Stage 6 demo: create an ordinary published-data revision",
            )
        )
        self._assert_pointer_when_present(
            migration_engine,
            dataset_id=revision.dataset_id,
            version_id=revision.version_id,
            expected_pointed_at=revision_pointed_at,
        )
        revision_row_id = self._first_row_id(migration_engine, revision.version_id)
        revision_ruleset = self._ruleset_version(migration_engine, revision.version_id)
        revision_corrected = ReviewService(
            repository=review_repository,
            clock=_clock_at(base_time + timedelta(seconds=11)),
        ).set_field_value(
            SetFieldValueCommand(
                head=_review_head(
                    dataset_id=revision.dataset_id,
                    version_id=revision.version_id,
                    status="draft",
                    data_revision=revision.data_revision,
                    review_revision=revision.review_revision,
                    pointed_at=revision_pointed_at,
                ),
                row_id=revision_row_id,
                field_name="sessions_total",
                value=11,
                actor_user_id=actors.manager_user_id,
                operation_token=stable_operation_token(
                    database_name=database_name,
                    primary_date=primary_date,
                    isolation_date=isolation_date,
                    operation_name="correct-revision-sessions",
                ),
                reason="Stage 6 demo: correct sessions in the ordinary revision",
            )
        )
        revision_noted = ReviewService(
            repository=review_repository,
            clock=_clock_at(base_time + timedelta(seconds=12)),
        ).create_note(
            CreateNoteCommand(
                target=VersionNoteTarget(revision.version_id),
                expected_review_revision=_required_int_or_zero(
                    revision_corrected.review_revision,
                    "ordinary revision review revision",
                ),
                body="Stage 6 demo note: ordinary revision reviewed before publish.",
                actor_user_id=actors.manager_user_id,
                operation_token=stable_operation_token(
                    database_name=database_name,
                    primary_date=primary_date,
                    isolation_date=isolation_date,
                    operation_name="note-ordinary-revision",
                ),
                visibility="internal",
            )
        )
        revision_validation = self._validate(
            validation_repository=validation_repository,
            dataset_id=revision.dataset_id,
            version_id=revision.version_id,
            data_revision=_required_int_or_zero(
                revision_noted.data_revision,
                "revision data revision",
            ),
            ruleset_version=revision_ruleset,
            actor_user_id=actors.manager_user_id,
            operation_token=stable_operation_token(
                database_name=database_name,
                primary_date=primary_date,
                isolation_date=isolation_date,
                operation_name="validate-ordinary-revision",
            ),
            occurred_at=base_time + timedelta(seconds=13),
        )
        revision_ready = self._mark_ready(
            review_repository=review_repository,
            head=_head_from_review_result(
                revision_noted,
                pointed_at=revision_pointed_at,
            ),
            validation=revision_validation,
            actor_user_id=actors.manager_user_id,
            operation_token=stable_operation_token(
                database_name=database_name,
                primary_date=primary_date,
                isolation_date=isolation_date,
                operation_name="ready-ordinary-revision",
            ),
            occurred_at=base_time + timedelta(seconds=14),
        )
        revision_published_at = base_time + timedelta(seconds=15)
        PublicationService(
            repository=publication_repository,
            clock=_clock_at(revision_published_at),
        ).publish(
            self._publish_command(
                dataset_id=revision.dataset_id,
                ready=revision_ready,
                pointed_at=revision_pointed_at,
                validation=revision_validation,
                expected_publication=PublicationPointerExpectation(
                    primary_draft.version_id,
                    initial_published_at,
                ),
                actor_user_id=actors.manager_user_id,
                operation_token=stable_operation_token(
                    database_name=database_name,
                    primary_date=primary_date,
                    isolation_date=isolation_date,
                    operation_name="publish-ordinary-revision",
                ),
                reason="Stage 6 demo: publish the ordinary revision",
            )
        )
        rollback_at = base_time + timedelta(seconds=16)
        PublicationService(
            repository=publication_repository,
            clock=_clock_at(rollback_at),
        ).rollback(
            RollbackCommand(
                dataset_id=primary_draft.dataset_id,
                expected_publication=PublicationPointerExpectation(
                    revision.version_id,
                    revision_published_at,
                ),
                target_version_id=primary_draft.version_id,
                actor_user_id=actors.admin_user_id,
                operation_token=stable_operation_token(
                    database_name=database_name,
                    primary_date=primary_date,
                    isolation_date=isolation_date,
                    operation_name="rollback-to-initial",
                ),
                reason="Stage 6 demo: administrator rollback to initial publication",
            )
        )
        self._emit(
            "[revision] ordinary revision published, then administrator rollback "
            f"restored version {primary_draft.version_id}"
        )

        isolation_after = self._dataset_fingerprint(
            migration_engine,
            isolation_draft.dataset_id,
        )
        if isolation_after != isolation_before:
            raise Stage6DemoError(
                "isolation proof failed: the other date changed during primary-date "
                "review/publication"
            )
        final_version_id = self._assert_final_publication(
            migration_engine,
            dataset_id=primary_draft.dataset_id,
            expected_version_id=primary_draft.version_id,
            expected_revision_version_id=revision.version_id,
        )
        self._emit(
            "[isolation] other-date fingerprint remained unchanged: "
            f"{isolation_before[:16]}..."
        )
        return Stage6DemoSummary(
            database_name=database_name,
            primary_date=primary_date,
            isolation_date=isolation_date,
            primary_dataset_id=primary_draft.dataset_id,
            isolation_dataset_id=isolation_draft.dataset_id,
            initial_publication_version_id=primary_draft.version_id,
            revision_publication_version_id=revision.version_id,
            final_publication_version_id=final_version_id,
            initial_validation_run_id=initial_validation.validation_run_id,
            revision_validation_run_id=revision_validation.validation_run_id,
            isolation_fingerprint=isolation_before,
        )

    def _import_and_parse(
        self,
        *,
        runtime_engine: Engine,
        ingest_repository: MySqlIngestRepository,
        parse_repository: MySqlParseRepository,
        store: LocalContentStore,
        actors: DemoActors,
        primary_date: date,
        isolation_date: date,
        report_date: date,
        role: str,
        parse_time: datetime,
    ) -> DemoImport:
        filename = _fixture_filename(primary_date, isolation_date, role)
        content = build_fixture_bytes(
            primary_date=primary_date,
            isolation_date=isolation_date,
            role=role,
        )
        sha256_hex = hashlib.sha256(content).hexdigest()
        ingest = IngestService(
            repository=ingest_repository,
            store=store,
            lease_ttl=timedelta(minutes=30),
            lease_renew_interval=timedelta(minutes=5),
            token_factory=uuid4,
        ).ingest(
            BytesIO(content),
            ImportCommand(
                original_filename=filename,
                media_type="text/csv",
                created_by_user_id=actors.manager_user_id,
                site_config_version_id=1,
                report_date=report_date,
            ),
        )
        if isinstance(ingest, ImportCreated):
            batch_id = ingest.batch_id
            raw_file_id = ingest.raw_file_id
        elif isinstance(ingest, DuplicateBatchConflict):
            batch_id = ingest.existing_batch_id
            raw_file_id = ingest.raw_file_id
        elif isinstance(ingest, RecoveredImport):
            batch_id = ingest.batch_id
            raw_file_id = ingest.raw_file_id
        else:  # pragma: no cover - protects this demo from future result drift.
            raise Stage6DemoError(f"unsupported ingest result: {type(ingest).__name__}")
        self._assert_import_binding(
            runtime_engine,
            batch_id=batch_id,
            raw_file_id=raw_file_id,
            report_date=report_date,
            filename=filename,
            sha256_hex=sha256_hex,
            actor_user_id=actors.manager_user_id,
        )
        parsed = ParseWorkflow(
            repository=parse_repository,
            store=store,
            clock=_clock_at(parse_time),
        ).confirm_and_parse(
            ConfirmAndParseCommand(
                batch_id=batch_id,
                report_type="business_report",
                report_date=report_date,
                encoding="utf-8-sig",
                site_config_version_id=1,
                actor_user_id=actors.manager_user_id,
                operation_token=stable_operation_token(
                    database_name=self._targets.database_name,
                    primary_date=primary_date,
                    isolation_date=isolation_date,
                    operation_name=f"parse-{role}",
                ),
            )
        )
        if not isinstance(parsed, SuccessfulParse):
            raise Stage6DemoError(
                f"synthetic {role} CSV did not parse successfully: {parsed!r}"
            )
        self._emit(
            f"[import] {role} CSV imported/parsed (batch {batch_id}, "
            f"baseline {parsed.parse_baseline_id})"
        )
        return DemoImport(
            batch_id=batch_id,
            raw_file_id=raw_file_id,
            parse_attempt_id=parsed.parse_attempt_id,
            parse_baseline_id=parsed.parse_baseline_id,
            filename=filename,
            sha256_hex=sha256_hex,
        )

    @staticmethod
    def _assert_import_binding(
        engine: Engine,
        *,
        batch_id: int,
        raw_file_id: int,
        report_date: date,
        filename: str,
        sha256_hex: str,
        actor_user_id: int,
    ) -> None:
        with engine.connect() as connection:
            row = (
                connection.execute(
                    sa.text(
                        """
                        SELECT batches.raw_file_id, batches.report_date,
                               batches.created_by_user_id,
                               batches.site_config_version_id,
                               raw_files.original_filename,
                               LOWER(HEX(raw_files.sha256)) AS sha256_hex
                        FROM import_batches AS batches
                        INNER JOIN raw_files ON raw_files.id = batches.raw_file_id
                        WHERE batches.id = :batch_id
                        """
                    ),
                    {"batch_id": batch_id},
                )
                .mappings()
                .first()
            )
        expected = {
            "raw_file_id": raw_file_id,
            "report_date": report_date,
            "created_by_user_id": actor_user_id,
            "site_config_version_id": 1,
            "original_filename": filename,
            "sha256_hex": sha256_hex,
        }
        if row is None or any(row[key] != value for key, value in expected.items()):
            raise Stage6DemoPreconditionError(
                "existing synthetic content is bound to unexpected import metadata"
            )

    @staticmethod
    def _assert_dataset_binding(
        engine: Engine,
        *,
        dataset_id: int,
        report_date: date,
    ) -> None:
        with engine.connect() as connection:
            row = (
                connection.execute(
                    sa.text(
                        """
                        SELECT report_date, report_type
                        FROM daily_datasets
                        WHERE id = :dataset_id
                        """
                    ),
                    {"dataset_id": dataset_id},
                )
                .mappings()
                .first()
            )
        if (
            row is None
            or row["report_date"] != report_date
            or row["report_type"] != "business_report"
        ):
            raise Stage6DemoError("materialized dataset does not match its demo date")

    @staticmethod
    def _assert_pointer_when_present(
        engine: Engine,
        *,
        dataset_id: int,
        version_id: int,
        expected_pointed_at: datetime,
    ) -> None:
        with engine.connect() as connection:
            row = (
                connection.execute(
                    sa.text(
                        """
                        SELECT version_id, pointed_at
                        FROM dataset_drafts
                        WHERE dataset_id = :dataset_id
                        """
                    ),
                    {"dataset_id": dataset_id},
                )
                .mappings()
                .first()
            )
        if row is None:
            return
        if (
            int(row["version_id"]) != version_id
            or _as_utc(
                row["pointed_at"],
                "draft pointed_at",
            )
            != expected_pointed_at
        ):
            raise Stage6DemoPreconditionError(
                "active draft pointer differs from the stable demo command history"
            )

    @staticmethod
    def _first_row_id(engine: Engine, version_id: int) -> int:
        with engine.connect() as connection:
            row_id = connection.scalar(
                sa.text(
                    """
                    SELECT id
                    FROM version_rows
                    WHERE version_id = :version_id
                    ORDER BY row_ordinal, id
                    LIMIT 1
                    """
                ),
                {"version_id": version_id},
            )
        if row_id is None:
            raise Stage6DemoError("draft has no row available for the correction demo")
        return int(row_id)

    @staticmethod
    def _ruleset_version(engine: Engine, version_id: int) -> str:
        with engine.connect() as connection:
            value = connection.scalar(
                sa.text(
                    "SELECT ruleset_version FROM dataset_versions "
                    "WHERE id = :version_id"
                ),
                {"version_id": version_id},
            )
        if not isinstance(value, str) or not value:
            raise Stage6DemoError("draft ruleset version is missing")
        return value

    @staticmethod
    def _validate(
        *,
        validation_repository: MySqlValidationRepository,
        dataset_id: int,
        version_id: int,
        data_revision: int,
        ruleset_version: str,
        actor_user_id: int,
        operation_token: UUID,
        occurred_at: datetime,
    ) -> ValidationRunReceipt:
        receipt = ValidationService(
            repository=validation_repository,
            clock=_clock_at(occurred_at),
        ).run_validation(
            RunValidationCommand(
                dataset_id=dataset_id,
                version_id=version_id,
                data_revision=data_revision,
                ruleset_version=ruleset_version,
                actor_user_id=actor_user_id,
                operation_token=operation_token,
            )
        )
        if receipt.status != "succeeded" or receipt.result != "passed":
            warning_count = (
                receipt.summary.parse_fidelity.warning_count
                + receipt.summary.draft_explainability.warning_count
            )
            blocking_count = (
                receipt.summary.parse_fidelity.blocking_count
                + receipt.summary.draft_explainability.blocking_count
            )
            raise Stage6DemoError(
                "full validation did not pass: "
                f"status={receipt.status}, result={receipt.result}, "
                f"warnings={warning_count}, blocking={blocking_count}"
            )
        return receipt

    @staticmethod
    def _mark_ready(
        *,
        review_repository: MySqlReviewRepository,
        head: DraftHeadExpectation,
        validation: ValidationRunReceipt,
        actor_user_id: int,
        operation_token: UUID,
        occurred_at: datetime,
    ) -> ReviewMutationResult:
        result = ReviewService(
            repository=review_repository,
            clock=_clock_at(occurred_at),
        ).mark_ready(
            MarkReadyCommand(
                head=head,
                validation_run_id=validation.validation_run_id,
                validation_data_digest=validation.data_digest,
                ruleset_version=validation.ruleset_version,
                confirmed_report_date=validation.summary.report_date,
                confirmed_report_type=validation.summary.report_type,
                confirmed_row_count=validation.summary.row_count,
                confirmed_totals=validation.summary.totals,
                actor_user_id=actor_user_id,
                operation_token=operation_token,
                reason="Stage 6 demo: confirm validation summary and mark ready",
            )
        )
        if result.status != "ready_for_publish":
            raise Stage6DemoError("mark-ready did not return ready_for_publish")
        return result

    @staticmethod
    def _publish_command(
        *,
        dataset_id: int,
        ready: ReviewMutationResult,
        pointed_at: datetime,
        validation: ValidationRunReceipt,
        expected_publication: PublicationPointerExpectation,
        actor_user_id: int,
        operation_token: UUID,
        reason: str,
    ) -> PublishCommand:
        version_id = _required_int(ready.version_id, "ready version ID")
        data_revision = _required_int_or_zero(
            ready.data_revision,
            "ready data revision",
        )
        review_revision = _required_int_or_zero(
            ready.review_revision,
            "ready review revision",
        )
        return PublishCommand(
            dataset_id=dataset_id,
            expected_draft=DraftPointerExpectation(
                version_id=version_id,
                status="ready_for_publish",
                data_revision=data_revision,
                review_revision=review_revision,
                pointed_at=pointed_at,
            ),
            expected_publication=expected_publication,
            validation=ValidationExpectation(
                run_id=validation.validation_run_id,
                version_id=version_id,
                data_revision=data_revision,
                ruleset_version=validation.ruleset_version,
                data_digest=validation.data_digest,
            ),
            confirmation=PublicationConfirmation(
                confirmed_report_date=validation.summary.report_date,
                report_type=validation.summary.report_type,
                row_count=validation.summary.row_count,
                totals=validation.summary.totals,
            ),
            actor_user_id=actor_user_id,
            operation_token=operation_token,
            reason=reason,
        )

    @staticmethod
    def _dataset_fingerprint(engine: Engine, dataset_id: int) -> str:
        queries = (
            ("dataset", "SELECT * FROM daily_datasets WHERE id = :dataset_id"),
            (
                "lock",
                "SELECT * FROM daily_dataset_locks WHERE dataset_id = :dataset_id",
            ),
            (
                "versions",
                "SELECT * FROM dataset_versions WHERE dataset_id = :dataset_id "
                "ORDER BY version_no, id",
            ),
            (
                "draft",
                "SELECT * FROM dataset_drafts WHERE dataset_id = :dataset_id",
            ),
            (
                "publication",
                "SELECT * FROM dataset_publications WHERE dataset_id = :dataset_id",
            ),
            (
                "parents",
                "SELECT parents.* FROM version_parent_versions AS parents "
                "INNER JOIN dataset_versions AS versions "
                "ON versions.id = parents.child_version_id "
                "WHERE versions.dataset_id = :dataset_id "
                "ORDER BY parents.child_version_id, parents.parent_ordinal",
            ),
            (
                "inputs",
                "SELECT inputs.* FROM version_input_batches AS inputs "
                "INNER JOIN dataset_versions AS versions "
                "ON versions.id = inputs.version_id "
                "WHERE versions.dataset_id = :dataset_id "
                "ORDER BY inputs.version_id, inputs.input_ordinal",
            ),
            (
                "snapshots",
                "SELECT snapshots.* FROM version_base_snapshots AS snapshots "
                "INNER JOIN dataset_versions AS versions "
                "ON versions.id = snapshots.version_id "
                "WHERE versions.dataset_id = :dataset_id ORDER BY snapshots.id",
            ),
            (
                "snapshot_members",
                "SELECT members.* FROM version_base_snapshot_members AS members "
                "INNER JOIN version_base_snapshots AS snapshots "
                "ON snapshots.id = members.snapshot_id "
                "INNER JOIN dataset_versions AS versions "
                "ON versions.id = snapshots.version_id "
                "WHERE versions.dataset_id = :dataset_id "
                "ORDER BY members.snapshot_id, members.member_ordinal",
            ),
            (
                "base_rows",
                "SELECT base_rows.* FROM version_base_rows AS base_rows "
                "INNER JOIN dataset_versions AS versions "
                "ON versions.id = base_rows.version_id "
                "WHERE versions.dataset_id = :dataset_id "
                "ORDER BY base_rows.version_id, base_rows.row_ordinal, base_rows.id",
            ),
            (
                "business_base_rows",
                "SELECT typed_base_rows.* FROM business_version_base_rows "
                "AS typed_base_rows "
                "INNER JOIN dataset_versions AS versions "
                "ON versions.id = typed_base_rows.version_id "
                "WHERE versions.dataset_id = :dataset_id "
                "ORDER BY typed_base_rows.version_id, "
                "typed_base_rows.version_base_row_id",
            ),
            (
                "version_rows",
                "SELECT version_row.* FROM version_rows AS version_row "
                "INNER JOIN dataset_versions AS versions "
                "ON versions.id = version_row.version_id "
                "WHERE versions.dataset_id = :dataset_id "
                "ORDER BY version_row.version_id, version_row.row_ordinal, "
                "version_row.id",
            ),
            (
                "business_rows",
                "SELECT typed_rows.* FROM business_report_rows AS typed_rows "
                "INNER JOIN dataset_versions AS versions "
                "ON versions.id = typed_rows.version_id "
                "WHERE versions.dataset_id = :dataset_id "
                "ORDER BY typed_rows.version_id, typed_rows.version_row_id",
            ),
            (
                "validation_runs",
                "SELECT runs.* FROM validation_runs AS runs "
                "INNER JOIN dataset_versions AS versions "
                "ON versions.id = runs.version_id "
                "WHERE versions.dataset_id = :dataset_id ORDER BY runs.id",
            ),
            (
                "data_changes",
                "SELECT events.* FROM data_change_events AS events "
                "INNER JOIN dataset_versions AS versions "
                "ON versions.id = events.version_id "
                "WHERE versions.dataset_id = :dataset_id ORDER BY events.id",
            ),
            (
                "field_changes",
                "SELECT changes.* FROM field_changes AS changes "
                "INNER JOIN dataset_versions AS versions "
                "ON versions.id = changes.version_id "
                "WHERE versions.dataset_id = :dataset_id ORDER BY changes.id",
            ),
            (
                "row_changes",
                "SELECT changes.* FROM row_changes AS changes "
                "INNER JOIN dataset_versions AS versions "
                "ON versions.id = changes.version_id "
                "WHERE versions.dataset_id = :dataset_id ORDER BY changes.id",
            ),
            (
                "note_threads",
                "SELECT threads.* FROM note_threads AS threads "
                "INNER JOIN dataset_versions AS versions "
                "ON versions.id = threads.version_id "
                "WHERE versions.dataset_id = :dataset_id ORDER BY threads.note_key",
            ),
            (
                "notes",
                "SELECT notes.* FROM notes "
                "INNER JOIN note_threads AS threads "
                "ON threads.note_key = notes.note_key "
                "INNER JOIN dataset_versions AS versions "
                "ON versions.id = threads.version_id "
                "WHERE versions.dataset_id = :dataset_id ORDER BY notes.id",
            ),
            (
                "version_reviews",
                "SELECT events.* FROM version_review_events AS events "
                "INNER JOIN dataset_versions AS versions "
                "ON versions.id = events.version_id "
                "WHERE versions.dataset_id = :dataset_id ORDER BY events.id",
            ),
            (
                "publication_events",
                "SELECT * FROM publication_events WHERE dataset_id = :dataset_id "
                "OR peer_dataset_id = :dataset_id ORDER BY id",
            ),
        )
        payload: dict[str, object] = {}
        with engine.connect() as connection:
            for name, sql in queries:
                payload[name] = [
                    _json_safe(dict(row))
                    for row in connection.execute(
                        sa.text(sql),
                        {"dataset_id": dataset_id},
                    )
                    .mappings()
                    .all()
                ]
        encoded = json.dumps(
            payload,
            ensure_ascii=True,
            separators=(",", ":"),
            sort_keys=True,
        ).encode("ascii")
        return hashlib.sha256(encoded).hexdigest()

    @staticmethod
    def _assert_final_publication(
        engine: Engine,
        *,
        dataset_id: int,
        expected_version_id: int,
        expected_revision_version_id: int,
    ) -> int:
        with engine.connect() as connection:
            pointer = (
                connection.execute(
                    sa.text(
                        """
                        SELECT version_id, version_status
                        FROM dataset_publications
                        WHERE dataset_id = :dataset_id
                        """
                    ),
                    {"dataset_id": dataset_id},
                )
                .mappings()
                .first()
            )
            draft_count = int(
                connection.scalar(
                    sa.text(
                        "SELECT COUNT(*) FROM dataset_drafts "
                        "WHERE dataset_id = :dataset_id"
                    ),
                    {"dataset_id": dataset_id},
                )
                or 0
            )
            statuses = {
                int(row["id"]): str(row["status"])
                for row in connection.execute(
                    sa.text(
                        """
                        SELECT id, status
                        FROM dataset_versions
                        WHERE dataset_id = :dataset_id
                          AND id IN (:initial_id, :revision_id)
                        """
                    ),
                    {
                        "dataset_id": dataset_id,
                        "initial_id": expected_version_id,
                        "revision_id": expected_revision_version_id,
                    },
                ).mappings()
            }
            event_types = tuple(
                str(value)
                for value in connection.scalars(
                    sa.text(
                        """
                        SELECT event_type
                        FROM publication_events
                        WHERE dataset_id = :dataset_id
                        ORDER BY id
                        """
                    ),
                    {"dataset_id": dataset_id},
                )
            )
        if (
            pointer is None
            or int(pointer["version_id"]) != expected_version_id
            or pointer["version_status"] != "published"
            or draft_count != 0
            or statuses
            != {
                expected_version_id: "published",
                expected_revision_version_id: "published",
            }
            or event_types[-3:] != ("published", "replaced", "rolled_back")
        ):
            raise Stage6DemoError(
                "final publication graph does not prove publish, revision, and rollback"
            )
        return int(pointer["version_id"])


def _required_int_or_zero(value: int | None, label: str) -> int:
    if value is None or value < 0:
        raise Stage6DemoError(f"{label} was not returned")
    return value


def _json_safe(value: object) -> object:
    if value is None or isinstance(value, (str, int, bool)):
        return value
    if isinstance(value, Decimal):
        return format(value, "f")
    if isinstance(value, (date, datetime)):
        return value.isoformat()
    if isinstance(value, (bytes, bytearray, memoryview)):
        return bytes(value).hex()
    if isinstance(value, Mapping):
        return {str(key): _json_safe(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_safe(item) for item in value]
    raise Stage6DemoError(
        f"cannot canonicalize database value of type {type(value).__name__}"
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m app.demo.stage6",
        description=(
            "Run the stage 6 backend workflow against one explicit local "
            "clsen_data_test* database. No API or UI is started."
        ),
    )
    parser.add_argument("--primary-date", required=True, type=date.fromisoformat)
    parser.add_argument("--isolation-date", required=True, type=date.fromisoformat)
    parser.add_argument("--environment-file", type=Path)
    parser.add_argument("--storage-root", required=True, type=Path)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    arguments = build_parser().parse_args(argv)
    try:
        environment = load_demo_environment(arguments.environment_file)
        targets = DemoDatabaseTargets.from_mapping(environment)
        print(
            "BOUNDARY: stage 6 backend-service demo only; stage 7 API and stage 8 "
            "UI are not available."
        )
        print(
            "SAFETY: writes are restricted to local "
            f"{targets.database_name!r}; no migrations or whole-database cleanup run."
        )
        summary = Stage6DemoRunner(
            targets=targets,
            storage_root=arguments.storage_root,
        ).run(
            primary_date=arguments.primary_date,
            isolation_date=arguments.isolation_date,
        )
    except Stage6DemoError as error:
        print(f"Stage 6 demo refused/failed safely: {error}", file=sys.stderr)
        return 2
    except Exception as error:  # pragma: no cover - CLI diagnostic boundary.
        print(
            f"Stage 6 demo failed ({type(error).__name__}): {error}",
            file=sys.stderr,
        )
        return 1

    print("STAGE6_DEMO_RESULT=" + json.dumps(summary.as_payload(), sort_keys=True))
    print(
        "Demo data was retained in the selected test database; rerun with the "
        "same date pair to recover the stable operation results."
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
