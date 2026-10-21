import { expect, test } from "@playwright/test";
import { openStory, prepareInteractiveStory } from "./storybookGateSupport";

for (const width of [1280, 768, 390]) {
  test(`field drawer edits, restores, revises notes and returns focus at ${width}px`, async ({ page }) => {
    await page.setViewportSize({ width, height: 900 });
    await openStory(page, "patterns-field-review--reference");
    const trigger = page.getByRole("button", { name: /sales，当前值 42.50/ }); await trigger.click();
    const drawer = page.getByRole("dialog", { name: "字段对照", exact: true });
    await expect(drawer.getByRole("button", { name: "关闭字段对照", exact: true })).toBeFocused();
    await drawer.getByRole("textbox", { name: "当前值", exact: true }).fill("44.20");
    await drawer.getByRole("textbox", { name: "修改原因", exact: true }).fill("");
    await expect(drawer.getByRole("button", { name: "保存字段修改", exact: true })).toBeDisabled();
    await drawer.getByRole("textbox", { name: "修改原因", exact: true }).fill("虚构原表核对");
    await drawer.getByRole("button", { name: "保存字段修改", exact: true }).click();
    await expect(drawer.getByText("当前草稿值", { exact: true }).locator("..")).toContainText("44.20");
    await drawer.getByRole("button", { name: "恢复父版本值", exact: true }).click();
    await expect(drawer.getByRole("textbox", { name: "当前值", exact: true })).toHaveValue("40.00");
    await drawer.getByRole("button", { name: "恢复源文件值", exact: true }).click();
    await expect(drawer.getByRole("textbox", { name: "当前值", exact: true })).toHaveValue("39.00");
    await drawer.getByRole("button", { name: "撤销本次修改", exact: true }).click();
    await expect(drawer.getByRole("textbox", { name: "当前值", exact: true })).toHaveValue("40.00");
    await drawer.getByRole("textbox", { name: "备注内容", exact: true }).fill("虚构追加字段备注");
    await drawer.getByRole("combobox", { name: "可见范围", exact: true }).selectOption("viewer_visible");
    await drawer.getByRole("button", { name: "追加字段备注", exact: true }).click();
    await expect(drawer.getByText("虚构追加字段备注", { exact: true })).toBeVisible();
    await drawer.getByRole("button", { name: "修订备注", exact: true }).first().click();
    await drawer.getByRole("textbox", { name: "修订备注 fictional-field-note", exact: true }).fill("虚构备注新修订");
    await drawer.getByRole("button", { name: "保存新修订", exact: true }).click();
    await expect(drawer.getByText("虚构备注新修订", { exact: true })).toBeVisible();
    await page.keyboard.press("Escape"); await expect(drawer).toHaveCount(0);
    await expect(page.getByRole("button", { name: /sales，当前值 40.00/ })).toBeFocused();
    await page.getByRole("button", { name: /sales，当前值 40.00/ }).click();
    await expect(drawer.getByRole("textbox", { name: "当前值", exact: true })).toHaveValue("40.00");
    await drawer.getByRole("button", { name: "关闭字段对照", exact: true }).click();
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
    await openStory(page, "patterns-field-review--save-failure");
    await page.getByRole("button", { name: /sales，当前值 42.50/ }).click();
    await drawer.getByRole("textbox", { name: "当前值", exact: true }).fill("47.25");
    await drawer.getByRole("textbox", { name: "修改原因", exact: true }).fill("失败恢复核对");
    await drawer.getByRole("button", { name: "保存字段修改", exact: true }).click();
    await expect(drawer.getByRole("alert")).toContainText("编辑内容保留");
    await expect(drawer.getByRole("textbox", { name: "当前值", exact: true })).toHaveValue("47.25");
    await expect(drawer.getByRole("textbox", { name: "修改原因", exact: true })).toHaveValue("失败恢复核对");
    await drawer.getByRole("button", { name: "保存字段修改", exact: true }).click();
    await expect(drawer.getByText("当前草稿值", { exact: true }).locator("..")).toContainText("47.25");
  });
}

test("field drawer handles null, integer, readonly, empty and pending states", async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 900 });
  await openStory(page, "patterns-field-review--nullable"); await prepareInteractiveStory(page, "patterns-field-review--nullable");
  let drawer = page.getByRole("dialog", { name: "字段对照", exact: true });
  await expect(drawer.getByRole("checkbox", { name: "设为空值", exact: true })).toBeChecked();
  await expect(drawer.getByRole("textbox", { name: "当前值", exact: true })).toBeDisabled();
  await drawer.getByRole("checkbox", { name: "设为空值", exact: true }).uncheck();
  await drawer.getByRole("textbox", { name: "当前值", exact: true }).fill("18.00");
  await drawer.getByRole("button", { name: "保存字段修改", exact: true }).click();
  await expect(drawer.getByText("当前草稿值", { exact: true }).locator("..")).toContainText("18.00");
  await drawer.getByRole("checkbox", { name: "设为空值", exact: true }).check();
  await drawer.getByRole("button", { name: "保存字段修改", exact: true }).click();
  await expect(drawer.getByRole("textbox", { name: "当前值", exact: true })).toHaveValue("");
  await openStory(page, "patterns-field-review--integer"); await prepareInteractiveStory(page, "patterns-field-review--integer");
  drawer = page.getByRole("dialog", { name: "字段对照", exact: true });
  await drawer.getByRole("textbox", { name: "当前值", exact: true }).fill("");
  await drawer.getByRole("button", { name: "保存字段修改", exact: true }).click();
  await expect(drawer.getByRole("alert")).toContainText("请输入有效整数");
  await drawer.getByRole("textbox", { name: "当前值", exact: true }).fill("8");
  await drawer.getByRole("button", { name: "保存字段修改", exact: true }).click();
  await expect(drawer.getByText("当前草稿值", { exact: true }).locator("..")).toContainText("8");
  for (const state of ["readonly", "empty-records", "long-text"]) {
    await openStory(page, `patterns-field-review--${state}`); await prepareInteractiveStory(page, `patterns-field-review--${state}`);
    if (state === "readonly") await expect(page.getByRole("button", { name: "保存字段修改", exact: true })).toHaveCount(0);
    if (state === "empty-records") await expect(page.getByText("当前字段暂无可恢复的历史或来源值。", { exact: true })).toBeVisible();
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
  }
  await openStory(page, "patterns-field-review--saving"); await prepareInteractiveStory(page, "patterns-field-review--saving");
  drawer = page.getByRole("dialog", { name: "字段对照", exact: true });
  await expect(drawer.getByRole("button", { name: "关闭字段对照", exact: true })).toBeDisabled();
  await page.keyboard.press("Escape"); await expect(drawer).toBeVisible();
  const content = drawer.getByRole("region", { name: "字段对照内容", exact: true }); await content.focus(); await expect(content).toBeFocused();
  const scroll = content.locator(".."); await scroll.evaluate(el => { el.scrollTop = 0; });
  await page.keyboard.press("PageDown"); await expect.poll(() => scroll.evaluate(el => el.scrollTop)).toBeGreaterThan(0);
});
