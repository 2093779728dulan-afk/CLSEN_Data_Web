import { expect, test } from "@playwright/test";
for (const width of [1280, 390]) {
  test(`actual history read recovery, page recovery, batch return and refresh at ${width}px`, async ({ page }, testInfo) => {
    await page.setViewportSize({ width, height: 900 }); let listFailure = true; let secondFailure = true; let writes = 0; const pages: number[] = [];
    await page.route(url => url.pathname.startsWith("/api/"), async route => {
      const req = route.request(); const url = new URL(req.url()); const path = url.pathname;
      if (req.method() !== "GET") { writes++; throw new Error(`Unexpected fictional write: ${path}`); }
      if (path === "/api/auth/me") return route.fulfill({ json: { id: 88, username: "fictional-history-manager", display_name: "虚构管理账号", roles: ["data_manager"] } });
      if (path === "/api/data-calendar/site-context") return route.fulfill({ json: { site_id: 1, site_code: "US", display_name: "虚构站点", site_config_version_id: 2, source_timezone: "UTC", reporting_timezone: "UTC", currency_code: "USD" } });
      if (path === "/api/catalog/styles") return route.fulfill({ json: { catalog: { catalog_version_id: 4, catalog_publication_revision: 7, version_number: 4, approved_at: "2099-01-01", category_required: false }, styles: [] } });
      if (path === "/api/catalog/exports/latest") return route.fulfill({ json: { export: null } });
      if (path === "/api/dashboard/style-readiness") return route.fulfill({ json: { published_reports: 2, published_business_reports: 1, published_return_reports: 1, return_snapshot_present: true, catalog_approved: true, source_scope_confirmed: true, prerequisites_present: true } });
      if (path === "/api/catalog/source-scope") return route.fulfill({ json: { marketplace_scope_code: "amazon_us", permissions: { can_confirm: false }, report_source_scope_id: 1, seller_account_display_name: "虚构账号", site_config_revision: 3, site_config_version_id: 2, status: "confirmed" } });
      if (path === "/api/catalog/imports") {
        const currentPage = Number(url.searchParams.get("page")); pages.push(currentPage);
        if (listFailure || currentPage === 2 && secondFailure) return route.fulfill({ status: 503, json: { error: { code: "UNAVAILABLE", message: "虚构示例：批次暂时不可用" } } });
        return route.fulfill({ json: { items: [{ import_id: currentPage === 1 ? 42 : 43, source_kind: currentPage === 1 ? "xlsx" : "online", status: currentPage === 1 ? "needs_attention" : "approved", workflow_revision: currentPage === 1 ? 3 : 6 }], has_next: currentPage === 1 } });
      }
      if (/^\/api\/catalog\/imports\/(42|43)$/.test(path)) return route.fulfill({ json: { import_id: Number(path.split("/").at(-1)), workflow_revision: path.endsWith("43") ? 6 : 3, catalog_publication_revision: 7, export_id: 8001, base_catalog_version_id: 4, parse_attempt_revision: 1, source_kind: path.endsWith("43") ? "online" : "xlsx", status: path.endsWith("43") ? "approved" : "needs_attention", approved_catalog_version_number: path.endsWith("43") ? 5 : null, issues: [], failure_reason_code: null, has_original_file: false, submitted_by_user_id: 88, validation_run_id: 1, permissions: { can_view: true, can_edit: false, can_preview: false, can_approve_normal: false, can_approve_high_risk: false, can_rebase: false, can_reject: false, can_withdraw: false, can_resume: false, can_validate: false, can_submit: false, can_download_original: false } } });
      if (/^\/api\/catalog\/imports\/(42|43)\/rows\//.test(path)) return route.fulfill({ json: { rows: [], total_rows: 0, workflow_revision: path.includes("43") ? 6 : 3 } });
      throw new Error(`Unexpected fictional request: ${path}`);
    });
    await page.goto("/catalog/maintenance"); const panel = page.getByRole("region", { name: "已有审核批次", exact: true }); await expect(panel.getByRole("alert")).toContainText("虚构示例：批次暂时不可用");
    listFailure = false; await panel.getByRole("button", { name: "刷新批次", exact: true }).click(); await expect(panel.getByRole("link", { name: "批次 #42 · 继续审核", exact: true })).toBeVisible();
    await panel.screenshot({ path: testInfo.outputPath(`history-${width}.png`) }); await panel.getByRole("link", { name: "批次 #42 · 继续审核", exact: true }).click(); await expect(page).toHaveURL(/\/catalog\/imports\/42$/); await expect(page.getByText("当前修订 3", { exact: true })).toBeVisible();
    await page.getByRole("link", { name: "返回来源页面", exact: true }).click(); await expect(page).toHaveURL(/\/catalog\/maintenance$/); await expect(panel.getByText("第 1 页", { exact: true })).toBeVisible();
    await panel.getByRole("button", { name: "下一页", exact: true }).click(); await expect(panel.getByRole("alert")).toBeVisible(); await expect(panel.getByRole("link", { name: /^批次/ })).toHaveCount(0);
    secondFailure = false; await panel.getByRole("button", { name: "刷新批次", exact: true }).click(); await expect(panel.getByText("第 2 页", { exact: true })).toBeVisible(); await expect(panel.getByRole("button", { name: "下一页", exact: true })).toBeDisabled();
    await panel.getByRole("link", { name: "批次 #43 · 查看批准结果", exact: true }).click(); await expect(page).toHaveURL(/\/catalog\/imports\/43$/); await page.reload(); await expect(page.getByText("修订 6", { exact: true })).toBeVisible(); await expect(page.getByRole("region", { name: "目录批准结果", exact: true })).toContainText("目录版本 V5 已生成"); await expect(page.getByText("已批准生效，本页展示批次记录", { exact: true })).toBeVisible();
    await expect(page.getByRole("link", { name: "返回来源页面", exact: true })).toHaveAttribute("href", "/catalog/maintenance"); await page.getByRole("link", { name: "返回来源页面", exact: true }).click(); await page.reload(); await expect(panel.getByText("第 1 页", { exact: true })).toBeVisible();
    expect(pages).toContain(1); expect(pages).toContain(2); expect(writes).toBe(0); expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
  });
}
