import { expect, test } from "@playwright/test";
import { openStory, prepareInteractiveStory } from "./storybookGateSupport";
import { VIEWPORTS } from "./storybookGateManifest";

for (const viewport of VIEWPORTS) {
  test(`import evidence source and note workflow at ${viewport.width}px`, async ({ page }) => {
    await page.setViewportSize(viewport);
    const errors: string[] = []; page.on("pageerror", error => errors.push(error.message));
    const api: string[] = []; page.on("request", request => { if (new URL(request.url()).pathname.startsWith("/api/")) api.push(request.url()); });
    await openStory(page, "pages-import-evidence--reference");
    const source = page.getByRole("region", { name: "上传源表预览", exact: true });
    await expect(source.getByRole("rowheader", { name: "1", exact: true })).toBeVisible();
    const search = source.getByRole("searchbox", { name: "搜索预览行", exact: true });
    await search.fill("DEMO-003");
    await expect(source.getByRole("rowheader", { name: "3", exact: true })).toBeVisible();
    await expect(source.getByRole("rowheader", { name: "1", exact: true })).toHaveCount(0);
    await search.fill("not-a-row"); await expect(source.getByText("没有找到符合条件的预览记录。", { exact: true })).toBeVisible();
    await search.fill(""); await source.getByRole("button", { name: "下一页", exact: true }).click();
    await expect(source.getByRole("rowheader", { name: "9", exact: true })).toBeVisible();
    await source.getByRole("button", { name: "收起源表", exact: true }).click(); await expect(source.getByRole("table")).toHaveCount(0);
    await source.getByRole("button", { name: "查看上传源表", exact: true }).click(); await expect(source.getByRole("rowheader", { name: "9", exact: true })).toBeVisible();
    const notes = page.getByRole("region", { name: "导入批次 #81 备注", exact: true });
    await expect(notes.getByRole("button", { name: "追加批次备注", exact: true })).toBeDisabled();
    await notes.getByRole("textbox", { name: "批次备注内容", exact: true }).fill("虚构补充核对结果");
    await notes.getByRole("button", { name: "追加批次备注", exact: true }).click();
    await expect(notes.getByText("虚构补充核对结果", { exact: true })).toBeVisible();
    await notes.getByRole("button", { name: "修订备注", exact: true }).first().click();
    const editor = notes.getByRole("textbox", { name: "修订备注 demo-batch-note-1", exact: true });
    await expect(editor).toBeFocused(); await editor.fill("虚构修订结果");
    await notes.getByRole("button", { name: "取消修订", exact: true }).click(); await expect(editor).toHaveCount(0);
    await notes.getByRole("button", { name: "修订备注", exact: true }).first().click();
    await editor.fill("虚构修订结果"); await notes.getByRole("button", { name: "保存新修订", exact: true }).click();
    await expect(notes.getByText("虚构修订结果", { exact: true })).toBeVisible(); await expect(notes.getByText("第 2 版", { exact: true })).toBeVisible();
    await expect(notes.getByRole("combobox")).toHaveCount(0);
    await notes.getByRole("button", { name: "收起批次备注", exact: true }).click(); await expect(notes.getByRole("textbox")).toHaveCount(0);
    await notes.getByRole("button", { name: "管理批次备注", exact: true }).click(); await expect(notes.getByText("虚构修订结果", { exact: true })).toBeVisible();
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
    expect(errors).toEqual([]); expect(api).toEqual([]);
  });
}

test("import evidence read retries and revision failure preserve the draft", async ({ page }) => {
  for (const [id, retry, expected] of [
    ["source-read-failure", "重试", "上传源表数据"],
    ["notes-read-failure", "重新加载批次备注", "已记录备注"],
  ] as const) {
    await openStory(page, `pages-import-evidence--${id}`);
    await expect(page.getByRole("alert")).toBeVisible();
    await page.getByRole("button", { name: retry, exact: true }).click(); await expect(page.getByRole("alert")).toHaveCount(0);
    if (id.startsWith("source")) await expect(page.getByRole("table", { name: expected, exact: true })).toBeVisible();
    else await expect(page.getByRole("heading", { name: expected, exact: true })).toBeVisible();
  }
  await openStory(page, "pages-import-evidence--revision-failure");
  await prepareInteractiveStory(page, "pages-import-evidence--revision-failure");
  const field = page.getByRole("textbox", { name: "修订备注 demo-batch-note-1", exact: true });
  await expect(field).not.toHaveValue(""); await field.fill("失败后仍可提交同一修订");
  await page.getByRole("button", { name: "保存新修订", exact: true }).click();
  await expect(page.getByText("失败后仍可提交同一修订", { exact: true })).toBeVisible(); await expect(page.getByText("第 2 版", { exact: true })).toBeVisible();
  await expect(page.getByRole("alert")).toHaveCount(0);
});
