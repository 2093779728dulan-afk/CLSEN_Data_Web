import { expect, test } from "@playwright/test";
import type { CatalogExportStatus } from "../../src/features/catalog/catalogApi";

for (const width of [1280, 390]) {
  test(`actual workbook generate, recover, review, upload retry and refresh at ${width}px`, async ({ page, context, baseURL }, testInfo) => {
    await page.setViewportSize({ width, height: 900 }); await context.addCookies([{ name: "clsen_csrf", url: baseURL!, value: "fictional-workbook-csrf" }]);
    const ready: CatalogExportStatus = { export_id: 8001, base_catalog_version_id: 4, catalog_publication_revision: 7, export_status: "ready", job_status: "succeeded", job_revision: 3, execution_phase: "completed", attempt_count: 2, max_attempts: 3, next_attempt_at: null, retry_allowed: false, worker_available: true, workbook_status: "ready", permissions: { can_download: true, can_resume: false }, capacity_violations: [], failure_reason_code: null };
    let exported: typeof ready | undefined; let uploads = 0; const uploadKeys: string[] = []; const commands: string[] = [];
    await page.route(url => url.pathname.startsWith("/api/"), async route => {
      const req = route.request(); const path = new URL(req.url()).pathname;
      if (req.method() === "POST") {
        expect(req.headers()["x-csrf-token"]).toBe("fictional-workbook-csrf"); const key = req.headers()["idempotency-key"]!; expect(key).toMatch(/^[0-9a-f-]{36}$/); commands.push(path);
        if (path === "/api/catalog/imports") {
          expect(req.headers()["content-type"]).toBe("application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"); expect(decodeURIComponent(req.headers()["x-original-filename"]!)).toBe("fictional-revised.xlsx"); expect(req.postData()).toBe("fictional workbook bytes"); uploadKeys.push(key);
          if (uploads++ === 0) return route.fulfill({ status: 400, json: { error: { code: "catalog_workbook_unsafe" } } });
          return route.fulfill({ json: { catalog_import_id: 43 } });
        }
        const body = req.postDataJSON() as Record<string, unknown>; expect(body.operation_token).toBe(key);
        if (path === "/api/catalog/exports") { expect(body.expected_catalog_publication_revision).toBe(7); exported = { ...ready, job_status: "failed", job_revision: 2, export_status: "failed", execution_phase: "awaiting_manual_recovery", workbook_status: "ready", permissions: { can_download: false, can_resume: true }, failure_reason_code: "fictional_worker_failure" }; return route.fulfill({ json: exported }); }
        if (path === "/api/catalog/exports/8001/resume") { expect(body.expected_job_revision).toBe(2); exported = ready; return route.fulfill({ json: { export_id: 8001, job_revision: 3, job_status: "succeeded" } }); }
        if (path === "/api/catalog/imports/from-export") { expect(body.export_id).toBe(8001); expect(body.expected_catalog_publication_revision).toBe(7); return route.fulfill({ json: { import_id: 42 } }); }
        throw new Error(`Unexpected fictional write: ${path}`);
      }
      if (path === "/api/auth/me") return route.fulfill({ json: { id: 88, username: "fictional-workbook-manager", display_name: "虚构维护账号", roles: ["data_manager"] } });
      if (path === "/api/data-calendar/site-context") return route.fulfill({ json: { site_id: 1, site_code: "US", display_name: "虚构站点", site_config_version_id: 2, source_timezone: "UTC", reporting_timezone: "UTC", currency_code: "USD" } });
      if (path === "/api/catalog/styles") return route.fulfill({ json: { catalog: { catalog_version_id: 4, catalog_publication_revision: 7, version_number: 4, approved_at: "2099-01-01", category_required: false }, styles: [] } });
      if (path === "/api/catalog/imports") return route.fulfill({ json: { items: [], has_next: false } });
      if (path === "/api/catalog/exports/latest") return route.fulfill({ json: { export: exported ?? null } });
      if (path === "/api/catalog/exports/8001") return route.fulfill({ json: exported });
      if (path === "/api/dashboard/style-readiness") return route.fulfill({ json: { published_reports: 2, published_business_reports: 1, published_return_reports: 1, return_snapshot_present: true, catalog_approved: true, source_scope_confirmed: true, prerequisites_present: true } });
      if (path === "/api/catalog/source-scope") return route.fulfill({ json: { marketplace_scope_code: "amazon_us", permissions: { can_confirm: false }, report_source_scope_id: 1, seller_account_display_name: "虚构账号", site_config_revision: 3, site_config_version_id: 2, status: "confirmed" } });
      if (/^\/api\/catalog\/imports\/(42|43)$/.test(path)) return route.fulfill({ json: { import_id: Number(path.split("/").at(-1)), workflow_revision: 3, catalog_publication_revision: 7, export_id: 8001, base_catalog_version_id: 4, parse_attempt_revision: 1, source_kind: path.endsWith("43") ? "xlsx" : "online", status: "validated", issues: [], failure_reason_code: null, has_original_file: false, submitted_by_user_id: 88, validation_run_id: 1, permissions: { can_view: true, can_edit: false, can_preview: false, can_approve_normal: false, can_approve_high_risk: false, can_rebase: false, can_reject: false, can_withdraw: false, can_resume: false, can_validate: false, can_submit: false, can_download_original: false } } });
      if (/^\/api\/catalog\/imports\/(42|43)\/rows\//.test(path)) return route.fulfill({ json: { rows: [], total_rows: 0, workflow_revision: 3 } });
      throw new Error(`Unexpected fictional request: ${path}`);
    });
    await page.goto("/catalog/maintenance?return_to=%2Fcatalog%2Funmatched"); const panel = page.getByRole("region", { name: "目录工作簿", exact: true });
    await panel.getByRole("button", { name: "生成候选", exact: true }).click(); await expect(panel.getByText("生成失败：fictional_worker_failure", { exact: true })).toBeVisible();
    await panel.getByRole("button", { name: "恢复生成", exact: true }).click(); await expect(panel.getByRole("link", { name: "下载兼容 XLSX", exact: true })).toHaveAttribute("href", "/api/catalog/exports/8001/file");
    await panel.screenshot({ path: testInfo.outputPath(`workbook-${width}.png`) });
    await panel.getByRole("button", { name: "开始在线审核", exact: true }).click(); await expect(page).toHaveURL(/\/catalog\/imports\/42$/); await expect(page.getByRole("link", { name: "返回来源页面", exact: true })).toHaveAttribute("href", "/catalog/unmatched");
    await page.goBack(); await expect(panel.getByRole("button", { name: "开始在线审核", exact: true })).toBeEnabled();
    await panel.getByLabel("上传已修改的兼容 XLSX", { exact: true }).setInputFiles({ name: "fictional-revised.xlsx", mimeType: "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", buffer: Buffer.from("fictional workbook bytes") });
    await panel.getByRole("button", { name: "上传并进入审核", exact: true }).click(); await expect(panel.getByRole("alert")).toContainText("工作簿格式未通过检查"); await expect(panel.getByText("fictional-revised.xlsx", { exact: true })).toBeVisible();
    await panel.getByRole("button", { name: "上传并进入审核", exact: true }).click(); await expect(page).toHaveURL(/\/catalog\/imports\/43$/); await expect(page.getByRole("link", { name: "返回来源页面", exact: true })).toHaveAttribute("href", "/catalog/maintenance");
    await page.reload(); await expect(page.getByRole("heading", { name: "商品主档审核", exact: true })).toBeVisible(); await expect(page.getByText("当前修订 3", { exact: true })).toBeVisible();
    expect(uploadKeys[0]).toBe(uploadKeys[1]); expect(commands).toEqual(["/api/catalog/exports", "/api/catalog/exports/8001/resume", "/api/catalog/imports/from-export", "/api/catalog/imports", "/api/catalog/imports"]);
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
  });
}
