import { expect, test } from "@playwright/test";
import type { CatalogUnmatchedResponse } from "../../src/features/catalog/catalogApi";

const style = { style_id: 1001, style_code: "DEMO-01", standard_name: "虚构商品", category_id: null, category_code: null, category_name: null, category_recorded: true, status: "enabled", revision: 3, variant_count: 0, seller_sku_count: 0, source_summary: { first_seen_date: null, latest_seen_date: null, observation_count: 0, source_report_count: 0 } };
for (const width of [1280, 390]) {
  test(`actual unmatched queries, partial failure, paging, review and refresh at ${width}px`, async ({ page }, testInfo) => {
    await page.setViewportSize({ width, height: 900 });
    let pendingFailed = true; let pageFailed = false; let laterEmpty = false; let canReview = true;
    const requests: Array<{ path: string; method: string }> = [];
    await page.route(/^https?:\/\/[^/]+\/api\//, async route => {
      const url = new URL(route.request().url()); const path = url.pathname; const method = route.request().method(); requests.push({ path, method });
      if (method !== "GET") throw new Error(`Unexpected write ${path}`);
      if (path === "/api/auth/me") return route.fulfill({ json: { id: 88, username: "fictional-source-reader", display_name: "虚构来源账号", roles: ["data_manager"] } });
      if (path === "/api/data-calendar/site-context") return route.fulfill({ json: { site_id: 1, site_code: "US", display_name: "虚构站点", site_config_version_id: 2, source_timezone: "UTC", reporting_timezone: "UTC", currency_code: "USD" } });
      if (path === "/api/dashboard/style-readiness") return route.fulfill({ json: { published_reports: 2, prerequisites_present: true, catalog_approved: true } });
      if (path === "/api/catalog/unmatched") {
        expect(url.searchParams.get("from")).toBe("2026-09-01"); expect(url.searchParams.get("to")).toBe("2026-09-30"); expect(url.searchParams.get("return_basis")).toBe("report_date"); expect(url.searchParams.get("page_size")).toBe("25");
        const n = Number(url.searchParams.get("page"));
        if (n === 2 && pageFailed) return route.fulfill({ status: 503, json: { error: { code: "UNAVAILABLE" } } });
        const response: CatalogUnmatchedResponse = { page: n, page_size: 25, total_items: 26, range: { from_date: "2026-09-01", to_date: "2026-09-30", return_basis: "report_date" }, baseline: { catalog_version_id: 104, catalog_publication_revision: 7, consistent_as_of: "2026-09-30T18:00:00Z", fact_basis: "current", publication_refs: [{ version_id: "fictional" }] }, impact: { business_fact_rows: 26, units: 26, sales_by_currency: [{ currency_code: "USD", value: "250.00" }, { currency_code: "EUR", value: "20.00" }], return_fact_rows: 1, return_quantity: 1, unresolved_return_rows: 1 }, items: n === 2 && laterEmpty ? [] : Array.from({ length: n === 1 ? 25 : 1 }, (_, i) => { const id = n === 1 ? i + 1 : 26; return { source_identity: { report_source_scope_id: 1, seller_sku_match: `fictional-${id}`, seller_sku_sha256: `fictional-${id}` }, source_ref_id: null, preview: `DEMO-SOURCE-${id}`, digest: `fictional-${id}`, is_unsafe: false, is_truncated: false, report_types: ["business_report"], first_seen_date: "2026-09-01", latest_seen_date: "2026-09-30", published_version_ids: ["fictional"], business: { rows: 1, units: 1, sales_by_currency: [{ currency_code: id === 26 ? "EUR" : "USD", value: id === 26 ? "20.00" : "10.00" }] }, returns: { rows: id === 26 ? 1 : 0, quantity: id === 26 ? 1 : 0, unresolved_rows: id === 26 ? 1 : 0 }, candidate: { status: "in_review", review_path: "/catalog/imports/42" } }; }) };
        return route.fulfill({ json: response });
      }
      if (path === "/api/catalog/styles") return route.fulfill({ json: { catalog: { catalog_version_id: 104, version_number: 4, catalog_publication_revision: 7, styles: [style], skus: [] } } });
      if (path === "/api/catalog/styles/1001/pending-items") {
        if (pendingFailed) return route.fulfill({ status: 503, json: { error: { code: "UNAVAILABLE" } } });
        return route.fulfill({ json: { items: [{ import_id: 42, review_path: "/catalog/imports/42", seller_sku_count: 2, seller_sku_previews: ["DEMO-PENDING"], status: "needs_attention", updated_at: "2026-09-30", variant_count: 1, workflow_revision: 3 }], permissions: { can_review: canReview } } });
      }
      if (path === "/api/catalog/styles/1001") return route.fulfill({ json: { catalog_version_id: 104, catalog_publication_revision: 7, permissions: { can_edit: false, can_manage_categories: false }, style, skus: [] } });
      if (path === "/api/catalog/imports/42") return route.fulfill({ json: { import_id: 42, workflow_revision: 3, catalog_publication_revision: 7, base_catalog_version_id: 104, export_id: 8001, parse_attempt_revision: 1, source_kind: "online", status: "needs_attention", issues: [], failure_reason_code: null, has_original_file: false, submitted_by_user_id: 88, validation_run_id: null, permissions: { can_view: true, can_edit: false, can_preview: false, can_approve_normal: false, can_approve_high_risk: false, can_rebase: false, can_reject: false, can_withdraw: false, can_resume: false, can_validate: false, can_submit: false, can_download_original: false } } });
      if (path.startsWith("/api/catalog/imports/42/rows/")) return route.fulfill({ json: { rows: [], total_rows: 0, workflow_revision: 3 } });
      throw new Error(`Unexpected API ${path}`);
    });
    const path = "/catalog/unmatched?from=2026-09-01&to=2026-09-30&return_basis=report_date&return_to=%2Fproducts%3Fmonth%3D2026-09";
    await page.goto(path); await expect(page.getByRole("alert")).toContainText("无法读取已有审核候选");
    const sources = page.getByRole("region", { name: "来源清单", exact: true }); await expect(sources.getByRole("listitem")).toHaveCount(25);
    await expect(page.getByRole("region", { name: "待归属来源核对", exact: true })).toContainText("US$250.00 · EUR 20.00");
    pendingFailed = false; const retry = page.getByRole("button", { name: "重新读取", exact: true }); await retry.focus(); await retry.press("Enter"); await expect(page.getByText("DEMO-PENDING", { exact: true })).toBeVisible();
    pageFailed = true; await page.getByRole("button", { name: "下一页", exact: true }).click(); await expect(page.getByRole("alert")).toContainText("无法读取待归属来源"); await expect(page).toHaveURL(/page=2/);
    pageFailed = false; await page.getByRole("button", { name: "重新读取", exact: true }).click(); await expect(sources.getByRole("listitem")).toHaveCount(1); await expect(sources).toContainText("DEMO-SOURCE-26"); await expect(sources).toContainText("1 件 · EUR 20.00");
    await page.getByRole("link", { name: "DEMO-01 · 虚构商品", exact: true }).click(); await expect(page.getByRole("link", { name: "返回商品主档", exact: true })).toHaveAttribute("href", `${path}&page=2`); await page.getByRole("link", { name: "返回商品主档", exact: true }).click();
    const review = sources.getByRole("link", { name: "继续审核", exact: true }); await review.focus(); await review.press("Enter"); await expect(page).toHaveURL(/\/catalog\/imports\/42$/); await expect(page.getByRole("link", { name: "返回来源页面", exact: true })).toBeVisible(); await page.goBack(); await expect(sources).toContainText("DEMO-SOURCE-26");
    const maintenance = await page.getByRole("link", { name: "生成或继续审核候选", exact: true }).getAttribute("href"); expect(new URL(maintenance!, "http://localhost").searchParams.get("return_to")).toBe(`${path}&page=2`);
    await page.screenshot({ path: testInfo.outputPath(`actual-unmatched-${width}.png`), fullPage: true }); await page.reload(); await expect(sources).toContainText("DEMO-SOURCE-26");
    laterEmpty = true; await page.reload(); await expect(page.getByRole("heading", { name: "本页没有来源记录" })).toBeVisible(); await page.getByRole("button", { name: "上一页", exact: true }).click(); await expect(sources.getByRole("listitem")).toHaveCount(25);
    canReview = false; await page.reload(); await expect(page.getByText("当前没有关联到已生效商品的审核候选。", { exact: true })).toBeVisible(); await expect(sources.getByRole("listitem")).toHaveCount(25);
    await expect(page.getByRole("link", { name: "返回产品分析", exact: true })).toHaveAttribute("href", "/products?month=2026-09"); expect(requests.filter(request => request.method !== "GET")).toEqual([]); expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
  });
}
