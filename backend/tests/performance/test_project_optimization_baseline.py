from __future__ import annotations

import json
import os
import socket
import subprocess
import sys
import threading
import time
import urllib.error
from collections.abc import Iterator
from contextlib import AbstractContextManager, contextmanager
from dataclasses import replace
from datetime import datetime
from itertools import pairwise
from pathlib import Path
from types import SimpleNamespace
from typing import cast
from uuid import UUID, uuid4

import pytest
import sqlalchemy as sa
from app.catalog.export_service import (
    CatalogExportMaterializer,
    MySqlCatalogExportFinalizer,
)
from app.catalog.import_repository import MySqlCatalogImportRepository
from app.catalog.return_dedup_repository import MySqlReturnDedupRepository
from app.imports.storage import LocalContentStore
from app.maintenance import worker_status
from app.maintenance.barrier import hold_maintenance_write_barrier
from app.worker.catalog_exports import CatalogExportWorker, MySqlCatalogExportWorkSource
from app.worker.catalog_imports import CatalogImportWorker
from app.worker.heartbeat import (
    WorkerHeartbeatController,
    WorkerHeartbeatRepository,
)
from app.worker.observability import HEARTBEAT_SECONDS, QUEUE_NAMES, QueueName
from app.worker.outbox import OutboxSettings, PublicationOutboxWorker
from app.worker.return_dedup import ReturnDedupWorker
from app.worker.runner import WorkerRunner
from fastapi.testclient import TestClient
from sqlalchemy.engine import Engine

import tests.performance.project_optimization_baseline as baseline
from tests.integration.test_admin_management_api import (
    AdminApiContext,
)
from tests.performance.project_optimization_baseline import (
    BaselineProvenanceError,
    measure_scenario,
    measure_sql,
    verify_baseline_preflight,
    write_explain_evidence,
    write_quick_diagnostic_result,
    write_scenario_result,
)

pytest_plugins = (
    "tests.integration.conftest",
    "tests.integration.test_admin_management_api",
)

STALE_SECONDS = 30
LONG_TASK_SECONDS = 3 * HEARTBEAT_SECONDS + 5
QUICK_DIAGNOSTIC_ENV = "APP_PROJECT_OPTIMIZATION_QUICK_CHECK"
QUICK_DIAGNOSTIC_NODE = (
    "tests/performance/test_project_optimization_baseline.py::"
    "test_heartbeat_long_task_quick_check"
)

BACKEND_SCENARIOS = {
    "api-startup-readiness",
    "admin-maintenance-api",
    "queue-publication-outbox-query",
    "queue-return-dedup-query",
    "queue-catalog-import-query",
    "queue-catalog-export-query",
    "worker-idle-pass",
    "heartbeat-single-row-update",
    "heartbeat-long-task",
    "heartbeat-maintenance-barrier",
}

QUEUE_SCENARIOS: dict[str, QueueName] = {
    "queue-publication-outbox-query": "publication_outbox",
    "queue-return-dedup-query": "return_dedup",
    "queue-catalog-import-query": "catalog_import",
    "queue-catalog-export-query": "catalog_export",
}


def _require_baseline_environment() -> Path:
    required = (
        "APP_PROJECT_OPTIMIZATION_RUN_DIR",
        "APP_RELEASE_SOURCE_SHA",
        "APP_TEST_DATABASE_URL",
        "APP_TEST_RUNTIME_DATABASE_URL",
    )
    missing = [name for name in required if not os.getenv(name, "").strip()]
    if missing:
        pytest.fail(
            "project optimization baseline requires " + ", ".join(missing),
            pytrace=False,
        )
    run_directory = Path(os.environ["APP_PROJECT_OPTIMIZATION_RUN_DIR"]).resolve()
    repository_root = Path(__file__).resolve().parents[3].resolve()
    if (
        not run_directory.is_dir()
        or run_directory == repository_root
        or repository_root in run_directory.parents
    ):
        pytest.fail(
            "baseline evidence directory must be external and pre-created",
            pytrace=False,
        )
    try:
        verify_baseline_preflight(
            run_directory,
            approved_scenarios=BACKEND_SCENARIOS,
        )
    except BaselineProvenanceError as error:
        pytest.fail(str(error), pytrace=False)
    return run_directory


def _require_quick_diagnostic_environment() -> Path:
    required = (
        "APP_PROJECT_OPTIMIZATION_EVIDENCE_ROOT",
        "APP_PROJECT_OPTIMIZATION_RUN_DIR",
        "APP_RELEASE_SOURCE_SHA",
        "APP_TEST_DATABASE_URL",
        "APP_TEST_RUNTIME_DATABASE_URL",
    )
    missing = [name for name in required if not os.getenv(name, "").strip()]
    if missing:
        pytest.fail(
            "quick diagnostic requires " + ", ".join(missing),
            pytrace=False,
        )
    repository_root = Path(__file__).resolve().parents[3].resolve()
    evidence_root = Path(os.environ["APP_PROJECT_OPTIMIZATION_EVIDENCE_ROOT"]).resolve()
    run_directory = Path(os.environ["APP_PROJECT_OPTIMIZATION_RUN_DIR"]).resolve()
    if (
        not evidence_root.is_dir()
        or not run_directory.is_dir()
        or evidence_root == repository_root
        or repository_root in evidence_root.parents
        or run_directory.parent != evidence_root
    ):
        pytest.fail(
            "quick diagnostic evidence directory must be external and isolated",
            pytrace=False,
        )
    try:
        evidence_entries = {path.name for path in evidence_root.iterdir()}
    except OSError as error:
        pytest.fail(
            f"quick diagnostic evidence directory is unreadable: {error}",
            pytrace=False,
        )
    if evidence_entries != {"diagnostic-identity.json", run_directory.name}:
        pytest.fail(
            "quick diagnostic evidence directory contains formal or unrelated "
            "artifacts",
            pytrace=False,
        )
    try:
        run_identity = json.loads(
            (run_directory / "run-identity.json").read_text(encoding="utf-8")
        )
        metadata = json.loads(
            (evidence_root / "diagnostic-identity.json").read_text(encoding="utf-8")
        )
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as error:
        pytest.fail(f"quick diagnostic identity is unreadable: {error}", pytrace=False)
    if (
        not isinstance(run_identity, dict)
        or run_identity.get("run_id") != run_directory.name
        or run_identity.get("source_sha") != os.environ["APP_RELEASE_SOURCE_SHA"]
        or run_identity.get("status") != "prepared"
    ):
        pytest.fail("quick diagnostic run identity is invalid", pytrace=False)
    if (
        not isinstance(metadata, dict)
        or metadata.get("mode") != "diagnostic-quick"
        or metadata.get("formal_evidence") is not False
        or metadata.get("finalize_run") is not False
        or metadata.get("selected_node") != QUICK_DIAGNOSTIC_NODE
        or Path(str(metadata.get("run_directory"))).resolve() != run_directory
    ):
        pytest.fail("quick diagnostic metadata is invalid", pytrace=False)
    if any(path.name != "run-identity.json" for path in run_directory.iterdir()):
        pytest.fail(
            "quick diagnostic run directory is not initially empty",
            pytrace=False,
        )
    return run_directory


def _run_baseline_preflight(request: pytest.FixtureRequest) -> None:
    if request.node.get_closest_marker("mysql") is not None:
        nodeid = request.node.nodeid.removeprefix("backend/")
        if nodeid == QUICK_DIAGNOSTIC_NODE and os.getenv(QUICK_DIAGNOSTIC_ENV) != "1":
            pytest.fail(
                "quick diagnostic node requires explicit quick mode",
                pytrace=False,
            )
        if os.getenv(QUICK_DIAGNOSTIC_ENV) == "1":
            if nodeid != QUICK_DIAGNOSTIC_NODE:
                pytest.fail(
                    "quick diagnostic mode only permits its explicit quick node",
                    pytrace=False,
                )
            _require_quick_diagnostic_environment()
        else:
            _require_baseline_environment()


@pytest.fixture(autouse=True)
def baseline_preflight_gate(request: pytest.FixtureRequest) -> Iterator[None]:
    """Run provenance checks before any MySQL-marked test can create fixtures."""

    _run_baseline_preflight(request)
    yield


@pytest.fixture()
def baseline_run_dir(
    baseline_preflight_gate: None,
    mysql_engine: Engine,
    monkeypatch: pytest.MonkeyPatch,
) -> Path:
    del baseline_preflight_gate
    run_directory = Path(os.environ["APP_PROJECT_OPTIMIZATION_RUN_DIR"]).resolve()
    with mysql_engine.connect() as connection:
        version = str(connection.scalar(sa.text("SELECT VERSION()")))
    mysql_version = next(
        (
            candidate
            for candidate in ("8.0", "8.4")
            if version.startswith(f"{candidate}.")
        ),
        None,
    )
    if mysql_version is None:
        pytest.fail("baseline requires Oracle MySQL 8.0 or 8.4", pytrace=False)
    monkeypatch.setenv("APP_BASELINE_MYSQL_VERSION", mysql_version)
    return run_directory


@pytest.fixture()
def quick_diagnostic_run_dir(
    baseline_preflight_gate: None,
    mysql_engine: Engine,
    monkeypatch: pytest.MonkeyPatch,
) -> Path:
    del baseline_preflight_gate
    with mysql_engine.connect() as connection:
        version = str(connection.scalar(sa.text("SELECT VERSION()")))
    mysql_version = next(
        (
            candidate
            for candidate in ("8.0", "8.4")
            if version.startswith(f"{candidate}.")
        ),
        None,
    )
    if mysql_version is None:
        pytest.fail("quick diagnostic requires Oracle MySQL 8.0 or 8.4")
    monkeypatch.setenv("APP_BASELINE_MYSQL_VERSION", mysql_version)
    return Path(os.environ["APP_PROJECT_OPTIMIZATION_RUN_DIR"]).resolve()


class OwnedUvicorn(AbstractContextManager["OwnedUvicorn"]):
    def __init__(self, *, runtime_database_url: str) -> None:
        self._runtime_database_url = runtime_database_url
        self._process: subprocess.Popen[bytes] | None = None
        self.pid: int | None = None
        self._port: int | None = None

    def __exit__(
        self,
        _exception_type: object,
        _exception: object,
        _traceback: object,
    ) -> None:
        self._terminate_owned_pid()

    def restart_until_ready_ms(self) -> float:
        self._terminate_owned_pid()
        self._port = _owned_free_port()
        environment = os.environ.copy()
        environment.update(
            {
                "APP_DATABASE_URL": self._runtime_database_url,
                "APP_ENVIRONMENT": "test",
                "APP_LOG_LEVEL": "WARNING",
            }
        )
        started = time.perf_counter_ns()
        self._process = subprocess.Popen(
            [
                sys.executable,
                "-m",
                "uvicorn",
                "app.main:app",
                "--host",
                "127.0.0.1",
                "--port",
                str(self._port),
            ],
            cwd=Path(__file__).resolve().parents[2],
            env=environment,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        self.pid = self._process.pid
        ready_url = f"http://127.0.0.1:{self._port}/api/health/ready"
        deadline = time.monotonic() + 20.0
        while time.monotonic() < deadline:
            if self._process.poll() is not None:
                raise RuntimeError("owned Uvicorn process exited before readiness")
            try:
                from tests.performance.project_optimization_baseline import measure_http

                measure_http(ready_url, timeout_seconds=0.5)
                return (time.perf_counter_ns() - started) / 1_000_000
            except OSError, RuntimeError, urllib.error.URLError:
                time.sleep(0.05)
        raise RuntimeError("owned Uvicorn process did not become ready")

    def _terminate_owned_pid(self) -> None:
        process = self._process
        if process is None:
            return
        try:
            if process.poll() is None:
                if os.name == "nt":
                    completed = subprocess.run(
                        ["taskkill", "/PID", str(process.pid), "/T", "/F"],
                        check=False,
                        stdout=subprocess.DEVNULL,
                        stderr=subprocess.DEVNULL,
                    )
                    if completed.returncode != 0:
                        raise RuntimeError("owned Uvicorn process tree could not stop")
                    process.wait(timeout=10)
                else:
                    process.terminate()
                    try:
                        process.wait(timeout=10)
                    except subprocess.TimeoutExpired:
                        process.kill()
                        process.wait(timeout=10)
        finally:
            self._process = None
            self.pid = None


def _owned_free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
        probe.bind(("127.0.0.1", 0))
        return int(probe.getsockname()[1])


@pytest.fixture()
def owned_uvicorn(baseline_run_dir: Path) -> Iterator[OwnedUvicorn]:
    del baseline_run_dir
    with OwnedUvicorn(
        runtime_database_url=os.environ["APP_TEST_RUNTIME_DATABASE_URL"]
    ) as owned:
        yield owned


def measured_testclient_get_ms(client: TestClient, path: str) -> float:
    started = time.perf_counter_ns()
    response = client.get(path)
    elapsed = (time.perf_counter_ns() - started) / 1_000_000
    assert response.status_code == 200, response.text
    return elapsed


@pytest.fixture()
def worker_telemetry(
    mysql_engine: Engine,
) -> Iterator[WorkerHeartbeatController]:
    controller = WorkerHeartbeatController(
        WorkerHeartbeatRepository(mysql_engine),
        instance_id=uuid4(),
        build_id="stage2-performance",
    )
    controller.start()
    try:
        yield controller
    finally:
        controller.stop()


@pytest.fixture()
def empty_worker_runner(
    mysql_engine: Engine,
    tmp_path: Path,
    worker_telemetry: WorkerHeartbeatController,
) -> WorkerRunner:
    storage = LocalContentStore(tmp_path / "stage0-worker-storage", 1_048_576)
    return WorkerRunner(
        return_dedup=ReturnDedupWorker(MySqlReturnDedupRepository(mysql_engine)),
        outbox=PublicationOutboxWorker(
            mysql_engine,
            OutboxSettings(
                worker_id="stage0-worker-baseline",
                max_attempts=5,
            ),
        ),
        catalog_exports=CatalogExportWorker(
            source=MySqlCatalogExportWorkSource(mysql_engine),
            materializer=CatalogExportMaterializer(
                store=storage,
                finalizer=MySqlCatalogExportFinalizer(mysql_engine),
            ),
        ),
        catalog_imports=CatalogImportWorker(
            MySqlCatalogImportRepository(mysql_engine), storage
        ),
        telemetry=worker_telemetry,
    )


class _RecordingWorkerHeartbeatRepository(WorkerHeartbeatRepository):
    def __init__(self, engine: Engine) -> None:
        super().__init__(engine)
        self._observation_lock = threading.Lock()
        self._observations: dict[UUID, list[int]] = {}

    def heartbeat(
        self,
        *,
        instance_id: UUID,
        sequence: int,
        result_code: str,
    ) -> datetime:
        heartbeat_at = super().heartbeat(
            instance_id=instance_id,
            sequence=sequence,
            result_code=result_code,
        )
        with self._observation_lock:
            self._observations.setdefault(instance_id, []).append(time.monotonic_ns())
        return heartbeat_at

    def observations_between(
        self,
        *,
        instance_id: UUID,
        started: int,
        completed: int,
    ) -> list[int]:
        with self._observation_lock:
            return [
                observed
                for observed in self._observations.get(instance_id, ())
                if started < observed < completed
            ]


class HeartbeatProbe(AbstractContextManager["HeartbeatProbe"]):
    def __init__(self, engine: Engine) -> None:
        self._engine = engine
        self._repository = _RecordingWorkerHeartbeatRepository(engine)
        self._manual_instance_id = uuid4()
        self._controller_instance_id = uuid4()
        self._manual_sequence = 0
        self._manual_registered = False
        self._controller = WorkerHeartbeatController(
            self._repository,
            instance_id=self._controller_instance_id,
            build_id="stage2-performance",
        )
        self._barrier_measurement: dict[str, float] | None = None

    def __enter__(self) -> HeartbeatProbe:
        try:
            self._repository.register(
                instance_id=self._manual_instance_id,
                role="local_worker",
                build_id="stage2-performance-manual",
                supported_queues=QUEUE_NAMES,
            )
            self._manual_registered = True
            self._controller.start()
        except BaseException:
            self._stop_instances()
            raise
        return self

    def __exit__(
        self,
        _exception_type: object,
        _exception: object,
        _traceback: object,
    ) -> None:
        self._stop_instances()

    def _stop_instances(self) -> None:
        try:
            self._controller.stop()
        finally:
            if self._manual_registered:
                try:
                    self._repository.stop(
                        instance_id=self._manual_instance_id,
                        result_code="worker_stopped",
                    )
                finally:
                    self._manual_registered = False

    def update_ms(self) -> float:
        self._manual_sequence += 1
        started = time.perf_counter_ns()
        self._repository.heartbeat(
            instance_id=self._manual_instance_id,
            sequence=self._manual_sequence,
            result_code="heartbeat_succeeded",
        )
        return (time.perf_counter_ns() - started) / 1_000_000

    def long_task_max_interval_ms(self) -> float:
        started = time.monotonic_ns()
        time.sleep(LONG_TASK_SECONDS)
        completed = time.monotonic_ns()
        observations = [
            started,
            *self._repository.observations_between(
                instance_id=self._controller_instance_id,
                started=started,
                completed=completed,
            ),
            completed,
        ]
        assert len(observations) >= 5
        intervals = [
            (later - earlier) / 1_000_000 for earlier, later in pairwise(observations)
        ]
        maximum = max(intervals)
        assert maximum < STALE_SECONDS * 1_000
        return maximum

    def long_task_observation(self) -> dict[str, object]:
        started = time.monotonic_ns()
        time.sleep(LONG_TASK_SECONDS)
        completed = time.monotonic_ns()
        observations = [
            started,
            *self._repository.observations_between(
                instance_id=self._controller_instance_id,
                started=started,
                completed=completed,
            ),
            completed,
        ]
        assert len(observations) >= 5
        intervals = [
            (later - earlier) / 1_000_000 for earlier, later in pairwise(observations)
        ]
        maximum = max(intervals)
        assert maximum < STALE_SECONDS * 1_000
        return {
            "window_seconds": LONG_TASK_SECONDS,
            "heartbeat_seconds": HEARTBEAT_SECONDS,
            "stale_seconds": STALE_SECONDS,
            "observation_count": len(observations),
            "intervals_ms": intervals,
            "max_interval_ms": maximum,
            "result": "pass",
        }

    def barrier_release_to_update_ms(self) -> float:
        complete = threading.Event()
        errors: list[BaseException] = []
        completed_at = 0

        def write_after_release() -> None:
            nonlocal completed_at
            try:
                self.update_ms()
                completed_at = time.perf_counter_ns()
            except BaseException as error:
                errors.append(error)
            finally:
                complete.set()

        with hold_maintenance_write_barrier(self._engine, timeout_seconds=0):
            blocked_started = time.perf_counter_ns()
            writer = threading.Thread(target=write_after_release, daemon=True)
            writer.start()
            assert not complete.wait(timeout=0.05)
        released_at = time.perf_counter_ns()
        assert complete.wait(timeout=5), (
            "probe write did not complete after barrier release"
        )
        writer.join(timeout=1)
        assert not errors
        self._barrier_measurement = {
            "blocked_duration_ms": (completed_at - blocked_started) / 1_000_000,
            "first_post_release_update_ms": max(
                0.0, (completed_at - released_at) / 1_000_000
            ),
        }
        return self._barrier_measurement["first_post_release_update_ms"]

    def consume_barrier_measurement(self) -> dict[str, float]:
        if self._barrier_measurement is None:
            raise RuntimeError("barrier measurement is unavailable")
        measurement = self._barrier_measurement
        self._barrier_measurement = None
        return measurement


@pytest.fixture()
def heartbeat_probe(mysql_engine: Engine) -> Iterator[HeartbeatProbe]:
    with HeartbeatProbe(mysql_engine) as probe:
        yield probe


@pytest.mark.mysql
def test_api_startup_readiness_baseline(
    baseline_run_dir: Path,
    owned_uvicorn: OwnedUvicorn,
) -> None:
    result = measure_scenario(
        "api-startup-readiness", owned_uvicorn.restart_until_ready_ms, unit="ms"
    )
    write_scenario_result(baseline_run_dir, result)


@pytest.mark.mysql
def test_admin_maintenance_api_baseline(
    admin_api: AdminApiContext,
    baseline_run_dir: Path,
) -> None:
    def operation() -> float:
        return measured_testclient_get_ms(admin_api.client, "/api/admin/maintenance")

    write_scenario_result(
        baseline_run_dir,
        measure_scenario("admin-maintenance-api", operation, unit="ms"),
    )


def _queue_explain(
    connection: sa.Connection,
    *,
    scenario_id: str,
    statement: sa.TextClause,
    parameters: dict[str, object],
    run_directory: Path,
) -> dict[str, object]:
    raw_plan = str(
        connection.scalar(
            sa.text(f"EXPLAIN FORMAT=JSON {statement.text}"),
            parameters,
        )
    )
    plan = json.loads(raw_plan)
    assert not baseline._unbounded_cartesian_join(plan)
    external_path = write_explain_evidence(
        run_directory,
        scenario_id=scenario_id,
        raw_plan=raw_plan,
    )
    return {
        "format": "JSON",
        "unbounded_cartesian_join": False,
        "external_evidence": external_path.name,
    }


@pytest.mark.mysql
@pytest.mark.parametrize("scenario_id", sorted(QUEUE_SCENARIOS))
def test_queue_query_baseline(
    mysql_engine: Engine,
    scenario_id: str,
    baseline_run_dir: Path,
) -> None:
    with mysql_engine.connect() as connection:
        queue_name = QUEUE_SCENARIOS[scenario_id]
        statement = worker_status._QUEUE_SQL[queue_name]
        observed_at = connection.scalar(sa.text("SELECT UTC_TIMESTAMP(6)"))
        assert isinstance(observed_at, datetime)
        parameters: dict[str, object] = {"observed_at": observed_at}
        if queue_name == "publication_outbox":
            parameters["outbox_stale_seconds"] = 300
        explain = _queue_explain(
            connection,
            scenario_id=scenario_id,
            statement=statement,
            parameters=parameters,
            run_directory=baseline_run_dir,
        )
        result = measure_scenario(
            scenario_id,
            lambda: measure_sql(connection, statement, parameters),
            unit="ms",
        )
    write_scenario_result(baseline_run_dir, replace(result, explain=explain))


@pytest.mark.mysql
def test_worker_idle_pass_baseline(
    empty_worker_runner: WorkerRunner,
    baseline_run_dir: Path,
) -> None:
    def operation() -> float:
        started = time.perf_counter_ns()
        worker_pass = empty_worker_runner.run_once()
        elapsed = (time.perf_counter_ns() - started) / 1_000_000
        assert worker_pass.did_work is False
        return elapsed

    write_scenario_result(
        baseline_run_dir,
        measure_scenario("worker-idle-pass", operation, unit="ms"),
    )


@pytest.mark.mysql
def test_heartbeat_candidate_baselines(
    heartbeat_probe: HeartbeatProbe,
    baseline_run_dir: Path,
) -> None:
    for scenario_id, operation in (
        ("heartbeat-single-row-update", heartbeat_probe.update_ms),
        ("heartbeat-long-task", heartbeat_probe.long_task_max_interval_ms),
        ("heartbeat-maintenance-barrier", heartbeat_probe.barrier_release_to_update_ms),
    ):
        result = measure_scenario(
            scenario_id,
            operation,
            unit="ms",
            measurement=(
                heartbeat_probe.consume_barrier_measurement
                if scenario_id == "heartbeat-maintenance-barrier"
                else None
            ),
        )
        write_scenario_result(baseline_run_dir, result)


@pytest.mark.mysql
def test_heartbeat_long_task_quick_check(
    mysql_engine: Engine,
    quick_diagnostic_run_dir: Path,
) -> None:
    observations: list[dict[str, object]] = []
    for _ in range(3):
        with HeartbeatProbe(mysql_engine) as probe:
            observations.append(probe.long_task_observation())
    write_quick_diagnostic_result(quick_diagnostic_run_dir, observations)


@pytest.mark.parametrize("node_prefix", ["", "backend/"])
def test_quick_node_requires_explicit_quick_mode(
    monkeypatch: pytest.MonkeyPatch,
    node_prefix: str,
) -> None:
    monkeypatch.delenv(QUICK_DIAGNOSTIC_ENV, raising=False)
    request = SimpleNamespace(
        node=SimpleNamespace(
            nodeid=node_prefix + QUICK_DIAGNOSTIC_NODE,
            get_closest_marker=lambda name: object() if name == "mysql" else None,
        )
    )

    with pytest.raises(pytest.fail.Exception, match="explicit quick mode"):
        _run_baseline_preflight(cast(pytest.FixtureRequest, request))


def test_quick_environment_rejects_formal_evidence_artifacts(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    evidence_root = tmp_path / "evidence"
    run_directory = evidence_root / "stage0-0123456789ab"
    evidence_root.mkdir()
    run_directory.mkdir()
    (run_directory / "run-identity.json").write_text(
        json.dumps(
            {
                "run_id": run_directory.name,
                "source_sha": "a" * 40,
                "status": "prepared",
            }
        ),
        encoding="utf-8",
    )
    (evidence_root / "diagnostic-identity.json").write_text("{}", encoding="utf-8")
    (evidence_root / "run-summary.json").write_text("{}", encoding="utf-8")
    monkeypatch.setenv("APP_PROJECT_OPTIMIZATION_EVIDENCE_ROOT", str(evidence_root))
    monkeypatch.setenv("APP_PROJECT_OPTIMIZATION_RUN_DIR", str(run_directory))
    monkeypatch.setenv("APP_RELEASE_SOURCE_SHA", "a" * 40)
    monkeypatch.setenv("APP_TEST_DATABASE_URL", "mysql+pymysql://synthetic")
    monkeypatch.setenv(
        "APP_TEST_RUNTIME_DATABASE_URL", "mysql+pymysql://synthetic-runtime"
    )
    monkeypatch.setenv(QUICK_DIAGNOSTIC_ENV, "1")

    with pytest.raises(
        pytest.fail.Exception,
        match="formal or unrelated artifacts",
    ):
        _require_quick_diagnostic_environment()


def test_measure_scenario_uses_three_warmups_then_twenty_samples_for_three_rounds() -> (
    None
):
    calls = 0

    def operation() -> float:
        nonlocal calls
        calls += 1
        return float(calls)

    result = measure_scenario("synthetic-contract", operation, unit="ms")

    assert calls == 69
    assert len(result.rounds) == 3
    assert all(round_["sample_count"] == 20 for round_ in result.rounds)


def test_scenario_writer_never_overwrites(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("APP_RELEASE_SOURCE_SHA", raising=False)
    result = measure_scenario("synthetic-contract", lambda: 1.0, unit="ms")

    path = write_scenario_result(tmp_path, result)

    payload = json.loads(path.read_text(encoding="utf-8"))
    assert payload["scenario_id"] == "synthetic-contract"
    with pytest.raises(FileExistsError):
        write_scenario_result(tmp_path, result)


def test_quick_diagnostic_writer_is_isolated(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("APP_BASELINE_MYSQL_VERSION", "8.0")
    monkeypatch.setattr(
        baseline,
        "_evidence_identity",
        lambda: {
            "source_sha": "a" * 40,
            "git_tree": "b" * 40,
            "fixture_id": "stage0-worker-synthetic-v1",
            "runner_digest": "c" * 64,
            "host_environment_digest": "d" * 64,
            "mysql_version": "8.0",
        },
    )
    observations = [
        {
            "window_seconds": 35,
            "heartbeat_seconds": 10,
            "stale_seconds": 30,
            "observation_count": 5,
            "intervals_ms": [10_000.0] * 4,
            "max_interval_ms": 10_000.0,
            "result": "pass",
        }
    ] * 3

    path = write_quick_diagnostic_result(tmp_path, observations)
    payload = json.loads(path.read_text(encoding="utf-8"))
    assert path.name == "quick-diagnostic-8.0-heartbeat-long-task.json"
    assert payload["mode"] == "diagnostic-quick"
    assert payload["formal_evidence"] is False
    assert payload["check_count"] == 3
    assert "p50" not in payload and "p95" not in payload


def test_formal_preflight_rejects_quick_diagnostic_evidence(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    run_directory = tmp_path / "stage0-0123456789ab"
    run_directory.mkdir()
    (run_directory / "run-identity.json").write_text(
        json.dumps(
            {
                "run_id": run_directory.name,
                "source_sha": "a" * 40,
                "status": "prepared",
            }
        ),
        encoding="utf-8",
    )
    (run_directory / "quick-diagnostic-8.0-heartbeat-long-task.json").write_text(
        "{}",
        encoding="utf-8",
    )
    monkeypatch.setattr(
        baseline,
        "_release_identity",
        lambda: {
            "source_sha": "a" * 40,
            "git_tree": "b" * 40,
            "fixture_id": "stage0-worker-synthetic-v1",
            "runner_digest": "c" * 64,
            "host_environment_digest": "d" * 64,
        },
    )

    with pytest.raises(BaselineProvenanceError, match="quick diagnostic"):
        verify_baseline_preflight(
            run_directory,
            approved_scenarios=BACKEND_SCENARIOS,
        )


def test_measure_scenario_retains_only_measured_pairs_in_protocol_order() -> None:
    calls = 0

    def operation() -> float:
        nonlocal calls
        calls += 1
        return float(calls)

    def measurement() -> dict[str, object]:
        return {
            "blocked_duration_ms": float(calls),
            "first_post_release_update_ms": float(calls) / 10,
        }

    result = measure_scenario(
        "synthetic-contract",
        operation,
        unit="ms",
        measurement=measurement,
    )

    assert result.rounds[0]["samples"] == [float(value) for value in range(4, 24)]
    assert result.rounds[0]["p50"] == 13.5
    assert result.rounds[0]["p95"] == 22.0
    assert result.rounds[0]["max"] == 23.0
    assert result.measurement_evidence == {
        "measured_rounds": [
            [
                {
                    "blocked_duration_ms": float(value),
                    "first_post_release_update_ms": float(value) / 10,
                }
                for value in range(first, first + 20)
            ]
            for first in (4, 27, 50)
        ]
    }


def test_release_identity_rejects_a_mismatched_checkout_head(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source_sha = "a" * 40
    monkeypatch.setenv("APP_RELEASE_SOURCE_SHA", source_sha)

    def fake_run(
        arguments: list[str], **_kwargs: object
    ) -> subprocess.CompletedProcess[str]:
        return subprocess.CompletedProcess(arguments, 0, stdout=f"{'b' * 40}\n")

    monkeypatch.setattr(subprocess, "run", fake_run)

    with pytest.raises(
        BaselineProvenanceError,
        match="does not match checkout HEAD",
    ):
        baseline._release_identity()


def test_release_identity_rejects_a_dirty_checkout(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source_sha = "a" * 40
    monkeypatch.setenv("APP_RELEASE_SOURCE_SHA", source_sha)

    def fake_run(
        arguments: list[str], **_kwargs: object
    ) -> subprocess.CompletedProcess[str]:
        if arguments[1:3] == ["rev-parse", "HEAD"]:
            output = source_sha
        elif arguments[1:3] == ["status", "--porcelain=v1"]:
            output = " M backend/tests/performance/project_optimization_baseline.py"
        else:
            raise AssertionError(arguments)
        return subprocess.CompletedProcess(arguments, 0, stdout=output)

    monkeypatch.setattr(subprocess, "run", fake_run)

    with pytest.raises(BaselineProvenanceError, match="checkout must be clean"):
        baseline._release_identity()


def test_release_identity_allows_only_untracked_data_and_uses_canonical_runner(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source_sha = "a" * 40
    canonical = ["canonical-one", "canonical-two"]
    (tmp_path / "scripts").mkdir()
    (tmp_path / "scripts" / "ci-suite-manifest.json").write_text(
        json.dumps(
            {
                "release_suites": {
                    "performance": {"runner_paths": ["old-runner"]},
                    "project-optimization-baseline": {"runner_paths": canonical},
                }
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setenv("APP_RELEASE_SOURCE_SHA", source_sha)
    monkeypatch.setattr(baseline, "_REPOSITORY_ROOT", tmp_path)
    requested: list[list[str]] = []

    def fake_run(
        arguments: list[str], **_kwargs: object
    ) -> subprocess.CompletedProcess[str]:
        requested.append(arguments)
        if arguments[1:3] == ["rev-parse", "HEAD"]:
            output = source_sha
        elif arguments[1:3] == ["status", "--porcelain=v1"]:
            output = "?? data/user-owned.xlsx\n"
        elif arguments[-1].endswith("^{tree}"):
            output = "b" * 40
        elif arguments[1:3] == ["rev-parse", f"{source_sha}:canonical-one"]:
            output = "c" * 40
        elif arguments[1:3] == ["rev-parse", f"{source_sha}:canonical-two"]:
            output = "d" * 40
        elif arguments[0] in {"node", "pnpm", "pnpm.cmd"}:
            output = "test-version"
        else:
            raise AssertionError(arguments)
        return subprocess.CompletedProcess(arguments, 0, stdout=output)

    monkeypatch.setattr(subprocess, "run", fake_run)
    identity = baseline._release_identity()
    assert identity["source_sha"] == source_sha
    blob_specs = {arguments[-1] for arguments in requested if ":" in arguments[-1]}
    assert blob_specs == {f"{source_sha}:{path}" for path in canonical}

    def dirty_run(
        arguments: list[str], **kwargs: object
    ) -> subprocess.CompletedProcess[str]:
        result = fake_run(arguments, **kwargs)
        if arguments[1:3] == ["status", "--porcelain=v1"]:
            return subprocess.CompletedProcess(
                arguments, 0, stdout="?? database/not-authorized.sql\n"
            )
        return result

    monkeypatch.setattr(subprocess, "run", dirty_run)
    with pytest.raises(BaselineProvenanceError, match="checkout must be clean"):
        baseline._release_identity()


def test_host_environment_uses_the_windows_pnpm_command_shim(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    commands: list[list[str]] = []

    def checked_output(arguments: list[str]) -> str:
        commands.append(arguments)
        return "test-version"

    monkeypatch.setattr(sys, "platform", "win32")

    baseline._host_environment_digest(checked_output)

    assert ["pnpm.cmd", "--version"] in commands


def _prepared_run(tmp_path: Path, *, source_sha: str) -> Path:
    run_directory = tmp_path / "stage0-123456789abc"
    run_directory.mkdir()
    (run_directory / "run-identity.json").write_text(
        json.dumps(
            {
                "run_id": run_directory.name,
                "source_sha": source_sha,
                "status": "prepared",
            }
        ),
        encoding="utf-8",
    )
    return run_directory


def _complete_scenario_payload(
    identity: dict[str, str],
    *,
    mysql_version: str,
    scenario_id: str,
) -> dict[str, object]:
    round_ = {
        "sample_count": 20,
        "samples": [float(value) for value in range(20)],
        "p50": 9.5,
        "p95": 18.0,
        "max": 19.0,
    }
    return {
        **identity,
        "mysql_version": mysql_version,
        "schema_version": 1,
        "scenario_id": scenario_id,
        "unit": "ms",
        "warmup_samples": 3,
        "measured_samples": 20,
        "round_count": 3,
        "rounds": [round_.copy() for _ in range(3)],
    }


def _barrier_measurement_evidence() -> dict[str, object]:
    return {
        "measured_rounds": [
            [
                {
                    "blocked_duration_ms": float(sample + 1),
                    "first_post_release_update_ms": float(sample) / 10,
                }
                for sample in range(20)
            ]
            for _round in range(3)
        ]
    }


def _queue_explain_reference(
    *, mysql_version: str, scenario_id: str
) -> dict[str, object]:
    return {
        "format": "JSON",
        "unbounded_cartesian_join": False,
        "external_evidence": f"external-explain-{mysql_version}-{scenario_id}.json",
    }


def _raw_explain_payload(
    identity: dict[str, str],
    *,
    mysql_version: str,
    scenario_id: str,
    raw_plan: str,
) -> dict[str, object]:
    return {
        **identity,
        "mysql_version": mysql_version,
        "schema_version": 1,
        "scenario_id": scenario_id,
        "format": "JSON",
        "raw_plan": raw_plan,
    }


def test_marked_preflight_gate_executes_before_any_mutating_fixture(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    events: list[str] = []

    class NodeDouble:
        nodeid = (
            "tests/performance/test_project_optimization_baseline.py::"
            "test_marked_preflight_gate_executes_before_any_mutating_fixture"
        )

        def get_closest_marker(self, name: str) -> object | None:
            return object() if name == "mysql" else None

    class RequestDouble:
        node = NodeDouble()

    monkeypatch.setattr(
        "tests.performance.test_project_optimization_baseline._require_baseline_environment",
        lambda: events.append("preflight"),
    )
    _run_baseline_preflight(cast(pytest.FixtureRequest, RequestDouble()))
    events.append("mutation")
    assert events == ["preflight", "mutation"]


def test_preflight_rejects_filename_and_protocol_mismatches(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    identity = {
        "source_sha": "a" * 40,
        "git_tree": "b" * 40,
        "fixture_id": "stage0-worker-synthetic-v1",
        "runner_digest": "c" * 64,
        "host_environment_digest": "d" * 64,
    }
    run_directory = _prepared_run(tmp_path, source_sha=identity["source_sha"])
    monkeypatch.setattr(baseline, "_release_identity", lambda: identity)
    evidence_path = run_directory / "backend-8.0-heartbeat-single-row-update.json"
    evidence_path.write_text(
        json.dumps(
            _complete_scenario_payload(
                identity,
                mysql_version="8.0",
                scenario_id="heartbeat-long-task",
            )
        ),
        encoding="utf-8",
    )

    with pytest.raises(BaselineProvenanceError, match="filename identity"):
        verify_baseline_preflight(
            run_directory,
            approved_scenarios={"heartbeat-single-row-update"},
        )

    malformed = _complete_scenario_payload(
        identity,
        mysql_version="8.0",
        scenario_id="heartbeat-single-row-update",
    )
    malformed["rounds"] = []
    evidence_path.write_text(json.dumps(malformed), encoding="utf-8")
    with pytest.raises(BaselineProvenanceError, match="rounds are invalid"):
        verify_baseline_preflight(
            run_directory,
            approved_scenarios={"heartbeat-single-row-update"},
        )

    invalid_unit = _complete_scenario_payload(
        identity,
        mysql_version="8.0",
        scenario_id="heartbeat-single-row-update",
    )
    invalid_unit["unit"] = "seconds"
    evidence_path.write_text(json.dumps(invalid_unit), encoding="utf-8")
    with pytest.raises(BaselineProvenanceError, match="protocol is invalid"):
        verify_baseline_preflight(
            run_directory,
            approved_scenarios={"heartbeat-single-row-update"},
        )

    negative_sample = _complete_scenario_payload(
        identity,
        mysql_version="8.0",
        scenario_id="heartbeat-single-row-update",
    )
    negative_rounds = cast(list[dict[str, object]], negative_sample["rounds"])
    cast(list[float], negative_rounds[0]["samples"])[0] = -1.0
    evidence_path.write_text(json.dumps(negative_sample), encoding="utf-8")
    with pytest.raises(BaselineProvenanceError, match="rounds are invalid"):
        verify_baseline_preflight(
            run_directory,
            approved_scenarios={"heartbeat-single-row-update"},
        )

    fabricated_summary = _complete_scenario_payload(
        identity,
        mysql_version="8.0",
        scenario_id="heartbeat-single-row-update",
    )
    fabricated_rounds = cast(list[dict[str, object]], fabricated_summary["rounds"])
    fabricated_rounds[0]["p95"] = 999.0
    evidence_path.write_text(json.dumps(fabricated_summary), encoding="utf-8")
    with pytest.raises(BaselineProvenanceError, match="summaries are invalid"):
        verify_baseline_preflight(
            run_directory,
            approved_scenarios={"heartbeat-single-row-update"},
        )


@pytest.mark.parametrize(
    "negative_field",
    ("blocked_duration_ms", "first_post_release_update_ms"),
)
def test_preflight_rejects_negative_barrier_measurement_evidence(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    negative_field: str,
) -> None:
    identity = {
        "source_sha": "a" * 40,
        "git_tree": "b" * 40,
        "fixture_id": "stage0-worker-synthetic-v1",
        "runner_digest": "c" * 64,
        "host_environment_digest": "d" * 64,
    }
    scenario_id = "heartbeat-maintenance-barrier"
    run_directory = _prepared_run(tmp_path, source_sha=identity["source_sha"])
    monkeypatch.setattr(baseline, "_release_identity", lambda: identity)
    evidence_path = run_directory / f"backend-8.0-{scenario_id}.json"
    payload = _complete_scenario_payload(
        identity,
        mysql_version="8.0",
        scenario_id=scenario_id,
    )
    payload["measurement_evidence"] = _barrier_measurement_evidence()
    evidence_path.write_text(json.dumps(payload), encoding="utf-8")

    verify_baseline_preflight(run_directory, approved_scenarios={scenario_id})

    measurement_evidence = cast(dict[str, object], payload["measurement_evidence"])
    measured_rounds = cast(
        list[list[dict[str, float]]], measurement_evidence["measured_rounds"]
    )
    measured_rounds[0][0][negative_field] = -0.01
    evidence_path.write_text(json.dumps(payload), encoding="utf-8")

    with pytest.raises(
        BaselineProvenanceError,
        match="measurement evidence is invalid",
    ):
        verify_baseline_preflight(run_directory, approved_scenarios={scenario_id})


def test_preflight_rejects_missing_orphan_and_unsafe_raw_explain_evidence(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    identity = {
        "source_sha": "a" * 40,
        "git_tree": "b" * 40,
        "fixture_id": "stage0-worker-synthetic-v1",
        "runner_digest": "c" * 64,
        "host_environment_digest": "d" * 64,
    }
    run_directory = _prepared_run(tmp_path, source_sha=identity["source_sha"])
    monkeypatch.setattr(baseline, "_release_identity", lambda: identity)
    scenario_id = "queue-publication-outbox-query"
    scenario_path = run_directory / f"backend-8.0-{scenario_id}.json"
    scenario = _complete_scenario_payload(
        identity,
        mysql_version="8.0",
        scenario_id=scenario_id,
    )
    scenario["explain"] = _queue_explain_reference(
        mysql_version="8.0",
        scenario_id=scenario_id,
    )
    scenario_path.write_text(json.dumps(scenario), encoding="utf-8")

    with pytest.raises(
        BaselineProvenanceError, match="queue EXPLAIN evidence is missing"
    ):
        verify_baseline_preflight(
            run_directory,
            approved_scenarios={scenario_id},
        )

    explain_path = run_directory / f"external-explain-8.0-{scenario_id}.json"
    explain_path.write_text(
        json.dumps(
            _raw_explain_payload(
                identity,
                mysql_version="8.0",
                scenario_id=scenario_id,
                raw_plan='{"query_block":{"table":{"table_name":"publication_outbox"}}}',
            )
        ),
        encoding="utf-8",
    )

    scenario_path.unlink()
    with pytest.raises(
        BaselineProvenanceError, match="raw EXPLAIN evidence is orphaned"
    ):
        verify_baseline_preflight(
            run_directory,
            approved_scenarios={scenario_id},
        )

    scenario_path.write_text(json.dumps(scenario), encoding="utf-8")
    unsafe_plan = {
        "query_block": {
            "nested_loop": [
                {"table": {"table_name": "left"}},
                {"table": {"table_name": "right"}},
            ]
        }
    }
    explain_path.write_text(
        json.dumps(
            _raw_explain_payload(
                identity,
                mysql_version="8.0",
                scenario_id=scenario_id,
                raw_plan=json.dumps(unsafe_plan),
            )
        ),
        encoding="utf-8",
    )

    with pytest.raises(BaselineProvenanceError, match="raw EXPLAIN plan is invalid"):
        verify_baseline_preflight(
            run_directory,
            approved_scenarios={scenario_id},
        )


def test_preflight_rejects_unrelated_or_mismatched_external_evidence(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    identity = {
        "source_sha": "a" * 40,
        "git_tree": "b" * 40,
        "fixture_id": "stage0-worker-synthetic-v1",
        "runner_digest": "c" * 64,
        "host_environment_digest": "d" * 64,
    }
    run_directory = _prepared_run(tmp_path, source_sha=identity["source_sha"])
    monkeypatch.setattr(baseline, "_release_identity", lambda: identity)

    (run_directory / "unexpected.json").write_text("{}", encoding="utf-8")
    with pytest.raises(BaselineProvenanceError, match="unrelated evidence"):
        verify_baseline_preflight(
            run_directory,
            approved_scenarios={"heartbeat-maintenance-barrier"},
        )

    (run_directory / "unexpected.json").unlink()
    (run_directory / "backend-8.0-heartbeat-maintenance-barrier.json").write_text(
        json.dumps(
            {
                **identity,
                "host_environment_digest": "e" * 64,
                "mysql_version": "8.0",
            }
        ),
        encoding="utf-8",
    )
    with pytest.raises(BaselineProvenanceError, match="provenance is invalid"):
        verify_baseline_preflight(
            run_directory,
            approved_scenarios={"heartbeat-maintenance-barrier"},
        )


def test_raw_explain_evidence_is_external_and_exclusive(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("APP_BASELINE_MYSQL_VERSION", "8.0")
    path = write_explain_evidence(
        tmp_path,
        scenario_id="queue-publication-outbox-query",
        raw_plan='{"query_block":{"table":{"table_name":"publication_outbox"}}}',
    )

    payload = json.loads(path.read_text(encoding="utf-8"))
    assert path.name == "external-explain-8.0-queue-publication-outbox-query.json"
    assert payload["raw_plan"].startswith('{"query_block"')
    with pytest.raises(FileExistsError):
        write_explain_evidence(
            tmp_path,
            scenario_id="queue-publication-outbox-query",
            raw_plan="{}",
        )


def test_heartbeat_probe_uses_real_repository_and_distinct_instances() -> None:
    engine = cast(Engine, object())
    probe = HeartbeatProbe(engine)

    assert isinstance(probe._repository, WorkerHeartbeatRepository)
    assert isinstance(probe._controller, WorkerHeartbeatController)
    assert probe._manual_instance_id != probe._controller_instance_id


def test_owned_uvicorn_terminates_its_windows_process_tree(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class ProcessDouble:
        pid = 42424

        def __init__(self) -> None:
            self.wait_timeout: int | None = None

        def poll(self) -> None:
            return None

        def wait(self, timeout: int) -> None:
            self.wait_timeout = timeout

    process = ProcessDouble()
    owned = OwnedUvicorn(
        runtime_database_url="mysql+pymysql://runtime:test@127.0.0.1/db?charset=utf8mb4"
    )
    owned._process = cast(subprocess.Popen[bytes], process)
    commands: list[list[str]] = []

    def fake_run(
        arguments: list[str], **_kwargs: object
    ) -> subprocess.CompletedProcess[bytes]:
        commands.append(arguments)
        return subprocess.CompletedProcess(arguments, 0)

    monkeypatch.setattr(os, "name", "nt")
    monkeypatch.setattr(subprocess, "run", fake_run)

    owned._terminate_owned_pid()

    assert commands == [["taskkill", "/PID", "42424", "/T", "/F"]]
    assert process.wait_timeout == 10
    assert owned.pid is None and owned._process is None


def test_barrier_measurement_starts_after_barrier_context_releases(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    released = threading.Event()
    probe = HeartbeatProbe(cast(Engine, object()))

    @contextmanager
    def synthetic_barrier(_engine: Engine, *, timeout_seconds: int) -> Iterator[None]:
        assert timeout_seconds == 0
        try:
            yield None
        finally:
            released.set()

    def update_after_release() -> float:
        assert released.wait(timeout=1)
        return 0.1

    monkeypatch.setattr(
        "tests.performance.test_project_optimization_baseline.hold_maintenance_write_barrier",
        synthetic_barrier,
    )
    monkeypatch.setattr(probe, "update_ms", update_after_release)

    latency = probe.barrier_release_to_update_ms()
    measurement = probe.consume_barrier_measurement()

    assert latency == measurement["first_post_release_update_ms"]
    assert (
        measurement["blocked_duration_ms"]
        >= measurement["first_post_release_update_ms"]
    )
    with pytest.raises(RuntimeError, match="unavailable"):
        probe.consume_barrier_measurement()
