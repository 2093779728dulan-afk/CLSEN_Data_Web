import { expect, test } from "@playwright/test";
import { openStory, prepareInteractiveStory } from "./storybookGateSupport";

for (const width of [1280, 768, 390]) {
  test(`publication confirmation retains reason, guards empty input and returns focus at ${width}px`, async ({ page }) => {
    await page.setViewportSize({ width, height: 900 });
    await openStory(page, "patterns-publication-confirmation--no-operator");
    let dialog = page.getByRole("dialog", { name: "发布确认", exact: true });
    const reason = dialog.getByRole("textbox", { name: "发布说明", exact: true });
    await expect(reason).toHaveValue("");
    await expect(dialog.getByRole("button", { name: "确认发布", exact: true })).toBeDisabled();
    await reason.fill("  ");
    await expect(dialog.getByRole("button", { name: "确认发布", exact: true })).toBeDisabled();
    await reason.fill("已核对虚构日期、行数与合计");
    await expect(dialog.getByRole("button", { name: "确认发布", exact: true })).toBeEnabled();
    await expect(dialog).toContainText("版本 ID #51");
    await dialog.getByRole("button", { name: "返回审核", exact: true }).last().click();
    await expect(dialog).toHaveCount(0);
    const reopen = page.getByRole("button", { name: "重新打开发布确认", exact: true });
    await reopen.click(); dialog = page.getByRole("dialog", { name: "发布确认", exact: true });
    await expect(dialog.getByRole("button", { name: "返回审核", exact: true }).first()).toBeFocused(); await page.keyboard.press("Tab"); await expect(dialog.getByRole("textbox", { name: "发布说明", exact: true })).toBeFocused();
    await page.keyboard.press("Shift+Tab"); await expect(dialog.getByRole("button", { name: "返回审核", exact: true }).first()).toBeFocused();
    await page.keyboard.press("Escape"); await expect(dialog).toHaveCount(0); await expect(reopen).toBeFocused();
    await reopen.click(); await page.getByRole("dialog").getByRole("textbox", { name: "发布说明", exact: true }).fill("虚构发布核对");
    await page.getByRole("button", { name: "确认发布", exact: true }).click();
    await expect(page.getByText("样板确认完成", { exact: true })).toBeVisible();
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
    await openStory(page, "patterns-publication-confirmation--failure");
    dialog = page.getByRole("dialog", { name: "发布确认", exact: true });
    await dialog.getByRole("textbox", { name: "发布说明", exact: true }).fill("失败后保留的发布说明");
    await dialog.getByRole("button", { name: "确认发布", exact: true }).click();
    await expect(dialog.getByRole("alert")).toContainText("说明已保留");
    await expect(dialog.getByRole("textbox", { name: "发布说明", exact: true })).toHaveValue("失败后保留的发布说明");
    await dialog.getByRole("button", { name: "确认发布", exact: true }).click();
    await expect(page.getByText("样板确认完成", { exact: true })).toBeVisible();
  });
}

test("publication progress, warnings and cross-date scope use the actual dialog", async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 900 });
  for (const [id, text] of [["return-building", "正在准备退货快照"], ["return-retrying", "快照准备未成功"], ["return-ready", "退货快照已准备"], ["return-superseded", "发布集合已变化"], ["submitting", "本次校验回执"]] as const) {
    await openStory(page, `patterns-publication-confirmation--${id}`);
    await prepareInteractiveStory(page, `patterns-publication-confirmation--${id}`);
    const dialog = page.getByRole("dialog", { name: "发布确认", exact: true });
    await expect(dialog).toContainText(text);
    await expect(dialog.getByRole("textbox", { name: "发布说明", exact: true })).toBeDisabled();
    const content = dialog.getByRole("region", { name: "发布确认内容", exact: true });
    await content.focus(); await expect(content).toBeFocused();
    const scroller = content.locator("..");
    if (await scroller.evaluate(el => el.scrollHeight > el.clientHeight)) {
      await scroller.evaluate(el => { el.scrollTop = 0; });
      await page.keyboard.press("PageDown");
      await expect.poll(() => scroller.evaluate(el => el.scrollTop)).toBeGreaterThan(0);
    }
    await expect(dialog.getByRole("button", { name: "返回审核", exact: true }).first()).toBeDisabled();
    await page.keyboard.press("Escape"); await expect(dialog).toBeVisible();
    await page.mouse.click(2, 2); await expect(dialog).toBeVisible();
  }
  await openStory(page, "patterns-publication-confirmation--warnings");
  await expect(page.getByRole("dialog")).toContainText("包含 2 项警告");
  await openStory(page, "patterns-publication-confirmation--cross-date");
  const dialog = page.getByRole("dialog", { name: "跨日期生效确认", exact: true });
  await expect(dialog.getByRole("region", { name: "跨日期生效范围", exact: true })).toContainText("2026-08-09");
  await expect(dialog.getByRole("region", { name: "跨日期生效范围", exact: true })).toContainText("2026-08-10");
  await expect(dialog.getByRole("button", { name: "确认跨日期生效", exact: true })).toBeEnabled();
  await dialog.getByRole("button", { name: "确认跨日期生效", exact: true }).click();
  await expect(page.getByText("样板确认完成", { exact: true })).toBeVisible();
});
