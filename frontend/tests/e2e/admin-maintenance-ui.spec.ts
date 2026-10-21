import { expect, test, type Page } from "@playwright/test";
import { statusFor } from "../../src/features/admin/AdminMaintenanceView.fixtures";
import { accountPrincipal, accountRoles, accountUsers } from "../../src/features/admin/AdminAccountsView.fixtures";
import { siteConfigs } from "../../src/features/admin/SiteConfigurationView.fixtures";

async function install(page: Page) {
  const state = { fail: true, hold: false }; let release: (() => void) | undefined; const reads: number[] = []; const unexpected: string[] = [];
  await page.context().route(url => url.pathname.startsWith("/api/"), async route => {
    const r = route.request(); const path = new URL(r.url()).pathname;
    const failure = () => route.fulfill({ status: 503, json: { error: { code: "synthetic_unavailable", message: "虚构维护状态读取失败" } } });
    if (r.method() !== "GET") { unexpected.push(`${r.method()} ${path}`); return failure(); }
    if (path === "/api/auth/me") return route.fulfill({ json: accountPrincipal });
    if (path === "/api/data-calendar/site-context") { const c = siteConfigs[0]!; return route.fulfill({ json: { site_id: c.site_id, site_code: c.site_code, display_name: c.site_display_name, site_config_version_id: c.id, source_timezone: c.source_timezone, reporting_timezone: c.reporting_timezone, currency_code: c.currency_code } }); }
    if (path === "/api/admin/users") return route.fulfill({ json: accountUsers });
    if (path === "/api/admin/roles") return route.fulfill({ json: accountRoles });
    if (path === "/api/admin/site-config-versions") return route.fulfill({ json: siteConfigs });
    if (path === "/api/admin/audit-events") return route.fulfill({ json: { items: [], total: 0, limit: 20, offset: 0, next_offset: null } });
    if (path === "/api/admin/maintenance") {
      reads.push(reads.length + 1); if (state.hold) await new Promise<void>(resolve => { release = resolve; }); if (state.fail) return failure();
      const status = statusFor("consumer-failure"); status.backups[0]!.raw_file_count = reads.length === 2 ? 4 : 5;
      return route.fulfill({ json: status });
    }
    unexpected.push(`${r.method()} ${path}`); return failure();
  });
  return { state, reads, unexpected, release: () => release?.() };
}
for (const width of [1280, 390]) {
  test(`actual maintenance lazy read, retry, refresh overlap and retained diagnostics at ${width}px`, async ({ page }) => {
    await page.setViewportSize({ width, height: 900 }); const fixture = await install(page); const errors: string[] = []; page.on("pageerror", e => errors.push(e.message));
    await page.goto("/admin"); await expect(page.getByRole("heading", { name: "账号与角色", exact: true })).toBeVisible(); expect(fixture.reads).toHaveLength(0);
    await page.getByRole("button", { name: "备份与任务", exact: true }).click(); await expect(page.getByRole("alert")).toContainText("虚构维护状态读取失败");
    fixture.state.fail = false; await page.getByRole("button", { name: "重新读取维护状态", exact: true }).click();
    await expect(page.getByRole("article", { name: "备份 501", exact: true })).toContainText("4 个原始对象"); await expect(page.getByText("进程在线，catalog_import 消费者失败", { exact: true })).toBeVisible();
    const queue = page.locator(".worker-observability__queue").last(); await queue.getByText("查看诊断", { exact: true }).click(); await expect(queue.getByText(/消费者连续失败/)).toBeVisible();
    fixture.state.hold = true; await page.getByRole("button", { name: "刷新状态", exact: true }).click();
    await expect(page.getByRole("button", { name: "刷新中…", exact: true })).toBeDisabled(); expect(fixture.reads).toHaveLength(3); await expect(queue.getByText(/消费者连续失败/)).toBeVisible();
    fixture.state.fail = true; fixture.state.hold = false; fixture.release(); await expect(page.getByRole("alert")).toContainText("状态可能已过期"); await expect(page.getByRole("article", { name: "备份 501", exact: true })).toContainText("4 个原始对象");
    fixture.state.fail = false; await page.getByRole("button", { name: "刷新状态", exact: true }).click(); await expect(page.getByRole("article", { name: "备份 501", exact: true })).toContainText("5 个原始对象"); await expect(queue.getByText(/消费者连续失败/)).toBeVisible();
    await page.getByRole("button", { name: "账号与角色", exact: true }).click(); await page.getByRole("button", { name: "备份与任务", exact: true }).click(); expect(fixture.reads).toHaveLength(4);
    await page.reload(); await page.getByRole("button", { name: "备份与任务", exact: true }).click(); await expect(page.getByRole("article", { name: "备份 501", exact: true })).toContainText("5 个原始对象");
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true); expect(fixture.unexpected).toEqual([]); expect(errors).toEqual([]);
  });
}
