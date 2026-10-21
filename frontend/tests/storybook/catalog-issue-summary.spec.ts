import { expect, test } from "@playwright/test";
import { openStory } from "./storybookGateSupport";

for (const width of [1280, 390]) {
  test(`catalog problem rows and keyboard locate parameters at ${width}px`, async ({ page }) => {
    await page.setViewportSize({ width, height: 900 }); await openStory(page, "patterns-catalog-issue-summary--reference");
    const panel = page.getByRole("complementary", { name: "商品审核问题", exact: true });
    await expect(panel.getByText("3 条问题", { exact: true })).toBeVisible();
    const locate = panel.getByRole("button", { name: "定位问题 2", exact: true });
    await locate.focus(); await page.keyboard.press("Enter");
    await expect(page.getByRole("status")).toContainText("分类 skus · 行 fictional-sku:2 · 字段 /standard_size");
    await page.reload(); await expect(page.getByText("已选择定位目标", { exact: true })).toHaveCount(0);
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
  });
}
test("parse correction, missing row, display-only and unknown codes retain their meaning", async ({ page }) => {
  await openStory(page, "patterns-catalog-issue-summary--parse-failed");
  await expect(page.getByText(/修正原文件并到批量维护重新上传/)).toBeVisible(); await expect(page.getByText("原因代码：", { exact: false })).toContainText("invalid_headers");
  await openStory(page, "patterns-catalog-issue-summary--unlocatable"); await expect(page.getByText("此项没有行定位信息", { exact: true })).toBeVisible(); await expect(page.getByRole("button", { name: /^定位问题/ })).toHaveCount(0);
  await openStory(page, "patterns-catalog-issue-summary--read-only"); await expect(page.getByRole("button", { name: /^定位问题/ })).toHaveCount(0); await expect(page.getByText("fictional-style:1", { exact: true })).toBeVisible();
  await openStory(page, "patterns-catalog-issue-summary--unknown-code"); await expect(page.getByText(/new_server_field.*new_server_rule/)).toBeVisible(); await expect(page.getByText("server_notice", { exact: true })).toBeVisible();
  await openStory(page, "patterns-catalog-issue-summary--empty"); await expect(page.getByRole("heading", { name: "暂无逐行问题", exact: true })).toBeVisible(); await expect(page.getByText(/不代表当前草稿已通过审核/)).toBeVisible();
});
test("long reasons and many issues remain readable on narrow screens", async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 900 });
  await openStory(page, "patterns-catalog-issue-summary--long-values");
  const panel = page.getByRole("complementary", { name: "商品审核问题", exact: true });
  expect(await panel.evaluate(el => el.scrollWidth <= el.clientWidth)).toBe(true);
  await openStory(page, "patterns-catalog-issue-summary--many-issues"); await expect(panel.getByRole("listitem")).toHaveCount(10);
  await panel.getByRole("button", { name: "定位问题 10", exact: true }).click(); await expect(page.getByRole("status")).toContainText("fictional-row:10");
});
