import { expect, test } from "@playwright/test";
import { openStory } from "./storybookGateSupport";
import { VIEWPORTS } from "./storybookGateManifest";

for (const viewport of VIEWPORTS) test(`recovery context, gating, keyboard and result at ${viewport.width}px`, async ({ page }) => {
  await page.setViewportSize(viewport); const api: string[] = []; page.on("request", r => { if (new URL(r.url()).pathname.startsWith("/api/")) api.push(r.url()); });
  await openStory(page, "pages-admin-recovery--reference"); await expect(page.getByRole("heading", { name: "强制重建从导入冲突进入" })).toBeVisible(); await expect(page.getByRole("form")).toHaveCount(0);
  await openStory(page, "pages-admin-recovery--context"); await expect(page.getByRole("complementary", { name: "重建来源上下文" })).toContainText("#51");
  const submit = page.getByRole("button", { name: "强制重建草稿", exact: true }); await expect(submit).toBeDisabled();
  await page.getByRole("textbox", { name: "重建原因" }).fill("核对后的虚构更正原因"); await expect(submit).toBeDisabled();
  const checkbox = page.getByRole("checkbox"); await checkbox.focus(); await checkbox.press("Space"); await expect(submit).toBeEnabled();
  await submit.focus(); await submit.press("Enter"); await expect(page.getByText("草稿已重建为 v3；新草稿仍需重新校验。", { exact: true })).toBeVisible(); await expect(submit).toBeDisabled();
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true); expect(api).toEqual([]);
});
test("recovery failure retains fields, pending locks controls and read failure retries", async ({ page }) => {
  await openStory(page, "pages-admin-recovery--failure"); await expect(page.getByRole("alert")).toContainText("结果尚未确认"); await expect(page.getByRole("textbox")).not.toHaveValue(""); await expect(page.getByRole("checkbox")).toBeChecked();
  await page.getByRole("button", { name: "强制重建草稿", exact: true }).click(); await expect(page.getByText("草稿已重建为 v3；新草稿仍需重新校验。", { exact: true })).toBeVisible();
  await openStory(page, "pages-admin-recovery--submitting"); await expect(page.getByRole("textbox")).toBeDisabled(); await expect(page.getByRole("checkbox")).toBeDisabled(); await expect(page.getByRole("button", { name: "正在重建…", exact: true })).toBeDisabled();
  await openStory(page, "pages-admin-recovery--read-failure"); await page.getByRole("button", { name: "重新读取", exact: true }).click(); await expect(page.getByRole("heading", { name: "强制重建从导入冲突进入" })).toBeVisible();
});
