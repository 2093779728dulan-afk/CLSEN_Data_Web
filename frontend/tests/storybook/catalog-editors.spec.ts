import { expect, test } from "@playwright/test";
import { openStory, prepareInteractiveStory } from "./storybookGateSupport";

for (const width of [1280, 390]) {
  test(`shared editors complete draft, preview, approval and category operations at ${width}px`, async ({ page }) => {
    await page.setViewportSize({ width, height: 900 });
    const api: string[] = [];
    await page.route(url => url.pathname.startsWith("/api/"), route => { api.push(route.request().url()); return route.abort(); });
    await openStory(page, "pages-catalog-editors--editing");
    await prepareInteractiveStory(page, "pages-catalog-editors--editing");
    await page.getByRole("textbox", { name: "标准商品名称", exact: true }).fill("示例新名称");
    await page.getByRole("combobox", { name: "主分类", exact: true }).selectOption("7");
    await page.getByRole("combobox", { name: "细分类（可选）", exact: true }).selectOption("8");
    await page.getByRole("button", { name: "生成变更预览", exact: true }).click();
    const table = page.getByRole("table", { name: "变更预览", exact: true });
    await expect(table.getByText("示例新名称", { exact: true })).toBeVisible();
    await expect(table.getByText("连衣裙 / 短款连衣裙（DRESS_MINI）", { exact: true })).toBeVisible();
    const reason = page.getByRole("textbox", { name: "批准原因", exact: true });
    await reason.fill("ab"); await expect(page.getByRole("button", { name: "批准并生成新目录版本", exact: true })).toBeDisabled();
    await page.getByRole("button", { name: "返回修改", exact: true }).click();
    await expect(page.getByRole("textbox", { name: "标准商品名称", exact: true })).toHaveValue("示例新名称");
    await page.getByRole("button", { name: "生成变更预览", exact: true }).click();
    await reason.fill("示例维护原因");
    await page.getByRole("button", { name: "批准并生成新目录版本", exact: true }).click();
    await expect(page.getByText(/示例目录已更新/)).toBeVisible();
    await expect(page.getByRole("button", { name: "修改名称 / 分类", exact: true })).toBeVisible();
    await openStory(page, "pages-catalog-editors--categories");
    await prepareInteractiveStory(page, "pages-catalog-editors--categories");
    await page.getByRole("button", { name: "编辑 连衣裙", exact: true }).click();
    await expect(page.getByRole("combobox", { name: "上级分类", exact: true })).toBeDisabled();
    await page.getByRole("button", { name: "编辑 短款连衣裙", exact: true }).click();
    await page.getByRole("textbox", { name: "分类名称", exact: true }).fill("示例编辑分类");
    await page.getByRole("button", { name: "编辑 衬衫", exact: true }).click();
    await expect(page.getByRole("alert")).toContainText("尚未保存");
    await expect(page.getByRole("textbox", { name: "分类名称", exact: true })).toHaveValue("示例编辑分类");
    await page.getByRole("button", { name: "保存修改", exact: true }).click();
    await expect(page.getByText("分类已保存", { exact: true })).toBeVisible();
    await page.getByRole("button", { name: "关闭分类管理", exact: true }).click();
    await page.getByRole("button", { name: "管理分类", exact: true }).click();
    await expect(page.getByRole("button", { name: "编辑 示例编辑分类", exact: true })).toBeVisible();
    await page.getByRole("button", { name: "新建分类", exact: true }).click();
    await page.getByRole("textbox", { name: "分类名称", exact: true }).fill("示例新分类");
    await page.getByRole("textbox", { name: "分类代码", exact: true }).fill("SHIRT_NEW");
    await page.getByRole("button", { name: "创建分类", exact: true }).click();
    await expect(page.getByRole("button", { name: "编辑 示例新分类", exact: true })).toBeVisible();
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
    expect(api).toEqual([]);
  });
}

test("editor failure states preserve edits and provide explicit recovery", async ({ page }) => {
  for (const state of ["prepare-failure", "approval-failure", "refresh-failure", "preparing", "unsaved", "loading", "empty", "read-failure", "save-failure", "saved"]) {
    await openStory(page, `pages-catalog-editors--${state}`);
    await prepareInteractiveStory(page, `pages-catalog-editors--${state}`);
    if (state === "read-failure") { await page.getByRole("button", { name: "重新读取分类", exact: true }).click(); await expect(page.getByRole("button", { name: "编辑 衬衫", exact: true })).toBeVisible(); }
    if (state === "prepare-failure") { await expect(page.getByRole("textbox", { name: "标准商品名称", exact: true })).toHaveValue("示例浅蓝府绸衬衫"); await page.getByRole("button", { name: "生成变更预览", exact: true }).click(); await expect(page.getByRole("table", { name: "变更预览", exact: true })).toBeVisible(); }
    if (state === "save-failure") { await expect(page.getByRole("textbox", { name: "分类名称", exact: true })).toHaveValue("示例短款连衣裙"); await page.getByRole("button", { name: "保存修改", exact: true }).click(); await expect(page.getByText("分类已保存", { exact: true })).toBeVisible(); }
    if (state === "preparing") { await expect(page.getByRole("textbox", { name: "标准商品名称", exact: true })).toBeDisabled(); await expect(page.getByRole("button", { name: "关闭修改", exact: true })).toBeDisabled(); }
  }
});

test("mobile change preview shows both before and after without horizontal scrolling", async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 });
  await openStory(page, "pages-catalog-editors--preview");
  await prepareInteractiveStory(page, "pages-catalog-editors--preview");
  const table = page.getByRole("table", { name: "变更预览", exact: true });
  for (const text of ["修改前", "批准后", "示例府绸衬衫", "示例浅蓝府绸衬衫"]) {
    const cell = table.getByText(text, { exact: true });
    await expect(cell).toBeVisible();
    const bounds = await cell.boundingBox();
    expect(bounds).not.toBeNull();
    expect(bounds!.x).toBeGreaterThanOrEqual(0);
    expect(bounds!.x + bounds!.width).toBeLessThanOrEqual(390);
  }
});
