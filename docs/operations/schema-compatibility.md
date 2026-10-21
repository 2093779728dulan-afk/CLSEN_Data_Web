# Schema 兼容性、显式迁移与回滚

本文面向有权部署应用制品、运行备份和执行数据库迁移的运维人员。目标是在 API 或 Worker 因 schema 不兼容而拒绝启动时，安全判断原因，并恢复一组已经证明兼容的“代码 + schema”。本文不授权迁移任何具体环境；迁移仍需单独的变更审批和维护窗口。

## 启动契约

每个真实 API 和 Worker 进程都必须在提供服务或领取任务前确认：

- `alembic_version` 存在；
- 查询返回且只返回一行；
- 该行的 `version_num` 与候选代码 `backend/app/maintenance/schema_revision.py` 中的 `CURRENT_SCHEMA_REVISION` 完全相同。

兼容性检查只执行一次只读查询：

```sql
SELECT version_num FROM alembic_version;
```

检查不会运行 Alembic、创建或修改表、更新版本号、重试写操作，也不会接受备份读取器的历史 revision。检查失败时拒绝启动是预期的安全行为。

九个受保护入口及其失败边界由 `scripts/schema-compatibility-entrypoints.json` 统一登记。支持的本地 API/Worker 脚本和容器角色先做进程前预检；直接 Uvicorn 仍由 FastAPI lifespan 防守，Worker CLI 也会在构造存储、runner 或领取任务前再次检查。

## 手工预检

从仓库根目录进入 `backend` 后运行。预检仅适合确认当前配置指向的数据库是否与当前代码兼容；成功并不授权启动、迁移或处理业务数据。

```powershell
Push-Location .\backend
..\.venv\Scripts\python.exe -m app.schema_preflight `
  --environment-file ..\.env `
  --component api
..\.venv\Scripts\python.exe -m app.schema_preflight `
  --environment-file ..\.env `
  --component worker
Pop-Location
```

使用进程中已设置的其他数据库变量时，可以显式选择变量名：

```powershell
Push-Location .\backend
..\.venv\Scripts\python.exe -m app.schema_preflight `
  --database-environment APP_TEST_RUNTIME_DATABASE_URL `
  --component worker
Pop-Location
```

成功返回退出码 `0` 和一个 `status=compatible` 的 JSON 事件；拒绝返回退出码 `2`。事件只包含闭合错误码、预期/实际 revision 和脱敏后的数据库身份，不包含密码、原始 SQL 异常、文件名或业务内容。

日常启动应使用受支持的包装器：

```powershell
.\scripts\dev-backend.ps1
.\scripts\run-worker.ps1
```

不要用自定义脚本绕过这些入口。直接启动 `app.main:app` 或 Worker CLI 仍会失败关闭，但缺少进程前预检会降低故障可观察性。

## 失败码参考

| 错误码 | 含义 | 安全处置 |
| --- | --- | --- |
| `schema_configuration_invalid` | 数据库 URL 或环境文件缺失、无效 | 检查变量名、环境文件路径和配置格式；不要在日志或工单中粘贴完整 URL |
| `schema_database_unavailable` | 无法建立连接，或查询期间连接失效 | 检查 MySQL 状态、DNS/端口、TLS、连接上限和账号可用性；数据库恢复可达前不要运行迁移 |
| `schema_version_table_missing` | 当前数据库没有 `alembic_version` 表 | 核对是否连错数据库；若确为新库或未迁移库，在批准的维护窗口执行显式迁移 |
| `schema_version_unreadable` | 已连接但无法读取版本表，包含权限拒绝或不可解释的查询错误 | 由数据库管理员核对运行账号对 `alembic_version` 的 `SELECT` 权限和表定义；不要改用 root 运行应用 |
| `schema_version_row_missing` | 版本表存在但没有 revision 行 | 将其视为迁移状态损坏或中断；保留现场和备份，调查迁移记录，不要手工补行 |
| `schema_version_rows_multiple` | 查询返回多个 revision 行 | 停止候选制品，调查多 head/异常数据来源；不要删除“多余”行来让检查通过 |
| `schema_revision_older` | 数据库 revision 低于候选代码要求 | 保持 API/Worker 停止；完成备份验证和单独授权后，运行显式前向迁移 |
| `schema_revision_newer` | 数据库 revision 高于当前制品要求 | 当前制品过旧；部署声明相同 revision 的匹配制品或执行经批准的前向修复，不要自动 downgrade |
| `schema_revision_unknown` | revision 不是受支持的四位数字值，或查询值无法解释 | 保留原值和迁移证据，检查非标准分支/手工变更；不要重写 `alembic_version` |

## 可以安全检查的信息

先保存失败事件和命令退出码，再检查：

- 候选 Git SHA、镜像 digest 和 `CURRENT_SCHEMA_REVISION`；
- 失败事件中的 `code`、`expected_revision`、`actual_revision` 与脱敏 `database_identity`；
- MySQL 服务、TLS、网络和连接上限状态；
- 使用获批只读或迁移账号执行上述 `SELECT` 后的完整行数和值；
- API/Worker 是否尚未绑定端口、发出 ready 事件或领取任务；
- 迁移作业、备份和部署日志的时间、操作者和退出码。

日志或工单不得记录完整数据库 URL、密码、Docker secret 内容、原始 SQL 参数、客户数据或文件内容。

## 显式部署与迁移顺序

以下顺序适用于已有数据库的升级。每一步必须成功并留下审计证据，才可进入下一步。

1. 记录候选 Git SHA、镜像 digest 和目标 `CURRENT_SCHEMA_REVISION`。
2. 停止所有能访问目标数据库的旧 API 和 Worker。确认没有旧进程、活动任务领取或写事务残留。
3. 按现有维护写屏障流程创建加密备份，并完成解密校验和随机隔离恢复验证。
4. 在单独批准的变更窗口运行迁移。容器部署只使用显式 operations profile：

   ```powershell
   docker compose -f .\ops\docker-compose.yml `
     --profile operations run --rm migrate
   ```

5. 使用获批数据库账号执行只读 revision 查询。结果必须恰好一行，且等于步骤 1 记录的 revision。
6. 启动与该 revision 匹配的 API 和 Worker 制品。普通 `docker compose up` 不会创建 `migrate` 容器；不兼容时 API/Worker 应拒绝启动。
7. 验证 API/Worker 的 `schema_compatibility` 成功事件、`/api/health/ready`、一次受控认证 canary，以及 Worker 的 idle/drain canary。确认没有异常重启、重复领取或业务写入。

新建空数据库没有可备份的旧状态，但仍必须先明确确认目标为空，并将迁移作为独立 operations 步骤执行。不得依赖 API/Worker 启动来隐式初始化数据库。

## 拒绝后的恢复决策

- 迁移尚未执行且代码要求更新 revision：保持新制品停止，继续运行已知兼容的旧“代码 + schema”组合，或在维护窗口完成备份和前向迁移。
- 数据库已经前移：优先部署与该 revision 匹配的制品或做经审查的前向修复。不要让旧制品连接新 schema。
- 怀疑迁移不完整或结构损坏：保持所有写进程停止，在隔离恢复环境复现并验证修复。不要在目标数据库上试错。
- 只有数据恢复能恢复兼容组合时，使用现有加密备份与随机隔离恢复 runbook。先在隔离数据库验证，再按单独授权切换；恢复不是普通代码回滚的一部分。

回滚的对象始终是一组已经证明兼容的代码和 schema。回滚绝不表示：

- 设置 bypass 参数或临时注释兼容性检查；
- 手工插入、删除或更新 `alembic_version`；
- 自动运行 downgrade；
- 恢复普通 Compose 对 `migrate` 的隐式依赖；
- 用 root/迁移账号运行 API 或 Worker；
- 启动旧进程“看看是否还能工作”。

## 验收记录

每次变更至少记录：候选 SHA/镜像 digest、目标 revision、备份与隔离恢复标识、迁移命令、开始/结束时间、退出码、revision 查询结果、API readiness、认证 canary、Worker idle/drain canary，以及最终回滚点。任何步骤失败都应停止流程并保留证据，不得通过重试写入或放宽检查把失败改成成功。
