import { expect, test } from "@playwright/test";
import { openStory, prepareInteractiveStory } from "./storybookGateSupport";
for (const width of [1280, 390]) {
  test(`note revision edits visibility, saves and restores focus; failures retain input at ${width}px`, async ({ page }) => {
    await page.setViewportSize({ width, height: 900 }); const errors: string[] = []; page.on("pageerror", error => errors.push(error.message));
    await openStory(page, "patterns-note-revision--reference");
    const trigger = page.getByRole("button", { name: "修订备注", exact: true }); await trigger.click();
    const form = page.getByRole("form", { name: "备注修订 fictional-note-1", exact: true });
    await expect(form.getByRole("textbox")).toBeFocused();
    await form.getByRole("textbox").fill("虚构新修订");
    await form.getByRole("combobox").selectOption("viewer_visible");
    await form.getByRole("button", { name: "取消修订", exact: true }).click(); await expect(trigger).toBeFocused();
    await page.keyboard.press("Enter"); await expect(form.getByRole("textbox")).toHaveValue("虚构新修订");
    await form.getByRole("button", { name: "保存新修订", exact: true }).click(); await expect(trigger).toBeFocused();
    await expect(page.getByText("虚构新修订", { exact: true })).toBeVisible(); await expect(page.getByRole("article")).toContainText("第 2 版 · 查看人员可见");
    await trigger.click(); await expect(form.getByRole("textbox")).toHaveValue("虚构新修订"); await expect(form.getByRole("combobox")).toHaveValue("viewer_visible");
    await openStory(page, "patterns-note-revision--save-failure"); await prepareInteractiveStory(page, "patterns-note-revision--save-failure");
    await expect(form.getByRole("textbox")).toHaveValue("虚构新修订依据");
    await form.getByRole("button", { name: "保存新修订", exact: true }).click(); await expect(trigger).toBeFocused();
    await expect(page.getByText("虚构新修订依据", { exact: true })).toBeVisible(); expect(errors).toEqual([]);
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
  });
}
test("batch notes remain internal; empty and pending states prevent saves", async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 });
  await openStory(page, "patterns-note-revision--batch"); await prepareInteractiveStory(page, "patterns-note-revision--batch");
  await expect(page.getByRole("combobox")).toHaveCount(0);
  await expect(page.getByText("批次备注仅审核人员可见，不进入已发布版本的查看页面。", { exact: true })).toBeVisible();
  await openStory(page, "patterns-note-revision--empty"); await prepareInteractiveStory(page, "patterns-note-revision--empty");
  await expect(page.getByRole("button", { name: "保存新修订", exact: true })).toBeDisabled();
  await openStory(page, "patterns-note-revision--saving"); await prepareInteractiveStory(page, "patterns-note-revision--saving");
  await expect(page.getByRole("textbox")).toBeDisabled(); await expect(page.getByRole("combobox")).toBeDisabled();
  await expect(page.getByRole("button", { name: "取消修订", exact: true })).toBeDisabled();
  await expect(page.getByRole("button", { name: "正在保存新修订", exact: true })).toBeDisabled();
});
