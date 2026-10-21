import { expect, test, type Page } from "@playwright/test";
import { sampleWorkbench } from "../../src/features/workbench/DateWorkbenchView.fixtures";

async function install(page: Page) {
  const state = { failure: true }; const requests: URL[] = [];
  await page.context().route(url => url.pathname.startsWith("/api/"), async route => {
    const url = new URL(route.request().url()); requests.push(url); expect(route.request().method()).toBe("GET");
    if (url.pathname === "/api/auth/me") return route.fulfill({ json: { id: 288, username: "synthetic-header-viewer", display_name: "虚构表头查看账号", roles: ["viewer"] } });
    if (url.pathname === "/api/data-calendar/site-context") return route.fulfill({ json: { site_id: 1, site_code: "US", display_name: "虚构站点", site_config_version_id: 2, source_timezone: "UTC", reporting_timezone: "UTC", currency_code: "USD" } });
    if (url.pathname === "/api/dashboard/daily-ledger") return route.fulfill({ json: { publications: [], site_config_versions: [], rows: [], range: { from_date: "2026-09-12", to_date: "2026-09-12" } } });
    if (url.pathname === "/api/workbench/dates/2026-09-12" || url.pathname === "/api/published-details/rows") {
      if (state.failure) return route.fulfill({ status: 503, json: { error: { code: "UNAVAILABLE" } } });
      const data = sampleWorkbench("published", false); data.rows = data.rows.slice(0, 3); data.pagination.total_rows = 3;
      data.rows.forEach((row, index) => { row.cells[0]!.current = ["DEMO-B", "DEMO-A", "DEMO-C"][index]!; });
      if (url.searchParams.get("sort_column_id") === data.columns[0]!.column_id) data.rows.sort((a, b) => String(a.cells[0]!.current).localeCompare(String(b.cells[0]!.current)) * (url.searchParams.get("direction") === "desc" ? -1 : 1));
      if (url.pathname.startsWith("/api/workbench")) return route.fulfill({ json: data });
      return route.fulfill({ json: { range: { from_date: "2026-09-01", to_date: "2026-09-12" }, scope_token: "fictional-header-scope", publications: [], permissions: { can_export: true }, pagination: { page: 1, page_size: 25, total_items: 3, total_pages: 1 }, columns: data.columns,
        rows: data.rows.map(row => ({ report_date: "2026-09-12", published_at: "2026-09-12T08:30:00Z", version_id: 92, version_no: 1, row_ordinal: row.row_ordinal, cells: row.cells.map(cell => ({ column_id: cell.column_id, value: cell.current })) })),
      } });
    }
    throw new Error(`Unexpected header fixture request: ${url.pathname}`);
  });
  return { state, requests };
}
for (const width of [1280, 390]) {
  test(`actual workbench and published header preserve server sorting and width at ${width}px`, async ({ page }) => {
    await page.setViewportSize({ width, height: 900 }); const { state, requests } = await install(page);
    for (const consumer of ["workbench", "published-details"]) {
      state.failure = true; await page.goto(consumer === "workbench" ? "/published/2026-09-12?report_type=business_report" : "/ledger/published-details?from=2026-09-01&to=2026-09-12&mode=rows");
      await expect(page.getByRole("alert")).toBeVisible(); state.failure = false;
      await page.getByRole("button", { name: consumer === "workbench" ? "重新读取" : "重新读取明细", exact: true }).click();
      const table = page.getByRole("table", { name: consumer === "workbench" ? "经营报告原始数据" : "经营报告已发布原始明细", exact: true });
      const sort = table.getByRole("button", { name: "按 Parent ASIN 排序", exact: true });
      await sort.click(); await expect(sort.locator("..")).toHaveAttribute("aria-sort", "ascending"); await expect(table.locator("tbody tr").first()).toContainText("DEMO-A");
      await expect(page).toHaveURL(/sort_column_id=3e2d27a9/);
      await page.reload(); await expect(sort.locator("..")).toHaveAttribute("aria-sort", "ascending"); await expect(table.locator("tbody tr").first()).toContainText("DEMO-A");
      await sort.click(); await expect(sort.locator("..")).toHaveAttribute("aria-sort", "descending"); await expect(table.locator("tbody tr").first()).toContainText("DEMO-C");
      await sort.focus(); await page.keyboard.press("Enter"); await expect(sort.locator("..")).toHaveAttribute("aria-sort", "none"); await expect(table.locator("tbody tr").first()).toContainText("DEMO-B");
      const resize = table.getByRole("button", { name: "调整“Parent ASIN”列宽", exact: true }); const header = resize.locator(".."); const initial = await header.evaluate(el => parseFloat(el.style.width)); const renderedInitial = (await header.boundingBox())!.width;
      await resize.focus(); await page.keyboard.press("ArrowRight"); await expect.poll(async () => await header.evaluate(el => parseFloat(el.style.width))).toBe(initial + 8);
      expect((await header.boundingBox())!.width).toBeGreaterThan(renderedInitial);
      await page.reload(); await expect.poll(async () => await header.evaluate(el => parseFloat(el.style.width))).toBe(initial + 8);
      const scroll = table.locator(".."); const leading = table.getByRole("columnheader", { name: consumer === "workbench" ? "行" : "报告日期", exact: true }); const before = (await leading.boundingBox())!.x;
      await scroll.evaluate(el => { el.scrollLeft = 500; });
      const offset = await scroll.evaluate(el => el.scrollLeft);
      expect(offset).toBeGreaterThan(0);
      // Narrow published grids scroll the leading column so metric headers stay
      // reachable; the workbench and desktop published grid retain frozen columns.
      await expect.poll(async () => (await leading.boundingBox())!.x).toBe(
        consumer === "published-details" && width === 390 ? before - offset : before,
      );
      expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
    }
    expect(requests.some(url => url.searchParams.get("sort_column_id")?.startsWith("3e2d27a9") && url.searchParams.get("direction") === "desc")).toBe(true);
  });
}
