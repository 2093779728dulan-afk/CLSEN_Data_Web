import { expect, test, type Page } from "@playwright/test";

async function install(page: Page) {
  const state = { failure: false };
  const requests: string[] = [];
  const base = { overall_status: "complete", business_status: "published", return_status: "published", counts_as_incomplete: false, pending_summary: null, reasons: [], sales: "120.25", units_ordered: 6, sessions: 60, conversion_rate: "0.1", return_quantity: 0 };
  await page.route(url => url.pathname.startsWith("/api/"), async route => {
    const url = new URL(route.request().url());
    requests.push(url.pathname + url.search);
    expect(route.request().method()).toBe("GET");
    if (url.pathname === "/api/auth/me") return route.fulfill({ json: { id: 88, username: "synthetic-daily", display_name: "虚构查看账号", roles: ["viewer"] } });
    if (url.pathname === "/api/data-calendar/site-context") return route.fulfill({ json: { site_id: 1, site_code: "US", display_name: "虚构站点", site_config_version_id: 2, source_timezone: "UTC", reporting_timezone: "UTC", currency_code: "USD" } });
    if (url.pathname === "/api/dashboard/daily-ledger") {
      if (state.failure) return route.fulfill({ status: 503, json: { error: { code: "UNAVAILABLE", message: "虚构读取失败" } } });
      const from = url.searchParams.get("from")!;
      const month = from.slice(0, 7);
      return route.fulfill({ json: { publications: [], site_config_versions: [], range: { from_date: from, to_date: url.searchParams.get("to") }, rows: month === "2026-07" ? [] : [
        { ...base, report_date: `${month}-12`, overall_status: "partial", return_status: "missing", return_quantity: null, counts_as_incomplete: true, pending_summary: "退货报告缺失" },
        { ...base, report_date: `${month}-10`, ...(month === "2026-08" ? { sales: "0", units_ordered: 0, sessions: 0, conversion_rate: "0" } : {}) },
      ] } });
    }
    if (url.pathname.startsWith("/api/workbench/dates/")) return route.fulfill({ json: { actions: [], columns: [], head: null, pagination: { page: 1, page_size: 50, total_pages: 1, total_rows: 0 }, pending_upload_count: 0, permissions: { can_create_revision: false, can_edit: false, can_publish: false, can_undo: false, can_upload: false, can_validate: false }, report_date: url.pathname.split("/").at(-1), report_type: "business_report", rows: [], source: "empty", tabs: [{ report_type: "business_report", source: "empty" }, { report_type: "return_report", source: "empty" }], validation: null } });
    throw new Error(`Unexpected synthetic API request: ${url.pathname}`);
  });
  return { state, requests };
}

for (const width of [1280, 390]) {
  test(`actual daily ledger preserves URL filtering, role routes and refresh at ${width}px`, async ({ page }) => {
    await page.setViewportSize({ width, height: 900 });
    const { requests } = await install(page);
    await page.goto("/?month=2026-09");
    const table = page.getByRole("table", { name: "每日发布记录", exact: true });
    await expect(table.getByText("2026-09-12", { exact: true })).toBeVisible();
    await expect(table.locator("tbody time")).toHaveText(["2026-09-10", "2026-09-12"]);
    await page.reload();
    await expect(table.locator("tbody time")).toHaveText(["2026-09-10", "2026-09-12"]);
    await expect(page.getByRole("button", { name: "进入今日审核", exact: true })).toHaveCount(0);
    await expect(page.getByRole("tab", { name: "产品总表", exact: true })).toHaveCount(0);
    await page.getByRole("combobox", { name: "日期状态", exact: true }).selectOption("partial");
    await expect(page).toHaveURL(/month=2026-09&status=partial/);
    await expect(table.getByRole("row")).toHaveCount(2);
    await page.reload();
    await expect(page.getByRole("combobox", { name: "日期状态", exact: true })).toHaveValue("partial");
    await expect(table.getByText("2026-09-12", { exact: true })).toBeVisible();
    await table.getByRole("row").nth(1).focus(); await page.keyboard.press("Enter");
    await expect(page).toHaveURL(/\/published\/2026-09-12/);
    await expect(page.getByRole("heading", { name: "2026-09-12 日期数据工作台", exact: true })).toBeVisible();
    await page.getByRole("link", { name: "返回总表", exact: true }).click();
    await expect(table.getByText("2026-09-12", { exact: true })).toBeVisible();
    await expect(page.getByRole("combobox", { name: "日期状态", exact: true })).toHaveValue("partial");
    await page.getByRole("link", { name: "查看 2026-09-12", exact: true }).click();
    await expect(page).toHaveURL(/\/published\/2026-09-12/);
    await page.getByRole("link", { name: "返回总表", exact: true }).click();
    await expect(page.getByRole("combobox", { name: "日期状态", exact: true })).toHaveValue("partial");
    await page.getByRole("combobox", { name: "日期状态", exact: true }).selectOption("all");
    await page.getByRole("textbox", { name: "统计月份", exact: true }).fill("2026-08");
    await expect(table.getByText("2026-08-10", { exact: true })).toBeVisible();
    await expect(table.locator("tbody time")).toHaveText(["2026-08-10", "2026-08-12"]);
    await expect(table.getByText("2026-09-12", { exact: true })).toHaveCount(0);
    await expect(table.getByText("US$0.00", { exact: true })).toBeVisible();
    await expect(page.getByRole("link", { name: "发布明细", exact: true })).toHaveAttribute("href", "/ledger/published-details?from=2026-08-01&to=2026-08-31");
    expect(requests).toContain("/api/dashboard/daily-ledger?from=2026-08-01&to=2026-08-31");
    expect(requests.some(path => /product-ledger|product-card|style-ledger/.test(path))).toBe(false);
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
  });
}

test("actual daily ledger failure recovery does not mark unavailable or empty month complete", async ({ page }) => {
  const { state, requests } = await install(page);
  state.failure = true;
  await page.goto("/?month=2026-09&status=complete");
  await expect(page.getByRole("alert")).toBeVisible();
  await expect(page.getByText("本月完整度暂不可用", { exact: true })).toBeVisible();
  await expect(page.getByRole("table", { name: "每日发布记录", exact: true })).toHaveCount(0);
  state.failure = false;
  await page.getByRole("button", { name: "重新读取", exact: true }).click();
  await expect(page.getByRole("table").getByText("2026-09-10", { exact: true })).toBeVisible();
  await expect(page.getByRole("combobox", { name: "日期状态", exact: true })).toHaveValue("complete");
  await page.getByRole("textbox", { name: "统计月份", exact: true }).fill("2026-07");
  await expect(page.getByText("本月暂无日期记录", { exact: true })).toBeVisible();
  await expect(page.getByText("本月无需补齐", { exact: true })).toHaveCount(0);
  await page.reload();
  await expect(page.getByText("本月暂无日期记录", { exact: true })).toBeVisible();
  expect(requests.every(path => !path.includes("/publications/"))).toBe(true);
});
