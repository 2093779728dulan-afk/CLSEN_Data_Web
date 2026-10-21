import { expect, test } from "@playwright/test";
import { openStory } from "./storybookGateSupport";

test("desktop navigation names, collapse and role-specific entries", async ({ page }) => {
  const api: string[] = []; page.on("request", r => { if (new URL(r.url()).pathname.startsWith("/api/")) api.push(r.url()); });
  await page.setViewportSize({ width: 1280, height: 900 });
  await openStory(page, "pages-workspace-shell--reference");
  const nav = page.getByRole("navigation", { name: "工作区", exact: true });
  await expect(nav.getByRole("link", { name: "产品分析", exact: true })).toHaveAttribute("aria-current", "page");
  await page.getByRole("button", { name: "收起侧栏", exact: true }).click();
  await expect(page.locator(".app-shell")).toHaveAttribute("data-sidebar-collapsed", "true");
  await expect(nav.getByRole("link", { name: "管理员控制台", exact: true })).toBeVisible();
  await nav.getByRole("link", { name: "版本记录", exact: true }).click();
  await expect(page.getByRole("heading", { name: "版本记录", exact: true })).toBeVisible();
  await expect(nav.getByRole("link", { name: "版本记录", exact: true })).toHaveAttribute("aria-current", "page");
  for (const [story, review, admin, role] of [["manager", 1, 0, "数据管理员"], ["viewer", 0, 0, "查看人员"]] as const) {
    await openStory(page, `pages-workspace-shell--${story}`);
    await expect(nav.getByRole("link", { name: "数据审核", exact: true })).toHaveCount(review);
    await expect(nav.getByRole("link", { name: "管理员控制台", exact: true })).toHaveCount(admin);
    await expect(page.getByText(role, { exact: true })).toBeVisible();
  }
  expect(api).toEqual([]);
});

for (const width of [768, 390]) test(`drawer focus, Escape, outside, route and resize at ${width}px`, async ({ page }) => {
  await page.setViewportSize({ width, height: 844 });
  await openStory(page, "pages-workspace-shell--reference");
  const trigger = page.getByRole("button", { name: "打开主导航", exact: true });
  await trigger.focus(); await trigger.press("Enter");
  const dialog = page.getByRole("dialog", { name: "工作区导航", exact: true });
  await expect(dialog).toBeVisible();
  for (let i = 0; i < 12; i++) { await page.keyboard.press("Tab"); expect(await dialog.evaluate(el => el.contains(document.activeElement))).toBe(true); }
  await page.keyboard.press("Shift+Tab"); expect(await dialog.evaluate(el => el.contains(document.activeElement))).toBe(true);
  await page.keyboard.press("Escape"); await expect(dialog).toBeHidden(); await expect(trigger).toBeFocused();
  await trigger.click();
  await dialog.getByRole("link", { name: "版本记录", exact: true }).click();
  await expect(dialog).toBeHidden(); await expect(page.getByRole("heading", { name: "版本记录", exact: true })).toBeVisible(); await expect(trigger).toBeFocused();
  await trigger.click(); await dialog.getByRole("link", { name: "版本记录", exact: true }).click(); await expect(dialog).toBeHidden();
  if (width === 768) {
    await trigger.click(); await page.mouse.click(10, 500); await expect(dialog).toBeHidden(); await expect(trigger).toBeFocused();
  }
  await trigger.click(); await page.setViewportSize({ width: 1280, height: 900 });
  await expect(dialog).toBeHidden(); await expect(page.getByRole("navigation", { name: "工作区", exact: true })).toBeVisible();
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
});

test("offline, disabled logout and in-drawer failure recovery", async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 });
  await openStory(page, "pages-workspace-shell--offline"); await expect(page.getByText("连接不可用", { exact: true })).toBeVisible();
  await openStory(page, "pages-workspace-shell--logout-busy"); await page.getByRole("button", { name: "打开主导航", exact: true }).click();
  await expect(page.getByRole("dialog").getByRole("button", { name: "退出中", exact: true })).toBeDisabled();
  await openStory(page, "pages-workspace-shell--navigation-failure"); await page.getByRole("button", { name: "打开主导航", exact: true }).click();
  await expect(page.getByRole("dialog").getByRole("alert")).toContainText("当前会话仍保留");
  await page.getByRole("dialog").getByRole("button", { name: "重试退出", exact: true }).click();
  await expect(page.getByText("已退出示例会话", { exact: true })).toBeVisible();
});

test("drawer uses existing motion tokens and respects reduced motion", async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 }); await openStory(page, "pages-workspace-shell--reference");
  await page.emulateMedia({ reducedMotion: "no-preference" }); await page.getByRole("button", { name: "打开主导航", exact: true }).click();
  const dialog = page.getByRole("dialog"); await expect(dialog).toBeVisible();
  expect(await dialog.evaluate(el => getComputedStyle(el).animationDuration)).toBe("0.2s");
  await page.keyboard.press("Escape"); await expect(dialog).toBeHidden();
  await page.emulateMedia({ reducedMotion: "reduce" }); await page.getByRole("button", { name: "打开主导航", exact: true }).click();
  expect(await dialog.evaluate(el => getComputedStyle(el).animationName)).toBe("none");
});
