import { expect, test } from "@playwright/test";
import { openStory } from "./storybookGateSupport";

test("draft table page navigation and source/base labels reuse the real table", async ({ page }) => {
  await openStory(page, "patterns-draft-data-table--reference");
  const table = page.getByRole("region", { name: "草稿数据对照", exact: true });
  await expect(table.getByRole("button", { name: "sales，当前值 22.50，与基础版本不同", exact: true })).toContainText("版本差异");
  await table.getByRole("button", { name: "下一页", exact: true }).click();
  await expect(table.getByRole("button", { name: "sku，当前值 A-07", exact: true })).toBeVisible();
  await table.getByRole("button", { name: "上一页", exact: true }).click();
  await expect(table.getByRole("button", { name: "sku，当前值 A-01", exact: true })).toBeVisible();
});
test("unchanged and empty current pages give distinct recovery paths; busy freezes writes and paging", async ({ page }) => {
  await openStory(page, "patterns-draft-data-table--unchanged");
  await expect(page.getByText("当前筛选没有匹配行", { exact: true })).toBeVisible();
  await page.getByRole("button", { name: "清除当前页筛选", exact: true }).click();
  await expect(page.getByRole("button", { name: "sku，当前值 A-06", exact: true })).toBeVisible();
  await openStory(page, "patterns-draft-data-table--empty");
  await expect(page.getByText("当前页没有数据行", { exact: true })).toBeVisible();
  await expect(page.getByRole("button", { name: "清除当前页筛选", exact: true })).toHaveCount(0);
  await openStory(page, "patterns-draft-data-table--busy");
  await expect(page.getByRole("button", { name: "新增纠错行", exact: true })).toBeDisabled();
  await expect(page.getByRole("button", { name: "下一页", exact: true })).toBeDisabled();
  await expect(page.getByRole("button", { name: "下一处差异", exact: true })).toBeDisabled();
});
