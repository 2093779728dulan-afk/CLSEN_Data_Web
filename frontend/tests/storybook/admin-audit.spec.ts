import { expect, test } from "@playwright/test";
import { openStory } from "./storybookGateSupport";
import { VIEWPORTS } from "./storybookGateManifest";

for (const viewport of VIEWPORTS) {
  test(`audit filters, paginates and expands evidence at ${viewport.width}px`, async ({ page }) => {
    await page.setViewportSize(viewport); const requests: string[] = []; const errors: string[] = [];
    page.on("request", r => { if (new URL(r.url()).pathname.startsWith("/api/")) requests.push(r.url()); });
    page.on("pageerror", e => errors.push(e.message));
    await openStory(page, "pages-admin-audit--reference");
    await expect(page.getByRole("article")).toHaveCount(20);
    await page.getByRole("button", { name: "下一页", exact: true }).click();
    await expect(page.getByRole("article")).toHaveCount(3); await expect(page.getByRole("button", { name: "下一页", exact: true })).toBeDisabled();
    await page.getByRole("button", { name: "上一页", exact: true }).click();
    const event = page.getByRole("article", { name: "审计事件 900", exact: true });
    const summary = event.getByText("查看脱敏详情", { exact: true }); await summary.focus(); await summary.press("Enter");
    await expect(event.locator("pre")).toContainText('"roles"'); await summary.press("Enter"); await expect(event.locator("pre")).toBeHidden();
    await page.getByRole("textbox", { name: "事件类型", exact: true }).fill("admin.user_updated");
    await page.getByRole("button", { name: "应用筛选", exact: true }).click(); await expect(page.getByRole("article")).toHaveCount(12);
    await page.getByRole("textbox", { name: "事件类型", exact: true }).fill("no.match"); await page.getByRole("button", { name: "应用筛选", exact: true }).click();
    await expect(page.getByRole("heading", { name: "当前筛选条件下没有审计记录", exact: true })).toBeVisible();
    await page.getByRole("textbox", { name: "事件类型", exact: true }).fill(""); await page.getByRole("button", { name: "应用筛选", exact: true }).click();
    await expect(page.getByRole("article")).toHaveCount(20); await page.reload(); await expect(page.getByRole("article")).toHaveCount(20);
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true); expect(requests).toEqual([]); expect(errors).toEqual([]);
  });
}
test("audit failures recover and loading/busy/permission states are truthful", async ({ page }) => {
  await openStory(page, "pages-admin-audit--read-failure"); await expect(page.getByRole("button", { name: "应用筛选", exact: true })).toBeDisabled();
  await page.getByRole("button", { name: "重新载入管理资料", exact: true }).click(); await expect(page.getByRole("article")).toHaveCount(20);
  await openStory(page, "pages-admin-audit--filter-failure"); await expect(page.getByRole("alert")).toContainText("上次读取");
  await page.getByRole("button", { name: "应用筛选", exact: true }).click(); await expect(page.getByRole("alert")).toHaveCount(0);
  await openStory(page, "pages-admin-audit--busy"); await expect(page.getByRole("textbox", { name: "事件类型", exact: true })).toBeDisabled(); await expect(page.getByRole("button", { name: "下一页", exact: true })).toBeDisabled();
  await openStory(page, "pages-admin-audit--loading"); await expect(page.getByRole("status", { name: "正在读取审计记录", exact: true })).toBeVisible();
  await openStory(page, "pages-admin-audit--access-denied"); await expect(page.getByRole("heading", { name: "管理员权限边界", exact: true })).toBeVisible();
});
