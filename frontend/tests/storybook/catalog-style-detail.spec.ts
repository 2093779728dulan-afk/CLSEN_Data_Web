import { expect, test } from "@playwright/test";
import { openStory, prepareInteractiveStory } from "./storybookGateSupport";

for (const width of [1280, 390]) {
  test(`detail filters real variants, expands aliases and preserves safe source navigation at ${width}px`, async ({ page }, testInfo) => {
    await page.setViewportSize({ width, height: 900 });
    const unexpected: string[] = [];
    await page.route(/^https?:\/\/[^/]+\/api\//, async route => { unexpected.push(route.request().url()); await route.abort(); });
    await openStory(page, "pages-catalog-style-detail--reference");
    await expect(page.getByRole("heading", { name: "浅蓝府绸衬衫", exact: true })).toBeVisible();
    await expect(page.getByRole("article")).toHaveCount(3);
    const search = page.getByRole("searchbox", { name: "查找实际变体" });
    await search.fill("米白");
    await expect(page.getByRole("article")).toHaveCount(1);
    await expect(page.getByRole("article")).toContainText("系统身份 SKU #2003");
    await page.getByRole("button", { name: "重置筛选", exact: true }).click();
    await expect(search).toBeFocused();
    await expect(page.getByRole("article")).toHaveCount(3);
    const first = page.getByRole("article", { name: "变体 DEMO-01-BLUE-S", exact: true });
    await first.getByRole("button", { name: "展开 Seller SKU", exact: true }).click();
    await expect(first.getByRole("table")).toBeVisible();
    await expect(first.getByText("DEMO-BLUE-S-OLD", { exact: true })).toBeVisible();
    await first.getByRole("button", { name: "查看来源明细", exact: true }).click();
    await expect(first.getByText("来源文件：demo-returns.csv", { exact: true })).toBeVisible();
    await expect(first.getByText("记录事件日期：2026-07-02", { exact: true })).toBeVisible();
    await expect(first.getByText("报告归属日：2026-07-03", { exact: true })).toBeVisible();
    await expect(first.getByText(/原始退货时间/)).toContainText("2026-07-02T23:00:00-07:00");
    await expect(first.getByRole("button", { name: "复制 SKU", exact: true })).toHaveCount(1);
    await first.getByText("系统追溯信息", { exact: true }).first().click();
    await expect(first.getByText("系统版本编号 7 · 系统记录编号 44（非文件行号）", { exact: true })).toBeVisible();
    await expect(first.getByRole("link", { name: "查看来源报告版本" }).first()).toHaveAttribute("href", "/versions?report_date=2026-07-02&report_type=business_report");
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
    await page.screenshot({ path: testInfo.outputPath(`detail-evidence-${width}.png`), fullPage: false });
    await first.getByRole("button", { name: "收起 Seller SKU", exact: true }).click();
    await expect(first.getByRole("table")).toHaveCount(0);
    await first.getByRole("button", { name: "展开 Seller SKU", exact: true }).click();
    await expect(first.getByRole("table")).toBeVisible();
    await page.getByRole("link", { name: "返回商品主档", exact: true }).click();
    await expect(page.getByRole("heading", { name: "虚构导航结果" })).toBeVisible();
    expect(unexpected).toEqual([]);
  });
}

test("detail loading, failures and pending links recover through their original actions", async ({ page }) => {
  await openStory(page, "pages-catalog-style-detail--loading");
  await expect(page.getByRole("status", { name: "正在读取商品详情" })).toBeVisible();
  await openStory(page, "pages-catalog-style-detail--read-failure");
  await page.getByRole("button", { name: "重新读取商品", exact: true }).click();
  await expect(page.getByRole("heading", { name: "浅蓝府绸衬衫", exact: true })).toBeVisible();
  for (const scenario of ["aliases-failure", "evidence-failure"]) {
    await openStory(page, `pages-catalog-style-detail--${scenario}`);
    await prepareInteractiveStory(page, `pages-catalog-style-detail--${scenario}`);
    const first = page.getByRole("article", { name: "变体 DEMO-01-BLUE-S", exact: true });
    await first.getByRole("button", { name: scenario === "aliases-failure" ? "重新读取销售别名" : "重新读取来源明细", exact: true }).click();
    if (scenario === "aliases-failure") await expect(first.getByRole("table")).toBeVisible();
    else await expect(first.getByText("来源文件：demo-business.csv", { exact: true })).toBeVisible();
    await expect(first.getByRole("alert")).toHaveCount(0);
  }
  await openStory(page, "pages-catalog-style-detail--empty");
  await expect(page.getByRole("heading", { name: "当前商品卡暂无实际变体" })).toBeVisible();
  await openStory(page, "pages-catalog-style-detail--read-only");
  await expect(page.getByRole("navigation", { name: "商品主档导航" }).getByRole("link")).toHaveCount(1);
  await expect(page.getByRole("button", { name: "修改名称 / 分类" })).toHaveCount(0);
  await openStory(page, "pages-catalog-style-detail--pending-candidates");
  await page.getByRole("link", { name: "进入审核", exact: true }).click();
  await expect(page.getByRole("heading", { name: "虚构导航结果" })).toBeVisible();
});
