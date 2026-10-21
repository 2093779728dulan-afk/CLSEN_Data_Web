import { expect, test } from "@playwright/test";
import { openStory } from "./storybookGateSupport";

for (const width of [1280, 390]) {
  test(`explicit keyboard retry, recovery and refresh at ${width}px`, async ({ page }) => {
    await page.setViewportSize({ width, height: 900 });
    await openStory(page, "patterns-catalog-read-feedback--reference");
    const button = page.getByRole("button", { name: "重新读取", exact: true });
    await button.focus(); await button.press("Enter");
    await expect(page.getByRole("status").filter({ hasText: "正在读取目录版本" })).toBeVisible();
    await expect(page.getByRole("heading", { name: "尚无已批准目录版本", exact: true })).toBeVisible();
    await expect(page.getByRole("status")).toContainText("本次手动读取 1 次");
    await page.reload(); await expect(button).toBeVisible();
    await openStory(page, "patterns-catalog-read-feedback--long-message");
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
  });
}
test("persistent failure requires an explicit new attempt; restricted states only navigate", async ({ page }) => {
  await openStory(page, "patterns-catalog-read-feedback--repeat-failure");
  await page.getByRole("button", { name: "重新读取", exact: true }).click();
  await expect(page.getByRole("alert")).toBeVisible();
  await expect(page.getByRole("status")).toContainText("本次手动读取 1 次");
  for (const scenario of ["forbidden", "not-found", "invalid-query"]) {
    await openStory(page, `patterns-catalog-read-feedback--${scenario}`);
    await expect(page.getByRole("button", { name: "重新读取", exact: true })).toHaveCount(0);
    await expect(page.getByRole("link", { name: "返回商品主档", exact: true })).toHaveAttribute("href", "/catalog");
    await expect(page.getByRole("region", { name: "商品分析初始化" })).toHaveCount(0);
  }
  await openStory(page, "patterns-catalog-read-feedback--rate-limited");
  await expect(page.getByRole("alert")).toContainText("请求过于频繁");
  await page.getByRole("button", { name: "重新读取", exact: true }).click();
  await expect(page.getByRole("heading", { name: "尚无已批准目录版本" })).toBeVisible();
});
test("initialization guidance is read-only and refresh does not fabricate readiness; consumers recover", async ({ page }) => {
  await openStory(page, "patterns-catalog-read-feedback--setup");
  await expect(page.getByRole("link", { name: "前往批量维护，完成初始化" })).toHaveAttribute("href", "/catalog/maintenance");
  await expect(page.getByRole("button", { name: "重新读取", exact: true })).toHaveCount(0);
  await expect(page.getByRole("button", { name: /确认来源范围|准备首次退货快照|确认建立首次快照/ })).toHaveCount(0);
  await page.getByRole("button", { name: "刷新准备状态" }).click();
  await expect(page.getByRole("status").filter({ hasText: "准备状态已刷新" })).toContainText("虚构前置仍未完成");
  await openStory(page, "pages-catalog-operations--versions-failure");
  await page.getByRole("button", { name: "重新读取", exact: true }).click();
  await expect(page.getByRole("heading", { name: "目录版本", exact: true })).toBeVisible();
  await openStory(page, "pages-catalog-operations--pending-failure");
  await expect(page.getByRole("alert")).toContainText("来源清单仍可使用");
  await page.getByRole("button", { name: "重新读取", exact: true }).click();
  await expect(page.getByRole("alert")).toHaveCount(0);
});
