import { expect, test } from "@playwright/test";
import { ledgerCategories, ledgerFixture } from "../../src/features/products/ProductLedgerView.fixtures";

for (const width of [1280, 390]) test(`actual ledger URL filters, sort failure recovery, pages and identity at ${width}px`, async ({ page }) => {
  await page.setViewportSize({ width, height: 900 }); const state = { fail: false, hold: false }; let release: (() => void) | undefined;
  const calls: URL[] = []; const unexpected: string[] = []; const errors: string[] = []; page.on("pageerror", e => errors.push(e.message));
  await page.route(url => url.pathname.startsWith("/api/"), async route => {
    const r = route.request(); const url = new URL(r.url()); const path = url.pathname;
    if (r.method() !== "GET") { unexpected.push(`${r.method()} ${path}`); return route.fulfill({ status: 405 }); }
    if (path === "/api/auth/me") return route.fulfill({ json: { id: 88, username: "demo-viewer", display_name: "示例查看人员", roles: ["viewer"] } });
    if (path === "/api/data-calendar/site-context") return route.fulfill({ json: { site_id: 1, site_code: "US", display_name: "示例美国站点", site_config_version_id: 2, source_timezone: "America/Los_Angeles", reporting_timezone: "America/Los_Angeles", currency_code: "USD" } });
    if (path === "/api/catalog/categories") return route.fulfill({ json: { categories: ledgerCategories } });
    if (path === "/api/dashboard/style-ledger") {
      calls.push(url); if (state.hold) await new Promise<void>(resolve => { release = resolve; });
      if (state.fail) return route.fulfill({ status: 503, json: { error: { code: "synthetic_failure", message: "示例读取失败" } } });
      const data = ledgerFixture(); const q = url.searchParams;
      const rows = Array.from({ length: 26 }, (_, i) => ({ ...structuredClone(data.rows[0]!), style_id: String(501 + i), style_code: i ? `DEMO-${i + 1}` : "10001" }));
      const filtered = q.get("search") ? rows.filter(row => row.style_code.includes(q.get("search")!)) : rows;
      data.page = Number(q.get("page") ?? 1); data.page_size = Number(q.get("page_size") ?? 50); data.total_rows = filtered.length; data.rows = filtered.slice((data.page - 1) * data.page_size, data.page * data.page_size);
      data.sort = (q.get("sort") ?? "units") as typeof data.sort; data.direction = (q.get("direction") ?? "desc") as typeof data.direction;
      data.filtered_sales_total = (filtered.length * 120).toFixed(2); data.provenance.fact_basis = q.get("fact_basis") as typeof data.provenance.fact_basis;
      const totals = { units: 52, sales: "3120.00", sessions: 260, returns: 0, conversion_numerator: 52, conversion_denominator: 260 };
      data.reconciliation.source_totals = totals; data.reconciliation.mapped_totals = totals;
      return route.fulfill({ json: data });
    }
    unexpected.push(`${r.method()} ${path}`); return route.fulfill({ status: 500, json: {} });
  });
  await page.goto("/products?from=2026-07-25&to=2026-08-24");
  const table = page.getByRole("table", { name: "稳定款式指标", exact: true }); await expect(table).toBeVisible();
  const coverage = page.getByRole("region", { name: "六桶指标对账", exact: true });
  await expect(coverage.locator("tbody tr").first().locator("td")).toHaveText(["52", "3,120.00", "0", "260", "52/260"]);
  const reportHeading = (await page.getByRole("heading", { name: "经营报表", exact: true }).boundingBox())!;
  const reportRate = (await page.getByText("报表覆盖比率", { exact: true }).first().boundingBox())!;
  expect(reportRate.y).toBeGreaterThanOrEqual(reportHeading.y + reportHeading.height);
  await page.getByRole("combobox", { name: "筛选主分类", exact: true }).selectOption("1"); await page.getByRole("combobox", { name: "筛选细分类", exact: true }).selectOption("2"); await expect(page).toHaveURL(/category_id=2/);
  await page.getByRole("checkbox", { name: "显示商品名称", exact: true }).check(); const trigger = page.getByRole("button", { name: "查看款号 10001 商品信息", exact: true }); await expect(trigger).toContainText("标准轻量夹克");
  await page.getByRole("combobox", { name: "每页", exact: true }).selectOption("25"); await page.getByRole("button", { name: "下一页", exact: true }).click(); await expect(page).toHaveURL(/page=2/); await expect(page.getByRole("button", { name: "查看款号 DEMO-26 商品信息", exact: true })).toBeVisible();
  await page.getByRole("textbox", { name: "款号或标准名称", exact: true }).fill("10001"); await page.getByRole("button", { name: "应用筛选", exact: true }).click(); await expect(page).toHaveURL(/search=10001/); await expect(page).toHaveURL(/page=1/); await expect(trigger).toBeVisible();
  state.hold = true; await page.getByRole("button", { name: "销售贡献", exact: true }).click(); await expect(page.locator("table[aria-label='稳定款式指标']")).toHaveAttribute("inert", "");
  state.fail = true; state.hold = false; release?.(); await expect(page.getByRole("alert")).toContainText("产品总表读取失败"); await expect(trigger).toHaveCount(0);
  state.fail = false; await page.getByRole("button", { name: "按原条件重试", exact: true }).click(); await expect(trigger).toBeVisible(); await expect(page).toHaveURL(/sort=sales/);
  await page.getByRole("combobox", { name: "退货日期", exact: true }).selectOption("report_date"); await page.getByRole("combobox", { name: "事实版本", exact: true }).selectOption("catalog_snapshot"); await expect(page).toHaveURL(/return_basis=report_date/); await expect(page).toHaveURL(/fact_basis=catalog_snapshot/);
  await page.reload(); await expect(trigger).toBeVisible(); await expect(page.getByRole("combobox", { name: "筛选细分类", exact: true })).toHaveValue("2"); await expect(page.getByRole("textbox", { name: "款号或标准名称", exact: true })).toHaveValue("10001");
  await expect(coverage.locator("tbody tr").first().locator("td")).toHaveText(["52", "3,120.00", "0", "260", "52/260"]);
  const help = page.getByRole("button", { name: "本期退货量与同期退销比说明", exact: true }); await help.click();
  await expect(page.getByRole("dialog")).toContainText("退货按报表日期筛选"); await expect(page.getByRole("dialog")).toContainText("目录快照");
  await page.keyboard.press("Escape"); await expect(help).toBeFocused();
  await trigger.click(); await expect(page.getByRole("link", { name: "进入款式详情" })).toHaveAttribute("href", /\/products\/501\?.*return_basis=report_date&fact_basis=catalog_snapshot/); await page.keyboard.press("Escape"); await expect(trigger).toBeFocused();
  expect(calls.at(-1)?.searchParams.get("search")).toBe("10001"); expect(unexpected).toEqual([]); expect(errors).toEqual([]); expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
});
