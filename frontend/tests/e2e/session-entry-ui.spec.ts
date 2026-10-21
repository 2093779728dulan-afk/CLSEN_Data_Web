import { expect, test, type Page } from "@playwright/test";
import { accountPrincipal, accountRoles, accountUsers } from "../../src/features/admin/AdminAccountsView.fixtures";
import { siteConfigs } from "../../src/features/admin/SiteConfigurationView.fixtures";

async function install(page: Page) {
  const state = { loggedIn: false, loginFails: true, holdLogin: false, holdSite: false, siteFails: true, logoutFails: true };
  let releaseMe: (() => void) | undefined; let releaseLogin: (() => void) | undefined; let releaseSite: (() => void) | undefined;
  const logins: { body: unknown; csrf?: string }[] = []; const unexpected: string[] = []; let sites = 0;
  await page.route(url => url.pathname.startsWith("/api/"), async route => {
    const r = route.request(); const path = new URL(r.url()).pathname;
    const failure = (status: number, message: string) => route.fulfill({ status, json: { error: { code: "fictional_failure", message } } });
    if (path === "/api/auth/me") { if (!state.loggedIn) await new Promise<void>(resolve => { releaseMe = resolve; }); return state.loggedIn ? route.fulfill({ json: accountPrincipal }) : failure(401, "示例未登录"); }
    if (path === "/api/auth/csrf") return route.fulfill({ json: { csrf_token: "fictional-login-csrf" } });
    if (path === "/api/auth/login" && r.method() === "POST") {
      logins.push({ body: r.postDataJSON(), csrf: r.headers()["x-csrf-token"] });
      if (state.holdLogin) await new Promise<void>(resolve => { releaseLogin = resolve; });
      if (state.loginFails) return failure(401, "示例账号或密码不正确");
      state.loggedIn = true; return route.fulfill({ headers: { "Set-Cookie": "clsen_csrf=fictional-session-csrf; Path=/; SameSite=Lax" }, json: { user: accountPrincipal, csrf_token: "fictional-session-csrf" } });
    }
    if (path === "/api/data-calendar/site-context") {
      sites += 1; if (state.holdSite) await new Promise<void>(resolve => { releaseSite = resolve; });
      if (state.siteFails) return failure(503, "示例站点配置暂时不可用");
      const c = siteConfigs[0]!; return route.fulfill({ json: { site_id: c.site_id, site_code: c.site_code, display_name: c.site_display_name, site_config_version_id: c.id, source_timezone: c.source_timezone, reporting_timezone: c.reporting_timezone, currency_code: c.currency_code } });
    }
    if (path === "/api/admin/users") return route.fulfill({ json: accountUsers });
    if (path === "/api/admin/roles") return route.fulfill({ json: accountRoles });
    if (path === "/api/admin/site-config-versions") return route.fulfill({ json: siteConfigs });
    if (path === "/api/admin/audit-events") return route.fulfill({ json: { items: [], total: 0, limit: 20, offset: 0, next_offset: null } });
    if (path === "/api/auth/logout" && r.method() === "POST") {
      expect(r.headers()["x-csrf-token"]).toBe("fictional-session-csrf");
      if (state.logoutFails) return failure(503, "示例网络中断");
      state.loggedIn = false; return route.fulfill({ status: 204 });
    }
    unexpected.push(`${r.method()} ${path}`); return failure(500, "非预期虚构请求");
  });
  return { state, logins, unexpected, sites: () => sites, releaseMe: () => releaseMe?.(), releaseLogin: () => releaseLogin?.(), releaseSite: () => releaseSite?.() };
}

for (const width of [1280, 390]) test(`actual login failure, pending, site retry, deep-link reload and logout at ${width}px`, async ({ page }) => {
  await page.setViewportSize({ width, height: 900 }); const fixture = await install(page); const errors: string[] = []; page.on("pageerror", e => errors.push(e.message));
  await page.goto("/admin"); await expect(page.getByRole("status", { name: "正在连接数据核验台…", exact: true })).toBeVisible(); fixture.releaseMe();
  const username = page.getByRole("textbox", { name: "账号", exact: true }); const password = page.locator("#login-password");
  await expect(username).toBeVisible(); await username.fill("fictional-admin"); await password.fill("fictional-only-password"); await password.press("Enter");
  await expect(page.getByRole("alert")).toContainText("示例账号或密码不正确"); await expect(username).toHaveValue("fictional-admin"); await expect(password).toHaveValue("fictional-only-password");
  fixture.state.loginFails = false; fixture.state.holdLogin = true; await page.getByRole("button", { name: "登录工作台", exact: true }).click();
  await expect(page.getByRole("button", { name: "正在登录…", exact: true })).toBeDisabled(); await expect(username).toBeDisabled(); await expect(password).toBeDisabled(); expect(fixture.logins).toHaveLength(2);
  fixture.state.holdLogin = false; fixture.releaseLogin(); await expect(page.getByRole("alert")).toContainText("示例站点配置暂时不可用"); await expect(page.getByRole("navigation", { name: "工作区", exact: true })).toHaveCount(0);
  fixture.state.siteFails = false; fixture.state.holdSite = true; await page.getByRole("button", { name: "重新读取站点配置", exact: true }).click();
  await expect(page.getByRole("status", { name: "正在读取当前站点配置…", exact: true })).toBeVisible(); expect(fixture.sites()).toBe(2);
  fixture.state.holdSite = false; fixture.releaseSite(); await expect(page.getByRole("heading", { name: "账号与角色", exact: true })).toBeVisible(); await expect(page).toHaveURL(/\/admin$/);
  if (width === 1280) {
    await page.getByRole("button", { name: "收起侧栏", exact: true }).click();
    await expect(page.getByRole("complementary", { name: "主导航", exact: true }).getByText("CLSEN", { exact: true })).toBeHidden();
    await page.getByRole("button", { name: "展开侧栏", exact: true }).click();
    await expect(page.getByRole("complementary", { name: "主导航", exact: true }).getByText("CLSEN", { exact: true })).toBeVisible();
  }
  await page.reload(); await expect(page.getByRole("heading", { name: "账号与角色", exact: true })).toBeVisible();
  if (width < 640) await page.getByRole("button", { name: "打开主导航", exact: true }).click();
  await page.getByRole("button", { name: "退出", exact: true }).click(); await expect(page.getByRole("alert")).toContainText("示例网络中断"); await expect(page).toHaveURL(/\/admin$/);
  if (width < 640) await page.getByRole("button", { name: "关闭主导航", exact: true }).click();
  await expect(page.getByRole("heading", { name: "账号与角色", exact: true })).toBeVisible();
  if (width < 640) await page.getByRole("button", { name: "打开主导航", exact: true }).click();
  fixture.state.logoutFails = false; await page.getByRole("button", { name: "退出", exact: true }).click(); await expect(username).toBeVisible(); await expect(username).toHaveValue(""); await expect(password).toHaveValue("");
  expect(fixture.logins).toEqual([{ body: { username: "fictional-admin", password: "fictional-only-password" }, csrf: "fictional-login-csrf" }, { body: { username: "fictional-admin", password: "fictional-only-password" }, csrf: "fictional-login-csrf" }]);
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true); expect(errors).toEqual([]); expect(fixture.unexpected).toEqual([]);
});
