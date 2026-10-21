from __future__ import annotations

import hashlib
import json
import math
import os
import platform
import re
import subprocess
import sys
import time
import urllib.request
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path

import sqlalchemy as sa

_REPOSITORY_ROOT = Path(__file__).resolve().parents[3]
_SCENARIO_EVIDENCE_NAME = re.compile(
    r"backend-(?P<mysql_version>8\.[04])-(?P<scenario_id>[a-z0-9-]+)\.json\Z"
)
_EXPLAIN_EVIDENCE_NAME = re.compile(
    r"external-explain-(?P<mysql_version>8\.[04])-"
    r"(?P<scenario_id>[a-z0-9-]+)\.json\Z"
)
_QUEUE_SCENARIO_IDS = frozenset(
    {
        "queue-publication-outbox-query",
        "queue-return-dedup-query",
        "queue-catalog-import-query",
        "queue-catalog-export-query",
    }
)


class BaselineProvenanceError(RuntimeError):
    """The release checkout or external evidence directory is not trustworthy."""


@dataclass(frozen=True, slots=True)
class SamplingProtocol:
    warmups: int = 3
    measured_samples: int = 20
    rounds: int = 3


@dataclass(frozen=True, slots=True)
class ScenarioResult:
    scenario_id: str
    unit: str
    rounds: tuple[dict[str, object], ...]
    explain: Mapping[str, object] | None = None
    measurement_evidence: Mapping[str, object] | None = None


def measure_scenario(
    scenario_id: str,
    operation: Callable[[], float],
    *,
    unit: str,
    protocol: SamplingProtocol = SamplingProtocol(),  # noqa: B008
    measurement: Callable[[], Mapping[str, object]] | None = None,
) -> ScenarioResult:
    rounds: list[dict[str, object]] = []
    measured_evidence: list[list[dict[str, object]]] = []
    for _ in range(protocol.rounds):
        for _ in range(protocol.warmups):
            operation()
            if measurement is not None:
                measurement()
        samples: list[float] = []
        round_evidence: list[dict[str, object]] = []
        for _ in range(protocol.measured_samples):
            samples.append(operation())
            if measurement is not None:
                round_evidence.append(dict(measurement()))
        ordered = sorted(samples)
        rounds.append(
            {
                "sample_count": len(samples),
                "samples": samples,
                "p50": (ordered[9] + ordered[10]) / 2,
                "p95": ordered[18],
                "max": ordered[-1],
            }
        )
        if measurement is not None:
            measured_evidence.append(round_evidence)
    return ScenarioResult(
        scenario_id=scenario_id,
        unit=unit,
        rounds=tuple(rounds),
        measurement_evidence=(
            {"measured_rounds": measured_evidence} if measurement is not None else None
        ),
    )


def measure_http(
    url: str,
    *,
    headers: Mapping[str, str] | None = None,
    timeout_seconds: float = 10.0,
) -> float:
    started = time.perf_counter_ns()
    request = urllib.request.Request(url, headers=dict(headers or {}))
    with urllib.request.urlopen(request, timeout=timeout_seconds) as response:
        if response.status != 200:
            raise RuntimeError(f"HTTP baseline received {response.status}")
        response.read()
    return (time.perf_counter_ns() - started) / 1_000_000


def measure_sql(
    connection: sa.Connection,
    statement: sa.TextClause,
    parameters: Mapping[str, object] | None = None,
) -> float:
    started = time.perf_counter_ns()
    connection.execute(statement, dict(parameters or {})).all()
    return (time.perf_counter_ns() - started) / 1_000_000


def write_scenario_result(run_directory: Path, result: ScenarioResult) -> Path:
    mysql_version = os.environ.get("APP_BASELINE_MYSQL_VERSION", "unit")
    path = run_directory / f"backend-{mysql_version}-{result.scenario_id}.json"
    payload: dict[str, object] = {
        "schema_version": 1,
        "scenario_id": result.scenario_id,
        "unit": result.unit,
        "warmup_samples": 3,
        "measured_samples": 20,
        "round_count": 3,
        "rounds": list(result.rounds),
    }
    payload.update(_evidence_identity())
    if result.explain is not None:
        payload["explain"] = dict(result.explain)
    if result.measurement_evidence is not None:
        payload["measurement_evidence"] = dict(result.measurement_evidence)
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(descriptor, "w", encoding="utf-8", newline="\n") as stream:
        json.dump(payload, stream, ensure_ascii=False, indent=2, sort_keys=True)
        stream.write("\n")
    return path


def write_quick_diagnostic_result(
    run_directory: Path,
    observations: Sequence[Mapping[str, object]],
) -> Path:
    """Write isolated short-check evidence that formal gates must not consume."""

    mysql_version = os.environ.get("APP_BASELINE_MYSQL_VERSION", "")
    if mysql_version not in {"8.0", "8.4"}:
        raise BaselineProvenanceError("quick diagnostic MySQL version is invalid")
    if len(observations) != 3:
        raise BaselineProvenanceError(
            "quick diagnostic requires exactly three long-task observations"
        )
    path = run_directory / f"quick-diagnostic-{mysql_version}-heartbeat-long-task.json"
    payload: dict[str, object] = {
        "schema_version": 1,
        "mode": "diagnostic-quick",
        "formal_evidence": False,
        "scenario_id": "heartbeat-long-task",
        "mysql_version": mysql_version,
        "check_count": len(observations),
        "observations": [dict(observation) for observation in observations],
    }
    payload.update(_evidence_identity())
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(descriptor, "w", encoding="utf-8", newline="\n") as stream:
        json.dump(payload, stream, ensure_ascii=False, indent=2, sort_keys=True)
        stream.write("\n")
    return path


def write_explain_evidence(
    run_directory: Path,
    *,
    scenario_id: str,
    raw_plan: str,
) -> Path:
    """Write raw MySQL plans outside the scenario payload consumed by the gate."""

    mysql_version = os.environ["APP_BASELINE_MYSQL_VERSION"]
    path = run_directory / f"external-explain-{mysql_version}-{scenario_id}.json"
    payload = {
        "schema_version": 1,
        "scenario_id": scenario_id,
        "format": "JSON",
        "raw_plan": raw_plan,
    }
    payload.update(_evidence_identity())
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(descriptor, "w", encoding="utf-8", newline="\n") as stream:
        json.dump(payload, stream, ensure_ascii=False, indent=2, sort_keys=True)
        stream.write("\n")
    return path


def verify_baseline_preflight(
    run_directory: Path,
    *,
    approved_scenarios: set[str],
) -> dict[str, str]:
    """Reject evidence that is not produced from a clean, current checkout."""

    identity = _release_identity()
    run = run_directory.resolve(strict=True)
    if run == _REPOSITORY_ROOT or _REPOSITORY_ROOT in run.parents:
        raise BaselineProvenanceError("baseline evidence directory must be external")
    run_identity_path = run / "run-identity.json"
    if run_identity_path.is_symlink():
        raise BaselineProvenanceError("run identity must not be a symbolic link")
    try:
        run_identity = json.loads(run_identity_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as error:
        raise BaselineProvenanceError("prepared run identity is required") from error
    if (
        not isinstance(run_identity, dict)
        or set(run_identity) != {"run_id", "source_sha", "status"}
        or run_identity.get("run_id") != run.name
        or re.fullmatch(r"stage0-[0-9a-f]{12}", run.name) is None
        or run_identity.get("source_sha") != identity["source_sha"]
        or run_identity.get("status") != "prepared"
    ):
        raise BaselineProvenanceError("prepared run identity is invalid")
    if (run / "diagnostic-identity.json").exists() or any(
        run.glob("quick-diagnostic-*.json")
    ):
        raise BaselineProvenanceError(
            "quick diagnostic evidence is not valid formal evidence"
        )
    scenarios: dict[tuple[str, str], Mapping[str, object]] = {}
    raw_explains: dict[tuple[str, str], Mapping[str, object]] = {}
    for path in run.iterdir():
        if path.name == "run-identity.json":
            continue
        if path.is_symlink() or not path.is_file():
            raise BaselineProvenanceError("run directory contains unrelated evidence")
        scenario_match = _SCENARIO_EVIDENCE_NAME.fullmatch(path.name)
        explain_match = _EXPLAIN_EVIDENCE_NAME.fullmatch(path.name)
        match = scenario_match or explain_match
        if match is None or match["scenario_id"] not in approved_scenarios:
            raise BaselineProvenanceError("run directory contains unrelated evidence")
        payload = _validate_existing_evidence(
            path,
            identity=identity,
            mysql_version=match["mysql_version"],
            scenario_id=match["scenario_id"],
            is_explain=explain_match is not None,
        )
        evidence_key = (match["mysql_version"], match["scenario_id"])
        if explain_match is not None:
            raw_explains[evidence_key] = payload
        else:
            scenarios[evidence_key] = payload
    _validate_explain_pairings(scenarios, raw_explains)
    return identity


def _validate_existing_evidence(
    path: Path,
    *,
    identity: Mapping[str, str],
    mysql_version: str,
    scenario_id: str,
    is_explain: bool,
) -> Mapping[str, object]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as error:
        raise BaselineProvenanceError("existing evidence is unreadable") from error
    if not isinstance(payload, dict) or any(
        payload.get(name) != value for name, value in identity.items()
    ):
        raise BaselineProvenanceError("existing evidence provenance is invalid")
    if payload.get("mysql_version") != mysql_version:
        raise BaselineProvenanceError("existing evidence MySQL identity is invalid")
    if payload.get("schema_version") != 1 or payload.get("scenario_id") != scenario_id:
        raise BaselineProvenanceError("existing evidence filename identity is invalid")
    if is_explain:
        _validate_existing_explain(payload)
    else:
        _validate_existing_scenario(
            payload,
            mysql_version=mysql_version,
            scenario_id=scenario_id,
        )
    return payload


def _validate_explain_pairings(
    scenarios: Mapping[tuple[str, str], Mapping[str, object]],
    raw_explains: Mapping[tuple[str, str], Mapping[str, object]],
) -> None:
    for mysql_version, scenario_id in raw_explains:
        if (
            scenario_id not in _QUEUE_SCENARIO_IDS
            or (
                mysql_version,
                scenario_id,
            )
            not in scenarios
        ):
            raise BaselineProvenanceError("existing raw EXPLAIN evidence is orphaned")
    for evidence_key, scenario in scenarios.items():
        mysql_version, scenario_id = evidence_key
        if scenario_id not in _QUEUE_SCENARIO_IDS:
            continue
        if evidence_key not in raw_explains:
            raise BaselineProvenanceError("existing queue EXPLAIN evidence is missing")
        if not _valid_explain_reference(
            scenario["explain"],
            mysql_version=mysql_version,
            scenario_id=scenario_id,
        ):
            raise BaselineProvenanceError(
                "existing scenario explain reference is invalid"
            )


def _validate_existing_scenario(
    payload: Mapping[str, object],
    *,
    mysql_version: str,
    scenario_id: str,
) -> None:
    required = {
        "schema_version",
        "source_sha",
        "git_tree",
        "fixture_id",
        "runner_digest",
        "host_environment_digest",
        "mysql_version",
        "scenario_id",
        "unit",
        "warmup_samples",
        "measured_samples",
        "round_count",
        "rounds",
    }
    is_queue_scenario = scenario_id in _QUEUE_SCENARIO_IDS
    if is_queue_scenario:
        required.add("explain")
    allowed = required | {"measurement_evidence"}
    if set(payload) - allowed or not required <= set(payload):
        raise BaselineProvenanceError("existing scenario evidence shape is invalid")
    if (
        payload["mysql_version"] != mysql_version
        or payload["scenario_id"] != scenario_id
        or payload["unit"] != "ms"
        or payload["warmup_samples"] != 3
        or payload["measured_samples"] != 20
        or payload["round_count"] != 3
    ):
        raise BaselineProvenanceError("existing scenario evidence protocol is invalid")
    rounds = payload["rounds"]
    if not isinstance(rounds, list) or len(rounds) != 3:
        raise BaselineProvenanceError("existing scenario evidence rounds are invalid")
    for round_ in rounds:
        if not isinstance(round_, dict) or set(round_) != {
            "sample_count",
            "samples",
            "p50",
            "p95",
            "max",
        }:
            raise BaselineProvenanceError(
                "existing scenario evidence rounds are invalid"
            )
        samples = round_["samples"]
        summaries = (round_["p50"], round_["p95"], round_["max"])
        if (
            round_["sample_count"] != 20
            or not isinstance(samples, list)
            or len(samples) != 20
            or any(not _finite_nonnegative_number(value) for value in samples)
            or any(not _finite_number(value) for value in summaries)
        ):
            raise BaselineProvenanceError(
                "existing scenario evidence rounds are invalid"
            )
        ordered = sorted(samples)
        if summaries != ((ordered[9] + ordered[10]) / 2, ordered[18], ordered[-1]):
            raise BaselineProvenanceError(
                "existing scenario evidence summaries are invalid"
            )
    if is_queue_scenario and not _valid_explain_reference(
        payload["explain"],
        mysql_version=mysql_version,
        scenario_id=scenario_id,
    ):
        raise BaselineProvenanceError("existing scenario explain reference is invalid")
    measurement = payload.get("measurement_evidence")
    if measurement is not None and not _valid_measurement_evidence(measurement):
        raise BaselineProvenanceError(
            "existing scenario measurement evidence is invalid"
        )


def _finite_number(value: object) -> bool:
    return (
        isinstance(value, (int, float))
        and not isinstance(value, bool)
        and math.isfinite(value)
    )


def _finite_nonnegative_number(value: object) -> bool:
    return (
        isinstance(value, (int, float))
        and not isinstance(value, bool)
        and math.isfinite(value)
        and value >= 0
    )


def _valid_explain_reference(
    value: object,
    *,
    mysql_version: str,
    scenario_id: str,
) -> bool:
    return (
        isinstance(value, dict)
        and set(value) == {"format", "unbounded_cartesian_join", "external_evidence"}
        and value["format"] == "JSON"
        and value["unbounded_cartesian_join"] is False
        and value["external_evidence"]
        == f"external-explain-{mysql_version}-{scenario_id}.json"
    )


def _valid_measurement_evidence(value: object) -> bool:
    if not isinstance(value, dict) or set(value) != {"measured_rounds"}:
        return False
    rounds = value["measured_rounds"]
    return (
        isinstance(rounds, list)
        and len(rounds) == 3
        and all(
            isinstance(round_, list)
            and len(round_) == 20
            and all(
                isinstance(row, dict)
                and set(row) == {"blocked_duration_ms", "first_post_release_update_ms"}
                and all(
                    _finite_nonnegative_number(measurement)
                    for measurement in row.values()
                )
                for row in round_
            )
            for round_ in rounds
        )
    )


def _validate_existing_explain(payload: Mapping[str, object]) -> None:
    required = {
        "schema_version",
        "source_sha",
        "git_tree",
        "fixture_id",
        "runner_digest",
        "host_environment_digest",
        "mysql_version",
        "scenario_id",
        "format",
        "raw_plan",
    }
    if (
        set(payload) != required
        or payload["format"] != "JSON"
        or not isinstance(payload["raw_plan"], str)
    ):
        raise BaselineProvenanceError("existing raw EXPLAIN evidence shape is invalid")
    try:
        plan = json.loads(payload["raw_plan"])
    except json.JSONDecodeError as error:
        raise BaselineProvenanceError("existing raw EXPLAIN plan is invalid") from error
    if (
        not isinstance(plan, dict)
        or not isinstance(plan.get("query_block"), dict)
        or _unbounded_cartesian_join(plan)
    ):
        raise BaselineProvenanceError("existing raw EXPLAIN plan is invalid")


def _unbounded_cartesian_join(plan: object) -> bool:
    """Mirror the deterministic gate used when a queue plan is first recorded."""

    if isinstance(plan, dict):
        nested_loop = plan.get("nested_loop")
        if isinstance(nested_loop, list) and len(nested_loop) > 1:
            table_rows: list[dict[str, object]] = []
            for row in nested_loop:
                if not isinstance(row, dict):
                    continue
                table = row.get("table")
                if isinstance(table, dict):
                    table_rows.append(table)
            if len(table_rows) > 1 and all(
                "key" not in table and "ref" not in table for table in table_rows
            ):
                return True
        return any(_unbounded_cartesian_join(value) for value in plan.values())
    if isinstance(plan, list):
        return any(_unbounded_cartesian_join(value) for value in plan)
    return False


def _release_identity() -> dict[str, str]:
    """Bind release evidence to the same immutable identity Task 3 validates."""

    source_sha = os.getenv("APP_RELEASE_SOURCE_SHA", "")
    if not source_sha:
        return {}
    if re.fullmatch(r"[0-9a-f]{40}", source_sha) is None:
        raise BaselineProvenanceError(
            "APP_RELEASE_SOURCE_SHA must be a full lowercase Git SHA"
        )

    def checked_output(arguments: list[str]) -> str:
        try:
            return subprocess.run(
                arguments,
                cwd=_REPOSITORY_ROOT,
                check=True,
                capture_output=True,
                text=True,
                encoding="utf-8",
            ).stdout.strip()
        except subprocess.SubprocessError as error:
            raise BaselineProvenanceError(
                "release Git provenance could not be read"
            ) from error

    if checked_output(["git", "rev-parse", "HEAD"]) != source_sha:
        raise BaselineProvenanceError(
            "APP_RELEASE_SOURCE_SHA does not match checkout HEAD"
        )
    status = checked_output(
        ["git", "status", "--porcelain=v1", "--untracked-files=all"]
    )
    disallowed_status = [
        line
        for line in status.splitlines()
        if not re.fullmatch(r"\?\? data/[^\r\n]+", line)
    ]
    if disallowed_status:
        raise BaselineProvenanceError("release checkout must be clean")
    git_tree = checked_output(["git", "rev-parse", f"{source_sha}^{{tree}}"])
    manifest = json.loads(
        (_REPOSITORY_ROOT / "scripts" / "ci-suite-manifest.json").read_text(
            encoding="utf-8"
        )
    )
    runner_paths = manifest["release_suites"]["project-optimization-baseline"][
        "runner_paths"
    ]
    runner_lines = [
        f"{path}\0{checked_output(['git', 'rev-parse', f'{source_sha}:{path}'])}"
        for path in runner_paths
    ]
    runner_payload = ("\n".join(sorted(runner_lines)) + "\n").encode("utf-8")
    return {
        "source_sha": source_sha,
        "git_tree": git_tree,
        "fixture_id": "stage0-worker-synthetic-v1",
        "runner_digest": hashlib.sha256(runner_payload).hexdigest(),
        "host_environment_digest": _host_environment_digest(checked_output),
    }


def _evidence_identity() -> dict[str, str]:
    identity = _release_identity()
    if not identity:
        return identity
    mysql_version = os.getenv("APP_BASELINE_MYSQL_VERSION", "")
    if mysql_version not in {"8.0", "8.4"}:
        raise BaselineProvenanceError("baseline MySQL version is invalid")
    return {**identity, "mysql_version": mysql_version}


def _host_environment_digest(checked_output: Callable[[list[str]], str]) -> str:
    host = {
        "python": sys.version.split()[0],
        "node": checked_output(["node", "--version"]),
        "pnpm": checked_output([_pnpm_command(), "--version"]),
        "playwright_chromium": "1.62.1",
        "os": platform.platform(),
        "machine": platform.machine(),
        "processor": platform.processor(),
        "cpu_count": os.cpu_count(),
        "memory_bytes": _physical_memory_bytes(),
        "fixture_ids": [
            "synthetic-reports-v1",
            "analytics_scale_v1",
            "stage0-worker-synthetic-v1",
        ],
    }
    canonical = json.dumps(
        host,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _pnpm_command() -> str:
    """Use the Windows command shim when probing the Node package manager."""

    return "pnpm.cmd" if sys.platform == "win32" else "pnpm"


def _physical_memory_bytes() -> int:
    if sys.platform == "win32":
        import ctypes

        class MemoryStatus(ctypes.Structure):
            _fields_ = [
                ("length", ctypes.c_ulong),
                ("memory_load", ctypes.c_ulong),
                ("total_physical", ctypes.c_ulonglong),
                ("available_physical", ctypes.c_ulonglong),
                ("total_page_file", ctypes.c_ulonglong),
                ("available_page_file", ctypes.c_ulonglong),
                ("total_virtual", ctypes.c_ulonglong),
                ("available_virtual", ctypes.c_ulonglong),
                ("available_extended_virtual", ctypes.c_ulonglong),
            ]

        status = MemoryStatus()
        status.length = ctypes.sizeof(MemoryStatus)
        if not ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(status)):
            raise BaselineProvenanceError("physical memory fingerprint is unavailable")
        return int(status.total_physical)
    else:
        sysconf = getattr(os, "sysconf", None)
        if sysconf is None:
            raise BaselineProvenanceError("physical memory fingerprint is unavailable")
        page_size = int(sysconf("SC_PAGE_SIZE"))
        page_count = int(sysconf("SC_PHYS_PAGES"))
        return page_size * page_count
