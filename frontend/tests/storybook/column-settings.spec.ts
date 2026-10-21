import { expect, test } from "@playwright/test";
import { COLUMN_SETTINGS_STORY_IDS } from "./storybookGateManifest";
import { openStory, prepareInteractiveStory } from "./storybookGateSupport";

for (const storyId of ["pages-date-workbench--column-settings", "pages-published-detail-ledger--column-settings"]) {
  test(`${storyId} uses the shared panel and restores its trigger focus`, async ({ page }) => {
    await page.setViewportSize({ width: 390, height: 844 });
    await openStory(page, storyId); await prepareInteractiveStory(page, storyId);
    const panel = page.getByRole("region", { name: "列设置", exact: true });
    const label = storyId.startsWith("pages-date") ? "Sales" : "销售额";
    await panel.getByRole("checkbox", { name: label, exact: true }).uncheck();
    await expect(page.getByRole("columnheader").filter({ hasText: label })).toHaveCount(0);
    await panel.getByRole("checkbox", { name: label, exact: true }).check();
    await expect(page.getByRole("columnheader").filter({ hasText: label })).toHaveCount(1);
    await panel.getByRole("button", { name: "关闭列设置", exact: true }).click();
    await expect(page.getByRole("button", { name: "列设置", exact: true })).toBeFocused();
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
  });
}

test("column settings preserves real layout, search, keyboard, drag and browser preferences", async ({ page }) => {
  await openStory(page, "patterns-column-settings--reference");
  const panel = page.getByRole("region", { name: "列设置", exact: true });
  await expect(panel.getByRole("checkbox", { name: "Seller SKU", exact: true })).toBeDisabled();
  await panel.getByRole("searchbox", { name: "搜索列" }).fill("sessions");
  await expect(panel.getByRole("checkbox", { name: "访问次数" })).toBeVisible();
  await expect(panel.getByRole("checkbox", { name: "销售额" })).toHaveCount(0);
  await panel.getByRole("button", { name: "清空列搜索", exact: true }).click();
  await panel.getByRole("checkbox", { name: "销售额" }).uncheck();
  await expect(page.getByLabel("当前显示列")).not.toContainText("销售额");
  await page.reload();
  await expect(panel.getByRole("checkbox", { name: "销售额" })).not.toBeChecked();
  await panel.getByRole("checkbox", { name: "销售额" }).check();
  await panel.getByRole("button", { name: "将 销售额 下移" }).click();
  await expect(page.getByLabel("当前显示列")).toHaveText("Seller SKU / 访问次数 / 销售额 / 来源扩展字段");
  await panel.getByRole("button", { name: "将 销售额 上移" }).click();
  await panel.getByRole("checkbox", { name: "来源扩展字段" }).locator("xpath=ancestor::li").dragTo(panel.getByRole("checkbox", { name: "访问次数" }).locator("xpath=ancestor::li"));
  await expect(page.getByLabel("当前显示列")).toHaveText("Seller SKU / 销售额 / 来源扩展字段 / 访问次数");
  await panel.getByRole("checkbox", { name: "来源扩展字段" }).locator("xpath=ancestor::li").dragTo(panel.getByRole("region", { name: "将拖动列放到末尾" }));
  await expect(page.getByLabel("当前显示列")).toHaveText("Seller SKU / 销售额 / 访问次数 / 来源扩展字段");
  await panel.getByRole("button", { name: "只显示统计字段", exact: true }).click();
  await expect(panel.getByRole("checkbox", { name: "来源扩展字段" })).not.toBeChecked();
  await panel.getByRole("button", { name: "恢复原始顺序" }).click();
  await panel.getByRole("button", { name: "重置列宽" }).click();
  await panel.getByRole("checkbox", { name: "来源扩展字段" }).check();
  await panel.getByRole("checkbox", { name: "销售额" }).focus();
  await page.keyboard.press("Space");
  await expect(panel.getByRole("checkbox", { name: "销售额" })).not.toBeChecked();
  await page.keyboard.press("Space");
  await page.keyboard.press("Escape");
  await expect(panel).toHaveCount(0);
  await expect(page.getByRole("button", { name: "列设置", exact: true })).toBeFocused();
  await page.getByRole("button", { name: "列设置", exact: true }).click();
  await expect(panel.getByRole("checkbox", { name: "销售额" })).toBeChecked();
});

for (const storyId of COLUMN_SETTINGS_STORY_IDS.filter(id => !id.endsWith("--reference"))) {
  test(`${storyId} supports its real empty, protected or overflow state`, async ({ page }) => {
    await page.setViewportSize({ width: 390, height: 844 });
    await openStory(page, storyId); await prepareInteractiveStory(page, storyId);
    const panel = page.getByRole("region", { name: "列设置", exact: true });
    if (storyId.endsWith("--filtered-empty")) {
      await expect(panel.getByText("没有匹配的列", { exact: true })).toBeVisible();
      await panel.getByRole("button", { name: "清空列搜索", exact: true }).last().click();
      await expect(panel.getByRole("checkbox")).toHaveCount(4);
    } else if (storyId.endsWith("--identity-only")) await expect(panel.getByRole("checkbox")).toBeDisabled();
    else if (storyId.endsWith("--empty")) { await expect(panel.getByText("暂无可设置的列")).toBeVisible(); await expect(panel.getByRole("button", { name: "只显示统计字段" })).toBeDisabled(); }
    else if (storyId.endsWith("--many-columns")) { await panel.getByRole("checkbox", { name: "来源字段 24", exact: true }).uncheck(); await expect(panel.getByRole("checkbox", { name: "来源字段 24", exact: true })).not.toBeChecked(); }
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
    if (await panel.getByRole("checkbox").count()) expect(await panel.getByRole("checkbox").first().evaluate(el => getComputedStyle(el).minHeight)).toBe("0px");
  });
}
