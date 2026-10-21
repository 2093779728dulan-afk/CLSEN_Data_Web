import { expect, test } from "@playwright/test";

test("keeps dangerous source values out of ordinary DOM until explicit reveal", async ({ page }) => {
  const dangerous = "危险\nsource";
  await page.route(/^https?:\/\/[^/]+\/api\//, async (route) => {
    const url = new URL(route.request().url());
    if (url.pathname === "/api/auth/me") return route.fulfill({ json: { id: 7, username: "manager", display_name: "目录管理员", roles: ["data_manager"] } });
    if (url.pathname === "/api/data-calendar/site-context") return route.fulfill({ json: { site_id: 1, site_code: "US", display_name: "美国站", site_config_version_id: 2, source_timezone: "UTC", reporting_timezone: "UTC", currency_code: "USD" } });
    if (url.pathname === "/api/catalog/imports/20") return route.fulfill({ json: { base_catalog_version_id: null, export_id: 12, failure_reason_code: null, has_original_file: false, import_id: 20, parse_attempt_revision: 0, permissions: { can_approve_high_risk: false, can_approve_normal: false, can_download_original: false, can_edit: true, can_preview: false, can_rebase: true, can_reject: false, can_submit: false, can_validate: true, can_view: true, can_withdraw: true }, source_kind: "online", status: "needs_attention", submitted_by_user_id: null, validation_run_id: null, workflow_revision: 2 } });
    if (url.pathname.includes("/rows/")) return route.fulfill({ json: { import_id: 20, page: 1, page_size: 200, parse_attempt_revision: 0, rows: [], section: "evidence", total_rows: 0, workflow_revision: 2 } });
    if (url.pathname === "/api/catalog/evidence") return route.fulfill({ json: { items: [{ digest: `sha256:${"a".repeat(64)}`, is_truncated: true, is_unsafe: true, preview: "危…ce", source_ref_id: "31" }] } });
    if (url.pathname.includes("/source-identifiers/31")) return route.fulfill({ json: { code_points: "U+5371", utf8_base64url: Buffer.from(dangerous).toString("base64url") } });
    return route.fulfill({ json: {} });
  });
  await page.goto("/catalog/imports/20");
  await page.getByRole("tab", { name: /来源证据/ }).click();
  await expect(page.locator("body")).not.toContainText(dangerous);
  await page.getByRole("button", { name: "查看完整标识" }).click();
  await expect(page.getByText(dangerous)).toBeVisible();
});
