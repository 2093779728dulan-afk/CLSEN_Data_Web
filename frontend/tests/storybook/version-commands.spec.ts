import { expect, test } from "@playwright/test";
import { openStory } from "./storybookGateSupport";

for (const width of [1280, 768, 390]) {
  test(`version command dialog interactions at ${width}px`, async ({ page }) => {
    await page.setViewportSize({ width, height: 900 });
    await openStory(page, "pages-version-commands--revision");
    let dialog = page.getByRole("dialog", { name: "创建发布修订", exact: true });
    await expect(dialog.getByRole("button", { name: "确认创建修订", exact: true })).toBeDisabled();
    await dialog.getByRole("textbox", { name: "修订原因" }).fill("虚构复核原因");
    await expect(dialog.getByRole("button", { name: "确认创建修订", exact: true })).toBeEnabled();
    await page.keyboard.press("Escape"); await expect(dialog).toHaveCount(0);
    const opener = page.getByRole("button", { name: "重新打开确认", exact: true });
    await opener.click(); await expect(dialog.getByRole("textbox", { name: "修订原因" })).toHaveValue("虚构复核原因");
    for (let i = 0; i < 9; i++) { await page.keyboard.press("Tab"); expect(await dialog.evaluate(el => el.contains(document.activeElement))).toBe(true); }
    await page.keyboard.press("Escape"); await expect(opener).toBeFocused();
    await opener.click(); await expect(dialog).toBeVisible();
    if (width > 600) await page.locator('[data-state="open"][class*="overlay"]').click({ position: { x: 2, y: 2 } });
    else await dialog.getByRole("button", { name: "关闭创建发布修订", exact: true }).click();
    await expect(dialog).toHaveCount(0); await expect(opener).toBeFocused();
    await openStory(page, "pages-version-commands--move");
    dialog = page.getByRole("dialog", { name: "已发布数据跨日期移动", exact: true });
    await dialog.getByLabel("目标报告日", { exact: true }).fill("2026-09-13");
    await dialog.getByRole("button", { name: "检查目标日期", exact: true }).click();
    await expect(dialog.getByText("目标日期尚无数据", { exact: true })).toBeVisible();
    await dialog.getByRole("textbox", { name: "移动原因" }).fill("日期归属复核");
    await dialog.getByRole("button", { name: "创建跨日期审核草稿", exact: true }).click();
    await expect(page.getByText("样板已接收本次确认；未发送实际写入命令。", { exact: true })).toBeVisible();
    await openStory(page, "pages-version-commands--move-draft");
    dialog = page.getByRole("dialog", { name: "已发布数据跨日期移动", exact: true });
    await dialog.getByRole("textbox", { name: "移动原因" }).fill("强制重建复核");
    const force = dialog.getByRole("button", { name: "强制重建跨日期草稿", exact: true });
    await expect(force).toBeDisabled();
    await dialog.getByRole("checkbox").check(); await expect(force).toBeEnabled();
    await dialog.getByRole("radio", { name: "合并到活动草稿", exact: true }).check();
    await expect(dialog.getByRole("button", { name: "创建跨日期审核草稿", exact: true })).toBeDisabled();
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
    const box = await dialog.boundingBox(); expect(box!.x).toBeGreaterThanOrEqual(0); expect(box!.x + box!.width).toBeLessThanOrEqual(width);
    await openStory(page, "pages-version-commands--undo");
    dialog = page.getByRole("dialog", { name: "撤销跨日期移动确认", exact: true });
    await dialog.getByRole("textbox", { name: "撤销原因" }).fill("核对两侧恢复");
    await dialog.getByRole("button", { name: "确认撤销跨日期移动", exact: true }).click();
    await expect(dialog).toHaveCount(0);
    await openStory(page, "pages-version-commands--rollback-failure");
    dialog = page.getByRole("dialog", { name: "管理员回滚确认", exact: true });
    await expect(dialog.getByRole("alert")).toContainText("发布状态已变化");
    await expect(dialog.getByRole("textbox", { name: "回滚原因" })).toHaveValue("虚构原因：复核报告归属日期");
    await dialog.getByRole("button", { name: "确认回滚到 v1", exact: true }).click();
    await expect(dialog).toHaveCount(0);
  });
}

test("pending commands cannot dismiss and blocked target cannot submit", async ({ page }) => {
  await openStory(page, "pages-version-commands--revision-submitting");
  const dialog = page.getByRole("dialog", { name: "创建发布修订", exact: true });
  await expect(dialog.getByRole("textbox")).toBeDisabled();
  await expect(dialog.getByRole("button", { name: "关闭创建发布修订", exact: true })).toBeDisabled();
  await page.keyboard.press("Escape"); await expect(dialog).toBeVisible();
  await page.mouse.click(2, 2); await expect(dialog).toBeVisible();
  await openStory(page, "pages-version-commands--move-blocked");
  await expect(page.getByRole("dialog").getByRole("button", { name: /创建跨日期审核草稿|强制重建/ })).toHaveCount(0);
});
