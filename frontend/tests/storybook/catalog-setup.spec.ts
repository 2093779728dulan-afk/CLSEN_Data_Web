import { expect, test } from "@playwright/test";
import { openStory } from "./storybookGateSupport";

for (const width of [1280, 390]) {
  test(`setup reference completes source confirmation, preview and snapshot at ${width}px`, async ({ page }) => {
    await page.setViewportSize({ width, height: 900 });
    const api: string[] = [];
    await page.route(url => url.pathname.startsWith("/api/"), route => { api.push(route.request().url()); return route.abort(); });
    await openStory(page, "pages-catalog-setup--reference");
    const confirm = page.getByRole("button", { name: "确认来源范围", exact: true });
    await expect(confirm).toBeDisabled();
    await page.getByRole("textbox", { name: "来源账号标识", exact: true }).fill("DEMO-US");
    await page.getByRole("textbox", { name: "账号显示名称", exact: true }).fill("虚构美国账号");
    await page.getByRole("textbox", { name: "确认依据", exact: true }).fill("虚构报表说明");
    await page.getByRole("checkbox").focus(); await page.keyboard.press("Space");
    await confirm.click();
    await expect(page.getByText("账号来源范围：已确认（虚构美国账号）", { exact: true })).toBeVisible();
    await expect(page.getByRole("textbox", { name: "来源账号标识", exact: true })).toHaveCount(0);
    await page.getByRole("button", { name: "准备首次退货快照", exact: true }).click();
    await expect(page.getByRole("region", { name: "首次快照预览", exact: true })).toContainText("37 份退货报告");
    await page.getByRole("button", { name: "确认建立首次快照", exact: true }).click();
    await expect(page.getByText(/首次退货快照已建立/)).toBeVisible();
    await expect(page.getByText("商品主档：待生成候选、审核并批准", { exact: true })).toBeVisible();
    await page.getByRole("button", { name: "刷新准备状态", exact: true }).click();
    await expect(page.getByText("退货去重快照：已建立，读取分析时仍会校验是否匹配最新报表", { exact: true })).toBeVisible();
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
    expect(api).toEqual([]);
  });
}

test("setup missing reports, readonly, progress and recovery states remain explicit", async ({ page }) => {
  await openStory(page, "pages-catalog-setup--missing-reports");
  await expect(page.getByRole("button", { name: "准备首次退货快照", exact: true })).toBeDisabled();
  await expect(page.getByText("尚无已发布退货报告", { exact: true })).toBeVisible();
  await openStory(page, "pages-catalog-setup--read-only");
  await expect(page.getByRole("button", { name: "准备首次退货快照", exact: true })).toHaveCount(0);
  await expect(page.getByRole("link", { name: "查看商品主档与初始化说明", exact: true })).toHaveAttribute("href", "/catalog");
  for (const state of ["source-submitting", "initializing"]) {
    await openStory(page, `pages-catalog-setup--${state}`);
    await expect(page.getByRole("button", { name: "刷新准备状态", exact: true })).toBeDisabled();
  }
  await openStory(page, "pages-catalog-setup--loading");
  await expect(page.getByRole("status", { name: "正在读取初始化状态", exact: true })).toBeVisible();
  await openStory(page, "pages-catalog-setup--read-failure");
  await expect(page.getByRole("alert")).toContainText("无法读取初始化状态");
  await page.getByRole("button", { name: "刷新核对状态", exact: true }).click();
  await expect(page.getByRole("textbox", { name: "来源账号标识", exact: true })).toBeVisible();
  await openStory(page, "pages-catalog-setup--source-failure");
  await expect(page.getByRole("textbox", { name: "来源账号标识", exact: true })).toHaveValue("DEMO-SCOPE-US");
  await page.getByRole("button", { name: "确认来源范围", exact: true }).click();
  await expect(page.getByText("账号来源范围：已确认（示例美国账号）", { exact: true })).toBeVisible();
  await openStory(page, "pages-catalog-setup--initialization-failure");
  await expect(page.getByRole("alert")).toContainText("首次快照尚未完成");
  await page.getByRole("button", { name: "确认建立首次快照", exact: true }).click();
  await expect(page.getByText(/首次退货快照已建立/)).toBeVisible();
  await openStory(page, "pages-catalog-setup--ready");
  await expect(page.getByText("基础资料已建立", { exact: true })).toBeVisible();
  await expect(page.getByRole("button", { name: "确认来源范围", exact: true })).toHaveCount(0);
  await expect(page.getByRole("button", { name: "准备首次退货快照", exact: true })).toHaveCount(0);
});

test("setup mobile error actions stay horizontal and refresh recovers each state", async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 900 });
  for (const state of ["source-failure", "initialization-failure", "read-failure"]) {
    await openStory(page, `pages-catalog-setup--${state}`);
    const alert = page.getByRole("alert");
    const action = alert.getByRole("button", { name: "刷新核对状态", exact: true });
    await expect(action).toBeVisible();
    const bounds = await action.boundingBox();
    expect(bounds!.width).toBeGreaterThan(100);
    expect(bounds!.height).toBeLessThan(60);
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
    await action.focus();
    await page.keyboard.press("Enter");
    await expect(alert).toHaveCount(0);
    await expect(page.getByRole("button", { name: "刷新准备状态", exact: true })).toBeEnabled();
  }
});
