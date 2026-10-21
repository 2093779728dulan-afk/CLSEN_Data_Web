import { expect, test } from "@playwright/test";
import { openStory } from "./storybookGateSupport";
import { VIEWPORTS } from "./storybookGateManifest";

for (const viewport of VIEWPORTS) {
  test(`site configuration creates a version and retains history at ${viewport.width}px`, async ({ page }) => {
    await page.setViewportSize(viewport);
    const api: string[] = []; const errors: string[] = [];
    page.on("request", request => { if (new URL(request.url()).pathname.startsWith("/api/")) api.push(request.url()); });
    page.on("pageerror", error => errors.push(error.message));
    await openStory(page, "pages-admin-site-configuration--reference");
    await expect(page.getByRole("table", { name: "站点配置版本历史", exact: true })).toBeVisible();
    await page.getByRole("button", { name: "新建配置版本", exact: true }).click();
    const form = page.getByRole("form", { name: "创建站点配置版本", exact: true });
    await expect(form.getByRole("spinbutton", { name: "站点 ID", exact: true })).toHaveValue("71");
    await form.getByRole("textbox", { name: "变更原因", exact: true }).fill("示例：统一统计时区");
    await form.getByRole("button", { name: "取消", exact: true }).click();
    await expect(form).toHaveCount(0); await expect(page.getByRole("table").getByRole("row")).toHaveCount(3);
    await page.getByRole("button", { name: "新建配置版本", exact: true }).click();
    await form.getByRole("textbox", { name: "统计时区", exact: true }).fill("UTC");
    await form.getByRole("textbox", { name: "币种", exact: true }).fill("usd");
    await form.getByRole("textbox", { name: "变更原因", exact: true }).fill("示例：统一统计时区");
    await form.getByRole("button", { name: "创建配置版本", exact: true }).click();
    await expect(form).toHaveCount(0); await expect(page.getByText("示例配置 v3 已创建，仅更新样板内存。", { exact: true })).toBeVisible();
    const history = page.getByRole("table", { name: "站点配置版本历史", exact: true }); await expect(history.getByRole("row")).toHaveCount(4);
    await expect(history.getByText("当前版本", { exact: true })).toHaveCount(1); await expect(history.getByText("历史版本", { exact: true })).toHaveCount(2);
    await expect(history.getByRole("cell", { name: "示例：统一统计时区", exact: true })).toBeVisible();
    await page.getByRole("button", { name: "账号与角色", exact: true }).click(); await expect(page.getByText("此批样板仅覆盖站点配置与版本历史", { exact: true })).toBeVisible();
    await page.getByRole("button", { name: "站点配置", exact: true }).click(); await expect(history.getByRole("row")).toHaveCount(4);
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true); expect(api).toEqual([]); expect(errors).toEqual([]);
  });
}

test("site configuration read/create failures recover and pending inputs stay disabled", async ({ page }) => {
  await openStory(page, "pages-admin-site-configuration--read-failure"); await expect(page.getByRole("button", { name: "新建配置版本", exact: true })).toBeDisabled();
  await page.getByRole("button", { name: "重新载入管理资料", exact: true }).click(); await expect(page.getByRole("table", { name: "站点配置版本历史", exact: true })).toBeVisible();
  await openStory(page, "pages-admin-site-configuration--create-failure"); const form = page.getByRole("form", { name: "创建站点配置版本", exact: true });
  await expect(page.getByRole("alert")).toContainText("已保留本次表单内容"); await expect(form.getByRole("textbox", { name: "变更原因", exact: true })).toHaveValue("示例：调整统计时区");
  await form.getByRole("button", { name: "创建配置版本", exact: true }).click(); await expect(page.getByText("示例配置 v3 已创建，仅更新样板内存。", { exact: true })).toBeVisible();
  await openStory(page, "pages-admin-site-configuration--creating"); await expect(form.getByRole("textbox", { name: "统计时区", exact: true })).toBeDisabled(); await expect(form.getByRole("button", { name: "正在创建配置版本…", exact: true })).toBeDisabled();
  await openStory(page, "pages-admin-site-configuration--multi-site"); const history = page.getByRole("table"); await expect(history.getByText("当前版本", { exact: true })).toHaveCount(2); await expect(history.getByText("示例日本站点 · v1", { exact: true })).toBeVisible();
});
