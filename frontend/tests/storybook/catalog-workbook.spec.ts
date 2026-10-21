import { expect, test } from "@playwright/test";
import { openStory } from "./storybookGateSupport";

for (const width of [1280, 390]) {
  test(`workbook generate, keyboard review, selected file and reset at ${width}px`, async ({ page }) => {
    await page.setViewportSize({ width, height: 900 }); await openStory(page, "patterns-catalog-workbook--idle");
    await page.getByRole("button", { name: "生成候选", exact: true }).click();
    const review = page.getByRole("button", { name: "开始在线审核", exact: true }); await review.focus(); await page.keyboard.press("Enter");
    await expect(page.getByText(/虚构导航：候选 8001/)).toBeVisible();
    await page.getByRole("link", { name: "下载兼容 XLSX", exact: true }).click(); await expect(page.getByText(/样板仅展示下载入口/)).toBeVisible();
    await page.getByLabel("上传已修改的兼容 XLSX", { exact: true }).setInputFiles({ name: "fictional-corrections.xlsx", mimeType: "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", buffer: Buffer.from("fictional file") });
    await expect(page.getByText("fictional-corrections.xlsx", { exact: true })).toBeVisible();
    await page.getByRole("button", { name: "上传并进入审核", exact: true }).click(); await expect(page.getByText(/虚构上传：fictional-corrections.xlsx/)).toBeVisible();
    await page.reload(); await expect(page.getByRole("button", { name: "生成候选", exact: true })).toBeVisible(); await expect(page.getByRole("button", { name: "上传并进入审核", exact: true })).toBeDisabled();
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
  });
}
test("recovery, version/capacity boundaries and pending file lock", async ({ page }) => {
  await openStory(page, "patterns-catalog-workbook--failed"); await page.getByRole("button", { name: "恢复生成", exact: true }).click(); await expect(page.getByText(/虚构任务已恢复/)).toBeVisible();
  await openStory(page, "patterns-catalog-workbook--no-resume"); await expect(page.getByRole("button", { name: "恢复生成", exact: true })).toHaveCount(0);
  await openStory(page, "patterns-catalog-workbook--stale"); await expect(page.getByRole("button", { name: "开始在线审核", exact: true })).toBeDisabled(); await expect(page.getByRole("link", { name: "下载兼容 XLSX", exact: true })).toHaveCount(0);
  await openStory(page, "patterns-catalog-workbook--capacity"); await expect(page.getByRole("button", { name: "开始在线审核", exact: true })).toBeEnabled(); await expect(page.getByRole("link", { name: "下载兼容 XLSX", exact: true })).toHaveCount(0);
  await openStory(page, "patterns-catalog-workbook--building"); await expect(page.getByText("等待自动重试", { exact: true })).toBeVisible(); await expect(page.getByText(/下次重试/)).toBeVisible(); await expect(page.getByRole("button", { name: "开始在线审核", exact: true })).toHaveCount(0);
  await openStory(page, "patterns-catalog-workbook--unready"); await expect(page.getByRole("button", { name: "生成候选", exact: true })).toBeDisabled();
  await openStory(page, "patterns-catalog-workbook--no-download"); await expect(page.getByRole("link", { name: "下载兼容 XLSX", exact: true })).toHaveCount(0);
  await openStory(page, "patterns-catalog-workbook--busy"); await expect(page.getByLabel("上传已修改的兼容 XLSX", { exact: true })).toBeDisabled(); await expect(page.getByRole("button", { name: "上传并进入审核", exact: true })).toBeDisabled();
});
test("failed upload retains selected file and allows explicit retry", async ({ page }) => {
  await openStory(page, "patterns-catalog-workbook--upload-failure"); await expect(page.getByRole("alert")).toContainText("工作簿格式未通过检查");
  await expect(page.getByText("fictional-workbook.xlsx", { exact: true })).toBeVisible(); await page.getByRole("button", { name: "上传并进入审核", exact: true }).click();
  await expect(page.getByRole("alert")).toHaveCount(0); await expect(page.getByText(/虚构上传：fictional-workbook.xlsx/)).toBeVisible();
});
