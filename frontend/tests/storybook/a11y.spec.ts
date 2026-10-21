import AxeBuilder from "@axe-core/playwright";
import { expect, test } from "@playwright/test";

import { RESPONSIVE_STORY_IDS, STORY_IDS, VIEWPORTS } from "./storybookGateManifest";
import { openStory, prepareInteractiveStory } from "./storybookGateSupport";

type StoryIndex = { entries: Record<string, { id: string; title: string; type: string }> };

test("Storybook manifest covers every design-system story", async ({ request }) => {
  const response = await request.get("/index.json");
  expect(response.ok()).toBe(true);
  const index = await response.json() as StoryIndex;
  const actual = Object.values(index.entries)
    .filter((entry) => entry.type === "story" && entry.title.startsWith("Design System/"))
    .map((entry) => entry.id)
    .sort();
  expect(actual).toEqual([...STORY_IDS].sort());
});

for (const viewport of VIEWPORTS) {
  const stories = viewport.width === 1280 ? STORY_IDS : RESPONSIVE_STORY_IDS;
  for (const storyId of stories) {
    test(`${storyId} has no serious accessibility violations at ${viewport.width}px`, async ({ page }) => {
      await page.setViewportSize(viewport);
      await openStory(page, storyId);
      await prepareInteractiveStory(page, storyId);
      const results = await new AxeBuilder({ page })
        .include("#storybook-root")
        .withTags(["wcag2a", "wcag2aa", "wcag21a", "wcag21aa"])
        .analyze();
      const blocking = results.violations.filter((violation) => violation.impact === "serious" || violation.impact === "critical");
      expect(blocking, blocking.map((violation) => `${violation.id}: ${violation.help}`).join("\n")).toEqual([]);
    });
  }
}
