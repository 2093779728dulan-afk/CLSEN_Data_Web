import { expect, test } from "@playwright/test";
import { openStory, prepareInteractiveStory } from "./storybookGateSupport";

for (const width of [1280, 768, 390]) {
  test(`catalog preview, reason, rebase and approval flow at ${width}px`, async ({ page }) => {
    await page.setViewportSize({ width, height: 900 });
    await openStory(page, "patterns-catalog-workflow-forms--reference");
    await page.getByRole("button", { name: "生成批准预览", exact: true }).click();
    const reason = page.getByRole("textbox", { name: "批准原因", exact: true });
    await reason.fill("ab"); await expect(page.getByRole("button", { name: "确认批准目录", exact: true })).toBeDisabled();
    await reason.fill("虚构批准依据");
    await page.getByText("高级操作 · 调整目录基准", { exact: true }).click();
    const id = page.getByRole("textbox", { name: "替代导出编号（export ID）", exact: true });
    await id.fill("invalid"); await expect(page.getByRole("button", { name: "调整到新基准", exact: true })).toBeDisabled();
    await id.fill("8002"); await page.getByRole("button", { name: "调整到新基准", exact: true }).click();
    await expect(page.getByText("当前修订 4", { exact: true })).toBeVisible();
    await expect(page.getByRole("textbox", { name: "批准原因", exact: true })).toHaveCount(0);
    await expect(id).toHaveValue("8002");
    await page.getByRole("button", { name: "生成批准预览", exact: true }).click();
    await expect(reason).toHaveValue("虚构批准依据");
    await page.getByRole("button", { name: "确认批准目录", exact: true }).click();
    await expect(page.getByRole("heading", { name: "已批准生效", exact: true })).toBeVisible();
    await expect(page.getByRole("link", { name: "查看目录版本", exact: true })).toHaveAttribute("href", "/catalog/versions");
    await page.reload(); await expect(page.getByRole("button", { name: "生成批准预览", exact: true })).toBeVisible();
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
  });
}

test("catalog advanced form retains failed input, allows explicit retry and locks pending actions", async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 900 });
  await openStory(page, "patterns-catalog-workflow-forms--failure"); await prepareInteractiveStory(page, "patterns-catalog-workflow-forms--failure");
  const id = page.getByRole("textbox", { name: "替代导出编号（export ID）", exact: true });
  await expect(id).toHaveValue("8002"); await expect(page.getByRole("alert")).toContainText("目录发布修订已变化");
  await page.getByRole("button", { name: "调整到新基准", exact: true }).click();
  await expect(page.getByText("当前修订 4", { exact: true })).toBeVisible(); await expect(page.getByRole("alert")).toHaveCount(0);
  await openStory(page, "patterns-catalog-workflow-forms--saving"); await prepareInteractiveStory(page, "patterns-catalog-workflow-forms--saving");
  await expect(id).toBeDisabled(); await expect(page.getByRole("button", { name: "生成批准预览", exact: true })).toBeDisabled();
});

test("catalog risk permissions and blocked drafts stay authoritative", async ({ page }) => {
  await openStory(page, "patterns-catalog-workflow-forms--high-risk"); await prepareInteractiveStory(page, "patterns-catalog-workflow-forms--high-risk");
  await expect(page.getByText("风险：高风险（仅管理员可批准）", { exact: true })).toBeVisible();
  await expect(page.getByRole("button", { name: "确认批准目录", exact: true })).toHaveCount(0);
  await openStory(page, "patterns-catalog-workflow-forms--blocked"); await prepareInteractiveStory(page, "patterns-catalog-workflow-forms--blocked");
  await expect(page.getByRole("textbox", { name: "替代导出编号（export ID）", exact: true })).toBeDisabled();
  await expect(page.getByRole("button", { name: "生成批准预览", exact: true })).toBeDisabled();
  await openStory(page, "patterns-catalog-workflow-forms--read-only");
  await expect(page.getByRole("textbox")).toHaveCount(0); await expect(page.getByRole("button")).toHaveCount(0);
});
