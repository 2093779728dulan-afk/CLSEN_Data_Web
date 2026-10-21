import { expect, test } from "@playwright/test";
import { openStory, prepareInteractiveStory } from "./storybookGateSupport";
for (const width of [1280, 390]) {
  test(`issue panel confirms, resolves, reopens, and retains failure input at ${width}px`, async ({ page }) => {
    await page.setViewportSize({ width, height: 900 }); const errors: string[] = []; page.on("pageerror", error => errors.push(error.message));
    await openStory(page, "patterns-issue-review--reference");
    const warning = page.getByRole("article", { name: /警告.*销售额与源文件不同/ });
    const blocking = page.getByRole("article", { name: /阻断项.*报表合计与明细不一致/ });
    await expect(warning.getByRole("button", { name: "确认警告", exact: true })).toBeDisabled();
    await warning.getByRole("textbox").fill("虚构审核说明"); await warning.getByRole("button", { name: "确认警告", exact: true }).click();
    await expect(warning.getByText("已确认", { exact: true })).toBeVisible();
    await blocking.getByRole("textbox").fill("虚构阻断说明"); await blocking.getByRole("button", { name: "标记已解决", exact: true }).click();
    await expect(blocking.getByText("已解决", { exact: true })).toBeVisible();
    await blocking.getByRole("button", { name: "重新打开", exact: true }).focus(); await page.keyboard.press("Enter");
    await expect(blocking.getByText("待处理", { exact: true })).toBeVisible();
    await openStory(page, "patterns-issue-review--save-failure"); await prepareInteractiveStory(page, "patterns-issue-review--save-failure");
    await expect(page.getByRole("textbox", { name: "审核说明", exact: true })).toHaveValue("虚构审核依据");
    await page.getByRole("button", { name: "确认警告", exact: true }).click(); await expect(page.getByText("已确认", { exact: true })).toBeVisible();
    expect(errors).toEqual([]); expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
  });
}
test("issue panel handles optional notes, long values and pending actions", async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 });
  await openStory(page, "patterns-issue-review--optional-note");
  await expect(page.getByRole("button", { name: "确认警告", exact: true })).toBeEnabled();
  await expect(page.getByRole("region", { name: "校验问题", exact: true }).locator("dd").nth(0)).toHaveText("—");
  await expect(page.getByRole("region", { name: "校验问题", exact: true }).locator("dd").nth(1)).toHaveText("0");
  await page.getByRole("button", { name: "确认警告", exact: true }).click(); await expect(page.getByText("已确认", { exact: true })).toBeVisible();
  await openStory(page, "patterns-issue-review--long-values");
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
  await openStory(page, "patterns-issue-review--saving"); await prepareInteractiveStory(page, "patterns-issue-review--saving");
  await expect(page.getByRole("textbox", { name: "审核说明", exact: true })).toBeDisabled();
  await expect(page.getByRole("button", { name: "正在提交审核", exact: true })).toBeDisabled();
});
