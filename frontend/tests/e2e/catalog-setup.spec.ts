import { expect, test, type Page } from "@playwright/test";

async function fixture(page: Page, missingReports = false) {
  const state = { confirmed: missingReports, ready: false, reports: missingReports ? 0 : 37, initialReadFailure: missingReports, viewer: false, jobReads: 0, scopeAttempts: 0, initAttempts: 0 };
  const commands: Array<{ path: string; body: Record<string, unknown>; key: string | undefined }> = [];
  const baseURL = test.info().project.use.baseURL;
  if (!baseURL) throw new Error("Synthetic setup fixture needs its configured base URL");
  await page.context().addCookies([{ name: "clsen_csrf", url: baseURL, value: "synthetic-setup-csrf" }]);
  await page.route(/^https?:\/\/[^/]+\/api\//, async route => {
    const path = new URL(route.request().url()).pathname;
    if (route.request().method() === "POST") {
      const body = route.request().postDataJSON() as Record<string, unknown>;
      const key = route.request().headers()["idempotency-key"];
      commands.push({ path, body, key });
      expect(body.operation_token).toBe(key); expect(key).toEqual(expect.any(String));
      expect(route.request().headers()["x-csrf-token"]).toBe("synthetic-setup-csrf");
      if (path === "/api/catalog/source-scope/confirm") {
        expect(body).toMatchObject({ expected_site_config_revision: 3, seller_account_scope_key: "DEMO-US", seller_account_display_name: "虚构美国账号", marketplace_scope_code: "amazon_us", reason: "虚构来源说明" });
        if (state.scopeAttempts++ === 0) return route.fulfill({ status: 503, json: { error: { code: "UNAVAILABLE" } } });
        state.confirmed = true; return route.fulfill({ json: {} });
      }
      if (path === "/api/publications/return-initialization") {
        expect(body).toMatchObject({ dataset_id: 74, proposed_version_id: 93, expected_publication_revision: 0, expected_dedup_publication_revision: 0, initialization_revision: 3, expected_set_digest: "a".repeat(64) });
        if (state.initAttempts++ === 0) return route.fulfill({ status: 503, json: { error: { code: "UNAVAILABLE" } } });
        return route.fulfill({ json: { job_id: 8, status: "building" } });
      }
      throw new Error(`Unexpected synthetic write: ${path}`);
    }
    if (path === "/api/auth/me") return route.fulfill({ json: { id: 88, username: "synthetic-setup", display_name: "虚构准备账号", roles: [state.viewer ? "viewer" : "admin"] } });
    if (path === "/api/data-calendar/site-context") return route.fulfill({ json: { site_id: 1, site_code: "US", display_name: "示例站点", site_config_version_id: 2, source_timezone: "UTC", reporting_timezone: "UTC", currency_code: "USD" } });
    if (path === "/api/catalog/styles") return route.fulfill({ json: { catalog: null } });
    if (path === "/api/catalog/imports") return route.fulfill({ json: { items: [], has_next: false } });
    if (path === "/api/catalog/exports/latest") return route.fulfill({ json: { export: null } });
    if (path === "/api/dashboard/style-readiness") return route.fulfill({ json: { published_reports: 37 + state.reports, published_business_reports: 37, published_return_reports: state.reports, coverage_from: "2026-07-01", coverage_to: "2026-08-06", return_snapshot_present: state.ready, catalog_approved: false, source_scope_confirmed: state.confirmed, prerequisites_present: false } });
    if (path === "/api/catalog/source-scope") {
      if (state.initialReadFailure) { return route.fulfill({ status: 503, json: { error: { code: "UNAVAILABLE" } } }); }
      return route.fulfill({ json: { marketplace_scope_code: "amazon_us", permissions: { can_confirm: !state.viewer && !state.confirmed }, report_source_scope_id: state.confirmed ? 1 : null, seller_account_display_name: state.confirmed ? "虚构美国账号" : null, site_config_revision: 3, site_config_version_id: 2, status: state.confirmed ? "confirmed" : "unconfirmed" } });
    }
    if (path === "/api/publications/return-initialization") return route.fulfill({ json: { dataset_id: 74, proposed_version_id: 93, expected_publication_revision: 0, expected_dedup_publication_revision: 0, initialization_revision: 3, expected_set_digest: "a".repeat(64), published_return_reports: 37, coverage_from: "2026-07-01", coverage_to: "2026-08-06", existing_job_id: state.initAttempts > 1 ? 8 : null } });
    if (path === "/api/publications/return-dedup-staging/8") { state.ready = state.jobReads++ > 0; return route.fulfill({ json: { job_id: 8, status: state.ready ? "ready" : "building", result_snapshot_id: state.ready ? 9 : null } }); }
    return route.fulfill({ json: {} });
  });
  await page.goto("/catalog/maintenance");
  return { state, commands };
}

for (const width of [1280, 390]) {
  test(`actual setup preserves operation identity and refreshes after snapshot at ${width}px`, async ({ page }) => {
    await page.setViewportSize({ width, height: 900 });
    const { commands } = await fixture(page);
    const setup = page.getByRole("region", { name: "商品分析初始化", exact: true });
    await setup.getByRole("textbox", { name: "来源账号标识", exact: true }).fill(" DEMO-US ");
    await setup.getByRole("textbox", { name: "账号显示名称", exact: true }).fill(" 虚构美国账号 ");
    await setup.getByRole("textbox", { name: "确认依据", exact: true }).fill(" 虚构来源说明 ");
    await setup.getByRole("checkbox").check();
    await setup.getByRole("button", { name: "确认来源范围", exact: true }).click();
    await expect(setup.getByRole("alert")).toContainText("来源范围确认未完成");
    await expect(setup.getByRole("textbox", { name: "来源账号标识", exact: true })).toHaveValue(" DEMO-US ");
    await setup.getByRole("button", { name: "确认来源范围", exact: true }).click();
    await expect(setup.getByText("账号来源范围：已确认（虚构美国账号）", { exact: true })).toBeVisible();
    expect(commands[0]?.key).toBe(commands[1]?.key);
    await setup.getByRole("button", { name: "准备首次退货快照", exact: true }).click();
    await expect(setup.getByRole("region", { name: "首次快照预览", exact: true })).toBeVisible();
    expect(commands).toHaveLength(2);
    await setup.getByRole("button", { name: "确认建立首次快照", exact: true }).click();
    await expect(setup.getByRole("alert")).toContainText("首次快照尚未完成");
    await setup.getByRole("button", { name: "确认建立首次快照", exact: true }).click();
    await expect(setup.getByText(/首次退货快照已建立/)).toBeVisible();
    await expect(setup.getByText("退货去重快照：已建立，读取分析时仍会校验是否匹配最新报表", { exact: true })).toBeVisible();
    await expect(setup.getByText("商品主档：待生成候选、审核并批准", { exact: true })).toBeVisible();
    expect(commands[2]?.key).toBe(commands[3]?.key);
    expect(commands).toHaveLength(4);
    await page.reload();
    await expect(setup.getByText("账号来源范围：已确认（虚构美国账号）", { exact: true })).toBeVisible();
    await expect(setup.getByRole("button", { name: "确认建立首次快照", exact: true })).toHaveCount(0);
    expect(commands).toHaveLength(4);
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
  });
}

test("actual setup recovers reading, blocks missing reports and offers readonly guidance", async ({ page }) => {
  const { state, commands } = await fixture(page, true);
  const setup = page.getByRole("region", { name: "商品分析初始化", exact: true });
  await expect(setup.getByRole("alert")).toContainText("无法读取初始化状态");
  state.initialReadFailure = false;
  await setup.getByRole("button", { name: "刷新核对状态", exact: true }).click();
  await expect(setup.getByRole("button", { name: "准备首次退货快照", exact: true })).toBeDisabled();
  state.viewer = true; await page.goto("/catalog");
  await expect(setup.getByRole("link", { name: "查看商品主档与初始化说明", exact: true })).toBeVisible();
  await expect(setup.getByRole("button", { name: "准备首次退货快照", exact: true })).toHaveCount(0);
  await expect(setup.getByRole("textbox", { name: "来源账号标识", exact: true })).toHaveCount(0);
  expect(commands).toEqual([]);
});
