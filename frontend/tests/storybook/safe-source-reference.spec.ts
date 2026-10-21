import { expect, test } from "@playwright/test";
import { SAFE_SOURCE_REFERENCE_STORY_IDS } from "./storybookGateManifest";
import { openStory } from "./storybookGateSupport";

for (const width of [1280, 390]) {
  test(`source preview, digest and safety states survive reload at ${width}px`, async ({ page }) => {
    await page.setViewportSize({ width, height: 900 });
    const requests: string[] = [];
    await page.route(url => url.pathname.startsWith("/api/"), route => {
      requests.push(route.request().url());
      throw new Error("Standalone fictional sources must not request an API");
    });
    for (const storyId of SAFE_SOURCE_REFERENCE_STORY_IDS) {
      await openStory(page, storyId);
      const references = page.locator(".safe-source-ref");
      await expect(references.first()).toBeVisible();
      for (const digest of await page.getByLabel("来源摘要后八位", { exact: true }).all()) await expect(digest).toHaveText("12345678");
      if (/--(structural-characters|combined)$/.test(storyId)) {
        await expect(references).toContainText("[含危险字符的来源]");
        expect(await references.textContent()).not.toContain("fictional-source");
      }
      if (/--(unsafe|structural-characters|combined)$/.test(storyId)) await expect(references.getByText("含危险字符", { exact: true })).toBeVisible();
      if (/--(truncated|combined)$/.test(storyId)) await expect(references.getByText("已截断", { exact: true })).toBeVisible();
      expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
      expect(await references.evaluateAll(elements => elements.every(element => element.scrollWidth <= element.clientWidth))).toBe(true);
      await page.reload(); await expect(references.first()).toBeVisible();
      await expect(page.locator("output")).toHaveCount(0);
    }
    expect(requests).toEqual([]);
  });
}
