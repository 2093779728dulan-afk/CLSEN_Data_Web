import { expect, test } from "@playwright/test";
import { openStory } from "./storybookGateSupport";
import { VIEWPORTS } from "./storybookGateManifest";

for (const viewport of VIEWPORTS) test(`detail metric, dimension, chart and variants at ${viewport.width}px`, async ({ page }) => {
  await page.setViewportSize(viewport);
  const requests: string[] = []; page.on("request", r => { if (new URL(r.url()).pathname.startsWith("/api/")) requests.push(r.url()); });
  await openStory(page, "pages-product-detail--reference");
  await expect(page.getByRole("heading", { name: "标准轻量夹克", exact: true })).toBeVisible();
  await page.getByRole("radio", { name: "销售额", exact: true }).check();
  await expect(page.getByRole("img", { name: /产品每日趋势.*销售额/ })).toBeVisible();
  await page.getByRole("radio", { name: "尺码", exact: true }).check();
  await page.getByRole("radio", { name: "蓝色", exact: true }).check();
  await expect(page.getByRole("group", { name: "选择要对比的尺码", exact: true })).toBeVisible();
  const slider = page.getByRole("slider", { name: "查看日期", exact: true }); await slider.focus(); await page.keyboard.press("Home"); await expect(slider).toHaveAttribute("aria-valuetext", "2026-08-22");
  await page.getByRole("combobox", { name: "筛选颜色", exact: true }).selectOption("蓝色");
  const region = page.getByRole("region", { name: "实际变体指标", exact: true }); await expect(region).toContainText("DEMO-BLUE-M"); await expect(region).not.toContainText("DEMO-RED-S");
  await page.getByRole("button", { name: "变体退货关注", exact: true }).click(); await expect(region).toContainText("同期退销比");
  await page.getByRole("combobox", { name: "筛选尺码", exact: true }).selectOption("S"); await expect(region).toContainText("没有匹配的实际变体");
  await page.getByRole("button", { name: "清除变体筛选", exact: true }).click();
  await page.getByText("1 个来源别名", { exact: true }).first().click(); await expect(region).toContainText("DEMO-SOURCE-RED-S");
  await region.focus(); await expect(region).toBeFocused();
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true); expect(requests).toEqual([]);
});
test("detail missing, partial, pending, failure and read-only boundaries", async ({ page }) => {
  await openStory(page, "pages-product-detail--no-reports"); await expect(page.getByRole("region", { name: "周期指标摘要", exact: true })).toContainText("无报表");
  await openStory(page, "pages-product-detail--partial"); await expect(page.getByRole("region", { name: "周期指标摘要", exact: true })).toContainText("部分数据");
  await openStory(page, "pages-product-detail--refreshing"); await expect(page.locator("[inert]")).toHaveCount(1);
  await openStory(page, "pages-product-detail--read-failure"); await page.getByRole("button", { name: "按原条件重试", exact: true }).click(); await expect(page.getByRole("heading", { name: "标准轻量夹克", exact: true })).toBeVisible();
  await openStory(page, "pages-product-detail--color-failure"); await expect(page.getByText("颜色选项读取失败", { exact: true })).toBeVisible(); await page.getByRole("button", { name: "重新读取颜色", exact: true }).click(); await expect(page.getByRole("radio", { name: "蓝色", exact: true })).toBeVisible();
  await openStory(page, "pages-product-detail--read-only"); await expect(page.getByRole("link", { name: "核对待归属来源", exact: true })).toHaveCount(0);
  await openStory(page, "pages-product-detail--access-denied"); await expect(page.getByRole("button", { name: "按原条件重试", exact: true })).toHaveCount(0);
});
