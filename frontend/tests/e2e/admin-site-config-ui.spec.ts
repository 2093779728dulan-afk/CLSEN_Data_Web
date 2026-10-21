import { expect, test, type Page } from "@playwright/test";
import { siteConfigs } from "../../src/features/admin/SiteConfigurationView.fixtures";
import { accountPrincipal, accountRoles, accountUsers } from "../../src/features/admin/AdminAccountsView.fixtures";

test.use({ timezoneId: "Asia/Shanghai" });
async function install(page: Page) {
  let configs = structuredClone(siteConfigs);
  const state = { readFailure: true, createFailure: true };
  const writes: { body: Record<string, unknown>; key?: string }[] = []; const unexpected: string[] = []; const siteReads: number[] = [];
  await page.context().addCookies([{ name: "clsen_csrf", value: "synthetic-site-config", url: test.info().project.use.baseURL! }]);
  await page.context().route(url => url.pathname.startsWith("/api/"), async route => {
    const request = route.request(); const path = new URL(request.url()).pathname;
    const failure = (code: string, message: string) => route.fulfill({ status: 503, json: { error: { code, message } } });
    if (path === "/api/auth/me") return route.fulfill({ json: accountPrincipal });
    if (path === "/api/data-calendar/site-context") {
      const current = configs.find(config => config.is_current)!; siteReads.push(current.id);
      return route.fulfill({ json: { site_id: current.site_id, site_code: current.site_code, display_name: current.site_display_name, site_config_version_id: current.id, source_timezone: current.source_timezone, reporting_timezone: current.reporting_timezone, currency_code: current.currency_code } });
    }
    if (path === "/api/admin/users") return route.fulfill({ json: accountUsers });
    if (path === "/api/admin/roles") return route.fulfill({ json: accountRoles });
    if (path === "/api/admin/audit-events") return route.fulfill({ json: { items: [], total: 0, limit: 20, offset: 0, next_offset: null } });
    if (path === "/api/admin/site-config-versions" && request.method() === "GET") return state.readFailure ? failure("synthetic_unavailable", "虚构配置读取失败") : route.fulfill({ json: configs });
    if (path === "/api/admin/site-config-versions" && request.method() === "POST") {
      expect(request.headers()["x-csrf-token"]).toBe("synthetic-site-config");
      const body = request.postDataJSON() as Record<string, unknown>; const key = request.headers()["idempotency-key"]; expect(key).toMatch(/^[0-9a-f-]{36}$/);
      expect(body).toEqual({ site_id: 71, source_timezone: "America/Los_Angeles", reporting_timezone: "UTC", currency_code: "USD", effective_at: "2026-09-13T00:00:00.000Z", change_reason: "虚构统计口径调整" });
      writes.push({ body, key }); if (state.createFailure) return failure("admin_operation_outcome_unknown", "虚构配置创建结果暂时无法确认");
      const created = { ...siteConfigs[0]!, id: 703, version_number: 3, reporting_timezone: "UTC", effective_at: String(body.effective_at), change_reason: String(body.change_reason) };
      configs = [created, ...configs.map(config => ({ ...config, is_current: false }))]; return route.fulfill({ status: 201, json: created });
    }
    unexpected.push(`${request.method()} ${path}`); return failure("unexpected", "未定义测试请求");
  });
  return { state, writes, siteReads, unexpected };
}

for (const width of [1280, 390]) {
  test(`actual site config retry, cancel, create and refresh history at ${width}px`, async ({ page }) => {
    await page.setViewportSize({ width, height: 900 }); const { state, writes, siteReads, unexpected } = await install(page);
    const errors: string[] = []; page.on("pageerror", error => errors.push(error.message));
    await page.goto("/admin"); await expect(page.getByRole("alert")).toContainText("虚构配置读取失败");
    await page.getByRole("button", { name: "站点配置", exact: true }).click(); await expect(page.getByRole("button", { name: "新建配置版本", exact: true })).toBeDisabled();
    state.readFailure = false; await page.getByRole("button", { name: "重新载入管理资料", exact: true }).click();
    const history = page.getByRole("table", { name: "站点配置版本历史", exact: true }); await expect(history.getByRole("row")).toHaveCount(3);
    await page.getByRole("button", { name: "新建配置版本", exact: true }).click(); const form = page.getByRole("form", { name: "创建站点配置版本", exact: true });
    await expect(form.getByRole("textbox", { name: "统计时区", exact: true })).toHaveValue("Asia/Shanghai"); await form.getByRole("button", { name: "取消", exact: true }).click(); expect(writes).toHaveLength(0);
    await page.getByRole("button", { name: "新建配置版本", exact: true }).click();
    await form.getByRole("textbox", { name: "统计时区", exact: true }).fill("UTC"); await form.getByRole("textbox", { name: "币种", exact: true }).fill("usd");
    await form.getByLabel(/^生效时间（本机时区）/).fill("2026-09-13T08:00"); await form.getByRole("textbox", { name: "变更原因", exact: true }).fill(" 虚构统计口径调整 ");
    await form.getByRole("button", { name: "创建配置版本", exact: true }).click(); await expect(page.getByRole("alert")).toContainText("虚构配置创建结果暂时无法确认"); await expect(form.getByRole("textbox", { name: "统计时区", exact: true })).toHaveValue("UTC");
    state.createFailure = false; await form.getByRole("button", { name: "创建配置版本", exact: true }).click();
    await expect.poll(() => siteReads).toContain(703); expect(writes).toHaveLength(2); expect(writes[1]?.key).toBe(writes[0]?.key);
    await page.getByRole("button", { name: "站点配置", exact: true }).click(); await expect(history.getByRole("row")).toHaveCount(4); await expect(history.getByText("当前版本", { exact: true })).toHaveCount(1); await expect(history.getByRole("cell", { name: "虚构统计口径调整", exact: true })).toBeVisible();
    await page.reload(); await page.getByRole("button", { name: "站点配置", exact: true }).click(); await expect(history.getByRole("row")).toHaveCount(4); await expect(page.getByRole("article", { name: "当前站点配置 demo-us", exact: true })).toContainText("v3");
    await page.getByRole("button", { name: "内部审计", exact: true }).click(); await expect(page.getByRole("heading", { name: "内部审计", exact: true })).toBeVisible(); await page.getByRole("button", { name: "站点配置", exact: true }).click(); await expect(history).toBeVisible();
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true); expect(unexpected).toEqual([]); expect(errors).toEqual([]);
  });
}
