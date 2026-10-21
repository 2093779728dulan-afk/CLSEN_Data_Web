import { expect, test } from "@playwright/test";

for (const width of [1280, 390]) {
  test(`actual approved history reads, retry, identities and refresh at ${width}px`, async ({ page }) => {
    await page.setViewportSize({ width, height: 900 });
    let values: Array<Record<string, unknown>> = [
      { id: 104, version_number: 4, risk: "normal", approved_at: "2026-09-30 14:20", base_catalog_version_id: 103 },
      { id: 103, version_number: 3, risk: "future_risk_code", approved_at: "2026-09-20 09:40", base_catalog_version_id: 101 },
      { id: 101, version_number: 1, risk: "normal", approved_at: "2026-09-02 16:10", base_catalog_version_id: null },
    ];
    let failed = false; let calls = 0; let release: () => void = () => undefined;
    let gate: Promise<void> | undefined = new Promise<void>(resolve => { release = resolve; });
    const requests: string[] = [];
    await page.route(/^https?:\/\/[^/]+\/api\//, async route => {
      const path = new URL(route.request().url()).pathname; requests.push(path);
      if (route.request().method() !== "GET") throw new Error(`Unexpected write ${path}`);
      if (path === "/api/auth/me") return route.fulfill({ json: { id: 88, username: "fictional-version-reader", display_name: "虚构维护账号", roles: ["data_manager"] } });
      if (path === "/api/data-calendar/site-context") return route.fulfill({ json: { site_id: 1, site_code: "US", display_name: "虚构站点", site_config_version_id: 2, source_timezone: "UTC", reporting_timezone: "UTC", currency_code: "USD" } });
      if (path === "/api/dashboard/style-readiness") return route.fulfill({ json: { published_reports: 0, prerequisites_present: false } });
      if (path === "/api/catalog/versions") {
        calls++; if (gate) await gate;
        if (failed) return route.fulfill({ status: 503, json: { error: { code: "demo_unavailable", message: "fictional" } } });
        return route.fulfill({ json: { versions: values } });
      }
      throw new Error(`Unexpected API ${path}`);
    });
    await page.goto("/catalog/versions"); await expect(page.getByRole("status").filter({ hasText: "正在读取目录版本" })).toBeVisible();
    release(); gate = undefined;
    const table = page.getByRole("table", { name: "已批准目录记录" });
    await expect(table.getByRole("row").nth(1)).toContainText("目录记录 #104");
    await expect(table.getByRole("row").nth(1).getByRole("cell").nth(3)).toHaveText("目录记录 #103");
    await expect(table.getByRole("row").nth(2)).toContainText("future_risk_code");
    await expect(table.getByRole("row").nth(3).getByRole("cell").nth(3)).toHaveText("首次");
    const scroll = table.locator(".."); await scroll.focus(); await expect(scroll).toBeFocused();
    if (width === 390) { await scroll.press("ArrowRight"); await expect.poll(() => scroll.evaluate(element => element.scrollLeft)).toBeGreaterThan(0); }
    failed = true; const before = calls; const reload = page.getByRole("button", { name: "重新读取版本", exact: true }); await reload.focus(); await reload.press("Enter");
    await expect(page.getByRole("alert")).toContainText("无法读取目录版本"); expect(calls).toBe(before + 1); await expect(table).toHaveCount(0);
    failed = false; await page.getByRole("button", { name: "重新读取", exact: true }).click(); await expect(table).toBeVisible(); expect(calls).toBe(before + 2);
    await page.reload(); await expect(table.getByRole("row").nth(1)).toContainText("目录记录 #104");
    values = []; await page.getByRole("button", { name: "重新读取版本" }).click(); await expect(page.getByRole("heading", { name: "尚无已批准目录版本" })).toBeVisible();
    await expect(page.getByRole("link", { name: "前往批量维护完成初始化", exact: true })).toHaveAttribute("href", "/catalog/maintenance");
    await page.reload(); await expect(page.getByRole("heading", { name: "尚无已批准目录版本" })).toBeVisible();
    expect(requests.some(path => path === "/api/catalog/source-scope")).toBe(false);
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
  });
}
