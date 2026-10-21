import { expect, test } from "@playwright/test";
import { openStory } from "./storybookGateSupport";

for (const width of [1280, 768, 390]) {
  test(`batch review shared selection, confirmation and pause path at ${width}px`, async ({ page }) => {
    await page.setViewportSize({ width, height: 900 });
    await openStory(page, "pages-batch-review--reference");
    await expect(page.getByRole("checkbox", { name: "选择 duplicate-2026-09-12.csv", exact: true })).toBeDisabled();
    const second = page.getByRole("checkbox", { name: "选择 returns-2026-09-13.csv", exact: true });
    await second.focus(); await second.press("Space"); await expect(second).not.toBeChecked();
    const confirm = page.getByRole("button", { name: "开始批量审核（1 项）", exact: true });
    await expect(confirm).toBeDisabled();
    await page.getByRole("checkbox", { name: "我已核对所选文件的报告日期和报表类型。", exact: true }).check();
    await confirm.click();
    await expect(page.getByRole("table", { name: "批量审核处理进度", exact: true })).toBeVisible();
    await expect(page.getByText("已取消选择", { exact: true })).toBeVisible();
    await page.getByRole("button", { name: "暂停批量处理", exact: true }).click();
    await expect(page.getByRole("button", { name: "恢复批量处理", exact: true })).toBeVisible();
    await page.getByRole("button", { name: "恢复批量处理", exact: true }).click();
    await expect(page.getByRole("button", { name: "暂停批量处理", exact: true })).toBeVisible();
    const scroll = page.getByRole("table", { name: "批量审核处理进度", exact: true }).locator("..");
    await scroll.focus(); await expect(scroll).toBeFocused();
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
  });
}

test("batch review completion links, retry, unknown outcome, busy and failure recovery", async ({ page }) => {
  await openStory(page, "pages-batch-review--exceptions");
  await expect(page.getByRole("link", { name: "查看全部待发布草稿", exact: true })).toHaveAttribute("href", "/versions?batch_review_run_id=81");
  await page.getByRole("button", { name: "重试", exact: true }).click();
  await expect(page.getByText("排队中", { exact: true })).toBeVisible();
  await expect(page.getByRole("button", { name: "重试", exact: true })).toHaveCount(0);
  await openStory(page, "pages-batch-review--outcome-unknown");
  await expect(page.getByText("正在确认服务器结果，请勿重复提交。", { exact: true })).toBeVisible();
  await expect(page.getByRole("button", { name: "重试", exact: true })).toHaveCount(0);
  await openStory(page, "pages-batch-review--confirming");
  await expect(page.getByRole("button", { name: "正在开始…", exact: true })).toBeDisabled();
  await openStory(page, "pages-batch-review--retrying");
  await expect(page.getByRole("button", { name: "正在重试…", exact: true })).toBeDisabled();
  await openStory(page, "pages-batch-review--read-failure");
  await page.getByRole("button", { name: "重新读取", exact: true }).click();
  await expect(page.getByRole("heading", { name: "批量审核", exact: true })).toBeVisible();
  await openStory(page, "pages-batch-review--action-failure");
  await expect(page.getByRole("alert")).toBeVisible();
  await page.getByRole("button", { name: "重新读取任务", exact: true }).click();
  await expect(page.getByRole("alert")).toHaveCount(0);
  await openStory(page, "pages-batch-review--empty");
  await expect(page.getByRole("button", { name: "开始批量审核（0 项）", exact: true })).toBeDisabled();
});
