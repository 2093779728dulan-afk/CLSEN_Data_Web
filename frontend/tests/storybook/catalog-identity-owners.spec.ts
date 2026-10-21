import { expect, test } from "@playwright/test";
import { openStory, prepareInteractiveStory } from "./storybookGateSupport";

for (const width of [1280, 768, 390]) {
  test(`identity ownership, conflict links and draft restore at ${width}px`, async ({ page }) => {
    await page.setViewportSize({ width, height: 900 });
    await openStory(page, "patterns-catalog-identity-owners--reference");
    await expect(page.getByRole("button", { name: "恢复到待审核", exact: true })).toBeDisabled();
    await prepareInteractiveStory(page, "patterns-catalog-identity-owners--reference");
    await expect(page.getByRole("link", { name: "商品 STYLE #8", exact: true })).toHaveAttribute("href", "/catalog/styles/8");
    await expect(page.getByRole("link", { name: "审核批次 #9", exact: true })).toHaveAttribute("href", "/catalog/imports/9");
    await expect(page.getByRole("region", { name: "已忽略记录", exact: true })).toContainText("此前按非经营商品排除");
    const reason = page.getByRole("textbox", { name: "恢复审核原因", exact: true });
    await reason.fill("   "); await expect(page.getByRole("button", { name: "恢复到待审核", exact: true })).toBeDisabled();
    await reason.fill("虚构复核依据"); await page.getByRole("button", { name: "恢复到待审核", exact: true }).click();
    await expect(page.getByText("草稿已恢复到待审核", { exact: true })).toBeVisible();
    await expect(reason).toHaveCount(0); await expect(page.getByRole("region", { name: "已忽略记录", exact: true })).toBeVisible();
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
    await page.reload(); await expect(reason).toHaveValue("");
  });
}

test("identity read and restore errors retain input and require explicit retry", async ({ page }) => {
  await openStory(page, "patterns-catalog-identity-owners--read-failure"); await prepareInteractiveStory(page, "patterns-catalog-identity-owners--read-failure");
  await page.getByRole("button", { name: "查看归属与冲突", exact: true }).click();
  await expect(page.getByRole("region", { name: "身份归属", exact: true })).toBeVisible();
  await openStory(page, "patterns-catalog-identity-owners--restore-failure"); await prepareInteractiveStory(page, "patterns-catalog-identity-owners--restore-failure");
  await expect(page.getByRole("textbox", { name: "恢复审核原因", exact: true })).toHaveValue("虚构来源复核依据");
  await page.getByRole("button", { name: "恢复到待审核", exact: true }).click();
  await expect(page.getByText("草稿已恢复到待审核", { exact: true })).toBeVisible();
  await openStory(page, "patterns-catalog-identity-owners--refresh-failure"); await prepareInteractiveStory(page, "patterns-catalog-identity-owners--refresh-failure");
  await expect(page.getByRole("button", { name: "恢复到待审核", exact: true })).toBeDisabled();
  await page.getByRole("button", { name: "重新读取草稿", exact: true }).click();
  await expect(page.getByText("草稿已恢复到待审核", { exact: true })).toBeVisible();
});

test("identity empty, long reason, pending and read-only states stay usable", async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 900 });
  await openStory(page, "patterns-catalog-identity-owners--empty"); await prepareInteractiveStory(page, "patterns-catalog-identity-owners--empty");
  await expect(page.getByRole("heading", { name: "尚无正式归属或草稿占用。", exact: true })).toBeVisible();
  await openStory(page, "patterns-catalog-identity-owners--long-reason"); await prepareInteractiveStory(page, "patterns-catalog-identity-owners--long-reason");
  const record = page.getByRole("region", { name: "已忽略记录", exact: true }); await expect(record).toContainText("不会自动改变正式目录");
  expect(await record.evaluate(el => el.scrollWidth <= el.clientWidth && el.scrollHeight <= el.clientHeight)).toBe(true);
  await openStory(page, "patterns-catalog-identity-owners--restore-saving"); await prepareInteractiveStory(page, "patterns-catalog-identity-owners--restore-saving");
  await expect(page.getByRole("button", { name: "查看归属与冲突", exact: true })).toBeDisabled();
  await openStory(page, "patterns-catalog-identity-owners--read-only");
  await expect(page.getByRole("textbox", { name: "恢复审核原因", exact: true })).toBeDisabled();
  await expect(page.getByRole("button", { name: "查看归属与冲突", exact: true })).toBeDisabled();
});
