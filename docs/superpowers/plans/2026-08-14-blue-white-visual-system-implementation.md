# 全站蓝白视觉系统实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 把首页、应用壳、日期工作台、发布明细、版本记录、管理员控制台和旧导入审核统一为专业、克制、高密度的蓝白数据运营工作台，同时保持全部业务流程、权限和版本安全语义不变。

**Architecture:** 先建立全局语义令牌、基础控件和状态组件，再按页面逐批迁移。共享层只表达颜色、排版、间距、焦点、表单、按钮、表格、提示和弹窗；各 feature CSS 继续负责自己的布局。迁移期间允许页面逐个采用令牌，但最终删除米白/深绿页面私有主题变量和宣传式大标题规则，避免两套主题长期并存。

**Tech Stack:** React 19、TypeScript 5.9、CSS 自定义属性、现有 feature CSS、Vitest、Testing Library、Playwright、axe-free 语义/键盘断言与真实浏览器检查。

## Cross-plan order

- Task 1 先独立执行，为日期工作台结构增强和跨日期发布明细总表提供共享令牌。
- 然后执行日期工作台结构增强计划和跨日期发布明细总表计划。
- 最后继续本计划 Tasks 2–7，统一首页、版本记录、管理员和旧审核区域。
- 本计划取代既有米白/深绿视觉语言，但不得改变既有路由、数据口径、恢复流程、权限或写入命令。

## Global Constraints

- 页面背景 `#F5F8FB`、表面 `#FFFFFF`、弱表面 `#EDF4FA`、主蓝 `#1769AA`、强蓝 `#0D4F86`、正文 `#17324D`、弱正文 `#60788D`、边框 `#C7D6E2`、细边框 `#DFE8EF`。
- 成功 `#287A55`、警告 `#946B16`、危险 `#B33A3A` 只表达真实状态；颜色不得是唯一信息。
- 正文 14px，紧凑表格 12–13px，页面标题 22–24px，区域标题 16–18px，正文行高至少 1.4。
- 基础间距 4px；常用 8/12/16/24px；默认控件 36px，紧凑控件 32px；圆角 4–6px。
- 禁止渐变、玻璃、发光、装饰性指标卡、宣传式 Hero、大面积胶囊和普通区域阴影。
- 768px 以下导航折叠；业务宽表只在自身容器横向滚动；页面本身不能横向溢出。
- 所有交互有可见焦点，文本达到 WCAG AA，200% 缩放可用，减少动画偏好关闭非必要过渡。
- 视觉迁移不改变管理员、版本、导入、审核、发布、恢复和权限流程；不得借机重写服务层。
- 保留当前脏工作区中的全部用户改动；禁止暂存、提交、推送和清理工作树。

---

### Task 1: 语义令牌、基础控件和状态组件

**Files:**
- Create: `frontend/src/design-system/tokens.css`
- Create: `frontend/src/design-system/tokens.test.ts`
- Create: `frontend/src/design-system/primitives.css`
- Create: `frontend/src/design-system/StatusMessage.tsx`
- Create: `frontend/src/design-system/StatusMessage.test.tsx`
- Create: `frontend/src/design-system/PageHeader.tsx`
- Create: `frontend/src/design-system/PageHeader.test.tsx`
- Modify: `frontend/src/main.tsx`
- Modify: `frontend/src/styles.css`

**Interfaces:**
- Global CSS variables use the exact semantic names in the approved design.
- `StatusMessage` accepts `{kind: "info" | "success" | "warning" | "danger"; title: string; children?: ReactNode; action?: ReactNode}`.
- `PageHeader` accepts `{eyebrow?: string; title: string; description?: ReactNode; meta?: ReactNode; actions?: ReactNode}` and renders one compact page heading.
- Shared classes are `.ui-button`, `.ui-button--primary|secondary|danger|text`, `.ui-field`, `.ui-surface`, `.ui-toolbar`, `.ui-dialog`, `.ui-table`, and `.ui-status`.

- [ ] **Step 1: 写令牌契约测试**

```ts
it("exposes the approved semantic color tokens", () => {
  const css = readFileSync(resolve("src/design-system/tokens.css"), "utf8");
  expect(css).toContain("--color-page: #F5F8FB");
  expect(css).toContain("--color-primary: #1769AA");
  expect(css).toContain("--color-danger: #B33A3A");
  expect(css).not.toMatch(/linear-gradient|backdrop-filter|text-shadow/);
});
```

Place this source assertion in `frontend/src/design-system/tokens.test.ts` using Node's `fs` APIs available to Vitest.

- [ ] **Step 2: 运行测试并确认文件缺失**

Run: `Set-Location frontend; pnpm test --run src/design-system/tokens.test.ts src/design-system/StatusMessage.test.tsx src/design-system/PageHeader.test.tsx`

Expected: FAIL because the design-system files do not exist.

- [ ] **Step 3: 创建令牌文件**

```css
:root {
  --color-page: #F5F8FB;
  --color-surface: #FFFFFF;
  --color-surface-muted: #EDF4FA;
  --color-primary: #1769AA;
  --color-primary-strong: #0D4F86;
  --color-text: #17324D;
  --color-text-muted: #60788D;
  --color-border: #C7D6E2;
  --color-border-subtle: #DFE8EF;
  --color-success: #287A55;
  --color-warning: #946B16;
  --color-danger: #B33A3A;
  --focus-ring: 0 0 0 3px rgb(23 105 170 / 24%);
  --radius-control: 5px;
}
```

Add soft status backgrounds, spacing scale, font sizes, control heights and z-index layers. Do not encode feature names into global tokens.

- [ ] **Step 4: 创建基础控件样式**

Normalize buttons, links, input/select/textarea, labels, toolbars, surfaces, tables, dialogs, focus, disabled and loading states. Use borders for ordinary layer separation and shadows only on dialogs/fixed action bars.

- [ ] **Step 5: 实现共享状态和页面标题组件**

```tsx
export function StatusMessage({ kind, title, children, action }: StatusMessageProps) {
  return <section className={`ui-status ui-status--${kind}`} role={kind === "danger" ? "alert" : "status"}>
    <div><strong>{title}</strong>{children}</div>{action}
  </section>;
}
```

The component always renders text; decorative status marks use `aria-hidden="true"`.

- [ ] **Step 6: 在入口按正确层级加载 CSS**

Import `tokens.css` first, then `primitives.css`, then the existing `styles.css`. Remove duplicated root palette declarations from `styles.css` only after every referenced variable has a semantic replacement.

- [ ] **Step 7: 运行共享层测试和静态检查**

Run: `Set-Location frontend; pnpm test --run src/design-system; pnpm lint; pnpm typecheck; pnpm build`

Expected: PASS.

- [ ] **Step 8: 检查差异**

Run: `Set-Location ..; git diff --check; git status --short`

Expected: nothing staged.

### Task 2: 应用外壳、登录页和导航

**Files:**
- Modify: `frontend/src/app/App.tsx`
- Modify: `frontend/src/app/App.test.tsx`
- Modify: `frontend/src/styles.css`

**Interfaces:**
- Desktop keeps stable left navigation and compact top bar.
- Mobile adds an explicit labelled navigation toggle; it does not remove or alter role-based links.
- Top bar continues to show site, environment, reporting timezone and account state.

- [ ] **Step 1: 写导航和角色不变测试**

Assert admin sees 发布总表/发布明细/数据审核/版本记录/管理员控制台, data_manager lacks admin, viewer lacks write routes, and all roles retain logout/site/timezone text. Add keyboard toggle and `aria-expanded` assertions for narrow navigation.

- [ ] **Step 2: 把外壳结构改为紧凑蓝白布局**

Use the existing `AppShell` business props and route guards. Replace decorative monogram/large boundary blocks only where they compete with navigation; keep site boundary and connection state as compact labelled metadata.

- [ ] **Step 3: 实现窄屏导航状态**

```tsx
<button aria-controls="primary-navigation" aria-expanded={navigationOpen} aria-label="打开主导航" className="app-nav-toggle" type="button" />
```

Close after route navigation and on Escape; restore focus to the toggle. Do not use CSS-only hidden navigation that remains focusable off-screen.

- [ ] **Step 4: 统一登录、站点加载和会话错误状态**

Apply shared surface, field, button and status styles without changing login/CSRF/logout calls or error recovery.

- [ ] **Step 5: 运行应用测试**

Run: `Set-Location frontend; pnpm test --run src/app/App.test.tsx; pnpm lint; pnpm typecheck`

Expected: all route and role tests PASS.

- [ ] **Step 6: 检查差异**

Run: `Set-Location ..; git diff --check; git status --short`

Expected: nothing staged.

### Task 3: 首页、日期工作台和发布明细首批页面

**Files:**
- Modify: `frontend/src/features/dashboard/PublishedDashboard.tsx`
- Modify: `frontend/src/features/dashboard/PublishedDashboard.css`
- Modify: `frontend/src/features/dashboard/PublishedDashboard.test.tsx`
- Modify: `frontend/src/features/workbench/DateWorkbenchPage.tsx`
- Modify: `frontend/src/features/workbench/DateWorkbenchPage.css`
- Modify: `frontend/src/features/workbench/DateWorkbenchPage.test.tsx`
- Modify: `frontend/src/features/published-details/PublishedDetailLedgerPage.tsx`
- Modify: `frontend/src/features/published-details/PublishedDetailLedgerPage.css`
- Modify: `frontend/src/features/published/PublishedDayPage.tsx`

**Interfaces:**
- 首页 retains 每日总表/产品总表 behavior and adds/retains 发布明细 as a first-screen entry.
- Workbench retains upload, recognition, editing, revision, undo, validation and publication behavior.
- Published detail pages remain read-only.

- [ ] **Step 1: 写紧凑层级测试**

Assert each page has exactly one `h1`, one visibly primary action per action region, labelled filters, existing tables/status content, and no removed business controls. Verify viewer variants contain no write buttons.

- [ ] **Step 2: 用 `PageHeader` 替换宣传式标题区**

Keep data-scope explanations as one concise sentence or accessible help text. Move date/month/status/actions into a compact toolbar so tables begin in the first viewport.

- [ ] **Step 3: 迁移首页表格和商品卡**

Replace feature-private cream/green variables with semantic tokens, retain fixed headers/first column, table sorting, product dialog focus trap and status text. Do not turn desktop rows into cards.

- [ ] **Step 4: 迁移工作台和发布明细**

Apply the shared toolbar, fields, buttons, state messages, table tokens and dialog styles. Preserve yellow edits, red conflicts, brief green save feedback, and blue selected states with text/icon equivalents.

- [ ] **Step 5: 完成三个断点样式**

At 1280px keep high density; at 768px wrap toolbars; at 390px keep page containment and local table scrolling. If the existing homepage mobile contract uses a compact grouped list, preserve that behavior rather than forcing the wide workbench rule onto it.

- [ ] **Step 6: 运行首批页面测试**

Run: `Set-Location frontend; pnpm test --run src/features/dashboard/PublishedDashboard.test.tsx src/features/workbench/DateWorkbenchPage.test.tsx src/features/published-details src/app/App.test.tsx`

Expected: PASS. This task starts only after the published-details dependency named in Cross-plan order exists.

- [ ] **Step 7: 检查差异**

Run: `Set-Location ..; git diff --check; git status --short`

Expected: nothing staged.

### Task 4: 版本记录页面统一

**Files:**
- Modify: `frontend/src/features/versions/VersionHistory.tsx`
- Modify: `frontend/src/features/versions/VersionHistory.css`
- Modify: `frontend/src/features/versions/VersionHistory.test.tsx`

**Interfaces:**
- Version selection, current publication mark, draft status, lineage, notes, move-date, undo-move and revision creation remain unchanged.
- Status always has text; colors only reinforce published/draft/discarded/risk states.

- [ ] **Step 1: 写业务控件保留测试**

For each supported role/state, assert the same filters, version list, current publication text, lineage, notes and allowed actions before changing CSS. Add one assertion that dialogs keep close/Escape/focus behavior.

- [ ] **Step 2: 移除页面私有主题令牌**

Delete `--version-ink`, `--version-paper`, `--version-blue`, `--version-green`, `--version-line` and replace each use with global semantic tokens. Keep only feature-specific layout variables if they have no global semantic meaning.

- [ ] **Step 3: 压缩 Hero 和深色 docket**

Use `PageHeader`/shared surface patterns; reduce the page title to 22–24px; convert the dark docket into a white/muted bordered summary row. Keep version facts and lineage scannable at high density.

- [ ] **Step 4: 统一筛选、状态、列表、详情和弹窗**

Use shared fields/buttons/status/dialogs. Danger styling stays on undo/move risk controls and includes explicit risk copy.

- [ ] **Step 5: 运行版本测试**

Run: `Set-Location frontend; pnpm test --run src/features/versions/VersionHistory.test.tsx; pnpm lint; pnpm typecheck`

Expected: PASS.

- [ ] **Step 6: 检查差异**

Run: `Set-Location ..; git diff --check; git status --short`

Expected: nothing staged.

### Task 5: 管理员控制台统一

**Files:**
- Modify: `frontend/src/features/admin/AdminConsole.tsx`
- Modify: `frontend/src/features/admin/AdminConsole.css`
- Modify: `frontend/src/features/admin/AdminConsole.test.tsx`

**Interfaces:**
- Accounts, roles, site configuration, backup, audit and high-impact confirmations retain their current API calls, idempotency keys, permission checks and result messages.
- Only admin can route to or render the console.

- [ ] **Step 1: 建立管理员流程回归断言**

Assert user creation/update, site config creation, maintenance/backup actions, audit reads, confirmation text, disabled/loading states, and non-admin denial still work.

- [ ] **Step 2: 统一控制台页面层级**

Use compact `PageHeader`, section headings, bordered surfaces and tables. Remove decorative large headings and unrelated whitespace; retain one primary action per section rather than per page when sections are independent admin tasks.

- [ ] **Step 3: 统一高影响操作反馈**

Use danger button/status/dialog patterns; retain explicit confirmation text and never downgrade confirmation to color-only or a generic browser confirm if the current flow is richer.

- [ ] **Step 4: 运行管理员测试**

Run: `Set-Location frontend; pnpm test --run src/features/admin/AdminConsole.test.tsx src/app/App.test.tsx; pnpm lint; pnpm typecheck`

Expected: PASS.

- [ ] **Step 5: 检查差异**

Run: `Set-Location ..; git diff --check; git status --short`

Expected: nothing staged.

### Task 6: 旧导入审核与高级恢复区域统一

**Files:**
- Modify: `frontend/src/styles.css`
- Modify: `frontend/src/features/import-review/ImportReviewFlow.tsx`
- Modify: `frontend/src/features/import-review/ReviewDataTable.tsx`
- Modify: `frontend/src/features/import-review/ImportReviewFlow.test.tsx`
- Modify: `frontend/src/features/import-review/ReviewDataTable.test.tsx`
- Modify: `frontend/src/features/import-review/DraftReviewGate.test.tsx`
- Modify: `frontend/src/features/import-review/BatchNotePanel.test.tsx`
- Modify: `frontend/src/features/import-review/MergeDecisionMatrix.test.tsx`
- Modify: `frontend/src/features/import-review/SourceFilePreview.test.tsx`

**Interfaces:**
- Intake, inspection, parse, materialize, conflict choice, draft review, validation, publication, notes, row state, restore and recovery flows remain intact.
- Advanced review stays visually secondary to the date workbench but remains fully discoverable and usable.

- [ ] **Step 1: 锁定审核流程行为**

Run existing import/reducer/recovery/table tests before editing and record the baseline count. Add missing assertions for conflict choices, destructive confirmation, notes visibility, drawer focus and viewer boundaries if not already covered.

- [ ] **Step 2: 将通用类映射到设计系统**

Migrate `.primary-action`, `.secondary-action`, `.quiet-action`, `.field-stack`, `.form-error`, `.form-notice`, `.workspace-loading`, drawers, dialogs and review tables to semantic tokens/shared primitives while preserving class names used by current tests.

- [ ] **Step 3: 降低高级区域视觉层级**

Remove repeated promotional copy and oversized section headings; keep evidence IDs, risk explanations, ruleset/version labels and recovery choices. Do not hide advanced controls behind an unlabeled icon.

- [ ] **Step 4: 统一表格、抽屉和证据区**

Use blue-white table headers, subtle borders, visible focus and bounded internal scrolling. Maintain current edit/history/restore source semantics and dialog roles.

- [ ] **Step 5: 运行审核完整测试**

Run: `Set-Location frontend; pnpm test --run src/features/import-review; pnpm lint; pnpm typecheck; pnpm build`

Expected: test count is not lower than the recorded baseline and all tests PASS.

- [ ] **Step 6: 检查差异**

Run: `Set-Location ..; git diff --check; git status --short`

Expected: nothing staged.

### Task 7: 全站响应式、无障碍和视觉门禁

**Files:**
- Create: `frontend/tests/e2e/blue-white-visual-system.spec.ts`
- Create: `frontend/src/design-system/visualContract.test.ts`
- Modify: `frontend/src/design-system/primitives.css`
- Modify: `frontend/src/styles.css`
- Modify: feature CSS files only for defects found by the gate
- Modify: `docs/user-guide/dashboard.md`
- Modify: `docs/user-guide/import-review.md`

**Interfaces:**
- Browser matrix covers login/authenticated shell, dashboard, date workbench, published details, versions, admin and advanced review at 1280/768/390px.
- Reduced motion and 200% zoom are explicit acceptance conditions.

- [ ] **Step 1: 添加禁止视觉模式的源检查**

Scan active CSS for gradients, backdrop blur, glow/text-shadow, feature-private cream/green theme variables, and page titles above 24px. Allow an exception only when documented inline for a functional chart/data visualization, not decoration.

- [ ] **Step 2: 写页面级浏览器矩阵**

```ts
for (const width of [1280, 768, 390]) {
  test(`keeps authenticated pages contained at ${width}px`, async ({ page }) => {
    await page.setViewportSize({ width, height: 900 });
    for (const path of ["/", "/ledger/published-details", "/versions"]) {
      await page.goto(path);
      expect(await page.locator("body").evaluate((body) => body.scrollWidth <= body.clientWidth)).toBe(true);
      await page.keyboard.press("Tab");
      await expect(page.locator(":focus")).toBeVisible();
      expect(await page.locator(":focus").evaluate((node) => getComputedStyle(node).outlineStyle !== "none")).toBe(true);
    }
  });
}
```

- [ ] **Step 3: 添加状态和角色矩阵**

Cover loading, empty, success, warning, blocking error, offline/uncertain, permission denied, conflict and high-impact busy states. Capture admin/data_manager/viewer screenshots or DOM evidence without placing secrets or business data in artifacts.

- [ ] **Step 4: 验证 200% 缩放和减少动画**

Use browser context/device scale or CSS zoom in a controlled test, inspect final-row visibility and dialog controls, and emulate `prefers-reduced-motion: reduce` to assert nonessential transitions are disabled.

- [ ] **Step 5: 更新用户文档截图说明与页面名称**

Document the blue-white navigation, compact headers, table-local scrolling, status text and responsive behavior. Do not change operational instructions or claim a feature exists before its implementation test passes.

- [ ] **Step 6: 运行前端完整门禁**

Run: `Set-Location frontend; pnpm test --run; pnpm lint; pnpm typecheck; pnpm build; pnpm test:e2e -- blue-white-visual-system.spec.ts`

Expected: PASS. If authenticated browser fixtures are unavailable, record the browser gate as not run and do not substitute screenshots from another site.

- [ ] **Step 7: 运行后端权限烟雾回归**

Run: `Set-Location ..; .\.venv\Scripts\python.exe -m pytest backend/tests/unit/test_openapi_contract.py -q`

Expected: PASS, proving visual route edits did not alter server role contracts.

- [ ] **Step 8: 最终只读检查**

Run: `git diff --check; git status --short`

Expected: intended UI changes remain unstaged, user work is preserved, and no backend business service, migration or database state was changed by this visual plan.
