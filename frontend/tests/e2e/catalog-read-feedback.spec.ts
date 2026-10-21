import { expect, test, type Page } from "@playwright/test";

const readiness = { catalog_approved: false, coverage_from: "2026-07-01", coverage_to: "2026-08-06", prerequisites_present: false, published_business_reports: 37, published_reports: 74, published_return_reports: 37, return_snapshot_present: false, source_scope_confirmed: false };
const scope = { marketplace_scope_code: "amazon_us", permissions: { can_confirm: false }, report_source_scope_id: null, seller_account_display_name: null, site_config_revision: 3, site_config_version_id: 2, status: "unconfirmed" };
async function fixture(page: Page, failureStatus: number, setup = false, partial = false) {
  let reads = 0; let recovered = false; let setupFailed = true; let sourceReads = 0;
  const requests: string[] = [];
  await page.route(/^https?:\/\/[^/]+\/api\//, async route => {
    const path = new URL(route.request().url()).pathname;
    if (route.request().method() !== "GET") throw new Error(`Unexpected write ${path}`);
    requests.push(path);
    if (path === "/api/auth/me") return route.fulfill({ json: { id: 88, username: "fictional-reader", display_name: "虚构读取账号", roles: ["data_manager"] } });
    if (path === "/api/data-calendar/site-context") return route.fulfill({ json: { site_id: 1, site_code: "US", display_name: "虚构站点", site_config_version_id: 2, source_timezone: "UTC", reporting_timezone: "UTC", currency_code: "USD" } });
    if (path === "/api/dashboard/style-readiness") return route.fulfill({ json: readiness });
    if (path === "/api/catalog/source-scope") {
      sourceReads++;
      if (setupFailed) return route.fulfill({ status: 503, json: { error: { code: "demo_unavailable", message: "fictional" } } });
      return route.fulfill({ json: scope });
    }
    if (partial && path === "/api/catalog/unmatched") {
      const query = new URL(route.request().url()).searchParams;
      expect(query.get("from")).toBe("2026-09-01"); expect(query.get("to")).toBe("2026-09-30");
      return route.fulfill({ json: { page: 1, page_size: 25, total_items: 1, range: { from_date: "2026-09-01", to_date: "2026-09-30", return_basis: "event_date" }, baseline: { catalog_version_id: 4, catalog_publication_revision: 7, consistent_as_of: "2026-10-01T00:00:00Z", fact_basis: "current", publication_refs: [{ version_id: 1 }] }, impact: { business_fact_rows: 1, units: 14, sales_by_currency: [{ currency_code: "USD", value: "419.46" }], return_fact_rows: 0, return_quantity: 0, unresolved_return_rows: 0 }, items: [{ source_identity: { report_source_scope_id: 1, seller_sku_match: "fictional-source", seller_sku_sha256: "fictional-hash" }, source_ref_id: null, preview: "DEMO-Light-Blue-XL", digest: "fictional-hash", is_unsafe: false, is_truncated: false, report_types: ["business_report"], first_seen_date: "2026-09-01", latest_seen_date: "2026-09-30", published_version_ids: ["1"], business: { rows: 1, units: 14, sales_by_currency: [{ currency_code: "USD", value: "419.46" }] }, returns: { rows: 0, quantity: 0, unresolved_rows: 0 }, candidate: { status: "not_started", review_path: null } }] } });
    }
    if (partial && path === "/api/catalog/styles") {
      if (!recovered) return route.fulfill({ status: 503, json: { error: { code: "demo_unavailable", message: "fictional" } } });
      return route.fulfill({ json: { catalog: { catalog_version_id: 4, version_number: 4, catalog_publication_revision: 7, styles: [], skus: [] } } });
    }
    if (path === (setup ? "/api/catalog/unmatched" : "/api/catalog/versions")) {
      reads++;
      if (!recovered || setup) return route.fulfill({ status: failureStatus, json: { error: { code: setup ? "catalog_snapshot_unavailable" : "demo_read_failure", message: "fictional" } } });
      return route.fulfill({ json: { versions: [{ id: 4, version_number: 4, risk: "normal", approved_at: "2026-09-30", base_catalog_version_id: 3 }] } });
    }
    throw new Error(`Unexpected API ${path}`);
  });
  return { requests, reads: () => reads, sourceReads: () => sourceReads, recover: () => { recovered = true; }, recoverSetup: () => { setupFailed = false; } };
}
for (const width of [1280, 390]) {
  test(`actual versions repeated failure, keyboard retry, restored record and refresh at ${width}px`, async ({ page }) => {
    await page.setViewportSize({ width, height: 900 }); const f = await fixture(page, 503);
    await page.goto("/catalog/versions");
    await expect(page.getByRole("alert")).toContainText("无法读取目录版本");
    await page.getByRole("button", { name: "重新读取", exact: true }).click();
    await expect.poll(f.reads).toBe(3); await expect(page.getByRole("alert")).toBeVisible();
    f.recover(); const retry = page.getByRole("button", { name: "重新读取", exact: true }); await retry.focus(); await retry.press("Enter");
    await expect(page.getByRole("table").getByText("V4", { exact: true })).toBeVisible();
    await page.reload(); await expect(page.getByRole("table").getByText("V4", { exact: true })).toBeVisible();
    expect(f.sourceReads()).toBe(0); expect(f.reads()).toBe(6);
  });
  test(`actual missing snapshot, failed preparation read, explicit refresh and read-only recovery at ${width}px`, async ({ page }) => {
    await page.setViewportSize({ width, height: 900 }); const f = await fixture(page, 409, true);
    await page.goto("/catalog/unmatched?from=2026-09-01&to=2026-09-30");
    await expect(page.getByRole("heading", { name: "待处理清单尚未就绪", exact: true })).toBeVisible();
    await expect(page.getByRole("alert").filter({ hasText: "无法读取初始化状态" })).toBeVisible();
    // StrictMode may abort its first read before the request reaches the fixture.
    const sourceReadsBeforeRefresh = f.sourceReads();
    const refreshedScope = page.waitForResponse(response => new URL(response.url()).pathname === "/api/catalog/source-scope" && response.status() === 200);
    f.recoverSetup(); await page.getByRole("button", { name: "刷新准备状态" }).click();
    await refreshedScope;
    await expect(page.getByRole("region", { name: "商品分析初始化" })).toContainText("74");
    await expect(page.getByRole("button", { name: /确认来源范围|准备首次退货快照|确认建立首次快照|^重新读取$/ })).toHaveCount(0);
    await expect(page.getByRole("link", { name: "前往批量维护，完成初始化", exact: true })).toHaveAttribute("href", "/catalog/maintenance");
    expect(f.sourceReads()).toBe(sourceReadsBeforeRefresh + 1); expect(f.reads()).toBe(2);
    await page.reload(); await expect(page.getByRole("region", { name: "商品分析初始化" })).toContainText("74");
    expect(f.reads()).toBe(4);
  });
}
for (const status of [403, 404, 422, 429]) {
  test(`actual ${status} preserves error policy and does not disclose setup`, async ({ page }) => {
    const f = await fixture(page, status); await page.goto("/catalog/versions");
    await expect(page.getByRole("alert")).toBeVisible();
    await expect(page.getByRole("region", { name: "商品分析初始化" })).toHaveCount(0);
    if (status === 429) {
      f.recover(); await page.getByRole("button", { name: "重新读取", exact: true }).click();
      await expect(page.getByRole("table").getByText("V4", { exact: true })).toBeVisible();
    } else {
      await expect(page.getByRole("button", { name: "重新读取", exact: true })).toHaveCount(0);
      await expect(page.getByRole("link", { name: "返回商品主档", exact: true })).toHaveAttribute("href", "/catalog");
      expect(f.reads()).toBe(2);
    }
    expect(f.sourceReads()).toBe(0);
  });
}

for (const width of [1280, 390]) {
  test(`actual partial candidate failure retains source evidence and query at ${width}px`, async ({ page }) => {
    await page.setViewportSize({ width, height: 900 }); const f = await fixture(page, 503, false, true);
    const path = "/catalog/unmatched?from=2026-09-01&to=2026-09-30&return_basis=event_date";
    await page.goto(path);
    await expect(page.getByRole("alert")).toContainText("无法读取已有审核候选");
    await expect(page.getByText("DEMO-Light-Blue-XL", { exact: true })).toBeVisible();
    f.recover(); await page.getByRole("button", { name: "重新读取", exact: true }).click();
    await expect(page.getByText("当前没有关联到已生效商品的审核候选。", { exact: true })).toBeVisible();
    await expect(page.getByText("DEMO-Light-Blue-XL", { exact: true })).toBeVisible();
    await expect(page).toHaveURL(new RegExp(path.replaceAll("?", "\\?")));
    await page.reload(); await expect(page.getByText("DEMO-Light-Blue-XL", { exact: true })).toBeVisible();
    expect(f.sourceReads()).toBe(0);
  });
}
