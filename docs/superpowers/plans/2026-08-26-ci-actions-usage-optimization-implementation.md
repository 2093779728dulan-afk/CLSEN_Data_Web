# GitHub Actions 用量优化实施计划

> **For agentic workers:** 按 Task 顺序执行；每个 Task 必须遵循 Red → 最小实现 → 聚焦验证 → 边界核验。开始实施时使用 `executing-plans` 技能。未经对应暂停门授权，不得 push、创建 PR、修改分支保护或运行发布门。

**Goal:** 在不减少已批准 Ubuntu、前端和 hosted MySQL compatibility 节点覆盖的前提下，消除功能分支 push/PR 双事件、重复 offline suite 和过期运行，把单次 PR 更新从约 97 未加权 runner-minutes 降到不超过 30，并让本地、hosted 与 release workflow 共用同一 canonical suite 定义。

**Architecture:** 新增版本化 suite manifest 和单一 PowerShell profile runner。`pull_request` 执行 Ubuntu full、Windows smoke、frontend full 与 MySQL 8.0；`master` 额外执行 MySQL 8.4；manual release 先验证精确 SHA 的 `master-required`，再只运行 release-only 门。所有汇总门 fail-closed，私有输入缩小到使用它的 step。

**Approved design:** `docs/superpowers/specs/2026-08-26-ci-actions-usage-optimization-design.md`，用户于 2026-08-26 分节批准架构、执行流、安全边界与验收标准，并完成书面规格复核。

**Baseline:** `master` 合并提交 `51beb33482eb0174a796a549bec8e6f98df69d2f` 的 GitHub Actions run `32944715482` 为成功基线：约 22 分 36 秒墙钟、约 50.73 未加权 runner-minutes。同一候选 SHA `e37cf2d` 的 push/PR 两次成功运行合计约 96.87 未加权 runner-minutes。官方 billing/usage 导出如可用，仅作为单独标注操作系统倍率的第二口径旁证。

**Execution status:** 未实施。本文只定义任务、暂停门与验收证据。

## Global Constraints

- 不修改业务 API、数据库 schema、产品流量或生产数据。
- 功能分支 push 不运行 compatibility；pull request 运行 MySQL 8.0；`master` 运行 MySQL 8.0/8.4。
- Ubuntu offline 必须包含全部优化前 node IDs；本计划新增 contract nodes 只能来自显式 allowlist。frontend full 的固定命令集合不得减少；pull request MySQL 8.0 与 `master` 双版本 compatibility node IDs 必须精确等于批准基线。
- Windows 只缩减到批准的跨平台 smoke 清单，不得临时再缩小以达成用量目标。
- 本轮不做 changed-path gating，不增加 MySQL 并行 shard，不以更多 runner 换取更短墙钟。
- MySQL runner 必须使用随机、runner-owned、名称匹配 `clsen_data_test*` 的 disposable 数据库；禁止连接业务库。
- performance、canary、restore、live 与 deployment verification 仍是 release-only 必需门；不能以已有普通 CI 代替。
- 私有 URL、密码、CSV、baseline 内容和完整业务标识不得写入仓库、日志或 artifact。
- release 敏感名称只能存在于 `clsen-release-gates` environment secrets；同名 repository/organization secret 或 self-hosted runner Process/User/Machine 继承变量均为硬阻断。专用 runner group 必须只允许 `release-gates.yml@refs/heads/master`；不支持该限制时 runner 保持离线且不挂载私有 corpus，等待单独批准替代方案。
- workflow 契约必须解析 YAML 结构。若引入 PyYAML，只能使用 `BaseLoader` 或禁用 YAML 1.1 布尔隐式解析，避免把顶层 `on` 解析为布尔值。
- 当前未跟踪 `data/` 属于本地运行数据，不得 add、清理、移动或改写。
- 未经用户另行授权，不 push、不创建/更新 PR、不修改 GitHub 分支保护、不执行 manual release workflow。
- 每次提交只包含本计划路径；提交前执行 `git diff --check`、staged path allowlist 和秘密扫描。

## Planned File Set

### Create

- `scripts/ci-suite-manifest.json`
- `scripts/CiSuiteManifest.psm1`
- `scripts/DatabaseContract.psm1`
- `scripts/run-ci-profile.ps1`
- `scripts/verify-release-source.ps1`
- `backend/tests/contracts/test_ci_suite_manifest.py`
- `backend/tests/contracts/test_release_evidence_contract.py`
- `backend/tests/fixtures/ci/offline-backend-nodeids.txt`
- `backend/tests/fixtures/ci/mysql-compatibility-nodeids.txt`
- `backend/tests/fixtures/ci/windows-smoke-nodeids.txt`

### Modify

- `.github/workflows/compatibility.yml`
- `.github/workflows/release-gates.yml`
- `scripts/test-mysql-matrix.ps1`
- `scripts/init-database.ps1`
- `scripts/sync-test-runtime-grants.ps1`
- `scripts/run-product-catalog-mysql-tests.ps1`
- `scripts/run-product-catalog-backup-restore.ps1`
- `scripts/run-product-catalog-performance.ps1`
- `scripts/run-product-catalog-canary.ps1`
- `backend/pyproject.toml`
- `backend/requirements.in`
- `backend/requirements.lock`
- `backend/tests/contracts/test_server_deployment.py`
- `backend/tests/contracts/test_database_bootstrap_script.py`
- `backend/tests/contracts/test_maintenance_scripts.py`
- `backend/tests/contracts/test_schema_revision_contract.py`
- `backend/tests/contracts/test_test_grant_sync_script.py`
- `backend/tests/integration/test_real_csv_regression.py`
- `backend/tests/integration/test_product_catalog_canary.py`
- `backend/tests/performance/product_catalog_scale_fixture.py`
- `backend/tests/performance/test_product_catalog_performance.py`
- `docs/operations/product-catalog-rollout.md`
- `docs/operations/local-maintenance.md`

文件集合如需变化，先更新本文并取得用户确认；不得把无关格式化或既有 `data/` 内容纳入提交。

## Task 0: 冻结基线、分支和 touched paths

**Produces:** 可复查的测试节点、workflow/job 耗时和文件边界；不改运行逻辑。

- [ ] **Step 1: 确认起点**

  ```powershell
  git status --short --branch
  git rev-parse HEAD
  git rev-parse origin/master
  gh run view 32944715482 --json status,conclusion,headSha,jobs,url
  ```

  Expected: 设计与计划提交可追溯，`data/` 是唯一既有未跟踪目录；若远端 `master` 已前进，先重新计算 merge-base 和 CI 基线，不覆盖新提交。

- [ ] **Step 2: 创建实现分支**

  使用 `codex/ci-actions-usage-optimization`。不得在 `master` 直接修改 workflow。创建分支本身只在用户授权实施后进行。

- [ ] **Step 3: 保存批准节点基线**

  在优化前 SHA 上运行 `--collect-only -q`：Ubuntu offline 与 MySQL compatibility 使用当前 hosted workflow 的精确 pytest 参数；Windows smoke 使用批准设计第 5 节的六类路径，而不是当前 Windows 的完整 offline 参数。规范化为仓库相对 node ID、排序、去重并检查无秘密。fixture 必须记录 source SHA 和生成命令注释，不能记录数据库 URL。MySQL fixture 是最终精确集合；Ubuntu/Windows fixture 是必须保留的基线子集，因为 Task 1 会在批准的 `backend/tests/contracts/` 路径中新增合同节点。

- [ ] **Step 4: 保存用量基线**

  通过 GitHub API 记录 runs `32944715482`、`32938758333`、`32938756579` 的 event、SHA、job started/completed 时间和结论，只保存汇总值：双事件 96.87 未加权 runner-minutes、master 50.73 未加权 runner-minutes、关键 job/step 耗时。若官方 billing/usage 导出可用，另存带操作系统倍率的汇总值，不能混入主验收口径。

## Task 1: 建立结构化 workflow 与 manifest Red 合同

**Files:** requirements、workflow contract tests、`test_ci_suite_manifest.py`、node ID fixtures。

**Produces:** 在旧 workflow/runner 上确定性失败的契约测试。

- [ ] **Step 1: 为结构化 YAML 测试加入锁定依赖**

  在 `backend/requirements.in` 与 `backend/pyproject.toml` 的 dev extras 同步增加约束的 PyYAML 6.x，并用项目锁定流程重建 `requirements.lock`。测试加载 workflow 时使用 `yaml.BaseLoader`，显式断言顶层 `on` 保持字符串键。

- [ ] **Step 2: 写触发与 concurrency Red 测试**

  解析 `.github/workflows/compatibility.yml` 并断言：

  - `push.branches` 精确为 `master`；
  - 存在 `pull_request`；
  - PR concurrency 使用 `application-compatibility-pr-` + PR number 且会 cancel；
  - master concurrency 使用互异的 `application-compatibility-master-` + 完整 SHA 且不会 cancel，连续 push 不会替换 pending 的旧 SHA；
  - 存在稳定 `pr-required` 与 `master-required`；
  - PR 的 required 依赖不含 MySQL 8.4，master 的依赖包含它；
  - 任一必需依赖非 success 时汇总脚本返回失败。

  Expected: 旧 workflow 因监听所有 push、无 concurrency/汇总门而 FAIL。

- [ ] **Step 3: 写 canonical runner Red 测试**

  断言两个 workflow 只通过 `run-ci-profile.ps1` 选择 profile，不含 `python -m pytest tests/integration/...` 长清单。断言 `mysql-compatibility` 不可选择子集且不隐式运行 `tests -m "not mysql"`；release-only 只能按 allowlisted `-ReleaseSuite` 分 step 调用且不运行普通 regression。结构化合同还必须证明 PR/master/release concurrency 使用互异固定前缀，release group 为 `product-catalog-release-` + 完整 `source_sha` 且 `cancel-in-progress: false`。

  Expected: 旧 workflow 和 matrix runner FAIL。

- [ ] **Step 4: 写 manifest 完整性 Red 测试**

  `test_ci_suite_manifest.py` 先要求 manifest：

  - 顶层键精确为 `schema_version`、`profiles`、`mysql_suites`、`mysql_exclusions`、`windows_smoke` 与 `release_suites`；
  - 每个路径存在、位于仓库内、无重复；
  - 每个 mysql-marked 模块恰好分类为 migrations/legacy/p0、一个 release-only suite，或带非空理由的优化前 exclusion；新增 marker 模块不能默认进入 exclusion；
  - compatibility collect node IDs 与批准 fixture 相等；
  - Ubuntu/Windows 保留全部优化前 fixture nodes，新增 nodes 只能匹配本计划 contract allowlist，且 Windows 路径边界精确等于批准六类范围；
  - profile 不接受未知 suite、版本或参数。

  Expected: manifest/runner 尚不存在，测试 FAIL。

- [ ] **Step 5: 写秘密作用域与 release provenance Red 测试**

  结构化断言 canary 与 performance evidence 不在 job env，旧 `APP_PLAN_BASELINE_ROOT` 不再进入 release workflow；release 有 `source_sha` input，并拆成 GitHub-hosted、无 environment/secret 的 trusted `provenance` job 与后续 self-hosted gate job。前者独占 `actions: read`，从 API 取得并明确 checkout 远端 master 后执行 verifier，把 `github.ref/workflow_sha` 只当待验证数据，并要求输入 SHA、远端 master、workflow ID/event/branch 与 `master-required` 全部一致；后者仅 `contents: read`，必须先通过 master-only environment policy 才分配 runner，依赖其输出后 checkout，秘密只存在于对应 release-suite step。断言 APP/VITE source 在同一 live release step 成对设置为 `p0_catalog`。

- [ ] **Step 6: 执行并保存 Red 证据**

  ```powershell
  .\.venv\Scripts\python.exe -m pytest backend/tests/contracts/test_ci_suite_manifest.py backend/tests/contracts/test_server_deployment.py backend/tests/contracts/test_database_bootstrap_script.py backend/tests/contracts/test_schema_revision_contract.py -q
  ```

  Expected: 旧 workflow 因事件、concurrency、内联清单、job-scoped secrets、单 job provenance 以及缺失 manifest/profile runner 而确定性 FAIL。记录失败测试名称；不得在 Red 尚未运行时开始 Green。

## Task 2: 实现 suite manifest、共享模块和 profile runner

**Files:** `ci-suite-manifest.json`、`CiSuiteManifest.psm1`、`DatabaseContract.psm1`、`run-ci-profile.ps1`、数据库 bootstrap/grant scripts 与相关 contracts。

- [ ] **Step 1: 实现严格 manifest schema**

  JSON 使用 schema version `1`，顶层精确包含 `schema_version`、`profiles`、`mysql_suites`、`mysql_exclusions`、`windows_smoke` 与 `release_suites`。模块必须拒绝重复 JSON key、未知键、绝对路径、`..`、不存在路径、空 suite、无理由 exclusion 和未批准 MySQL 版本。`mysql-compatibility` 固定按 migrations → legacy → p0 展开，调用方不能删减、重排或混入 release selector。

- [ ] **Step 2: 填入批准分类**

  将旧 hosted compatibility 节点映射到 migrations/legacy/p0，精确保留 `test_product_catalog_permissions.py`；performance、canary、纯 backup/restore、live 和 disposable deployment selector 映射到 release-only。优化前未被任何批准 runner 收集的 mysql-marked 模块逐项进入带理由 exclusion，不得借此移除 fixture 中的节点。Windows 路径严格使用设计规格第 5 节六类范围；Ubuntu/Windows 新增 node allowlist 只包含本计划合同测试。

- [ ] **Step 3: 提取共享数据库 contract 模块**

  把三个脚本重复的 schema revision 读取与严格 privilege-manifest 加载收敛到 `DatabaseContract.psm1`；`init-database.ps1`、`sync-test-runtime-grants.ps1` 和 `test-mysql-matrix.ps1` 只调用同一导出函数。先用现有 bootstrap/schema/grant contracts 证明重复实现仍被识别，再做最小替换；不改变权限集合或数据库安全规则。

- [ ] **Step 4: 实现 `run-ci-profile.ps1`**

  接口至少包含：

  ```powershell
  .\scripts\run-ci-profile.ps1 -Profile ubuntu-full -PythonExecutable <python>
  .\scripts\run-ci-profile.ps1 -Profile windows-smoke -PythonExecutable <python>
  .\scripts\run-ci-profile.ps1 -Profile frontend-full
  .\scripts\run-ci-profile.ps1 -Profile mysql-compatibility -MySqlVersion 8.0 -PythonExecutable <python>
  .\scripts\run-ci-profile.ps1 -Profile release-only -ReleaseSuite performance -SourceSha <sha> -PythonExecutable <python>
  .\scripts\run-ci-profile.ps1 -Profile release-only -ReleaseSuite canary -SourceSha <sha> -PythonExecutable <python>
  .\scripts\run-ci-profile.ps1 -Profile release-only -ReleaseSuite canary -SourceSha <sha> -PythonExecutable <python> -ValidateOnly
  .\scripts\run-ci-profile.ps1 -Profile windows-smoke -ListOnly
  ```

  `-PythonExecutable` 必须解析为现有文件，并验证 Python 3.14 与锁定依赖可导入；hosted workflow 显式传入 setup-python 暴露的解释器，本地默认值只能在同样验证后使用。每个 release suite 必须实现无副作用 `-ValidateOnly`。`-ListOnly` 输出 allowlisted profile、suite、版本、node count、排序 node-ID digest 与 baseline comparison，不输出完整环境或秘密；任何不允许的新增/缺失、未知参数或缺少必需输入均 fail-closed。

- [ ] **Step 5: 聚焦验证**

  ```powershell
  .\.venv\Scripts\python.exe -m pytest backend/tests/contracts/test_ci_suite_manifest.py backend/tests/contracts/test_server_deployment.py backend/tests/contracts/test_database_bootstrap_script.py backend/tests/contracts/test_schema_revision_contract.py backend/tests/contracts/test_test_grant_sync_script.py -q
  .\scripts\run-ci-profile.ps1 -Profile windows-smoke -PythonExecutable .\.venv\Scripts\python.exe -ListOnly
  .\scripts\run-ci-profile.ps1 -Profile mysql-compatibility -MySqlVersion 8.0 -PythonExecutable .\.venv\Scripts\python.exe -ListOnly
  ```

## Task 3: 把 MySQL matrix 收敛为纯数据库 runner

**Files:** `test-mysql-matrix.ps1`、`run-product-catalog-mysql-tests.ps1`、`run-product-catalog-backup-restore.ps1`、`run-product-catalog-performance.ps1`、manifest/maintenance/grant contracts。

- [ ] **Step 1: 写 runner Red 合同**

  断言 matrix 缺 suite 时拒绝，不存在默认 offline 执行路径；所有调用者必须显式给 allowlisted suite，且必须传入或解析出已验证的 Python 3.14 解释器。断言两版本、随机数据库、TLS、三身份、grant 和 label-bound cleanup 仍存在；用合成 adapter 注入测试、grant 与 cleanup failure，证明任一失败均返回非零且 cleanup failure 不会被原始成功状态吞掉。先实际运行这些 Red tests 并保存旧 runner 的预期失败名称。

- [ ] **Step 2: 删除 matrix 内 offline 副本**

  移除 `$PytestPaths.Count -eq 0` 时执行完整 offline suite 的行为和任意路径入口。将接口改为 `-Suites` 必填，由 shared module 展开受控 selector；`-PythonExecutable` 经版本、路径和依赖校验后用于所有 pytest/alembic 调用。

- [ ] **Step 3: 统一迁移与 suite 顺序**

  每个版本只 bootstrap 一次：migration tests/upgrade → revision check → least-privilege grants → legacy/P0 suite。保持同一版本内串行，避免增加 runner 用量。

- [ ] **Step 4: 更新全部调用者**

  `run-product-catalog-mysql-tests.ps1`、profile runner、performance 和 backup/restore runner 只传 suite name；`rg "test-mysql-matrix"` 的每个生产调用都必须有显式 suite 与 Python 入口。backup/restore 只运行纯 restore selector，不再重复属于 `mysql-p0` compatibility 的 `test_product_catalog_permissions.py`。

- [ ] **Step 5: disposable MySQL 聚焦验证**

  在本地 Oracle MySQL 8.0 先跑完整 compatibility；8.4 在 Docker 可用时同样跑。记录 node count 与 fixture 相等，且日志中 offline suite 次数为零。

## Task 4: 重写 compatibility workflow

**Files:** `.github/workflows/compatibility.yml`、结构化 contracts。

- [ ] **Step 1: 收窄事件**

  `push` 仅允许 `master`，保留 `pull_request`。PR concurrency group 使用 `application-compatibility-pr-` + PR number 且 cancel true；master group 使用互异的 `application-compatibility-master-` + 完整 `github.sha` 且 cancel false，避免跨 workflow 碰撞或第三个连续 push 替换仍 pending 的旧 master run。

- [ ] **Step 2: 建立四类执行 job**

  Ubuntu、Windows、frontend 和 MySQL job 只调用 profile runner。所有 Python profile 显式传入 setup-python 的解释器。PR 固定 MySQL 8.0；MySQL 8.4 job 仅在 master push 执行。保留 pip/pnpm cache，不新增浏览器或 venv cache。

- [ ] **Step 3: 建立汇总门**

  `pr-required` 和 `master-required` 使用固定 job name、`needs` 与 `if: always()`；仅允许事件设计导致的预期 skip，其他非 success 均失败。汇总门自身不读取秘密、不 checkout、不运行测试。用本地结构化合同枚举 `failure/cancelled/skipped` 的合成 `needs` 结果并证明全部 fail-closed，不为此制造 hosted 失败提交。

- [ ] **Step 4: 验证 YAML 与 contracts**

  ```powershell
  .\.venv\Scripts\python.exe -m pytest backend/tests/contracts/test_ci_suite_manifest.py backend/tests/contracts/test_server_deployment.py -q
  .\.venv\Scripts\python.exe -c "from pathlib import Path; import yaml; yaml.load(Path('.github/workflows/compatibility.yml').read_text(encoding='utf-8'), Loader=yaml.BaseLoader)"
  ```

## Task 5: 收窄 release workflow、provenance 与性能证据

**Files:** release workflow、`verify-release-source.ps1`、profile/canary runners、performance producer/consumer、`test_release_evidence_contract.py`、runbooks 与相关 contracts。

- [ ] **Step 1: 写 trusted provenance Red 合同**

  先为 `verify-release-source.ps1` 与结构化 workflow 写失败测试，使用合成 GitHub JSON/adapter 覆盖：dispatch ref 非 master、workflow SHA 与输入 SHA 不同、非当前 master tip、错误 workflow ID/event/branch/head SHA、缺 run、run 未完成、conclusion 非 success、缺 `master-required`、分页不完整、结果歧义和 API 失败。测试还必须证明 provenance 在 GitHub-hosted runner 上从 API 取得并 checkout 明确的远端 master 后执行 verifier，`github.workflow_sha` 只作为待验证输入；provenance job 不绑定 environment/secret 且独占 `actions: read`，self-hosted gate job 只有 `contents: read`。实际运行 Red 并记录失败名称。

- [ ] **Step 2: 实现 verifier 并拆分 manual workflow**

  `verify-release-source.ps1` 接受 dispatch ref、workflow SHA、source SHA、repository、固定 workflow ID 与 run/check adapter；只输出规范化的已验证 40 位 SHA。workflow 增加必填 `source_sha`：GitHub-hosted provenance job 先通过 API 解析当前 master，明确 checkout 该 SHA 并从该 trusted checkout 运行 verifier；gate job 依赖其输出、绑定 `clsen-release-gates` environment、在 environment policy 通过后才分配 self-hosted runner，精确 checkout 已验证 SHA 并再次断言 HEAD。release concurrency group 使用完整 `source_sha` 且 `cancel-in-progress: false`，runbook 禁止重复 dispatch，并记录同 SHA pending run 可能被更新 pending run 替换的队列语义。只读核验 environment deployment branch policy 与 secret scopes；若不满足，记录为 Task 8 合并前的单独授权变更，不能在本 Task 擅自修改。

- [ ] **Step 3: 按 release suite 隔离输入和副作用**

  gate job 获批并取得 runner 后，首个无秘密 host preflight 检查全部敏感名称在 runner service 的 Process、User、Machine scope 均不存在，并重新查询远端 master 是否仍等于 verified SHA；命中只报告变量名/作用域或布尔漂移并失败，绝不输出值或自动清除。紧接着先运行 workspace-boundary，从已验证 SHA 重算 Git tree、artifact digest，要求 checkout/index/worktree clean。随后对 `performance|canary|restore|live|deployment|generated-contract` 依次运行独立 `-ValidateOnly` step；每个 validator 只接收本 suite 输入。只有所有 validation-only step 成功后，才按同一顺序运行有副作用/长时 suite step。performance 只接收两份 evidence 路径；canary 只接收 SELECT-only URL、仓库外 private manifest 路径和 corpus root；live 同时设置 APP/VITE source=`p0_catalog`。全部执行完成后再复验远端 master 与 workspace-boundary，任一漂移使整次 gate 失败。删除普通 offline/frontend/MySQL compatibility 重跑，restore suite 不重复 `test_product_catalog_permissions.py`。

  `run-product-catalog-canary.ps1` 增加显式 private manifest/corpus 参数和 release 模式外部路径强制；相关 Python tests 从经校验的环境路径读取。release 模式拒绝仓库内路径、reparse point、路径逃逸、缺失/多余 CSV、manifest hash/count 不一致，同时保留本地默认路径以兼容既有人工 canary。不得移动或修改当前工作区 `data/`；release runner 的仓库外私有副本需要单独授权准备。

- [ ] **Step 4: 写 performance evidence binding Red**

  在修改 producer 前，于 `test_release_evidence_contract.py` 增加 consumer tests，覆盖缺失或错配的 `source_sha`、`git_tree`、`artifact_digest`、`runner_digest`，以及 dirty checkout、调用方自报摘要和旧 evidence。逐项运行并确认 Red；这些测试使用小型 synthetic payload，不执行 4M fixture，新增 node 仍落在批准的 contracts smoke 路径内。

- [ ] **Step 5: 实现 performance evidence binding Green**

  producer/consumer 增加上述四个字段：`git_tree` 来自 `git rev-parse <source_sha>^{tree}`；`artifact_digest` 是规范化 UTF-8/LF 的 `git ls-tree -r --full-tree <source_sha>` 输出 SHA-256；`runner_digest` 是 manifest 固定的 performance producer、consumer 与 runner Git blob 身份清单 SHA-256。producer 和 consumer 都从精确 clean checkout 重新推导，不能接受调用方自报值，也不能把 evidence 文件自身放入循环摘要。旧 evidence 因缺字段或 digest 不匹配而 FAIL，不得自动填补。

- [ ] **Step 6: 本地 release profile 与 provenance Green 验证**

  用合成 adapter 重新运行全部 provenance 负向/正向 cases；对每个 release suite 执行 `-ListOnly` 和无秘密 synthetic preflight，证明普通 regression 次数为零、输入作用域不交叉、私有路径逃逸/仓库内路径失败、host inherited-variable 检查 fail-closed，workspace-boundary 不依赖旧 baseline。这里不 dispatch workflow，也不生成真实 4M evidence。

- [ ] **Step 7: 更新运维文档**

  说明 PR/master/release 三层门、required check 名称、trusted provenance job、step-scoped secrets、合并后 evidence 时序、未加权运行时与官方 billing 两种用量口径及失败恢复。明确通过 CI 仍不授权部署。

## Task 6: 本地全量验证与静态边界

- [ ] **Step 1: 后端与工具回归**

  ```powershell
  .\.venv\Scripts\python.exe -m pytest backend/tests -m "not mysql" -q
  .\.venv\Scripts\python.exe -m pytest tools/tests -q
  .\.venv\Scripts\python.exe -m ruff check --config backend/pyproject.toml backend/app backend/tests
  .\.venv\Scripts\python.exe -m ruff format --check --config backend/pyproject.toml backend/app backend/tests
  .\.venv\Scripts\python.exe -m mypy --config-file backend/pyproject.toml backend/app backend/tests
  ```

- [ ] **Step 2: 前端回归**

  ```powershell
  Push-Location frontend
  pnpm lint
  pnpm typecheck
  pnpm test --run
  pnpm exec playwright test
  $env:VITE_PRODUCT_ANALYTICS_SOURCE = "legacy_parser"; pnpm build
  $env:VITE_PRODUCT_ANALYTICS_SOURCE = "p0_catalog"; pnpm build
  Pop-Location
  ```

- [ ] **Step 3: profile 与 node ID 回归**

  对 ubuntu-full/windows-smoke/frontend-full/mysql-compatibility 及每个 release suite 执行 `-ListOnly`：MySQL node IDs 必须精确匹配 fixture；Ubuntu/Windows 必须包含全部优化前 fixture nodes，额外 nodes 只能来自本计划 contract allowlist，且 Windows 路径边界精确；frontend 必须列出全部批准命令。实际运行 Windows smoke 和 Ubuntu full。

- [ ] **Step 4: 文本、diff 与秘密扫描**

  ```powershell
  git diff --check
  rg -n "mysql\+pymysql://|APP_PRODUCT_CATALOG_CANARY_DATABASE_URL=.*@|password\s*=" .github scripts backend/tests docs/operations
  git status --short
  ```

  只允许计划路径和既有 `data/`。任何凭据样式命中必须人工分类并清除真实秘密后才能继续。

## Task 7: Hosted PR 验收与用量证据

**Pause gate:** 需要用户明确授权 push 实现分支和创建/更新 PR。

- [ ] **Step 1: 推送实现候选并创建 PR**

  PR 描述固定 source SHA、批准设计/计划、基线 node IDs、预期 required jobs 和不包含部署授权。

- [ ] **Step 2: 验证事件去重**

  证明分支 push 没有 compatibility run，PR 只有一组 run。若 GitHub 在旧 workflow SHA 上仍触发 push，区分旧 workflow 触发事实，不误判新 workflow。

- [ ] **Step 3: 验证 superseded cancellation**

  只做一组 cancellation 证明：复用一个真实、计划内且尚未推送的后继修正，在旧 PR run 已启动后推送，证明旧 run 被取消、新 SHA 完整运行。不得创建 no-op commit、不得人为取消新 run，也不得重复演练消耗 Actions。

- [ ] **Step 4: 验证 PR 覆盖**

  `pr-required` 成功；无 MySQL 8.4 job；MySQL 8.0 node IDs 精确等于基线；Ubuntu/Windows 满足“旧节点全保留 + 仅允许计划内合同新增”，Windows 路径边界精确；frontend 固定完整命令全部执行；MySQL 日志不含 offline suite。

- [ ] **Step 5: 计算用量**

  通过 GitHub API 汇总每个 job 的 started/completed 时间。单次最终 PR run ≤30 未加权 runner-minutes，且相对 96.87 基线降低 ≥65%。如可读取官方 billing/usage，再记录带平台倍率的旁证并与主口径分列。失败时先分析 runner/fixture，不删除测试达标。

## Task 8: 分支保护迁移、Master 与 Release 验收

**Pause gate:** 需要用户分别授权修改分支保护、合并前修正 environment/secret/runner-group/runner-host 边界、准备仓库外私有 canary 副本、合并 PR、为最终 master SHA 生成真实 4M evidence，以及运行 manual release gate。任一授权不能从其他授权推导。

- [ ] **Step 1: 合并前建立 release trust boundary**

  只读核验 `clsen-release-gates` deployment branch policy、environment/repository/organization secret 名称、runner group workflow/ref allowlist，以及目标 self-hosted runner 的敏感变量 Process/User/Machine scope。必须证明 environment 只允许 master，runner group 只允许 `.github/workflows/release-gates.yml@refs/heads/master`，canary URL/evidence/private-path 名称只存在于该 environment，runner host 没有继承同名值；敏感值本身不读取或输出。若不满足，取得各自单独授权后迁移/删除重复 secret、修正 runner group、清除主机变量并按需重启 runner service，再读回。若套餐不支持 workflow/ref allowlist，runner 必须保持离线且不挂载私有 corpus，直到替代临时 runner 流程另行获批。准备仓库外 private manifest/corpus 副本同样需要单独授权，必须校验 manifest hash/count 且不移动、清理或改写当前工作区 `data/`。任一条件未满足都禁止合并新 release workflow。

- [ ] **Step 2: 安全迁移 required check**

  先确认 PR 已产生稳定 `pr-required`，再读回 branch protection 与 rulesets。当前基线二者均不存在：经单独授权后首次创建保护并直接加入 `pr-required`，从首次启用起不得出现空窗。只有旧 required names 实际存在时才执行“先加新门并读回、再移除旧门”。保存脱敏前后配置摘要。

- [ ] **Step 3: 合并并验证 master**

  合并后 `master-required` 必须等待 MySQL 8.0/8.4 和其他三个 profile 全部成功。证明 master run 未被自动取消，两个 MySQL 版本 node IDs 与基线一致。

- [ ] **Step 4: 计算 master 用量**

  同样用 job 时间计算，目标 ≤45 未加权 runner-minutes。记录相对 run `32944715482` 的绝对和百分比变化；官方 billing/usage 如可用则另列旁证。

- [ ] **Step 5: Release fail-closed dry runs**

  只在本地使用合成 adapter 覆盖错误 ref/SHA、旧 master、错误 workflow/event/branch、缺成功 gate、API 分页/歧义、缺秘密、旧 performance evidence 和 digest 不匹配；确认 release-only 副作用次数为零。不得为每个负向 case 实际 dispatch GitHub Actions。

- [ ] **Step 6: 为最终 master SHA 生成真实 performance evidence**

  在 `master-required` 成功且用户单独授权后，锁定当前 master SHA，使用批准的 4 vCPU/8 GiB/2 GiB profile 和原 4M fixture 各生成一次 MySQL 8.0/8.4 evidence。生成前后都验证远端 master 未前进，并用 consumer 验证 source/tree/artifact/runner digest；安全保存路径，不写入仓库或日志。若 master 前进，两份 evidence 均失效，必须停止而不是复用或自动 dispatch release。

- [ ] **Step 7: 最终复核 release trust boundary**

  再次只读确认 `clsen-release-gates` 仅允许 master、runner group 仍只允许批准 workflow/ref、敏感名称只在 environment scope、仓库外 private corpus 仍匹配 manifest、runner host 没有继承敏感变量，且远端 master 仍等于 evidence source SHA。任一漂移都停止；不得在此步骤自动修复。

- [ ] **Step 8: 执行批准 SHA 的 release-only 门**

  只在用户单独授权后运行。验证 performance、current-db SELECT-only canary、encrypted restore、live E2E、deployment verification、generated contract 和 workspace boundary 全部 PASS，且普通 offline suite 次数为零。这仍不授权生产部署、tag 或流量切换。

## Completion Definition

只有同时满足以下条件才完成本计划：

1. workflow、本地和 release 只消费同一 manifest/profile runner；
2. 功能分支 push 不运行 compatibility，PR superseded run 自动取消；
3. PR required 覆盖 Ubuntu full、Windows smoke、frontend full、MySQL 8.0；
4. master required 额外覆盖 MySQL 8.4；
5. compatibility 与 release 中重复 offline 次数均为零；
6. MySQL compatibility node IDs 精确等于批准基线；Ubuntu/Windows 旧节点全部保留，额外节点仅为批准合同 allowlist，Windows 路径边界精确；
7. secrets 为 step scope，trusted provenance 与 release gate 分 job，release SHA/check/evidence 绑定 fail-closed；
8. PR ≤30 未加权 runner-minutes且降低 ≥65%，master ≤45 未加权 runner-minutes；
9. 本地回归、hosted PR/master 和经授权的 release-only 全部 PASS；
10. 若经授权启用分支保护，则从首次启用起无空窗；environment policy 与 runbook、实际 check names 一致；
11. 未修改业务数据库、未部署、未打 tag、未触及 `data/`。
