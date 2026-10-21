import { expect, test } from "@playwright/test";
import { openStory } from "./storybookGateSupport";

for (const width of [1280, 390]) {
  test(`published daily filters, changes month and opens readonly day at ${width}px`, async ({ page }) => {
    const api: string[] = [];
    await page.route(url => url.pathname.startsWith("/api/"), route => { api.push(route.request().url()); return route.abort(); });
    await page.setViewportSize({ width, height: 900 });
    await openStory(page, "pages-published-daily-ledger--reference");
    await expect(page.getByText("3 个日期待补齐", { exact: true })).toBeVisible();
    await page.getByRole("combobox", { name: "日期状态", exact: true }).selectOption("partial");
    const table = page.getByRole("table", { name: "每日发布记录", exact: true });
    await expect(table.getByRole("row")).toHaveCount(2);
    await expect(page.getByText("3 个日期待补齐", { exact: true })).toBeVisible();
    await page.getByRole("textbox", { name: "统计月份", exact: true }).fill("2026-08");
    await expect(table.getByText("2026-08-12", { exact: true })).toBeVisible();
    await expect(page.getByRole("link", { name: "发布明细", exact: true })).toHaveAttribute("href", "/ledger/published-details?from=2026-08-01&to=2026-08-31");
    const row = table.getByRole("row").nth(1);
    await row.focus(); await page.keyboard.press("Enter");
    await expect(page.getByRole("heading", { name: "虚构日期入口" })).toBeVisible();
    await expect(page.getByText("/published/2026-08-12", { exact: true })).toBeVisible();
    await page.getByRole("link", { name: "返回发布总表", exact: true }).click();
    await expect(page.getByRole("combobox", { name: "日期状态", exact: true })).toHaveValue("partial");
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
    expect(api).toEqual([]);
  });
}

test("published daily manager routes, error recovery, empty and zero values are explicit", async ({ page }) => {
  await openStory(page, "pages-published-daily-ledger--manager");
  await page.getByRole("link", { name: "审核 2026-09-12", exact: true }).click();
  await expect(page.getByText("/review/2026-09-12", { exact: true })).toBeVisible();
  await openStory(page, "pages-published-daily-ledger--read-failure");
  await expect(page.getByRole("alert")).toBeVisible();
  await page.getByRole("button", { name: "重新读取", exact: true }).click();
  await expect(page.getByRole("table", { name: "每日发布记录", exact: true }).getByText("2026-09-12", { exact: true })).toBeVisible();
  await openStory(page, "pages-published-daily-ledger--loading");
  await expect(page.getByRole("status", { name: "正在读取每日发布总表", exact: true })).toBeVisible();
  await expect(page.getByText("正在核对本月数据", { exact: true })).toBeVisible();
  await openStory(page, "pages-published-daily-ledger--no-records");
  await expect(page.getByText("本月暂无日期记录", { exact: true })).toBeVisible();
  await expect(page.getByText("本月无需补齐", { exact: true })).toHaveCount(0);
  await openStory(page, "pages-published-daily-ledger--filter-empty");
  await page.getByRole("button", { name: "清除状态筛选", exact: true }).click();
  await expect(page.getByRole("table").getByRole("row")).toHaveCount(5);
  await openStory(page, "pages-published-daily-ledger--zero-values");
  await expect(page.getByRole("table").getByText("US$0.00", { exact: true })).toBeVisible();
  await expect(page.getByRole("table").getByText("—", { exact: true })).toHaveCount(0);
});
