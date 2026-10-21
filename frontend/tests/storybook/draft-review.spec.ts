import { expect, test } from "@playwright/test";
import { openStory } from "./storybookGateSupport";

for (const width of [1280, 768, 390]) {
  test(`draft review validates, confirms, cancels publication and maintenance at ${width}px`, async ({ page }) => {
    await page.setViewportSize({ width, height: 900 });
    await openStory(page, "pages-draft-review--reference");
    await page.getByRole("button", { name: "运行草稿校验", exact: true }).click();
    const reason = page.getByRole("textbox", { name: "审核确认说明", exact: true });
    await reason.fill("");
    await expect(page.getByRole("button", { name: "确认结果并标记待发布", exact: true })).toBeDisabled();
    await reason.fill("已核对虚构源表与合计");
    await page.getByRole("button", { name: "确认结果并标记待发布", exact: true }).click();
    const trigger = page.getByRole("button", { name: "打开发布确认", exact: true });
    await trigger.click();
    const dialog = page.getByRole("dialog", { name: "发布确认", exact: true });
    await expect(dialog).toBeVisible();
    await dialog.getByRole("button", { name: "返回审核", exact: true }).last().click();
    await expect(dialog).toHaveCount(0);
    await expect(trigger).toBeFocused();
    await page.getByText("调整草稿日期", { exact: true }).click();
    await page.getByLabel("目标报告日", { exact: true }).fill("2026-08-11");
    await page.getByRole("button", { name: "检查目标日期", exact: true }).click();
    await page.getByRole("radio", { name: "取消，保留当前所属日期", exact: true }).check();
    await page.getByRole("button", { name: "确认取消", exact: true }).click();
    await expect(page.getByText("已取消，所属日期保留。", { exact: true })).toBeVisible();
    await page.getByText("重新解析或废弃草稿", { exact: true }).click();
    const discard = page.getByRole("button", { name: "只废弃当前草稿", exact: true });
    await expect(discard).toBeDisabled();
    await page.getByRole("checkbox", { name: "我确认当前草稿将被废弃，历史记录不会删除。", exact: true }).check();
    await expect(discard).toBeEnabled();
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
  });
}

test("draft read retry, blocking, warning and administrator gates remain explicit", async ({ page }) => {
  await openStory(page, "pages-draft-review--read-failure");
  await expect(page.getByRole("heading", { name: "无法读取草稿", exact: true })).toBeVisible();
  await page.getByRole("button", { name: "重新读取草稿", exact: true }).click();
  await expect(page.getByRole("heading", { name: "无法读取草稿", exact: true })).toHaveCount(0);
  await expect(page.getByRole("button", { name: "运行草稿校验", exact: true })).toBeVisible();
  for (const scenario of ["blocking", "warning", "admin-required"]) {
    await openStory(page, `pages-draft-review--${scenario}`);
    await expect(page.getByRole("button", { name: "确认结果并标记待发布", exact: true })).toHaveCount(0);
    await expect(page.getByRole("button", { name: "打开发布确认", exact: true })).toHaveCount(0);
  }
  await openStory(page, "pages-draft-review--validating");
  await expect(page.getByRole("button", { name: "正在校验…", exact: true })).toBeDisabled();
});

test("publication error retains dialog and reason, keyboard dismissal returns to review", async ({ page }) => {
  await openStory(page, "pages-draft-review--ready-for-publish");
  const trigger = page.getByRole("button", { name: "打开发布确认", exact: true });
  await trigger.click();
  const dialog = page.getByRole("dialog", { name: "发布确认", exact: true });
  await dialog.getByRole("textbox", { name: "发布说明", exact: true }).fill("核对虚构数据后尝试发布");
  await dialog.getByRole("button", { name: "确认发布", exact: true }).click();
  await expect(dialog.getByRole("alert")).toContainText("样板不提交真实发布请求。");
  await expect(dialog.getByRole("textbox", { name: "发布说明", exact: true })).toHaveValue("核对虚构数据后尝试发布");
  await page.keyboard.press("Escape");
  await expect(dialog).toHaveCount(0);
  await expect(trigger).toBeFocused();
});
