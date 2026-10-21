import { expect, test } from "@playwright/test";
import { openStory, prepareInteractiveStory } from "./storybookGateSupport";

for (const width of [1280, 390]) {
  test(`quick-view focus, context, outside close and failure recovery at ${width}px`, async ({ page }, testInfo) => {
    await page.setViewportSize({ width, height: 900 });
    await openStory(page, "pages-catalog-product-list--reference");
    const search = page.getByRole("searchbox", { name: "查找商品" });
    await search.fill("DEMO-01");
    const trigger = page.getByRole("button", { name: "快速查看 DEMO-01", exact: true });
    await trigger.click();
    const dialog = page.getByRole("dialog", { name: "商品快速查看" });
    await expect(dialog.getByRole("table")).toBeVisible();
    await expect(dialog.getByText("STYLE #1001 · 商品修订 1", { exact: true })).toBeVisible();
    for (let i = 0; i < 7; i++) { await page.keyboard.press("Tab"); expect(await dialog.evaluate(el => el.contains(document.activeElement))).toBe(true); }
    expect(await dialog.evaluate(el => el.scrollWidth <= el.clientWidth)).toBe(true);
    const note = dialog.getByText(/销售别名与详细来源/);
    const noteBox = (await note.boundingBox())!;
    expect(noteBox.x + noteBox.width).toBeLessThanOrEqual(width);
    await page.screenshot({ path: testInfo.outputPath(`drawer-${width}.png`) });
    await page.keyboard.press("Escape");
    await expect(trigger).toBeFocused();
    await expect(search).toHaveValue("DEMO-01");
    await trigger.click();
    await expect(dialog.getByRole("table")).toBeVisible();
    if (width === 1280) await page.mouse.click(8, 8);
    else await dialog.getByRole("button", { name: "关闭商品快速查看" }).click();
    await expect(dialog).toHaveCount(0);
    await expect(trigger).toBeFocused();
    await page.getByRole("button", { name: "刷新商品主档", exact: true }).click();
    await expect(search).toHaveValue("DEMO-01");
    await expect(page.getByText("正在刷新，保留当前列表", { exact: false })).toBeVisible();
    await expect(page.getByRole("button", { name: "刷新商品主档", exact: true })).toBeEnabled();
    await openStory(page, "pages-catalog-product-list--quick-view-failure");
    await prepareInteractiveStory(page, "pages-catalog-product-list--quick-view-failure");
    await dialog.getByRole("button", { name: "重新读取详情" }).click();
    await expect(dialog.getByRole("table")).toBeVisible();
    await dialog.getByRole("link", { name: "打开完整商品卡" }).click();
    await expect(page.getByRole("heading", { name: "暖灰直筒长裤" })).toBeVisible();
    await page.getByRole("link", { name: "返回商品主档", exact: true }).click();
    await expect(search).toBeVisible();
  });
}

test("drawer animates in and reduced motion shows content directly", async ({ page }) => {
  await openStory(page, "pages-catalog-product-list--reference");
  await page.emulateMedia({ reducedMotion: "no-preference" });
  const trigger = page.getByRole("button", { name: "快速查看 DEMO-01", exact: true });
  await trigger.click();
  const dialog = page.getByRole("dialog", { name: "商品快速查看" });
  const name = await dialog.evaluate(el => getComputedStyle(el).animationName);
  expect(name).toContain("drawer-in");
  await page.keyboard.press("Escape");
  await expect(dialog).toHaveCount(0);
  await page.emulateMedia({ reducedMotion: "reduce" });
  await trigger.click();
  await expect(dialog).toBeVisible();
  expect(await dialog.evaluate(el => getComputedStyle(el).animationName)).toBe("none");
  await expect(dialog.getByRole("table")).toBeVisible();
});
