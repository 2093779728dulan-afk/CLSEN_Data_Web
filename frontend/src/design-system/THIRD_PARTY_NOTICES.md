# Third-party component sources

Spinner.tsx is adapted from shadcn/ui Spinner. Button integrates that Spinner using a project-specific stable-label adapter; Dialog CSS adapts shadcn/ui's data-state fade/zoom pattern to CLSEN CSS Modules and tokens. No Tailwind, cn, cva, radix-ui umbrella package or animation dependency is added.

Upstream repository: https://github.com/shadcn-ui/ui
Sources read on 2026-10-06:
- apps/v4/registry/new-york-v4/ui/input-group.tsx, Git blob a457945603c5e2fd52190135520fb67ccb6af388
- apps/v4/registry/new-york-v4/ui/spinner.tsx, Git blob 3e0fd0a1d046107cb97bb3028561485c08be65c2
- apps/v4/registry/new-york-v4/ui/button.tsx, Git blob e3345d985d14c33e3cb9d8c45cf973807326c944
- apps/v4/registry/new-york-v4/ui/dialog.tsx, Git blob ccadf4a85bf6398d52314b112600f796fc97db97
- apps/v4/registry/new-york-v4/ui/input.tsx, Git blob ddb9b315e34245addded54b1848bb32c80c418cc
- apps/v4/registry/new-york-v4/ui/select.tsx, Git blob 8058e266346ddf79b0b156a7c5d07e716d5792ee
- apps/v4/registry/new-york-v4/ui/checkbox.tsx, Git blob 9aaa1baace43e42aba6ee7c3b04adb8ff7e99ea2
- apps/v4/registry/new-york-v4/ui/badge.tsx, Git blob 1a94cc539326e26227271a0b3599be99e0e55fb6
- apps/v4/registry/new-york-v4/ui/tooltip.tsx, Git blob c8c47cb146e6167c68f74f8a2f2f0c7c2d06ec72
- apps/v4/registry/new-york-v4/ui/pagination.tsx, Git blob 0e5980373355daf65200d8070ed99ffb839fbf8d

Changes: localized status text; existing Lucide LoaderCircle and CSS motion tokens; no-motion spinner; optional stable loading labels; project-owned Radix Dialog with data-state fade/zoom entrance and exit. Existing focus and keyboard handling remain in Radix.

Small-component adaptation: Input/Select share shadcn's minimum-width, placeholder, selection, focus and invalid-state treatment. Select keeps its native arrow, popup, multiple/size behavior and ref API rather than adopting the upstream Radix Select. Checkbox adapts the bordered square and Check indicator onto a native input, adds a mixed-state Minus and restores native rendering in forced colors. Badge uses lighter text and compact icons, permitting long status labels to wrap. Tooltip adapts the Radix-origin fade/zoom pattern with reduced-motion support and viewport width constraints. Pagination adapts the current-page outline and previous/next arrangement to the existing callback API; it does not implement new page links or ellipsis logic. The ReviewControls story composes these project-owned components using fictional records only.

SearchInput additionally adapts shadcn InputGroup's leading icon, shared border/focus treatment and inline clear button. It retains the native input label, description, invalid state and ref, and returns focus after clearing. FilterToolbar composes that adapter with existing Checkbox/Button and removable conditions; no cva, cn, Tailwind or new dependency is imported.

MIT License


Copyright (c) 2023 shadcn

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all
copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
SOFTWARE.


## Motion shared route underline (2026-10-06)

RouteNavigation adapts the official Motion shared-layout example `isSelected && <motion.div layoutId="underline" />`: https://motion.dev/docs/react-layout-animations. Motion 14.0.0 (MIT) handles shared geometry; the project uses an aria-hidden motion.span inside React Router NavLink, an instance-scoped LayoutGroup, native route-link focus/activation, horizontal layoutScroll and reduced motion. Duration comes from the existing motion-content-enter token. The project CSS Module adapts existing shared Tabs styling and semantic tokens; no third-party theme or page renderer is copied.

The upstream MIT notice is retained in [LICENSE.motion.md](./LICENSE.motion.md). The no-animation-dependency statements above apply to their earlier component batches; this navigation batch explicitly adds Motion and its pinned lock dependencies in an isolated UI runtime.


PageTransition (2026-10-06) uses the same existing Motion 14.0.0 MIT dependency and the official initial/animate entrance pattern: https://motion.dev/docs/react-animation. Local changes are CSS-token timing/distance, reduced-motion overrides and the catalog's original pathname key; no AnimatePresence exit retention, synthetic load completion, new router or dependency is introduced. LICENSE.motion.md continues to carry the upstream notice.


## React Bits ClickSpark (2026-10-06)

Official source: https://reactbits.dev/r/ClickSpark-JS-CSS.json, registry SHA-256 `c0381de329a477d97b98c42468739e649de91ac07aecc0be30bb890b5ef42707`.
Documentation: https://reactbits.dev/c/animations/click-spark. No registry dependencies.
`ClickSpark.tsx` ports its Canvas radial-stroke / ease-out algorithm and defaults (8 particles, 400ms) to the existing TypeScript stack. Local changes: four semantic palette tokens, shorter 7px strokes / 18px radius, native action filtering and keyboard centers, pointer-transparent viewport portal, DPR scaling, reduced-motion/forced-colors behavior, bounded recent bursts, animation only while particles exist and cleanup. The original exact JSX is retained in task evidence `click-spark-pages-20261006/ClickSpark.original.jsx`; it is not claimed as an unchanged upstream file.
React Bits' retained MIT + Commons Clause notice is [LICENSE.react-bits.md](./react-bits/LICENSE.react-bits.md). It permits integration and modification within an application under its conditions; this task does not distribute components as a standalone product. Catalog page layouts reuse the existing project-owned shadcn-derived Button, Input, Table, Skeleton, EmptyState and feedback components; no second theme or component framework is installed.
