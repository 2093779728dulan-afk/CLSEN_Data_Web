import { expect, test } from "@playwright/test";
import { openStory } from "./storybookGateSupport";

async function sparkSamples(page: import("@playwright/test").Page) {
  return page.locator("canvas").evaluate(async element => {
    const canvas = element as HTMLCanvasElement;
    const samples: string[][] = [];
    for (let frame = 0; frame < 28; frame++) {
      await new Promise<void>(resolve => requestAnimationFrame(() => resolve()));
      const image = canvas.getContext("2d")!.getImageData(0, 0, canvas.width, canvas.height).data;
      const colors = new Set<string>();
      for (let i = 0; i < image.length; i += 4) if (image[i + 3]! > 180) colors.add(`${image[i]},${image[i + 1]},${image[i + 2]}`);
      samples.push([...colors]);
    }
    return samples;
  });
}

test("colored sparks preserve pointer and keyboard actions, clear and respect reduced motion", async ({ page }, testInfo) => {
  await openStory(page, "design-system-interaction-feedback--click-spark-states");
  await page.emulateMedia({ reducedMotion: "no-preference" });
  await page.reload();
  const button = page.getByRole("button", { name: "确认示例操作" });
  await expect(button).toBeVisible();
  const samplePromise = sparkSamples(page);
  await button.click();
  await expect(page.getByText("已执行 1 次", { exact: true })).toBeVisible();
  const samples = await samplePromise;
  expect(samples.some(colors => ["23,105,170", "40,122,85", "148,107,22", "116,82,165"].every(color => colors.includes(color)))).toBe(true);
  await testInfo.attach("spark-pixel-samples", { body: JSON.stringify(samples), contentType: "application/json" });
  const keyboardSample = sparkSamples(page);
  await button.press("Enter");
  await expect(page.getByText("已执行 2 次", { exact: true })).toBeVisible();
  expect((await keyboardSample).some(colors => colors.length > 0)).toBe(true);
  await expect(page.getByRole("button", { name: "不可操作" })).toBeDisabled();
  await expect(page.getByRole("button", { name: "正在保存", exact: true })).toBeDisabled();
  await page.getByRole("button", { name: "无火花操作" }).click();
  await expect(page.getByText("已执行 3 次", { exact: true })).toBeVisible();
  expect((await sparkSamples(page)).every(colors => colors.length === 0)).toBe(true);
  await page.emulateMedia({ reducedMotion: "reduce" });
  await button.click();
  await expect(page.getByText("已执行 4 次", { exact: true })).toBeVisible();
  await expect(page.locator("canvas")).toBeHidden();
  expect((await sparkSamples(page)).every(colors => colors.length === 0)).toBe(true);
});

for (const width of [1280, 390]) {
  test(`catalog operations navigation and workflow preserve behavior at ${width}px`, async ({ page }, testInfo) => {
    await page.setViewportSize({ width, height: 900 });
    await openStory(page, "pages-catalog-operations--unmatched");
    await expect(page.getByText("DEMO-1-Light-Blue-XL")).toBeVisible();
    await expect(page.getByRole("link", { name: "继续审核", exact: true })).toHaveAttribute("href", "/catalog/imports/901");
    await page.getByRole("button", { name: "下一页", exact: true }).click();
    await expect(page.getByText("第 2 / 2 页", { exact: true })).toBeVisible();
    await page.getByRole("link", { name: "生成或继续审核候选" }).click();
    await expect(page.getByRole("heading", { name: "批量维护", exact: true })).toBeVisible();
    await expect(page.getByRole("button", { name: "上传并进入审核" })).toBeDisabled();
    await page.getByLabel("上传已修改的兼容 XLSX").setInputFiles({ name: "fictional.xlsx", mimeType: "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", buffer: Buffer.from("fictional story file; no real upload") });
    await page.getByRole("button", { name: "上传并进入审核" }).click();
    await expect(page.getByRole("heading", { name: "虚构导航结果" })).toBeVisible();
    await page.getByRole("link", { name: "返回批量维护" }).click();
    await page.getByRole("button", { name: "开始在线审核" }).click();
    await expect(page.getByRole("heading", { name: "虚构导航结果" })).toBeVisible();
    await page.getByRole("navigation", { name: "商品主档导航" }).getByRole("link", { name: "目录版本", exact: true }).click();
    await expect(page.getByRole("table")).toBeVisible();
    await expect(page.getByText("V4", { exact: true })).toBeVisible();
    await page.getByRole("button", { name: "重新读取版本" }).click();
    await expect(page.getByRole("table")).toBeVisible();
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
    await page.screenshot({ path: testInfo.outputPath(`catalog-versions-${width}.png`), fullPage: true });
  });
}

test("page recovery and candidate prerequisites are explicit", async ({ page }) => {
  await openStory(page, "pages-catalog-operations--versions-failure");
  await expect(page.getByRole("alert")).toBeVisible();
  await page.getByRole("button", { name: "重新读取", exact: true }).click();
  await expect(page.getByText("V4", { exact: true })).toBeVisible();
  await openStory(page, "pages-catalog-operations--pending-failure");
  await expect(page.getByText("DEMO-1-Light-Blue-XL")).toBeVisible();
  await page.getByRole("button", { name: "重新读取", exact: true }).click();
  await expect(page.getByText("审核批次 #901", { exact: true })).toBeVisible();
  await openStory(page, "pages-catalog-operations--uninitialized");
  await expect(page.getByRole("button", { name: "生成候选", exact: true })).toBeDisabled();
  await openStory(page, "pages-catalog-operations--generation-failed");
  await page.getByRole("button", { name: "恢复生成" }).click();
  await expect(page.getByRole("button", { name: "开始在线审核" })).toBeEnabled();
  await openStory(page, "pages-catalog-operations--stale-candidate");
  await expect(page.getByRole("button", { name: "开始在线审核" })).toBeDisabled();
  await page.getByRole("button", { name: "重新生成候选" }).click();
  await expect(page.getByRole("button", { name: "开始在线审核" })).toBeEnabled();
  await openStory(page, "pages-catalog-operations--no-publication-evidence");
  await expect(page.getByRole("heading", { name: "当前范围没有可用的发布依据" })).toBeVisible();
  await expect(page.getByText("当前范围没有未归属来源。", { exact: true })).toHaveCount(0);
  await openStory(page, "pages-catalog-operations--unmatched-empty");
  await expect(page.getByText("当前范围没有未归属来源。", { exact: true })).toBeVisible();
});
