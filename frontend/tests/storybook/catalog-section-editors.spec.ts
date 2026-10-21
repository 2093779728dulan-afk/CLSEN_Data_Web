import { expect, test } from "@playwright/test";
import { openStory } from "./storybookGateSupport";

for (const width of [1280, 390]) {
  test(`report candidates, manual text, hidden edits and keyboard save at ${width}px`, async ({ page }) => {
    await page.setViewportSize({ width, height: 900 });
    await openStory(page, "patterns-catalog-section-editors--reference");
    const name = "demo-styles-1 standard_name";
    await page.getByRole("combobox", { name, exact: true }).selectOption("__manual__");
    const input = page.getByRole("textbox", { name, exact: true });
    await expect(input).toHaveValue("虚构报告名称");
    await page.locator('[data-review-row="demo-styles-1"]').getByRole("button", { name: "清空标准商品名称", exact: true }).click();
    await expect(input).toHaveValue(""); await expect(input).toBeFocused();
    await input.fill("本地名称"); await input.press("Escape"); await expect(input).toHaveValue("虚构报告名称");
    await page.getByRole("button", { name: "从报告候选中选择 标准商品名称", exact: true }).click();
    await page.getByRole("combobox", { name, exact: true }).selectOption("虚构退货名称");
    await page.getByLabel("demo-styles-2 standard_name", { exact: true }).fill("第二行修改");
    await page.getByRole("searchbox", { name: "搜索当前审核项", exact: true }).fill("DEMO-01");
    await page.getByText("核对本次修改 · 2 行（含筛选隐藏的修改）", { exact: true }).click();
    await expect(page.locator("ins").filter({ hasText: "第二行修改" })).toBeVisible();
    await page.getByLabel("demo-styles-1 change_reason", { exact: true }).focus();
    await page.keyboard.press("Control+Enter");
    await expect(page.getByText("已保存 2 行草稿。目录尚未批准生效。", { exact: true })).toBeVisible();
    await expect(page.getByText("样板修订 4 · 模拟提交 1 次 · 0 行未保存", { exact: true })).toBeVisible();
    await page.getByRole("searchbox", { name: "搜索当前审核项", exact: true }).fill("");
    await expect(page.getByLabel("demo-styles-2 standard_name", { exact: true })).toHaveValue("第二行修改");
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
    await page.reload(); await expect(page.getByLabel("demo-styles-2 standard_name", { exact: true })).toHaveValue("");
  });
}

test("SKU, mapping and exception selects keep their real field values", async ({ page }) => {
  await openStory(page, "patterns-catalog-section-editors--skus");
  await page.getByLabel("demo-skus-1 standard_color", { exact: true }).selectOption("浅蓝");
  await page.getByLabel("demo-skus-1 standard_size", { exact: true }).selectOption("L");
  await page.getByRole("button", { name: "保存当前分类修改（1行）", exact: true }).click();
  await expect(page.getByText("草稿保存完成", { exact: true })).toBeVisible();
  await openStory(page, "patterns-catalog-section-editors--mappings");
  await page.getByLabel("demo-mappings-1 identity_decision", { exact: true }).selectOption("mapped");
  await page.getByLabel("demo-mappings-1 target_sku_row_key", { exact: true }).selectOption("demo-sku-1");
  await page.getByRole("button", { name: "保存当前分类修改（1行）", exact: true }).click();
  await expect(page.getByText("草稿保存完成", { exact: true })).toBeVisible();
  await openStory(page, "patterns-catalog-section-editors--exceptions");
  await page.getByLabel("demo-exceptions-1 action", { exact: true }).selectOption("exclude");
  await page.getByLabel("demo-exceptions-1 exclusion_reason", { exact: true }).fill("虚构排除原因");
  await page.getByRole("button", { name: "保存当前分类修改（1行）", exact: true }).click();
  await expect(page.getByText("草稿保存完成", { exact: true })).toBeVisible();
});

test("explicit retry and acknowledged refresh failure keep the original save boundary", async ({ page }) => {
  await openStory(page, "patterns-catalog-section-editors--save-failure");
  await page.getByLabel("demo-styles-2 standard_name", { exact: true }).fill("失败后保留");
  await page.getByRole("button", { name: "保存当前分类修改（1行）", exact: true }).click();
  await expect(page.getByRole("alert")).toContainText("编辑内容已保留");
  await expect(page.getByLabel("demo-styles-2 standard_name", { exact: true })).toHaveValue("失败后保留");
  await page.getByRole("button", { name: "保存当前分类修改（1行）", exact: true }).click();
  await expect(page.getByText("样板修订 4 · 模拟提交 2 次 · 0 行未保存", { exact: true })).toBeVisible();
  await openStory(page, "patterns-catalog-section-editors--refresh-failure");
  await page.getByLabel("demo-styles-2 standard_name", { exact: true }).fill("已经保存");
  await page.getByRole("button", { name: "保存当前分类修改（1行）", exact: true }).click();
  await expect(page.getByRole("alert")).toContainText("草稿已保存，但最新明细读取失败");
  await expect(page.getByRole("button", { name: "保存当前分类修改（0行）", exact: true })).toBeDisabled();
  await page.getByRole("button", { name: "重新读取样板草稿", exact: true }).click();
  await expect(page.getByLabel("demo-styles-2 standard_name", { exact: true })).toHaveValue("已经保存");
  await expect(page.getByText("样板修订 4 · 模拟提交 1 次 · 0 行未保存", { exact: true })).toBeVisible();
});

test("read-only, disabled, issues and empty states expose the right controls", async ({ page }) => {
  await openStory(page, "patterns-catalog-section-editors--read-only");
  await expect(page.getByRole("button", { name: "保存此行", exact: true })).toHaveCount(0);
  await openStory(page, "patterns-catalog-section-editors--busy");
  await expect(page.getByLabel("demo-styles-2 standard_name", { exact: true })).toBeDisabled();
  await openStory(page, "patterns-catalog-section-editors--field-issues");
  await expect(page.getByLabel("demo-styles-2 standard_name", { exact: true })).toHaveAttribute("aria-invalid", "true");
  await expect(page.getByText("尚未填写或确认；修改后请重新校验。", { exact: true })).toBeVisible();
  await openStory(page, "patterns-catalog-section-editors--empty");
  await expect(page.getByText("当前分类没有记录", { exact: true })).toBeVisible();
  await openStory(page, "patterns-catalog-section-editors--filtered-empty");
  await expect(page.getByText("没有符合筛选条件的审核项", { exact: true })).toBeVisible();
});
