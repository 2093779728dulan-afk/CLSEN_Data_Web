import { expect, test } from "@playwright/test";
import type { CatalogCategory } from "../../src/features/catalog/catalogApi";

for (const width of [1280, 390]) {
  test(`actual category editor preserves identities, writes and refreshed results at ${width}px`, async ({ page }) => {
    await page.setViewportSize({ width, height: 900 });
    const baseURL = test.info().project.use.baseURL;
    if (!baseURL) throw new Error("Synthetic editor fixture requires its configured base URL");
    await page.context().addCookies([{ name: "clsen_csrf", url: baseURL, value: "synthetic-editor-csrf" }]);
    let rows: CatalogCategory[] = [{ category_id: 7, code: "DRESS", display_name: "连衣裙", aliases: [], status: "enabled" }, { category_id: 8, code: "DRESS_MINI", display_name: "短款连衣裙", parent_category_id: 7, aliases: [], status: "enabled" }];
    let firstRead = true;
    let failSave = true;
    let canManage = true;
    const writes: Array<{ path: string; method: string; body: Record<string, unknown> }> = [];
    await page.route(/^https?:\/\/[^/]+\/api\//, async route => {
      const path = new URL(route.request().url()).pathname;
      const method = route.request().method();
      if (path === "/api/auth/me") return route.fulfill({ json: { id: 88, username: "synthetic-editor", display_name: "虚构维护账号", roles: [canManage ? "data_manager" : "viewer"] } });
      if (path === "/api/data-calendar/site-context") return route.fulfill({ json: { site_id: 1, site_code: "US", display_name: "示例站点", site_config_version_id: 2, source_timezone: "UTC", reporting_timezone: "UTC", currency_code: "USD" } });
      if (path === "/api/dashboard/style-readiness") return route.fulfill({ json: { prerequisites_present: true, catalog_approved: true, published_reports: 0 } });
      if (path === "/api/catalog/styles/700") return route.fulfill({ json: { catalog_version_id: 3, catalog_publication_revision: 4, style: { style_id: 700, style_code: "DEMO-01", standard_name: "示例商品", category_id: 7, category_code: "DRESS", category_name: "连衣裙", category_recorded: true, status: "enabled", revision: 1, variant_count: 0, seller_sku_count: 0, source_summary: { first_seen_date: null, latest_seen_date: null, observation_count: 0, source_report_count: 0 } }, skus: [], permissions: { can_edit: canManage, can_manage_categories: canManage } } });
      if (path === "/api/catalog/styles/700/pending-items") return route.fulfill({ json: { items: [], permissions: { can_review: canManage } } });
      if (path === "/api/catalog/categories" && method === "GET") {
        if (firstRead) { firstRead = false; return route.fulfill({ status: 503, json: { error: { code: "UNAVAILABLE" } } }); }
        return route.fulfill({ json: { categories: rows } });
      }
      if (method !== "GET") {
        const body = route.request().postDataJSON() as Record<string, unknown>;
        writes.push({ path, method, body });
        expect(body.operation_token).toEqual(expect.any(String));
        expect(route.request().headers()["x-csrf-token"]).toBe("synthetic-editor-csrf");
        if (path === "/api/catalog/categories/8" && method === "PUT") {
          if (failSave) { failSave = false; return route.fulfill({ status: 409, json: { error: { code: "CONFLICT" } } }); }
          const previous = rows.find(item => item.category_id === 8);
          if (!previous) throw new Error("Synthetic category 8 missing");
          const saved: CatalogCategory = { ...previous, code: body.code as string, display_name: body.display_name as string, aliases: body.aliases as string[], parent_category_id: body.parent_category_id as number, status: body.status as CatalogCategory["status"] };
          rows = rows.map(item => item.category_id === 8 ? saved : item); return route.fulfill({ json: saved });
        }
        if (path === "/api/catalog/categories" && method === "POST") {
          const saved: CatalogCategory = { category_id: 11, code: body.code as string, display_name: body.display_name as string, parent_category_id: body.parent_category_id as number | null, aliases: body.aliases as string[], status: "enabled" };
          rows.push(saved); return route.fulfill({ json: saved });
        }
        throw new Error(`Unexpected synthetic write: ${method} ${path}`);
      }
      return route.fulfill({ json: {} });
    });
    await page.goto("/catalog/styles/700");
    await page.getByRole("button", { name: "管理分类", exact: true }).click();
    await expect(page.getByRole("alert")).toContainText("分类字典读取未完成");
    await expect(page.getByRole("textbox", { name: "分类名称", exact: true })).toBeDisabled();
    await page.getByRole("button", { name: "重新读取分类", exact: true }).click();
    await page.getByRole("button", { name: "编辑 短款连衣裙", exact: true }).click();
    await page.getByRole("textbox", { name: "分类 8 代码", exact: true }).fill("dress_mini_new");
    await page.getByRole("textbox", { name: "分类别名", exact: true }).fill(" Mini dress ， 短裙 ");
    await page.getByRole("button", { name: "保存修改", exact: true }).click();
    await expect(page.getByRole("alert")).toContainText("保存失败");
    await expect(page.getByRole("textbox", { name: "分类 8 代码", exact: true })).toHaveValue("DRESS_MINI_NEW");
    await page.getByRole("button", { name: "保存修改", exact: true }).click();
    await expect(page.getByText("分类已保存", { exact: true })).toBeVisible();
    expect(writes[1]).toMatchObject({ path: "/api/catalog/categories/8", method: "PUT", body: { code: "DRESS_MINI_NEW", parent_category_id: 7, aliases: ["Mini dress", "短裙"], status: "enabled" } });
    await page.reload();
    await page.getByRole("button", { name: "管理分类", exact: true }).click();
    await page.getByRole("button", { name: "编辑 短款连衣裙", exact: true }).click();
    await expect(page.getByRole("textbox", { name: "分类 8 代码", exact: true })).toHaveValue("DRESS_MINI_NEW");
    await page.getByRole("button", { name: "新建分类", exact: true }).click();
    await page.getByRole("textbox", { name: "分类名称", exact: true }).fill("示例衬衫");
    await page.getByRole("textbox", { name: "分类代码", exact: true }).fill("SHIRT");
    await page.getByRole("button", { name: "创建分类", exact: true }).click();
    await expect(page.getByRole("button", { name: "编辑 示例衬衫", exact: true })).toBeVisible();
    expect(writes).toHaveLength(3);
    expect(writes[2]).toMatchObject({ path: "/api/catalog/categories", method: "POST", body: { code: "SHIRT", parent_category_id: null } });
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
    canManage = false; await page.reload();
    await expect(page.getByRole("heading", { name: "示例商品", exact: true })).toBeVisible();
    await expect(page.getByRole("button", { name: "管理分类", exact: true })).toHaveCount(0);
    await expect(page.getByRole("button", { name: "修改名称 / 分类", exact: true })).toHaveCount(0);
    expect(writes).toHaveLength(3);
  });
}
