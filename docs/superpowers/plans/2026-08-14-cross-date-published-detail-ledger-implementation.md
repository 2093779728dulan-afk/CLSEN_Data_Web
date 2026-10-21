# 跨日期已发布原始明细总表实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 新增 `/ledger/published-details`，让三个读取角色按默认最近 30 天或自选日期范围查看每日报告当前发布版本的原始明细、摘要展开视图、连续分页视图，并安全流式导出当前筛选和可见列。

**Architecture:** 新建独立的 `published_details` 只读边界，以 `dataset_publications` 为唯一入口，在一次数据库快照中解析当前发布引用、合并稳定列架构并查询行。短期 HMAC 签名 `scope_token` 绑定用户、站点、角色字段边界、报表类型、日期范围和发布引用；后续分页、展开和导出先重验当前指针，避免混用不同发布快照。前端复用日期工作台计划产生的列布局、两层表头和列偏好组件，只新增只读行体、摘要和导出编排。

**Tech Stack:** Python 3.14、FastAPI、Pydantic、SQLAlchemy Core/ORM、MySQL 8.0/8.4、React 19、TypeScript 5.9、React Router 7、Vitest、Playwright、CSV 标准库。

## Dependencies and order

- 先完成“日期工作台结构增强”计划 Tasks 1–2，获得共享 `components/data-table` 接口；若尚未完成，必须先执行那些任务，不能在本 feature 复制实现。
- 先完成“全站蓝白视觉系统”计划 Task 1，或使用带 fallback 的同名 CSS 令牌。
- 本计划不新增数据库表、不运行 Alembic 迁移，也不改变现有发布事务。

## Global Constraints

- 只读取每个数据集的 `dataset_publications` 当前指针；草稿、旧发布版本、未确认上传、丢弃版本和内部证据不进入结果。
- 经营报告与退货报告的列架构、查询和导出始终分离。
- 默认范围是站点时区当前自然日及前 29 天；所有日期计算由站点时区决定。
- 页面每次最多返回 100 行；摘要每页最多 100 个日期；全部结果仅通过服务端分页或流式 CSV 处理。
- 动态排序只接受当前有序列并集中的稳定列 ID；所有搜索值参数化。
- CSV 必须使用 UTF-8 BOM，按当前可见列顺序输出，并防止 `= + - @` 公式注入。
- `scope_token` 不授予权限；每次请求仍执行会话、角色和站点检查，令牌过期或发布指针变化返回结构化冲突。
- 不暴露原始文件路径、账号信息、内部审计 ID、草稿备注或不可公开字段。
- 保留当前脏工作区中的全部用户改动；禁止暂存、提交、推送、迁移和主数据库测试。
- MySQL 集成测试只能使用已确认的可丢弃测试数据库；未确认环境时只运行非 MySQL 测试并明确记录未执行项。

---

### Task 1: 发布范围模型与一致性令牌

**Files:**
- Create: `backend/app/published_details/__init__.py`
- Create: `backend/app/published_details/models.py`
- Create: `backend/app/published_details/scope.py`
- Create: `backend/tests/unit/published_details/__init__.py`
- Create: `backend/tests/unit/published_details/test_scope.py`

**Interfaces:**
- Produces `PublishedDetailScope` with `user_id`, sorted roles, site ID, report type, requested range, issue/expiry timestamps, and ordered `PublicationReference` values.
- Produces `PublishedScopeCodec(secret: str, clock: Callable[[], datetime], ttl: timedelta)` with `encode(scope) -> str` and `decode(token, principal, expected_query) -> PublishedDetailScope`.
- Produces response models `PublishedDetailColumn`, `PublishedDetailRow`, `PublishedDateSummary`, `PublishedSummaryResponse`, `PublishedRowsResponse`, and `PublishedRangeResponse`.

- [ ] **Step 1: 写令牌绑定和过期失败测试**

```py
def test_scope_token_binds_user_site_roles_type_and_range() -> None:
    token = codec.encode(scope(user_id=7, site_id=3))
    decoded = codec.decode(token, principal(user_id=7), query())
    assert decoded.publications == expected_publications
    with pytest.raises(PublishedScopeInvalid):
        codec.decode(token, principal(user_id=8), query())

def test_scope_token_expires() -> None:
    token = codec.encode(scope())
    clock.advance(timedelta(minutes=6))
    with pytest.raises(PublishedScopeExpired):
        codec.decode(token, principal(), query())
```

- [ ] **Step 2: 运行测试并确认模块缺失**

Run: `.\.venv\Scripts\python.exe -m pytest backend/tests/unit/published_details/test_scope.py -q`

Expected: FAIL because `app.published_details` does not exist.

- [ ] **Step 3: 定义公开响应模型**

```py
class PublishedDetailColumn(BaseModel):
    column_id: UUID
    source_header: str
    display_order: int
    value_kind: Literal["text", "integer", "decimal", "utc_datetime"]
    standard_field_name: str | None
    is_key: bool
    participates_in_statistics: bool

class PublishedDetailRow(BaseModel):
    report_date: date
    version_id: int
    version_no: int
    published_at: datetime
    row_ordinal: int
    cells: list[PublishedDetailCell]
```

Rows do not expose database row IDs. Summary responses contain full-day metrics, `total_row_count`, `matching_row_count`, publication reference, permissions, pagination, resolved range, and `scope_token`.

- [ ] **Step 4: 实现规范化签名令牌**

Use canonical UTF-8 JSON, URL-safe base64, `HMAC-SHA256(session_secret, payload)`, and `hmac.compare_digest`. Reject malformed payloads, duplicate/missing publication fields, role/user/site/query mismatch, future issue time, and expiry. Never log the token or secret.

- [ ] **Step 5: 运行单元测试和静态检查**

Run: `.\.venv\Scripts\python.exe -m pytest backend/tests/unit/published_details/test_scope.py -q; .\.venv\Scripts\python.exe -m ruff check backend/app/published_details backend/tests/unit/published_details; .\.venv\Scripts\python.exe -m mypy backend/app/published_details`

Expected: PASS.

- [ ] **Step 6: 检查差异**

Run: `git diff --check; git status --short`

Expected: nothing staged.

### Task 2: 当前发布范围与有序列并集

**Files:**
- Create: `backend/app/published_details/service.py`
- Create: `backend/tests/unit/published_details/test_schema_union.py`
- Create: `backend/tests/integration/test_published_detail_scope.py`
- Reuse: `backend/app/analytics/models.py`
- Reuse: `backend/app/workbench/queries.py`

**Interfaces:**
- Produces `PublishedDetailQueryService(database_session, scope_codec)`.
- Produces `resolve_publication_scope(principal, report_type, from_date, to_date) -> PublishedDetailScope`.
- Produces `resolve_full_range(principal, report_type, today) -> PublishedRangeResponse`.
- Produces `compose_published_schema(scope) -> list[PublishedDetailColumn]`.
- Produces `assert_scope_current(scope) -> None`, raising `PublicationScopeChanged`.

- [ ] **Step 1: 写当前指针和经营/退货隔离测试**

Seed two dates, revise and republish one date, retain its old published version, and assert the scope contains exactly the two current pointer versions for the selected report type. Add viewer and cross-site negative cases.

- [ ] **Step 2: 写有序并集失败测试**

```py
def test_schema_union_uses_date_ascending_first_seen_order() -> None:
    result = service.compose_published_schema(scope_with_columns(
        day1=[sku, title, custom_a],
        day2=[sku, custom_b, title],
    ))
    assert [column.column_id for column in result] == [sku.id, title.id, custom_a.id, custom_b.id]
```

Also prove business and return schemas never merge, repeated stable IDs appear once, and metadata conflicts for the same stable ID raise `PublishedSchemaIntegrityError` rather than silently choosing one.

- [ ] **Step 3: 实现范围解析 SQL**

Join `daily_datasets` to `dataset_publications` and `dataset_versions`, filter the session's current site, report type, and inclusive dates, and order by report date ascending. Build `PublicationReference` values from the pointer rows only. `resolve_full_range` queries `MIN(report_date)` for current pointers and returns `from_date=None, to_date=None` when none exist.

- [ ] **Step 4: 实现列架构并集**

Read `version_table_columns` only for scope version IDs, order by report date then `display_order`, validate report type and stable metadata, and retain first-seen order. Do not create or backfill schema rows.

- [ ] **Step 5: 实现后续请求的指针复核**

Re-resolve current pointer pairs `(dataset_id, version_id, published_at)` for the token range and compare the exact ordered set. Missing, added, removed, or changed pointers raises `PublicationScopeChanged(code="publication_scope_changed")` before reading rows.

- [ ] **Step 6: 运行范围测试**

Run: `.\.venv\Scripts\python.exe -m pytest backend/tests/unit/published_details/test_schema_union.py -q`

Expected: PASS.

Run only on a disposable test database: `.\.venv\Scripts\python.exe -m pytest backend/tests/integration/test_published_detail_scope.py --require-mysql -q`

Expected: PASS without addressing the primary database.

- [ ] **Step 7: 检查差异**

Run: `git diff --check; git status --short`

Expected: nothing staged.

### Task 3: 日期摘要、搜索、排序和分页行查询

**Files:**
- Modify: `backend/app/published_details/service.py`
- Create: `backend/app/published_details/query_builder.py`
- Create: `backend/tests/unit/published_details/test_query_builder.py`
- Create: `backend/tests/integration/test_published_detail_queries.py`

**Interfaces:**
- Produces `query_date_summaries(scope, search, page, page_size) -> PublishedSummaryPage`.
- Produces `query_published_rows(scope, search, sort_column_id, direction, page, page_size, report_date=None) -> PublishedRowsPage`.
- Produces one internal `VisibleColumnResolver` that maps allow-listed stable IDs to typed SQL expressions or extension-cell joins.

- [ ] **Step 1: 写参数化搜索和排序表达式测试**

```py
def test_unknown_sort_column_is_rejected() -> None:
    with pytest.raises(InvalidPublishedSortColumn):
        builder.order_by(UUID("00000000-0000-0000-0000-000000000001"), "asc")

def test_search_value_is_never_interpolated() -> None:
    sql, params = builder.search("%' OR 1=1 --")
    assert "OR 1=1" not in sql
    assert params["search"] == "%\\%\' OR 1=1 --%"
```

- [ ] **Step 2: 实现可见列解析器**

Map standard fields through the existing report field contract and actual typed table columns; map extension IDs through `version_extension_cells`. Return `NULL` for a date/version missing a union column. Never accept a raw SQL identifier from request text.

- [ ] **Step 3: 写摘要口径集成测试**

Seed matching and non-matching rows for one day. Assert the day remains when at least one public field matches, `matching_row_count` is filtered, `total_row_count` is complete, and sales/units/sessions or return metrics remain the full current publication totals with `metric_scope="full_day"`.

- [ ] **Step 4: 实现摘要查询**

Use one reusable search predicate for summary matching and row results. Aggregate full-day metrics in a separate CTE/subquery not narrowed by the search predicate. Paginate dates, not rows; order dates descending and include version number/published time.

- [ ] **Step 5: 写行并集与缺失空值集成测试**

Assert default order `(report_date DESC, row_ordinal ASC)`, stable sorting with `(report_date, row_ordinal)` tiebreakers, optional `report_date` constrained inside the token range, page size maximum 100, and JSON `null` for absent columns.

- [ ] **Step 6: 实现分页行查询**

Select the scoped version IDs explicitly after `assert_scope_current`. Fetch one bounded row page and its cells; assemble cells in union schema order. Search only role-visible public raw fields plus report date. Reject `report_date` outside the original scope.

- [ ] **Step 7: 运行查询测试**

Run: `.\.venv\Scripts\python.exe -m pytest backend/tests/unit/published_details/test_query_builder.py -q`

Run only on disposable MySQL: `.\.venv\Scripts\python.exe -m pytest backend/tests/integration/test_published_detail_queries.py --require-mysql -q`

Expected: PASS.

- [ ] **Step 8: 检查差异**

Run: `git diff --check; git status --short`

Expected: nothing staged.

### Task 4: CSV 安全与流式导出

**Files:**
- Create: `backend/app/published_details/csv_export.py`
- Create: `backend/tests/unit/published_details/test_csv_export.py`
- Create: `backend/tests/integration/test_published_detail_export.py`

**Interfaces:**
- Produces `csv_safe_text(value: object | None) -> str`.
- Produces `stream_published_csv(scope, query, visible_column_ids) -> Iterator[bytes]`.
- The iterator starts with UTF-8 BOM and yields bounded batches; it never materializes the full result.

- [ ] **Step 1: 写公式注入和中文 CSV 失败测试**

```py
@pytest.mark.parametrize("value", ["=1+1", " +SUM(A1:A2)", "\t@cmd", "\x00-2"])
def test_csv_safe_text_prefixes_formula_candidates(value: str) -> None:
    safe = csv_safe_text(value)
    assert safe.startswith("'")

def test_stream_starts_with_bom_and_quotes_newlines() -> None:
    payload = b"".join(stream_fixture([["中文", 'line 1\nline "2"']]))
    assert payload.startswith(codecs.BOM_UTF8)
    assert b'"line 1\nline ""2"""' in payload
```

- [ ] **Step 2: 实现安全单元格规范化**

Strip leading C0 control characters except tab/CR/LF for CSV structure, examine the value after ignored leading whitespace/control characters, and prefix a single quote when the first meaningful character is `=`, `+`, `-`, or `@`. Use `csv.writer`; never concatenate comma-delimited text manually.

- [ ] **Step 3: 实现流式导出**

Validate requested repeated `column_id` values against the scope schema, preserve their requested order, and force report date, published version and necessary identity columns. Execute with server-side streaming/yield batches and close the result on disconnect or exception.

- [ ] **Step 4: 写条件一致性和中断测试**

Assert export uses the same scope/search/sort as page rows, excludes old publications, exports all matched rows rather than one page, and closes the cursor when the generator is cancelled. The filename is ASCII-safe plus RFC 5987 UTF-8 metadata and contains site, report type, and dates.

- [ ] **Step 5: 运行 CSV 测试**

Run: `.\.venv\Scripts\python.exe -m pytest backend/tests/unit/published_details/test_csv_export.py -q`

Run only on disposable MySQL: `.\.venv\Scripts\python.exe -m pytest backend/tests/integration/test_published_detail_export.py --require-mysql -q`

Expected: PASS.

- [ ] **Step 6: 检查差异**

Run: `git diff --check; git status --short`

Expected: nothing staged.

### Task 5: FastAPI 路由、权限与 OpenAPI 契约

**Files:**
- Create: `backend/app/api/published_details.py`
- Modify: `backend/app/main.py`
- Modify: `backend/tests/unit/test_openapi_contract.py`
- Create: `backend/tests/unit/test_published_details_api.py`
- Modify: `frontend/src/api/generated.ts` only through `scripts/generate-api-client.ps1`

**Interfaces:**
- `GET /api/published-details/range?report_type=` resolves the earliest current publication through today for the “全部已发布” shortcut.
- `GET /api/published-details/summaries` accepts `report_type`, `from`, `to`, `search`, `page`, `page_size`, optional `scope_token`.
- `GET /api/published-details/rows` additionally accepts `sort_column_id`, `direction`, optional constrained `report_date`.
- `GET /api/published-details/export.csv` accepts row filters, required `scope_token`, and repeated `column_id`.
- All routes require exactly `admin | data_manager | viewer`.

- [ ] **Step 1: 写路由形状和角色失败测试**

Extend `viewer_safe_routes` with the four endpoints. Assert `page_size` maximum 100, enum report type/direction, repeated UUID columns, response models, CSV media type, session security, and no CSRF/idempotency headers on these reads.

- [ ] **Step 2: 实现路由依赖和错误映射**

Construct `PublishedScopeCodec` from `request.app.state.settings.session_secret`; use the request-scoped database session. Map invalid range to 422, invalid/expired token to 409, changed pointers to `409 publication_scope_changed`, unauthorized fields to 403, and integrity faults to a non-leaking 409/500 envelope as appropriate.

- [ ] **Step 3: 实现首次与后续请求流程**

When `scope_token` is absent, resolve current scope and issue a token in the same session snapshot. When present, decode, revalidate current pointers, and reuse the token scope. For export, reject a missing token so the downloaded file always matches a previously presented scope.

- [ ] **Step 4: 注册路由并生成前端契约**

Add `published_details_router` beside the dashboard/workbench routers in `backend/app/main.py`.

Run: `pwsh .\scripts\generate-api-client.ps1`

Expected: `frontend/src/api/generated.ts` contains the four new operations and current OpenAPI digest; do not hand-edit generated definitions.

- [ ] **Step 5: 运行 API 契约测试**

Run: `.\.venv\Scripts\python.exe -m pytest backend/tests/unit/test_published_details_api.py backend/tests/unit/test_openapi_contract.py -q`

Expected: PASS.

- [ ] **Step 6: 后端静态门禁**

Run: `.\.venv\Scripts\python.exe -m ruff check backend/app/published_details backend/app/api/published_details.py backend/tests/unit/published_details backend/tests/unit/test_published_details_api.py; .\.venv\Scripts\python.exe -m mypy backend/app/published_details backend/app/api/published_details.py`

Expected: PASS.

- [ ] **Step 7: 检查差异**

Run: `git diff --check; git status --short`

Expected: nothing staged.

### Task 6: 前端 URL 状态与读取 API

**Files:**
- Create: `frontend/src/features/published-details/publishedDetailsState.ts`
- Create: `frontend/src/features/published-details/publishedDetailsState.test.ts`
- Create: `frontend/src/features/published-details/publishedDetailsApi.ts`
- Create: `frontend/src/features/published-details/publishedDetailsApi.test.ts`
- Create: `frontend/src/features/published-details/publishedDetailsTypes.ts`

**Interfaces:**
- Produces `parsePublishedDetailsSearch(params, today): PublishedDetailsViewState` and `serializePublishedDetailsSearch(state): URLSearchParams`.
- View state contains report type, explicit `from`/`to`, `mode: "summary" | "rows"`, search, sort, direction, page, and optional expanded date.
- API functions use generated response types and preserve one `AbortSignal` per load.

- [ ] **Step 1: 写默认 30 天和 URL 规范化测试**

```ts
expect(parsePublishedDetailsSearch(new URLSearchParams(), "2026-08-14")).toMatchObject({
  from: "2026-07-16",
  to: "2026-08-14",
  mode: "summary",
  reportType: "business_report",
  page: 1,
});
```

Cover leap/month boundaries, invalid dates, reversed ranges, mode/tab changes resetting page, and preserving shareable filters while excluding personal widths/hidden columns.

- [ ] **Step 2: 实现纯 URL 状态函数**

Use ISO calendar arithmetic in UTC for client defaults, then accept the server's resolved site-timezone range as authority. Never derive “today” from `toISOString()` in the page; receive it from site context/current report day.

- [ ] **Step 3: 写 API 请求和冲突测试**

Assert summary/rows requests carry the returned token on subsequent pages and expansion, export includes repeated `column_id`, and `ApiRequestError(code="publication_scope_changed")` is distinguishable.

- [ ] **Step 4: 实现读取函数**

```ts
export function loadPublishedRows(query: PublishedRowsQuery, signal?: AbortSignal) {
  return requestApi<PublishedRowsResponse>(`/api/published-details/rows?${rowsParams(query)}`, { signal });
}

export function publishedCsvUrl(query: PublishedExportQuery) {
  return `/api/published-details/export.csv?${exportParams(query)}`;
}
```

- [ ] **Step 5: 运行状态/API 测试**

Run: `Set-Location frontend; pnpm test --run src/features/published-details/publishedDetailsState.test.ts src/features/published-details/publishedDetailsApi.test.ts; pnpm typecheck`

Expected: PASS.

- [ ] **Step 6: 检查差异**

Run: `Set-Location ..; git diff --check; git status --short`

Expected: nothing staged.

### Task 7: 日期摘要展开视图

**Files:**
- Create: `frontend/src/features/published-details/PublishedDetailLedgerPage.tsx`
- Create: `frontend/src/features/published-details/PublishedDetailLedgerPage.test.tsx`
- Create: `frontend/src/features/published-details/PublishedDateSummaries.tsx`
- Create: `frontend/src/features/published-details/PublishedDateSummaries.test.tsx`
- Create: `frontend/src/features/published-details/PublishedDetailLedgerPage.css`

**Interfaces:**
- Page owns the active `scope_token`; only one date can be expanded.
- Summary metrics are labelled “全日”; search matching is shown as `匹配行数/总行数`.
- Expansion calls the rows endpoint with original range plus constrained `report_date` and inherited search.

- [ ] **Step 1: 写摘要页面失败测试**

```tsx
expect(await screen.findByText("经营明细")).toHaveAttribute("aria-selected", "true");
expect(screen.getByText("12 / 80 行")).toBeVisible();
expect(screen.getByText(/销售额.*全日/)).toBeVisible();
await user.click(screen.getByRole("button", { name: "展开 2026-08-14 明细" }));
expect(api.loadPublishedRows).toHaveBeenCalledWith(expect.objectContaining({ reportDate: "2026-08-14", search: "2401" }), expect.any(AbortSignal));
```

- [ ] **Step 2: 实现工具栏与快捷日期**

Render report tabs, explicit from/to inputs, 7 days, 30 days, current month, all-published, search, summary/rows mode, column settings, and export. The all-published action first calls `/range`, replaces URL with explicit dates, then performs the normal query.

- [ ] **Step 3: 实现摘要列表和单展开状态**

Each card/row shows publication version/time, counts, full-day metrics, “展开明细”, link to `/published/:date?report_type=...`, and `/versions?report_date=...&report_type=...`. Opening another date aborts and releases the prior expanded request/state.

- [ ] **Step 4: 实现加载、空、失败、权限和冲突状态**

On `publication_scope_changed`, show “发布数据已更新，正在重新读取”，drop token/expanded rows, reset page 1, and reload once. Preserve URL filters on ordinary failure and provide an in-place retry.

- [ ] **Step 5: 完成摘要组件测试**

Cover default range, custom range, tabs, URL restoration, search semantics, single expansion, collapse, abort, empty results, retry, 409 refresh, and links.

Run: `Set-Location frontend; pnpm test --run src/features/published-details/PublishedDateSummaries.test.tsx src/features/published-details/PublishedDetailLedgerPage.test.tsx`

Expected: PASS.

- [ ] **Step 6: 检查差异**

Run: `Set-Location ..; git diff --check; git status --short`

Expected: nothing staged.

### Task 8: 全部明细只读网格、导出、路由和导航

**Files:**
- Create: `frontend/src/features/published-details/ReadonlyPublishedDataGrid.tsx`
- Create: `frontend/src/features/published-details/ReadonlyPublishedDataGrid.test.tsx`
- Modify: `frontend/src/features/published-details/PublishedDetailLedgerPage.tsx`
- Modify: `frontend/src/app/App.tsx`
- Modify: `frontend/src/app/App.test.tsx`
- Modify: `frontend/src/features/dashboard/PublishedDashboard.tsx`
- Modify: `frontend/src/features/dashboard/PublishedDashboard.test.tsx`
- Modify: `frontend/src/features/versions/VersionHistory.tsx`
- Modify: `frontend/src/features/versions/VersionHistory.test.tsx`

**Interfaces:**
- `/ledger/published-details` is viewer-safe and renders inside the existing authenticated `AppShell`.
- `PublishedDetailLedgerPage` receives `{principal, siteId, reportingTimezone, today}`; `today` is computed by the existing site-timezone `currentReportDay` helper in `App.tsx`.
- The leftmost system columns are report date, published version, row number, then shared identity columns.
- Export is a normal same-origin download URL built from current token/filter/sort and visible column order.

- [ ] **Step 1: 写只读网格测试**

Assert two-layer grouped headers, report date/version/row system columns, shared semantic widths/frozen offsets, `null` rendered as `—`, no textbox/editor, service-side sort URL, pagination, and column settings persistence.

- [ ] **Step 2: 实现只读行体并复用共享表头**

Use `DataTableHeader`, `ColumnSettingsPanel`, `useColumnLayout`, and `preferenceKey({namespace: "published-details", userId, siteId, reportType})` so workbench and ledger visibility choices do not unexpectedly overwrite one another.

- [ ] **Step 3: 实现导出交互**

Disable export until a token and schema exist. Build repeated `column_id` values from current visible order; retain mandatory system/identity columns. Use `<a download href={publishedCsvUrl(query)}>` so browser download failure is not mistaken for a JSON page response.

- [ ] **Step 4: 注册路由和入口**

Add the route for all authenticated roles. Add “发布明细” to the sidebar or the dashboard's first-screen ledger navigation next to 每日总表/产品总表, without removing existing routes or changing role guards.

Update `VersionHistory` to initialize and synchronize its report date/type filters from `report_date` and `report_type` query parameters, so summary links land on the requested history. Preserve its existing prop-based fallback and callback behavior.

- [ ] **Step 5: 完成路由与页面测试**

Run: `Set-Location frontend; pnpm test --run src/features/published-details src/app/App.test.tsx src/features/dashboard/PublishedDashboard.test.tsx src/features/versions/VersionHistory.test.tsx`

Expected: admin, data_manager, and viewer can open the page; no write controls appear; existing dashboard navigation remains intact.

- [ ] **Step 6: 前端静态门禁**

Run: `pnpm lint; pnpm typecheck; pnpm build`

Expected: PASS.

- [ ] **Step 7: 检查差异**

Run: `Set-Location ..; git diff --check; git status --short`

Expected: nothing staged.

### Task 9: 端到端一致性、性能与最终回归

**Files:**
- Create: `frontend/tests/e2e/published-detail-ledger.spec.ts`
- Modify: `backend/tests/integration/test_published_detail_queries.py`
- Modify: `backend/tests/integration/test_published_detail_export.py`
- Modify: `docs/user-guide/dashboard.md`

**Interfaces:**
- Browser evidence covers at least two published dates and one republished revision.
- Documentation states current-pointer-only semantics, default 30 days, search metric scope, CSV safety, and viewer access.

- [ ] **Step 1: 增加大范围和指针切换测试**

Generate more than 100 rows and 100 dates in the disposable fixture. Assert bounded pages, no duplicate old publication, stable schema union, token conflict after republish, and streamed export without a full in-memory list.

- [ ] **Step 2: 写浏览器工作流**

```ts
test("views summaries, expands one date, switches to all rows and exports", async ({ page }) => {
  await page.goto("/ledger/published-details");
  await expect(page.getByRole("heading", { name: "已发布原始明细" })).toBeVisible();
  await page.getByRole("button", { name: /展开.*明细/ }).first().click();
  await expect(page.getByRole("table", { name: /已发布.*明细/ })).toBeVisible();
  await page.getByRole("tab", { name: "全部明细" }).click();
  const download = page.waitForEvent("download");
  await page.getByRole("link", { name: "导出 CSV" }).click();
  expect((await download).suggestedFilename()).toMatch(/published-details.*\.csv$/);
});
```

- [ ] **Step 3: 更新用户说明**

Explain report tabs, explicit dates, shortcuts, summary/full rows, full-day metric labels, current publication pointer, sorting/search, and formula-safe CSV. Do not claim historical versions are included.

- [ ] **Step 4: 运行后端非 MySQL完整回归**

Run: `.\.venv\Scripts\python.exe -m pytest backend/tests -m "not mysql and not deepseek_live" -q; .\.venv\Scripts\python.exe -m ruff check backend; .\.venv\Scripts\python.exe -m mypy backend/app`

Expected: PASS.

- [ ] **Step 5: 运行可丢弃 MySQL 集成门禁**

Run only after verifying the configured test database is disposable and not the primary database: `.\.venv\Scripts\python.exe -m pytest backend/tests/integration/test_published_detail_scope.py backend/tests/integration/test_published_detail_queries.py backend/tests/integration/test_published_detail_export.py --require-mysql -q`

Expected: PASS. No migration runs.

- [ ] **Step 6: 运行前端完整门禁**

Run: `Set-Location frontend; pnpm test --run; pnpm lint; pnpm typecheck; pnpm build; pnpm test:e2e -- published-detail-ledger.spec.ts`

Expected: PASS. If authenticated E2E infrastructure is unavailable, record it as not run.

- [ ] **Step 7: 最终只读检查**

Run: `Set-Location ..; git diff --check; git status --short`

Expected: intended files remain unstaged, no migration file exists for this feature, and no primary database operation occurred.
