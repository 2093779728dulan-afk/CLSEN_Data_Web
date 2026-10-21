import { expect, test } from "@playwright/test";
import { openStory } from "./storybookGateSupport";

for (const width of [1280, 768, 390]) {
  test(`merge decisions preserve pairs, reasons and pagination at ${width}px`, async ({ page }) => {
    await page.setViewportSize({ width, height: 900 }); await openStory(page, "patterns-merge-decision-matrix--reference");
    const matrix = page.getByRole("region", { name: "重复记录合并决定", exact: true });
    await expect(matrix.getByText("6 组重复记录 · 已处理 1/6", { exact: true })).toBeVisible();
    const first = matrix.getByLabel("重复记录 1 处理方式", { exact: true }); await expect(first).toHaveValue("keep_target");
    const originalReason = await matrix.getByLabel("重复记录 1 决定依据", { exact: true }).inputValue();
    await matrix.getByLabel("当前页统一处理方式", { exact: true }).selectOption("keep_source");
    await matrix.getByRole("button", { name: "应用到当前页未处理项", exact: true }).click();
    await expect(first).toHaveValue("keep_target"); await expect(matrix.getByLabel("重复记录 1 决定依据", { exact: true })).toHaveValue(originalReason);
    await expect(matrix.getByText("6 组重复记录 · 已处理 4/6", { exact: true })).toBeVisible();
    await expect(page.getByLabel("合并决定状态", { exact: true })).toContainText("未就绪");
    await matrix.getByRole("button", { name: "下一页", exact: true }).click();
    await expect(matrix.getByLabel("重复记录 5 处理方式", { exact: true })).toHaveValue("");
    await matrix.getByLabel("当前页统一处理方式", { exact: true }).selectOption("keep_both");
    await matrix.getByRole("button", { name: "应用到当前页未处理项", exact: true }).click();
    await expect(page.getByLabel("合并决定状态", { exact: true })).toContainText("已就绪：6 组决定");
    const reason = matrix.getByLabel("重复记录 6 决定依据", { exact: true });
    await expect(reason).toHaveValue(/用户 #88.*目标第 6 行.*来源第 16 行/);
    await reason.fill(""); await expect(page.getByLabel("合并决定状态", { exact: true })).toContainText("未就绪");
    await reason.fill("核对原表：两笔记录均需保留"); await expect(page.getByLabel("合并决定状态", { exact: true })).toContainText("已就绪：6 组决定");
    await matrix.getByRole("button", { name: "上一页", exact: true }).click(); await expect(first).toHaveValue("keep_target");
    await first.focus(); await expect(first).toBeFocused();
    await openStory(page, "patterns-merge-decision-matrix--hidden-fields");
    const pair = page.getByRole("article", { name: "重复记录 1", exact: true });
    await expect(pair.getByText("7 个字段不同", { exact: true })).toBeVisible();
    await pair.getByText("查看两行的全部字段", { exact: true }).click();
    const full = pair.getByRole("table", { name: "重复记录 1 全部字段", exact: true });
    await expect(full.getByText("第七个差异字段，必须在全部字段中可查看", { exact: true })).toBeVisible();
    const scroll = pair.getByRole("region", { name: "重复记录 1 完整字段，可横向滚动", exact: true }); await scroll.focus(); await expect(scroll).toBeFocused();
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
  });
}

test("matrix recovery, identical defaults, readonly and embedded focus", async ({ page }) => {
  await openStory(page, "patterns-merge-decision-matrix--read-failure");
  await expect(page.getByRole("alert")).toContainText("预览暂时不可用"); await expect(page.getByLabel("合并决定状态", { exact: true })).toContainText("未就绪");
  await page.getByRole("button", { name: "重新读取重复记录", exact: true }).click(); await expect(page.getByText("6 组重复记录 · 已处理 1/6", { exact: true })).toBeVisible();
  await openStory(page, "patterns-merge-decision-matrix--identical"); await expect(page.getByLabel("合并决定状态", { exact: true })).toContainText("已就绪：6 组决定");
  await page.getByRole("button", { name: "下一页", exact: true }).click(); await expect(page.getByLabel("重复记录 6 处理方式", { exact: true })).toHaveValue("keep_target");
  await openStory(page, "patterns-merge-decision-matrix--empty"); await expect(page.getByLabel("合并决定状态", { exact: true })).toContainText("已就绪：0 组决定");
  await openStory(page, "patterns-merge-decision-matrix--loading"); await expect(page.getByRole("status", { name: "正在读取重复记录", exact: true })).toBeVisible();
  await expect(page.getByLabel("合并决定状态", { exact: true })).toContainText("未就绪");
  await openStory(page, "patterns-merge-decision-matrix--disabled"); await expect(page.getByLabel("重复记录 2 处理方式", { exact: true })).toBeDisabled();
  await expect(page.getByLabel("重复记录 2 决定依据", { exact: true })).toBeDisabled();
  await openStory(page, "patterns-merge-decision-matrix--return-report"); await expect(page.getByText(/退货报告按/)).toBeVisible();
  await openStory(page, "patterns-merge-decision-matrix--in-dialog"); const dialog = page.getByRole("dialog", { name: "跨日期移动 · 合并记录", exact: true });
  await expect(dialog.getByLabel("重复记录 1 处理方式", { exact: true })).toHaveValue("keep_target");
  await page.keyboard.press("Escape"); await expect(dialog).toHaveCount(0);
  const opener = page.getByRole("button", { name: "重新打开合并确认", exact: true }); await opener.click();
  await expect(dialog).toBeVisible(); await page.keyboard.press("Escape"); await expect(opener).toBeFocused();
});
