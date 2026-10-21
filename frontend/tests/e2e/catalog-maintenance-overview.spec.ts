import { expect, test } from "@playwright/test";

for (const width of [1280, 390]) {
  test(`actual maintenance overview, prepared-state boundary, navigation and refresh at ${width}px`, async ({ page }, testInfo) => {
    await page.setViewportSize({ width, height: 900 });
    let initialized = true; let prepared = false;
    let release: () => void = () => undefined;
    let gate: Promise<void> | undefined = new Promise<void>(resolve => { release = resolve; });
    const requests: Array<{ path: string; method: string }> = [];
    await page.route(/^https?:\/\/[^/]+\/api\//, async route => {
      const path = new URL(route.request().url()).pathname; const method = route.request().method(); requests.push({ path, method });
      if (method !== "GET") throw new Error(`Unexpected write ${path}`);
      if (path === "/api/auth/me") return route.fulfill({ json: { id: 88, username: "fictional-overview-reader", display_name: "虚构维护账号", roles: ["data_manager"] } });
      if (path === "/api/data-calendar/site-context") return route.fulfill({ json: { site_id: 1, site_code: "US", display_name: "虚构站点", site_config_version_id: 2, source_timezone: "UTC", reporting_timezone: "UTC", currency_code: "USD" } });
      if (path === "/api/catalog/styles") { if (gate) await gate; return route.fulfill({ json: { catalog: initialized ? { catalog_version_id: 104, version_number: 4, catalog_publication_revision: 7, styles: [], skus: [] } : null } }); }
      if (path === "/api/catalog/versions") return route.fulfill({ json: { versions: [{ id: 104, version_number: 4, risk: "normal", approved_at: "2026-09-30", base_catalog_version_id: 103 }] } });
      if (path === "/api/catalog/imports") return route.fulfill({ json: { items: [], has_next: false } });
      if (path === "/api/catalog/exports/latest") return route.fulfill({ json: { export: null } });
      if (path === "/api/dashboard/style-readiness") return route.fulfill({ json: { published_reports: 2, published_business_reports: 1, published_return_reports: 1, source_scope_confirmed: prepared, return_snapshot_present: prepared, catalog_approved: initialized, prerequisites_present: initialized && prepared, coverage_from: "2026-09-01", coverage_to: "2026-09-30" } });
      if (path === "/api/catalog/source-scope") return route.fulfill({ json: { marketplace_scope_code: "amazon_us", permissions: { can_confirm: false }, report_source_scope_id: 1, seller_account_display_name: "虚构账号", site_config_revision: 3, site_config_version_id: 2, status: prepared ? "confirmed" : "unconfirmed" } });
      throw new Error(`Unexpected API ${path}`);
    });
    const url = "/catalog/maintenance?return_to=%2Fcatalog%2Funmatched%3Fpage%3D2";
    await page.goto(url); await expect(page.getByRole("status").filter({ hasText: "正在读取批量维护" })).toBeVisible(); release(); gate = undefined;
    const panel = page.getByRole("region", { name: "批量维护总览", exact: true }); await expect(panel.getByText("#104", { exact: true })).toBeVisible(); await expect(panel).toContainText("已生效 V4");
    const generate = page.getByRole("region", { name: "目录工作簿", exact: true }).getByRole("button", { name: "生成候选", exact: true }); await expect(generate).toBeDisabled();
    await expect(page.getByRole("region", { name: "商品分析初始化", exact: true })).toContainText("待管理员确认");
    const products = panel.getByRole("link", { name: "查看已生效商品", exact: true }); await products.focus(); await products.press("Enter"); await expect(page).toHaveURL(/\/catalog$/); await expect(page.getByRole("heading", { name: "当前主档尚无商品", exact: true })).toBeVisible(); await page.goBack(); await expect(panel).toBeVisible();
    await panel.getByRole("link", { name: "查看批准记录", exact: true }).click(); await expect(page.getByRole("table", { name: "已批准目录记录" })).toContainText("目录记录 #104"); await page.goBack(); await expect(page).toHaveURL(new RegExp(url.replaceAll("?", "\\?"))); await expect(generate).toBeDisabled();
    await page.reload(); await expect(panel).toContainText("已生效 V4");
    prepared = true; await page.getByRole("button", { name: "刷新准备状态", exact: true }).click(); await expect(generate).toBeEnabled(); await expect(panel).toContainText("已生效目录不代表新的来源资料已就绪");
    await panel.screenshot({ path: testInfo.outputPath(`actual-overview-${width}.png`) });
    initialized = false; prepared = false; await page.reload(); await expect(panel).toContainText("尚未初始化"); await expect(page.getByRole("region", { name: "首个目录前置", exact: true })).toContainText("先在每日核验中导入、审核并发布来源报告"); await expect(generate).toBeDisabled(); await expect(panel.getByRole("link", { name: "返回每日数据查看发布情况", exact: true })).toHaveAttribute("href", "/");
    await page.reload(); await expect(panel).toContainText("尚未初始化"); await expect(panel.getByRole("link", { name: "查看已生效商品", exact: true })).toHaveCount(0);
    expect(requests.filter(request => request.method !== "GET")).toEqual([]); expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
  });
}
