import { expect, test, type Page } from "@playwright/test";

async function fixture(page: Page, edit = false) {
  const requests: Array<{ path: string; method: string; page: string | null }> = [];
  const mode = { styleStatus: 0, evidenceStatus: 0, name: "示例完整商品", revision: 1, publication: 4, approvalRefreshFailure: false, approvals: 0 };
  const summary = { first_seen_date: "2026-07-01", latest_seen_date: "2026-09-30", observation_count: 30, source_report_count: 3 };
  const ref = (id: string, text: string, unsafe = false, truncated = false) => ({ source_ref_id: id, preview: text, digest: `sha256:${"a".repeat(64)}`, is_unsafe: unsafe, is_truncated: truncated });
  const style = () => ({ style_id: 700, style_code: "DEMO-01", standard_name: mode.name, category_id: 1, category_code: "SHIRT", category_name: "示例分类", category_recorded: true, status: "enabled", revision: mode.revision, variant_count: 2, seller_sku_count: 52, source_summary: summary });
  const skus = ["蓝", "白"].map((color, i) => ({ sku_id: 900 + i, style_id: 700, internal_display_sku: `DEMO-${color}-M`, standard_color: color, standard_size: "M", status: "enabled", revision: 1, seller_sku_count: i ? 1 : 51, source_summary: summary }));
  const preview = { after: { standard_name: "示例修改名称", category: { category_id: 1, code: "SHIRT", display_name: "示例分类" } }, before: { standard_name: mode.name, category: { category_id: 1, code: "SHIRT", display_name: "示例分类" } }, base_catalog_publication_revision: 4, draft_id: 30, draft_revision: 1, status: "draft", style_code: "DEMO-01", style_id: 700 };
  await page.route(/^https?:\/\/[^/]+\/api\//, async route => {
    const url = new URL(route.request().url()); const path = url.pathname;
    if (!edit && route.request().method() !== "GET") throw new Error(`Unexpected fixture write: ${path}`);
    requests.push({ path, method: route.request().method(), page: url.searchParams.get("page") });
    if (path === "/api/auth/me") return route.fulfill({ json: { id: 88, username: "synthetic-detail-reader", display_name: "虚构详情账号", roles: [edit ? "data_manager" : "viewer"] } });
    if (path === "/api/data-calendar/site-context") return route.fulfill({ json: { site_id: 1, site_code: "US", display_name: "示例站点", site_config_version_id: 2, source_timezone: "UTC", reporting_timezone: "UTC", currency_code: "USD" } });
    if (path === "/api/dashboard/style-readiness") return route.fulfill({ json: { prerequisites_present: true, catalog_approved: true, published_reports: 0 } });
    if (path === "/api/catalog/source-scope") return route.fulfill({ json: { status: "unconfirmed", permissions: { can_confirm: false }, site_config_revision: 1 } });
    if (path === "/api/catalog/styles") return route.fulfill({ json: { catalog: { catalog_version_id: 3, catalog_publication_revision: mode.publication, version_number: 3, skus: [], styles: [style()] } } });
    if (path === "/api/catalog/styles/700") {
      if (mode.styleStatus) return route.fulfill({ status: mode.styleStatus, json: { error: { code: "UNAVAILABLE" } } });
      await new Promise(resolve => setTimeout(resolve, 100));
      return route.fulfill({ json: { catalog_version_id: 3, catalog_publication_revision: mode.publication, style: style(), skus, permissions: { can_edit: edit, can_manage_categories: false } } });
    }
    if (path === "/api/catalog/styles/700/pending-items") return route.fulfill({ json: { items: [], permissions: { can_review: edit } } });
    if (path === "/api/catalog/variants/900/seller-skus") {
      const pageNo = Number(url.searchParams.get("page"));
      return route.fulfill({ json: { page: pageNo, page_size: 50, total_items: 51, items: Array.from({ length: pageNo === 1 ? 50 : 1 }, (_, i) => ({ mapping_id: (pageNo - 1) * 50 + i + 1, mapping_status: "mapped", seller_account: "虚构美国账号", marketplace: "amazon_us", seller_sku: ref(`demo:${i}`, `DEMO-ALIAS-${(pageNo - 1) * 50 + i + 1}`), source_summary: summary })) } });
    }
    if (path === "/api/catalog/variants/900/evidence") {
      if (mode.evidenceStatus) return route.fulfill({ status: mode.evidenceStatus, json: { error: { code: "UNAVAILABLE" } } });
      const pageNo = Number(url.searchParams.get("page"));
      return route.fulfill({ json: { page: pageNo, page_size: 50, total_items: 51, items: Array.from({ length: pageNo === 1 ? 50 : 1 }, (_, i) => ({ evidence_id: (pageNo - 1) * 50 + i + 1, dataset_id: 1, report_type: pageNo === 1 ? "business_report" : "return_report", report_date: "2026-07-03", event_date: "2026-07-02", published_version_id: 7, source_row_id: 44 + i, source_filename: "synthetic.csv", source_record_number: 5 + i, source_event_timestamp: "2026-07-02T23:00:00-07:00", source_timezone: "America/Los_Angeles", seller_sku: pageNo === 2 ? ref("demo:unsafe", "<script>unsafe</script>") : ref(`demo:safe:${i}`, `DEMO-ALIAS-${i + 1}`), title: pageNo === 2 ? ref("demo:title", "截断标题…", false, true) : null, child_asin: null, parent_asin: null, fnsku: null, evidence_digest: `sha256:${"b".repeat(64)}` })) } });
    }
    if (path === "/api/catalog/categories") return route.fulfill({ json: { categories: [{ category_id: 1, code: "SHIRT", display_name: "示例分类", status: "enabled", aliases: [] }] } });
    if (path === "/api/catalog/styles/700/change-drafts") {
      const body = route.request().postDataJSON() as Record<string, unknown>;
      expect(body.expected_style_revision).toBe(1); expect(body.expected_catalog_publication_revision).toBe(4);
      expect(body.standard_name).toBe("示例修改名称");
      return route.fulfill({ json: { draft_id: 30 } });
    }
    if (path === "/api/catalog/style-change-drafts/30") return route.fulfill({ json: preview });
    if (path === "/api/catalog/style-change-drafts/30/approve") {
      mode.approvals++; mode.name = "示例修改名称"; mode.revision = 2; mode.publication = 5;
      if (mode.approvalRefreshFailure) mode.styleStatus = 503;
      return route.fulfill({ json: { catalog_version_id: 4, catalog_publication_revision: 5 } });
    }
    if (!edit) throw new Error(`Unexpected fictional read: ${path}`);
    return route.fulfill({ json: {} });
  });
  if (edit) {
    const baseURL = test.info().project.use.baseURL;
    if (!baseURL) throw new Error("Synthetic fixture needs its configured base URL");
    await page.context().addCookies([{ name: "clsen_csrf", url: baseURL, value: "synthetic-detail-csrf" }]);
  }
  await page.goto(edit ? "/catalog/styles/700" : "/catalog");
  return { mode, requests };
}

for (const width of [1280, 390]) {
  test(`real detail route keeps stable identity, lazy pages, safety and list return at ${width}px`, async ({ page }, testInfo) => {
    await page.setViewportSize({ width, height: 900 });
    const { mode, requests } = await fixture(page);
    const search = page.getByRole("searchbox", { name: "查找商品" }); await search.fill("DEMO-01");
    await page.getByRole("button", { name: "快速查看 DEMO-01", exact: true }).click();
    await page.getByRole("dialog").getByRole("link", { name: "打开完整商品卡" }).click();
    await expect(page).toHaveURL(/\/catalog\/styles\/700$/);
    await expect(page.getByRole("heading", { name: "示例完整商品", exact: true })).toBeVisible();
    expect(requests.filter(item => item.path.includes("/variants/")).length).toBe(0);
    await expect(page.getByText("系统永久身份 STYLE #700", { exact: true })).toBeVisible();
    const filter = page.getByRole("searchbox", { name: "查找实际变体" }); await filter.fill("白");
    await expect(page.getByRole("article")).toHaveCount(1); await page.getByRole("button", { name: "重置筛选", exact: true }).click();
    const first = page.getByRole("article", { name: "变体 DEMO-蓝-M", exact: true });
    await first.getByRole("button", { name: "展开 Seller SKU", exact: true }).click();
    const aliases = first.getByRole("region", { name: "关联 Seller SKU", exact: true });
    await expect(aliases.getByRole("table").locator("tbody tr")).toHaveCount(50);
    await aliases.getByRole("button", { name: "下一页", exact: true }).click();
    await expect(aliases.getByText("DEMO-ALIAS-51", { exact: true })).toBeVisible();
    await expect(aliases.getByLabel("来源摘要后八位", { exact: true })).toHaveText("aaaaaaaa");
    expect(requests.some(item => item.path === "/api/catalog/variants/900/evidence")).toBe(false);
    await aliases.getByRole("button", { name: "查看来源明细", exact: true }).click();
    const evidence = first.getByRole("region", { name: "来源明细", exact: true });
    await expect(evidence.locator("li")).toHaveCount(50);
    mode.evidenceStatus = 503;
    await evidence.getByRole("button", { name: "下一页", exact: true }).click();
    await expect(first.getByRole("alert")).toContainText("来源明细读取未完成");
    mode.evidenceStatus = 0;
    await first.getByRole("button", { name: "重新读取来源明细", exact: true }).click();
    await expect(evidence.getByText("原始退货时间：2026-07-02T23:00:00-07:00", { exact: true })).toBeVisible();
    await expect(evidence.getByRole("button", { name: "复制 SKU" })).toHaveCount(0);
    await expect(evidence.getByText("[含危险字符的来源]", { exact: true })).toBeVisible();
    await expect(evidence.getByText("已截断", { exact: true })).toBeVisible();
    await evidence.getByText("系统追溯信息", { exact: true }).click();
    await expect(evidence.getByText("系统版本编号 7 · 系统记录编号 44（非文件行号）", { exact: true })).toBeVisible();
    await expect(evidence.getByRole("link", { name: "查看来源报告版本" })).toHaveAttribute("href", "/versions?report_date=2026-07-03&report_type=return_report");
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
    await page.screenshot({ path: testInfo.outputPath(`detail-route-${width}.png`) });
    await page.getByRole("link", { name: "返回商品主档", exact: true }).click(); await expect(search).toHaveValue("DEMO-01");
    await page.getByRole("link", { name: "查看 DEMO-01 商品卡", exact: true }).click();
    await page.reload(); await expect(page.getByRole("heading", { name: "示例完整商品", exact: true })).toBeVisible();
    await expect(page.getByRole("table")).toHaveCount(0);
    mode.styleStatus = 403; await page.getByRole("button", { name: "刷新商品详情", exact: true }).click();
    await expect(page.getByRole("alert")).toContainText("没有查看此商品主档页面的权限");
    await expect(page.getByRole("heading", { name: "示例完整商品", exact: true })).toHaveCount(0);
    await expect(page.getByRole("button", { name: "刷新商品详情", exact: true })).toBeDisabled();
    expect(requests.filter(item => item.method !== "GET")).toEqual([]);
  });
}

test("existing approval observes refresh failure and recovers without a second approval", async ({ page }) => {
  const { mode } = await fixture(page, true);
  await page.getByRole("button", { name: "修改名称 / 分类", exact: true }).click();
  await page.getByRole("textbox", { name: "标准商品名称", exact: true }).fill("示例修改名称");
  await page.getByRole("button", { name: "生成变更预览", exact: true }).click();
  await expect(page.getByText("批准后", { exact: true })).toBeVisible();
  mode.approvalRefreshFailure = true;
  await page.getByRole("button", { name: "批准并生成新目录版本", exact: true }).click();
  await expect(page.getByText("刷新未完成，当前显示上次读取的商品", { exact: true })).toBeVisible();
  await expect(page.getByRole("region", { name: "单商品修改", exact: true })).toBeVisible();
  expect(mode.approvals).toBe(1);
  mode.styleStatus = 0;
  await page.getByRole("button", { name: "刷新商品详情", exact: true }).click();
  await expect(page.getByRole("heading", { name: "示例修改名称", exact: true })).toBeVisible();
  await page.getByRole("button", { name: "关闭修改", exact: true }).click();
  await expect(page.getByRole("button", { name: "修改名称 / 分类", exact: true })).toBeVisible();
  expect(mode.approvals).toBe(1);
});
