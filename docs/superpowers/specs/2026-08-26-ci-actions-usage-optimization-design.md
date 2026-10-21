# GitHub Actions 用量优化设计

日期：2026-08-26

状态：已由用户于 2026-08-26 书面批准

基线提交：`51beb33482eb0174a796a549bec8e6f98df69d2f`

基线运行：[Application compatibility #32944715482](https://github.com/dulanjy/CLSEN_Data_Web/actions/runs/32944715482)

## 1. 背景与目标

当前 `Application compatibility` 同时监听所有 `push` 与 `pull_request`。同一候选 SHA `e37cf2d` 因此产生一组 push 和一组 pull request 运行，合计 96.87 未加权 runner-minutes。合并后的 `master` 基线运行耗时约 22 分 36 秒、消耗 50.73 未加权 runner-minutes；关键路径是 MySQL 8.0 的 22 分 32 秒。

本次优化以减少 GitHub Actions 用量为第一目标，而不是以增加并行 job 换取最短墙钟时间。用户已批准以下覆盖调整：

- 功能分支 push 不再运行完整 CI，只保留 pull request 和 `master` push；
- Windows 不再执行完整 offline suite，只执行固定的跨平台敏感集合；
- pull request 只运行 MySQL 8.0，合并到 `master` 后再运行 MySQL 8.0/8.4 双版本完整兼容门。

验收目标是把单次 pull request 更新从约 97 未加权 runner-minutes 降到不超过 30 未加权 runner-minutes，降幅至少 65%。`master` 单次运行目标不超过约 45 未加权 runner-minutes。

## 2. 非目标

- 本次不减少 Ubuntu offline、前端或当前 hosted MySQL 8.0 兼容节点集合；
- 本次不按变更路径跳过 job；
- 本次不把 MySQL suite 拆成更多并行 job；
- 本次不改变测试断言、性能预算、数据库安全边界或发布完成定义；
- 本次不部署应用、不迁移业务数据库，也不改变产品流量 source；
- 本次不把缓存作为主要优化方向；现有 pip/pnpm 缓存保留。

## 3. 当前问题

### 3.1 重复事件

`.github/workflows/compatibility.yml` 对功能分支 push 与其 pull request 各运行一次相同矩阵。两次运行并行时不会明显延长单次等待，却将 runner 用量近似翻倍。

### 3.2 重复 offline suite

Ubuntu、Windows、MySQL 8.0 和 MySQL 8.4 job 均执行同一 offline backend suite。基线中两个 MySQL 副本分别耗时约 2 分 06 秒和 1 分 56 秒；手动 release workflow 也先执行 offline suite，再调用会重复执行 offline suite 的 matrix runner。

### 3.3 canonical runner 漂移

hosted workflow 内联维护 MySQL 测试长清单，本地 `scripts/test-mysql-matrix.ps1` 又维护另一套默认范围，manual release workflow 调用的范围小于 hosted compatibility。现有契约测试主要检查字符串是否出现，不能证明 YAML 中实际调用的 suite、版本和参数正确。

### 3.4 过期运行不会自动停止

连续推送 pull request 时，旧 SHA 的完整矩阵继续占用 runner。旧 SHA 的成功结果不能代替新 SHA 的门禁证据。

### 3.5 发布输入作用域过大

release workflow 把 canary URL、外部性能证据和旧任务私有 baseline root 设为 job 级变量，使不需要这些输入的普通 pytest、pnpm 与构建步骤也能读取。该私有 baseline 又绑定旧 HEAD，不能证明新的已提交 release source。私有 CSV runner 还把 corpus 固定在会被 clean checkout 清理的仓库内 ignored 路径。前端 `VITE_PRODUCT_ANALYTICS_SOURCE` 与后端 `APP_PRODUCT_ANALYTICS_SOURCE` 也没有由同一步骤明确成对设置。

### 3.6 证据绑定不完整

性能 evidence consumer 校验 fixture、MySQL 版本和样本计数，但没有完整验证 evidence 属于当前 source SHA、Git tree 与 artifact digest。

## 4. 总体架构

CI 分为 pull request、`master` 和手动发布三个层级。三个层级共享同一份版本化 suite manifest 和同一组 runner，workflow 只选择 profile，不再直接维护 pytest 文件长清单。

### 4.1 Pull request 门禁

触发器只接受 `pull_request`。同一 pull request 的新提交自动取消旧运行。

必需 job：

- `ubuntu-full`：Ruff lint、Ruff format check、Mypy、完整 offline pytest；
- `windows-smoke`：固定跨平台敏感测试；
- `frontend-full`：lint、typecheck、Vitest、默认 Playwright 和 `legacy_parser`/`p0_catalog` 两种 production build；
- `mysql-8.0`：当前 hosted compatibility 的完整 MySQL 8.0 节点集合，不重复 offline pytest；
- `pr-required`：稳定名称的汇总门。

`pr-required` 使用 `if: always()` 读取全部依赖结果。只有四个执行 job 均为 `success` 时成功；意外的 `skipped`、`cancelled` 或 `failure` 均失败。

### 4.2 Master 门禁

触发器只接受 `push.branches: [master]`。`master` 运行不自动取消，以保留每个已合并 SHA 的完整审计证据。

它执行 pull request 的全部覆盖，并增加 MySQL 8.4。`master-required` 只有在 Ubuntu、Windows smoke、前端、MySQL 8.0 和 MySQL 8.4 全部成功时才成功。

### 4.3 手动发布门禁

`Product catalog release gates` 继续由 `workflow_dispatch` 触发，并要求调用者提供确定的 `source_sha`。

GitHub 的 `workflow_dispatch` 没有声明式 branch filter，因此不能只靠 YAML 声称“只能从 master dispatch”。发布 workflow 先在 GitHub-hosted runner 上运行不绑定 release environment 的 `provenance` job；该 job 只拥有 `actions: read` 与 `contents: read`，通过 API 取得远端当前 `master` SHA、明确 checkout 该 SHA 并从该 checkout 执行 verifier。`github.ref` 与 `github.workflow_sha` 只作为待验证数据，不能决定 verifier 来源。它在任何 self-hosted runner 分配、候选 checkout 或私有输入注入前验证：

1. `github.ref`、`github.workflow_sha`、输入 `source_sha` 与远端当前 `master` 精确一致；
2. 同一 `source_sha` 存在 event=`push`、branch=`master`、workflow ID 精确匹配且成功的 `master-required`；
3. API 缺失、分页不完整、结果歧义或任何 SHA/check 不一致均失败。

验证通过后，它只输出已验证的完整 SHA。后续绑定 release environment 的 gate job 仅拥有 `contents: read`；GitHub 必须先通过 environment 的 master deployment-branch policy，才允许把 job 分配到 self-hosted runner。专用 runner group 还必须只允许 `.github/workflows/release-gates.yml@refs/heads/master`；若当前 GitHub 套餐不支持 workflow/ref allowlist，则 runner 保持离线且私有 corpus 不挂载，直到另行批准替代的临时 runner 流程。gate 获批并取得 runner 后，先重新查询远端 `master`、断言它仍等于已验证 SHA，再断言 checkout HEAD 相等并执行 workspace-boundary。随后所有 release suite 先各自运行 `validation-only`，每个 validator 只接收本 suite 输入；只有全部 validator 成功后才允许任何 suite 执行。全部 gate 完成后再次查询远端 `master` 并复验 workspace/source identity，漂移即整次 release gate 失败。它不重复普通 offline、Windows smoke、前端 full 或 hosted compatibility MySQL suite。GitHub Actions 权限是 workflow/job 级，因此不能声称只给单个 step 授予 `actions: read`。敏感名称只能存在于 `clsen-release-gates` environment secrets，不能同名存在于 repository/organization secrets；environment policy、runner-group policy 或 secret scope 不满足时，需另行授权修正并在修正前禁止合并/dispatch。

## 5. Canonical suite manifest

新增 `scripts/ci-suite-manifest.json`。顶层键精确为 `schema_version`、`profiles`、`mysql_suites`、`mysql_exclusions`、`windows_smoke` 与 `release_suites`；禁止未知字段、重复路径与父目录逃逸。

顶层 profile 固定为：

- `ubuntu-full`；
- `windows-smoke`；
- `frontend-full`；
- `mysql-compatibility`；
- `release-only`。

`mysql-compatibility` 是不可部分选择的有序聚合 profile，只由 `mysql-migrations`、`mysql-legacy` 与 `mysql-p0` 三个 suite 组成，并在同一版本、同一 disposable database 上串行执行。`test_product_catalog_permissions.py` 属于 `mysql-p0`，不得因 release restore runner 也曾调用它而移出 hosted compatibility。

每个带 `mysql` marker 的测试模块必须在 `mysql_suites`、release-only pytest selectors 与 `mysql_exclusions` 的并集中恰好出现一次：归入一个 compatibility suite、一个 release-only suite，或带有非空理由的显式 exclusion；不得未分类或重复分类。exclusion 只记录优化前已经不属于任何批准 runner 的模块，不能用于删除现有覆盖；新增 marker 模块若没有明确归属即失败。优化前 hosted compatibility 实际收集的 MySQL node IDs 保存为测试 fixture，优化后的 pull request MySQL 8.0 和 `master` 双版本集合必须与该基线精确一致。仅由 performance、canary、restore、live 或 disposable deployment runner 执行的 selector 归入 `release-only`，不得被误计为普通 compatibility 遗漏。

Windows smoke 的初始范围固定覆盖：

- `backend/tests/contracts/`；
- `backend/tests/unit/catalog/test_ooxml.py`；
- `backend/tests/unit/catalog/test_normalization.py`；
- `backend/tests/unit/imports/test_storage.py`；
- `backend/tests/unit/auth/test_product_catalog_live_harness.py`；
- `backend/tests/unit/deployment/test_entrypoint.py`。

Windows smoke 的路径边界必须与上述集合精确一致。优化前 node IDs 保存为必须保留的基线子集；本次计划新增的 contract nodes 使用显式 allowlist，未来扩大或缩小路径边界仍必须修改 manifest schema fixture 并由代码审查显式确认。Ubuntu offline 同样冻结优化前 node IDs 为必须保留的基线子集；前端以固定 lint、typecheck、Vitest、Playwright 和双 source production-build 命令证明 full coverage，不维护易漂移的前端 node-ID 文件。

## 6. Runner 接口

新增 `scripts/run-ci-profile.ps1` 作为 workflow 与本地调用的统一入口。它只接受 manifest 中的 profile、可选 MySQL 版本以及显式 evidence/output 参数。`mysql-compatibility` 必须一次展开全部三个有序 MySQL suite，调用方不能请求其子集。`release-only` 必须再接受一个 allowlisted release suite，使 performance、canary、restore、live、deployment、generated-contract 与 workspace-boundary 分别由独立 workflow step 调用并保持秘密最小作用域。

现有 `scripts/test-mysql-matrix.ps1` 收敛为纯数据库 runner：

- 默认不运行 offline suite；
- 必须显式传入一个 manifest MySQL suite 或受控 suite 集合；
- 每个版本创建 runner-owned 随机 `clsen_data_test*` 数据库、独立 migration/runtime/backup 账号和校验 TLS；
- migration、grant、测试和清理失败均返回非零；
- finally 只清理当前 run label 对应的容器、证书与临时账号；
- 不接受生产数据库名、外部测试身份或未列入 manifest 的路径。

workflow 不再内联数据库 bootstrap、grant manifest 解析或 pytest 路径列表。PowerShell 公共的 schema revision 读取和 manifest 校验提取为单一模块，避免多个脚本复制。

## 7. 并发与事件策略

compatibility workflow 只监听：

- `pull_request`；
- `push` 到 `master`。

三类 concurrency group 使用互异固定前缀：pull request 为 `application-compatibility-pr-<number>` 且 `cancel-in-progress: true`；`master` 为 `application-compatibility-master-<full-sha>` 且 `cancel-in-progress: false`，避免跨 workflow 碰撞或连续三次 push 时替换仍 pending 的旧 SHA；手动发布为 `product-catalog-release-<source-sha>` 且 `cancel-in-progress: false`，防止同一候选并发执行两套 release gates。runbook 禁止重复 dispatch，并明确 GitHub 可能以更新的同 SHA pending run 替换更早的同 SHA pending run，但不得取消已经 running 的 release。

功能分支 push 不产生 compatibility run。旧的 push/pull-request 双事件证据要求由本设计明确替代为“pull request 预合并证据 + master 合并后证据”。

## 8. 凭据和证据边界

- workflow 默认 `contents: read`；只有独立发布 provenance job 增加 `actions: read`，release gate job 不继承该权限；
- canary URL 只注入 `run-product-catalog-canary.ps1` 所在 step；
- 私有 manifest/corpus 使用仓库外绝对路径，只注入 canary step；release 模式拒绝仓库内路径、reparse point、缺失文件、manifest hash/count 不一致；
- 性能 evidence 路径只注入 performance step；
- 旧任务私有 baseline root 不再进入 release workflow；workspace-boundary 从已验证 source SHA 重新推导 Git tree、artifact digest 与 clean checkout 状态；
- 前端和后端 source 由同一个 release step 同时设置为 `p0_catalog`，任何缺失或不一致均失败；
- 日志只允许测试计数、耗时、source SHA、Git tree、artifact/evidence digest 和布尔安全结果；
- URL、密码、完整 Seller SKU、标题、订单号、留言与牌照不得进入日志或 artifact。

self-hosted gate 的第一个无秘密 preflight 必须确认敏感变量在 runner service 的 Process、User、Machine scope 均不存在，避免 YAML step scope 被主机继承环境绕过。若命中，先停止并取得单独授权完成迁移、清除和必要的 runner service 重启；不得由 workflow 自动修改主机环境。

性能 evidence schema 增加并强制验证：

- `source_sha`；
- `git_tree`；
- `artifact_digest`；
- `runner_digest`；
- 既有 fixture、MySQL 版本、规模、硬件 profile、query plan 与 p95 字段。

任一绑定不一致必须在性能测试或部署动作前失败。

真实 4M performance evidence 只在候选已经合并、最终 `master` SHA 的 `master-required` 成功后生成一次；若生成期间 `master` 前进，该 evidence 失效并必须为新的最终 SHA 重建。`artifact_digest` 定义为对 `git ls-tree -r --full-tree <source_sha>` 规范化 UTF-8/LF 输出计算的 SHA-256；`runner_digest` 定义为 manifest 固定的 performance producer、consumer 与 runner Git blob 身份清单的 SHA-256。producer 和 consumer 均从精确 checkout 重新推导这些字段，不能接受调用方自报值或循环计算 evidence 文件自身摘要。

## 9. 失败语义

- 所有必需门 fail-closed；不使用 `continue-on-error`；
- 重试不能减少版本、suite、fixture 规模或断言；
- manifest schema、路径、分类、node ID 基线或期望版本不一致即失败；
- pull request 中只有被新 SHA 取代的旧运行允许自动取消；
- `master` 和 evidence producer 不允许自动取消；running release 不允许取消，同 SHA 的重复 pending dispatch 按已记录的平台队列语义处理；
- release 拒绝非当前 `master`、缺少成功 `master-required`、缺少秘密或 evidence 绑定不一致的 SHA；
- 清理步骤使用 `always()`，但清理失败仍使相应 job 失败并保留安全的定位信息。

## 10. 契约测试

workflow 契约测试使用结构化 YAML 解析，不再通过任意字符串包含判断语义。测试至少证明：

- 只有 pull request 与 `master` push 两个自动触发面；
- pull request 可取消旧运行，`master` 与 release 不可自动取消；
- pull request 不实例化 MySQL 8.4；
- `master-required` 依赖 MySQL 8.0/8.4；
- workflow 通过 canonical runner/profile 调用 suite，不含 pytest 文件长清单；
- MySQL profile 不隐式执行 offline suite；
- release-only 不重复普通 regression；
- 秘密仅存在于对应 step env；
- source SHA、成功 master gate 和 evidence digest 在 release 执行前验证；
- gate 获批后在任何 secret-backed 执行前重新验证当前 master/workspace，并要求全部 release suite 的 validation-only 阶段先成功；结束后再次复验 master/workspace；
- 所有带 mysql marker 的模块均恰好分类一次，compatibility node IDs 与批准基线一致；
- `test_product_catalog_permissions.py` 仍属于 compatibility，release restore 不重复该普通节点；
- PR/master/release concurrency group 使用互异固定前缀与完整身份；release 按 source SHA 分组、`cancel-in-progress: false`，并禁止重复 dispatch；
- cleanup 失败注入会使对应 runner 和汇总门返回失败。

## 11. 验收

### 11.1 功能验收

在临时 pull request 上依次证明：

1. 只有 pull request run，没有功能分支 push run；
2. 快速推送第二个 SHA 后，第一个 pull request run 被取消；
3. 第二个 SHA 的 `pr-required` 成功且不包含 MySQL 8.4；
4. Ubuntu offline 包含全部优化前 node IDs，新增 node 仅来自显式批准的本计划 contract allowlist；
5. MySQL 8.0 compatibility node IDs 与优化前一致；
6. Windows 路径边界精确等于批准 smoke 集合，保留全部优化前 node IDs，新增 node 仅来自显式批准的本计划 contract allowlist；
7. 前端完整门全部执行。

合并后证明：

1. `master-required` 同时要求 MySQL 8.0/8.4；
2. 两个版本的 compatibility node IDs 与批准基线一致；
3. 契约与本地合成结果证明任一依赖非 success 时汇总门失败；如需 hosted 人为失败演练，必须另行批准且不得制造无业务意义的提交；
4. master run 不会被后续提交自动取消。

手动 release dry-run 证明错误 SHA、非当前 master、缺成功 gate、缺秘密和 digest 不一致均在 release-only 副作用前拒绝。随后对同一批准 SHA 实跑完整 release-only 门。

### 11.2 用量验收

以 GitHub API 的 job `started_at/completed_at` 计算未加权原始 runner-minutes，不使用 workflow 墙钟替代，也不把它冒充平台账单分钟。若 GitHub billing/usage 导出可用，将其作为第二口径旁证并单独标注操作系统倍率：

- 单次 pull request 更新不超过 30 未加权 runner-minutes；
- 相对 `e37cf2d` 双事件基线 96.87 未加权 runner-minutes，降低至少 65%；
- 单次 `master` run 不超过约 45 未加权 runner-minutes；
- MySQL job 中 offline pytest 执行次数为零；
- release-only 中普通 offline pytest 执行次数为零；
- superseded pull request run 的取消行为有实际证据。

若保留全部批准覆盖后未达到用量目标，不得通过删除测试、跳过 MySQL 版本或提高失败容忍度达标；应另行分析慢 fixture/query 或提出路径感知设计。

## 12. 分支保护迁移

先让新 workflow 在临时 pull request 上生成 `pr-required`，确认汇总依赖和失败语义。当前仓库没有 branch protection 或 ruleset；经单独授权后，首次创建保护时直接加入已经出现的 `pr-required`，从首次启用保护起不得出现空窗。只有读回结果证明旧 required checks 实际存在时，才执行“先加新门、再移除旧名称”的迁移。

`master-required` 用于合并后审计和 release provenance，不作为 pull request 合并前 required check，因为 MySQL 8.4 按批准策略只在 `master` 运行。

## 13. 采用方案与放弃方案

采用“分层门禁”：pull request 使用 MySQL 8.0，`master` 使用双版本，release 只运行发布专属门。它在不增加 job 分片的前提下消除最大重复用量。

本轮不采用路径感知门禁，因为 backend 契约会读取 workflow、scripts 和部分 docs，错误分类可能漏掉跨模块影响。待收集至少一个月变更与 job 数据后再单独设计。

本轮不采用最小 PR 门禁，因为把全部数据库兼容验证后移到 `master` 会使常见 MySQL 8.0 回归只能在合并后发现。
