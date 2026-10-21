# 日期工作台结构增强实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 在不改变日期工作台版本、编辑、撤销、校验和发布语义的前提下，把现有单层等宽表格升级为支持分组表头、自适应冻结、语义列宽、个人列偏好和连续商品组分隔的高密度可编辑网格。

**Architecture:** 复用现有 `DateWorkbenchResponse` 中的稳定 `column_id`、`standard_field_name`、`is_key`、`participates_in_statistics` 和服务端排序接口。把纯展示规则与浏览器偏好放入共享 `components/data-table`，把可编辑单元格和服务器状态继续留在 workbench feature；页面只负责编排 URL、加载、导入和审核命令。

**Tech Stack:** React 19、TypeScript 5.9、React Router 7、CSS 自定义属性、Vitest、Testing Library、Playwright、现有 FastAPI 工作台读取接口。

## Cross-plan order

- 最佳顺序是先执行“全站蓝白视觉系统”计划的 Task 1（共享令牌与基础控件），再执行本计划。
- 如果共享令牌尚未落地，本计划的 CSS 必须使用 `var(--token, fallback)`，保持独立可运行；后续视觉计划只替换 fallback，不重写网格行为。
- 跨日期发布明细总表将复用本计划产生的只读表头、列设置和列布局接口，不能复制第二套列偏好实现。

## Global Constraints

- 保留一个日期一张原始报表的数据模型、稳定列 ID、原始列顺序和原始行顺序。
- 不改变现有自动保存、撤销、校验、发布、修订、权限或历史接口。
- 列偏好仅保存在浏览器 `localStorage`，按用户 ID、站点 ID、报表类型和偏好版本隔离；不得包含日期、数据集 ID 或业务值。
- 关键身份列不能全部隐藏；服务端列元数据始终比本地偏好权威。
- 服务端排序参数写入 URL；不得在浏览器仅对当前页伪排序。
- 200% 缩放时文本不能进入相邻单元格，固定操作栏不能遮挡最后一行。
- 保留当前脏工作区中的全部用户改动；禁止 `git add`、`git commit`、`git push` 和任何清理工作树命令。
- 每个任务以测试结果、`git diff --check` 和 `git status --short` 作为检查点，不创建提交。

---

### Task 1: 列展示规则与本地偏好

**Files:**
- Create: `frontend/src/components/data-table/columnPresentation.ts`
- Create: `frontend/src/components/data-table/columnPresentation.test.ts`
- Create: `frontend/src/components/data-table/columnPreferences.ts`
- Create: `frontend/src/components/data-table/columnPreferences.test.ts`
- Modify: `frontend/src/features/workbench/workbenchTypes.ts`

**Interfaces:**
- Produces `type DataTableReportType = "business_report" | "return_report"`.
- Produces `type PresentableColumn = Pick<WorkbenchColumnResponse, "column_id" | "source_header" | "standard_field_name" | "is_key" | "display_order">`.
- Produces `classifyColumn(reportType, column): "product" | "traffic" | "conversion" | "sales" | "return" | "resolution" | "amount" | "other"`.
- Produces `recommendedWidth(column): number`, `clampColumnWidth(width): number`, `groupVisibleColumns(reportType, columns): ColumnGroupSpan[]`, and `frozenColumnIds(reportType, columns, widths, viewportWidth): string[]`.
- Produces `loadColumnPreferences(key, columns): ResolvedColumnPreferences`, `saveColumnPreferences(key, preferences): void`, and `preferenceKey({namespace, userId, siteId, reportType}): string`, where namespace is `"workbench" | "published-details"`.

- [ ] **Step 1: 写展示规则失败测试**

```ts
it("classifies columns and splits a group after view reordering", () => {
  const columns = [column("sku", "SKU"), column("sessions", "Sessions"), column("title", "Title")];
  expect(groupVisibleColumns("business_report", columns).map((item) => item.label))
    .toEqual(["商品信息", "流量", "商品信息"]);
  expect(recommendedWidth(column("title", "商品标题"))).toBe(300);
  expect(clampColumnWidth(30)).toBe(72);
  expect(clampColumnWidth(800)).toBe(480);
});
```

- [ ] **Step 2: 运行测试并确认缺少实现**

Run: `Set-Location frontend; pnpm test --run src/components/data-table/columnPresentation.test.ts`

Expected: FAIL because `columnPresentation.ts` does not exist.

- [ ] **Step 3: 实现确定性展示纯函数**

```ts
export const WIDTH_LIMITS = { min: 72, max: 480 } as const;

export function clampColumnWidth(value: number) {
  return Math.min(WIDTH_LIMITS.max, Math.max(WIDTH_LIMITS.min, Math.round(value)));
}

export function recommendedWidth(column: PresentableColumn) {
  const name = `${column.standard_field_name ?? ""} ${column.source_header}`.toLocaleLowerCase();
  if (/title|product.?name|商品.*名|标题/.test(name)) return 300;
  if (/asin|sku|fnsku/.test(name)) return 144;
  if (/date|status|reason|日期|状态|原因/.test(name)) return 152;
  if (/quantity|units|sales|amount|rate|数量|金额|比例|率/.test(name)) return 104;
  return 168;
}
```

Implement NFC-normalized header matching, report-specific group labels, contiguous span splitting, alignment, frozen priority, the 45% viewport cap, and the guarantee that row number plus at least one identity column remain frozen.

- [ ] **Step 4: 写偏好损坏、迁移和账号隔离失败测试**

```ts
it("merges new columns and isolates identities", () => {
  expect(preferenceKey({ namespace: "workbench", userId: 7, siteId: 3, reportType: "business_report" }))
    .toBe("clsen:data-table:v1:workbench:user:7:site:3:report:business_report");
  localStorage.setItem(preferenceKey(identity), "broken-json");
  expect(loadColumnPreferences(preferenceKey(identity), columns).visibleIds)
    .toEqual(columns.map((item) => item.column_id));
});
```

- [ ] **Step 5: 实现版本化偏好合并**

```ts
export type StoredColumnPreferences = {
  version: 1;
  order: string[];
  hidden: string[];
  widths: Record<string, number>;
};

export type ResolvedColumnPreferences = {
  orderedIds: string[];
  visibleIds: string[];
  widths: Record<string, number>;
};
```

Ignore removed IDs, insert new IDs at their server `display_order`, clamp all widths, force at least one current identity column visible, and fall back atomically for invalid JSON or unsupported versions. `saveColumnPreferences` catches storage quota/security failures and returns without affecting business state.

- [ ] **Step 6: 运行纯函数测试和静态检查**

Run: `Set-Location frontend; pnpm test --run src/components/data-table/columnPresentation.test.ts src/components/data-table/columnPreferences.test.ts; pnpm typecheck`

Expected: PASS.

- [ ] **Step 7: 检查工作区**

Run: `Set-Location ..; git diff --check; git status --short`

Expected: only intended new frontend files plus pre-existing user changes; nothing staged.

### Task 2: 两层表头、调宽和列设置组件

**Files:**
- Create: `frontend/src/components/data-table/DataTableHeader.tsx`
- Create: `frontend/src/components/data-table/DataTableHeader.test.tsx`
- Create: `frontend/src/components/data-table/ColumnSettingsPanel.tsx`
- Create: `frontend/src/components/data-table/ColumnSettingsPanel.test.tsx`
- Create: `frontend/src/components/data-table/useColumnLayout.ts`
- Create: `frontend/src/components/data-table/dataTable.css`

**Interfaces:**
- `useColumnLayout({columns, identity, viewportWidth})` returns ordered visible columns, widths, group spans, frozen IDs, sticky left offsets, and mutation commands.
- `DataTableHeader` receives `{groups, columns, widths, frozenLeft, sort, onSort, onResize}` and renders exactly two semantic header rows.
- `ColumnSettingsPanel` receives `{columns, layout, onChange, onClose}` and never writes server data.

- [ ] **Step 1: 写两层表头和拆分组测试**

```tsx
render(<DataTableHeader groups={groups} columns={columns} sort={{columnId: skuId, direction: "asc"}} {...handlers} />);
expect(screen.getAllByRole("row")).toHaveLength(2);
expect(screen.getByRole("columnheader", { name: "SKU" })).toHaveAttribute("aria-sort", "ascending");
expect(screen.getAllByRole("columnheader", { name: "商品信息" })).toHaveLength(2);
```

- [ ] **Step 2: 运行测试并确认组件缺失**

Run: `Set-Location frontend; pnpm test --run src/components/data-table/DataTableHeader.test.tsx src/components/data-table/ColumnSettingsPanel.test.tsx`

Expected: FAIL because the components do not exist.

- [ ] **Step 3: 实现列布局 hook**

```ts
export type ColumnLayoutCommands = {
  resize(columnId: string, width: number): void;
  move(columnId: string, beforeColumnId: string | null): void;
  setVisible(columnId: string, visible: boolean): void;
  showStatisticalOnly(): void;
  restoreSourceOrder(): void;
  resetWidths(): void;
};
```

Use measured wrapper width through `ResizeObserver`; calculate sticky `left` values from the actual resolved widths. Persist only after pointer release or keyboard adjustment, not on every pointer movement.

- [ ] **Step 4: 实现可访问的两层表头和调宽手柄**

```tsx
<button
  aria-label={`调整“${column.source_header}”列宽`}
  className="data-table-resizer"
  onKeyDown={(event) => {
    if (event.key === "ArrowLeft") onResize(column.column_id, width - 8);
    if (event.key === "ArrowRight") onResize(column.column_id, width + 8);
  }}
  type="button"
/>
```

The group row uses `scope="colgroup"` and `colSpan`; the source row uses `scope="col"`, full text in `title`, statistics text, and tri-state sorting (`asc`, `desc`, original/no sort).

- [ ] **Step 5: 实现列设置面板**

The panel contains a labelled search input, checkboxes for visibility, keyboard-operable move up/down buttons in addition to pointer drag, “只显示统计字段”, “恢复原始顺序”, and “重置列宽”. Disable the final visible identity checkbox rather than accepting an invalid state.

- [ ] **Step 6: 完成组件测试**

Add tests for pointer/keyboard resize, search, hide/show, reordering, reset, disabled last identity column, damaged storage fallback, and persistence after remount.

Run: `Set-Location frontend; pnpm test --run src/components/data-table`

Expected: PASS.

- [ ] **Step 7: 检查差异**

Run: `Set-Location ..; git diff --check; git status --short`

Expected: no whitespace errors and nothing staged.

### Task 3: 可编辑网格与连续商品组

**Files:**
- Create: `frontend/src/features/workbench/EditableDataGrid.tsx`
- Create: `frontend/src/features/workbench/EditableDataGrid.test.tsx`
- Create: `frontend/src/features/workbench/workbenchGrouping.ts`
- Create: `frontend/src/features/workbench/workbenchGrouping.test.ts`
- Modify: `frontend/src/features/workbench/DateWorkbenchPage.css`

**Interfaces:**
- `groupKey(reportType, row, columns): string | null` reads visible server cell values without mutating order.
- `rowGroupBoundaries(reportType, rows, columns): Array<{key: string | null; startsGroup: boolean}>` compares adjacent rows on the current page only.
- `EditableDataGrid` receives the existing page, editor map, column layout, `onSaveCell`, and sort command; it does not fetch or mutate authoritative data by itself.

- [ ] **Step 1: 写商品组纯函数失败测试**

```ts
expect(rowGroupBoundaries("business_report", rows, columns)).toEqual([
  { key: "B000-PARENT", startsGroup: true },
  { key: "B000-PARENT", startsGroup: false },
  { key: "2401", startsGroup: true },
]);
```

Cover parent ASIN, stable SKU style prefix, return-report SKU/ASIN fallback, missing identity, and page-first-row semantics.

- [ ] **Step 2: 实现只比较相邻行的分组函数**

Do not sort. The SKU prefix fallback accepts only the existing `数字款号-颜色-尺码` format and returns its numeric first segment; otherwise it returns the full non-empty SKU to avoid merging unrelated rows.

- [ ] **Step 3: 写网格行为失败测试**

```tsx
expect(screen.getByRole("table", { name: "经营报告原始数据" })).toBeVisible();
expect(screen.getByRole("rowheader", { name: "1" })).toHaveStyle({ left: "0px" });
expect(screen.getByText("Very long product title")).toHaveClass("workbench-cell-value");
expect(screen.getByText("Very long product title")).toHaveAttribute("title", "Very long product title");
```

- [ ] **Step 4: 实现网格组件**

Render `DataTableHeader`, sticky row number and identity cells, editor inputs, status text, group label, and group boundary classes. Preserve the existing `saveCell` contract and `cellKey`; do not move server response state into the component.

- [ ] **Step 5: 实现优先级明确的状态样式**

```css
.workbench-grid td { overflow: hidden; }
.workbench-cell-value { display: block; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.workbench-grid tr.is-group-start > * { border-top: 2px solid var(--color-border, #c7d6e2); }
.workbench-grid td.is-changed { background: var(--color-warning-soft, #fff6d8); }
.workbench-grid td.has-error { background: var(--color-danger-soft, #fdeaea); }
```

Status classes override alternating group backgrounds. Inputs stay inside the cell and use internal horizontal scrolling.

- [ ] **Step 6: 运行网格测试**

Run: `Set-Location frontend; pnpm test --run src/features/workbench/EditableDataGrid.test.tsx src/features/workbench/workbenchGrouping.test.ts`

Expected: PASS.

- [ ] **Step 7: 检查差异**

Run: `Set-Location ..; git diff --check; git status --short`

Expected: nothing staged.

### Task 4: 日期页面集成、URL 排序和身份隔离

**Files:**
- Modify: `frontend/src/features/workbench/DateWorkbenchPage.tsx`
- Modify: `frontend/src/features/workbench/DateWorkbenchPage.test.tsx`
- Modify: `frontend/src/features/workbench/workbenchApi.ts`
- Modify: `frontend/src/app/App.tsx`
- Modify: `frontend/src/app/App.test.tsx`

**Interfaces:**
- `DateWorkbenchPage` props become `{canWrite: boolean; reportDate: string; siteId: number; userId: number}`.
- URL keys are `report_type`, `search`, `changed_only`, `sort_column_id`, `direction`, and `page`.
- Removing sort deletes both `sort_column_id` and `direction`; changing report/search/sort resets page to 1.

- [ ] **Step 1: 扩展页面测试夹具**

Add at least parent ASIN, SKU, title, sessions, sales, and unknown extension columns with stable UUIDs. Assert two header rows, semantic widths, frozen offsets, settings persistence, and unmodified server column order.

- [ ] **Step 2: 写 URL 服务端排序失败测试**

```tsx
await user.click(await screen.findByRole("columnheader", { name: /Sessions/ }));
await waitFor(() => expect(api.loadWorkbench).toHaveBeenCalledTimes(2));
const [date, type, query] = api.loadWorkbench.mock.calls.at(-1)!;
expect([date, type]).toEqual(["2026-08-14", "business_report"]);
expect(Object.fromEntries((query as URLSearchParams).entries())).toMatchObject({
  page: "1", page_size: "50", sort_column_id: sessionsId, direction: "asc",
});
```

- [ ] **Step 3: 把排序参数纳入查询编排**

```ts
const sortColumnId = searchParams.get("sort_column_id");
if (sortColumnId) {
  next.set("sort_column_id", sortColumnId);
  next.set("direction", searchParams.get("direction") === "desc" ? "desc" : "asc");
}
```

On a server `invalid_sort_column` response, remove the stale sort keys, retain report/search, and reload page 1 once.

- [ ] **Step 4: 用布局组件替换内联单层表格**

Keep import confirmation, duplicate/conflict states, revision creation, autosave, undo, validation and action bar code in `DateWorkbenchPage`. Replace only the table rendering with `EditableDataGrid` and add a labelled column-settings trigger.

- [ ] **Step 5: 从应用壳传递用户与站点身份**

Change `DateWorkbenchRoute` to accept and forward `principal.id` and `siteContext.site_id`; update both `/review/:reportDate` and `/published/:reportDate` branches and route tests.

- [ ] **Step 6: 回归编辑与只读行为**

Run: `Set-Location frontend; pnpm test --run src/features/workbench/DateWorkbenchPage.test.tsx src/app/App.test.tsx`

Expected: uploads, autosave, undo, long-value containment, viewer read-only state, and route behavior all PASS.

- [ ] **Step 7: 静态检查**

Run: `pnpm lint; pnpm typecheck; pnpm build`

Expected: PASS.

- [ ] **Step 8: 检查差异**

Run: `Set-Location ..; git diff --check; git status --short`

Expected: nothing staged and no unrelated edits changed.

### Task 5: 响应式、无障碍与真实浏览器验收

**Files:**
- Modify: `frontend/src/components/data-table/dataTable.css`
- Modify: `frontend/src/features/workbench/DateWorkbenchPage.css`
- Create: `frontend/tests/e2e/date-workbench-structural-grid.spec.ts`

**Interfaces:**
- Desktop >=1280px uses the full frozen calculation; 768–1279px retains row number and necessary identity; 390–767px keeps contained horizontal scrolling.
- All resize, sort, visibility and edit actions remain keyboard-operable.

- [ ] **Step 1: 写三个视口的浏览器测试**

```ts
for (const width of [1280, 768, 390]) {
  test(`contains the wide grid at ${width}px`, async ({ page }) => {
    await page.setViewportSize({ width, height: 900 });
    await page.goto("/review/2026-08-14?report_type=business_report");
    await expect(page.getByRole("table", { name: /经营报告原始数据/ })).toBeVisible();
    expect(await page.locator("body").evaluate((body) => body.scrollWidth <= body.clientWidth)).toBe(true);
  });
}
```

- [ ] **Step 2: 完成断点和缩放样式**

Ensure only `.workbench-grid-wrap` scrolls horizontally, sticky cells have opaque backgrounds and z-index layers, the bottom bar reserves padding, touch targets remain usable, and the column panel fits the viewport.

- [ ] **Step 3: 添加键盘验收**

Tab to the resize handle, use arrows, open settings, hide/show a column, sort, edit, press Escape, and assert visible focus throughout. Add a 200% zoom run and verify no overlap or hidden final row.

- [ ] **Step 4: 运行前端完整门禁**

Run: `Set-Location frontend; pnpm test --run; pnpm lint; pnpm typecheck; pnpm build; pnpm test:e2e -- date-workbench-structural-grid.spec.ts`

Expected: PASS. If the E2E server or authenticated fixture is unavailable, record that exact external blocker; do not report the browser gate as passed.

- [ ] **Step 5: 最终只读检查**

Run: `Set-Location ..; git diff --check; git status --short`

Expected: all intended work remains unstaged, existing user changes are preserved, and no backend migration or database operation was introduced.
