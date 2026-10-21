import { expect, test, type Page } from "@playwright/test";

async function fixture(page: Page, baseURL: string) {
  await page.context().addCookies([{ name: "clsen_csrf", url: baseURL, value: "fictional-owner-csrf" }]);
  const state = { revision: 3, readFailure: true, restoreFailure: true, refreshFailure: false };
  const row = { section: "mappings", row_key: "fictional/mapping-1", row_origin: "system", projection_state: "audit_only", payload: { seller_sku_preview: "DEMO-01-Blue-M", identity_decision: "excluded" as string | null, exclusion_reason: "虚构来源排除依据", target_sku_row_key: null, change_reason: null } };
  const writes: { body: Record<string, unknown>; key: string }[] = [];
  let identityReads = 0;
  await page.route(url => url.pathname.startsWith("/api/"), async route => {
    const req = route.request(); const path = new URL(req.url()).pathname;
    if (path === "/api/auth/me") return route.fulfill({ json: { id: 88, username: "fictional-owner-manager", display_name: "虚构管理账号", roles: ["data_manager"] } });
    if (path === "/api/data-calendar/site-context") return route.fulfill({ json: { site_id: 1, site_code: "US", display_name: "虚构站点", site_config_version_id: 2, source_timezone: "UTC", reporting_timezone: "UTC", currency_code: "USD" } });
    if (path === "/api/dashboard/style-readiness") return route.fulfill({ json: { published_reports: 0, prerequisites_present: false } });
    if (path === "/api/catalog/imports/42") {
      if (state.refreshFailure) { state.refreshFailure = false; return route.fulfill({ status: 503, json: { error: { code: "UNAVAILABLE", message: "示例：最新草稿读取失败" } } }); }
      return route.fulfill({ json: { import_id: 42, workflow_revision: state.revision, catalog_publication_revision: 7, base_catalog_version_id: 4, export_id: 8001, parse_attempt_revision: 1, source_kind: "online", status: "needs_attention", failure_reason_code: null, has_original_file: false, submitted_by_user_id: 88, validation_run_id: null,
        permissions: { can_view: true, can_edit: true, can_preview: false, can_approve_normal: false, can_approve_high_risk: false, can_rebase: false, can_reject: false, can_withdraw: false, can_resume: false, can_validate: false, can_submit: false, can_download_original: false } } });
    }
    if (path.includes("/rows/")) return route.fulfill({ json: { rows: path.endsWith("/mappings") ? [row] : [], total_rows: path.endsWith("/mappings") ? 1 : 0, workflow_revision: state.revision } });
    if (path.includes("/identity-owners/")) {
      expect(path.split("/identity-owners/")[1]).toBe("fictional%2Fmapping-1"); identityReads++;
      if (state.readFailure) { state.readFailure = false; return route.fulfill({ status: 503, json: { error: { code: "UNAVAILABLE", message: "示例：归属暂时不可用" } } }); }
      return route.fulfill({ json: { formal: [{ style_id: 8, sku_id: 12 }], drafts: [{ import_id: 9, decision_kind: "excluded" }], ignored: [{ catalog_version_id: 2, reason: "虚构旧忽略记录" }] } });
    }
    if (path === "/api/catalog/imports/42/decisions") {
      const body = req.postDataJSON() as Record<string, unknown>; const key = req.headers()["idempotency-key"]!; writes.push({ body, key });
      expect(req.headers()["x-csrf-token"]).toBe("fictional-owner-csrf"); expect(key).toMatch(/^[0-9a-f-]{36}$/); expect(body.expected_workflow_revision).toBe(state.revision);
      expect(body.mutations).toEqual([expect.objectContaining({ type: "restore_seller_sku_review", decision_group_key: "fictional/mapping-1", row_key: null, payload: { change_reason: "虚构来源复核依据" } })]);
      if (state.restoreFailure) { state.restoreFailure = false; return route.fulfill({ status: 409, json: { error: { code: "REVISION_CONFLICT", message: "示例：恢复需重新核对" } } }); }
      state.revision++; row.payload.identity_decision = null; row.projection_state = "included"; state.refreshFailure = true;
      return route.fulfill({ json: { safe_result: { workflow_revision: state.revision } } });
    }
    throw new Error(`Unexpected fictional request: ${req.method()} ${path}`);
  });
  await page.goto("/catalog/imports/42");
  await expect(page.getByRole("heading", { name: "商品主档审核", exact: true })).toBeVisible();
  await page.getByRole("tab", { name: /^SKU 映射/ }).click();
  await page.getByRole("checkbox", { name: "仅看待处理", exact: true }).uncheck();
  await page.getByText("查看归属、冲突与恢复", { exact: true }).click();
  return { state, writes, identityReads: () => identityReads };
}

for (const width of [1280, 390]) {
  test(`actual identity inspect, conflict retry, acknowledged read recovery and reload at ${width}px`, async ({ page, baseURL }, testInfo) => {
    await page.setViewportSize({ width, height: 900 }); const { writes, identityReads } = await fixture(page, baseURL!);
    const panel = page.getByRole("region", { name: "身份归属与审核恢复", exact: true });
    const reason = panel.getByRole("textbox", { name: "恢复审核原因", exact: true });
    await reason.click(); await reason.fill("  虚构来源复核依据  ");
    await panel.getByRole("button", { name: "查看归属与冲突", exact: true }).click();
    await expect(panel.getByRole("alert")).toContainText("归属暂时不可用"); expect(identityReads()).toBe(1);
    await panel.getByRole("button", { name: "查看归属与冲突", exact: true }).click();
    await expect(panel.getByRole("link", { name: "商品 STYLE #8", exact: true })).toHaveAttribute("href", "/catalog/styles/8");
    await expect(panel.getByRole("link", { name: "审核批次 #9", exact: true })).toHaveAttribute("href", "/catalog/imports/9");
    await panel.scrollIntoViewIfNeeded();
    await page.getByRole("region", { name: "当前分类审核表格", exact: true }).evaluate(el => { el.scrollLeft = el.scrollWidth; });
    const box = await panel.boundingBox();
    expect(box).not.toBeNull();
    expect(box!.x).toBeGreaterThanOrEqual(0);
    expect(box!.x + box!.width).toBeLessThanOrEqual(width);
    expect(box!.width).toBeGreaterThan(250);
    await page.screenshot({ path: testInfo.outputPath(`owner-page-${width}.png`), fullPage: true });
    await panel.screenshot({ path: testInfo.outputPath(`owner-panel-${width}.png`) });
    await panel.getByRole("button", { name: "恢复到待审核", exact: true }).click();
    await expect(panel.getByRole("alert")).toContainText("恢复需重新核对"); await expect(reason).toHaveValue("  虚构来源复核依据  "); expect(writes).toHaveLength(1);
    await panel.getByRole("button", { name: "恢复到待审核", exact: true }).click();
    await expect(panel.getByRole("alert")).toContainText("草稿已恢复，最新明细读取失败");
    await expect(panel.getByRole("button", { name: "恢复到待审核", exact: true })).toBeDisabled(); expect(writes).toHaveLength(2);
    await panel.getByRole("button", { name: "重新读取草稿", exact: true }).click();
    await expect(page.getByText("当前修订 4", { exact: true })).toBeVisible();
    await expect(reason).toHaveCount(0); await expect(panel.getByText("草稿已恢复到待审核", { exact: true })).toBeVisible();
    await expect(panel.getByRole("region", { name: "已忽略记录", exact: true })).toContainText("虚构旧忽略记录");
    expect(writes).toHaveLength(2); expect(writes[0]!.key).not.toBe(writes[1]!.key);
    await page.reload(); await page.getByRole("tab", { name: /^SKU 映射/ }).click();
    await page.getByText("查看归属、冲突与恢复", { exact: true }).click(); await expect(reason).toHaveCount(0);
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
  });
}

test("actual unsaved mapping prevents identity reads and restore writes", async ({ page, baseURL }) => {
  const { writes, identityReads } = await fixture(page, baseURL!);
  const panel = page.getByRole("region", { name: "身份归属与审核恢复", exact: true });
  await page.getByLabel("fictional/mapping-1 change_reason", { exact: true }).fill("虚构未保存说明");
  await expect(panel.getByRole("button", { name: "查看归属与冲突", exact: true })).toBeDisabled();
  await expect(panel.getByRole("textbox", { name: "恢复审核原因", exact: true })).toBeDisabled();
  await expect(panel.getByRole("button", { name: "恢复到待审核", exact: true })).toBeDisabled();
  expect(identityReads()).toBe(0); expect(writes).toHaveLength(0);
  await page.getByRole("button", { name: "撤销本行修改", exact: true }).click();
  await expect(panel.getByRole("button", { name: "查看归属与冲突", exact: true })).toBeEnabled();
});
