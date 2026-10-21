import { expect, test } from "@playwright/test";
import { openStory } from "./storybookGateSupport";

test("existing chart consumer retains selection, single day and unavailable values", async ({ page }) => {
  await page.route(url => url.pathname.startsWith("/api/"), route => route.abort());
  await openStory(page, "patterns-product-trend-chart--reference");
  const matrix = page.getByRole("region", { name: "趋势每日点矩阵", exact: true });
  await expect(matrix.locator("thead th")).toHaveCount(5);
  await page.getByRole("checkbox", { name: "海蓝", exact: true }).uncheck();
  await expect(matrix.locator("thead th")).toHaveCount(4);
  await expect(matrix.getByRole("columnheader", { name: "海蓝", exact: true })).toHaveCount(0);
  await page.reload(); await expect(matrix.locator("thead th")).toHaveCount(5);
  await openStory(page, "patterns-product-trend-chart--single-day");
  await expect(matrix.locator("tbody tr")).toHaveCount(1);
  await expect(matrix.locator("tbody td")).toHaveText("0.00");
  await openStory(page, "patterns-product-trend-chart--missing-and-partial");
  await expect(matrix).toContainText("无报表"); await expect(matrix).toContainText("部分数据");
  await openStory(page, "patterns-product-trend-chart--conversion-ratio");
  await expect(matrix).toContainText("0.000000"); await expect(matrix).toContainText("分母为 0");
  await openStory(page, "patterns-product-trend-chart--empty");
  await expect(matrix.locator("tbody tr")).toHaveCount(7); await expect(matrix).toContainText("无报表");
});

for (const width of [1280, 390]) {
  test(`matrix original values, selection, unavailable states and reload at ${width}px`, async ({ page }) => {
    await page.setViewportSize({ width, height: 900 });
    const requests: string[] = [];
    await page.route(url => url.pathname.startsWith("/api/"), route => { requests.push(route.request().url()); throw new Error("Matrix samples must use fictional local data"); });
    await openStory(page, "patterns-trend-point-matrix--reference");
    const region = page.getByRole("region", { name: "趋势每日点矩阵", exact: true });
    const table = region.getByRole("table");
    await expect(table.locator("tbody time")).toHaveText(["2026-08-01", "2026-08-02", "2026-08-03"]);
    await expect(table.locator("tbody tr").first()).toContainText("0.00");
    await page.getByRole("combobox", { name: "明细指标", exact: true }).selectOption("conversion");
    await expect(table).toContainText("0.200000"); await expect(table).toContainText("分母为 0");
    await page.getByRole("checkbox", { name: "海蓝 / M", exact: true }).uncheck();
    await expect(table.getByRole("columnheader", { name: "海蓝 / M", exact: true })).toHaveCount(0);
    await page.reload(); await expect(table.getByRole("columnheader", { name: "海蓝 / M", exact: true })).toBeVisible();
    await expect(page.getByRole("combobox", { name: "明细指标", exact: true })).toHaveValue("sales");
    await openStory(page, "patterns-trend-point-matrix--missing-and-partial");
    await expect(table).toContainText("无报表"); await expect(table).toContainText("部分数据"); await expect(table).toContainText("完整性未定");
    await expect(table.locator("tbody tr").nth(1).locator("td").last()).toContainText("无报表");
    await openStory(page, "patterns-trend-point-matrix--long-values");
    await expect(table).toContainText("123,456,789,012,345,678,901,234,567,890.12"); await expect(table).toContainText("-1,234.50");
    const amount = table.locator("tbody tr").first().locator("td > span");
    expect(await amount.evaluate(node => getComputedStyle(node).whiteSpace)).toBe("nowrap");
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
    await openStory(page, "patterns-trend-point-matrix--empty"); await expect(page.getByRole("heading", { name: "暂无每日明细", exact: true })).toBeVisible();
    await expect(page.getByRole("table")).toHaveCount(0);
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true); expect(requests).toEqual([]);
  });
  test(`matrix keyboard scroll keeps date and header fixed at ${width}px`, async ({ page }) => {
    await page.setViewportSize({ width, height: 900 }); await openStory(page, "patterns-trend-point-matrix--wide");
    const region = page.getByRole("region", { name: "趋势每日点矩阵", exact: true });
    await region.scrollIntoViewIfNeeded(); await region.focus(); await expect(region).toBeFocused();
    const rowDate = region.locator("tbody th").first(); const headerDate = region.locator("thead th").first();
    const initial = (await rowDate.boundingBox())!;
    await page.keyboard.press("ArrowRight"); await expect.poll(() => region.evaluate(node => node.scrollLeft)).toBeGreaterThan(0);
    expect(Math.abs((await rowDate.boundingBox())!.x - initial.x)).toBeLessThanOrEqual(1);
    await page.keyboard.press("PageDown"); await expect.poll(() => region.evaluate(node => node.scrollTop)).toBeGreaterThan(0);
    const top = (await region.boundingBox())!.y; expect(Math.abs((await headerDate.boundingBox())!.y - top)).toBeLessThanOrEqual(3);
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
  });
}
