import { expect, test } from "@playwright/test";
import { openStory, prepareInteractiveStory } from "./storybookGateSupport";

for (const width of [1280, 390]) {
  test(`safe sources, reveal, copy, hide and reload at ${width}px`, async ({ page, context }) => {
    await context.grantPermissions(["clipboard-read", "clipboard-write"]);
    await page.setViewportSize({ width, height: 900 });
    await openStory(page, "patterns-catalog-source-evidence--reference");
    const row = page.getByRole("listitem", { name: "来源 3", exact: true });
    await expect(row).toContainText("DEMO-01-Blue-M");
    await expect(page.getByText("[含危险字符的来源]", { exact: true })).toBeVisible();
    await expect(page.locator("output")).toHaveCount(0);
    await row.getByRole("button", { name: "查看完整标识", exact: true }).click();
    const raw = row.getByLabel("来源 3 完整标识", { exact: true });
    await expect(raw).toContainText("虚构来源 DEMO-01-Blue-M <仅示例>");
    await row.getByRole("button", { name: "复制完整标识", exact: true }).click();
    await expect(row.getByText("已复制到剪贴板", { exact: true })).toBeVisible();
    expect((await page.evaluate(() => navigator.clipboard.readText())).replace(/\r\n/g, "\n")).toBe("虚构来源 DEMO-01-Blue-M <仅示例>\n第二行");
    await row.getByRole("button", { name: "隐藏完整标识", exact: true }).click();
    await expect(raw).toHaveCount(0);
    await expect(row.getByRole("button", { name: "复制完整标识", exact: true })).toHaveCount(0);
    await page.reload(); await expect(row).toContainText("DEMO-01-Blue-M"); await expect(page.locator("output")).toHaveCount(0);
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
  });
}
test("read and reveal failures require explicit retry; copy failures do not claim success", async ({ page }) => {
  await openStory(page, "patterns-catalog-source-evidence--read-failure"); await prepareInteractiveStory(page, "patterns-catalog-source-evidence--read-failure");
  await page.getByRole("button", { name: "重新读取来源", exact: true }).click();
  await expect(page.getByRole("listitem", { name: "来源 3", exact: true })).toBeVisible();
  await openStory(page, "patterns-catalog-source-evidence--reveal-failure"); await prepareInteractiveStory(page, "patterns-catalog-source-evidence--reveal-failure");
  const row = page.getByRole("listitem", { name: "来源 3", exact: true });
  await expect(page.locator("output")).toHaveCount(0); await expect(row).toContainText("DEMO-01-Blue-M");
  await row.getByRole("button", { name: "查看完整标识", exact: true }).click(); await expect(row.locator("output")).toBeVisible();
  await page.evaluate(() => { Object.defineProperty(navigator.clipboard, "writeText", { value: () => Promise.reject(new Error("fictional denied")), configurable: true }); });
  await row.getByRole("button", { name: "复制完整标识", exact: true }).click();
  await expect(row.getByRole("alert")).toContainText("复制未完成"); await expect(row.getByText("已复制到剪贴板", { exact: true })).toHaveCount(0);
});
test("permission generation clears revealed values; pending and long states stay usable", async ({ page }) => {
  await openStory(page, "patterns-catalog-source-evidence--boundary-change"); await prepareInteractiveStory(page, "patterns-catalog-source-evidence--boundary-change");
  await expect(page.locator("output")).toBeVisible(); await page.getByRole("button", { name: "模拟权限变化", exact: true }).click(); await expect(page.locator("output")).toHaveCount(0);
  await openStory(page, "patterns-catalog-source-evidence--revealing"); await prepareInteractiveStory(page, "patterns-catalog-source-evidence--revealing");
  await expect(page.getByRole("listitem", { name: "来源 3", exact: true }).getByRole("button", { name: "正在校验权限", exact: true })).toBeDisabled();
  await page.setViewportSize({ width: 390, height: 900 });
  for (const state of ["long-preview", "long-identifier"]) {
    await openStory(page, `patterns-catalog-source-evidence--${state}`); await prepareInteractiveStory(page, `patterns-catalog-source-evidence--${state}`);
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
  }
  await openStory(page, "patterns-catalog-source-evidence--empty"); await expect(page.getByRole("heading", { name: "暂无来源证据", exact: true })).toBeVisible();
});
