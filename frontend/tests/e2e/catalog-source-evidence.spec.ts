import { expect, test } from "@playwright/test";

for (const width of [1280, 390]) {
  test(`actual evidence retry, scoped reveal, copy, revision clearing and reload at ${width}px`, async ({ page, context }, testInfo) => {
    await context.grantPermissions(["clipboard-read", "clipboard-write"]);
    await page.setViewportSize({ width, height: 900 });
    let revision = 3; let listFailure = true; let revealReads = 0; let writes = 0;
    await page.route(url => url.pathname.startsWith("/api/"), async route => {
      const req = route.request(); const url = new URL(req.url()); const path = url.pathname;
      if (req.method() !== "GET") { writes++; throw new Error("Unexpected fixture write"); }
      if (path === "/api/auth/me") return route.fulfill({ json: { id: 88, username: "fictional-evidence-manager", display_name: "虚构管理账号", roles: ["data_manager"] } });
      if (path === "/api/data-calendar/site-context") return route.fulfill({ json: { site_id: 1, site_code: "US", display_name: "虚构站点", site_config_version_id: 2, source_timezone: "UTC", reporting_timezone: "UTC", currency_code: "USD" } });
      if (path === "/api/dashboard/style-readiness") return route.fulfill({ json: { published_reports: 0, prerequisites_present: false } });
      if (path === "/api/catalog/imports/42") return route.fulfill({ json: { import_id: 42, workflow_revision: revision, catalog_publication_revision: 7, base_catalog_version_id: 4, export_id: 8001, parse_attempt_revision: 1, source_kind: "online", status: "needs_attention", failure_reason_code: null, has_original_file: false, submitted_by_user_id: 88, validation_run_id: null, permissions: { can_view: true, can_edit: true, can_preview: false, can_approve_normal: false, can_approve_high_risk: false, can_rebase: false, can_reject: false, can_withdraw: false, can_resume: false, can_validate: false, can_submit: false, can_download_original: false } } });
      if (path.includes("/rows/")) return route.fulfill({ json: { rows: [], total_rows: 0, workflow_revision: revision } });
      if (path === "/api/catalog/evidence") {
        expect(url.searchParams.get("import_id")).toBe("42"); expect(url.searchParams.get("page_size")).toBe("50");
        if (listFailure) return route.fulfill({ status: 503, json: { error: { code: "UNAVAILABLE", message: "虚构来源列表读取失败" } } });
        return route.fulfill({ json: { items: [{ source_ref_id: "3", preview: "DEMO-SAFE-SOURCE", digest: `sha256:${"c".repeat(64)}`, is_truncated: true, is_unsafe: false }] } });
      }
      if (path === "/api/catalog/imports/42/source-identifiers/3") {
        expect(url.searchParams.get("workflow_revision")).toBe(String(revision)); revealReads++;
        if (revealReads === 1) return route.fulfill({ status: 403, json: { error: { code: "catalog_source_identifier_forbidden", message: "虚构完整标识权限未通过" } } });
        return route.fulfill({ json: { code_points: "U+0044", utf8_base64url: "REVNTy1SRVZFQUwtT05MWQ" } });
      }
      throw new Error(`Unexpected fictional read: ${path}`);
    });
    await page.goto("/catalog/imports/42"); await expect(page.getByRole("heading", { name: "商品主档审核", exact: true })).toBeVisible();
    await page.getByRole("tab", { name: /^来源证据/ }).click();
    const panel = page.getByRole("region", { name: "安全来源证据", exact: true });
    await expect(panel.getByRole("alert")).toContainText("虚构来源列表读取失败"); listFailure = false; await panel.getByRole("button", { name: "重新读取来源", exact: true }).click();
    const row = panel.getByRole("listitem", { name: "来源 3", exact: true }); await expect(row).toContainText("DEMO-SAFE-SOURCE");
    await expect(row.locator("output")).toHaveCount(0); expect(revealReads).toBe(0);
    await row.getByRole("button", { name: "查看完整标识", exact: true }).click(); await expect(row.getByRole("alert")).toContainText("权限未通过"); await expect(row.locator("output")).toHaveCount(0);
    await row.getByRole("button", { name: "查看完整标识", exact: true }).click(); await expect(row.locator("output")).toHaveText("DEMO-REVEAL-ONLY");
    await row.getByRole("button", { name: "复制完整标识", exact: true }).click(); await expect(row.getByText("已复制到剪贴板", { exact: true })).toBeVisible();
    expect(await page.evaluate(() => navigator.clipboard.readText())).toBe("DEMO-REVEAL-ONLY");
    await panel.screenshot({ path: testInfo.outputPath(`evidence-${width}.png`) });
    revision = 4; await page.getByRole("button", { name: "重新读取草稿", exact: true }).click(); await expect(page.getByText("当前修订 4", { exact: true })).toBeVisible(); await expect(panel.locator("output")).toHaveCount(0);
    await row.getByRole("button", { name: "查看完整标识", exact: true }).click(); await expect(row.locator("output")).toHaveText("DEMO-REVEAL-ONLY");
    await row.getByRole("button", { name: "隐藏完整标识", exact: true }).click(); await expect(row.locator("output")).toHaveCount(0);
    await page.reload(); await page.getByRole("tab", { name: /^来源证据/ }).click(); await expect(row).toContainText("DEMO-SAFE-SOURCE"); await expect(panel.locator("output")).toHaveCount(0);
    expect(writes).toBe(0); expect(revealReads).toBe(3); expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
  });
}
