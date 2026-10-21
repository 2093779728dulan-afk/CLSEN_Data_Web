import { expect, test } from "@playwright/test";
import { openStory } from "./storybookGateSupport";
import { VIEWPORTS } from "./storybookGateManifest";

for (const viewport of VIEWPORTS) {
  test(`admin accounts create, edit and keyboard flow at ${viewport.width}px`, async ({ page }) => {
    await page.setViewportSize(viewport);
    const errors: string[] = []; const api: string[] = [];
    page.on("pageerror", error => errors.push(error.message)); page.on("request", request => { if (new URL(request.url()).pathname.startsWith("/api/")) api.push(request.url()); });
    await openStory(page, "pages-admin-accounts--reference");
    await page.getByRole("button", { name: "新建账号", exact: true }).click();
    const create = page.getByRole("form", { name: "创建账号", exact: true });
    await expect(create.getByRole("button", { name: "创建账号", exact: true })).toBeDisabled();
    await create.getByRole("textbox", { name: "账号", exact: true }).fill("fictional-colleague");
    await create.getByRole("textbox", { name: "显示名", exact: true }).fill("虚构同事");
    await create.getByLabel(/^临时密码/).fill("Synthetic-only-123!");
    await create.getByRole("checkbox", { name: "查看人员", exact: true }).check();
    await create.getByRole("combobox", { name: "账号状态", exact: true }).selectOption("disabled");
    await create.getByRole("button", { name: "创建账号", exact: true }).click();
    await expect(page.getByRole("button", { name: "编辑 fictional-colleague", exact: true })).toBeVisible();
    await page.getByRole("button", { name: "收起创建表单", exact: true }).click();
    const opener = page.getByRole("button", { name: "编辑 fictional-colleague", exact: true });
    await opener.click(); const dialog = page.getByRole("dialog", { name: "编辑 @fictional-colleague", exact: true });
    await expect(dialog).toBeVisible();
    for (let index = 0; index < 12; index++) { await page.keyboard.press("Tab"); expect(await dialog.evaluate(element => element.contains(document.activeElement))).toBe(true); }
    await dialog.getByRole("textbox", { name: "显示名", exact: true }).fill("虚构修订显示名");
    await dialog.getByRole("checkbox", { name: "数据管理员", exact: true }).check();
    await dialog.getByRole("checkbox", { name: "查看人员", exact: true }).uncheck();
    await dialog.getByRole("button", { name: "保存账号修改", exact: true }).click();
    await expect(dialog).toHaveCount(0); await expect(opener).toBeFocused();
    await expect(page.getByText("虚构修订显示名", { exact: true })).toBeVisible();
    await opener.click(); await expect(dialog.getByRole("checkbox", { name: "数据管理员", exact: true })).toBeChecked(); await expect(dialog.getByLabel("新密码（留空则不修改）", { exact: true })).toHaveValue("");
    await page.keyboard.press("Escape"); await expect(dialog).toHaveCount(0); await expect(opener).toBeFocused();
    await page.getByRole("button", { name: "站点配置", exact: true }).click(); await expect(page.getByText("此批样板仅覆盖账号与角色", { exact: true })).toBeVisible();
    await page.getByRole("button", { name: "账号与角色", exact: true }).click(); await expect(opener).toBeVisible();
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true); expect(errors).toEqual([]); expect(api).toEqual([]);
  });
}
test("admin account failed reads retry and dialog failures keep edits visible", async ({ page }) => {
  await openStory(page, "pages-admin-accounts--read-failure"); await expect(page.getByRole("button", { name: "新建账号", exact: true })).toBeDisabled();
  await page.getByRole("button", { name: "重新载入管理资料", exact: true }).click(); await expect(page.getByRole("table", { name: "账号台账", exact: true })).toBeVisible();
  await openStory(page, "pages-admin-accounts--edit-failure"); let dialog = page.getByRole("dialog"); await expect(dialog.getByRole("alert")).toContainText("当前编辑内容已保留");
  await dialog.getByRole("textbox", { name: "显示名", exact: true }).fill("虚构重试结果"); await dialog.getByRole("button", { name: "保存账号修改", exact: true }).click(); await expect(page.getByText("虚构重试结果", { exact: true })).toBeVisible();
  await openStory(page, "pages-admin-accounts--last-admin-protected"); dialog = page.getByRole("dialog");
  await dialog.getByRole("checkbox", { name: "管理员", exact: true }).uncheck(); await dialog.getByRole("checkbox", { name: "查看人员", exact: true }).check();
  await dialog.getByRole("button", { name: "保存账号修改", exact: true }).click(); await expect(dialog.getByRole("alert")).toContainText("最后一个启用的管理员"); await expect(dialog).toBeVisible();
});
