import { expect, test, type Page } from "@playwright/test";
import { auditEvents } from "../../src/features/admin/AdminAuditView.fixtures";
import { accountPrincipal, accountRoles, accountUsers } from "../../src/features/admin/AdminAccountsView.fixtures";
import { siteConfigs } from "../../src/features/admin/SiteConfigurationView.fixtures";

async function install(page: Page, denied = false) {
  const state = { readFailure: true, filterFailure: true }; const unexpected: string[] = []; const queries: string[] = [];
  await page.context().route(url => url.pathname.startsWith("/api/"), async route => {
    const request = route.request(); const url = new URL(request.url()); const path = url.pathname;
    const failure = (message: string) => route.fulfill({ status: 503, json: { error: { code: "synthetic_unavailable", message } } });
    if (request.method() !== "GET") { unexpected.push(`${request.method()} ${path}`); return failure("禁止测试写入"); }
    if (path === "/api/auth/me") return route.fulfill({ json: denied ? { ...accountPrincipal, roles: ["viewer"] } : accountPrincipal });
    if (path === "/api/data-calendar/site-context") { const c = siteConfigs[0]!; return route.fulfill({ json: { site_id: c.site_id, site_code: c.site_code, display_name: c.site_display_name, site_config_version_id: c.id, source_timezone: c.source_timezone, reporting_timezone: c.reporting_timezone, currency_code: c.currency_code } }); }
    if (denied && path === "/api/data-calendar/days") return route.fulfill({ json: [] });
    if (denied && path === "/api/published/daily-summary") return route.fulfill({ json: { items: [] } });
    if (path === "/api/admin/users") return route.fulfill({ json: accountUsers });
    if (path === "/api/admin/roles") return route.fulfill({ json: accountRoles });
    if (path === "/api/admin/site-config-versions") return route.fulfill({ json: siteConfigs });
    if (path === "/api/admin/audit-events") {
      queries.push(url.search); if (state.readFailure) return failure("虚构审计首次读取失败");
      const type = url.searchParams.get("event_type"); if (type && state.filterFailure) return failure("虚构事件筛选失败");
      expect(url.searchParams.get("limit")).toBe("20");
      const offset = Number(url.searchParams.get("offset")); const filtered = auditEvents.filter(item => !type || item.event_type === type);
      const items = structuredClone(filtered.slice(offset, offset + 20));
      if (items[0]) items[0].redacted_payload = { safe: "保留的脱敏字段", customer: "synthetic-secret-1", nested: { roles: ["viewer"], order_number: "synthetic-secret-2" }, array: [{ message: "synthetic-secret-3", status: "disabled" }] };
      return route.fulfill({ json: { items, total: filtered.length, offset, limit: 20, next_offset: offset + 20 < filtered.length ? offset + 20 : null } });
    }
    unexpected.push(`${request.method()} ${path}`); return failure("未定义测试请求");
  });
  return { state, queries, unexpected };
}
for (const width of [1280, 390]) {
  test(`actual audit read/filter recovery, paging, redaction and refresh at ${width}px`, async ({ page }) => {
    await page.setViewportSize({ width, height: 900 }); const { state, queries, unexpected } = await install(page); const errors: string[] = []; page.on("pageerror", e => errors.push(e.message));
    await page.goto("/admin"); await page.getByRole("button", { name: "内部审计", exact: true }).click();
    await expect(page.getByRole("alert")).toContainText("虚构审计首次读取失败"); state.readFailure = false;
    await page.getByRole("button", { name: "重新载入管理资料", exact: true }).click(); await expect(page.getByRole("article")).toHaveCount(20);
    const event = page.getByRole("article", { name: "审计事件 900", exact: true }); await event.getByText("查看脱敏详情", { exact: true }).click();
    await expect(event.locator("pre")).toContainText("保留的脱敏字段"); await expect(event.locator("pre")).toContainText('"status"');
    await expect(event.locator("pre")).not.toContainText("synthetic-secret");
    await page.getByRole("button", { name: "下一页", exact: true }).click(); await expect(page.getByRole("article")).toHaveCount(3); expect(queries.at(-1)).toBe("?limit=20&offset=20");
    const input = page.getByRole("textbox", { name: "事件类型", exact: true }); await input.fill(" admin.user_updated "); await page.getByRole("button", { name: "应用筛选", exact: true }).click();
    await expect(page.getByRole("alert")).toContainText("虚构事件筛选失败"); await expect(page.getByRole("article")).toHaveCount(3); await expect(input).toHaveValue(" admin.user_updated ");
    state.filterFailure = false; await page.getByRole("button", { name: "应用筛选", exact: true }).click(); await expect(page.getByRole("article")).toHaveCount(12); expect(queries.at(-1)).toBe("?limit=20&offset=0&event_type=admin.user_updated");
    await input.fill("no.match"); await page.getByRole("button", { name: "应用筛选", exact: true }).click(); await expect(page.getByRole("heading", { name: "当前筛选条件下没有审计记录", exact: true })).toBeVisible();
    await page.reload(); await page.getByRole("button", { name: "内部审计", exact: true }).click(); await expect(page.getByRole("article")).toHaveCount(20); await expect(input).toHaveValue("");
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true); expect(unexpected).toEqual([]); expect(errors).toEqual([]);
  });
}
test("actual viewer cannot read admin audit", async ({ page }) => {
  const { queries } = await install(page, true); await page.goto("/admin");
  await expect(page).toHaveURL(/\/$/); await expect(page.getByRole("heading", { name: "管理员控制台", exact: true })).toHaveCount(0); expect(queries).toEqual([]);
});
