import { expect, test } from "@playwright/test";
import { openStory } from "./storybookGateSupport";

test("save feedback keeps width, blocks duplicate clicks and preserves input on failure", async ({ page }, testInfo) => {
  await openStory(page, "design-system-actions-and-status--save-feedback");
  await page.emulateMedia({ reducedMotion: "no-preference" });
  await page.getByLabel("审核名称", { exact: true }).fill("保留的示例草稿");
  await page.getByLabel("模拟本次保存失败").check();
  const button = page.getByRole("button", { name: "保存修改", exact: true });
  const before = await button.boundingBox();
  await button.click();
  const pending = page.getByRole("button", { name: "正在保存修改", exact: true });
  await expect(pending).toBeDisabled();
  await expect(pending).toHaveAttribute("aria-busy", "true");
  const during = await pending.boundingBox();
  expect(Math.abs(before!.width - during!.width)).toBeLessThan(1);
  await page.screenshot({ path: testInfo.outputPath("save-feedback-pending.png") });
  await expect(page.getByRole("alert")).toContainText("输入内容已保留");
  await page.screenshot({ path: testInfo.outputPath("save-feedback-failure.png") });
  await expect(page.getByLabel("审核名称", { exact: true })).toHaveValue("保留的示例草稿");
  await page.getByLabel("模拟本次保存失败").uncheck();
  await button.click();
  await expect(page.getByRole("status").filter({ hasText: "修改已保存" })).toContainText("保留的示例草稿");
  await expect(button).toBeEnabled();
  await page.screenshot({ path: testInfo.outputPath("save-feedback-success.png") });
});

test("dialog opens and exits with focus returned in normal and reduced motion", async ({ page }) => {
  await openStory(page, "design-system-structure-and-navigation--dialog-interaction");
  for (const preference of ["no-preference", "reduce"] as const) {
    await page.emulateMedia({ reducedMotion: preference });
    const opener = page.getByRole("button", { name: "打开发布确认" });
    await opener.click();
    const dialog = page.getByRole("dialog");
    await expect(dialog).toBeVisible();
    const animation = await dialog.evaluate(element => getComputedStyle(element).animationName);
    expect(preference === "reduce" ? animation === "none" : animation.includes("content-in")).toBe(true);
    await page.keyboard.press("Escape");
    await expect(dialog).toHaveCount(0);
    await expect(opener).toBeFocused();
  }
});

test("review transitions retain cross-category drafts and reduced motion stops loops", async ({ page }) => {
  await openStory(page, "pages-catalog-import-review--reference");
  await page.emulateMedia({ reducedMotion: "no-preference" });
  await page.getByLabel("demo-style-1 standard_name", { exact: true }).fill("跨分类保留的示例");
  await page.getByRole("tab", { name: /SKU 标准化/ }).click();
  await expect(page.getByRole("tabpanel").filter({ has: page.getByRole("heading", { name: "SKU 标准化", exact: true }) })).toBeVisible();
  await page.getByRole("tab", { name: /款式命名/ }).click();
  await expect(page.getByLabel("demo-style-1 standard_name", { exact: true })).toHaveValue("跨分类保留的示例");
  const panel = page.getByRole("tabpanel").filter({ has: page.getByRole("heading", { name: "款式命名", exact: true }) });
  expect(await panel.evaluate(element => getComputedStyle(element).animationName)).toContain("content-enter");
  await page.emulateMedia({ reducedMotion: "reduce" });
  expect(await panel.evaluate(element => getComputedStyle(element).animationName)).toBe("none");
  const reload = page.getByRole("button", { name: "重新读取草稿", exact: true });
  await reload.click();
  const pending = page.getByRole("button", { name: "正在读取草稿", exact: true });
  await expect(pending).toBeDisabled();
  expect(await pending.locator("svg[role='status']").evaluate(element => getComputedStyle(element).animationName)).toBe("none");
  await expect(reload).toBeEnabled();
  await expect(page.getByLabel("demo-style-1 standard_name", { exact: true })).toHaveValue("跨分类保留的示例");
  await page.goto("/iframe.html?id=pages-catalog-import-review--loading&viewMode=story");
  await expect(page.getByRole("progressbar", { name: "审核明细加载进度" })).toHaveAttribute("value", "2");
  expect(await page.locator("[aria-hidden='true'] span").first().evaluate(element => getComputedStyle(element, "::after").animationName)).toBe("none");
});
