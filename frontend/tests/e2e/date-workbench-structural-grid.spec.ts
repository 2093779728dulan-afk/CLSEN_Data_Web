import { expect, test, type Page, type Route } from "@playwright/test";

const reportDate = "2026-08-14";
const reportType = "business_report";

function json(route: Route, payload: unknown, status = 200) {
  return route.fulfill({ body: JSON.stringify(payload), contentType: "application/json", status });
}

function workbenchPage(sortedByTitle = false) {
  const columns = [
    { column_id: "asin", display_order: 0, editable: false, is_key: true, participates_in_statistics: false, source_header: "ASIN", standard_field_name: "asin", value_kind: "text" },
    { column_id: "sku", display_order: 1, editable: false, is_key: true, participates_in_statistics: false, source_header: "卖家 SKU", standard_field_name: "seller_sku", value_kind: "text" },
    { column_id: "title", display_order: 2, editable: true, is_key: false, participates_in_statistics: false, source_header: "商品标题", standard_field_name: "title", value_kind: "text" },
    { column_id: "sales", display_order: 3, editable: true, is_key: false, participates_in_statistics: true, source_header: "销售额", standard_field_name: "ordered_product_sales", value_kind: "decimal" },
    { column_id: "sessions", display_order: 4, editable: true, is_key: false, participates_in_statistics: true, source_header: "访问次数", standard_field_name: "sessions", value_kind: "integer" },
    { column_id: "wide_note", display_order: 5, editable: true, is_key: false, participates_in_statistics: false, source_header: "原始备注字段", standard_field_name: null, value_kind: "text" },
  ];
  const row = (rowId: number, ordinal: number, title: string) => ({
    cells: [
      { base: `B00000${rowId}`, cell_revision: 1, changed: false, column_id: "asin", current: `B00000${rowId}`, editable: false },
      { base: `只读身份字段的超长原始文本 ${rowId}`.repeat(3), cell_revision: 1, changed: false, column_id: "sku", current: `只读身份字段的超长原始文本 ${rowId}`.repeat(3), editable: false },
      { base: title, cell_revision: 1, changed: false, column_id: "title", current: title, editable: true },
      { base: "10.00", cell_revision: 1, changed: false, column_id: "sales", current: "10.00", editable: true },
      { base: 10, cell_revision: 1, changed: false, column_id: "sessions", current: 10, editable: true },
      { base: `不应溢出至相邻单元格的超长原始说明文字 ${rowId}`.repeat(3), cell_revision: 1, changed: false, column_id: "wide_note", current: `不应溢出至相邻单元格的超长原始说明文字 ${rowId}`.repeat(3), editable: true },
    ],
    row_id: rowId,
    row_ordinal: ordinal,
    row_state: "active",
  });
  return {
    actions: [],
    columns,
    head: { data_revision: 1, dataset_id: 21, pointed_at: "2026-08-14T08:00:00Z", review_revision: 1, ruleset_version: "business_report_v1", status: "draft", version_id: 31, version_no: 1 },
    pagination: { page: 1, page_size: 50, total_pages: 1, total_rows: 3 },
    pending_upload_count: 0,
    permissions: { can_create_revision: true, can_edit: true, can_publish: true, can_undo: true, can_upload: true, can_validate: true },
    report_date: reportDate,
    report_type: reportType,
    rows: sortedByTitle
      ? [row(102, 2, "Alpha 浏览器验收商品 102"), row(103, 3, "Bravo 浏览器验收商品 103"), row(101, 1, "Zulu 浏览器验收商品 101")]
      : [row(101, 1, "Zulu 浏览器验收商品 101"), row(102, 2, "Alpha 浏览器验收商品 102"), row(103, 3, "Bravo 浏览器验收商品 103")],
    source: "draft",
    tabs: [
      { dataset_id: 21, report_type: "business_report", source: "draft", status: "draft", version_id: 31 },
      { dataset_id: null, report_type: "return_report", source: "empty", status: null, version_id: null },
    ],
    validation: null,
  };
}

async function installWorkbenchApi(page: Page) {
  await page.route((url) => url.pathname.startsWith("/api/"), async (route) => {
    const method = route.request().method();
    const url = new URL(route.request().url());
    const path = url.pathname;
    if (path === "/api/auth/me" && method === "GET") return json(route, { id: 1, username: "playwright-admin", display_name: "浏览器验收管理员", roles: ["admin"] });
    if (path === "/api/data-calendar/site-context" && method === "GET") return json(route, { site_id: 1, site_code: "amazon_us", display_name: "Amazon US", site_config_version_id: 1, source_timezone: "America/Los_Angeles", reporting_timezone: "America/Los_Angeles", currency_code: "USD" });
    if (path === `/api/workbench/dates/${reportDate}` && method === "GET") return json(route, workbenchPage(url.searchParams.get("sort_column_id") === "title"));
    if (path === "/api/workbench/versions/31/rows/101/cells/sales" && method === "PATCH") return json(route, { cell: { base: "10.00", cell_revision: 2, changed: true, column_id: "sales", current: "11.00" }, change_id: 1, head: { data_revision: 2, dataset_id: 21, pointed_at: "2026-08-14T08:00:00Z", review_revision: 1, status: "draft", version_id: 31 }, operation_token: "playwright" });
    if (path === "/api/data-calendar" && method === "GET") return json(route, []);
    if (path === "/api/data-calendar/days" && method === "GET") return json(route, []);
    return json(route, { error: { code: "unhandled_e2e_route", message: `${method} ${path}`, request_id: "playwright" } }, 500);
  });
}

async function tabTo(page: Page, target: ReturnType<Page["locator"]>, direction: "forward" | "backward" = "forward") {
  for (let step = 0; step < 80; step += 1) {
    await page.keyboard.press(direction === "forward" ? "Tab" : "Shift+Tab");
    if (await target.evaluate((element) => document.activeElement === element)) return;
  }
  throw new Error(`Unable to reach ${await target.getAttribute("aria-label") ?? "target"} with ${direction} Tab navigation.`);
}

async function assertContainedInCell(locator: ReturnType<Page["locator"]>) {
  expect(await locator.evaluate((element) => {
    const cell = element.closest("td");
    if (!cell) return false;
    const elementRect = element.getBoundingClientRect();
    const cellRect = cell.getBoundingClientRect();
    return elementRect.left >= cellRect.left && elementRect.right <= cellRect.right;
  })).toBe(true);
}

async function emulateTwoHundredPercentZoom(page: Page) {
  const before = await page.evaluate(() => ({ devicePixelRatio, innerHeight, innerWidth }));
  for (let step = 0; step < 5; step += 1) await page.keyboard.press("Control+Equal");
  const shortcutMetrics = await page.evaluate(() => ({ devicePixelRatio, innerHeight, innerWidth }));
  const shortcutReachedTwoHundredPercent = shortcutMetrics.devicePixelRatio >= before.devicePixelRatio * 2 || shortcutMetrics.innerWidth <= before.innerWidth / 2;
  if (!shortcutReachedTwoHundredPercent) {
    const session = await page.context().newCDPSession(page);
    await session.send("Emulation.setDeviceMetricsOverride", { deviceScaleFactor: 2, height: Math.floor(before.innerHeight / 2), mobile: false, width: Math.floor(before.innerWidth / 2) });
  }
  const applied = await page.evaluate(() => ({ devicePixelRatio, innerHeight, innerWidth }));
  expect(applied.devicePixelRatio >= before.devicePixelRatio * 2).toBe(true);
  expect(applied.innerWidth <= before.innerWidth / 2).toBe(true);
}

async function openWorkbench(page: Page, width: number) {
  await page.setViewportSize({ width, height: 900 });
  await installWorkbenchApi(page);
  await page.goto(`/review/${reportDate}?report_type=${reportType}`);
  await expect(page.getByRole("table", { name: /经营报告原始数据/ })).toBeVisible();
}

for (const width of [1280, 768, 390]) {
  test(`contains the wide grid at ${width}px`, async ({ page }) => {
    await openWorkbench(page, width);
    expect(await page.locator("body").evaluate((body) => body.scrollWidth <= body.clientWidth)).toBe(true);
    const grid = page.getByRole("table", { name: "经营报告原始数据" }).locator("..");
    if (width < 1280) {
      expect(await grid.evaluate((element) => element.scrollWidth > element.clientWidth)).toBe(true);
      expect(await grid.evaluate((element) => { element.scrollLeft = 120; return element.scrollLeft > 0; })).toBe(true);
    }
  });
}

test("keeps resize, settings, sort, edit, focus, and 200% zoom usable from the keyboard", async ({ page }) => {
  await openWorkbench(page, 1280);
  const table = page.getByRole("table", { name: "经营报告原始数据" });
  const resizer = page.getByRole("button", { name: "调整“销售额”列宽" });
  await tabTo(page, resizer);
  await expect(resizer).toBeFocused();
  expect(await resizer.evaluate((element) => getComputedStyle(element).outlineStyle !== "none")).toBe(true);
  const header = page.getByRole("columnheader", { name: /销售额/ });
  const widthBefore = await header.evaluate((element) => element.getBoundingClientRect().width);
  await resizer.press("ArrowRight");
  expect(await header.evaluate((element) => element.getBoundingClientRect().width)).toBeGreaterThan(widthBefore);

  const settings = page.getByRole("button", { name: "列设置" });
  await tabTo(page, settings, "backward");
  await expect(settings).toBeFocused();
  await settings.press("Enter");
  await expect(page.getByRole("region", { name: "列设置" })).toBeVisible();
  const salesVisibility = page.getByRole("checkbox", { name: "销售额" });
  await tabTo(page, salesVisibility);
  await salesVisibility.press("Space");
  await expect(page.getByRole("columnheader", { name: /销售额/ })).toHaveCount(0);
  await salesVisibility.press("Space");
  await expect(page.getByRole("columnheader", { name: /销售额/ })).toHaveCount(1);
  const closeSettings = page.getByRole("button", { name: "关闭列设置" });
  await tabTo(page, closeSettings, "backward");
  await closeSettings.press("Enter");
  await expect(settings).toBeFocused();

  const sort = page.getByRole("button", { name: "按 商品标题 排序" });
  await tabTo(page, sort);
  await sort.press("Enter");
  await expect(page).toHaveURL(/sort_column_id=title/);
  await expect(table.locator("tbody tr").first().getByRole("textbox").first()).toHaveValue("Alpha 浏览器验收商品 102");

  const editor = page.getByLabel("商品标题，第 2 行");
  await tabTo(page, editor);
  await expect(editor).toBeFocused();
  expect(await editor.evaluate((element) => {
    const probe = document.createElement("span");
    probe.style.color = getComputedStyle(element).getPropertyValue("--color-focus");
    document.body.append(probe);
    const focusColor = getComputedStyle(probe).color;
    probe.remove();
    return getComputedStyle(element).borderColor === focusColor;
  })).toBe(true);
  await editor.fill("临时键盘修改");
  await editor.press("Escape");
  await expect(editor).toHaveValue("Alpha 浏览器验收商品 102");

  await emulateTwoHundredPercentZoom(page);
  const lastRow = table.locator("tbody tr").last();
  await lastRow.scrollIntoViewIfNeeded();
  await expect(lastRow).toBeVisible();
  const [lastRowBox, actionBarBox] = await Promise.all([
    lastRow.boundingBox(),
    page.getByRole("button", { name: "前往发布" }).locator("../..").boundingBox(),
  ]);
  expect(lastRowBox && actionBarBox && lastRowBox.y + lastRowBox.height <= actionBarBox.y).toBe(true);
  expect(await page.locator("body").evaluate((body) => body.scrollWidth <= body.clientWidth)).toBe(true);
  await assertContainedInCell(table.getByText("B00000101", { exact: true }));
  await assertContainedInCell(table.locator("td input").last());
});
