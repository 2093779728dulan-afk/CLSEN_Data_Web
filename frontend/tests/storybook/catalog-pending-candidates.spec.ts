import { expect, test } from "@playwright/test";
import { openStory } from "./storybookGateSupport";
for (const width of [1280, 390]) {
  test(`pending candidates preserve batch and style navigation at ${width}px`, async ({ page }) => {
    await page.setViewportSize({ width, height: 900 }); await openStory(page, "patterns-catalog-pending-candidates--reference");
    const panel = page.getByRole("region", { name: "新变体与 Seller SKU 候选", exact: true });
    const row = panel.getByRole("listitem", { name: "审核批次 #43", exact: true });
    await expect(row.getByText("已校验", { exact: true })).toBeVisible(); const link = row.getByRole("link", { name: "进入审核", exact: true }); await expect(link).toHaveAttribute("href", "/catalog/imports/43");
    await link.focus(); await page.keyboard.press("Enter"); await expect(page.getByText(/目标路径：\/catalog\/imports\/43；返回路径：\/catalog\/styles\/1001/)).toBeVisible();
    await page.getByRole("link", { name: "返回商品详情", exact: true }).click(); await expect(panel).toBeVisible(); await page.reload(); await expect(panel.getByText("3 个审核批次", { exact: true })).toBeVisible();
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
  });
}
test("read-only, empty and preview absence do not invent candidates or actions", async ({ page }) => {
  await openStory(page, "patterns-catalog-pending-candidates--read-only"); await expect(page.getByRole("link", { name: "进入审核", exact: true })).toHaveCount(0); await expect(page.getByText("由数据管理员确认", { exact: true })).toHaveCount(3);
  await openStory(page, "patterns-catalog-pending-candidates--empty"); await expect(page.getByRole("region", { name: "新变体与 Seller SKU 候选", exact: true })).toHaveCount(0);
  await openStory(page, "patterns-catalog-pending-candidates--no-previews"); await expect(page.getByText("当前批次未提供 Seller SKU 预览。", { exact: true })).toBeVisible();
  await openStory(page, "patterns-catalog-pending-candidates--zero-counts"); await expect(page.getByText("新增变体 0", { exact: true })).toBeVisible(); await expect(page.getByText("Seller SKU 0", { exact: true })).toBeVisible();
});
test("long previews remain text and six batches retain distinct targets on mobile", async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 900 }); await openStory(page, "patterns-catalog-pending-candidates--long-previews");
  await expect(page.getByText("<fictional-preview-only>", { exact: true })).toBeVisible(); await expect(page.locator("fictional-preview-only")).toHaveCount(0);
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
  await openStory(page, "patterns-catalog-pending-candidates--many-batches"); const row = page.getByRole("listitem", { name: "审核批次 #105", exact: true }); await expect(row).toBeVisible(); await expect(row.getByRole("link", { name: "进入审核", exact: true })).toHaveAttribute("href", "/catalog/imports/105");
});
