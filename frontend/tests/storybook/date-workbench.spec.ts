import { expect, test } from "@playwright/test";
import { openStory } from "./storybookGateSupport";

for (const width of [1280, 768, 390]) {
  test(`date workbench shared path edits, saves, filters, undoes and hands off at ${width}px`, async ({ page }) => {
    await page.setViewportSize({ width, height: 900 });
    await openStory(page, "pages-date-workbench--manager");
    await expect(page.getByRole("table", { name: "经营报告原始数据" })).toBeVisible();
    await expect(page.getByRole("button", { name: "前往发布", exact: true })).toBeDisabled();
    await page.getByRole("button", { name: "开始修改", exact: true }).click();
    const cell = page.getByRole("textbox", { name: "Title，第 1 行", exact: true });
    await cell.click();
    await cell.fill("放弃的输入"); await cell.press("Escape");
    await expect(cell).toHaveValue("示例蓝色衬衫 · 中码");
    await cell.fill("新的示例名称"); await cell.press("Enter");
    await expect(page.getByRole("button", { name: "前往发布", exact: true })).toBeDisabled();
    await expect(page.getByText("已保存", { exact: true })).toBeVisible();
    await page.getByRole("checkbox", { name: "只看修改", exact: true }).click();
    await expect(page.getByRole("checkbox", { name: "只看修改", exact: true })).toBeChecked();
    await expect(page.getByRole("table", { name: "经营报告原始数据" }).locator("tbody tr")).toHaveCount(1);
    await page.getByRole("checkbox", { name: "只看修改", exact: true }).click();
    await expect(page.getByRole("checkbox", { name: "只看修改", exact: true })).not.toBeChecked();
    const search = page.getByRole("textbox", { name: "搜索表格", exact: true });
    await search.fill("不存在"); await search.press("Enter"); await expect(page.getByRole("table", { name: "经营报告原始数据" }).locator("tbody tr")).toHaveCount(0);
    await search.fill(""); await search.press("Enter");
    await page.getByRole("button", { name: "列设置", exact: true }).click();
    await page.getByRole("checkbox", { name: "Sales", exact: true }).uncheck();
    await page.getByRole("button", { name: "关闭列设置", exact: true }).click();
    await expect(page.getByRole("button", { name: "列设置", exact: true })).toBeFocused();
    await expect(page.getByRole("button", { name: "按 Sales 排序", exact: true })).toHaveCount(0);
    await page.getByRole("button", { name: "撤销上次修改", exact: true }).click();
    await expect(cell).toHaveValue("示例蓝色衬衫 · 中码");
    await page.getByRole("region", { name: "日期工作台数据表格，可横向滚动" }).focus();
    await expect(page.getByRole("region", { name: "日期工作台数据表格，可横向滚动" })).toBeFocused();
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
    await page.getByRole("button", { name: "前往发布", exact: true }).click();
    await expect(page.getByRole("heading", { name: "虚构导航目的地" })).toBeVisible();
    await expect(page.getByText("/review-advanced/2026-09-12?report_type=business_report&version_id=92", { exact: true })).toBeVisible();
  });
}
test("workbench empty, import confirmation, conflict, failed-cell and read recovery states", async ({ page }) => {
  await openStory(page, "pages-date-workbench--read-only-empty");
  await expect(page.getByText("当前没有可读取的已发布表格。", { exact: true })).toBeVisible();
  await expect(page.locator('input[type="file"]')).toHaveCount(0);
  await openStory(page, "pages-date-workbench--empty");
  await page.locator('input[type="file"]').setInputFiles({ name: "fictional.csv", mimeType: "text/csv", buffer: Buffer.from("Title\nExample\n") });
  await expect(page.getByRole("alert")).toContainText("文件类型与当前入口不一致");
  await page.getByRole("combobox", { name: "类型", exact: true }).selectOption("return_report");
  await page.getByRole("button", { name: "按退货报告继续", exact: true }).click();
  await expect(page.getByRole("table", { name: "退货报告原始数据" })).toBeVisible();
  await openStory(page, "pages-date-workbench--import-conflict");
  await expect(page.getByText("新文件已保存，尚未替换当前表格", { exact: true })).toBeVisible();
  await page.getByRole("button", { name: "核对文件并继续审核", exact: true }).click();
  await expect(page.getByText("/review-advanced/2026-09-12?batch_id=44&report_type=business_report", { exact: true })).toBeVisible();
  await openStory(page, "pages-date-workbench--save-failure");
  await expect(page.getByRole("alert")).toContainText("请重新提交");
  await expect(page.getByRole("button", { name: "前往发布", exact: true })).toBeDisabled();
  const cell = page.getByRole("textbox", { name: "Title，第 1 行", exact: true });
  await cell.focus(); await cell.press("Enter");
  await expect(page.getByText("已保存", { exact: true })).toBeVisible();
  await expect(page.getByRole("button", { name: "前往发布", exact: true })).toBeEnabled();
  await openStory(page, "pages-date-workbench--read-failure");
  await page.getByRole("button", { name: "重新读取", exact: true }).click();
  await expect(page.getByRole("table", { name: "经营报告原始数据" })).toBeVisible();
});

for (const width of [1280, 390]) {
  test(`cell feedback keeps saving editable and exposes full conflict recovery at ${width}px`, async ({ page }) => {
    await page.setViewportSize({ width, height: 900 });
    await openStory(page, "pages-date-workbench--cell-saving");
    const cell = page.getByRole("textbox", { name: "Title，第 1 行", exact: true });
    await cell.click();
    await expect(cell).toHaveAttribute("aria-busy", "true");
    await expect(cell).toBeEditable();
    await expect(page.getByText("1 个正在保存", { exact: true })).toBeVisible();
    await cell.fill("保存期间的新输入");
    await expect(page.getByText("1 个待保存", { exact: true })).toBeVisible();
    await cell.press("Enter");
    await expect(page.getByText("已保存", { exact: true })).toBeVisible();
    await expect(cell).toHaveValue("保存期间的新输入");
    await openStory(page, "pages-date-workbench--cell-conflict");
    await expect(cell).toHaveAttribute("aria-invalid", "true");
    await expect(page.getByText("版本冲突", { exact: true })).toBeVisible();
    await expect(page.getByRole("alert")).toContainText("另一位审核员");
    const description = await cell.getAttribute("aria-describedby");
    await expect(page.locator(`[id="${description}"]`)).toContainText("输入已保留");
    await cell.press("Escape");
    await expect(cell).toHaveValue("示例蓝色衬衫 · 中码");
    await expect(page.getByRole("alert")).toHaveCount(0);
    await openStory(page, "pages-date-workbench--cell-long-error");
    const alert = page.getByRole("alert");
    await expect(alert).toContainText("也不会进入已发布数据");
    expect(await alert.evaluate(el => el.scrollHeight <= el.clientHeight + 1)).toBe(true);
    await cell.focus(); await cell.press("Enter");
    await expect(page.getByText("已保存", { exact: true })).toBeVisible();
    await expect(cell).not.toHaveAttribute("aria-invalid", "true");
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
  });
}
