import { expect, test } from "@playwright/test";
import { detailFixture } from "../../src/features/products/ProductDetailAnalysisView.fixtures";
import { parseProductDetailSearch } from "../../src/features/products/productDetailState";

for (const width of [1280, 390]) test(`actual detail async metrics, URL, color recovery and back at ${width}px`, async ({ page }) => {
  await page.setViewportSize({ width, height: 900 });
  const state = { hold: false, fail: false, colorFail: false }; let release: (() => void) | undefined;
  const calls: URL[] = []; const unexpected: string[] = []; const errors: string[] = [];
  page.on("pageerror", error => errors.push(error.message));
  await page.route(url => url.pathname.startsWith("/api/"), async route => {
    const request = route.request(); const url = new URL(request.url()); const path = url.pathname;
    if (request.method() !== "GET") { unexpected.push(`${request.method()} ${path}`); return route.fulfill({ status: 405 }); }
    if (path === "/api/auth/me") return route.fulfill({ json: { id: 88, username: "demo-viewer", display_name: "示例查看人员", roles: ["viewer"] } });
    if (path === "/api/data-calendar/site-context") return route.fulfill({ json: { site_id: 1, site_code: "US", display_name: "示例美国站点", site_config_version_id: 2, source_timezone: "America/Los_Angeles", reporting_timezone: "America/Los_Angeles", currency_code: "USD" } });
    if (path === "/api/dashboard/styles/501/card") {
      calls.push(url);
      if (state.hold) await new Promise<void>(resolve => { release = resolve; });
      if (state.fail || state.colorFail && url.searchParams.get("dimension") === "color") return route.fulfill({ status: 503, json: { error: { code: "synthetic_failure", message: "示例读取失败" } } });
      if (url.searchParams.get("series") === "unknown-series") return route.fulfill({ status: 422, json: { error: { code: "analytics_series_invalid", message: "示例系列已失效" } } });
      const data = detailFixture(parseProductDetailSearch(url.searchParams, "2026-08-24"), "read-only");
      return route.fulfill({ json: data });
    }
    unexpected.push(`${request.method()} ${path}`); return route.fulfill({ status: 500, json: {} });
  });
  await page.goto("/products/501?from=2026-08-22&to=2026-08-24");
  const heading = page.getByRole("heading", { name: "标准轻量夹克", exact: true }); await expect(heading).toBeVisible();
  const matrix = page.getByRole("region", { name: "趋势每日点矩阵", exact: true });
  await expect(matrix.locator("tbody time")).toHaveText(["2026-08-22", "2026-08-23", "2026-08-24"]);
  await expect(matrix.locator("tbody tr").first().locator("td")).toHaveText(["2", "4"]);
  await expect(page.getByRole("link", { name: "核对待归属来源", exact: true })).toHaveCount(0);
  const aliasSummary = page.locator("summary").filter({ hasText: /个来源别名/ }).first();
  await aliasSummary.click();
  const alias = aliasSummary.locator("..").locator(".safe-source-ref").first();
  await expect(alias).toBeVisible();
  await expect(alias.getByLabel("来源摘要后八位", { exact: true })).toHaveText(/[a-f0-9]{8}/);
  await aliasSummary.click(); await expect(alias).toBeHidden();
  const chart = page.getByRole("img", { name: /产品每日趋势.*销量/ }); await chart.evaluate(element => element.setAttribute("data-before", "true"));
  state.hold = true; await page.getByRole("radio", { name: "销售额", exact: true }).click(); await expect(page).toHaveURL(/metric=sales/); await expect(chart).toHaveAttribute("data-before", "true"); await expect(page.locator("[inert]")).toHaveCount(1);
  state.hold = false; release?.(); await expect(page.getByRole("img", { name: /产品每日趋势.*销售额/ })).toHaveAttribute("data-before", "true");
  await expect(matrix.locator("tbody tr").first().locator("td")).toHaveText(["40.00", "80.00"]);
  await page.getByRole("radio", { name: "尺码", exact: true }).click(); await expect(page).toHaveURL(/dimension=size&color_key=red-key/);
  await page.getByRole("radio", { name: "蓝色", exact: true }).click(); await expect(page).toHaveURL(/color_key=blue-key/);
  await page.getByRole("radio", { name: "报表日期", exact: true }).click(); await expect(page).toHaveURL(/return_basis=report_date/);
  await page.reload(); await expect(heading).toBeVisible();
  await expect(matrix.getByRole("columnheader", { name: "M", exact: true })).toBeVisible();
  await expect(matrix.locator("tbody tr").first().locator("td")).toHaveText(["80.00"]);
  await aliasSummary.click(); await expect(alias).toBeVisible(); await expect(page.getByRole("radio", { name: "蓝色", exact: true })).toBeChecked();
  expect(calls.some(url => url.searchParams.get("dimension") === "color" && url.searchParams.get("catalog_version") === "7")).toBe(true);
  state.fail = true; await page.getByRole("radio", { name: "会话", exact: true }).click(); await expect(page.getByRole("alert")).toContainText("产品详情读取失败"); await expect(heading).toHaveCount(0);
  state.fail = false; await page.getByRole("button", { name: "按原条件重试", exact: true }).click(); await expect(page.getByRole("img", { name: /产品每日趋势.*会话/ })).toBeVisible();
  state.colorFail = true; await page.reload(); await expect(page.getByText("颜色选项读取失败", { exact: true })).toBeVisible();
  state.colorFail = false; await page.getByRole("button", { name: "重新读取颜色", exact: true }).click(); await expect(page.getByRole("radio", { name: "蓝色", exact: true })).toBeVisible();
  await page.goto("/products/501?from=2026-08-22&to=2026-08-24&dimension=color&series=unknown-series"); await expect(heading).toBeVisible(); await expect(page).not.toHaveURL(/unknown-series/);
  await expect(page.getByRole("link", { name: "产品总表", exact: true })).toHaveAttribute("href", /\/products\?from=2026-08-22&to=2026-08-24&return_basis=event_date&fact_basis=current/);
  expect(unexpected).toEqual([]); expect(errors).toEqual([]); expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
});
