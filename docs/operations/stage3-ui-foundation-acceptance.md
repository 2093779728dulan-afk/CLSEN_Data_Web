# Stage 3 UI foundation acceptance

This reference defines the evidence required to accept Stage 3. It does not authorize deployment, merge, push, or a full release Collect.

## Product boundary

- Desktop PC is the primary product surface and receives the main visual and interaction refinement.
- The 768px and 390px viewports protect baseline usability: core content is readable, key actions remain operable, and overflow does not block the workflow.
- A 390px reflow check is narrower than the 640 CSS-pixel viewport produced by viewing a 1280px desktop at 200% browser zoom. It is acceptable automated reflow evidence, but it does not replace a requested manual browser-zoom review.
- Stage 3 establishes shared UI foundations and the administrator Worker page as the first consumer. Migrating every business page belongs to Stage 4.

## Automated gates

Run these commands from `frontend` unless the row says otherwise.

| Evidence | Command | Pass condition |
| --- | --- | --- |
| Token policy | `pnpm test:tokens` | Every CSS Module uses semantic colors and motion durations, or an exact exception records a reason and approver. |
| Shared component contracts | Focused Vitest files for the changed components | Accessible names, states, keyboard behavior, and focus contracts pass without skipped tests. |
| Storybook static output | `pnpm storybook:build` | Static build completes. |
| Accessibility | `pnpm test:a11y` | No serious or critical axe findings in the manifest stories and responsive subset. |
| Visual regression | `pnpm test:visual` | All approved 1280/768/390 screenshots match; CI never updates snapshots. |
| Frontend unified gate | From repository root: `pwsh -File scripts/run-ci-profile.ps1 -Profile frontend-full` | The complete frontend profile exits zero. |
| Backend compatibility | From repository root: `pwsh -File scripts/run-ci-profile.ps1 -Profile ubuntu-full` and `pwsh -File scripts/run-ci-profile.ps1 -Profile windows-smoke` | Existing backend and cross-platform contract profiles exit zero on the final candidate. |

Database matrices, performance repetitions, backup/restore, and deployment rehearsal remain release-validation work when Stage 3 contains no database or deployment change. Do not start a full Collect merely to finish a UI development iteration.

## Bundle gate

Build once with `VITE_PRODUCT_ANALYTICS_SOURCE=legacy_parser` and once with `VITE_PRODUCT_ANALYTICS_SOURCE=p0_catalog`. Sum emitted `.js` and `.css` bytes after each clean build and compare them with the current approved Stage 0 record:

- `frontend-bundle-legacy_parser`: at most `804210` bytes.
- `frontend-bundle-p0_catalog`: at most `838968` bytes.

The repeated Stage 0 calibration sampler is not required for this deterministic artifact-size comparison. A changed runtime, dependency environment, build parameter, or approved baseline requires the Stage 0 versioning procedure instead of silently changing these ceilings.

## Human review

The project owner verifies the desktop Storybook and administrator Worker page. The minimum review covers:

1. Keyboard open, focus movement, selection, close, and focus return for composite controls.
2. Visible focus, readable Chinese text, error and disabled states, and reduced-motion behavior.
3. The administrator Worker and queue layout at the primary PC width.
4. Basic operability at 768px and 390px without requiring desktop-equivalent polish.

Automated browser actions, screenshots, or an earlier approval do not replace the user's explicit experience result for the reviewed version.

## Completion record

An acceptance record must identify the final commit SHA and include:

- Token policy result and exception count.
- Shared component inventory and Storybook build result.
- Accessibility and visual result counts.
- Baseline approval metadata and visual review outcome.
- Both bundle byte totals, ceilings, and remaining headroom.
- Administrator page before/after evidence and the user experience result.
- Frontend, Ubuntu backend, and Windows smoke profile results.

Use separate status fields: `development_complete`, `ready_for_user_review` or `user_verified`, and `release_validation`. Mark Stage 3 `accepted` only when every required item above is bound to the final candidate and the user has explicitly approved the experience.
