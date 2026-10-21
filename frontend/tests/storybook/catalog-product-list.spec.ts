import { expect, test } from "@playwright/test";
import { openStory } from "./storybookGateSupport";

test("catalog pages enter on pathname changes without replaying during filtering", async ({ page }, testInfo) => {
  await openStory(page, "pages-catalog-product-list--reference");
  await page.emulateMedia({ reducedMotion: "no-preference" });
  await page.reload();
  const nav = page.getByRole("navigation", { name: "商品主档导航" });
  await expect(page.getByRole("searchbox", { name: "查找商品" })).toBeVisible();
  const samplesPromise = page.locator("#main-content").evaluate(async main => {
    const samples: Array<{ opacity: number; y: number }> = [];
    for (let i = 0; i < 24; i++) {
      await new Promise<void>(resolve => requestAnimationFrame(() => resolve()));
      const section = main.querySelector("h2")?.parentElement;
      const container = section?.parentElement;
      if (container) {
        const style = getComputedStyle(container);
        samples.push({ opacity: Number(style.opacity), y: style.transform === "none" ? 0 : new DOMMatrixReadOnly(style.transform).m42 });
      }
    }
    return samples;
  });
  await nav.getByRole("link", { name: "目录版本", exact: true }).click();
  await expect(page.getByRole("heading", { name: "目录版本", exact: true })).toBeVisible();
  const samples = await samplesPromise;
  expect(samples.some(s => s.opacity > 0 && s.opacity < 1 && s.y > 0 && s.y < 8)).toBe(true);
  const content = page.getByRole("heading", { name: "目录版本", exact: true }).locator("../..");
  await expect(content).toHaveCSS("opacity", "1");
  await expect(content).toHaveCSS("transform", "none");
  await testInfo.attach("page-motion-samples", { body: JSON.stringify(samples), contentType: "application/json" });
  await nav.getByRole("link", { name: "商品", exact: true }).click();
  const search = page.getByRole("searchbox", { name: "查找商品" });
  const homeContent = page.getByRole("region", { name: "商品主档列表" }).locator("..");
  await expect(homeContent).toHaveCSS("opacity", "1");
  await search.fill("DEMO-01");
  await expect(homeContent).toHaveCSS("opacity", "1");
  await expect(homeContent).toHaveCSS("transform", "none");
  await expect(page.getByRole("article")).toHaveCount(1);
  await page.emulateMedia({ reducedMotion: "reduce" });
  await nav.getByRole("link", { name: "待处理", exact: true }).click();
  const reduced = page.getByRole("heading", { name: "待处理", exact: true }).locator("../..");
  await expect(reduced).toHaveCSS("opacity", "1");
  await expect(reduced).toHaveCSS("transform", "none");
});

for (const width of [1280, 320]) {
  test(`catalog route navigation preserves links, focus and scroll at ${width}px`, async ({ page }, testInfo) => {
    await page.setViewportSize({ width, height: 900 });
    await openStory(page, "pages-catalog-product-list--reference");
    const nav = page.getByRole("navigation", { name: "商品主档导航" });
    const home = nav.getByRole("link", { name: "商品", exact: true });
    await expect(home).toHaveAttribute("href", "/catalog");
    await expect(home).toHaveAttribute("aria-current", "page");
    await expect(nav.getByRole("link")).toHaveCount(4);
    await page.getByRole("searchbox", { name: "查找商品" }).fill("DEMO-01");
    const pending = nav.getByRole("link", { name: "待处理", exact: true });
    await home.focus();
    await home.press("Tab");
    await expect(pending).toBeFocused();
    await expect(home).toHaveAttribute("aria-current", "page");
    await pending.press("Enter");
    await expect(pending).toHaveAttribute("aria-current", "page");
    await expect(page.getByRole("heading", { name: "待处理", exact: true })).toBeVisible();
    await expect(pending).toBeFocused();
    for (const label of ["目录版本", "批量维护"]) {
      const link = nav.getByRole("link", { name: label, exact: true });
      await link.click();
      await expect(link).toHaveAttribute("aria-current", "page");
      await expect(page.getByRole("heading", { name: label, exact: true })).toBeVisible();
    }
    await home.click();
    await expect(page.getByRole("searchbox", { name: "查找商品" })).toHaveValue("DEMO-01");
    if (width === 320) {
      const last = nav.getByRole("link", { name: "批量维护", exact: true });
      await last.focus();
      const visible = await last.evaluate(el => {
        const link = el.getBoundingClientRect(); const container = el.parentElement!.getBoundingClientRect();
        return link.left >= container.left && link.right <= container.right;
      });
      expect(visible).toBe(true);
      expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
      await home.focus();
    }
    await page.getByRole("button", { name: "重置筛选" }).click();
    await page.screenshot({ path: testInfo.outputPath(`catalog-navigation-${width}.png`), fullPage: true });
    await openStory(page, "pages-catalog-product-list--read-only");
    await expect(nav.getByRole("link")).toHaveCount(1);
    await expect(nav.getByRole("link", { name: "商品", exact: true })).toHaveAttribute("aria-current", "page");
  });
}

test("catalog navigation glides its shared underline and respects reduced motion", async ({ page }) => {
  await openStory(page, "pages-catalog-product-list--reference");
  await page.emulateMedia({ reducedMotion: "no-preference" });
  // Motion's hook reads the preference on mount; the standard helper starts reduced.
  await page.reload();
  const nav = page.getByRole("navigation", { name: "商品主档导航" });
  const currentIndicator = nav.locator('[aria-current="page"] span[aria-hidden="true"]');
  const start = (await currentIndicator.boundingBox())!.x;
  const movement = nav.evaluate(async el => {
    const positions: number[] = [];
    for (let i = 0; i < 20; i++) {
      await new Promise<void>(resolve => requestAnimationFrame(() => resolve()));
      const indicator = el.querySelector('[aria-current="page"] span[aria-hidden="true"]');
      if (indicator) positions.push(indicator.getBoundingClientRect().x);
    }
    return positions;
  });
  await nav.getByRole("link", { name: "目录版本", exact: true }).click();
  const positions = await movement;
  const target = (await currentIndicator.boundingBox())!.x;
  expect(positions.some(x => x > start + 1 && x < target - 1)).toBe(true);
  await page.emulateMedia({ reducedMotion: "reduce" });
  await nav.getByRole("link", { name: "商品", exact: true }).click();
  await expect(nav.getByRole("link", { name: "商品", exact: true })).toHaveAttribute("aria-current", "page");
  // Reduced motion moves directly to the active link without a transform animation.
  await expect(currentIndicator).toHaveCSS("transform", "none");
  await expect(nav.getByRole("link", { name: "商品", exact: true })).toHaveCSS("transition-property", "none");
});

for (const width of [1280, 390]) {
  test(`catalog sample composes shared filters, paging and table scrolling at ${width}px`, async ({ page }, testInfo) => {
    await page.setViewportSize({ width, height: 900 });
    await openStory(page, "pages-catalog-product-list--reference");
    const region = page.getByRole("region", { name: "商品主档列表" });
    const search = region.getByRole("searchbox", { name: "查找商品" });
    await expect(region.getByRole("article")).toHaveCount(12);
    await region.getByRole("button", { name: "下一页" }).click();
    await expect(region.getByLabel("第 2 / 2 页")).toBeVisible();
    await region.getByRole("combobox", { name: "商品状态" }).click();
    await page.getByRole("listbox", { name: "商品状态" }).getByRole("option", { name: "已停用", exact: true }).click();
    await expect(region.getByLabel("第 1 / 1 页")).toBeVisible();
    await expect(region.getByRole("article")).toHaveCount(5);
    await search.fill("不匹配的示例");
    await expect(region.getByRole("heading", { name: "没有符合条件的商品" })).toBeVisible();
    await region.getByRole("button", { name: "重置筛选" }).click();
    await expect(search).toBeFocused();
    await region.getByRole("button", { name: "批量表格" }).click();
    const table = region.getByRole("table", { name: "商品主档批量表格" });
    await expect(table.getByText("已停用", { exact: true })).toHaveCount(3);
    if (width === 390) {
      const scroller = table.locator("..");
      await scroller.focus();
      await scroller.press("ArrowRight");
      await expect.poll(() => scroller.evaluate(element => element.scrollLeft)).toBeGreaterThan(0);
    }
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
    await page.screenshot({ path: testInfo.outputPath(`catalog-reference-${width}.png`), fullPage: true });
  });
}

test("catalog samples separate setup, empty, pending, failure recovery and viewer navigation", async ({ page }) => {
  for (const [id, label] of [
    ["uninitialized", "商品主档尚未初始化"],
    ["empty", "当前主档尚无商品"],
    ["no-results", "没有符合条件的商品"],
  ]) {
    await openStory(page, `pages-catalog-product-list--${id}`);
    await expect(page.getByRole("heading", { name: label! })).toBeVisible();
  }
  await openStory(page, "pages-catalog-product-list--loading");
  await expect(page.getByRole("status", { name: "正在读取商品主档" })).toBeVisible();
  await expect(page.getByRole("button", { name: "正在读取主档" })).toBeDisabled();
  await openStory(page, "pages-catalog-product-list--read-failure");
  await expect(page.getByRole("alert")).toContainText("连接暂时不可用");
  await page.getByRole("button", { name: "重新读取", exact: true }).click();
  await expect(page.getByRole("searchbox", { name: "查找商品" })).toBeVisible();
  await openStory(page, "pages-catalog-product-list--read-only");
  await expect(page.getByRole("navigation", { name: "商品主档导航" }).getByRole("link")).toHaveCount(1);
  await expect(page.getByRole("region", { name: "商品主档列表" }).getByText("只读", { exact: true })).toBeVisible();
});

for (const width of [1280, 390, 320]) {
  test(`glide select keeps keyboard, outside focus and viewport boundaries at ${width}px`, async ({ page }, testInfo) => {
    await page.setViewportSize({ width, height: 900 });
    await openStory(page, "pages-catalog-product-list--reference");
    const control = page.getByRole("combobox", { name: "商品状态", exact: true });
    const search = page.getByRole("searchbox", { name: "查找商品" });
    await control.focus();
    await page.keyboard.press("ArrowDown");
    const list = page.getByRole("listbox", { name: "商品状态", exact: true });
    await expect(list).toBeVisible();
    await expect(control).toBeFocused();
    await expect(control).toHaveAttribute("aria-activedescendant", await list.getByRole("option", { name: "全部状态" }).getAttribute("id") as string);
    await page.keyboard.press("End");
    await page.keyboard.press("Enter");
    await expect(control).toHaveText("已停用");
    await expect(page.getByRole("article")).toHaveCount(5);
    await expect(control).toBeFocused();
    await control.press("Space");
    await control.press("Home");
    await control.press("Enter");
    await expect(page.getByRole("article")).toHaveCount(12);
    await control.press("ArrowUp");
    await control.press("ArrowDown");
    await control.press("Escape");
    await expect(control).toHaveText("全部状态");
    await expect(control).toBeFocused();
    await control.click();
    await search.click();
    await expect(list).toHaveCount(0);
    await expect(search).toBeFocused();
    await control.press("Enter");
    await control.press("Tab");
    await expect(list).toHaveCount(0);
    await expect(page.getByRole("combobox", { name: "排序", exact: true })).toBeFocused();

    // A short viewport puts the trigger near its lower edge, forcing an actual upward flip.
    await page.setViewportSize({ width, height: 360 });
    const before = await control.boundingBox();
    await page.evaluate(bottom => window.scrollTo(0, Math.max(0, bottom - 344)), before!.y + before!.height);
    await control.click();
    await expect(list).toBeVisible();
    await expect(list.locator("..")).toHaveAttribute("data-side", "top");
    const box = (await list.locator("..").boundingBox())!;
    expect(box.x).toBeGreaterThanOrEqual(8);
    expect(box.x + box.width).toBeLessThanOrEqual(width - 8);
    expect(box.y).toBeGreaterThanOrEqual(8);
    expect(box.y + box.height).toBeLessThanOrEqual(352);
    expect(await list.evaluate(element => element.parentElement?.parentElement?.parentElement === document.body)).toBe(true);
    expect(await list.getByRole("option", { name: "已停用" }).evaluate(element => {
      const r = element.getBoundingClientRect();
      return element.contains(document.elementFromPoint(r.x + r.width / 2, r.y + r.height / 2));
    })).toBe(true);
    await page.screenshot({ path: testInfo.outputPath(`glide-select-${width}-open.png`) });
    // The top of a row must select that row, not its predecessor or menu padding.
    await list.getByRole("option", { name: "已停用", exact: true }).click({ position: { x: 20, y: 1 } });
    await expect(control).toHaveText("已停用");
    await expect(page.getByRole("article")).toHaveCount(5);
    await expect(list).toHaveCount(0);
    await page.getByRole("button", { name: "重置筛选" }).click();
    await expect(control).toHaveText("全部状态");
    await expect(search).toBeFocused();
  });
}

test("glide highlight animates between rows and remembers pointer leave/re-entry", async ({ page }, testInfo) => {
  await openStory(page, "pages-catalog-product-list--reference");
  await page.emulateMedia({ reducedMotion: "no-preference" });
  const control = page.getByRole("combobox", { name: "商品状态", exact: true });
  await control.click();
  const list = page.getByRole("listbox", { name: "商品状态", exact: true });
  const menu = list.locator("..");
  const pill = list.locator(".glide-select__pill");
  await expect.poll(() => menu.evaluate(el => getComputedStyle(el).opacity)).toBe("1");
  expect(await menu.evaluate(el => getComputedStyle(el).transitionDuration)).toBe("0.18s, 0.18s");
  const movement = pill.evaluate(async el => {
    const samples: number[] = [];
    for (let i = 0; i < 16; i++) {
      await new Promise<void>(resolve => requestAnimationFrame(() => resolve()));
      samples.push(new DOMMatrixReadOnly(getComputedStyle(el).transform).m42);
    }
    return samples;
  });
  await list.getByRole("option", { name: "已停用", exact: true }).hover();
  expect(await pill.evaluate(el => getComputedStyle(el).transitionDuration)).toBe("0.22s, 0.15s");
  const samples = await movement;
  expect(samples.some(y => y > 0 && y < 62)).toBe(true);
  await expect.poll(() => pill.evaluate(el => new DOMMatrixReadOnly(getComputedStyle(el).transform).m42)).toBe(62);
  await page.getByRole("heading", { name: "当前批准主档" }).hover();
  await expect(pill).toHaveCSS("opacity", "1");
  expect(await pill.evaluate(el => new DOMMatrixReadOnly(getComputedStyle(el).transform).m42)).toBe(62);
  await list.getByRole("option", { name: "已启用", exact: true }).hover();
  await expect.poll(() => pill.evaluate(el => new DOMMatrixReadOnly(getComputedStyle(el).transform).m42)).toBe(31);
  await expect(control).toHaveText("全部状态");
  await page.screenshot({ path: testInfo.outputPath("glide-highlight.png") });
  await control.press("Escape");
  await control.click();
  await expect(list.getByRole("option", { name: "全部状态", exact: true })).toHaveAttribute("aria-selected", "true");
  await control.press("Escape");
  await page.emulateMedia({ reducedMotion: "reduce" });
  await control.click();
  await expect(pill).toHaveCSS("transition-property", "none");
  await expect(menu).toHaveCSS("transition-property", "none");
});

test("glide select supports touch selection without changing the original filter data", async ({ browser }, testInfo) => {
  const context = await browser.newContext({ viewport: { width: 390, height: 844 }, hasTouch: true, locale: "zh-CN" });
  try {
    const page = await context.newPage();
    await page.goto("http://127.0.0.1:17641/iframe.html?id=pages-catalog-product-list--reference&viewMode=story");
    const control = page.getByRole("combobox", { name: "商品状态", exact: true });
    await control.tap();
    const list = page.getByRole("listbox", { name: "商品状态", exact: true });
    await expect(list.getByRole("option")).toHaveText(["全部状态", "已启用", "已停用"]);
    await list.getByRole("option", { name: "已停用", exact: true }).tap();
    await expect(control).toHaveText("已停用");
    await expect(page.getByRole("article")).toHaveCount(5);
    await expect(list).toHaveCount(0);
    await page.getByRole("combobox", { name: "排序", exact: true }).tap();
    await page.getByRole("listbox", { name: "排序" }).getByRole("option", { name: "商品名称", exact: true }).tap();
    await expect(page.getByRole("combobox", { name: "排序", exact: true })).toHaveText("商品名称");
    await page.getByRole("button", { name: "重置筛选" }).tap();
    await expect(control).toHaveText("全部状态");
    await expect(page.getByRole("combobox", { name: "排序", exact: true })).toHaveText("款式编号");
    await page.screenshot({ path: testInfo.outputPath("glide-touch.png") });
  } finally { await context.close(); }
});
