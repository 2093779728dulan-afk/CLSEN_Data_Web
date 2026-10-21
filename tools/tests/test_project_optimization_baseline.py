from __future__ import annotations

import hashlib
import json
import subprocess
import sys
from pathlib import Path
from typing import cast

import pytest
from tests.performance import (  # type: ignore[import-not-found]
    project_optimization_baseline as producer,
)

from tools import project_optimization_baseline as baseline
from tools.project_optimization_baseline import (
    BaselineContractError,
    build_freeze_record,
    build_run_summary,
    load_manifest,
    main,
    publish_command_results,
    resolve_empty_external_root,
    summarize_round,
    summarize_scenario,
    validate_run,
    write_json_exclusive,
)

ROOT = Path(__file__).resolve().parents[2]
MANIFEST = ROOT / "scripts" / "project-optimization-baseline-manifest.json"


def _outcome_digest(nodeids: list[str]) -> str:
    return hashlib.sha256(("\n".join(sorted(nodeids)) + "\n").encode()).hexdigest()


def _write_outcome_report(
    directory: Path,
    *,
    source_sha: str,
    command_id: str,
    profile: str,
    platform_id: str,
    shard_id: str,
    outcomes: list[dict[str, str]],
    binding: str | None = None,
) -> str:
    nodeids = [row["nodeid"] for row in outcomes]
    profile_digest = _outcome_digest(nodeids)
    expected_binding = baseline.pytest_outcome_binding(
        source_sha=source_sha,
        command_id=command_id,
        profile=profile,
        profile_node_digest=profile_digest,
        shard_node_digests={shard_id: profile_digest},
        platform_id=platform_id,
    )
    _write_json(
        directory / f"{shard_id}.json",
        {
            "schema_version": 2,
            "binding_sha256": binding or expected_binding,
            "shard_id": shard_id,
            "expected_node_digest": profile_digest,
            "session_exit_code": 0,
            "private_environment_clear": True,
            "collected_nodeids": nodeids,
            "outcomes": outcomes,
        },
    )
    return profile_digest


def test_pytest_outcomes_accept_only_reviewed_windows_skip(tmp_path: Path) -> None:
    manifest = load_manifest(MANIFEST, repository_root=ROOT)
    report_directory = tmp_path / "reports"
    report_directory.mkdir()
    source_sha = "a" * 40
    outcomes = [
        {
            "nodeid": (
                "backend/tests/integration/test_product_catalog_canary.py::"
                "test_current_database_read_only_snapshot_matches_approved_counts"
            ),
            "status": "skipped",
            "reason": "SELECT-only current database URL is required",
        }
    ]
    profile_digest = _write_outcome_report(
        report_directory,
        source_sha=source_sha,
        command_id="ubuntu-full",
        profile="ubuntu-full",
        platform_id="win32",
        shard_id="pytest",
        outcomes=outcomes,
    )

    evidence = baseline.validate_pytest_outcome_reports(
        report_directory,
        manifest=manifest,
        source_sha=source_sha,
        command_id="ubuntu-full",
        profile="ubuntu-full",
        profile_node_digest=profile_digest,
        shard_node_digests={"pytest": profile_digest},
        platform_id="win32",
    )

    assert evidence["skip_count"] == 1
    assert evidence["explained_skip_count"] == 1
    assert evidence["unexplained_skip_count"] == 0
    assert evidence["skips"] == outcomes
    assert evidence["report_digests"] == {
        "pytest.json": hashlib.sha256(
            (report_directory / "pytest.json").read_bytes()
        ).hexdigest()
    }


@pytest.mark.parametrize(
    ("mutation", "message"),
    [
        ("unknown-node", "skip allowlist"),
        ("unknown-reason", "skip allowlist"),
        ("duplicate", "duplicate"),
        ("xfail", "adverse pytest outcome"),
        ("binding", "binding"),
        ("missing", "report identity"),
        ("malformed", "could not be read"),
    ],
)
def test_pytest_outcomes_fail_closed(
    tmp_path: Path, mutation: str, message: str
) -> None:
    manifest = load_manifest(MANIFEST, repository_root=ROOT)
    report_directory = tmp_path / "reports"
    report_directory.mkdir()
    source_sha = "b" * 40
    allowed_node = (
        "backend/tests/integration/test_product_catalog_canary.py::"
        "test_current_database_read_only_snapshot_matches_approved_counts"
    )
    outcomes = [
        {
            "nodeid": allowed_node,
            "status": "skipped",
            "reason": "SELECT-only current database URL is required",
        }
    ]
    if mutation == "unknown-node":
        outcomes[0]["nodeid"] = "backend/tests/test_unknown.py::test_unknown"
    elif mutation == "unknown-reason":
        outcomes[0]["reason"] = "unreviewed reason"
    elif mutation == "duplicate":
        outcomes.append(dict(outcomes[0]))
    elif mutation == "xfail":
        outcomes[0] = {"nodeid": allowed_node, "status": "xfail", "reason": "known"}
    binding = "0" * 64 if mutation == "binding" else None
    profile_digest = _write_outcome_report(
        report_directory,
        source_sha=source_sha,
        command_id="ubuntu-full",
        profile="ubuntu-full",
        platform_id="win32",
        shard_id="pytest",
        outcomes=outcomes,
        binding=binding,
    )
    if mutation == "missing":
        (report_directory / "pytest.json").unlink()
    elif mutation == "malformed":
        (report_directory / "pytest.json").write_text("{", encoding="utf-8")

    with pytest.raises(BaselineContractError, match=message):
        baseline.validate_pytest_outcome_reports(
            report_directory,
            manifest=manifest,
            source_sha=source_sha,
            command_id="ubuntu-full",
            profile="ubuntu-full",
            profile_node_digest=profile_digest,
            shard_node_digests={"pytest": profile_digest},
            platform_id="win32",
        )


def test_stage0_backend_outcomes_require_an_exact_profile_identity(
    tmp_path: Path,
) -> None:
    del tmp_path
    source_sha = "c" * 40

    with pytest.raises(BaselineContractError, match="profile node digest is required"):
        baseline.pytest_outcome_binding(
            source_sha=source_sha,
            command_id="stage0-backend-8-0",
            profile="project-optimization-baseline",
            profile_node_digest=None,
            shard_node_digests={"scoped": "e" * 64},
            platform_id="win32",
        )


def test_mysql_outcomes_reject_cross_shard_identity_substitution(
    tmp_path: Path,
) -> None:
    manifest = load_manifest(MANIFEST, repository_root=ROOT)
    report_directory = tmp_path / "reports"
    report_directory.mkdir()
    source_sha = "d" * 40
    migration_node = (
        "backend/tests/integration/test_migrations.py::test_migration_identity"
    )
    scoped_node = "backend/tests/integration/test_models.py::test_scoped_identity"
    shard_node_digests = {
        "migration": _outcome_digest([migration_node]),
        "scoped": _outcome_digest([scoped_node]),
    }
    profile_digest = _outcome_digest([migration_node, scoped_node])
    binding = baseline.pytest_outcome_binding(
        source_sha=source_sha,
        command_id="mysql-compatibility-8-0",
        profile="mysql-compatibility",
        profile_node_digest=profile_digest,
        shard_node_digests=shard_node_digests,
        platform_id="win32",
    )
    for shard_id, substituted_node in (
        ("migration", scoped_node),
        ("scoped", migration_node),
    ):
        _write_json(
            report_directory / f"{shard_id}.json",
            {
                "schema_version": 2,
                "binding_sha256": binding,
                "shard_id": shard_id,
                "expected_node_digest": shard_node_digests[shard_id],
                "session_exit_code": 0,
                "private_environment_clear": True,
                "collected_nodeids": [substituted_node],
                "outcomes": [
                    {
                        "nodeid": substituted_node,
                        "status": "passed",
                        "reason": "",
                    }
                ],
            },
        )

    with pytest.raises(BaselineContractError, match="shard identity"):
        baseline.validate_pytest_outcome_reports(
            report_directory,
            manifest=manifest,
            source_sha=source_sha,
            command_id="mysql-compatibility-8-0",
            profile="mysql-compatibility",
            profile_node_digest=profile_digest,
            shard_node_digests=shard_node_digests,
            platform_id="win32",
        )


_MYSQL_CANARY_NODE = (
    "backend/tests/integration/test_product_catalog_permissions.py::"
    "test_canary_identity_is_select_only_when_configured"
)
_MYSQL_CANARY_REASON = (
    "current database canary is verified only by its canonical runner"
)


def _write_mysql_outcome_reports(
    directory: Path,
    *,
    source_sha: str,
    command_id: str,
    platform_id: str,
    scoped_outcomes: list[dict[str, str]] | None = None,
) -> tuple[str, dict[str, str]]:
    migration_outcomes = [
        {
            "nodeid": (
                "backend/tests/integration/test_migrations.py::test_migration_identity"
            ),
            "status": "passed",
            "reason": "",
        }
    ]
    if scoped_outcomes is None:
        scoped_outcomes = [
            {
                "nodeid": _MYSQL_CANARY_NODE,
                "status": "skipped",
                "reason": _MYSQL_CANARY_REASON,
            }
        ]
    outcomes_by_shard = {
        "migration": migration_outcomes,
        "scoped": scoped_outcomes,
    }
    shard_node_digests = {
        shard: _outcome_digest([row["nodeid"] for row in outcomes])
        for shard, outcomes in outcomes_by_shard.items()
    }
    profile_digest = _outcome_digest(
        [row["nodeid"] for outcomes in outcomes_by_shard.values() for row in outcomes]
    )
    binding = baseline.pytest_outcome_binding(
        source_sha=source_sha,
        command_id=command_id,
        profile="mysql-compatibility",
        profile_node_digest=profile_digest,
        shard_node_digests=shard_node_digests,
        platform_id=platform_id,
    )
    for shard, outcomes in outcomes_by_shard.items():
        _write_json(
            directory / f"{shard}.json",
            {
                "schema_version": 2,
                "binding_sha256": binding,
                "shard_id": shard,
                "expected_node_digest": shard_node_digests[shard],
                "session_exit_code": 0,
                "private_environment_clear": True,
                "collected_nodeids": sorted(row["nodeid"] for row in outcomes),
                "outcomes": outcomes,
            },
        )
    return profile_digest, shard_node_digests


@pytest.mark.parametrize(
    ("command_id", "platform_id"),
    [
        (command_id, platform_id)
        for command_id in (
            "mysql-compatibility-8-0",
            "mysql-compatibility-8-4",
        )
        for platform_id in ("win32", "linux", "darwin")
    ],
)
def test_mysql_outcomes_accept_only_the_canonical_runner_skip(
    tmp_path: Path, command_id: str, platform_id: str
) -> None:
    manifest = load_manifest(MANIFEST, repository_root=ROOT)
    report_directory = tmp_path / "reports"
    report_directory.mkdir()
    source_sha = "e" * 40
    profile_digest, shard_node_digests = _write_mysql_outcome_reports(
        report_directory,
        source_sha=source_sha,
        command_id=command_id,
        platform_id=platform_id,
    )

    evidence = baseline.validate_pytest_outcome_reports(
        report_directory,
        manifest=manifest,
        source_sha=source_sha,
        command_id=command_id,
        profile="mysql-compatibility",
        profile_node_digest=profile_digest,
        shard_node_digests=shard_node_digests,
        platform_id=platform_id,
    )

    assert evidence["skip_count"] == 1
    assert evidence["explained_skip_count"] == 1
    assert evidence["unexplained_skip_count"] == 0
    assert evidence["skips"] == [
        {
            "nodeid": _MYSQL_CANARY_NODE,
            "status": "skipped",
            "reason": _MYSQL_CANARY_REASON,
        }
    ]


@pytest.mark.parametrize(
    "command_id", ("mysql-compatibility-8-0", "mysql-compatibility-8-4")
)
@pytest.mark.parametrize(
    ("mutation", "message"),
    [
        ("node-drift", "pytest skip allowlist rejected"),
        ("reason-drift", "pytest skip allowlist rejected"),
        ("extra-skip", "pytest skip allowlist rejected"),
        ("missing-skip", "pytest required skip is missing"),
        ("wrong-profile", "pytest outcome profile is invalid"),
        ("unsupported-platform", "pytest skip allowlist platform is invalid"),
    ],
)
def test_mysql_outcomes_reject_policy_drift(
    tmp_path: Path, command_id: str, mutation: str, message: str
) -> None:
    manifest = load_manifest(MANIFEST, repository_root=ROOT)
    report_directory = tmp_path / "reports"
    report_directory.mkdir()
    source_sha = "f" * 40
    scoped_outcomes = [
        {
            "nodeid": _MYSQL_CANARY_NODE,
            "status": "skipped",
            "reason": _MYSQL_CANARY_REASON,
        }
    ]
    if mutation == "node-drift":
        scoped_outcomes[0]["nodeid"] += "_renamed"
    elif mutation == "reason-drift":
        scoped_outcomes[0]["reason"] += "."
    elif mutation == "extra-skip":
        scoped_outcomes.append(
            {
                "nodeid": "backend/tests/integration/test_unknown.py::test_unknown",
                "status": "skipped",
                "reason": "unexpected skip",
            }
        )
    elif mutation == "missing-skip":
        scoped_outcomes[0]["status"] = "passed"
        scoped_outcomes[0]["reason"] = ""
    profile_digest, shard_node_digests = _write_mysql_outcome_reports(
        report_directory,
        source_sha=source_sha,
        command_id=command_id,
        platform_id="win32",
        scoped_outcomes=scoped_outcomes,
    )
    profile = "ubuntu-full" if mutation == "wrong-profile" else "mysql-compatibility"
    platform_id = "freebsd" if mutation == "unsupported-platform" else "win32"

    with pytest.raises(BaselineContractError, match=message):
        baseline.validate_pytest_outcome_reports(
            report_directory,
            manifest=manifest,
            source_sha=source_sha,
            command_id=command_id,
            profile=profile,
            profile_node_digest=profile_digest,
            shard_node_digests=shard_node_digests,
            platform_id=platform_id,
        )


def _write_json(path: Path, payload: object) -> None:
    path.write_text(json.dumps(payload), encoding="utf-8")


def _complete_run(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> tuple[Path, dict[str, object], str, Path, Path]:
    source_sha = "1" * 40
    source_identity = {
        "source_sha": source_sha,
        "git_tree": "2" * 40,
        "artifact_digest": "3" * 64,
        "runner_digest": "4" * 64,
    }
    product_runner_digest = "9" * 64

    def fake_source_identity(value: str) -> dict[str, str]:
        assert value == source_sha
        return source_identity

    def fake_environment(
        *, repository_root: Path, mysql_version: str
    ) -> dict[str, object]:
        assert repository_root == ROOT
        return {
            "source_sha": source_sha,
            "git_tree": source_identity["git_tree"],
            "python": "3.14.0",
            "node": "v24.0.0",
            "pnpm": "10.0.0",
            "playwright_chromium": "1.62.1",
            "mysql": mysql_version,
            "os": "test-os",
            "machine": "test-machine",
            "processor": "test-processor",
            "cpu_count": 8,
            "memory_bytes": 16 * 1024**3,
            "fixture_ids": [
                "synthetic-reports-v1",
                "analytics_scale_v1",
                "stage0-worker-synthetic-v1",
            ],
        }

    monkeypatch.setattr(baseline, "_release_source_identity", fake_source_identity)
    monkeypatch.setattr(
        baseline,
        "_release_runner_digest",
        lambda value, suite_name: (
            product_runner_digest
            if value == source_sha and suite_name == "performance"
            else (_ for _ in ()).throw(AssertionError((value, suite_name)))
        ),
    )
    monkeypatch.setattr(baseline, "capture_environment", fake_environment)
    manifest = load_manifest(MANIFEST, repository_root=ROOT)
    run = tmp_path / "stage0-111111111111"
    run.mkdir()
    _write_json(
        run / "run-identity.json",
        {
            "run_id": run.name,
            "source_sha": source_sha,
            "status": "prepared",
        },
    )
    for file_id, command_id, has_profile_digest in baseline._COMMAND_RESULT_IDENTITIES:
        profile_digest = "7" * 64 if has_profile_digest else None
        outcome_evidence: dict[str, object] | None = None
        skip_rows: list[dict[str, str]] = []
        if command_id in baseline._PYTEST_OUTCOME_COMMANDS:
            policy = baseline._PYTEST_OUTCOME_POLICY["commands"][command_id]
            shards = cast(list[str], policy["report_shards"])
            shard_node_digests = {shard: "8" * 64 for shard in shards}
            platform_allowlist = cast(
                dict[str, list[dict[str, object]]], policy["skip_allowlist"]
            )
            skip_rows = [
                {
                    "nodeid": cast(str, entry["nodeid"]),
                    "status": "skipped",
                    "reason": cast(str, entry["reason"]),
                }
                for entry in platform_allowlist["win32"]
                if entry.get("required") is True
            ]
            outcome_evidence = {
                "status": "valid",
                "binding_sha256": baseline.pytest_outcome_binding(
                    source_sha=source_sha,
                    command_id=command_id,
                    profile=cast(str, policy["profile"]),
                    profile_node_digest=profile_digest,
                    shard_node_digests=shard_node_digests,
                    platform_id="win32",
                ),
                "platform_id": "win32",
                "profile": policy["profile"],
                "collected_node_count": 1,
                "collected_node_digest": profile_digest,
                "shard_node_digests": shard_node_digests,
                "report_digests": {f"{shard}.json": "9" * 64 for shard in shards},
                "session_exit_codes": {shard: 0 for shard in shards},
                "private_environment_clear": True,
                "skip_count": len(skip_rows),
                "explained_skip_count": len(skip_rows),
                "unexplained_skip_count": 0,
                "xfail_count": 0,
                "retry_count": 0,
                "flaky_count": 0,
                "skips": skip_rows,
            }
        skip_count = len(skip_rows)
        _write_json(
            run / f"command-result-{file_id}.json",
            {
                "schema_version": 2,
                "command_id": command_id,
                "started_at": "2026-08-28T01:00:00.0000000Z",
                "ended_at": "2026-08-28T01:00:01.0000000Z",
                "exit_code": 0,
                "skip_count": skip_count,
                "explained_skip_count": skip_count,
                "unexplained_skip_count": 0,
                "xfail_count": 0,
                "retry_count": 0,
                "flaky_count": 0,
                "stdout_sha256": "5" * 64,
                "stderr_sha256": "6" * 64,
                "profile_node_digest": profile_digest,
                "pytest_outcome_evidence": outcome_evidence,
            },
        )
    rounds = [
        summarize_round([float(value) for value in range(1, 21)]) for _ in range(3)
    ]
    mysql_scenarios = set(manifest["mysql_matrix_scenarios"])
    for scenario_id in manifest["performance_scenarios"]:
        versions: tuple[str | None, ...] = (
            ("8.0", "8.4") if scenario_id in mysql_scenarios else (None,)
        )
        for mysql_version in versions:
            if mysql_version is not None:
                name = f"backend-{mysql_version}-{scenario_id}.json"
            elif str(scenario_id).startswith("ui-"):
                name = f"ui-{scenario_id}.json"
            else:
                name = f"bundle-{scenario_id}.json"
            payload: dict[str, object] = {
                "schema_version": 1,
                "source_sha": source_sha,
                "scenario_id": scenario_id,
                "unit": "bytes" if str(scenario_id).startswith("frontend-") else "ms",
                "warmup_samples": 3,
                "measured_samples": 20,
                "round_count": 3,
                "rounds": rounds,
            }
            if mysql_version is not None:
                payload.update(
                    {
                        "mysql_version": mysql_version,
                        "git_tree": source_identity["git_tree"],
                        "fixture_id": "stage0-worker-synthetic-v1",
                        "runner_digest": source_identity["runner_digest"],
                        "host_environment_digest": "8" * 64,
                    }
                )
                if scenario_id in baseline._QUEUE_SCENARIOS:
                    raw_name = f"external-explain-{mysql_version}-{scenario_id}.json"
                    payload["explain"] = {
                        "format": "JSON",
                        "unbounded_cartesian_join": False,
                        "external_evidence": raw_name,
                    }
                    _write_json(
                        run / raw_name,
                        {
                            "schema_version": 1,
                            "source_sha": source_sha,
                            "git_tree": source_identity["git_tree"],
                            "fixture_id": "stage0-worker-synthetic-v1",
                            "runner_digest": source_identity["runner_digest"],
                            "host_environment_digest": "8" * 64,
                            "mysql_version": mysql_version,
                            "scenario_id": scenario_id,
                            "format": "JSON",
                            "raw_plan": json.dumps(
                                {"query_block": {"table": {"table_name": scenario_id}}}
                            ),
                        },
                    )
            _write_json(run / name, payload)
    evidence_paths: list[Path] = []
    for version in ("8.0", "8.4"):
        path = tmp_path / f"analytics-{version}.json"
        _write_json(
            path,
            {
                "source_sha": source_identity["source_sha"],
                "git_tree": source_identity["git_tree"],
                "artifact_digest": source_identity["artifact_digest"],
                "runner_digest": product_runner_digest,
                "fixture": "analytics_scale_v1",
                "mysql_version": version,
                "warmup_samples": 3,
                "measured_samples": 20,
                "cpu_count": 4,
                "memory_bytes": 8 * 1024**3,
            },
        )
        evidence_paths.append(path)
    return run, manifest, source_sha, evidence_paths[0], evidence_paths[1]


def test_repository_manifest_is_valid_and_complete() -> None:
    payload = load_manifest(MANIFEST, repository_root=ROOT)
    assert payload["schema_version"] == 1
    assert payload["baseline_id"] == "project-optimization-stage-0-v1"
    assert {entry["id"] for entry in payload["entrypoints"]} == {
        "dev-api",
        "direct-api",
        "container-api",
        "demo-api",
        "live-api",
        "dev-worker",
        "direct-worker",
        "container-worker",
        "live-worker",
    }
    assert {route["path"] for route in payload["routes"]} == {
        "/",
        "/ledger/published-details",
        "/products",
        "/products/:style_id",
        "/dashboard",
        "/catalog",
        "/catalog/styles/:style_id",
        "/catalog/imports/:import_id",
        "/catalog/unmatched",
        "/catalog/versions",
        "/review/batch/:runId",
        "/review/:reportDate",
        "/published/:reportDate",
        "/review-advanced/:reportDate",
        "/published-details/:reportDate",
        "/versions",
        "/admin",
        "*",
    }
    assert {queue["name"] for queue in payload["queues"]} == {
        "publication_outbox",
        "return_dedup",
        "catalog_import",
        "catalog_export",
    }


def test_manifest_rejects_invalid_timing_relationships(tmp_path: Path) -> None:
    payload = json.loads(MANIFEST.read_text(encoding="utf-8"))
    payload["timing_candidate"] = {
        "heartbeat_seconds": 10,
        "stale_seconds": 29,
        "offline_seconds": 60,
        "refresh_seconds": 15,
    }
    path = tmp_path / "manifest.json"
    path.write_text(json.dumps(payload), encoding="utf-8")
    with pytest.raises(BaselineContractError, match="stale_seconds must be at least 3"):
        load_manifest(path, repository_root=ROOT)


def test_manifest_rejects_unknown_keys_and_absolute_repository_paths(
    tmp_path: Path,
) -> None:
    payload = json.loads(MANIFEST.read_text(encoding="utf-8"))
    payload["unexpected"] = True
    path = tmp_path / "manifest.json"
    path.write_text(json.dumps(payload), encoding="utf-8")
    with pytest.raises(BaselineContractError):
        load_manifest(path, repository_root=ROOT)


def test_manifest_rejects_absolute_repository_paths(tmp_path: Path) -> None:
    payload = json.loads(MANIFEST.read_text(encoding="utf-8"))
    payload["entrypoints"][0]["path"] = str(ROOT / "scripts" / "dev-backend.ps1")
    path = tmp_path / "manifest.json"
    path.write_text(json.dumps(payload), encoding="utf-8")
    with pytest.raises(BaselineContractError, match="repository-relative"):
        load_manifest(path, repository_root=ROOT)


def test_manifest_rejects_altered_queue_contract(tmp_path: Path) -> None:
    payload = json.loads(MANIFEST.read_text(encoding="utf-8"))
    payload["queues"][0]["claim"] = "unapproved claim"
    path = tmp_path / "manifest.json"
    path.write_text(json.dumps(payload), encoding="utf-8")
    with pytest.raises(BaselineContractError, match="queue contract"):
        load_manifest(path, repository_root=ROOT)


def test_manifest_rejects_altered_mysql_exclusion(tmp_path: Path) -> None:
    payload = json.loads(MANIFEST.read_text(encoding="utf-8"))
    payload["mysql_hosted_exclusions"] = {}
    path = tmp_path / "manifest.json"
    path.write_text(json.dumps(payload), encoding="utf-8")
    with pytest.raises(BaselineContractError, match="mysql_hosted_exclusions"):
        load_manifest(path, repository_root=ROOT)


def test_manifest_rejects_altered_entrypoint_fact(tmp_path: Path) -> None:
    payload = json.loads(MANIFEST.read_text(encoding="utf-8"))
    payload["entrypoints"][0]["evidence_token"] = "unapproved token"
    path = tmp_path / "manifest.json"
    path.write_text(json.dumps(payload), encoding="utf-8")
    with pytest.raises(BaselineContractError, match="entrypoint contract"):
        load_manifest(path, repository_root=ROOT)


def test_manifest_rejects_altered_route_fact(tmp_path: Path) -> None:
    payload = json.loads(MANIFEST.read_text(encoding="utf-8"))
    payload["routes"][0]["primary_action"] = "unapproved action"
    path = tmp_path / "manifest.json"
    path.write_text(json.dumps(payload), encoding="utf-8")
    with pytest.raises(BaselineContractError, match="route contract"):
        load_manifest(path, repository_root=ROOT)


@pytest.mark.parametrize(
    ("field", "replacement", "message"),
    [
        ("non_route_states", [], "non_route_states"),
        ("quality_profiles", [], "quality_profiles"),
        ("owner_roles", {}, "owner_roles"),
    ],
)
def test_manifest_rejects_altered_auxiliary_contracts(
    tmp_path: Path,
    field: str,
    replacement: object,
    message: str,
) -> None:
    payload = json.loads(MANIFEST.read_text(encoding="utf-8"))
    payload[field] = replacement
    path = tmp_path / "manifest.json"
    path.write_text(json.dumps(payload), encoding="utf-8")
    with pytest.raises(BaselineContractError, match=message):
        load_manifest(path, repository_root=ROOT)


def test_evidence_root_must_be_external_empty_and_new(tmp_path: Path) -> None:
    repository = tmp_path / "repository"
    repository.mkdir()
    inside = repository / "evidence"
    inside.mkdir()
    with pytest.raises(BaselineContractError, match="outside the repository"):
        resolve_empty_external_root(str(inside), repository_root=repository)
    external = tmp_path / "external"
    external.mkdir()
    (external / "existing.json").write_text("{}", encoding="utf-8")
    with pytest.raises(BaselineContractError, match="must be empty"):
        resolve_empty_external_root(str(external), repository_root=repository)


def test_round_summary_uses_nearest_rank_p95() -> None:
    samples = [float(value) for value in range(1, 21)]
    assert summarize_round(samples) == {
        "sample_count": 20,
        "samples": samples,
        "p50": 10.5,
        "p95": 19.0,
        "max": 20.0,
    }


def test_scenario_summary_requires_three_rounds_of_twenty() -> None:
    valid = [
        summarize_round([float(value) for value in range(1, 21)]) for _ in range(3)
    ]
    assert summarize_scenario(valid)["median_round_p95"] == 19.0
    with pytest.raises(BaselineContractError, match="exactly 3 rounds"):
        summarize_scenario(valid[:2])


def test_run_validation_rejects_identity_mismatch(tmp_path: Path) -> None:
    (tmp_path / "run-identity.json").write_text(
        json.dumps(
            {
                "run_id": "stage0-111111111111",
                "source_sha": "1" * 40,
                "status": "prepared",
            }
        ),
        encoding="utf-8",
    )
    (tmp_path / "run-summary.json").write_text(
        json.dumps(
            {
                "source_sha": "2" * 40,
                "skip_count": 0,
                "xfail_count": 0,
                "retry_count": 0,
                "flaky_count": 0,
            }
        ),
        encoding="utf-8",
    )
    manifest = load_manifest(MANIFEST, repository_root=ROOT)
    with pytest.raises(BaselineContractError, match="run identity"):
        validate_run(tmp_path, manifest=manifest, source_sha="1" * 40)


def test_freeze_record_is_bound_to_approval_and_cannot_overwrite(
    tmp_path: Path,
) -> None:
    validated = {
        "run_id": "stage0-111111111111",
        "source_sha": "1" * 40,
        "validated": True,
        "scenarios": {
            "admin-maintenance-api": {
                "unit": "ms",
                "rounds": [{"p50": 10.0, "p95": 19.0, "max": 20.0} for _ in range(3)],
                "median_round_p95": 19.0,
            }
        },
        "environment_digest": "2" * 64,
        "evidence_digest": "3" * 64,
        "candidate_timing": {
            "heartbeat_seconds": 10,
            "stale_seconds": 30,
            "offline_seconds": 60,
            "refresh_seconds": 15,
            "offline_visible_seconds": 75,
            "approval_status": "proposed",
        },
    }
    record = build_freeze_record(
        validated,
        approved_by="project-owner",
        approval_reference="codex-task-explicit-approval",
        approval_token=baseline._freeze_approval_token(validated),
        approved_timing={
            "heartbeat_seconds": 10,
            "stale_seconds": 30,
            "offline_seconds": 60,
            "refresh_seconds": 15,
        },
        approved_budgets={"admin-maintenance-api": 125.0},
    )
    path = tmp_path / "approval-v1.json"
    write_json_exclusive(path, record)
    with pytest.raises(FileExistsError):
        write_json_exclusive(path, record)


def test_build_summary_rejects_missing_required_mysql_skip_evidence(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    run, manifest, source_sha, mysql80, mysql84 = _complete_run(tmp_path, monkeypatch)
    result_path = run / "command-result-04-mysql-compatibility-8-0.json"
    result = cast(
        dict[str, object], json.loads(result_path.read_text(encoding="utf-8"))
    )
    outcome = cast(dict[str, object], result["pytest_outcome_evidence"])
    outcome["skips"] = []
    for name in ("skip_count", "explained_skip_count"):
        result[name] = 0
        outcome[name] = 0
    _write_json(result_path, result)

    with pytest.raises(
        BaselineContractError, match="pytest required skip evidence is missing"
    ):
        build_run_summary(
            run,
            manifest=manifest,
            source_sha=source_sha,
            mysql80_evidence=mysql80,
            mysql84_evidence=mysql84,
        )


@pytest.mark.parametrize(
    "file_id",
    (
        "04-mysql-compatibility-8-0",
        "05-mysql-compatibility-8-4",
    ),
)
def test_build_summary_rejects_duplicate_mysql_skip_evidence(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, file_id: str
) -> None:
    run, manifest, source_sha, mysql80, mysql84 = _complete_run(tmp_path, monkeypatch)
    result_path = run / f"command-result-{file_id}.json"
    result = cast(
        dict[str, object], json.loads(result_path.read_text(encoding="utf-8"))
    )
    outcome = cast(dict[str, object], result["pytest_outcome_evidence"])
    skips = cast(list[dict[str, str]], outcome["skips"])
    skips.append(dict(skips[0]))
    for name in ("skip_count", "explained_skip_count"):
        result[name] = 2
        outcome[name] = 2
    _write_json(result_path, result)

    with pytest.raises(
        BaselineContractError,
        match="pytest skip evidence contains duplicate node identities",
    ):
        build_run_summary(
            run,
            manifest=manifest,
            source_sha=source_sha,
            mysql80_evidence=mysql80,
            mysql84_evidence=mysql84,
        )


def test_build_summary_and_validate_run_happy_path(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    run, manifest, source_sha, mysql80, mysql84 = _complete_run(tmp_path, monkeypatch)
    summary = build_run_summary(
        run,
        manifest=manifest,
        source_sha=source_sha,
        mysql80_evidence=mysql80,
        mysql84_evidence=mysql84,
    )
    write_json_exclusive(run / "run-summary.json", summary)
    validated = validate_run(run, manifest=manifest, source_sha=source_sha)
    assert validated["validated"] is True
    assert len(validated["scenarios"]) == 26
    assert set(summary["external_evidence"]) == {
        "analytics_scale_v1:mysql:8.0",
        "analytics_scale_v1:mysql:8.4",
    }
    assert set(summary["timing_trials"]) == {
        "heartbeat-single-row-update",
        "heartbeat-long-task",
        "heartbeat-maintenance-barrier",
    }


@pytest.mark.parametrize("mutation", ["missing", "invalid-protocol"])
def test_finalize_rejects_incomplete_or_invalid_scenario_set(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, mutation: str
) -> None:
    run, _, source_sha, mysql80, mysql84 = _complete_run(tmp_path, monkeypatch)
    target = run / "bundle-frontend-bundle-p0_catalog.json"
    if mutation == "missing":
        target.unlink()
    else:
        payload = json.loads(target.read_text(encoding="utf-8"))
        payload["measured_samples"] = 19
        _write_json(target, payload)
    with pytest.raises(SystemExit) as error:
        main(
            [
                "finalize-run",
                "--run-dir",
                str(run),
                "--manifest",
                str(MANIFEST),
                "--source-sha",
                source_sha,
                "--mysql80-evidence",
                str(mysql80),
                "--mysql84-evidence",
                str(mysql84),
            ]
        )
    assert error.value.code == 2
    assert not (run / "run-summary.json").exists()


@pytest.mark.parametrize("mutation", ["tamper", "add", "remove"])
def test_validate_run_rejects_scenario_set_changes_after_finalize(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, mutation: str
) -> None:
    run, manifest, source_sha, mysql80, mysql84 = _complete_run(tmp_path, monkeypatch)
    summary = build_run_summary(
        run,
        manifest=manifest,
        source_sha=source_sha,
        mysql80_evidence=mysql80,
        mysql84_evidence=mysql84,
    )
    write_json_exclusive(run / "run-summary.json", summary)
    target = run / "ui-ui-dashboard-load.json"
    if mutation == "tamper":
        payload = json.loads(target.read_text(encoding="utf-8"))
        payload["diagnostic"] = "changed after finalize"
        _write_json(target, payload)
    elif mutation == "add":
        payload = json.loads(target.read_text(encoding="utf-8"))
        _write_json(run / "ui-added-after-finalize.json", payload)
    else:
        target.unlink()
    with pytest.raises(BaselineContractError, match="finalized scenario evidence"):
        validate_run(run, manifest=manifest, source_sha=source_sha)


def test_malformed_samples_and_budgets_are_contract_errors() -> None:
    with pytest.raises(BaselineContractError, match="finite non-negative"):
        summarize_round([object(), *[1.0] * 19])  # type: ignore[list-item]
    with pytest.raises(BaselineContractError, match="budget"):
        build_freeze_record(
            {
                "run_id": "stage0-111111111111",
                "source_sha": "1" * 40,
                "validated": True,
                "scenarios": {"admin-maintenance-api": {}},
                "environment_digest": "2" * 64,
                "evidence_digest": "3" * 64,
            },
            approved_by="project-owner",
            approval_reference="explicit-approval",
            approval_token="5" * 64,
            approved_timing={
                "heartbeat_seconds": 10,
                "stale_seconds": 30,
                "offline_seconds": 60,
                "refresh_seconds": 15,
            },
            approved_budgets={"admin-maintenance-api": object()},  # type: ignore[dict-item]
        )


def test_freeze_cli_rejects_malformed_budget_without_disclosure(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    run, manifest, source_sha, mysql80, mysql84 = _complete_run(tmp_path, monkeypatch)
    summary = build_run_summary(
        run,
        manifest=manifest,
        source_sha=source_sha,
        mysql80_evidence=mysql80,
        mysql84_evidence=mysql84,
    )
    write_json_exclusive(run / "run-summary.json", summary)
    overrides = tmp_path / "overrides.json"
    sentinel = "mysql://user:secret@example.invalid/database"
    _write_json(overrides, {"admin-maintenance-api": {"value": sentinel}})
    output = tmp_path / "approval.json"
    arguments = [
        "freeze",
        "--run-dir",
        str(run),
        "--manifest",
        str(MANIFEST),
        "--source-sha",
        source_sha,
        "--approved-by",
        "project-owner",
        "--approval-reference",
        "explicit-approval",
        "--approved-run-id",
        run.name,
        "--heartbeat-seconds",
        "10",
        "--stale-seconds",
        "30",
        "--offline-seconds",
        "60",
        "--refresh-seconds",
        "15",
        "--budget-overrides",
        str(overrides),
        "--output",
        str(output),
    ]
    assert main(arguments) == 0
    token = json.loads(capsys.readouterr().out)["approval_token"]
    arguments.insert(-2, "--complete-freeze")
    arguments.insert(-2, "--approved-token")
    arguments.insert(-2, token)
    with pytest.raises(SystemExit) as error:
        main(arguments)
    assert error.value.code == 2
    assert sentinel not in capsys.readouterr().err
    assert not output.exists()


def test_capture_environment_uses_windows_pnpm_shim(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    commands: list[list[str]] = []

    def checked(command: list[str], _cwd: Path) -> str:
        commands.append(command)
        return "test"

    monkeypatch.setattr(sys, "platform", "win32")
    monkeypatch.setattr(baseline, "_checked_output", checked)
    monkeypatch.setattr(baseline, "_physical_memory_bytes", lambda: 1)
    baseline.capture_environment(repository_root=ROOT, mysql_version="8.0")
    assert ["pnpm.cmd", "--version"] in commands


def test_release_identity_uses_canonical_runner_paths(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    source_sha = "a" * 40
    canonical = ["canonical-one", "canonical-two"]
    old = ["old-performance-runner"]
    requested: list[list[str]] = []

    monkeypatch.setattr(baseline, "REPOSITORY_ROOT", tmp_path)
    monkeypatch.setattr(
        baseline,
        "_read_json_object",
        lambda *_args, **_kwargs: {
            "release_suites": {
                "performance": {"runner_paths": old},
                "project-optimization-baseline": {"runner_paths": canonical},
            }
        },
    )

    def checked(command: list[str], _cwd: Path) -> str:
        requested.append(command)
        if command[-1] == "HEAD":
            return source_sha
        if command[-1].endswith("^{tree}"):
            return "b" * 40
        return "c" * 40

    monkeypatch.setattr(baseline, "_checked_output", checked)
    monkeypatch.setattr(
        subprocess,
        "run",
        lambda *args, **kwargs: subprocess.CompletedProcess(
            args[0], 0, stdout=b"tree\n"
        ),
    )
    baseline._release_source_identity(source_sha)
    blob_specs = {command[-1] for command in requested if ":" in command[-1]}
    assert blob_specs == {f"{source_sha}:{path}" for path in canonical}
    requested.clear()
    baseline._release_runner_digest(source_sha, "performance")
    blob_specs = {command[-1] for command in requested if ":" in command[-1]}
    assert blob_specs == {f"{source_sha}:{path}" for path in old}


def test_command_results_require_exact_closed_identity_set(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    run, manifest, source_sha, mysql80, mysql84 = _complete_run(tmp_path, monkeypatch)
    result = run / "command-result-01-ubuntu-full.json"
    payload = json.loads(result.read_text(encoding="utf-8"))
    payload["unexpected"] = True
    _write_json(result, payload)
    with pytest.raises(BaselineContractError, match="command result"):
        build_run_summary(
            run,
            manifest=manifest,
            source_sha=source_sha,
            mysql80_evidence=mysql80,
            mysql84_evidence=mysql84,
        )


def test_command_results_reject_empty_non_profile_digest(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    run, manifest, source_sha, mysql80, mysql84 = _complete_run(tmp_path, monkeypatch)
    result = run / "command-result-06-generated-contract.json"
    payload = json.loads(result.read_text(encoding="utf-8"))
    payload["profile_node_digest"] = ""
    _write_json(result, payload)

    with pytest.raises(BaselineContractError, match="profile identity"):
        build_run_summary(
            run,
            manifest=manifest,
            source_sha=source_sha,
            mysql80_evidence=mysql80,
            mysql84_evidence=mysql84,
        )


def test_external_evidence_requires_controlled_environment_identity(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    run, manifest, source_sha, mysql80, mysql84 = _complete_run(tmp_path, monkeypatch)
    payload = json.loads(mysql80.read_text(encoding="utf-8"))
    payload["cpu_count"] = 8
    _write_json(mysql80, payload)
    with pytest.raises(BaselineContractError, match="evidence identity"):
        build_run_summary(
            run,
            manifest=manifest,
            source_sha=source_sha,
            mysql80_evidence=mysql80,
            mysql84_evidence=mysql84,
        )


def test_external_evidence_requires_product_runner_identity(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    run, manifest, source_sha, mysql80, mysql84 = _complete_run(tmp_path, monkeypatch)
    payload = json.loads(mysql80.read_text(encoding="utf-8"))
    payload["runner_digest"] = "4" * 64
    _write_json(mysql80, payload)
    with pytest.raises(BaselineContractError, match="runner identity"):
        build_run_summary(
            run,
            manifest=manifest,
            source_sha=source_sha,
            mysql80_evidence=mysql80,
            mysql84_evidence=mysql84,
        )


def test_raw_explain_bytes_are_finalized_and_revalidated(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    run, manifest, source_sha, mysql80, mysql84 = _complete_run(tmp_path, monkeypatch)
    raw = run / "external-explain-8.0-queue-publication-outbox-query.json"
    summary = build_run_summary(
        run,
        manifest=manifest,
        source_sha=source_sha,
        mysql80_evidence=mysql80,
        mysql84_evidence=mysql84,
    )
    write_json_exclusive(run / "run-summary.json", summary)
    payload = json.loads(raw.read_text(encoding="utf-8"))
    payload["raw_plan"] = json.dumps(
        {"query_block": {"table": {"table_name": "tampered-after-finalize"}}}
    )
    _write_json(raw, payload)
    with pytest.raises(BaselineContractError, match="raw EXPLAIN"):
        validate_run(run, manifest=manifest, source_sha=source_sha)


def test_freeze_requires_explicit_budget_acceptance_and_retains_measurements(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    run, manifest, source_sha, mysql80, mysql84 = _complete_run(tmp_path, monkeypatch)
    summary = build_run_summary(
        run,
        manifest=manifest,
        source_sha=source_sha,
        mysql80_evidence=mysql80,
        mysql84_evidence=mysql84,
    )
    write_json_exclusive(run / "run-summary.json", summary)
    arguments = [
        "freeze",
        "--run-dir",
        str(run),
        "--manifest",
        str(MANIFEST),
        "--source-sha",
        source_sha,
        "--approved-by",
        "project-owner",
        "--approval-reference",
        "explicit-approval",
        "--approved-run-id",
        run.name,
        "--heartbeat-seconds",
        "10",
        "--stale-seconds",
        "30",
        "--offline-seconds",
        "60",
        "--refresh-seconds",
        "15",
        "--accept-proposed-budgets",
        "--output",
        str(tmp_path / "approval.json"),
    ]
    assert main(arguments) == 0
    assert not (tmp_path / "approval.json").exists()
    preview = json.loads(capsys.readouterr().out)
    assert preview["approval_required"] is True
    assert preview["run_id"] == run.name
    approval_token = preview["approval_token"]
    assert len(approval_token) == 64

    scenario_path = run / "backend-8.0-admin-maintenance-api.json"
    scenario = json.loads(scenario_path.read_text(encoding="utf-8"))
    scenario["rounds"] = [
        summarize_round([float(value) for value in range(2, 22)]) for _ in range(3)
    ]
    _write_json(scenario_path, scenario)
    replacement_summary = build_run_summary(
        run,
        manifest=manifest,
        source_sha=source_sha,
        mysql80_evidence=mysql80,
        mysql84_evidence=mysql84,
    )
    _write_json(run / "run-summary.json", replacement_summary)

    arguments.insert(-2, "--complete-freeze")
    arguments.insert(-2, "--approved-token")
    arguments.insert(-2, approval_token)
    with pytest.raises(SystemExit) as error:
        main(arguments)
    assert error.value.code == 2
    assert not (tmp_path / "approval.json").exists()
    capsys.readouterr()

    preview_arguments = [
        value
        for value in arguments
        if value
        not in {
            "--complete-freeze",
            "--approved-token",
            approval_token,
        }
    ]
    assert main(preview_arguments) == 0
    refreshed_preview = json.loads(capsys.readouterr().out)
    refreshed_token = refreshed_preview["approval_token"]
    assert refreshed_token != approval_token
    token_index = arguments.index("--approved-token") + 1
    arguments[token_index] = refreshed_token
    assert main(arguments) == 0
    record = json.loads((tmp_path / "approval.json").read_text(encoding="utf-8"))
    assert record["approval_token"] == refreshed_token
    measurement = record["scenario_measurements"]["admin-maintenance-api@mysql-8.0"]
    assert set(measurement) >= {
        "unit",
        "rounds",
        "median_round_p95",
        "approved_ceiling",
    }
    assert set(measurement["rounds"][0]) == {"p50", "p95", "max"}


def test_synthetic_collect_flow_stages_preflights_publishes_and_validates(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    run, manifest, source_sha, mysql80, mysql84 = _complete_run(tmp_path, monkeypatch)
    command_staging = tmp_path / f".{run.name}-command-results"
    scenario_staging = tmp_path / f".{run.name}-scenario-placeholders"
    command_staging.mkdir()
    scenario_staging.mkdir()
    for path in list(run.iterdir()):
        if path.name.startswith("command-result-"):
            path.rename(command_staging / path.name)
        elif path.name != "run-identity.json":
            path.rename(scenario_staging / path.name)

    task4_identity = {
        "source_sha": source_sha,
        "git_tree": "2" * 40,
        "fixture_id": "stage0-worker-synthetic-v1",
        "runner_digest": "4" * 64,
        "host_environment_digest": "8" * 64,
    }
    monkeypatch.setattr(producer, "_release_identity", lambda: task4_identity)
    assert (
        producer.verify_baseline_preflight(
            run,
            approved_scenarios=set(cast(list[str], manifest["mysql_matrix_scenarios"])),
        )
        == task4_identity
    )
    assert not any(run.glob("command-result-*.json"))

    for path in list(scenario_staging.iterdir()):
        path.rename(run / path.name)
    scenario_staging.rmdir()
    published = publish_command_results(command_staging, run)
    assert published["published"] is True
    assert not command_staging.exists()
    assert len(list(run.glob("command-result-*.json"))) == 11

    summary = build_run_summary(
        run,
        manifest=manifest,
        source_sha=source_sha,
        mysql80_evidence=mysql80,
        mysql84_evidence=mysql84,
    )
    write_json_exclusive(run / "run-summary.json", summary)
    assert (
        validate_run(run, manifest=manifest, source_sha=source_sha)["validated"] is True
    )


def test_runner_default_profile_identity_publishes_as_json_null(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    run, _, _, _, _ = _complete_run(tmp_path, monkeypatch)
    command_staging = tmp_path / f".{run.name}-command-results"
    command_staging.mkdir()
    for path in list(run.glob("command-result-*.json")):
        path.rename(command_staging / path.name)
    (command_staging / "command-result-06-generated-contract.json").unlink()

    helper_names = (
        "Get-Sha256Bytes",
        "Protect-Output",
        "Write-ExclusiveJson",
        "Get-ManagedEnvironmentSnapshot",
        "Clear-PrivateCanaryEnvironment",
        "Clear-Stage0PytestOutcomeEnvironment",
        "Restore-ManagedEnvironment",
        "Get-PytestOutcomeBinding",
        "Get-ValidatedPytestOutcome",
        "Remove-OwnedDirectRegularChildren",
        "Invoke-NativeChecked",
        "Publish-CommandResults",
    )
    command = r"""
$ErrorActionPreference = 'Stop'
$tokens = $null
$errors = $null
$ast = [Management.Automation.Language.Parser]::ParseFile(
    $args[0], [ref]$tokens, [ref]$errors
)
foreach ($name in $args[1].Split(',')) {
    $function = $ast.FindAll({
        param($node)
        $node -is [Management.Automation.Language.FunctionDefinitionAst] -and
            $node.Name -ceq $name
    }, $true) | Select-Object -First 1
    if ($null -eq $function) {
        throw "runner helper is missing: $name"
    }
    . ([scriptblock]::Create($function.Extent.Text))
}
$script:commandStagingDirectory = $args[2]
$script:commandSequence = 5
$script:nativeCommand = $args[3]
$script:PythonExecutable = $args[3]
$script:SourceSha = ('1' * 40)
$script:manifest = $args[4]
$script:platformId = 'win32'
$script:runDirectory = $args[5]
$script:privateCanaryEnvironmentNames = @()
$script:stage0PytestOutcomeEnvironmentNames = @(
    'APP_STAGE0_PYTEST_OUTCOME_DIRECTORY',
    'APP_STAGE0_PYTEST_OUTCOME_BINDING',
    'APP_STAGE0_PYTEST_OUTCOME_COMMAND_ID',
    'APP_STAGE0_PYTEST_OUTCOME_SHARD',
    'APP_STAGE0_PYTEST_OUTCOME_EXPECTED_NODE_DIGEST',
    'APP_STAGE0_PYTEST_OUTCOME_SHARD_DIGESTS'
)
Invoke-NativeChecked `
    -Description 'generated contract regression' `
    -EvidenceKey 'generated-contract' `
    -SuppressOutput {
    & $script:nativeCommand -c 'raise SystemExit(0)'
}
Publish-CommandResults
"""
    completed = subprocess.run(
        [
            "pwsh",
            "-NoProfile",
            "-CommandWithArgs",
            command,
            str(ROOT / "scripts/run-project-optimization-baseline.ps1"),
            ",".join(helper_names),
            str(command_staging),
            sys.executable,
            str(MANIFEST),
            str(run),
        ],
        cwd=ROOT,
        check=False,
        capture_output=True,
        text=True,
        encoding="utf-8",
    )
    assert completed.returncode == 0, completed.stderr
    published = json.loads(
        (run / "command-result-06-generated-contract.json").read_text(encoding="utf-8")
    )
    assert published["profile_node_digest"] is None
    assert not command_staging.exists()
