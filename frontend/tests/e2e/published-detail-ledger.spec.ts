import { expect, test, type Page } from "@playwright/test";

async function install(page: Page) {
  const state = { failure: false, conflict: 0, emptyRange: false, rangeFailure: false };
  const requests: URL[] = [];
  await page.context().route(url => url.pathname.startsWith("/api/"), async route => {
    const url = new URL(route.request().url()); requests.push(url);
    expect(route.request().method()).toBe("GET");
    if (url.pathname === "/api/auth/me") return route.fulfill({ json: { id: 88, username: "synthetic-ledger", display_name: "虚构查看账号", roles: ["viewer"] } });
    if (url.pathname === "/api/data-calendar/site-context") return route.fulfill({ json: { site_id: 1, site_code: "US", display_name: "虚构站点", site_config_version_id: 2, source_timezone: "UTC", reporting_timezone: "UTC", currency_code: "USD" } });
    const from = url.searchParams.get("from") ?? "2026-09-01"; const to = url.searchParams.get("to") ?? "2026-09-12";
    if (url.pathname === "/api/published-details/range") return route.fulfill({ status: state.rangeFailure ? 503 : 200, json: state.rangeFailure ? { error: { code: "UNAVAILABLE" } } : { from_date: state.emptyRange ? null : "2026-09-01", to_date: state.emptyRange ? null : "2026-09-12" } });
    if (url.pathname === "/api/published-details/export.csv") return route.fulfill({ contentType: "text/csv", headers: { "content-disposition": 'attachment; filename="synthetic-ledger.csv"' }, body: "Seller SKU,Sales\nSAMPLE-BLUE-S,120.50\n" });
    if (url.pathname.startsWith("/api/published-details/")) {
      if (state.failure) return route.fulfill({ status: 503, json: { error: { code: "UNAVAILABLE" } } });
      if (state.conflict > 0) { state.conflict -= 1; return route.fulfill({ status: 409, json: { error: { code: "publication_scope_changed" } } }); }
      const reportType = url.searchParams.get("report_type") ?? "business_report";
      const pagination = { page: Number(url.searchParams.get("page") ?? "1"), page_size: 25, total_items: 26, total_pages: 2 };
      const base = { range: { from_date: from, to_date: to }, scope_token: "fictional-scope", publications: [], permissions: { can_export: true }, pagination };
      if (url.pathname.endsWith("/summaries")) return route.fulfill({ json: { ...base, summaries: [{ report_date: "2026-09-12", published_at: "2026-09-12T08:30:00Z", publication: { report_date: "2026-09-12", report_type: reportType, published_at: "2026-09-12T08:30:00Z", dataset_id: 12, site_id: 1, version_id: 112 }, version_id: 112, version_no: 3, matching_row_count: 2, total_row_count: 2, metric_scope: "full_day", sales: "120.50", sessions: 100, units_ordered: 4, return_quantity: 0 }] } });
      if (url.pathname.endsWith("/rows")) return route.fulfill({ json: { ...base, columns: [{ column_id: "8e4555a0-5397-4b36-b165-0af347ba05b9", source_header: "Seller SKU", display_order: 0, is_key: true, participates_in_statistics: false, standard_field_name: "seller_sku", value_kind: "text" }, { column_id: "9e4555a0-5397-4b36-b165-0af347ba05b9", source_header: "销售额", display_order: 1, is_key: false, participates_in_statistics: true, standard_field_name: "sales", value_kind: "decimal" }], rows: [{ report_date: url.searchParams.get("report_date") ?? "2026-09-12", published_at: "2026-09-12T08:30:00Z", version_id: 112, version_no: 3, row_ordinal: pagination.page === 2 ? 26 : 1, cells: [{ column_id: "8e4555a0-5397-4b36-b165-0af347ba05b9", value: "SAMPLE-BLUE-S" }, { column_id: "9e4555a0-5397-4b36-b165-0af347ba05b9", value: "120.50" }] }] } });
    }
    if (url.pathname === "/api/dashboard/daily-ledger") return route.fulfill({ json: { publications: [], site_config_versions: [], range: { from_date: from, to_date: to }, rows: [{ report_date: "2026-09-12", overall_status: "complete", business_status: "published", return_status: "published", counts_as_incomplete: false, pending_summary: null, reasons: [], sales: "120.50", units_ordered: 4, sessions: 100, conversion_rate: "0.04", return_quantity: 0 }] } });
    throw new Error(`Unexpected synthetic request ${url.pathname}`);
  });
  return { state, requests };
}
for (const width of [1280, 390]) {
  test(`actual detail ledger preserves URL, snapshot, column layout and export at ${width}px`, async ({ page }) => {
    await page.setViewportSize({ width, height: 900 });
    const { state, requests } = await install(page); state.failure = true;
    await page.goto("/ledger/published-details?from=2026-09-01&to=2026-09-12");
    await expect(page.getByRole("alert")).toBeVisible(); state.failure = false;
    await page.getByRole("button", { name: "重新读取日期摘要", exact: true }).click();
    await page.getByRole("searchbox", { name: "搜索已发布原始字段和报告日期", exact: true }).fill("SAMPLE");
    await page.getByRole("button", { name: "搜索", exact: true }).click();
    await page.getByRole("button", { name: "展开 2026-09-12 明细", exact: true }).click();
    await expect(page.getByRole("region", { name: "2026-09-12 展开明细", exact: true })).toContainText("SAMPLE-BLUE-S");
    expect(requests.some(url => url.pathname.endsWith("/rows") && url.searchParams.get("scope_token") === "fictional-scope" && url.searchParams.get("report_date") === "2026-09-12" && url.searchParams.get("search") === "SAMPLE")).toBe(true);
    await page.getByRole("tab", { name: "全部明细", exact: true }).click();
    await page.getByRole("button", { name: "按 销售额 排序", exact: true }).click();
    await expect(page).toHaveURL(/sort_column_id=9e4555a0-5397-4b36-b165-0af347ba05b9/);
    await page.getByRole("button", { name: "列设置", exact: true }).click();
    await page.getByRole("checkbox", { name: "销售额", exact: true }).uncheck();
    await page.getByRole("button", { name: "关闭列设置", exact: true }).click();
    await page.reload();
    await expect(page.getByRole("button", { name: "按 销售额 排序", exact: true })).toHaveCount(0);
    await expect(page.getByRole("searchbox", { name: "搜索已发布原始字段和报告日期", exact: true })).toHaveValue("SAMPLE");
    const exportLink = page.getByRole("link", { name: "导出 CSV", exact: true });
    await expect(exportLink).toHaveAttribute("href", /scope_token=fictional-scope/);
    await expect(exportLink).toHaveAttribute("href", /column_id=8e4555a0-5397-4b36-b165-0af347ba05b9/);
    await expect(exportLink).toHaveAttribute("download", "");
    // Chromium bypasses Playwright routing for a download-attribute request. The synthetic
    // attachment response supplies the download semantics while retaining the actual href.
    await exportLink.evaluate(element => element.removeAttribute("download"));
    const download = page.waitForEvent("download"); await exportLink.click(); expect((await download).suggestedFilename()).toBe("synthetic-ledger.csv");
    await page.getByRole("button", { name: "下一页", exact: true }).click();
    await expect(page).toHaveURL(/page=2/);
    await expect(page.getByRole("cell", { name: "26", exact: true })).toBeVisible();
    const dateLink = page.getByRole("link", { name: "查看 2026-09-12 单日摘要", exact: true });
    await dateLink.click();
    await expect(page.getByRole("region", { name: "当前发布指标", exact: true })).toContainText("US$120.50");
    await page.getByRole("link", { name: "返回发布明细", exact: true }).click();
    await expect(page).toHaveURL(/mode=rows/); await expect(page).toHaveURL(/search=SAMPLE/); await expect(page).toHaveURL(/page=2/);
    await page.getByRole("tab", { name: "退货明细", exact: true }).click();
    await page.getByRole("tab", { name: "按日期摘要", exact: true }).click();
    await expect(page.getByText("退货数量 · 全日 0", { exact: true })).toBeVisible();
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
  });
}
test("actual detail ledger stops repeated publication conflicts and recovers range failure/empty", async ({ page }) => {
  const { state, requests } = await install(page);
  await page.goto("/ledger/published-details?from=2026-09-01&to=2026-09-12");
  await expect(page.getByText("当前发布 v3", { exact: true })).toBeVisible();
  const initial = requests.filter(url => url.pathname.endsWith("/summaries")).length;
  state.conflict = 2;
  await page.getByRole("searchbox", { name: "搜索已发布原始字段和报告日期", exact: true }).fill("conflict-fixture");
  await page.getByRole("button", { name: "搜索", exact: true }).click();
  await expect(page.getByRole("alert")).toContainText("发布数据持续变化");
  expect(requests.filter(url => url.pathname.endsWith("/summaries"))).toHaveLength(initial + 2);
  await page.getByRole("button", { name: "重新读取日期摘要", exact: true }).click();
  await expect(page.getByText("当前发布 v3", { exact: true })).toBeVisible();
  state.rangeFailure = true; await page.getByRole("button", { name: "全部已发布", exact: true }).click();
  await expect(page.getByRole("alert")).toContainText("已发布范围读取失败");
  state.rangeFailure = false; state.emptyRange = true;
  await page.getByRole("button", { name: "重试全部已发布范围", exact: true }).click();
  await expect(page.getByText("当前报表类型还没有任何已发布明细。", { exact: true })).toBeVisible();
  state.emptyRange = false; await page.getByRole("button", { name: "全部已发布", exact: true }).click();
  await expect(page.getByText("当前发布 v3", { exact: true })).toBeVisible();
});
