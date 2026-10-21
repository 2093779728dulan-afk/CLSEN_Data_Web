import { expect, type Page } from "@playwright/test";

export async function openStory(page: Page, storyId: string): Promise<void> {
  await page.emulateMedia({ reducedMotion: "reduce" });
  await page.goto(`/iframe.html?id=${storyId}&viewMode=story`);
  await expect(page.locator("#storybook-root")).toBeVisible();
  await page.evaluate(async () => document.fonts.ready);
  await expect.poll(() => page.evaluate(() => getComputedStyle(document.body).fontFamily))
    .toContain("Noto Sans SC Variable");
}

export async function prepareInteractiveStory(page: Page, storyId: string): Promise<void> {
  if (storyId.endsWith("dialog-interaction")) {
    await page.getByRole("button", { name: "打开发布确认" }).click();
    await expect(page.getByRole("dialog")).toBeVisible();
  }
  if (storyId.endsWith("composite-interactions")) {
    await page.getByRole("tab", { name: "产品总表" }).click();
    await page.getByRole("button", { name: "更多操作" }).click();
    await expect(page.getByRole("menu")).toBeVisible();
  }
}

export function screenshotName(storyId: string, viewportName: string): string {
  return `${storyId.replace("design-system-", "")}-${viewportName}.png`;
}
