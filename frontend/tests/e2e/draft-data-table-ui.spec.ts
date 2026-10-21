import { expect, test } from "@playwright/test";
import { dataTableWorkspace } from "../../src/features/import-review/ReviewDataTable.fixtures";

for (const width of [1280, 390]) {
  test(`actual draft table filters, key navigation, comparison and pagination at ${width}px`, async ({ page }) => {
    await page.setViewportSize({ width, height: 900 });
    const unexpected: string[] = []; const pages: number[] = []; const errors: string[] = [];
    page.on("pageerror", error => errors.push(error.message));
    await page.context().route(url => url.pathname.startsWith("/api/"), async route => {
      const req = route.request(); const url = new URL(req.url()); const path = url.pathname;
      const json = (data: unknown) => route.fulfill({ contentType: "application/json", body: JSON.stringify(data) });
      if (req.method() !== "GET") { unexpected.push(`${req.method()} ${path}`); return route.fulfill({ status: 500, body: "No write allowed" }); }
      if (path === "/api/auth/me") return json({ id: 88, username: "fictional-reviewer", display_name: "虚构审核员", roles: ["data_manager"] });
      if (path === "/api/data-calendar/site-context") return json({ site_id: 1, site_code: "US", display_name: "虚构站点", site_config_version_id: 2, source_timezone: "UTC", reporting_timezone: "UTC", currency_code: "USD" });
      if (path === "/api/data-calendar") return json([{ report_date: "2026-08-10", report_type: "business_report", dataset_id: 41, version_id: 51, version_no: 2, status: "draft" }]);
      if (["/api/data-calendar/days", "/api/versions", "/api/imports/11/notes"].includes(path)) return json([]);
      if (path === "/api/drafts/51/review-workspace") { const p = Number(url.searchParams.get("page") ?? "1"); expect(url.searchParams.get("page_size")).toBe("50"); pages.push(p); return json(dataTableWorkspace("reference", p, 50, 56)); }
      unexpected.push(`${req.method()} ${path}`); return route.fulfill({ status: 500, body: "Unexpected fictional request" });
    });
    await page.goto("/review-advanced/2026-08-10?report_type=business_report&version_id=51");
    const table = page.getByRole("region", { name: "草稿数据对照", exact: true });
    await expect(table.getByRole("button", { name: "sales，当前值 22.50，与基础版本不同", exact: true })).toBeVisible();
    await table.getByRole("searchbox", { name: "搜索当前页" }).fill("no-match");
    await expect(table.getByText("当前筛选没有匹配行", { exact: true })).toBeVisible();
    await table.getByRole("button", { name: "清除当前页搜索" }).click();
    await expect(table.getByRole("searchbox")).toBeFocused();
    await table.getByRole("combobox", { name: "行状态", exact: true }).selectOption("excluded");
    await expect(table.getByRole("button", { name: "管理第 3 行状态，当前 excluded", exact: true })).toHaveText(/已排除/);
    await table.getByRole("combobox", { name: "显示字段", exact: true }).selectOption("asin");
    await expect(table.getByText("当前筛选没有匹配行", { exact: true })).toBeVisible();
    await table.getByRole("button", { name: "清除当前页筛选" }).click();
    await expect(table.getByRole("checkbox", { name: "仅看差异" })).not.toBeChecked();
    await expect(table.getByRole("button", { name: "管理第 6 行状态，当前 active", exact: true })).toBeVisible();
    await table.getByRole("combobox", { name: "显示字段", exact: true }).selectOption("sales");
    await expect(table.getByRole("columnheader", { name: /title/ })).toHaveCount(0);
    await table.getByRole("button", { name: "按 sales 升序排序", exact: true }).click();
    await expect(table.getByRole("columnheader", { name: /sales/ })).toHaveAttribute("aria-sort", "ascending");
    const sku = table.getByRole("button", { name: "sku，当前值 A-01", exact: true });
    await sku.focus(); await page.keyboard.press("ArrowRight");
    await expect(table.getByRole("button", { name: "asin，当前值 B0DEMO0001", exact: true })).toBeFocused();
    await page.keyboard.press("End"); await page.keyboard.press("Enter");
    const drawer = page.getByRole("dialog", { name: "字段对照", exact: true });
    await expect(drawer.getByText("源文件值", { exact: true }).locator("..")).toContainText("9.00");
    await expect(drawer.getByText("版本基础值", { exact: true }).locator("..")).toContainText("10.00");
    await expect(drawer.getByText("当前草稿值", { exact: true }).locator("..")).toContainText("12.50");
    await page.keyboard.press("Escape");
    await table.getByRole("button", { name: "下一处差异", exact: true }).click();
    await expect(drawer.getByText("第 2 行", { exact: true })).toBeVisible();
    await drawer.getByRole("button", { name: "关闭字段对照", exact: true }).click();
    await table.getByRole("button", { name: "下一处差异", exact: true }).click();
    await expect(drawer.getByText("第 3 行", { exact: true })).toBeVisible();
    await page.keyboard.press("Escape");
    await table.getByRole("button", { name: "下一页", exact: true }).click();
    await expect(table.getByRole("button", { name: "sku，当前值 A-51", exact: true })).toBeVisible();
    expect(pages).toContain(2);
    await table.getByRole("button", { name: "上一页", exact: true }).click();
    await expect(table.getByRole("button", { name: "sku，当前值 A-01", exact: true })).toBeVisible();
    await page.reload();
    await expect(table.getByRole("checkbox", { name: "仅看差异" })).toBeChecked();
    await expect(table.getByRole("button", { name: "sales，当前值 22.50，与基础版本不同", exact: true })).toBeVisible();
    expect(unexpected).toEqual([]); expect(errors).toEqual([]);
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth + 1)).toBe(true);
  });
}
