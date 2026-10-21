import { expect, test } from "@playwright/test";
import { VIEWPORTS } from "./storybookGateManifest";
import { openStory } from "./storybookGateSupport";

for (const viewport of VIEWPORTS) test(`session form keyboard, password visibility and initialization at ${viewport.width}px`, async ({ page }) => {
  await page.setViewportSize(viewport); const api: string[] = []; const errors: string[] = []; page.on("request", r => { if (new URL(r.url()).pathname.startsWith("/api/")) api.push(r.url()); }); page.on("pageerror", e => errors.push(e.message));
  await openStory(page, "pages-session-entry--reference");
  await page.getByRole("button", { name: "登录工作台", exact: true }).click(); await expect(page.getByRole("textbox", { name: "账号", exact: true })).toBeFocused();
  await page.getByRole("textbox", { name: "账号", exact: true }).fill("fictional-user"); const password = page.locator("#login-password"); await password.fill("fictional-only-password"); await expect(password).toHaveAttribute("type", "password");
  const toggle = page.getByRole("button", { name: "显示密码", exact: true }); await toggle.focus(); await toggle.press("Enter"); await expect(password).toHaveAttribute("type", "text"); await expect(page.getByRole("button", { name: "隐藏密码", exact: true })).toHaveAttribute("aria-pressed", "true");
  await page.getByRole("button", { name: "隐藏密码", exact: true }).press("Enter"); await password.focus(); await password.press("Enter");
  await expect(page.getByRole("status", { name: "正在读取当前站点配置…", exact: true })).toBeVisible();
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true); expect(api).toEqual([]); expect(errors).toEqual([]);
});
test("session failure, pending lock, loading and site retry states", async ({ page }) => {
  await openStory(page, "pages-session-entry--login-failure"); await expect(page.getByRole("alert")).toContainText("核对后重试"); await expect(page.getByRole("textbox", { name: "账号", exact: true })).toHaveValue("demo-reviewer");
  await openStory(page, "pages-session-entry--submitting"); await expect(page.getByRole("textbox", { name: "账号", exact: true })).toBeDisabled(); await expect(page.locator("#login-password")).toBeDisabled(); await expect(page.getByRole("button", { name: "显示密码", exact: true })).toBeDisabled(); await expect(page.getByRole("button", { name: "正在登录…", exact: true })).toBeDisabled();
  await openStory(page, "pages-session-entry--checking"); await expect(page.getByRole("status", { name: "正在连接数据核验台…", exact: true })).toBeVisible();
  await openStory(page, "pages-session-entry--site-failure"); await expect(page.getByRole("alert")).toContainText("示例站点配置读取失败"); await page.getByRole("button", { name: "重新读取站点配置", exact: true }).click(); await expect(page.getByRole("status", { name: "正在读取当前站点配置…", exact: true })).toBeVisible();
});
