# 高频共享 UI 组件设计

## 目标与范围

在现有 `frontend/src/design-system` 受控入口中补齐 Checkbox、Radio、Tooltip、Tabs、Menu、Toast、Skeleton、EmptyState、ErrorState 和基础 Table。组件延续蓝白语义 Token、CSS Modules、长中文和键盘可用原则，不改变任何业务流程、权限、校验规则或数据接口。

## 技术边界

- Checkbox 与 Radio 使用原生 input，项目组件负责标签、说明、错误和视觉状态。
- Tooltip、Tabs 和 Menu 使用按需锁定的 Radix 原语，项目 API 不暴露 Radix props。
- Toast 使用 Radix Toast 的视口、焦点和关闭基础，项目 API 只接受状态、标题、正文、操作和持续时间。
- Skeleton、EmptyState、ErrorState 和 Table 使用 React 与 CSS Modules，不增加第三方依赖。
- 所有公共组件只从 `design-system/index.ts` 导出；应用代码不得直接导入新增 Radix 包。

## 公共组件契约

### 表单与选择

`Checkbox` 和 `Radio` 接受原生 input 属性以及必填的 `label`，可选 `description`。Radio 由调用者通过相同 `name` 组成原生单选组。禁用、选中、焦点和错误状态不依赖颜色作为唯一提示。

### 复合导航

`Tooltip` 接受 `content`、`children` 和可选 `side`，触发器必须是可聚焦元素。`Tabs` 接受稳定的项目项数组、当前值和变更回调，并呈现关联 tabpanel。`Menu` 接受触发按钮名称和项目数组；项目支持普通、禁用与危险语义，键盘移动、Escape 关闭和焦点返回由 Radix 提供。

### 反馈

`ToastProvider` 在应用或故事边界提供统一 viewport；`Toast` 接受 `kind`、`title`、可选正文、操作和关闭回调。成功、警告、错误和信息均有文字及图标。Skeleton 为纯展示占位并对辅助技术隐藏；真实载入容器负责 `aria-busy`。

### 空、错与表格

`EmptyState` 提供标题、说明和可选操作；`ErrorState` 额外使用 alert 语义并支持明确的重试操作。基础 `Table` 只提供带标题、说明、横向滚动和语义 table 的结构，不封装排序、分页或业务列模型。

## Storybook 与验证

Storybook 为全部组件提供正常、禁用、加载、错误、长中文及窄屏适用状态。每个交互组件补定向 Vitest/Testing Library 测试，覆盖原生名称或 Radix 键盘/关闭/焦点契约；展示组件只测试关键语义，不增加快照测试。

开发验证分为两组：表单与导航、反馈与数据。每组只运行相关测试和定向 ESLint；全部实现完成后运行一次 TypeScript、一次 Storybook 静态构建和 `git diff --check`。本批不运行全前端测试、Playwright 全回归、正式 `test:a11y`、视觉基线或 Collect。

## 非目标

- 不在本批迁移业务页面或替换既有页面内组件。
- 不实现 Drawer、复杂数据网格、列调整、虚拟滚动或 Toast 队列持久化。
- 不新增 Motion 或 ECharts。
- Storybook a11y 面板不等同于 Stage 3 正式无障碍门禁。
