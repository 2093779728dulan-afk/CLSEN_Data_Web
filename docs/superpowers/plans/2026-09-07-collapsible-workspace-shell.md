# Collapsible Workspace Shell Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a compact top bar, a user-controlled persistent desktop sidebar, and a clearer account connection area without changing routing, permissions, sessions, or data APIs.

**Architecture:** Keep shell state local to `AppShell`, initialize it from one namespaced `localStorage` key, and expose the state through an `app-shell--sidebar-collapsed` modifier plus accessible button attributes. CSS owns expanded, collapsed, and existing mobile layouts; application routes and server calls remain unchanged.

**Tech Stack:** React 19, React Router, TypeScript, Lucide React, CSS, Vitest, Testing Library

## Global Constraints

- Desktop widths are exactly 238px expanded and 72px collapsed.
- Persist the preference in browser local storage; default to expanded when storage is unavailable or invalid.
- At 860px and below, keep the existing horizontal navigation and ignore desktop sidebar widths.
- Do not change routes, permissions, logout semantics, site configuration, or business-data APIs.
- Preserve visible keyboard focus and existing reduced-motion behavior.
- Work inline; do not use subagents, run full frontend regression, or start Collect.
- Do not commit implementation until the user completes the experience review.

---

### Task 1: Accessible persistent sidebar behavior

**Files:**
- Modify: `frontend/src/app/App.tsx`
- Test: `frontend/src/app/App.test.tsx`

**Interfaces:**
- Consumes: browser `localStorage`, existing `AppShell` props, existing `NavLink` routes.
- Produces: `SIDEBAR_COLLAPSED_KEY`, a boolean `sidebarCollapsed` state, `app-shell--sidebar-collapsed`, and a button named `收起侧栏` or `展开侧栏` with `aria-expanded`.

- [x] **Step 1: Write the failing interaction test**

```tsx
it("collapses the desktop sidebar and restores the saved preference", async () => {
  const first = renderApp();
  const collapse = await screen.findByRole("button", { name: "收起侧栏" });
  fireEvent.click(collapse);
  expect(screen.getByRole("button", { name: "展开侧栏" })).toHaveAttribute("aria-expanded", "false");
  expect(document.querySelector(".app-shell")).toHaveClass("app-shell--sidebar-collapsed");
  first.unmount();
  renderApp();
  expect(await screen.findByRole("button", { name: "展开侧栏" })).toBeVisible();
});
```

- [x] **Step 2: Run the exact test and confirm RED**

Run: `pnpm test --run src/app/App.test.tsx -t "collapses the desktop sidebar"`

Expected: FAIL because the `收起侧栏` button does not exist.

- [x] **Step 3: Implement local shell state and semantic controls**

Add a guarded initializer and writer around the key `clsen.workspace.sidebar-collapsed`. Render a Lucide panel icon button in the brand area, apply the shell modifier, keep full accessible names on links, and add titles for collapsed navigation discovery. Storage exceptions must not block toggling.

- [x] **Step 4: Run the exact test and confirm GREEN**

Run: `pnpm test --run src/app/App.test.tsx -t "collapses the desktop sidebar"`

Expected: PASS.

### Task 2: Shell visual hierarchy and bounded verification

**Files:**
- Modify: `frontend/src/styles.css`
- Verify: `frontend/src/app/App.tsx`
- Verify: `frontend/src/app/App.test.tsx`

**Interfaces:**
- Consumes: `.app-shell--sidebar-collapsed`, `.sidebar`, `.brand`, `.primary-nav`, `.sidebar__boundary`, `.connection-state`, and `.topbar`.
- Produces: 238px/72px shell tracks, compact top-bar context, centered collapsed navigation marks, and a two-line account identity block.

- [x] **Step 1: Implement the approved visual states**

Use CSS grid-track transitions for the desktop shell, an icon-only collapsed brand and navigation rail, a compact 58px top bar, and an account avatar/status/action layout. Hide supporting copy only in the collapsed modifier; keep it available to assistive technology through link and button names.

- [x] **Step 2: Protect the existing mobile layout**

Inside `@media (max-width: 860px)`, force the shell to `display: block`, hide the desktop toggle, and neutralize the collapsed modifier so the existing horizontal navigation remains unchanged.

- [x] **Step 3: Run minimum sufficient verification**

Run:

```powershell
pnpm test --run src/app/App.test.tsx -t "sidebar|退出"
pnpm exec eslint src/app/App.tsx src/app/App.test.tsx --max-warnings 0
pnpm typecheck
git diff --check
```

Expected: targeted tests, ESLint, TypeScript, and diff check all pass.

- [x] **Step 4: Prepare user experience review**

Open `http://127.0.0.1:5710/?month=2026-09`, verify expanded and collapsed desktop states, confirm navigation and logout remain usable, check the developer log for errors, and leave the sidebar expanded for the user. Mark the implementation `ready_for_user_review`; defer the implementation commit until the user explicitly confirms the experience.
