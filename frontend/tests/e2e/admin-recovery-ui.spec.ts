import { expect, test } from "@playwright/test";
import { accountPrincipal, accountRoles, accountUsers } from "../../src/features/admin/AdminAccountsView.fixtures";
import { siteConfigs } from "../../src/features/admin/SiteConfigurationView.fixtures";

for (const width of [1280, 390]) test(`actual recovery entry remains context-only after refresh at ${width}px`, async ({ page }) => {
  await page.setViewportSize({ width, height: 900 }); const unexpected: string[] = []; const errors: string[] = []; page.on("pageerror", e => errors.push(e.message));
  await page.route(url => url.pathname.startsWith("/api/"), async route => {
    const r = route.request(); const path = new URL(r.url()).pathname;
    if (r.method() === "GET") {
      if (path === "/api/auth/me") return route.fulfill({ json: accountPrincipal });
      if (path === "/api/data-calendar/site-context") { const c = siteConfigs[0]!; return route.fulfill({ json: { site_id: c.site_id, site_code: c.site_code, display_name: c.site_display_name, site_config_version_id: c.id, source_timezone: c.source_timezone, reporting_timezone: c.reporting_timezone, currency_code: c.currency_code } }); }
      if (path === "/api/admin/users") return route.fulfill({ json: accountUsers });
      if (path === "/api/admin/roles") return route.fulfill({ json: accountRoles });
      if (path === "/api/admin/site-config-versions") return route.fulfill({ json: siteConfigs });
      if (path === "/api/admin/audit-events") return route.fulfill({ json: { items: [], total: 0, limit: 20, offset: 0, next_offset: null } });
    }
    unexpected.push(`${r.method()} ${path}`); return route.fulfill({ status: 500, json: {} });
  });
  await page.goto("/admin"); await page.getByRole("button", { name: "草稿恢复", exact: true }).click();
  await expect(page.getByRole("heading", { name: "强制重建从导入冲突进入" })).toBeVisible(); await expect(page.getByRole("textbox")).toHaveCount(0); await expect(page.getByRole("button", { name: "强制重建草稿", exact: true })).toHaveCount(0);
  await page.getByRole("button", { name: "账号与角色", exact: true }).click(); await page.getByRole("button", { name: "草稿恢复", exact: true }).click();
  await page.reload(); await page.getByRole("button", { name: "草稿恢复", exact: true }).click(); await expect(page.getByRole("heading", { name: "强制重建从导入冲突进入" })).toBeVisible();
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true); expect(unexpected).toEqual([]); expect(errors).toEqual([]);
});
