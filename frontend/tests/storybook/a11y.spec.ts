import AxeBuilder from "@axe-core/playwright";
import { expect, test } from "@playwright/test";
import { VISUAL_STORY_IDS } from "./storybookGateManifest";

import { COVERAGE_RECONCILIATION_STORY_IDS, LEDGER_METRIC_HELP_STORY_IDS, TREND_MATRIX_STORY_IDS, PRODUCT_TREND_CHART_STORY_IDS, METRIC_VALUE_STORY_IDS, SAFE_SOURCE_REFERENCE_STORY_IDS, TABLE_HEADER_STORY_IDS, COLUMN_SETTINGS_STORY_IDS, CATALOG_MAINTENANCE_OVERVIEW_STORY_IDS, CATALOG_UNMATCHED_STORY_IDS, CATALOG_VERSION_STORY_IDS, CATALOG_READ_FEEDBACK_STORY_IDS, CATALOG_SECTION_EDITOR_STORY_IDS, CATALOG_PENDING_CANDIDATE_STORY_IDS, CATALOG_IMPORT_HISTORY_STORY_IDS, CATALOG_WORKBOOK_STORY_IDS, CATALOG_ISSUE_SUMMARY_STORY_IDS, CATALOG_SOURCE_EVIDENCE_STORY_IDS, CATALOG_IDENTITY_OWNER_STORY_IDS, CATALOG_WORKFLOW_FORM_STORY_IDS, DRAFT_DATA_TABLE_STORY_IDS, NOTE_REVISION_STORY_IDS, ISSUE_REVIEW_STORY_IDS, ROW_REVIEW_STORY_IDS, FIELD_REVIEW_STORY_IDS, PUBLICATION_CONFIRMATION_STORY_IDS, MERGE_DECISION_STORY_IDS, VERSION_COMMAND_STORY_IDS, ADVANCED_REVIEW_WORKSPACE_STORY_IDS, WORKSPACE_SHELL_STORY_IDS, PRODUCT_DETAIL_STORY_IDS, PRODUCT_LEDGER_STORY_IDS, SESSION_ENTRY_STORY_IDS, ADMIN_RECOVERY_STORY_IDS, ADMIN_MAINTENANCE_STORY_IDS, ADMIN_AUDIT_STORY_IDS, ADMIN_SITE_CONFIG_STORY_IDS, ADMIN_ACCOUNTS_STORY_IDS, IMPORT_EVIDENCE_STORY_IDS, DRAFT_REVIEW_STORY_IDS, IMPORT_INTAKE_STORY_IDS, BATCH_REVIEW_STORY_IDS, VERSION_HISTORY_STORY_IDS, DATE_WORKBENCH_STORY_IDS, PUBLISHED_DETAIL_LEDGER_STORY_IDS, PUBLISHED_DAY_STORY_IDS, PUBLISHED_DAILY_STORY_IDS, CATALOG_SETUP_STORY_IDS, CATALOG_EDITORS_STORY_IDS, CATALOG_STYLE_DETAIL_STORY_IDS, CATALOG_OPERATIONS_STORY_IDS, CATALOG_PRODUCT_LIST_STORY_IDS, CATALOG_REVIEW_STORY_IDS, RESPONSIVE_STORY_IDS, STORY_IDS, VIEWPORTS } from "./storybookGateManifest";
import { openStory, prepareInteractiveStory } from "./storybookGateSupport";

type StoryIndex = { entries: Record<string, { id: string; title: string; type: string }> };

test("Storybook manifest covers every design-system and product-list story", async ({ request }) => {
  const response = await request.get("/index.json");
  expect(response.ok()).toBe(true);
  const index = await response.json() as StoryIndex;
  const actual = Object.values(index.entries)
    .filter((entry) => entry.type === "story" && entry.title.startsWith("Design System/"))
    .map((entry) => entry.id)
    .sort();
  expect(actual).toEqual([...STORY_IDS].sort());
  const productList = Object.values(index.entries)
    .filter((entry) => entry.type === "story" && entry.title === "Pages/Catalog Product List")
    .map((entry) => entry.id)
    .sort();
  expect(productList).toEqual([...CATALOG_PRODUCT_LIST_STORY_IDS].sort());
  const coverage = Object.values(index.entries).filter(entry => entry.type === "story" && entry.title === "Patterns/Coverage Reconciliation").map(entry => entry.id).sort();
  expect(coverage).toEqual([...COVERAGE_RECONCILIATION_STORY_IDS].sort());
  const help = Object.values(index.entries).filter(entry => entry.type === "story" && entry.title === "Patterns/Product Ledger Metric Help").map(entry => entry.id).sort();
  expect(help).toEqual([...LEDGER_METRIC_HELP_STORY_IDS].sort());
  const matrix = Object.values(index.entries).filter(entry => entry.type === "story" && entry.title === "Patterns/Trend Point Matrix").map(entry => entry.id).sort();
  expect(matrix).toEqual([...TREND_MATRIX_STORY_IDS].sort());
  const charts = Object.values(index.entries).filter(entry => entry.type === "story" && entry.title === "Patterns/Product Trend Chart").map(entry => entry.id).sort();
  expect(charts).toEqual([...PRODUCT_TREND_CHART_STORY_IDS].sort());
  const readouts = Object.values(index.entries).filter(entry => entry.type === "story" && entry.title === "Patterns/Metric Value").map(entry => entry.id).sort();
  expect(readouts).toEqual([...METRIC_VALUE_STORY_IDS].sort());
  const sources = Object.values(index.entries).filter(entry => entry.type === "story" && entry.title === "Patterns/Safe Source Reference").map(entry => entry.id).sort();
  expect(sources).toEqual([...SAFE_SOURCE_REFERENCE_STORY_IDS].sort());
  const tableHeader = Object.values(index.entries).filter(entry => entry.type === "story" && entry.title === "Patterns/Table Header").map(entry => entry.id).sort();
  expect(tableHeader).toEqual([...TABLE_HEADER_STORY_IDS].sort());
  const columnSettings = Object.values(index.entries).filter(entry => entry.type === "story" && entry.title === "Patterns/Column Settings").map(entry => entry.id).sort();
  expect(columnSettings).toEqual([...COLUMN_SETTINGS_STORY_IDS].sort());
  const overview = Object.values(index.entries).filter(entry => entry.type === "story" && entry.title === "Patterns/Catalog Maintenance Overview").map(entry => entry.id).sort();
  expect(overview).toEqual([...CATALOG_MAINTENANCE_OVERVIEW_STORY_IDS].sort());
  const unmatched = Object.values(index.entries).filter(entry => entry.type === "story" && entry.title === "Patterns/Catalog Unmatched Sources").map(entry => entry.id).sort();
  expect(unmatched).toEqual([...CATALOG_UNMATCHED_STORY_IDS].sort());
  const operations = Object.values(index.entries).filter(entry => entry.type === "story" && entry.title === "Pages/Catalog Operations").map(entry => entry.id).sort();
  expect(operations).toEqual([...CATALOG_OPERATIONS_STORY_IDS].sort());
  const rowReview = Object.values(index.entries).filter(entry => entry.type === "story" && entry.title === "Patterns/Row Review").map(entry => entry.id).sort();
  expect(rowReview).toEqual([...ROW_REVIEW_STORY_IDS].sort());
  const issueReview = Object.values(index.entries).filter(entry => entry.type === "story" && entry.title === "Patterns/Issue Review").map(entry => entry.id).sort();
  expect(issueReview).toEqual([...ISSUE_REVIEW_STORY_IDS].sort());
  const versionList = Object.values(index.entries).filter(entry => entry.type === "story" && entry.title === "Patterns/Catalog Versions").map(entry => entry.id).sort();
  expect(versionList).toEqual([...CATALOG_VERSION_STORY_IDS].sort());
  const readFeedback = Object.values(index.entries).filter(entry => entry.type === "story" && entry.title === "Patterns/Catalog Read Feedback").map(entry => entry.id).sort();
  expect(readFeedback).toEqual([...CATALOG_READ_FEEDBACK_STORY_IDS].sort());
  const sectionEditors = Object.values(index.entries).filter(entry => entry.type === "story" && entry.title === "Patterns/Catalog Section Editors").map(entry => entry.id).sort();
  expect(sectionEditors).toEqual([...CATALOG_SECTION_EDITOR_STORY_IDS].sort());
  const pendingCandidates = Object.values(index.entries).filter(entry => entry.type === "story" && entry.title === "Patterns/Catalog Pending Candidates").map(entry => entry.id).sort();
  expect(pendingCandidates).toEqual([...CATALOG_PENDING_CANDIDATE_STORY_IDS].sort());
  const importHistory = Object.values(index.entries).filter(entry => entry.type === "story" && entry.title === "Patterns/Catalog Import History").map(entry => entry.id).sort();
  expect(importHistory).toEqual([...CATALOG_IMPORT_HISTORY_STORY_IDS].sort());
  const workbook = Object.values(index.entries).filter(entry => entry.type === "story" && entry.title === "Patterns/Catalog Workbook").map(entry => entry.id).sort();
  expect(workbook).toEqual([...CATALOG_WORKBOOK_STORY_IDS].sort());
  const issueSummary = Object.values(index.entries).filter(entry => entry.type === "story" && entry.title === "Patterns/Catalog Issue Summary").map(entry => entry.id).sort();
  expect(issueSummary).toEqual([...CATALOG_ISSUE_SUMMARY_STORY_IDS].sort());
  const catalogEvidence = Object.values(index.entries).filter(entry => entry.type === "story" && entry.title === "Patterns/Catalog Source Evidence").map(entry => entry.id).sort();
  expect(catalogEvidence).toEqual([...CATALOG_SOURCE_EVIDENCE_STORY_IDS].sort());
  const identityOwners = Object.values(index.entries).filter(entry => entry.type === "story" && entry.title === "Patterns/Catalog Identity Owners").map(entry => entry.id).sort();
  expect(identityOwners).toEqual([...CATALOG_IDENTITY_OWNER_STORY_IDS].sort());
  const workflowForms = Object.values(index.entries).filter(entry => entry.type === "story" && entry.title === "Patterns/Catalog Workflow Forms").map(entry => entry.id).sort();
  expect(workflowForms).toEqual([...CATALOG_WORKFLOW_FORM_STORY_IDS].sort());
  const dataTable = Object.values(index.entries).filter(entry => entry.type === "story" && entry.title === "Patterns/Draft Data Table").map(entry => entry.id).sort();
  expect(dataTable).toEqual([...DRAFT_DATA_TABLE_STORY_IDS].sort());
  const noteRevision = Object.values(index.entries).filter(entry => entry.type === "story" && entry.title === "Patterns/Note Revision").map(entry => entry.id).sort();
  expect(noteRevision).toEqual([...NOTE_REVISION_STORY_IDS].sort());
  const fieldReview = Object.values(index.entries).filter(entry => entry.type === "story" && entry.title === "Patterns/Field Review").map(entry => entry.id).sort();
  expect(fieldReview).toEqual([...FIELD_REVIEW_STORY_IDS].sort());
  const publicationConfirmation = Object.values(index.entries).filter(entry => entry.type === "story" && entry.title === "Patterns/Publication Confirmation").map(entry => entry.id).sort();
  expect(publicationConfirmation).toEqual([...PUBLICATION_CONFIRMATION_STORY_IDS].sort());
  const merge = Object.values(index.entries).filter(entry => entry.type === "story" && entry.title === "Patterns/Merge Decision Matrix").map(entry => entry.id).sort();
  expect(merge).toEqual([...MERGE_DECISION_STORY_IDS].sort());
  const commands = Object.values(index.entries).filter(entry => entry.type === "story" && entry.title === "Pages/Version Commands").map(entry => entry.id).sort();
  expect(commands).toEqual([...VERSION_COMMAND_STORY_IDS].sort());
  const advanced = Object.values(index.entries).filter(entry => entry.type === "story" && entry.title === "Pages/Advanced Review Workspace").map(entry => entry.id).sort();
  expect(advanced).toEqual([...ADVANCED_REVIEW_WORKSPACE_STORY_IDS].sort());
  const shell = Object.values(index.entries).filter(entry => entry.type === "story" && entry.title === "Pages/Workspace Shell").map(entry => entry.id).sort();
  expect(shell).toEqual([...WORKSPACE_SHELL_STORY_IDS].sort());
  const detail = Object.values(index.entries).filter(entry => entry.type === "story" && entry.title === "Pages/Product Detail").map(entry => entry.id).sort();
  expect(detail).toEqual([...PRODUCT_DETAIL_STORY_IDS].sort());
  const ledger = Object.values(index.entries).filter(entry => entry.type === "story" && entry.title === "Pages/Product Ledger").map(entry => entry.id).sort();
  expect(ledger).toEqual([...PRODUCT_LEDGER_STORY_IDS].sort());
  const session = Object.values(index.entries).filter(entry => entry.type === "story" && entry.title === "Pages/Session Entry").map(entry => entry.id).sort();
  expect(session).toEqual([...SESSION_ENTRY_STORY_IDS].sort());
  const recovery = Object.values(index.entries).filter(entry => entry.type === "story" && entry.title === "Pages/Admin Recovery").map(entry => entry.id).sort();
  expect(recovery).toEqual([...ADMIN_RECOVERY_STORY_IDS].sort());
  const maintenance = Object.values(index.entries).filter(entry => entry.type === "story" && entry.title === "Pages/Admin Maintenance").map(entry => entry.id).sort();
  expect(maintenance).toEqual([...ADMIN_MAINTENANCE_STORY_IDS].sort());
  const audit = Object.values(index.entries).filter(entry => entry.type === "story" && entry.title === "Pages/Admin Audit").map(entry => entry.id).sort();
  expect(audit).toEqual([...ADMIN_AUDIT_STORY_IDS].sort());
  const siteConfig = Object.values(index.entries).filter(entry => entry.type === "story" && entry.title === "Pages/Admin Site Configuration").map(entry => entry.id).sort();
  expect(siteConfig).toEqual([...ADMIN_SITE_CONFIG_STORY_IDS].sort());
  const accounts = Object.values(index.entries).filter(entry => entry.type === "story" && entry.title === "Pages/Admin Accounts").map(entry => entry.id).sort();
  expect(accounts).toEqual([...ADMIN_ACCOUNTS_STORY_IDS].sort());
  const evidence = Object.values(index.entries).filter(entry => entry.type === "story" && entry.title === "Pages/Import Evidence").map(entry => entry.id).sort();
  expect(evidence).toEqual([...IMPORT_EVIDENCE_STORY_IDS].sort());
  const draft = Object.values(index.entries).filter(entry => entry.type === "story" && entry.title === "Pages/Draft Review").map(entry => entry.id).sort();
  expect(draft).toEqual([...DRAFT_REVIEW_STORY_IDS].sort());
  const intake = Object.values(index.entries).filter(entry => entry.type === "story" && entry.title === "Pages/Import Intake").map(entry => entry.id).sort();
  expect(intake).toEqual([...IMPORT_INTAKE_STORY_IDS].sort());
  const batchReview = Object.values(index.entries).filter(entry => entry.type === "story" && entry.title === "Pages/Batch Review").map(entry => entry.id).sort();
  expect(batchReview).toEqual([...BATCH_REVIEW_STORY_IDS].sort());
  const history = Object.values(index.entries).filter(entry => entry.type === "story" && entry.title === "Pages/Version History").map(entry => entry.id).sort();
  expect(history).toEqual([...VERSION_HISTORY_STORY_IDS].sort());
  const workbench = Object.values(index.entries).filter(entry => entry.type === "story" && entry.title === "Pages/Date Workbench").map(entry => entry.id).sort();
  expect(workbench).toEqual([...DATE_WORKBENCH_STORY_IDS].sort());
  const detailLedger = Object.values(index.entries).filter(entry => entry.type === "story" && entry.title === "Pages/Published Detail Ledger").map(entry => entry.id).sort();
  expect(detailLedger).toEqual([...PUBLISHED_DETAIL_LEDGER_STORY_IDS].sort());
  const publishedDay = Object.values(index.entries).filter(entry => entry.type === "story" && entry.title === "Pages/Published Day Detail").map(entry => entry.id).sort();
  expect(publishedDay).toEqual([...PUBLISHED_DAY_STORY_IDS].sort());
  const publishedDaily = Object.values(index.entries).filter(entry => entry.type === "story" && entry.title === "Pages/Published Daily Ledger").map(entry => entry.id).sort();
  expect(publishedDaily).toEqual([...PUBLISHED_DAILY_STORY_IDS].sort());
  const setup = Object.values(index.entries).filter(entry => entry.type === "story" && entry.title === "Pages/Catalog Setup").map(entry => entry.id).sort();
  expect(setup).toEqual([...CATALOG_SETUP_STORY_IDS].sort());
  const editors = Object.values(index.entries).filter(entry => entry.type === "story" && entry.title === "Pages/Catalog Editors").map(entry => entry.id).sort();
  expect(editors).toEqual([...CATALOG_EDITORS_STORY_IDS].sort());
  const details = Object.values(index.entries).filter(entry => entry.type === "story" && entry.title === "Pages/Catalog Style Detail").map(entry => entry.id).sort();
  expect(details).toEqual([...CATALOG_STYLE_DETAIL_STORY_IDS].sort());
  const allStories = Object.values(index.entries).filter(entry => entry.type === "story").map(entry => entry.id).sort();
  expect(new Set(VISUAL_STORY_IDS).size).toBe(VISUAL_STORY_IDS.length);
  expect([...VISUAL_STORY_IDS].sort()).toEqual(allStories);
});

for (const viewport of VIEWPORTS) {
  for (const label of ["商品状态", "排序"]) {
    test(`catalog glide menu ${label} has no serious accessibility violations at ${viewport.width}px`, async ({ page }) => {
      await page.setViewportSize(viewport);
      await openStory(page, "pages-catalog-product-list--reference");
      await page.getByRole("combobox", { name: label, exact: true }).click();
      await expect(page.getByRole("listbox", { name: label, exact: true })).toBeVisible();
      const results = await new AxeBuilder({ page })
        .include("#storybook-root")
        .include(".glide-select--portal")
        .withTags(["wcag2a", "wcag2aa", "wcag21a", "wcag21aa"])
        .analyze();
      const blocking = results.violations.filter(violation => violation.impact === "serious" || violation.impact === "critical");
      expect(blocking, blocking.map(violation => `${violation.id}: ${violation.help}`).join("\n")).toEqual([]);
    });
  }
  const stories = [...COVERAGE_RECONCILIATION_STORY_IDS, ...LEDGER_METRIC_HELP_STORY_IDS, ...TREND_MATRIX_STORY_IDS, ...PRODUCT_TREND_CHART_STORY_IDS, ...METRIC_VALUE_STORY_IDS, ...SAFE_SOURCE_REFERENCE_STORY_IDS, ...TABLE_HEADER_STORY_IDS, ...COLUMN_SETTINGS_STORY_IDS, ...CATALOG_MAINTENANCE_OVERVIEW_STORY_IDS, ...CATALOG_UNMATCHED_STORY_IDS, ...CATALOG_VERSION_STORY_IDS, ...CATALOG_READ_FEEDBACK_STORY_IDS, ...CATALOG_SECTION_EDITOR_STORY_IDS, ...CATALOG_PENDING_CANDIDATE_STORY_IDS, ...CATALOG_IMPORT_HISTORY_STORY_IDS, ...CATALOG_WORKBOOK_STORY_IDS, ...CATALOG_ISSUE_SUMMARY_STORY_IDS, ...CATALOG_SOURCE_EVIDENCE_STORY_IDS, ...CATALOG_IDENTITY_OWNER_STORY_IDS, ...CATALOG_WORKFLOW_FORM_STORY_IDS, ...DRAFT_DATA_TABLE_STORY_IDS, ...NOTE_REVISION_STORY_IDS, ...ISSUE_REVIEW_STORY_IDS, ...ROW_REVIEW_STORY_IDS, ...FIELD_REVIEW_STORY_IDS, ...PUBLICATION_CONFIRMATION_STORY_IDS, ...MERGE_DECISION_STORY_IDS, ...VERSION_COMMAND_STORY_IDS, ...ADVANCED_REVIEW_WORKSPACE_STORY_IDS, ...WORKSPACE_SHELL_STORY_IDS, ...PRODUCT_DETAIL_STORY_IDS, ...PRODUCT_LEDGER_STORY_IDS, ...SESSION_ENTRY_STORY_IDS, ...ADMIN_RECOVERY_STORY_IDS, ...(viewport.width === 1280 ? STORY_IDS : RESPONSIVE_STORY_IDS), ...ADMIN_MAINTENANCE_STORY_IDS, ...ADMIN_AUDIT_STORY_IDS, ...ADMIN_SITE_CONFIG_STORY_IDS, ...ADMIN_ACCOUNTS_STORY_IDS, ...IMPORT_EVIDENCE_STORY_IDS, ...DRAFT_REVIEW_STORY_IDS, ...IMPORT_INTAKE_STORY_IDS, ...BATCH_REVIEW_STORY_IDS, ...VERSION_HISTORY_STORY_IDS, ...DATE_WORKBENCH_STORY_IDS, ...PUBLISHED_DETAIL_LEDGER_STORY_IDS, ...PUBLISHED_DAY_STORY_IDS, ...PUBLISHED_DAILY_STORY_IDS, ...CATALOG_SETUP_STORY_IDS, ...CATALOG_EDITORS_STORY_IDS, ...CATALOG_STYLE_DETAIL_STORY_IDS, ...CATALOG_REVIEW_STORY_IDS, ...CATALOG_PRODUCT_LIST_STORY_IDS, ...CATALOG_OPERATIONS_STORY_IDS];
  for (const storyId of stories) {
    test(`${storyId} has no serious accessibility violations at ${viewport.width}px`, async ({ page }) => {
      await page.setViewportSize(viewport);
      await openStory(page, storyId);
      await prepareInteractiveStory(page, storyId);
      const results = await new AxeBuilder({ page })
        .include("#storybook-root")
        .include('[role="dialog"]')
        .withTags(["wcag2a", "wcag2aa", "wcag21a", "wcag21aa"])
        .analyze();
      const blocking = results.violations.filter((violation) => violation.impact === "serious" || violation.impact === "critical");
      expect(blocking, blocking.map((violation) => `${violation.id}: ${violation.help}`).join("\n")).toEqual([]);
    });
  }
}
