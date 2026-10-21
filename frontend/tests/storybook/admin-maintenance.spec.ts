import { expect, test } from "@playwright/test";
import { openStory } from "./storybookGateSupport";
import { VIEWPORTS } from "./storybookGateManifest";

for (const viewport of VIEWPORTS) {
  test(`maintenance refresh and keyboard diagnostics at ${viewport.width}px`, async ({ page }) => {
    await page.setViewportSize(viewport); const api: string[] = []; const errors: string[] = [];
    page.on("request", r => { if (new URL(r.url()).pathname.startsWith("/api/")) api.push(r.url()); }); page.on("pageerror", e => errors.push(e.message));
    await openStory(page, "pages-admin-maintenance--reference");
    await expect(page.getByRole("article", { name: "备份 501", exact: true })).toContainText("已恢复验证");
    const thresholds = page.getByText("心跳阈值参考", { exact: true }); await thresholds.focus(); await thresholds.press("Enter");
    await expect(page.getByText("写入间隔", { exact: false })).toBeVisible();
    const instance = page.locator(".worker-observability__instance").first(); const instanceToggle = instance.getByText("查看诊断", { exact: true });
    await instanceToggle.focus(); await instanceToggle.press("Enter"); await expect(instance.getByText("状态码", { exact: true })).toBeVisible();
    const queue = page.locator(".worker-observability__queue").first(); await queue.getByText("查看诊断", { exact: true }).click();
    await expect(queue.getByText("不适用", { exact: true }).first()).toBeVisible();
    const region = await queue.locator(".worker-observability__diagnostic").boundingBox(); expect(region!.x).toBeGreaterThanOrEqual(0); expect(region!.x + region!.width).toBeLessThanOrEqual(viewport.width);
    await page.getByRole("button", { name: "刷新状态", exact: true }).click(); await expect(instance.getByText("状态码", { exact: true })).toBeVisible();
    await expect(page.getByText(/页面最后刷新/)).toContainText("18:30:15");
    await page.reload(); await expect(page.getByRole("article", { name: "备份 501", exact: true })).toBeVisible();
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true); expect(api).toEqual([]); expect(errors).toEqual([]);
  });
}
test("maintenance recovery and distinct health/backup states", async ({ page }) => {
  await openStory(page, "pages-admin-maintenance--read-failure"); await expect(page.getByRole("alert")).toContainText("读取失败");
  await page.getByRole("button", { name: "重新读取维护状态", exact: true }).click(); await expect(page.getByRole("heading", { name: "Worker 运行状态", exact: true })).toBeVisible();
  await openStory(page, "pages-admin-maintenance--refresh-failure"); await expect(page.getByRole("alert")).toContainText("状态可能已过期");
  await page.getByRole("button", { name: "刷新状态", exact: true }).click(); await expect(page.getByRole("alert")).toHaveCount(0);
  await openStory(page, "pages-admin-maintenance--refreshing"); await expect(page.getByRole("button", { name: "刷新中…", exact: true })).toBeDisabled();
  await openStory(page, "pages-admin-maintenance--consumer-failure"); await expect(page.getByText("进程在线，catalog_import 消费者失败", { exact: true })).toBeVisible();
  await openStory(page, "pages-admin-maintenance--query-unknown"); await expect(page.getByText("Worker 状态无法确认", { exact: true })).toBeVisible();
  await openStory(page, "pages-admin-maintenance--heartbeat-delayed"); await expect(page.getByText("维护模式已开启", { exact: true })).toBeVisible(); await expect(page.getByText("持续持有，请核对", { exact: true })).toBeVisible();
  await openStory(page, "pages-admin-maintenance--backup-failure"); await expect(page.getByRole("article", { name: "备份 501", exact: true })).toContainText("尚未恢复演练"); await expect(page.getByRole("article", { name: "恢复验证 601", exact: true })).toContainText("demo_restore_failed");
  await openStory(page, "pages-admin-maintenance--empty"); await expect(page.getByRole("heading", { name: "尚无恢复验证记录", exact: true })).toBeVisible();
  await openStory(page, "pages-admin-maintenance--loading"); await expect(page.getByRole("status", { name: "正在载入维护与 Worker 状态", exact: true })).toBeVisible();
});
