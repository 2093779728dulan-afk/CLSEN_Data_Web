import { expect, test } from "@playwright/test";
import { openStory } from "./storybookGateSupport";

for (const width of [1280, 390]) {
  test(`version identity, base record and keyboard reload at ${width}px`, async ({ page }) => {
    await page.setViewportSize({ width, height: 900 });
    await openStory(page, "patterns-catalog-versions--reference");
    const table = page.getByRole("table", { name: "已批准目录记录" });
    await expect(table.getByRole("row").nth(1)).toContainText("V4");
    await expect(table.getByRole("row").nth(1)).toContainText("目录记录 #104");
    await expect(table.getByRole("row").nth(1).getByRole("cell").nth(3)).toHaveText("目录记录 #103");
    await expect(table.getByRole("row").nth(3).getByRole("cell").nth(3)).toHaveText("首次");
    const scroll = table.locator(".."); await scroll.focus(); await expect(scroll).toBeFocused();
    if (width === 390) { await scroll.press("ArrowRight"); await expect.poll(() => scroll.evaluate(element => element.scrollLeft)).toBeGreaterThan(0); }
    const reload = page.getByRole("button", { name: "重新读取版本", exact: true }); await reload.focus(); await reload.press("Enter");
    await expect(page.getByRole("status").filter({ hasText: "正在读取目录版本" })).toBeVisible();
    await expect(table).toBeVisible(); await expect(page.getByRole("status").filter({ hasText: "读取已完成" })).toContainText("第 1 次");
    await page.reload(); await expect(table).toBeVisible(); await expect(page.getByRole("status").filter({ hasText: "读取已完成" })).toHaveCount(0);
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
  });
}
test("empty navigation, first version, unknown risk and missing fields preserve meaning", async ({ page }) => {
  await openStory(page, "patterns-catalog-versions--empty");
  const link = page.getByRole("link", { name: "前往批量维护完成初始化", exact: true }); await expect(link).toHaveAttribute("href", "/catalog/maintenance");
  await link.click(); await expect(page.getByRole("heading", { name: "初始化维护入口" })).toBeVisible();
  await page.getByRole("link", { name: "返回目录版本" }).click(); await expect(link).toBeVisible();
  await openStory(page, "patterns-catalog-versions--first-version"); await expect(page.getByRole("table")).toContainText("V1"); await expect(page.getByRole("cell", { name: "首次", exact: true })).toBeVisible();
  await openStory(page, "patterns-catalog-versions--unknown-risk"); await expect(page.getByRole("table")).toContainText("future_risk_code"); await expect(page.getByRole("cell", { name: "正常", exact: true })).toHaveCount(0);
  await openStory(page, "patterns-catalog-versions--missing-fields"); const row = page.getByRole("table").getByRole("row").nth(1);
  await expect(row.getByRole("cell").nth(1)).toHaveText("—"); await expect(row.getByRole("cell").nth(2)).toHaveText("—"); await expect(row.getByRole("cell").nth(3)).toHaveText("—"); await expect(page.getByText("首次", { exact: true })).toHaveCount(0);
});
test("failed reread requires explicit retry; loading and long values stay usable on mobile", async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 900 });
  await openStory(page, "patterns-catalog-versions--refresh-failure");
  await page.getByRole("button", { name: "重新读取版本" }).click(); await expect(page.getByRole("alert")).toContainText("无法读取目录版本");
  await expect(page.getByRole("table")).toHaveCount(0);
  await page.getByRole("button", { name: "重新读取", exact: true }).click(); await expect(page.getByRole("table")).toBeVisible();
  await expect(page.getByRole("status").filter({ hasText: "读取已完成" })).toContainText("第 2 次");
  await openStory(page, "patterns-catalog-versions--loading"); await expect(page.getByRole("region", { name: "目录版本记录" })).toHaveAttribute("aria-busy", "true"); await expect(page.getByRole("table")).toHaveCount(0);
  await openStory(page, "patterns-catalog-versions--long-values");
  const table = page.getByRole("table"); await expect(table).toContainText("12345678901234567890");
  await table.locator("..").focus(); await table.locator("..").press("End");
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
});
