import { expect, test } from "@playwright/test";
import { openStory } from "./storybookGateSupport";

for (const width of [1280, 390]) {
  test(`source pagination, keyboard review, style return and refresh at ${width}px`, async ({ page }) => {
    await page.setViewportSize({ width, height: 900 });
    await openStory(page, "patterns-catalog-unmatched-sources--reference");
    await expect(page.getByRole("region", { name: "待归属来源核对", exact: true })).toContainText("目录记录 #104");
    await expect(page.getByRole("button", { name: "上一页", exact: true })).toBeDisabled();
    await expect(page.getByRole("region", { name: "来源清单", exact: true }).getByRole("listitem")).toHaveCount(2);
    const next = page.getByRole("button", { name: "下一页", exact: true }); await next.focus(); await next.press("Enter");
    await expect(page.getByText("DEMO-3-Blue-XL", { exact: true })).toBeVisible(); await expect(next).toBeDisabled();
    const review = page.getByRole("link", { name: "查看候选", exact: true }); await expect(review).toHaveAttribute("href", "/catalog/imports/903"); await review.focus(); await review.press("Enter");
    await expect(page.getByRole("heading", { name: "虚构关联结果" })).toBeVisible(); await page.getByRole("link", { name: "返回待归属来源" }).click();
    await expect(page.getByText("DEMO-3-Blue-XL", { exact: true })).toBeVisible();
    await page.getByRole("link", { name: "DEMO-01 · 示例蓝色衬衫", exact: true }).click();
    await expect(page.getByRole("link", { name: "返回待归属来源" })).toHaveAttribute("href", /page=2/);
    await page.getByRole("link", { name: "返回待归属来源" }).click();
    const maintenance = page.getByRole("link", { name: "生成或继续审核候选", exact: true }); const href = await maintenance.getAttribute("href");
    const back = new URL(href!, "http://localhost").searchParams.get("return_to")!; expect(new URL(back, "http://localhost").searchParams.get("page")).toBe("2"); expect(back).toContain("from=2026-09-01");
    await maintenance.click(); await page.getByRole("link", { name: "返回待归属来源" }).click(); await expect(page.getByText("DEMO-3-Blue-XL", { exact: true })).toBeVisible();
    await page.getByRole("button", { name: "上一页", exact: true }).click(); await expect(page.getByText("DEMO-1-Blue-XL", { exact: true })).toBeVisible();
    await page.reload(); await expect(page.getByRole("button", { name: "上一页", exact: true })).toBeDisabled();
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
  });
}
test("empty evidence, future range, later empty page and currency boundaries", async ({ page }) => {
  await openStory(page, "patterns-catalog-unmatched-sources--empty"); await expect(page.getByRole("heading", { name: "当前范围没有未归属来源。", exact: true })).toBeVisible();
  await openStory(page, "patterns-catalog-unmatched-sources--no-evidence"); await expect(page.getByRole("heading", { name: "当前范围没有可用的发布依据", exact: true })).toBeVisible(); await expect(page.getByRole("region", { name: "来源清单", exact: true })).toHaveCount(0);
  await expect(page.getByRole("link", { name: "查看该日发布状态" })).toHaveAttribute("href", "/review/2026-09-01");
  await openStory(page, "patterns-catalog-unmatched-sources--future-range"); await expect(page.getByRole("heading", { name: "所选日期尚未到达" })).toBeVisible(); await expect(page.getByText("少计销量", { exact: true })).toHaveCount(0);
  await openStory(page, "patterns-catalog-unmatched-sources--empty-page"); await expect(page.getByRole("heading", { name: "本页没有来源记录" })).toBeVisible(); await page.getByRole("button", { name: "上一页", exact: true }).click(); await expect(page.getByText("DEMO-1-Blue-XL", { exact: true })).toBeVisible();
  await openStory(page, "patterns-catalog-unmatched-sources--multi-currency"); const summary = page.getByRole("region", { name: "待归属来源核对", exact: true }); await expect(summary).toContainText("US$99.90 · EUR 20.00"); await page.getByRole("button", { name: "下一页", exact: true }).click(); await expect(page.getByRole("region", { name: "来源清单", exact: true })).toContainText("0 件 · US$0.00");
});
test("partial failure explicit recovery, persistent loading and safe long preview", async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 900 });
  await openStory(page, "patterns-catalog-unmatched-sources--pending-failure"); await expect(page.getByRole("alert")).toContainText("审核候选读取失败"); await expect(page.getByText("DEMO-1-Blue-XL", { exact: true })).toBeVisible();
  const retry = page.getByRole("button", { name: "重新读取", exact: true }); await retry.focus(); await retry.press("Enter"); await expect(page.getByRole("link", { name: "DEMO-01 · 示例蓝色衬衫", exact: true })).toBeVisible(); await expect(page.getByText("DEMO-1-Blue-XL", { exact: true })).toBeVisible();
  await page.reload(); await expect(page.getByRole("alert")).toBeVisible();
  await openStory(page, "patterns-catalog-unmatched-sources--loading"); await expect(page.getByRole("region", { name: "待归属来源核对", exact: true })).toHaveAttribute("aria-busy", "true");
  await openStory(page, "patterns-catalog-unmatched-sources--pending-loading"); await expect(page.getByRole("status").filter({ hasText: "正在读取已有审核候选" })).toBeVisible(); await expect(page.getByText("DEMO-1-Blue-XL", { exact: true })).toBeVisible();
  await openStory(page, "patterns-catalog-unmatched-sources--long-preview"); await expect(page.getByText("预览已截断", { exact: true })).toHaveCount(2); expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
});
