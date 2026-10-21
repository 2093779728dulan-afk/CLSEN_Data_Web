import { expect, test } from "@playwright/test";
import { TABLE_HEADER_STORY_IDS } from "./storybookGateManifest";
import { openStory } from "./storybookGateSupport";

test("shared header sorts results, resizes by pointer/keyboard and retains browser width", async ({ page }) => {
  await openStory(page, "patterns-table-header--reference");
  const table = page.getByRole("table", { name: "虚构报表" });
  const sales = table.getByRole("button", { name: "按 销售额 排序", exact: true });
  const rows = table.locator("tbody tr");
  await sales.click(); await expect(sales.locator("..")).toHaveAttribute("aria-sort", "ascending");
  await expect(rows.first()).toContainText("DEMO-WHITE-M");
  await sales.click(); await expect(sales.locator("..")).toHaveAttribute("aria-sort", "descending");
  await expect(rows.first()).toContainText("DEMO-GREEN-L");
  await sales.focus(); await page.keyboard.press("Enter");
  await expect(sales.locator("..")).toHaveAttribute("aria-sort", "none"); await expect(rows.first()).toContainText("DEMO-BLUE-S");
  const resize = table.getByRole("button", { name: "调整“Seller SKU”列宽", exact: true });
  const header = resize.locator(".."); const initial = await header.evaluate(el => parseFloat(el.style.width));
  await resize.focus(); await page.keyboard.press("ArrowRight");
  await expect.poll(async () => await header.evaluate(el => parseFloat(el.style.width))).toBe(initial + 8);
  const box = (await resize.boundingBox())!;
  await page.mouse.move(box.x + 6, box.y + box.height / 2); await page.mouse.down(); await page.mouse.move(box.x + 30, box.y + box.height / 2);
  await expect(header).toHaveAttribute("data-resizing", "true");
  await page.mouse.up(); const resized = await header.evaluate(el => parseFloat(el.style.width));
  expect(resized).toBe(initial + 32); await expect(header).not.toHaveAttribute("data-resizing");
  await page.reload(); await expect.poll(async () => await header.evaluate(el => parseFloat(el.style.width))).toBe(resized);
});
for (const storyId of TABLE_HEADER_STORY_IDS) {
  test(`${storyId} keeps frozen headers and narrow-screen controls usable`, async ({ page }) => {
    await page.setViewportSize({ width: 390, height: 844 }); await openStory(page, storyId);
    const table = page.getByRole("table", { name: "虚构报表" });
    await expect(table.locator("thead tr")).toHaveCount(2);
    const scroll = page.getByRole("region", { name: "可横向滚动的虚构表格" });
    const leading = table.getByRole("columnheader", { name: "行号", exact: true });
    const initial = (await leading.boundingBox())!.x;
    await scroll.evaluate(el => { el.scrollLeft = 400; });
    expect((await leading.boundingBox())!.x).toBe(initial);
    await table.getByRole("button", { name: /按 .* 排序/ }).first().focus(); await page.keyboard.press("Enter");
    await expect(table.locator('th[aria-sort="ascending"],th[aria-sort="descending"]')).toHaveCount(1);
    if (storyId.endsWith("--split-groups")) await expect(table.getByRole("columnheader", { name: "商品信息", exact: true })).toHaveCount(2);
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
  });
}
