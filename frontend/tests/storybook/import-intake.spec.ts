import { expect, test } from "@playwright/test";
import { openStory } from "./storybookGateSupport";

for (const width of [1280, 768, 390]) {
  test(`import intake file recognition date correction and conflict cancellation at ${width}px`, async ({ page }) => {
    await page.setViewportSize({ width, height: 900 }); await openStory(page, "pages-import-intake--reference");
    await expect(page.getByRole("button", { name: "保存并检查文件", exact: true })).toBeDisabled();
    await page.getByLabel("CSV 文件", { exact: true }).setInputFiles({ name: "fictional.csv", mimeType: "text/csv", buffer: Buffer.from("sku,units\nfictional,2") });
    await page.getByRole("button", { name: "保存并检查文件", exact: true }).click();
    await page.getByLabel("所属报告日", { exact: true }).fill("2026-09-13");
    await expect(page.getByText("识别日期与所选报告日不同")).toBeVisible(); await page.getByRole("button", { name: "采用识别日期" }).click();
    await expect(page.getByLabel("所属报告日", { exact: true })).toHaveValue("2026-09-12");
    await page.getByRole("button", { name: "确认并解析", exact: true }).click(); await expect(page.getByRole("heading", { name: "已解析 2 行源数据" })).toBeVisible();
    await page.getByRole("button", { name: "生成审核草稿", exact: true }).click();
    await page.getByRole("radio", { name: "取消，不生成草稿", exact: true }).check(); await page.getByRole("button", { name: "确认取消", exact: true }).click();
    await expect(page.getByText("已取消，解析基线保留。", { exact: true })).toBeVisible();
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true);
  });
}
test("import intake busy, failure recovery and administrator confirmation states", async ({ page }) => {
  await openStory(page, "pages-import-intake--active-draft-conflict");
  await expect(page.getByRole("radio", { name: "替换当前发布版本", exact: true })).toBeDisabled();
  await page.getByRole("radio", { name: "管理员强制重建活动草稿", exact: true }).check();
  await expect(page.getByRole("button", { name: "强制重建审核草稿", exact: true })).toBeDisabled();
  await page.getByRole("checkbox", { name: "确认废弃目标活动草稿并保留审计历史", exact: true }).check();
  await expect(page.getByRole("button", { name: "强制重建审核草稿", exact: true })).toBeEnabled();
  await openStory(page, "pages-import-intake--parsing"); await expect(page.getByRole("button", { name: "正在解析…", exact: true })).toBeDisabled();
  await openStory(page, "pages-import-intake--parse-failure"); await expect(page.getByRole("alert")).toContainText("解析未完成");
  await page.getByRole("button", { name: "确认并解析", exact: true }).click(); await expect(page.getByRole("alert")).toHaveCount(0);
});
