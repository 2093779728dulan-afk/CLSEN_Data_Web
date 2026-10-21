# Shared UI boundary

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
- Structure: `PageHeader`, `Dialog`, `EmptyState`, `ErrorState`, `Skeleton`, `Table`.
- Forms and navigation: `FormField`, `Input`, `Select`, `Checkbox`, `Radio`, `Tooltip`, `Tabs`, `Menu`, `Pagination`.
- Feedback: `ToastProvider`, `Toast`.

The published data table is the first consumer of the shared form and pagination controls. Its horizontal table scroll remains independent from the pagination controls.

## Storybook workspace

Run `pnpm storybook` for the local component workspace and `pnpm storybook:build` for its static build. Stories cover the current public components across primary, disabled, loading, long-Chinese, validation, dialog, and pagination states.

`pnpm test:a11y` scans every design-system story at 1280px and the responsive subset at 768px and 390px. Serious or critical WCAG findings fail the command. `pnpm test:visual` compares the approved screenshots at all three widths. Both commands use Playwright Chromium, reduced motion, `zh-CN`, `Asia/Shanghai`, device scale 1, and the bundled `Noto Sans SC Variable` font.

Product experience is desktop-first. PC layouts receive the primary interaction and visual-polish effort; the 768px and 390px checks protect baseline usability only: core content remains readable, key actions remain operable, and overflow does not block the workflow. Tablet and mobile do not require desktop-equivalent refinement unless a later product requirement explicitly raises their priority.

Visual differences are never accepted in CI. To create or update baselines after reviewing the rendered stories, set `VISUAL_BASELINE_APPROVED_BY` and a meaningful `VISUAL_BASELINE_REASON`, then run `pnpm test:visual:update`. The guarded command records the reviewer, reason, font, Playwright version, and timestamp beside the screenshots. Direct or CI snapshot updates are rejected.

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
