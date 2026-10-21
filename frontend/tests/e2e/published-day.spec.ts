import { expect, test, type Page } from "@playwright/test";

async function install(page: Page) {
  const state = { failure: false, empty: false };
  const requests: string[] = [];
  const row = { report_date: "2026-09-12", overall_status: "partial", business_status: "published", return_status: "missing", counts_as_incomplete: true, pending_summary: "退货报告缺失", reasons: [], sales: "120.25", units_ordered: 6, sessions: 60, conversion_rate: "0.1", return_quantity: null };
  await page.route(url => url.pathname.startsWith("/api/"), async route => {
    const url = new URL(route.request().url()); requests.push(url.pathname + url.search);
    expect(route.request().method()).toBe("GET");
    if (url.pathname === "/api/auth/me") return route.fulfill({ json: { id: 88, username: "synthetic-published-day", display_name: "虚构查看账号", roles: ["viewer"] } });
    if (url.pathname === "/api/data-calendar/site-context") return route.fulfill({ json: { site_id: 1, site_code: "US", display_name: "虚构站点", site_config_version_id: 2, source_timezone: "UTC", reporting_timezone: "UTC", currency_code: "USD" } });
    if (url.pathname === "/api/dashboard/daily-ledger") {
      if (state.failure) return route.fulfill({ status: 503, json: { error: { code: "UNAVAILABLE" } } });
      const from = url.searchParams.get("from")!; const to = url.searchParams.get("to")!;
      return route.fulfill({ json: { publications: [], site_config_versions: [], range: { from_date: from, to_date: to }, rows: state.empty ? [] : from === to ? [row] : [{ ...row, report_date: "2026-09-01", sales: "0.10", return_status: "published", return_quantity: 0 }, { ...row, report_date: "2026-09-02", sales: "0.20", return_status: "published", return_quantity: 1 }, row] } });
    }
    if (url.pathname.startsWith("/api/workbench/dates/")) return route.fulfill({ json: { actions: [], columns: [], head: null, pagination: { page: 1, page_size: 50, total_pages: 1, total_rows: 0 }, pending_upload_count: 0, permissions: { can_create_revision: false, can_edit: false, can_publish: false, can_undo: false, can_upload: false, can_validate: false }, report_date: url.pathname.split("/").at(-1), report_type: "business_report", rows: [], source: "empty", tabs: [{ report_type: "business_report", source: "empty" }, { report_type: "return_report", source: "empty" }], validation: null } });
    throw new Error(`Unexpected synthetic request: ${url.pathname}`);
  });
  return { state, requests };
}
for (const width of [1280, 390]) {
  test(`actual published day recovers, preserves scopes and navigates at ${width}px`, async ({ page }) => {
    await page.setViewportSize({ width, height: 900 });
    const { state, requests } = await install(page); state.failure = true;
    await page.goto("/published-details/2026-09-12?return_to=" + encodeURIComponent("/ledger/published-details?from=2026-09-01&to=2026-09-30&mode=rows"));
    await expect(page.getByRole("alert")).toBeVisible(); state.failure = false;
    await page.getByRole("button", { name: "重新读取", exact: true }).click();
    await expect(page.getByRole("region", { name: "当前发布指标", exact: true })).toContainText("报告未发布");
    await expect(page.getByText("US$120.55", { exact: true })).toBeVisible();
    await page.getByRole("combobox", { name: "趋势指标", exact: true }).selectOption("return_quantity");
    await page.getByText("查看逐日数据 · 退货数", { exact: true }).click();
    await expect(page.getByRole("table").getByRole("row", { name: /2026-09-03/ })).toContainText("未发布或暂无指标值");
    await expect(page.getByRole("table").getByRole("row", { name: /2026-09-12/ })).toContainText("未发布或暂无指标值");
    await expect(page.getByRole("link", { name: "返回发布明细", exact: true })).toHaveAttribute("href", "/ledger/published-details?from=2026-09-01&to=2026-09-30&mode=rows");
    await expect(page.getByRole("link", { name: "查看当日原始明细", exact: true })).toHaveAttribute("href", "/ledger/published-details?from=2026-09-12&to=2026-09-12&mode=rows");
    await page.reload();
    await expect(page.getByRole("region", { name: "当前发布指标", exact: true })).toContainText("US$120.25");
    await page.getByRole("link", { name: "返回每日总表", exact: true }).click();
    await expect(page).toHaveURL(/\?month=2026-09/);
    const table = page.getByRole("table", { name: "每日发布记录", exact: true });
    await table.getByRole("link", { name: "查看 2026-09-12", exact: true }).click();
    await expect(page.getByRole("region", { name: "单日只读发布详情", exact: true })).toBeVisible();
    await expect(page.getByRole("heading", { name: "本月趋势", exact: true })).toHaveCount(0);
    expect(requests).toContain("/api/dashboard/daily-ledger?from=2026-09-01&to=2026-09-12");
    expect(requests).toContain("/api/dashboard/daily-ledger?from=2026-09-12&to=2026-09-12");
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
  });
}
test("actual published day rejects unsafe return destinations and invalid dates; empty remains explicit", async ({ page }) => {
  const { state, requests } = await install(page); state.empty = true;
  await page.goto("/published-details/2026-09-12?return_to=" + encodeURIComponent("https://example.com/"));
  await expect(page.getByText("这个日期没有发布数据", { exact: true })).toBeVisible();
  await expect(page.getByRole("link", { name: "返回发布明细", exact: true })).toHaveCount(0);
  const before = requests.filter(path => path.startsWith("/api/dashboard/daily-ledger")).length;
  await page.goto("/published-details/2026-02-31");
  await expect(page.getByRole("alert")).toContainText("报告日期格式无效");
  expect(requests.filter(path => path.startsWith("/api/dashboard/daily-ledger"))).toHaveLength(before);
});
