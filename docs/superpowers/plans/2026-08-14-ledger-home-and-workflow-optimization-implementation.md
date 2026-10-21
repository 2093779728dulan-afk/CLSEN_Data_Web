# 总表首页与审核流程优化实施计划

> 本计划落实已批准设计：`docs/superpowers/specs/2026-08-14-ledger-home-and-workflow-optimization-design.md`。实施时逐项使用测试驱动开发：先写失败测试（RED），再做最小实现（GREEN），最后在测试保护下整理代码（REFACTOR）。

**目标：** 将 `/` 改为按月发布数据总表，提供每日总表、按款号聚合的产品总表和弹出式商品信息卡；将日期审核与只读发布详情拆成独立路由；同时完成导入状态恢复、原文件探测和受限预览的稳定性优化。

**架构：** FastAPI 继续以 `dataset_publications` 当前发布指针为唯一经营数据来源。新增 ledger 响应模型与只读查询服务，统一从 `款号-颜色-尺寸` Seller SKU 派生商品与变体，不建立人工商品主档。React 首页改为 URL 驱动的高密度总表；审核页使用 reducer 状态机，并把恢复键限定到架构版本、站点、用户和报告日。

**技术栈：** Python 3.14、FastAPI、同步 SQLAlchemy 2、MySQL 8.0/8.4、Pydantic、React 19、TypeScript 5.9、React Router 7、Vitest、Testing Library、Playwright。

---

## 全局约束与已锁定契约

- 经营指标、退货指标、商品名称和变体关联只读取 `dataset_publications` 指向的活动行；草稿、失败导入和历史版本不得进入 ledger。
- 当前站点由服务端解析；浏览器不得传入或覆盖 `site_id`。所有新查询允许 `admin`、`data_manager`、`viewer` 读取。
- Seller SKU 只接受 `^(?<style_code>[0-9]+)-(?<color>[^-]+)-(?<size>[^-]+)$`。`style_code` 保留字符串语义，不转整数，避免丢失前导零。
- 异常 SKU 不得合并：每个非空异常 Seller SKU 单独返回一条 `unclassified` 行；空 SKU 统一计为一条“缺少 Seller SKU”异常行。异常行不调用按款号查询的商品卡。
- 第一版不新增数据库表或迁移。商品、变体、ASIN/FNSKU、名称与指标由查询时 CTE 从当前发布行派生。只有用真实月度规模完成查询计划和性能验收后，才另行设计持久化索引或商品主档。
- 新接口固定为：
  - `GET /api/dashboard/daily-ledger?from=YYYY-MM-DD&to=YYYY-MM-DD`
  - `GET /api/dashboard/product-ledger?from=...&to=...&search=...&sort=...&direction=...&page=...&page_size=...`
  - `GET /api/dashboard/product-card/{style_code}?from=...&to=...`
  - `GET /api/imports/{batch_id}/raw-file/preview?encoding=...&row_limit=200`
- `row_limit` 服务端允许 `1..200`，前端第一版固定传 200。预览返回表头、最多 200 行、`truncated`、实际行数和编码；不提供全文件搜索或任意页跳转。
- 原 `/api/dashboard/summary`、`/products`、`/returns` 在首页切换期间保留，避免把接口移除与 UI 改版耦合。新首页不再依赖它们；后续删除须单独确认兼容范围。
- 页面路由固定为 `/`、`/review/:reportDate`、`/published/:reportDate`。商品只使用模态卡，不新增详情路由。
- URL 查询参数固定保存 `month`、`tab`、`status`、`search`、`sort`、`direction`、`page`。关闭商品卡不清除这些参数；商品卡本身不写历史路由。
- 当前工作区已有未提交的 bug 修复与 UI 修改。每个任务提交前只暂存本任务列出的文件，禁止 `git add .`，禁止覆盖无关改动。

## 响应模型

`DailyLedgerResponse` 返回完整请求日期范围，一天一行。每行至少包含：

- `report_date`；
- `business_status`、`return_status`：`published | draft | processing | failed | blocked | missing | future`；
- `overall_status`：`complete | partial | review | blocked | empty | future`；
- 可空的 `sales`、`units_ordered`、`sessions`、`conversion_rate`、`return_quantity`；
- viewer 安全的 `pending_summary` 与可写角色才可见的 `reasons`；
- `counts_as_incomplete`，仅已发生且存在至少一种报告或审核活动、但尚未双发布时为真。

`ProductLedgerResponse` 返回 `rows`、`total_rows`、`page`、`page_size`、日期范围、排序回显和发布引用。正常行以 `style_code` 唯一标识，包含商品名称状态、变体/颜色/尺寸数量、销售额、订购数、会话数、转化率、退货数、有数据天数和最近发布日。异常行包含 `row_kind=unclassified` 与原始 SKU，不伪造 `style_code`。

`ProductCardResponse` 返回款号、名称状态、月度汇总、最近发布日、按日趋势和变体数组。每个变体以完整 Seller SKU 唯一标识，包含颜色、尺寸、其最新发布名称，以及去重并稳定排序的 ASIN/FNSKU 数组。

金额继续以十进制字符串返回；比率为十进制字符串或 `null`。所有数组使用稳定顺序，分页排序最后总以 `style_code ASC`（异常行以原始 SKU ASC）打破并列。

---

## 阶段 0：保护现有基线

### 任务 0.1：记录工作区边界并运行定向基线

**读取：**

- `git status --short`
- 当前未提交 diff

**执行：**

```powershell
git status --short
git diff --check
& .\.venv\Scripts\python.exe -m pytest .\backend\tests\unit\analytics .\backend\tests\unit\test_data_calendar.py .\backend\tests\unit\test_raw_files_api.py
pnpm --dir .\frontend test -- --run src/app/App.test.tsx src/features/dashboard/PublishedDashboard.test.tsx src/features/import-review/ImportReviewFlow.test.tsx src/features/import-review/SourceFilePreview.test.tsx
```

若失败来自已存在的未提交改动，先记录准确测试名和失败原因；不得用回退用户改动的方式建立“干净”基线。

---

## 阶段 1：商品身份解析与公共 ledger 模型

### 任务 1.1：建立 Seller SKU 单一解析规则

**新增：**

- `backend/app/analytics/product_identity.py`
- `backend/tests/unit/analytics/test_product_identity.py`

**RED：** 覆盖 `2301-White-S`、不同颜色/尺寸、前导零款号、缺段、多段、非数字款号、空白段和空值。证明异常 SKU 不会得到正常 `style_code`。

**GREEN：** 实现不可变 `SellerSkuIdentity(style_code, color, size, seller_sku)`、严格 `fullmatch` 解析器、公共正则常量，以及供 MySQL CTE 使用的绑定参数/表达式辅助函数。Python 与 SQL 使用同一个正则文本，禁止在查询中复制第二份模式。

**验证：**

```powershell
& .\.venv\Scripts\python.exe -m pytest .\backend\tests\unit\analytics\test_product_identity.py
& .\.venv\Scripts\python.exe -m ruff check .\backend\app\analytics\product_identity.py .\backend\tests\unit\analytics\test_product_identity.py
```

### 任务 1.2：定义稳定的 ledger DTO

**修改：**

- `backend/app/analytics/models.py`
- `backend/tests/unit/analytics/test_service.py`
- `backend/tests/unit/test_openapi_contract.py`

**RED：** 为每日行的可空指标、商品正常/异常判别联合、变体外部标识、名称冲突、趋势点、分页与排序回显写模型和 OpenAPI 断言。

**GREEN：** 新增前述 DTO 与 Literal 枚举；使用显式字段，不向前端暴露内部 SQL 键。对 `style_code` 使用严格数字字符串验证，对 `page/page_size` 建边界。

**提交建议：** `feat: define ledger product identities and contracts`

---

## 阶段 2：每日总表后端

### 任务 2.1：抽取并统一日期状态判定

**新增：**

- `backend/app/analytics/daily_ledger.py`
- `backend/tests/unit/analytics/test_daily_ledger.py`

**修改：**

- `backend/app/api/data_calendar.py`
- `backend/tests/unit/test_data_calendar.py`

**RED：** 建立状态矩阵：双发布、仅经营发布、仅退货发布、草稿、处理中、失败、完整性阻断、完全无活动、未来日期。分别验证 reviewer 与 viewer 响应；尤其验证未来和完全空白日的 `counts_as_incomplete=false`。

**GREEN：** 将现有 `_CalendarDay` 的优先级规则变为可复用的纯领域函数。viewer 只能看到发布事实和安全摘要，不能由响应差异推断草稿、失败文件或校验问题。

### 任务 2.2：在一个请求事务中组合状态和当前发布指标

**修改：**

- `backend/app/analytics/daily_ledger.py`
- `backend/app/api/dashboard.py`
- `backend/tests/unit/analytics/test_daily_ledger.py`
- `backend/tests/integration/test_published_analytics.py`
- `backend/tests/integration/test_data_calendar_api.py`

**RED：**

- 发布经营但未发布退货时，经营指标有值而 `return_quantity=null`；反向同理。
- 草稿替换和历史版本不会改变 ledger，移动发布指针后才改变。
- 请求范围每天都有一行，且站点和日期隔离。
- viewer 与 reviewer 的指标相同，但待办原因按角色脱敏。

**GREEN：** 实现 `DailyLedgerQueryService`。同一数据库会话/事务内先解析当前站点，再读取发布指针、活动行和角色允许的状态信号，最后以日期骨架组合响应。不要通过浏览器并发拼接 `/summary` 与 `/data-calendar/days`。

**接口参数：** 日期范围顺序合法、最多 366 个含首尾日期；非法范围返回现有结构化 422。

**验证：**

```powershell
& .\.venv\Scripts\python.exe -m pytest .\backend\tests\unit\analytics\test_daily_ledger.py .\backend\tests\unit\test_data_calendar.py
& .\.venv\Scripts\python.exe -m pytest .\backend\tests\integration\test_published_analytics.py .\backend\tests\integration\test_data_calendar_api.py --require-mysql
```

**提交建议：** `feat: add published daily ledger query`

---

## 阶段 3：产品总表后端

### 任务 3.1：按款号聚合经营与退货发布行

**新增：**

- `backend/app/analytics/product_ledger.py`
- `backend/tests/unit/analytics/test_product_ledger.py`

**修改：**

- `backend/app/api/dashboard.py`
- `backend/tests/integration/test_published_analytics.py`

**RED：** 构造同款多颜色、多尺寸、多 ASIN/FNSKU、跨日发布数据；证明三个变体只形成一个 `2301` 商品行，经营与退货数量正确合并。再加入异常 SKU，证明它独立出现且不污染 `2301`。

**GREEN：** 使用 MySQL 8 CTE：先从经营和退货当前发布活动行规范化 Seller SKU，再 `UNION ALL`，最后按正常 `style_code` 或异常原始 SKU 聚合。转换率使用总订购数/总会话数重新计算，不平均日比率。`published_days` 是至少有一种当前发布贡献的去重报告日。

### 任务 3.2：实现名称解析、搜索、排序和服务端分页

**修改：**

- `backend/app/analytics/product_ledger.py`
- `backend/app/api/dashboard.py`
- `backend/tests/unit/analytics/test_product_ledger.py`
- `backend/tests/integration/test_published_analytics.py`

**RED：**

- 搜索命中款号、完整 Seller SKU、ASIN、FNSKU、`title` 和 `product_name`。
- 默认按销售额降序；所有允许列支持升降序并有稳定并列键。
- 无效 sort/direction/page/page_size 返回 422，不把排序字段拼成任意 SQL。
- 页间无重复/遗漏，`total_rows` 不受分页影响。
- 最新非空发布名称被选中；变体名称不一致时 `name_status=multiple`。

**GREEN：** 排序使用服务端 allowlist 映射到固定 SQL 片段；搜索值只作为绑定参数。先得到过滤后的商品键与总数，再取一页聚合，避免把行级 `LIMIT` 错当商品级分页。正常商品优先于异常项，之后使用稳定并列键。

**性能核对：** 对一个完整月份和项目现有最大测试数据运行 `EXPLAIN ANALYZE`，把结果摘要记录到测试/提交说明。不得为了速度绕开当前发布指针或读取草稿。

**验证：**

```powershell
& .\.venv\Scripts\python.exe -m pytest .\backend\tests\unit\analytics\test_product_ledger.py
& .\.venv\Scripts\python.exe -m pytest .\backend\tests\integration\test_published_analytics.py --require-mysql
```

**提交建议：** `feat: aggregate published products by style code`

---

## 阶段 4：商品信息卡后端

### 任务 4.1：返回商品汇总、趋势和全部变体

**修改：**

- `backend/app/analytics/product_ledger.py`
- `backend/app/api/dashboard.py`
- `backend/tests/unit/analytics/test_product_ledger.py`
- `backend/tests/integration/test_published_analytics.py`

**RED：**

- `style_code=2301` 只返回其全部已发布变体，并去重 ASIN/FNSKU。
- 经营标题和退货商品名都能成为名称来源；名称冲突保留到各变体。
- 每日趋势覆盖所选范围，有贡献日数、最近发布日和月汇总一致。
- 非数字、未知款号、跨站点和只存在于草稿的款号分别得到 422/404，不泄露存在性。

**GREEN：** 实现 `product_card` 查询。路径参数先用纯解析/验证规则校验；名称选择按报告日、发布时间和稳定来源顺序确定最新非空值。趋势只返回紧凑数值点，不返回原始行。

**提交建议：** `feat: add published product information card query`

---

## 阶段 5：原文件 HEAD 与受限预览

### 任务 5.1：统一原文件元数据与完整性判定

**修改：**

- `backend/app/api/raw_files.py`
- `backend/app/imports/storage.py`
- `backend/tests/unit/test_raw_files_api.py`
- `backend/tests/unit/imports/test_storage.py`

**RED：** HEAD 与 GET 对不存在批次返回同一 404；数据库完整性状态不可用、对象缺失、大小不符和不安全路径返回同一 409；HEAD 响应体为空且测试证明未调用内容读取/哈希函数。

**GREEN：** 抽出一个批次元数据加载器和错误映射。为 `LocalContentStore` 增加只检查规范 storage key、安全普通文件身份与精确大小的 metadata inspect；HEAD 使用它但不打开读取内容。GET 复用相同元数据判定后继续完整读取和 SHA-256 校验。

### 任务 5.2：实现最多 200 行的服务端 CSV 预览

**修改：**

- `backend/app/api/raw_files.py`
- `backend/app/imports/storage.py`
- `backend/tests/unit/test_raw_files_api.py`
- `backend/tests/unit/imports/test_storage.py`
- `backend/tests/unit/test_openapi_contract.py`

**RED：** 覆盖三种允许编码、引号内换行/逗号、空文件、仅表头、恰好 200 行、201 行截断、坏编码、异常 CSV、超长单行、对象读取中被替换，以及权限拒绝。测试必须证明服务端不把 100MB 文件整体装入内存。

**GREEN：** 使用 `TextIOWrapper(newline="")` 与标准库 `csv.reader` 从安全文件句柄流式读取表头和 `row_limit + 1` 行；设定单字段/单行安全上限并把解析/编码失败映射为结构化 422。读取前后核对文件身份、大小和 mtime；响应 `Cache-Control: private, no-store`。

**验证：**

```powershell
& .\.venv\Scripts\python.exe -m pytest .\backend\tests\unit\test_raw_files_api.py .\backend\tests\unit\imports\test_storage.py
```

**提交建议：** `feat: serve integrity-aware source previews`

---

## 阶段 6：生成客户端契约与前端数据层

### 任务 6.1：刷新 OpenAPI 生成类型

**修改（生成）：**

- `frontend/src/api/generated.ts`

**执行：**

```powershell
pwsh .\scripts\generate-api-client.ps1
pwsh .\scripts\generate-api-client.ps1 -Check
git diff -- .\frontend\src\api\generated.ts
```

禁止手工编辑生成文件。确认 HEAD 因 `include_in_schema=False` 不污染生成契约，preview 与三个 ledger 接口均存在且 operationId 唯一。

### 任务 6.2：建立 dashboard 查询与 URL 状态辅助层

**新增：**

- `frontend/src/features/dashboard/dashboardApi.ts`
- `frontend/src/features/dashboard/dashboardUrlState.ts`
- `frontend/src/features/dashboard/dashboardUrlState.test.ts`

**修改：**

- `frontend/src/features/dashboard/dashboardTypes.ts`

**RED：** 测试默认当月、非法月份回退、tab/search/sort/direction/page 解析、切换筛选重置页码、API 查询参数编码与 AbortSignal 传递。

**GREEN：** 从生成类型派生业务类型；所有请求统一经过 `requestApi`。URL 状态解析为纯函数，组件不各自复制默认值。

**提交建议：** `feat: add typed ledger frontend queries`

---

## 阶段 7：首页每日总表与角色导航

### 任务 7.1：把 `/` 改为 ledger 首页

**新增：**

- `frontend/src/features/dashboard/LedgerHomePage.tsx`
- `frontend/src/features/dashboard/DailyLedgerTable.tsx`
- `frontend/src/features/dashboard/LedgerHomePage.test.tsx`

**修改：**

- `frontend/src/app/App.tsx`
- `frontend/src/app/App.test.tsx`
- `frontend/src/features/dashboard/PublishedDashboard.css`
- `frontend/src/styles.css`

**RED：** 默认打开当前月每日总表；加载保留表头骨架；空月、错误重试、部分发布、未来日和完全空白日正确显示；缺失业务值为 `—` 而不是 `0`。

**GREEN：** 建立紧凑标题、站点/月选择器、同级标签和表格。桌面固定表头/首列；状态由文字加色点表达；手机改紧凑分组列表。删除首页 welcome hero、指标卡阵列和装饰性渐变，不把审核表单嵌入首页。

### 任务 7.2：日期行按角色进入独立页面

**新增：**

- `frontend/src/features/published/PublishedDayPage.tsx`
- `frontend/src/features/published/PublishedDayPage.test.tsx`

**修改：**

- `frontend/src/app/App.tsx`
- `frontend/src/app/App.test.tsx`
- `frontend/src/features/dashboard/DailyLedgerTable.tsx`

**RED：** admin/data_manager 点击行进入 `/review/:reportDate`；viewer 进入 `/published/:reportDate`。键盘 Enter/Space 可激活行；单元格按钮阻止冒泡。viewer 直接访问 review 路由被重定向到对应 published 路由。

**GREEN：** 把现有 `ReviewPage` 改为从 `useParams` 读取并验证日期，保留草稿选择和发布后的刷新。只读页只请求指定日期的 daily ledger 和当前发布详情，不渲染导入/草稿/发布控件。`/dashboard` 暂时重定向 `/` 以保留旧书签。

**提交建议：** `feat: make the monthly daily ledger the home page`

---

## 阶段 8：产品总表与单张商品信息卡

### 任务 8.1：实现 URL 驱动的产品总表

**新增：**

- `frontend/src/features/dashboard/ProductLedgerTable.tsx`
- `frontend/src/features/dashboard/ProductLedgerTable.test.tsx`

**修改：**

- `frontend/src/features/dashboard/LedgerHomePage.tsx`
- `frontend/src/features/dashboard/LedgerHomePage.test.tsx`
- `frontend/src/features/dashboard/PublishedDashboard.css`

**RED：** 标签切换、搜索防抖、排序、分页和刷新恢复 URL 状态；一行对应款号而非 SKU/ASIN；异常 SKU 清楚标注且不可请求正常商品卡。

**GREEN：** 桌面显示已批准列；手机只保留款号、名称、销售额、订购数和退货数。服务器负责搜索/排序/分页，前端不下载全部商品后本地处理。

### 任务 8.2：实现无独立页面的模态商品卡

**新增：**

- `frontend/src/features/dashboard/ProductInfoDialog.tsx`
- `frontend/src/features/dashboard/ProductInfoDialog.test.tsx`

**修改：**

- `frontend/src/features/dashboard/ProductLedgerTable.tsx`
- `frontend/src/features/dashboard/PublishedDashboard.css`

**RED：** 点击正常商品行打开一张卡；展示款号、名称状态、月指标、最近发布日、紧凑趋势和全部变体标识；loading/error/retry 不清空底层表格；关闭按钮、Escape、焦点锁定、背景不可交互和关闭后焦点恢复全部通过。

**GREEN：** 优先使用原生 `<dialog>`，补齐测试环境与浏览器兼容处理。趋势使用轻量内联 SVG，必须有文本摘要/可访问名称，不引入图表依赖。手机端占可用视口并内部滚动；不在卡内嵌套第二个页面或完整明细表。

**提交建议：** `feat: add style ledger and product information dialog`

---

## 阶段 9：导入流程 reducer 与安全恢复

### 任务 9.1：把活动队列项变成唯一状态源

**新增：**

- `frontend/src/features/import-review/importReviewReducer.ts`
- `frontend/src/features/import-review/importReviewReducer.test.ts`

**修改：**

- `frontend/src/features/import-review/workflowTypes.ts`
- `frontend/src/features/import-review/ImportReviewFlow.tsx`
- `frontend/src/features/import-review/ImportReviewFlow.test.tsx`

**RED：** reducer 转移覆盖 intake、inspection、parsed、draft、published、failed；切换文件、重识别、改编码、重解析、发布均只更新目标队列项，不能把上一项 inspection/parsed/upload 带入下一项。

**GREEN：** 删除顶层与队列重复的 upload/inspection/parse 状态；selector 从 `activeQueueId` 得到活动项。服务端批次、草稿和发布指针仍是恢复后的事实校验来源，reducer 不能伪造服务端完成状态。

### 任务 9.2：版本化、按身份隔离并深度校验恢复数据

**新增：**

- `frontend/src/features/import-review/reviewRecovery.ts`
- `frontend/src/features/import-review/reviewRecovery.test.ts`

**修改：**

- `frontend/src/features/import-review/ImportReviewFlow.tsx`
- `frontend/src/features/import-review/ImportReviewFlow.test.tsx`
- `frontend/src/app/App.tsx`
- `frontend/src/app/App.test.tsx`

**RED：** 键格式包含 schema version、site ID、user ID、date；旧版、损坏 JSON、错误枚举、缺字段、重复队列 ID、跨用户/跨站点数据均被丢弃。成功 logout 和服务端 401 会清当前身份的所有 recovery 键；普通网络退出失败保留会话和恢复数据。

**GREEN：** 实现无副作用的 decode/validate，再显式 load/save/remove。`ImportReviewFlow` 接收 `siteId`、`userId`。App 在清空 principal 之前调用限定前缀清理函数，不使用 `sessionStorage.clear()`，避免删除无关应用状态。

### 任务 9.3：只在恢复或批次集合变化时做 HEAD 探测

**修改：**

- `frontend/src/features/import-review/ImportReviewFlow.tsx`
- `frontend/src/features/import-review/importReviewReducer.ts`
- `frontend/src/features/import-review/ImportReviewFlow.test.tsx`

**RED：** 首次恢复会检查所有恢复批次；增删 batch ID 后只重新建立检查；改日期、编码、识别和解析状态不会重复 HEAD；404 删除缺失项，409 显示不可用而不误判为不存在。

**GREEN：** effect 依赖稳定的排序 batch ID 指纹，而不是完整队列对象；并发请求支持 AbortController 和卸载取消。

**提交建议：** `refactor: make import review state explicit and recoverable`

---

## 阶段 10：前端切换受限原文件预览

### 任务 10.1：不再下载完整 CSV 到浏览器解析

**修改：**

- `frontend/src/features/import-review/SourceFilePreview.tsx`
- `frontend/src/features/import-review/SourceFilePreview.test.tsx`
- `frontend/src/features/import-review/ImportReviewFlow.tsx`

**RED：** 断言请求 preview JSON 而不是 raw-file 二进制；显示“预览前 200 行”和截断提示；切换批次/编码取消旧请求且旧响应不能覆盖新表；搜索只过滤返回的预览行；错误可重试。

**GREEN：** 删除浏览器 `arrayBuffer`、`TextDecoder` 和全文件 CSV parser。保留单独“下载原始 CSV”链接用于完整文件。组件状态由 `{headers, rows, truncated}` 直接驱动。

**提交建议：** `perf: replace full browser csv parsing with bounded preview`

---

## 阶段 11：可访问性、响应式与端到端回归

### 任务 11.1：补齐关键交互和视觉状态

**修改：**

- `frontend/src/features/dashboard/PublishedDashboard.css`
- `frontend/src/styles.css`
- 对应 dashboard/import-review 组件测试

**检查：**

- 1280px 桌面：高密度表格、固定表头和首列、横向溢出可控。
- 768px：筛选工具栏换行但顺序不变。
- 390px：每日分组列表、产品精简列、商品卡全视口内部滚动。
- 键盘焦点清晰；状态不只依赖颜色；表头 `scope`、排序 `aria-sort`、错误 `role=alert`、加载状态和空状态语义正确。
- `prefers-reduced-motion` 下无非必要动画。

### 任务 11.2：扩充 Playwright 主路径

**修改：**

- `frontend/tests/e2e/import-review-publish.spec.ts`
- 如职责过大，新增 `frontend/tests/e2e/ledger-home.spec.ts`

**场景：** 登录后默认每日总表；管理员从日期行进入审核、发布后返回总表看到当前发布指标；viewer 进入只读页；产品搜索和分页写入 URL；商品卡打开/关闭保留表格状态；退出后换账号不恢复前一账号队列。

测试数据只能用合成 fixture，不读取私有 CSV。

---

## 阶段 12：完整质量门禁与交付

### 任务 12.1：运行全部自动化门禁

```powershell
& .\.venv\Scripts\python.exe -m ruff format --check .\backend
& .\.venv\Scripts\python.exe -m ruff check .\backend
& .\.venv\Scripts\python.exe -m mypy --config-file .\backend\pyproject.toml .\backend\app .\backend\tests
& .\.venv\Scripts\python.exe -m pytest .\backend\tests
pwsh .\scripts\generate-api-client.ps1 -Check
pnpm --dir .\frontend lint
pnpm --dir .\frontend typecheck
pnpm --dir .\frontend test -- --run
pnpm --dir .\frontend build
pnpm --dir .\frontend test:e2e
git diff --check
```

MySQL 集成环境可用时再运行：

```powershell
& .\.venv\Scripts\python.exe -m pytest .\backend\tests --require-mysql
```

### 任务 12.2：人工验收与兼容复核

- 用 admin、data_manager、viewer 各验收一次首页和日期行跳转。
- 核对本月首日、今日、未来日、完全空日、部分发布日和双发布日。
- 用同款多颜色/尺寸和多 ASIN/FNSKU fixture 核对产品只占一行，卡片变体完整。
- 刷新/前进/后退后，月份、tab、筛选、排序和分页保持一致。
- 验证 100MB 上限附近文件的浏览器网络响应只包含有限预览，不出现完整文件内存峰值。
- 检查 `/dashboard` 旧书签重定向、旧 dashboard API 暂时可用、生成契约无漂移。
- `git status --short` 逐项核对，只提交本计划范围内文件；用户原有未提交改动必须保持原样。

## 完成定义

- `/` 是当前月每日总表，产品总表为同级标签。
- 日期点击按角色进入独立审核或只读页面。
- 产品按数字款号聚合；Seller SKU/ASIN/FNSKU 作为变体信息，点击正常产品行只弹出一张信息卡。
- 所有首页和商品数据仅来自当前发布指针，异常 SKU 不误合并。
- 导入流程没有顶层/队列重复状态；恢复数据按版本、站点、用户、日期隔离且能在退出时定向清除。
- HEAD 不读取文件内容但与 GET 共享元数据/完整性错误语义；预览最多返回 200 行且浏览器不下载整份 CSV。
- 后端、前端、生成契约和 E2E 门禁全部通过，无新迁移，无无关文件被覆盖或提交。

## P0 兼容说明（2026-08-20）

本计划已经交付的 `product-ledger/product-card/{style_code}` 与 dashboard 产品 tab 固定为 legacy compatibility。这里的 `style_code` 不再被称为稳定身份，只是旧 parser 的字符串分组键；旧 API JSON/状态码保持，响应 header 明确 `X-Identity-Source: legacy_parser` 与 parser version。

P0 在独立路由/API 上使用数据库分配的 `style_id/sku_id`，任何 404、空页或数字 path 都不调用本计划 service 兜底。直到 P0 固定事实对账和整套 cutover/rollback 演练通过，旧 dashboard 正式入口不替换；切换后旧入口与 modal 必须和旧 adapter 一起隐藏，rollback 则整套恢复，禁止一页混合两种身份来源。
