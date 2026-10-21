import { expect, test } from "@playwright/test";
import { openStory } from "./storybookGateSupport";
for (const width of [1280, 390]) {
  test(`history page, keyboard batch navigation, return and refresh at ${width}px`, async ({ page }) => {
    await page.setViewportSize({ width, height: 900 }); await openStory(page, "patterns-catalog-import-history--reference");
    const panel = page.getByRole("region", { name: "已有审核批次", exact: true });
    await expect(panel.getByRole("button", { name: "上一页", exact: true })).toBeDisabled();
    const link = panel.getByRole("link", { name: "批次 #902 · 查看批准结果", exact: true }); await link.focus(); await page.keyboard.press("Enter");
    await expect(page.getByText(/目标路径：\/catalog\/imports\/902/)).toBeVisible(); await page.getByRole("link", { name: "返回批次列表", exact: true }).click();
    await panel.getByRole("button", { name: "下一页", exact: true }).click(); await expect(panel.getByText("第 2 页", { exact: true })).toBeVisible(); await expect(panel.getByRole("button", { name: "下一页", exact: true })).toBeDisabled();
    await panel.getByRole("button", { name: "上一页", exact: true }).click(); await page.reload(); await expect(panel.getByText("第 1 页", { exact: true })).toBeVisible();
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
  });
}
test("loading and read failure recover explicitly; empty and archived meaning preserved", async ({ page }) => {
  for (const state of ["loading", "read-failure"]) {
    await openStory(page, `patterns-catalog-import-history--${state}`); await expect(page.getByRole("link", { name: /^批次/ })).toHaveCount(0);
    await page.getByRole("button", { name: "刷新批次", exact: true }).click(); await expect(page.getByRole("link", { name: "批次 #901 · 继续审核", exact: true })).toBeVisible(); await expect(page.getByRole("alert")).toHaveCount(0);
  }
  await openStory(page, "patterns-catalog-import-history--empty"); await expect(page.getByRole("heading", { name: "暂无审核批次，可在下方生成候选。", exact: true })).toBeVisible(); await expect(page.getByRole("button", { name: "下一页", exact: true })).toBeDisabled();
  await openStory(page, "patterns-catalog-import-history--archived"); await expect(page.getByRole("link", { name: "批次 #901 · 查看批次", exact: true })).toBeVisible(); await expect(page.getByText("已取代", { exact: true })).toBeVisible();
});
test("long stable identifiers and unknown status remain visible on mobile", async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 900 }); await openStory(page, "patterns-catalog-import-history--long-values"); await expect(page.getByRole("link", { name: "批次 #9007199254740991 · 继续审核", exact: true })).toHaveAttribute("href", "/catalog/imports/9007199254740991");
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
  await openStory(page, "patterns-catalog-import-history--unknown-status"); await expect(page.getByText("future_status", { exact: true })).toBeVisible();
});
