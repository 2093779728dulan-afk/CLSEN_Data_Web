# 商品主档与产品分析发布、切换和回滚

本 runbook 只描述受控候选验证，不授权生产迁移或流量切换，也不授权 tag 或部署。未经精确 master SHA、`master-required`、release-only gates、变更窗口和负责人批准，不得用于生产。

## 三层门禁

2026-10-21用户明确不再要求MySQL8.0测试，当前主用8.4。自本次策略修订后的来源起，PR/master兼容检查及日常矩阵默认只运行8.4，性能producer/证据预检与加密恢复也默认只要求8.4；不减少8.4的测试集合、顺序、采样、来源身份、事务/权限、清理或其他发布门禁。8.0保留为显式可选诊断能力，不再默认验证或承诺其兼容性。已创建的旧CI仍按旧来源执行，不伪记跳过8.0为通过，不取消运行中的8.4。历史正式project-optimization基线的固定双版本证据格式保留溯源，不自动改写或重启该历史流程；如后续要使用它，须先明确其单版本适配，不能用本次CI绿灯冒充该基线完成。

- Pull request 只由 `Application compatibility` 的 PR 事件触发，稳定 required check 为 `pr-required`。它汇总 Ubuntu full、Windows smoke、frontend full 与 Oracle MySQL 8.4；功能分支 push 不再重复运行。
- 合并到 `master` 后，稳定 check 为 `master-required`，同样要求上述四类检查（MySQL只要求8.4）。master run 不自动取消。
- `Product catalog release gates` 只执行 release-only 的 performance、SELECT-only canary、encrypted restore、live、deployment、generated contract 与 workspace boundary，不重复普通 offline、frontend 或 hosted MySQL compatibility。

手动 release 必须输入当前完整 40 位 master SHA。provenance job 从 API 重新解析当前 master，并要求该 SHA 已有唯一成功的 `master-required`；通过后才允许 master-only `clsen-release-gates` environment 分配专用 self-hosted runner。若 master 在批准前后或运行期间前进，整次 gate 失败，不能复用旧 evidence 或旧批准。

专用 runner group 必须只允许 `.github/workflows/release-gates.yml@refs/heads/master`。canary URL、8.4性能 evidence 路径和仓库外 private manifest/corpus 路径只能存在于 `clsen-release-gates` environment secrets；同名 repository/organization secret 或 runner Process/User/Machine 变量会阻断发布。若套餐不能限制 workflow/ref，runner 保持离线且不挂载私有 corpus。

## release-scoped selector

后端 `APP_PRODUCT_ANALYTICS_SOURCE` 与前端构建变量 `VITE_PRODUCT_ANALYTICS_SOURCE` 必须由同一发布动作同时设置，只接受 `legacy_parser` 或 `p0_catalog`。缺失、非法或二者不一致都必须失败关闭。选择器只控制产品分析入口、旧 dashboard 产品 tab/modal 和 `/products*`；`/catalog` 不受切换影响。

## 本地候选门

```powershell
$sha = git rev-parse HEAD
.\scripts\run-ci-profile.ps1 -Profile release-only -ReleaseSuite live -SourceSha $sha -PythonExecutable .\.venv\Scripts\python.exe -ListOnly
.\scripts\run-ci-profile.ps1 -Profile release-only -ReleaseSuite performance -SourceSha $sha -PythonExecutable .\.venv\Scripts\python.exe -ListOnly
.\scripts\run-ci-profile.ps1 -Profile release-only -ReleaseSuite canary -SourceSha $sha -PythonExecutable .\.venv\Scripts\python.exe -ListOnly
.\scripts\run-ci-profile.ps1 -Profile release-only -ReleaseSuite restore -SourceSha $sha -PythonExecutable .\.venv\Scripts\python.exe -ListOnly
```

`-ListOnly` 只列出 canonical selector，不运行发布动作。实际 performance 门默认只绑定 Oracle MySQL 8.4 的外部 `analytics_scale_v1` evidence；evidence 必须包含并匹配 `source_sha`、Git tree、完整 artifact digest 和 runner digest。真实 4M evidence 只能在最终 master SHA 的 `master-required` 成功后生成一次；master 前进后旧 evidence 立即失效。显式选测8.0时另需对应版本证据，不把它重新加入默认发布要求。

canary 需要当前业务库 SELECT-only URL，以及仓库外 private manifest 和 corpus root。release 模式拒绝仓库内路径、reparse point、路径逃逸、缺失/多余 CSV 或 hash/count 不一致；不要移动、清理或改写当前工作区 `data/`。所有写入、压测和恢复只允许 runner-owned `clsen_data_test*`/`clsen_restore_*`。缺失输入一律 FAIL，不是 skip。

### Canary 输入与只读范围

manifest 必须包含明确批准的 `approved_scope`（`site_id`、逐日 `report_dates`、两种 `report_types`）和独立 `canary_expected`。先确定范围，再用标准库工具生成，不能从待测数据库反填预期值：

```powershell
python tools/build_golden_manifest.py --source <仓库外样本副本> --output <仓库外manifest> --site-id <批准的站点ID> --start YYYY-MM-DD --end YYYY-MM-DD
python tools/verify_golden_manifest.py --source <同一副本> --manifest <同一manifest>
```

每个批准日期必须恰有一份经营报告和一份退货报告；没有固定 62/74 文件数或历史商品计数。数据库仅核对同站点、同报告日期的当前发布版本和 active 行，包含空报告覆盖、逐日报表行数、逐类型 SKU 集合摘要及候选款式/交集计数。退货日期与报告日期可不同，日期范围按报告日期选取。原有逐文件字段、数值、百分比、文本和 UTC 语义核验保留。

预期值生成器不调用应用解析器或数据库；当前 SKU oracle 限可打印 ASCII，其他编码的 SKU 需另审独立预期合同。原文件编码不受应用支持时保留原件，只对获准样本副本作无损转码，另记原始/输入哈希与逐单元格等价证明；不能把转码后的通过写成原编码受支持。

账号仅授目标表 SELECT，要求 TLS，不能复用应用/管理员账号。URL 保持证书中的主机名并配置 `ssl_ca`、`ssl_check_hostname=true`。若使用本机 TCP 转发，仅在该任务进程设置 `APP_PRODUCT_CATALOG_CANARY_LOOPBACK_PORT`；连接走 `127.0.0.1` 指定端口，TLS 仍校验证书原主机名，不关闭身份校验。转发须绑定回环、标记任务归属并核对实际端口/容器 IP；不得开放原数据库公网端口或修改用户级环境。单独 `RequireCurrentDatabase` 也须提供同一 manifest/corpus，脚本会核验其完整性。定向 canary 通过不等于完整 release-only 通过。

## Actions 用量证据

主验收口径是 GitHub API 中各 job `started_at` 到 `completed_at` 的未加权 runner-minutes：最终 PR 目标不超过 30，且相对 96.87 基线降低至少 65%；master 目标不超过 45。官方 billing/usage 如可读取，应另列操作系统倍率后的计费口径，不得与未加权口径混算。通过这些门仍不构成部署授权。

## 切换演练

canonical live runner 在同一随机 MySQL 与同一候选事实快照上顺序执行：

1. fresh `legacy-before` build + FastAPI；验证旧入口不读取 P0。
2. fresh `p0` build + FastAPI；验证目录批准、产品总表、详情和 provenance。
3. fresh `legacy-rollback` build + FastAPI；验证恢复旧入口。

每个阶段使用独立输出目录、端口和进程树。P0 后与 rollback 后的 catalog、publication、dedup、facts 和 audit 语义 checksum 必须一致；rollback 不运行数据库迁移、不改目录指针。

## 故障回滚

停止向错误 release 发送新流量，启动新的 `legacy_parser` 后端和新的 legacy 前端 artifact，核对 process environment、bundle marker、endpoint provenance 和 attestation 后再切换。不得复用第一次 legacy 进程冒充回滚，也不得 downgrade Alembic 或回写历史目录版本。

目录内容错误使用向前目录版本纠正。数据库或对象存储故障先创建加密备份，并只恢复到新的隔离库验证；不要覆盖现有业务库。
