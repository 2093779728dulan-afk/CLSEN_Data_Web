# Shared UI boundary

## 当前路由与样板覆盖核对（2026-10-08）

本节是当前本地覆盖概览；后文带日期的开发记录保留原版本与原确认范围。

视觉比较以 CI 的 Ubuntu 24.04、Playwright Chromium 1.62.1 和锁定 Noto Sans SC 5.3.0 为参考环境。更新基线需沿用用户批准，在匹配的 Linux 运行时生成并独立比较，保留原图和审批历史。Windows 可用于开发与体验；其原生月份控件、字体排版截图不能直接覆盖 Ubuntu 参考图。

- 实际 `App.tsx` 的 19 个路由声明中，17 个承载页面，`/dashboard` 和 `*` 为重定向。当前核对限定 `p0_catalog` 模式；未将 `legacy_parser` 的旧商品界面计入本次结论。
- 528 个已注册样板全部纳入现有视觉清单。原遗漏的 `Design System/Structure and navigation / Header` 已补齐三档基线；既有样板和业务组件未新增或改写。
- 1280/768/390 三档共 1,584 个常规基线文件，另有原商品筛选菜单 6 个基线，均已核对存在。**文件存在与注册齐备不等于全套回归通过**；本轮仅执行 Header 三档视觉比较、无障碍检查及全样板注册合同，其他仍有效结果按原范围复用。
- 原清单合同同时比较全部已注册故事与视觉清单，防止新故事仅出现在展示平台却遗漏回归。允许使用现有页面样板覆盖共享组件，不按组件数量强制增加独立故事。

| 实际入口 | 复用样板 |
| --- | --- |
| `/`、`/ledger/published-details` | Published Daily Ledger、Published Detail Ledger |
| `/published/:reportDate`、`/published-details/:reportDate` | Date Workbench、Published Day Detail |
| `/products`、`/products/:style_id` | Product Ledger、Product Detail；Coverage Reconciliation、Metric Help、Trend Chart、Trend Point Matrix |
| `/catalog`、`/catalog/styles/:style_id` | Catalog Product List、Catalog Setup、Catalog Style Detail、Catalog Editors、Read Feedback、Source Evidence |
| `/catalog/imports/:import_id` | Catalog Import Review、Section Editors、Workflow Forms及原审核组合 |
| `/catalog/unmatched`、`/catalog/maintenance`、`/catalog/versions` | Unmatched Sources、Catalog Operations、Maintenance Overview、Workbook、Catalog Versions |
| `/review/:reportDate`、`/review-advanced/:reportDate` | Date Workbench、Advanced Review Workspace、Import Intake、Draft Review、Import Evidence及原审核组合 |
| `/review/batch/:runId`、`/versions` | Batch Review、Version History、Version Commands |
| `/admin` | Admin Accounts、Site Configuration、Audit、Maintenance、Recovery |
| 登录与全局导航 | Session Entry、Workspace Shell |

此表说明实际入口有对应展示与状态样板，不证明每个业务分支已穷尽、真实数据已验收或已部署。三条主要只读跨页路径见上一批 `integrated-navigation-20261008`；完整审核写入链及正式发布验证不由本次静态覆盖核对替代。

历史确认核对保留 12 个早期批次的原 `user_verified=false`。其中 ClickSpark 已有“彩色点击反馈”范围确认，整批仍包含其他页面；另有明确拒绝过的旧控件方向及后来替换的实现。既有新版页面确认继续有效，不凭旧批标记推断新版未体验，也不将局部反馈扩写为整批或发布确认。用户本轮“批准继续下一步”记录为继续覆盖核对授权；上一批跨页修复仍保持待用户体验。

`src/design-system` is the controlled entry point for shared UI. Consumers import public components from `design-system/index.ts`; component-specific implementation files and third-party primitives remain internal.

## Rules

- Use semantic values from `tokens.css`; do not introduce page-local brand colors or arbitrary stacking levels.
- Put component styles in CSS Modules. Global CSS is limited to tokens, reset, typography foundations, and temporary compatibility rules for pages not yet migrated.
- Prefer native HTML when it already provides the required semantics. Use Radix only for composite focus, keyboard, or overlay behavior, and wrap it behind a project-owned component.
- Public props describe product behavior rather than Radix APIs. Application code must not import Radix packages directly.
- Every new interactive component needs focused tests for its own accessible name, keyboard behavior, disabled/loading behavior when applicable, and focus return.
- Run `pnpm test:tokens` for shared component styles. Raw color values and raw animation or transition durations are rejected in CSS Modules; an unavoidable exception must exactly match `token-policy-allowlist.json` and record both a reason and an approver.

## Current public components

- Actions and status: `Button`, `StatusBadge`, `StatusMessage`.
- Structure: `PageHeader`, `Dialog`, `EmptyState`, `ErrorState`, `Skeleton`, `Spinner`, `Table`.
- Forms and navigation: `FormField`, `Input`, `SearchInput`, `FilterToolbar`, `Select`, `Checkbox`, `Radio`, `Tooltip`, `Tabs`, `Menu`, `Pagination`.
- Feedback: `ToastProvider`, `Toast`.

The published data table is the first consumer of the shared form and pagination controls. Its horizontal table scroll remains independent from the pagination controls.

## React Bits GlideSelect（2026-10-06）

本项随后按用户“颜色与我们全局不太符合”反馈改为现有浅色tokens：白色surface、浅蓝info-bg滑行高亮、深灰text与primary蓝色选中标记，边框/阴影和forced-colors使用项目/系统值。下方暗色配置是初版历史；当前配置由GlideSelectField的CSS变量确定。商品状态和排序共用包装，180/220ms、rememberPosition与业务状态不变。截图中的商品/待处理/目录版本/批量维护属于NavLink路由导航；本轮只查询导航优化方案，没有改路由或引入Motion/GSAP依赖。增量验证与基线结果见同任务glide-select-20261006/theme-refinement/result.json。

商品主档实际 `/catalog` 与现有 `Pages/Catalog Product List/Reference` 共用 `CatalogProductList`，商品状态和排序使用公共入口的 `GlideSelectField`。JSX/CSS 来自官方 JS-CSS registry；准确源码来源、JSON hash、许可证及必要适配记录见 [react-bits/README.md](./react-bits/README.md)。受控 `value` 与 `onChange(value, option)` 更新原列表状态并将页码设为1；真实选项、搜索、稳定 style_id、详情返回及刷新规则不变。

沿用用户配置：surface `#27272a`、highlight `#3f3f46`、accent/text `#f5f5f5`，md、10px圆角、176px菜单、bottom/left、180ms弹出与220ms滑行。原选项没有辅助说明，关闭tags。`rememberPosition` 按官方语义保留指针离开前的高亮，再进入时从该处滑行；关闭再打开回当前选中项。悬停不提交值。

内部保留 `glide-select` 前缀的官方普通CSS，项目布局使用CSS Module；这是明确选择JS-CSS/配色的局部适配，vendor CSS不宣称纳入CSS Module token扫描。Portal避免现有workspace裁切，屏幕边界定位、键盘、可访问名称、焦点、外部关闭及reduced motion已验证。其他页面的原生Select保持原实现。仅新增registry所列Hugeicons两包；本机UI依赖隔离，冻结发布来源四项依赖摘要保持不变。新checkout按正常package/lock安装。

本轮有效通过：8项组件交互、4项虚构API实际路由完整路径、6项受影响单测、31项无障碍检查（含6个展开菜单）及36项视觉比较；TypeScript、目标ESLint、22模块Token与生产构建通过。构建主包752.32KB/gzip226.57KB，有超过500KB提示。初始动效、减少动态效果断言及jsdom选择测试失败与修正证据保留。

原24张列表基线实际替换15/保持9，新增两菜单各三档共6张局部基线；原件、初次全页菜单图及审批历史保留。批准生成精确捕获小控件变化，正常比较阈值保持；manifest共96张，本轮未全套执行。截图只验证静态状态，动画另有时长/逐帧滑行/触摸检查。development_complete=true / ready_for_user_review=true / user_verified=false / accepted=false / UI_deployed=false；证据为同任务 `glide-select-20261006/result.json`。

## Catalog page entrance（2026-10-06）

`PageTransition` 复用现有 Motion 的 initial/animate 入场模式，时长读取 motion-content-enter（180ms），位移读取 space-2（8px）；CSS Module 只组织容器和减少动态效果覆盖。CatalogLayout 以原 pathname key 替换原 Fragment，保留原内容重建和草稿边界，不因搜索参数、筛选、分页、读取或保存状态而重新挂载。商品主档实际子页和现有Reference共用；未推广到其他应用模块。

路由改变后新内容淡入并从下方轻微上移，旧内容按原路由立即卸载，不保留延迟可操作的旧页面。减少动态效果时直接显示；CSS覆盖也能跟随挂载期间系统偏好改变。标题/导航/角色控制保持，已有后台API加载与失败恢复负责真实内容状态；入场动画不声明数据加载成功，也不模拟加载进度。无新增依赖。

本轮3项组件完整路径/逐帧动画、2项实际虚构API路由（包含返回/硬刷新/筛选/分页/稳定详情身份）与30项已有视觉比较通过；TypeScript、目标ESLint、24模块Token和构建通过。静态基线保持，动画采样另记录opacity/y及reduced motion。前批无障碍结果仍适用于未变的名称/链接/角色，不把本轮静态包装称为新的全站无障碍检查。主包gzip268.33KB，500KB提示保留。本地development_complete=true / ready_for_user_review=true / user_verified=false / accepted=false / UI_deployed=false；证据同任务 catalog-page-transition-20261006/result.json。

## Animated route navigation（2026-10-06）

公共 `RouteNavigation` 适配 Motion 官方共享下划线样例，样式复用已有 Tabs 的尺寸、字体、边框及全局 tokens。基础仍是 React Router NavLink：通过 aria-current 显示当前页面、真实 href 支持浏览器链接行为，Tab/Enter 激活保留；导航不是同页 tabpanel，不添加不匹配的 ARIA Tabs 角色。实例独立 LayoutGroup 避免两个导航共享同一指示器；layoutScroll 支持横向滚动。动效时长来自 motion-content-enter（180ms），减少动态效果时直接切换。悬停不移动已选下划线，只有路由变化才移动。

CatalogLayout 的原四个地址和 end 匹配、canManage 权限及 pathname 内容重建边界保持；全部实际商品目录子页采用同一个导航。末项键盘聚焦时滚动至完整可见，窄屏不换行挤压按钮，不把水平溢出传到文档。来源与 MIT 许可证见 THIRD_PARTY_NOTICES.md / LICENSE.motion.md。新增 motion@14.0.0；本机依赖隔离，冻结发布四项摘要保持不变。主包878.43KB/gzip268.23KB，相比上一浅色批次 gzip增加41.63KB，Vite 500KB提示保留。

既有商品列表Reference已补三处明确标注虚构的导航目的地，以便验证四路切换与返回；不是业务数据样板，也不模拟维护写入。没有新增故事或演示入口。实际路由采用虚构API验证目录版本切换/硬刷新/返回、筛选与稳定详情ID；真实业务数据及生产未更改。现有视觉/a11y manifest继续覆盖实际使用本导航的八个列表状态与展开菜单，未宣称完整96张执行。首轮窄屏焦点边缘不足已修复；默认减少动态效果前置导致的动画断言失败已按上游挂载时偏好规则修正，原失败保留。当前结果见同任务 catalog-navigation-20261006/result.json；development_complete=true / ready_for_user_review=true / user_verified=false / accepted=false / UI_deployed=false。

## Storybook workspace

### Refined review controls (2026-10-06)

User feedback "感觉没有体现出是高级前端做出了的感觉" rejects the preceding visual direction; that version is not user-verified. ReviewControls now uses a compact product workspace hierarchy, a neutral palette from workspace tokens, explicit result metadata, an icon-only help action, removable conditions and a recovery-focused empty state. SearchInput adapts shadcn/ui InputGroup (MIT); FilterToolbar is shared by the story and routed CatalogImportReview. Brand blue remains the focus/action color. These workspace tokens were introduced locally; the later global refinement below now reuses their neutral colors for shared defaults.

SearchInput remains a controlled native input with its label/description/invalid/readonly/disabled/ref contract. Clear and removable-filter actions return keyboard focus to search. FilterToolbar only changes local display conditions; it does not mutate drafts or issue requests. Catalog toolbar counts and table visibility reuse the exact existing filter predicate via filterCatalogReviewRows; row_key, SKU identities, revision-bound saves, transactions and authorization are unchanged. Result counts describe loaded rows in the current section, not an unrequested global data query.

The existing ReviewControls and seven catalog states continue to use the same manifest and 1280/768/390 viewports. No new test platform, dependency, production rollout or global route transition is introduced. Original snapshots and baseline history remain in the task evidence directory. Current results are in development-summary.json; user_verified=false and UI_deployed=false remain until explicit review and separate release authorization.

### Reusable motion (2026-10-06)

Prefer adapting mature open-source components before designing new primitives. This batch adapts shadcn/ui's MIT Spinner and Dialog state animation patterns; sources and license are retained in [THIRD_PARTY_NOTICES.md](./THIRD_PARTY_NOTICES.md). Keep React/Vite, CSS Modules, existing Radix wrappers and tokens; no animation library or Tailwind migration is required.

- Components select semantic motion tokens: `motion-interaction` (120ms), `motion-content-enter` (180ms), overlay entrance (200ms) / exit (120ms), and spinner (800ms). Entry and exit use separate easing. Existing base tokens remain compatible.
- `Button loading loadingLabel="正在保存修改"` swaps visible labels within one grid cell. Both labels participate in sizing; only the current label is accessible. The pending action is disabled and exposes `aria-busy`; it remains readable instead of looking unavailable. Use a stable idle label during the request. The component never sends requests or declares success itself.
- `Spinner` is the shared loading indicator; inside an already labelled button use `aria-hidden`. Reduced motion stops rotation rather than slowing it down. Hidden pending spinners pause. Skeleton shimmer, feedback entrances and Dialog/Tabs animations also stop under reduced motion.
- Dialog uses Radix `data-state` CSS animations for entrance and exit. Radix controls unmount, Escape and focus. Do not add manual timeouts or `forceMount` just to support CSS exits.
- `Tabs animate keepMounted` opts into a short content fade while retaining mounted drafts; ordinary consumers keep their existing default. Only active panels appear. Do not change keys or remount forms to trigger an animation. This batch applies category transitions in the review page; it does not change global route navigation.
- StatusMessage fades in once when mounted. Failure messages keep their alert semantics, input and recovery instructions; no shake, automatic retry, fake progress or success timer is introduced.
- Routed CatalogImportReview and its stories share the implementation: actual request state drives saving/reload labels; initial loading uses existing Skeleton and real loaded-section progress. Background reload retains current content. All existing identity, workflow revision, permissions, 500-row batch limit and post-save read recovery behavior remain unchanged.
- `Actions and status / Save Feedback` demonstrates idle → pending → success/failure with fictional latency only. It is included in the existing visual and accessibility manifests on all three viewports. `tests/storybook/motion.spec.ts` checks stable action width, failure recovery, focus return, draft retention and no-motion behavior. Static screenshots verify final states, not animation timing. Old unrelated baseline failures are retained separately.

Run `pnpm storybook` for the local component workspace and `pnpm storybook:build` for its static build. Stories cover the current public components across primary, disabled, loading, long-Chinese, validation, dialog, and pagination states.

`pnpm test:a11y` scans every design-system story at 1280px and the responsive subset at 768px and 390px. Serious or critical WCAG findings fail the command. `pnpm test:visual` compares the approved screenshots at all three widths. Both commands use Playwright Chromium, reduced motion, `zh-CN`, `Asia/Shanghai`, device scale 1, and the bundled `Noto Sans SC Variable` font.

Product experience is desktop-first. PC layouts receive the primary interaction and visual-polish effort; the 768px and 390px checks protect baseline usability only: core content remains readable, key actions remain operable, and overflow does not block the workflow. Tablet and mobile do not require desktop-equivalent refinement unless a later product requirement explicitly raises their priority.

Visual differences are never accepted in CI. To create or update baselines after reviewing the rendered stories, set `VISUAL_BASELINE_APPROVED_BY` and a meaningful `VISUAL_BASELINE_REASON`, then run `pnpm test:visual:update`. The guarded command records the reviewer, reason, font, Playwright version, and timestamp beside the screenshots. Direct or CI snapshot updates are rejected.

## 导入审核规范与状态覆盖（2026-10-05）

规范源由 `tokens.css`（视觉值）、公共组件、组合实现及 Storybook 样板共同组成；Storybook 承载规范与检查，不另维护一份与产品脱节的页面实现。

| 层级 | 当前来源与复用规则 |
| --- | --- |
| Foundations | `tokens.css` 已覆盖语义颜色、间距、字号与字体、圆角、边框颜色、阴影、动效及 z-index；沿用现有蓝色数据工作台风格，不新增品牌色或视觉 primitive。 |
| Components | 22 个公共组件（含 LinkButton / ToastProvider / Spinner）由 `index.ts` 导出；按钮、表单、反馈、结构与导航故事位于 `Design System/*`。业务代码通过公共入口使用封装。 |
| Patterns / Domain | `CatalogImportSectionTable` 负责来源项、字段编辑、保存条、未保存标识与错误恢复；`CatalogImportReview` 组合页头、进度、分类、筛选、审核明细及原有校验批准操作。 |
| Reference Pages | `Pages/Catalog Import Review` 提供七个虚构数据状态（含展开的 PendingChanges 修改预览），与实际路由共用 `CatalogImportReview`，没有复制页面布局。 |
| Actual Pages | `/catalog/imports/:import_id` 的 `CatalogImportPage` 读取真实 API、权限、同修订分页明细，保持原工作流与商品身份写入边界。 |

现有状态与缺口按实际故事记录，不把组件存在当作全部状态已覆盖：

| 对象 | 已有可见状态 / 检查 | 尚未独立覆盖 |
| --- | --- | --- |
| Button | primary / secondary / danger / quiet、disabled、loading、长中文；交互测试与焦点样式 | hover / active / focus 未各自建立截图基线 |
| Input / Select / FormField | 空值、已有值、错误、disabled、可聚焦 readonly、长标签；原生选择交互 | hover / focus 状态未各自独立截图 |
| 小组件增量（2026-10-06） | Input / native Select / Checkbox / StatusBadge / Tooltip / Pagination：shadcn/ui MIT 源码样式适配；ReviewControls 联合筛选、空结果恢复和分页样板；FieldStates 新增可聚焦 readonly 与 disabled Select；mixed checkbox / forced colors / Tooltip 键盘与减少动态效果检查 | focus / hover 并非各自独立基线；原生 Select 弹出列表保持系统交互，未换成 Radix Select |
| Checkbox / Radio / Tabs / Menu / Tooltip | 选中、未选中、disabled、错误、键盘导航和组合交互、窄屏长中文 | 每个浮层与焦点组合的穷举截图 |
| Dialog / Pagination / Table / Toast / Status | 对话框交互、分页、基础表格、反馈类别、Skeleton、EmptyState、ErrorState | 全站每种表格及页面组合未穷举 |
| 导入审核页面 | Reference、PendingChanges、Loading、Empty、ReadOnly、SaveFailure、RefreshFailure；每状态 1280 / 768 / 390 三档截图与 serious/critical axe 检查 | 正式批准、身份恢复、真实来源证据不由虚构样板模拟；继续使用原 API、权限及正式验收路径 |

没有通用 Card、Drawer、Upload 或全站 Search / Filter 公共组件；本轮复用已有容器、上传路径与表单控件，不为清单数量创建空壳组件。商品详情与其他页面继续渐进采用规范，ProductTrendChart 的 review-23 参考保持。

### 草稿保存与审核操作

- 可以一次保存当前分类的所有修改，包含被搜索或“仅看待处理”隐藏的修改；跨分类切换保留本页草稿。单行保存仍可用，保存后保留其他行修改。
- 左侧分类同时显示记录、待处理及未保存数量；右侧区分来源审核项与可编辑标准字段。保存前可展开“核对本次修改”，逐字段查看原值与新值（包括筛选隐藏的修改）。这是本地草稿预览，不是服务端校验或批准预览。
- 每次请求沿用已有 decisions API 的原子事务、操作键、独立 mutation ID、稳定 row / decision-group 身份和 workflow revision。最多 500 行；超过时按钮明确保存前 500 行，剩余修改继续保留，用户再发下一批，没有自动分片或重试。
- 保存期间锁定编辑及其他工作流写入；仍有未保存修改时不能校验或批准，也不能恢复映射归属。草稿保存成功不代表批准生效。
- 被拒绝的保存保留修改，只有明确点击才重试。服务端内容发生变化时要求核对并放弃该行旧修改后再编辑，不自动合并或覆盖。
- 服务端确认保存但重新读取失败时阻止后续写入，提示重新读取，避免重复提交；读取成功后恢复操作。刷新浏览器只能恢复已保存草稿，本地未保存修改不持久化。

样板只使用 DEMO 虚构数据，可体验款式 / SKU 编辑、筛选、切换及草稿保存；校验批准按钮不向真实服务发送命令，来源证据与身份恢复不提供模拟数据。实际应用浏览器测试通过虚构 API 拦截验证路由与保存流程，不能替代真实 MySQL / 正式批准验收。

### 增量视觉回归

七种页面状态各三档全页截图，共 21 张；本次重设计更新原页面 18 张并新增 PendingChanges 3 张，更新前原件保存于任务证据目录，原有其他组件 27 张不覆盖，总比较范围为 48 张。`storybookGateManifest.ts` 是截图及无障碍范围入口，`storybookGateSupport.ts` 把两个失败故事推进至实际失败状态，并等待修改预览展开后再比较。

2026-10-06动效批次在上述范围新增 SaveFeedback 三档基线，manifest 现为51张。已定向执行导入审核、按钮、Dialog及新增反馈共30张：首次旧基线比较26通过/1手机加载布局差异，核看后只更新该加载故事范围（实际仅手机图变化），新增反馈3张；最终6张加载/新增反馈比较通过，其余24张沿用本批有效结果。旧4个其他手机差异与基线保持，未宣称51张全套通过。当前新增基线为用户授权范围内的代理视觉审阅，仍不是用户体验验收。

随后的小组件批次新增 ReviewControls、StatusStates、PaginationStates 各三档视觉基线，manifest 总范围60张。本轮先比较36张旧图（25通过、11差异），核看表单新增状态、原生 Checkbox 方框与尺寸、徽标和手机布局后，仅用既有 updater 更新本次范围；原基线、失败图和 trace 保存在 `small-components-20261006/before` 与 `visual-initial`。旧 FieldStates / SelectionStates 手机基线因本次明确改版而被替代，不能据此声称历史环境差异原因已查明；旧 Toast / LoadingEmptyAndError 手机图保持。新增9张，实际替换11张原图，审批历史追加且 user_verified=false。此处只记录覆盖与基线范围，当前比较结果以同任务 development-summary 为准，不宣称60张全套通过。

体验入口：`http://127.0.0.1:17641/?path=/story/design-system-form-controls--review-controls`。可搜索虚构款号/名称、选择处理状态、用 Space 勾选待处理、前后翻页、清空结果后重置；“帮助”支持悬停/键盘聚焦与 Escape。原生 Select 继续使用系统弹出列表。复用方无需引入新的依赖或视觉组件；导入审核已有 Input / Checkbox / StatusBadge 直接采用公共实现。Hover、Focus、禁用、错误、只读及减少动态效果沿用公共组件，无全站路由动画接入。

Token 检查包含共享组件模块及 `CatalogImportReview.module.css`，没有宣称覆盖旧版全站 CSS。审核工作区、表格与手机编辑卡片布局由该模块控制，移除旧 `catalog-review-panel` 类以避免卡片变形规则叠加；原工作流和其他目录页仍保留兼容样式。

本次视觉参考为 [Linear 重设计](https://linear.app/now/how-we-redesigned-the-linear-ui)的工作区层次与 [Basis 批量编辑](https://design.basis.com/patterns/bulk-editing)的修改核对。复用项目现有 React、Radix、Lucide 组件及 Token，不复制未核明许可的第三方源码，不增加依赖。

增量更新通过已有 guarded updater，设置 `VISUAL_BASELINE_STORY_FILTER=pages-catalog-import-review` 限定范围；仍需 reviewer / reason 且不能在 CI 接受差异。审批 JSON 保留原记录并追加 scoped updates。本轮新增基线是在用户授权范围内由 Codex 视觉审阅建立，用户体验状态仍待确认。

## Current dependency record

| Package | Version | License | Purpose |
| --- | --- | --- | --- |
| `lucide-react` | `1.41.0` | ISC | Consistent interface icons |
| `@radix-ui/react-dialog` | `1.1.23` | MIT | Dialog focus, keyboard, portal, and dismissal behavior |
| `@radix-ui/react-tooltip` | `1.2.16` | MIT | Tooltip timing, positioning, portal, and dismissal behavior |
| `@radix-ui/react-tabs` | `1.1.21` | MIT | Tab keyboard navigation, selection, and panel relationships |
| `@radix-ui/react-dropdown-menu` | `2.1.24` | MIT | Menu focus, keyboard navigation, portal, and dismissal behavior |
| `@radix-ui/react-toast` | `1.2.23` | MIT | Toast viewport, announcement, swipe, and close behavior |
| `storybook` | `10.6.0` | MIT | Isolated component workspace and static build |
| `@storybook/react-vite` | `10.6.0` | MIT | React and Vite Storybook framework integration |
| `@storybook/addon-a11y` | `10.6.0` | MIT | In-workspace accessibility inspection |
| `@axe-core/playwright` | `4.13.0` | MPL-2.0 | Automated serious/critical accessibility gate |
| `@fontsource-variable/noto-sans-sc` | `5.3.0` | OFL-1.1 | Fixed cross-platform Storybook and screenshot font |

Checkbox and Radio remain native inputs because HTML already provides their selection and grouping semantics. Tooltip, Tabs, Menu, Toast, and Dialog use project-owned Radix wrappers because these composite interactions need coordinated focus, keyboard, portal, or announcement behavior. Consumers continue to import only from `design-system/index.ts`.

The hosted frontend profile runs the Token policy, Storybook build, accessibility gate, and approved visual comparison on Ubuntu 24.04 with the Chromium version locked by `@playwright/test`. This inventory remains incremental: the final acceptance checklist and wider page adoption are separate Stage 3 delivery work.

### 导入审核连续编辑（2026-10-06）

沿用shadcn/ui改造后的Button、FilterToolbar及原生审核表格；没有新增表格库。Tab保留原生焦点顺序，Alt+↑/↓切换到上下可见行的同一字段，Ctrl/⌘+Enter保存当前分类修改（仍最多500行），Esc仅恢复当前文本字段的编辑起始值；中文输入法组字期间不拦截这些快捷键，普通Enter和文本撤销保持原生行为。

“撤销本行修改”恢复当前读取的草稿值，不发送请求、不影响其他行或分类。保存等待期间继续沿用原权限、修订和写入锁；响应确认前不清空草稿。保存后恢复编辑焦点、文本选区及仍可用的滚动位置，已完成行被筛选隐藏时转到下一可见行，当前筛选已空则焦点留在编辑区。用户主动切换分类或控件优先，不抢回焦点。内容变短时滚动值服从浏览器新的最大范围。

仅对服务端当前修订明确标记的error行/字段显示aria-invalid与说明；定位问题打开所属分类、解除待处理过滤并聚焦对应字段。普通保存失败只提供返回修改行，不推测字段，不自动重试；已确认写入后的读取失败继续通过原重新读取路径恢复。ValidationIssues为虚构错误样板，加入既有manifest与三档视觉回归。此次验证使用虚构API，不代替真实数据库及正式发布门禁。


### 全局样式与组件优先级（2026-10-06）

沿用既有 shadcn/ui 适配组件与 Token。`primitives.css` 提供低特异性原生默认值；公共组件的 CSS Module 管理自身焦点、禁用、错误与只读状态。页面样式负责布局，不用 `.catalog-workspace input:focus-visible` 等大范围规则覆盖组件。`styles.css` 的旧黄色全局焦点已归并到统一默认值，商品主档中的旧绿/黄色、边框、圆角和卡片动效采用既有语义 Token。

无 class 的文本输入、Select、Textarea 与原生按钮采用基础控件外观；checkbox/radio/range/file/hidden 不套用文本输入尺寸。旧 `.ui-field` 的基础规则降低优先级，原生只读背景及错误边框在默认值之后定义，公共 Input 的状态仍优先。键盘默认焦点为 2px 轮廓，SearchInput 保留单一容器焦点，forced-colors 保留系统可见轮廓。没有新依赖或全站切页动画。

新增 `Design System/Form controls/GlobalDefaults`，使用虚构字段覆盖原生、旧表单与公共组件的组合。实际审核路由与原商品主档完整路径共 11 项有效结果；新样板交互验证只读不可改、错误边框、键盘勾选、组件优先、原生 details 展开与高对比度。定向 axe 13 个故事/视口结果及 manifest 通过；12 张既有定向截图无差异，新样板三档基线经代理审阅、guarded updater 添加并比较通过，总 manifest 66 张未整套重跑。新样板不是用户验收；旧无关视觉失败保留。TypeScript、定向 ESLint、20 模块 Token 检查通过。

体验：`http://127.0.0.1:17641/?path=/story/design-system-form-controls--global-defaults`。本轮仅本地样式与样板，真实站点未发布，`user_verified=false / accepted=false / UI_deployed=false`。


### 全局视觉细化（2026-10-06，继续优化）

沿用当前 shadcn/ui 适配，不引入第二套组件库。全局基础 Token 复用已存在的 workspace 中性色：页面 #FAFBFC、正文 #242A31、辅助文字 #59636E、边框 #DFE3E8、只读/次级表面 #F3F5F7；品牌蓝仍用于操作、焦点与选中状态。标题复用正文的现有字体栈，数据字体及图表序列/网格 Token 保持原值。Button 改用600字重、克制的背景变化；移除悬停上浮和大阴影。FormField 对齐原生表单的标签层级；原生按钮和旧ui-field控件采用40px最低高度，悬停不覆盖错误或只读，减少动态效果时停止新增过渡。

GlobalDefaults 使用现有 FormField/Input/Button，按基础字段与公共组件分组，桌面/平板双栏、手机单栏，包含辅助说明、只读、错误、勾选、操作区与details。不是额外的页面实现；实际应用复用同一基础Token与组件。9项组件/动效路径、11项虚构API实际路由路径通过，TypeScript、目标ESLint、20模块Token通过；由于全局基础变化，本轮使用现有全故事无障碍范围，62项（含manifest）通过。

旧视觉首次比较4通过/4差异后按上限停止，58未执行；旧失败截图和trace保留。核看布局与文字变化后，用原guarded updater在本轮全局授权范围更新28张开发基线，其余38张保留；三档66张最终独立比较通过。旧Toast/LoadingEmptyAndError手机基线随此次明确全局改版被替代，原件和此前失败仍保留，不能据新基线声称历史环境差异根因解决。基线为代理视觉审阅，用户确认仍待完成；Storybook比较通过不代表全站功能或正式发布验收。

体验入口保持GlobalDefaults与CatalogImportReview Reference。本轮development_complete=true/ready_for_user_review=true，user_verified=false/accepted=false/UI_deployed=false。没有新依赖、线上、业务数据或发布来源变更；证据global-style-polish-20261006。


### 商品主档列表与筛选（2026-10-06）

实际 `/catalog` 与 `Pages/Catalog Product List` 共用 `CatalogProductList`。复用本项目已适配 shadcn/ui 的公共控件，不增加依赖。支持商品卡与只读表格、款式编号/名称/分类搜索、启用状态筛选、自然款号/中文名称排序、12款分页；详情按稳定 `style_id` 导航，同名商品保持独立。详情返回与手动刷新保留列表上下文；整页刷新仍按原内存状态重置，不声称持久化筛选。手机卡片单栏，表格支持键盘及横向滚动。

加载、未初始化、批准空目录、筛选无结果、可重试读取失败和只读账号各有明确状态。`403` 无重试且禁用刷新；原初始化流程、来源范围及服务端授权不改。重置筛选回焦搜索框；未知商品状态只在全部状态中显示原值。卡片保留变体、Seller SKU、来源报告/观察数和日期。

八个故事三档新增24张基线，manifest总范围90张；本批独立新增24张比较通过，既有审核Reference及ReviewControls六张无差异，没有重跑全部90张。新增24项axe及更新后的manifest通过，实际路由虚构API四项、样板交互三项、直接共享控件两项及六项受影响单测有效结果通过。旧失败与原66张基线保留；新增基线为代理视觉审阅，`user_verified=false`。原单次故障fixture、场景拦截卸载及旧选择器错误只修正测试，未改变业务行为。

体验入口：`http://127.0.0.1:17641/?path=/story/pages-catalog-product-list--reference`。虚构数据无需登录；样板详情仅演示导航，不模拟真实变体/来源证据，初始化及其他目录功能请在具备账号与API的实际应用中使用。实际路由测试亦为虚构API，不证明真实数据或数据库验收。当前仅本地开发，`development_complete=true / ready_for_user_review=true / user_verified=false / accepted=false / UI_deployed=false`。


### 点击反馈与目录操作样板（2026-10-06）

`ClickSpark` 基于 React Bits 官方 [ClickSpark JS-CSS registry](https://reactbits.dev/r/ClickSpark-JS-CSS.json) 的 Canvas 径向线段算法适配到 TypeScript，没有新增依赖。原文件在任务证据保留。商品主档的 `CatalogLayout` 共用一个点击边界，包含列表、详情、待处理、目录版本、批量维护与导入审核；其他应用模块未启用。按钮、链接和具有 button 角色的操作控件触发，普通输入/空白区域不触发。

彩色线段使用 `--spark-color-1..4`，引用既有四个图表色：蓝、绿、金、紫。400ms ease-out、8条短线，装饰不表示成功；成功/失败仍来自实际请求和 StatusMessage。鼠标点击以指针为中心，键盘激活以控件为中心，不拦截默认事件、不增加提交。禁用、加载、`aria-disabled` 与 `data-click-spark="off"` 操作不绘制。系统减少动态效果或强制高对比时关闭；空闲时不保留 RAF 循环，卸载、滚动、缩放或偏好变更清理粒子。固定 Canvas Portal 不拦截指针，避免被工作区裁切，DPR 上限2。

此次检查的状态覆盖与组件接入：

| 层级 | 组件/页面 | Storybook 与覆盖 |
| --- | --- | --- |
| 点击反馈 | ClickSpark + 既有 Button | `Design System/Interaction Feedback/ClickSparkStates`；常规、键盘、禁用、加载、关闭火花、减少动态效果 |
| 选择/导航/切页 | GlideSelectField、RouteNavigation、PageTransition | 复用此前官方 React Bits 与 Motion 适配；商品列表/目录操作样板覆盖真实受控选择与路由 |
| 目录版本 | CatalogVersionsView | `Pages/Catalog Operations/Versions*`；已批准记录、空、加载、失败恢复 |
| 待处理 | CatalogUnmatchedView + CatalogPendingItems | `Unmatched* / NoPublicationEvidence / PendingFailure`；来源清单、分页、范围为空、发布依据缺失、候选读取失败 |
| 批量维护 | CatalogMaintenanceOverview | `Maintenance / Uninitialized`；生效目录与初始化前置、流程层级 |
| 审核批次 | CatalogImportHistoryView | 批量维护样板内直接使用实际展示组件；状态、修订、原批次链接、分页与刷新 |
| 候选生成/审核方式 | CatalogExportView | `Maintenance / Building / GenerationFailed / StaleCandidate / CapacityExceeded / Uninitialized`；准备不足、运行、恢复、过期与XLSX容量限制 |

以上展示组件直接由原页面容器消费。读取、来源身份、币种分组、稳定 style_id/import_id、URL 参数、return_to、版本前置、上传操作键、恢复权限与请求方法留在原容器中。共享展示通过 callbacks 连接原逻辑，不复制业务规则到另一套页面。目录版本保留接口原顺序，未知风险保留原字段；不臆测当前生效版本。

新增15个页面状态和1个 Design System 故事已纳入既有 manifest、三档 axe 与视觉比较。动画像素验证独立于减少动态效果的静态截图，不用静态基线宣称动画正确。样板全部虚构、无 API 请求；来源账号确认/快照组件仍在真实应用，样板仅显示其前置说明，尚未补完整交互故事。当前覆盖只限商品主档，本次没有声称全站组件已齐备。用户体验与正式发布分别确认。


### 加载交接与商品快速查看（2026-10-06）

公共 `ContentReveal` 复用已安装 Motion 的 opacity 入场与 `--motion-content-enter`，减少动态效果直接显示。首次 Skeleton → 内容轻淡入；刷新保持原组件挂载与 DOM，不以 request counter 作为 key。`CatalogHomePage` 单独管理 reading 状态；商品主档刷新保持筛选、分页、输入焦点与列表，只读旧结果在可重试失败时显示明确警告。403、初始化前置、404及其他不可重试读取失败清除原目录。窗口焦点/可见性刷新仍沿原请求入口；请求卸载隔离和原会话撤销边界保留。

公共 `Dialog` 新增 `presentation="drawer"`，采用既有 Radix Dialog / shadcn Sheet 侧滑模式，复用 Portal、焦点圈定、Escape、外部关闭与返回焦点；原居中变体不变。`CatalogProductDrawer` 接入 `/catalog` 商品卡与批量表格的“快速查看”，沿稳定 style_id 调用原 getCatalogStyle GET，只显示基础信息、来源汇总和实际变体，不调用销售别名 reveal、详细证据或写入接口。保留完整商品卡 href 与原返回上下文；关闭不改列表状态或滚动。每次打开重新读取，关闭/切换取消旧响应应用，加载、失败、重试和权限失效有明确状态。手机全屏，变体表格按抽屉可用宽度布局，长内容独立滚动。

新增 `QuickView / QuickViewLoading / QuickViewFailure / Refreshing / RefreshFailure` 五个商品列表故事，全部虚构数据，真实展示组件与 callbacks 共用；已纳入既有 manifest、axe、视觉基线。抽屉基线捕获实际 viewport，普通列表仍使用 fullPage，避免固定弹层在长页截图中的拼接失真。原基线、首次截图、失败日志与审批历史保留。未增加依赖；仅本地开发，用户确认与正式发布另记。

体验：`http://127.0.0.1:17641/?path=/story/pages-catalog-product-list--reference`，点击“快速查看”或刷新；失败恢复在对应故事体验。无需账号，样板不发 API 请求。实际路由需要原账号权限与 API，当前定向路由检查使用虚构拦截，不能代替真实数据或发布验收。


### 完整商品详情共享样板（2026-10-06）

实际 `/catalog/styles/:styleId` 与 `Pages/Catalog Style Detail`、列表样板完整详情均消费 `CatalogStyleView`。复用既有 shadcn 派生 Button/Input/Table/Pagination/StatusBadge、Motion ContentReveal 和全局 tokens，无新增依赖。展示稳定 STYLE/SKU 身份、来源汇总、真实存在的变体；搜索只过滤已有数组，不补颜色×尺码组合。Seller SKU 和来源各按用户展开/翻页读取，沿原 page_size=50；关闭保留缓存，目录发布修订变化重新读取。安全来源摘要、报告版本链接、文件行序号与系统记录编号的区别、退货原时间和时区说明保留；截断/危险内容不可复制。

原分类修改与草稿/预览/批准入口留在容器。刷新期间维护区域保持挂载并临时禁用；批准后的刷新失败继续拒绝 Promise 并显示恢复入口，不丢预览或重复批准。可重试读取失败保留旧只读详情，403/不可重试失败清空；style_id keyed 资源与请求序号隔离过期响应。样板 readers 全部虚构，无真实 API 或写操作；实际页面仍需原账号、批准目录及 API。

十种状态：Reference、Loading、Empty、ReadFailure、ReadOnly、AliasesLoading、AliasesFailure、Evidence、EvidenceFailure、PendingCandidates。新增30张开发基线经代理审阅，独立比较新增30＋原列表/快速查看6张共36通过；31项manifest/三档axe通过。功能覆盖列表→抽屉→详情→返回、搜索、分页、安全摘要与失败恢复，实际路由检查使用虚构 API。新基线不是人工验收。

体验：`http://127.0.0.1:17641/?path=/story/pages-catalog-style-detail--reference`，或列表打开完整详情。展开 Seller SKU、查看来源明细、搜索和返回列表；无需账号。本批 development_complete=true / ready_for_user_review=true / user_verified=false / accepted=false / UI_deployed=false。上一批加载交接/快速查看已由用户“体验通过继续下一步”确认；不扩展到本批或生产。Skill：frontend-design。


### 商品修改／批准与分类编辑（2026-10-06）

`CatalogChangeReview` 和 `CatalogCategoryEditor` 继续由原商品详情权限容器使用，统一到现有 shadcn 派生 FormField/Input/Select/Button/Table/StatusBadge/StatusMessage 及全局 tokens；不新增依赖或第二套视觉主题。修改区展示两步编辑／预览、稳定商品身份及目录修订；手机前后列自动换行同时可见，不要求横向滚动。分类管理采用既有侧栏／编辑区模式，中性表面、品牌蓝选中、相同控件和反馈；目录可键盘聚焦滚动，折叠和选择仍是独立按钮，不声明未实现的 ARIA tree 键盘协议。加载／提交禁用，未保存提示、取消恢复、失败保留字段及显式分类读取重试统一。

实际默认 services 指向原 API，草稿 revision／目录 revision、分类 category_id、CSRF、operation token、原批准后的 refresh Promise 和实际角色入口不改。可选 services 仅是 Storybook 虚构依赖注入，不模拟真实权限或授权真实写入。分类保存不会自动批准商品关联；批准后刷新失败仍显式显示，需在详情页刷新核对，不能把读取失败当成未提交。

`Pages/Catalog Editors` 含 Editing、Preview、Preparing、PrepareFailure、ApprovalFailure、RefreshFailure、Categories、Unsaved、Loading、ReadFailure、Empty、SaveFailure、Saved 共13状态，已接现有 manifest、三档 axe 和视觉回归。4项样板功能／3项实际路由虚构API、8项原组件、40项有效axe结果通过；39张开发基线经截图审阅，新增39+原详情Reference和GlobalDefaults六张独立比较45通过。原错误日志、首轮手机需横滚的预览截图和基线历史保留；新增基线是开发审阅，不是用户验收。TypeScript、目标ESLint、30模块Token零例外及 p0_catalog 构建通过；500KB chunk提示保留。

体验 `http://127.0.0.1:17641/?path=/story/pages-catalog-editors--editing` 与 `http://127.0.0.1:17641/?path=/story/pages-catalog-editors--categories`。样板全虚构、无需账号，不发实际 API；实际页面仍需原可维护账号和API。本批 development_complete=true / ready_for_user_review=true / user_verified=false / accepted=false / UI_deployed=false。用户明确详情尚未体验，原详情确认保持待办。本批 Skill：frontend-design，仅本地。


### 商品分析准备与首次快照（2026-10-06）

用户“全部体验通过下一步”已确认本地完整详情与修改／批准／分类管理；上述待体验记载保留历史。

分析准备/来源确认/首次快照共享展示已开发完成：实际CatalogSetup消费CatalogSetupView，原state/effects/权限generation、来源scope、CSRF、版本/摘要、StableOperationKeyStore、确认/初始化及轮询控制器保持。沿用shadcn派生共享组件与全局tokens，无新增依赖。12虚构故事覆盖来源待确认/提交/失败、已确认、预览/初始化/失败、缺报、已准备、只读、加载/读取失败；手机错误按钮纵向排布，链接颜色/焦点统一。有效4项Story功能、3项实际路由虚构API、3项原组件单测、37项manifest/三档axe通过；36张新开发基线经代理截图审阅，独立新36+原详情Reference/分类Categories六张共42比较通过。TypeScript/目标ESLint/31模块Token零例外及p0_catalog构建exit0；主包1000.64KB/gzip307.47KB，原500KB提示保留。首轮失败、截图与基线历史保留，临时Vite17341按PID/时间/命令核对停止，Storybook17641保留。development_complete=true/ready_for_user_review=true/user_verified=false/accepted=false/UI_deployed=false。体验http://127.0.0.1:17641/?path=/story/pages-catalog-setup--reference：来源填写→键盘勾选→确认→快照预览→建立→刷新，另可查看缺报/失败恢复；虚构数据无需账号，不请求真实API。实际页面仍需原授权账号/报表/API，未执行真实来源确认或快照。证据storybook-import-review-20261005-01/catalog-setup-20261006/result.json；Skill frontend-design。


### 发布数据总表（2026-10-07）

用户“体验通过，批准继续下一步”已确认上一批CatalogSetup本地样板；上述待体验说明保留历史。

2026-10-07发布数据总表UI批次已完成：PublishedDashboard每日分支消费PublishedDailyView，沿用现有shadcn派生PageHeader/FormField/Input/Select/Table/Button/StatusBadge/EmptyState/ErrorState/Skeleton及Radix Tabs，颜色/间距/焦点使用现有tokens；桌面完整表格、手机逐日两列卡片和显式日期入口。原月范围、URL筛选/刷新、角色日期路径、请求AbortController与旧产品分支控制器文本保持；状态筛选不改变本月总完整度，缺报显示—，真实零保留0，空月不再误称无需补齐。8虚构故事覆盖Reference/Manager/Filtered/FilterEmpty/NoRecords/Loading/ReadFailure/ZeroValues，不发实际API。3项Story功能、3项实际路由虚构API功能、8项原组件单测、25项有效manifest/三档axe通过；24张新开发基线经代理截图审阅，独立比较新增24+原CatalogSetupReference/GlobalDefaults六张共30通过。FilterEmpty改为原有效blocked选项、虚构记录无该状态；初版24图和基线历史保留，相关功能/axe三档/截图已复核。TypeScript/目标ESLint/32模块Token零例外/p0_catalog构建exit0；主包1003.49KB/gzip308.45KB，原500KB提示保留。临时Vite17341按PID/创建时间/命令核对停止，Storybook17641保留。development_complete=true/ready_for_user_review=true/user_verified=false/accepted=false/UI_deployed=false。体验http://127.0.0.1:17641/?path=/story/pages-published-daily-ledger--reference：切换状态→更换月份→键盘打开日期→返回，另看读取失败重试/空月/零值；样板虚构数据，无需账号。实际总表仍需原账号/API；本轮未操作生产或真实业务库，不commit/push/merge/deploy。证据storybook-import-review-20261005-01/published-dashboard-20261007/result.json；Skill frontend-design。


### 单日发布详情与月内趋势（2026-10-07）

用户“体验通过，下一步”已确认上一批本地发布总表；上述待体验状态保留历史。

单日发布详情与月内趋势共享展示已开发完成：实际PublishedDayPage和Pages/Published Day Detail共用PublishedDayView，沿用既有shadcn派生PageHeader/LinkButton/Button/StatusBadge/Skeleton/EmptyState/ErrorState及tokens，零新增依赖。原日期校验、return_to白名单、角色入口、只读请求/abort/重试控制器文本保持；独立详情读月初至当日，嵌入工作台仅读当天，月内趋势保持原lazy加载、图表/精确计算/缺口断线源码字节不变。8种虚构故事覆盖Reference/Partial/ZeroValues/Loading/ReadFailure/Empty/SingleDay/Embedded，无需账号，不请求实际API。3项Story功能、3项实际路由虚构API、7项原组件、25项manifest/三档axe通过；截图审阅发现手机金额尾数折行，销售额改跨两列，定向手机功能及8项axe复查通过，首24图与历史保留。24张新开发基线经截图审阅，独立比较新增24+原发布总表Reference/GlobalDefaults六张共30通过，未重跑全manifest。TypeScript/目标ESLint/33模块Token零例外/p0_catalog最终构建exit0；主包1004.96KB/gzip308.90KB，原500KB提示保留。任务Vite17341按PID/创建时间/命令核对停止，Storybook17641保留。development_complete=true/ready_for_user_review=true/user_verified=false/accepted=false/UI_deployed=false。体验http://127.0.0.1:17641/?path=/story/pages-published-day-detail--reference：切换趋势→展开逐日数据→查看日期与返回；另看缺报/零值/失败重试。实际页面仍需原账号/API，本轮仅使用虚构拦截验证路由，未读写真实业务库或操作生产/冻结来源/LAN/Alpha，无commit/push/merge/deploy。证据storybook-import-review-20261005-01/published-day-20261007/result.json；Skill frontend-design。


### 跨日期已发布明细（2026-10-07）

用户“体验通过，继续下一步”已确认上一批本地单日详情与月内趋势；此前待体验说明保留历史。

2026-10-07跨日期已发布明细UI开发完成：实际/ledger/published-details消费PublishedDetailLedgerView，沿用既有shadcn派生PageHeader/FormField/Input/Button/StatusBadge及Radix Tabs，日期摘要复用共享反馈/分页，窄屏和平板为卡片，原始数据表保留横向滚动、列宽/显示/排序和导出权限。Button类型改为React19原生button props以支持列设置焦点ref，渲染实现不变。原日期/搜索/URL、请求generation/abort、scope_token/最多一次自动冲突重读、全范围解析、展开/分页/排序控制器逐字相同；API/URL-state源码字节相同。保留report_date/version_id/row_ordinal、site和用户列布局隔离，不改变产品归属或写入范围。9种虚构故事覆盖Reference/AllRows/ReturnReport/Loading/ReadFailure/Empty/ExpansionFailure/ExpansionLoading/ScopeChanged；样板排序实际改变行序，零值与展开/摘要一致。4项Story功能（1280/768/390及状态）、3项实际路由虚构GET API（筛选展开、scope继承、列布局刷新、分页排序、下载、单日摘要返回、冲突停止、全范围失败/空恢复）、29项原组件通过。下载夹具先核对原download属性与href，再仅在测试DOM移除download属性由模拟Content-Disposition接管，以避免Chromium该属性绕过路由；不代表真实CSV服务验收。28项有效manifest/三档axe通过；平板截图隐藏右侧操作后改卡片并定向复查。27张开发基线经代理截图审阅，33项有效独立比较（首33中的24未受平板修改影响＋最终9平板）通过，不重跑全manifest。TypeScript/目标ESLint/35模块Token零例外/p0_catalog最终构建exit0，主包1003.99KB/gzip309.33KB，原500KB提示保留。首失败/截图库/审批历史保留；一次768px过滤过宽的检查在核对任务CLI身份后主动停止exit-1，不计PASS，最终10项定向复查exit0，无剩余子进程。任务Vite17341按PID/创建时间/命令核对停止，Storybook17641保留。development_complete=true/ready_for_user_review=true/user_verified=false/accepted=false/UI_deployed=false。体验http://127.0.0.1:17641/?path=/story/pages-published-detail-ledger--reference：日期/搜索→展开→全部明细/列设置→切换报表→单日摘要与返回；另看读取/展开失败恢复。样板虚构、无需账号、不请求实际API；实际页面仍需原账号和API。仅本地，无真实库/生产/冻结来源/LAN/Alpha/commit/push/merge/deploy。证据storybook-import-review-20261005-01/published-ledger-20261007/result.json；Skill frontend-design。


### 日期数据工作台（2026-10-07）

用户“体验通过，进行下一步”已确认上一批本地跨日期已发布明细；此前状态记载保留历史。

2026-10-07日期工作台本地UI已开发完成：实际/published/:reportDate与Pages/Date Workbench共用DateWorkbenchView，复用现有shadcn派生PageHeader/Button/FormField/StatusBadge/StatusMessage/EmptyState及tokens，无新增依赖。原请求/编辑generation/权限/版本/cell revision/StableOperationKeyStore/URL/导入确认/审核交接控制器经归一换行比较保持，EditableDataGrid及其CSS未改。只读/管理/草稿保存反馈/空日上传/归属确认/原文件冲突/读取与保存失败共10虚构故事；只读说明按实际状态显示，手机操作栏随文档排列避免覆盖数据行，表格可键盘聚焦横向滚动。有效4项Story功能（含最终手机复查）、3项实际App路由虚构API功能、原30项组件测试、31项有效manifest/三档axe（原24未受影响+最终7复查）、30项独立视觉比较通过；30张新开发基线经截图审阅并纳入现有manifest。TypeScript/目标ESLint/36模块Token零例外及p0_catalog构建exit0，主包1008.22KB/gzip310.52KB，原500KB提示保留。首轮测试选择器、异步checkbox断言、虚构PATCH路径索引及ESLint回调问题已修正，失败日志/截图保留。任务Vite17341已核对PID/创建时间/命令停止，Storybook17641保留。development_complete=true/ready_for_user_review=true/user_verified=false/accepted=false/UI_deployed=false。体验http://127.0.0.1:17641/?path=/story/pages-date-workbench--manager：开始修改→Enter保存/Escape放弃→筛选/列设置→撤销→审核交接；另看导入确认/失败恢复。虚构数据，无需账号，样板不请求真实API；实际页面仍需原账号及API，未执行真实业务写入或生产/发布。证据storybook-import-review-20261005-01/date-workbench-20261007/result.json；Skill frontend-design。下一动作：体验日期工作台管理与状态样板，待对应版本用户确认。


### 日期版本记录（2026-10-07）

用户“体验通过，继续下一步”已确认上一批本地日期工作台；此前待体验状态保留历史。

2026-10-07版本记录本地UI已开发完成：实际/versions与Pages/Version History共享VersionHistoryView、VersionRowsView及BatchReviewHistoryView，复用现有shadcn派生PageHeader/FormField/Input/Select/Button/Table/反馈/分页与tokens，零新增依赖。统一日期筛选、当前发布与活动草稿摘要、版本列表、只读原始行、谱系/备注和批量任务显示，桌面双栏、平板/手机分栏排列，表格可聚焦横向滚动。原角色/请求generation/固定version_id/CSRF/operation key/发布预期/修订/回滚/移动/撤销与dedup控制器经LF归一比较保持；BatchHistory只作类型改名，原命令弹窗及VersionHistory.css未重设计。实际功能验证发现原筛选输入未写回URL，已仅在用户输入时同步report_date/report_type，保留其他参数与浏览器前后记录；刷新和后退/前进已核对。13个虚构故事含查看/管理/活动草稿/批量草稿/空/加载/列表与详情失败/原始行加载失败空，样板命令仅展示反馈，不模拟真实写成功。有效4项Story功能、3项实际路由虚构GET API功能、20项原组件、40项manifest/三档axe、39项独立视觉比较通过；39张新开发基线纳入现有manifest，代表性桌面/平板/手机及失败/草稿图经代理审阅，未全仓回归。TypeScript/目标ESLint/39模块Token零例外/p0_catalog构建exit0，8569模块，主包1010.85KB/gzip311.53KB，原500KB提示保留。首轮历史标签选择器错误/URL未同步失败证据保留，已定向修复复查。任务Vite17341按PID/创建时间/命令核对停止，Storybook17641保留。development_complete=true/ready_for_user_review=true/user_verified=false/accepted=false/UI_deployed=false。体验http://127.0.0.1:17641/?path=/story/pages-version-history--reference：切换版本→查看此版本数据→分页；再看Manager/ActiveDraft/读取失败重试。虚构数据，无需账号；实际/versions仍需原账号/API。本轮未读写真实库/生产/冻结来源/LAN/Alpha，无commit/push/merge/deploy。证据storybook-import-review-20261005-01/version-history-20261007/result.json；Skill frontend-design。


### 批量审核任务（2026-10-07）

用户“体验通过下一步”已确认上一批本地版本记录及状态样板；此前待体验记载保留历史。

2026-10-07批量审核本地UI已开发完成：实际/review/batch/:runId与Pages/Batch Review共用BatchReviewView，复用现有shadcn派生PageHeader/Button/Checkbox/Table/StatusBadge/反馈及tokens，零新增依赖。预检清单、确认栏、任务计数、处理进度、暂停/恢复、失败重试及版本记录交接统一，桌面表格、平板/手机带标签卡片；选择辅助名称仅供读屏，文件名优先，表头不折行。原pageError/路由身份/state/请求/executor/轮询/写命令经LF归一比较保持；API/executor/types源码字节相同，预检分类与人工审核URL规则保持。12种虚构故事覆盖Reference/Running/Paused/Completed/Exceptions/OutcomeUnknown/Confirming/Retrying/Empty/Loading/ReadFailure/ActionFailure，样板只模拟预检、排队、暂停/恢复，不伪造校验完成或发布。有效4项Story功能（原状态恢复1+最终三档3）、3项实际App路由虚构API功能（选择确认/CSRF/幂等/修订/执行器/刷新/版本交接/暂停恢复/重试/权限及结果待确认）、14项原组件、37项有效manifest/三档axe（原28+最终9）、36项独立视觉比较通过；36张新开发基线经桌面/平板/手机代表截图审阅并纳入现有manifest。TypeScript/目标ESLint/40模块Token零例外/p0_catalog最终构建exit0，8570模块，主包1011.34KB/gzip311.96KB，原500KB提示保留。首轮布局截图与基线更新历史保留，未全仓或全manifest重跑。任务Vite17341按PID/创建时间/命令核对停止，所属两个子进程已自然退出，Storybook17641保留。development_complete=true/ready_for_user_review=true/user_verified=false/accepted=false/UI_deployed=false。体验http://127.0.0.1:17641/?path=/story/pages-batch-review--reference：选择文件→勾选日期/类型确认→开始→暂停/恢复；另看Exceptions重试、OutcomeUnknown和读取失败恢复。虚构数据，无需账号，不请求真实API；实际页面仍需原可管理账号和API。未读写真实业务库/生产/冻结来源/LAN/Alpha，无commit/push/merge/deploy。证据storybook-import-review-20261005-01/batch-review-20261007/result.json；Skill frontend-design。


### 数据导入入口（2026-10-07）

用户“体验通过，继续下一步”已确认上一批本地批量审核及状态样板；此前待体验说明保留历史。

2026-10-07数据导入入口本地UI已开发完成：ImportReviewFlow与Pages/Import Intake共享ImportIntakeView，沿用现有shadcn派生Button/Input/Select/Radio/Checkbox/StatusMessage/Skeleton及tokens，零新增依赖。统一五步证据链、CSV选择/多文件队列、日期差异、识别参数、不可变解析基线和合并/替换/管理员重建/取消选项；三档响应式、加载/错误恢复/禁用和焦点一致。原controller私有类型/state/reducer/recovery/effects与所有命令经LF归一比较保持；原SourceFilePreview/MergeDecisionMatrix/DraftReviewGate/备注仍以原callbacks和数据作为容器所属插槽，不重设计下游草稿/重复行审核及发布。本轮保留site/user恢复身份、batch_id/report_date/report_type/parse_baseline_id/版本修订/CSRF/稳定operation key，唯一业务写入仍为原API，不改变SKU归属或原文件。11种虚构故事覆盖Reference/Recognition/DateMismatch/Baseline/TargetConflict/ActiveDraftConflict/Uploading/Parsing/Restoring/ReadFailure/ParseFailure；虚构状态不调用API，不模拟真实草稿或发布成功。有效4项Story功能（原三档3+修复后状态1）、2项实际App路由虚构API（上传一次/识别与源表失败重试/解析失败重试/原确认body/取消零写入/刷新恢复基线/一次草稿生成及刷新恢复）、27项原组件通过。34项有效manifest/三档axe（原31+最终恢复3）及33项有效独立视觉比较（最终比较30未受恢复提示影响+最终恢复3）通过，33张新增开发基线和原审批历史保留。三档与冲突代表截图经代理审阅；自审收窄CSS到入口区域，保留原草稿区样式，恢复提示专用行高修复手机差异；首轮确认checkbox名称与视觉差异日志/trace保留，未全仓或全manifest重跑。TypeScript/目标ESLint/41模块Token零例外/p0_catalog最终构建exit0，8571模块，主包1014.08KB/gzip313.00KB，原500KB提示保留。任务Vite17341按PID/创建时间/命令核对停止，所属两个子进程自然退出，Storybook17641保留。development_complete=true/ready_for_user_review=true/user_verified=true/accepted=false/UI_deployed=false。体验http://127.0.0.1:17641/?path=/story/pages-import-intake--reference：选择虚构CSV→核对日期/类型/编码→确认解析→查看目标冲突→取消；另看DateMismatch/ActiveDraftConflict/ParseFailure/Restoring。虚构数据无需账号；实际/review-advanced/:reportDate及原日期审核入口仍需原可管理账号/API。未读写真实业务库/生产/冻结来源/LAN/Alpha，无commit/push/merge/deploy。证据storybook-import-review-20261005-01/import-intake-20261007/result.json；Skill frontend-design。


### 草稿审核与发布（2026-10-07）

用户“体验通过，继续下一步”已确认前一批数据导入入口及状态样板。

2026-10-07草稿审核/校验/人工确认/发布本地UI已开发完成：实际DraftReviewGate与13种虚构Pages/Draft Review状态共享DraftReviewView和PublicationDialog，复用现有shadcn派生控件与tokens，零新增依赖。统一备注/校验/人工确认卡片、日期冲突Radio、处置Checkbox、发布闸门及确认弹窗；补首次草稿读取失败的重读入口，发布失败保留说明。原controller的state/effects/所有命令与三个搬移helper按本轮前快照LF归一比较一致；ReviewDataTable/MergeDecisionMatrix源码字节相同，旧表格CSS仅两处辅助文字改用token字号/颜色以修复实际对比度失败。版本、修订、校验摘要、发布指针、CSRF、幂等键、跨日期管理员和退货去重准备合同保持。有效5项Story功能（状态门禁1+修正定位后三档/弹窗4）、3项实际App路由虚构API（读取失败重读/校验/确认/刷新待发布/取消零发布/失败同UUID重试/发布回执/查看人员重定向）、36项原组件、40项有效manifest/三档axe（原10+两次修复后18+12）、39项独立视觉比较通过。39张新开发基线经三档/弹窗/错误代表截图审阅纳入现有manifest，原失败日志/trace与基线审批历史保留。TypeScript/目标ESLint/42模块Token零例外/p0_catalog构建exit0，8575模块，主包1017.13KB/gzip313.29KB，原500KB提示保留。任务Vite17341与所属子进程已清理，Storybook17641保留。development_complete=true/ready_for_user_review=true/user_verified=true/accepted=false/UI_deployed=false。体验http://127.0.0.1:17641/?path=/story/pages-draft-review--reference：运行校验→确认结果→打开发布确认→返回审核；另看Warning/Blocking/ReadFailure/PublicationFailure/AdminRequired。虚构数据无需账号，不调用真实API；实际页面仍需原可管理账号/API。本轮未读写真实业务库/生产/冻结来源/LAN/Alpha，无commit/push/merge/deploy或新Collect。证据storybook-import-review-20261005-01/draft-review-20261007/result.json；Skill frontend-design。用户2026-10-07原话“体验通过，继续下一步”，确认本批user_verified=true。下一动作：源表预览/批次备注/备注修订样板优化进行中。


## 源表与批次备注（2026-10-07）

2026-10-07源表预览/批次备注/备注修订本地UI已开发完成：实际SourceFilePreview和BatchNotePanel与Pages/Import Evidence共享SourcePreviewView/BatchNotesView，NoteRevisionEditor沿用原修订逻辑；复用现有shadcn派生Button/Input/Table/Pagination/StatusMessage/Skeleton和tokens，零新增依赖。统一只读文件身份、搜索原行号/分页、空表/读取失败重试、备注账目与追加/修订/保存反馈，手机搜索独占一行。原batch_id/encoding、200行读取上限/50行分页、note_key/expected_note_id/expected_revision_number、internal范围、CSRF及稳定重试键保持；controller state/effects/commands与本轮前快照LF归一比较一致，原件和历史不变。13种虚构故事接现有manifest，39张三档开发基线经代表图及三档总览审阅，39项独立比较通过；有效4项Story功能、2项实际App路由虚构API完整路径（读取/追加/修订失败恢复、同UUID重试、刷新后结果、草稿侧栏）、21项原组件、40项manifest/三档axe通过。手机toolbar调整后仅复查受影响1项Story/1项App/10项axe；首轮测试夹具遗漏HEAD与草稿日历身份、测试类型错误及原日志保留。TypeScript/目标ESLint/43模块Token零例外/p0_catalog构建exit0，8578模块，主包1018.74KB/gzip314.20KB，原500KB提示保留。任务Vite17341及所属子进程已清理，Storybook17641保留。development_complete=true/ready_for_user_review=true/user_verified=true/accepted=false/UI_deployed=false。体验http://127.0.0.1:17641/?path=/story/pages-import-evidence--reference：搜索→翻页→追加虚构备注→修订/取消；另看SourceReadFailure/NotesReadFailure/RevisionFailure/RevisionSaving。虚构样板无需账号，不请求API；实际页面仍需原可管理账号/API，本轮只用拦截虚构数据，不读写真实业务库/生产/冻结来源/LAN/Alpha，无commit/push/merge/deploy或新Collect。证据storybook-import-review-20261005-01/import-evidence-20261007/result.json；Skill frontend-design。 用户2026-10-07原话“体验通过，继续下一步”，确认本批user_verified=true；下一动作：备份与后台任务已开发完成，待本地体验确认（user_verified=false）；内部审计已体验确认，accepted/UI_deployed仍false。


## 管理员账号与角色（2026-10-07）

2026-10-07管理员账号与角色本地UI已开发完成：实际AdminConsole与14种虚构Pages/Admin Accounts状态共享AdminAccountsView及控制台导航，沿用现有shadcn派生控件、Radix Dialog和tokens，零新增依赖。统一账号台账/新建表单/编辑弹窗/角色说明/状态及手机布局，同一份DOM响应式排版；弹窗内保留失败反馈和编辑内容，补首次管理资料读取失败的显式重试，成功读取前禁用账号创建。原账号写入handler、UUID/CSRF helper及其他四区handler/内容与本轮前快照字节一致，保持expected_updated_at/密码留空/稳定重试键和版本冲突重读；最后管理员保护仅展示虚构提示样板，不把mock声明为后端保护验证。有效4项Story功能、3项实际App路由虚构API完整路径（创建/角色修改失败同UUID重试、刷新保留、冲突重读、权限边界、焦点返回/键盘圈定/手机无溢出）、12项原组件、43项manifest/三档axe及42项独立视觉比较通过。42张新开发基线经三档/弹窗/错误代表截图审阅，原审批历史/失败日志保留；首轮密码必填标识定位及测试类型问题已定向修正。TypeScript/目标ESLint/44模块Token零例外/p0_catalog构建exit0，8580模块，主包1020.99KB/gzip315.27KB，原500KB提示保留。任务Vite17341按PID/父PID/创建时间/命令核对停止，所属子进程自然退出，Storybook17641保留。development_complete=true/ready_for_user_review=true/user_verified=true/accepted=false/UI_deployed=false。体验http://127.0.0.1:17641/?path=/story/pages-admin-accounts--reference：新建虚构账号→分配查看人员/停用→编辑数据管理员→保存后重开；另看ReadFailure/CreateFailure/EditFailure/Conflict/LastAdminProtected。虚构数据无需账号，不请求API；实际/admin仍需原管理员账号/API。本轮未读写真实业务库/生产/冻结来源/LAN/Alpha，无commit/push/merge/deploy或新Collect。证据storybook-import-review-20261005-01/admin-accounts-20261007/result.json；Skill frontend-design。 用户2026-10-07原话“体验通过，继续下一步”，确认本批user_verified=true。

## 站点配置与版本历史（2026-10-07）

2026-10-07站点配置与版本历史本地UI已开发完成：实际AdminConsole与Pages/Admin Site Configuration共享SiteConfigurationView，复用既有shadcn派生控件与全局tokens，零新增依赖。统一当前站点/时区/币种/生效时间、新建版本和历史记录，三档响应式；9种虚构样板覆盖新建/提交中/提交失败/加载/读取失败/空/权限不足/多站点。原站点及账号写入handler、初始读取/当前选择、其他区内容和API helper与本轮前快照字节一致，保留site_id/版本归属、UTC转换、CSRF与稳定重试键。有效4项Story功能、2项实际App路由虚构API完整路径、10项原组件、28项有效manifest/三档axe、27项独立视觉比较通过；27张开发基线已接现有视觉回归并保留原审批历史。TypeScript/目标ESLint/45模块Token零例外/p0_catalog构建exit0，主包1024.77KB/gzip316.38KB，原500KB提示保留。定义列表结构与测试可访问cell定位问题已修正，首失败日志/截图保留；有效结果复用，未全仓回归。任务Vite17341与所属子进程已清理，Storybook17641保留。development_complete=true/ready_for_user_review=true/user_verified=true/accepted=false/UI_deployed=false。体验http://127.0.0.1:17641/?path=/story/pages-admin-site-configuration--reference：新建版本→修改统计时区/原因→保存→核对当前版本与新旧历史；另看CreateFailure/ReadFailure/MultiSite。虚构数据无需账号，不请求实际API；实际/admin仍需原管理员账号/API，本轮不证明生产站点配置写入或其受限数据库权限。仅本地，无真实库/生产/冻结来源/LAN/Alpha、commit/push/merge/deploy或新Collect。证据storybook-import-review-20261005-01/admin-site-config-20261007/result.json；Skill frontend-design。

用户2026-10-07原话“体验通过，继续下一步”，确认本地站点配置与版本历史user_verified=true；授权继续内部审计UI，正式accepted/UI_deployed仍false。

## 内部审计（2026-10-07）

2026-10-07内部审计本地UI已开发完成：实际AdminConsole与Pages/Admin Audit共享AdminAuditView，复用现有shadcn派生控件和tokens，零新增依赖。统一事件筛选、操作人/对象/站点/请求信息、键盘可展开脱敏详情和分页，9种虚构样板覆盖筛选/详情/加载/首次失败/筛选失败/空/读取中/权限不足。原state/effects/读取/写入/筛选handler与本轮前快照LF归一比较一致，递归脱敏函数原样搬移；保留20条分页及服务端next_offset，不扩大读取范围。首次失败补显式管理资料重读，筛选或分页失败明确保留旧记录；刷新沿用原筛选重置。有效4项Story功能、3项实际App路由虚构API完整路径、10项原组件、28项manifest/三档axe、27项独立视觉比较通过，27张开发基线经三档/脱敏详情/错误代表截图审阅纳入原视觉回归。TypeScript/目标ESLint/46模块Token零例外/p0_catalog最终构建exit0，8584模块，主包1026.65KB/gzip316.95KB，原500KB提示保留。首轮测试误把查看人员路由重定向当组件权限页、Story同步click误await已修正，仅定向复查；原失败日志/截图和基线审批历史保留。最终既有primary按钮/焦点token/反馈文字调整经截图和视觉核对，未改变功能；不重跑全仓。任务Vite17341与所属子进程已核对清理，Storybook17641保留。development_complete=true/ready_for_user_review=true/user_verified=true/accepted=false/UI_deployed=false。体验http://127.0.0.1:17641/?path=/story/pages-admin-audit--reference：展开脱敏详情→下一页→输入admin.user_updated并应用筛选→清空恢复；另看ReadFailure/FilterFailure/Empty。虚构样板无需账号，不请求真实API；实际/admin仍需原管理员/API，本轮只用虚构拦截验证。未读写真实业务库/生产/冻结来源/LAN/Alpha，无commit/push/merge/deploy或新Collect。证据storybook-import-review-20261005-01/admin-audit-20261007/result.json；Skill frontend-design。

## 备份与后台任务（2026-10-07）

用户2026-10-07原话“体验通过，继续下一步”，确认内部审计本地UI user_verified=true。2026-10-07备份与后台任务UI已开发完成：实际AdminConsole与12种虚构Pages/Admin Maintenance状态共享AdminMaintenanceView，复用原WorkerObservabilityPanel/shadcn派生控件和全局tokens，零新增依赖。统一Worker概览/实例/四队列诊断及写屏障/备份/恢复记录，补首次维护读取失败显式重试，刷新失败保留数据与已展开诊断；在线、消费者失败、查询未知、不适用及备份成功/恢复验证继续独立展示。原全部controller与账号/站点/审计/恢复展示按本轮前快照LF归一比较一致，Worker源码和旧CSS字节一致；维护GET、15秒活动页轮询和in-flight控制不变，无备份/恢复执行入口，不展示DB凭据或密钥。有效4项Story功能、2项实际App路由虚构API完整路径、4项原定向组件（其余8账号测试未执行）、37项有效manifest/三档axe、36项独立视觉比较通过；36张开发基线经三档/异常/诊断/备份失败代表图审阅纳入原视觉回归，旧审批历史保留。首次三档诊断标签对比度4.36/字号9.92px失败已改全局tokens，受影响3项axe及手机功能复查通过，首失败日志/图/trace保留。TypeScript/目标ESLint/47模块Token零例外/p0_catalog构建exit0，8586模块，主包1027.78KB/gzip317.31KB，原500KB提示保留。任务Vite17341与所属子进程已按身份核对清理，Storybook17641保留。development_complete=true/ready_for_user_review=true/user_verified=false/accepted=false/UI_deployed=false。体验http://127.0.0.1:17641/?path=/story/pages-admin-maintenance--reference：展开心跳阈值→查看实例/队列诊断→刷新→查看备份与恢复记录；另看ReadFailure/RefreshFailure/ConsumerFailure/QueryUnknown/BackupFailure。样板虚构无需账号，不请求真实API；实际/admin仍需原管理员/API，本轮不执行真实备份、恢复或运维任务。未读写真实库/生产/冻结来源/LAN/Alpha，无commit/push/merge/deploy或新Collect。证据storybook-import-review-20261005-01/admin-maintenance-20261007/result.json；Skill frontend-design。

用户2026-10-07原话“体验通过，继续下一步”，上述备份与后台任务本地user_verified=true；先前false为开发交付历史，accepted/UI_deployed仍false。

## 草稿恢复（2026-10-07）

2026-10-07用户原话“体验通过，继续下一步”，确认备份与后台任务本地user_verified=true。草稿恢复本地UI已开发完成：AdminConsole与10种虚构Pages/Admin Recovery状态共享AdminRecoveryView，复用既有shadcn派生Button/Checkbox/FormField/StatusMessage/Skeleton和全局tokens，零新增依赖。统一无上下文的三步操作说明、只读来源标识、原因/确认及提交/失败/成功状态；明确活动草稿ID不是版本号，未发布指针显示“尚未发布”。实际/admin未传入重建上下文，因此仅展示导入冲突入口说明；真实重建仍由现有ImportReviewFlow使用服务器预览上下文，源码和业务路径不变，未新增自由ID或路由交接。原AdminConsole全部controller经本轮前快照LF归一比较一致，精确payload、CSRF、失败保留内容/操作键、修改原因后新键、成功回调保持；提交期间锁定原因和确认。有效4项Story功能、2项实际App无上下文路由虚构API、3项定向组件（成功载荷/失败重试键/查看人员边界）、31项manifest/三档axe、30张独立视觉比较通过。首轮故事重试错误切换到上下文及旧单测必填标识标签选择失败，均定向修正；首失败日志/trace保留。30张开发基线经桌面/手机参考与失败图审阅加入既有manifest和视觉回归，审批历史保留，未跑全套回归。TypeScript/目标ESLint/48模块Token零例外/p0_catalog构建exit0；8588模块，主包1030.93KB/gzip318.12KB，原500KB提示保留。任务Vite17341及所属子进程按PID/创建时间/命令核对停止，Storybook17641保留。development_complete=true/ready_for_user_review=true/user_verified=false/accepted=false/UI_deployed=false。体验http://127.0.0.1:17641/?path=/story/pages-admin-recovery--reference：查看三步说明，切换Context填写原因→键盘勾选→提交→查看新草稿提示；另看Failure/Submitting/ReadFailure。样板虚构无需账号、不请求真实API；实际/admin仍需管理员/API，真实导入重建写入本轮未执行。未读写真实库/生产/冻结来源/LAN/Alpha，无commit/push/merge/deploy或新Collect。证据storybook-import-review-20261005-01/admin-recovery-20261007/result.json；Skill frontend-design。

用户2026-10-07原话“体验通过，继续下一步”，上述草稿恢复本地user_verified=true；先前false为开发交付历史，accepted/UI_deployed仍false。

## 登录与会话入口（2026-10-07）

2026-10-07用户原话“体验通过，继续下一步”，确认草稿恢复本地user_verified=true。登录与会话入口本地UI已开发完成：实际App与7种虚构Pages/Session Entry状态共享LoginView/SessionStateView，沿用现有shadcn派生FormField/Input/Button/StatusMessage/ErrorState/Skeleton及全局tokens，零新增依赖。桌面流程说明与登录表单双栏、手机聚焦表单，统一连接中/站点读取/失败重试；新增键盘可操作的密码显示切换，默认隐藏且保留autocomplete，提交期间锁定输入与显示按钮。原LoginPage凭据/CSRF/回调handler、App会话/站点controller、AppShell导航及审核路由按本轮前快照LF归一比較一致；只删除旧登录选择器，侧栏折叠CSS完整保留，实际地址/权限/站点重试及退出逻辑保持。4项Story功能、2项有效实际App虚构API完整路径（登录失败保留输入→重试待处理→站点读取失败→重试加载→进入原/admin→硬刷新→退出失败保留会话→退出成功清空表单；桌面含折叠/展开核对）、4项定向既有App单测（其余37跳过）、22项manifest/三档axe通过。21张新开发基线经桌面/手机参考/登录失败及站点失败截图审阅，独立21项比较通过并接既有manifest，未重跑全套。初轮虚构登录响应缺少CSRF Cookie导致硬刷新后退出测试失败，补齐模拟Cookie及精确服务端失败断言后复查通过，首日志/图/trace保留；CSS清理中误删侧栏折叠规则已按前快照恢复，最终精确差异只含旧登录样式，最终桌面路径和构建复查通过。TypeScript/目标ESLint/49模块Token零例外/p0_catalog最终构建exit0；8590模块，主包1035.52KB/gzip319.34KB，原500KB提示保留。任务Vite17341与所属子进程按PID/父PID/创建时间/命令核对清理，Storybook17641保留。development_complete=true/ready_for_user_review=true/user_verified=false/accepted=false/UI_deployed=false。体验http://127.0.0.1:17641/?path=/story/pages-session-entry--reference：填写虚构账号/密码→显示/隐藏→Enter提交进入站点读取样板；另看LoginFailure/Submitting/Checking/SiteFailure。样板无需真实账号，不发送API；填写内容仅在样板内，不输入真实密码。实际入口仍需原账号和API，本轮完整路径只用虚构拦截，无真实登录、站点修改、退出或业务写入。未操作生产/冻结来源/LAN/Alpha，未读写data/，无commit/push/merge/deploy或新Collect。证据storybook-import-review-20261005-01/session-entry-20261007/result.json；Skill frontend-design。

用户2026-10-07原话“体验通过，继续下一步”，上述登录与会话入口本地user_verified=true；先前false为开发交付历史，accepted/UI_deployed仍false。

## 产品分析总表（2026-10-07）

2026-10-07用户原话“体验通过，继续下一步”，确认登录与会话入口本地user_verified=true。产品分析总表本地UI已开发完成：实际/products与10种虚构Pages/Product Ledger状态共享ProductLedgerView，沿用既有shadcn派生FormField/Input/Select/Checkbox/Button/Table/Pagination及全局tokens，零新增依赖。统一筛选/事实来源/返回排序/款式台账/覆盖六桶对账，窄屏表格内部滚动；款号与指标说明入口改用现有Button，抽屉和说明弹层保留原焦点/关闭/链接逻辑。原请求、权限generation、abort/sequence、canonical URL/分页/失败清除/焦点恢复controller经本轮前快照归一核对一致，API/state/六桶源码/原图表CSS字节一致；stable style_id/detail href和返回上下文、报表缺失与零值/分母为零及部分数据语义保持。有效4项Story功能、2项实际路由虚构API完整路径、9项原组件、31项有效manifest/三档axe通过（最后按钮修正后复查12受影响项，19未受影响结果复用）；10故事30张开发基线经代表截图审阅，独立30项视觉比较通过并纳入既有回归。原虚构金额格式不符合canonical decimal及一次错误端口导致零执行启动失败已修正，首次日志/图/trace保留，不算通过。TypeScript/目标ESLint/50模块Token零例外/p0_catalog构建exit0；8592模块，主包1036.19KB/gzip320.13KB，原500KB提示保留。任务Vite17341及所属子进程按身份核对停止，Storybook17641保留。development_complete=true/ready_for_user_review=true/user_verified=false/accepted=false/UI_deployed=false。体验http://127.0.0.1:17641/?path=/story/pages-product-ledger--reference：主/细分类→显示名称→点击款号→Escape焦点返回→指标说明→销售贡献/退货关注；另看Partial/NoReports/ZeroValues/Refreshing/ReadFailure/AccessDenied/SetupRequired。样板虚构无需账号，不请求实际API；实际/products仍需原账号/后端/已发布报表，仅以虚构API验证，未重验真实详情路由。未读写data/、真实库或生产，不改冻结来源/LAN/Alpha，无commit/push/merge/deploy/migration或新Collect。证据storybook-import-review-20261005-01/product-ledger-20261007/result.json；Skill frontend-design。

用户2026-10-07原话“体验通过继续”，上述产品分析总表本地user_verified=true；先前false为开发交付历史，accepted/UI_deployed仍false。

## 产品经营详情页（2026-10-07）

2026-10-07用户原话“体验通过继续”，确认产品分析总表本地user_verified=true。产品经营详情页本地UI已开发完成：实际/products/:style_id与10种虚构Pages/Product Detail状态共享ProductDetailAnalysisView，沿用既有shadcn派生Button/LinkButton/StatusBadge/tokens，完整复用review-23 ProductTrendChart/SeriesSelector/TrendPointMatrix/VariantReviewTable，零新增依赖。统一身份及事实来源、五项指标层级、指标/维度/退货口径/同色尺码选择与守恒状态，矩阵和实际变体在自身区域横向滚动。原请求controller在return前逐字归一一致，保留generation/abort/sequence、响应与displayedView整体更新、失效颜色/系列一次修正、版本绑定颜色读取/显式重试和返回总表上下文；API/state/原图表CSS及四业务组件字节一致，稳定style_id/sku_id、实际变体组合、来源安全展示及款内占比分母不变。有效4项Story功能、2项实际路由虚构API完整路径、5项原定向单测、31项manifest/三档axe通过；最终虚构数量与nullable元数据及数字层级调整后功能复查，30张新开发基线经代表截图审阅，独立30项视觉比较通过并纳入既有回归。首次badge tone类型和Playwright check对异步路由状态的即时断言失败已定向修正，首日志/图/trace保留；夹具汇总/趋势/变体及无报表可计算状态已核对，不冒充真实数据验收。TypeScript/目标ESLint/51模块Token零例外/p0_catalog最终构建exit0；8594模块，主包1037.65KB/gzip320.50KB，原500KB提示保留。任务Vite17341及所属esbuild按PID/父PID/创建时间/命令核对停止，Storybook17641保留。development_complete=true/ready_for_user_review=true/user_verified=false/accepted=false/UI_deployed=false。体验http://127.0.0.1:17641/?path=/story/pages-product-detail--reference：切销售额→尺码→限定蓝色→日期方向键读数→变体颜色/尺码筛选→清除→来源别名；另看Partial/NoReports/EmptyVariants/Refreshing/ReadFailure/ColorFailure/ReadOnly/AccessDenied。样板虚构无需账号、不请求实际API；实际经营详情仍需原账号/API/商品和报表初始化，本轮仅虚构API完整路径，不读真实报表。未读写data/、真实库或生产，不改冻结来源/LAN/Alpha，无commit/push/merge/deploy/migration或新Collect。证据storybook-import-review-20261005-01/product-detail-20261007/result.json；Skill frontend-design。


## 应用外壳与主导航（2026-10-07）

产品经营详情页已由用户“体验通过，继续”确认。本批实际 App 和 Pages/Workspace Shell 同用 WorkspaceShell；导航基于现有 shadcn 派生控件、Lucide 和 Radix Sheet 抽屉交互，遵循项目 tokens。9种状态与三档27张开发基线已接现有 manifest；27项独立比较及28项 manifest/axe通过，用户体验尚待确认，未部署。

桌面核对折叠/展开及导航；窄屏核对键盘焦点、Escape、外部关闭与退出失败重试。样板仅用虚构数据，无需账号，不发送 API。实际登录/会话/站点/业务路由保持原 controller 与权限。


## 高级日期审核工作区（2026-10-07）

应用外壳与主导航已由用户“体验通过，继续下一步”确认。本批实际 ReviewPage 和 Pages/Advanced Review Workspace 同用 AdvancedReviewWorkspaceView；复用现有 shadcn 派生组件、Lucide 和项目 tokens，无新增依赖。桌面每日状态轨、手机日期列表与报告日/草稿版本摘要统一；读取未知时显示待确认，失败只显式重试原月读取。指定来源重新审核复用 SourceBatchReviewView 页头，内部 ImportReviewFlow 和业务命令保持。

8种虚构状态、三档24张开发基线已接现有 manifest，独立24项比较通过；日期/草稿切换、键盘操作、实际路由读取失败恢复及刷新后URL版本保持均通过。有效25项manifest/axe通过，黄色选中日对比度及手机重试排布已修正。仅本地开发完成、待用户体验，未部署。

体验 http://127.0.0.1:17641/?path=/story/pages-advanced-review-workspace--reference：切换日期和草稿版本，另看读取失败重试、加载、只读及指定来源页头。Storybook 使用虚构数据，无需账号，不发实际API；实际页面保留原账号/后端和报表前置。本轮不是完整来源审核流程的新验收。


## 版本操作确认（2026-10-07）

高级日期审核工作区已由用户“体验通过，继续下一步”确认。本批四个实际版本命令弹窗共享 VersionCommandViews，沿用现有 Radix/shadcn 派生 Dialog、Button、Input、Radio、Checkbox、StatusMessage、Control CSS 和项目 tokens，不增加依赖或业务写入口。Dialog 的可选 accessibleLabel 保留原命令可访问名称，dismissDisabled 保留提交期间禁止关闭约束；默认调用行为不变。

修订、跨日期移动、撤销移动与回滚显示各自真实生效范围；目标活动草稿仍要求明确选择及强制确认，原合并决策矩阵和所有命令 controller 保持。回滚错误展示在弹窗内部，输入保留。桌面/平板支持焦点圈定、Escape、外部关闭及焦点返回，手机复用全屏和内部滚动。

13种虚构状态、39张开发基线接入现有 manifest。4项有效Story功能、2项实际路由虚构API路径、18项原组件、40项manifest/axe及45项独立视觉比较通过。开发完成待本地体验，未正式验收或部署。

体验 http://127.0.0.1:17641/?path=/story/pages-version-commands--revision，再看 Move、MoveDraft、Undo 与 RollbackFailure。样板无真实API或账号前置；合并故事不请求行数据，不开放合并提交。实际 /versions 保留原账号/权限/后端/发布版本与可撤销移动前置，虚构写入测试不替代真实事务验收。


## 重复记录合并决定（2026-10-07）

版本操作确认弹窗已由用户“体验通过，继续下一步”确认。本批实际导入审核及版本移动共享 MergeDecisionMatrix，复用现有 shadcn 派生 FormField/Input/Select/Button/Table/Pagination/Skeleton/StatusMessage 与全局 tokens，无新增依赖。目标与来源逐项对照、相同字段及差异数量、全字段展开和四组分页统一展示；手机完整表格在自身区域滚动。

保留原行对ID、跨页决定、相同字段默认处理及全部依据齐备才可提交的规则。导入审核带操作人自动依据，版本移动无操作人时需手填。预览失败仅显式重读原范围；未知命令结果保留决定并使用原操作键重试。实际调用保持原请求与业务写入。

九种虚构状态、27张开发基线纳入既有manifest；有效4项Story功能、2项实际路由虚构API路径、9项原定向单测、28项manifest/axe和30项独立视觉比较通过。截图发现手机错误按钮竖排后，仅复查受影响范围。TypeScript、目标ESLint、55模块Token零例外及p0_catalog构建通过。开发完成待本地体验，未正式验收或部署。

体验 http://127.0.0.1:17641/?path=/story/patterns-merge-decision-matrix--reference：展开完整字段，切处理方式与依据，批量应用当前页，翻页返回核对保留；另看 Identical、HiddenFields、ReadFailure 与 InDialog。样板仅虚构数据，无需账号、不请求真实API；真实页面仍需原账号、后端、来源和目标版本。本轮未重新验收完整真实上传/合并事务。


## 最终发布确认（2026-10-07）

重复记录合并决定已由用户“体验通过，继续下一步”确认。本批实际 PublicationDialog 复用现有 Radix/shadcn 派生 Dialog、FormField/Control、Button、StatusMessage/StatusBadge 和 tokens，无新增依赖。校验回执、稳定版本ID、行数/合计/警告与跨日期两侧生效范围统一；退货快照准备和最终发布结果分别展示。说明默认值及提交controller未改，业务 DraftReviewGate 字节不变。

发布处理中使用既有 dismissDisabled 和 loadingLabel；锁定控件后内容仍可键盘滚动。11种虚构状态、33张新开发基线与原草稿确认六图纳入既有回归；有效4项Story功能、2项实际普通发布路由虚构API路径、5项原组件、34项manifest/axe及42项独立视觉比较通过，TypeScript/目标ESLint/56模块Token零例外与构建通过。首次窄屏处理中滚动无键盘入口已修复，原日志保留。开发完成待体验，未部署或正式验收。

体验 http://127.0.0.1:17641/?path=/story/patterns-publication-confirmation--reference，另看 Failure、CrossDate、ReturnBuilding/ReturnReady。样板仅虚构回执，无账号或真实API；实际流程仍需原管理账号、后端和已校验待发布草稿，跨日期最终生效仍由管理员操作。本轮不执行真实发布、退货快照或跨日期事务。


## 字段对照与修正抽屉（2026-10-07）

上一批最终发布确认及快照进度已由用户“体验通过，继续下一步”确认。本批实际 ReviewDataTable 的 CellDrawer 使用现有 Radix/shadcn 派生 Dialog 抽屉与设计系统控件，无新增依赖。统一源值、版本基础与当前值的对照、稳定行/字段/父版本ID、恢复来源、备注修订与历史。修改及恢复原因多行显示；保存失败保留输入，处理中锁定关闭但仍支持键盘滚动。620px以下业务键列随表格横向滚动，避免遮住可编辑字段；桌面固定列保留。

字段转换与业务controller归一不变，DraftReviewGate字节不变。10虚构状态与30张新开发基线接现有manifest；有效4项Story功能、2项实际路由虚构API路径、5项原组件、31项manifest/axe及33项独立视觉比较通过，旧草稿Reference三图不变。TypeScript/定向ESLint/57模块Token零例外与构建通过。失败日志及修复记录保留。

体验 http://127.0.0.1:17641/?path=/story/patterns-field-review--reference，点击金额字段，试修改、三种恢复和备注修订；另看Nullable/Readonly/SaveFailure/Saving。样板无需账号、无真实API；实际流程仍需原管理账号、后端和草稿。development_complete/ready_for_user_review=true，user_verified/accepted/UI_deployed=false；本轮仅本地开发，未部署。


## 新增纠错行与排除/恢复行（2026-10-07）

字段对照与修正抽屉已由用户“体验通过，继续下一步”确认。当前批次实际 ReviewDataTable 的 AddRowDrawer/RowStateDrawer 复用现有 Radix/shadcn 派生 Dialog、表单与反馈组件；复用字段抽屉的布局样式，无新增依赖。来源批次、完整字段/空值、稳定行ID、状态影响/说明、备注修订和历史统一展示。提交期间锁定关闭和控件，内容仍可键盘滚动。无来源仍禁新增，来源删除行仍禁恢复，人工删除行按原规则处理。

原controller和业务 DraftReviewGate 保持；intentional变更为Dialog焦点/关闭、busy UI锁定与无来源可见说明。14虚构状态、42张新开发基线接原manifest；有效4项Story功能、2项实际路由虚构API完整路径、3项原组件/命令合同、43项manifest/axe和48项独立视觉比较通过。字段/草稿Reference六图不变。TypeScript、目标ESLint、58模块Token零例外和构建通过。首次测试/动态模块失败保留，仅复查实际受影响范围。

体验 http://127.0.0.1:17641/?path=/story/patterns-row-review--reference，填写新增行并保存；另看Exclude/Restore、AddFailure/StateFailure、SourceDeleted和Nullable。样板全部虚构、无需账号、不发实际API；实际流程仍需原管理账号、后端、草稿和来源。development_complete/ready_for_user_review=true，user_verified/accepted/UI_deployed=false；本轮仅本地，未部署。

## 校验问题审核（2026-10-07）

上一批新增纠错行与排除/恢复行已由用户“体验通过，继续下一步”确认。实际 ReviewDataTable 使用提取的 IssueReviewPanel，复用现有 shadcn 派生 FormField/Button/StatusBadge/StatusMessage 和全局 tokens，零新增依赖。区分警告/阻断和待处理/已确认/已解决；并列源值与处理值，显示稳定问题/规则/行/字段及已有审核记录。手机单列问题卡、长值换行，null 显示—、真实0保留。

原 action 选择和 requires_note 禁用规则保持；intentional 变更为 await/catch 提交、对应问题内可见错误、保留说明、pending 按钮和 busy 控件。修复原 void 回调的未处理 Promise。父 DraftReviewGate 字节不变，API payload、校验绑定、CSRF/幂等和刷新保持。无问题仍不显示问题区，不代替正式校验结论。

8虚构状态、24新开发基线接原manifest；3项Story功能、2项实际路由虚构API完整路径、2项定向组件测试、25项manifest/三档axe及30项独立视觉比较通过，旧行/草稿Reference六图不变。TypeScript/定向ESLint/59模块Token零例外/p0_catalog构建通过，原500KB提示保留。初次类型/API测试定义问题和原日志保留，未执行全manifest或正式发布。

体验 http://127.0.0.1:17641/?path=/story/patterns-issue-review--reference：在页面下方问题卡填写审核说明，确认警告、标记解决、重新打开；另看Handled/OptionalNote/LongValues/Saving/SaveFailure（后两项填写说明并提交）。虚构样板无需账号、不请求实际API；实际页面仍需原管理账号、后端、草稿及校验问题数据。development_complete/ready_for_user_review=true，user_verified/accepted/UI_deployed=false，未部署。Skill frontend-design。

## 共用备注修订编辑器（2026-10-07）

校验问题审核已由用户“体验通过，继续下一步”确认。本批实际 NoteRevisionEditor 由批次、版本、行与字段备注复用，使用现有 shadcn 派生 FormField/Select/Button/StatusBadge/StatusMessage、Control样式和全局tokens，无新增依赖。统一当前修订标识、内容与字数/原4096限制、可见范围、操作与错误反馈；内部批次仍无可见范围选择。

父 ReviewDataTable/DraftReviewGate/BatchNotePanel 字节不变；泛型callback、note key/id/revision绑定、参数与原note同步effect保持。版本/行/字段传原文，批次按原handler去除首尾空格；不改API/CSRF/幂等/并发合同。新增本地pending锁定输入及取消/提交，失败保留body/visibility，显式重试；保存和取消后焦点回到修订按钮，取消后的未提交草稿保留行为沿用原实现。短加载文案适应手机，完整可访问名称保持。

9虚构状态、27新基线及21受影响编辑基线纳入原manifest。3项Story功能、4项有效实际路由虚构API路径（首轮batch2通过，新version/row/field夹具trim错误2失败，改夹具后2通过）、3项组件（其余2跳过）、49项有效manifest/三档axe、54项独立视觉比较通过；原issue/import-evidence Reference六图不变。TypeScript/目标ESLint/60模块Token零例外/p0_catalog构建通过，原500KB提示保留。首失败日志/trace、旧基线、手机加载文案折行首图和审批历史保留；只复查受影响范围，不执行全manifest或正式发布。

体验 http://127.0.0.1:17641/?path=/story/patterns-note-revision--reference：点击修订备注，修改内容/可见范围，保存后核对修订号并再次打开；另看Batch/Row/Field/ViewerVisible/LongContent/Empty/Saving/SaveFailure。样板虚构、无需账号、不请求API。实际四类备注仍需原管理账号、后端、草稿或导入批次及已有备注数据。development_complete/ready_for_user_review/user_verified=true，accepted/UI_deployed=false，仅本地开发，未部署。Skill frontend-design。

用户2026-10-07原话“体验通过，后续还有哪些需要更改的”，确认本批本地样板；后续范围讨论不自动授权新UI实施或发布。


## 草稿数据对照表（2026-10-07）

草稿数据对照表本地UI已开发完成：实际ReviewDataTable与7种虚构Patterns/Draft Data Table状态共享实现，复用现有shadcn派生FormField/SearchInput/Select/Checkbox/Button/Pagination/EmptyState及全局tokens，零新增依赖。统一搜索/字段/行状态/差异导航、中文行状态、源表与基础版本差异说明、当前页匹配计数与两种空态；清除筛选只清本地状态。修正base-only差异被误报为来源差异的可访问文本；按表格容器宽度调整固定业务列，解决桌面双栏窄容器遮挡排序按钮，手机仅表格内部横滚。原表格controller及审核抽屉逻辑归一一致，DraftReviewGate和旧CSS字节不变；row_id/logical_row_id/字段/source恢复绑定、筛选当前页范围、原50行API分页与写入/刷新/并发合同保持。2项Story功能、2项最终实际路由虚构API完整路径、9项组件、37项manifest/三档axe通过；21新基线和135原消费者基线按授权本地更新（107图变化/28图字节一致，原135图及审批历史保留），独立162项视觉比较通过。首次桌面固定列遮挡和手机测试差异游标预期失败保留；API夹具最终按真实请求50行/总56行两页核对。TypeScript/目标ESLint/61模块Token零例外/p0_catalog构建exit0；8605模块，主包1045.53KB/gzip324.13KB，既有500KB提示保留。任务Vite17341及所属esbuild按身份停止，Storybook17641保留。development_complete/ready_for_user_review=true，user_verified/accepted/UI_deployed=false。体验http://127.0.0.1:17641/?path=/story/patterns-draft-data-table--reference：搜索/清除→行状态→仅看差异→字段/排序→上一/下一差异→抽屉核对→翻页；另看LongValues/Unchanged/Empty/FilterEmpty/Busy/SecondPage。样板虚构无需账号、不请求API；实际高级草稿审核仍需原管理账号、后端、草稿和来源，本轮只以虚构API验证。未读写data/、真实库或生产，不改冻结来源/LAN/Alpha，无commit/push/merge/deploy/migration或新Collect。证据storybook-import-review-20261005-01/draft-data-table-20261007/result.json；Skill frontend-design。


2026-10-07工作台单元格反馈本地开发完成：实际日期工作台与Storybook共享EditableDataGrid/DateWorkbenchView，复用既有shadcn派生Input、Lucide及全局tokens，零新增依赖。统一焦点/待保存/正在保存/已保存/未保存/版本冲突，完整错误关联输入并保留内容，Enter/离开保存、Esc放弃；保存期间可继续输入，旧响应不覆盖新输入，重提仍绑定最新cell/head revision与新operation key。窄容器冻结身份列剩余不足180px时保留固定行号、业务列随表格滚动，解决编辑与错误说明遮挡；共享列设置/存储偏好不改。原DateWorkbenchPage controller、workbenchApi、旧页面CSS和输入同步/blur/change/Enter/Escape处理保持字节或归一一致。新增CellEditing/CellSaving/CellSaved/CellConflict/CellLongError五故事；有效6项Story完整功能、4项实际路由虚构API路径、14项定向单测、22项manifest/三档axe通过，截图发现的手机遮挡修复后移动端2项Story+2项实际路径+7项axe定向复查通过。初次实际桌面筛选后搜索在查询重载期间使用旧DOM，已补结果加载同步并原失败定向复查通过；首失败日志/trace保留。新增15张开发基线、更新原Draft/SaveFailure六张，旧30张已快照，独立比较相关21+原Reference/Manager/草稿数据表Reference九张共30项通过，未整套回归。TypeScript/目标ESLint/62模块Token零例外/p0_catalog构建exit0；8606模块，主包1047.09KB/gzip324.58KB，既有500KB提示保留。任务Vite17341及所属esbuild按PID/创建时间/父子关系/命令核对停止，终端exit1为主动清理，Storybook17641保留。development_complete/ready_for_user_review=true，user_verified/accepted/UI_deployed=false。体验http://127.0.0.1:17641/?path=/story/pages-date-workbench--cell-conflict：核对冲突与完整说明→Esc放弃→重新输入Enter保存；另看CellEditing/CellSaving/CellSaved/CellLongError和Manager完整编辑流程。样板虚构无需账号、不请求实际API，刷新样板重置示例；实际路由仍需原管理账号/后端/已初始化报表，本轮只用虚构API验证保存和刷新。不读写data/、真实库或生产，不改冻结来源/LAN/Alpha，无commit/push/merge/deploy/migration或新Collect。证据storybook-import-review-20261005-01/workbench-cells-20261007/result.json；Skill frontend-design。


2026-10-07商品审核高级工作流表单本地开发完成：CatalogWorkflowActions在实际/catalog/imports/:import_id与8种虚构Patterns/Catalog Workflow Forms状态共享，沿用现有shadcn派生FormField/Input/Button/StatusMessage/StatusBadge及tokens，零新增依赖。统一批准预览的风险/纳入行/仅审计行/目录发布修订，批准与拒绝/撤回共用原reason；调整基准明确导出编号、数字限制和重校验说明，提交中锁定表单，失败保留输入，批准结果保留V号及原三条导航。高风险/无权限/未保存/只读继续服从原服务器权限和blockedReason；移除完整审核页重复的阻断提示，改由共享组件展示。原run控制器除可注入command函数外归一一致，默认仍catalogCommand；保留workflow/catalog publication revision、projection ID/digest、replacement export ID、CSRF/operation key、409清预览、批准结果先记录再刷新及原API/onChanged合同，读取失败不会重新显示批准按钮。父审核controller在return前逐字一致，实际路由controller/API/全局目录CSS字节一致，稳定ID与映射/历史解释不变。5项Story完整功能、4项实际工作流虚构API路径+1项原审核批量保存路径、3项原单测、34项manifest/三档axe通过；TypeScript/目标ESLint/63模块Token零例外/p0_catalog构建exit0，8607模块，主包1048.38KB/gzip325.03KB，既有500KB提示保留。代理审阅桌面/手机预览、失败、批准及完整消费者截图；24新开发基线与24原消费者图按授权本地更新（原件已快照），独立比较48相关+工作台冲突三档3张共51通过，未整套回归。任务Vite17341及esbuild按PID/创建时间/命令/父子链核对停止，终端exit1为主动清理，Storybook17641保留。development_complete/ready_for_user_review=true，user_verified/accepted/UI_deployed=false。体验http://127.0.0.1:17641/?path=/story/patterns-catalog-workflow-forms--reference：生成批准预览→输入批准原因→展开高级操作核对替代导出编号→调整基准后重新预览→确认批准虚构目录；另看HighRisk/Rebase/Saving/Failure/Blocked/ReadOnly/Approved。样板虚构无需账号、不请求实际API，刷新重置示例；实际页面需原管理账号/后端/目录草稿，本轮只用虚构API验证，不代表真实目录已批准。未读写data/、真实库或生产，不改冻结来源/LAN/Alpha，无commit/push/merge/deploy/migration或新Collect。证据storybook-import-review-20261005-01/catalog-workflow-forms-20261007/result.json；Skill frontend-design。


2026-10-08身份归属、冲突与恢复面板本地开发完成（沿用2026-10-07“体验通过，批准继续”授权）：实际商品导入审核页SKU映射与10种虚构Patterns/Catalog Identity Owners状态共享现有组件，沿用shadcn派生Button/FormField/Input/StatusBadge/StatusMessage/EmptyState和全局tokens，零新增依赖。分组显示正式归属、草稿占用及正式忽略；保留稳定ID、原链接、编码row_key GET、恢复mutation/revision/trimmed原因/CSRF/操作键和既有权限/未保存/忙碌锁定。恢复写入成功后先记修订号，后续读取失败只显式重读、不重复提交；正式忽略仍需原批准流程。修复桌面审核表格网格最小宽度造成的裁切及窄屏错误动作逐字换行。5项Story功能、3项实际路由虚构API完整路径、12项定向单测、31项manifest/三档axe通过，最后修正后复查6项直接受影响axe；30张新开发基线、独立36项视觉比较通过（含原审核及工作流表单参考三档），未更新旧页面基线。TypeScript/目标ESLint/64模块Token零例外/p0_catalog最终构建exit0，主包1051.47KB/gzip325.77KB，既有500KB提示保留。首次RED回归、预览服务停止导致零执行启动失败、测试类型/样板lint/诊断lint及一次修正期间视觉差异原记录保留，最终对应检查通过。任务Vite与esbuild已按PID/创建时间/命令/父子关系清理，终端exit1为主动停止；新Storybook17641保留供体验。development_complete/ready_for_user_review=true，user_verified/accepted/UI_deployed=false。体验http://127.0.0.1:17641/?path=/story/patterns-catalog-identity-owners--reference：查看归属与冲突→填写恢复原因→恢复草稿；另看ReadFailure/RestoreFailure/RefreshFailure/ReadOnly/LongReason。样板虚构无需账号、不请求真实API，刷新重置；实际页仍需原管理账号/API/已初始化目录草稿，本轮用全API拦截验证。未读写data/、真实库或生产，不改冻结来源/LAN/Alpha，无commit/push/merge/deploy/migration或新Collect。证据storybook-import-review-20261005-01/catalog-identity-owners-20261007/result.json；Skill frontend-design。


2026-10-08用户截图反馈“这个地方可以再优化一下”：同一身份归属面板改为自适应分组记录，宽屏并排、窄容器堆叠，标题右侧统一数量；商品/审核批次整行链接复用原href和可访问名称，显示对象图标、SKU及原草稿排除/映射占用状态，增加token化悬停和键盘焦点，减少裸链接与远端信息的视觉割裂。复用现有shadcn派生StatusBadge/global tokens，未改读取/恢复/权限/修订/刷新控制器或依赖。5项完整Story路径、桌面/手机Tab焦点及悬停、30项三档axe与独立30项视觉比较通过，TypeScript/目标ESLint/64模块Token零例外通过；本批仅展示改动，复用有效实际路由与单测行为证据，不追加整套检查。30张相关开发基线已按本次反馈更新，原图/原result和首次不存在info tone导致的类型/Story失败保留，改用组件实际支持的quiet tone后对应复查通过。development_complete/ready_for_user_review=true，user_verified/accepted/UI_deployed=false，仍待当前版本体验；虚构样板无需账号，不请求真实API，未部署。Skill frontend-design。


2026-10-08商品导入安全来源证据面板本地开发完成：实际商品主档审核来源证据分类与10种虚构Patterns/Catalog Source Evidence状态共享CatalogEvidencePanel，复用现有shadcn派生Button/StatusBadge/StatusMessage/EmptyState/Skeleton/Spinner及tokens，零新增依赖。统一来源卡片、安全预览/摘要、完整标识及复制/隐藏反馈；补加载/空结果/列表失败显式重读/权限未通过/查看中/长内容/权限变化状态，捕获剪贴板拒绝不报成功。保持import_id/workflow_revision/source_ref_id、原GET和最多50条、SafeSourceRefView及useSensitiveReveal/RequestGate/AuthzGeneration源码字节一致，不改来源规范化/摘要/解码/权限清除规则；来源列表取消过时请求，敏感行随权限generation/批次/修订重建，隐藏调用原purge。实际审核与路由controller及全局目录CSS/package/lock字节一致；仅本地虚构API只读关联，未读取真实来源或改变业务身份。4项完整Story路径、2项实际路由虚构API路径、3项相关单测、31项manifest/三档axe及独立30项视觉比较通过；30张新开发基线纳入现有回归并经桌面/手机消费者、权限失败、长预览/长标识和读取失败截图审阅，旧页面基线未更新。TypeScript/目标ESLint/65模块Token零例外/p0_catalog构建exit0，主包1054.86KB/gzip326.75KB，既有500KB提示保留。首次未使用测试参数类型失败、Windows剪贴板CRLF断言失败及StrictMode初次中止读取的虚构夹具失败已定向修正，首日志/图/trace保留；本轮不修改真实编码或clipboard数据。任务Vite17341及esbuild按PID/父子链/创建时间/命令核对停止，终端exit1为主动清理，Storybook17641保留。development_complete/ready_for_user_review=true，user_verified/accepted/UI_deployed=false。体验http://127.0.0.1:17641/?path=/story/patterns-catalog-source-evidence--reference：查看完整标识→复制→隐藏→刷新确认只剩安全预览；另看ReadFailure/RevealFailure/Revealing/LongPreview/LongIdentifier/BoundaryChange（查看后模拟权限变化）。样板完全虚构无需账号、不请求实际API；实际页仍需原管理账号/API及初始化批次，本轮仅全API拦截验证。未读写data/、真实库/生产/冻结来源，不改LAN/Alpha，无commit/push/merge/deploy/migration或新Collect。证据storybook-import-review-20261005-01/catalog-evidence-panel-20261008/result.json；Skill frontend-design。


## 商品审核问题定位（2026-10-08）

2026-10-08商品审核问题定位面板本地开发完成：CatalogIssueSummary实际消费者与10种虚构Patterns/Catalog Issue Summary状态共享现有组件，复用shadcn派生Button/StatusBadge/EmptyState、Lucide图标和tokens，零新增依赖。问题编号、分类/字段/原因、服务端严重程度和row_key分层展示，手机操作随卡片换行；区分警告/错误/阻断，未知字段/reason/severity保留原文，无row或handler不生成定位按钮。解析失败保留修正原文件与可恢复故障的区别，无逐行问题不代表审核通过。status门槛、列表顺序及完整原issue callback不变；父审核页、分类表、路由、API/types、全局目录CSS/package/lock与本轮快照字节一致，未改变稳定ID、原section/row_key/field定位、保存/修订/CSRF/幂等合同。4项完整Story路径、桌面/手机2项实际路由全API拦截路径（筛选解除→跨分类定位聚焦→两行修改保存→重新校验→刷新保留）、12项有效定向单测、34项manifest/三档axe及独立33项视觉比较通过；30张新状态和3张直接消费者开发基线纳入现有回归，原消费者基线已备份。TypeScript/目标ESLint/66模块Token零例外/p0_catalog构建exit0，主包1056.54KB/gzip327.19KB，既有500KB提示保留。首次实际测试搜索框名称不符2失败及原单测拆分code文本查询1失败（分类表10项仍通过）仅修正测试查询，首日志/图/trace保留，受影响复查通过。任务Vite17341及esbuild按PID/父子关系/创建时间/命令核对停止，终端exit1为主动清理，Storybook17641保留。development_complete/ready_for_user_review=true，user_verified/accepted/UI_deployed=false。体验http://127.0.0.1:17641/?path=/story/patterns-catalog-issue-summary--reference：点击或Enter触发定位问题，核对分类/行/字段参数；另看Warning/Blocking/Unlocatable/ParseFailed/Empty/ReadOnly/UnknownCode/LongValues/ManyIssues。样板虚构无需账号、不请求实际API、刷新重置；实际审核页需原管理账号/API及已初始化草稿，本轮仅隔离虚构夹具验证。未读写data/、真实库/生产，不改冻结来源/LAN/Alpha，无commit/push/merge/deploy/migration或新Collect。证据storybook-import-review-20261005-01/catalog-issue-summary-20261008/result.json；Skill frontend-design。


## 目录工作簿操作面板（2026-10-08）

商品审核问题定位面板已获用户“体验通过继续下一步”确认。

2026-10-08目录工作簿操作面板本地开发完成：实际批量维护页和11种虚构Patterns/Catalog Workbook状态共享CatalogExportView，复用既有shadcn派生Button/FormField/Input/StatusBadge/StatusMessage/Spinner、Lucide和全局tokens，无新增依赖。三步工作流、候选export_id与发布修订、在线审核及离线XLSX分区、已选文件、恢复/过期/容量/无下载与无恢复权限/前置不足/忙碌/上传失败状态统一；文件选择按钮样式限定模块，忙碌期间禁止更换文件，避免上传中的文件与反馈错位。原生成/轮询/人工恢复/上传/跳转容器、API/state/types、实际维护页与全局CSS/package/lock字节一致，保留export_id/job_revision/catalog_publication_revision、下载href、六表模板约定、上传原始bytes/文件名/content-type、CSRF/幂等及return_to行为。4项Story完整路径、2项桌面/手机实际路由全API拦截路径（生成失败→恢复→在线审核及返回上下文→上传失败保留文件→相同操作键显式重试→审核页刷新）、4项原定向单测、52项manifest/三档axe及最终文件控件6项axe通过。33张新状态和18张直接维护消费者开发基线已纳入现有回归，旧图备份保留；独立51项视觉比较通过，宽窄屏/旧修订/忙碌截图审阅。TypeScript/目标ESLint/67模块Token零例外/p0_catalog构建exit0，主包1058.15KB/gzip327.66KB，原500KB提示保留。首实际夹具误用safe_result包装2失败及测试null类型推断失败已仅修正夹具/类型，原失败日志/图/trace保留，对应复查通过。任务Vite17341与esbuild按PID/创建时间/命令/父子链清理，终端exit1为主动停止；Storybook17641保留。development_complete/ready_for_user_review=true，user_verified/accepted/UI_deployed=false。体验http://127.0.0.1:17641/?path=/story/patterns-catalog-workbook--reference：开始在线审核看虚构导航；选择虚构XLSX→上传，或在Idle生成/Failed恢复/UploadFailure重试；另看Unready/Building/NoResume/Stale/Capacity/NoDownload/Busy。样板虚构无需账号、不请求实际API、刷新重置；下载仅显示入口说明不下载真实文件，实际页面需原管理账号/API与来源准备就绪，本轮仅隔离夹具验证，不证明真实工作簿解析/后端或业务库通过。未读写data/、真实库/生产，不改冻结来源/LAN/Alpha，无commit/push/merge/deploy/migration或新Collect。证据storybook-import-review-20261005-01/catalog-workbook-20261008/result.json；Skill frontend-design。


## 已有商品审核批次（2026-10-08）

目录工作簿面板已获用户“体验通过继续下一步”确认。

2026-10-08已有商品审核批次列表本地开发完成：实际批量维护与8种虚构Patterns/Catalog Import History状态共享CatalogImportHistoryView，沿用现有shadcn派生Button/EmptyState/Skeleton/StatusBadge/StatusMessage、Lucide及tokens，零新增依赖。分层展示批次、继续审核/批准结果/归档操作、来源方式和修订；本页数量不冒充总数，沿用服务端has_next和原上一页/下一页合同，后续空页提示返回上一页而不误导重新生成候选。加载/读取失败/空/第二页/撤回及取代/长编号/未知状态覆盖，原状态文本回退、稳定import_id/href及onOpenReview保持。列表请求controller、实际维护及审核路由、导航状态、API/types、全局CSS和package/lock字节不变；关联审核页仅修正一处已批准状态仍显示未生效的矛盾文案，其他源码LF归一一致，不改变任何写入/批准逻辑。4项Story完整路径、桌面/手机2项实际路由全API拦截路径（首读取失败→显式重读→草稿审核及返回→第二页失败→当前页重读→批准结果及刷新→返回维护重置第一页）、1项原定向单测、43项manifest/三档axe及42项独立视觉比较通过。24张新状态和18张直接消费者开发基线纳入现有回归，原图/审批历史保留，桌面/手机/长编号/读取失败图经审阅。TypeScript/目标ESLint/68模块Token零例外/p0_catalog构建exit0，主包1059.38KB/gzip328.03KB，原500KB提示保留。首次实际测试误查已批准页面不存在的“当前修订”标签2失败已改为真实修订和批准结果断言；同时发现并修正关联矛盾文案，首日志/图/trace保留，对应复查通过。任务Vite17341/esbuild按PID/创建时间/命令/父子链清理，终端exit1为主动停止，Storybook17641保留。development_complete/ready_for_user_review=true，user_verified/accepted/UI_deployed=false。体验http://127.0.0.1:17641/?path=/story/patterns-catalog-import-history--reference：用鼠标或Enter打开批次→返回→下一页/上一页；另看Loading/ReadFailure刷新重读、Archived/LongValues/UnknownStatus。样板虚构无需账号、不请求实际API、刷新重置；实际维护页仍需原管理账号/API和已初始化数据，本轮只做隔离虚构GET关联，未创建候选或执行真实写入。未读写data/、真实库/生产，不改冻结来源/LAN/Alpha，无commit/push/merge/deploy/migration或新Collect。证据storybook-import-review-20261005-01/catalog-import-history-20261008/result.json；Skill frontend-design。


## 商品候选批次（2026-10-08）

已有商品审核批次列表已获用户“体验通过，继续下一步”确认。

2026-10-08商品新变体与Seller SKU候选面板本地开发完成：实际商品详情与7种虚构Patterns/Catalog Pending Candidates状态共享CatalogPendingItems，复用既有shadcn派生LinkButton/StatusBadge、Lucide和tokens，零新增依赖。局部CSS模块统一批次记录卡、状态/数量/原审核修订及原SKU预览层级；手机堆叠与长编码换行，无预览明确提示、零数量照实显示、空数组保持实际面板不显示。原items顺序/import_id/review_path、三状态文本、canReview和location.pathname返回语义保留，无候选生成、reveal或批准写入。商品详情controller/view/story、导航Context、API/types、全局CSS和package/lock字节一致。4项Story完整路径、桌面/手机2项实际路由虚构GET路径（首读失败→显式恢复→审核/返回→硬刷新→空数组/恢复→只读权限）、3项原商品详情单测、25项有效manifest/三档axe及24项独立视觉比较通过。21张新状态和3张直接消费者开发基线纳入现有回归，原图/审批历史保留；桌面/手机/长编码/只读及实际详情消费者截图已审阅。首次空状态测试把StatusMessage文字误当heading，axe和基线各3失败；修正测试定位后仅复查受影响3项，复用原22项axe/21张基线，日志/图/trace保留。TypeScript/目标ESLint/69模块Token零例外/p0_catalog构建exit0，8613模块，主包1060.07KB/gzip328.26KB，原500KB提示保留。任务Vite17341/esbuild按PID/创建时间/命令/父子链核对停止，终端exit1为主动停止，Storybook17641保留。development_complete/ready_for_user_review=true，user_verified/accepted/UI_deployed=false。体验http://127.0.0.1:17641/?path=/story/patterns-catalog-pending-candidates--reference：用鼠标或Enter进入任一批次→核对目标和商品返回路径→返回；另看ReadOnly/Empty/NoPreviews/ZeroCounts/LongPreviews/ManyBatches。样板虚构无需账号、不请求实际API、刷新重置；实际商品详情仍需原账号/API与已初始化商品，本轮只做隔离虚构GET关联。保留style_id商品身份和每import_id独立批次粒度，不合并/规范化Seller SKU、不扩大来源读取、不改变唯一写入权威。未读写data/、真实库/生产，不改冻结来源/LAN/Alpha，无commit/push/merge/deploy/migration或新Collect。证据storybook-import-review-20261005-01/catalog-pending-candidates-20261008/result.json；Skill frontend-design。


## 商品审核分类编辑（2026-10-08）

候选面板已获用户“体验通过，继续下一步”确认。

2026-10-08商品审核分类编辑控件与状态样板本地开发完成：实际审核页与12种虚构Patterns/Catalog Section Editors共享CatalogImportSectionTable，复用既有shadcn派生Input/Select/Button及共享Control样式与全局tokens，零新增依赖。报告候选/手工输入/清空、原自动扩展多行文本、状态/映射/处理选择、错误轮廓与禁用反馈统一；解析异常从窄表格改三栏/两栏/手机单栏记录卡，手机保留可见字段标签。原editable fields、筛选/pending/source identity/mutation type与draft/dirty/stale/in-flight/保存ack/修订/失败/焦点/快捷键controller按前快照LF归一逐字一致；保留原canEdit/busy、500行上限、hidden edits保存、原manual/candidate/clear回调及字段可访问名。审核Page/View/原Story/CSS、导航/身份归属、API/types/options与DS基础源码/package/lock字节一致。有效5项Story完整路径、8项实际路由虚构API完整路径、10项原单测、61项有效manifest/三档axe和60项独立视觉比较通过。截图发现桌面异常字段挤压/手机缺标签后已局部修正，受影响2项Story、2项四类字段实际路径及16项axe复查通过，其余未受影响结果复用。36张新状态与24张原审核页消费者开发基线已纳入现有回归，原图/审批历史保留；参考/手机/异常/长文本及审核页图已审阅。实际路径核对候选→手动→清空焦点→报告候选、四类mutation type及row_key/decision_group_key/target_sku_row_key、修订3→7与刷新保留；原失败保留编辑、ack后明细失败只读恢复、筛选隐藏/跨分类修改及键盘保存和权限路径通过。首次新实际测试误用Seller SKU标签导致2定位失败，改为原SKU映射标签后复查；故事payload类型推断及无await的async回调lint问题已修正，首日志/图/trace保留。TypeScript/目标ESLint/70模块Token零例外/p0_catalog构建exit0，8614模块，主包1060.56KB/gzip328.46KB，原500KB提示保留。任务Vite17341/esbuild按PID/父PID/创建/命令核对停止，终端exit1为主动停止，Storybook17641保留。development_complete/ready_for_user_review=true，user_verified/accepted/UI_deployed=false。体验http://127.0.0.1:17641/?path=/story/patterns-catalog-section-editors--reference：报告候选切手动→清空→返回报告候选→修改第二行→搜索隐藏第二行→核对并保存；另看Skus/Mappings/Exceptions/ReadOnly/FieldIssues/Busy/Empty/FilteredEmpty/SaveFailure/RefreshFailure/LongValues。样板虚构无需账号、不请求真实API、刷新重置；实际审核仍需原管理账号/API和已初始化批次，本轮写请求全部在隔离夹具拦截，不批准或修改真实批次。关联仅沿用import_id/row_key/decision_group_key与目标SKU行身份及原scope，不改变规范化/唯一写入权威/真实数据授权。未读写data/、真实库/生产，不改冻结来源/LAN/Alpha，无commit/push/merge/deploy/migration或新Collect。证据storybook-import-review-20261005-01/catalog-section-editors-20261008/result.json；Skill frontend-design。


## 目录读取反馈（2026-10-08）

商品审核分类编辑已获用户“体验通过，继续下一步”确认。

2026-10-08目录读取失败与初始化引导本地开发完成：实际目录版本、待归属来源与已有候选局部失败共享CatalogReadFailurePanel，原版本失败Story已采用真实组件，8种虚构Patterns/Catalog Read Feedback覆盖显式重试/持续失败/限流/无权限/不存在/无效查询/初始化不足/长文案。复用现有shadcn派生Button/LinkButton/StatusBadge、Lucide与全局tokens，零新增依赖；错误原因、下一步和动作分层，手机换行不横向溢出。原错误映射、读取controller、CatalogSetup真实只读容器及View、API/types/DS基础/package/lock与本轮前快照字节一致；保留setup优先于retry、原callback/href及仅setup挂载准备读取，403/404/422无重试且不读取准备信息。有效4项Story完整路径、10项实际App路由全API拦截路径通过：503重复失败后键盘显式重试→V4恢复→刷新，429手动恢复，403/404/422只导航；409缺快照→准备读取失败→显式刷新→74份虚构报告状态，只读且不代替初始化；已有候选局部失败保留来源清单及from/to/return_basis URL，恢复和刷新仍一致。5项定向单测通过（另2项无关来源事实测试未执行）、31项manifest/三档axe与30项独立视觉比较通过；24张新状态和6张受影响消费者开发基线纳入既有回归，原6图和审批历史保留，桌面/手机/初始化/局部失败截图已审阅。TypeScript/目标ESLint/71模块Token零例外/p0_catalog构建exit0，8615模块，主包1061.85KB/gzip328.82KB，原500KB提示保留。首Storybook热更新未加载新export，重新写入目标文件后原进程源码已刷新；首实际测试未计入React StrictMode初次双挂载，按真实调用次数修正；既有单测仍匹配旧74份文案，仅改为现有已发布报表区域数字断言；首失败日志/图/trace保留，业务源码未为测试改动。Vite17341与所属esbuild按PID/父PID/创建时间/命令核对停止，terminal exit1为主动清理；Storybook17641原PID18044保留。development_complete/ready_for_user_review=true，user_verified/accepted/UI_deployed=false。体验http://127.0.0.1:17641/?path=/story/patterns-catalog-read-feedback--reference：键盘聚焦重新读取→Enter→恢复为空目录结果→刷新重置；另看RepeatFailure/RateLimited/Forbidden/NotFound/InvalidQuery/Setup/LongMessage。样板虚构无需账号、不请求真实API，实际页面需原管理账号/API及初始化条件；本轮仅GET夹具拦截，不验证真实数据/后端或初始化写入。未读写data/、真实库/生产，不改冻结来源/LAN/Alpha，无commit/push/merge/deploy/migration或新Collect。证据storybook-import-review-20261005-01/catalog-read-feedback-20261008/result.json；Skill frontend-design。


## 已批准目录版本（2026-10-08）

目录读取反馈样板已获用户“体验通过，继续下一步”确认。

2026-10-08已批准目录版本列表本地开发完成：实际/catalog/versions与8种虚构Patterns/Catalog Versions共享CatalogVersionsView，沿用既有shadcn派生Table/Button/LinkButton/Skeleton/EmptyState/StatusBadge、Lucide及全局tokens，零新增依赖。批准记录分层展示版本号、目录记录ID、原风险、批准时间与基础目录记录，null基础版本显示首次，未知风险及缺失字段仍沿用原安全文本回退；不把base_catalog_version_id误标为版本号，不排序或推断当前生效版本。手机保留可键盘聚焦的横向滚动表格与完整信息。原controller/API/helper/读取失败/初始化/维护容器、基础组件源码与package/lock按本轮前快照字节一致；原空列表初始化href、显式重新读取、失败重试、迭代/key/risk/首次判定保持。有效8项Story功能（4新样板与4读取反馈消费者）、5项实际App路由全API拦截路径（2新历史列表桌面/手机与3原版本失败/限流消费者）、3项原定向单测、34项manifest/三档serious-critical axe通过。完整路径核对初次加载→记录104/V4引用基础记录103→未知风险/首次→键盘表格滚动和重新读取→503显式重试恢复→刷新保留→空结果及初始化href；样板空列表导航及持续加载/缺失/长内容状态通过。本批首次功能及静态检查无失败。24张新状态与9张直接消费者开发基线纳入既有回归，原图/审批历史保留；截图发现手机风险代码碎行后仅调整风险/日期列百分比，18张受影响图重新生成，原首版33图留于before-layout-review，其余15有效图复用；最终33项独立视觉比较通过。未改交互/语义/字体/颜色/焦点规则，已通过功能/单测/类型/目标ESLint/72模块Token零例外证据复用；最终p0_catalog构建exit0，8616模块，主包1063.49KB/gzip329.21KB，原500KB提示保留。任务Vite17341及所属esbuild按PID/父PID/创建/命令核对停止，terminal exit1为主动停止，原Storybook17641/PID18044保留。development_complete/ready_for_user_review=true，user_verified/accepted/UI_deployed=false。体验http://127.0.0.1:17641/?path=/story/patterns-catalog-versions--reference：核对V4与目录记录104/基础记录103→键盘重新读取→手机横向滚动→查看Empty/FirstVersion/UnknownRisk/MissingFields/LongValues/Loading；RefreshFailure先点击重新读取版本，再显式重新读取恢复。样板全虚构无需账号、不请求实际API、刷新重置；实际页面需原管理账号/API，本轮仅GET隔离夹具验证，不证明真实批准历史/业务数据/后端或初始化写入。关联沿用目录记录ID与基础记录引用、当前账号/站点scope及唯一主档权威，无新写入。未读写data/、真实库/生产，不改冻结来源/LAN/Alpha，无commit/push/merge/deploy/migration或新Collect。证据storybook-import-review-20261005-01/catalog-versions-20261008/result.json；Skill frontend-design。


## 待归属来源核对（2026-10-08）

目录版本列表已获用户“体验通过，继续下一步”确认。

2026-10-08待归属来源核对本地开发完成：实际/catalog/unmatched与10种虚构Patterns/Catalog Unmatched Sources状态共享CatalogUnmatchedView，复用现有shadcn派生Button/LinkButton/EmptyState/Skeleton/StatusBadge/StatusMessage、Lucide与tokens，零新增依赖。影响数字、按币种金额、来源预览/报表类型/审核入口、已有商品候选分层；手机堆叠、长安全预览与截断提示、零值/无金额、多币种、加载、无依据/未来日期、后续空页及候选局部失败覆盖。目录记录ID不再误标为版本号；后续空页明确可返回上一页，不改页码或推断全部归属完成。原money函数、无依据/未来/pageCount判定、scope及稳定seller_sku_match/style_id、href、分页回调/禁用、候选权限原样；22份controller/API/types/导航/既有候选/全局CSS/DS基础与package/lock按本轮前快照字节一致。4项Story完整交互、桌面/手机2项新实际路由和2项原候选局部失败消费者全API拦截GET路径、原4项单测通过；46项有效manifest/三档axe（首轮16项有效+修正后30项）及45项独立视觉比较通过。新增30张与15张直接消费者开发基线纳入既有回归，旧15图、首版45图及审批历史保留；参考桌面/手机、长预览、无依据/局部失败截图经审阅。首次Story测试因旧服务已结束且pnpm启动中止未执行，直接复用运行时重启Storybook后4项通过；实际测试两轮各2失败分别为夹具缺catalog包装和按钮名称误匹配，修正测试后2项通过；axe发现定义列表说明节点结构无效，改为dd后受影响30项通过，首日志/图/trace保留。TypeScript/目标ESLint/73模块Token零例外通过；最终p0_catalog构建exit0、8617模块、主包1066.00KB/gzip329.87KB，500KB提示保留。仅定义列表语义及等效说明样式修正后复查目标单测/lint/build/axe/基线，其他未受影响功能/类型/token有效结果复用。体验http://127.0.0.1:17641/?path=/story/patterns-catalog-unmatched-sources--reference：键盘下一页→查看候选→返回→商品链接→返回→维护入口；另看MultiCurrency/LongPreview/NoEvidence/FutureRange/EmptyPage/PendingLoading/PendingFailure，失败显式重读，刷新重置。样板全虚构无需账号、不请求实际API；实际页面仍需原管理账号/API/有效发布事实和已初始化目录，本轮只验证隔离虚构GET路径，不证明真实来源/金额/归属或后端。任务Vite17341及所属esbuild按PID/父PID/创建时间/命令核对停止，terminal exit1为主动清理；Storybook17641/PID11288保留。development_complete/ready_for_user_review=true，user_verified/accepted/UI_deployed=false。未读写data/、真实库/生产，不改冻结来源/LAN/Alpha，无commit/push/merge/deploy/migration或新Collect。证据storybook-import-review-20261005-01/catalog-unmatched-20261008/result.json；Skill frontend-design。


## 批量维护总览（2026-10-08）

待归属来源核对已获用户“体验通过，继续下一步”确认。

2026-10-08批量维护总览本地开发完成：实际/catalog/maintenance与4种虚构Patterns/Catalog Maintenance Overview共享CatalogMaintenanceOverview，沿用现有shadcn派生LinkButton/StatusBadge、Lucide和tokens，无新增依赖。生效版本、目录记录ID与发布修订分开展示，首次来源发布/账号范围/退货快照/草稿批准前置和三步维护流程分层，新增查看已生效商品/批准记录导航；首个版本空商品不误判为未初始化，长编号与手机堆叠覆盖。原catalog/null判定、说明与初始化href保留；已生效不冒充新来源就绪，生成/快照/批准及权限仍由原controller决定。4项Story完整交互、桌面/手机2项实际App全API拦截GET路径、1项原定向单测、31项manifest/三档axe、30项独立视觉比较通过。实际核对初次加载→V4/记录104→准备不足禁生成→空商品与批准记录导航/返回→URL与刷新保留→显式刷新准备后启用→未初始化与刷新仍禁用，无写请求。12张新样板与18张直接消费者开发基线纳入既有回归；旧18图和首版12图保留，截图审阅后仅让Story采用实际catalog-stack间距，复用未受影响功能/类型/axe及18消费者图。TypeScript/目标ESLint/74模块Token零例外/p0_catalog构建exit0，8617模块、主包1068.73KB/gzip330.45KB，500KB提示保留；本轮功能及静态检查无失败。所有controllers/API/types/原Story/共享CSS/DS基础与package/lock按前快照字节一致。任务Vite17341及所属esbuild按PID/父PID/创建/命令核对停止，terminal exit1为主动清理；原Storybook17641/PID11288保留。development_complete/ready_for_user_review=true，user_verified/accepted/UI_deployed=false。体验http://127.0.0.1:17641/?path=/story/patterns-catalog-maintenance-overview--reference：核对V4与目录记录104→键盘打开已生效商品→返回→批准记录→返回/刷新；另看Uninitialized/FirstVersion/LongIdentifiers。样板全虚构无需账号、不请求真实API；实际页面需原管理账号/API/来源准备及已初始化目录，本轮不证明真实目录与前置数据，不确认来源、建立快照、生成候选或批准。未读写data/、真实库/生产，不改冻结来源/LAN/Alpha，无commit/push/merge/deploy/migration或新Collect。证据storybook-import-review-20261005-01/catalog-maintenance-overview-20261008/result.json；Skill frontend-design。


## 共享列设置（2026-10-08）

批量维护总览已获用户“体验通过，继续下一步”确认。

2026-10-08共享列设置本地开发完成：日期工作台与已发布明细复用 ColumnSettingsPanel，沿用 shadcn 派生 Button/Checkbox/SearchInput、Lucide 与 tokens。搜索清空、显示计数、拖动/键盘上下移、最后标识列说明、统计字段与重置操作统一；无匹配/无列/长列名/多列滚动状态齐备。展开聚焦搜索并滚入可见区域，Escape/关闭恢复原触发焦点；原 column_id 排序、最后标识列保护、统计字段规则、列宽与账号/站点/报表/namespace 本地偏好逻辑不变。六种 Patterns/Column Settings 与两个实际页面列设置样板共用真实布局 hook，无实际 API。8项Story完整路径、桌面/手机2项实际App全API拦截GET路径、原4项单测通过；核对读取失败恢复→搜索/显示/排序/统计与重置→表格同步→关闭焦点→刷新记忆与页面间namespace隔离。24项三档axe与manifest、24项最终独立视觉比较通过；新增24图纳入既有门禁，前版图及审批历史保留。TypeScript/目标ESLint/75模块Token零例外/p0_catalog构建通过，主包1072.20KB/gzip331.37KB，既有500KB提示仍在。首轮测试两处定位问题（空列表查询不存在checkbox、恢复按钮名称写错）和故事字段缺standard_field_name已修正，失败日志保留；截图审阅修正底部按钮布局与首屏外面板，复查直接受影响功能。原布局/偏好/列展示/两消费者View/全局表格CSS/package/lock共9文件与本轮前快照字节一致。Storybook17641/PID11288保留；本批Vite6812及所属esbuild26872按真实身份停止，terminal exit1为主动收尾。development_complete/ready_for_user_review=true，user_verified/accepted/UI_deployed=false；正式release_validation未推进。体验入口 http://127.0.0.1:17641/?path=/story/patterns-column-settings--reference；搜索sales→勾选/上下移动或拖到末尾→关闭再开/刷新；另看六种状态及两个页面ColumnSettings。全虚构无需账号；实际页面仍需原账号/API/列结构，本轮不证明真实业务数据或后端。仅本地，未读写data/、真实库/生产，不改冻结来源/LAN/Alpha，无安装、commit/push/merge/deploy/migration或Collect。证据 column-settings-20261008/result.json；Skill frontend-design。


## 共享分组表头（2026-10-08）

共享列设置已获用户“体验通过，继续下一步”确认。

2026-10-08共享分组表头本地开发完成：DataTableHeader接入局部CSS Module及现有Lucide/tokens，日期工作台和已发布明细直接复用。分组/列名改为全局中性表面，排序箭头、当前排序列高亮、统计标记与窄列提示、列边缘拖动/键盘焦点统一；冻结列层级保留，局部覆盖旧leading列的已有important规则。新增6种Patterns/Table Header（默认、升序、降序、退货、长列名、拆分分组），使用原列偏好hook和虚构数据；样板本地排序，实际页面仍服务端排序。7项有效Story交互、桌面/手机2项实际App全API拦截GET路径、原4项单测通过：读取失败恢复→排序升/降/清除→真实排序请求/URL与行顺序→刷新保留→键盘列宽与刷新记忆→横滚冻结；样板另核对鼠标拖动/活动提示。42项三档axe和manifest通过；18张新样板+78张直接消费者开发基线纳入既有回归，最终96项独立视觉比较通过；原78图/审批历史保留，其中39图变化、39图字节一致。TypeScript/目标ESLint/76模块Token零例外/p0_catalog构建通过；主包1073.30KB/gzip331.76KB，原500KB提示保留。首轮浏览器测试把固定布局表格最终分配宽度误当为持久列宽，改为核对原模型8px变化、实际渲染增宽与刷新保留后通过；Story未绑定方法lint修为等价回调，原失败日志/trace保留。原三态排序、键盘/指针完成/取消/卸载清理代码块及15项布局/偏好/表格消费者/controller/Story/CSS/package/lock文件与前快照字节一致。任务Vite9356与所属esbuild8736按PID/父PID/创建时间/命令核对停止，terminal exit1为主动收尾；Storybook17641/PID11288保留。development_complete/ready_for_user_review=true，user_verified/accepted/UI_deployed=false，未推进正式release_validation。体验 http://127.0.0.1:17641/?path=/story/patterns-table-header--reference：点击销售额三次→聚焦列边缘按左右键/拖动→刷新→手机横滚；另看Ascending/Descending/ReturnReport/LongHeaders/SplitGroups。全虚构无需账号、不请求真实API；实际页面需原账号/API/报表列结构，本轮不证明真实业务数据或后端。仅本地，未访问data/或真实库/生产，不改冻结来源/LAN/Alpha，无安装/commit/push/merge/deploy/migration/Collect。证据table-header-20261008/result.json；Skill frontend-design。

2026-10-08共享安全来源引用本地开发完成：SafeSourceRefView复用现有StatusBadge/Lucide及全局tokens，以局部CSS Module替换硬编码黄色徽标；预览、指纹摘要和截断/危险字符提示分层，长文本及手机宽度正常换行。保留原摘要后八位计算和结构字符替换判定、旧根class及完整标识权限/解码/清除流程，未新增自动揭示或复制动作。三个直接消费者（商品导入来源证据、商品主档详情、经营商品变体来源别名）源码及安全hook/原组件测试/夹具/package/lock共9文件与前快照字节一致。新增6种Patterns/Safe Source Reference（默认、长预览、截断、上游危险标记、结构字符、合并提示），全虚构无需账号、不请求实际API。6项Story完整路径与6项桌面/手机实际App全API拦截GET路径通过，包括预览/摘要、安全替换、展开/关闭/刷新、读取失败恢复及原揭示权限失败/复制/隐藏/修订清除；原2项安全组件测试、61项manifest/三档axe、TypeScript/目标ESLint/77模块Token零例外及p0_catalog构建通过。18张新样板与42张直接消费者开发基线接入既有回归，60项独立视觉比较通过；90张既有原图与审批历史保留，选中消费者33图变化、9图不变，另外48图未更新。桌面/手机长文本、来源权限失败、来源面板及两种商品详情截图已审阅。ESLint首次仅测试拦截回调无await，改为同步throw后定向复查通过；首失败日志保留。主包1074.22KB/gzip332.03KB，既有500KB提示保留。任务Vite5584及所属esbuild29200按PID/父PID/创建时间/命令核对停止，原终端exit1为主动收尾；Storybook17641/PID11288保留。development_complete/ready_for_user_review=true，user_verified/accepted/UI_deployed=false，正式发布状态不变。体验 http://127.0.0.1:17641/?path=/story/patterns-safe-source-reference--reference ，另看LongPreview/Truncated/Unsafe/StructuralCharacters/Combined；实际页面仍需原账号/API及初始化数据，本轮不证明真实业务数据或后端。仅本地，未访问data/、真实业务库或生产，不改冻结来源/LAN/Alpha，无安装/commit/push/merge/deploy/migration/Collect。证据source-reference-20261008/result.json；Skill frontend-design。

2026-10-08共享经营指标读数本地开发完成：MetricValueView沿用原组件、Lucide及全局tokens，独立局部CSS Module统一数字、无报表/分母为零的中性状态提示、零值说明和部分数据提示；非紧凑读数补充实际已发布/应有天数，缺报表时复用原覆盖说明，紧凑表格保留提示。总表、经营详情摘要和实际变体表直接复用。金额/六位比率/百分比及零/缺报表/分母为零原计算块换行归一后逐字一致；两个controller、三种消费者、原组件测试、两种虚构夹具、格式化/计算/类型/实际API测试/package/lock共15文件与前快照字节一致。旧ProductAnalytics仅移除一条已迁移的指标CSS，详情局部CSS仅将原直接子节点字号规则改为作用于读数的局部字号变量，保留24px摘要与13px紧凑表格层级及原业务/权限/稳定身份/URL/排序/刷新行为，无新增依赖。新增8种Patterns/Metric Value（默认、零值、无报表、零分母、部分数据、紧凑、百分比、长/负金额），全虚构无需账号、不请求实际API。10项有效Story完整路径（初轮10项通过；夹具source_completeness校准为合同indeterminate及部分零值覆盖天数完善后，受影响4项状态最终复查通过）与4项桌面/手机实际App全API拦截GET路径通过；覆盖两页入口、筛选/排序、URL与刷新保留、读取失败显式重试、图表/维度/变体过滤、权限/初始化/空/缺报表及零值状态。原2项组件单测、85项manifest/三档axe、TypeScript/目标ESLint/78模块Token零例外及p0_catalog构建通过。24张新样板+60张直接消费者开发基线接入既有回归，最终84项独立视觉比较通过；原60图和审批历史保留，33图变化、27图字节一致。桌面/手机读数、部分数据、最长支持金额与负金额、无报表详情及实际消费者截图已审阅。主包1075.52KB/gzip332.36KB，既有500KB提示保留。任务Vite8776及所属esbuild按PID/父PID/创建时间/命令核对停止，原终端exit1为主动收尾；Storybook17641/PID11288保留。development_complete/ready_for_user_review=true，user_verified/accepted/UI_deployed=false，正式发布状态不变。体验 http://127.0.0.1:17641/?path=/story/patterns-metric-value--reference ，另看ZeroValues/MissingReport/UndefinedDenominator/Partial/Compact/Percentage/LongValues；样板使用虚构数值，实际页面仍需原账号/API/已初始化商品与报表，本轮不证明真实数据或后端。仅本地，未访问data/、真实业务库或生产，不改冻结来源/LAN/Alpha，无安装/commit/push/merge/deploy/migration/Collect。证据metric-value-20261008/result.json；Skill frontend-design。


2026-10-08趋势每日明细矩阵本地开发完成：TrendPointMatrix沿用现有组件、StatusBadge/EmptyState及全局tokens，局部CSS统一表头/日期冻结、等宽数字右对齐、长金额单行、缺报/零分母/部分数据与完整性未定提示，窄屏在一个可键盘聚焦的区域双轴滚动。实际商品详情及原折线图样板直接复用；原valueText、日期并集排序和point映射保持，不补零/插值/重算比率。review-23图表/故事、SeriesSelector、详情controller/view/虚构夹具、原矩阵单测、指标组件/格式化与package/lock共13文件字节一致，零新增依赖。新增Reference/MissingAndPartial/ConversionRatio/Wide/LongValues/Empty六状态，无需账号且不请求实际API。9项有效Story功能（长金额修正后受影响5项最终复查）与2项桌面/手机实际App全API拦截GET路径通过，包括指标/系列切换、日期排序、刷新/URL保留、失败恢复、只读角色及键盘双轴冻结。原1项组件测试、76项有效manifest/三档axe（初76通过，CSS修正后受影响60复查通过，其余16复用）、TypeScript/目标ESLint/79模块Token零例外/p0_catalog最终构建通过。18张矩阵+27张原图表首次基线+30张详情接入既有回归，75项最终独立视觉比较通过；原30图、初版75图和审批历史保留。桌面/手机默认、缺失、宽表、长金额、单日图表与详情截图已审阅。主包1076.87KB/gzip332.82KB，既有500KB提示保留。首轮样板括号语法错误造成Storybook虚拟模块404，初失败/日志/trace保留，修正后恢复同端口；原PID11288已核对归属停止，现Storybook17641/PID24712保留。App首轮测试将默认颜色维度误写为合计，按原controller和虚构输入修正断言，业务实现未改。任务Vite17544及esbuild13164按PID/父PID/创建时间/命令核对停止，原终端exit1为主动收尾。development_complete/ready_for_user_review=true，user_verified/accepted/UI_deployed=false；经营指标前批用户确认保留，正式发布状态不变。体验 http://127.0.0.1:17641/?path=/story/patterns-trend-point-matrix--reference ，切换明细指标、取消/恢复系列，再看缺失/零分母/31天8系列滚动及长金额；实际页面仍需原账号/API/初始化报表，本轮不证明真实经营数据或后端。仅本地，未访问data/、真实业务库或生产，不改冻结来源/LAN/Alpha，无安装/commit/push/merge/deploy/migration/Collect。证据trend-matrix-20261008/result.json；Skill frontend-design。


2026-10-08经营分析覆盖收尾本地开发完成：用户在每日明细矩阵入口回复“批准”，该批12项摘要核对一致后记录user_verified=true；本轮核对商品经营余量，发现覆盖与六桶对账缺独立样板、已有指标说明5故事未进视觉/a11y门禁，SeriesSelector已有图表/矩阵覆盖不重复新建。CoverageReconciliation沿用现有组件、StatusBadge/LinkButton和tokens，经营/退货两卡分层展示天数与原六位比率，身份状态中文标识，六桶原数值右对齐、桶名冻结与可键盘横向核对；零值、不可计算和未归属提示保留。实际产品总表直接共享。截图审阅发现其旧父容器CSS把新覆盖卡片挤成横排，仅删除ProductLedgerView.module.css三条旧覆盖规则，其他字节保持；修正后桌面/手机实际路径2项通过，并新增卡片标题/比率纵向几何断言。LedgerMetricHelp沿用原8项定义/范围和Dialog控制器；局部CSS改用全局tokens、继承现有Radix/shadcn Dialog动效，保留关闭/外部关闭/Escape/焦点返回与手机内部滚动。原totalCell/BucketRow计算、未归属显示条件和完整href表达式保持；两controller/view/原总表故事与夹具、指标说明组件、格式化/原单测/原Story功能测试/package/lock共11文件字节一致，零新增依赖。新增覆盖Reference/Partial/NoReports/ZeroValues/Unmatched/LongValues六故事，复用既有指标说明五故事，均虚构无需账号、不请求实际API。8项有效Story完整功能（初6通过/2因重开弹窗后立即鼠标点击早于Radix焦点和外部事件就绪而失败；等待实际弹窗可见/焦点就绪后只复查2项通过，不改Dialog源码）、2项桌面/手机实际App全API拦截GET路径通过：初始化、筛选/分页/URL、失败显式重试、刷新保留、原六桶原始值、两事实口径与说明、键盘说明八项切换/关闭/外部关闭/焦点返回，长金额/缺报/零值/部分状态与未归属链接/返回范围。原1项组件单测、64项有效manifest/三档axe（46项未受影响结果复用+18项消费者修正后复查）、TypeScript/目标ESLint/81模块Token零例外及p0_catalog构建通过。18张新覆盖+15张既有说明首次开发基线+30张产品总表消费者纳入原视觉回归，消费者修正后最终63项独立比较通过；原30图、消费者修正前首63图、审批历史与初功能失败日志/图/trace保留。桌面/手机默认、未归属、长金额、零/缺报、说明弹层与总表截图已审阅。主包1075.38KB/gzip332.60KB，CSS491.22KB，既有500KB提示保留。两轮任务Vite12636/5908及esbuild23080/21520均按PID/父PID/创建时间/命令停止，两个原终端exit1为主动收尾；第二轮立即停止检查早于进程退出，后续真实进程快照确认已不存在，未重复停止；Storybook17641/PID24712保留。development_complete/ready_for_user_review=true，user_verified/accepted/UI_deployed=false；每日明细与指标前批确认保留，正式发布状态不变。体验 http://127.0.0.1:17641/?path=/story/patterns-coverage-reconciliation--reference 与 http://127.0.0.1:17641/?path=/story/patterns-product-ledger-metric-help--all-metrics ：核对各报表覆盖→六桶→手机滚动→未归属href；点击八项说明→Escape/关闭/焦点返回。实际产品总表仍需原账号/API及已初始化报表，本轮不证明真实数据/后端；覆盖核对仅为商品经营相关组件，不宣称全站缺口审计或全站串联完成，早期批次体验标记未擅自归一。仅本地，未访问data/、真实库或生产，不改冻结来源/LAN/Alpha，无安装/commit/push/merge/deploy/migration/Collect。证据analytics-coverage-20261008/result.json；Skill frontend-design。
