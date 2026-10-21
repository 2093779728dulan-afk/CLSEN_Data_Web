# React Bits GlideSelect

Source: [official JS-CSS registry](https://reactbits.dev/r/GlideSelect-JS-CSS.json), fetched 2026-10-06.
Documentation: <https://reactbits.dev/micro/glide-select>.
Original registry SHA-256: `6c719730ecd209f86074a0756324f52f0c4b5fe2eba18e024892e8a88f7a12c7`.
The exact fetched registry is preserved in the task evidence directory `glide-select-20261006`.

`GlideSelect.jsx` and `GlideSelect.css` originate from that registry. The component remains JavaScript with plain, `glide-select`-scoped CSS; `GlideSelect.d.ts` describes the verified official API for this TypeScript project. `GlideSelectField` applies the catalog configuration and disables tags because the original filter options have no auxiliary descriptions.

Dependencies are pinned within the registry's ranges: `@hugeicons/react` 1.1.10 and `@hugeicons/core-free-icons` 4.3.5. React remains the existing 19.1.1. The package manifest and pnpm lock record the dependencies. Local development uses an isolated UI dependency overlay so the frozen release source's shared dependencies remain unchanged; a fresh checkout uses the normal pnpm install flow.

## Current project theme (2026-10-06 refinement)

Following user feedback that the original dark palette did not match the project, `GlideSelectField` now passes shared CSS tokens: accent `--color-primary`, surface `--color-surface`, highlight `--color-info-bg`, and text `--color-text`. The trigger/menu border and shadow use existing tokens in the wrapper CSS Module; forced-colors borders retain system colors. Both the control and body portal receive the same configuration. The original registry defaults remain preserved in the vendor source. Durations, controlled callbacks, keyboard behavior and rememberPosition semantics are unchanged.

## Local changes to the upstream source

- Portal the menu to `document.body` because the real catalog workspace clips its children; measure against the trigger, clamp horizontally, flip vertically, and reposition on resize/scroll. Outside pointer/focus handling includes the portal.
- Add `id`, `aria-describedby`, and `aria-invalid` to connect the existing `FormField`; keep the official `ariaLabel`, combobox/listbox roles and keyboard navigation. A virtual click without pointer events also activates the trigger or an option.
- Restore visible keyboard focus and system colors; remove transitions under reduced motion. Closed menus expose no active descendant and closing menus are hidden from accessibility APIs.
- Separate the menu pop from the upstream pill's `instant` flag. The original open path set every menu pop to `0ms`; the adapted menu uses the supplied 180ms duration.
- Calculate pointer row selection from the list's actual top. The original extra 4px padding subtraction selected the previous row at a row's upper edge.

`rememberPosition` retains the official meaning: the highlight stays on the last hovered row when the pointer leaves, and glides from there on re-entry. Closing and reopening starts at the current selected option. Hover does not commit a value; only a pick invokes `onChange(value, option)`.

License: **MIT + Commons Clause License Condition v1.0**, copyright 2026 David Haz. The full upstream notice is retained in [LICENSE.react-bits.md](./LICENSE.react-bits.md). It permits use and modification as part of an application, website or product, with restrictions on selling, sublicensing or redistributing the components themselves. The Hugeicons packages declare MIT licenses.


## ClickSpark adapter

The project public `../ClickSpark.tsx` is a TypeScript adaptation of the official JS-CSS Canvas component (https://reactbits.dev/r/ClickSpark-JS-CSS.json). Original registry/JSX are preserved in `click-spark-pages-20261006` evidence. Dependencies: none. Source hash and differences are listed in `../THIRD_PARTY_NOTICES.md`; the same retained upstream license applies. It runs within a shared catalog boundary rather than installing a perpetual Canvas/RAF loop per Button.
