import { expect, test } from "@playwright/test";
import { openStory } from "./storybookGateSupport";

for (const width of [1280, 390]) {
  test(`overview record identity, keyboard navigation and refresh at ${width}px`, async ({ page }) => {
    await page.setViewportSize({ width, height: 900 });
    await openStory(page, "patterns-catalog-maintenance-overview--reference");
    const panel = page.getByRole("region", { name: "批量维护总览", exact: true });
    await expect(panel).toContainText("当前生效目录 V4"); await expect(panel.getByText("#104", { exact: true })).toBeVisible(); await expect(panel.getByText("7", { exact: true })).toBeVisible();
    await expect(page.getByRole("region", { name: "维护流程", exact: true }).getByRole("listitem")).toHaveCount(3);
    const products = panel.getByRole("link", { name: "查看已生效商品", exact: true }); await expect(products).toHaveAttribute("href", "/catalog"); await products.focus(); await products.press("Enter"); await expect(page.getByRole("heading", { name: "虚构关联结果" })).toBeVisible(); await expect(page.getByText("目标路径：/catalog", { exact: true })).toBeVisible();
    await page.getByRole("link", { name: "返回批量维护总览" }).click(); const versions = panel.getByRole("link", { name: "查看批准记录", exact: true }); await expect(versions).toHaveAttribute("href", "/catalog/versions"); await versions.click(); await expect(page.getByText("目标路径：/catalog/versions", { exact: true })).toBeVisible(); await page.getByRole("link", { name: "返回批量维护总览" }).click();
    await page.reload(); await expect(panel).toContainText("当前生效目录 V4"); expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
  });
}
test("uninitialized overview keeps published-source prerequisite and report navigation", async ({ page }) => {
  await openStory(page, "patterns-catalog-maintenance-overview--uninitialized");
  const panel = page.getByRole("region", { name: "批量维护总览", exact: true });
  await expect(panel.getByText("尚未初始化", { exact: true })).toBeVisible(); await expect(page.getByRole("region", { name: "首个目录前置", exact: true }).getByRole("listitem")).toHaveCount(4);
  await expect(panel.getByRole("link", { name: "查看已生效商品", exact: true })).toHaveCount(0); await expect(panel.getByText("当前生效依据", { exact: true })).toHaveCount(0);
  const daily = page.getByRole("link", { name: "返回每日数据查看发布情况", exact: true }); await expect(daily).toHaveAttribute("href", "/"); await daily.click(); await expect(page.getByText("目标路径：/", { exact: true })).toBeVisible(); await page.getByRole("link", { name: "返回批量维护总览" }).click(); await expect(panel).toContainText("保存、校验并批准后");
});
test("first version with no styles stays initialized; long record identifiers fit mobile", async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 900 }); await openStory(page, "patterns-catalog-maintenance-overview--first-version");
  await expect(page.getByText("已生效 V1", { exact: true })).toBeVisible(); await expect(page.getByRole("region", { name: "首个目录前置", exact: true })).toHaveCount(0);
  await openStory(page, "patterns-catalog-maintenance-overview--long-identifiers"); await expect(page.getByText("#1234567890123", { exact: true })).toBeVisible(); await expect(page.getByRole("link", { name: "查看批准记录", exact: true })).toBeVisible(); expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
});
