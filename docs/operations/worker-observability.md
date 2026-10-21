# Worker 可观测性运行手册

本文是本地 Windows 部署的操作指南，供项目管理员和数据库运维人员判断 Worker 是否可达、某类消费者是否失败，以及队列原生状态是否需要处理。它不提供业务任务重排或修改按钮，也不替代数据库备份与恢复手册。

## 启动与停止

从仓库根目录启动长期 Worker：

```powershell
.\scripts\run-worker.ps1
```

测试库只排空当前可执行任务后退出：

```powershell
.\scripts\run-worker.ps1 -UseTestDatabase -Drain
```

Worker 只有在 schema `0023` 预检、实例注册和首次数据库心跳写入成功后才领取新任务。正常停止使用当前终端的 `Ctrl+C`；进程会先关闭领取门禁，再等待心跳线程退出，最后写入 `stopped`。若注册失败或心跳连续写入失败，保持 Worker 停止并先检查数据库连接、权限与 schema，不要绕过门禁。

## 状态解释

管理员控制台“备份与任务”中的时间来自一次数据库 `UTC_TIMESTAMP(6)`，浏览器时钟不参与健康判断。阈值固定为 `10/30/60/15`：每 10 秒写一次心跳，年龄达到 30 秒为 `stale`，达到 60 秒为 `offline`，页面仅在该标签活动时每 15 秒刷新。

“在线”只表示最近成功写入数据库心跳，不表示四类消费者都成功。`consumer_health=failing` 与 Worker 心跳正交；界面会明确显示“进程在线，某消费者失败”。`maintenance_active` 只表示维护写屏障，不会把在线、延迟或离线状态改写成另一种含义。

`query_health=unknown` 表示该只读查询失败。此时对应指标显示“无法确认”，不能当作零。服务端只持久化和展示封闭的 `failure_code`；异常堆栈只进入受控服务端 JSON 日志，不进入管理员 API。

## 四类队列映射

- `return_dedup`：无租约或租约过期的 `building` 是可执行；有效租约是执行中；过期租约同时计入 stale。retry wait 和 stuck 不适用。
- `publication_outbox`：到期 `pending` 是可执行；未来 `pending` 是等待重试；有效 `processing` 是执行中；过期 `processing` 是 stale。
- `catalog_import`：`uploaded` 是可执行；最新解析尝试租约有效的 `parsing` 是执行中；租约过期的 `parsing` 是 stuck，绝不能标为可执行。
- `catalog_export`：`building` 仅显示为 `unresolved_building`。该原生协议没有领取者或租约，actionable、in-flight、retry wait、stale 和 stuck 均显示“不适用”，不能用零代替。

每类队列查询使用独立数据库连接。一类查询失败不会隐藏其他三类的计数或消费者状态。队列原生行仍由既有业务状态机管理；观测代码不改写领取、租约、失败或终态。

## 30 天保留

停止或最后心跳超过 30 天的 Worker 实例可由注册后的有界清理删除。每次最多删除 500 个 `worker_instances` 父行，相关 `worker_consumer_states` 通过外键级联删除。清理失败不会关闭已经成功注册的领取门禁，也不会删除业务队列数据。

不得用应用账号执行无条件删除，也不得把保留清理扩展到业务表。需要更改 30 天或 500 行上限时，必须另行设计、审批和验证。

## 部署顺序

1. 停止旧 API 和旧 Worker，确认不再领取新任务。
2. 按备份手册创建可恢复备份。
3. 使用迁移身份显式升级到 `0023`，再同步运行账号的表级权限。
4. 只读确认 `alembic_version` 恰好为 `0023`。
5. 部署同一候选 SHA 的 API 和 Worker。
6. 启动 Worker，确认数据库出现真实、递增的心跳序列。
7. 打开管理员页面，检查四类队列顺序、查询健康和消费者健康。

不要让启动脚本自动迁移，不要手工编辑 `alembic_version`，也不要把不同 SHA 的 API、Worker 和证据混用。

## 回滚

管理员 UI 可以独立回滚。API/Worker 在 schema `0023` 上的应用回滚只能回到 Stage 2 schema anchor `3750ad3` 或与 `0023` 明确兼容的提交；Stage 1 的 `0022` 应用不能直接运行在 `0023` schema 上。

回滚 API/Worker 时，先停止新 Worker，并等待已有原生租约或领取进入各自既定恢复条件。不要手工修改 `processing`、`building` 或 `parsing` 行。紧急应用回滚不删除 `worker_instances` 或 `worker_consumer_states`；删除观测表必须使用另行批准的迁移。

## 故障检查

- Worker 未注册：检查 schema 是否为 `0023`，运行账号是否具有两张观测表所需的 `SELECT/INSERT/UPDATE`，并检查 `worker_registration_failed`。
- 心跳 stale/offline：确认进程仍在、数据库可达且没有长时间连接阻塞；查找 `heartbeat_write_failed`，不要仅凭进程 PID 宣告在线。
- 进程在线但消费者失败：按 `queue_name` 和安全 `failure_code` 查受控 JSON 日志；修复原因后让既有状态机恢复，不要直接改行。
- 单类 `query_health=unknown`：检查该表的 SELECT 权限和 SQL 错误；其他队列仍可信，不要把整页归零。
- `catalog_import` stuck：按导入恢复流程处理过期解析租约，不要将其改为 uploaded。
- `catalog_export` 未决构建：该协议不能证明是否可领取；检查物化日志和工件状态，不要伪造 in-flight。
- 维护中状态不一致：先确认写屏障所有者和持续时间，再结合 Worker 心跳判断；两者不可互相替代。

性能验收使用 manifest 中已批准的逐场景 ceiling，三次预热、二十个样本、三轮，取各轮 p95 的中位数。证据必须绑定一个干净候选 SHA，并同时包含 Oracle MySQL 8.0 和 8.4；超限、跳过、重试或 SHA 不一致均失败关闭。

## 同 SHA 验收

Task 8 只执行一次完整门禁。先提交全部 Stage 2 代码并确认 tracked workspace 干净，再冻结候选 SHA；证据目录必须位于仓库外且尚不存在：

```powershell
$stage2Sha = (git rev-parse HEAD).Trim()
$evidenceRoot = Join-Path ([IO.Path]::GetTempPath()) "clsen-stage2-$stage2Sha"
pwsh -File scripts/run-project-optimization-stage2.ps1 `
  -SourceSha $stage2Sha -Mode Collect -EvidenceRoot $evidenceRoot
pwsh -File scripts/run-project-optimization-stage2.ps1 `
  -SourceSha $stage2Sha -Mode Validate -EvidenceRoot $evidenceRoot
```

`Collect` 统一执行完整 profile、Oracle MySQL 8.0/8.4、真实 Worker 心跳与四队列性能、EXPLAIN、备份恢复、部署演练和管理员页截图；不要在它之前重复运行这些长时项目。`Validate` 不重跑测试，只复核 SHA、节点身份、ceiling、命令结果、证据摘要和脱敏状态。任一非零退出、未解释 skip、xfail、retry、证据覆盖、摘要不一致或工作区变脏都会失败关闭。
