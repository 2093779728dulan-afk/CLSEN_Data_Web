from __future__ import annotations

import json
import os
import re
from pathlib import Path
from typing import Any

import pytest
import sqlalchemy as sa
from app.db.settings import DatabaseSettings
from dotenv import load_dotenv
from sqlalchemy.engine import make_url

REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
_SAFE_TEST_DATABASE = re.compile(r"clsen_data_test(?:_[a-z0-9_]+)?\Z")
_RUN_ID = re.compile(r"[0-9a-f]{32}\Z")
_DISPOSABLE_COMPOSE_PROJECT = re.compile(r"clsen-deployment-verify-[0-9a-f]{12}\Z")
_OUTCOME_DIRECTORY_ENV = "APP_STAGE0_PYTEST_OUTCOME_DIRECTORY"
_OUTCOME_BINDING_ENV = "APP_STAGE0_PYTEST_OUTCOME_BINDING"
_OUTCOME_SHARD_ENV = "APP_STAGE0_PYTEST_OUTCOME_SHARD"
_OUTCOME_EXPECTED_NODE_DIGEST_ENV = "APP_STAGE0_PYTEST_OUTCOME_EXPECTED_NODE_DIGEST"
_PRIVATE_CANARY_ENVIRONMENT_NAMES = (
    "APP_PRODUCT_CATALOG_CANARY_DATABASE_URL",
    "APP_PRODUCT_CATALOG_PRIVATE_MANIFEST",
    "APP_PRODUCT_CATALOG_PRIVATE_CORPUS_ROOT",
    "APP_REQUIRE_PRODUCT_CATALOG_CANARY",
    "APP_PRODUCT_CATALOG_CANARY_EVIDENCE_PATH",
)


def _stage0_nodeid(value: str) -> str:
    path, separator, test_identity = value.partition("::")
    normalized_path = path.replace("\\", "/")
    if normalized_path.startswith("tests/"):
        normalized_path = f"backend/{normalized_path}"
    return separator.join((normalized_path, test_identity))


def _skip_reason(report: pytest.TestReport) -> str:
    longrepr = report.longrepr
    reason = str(longrepr[2]) if isinstance(longrepr, tuple) else str(longrepr)
    reason = reason.strip()
    return reason.removeprefix("Skipped: ")


class _Stage0OutcomeReporter:
    def __init__(
        self,
        *,
        directory: Path,
        binding: str,
        shard: str,
        expected_node_digest: str,
        private_environment_clear: bool,
    ) -> None:
        self._directory = directory
        self._binding = binding
        self._shard = shard
        self._expected_node_digest = expected_node_digest
        self._private_environment_clear = private_environment_clear
        self._collected: list[str] = []
        self._reports: dict[str, list[pytest.TestReport]] = {}

    def pytest_collection_finish(self, session: pytest.Session) -> None:
        self._collected = sorted(_stage0_nodeid(item.nodeid) for item in session.items)
        self._private_environment_clear = (
            self._private_environment_clear and _private_canary_environment_clear()
        )

    def pytest_runtest_logreport(self, report: pytest.TestReport) -> None:
        nodeid = _stage0_nodeid(report.nodeid)
        self._reports.setdefault(nodeid, []).append(report)

    def _outcome(self, nodeid: str) -> dict[str, str]:
        reports = self._reports.get(nodeid, [])
        call_reports = [report for report in reports if report.when == "call"]
        if len(call_reports) > 1 or any(
            getattr(report, "outcome", None) == "rerun" for report in reports
        ):
            return {"nodeid": nodeid, "status": "rerun", "reason": "repeated call"}
        xfail_reports = [report for report in reports if hasattr(report, "wasxfail")]
        if xfail_reports:
            report = xfail_reports[-1]
            status = "xfail" if report.skipped else "xpass"
            return {
                "nodeid": nodeid,
                "status": status,
                "reason": str(getattr(report, "wasxfail", "")),
            }
        failed = [report for report in reports if report.failed]
        if failed:
            status = (
                "failed" if any(report.when == "call" for report in failed) else "error"
            )
            return {"nodeid": nodeid, "status": status, "reason": "test failed"}
        skipped = [report for report in reports if report.skipped]
        if skipped:
            return {
                "nodeid": nodeid,
                "status": "skipped",
                "reason": _skip_reason(skipped[-1]),
            }
        if len(call_reports) == 1 and call_reports[0].passed:
            return {"nodeid": nodeid, "status": "passed", "reason": ""}
        return {"nodeid": nodeid, "status": "error", "reason": "test did not complete"}

    def pytest_sessionfinish(self, session: pytest.Session, exitstatus: int) -> None:
        del session
        self._private_environment_clear = (
            self._private_environment_clear and _private_canary_environment_clear()
        )
        _clear_private_canary_environment()
        payload: dict[str, Any] = {
            "schema_version": 2,
            "binding_sha256": self._binding,
            "shard_id": self._shard,
            "expected_node_digest": self._expected_node_digest,
            "session_exit_code": int(exitstatus),
            "private_environment_clear": self._private_environment_clear,
            "collected_nodeids": self._collected,
            "outcomes": [self._outcome(nodeid) for nodeid in self._collected],
        }
        encoded = (
            json.dumps(
                payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")
            )
            + "\n"
        ).encode("utf-8")
        output = self._directory / f"{self._shard}.json"
        descriptor = os.open(output, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        try:
            with os.fdopen(descriptor, "wb") as stream:
                descriptor = -1
                stream.write(encoded)
                stream.flush()
                os.fsync(stream.fileno())
        finally:
            if descriptor != -1:
                os.close(descriptor)


def _private_canary_environment_clear() -> bool:
    return all(os.getenv(name) is None for name in _PRIVATE_CANARY_ENVIRONMENT_NAMES)


def _clear_private_canary_environment() -> None:
    for name in _PRIVATE_CANARY_ENVIRONMENT_NAMES:
        os.environ.pop(name, None)


def _stage0_outcome_requested() -> bool:
    return any(
        os.getenv(name, "")
        for name in (
            _OUTCOME_DIRECTORY_ENV,
            _OUTCOME_BINDING_ENV,
            _OUTCOME_SHARD_ENV,
            _OUTCOME_EXPECTED_NODE_DIGEST_ENV,
        )
    )


def _load_stage0_safe_dotenv() -> None:
    if not _private_canary_environment_clear():
        raise pytest.UsageError(
            "Stage 0 pytest outcome process inherited private canary configuration"
        )
    for name in _PRIVATE_CANARY_ENVIRONMENT_NAMES:
        os.environ[name] = ""
    try:
        load_dotenv(REPOSITORY_ROOT / ".env", override=False)
    finally:
        _clear_private_canary_environment()
    if not _private_canary_environment_clear():
        raise pytest.UsageError(
            "Stage 0 pytest outcome process retained private canary configuration"
        )


def _configure_stage0_outcome_report(config: pytest.Config) -> None:
    values = {
        "directory": os.getenv(_OUTCOME_DIRECTORY_ENV, ""),
        "binding": os.getenv(_OUTCOME_BINDING_ENV, ""),
        "shard": os.getenv(_OUTCOME_SHARD_ENV, ""),
        "expected_node_digest": os.getenv(_OUTCOME_EXPECTED_NODE_DIGEST_ENV, ""),
    }
    if not any(values.values()):
        return
    if not all(values.values()):
        raise pytest.UsageError("Stage 0 pytest outcome configuration is incomplete")
    if not _private_canary_environment_clear():
        raise pytest.UsageError(
            "Stage 0 pytest outcome process inherited private canary configuration"
        )
    raw_directory = Path(values["directory"])
    try:
        directory = raw_directory.resolve(strict=True)
    except OSError as error:
        raise pytest.UsageError(
            "Stage 0 pytest outcome directory is unavailable"
        ) from error
    repository = REPOSITORY_ROOT.resolve()
    if (
        not raw_directory.is_absolute()
        or raw_directory.is_symlink()
        or not directory.is_dir()
        or directory == repository
        or repository in directory.parents
    ):
        raise pytest.UsageError("Stage 0 pytest outcome directory must be external")
    if re.fullmatch(r"[0-9a-f]{64}", values["binding"]) is None:
        raise pytest.UsageError("Stage 0 pytest outcome binding is invalid")
    if re.fullmatch(r"[a-z][a-z0-9-]*", values["shard"]) is None:
        raise pytest.UsageError("Stage 0 pytest outcome shard is invalid")
    if re.fullmatch(r"[0-9a-f]{64}", values["expected_node_digest"]) is None:
        raise pytest.UsageError(
            "Stage 0 pytest outcome expected node digest is invalid"
        )
    if (directory / f"{values['shard']}.json").exists():
        raise pytest.UsageError("Stage 0 pytest outcome report already exists")
    reporter = _Stage0OutcomeReporter(
        directory=directory,
        binding=values["binding"],
        shard=values["shard"],
        expected_node_digest=values["expected_node_digest"],
        private_environment_clear=_private_canary_environment_clear(),
    )
    config.pluginmanager.register(reporter, "stage0-outcome-reporter")


def _validate_catalog_mysql_runner() -> None:
    run_id = os.getenv("APP_TEST_RUN_ID", "")
    if _RUN_ID.fullmatch(run_id) is None:
        raise pytest.UsageError(
            "APP_TEST_RUN_ID must be a non-empty 32-character lowercase hex runner ID"
        )
    variable_names = (
        "APP_TEST_DATABASE_URL",
        "APP_TEST_RUNTIME_DATABASE_URL",
        "APP_TEST_BACKUP_DATABASE_URL",
        "APP_TEST_SCHEMA_UNREADABLE_DATABASE_URL",
    )
    values = {name: os.getenv(name, "").strip() for name in variable_names}
    missing = [name for name, value in values.items() if not value]
    if missing:
        raise pytest.UsageError(
            "separate migration, runtime, backup, and unreadable test URLs are required"
        )
    urls = {name: make_url(value) for name, value in values.items()}
    # Keep MySQL GET_LOCK names under its 64-byte ceiling while retaining a
    # runner-owned 64-bit random schema suffix and the full run ID in labels.
    expected_database = f"clsen_data_test_{run_id[:16]}"
    expected_compose_project = f"clsen-deployment-verify-{run_id[:12]}"
    database_scope = os.getenv("APP_TEST_DATABASE_SCOPE", "literal-loopback")
    compose_project = os.getenv("APP_TEST_COMPOSE_PROJECT", "")
    for name, url in urls.items():
        is_literal_loopback = url.host == "127.0.0.1" and url.port is not None
        is_owned_disposable_compose = (
            database_scope == "disposable-compose"
            and _DISPOSABLE_COMPOSE_PROJECT.fullmatch(compose_project) is not None
            and compose_project == expected_compose_project
            and url.host == "mysql"
            and url.port == 3306
        )
        if (
            url.drivername != "mysql+pymysql"
            or not (is_literal_loopback or is_owned_disposable_compose)
            or url.database != expected_database
            or url.query.get("charset") != "utf8mb4"
        ):
            raise pytest.UsageError(
                f"{name} must target the runner-owned literal-loopback or "
                "owned disposable-compose utf8mb4 database "
                f"{expected_database!r}"
            )
    usernames = {url.username for url in urls.values()}
    if None in usernames or len(usernames) != len(urls):
        raise pytest.UsageError(
            "migration, runtime, backup, and unreadable test accounts must be distinct"
        )

    settings = DatabaseSettings.from_url(values["APP_TEST_DATABASE_URL"])
    engine = sa.create_engine(settings.url, pool_pre_ping=True)
    try:
        with engine.connect() as connection:
            database_name, version, version_comment, character_set = connection.execute(
                sa.text(
                    "SELECT DATABASE(), @@version, @@version_comment, "
                    "@@character_set_database"
                )
            ).one()
    except Exception as error:
        raise pytest.UsageError(
            "runner-owned MySQL identity could not be verified"
        ) from error
    finally:
        engine.dispose()
    if (
        str(database_name) != expected_database
        or not str(version).startswith(("8.0.", "8.4."))
        or "mysql" not in str(version_comment).casefold()
        or str(character_set).casefold() != "utf8mb4"
    ):
        raise pytest.UsageError(
            "MySQL tests require runner-owned Oracle MySQL 8.0/8.4 with utf8mb4"
        )


def pytest_addoption(parser: pytest.Parser) -> None:
    group = parser.getgroup("mysql")
    group.addoption(
        "--run-mysql",
        action="store_true",
        default=False,
        help="run tests marked mysql when a safe test URL is configured",
    )
    group.addoption(
        "--require-mysql",
        action="store_true",
        default=False,
        help=(
            "run mysql tests and fail instead of skipping when configuration is absent"
        ),
    )


def pytest_configure(config: pytest.Config) -> None:
    if config.getoption("--run-mysql") or config.getoption("--require-mysql"):
        if _stage0_outcome_requested():
            _load_stage0_safe_dotenv()
        else:
            load_dotenv(REPOSITORY_ROOT / ".env", override=False)
    _configure_stage0_outcome_report(config)


def pytest_collection_modifyitems(
    config: pytest.Config,
    items: list[pytest.Item],
) -> None:
    mysql_items = [item for item in items if item.get_closest_marker("mysql")]
    if not mysql_items:
        return

    should_run = config.getoption("--run-mysql") or config.getoption("--require-mysql")
    if not should_run:
        marker = pytest.mark.skip(reason="pass --run-mysql to enable MySQL tests")
        for item in mysql_items:
            item.add_marker(marker)
        return

    value = os.getenv("APP_TEST_DATABASE_URL")
    if value is None or not value.strip():
        if config.getoption("--require-mysql"):
            raise pytest.UsageError(
                "APP_TEST_DATABASE_URL is required by --require-mysql"
            )
        marker = pytest.mark.skip(reason="APP_TEST_DATABASE_URL is not configured")
        for item in mysql_items:
            item.add_marker(marker)
        return

    settings = DatabaseSettings.from_url(value)
    database_name = settings.url.database or ""
    if _SAFE_TEST_DATABASE.fullmatch(database_name) is None:
        raise pytest.UsageError(
            "MySQL tests refuse databases outside clsen_data_test*; "
            f"configured database was {database_name!r}"
        )
    _validate_catalog_mysql_runner()
