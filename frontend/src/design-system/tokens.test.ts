import { readFileSync } from "node:fs";
import { resolve } from "node:path";

import { expect, it } from "vitest";

it("exposes the approved semantic color tokens", () => {
  const css = readFileSync(resolve("src/design-system/tokens.css"), "utf8");

  expect(css).toContain("--color-page: var(--color-workspace-background)");
  expect(css).toContain("--color-workspace-background: #FAFBFC");
  expect(css).toContain("--color-primary: #1769AA");
  expect(css).toContain("--color-danger: #B33A3A");
  expect(css).toContain("--motion-duration-fast: 120ms");
  expect(css).toContain("--motion-duration-enter: 180ms");
  expect(css).toContain("--motion-duration-loop: 1.4s");
  expect(css).toContain("--chart-series-1: #1769AA");
  expect(css).toContain("--shadow-raised:");
  expect(css).not.toMatch(/linear-gradient|backdrop-filter|text-shadow/);
});
