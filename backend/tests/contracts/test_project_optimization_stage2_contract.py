from __future__ import annotations

import json
from pathlib import Path

REPOSITORY_ROOT = Path(__file__).resolve().parents[3]
MANIFEST = REPOSITORY_ROOT / "scripts/project-optimization-stage2-manifest.json"
RUNNER = REPOSITORY_ROOT / "scripts/run-project-optimization-stage2.ps1"
RUNBOOK = REPOSITORY_ROOT / "docs/operations/worker-observability.md"
CI_MANIFEST = REPOSITORY_ROOT / "scripts/ci-suite-manifest.json"
PERFORMANCE = (
    REPOSITORY_ROOT / "backend/tests/performance/test_project_optimization_baseline.py"
)
ADMIN_E2E = REPOSITORY_ROOT / "frontend/tests/e2e/admin-worker-observability.spec.ts"


def test_stage2_manifest_freezes_schema_thresholds_and_ceilings() -> None:
    payload = json.loads(MANIFEST.read_text(encoding="utf-8"))

    assert payload["schema_version"] == 1
    assert payload["schema_revision"] == "0023"
    assert payload["schema_anchor"] == "3750ad3"
    assert payload["queue_names"] == [
        "return_dedup",
        "publication_outbox",
        "catalog_export",
        "catalog_import",
    ]
    assert payload["thresholds_seconds"] == {
        "heartbeat": 10,
        "stale": 30,
        "offline": 60,
        "refresh": 15,
    }
    assert payload["retention"] == {"days": 30, "delete_limit": 500}
    assert payload["mysql_versions"] == ["8.0", "8.4"]
    assert payload["performance_protocol"] == {
        "warmups_per_round": 3,
        "samples_per_round": 20,
        "rounds": 3,
        "aggregate": "median_of_round_p95",
    }
    assert payload["scenario_ceilings_ms"] == {
        "admin-maintenance-api": {"8.0": 50, "8.4": 28},
        "heartbeat-single-row-update": {"8.0": 57, "8.4": 22},
        "heartbeat-long-task": {"8.0": 12028, "8.4": 12052},
        "heartbeat-maintenance-barrier": {"8.0": 27, "8.4": 21},
        "worker-idle-pass": {"8.0": 11, "8.4": 10},
        "queue-publication-outbox-query": {"8.0": 1, "8.4": 1},
        "queue-return-dedup-query": {"8.0": 2, "8.4": 1},
        "queue-catalog-import-query": {"8.0": 2, "8.4": 2},
        "queue-catalog-export-query": {"8.0": 1, "8.4": 2},
        "ui-admin-maintenance-load": {"chromium": 283},
    }
    assert payload["required_evidence"] == [
        "source_sha",
        "schema_revision",
        "environment_fingerprint",
        "command",
        "started_at",
        "completed_at",
        "exit_code",
        "node_count",
        "node_digest",
        "suite_results",
        "mysql_results",
        "command_records",
        "performance_results",
        "explain_plans",
        "privilege_verification",
        "backup_restore_rehearsal",
        "deployment_rehearsal",
        "administrator_page",
        "outcome_summary",
        "redaction",
    ]


def test_stage2_runner_is_same_sha_external_and_fail_closed() -> None:
    source = RUNNER.read_text(encoding="utf-8")

    for token in (
        '[ValidatePattern("^[0-9a-f]{40}$")]',
        '[ValidateSet("Collect", "Validate")]',
        "SourceSha",
        "EvidenceRoot",
        "git rev-parse HEAD",
        "git status --porcelain --untracked-files=no",
        "SELECT VERSION()",
        "node_digest",
        "started_at",
        "completed_at",
        "exit_code",
        "redaction",
        "mysql_results",
        "performance_results",
        "explain_plans",
        "backup_restore_rehearsal",
        "deployment_rehearsal",
        "administrator_page",
        "skipped|xfailed|xpassed|rerun|retried",
        "scenario_ceilings_ms",
        "[AllowEmptyCollection()]",
        "[AllowEmptyString()]",
        '[regex]::Replace($text, $sensitivePattern, "<redacted>")',
        "redaction_count",
    ):
        assert token in source
    assert "data/" not in source
    assert "data\\" not in source
    assert "Set-Content" not in source
    assert "Out-File" not in source


def test_worker_observability_runbook_has_operational_and_rollback_boundaries() -> None:
    source = RUNBOOK.read_text(encoding="utf-8")

    for heading in (
        "## 启动与停止",
        "## 状态解释",
        "## 四类队列映射",
        "## 30 天保留",
        "## 部署顺序",
        "## 回滚",
        "## 故障检查",
    ):
        assert heading in source
    for token in (
        "0023",
        "3750ad3",
        "10/30/60/15",
        "catalog_export",
        "catalog_import",
        "return_dedup",
        "publication_outbox",
        "先停止新 Worker",
        "不要手工修改",
    ):
        assert token in source


def test_worker_observability_is_one_canonical_mysql_suite() -> None:
    payload = json.loads(CI_MANIFEST.read_text(encoding="utf-8"))

    assert payload["profiles"]["mysql-compatibility"]["suites"][-1] == (
        "mysql-worker-observability"
    )
    assert payload["mysql_suites"]["mysql-worker-observability"] == [
        "backend/tests/integration/test_worker_observability.py",
        "backend/tests/integration/test_worker_observability_api.py",
    ]
    assert payload["profiles"]["ubuntu-full"]["pytest_ignores"][-2:] == [
        "backend/tests/integration/test_product_catalog_canary.py",
        "backend/tests/integration/test_real_csv_regression.py",
    ]


def test_performance_gate_uses_real_worker_observability_paths() -> None:
    source = PERFORMANCE.read_text(encoding="utf-8")

    assert "stage0_worker_heartbeat_probe" not in source
    assert "WorkerHeartbeatRepository" in source
    assert "WorkerHeartbeatController" in source
    assert "worker_status._QUEUE_SQL" in source


def test_admin_e2e_can_capture_external_stage2_evidence() -> None:
    source = ADMIN_E2E.read_text(encoding="utf-8")

    assert "APP_STAGE2_ADMIN_SCREENSHOT_PATH" in source
    assert "page.screenshot" in source
    assert "fullPage: true" in source
