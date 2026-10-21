import { expect, test } from "@playwright/test";
import { VIEWPORTS } from "./storybookGateManifest";
import { openStory } from "./storybookGateSupport";

for (const viewport of VIEWPORTS) test(`date evidence, exact draft switch and keyboard at ${viewport.width}px`, async ({ page }) => {
  await page.setViewportSize(viewport); const api: string[] = []; const errors: string[] = [];
  page.on("request", r => { if (new URL(r.url()).pathname.startsWith("/api/")) api.push(r.url()); }); page.on("pageerror", e => errors.push(e.message));
  await openStory(page, "pages-advanced-review-workspace--reference");
  const rail = page.getByRole("complementary", { name: "8 月每日证据轨", exact: true }); await expect(rail.getByRole("button")).toHaveCount(31);
  const switcher = page.getByRole("group", { name: "选择待审核报表", exact: true });
  const returns = switcher.getByRole("button", { name: "退货报告 · 草稿 v3", exact: true }); await returns.focus(); await returns.press("Enter");
  await expect(returns).toHaveAttribute("aria-pressed", "true"); await expect(page.getByText("当前草稿 · 退货报告 v3", { exact: true })).toBeVisible();
  await expect(page.getByRole("region", { name: "当前工作日", exact: true })).toContainText("当前发布 v1");
  const day9 = rail.getByRole("button", { name: "选择 8 月 9 日，需处理：阻断、导入失败或原文件异常", exact: true }); await day9.focus(); await day9.press("Enter");
  await expect(day9).toHaveAttribute("aria-current", "date"); await expect(page.getByRole("region", { name: "当前工作日", exact: true })).toContainText("2026 年 8 月 9 日");
  await expect(page.getByRole("group", { name: "选择待审核报表", exact: true })).toHaveCount(0);
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true); expect(api).toEqual([]); expect(errors).toEqual([]);
});

test("unknown calendar, retry, empty, published, read-only and source context", async ({ page }) => {
  await openStory(page, "pages-advanced-review-workspace--loading"); await expect(page.getByRole("status", { name: "正在读取日期状态", exact: true })).toBeVisible();
  await expect(page.getByRole("button", { name: /状态待确认/ })).toHaveCount(31); await expect(page.getByText("尚未导入", { exact: true })).toHaveCount(0);
  await openStory(page, "pages-advanced-review-workspace--read-failure"); await expect(page.getByRole("alert")).toContainText("当前报表状态尚未确认");
  await page.getByRole("button", { name: "重新读取日期状态", exact: true }).click(); await expect(page.getByRole("group", { name: "选择待审核报表", exact: true })).toBeVisible();
  await openStory(page, "pages-advanced-review-workspace--refreshing"); await expect(page.getByText("当前草稿 · 经营报告 v2", { exact: true })).toBeVisible();
  await openStory(page, "pages-advanced-review-workspace--empty"); await expect(page.getByText("尚未导入", { exact: true })).toHaveCount(2);
  await openStory(page, "pages-advanced-review-workspace--published"); await expect(page.getByText("已发布", { exact: true })).toBeVisible(); await expect(page.getByRole("group", { name: "选择待审核报表", exact: true })).toHaveCount(0);
  await openStory(page, "pages-advanced-review-workspace--read-only"); await expect(page.getByText("此账号仅可查看已发布数据", { exact: true })).toBeVisible(); await expect(page.getByRole("group", { name: "选择待审核报表", exact: true })).toHaveCount(0);
  await openStory(page, "pages-advanced-review-workspace--source-batch"); await expect(page.getByRole("heading", { name: "从指定文件重新审核", exact: true })).toBeVisible(); await expect(page.getByText("来源批次 #11", { exact: true })).toBeVisible();
  await expect(page.getByRole("link", { name: "返回日期表格", exact: true })).toHaveAttribute("href", "/review/2026-08-10?report_type=business_report");
});
