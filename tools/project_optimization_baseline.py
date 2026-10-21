from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import platform
import re
import secrets
import statistics
import subprocess
import sys
from collections.abc import Mapping, Sequence
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, cast

REPOSITORY_ROOT = Path(__file__).resolve().parents[1]


class BaselineContractError(ValueError):
    """The baseline manifest or evidence violates a closed project contract."""


_TOP_LEVEL_KEYS = {
    "schema_version",
    "baseline_id",
    "design_commit",
    "business_baseline_commit",
    "roles",
    "page_states",
    "entrypoints",
    "routes",
    "non_route_states",
    "queues",
    "performance_protocol",
    "performance_scenarios",
    "mysql_matrix_scenarios",
    "required_external_evidence",
    "timing_candidate",
    "quality_profiles",
    "pytest_outcome_policy",
    "mysql_hosted_exclusions",
    "owner_roles",
}
_ROLES = ["admin", "data_manager", "viewer"]
_PAGE_STATES = [
    "normal",
    "loading",
    "empty",
    "error",
    "permission",
    "offline",
    "long-content",
    "narrow",
]
_ENTRYPOINT_IDS = [
    "dev-api",
    "direct-api",
    "container-api",
    "demo-api",
    "live-api",
    "dev-worker",
    "direct-worker",
    "container-worker",
    "live-worker",
]
_ROUTE_KINDS = {
    "/": "business",
    "/ledger/published-details": "business",
    "/products": "feature-gated",
    "/products/:style_id": "feature-gated",
    "/dashboard": "redirect",
    "/catalog": "business",
    "/catalog/styles/:style_id": "business",
    "/catalog/imports/:import_id": "permission-gated",
    "/catalog/unmatched": "permission-gated",
    "/catalog/maintenance": "permission-gated",
    "/catalog/versions": "permission-gated",
    "/review/batch/:runId": "permission-gated",
    "/review/:reportDate": "role-branch",
    "/published/:reportDate": "business",
    "/review-advanced/:reportDate": "role-branch",
    "/published-details/:reportDate": "business",
    "/versions": "business",
    "/admin": "permission-gated",
    "*": "redirect",
}
_ROUTE_ROLES = {
    "/catalog/imports/:import_id": ["admin", "data_manager"],
    "/catalog/unmatched": ["admin", "data_manager"],
    "/catalog/maintenance": ["admin", "data_manager"],
    "/catalog/versions": ["admin", "data_manager"],
    "/review/batch/:runId": ["admin", "data_manager"],
    "/admin": ["admin"],
}
_QUEUE_NAMES = [
    "publication_outbox",
    "return_dedup",
    "catalog_import",
    "catalog_export",
]
_PERFORMANCE_PROTOCOL = {
    "warmups_per_round": 3,
    "samples_per_round": 20,
    "rounds": 3,
    "round_summaries": ["p50", "p95", "max"],
    "cross_round_aggregate": "median_of_round_p95",
}
_PERFORMANCE_SCENARIOS = [
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
    "ui-dashboard-load",
    "ui-batch-review-confirm",
    "ui-admin-maintenance-load",
    "ui-product-chart-load",
    "frontend-bundle-legacy_parser",
    "frontend-bundle-p0_catalog",
]
_MYSQL_MATRIX_SCENARIOS = _PERFORMANCE_SCENARIOS[:10]
_NON_ROUTE_STATES = [
    "login",
    "session-restore",
    "site-loading",
    "site-error",
    "offline",
    "permission-denied",
    "feature-source-legacy_parser",
    "feature-source-p0_catalog",
]
_QUALITY_PROFILES = [
    "ubuntu-full",
    "windows-smoke",
    "frontend-full",
    "mysql-compatibility-8.0",
    "mysql-compatibility-8.4",
    "generated-contract",
    "project-optimization-baseline",
]
_CANARY_PRIVATE_NODE = (
    "backend/tests/integration/test_product_catalog_canary.py::"
    "test_private_representatives_preserve_shape_quoting_and_identity_semantics"
)
_CANARY_CURRENT_NODE = (
    "backend/tests/integration/test_product_catalog_canary.py::"
    "test_current_database_read_only_snapshot_matches_approved_counts"
)
_PRIVATE_CSV_NODE = (
    "backend/tests/integration/test_real_csv_regression.py::"
    "test_private_real_csv_matches_approved_golden_manifest"
)
_POSIX_PRIVATE_NODE = (
    "backend/tests/unit/imports/test_storage.py::"
    "test_managed_directories_and_staged_content_are_private"
)
_SYMLINK_NODE = (
    "backend/tests/unit/imports/test_storage.py::"
    "test_assert_ready_rejects_an_actual_symlink_root_when_supported"
)
_WINDOWS_FLUSH_NODE = (
    "backend/tests/unit/imports/test_storage.py::"
    "test_fsync_directory_uses_the_windows_flush_adapter"
)
_WINDOWS_VOLUME_NODE = (
    "backend/tests/unit/imports/test_storage.py::"
    "test_assert_ready_checks_the_windows_storage_volume"
)
_MYSQL_CANARY_NODE = (
    "backend/tests/integration/test_product_catalog_permissions.py::"
    "test_canary_identity_is_select_only_when_configured"
)
_MYSQL_CANARY_REASON = (
    "current database canary is verified only by its canonical runner"
)
_PRIVATE_CSV_SKIP_REASON = (
    "private CSV regression data unavailable: approved manifest is missing"
)
_MYSQL_CANARY_SKIP_POLICY = {
    "nodeid": _MYSQL_CANARY_NODE,
    "reason": _MYSQL_CANARY_REASON,
    "match": "exact",
    "required": True,
}
_PYTEST_OUTCOME_POLICY: dict[str, Any] = {
    "schema_version": 1,
    "commands": {
        "ubuntu-full": {
            "profile": "ubuntu-full",
            "report_shards": ["pytest"],
            "skip_allowlist": {
                "win32": [
                    {
                        "nodeid": _CANARY_PRIVATE_NODE,
                        "reason": "private canary corpus is unavailable",
                        "match": "exact",
                    },
                    {
                        "nodeid": _CANARY_CURRENT_NODE,
                        "reason": "SELECT-only current database URL is required",
                        "match": "exact",
                    },
                    {
                        "nodeid": _PRIVATE_CSV_NODE,
                        "reason": _PRIVATE_CSV_SKIP_REASON,
                        "match": "exact",
                    },
                    {
                        "nodeid": _POSIX_PRIVATE_NODE,
                        "reason": "POSIX permission bits are unavailable",
                        "match": "exact",
                    },
                    {
                        "nodeid": _SYMLINK_NODE,
                        "reason": "directory symlinks are unavailable: ",
                        "match": "prefix",
                    },
                ],
                "linux": [
                    {
                        "nodeid": _CANARY_PRIVATE_NODE,
                        "reason": "private canary corpus is unavailable",
                        "match": "exact",
                    },
                    {
                        "nodeid": _CANARY_CURRENT_NODE,
                        "reason": "SELECT-only current database URL is required",
                        "match": "exact",
                    },
                    {
                        "nodeid": _PRIVATE_CSV_NODE,
                        "reason": _PRIVATE_CSV_SKIP_REASON,
                        "match": "exact",
                    },
                    {
                        "nodeid": _WINDOWS_FLUSH_NODE,
                        "reason": "Windows directory flush is unavailable",
                        "match": "exact",
                    },
                    {
                        "nodeid": _WINDOWS_VOLUME_NODE,
                        "reason": "Windows volume checks are unavailable",
                        "match": "exact",
                    },
                ],
                "darwin": [
                    {
                        "nodeid": _CANARY_PRIVATE_NODE,
                        "reason": "private canary corpus is unavailable",
                        "match": "exact",
                    },
                    {
                        "nodeid": _CANARY_CURRENT_NODE,
                        "reason": "SELECT-only current database URL is required",
                        "match": "exact",
                    },
                    {
                        "nodeid": _PRIVATE_CSV_NODE,
                        "reason": _PRIVATE_CSV_SKIP_REASON,
                        "match": "exact",
                    },
                    {
                        "nodeid": _WINDOWS_FLUSH_NODE,
                        "reason": "Windows directory flush is unavailable",
                        "match": "exact",
                    },
                    {
                        "nodeid": _WINDOWS_VOLUME_NODE,
                        "reason": "Windows volume checks are unavailable",
                        "match": "exact",
                    },
                ],
            },
        },
        "windows-smoke": {
            "profile": "windows-smoke",
            "report_shards": ["pytest"],
            "skip_allowlist": {
                "win32": [
                    {
                        "nodeid": _POSIX_PRIVATE_NODE,
                        "reason": "POSIX permission bits are unavailable",
                        "match": "exact",
                    },
                    {
                        "nodeid": _SYMLINK_NODE,
                        "reason": "directory symlinks are unavailable: ",
                        "match": "prefix",
                    },
                ],
                "linux": [
                    {
                        "nodeid": _WINDOWS_FLUSH_NODE,
                        "reason": "Windows directory flush is unavailable",
                        "match": "exact",
                    },
                    {
                        "nodeid": _WINDOWS_VOLUME_NODE,
                        "reason": "Windows volume checks are unavailable",
                        "match": "exact",
                    },
                ],
                "darwin": [
                    {
                        "nodeid": _WINDOWS_FLUSH_NODE,
                        "reason": "Windows directory flush is unavailable",
                        "match": "exact",
                    },
                    {
                        "nodeid": _WINDOWS_VOLUME_NODE,
                        "reason": "Windows volume checks are unavailable",
                        "match": "exact",
                    },
                ],
            },
        },
        "mysql-compatibility-8-0": {
            "profile": "mysql-compatibility",
            "report_shards": ["migration", "scoped"],
            "skip_allowlist": {
                "win32": [_MYSQL_CANARY_SKIP_POLICY],
                "linux": [_MYSQL_CANARY_SKIP_POLICY],
                "darwin": [_MYSQL_CANARY_SKIP_POLICY],
            },
        },
        "mysql-compatibility-8-4": {
            "profile": "mysql-compatibility",
            "report_shards": ["migration", "scoped"],
            "skip_allowlist": {
                "win32": [_MYSQL_CANARY_SKIP_POLICY],
                "linux": [_MYSQL_CANARY_SKIP_POLICY],
                "darwin": [_MYSQL_CANARY_SKIP_POLICY],
            },
        },
        "stage0-backend-8-0": {
            "profile": "project-optimization-baseline",
            "report_shards": ["scoped"],
            "skip_allowlist": {"win32": [], "linux": [], "darwin": []},
        },
        "stage0-backend-8-4": {
            "profile": "project-optimization-baseline",
            "report_shards": ["scoped"],
            "skip_allowlist": {"win32": [], "linux": [], "darwin": []},
        },
    },
}
_OWNER_ROLES = {
    "stage_owner": "project_owner",
    "backend_evidence": "backend_maintainer",
    "frontend_evidence": "frontend_maintainer",
    "database_safety": "database_operator",
    "rollback": "change_author",
}
_ENTRYPOINTS_DIGEST = "0162b9a1d8126ecc81b1d72a9dc4e9965e1266499fe3684cb484706d417f31f6"
_ROUTES_DIGEST = "80fb99a8581602f9d43c6a02f11d559f7aaedd9e543e9520d15da8e921899196"
_QUEUES_DIGEST = "6931ccac3e30bacf0816eb28322a2dd3ec20dbbf309b2c052105da71796934dc"
_MYSQL_HOSTED_EXCLUSIONS_DIGEST = (
    "314f60ddea98947d15b6a154ef877493a799693be7eb04bcd7bfa743bd369d67"
)


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise BaselineContractError(message)


def _as_list(value: object, message: str) -> list[Any]:
    _require(isinstance(value, list), message)
    return cast(list[Any], value)


def _as_object(value: object, message: str) -> dict[str, Any]:
    _require(isinstance(value, dict), message)
    return cast(dict[str, Any], value)


def _contract_digest(value: object) -> str:
    canonical = json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _validate_entrypoints(entries: object, repository_root: Path) -> None:
    rows = _as_list(entries, "entrypoints must be a list")
    _require(len(rows) == len(_ENTRYPOINT_IDS), "entrypoints must have 9 identities")
    ids: list[str] = []
    for entry in rows:
        row = _as_object(entry, "each entrypoint must be an object")
        _require(
            set(row) == {"id", "kind", "path", "evidence_token", "schema_guard"},
            "entrypoint keys are not the closed v1 contract",
        )
        _require(
            isinstance(row["id"], str)
            and isinstance(row["kind"], str)
            and isinstance(row["path"], str)
            and isinstance(row["evidence_token"], str)
            and isinstance(row["schema_guard"], str),
            "entrypoint values must be strings",
        )
        path = Path(row["path"])
        _require(
            not path.is_absolute() and ".." not in path.parts,
            "entrypoint paths must be repository-relative",
        )
        _require(
            (repository_root / path).is_file(),
            f"entrypoint path does not exist: {path.as_posix()}",
        )
        ids.append(row["id"])
    _require(
        ids == _ENTRYPOINT_IDS, "entrypoints must use the approved order and identities"
    )
    _require(
        _contract_digest(rows) == _ENTRYPOINTS_DIGEST,
        "entrypoint contract must match the approved facts",
    )


def _validate_routes(routes: object) -> None:
    rows = _as_list(routes, "routes must be a list")
    _require(len(rows) == len(_ROUTE_KINDS), "routes must contain 19 unique identities")
    paths: list[str] = []
    base_keys = {
        "path",
        "kind",
        "roles",
        "states",
        "not_applicable_states",
        "primary_task",
        "primary_action",
        "information_hierarchy",
        "responsive_contract",
        "role_behavior",
    }
    for route in rows:
        row = _as_object(route, "each route must be an object")
        path = row.get("path")
        _require(
            isinstance(path, str) and path in _ROUTE_KINDS,
            "route identity is not approved",
        )
        path = cast(str, path)
        expected_keys = base_keys | (
            {"redirect_to"} if path in {"/dashboard", "*"} else set()
        )
        _require(
            set(row) == expected_keys, f"route keys are not the closed contract: {path}"
        )
        _require(
            row["kind"] == _ROUTE_KINDS[path], f"route kind is not approved: {path}"
        )
        expected_roles = _ROUTE_ROLES.get(path, _ROLES)
        _require(
            row["roles"] == expected_roles, f"route roles are not approved: {path}"
        )
        states = _as_list(row["states"], f"route states must be a list: {path}")
        _require(
            all(isinstance(state, str) for state in states)
            and len(states) == len(set(states))
            and set(states) <= set(_PAGE_STATES),
            f"route states are invalid: {path}",
        )
        expected_not_applicable = [
            state for state in _PAGE_STATES if state not in states
        ]
        _require(
            row["not_applicable_states"] == expected_not_applicable,
            f"route not_applicable_states must complement states: {path}",
        )
        _require(
            all(
                isinstance(row[name], str) and row[name]
                for name in (
                    "primary_task",
                    "primary_action",
                    "information_hierarchy",
                )
            ),
            f"route content fields must be non-empty: {path}",
        )
        _require(
            row["responsive_contract"] in {"wide", "narrow", "wide+narrow"},
            f"route responsive_contract is invalid: {path}",
        )
        role_behavior = _as_object(
            row["role_behavior"], f"route role_behavior must be an object: {path}"
        )
        _require(
            set(role_behavior) == set(_ROLES)
            and all(
                isinstance(value, str) and value for value in role_behavior.values()
            ),
            f"route role_behavior must cover every role: {path}",
        )
        if path in {"/dashboard", "*"}:
            _require(
                row["redirect_to"] == "/", f"route redirect target is invalid: {path}"
            )
        paths.append(path)
    _require(
        paths == list(_ROUTE_KINDS), "routes must use the approved order and identities"
    )
    _require(
        _contract_digest(rows) == _ROUTES_DIGEST,
        "route contract must match the approved facts",
    )


def _validate_queues(queues: object) -> None:
    rows = _as_list(queues, "queues must be a list")
    names: list[str] = []
    for queue in rows:
        row = _as_object(queue, "each queue must be an object")
        _require(
            set(row)
            == {
                "name",
                "native_states",
                "claim",
                "lease",
                "retry",
                "current_recovery_gap",
            },
            "queue keys are not the closed v1 contract",
        )
        name = row.get("name")
        _require(isinstance(name, str), "queue name must be a string")
        names.append(cast(str, name))
    _require(names == _QUEUE_NAMES, "queues must use the approved order and names")
    _require(
        _contract_digest(rows) == _QUEUES_DIGEST,
        "queue contract must match the approved facts",
    )


def validate_manifest(
    payload: Mapping[str, object], *, repository_root: Path
) -> dict[str, Any]:
    _require(
        set(payload) == _TOP_LEVEL_KEYS,
        "manifest top-level keys are not the closed v1 contract",
    )
    _require(payload["schema_version"] == 1, "schema_version must be 1")
    _require(
        payload["baseline_id"] == "project-optimization-stage-0-v1",
        "baseline_id is not the approved stage 0 identity",
    )
    _require(
        payload["roles"] == _ROLES, "roles must use the approved order and identities"
    )
    _require(
        payload["page_states"] == _PAGE_STATES,
        "page_states must use the approved order and identities",
    )
    _require(
        payload["design_commit"] == "1495fa0751e206c114a0b32626cb9bbf7a66b52e",
        "design_commit is not the approved baseline",
    )
    _require(
        payload["business_baseline_commit"]
        == "8e2fb3478aa0cee3f2bcf1f34a02c16c01848826",
        "business_baseline_commit is not the approved baseline",
    )
    _require(
        payload["non_route_states"] == _NON_ROUTE_STATES,
        "non_route_states must match the approved contract",
    )
    _require(
        payload["quality_profiles"] == _QUALITY_PROFILES,
        "quality_profiles must match the approved contract",
    )
    _require(
        payload["pytest_outcome_policy"] == _PYTEST_OUTCOME_POLICY,
        "pytest_outcome_policy must match the reviewed platform contract",
    )
    _require(
        payload["owner_roles"] == _OWNER_ROLES,
        "owner_roles must match the approved contract",
    )
    _require(
        _contract_digest(payload["mysql_hosted_exclusions"])
        == _MYSQL_HOSTED_EXCLUSIONS_DIGEST,
        "mysql_hosted_exclusions must match the approved contract",
    )
    result = dict(payload)
    timing = _as_object(
        result["timing_candidate"], "timing_candidate must be an object"
    )
    required_timing_keys = {
        "heartbeat_seconds",
        "stale_seconds",
        "offline_seconds",
        "refresh_seconds",
        "offline_visible_seconds",
        "approval_status",
    }
    h, s, o, r = (
        timing[name]
        for name in (
            "heartbeat_seconds",
            "stale_seconds",
            "offline_seconds",
            "refresh_seconds",
        )
    )
    _require(
        all(
            isinstance(value, int) and not isinstance(value, bool) and value > 0
            for value in (h, s, o, r)
        ),
        "timing values must be positive integers",
    )
    _require(s >= 3 * h, "stale_seconds must be at least 3 * heartbeat_seconds")
    _require(o > s, "offline_seconds must be greater than stale_seconds")
    _require(
        timing["offline_visible_seconds"] == o + r,
        "offline_visible_seconds must equal offline_seconds + refresh_seconds",
    )
    _require(
        set(timing) == required_timing_keys,
        "timing_candidate keys are not the closed v1 contract",
    )
    _validate_entrypoints(result["entrypoints"], repository_root)
    _validate_routes(result["routes"])
    _validate_queues(result["queues"])
    _require(
        result["performance_protocol"] == _PERFORMANCE_PROTOCOL,
        "performance_protocol is not the approved contract",
    )
    _require(
        result["performance_scenarios"] == _PERFORMANCE_SCENARIOS,
        "performance_scenarios are not the approved contract",
    )
    _require(
        result["mysql_matrix_scenarios"] == _MYSQL_MATRIX_SCENARIOS,
        "MySQL matrix scenarios are not the approved contract",
    )
    _require(
        result["required_external_evidence"]
        == ["analytics_scale_v1:mysql:8.0", "analytics_scale_v1:mysql:8.4"],
        "both analytics_scale_v1 identities are required",
    )
    return result


def load_manifest(path: Path, *, repository_root: Path) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise BaselineContractError(f"manifest could not be read: {error}") from error
    if not isinstance(payload, dict):
        raise BaselineContractError("manifest root must be an object")
    return validate_manifest(payload, repository_root=repository_root.resolve())


def resolve_empty_external_root(raw_path: str, *, repository_root: Path) -> Path:
    root = Path(raw_path).expanduser().resolve()
    repository = repository_root.resolve()
    if root == repository or repository in root.parents:
        raise BaselineContractError("evidence root must be outside the repository")
    try:
        root.mkdir(parents=True, exist_ok=True)
        if not root.is_dir():
            raise BaselineContractError("evidence root must be a directory")
        if any(root.iterdir()):
            raise BaselineContractError("evidence root must be empty")
    except BaselineContractError:
        raise
    except OSError as error:
        raise BaselineContractError("evidence root is unavailable") from error
    return root


def create_run_directory(evidence_root: Path, *, run_id: str) -> Path:
    if not re.fullmatch(r"stage0-[0-9a-f]{12}", run_id):
        raise BaselineContractError("run_id must match stage0-[0-9a-f]{12}")
    root = evidence_root.resolve(strict=True)
    if not root.is_dir():
        raise BaselineContractError("evidence root must be a directory")
    repository = REPOSITORY_ROOT.resolve()
    if root == repository or repository in root.parents:
        raise BaselineContractError("evidence root must be outside the repository")
    run = root / run_id
    run.mkdir(mode=0o700, parents=False, exist_ok=False)
    return run


def percentile(samples: Sequence[float], percentile_value: float) -> float:
    values = _finite_float_samples(
        samples, message="percentile input is invalid", require_non_negative=False
    )
    try:
        checked_percentile = float(percentile_value)
    except (TypeError, ValueError, OverflowError) as error:
        raise BaselineContractError("percentile input is invalid") from error
    if (
        not values
        or isinstance(percentile_value, bool)
        or not math.isfinite(checked_percentile)
        or not 0 < checked_percentile <= 100
    ):
        raise BaselineContractError("percentile input is invalid")
    ordered = sorted(values)
    rank = max(1, math.ceil(checked_percentile / 100 * len(ordered)))
    return ordered[rank - 1]


def _finite_float_samples(
    samples: Sequence[float],
    *,
    message: str,
    require_non_negative: bool,
) -> list[float]:
    values: list[float] = []
    try:
        for value in samples:
            if isinstance(value, bool) or not isinstance(value, (int, float)):
                raise TypeError
            checked = float(value)
            if not math.isfinite(checked) or (require_non_negative and checked < 0):
                raise ValueError
            values.append(checked)
    except (TypeError, ValueError, OverflowError) as error:
        raise BaselineContractError(message) from error
    return values


def summarize_round(samples: Sequence[float]) -> dict[str, object]:
    values = _finite_float_samples(
        samples,
        message="each round requires 20 finite non-negative samples",
        require_non_negative=True,
    )
    if len(values) != 20:
        raise BaselineContractError(
            "each round requires 20 finite non-negative samples"
        )
    return {
        "sample_count": 20,
        "samples": values,
        "p50": statistics.median(values),
        "p95": percentile(values, 95),
        "max": max(values),
    }


def summarize_scenario(
    rounds: Sequence[Mapping[str, object]],
) -> dict[str, object]:
    if len(rounds) != 3:
        raise BaselineContractError("scenario requires exactly 3 rounds")
    checked_rounds: list[Mapping[str, object]] = []
    p95s: list[float] = []
    for round_ in rounds:
        samples = round_.get("samples")
        if not isinstance(samples, list):
            raise BaselineContractError("round samples must be a list")
        expected = summarize_round(cast(list[float], samples))
        if any(round_.get(name) != expected[name] for name in expected):
            raise BaselineContractError("round summary does not match its samples")
        checked_rounds.append(round_)
        p95s.append(cast(float, expected["p95"]))
    median_p95 = statistics.median(p95s)
    return {
        "rounds": list(checked_rounds),
        "median_round_p95": median_p95,
        "min_round_p95": min(p95s),
        "max_round_p95": max(p95s),
        "relative_p95_spread": (
            (max(p95s) - min(p95s)) / median_p95 if median_p95 else 0.0
        ),
    }


def _checked_output(command: Sequence[str], cwd: Path) -> str:
    return subprocess.run(
        command,
        cwd=cwd,
        check=True,
        capture_output=True,
        text=True,
        encoding="utf-8",
    ).stdout.strip()


def capture_environment(
    *, repository_root: Path, mysql_version: str
) -> dict[str, object]:
    return {
        "source_sha": _checked_output(["git", "rev-parse", "HEAD"], repository_root),
        "git_tree": _checked_output(
            ["git", "rev-parse", "HEAD^{tree}"], repository_root
        ),
        "python": sys.version.split()[0],
        "node": _checked_output(["node", "--version"], repository_root),
        "pnpm": _checked_output([_pnpm_command(), "--version"], repository_root),
        "playwright_chromium": "1.62.1",
        "mysql": mysql_version,
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


def _physical_memory_bytes() -> int:
    if os.name == "nt":
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
            raise BaselineContractError("physical memory fingerprint is unavailable")
        return int(status.total_physical)
    sysconf = os.sysconf  # type: ignore[attr-defined]
    page_size = int(sysconf("SC_PAGE_SIZE"))
    page_count = int(sysconf("SC_PHYS_PAGES"))
    return page_size * page_count


def write_json_exclusive(path: Path, payload: Mapping[str, object]) -> None:
    encoded = (
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    ).encode("utf-8")
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    try:
        with os.fdopen(descriptor, "wb") as stream:
            descriptor = -1
            stream.write(encoded)
            stream.flush()
            os.fsync(stream.fileno())
    finally:
        if descriptor != -1:
            os.close(descriptor)


def _read_json_object(path: Path, *, label: str) -> dict[str, Any]:
    if path.is_symlink():
        raise BaselineContractError(f"{label} must not be a symbolic link")
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise BaselineContractError(f"{label} could not be read") from error
    if not isinstance(payload, dict):
        raise BaselineContractError(f"{label} must be a JSON object")
    return payload


def _require_source_sha(source_sha: str) -> None:
    if not re.fullmatch(r"[0-9a-f]{40}", source_sha):
        raise BaselineContractError("source_sha must be 40 lowercase hex characters")


def _release_source_identity(source_sha: str) -> dict[str, str]:
    _require_source_sha(source_sha)
    head = _checked_output(["git", "rev-parse", "HEAD"], REPOSITORY_ROOT)
    if head != source_sha:
        raise BaselineContractError("source_sha does not match checkout HEAD")
    git_tree = _checked_output(
        ["git", "rev-parse", f"{source_sha}^{{tree}}"], REPOSITORY_ROOT
    )
    tree_listing = subprocess.run(
        ["git", "ls-tree", "-r", "--full-tree", source_sha],
        cwd=REPOSITORY_ROOT,
        check=True,
        capture_output=True,
    ).stdout.replace(b"\r\n", b"\n")
    if tree_listing and not tree_listing.endswith(b"\n"):
        tree_listing += b"\n"
    return {
        "source_sha": source_sha,
        "git_tree": git_tree,
        "artifact_digest": hashlib.sha256(tree_listing).hexdigest(),
        "runner_digest": _release_runner_digest(
            source_sha, "project-optimization-baseline"
        ),
    }


def _release_runner_digest(source_sha: str, suite_name: str) -> str:
    _require_source_sha(source_sha)
    _require(
        suite_name in {"performance", "project-optimization-baseline"},
        "release runner suite identity is invalid",
    )
    manifest = _read_json_object(
        REPOSITORY_ROOT / "scripts" / "ci-suite-manifest.json",
        label="CI suite manifest",
    )
    release_suites = _as_object(
        manifest.get("release_suites"), "release_suites must be an object"
    )
    suite = _as_object(
        release_suites.get(suite_name),
        f"{suite_name} suite must be an object",
    )
    runner_paths = _as_list(
        suite.get("runner_paths"),
        f"{suite_name} runner paths must be a list",
    )
    _require(bool(runner_paths), f"{suite_name} runner paths must not be empty")
    runner_lines: list[str] = []
    for value in runner_paths:
        _require(
            isinstance(value, str) and bool(value),
            f"{suite_name} runner path is invalid",
        )
        blob = _checked_output(
            ["git", "rev-parse", f"{source_sha}:{value}"], REPOSITORY_ROOT
        )
        _require(
            re.fullmatch(r"[0-9a-f]{40}", blob) is not None,
            f"{suite_name} runner identity is invalid",
        )
        runner_lines.append(f"{value}\0{blob}")
    runner_payload = ("\n".join(sorted(runner_lines)) + "\n").encode("utf-8")
    return hashlib.sha256(runner_payload).hexdigest()


_HOST_IDENTITY_FIELDS = (
    "python",
    "node",
    "pnpm",
    "playwright_chromium",
    "os",
    "machine",
    "processor",
    "cpu_count",
    "memory_bytes",
    "fixture_ids",
)
_TIMING_TRIALS = {
    "heartbeat-single-row-update",
    "heartbeat-long-task",
    "heartbeat-maintenance-barrier",
}
_QUEUE_SCENARIOS = (
    "queue-publication-outbox-query",
    "queue-return-dedup-query",
    "queue-catalog-import-query",
    "queue-catalog-export-query",
)
_COMMAND_RESULT_IDENTITIES = (
    ("01-ubuntu-full", "ubuntu-full", True),
    ("02-windows-smoke", "windows-smoke", True),
    ("03-frontend-full", "frontend-full", True),
    ("04-mysql-compatibility-8-0", "mysql-compatibility-8-0", True),
    ("05-mysql-compatibility-8-4", "mysql-compatibility-8-4", True),
    ("06-generated-contract", "generated-contract", False),
    ("07-product-catalog-evidence", "product-catalog-evidence", False),
    ("08-stage0-backend-8-0", "stage0-backend-8-0", True),
    ("09-stage0-backend-8-4", "stage0-backend-8-4", True),
    ("10-stage0-ui", "stage0-ui", False),
    ("11-stage0-bundle", "stage0-bundle", False),
)
_COMMAND_RESULT_KEYS = {
    "schema_version",
    "command_id",
    "started_at",
    "ended_at",
    "exit_code",
    "skip_count",
    "explained_skip_count",
    "unexplained_skip_count",
    "xfail_count",
    "retry_count",
    "flaky_count",
    "stdout_sha256",
    "stderr_sha256",
    "profile_node_digest",
    "pytest_outcome_evidence",
}
_PYTEST_OUTCOME_COMMANDS = {
    "ubuntu-full",
    "windows-smoke",
    "mysql-compatibility-8-0",
    "mysql-compatibility-8-4",
    "stage0-backend-8-0",
    "stage0-backend-8-4",
}


def _host_identity(environment: Mapping[str, object]) -> dict[str, object]:
    missing = [name for name in _HOST_IDENTITY_FIELDS if name not in environment]
    if missing:
        raise BaselineContractError("host environment identity is incomplete")
    host = {name: environment[name] for name in _HOST_IDENTITY_FIELDS}
    host["host_environment_digest"] = _contract_digest(host)
    return host


def _pnpm_command() -> str:
    return "pnpm.cmd" if sys.platform == "win32" else "pnpm"


def _validate_external_evidence(
    path: Path,
    *,
    mysql_version: str,
    source_identity: Mapping[str, str],
    product_runner_digest: str,
) -> tuple[str, dict[str, object]]:
    if path.is_symlink():
        raise BaselineContractError("external evidence must not be a symbolic link")
    try:
        resolved = path.resolve(strict=True)
        encoded = resolved.read_bytes()
        payload = json.loads(encoded.decode("utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as error:
        raise BaselineContractError("external evidence could not be read") from error
    repository = REPOSITORY_ROOT.resolve()
    _require(
        resolved != repository and repository not in resolved.parents,
        "external evidence must be outside the repository",
    )
    _require(isinstance(payload, dict), "external evidence must be a JSON object")
    _require(
        payload.get("fixture") == "analytics_scale_v1"
        and payload.get("mysql_version") == mysql_version
        and payload.get("warmup_samples") == 3
        and payload.get("measured_samples") == 20
        and payload.get("cpu_count") == 4
        and payload.get("memory_bytes") == 8 * 1024**3,
        f"MySQL {mysql_version} analytics_scale_v1 evidence identity is invalid",
    )
    for field in ("source_sha", "git_tree", "artifact_digest"):
        _require(
            payload.get(field) == source_identity[field],
            f"MySQL {mysql_version} analytics_scale_v1 identity is invalid",
        )
    _require(
        payload.get("runner_digest") == product_runner_digest,
        f"MySQL {mysql_version} analytics_scale_v1 product runner identity is invalid",
    )
    digest = hashlib.sha256(encoded).hexdigest()
    return (
        f"analytics_scale_v1:mysql:{mysql_version}",
        {
            "sha256": digest,
            "source_sha": source_identity["source_sha"],
            "git_tree": source_identity["git_tree"],
            "artifact_digest": source_identity["artifact_digest"],
            "runner_digest": product_runner_digest,
            "stage0_runner_digest": source_identity["runner_digest"],
            "cpu_count": 4,
            "memory_bytes": 8 * 1024**3,
        },
    )


def _utc_timestamp(value: object) -> datetime:
    if not isinstance(value, str):
        raise BaselineContractError("command result timestamp is invalid")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as error:
        raise BaselineContractError("command result timestamp is invalid") from error
    _require(
        parsed.tzinfo is not None and parsed.utcoffset() == UTC.utcoffset(parsed),
        "command result timestamp is invalid",
    )
    return parsed


def pytest_outcome_binding(
    *,
    source_sha: str,
    command_id: str,
    profile: str,
    profile_node_digest: str | None,
    shard_node_digests: Mapping[str, str],
    platform_id: str,
) -> str:
    _require_source_sha(source_sha)
    _require(
        isinstance(command_id, str)
        and command_id in _PYTEST_OUTCOME_POLICY["commands"],
        "pytest outcome command identity is invalid",
    )
    command_policy = cast(
        dict[str, Any], _PYTEST_OUTCOME_POLICY["commands"][command_id]
    )
    _require(command_policy["profile"] == profile, "pytest outcome profile is invalid")
    _require(platform_id in {"win32", "linux", "darwin"}, "platform is invalid")
    _require(
        isinstance(profile_node_digest, str)
        and re.fullmatch(r"[0-9a-f]{64}", profile_node_digest) is not None,
        "pytest outcome profile node digest is required and invalid",
    )
    expected_shards = cast(list[str], command_policy["report_shards"])
    _require(
        set(shard_node_digests) == set(expected_shards)
        and all(
            isinstance(value, str) and re.fullmatch(r"[0-9a-f]{64}", value) is not None
            for value in shard_node_digests.values()
        ),
        "pytest outcome shard node digests are invalid",
    )
    return _contract_digest(
        {
            "schema_version": 2,
            "source_sha": source_sha,
            "command_id": command_id,
            "profile": profile,
            "profile_node_digest": profile_node_digest,
            "shard_node_digests": {
                shard: shard_node_digests[shard] for shard in sorted(expected_shards)
            },
            "platform_id": platform_id,
        }
    )


def _pytest_node_digest(nodeids: Sequence[str]) -> str:
    encoded = (("\n".join(sorted(nodeids))) + "\n").encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _skip_matches_entry(
    *, nodeid: str, reason: str, entry: Mapping[str, object]
) -> bool:
    if entry.get("nodeid") != nodeid:
        return False
    approved_reason = entry.get("reason")
    match = entry.get("match")
    if not isinstance(approved_reason, str):
        return False
    return (match == "exact" and reason == approved_reason) or (
        match == "prefix" and reason.startswith(approved_reason)
    )


def _skip_is_reviewed(
    *, nodeid: str, reason: str, allowlist: Sequence[Mapping[str, object]]
) -> bool:
    for entry in allowlist:
        if entry.get("nodeid") != nodeid:
            continue
        if not isinstance(entry.get("reason"), str):
            return False
        if _skip_matches_entry(nodeid=nodeid, reason=reason, entry=entry):
            return True
    return False


def _required_skips_are_present(
    *,
    skips: Sequence[Mapping[str, object]],
    allowlist: Sequence[Mapping[str, object]],
) -> bool:
    return all(
        any(
            isinstance(skip.get("nodeid"), str)
            and isinstance(skip.get("reason"), str)
            and _skip_matches_entry(
                nodeid=cast(str, skip["nodeid"]),
                reason=cast(str, skip["reason"]),
                entry=entry,
            )
            for skip in skips
        )
        for entry in allowlist
        if entry.get("required") is True
    )


def validate_pytest_outcome_reports(
    report_directory: Path,
    *,
    manifest: Mapping[str, object],
    source_sha: str,
    command_id: str,
    profile: str,
    profile_node_digest: str | None,
    shard_node_digests: Mapping[str, str],
    platform_id: str,
) -> dict[str, object]:
    policy = _as_object(
        manifest.get("pytest_outcome_policy"),
        "pytest_outcome_policy must be an object",
    )
    commands = _as_object(policy.get("commands"), "pytest outcome commands are invalid")
    command_policy = _as_object(
        commands.get(command_id), "pytest outcome command identity is invalid"
    )
    _require(
        command_policy.get("profile") == profile, "pytest outcome profile is invalid"
    )
    platform_allowlists = _as_object(
        command_policy.get("skip_allowlist"), "pytest skip allowlists are invalid"
    )
    allowlist = _as_list(
        platform_allowlists.get(platform_id),
        "pytest skip allowlist platform is invalid",
    )
    expected_shards = cast(
        list[str],
        _as_list(
            command_policy.get("report_shards"), "pytest report shards are invalid"
        ),
    )
    _require(
        isinstance(profile_node_digest, str)
        and re.fullmatch(r"[0-9a-f]{64}", profile_node_digest) is not None,
        "pytest outcome profile node digest is required and invalid",
    )
    _require(
        set(shard_node_digests) == set(expected_shards)
        and all(
            isinstance(value, str) and re.fullmatch(r"[0-9a-f]{64}", value) is not None
            for value in shard_node_digests.values()
        ),
        "pytest outcome shard node digests are invalid",
    )
    binding = pytest_outcome_binding(
        source_sha=source_sha,
        command_id=command_id,
        profile=profile,
        profile_node_digest=profile_node_digest,
        shard_node_digests=shard_node_digests,
        platform_id=platform_id,
    )
    repository = REPOSITORY_ROOT.resolve()
    try:
        report_root = report_directory.resolve(strict=True)
    except OSError as error:
        raise BaselineContractError("pytest report identity is missing") from error
    _require(
        report_root.is_dir()
        and not report_directory.is_symlink()
        and report_root != repository
        and repository not in report_root.parents,
        "pytest report directory must be external and real",
    )
    expected_files = {f"{shard}.json" for shard in expected_shards}
    entries = list(report_root.iterdir())
    _require(
        {path.name for path in entries} == expected_files
        and all(path.is_file() and not path.is_symlink() for path in entries),
        "pytest report identity set is incomplete or invalid",
    )
    report_digests: dict[str, str] = {}
    all_collected: list[str] = []
    all_outcomes: list[dict[str, str]] = []
    session_exit_codes: dict[str, int] = {}
    for shard in expected_shards:
        path = report_root / f"{shard}.json"
        try:
            encoded = path.read_bytes()
            payload = json.loads(encoded.decode("utf-8"))
        except (OSError, UnicodeDecodeError, json.JSONDecodeError) as error:
            raise BaselineContractError(
                "pytest outcome report could not be read"
            ) from error
        report = _as_object(payload, "pytest outcome report must be an object")
        _require(
            set(report)
            == {
                "schema_version",
                "binding_sha256",
                "shard_id",
                "expected_node_digest",
                "session_exit_code",
                "private_environment_clear",
                "collected_nodeids",
                "outcomes",
            }
            and report.get("schema_version") == 2
            and report.get("binding_sha256") == binding
            and report.get("shard_id") == shard,
            "pytest outcome report schema or binding is invalid",
        )
        _require(
            report.get("expected_node_digest") == shard_node_digests[shard],
            "pytest outcome shard identity is invalid",
        )
        _require(
            report.get("private_environment_clear") is True,
            "pytest process inherited private canary configuration",
        )
        exit_code = report.get("session_exit_code")
        _require(
            isinstance(exit_code, int) and not isinstance(exit_code, bool),
            "pytest session exit code is invalid",
        )
        session_exit_codes[shard] = cast(int, exit_code)
        collected = _as_list(
            report.get("collected_nodeids"), "pytest collected nodes are invalid"
        )
        _require(
            all(
                isinstance(nodeid, str)
                and re.fullmatch(r"backend/tests/.+::.+", nodeid) is not None
                for nodeid in collected
            )
            and collected == sorted(collected)
            and len(collected) == len(set(collected)),
            "pytest collected nodes are invalid or duplicate",
        )
        _require(
            bool(collected)
            and _pytest_node_digest(cast(list[str], collected))
            == shard_node_digests[shard],
            "pytest collected nodes do not match the expected shard identity",
        )
        outcomes = _as_list(report.get("outcomes"), "pytest outcomes are invalid")
        normalized: list[dict[str, str]] = []
        for raw_outcome in outcomes:
            outcome = _as_object(raw_outcome, "pytest outcome row is invalid")
            _require(
                set(outcome) == {"nodeid", "status", "reason"}
                and isinstance(outcome.get("nodeid"), str)
                and isinstance(outcome.get("status"), str)
                and isinstance(outcome.get("reason"), str),
                "pytest outcome row is invalid",
            )
            normalized.append(cast(dict[str, str], outcome))
        outcome_nodes = [row["nodeid"] for row in normalized]
        _require(
            len(outcome_nodes) == len(set(outcome_nodes))
            and set(outcome_nodes) == set(cast(list[str], collected)),
            "pytest outcome node identity is missing or duplicate",
        )
        all_collected.extend(cast(list[str], collected))
        all_outcomes.extend(normalized)
        report_digests[path.name] = hashlib.sha256(encoded).hexdigest()
    _require(
        len(all_collected) == len(set(all_collected)),
        "pytest report shards contain duplicate node identities",
    )
    collected_digest = _pytest_node_digest(all_collected)
    _require(
        collected_digest == profile_node_digest,
        "pytest collected nodes do not match the profile identity",
    )
    skips: list[dict[str, str]] = []
    adverse = {"xfail": 0, "xpass": 0, "rerun": 0, "flaky": 0}
    for outcome in all_outcomes:
        status = outcome["status"]
        _require(
            status in {"passed", "failed", "error", "skipped", *adverse.keys()},
            "pytest outcome status is invalid",
        )
        if status == "skipped":
            _require(
                _skip_is_reviewed(
                    nodeid=outcome["nodeid"],
                    reason=outcome["reason"],
                    allowlist=cast(list[Mapping[str, object]], allowlist),
                ),
                "pytest skip allowlist rejected a node or reason",
            )
            skips.append(outcome)
        elif status in adverse:
            adverse[status] += 1
        elif status in {"failed", "error"}:
            raise BaselineContractError("pytest report contains failed test outcomes")
        else:
            _require(outcome["reason"] == "", "passed pytest outcome has a reason")
    if any(adverse.values()):
        raise BaselineContractError("pytest report contains an adverse pytest outcome")
    _require(
        _required_skips_are_present(
            skips=skips,
            allowlist=cast(list[Mapping[str, object]], allowlist),
        ),
        "pytest required skip is missing",
    )
    _require(
        all(value == 0 for value in session_exit_codes.values()),
        "pytest session exit code is nonzero",
    )
    return {
        "status": "valid",
        "binding_sha256": binding,
        "platform_id": platform_id,
        "profile": profile,
        "collected_node_count": len(all_collected),
        "collected_node_digest": collected_digest,
        "shard_node_digests": dict(sorted(shard_node_digests.items())),
        "report_digests": report_digests,
        "session_exit_codes": session_exit_codes,
        "private_environment_clear": True,
        "skip_count": len(skips),
        "explained_skip_count": len(skips),
        "unexplained_skip_count": 0,
        "xfail_count": 0,
        "retry_count": 0,
        "flaky_count": 0,
        "skips": sorted(skips, key=lambda row: row["nodeid"]),
    }


def _command_results(
    run_directory: Path,
    *,
    source_sha: str,
) -> tuple[list[dict[str, object]], dict[str, int]]:
    rows: list[dict[str, object]] = []
    counts = {
        "skip_count": 0,
        "explained_skip_count": 0,
        "unexplained_skip_count": 0,
        "xfail_count": 0,
        "retry_count": 0,
        "flaky_count": 0,
    }
    expected = {
        f"command-result-{file_id}.json": (command_id, profile_digest)
        for file_id, command_id, profile_digest in _COMMAND_RESULT_IDENTITIES
    }
    paths = {path.name: path for path in run_directory.glob("command-result-*.json")}
    _require(
        set(paths) == set(expected),
        "command result identity set is incomplete or invalid",
    )
    for file_name in sorted(expected):
        path = paths[file_name]
        if path.is_symlink():
            raise BaselineContractError("command result must not be a symbolic link")
        try:
            encoded = path.read_bytes()
            payload = json.loads(encoded.decode("utf-8"))
        except (OSError, UnicodeDecodeError, json.JSONDecodeError) as error:
            raise BaselineContractError("command result could not be read") from error
        if not isinstance(payload, dict):
            raise BaselineContractError("command result must be a JSON object")
        command_id, requires_profile_digest = expected[file_name]
        _require(
            set(payload) == _COMMAND_RESULT_KEYS
            and payload.get("schema_version") == 2
            and payload.get("command_id") == command_id
            and payload.get("exit_code") == 0,
            "command result schema or identity is invalid",
        )
        started_at = _utc_timestamp(payload.get("started_at"))
        ended_at = _utc_timestamp(payload.get("ended_at"))
        _require(started_at <= ended_at, "command result timestamp is invalid")
        for digest_name in ("stdout_sha256", "stderr_sha256"):
            _require(
                isinstance(payload.get(digest_name), str)
                and re.fullmatch(r"[0-9a-f]{64}", cast(str, payload[digest_name]))
                is not None,
                "command result stream digest is invalid",
            )
        profile_digest = payload.get("profile_node_digest")
        _require(
            (
                requires_profile_digest
                and isinstance(profile_digest, str)
                and re.fullmatch(r"[0-9a-f]{64}", profile_digest) is not None
            )
            or (not requires_profile_digest and profile_digest is None),
            "command result profile identity is invalid",
        )
        outcome_evidence = payload.get("pytest_outcome_evidence")
        if command_id in _PYTEST_OUTCOME_COMMANDS:
            outcome = _as_object(
                outcome_evidence, "pytest command outcome evidence is invalid"
            )
            policy = cast(
                dict[str, Any], _PYTEST_OUTCOME_POLICY["commands"][command_id]
            )
            expected_shards = cast(list[str], policy["report_shards"])
            _require(
                set(outcome)
                == {
                    "status",
                    "binding_sha256",
                    "platform_id",
                    "profile",
                    "collected_node_count",
                    "collected_node_digest",
                    "shard_node_digests",
                    "report_digests",
                    "session_exit_codes",
                    "private_environment_clear",
                    "skip_count",
                    "explained_skip_count",
                    "unexplained_skip_count",
                    "xfail_count",
                    "retry_count",
                    "flaky_count",
                    "skips",
                }
                and outcome.get("status") == "valid"
                and outcome.get("profile") == policy["profile"]
                and outcome.get("platform_id") in {"win32", "linux", "darwin"}
                and outcome.get("private_environment_clear") is True,
                "pytest command outcome schema or profile is invalid",
            )
            platform_id = cast(str, outcome["platform_id"])
            shard_node_digests = _as_object(
                outcome.get("shard_node_digests"),
                "pytest shard node digests are invalid",
            )
            _require(
                set(shard_node_digests) == set(expected_shards)
                and all(
                    isinstance(value, str)
                    and re.fullmatch(r"[0-9a-f]{64}", value) is not None
                    for value in shard_node_digests.values()
                ),
                "pytest shard node digests are invalid",
            )
            expected_binding = pytest_outcome_binding(
                source_sha=source_sha,
                command_id=command_id,
                profile=cast(str, policy["profile"]),
                profile_node_digest=cast(str, profile_digest),
                shard_node_digests=cast(dict[str, str], shard_node_digests),
                platform_id=platform_id,
            )
            _require(
                outcome.get("binding_sha256") == expected_binding,
                "pytest command outcome source binding is invalid",
            )
            collected_count = outcome.get("collected_node_count")
            collected_digest = outcome.get("collected_node_digest")
            _require(
                isinstance(collected_count, int)
                and not isinstance(collected_count, bool)
                and collected_count > 0
                and isinstance(collected_digest, str)
                and re.fullmatch(r"[0-9a-f]{64}", collected_digest) is not None
                and collected_digest == profile_digest,
                "pytest command collected identity is invalid",
            )
            report_digests = _as_object(
                outcome.get("report_digests"), "pytest report digests are invalid"
            )
            _require(
                set(report_digests) == {f"{shard}.json" for shard in expected_shards}
                and all(
                    isinstance(value, str)
                    and re.fullmatch(r"[0-9a-f]{64}", value) is not None
                    for value in report_digests.values()
                ),
                "pytest report digests are invalid",
            )
            session_exit_codes = _as_object(
                outcome.get("session_exit_codes"), "pytest session exits are invalid"
            )
            _require(
                set(session_exit_codes) == set(expected_shards)
                and all(value == 0 for value in session_exit_codes.values()),
                "pytest session exits are invalid",
            )
            skips = _as_list(outcome.get("skips"), "pytest skips are invalid")
            platform_policies = cast(
                dict[str, list[Mapping[str, object]]], policy["skip_allowlist"]
            )
            allowlist = platform_policies[platform_id]
            skip_nodeids: list[str] = []
            for skip in skips:
                row_skip = _as_object(skip, "pytest skip row is invalid")
                _require(
                    set(row_skip) == {"nodeid", "status", "reason"}
                    and row_skip.get("status") == "skipped"
                    and isinstance(row_skip.get("nodeid"), str)
                    and isinstance(row_skip.get("reason"), str)
                    and _skip_is_reviewed(
                        nodeid=cast(str, row_skip["nodeid"]),
                        reason=cast(str, row_skip["reason"]),
                        allowlist=allowlist,
                    ),
                    "pytest skip evidence is invalid",
                )
                skip_nodeids.append(cast(str, row_skip["nodeid"]))
            _require(
                len(skip_nodeids) == len(set(skip_nodeids)),
                "pytest skip evidence contains duplicate node identities",
            )
            _require(
                _required_skips_are_present(
                    skips=cast(list[Mapping[str, object]], skips),
                    allowlist=allowlist,
                ),
                "pytest required skip evidence is missing",
            )
            _require(
                outcome.get("skip_count") == len(skips)
                and outcome.get("explained_skip_count") == len(skips)
                and outcome.get("unexplained_skip_count") == 0
                and outcome.get("xfail_count") == 0
                and outcome.get("retry_count") == 0
                and outcome.get("flaky_count") == 0,
                "pytest outcome counts are invalid",
            )
        else:
            _require(
                outcome_evidence is None,
                "non-pytest command has pytest outcome evidence",
            )
        row: dict[str, object] = {
            "file_name": path.name,
            "command_id": command_id,
            "result_digest": hashlib.sha256(encoded).hexdigest(),
        }
        for name in counts:
            value = payload.get(name, 0)
            _require(
                isinstance(value, int) and not isinstance(value, bool) and value >= 0,
                "command result counts are invalid",
            )
            counts[name] += value
            row[name] = value
        skip_count = cast(int, payload["skip_count"])
        explained_skip_count = cast(int, payload["explained_skip_count"])
        unexplained_skip_count = cast(int, payload["unexplained_skip_count"])
        _require(
            skip_count == explained_skip_count + unexplained_skip_count,
            "command result skip accounting is invalid",
        )
        if command_id in _PYTEST_OUTCOME_COMMANDS:
            outcome = cast(dict[str, object], outcome_evidence)
            _require(
                all(payload.get(name) == outcome.get(name) for name in counts),
                "command result does not match pytest outcome evidence",
            )
        else:
            _require(
                all(payload.get(name) == 0 for name in counts),
                "non-pytest command has test outcome counts",
            )
        rows.append(row)
    return rows, counts


def publish_command_results(
    staging_directory: Path, run_directory: Path
) -> dict[str, object]:
    staging = staging_directory.resolve(strict=True)
    run = run_directory.resolve(strict=True)
    repository = REPOSITORY_ROOT.resolve()
    _require(
        staging != run
        and staging.parent == run.parent
        and repository not in staging.parents
        and repository not in run.parents
        and not staging_directory.is_symlink()
        and not run_directory.is_symlink(),
        "command result staging and run directories are invalid",
    )
    identity = _read_json_object(run / "run-identity.json", label="run identity")
    _require(
        identity.get("run_id") == run.name and identity.get("status") == "prepared",
        "prepared run identity is invalid",
    )
    expected_names = {
        f"command-result-{file_id}.json" for file_id, _, _ in _COMMAND_RESULT_IDENTITIES
    }
    entries = list(staging.iterdir())
    _require(
        {path.name for path in entries} == expected_names
        and all(path.is_file() and not path.is_symlink() for path in entries),
        "command result staging set is incomplete or invalid",
    )
    source_sha_value = identity.get("source_sha")
    _require(
        isinstance(source_sha_value, str), "prepared run source identity is invalid"
    )
    source_sha = cast(str, source_sha_value)
    _command_results(staging, source_sha=source_sha)
    _require(
        not any(run.glob("command-result-*.json")),
        "prepared run already contains command results",
    )
    created: list[Path] = []
    try:
        for name in sorted(expected_names):
            source = staging / name
            destination = run / name
            descriptor = os.open(
                destination, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600
            )
            created.append(destination)
            try:
                with os.fdopen(descriptor, "wb") as stream:
                    descriptor = -1
                    stream.write(source.read_bytes())
                    stream.flush()
                    os.fsync(stream.fileno())
            finally:
                if descriptor != -1:
                    os.close(descriptor)
        _command_results(run, source_sha=source_sha)
    except Exception:
        for path in created:
            path.unlink(missing_ok=True)
        raise
    for path in entries:
        path.unlink()
    staging.rmdir()
    return {"published": True, "command_results": sorted(expected_names)}


def _has_unbounded_cartesian_join(plan: object) -> bool:
    if isinstance(plan, dict):
        nested_loop = plan.get("nested_loop")
        if isinstance(nested_loop, list) and len(nested_loop) > 1:
            tables = [
                row.get("table")
                for row in nested_loop
                if isinstance(row, dict) and isinstance(row.get("table"), dict)
            ]
            if len(tables) > 1 and all(
                "key" not in table and "ref" not in table
                for table in cast(list[dict[str, object]], tables)
            ):
                return True
        return any(_has_unbounded_cartesian_join(value) for value in plan.values())
    if isinstance(plan, list):
        return any(_has_unbounded_cartesian_join(value) for value in plan)
    return False


def _raw_explain_digests(
    run_directory: Path,
    *,
    scenario_evidence: Sequence[tuple[Path, dict[str, Any], str]],
    source_sha: str,
    source_identity: Mapping[str, object],
) -> dict[str, str]:
    expected = {
        f"external-explain-{version}-{scenario_id}.json": (version, scenario_id)
        for version in ("8.0", "8.4")
        for scenario_id in _QUEUE_SCENARIOS
    }
    paths = {path.name: path for path in run_directory.glob("external-explain-*.json")}
    _require(
        set(paths) == set(expected),
        "raw EXPLAIN evidence set is incomplete or invalid",
    )
    scenarios = {
        (
            cast(str, payload.get("mysql_version")),
            cast(str, payload.get("scenario_id")),
        ): payload
        for _, payload, _ in scenario_evidence
    }
    digests: dict[str, str] = {}
    required_keys = {
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
    for file_name in sorted(expected):
        path = paths[file_name]
        _require(not path.is_symlink(), "raw EXPLAIN must not be a symbolic link")
        try:
            encoded = path.read_bytes()
            payload = json.loads(encoded.decode("utf-8"))
        except (OSError, UnicodeDecodeError, json.JSONDecodeError) as error:
            raise BaselineContractError(
                "raw EXPLAIN evidence could not be read"
            ) from error
        version, scenario_id = expected[file_name]
        scenario = scenarios.get((version, scenario_id))
        _require(
            isinstance(payload, dict)
            and set(payload) == required_keys
            and payload.get("schema_version") == 1
            and payload.get("source_sha") == source_sha
            and payload.get("git_tree") == source_identity.get("git_tree")
            and payload.get("runner_digest") == source_identity.get("runner_digest")
            and payload.get("fixture_id") == "stage0-worker-synthetic-v1"
            and payload.get("mysql_version") == version
            and payload.get("scenario_id") == scenario_id
            and payload.get("format") == "JSON"
            and isinstance(payload.get("raw_plan"), str)
            and isinstance(scenario, dict)
            and payload.get("host_environment_digest")
            == scenario.get("host_environment_digest"),
            "raw EXPLAIN evidence identity is invalid",
        )
        reference = cast(dict[str, Any], scenario).get("explain")
        _require(
            isinstance(reference, dict)
            and reference
            == {
                "format": "JSON",
                "unbounded_cartesian_join": False,
                "external_evidence": file_name,
            },
            "raw EXPLAIN scenario reference is invalid",
        )
        try:
            plan = json.loads(cast(str, payload["raw_plan"]))
        except json.JSONDecodeError as error:
            raise BaselineContractError("raw EXPLAIN plan is invalid") from error
        _require(
            isinstance(plan, dict)
            and isinstance(plan.get("query_block"), dict)
            and not _has_unbounded_cartesian_join(plan),
            "raw EXPLAIN plan is invalid",
        )
        digests[file_name] = hashlib.sha256(encoded).hexdigest()
    return digests


def _scenario_payloads(
    run_directory: Path,
) -> list[tuple[Path, dict[str, Any], str]]:
    _require(
        not (run_directory / "diagnostic-identity.json").exists()
        and not any(run_directory.glob("quick-diagnostic-*.json")),
        "quick diagnostic evidence is not valid formal evidence",
    )
    rows: list[tuple[Path, dict[str, Any], str]] = []
    paths = {
        path
        for pattern in ("backend-*.json", "ui-*.json", "bundle-*.json")
        for path in run_directory.glob(pattern)
    }
    for path in sorted(paths):
        if path.is_symlink():
            raise BaselineContractError("scenario evidence must not be a symbolic link")
        try:
            encoded = path.read_bytes()
            payload = json.loads(encoded.decode("utf-8"))
        except (OSError, UnicodeDecodeError, json.JSONDecodeError) as error:
            raise BaselineContractError(
                "scenario evidence could not be read"
            ) from error
        if not isinstance(payload, dict):
            raise BaselineContractError("scenario evidence must be a JSON object")
        rows.append((path, payload, hashlib.sha256(encoded).hexdigest()))
    return rows


def build_run_summary(
    run_directory: Path,
    *,
    manifest: Mapping[str, object],
    source_sha: str,
    mysql80_evidence: Path,
    mysql84_evidence: Path,
) -> dict[str, Any]:
    _require_source_sha(source_sha)
    run = run_directory.resolve(strict=True)
    repository = REPOSITORY_ROOT.resolve()
    _require(
        run != repository and repository not in run.parents,
        "run directory must be outside the repository",
    )
    identity = _read_json_object(run / "run-identity.json", label="run identity")
    _require(
        identity.get("run_id") == run.name
        and re.fullmatch(r"stage0-[0-9a-f]{12}", run.name) is not None
        and identity.get("source_sha") == source_sha
        and identity.get("status") == "prepared",
        "run identity is invalid",
    )
    source_identity = _release_source_identity(source_sha)
    product_runner_digest = _release_runner_digest(source_sha, "performance")
    external_evidence = dict(
        (
            _validate_external_evidence(
                mysql80_evidence,
                mysql_version="8.0",
                source_identity=source_identity,
                product_runner_digest=product_runner_digest,
            ),
            _validate_external_evidence(
                mysql84_evidence,
                mysql_version="8.4",
                source_identity=source_identity,
                product_runner_digest=product_runner_digest,
            ),
        )
    )
    _require(
        set(external_evidence)
        == set(cast(list[str], manifest["required_external_evidence"])),
        "required analytics_scale_v1 evidence is incomplete",
    )
    environment80 = capture_environment(
        repository_root=REPOSITORY_ROOT, mysql_version="8.0"
    )
    environment84 = capture_environment(
        repository_root=REPOSITORY_ROOT, mysql_version="8.4"
    )
    _require(
        environment80.get("source_sha") == source_sha
        and environment84.get("source_sha") == source_sha
        and environment80.get("git_tree") == source_identity["git_tree"]
        and environment84.get("git_tree") == source_identity["git_tree"],
        "captured environment does not match the source identity",
    )
    host80 = _host_identity(environment80)
    host84 = _host_identity(environment84)
    _require(
        host80["host_environment_digest"] == host84["host_environment_digest"],
        "run mixes host environment identities",
    )
    environment_identities = [
        {
            **host80,
            **source_identity,
            "mysql_version": "8.0",
        },
        {
            **host84,
            **source_identity,
            "mysql_version": "8.4",
        },
    ]
    command_results, counts = _command_results(run, source_sha=source_sha)
    scenario_evidence = _scenario_payloads(run)
    _, timing_trials = _validate_scenario_evidence(
        scenario_evidence,
        manifest=manifest,
        source_sha=source_sha,
        source_identity=source_identity,
    )
    scenario_digests = _scenario_digest_map(scenario_evidence)
    raw_explain_digests = _raw_explain_digests(
        run,
        scenario_evidence=scenario_evidence,
        source_sha=source_sha,
        source_identity=source_identity,
    )
    summary_without_digest: dict[str, Any] = {
        "schema_version": 1,
        "run_id": identity["run_id"],
        "source_sha": source_sha,
        "source_identity": source_identity,
        "environment_identities": environment_identities,
        "external_evidence": external_evidence,
        "command_results": command_results,
        "scenario_evidence_digests": scenario_digests,
        "raw_explain_evidence_digests": raw_explain_digests,
        "timing_trials": timing_trials,
        **counts,
    }
    return {
        **summary_without_digest,
        "evidence_digest": _contract_digest(summary_without_digest),
    }


def _validated_rounds(payload: Mapping[str, object]) -> list[Mapping[str, object]]:
    rounds = payload.get("rounds")
    if not isinstance(rounds, list) or not all(isinstance(row, dict) for row in rounds):
        raise BaselineContractError("scenario rounds are invalid")
    return cast(list[Mapping[str, object]], rounds)


def _required_scenario_keys(manifest: Mapping[str, object]) -> set[str]:
    performance_scenarios = cast(list[str], manifest["performance_scenarios"])
    mysql_scenarios = set(cast(list[str], manifest["mysql_matrix_scenarios"]))
    return {
        *(
            scenario_id
            for scenario_id in performance_scenarios
            if scenario_id not in mysql_scenarios
        ),
        *(
            f"{scenario_id}@mysql-{version}"
            for scenario_id in mysql_scenarios
            for version in ("8.0", "8.4")
        ),
    }


def _validate_scenario_evidence(
    evidence: Sequence[tuple[Path, dict[str, Any], str]],
    *,
    manifest: Mapping[str, object],
    source_sha: str,
    source_identity: Mapping[str, object],
) -> tuple[dict[str, Any], dict[str, dict[str, list[str]]]]:
    mysql_scenarios = set(cast(list[str], manifest["mysql_matrix_scenarios"]))
    performance_scenarios = cast(list[str], manifest["performance_scenarios"])
    scenario_rows: dict[str, Any] = {}
    timing_versions: dict[str, set[str]] = {name: set() for name in _TIMING_TRIALS}
    for _, payload, _ in evidence:
        scenario_id = payload.get("scenario_id")
        if not isinstance(scenario_id, str) or scenario_id not in performance_scenarios:
            raise BaselineContractError("unapproved scenario evidence is present")
        if (
            payload.get("source_sha") != source_sha
            or payload.get("warmup_samples") != 3
            or payload.get("measured_samples") != 20
            or payload.get("round_count") != 3
        ):
            raise BaselineContractError(
                f"invalid identity or protocol for {scenario_id}"
            )
        mysql_version = payload.get("mysql_version")
        if scenario_id in mysql_scenarios:
            if mysql_version not in {"8.0", "8.4"}:
                raise BaselineContractError(
                    f"MySQL identity is missing for {scenario_id}"
                )
            if payload.get("git_tree") != source_identity.get(
                "git_tree"
            ) or payload.get("runner_digest") != source_identity.get("runner_digest"):
                raise BaselineContractError(
                    f"source tree or runner identity is invalid for {scenario_id}"
                )
            scenario_key = f"{scenario_id}@mysql-{mysql_version}"
        else:
            if mysql_version is not None:
                raise BaselineContractError(
                    f"unexpected MySQL identity for {scenario_id}"
                )
            scenario_key = scenario_id
        if scenario_key in scenario_rows:
            raise BaselineContractError(f"duplicate scenario evidence: {scenario_key}")
        scenario_summary = summarize_scenario(_validated_rounds(payload))
        unit = payload.get("unit")
        _require(isinstance(unit, str) and bool(unit), "scenario unit is invalid")
        scenario_rows[scenario_key] = {
            **scenario_summary,
            "unit": unit,
            "proposed_ceiling": math.ceil(
                cast(float, scenario_summary["max_round_p95"]) * 1.20
            ),
        }
        if scenario_id in _TIMING_TRIALS:
            timing_versions[scenario_id].add(cast(str, mysql_version))
    required = _required_scenario_keys(manifest)
    if set(scenario_rows) != required:
        missing = sorted(required - set(scenario_rows))
        unexpected = sorted(set(scenario_rows) - required)
        raise BaselineContractError(
            f"scenario evidence set is incomplete or invalid: "
            f"missing={missing}, unexpected={unexpected}"
        )
    if not all(versions == {"8.0", "8.4"} for versions in timing_versions.values()):
        raise BaselineContractError(
            "all timing trials are required for both MySQL versions"
        )
    timing_trials = {
        name: {"mysql_versions": sorted(versions)}
        for name, versions in sorted(timing_versions.items())
    }
    return scenario_rows, timing_trials


def _scenario_digest_map(
    evidence: Sequence[tuple[Path, dict[str, Any], str]],
) -> dict[str, str]:
    return {path.name: digest for path, _, digest in evidence}


def validate_run(
    run_directory: Path, *, manifest: Mapping[str, object], source_sha: str
) -> dict[str, Any]:
    _require_source_sha(source_sha)
    run = run_directory.resolve(strict=True)
    repository = REPOSITORY_ROOT.resolve()
    _require(
        run != repository and repository not in run.parents,
        "run directory must be outside the repository",
    )
    identity = _read_json_object(run / "run-identity.json", label="run identity")
    run_summary = _read_json_object(run / "run-summary.json", label="run summary")
    if (
        identity.get("source_sha") != source_sha
        or identity.get("run_id") != run.name
        or re.fullmatch(r"stage0-[0-9a-f]{12}", run.name) is None
        or run_summary.get("source_sha") != source_sha
        or run_summary.get("run_id") != identity.get("run_id")
        or run_summary.get("unexplained_skip_count") != 0
        or run_summary.get("xfail_count") != 0
        or run_summary.get("retry_count") != 0
        or run_summary.get("flaky_count") != 0
        or run_summary.get("skip_count") != run_summary.get("explained_skip_count")
    ):
        raise BaselineContractError(
            "run identity or non-deterministic test counts are invalid"
        )
    source_identity = run_summary.get("source_identity")
    if not isinstance(source_identity, dict) or any(
        source_identity.get(name) != value
        for name, value in _release_source_identity(source_sha).items()
    ):
        raise BaselineContractError("run source tree or runner identity is invalid")
    summary_copy = dict(run_summary)
    recorded_digest = summary_copy.pop("evidence_digest", None)
    if recorded_digest != _contract_digest(summary_copy):
        raise BaselineContractError("run summary evidence digest is invalid")
    scenario_evidence = _scenario_payloads(run)
    recorded_scenario_digests = run_summary.get("scenario_evidence_digests")
    if not isinstance(
        recorded_scenario_digests, dict
    ) or recorded_scenario_digests != _scenario_digest_map(scenario_evidence):
        raise BaselineContractError(
            "finalized scenario evidence does not match the current run"
        )
    scenario_rows, expected_timing_trials = _validate_scenario_evidence(
        scenario_evidence,
        manifest=manifest,
        source_sha=source_sha,
        source_identity=source_identity,
    )
    current_raw_explain_digests = _raw_explain_digests(
        run,
        scenario_evidence=scenario_evidence,
        source_sha=source_sha,
        source_identity=source_identity,
    )
    if run_summary.get("raw_explain_evidence_digests") != current_raw_explain_digests:
        raise BaselineContractError(
            "finalized raw EXPLAIN evidence does not match the current run"
        )
    command_results, current_counts = _command_results(run, source_sha=source_sha)
    if run_summary.get("command_results") != command_results or any(
        run_summary.get(name) != value for name, value in current_counts.items()
    ):
        raise BaselineContractError(
            "finalized command evidence does not match the current run"
        )
    identities = run_summary.get("environment_identities")
    if not isinstance(identities, list) or not all(
        isinstance(row, dict) for row in identities
    ):
        raise BaselineContractError("run mixes source or environment identities")
    identity_rows = cast(list[dict[str, object]], identities)
    if (
        {row.get("source_sha") for row in identity_rows} != {source_sha}
        or len({row.get("host_environment_digest") for row in identity_rows}) != 1
        or {
            row.get("mysql_version")
            for row in identity_rows
            if row.get("mysql_version") is not None
        }
        != {"8.0", "8.4"}
        or any(
            row.get("git_tree") != source_identity.get("git_tree")
            or row.get("runner_digest") != source_identity.get("runner_digest")
            for row in identity_rows
        )
    ):
        raise BaselineContractError("run mixes source or environment identities")
    external_evidence = run_summary.get("external_evidence")
    if not isinstance(external_evidence, dict) or set(external_evidence) != set(
        cast(list[str], manifest["required_external_evidence"])
    ):
        raise BaselineContractError(
            "required analytics_scale_v1 evidence is incomplete"
        )
    timing_trials = run_summary.get("timing_trials")
    if not isinstance(timing_trials, dict) or timing_trials != expected_timing_trials:
        raise BaselineContractError("all timing trials are required")
    return {
        "validated": True,
        "run_id": identity["run_id"],
        "source_sha": source_sha,
        "environment_digest": identity_rows[0]["host_environment_digest"],
        "evidence_digest": recorded_digest,
        "candidate_timing": manifest["timing_candidate"],
        "scenarios": scenario_rows,
    }


def _freeze_approval_token(validated_run: Mapping[str, object]) -> str:
    fields = {
        "run_id": validated_run.get("run_id"),
        "source_sha": validated_run.get("source_sha"),
        "environment_digest": validated_run.get("environment_digest"),
        "evidence_digest": validated_run.get("evidence_digest"),
        "candidate_timing": validated_run.get("candidate_timing"),
        "scenarios": validated_run.get("scenarios"),
    }
    _require(
        isinstance(fields["run_id"], str)
        and re.fullmatch(r"stage0-[0-9a-f]{12}", fields["run_id"]) is not None
        and isinstance(fields["source_sha"], str)
        and re.fullmatch(r"[0-9a-f]{40}", fields["source_sha"]) is not None
        and isinstance(fields["environment_digest"], str)
        and re.fullmatch(r"[0-9a-f]{64}", fields["environment_digest"]) is not None
        and isinstance(fields["evidence_digest"], str)
        and re.fullmatch(r"[0-9a-f]{64}", fields["evidence_digest"]) is not None
        and isinstance(fields["candidate_timing"], dict)
        and isinstance(fields["scenarios"], dict),
        "validated run cannot produce an approval token",
    )
    return _contract_digest(
        {
            "schema_version": 1,
            **fields,
        }
    )


def build_freeze_record(
    validated_run: Mapping[str, object],
    *,
    approved_by: str,
    approval_reference: str,
    approval_token: str,
    approved_timing: Mapping[str, int],
    approved_budgets: Mapping[str, float],
) -> dict[str, Any]:
    scenarios = validated_run.get("scenarios")
    if (
        validated_run.get("validated") is not True
        or not approved_by.strip()
        or not approval_reference.strip()
        or not isinstance(scenarios, dict)
    ):
        raise BaselineContractError(
            "validated evidence and explicit approval are required"
        )
    timing_names = {
        "heartbeat_seconds",
        "stale_seconds",
        "offline_seconds",
        "refresh_seconds",
    }
    if set(approved_timing) != timing_names:
        raise BaselineContractError(
            "approved timing or scenario budget keys are invalid"
        )
    h, s, o, r = (
        approved_timing[name]
        for name in (
            "heartbeat_seconds",
            "stale_seconds",
            "offline_seconds",
            "refresh_seconds",
        )
    )
    normalized_budgets: dict[str, float] = {}
    try:
        for name, value in approved_budgets.items():
            if isinstance(value, bool) or not isinstance(value, (int, float)):
                raise TypeError
            checked = float(value)
            if not math.isfinite(checked) or checked <= 0:
                raise ValueError
            normalized_budgets[name] = checked
    except (TypeError, ValueError, OverflowError) as error:
        raise BaselineContractError(
            "approved timing or scenario budget keys are invalid"
        ) from error
    if (
        any(
            not isinstance(value, int) or isinstance(value, bool) or value <= 0
            for value in (h, s, o, r)
        )
        or s < 3 * h
        or o <= s
        or set(normalized_budgets) != set(scenarios)
    ):
        raise BaselineContractError(
            "approved timing or scenario budget keys are invalid"
        )
    run_id = validated_run.get("run_id")
    source_sha = validated_run.get("source_sha")
    environment_digest = validated_run.get("environment_digest")
    evidence_digest = validated_run.get("evidence_digest")
    if (
        not isinstance(run_id, str)
        or re.fullmatch(r"stage0-[0-9a-f]{12}", run_id) is None
        or not isinstance(source_sha, str)
        or re.fullmatch(r"[0-9a-f]{40}", source_sha) is None
        or not isinstance(environment_digest, str)
        or re.fullmatch(r"[0-9a-f]{64}", environment_digest) is None
        or not isinstance(evidence_digest, str)
        or re.fullmatch(r"[0-9a-f]{64}", evidence_digest) is None
        or not isinstance(approval_token, str)
        or re.fullmatch(r"[0-9a-f]{64}", approval_token) is None
    ):
        raise BaselineContractError("validated run identity is invalid")
    _require(
        approval_token == _freeze_approval_token(validated_run),
        "approval token does not match the validated evidence",
    )
    scenario_measurements: dict[str, object] = {}
    for name, scenario_value in cast(dict[str, object], scenarios).items():
        _require(
            isinstance(scenario_value, dict),
            "validated scenario measurement is invalid",
        )
        row = cast(dict[str, object], scenario_value)
        rounds = row.get("rounds")
        _require(
            isinstance(rounds, list)
            and len(rounds) == 3
            and all(
                isinstance(round_, dict)
                and all(
                    isinstance(round_.get(field), (int, float))
                    and not isinstance(round_.get(field), bool)
                    and math.isfinite(cast(float, round_[field]))
                    for field in ("p50", "p95", "max")
                )
                for round_ in rounds
            )
            and isinstance(row.get("unit"), str)
            and isinstance(row.get("median_round_p95"), (int, float)),
            "validated scenario measurement is invalid",
        )
        checked_rounds = cast(list[dict[str, object]], rounds)
        scenario_measurements[name] = {
            "unit": row["unit"],
            "rounds": [
                {field: round_[field] for field in ("p50", "p95", "max")}
                for round_ in checked_rounds
            ],
            "median_round_p95": row["median_round_p95"],
            "approved_ceiling": normalized_budgets[name],
        }
    return {
        "schema_version": 1,
        "baseline_id": "project-optimization-stage-0-v1",
        "measurement_source_sha": source_sha,
        "run_id": run_id,
        "approved_by": approved_by.strip(),
        "approval_reference": approval_reference.strip(),
        "approval_token": approval_token,
        "approved_at": datetime.now(UTC).isoformat().replace("+00:00", "Z"),
        "timing": {
            **dict(approved_timing),
            "offline_visible_seconds": o + r,
        },
        "scenario_budgets": normalized_budgets,
        "scenario_measurements": scenario_measurements,
        "environment_digest": environment_digest,
        "evidence_digest": evidence_digest,
    }


def _command_validate_manifest(options: argparse.Namespace) -> dict[str, object]:
    manifest = load_manifest(options.manifest, repository_root=REPOSITORY_ROOT)
    return {"valid": True, "baseline_id": manifest["baseline_id"]}


def _shard_node_digests_from_options(options: argparse.Namespace) -> dict[str, str]:
    values = cast(list[str], options.shard_node_digest)
    digests: dict[str, str] = {}
    for value in values:
        shard, separator, digest = value.partition("=")
        _require(
            bool(separator)
            and re.fullmatch(r"[a-z][a-z0-9-]*", shard) is not None
            and re.fullmatch(r"[0-9a-f]{64}", digest) is not None
            and shard not in digests,
            "pytest outcome shard node digests are invalid",
        )
        digests[shard] = digest
    return digests


def _command_validate_pytest_outcomes(options: argparse.Namespace) -> dict[str, object]:
    manifest = load_manifest(options.manifest, repository_root=REPOSITORY_ROOT)
    return validate_pytest_outcome_reports(
        options.report_directory,
        manifest=manifest,
        source_sha=options.source_sha,
        command_id=options.command_id,
        profile=options.profile,
        profile_node_digest=options.profile_node_digest,
        shard_node_digests=_shard_node_digests_from_options(options),
        platform_id=options.platform_id,
    )


def _command_pytest_outcome_binding(options: argparse.Namespace) -> dict[str, object]:
    return {
        "binding_sha256": pytest_outcome_binding(
            source_sha=options.source_sha,
            command_id=options.command_id,
            profile=options.profile,
            profile_node_digest=options.profile_node_digest,
            shard_node_digests=_shard_node_digests_from_options(options),
            platform_id=options.platform_id,
        )
    }


def _command_prepare_run(options: argparse.Namespace) -> dict[str, object]:
    root = resolve_empty_external_root(
        str(options.evidence_root), repository_root=REPOSITORY_ROOT
    )
    run = create_run_directory(root, run_id=f"stage0-{secrets.token_hex(6)}")
    write_json_exclusive(
        run / "run-identity.json",
        {"run_id": run.name, "source_sha": options.source_sha, "status": "prepared"},
    )
    return {"run_directory": str(run), "run_id": run.name}


def _validated_from_options(options: argparse.Namespace) -> dict[str, Any]:
    manifest = load_manifest(options.manifest, repository_root=REPOSITORY_ROOT)
    return validate_run(
        options.run_dir, manifest=manifest, source_sha=options.source_sha
    )


def _command_summarize(options: argparse.Namespace) -> dict[str, Any]:
    return _validated_from_options(options)


def _command_validate_run(options: argparse.Namespace) -> dict[str, Any]:
    return _validated_from_options(options)


def _command_finalize_run(options: argparse.Namespace) -> dict[str, Any]:
    manifest = load_manifest(options.manifest, repository_root=REPOSITORY_ROOT)
    summary = build_run_summary(
        options.run_dir,
        manifest=manifest,
        source_sha=options.source_sha,
        mysql80_evidence=options.mysql80_evidence,
        mysql84_evidence=options.mysql84_evidence,
    )
    write_json_exclusive(options.run_dir / "run-summary.json", summary)
    return summary


def _command_publish_results(options: argparse.Namespace) -> dict[str, object]:
    return publish_command_results(options.staging_dir, options.run_dir)


def _command_validate_external_evidence(
    options: argparse.Namespace,
) -> dict[str, object]:
    source_identity = _release_source_identity(options.source_sha)
    product_runner_digest = _release_runner_digest(options.source_sha, "performance")
    evidence = dict(
        (
            _validate_external_evidence(
                options.mysql80_evidence,
                mysql_version="8.0",
                source_identity=source_identity,
                product_runner_digest=product_runner_digest,
            ),
            _validate_external_evidence(
                options.mysql84_evidence,
                mysql_version="8.4",
                source_identity=source_identity,
                product_runner_digest=product_runner_digest,
            ),
        )
    )
    return {"valid": True, "source_identity": source_identity, "evidence": evidence}


def _command_freeze(options: argparse.Namespace) -> dict[str, Any]:
    validated = _validated_from_options(options)
    scenario_rows = cast(dict[str, dict[str, object]], validated["scenarios"])
    approval_token = _freeze_approval_token(validated)
    if not options.complete_freeze:
        return {
            "approval_required": True,
            "run_id": validated["run_id"],
            "source_sha": validated["source_sha"],
            "candidate_timing": validated["candidate_timing"],
            "scenarios": scenario_rows,
            "approval_token": approval_token,
        }

    _require(
        options.approved_run_id == validated["run_id"],
        "approved run ID does not match the validated run",
    )
    _require(
        options.approved_token == approval_token,
        "approved token does not match the validated evidence",
    )
    _require(
        isinstance(options.approved_by, str) and bool(options.approved_by.strip()),
        "approved-by is required to complete Freeze",
    )
    _require(
        isinstance(options.approval_reference, str)
        and bool(options.approval_reference.strip()),
        "approval-reference is required to complete Freeze",
    )
    timing_values = (
        options.heartbeat_seconds,
        options.stale_seconds,
        options.offline_seconds,
        options.refresh_seconds,
    )
    _require(
        all(value is not None for value in timing_values),
        "all four approved timing values are required to complete Freeze",
    )
    budget_selection_count = int(options.budget_overrides is not None) + int(
        options.accept_proposed_budgets is True
    )
    _require(
        budget_selection_count == 1,
        "exactly one approved budget selection is required to complete Freeze",
    )
    _require(options.output is not None, "output is required to complete Freeze")

    budgets: dict[str, float]
    if options.budget_overrides is not None:
        overrides = _read_json_object(
            options.budget_overrides, label="budget overrides"
        )
        try:
            budgets = {str(name): float(value) for name, value in overrides.items()}
        except (TypeError, ValueError, OverflowError) as error:
            raise BaselineContractError("budget overrides are invalid") from error
    else:
        _require(
            options.accept_proposed_budgets is True,
            "explicit proposed budget acceptance is required",
        )
        budgets = {
            name: float(cast(float, row["proposed_ceiling"]))
            for name, row in scenario_rows.items()
        }
    timing = {
        "heartbeat_seconds": options.heartbeat_seconds,
        "stale_seconds": options.stale_seconds,
        "offline_seconds": options.offline_seconds,
        "refresh_seconds": options.refresh_seconds,
    }
    record = build_freeze_record(
        validated,
        approved_by=options.approved_by.strip(),
        approval_reference=options.approval_reference.strip(),
        approval_token=approval_token,
        approved_timing=timing,
        approved_budgets=budgets,
    )
    write_json_exclusive(options.output, record)
    return record


def _add_manifest_argument(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--manifest", type=Path, required=True)


def _add_run_arguments(parser: argparse.ArgumentParser) -> None:
    _add_manifest_argument(parser)
    parser.add_argument("--run-dir", type=Path, required=True)
    parser.add_argument("--source-sha", type=_source_sha, required=True)


def _source_sha(value: str) -> str:
    if not re.fullmatch(r"[0-9a-f]{40}", value):
        raise argparse.ArgumentTypeError(
            "source SHA must be 40 lowercase hex characters"
        )
    return value


def main(arguments: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="project-optimization-baseline")
    subparsers = parser.add_subparsers(dest="command", required=True)
    validate_manifest_parser = subparsers.add_parser("validate-manifest")
    _add_manifest_argument(validate_manifest_parser)
    pytest_outcomes_parser = subparsers.add_parser("validate-pytest-outcomes")
    _add_manifest_argument(pytest_outcomes_parser)
    pytest_outcomes_parser.add_argument("--report-directory", type=Path, required=True)
    pytest_outcomes_parser.add_argument("--source-sha", type=_source_sha, required=True)
    pytest_outcomes_parser.add_argument("--command-id", required=True)
    pytest_outcomes_parser.add_argument("--profile", required=True)
    pytest_outcomes_parser.add_argument("--profile-node-digest", required=True)
    pytest_outcomes_parser.add_argument(
        "--shard-node-digest", action="append", required=True
    )
    pytest_outcomes_parser.add_argument(
        "--platform-id", choices=("win32", "linux", "darwin"), required=True
    )
    pytest_binding_parser = subparsers.add_parser("pytest-outcome-binding")
    pytest_binding_parser.add_argument("--source-sha", type=_source_sha, required=True)
    pytest_binding_parser.add_argument("--command-id", required=True)
    pytest_binding_parser.add_argument("--profile", required=True)
    pytest_binding_parser.add_argument("--profile-node-digest", required=True)
    pytest_binding_parser.add_argument(
        "--shard-node-digest", action="append", required=True
    )
    pytest_binding_parser.add_argument(
        "--platform-id", choices=("win32", "linux", "darwin"), required=True
    )
    prepare_parser = subparsers.add_parser("prepare-run")
    _add_manifest_argument(prepare_parser)
    prepare_parser.add_argument("--evidence-root", type=Path, required=True)
    prepare_parser.add_argument("--source-sha", type=_source_sha, required=True)
    summarize_parser = subparsers.add_parser("summarize")
    _add_run_arguments(summarize_parser)
    finalize_parser = subparsers.add_parser("finalize-run")
    _add_run_arguments(finalize_parser)
    finalize_parser.add_argument("--mysql80-evidence", type=Path, required=True)
    finalize_parser.add_argument("--mysql84-evidence", type=Path, required=True)
    publish_parser = subparsers.add_parser("publish-command-results")
    publish_parser.add_argument("--staging-dir", type=Path, required=True)
    publish_parser.add_argument("--run-dir", type=Path, required=True)
    external_parser = subparsers.add_parser("validate-external-evidence")
    external_parser.add_argument("--source-sha", type=_source_sha, required=True)
    external_parser.add_argument("--mysql80-evidence", type=Path, required=True)
    external_parser.add_argument("--mysql84-evidence", type=Path, required=True)
    validate_run_parser = subparsers.add_parser("validate-run")
    _add_run_arguments(validate_run_parser)
    freeze_parser = subparsers.add_parser("freeze")
    _add_run_arguments(freeze_parser)
    freeze_parser.add_argument("--approved-by")
    freeze_parser.add_argument("--approval-reference")
    freeze_parser.add_argument("--approved-run-id")
    freeze_parser.add_argument("--approved-token")
    freeze_parser.add_argument("--complete-freeze", action="store_true")
    freeze_parser.add_argument("--heartbeat-seconds", type=int)
    freeze_parser.add_argument("--stale-seconds", type=int)
    freeze_parser.add_argument("--offline-seconds", type=int)
    freeze_parser.add_argument("--refresh-seconds", type=int)
    budget_group = freeze_parser.add_mutually_exclusive_group()
    budget_group.add_argument("--budget-overrides", type=Path)
    budget_group.add_argument("--accept-proposed-budgets", action="store_true")
    freeze_parser.add_argument("--output", type=Path)
    options = parser.parse_args(arguments)
    handlers = {
        "validate-manifest": _command_validate_manifest,
        "validate-pytest-outcomes": _command_validate_pytest_outcomes,
        "pytest-outcome-binding": _command_pytest_outcome_binding,
        "prepare-run": _command_prepare_run,
        "summarize": _command_summarize,
        "finalize-run": _command_finalize_run,
        "publish-command-results": _command_publish_results,
        "validate-external-evidence": _command_validate_external_evidence,
        "validate-run": _command_validate_run,
        "freeze": _command_freeze,
    }
    try:
        result = handlers[options.command](options)
    except BaselineContractError as error:
        parser.error(str(error))
    except (
        OSError,
        json.JSONDecodeError,
        subprocess.SubprocessError,
        TypeError,
        ValueError,
        OverflowError,
    ):
        parser.error("baseline evidence operation failed")
    print(json.dumps(result, ensure_ascii=False, sort_keys=True, separators=(",", ":")))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
