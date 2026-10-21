import { expect, test, type Page } from "@playwright/test";
import { detailFixture } from "../../src/features/products/ProductDetailAnalysisView.fixtures";
import { ledgerCategories, ledgerFixture } from "../../src/features/products/ProductLedgerView.fixtures";
import { parseProductDetailSearch } from "../../src/features/products/productDetailState";

// Exercise real Routes/controllers with fictional GET responses; no backend is contacted.
async function install(page: Page, role: "viewer" | "data_manager" = "viewer") {
  const state = { detailFailure: false, dayFailure: false };
  const unexpected: string[] = [];
  const reads: URL[] = [];
  const errors: string[] = [];
  page.on("pageerror", error => errors.push(error.message));
  const styles = Array.from({ length: 26 }, (_, i) => ({ style_id: 700 + i, style_code: `DEMO-${i + 1}`, standard_name: i < 2 ? "同名示例商品" : `示例商品 ${i + 1}`, category_name: "示例分类", category_id: 1, category_code: "DEMO", category_recorded: true, revision: 1, status: "enabled", variant_count: 0, seller_sku_count: 0, source_summary: { first_seen_date: "2026-08-22", latest_seen_date: "2026-08-24", source_report_count: 0, observation_count: 0 } }));
  const day = { report_date: "2026-09-12", overall_status: "partial", business_status: "published", return_status: "missing", counts_as_incomplete: true, pending_summary: "退货报告缺失", reasons: [], sales: "120.25", units_ordered: 6, sessions: 60, conversion_rate: "0.1", return_quantity: null };
  await page.route(url => url.pathname.startsWith("/api/"), async route => {
    const request = route.request(); const url = new URL(request.url()); const path = url.pathname;
    if (request.method() !== "GET") { unexpected.push(`${request.method()} ${path}`); return route.fulfill({ status: 405 }); }
    reads.push(url);
    const failure = () => route.fulfill({ status: 503, json: { error: { code: "fictional_failure", message: "虚构跨页读取失败" } } });
    if (path === "/api/auth/me") return route.fulfill({ json: { id: 88, username: `synthetic-navigation-${role}`, display_name: "虚构串联账号", roles: [role] } });
    if (path === "/api/data-calendar/site-context") return route.fulfill({ json: { site_id: 1, site_code: "US", display_name: "虚构美国站点", site_config_version_id: 2, source_timezone: "America/Los_Angeles", reporting_timezone: "America/Los_Angeles", currency_code: "USD" } });
    if (path === "/api/catalog/categories") return route.fulfill({ json: { categories: ledgerCategories } });
    if (path === "/api/dashboard/styles/501/card") {
      if (state.detailFailure) return failure();
      return route.fulfill({ json: detailFixture(parseProductDetailSearch(url.searchParams, "2026-08-24"), "read-only") });
    }
    if (path === "/api/dashboard/style-ledger") {
      const q = url.searchParams; const data = ledgerFixture();
      const detail = detailFixture(parseProductDetailSearch(q, q.get("to") ?? "2026-08-24"), "read-only");
      const expectedDays = Math.round((Date.parse(detail.provenance.to) - Date.parse(detail.provenance.from)) / 86_400_000) + 1;
      const observedDays = Math.min(3, expectedDays);
      for (const metric of Object.values(detail.summary.metrics)) Object.assign(metric, { expected_days: expectedDays, observed_days: observedDays, is_partial: observedDays < expectedDays, source_completeness: observedDays < expectedDays ? "partial" : "complete" });
      Object.assign(data.provenance, detail.provenance);
      Object.assign(data.rows[0]!, { metrics: detail.summary.metrics, sku_count: 2, color_count: 2, size_count: 2 });
      data.page = Number(q.get("page") ?? 1); data.page_size = Number(q.get("page_size") ?? 50);
      data.sort = (q.get("sort") ?? "units") as typeof data.sort; data.direction = (q.get("direction") ?? "desc") as typeof data.direction;
      data.filtered_sales_total = "360.00";
      for (const block of [data.coverage.business, data.coverage.returns]) Object.assign(block, { coverage_from: q.get("from"), coverage_to: q.get("to"), expected_days: expectedDays, published_days: observedDays, missing_days: expectedDays - observedDays, report_coverage_rate: (observedDays / expectedDays).toFixed(6) });
      data.reconciliation.source_totals = { ...detail.style_reconciliation.summary_totals };
      data.reconciliation.mapped_totals = { ...detail.style_reconciliation.summary_totals };
      return route.fulfill({ json: data });
    }
    if (path === "/api/catalog/styles") return route.fulfill({ json: { catalog: { catalog_publication_revision: 7, catalog_version_id: 7, version_number: 7, skus: [], styles } } });
    const style = path.match(/^\/api\/catalog\/styles\/(7\d\d)$/);
    if (style) return route.fulfill({ json: { style: styles.find(item => item.style_id === Number(style[1])), skus: [], catalog_version_id: 7, permissions: { can_edit: false, can_manage_categories: false } } });
    if (path.endsWith("/pending-items")) return route.fulfill({ json: { items: [], permissions: { can_review: false } } });
    if (path === "/api/catalog/source-scope") return route.fulfill({ json: { status: "unconfirmed", permissions: { can_confirm: false }, site_config_revision: 1 } });
    if (path === "/api/dashboard/style-readiness") return route.fulfill({ json: { prerequisites_present: false, catalog_approved: true, published_reports: 0 } });
    if (path === "/api/dashboard/daily-ledger") {
      const from = url.searchParams.get("from")!; const to = url.searchParams.get("to")!;
      if (state.dayFailure && from === to) return failure();
      return route.fulfill({ json: { publications: [], site_config_versions: [], range: { from_date: from, to_date: to }, rows: [day, { ...day, report_date: "2026-09-10", overall_status: "complete", return_status: "published", counts_as_incomplete: false, pending_summary: null, return_quantity: 0 }].filter(row => row.report_date >= from && row.report_date <= to) } });
    }
    if (path.startsWith("/api/workbench/dates/")) return route.fulfill({ json: { actions: [], columns: [], head: null, pagination: { page: 1, page_size: 50, total_pages: 1, total_rows: 0 }, pending_upload_count: 0, permissions: { can_create_revision: false, can_edit: false, can_publish: false, can_undo: false, can_upload: false, can_validate: false }, report_date: path.split("/").at(-1), report_type: "business_report", rows: [], source: "empty", tabs: [{ report_type: "business_report", source: "empty" }, { report_type: "return_report", source: "empty" }], validation: null } });
    if (["/api/versions", "/api/admin/published-moves/undoable"].includes(path)) return route.fulfill({ json: [] });
    if (path === "/api/imports/batch-reviews") return route.fulfill({ json: { items: [], has_next: false } });
    unexpected.push(`${request.method()} ${path}`); return route.fulfill({ status: 500, json: {} });
  });
  return { state, unexpected, reads, errors };
}

test("direct workbench entry ignores external or malformed return state", async ({ page }) => {
  const fixture = await install(page);
  await page.goto("/published/2026-09-12");
  const back = page.getByRole("link", { name: "返回总表", exact: true });
  await expect(back).toHaveAttribute("href", "/?month=2026-09");
  for (const returnTo of ["https://example.com/", "//example.com/", "/catalog", 12]) {
    await page.evaluate(value => history.replaceState({ ...history.state, usr: { returnTo: value } }, ""), returnTo);
    await page.reload(); await expect(back).toHaveAttribute("href", "/?month=2026-09");
  }
  await back.click(); await expect(page.getByRole("table", { name: "每日发布记录", exact: true })).toBeVisible();
  expect(fixture.errors).toEqual([]); expect(fixture.unexpected).toEqual([]);
});

async function primaryNavigation(page: Page, width: number, label: string) {
  if (width === 390) await page.getByRole("button", { name: "打开主导航", exact: true }).click();
  const navigation = page.getByRole("navigation", { name: "工作区", exact: true });
  const link = navigation.getByRole("link", { name: label, exact: true });
  await link.focus(); await page.keyboard.press("Enter");
  await expect(page.getByRole("dialog", { name: "工作区导航", exact: true })).toHaveCount(0);
}

for (const width of [1280, 390]) {
  test(`ledger to detail retains URL, stable identity, recovery and return focus at ${width}px`, async ({ page }, testInfo) => {
    await page.setViewportSize({ width, height: 900 });
    if (width === 390) await page.emulateMedia({ reducedMotion: "reduce" });
    const fixture = await install(page);
    await page.goto("/products?from=2026-08-22&to=2026-08-24");
    await page.getByRole("combobox", { name: "筛选主分类", exact: true }).selectOption("1");
    await page.getByRole("combobox", { name: "筛选细分类", exact: true }).selectOption("2");
    await page.getByRole("textbox", { name: "款号或标准名称", exact: true }).fill("10001");
    await page.getByRole("button", { name: "应用筛选", exact: true }).click();
    await page.getByRole("button", { name: "销售贡献", exact: true }).click();
    await page.getByRole("combobox", { name: "退货日期", exact: true }).selectOption("report_date");
    await expect(page).toHaveURL(/return_basis=report_date/);
    // BrowserRouter updates the address before React commits the controlled field.
    await expect(page.getByRole("combobox", { name: "退货日期", exact: true })).toHaveValue("report_date");
    await page.getByRole("combobox", { name: "事实版本", exact: true }).selectOption("catalog_snapshot");
    await expect(page).toHaveURL(/fact_basis=catalog_snapshot/);
    await expect(page.getByRole("combobox", { name: "退货日期", exact: true })).toHaveValue("report_date");
    await expect(page.getByRole("combobox", { name: "筛选细分类", exact: true })).toHaveValue("2");
    await expect(page).toHaveURL(/category_id=2&search=10001&sort=sales/);
    const trigger = page.getByRole("button", { name: "查看款号 10001 商品信息", exact: true });
    await expect(trigger).toBeEnabled(); const ledgerUrl = page.url();
    await trigger.focus(); await page.keyboard.press("Enter");
    await expect(page.getByRole("link", { name: "进入款式详情" })).toHaveAttribute("href", /return_basis=report_date&fact_basis=catalog_snapshot/);
    await page.getByRole("link", { name: "进入款式详情" }).click();
    await expect(page).toHaveURL(/\/products\/501\?/);
    await expect(page.getByRole("heading", { name: "标准轻量夹克", exact: true })).toBeVisible();
    await expect(page.getByRole("radio", { name: "报表日期", exact: true })).toBeChecked();
    fixture.state.detailFailure = true;
    await page.getByRole("radio", { name: "销售额", exact: true }).click();
    await expect(page.getByRole("alert")).toContainText("产品详情读取失败");
    fixture.state.detailFailure = false;
    await page.getByRole("button", { name: "按原条件重试", exact: true }).click();
    await expect(page.getByRole("img", { name: /产品每日趋势.*销售额/ })).toBeVisible();
    await page.reload(); await expect(page.getByRole("heading", { name: "标准轻量夹克", exact: true })).toBeVisible();
    await page.getByRole("link", { name: "产品总表", exact: true }).click();
    await expect(page).toHaveURL(ledgerUrl); await expect(trigger).toBeFocused();
    await expect(page.getByRole("textbox", { name: "款号或标准名称", exact: true })).toHaveValue("10001");
    await expect(page.getByRole("combobox", { name: "筛选细分类", exact: true })).toHaveValue("2");
    await page.goBack(); await expect(page.getByRole("heading", { name: "标准轻量夹克", exact: true })).toBeVisible();
    await page.goForward(); await expect(page).toHaveURL(ledgerUrl); await expect(trigger).toBeFocused();
    await page.screenshot({ path: testInfo.outputPath(`integrated-ledger-${width}.png`), fullPage: true });
    expect(fixture.errors).toEqual([]); expect(fixture.unexpected).toEqual([]);
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
  });

  test(`catalog and primary navigation preserve list state and role boundaries at ${width}px`, async ({ page }, testInfo) => {
    await page.setViewportSize({ width, height: 900 });
    if (width === 390) await page.emulateMedia({ reducedMotion: "reduce" });
    const fixture = await install(page, "data_manager"); await page.goto("/catalog");
    const list = page.getByRole("region", { name: "商品主档列表", exact: true });
    const search = list.getByRole("searchbox", { name: "查找商品", exact: true });
    await search.fill("同名示例商品"); await list.getByRole("button", { name: "批量表格", exact: true }).click();
    const links = list.getByRole("table").locator("tbody tr td:first-child a");
    await expect(links).toHaveCount(2); expect(await links.evaluateAll(elements => elements.map(a => a.getAttribute("href")))).toEqual(["/catalog/styles/700", "/catalog/styles/701"]);
    await links.nth(1).click(); await expect(page).toHaveURL(/\/catalog\/styles\/701$/);
    await expect(page.getByText("系统永久身份 STYLE #701", { exact: false })).toBeVisible();
    await page.getByRole("link", { name: "返回商品主档", exact: true }).click();
    await expect(search).toHaveValue("同名示例商品"); await expect(links).toHaveCount(2);
    await primaryNavigation(page, width, "产品分析"); await expect(page.getByRole("heading", { name: "产品总表", exact: true })).toBeVisible();
    await primaryNavigation(page, width, "商品主档"); await expect(search).toHaveValue("同名示例商品");
    await primaryNavigation(page, width, "版本记录"); await expect(page.getByRole("heading", { name: "版本记录", exact: true })).toBeVisible();
    await page.goBack(); await expect(search).toHaveValue("同名示例商品");
    await page.reload(); await expect(search).toHaveValue(""); // Intentionally scoped to the authorization/session provider, not persisted data.
    if (width === 390) await page.getByRole("button", { name: "打开主导航", exact: true }).click();
    const navigation = page.getByRole("navigation", { name: "工作区", exact: true });
    await expect(navigation.getByRole("link", { name: "数据审核", exact: true })).toBeVisible();
    await expect(navigation.getByRole("link", { name: "管理员控制台", exact: true })).toHaveCount(0);
    if (width === 390) await page.keyboard.press("Escape");
    await page.screenshot({ path: testInfo.outputPath(`integrated-catalog-${width}.png`), fullPage: true });
    expect(fixture.errors).toEqual([]); expect(fixture.unexpected).toEqual([]);
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
  });

  test(`daily ledger and published day preserve filter, history and scoped recovery at ${width}px`, async ({ page }, testInfo) => {
    await page.setViewportSize({ width, height: 900 });
    if (width === 390) await page.emulateMedia({ reducedMotion: "reduce" });
    const fixture = await install(page); await page.goto("/?month=2026-09&status=partial");
    const table = page.getByRole("table", { name: "每日发布记录", exact: true });
    const row = table.getByRole("row").nth(1); await expect(row).toContainText("2026-09-12");
    await row.focus(); await page.keyboard.press("Enter");
    await expect(page.getByRole("heading", { name: "2026-09-12 日期数据工作台", exact: true })).toBeVisible();
    await expect(page.getByRole("region", { name: "单日只读发布详情", exact: true })).toContainText("US$120.25");
    fixture.state.dayFailure = true; await page.reload(); await expect(page.getByRole("alert")).toBeVisible();
    fixture.state.dayFailure = false; await page.getByRole("button", { name: "重新读取", exact: true }).click();
    await expect(page.getByRole("region", { name: "单日只读发布详情", exact: true })).toContainText("报告未发布");
    await page.getByRole("link", { name: "返回总表", exact: true }).click();
    await expect(page).toHaveURL(/month=2026-09.*status=partial/);
    await expect(page.getByRole("combobox", { name: "日期状态", exact: true })).toHaveValue("partial");
    await page.goBack(); await expect(page.getByRole("region", { name: "单日只读发布详情", exact: true })).toBeVisible();
    await page.goForward(); await expect(table.getByRole("row")).toHaveCount(2);
    await primaryNavigation(page, width, "产品分析"); await expect(page.getByRole("heading", { name: "产品总表", exact: true })).toBeVisible();
    await page.goBack(); await expect(page.getByRole("combobox", { name: "日期状态", exact: true })).toHaveValue("partial");
    await page.reload(); await expect(row).toContainText("2026-09-12");
    if (width === 390) await page.getByRole("button", { name: "打开主导航", exact: true }).click();
    const navigation = page.getByRole("navigation", { name: "工作区", exact: true });
    await expect(navigation.getByRole("link", { name: "数据审核", exact: true })).toHaveCount(0);
    await expect(navigation.getByRole("link", { name: "管理员控制台", exact: true })).toHaveCount(0);
    if (width === 390) await page.keyboard.press("Escape");
    await page.screenshot({ path: testInfo.outputPath(`integrated-daily-${width}.png`), fullPage: true });
    expect(fixture.reads.some(url => url.pathname === "/api/dashboard/daily-ledger" && url.searchParams.get("from") === "2026-09-12" && url.searchParams.get("to") === "2026-09-12")).toBe(true);
    expect(fixture.errors).toEqual([]); expect(fixture.unexpected).toEqual([]);
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
  });
}
