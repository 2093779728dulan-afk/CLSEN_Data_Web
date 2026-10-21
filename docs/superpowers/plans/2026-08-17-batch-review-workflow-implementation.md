# 批量审核工作流实施计划

> **执行说明：** 按任务顺序测试驱动实施。第一版只交付本机可体验的“服务端权威预检 + 浏览器最多三项并行推进”；明确不包含 Worker、消息队列、常驻任务调度、任务监控、生产部署和生产数据库迁移。

**目标：** 用户在多文件导入后只核对一次日期与报表类型，即可把全部安全项目并行推进到 `ready_for_publish`；冲突、识别不确定、校验警告或阻断继续进入人工审核，且任何路径都不会自动发布。

**架构：** 新增持久化的批量任务与项目状态，由服务端负责资格判断、状态重检、幂等、单项租约和恢复。单项推进复用 `WorkbenchImportOrchestrator` 完成确认解析与草稿物化，再复用 `ValidationService` 和 `ReviewService.mark_ready` 完成完整校验与待发布门禁。前端只负责最多三项的限流领取，不是权威任务队列。

**技术栈：** Python 3.14、FastAPI、SQLAlchemy Core、Alembic、MySQL 8.0/8.4、Pydantic、React 19、TypeScript 5.9、Vitest、Playwright、pnpm。

**批准规格：** `docs/superpowers/specs/2026-08-17-batch-review-workflow-design.md`

## 实施边界与安全门禁

- 保留现有单文件与逐份审核流程，批量入口失败时仍可逐项处理。
- 不自动发布、不切换 `dataset_publications` 指针、不覆盖已有草稿或发布版本。
- 不自动确认警告，不自动填写审核备注；出现任意警告或阻断即转 `manual_review`。
- 每份文件独立提交；一个项目失败不回滚或停止其他项目。
- 只复用现有领域服务，不直接更新解析基线、草稿内容、审核状态或发布指针。
- 实施前先运行 Alembic 单头检查。当前实际头为 `0020`，因此本计划暂用 `0021`；若执行时已有新迁移，先顺延编号和 `down_revision`，不得创建分叉。
- 数据库相关集成测试只允许连接已确认可丢弃的测试数据库。不得对主数据库执行迁移、清空、降级或测试夹具写入。
- 可以更新权限清单作为代码契约，但本计划不执行生产授权同步，也不包含部署操作。
- 保留当前脏工作区，不清理、不还原、不暂存、不提交用户已有修改。

## 任务 0：冻结基线并确认复用契约

**文件：**

- 阅读：`backend/app/workbench/import_orchestration.py`
- 阅读：`backend/app/validation/service.py`
- 阅读：`backend/app/validation/types.py`
- 阅读：`backend/app/review/service.py`
- 阅读：`backend/app/review/types.py`
- 阅读：`backend/app/api/imports.py`
- 阅读：`backend/app/api/validation_runs.py`
- 阅读：`backend/app/api/review.py`
- 阅读：`backend/alembic/versions/`
- 阅读：`backend/tests/contracts/test_migration_contract.py`

- [x] **步骤 1：记录工作区和迁移头**

运行：

```powershell
git status --short
Get-ChildItem backend/alembic/versions -File | Sort-Object Name | Select-Object -ExpandProperty Name
.\.venv\Scripts\python.exe -m alembic -c backend/alembic.ini heads
```

预期：只读检查；不改变工作区。若迁移头不是 `0020`，先调整任务 1 的文件名、修订号和契约测试。

- [x] **步骤 2：写下禁止绕过的领域边界**

实施代码必须通过以下现有入口推进：

- `WorkbenchImportOrchestrator.run(OrchestrateImportCommand)`；
- `ValidationService.run_validation(RunValidationCommand)`；
- `ReviewService.mark_ready(MarkReadyCommand)`。

批量模块只保存任务编排元数据，不自行复制解析、物化、校验或待发布 SQL。

- [x] **步骤 3：运行现有聚焦回归作为基线**

```powershell
.\.venv\Scripts\python.exe -m pytest backend/tests/unit/workbench backend/tests/unit/validation backend/tests/unit/review -q
Set-Location frontend
pnpm test --run src/features/import-review/ImportReviewFlow.test.tsx
Set-Location ..
```

预期：PASS；若存在与本功能无关的既有失败，记录原始失败，不在本任务中顺手修改。

## 任务 1：批量任务数据库契约

**文件：**

- 创建：`backend/alembic/versions/0021_batch_review_workflow.py`（执行时按实际迁移头顺延）
- 修改：`backend/tests/contracts/test_migration_contract.py`
- 修改：`backend/tests/integration/test_migrations.py`
- 修改：`backend/tests/integration/test_database_constraints.py`
- 修改：`scripts/database-privileges.json`

**接口与约束：**

- `batch_review_runs` 保存站点、创建人、状态、修订号、确认人、确认时间、确认声明版本和时间戳。
- `batch_review_items` 保存服务端识别快照、目标键、选择状态、阶段、原因、领域对象 ID、固定操作 UUID/摘要、尝试次数、可重试标记和时间戳。
- 任务状态：`preview | confirmed | running | paused | completed | completed_with_exceptions`。
- 项目状态：`eligible | skipped | queued | parsing | materializing | validating | ready_for_publish | manual_review | failed`。
- 唯一约束至少覆盖 `(run_id, batch_id)`；目标键建立任务内查询索引，但不以数据库唯一索引替代确认时的服务端目标冲突检查。

- [x] **步骤 1：先写迁移契约失败测试**

扩展 `EXPECTED_MIGRATIONS`，并断言：

- 新修订线性承接当前唯一头；
- 两张表的外键、枚举/检查约束和唯一约束存在；
- 任务 `revision >= 0`，项目 `attempt_count >= 0`；
- 操作令牌为 16 字节 UUID，摘要为 32 字节；
- 删除任务时只级联其项目，不级联删除原始批次、草稿、校验或用户。

- [x] **步骤 2：实现升级与保守降级**

升级只创建批量编排表、索引和外键；不回填、不触碰现有业务数据。降级在存在批量任务行时拒绝破坏性删除，空表时按外键逆序移除。

- [x] **步骤 3：补充数据库约束测试**

覆盖重复批次、非法状态、负修订号、跨站点外键关系、无效操作摘要及删除边界。

- [x] **步骤 4：更新权限清单但不执行授权同步**

运行时账户仅获得两张新表所需的 `SELECT/INSERT/UPDATE`；不得获得 `DELETE` 或 DDL。备份账户按项目现有完整备份规则纳入新表。本任务只修改并测试清单，不执行授权命令。

- [x] **步骤 5：运行非数据库契约测试**

```powershell
.\.venv\Scripts\python.exe -m pytest backend/tests/contracts/test_migration_contract.py backend/tests/contracts/test_database_bootstrap_script.py -q
```

预期：PASS；不运行迁移。

- [x] **步骤 6：仅在确认可丢弃数据库后运行迁移重放**

> 已于 2026-08-18 在独立可丢弃数据库 `clsen_data_test_batch_review`
> 验收：迁移重放 29 个用例通过，数据库约束 70 个用例通过；未连接主数据库。

```powershell
.\.venv\Scripts\python.exe -m pytest backend/tests/integration/test_migrations.py backend/tests/integration/test_database_constraints.py --require-mysql -q
```

预期：PASS。未确认测试数据库可丢弃时标记为未运行，不得改连主数据库。

## 任务 2：领域类型、稳定原因码和资格规则

**文件：**

- 创建：`backend/app/batch_review/__init__.py`
- 创建：`backend/app/batch_review/types.py`
- 创建：`backend/app/batch_review/eligibility.py`
- 创建：`backend/tests/unit/batch_review/__init__.py`
- 创建：`backend/tests/unit/batch_review/test_types.py`
- 创建：`backend/tests/unit/batch_review/test_eligibility.py`

**接口：**

- `BatchReviewReasonCode` 使用稳定机器码。
- `BatchReviewCandidate` 表示服务端读取的原始批次事实。
- `BatchReviewTargetState` 表示目标草稿/发布占用状态。
- `evaluate_candidate(candidate, target, seen_targets) -> EligibilityDecision` 是纯函数。
- 命令类型至少包括 `CreatePreflightCommand`、`ConfirmBatchReviewCommand`、`AdvanceBatchReviewItemCommand`、`ChangeBatchReviewRunStateCommand` 和 `RetryBatchReviewItemCommand`。

- [x] **步骤 1：写全部原因码的失败测试**

至少覆盖：

`recognition_uncertain`、`source_unavailable`、`batch_state_conflict`、`duplicate_target_in_run`、`active_draft_exists`、`publication_exists`、`already_materialized`、`permission_denied`。

断言每个决定同时具有机器码、安全中文说明、是否合格和人工处理 URL；中文说明不得包含 SQL、堆栈或原始单元格内容。

- [x] **步骤 2：实现不可变类型和命令摘要**

命令验证正整数 ID、UUID v4 幂等键、非空确认声明版本、去重后的批次/项目列表。摘要使用排序后的规范 JSON 和 SHA-256，不包含可变时间戳。

- [x] **步骤 3：实现严格资格纯函数**

全部条件同时满足才返回 `eligible`。同一任务目标重复时，按服务端稳定排序保留第一项可选，其余项目进入 `manual_review`；不得依赖浏览器提交顺序。

- [x] **步骤 4：写状态机测试**

覆盖合法转移、非法回退、终态不可重开、暂停不改变活动项、失败重试只回到允许恢复的服务器阶段，以及无项目时任务汇总规则。

- [x] **步骤 5：运行领域单元测试**

```powershell
.\.venv\Scripts\python.exe -m pytest backend/tests/unit/batch_review/test_types.py backend/tests/unit/batch_review/test_eligibility.py -q
```

预期：PASS。

## 任务 3：Repository——权威预检、并发修订和单项租约

**文件：**

- 创建：`backend/app/batch_review/repository.py`
- 创建：`backend/tests/unit/batch_review/test_repository.py`
- 创建：`backend/tests/integration/test_batch_review_repository.py`

**接口：**

- `load_candidates(site_id, batch_ids)` 一次读取原始文件、导入批次、检测、解析、物化和目标指针事实。
- `create_preflight(command, decisions)` 原子创建任务和项目快照。
- `get_run(run_id, site_id)` 返回恢复页面所需的完整聚合。
- `confirm_run(...)` 锁定任务并按预期修订号提交选择结果。
- `claim_item(...)` 为一个项目建立唯一活动推进租约。
- `record_item_stage(...)`、`finish_item(...)` 和 `recompute_run_status(...)` 使用短事务和乐观修订。
- `append_audit_event(...)` 在同一事务写入现有 `audit_events`，只保存任务/项目标识、状态、稳定原因码和已清理元数据。

- [x] **步骤 1：先写 SQL 形状与权限边界测试**

断言候选查询必须按 `site_id` 限制，返回数量必须与请求 ID 完全一致；跨站点、缺失 ID 和重复 ID不得静默忽略。任务读取也必须同时限制站点和角色。

- [x] **步骤 2：实现预检读取和创建事务**

文件名、日期、类型、编码、完整性状态和目标占用均由服务端读取。创建任务时保存展示快照与原因码，但不确认、不解析、不生成草稿。

- [x] **步骤 3：实现确认锁和修订号**

使用任务行 `SELECT ... FOR UPDATE` 或等价条件更新；`expected_revision` 不匹配返回明确冲突。确认事务重新读取选中项目的权威事实，变化项目转 `manual_review`，仍合格项目转 `queued`。

- [x] **步骤 4：实现单项领取与重复推进保护**

同一项目同时只有一个活动命令摘要。相同 UUID 与相同摘要恢复原结果；相同 UUID 不同摘要冲突；不同 UUID 在已有活动租约时不得并行推进。

- [x] **步骤 5：实现暂停、恢复与汇总**

暂停后 `claim_item` 不再领取新项，已领取项目可结束。无 `queued/running` 项后按是否存在异常计算 `completed` 或 `completed_with_exceptions`。

- [x] **步骤 6：实现批量编排审计**

使用现有 `audit_events` 记录任务创建、预检结论、统一确认、暂停、恢复、重试和任务完成。解析、校验和待发布的细粒度证据继续由现有领域服务记录。审计详情不得包含原文件正文、单元格值、未清理异常或用户可控 SQL 文本。

- [x] **步骤 7：运行 Repository 测试**

```powershell
.\.venv\Scripts\python.exe -m pytest backend/tests/unit/batch_review/test_repository.py -q
```

仅在可丢弃 MySQL：

```powershell
.\.venv\Scripts\python.exe -m pytest backend/tests/integration/test_batch_review_repository.py --require-mysql -q
```

预期：PASS；同一项目的并发领取最多一个成功。

## 任务 4：Service——预检、确认、暂停、恢复和重试

**文件：**

- 创建：`backend/app/batch_review/service.py`
- 修改：`backend/app/batch_review/types.py`
- 创建：`backend/tests/unit/batch_review/test_service.py`

**接口：**

- `BatchReviewService.create_preflight(command) -> BatchReviewRunView`
- `BatchReviewService.get_run(run_id, actor) -> BatchReviewRunView`
- `BatchReviewService.confirm(command) -> BatchReviewRunView`
- `BatchReviewService.pause(command) -> BatchReviewRunView`
- `BatchReviewService.resume(command) -> BatchReviewRunView`
- `BatchReviewService.retry_item(command) -> BatchReviewRunView`

- [x] **步骤 1：写创建和确认失败测试**

覆盖空数组、重复批次 ID、缺失批次、跨站点、角色不足、无选中项目、未接受声明、声明版本不匹配、过期任务修订和确认时目标状态变化。

- [x] **步骤 2：实现服务端权威预检**

按批次 ID 稳定排序加载事实，调用资格纯函数，持久化任务。响应包含汇总、全部项目、允许操作和当前修订；客户端显示值从响应读取。

- [x] **步骤 3：实现确认重检**

确认请求只信任项目 ID 和声明接受状态，不信任客户端日期、类型或编码。重检后把合格选择转 `queued`，取消选择转 `skipped`，失效选择转 `manual_review`；同一事务记录确认审计，任务最终进入 `running`，不得停留在无执行者领取的 `confirmed`。`confirmed` 只作为服务端恢复尚未完成状态切换时的受控中间态。

- [x] **步骤 4：实现暂停/恢复/重试状态门禁**

只有 `running` 可暂停，只有 `paused` 可恢复。仅服务器标记 `retry_allowed=true` 的 `failed` 项可重试；业务冲突、校验异常和结果不确定不得直接换 UUID 重放。

- [x] **步骤 5：运行服务单元测试**

```powershell
.\.venv\Scripts\python.exe -m pytest backend/tests/unit/batch_review/test_service.py -q
```

预期：PASS。

## 任务 5：单项推进——复用导入、校验与待发布门禁

**文件：**

- 修改：`backend/app/batch_review/service.py`
- 小幅修改：`backend/app/workbench/import_orchestration.py`
- 创建：`backend/tests/unit/batch_review/test_advance.py`
- 创建：`backend/tests/integration/test_batch_review_workflow.py`

**接口：**

- `BatchReviewService.advance_item(command) -> BatchReviewItemView`
- 必要时从现有编排器提取不改变行为的查询/结果适配接口，使批量服务能读取已生成的 `dataset_id`、`version_id` 和恢复阶段。
- 子操作令牌由项目固定操作 UUID 通过 `uuid5` 派生：`import`、`validation`、`mark-ready`；重试不得生成新的语义身份。

- [x] **步骤 1：写完整成功路径失败测试**

一份合格文件应依次记录：`parsing -> materializing -> validating -> ready_for_publish`。断言生成一个解析基线、一个活动草稿、一个完整校验运行和一个待发布审核事件；没有发布事件和发布指针切换。

- [x] **步骤 2：写导入阶段异常矩阵**

覆盖源文件不可用、识别状态变化、已有物化、目标占用、解析失败、物化竞争、提交结果不确定。确定业务冲突转 `manual_review`；短暂基础设施错误才转可重试 `failed`。

- [x] **步骤 3：复用 `WorkbenchImportOrchestrator` 完成草稿创建**

用确认清单冻结的日期、类型和编码构造 `OrchestrateImportCommand`。如果编排器返回 `confirmation_required` 或 `conflict_required`，转换为人工处理；`workspace_ready` 后保存其领域 ID。不得以 `strategy="replace"` 覆盖确认后出现的已有目标。

- [x] **步骤 4：写校验门禁测试**

覆盖校验错误、阻断、一个警告、数据修订变化、审核修订变化、规则集变化、活动草稿变化和发布指针竞争。任一情况都保留草稿并转人工，不自动确认警告。

- [x] **步骤 5：调用现有完整校验**

从当前草稿头读取 `dataset_id/version_id/data_revision/ruleset_version`，调用 `ValidationService.run_validation`。只接受 `status=succeeded`、`result=passed`、`warning_count=0` 且结果对应当前数据修订。

- [x] **步骤 6：调用现有 `mark_ready`**

用校验回执和重新读取的 `DraftHeadExpectation` 构造 `MarkReadyCommand`。理由明确记录批量任务与项目 ID。若版本头或发布状态在校验后变化，转人工处理，不重建或覆盖。

- [x] **步骤 7：写幂等、恢复和独立失败测试**

相同推进 UUID 重试返回相同领域结果；提交确认丢失时先读取服务器状态。至少四项中一项失败时，其他三项仍可完成；失败项目不得删除已有基线或草稿。

- [x] **步骤 8：运行推进测试**

```powershell
.\.venv\Scripts\python.exe -m pytest backend/tests/unit/batch_review/test_advance.py -q
```

仅在可丢弃 MySQL：

```powershell
.\.venv\Scripts\python.exe -m pytest backend/tests/integration/test_batch_review_workflow.py --require-mysql -q
```

预期：PASS；测试同时断言零自动发布。

## 任务 6：FastAPI、权限、错误语义与 OpenAPI

**文件：**

- 创建：`backend/app/api/batch_reviews.py`
- 修改：`backend/app/main.py`
- 修改：`backend/tests/unit/test_openapi_contract.py`
- 创建：`backend/tests/unit/test_batch_reviews_api.py`
- 创建：`backend/tests/integration/test_batch_reviews_api.py`
- 生成：`frontend/src/api/generated.ts`（只能通过生成脚本）

**路由：**

- `POST /api/imports/batch-reviews/preflight`
- `GET /api/imports/batch-reviews/{run_id}`
- `POST /api/imports/batch-reviews/{run_id}/confirm`
- `POST /api/imports/batch-reviews/{run_id}/items/{item_id}/advance`
- `POST /api/imports/batch-reviews/{run_id}/pause`
- `POST /api/imports/batch-reviews/{run_id}/resume`
- `POST /api/imports/batch-reviews/{run_id}/items/{item_id}/retry`

- [x] **步骤 1：写 OpenAPI 和角色失败测试**

所有路由只允许 `admin | data_manager`。GET 要求认证；所有 POST 同时要求 CSRF 和 `Idempotency-Key`。请求 ID 有正整数约束，批次列表有上下限，响应模型不得暴露异常堆栈或未发布单元格值。

- [x] **步骤 2：实现 Pydantic 请求/响应模型**

响应统一返回任务修订、状态、汇总、项目列表、`allowed_actions`、`retry_allowed` 和人工处理 URL。稳定业务异常映射为 409/422；忙碌和结果不确定使用可识别错误码。

- [x] **步骤 3：注册路由并实现错误映射**

复用 `require_write_roles("admin", "data_manager")` 和数据库引擎依赖。把领域错误映射为稳定 API envelope；不得用通用 500 掩盖可恢复状态。

- [x] **步骤 4：生成前端客户端契约**

```powershell
pwsh .\scripts\generate-api-client.ps1
```

预期：`frontend/src/api/generated.ts` 包含七个操作及最新 OpenAPI 摘要，不手工修改生成文件。

- [x] **步骤 5：运行 API 测试与静态检查**

```powershell
.\.venv\Scripts\python.exe -m pytest backend/tests/unit/test_batch_reviews_api.py backend/tests/unit/test_openapi_contract.py -q
.\.venv\Scripts\python.exe -m ruff check backend/app/batch_review backend/app/api/batch_reviews.py backend/tests/unit/batch_review backend/tests/unit/test_batch_reviews_api.py
.\.venv\Scripts\python.exe -m mypy backend/app/batch_review backend/app/api/batch_reviews.py
```

仅在可丢弃 MySQL：

```powershell
.\.venv\Scripts\python.exe -m pytest backend/tests/integration/test_batch_reviews_api.py --require-mysql -q
```

预期：PASS。

## 任务 7：前端类型、API 与三并发执行器

**文件：**

- 创建：`frontend/src/features/batch-review/batchReviewTypes.ts`
- 创建：`frontend/src/features/batch-review/batchReviewApi.ts`
- 创建：`frontend/src/features/batch-review/batchReviewApi.test.ts`
- 创建：`frontend/src/features/batch-review/batchReviewExecutor.ts`
- 创建：`frontend/src/features/batch-review/batchReviewExecutor.test.ts`

**接口：**

- API 层只使用生成的请求/响应类型和现有 `requestApi/writeApi`。
- `runBatchReviewExecutor(snapshot, advance, reload, options)` 最多同时推进三项。
- 执行器只消费服务端 `queued` 项，不把 React 内存状态当成完成依据。

- [x] **步骤 1：写 API 序列化与错误恢复测试**

覆盖批次 ID 去重、确认项目列表、任务修订号、幂等键、暂停/恢复/重试，以及 `outcome_unknown` 必须先 GET 恢复而非更换 UUID 重放。

- [x] **步骤 2：实现轻量 API 适配层**

每个写命令生成并保留一个 UUID。页面生命周期内重试相同语义时复用；刷新后从服务端返回的固定操作身份恢复。

- [x] **步骤 3：写并发上限测试**

使用可控 Promise 断言：3 项正在处理时第 4 项不会启动；任一完成后只补一个；一项失败不取消其他项；暂停后活动项可结束但不领取新项。

- [x] **步骤 4：实现无权威状态的执行器**

每次单项响应后重新合并服务端快照；遇到 409 修订冲突或结果不确定时调用 GET。页面卸载后停止领取新项，不承诺浏览器关闭后继续处理。

- [x] **步骤 5：运行前端执行器测试**

```powershell
Set-Location frontend
pnpm test --run src/features/batch-review/batchReviewApi.test.ts src/features/batch-review/batchReviewExecutor.test.ts
pnpm typecheck
Set-Location ..
```

预期：PASS，观测到的最大并发数严格为 3。

## 任务 8：独立批量审核页面

**文件：**

- 创建：`frontend/src/features/batch-review/BatchReviewPage.tsx`
- 创建：`frontend/src/features/batch-review/BatchReviewPage.css`
- 创建：`frontend/src/features/batch-review/BatchReviewPage.test.tsx`
- 创建：`frontend/src/features/batch-review/BatchReviewSummary.tsx`
- 创建：`frontend/src/features/batch-review/BatchReviewPreflightTable.tsx`
- 创建：`frontend/src/features/batch-review/BatchReviewProgressTable.tsx`
- 创建：`frontend/src/features/batch-review/BatchReviewCompletionActions.tsx`
- 创建：对应组件测试文件

**界面要求：**

- 路由：`/review/batch/:runId`。
- 继续使用现有蓝白视觉系统和 `AppShell`。
- 桌面为紧凑表格；窄屏表格内部横向滚动，不把项目压成难读卡片墙。
- 按钮、复选框和链接至少 44px 触控高度，状态不仅依赖颜色表达。

- [x] **步骤 1：写预检清单失败测试**

断言展示文件名、批次号、日期、报表类型、编码、识别状态、目标状态和预计动作。合格项默认选中，不合格项禁用并显示原因；重复目标不可选。

- [x] **步骤 2：实现摘要和预检表**

摘要显示总数、可执行、人工处理、失败和待发布数量。选择状态只影响确认请求，不修改服务端识别快照。

- [x] **步骤 3：实现确认声明门禁**

未勾选“我已核对所选文件的报告日期和报表类型”时禁止开始。按钮显示选中数量；确认请求携带任务修订号和声明版本。

- [x] **步骤 4：写进度和结果测试**

覆盖各阶段中文文案、服务端原因、暂停、恢复、可重试失败、人工处理链接、全部待发布入口和 `completed_with_exceptions`。

- [x] **步骤 5：实现进度表与完成操作**

“查看全部待发布草稿”只导航至按任务筛选的版本视图，不发布。“处理异常”进入对应 `/review/:reportDate?report_type=...`；只有 `retry_allowed` 显示重试。

- [x] **步骤 6：实现加载、刷新与失效状态**

页面首次和刷新都先 GET 任务。401 留给应用登录恢复；403 显示无权限；404 显示任务不存在；普通网络失败提供原地重试且不伪造项目完成。

- [x] **步骤 7：运行页面测试**

```powershell
Set-Location frontend
pnpm test --run src/features/batch-review
pnpm lint
pnpm typecheck
Set-Location ..
```

预期：PASS。

## 任务 9：从多文件导入队列接入并注册路由

**文件：**

- 修改：`frontend/src/features/import-review/ImportReviewFlow.tsx`
- 修改：`frontend/src/features/import-review/ImportReviewFlow.test.tsx`
- 修改：`frontend/src/features/import-review/workflowTypes.ts`
- 修改：`frontend/src/app/App.tsx`
- 修改：`frontend/src/app/App.test.tsx`

**接口：**

- 导入队列存在至少两个可提交服务端批次时显示“批量审核”。
- 重复上传返回的已有未完成批次可以预检，但提交的批次 ID 必须去重。
- 创建预检成功后导航 `/review/batch/{runId}`。

- [x] **步骤 1：写入口可见性测试**

覆盖 0/1/2 个批次、重复批次 ID、尚未保存成功的本地文件、viewer 权限和现有逐项按钮仍可用。

- [x] **步骤 2：提取批量入口，控制 `ImportReviewFlow` 体量**

新增小型入口组件或 hook；`ImportReviewFlow` 只提供队列中的服务端批次 ID 和导航回调，不承担执行器逻辑。

- [x] **步骤 3：注册独立路由**

在已认证 `AppShell` 内添加 `/review/batch/:runId`，仅写角色可进入。确保它在 `/review/:reportDate` 动态路由之前精确匹配，避免把 `batch` 当日期。

- [x] **步骤 4：验证旧流程不回归**

```powershell
Set-Location frontend
pnpm test --run src/features/import-review/ImportReviewFlow.test.tsx src/app/App.test.tsx
pnpm typecheck
Set-Location ..
```

预期：批量入口和原逐份审核入口同时可用。

## 任务 10：刷新恢复、暂停、异常跳转与任务筛选

**文件：**

- 修改：`frontend/src/features/batch-review/BatchReviewPage.tsx`
- 修改：`frontend/src/features/batch-review/batchReviewExecutor.ts`
- 修改：`backend/app/api/versions.py`
- 修改：`backend/tests/unit/test_versions_api.py`
- 创建：`backend/tests/integration/test_batch_review_version_filter.py`
- 生成：`frontend/src/api/generated.ts`（只能通过生成脚本）
- 修改：`frontend/src/features/versions/VersionHistory.tsx`
- 修改：`frontend/src/features/versions/VersionHistory.test.tsx`
- 创建：`frontend/src/features/batch-review/BatchReviewRecovery.test.tsx`

- [x] **步骤 1：写刷新恢复测试**

在 `running`、`paused`、单项 `validating`、`failed` 和 `outcome_unknown` 状态刷新页面，断言只依据 GET 响应恢复；不会重复确认、重新生成草稿或超过三并发。

- [x] **步骤 2：实现暂停和恢复交互**

暂停成功后停止领取；活动请求完成后刷新任务。恢复使用最新修订号，再由执行器读取 `queued` 项。

- [x] **步骤 3：实现异常项目深链**

人工处理链接包含报告日期和报表类型；如果已有版本 ID，也作为可验证定位参数传递。目标页仍按服务端日历/活动草稿事实解析，不信任 URL 直接修改数据。

- [x] **步骤 4：实现待发布任务筛选**

扩展 `GET /api/versions` 的可选 `batch_review_run_id`：服务端按当前站点连接批量项目与版本，只返回该任务产生且当前仍为 `ready_for_publish` 的版本；跨站点任务返回 404/403，不能泄露存在性。“查看全部待发布草稿”携带该参数，版本历史页读取并展示清晰的任务筛选标签。重新生成 OpenAPI 客户端，不在前端假装过滤。

- [x] **步骤 5：写服务端任务筛选测试并重新生成客户端**

覆盖当前站点、跨站点、任务不存在、项目没有版本、版本后来发布/退回草稿，以及没有参数时保持原列表语义。

```powershell
.\.venv\Scripts\python.exe -m pytest backend/tests/unit/test_versions_api.py -q
pwsh .\scripts\generate-api-client.ps1
```

仅在可丢弃 MySQL：

```powershell
.\.venv\Scripts\python.exe -m pytest backend/tests/integration/test_batch_review_version_filter.py --require-mysql -q
```

预期：PASS。

- [x] **步骤 6：运行恢复测试**

```powershell
Set-Location frontend
pnpm test --run src/features/batch-review/BatchReviewRecovery.test.tsx src/features/versions/VersionHistory.test.tsx
Set-Location ..
```

预期：PASS。

## 任务 11：端到端、效率和零自动发布验收

**文件：**

- 创建：`frontend/tests/e2e/batch-review.spec.ts`
- 创建：`backend/tests/integration/test_batch_review_efficiency.py`
- 修改：`docs/user-guide/stage9-local-demo.md`

- [x] **步骤 1：准备 30 份和 100 份可丢弃 fixture**

fixture 分布多个日期与两类报表，包含纯成功组，以及识别不确定、目标重复、已有草稿、已有发布、校验警告、解析失败和短暂可重试错误。不得复制真实敏感文件内容。

- [x] **步骤 2：写浏览器主流程**

覆盖多文件导入、创建预检、取消一项、接受确认、三并发执行、暂停、恢复、刷新、单项失败继续、进入异常页面及查看待发布结果。

- [x] **步骤 3：写 30 份效率验收**

在同一受控本机测试环境比较批量流程与现有逐份串行操作。批量必要人工动作固定为核对清单、勾选声明和开始；总耗时至少缩短 50%，最大并发不超过三。

- [x] **步骤 4：写 100 份稳定性验收**

断言零重复草稿、零重复解析结果、零连接池耗尽、任务汇总准确、单项失败互不影响，并且刷新后继续从服务器事实恢复。

- [x] **步骤 5：建立零自动发布硬断言**

全流程结束后直接查询测试数据库：`dataset_publications`、发布事件和发布 outbox 均无新增；成功版本只处于 `ready_for_publish`。

- [x] **步骤 6：更新本机体验说明**

说明批量入口、确认声明、暂停/恢复、异常处理和“待发布不是已发布”。明确浏览器关闭后不会继续领取新项目，且第一版没有后台 Worker。

- [x] **步骤 7：运行后端非 MySQL 完整门禁**

```powershell
.\.venv\Scripts\python.exe -m pytest backend/tests -m "not mysql and not deepseek_live" -q
.\.venv\Scripts\python.exe -m ruff check backend
.\.venv\Scripts\python.exe -m mypy backend/app
```

预期：PASS。

- [x] **步骤 8：仅在已确认可丢弃 MySQL 运行批量集成与效率测试**

> 已于 2026-08-18 在独立可丢弃数据库 `clsen_data_test_batch_review`
> 验收：Repository、完整工作流、API、任务版本筛选、零发布及效率测试共 6 个用例通过。

```powershell
.\.venv\Scripts\python.exe -m pytest backend/tests/integration/test_batch_review_repository.py backend/tests/integration/test_batch_review_workflow.py backend/tests/integration/test_batch_reviews_api.py backend/tests/integration/test_batch_review_version_filter.py backend/tests/integration/test_batch_review_efficiency.py --require-mysql -q
```

预期：PASS；不得运行主数据库迁移。

- [x] **步骤 9：运行前端完整门禁和 E2E**

```powershell
Set-Location frontend
pnpm test --run
pnpm lint
pnpm typecheck
pnpm build
pnpm test:e2e -- batch-review.spec.ts
Set-Location ..
```

预期：PASS。若本机认证或可丢弃数据库环境未准备好，E2E 标记未运行，不使用主数据库替代。

- [x] **步骤 10：最终只读检查**

```powershell
git diff --check
git status --short
```

预期：只有本功能及既有用户改动，所有文件保持未暂存；没有生产迁移、授权同步、部署或数据清理记录。

## 本机体验完成定义

以下条件全部满足才可交付体验：

1. 多文件导入队列可创建权威预检，并进入 `/review/batch/:runId`；
2. 用户能一次核对日期/类型并确认所选项目；
3. 浏览器最多三项并发，把安全项目推进到 `ready_for_publish`；
4. 已有草稿/发布、识别不确定、警告、阻断和状态变化全部转人工；
5. 一项失败不停止其他项，暂停、恢复和刷新均从服务器状态继续；
6. 相同命令重试不产生重复解析基线、草稿、校验或审核事件；
7. 全流程没有自动发布、发布指针切换或覆盖既有版本；
8. 30 份文件相对逐份串行至少提速 50%，100 份文件无重复与连接池耗尽；
9. 单元、契约、集成、前端、响应式和端到端门禁通过，或对缺失的可丢弃测试环境有明确未运行记录；
10. 未执行任何生产数据库迁移、生产授权、后台 Worker、消息队列、监控或部署工作。
