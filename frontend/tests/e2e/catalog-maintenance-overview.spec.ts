import { expect, test } from "@playwright/test";

for (const width of [1280, 390]) {
  test(`actual maintenance entry, prepared-state boundary, dialog recovery and refresh at ${width}px`, async ({ page }, testInfo) => {
    await page.setViewportSize({ width, height: 900 });
    let initialized = true; let prepared = false;
    let release: () => void = () => undefined;
    let gate: Promise<void> | undefined = new Promise<void>(resolve => { release = resolve; });
    const requests: Array<{ path: string; method: string }> = [];
    await page.route(/^https?:\/\/[^/]+\/api\//, async route => {
      const path = new URL(route.request().url()).pathname; const method = route.request().method(); requests.push({ path, method });
      if (method !== "GET") throw new Error(`Unexpected write ${path}`);
      if (path === "/api/auth/me") return route.fulfill({ json: { id: 88, username: "fictional-overview-reader", display_name: "虚构维护账号", roles: ["data_manager"] } });
      if (path === "/api/data-calendar/site-context") return route.fulfill({ json: { site_id: 1, site_code: "US", display_name: "虚构站点", site_config_version_id: 2, source_timezone: "UTC", reporting_timezone: "UTC", currency_code: "USD" } });
      if (path === "/api/catalog/styles") { if (gate) await gate; return route.fulfill({ json: { catalog: initialized ? { catalog_version_id: 104, version_number: 4, catalog_publication_revision: 7, styles: [], skus: [] } : null } }); }
      if (path === "/api/catalog/versions") return route.fulfill({ json: { versions: [{ id: 104, version_number: 4, risk: "normal", approved_at: "2026-09-30", base_catalog_version_id: 103 }] } });
      if (path === "/api/catalog/imports") return route.fulfill({ json: { items: [], has_next: false } });
      if (path === "/api/catalog/exports/latest") return route.fulfill({ json: { export: null } });
      if (path === "/api/dashboard/style-readiness") return route.fulfill({ json: { published_reports: 2, published_business_reports: 1, published_return_reports: 1, source_scope_confirmed: prepared, return_snapshot_present: prepared, catalog_approved: initialized, prerequisites_present: initialized && prepared, coverage_from: "2026-09-01", coverage_to: "2026-09-30" } });
      if (path === "/api/catalog/source-scope") return route.fulfill({ json: { marketplace_scope_code: "amazon_us", permissions: { can_confirm: false }, report_source_scope_id: 1, seller_account_display_name: "虚构账号", site_config_revision: 3, site_config_version_id: 2, status: prepared ? "confirmed" : "unconfirmed" } });
      throw new Error(`Unexpected API ${path}`);
    });
    const url = "/catalog/maintenance?return_to=%2Fcatalog%2Funmatched%3Fpage%3D2";
    await page.goto(url);
    await expect(page.getByRole("status").filter({ hasText: "正在读取建档与维护" })).toBeVisible();
    release(); gate = undefined;
    await expect(page.getByText("当前目录 V4", { exact: true })).toBeVisible();
    await expect(page.getByRole("region", { name: "已有审核批次", exact: true })).toBeVisible();
    await page.getByRole("button", { name: "目录维护", exact: true }).click();
    const dialog = page.getByRole("dialog", { name: "目录维护", exact: true });
    const generate = dialog.getByRole("button", { name: "生成候选", exact: true });
    await expect(generate).toBeDisabled();
    await expect(dialog.getByText("来源准备尚未完成", { exact: true })).toBeVisible();
    await expect(dialog.getByLabel("上传已修改的目录维护工作簿")).toBeEnabled();
    await dialog.getByRole("button", { name: "关闭对话框" }).click();
    await expect(page).toHaveURL(new RegExp(url.replaceAll("?", "\\?")));
    prepared = true;
    await page.getByRole("button", { name: "目录维护", exact: true }).click();
    await expect(generate).toBeEnabled();
    await dialog.screenshot({ path: testInfo.outputPath(`actual-maintenance-${width}.png`) });
    await dialog.getByRole("button", { name: "关闭对话框" }).click();
    await page.reload();
    await expect(page.getByText("当前目录 V4", { exact: true })).toBeVisible();
    initialized = false; prepared = false;
    await page.reload();
    await expect(page.getByText("尚未建立目录", { exact: true })).toBeVisible();
    await page.getByRole("button", { name: "目录维护", exact: true }).click();
    await expect(generate).toBeDisabled();
    await expect(dialog.getByLabel("上传已修改的目录维护工作簿")).toBeEnabled();
    expect(requests.filter(request => request.method !== "GET")).toEqual([]);
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
  });
}
