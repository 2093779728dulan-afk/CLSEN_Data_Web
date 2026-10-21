# 商品款式主档与变体趋势基础实施计划（P0）

> **For agentic workers:** REQUIRED SUB-SKILL: use `executing-plans` to execute this document task-by-task. Every task follows Red → minimal implementation → focused verification → milestone evidence. Checkboxes are the execution ledger and must not be pre-checked.

**Goal:** 在现有 CLSEN Web 应用中先建立“一款一个权威标准名称、一个款色码一个稳定 `sku_id`”的商品目录，再交付按颜色和尺码查看每日销售、退货、会话和转化趋势的产品总表与详情页，为后续生产订单、广州成品仓、海运、FBA 和 Amazon 全链路提供稳定身份基础。

**Architecture:** P0 新建独立 `catalog` 领域，复用现有 FastAPI、Cookie/CSRF/RBAC、不可变原文件存储、MySQL 事务和 React 应用，但不把商品目录塞入日报 `import_batches`，也不以旧 Seller SKU 临时解析器作为新分析的回退。实现分为三个顺序里程碑：A 完成商品主档候选、XLSX/在线审核和目录 V1；B 在保留旧 API/旧 UI 的同时完成稳定款式产品总表与颜色/尺码趋势；C 在固定事实快照上对账、演练整套切换和回滚，再通过性能、真实只读 canary、备份恢复与全量回归。每个响应只能声明一种身份来源。

**Tech stack:** Python 3.14、FastAPI、Pydantic/dataclass、SQLAlchemy Core/raw SQL、Alembic、Oracle MySQL 8.0/8.4、`openpyxl`、`defusedxml`、React 19.1.1、TypeScript 5.9.2、Vitest 3.2、Playwright 1.62、pnpm 11.16。

**Approved design:** `docs/superpowers/specs/2026-08-19-product-style-variant-analytics-foundation-design.md`，原始批准基线为 Git commit `1ead0fd952d0aba45ad2bc39fc744c1967f8d587`、SHA-256 `cab5b39b6e2cc04749a6ae7b467bc797dd7cd1d65ce47ef2ebdd028fd70019f7`；用户于 2026-08-20 书面批准原基线，并于 2026-08-20 再次书面批准 Task 1 successor SHA-256 `858cd5a165f1440e4f8e30b1abf1fb8233e9554d0310a923fdc7593c9384b7c0`。该 successor 是 Task 2 起唯一权威规格。

**Plan directory:** `docs/superpowers/plans/`。

**Execution status:** Tasks 0–20 的实现、完整本地 release gates 与 hosted CI 已通过；Milestones A/B 和 `legacy_parser → p0_catalog → legacy_parser` rollback 的真实 React → FastAPI → MySQL 无 mock 验收均通过。固定 4M 性能证据、当前业务库 SELECT-only canary、最小权限、MySQL 8.0/8.4 matrix 与加密备份恢复、release-build live、deployment verification、前端/OpenAPI、Ruff-format/Mypy 和文档均为 PASS；41 路径静态债 successor manifest/baseline 已获批准并通过边界核验。用户已授权 candidate 分支 `codex/product-catalog-task20-candidate-20260826` 的 commit/push 和 PR #7；实现候选 HEAD `b86cbffeaac9c237f726052d317278feb56b3754` 的 push/PR 两组 hosted CI 均全部通过。P0 迁移 `0022` 仅在 canonical runner 拥有的随机 disposable Oracle MySQL 8.0/8.4 数据库执行；未执行 stamp、业务数据库写入、生产部署、合并或 tag。原《成品生产订单与完工入库实施计划》继续暂停。

## Global Constraints

- P0 只交付商品目录、Seller SKU 精确映射和款式/颜色/尺码分析；不实现生产订单、工厂完工、广州仓、出货、海运、FBA 实收，也不冒充 E0 完整 Amazon snapshot。
- 每个正式款式使用稳定 `style_id`；每个实际款色码使用稳定 `sku_id`。ID 由数据库分配，不能由款号、名称、Seller SKU、ASIN、FNSKU 或 hash 派生。
- 一次批准生成不可变目录版本；历史 revision、成员、证据、reservation、审计和 fact tuple 只追加不更新。目录纠错通过向前版本完成，不直接回拨 current pointer。
- 当前分析只使用有界 publication members、匹配的 ready return-dedup snapshot 和指定目录 mapping 在 MySQL 聚合。禁止把整段原始日报读到 Python 或浏览器再聚合。
- `fact_basis=current` 与历史目录非法；`catalog_snapshot` 必须精确重放目录冻结的 publication、dedup、site config 和 cutoff tuple。任一响应不得混合两套事实来源。
- 退货 KPI 使用 `quantity`；默认按事件业务日，也可按报告日。经营转化率固定为 `SUM(units_ordered) / SUM(sessions_total)`，分母小于等于 0 时为 `null`。
- 缺报、真零、未归类、明确排除、重复和未决重复是不同状态；产品总表返回六桶对账，商品详情只返回本款守恒。
- 普通 API 只返回 `SafeSourceRef`。订单号、物流牌照号、买家留言和危险来源字符不得进入 XLSX、普通 JSON、DOM、ARIA、URL、日志、trace 或测试失败文本。
- 原始 XLSX 上传是 bounded raw body，不使用 multipart；解析前执行 ZIP/OOXML allowlist、实际字节、member、解压大小、压缩比、XML、公式、宏和外链安全门。
- Unicode 身份算法固定 UCD 15.1.0；禁止直接继承 Python 3.14 的宿主 Unicode 16.0。规范化和 JCS 都要有 known-answer/golden fixtures。
- 前端不得把金额或转化率 decimal string 先转 JavaScript `Number` 再展示或重算；图表如需定位，只使用定点整数。
- Reveal 只存在内存。主体、站点、角色、permissions、request key 或 revision 改变，以及当前请求返回 403、绑定资源的 404 或草稿 409 时，必须销毁可逆值和复制缓冲。
- 任一已认证、非登录请求返回 401 时必须触发一次全局 session-revoked 边界：同步清除 principal/site/CSRF，递增 authz generation，终止全部旧 request gate，并销毁 reveal、base64、解码值与复制缓冲；同一旧边界的并发 401 和迟到成功响应都不得二次提交。
- 自动迁移、集成、性能、备份恢复和 live E2E 只能连接 runner-owned、名称匹配 `clsen_data_test*`、`utf8mb4` 的 disposable Oracle MySQL；不得对业务库写入或压测。
- 唯一允许读取当前业务库的最终 canary 使用 SELECT-only 身份和 `REPEATABLE READ READ ONLY`，输出只有计数、版本和 digest allowlist。
- 当前已知三套迁移事实必须分开记录：Git 已提交迁移头 `0019`；工作树因未跟踪 `0020/0021` 显示 `0021`；最近一次业务库只读证据为 `0020`。`0020` 已有应用证据，绝不可重写。
- 开工时重新证明 `0021` 是否曾在任何环境应用。任何可能已应用的 revision 保持字节级不可变；P0 使用当时真实线性 head 的下一编号，本文默认在 Task 1 消除冲突后为 `0022`。
- 当前工作树包含大量用户既有修改和未跟踪文件。不得使用 `git reset --hard`、覆盖式 checkout、clean、自动格式化全仓或删除未跟踪文件。
- Task 0 先冻结仓库外私有基线和 touched-file manifest。后续只修改 manifest 内路径；重叠脏文件必须保留用户原 hunk，不能用“重写整个文件”掩盖覆盖。
- 未经用户另行授权，不执行 `git add`、`git commit`、merge、rebase、tag 或 push。任务完成点保存未提交证据并等待验收。
- 配置、脚本或测试文件存在不等于门禁通过；只有同一候选代码和 artifact digest 的实际 PASS 证据才能支持完成声明。
- 未获 Git 授权的未提交候选只能声明 local release-ready：workflow contract 和 canonical local runners 必须通过，但 hosted CI 只能在用户另行授权创建 candidate ref/PR 后作为后续部署硬门，不能伪称已运行。

## Milestones and Pause Gates

| 里程碑 | 入口 | 可独立体验的结果 | 暂停门 |
| --- | --- | --- | --- |
| A：商品主档 V1 | Task 1 successor 规格已再次书面批准，Tasks 2–10 后端门通过 | 生成候选、标准 XLSX/在线草稿、异常处理、审核、普通/高风险批准、版本与安全证据 | Task 13 真实 React → FastAPI → MySQL 无 mock 验收通过后暂停；旧产品分析仍保持 legacy |
| B：稳定款式与变体趋势 | 已批准目录 V1 | 新 `/products` 和 `/products/:style_id` 直达体验；旧新 API 双轨且互不 fallback | Task 18 双轨 live 验收通过后暂停；尚未替换正式旧入口 |
| C：受控切换与 release gate | A/B 证据均通过 | 固定快照对账、整套 UI/adapter 切换和零业务写 rollback 演练；性能、canary、恢复、workflow contract、文档与 hosted CI 全通过 | Task 20 已达到 candidate release-ready；生产迁移、流量启用、merge 和 tag 仍需单独授权 |

## Planned Component Boundaries

### Backend

- `backend/app/catalog/`：UCD/JCS、安全引用、scope、dedup、fact tuple、候选、XLSX、导入工作流、身份、revision、批准和查询。
- `backend/app/api/catalog_*.py`：商品目录的严格 API、RBAC、CSRF、错误、安全 evidence/reveal 和原文件下载。
- `backend/app/analytics/style_*.py`：只从有界 publication members 和 catalog mappings 进入 MySQL 的稳定款式聚合。
- `backend/app/api/style_analytics.py`：新 `style-ledger` 与稳定 `style_id` card；旧 dashboard 路由只保留兼容语义和 identity headers。
- `backend/app/worker/`：return dedup staging、目录 export/import worker 和租约恢复。

### Frontend

- `frontend/src/components/source-reference/`：普通安全引用和内存 reveal 生命周期。
- `frontend/src/features/catalog/`：主档、导出、上传、五 section 审核、问题定位、版本、未匹配和证据。
- `frontend/src/features/products/`：稳定款式产品总表、详情、独立 SVG 趋势、每日等价矩阵和 cutover adapter。
- `frontend/tests/e2e/live/` 与 `frontend/playwright.catalog-live.config.ts`：默认套件之外、只连接 runner-owned 真服务的 live 验收。

### Operations and evidence

- `scripts/run-product-catalog-*.ps1`：live、性能、真实只读 canary、备份恢复和 release gate。
- `docs/user-guide/` 与 `docs/operations/`：运营使用、数据口径、切换、回滚和恢复。
- `docs/superpowers/plans/2026-08-20-product-style-variant-analytics-foundation-file-manifest.json`：本计划允许触碰的仓库相对路径，排序、去重、自包含。

**Manifest convention:** `Files` 中省略目录的文件名继承同一 bullet 内最近一个在它之前出现的完整路径目录；以 `.` 开头的仓库根文件不继承目录。JSON manifest 保存每个文件的完整仓库相对路径，是执行时的精确边界。`Read`、符号名或 “reuse without modification” 路径不进入 manifest；若实现确需修改，必须先修订本计划和 manifest，再重新执行 Task 0。

---

## Milestone A：商品主档初始化、审核与批准 V1

### Task 0: 冻结工作区、touched manifest 和真实迁移头

**Files:**

- Create now / validate at execution: `docs/superpowers/plans/2026-08-20-product-style-variant-analytics-foundation-file-manifest.json`
- Create now / use as execution ledger: `docs/superpowers/plans/2026-08-20-product-style-variant-analytics-foundation-implementation.md`
- Read: `docs/superpowers/specs/2026-08-19-product-style-variant-analytics-foundation-design.md`
- Read: `backend/alembic/versions/`、`backend/app/cli.py`、`backend/app/maintenance/backup.py`、`backend/app/maintenance/restore.py`、`scripts/database-privileges.json`
- No product-code modification

**Interfaces:**

- Consumes: commit `1ead0fd`、当前 index/worktree、已提交/文件系统/业务库三套 revision 证据。
- Produces: 仓库外私有 baseline、排序去重的 touched manifest、逐路径 owner/状态/checksum、`0020/0021` 部署历史结论和 Task 1 可执行分支。
- Invariants: 本任务不改业务代码、迁移或数据库；无法证明迁移历史或 baseline 完整时后续全部阻塞。

- [x] **Step 1: 记录只读 Git 与 Alembic 基线**

  ```powershell
  git status --short --branch
  git rev-parse HEAD
  git ls-files --stage -- backend/alembic/versions
  Push-Location backend
  ..\.venv\Scripts\python.exe -m alembic -c alembic.ini heads
  Pop-Location
  ```

  Expected: HEAD 为 `1ead0fd...`；已提交图到 `0019`，当前文件系统单一 head 为 `0021`；`0020/0021` 的未跟踪状态和所有重叠脏文件被完整记录。

- [x] **Step 2: 验证 manifest，而不是从 `git status` 自动收录文件**

  ```powershell
  $manifest = Get-Content -Raw -LiteralPath .\docs\superpowers\plans\2026-08-20-product-style-variant-analytics-foundation-file-manifest.json | ConvertFrom-Json
  if ($manifest.Count -eq 0) { throw "manifest is empty" }
  $ordinal = [string[]]$manifest.Clone()
  [Array]::Sort($ordinal, [StringComparer]::Ordinal)
  if (($manifest -join "`n") -cne ($ordinal -join "`n") -or ($manifest | Select-Object -Unique).Count -ne $manifest.Count) { throw "manifest must be ordinal-sorted and unique" }
  $repoPrefix = [IO.Path]::GetFullPath((Get-Location).Path + [IO.Path]::DirectorySeparatorChar)
  foreach ($path in $manifest) {
    if ($path -isnot [string] -or [string]::IsNullOrWhiteSpace($path) -or [IO.Path]::IsPathRooted($path)) { throw "unsafe manifest path" }
    $resolved = [IO.Path]::GetFullPath((Join-Path $repoPrefix $path))
    if (-not $resolved.StartsWith($repoPrefix, [StringComparison]::OrdinalIgnoreCase)) { throw "manifest path escapes repository" }
  }
  ```

  Expected: JSON 是非空、排序、去重的仓库相对路径数组，包含计划和 manifest 自身，不含用户范围外文件或路径逃逸。

- [x] **Step 3: 在仓库外创建 ACL 收紧的私有 baseline**

  保存冻结仓库绝对路径、HEAD OID、NUL 分隔的 `git status --porcelain=v1 -z --untracked-files=all` 与 `git ls-files -s -z`；对 manifest 每个路径保存 `absent|tracked_clean|tracked_dirty|untracked`、index/worktree 状态、长度、SHA-256 和存在文件的原始字节。跟踪脏文件另保存 HEAD/index blob 和 staged/unstaged binary diff。baseline 根不得位于仓库、不得写入日志或 manifest，并通过私有 `APP_PLAN_BASELINE_ROOT` 交给最终核验。

- [x] **Step 4: 证明迁移历史**

  以部署记录、备份 manifest 和只读 `alembic_version` 证据确认：`0020` 已应用并保持不可变；逐环境确认 `0021` 是否曾应用。未知视为“可能已应用”，不允许重写。禁止为了得到答案对业务库执行 migration、stamp 或 DDL。

- [x] **Step 5: 扫描所有 revision、权限和备份硬编码**

  ```powershell
  rg -n "0019|0020|0021|alembic_version|schema_revision|database must be migrated" backend scripts ops .github docs
  rg -n "product_skus|product_sku_revisions|0022|0023|0024" docs backend scripts
  ```

  Expected: 冲突清单覆盖文档、CLI、migration contract、bootstrap、权限、backup/restore、MySQL matrix、CI、部署验证及未实施计划，不只修改一个常量。

- [x] **Step 6: 为每个 manifest 路径登记 owner task 和基线重叠**

  同一路径跨任务修改时登记顺序 owner；已有用户 hunk 的文件必须标记为 `overlap`，执行时使用窄 `apply_patch` 并在每个里程碑做三方比较。

- [x] **Step 7: 保存 Task 0 门禁记录**

  Expected: 得到“已提交 head `0019` / 工作树 head `0021` / 业务库证据 `0020`”的无歧义说明、`0021` 的不可变性决策、P0 实际下一 revision 决策和数据库安全边界；除本计划与 manifest 外无新增 diff。

  Actual (2026-08-20): PASS。HEAD 为 `1ead0fd952d0aba45ad2bc39fc744c1967f8d587`；已提交迁移 head 为 `0019`，文件系统唯一 head 为 `0021`。只读 `REPEATABLE READ` 证据确认业务库及其备份 revision 为 `0020`，测试库已应用 `0021`；因此 `0020/0021` 均保持字节级不可变，P0 下一 revision 固定为 `0022`。私有 baseline 在仓库外建立，302 个 manifest 路径全部登记，含 27 个 overlap 与 39 个跨 Task 路径；Step 5 扫描覆盖 33 个文件。数据库取证未执行 migration、stamp 或 DDL，Task 0 期间工作区 NUL 状态与冻结快照逐字节一致。

### Task 1: 修订冲突文档、迁移编号和运维契约硬门

**Files:**

- Modify: `docs/superpowers/specs/2026-08-19-product-style-variant-analytics-foundation-design.md`
- Modify: `docs/superpowers/specs/2026-08-06-daily-data-review-platform-design.md`
- Modify: `docs/superpowers/plans/2026-08-06-daily-data-review-platform-implementation.md`
- Modify: `docs/superpowers/specs/2026-08-14-ledger-home-and-workflow-optimization-design.md`
- Modify: `docs/superpowers/plans/2026-08-14-ledger-home-and-workflow-optimization-implementation.md`
- Modify: `docs/superpowers/specs/2026-08-18-finished-goods-production-receipt-design.md`
- Modify: `docs/superpowers/plans/2026-08-18-finished-goods-production-receipt-implementation.md`
- Modify: `docs/superpowers/plans/2026-08-18-end-to-end-sku-supply-chain-roadmap.md`
- Modify: `docs/superpowers/plans/2026-08-12-read-only-agent-analysis-implementation.md`、`docs/superpowers/plans/2026-08-12-switchable-application-release-management-implementation.md`
- Create: `backend/app/maintenance/schema_revision.py`、`backend/tests/contracts/test_schema_revision_contract.py`
- Modify: `backend/app/cli.py`、`backend/app/maintenance/backup.py`、`backend/app/maintenance/restore.py`
- Modify: `backend/tests/contracts/test_migration_contract.py`、`backend/tests/contracts/test_database_bootstrap_script.py`、`backend/tests/contracts/test_maintenance_scripts.py`、`backend/tests/contracts/test_test_grant_sync_script.py`、`backend/tests/contracts/test_server_deployment.py`、`backend/tests/unit/auth/test_admin_cli.py`
- Modify: `scripts/init-database.ps1`、`scripts/database-privileges.json`、`scripts/sync-test-runtime-grants.ps1`、`scripts/test-mysql-matrix.ps1`、`.github/workflows/compatibility.yml`
- Create: `scripts/check-worktree-text.ps1`、`scripts/check-plan-worktree-baseline.ps1`

**Interfaces:**

- Consumes: Task 0 的部署历史结论和已批准 P0 规格。
- Produces: 候选 successor 规格、唯一迁移顺序、共享 schema revision 来源、scope/dedup/publication/XLSX/API 的无歧义补充契约、工作区三方检查器，以及生产计划 `0023/0024` 或实际顺延编号。
- Invariants: `0020` 永不修改；任何可能已应用的 `0021` 也不修改。补充后的 successor 规格必须计算新 SHA-256 并再次取得用户书面批准；未批准时 Task 2 及全部 P0 业务代码阻塞。

- [x] **Step 1: 先写失败的 schema-head 与工作区保护契约**

  测试要求 Alembic 只有一个 head；CLI、backup writer、restore compatibility、bootstrap、matrix 和部署验证从 `schema_revision.py` 或同一生成来源读取，禁止各自维护字符串。两个检查器必须只接受 Task 0 的私有 baseline＋排序 manifest，拒绝仓库外逃逸、未登记路径、丢失的用户原 hunk、文本损坏和伪造 baseline 元数据。

- [x] **Step 2: 正式修订替代关系与迁移排期**

  保留并明确记录原 P0 基线已批准的事实；本任务新增内容先标记为待再次批准的 successor candidate，只有 Step 7 取得书面批准后才改为“正式批准”。日报规格加入 source scope sidecar 和 publication/dedup 同事务 CAS；ledger 文档把 `style_code` 降为 legacy；生产规格/计划删除重复 SKU 身份建模并顺延为 `0023/0024`；Agent/发布后继计划解除固定 `0022` 占用或明确归档。若 Task 0 得出不同下一编号，同步修改所有引用后再继续。

- [x] **Step 3: 冻结 `return_event_fingerprint_v1`**

  在规格中明确：对 `return_report_v1` 已严格解析的 13 个 typed 字段按固定键名、UTC 时间表示、整数和原样 Unicode string 组成 JCS object；对 JCS UTF-8 求 SHA-256。只有相同 scope、不同 current publication member 出现相同 fingerprint 才形成跨报告候选组；组内按 `report_date/dataset_id/published_version_id/active_row_id` 的二进制稳定顺序选初始 canonical，新增或变化组默认为 `unresolved`。订单号、牌照和留言只进入摘要，不进日志、XLSX 或普通 API。规则升级只能新建版本。

- [x] **Step 4: 补齐缺失的 API/worker 协议**

  在规格中精确加入 source-scope status/confirm、dedup group list/decision、原始 catalog XLSX 下载，以及 publication staging 的 trigger/status/wait/retry/failed/command recovery 契约；同时冻结 Task 19 只允许 release/build 级 `legacy_parser|p0_catalog` 闭集选择、禁止请求级或行级 fallback。固定状态码、角色、counter、幂等 token、判定顺序和安全错误字段。

- [x] **Step 5: 建立共享 revision 来源并同步运维门**

  `schema_revision.py` 先表示 Task 0 确认的当前工作树 head；CLI、backup、restore、bootstrap、grant sync、MySQL matrix 和 CI 全部导入/生成该值。Task 3 创建 P0 revision 时只推进一次。旧 backup artifact 读取兼容与新 writer 精确 head 必须分开。

- [x] **Step 6: 运行文档引用和契约测试**

  ```powershell
  .\.venv\Scripts\python.exe -m pytest backend/tests/contracts/test_schema_revision_contract.py backend/tests/contracts/test_migration_contract.py backend/tests/contracts/test_database_bootstrap_script.py backend/tests/contracts/test_maintenance_scripts.py backend/tests/contracts/test_test_grant_sync_script.py backend/tests/contracts/test_server_deployment.py backend/tests/unit/auth/test_admin_cli.py -q
  Push-Location backend
  ..\.venv\Scripts\python.exe -m alembic -c alembic.ini heads
  Pop-Location
  rg -n "P0|0022|0023|0024|legacy_parser|p0_catalog" docs/superpowers
  ```

- [x] **Step 7: 冻结 successor digest、执行硬门自审并暂停批准**

  计算补充后规格的 SHA-256，保存相对原批准基线的逐节语义 diff，并运行 `check-worktree-text.ps1` 与 `check-plan-worktree-baseline.ps1`。随后暂停，请用户书面批准 successor；批准后把本计划 `Approved design` 更新为 successor digest/批准日期并重跑本步。

  Expected: 单一文件系统 head 保持 Task 0 确认值（默认 `0021`）；`0020` 字节未变；规格不再有待复核或协议空洞；生产计划明确暂停且不重复建 SKU；所有运维契约指向同一 revision 来源；successor digest 与书面批准可复核。任一失败或未批准都阻止 Task 2。

  Actual candidate checkpoint (2026-08-20): 原批准基线 SHA-256 已从 Git blob 复核为 `cab5b39b6e2cc04749a6ae7b467bc797dd7cd1d65ce47ef2ebdd028fd70019f7`；successor candidate SHA-256 为 `858cd5a165f1440e4f8e30b1abf1fb8233e9554d0310a923fdc7593c9384b7c0`。逐节语义 diff、raw patch 和验证 evidence 已保存到仓库外私有基线。聚焦契约 `90 passed`，Alembic 唯一 head 为 `0021 (head)`，302 路径三方保护和 91 个严格 UTF-8 文件检查均 PASS。当前状态为 `candidate_pending_written_approval`；Step 7 保持未勾选，未经用户再次书面批准不得更新本计划的 Approved design 权威摘要，也不得开始 Task 2。

  Actual approval (2026-08-20): 用户书面批准 SHA-256 `858cd5a165f1440e4f8e30b1abf1fb8233e9554d0310a923fdc7593c9384b7c0` 作为 successor 规格并明确授权继续 Task 2。批准后复核规格 bytes/digest、Task 1 聚焦契约、唯一 Alembic head、文本和私有 baseline 门保持 PASS；Task 1 完成。

### Task 2: UCD 15.1、JCS、SafeSourceRef 和严格领域类型

**Files:**

- Create: `backend/app/catalog/__init__.py`、`backend/app/catalog/types.py`、`backend/app/catalog/errors.py`、`backend/app/catalog/models.py`
- Create: `backend/app/catalog/normalization.py`、`backend/app/catalog/canonical_json.py`、`backend/app/catalog/source_refs.py`
- Create: `backend/app/catalog/data/ucd_15_1/UnicodeData.txt`、`CompositionExclusions.txt`、`DerivedNormalizationProps.txt`、`NormalizationTest.txt`、`CaseFolding.txt`、`PropList.txt`、`LICENSE.txt`、`manifest.json`
- Modify: `backend/pyproject.toml`、`backend/requirements.in`、`backend/requirements.lock`
- Create tests: `backend/tests/unit/catalog/test_normalization.py`、`test_canonical_json.py`、`test_source_refs.py`、`test_types.py`

**Interfaces:**

- Consumes: `seller_sku_match_v1`、`catalog_identity_key_v1`、`safe_source_projection_v1`、`publication_refs_jcs_v1`。
- Produces: 与宿主 Unicode 版本无关的规范键、只接受受控 JSON 值域的 canonical bytes/hash、不可携带原始值的 `SafeSourceRef`、`extra="forbid"` 的请求/响应/command DTO。
- Invariants: runtime 不联网；UCD 文件和 license 有 SHA-256 manifest；JCS 拒绝 float/NaN/Infinity；未知字段一律拒绝。

- [x] **Step 1: 写 UCD 15.1 与宿主 16.0 差异的失败 golden tests**

  对官方 `NormalizationTest.txt` 执行完整 conformance，并覆盖 NFKC、Unicode White_Space trim、保留 Seller SKU 大小写、默认非 Turkic full case-fold、XML 1.0 Char、`Cc/Cf/Zl/Zp`、组合字符、空键、碰撞、非 ASCII 及宿主 16.0 差异。

- [x] **Step 2: 固定并验证 UCD 15.1 数据**

  把所需官方数据、license、版本和每个文件 SHA-256 固化到 `manifest.json`，并在 `pyproject.toml` 显式声明 package data；从构建 wheel 安装后的测试环境再次读取并校验。加载器遇到缺失或不匹配时 fail closed；不得回退到 `unicodedata.normalize` 或宿主 casefold。

- [x] **Step 3: 最小实现两个规范化算法和安全预览**

  `seller_sku_match_v1` 执行 NFKC＋White_Space trim、保留大小写并返回 full bytes＋digest；`catalog_identity_key_v1` 再执行 C+F、排除 T 的 full case-fold；`safe_source_projection_v1` 只返回安全 preview/digest/flags。

- [x] **Step 4: 写 JCS known-answer 后实现内部编码器**

  覆盖 Unicode key ordering、escaping、null、boolean、有符号整数、array/object 和嵌套对象；编码器只接受本项目需要的整数/string/bool/null/array/object，decimal 先作为规范 string，float 稳定拒绝。

- [x] **Step 5: 实现严格领域类型和 `SafeSourceRef`**

  固定 ID、revision/counter、状态、reason code、permissions、source kind 和 command envelope；`SafeSourceRef` 只含 `source_ref_id/preview/sha256/is_unsafe/is_truncated`，不能从 ref 反推出 raw 值。

- [x] **Step 6: 增加隐私与日志负向测试**

  NUL、换行、bidi、noncharacter、订单号、牌照和留言不能出现在 repr、validation detail、异常、普通日志或 API-safe model dump。

- [x] **Step 7: 运行聚焦门**

  ```powershell
  .\.venv\Scripts\python.exe -m pytest backend/tests/unit/catalog/test_normalization.py backend/tests/unit/catalog/test_canonical_json.py backend/tests/unit/catalog/test_source_refs.py backend/tests/unit/catalog/test_types.py -q
  .\.venv\Scripts\python.exe -m ruff check backend/app/catalog backend/tests/unit/catalog
  ```

  Expected: 当前 Python/UCD 16 主机仍输出冻结的 15.1 golden bytes；UCD/checksum、JCS、碰撞和敏感输出测试全部 PASS。

  Actual (2026-08-20): PASS。四组聚焦测试 `37 passed`，其中对官方 `NormalizationTest.txt` 执行了完整 UCD 15.1 conformance；Ruff lint、Ruff format check 和 scoped strict mypy 均通过。官方七份 UCD/license 文件的长度与 SHA-256 manifest 全部验证，runtime 未使用宿主 `unicodedata.normalize`、宿主 casefold 或网络回退。最终 wheel `clsen_daily_data_review-0.1.0-py3-none-any.whl` SHA-256 为 `8a013392c186e731d549f43e9c745e2b1df60ed419842c4aa356bc18f9dae1f0`；隔离安装后从 wheel 内读取七份 UCD 文件、重验 manifest，并通过 NFKC 与 identity-key known-answer。工作区严格 UTF-8 检查覆盖 110 个文件，302 路径私有 baseline 三方门 PASS；构建残留已从仓库移除。未执行 migration、stamp、DDL、数据库写入或 Git 暂存/提交/推送。

### Task 3: 迁移 `0022_product_catalog_foundation`、最小权限和备份契约

**Files:**

- Create: `backend/alembic/versions/0022_product_catalog_foundation.py`（若 Task 0 得到不同下一编号，先全局改名和同步 `down_revision`）
- Modify: `backend/app/maintenance/schema_revision.py`、`backend/app/maintenance/backup.py`、`backend/app/maintenance/restore.py`
- Modify: `scripts/database-privileges.json`、`scripts/init-database.ps1`、`scripts/sync-test-runtime-grants.ps1`、`scripts/test-mysql-matrix.ps1`、`.github/workflows/compatibility.yml`
- Modify tests: `backend/tests/contracts/test_migration_contract.py`、`backend/tests/contracts/test_database_bootstrap_script.py`、`backend/tests/contracts/test_maintenance_scripts.py`、`backend/tests/contracts/test_test_grant_sync_script.py`、`backend/tests/contracts/test_server_deployment.py`、`backend/tests/integration/test_migrations.py`、`backend/tests/integration/test_database_constraints.py`
- Modify test safety: `backend/tests/conftest.py`
- Create: `backend/tests/integration/test_catalog_schema.py`、`backend/tests/integration/test_catalog_grants.py`
- Create: `scripts/run-product-catalog-mysql-tests.ps1`

**Interfaces:**

- Consumes: Task 1 唯一线性 head 和 Task 2 固定算法版本。
- Produces: scope/assignment/sidecar、publication snapshot/fact tuple、return dedup checkpoint/delta/pointer、style/SKU/revision/reservation、catalog version/member/mapping/exclusion/pointer/event、source/evidence、export/import/parse/workflow/issue/projection、command/effect/audit/job lease 的完整 schema。
- Invariants: immutable 集合 insert-only；pointer/lease/draft 只有窄更新权限；不新增宽泛 DELETE/UPDATE；MySQL 非事务 DDL 支持 preflight、部分完成签名和安全重试；任何 Alembic/DDL fixture 之前必须通过 runner ownership 和数据库实连接安全门。

- [x] **Step 1: 先扩展失败的 schema、约束和 grant contract**

  逐项断言表、列、复合 FK、unique/check、二进制键、索引、immutability、CAS revision、source-of-truth backup inventory 和 runtime/backup 权限；禁止只用“表存在”验收。根 `conftest.py` 在 collection/fixture 前要求 runner 注入不可空的 `APP_TEST_RUN_ID`，并拒绝非字面 loopback、数据库名未以该随机 run ID 结尾的 `clsen_data_test*`、URL schema 与 `DATABASE()` 不同、非 Oracle MySQL 8.0/8.4、非 `utf8mb4`，以及 migration/runtime/backup 账号未分离的连接。

- [x] **Step 2: 实现可安全重跑的迁移 preflight**

  复用 `0011` 的 partial-DDL signature 思路。fresh、`0020→0021→0022` 和带数据 `0021→0022` 都必须继续或给出精确诊断；不得自动 downgrade、stamp、drop 或重建已存在业务表。新 canonical runner 为每次执行创建带 ownership label 的随机 loopback Oracle MySQL、随机数据库和分离账号，只接受显式 backend-relative pytest 路径；它只向测试子进程注入匹配的 `APP_TEST_RUN_ID` 与各账号 URL，并在 `finally` 恢复环境、按 label 清理。matrix 复用同一实现，直接提供任意外部 `APP_TEST_DATABASE_URL` 必须 fail closed。

- [x] **Step 3: 创建不可变实体和受控可变指针**

  对 revision/member/evidence/reservation/command effect/event 使用 append-only；catalog/import row 自身保存 original filename/media type；publication pointer revision 独立单调，不能复用 `daily_dataset_locks.lock_revision`。

- [x] **Step 4: 实现确定性历史回填和有界索引**

  回填 source scope assignment 和 Seller SKU match-key sidecar；为 publication member、scope＋match key、catalog version＋SKU、style/date、return event time、dedup group 和 pointer lookup 建索引。碰撞只落显式队列，绝不自动合并。

- [x] **Step 5: 同步最小权限、revision 和 backup/restore inventory**

  immutable 表进入 `insert_only`；pointer/job/draft 进入列级或用途级 mutable 集合。writer 只接受新精确 head，reader 保留已批准的 v1/`0020` artifact 兼容。

- [x] **Step 6: 先跑非 DB 契约，再跑 disposable MySQL**

  ```powershell
  .\.venv\Scripts\python.exe -m pytest backend/tests/contracts/test_migration_contract.py backend/tests/contracts/test_database_bootstrap_script.py backend/tests/contracts/test_schema_revision_contract.py backend/tests/contracts/test_maintenance_scripts.py backend/tests/contracts/test_test_grant_sync_script.py backend/tests/contracts/test_server_deployment.py backend/tests/unit/maintenance/test_backup.py backend/tests/unit/maintenance/test_restore.py -q
  pwsh .\scripts\run-product-catalog-mysql-tests.ps1 -Versions @("8.0") -PytestPaths @("tests/integration/test_migrations.py", "tests/integration/test_database_constraints.py", "tests/integration/test_catalog_schema.py", "tests/integration/test_catalog_grants.py")
  ```

- [x] **Step 7: 验证两个 MySQL 版本和单一 head**

  ```powershell
  pwsh .\scripts\test-mysql-matrix.ps1 -Versions @("8.0", "8.4")
  Push-Location backend
  ..\.venv\Scripts\python.exe -m alembic -c alembic.ini heads
  Pop-Location
  ```

  Expected: Oracle MySQL 8.0/8.4 的三条迁移路径均到唯一 `0022`（或 Task 0 顺延值）；重跑安全；约束、grant、backup/restore inventory 和运行时 revision 完全一致。

  Actual (2026-08-21): PASS。Red 阶段先得到 5 个预期失败（`0022` 尚不存在），随后创建初始含 37 张目录/去重/fact/workflow 表的线性迁移（Task 5 前向增加两张 staging 表，Task 6 再增加 exact export payload 表，当前共 40 张），并同步 shared revision、最小 runtime/backup grants、backup/restore inventory 与随机库 runner 安全门。真实 MySQL 验证发现并修复两类跨版本问题：table comment seal 在首次 `ALTER TABLE` 后重新稳定计算；MySQL 8.4 严格复合 FK 要求补齐 `publication_snapshots(id, site_id)`、`return_dedup_snapshots(id, site_id, report_source_scope_id)` 与 `fact_snapshot_tuples(id, site_id)` 唯一键。matrix readiness 改为最终 server 的容器内 TCP 探针，并在 TLS 验证后设置 trigger policy，消除官方镜像临时 Unix-socket server 竞态。

  最终同一候选上，非 DB 契约 `98 passed`；Oracle MySQL 8.0 migration `29 passed`、constraints/schema/grants `75 passed`，Oracle MySQL 8.4 migration `29 passed`、constraints/schema/grants `75 passed`；两个版本的聚焦 catalog schema/grants 均 `5 passed`。Alembic 唯一 head 为 `0022 (head)`；Task 3 路径 Ruff lint、14 个非 overlap 文件 format check、5 个文件 scoped mypy 和四个 PowerShell runner parse 均 PASS。严格文本检查覆盖 114 个文件，302 路径私有 baseline 三方门 PASS；Task 0 原始用户内容及未登记路径边界保持完整。Task 4 为支持不可变 Seller SKU 编辑历史，把 sidecar 唯一键细化为 `(version_id, source_row_id, source_key_revision)`，并把三处完整 match bytes 容量从 512 修正为最坏 1020 bytes；同一最终候选随后重新取得 MySQL 8.0/8.4 migration `29/29` 和 constraints/schema/grants `75/75`。所有 DDL 只发生在 runner-owned 随机数据库，runner 最终按 label 清理；用户 compose MySQL 容器未启动、删除或修改，未执行业务库写入、Git staging/commit/push。

### Task 4: Seller Account scope、dataset sidecar 和 `CurrentSiteContext`

**Files:**

- Create: `backend/app/site_context.py`
- Create: `backend/app/catalog/scope_repository.py`、`backend/app/catalog/scope_service.py`
- Modify: `backend/app/api/dependencies.py`、`backend/app/datasets/repository.py`、`backend/app/review/repository.py`、`backend/app/parsers/repository.py`
- Create tests: `backend/tests/unit/catalog/test_site_context.py`、`backend/tests/integration/test_catalog_scope.py`、`test_catalog_source_keys.py`

**Interfaces:**

- Consumes: Task 3 的 source scope、dataset assignment 和 match-key sidecar；现有全局 session/RBAC/CSRF 与 P0 单站点部署约束。
- Produces: 服务端派生的 `CurrentSiteContext`、一次性不可逆的单 Seller Account＋`amazon_us` 确认、所有历史/新增 dataset 的 scope assignment、每条 active Seller SKU 的 versioned match key。
- Invariants: P0 不虚构尚不存在的 user-site membership；系统必须恰有一个 active site，零个或多个都 fail closed。API 不接受客户端 `site_id` 作为授权依据；dataset 与 assignment 同事务；碰撞保留全部原值并显式处理；确认后不能静默换域。

- [x] **Step 1: 先写站点、角色和 scope 失败测试**

  覆盖伪造 site、多个/零个/inactive active site、viewer 确认、重复同语义确认、不同语义重试、跨 account/marketplace 相同 Seller SKU。未来多站点或按用户选站必须另立规格，不能在 P0 读取“第一条”。

- [x] **Step 2: 实现 `CurrentSiteContext`**

  从已认证主体和服务端唯一 active site/config 构造 immutable context；查询必须证明结果恰好一行，不能用排序＋第一条降级。路由、service 和 repository 只接收该对象或其内部 ID，不接受请求体/查询头覆盖。

- [x] **Step 3: 实现 scope status/confirm service**

  首次确认仅 admin，携带 operation token、expected site config revision 和审计原因；同 token 同语义恢复首次结果，不同语义冲突；成功后 append config revision，禁止 update 原行。

- [x] **Step 4: 同事务维护 dataset assignment**

  新 dataset、日报导入、日期改派和 materialization 都必须写唯一 assignment；历史 backfill 使用 Task 3 固定 scope，未分配或多分配均阻断新分析。

- [x] **Step 5: 维护 Seller SKU sidecar**

  parser materialization、审核编辑、新增行和迁移回填调用同一个 `seller_sku_match_v1`；保存原值 digest、完整二进制规范 bytes、算法版本、scope 和 collision group，不修改已发布原行。

- [x] **Step 6: 验证碰撞和跨站隔离**

  碰撞不得自动合并、选代表或创建正式身份；相同规范 bytes 在不同 account/marketplace 仍是不同作用域；跨站查询返回统一 404/403 而不泄漏存在性。

- [x] **Step 7: 运行聚焦 MySQL 门**

  ```powershell
  pwsh .\scripts\run-product-catalog-mysql-tests.ps1 -Versions @("8.0") -PytestPaths @("tests/unit/catalog/test_site_context.py", "tests/integration/test_catalog_scope.py", "tests/integration/test_catalog_source_keys.py")
  ```

  Expected: 全部历史/新增 dataset 恰有一个 scope；客户端无法跨站；编辑、解析和回填产生相同 match key；确认与碰撞行为可重放。

  Actual (2026-08-21): PASS。Red 首先得到缺少 `app.site_context` 的预期 collection failure；随后实现 frozen `CurrentSiteContext`，使用 `LIMIT 2` 证明恰有一个 active site/current config，零个、多个、dangling config 和客户端 `site_id` 覆盖均 fail closed，且 P0 未虚构 user-site membership。scope service 固定 `amazon_us`，仅 admin 可确认；operation token 绑定 actor/site/expected revision/安全显示名/账号 key digest/reason，同 token 同语义可跨新请求上下文恢复，不同语义稳定冲突，新 token 携带旧 revision 冲突；首次成功追加 site config revision、CAS 推进 current pointer，并在同一事务回填全部历史 dataset assignment 和 active Seller SKU key。

  dataset 创建、日期改派和 materialization 统一经过 assignment helper；scope 未确认时保留 legacy 流程，确认事务在提交前补齐全部历史 dataset，此后新 dataset 与唯一 assignment 原子提交。parser storage、dataset materialization、审核 SKU set/restore、人工新增行和 row restore 统一调用 `seller_sku_match_v1`。sidecar 以不可变 `source_key_revision` 追加，当前 active row 只选择最新 revision；原值 digest、完整规范 bytes、算法版本、scope 和确定性 collision group 同事务保存。测试覆盖两个不同原值规范到同一 `ABC`、不自动合并、不同 scope 的 collision group 隔离，以及 200 个四字节 scalar 形成的 800-byte match bytes；schema 容量固定为 Seller SKU 255 scalar 的最坏 1020 bytes。

  最终同一候选上，Task 4 聚焦门在 Oracle MySQL 8.0 为 `7 passed`、Oracle MySQL 8.4 为 `7 passed`；因 `0022` sidecar revision/width 向前修正而完整重跑的 MySQL 8.0 migration `29 passed`、constraints/schema/grants `75 passed`，MySQL 8.4 同为 `29 passed` 与 `75 passed`。相关非 DB migration/grant contracts `55 passed`；Task 4 路径 Ruff lint、7 个非 overlap 文件 format check、10 个文件 scoped mypy、严格 UTF-8 文本和 302 路径私有 baseline 门均 PASS。四个 overlap repository/dependency 文件只做 lint/mypy 和精确 hunk 编辑，未全文件格式化，用户原内容保持。全部 DDL/写测试仅在 runner-owned 随机 disposable 数据库执行；未连接或写入业务库，未执行 Git staging/commit/push。

### Task 5: Return dedup staging、checkpoint/delta 和 publication 双指针 CAS

**Files:**

- Create: `backend/app/catalog/return_dedup.py`、`backend/app/catalog/return_dedup_repository.py`
- Create: `backend/app/worker/return_dedup.py`、`backend/app/worker/runner.py`
- Modify: `backend/app/publications/commands.py`、`backend/app/publications/repository.py`、`backend/app/publications/results.py`、`backend/app/publications/service.py`、`backend/app/publications/coordination.py`、`backend/app/publications/queries.py`
- Modify: `backend/app/api/publications.py`、`backend/app/api/workbench.py`、`backend/tests/integration/publication_test_support.py`
- Modify: `backend/app/worker/cli.py`、`backend/app/worker/outbox.py`
- Create tests: `backend/tests/unit/catalog/test_return_dedup_rules.py`、`backend/tests/integration/test_return_dedup.py`
- Modify tests: `backend/tests/integration/test_publication_transactions.py`、`test_publication_concurrency.py`、`backend/tests/unit/publications/test_commands.py`、`test_publication_repository.py`、`test_publication_service.py`、`test_coordination.py`、`test_queries.py`、`backend/tests/unit/test_openapi_contract.py`
- Regenerate: `frontend/src/api/generated.ts`
- Modify legacy UI: `frontend/src/features/versions/VersionHistory.tsx`、`VersionHistory.test.tsx`、`frontend/src/features/import-review/ImportReviewFlow.tsx`、`ImportReviewFlow.test.tsx`、`DraftReviewGate.tsx`、`DraftReviewGate.test.tsx`、`frontend/src/features/workbench/workbenchApi.ts`

**Interfaces:**

- Consumes: Task 1 的 `return_event_fingerprint_v1` 与 staging 协议、Task 3 dedup schema、Task 4 scoped return sidecar。
- Produces: deterministic candidate-group revisions、checkpoint/delta snapshot、深度不超过 32 的 ready pointer，完整 trigger/status/wait/retry/recovery wire contract，以及 publish/rollback/move/undo 与 dedup pointer 的短事务 CAS。
- Invariants: worker 不推进 current publication；只有完全匹配 proposed set/revisions/scope 的 staged snapshot 可提交；任一 CAS 失败时两个 pointer 都不变。

- [x] **Step 1: 先写规则、重放和敏感输出失败测试**

  覆盖 13 字段相同/任一字段变化、跨 publication/same publication、稳定 canonical、敏感字段只参与 digest、四状态互斥、duplicate chain/cycle 拒绝和相同输入 byte-for-byte 重放。

- [x] **Step 2: 实现 candidate group 与 checkpoint/delta**

  未进入候选组的行隐式为 `unique`；新/变化组为 `unresolved`；稳定组复用旧 revision。每 32 个 snapshot 或下一 delta 将到 32 时生成 checkpoint，查询链永不超过 32。

- [x] **Step 3: 实现 job lease、revision 和防 ABA**

  staging job 固定 proposed publication-set digest、全部 pointer revisions、scope、rule version 和 lease token；续租、takeover、完成和失败都用 expected revision CAS，旧 worker 不能覆盖新 attempt。

- [x] **Step 4: 在事务外构建并完整验证 staged snapshot**

  worker 从冻结输入读取，不重读后来变化的 current；校验逻辑全覆盖、group 引用、digest、delta depth 和 canonical 约束后才标记可参与最终 CAS。

- [x] **Step 5: 把所有 publication pointer 操作接入统一 helper**

  `service.py` 作为唯一编排入口，`coordination.py` 明确站点 return sync → 按 ID 排序的 dataset publication → dedup pointer 锁序；publish、rollback、published move 和 undo 都复用同一 helper。短 `REPEATABLE READ` 事务同时切换 report version、ready dedup snapshot 和 pointer revision；router 不自行编排，repository 不隐藏异步 handshake。

- [x] **Step 6: 实现人工 dedup 决定后继**

  data_manager/admin 的决定在事务外创建同 publication-set digest 的新 delta，再以短 CAS 只推进 dedup pointer；历史 snapshot 不更新，`unresolved` 从正式 KPI 排除并使 returns partial。

- [x] **Step 7: 运行规则、调用链、旧 UI、并发和回滚门**

  ```powershell
  .\.venv\Scripts\python.exe -m pytest backend/tests/unit/publications/test_commands.py backend/tests/unit/publications/test_publication_repository.py backend/tests/unit/publications/test_publication_service.py backend/tests/unit/publications/test_coordination.py backend/tests/unit/publications/test_queries.py backend/tests/unit/test_openapi_contract.py -q
  pwsh .\scripts\run-product-catalog-mysql-tests.ps1 -Versions @("8.0") -PytestPaths @("tests/unit/catalog/test_return_dedup_rules.py", "tests/integration/test_return_dedup.py", "tests/integration/test_publication_transactions.py", "tests/integration/test_publication_concurrency.py")
  .\scripts\generate-api-client.ps1
  .\scripts\generate-api-client.ps1 -Check
  Push-Location frontend
  pnpm exec vitest run src/features/versions/VersionHistory.test.tsx src/features/import-review/ImportReviewFlow.test.tsx src/features/import-review/DraftReviewGate.test.tsx
  pnpm typecheck
  Pop-Location
  ```

  Expected: stale/failed staging 无法发布；旧 UI 能等待、重试和恢复而不把 building 冒充 published；丢回执和重试收敛；所有 publication 操作整体提交或整体不变；snapshot 重放和深度限制稳定。

  Actual (2026-08-21): PASS。实现 deterministic return candidate group、四状态互斥、checkpoint/delta snapshot、revision-CAS job lease/takeover/renew/complete/fail 和完整 staged validation；worker 只产出 ready snapshot，不推进 publication。publish、rollback、published move 与 undo 均由 service/coordination 统一进入 return sync → 有序 dataset publication → dedup pointer 锁序，最终短 `REPEATABLE READ` CAS 同时验证冻结 publication set、全部 revision、scope 和 snapshot digest；任一 stale/ABA/CAS 冲突保持两个 pointer 不变。move undo 从唯一未反转 lineage 冻结 source-restored/target-restored-or-removed 集合，实库测试证明 move 与 undo 都原子推进两侧 publication revision 和 dedup revision。

  人工 `confirmed_distinct|duplicate_of` 决定使用安全 Seller SKU `SafeSourceRef`、严格 dedup/group revision、不可变 successor group revision、事务外 snapshot 构建和短 dedup-pointer-only CAS；publication revision 不变，command claim/effect 支持丢回执后的幂等恢复，历史 snapshot 不变。连续 32 个额外人工 successor 后 dedup revision 达到 34，至少两个 checkpoint，最大 delta depth 不超过 31，最新 group revision 可稳定重放。旧 UI 的 publish/finalize/rollback/undo 全部先 staging；building 只显示准备状态，recoverable failed 使用独立 retry token，superseded/revision conflict 最多重建一次，最终 publication 命令只在 ready 后发送并复用对应 staging token。版本 API 明确暴露 publication/dedup revision；人工 group list/decision API 与生成客户端同步。

  最终同一候选上，publication unit/OpenAPI 门为 `94 passed`；旧 UI 三文件 Vitest 为 `41 passed`，TypeScript typecheck、生成客户端 `-Check`、Task 5 路径 Ruff 与 scoped mypy 均 PASS。Oracle MySQL 8.0 Task 5 矩阵为 `23 passed`，Oracle MySQL 8.4 同为 `23 passed`（5 rules、2 dedup integration、14 publication transaction、2 concurrency）。首轮 8.0 门暴露 legacy-lineage 测试夹具误穿越不在本任务冻结范围的旧 workbench semantic-kind 合并；夹具改为在 disposable DB 以 legacy guard bypass force-rebuild 后显式补回 `draft_predecessor` 历史边，聚焦复跑 `14 passed`，随后两个完整矩阵均 PASS。runtime grant 清单包含 `catalog_command_claims`、`catalog_command_effects`、`catalog_audit_events`，实库人工决定写链已通过。

  批准 successor SHA-256 复核仍为 `858cd5a165f1440e4f8e30b1abf1fb8233e9554d0310a923fdc7593c9384b7c0`；在收尾单文件授权扩展前，302 路径私有三方 baseline、126 个严格 UTF-8 文本与 manifest `git diff --check` 均 PASS。生成客户端替换的 Task 0 单行 OpenAPI digest 已用原行 hash＋当前整文件 hash 登记在仓库外私有 replacement ledger，未放宽检查器。所有 DDL/写测试只使用 runner-owned 随机 disposable 数据库，runner 容器已清理；未连接或写入业务库，未改写 `0020/0021`，未执行 Git staging/commit/merge/rebase/tag/push。

  收尾项目级门先暴露两个 frozen contract 旧断言（runtime column grant 与 migration table count）和一个原 manifest 外的 Task 4 dataset fake 缺口；前两项在原范围内修正后 contract 为 `19 passed`。用户随后明确回复“继续”，授权只扩展 `backend/tests/unit/datasets/test_dataset_repository.py`；该 fake 只增加未确认 scope 的空查询结果和顺序事件，聚焦 repository 为 `31 passed`，HEAD/current SHA-256 与严格 UTF-8 已登记到仓库外 `task5-authorized-scope-expansion.json`，原 302 路径 baseline 未被回写或伪造。最终全量后端为 `894 passed, 290 skipped`，全量前端为 `216 passed`；publication 关键门复核仍为 `94 passed`。

### Task 6: RR fact tuple、publication snapshot、候选与证据生成

**Files:**

- Create: `backend/app/catalog/snapshots.py`、`backend/app/catalog/fact_tuples.py`、`backend/app/catalog/candidates.py`、`backend/app/catalog/evidence.py`
- Create tests: `backend/tests/unit/catalog/test_fact_tuples.py`、`test_candidates.py`、`test_evidence.py`
- Create integration: `backend/tests/integration/test_catalog_snapshot_consistency.py`

**Interfaces:**

- Consumes: Task 2 normalization/JCS/SafeSourceRef、Task 4 scope/sidecar、Task 5 原子 publication＋dedup snapshot。
- Produces: 单一只读 RR 事务中的 publication snapshot payload、状态为 building 的 exact fact tuple/candidate/evidence payload、覆盖全历史 current publications 的系统候选、证据摘要、异常组及供 Task 7 使用的 finalizer contract。
- Invariants: 读事务结束后写事务只能持久化刚才冻结的 payload，禁止重读 current；不生成颜色×尺码笛卡尔积；标准名称不从标题推断。

- [x] **Step 1: 写一致性和候选边界失败测试**

  覆盖事务中途切换 publication/dedup/config/catalog pointer、经营独有/退货独有、2 个异常、规范化碰撞、已发布无事实真零、缺报 null 和不完整 dedup。

- [x] **Step 2: 实现只读 RR snapshot coordinator**

  事务开始后一次性固定 site config、scope、current catalog（若有）、两类日报 members、pointer revisions、ready dedup digest 和 `fact_cutoff_at`；事务内禁止再次解析裸 current。

- [x] **Step 3: 生成完整 publication snapshot 与 fact tuple payload**

  coverage 内每个日×报表都有 published 或 explicit missing member；active-row projection digest 只含允许的身份/指标字段。tuple 固定 publication、dedup、site config、cutoff 和 digest。

- [x] **Step 4: 生成有界、确定性的候选**

  从 publication members＋sidecar 进入数据库；严格三段格式只作建议。保留事实出现的实际变体、新旧别名、碰撞、未匹配和排除候选；排序完全显式，不依赖数据库偶然顺序。

- [x] **Step 5: 生成 `source_evidence_jcs_v1`**

  按规范聚合 Seller SKU、标题、ASIN/FNSKU、日期和次数，生成安全 preview/digest/SafeSourceRef。订单号、fulfillment center、牌照和留言不得进入 payload。

- [x] **Step 6: 在独立写事务幂等持久化 exact payload**

  使用 export operation token 幂等写入完整成员、tuple、candidate、evidence 和 digest，但本任务只能保持 export/publication snapshot/fact tuple 为 `building`，artifact/workbook 分类字段为空。写事务不得替换成“此刻最新”的任何组成项；Task 7 最终化以前任何目录、下载或上传都不得引用。

- [x] **Step 7: 运行 unit＋RR 并发门**

  ```powershell
  pwsh .\scripts\run-product-catalog-mysql-tests.ps1 -Versions @("8.0") -PytestPaths @("tests/unit/catalog/test_fact_tuples.py", "tests/unit/catalog/test_candidates.py", "tests/unit/catalog/test_evidence.py", "tests/integration/test_catalog_snapshot_consistency.py")
  ```

  Expected: 并发切换不会混入响应；同一 tuple 产生相同 candidate/evidence bytes；34/224 分类能力、实际变体、missing/zero/partial 语义均可由 fixture 证明；本任务结束时没有未分类 payload 被标成 ready。

  Actual (2026-08-21): PASS。实现 `START TRANSACTION WITH CONSISTENT SNAPSHOT, READ ONLY` 的单一 MySQL RR 读取，事务内固定 current site config、已确认 scope、可空 current catalog、两类日报 publication/version/pointer revision、ready dedup snapshot/digest/revision 和 fact cutoff；active-row digest 使用闭合的身份/指标 DTO，退货 order ID、fulfillment center、license plate 和 customer comments 无法进入投影。coverage 为逐日×双报表完整矩阵，published-zero 与 explicit-missing 保持不同语义；fact tuple、candidate、evidence 和组合 payload digest 都由冻结 JCS bytes 确定。

  候选只对安全、总长和分段有界且匹配 `^[0-9]+-[^-]+-[^-]+$` 的 Seller SKU 提建议，保留实际观察变体而不做颜色×尺码笛卡尔积；标准名称保持 null。规范化碰撞、unsafe、unmatched、既有 alias mapping 和 exclusion 都有显式确定顺序。`source_evidence_jcs_v1` 严格按 scope＋Seller SKU 原值＋report type 聚合，distinct tuple 使用 null-first、原始 UTF-8 bytes 排序并经 frozen JCS 计算 `sha256:` digest；34 valid/224 unmatched fixture 已锁定分类能力。

  0022 前向修正了三个 Task 6 持久化必需契约：fact tuple 以独立 `return_dedup_snapshot_status='ready'` 复合 FK 引用 ready dedup 而自身仍为 building；逐条 evidence 唯一键使用真实 source row 身份，不错误折叠跨日出现次数；新增不可变 `catalog_export_payloads` 保存 exact candidate/evidence JSON 与 digest，并给 source refs 增加 `export` resource kind。独立写事务只读取 operation token、tuple digest 和 immutable evidence 身份以实现幂等，不读取任何 current pointer；export/publication snapshot/fact tuple 均保持 building，workbook/artifact/failure 分类字段为空。

  指定 MySQL 8.0 Task 6 门最终为 `12 passed`；迁移 schema/grant 复核为 `5 passed`，全量 contracts 为 `87 passed`，Task 6 路径 Ruff、scoped mypy 和 `git diff --check` 均 PASS。RR 实库测试在读事务冻结 publication 后并发撤下经营指针并递增 revision，后续 active rows 和写事务仍使用旧 frozen version，证明没有混入并发 current。全部 DDL/写入只发生在 runner-owned 随机 disposable database；runner 容器已清理，未连接业务库，未执行 Git integration 操作。

### Task 7: 安全 XLSX、export worker 和 raw-body 上传

**Files:**

- Create: `backend/app/catalog/ooxml.py`、`backend/app/catalog/workbook.py`、`backend/app/catalog/export_service.py`、`backend/app/catalog/upload_service.py`
- Create: `backend/app/worker/catalog_exports.py`
- Modify: `backend/app/worker/runner.py`、`backend/pyproject.toml`、`backend/requirements.in`、`backend/requirements.lock`
- Reuse without catalog-state coupling: `backend/app/imports/storage.py`
- Create tests: `backend/tests/unit/catalog/test_ooxml.py`、`test_workbook.py`、`test_export_service.py`、`test_raw_upload.py`
- Create integration: `backend/tests/integration/test_catalog_export_finalization.py`
- Create fixtures: `backend/tests/fixtures/catalog_workbooks/README.md`

**Interfaces:**

- Consumes: Task 6 的 building exact candidate/evidence/fact tuple payload 与 finalizer contract、现有内容寻址 storage primitive、规格的六工作表逐列契约。
- Produces: hardened OOXML envelope、纯 workbook codec、`building|ready|failed` export 和 `ready|capacity_exceeded` workbook status、bounded raw upload。
- Invariants: codec 不访问 DB/current；生成文件必须通过同一 uploader 往返；容量超限无截断 artifact、改走 online；每个 import 自身保存原文件名/media type。

- [x] **Step 1: 先写恶意 ZIP/OOXML 和容量失败 fixtures**

  覆盖 traversal、大小写/Unicode 冲突 member、129 members、zip bomb、CRC/header mismatch、未知 part/relationship、external link、DTD/entity、宏、公式、隐藏 sheet/row/column、错 sheet/列/type、尾部数据和所有 exact boundary。

- [x] **Step 2: 锁定并验证依赖**

  把 `openpyxl`、`defusedxml` 加入 project、input 和 lock；记录版本与 hash。所有 XML 入口使用安全解析；`openpyxl` 只在 envelope allowlist 后以 `read_only=True,data_only=False,keep_links=False` 打开。

- [x] **Step 3: 实现 ZIP/OOXML 安全 envelope**

  判定顺序固定为 archive 实际字节 → central directory/member count → path/duplicate/allowlist/header → 流式解压大小/比例。最多 128 members、单 member 64 MiB、累计 200 MiB、200:1，上传最多 `min(APP_STORAGE_MAX_UPLOAD_BYTES,100 MiB)`。

- [x] **Step 4: 实现六表纯函数 codec**

  精确处理 `生成信息/款式主档/SKU变体/SellerSKU映射/待处理异常/来源证据` 的顺序、表头、RO/E/K/C、T/I、nullable 和 group decision；危险文本只写安全预览和 digest。

- [x] **Step 5: 实现 export worker 与容量矩阵**

  从 Task 6 exact payload 生成临时 archive，再用 uploader 自检。最终短事务重新校验 operation token、building 状态和全部 digest，只在 artifact 安全通过或容量违规被完整分类后，同时把 export/publication snapshot/fact tuple 推进 ready 并写 `workbook_status=ready|capacity_exceeded`；ready artifact 使用固定下载名/header。行/字节/压缩比容量违规保存结构化 violations 并删除临时文件；未知 part 等非容量安全失败使整组进入 failed。最终化禁止重读 current。

- [x] **Step 6: 实现 raw-body bounded upload**

  required `Idempotency-Key`、percent-encoded `X-Original-Filename` 和精确 Content-Type；先校验 Content-Length，再流式 spool＋实际计数＋SHA-256。通过安全门后才原子登记 raw file 和 catalog import；不创建日报 `import_batches`。

- [x] **Step 7: 运行安全与 round-trip 门**

  ```powershell
  .\.venv\Scripts\python.exe -m pytest backend/tests/unit/catalog/test_ooxml.py backend/tests/unit/catalog/test_workbook.py backend/tests/unit/catalog/test_export_service.py backend/tests/unit/catalog/test_raw_upload.py -q
  pwsh .\scripts\run-product-catalog-mysql-tests.ps1 -Versions @("8.0") -PytestPaths @("tests/integration/test_catalog_export_finalization.py")
  ```

  Expected: 恶意/超限输入在业务解析前稳定失败；六表 generator→uploader 原样往返；capacity exceeded 有完整 online 路径且绝无部分文件。

  实施证据（2026-08-21）：锁定 `openpyxl==3.1.5`、`defusedxml==0.7.1` 与传递依赖 `et-xmlfile==2.0.0` 及全部 hashes；四组规定单元/安全门为 `24 passed`，MySQL 8.0 export finalization 为 `3 passed`，catalog schema/grants 为 `5 passed`，迁移/bootstrap/grant contracts 为 `55 passed`。Task 7 文件的 Ruff 与 scoped strict mypy 均 PASS，`git diff --check` PASS，严格文本门 PASS。baseline 门只报告此前用户已单独授权且仓库外 ledger/current SHA-256 仍精确匹配的 `backend/tests/unit/datasets/test_dataset_repository.py`，没有新未登记越界路径。0022 forward correction 以 publication snapshot 的窄 `building→ready|failed` trigger、FK status cascade、export capacity JSON 与 catalog import UUID v4 operation token 完成；MySQL 不允许在 `ON UPDATE CASCADE` 子列上重复 CHECK，因此 tuple status 由父表已检查 status＋复合 FK 唯一约束，不放宽状态集合。

### Task 8: XLSX/online import、状态机、counter、幂等和 rebase

**Files:**

- Create: `backend/app/catalog/import_repository.py`、`backend/app/catalog/import_service.py`、`backend/app/catalog/commands.py`、`backend/app/catalog/workflow.py`
- Create: `backend/app/worker/catalog_imports.py`
- Modify: `backend/app/worker/runner.py`、`backend/app/worker/cli.py`
- Create tests: `backend/tests/unit/catalog/test_workflow.py`、`test_commands.py`
- Create integration: `backend/tests/integration/test_catalog_import_workflow.py`、`test_catalog_worker.py`、`test_catalog_command_recovery.py`

**Interfaces:**

- Consumes: Task 3 import/workflow/command schema、Task 7 parser/upload、Task 6 export baseline。
- Produces: 独立 catalog import 状态机、五种 row union 分页、1–500 mutation 原子批、parse lease、防 ABA counters、validate/submit/preview/reject/withdraw/rebase 和可恢复命令结果。
- Invariants: 不复用日报 import 状态机；GET 无业务副作用；同 token 同语义只返回原 effect；成功 counter 永不回退或重复；rebase 不覆盖决定。

- [x] **Step 1: 先写完整状态转移表失败测试**

  覆盖 `uploaded|parsing|parse_failed|needs_attention|validated|ready_for_approval|approved|rejected|withdrawn|superseded` 的合法边、非法跳转、owner/current-role、高风险权限和终态。

- [x] **Step 2: 实现 parse attempt lease 与防 ABA**

  `workflow_revision`、`parse_attempt_revision` 均从 0 开始单调；领取/续租/释放/过期都推进 workflow revision。worker 完成必须同时匹配状态、两个 revision 和不可猜 lease token。

- [x] **Step 3: 实现 XLSX 与 from-export 统一草稿投影**

  XLSX 经 parser 写 rows/issues；from-export 在一个事务复制完整候选并直接进入 `needs_attention|validated`、`parse_attempt_revision=0`，不伪造 raw file 或 parsing attempt。

- [x] **Step 4: 实现五 section 服务端分页与 row union**

  `styles|skus|mappings|exceptions|evidence` 默认按 binary row key；page size 1–200；detail 只返回五 section counts。跨页 revision 变化必须让调用方从第一页重读。

- [x] **Step 5: 实现 1–500 条原子 mutation**

  固定 create/update/delete/map/exception mutation schema、client mutation key 和字段级安全 issue pointer；501、跨批引用、环、删除系统/被引用行、stale revision 都零写入。

- [x] **Step 6: 实现 command claim/effect/counter 和恢复**

  semantic hash 覆盖 route/resource/body/expected counters，不含 token；业务变化与 effect 同事务。commit 回执丢失、claim-only、crash-after-effect 和 `outcome_unknown` 重试返回首次结果且不重复 issue/event/counter。

- [x] **Step 7: 实现 validate/submit/preview/reject/withdraw/rebase**

  preview 是持久化 projection 的幂等写，30 分钟过期但不改状态；rebase 明确指定 ready replacement export，原批次 superseded、后继重做完整验证，冲突和失效证据显式保留。

- [x] **Step 8: 运行 workflow 与恢复门**

  ```powershell
  pwsh .\scripts\run-product-catalog-mysql-tests.ps1 -Versions @("8.0") -PytestPaths @("tests/unit/catalog/test_workflow.py", "tests/unit/catalog/test_commands.py", "tests/integration/test_catalog_import_workflow.py", "tests/integration/test_catalog_worker.py", "tests/integration/test_catalog_command_recovery.py")
  ```

  Expected: 所有状态和 counter 可重放；1/500 成功、501 原子拒绝；ABA、stale、权限降级和崩溃恢复均无重复副作用。

  实施证据（2026-08-21）：实现独立 catalog workflow/permission 纯模型、XLSX 与 from-export 统一草稿投影、五 section binary-key 服务端分页、1–500 原子 mutations、parse lease/revision/token 防 ABA、command claim/effect 恢复，以及 validate/submit/preview/reject/withdraw/rebase。preview 持久化 30 分钟 projection 而不改 workflow；online rebase successor 不伪造 raw file 或 parse attempt。worker 通过 content-addressed verified read 完成 parse/project/finalize，失败和恢复路径保持 counter 单调。

  0022 以前向修正增加 parse attempt 与 command claim 的受控 transition triggers、列级最小 UPDATE grants 和 partial-upgrade signature 校验；过长的 candidate row key 改用 URL-safe base64 SHA-256，保持 schema `VARCHAR(64)` 边界。Task 8 规定 MySQL 8.0 门为 `35 passed`，catalog schema/grants 为 `5 passed`，migration/bootstrap/grant contracts 为 `55 passed`；Task 8 路径 Ruff、scoped mypy 和 `git diff --check` 均 PASS。baseline 门仍只报告 Task 5 已由用户单独授权、仓库外 ledger/current SHA-256 精确匹配的 `backend/tests/unit/datasets/test_dataset_repository.py`，没有发现新的越界路径。全部 DDL/写入只发生在 runner-owned 随机 disposable database；未连接业务库，未执行 Git integration 操作。

### Task 9: 稳定身份、revision、reservation、projection 和批准事务

**Files:**

- Create: `backend/app/catalog/repository.py`、`backend/app/catalog/queries.py`、`backend/app/catalog/projection.py`、`backend/app/catalog/validation.py`、`backend/app/catalog/approval.py`、`backend/app/catalog/service.py`
- Modify: `backend/app/catalog/commands.py`、`backend/app/catalog/workflow.py`
- Create integration: `backend/tests/integration/test_catalog_repository.py`、`test_catalog_identity_reservations.py`、`test_catalog_approval.py`、`test_catalog_concurrency.py`、`test_catalog_projection_expiry.py`

**Interfaces:**

- Consumes: Task 8 validated/ready projection、Task 6 candidate/evidence tuple、Task 3 identity/catalog schema。
- Produces: stable style/SKU IDs、永久 reservations、immutable revisions/members/mappings/exclusions/events、current projection、normal/high-risk approval 和 restore-as-forward-version。
- Invariants: `audit_only` 零身份/零 revision/零 member/零 reservation；任一 undecided group 阻断整份；批准在一个事务内全部完成或全部回滚。

- [x] **Step 1: 先写身份、风险和并发失败测试**

  覆盖字符串/hash 派生 ID、reservation 重用、不可达 candidate、undecided/collision、高风险越权、projection expiry、base/current drift、双审批和恢复不兼容生产事实。

- [x] **Step 2: 实现 identity/revision repository**

  数据库分配稳定 ID；revision 从 1 开始；current projection 只由批准事务更新；所有历史实体 append-only，停用或改名不释放旧键。

- [x] **Step 3: 实现永久 reservation**

  批准前按固定锁顺序检查款号、款色码和内部展示 SKU 规范键；事务提交后无 release/delete API，旧键永远归原 ID。

- [x] **Step 4: 实现最终可达性与 `audit_only` 投影**

  根集合和闭包严格按规格重算；映射到既有 SKU 或全部排除会使未采用系统候选 audit-only；用户要保留无来源身份必须显式创建 `user_created` 行。

- [x] **Step 5: 实现完整验证、diff 和风险**

  重算条件必填、唯一性、reservation、evidence drift、新匹配键、scope/base drift、事实引用和 normal/high 风险。草稿混合高风险时整份只允许 admin＋原因。

- [x] **Step 6: 实现单事务批准与命令恢复**

  固定锁定 workflow、catalog sync/pointer 和 reservations；一次写 identities、revisions、members、mapping/exclusion/evidence、event、audit、command effect/counter 和 current pointer。commit 后崩溃重试恢复原结果。

- [x] **Step 7: 实现 restore 为向前版本**

  只允许 admin＋原因＋expected publication revision；复制目标版本内容和原 ready fact tuple，创建新版本号并做当前生产事实兼容检查，绝不把 pointer 直接回拨。

- [x] **Step 8: 运行批准与并发门**

  ```powershell
  pwsh .\scripts\run-product-catalog-mysql-tests.ps1 -Versions @("8.0") -PytestPaths @("tests/integration/test_catalog_repository.py", "tests/integration/test_catalog_identity_reservations.py", "tests/integration/test_catalog_approval.py", "tests/integration/test_catalog_concurrency.py", "tests/integration/test_catalog_projection_expiry.py")
  ```

  Expected: 首次批准原子创建 catalog V1；并发最多一个 CAS 胜者；audit-only 计数零增长；失败事务不留半套目录或可复用 reservation。

  实施证据（2026-08-21）：实现服务端唯一可达性闭包，既有正式 ID、`user_created` 和最终 mapped 目标为根，递归纳入 SKU 所属款式；不可达 system/null-ID 候选稳定标记 `audit_only`。完整批准验证只对 included 行执行条件必填、引用、身份规范键和重复组合检查，并把既有身份字段、已批准 mapping/exclusion 改绑或理由变化分为 high risk；projection 绑定 workflow、validation、base、publication counter、ready fact tuple、risk、diff 和 30 分钟 expiry。

  批准事务按 command claim/effect、目录 pointer、草稿、projection、身份和 reservation 顺序复核，在一个事务内由 MySQL 分配 style/SKU ID，追加 revision、永久 key reservations、不可变 catalog version/members/mappings/exclusions、publication event/audit/effect，并 CAS 单调推进目录与 workflow counter。不可变 reservation 使用唯一键 `INSERT IGNORE` 后无锁复核 owner，在最小权限下串行化并发竞争；不提供 release/delete API。restore 复用目标 ready fact tuple 和不可变成员创建新的高风险向前版本，绝不回拨 pointer；同 token 重放返回首次版本。

  Task 9 规定 MySQL 8.0 五文件门为 `7 passed`；与 Task 8 workflow/recovery 合并回归为 `42 passed`。测试中的两个不可达 system 候选在批准前后身份/revision/member/reservation 增量均为零；首次批准生成 catalog V1，重复 token 不重复版本，并发 stale counter 只有一个 CAS 胜者，restore 生成 V2/revision 2。Task 9 路径 Ruff、scoped mypy 和 `git diff --check` 均 PASS；全部 DDL/写入只发生在 runner-owned 随机 disposable database，未连接业务库，未执行 Git integration 操作。

### Task 10: Catalog API、OpenAPI、RBAC、evidence/reveal 和原文件

**Files:**

- Create: `backend/app/api/catalog_common.py`、`catalog_scope.py`、`catalog_dedup.py`、`catalog_exports.py`、`catalog_imports.py`、`catalog_queries.py`、`catalog_admin.py`
- Modify: `backend/app/main.py`、`backend/app/api/errors.py`
- Modify: `backend/tests/unit/test_openapi_contract.py`
- Create tests: `backend/tests/unit/test_catalog_api.py`、`backend/tests/integration/test_catalog_security.py`、`test_catalog_evidence_reveal.py`、`test_catalog_api_workflow.py`
- Regenerate: `frontend/src/api/generated.ts`

**Interfaces:**

- Consumes: Tasks 4–9 的 scope、dedup、export/upload、workflow、approval、query 和 command recovery。
- Produces: 规格固定的 `/api/catalog/*` 资源、严格 OpenAPI、统一安全错误 envelope、server-computed permissions、raw XLSX 下载和 resource-bound reveal。
- Invariants: 所有 JSON model `additionalProperties=false`；写请求强制 session/RBAC/CSRF/site/idempotency/expected counters；viewer 永不获得 raw source；判定顺序不泄露资源存在性。

- [x] **Step 1: 先写 OpenAPI、严格输入和安全矩阵失败测试**

  覆盖额外字段、raw-body 不是 multipart、required headers、CSRF、site spoof、viewer/data_manager/admin、current role 降级、同 token 重放和所有稳定 reason code。

- [x] **Step 2: 扩展统一错误 renderer**

  只允许白名单 `meta` counters、safe issue/projection fields；未知 validation body、SQL/异常文本和 raw source 一律丢弃。403/404/409 的顺序和 envelope 用表驱动测试固定。

- [x] **Step 3: 实现 scope、dedup 和 export/import routers**

  暴露 Task 1 精确冻结的 scope status/confirm、dedup groups/decisions、exports status/file、raw imports 和 from-export；路由只负责认证、严格解析和调用 service。

- [x] **Step 4: 实现 import detail/rows 和全部 workflow commands**

  detail 不内联全量行；rows 使用五 section 分页与 optional revision；resume/decisions/validate/submit/preview/approve/reject/rebase/withdraw 要求各自 exact counters，并返回下一次请求所需新 counters/permissions。

- [x] **Step 5: 实现当前 catalog、unmatched、versions/diff/restore 和 command recovery**

  viewer 只读当前批准 styles/SKUs 和安全标识；历史、diff、草稿、原文件和 evidence history 按权限裁剪。命令 GET 只允许原操作者；admin 代查是带新 token/原因的 POST。

- [x] **Step 6: 实现原 XLSX 下载与 evidence/source reveal**

  下载和 reveal 都绑定 site、resource、catalog/import revision 和 membership，写安全审计并返回 `Cache-Control: private, no-store`。草稿 reveal 判定顺序固定 authentication → requested workflow revision → membership：viewer 永远先 403；有读取权但 stale 先 409；current revision 的无效 ref 统一 404。

- [x] **Step 7: 注册 routers 并生成/检查 OpenAPI**

  ```powershell
  pwsh .\scripts\run-product-catalog-mysql-tests.ps1 -Versions @("8.0") -PytestPaths @("tests/unit/test_catalog_api.py", "tests/unit/test_openapi_contract.py", "tests/integration/test_catalog_security.py", "tests/integration/test_catalog_evidence_reveal.py", "tests/integration/test_catalog_api_workflow.py")
  .\scripts\generate-api-client.ps1
  .\scripts\generate-api-client.ps1 -Check
  ```

- [x] **Step 8: 执行日志和资源侧信道检查**

  Expected: Catalog API 与 OpenAPI 无 drift；跨站、权限、revision 和 reveal 顺序全部 PASS；危险来源值不在响应/日志；尚未修改新商品分析 API 或旧 dashboard 语义。

  Actual (2026-08-21): PASS。新增并注册 7 个 catalog router，覆盖冻结的 31 个资源操作；写请求统一要求 CSRF、UUID `Idempotency-Key` 并与 body token 一致，raw XLSX 使用 bounded raw-body spool，viewer 在资源查询前拒绝，draft reveal 固定 role→revision→membership 顺序且 reveal/download 返回 `private, no-store`。canonical disposable Oracle MySQL 8.0 门为 `15 passed`，Tasks 8–9 回归为 `10 passed`；OpenAPI client 已重新生成且 `-Check` PASS，Ruff、scoped mypy、`git diff --check` PASS。修正了 reveal 测试中与 `U+5371 U+9669` 不一致的 UTF-8 base64url 常量，保持可逆编码不变量。

### Task 11: 前端生成契约、请求门、权限代次和安全来源引用

**Files:**

- Regenerate only: `frontend/src/api/generated.ts`
- Modify: `frontend/src/api/client.ts`、`frontend/src/api/client.test.ts`、`frontend/src/app/App.tsx`、`frontend/src/app/App.test.tsx`
- Create: `frontend/src/api/sessionRevocation.ts`、`frontend/src/api/sessionRevocation.test.ts`
- Create: `frontend/src/api/requestGate.ts`、`frontend/src/api/requestGate.test.ts`
- Create: `frontend/src/app/AuthzGenerationContext.tsx`、`frontend/src/app/AuthzGenerationContext.test.tsx`
- Create: `frontend/src/components/source-reference/SafeSourceRefView.tsx`、`SafeSourceRefView.test.tsx`、`SafeSourceRefView.css`
- Create: `frontend/src/components/source-reference/useSensitiveReveal.ts`、`useSensitiveReveal.test.ts`

**Interfaces:**

- Consumes: Task 10 OpenAPI、现有 `requestApi/writeApi`、CSRF 和 stable operation key。
- Produces: 生成类型、canonical request key＋sequence＋authz generation 提交门、全局 authenticated-401 session-revoked 桥、页面权限代次、普通安全引用组件和仅内存 reveal 生命周期。
- Invariants: `generated.ts` 禁止手改；取消请求不等于防乱序；request key 不用展示文本拼接；未知错误正文丢弃；raw upload token 只在 header。

- [x] **Step 1: 先写 client 错误解码和幂等失败测试**

  覆盖 catalog 409 安全 counters、422 decision issues、`outcome_unknown`、同语义复用 UUID、不同语义换 UUID、危险额外字段不进入 `ApiRequestError`、raw body 没有 multipart/JSON 包装，以及同一认证边界的并发 401 只触发一次 session revoke。

- [x] **Step 2: 扩展 caller-supplied safe error decoder**

  保持旧调用兼容；decoder 只保留调用方声明的字段，不保存完整未知 response body、不隐式 console log。JSON command helper 保证 body `operation_token` 与 header `Idempotency-Key` 是同一个 UUID。除 `/api/auth/csrf|login` 外的已认证请求收到 401 时，client 在抛出安全错误前向 `sessionRevocation.ts` 发出边界内幂等事件；桥不保存 response body，也不使用 DOM 全局事件泄露数据。

- [x] **Step 3: 实现 canonical request gate**

  `begin(tuple,authzGeneration)` 返回单调 sequence、AbortSignal 和 `isCurrent()`；固定字段顺序的 JSON tuple 覆盖换行、逗号、NUL-safe encoding 和非 ASCII，证明不同语义不碰撞。

- [x] **Step 4: 实现 `AuthzGenerationContext`**

  主体边界由 principal、roles、site 和 site config 组成；同资源 permissions fingerprint 改变时单调递增。首次观察不算变化；登出、换站或主体变化立即创建新边界并通知敏感缓存 purge。App 为当前已认证边界注册唯一 revoke handler；401 时同步清空 principal/site/CSRF、递增 generation、abort 全部 gates 并 purge，后续并发 401 幂等，重新登录才建立新边界。

- [x] **Step 5: 实现 `SafeSourceRefView`**

  只显示 preview、digest 后缀和 unsafe/truncated 徽标；`source_ref_id` 只作 React key。原值不得进入 `title/data-*`、ARIA、日志、默认复制目标或 URL。

- [x] **Step 6: 实现敏感 reveal 生命周期**

  reveal 只存在 hook 内存；403、当前 key 的 404、草稿 409、全局 session revoke、generation/key/revision 变化和显式 purge 同步清空 code-points、base64、解码结果及 clipboard staging，并保持复制禁用。401 之后即使旧请求返回 200，`isCurrent()` 也必须拒绝提交。

- [x] **Step 7: 挂载 provider、生成客户端并运行门**

  ```powershell
  .\scripts\generate-api-client.ps1
  .\.venv\Scripts\python.exe -m pytest backend/tests/unit/test_openapi_contract.py -q
  .\scripts\generate-api-client.ps1 -Check
  Push-Location frontend
  pnpm exec vitest run src/api/client.test.ts src/api/sessionRevocation.test.ts src/api/requestGate.test.ts src/app/AuthzGenerationContext.test.tsx src/components/source-reference src/app/App.test.tsx
  pnpm exec playwright test
  pnpm typecheck
  Pop-Location
  ```

  Expected: 全部 PASS；危险值和未允许错误字段不出现在 DOM、ARIA、clipboard staging 或错误对象；任一已认证 API 401 都单次回到登录边界且旧响应无法复活敏感状态；现有非认证路由行为不变。

  Actual (2026-08-21): PASS。生成客户端绑定 Task 10 OpenAPI；client 仅保留调用方 allowlist counters/issues，新增 body/header 同 UUID command helper。实现 collision-safe tuple request gate、全局单次 session revoke、Authz generation、敏感 purge registry、SafeSourceRefView 和 resource-bound reveal hook。聚焦 Vitest `37 passed`，默认 Playwright `6 passed`，typecheck、lint、production build 与 OpenAPI `-Check` 均 PASS；并发 401、迟到 response、403/404/409、key/revision/generation 变化均有清理测试。

### Task 12: 商品主档、在线审核、问题定位、版本和未匹配 UI

**Files:**

- Create: `frontend/src/features/catalog/catalogTypes.ts`、`catalogApi.ts`、`catalogApi.test.ts`、`catalogState.ts`、`catalogState.test.ts`、`catalogImportState.ts`、`catalogImportState.test.ts`
- Create: `frontend/src/features/catalog/CatalogLayout.tsx`、`CatalogHomePage.tsx`、`CatalogHomePage.test.tsx`、`CatalogStylePage.tsx`、`CatalogStylePage.test.tsx`
- Create: `frontend/src/features/catalog/CatalogExportPanel.tsx`、`CatalogExportPanel.test.tsx`、`CatalogImportPage.tsx`、`CatalogImportPage.test.tsx`
- Create: `frontend/src/features/catalog/CatalogImportSectionTable.tsx`、`CatalogImportSectionTable.test.tsx`、`CatalogIssueSummary.tsx`、`CatalogIssueSummary.test.tsx`
- Create: `frontend/src/features/catalog/CatalogWorkflowActions.tsx`、`CatalogWorkflowActions.test.tsx`、`CatalogEvidencePanel.tsx`、`CatalogEvidencePanel.test.tsx`
- Create: `frontend/src/features/catalog/CatalogUnmatchedPage.tsx`、`CatalogUnmatchedPage.test.tsx`、`CatalogVersionsPage.tsx`、`CatalogVersionsPage.test.tsx`、`CatalogWorkspace.css`
- Modify: `frontend/src/app/App.tsx`、`frontend/src/app/App.test.tsx`
- Create E2E: `frontend/tests/e2e/catalog-workflow.spec.ts`、`frontend/tests/e2e/catalog-sensitive-reveal.spec.ts`

**Interfaces:**

- Consumes: Task 11 类型、request gate、authz generation、SafeSourceRef 和安全错误 decoder；Task 10 全部 catalog API。
- Produces: `/catalog`、`/catalog/styles/:style_id`、`/catalog/imports/:import_id`、`/catalog/unmatched`、`/catalog/versions` 及完整 export→XLSX/from-export→审核→批准体验。
- Invariants: 导航隐藏不是鉴权；页面只采用服务端 counters/permissions/projection；issue pointer 相对单行；projection state 只由重读服务端结果决定；`catalogTypes.ts` 只定义本地 view state/判别 helper，不复制生成 wire contract。

- [x] **Step 1: 写 API、URL、raw upload 和 command 失败测试**

  固定 query/header/body、文件名编码、MIME、from-export 三方 revision CAS、export 状态矩阵、五 section 分页和所有 workflow command。选中文件生成一个 token；同一选择重试复用，重新选文件换 token。

- [x] **Step 2: 实现 layout、当前主档和款式详情**

  无 current catalog 显示“商品主档尚未初始化”；有目录时按服务端分页显示款号、标准名称、状态和实际变体。viewer 只见批准主档和 SafeSourceRef，证据/revision 入口按 permissions 裁剪。

- [x] **Step 3: 实现 export、下载、raw upload 和 from-export**

  building 轮询使用 request gate；ready＋workbook ready 才下载；capacity exceeded 显示具体 violation 和在线审核入口。online import 的 `raw_file_id=null`，不能显示原文件下载。

- [x] **Step 4: 实现五 section 表和原子 mutations**

  Styles/SKUs 可建 user-created；mappings/exceptions 按 group 原子保存；evidence 只读。明确显示“将进入目录”与“仅保留审计，不创建身份”；成功后按新 revision 重读受影响 sections。

- [x] **Step 5: 实现字段 issue、汇总和焦点**

  可修复 issue 将目标 input 设 `aria-invalid` 并用稳定安全 ID 关联 `aria-describedby`；`field=null` 和组级问题只在安全汇总。decision error 先按 mutation ID 定位，再解释相对 pointer；不得混用 row `/target_internal_display_sku` 与 mutation check 字段。

- [x] **Step 6: 实现 workflow actions 和冲突恢复**

  Resume、validate、submit、preview、approve、reject、rebase、withdraw 全部使用响应 counters。任何 mutation/counter 变化废弃 projection；普通自批与高风险 admin＋原因由 permissions 驱动。普通 409 保留安全本地编辑。

- [x] **Step 7: 实现 evidence/reveal、unmatched 和 versions**

  Approved evidence、approved reveal、draft reveal 使用不同 endpoint kind 和完整 resource key。当前 key 的 403/404 或 draft 409 先 purge；409 只采用安全 counters 重读，用户必须再次显式 reveal。版本恢复只向 admin 显示。

- [x] **Step 8: 接入路由并运行目录 UI 门**

  ```powershell
  Push-Location frontend
  pnpm exec vitest run src/features/catalog src/api/requestGate.test.ts src/app/AuthzGenerationContext.test.tsx src/components/source-reference src/app/App.test.tsx
  pnpm exec playwright test tests/e2e/catalog-workflow.spec.ts tests/e2e/catalog-sensitive-reveal.spec.ts --project=chromium
  pnpm typecheck
  pnpm lint
  Pop-Location
  ```

  Expected: 全部 PASS；乱序、字段焦点、revision 冲突和敏感清理有证据；旧 dashboard 产品体验和旧分析 API 尚未切换。

  Actual (2026-08-21): PASS。新增 `/catalog`、稳定 style 详情、import 五 section、unmatched 与 versions 路由；实现 export 轮询/download/from-export、raw XLSX 选件 token 生命周期、行级原子 mutation、validate/submit/preview/approve/reject/withdraw/resume/rebase 和 permissions 驱动操作。evidence 列表只渲染 SafeSourceRef，显式 reveal 绑定 import/revision/resource key 并使用 Task 11 purge。聚焦 Vitest `45 passed`、catalog Playwright `2 passed`、默认 Playwright `6 passed`，typecheck、lint、production build PASS；旧 dashboard/legacy API 未切换。

### Task 13: Milestone A——真实商品主档初始化与审核 live 验收

**Files:**

- Modify: `frontend/playwright.config.ts`、`frontend/vite.config.ts`、`frontend/tsconfig.node.json`、`frontend/tests/e2e/tsconfig.json`
- Create: `frontend/playwright.catalog-live.config.ts`
- Create: `backend/tests/live/__init__.py`、`backend/tests/live/product_catalog_live_harness.py`、`backend/tests/unit/auth/test_product_catalog_live_harness.py`
- Create: `frontend/tests/e2e/live/global-setup.ts`、`global-teardown.ts`、`catalogLiveFixtures.ts`、`catalog-milestone-a.live.spec.ts`
- Create: `scripts/run-product-catalog-live-e2e.ps1`

**Interfaces:**

- Consumes: Tasks 1–12 的真实 migration、最小权限、FastAPI、MySQL、XLSX、catalog API 和 React UI。
- Produces: 无 `page.route()` mock 的 React → FastAPI → MySQL 目录初始化证据，以及 Tasks 18/20 复用的 runner ownership/cleanup 协议。
- Invariants: 默认 Playwright 排除 live；live config 无 `webServer`；runner 不复用/终止已有服务；只清理 run manifest 证明属于本 run 的账号、事实、进程和文件；禁止为 live 增加 test-only API、特殊授权 header、生产故障开关或隐藏业务入口。

- [x] **Step 1: 先写 harness preflight/seed/cleanup 失败测试**

  覆盖非 loopback、错误 schema 名、非 Oracle MySQL、普通账号/事实存在、伪造 run ID、重复 seed、部分失败、PID 复用、live config 意外出现 `webServer/reuseExistingServer` 和无法证明归属的 cleanup 目标；模糊目标一律拒绝。

- [x] **Step 2: 实现独占 runner 与进程归属**

  启动前验证随机 loopback 端口未占用；FastAPI 无 reload，Vite strictPort。Windows 直接以隐藏窗口启动 Python/Node 根进程，并把每棵进程树放入 kill-on-close Job Object；run manifest 记录根 PID、启动时间、命令指纹、run ID 和全部后代。所有退出路径使用 `try/finally`，cleanup 逐树复核 Job/run ownership 后才终止，既不能遗漏 Vite/esbuild 后代，也不能按名称误杀外部进程。

- [x] **Step 3: 实现 run-scoped DB、storage 和身份**

  只接受 `clsen_data_test*`＋`utf8mb4` URL；使用 migration/runtime/grant-admin 分离身份。Harness 创建本 run admin；global setup 经真实 API 创建 data_manager/viewer 和三份私有 storageState，密码不进命令行/stdout。

- [x] **Step 4: 建立 live Playwright 配置**

  首版只收集 `catalog-milestone-a` project，不声明 webServer。Runner 通过操作系统端口的 owning PID、进程启动时间/命令指纹和既有健康响应共同证明 FastAPI/Vite 属于本 run；只有 HTTP 200 不足以继续，也不修改应用增加 run-ID 响应。E2E tsconfig 递归包含 live 目录；默认 config 显式 `testIgnore`。

- [x] **Step 5: 完成真实在线审核首次批准**

  Data manager 从 ready export 建 online 草稿，补齐标准名称/展示 SKU/颜色/尺码，改映一个候选、修正一个异常并排除另一个；验证 audit-only 零身份增长，再执行 decisions→validate→submit→preview→approve 得到 catalog V1。

- [x] **Step 6: 完成真实 XLSX、权限和安全验收**

  下载最终 ready XLSX，使用 fixture helper 只改 E 字段，再经浏览器 raw upload 到可审核状态。Viewer 读当前主档但对 import/original/version/diff/evidence history 得真实 403；manager reveal 可逆、普通 DOM 无危险原值。

- [x] **Step 7: 运行并保存里程碑 A 证据**

  ```powershell
  .\.venv\Scripts\python.exe -m pytest backend/tests/unit/auth/test_product_catalog_live_harness.py -q
  Push-Location frontend
  pnpm exec vitest run src/features/catalog src/app/App.test.tsx
  pnpm exec tsc -p tests/e2e/tsconfig.json --noEmit
  pnpm typecheck
  pnpm exec playwright test --config=playwright.catalog-live.config.ts --list --project=catalog-milestone-a
  Pop-Location
  .\scripts\run-product-catalog-live-e2e.ps1 -Milestone Catalog
  if ([string]::IsNullOrWhiteSpace($env:APP_PLAN_BASELINE_ROOT)) { throw "APP_PLAN_BASELINE_ROOT is required" }
  .\scripts\check-plan-worktree-baseline.ps1 -PathManifest .\docs\superpowers\plans\2026-08-20-product-style-variant-analytics-foundation-file-manifest.json -BaselineRoot $env:APP_PLAN_BASELINE_ROOT
  ```

  Expected: 全部 PASS；保存 run ID、migration head、catalog version ID、export/workbook checksum、收集清单和 cleanup PASS。用户现有服务、账号和数据未被复用、终止或修改。

  Actual (2026-08-24): PASS。最终 canonical run ID 为 `a1acf382e2e84ab5bf7ba064d448081f`，在 runner-owned 随机 disposable Oracle MySQL 上从 fresh schema 迁移到唯一 head `0022`，以分离的 migration/grant-admin/runtime 身份启动 FastAPI、Vite 和 worker；Playwright 仅收集并执行 `catalog-milestone-a`，无 `webServer`、route mock 或 test-only API，结果为 `1 passed`。真实浏览器流程完成 ready export/download、online import、两款两 SKU 草稿补全、一个严格候选改映、一个异常修正、另一个异常排除、validate→submit→preview→approve，并创建 catalog version ID/number `1/1`；批准 effect 证明 `audit_only_row_count=2`，最终仅创建 1 个稳定 style 和 1 个稳定 SKU，未采用系统候选未创建身份。下载 workbook SHA-256 为 `289e4d9b223f95f9f0fe89d9d8a4678db48719c469917939dfb0167881bb8f82`，浏览器修改 E 字段后 raw upload 到 `needs_attention`；viewer 对 import/original/version/diff/evidence history 得到真实 403，manager 的危险标题普通 DOM 使用安全预览，只有显式 resource-bound reveal 可逆，离开资源后清除。

  完整门在同一候选上为 harness `10 passed`、目录/App Vitest `42 passed`、E2E TypeScript、全前端 typecheck/lint/build、OpenAPI client `-Check` 和 `git diff --check` 全部 PASS；live list 精确为 1 test/1 file。Evidence 保存于仓库外 `C:\Users\20937\AppData\Local\Temp\clsen-catalog-live-evidence-a1acf382e2e84ab5bf7ba064d448081f.json`，其中 cleanup 为 `PASS`，逐项证明 Job Object closed、容器 label 复核后删除、私有 storageState 删除和 runtime root 删除；复核无 run 容器、进程或临时根残留。私有 baseline checker 唯一报告 Task 5 已经用户单独授权的 `backend/tests/unit/datasets/test_dataset_repository.py`，仓库外 `task5-authorized-scope-expansion.json` 记录的 current SHA-256 `97dfbe30dfb83e6caaf78df048df16bfa564c607b74807f9957537d694e72a67` 与当前文件一致，没有新越界路径，baseline 未被改写。未连接或写入业务库，未执行 Git staging/commit/merge/rebase/tag/push。

#### Milestone A pause

Task 13 PASS 后暂停并交付体验证据。此时商品主档可以独立使用，但旧 `product-ledger/product-card` 和旧 dashboard 产品入口仍完整保持 `legacy_parser`；未经下一里程碑授权不得把它描述为颜色/尺码分析已切换。

Milestone A acceptance (2026-08-24): 用户在本机成功重跑 `run-product-catalog-live-e2e.ps1 -Milestone Catalog` 后书面确认“成功，进行下一步吧”，验收 Milestone A 并授权进入 Task 14。

---

## Milestone B：稳定款式产品总表与颜色/尺码趋势双轨体验

### Task 14: MySQL 商品分析、coverage、六桶与 current/snapshot 一致性

**Files:**

- Create: `backend/app/analytics/style_models.py`、`backend/app/analytics/style_sql.py`、`backend/app/analytics/style_repository.py`、`backend/app/analytics/style_service.py`
- Create tests: `backend/tests/unit/analytics/test_style_models.py`、`test_style_sql.py`、`test_style_service.py`
- Create integration: `backend/tests/integration/test_style_analytics.py`、`test_style_analytics_consistency.py`、`test_style_analytics_reconciliation.py`

**Interfaces:**

- Consumes: 已批准 catalog V1、publication/dedup/config fact tuple 和稳定 `style_id/sku_id`。
- Produces: 有界 RR 查询、`MetricValue/TrendPoint/CoverageBlock/MetricTotals/PublicationRefs`、站点六桶、款式守恒、列表分页和 card payload；本任务不注册 HTTP 路由。
- Invariants: MySQL 完成过滤、排序、分页和聚合；Python 只接收页行、日期×活动系列、coverage/reconciliation；新查询绝不调用 legacy parser。

- [x] **Step 1: 写五项指标与精确数值失败测试**

  固定 units、USD sales 两位 decimal string、returns quantity、sessions 和 conversion 六位 `ROUND_HALF_UP`；B2B 不重复相加；negative business facts 原样聚合；分母小于等于 0 为 undefined。

- [x] **Step 2: 写 daily/range 状态矩阵失败测试**

  覆盖 published/missing、observed/zero/missing_report/undefined_denominator、`no_observed_reports`、partial、event-date indeterminate 特例、report-date coverage 和未来 `to` 拒绝；明确覆盖“事件日在 `[from,to]` 内、贡献它的退货 publication report date 在区间外”，该事件不得漏数或变成 null。

- [x] **Step 3: 写身份与 dedup 六桶守恒测试**

  `source=mapped+unmatched+excluded+duplicate+unresolved` 只对 evaluable 指标执行；duplicate/unresolved 先分桶再做身份决定；正式款式总计只等于 mapped。未归类/排除不能伪造款式行。

- [x] **Step 4: 写款式/颜色/尺码/SKU 守恒测试**

  所有实际 SKU＝款式；同色尺码＝颜色；全部颜色＝款式；size 维度只等于选中颜色，不宣称等于整款；conversion 每层从聚合分子分母重算。

- [x] **Step 5: 实现 current 与 catalog_snapshot RR resolver**

  current 固定请求时 current catalog、business/report-date 覆盖带、匹配 ready dedup 和 site config；`return_basis=event_date` 还必须从 event-time 索引找出全部实际贡献的 current return publications，即使其 report date 落在区间外，并把贡献 report-date 范围加入 provenance。snapshot 只读目录 fact tuple 内相同两类成员。历史目录＋current、越界日期或 digest 不匹配稳定失败，禁止 fallback。

- [x] **Step 6: 实现有界 SQL repository**

  先限定 site、catalog version、publication members、日期和 scoped mappings，再聚合/分页；event-date 查询先用事件时间索引限定事实，再连接其实际 contributing publication，不能先按 report date 截断。产品总表执行 count/page/coverage/six buckets；card 只扫描该 style 的 mapping key 集合、趋势、variants、publication coverage 和 style reconciliation。

- [x] **Step 7: 实现 provenance 和稳定系列 key**

  `publication_refs_jcs_v1`、dedup ID、site config、timezone、consistent_as_of、fact cutoff 和唯一 `identity_source=p0_catalog` 全部 required。颜色/尺码/sku key 由服务端按规格 tuple 生成，客户端不可构造。

- [x] **Step 8: 运行 unit、RR 和守恒门**

  ```powershell
  .\.venv\Scripts\python.exe -m pytest backend/tests/unit/analytics/test_style_models.py backend/tests/unit/analytics/test_style_sql.py backend/tests/unit/analytics/test_style_service.py -q
  pwsh .\scripts\run-product-catalog-mysql-tests.ps1 -Versions @("8.0") -PytestPaths @("tests/integration/test_style_analytics.py", "tests/integration/test_style_analytics_consistency.py", "tests/integration/test_style_analytics_reconciliation.py")
  ```

  Expected: 五项指标、两种退货日期、缺报/真零、六桶和各层守恒全部 PASS；并发 pointer 变化仍只产生一套 provenance；无无界 Python 聚合。

  Actual (2026-08-24): PASS。新增严格 `MetricValue/TrendPoint/CoverageBlock/MetricTotals/PublicationRefs` 模型和 `StyleAnalyticsService`；金额固定两位、conversion/coverage 固定六位并使用 `ROUND_HALF_UP`，daily/range 缺报、真零、undefined denominator 与 event-date indeterminate 矩阵均由 unit 测试锁定。`MySqlStyleAnalyticsRepository` 在单个 `REPEATABLE READ` read-only consistent snapshot 内解析 current 或目录冻结 fact tuple；current 复核完整 return publication-set digest，snapshot 禁止 current pointer fallback，历史目录＋current 和越界范围稳定失败。经营、退货、dedup、身份、分页、排序、搜索、款式/SKU/日期系列和 event-time 边界均在 MySQL 限定与聚合；event-date 测试证明 report date 在请求区间外的贡献 publication 仍进入数值与 provenance。Unit 门为 `16 passed`；canonical disposable Oracle MySQL 8.0 runner 收集 6 项 integration，最终 `6 passed`。Task 14 文件均在 manifest，`git diff --check` PASS，successor SHA-256 仍为 `858cd5a165f1440e4f8e30b1abf1fb8233e9554d0310a923fdc7593c9384b7c0`。baseline checker 唯一报告既有授权路径 `backend/tests/unit/datasets/test_dataset_repository.py`，其当前 SHA-256 `97dfbe30dfb83e6caaf78df048df16bfa564c607b74807f9957537d694e72a67` 与授权证据一致；Task 14 未新增范围外路径。未注册 HTTP 路由，未执行业务库写入或 Git 暂存/提交。

### Task 15: 新产品 API、OpenAPI 双轨、adapter 和精确 decimal string

**Files:**

- Create: `backend/app/api/style_analytics.py`
- Modify: `backend/app/main.py`、`backend/app/api/dashboard.py`、`backend/tests/unit/test_openapi_contract.py`
- Create tests: `backend/tests/unit/test_style_analytics_api.py`、`backend/tests/integration/test_style_analytics_api.py`、`test_legacy_product_analytics_compatibility.py`
- Regenerate only: `frontend/src/api/generated.ts`
- Create: `frontend/src/features/products/productAnalyticsTypes.ts`、`productAnalyticsApi.ts`、`productAnalyticsApi.test.ts`
- Create: `frontend/src/features/products/analyticsRequestKeys.ts`、`analyticsRequestKeys.test.ts`、`metricFormatting.ts`、`metricFormatting.test.ts`

**Interfaces:**

- Consumes: Task 14 service models、Task 11 client/request gate。
- Produces: 新 `GET /api/dashboard/style-ledger` 和 `GET /api/dashboard/styles/{style_id}/card`；旧 `product-ledger` 和 `product-card/{style_code}` 保持原义；前端类型安全 adapter 和定点格式工具。
- Invariants: 新旧无 fallback、不按数字猜路径；所有 ID 是 string；sales/conversion 不经 binary float；header/body provenance 一致；`productAnalyticsTypes.ts` 只包含本地 view aliases/guards，不手抄 OpenAPI schema。

- [x] **Step 1: 先写两个新端点的表驱动契约**

  覆盖日期、search/sort/page、fact/return basis、catalog version、metric/dimension/color/series、1–8 上限和所有 403/404/409/422 reason code；所有 response required 字段和 null 显式返回。

- [x] **Step 2: 写旧 API snapshot 和 path 歧义测试**

  旧 JSON、状态码和 `style_code` path 保持，响应头固定 `X-Identity-Source: legacy_parser` / `seller_sku_parser_v1`；新端点固定 P0 provenance。数字款号不能路由为 `style_id`。

- [x] **Step 3: 实现薄 style analytics router**

  从 `CurrentSiteContext` 调用 Task 14；严格 query parsing、history RBAC 和安全错误；不在 route 内聚合，不捕获 404 后调用旧 service。

- [x] **Step 4: 注册路由并仅给旧端点增加 identity headers**

  旧 body 完全不变；新 body/header 都只有 `p0_catalog + catalog_version_id`。任何 header/body source 冲突按测试失败。

- [x] **Step 5: 生成客户端并写 adapter 无 fallback 测试**

  Adapter 精确调用新 path/query；404、空 rows、数字字符串或目录未初始化均不调用旧 API。Request key 使用 canonical tuple，覆盖全部规范参数。

- [x] **Step 6: 实现 decimal string/定点工具**

  金额两位、conversion 六位和 coverage 六位逐字符校验与本地化显示；负数、`<0`、`>1`、null 正确。图表比较解析为有界 BigInt scale，展示仍用服务端 string；禁止 `Number/parseFloat`。

- [x] **Step 7: 运行后端、OpenAPI 和前端静态门**

  ```powershell
  pwsh .\scripts\run-product-catalog-mysql-tests.ps1 -Versions @("8.0") -PytestPaths @("tests/unit/test_style_analytics_api.py", "tests/integration/test_style_analytics_api.py", "tests/integration/test_legacy_product_analytics_compatibility.py", "tests/unit/test_openapi_contract.py")
  .\scripts\generate-api-client.ps1
  .\scripts\generate-api-client.ps1 -Check
  Push-Location frontend
  pnpm exec vitest run src/features/products/productAnalyticsApi.test.ts src/features/products/analyticsRequestKeys.test.ts src/features/products/metricFormatting.test.ts src/api/client.test.ts
  pnpm typecheck
  Pop-Location
  ```

  Expected: 新旧 operation 同时存在且无歧义；生成物无 drift；负/零/null/超 1 decimal 显示准确；新 adapter 没有 legacy fallback。

  Actual (2026-08-24): PASS。新增薄 `style_analytics` router，在 `CurrentSiteContext` 解析并释放认证连接后由 Task 14 `StyleAnalyticsService` 开启独立 `REPEATABLE READ` 只读一致性事务；新 `style-ledger`/稳定 `style_id` card 与旧 `style_code` 路径无 fallback、无数字猜测。参数表和 403/404/409/422 稳定码已冻结；新响应 header/body 统一为 `p0_catalog + catalog_version_id`，旧 ledger/card body 保持原 schema，仅增加 `legacy_parser + seller_sku_parser_v1` headers。OpenAPI 同时生成四条新旧 operation，所有响应字段（含 nullable 和常量）为 required、ID 为 string；`generated.ts` drift check PASS。前端类型只引用生成 contract；adapter 单次调用新 path，canonical request key 覆盖全部参数；金额两位、conversion/coverage 六位逐字符校验，图表定位只用有界 BigInt，不使用 `Number/parseFloat`。canonical disposable Oracle MySQL 8.0 门最终 `42 passed`；前端指定 4 文件 `33 passed`，typecheck、Ruff、Mypy、OpenAPI check 和 `git diff --check` 全部 PASS。successor SHA-256 保持 `858cd5a165f1440e4f8e30b1abf1fb8233e9554d0310a923fdc7593c9384b7c0`。baseline checker 仍只报告既有批准路径 `backend/tests/unit/datasets/test_dataset_repository.py`，未新增越界路径。未进入 Task 16，未执行 Git 暂存、提交、合并、tag 或推送。

### Task 16: `/products` 稳定款式产品总表

**Files:**

- Create: `frontend/src/features/products/productLedgerState.ts`、`productLedgerState.test.ts`
- Create: `frontend/src/features/products/MetricValueView.tsx`、`MetricValueView.test.tsx`
- Create: `frontend/src/features/products/CoverageReconciliation.tsx`、`CoverageReconciliation.test.tsx`
- Create: `frontend/src/features/products/ProductLedgerPage.tsx`、`ProductLedgerPage.test.tsx`、`ProductAnalytics.css`
- Modify: `frontend/src/app/App.tsx`、`frontend/src/app/App.test.tsx`
- Create: `frontend/tests/e2e/product-ledger.spec.ts`

**Interfaces:**

- Consumes: Task 15 adapter、request keys、decimal formatter 和 `style-ledger`。
- Produces: 可直达、刷新、前进/后退恢复的 `/products`，标准款名一款一行，站点 coverage 和六桶对账。
- Invariants: URL 参数白名单精确；旧 key 结果在新筛选标题下不可见；来源标题只作数量徽标；未归类不伪造款式。

- [x] **Step 1: 写 URL parse/serialize/reset 失败测试**

  精确白名单为 `from/to/search/sort/direction/page/page_size/return_basis/catalog_version/fact_basis`；覆盖真实日历、31 天默认、未来、366/367 天、100 字符、枚举、分页、未知参数、push/replace 和 page reset。

- [x] **Step 2: 写 MetricValue 和 reconciliation 展示测试**

  分开测试 observed zero、no reports、zero sessions、partial、business 完整但 returns partial、六桶 null/evaluable 和 decimal strings；不得统一显示 `--`。

- [x] **Step 3: 实现筛选、排序、分页和列表返回状态**

  默认当前业务日止 31 天、units desc、page 1、50 行、event_date/current。日期/search/sort/direction 改变将 page 重置 1；row link 使用稳定 style_id 并保存完整列表 URL/focus target。

- [x] **Step 4: 实现 latest request gate 和 loading/error**

  新 key 立即移除旧表/指标/coverage，显示稳定 skeleton、`aria-busy` 和 live announcement；retry 精确复用失败 key；旧响应不得更新 permissions、URL 或错误。

- [x] **Step 5: 实现标准名称、来源徽标、五指标和六桶**

  名称只读 `standard_name`；“多个来源标题”显示冻结证据计数且不随日期筛选改变。全站 identity/mapping/dedup coverage 和 reconciliation 只在本页；显示 fact basis、目录、时区和 consistent time。

- [x] **Step 6: 接入 direct route，保留旧产品入口**

  App 注册 `/products` 供里程碑直达测试，但不移除现有 dashboard 产品 tab/modal，也不把旧链接自动重定向；正式入口切换留给 Task 19。

- [x] **Step 7: 运行组件、URL、响应式和 mock E2E**

  ```powershell
  Push-Location frontend
  pnpm exec vitest run src/features/products/productLedgerState.test.ts src/features/products/MetricValueView.test.tsx src/features/products/CoverageReconciliation.test.tsx src/features/products/ProductLedgerPage.test.tsx src/app/App.test.tsx
  pnpm exec playwright test tests/e2e/product-ledger.spec.ts --project=chromium
  pnpm typecheck
  pnpm lint
  Pop-Location
  ```

  Expected: 直达、刷新、后退、乱序、retry、1440/768/390px 和 200% zoom 全部 PASS；页面无横向溢出，只有标注表容器可滚动。

  Actual (2026-08-24): PASS。`/products` 以 canonical URL/request key 驱动筛选、排序、分页、retry 与焦点返回；新 key 立即清除旧数据，标准名称、来源证据徽标、五指标、coverage 和六桶均只消费 P0 adapter。组件、App、typecheck/lint/build 与三档视口 mock E2E 通过；Task 18 live 进一步证明页面未请求 legacy product endpoint。

### Task 17: `/products/:style_id` 颜色/尺码趋势、等价矩阵和八系列

**Files:**

- Create: `frontend/src/features/products/productDetailState.ts`、`productDetailState.test.ts`
- Create: `frontend/src/features/products/SeriesSelector.tsx`、`SeriesSelector.test.tsx`
- Create: `frontend/src/features/products/ProductTrendChart.tsx`、`ProductTrendChart.test.tsx`
- Create: `frontend/src/features/products/TrendPointMatrix.tsx`、`TrendPointMatrix.test.tsx`
- Create: `frontend/src/features/products/ProductDetailPage.tsx`、`ProductDetailPage.test.tsx`
- Modify: `frontend/src/features/products/ProductAnalytics.css`、`frontend/src/app/App.tsx`、`frontend/src/app/App.test.tsx`
- Create: `frontend/tests/e2e/product-detail.spec.ts`

**Interfaces:**

- Consumes: Task 15 card adapter/formatting、Task 11 SafeSourceRef/reveal/request gate、Task 16 list location state。
- Produces: 默认颜色比较、选中颜色后的尺码比较、total/sku 维度、五项指标、两种退货口径、全部实际 SKU 和图表同源每日矩阵。
- Invariants: 展示文本不是 URL 身份；客户端不构造 color/series key；null gap 不插值；最多 8 条；详情不显示全站六桶。

- [x] **Step 1: 写详情 URL 与语义恢复失败测试**

  白名单为 `from/to/metric/dimension/color_key/series/return_basis/catalog_version/fact_basis`；覆盖非法空 series、重复/9 条、size 缺颜色、非 size 带颜色、非 ASCII label、目录切换和颜色改名。只有当前 key 返回明确 membership 失效 reason（例如 `catalog_color_not_found`、`analytics_series_invalid`）时才按服务端建议单次 replace；款式不存在、日期/权限等其他 404/422 只显示绑定当前 key 的错误且不改 URL。

- [x] **Step 2: 写 `SeriesSelector` 键盘和上限测试**

  可聚焦 checkbox；已有 8 条时第 9 条被阻止且数组逐项不变；有可用系列时不可取消最后 1 条；无系列不写 URL。限制和异步更新通过 `aria-live`。

- [x] **Step 3: 实现无新依赖的 SVG renderer**

  使用独立 SVG＋定点 scale；测试负数、零、null gap、单点、8 线、line style＋label、非颜色唯一识别和 reduced motion。图不重算业务聚合。

- [x] **Step 4: 实现同源每日点矩阵**

  每格显示日期、系列和精确值或 missing/undefined 文案；非 conversion numerator/denominator 保持 null，conversion 使用服务端值。矩阵和文字摘要只消费同一 card response。

- [x] **Step 5: 实现详情、summary、coverage 和 variants**

  顶部显示标准名称、款号、实际变体数、最近发布日和分报表覆盖。Variants 列出全部实际 SKU、颜色、尺码、内部展示 SKU、安全 aliases 和五项周期指标，不生成笛卡尔积。

- [x] **Step 6: 实现 metric/dimension/color/series/return/fact 切换**

  默认 units/color/event_date；size 先选服务端 color key，离开 size 清除 color。用户交互 push、语法修复 replace；非 returns trend 显示 `trend_effective_return_basis=null`，summary/variants 仍使用 effective return basis。

- [x] **Step 7: 实现乱序、焦点、列表返回和 reveal 清理**

  新 key 下旧图表/表格立即不可见，依赖响应的系列和复制禁用；正常文档焦点顺序，无 dialog trap；返回列表恢复完整 URL/focus。Reveal 继续服从 resource key、authz generation 和草稿 409 purge。

- [x] **Step 8: 运行详情、矩阵、ARIA 和响应式门**

  ```powershell
  Push-Location frontend
  pnpm exec vitest run src/features/products/productDetailState.test.ts src/features/products/SeriesSelector.test.tsx src/features/products/ProductTrendChart.test.tsx src/features/products/TrendPointMatrix.test.tsx src/features/products/ProductDetailPage.test.tsx src/components/source-reference src/app/App.test.tsx
  pnpm exec playwright test tests/e2e/product-detail.spec.ts --project=chromium
  pnpm typecheck
  pnpm lint
  Pop-Location
  ```

  Expected: 直达、刷新、后退、失效 key、8 系列、键盘、每日矩阵、SafeSourceRef、三档视口和 200% zoom 全部 PASS；危险值不在 DOM/ARIA/copy/log。

  Actual (2026-08-24): PASS。稳定 `style_id` 详情支持颜色/尺码维度、服务端系列 key、最多八系列、两种退货口径、五指标 summary、全部实际 SKU 与同源每日矩阵；SVG 使用定点 scale 并保留 null gap。组件、SafeSourceRef、App、typecheck/lint/build、三档视口及 200% zoom mock E2E 通过；Milestone B live 验证 10 个实际 SKU、9 个候选系列限制、URL 恢复和危险值边界。

### Task 18: Milestone B——旧新 API 双轨与真实产品分析 live 验收

**Files:**

- Modify: `frontend/playwright.catalog-live.config.ts`、`frontend/tests/e2e/live/catalogLiveFixtures.ts`
- Create: `frontend/tests/e2e/live/product-analytics-milestone-b.live.spec.ts`
- Modify: `scripts/run-product-catalog-live-e2e.ps1`
- Modify compatibility tests: `backend/tests/integration/test_legacy_product_analytics_compatibility.py`

**Interfaces:**

- Consumes: Milestone A 真实目录流程和 Tasks 14–17 的新 API/直达页面。
- Produces: 同一私有 run 内先批准目录、再验证新产品总表/详情，同时直接验证旧 API 兼容的无 mock 证据。
- Invariants: 正式旧 UI 入口仍未移除；live 只能监听真实请求，禁止 fulfill/abort/rewrite；新页面网络不得调用旧 product endpoints。

- [x] **Step 1: 扩展固定商品分析验收集**

  同款 3 色、9 个尺码候选但只有 10 个实际 SKU；一个 SKU 有新旧 Seller SKU；含缺失经营日、unresolved duplicate、9 个可选系列、event/report date 差异、负/零边界和危险来源字符，全部绑定本 run。

- [x] **Step 2: 在 live config 增加依赖 project**

  `product-milestone-b` depends on `catalog-milestone-a`，共享同一 runner/run ID 和已批准目录。默认 Playwright 继续排除 live，live config 继续无 webServer。

- [x] **Step 3: 真实验证旧新 API 双轨**

  用 `APIRequestContext` 请求旧 ledger/card，断言旧 JSON 和 legacy headers；请求新端点断言唯一 P0 provenance。验证数字款号路径、404 和空结果都不发生 fallback。

- [x] **Step 4: 真实验证产品总表**

  Viewer 直达 `/products`，看到标准名称、来源标题徽标、五指标、partial、coverage/reconciliation 和 P0 provenance；监听请求确认没有旧 product-ledger/card。

- [x] **Step 5: 真实验证详情、URL、日期和八系列**

  进入稳定 style route，验证默认颜色、选色后尺码、10 个实际 SKU、missing/zero、两种退货日期和等价矩阵；其中一个 event-date 事实来自 report date 在请求区间外的 publication，仍必须显示并出现在 contributing provenance。第 9 条被阻止，刷新/后退恢复 URL，返回列表恢复筛选和焦点。

- [x] **Step 6: 真实验证权限、安全、ARIA 和响应式**

  Viewer 只见安全 preview；manager reveal 经真实审计；角色/revision 变化销毁旧可逆值。1440/768/390px、200% zoom、键盘和读屏状态通过，页面无横向溢出。

- [x] **Step 7: 运行默认回归和 Milestone B live**

  ```powershell
  Push-Location frontend
  pnpm exec vitest run src/features/products src/features/catalog src/components/source-reference src/app/App.test.tsx
  pnpm exec playwright test
  pnpm exec tsc -p tests/e2e/tsconfig.json --noEmit
  pnpm typecheck
  pnpm lint
  pnpm build
  pnpm exec playwright test --config=playwright.catalog-live.config.ts --list --project=product-milestone-b
  Pop-Location
  .\scripts\run-product-catalog-live-e2e.ps1 -Milestone Products
  if ([string]::IsNullOrWhiteSpace($env:APP_PLAN_BASELINE_ROOT)) { throw "APP_PLAN_BASELINE_ROOT is required" }
  .\scripts\check-plan-worktree-baseline.ps1 -PathManifest .\docs\superpowers\plans\2026-08-20-product-style-variant-analytics-foundation-file-manifest.json -BaselineRoot $env:APP_PLAN_BASELINE_ROOT
  ```

  Expected: 默认 mock suite 和专用真实链路全部 PASS；旧 API 保持兼容，新直达 UI 只请求新端点；runner 只清理本 run 资源。

  Actual (2026-08-24): PASS。最终固定 fixture 为 2 个稳定款式、10 个稳定 SKU 和 1 个 `audit_only` SKU；同一 run 内真实验证目录批准、旧 API legacy provenance、新 API P0 provenance、列表/详情无 fallback、event/report date 差异、八系列上限、权限/reveal、ARIA 与响应式。最新完整 All 证据为 `C:\Users\20937\AppData\Local\Temp\clsen-catalog-live-evidence-9ef55ec6c47d487286af25f0a232f72d.json`，cleanup PASS。

#### Milestone B pause

Task 18 PASS 后保存双轨证据并暂停。此时用户可以通过直达路由体验标准名称、颜色和尺码趋势，但现有 dashboard 的正式产品入口仍未替换；只有 Task 19 的固定事实对账、整套切换及 rollback 演练通过后才能改入口。

---

## Milestone C：固定事实对账、受控切换、回滚与 release gate

### Task 19: 新旧对账、整套 `legacy_parser → p0_catalog` 切换和 rollback

**Files:**

- Create: `backend/app/analytics/cutover.py`
- Create tests: `backend/tests/unit/analytics/test_cutover.py`、`backend/tests/integration/test_product_analytics_cutover.py`、`test_product_analytics_reconciliation.py`
- Modify: `backend/app/api/dashboard.py`
- Create: `frontend/src/features/products/productAnalyticsSource.ts`、`productAnalyticsSource.test.ts`
- Modify: `frontend/src/features/dashboard/PublishedDashboard.tsx`、`PublishedDashboard.test.tsx`、`PublishedDashboard.css`、`ProductInfoDialog.tsx`
- Modify: `frontend/src/features/products/ProductLedgerPage.tsx`、`frontend/src/features/products/ProductDetailPage.tsx`
- Modify: `frontend/src/app/App.tsx`、`frontend/src/app/App.test.tsx`、`frontend/playwright.config.ts`、`.env.example`
- Create: `frontend/tests/e2e/product-analytics-cutover.spec.ts`
- Modify: `frontend/playwright.catalog-live.config.ts`、`frontend/tests/e2e/live/catalogLiveFixtures.ts`、`scripts/run-product-catalog-live-e2e.ps1`
- Modify tests: `backend/tests/unit/auth/test_product_catalog_live_harness.py`
- Create: `frontend/tests/e2e/live/product-analytics-cutover.live.spec.ts`
- Regenerate: `frontend/src/api/generated.ts`

**Interfaces:**

- Consumes: 已批准目录、双轨 API/页面、一个不可变 fact tuple、旧 API frozen snapshots 和 Milestones A/B evidence。
- Produces: release-scoped closed source selector、固定事实 reconciliation manifest、P0 正式导航/入口、legacy 整套 rollback 和数据库零业务变化证明。
- Invariants: selector 只控制产品分析导航、旧 dashboard 产品 tab/modal、`/products` 和 `/products/:style_id`；独立 `/catalog` 自 Milestone A 起在两种模式都按权限保留。selector 只能在进程/build/release 级选择 `legacy_parser|p0_catalog`，不能由 request、cookie、用户、SKU 或行覆盖；切换/回滚不改 catalog/publication/dedup/facts/audit。

- [x] **Step 1: 先写旧 API 兼容和单一 provenance 失败测试**

  固定旧 endpoint body/status/headers；新 endpoint body/header 固定 P0。逐格拒绝缺失、冲突或混合 source/version；数字 style code 与 style ID 路由永不串义。表驱动覆盖两种 build 下 `/catalog`、`/?tab=products`、`/products` 和 `/products/:style_id` 的入口/直达行为，并断言 legacy 直达绝不请求 P0 API。

- [x] **Step 2: 写固定 fact tuple 对账测试**

  在同一 RR tuple 比较旧 parser eligible source 与新 `mapped+unmatched+excluded`；再按款号/稳定款式、颜色、尺码、SKU 和五项指标核对。允许差异必须逐行落入 explicit mapping/exclusion/anomaly bucket；`unexplained_count/value` 全为零。

- [x] **Step 3: 写 rollback 零业务写测试**

  在 legacy→P0→legacy 前后计算 catalog version/member/revision/mapping/reservation、catalog/publication/dedup pointers、日报 facts 和 audit/event 的语义 checksum；全部必须相同。

- [x] **Step 4: 实现 cutover manifest 和 closed source selector**

  唯一 release-mode 输入由 runner 内部的 `$source` 产生，并分别注入后端 `APP_PRODUCT_ANALYTICS_SOURCE` 与前端 `VITE_PRODUCT_ANALYTICS_SOURCE`；两者只接受 `legacy_parser|p0_catalog`，缺失、非法或不一致都 fail closed。后端 `cutover.py` 生成包含 source/release/artifact/fact tuple/catalog/dedup/provenance/diff digest 的脱敏 attestation manifest；前端 source 模块只读取 build-time 字面值，不做 runtime per-request fallback，`.env.example` 只作说明且绝不是注入来源。

- [x] **Step 5: 原子切换整套 UI/adapter**

  `/catalog` 在两种模式始终保留。`p0_catalog` 隐藏旧 dashboard 产品 tab/modal，侧栏显示 `/products`，列表/详情只用新 adapter；旧 `/?tab=products` 使用 `replace` 统一转到 `/products`。`legacy_parser` 恢复旧产品 tab/modal并隐藏 `/products` 导航；书签直达 `/products` 或 `/products/:style_id` 必须在挂载页面或发起请求前 `replace` 到 `/?tab=products`。不能出现一页新列表配旧 card，也不能只藏链接却继续读取 P0。

- [x] **Step 6: 运行后端、OpenAPI、前端和 mock cutover 门**

  ```powershell
  .\.venv\Scripts\python.exe -m pytest backend/tests/unit/analytics/test_cutover.py backend/tests/unit/auth/test_product_catalog_live_harness.py -q
  pwsh .\scripts\run-product-catalog-mysql-tests.ps1 -Versions @("8.0") -PytestPaths @("tests/integration/test_product_analytics_cutover.py", "tests/integration/test_product_analytics_reconciliation.py")
  .\scripts\generate-api-client.ps1
  .\scripts\generate-api-client.ps1 -Check
  Push-Location frontend
  pnpm lint
  pnpm typecheck
  $previousSource = [Environment]::GetEnvironmentVariable("VITE_PRODUCT_ANALYTICS_SOURCE", "Process")
  $previousCutoverRun = [Environment]::GetEnvironmentVariable("PLAYWRIGHT_CUTOVER_RUN", "Process")
  try {
    $env:PLAYWRIGHT_CUTOVER_RUN = "1"
    foreach ($source in @("legacy_parser", "p0_catalog")) {
      $env:VITE_PRODUCT_ANALYTICS_SOURCE = $source
      pnpm exec vitest run src/features/products/productAnalyticsSource.test.ts src/features/dashboard/PublishedDashboard.test.tsx src/app/App.test.tsx
      if ($LASTEXITCODE -ne 0) { throw "vitest failed for $source" }
      pnpm exec playwright test tests/e2e/product-analytics-cutover.spec.ts --project=chromium
      if ($LASTEXITCODE -ne 0) { throw "playwright failed for $source" }
      pnpm build
      if ($LASTEXITCODE -ne 0) { throw "build failed for $source" }
    }
  }
  finally {
    [Environment]::SetEnvironmentVariable("VITE_PRODUCT_ANALYTICS_SOURCE", $previousSource, "Process")
    [Environment]::SetEnvironmentVariable("PLAYWRIGHT_CUTOVER_RUN", $previousCutoverRun, "Process")
    Pop-Location
  }
  ```

  默认 `playwright.config.ts` 在 `PLAYWRIGHT_CUTOVER_RUN=1` 时固定 `reuseExistingServer=false`，所以每个 source 使用继承本次环境的新 Vite 进程；测试证明旧 server 不能让 P0/legacy 用错 bundle。

- [x] **Step 7: 在 runner-owned MySQL 演练整 release 切换与回滚**

  使用 Task 13/18 的独占 runner 和新增 `product-cutover` live project，在同一候选 backend/catalog/fact tuple 上依次启动 `legacy-before`、`p0`、`legacy-rollback` 三套全新后端进程和独立前端输出目录；每次 runner 从一个 `$source` 同时设置 APP/VITE 变量，只允许一个 Job Object/模式对外。启动后核对 process environment、bundle marker、cutover attestation 和实际 endpoint provenance 四者一致，再重放浏览器入口和 DB checksum，保存三个 artifact digest 与 reconciliation manifest。live config 必须继续无 `webServer/reuseExistingServer`。

  Runner 对三次构建使用不同的 runner-owned 临时目录且禁止复用旧 `dist`；所有 APP/VITE/PLAYWRIGHT 变量、端口、Job Object、进程树和临时目录都在 `try/finally` 中恢复或按 ownership manifest 清理，原来未设置的变量必须删除而不是留空。rollback 必须是新的 legacy build/process，不能复用第一次 artifact 冒充回滚。

  ```powershell
  Push-Location frontend
  pnpm exec playwright test --config=playwright.catalog-live.config.ts --list --project=product-cutover
  Pop-Location
  .\scripts\run-product-catalog-live-e2e.ps1 -Milestone Cutover
  ```

- [x] **Step 8: 核对 manifest 范围并暂停**

  ```powershell
  if ([string]::IsNullOrWhiteSpace($env:APP_PLAN_BASELINE_ROOT)) { throw "APP_PLAN_BASELINE_ROOT is required" }
  .\scripts\check-plan-worktree-baseline.ps1 -PathManifest .\docs\superpowers\plans\2026-08-20-product-style-variant-analytics-foundation-file-manifest.json -BaselineRoot $env:APP_PLAN_BASELINE_ROOT
  ```

  Expected: `/catalog` 在两种模式保持；双轨 API 保持，正式产品分析 UI 可整套 `legacy→P0→legacy`；legacy 直达不会读取 P0；每个响应只有一个 source/version；三套 build/process attestation 与 digest 不混用；未解释差异为零；rollback 前后数据库业务 checksum 相同；用户原 hunk 未丢失。这里只完成隔离演练，不启用生产。

  Actual (2026-08-24): PASS。closed APP/VITE selector、cutover attestation、旧新 endpoint provenance、整套导航/直达重定向和固定 fact-tuple reconciliation 已通过 unit、MySQL、OpenAPI、Vitest 与 mock E2E。最新 All live 使用三套独立 build/process 执行 `legacy-before → p0 → legacy-rollback`；三个 artifact digest 各自单值绑定，P0/rollback 业务 checksum 均为 `e4c21d6288641b6fba929dd1de64e34904cbb3eecab9ecd8797a58588a119425`，`zero_business_writes_on_rollback=true`，未启用生产流量。

### Task 20: 固定性能、真实只读 canary、备份恢复、CI、全回归和文档

**Files:**

- Create: `backend/tests/performance/__init__.py`、`product_catalog_scale_fixture.py`、`test_product_catalog_performance.py`
- Create: `backend/tests/integration/test_product_catalog_canary.py`、`test_product_catalog_permissions.py`、`test_product_catalog_backup_restore.py`
- Create: `backend/tests/unit/security/test_product_catalog_sensitive_output.py`
- Create golden fixture: `backend/tests/fixtures/backups/v1_0020/README.md`、`catalog.json`、`manifest.json.enc`、`database.sql.enc`、`sha256sums.json`、`test-keyring.json`
- Modify: `backend/tests/integration/conftest.py`、`backend/tests/contracts/test_maintenance_scripts.py`、`backend/tests/contracts/test_server_deployment.py`、`backend/tests/contracts/test_test_grant_sync_script.py`、`backend/tests/unit/maintenance/test_backup.py`、`backend/tests/unit/maintenance/test_restore.py`
- Create: `scripts/run-product-catalog-performance.ps1`、`run-product-catalog-canary.ps1`、`run-product-catalog-backup-restore.ps1`
- Modify: `scripts/run-product-catalog-live-e2e.ps1`、`scripts/test-mysql-matrix.ps1`、`scripts/backup.ps1`、`scripts/restore-verify.ps1`、`scripts/sync-test-runtime-grants.ps1`
- Modify: `scripts/check-worktree-text.ps1`、`scripts/check-plan-worktree-baseline.ps1`
- Modify: `backend/app/maintenance/backup.py`、`backend/app/maintenance/restore.py`、`ops/mysql/init-users.sh`、`ops/verify-deployment.ps1`
- Modify: `frontend/playwright.catalog-live.config.ts`、`frontend/playwright.config.ts`
- Create: `frontend/tests/e2e/live/product-catalog-release.live.spec.ts`
- Modify: `.github/workflows/compatibility.yml`
- Create: `.github/workflows/release-gates.yml`
- Create: `docs/user-guide/product-catalog.md`、`docs/user-guide/product-analytics.md`、`docs/operations/product-catalog-rollout.md`
- Modify: `docs/user-guide/dashboard.md`、`docs/operations/local-maintenance.md`、`ops/DEPLOYMENT.md`
- Regenerate: `frontend/src/api/generated.ts`

**Interfaces:**

- Consumes: Tasks 1–19 的同一候选代码/artifact、两个里程碑证据、用户两份私有真实 CSV 和当前业务库 SELECT-only 凭据。
- Produces: `analytics_scale_v1`、查询计划和 p95、count-only canary、安全输出扫描、最小权限、加密恢复、release-build live、canonical local/workflow/deployment gates、用户/运维文档和最终 evidence bundle；hosted CI 留作获准创建 candidate ref 后的部署硬门。
- Invariants: 私有 CSV/凭据不进仓库/CI；缺任一必需环境时 release gate FAIL 而非 skip 成功；通过本任务不授权生产部署。

- [x] **Step 1: 建立固定规模 fixture 和查询计划门**

  Seed `20260819`：1,700 款、11,200 Seller SKU keys、365 日、4,088,000 经营 active rows、408,800 退货 rows、560 aliases、224 unmatched、112 excluded、8,176 duplicate-candidate members（恰好 4,088 个 canonical/duplicate 与 4,088 个 unresolved）、12 missing days、一个 16 系列款式。每个 key 在经营、退货两个 report type 的历史中都轮换恰好三个合成标题/标识 tuple；`source_evidence_jcs_v1` 必须把同一 key＋report type 的历史 tuple 聚合为一条摘要，所以精确得到 `11,200 × 2 = 22,400` 条来源证据，而不是 67,200 条原始 tuple。完整 export 必须经过 Excel 可打开验证、原样再上传、解析和审核投影，不只测试 writer。

  MySQL 8.0/8.4 各使用 4 vCPU、8 GiB、2 GiB buffer pool、loopback release API；warmup 3 次、measured 20 次、取 p95。保存脱敏 `EXPLAIN ANALYZE`；越过 publication/date 的 `ALL` scan、单款扫描其他款或 Python 收原始行都失败。

- [x] **Step 2: 固定并执行五项性能预算**

  | 场景 | p95 上限 |
  | --- | ---: |
  | 31 天产品总表，第 1 页 50 款 | 1,500 ms |
  | 单款 31 天、8 条系列 | 750 ms |
  | 单款 365 天、8 条系列 | 1,500 ms |
  | 连续退货 dedup staging | 30 s |
  | publication＋dedup CAS lock transaction | 500 ms |

  365 次后 delta depth ≤32、物理 group membership ≤150,000。Runner 不提供降低样本、提高 timeout 或跳过某 MySQL 版本的发布模式。

- [x] **Step 3: 实现真实文件和当前库只读 canary**

  经营文件必须重现 22 列、24 行、9 款、24 个严格 Seller SKU、5 款多标题，并验证标准 CSV quoting 下含逗号标题；退货文件重现 13 列、10 行、6 款、10 个严格 Seller SKU，验证含逗号留言并保留 raw timestamp、UTC/event/report business date。用两个不同 raw/UTC 日期但转换后同属 `America/Los_Angeles` 同一业务日的事实做 known-answer；多来源标题只能增加 evidence，绝不覆盖目录标准名称。当前库在 `REPEATABLE READ READ ONLY` 中重现 34 候选、224 distinct、222 strict、2 anomaly 和 `125+7+92=224`。

  输出 allowlist 只含 query/digest、normalization version、consistent_as_of、行列/计数、布尔安全结果和 artifact digest；禁止完整 Seller SKU、标题、订单号、留言或牌照。

- [x] **Step 4: 强化数据库身份、最小 grant 和加密恢复**

  在创建库/启动服务前验证 loopback、Oracle 8.0/8.4、`utf8mb4`、`clsen_data_test*` 和 URL schema＝`DATABASE()`。Migration/runtime/backup/restore/canary 分离；runtime 无 DDL/GRANT，backup 无业务写，canary 只有 SELECT。

  新 writer 只接受最终 P0 head；reader 恢复新 P0 加密 artifact 和仓库内固定 digest 的 synthetic v1/`0020` golden。Golden 必须由冻结的旧 writer/historical schema harness 独立生成，含公开的纯测试 keyring、生成 commit/命令和逐 artifact SHA-256；新 reader 不能在测试时自行生成它形成同源自证。恢复目标只能是新建 runner-owned 测试库，并逐表验证 revision/member/mapping/pointer/audit、dedup、趋势和语义 checksum，不只比行数。

- [x] **Step 5: 建立 release-build 真实 live E2E**

  Runner 独占 loopback、测试库、storage 和进程，升级到最终 head，以最小 runtime 身份启动 FastAPI，再启动 release React build；覆盖目录初始化、审核批准、产品分析、Task 19 P0 切换与 legacy rollback。禁止 route mock；finally 只清理本 run。

- [x] **Step 6: 让 workflow、matrix 和部署验证调用 canonical runners**

  消除不完整显式测试列表；workflow 先验证预期 suites 被收集，再声明 MySQL 8.0/8.4 三迁移路径、performance、restore、mock/live E2E、OpenAPI drift 和 deployment verification 都调用与本地相同的 canonical runner。用 workflow contract 测试和本地 runner 实际 PASS 验证配置，任一必需 artifact 或版本缺失即失败。由于本轮禁止 commit/ref，Task 20 不宣称 hosted CI 已运行；用户日后授权 candidate ref/PR 后，真实 hosted CI PASS 才能解除部署硬门。

- [x] **Step 7: 运行完整 backend/frontend/ops 回归**

  ```powershell
  .\.venv\Scripts\python.exe -m pytest backend/tests -m "not mysql" -q
  .\.venv\Scripts\python.exe -m ruff check --config backend/pyproject.toml backend/app backend/tests
  .\.venv\Scripts\python.exe -m ruff format --check --config backend/pyproject.toml backend/app backend/tests
  .\.venv\Scripts\python.exe -m mypy --config-file backend/pyproject.toml backend/app backend/tests
  pwsh .\scripts\test-mysql-matrix.ps1 -Versions @("8.0", "8.4")
  pwsh .\scripts\run-product-catalog-performance.ps1
  pwsh .\scripts\run-product-catalog-canary.ps1 -RequirePrivateCorpus -RequireCurrentDatabase
  pwsh .\scripts\run-product-catalog-backup-restore.ps1
  pwsh .\scripts\run-product-catalog-live-e2e.ps1 -Milestone All
  pwsh .\ops\verify-deployment.ps1 -DisposableTestRun
  .\scripts\generate-api-client.ps1
  .\scripts\generate-api-client.ps1 -Check
  Push-Location frontend
  pnpm test --run
  pnpm lint
  pnpm typecheck
  pnpm build
  pnpm exec playwright test
  Pop-Location
  ```

- [x] **Step 8: 完成文档、工作区三方核验和 release evidence**

  用户指南说明标准名称、实际变体、五指标、两种退货日期、partial/null、来源安全和目录审核；runbook 说明整套流量 rollback 与向前目录纠错。Evidence 绑定 commit/worktree snapshot、artifact digest、最终 head、MySQL profile、测试计数和 runner digests。

  ```powershell
  git diff --check -- (Get-Content -Raw -LiteralPath .\docs\superpowers\plans\2026-08-20-product-style-variant-analytics-foundation-file-manifest.json | ConvertFrom-Json)
  .\scripts\check-worktree-text.ps1 -PathManifest .\docs\superpowers\plans\2026-08-20-product-style-variant-analytics-foundation-file-manifest.json -Extensions .py,.ts,.tsx,.css,.md,.json,.toml,.ps1,.in,.lock,.yml,.yaml,.txt
  if ([string]::IsNullOrWhiteSpace($env:APP_PLAN_BASELINE_ROOT)) { throw "APP_PLAN_BASELINE_ROOT is required" }
  .\scripts\check-plan-worktree-baseline.ps1 -PathManifest .\docs\superpowers\plans\2026-08-20-product-style-variant-analytics-foundation-file-manifest.json -BaselineRoot $env:APP_PLAN_BASELINE_ROOT
  git status --short
  ```

  Expected: 全部 local/workflow-contract 门 PASS；真实输入和当前库计数及日期/CSV/标准名称语义精确重现且零敏感泄漏；两个 MySQL 版本性能/恢复/权限通过；用户既有修改无丢失；候选版本只达到 local release-ready，hosted CI 明确 pending authorization，没有生产迁移、流量启用、Git staging/commit/push。

  Actual (2026-08-25): PARTIAL / EXTERNAL GATES BLOCKED。实现已包含固定规模 fixture/runner、私有 CSV 与当前库 canary、分离身份和最小 grant、加密 golden restore、release live、canonical workflow/matrix、敏感输出扫描及用户/运维文档。既有本地证据保持有效：Oracle MySQL 8.0/8.4 各为 migrations `29 passed`、constraints `70 passed`、Stage 5/6 `47 passed`；两版本恢复各 `4 passed, 1 expected skip`；frontend Vitest `297 passed`、默认 Playwright `12 passed, 1 expected skip`，lint/typecheck/P0 build/E2E TypeScript/OpenAPI drift/Ruff lint 均 PASS；All live 4 个 P0 场景与两次 legacy phase 全部 PASS。全矩阵暴露并修复了 materialized `decimal` 与 parse `percentage|usd` 的 source-kind roundtrip 兼容性，单元 `11 passed`，聚焦 MySQL `22 passed`；另修复 DateWorkbench 异步列布局测试的等待边界，全前端复归为 297/297。

  Deployment canonical runner 已改为每次创建 `clsen-deployment-verify-<12hex>` project 和 `clsen_data_test_<16hex>` runner-owned 随机数据库；migrate 与 test-runner 共享同一 `APP_TEST_RUN_ID`，正常非 disposable 部署语义不变。完整 `pwsh .\ops\verify-deployment.ps1 -DisposableTestRun` 实跑 PASS：migrations `29 passed`、constraints `70 passed`、Stage 5 `18 passed`、Stage 6 `7 passed`、transaction groups `13 passed` 与 `9 passed`、API/权限 `47 passed`、publication `17 passed`、analytics `3 passed`、admin/write-barrier/ingest/worker/parse `48 passed`、deployment load `1 passed`，并输出 `Server deployment verification completed successfully.`；加密备份 UUID 为 `110590618d14432682f5877b652a567c`，恢复 UUID 为 `85faeee9626244e2b053b5b59e9a063f`，恢复库为 `clsen_restore_85faeee9626244e2b053b5b59e9a063f`。完整运行后发现 verification profile 资源未被原 cleanup 激活，随后为 `finally` 补齐 verification/maintenance/load-test profiles；快速复验 `-SkipBuild -SkipMigrationRoundtrip -SkipBackupRestore` 再次退出码 0，随机 project `clsen-deployment-verify-54c5710b526a` 独立检查为 containers `0`、volumes `0`、networks `0`、temporary override `0`。本次 deployment contracts `18 passed`，backend offline 更新为 `1042 passed, 3 skipped, 325 deselected`；相关 5 个 Python 路径 Ruff lint/format 与 Mypy 均 PASS。

  用户已批准 manifest 外窄改 `backend/app/api/raw_files.py`（当前 SHA-256 `f24ecbf5336327326d9ab1dc3f04b2e15d7553436f15122d56ee10aca993771c`）和 `backend/tests/integration/test_admin_operation_permissions.py`（`9ebb41a0cf651e44b2d35cafa1ff5ce81b04e92cb4afed6280bccf7262f3141e`）；前者修正 raw-file HEAD decorator 绑定并保留 preview/download 契约，后者改为使用最终 `CURRENT_SCHEMA_REVISION`。successor 规格仍绑定 SHA-256 `858cd5a165f1440e4f8e30b1abf1fb8233e9554d0310a923fdc7593c9384b7c0`。

  未解除硬门：缺 `APP_PRODUCT_CATALOG_MYSQL80_SCALE_EVIDENCE`、`APP_PRODUCT_CATALOG_MYSQL84_SCALE_EVIDENCE`，性能 runner 按设计 fail closed；缺 SELECT-only `APP_PRODUCT_CATALOG_CANARY_DATABASE_URL`，current-db canary 按设计 fail closed；未获 candidate ref/PR 授权，hosted CI 未运行。后续静态债收敛把全量 Mypy 从 128 errors/37 files 降至 34 errors/11 files，批准 manifest 内为 0 errors；只格式化 35 个 baseline 非 overlap 文件后，Ruff format-check 从 65 降至 30 个文件，剩余为 10 个 manifest overlap 和 20 个范围外文件，Ruff lint 保持 PASS。

  原 302 路径私有 baseline 未被改写；最终 checker 仍正确阻止 Task 0 后的未登记路径：`backend/app/config.py`、`frontend/Dockerfile`、`ops/docker-compose.yml` 和 `frontend/src/components/source-reference/useSensitiveReveal.test.tsx`，另有 Task 5 已单独授权的 `backend/tests/unit/datasets/test_dataset_repository.py`。本轮为全矩阵与全前端回归窄改的三个 Task 0 前既有未跟踪文件也不在 manifest：`backend/app/workbench/schema.py`（当前 SHA-256 `fdb57355be8817be5146f2ba2bf35e39c8d214c76e078e37595cdb28c10e4cc7`）、`backend/tests/unit/workbench/test_schema.py`（`f95aee75319a58167bf5a0218d712ad40b5dd1c37bb2261ab11e792ff4c2aa41`）和 `frontend/src/features/workbench/DateWorkbenchPage.test.tsx`（`db015c5bca1c18ab9c25bc364a3f5bff98d6460727161524f7343ae63a0c9a42`）。这些兼容性修复已有完整测试证据，但除上述两条新获批范围例外外，其他未登记路径和全仓既有静态债仍需后续建立 successor manifest/baseline 或取得逐路径批准；Task 20 因此外加三类外部硬门而不能宣称完整 PASS、local release-ready 或部署就绪。

  继续复核（2026-08-25）：`run-product-catalog-canary.ps1 -RequirePrivateCorpus` 实跑 `2 passed`，真实私有 CSV corpus 部分 PASS；组合 `-RequirePrivateCorpus -RequireCurrentDatabase` 在缺 `APP_PRODUCT_CATALOG_CANARY_DATABASE_URL` 时于数据库连接前 fail closed。`run-product-catalog-performance.ps1` 在缺 MySQL 8.0 `analytics_scale_v1` evidence 时同样于性能执行前 fail closed。四条仍未授权但直接服务 P0 契约的路径已只读绑定当前 SHA-256：`backend/app/config.py` 为 `719713f82c5198e14ff0efd64ee784ca0fb515448fbb6a3d00eeae7227c34b78`、`frontend/Dockerfile` 为 `a33caf7726ddae3420c6254ee76ab1b8fbc9b7f30e3f31d7f776402c776ed587`、`ops/docker-compose.yml` 为 `89d7c01f07b5f3399d15318795eb752f5a47d3644e49f33f686af542624fdc5d`、`frontend/src/components/source-reference/useSensitiveReveal.test.tsx` 为 `290da7e2d20440d650a9a81db84b1a2f7cac69e8dcbffd5068adde004a1401c4`；本次未改写或纳入这些路径。

  外部变量设置审计（2026-08-25）：三个必需变量在 Process/User/Machine scope 均不存在；workspace、私有 baseline、Desktop/Documents/Downloads 也没有 `analytics_scale_v1` evidence。现有 `.env` 的 `APP_DATABASE_URL` 只读执行 `SHOW GRANTS FOR CURRENT_USER` 可连接，但安全归类得到 3 类非 SELECT 权限，因此拒绝将其复制为 canary URL；未输出 URL/账号/grant，未创建用户或执行 GRANT，也未设置占位环境变量。

  固定规模性能证据（2026-08-25）：Oracle MySQL 8.0.46 与 8.4.11 的 canonical `analytics_scale_v1` producer 均在 4 vCPU、8 GiB、2 GiB buffer pool、loopback release API、warmup 3＋measured 20 下 PASS；正式双版本生成各为 `4 passed, 1 expected skip`，随后只消费 evidence 的 release gate 两版本也各为 `4 passed, 1 expected skip`。MySQL 8.0 p95（ms）为 ledger `414.883`、style 31d `643.033`、style 365d `219.668`、dedup `96.778`、CAS `6.587`；evidence SHA-256 为 `c88317504e08d89441553005fff7993749e01da5f03e47ed97f45d5ea2a3bf6a`。MySQL 8.4 p95（ms）为 ledger `388.199`、style 31d `184.012`、style 365d `192.289`、dedup `91.146`、CAS `10.943`；evidence SHA-256 为 `f4776d4501eb45b4aba9a3ecd9f7e96123f47ff6be79724081a287927c797055`。两份 evidence 均为 4,088,000 经营行、408,800 退货行且 `explain_analyze_bounded=true`，路径已写入 User scope 的 `APP_PRODUCT_CATALOG_MYSQL80_SCALE_EVIDENCE` 与 `APP_PRODUCT_CATALOG_MYSQL84_SCALE_EVIDENCE`。`APP_PRODUCT_CATALOG_CANARY_DATABASE_URL` 在 User/Process scope 仍为空，未创建用户、未执行 GRANT、未设置占位值；current-db canary 与 hosted CI 因此仍是外部硬门。

  Canary grant 门加固（2026-08-25）：发现原 `SHOW GRANTS` 检查会因字符串包含 `SELECT` 而误接受 `GRANT SELECT, INSERT`。已改为严格解析每条 grant：只允许 `USAGE ON *.*`，必须至少存在一条仅覆盖 URL 指定数据库的纯 `SELECT`，并拒绝全局 SELECT、其他数据库、角色授权和 `WITH GRANT OPTION`。Red 用例先得到 `3 failed, 3 passed`；修复后权限 known-answer `8 passed`，完整 canary 文件 `9 passed, 1 expected skip`，私有 corpus canonical runner `2 passed`，该路径 Ruff lint/format 与 Mypy 均 PASS。未连接当前业务库；`APP_PRODUCT_CATALOG_CANARY_DATABASE_URL` 仍为空。

  Current-db Canary 尝试（2026-08-26）：User scope URL 已存在且通过连接串结构校验；组合 runner 的私有 corpus 为 `2 passed`，但 MySQL 在任何业务查询或 `SHOW GRANTS` 前以认证错误 `1045 Access denied` fail closed。未记录 URL、密码或账号，未读取/写入业务数据，未创建用户或执行 GRANT。该 URL 需要 DBA 更正真实 SELECT-only 凭据或允许的 Host 绑定后才能重试；current-db Canary 仍未通过。

  Current-db Canary 完成（2026-08-26）：用户以本机 DBA 身份明确批准创建独立 canary 账号并仅授予 `clsen_data` 的 SELECT。管理员登录路径只作一次性本机凭据桥接；创建前确认同名 `localhost` 账号不存在，生成随机密码后只执行 `CREATE USER` 与 `GRANT SELECT ON clsen_data.*`，严格 `SHOW GRANTS` 校验通过，User scope URL 已更新，临时管理员登录路径随后删除。首轮真实只读 snapshot 正确 fail closed 于计数差异 `33/224/198/26`；脱敏聚合证明其中 24 个值符合批准的三段规则且仅含普通 ASCII 内部空格，现实现错误复用了安全预览分隔规则。根据 successor 规格第 8.1 节，将 `is_unsafe_source_text_v1` 收敛为 XML 非法字符、冻结 UCD `Cc|Cf|Zl|Zp` 和 noncharacter，普通内部空格及 HTML structural 字符仍由 `SafeSourceRef` 预览层安全化。Red 为 `3 failed`；修复后 candidate/normalization `26 passed`，三个路径 Ruff lint/format 与 Mypy 均 PASS。最终 `run-product-catalog-canary.ps1 -RequirePrivateCorpus -RequireCurrentDatabase` 为 `3 passed`，evidence 精确为候选款 `34`、distinct `224`、strict `222`、anomaly `2`、membership `125/7/92`、`safe_output=true`；query digest `47050fac36b449e1665d79b07b8f61e401b8a2cac561826f77950b2e69216f70`，artifact digest `2f63377747a9bd28bebd49cdb98836708cd088b0036c7f1d659ef073cadad66b`，consistent snapshot 为 `2026-08-26 00:37:21.939744`。未写业务表，未输出 URL、密码或完整 Seller SKU。

  Local release gates 完成（2026-08-26）：用户批准 SHA-256 `39758f466791094c301b091986ab7247197d104f2dab130c6497a9463ccebcee` 的 41 路径静态债 successor manifest/baseline 后，全仓 Ruff lint、356 文件 Ruff format-check、354 source Mypy 均 PASS；聚焦静态债测试 `61 passed`，backend offline `1055 passed, 2 skipped, 324 deselected`。Oracle MySQL 8.0/8.4 canonical matrix 各为 migrations `29 passed`、constraints `70 passed`、Stage 5/6 与事务 `47 passed`；4M performance evidence consumer 两版本各 `4 passed, 1 expected skip`；私有 corpus＋current-db SELECT-only canary `3 passed`；permissions/encrypted restore 两版本各 `5 passed`。release-build live 为 legacy-before `1 passed`、P0 `4 passed`、legacy-rollback `1 passed`，并输出 `All live acceptance PASS`。完整 disposable deployment verification 为 `29/70/18/7/13/9/47/17/3/48/1` 全通过，备份 UUID `5c0aaab360b14810b983374169084f07`、恢复 UUID `12fedde4124246b0af16abcf9fca7632`，最终 containers/volumes/networks 均为 0。OpenAPI generate/check PASS；frontend Vitest `297 passed`、lint/typecheck、`p0_catalog` production build PASS，默认 Playwright `12 passed, 1 expected skip`。successor baseline、41 个 strict UTF-8 文件和 `git diff --check` 均 PASS，未登记路径和用户原内容边界完好。用户已授权 candidate branch/commit/push/PR 与 hosted CI；本地候选达到 local release-ready，hosted CI 待 candidate ref 创建后实际运行。

  Candidate 与 hosted CI 完成（2026-08-26）：用户明确授权创建、提交和推送 candidate 分支并创建 PR；分支为 `codex/product-catalog-task20-candidate-20260826`，PR 为 #7，实现候选 HEAD 为 `b86cbffeaac9c237f726052d317278feb56b3754`。Hosted CI 兼容性收敛严格限制在失败证据对应的四个提交：`fad2abf` 使用当前 Python 解释器并修正性能夹具锁定名；`acafb73` 格式化 `0022` 并以 OOXML 原始 ZIP member 名保持跨平台错误码一致；`6ba6313` 修正 analytics 过期 cutoff，并在用户逐路径批准后为 `backend/app/catalog/data/ucd_15_1/**` 固定 LF；`b86cbff` 将 MySQL compatibility job 超时从 20 分钟调整为 30 分钟，使完整 canonical suite 能结束，未放宽测试断言或性能预算。

  最终实现候选的 push run `32936563066` 与 pull-request run `32936567217` 均为 `completed/success`。两组各自的 Ubuntu Python 3.14、Windows Python 3.14、Node 24 / pnpm 11、Oracle MySQL 8.0 和 Oracle MySQL 8.4 五类 job 全部 PASS；MySQL 8.0 已实际越过旧 20 分钟上限并完成全套测试。至此 Task 20 的本地与 hosted CI 硬门均已解除；未 merge PR、未部署、未 tag、未执行生产迁移或流量切换，也未对业务库执行写操作。

## Execution Dependency Summary

1. Tasks 0–1 是绝对硬门；Task 1 successor 规格取得新 digest 和用户再次书面批准前，不得与任何业务代码并行。
2. Task 2 完成后，Task 3 才能创建 schema；Task 4 依赖 schema 与规范化。
3. Task 5 必须先原子化日报 publication/dedup，再允许 Task 6 候选与任一新分析。
4. Tasks 7–10 顺序交付 export/upload → workflow → approval → API。
5. Task 10 为 Catalog OpenAPI 生成 client，Task 11 在该生成物上实现全局 client/request/authz 安全层；Task 12 后才能跑 Milestone A。
6. Milestone A 书面验收后才进入 Tasks 14–18；Task 14 SQL 先于 Task 15 HTTP/adapter。
7. Tasks 16–17 可以在 Task 15 后并行开发，但 Task 18 必须在二者和默认回归都通过后执行。
8. Task 19 只能消费 Milestones A/B 的同一候选 artifact；Task 20 只对 Task 19 已演练的候选执行 release gates。

## Completion Gate

- [x] Task 0 私有 baseline、manifest、已提交/工作树/业务库 revision 和 `0021` 部署历史均有可复核记录。
- [x] Task 1 所列冲突规格、计划、roadmap、CLI、迁移、权限、备份、workflow 和部署契约已正式同步；successor 规格 SHA-256 已再次书面批准；生产计划仍暂停且不重复创建 SKU。
- [x] 实际 P0 migration 是单一线性 head；所有 DB 测试在 fixture/DDL 前证明 runner-owned random loopback Oracle MySQL、`utf8mb4` 与账号分离；fresh、`0020→0021→P0`、带数据 `0021→P0` 在 8.0/8.4 全通过。
- [x] 官方 `NormalizationTest.txt` 的 UCD 15.1 全量 conformance、JCS、SafeSourceRef、XLSX/OOXML 安全、raw-body upload 和敏感输出门全部通过。
- [x] Return dedup 四状态、≤32 delta、publication 双指针 CAS、真实 service/coordination/API/旧 UI staging 调用链、人工决定和失败恢复全部原子、可重放。
- [x] 候选来自全部历史 current publications；经营独有、退货独有、异常和 normalization collision 都显式进入流程。
- [x] 首个目录 V1 中每个 eligible Seller SKU match key 恰有 mapped 或 excluded 决定；unmatched、undecided 和 unresolved collision 为 0。
- [x] `audit_only` 未采用候选产生的 identity、revision、member 和 reservation 增量均为 0；纳入候选只创建一次稳定身份。
- [x] 普通/高风险权限、counter、幂等、projection expiry、并发批准、restore-as-forward-version 和命令恢复全部通过。
- [x] 旧 API 保持 legacy 语义；新 API 只使用稳定 style/SKU 和 P0 catalog；数字路径无歧义且没有 fallback。
- [x] 产品总表显示唯一标准名称；来源标题只作证据徽标；颜色/尺码/SKU 为真实组合，不生成笛卡尔积。
- [x] 五指标、两种退货日期、missing/zero/partial、coverage、六桶和款式各层守恒全部通过；event-date 区间不会漏掉 report date 在区间外的 contributing publication。
- [x] URL、latest request gate、authz generation、8 系列、等价矩阵、键盘/读屏、三档视口和 200% zoom 通过；只有明确 membership reason 才自动规范化详情 URL。
- [x] 403/404/草稿 409、角色/revision/key 变化会销毁 reveal 和复制缓冲；已认证 API 401 会单次清空 session/authz/gates/全部可逆缓冲且迟到响应不能复活；危险来源值不在普通输出。
- [x] Milestones A/B 的真实 React → FastAPI → MySQL 无 mock 证据都绑定同一候选 artifact。
- [x] Task 19 固定事实对账的 unexplained 差异为 0；APP/VITE mode、bundle、process 和 attestation 一致；`/catalog` 始终可用，legacy 直达不读 P0；`legacy→P0→legacy` 三套 fresh build/process 的 rollback 前后数据库业务 checksum 相同。
- [x] 两份真实 CSV 精确重现 `22×24/9/5` 与 `13×10/6` 基线，并通过逗号 quoting、LA 同业务日和多标题不覆盖标准名称断言；当前库 canary 精确重现 `34/224/222/2` 和 `125/7/92`，输出符合 allowlist。
- [x] MySQL 8.0/8.4 五项 p95、EXPLAIN、连接池、XLSX 全流程、4,088/4,088 dedup 分布、物理规模和加密恢复全通过，未放宽参数。
- [x] Runtime/migration/backup/restore/canary 账号分离及最小 grant 负向测试通过；独立生成、固定 digest 的 synthetic v1/`0020` golden 仍可安全读取/恢复。
- [x] Backend 全量、OpenAPI drift、frontend unit/lint/type/build、默认 Playwright、release live、workflow contract 和 deployment verification 的本地 canonical runners 全通过；获准创建 candidate ref 后，push/PR 两组 hosted CI 的五类 job 均已实际通过。
- [x] 用户指南、运维/切换/rollback 文档完成，工作区三方比较证明用户原修改未丢失。
- [x] Candidate 分支、commit、push 和 PR 均有用户明确授权；截至完成检查未 merge、未 tag、未部署、未执行生产迁移或生产切换，也未对业务库执行写操作。

## Handoff

实施者每完成一个 Task 都应更新本文 checkbox、记录实际命令和 Expected/Actual；任何路径新增先更新 touched manifest 并重做 Task 0 路径安全检查。每个里程碑交付证据后必须暂停等待用户验收。若实际迁移头、数据库产品/版本、真实输入结构或已批准规格发生变化，停止后续任务，先向前修订规格和本计划，禁止自行兼容猜测。
