import { expect, test } from "@playwright/test";

const principal = { id: 7, username: "manager", display_name: "目录管理员", roles: ["data_manager"] };
const site = { site_id: 1, site_code: "US", display_name: "美国站", site_config_version_id: 2, source_timezone: "America/Los_Angeles", reporting_timezone: "America/Los_Angeles", currency_code: "USD" };

test("creates a ready export and opens an online catalog review", async ({ page }) => {
  await page.context().addCookies([
    { name: "clsen_csrf", url: "http://127.0.0.1:5173", value: "catalog-csrf" },
  ]);
  await page.route(/^https?:\/\/[^/]+\/api\//, async (route) => {
    const url = new URL(route.request().url());
    if (url.pathname === "/api/auth/me") return route.fulfill({ json: principal });
    if (url.pathname === "/api/data-calendar/site-context") return route.fulfill({ json: site });
    if (url.pathname === "/api/dashboard/style-readiness") return route.fulfill({ json: { published_reports: 74, published_business_reports: 37, published_return_reports: 37, return_snapshot_present: true, catalog_approved: false, prerequisites_present: true } });
    if (url.pathname === "/api/catalog/source-scope") return route.fulfill({ json: { status: "confirmed", seller_account_display_name: "测试账号", permissions: { can_confirm: false } } });
    if (url.pathname === "/api/catalog/styles") return route.fulfill({ json: { catalog: null } });
    if (url.pathname === "/api/catalog/imports" && route.request().method() === "GET") return route.fulfill({ json: { has_next: false, items: [] } });
    if (url.pathname === "/api/catalog/exports" && route.request().method() === "POST") return route.fulfill({ json: { attempt_count: 0, base_catalog_version_id: null, capacity_violations: [], catalog_publication_revision: 0, execution_phase: "waiting_for_worker", export_id: 12, export_status: "building", failure_reason_code: null, job_revision: 1, job_status: "queued", max_attempts: 3, next_attempt_at: null, permissions: { can_download: false, can_resume: false }, retry_allowed: false, worker_available: true, workbook_status: null }, status: 202 });
    if (url.pathname === "/api/catalog/exports/12") return route.fulfill({ json: { attempt_count: 1, base_catalog_version_id: null, capacity_violations: [], catalog_publication_revision: 0, execution_phase: "completed", export_id: 12, export_status: "ready", failure_reason_code: null, job_revision: 2, job_status: "succeeded", max_attempts: 3, next_attempt_at: null, permissions: { can_download: true, can_resume: false }, retry_allowed: false, worker_available: true, workbook_status: "ready" } });
    if (url.pathname === "/api/catalog/imports/from-export") return route.fulfill({ json: { import_id: 20 }, status: 201 });
    if (url.pathname === "/api/catalog/imports/20") return route.fulfill({ json: { base_catalog_version_id: null, export_id: 12, failure_reason_code: null, has_original_file: false, import_id: 20, parse_attempt_revision: 0, permissions: { can_approve_high_risk: false, can_approve_normal: false, can_download_original: false, can_edit: true, can_preview: false, can_rebase: true, can_reject: false, can_submit: false, can_validate: true, can_view: true, can_withdraw: true }, source_kind: "online", status: "needs_attention", submitted_by_user_id: null, validation_run_id: null, workflow_revision: 0 } });
    if (url.pathname.includes("/rows/")) return route.fulfill({ json: { import_id: 20, page: 1, page_size: 200, parse_attempt_revision: 0, rows: [], section: "styles", total_rows: 0, workflow_revision: 0 } });
    return route.fulfill({ json: {} });
  });
  await page.goto("/catalog");
  await expect(page.getByRole("heading", { name: "商品主档尚未初始化" })).toBeVisible();
  await page.getByRole("link", { name: "进入批量维护" }).click();
  await expect(page).toHaveURL(/\/catalog\/maintenance$/);
  await page.getByRole("button", { name: "生成候选" }).click();
  await expect(page.getByRole("link", { name: "下载兼容 XLSX" })).toBeVisible();
  await page.getByRole("button", { name: "开始在线审核" }).click();
  await expect(page).toHaveURL(/\/catalog\/imports\/20$/);
  await expect(page.getByRole("heading", { name: "商品主档审核" })).toBeVisible();
});
