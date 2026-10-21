import { expect, test } from "@playwright/test";
import { openStory } from "./storybookGateSupport";
import { VIEWPORTS } from "./storybookGateManifest";

for (const viewport of VIEWPORTS) test(`ledger filters, identity, metric help and keyboard at ${viewport.width}px`, async ({ page }) => {
  await page.setViewportSize(viewport); const api: string[] = []; page.on("request", r => { if (new URL(r.url()).pathname.startsWith("/api/")) api.push(r.url()); });
  await openStory(page, "pages-product-ledger--reference"); await page.getByRole("combobox", { name: "筛选主分类", exact: true }).selectOption("1"); await page.getByRole("combobox", { name: "筛选细分类", exact: true }).selectOption("2");
  await page.getByRole("checkbox", { name: "显示商品名称", exact: true }).check(); await expect(page.getByRole("button", { name: "查看款号 10001 商品信息", exact: true })).toContainText("标准轻量夹克");
  const region = page.getByRole("region", { name: "产品总表，可横向滚动", exact: true }); await region.focus(); await expect(region).toBeFocused();
  const trigger = page.getByRole("button", { name: "查看款号 10001 商品信息", exact: true }); await trigger.click(); await expect(page.getByRole("dialog")).toContainText("标准轻量夹克"); await expect(page.getByRole("link", { name: "进入款式详情" })).toHaveAttribute("href", /\/products\/501\?/); await page.keyboard.press("Escape"); await expect(trigger).toBeFocused();
  const help = page.getByRole("button", { name: "销量说明", exact: true }); await help.click(); await expect(page.getByRole("dialog", { name: "销量", exact: true })).toBeVisible(); await page.keyboard.press("Escape"); await expect(help).toBeFocused();
  await page.getByRole("button", { name: "退货关注", exact: true }).click(); await expect(page.getByText("当前排序：", { exact: false })).toContainText("本期退货量"); await expect(page.getByText(/不代表订单退货率/)).toBeVisible();
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true); expect(api).toEqual([]);
});
test("ledger zero, missing reports, partial, loading, retry and boundaries", async ({ page }) => {
  await openStory(page, "pages-product-ledger--zero-values"); await expect(page.getByRole("table", { name: "稳定款式指标", exact: true })).toContainText("分母为 0");
  await openStory(page, "pages-product-ledger--no-reports"); await expect(page.getByText("所选日期没有已发布报表", { exact: true })).toBeVisible();
  await openStory(page, "pages-product-ledger--partial"); await expect(page.getByRole("table", { name: "稳定款式指标", exact: true })).toContainText("部分数据");
  await openStory(page, "pages-product-ledger--refreshing"); await expect(page.locator("table[aria-label='稳定款式指标']")).toHaveAttribute("inert", "");
  await openStory(page, "pages-product-ledger--read-failure"); await page.getByRole("button", { name: "按原条件重试", exact: true }).click(); await expect(page.getByRole("button", { name: "查看款号 10001 商品信息", exact: true })).toBeVisible();
  await openStory(page, "pages-product-ledger--access-denied"); await expect(page.getByRole("button", { name: "按原条件重试", exact: true })).toHaveCount(0);
  await openStory(page, "pages-product-ledger--setup-required"); await expect(page.getByRole("link", { name: "查看初始化与处理步骤", exact: true })).toHaveAttribute("href", "/catalog");
});
