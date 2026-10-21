import { expect, test } from "@playwright/test";
import { openStory } from "./storybookGateSupport";

for (const width of [1280, 390]) {
  test(`published day changes trend and checks exact day/navigation at ${width}px`, async ({ page }) => {
    const api: string[] = [];
    await page.route(url => url.pathname.startsWith("/api/"), route => { api.push(route.request().url()); return route.abort(); });
    await page.setViewportSize({ width, height: 900 });
    await openStory(page, "pages-published-day-detail--reference");
    await expect(page.getByRole("heading", { name: "2026-09-12", exact: true })).toBeVisible();
    const sales = page.getByRole("region", { name: "当前发布指标", exact: true }).getByText("US$18,420.50", { exact: true });
    await expect(sales).toBeVisible();
    if (width === 390) {
      expect(await sales.evaluate(element => {
        const range = document.createRange();
        range.selectNodeContents(element);
        return range.getClientRects().length;
      })).toBe(1);
    }
    await page.getByRole("combobox", { name: "趋势指标", exact: true }).selectOption("return_quantity");
    await expect(page.getByRole("img", { name: /退货数月内每日趋势/ })).toBeVisible();
    await page.getByText("查看逐日数据 · 退货数", { exact: true }).click();
    const table = page.getByRole("table", { name: "退货数 · 2026-09-01 至 2026-09-12", exact: true });
    await expect(table.getByRole("row", { name: /2026-09-03/ })).toContainText("未发布或暂无指标值");
    await expect(table.getByRole("row", { name: /2026-09-12/ })).toContainText("5");
    await expect(page.getByRole("link", { name: "查看当日原始明细", exact: true })).toHaveAttribute("href", "/ledger/published-details?from=2026-09-12&to=2026-09-12&mode=rows");
    await page.getByRole("link", { name: "查看另一日期样板", exact: true }).click();
    await expect(page.getByRole("heading", { name: "2026-09-11", exact: true })).toBeVisible();
    await page.getByRole("link", { name: "返回每日总表", exact: true }).click();
    await expect(page.getByText("/?month=2026-09", { exact: true })).toBeVisible();
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
    expect(api).toEqual([]);
  });
}

test("published day distinguishes partial/zero, failure recovery, loading, empty and embedded modes", async ({ page }) => {
  await openStory(page, "pages-published-day-detail--partial");
  await expect(page.getByRole("region", { name: "当前发布指标", exact: true })).toContainText("报告未发布");
  await page.getByRole("combobox", { name: "趋势指标", exact: true }).selectOption("return_quantity");
  await page.getByText("查看逐日数据 · 退货数", { exact: true }).click();
  await expect(page.getByRole("table").getByRole("row", { name: /2026-09-12/ })).toContainText("未发布或暂无指标值");
  await openStory(page, "pages-published-day-detail--zero-values");
  await expect(page.getByRole("region", { name: "当前发布指标", exact: true })).toContainText("US$0.00");
  await openStory(page, "pages-published-day-detail--read-failure");
  await expect(page.getByRole("alert")).toBeVisible();
  await page.getByRole("button", { name: "重新读取", exact: true }).click();
  await expect(page.getByRole("heading", { name: "两类报告均已发布", exact: true })).toBeVisible();
  await expect(page.getByRole("alert")).toHaveCount(0);
  await openStory(page, "pages-published-day-detail--loading");
  await expect(page.getByRole("status", { name: "正在读取当前发布数据", exact: true })).toBeVisible();
  await openStory(page, "pages-published-day-detail--empty");
  await expect(page.getByText("这个日期没有发布数据", { exact: true })).toBeVisible();
  await openStory(page, "pages-published-day-detail--single-day");
  await expect(page.getByRole("img")).toBeVisible();
  await openStory(page, "pages-published-day-detail--embedded");
  await expect(page.getByRole("region", { name: "单日只读发布详情", exact: true })).toBeVisible();
  await expect(page.getByRole("heading", { name: "本月趋势", exact: true })).toHaveCount(0);
});
