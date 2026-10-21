# 项目优化阶段 0 基线运行手册

本手册只定义阶段 0 的可复现基线采集、人工批准和回退。它不授权生产发布、业务数据读取、真实数据处理或业务表写入。

## 权限与数据边界

只允许可丢弃 MySQL 测试库和仓库合成数据夹具；不得读取 data/、真实客户数据、凭据或备份。

证据根目录必须是仓库外的真实目录，且每次 `Validate` 或 `Collect` 都必须为空。原始 evidence（原始样本、命令流、浏览器报告和运行摘要）留在该仓库外目录，不提交到 Git。运行器只允许其自有的测试库测量；不得对业务表或真实库进行任何写入。

## 创建一次性仓库外证据根目录

```powershell
$baselineEvidence = Join-Path $env:TEMP ("clsen-stage0-" + [guid]::NewGuid().ToString("N"))
New-Item -ItemType Directory -Path $baselineEvidence | Out-Null
$env:APP_PROJECT_OPTIMIZATION_EVIDENCE_ROOT = $baselineEvidence
```

不要把该目录改为仓库内目录、链接或共享的历史目录。一次采集只使用一个全新的证据根目录。

## 预检

在已提交且干净的候选 SHA 上执行；`$sourceSha` 必须是本次采集、复核和冻结的同一个完整 40 位 SHA。

```powershell
$sourceSha = (git rev-parse HEAD).Trim()
pwsh -NoProfile -File scripts/run-project-optimization-baseline.ps1 -Mode Validate -SourceSha $sourceSha -PythonExecutable D:\CLSEN_Data_Web\.venv\Scripts\python.exe -EvidenceRoot $env:APP_PROJECT_OPTIMIZATION_EVIDENCE_ROOT
```

预检验证 manifest、Docker/MySQL 8.0 与 MySQL 8.4 映像、Node、pnpm、Chromium，以及两份受控的外部合成规模证据。缺失输入或环境不匹配是失败，不是 skip。

## CLI 合同

`tools/project_optimization_baseline.py --help` 的子命令是 `validate-manifest`、`prepare-run`、`summarize`、`finalize-run`、`publish-command-results`、`validate-external-evidence`、`validate-run` 和 `freeze`。日常操作只能调用本手册的 PowerShell runner；不要直接调用这些低层子命令以跳过外部目录、同 SHA、质量 profile 或冻结约束。

## 采集

```powershell
pwsh -NoProfile -File scripts/run-project-optimization-baseline.ps1 -Mode Collect -SourceSha $sourceSha -PythonExecutable D:\CLSEN_Data_Web\.venv\Scripts\python.exe -EvidenceRoot $env:APP_PROJECT_OPTIMIZATION_EVIDENCE_ROOT
```

采集为同一个 `$sourceSha` 依次生成并验证完整 evidence。采集后不得修改工作树、切换 SHA 或复用其他 SHA 的证据；任何源代码、Git tree、runner 或环境身份不一致均应重新从预检开始。运行器要求所有原始样本、命令结果和最终摘要使用同一 SHA，并在结束前执行 `validate-run`。

## 质量 profile、兼容性和结果判定

同一 SHA 必须通过 `ubuntu-full`、`windows-smoke`、`frontend-full`、OpenAPI 漂移检查、MySQL 8.0 和 MySQL 8.4 兼容性以及阶段 0 专用测量。PR 的稳定 `pr-required` 包含 Oracle MySQL 8.0；合并到 master 后的 `master-required` 在相同覆盖上增加 Oracle MySQL 8.4。两者的差异只在额外的 8.4 覆盖，不能把 PR 的 8.0 结果当作 master 的 8.4 结果。

质量 profile 和测量结果一律按同一 SHA 绑定。任何 skip、xfail、xpass、retry、rerun 或 flaky 结果都使本次基线失败；不得用重试把失败变成通过。`-ListOnly` 只列出固定 selector 与 node digest，不执行采集，适用于复核当前 `ubuntu-full` 和 `windows-smoke` fixture 身份：

```powershell
pwsh -NoProfile -File scripts/run-ci-profile.ps1 -Profile ubuntu-full -PythonExecutable D:\CLSEN_Data_Web\.venv\Scripts\python.exe -ListOnly
pwsh -NoProfile -File scripts/run-ci-profile.ps1 -Profile windows-smoke -PythonExecutable D:\CLSEN_Data_Web\.venv\Scripts\python.exe -ListOnly
```

### Hosted MySQL 的 14 个排除项

`14 个排除项` 只描述既有 hosted compatibility 工作流未采集的范围，绝不代表通过、跳过批准或可从其他 profile 删除。排除项及理由由 `scripts/ci-suite-manifest.json` 固定：

1. `backend/tests/integration/test_admin_cli.py` — 此优化前未由批准的 hosted workflow 收集。
2. `backend/tests/integration/test_backup_write_barrier.py` — 由 release backup/restore gate 覆盖。
3. `backend/tests/integration/test_batch_review_repository.py` — 此优化前未由批准的 hosted workflow 收集。
4. `backend/tests/integration/test_batch_review_version_filter.py` — 此优化前未由批准的 hosted workflow 收集。
5. `backend/tests/integration/test_batch_review_workflow.py` — 此优化前未由批准的 hosted workflow 收集。
6. `backend/tests/integration/test_batch_reviews_api.py` — 此优化前未由批准的 hosted workflow 收集。
7. `backend/tests/integration/test_file_ingest.py` — 此优化前未由批准的 hosted workflow 收集。
8. `backend/tests/integration/test_outbox_worker.py` — 此优化前未由批准的 hosted workflow 收集。
9. `backend/tests/integration/test_parse_workflow.py` — 此优化前未由批准的 hosted workflow 收集。
10. `backend/tests/integration/test_published_detail_export.py` — 此优化前未由批准的 hosted workflow 收集。
11. `backend/tests/integration/test_published_detail_queries.py` — 此优化前未由批准的 hosted workflow 收集。
12. `backend/tests/integration/test_published_detail_scope.py` — 此优化前未由批准的 hosted workflow 收集。
13. `backend/tests/integration/test_workbench_import_orchestration.py` — 此优化前未由批准的 hosted workflow 收集。
14. `backend/tests/integration/test_workbench_snapshots.py` — 此优化前未由批准的 hosted workflow 收集。

## 人工复核与冻结

先核对环境指纹、三轮原始样本、p50/p95/max、20% 绝对上限建议、H=10/S=30/O=60/R=15 和 O+R=75，再由项目负责人明确批准。批准前不得运行 Freeze。这里的 Freeze 指会写入批准记录的完成冻结，不包括下文的只读预览。

这里的“Freeze”是两步协议：下面的预览会验证唯一的完整 run、显示 run-bound 的不可变 `Approval token` 和建议预算，且**不写入**批准记录；`ApprovedBy` 与 `ApprovalReference` 本身不能自动冻结。项目负责人批准后，完成命令必须回填预览中完全匹配的 run ID 和 token、明确的负责人身份与批准引用、全部四个时间值，并且二选一地接受建议预算或提供完整预算覆盖。

### 安全预览（只读）

预览使用当前证据根目录中唯一完成的 run；不要添加 `-CompleteFreeze`。预览显示精确的已验证场景/时间表：每个场景的 p50/p95/max、建议上限和单位，以及包括 H=10、S=30、O=60、R=15 四个时间值的候选时间。项目负责人必须复核此精确表、run ID 和 `Approval token`，再决定接受建议预算或批准完整预算覆盖：

```powershell
pwsh -NoProfile -File scripts/run-project-optimization-baseline.ps1 -Mode Freeze -SourceSha $sourceSha -PythonExecutable D:\CLSEN_Data_Web\.venv\Scripts\python.exe -EvidenceRoot $env:APP_PROJECT_OPTIMIZATION_EVIDENCE_ROOT
```

记录输出的 `Approval token` 与 run ID。预览只显示候选值，不写 `project-optimization-baseline-approval-v1.json`。

### 项目负责人批准后的完成冻结

以下示例显式接受预览的建议预算；方括号值必须替换为刚才预览显示的精确值和实际批准身份/引用。四个时间输入必须与预览中已复核的精确表完全匹配；`-ApprovedRunId` 和 `-ApprovedToken` 也必须完全匹配该表对应的预览。该命令才会写入 `docs/operations/project-optimization-baseline-approval-v1.json`，并且文件已存在时不会覆盖。

```powershell
$approvedRunId = "<preview run ID>"
$approvedToken = "<preview Approval token>"
$approvedBy = "<project owner identity>"
$approvalReference = "<approval ticket or recorded decision>"
pwsh -NoProfile -File scripts/run-project-optimization-baseline.ps1 -Mode Freeze -CompleteFreeze -SourceSha $sourceSha -PythonExecutable D:\CLSEN_Data_Web\.venv\Scripts\python.exe -EvidenceRoot $env:APP_PROJECT_OPTIMIZATION_EVIDENCE_ROOT -ApprovedRunId $approvedRunId -ApprovedToken $approvedToken -ApprovedBy $approvedBy -ApprovalReference $approvalReference -HeartbeatSeconds 10 -StaleSeconds 30 -OfflineSeconds 60 -RefreshSeconds 15 -AcceptProposedBudgets
```

如不接受建议预算，用一个包含所有场景完整覆盖的绝对路径替换 `-AcceptProposedBudgets`：`-BudgetOverridesPath <absolute complete-overrides.json>`。完整覆盖必须逐项对应预览中已复核的精确场景表，并由项目负责人明确批准；不得同时给出两者，也不得只给部分时间值或部分预算。token 绑定 run ID、SHA、环境摘要、evidence digest、候选时间和场景结果；任何一项改变都必须重新预览并重新取得项目负责人批准。

## evidence digest 复核

运行器的 `validate-run` 复核 `run-summary.json` 中的规范化 `evidence_digest`；它不是文件自身的 SHA-256 值。使用 `Get-FileHash -Algorithm SHA256` 复核单个原始 evidence 文件的字节摘要，并把结果与 `run-summary.json` 的相应 `scenario_evidence_digests` 项比较：

```powershell
$runDirectory = Get-ChildItem -LiteralPath $baselineEvidence -Directory -Filter "stage0-*" | Select-Object -First 1
$scenarioEvidence = Get-ChildItem -LiteralPath $runDirectory.FullName -File -Filter "scenario-*.json" | Select-Object -First 1
Get-FileHash -Algorithm SHA256 -LiteralPath $scenarioEvidence.FullName
```

随后以同一 `$sourceSha` 运行 `validate-run`（或再次运行不含 `-CompleteFreeze` 的 Freeze 预览）验证汇总 `evidence_digest`、环境摘要、场景摘要和 token 绑定；不要把 Get-FileHash 的文件摘要误当作 `evidence_digest` 本身。

## 环境变化与 v2

CPU、内存、OS、Python、Node、Chromium、MySQL、数据夹具或构建参数变化时创建 approval-v2；不得覆盖 v1。

新版本必须在新的仓库外证据根目录上重新预检、采集、复核和批准，且仍遵守同 SHA 规则。已有批准 JSON 和原始外部 evidence 都是历史记录，不得改写以伪造新环境结果。

## 负责人和回退责任

| 角色 | 基线职责 | 回退职责 |
| --- | --- | --- |
| `project_owner` | 复核完整同 SHA 摘要并作出明确批准。 | 批准阶段 0 回退，并决定是否以新 SHA/new approval-v2 重建。 |
| `backend_maintainer` | 维护后端 profile、API/队列测量和可复现测试。 | 回退其后端 runner/采集器提交，证明只影响测试库。 |
| `frontend_maintainer` | 维护 `frontend-full`、浏览器和 bundle 测量。 | 回退其前端基线提交并重新运行受影响 profile。 |
| `database_operator` | 只允许隔离 MySQL 测试库，核对 MySQL 8.0/8.4 和数据边界。 | 确认没有业务表变更；清理由 runner 所有的可丢弃测试资源。 |
| `change_author` | 将变更拆为可独立审查和回退的提交。 | 执行授权的阶段提交回退，保留批准 JSON 和仓库外历史 evidence。 |

阶段 0 的回退由 `change_author` 执行、`project_owner` 批准、`database_operator` 复核数据库边界；后续阶段分别由其变更作者执行、对应维护者验证、项目负责人批准。任何阶段都不得以“回退”为由覆盖批准记录、重写原始 evidence、修改业务表或触碰 `data/`。

## 回退

阶段 0 只增加清单、测试、只读/测试库测量和文档。回退时按独立提交删除 runner 或采集器，保留已批准 JSON 作为历史证据；不得借回退修改业务表或 data/。
