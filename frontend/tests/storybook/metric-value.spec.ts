import { expect, test } from "@playwright/test";
import { METRIC_VALUE_STORY_IDS } from "./storybookGateManifest";
import { openStory } from "./storybookGateSupport";

for (const width of [1280, 390]) {
  test(`metric precision, availability, partial coverage and reload at ${width}px`, async ({ page }) => {
    await page.setViewportSize({ width, height: 900 });
    const requests: string[] = [];
    await page.route(url => url.pathname.startsWith("/api/"), route => {
      requests.push(route.request().url()); throw new Error("Fictional metric samples must not request API data");
    });
    for (const storyId of METRIC_VALUE_STORY_IDS) {
      await openStory(page, storyId);
      const samples = page.getByRole("list", { name: "经营指标示例", exact: true });
      await expect(samples).toBeVisible();
      if (storyId.endsWith("--reference")) {
        await expect(samples.getByText("1,234.50", { exact: true })).toBeVisible();
        await expect(samples.getByText("0.200000", { exact: true })).toBeVisible();
      }
      if (storyId.endsWith("--zero-values")) {
        await expect(samples.getByText("0.00", { exact: true })).toBeVisible();
        await expect(samples.getByText("0.000000", { exact: true })).toBeVisible();
        await expect(samples.getByText("已观测为零", { exact: true })).toHaveCount(5);
        await expect(samples.getByText("无报表", { exact: true })).toHaveCount(0);
      }
      if (storyId.endsWith("--missing-report")) {
        await expect(samples.getByText("无报表", { exact: true })).toHaveCount(5);
        await expect(samples.getByText("已发布 0/31 天", { exact: true })).toHaveCount(5);
        await expect(samples.getByText("0", { exact: true })).toHaveCount(0);
      }
      if (storyId.endsWith("--undefined-denominator")) {
        await expect(samples.getByText("分母为 0", { exact: true })).toBeVisible();
        await expect(samples.getByText("转化率未定义", { exact: true })).toBeVisible();
        await expect(samples.getByText("0.00%", { exact: true })).toHaveCount(0);
      }
      if (storyId.endsWith("--partial")) {
        await expect(samples.getByText("部分数据", { exact: true })).toHaveCount(5);
        await expect(samples.getByLabel("已发布 30/31 天", { exact: true })).toHaveCount(5);
      }
      if (storyId.endsWith("--compact")) {
        await expect(samples.getByText("部分数据", { exact: true })).toHaveCount(5);
        await expect(samples.getByText("已观测为零", { exact: true })).toHaveCount(0);
        await expect(samples.getByLabel("已发布 30/31 天", { exact: true })).toHaveCount(0);
      }
      if (storyId.endsWith("--percentage")) await expect(samples.getByText("20.00%", { exact: true })).toBeVisible();
      if (storyId.endsWith("--long-values")) {
        await expect(samples.getByText("123,456,789,012,345,678,901,234,567,890.12", { exact: true })).toBeVisible();
        await expect(samples.getByText("-1,234.50", { exact: true })).toBeVisible();
      }
      expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
      await page.reload(); await expect(samples).toBeVisible();
    }
    expect(requests).toEqual([]);
  });
}
