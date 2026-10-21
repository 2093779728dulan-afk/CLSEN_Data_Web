# 本地备份、恢复与后台任务

本页适用于当前 Windows 本地运行阶段。正式库 `clsen_data` 不会被初始化脚本之外的测试命令迁移；日常验证应使用 `clsen_data_test`。所有命令在 PowerShell 7 中从仓库根目录运行。

## 安全边界

- 每个应用写事务在首次写入前持有专用单行屏障的共享 InnoDB 锁；备份使用按数据库名隔离的 MySQL named lock 防止并行维护，再持有同一行的独占锁。备份期间写入暂停、读取继续，事务结束或连接中断会自动释放行锁。
- `clsen_backup` 对业务表只有只读权限。它仅能新增或更新 `backup_snapshots`、`backup_snapshot_objects`、`restore_verifications`，并能对受单行检查约束保护的 `maintenance_write_barrier` 取得独占锁；它不能删除这些记录，也不能改变屏障哨兵值。
- `TRIGGER` 和 `EVENT` 只授予目标数据库，用于完整导出触发器和事件，不允许修改业务行。
- dump、清单和原始内容对象均使用分块 AES-256-GCM 加密。数据库密码不进入命令行，临时 MySQL option file 在 `finally` 中清理。
- 密钥环默认位于 `%LOCALAPPDATA%\CLSEN\DataWeb\backup-keyring.json`，必须留在仓库外。Git 忽略备份目录，但 Git 忽略不等于密钥保护。
- 恢复只允许随机 `clsen_restore_<uuid>` 数据库和 `data/restore-tests` 下的随机目录；默认不清理，绝不覆盖正式数据库或原始文件根。
- P0 发布候选必须额外运行 `run-product-catalog-backup-restore.ps1`，在 Oracle MySQL 8.0/8.4 上用分离账号完成当前 head 加密备份和随机恢复；固定 v1/`0020` golden 同时验证 reader 向后兼容。
- 本地与 hosted MySQL 均通过 `run-ci-profile.ps1 -Profile mysql-compatibility` 展开同一 manifest；`test-mysql-matrix.ps1` 必须显式接收 allowlisted suite 和已验证的 Python 3.14，不再隐式运行 offline suite 或接受任意 pytest 路径。

## 首次准备

迁移到阶段 10A 后，先同步测试库运行账号与备份账号的最小权限。该脚本只接受 `clsen_data_test*`，不运行迁移，也不访问正式库：

```powershell
.\scripts\sync-test-runtime-grants.ps1
```

凭据提示中的 `User` 填具有 `GRANT` 权限的 MySQL 管理员，通常是 `root`。脚本会精确撤销并重建目标测试库权限，同时保持其他数据库权限不变。

首次创建仓库外密钥环：

```powershell
.\scripts\backup.ps1 -Action InitializeKeyring
```

立即把密钥环的独立恢复副本保存到另一故障域，例如企业密码库或加密离线介质。不要只保存在当前硬盘。

## 创建备份

先在测试库演练：

```powershell
.\scripts\backup.ps1 `
  -UseTestDatabase `
  -StorageRoot .\data\raw\stage6-demo `
  -Destination .\data\backups
```

`-StorageRoot` 必须与被备份数据库当前运行时使用的原始文件根目录一致。阶段 9
本地体验数据使用 `data\raw\stage6-demo`；若数据库引用的内容对象在所选目录中缺失或
哈希不一致，备份会失败关闭，不能把不完整快照标记为成功。

正式库日常备份：

```powershell
.\scripts\backup.ps1 -Destination .\data\backups
```

流程会等待活动导入租约结束，冻结审计清单，在写屏障内运行一致性 `mysqldump`，随后释放屏障、加密文件并逐项解密校验。只有全部通过，快照状态才变为 `succeeded`。

默认保留最近 30 份成功备份。系统在至少一份备份完成真实恢复演练前不会自动清理历史成功备份。备份审计记录仍保留在数据库中。

## 隔离恢复演练

恢复测试库备份：

```powershell
.\scripts\restore-verify.ps1 `
  -BackupRoot .\data\backups `
  -TemporaryRoot .\data\restore-tests `
  -UseTestDatabase
```

脚本要求 MySQL 管理员凭据，用于创建随机恢复数据库。它会验证：

- 所有密文大小、SHA-256 和 AES-GCM 标签；
- 清单、数据库备份 ID 和 `key_id`；
- Alembic 版本、原始文件数、发布指针数、版本数和审计数；
- 当前站点配置指针；
- 每个恢复文件的存储键、大小和 SHA-256。

成功后数据库和目录默认保留，便于人工检查。确认不再需要时，可以重新执行并显式加 `-Cleanup`；清理前脚本会再次验证数据库名和目录边界。

## 密钥轮换

```powershell
.\scripts\backup.ps1 -Action RotateKey
```

轮换只改变后续备份使用的活动 `key_id`。只要历史备份仍存在，旧密钥必须保留。轮换后必须使用密钥环的独立副本完成一次恢复演练，确认本机密钥文件丢失时仍能恢复。

## 后台任务

### Schema 预检与受支持启动

本地 API 和 worker 都要求目标数据库包含且只包含一个与当前代码相同的 Alembic revision。可以在启动前手工执行只读预检：

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

预检成功返回 `0`；配置或兼容性拒绝返回 `2`，且不会运行迁移。日常 API 启动使用：

```powershell
.\scripts\dev-backend.ps1
```

脚本会在 Uvicorn 和端口绑定前预检，FastAPI lifespan 仍会在进程内再次防守。Worker 包装器同样在 ready 文本前预检，Worker CLI 在构造存储、runner 或领取任务前再检查一次。

若出现 `schema_revision_older`、`schema_revision_newer` 或其他 schema 拒绝，保持 API/Worker 停止；不要手工编辑 `alembic_version`、增加 bypass 或让启动脚本自动迁移。错误码、显式迁移顺序和兼容回滚见 [Schema 兼容性 runbook](./schema-compatibility.md)。

本地长期运行：

```powershell
.\scripts\run-worker.ps1
```

测试库排空当前可执行任务后退出：

```powershell
.\scripts\run-worker.ps1 -UseTestDatabase -Drain
```

worker 通过行锁独占领取任务，崩溃后的陈旧 `processing` 任务会被重新领取。失败按指数延迟重试，达到上限后进入 `failed`，不会无限快速重试。当前看板直接查询发布指针，因此消费操作是校验来源并确认失效事件；后续增加物化汇总时沿用相同去重键。

Worker 心跳、四类队列指标、安全故障码、30 天保留和事故检查见 [Worker 可观测性 runbook](./worker-observability.md)。其中“在线”只证明数据库心跳新鲜，不代表所有消费者健康；维护写屏障与心跳状态必须分别判断。

Stage 2 部署必须使用同一候选 SHA：先停止旧 API/Worker 并备份，再显式迁移到 `0023`、同步表级权限、确认 exact head，最后部署匹配的 API/Worker 并验证真实递增心跳和四类队列。应用回滚时先停止新 Worker，等待既有业务租约进入原生恢复条件，再回到 schema anchor `3750ad3` 或其他明确兼容 `0023` 的提交；紧急回滚不删除观测表，也不手工改写业务队列行。

## 管理员状态页

管理员控制台的“备份与任务”显示最近 20 次备份、恢复演练、outbox 积压和维护写屏障状态。页面不包含密钥、数据库密码、原始订单号或文件内容。

`/api/health/ready` 会连续观测维护锁。默认持续 120 秒仍未释放时返回 `503 degraded`；普通短写事务和正常备份不会立即被判故障。阈值可通过 `APP_MAINTENANCE_LOCK_WARNING_SECONDS` 调整。

## 故障排查

- API/worker 返回 schema 兼容性错误：保存闭合错误码、预期/实际 revision 与脱敏数据库身份，按 [Schema 兼容性 runbook](./schema-compatibility.md) 排查；不要在工单中粘贴完整数据库 URL 或密码。
- `mysqldump ... Access denied`：重新运行 `sync-test-runtime-grants.ps1`，确认清单版本为 5；不要改用迁移账号作为日常备份账号。
- 快照停在 `running` 或 `sealed`：备份进程可能被中止。先确认管理员页面写屏障已释放，再保留记录排查；不要手工伪造 `succeeded`。
- `failed` 且有 `failure_code`：修复原因后新建一份备份。失败证据不应通过应用账号删除。
- 恢复失败：默认保留随机数据库和目录。先检查报告，再决定是否显式清理；绝不把目标改为 `clsen_data`。
- worker 有 `failed`：查看管理员状态和服务端日志，修复不支持的 topic 或数据来源后再由受控运维操作重新排队。

商品主档发布、整套产品入口回滚、性能与只读 canary 的操作顺序见[商品主档发布 runbook](./product-catalog-rollout.md)；Worker 状态、部署和回滚见 [Worker 可观测性 runbook](./worker-observability.md)。
