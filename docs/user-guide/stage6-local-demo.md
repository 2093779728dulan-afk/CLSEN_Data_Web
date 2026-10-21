# 阶段 6 本地后端闭环体验

这个入口让你在阶段 7 API 和阶段 8 UI 尚未开始时，直接调用后端服务体验阶段 6 的主闭环。它不是网页，也不会启动 HTTP 服务。

## 能体验什么

一次成功运行会在两个明确选择的日期上导入两份可识别的合成业务报告，并完成：

1. 合成 CSV 导入与解析基线创建；
2. 两个日期各自物化活动草稿；
3. 主日期字段纠错和内部版本备注；
4. “源行 → 解析基线”和“基础快照 + 修改事件 → 当前草稿”全量校验；
5. 确认校验摘要并切换到 `ready_for_publish`；
6. 发布初始版本；
7. 从当前发布版本创建普通修订，进行第二次纠错、备注、校验和发布；
8. 管理员把发布指针回滚到初始发布版本；
9. 对另一个日期在主日期审核前后计算关系状态指纹，并断言完全一致。

入口使用真实的 `imports`、`parsers`、`datasets`、`review`、`validation` 和 `publications` 服务及 MySQL 仓储，不用内存替身伪造成功结果。

## 安全边界

入口在创建数据库引擎之前执行以下检查：

- 只读取 `APP_TEST_DATABASE_URL` 和 `APP_TEST_RUNTIME_DATABASE_URL`；不会回退到正式库连接变量；
- 两个 URL 的数据库名必须匹配 `clsen_data_test` 或 `clsen_data_test_<suffix>`；
- MySQL 主机只能是 `localhost`、`127.0.0.1` 或 `::1`；
- 两个 URL 必须指向同一测试库，并使用不同的迁移账号和运行账号；
- 测试库必须已经位于 Alembic `0009` 或更高版本，且阶段 6 表完整；
- 入口不执行迁移、不建库、不删库、不清空整库，也不读取正式库 URL。

如果迁移版本低于 `0009`，命令会在任何 demo 写入前退出。请先通过项目既有的数据库初始化或迁移流程升级测试库，并同步 `scripts/database-privileges.json` 中的运行账号权限；不要为了体验入口临时放宽正式库账号权限。

## 运行前提

- Windows PowerShell；
- 仓库根目录存在 `.venv\Scripts\python.exe`，且已安装 `backend/requirements.lock`；
- 本机 MySQL 测试库已经初始化并迁移到阶段 6；
- `.env` 包含指向同一个本机测试库的 `APP_TEST_DATABASE_URL` 和 `APP_TEST_RUNTIME_DATABASE_URL`；
- 选择两个不同、准备保留给本次 demo 日期对的测试日期。

首次建议选远离日常测试数据的日期，例如 `2099-06-01` 和 `2099-06-02`。日期必须在 MySQL 支持的 `1000-9999` 年范围内。

先查看将执行的动作，不连接数据库：

```powershell
.\scripts\stage6-demo.ps1 `
  -PrimaryDate '2099-06-01' `
  -IsolationDate '2099-06-02' `
  -WhatIf
```

确认日期后运行：

```powershell
.\scripts\stage6-demo.ps1 `
  -PrimaryDate '2099-06-01' `
  -IsolationDate '2099-06-02'
```

若环境文件或合成对象目录不使用默认路径，可显式指定：

```powershell
.\scripts\stage6-demo.ps1 `
  -PrimaryDate '2099-06-01' `
  -IsolationDate '2099-06-02' `
  -EnvironmentFile '.env' `
  -StorageRoot 'data\raw\stage6-demo'
```

相对路径从仓库根目录解析。默认合成对象目录为 `data\raw\stage6-demo`，位于 Git 忽略范围内。

## 如何判断成功

过程输出会依次出现 `preflight`、`import`、`draft`、`review`、`publish`、`revision` 和 `isolation` 标记。最后一行机器可读结果以 `STAGE6_DEMO_RESULT=` 开头，包含：

- 主日期和隔离日期的数据集 ID；
- 初始发布版本和普通修订版本 ID；
- 两次全量校验运行 ID；
- 回滚后的最终发布版本 ID；
- 另一日期未变化的 SHA-256 状态指纹；
- `stage7_api_available: false` 和 `stage8_ui_available: false` 边界标记。

成功状态应满足：

- 初始版本和普通修订版本都已封存为 `published`；
- 主日期不存在活动草稿；
- 当前发布指针因回滚重新指向初始版本；
- 最近三个普通发布事件依次为 `published`、`replaced`、`rolled_back`；
- 隔离日期的前后指纹相同。

可在自己的测试库客户端中进一步查看（不要把示例日期用于正式库）：

```sql
SELECT d.report_date, d.report_type, v.version_no, v.status,
       p.version_id AS current_published_version_id
FROM daily_datasets AS d
INNER JOIN dataset_versions AS v ON v.dataset_id = d.id
LEFT JOIN dataset_publications AS p ON p.dataset_id = d.id
WHERE d.report_date IN ('2099-06-01', '2099-06-02')
ORDER BY d.report_date, v.version_no;

SELECT e.event_type, e.previous_version_id, e.next_version_id, e.occurred_at
FROM publication_events AS e
INNER JOIN daily_datasets AS d ON d.id = e.dataset_id
WHERE d.report_date = '2099-06-01'
ORDER BY e.id;
```

## 重复运行与保留数据

命令默认保留 demo 数据，便于检查，也避免隐式删除测试数据。文件名、CSV 内容、应用 demo 账号和所有有幂等合同的阶段 6 操作 token 都由“测试库名 + 日期对 + 操作名”稳定派生。

使用同一个测试库和完全相同的日期对重跑时，导入会复用相同内容，解析、草稿、审核、校验、发布、修订和回滚命令会恢复首次终态结果。这样可以从中断处继续，也不会创建第二套发布历史。

以下情况会拒绝继续写入：

- 日期已包含非 demo 业务数据；
- 日期属于另一组 demo 日期对；
- 固定 demo 账号存在但元数据或角色已被改变；
- 同一稳定 token 已绑定不同命令；
- 活动指针或已存导入元数据与首次命令历史不一致。

若要体验另一轮，请选择另一对空闲测试日期。当前入口没有删除开关；需要清理时应使用专门的测试库维护流程，而不是对共享测试库执行整库清空。

## 当前没有覆盖的内容

- 阶段 7 的认证、权限 API、OpenAPI 合同和 HTTP 会话；
- 阶段 8 的数据日历、审核工作台和浏览器操作；
- 管理员已发布跨日期移动、最终切换和移动撤销；它们不是这条普通修订 smoke 路径的一部分；
- 结构错误重新解析、重复行三选一和所有负向权限分支；
- MySQL 8.0/8.4 并发屏障、死锁重试和提交响应丢失矩阵；
- 正式库升级、备份恢复或服务器部署验收；
- `return_report`；当前 fixture 是两行业务报告。

因此，这个命令证明的是“指定本机测试库上的阶段 6 后端服务主闭环可以实际串接”，不等同于阶段 7/8 用户产品已经交付，也不替代阶段 6 的完整 MySQL 集成和兼容矩阵验收。
