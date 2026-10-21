# Project Optimization Stage 0 Baseline Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 为当前项目建立可追溯、可重复、可批准的阶段 0 基线，冻结真实入口、页面状态、四类 Worker 队列、质量门、性能证据协议和 H/S/O/R 候选值，同时不改变任何业务行为。

**Architecture:** 使用一个版本化 JSON manifest 作为阶段 0 的权威清单；Python 验证器负责严格校验清单、仓库追溯、外部证据目录、样本统计与冻结记录，PowerShell runner 负责在同一 clean SHA 上编排后端、前端、MySQL 8.0/8.4 和 OpenAPI 门禁。后端与 Playwright 基线采集器只使用合成夹具和可丢弃测试库，原始结果写入仓库外的新运行目录；仓库只提交清单、工具、测试、运维说明和经项目负责人明确批准后生成的冻结记录。

**Tech Stack:** Python 3.14、pytest、SQLAlchemy 2、FastAPI TestClient/真实 Uvicorn 进程、PowerShell 7、React 19、TypeScript 5.9、Playwright 1.62、MySQL 8.0/8.4、现有 `run-ci-profile.ps1` 与商品主档性能 harness。

## Global Constraints

- 本计划只实施路线图阶段 0；阶段 1 的 schema fail-fast、阶段 2 的 Worker 心跳/监控、阶段 3～4 的 UI 依赖与迁移、阶段 5 的模块拆分均不在本计划中。
- 不修改业务 schema，不运行或生成生产迁移，不调用 `alembic upgrade` 连接任何真实运行数据库。
- 不安装 Redis、RabbitMQ、Celery、RQ、Prometheus、Grafana、Radix UI、Lucide、Storybook、Motion、ECharts、Tailwind 或其他新运行依赖。
- 不修改审核、发布、权限、幂等、版本、商品目录或四类 Worker 的权威业务语义。
- 不读取、写入、删除、暂存或提交仓库中的 `data/`；不得读取真实客户数据、凭据、备份或私有语料。
- 只允许使用 `backend/tests/fixtures/synthetic/`、测试内构造数据和可丢弃 MySQL 8.0/8.4 测试库。
- 原始性能证据必须写入 `APP_PROJECT_OPTIMIZATION_EVIDENCE_ROOT` 指向的仓库外、新建且初始为空的目录；不得提交原始证据。
- 每个新增性能场景每轮恰好先预热 3 次，再保留 20 个有效样本，并独立运行 3 轮；保存每个原始样本及每轮 p50/p95/max，跨轮判定使用三轮 p95 的中位数。
- 复用 `analytics_scale_v1` 既有商品主档 harness 及其更严格约束，不复制、不降级、不外推为全系统性能结论。
- H/S/O/R 初始测量候选固定为 H=10 秒、S=30 秒、O=60 秒、R=15 秒；必须满足 `S >= 3H`、`O > S`，离线可见上限计算为 `O + R`，未经测量和项目负责人批准不得称为产品 SLO。
- 完成证据必须来自同一 clean candidate SHA；MySQL 8.4 结果不得引用另一 SHA，且不得有未解释的 skip、xfail、Playwright retry 或“重跑后才成功”。
- pull request 当前只要求 MySQL 8.0，MySQL 8.4 当前只在 master 门禁；此差异必须保留为基线事实。
- 当前 `ci-suite-manifest.json` 的 14 个 MySQL 排除项必须完整登记；profile 成功不得被描述为 batch review、outbox 等排除测试已获得 MySQL 双版本覆盖。
- 所有测量工具必须默认拒绝 dirty worktree、仓库内 evidence 目录、已有非空 evidence 目录、缺少环境指纹、错误 source SHA 或混合 MySQL 版本的结果。
- 预算放宽、H/S/O/R 替换或环境指纹变化必须生成新版本冻结记录并保留旧版本；实现者不能覆盖已批准记录。
- 工作区已有的用户未跟踪内容属于用户；实施提交只能包含本计划列出的文件。

---

## Approved Design and Baseline

- 权威规格：`docs/superpowers/specs/2026-08-27-project-optimization-roadmap-design.md`
- 规格提交：`1495fa0751e206c114a0b32626cb9bbf7a66b52e`
- 规格记录的业务基线提交：`8e2fb3478aa0cee3f2bcf1f34a02c16c01848826`
- 编写本计划时 HEAD：`1495fa0751e206c114a0b32626cb9bbf7a66b52e`
- 编写本计划时 tree：`47f73984b3e69899d84e28a069379fd08e8adce0`
- 编写本计划时工作区：`master...origin/master [ahead 5]`，唯一已知未跟踪项为用户目录 `data/`。

## Planned File Set

| Path | Action | Single responsibility |
| --- | --- | --- |
| `scripts/project-optimization-baseline-manifest.json` | Create | 阶段 0 的入口、页面、队列、质量门、场景、H/S/O/R 和负责人角色权威清单 |
| `tools/project_optimization_baseline.py` | Create | 严格 manifest/evidence 校验、统计、环境指纹、冻结记录生成和 CLI |
| `tools/tests/test_project_optimization_baseline.py` | Create | 验证器的纯单元测试，不需要数据库或浏览器 |
| `backend/tests/contracts/test_project_optimization_baseline_contract.py` | Create | 清单与真实仓库入口、路由、队列、CI 排除项的追溯合同 |
| `backend/tests/contracts/test_project_optimization_baseline_runner.py` | Create | PowerShell runner、外部 evidence 和同 SHA 门禁合同 |
| `backend/tests/performance/project_optimization_baseline.py` | Create | 后端 HTTP、SQL、Worker pass 与 H/S/O/R 试验的通用采样器 |
| `backend/tests/performance/test_project_optimization_baseline.py` | Create | 可丢弃 MySQL 环境中的阶段 0 后端场景适配与证据写入 |
| `frontend/playwright.baseline.config.ts` | Create | 固定 Chromium、字体、视口、无 retry 与外部 outputDir 的基线配置 |
| `frontend/tests/e2e/project-optimization-baseline.spec.ts` | Create | 合成 API mock 下的 UI 核心交互采样和机器可读结果 |
| `frontend/scripts/project-optimization-bundle-baseline.mjs` | Create | 对两种生产构建模式执行 3×(3+20) 次独立构建并记录耗时与 bundle bytes |
| `frontend/playwright.config.ts` | Modify | 从普通 `frontend-full` 浏览器门禁排除需要外部 evidence 的专用基线 spec |
| `frontend/package.json` | Modify | 增加不引入依赖的 `test:e2e:baseline` 命令 |
| `scripts/run-project-optimization-baseline.ps1` | Create | 同 clean SHA 质量门、两版 MySQL、前后端采样、汇总和冻结编排 |
| `scripts/run-ci-profile.ps1` | Modify | 增加 `project-optimization-baseline` release-only suite 的列出、验证和执行分支 |
| `scripts/ci-suite-manifest.json` | Modify | 登记阶段 0 release suite、runner 文件和 Windows contract allowlist |
| `scripts/CiSuiteManifest.psm1` | Modify | 允许阶段 0 release suite 拥有 runner identity，并将其解析为显式 MySQL-backed suite |
| `scripts/test-mysql-matrix.ps1` | Modify | 允许 `project-optimization-baseline` suite 在可丢弃 MySQL 8.0/8.4 数据库运行 |
| `backend/tests/contracts/test_ci_suite_manifest.py` | Modify | 锁定新增 release/MySQL suite 的严格 manifest 行为 |
| `backend/tests/fixtures/ci/offline-backend-nodeids.txt` | Modify | 冻结新增离线合同/单元测试节点 |
| `backend/tests/fixtures/ci/windows-smoke-nodeids.txt` | Modify | 冻结新增 Windows 合同测试节点 |
| `backend/tests/fixtures/ci/mysql-compatibility-nodeids.txt` | Do not modify | 阶段 0 性能测试由 release-only runner 执行，不进入既有 hosted MySQL collection；14 项排除范围保持原样 |
| `docs/operations/project-optimization-baseline.md` | Create | 操作者环境、命令、证据目录、审批、重建和回退手册 |
| `docs/operations/project-optimization-baseline-approval-v1.json` | Create at approval gate | 从经批准 evidence 自动生成的不可覆写冻结记录；不得手填测量数值 |

## Fixed Public Interfaces

所有后续任务必须使用以下精确名称；不得在实现中创建近义的第二套接口。

```python
# tools/project_optimization_baseline.py
class BaselineContractError(ValueError): ...

def load_manifest(path: Path, *, repository_root: Path) -> dict[str, Any]: ...
def validate_manifest(payload: Mapping[str, object], *, repository_root: Path) -> dict[str, Any]: ...
def resolve_empty_external_root(raw_path: str, *, repository_root: Path) -> Path: ...
def create_run_directory(evidence_root: Path, *, run_id: str) -> Path: ...
def percentile(samples: Sequence[float], percentile_value: float) -> float: ...
def summarize_round(samples: Sequence[float]) -> dict[str, object]: ...
def summarize_scenario(rounds: Sequence[Mapping[str, object]]) -> dict[str, object]: ...
def capture_environment(*, repository_root: Path, mysql_version: str) -> dict[str, object]: ...
def build_run_summary(run_directory: Path, *, manifest: Mapping[str, object], source_sha: str, mysql80_evidence: Path, mysql84_evidence: Path) -> dict[str, Any]: ...
def validate_run(run_directory: Path, *, manifest: Mapping[str, object], source_sha: str) -> dict[str, Any]: ...
def build_freeze_record(validated_run: Mapping[str, object], *, approved_by: str, approval_reference: str, approved_timing: Mapping[str, int], approved_budgets: Mapping[str, float]) -> dict[str, Any]: ...
def write_json_exclusive(path: Path, payload: Mapping[str, object]) -> None: ...
def main(arguments: Sequence[str] | None = None) -> int: ...
```

```python
# backend/tests/performance/project_optimization_baseline.py
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

def measure_scenario(scenario_id: str, operation: Callable[[], float], *, unit: str, protocol: SamplingProtocol = SamplingProtocol()) -> ScenarioResult: ...
def measure_http(url: str, *, headers: Mapping[str, str] | None = None, timeout_seconds: float = 10.0) -> float: ...
def measure_sql(connection: sa.Connection, statement: sa.TextClause, parameters: Mapping[str, object] | None = None) -> float: ...
def write_scenario_result(run_directory: Path, result: ScenarioResult) -> Path: ...
```

```typescript
// frontend/tests/e2e/project-optimization-baseline.spec.ts
type UiScenarioId = "dashboard-load" | "batch-review-confirm" | "admin-maintenance-load" | "product-chart-load";
type SampleRound = { samples_ms: number[]; p50_ms: number; p95_ms: number; max_ms: number };
async function measureUiScenario(page: Page, scenarioId: UiScenarioId, operation: () => Promise<void>): Promise<SampleRound[]>;
async function writeUiEvidence(testInfo: TestInfo, scenarioId: UiScenarioId, rounds: SampleRound[], browserVersion: string): Promise<void>;
```

---

### Task 1: Authoritative Baseline Manifest and Strict Loader

**Files:**
- Create: `scripts/project-optimization-baseline-manifest.json`
- Create: `tools/project_optimization_baseline.py`
- Create: `tools/tests/test_project_optimization_baseline.py`

**Interfaces:**
- Consumes: repository root `Path`; approved route/queue/profile facts from the roadmap and current source.
- Produces: `BaselineContractError`, `load_manifest(path, *, repository_root)`, and `validate_manifest(payload, *, repository_root)` with the signatures in **Fixed Public Interfaces**.

- [ ] **Step 1: Write failing tests for strict manifest identity, timing relations, complete route identities, four exact queue names, and repository-relative paths**

```python
# tools/tests/test_project_optimization_baseline.py
from __future__ import annotations

import json
from pathlib import Path

import pytest

from tools.project_optimization_baseline import BaselineContractError, load_manifest

ROOT = Path(__file__).resolve().parents[2]
MANIFEST = ROOT / "scripts" / "project-optimization-baseline-manifest.json"


def test_repository_manifest_is_valid_and_complete() -> None:
    payload = load_manifest(MANIFEST, repository_root=ROOT)
    assert payload["schema_version"] == 1
    assert payload["baseline_id"] == "project-optimization-stage-0-v1"
    assert {entry["id"] for entry in payload["entrypoints"]} == {
        "dev-api", "direct-api", "container-api", "demo-api",
        "live-api", "dev-worker", "direct-worker", "container-worker",
        "live-worker",
    }
    assert {route["path"] for route in payload["routes"]} == {
        "/", "/ledger/published-details", "/products", "/products/:style_id",
        "/dashboard", "/catalog", "/catalog/styles/:style_id",
        "/catalog/imports/:import_id", "/catalog/unmatched", "/catalog/versions",
        "/review/batch/:runId", "/review/:reportDate", "/published/:reportDate",
        "/review-advanced/:reportDate", "/published-details/:reportDate",
        "/versions", "/admin", "*",
    }
    assert {queue["name"] for queue in payload["queues"]} == {
        "publication_outbox", "return_dedup", "catalog_import", "catalog_export"
    }


def test_manifest_rejects_invalid_timing_relationships(tmp_path: Path) -> None:
    payload = json.loads(MANIFEST.read_text(encoding="utf-8"))
    payload["timing_candidate"] = {"heartbeat_seconds": 10, "stale_seconds": 29, "offline_seconds": 60, "refresh_seconds": 15}
    path = tmp_path / "manifest.json"
    path.write_text(json.dumps(payload), encoding="utf-8")
    with pytest.raises(BaselineContractError, match="stale_seconds must be at least 3"):
        load_manifest(path, repository_root=ROOT)


def test_manifest_rejects_unknown_keys_and_absolute_repository_paths(tmp_path: Path) -> None:
    payload = json.loads(MANIFEST.read_text(encoding="utf-8"))
    payload["unexpected"] = True
    payload["entrypoints"][0]["path"] = str(ROOT / "scripts" / "dev-backend.ps1")
    path = tmp_path / "manifest.json"
    path.write_text(json.dumps(payload), encoding="utf-8")
    with pytest.raises(BaselineContractError):
        load_manifest(path, repository_root=ROOT)
```

- [ ] **Step 2: Run the focused tests and verify Red**

Run: `D:\CLSEN_Data_Web\.venv\Scripts\python.exe -m pytest tools/tests/test_project_optimization_baseline.py -q`

Expected: FAIL during collection with `ModuleNotFoundError: No module named 'tools.project_optimization_baseline'`.

- [ ] **Step 3: Create the manifest with the exact route, state, queue, quality, performance, and ownership contracts**

Use this top-level shape and exact closed sets; route rows must each also include non-empty `primary_task`, `primary_action`, `information_hierarchy`, and one of `wide`, `narrow`, `wide+narrow` as `responsive_contract`.

```json
{
  "schema_version": 1,
  "baseline_id": "project-optimization-stage-0-v1",
  "design_commit": "1495fa0751e206c114a0b32626cb9bbf7a66b52e",
  "business_baseline_commit": "8e2fb3478aa0cee3f2bcf1f34a02c16c01848826",
  "roles": ["admin", "data_manager", "viewer"],
  "page_states": ["normal", "loading", "empty", "error", "permission", "offline", "long-content", "narrow"],
  "entrypoints": [
    {"id":"dev-api","kind":"api","path":"scripts/dev-backend.ps1","evidence_token":"app.main:app","schema_guard":"missing"},
    {"id":"direct-api","kind":"api","path":"backend/app/main.py","evidence_token":"app = create_app()","schema_guard":"missing"},
    {"id":"container-api","kind":"api","path":"backend/app/deployment/entrypoint.py","evidence_token":"uvicorn","schema_guard":"missing"},
    {"id":"demo-api","kind":"api","path":"scripts/start-stage9-demo.ps1","evidence_token":"app.main:app","schema_guard":"missing"},
    {"id":"live-api","kind":"api","path":"scripts/run-product-catalog-live-e2e.ps1","evidence_token":"app.main:app","schema_guard":"missing"},
    {"id":"dev-worker","kind":"worker","path":"scripts/run-worker.ps1","evidence_token":"app.worker.cli","schema_guard":"missing"},
    {"id":"direct-worker","kind":"worker","path":"backend/app/worker/cli.py","evidence_token":"def main(","schema_guard":"missing"},
    {"id":"container-worker","kind":"worker","path":"backend/app/deployment/entrypoint.py","evidence_token":"app.worker.cli","schema_guard":"missing"},
    {"id":"live-worker","kind":"worker","path":"scripts/run-product-catalog-live-e2e.ps1","evidence_token":"app.worker.cli","schema_guard":"missing"}
  ],
  "routes": [],
  "non_route_states": ["login", "session-restore", "site-loading", "site-error", "offline", "permission-denied", "feature-source-legacy_parser", "feature-source-p0_catalog"],
  "queues": [],
  "performance_protocol": {"warmups_per_round":3,"samples_per_round":20,"rounds":3,"round_summaries":["p50","p95","max"],"cross_round_aggregate":"median_of_round_p95"},
  "performance_scenarios": [
    "api-startup-readiness", "admin-maintenance-api",
    "queue-publication-outbox-query", "queue-return-dedup-query",
    "queue-catalog-import-query", "queue-catalog-export-query", "worker-idle-pass",
    "heartbeat-single-row-update", "heartbeat-long-task", "heartbeat-maintenance-barrier",
    "ui-dashboard-load", "ui-batch-review-confirm", "ui-admin-maintenance-load",
    "ui-product-chart-load", "frontend-bundle-legacy_parser", "frontend-bundle-p0_catalog"
  ],
  "mysql_matrix_scenarios": ["api-startup-readiness","admin-maintenance-api","queue-publication-outbox-query","queue-return-dedup-query","queue-catalog-import-query","queue-catalog-export-query","worker-idle-pass","heartbeat-single-row-update","heartbeat-long-task","heartbeat-maintenance-barrier"],
  "required_external_evidence": ["analytics_scale_v1:mysql:8.0","analytics_scale_v1:mysql:8.4"],
  "timing_candidate": {"heartbeat_seconds":10,"stale_seconds":30,"offline_seconds":60,"refresh_seconds":15,"offline_visible_seconds":75,"approval_status":"measurement_required"},
  "quality_profiles": ["ubuntu-full","windows-smoke","frontend-full","mysql-compatibility-8.0","mysql-compatibility-8.4","generated-contract","project-optimization-baseline"],
  "mysql_hosted_exclusions": [],
  "owner_roles": {"stage_owner":"project_owner","backend_evidence":"backend_maintainer","frontend_evidence":"frontend_maintainer","database_safety":"database_operator","rollback":"change_author"}
}
```

Set `routes` to the following closed matrix. `S1` means `normal,loading,empty,error,offline,long-content,narrow`; `S2` means `normal,permission`; the JSON stores the expanded state strings rather than the abbreviations.

| path | kind | roles | states | primary_task | primary_action | information_hierarchy | responsive_contract | role_behavior / redirect |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| `/` | business | admin,data_manager,viewer | S1 | 查看指定月份的发布概览 | 选择日期进入审核或已发布详情 | 月份与摘要→日历/指标→日期操作 | wide+narrow | 三角色读取；写角色可进入审核 |
| `/ledger/published-details` | business | admin,data_manager,viewer | S1 | 检索已发布明细账 | 筛选、分页、授权时导出 | 筛选条件→汇总→明细表→分页 | wide+narrow | viewer 无导出权限时保留只读页 |
| `/products` | feature-gated | admin,data_manager,viewer | S1 | 浏览商品指标账 | 筛选并进入款式详情 | 筛选/来源→指标表→分页 | wide+narrow | legacy_parser 时重定向 `/?tab=products` |
| `/products/:style_id` | feature-gated | admin,data_manager,viewer | S1 | 查看单款趋势和变体 | 切换指标/维度 | 款式身份→汇总→趋势→变体矩阵 | wide+narrow | legacy_parser 时重定向 `/?tab=products` |
| `/dashboard` | redirect | admin,data_manager,viewer | S2 | 保留旧入口兼容 | 自动重定向 | 无页面内容 | wide+narrow | `redirect_to: "/"` |
| `/catalog` | business | admin,data_manager,viewer | S1 | 浏览当前目录状态 | 搜索或进入款式 | 目录摘要→筛选→款式列表 | wide+narrow | 写操作按服务端权限显示 |
| `/catalog/styles/:style_id` | business | admin,data_manager,viewer | S1 | 查看目录款式和证据 | 查看版本/证据 | 款式身份→SKU→来源证据 | wide+narrow | 三角色读取 |
| `/catalog/imports/:import_id` | permission-gated | admin,data_manager | S1+permission | 审核目录导入草稿 | 校验、提交或批准 | 导入状态→问题摘要→分区表→工作流操作 | wide+narrow | viewer 重定向 `/catalog` |
| `/catalog/unmatched` | permission-gated | admin,data_manager | S1+permission | 处理未匹配标识 | 映射或排除 | 筛选→候选→证据→决策 | wide+narrow | viewer 重定向 `/catalog` |
| `/catalog/versions` | permission-gated | admin,data_manager | S1+permission | 查看目录版本历史 | 选择版本 | 当前版本→版本列表→变更摘要 | wide+narrow | viewer 重定向 `/catalog` |
| `/review/batch/:runId` | permission-gated | admin,data_manager | S1+permission | 批量推进已确认文件 | 确认、暂停、恢复或重试 | 任务状态→汇总→文件项→异常与待发布链接 | wide+narrow | viewer 重定向 `/` |
| `/review/:reportDate` | role-branch | admin,data_manager,viewer | S1+permission | 审核指定日期或查看已发布结果 | 编辑/验证/发布 | 日期上下文→工作台→高级发布控制 | wide+narrow | viewer 由 `ViewerReviewRedirect` 进入已发布路径 |
| `/published/:reportDate` | business | admin,data_manager,viewer | S1 | 查看指定日期已发布数据 | 浏览明细 | 日期工作台→已发布详情 | wide+narrow | 三角色只读 |
| `/review-advanced/:reportDate` | role-branch | admin,data_manager,viewer | S1+permission | 进入高级审核与发布控制 | 验证或发布 | 版本状态→检查→发布操作 | wide+narrow | 权限由 `DraftReviewGate` 服务端合同决定 |
| `/published-details/:reportDate` | business | admin,data_manager,viewer | S1 | 查看日期发布明细 | 筛选/导出（若授权） | 日期摘要→明细→操作 | wide+narrow | viewer 可能无导出权限 |
| `/versions` | business | admin,data_manager,viewer | S1 | 检索版本历史 | 选择或创建修订 | 筛选→版本列表→关系/操作 | wide+narrow | 写操作按权限显示 |
| `/admin` | permission-gated | admin | S1+permission | 管理用户、站点和维护状态 | 执行管理员命令 | 管理导航→状态→表单/命令结果 | wide+narrow | data_manager/viewer 重定向 `/` |
| `*` | redirect | admin,data_manager,viewer | S2 | 保留未知路径行为 | 自动重定向 | 无页面内容 | wide+narrow | `redirect_to: "/"` |

For each row, set `not_applicable_states` to the exact complement of its expanded `states` within the manifest `page_states`. Store `role_behavior` for every role, even when all three values are `read`; no row may use a wildcard role or an “other page” category.

Set the four queue rows to these exact native contracts:

```json
[
  {"name":"publication_outbox","native_states":["pending","processing","completed","failed"],"claim":"row-lock-and-processing-token","lease":"stale processing reclaim","retry":"available_at plus bounded attempts","current_recovery_gap":null},
  {"name":"return_dedup","native_states":["building","ready","failed","superseded"],"claim":"lease token plus fencing token","lease":"lease_expires_at","retry":"failed job restart with revision","current_recovery_gap":null},
  {"name":"catalog_import","native_states":["uploaded","parsing","parse_failed","needs_attention","validated","ready_for_approval","approved","rejected","withdrawn","superseded"],"claim":"uploaded to parsing plus parse lease/fencing","lease":"catalog_parse_attempts.lease_expires_at","retry":"explicit resume after parse_failed","current_recovery_gap":"expired parsing is not reclaimed by ordinary polling"},
  {"name":"catalog_export","native_states":["building","ready","failed"],"claim":"none","lease":"none","retry":"none","current_recovery_gap":"building cannot distinguish waiting from active and has no safe reclaim"}
]
```

Copy all 14 keys and reasons from `scripts/ci-suite-manifest.json:mysql_exclusions` into `mysql_hosted_exclusions` verbatim. Do not recategorize or remove any exclusion in this task.

- [ ] **Step 4: Implement the strict loader and closed-set validation**

```python
# tools/project_optimization_baseline.py
from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Mapping


class BaselineContractError(ValueError):
    """The baseline manifest or evidence violates a closed project contract."""


_TOP_LEVEL_KEYS = {
    "schema_version", "baseline_id", "design_commit", "business_baseline_commit",
    "roles", "page_states", "entrypoints", "routes", "non_route_states", "queues",
    "performance_protocol", "performance_scenarios", "mysql_matrix_scenarios",
    "required_external_evidence", "timing_candidate",
    "quality_profiles", "mysql_hosted_exclusions", "owner_roles",
}


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise BaselineContractError(message)


def validate_manifest(payload: Mapping[str, object], *, repository_root: Path) -> dict[str, Any]:
    _require(set(payload) == _TOP_LEVEL_KEYS, "manifest top-level keys are not the closed v1 contract")
    _require(payload["schema_version"] == 1, "schema_version must be 1")
    result = dict(payload)
    timing = result["timing_candidate"]
    _require(isinstance(timing, dict), "timing_candidate must be an object")
    h, s, o, r = (timing[name] for name in ("heartbeat_seconds", "stale_seconds", "offline_seconds", "refresh_seconds"))
    _require(all(isinstance(value, int) and value > 0 for value in (h, s, o, r)), "timing values must be positive integers")
    _require(s >= 3 * h, "stale_seconds must be at least 3 * heartbeat_seconds")
    _require(o > s, "offline_seconds must be greater than stale_seconds")
    _require(timing["offline_visible_seconds"] == o + r, "offline_visible_seconds must equal offline_seconds + refresh_seconds")
    for entry in result["entrypoints"]:
        path = Path(entry["path"])
        _require(not path.is_absolute() and ".." not in path.parts, "entrypoint paths must be repository-relative")
        _require((repository_root / path).is_file(), f"entrypoint path does not exist: {path.as_posix()}")
    route_paths = [row["path"] for row in result["routes"]]
    _require(len(route_paths) == len(set(route_paths)) == 18, "routes must contain 18 unique identities")
    queue_names = [row["name"] for row in result["queues"]]
    _require(queue_names == ["publication_outbox", "return_dedup", "catalog_import", "catalog_export"], "queues must use the approved order and names")
    scenario_ids = result["performance_scenarios"]
    mysql_scenarios = result["mysql_matrix_scenarios"]
    _require(len(scenario_ids) == len(set(scenario_ids)), "performance scenarios must be unique")
    _require(set(mysql_scenarios) <= set(scenario_ids), "MySQL matrix scenarios must be performance scenarios")
    _require(result["required_external_evidence"] == ["analytics_scale_v1:mysql:8.0", "analytics_scale_v1:mysql:8.4"], "both analytics_scale_v1 identities are required")
    return result


def load_manifest(path: Path, *, repository_root: Path) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise BaselineContractError(f"manifest could not be read: {error}") from error
    if not isinstance(payload, dict):
        raise BaselineContractError("manifest root must be an object")
    return validate_manifest(payload, repository_root=repository_root.resolve())
```

- [ ] **Step 5: Run the unit tests and static checks**

Run: `D:\CLSEN_Data_Web\.venv\Scripts\python.exe -m pytest tools/tests/test_project_optimization_baseline.py -q`

Expected: PASS with 3 tests.

Run: `D:\CLSEN_Data_Web\.venv\Scripts\python.exe -m ruff check --config backend/pyproject.toml tools/project_optimization_baseline.py tools/tests/test_project_optimization_baseline.py`

Expected: `All checks passed!`

- [ ] **Step 6: Commit the manifest contract**

```powershell
git add -- scripts/project-optimization-baseline-manifest.json tools/project_optimization_baseline.py tools/tests/test_project_optimization_baseline.py
git commit -m "test: define project optimization baseline contract"
```

Expected: commit contains exactly the three listed files and does not include `data/`.

---

### Task 2: Repository Traceability and CI Coverage Audit Contracts

**Files:**
- Create: `backend/tests/contracts/test_project_optimization_baseline_contract.py`
- Modify: `scripts/ci-suite-manifest.json` (`windows_smoke.contract_node_allowlist` only in this task)
- Modify: `backend/tests/fixtures/ci/offline-backend-nodeids.txt`
- Modify: `backend/tests/fixtures/ci/windows-smoke-nodeids.txt`

**Interfaces:**
- Consumes: `load_manifest(...)` from Task 1; `scripts/ci-suite-manifest.json`; current `frontend/src/app/App.tsx`, Worker source, migration 0022, and launch scripts.
- Produces: contract node IDs under `backend/tests/contracts/test_project_optimization_baseline_contract.py::*` and a Windows allowlist pattern with that exact filename.

- [ ] **Step 1: Write traceability tests that fail if an entry token disappears, route inventory drifts, queue native states drift, or any hosted MySQL exclusion is silently changed**

```python
# backend/tests/contracts/test_project_optimization_baseline_contract.py
from __future__ import annotations

import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
BASELINE = json.loads((ROOT / "scripts/project-optimization-baseline-manifest.json").read_text(encoding="utf-8"))


def test_every_declared_entrypoint_is_traceable_to_source() -> None:
    for entry in BASELINE["entrypoints"]:
        source = (ROOT / entry["path"]).read_text(encoding="utf-8")
        assert entry["evidence_token"] in source, entry["id"]


def test_react_route_inventory_matches_the_closed_manifest() -> None:
    source = (ROOT / "frontend/src/app/App.tsx").read_text(encoding="utf-8")
    source_paths = set(re.findall(r'<Route[^>]+path="([^"]+)"', source))
    assert source_paths == {row["path"] for row in BASELINE["routes"]}


def test_worker_runner_contains_each_manifest_queue() -> None:
    source = (ROOT / "backend/app/worker/runner.py").read_text(encoding="utf-8")
    required_tokens = {
        "publication_outbox": "self._outbox.run_once()",
        "return_dedup": "self._return_dedup.run_once()",
        "catalog_import": "self._catalog_imports.run_once()",
        "catalog_export": "self._catalog_exports.run_once()",
    }
    for queue in BASELINE["queues"]:
        assert required_tokens[queue["name"]] in source


def test_mysql_exclusion_audit_matches_current_ci_manifest_exactly() -> None:
    ci = json.loads((ROOT / "scripts/ci-suite-manifest.json").read_text(encoding="utf-8"))
    audited = {row["path"]: row["reason"] for row in BASELINE["mysql_hosted_exclusions"]}
    assert audited == ci["mysql_exclusions"]
    assert len(audited) == 14


def test_known_queue_state_sources_remain_traceable() -> None:
    expected = {
        "publication_outbox": {"pending", "processing", "completed", "failed"},
        "return_dedup": {"building", "ready", "failed", "superseded"},
        "catalog_import": {"uploaded", "parsing", "parse_failed", "needs_attention", "validated", "ready_for_approval", "approved", "rejected", "withdrawn", "superseded"},
        "catalog_export": {"building", "ready", "failed"},
    }
    assert {row["name"]: set(row["native_states"]) for row in BASELINE["queues"]} == expected
```

- [ ] **Step 2: Run the focused contract and verify Red on the missing CI node allowlist/baseline fixtures**

Run: `D:\CLSEN_Data_Web\.venv\Scripts\python.exe -m pytest backend/tests/contracts/test_project_optimization_baseline_contract.py -q`

Expected: the new contract itself passes; the next `ubuntu-full -ListOnly` or `windows-smoke -ListOnly` command fails because the new nodes are not approved yet.

Run: `pwsh -NoProfile -File scripts/run-ci-profile.ps1 -Profile windows-smoke -ListOnly`

Expected: FAIL with `Unapproved node 'backend/tests/contracts/test_project_optimization_baseline_contract.py::...' was added to the profile.`

- [ ] **Step 3: Add the exact contract allowlist and regenerate only the two affected node fixtures from collection output**

```json
// scripts/ci-suite-manifest.json, append under windows_smoke.contract_node_allowlist
"backend/tests/contracts/test_project_optimization_baseline_contract.py::*"
```

Generate candidate node lists without redirecting arbitrary shell text into repository files. Use the existing profile collection logic, compare sorted nodes, then edit both fixtures with `apply_patch`; expected additions are exactly the five test node IDs defined above. Do not change `mysql-compatibility-nodeids.txt` because these are non-MySQL contracts.

- [ ] **Step 4: Verify both profile collections and the exclusion audit**

Run: `pwsh -NoProfile -File scripts/run-ci-profile.ps1 -Profile ubuntu-full -ListOnly`

Expected: one JSON line with `"baseline_comparison":"baseline-preserved"` and no missing/unapproved nodes.

Run: `pwsh -NoProfile -File scripts/run-ci-profile.ps1 -Profile windows-smoke -ListOnly`

Expected: one JSON line with `"baseline_comparison":"baseline-preserved"` and no missing/unapproved nodes.

Run: `D:\CLSEN_Data_Web\.venv\Scripts\python.exe -m pytest backend/tests/contracts/test_project_optimization_baseline_contract.py -q`

Expected: PASS with 5 tests.

- [ ] **Step 5: Commit the traceability contracts**

```powershell
git add -- backend/tests/contracts/test_project_optimization_baseline_contract.py scripts/ci-suite-manifest.json backend/tests/fixtures/ci/offline-backend-nodeids.txt backend/tests/fixtures/ci/windows-smoke-nodeids.txt
git commit -m "test: audit optimization baseline coverage"
```

Expected: no business code and no MySQL exclusion are changed.

---

### Task 3: External Evidence Safety, Statistics, and Freeze Record

**Files:**
- Modify: `tools/project_optimization_baseline.py`
- Modify: `tools/tests/test_project_optimization_baseline.py`

**Interfaces:**
- Consumes: valid Task 1 manifest and the fixed performance protocol.
- Produces: all evidence/statistics/approval functions in **Fixed Public Interfaces** and CLI subcommands `validate-manifest`, `prepare-run`, `summarize`, `validate-run`, and `freeze`.

- [ ] **Step 1: Write failing tests for external empty roots, exclusive writes, exact percentile behavior, three-round validation, identity mismatch, and immutable approval output**

```python
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
    valid = [summarize_round([float(value) for value in range(1, 21)]) for _ in range(3)]
    assert summarize_scenario(valid)["median_round_p95"] == 19.0
    with pytest.raises(BaselineContractError, match="exactly 3 rounds"):
        summarize_scenario(valid[:2])


def test_freeze_record_is_bound_to_approval_and_cannot_overwrite(tmp_path: Path) -> None:
    record = build_freeze_record(
        {"run_id":"stage0-111111111111","source_sha":"1" * 40,"validated":True,"scenarios":{"admin-maintenance-api":{}},"environment_digest":"2" * 64,"evidence_digest":"3" * 64},
        approved_by="project-owner",
        approval_reference="codex-task-explicit-approval",
        approved_timing={"heartbeat_seconds":10,"stale_seconds":30,"offline_seconds":60,"refresh_seconds":15},
        approved_budgets={"admin-maintenance-api":125.0},
    )
    path = tmp_path / "approval-v1.json"
    write_json_exclusive(path, record)
    with pytest.raises(FileExistsError):
        write_json_exclusive(path, record)
```

- [ ] **Step 2: Run the focused tests and verify Red**

Run: `D:\CLSEN_Data_Web\.venv\Scripts\python.exe -m pytest tools/tests/test_project_optimization_baseline.py -q`

Expected: FAIL with imports such as `cannot import name 'summarize_round'`.

- [ ] **Step 3: Implement deterministic statistics and safe external run creation**

```python
import hashlib
import math
import os
import platform
import re
import secrets
import statistics
import subprocess
import sys
from collections.abc import Sequence
from datetime import UTC, datetime


def resolve_empty_external_root(raw_path: str, *, repository_root: Path) -> Path:
    root = Path(raw_path).expanduser().resolve()
    repository = repository_root.resolve()
    if root == repository or repository in root.parents:
        raise BaselineContractError("evidence root must be outside the repository")
    root.mkdir(parents=True, exist_ok=True)
    if any(root.iterdir()):
        raise BaselineContractError("evidence root must be empty")
    return root


def create_run_directory(evidence_root: Path, *, run_id: str) -> Path:
    if not re.fullmatch(r"stage0-[0-9a-f]{12}", run_id):
        raise BaselineContractError("run_id must match stage0-[0-9a-f]{12}")
    run = evidence_root / run_id
    run.mkdir(mode=0o700, parents=False, exist_ok=False)
    return run


def percentile(samples: Sequence[float], percentile_value: float) -> float:
    if not samples or not 0 < percentile_value <= 100:
        raise BaselineContractError("percentile input is invalid")
    ordered = sorted(float(value) for value in samples)
    rank = max(1, math.ceil(percentile_value / 100 * len(ordered)))
    return ordered[rank - 1]


def summarize_round(samples: Sequence[float]) -> dict[str, object]:
    values = [float(value) for value in samples]
    if len(values) != 20 or any(not math.isfinite(value) or value < 0 for value in values):
        raise BaselineContractError("each round requires 20 finite non-negative samples")
    return {"sample_count":20,"samples":values,"p50":statistics.median(values),"p95":percentile(values,95),"max":max(values)}


def summarize_scenario(rounds: Sequence[Mapping[str, object]]) -> dict[str, object]:
    if len(rounds) != 3:
        raise BaselineContractError("scenario requires exactly 3 rounds")
    p95s = [float(round_["p95"]) for round_ in rounds]
    return {"rounds":list(rounds),"median_round_p95":statistics.median(p95s),"min_round_p95":min(p95s),"max_round_p95":max(p95s),"relative_p95_spread":(max(p95s)-min(p95s))/statistics.median(p95s) if statistics.median(p95s) else 0.0}
```

- [ ] **Step 4: Implement environment/source identity, run validation, immutable freeze output, and CLI dispatch**

```python
def _checked_output(command: Sequence[str], cwd: Path) -> str:
    return subprocess.run(command, cwd=cwd, check=True, capture_output=True, text=True, encoding="utf-8").stdout.strip()


def capture_environment(*, repository_root: Path, mysql_version: str) -> dict[str, object]:
    return {
        "source_sha": _checked_output(["git", "rev-parse", "HEAD"], repository_root),
        "git_tree": _checked_output(["git", "rev-parse", "HEAD^{tree}"], repository_root),
        "python": sys.version.split()[0],
        "node": _checked_output(["node", "--version"], repository_root),
        "pnpm": _checked_output(["pnpm", "--version"], repository_root),
        "playwright_chromium": "1.62.1",
        "mysql": mysql_version,
        "os": platform.platform(),
        "machine": platform.machine(),
        "processor": platform.processor(),
        "cpu_count": os.cpu_count(),
        "memory_bytes": _physical_memory_bytes(),
        "fixture_ids": ["synthetic-reports-v1", "analytics_scale_v1", "stage0-worker-synthetic-v1"],
    }


def _physical_memory_bytes() -> int:
    if os.name == "nt":
        import ctypes
        class MemoryStatus(ctypes.Structure):
            _fields_ = [("length",ctypes.c_ulong),("memory_load",ctypes.c_ulong),("total_physical",ctypes.c_ulonglong),("available_physical",ctypes.c_ulonglong),("total_page_file",ctypes.c_ulonglong),("available_page_file",ctypes.c_ulonglong),("total_virtual",ctypes.c_ulonglong),("available_virtual",ctypes.c_ulonglong),("available_extended_virtual",ctypes.c_ulonglong)]
        status = MemoryStatus()
        status.length = ctypes.sizeof(MemoryStatus)
        if not ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(status)):
            raise BaselineContractError("physical memory fingerprint is unavailable")
        return int(status.total_physical)
    page_size = os.sysconf("SC_PAGE_SIZE")
    page_count = os.sysconf("SC_PHYS_PAGES")
    return int(page_size * page_count)


def write_json_exclusive(path: Path, payload: Mapping[str, object]) -> None:
    encoded = (json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n").encode("utf-8")
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(descriptor, "wb") as stream:
        stream.write(encoded)
        stream.flush()
        os.fsync(stream.fileno())


def build_freeze_record(validated_run: Mapping[str, object], *, approved_by: str, approval_reference: str, approved_timing: Mapping[str, int], approved_budgets: Mapping[str, float]) -> dict[str, Any]:
    if validated_run.get("validated") is not True or not approved_by.strip() or not approval_reference.strip():
        raise BaselineContractError("validated evidence and explicit approval are required")
    h, s, o, r = (int(approved_timing[name]) for name in ("heartbeat_seconds", "stale_seconds", "offline_seconds", "refresh_seconds"))
    if s < 3 * h or o <= s or set(approved_budgets) != set(validated_run["scenarios"]):
        raise BaselineContractError("approved timing or scenario budget keys are invalid")
    return {
        "schema_version":1,
        "baseline_id":"project-optimization-stage-0-v1",
        "measurement_source_sha":validated_run["source_sha"],
        "run_id":validated_run["run_id"],
        "approved_by":approved_by.strip(),
        "approval_reference":approval_reference.strip(),
        "approved_at":datetime.now(UTC).isoformat().replace("+00:00","Z"),
        "timing":{**dict(approved_timing),"offline_visible_seconds":o+r},
        "scenario_budgets":{name:float(value) for name,value in approved_budgets.items()},
        "environment_digest":validated_run["environment_digest"],
        "evidence_digest":validated_run["evidence_digest"],
    }
```

Implement run validation and CLI dispatch with this exact data flow:

```python
def validate_run(run_directory: Path, *, manifest: Mapping[str, object], source_sha: str) -> dict[str, Any]:
    if not re.fullmatch(r"[0-9a-f]{40}", source_sha):
        raise BaselineContractError("source_sha must be 40 lowercase hex characters")
    identity = json.loads((run_directory / "run-identity.json").read_text(encoding="utf-8"))
    run_summary = json.loads((run_directory / "run-summary.json").read_text(encoding="utf-8"))
    if identity["source_sha"] != source_sha or run_summary["source_sha"] != source_sha or run_summary["skip_count"] or run_summary["xfail_count"] or run_summary["retry_count"] or run_summary["flaky_count"]:
        raise BaselineContractError("run identity or non-deterministic test counts are invalid")
    mysql_scenarios = set(manifest["mysql_matrix_scenarios"])
    scenario_rows: dict[str, Any] = {}
    for path in sorted(run_directory.glob("*-*.json")):
        payload = json.loads(path.read_text(encoding="utf-8"))
        scenario_id = payload.get("scenario_id")
        if scenario_id not in manifest["performance_scenarios"]:
            continue
        if payload.get("source_sha") != source_sha or payload.get("warmup_samples") != 3 or payload.get("measured_samples") != 20 or payload.get("round_count") != 3:
            raise BaselineContractError(f"invalid identity or protocol for {scenario_id}")
        mysql_version = payload.get("mysql_version")
        if scenario_id in mysql_scenarios and mysql_version not in {"8.0", "8.4"}:
            raise BaselineContractError(f"MySQL identity is missing for {scenario_id}")
        scenario_key = f"{scenario_id}@mysql-{mysql_version}" if scenario_id in mysql_scenarios else str(scenario_id)
        if scenario_key in scenario_rows:
            raise BaselineContractError(f"duplicate scenario evidence: {scenario_key}")
        scenario_summary = summarize_scenario(payload["rounds"])
        scenario_rows[scenario_key] = {**scenario_summary, "unit":payload["unit"], "proposed_ceiling":math.ceil(float(scenario_summary["max_round_p95"]) * 1.20)}
    required = {
        *(scenario_id for scenario_id in manifest["performance_scenarios"] if scenario_id not in mysql_scenarios),
        *(f"{scenario_id}@mysql-{version}" for scenario_id in mysql_scenarios for version in ("8.0", "8.4")),
    }
    if set(scenario_rows) != required:
        raise BaselineContractError(f"missing scenarios: {sorted(required - set(scenario_rows))}")
    identities = run_summary["environment_identities"]
    if {row["source_sha"] for row in identities} != {source_sha} or len({row["host_environment_digest"] for row in identities}) != 1 or {row["mysql_version"] for row in identities if row["mysql_version"] is not None} != {"8.0", "8.4"}:
        raise BaselineContractError("run mixes source or environment identities")
    if set(run_summary["external_evidence"]) != set(manifest["required_external_evidence"]):
        raise BaselineContractError("required analytics_scale_v1 evidence is incomplete")
    timing_trials = run_summary["timing_trials"]
    if set(timing_trials) != {"heartbeat-single-row-update", "heartbeat-long-task", "heartbeat-maintenance-barrier"}:
        raise BaselineContractError("all timing trials are required")
    return {
        "validated":True,
        "run_id":identity["run_id"],
        "source_sha":source_sha,
        "environment_digest":identities[0]["host_environment_digest"],
        "evidence_digest":run_summary["evidence_digest"],
        "candidate_timing":manifest["timing_candidate"],
        "scenarios":scenario_rows,
    }


def _command_validate_manifest(options: argparse.Namespace) -> dict[str, object]:
    manifest = load_manifest(options.manifest, repository_root=REPOSITORY_ROOT)
    return {"valid":True,"baseline_id":manifest["baseline_id"]}


def _command_prepare_run(options: argparse.Namespace) -> dict[str, object]:
    root = resolve_empty_external_root(str(options.evidence_root), repository_root=REPOSITORY_ROOT)
    run = create_run_directory(root, run_id=f"stage0-{secrets.token_hex(6)}")
    write_json_exclusive(run / "run-identity.json", {"run_id":run.name,"source_sha":options.source_sha,"status":"prepared"})
    return {"run_directory":str(run),"run_id":run.name}


def _validated_from_options(options: argparse.Namespace) -> dict[str, Any]:
    manifest = load_manifest(options.manifest, repository_root=REPOSITORY_ROOT)
    return validate_run(options.run_dir, manifest=manifest, source_sha=options.source_sha)


def _command_summarize(options: argparse.Namespace) -> dict[str, Any]:
    return _validated_from_options(options)


def _command_validate_run(options: argparse.Namespace) -> dict[str, Any]:
    return _validated_from_options(options)


def _command_finalize_run(options: argparse.Namespace) -> dict[str, Any]:
    manifest = load_manifest(options.manifest, repository_root=REPOSITORY_ROOT)
    summary = build_run_summary(options.run_dir, manifest=manifest, source_sha=options.source_sha, mysql80_evidence=options.mysql80_evidence, mysql84_evidence=options.mysql84_evidence)
    write_json_exclusive(options.run_dir / "run-summary.json", summary)
    return summary


def _command_freeze(options: argparse.Namespace) -> dict[str, Any]:
    validated = _validated_from_options(options)
    budgets = {name:float(row["proposed_ceiling"]) for name,row in validated["scenarios"].items()}
    if options.budget_overrides is not None:
        overrides = json.loads(options.budget_overrides.read_text(encoding="utf-8"))
        if not isinstance(overrides, dict):
            raise BaselineContractError("budget overrides must be a JSON object")
        budgets = {str(name):float(value) for name,value in overrides.items()}
    timing = {
        "heartbeat_seconds":options.heartbeat_seconds,
        "stale_seconds":options.stale_seconds,
        "offline_seconds":options.offline_seconds,
        "refresh_seconds":options.refresh_seconds,
    }
    record = build_freeze_record(validated, approved_by=options.approved_by, approval_reference=options.approval_reference, approved_timing=timing, approved_budgets=budgets)
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
        raise argparse.ArgumentTypeError("source SHA must be 40 lowercase hex characters")
    return value


def main(arguments: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="project-optimization-baseline")
    subparsers = parser.add_subparsers(dest="command", required=True)
    validate_manifest_parser = subparsers.add_parser("validate-manifest")
    _add_manifest_argument(validate_manifest_parser)
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
    validate_run_parser = subparsers.add_parser("validate-run")
    _add_run_arguments(validate_run_parser)
    freeze_parser = subparsers.add_parser("freeze")
    _add_run_arguments(freeze_parser)
    freeze_parser.add_argument("--approved-by", required=True)
    freeze_parser.add_argument("--approval-reference", required=True)
    freeze_parser.add_argument("--heartbeat-seconds", type=int, required=True)
    freeze_parser.add_argument("--stale-seconds", type=int, required=True)
    freeze_parser.add_argument("--offline-seconds", type=int, required=True)
    freeze_parser.add_argument("--refresh-seconds", type=int, required=True)
    freeze_parser.add_argument("--budget-overrides", type=Path)
    freeze_parser.add_argument("--output", type=Path, required=True)
    options = parser.parse_args(arguments)
    handlers = {
        "validate-manifest": _command_validate_manifest,
        "prepare-run": _command_prepare_run,
        "summarize": _command_summarize,
        "finalize-run": _command_finalize_run,
        "validate-run": _command_validate_run,
        "freeze": _command_freeze,
    }
    result = handlers[options.command](options)
    print(json.dumps(result, ensure_ascii=False, sort_keys=True, separators=(",", ":")))
    return 0
```

Import `argparse` and define `REPOSITORY_ROOT = Path(__file__).resolve().parents[1]`. `build_run_summary` reads the immutable `run-identity.json`, all command-result JSON files and scenario evidence; it computes one host-only digest (OS/CPU/memory/Python/Node/pnpm/Chromium/fixture IDs), records MySQL 8.0 and 8.4 as separate database identities, validates both supplied `analytics_scale_v1` files against the source/tree/runner identity, counts skip/xfail/retry/flaky results, records the three timing trials, and returns a payload for exclusive `run-summary.json` creation. `validate_run` additionally rejects mismatched tree/runner digest, missing MySQL 8.0 or 8.4, absent `analytics_scale_v1` evidence, or timing trials without idle update, long task and maintenance write barrier. Error paths raise `SystemExit(2)` without printing secrets or database URLs.

- [ ] **Step 5: Run unit tests, Ruff, and mypy**

Run: `D:\CLSEN_Data_Web\.venv\Scripts\python.exe -m pytest tools/tests/test_project_optimization_baseline.py -q`

Expected: PASS.

Run: `D:\CLSEN_Data_Web\.venv\Scripts\python.exe -m ruff check --config backend/pyproject.toml tools/project_optimization_baseline.py tools/tests/test_project_optimization_baseline.py`

Expected: `All checks passed!`

Run: `D:\CLSEN_Data_Web\.venv\Scripts\python.exe -m mypy --config-file backend/pyproject.toml tools/project_optimization_baseline.py tools/tests/test_project_optimization_baseline.py`

Expected: `Success: no issues found`.

- [ ] **Step 6: Commit evidence primitives**

```powershell
git add -- tools/project_optimization_baseline.py tools/tests/test_project_optimization_baseline.py
git commit -m "feat: add immutable baseline evidence tooling"
```

---

### Task 4: Backend Performance and H/S/O/R Measurement Harness

**Files:**
- Create: `backend/tests/performance/project_optimization_baseline.py`
- Create: `backend/tests/performance/test_project_optimization_baseline.py`
- Modify: `scripts/ci-suite-manifest.json` (initial `project-optimization-baseline` release suite)
- Modify: `scripts/CiSuiteManifest.psm1` (strict suite keys and MySQL path resolution)
- Modify: `scripts/test-mysql-matrix.ps1` (suite ValidateSet)
- Modify: `backend/tests/contracts/test_ci_suite_manifest.py` (new suite resolution contract)

**Interfaces:**
- Consumes: `APP_PROJECT_OPTIMIZATION_RUN_DIR`, `APP_RELEASE_SOURCE_SHA`, `APP_TEST_DATABASE_URL`, `APP_TEST_RUNTIME_DATABASE_URL`, current admin login fixture patterns, `WorkerRunner.run_once()`, and Task 3 summaries.
- Produces: `SamplingProtocol`, `ScenarioResult`, `measure_scenario`, `measure_http`, `measure_sql`, `write_scenario_result`; JSON files named `backend-<mysql-version>-<scenario-id>.json`.

- [ ] **Step 1: Write unit-contract tests for exact warmup/sample/round call counts and exclusive evidence files**

```python
# backend/tests/performance/test_project_optimization_baseline.py
from __future__ import annotations

import json
from pathlib import Path

import pytest

from tests.performance.project_optimization_baseline import measure_scenario, write_scenario_result


def test_measure_scenario_uses_three_warmups_then_twenty_samples_for_three_rounds() -> None:
    calls = 0
    def operation() -> float:
        nonlocal calls
        calls += 1
        return float(calls)
    result = measure_scenario("synthetic-contract", operation, unit="ms")
    assert calls == 69
    assert len(result.rounds) == 3
    assert all(round_["sample_count"] == 20 for round_ in result.rounds)


def test_scenario_writer_never_overwrites(tmp_path: Path) -> None:
    result = measure_scenario("synthetic-contract", lambda: 1.0, unit="ms")
    path = write_scenario_result(tmp_path, result)
    assert json.loads(path.read_text(encoding="utf-8"))["scenario_id"] == "synthetic-contract"
    with pytest.raises(FileExistsError):
        write_scenario_result(tmp_path, result)
```

- [ ] **Step 2: Run focused tests and verify Red**

Run from `backend`: `..\.venv\Scripts\python.exe -m pytest tests/performance/test_project_optimization_baseline.py -k "measure_scenario or scenario_writer" -q`

Expected: FAIL with `ModuleNotFoundError: No module named 'tests.performance.project_optimization_baseline'`.

- [ ] **Step 3: Implement the sampler and exclusive result writer**

```python
# backend/tests/performance/project_optimization_baseline.py
from __future__ import annotations

import json
import os
import time
import urllib.request
from collections.abc import Callable, Mapping
from dataclasses import asdict, dataclass
from pathlib import Path

import sqlalchemy as sa


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


def measure_scenario(scenario_id: str, operation: Callable[[], float], *, unit: str, protocol: SamplingProtocol = SamplingProtocol()) -> ScenarioResult:
    rounds: list[dict[str, object]] = []
    for _ in range(protocol.rounds):
        for _ in range(protocol.warmups):
            operation()
        samples = [operation() for _ in range(protocol.measured_samples)]
        ordered = sorted(samples)
        rounds.append({
            "sample_count": len(samples),
            "samples": samples,
            "p50": (ordered[9] + ordered[10]) / 2,
            "p95": ordered[18],
            "max": ordered[-1],
        })
    return ScenarioResult(scenario_id=scenario_id, unit=unit, rounds=tuple(rounds))


def measure_http(url: str, *, headers: Mapping[str, str] | None = None, timeout_seconds: float = 10.0) -> float:
    started = time.perf_counter_ns()
    request = urllib.request.Request(url, headers=dict(headers or {}))
    with urllib.request.urlopen(request, timeout=timeout_seconds) as response:
        if response.status != 200:
            raise RuntimeError(f"HTTP baseline received {response.status}")
        response.read()
    return (time.perf_counter_ns() - started) / 1_000_000


def measure_sql(connection: sa.Connection, statement: sa.TextClause, parameters: Mapping[str, object] | None = None) -> float:
    started = time.perf_counter_ns()
    connection.execute(statement, dict(parameters or {})).all()
    return (time.perf_counter_ns() - started) / 1_000_000


def write_scenario_result(run_directory: Path, result: ScenarioResult) -> Path:
    path = run_directory / f"backend-{os.environ.get('APP_BASELINE_MYSQL_VERSION','unit')}-{result.scenario_id}.json"
    payload = {"schema_version":1,"scenario_id":result.scenario_id,"unit":result.unit,"warmup_samples":3,"measured_samples":20,"round_count":3,"rounds":list(result.rounds)}
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(descriptor, "w", encoding="utf-8", newline="\n") as stream:
        json.dump(payload, stream, ensure_ascii=False, indent=2, sort_keys=True)
        stream.write("\n")
    return path
```

- [ ] **Step 4: Add MySQL-marked adapters for the exact backend scenarios**

Keep the two sampler/writer contract tests unmarked so `ubuntu-full` can run them offline. Apply `@pytest.mark.mysql` only to the API, SQL, Worker and heartbeat adapter tests. The canonical runner sets `APP_REQUIRE_MYSQL_TESTS=1`; a MySQL-marked adapter must fail, not skip, when `APP_PROJECT_OPTIMIZATION_RUN_DIR`, `APP_RELEASE_SOURCE_SHA`, or the two test database URLs are missing.

```python
BACKEND_SCENARIOS = {
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

QUEUE_SQL = {
    "queue-publication-outbox-query": "SELECT status, COUNT(*) AS count, MIN(available_at) AS oldest_at FROM publication_outbox GROUP BY status",
    "queue-return-dedup-query": "SELECT status, COUNT(*) AS count, MIN(lease_expires_at) AS oldest_lease FROM return_dedup_staging_jobs GROUP BY status",
    "queue-catalog-import-query": "SELECT status, COUNT(*) AS count, MIN(updated_at) AS oldest_updated FROM catalog_imports GROUP BY status",
    "queue-catalog-export-query": "SELECT export_status AS status, COUNT(*) AS count, MIN(created_at) AS oldest_created FROM catalog_exports GROUP BY export_status",
}

@pytest.mark.parametrize("scenario_id", sorted(QUEUE_SQL))
@pytest.mark.mysql
def test_queue_query_baseline(mysql_engine: Engine, scenario_id: str, baseline_run_dir: Path) -> None:
    with mysql_engine.connect() as connection:
        statement = sa.text(QUEUE_SQL[scenario_id])
        result = measure_scenario(scenario_id, lambda: measure_sql(connection, statement), unit="ms")
    write_scenario_result(baseline_run_dir, result)
```

Implement these exact adapters as named tests:

- start a real Uvicorn subprocess on an OS-assigned free localhost port, measure process start through `GET /api/health/ready`, terminate only the owned PID in `finally`, and write `api-startup-readiness`;
- create/login an admin through the existing test pattern and measure `GET /api/admin/maintenance` without changing the response;
- build the existing four-worker `WorkerRunner`, run `--drain` semantics against empty synthetic queues, assert `WorkerPass.did_work is False`, and measure `worker-idle-pass`;
- create a temporary `stage0_worker_heartbeat_probe` table in the disposable test schema, measure one-row `UPDATE ... SET observed_at=UTC_TIMESTAMP(6)`, and drop only that exact temporary table in `finally`;
- run the same probe throughout a deterministic synthetic long task lasting at least `3H + 5` seconds and assert the maximum observed interval stays below S;
- use `hold_maintenance_write_barrier` to prove the probe write is blocked during the barrier, succeeds only after release, and record both blocked duration and first post-release update;
- never alter production migrations or call the future heartbeat implementation.

The adapter names and setup/cleanup boundaries are fixed by this code:

```python
def test_api_startup_readiness_baseline(baseline_run_dir: Path, owned_uvicorn: OwnedUvicorn) -> None:
    result = measure_scenario("api-startup-readiness", owned_uvicorn.restart_until_ready_ms, unit="ms")
    write_scenario_result(baseline_run_dir, result)


def test_admin_maintenance_api_baseline(admin_api: AdminApiContext, baseline_run_dir: Path) -> None:
    operation = lambda: measured_testclient_get_ms(admin_api.client, "/api/admin/maintenance")
    write_scenario_result(baseline_run_dir, measure_scenario("admin-maintenance-api", operation, unit="ms"))


def test_worker_idle_pass_baseline(empty_worker_runner: WorkerRunner, baseline_run_dir: Path) -> None:
    def operation() -> float:
        started = time.perf_counter_ns()
        worker_pass = empty_worker_runner.run_once()
        elapsed = (time.perf_counter_ns() - started) / 1_000_000
        assert worker_pass.did_work is False
        return elapsed
    write_scenario_result(baseline_run_dir, measure_scenario("worker-idle-pass", operation, unit="ms"))


def test_heartbeat_candidate_baselines(heartbeat_probe: HeartbeatProbe, baseline_run_dir: Path) -> None:
    for scenario_id, operation in (
        ("heartbeat-single-row-update", heartbeat_probe.update_ms),
        ("heartbeat-long-task", heartbeat_probe.long_task_max_interval_ms),
        ("heartbeat-maintenance-barrier", heartbeat_probe.barrier_release_to_update_ms),
    ):
        write_scenario_result(baseline_run_dir, measure_scenario(scenario_id, operation, unit="ms"))
```

Define `OwnedUvicorn` as a context-managed fixture that records one PID, starts `python -m uvicorn app.main:app --host 127.0.0.1 --port <owned-free-port>`, waits only on `/api/health/ready`, and terminates only that PID in `finally`. Define `HeartbeatProbe` as a context-managed fixture that creates/drops only `stage0_worker_heartbeat_probe` in the disposable database and exposes the three zero-argument methods above. Define `measured_testclient_get_ms(client: TestClient, path: str) -> float` locally and assert status 200 before returning milliseconds.

Each JSON adds `source_sha`, `git_tree`, `mysql_version`, `fixture_id`, `runner_digest`, and an `explain` object for each queue SQL. `EXPLAIN FORMAT=JSON` must show no unbounded Cartesian join; the raw plan is stored in external evidence only.

- [ ] **Step 5: Register the backend test file as an explicit MySQL-backed release suite**

```json
// scripts/ci-suite-manifest.json
"project-optimization-baseline": {
  "pytest_paths": ["backend/tests/performance/test_project_optimization_baseline.py"],
  "runner_paths": [
    "scripts/project-optimization-baseline-manifest.json",
    "tools/project_optimization_baseline.py",
    "backend/tests/performance/project_optimization_baseline.py",
    "backend/tests/performance/test_project_optimization_baseline.py"
  ]
}
```

```powershell
# scripts/CiSuiteManifest.psm1
Assert-ExactKeys $manifest.release_suites @(
    "workspace-boundary", "performance", "canary", "restore", "live",
    "deployment", "generated-contract", "project-optimization-baseline"
) "release_suites"

$expectedKeys = if ($suiteName -in @("performance", "project-optimization-baseline")) {
    @("pytest_paths", "runner_paths")
} else {
    @("pytest_paths")
}

foreach ($identitySuite in @("performance", "project-optimization-baseline")) {
    foreach ($relativePath in @($manifest.release_suites[$identitySuite].runner_paths)) {
        Assert-RepositoryPath $RepositoryRoot ([string]$relativePath)
    }
}

# inside Get-MySqlSuitePaths
elseif ($suite -in @("performance", "restore", "project-optimization-baseline")) {
    $suitePaths = @($Manifest.release_suites[$suite].pytest_paths)
}
```

```powershell
# scripts/test-mysql-matrix.ps1 parameter contract
[ValidateSet(
    "mysql-migrations", "mysql-legacy", "mysql-p0", "performance", "restore",
    "project-optimization-baseline"
)]
[string[]]$Suites
```

Add a contract test that imports the manifest and asserts this suite resolves exactly one path: `backend/tests/performance/test_project_optimization_baseline.py`. Do not add it to `profiles.mysql-compatibility.suites`, so hosted MySQL coverage and the 14 exclusions remain unchanged.

- [ ] **Step 6: Run offline sampler tests, strict manifest contracts, then one disposable MySQL 8.0 focused run**

Run from `backend`: `..\.venv\Scripts\python.exe -m pytest tests/performance/test_project_optimization_baseline.py -k "measure_scenario or scenario_writer" -q`

Expected: PASS with 2 tests and no skip.

Run: `D:\CLSEN_Data_Web\.venv\Scripts\python.exe -m pytest backend/tests/contracts/test_ci_suite_manifest.py -q`

Expected: PASS and prove the new suite is release-only/MySQL-backed but absent from hosted compatibility.

Run through the existing database matrix after setting a new external run directory: `pwsh -NoProfile -File scripts/test-mysql-matrix.ps1 -Versions 8.0 -Suites project-optimization-baseline -PythonExecutable D:\CLSEN_Data_Web\.venv\Scripts\python.exe -Confirm:$false`

Expected: every stage 0 performance test either runs and passes under the canonical environment or the command fails; no default skip is accepted when the canonical runner is active.

- [ ] **Step 7: Commit the backend harness**

```powershell
git add -- backend/tests/performance/project_optimization_baseline.py backend/tests/performance/test_project_optimization_baseline.py scripts/ci-suite-manifest.json scripts/CiSuiteManifest.psm1 scripts/test-mysql-matrix.ps1 backend/tests/contracts/test_ci_suite_manifest.py
git commit -m "test: measure backend optimization baseline"
```

---

### Task 5: Fixed Playwright UI Baseline Harness

**Files:**
- Create: `frontend/playwright.baseline.config.ts`
- Create: `frontend/tests/e2e/project-optimization-baseline.spec.ts`
- Create: `frontend/scripts/project-optimization-bundle-baseline.mjs`
- Modify: `frontend/playwright.config.ts` (`testIgnore`)
- Modify: `frontend/package.json` (`scripts.test:e2e:baseline`, `scripts.baseline:bundle`)

**Interfaces:**
- Consumes: `APP_PROJECT_OPTIMIZATION_RUN_DIR`, `APP_RELEASE_SOURCE_SHA`, existing Vite app and synthetic `page.route` API patterns.
- Produces: one exclusive `ui-<scenario-id>.json` per `UiScenarioId`; no screenshots become an approved visual baseline in stage 0.

- [ ] **Step 1: Write the fixed config and failing spec contract**

```typescript
// frontend/playwright.baseline.config.ts
import path from "node:path";
import { defineConfig, devices } from "@playwright/test";

const outputDir = process.env.APP_PROJECT_OPTIMIZATION_RUN_DIR;
if (!outputDir || !path.isAbsolute(outputDir)) throw new Error("APP_PROJECT_OPTIMIZATION_RUN_DIR must be an absolute external path");
const port = process.env.PLAYWRIGHT_PORT ?? "5173";

export default defineConfig({
  testDir: "./tests/e2e",
  testMatch: "project-optimization-baseline.spec.ts",
  fullyParallel: false,
  forbidOnly: true,
  retries: 0,
  workers: 1,
  reporter: [["list"], ["json", { outputFile: path.join(outputDir, "playwright-report.json") }]],
  outputDir: path.join(outputDir, "playwright-artifacts"),
  use: {
    ...devices["Desktop Chrome"],
    baseURL: `http://127.0.0.1:${port}`,
    locale: "zh-CN",
    timezoneId: "Asia/Shanghai",
    viewport: { width: 1440, height: 900 },
    deviceScaleFactor: 1,
    colorScheme: "light",
    reducedMotion: "reduce",
    screenshot: "off",
    trace: "off",
    video: "off",
  },
  webServer: {
    command: `pnpm dev --host 127.0.0.1 --port ${port} --strictPort`,
    env: { ...process.env, VITE_PRODUCT_ANALYTICS_SOURCE: "p0_catalog" },
    reuseExistingServer: false,
    timeout: 120_000,
    url: `http://127.0.0.1:${port}`,
  },
});
```

```typescript
// package.json scripts
"test:e2e:baseline": "playwright test --config playwright.baseline.config.ts",
"baseline:bundle": "node scripts/project-optimization-bundle-baseline.mjs"
```

```typescript
// playwright.config.ts: keep this evidence-only spec out of frontend-full
testIgnore: ["**/live/**", "**/*.live.spec.ts", "**/project-optimization-baseline.spec.ts"],
```

Create the spec with a test that asserts `process.env.APP_RELEASE_SOURCE_SHA` matches `/^[0-9a-f]{40}$/`, installs a shared synthetic auth/site-context route, and calls the not-yet-defined `measureUiScenario`; initial collection must fail on that missing function.

- [ ] **Step 2: Run TypeScript checks and verify Red**

Run from `frontend`: `pnpm typecheck`

Expected: FAIL because `measureUiScenario`/`writeUiEvidence` are referenced before implementation.

- [ ] **Step 3: Implement deterministic UI sampling and exclusive evidence writes**

```typescript
import { promises as fs } from "node:fs";
import path from "node:path";
import { performance } from "node:perf_hooks";
import { expect, test, type Page, type Route, type TestInfo } from "@playwright/test";

type UiScenarioId = "dashboard-load" | "batch-review-confirm" | "admin-maintenance-load" | "product-chart-load";
type SampleRound = { samples_ms: number[]; p50_ms: number; p95_ms: number; max_ms: number };

const percentile = (samples: number[], ratio: number) => [...samples].sort((a,b)=>a-b)[Math.max(0, Math.ceil(samples.length * ratio) - 1)];
const summarize = (samples_ms: number[]): SampleRound => ({
  samples_ms,
  p50_ms: ([...samples_ms].sort((a,b)=>a-b)[9] + [...samples_ms].sort((a,b)=>a-b)[10]) / 2,
  p95_ms: percentile(samples_ms, 0.95),
  max_ms: Math.max(...samples_ms),
});

async function measureUiScenario(page: Page, scenarioId: UiScenarioId, operation: () => Promise<void>): Promise<SampleRound[]> {
  const rounds: SampleRound[] = [];
  for (let round = 0; round < 3; round += 1) {
    for (let warmup = 0; warmup < 3; warmup += 1) await operation();
    const samples: number[] = [];
    for (let sample = 0; sample < 20; sample += 1) {
      const started = performance.now();
      await operation();
      const finished = performance.now();
      samples.push(finished - started);
    }
    rounds.push(summarize(samples));
  }
  test.info().annotations.push({ type: "scenario", description: scenarioId });
  return rounds;
}

async function writeUiEvidence(testInfo: TestInfo, scenarioId: UiScenarioId, rounds: SampleRound[], browserVersion: string): Promise<void> {
  const runDir = process.env.APP_PROJECT_OPTIMIZATION_RUN_DIR!;
  const target = path.join(runDir, `ui-${scenarioId}.json`);
  const handle = await fs.open(target, "wx", 0o600);
  try {
    await handle.writeFile(JSON.stringify({ schema_version:1, source_sha:process.env.APP_RELEASE_SOURCE_SHA, scenario_id:`ui-${scenarioId}`, warmup_samples:3, measured_samples:20, round_count:3, rounds, browser_name:"chromium", browser_version:browserVersion, viewport:{width:1440,height:900}, locale:"zh-CN", timezone:"Asia/Shanghai", retries:0 }, null, 2) + "\n", "utf8");
  } finally {
    await handle.close();
  }
  await testInfo.attach(`${scenarioId}-summary`, { body: Buffer.from(JSON.stringify(rounds)), contentType: "application/json" });
}
```

- [ ] **Step 4: Add all four explicit synthetic scenario operations**

Each test begins with a fresh browser page, installs only synthetic `/api/` responses, waits for a semantic completion locator, and resets UI state between samples:

```typescript
test("records dashboard load", async ({ page }, testInfo) => {
  await installSyntheticBootstrap(page, ["viewer"]);
  await installDashboardApi(page);
  const rounds = await measureUiScenario(page, "dashboard-load", async () => {
    await page.goto("/");
    await expect(page.getByRole("heading", { name: /数据看板/ })).toBeVisible();
  });
  await writeUiEvidence(testInfo, "dashboard-load", rounds, page.context().browser()?.version() ?? "unavailable");
});

test("records batch review confirmation", async ({ page }, testInfo) => {
  const fixture = await installSyntheticBatchReview(page);
  const rounds = await measureUiScenario(page, "batch-review-confirm", async () => {
    fixture.reset();
    await page.goto("/review/batch/42");
    await page.getByText("我已核对所选文件的报告日期和报表类型。").click();
    await page.getByRole("button", { name: /开始批量审核/ }).click();
    await expect(page.getByRole("button", { name: "暂停批量处理" })).toBeVisible();
  });
  await writeUiEvidence(testInfo, "batch-review-confirm", rounds, page.context().browser()?.version() ?? "unavailable");
});

test("records admin maintenance load", async ({ page }, testInfo) => {
  await installSyntheticBootstrap(page, ["admin"]);
  await installMaintenanceApi(page);
  const rounds = await measureUiScenario(page, "admin-maintenance-load", async () => {
    await page.goto("/admin");
    await expect(page.getByText(/维护与备份/)).toBeVisible();
  });
  await writeUiEvidence(testInfo, "admin-maintenance-load", rounds, page.context().browser()?.version() ?? "unavailable");
});

test("records product chart load", async ({ page }, testInfo) => {
  await installSyntheticBootstrap(page, ["viewer"]);
  await installProductChartApi(page);
  const rounds = await measureUiScenario(page, "product-chart-load", async () => {
    await page.goto("/products/88");
    await expect(page.getByRole("img", { name: /产品每日趋势/ })).toBeVisible();
  });
  await writeUiEvidence(testInfo, "product-chart-load", rounds, page.context().browser()?.version() ?? "unavailable");
});
```

Implement four local helpers with these exact signatures and state ownership:

```typescript
async function installSyntheticBootstrap(page: Page, roles: Array<"admin" | "data_manager" | "viewer">): Promise<void>;
async function installDashboardApi(page: Page): Promise<void>;
async function installSyntheticBatchReview(page: Page): Promise<{ reset(): void }>;
async function installMaintenanceApi(page: Page): Promise<void>;
async function installProductChartApi(page: Page): Promise<void>;
```

`installSyntheticBootstrap` returns `/api/auth/me` with `{id:3,username:"baseline-user",display_name:"基线用户",roles}` and `/api/data-calendar/site-context` with `{site_id:1,site_code:"amazon_us",display_name:"Amazon US",site_config_version_id:1,source_timezone:"America/Los_Angeles",reporting_timezone:"America/Los_Angeles",currency_code:"USD"}`. The other helpers use fixed IDs/date `42/88/2026-08-24`, reset all mutable counters before every operation, and reproduce the response models already asserted by `batch-review.spec.ts`, `AdminConsole.test.tsx`, and `ProductDetailPage.test.tsx`; because those checked-in tests are the DTO contract, copy their literal objects without deleting or renaming any field. Every unhandled API request returns a 500 JSON error with code `unhandled_baseline_request`; the browser context blocks every request whose hostname is not `127.0.0.1`.

- [ ] **Step 5: Implement independent production bundle sampling for both feature modes**

```javascript
// frontend/scripts/project-optimization-bundle-baseline.mjs
import { createHash } from "node:crypto";
import { closeSync, openSync, readdirSync, rmSync, statSync, writeFileSync } from "node:fs";
import path from "node:path";
import { performance } from "node:perf_hooks";
import { spawnSync } from "node:child_process";

const runDirectory = process.env.APP_PROJECT_OPTIMIZATION_RUN_DIR;
const sourceSha = process.env.APP_RELEASE_SOURCE_SHA;
if (!runDirectory || !path.isAbsolute(runDirectory) || !/^[0-9a-f]{40}$/.test(sourceSha ?? "")) throw new Error("external run directory and exact source SHA are required");
const pnpm = process.platform === "win32" ? "pnpm.cmd" : "pnpm";

function files(root) {
  return readdirSync(root, { withFileTypes: true }).flatMap((entry) => {
    const value = path.join(root, entry.name);
    return entry.isDirectory() ? files(value) : [value];
  });
}

function build(source) {
  rmSync("dist", { recursive: true, force: true });
  const started = performance.now();
  const result = spawnSync(pnpm, ["build"], { encoding: "utf8", env: { ...process.env, VITE_PRODUCT_ANALYTICS_SOURCE: source } });
  const build_ms = performance.now() - started;
  if (result.status !== 0) throw new Error(`bundle build failed for ${source}: ${result.stderr}`);
  const artifacts = files("dist").filter((file) => /\.(js|css)$/.test(file));
  return { build_ms, bundle_bytes: artifacts.reduce((total, file) => total + statSync(file).size, 0), artifact_digest: createHash("sha256").update(artifacts.sort().map((file) => `${path.relative("dist", file)}:${statSync(file).size}`).join("\n")).digest("hex") };
}

function summarize(values) {
  const ordered = [...values].sort((a, b) => a - b);
  return { sample_count:20, samples:values, p50:(ordered[9]+ordered[10])/2, p95:ordered[18], max:ordered[19] };
}

for (const source of ["legacy_parser", "p0_catalog"]) {
  const rounds = [];
  for (let round = 0; round < 3; round += 1) {
    for (let warmup = 0; warmup < 3; warmup += 1) build(source);
    const measurements = Array.from({ length: 20 }, () => build(source));
    rounds.push({ ...summarize(measurements.map((row) => row.bundle_bytes)), build_ms_samples:measurements.map((row) => row.build_ms), artifact_digests:[...new Set(measurements.map((row) => row.artifact_digest))] });
  }
  const payload = { schema_version:1, source_sha:sourceSha, scenario_id:`frontend-bundle-${source}`, unit:"bytes", warmup_samples:3, measured_samples:20, round_count:3, rounds };
  const output = path.join(runDirectory, `bundle-${source}.json`);
  const descriptor = openSync(output, "wx", 0o600);
  try { writeFileSync(descriptor, JSON.stringify(payload, null, 2) + "\n", "utf8"); } finally { closeSync(descriptor); }
}
```

The runner executes this script once. Each measured sample is a fresh production build after deleting only `frontend/dist`; the primary budget unit is total JS+CSS bytes, while build milliseconds and artifact digests remain diagnostic evidence.

- [ ] **Step 6: Verify lint, typecheck, normal E2E isolation, bundle sampling, and a canonical baseline run**

Run from `frontend`: `pnpm lint && pnpm typecheck`

Expected: both commands PASS with zero warnings.

Run from `frontend`: `pnpm exec playwright test --list`

Expected: normal config lists the existing E2E suite and does not list `project-optimization-baseline.spec.ts`.

Run after setting a new external run directory and exact SHA: `pnpm test:e2e:baseline`

Expected: 4 passed, 0 failed, 0 flaky, 0 skipped, 0 retries; four `ui-*.json` files and `playwright-report.json` exist outside the repository.

Run from `frontend`: `pnpm baseline:bundle`

Expected: PASS and create `bundle-legacy_parser.json` plus `bundle-p0_catalog.json` outside the repository, each with 3 rounds × 20 measured bundle-byte samples and three warmup builds per round.

- [ ] **Step 7: Commit the UI harness**

```powershell
git add -- frontend/playwright.baseline.config.ts frontend/tests/e2e/project-optimization-baseline.spec.ts frontend/scripts/project-optimization-bundle-baseline.mjs frontend/playwright.config.ts frontend/package.json
git commit -m "test: measure fixed UI interaction baseline"
```

---

### Task 6: Canonical Same-SHA Runner and Release Profile Integration

**Files:**
- Create: `scripts/run-project-optimization-baseline.ps1`
- Create: `backend/tests/contracts/test_project_optimization_baseline_runner.py`
- Modify: `scripts/run-ci-profile.ps1`
- Modify: `scripts/ci-suite-manifest.json`
- Modify: `backend/tests/contracts/test_ci_suite_manifest.py`
- Modify: `backend/tests/fixtures/ci/offline-backend-nodeids.txt`
- Modify: `backend/tests/fixtures/ci/windows-smoke-nodeids.txt`

**Interfaces:**
- Consumes: `-SourceSha <40 hex>`, `-PythonExecutable <absolute file>`, `-EvidenceRoot <external empty dir>`, `-Mode Validate|Collect|Freeze`, Task 3 CLI, Task 4/5 harnesses, and all existing CI profiles.
- Produces: `run-project-optimization-baseline.ps1`; release-only suite name `project-optimization-baseline`; `<run>/run-summary.json`; exit code 0 only for complete same-SHA evidence.

- [ ] **Step 1: Write failing runner contract tests**

```python
# backend/tests/contracts/test_project_optimization_baseline_runner.py
from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
RUNNER = ROOT / "scripts/run-project-optimization-baseline.ps1"


def test_runner_requires_external_evidence_and_same_sha() -> None:
    source = RUNNER.read_text(encoding="utf-8")
    for token in ("EvidenceRoot", "SourceSha", "git status --porcelain", "APP_PROJECT_OPTIMIZATION_EVIDENCE_ROOT", "APP_RELEASE_SOURCE_SHA"):
        assert token in source


def test_runner_executes_every_frozen_quality_gate() -> None:
    source = RUNNER.read_text(encoding="utf-8")
    for token in ("ubuntu-full", "windows-smoke", "frontend-full", 'mysql-compatibility', '8.0', '8.4', "generate-api-client.ps1", "run-product-catalog-performance.ps1"):
        assert token in source


def test_runner_disallows_retry_based_success() -> None:
    source = RUNNER.read_text(encoding="utf-8")
    assert 'PLAYWRIGHT_BASELINE_RETRIES = "0"' in source
    assert "Invoke-NativeChecked" in source
    assert "Retry" not in source
```

- [ ] **Step 2: Run the focused test and verify Red**

Run: `D:\CLSEN_Data_Web\.venv\Scripts\python.exe -m pytest backend/tests/contracts/test_project_optimization_baseline_runner.py -q`

Expected: FAIL with `FileNotFoundError` for `run-project-optimization-baseline.ps1`.

- [ ] **Step 3: Implement the runner preflight, owned environment, and validation mode**

```powershell
#Requires -Version 7.0
[CmdletBinding()]
param(
    [Parameter(Mandatory)][ValidatePattern("\A[0-9a-f]{40}\z")][string]$SourceSha,
    [Parameter(Mandatory)][string]$PythonExecutable,
    [Parameter(Mandatory)][string]$EvidenceRoot,
    [Parameter()][ValidateSet("Validate", "Collect", "Freeze")][string]$Mode = "Validate",
    [Parameter()][string]$ApprovedBy,
    [Parameter()][string]$ApprovalReference,
    [Parameter()][ValidateRange(1, 300)][int]$HeartbeatSeconds = 10,
    [Parameter()][ValidateRange(1, 900)][int]$StaleSeconds = 30,
    [Parameter()][ValidateRange(1, 1800)][int]$OfflineSeconds = 60,
    [Parameter()][ValidateRange(1, 300)][int]$RefreshSeconds = 15,
    [Parameter()][string]$BudgetOverridesPath
)
Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"
$PSNativeCommandUseErrorActionPreference = $false
$repositoryRoot = [IO.Path]::GetFullPath((Join-Path $PSScriptRoot ".."))
$manifest = Join-Path $PSScriptRoot "project-optimization-baseline-manifest.json"

function Invoke-NativeChecked([string]$Description, [scriptblock]$Command) {
    & $Command
    if ($LASTEXITCODE -ne 0) { throw "$Description failed with exit code $LASTEXITCODE." }
}

Push-Location -LiteralPath $repositoryRoot
try {
    $actualSha = (git rev-parse HEAD).Trim()
    if ($actualSha -cne $SourceSha) { throw "HEAD does not match SourceSha." }
    $dirty = @(git status --porcelain --untracked-files=all | Where-Object { $_ -notmatch '^\?\? data/' })
    if ($dirty.Count -ne 0) { throw "Baseline collection requires a clean candidate SHA outside the user-owned data directory." }
    Invoke-NativeChecked "manifest validation" { & $PythonExecutable tools/project_optimization_baseline.py validate-manifest --manifest $manifest }
}
finally { Pop-Location }

$env:APP_PROJECT_OPTIMIZATION_EVIDENCE_ROOT = [IO.Path]::GetFullPath($EvidenceRoot)
$env:APP_RELEASE_SOURCE_SHA = $SourceSha
$env:PLAYWRIGHT_BASELINE_RETRIES = "0"
```

Validation mode checks tools, MySQL URLs, Docker/MySQL version access, Node/pnpm/Chromium versions and both product catalog evidence paths, but creates no evidence and changes no database. Always restore every previous environment value in `finally`.

- [ ] **Step 4: Implement Collect mode in an exact, fail-fast order**

```powershell
$profiles = @(
    @{ Name = "ubuntu-full" },
    @{ Name = "windows-smoke" },
    @{ Name = "frontend-full" },
    @{ Name = "mysql-compatibility"; MySqlVersion = "8.0" },
    @{ Name = "mysql-compatibility"; MySqlVersion = "8.4" }
)
foreach ($profile in $profiles) {
    $arguments = @("-Profile", $profile.Name)
    if ($profile.Name -ne "frontend-full") { $arguments += @("-PythonExecutable", $PythonExecutable) }
    if ($profile.MySqlVersion) { $arguments += @("-MySqlVersion", $profile.MySqlVersion) }
    Invoke-NativeChecked "$($profile.Name) $($profile.MySqlVersion)" { pwsh -NoProfile -File scripts/run-ci-profile.ps1 @arguments }
}
Invoke-NativeChecked "OpenAPI drift" { pwsh -NoProfile -File scripts/generate-api-client.ps1 -Check }
Invoke-NativeChecked "existing product catalog baseline" { pwsh -NoProfile -File scripts/run-product-catalog-performance.ps1 -SourceSha $SourceSha -PythonExecutable $PythonExecutable -ValidateOnly }
foreach ($version in @("8.0", "8.4")) {
    $env:APP_BASELINE_MYSQL_VERSION = $version
    Invoke-NativeChecked "stage 0 backend MySQL $version" { pwsh -NoProfile -File scripts/test-mysql-matrix.ps1 -Versions $version -Suites project-optimization-baseline -PythonExecutable $PythonExecutable -Confirm:$false }
}
Push-Location frontend
try {
    Invoke-NativeChecked "stage 0 UI" { pnpm test:e2e:baseline }
    Invoke-NativeChecked "stage 0 bundle" { pnpm baseline:bundle }
}
finally { Pop-Location }
Invoke-NativeChecked "finalize evidence" { & $PythonExecutable tools/project_optimization_baseline.py finalize-run --run-dir $runDirectory --manifest $manifest --source-sha $SourceSha --mysql80-evidence $env:APP_PRODUCT_CATALOG_MYSQL80_SCALE_EVIDENCE --mysql84-evidence $env:APP_PRODUCT_CATALOG_MYSQL84_SCALE_EVIDENCE }
Invoke-NativeChecked "evidence validation" { & $PythonExecutable tools/project_optimization_baseline.py validate-run --run-dir $runDirectory --manifest $manifest --source-sha $SourceSha }
```

Before the first command, call `prepare-run` once to create `stage0-<12 hex>` under the empty external root and set `APP_PROJECT_OPTIMIZATION_RUN_DIR`. Capture each command’s start/end UTC, exit code, skip/xfail/flaky/retry counts, stdout digest and profile node digest into separate external JSON. Do not store full environment variables or command lines containing URLs.

- [ ] **Step 5: Implement Freeze mode as a distinct explicit-approval gate**

```powershell
if ($Mode -eq "Freeze") {
    if ([string]::IsNullOrWhiteSpace($ApprovedBy) -or [string]::IsNullOrWhiteSpace($ApprovalReference)) {
        throw "Freeze requires ApprovedBy and ApprovalReference after explicit project-owner approval."
    }
    & $PythonExecutable tools/project_optimization_baseline.py freeze `
        --run-dir $runDirectory `
        --manifest $manifest `
        --source-sha $SourceSha `
        --approved-by $ApprovedBy `
        --approval-reference $ApprovalReference `
        --heartbeat-seconds $HeartbeatSeconds `
        --stale-seconds $StaleSeconds `
        --offline-seconds $OfflineSeconds `
        --refresh-seconds $RefreshSeconds `
        --output docs/operations/project-optimization-baseline-approval-v1.json
    if ($LASTEXITCODE -ne 0) { throw "Freeze record generation failed." }
}
```

When `BudgetOverridesPath` is supplied, append `--budget-overrides $BudgetOverridesPath`; the JSON must contain every scenario exactly once and every ceiling must be a positive finite number. `Freeze` must refuse to collect missing evidence, infer approval, overwrite an existing approval file, accept a dirty SHA, or choose budgets automatically. The validated summary proposes an absolute p95 ceiling per scenario as `ceil(max(round_p95) * 1.20)` in the scenario’s unit, but this proposal becomes effective only when the project owner explicitly accepts the displayed table; the freeze record stores both measured p50/p95/max and approved ceiling. H/S/O/R defaults to 10/30/60/15 only when the three timing experiments pass; any replacement must be supplied as four explicit CLI values and revalidated.

- [ ] **Step 6: Register the release-only suite and update contract node fixtures**

```json
// scripts/ci-suite-manifest.json
"project-optimization-baseline": {
  "pytest_paths": ["backend/tests/performance/test_project_optimization_baseline.py"],
  "runner_paths": [
    "scripts/project-optimization-baseline-manifest.json",
    "tools/project_optimization_baseline.py",
    "backend/tests/performance/project_optimization_baseline.py",
    "backend/tests/performance/test_project_optimization_baseline.py",
    "frontend/playwright.baseline.config.ts",
    "frontend/playwright.config.ts",
    "frontend/tests/e2e/project-optimization-baseline.spec.ts",
    "frontend/scripts/project-optimization-bundle-baseline.mjs",
    "scripts/run-project-optimization-baseline.ps1"
  ]
}
```

Task 4 already registered the backend test file as a strict MySQL-backed release suite. In this task, expand that suite's `runner_paths` to the complete list above, add `project-optimization-baseline` to both `run-ci-profile.ps1` release-only ValidateSets/listings and `$requiredFiles`, make its `ValidateOnly` branch call the runner with `-Mode Validate`, and make its execution branch call `-Mode Collect`. Extend `test_ci_suite_manifest.py` so it also asserts every final runner identity path exists, while the hosted `mysql-compatibility` profile remains exactly `mysql-migrations,mysql-legacy,mysql-p0`. Add `backend/tests/contracts/test_project_optimization_baseline_runner.py::*` to the Windows allowlist and update only offline/Windows node fixtures with the three exact new node IDs.

- [ ] **Step 7: Verify contracts and all list-only profiles**

Run: `D:\CLSEN_Data_Web\.venv\Scripts\python.exe -m pytest backend/tests/contracts/test_project_optimization_baseline_runner.py backend/tests/contracts/test_ci_suite_manifest.py -q`

Expected: PASS, with no skip/xfail.

Run: `pwsh -NoProfile -File scripts/run-ci-profile.ps1 -Profile ubuntu-full -ListOnly`

Expected: baseline preserved.

Run: `pwsh -NoProfile -File scripts/run-ci-profile.ps1 -Profile windows-smoke -ListOnly`

Expected: baseline preserved.

Run: `pwsh -NoProfile -File scripts/run-ci-profile.ps1 -Profile mysql-compatibility -MySqlVersion 8.0 -ListOnly`

Expected: exact baseline preserved; the 14 exclusions remain excluded and documented.

Run: `pwsh -NoProfile -File scripts/test-mysql-matrix.ps1 -Versions 8.0 -Suites project-optimization-baseline -PythonExecutable D:\CLSEN_Data_Web\.venv\Scripts\python.exe -WhatIf`

Expected: the suite resolves only `tests/performance/test_project_optimization_baseline.py`; it never falls back to the product-catalog performance file.

Run: `pwsh -NoProfile -File scripts/run-ci-profile.ps1 -Profile release-only -ReleaseSuite project-optimization-baseline -SourceSha $(git rev-parse HEAD) -PythonExecutable D:\CLSEN_Data_Web\.venv\Scripts\python.exe -ValidateOnly`

Expected: PASS without collecting evidence or modifying the database.

- [ ] **Step 8: Commit the canonical runner**

```powershell
git add -- scripts/run-project-optimization-baseline.ps1 backend/tests/contracts/test_project_optimization_baseline_runner.py scripts/run-ci-profile.ps1 scripts/ci-suite-manifest.json backend/tests/contracts/test_ci_suite_manifest.py backend/tests/fixtures/ci/offline-backend-nodeids.txt backend/tests/fixtures/ci/windows-smoke-nodeids.txt
git commit -m "feat: orchestrate same-sha optimization baseline"
```

---

### Task 7: Operations Guide, Scope Ownership, and Rollback Contract

**Files:**
- Create: `docs/operations/project-optimization-baseline.md`
- Test: `backend/tests/contracts/test_project_optimization_baseline_contract.py`

**Interfaces:**
- Consumes: manifest/runner CLI and evidence names from Tasks 1–6.
- Produces: one operator guide whose commands match actual CLI/help output and which names all stage owner roles and rollback responsibilities.

- [ ] **Step 1: Add a failing documentation contract**

```python
def test_operations_guide_covers_safety_profiles_approval_and_rebuild() -> None:
    guide = (ROOT / "docs/operations/project-optimization-baseline.md").read_text(encoding="utf-8")
    for token in (
        "APP_PROJECT_OPTIMIZATION_EVIDENCE_ROOT", "仓库外", "合成数据",
        "ubuntu-full", "windows-smoke", "frontend-full", "MySQL 8.0", "MySQL 8.4",
        "OpenAPI", "H=10", "S=30", "O=60", "R=15", "O+R=75",
        "项目负责人批准", "不得覆盖", "data/", "14 个排除项",
        "project_owner", "backend_maintainer", "frontend_maintainer",
        "database_operator", "change_author",
    ):
        assert token in guide
```

- [ ] **Step 2: Run the focused contract and verify Red**

Run: `D:\CLSEN_Data_Web\.venv\Scripts\python.exe -m pytest backend/tests/contracts/test_project_optimization_baseline_contract.py::test_operations_guide_covers_safety_profiles_approval_and_rebuild -q`

Expected: FAIL with `FileNotFoundError` for the guide.

- [ ] **Step 3: Write the complete operator guide**

The guide must contain these exact sections and commands:

````markdown
# 项目优化阶段 0 基线运行手册

## 权限与数据边界
只允许可丢弃 MySQL 测试库和仓库合成夹具；不得读取 data/、真实客户数据、凭据或备份。

## 创建一次性仓库外证据根目录
```powershell
$baselineEvidence = Join-Path $env:TEMP ("clsen-stage0-" + [guid]::NewGuid().ToString("N"))
New-Item -ItemType Directory -Path $baselineEvidence | Out-Null
$env:APP_PROJECT_OPTIMIZATION_EVIDENCE_ROOT = $baselineEvidence
```

## 预检
```powershell
$sourceSha = (git rev-parse HEAD).Trim()
pwsh -NoProfile -File scripts/run-project-optimization-baseline.ps1 -Mode Validate -SourceSha $sourceSha -PythonExecutable D:\CLSEN_Data_Web\.venv\Scripts\python.exe -EvidenceRoot $env:APP_PROJECT_OPTIMIZATION_EVIDENCE_ROOT
```

## 采集
```powershell
pwsh -NoProfile -File scripts/run-project-optimization-baseline.ps1 -Mode Collect -SourceSha $sourceSha -PythonExecutable D:\CLSEN_Data_Web\.venv\Scripts\python.exe -EvidenceRoot $env:APP_PROJECT_OPTIMIZATION_EVIDENCE_ROOT
```

## 人工复核与冻结
先核对环境指纹、三轮原始样本、p50/p95/max、20% 绝对上限建议、H=10/S=30/O=60/R=15 和 O+R=75，再由项目负责人明确批准。批准前不得运行 Freeze。

## 环境变化与 v2
CPU、内存、OS、Python、Node、Chromium、MySQL、数据夹具或构建参数变化时创建 approval-v2；不得覆盖 v1。

## 回退
阶段 0 只增加清单、测试、只读/测试库测量和文档。回退时按独立提交删除 runner 或采集器，保留已批准 JSON 作为历史证据；不得借回退修改业务表或 data/。
````

另外逐项说明：质量 profile 同 SHA 规则、PR/MySQL 8.0 与 master/MySQL 8.4 差异、14 个排除项、skip/xfail/retry 判定、原始 evidence 不提交、负责人角色分工、各阶段回退责任，以及如何用 `Get-FileHash -Algorithm SHA256` 复核 evidence digest。

- [ ] **Step 4: Verify the documentation contract and CLI help agreement**

Run: `D:\CLSEN_Data_Web\.venv\Scripts\python.exe -m pytest backend/tests/contracts/test_project_optimization_baseline_contract.py -q`

Expected: PASS.

Run: `D:\CLSEN_Data_Web\.venv\Scripts\python.exe tools/project_optimization_baseline.py --help`

Expected: lists `validate-manifest`, `prepare-run`, `finalize-run`, `summarize`, `validate-run`, and `freeze` exactly as documented.

Run: `Get-Help .\scripts\run-project-optimization-baseline.ps1 -Full`

Expected: lists `Validate`, `Collect`, `Freeze`, `SourceSha`, `PythonExecutable`, `EvidenceRoot`, `ApprovedBy`, and `ApprovalReference`.

- [ ] **Step 5: Commit the operations contract**

```powershell
git add -- docs/operations/project-optimization-baseline.md backend/tests/contracts/test_project_optimization_baseline_contract.py backend/tests/fixtures/ci/offline-backend-nodeids.txt backend/tests/fixtures/ci/windows-smoke-nodeids.txt
git commit -m "docs: add optimization baseline operations guide"
```

---

### Task 8: Collect, Review, Freeze, and Prove Stage 0 Completion

**Files:**
- Create after explicit approval: `docs/operations/project-optimization-baseline-approval-v1.json`
- Modify only if the approved timing differs from the candidate: `scripts/project-optimization-baseline-manifest.json`
- Modify only if manifest tests change because timing differs: `tools/tests/test_project_optimization_baseline.py`
- External only, never commit: `$env:APP_PROJECT_OPTIMIZATION_EVIDENCE_ROOT/stage0-*/**`

**Interfaces:**
- Consumes: all prior tasks; an explicit project-owner approval of the displayed same-SHA summary.
- Produces: immutable approval v1 and complete stage 0 evidence; no later-stage code.

- [ ] **Step 1: Freeze the candidate source before collection**

```powershell
$candidateSha = (git rev-parse HEAD).Trim()
$candidateTree = (git rev-parse 'HEAD^{tree}').Trim()
git status --short --branch
```

Expected: only the explicitly tolerated user-owned `?? data/` is present; no planned file is dirty. Record `$candidateSha` and `$candidateTree` in the external run metadata.

- [ ] **Step 2: Create a fresh external root and run validation**

```powershell
$stage0Evidence = Join-Path $env:TEMP ("clsen-stage0-" + [guid]::NewGuid().ToString("N"))
New-Item -ItemType Directory -Path $stage0Evidence | Out-Null
pwsh -NoProfile -File scripts/run-project-optimization-baseline.ps1 -Mode Validate -SourceSha $candidateSha -PythonExecutable D:\CLSEN_Data_Web\.venv\Scripts\python.exe -EvidenceRoot $stage0Evidence
```

Expected: PASS without files in the repository or DML in any real database.

- [ ] **Step 3: Collect all same-SHA evidence once**

```powershell
pwsh -NoProfile -File scripts/run-project-optimization-baseline.ps1 -Mode Collect -SourceSha $candidateSha -PythonExecutable D:\CLSEN_Data_Web\.venv\Scripts\python.exe -EvidenceRoot $stage0Evidence
```

Expected: ubuntu-full, windows-smoke, frontend-full, MySQL 8.0, MySQL 8.4, OpenAPI drift, existing `analytics_scale_v1`, backend stage 0 and UI stage 0 all PASS on `$candidateSha`; run summary reports 0 unexplained skips, 0 xfails, 0 flaky tests and 0 retries.

- [ ] **Step 4: Review the exact evidence table before any candidate implementation is run**

```powershell
$runDirectory = Get-ChildItem -LiteralPath $stage0Evidence -Directory | Select-Object -Single
& D:\CLSEN_Data_Web\.venv\Scripts\python.exe tools/project_optimization_baseline.py summarize --run-dir $runDirectory.FullName --manifest scripts/project-optimization-baseline-manifest.json --source-sha $candidateSha
```

Expected: prints every scenario’s three p50/p95/max rows, p95 spread, proposed absolute ceiling, environment digest, database overhead, long-task interval, maintenance-barrier behavior, H/S/O/R candidate and O+R. It must not silently freeze anything.

- [ ] **Step 5: Stop for explicit project-owner approval**

Present the complete summary, the proposed absolute ceilings, and H=10/S=30/O=60/R=15 to the project owner. Continue only after an explicit approval message that identifies this run ID and either accepts all values or supplies all four replacement timing values plus adjusted scenario ceilings. This is a mandatory authority boundary; silence, prior roadmap approval, or implementation success is not approval of measured budgets.

- [ ] **Step 6: Generate the immutable freeze record from approved evidence**

After approval, run the command with the actual approving identity and durable approval reference from that message:

```powershell
pwsh -NoProfile -File scripts/run-project-optimization-baseline.ps1 -Mode Freeze -SourceSha $candidateSha -PythonExecutable D:\CLSEN_Data_Web\.venv\Scripts\python.exe -EvidenceRoot $stage0Evidence -ApprovedBy $approvedBy -ApprovalReference $approvalReference
```

Expected: creates `docs/operations/project-optimization-baseline-approval-v1.json` exactly once, bound to the measurement source SHA/tree, calibration run ID, environment digest, evidence digest, approved timing and per-scenario absolute budgets. If approved timing differs, update the manifest candidate to the four approved values and keep the original measured candidate in the approval record’s `candidate_timing` field. The record calls this field `measurement_source_sha`; it does not attempt to predict the later commit SHA that will contain the record.

- [ ] **Step 7: Commit the approved freeze record and establish the final candidate SHA**

```powershell
git add -- docs/operations/project-optimization-baseline-approval-v1.json scripts/project-optimization-baseline-manifest.json tools/tests/test_project_optimization_baseline.py
git diff --cached --name-only
git commit -m "docs: freeze project optimization baseline v1"
$finalCandidateSha = (git rev-parse HEAD).Trim()
```

Expected: the staged list contains the approval JSON and only the two timing-related files when timing actually changed; `data/` is absent. The resulting `$finalCandidateSha` is the candidate used by every completion gate below. The approval JSON continues to reference the earlier calibration run through `measurement_source_sha`, eliminating a self-referential commit cycle.

- [ ] **Step 8: Recollect final completion evidence on the one final candidate SHA**

```powershell
$finalEvidence = Join-Path $env:TEMP ("clsen-stage0-final-" + [guid]::NewGuid().ToString("N"))
New-Item -ItemType Directory -Path $finalEvidence | Out-Null
pwsh -NoProfile -File scripts/run-project-optimization-baseline.ps1 -Mode Collect -SourceSha $finalCandidateSha -PythonExecutable D:\CLSEN_Data_Web\.venv\Scripts\python.exe -EvidenceRoot $finalEvidence
```

Expected: the new run remeasures every scenario against the already-approved ceilings, verifies the approval record digest, and passes on `$finalCandidateSha`; it does not change or overwrite the approval record. This final run—not the calibration run—is the same-SHA completion evidence.

- [ ] **Step 9: Run the complete same-SHA verification matrix again without retries**

```powershell
pwsh -NoProfile -File scripts/run-ci-profile.ps1 -Profile ubuntu-full
pwsh -NoProfile -File scripts/run-ci-profile.ps1 -Profile windows-smoke
pwsh -NoProfile -File scripts/run-ci-profile.ps1 -Profile frontend-full
pwsh -NoProfile -File scripts/run-ci-profile.ps1 -Profile mysql-compatibility -MySqlVersion 8.0
pwsh -NoProfile -File scripts/run-ci-profile.ps1 -Profile mysql-compatibility -MySqlVersion 8.4
pwsh -NoProfile -File scripts/generate-api-client.ps1 -Check
```

Expected: all PASS at `$finalCandidateSha`; no unexplained skip/xfail/retry. Results from the earlier measurement SHA are calibration evidence only and cannot substitute for this completion matrix.

- [ ] **Step 10: Run plan-specific validation and repository hygiene checks**

```powershell
& D:\CLSEN_Data_Web\.venv\Scripts\python.exe -m pytest tools/tests/test_project_optimization_baseline.py backend/tests/contracts/test_project_optimization_baseline_contract.py backend/tests/contracts/test_project_optimization_baseline_runner.py -q
git diff --check
git status --short
git diff --name-only
git diff --cached --name-only
```

Expected: tests PASS; `git diff --check` has no output; no raw evidence, `data/`, credentials, backups, generated database files or unrelated user changes appear in diff/index. HEAD remains `$finalCandidateSha`.

- [ ] **Step 11: Produce the stage 0 completion statement**

The completion statement must list: final source SHA/tree, manifest link, operations guide link, approval record link, external evidence run ID and digest (not its machine-specific path), MySQL 8.0/8.4 versions, every quality profile result, OpenAPI drift result, 14 hosted MySQL exclusions, every scenario budget, approved H/S/O/R and O+R, unexplained skip/xfail/retry counts, and owner/rollback roles. Do not claim stages 1–5 are implemented.

---

## Completion Definition

Stage 0 is complete only when every item below is true:

- The manifest is strict, versioned, tested, and traceable to all 9 current API/Worker launch identities.
- The manifest covers all 18 React route identities, redirects, login/session/site/error/offline/permission/feature branches, all three roles, and explicit applicable/not-applicable visual states.
- The manifest preserves the native states and current recovery limitations of `publication_outbox`, `return_dedup`, `catalog_import`, and `catalog_export` without pretending they share one queue protocol.
- The current 14 hosted MySQL exclusions are an exact audited map; batch review/outbox coverage is not overstated.
- All raw evidence is synthetic, outside the repository, bound to one clean SHA/tree/environment, and uses 3 warmups × 20 samples × 3 independent rounds for each new scenario.
- Existing `analytics_scale_v1` evidence remains authoritative for its narrow product-catalog scope.
- API startup/readiness, maintenance API, four queue queries, idle Worker pass, heartbeat update/long task/write barrier, four UI interactions and frontend bundle are measured independently.
- Every scenario stores raw samples, p50/p95/max, variance/spread and an explicitly approved absolute ceiling.
- H/S/O/R is approved after the database, long-task and maintenance-barrier trials; `S >= 3H`, `O > S`, and `O + R` is stored.
- ubuntu-full, windows-smoke, frontend-full, MySQL 8.0, MySQL 8.4, OpenAPI no-drift and stage-specific tests all pass on the same candidate SHA.
- There are zero unexplained skips, xfails, retries or flaky-success results.
- The immutable approval record exists, cites explicit project-owner approval, and cannot be overwritten.
- No business schema, production migration, runtime framework, UI dependency, application behavior, real data or `data/` content changed.

## Plan Self-Review Record

- **Spec coverage:** Tasks 1–2 cover entrance/route/queue/CI inventory; Tasks 3–6 cover evidence identity, repeatability, performance scenarios, H/S/O/R, quality profiles and same-SHA orchestration; Tasks 7–8 cover responsibilities, rollback, approval and completion evidence. All Stage 0 deliverables and validation gates in section 5.1 of the approved roadmap map to at least one task.
- **Placeholder scan:** Every implementation action names its file, interface, command, expected result and concrete code shape. Runtime measurements are intentionally generated values, with exact collection, proposal and approval algorithms rather than guessed constants.
- **Type consistency:** `BaselineContractError`, loader/statistics/evidence functions, `SamplingProtocol`, `ScenarioResult`, `UiScenarioId`, JSON filenames, environment variables, suite name and runner modes use one spelling throughout.
- **Boundary check:** Tasks 1–8 add only documentation, contracts, synthetic fixtures and read-only/disposable-test measurement tooling. No stage 1–5 implementation is authorized.
