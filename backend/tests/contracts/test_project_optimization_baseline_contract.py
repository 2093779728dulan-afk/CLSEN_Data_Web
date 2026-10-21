from __future__ import annotations

import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
BASELINE = json.loads(
    (ROOT / "scripts/project-optimization-baseline-manifest.json").read_text(
        encoding="utf-8"
    )
)


def test_every_declared_entrypoint_is_traceable_to_source() -> None:
    current_tokens = {"direct-api": "app = create_runtime_app()"}
    for entry in BASELINE["entrypoints"]:
        source = (ROOT / entry["path"]).read_text(encoding="utf-8")
        token = current_tokens.get(entry["id"], entry["evidence_token"])
        assert token in source, entry["id"]


def test_react_route_inventory_matches_the_closed_manifest() -> None:
    source = (ROOT / "frontend/src/app/App.tsx").read_text(encoding="utf-8")
    source_paths = set(
        re.findall(r'<Route\b(?:(?!<Route)[\s\S])*?\bpath="([^"]+)"', source)
    )
    assert source_paths == {row["path"] for row in BASELINE["routes"]}


def test_worker_runner_contains_each_manifest_queue() -> None:
    source = (ROOT / "backend/app/worker/runner.py").read_text(encoding="utf-8")
    required_tokens = {
        "publication_outbox": "self._outbox.run_once",
        "return_dedup": "self._return_dedup.run_once",
        "catalog_import": "self._catalog_imports.run_once",
        "catalog_export": "self._catalog_exports.run_once",
    }
    for queue in BASELINE["queues"]:
        assert required_tokens[queue["name"]] in source


def test_mysql_exclusion_audit_matches_current_ci_manifest_exactly() -> None:
    ci = json.loads(
        (ROOT / "scripts/ci-suite-manifest.json").read_text(encoding="utf-8")
    )
    audited = BASELINE["mysql_hosted_exclusions"]
    assert audited == ci["mysql_exclusions"]
    assert len(audited) == 14


def test_known_queue_state_sources_remain_traceable() -> None:
    expected = {
        "publication_outbox": {"pending", "processing", "completed", "failed"},
        "return_dedup": {"building", "ready", "failed", "superseded"},
        "catalog_import": {
            "uploaded",
            "parsing",
            "parse_failed",
            "needs_attention",
            "validated",
            "ready_for_approval",
            "approved",
            "rejected",
            "withdrawn",
            "superseded",
        },
        "catalog_export": {"building", "ready", "failed"},
    }
    assert {
        row["name"]: set(row["native_states"]) for row in BASELINE["queues"]
    } == expected


def test_operations_guide_covers_safety_profiles_approval_and_rebuild() -> None:
    guide = (ROOT / "docs/operations/project-optimization-baseline.md").read_text(
        encoding="utf-8"
    )
    for token in (
        "APP_PROJECT_OPTIMIZATION_EVIDENCE_ROOT",
        "仓库外",
        "合成数据",
        "ubuntu-full",
        "windows-smoke",
        "frontend-full",
        "MySQL 8.0",
        "MySQL 8.4",
        "OpenAPI",
        "H=10",
        "S=30",
        "O=60",
        "R=15",
        "O+R=75",
        "项目负责人批准",
        "不得覆盖",
        "data/",
        "14 个排除项",
        "project_owner",
        "backend_maintainer",
        "frontend_maintainer",
        "database_operator",
        "change_author",
    ):
        assert token in guide

    preview_start = guide.index("### 安全预览")
    completion_start = guide.index("### 项目负责人批准后的完成冻结")
    preview = guide[preview_start:completion_start]
    completion = guide[completion_start:]
    assert "精确的已验证场景/时间表" in preview
    assert "包括 H=10、S=30、O=60、R=15 四个时间值" in preview
    assert "项目负责人必须复核此精确表" in preview
    assert "四个时间输入必须与预览中已复核的精确表完全匹配" in completion
