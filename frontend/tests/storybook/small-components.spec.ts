import { expect, test } from "@playwright/test";
import { openStory } from "./storybookGateSupport";

for (const width of [1280, 390]) {
  test(`shared controls filter, paginate and recover at ${width}px`, async ({ page }, testInfo) => {
    await page.setViewportSize({ width, height: 900 });
    await openStory(page, "design-system-form-controls--review-controls");
    const list = page.getByRole("list", { name: "示例商品结果" });
    await expect(list.getByRole("listitem")).toHaveCount(2);
    await expect(page.getByRole("button", { name: "上一页" })).toBeDisabled();
    await page.getByRole("button", { name: "下一页" }).click();
    await expect(list).toContainText("DEMO-03");
    await page.getByRole("button", { name: "下一页" }).click();
    await expect(list).toContainText("DEMO-05");
    await expect(page.getByRole("button", { name: "下一页" })).toBeDisabled();
    await page.getByRole("button", { name: "上一页" }).click();
    await expect(list).toContainText("DEMO-03");
    const pending = page.getByRole("checkbox", { name: "仅看待处理示例" });
    await pending.focus();
    await page.keyboard.press("Space");
    await expect(pending).toBeChecked();
    await expect(page.getByLabel("第 1 / 2 页")).toBeVisible();
    const search = page.getByRole("searchbox", { name: "搜索示例商品" });
    await search.fill("暖灰");
    await page.getByRole("button", { name: "清空搜索", exact: true }).click();
    await expect(search).toHaveValue("");
    await expect(search).toBeFocused();
    await expect(pending).toBeChecked();
    await search.fill("暖灰");
    await page.getByRole("button", { name: "移除搜索条件" }).click();
    await expect(search).toBeFocused();
    await expect(pending).toBeChecked();
    await page.getByRole("button", { name: "移除待处理筛选" }).click();
    await expect(pending).not.toBeChecked();
    await expect(search).toBeFocused();
    await pending.check();
    await page.getByRole("combobox", { name: "示例处理状态" }).selectOption("complete");
    await expect(page.getByRole("status")).toContainText("没有匹配");
    await page.getByRole("button", { name: "重置筛选" }).click();
    await expect(pending).not.toBeChecked();
    await page.getByRole("searchbox", { name: "搜索示例商品" }).fill("衬衫");
    await expect(page.getByText("共 3 个示例商品")).toBeVisible();
    await page.screenshot({ path: testInfo.outputPath(`controls-${width}-active-filters.png`) });
    await page.getByRole("button", { name: "下一页" }).click();
    await expect(list).toContainText("DEMO-06");
    await page.getByRole("button", { name: "重置筛选" }).click();
    const help = page.getByRole("button", { name: "筛选说明" });
    await help.focus();
    await expect(page.getByRole("tooltip")).toContainText("搜索与处理状态");
    await page.screenshot({ path: testInfo.outputPath(`controls-${width}-tooltip.png`) });
    await page.keyboard.press("Escape");
    await expect(page.getByRole("tooltip")).toHaveCount(0);
    await expect(help).toBeFocused();
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
    await help.blur();
    await page.screenshot({ path: testInfo.outputPath(`controls-${width}.png`) });
  });
}

test("form states, disabled checkbox, mixed state and tooltip motion retain native behavior", async ({ page }) => {
  await openStory(page, "design-system-form-controls--field-states");
  const source = page.getByRole("textbox", { name: "来源编号" });
  await source.focus();
  await expect(source).toBeFocused();
  await expect(source).toHaveAttribute("readonly", "");
  await expect(page.getByRole("combobox", { name: "不可用的处理状态" })).toBeDisabled();
  const invalid = page.getByLabel("统计月份", { exact: true });
  await expect(invalid).toHaveAttribute("aria-invalid", "true");
  const errorBorder = await invalid.evaluate(element => getComputedStyle(element).borderColor);
  await invalid.hover();
  expect(await invalid.evaluate(element => getComputedStyle(element).borderColor)).toBe(errorBorder);
  await openStory(page, "design-system-selection-and-navigation--selection-states");
  await expect(page.getByRole("checkbox", { name: "当前账号不可更改此选项" })).toBeDisabled();
  const checkbox = page.getByRole("checkbox", { name: "包含缺货商品" });
  await checkbox.evaluate((input: HTMLInputElement) => { input.indeterminate = true; });
  expect(await checkbox.locator("..").locator("svg").last().evaluate(element => getComputedStyle(element).opacity)).toBe("1");
  await checkbox.focus();
  await page.keyboard.press("Space");
  expect(await checkbox.evaluate((input: HTMLInputElement) => input.indeterminate)).toBe(false);
  await page.emulateMedia({ forcedColors: "active" });
  expect(await checkbox.evaluate(element => getComputedStyle(element).appearance)).toBe("auto");
  await page.emulateMedia({ forcedColors: "none" });
  await openStory(page, "design-system-form-controls--review-controls");
  for (const motion of ["no-preference", "reduce"] as const) {
    await page.emulateMedia({ reducedMotion: motion });
    const help = page.getByRole("button", { name: "筛选说明" });
    await help.focus();
    const tooltip = page.getByRole("tooltip");
    await expect(page.getByRole("tooltip")).toBeVisible();
    const animation = await tooltip.evaluate(element => getComputedStyle(element).animationName);
    expect(motion === "reduce" ? animation === "none" : animation.includes("tooltip-in")).toBe(true);
    await page.keyboard.press("Escape");
    await expect(page.getByRole("tooltip")).toHaveCount(0);
    await help.blur();
  }
});


test("search input owns a single group focus indicator, including catalog and forced colors", async ({ page }, testInfo) => {
  await page.setViewportSize({ width: 390, height: 844 });
  for (const [story, label] of [
    ["pages-catalog-import-review--reference", "搜索当前审核项"],
    ["design-system-form-controls--review-controls", "搜索示例商品"],
  ]) {
    await openStory(page, story!);
    const search = page.getByRole("searchbox", { name: label! });
    const group = search.locator("..");
    await search.focus();
    await group.screenshot({ path: testInfo.outputPath(`${story}-focus.png`) });
    expect(await search.evaluate(element => getComputedStyle(element).outlineStyle)).toBe("none");
    expect(await search.evaluate(element => getComputedStyle(element).boxShadow)).toBe("none");
    expect(await group.evaluate(element => getComputedStyle(element).boxShadow)).not.toBe("none");
    await search.fill("DEMO");
    await page.getByRole("button", { name: "清空搜索", exact: true }).click();
    await expect(search).toHaveValue("");
    await expect(search).toBeFocused();
    await page.emulateMedia({ forcedColors: "active" });
    expect(await search.evaluate(element => getComputedStyle(element).outlineStyle)).toBe("none");
    expect(await group.evaluate(element => getComputedStyle(element).outlineStyle)).toBe("solid");
    await group.screenshot({ path: testInfo.outputPath(`${story}-forced-colors-focus.png`) });
    await page.emulateMedia({ forcedColors: "none" });
  }
});


for (const width of [1280, 390]) {
test(`global defaults respect native interaction and component state ownership at ${width}px`, async ({ page }, testInfo) => {
  await page.setViewportSize({ width, height: 900 });
  await openStory(page, "design-system-form-controls--global-defaults");
  const native = page.getByRole("textbox", { name: "原生名称字段" });
  await native.fill("示例名称");
  await expect(native).toHaveValue("示例名称");
  await page.getByRole("combobox", { name: "原生处理状态" }).selectOption("done");
  const readonly = page.getByRole("textbox", { name: "只读来源" });
  await readonly.focus();
  await readonly.press("End");
  await readonly.press("a");
  await expect(readonly).toHaveValue("DEMO-2026");
  const nested = page.getByRole("textbox", { name: "旧表单中的公共输入" });
  const invalid = page.getByRole("textbox", { name: "组件错误状态" });
  expect(await nested.evaluate(element => getComputedStyle(element).height)).toBe(await invalid.evaluate(element => getComputedStyle(element).height));
  expect(await nested.evaluate(element => getComputedStyle(element).borderRadius)).toBe(await invalid.evaluate(element => getComputedStyle(element).borderRadius));
  expect(await invalid.evaluate(element => getComputedStyle(element).borderColor)).not.toBe(await nested.evaluate(element => getComputedStyle(element).borderColor));
  expect(await readonly.evaluate(element => getComputedStyle(element).backgroundColor)).not.toBe(await native.evaluate(element => getComputedStyle(element).backgroundColor));
  const nativeInvalid = page.getByRole("textbox", { name: "原生错误状态" });
  expect(await nativeInvalid.evaluate(element => getComputedStyle(element).borderColor)).toBe(await invalid.evaluate(element => getComputedStyle(element).borderColor));
  const checkbox = page.getByRole("checkbox", { name: "保留原生勾选行为" });
  await checkbox.focus();
  await checkbox.press("Space");
  await expect(checkbox).toBeChecked();
  const shared = page.getByRole("button", { name: "公共操作", exact: true });
  await shared.focus();
  expect(await shared.evaluate(element => element.matches(":focus-visible"))).toBe(true);
  expect(await shared.evaluate(element => getComputedStyle(element).outlineWidth)).toBe("2px");
  expect(await shared.evaluate(element => getComputedStyle(element).boxShadow)).not.toBe("none");
  await expect(page.getByRole("button", { name: "暂不可用" })).toBeDisabled();
  const nativeButton = page.getByRole("button", { name: "原生操作", exact: true });
  await nativeButton.focus();
  expect(await nativeButton.evaluate(element => getComputedStyle(element).outlineWidth)).toBe("2px");
  const summary = page.getByText("操作说明", { exact: true });
  await summary.focus();
  expect(await summary.evaluate(element => getComputedStyle(element).outlineOffset)).toBe("2px");
  await summary.press("Enter");
  await expect(page.getByText("基础样式提供默认值，公共组件管理自己的焦点、禁用和错误状态。")).toBeVisible();
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
  await page.screenshot({ path: testInfo.outputPath("global-controls-keyboard.png"), fullPage: true });
  await page.emulateMedia({ reducedMotion: "no-preference" });
  const errorBorder = await nativeInvalid.evaluate(element => getComputedStyle(element).borderColor);
  await nativeInvalid.hover();
  expect(await nativeInvalid.evaluate(element => getComputedStyle(element).borderColor)).toBe(errorBorder);
  await page.emulateMedia({ reducedMotion: "reduce" });
  expect(await native.evaluate(element => getComputedStyle(element).transitionDuration)).toBe("0s");
  await page.emulateMedia({ forcedColors: "active" });
  await summary.focus();
  expect(await summary.evaluate(element => getComputedStyle(element).outlineStyle)).toBe("solid");
  expect(await summary.evaluate(element => getComputedStyle(element).outlineWidth)).toBe("2px");
  await page.screenshot({ path: testInfo.outputPath("global-controls-forced-colors.png") });
});
}
