import { existsSync } from "node:fs";
import { expect, test } from "@playwright/test";

import { VIEWPORTS, VISUAL_STORY_IDS } from "./storybookGateManifest";
import { openStory, prepareInteractiveStory, screenshotName } from "./storybookGateSupport";

for (const viewport of VIEWPORTS) {
  for (const storyId of VISUAL_STORY_IDS) {
    test(`${storyId} matches the approved ${viewport.name} baseline`, async ({ page }, testInfo) => {
      const name = screenshotName(storyId, viewport.name);
      const approvedUpdate = process.env.STORYBOOK_VISUAL_BASELINE_UPDATE === "approved";
      const updateRequested = testInfo.config.updateSnapshots === "all" || testInfo.config.updateSnapshots === "changed";
      if ((updateRequested || !existsSync(testInfo.snapshotPath(name))) && !approvedUpdate) {
        throw new Error(`Visual baseline '${name}' is missing or an update was requested without recorded approval.`);
      }

      await page.setViewportSize(viewport);
      await openStory(page, storyId);
      await prepareInteractiveStory(page, storyId);
      await expect(page).toHaveScreenshot(name, { fullPage: false });
    });
  }
}
