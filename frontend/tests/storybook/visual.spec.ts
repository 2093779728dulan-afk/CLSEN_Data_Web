import { existsSync } from "node:fs";
import { expect, test } from "@playwright/test";

import { CATALOG_PRODUCT_LIST_MENU_CASES, VIEWPORTS, VISUAL_STORY_IDS } from "./storybookGateManifest";
import { openStory, prepareInteractiveStory, screenshotName } from "./storybookGateSupport";

for (const viewport of VIEWPORTS) {
  for (const menu of CATALOG_PRODUCT_LIST_MENU_CASES) {
    test(`${menu.snapshotId} matches the approved ${viewport.name} baseline`, async ({ page }, testInfo) => {
      const name = screenshotName(menu.snapshotId, viewport.name);
      const approvedUpdate = process.env.STORYBOOK_VISUAL_BASELINE_UPDATE === "approved";
      const updateRequested = testInfo.config.updateSnapshots === "all" || testInfo.config.updateSnapshots === "changed";
      if ((updateRequested || !existsSync(testInfo.snapshotPath(name))) && !approvedUpdate) {
        throw new Error(`Visual baseline '${name}' is missing or an update was requested without recorded approval.`);
      }
      await page.setViewportSize(viewport);
      await openStory(page, "pages-catalog-product-list--reference");
      const control = page.getByRole("combobox", { name: menu.label, exact: true });
      await control.click();
      const list = page.getByRole("listbox", { name: menu.label, exact: true });
      await expect(list).toBeVisible();
      const field = (await control.locator("..").locator("..").boundingBox())!;
      const popup = (await list.locator("..").boundingBox())!;
      const x = Math.max(0, Math.floor(Math.min(field.x, popup.x) - 8));
      const y = Math.max(0, Math.floor(Math.min(field.y, popup.y) - 8));
      const right = Math.min(viewport.width, Math.ceil(Math.max(field.x + field.width, popup.x + popup.width) + 8));
      const bottom = Math.min(viewport.height, Math.ceil(Math.max(field.y + field.height, popup.y + popup.height) + 8));
      await expect(page).toHaveScreenshot(name, {
        clip: { x, y, width: right - x, height: bottom - y },
        ...(approvedUpdate ? { maxDiffPixelRatio: 0 } : {}),
      });
    });
  }
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
      await expect(page).toHaveScreenshot(name, {
        // Modal overlays must be captured in the visible viewport, not a full-page scroll composite.
        fullPage: (storyId.startsWith("patterns-coverage-reconciliation--") || storyId.startsWith("patterns-trend-point-matrix--") || storyId.startsWith("patterns-product-trend-chart--") || storyId.startsWith("patterns-metric-value--") || storyId.startsWith("patterns-safe-source-reference--") || storyId.startsWith("patterns-table-header--") || storyId.startsWith("patterns-column-settings--") || storyId.startsWith("patterns-catalog-maintenance-overview--") || storyId.startsWith("patterns-catalog-unmatched-sources--") || storyId.startsWith("patterns-catalog-versions--") || storyId.startsWith("patterns-catalog-read-feedback--") || storyId.startsWith("patterns-catalog-section-editors--") || storyId.startsWith("patterns-catalog-pending-candidates--") || storyId.startsWith("patterns-catalog-import-history--") || storyId.startsWith("patterns-catalog-workbook--") || storyId.startsWith("patterns-catalog-issue-summary--") || storyId.startsWith("patterns-catalog-source-evidence--") || storyId.startsWith("patterns-catalog-identity-owners--") || storyId.startsWith("patterns-catalog-workflow-forms--") || storyId.startsWith("patterns-draft-data-table--") || storyId.startsWith("patterns-note-revision--") || storyId.startsWith("patterns-issue-review--") || storyId.startsWith("pages-advanced-review-workspace--") || storyId.startsWith("pages-workspace-shell--") || storyId.startsWith("pages-product-detail--") || storyId.startsWith("pages-product-ledger--") || storyId.startsWith("pages-session-entry--") || storyId.startsWith("pages-admin-recovery--") || storyId.startsWith("pages-admin-maintenance--") || storyId.startsWith("pages-admin-audit--") || storyId.startsWith("pages-admin-site-configuration--") || storyId.startsWith("pages-admin-accounts--") || storyId.startsWith("pages-import-evidence--") || storyId.startsWith("pages-draft-review--") || storyId.startsWith("pages-import-intake--") || storyId.startsWith("pages-batch-review--") || storyId.startsWith("pages-version-history--") || storyId.startsWith("pages-date-workbench--") || storyId.startsWith("pages-catalog-") || storyId.startsWith("pages-published-daily-ledger--") || storyId.startsWith("pages-published-day-detail--") || storyId.startsWith("pages-published-detail-ledger--")) && !/^pages-workspace-shell--navigation/.test(storyId) && !/pages-admin-accounts--(editing|saving|edit-failure|last-admin-protected)$/.test(storyId) && !storyId.includes("catalog-product-list--quick-view") && !/pages-draft-review--(publish-dialog|publication-failure)$/.test(storyId),
        // When explicitly regenerating, small changed controls must also replace their baseline.
        ...(approvedUpdate ? { maxDiffPixelRatio: 0 } : {}),
      });
    });
  }
}
