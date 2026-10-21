import { expect, test, type Page } from "@playwright/test";
import { accountPrincipal, accountRoles, accountUsers } from "../../src/features/admin/AdminAccountsView.fixtures";
import { siteConfigs } from "../../src/features/admin/SiteConfigurationView.fixtures";

async function install(page: Page) {
  const state = { logoutFails: true, holdLogout: false }; let releaseLogout: (() => void) | undefined;
  const unexpected: string[] = []; const writes: string[] = [];
  await page.context().addCookies([{ name: "clsen_csrf", value: "fictional-session-csrf", url: test.info().project.use.baseURL! }]);
  await page.route(url => url.pathname.startsWith("/api/"), async route => {
    const r = route.request(); const path = new URL(r.url()).pathname;
    if (path === "/api/auth/logout" && r.method() === "POST") {
      writes.push(path); expect(r.headers()["x-csrf-token"]).toBe("fictional-session-csrf");
      if (state.holdLogout) await new Promise<void>(resolve => { releaseLogout = resolve; });
      return state.logoutFails ? route.fulfill({ status: 503, json: { error: { code: "fictional_failure", message: "示例网络中断" } } }) : route.fulfill({ status: 204 });
    }
    if (r.method() !== "GET") { unexpected.push(`${r.method()} ${path}`); return route.fulfill({ status: 405 }); }
    if (path === "/api/auth/me") return route.fulfill({ json: accountPrincipal });
    if (path === "/api/data-calendar/site-context") {
      const c = siteConfigs[0]!; return route.fulfill({ json: { site_id: c.site_id, site_code: c.site_code, display_name: c.site_display_name, site_config_version_id: c.id, source_timezone: c.source_timezone, reporting_timezone: c.reporting_timezone, currency_code: c.currency_code } });
    }
    if (path === "/api/admin/users") return route.fulfill({ json: accountUsers });
    if (path === "/api/admin/roles") return route.fulfill({ json: accountRoles });
    if (path === "/api/admin/site-config-versions") return route.fulfill({ json: siteConfigs });
    if (path === "/api/admin/audit-events") return route.fulfill({ json: { items: [], total: 0, limit: 20, offset: 0, next_offset: null } });
    if (["/api/versions", "/api/admin/published-moves/undoable"].includes(path)) return route.fulfill({ json: [] });
    if (path === "/api/imports/batch-reviews") return route.fulfill({ json: { items: [], has_next: false } });
    unexpected.push(`${r.method()} ${path}`); return route.fulfill({ status: 500 });
  });
  return { state, unexpected, writes, releaseLogout: () => releaseLogout?.() };
}

for (const width of [1280, 390]) test(`actual shell persistence, routing and logout recovery at ${width}px`, async ({ page }) => {
  await page.setViewportSize({ width, height: 900 }); const fixture = await install(page); const errors: string[] = []; page.on("pageerror", e => errors.push(e.message));
  await page.goto("/admin"); await expect(page.getByRole("heading", { name: "账号与角色", exact: true })).toBeVisible();
  if (width === 1280) {
    await page.getByRole("button", { name: "收起侧栏", exact: true }).click(); await page.reload();
    await expect(page.getByRole("button", { name: "展开侧栏", exact: true })).toBeVisible(); await expect(page.locator(".app-shell")).toHaveAttribute("data-sidebar-collapsed", "true");
  } else await page.getByRole("button", { name: "打开主导航", exact: true }).click();
  await page.getByRole("navigation", { name: "工作区", exact: true }).getByRole("link", { name: "版本记录", exact: true }).click();
  await expect(page).toHaveURL(/\/versions$/); await expect(page.getByRole("heading", { name: "版本记录", exact: true })).toBeVisible();
  await expect(page.getByRole("dialog", { name: "工作区导航", exact: true })).toHaveCount(0);
  await page.reload(); await expect(page.getByRole("heading", { name: "版本记录", exact: true })).toBeVisible();
  if (width === 390) await page.getByRole("button", { name: "打开主导航", exact: true }).click();
  const scope = width === 390 ? page.getByRole("dialog") : page.locator(".app-shell");
  await expect(scope.getByRole("link", { name: "版本记录", exact: true })).toHaveAttribute("aria-current", "page");
  await expect(scope.getByRole("link", { name: "数据审核", exact: true })).toHaveAttribute("href", /\/review\/\d{4}-\d{2}-\d{2}$/);
  fixture.state.holdLogout = true; await scope.getByRole("button", { name: "退出", exact: true }).click();
  await expect(scope.getByRole("button", { name: "退出中", exact: true })).toBeDisabled();
  fixture.state.holdLogout = false; fixture.releaseLogout(); await expect(scope.getByRole("alert")).toContainText("示例网络中断");
  fixture.state.logoutFails = false; await scope.getByRole("button", { name: "重试退出", exact: true }).click();
  await expect(page.getByRole("textbox", { name: "账号", exact: true })).toBeVisible();
  expect(fixture.writes).toEqual(["/api/auth/logout", "/api/auth/logout"]); expect(fixture.unexpected).toEqual([]); expect(errors).toEqual([]);
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
});
