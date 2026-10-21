# 成品生产订单与完工入库实施计划（第一期优化稿）

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 在 P0 已批准商品目录之上交付成品生产订单、工厂完工审核和广州工厂成品仓库存模块，形成“订单到广州成品仓”的第一期闭环；生产领域只消费稳定 `style_id/sku_id`，不再建立第二套商品身份。

**Architecture:** 新建独立 `production` 领域，复用 P0 商品目录、站点隔离、Cookie/CSRF/RBAC、不可变内容存储、审计、幂等和批量审核交互模式，但不把生产数据塞入日报或商品目录表。P0 `0022` 先交付稳定商品身份；生产迁移 `0023` 只交付生产订单和工厂/运营编码 sidecar，Task 7 暂停保存体验证据；迁移 `0024` 再交付完工审核、入库流水和库存余额。开始 Task 8 后最终最低 head 为 `0024`，不承诺运行于纯 `0023`。

**Tech Stack:** Python 3.14、FastAPI、Pydantic、SQLAlchemy Core、Alembic、MySQL 8.0/8.4、openpyxl 3.1、defusedxml 0.7、React 19.1.1、TypeScript 5.9.2、Vitest 3.2、Playwright 1.62、pnpm 11.16。

**Design spec:** `docs/superpowers/specs/2026-08-18-finished-goods-production-receipt-design.md`（第一期正式批准规格）

**Full-chain roadmap:** `docs/superpowers/plans/2026-08-18-end-to-end-sku-supply-chain-roadmap.md`

**Execution status:** 本文仍是未实施且暂停的后继计划。2026-08-20 已删除可执行范围中的重复 SKU 身份建模并顺延迁移为 `0023/0024`；只有 P0 Milestone A 通过、目录 V1 已批准且本计划 successor 再次书面批准后才可开工。本轮未编码、未执行迁移或业务测试、未提交。

## Global Constraints

- 第一阶段只管理成品生产数量和完工入库；不加入原材料、BOM、工序、质检、出货、海运、FBA、销售或退货。后五项仍是总体项目要求，按全链路路线图 E0/C/D/E 交付。
- 库存单位固定为“件”；订单量和完工量使用正整数，库存流水使用有符号整数。
- 业务关联只使用 P0 当前批准目录中的稳定 `style_id/sku_id/style_revision_id/sku_revision_id`、订单 ID、订单明细 ID 和来源行 ID；不得使用展示 SKU 字符串拼接外键。
- `product_styles/product_skus`、两类 revision、identity reservation 和 Seller SKU mapping 完全由 P0 拥有；production 代码、迁移和权限清单不得创建、修改或删除这些身份事实。历史生产行冻结目录四元组和字段快照，第一期不合并两个 `sku_id`、不迁移既有事实。
- 运营/工厂编码只保存带目录版本与审核来源的 production sidecar；Amazon Seller SKU/FNSKU/ASIN 继续由 P0/E0 的带作用域映射拥有。未知编码必须选择已批准 SKU，或先回到商品目录批准后继版本，生产 UI 不提供第二套建 SKU 命令。
- 生产窗口不保存人工预计完工日，统一按订单日 `D` 和站点本地自然日派生：有未完工量的非取消订单在 `D+7` 前为 `not_due`、`D+7` 至 `D+30`（含首尾）为 `in_window`、`D+30` 后为 `overdue`；已无未完工量或已取消时窗口状态为 `null`。API 可接受 `as_of_date` 以便确定性查询和测试。
- 只有审核通过且未冲销的完工行进入正式完工量和库存；所有入账必须在一个 MySQL 事务中完成。
- 复用现有 `admin`、`data_manager`、`viewer`，不创建角色；写操作使用 `require_write_roles("admin", "data_manager")`，冲销只允许 `admin`，`viewer` 不访问本模块。
- 原始工作簿进入现有内容寻址存储和 `raw_files`，但生产导入使用独立领域表，不创建伪造的日报 `import_batches`。
- 第一版只接受 `.xlsx`，拒绝 `.xls`、`.xlsm`、公式、外部链接、隐藏数据表和非标准表头。
- 工作簿使用只读解析；每份文件最多 10,000 条数据行、16 列、128 个 ZIP 条目和 200 MiB 解压后内容，并继续受 `APP_STORAGE_MAX_UPLOAD_BYTES` 限制。
- 导入批次区分文件保存、解析中、解析成功和解析失败；进程退出后必须恢复同一批次，不能留下被摘要去重永久卡住的空批次。
- 每条校验成功的完工行保存带 schema 版本的 `validation_digest`；提交审核时服务端必须复读事实并复算，摘要变化的行不能进入审核。
- 完工文件去重只约束未撤回活动批次；撤回释放活动去重键，原批次和审计不删除。
- 审核先对完整决定集合执行服务端 `review-preview`，返回 `projection_digest` 和逐条 `{code, fingerprint}`；正式审核必须提交同一决定集合、摘要和确认。选择、排序后规范内容或锁内事实任一变化都使旧摘要及确认失效。
- 写命令先以 UUID v4 建立带租约和 fencing token 的持久 claim；成功业务事务同时写不可变 `production_command_effects` 事实锚点并完成命令。提交结果不确定时由 reconciler 查询事实锚点，确定转换为 `completed` 或在租约过期且无事实时转换为 `retryable`，不能让 `running/outcome_unknown` 永久悬挂。
- 批次、明细、待办、订单和库存列表使用服务端分页；单次审核决定默认最多 500 行，超过时由客户端分批且每批保持独立原子性。
- 所有带 `site_id` 的业务引用使用复合外键保证同站点；API 与服务层仍继续执行站点过滤。
- 当前文件系统迁移头为已应用于测试环境且不可重写的 `0021`；P0 使用 `0022`，本计划固定消费该 head 后的 `0023/0024`，执行前若真实线性 head 再变化必须先向前修订本计划，不能创建分叉。
- 应用、迁移和备份测试只能连接名称匹配 `clsen_data_test*` 的可丢弃数据库，并使用包含 `charset=utf8mb4` 的 URL。唯一窄例外是 `verify_restore()` 的一次性 scratch schema：它必须精确命名为外部注入 run ID 对应的 `clsen_restore_<32hex>`，内容面只允许专用最小 restore-admin 连接、恢复和读取；经校验的 caller-owned grant-admin 仅可依据私有所有权清单对该精确名称执行 `CREATE USER/GRANT/REVOKE/DROP` 等控制面 provision/cleanup，不得 `USE`、导入或读取 scratch 内容。应用、迁移、runtime/backup 账号及其他测试均不得连接该前缀，验证结束即清理。
- 保留现有脏工作区；不得清理、覆盖或还原无关修改。
- 未经用户另行授权，不执行 `git add`、`git commit`、合并、变基、打标签或推送。现有工作区在本计划开始前已包含无关脏文件，Task 0 必须冻结本计划 touched-file manifest；后续 `git diff --check` 只传入该 manifest 中的路径，不能因无关基线告警失败，也不能顺手格式化用户文件。最终门禁再对 manifest 内已跟踪及未跟踪文本执行格式化器和显式尾随空白/末尾换行扫描；全工作区扫描只生成非阻断基线报告。

## File Structure

### Backend production domain

- `backend/app/site_context.py`：从认证后的站点配置构造共享、不可由客户端覆盖的 `CurrentSiteContext`。
- `backend/app/production/types.py`：枚举、错误、不可变 DTO、命令、规范摘要和状态转移。
- `backend/app/production/workbooks.py`：两份导入模板、工作簿安全检查、解析和固定版本的工厂生产订单导出。
- `backend/app/production/command_repository.py`、`command_service.py`：命令租约、fencing、成功事实锚点、结果查询和 `completed/retryable` 恢复。
- `backend/app/production/upload_service.py`：把领域上传接入通用不可变文件协调器。
- `backend/app/production/sku_repository.py`、`sku_service.py`：只读 P0 目录适配、production alias 规范化、绑定和解析；不创建或修订商品身份。
- `backend/app/production/order_repository.py`、`order_service.py`：订单导入、编号、确认、变更、关闭、取消、详情和进度。
- `backend/app/production/completion_repository.py`、`completion_service.py`：完工批次、匹配、提交、审核、幂等入账和冲销。
- `backend/app/production/inventory_queries.py`：成品仓余额和不可变流水查询。
- `backend/app/api/production_skus.py`、`production_orders.py`、`production_completions.py`、`production_inventory.py`、`production_commands.py`：五个聚焦 API 路由；`production_skus.py` 仅暴露 P0 目录只读选择和 production alias 写入。

### Frontend production feature

- `frontend/src/features/production/productionTypes.ts`：服务端响应和命令类型。
- `frontend/src/features/production/productionApi.ts`：模板下载、二进制上传、JSON 写命令和查询。
- `frontend/src/features/production/ProductionLayout.tsx`：模块内部导航与嵌套路由出口。
- `frontend/src/features/production/SkuCatalogPage.tsx`：P0 SKU 只读选择与 production alias 维护，不承载商品建档。
- `frontend/src/features/production/ProductionOrdersPage.tsx`、`ProductionOrderDetailPage.tsx`：订单上传、列表、详情、变更和导出。
- `frontend/src/features/production/CompletionImportsPage.tsx`、`CompletionReviewPage.tsx`：完工上传、匹配、校验和审核。
- `frontend/src/features/production/CompletionReviewQueuePage.tsx`：服务端分页待审核队列。
- `frontend/src/features/production/FactoryInventoryPage.tsx`：库存余额与流水。
- `frontend/src/features/production/FinishedGoodsReceiptDetailPage.tsx`：入库单、来源完工行、生产订单和冲销链只读详情。
- `frontend/src/features/production/ProductionWorkspace.css`：紧凑表格、步骤条、警告和窄屏内部滚动。

---

## Milestone A：SKU 与成品生产订单

### Task 0: 冻结基线和迁移头

**Files:**

- Create: `docs/superpowers/plans/2026-08-18-finished-goods-production-receipt-file-manifest.json`
- Read: `backend/alembic/versions/`
- Read: `backend/app/imports/service.py`
- Read: `backend/app/imports/repository.py`
- Read: `backend/app/imports/storage.py`
- Read: `backend/app/api/dependencies.py`
- Read: `frontend/src/app/App.tsx`
- Read: `docs/superpowers/specs/2026-08-18-finished-goods-production-receipt-design.md`
- Read: `docs/superpowers/plans/2026-08-18-end-to-end-sku-supply-chain-roadmap.md`

**Interfaces:**

- Consumes: 当前 `0021` 迁移头、`LocalContentStore`、现有认证和 `writeApi`。
- Produces: 一份保存在仓库外私有目录的可校验工作区基线，以及仅列出本计划后续 Create/Modify/Regenerate 路径的 JSON touched-file manifest；不产生业务代码或数据库变化。

- [ ] **Step 1: 确认第一期边界、工作区和唯一迁移头**

```powershell
git status --short --branch
.\.venv\Scripts\python.exe -m alembic -c backend/alembic.ini heads
```

Expected: 文末“第一期开工门禁”已有明确答案且当前只授权 A/B；唯一头为 `0021`。若迁移头不是 `0021`，先修改本计划中的迁移编号和契约测试预期。

用 `apply_patch` 创建 JSON 字符串数组形式的 touched-file manifest，逐项收录本文各 Task 的计划内 Create/Modify/Regenerate 路径并按仓库相对路径去重、升序排列；清单必须包含自身和本实施计划，不得自动收录 `git status` 中其他既有脏文件。立即验证 JSON 可解析、每项都是非空相对路径、没有 `..` 逃逸且解析后仍位于当前仓库内；后续若计划内文件集合变化，同一 Task 必须先更新 manifest。另把全工作区已有尾随空白等问题记录为非阻断基线，禁止修改这些无关文件。

在任何计划内源码改动前创建带随机 ID、ACL 仅当前操作者可读写的仓库外私有 `baseline_root`；解析后的目录必须不在仓库根内，ACL 建立或验证失败就停止。基线保存冻结的仓库绝对路径和 `HEAD` OID，以及 NUL 分隔的 `git status --porcelain=v1 -z --untracked-files=all`、`git ls-files -s -z` 原始输出，不能用逐行解析破坏带空格文件名。对 manifest 每个路径记录 `absent | tracked_clean | tracked_dirty | untracked`、索引/工作树状态、长度和 SHA-256；凡基线时已存在者都按仓库相对结构保存原始字节副本。对已跟踪脏文件另保存 `HEAD` blob、index blob、staged/unstaged 二进制 diff；对基线不存在的路径保存显式 absent 记录。元数据及所有副本再生成一份排序的 SHA-256 清单。`baseline_root` 及其路径提示不得进入仓库、manifest、日志或提交；把根路径保存在操作者私有记录中，最终通过 `APP_PLAN_BASELINE_ROOT` 显式提供，并保留到用户验收结束。

- [ ] **Step 2: 运行现有聚焦基线**

```powershell
.\.venv\Scripts\python.exe -m pytest backend/tests/unit/imports backend/tests/unit/batch_review backend/tests/unit/test_openapi_contract.py -q
Set-Location frontend
pnpm test --run src/app/App.test.tsx src/features/batch-review
Set-Location ..
```

Expected: PASS；无关既有失败只记录，不顺手修改。

- [ ] **Step 3: 保存未提交检查点**

```powershell
$manifestPath = '.\docs\superpowers\plans\2026-08-18-finished-goods-production-receipt-file-manifest.json'
$planPaths = @(Get-Content -Raw -LiteralPath $manifestPath | ConvertFrom-Json)
if ($planPaths.Count -eq 0 -or ($planPaths -join "`n") -cne (($planPaths | Sort-Object -Unique) -join "`n")) { throw 'touched-file manifest must be non-empty, unique, and sorted' }
$requiredPaths = @('docs/superpowers/plans/2026-08-18-finished-goods-production-receipt-file-manifest.json', 'docs/superpowers/plans/2026-08-18-finished-goods-production-receipt-implementation.md')
if (@($requiredPaths | Where-Object { $_ -cnotin $planPaths }).Count -ne 0) { throw 'touched-file manifest is not self-contained' }
$repoPrefix = [IO.Path]::GetFullPath((Get-Location).Path + [IO.Path]::DirectorySeparatorChar)
foreach ($path in $planPaths) { if ($path -isnot [string] -or [string]::IsNullOrWhiteSpace($path) -or [IO.Path]::IsPathRooted($path) -or [IO.Path]::GetFullPath((Join-Path $repoPrefix $path)).StartsWith($repoPrefix, [StringComparison]::OrdinalIgnoreCase) -ne $true) { throw "unsafe manifest path: $path" } }
git diff --check -- $planPaths
git status --short
```

Expected: manifest 通过 JSON、排序、去重、自包含和仓库边界验证；仓库外基线完整记录跟踪/未跟踪/不存在状态、SHA-256、原始字节和已跟踪脏文件的 staged/unstaged diff；除该计划内 manifest 外没有新增修改，既有无关脏文件保持不变。

### Task 1: 安全 XLSX 契约、模板与解析器

**Files:**

- Modify: `backend/pyproject.toml`
- Modify: `backend/requirements.in`
- Regenerate: `backend/requirements.lock`
- Create: `backend/app/production/__init__.py`
- Create: `backend/app/production/workbooks.py`
- Create: `backend/tests/unit/production/__init__.py`
- Create: `backend/tests/unit/production/test_workbooks.py`

**Interfaces:**

- Consumes: `WorkbookUpload(content: bytes, filename: str, media_type: str)`；内容、原文件名和声明媒体类型必须同时进入安全校验，不能让解析函数在缺少元数据时声称已经验证扩展名或 MIME。
- Produces: `validate_workbook_upload_metadata(filename, media_type) -> SafeWorkbookMetadata`、`build_order_template() -> WorkbookArtifact`、`build_completion_template() -> WorkbookArtifact`、`parse_order_workbook(upload: WorkbookUpload) -> ParsedOrderWorkbook`、`parse_completion_workbook(upload: WorkbookUpload) -> ParsedCompletionWorkbook`、`build_factory_order_export(order: FactoryOrderExport) -> WorkbookArtifact`；`WorkbookArtifact` 固定包含 `content`、安全 `filename` 和 XLSX `media_type`。纯元数据预检可在写入 raw file/领域批次前执行，完整内容安全校验仍由 parser 负责。

- [ ] **Step 1: 写依赖和模板失败测试**

测试固定工作表及表头：

```python
ORDER_SHEET = "成品生产订单"
ORDER_HEADERS = (
    "外部订单号", "订单日期", "SKU编码", "款号",
    "颜色", "尺码", "下单数量", "备注",
)
COMPLETION_SHEET = "完工入库"
COMPLETION_HEADERS = (
    "系统生产订单号", "工厂订单导出版本", "工厂订单修订号", "SKU编码",
    "本次完工数量", "实际完工日期", "款号", "颜色", "尺码", "工厂备注",
)
FACTORY_ORDER_EXPORT_VERSION = "production_factory_order_v1"
FACTORY_ORDER_SHEET = "工厂生产订单"
FACTORY_ORDER_HEADERS = (
    "导出版本", "系统生产订单号", "订单修订号", "外部订单号", "订单日期",
    "生产窗口开始日", "生产窗口结束日", "SKU编码", "款号", "颜色",
    "尺码", "下单数量", "备注",
)
```

断言两份导入模板可被 openpyxl 只读打开、只有一个可见工作表、首行为精确表头、数量和工厂订单修订号列有正整数提示、日期列格式为 `yyyy-mm-dd`，完工模板的导出版本提示固定值 `production_factory_order_v1`。工厂导出同样只有一个可见工作表，首行为 `FACTORY_ORDER_HEADERS`；输入/查询即使乱序，输出仍严格按稳定 `order_line_id` 升序。每行导出版本、系统订单号和订单修订号一致，生产窗口开始/结束日严格由订单日派生为 D+7/D+30，SKU 编码、款号、颜色、尺码取订单确认时的行快照，数量取该修订的有效下单量，不读取后来变更的 SKU 当前属性。

- [ ] **Step 2: 运行测试确认缺少实现**

```powershell
.\.venv\Scripts\python.exe -m pytest backend/tests/unit/production/test_workbooks.py -q
```

Expected: FAIL，原因是 `app.production.workbooks` 或目标函数不存在。

- [ ] **Step 3: 锁定工作簿依赖**

在 `pyproject.toml` 和 `requirements.in` 增加：

```text
openpyxl>=3.1,<4
defusedxml>=0.7,<1
types-openpyxl>=3.1,<4
types-defusedxml>=0.7,<1
```

前两项属于运行依赖，两个 `types-*` 包属于开发/质量依赖；版本由锁文件解析并固定。实现直接导入 openpyxl/defusedxml 时不得用全局 `ignore_missing_imports` 掩盖类型缺口。

使用以下现有锁定流程，不得手改锁文件中的哈希：

```powershell
.\.venv\Scripts\pip-compile.exe --allow-unsafe --generate-hashes --no-emit-index-url --no-emit-trusted-host --output-file=backend\requirements.lock --strip-extras backend\requirements.in
.\.venv\Scripts\python.exe -m pip install --require-hashes -r backend\requirements.lock
```

- [ ] **Step 4: 实现模板和安全解析**

`workbooks.py` 固定：

```python
MAX_DATA_ROWS = 10_000
MAX_COLUMNS = 16
MAX_ZIP_ENTRIES = 128
MAX_UNCOMPRESSED_BYTES = 200 * 1024 * 1024
```

先对不可信 basename 校验 `.xlsx` 扩展名，并校验声明媒体类型与实际 ZIP/OOXML 内容；正式接受 `application/vnd.openxmlformats-officedocument.spreadsheetml.sheet`，只有扩展名和内容均严格通过时才兼容 `application/octet-stream`。在调用 openpyxl 前遍历 ZIP 中央目录：拒绝重复 member 名，以及在统一 `/` 分隔、去除冗余 `.` 段并 `casefold()` 后发生的名称冲突；拒绝绝对路径、盘符、反斜杠、NUL、空段和任何 `..` 段。不能只相信中央目录的 `file_size`：以有上限的流式读取核对每项实际解压字节数、累计上限和 CRC，未读到 EOF、声明/实际长度不符或 CRC 异常均拒绝。完成这一步后再检查唯一的 `[Content_Types].xml`、关系文件和 worksheet part，并以 `read_only=True, data_only=False, keep_links=False` 打开，避免校验器与 zipfile/openpyxl 对重复 part 选择不同条目。显式拒绝加密条目、宏/VBA、`externalLinks`、`TargetMode="External"`、OLE/DDE 关系、公式、隐藏表、多表、错误表名、错误表头、超过限制、布尔数量、小数数量、零和负数；不能把 `keep_links=False` 当成已经验证“没有外部链接”。工厂导出文件名固定为 `production-order-{internal_order_number}-r{revision}.xlsx`，日期单元格固定 `yyyy-mm-dd`，数量为整数。实现统一 `write_formula_safe_text_cell()`：把用户文本显式写为 OOXML 字符串单元格、绝不写成公式类型，且不通过添加 `'` 等前缀改变逻辑值；模板把编码和备注列预设为文本。以 `= + - @` 开头的合法 SKU 必须导出后逐字符读回并可直接用于完工匹配。

- [ ] **Step 5: 补齐有效和恶意 fixture 测试**

覆盖正常日期、Excel 日期单元格、空行、重复 SKU、跨行订单头不一致、工厂导出版本/订单修订号缺失或非法、公式、`.xlsm`/VBA、外部关系、OLE/DDE、加密条目、隐藏表、ZIP 膨胀、超行、超列、错误扩展名/MIME 和公式注入；恶意 ZIP fixture 另覆盖重复 `[Content_Types].xml`、重复 worksheet、仅大小写或斜杠规范化后冲突的 part、绝对/盘符/反斜杠/`..` 路径、伪造解压长度、截断流和 CRC 错误，全部必须在 openpyxl 解析前稳定拒绝。另以乱序 `FactoryOrderExport` fixture 断言工作表、版本、精确列序、按 `order_line_id` 稳定排序、文件名、订单修订、空外部单号、Unicode、行快照和公式安全字符串；对 `=SKU`、`+SKU`、`-SKU`、`@SKU` 逐字符往返并完成完工回匹配。SKU 当前修订变化后重导同一订单修订，快照列和行序必须不变。

- [ ] **Step 6: 运行解析测试和静态检查**

```powershell
.\.venv\Scripts\python.exe -m pytest backend/tests/unit/production/test_workbooks.py -q
.\.venv\Scripts\python.exe -m ruff check backend/app/production/workbooks.py backend/tests/unit/production/test_workbooks.py
.\.venv\Scripts\python.exe -m ruff format --check backend/app/production/workbooks.py backend/tests/unit/production/test_workbooks.py
.\.venv\Scripts\python.exe -m mypy --config-file backend/pyproject.toml backend/app/production/workbooks.py backend/tests/unit/production/test_workbooks.py
git diff --check -- (Get-Content -Raw -LiteralPath .\docs\superpowers\plans\2026-08-18-finished-goods-production-receipt-file-manifest.json | ConvertFrom-Json)
```

Expected: PASS；保持未提交。

### Task 2: 迁移 0023——生产订单、目录引用和命令账本

**Files:**

- Create: `backend/alembic/versions/0023_production_orders.py`
- Modify: `backend/tests/contracts/test_migration_contract.py`
- Modify: `backend/tests/integration/test_migrations.py`
- Modify: `backend/tests/conftest.py`
- Create: `backend/tests/unit/test_mysql_safety_gate.py`
- Create: `backend/tests/integration/test_production_order_schema.py`
- Create: `backend/tests/integration/test_production_runtime_permissions.py`
- Modify: `backend/app/cli.py`、`backend/tests/unit/auth/test_admin_cli.py`
- Modify: `scripts/database-privileges.json`、`scripts/sync-test-runtime-grants.ps1`
- Create: `scripts/prepare-production-test-database.ps1`
- Modify: `backend/tests/contracts/test_database_bootstrap_script.py`、`.env.example`、`docs/operations/local-maintenance.md`

**Interfaces:**

- Consumes: P0 `0022` 的 `product_styles/product_style_revisions/product_skus/product_sku_revisions/product_catalog_versions/product_catalog_members` 只读身份，以及现有 `sites/users/raw_files/audit_events`。
- Produces: production-owned `production_sku_aliases`、`warehouses`、`production_order_sequences`、`production_order_imports/rows`、`production_orders/lines/adjustments`、`production_commands/effects`。不得创建或授予 production 对 P0 身份表的 INSERT/UPDATE/DELETE。

- [ ] **Step 1: 写线性迁移和安全门失败测试**

  迁移历史追加 `("0023", "0022", "0023_production_orders.py")`。所有自动 DDL 只允许 runner-owned、loopback、名称匹配 `clsen_data_test*`、`utf8mb4` 的 Oracle MySQL 8.0/8.4，且 migration/runtime/backup 账号分离；常驻业务库和 `APP_MIGRATION_DATABASE_URL` 不能作为测试 fallback。共享 `schema_revision.py` 在迁移创建时从 `0022` 推进到 `0023`，CLI/backup/bootstrap/grant/matrix 同步引用，不各自维护字符串。

- [ ] **Step 2: 写目录引用、订单和命令约束失败测试**

  每条订单明细必须以 `(site_id, sku_id, sku_revision_id)` 和 `(site_id, style_id, style_revision_id)` 复合外键证明引用 P0 同站点真实 revision，并保存批准时 `catalog_version_id` 与字段快照。production alias 唯一键必须含 site、source kind 和规范 bytes，只允许指向 P0 已批准成员；它不能使用或覆盖 P0 Seller Account/Marketplace mapping。仓库、年度序列、订单号、导入状态、数量、UUID、SHA-256、command lease/effect、复合站点外键与保守降级约束沿原计划保持。

- [ ] **Step 3: 实现 0023 且不重复建身份**

  迁移只建 production-owned 表、索引和约束。不得出现创建 `product_styles/product_style_revisions/product_skus/product_sku_revisions/product_identity_key_reservations` 的 DDL；对这些表的 runtime grant 只能是查询所需 SELECT。发现无当前已批准目录、SKU 不属于目录、revision 不匹配或目录在确认事务前变化时整单阻断。降级发现任一 production 业务行时在结构变化前抛出 `0023 downgrade refused`。

- [ ] **Step 4: 同步最小权限和测试准备脚本**

  prepare 只接受显式 `-Revision 0023`，从三个已校验测试 URL 与 caller-owned grant-admin option file 取得精确目标；迁移后查询实际 head，再同步 production-owned 表权限。运行账号对 P0 身份表零写权限，对不可变订单事实/command effect 仅 INSERT，对窄状态/lease 表仅列级 UPDATE，无 DELETE/DDL。

- [ ] **Step 5: 运行非数据库和 disposable MySQL 门**

  ```powershell
  .\.venv\Scripts\python.exe -m pytest backend/tests/contracts/test_migration_contract.py backend/tests/contracts/test_schema_revision_contract.py backend/tests/contracts/test_database_bootstrap_script.py backend/tests/unit/auth/test_admin_cli.py backend/tests/unit/test_mysql_safety_gate.py -q
  .\scripts\prepare-production-test-database.ps1 -Revision 0023
  .\.venv\Scripts\python.exe -m pytest backend/tests/integration/test_migrations.py backend/tests/integration/test_production_order_schema.py backend/tests/integration/test_production_runtime_permissions.py --require-mysql -q
  ```

  Expected: P0 `0022` 保持字节级不可变；单一 head 为 `0023`；production 不能写 P0 身份表，跨目录/跨站/revision 拼接均被数据库拒绝。

### Task 3: P0 目录解析、production alias 和命令恢复基础

**Files:**

- Create: `backend/app/site_context.py`
- Create: `backend/app/production/types.py`
- Create: `backend/app/production/command_repository.py`、`command_service.py`
- Create: `backend/app/production/sku_repository.py`、`sku_service.py`
- Create: `backend/tests/unit/production/test_types.py`、`test_command_service.py`、`test_sku_service.py`
- Create: `backend/tests/integration/test_production_command_recovery.py`、`test_sku_repository.py`

**Interfaces:**

- `sku_repository.py/sku_service.py` 是只读 P0 catalog adapter 与 production alias service，名称为兼容原 manifest 保留；它们不提供 create/update/merge/repoint SKU。
- Consumes: `CurrentSiteContext`、认证 actor、当前批准 `catalog_version_id`、外部运营/工厂编码、明确目标 `sku_id`、expected catalog publication revision、原因和 UUID v4。
- Produces: `resolve_catalog_sku(...)`、`list_catalog_skus(...)`、`bind_production_alias(...)`、`resolve_production_alias(...)` 与既有 command claim/renew/complete/reconcile；任何请求 DTO 都不接受客户端 site/actor。

- [ ] **Step 1: 写只读目录与 alias 失败测试**

  覆盖无批准目录、stale catalog revision、disabled/非成员 SKU、跨站 SKU、错误 SKU/style revision、alias 冲突、未知编码、Amazon source kind 越界，以及 repository/API 中不存在任何创建或修改 P0 identity 的方法。款号/颜色/尺码只作安全建议，不拼接新 ID。

- [ ] **Step 2: 实现命令租约、语义摘要与恢复**

  继续使用 UUID v4、canonical JSON SHA-256、lease/fencing 和唯一 effect。提交回执未知时按事实锚点收敛；过期且无 effect 才 retryable，同 token 改语义冲突，旧 worker 不能写入。

- [ ] **Step 3: 实现目录解析和 production alias**

  在一个一致性读取中固定 current catalog publication revision，验证目标 SKU/style revision 都是该目录成员。解析顺序为订单行冻结 `factory_sku_code_snapshot` → 同 source production alias → 当前批准目录内部展示编码；历史编码只返回需确认建议。成功 alias 事务保存目录版本、目标四元组、来源和审计，不更新 P0 表。

- [ ] **Step 4: 运行聚焦测试**

  ```powershell
  .\.venv\Scripts\python.exe -m pytest backend/tests/unit/production/test_types.py backend/tests/unit/production/test_command_service.py backend/tests/unit/production/test_sku_service.py -q
  .\.venv\Scripts\python.exe -m pytest backend/tests/integration/test_production_command_recovery.py backend/tests/integration/test_sku_repository.py --require-mysql -q
  ```

  Expected: production 只能消费已批准 P0 身份；alias 可审计、可重放且不产生任何 style/SKU/revision/reservation 增量。
### Task 4: 提取通用不可变原文件上传协调器

**Files:**

- Create: `backend/app/imports/raw_upload.py`
- Modify: `backend/app/imports/service.py`
- Modify: `backend/app/imports/repository.py`
- Create: `backend/app/production/upload_service.py`
- Modify: `backend/tests/unit/imports/test_service.py`
- Create: `backend/tests/unit/production/test_upload_service.py`
- Create: `backend/tests/integration/test_production_uploads.py`

**Interfaces:**

- Consumes: 现有 `LocalContentStore`、`file_ingest_leases`、`raw_files` 和领域 finalizer。
- Produces: 通用 `RawUploadCoordinator[T]`；现有 `IngestService.ingest()` 外部签名和行为保持不变；production finalizer 显式接收服务端 `CurrentSiteContext` 和 actor，生产订单上传返回 `ProductionImportCreated(import_id, raw_file_id, sha256_hex)`，领域服务另提供 `resume_order_parse(context, actor_user_id, import_id, command) -> OrderImportView`，不要求浏览器重新持有源文件。可恢复状态从已保存的 `raw_file_id` 读取内容并取得新的解析 fencing claim；已经 `parsed` 时只完成 production command claim/effect，不读取工作簿或取得解析 claim。

- [ ] **Step 1: 写现有导入不回归和生产上传失败测试**

定义精确泛型边界：

```python
class RawUploadFinalizer(Protocol[T]):
    def finalize(
        self, connection: Connection, *, lease_token: UUID,
        command: RawUploadCommand, stored: StoredContent,
        completed_at: datetime,
    ) -> T:
        raise NotImplementedError
    def recover(self, lease_token: UUID) -> T | None:
        raise NotImplementedError

class RawUploadCoordinator(Generic[T]):
    def ingest(
        self, source: BinaryReadStream, command: RawUploadCommand,
        finalizer: RawUploadFinalizer[T],
    ) -> T:
        raise NotImplementedError
```

测试相同内容只创建一个 `raw_files` 对象，但日报和生产领域各自拥有独立引用；同一 production 领域相同文件摘要返回已有活动导入定位符。扩展名/MIME 纯元数据预检必须发生在内容存储、摘要去重和领域 finalizer 之前：错误元数据请求返回 422 且不创建 raw file/import，随后用相同字节和正确元数据重传可以正常创建。覆盖 finalizer 已提交但响应丢失、文件已保存但预览尚未解析、同一 UUID 恢复和不同 UUID 并发上传。

- [ ] **Step 2: 运行测试确认缺少协调器**

```powershell
.\.venv\Scripts\python.exe -m pytest backend/tests/unit/imports/test_service.py backend/tests/unit/production/test_upload_service.py -q
```

Expected: 新生产测试 FAIL，现有导入测试仍 PASS。

- [ ] **Step 3: 提取协调器并适配现有 IngestService**

把租约创建、续租、流式写入、摘要锁、提升、提交结果恢复和失败清理移动到 `raw_upload.py`。现有 `IngestService` 只构造日报 finalizer；不得复制存储安全逻辑。

- [ ] **Step 4: 实现生产订单 finalizer**

API 先调用 Task 1 的纯元数据预检，通过后生产 finalizer 才在摘要锁事务内复用或创建 `raw_files`，再创建解析状态为 `uploaded` 的 `production_order_imports`，并把本次 `RawUploadCommand` 的安全原文件名和声明媒体类型复制到领域批次。内容相同但上传元数据不同的合法请求可复用 raw file 内容，绝不能覆盖或借用另一批次的元数据。不创建 `import_batches`，不伪造报告日期和报告类型。finalizer 返回稳定 import ID；后续解析通过 fencing claim 把同一批次推进到 `parsed` 或 `parse_failed`，进程退出后可由显式 resume 命令用“批次元数据 + raw file 内容”重建 `WorkbookUpload` 并安全恢复，重复上传不得生成永久空批次。GET 只报告状态，不隐式执行长解析；不可恢复的工作簿校验错误保持 `parse_failed` 并返回稳定原因码，`uploaded`、暂时性 `parse_failed` 或过期 `parsing` claim 允许 resume；`parsed` 对任意合法 resume UUID 都通过 production command claim/effect 幂等返回现有批次结果，但不取得解析 claim、不重新解析。

- [ ] **Step 5: 运行上传、存储和集成回归**

```powershell
.\.venv\Scripts\python.exe -m pytest backend/tests/unit/imports backend/tests/unit/production/test_upload_service.py -q
.\.venv\Scripts\python.exe -m pytest backend/tests/integration/test_file_ingest.py backend/tests/integration/test_production_uploads.py --require-mysql -q
git diff --check -- (Get-Content -Raw -LiteralPath .\docs\superpowers\plans\2026-08-18-finished-goods-production-receipt-file-manifest.json | ConvertFrom-Json)
```

Expected: PASS；现有 CSV 导入语义不变；既有并发上传、提交回执丢失、摘要锁释放和恢复测试全部继续通过。

### Task 5: 生产订单导入、确认和进度服务

**Files:**

- Create: `backend/app/production/order_repository.py`
- Create: `backend/app/production/order_service.py`
- Create: `backend/tests/unit/production/test_order_service.py`
- Create: `backend/tests/integration/test_production_order_workflow.py`

**Interfaces:**

- Consumes: `CurrentSiteContext`、认证 actor、`ParsedOrderWorkbook`、SKU 解析、原文件导入记录和命令 UUID。
- Produces: `OrderService.create_or_resume_preview(context, actor_user_id, command, workbook) -> OrderImportView`、`get_import(context, import_id, page) -> OrderImportView`、`resolve_matches(context, actor_user_id, command) -> OrderImportView`、`confirm(context, actor_user_id, command) -> ProductionOrderView`、`adjust(context, actor_user_id, command) -> ProductionOrderView`、`close(context, actor_user_id, command) -> ProductionOrderView`、`cancel(context, actor_user_id, command) -> ProductionOrderView`、`get_order(context, order_id, as_of_date, page) -> ProductionOrderView`、`list_orders(context, as_of_date, filters) -> ProductionOrderPage`、`build_factory_export(context, order_id) -> WorkbookArtifact`。未显式提供 `as_of_date` 时，用 `context.reporting_timezone` 派生当前业务日；命令/请求模型中的站点和 actor 均不得覆盖 context/principal。导入、订单和明细响应使用服务端分页；`get_import` 是刷新与 resume UI 的只读服务边界，API 不得绕过它直查 repository。工厂导出使用专用非分页服务，在同一一致性读取中取得订单头、当前 order revision 和全部明细，固定按 `order_line_id` 排序；不得拿详情第一页生成整单导出。

- [ ] **Step 1: 写订单状态和命令失败测试**

固定状态：

```python
class ProductionOrderStatus(StrEnum):
    ACTIVE = "active"
    CLOSED = "closed"
    CANCELLED = "cancelled"

class FulfillmentStatus(StrEnum):
    NOT_STARTED = "not_started"
    PARTIALLY_COMPLETED = "partially_completed"
    COMPLETED = "completed"
    OVER_COMPLETED = "over_completed"

class ProductionWindowStatus(StrEnum):
    NOT_DUE = "not_due"
    IN_WINDOW = "in_window"
    OVERDUE = "overdue"
```

测试一份文件只生成一张订单、重复 SKU 阻断、未知 SKU 为 `needs_match`、全部阻断解除前不能确认。相同外部订单号或高度相似的“订单日 + SKU + 数量”返回 `possible_duplicate_order` 警告，避免修改过文件后误建第二张订单；指纹绑定候选订单 ID/revision、规范化当前行集合和导入 revision，确认命令必须提交精确 `{code, fingerprint}`，锁内候选变化使旧确认返回 409。外部单号仍不作为主键。窗口状态只对有未完工量的非取消订单返回枚举，使用站点本地自然日或显式 `as_of_date`：D+6=`not_due`、D+7/D+30=`in_window`、D+31=`overdue`，并覆盖跨月、闰日和完成后 `null`。

- [ ] **Step 2: 写编号、确认和变更集成失败测试**

订单编号由唯一 `(site_id, calendar_year)` 序列行在锁内生成，格式固定为 `PO-YYYY-NNNNNN`，数据库另以唯一 `(site_id, internal_order_number)` 兜底。约束测试直接插入重复年度序列和重复内部单号均失败；并发确认至少 20 个导入得到 20 个不同且连续递增的编号，重复确认同一命令返回同一订单；序列已经是 `999999` 时下一次确认返回 `409 production_order_sequence_exhausted`，不创建订单或消耗不合法号码。

- [ ] **Step 3: 实现订单预览和匹配**

使用解析 claim 原子保存每个原始行号、原始字段、规范 SKU、匹配状态和原因码；匹配成功时同时保存当时的 `sku_revision_id` 和展示编码/款号/颜色/尺码快照。解析失败不产生部分行并进入 `parse_failed`。同一 import ID 可恢复解析。命中已批准 P0 SKU 后可以保存 production alias；未知身份只能选择当前批准目录中的 SKU，或先在 `/catalog` 批准后继目录版本再回来重新解析，Task 3 不提供创建 SKU 服务。

- [ ] **Step 4: 实现确认、查询和派生进度**

确认事务锁定导入，重新验证每行并创建订单。每条订单明细固化 `sku_revision_id`、展示编码/款号/颜色/尺码和 `factory_sku_code_snapshot`，并幂等建立相同编码的 `factory_completion_excel` 别名；此后任何 SKU 新修订都不改变既有订单行或工厂导出。第一里程碑累计完工为零；查询接口已经使用统一公式，供第二里程碑接入有效入库汇总，并按 `order_date + as_of_date + remaining` 派生 `expected_completion_from`、`expected_completion_to` 和 `production_window_status`，不持久化会过期的状态。`build_factory_export` 在同一站点权限边界内一致读取当前订单 revision 的全部明细，按 `order_line_id` 排序后调用 Task 1 builder；详情分页大小不影响导出数量或顺序。

- [ ] **Step 5: 实现变更、关闭和取消**

数量变更写不可变 `production_order_line_adjustments` 和审计；关闭/取消必须填写原因。取消仅允许从未有批准入库的订单，第二里程碑加入收货事实复核。

- [ ] **Step 6: 运行订单领域测试**

```powershell
.\.venv\Scripts\python.exe -m pytest backend/tests/unit/production/test_order_service.py -q
.\.venv\Scripts\python.exe -m pytest backend/tests/integration/test_production_order_workflow.py --require-mysql -q
git diff --check -- (Get-Content -Raw -LiteralPath .\docs\superpowers\plans\2026-08-18-finished-goods-production-receipt-file-manifest.json | ConvertFrom-Json)
```

Expected: PASS。

### Task 6: P0 目录选择与生产订单 API、OpenAPI 契约和导出

**Files:**

- Create: `backend/app/api/production_skus.py`
- Create: `backend/app/api/production_orders.py`
- Create: `backend/app/api/production_commands.py`
- Modify: `backend/app/api/dependencies.py`
- Modify: `backend/app/api/data_calendar.py`
- Modify: `backend/app/main.py`
- Create: `backend/tests/unit/test_production_skus_api.py`
- Create: `backend/tests/unit/test_production_orders_api.py`
- Create: `backend/tests/unit/test_production_commands_api.py`
- Create: `backend/tests/integration/test_production_orders_api.py`
- Modify: `backend/tests/unit/test_openapi_contract.py`
- Regenerate: `frontend/src/api/generated.ts`

**Interfaces:**

- Consumes: Task 3/5 服务、共享 `CurrentSiteContext`、`X-Original-Filename`、请求 `Content-Type`、`Idempotency-Key` 和 `expected_revision`。`CurrentSiteContext` 由认证后的服务端配置解析，固定提供 `site_id`、`site_config_version_id` 和 `reporting_timezone`；生产 API 不接收也不信任客户端 `site_id`，现有 `data_calendar.py` 同步改为复用该依赖。
- Produces: `GET /api/production/skus`、`GET /api/production/skus/{sku_id}/revisions`、`POST /api/production/sku-aliases`、`GET /api/production/templates/production-order`、`POST /api/production/order-imports`、`GET /api/production/order-imports/{import_id}`、`POST /api/production/order-imports/{import_id}/resume`、`POST /api/production/order-imports/{import_id}/matches`、`POST /api/production/order-imports/{import_id}/confirm`、`GET /api/production/orders`、`GET /api/production/orders/{order_id}`、`GET /api/production/orders/{order_id}/factory-export`、`POST /api/production/orders/{order_id}/adjustments`、`POST /api/production/orders/{order_id}/close`、`POST /api/production/orders/{order_id}/cancel`、`GET /api/production/commands/{operation_token}`。前两个 SKU 端点是当前批准 P0 目录的只读投影，production 不提供 SKU create/PATCH/merge/repoint；订单 GET 可选 `as_of_date` 并返回 `expected_completion_from`、`expected_completion_to` 和可空 `production_window_status`；所有集合和明细行使用有上限的服务端分页。

- [ ] **Step 1: 写 RBAC、CSRF 和错误映射失败测试**

断言 `admin/data_manager` 可读写 production alias、订单和导入，`viewer` 得到 403，写端点要求 CSRF 和 UUID v4。客户端伪造 `site_id` 无论放在正文、查询还是头中都不能改变服务端站点；production 与 data-calendar 对同一会话得到同一个 `CurrentSiteContext`。SKU 列表和 revision 历史分别测试有上限分页、总数、筛选、批量别名加载、零 N+1 和跨站拒绝，并断言 production OpenAPI 中不存在 SKU create/PATCH/merge/repoint；订单 import GET 通过 `OrderService.get_import` 分页恢复，不由路由直查 repository。订单确认请求固定携带 `acknowledged_warnings: [{code, fingerprint}]`，未知字段禁止；过期 `possible_duplicate_order` 指纹返回 409。P0 身份纠错只能经 `/catalog` 的向前版本流程完成；命令 GET 只允许同站点原操作者读取，同站点 `admin` 代查必须新增审计。GET 对 `outcome_unknown` 和过期 `running` 调用 reconciler。固定映射：不存在 404，修订/状态/幂等冲突 409，字段及工作簿问题 422，仍在有效租约内的非终态 503，`retryable` 返回原 token 可重试语义。

- [ ] **Step 2: 实现 Pydantic 请求响应和路由**

所有请求模型使用 `ConfigDict(extra="forbid")`。上传正文保持二进制流，文件名来自百分号编码 UTF-8 的 `X-Original-Filename`，声明媒体类型来自请求 `Content-Type`；API 在调用内容存储前先执行 Task 1 的纯元数据预检，通过后才以三者构造 `WorkbookUpload`。错误扩展名/MIME 返回 422 且 raw file/import 均零落库。模板和导出直接使用 `WorkbookArtifact` 的 XLSX 媒体类型及安全 `Content-Disposition`；工厂导出只能调用 Task 5 的 `build_factory_export`，严格使用 Task 1 的版本、单表、精确列序和 `production-order-{internal_order_number}-r{revision}.xlsx` 文件名契约。`POST .../{import_id}/resume` 对同站点可恢复状态先取得 production command claim，再取得解析 claim 并从已保存原文件继续；状态已经是 `parsed` 时，同一或新的合法 UUID 仍必须取得 production command claim，并在事务内写恰好一条指向既有 import/revision 的 no-op/idempotent effect，但不取得解析 claim、不重新解析。重复或并发调用返回同一批次且不能产生重复行；新 UUID 也可通过 commands GET 恢复，且不能被另一语义复用。

- [ ] **Step 3: 写并通过 API 集成流程**

覆盖“从批准目录选择 SKU → 绑定 production alias → 下载模板 → 上传订单 → 处理匹配 → 确认 → 查询 D+6/7/30/31 窗口 → 调整 → 导出 → 在 P0 批准向前纠错 revision → 用旧工厂导出编码恢复匹配 → 关闭”，逐格断言工厂导出 v1 契约、repository 查询的 `ORDER BY order_line_id`、乱序数据仍稳定输出和历史行快照，并断言 production 侧 style/SKU/revision/reservation 增量为零；另创建明细数超过详情单页但不超过 10,000 行的订单，证明专用导出服务不漏行、不重复且 revision 一致，并断言审计中没有整份工作簿或绝对存储路径。订单 `parsed` 后用新 UUID 调用 resume，断言只新增一个指向既有 import 的 command effect、零解析 claim/零重复行，且 commands GET 返回同一结果；同 UUID 重试仍只有一个 effect。FastAPI 应用连接显式使用 `APP_TEST_RUNTIME_DATABASE_URL`，迁移账号只负责测试库建表/清理；权限不足必须暴露测试失败，不能悄悄回退到迁移账号。分别模拟确认事务已提交但 HTTP 回执丢失，以及事务回滚且租约过期；前者按 UUID GET 归并 `completed` 并得到同一订单，后者归并 `retryable` 后以原 UUID 只创建一张订单。

- [ ] **Step 4: 更新并生成 OpenAPI 客户端**

```powershell
.\scripts\generate-api-client.ps1
.\.venv\Scripts\python.exe -m pytest backend/tests/unit/test_production_skus_api.py backend/tests/unit/test_production_orders_api.py backend/tests/unit/test_production_commands_api.py backend/tests/unit/test_openapi_contract.py -q
.\scripts\generate-api-client.ps1 -Check
```

Expected: 无参数命令先写入 `frontend/src/api/generated.ts`，随后契约测试通过，最后 `-Check` 证明生成物稳定；脚本不存在 `-Write` 参数。

- [ ] **Step 5: 运行 API 与静态回归**

```powershell
.\.venv\Scripts\python.exe -m pytest backend/tests/integration/test_production_orders_api.py --require-mysql -q
.\.venv\Scripts\python.exe -m ruff check backend/app backend/tests
.\.venv\Scripts\python.exe -m ruff format --check backend/app backend/tests
.\.venv\Scripts\python.exe -m mypy --config-file backend/pyproject.toml backend/app backend/tests
git diff --check -- (Get-Content -Raw -LiteralPath .\docs\superpowers\plans\2026-08-18-finished-goods-production-receipt-file-manifest.json | ConvertFrom-Json)
```

Expected: PASS。

### Task 7: P0 目录选择与生产订单前端里程碑

**Files:**

- Create: `frontend/src/features/production/productionTypes.ts`
- Create: `frontend/src/features/production/productionApi.ts`
- Create: `frontend/src/features/production/ProductionLayout.tsx`
- Create: `frontend/src/features/production/SkuCatalogPage.tsx`
- Create: `frontend/src/features/production/ProductionOrdersPage.tsx`
- Create: `frontend/src/features/production/ProductionOrderDetailPage.tsx`
- Create: `frontend/src/features/production/ProductionWorkspace.css`
- Create: `frontend/src/features/production/productionApi.test.ts`
- Create: `frontend/src/features/production/SkuCatalogPage.test.tsx`
- Create: `frontend/src/features/production/ProductionOrdersPage.test.tsx`
- Create: `frontend/src/features/production/ProductionOrderDetailPage.test.tsx`
- Modify: `frontend/src/app/App.tsx`
- Modify: `frontend/src/app/App.test.tsx`
- Modify: `frontend/playwright.config.ts`
- Create: `frontend/playwright.live.config.ts`
- Modify: `frontend/vite.config.ts`
- Modify: `frontend/tsconfig.node.json`
- Modify: `backend/app/main.py`
- Create: `backend/tests/live/__init__.py`
- Create: `backend/tests/live/production_live_harness.py`
- Create: `backend/tests/unit/auth/test_production_live_harness.py`
- Create: `frontend/tests/e2e/live/global-setup.ts`
- Create: `frontend/tests/e2e/live/global-teardown.ts`
- Create: `frontend/tests/e2e/live/liveFixtures.ts`
- Create: `frontend/tests/e2e/live/production-orders-milestone.live.spec.ts`
- Create: `scripts/run-production-live-e2e.ps1`

**Interfaces:**

- Consumes: Task 6 API 和当前 `requestApi/writeApi`。
- Produces: `/production/skus`（只读 P0 目录选择与 production alias）、`/production/orders`、`/production/orders/:orderId`；侧栏为现有写角色显示一个“生产入库”入口，`viewer` 不显示且路由重定向首页。

- [ ] **Step 1: 写 API 适配器和路由失败测试**

断言二进制上传携带 `X-Original-Filename`、CSRF 和 UUID v4，JSON 写请求携带 `expected_revision`，模板/导出下载从响应头提取安全文件名。请求开始后 UUID 持久保留到命令 GET 返回终态；503、网络错误或刷新不能自动换 UUID。

- [ ] **Step 2: 实现 productionTypes 和 productionApi**

前端状态联合类型必须与服务端固定枚举一致，不用任意 `string` 代替订单、导入行或匹配状态。

- [ ] **Step 3: 写并实现 P0 SKU 选择与 production alias 页面**

页面只读查询当前批准 P0 款式/SKU、revision 和安全来源，允许绑定运营/工厂 production alias；不提供新建、修改、合并或重绑 P0 身份。未知 SKU 明确链接到 `/catalog` 发起目录后继版本，批准后返回并重新解析；production 页面不能把文件字段直接升格为身份。

- [ ] **Step 4: 写并实现订单上传和列表**

页面流程固定为“下载模板 → 选择文件 → 查看逐行结果 → 处理未知 SKU → 确认订单”。刷新后 GET 返回 `uploaded`、租约过期的 `parsing` 或可恢复 `parse_failed` 时显示“恢复解析”，显式调用订单 resume API 并保留该 UUID 到终态；恢复使用服务端原文件，不要求重新选择本地文件，永久工作簿错误只允许修正后重传。`possible_duplicate_order` 必须显示候选内部订单号并要求勾选当前服务端指纹，刷新或候选变化后重新确认。列表显示系统订单号、外部单号、日期、SKU 数、下单总量、单据状态、完工状态和 `not_due | in_window | overdue` 窗口徽标；无未完工量或已取消时不显示窗口徽标。

- [ ] **Step 5: 写并实现订单详情**

详情显示每个 SKU 的下单、待审核、累计完工、未完工、超额和基于站点自然日的窗口状态；第一里程碑后三项为零/下单量。实现固定 v1 工厂生产订单导出、数量变更、关闭和取消确认对话框；导出下载名和表内订单修订一致。

- [ ] **Step 6: 接入 App 路由并运行里程碑验收**

```powershell
.\.venv\Scripts\python.exe -m pytest backend/tests/unit/auth/test_production_live_harness.py -q
Set-Location frontend
pnpm test --run src/features/production src/app/App.test.tsx
pnpm lint
pnpm typecheck
pnpm build
Set-Location ..
git diff --check -- (Get-Content -Raw -LiteralPath .\docs\superpowers\plans\2026-08-18-finished-goods-production-receipt-file-manifest.json | ConvertFrom-Json)
```

Expected: PASS；此时可在已批准 P0 商品目录上单独体验目录选择、production alias 和生产订单，不依赖完工库存功能。

- [ ] **Step 7: 运行仅 production `0023` 的完整栈冒烟**

先落地专用 live harness：默认 `playwright.config.ts` 必须 `testIgnore` 所有 `*.live.spec.ts`；`playwright.live.config.ts` 只收集 `tests/e2e/live`，不继承默认配置且完全不声明 `webServer`。`run-production-live-e2e.ps1` 是 FastAPI 和 Vite 的唯一进程所有者：它从已校验测试 URL 派生 runner-owned 可丢弃库，要求 caller-owned grant-admin option file，先升级并初始化 P0 `0022` 目录 fixture，再调用 Task 2 安全准备脚本升级到 production `0023` 并同步最小授权；缺任何证据都在启动进程前拒绝。

runner 在启动任何进程前必须检查 `127.0.0.1:5173` 和 `127.0.0.1:8000` 均未占用；任一占用都安全拒绝，不复用也不终止现有开发进程。Vite 固定 loopback、端口 5173 和 `strictPort: true`，FastAPI 固定 loopback 和端口 8000，避免预检后的端口竞争被静默改到别处。每次先生成随机 run ID 和 ACL 收紧的私有临时根，在启动后端前创建其下独享的 app storage、browser storageState、fixture 和 log 目录，并只向 FastAPI 子进程注入该 app storage 的绝对 `APP_STORAGE_ROOT`；global setup 不得事后改变后端 storage。

Windows 后台进程使用 `Start-Process -WindowStyle Hidden -PassThru` 并把 stdout/stderr 定向到本 run log 目录，不能弹出可见窗口。FastAPI 必须直接以无 `--reload` 的 Python/uvicorn 进程启动；Vite 必须解析并由 `node.exe` 直接执行项目内 Vite CLI，不能经会派生不可追踪子进程的 `pnpm.cmd`。runner 在启动前建立启用 kill-on-close 的本 run Windows Job Object，把两个直接进程及其所有后代加入；Job Object 建立或归属失败则在启动 Playwright 前安全拒绝。后端/Vite 仅在 live 环境下分别暴露带该 run ID 的健康探针；Playwright 开始前必须读取并核对两个探针的精确 run ID，不能只因端口返回 200 就继续。runner 在 `try/finally` 中记录 Job Object、PID、启动时间和命令指纹；清理前再次核对根 PID/进程树仍属于本次 run，再关闭 Job Object 终止整棵本 run 树。未知 PID、已复用 PID、指纹不符或 Job 外进程一律不杀，临时目录也只在进程退出且解析后确认属于本 run 根目录才删除。

不要自动化当前必须交互式 `getpass` 的 `create-admin` CLI。新增仅供 live 测试的 `production_live_harness.py`，显式提供 `preflight`、`seed` 和 `cleanup` 子命令：它再次解析并拒绝非 loopback、不同 host/port/schema、非 MySQL 8.0/8.4 或非 `clsen_data_test*` URL，并要求数据库除显式允许的 schema/bootstrap 配置外没有业务事实。preflight 只允许清理用户名带保留前缀、run ID 格式合法且可证明来自已过期 live run 的陈旧账号及其事实；一旦发现普通管理员、普通用户或非 live 业务数据立即拒绝，绝不为了跑测试删除用户数据。

清理合法陈旧 live 数据后，seed helper 直接调用既有 `create_administrator()` 创建本 run admin。global setup 先用该管理员登录，再通过真实 admin-management API 创建同 run ID 的 `data_manager` 和 `viewer`，把三个用户 ID、会话和所有业务根 ID 写入本 run 私有清单，并为三种角色分别生成独享 browser storageState；程序生成的 XLSX fixture 也只写入 runner 已创建的 fixture 目录。三个随机密码只存在于 ACL 收紧的临时凭据文件，不写 stdout、日志或命令行，完成三次登录后立即删除。global teardown 先撤销本 run 会话；无论 setup/test/teardown 在何处失败，runner 的 `finally` 都在服务器停止后调用 cleanup helper，以测试迁移账号按依赖顺序只删除清单或保留前缀证明属于本 run 的管理员、`data_manager`、`viewer`、会话、审计/命令和业务事实。重复 seed、部分失败、陈旧 run 和 cleanup 均有单测；任何目标不能证明属于本 run 时 fail closed，不能清理普通开发库、既有账号、用户事实或共享 storage。

Playwright 完成“批准 P0 目录 fixture → 从 production 选择既有 SKU/绑定工厂 alias → 上传并确认订单 → 断言 D+7 窗口 → 下载并核对工厂导出 v1 → 在 P0 创建向前纠错 revision → 历史订单快照仍关联旧 revision”，全程禁止 `page.route()` mock。此时 production `0023` 只承诺可在可丢弃数据库独立体验。

```powershell
.\scripts\run-production-live-e2e.ps1 -Milestone Orders
```

Expected: PASS；默认 `pnpm exec playwright test` 不收集 live spec，专用脚本使用真实 React → FastAPI → MySQL 链路且运行账号权限验证通过；已有开发服务器、普通管理员或非 live 数据只会触发安全拒绝，不会被复用、删除或终止。

这是必须保存证据的顺序里程碑门：记录 P0 目录版本、测试收集清单、`0023` 精确 head、runner/run ID、关键导出 checksum 和 PASS 日志，确认用户能独立体验订单模块后，才开始 Task 8。Task 8 会把 production 最低 head 提升到 `0024`；最终工作树不承诺再次连接纯 production `0023`。

---

## Milestone B：完工审核与广州成品仓

### Task 8: 迁移 0024——完工、入库和库存流水

**Files:**

- Create: `backend/alembic/versions/0024_finished_goods_receipts.py`
- Modify: `backend/tests/contracts/test_migration_contract.py`
- Modify: `backend/tests/integration/test_migrations.py`
- Create: `backend/tests/integration/test_finished_goods_schema.py`
- Modify: `backend/tests/integration/test_production_runtime_permissions.py`
- Modify: `backend/app/cli.py`
- Modify: `backend/tests/unit/auth/test_admin_cli.py`
- Modify: `scripts/database-privileges.json`
- Modify: `scripts/prepare-production-test-database.ps1`
- Modify: `backend/tests/unit/test_mysql_safety_gate.py`
- Modify: `backend/tests/contracts/test_database_bootstrap_script.py`

**Interfaces:**

- Consumes: `0023` 对 P0 SKU/SKU revision 的冻结引用，以及 production 订单、订单明细快照、仓库、命令 claim 和成功 effect；SKU 身份本身仍由 `0022` P0 拥有。
- Produces: `completion_imports`、`completion_import_rows`、`finished_goods_receipts`、`finished_goods_receipt_lines`、`inventory_ledger`、`inventory_balances`。批次保存解析状态、活动文件去重键以及本次上传的安全原文件名/声明媒体类型快照；完工行及入库明细保存工厂回传的导出版本/订单修订号、订单行的 `sku_revision_id` 和字段快照；入库单头及冲销流水保存创建它们的 `operation_token`。

- [ ] **Step 1: 写迁移和 MySQL 约束失败测试**

状态必须与规格一致。约束固定包括：一条完工来源行最多一条入库明细；一个入库明细最多一条 `receipt` 和一条 `reversal` 流水；`reversal_of_ledger_id` 唯一；`finished_goods_receipts` 的 `(site_id, operation_token)` 唯一，冲销流水的 `(site_id, operation_token)` 唯一；余额按 `(site_id, warehouse_id, sku_id)` 唯一且非负；上传数量为正；流水变化非零。`completion_imports` 持久化 `parse_error_code` 和 `parse_failure_recoverable`，状态组合规则与订单导入相同；`completion_import_rows` 保存 `validation_schema_version` 和 32 字节 `validation_digest`；`validated | ready_for_review | approved | rejected | reversed` 行必须两者非空，尚未校验的行允许为空。批次使用生成列 `active_raw_file_id = NULL`（withdrawn）或 `raw_file_id`（其他状态），唯一约束为 `(site_id, active_raw_file_id)`，从而允许撤回后重传。批次、来源行、订单、订单明细、SKU、SKU 修订、仓库、入库明细、流水、命令和 effect 全部使用复合站点外键。管理员密码重置 CLI 的允许 schema head 同步推进到 `0024`，并测试 `0024` 通过及其他 head 安全拒绝。

- [ ] **Step 2: 实现 0024 及保守降级**

创建顺序为上传批次、上传行、入库单、入库明细、库存流水、库存余额；上传批次复制本次上传的安全原文件名和声明媒体类型，resume 不从可能被其他相同内容上传复用的 `raw_files` 元数据取值。上传行与入库明细保存 `reported_factory_export_version`、`reported_order_revision`，并复制订单明细的 `sku_revision_id`、展示编码、款号、颜色、尺码及工厂编码快照，不能通过联查当前 `product_skus` 重写历史展示。完成批次解析状态、活动去重生成列、warning JSON schema/version、`validation_digest` schema/version、operation token 唯一键和复合站点候选键。降级逆序执行，任一业务行存在时抛出 `0024 downgrade refused`。

- [ ] **Step 3: 更新最小授权**

上传批次、上传行、入库单状态和余额进入最小 mutable insert/update；入库明细、库存流水、SKU 行快照和命令 effect 为 insert-only，运行时无 DELETE。清单更新后只允许对名称匹配 `clsen_data_test*` 的可丢弃测试库同步授权，普通开发库和生产库不得由计划自动变更。同时把安全准备脚本的唯一受支持目标从 `0023` 切换为 `0024`；最终工作树对 `-Revision 0023` 必须在 Alembic 和授权同步前返回稳定的历史里程碑不受支持错误，不能拿已经包含 0024 表的 privilege manifest 去碰纯 0023 schema。单测证明 `0024` 精确传入授权同步，而 `0023` 零 DDL、零 grant 副作用。

- [ ] **Step 4: 运行契约、迁移和约束测试**

沿用 Task 2 已验证的三个测试 URL 和 caller-owned grant-admin option file；实际数据库名、loopback host、端口及 runtime/backup 用户继续从 URL 派生，必须指向同一个名称匹配 `clsen_data_test*` 的已存在可丢弃 schema。先由安全准备脚本临时使用测试迁移 URL 升级并把授权同步到精确解析的用户/实例，最后让最小运行账号以原生 SQL 探测新增 0024 表权限，并回归已经存在的订单 API；不能裸跑读取常驻 `APP_MIGRATION_DATABASE_URL` 的 Alembic。完整 completion repository/API 此时尚未实现，其权限证据分别由 Task 9 和 Task 11 提供。

```powershell
.\.venv\Scripts\python.exe -m pytest backend/tests/contracts/test_migration_contract.py backend/tests/contracts/test_database_bootstrap_script.py backend/tests/unit/auth/test_admin_cli.py -q
.\.venv\Scripts\python.exe -m ruff check --config backend/pyproject.toml backend/alembic/versions/0024_finished_goods_receipts.py
.\.venv\Scripts\python.exe -m ruff format --check --config backend/pyproject.toml backend/alembic/versions/0024_finished_goods_receipts.py
.\scripts\prepare-production-test-database.ps1 -Revision 0024
.\.venv\Scripts\python.exe -m pytest backend/tests/integration/test_migrations.py --require-mysql -q
.\.venv\Scripts\python.exe -m pytest backend/tests/integration/test_finished_goods_schema.py backend/tests/integration/test_production_runtime_permissions.py backend/tests/integration/test_production_orders_api.py --require-mysql -q
git diff --check -- (Get-Content -Raw -LiteralPath .\docs\superpowers\plans\2026-08-18-finished-goods-production-receipt-file-manifest.json | ConvertFrom-Json)
```

Expected: PASS；schema/DDL 断言使用 `APP_TEST_DATABASE_URL` 的迁移账号；新增 0024 表用 `APP_TEST_RUNTIME_DATABASE_URL` 做原生允许/拒绝 SQL 探针，既有订单 API 以同一最小运行账号回归，并证明运行账号无 DELETE/DDL。Task 9/11 实现后再由真实 completion repository/API 证明业务权限足够。

### Task 9: 完工上传、SKU 匹配和确定性校验

**Files:**

- Modify: `backend/app/production/types.py`
- Modify: `backend/app/production/upload_service.py`
- Create: `backend/app/production/completion_repository.py`
- Create: `backend/app/production/completion_service.py`
- Create: `backend/tests/unit/production/test_completion_validation.py`
- Create: `backend/tests/unit/production/test_completion_service.py`
- Create: `backend/tests/integration/test_completion_import_workflow.py`

**Interfaces:**

- Consumes: `CurrentSiteContext`、认证 actor、`ParsedCompletionWorkbook`、订单事实、SKU 解析、历史完工候选和文件摘要。
- Produces: `CompletionService.create_or_resume_preview(context, actor_user_id, command, workbook) -> CompletionImportView`、`resume_parse(context, actor_user_id, command) -> CompletionImportView`、`resolve_matches(context, actor_user_id, command) -> CompletionImportView`、`submit(context, actor_user_id, command) -> CompletionImportView`、`withdraw(context, actor_user_id, command) -> CompletionImportView`、`get_import(context, import_id, page) -> CompletionImportView`、`list_imports(context, filters) -> CompletionImportPage`、`list_review_lines(context, filters) -> CompletionReviewLinePage`。

- [ ] **Step 1: 写状态和原因码失败测试**

```python
class CompletionImportStatus(StrEnum):
    UPLOADED = "uploaded"
    NEEDS_ATTENTION = "needs_attention"
    VALIDATED = "validated"
    PENDING_REVIEW = "pending_review"
    PARTIALLY_REVIEWED = "partially_reviewed"
    COMPLETED = "completed"
    WITHDRAWN = "withdrawn"

class CompletionLineStatus(StrEnum):
    NEEDS_MATCH = "needs_match"
    INVALID = "invalid"
    VALIDATED = "validated"
    READY_FOR_REVIEW = "ready_for_review"
    APPROVED = "approved"
    REJECTED = "rejected"
    REVERSED = "reversed"
```

断言所有阻断码和警告码与规格逐字一致。

阻断码固定为：

```text
missing_required_field
invalid_date
invalid_quantity
unsupported_factory_order_export_version
factory_order_revision_not_found
order_not_found
order_cancelled
sku_unmatched
sku_ambiguous
sku_not_on_order
line_already_posted
permission_denied
```

警告码固定为：

```text
completion_overage
possible_duplicate
order_closed
sku_attribute_mismatch
stale_factory_order_revision
```

- [ ] **Step 2: 实现纯校验函数**

`validate_completion_row(row, facts) -> CompletionDecision` 必须区分错误和警告；语义重复键固定为 `(order_line_id, sku_id, completion_date, quantity)`。只接受 `production_factory_order_v1`，回传订单 revision 必须在该订单历史中存在且不大于当前 revision；早于当前 revision 返回 `stale_factory_order_revision` 警告，并继续用当前有效下单量判断超额。关闭订单是警告，取消订单是阻断。进入 `validated` 时按带 schema version 的规范 JSON 生成 SHA-256 `validation_digest`，至少绑定站点/批次/行、规范原始值、工厂导出版本/订单 revision、订单及明细 revision、`sku_id/sku_revision_id`、匹配来源、全部校验原因码和排序后的警告代码/事实；任何一项变化都使摘要变化。

- [ ] **Step 3: 扩展生产上传 finalizer**

同一原文件可在内容存储复用；完工领域只对未撤回批次的 `(site_id, raw_file_id)` 活动键唯一。若存在活动批次则返回它；若历史批次均已撤回则创建新批次。扩展名/MIME 预检仍在 raw file/批次创建前完成，错误元数据不占活动键。使用解析 claim 保存全部原始证据、匹配、订单行 `sku_revision_id`、字段快照和决策；解析失败不产生部分行并进入 `parse_failed`。公开 resume 命令从批次的不可变 `raw_file_id` 重取内容，并结合批次自己的原文件名/媒体类型快照重建 `WorkbookUpload`；`uploaded` 可直接取得 claim，`parsing` 必须租约已过期，`parse_failed` 必须标记为可恢复，`parsed` 幂等返回现有结果而不重跑。GET 只查询，不能把卡住批次留成只有后台内部方法才能推进。测试两个并发上传只得到一个活动批次、相同内容不同元数据不会串用、错误元数据零落库后以正确元数据重传、“撤回 → 同文件重传 → 新批次 ID”，以及上传提交后进程退出 → UI 调用 resume → 原批次完成解析且不重复行。

- [ ] **Step 4: 实现匹配、提交和撤回**

匹配先读取系统订单号、工厂导出版本和订单修订号，在该订单内按 `factory_sku_code_snapshot` 唯一匹配，再使用 `factory_completion_excel` 别名和当前展示编码；订单快照与全局别名冲突时阻断。命中订单行后，完工行保存工厂回传 revision 证据，并复制该订单行的 `sku_revision_id` 和属性快照，而不是当前 SKU 修订；当前修订只用于提示已发生档案纠错。校验通过的行先保存为 `validated`，批次进入 `validated`。提交审核不接受行选择：只有批次不存在 `needs_match/invalid` 时，服务端才复读所有 `validated` 行并复算 `validation_digest`，摘要全部相等后原子转换全部合法行为 `ready_for_review`；任何摘要变化返回 `409 stale_completion_validation` 且零状态变化。有问题的批次保持 `needs_attention`，用户须修正匹配、撤回或重传，不能制造“部分已提交、部分仍 validated”的无定义状态。首次批准前只允许上传者撤回；`admin` 代撤回必须提供原因并单独审计，普通 `data_manager` 不能撤回他人批次。撤回后原批次不能提交或审核，但活动文件去重键被释放。

- [ ] **Step 5: 运行完工导入测试**

```powershell
.\.venv\Scripts\python.exe -m pytest backend/tests/unit/production/test_completion_validation.py backend/tests/unit/production/test_completion_service.py -q
.\.venv\Scripts\python.exe -m pytest backend/tests/integration/test_completion_import_workflow.py --require-mysql -q
git diff --check -- (Get-Content -Raw -LiteralPath .\docs\superpowers\plans\2026-08-18-finished-goods-production-receipt-file-manifest.json | ConvertFrom-Json)
```

Expected: PASS。

### Task 10: 审核入账、并发幂等和冲销

**Files:**

- Modify: `backend/app/production/types.py`
- Modify: `backend/app/production/command_repository.py`
- Modify: `backend/app/production/command_service.py`
- Modify: `backend/app/production/completion_repository.py`
- Modify: `backend/app/production/completion_service.py`
- Modify: `backend/app/production/order_repository.py`
- Create: `backend/app/production/inventory_queries.py`
- Create: `backend/tests/unit/production/test_inventory_calculations.py`
- Create: `backend/tests/integration/test_finished_goods_posting.py`
- Create: `backend/tests/integration/test_finished_goods_concurrency.py`
- Modify: `backend/tests/integration/test_production_command_recovery.py`

**Interfaces:**

- Consumes: `CurrentSiteContext`、认证 actor、`PreviewCompletionReviewCommand`、`ReviewCompletionCommand`、逐行批准/拒绝决定、`projection_digest`、逐警告 `{code, fingerprint}` 确认、`expected_revision` 和 UUID v4。
- Produces: `CompletionService.preview_review(context, actor_user_id, command) -> ReviewProjection`、`review(context, actor_user_id, command) -> CompletionImportView`、`reverse(context, actor_user_id, command) -> ReversalResult`、`InventoryQueries.get_receipt(context, receipt_id) -> FinishedGoodsReceiptView`、`list_inventory(context, query) -> InventoryPage`、`list_ledger(context, query) -> InventoryLedgerPage`，并让订单查询用同一 context 返回正式进度和生产窗口。

- [ ] **Step 1: 写数量公式和警告复核失败测试**

```python
remaining = max(ordered_quantity - approved_quantity, 0)
overage = max(approved_quantity - ordered_quantity, 0)
```

待审核数量单独计算。审核预检先按订单明细分组，再用“当前有效累计完工 + 本命令按来源行 ID 排序的选中批准量”计算投影；例如当前 0、同一命令批准 `60 + 60`、订单 100 时，第二行必须产生超额警告。响应的 `projection_digest` 对带 schema version 的规范 JSON 计算 SHA-256，至少绑定 `site_id`、批次 ID/revision、规范化完整决定集合、每行 `validation_digest`、订单/订单明细/SKU/具体 SKU revision、当前有效累计完工、排序后的重复候选稳定 ID 集合和每条警告指纹。每个 `warning_fingerprint` 自身也至少覆盖订单和订单明细 revision、`sku_id/sku_revision_id`、当前有效累计量、相关疑似重复行 ID、同行 ID/数量、订单状态以及产生该警告的字段值，不能只依赖外层 projection。正式批准在锁内重放同一投影并精确比较摘要；schema、站点、选择、批准/拒绝决定、事实数值、候选集合、行校验摘要或警告任一变化都返回 `409 stale_review_projection`，且零业务副作用。

- [ ] **Step 2: 写原子入账和回滚集成失败测试**

选中多行时锁定命令、批次、来源行、生产订单头、订单明细、所引用的 P0 SKU 和余额，在锁内重放审核预检的整组投影。任一行最终校验失败，入库单、入库明细、流水、余额、审核状态、command effect 和审计全部不提交。集成测试覆盖同命令 `60 + 60 > 100`、不同批次 `60 + 60 > 100`、预检后增删或改变任一决定导致旧 `projection_digest` 失效，并并发执行批准 × 调量、批准 × 关闭、批准 × 取消和批准 × P0 向前目录纠错，不能得到取消订单带有效入库或过期警告确认；目录变化不允许 production 写回 P0，历史订单仍固定旧 revision。

- [ ] **Step 3: 实现批准与拒绝事务**

稳定锁顺序为命令 UUID、批次 ID、来源行 ID、订单头 ID、订单明细 ID、SKU ID、余额 `(warehouse_id, sku_id)`；所有集合先去重再排序。批准创建一张带本次 `operation_token` 的入库单和多条明细/流水，入库明细复制订单行 SKU 修订快照；拒绝必须有非空原因且不写库存。批准或纯拒绝命令都写唯一 command effect，批次状态按剩余待审核行重算。

- [ ] **Step 4: 实现幂等和并发保护**

相同 UUID/摘要恢复同一结果；相同 UUID/不同摘要冲突；不同 UUID 并发审核同一行只有一个成功。production 领域明确识别 MySQL 错误码 `{1205, 1213}`，包含首次尝试在内最多 4 次；三次重试前退避固定为 50 ms、100 ms、200 ms，每次都重新开启事务、重新取得租约/最新 fencing token 并按稳定顺序加锁，其他数据库错误不进入该循环；不得声称复用仓库中并不存在的共享重试器。第 4 次仍失败时返回稳定原因码 `database_contention_retry_exhausted` 且不写部分业务事实：已证明无效果时命令为可用原 UUID 重放的 `retryable`，提交结果无法证明时为 `outcome_unknown`。审核或冲销提交回执不确定时进入 `outcome_unknown`：reconciler 找到 receipt/reversal 的 operation token 或 command effect 时转 `completed`，找不到且租约过期时转 `retryable`。集成测试分别强制 1205、1213、重试后成功、4 次耗尽并逐次断言退避、“COMMIT 成功但响应丢失”和“业务事务回滚”，断言前者恢复原结果，耗尽或回滚分支只允许原 UUID/摘要安全重试且不产生部分入库。

- [ ] **Step 5: 实现管理员冲销**

冲销锁定原入库明细和余额，写带唯一 `operation_token`、数量相反的 `reversal` 流水，更新来源完工行状态并重算订单进度。相同命令不重复冲销；曾经批准过的订单即使全部冲销也不能取消。订单数量变更在本任务起必须重新查询当前有效累计完工量，调整后数量小于该值时返回 409。每个集成场景断言 `inventory_balances = SUM(inventory_ledger) = SUM(未冲销入库明细)`；失败命令的业务表、effect 和审计均零副作用。

- [ ] **Step 6: 运行入账、并发和回归测试**

```powershell
.\.venv\Scripts\python.exe -m pytest backend/tests/unit/production/test_inventory_calculations.py -q
.\.venv\Scripts\python.exe -m pytest backend/tests/integration/test_finished_goods_posting.py backend/tests/integration/test_finished_goods_concurrency.py --require-mysql -q
git diff --check -- (Get-Content -Raw -LiteralPath .\docs\superpowers\plans\2026-08-18-finished-goods-production-receipt-file-manifest.json | ConvertFrom-Json)
```

Expected: PASS；零重复流水、零部分库存。

### Task 11: 完工审核与库存 API 契约

**Files:**

- Create: `backend/app/api/production_completions.py`
- Create: `backend/app/api/production_inventory.py`
- Modify: `backend/app/main.py`
- Create: `backend/tests/unit/test_production_completions_api.py`
- Create: `backend/tests/unit/test_production_inventory_api.py`
- Modify: `backend/tests/unit/test_production_commands_api.py`
- Create: `backend/tests/integration/test_production_completions_api.py`
- Modify: `backend/tests/unit/test_openapi_contract.py`
- Regenerate: `frontend/src/api/generated.ts`

**Interfaces:**

- Consumes: Task 9/10 服务。
- Produces: `GET /api/production/templates/completion-receipt`、`GET/POST /api/production/completion-imports`、`GET /api/production/completion-imports/{import_id}`、`POST /api/production/completion-imports/{import_id}/resume`、`POST /api/production/completion-imports/{import_id}/matches`、`POST /api/production/completion-imports/{import_id}/submit`、`POST /api/production/completion-imports/{import_id}/withdraw`、`POST /api/production/completion-imports/{import_id}/review-preview`、`POST /api/production/completion-imports/{import_id}/review`、`GET /api/production/completion-review-lines`、`GET /api/production/receipts/{receipt_id}`、`POST /api/production/receipt-lines/{receipt_line_id}/reverse`、`GET /api/production/inventory`、`GET /api/production/inventory/ledger`。集合、批次行、待办行和流水均服务端分页。

- [ ] **Step 1: 写请求模型和权限失败测试**

上传路由与订单上传相同，必须在内容存储前预检扩展名/MIME，错误元数据零落库。提交审核请求只含批次 `expected_revision`，不接受行 ID；服务端必须按 Task 9 一次提交该批次全部 `validated` 行，并在 `validation_digest` 过期时返回 `409 stale_completion_validation`。解析 resume 只允许同站点写角色调用，要求 CSRF、UUID v4 和 `expected_revision`，并从已存 raw file 幂等推进原批次；`uploaded`、过期 `parsing` 和 recoverable `parse_failed` 按契约恢复。`parsed` 对新的合法 UUID 也只返回现有结果、不重跑，但仍取得 production command claim，并写恰好一条指向既有 import/revision 的 no-op/idempotent effect；它不取得解析 claim，新 UUID 可从 commands GET 恢复且不得被其他语义复用。审核预检和正式审核使用完全相同的 1～500 条不重复决定数组。预检返回规范决定集合对应的 `projection_digest`、投影数量和服务端警告；正式请求固定包含 `expected_revision`、该 `projection_digest`，以及每条批准决定的 `acknowledged_warnings: [{code, fingerprint}]`。schema、站点、决定、事实或警告指纹任一变化固定返回 `409 stale_review_projection`；拒绝决定必须有原因。入库单详情按站点返回头、行、工厂导出版本/订单修订号证据、SKU 修订快照、来源 `import_id/import_row_id/order_id/order_line_id`、原 receipt/reversal 流水定位符；撤回测试区分上传者、其他 `data_manager` 和 `admin` 代撤回，冲销路由只允许 `admin`。

- [ ] **Step 2: 实现路由和安全错误映射**

GET 使用 `require_roles("admin", "data_manager")`；普通写操作使用 `require_write_roles("admin", "data_manager")`；服务层继续校验资源所属站点和撤回 owner；冲销使用 `require_write_roles("admin")`。响应不返回绝对存储路径、SQL 或堆栈。对所有路由执行角色 × 跨站 IDOR 参数化测试。

- [ ] **Step 3: 写完整 API 集成流程**

使用 `APP_TEST_RUNTIME_DATABASE_URL` 启动 FastAPI，覆盖“上传多订单完工 → 从待办列表发现批次 → 处理 SKU → 提交 → 预检决定集合 → 确认指纹 → 部分批准/拒绝 → 从流水 GET 入库单并回溯上传行/订单 → 管理员冲销 → 进度恢复”，以及上传后解析崩溃并显式 resume、`parsed` 后以新 UUID resume 只写 command effect 且零解析 claim/零重复行、同 UUID 重试仍只有一个 effect并可由 commands GET 恢复、选择变化使 `projection_digest` 失效、撤回后同文件重传、警告事实变化但代码不变、命令已提交丢回执后归并 completed、命令回滚后归并 retryable 并以原 UUID 恢复。迁移账号只负责测试库建表和清理，应用请求不得回退使用迁移账号。

- [ ] **Step 4: 重新生成 OpenAPI 客户端并验证**

```powershell
.\scripts\generate-api-client.ps1
.\.venv\Scripts\python.exe -m pytest backend/tests/unit/test_production_completions_api.py backend/tests/unit/test_production_inventory_api.py backend/tests/unit/test_production_commands_api.py backend/tests/unit/test_openapi_contract.py -q
.\scripts\generate-api-client.ps1 -Check
.\.venv\Scripts\python.exe -m pytest backend/tests/integration/test_production_completions_api.py --require-mysql -q
git diff --check -- (Get-Content -Raw -LiteralPath .\docs\superpowers\plans\2026-08-18-finished-goods-production-receipt-file-manifest.json | ConvertFrom-Json)
```

Expected: 无参数命令先生成客户端，契约与集成测试 PASS，`-Check` 证明生成物稳定。

### Task 12: 完工上传和人工审核前端

**Files:**

- Modify: `frontend/src/features/production/productionTypes.ts`
- Modify: `frontend/src/features/production/productionApi.ts`
- Create: `frontend/src/features/production/CompletionImportsPage.tsx`
- Create: `frontend/src/features/production/CompletionReviewQueuePage.tsx`
- Create: `frontend/src/features/production/CompletionReviewPage.tsx`
- Create: `frontend/src/features/production/CompletionImportsPage.test.tsx`
- Create: `frontend/src/features/production/CompletionReviewQueuePage.test.tsx`
- Create: `frontend/src/features/production/CompletionReviewPage.test.tsx`
- Modify: `frontend/src/features/production/ProductionLayout.tsx`
- Modify: `frontend/src/features/production/ProductionWorkspace.css`

**Interfaces:**

- Consumes: Task 11 的完工 API。
- Produces: `/production/completions`、`/production/completion-reviews` 和 `/production/completions/:importId/review`。

- [ ] **Step 1: 写四步上传流程失败测试**

断言页面依次展示“选择文件、自动校验、处理错误和警告、提交审核”，刷新后通过 GET 恢复服务端批次，不能只依赖 React 内存状态。GET 返回 `uploaded`、租约过期的 `parsing` 或可恢复 `parse_failed` 时显示“恢复解析”，沿用该 resume 命令的 UUID 直到得到终态；恢复从服务端已存原文件读取，不要求用户重新选择本地文件。不可恢复的工作簿错误只显示原因和重传入口。

- [ ] **Step 2: 实现上传、匹配、提交和撤回**

表格定位原始行号，错误和警告显示稳定中文。未知 SKU 可选择当前批准 P0 目录中的 SKU；若目录中不存在目标身份，则链接到 `/catalog` 创建并批准后继版本，返回后重新解析，production 页面和 API 均不新建 SKU。批次仍有阻断行时禁用“提交审核”；消除全部阻断后一次提交全部 `validated` 行，不提供局部提交选择。`stale_completion_validation` 时刷新逐行校验且不伪装为已提交。首次批准后隐藏撤回操作。

- [ ] **Step 3: 写部分审核和警告确认失败测试**

超额、疑似重复、关闭订单、属性冲突和 `stale_factory_order_revision` 必须逐项勾选确认。用户每次增删行、切换批准/拒绝或修改拒绝原因后，前端都清空旧警告确认与 `projection_digest`，重新调用 `review-preview`；只有当前决定集合的预检返回后才能勾选服务端警告并提交，前端不能自行计算 fingerprint。拒绝必须填写原因；没有决定的行保持待审核。测试同订单两行 `60 + 60 > 100`、选择变化触发新摘要、旧摘要不能提交。

- [ ] **Step 4: 实现服务端分页待办队列**

独立页面按批次状态、上传人、日期、订单号和 SKU 查询待审核行；分页、总数和筛选来自服务端。点击待办进入批次审核详情，刷新和跨页选择不能丢失已保存的服务端状态。单次提交最多 500 行。

- [ ] **Step 5: 实现审核页面和冲突恢复**

提交 409 时重新 GET，保留仍存在的本地选择但丢弃全部旧 `projection_digest` 和警告勾选，再对当前集合执行 review-preview；新出现、消失或 fingerprint 改变的警告都必须重新确认。重复点击按钮期间禁用命令，但最终幂等依赖服务端；网络错误或刷新继续保留原 operation token，并通过命令 GET 的 `completed/retryable` 结果恢复。

- [ ] **Step 6: 运行前端聚焦测试**

```powershell
Set-Location frontend
pnpm test --run src/features/production/CompletionImportsPage.test.tsx src/features/production/CompletionReviewQueuePage.test.tsx src/features/production/CompletionReviewPage.test.tsx
pnpm lint
pnpm typecheck
Set-Location ..
git diff --check -- (Get-Content -Raw -LiteralPath .\docs\superpowers\plans\2026-08-18-finished-goods-production-receipt-file-manifest.json | ConvertFrom-Json)
```

Expected: PASS。

### Task 13: 广州成品仓、订单进度和完整模块导航

**Files:**

- Create: `frontend/src/features/production/FactoryInventoryPage.tsx`
- Create: `frontend/src/features/production/FactoryInventoryPage.test.tsx`
- Create: `frontend/src/features/production/FinishedGoodsReceiptDetailPage.tsx`
- Create: `frontend/src/features/production/FinishedGoodsReceiptDetailPage.test.tsx`
- Modify: `frontend/src/features/production/ProductionOrderDetailPage.tsx`
- Modify: `frontend/src/features/production/ProductionOrderDetailPage.test.tsx`
- Modify: `frontend/src/features/production/ProductionLayout.tsx`
- Modify: `frontend/src/features/production/ProductionWorkspace.css`
- Modify: `frontend/src/app/App.tsx`
- Modify: `frontend/src/app/App.test.tsx`

**Interfaces:**

- Consumes: 库存余额、库存流水、入库单详情和正式订单进度 API。
- Produces: `/production/inventory`、`/production/receipts/:receiptId`，以及模块内“商品目录选择、生产订单、完工上传、完工审核、广州成品仓”五个入口；“商品目录选择”只读消费 P0 身份并维护 production alias，“完工审核”进入 `/production/completion-reviews` 服务端待办队列，不依赖用户记住 import ID。

- [ ] **Step 1: 写库存余额和流水失败测试**

断言按 SKU 搜索，显示当前库存、累计入库和最近流水；每条流水携带 `receipt_id` 并链接 `/production/receipts/:receiptId`。入库单页显示头、行、当时的 SKU 修订快照、来源完工上传行和生产订单链接，以及原流水/冲销流水关系；跨站 receipt ID 返回安全无权/不存在状态。冲销显示为独立负向流水，不能覆盖原记录。

- [ ] **Step 2: 实现库存页面**

余额和流水分页由服务端权威返回。实现入库单只读详情路由，来源 import 行链接到 `/production/completions/:importId/review` 并带行定位信息，订单链接到 `/production/orders/:orderId`。桌面使用紧凑表格；390px 与 768px 仅表格内部横向滚动，页面根节点无横向溢出。

- [ ] **Step 3: 更新订单详情正式进度**

每行显示下单、待审核、累计完工、未完工和超额；订单同时显示单据状态、派生完工状态和基于站点自然日的 `not_due | in_window | overdue`，无未完工量或已取消时窗口状态为空，不把关闭显示成已完工。

- [ ] **Step 4: 完成导航和权限路由测试**

`admin/data_manager` 看见“生产入库”，`viewer` 不看见且直接访问任一生产路由都回首页。管理员额外看见冲销操作，`data_manager` 不渲染冲销按钮。

- [ ] **Step 5: 运行完整前端单测和构建**

```powershell
Set-Location frontend
pnpm test --run
pnpm lint
pnpm typecheck
pnpm build
Set-Location ..
git diff --check -- (Get-Content -Raw -LiteralPath .\docs\superpowers\plans\2026-08-18-finished-goods-production-receipt-file-manifest.json | ConvertFrom-Json)
```

Expected: PASS。

### Task 14: 端到端验收、体验文档和全量回归

**Files:**

- Create: `frontend/tests/e2e/live/production-finished-goods.live.spec.ts`
- Modify: `frontend/tests/e2e/live/global-setup.ts`
- Modify: `frontend/tests/e2e/live/global-teardown.ts`
- Modify: `frontend/tests/e2e/live/liveFixtures.ts`
- Create: `backend/tests/integration/test_production_efficiency.py`
- Create: `backend/tests/integration/test_production_backup_restore.py`
- Modify: `backend/tests/integration/conftest.py`
- Modify: `backend/tests/unit/test_mysql_safety_gate.py`
- Modify: `backend/app/maintenance/backup.py`
- Modify: `backend/app/maintenance/restore.py`
- Modify: `backend/tests/unit/maintenance/test_backup.py`
- Modify: `backend/tests/unit/maintenance/test_restore.py`
- Create: `backend/tests/contracts/test_production_mysql_integration_runner.py`
- Modify: `.github/workflows/compatibility.yml`
- Modify: `scripts/test-mysql-matrix.ps1`
- Create: `scripts/run-production-mysql-integration.ps1`
- Modify: `scripts/run-production-live-e2e.ps1`
- Create: `scripts/check-worktree-text.ps1`
- Create: `scripts/check-plan-worktree-baseline.ps1`
- Modify: `.env.example`
- Create: `docs/user-guide/production-finished-goods-demo.md`
- Modify: `docs/user-guide/stage9-local-demo.md`
- Modify: `docs/operations/local-maintenance.md`
- Modify: `docs/superpowers/plans/2026-08-18-finished-goods-production-receipt-file-manifest.json`
- Modify: `docs/superpowers/plans/2026-08-18-finished-goods-production-receipt-implementation.md`（只勾选实际完成步骤并记录真实测试结果）

**Interfaces:**

- Consumes: 两个里程碑的完整 API 和 UI。
- Produces: 可重复的本机体验路径和最终验收证据。

- [ ] **Step 1: 写端到端成功与异常流程**

专用 live Playwright 只覆盖真实用户能通过正式页面触发并观察的核心链路：先在 P0 `/catalog` 正式流程批准包含两个 SKU 的目录 V1，再从 production 选择它们、绑定 production alias、上传多 SKU 订单、核对固定 v1 工厂生产订单 XLSX、用相对当前业务日的订单日期核对 D+6/7/30/31 窗口，并在 P0 批准向前纠错后核对历史订单快照；随后由 `data_manager` 上传包含导出版本/订单修订号及多个订单的完工表，在页面处理一个未知 SKU、提交并从待办队列进入审核，确认旧 revision/超额警告，完成部分批准/拒绝，核对广州库存、流水、入库单和上传行/订单回溯；最后由 `admin` 从正式页面冲销一条入库明细并核对库存与订单进度恢复。所有事实必须经真实 React → FastAPI → MySQL 用户流程创建，账号 seed 之外不得用 helper 直写业务表；production 侧身份增量必须为零。

解析进程崩溃、MySQL 1205/1213 与重试耗尽、COMMIT 成功但回执丢失、命令状态标记丢失、`completed/retryable/outcome_unknown` 收敛、并发重放，以及通过改变 schema/site/摘要内部字段制造 stale 的分支，留在 Tasks 6、9、10、11 的 API/MySQL integration 测试；live 不重复故障注入。严禁为 live 新增 test-only endpoint、特殊请求头、生产运行时故障开关、隐藏前端入口或直接数据库篡改，也不允许 `page.route()` mock。UI 无法通过正式操作建立的前置条件不属于 live 验收。默认 Playwright 配置继续运行既有完整 mock/UI 套件并明确排除 live 目录；所有 `*.live.spec.ts` 只由 `playwright.live.config.ts` 连接 runner 独占的真实服务执行，二者不能混称。

Task 14 把 runner 的最终最低 head 明确提升到 `0024`：`-Milestone Orders` 只在当前 `0024` 上重跑订单用户旅程，`-Milestone All` 在 `0024` 上运行订单和完工入库两条旅程；两者都不得尝试让最终 repository、权限清单或 UI 连接纯 `0023`。Task 7 保存的 `0023` PASS 证据仍作为里程碑 A 的验收记录，不被最终 head 的回归替代。

- [ ] **Step 2: 写权限和响应式端到端测试**

验证 `viewer` 无导航和路由访问，`data_manager` 无冲销；验证 1440px、768px、390px 无整页横向溢出，表格可键盘操作且状态不只依赖颜色。

- [ ] **Step 3: 编写本机体验文档**

文档明确：先备份、升级测试或体验库到新头、启动现有后端和前端、用现有账号进入“生产入库”、依次下载两份模板。文档标题和完成提示使用“第一期：订单到广州成品仓”，并链接全链路路线图，不能声称出货、在途、FBA 或销售退货已完成。命令不得包含真实密码；普通开发库迁移必须由用户明确选择，脚本不自动升级生产库。最终再同步 `docs/operations/local-maintenance.md`：普通人工授权只能显式使用 `-AllowInteractiveCredential`，所有 live/完整回归命令都指向 caller-owned grant-admin option file 和安全 wrapper，删除已经失效的“无参数运行后等待凭据提示”说明。

- [ ] **Step 4: 写并运行批量效率与查询形状测试**

生成 10,000 行工作簿验证上限可解析，10,001 行稳定拒绝；在 1,000 条完工行上断言匹配、预检和库存查询使用批量 SQL，不按行发起 SKU、订单或余额查询。效率测试记录受控环境耗时，但只以查询数量、连接池不耗尽和零重复流水作为稳定门禁。

```powershell
.\.venv\Scripts\python.exe -m pytest backend/tests/integration/test_production_efficiency.py --require-mysql -q
```

Expected: PASS。

- [ ] **Step 5: 验证里程碑升级和备份恢复**

先在当前 `0021` 数据库创建一组相互关联的 `batch_review_runs`、`batch_review_items` 和 `batch_review_commands` 事实；升级 `0022` 后由 P0 fixture 创建款式、SKU、两类 revision、目录成员和当前目录 publication；再升级 `0023` 创建 production alias、命令 effect 和订单；最后升级 `0024`，断言 0021 批量审核关系、P0 identity/revision/catalog ID、唯一订单号、年度序列、订单行快照、工厂导出编码快照和审计均不变。这个跨版本 preservation canary 只能使用本机/矩阵 wrapper 为本 run 预先创建并记录的全新 `clsen_data_test_preservation_<32hex>`；wrapper 同时创建限于该 schema 的临时迁移/备份账号，把不含日志输出的随机凭据仅注入 pytest 子进程的 `APP_TEST_PRESERVATION_DATABASE_URL` 和 `APP_TEST_PRESERVATION_BACKUP_DATABASE_URL`。fixture 再次核对前缀、run ID、loopback host/port、账号分离和 MySQL 版本，从 `0021` 逐头前进；它不调用最终只支持 `0024` 的准备脚本去降级或假装运行纯 0023 应用，也不复用已经位于 0024 的主测试库。

扩展备份工具的当前 schema head 从 `0020` 到 `0024`：`create_backup()` writer 只接受精确当前 head `0024`，对 `0020/0021/0023`、未知或更高 head 都安全拒绝写新 artifact；`restore/verify` 继续兼容读取仓库已经支持的 v1/`0020` 历史 artifact。单元和集成测试必须分别覆盖 `0024` 当前写入成功、旧/未知 writer 拒绝、已知旧 artifact 仍可校验读取，不能把“兼容旧备份”误写成“允许旧 schema 继续产出新备份”。主库 `APP_TEST_BACKUP_DATABASE_URL` 必须与迁移/运行测试 URL 指向同一本机 `clsen_data_test*` schema，但使用独立最小备份账号；preservation canary 只使用 wrapper-owned 的独立 backup URL，两者都不能缺省或回退到迁移账号。

对全部 0021～0024 source-of-truth 表逐表保存并核对行数及规范内容 checksum：`batch_review_runs`、`batch_review_items`、`batch_review_commands`，P0 的 `product_styles/product_style_revisions/product_skus/product_sku_revisions/product_catalog_versions` 及成员/publication/mapping/reservation/audit 事实，以及 production 的 `production_sku_aliases`、`warehouses`、`production_order_sequences`、两类导入及其行、订单及明细/调整、命令 claim/effect、入库单及明细、库存流水和余额。canary 必须逐字段核对三张批量审核表及其 run/item/command 关系，并显式让订单导入和完工导入分别覆盖 `parse_error_code`、`parse_failure_recoverable` 的成功空值、可恢复失败和永久失败组合，恢复后逐字段相等。创建完工入库和冲销后执行加密备份恢复 canary，除 checksum 外执行跨站复合 FK/孤儿检查、来源定位符检查，以及逐 `(site_id, warehouse_id, sku_id)` 的 `inventory_balances = SUM(inventory_ledger) = SUM(未冲销入库明细)` 关系验证。

真实备份/恢复测试不得假设 PyMySQL 或 Docker 已经提供宿主命令行客户端。每个本机/CI job 必须安装或验证与目标 MySQL 8.0/8.4 兼容的宿主 `mysql` 和 `mysqldump`，校验 `--version`，再通过测试专用环境 `APP_TEST_MYSQL_EXECUTABLE`、`APP_TEST_MYSQLDUMP_EXECUTABLE` 的绝对路径传给 `BackupSettings`/`RestoreSettings`，不能依赖默认 `*.exe` 或 PATH 偶然命中。本机 `run-production-mysql-integration.ps1` 和矩阵 wrapper 都先生成 32 位十六进制 verification run ID，创建只可操作其精确 `clsen_restore_<32hex>` 的临时 restore-admin，再把 run ID 与 ACL 仅当前用户可读（POSIX `0600`）的临时 option file 成对注入 pytest 子进程的 `APP_TEST_RESTORE_VERIFICATION_RUN_ID`、`APP_TEST_RESTORE_ADMIN_OPTION_FILE`。option file 保存本 job 的 host、随机端口、临时用户名/密码和 CA 校验参数，凭据不得进入 argv、pytest 输出或日志。

`RestoreSettings` 显式接收该 verification run ID；测试调用不得缺省，`verify_restore()` 只能把它规范化为同一个精确 scratch schema，不能内部另生成 UUID，也拒绝通配或调用者提供完整任意库名。缺省随机 ID 只保留给非测试生产调用。pytest 把 wrapper-owned run ID/option file 当作只读成对输入，不创建账号、不更换 ID、不删除 option file；只验证恢复内容并在正常路径删除自己的 exact scratch schema。wrapper 在 `finally` 中再次依据私有所有权清单清理残留的同一 scratch schema、临时账号、option file 和目录，并恢复自己改写的环境变量；caller-owned grant-admin option file 始终只读且永不删除。任何目标无法与本 run 精确对应就 fail closed，不清理其他 `clsen_restore_*`、其他测试库、调用者凭据或普通 schema。

- [ ] **Step 6: 运行后端非 MySQL 全量检查**

```powershell
.\.venv\Scripts\python.exe -m pytest backend/tests -m "not mysql" -q
Push-Location backend
try {
    ..\.venv\Scripts\python.exe -m ruff check .
    ..\.venv\Scripts\python.exe -m ruff format --check .
    ..\.venv\Scripts\python.exe -m mypy app tests
}
finally {
    Pop-Location
}
```

Expected: PASS；Ruff 从 `backend` 配置根执行，因此 `pyproject.toml` 中对既有已应用迁移的相对 exclude 正确生效，不会要求格式化明确排除的历史迁移。

- [ ] **Step 7: 在可丢弃 MySQL 上运行完整 integration 回归**

`run-production-mysql-integration.ps1` 是本机完整 MySQL 回归的唯一入口。它先只读验证三个主测试 URL、caller-owned `APP_TEST_GRANT_ADMIN_OPTION_FILE`、宿主客户端和服务端版本；再创建私有 run manifest，并生成两个不同随机 ID。wrapper 实际创建 `clsen_data_test_preservation_<32hex>` 及其临时迁移/备份账号和子进程专用 URL；对 `clsen_restore_<32hex>` 只保留精确名称、创建最小 restore-admin 并授予该尚不存在 schema 的精确权限，restore 开始前必须再次证明 schema 不存在。所有随机密码只存在于 ACL 收紧的临时文件/子进程环境，不进 argv、输出或日志。随后 wrapper 对主测试库调用最终 `prepare -Revision 0024`，向同一 pytest 子进程注入成对 preservation/restore 配置并运行完整 `backend/tests/integration --require-mysql`；缺任何成对值都必须失败，测试不得 skip 或自行生成另一 ID。

`finally` 先终止/等待本 run 子进程，再使用 caller-owned grant-admin option file 只撤销并删除私有 manifest 中精确记录的临时账号和两个 exact schema，随后删除 wrapper-owned option file/临时目录并恢复环境。grant-admin 在 provision/cleanup 中只能执行精确名称的账号/授权/schema 控制面语句，禁止 `USE`、导入、查询或校验 scratch 业务内容；恢复内容面始终只由 restore-admin 访问。每个目标在删除前重新核对 loopback 实例、前缀、32 位 run ID 和所有权；不匹配就报告残留并拒绝扩大清理范围。`test-mysql-matrix.ps1` 为 8.0/8.4 容器创建自己的 caller-owned admin option file 后复用同一 provision/run/cleanup 契约。契约测试覆盖 setup 中断、pytest 失败、重复 cleanup、凭据文件缺失、ID/实例错配、grant-admin 越权内容访问和未知残留，证明不会读取恢复内容，也不会删除普通 schema、其他 run 或调用者文件。

```powershell
.\scripts\run-production-mysql-integration.ps1
.\scripts\test-mysql-matrix.ps1 -Versions "8.0","8.4"
```

Expected: 本机 wrapper 收集并运行完整 integration 目录且 PASS，本地矩阵的 MySQL 8.0/8.4 也均 PASS；不得用直接 pytest 或挑选 production 文件代替 wrapper 的全量目录。同步更新 `.github/workflows/compatibility.yml` 和 `scripts/test-mysql-matrix.ps1` 的显式测试清单，使两种版本都验证线性迁移经过 `0023` 并最终到达 `0024`，而 production repository/API/UI workflow 和最小运行账号权限只在最终 `0024` 执行；另覆盖真实备份恢复。应用/迁移/备份测试 schema 都匹配 `clsen_data_test*`；唯一 `clsen_restore_<32hex>` scratch 的内容面只由成对 run ID 与最小 restore-admin canary 访问，validated grant-admin 仅执行同 run 精确名称的控制面 provision/cleanup。`APP_TEST_RUNTIME_DATABASE_URL` 必须真正参与 repository/API 测试，主库和 preservation 的 backup URL 都必须以各自独立最小备份账号参与 write-barrier；restore-admin 不得替代任何应用、迁移或备份账号。保存测试收集清单、两个临时 schema/run ID 和 cleanup 结果，避免 marker、缺少宿主客户端或配置误排除 MySQL 用例。

- [ ] **Step 8: 运行前端全量和端到端检查**

```powershell
Set-Location frontend
pnpm test --run
pnpm lint
pnpm typecheck
pnpm build
pnpm exec playwright test
Set-Location ..
.\scripts\run-production-live-e2e.ps1 -Milestone All
.\scripts\generate-api-client.ps1 -Check
git diff --check -- (Get-Content -Raw -LiteralPath .\docs\superpowers\plans\2026-08-18-finished-goods-production-receipt-file-manifest.json | ConvertFrom-Json)
.\scripts\check-worktree-text.ps1 -PathManifest .\docs\superpowers\plans\2026-08-18-finished-goods-production-receipt-file-manifest.json -Extensions .py,.ts,.tsx,.css,.md,.json,.toml,.ps1,.in,.lock,.yml,.yaml
if ([string]::IsNullOrWhiteSpace($env:APP_PLAN_BASELINE_ROOT)) { throw 'APP_PLAN_BASELINE_ROOT must point to the private Task 0 snapshot' }
.\scripts\check-plan-worktree-baseline.ps1 -PathManifest .\docs\superpowers\plans\2026-08-18-finished-goods-production-receipt-file-manifest.json -BaselineRoot $env:APP_PLAN_BASELINE_ROOT
git status --short
```

Expected: 既有完整 Playwright 套件和 `0024` 上的两条 live production 流程全部 PASS；Task 7 的 `0023` 订单里程碑证据仍可追溯，但最终代码不被误报为纯 `0023` 兼容。live config 不复用服务器，两个 run-ID 健康探针匹配，清理只涉及本 run PID、管理员、事实和临时文件；OpenAPI 生成文件稳定。`check-worktree-text.ps1` 必须验证 manifest 路径均位于仓库内，并同时处理其中 Git 已跟踪和未跟踪的新文本文件；扩展名清单必须覆盖 requirements 的 `.in/.lock` 和 workflow 的 `.yml/.yaml`，并拒绝尾随空白、缺少末尾换行和 UTF-8 解码失败，弥补 path-scoped `git diff --check` 对未跟踪文件的盲区。另可输出全工作区非阻断报告，但不得让既有无关告警污染本计划结果或触发自动修复。

`check-plan-worktree-baseline.ps1` 必须先验证私有基线 SHA-256 清单、冻结仓库路径和 `HEAD` OID，且只读不恢复文件。对基线时已跟踪脏路径，以冻结 `HEAD` blob 为共同祖先，对“基线工作树原始字节”和“最终工作树字节”执行三方比较：不得有冲突，保留基线修改后重建的结果必须与最终文件逐字节一致；index blob 和 staged 状态也不得被计划改变。对基线时已存在的未跟踪路径，用状态、原始副本、基线/最终 SHA-256 和完整二进制安全差异证明文件未被删除、截断或替换，只允许 manifest 所属 Task 声明的增量。任何基线缺失、状态异常、既有 hunk 丢失、未声明转换或无法证明归属都失败，脚本不得自动还原。最终工作区保持未提交，等待用户决定是否提交或进入下一模块。

## 第一期开工门禁

开始 Task 1 前必须确认：

1. 本计划只交付“订单到广州成品仓”，用户已知出货、在途、FBA、销售和退货由全链路路线图继续交付；
2. 用户接受系统标准订单/完工模板，或已经提供需要兼容的真实样表；
3. 第一期不保存人工预计完工日，而是以订单日为 D、按站点本地自然日派生 D+7～D+30 窗口；D+7 与 D+30 均属于 `in_window`，有未完工量时 D+31 起为 `overdue`；
4. SKU 款号、颜色、尺码和展示编码的纠错完全由 P0 商品目录使用不可变向前 revision 处理；production 只选择批准成员并冻结历史行快照，不提供身份修改或 SKU merge；
5. 第一期开工不会被解释为 E0/C/D/E 已获字段级批准。

## 第一期 Completion Gate

实施结束时必须同时满足：

1. Alembic 形成单一线性头；Task 7 已在继续施工前以精确 `0023` 保存可独立体验订单里程碑的证据，最终最低 head `0024` 完成入库里程碑且不虚假承诺纯 `0023` 向后兼容；
2. 两份导入模板、固定 `production_factory_order_v1` 工厂生产订单导出、解析和恶意工作簿防护测试通过；
3. SKU、订单、完工、入库、冲销和库存全部按站点隔离；
4. 完工提交时复算带 schema 的 `validation_digest`，变化固定返回 `409 stale_completion_validation` 且零状态变化；审核的 review-preview、带 schema/site 的 `projection_digest`、逐警告事实指纹、`409 stale_review_projection`、选择/事实变化失效、并发、幂等和事务回滚证明零过期确认、零重复、零部分库存；
5. 过期 `running` 或 `outcome_unknown` 在事实存在时归并 `completed`、事实不存在且租约过期时归并 `retryable`；MySQL 1205/1213 的 4 次固定退避与 `database_contention_retry_exhausted`、丢回执、回滚和状态标记丢失分支均以原 UUID 恢复且有测试证据；
6. production 对 P0 身份表的零写权限、只读目录选择、production alias 审核来源、历史行快照及“无 create/PATCH/merge/repoint”边界通过 API、OpenAPI、MySQL 和浏览器测试；
7. D+6/7/30/31 自然日边界、内部订单号/年度序列唯一约束及并发编号通过测试；
8. 入库单详情 GET、`/production/receipts/:receiptId`、流水链接和来源上传行/订单回溯通过角色与跨站测试；
9. `run-production-mysql-integration.ps1` 收集的完整 `backend/tests/integration --require-mysql`、MySQL 8.0/8.4 矩阵、现有日报导入/审核/发布/日期工作台/批量审核和前端全量回归全部通过；
10. 用户能按文档在隔离体验库完成“订单到广州成品仓”的第一期完整流程；
11. 撤回后同文件重传、显式 resume 解析崩溃恢复、`parsed` 新 UUID 的 command effect/零重复解析、警告事实指纹、待办分页、owner 权限和跨站复合外键均有测试证据；
12. Task 7 的 `0023` 订单 live 证据，以及最终 `0024` 上的订单里程碑和完整入库流程，各至少一条不 mock API 的 React → FastAPI → MySQL 冒烟通过，既有默认 Playwright 全量套件也通过；live runner 不复用或终止既有服务器，不删除普通账号/数据，只清理本 run 资源；
13. 备份恢复后全部 0021/0022/0023/0024 source-of-truth 表的行数、checksum、0021 批量审核三表关系、P0 身份/目录关系、两类生产导入解析失败字段、复合 FK、来源关系和库存余额守恒不变；writer 仅接受当前 `0024`，已知 v1/`0020` artifact 仍可读取，8.0/8.4 均以显式宿主客户端和精确 schema 的隔离 restore-admin 完成真实恢复；
14. 文档链接全链路路线图，并明确只有 A/B 与 E0/C/D/E 全部完成才满足用户的完整供应链要求；
15. 所有 Task 仍以未提交检查点交付；touched-file manifest 内路径的格式化器、已跟踪/未跟踪文本扫描和 path-scoped `git diff --check` 均通过；仓库外私有基线的状态、SHA-256、原始字节和三方比较证明既有重叠修改未被覆盖，既有无关脏文件保持不变，未经授权没有提交、合并、标签或推送。
