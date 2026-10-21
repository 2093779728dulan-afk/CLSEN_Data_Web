import { expect, test, type Page } from "@playwright/test";
import { sampleWorkbench } from "../../src/features/workbench/DateWorkbenchView.fixtures";

async function install(page: Page) {
  const state = { failure: true };
  const data = sampleWorkbench("published", false);
  await page.context().route(url => url.pathname.startsWith("/api/"), async route => {
    const url = new URL(route.request().url()); expect(route.request().method()).toBe("GET");
    if (url.pathname === "/api/auth/me") return route.fulfill({ json: { id: 188, username: "synthetic-column-viewer", display_name: "虚构列设置查看账号", roles: ["viewer"] } });
    if (url.pathname === "/api/data-calendar/site-context") return route.fulfill({ json: { site_id: 1, site_code: "US", display_name: "虚构站点", site_config_version_id: 2, source_timezone: "UTC", reporting_timezone: "UTC", currency_code: "USD" } });
    if (url.pathname === "/api/dashboard/daily-ledger") return route.fulfill({ json: { publications: [], site_config_versions: [], rows: [], range: { from_date: "2026-09-12", to_date: "2026-09-12" } } });
    if (url.pathname === "/api/workbench/dates/2026-09-12") return route.fulfill({ status: state.failure ? 503 : 200, json: state.failure ? { error: { code: "UNAVAILABLE" } } : data });
    if (url.pathname === "/api/published-details/rows") return route.fulfill({ status: state.failure ? 503 : 200, json: state.failure ? { error: { code: "UNAVAILABLE" } } : {
      range: { from_date: "2026-09-01", to_date: "2026-09-12" }, scope_token: "fictional-scope", publications: [], permissions: { can_export: true }, pagination: { page: 1, page_size: 25, total_items: 1, total_pages: 1 },
      columns: data.columns, rows: [{ report_date: "2026-09-12", published_at: "2026-09-12T08:30:00Z", version_id: 92, version_no: 1, row_ordinal: 1, cells: data.rows[0]!.cells.map(cell => ({ column_id: cell.column_id, value: cell.current })) }],
    } });
    throw new Error(`Unexpected column-settings request: ${url.pathname}`);
  });
  return state;
}
for (const width of [1280, 390]) {
  test(`both actual consumers preserve column preferences, recovery and scope at ${width}px`, async ({ page }) => {
    await page.setViewportSize({ width, height: 900 });
    const state = await install(page);
    for (const consumer of ["workbench", "published-details"] as const) {
      state.failure = true;
      const url = consumer === "workbench" ? "/published/2026-09-12?report_type=business_report" : "/ledger/published-details?from=2026-09-01&to=2026-09-12&mode=rows";
      await page.goto(url); await expect(page.getByRole("alert")).toBeVisible();
      state.failure = false;
      await page.getByRole("button", { name: consumer === "workbench" ? "重新读取" : "重新读取明细", exact: true }).click();
      const trigger = page.getByRole("button", { name: "列设置", exact: true });
      await trigger.click();
      const panel = page.getByRole("region", { name: "列设置", exact: true });
      await expect(panel.getByRole("searchbox", { name: "搜索列", exact: true })).toBeFocused();
      const openingBox = (await panel.boundingBox())!;
      expect(openingBox.y).toBeGreaterThanOrEqual(0);
      expect(openingBox.y + openingBox.height).toBeLessThanOrEqual(901);
      // Same IDs and user/site/report; the published namespace must remain independent.
      await expect(panel.getByRole("checkbox", { name: "Sales", exact: true })).toBeChecked();
      await panel.getByRole("searchbox", { name: "搜索列" }).fill("sales");
      await panel.getByRole("checkbox", { name: "Sales", exact: true }).uncheck();
      await panel.getByRole("button", { name: "清空列搜索", exact: true }).click();
      await panel.getByRole("checkbox", { name: "Parent ASIN", exact: true }).uncheck();
      await expect(panel.getByRole("checkbox", { name: "SKU", exact: true })).toBeDisabled();
      await panel.getByRole("button", { name: "将 Sessions 上移", exact: true }).click();
      await panel.getByRole("button", { name: "只显示统计字段", exact: true }).click();
      await expect(panel.getByRole("checkbox", { name: "Marketplace extension", exact: true })).not.toBeChecked();
      await panel.getByRole("checkbox", { name: "Sales", exact: true }).uncheck();
      await panel.getByRole("button", { name: "恢复原始顺序", exact: true }).click();
      await panel.getByRole("button", { name: "重置列宽", exact: true }).click();
      await panel.getByRole("searchbox", { name: "搜索列" }).focus(); await page.keyboard.press("Escape");
      await expect(panel).toHaveCount(0); await expect(trigger).toBeFocused();
      await expect(page.getByRole("columnheader").filter({ hasText: "Sales" })).toHaveCount(0);
      await expect(page).toHaveURL(url);
      await page.reload(); await trigger.click();
      await expect(panel.getByRole("checkbox", { name: "Sales", exact: true })).not.toBeChecked();
      await panel.getByRole("checkbox", { name: "Sales", exact: true }).check();
      await expect(page.getByRole("columnheader").filter({ hasText: "Sales" })).toHaveCount(1);
      const box = (await panel.boundingBox())!; expect(box.x).toBeGreaterThanOrEqual(0); expect(box.x + box.width).toBeLessThanOrEqual(width);
      await panel.getByRole("button", { name: "关闭列设置", exact: true }).click(); await expect(trigger).toBeFocused();
      expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
      if (consumer === "workbench") {
        await trigger.click(); await panel.getByRole("checkbox", { name: "Sales", exact: true }).uncheck(); await panel.getByRole("button", { name: "关闭列设置", exact: true }).click();
      }
    }
  });
}
