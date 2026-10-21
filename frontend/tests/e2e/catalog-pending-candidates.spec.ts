import { expect, test } from "@playwright/test";

for (const width of [1280, 390]) {
  test(`candidate panel preserves review return, recovery and permission at ${width}px`, async ({ page }, testInfo) => {
    await page.setViewportSize({ width, height: 900 });
    const mode = { failure: true, empty: false, review: true };
    const requests: Array<{ path: string; method: string }> = [];
    await page.route(/^https?:\/\/[^/]+\/api\//, async route => {
      const path = new URL(route.request().url()).pathname;
      const method = route.request().method();
      requests.push({ path, method });
      if (method !== "GET") throw new Error(`Unexpected write ${method} ${path}`);
      if (path === "/api/auth/me") return route.fulfill({ json: { id: 88, username: "fictional-pending-reader", display_name: "虚构候选账号", roles: [mode.review ? "data_manager" : "viewer"] } });
      if (path === "/api/data-calendar/site-context") return route.fulfill({ json: { site_id: 1, site_code: "US", display_name: "虚构站点", site_config_version_id: 2, source_timezone: "UTC", reporting_timezone: "UTC", currency_code: "USD" } });
      if (path === "/api/dashboard/style-readiness") return route.fulfill({ json: { published_reports: 2, prerequisites_present: true, catalog_approved: true } });
      if (path === "/api/catalog/styles/1001") return route.fulfill({ json: {
        catalog_version_id: 4, catalog_publication_revision: 7,
        permissions: { can_edit: false, can_manage_categories: false },
        style: { style_id: 1001, style_code: "DEMO-01", standard_name: "虚构商品", category_id: null, category_code: null, category_name: null, category_recorded: true, status: "enabled", revision: 3, variant_count: 0, seller_sku_count: 0, source_summary: { first_seen_date: null, latest_seen_date: null, observation_count: 0, source_report_count: 0 } }, skus: [],
      } });
      if (path === "/api/catalog/styles/1001/pending-items") {
        if (mode.failure) return route.fulfill({ status: 503, json: { error: { code: "UNAVAILABLE" } } });
        return route.fulfill({ json: { items: mode.empty ? [] : [{ import_id: 42, review_path: "/catalog/imports/42", seller_sku_count: 2, seller_sku_previews: ["DEMO-NAVY-L", "DEMO-BLUE-M"], status: "needs_attention", updated_at: "2099-01-01", variant_count: 1, workflow_revision: 3 }], permissions: { can_review: mode.review } } });
      }
      if (path === "/api/catalog/imports/42") return route.fulfill({ json: {
        import_id: 42, workflow_revision: 3, catalog_publication_revision: 7, base_catalog_version_id: 4, export_id: 8001, parse_attempt_revision: 1, source_kind: "online", status: "needs_attention", issues: [], failure_reason_code: null, has_original_file: false, submitted_by_user_id: 88, validation_run_id: null,
        permissions: { can_view: true, can_edit: false, can_preview: false, can_approve_normal: false, can_approve_high_risk: false, can_rebase: false, can_reject: false, can_withdraw: false, can_resume: false, can_validate: false, can_submit: false, can_download_original: false },
      } });
      if (path.startsWith("/api/catalog/imports/42/rows/")) return route.fulfill({ json: { rows: [], total_rows: 0, workflow_revision: 3 } });
      throw new Error(`Unexpected API ${path}`);
    });
    await page.goto("/catalog/styles/1001");
    await expect(page.getByRole("alert")).toBeVisible();
    mode.failure = false;
    await page.getByRole("button", { name: "重新读取商品", exact: true }).click();
    const panel = page.getByRole("region", { name: "新变体与 Seller SKU 候选", exact: true });
    const batch = panel.getByRole("listitem", { name: "审核批次 #42", exact: true });
    await expect(batch.getByText("DEMO-NAVY-L", { exact: true })).toBeVisible();
    await expect(batch).toContainText("审核修订 3");
    await panel.screenshot({ path: testInfo.outputPath(`actual-panel-${width}.png`) });
    await batch.getByRole("link", { name: "进入审核", exact: true }).click();
    await expect(page).toHaveURL(/\/catalog\/imports\/42$/);
    const back = page.getByRole("link", { name: "返回来源页面", exact: true });
    await expect(back).toHaveAttribute("href", "/catalog/styles/1001");
    await back.click();
    await expect(batch).toBeVisible();
    await page.reload();
    await expect(batch).toBeVisible();
    mode.empty = true;
    await page.getByRole("button", { name: "刷新商品详情", exact: true }).click();
    await expect(panel).toHaveCount(0);
    mode.empty = false;
    await page.getByRole("button", { name: "刷新商品详情", exact: true }).click();
    await expect(batch).toBeVisible();
    mode.review = false;
    await page.reload();
    await expect(panel.getByText("由数据管理员确认", { exact: true })).toBeVisible();
    await expect(panel.getByRole("link", { name: "进入审核", exact: true })).toHaveCount(0);
    await expect(panel.getByText("DEMO-BLUE-M", { exact: true })).toBeVisible();
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
    expect(requests.filter(request => request.method !== "GET")).toEqual([]);
  });
}
