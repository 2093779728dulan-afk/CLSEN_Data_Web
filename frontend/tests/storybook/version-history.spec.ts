import { expect, test } from "@playwright/test";
import { openStory } from "./storybookGateSupport";

for (const width of [1280, 768, 390]) {
  test(`version history selects, reads, pages and filters at ${width}px`, async ({ page }) => {
    await page.setViewportSize({ width, height: 900 });
    await openStory(page, "pages-version-history--reference");
    const history = page.getByRole("button", { name: "查看版本 v1，历史发布" });
    await history.focus(); await history.press("Enter");
    await expect(history).toHaveAttribute("aria-pressed", "true");
    await expect(page.getByRole("heading", { name: "v1 · 历史发布", exact: true })).toBeVisible();
    await page.getByRole("button", { name: "查看此版本数据", exact: true }).click();
    const rows = page.getByRole("region", { name: "v1 数据明细", exact: true });
    await expect(rows.getByRole("table")).toBeVisible();
    await rows.getByRole("button", { name: "下一页", exact: true }).click();
    await expect(rows.getByRole("rowheader", { name: "51", exact: true })).toBeVisible();
    await rows.getByRole("button", { name: "上一页", exact: true }).click();
    await expect(rows.getByRole("rowheader", { name: "1", exact: true })).toBeVisible();
    await page.getByRole("region", { name: "版本数据表格，可横向滚动" }).focus();
    await expect(page.getByRole("region", { name: "版本数据表格，可横向滚动" })).toBeFocused();
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
    await page.getByRole("combobox", { name: "报表类型", exact: true }).selectOption("return_report");
    await expect(page.getByRole("link", { name: "返回日期工作台", exact: true }).first()).toHaveAttribute("href", "/published/2026-09-12?report_type=return_report");
    await page.getByLabel("报告日期", { exact: true }).fill("2026-09-13");
    await expect(page.getByText("该日期的退货报告还没有版本。", { exact: true })).toBeVisible();
    await page.getByLabel("报告日期", { exact: true }).fill("2026-09-12");
    await expect(history).toBeVisible();
  });
}

test("version history recovers failures and preserves manager restrictions and task links", async ({ page }) => {
  for (const story of ["read-failure", "detail-failure"]) {
    await openStory(page, `pages-version-history--${story}`);
    await expect(page.getByRole("alert")).toBeVisible();
    await page.getByRole("button", { name: "重新读取版本记录", exact: true }).click();
    await expect(page.getByRole("heading", { name: "v3 · 当前发布", exact: true })).toBeVisible();
  }
  await openStory(page, "pages-version-history--rows-failure");
  await page.getByRole("button", { name: "重新读取", exact: true }).click();
  await expect(page.getByRole("table")).toBeVisible();
  await openStory(page, "pages-version-history--manager");
  const tasks = page.getByRole("region", { name: "已有批量审核任务", exact: true });
  await expect(tasks.getByRole("link")).toHaveAttribute("href", "/review/batch/81");
  await tasks.getByRole("button", { name: "下一页", exact: true }).click();
  await expect(tasks.getByRole("link")).toHaveAttribute("href", "/review/batch/82");
  await tasks.getByRole("button", { name: "刷新任务", exact: true }).click();
  await expect(tasks.getByRole("link")).toHaveAttribute("href", "/review/batch/81");
  await page.getByRole("button", { name: "创建修订", exact: true }).click();
  await expect(page.getByText(/虚构样板：创建修订入口已触发/)).toBeVisible();
  await openStory(page, "pages-version-history--active-draft");
  await expect(page.getByRole("button", { name: "创建修订", exact: true })).toBeDisabled();
  await page.getByRole("button", { name: "查看版本 v4，活动草稿" }).click();
  await expect(page.getByRole("link", { name: "继续审核草稿", exact: true })).toHaveAttribute("href", "/review/2026-09-12?report_type=business_report");
  await openStory(page, "pages-version-history--batch-drafts");
  await expect(page.getByRole("link", { name: "返回批量任务", exact: true })).toHaveAttribute("href", "/review/batch/81");
  await expect(page.getByLabel("报告日期", { exact: true })).toHaveCount(0);
});
