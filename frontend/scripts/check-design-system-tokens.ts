import { readFileSync, readdirSync } from "node:fs";
import { relative, resolve } from "node:path";

import { checkTokenPolicy, type TokenPolicyAllowlist } from "./tokenPolicy.ts";

const root = process.cwd();
const designSystemDirectory = resolve(root, "src/design-system");
const allowlistPath = resolve(designSystemDirectory, "token-policy-allowlist.json");
const allowlist = JSON.parse(readFileSync(allowlistPath, "utf8")) as TokenPolicyAllowlist;
const sources = readdirSync(designSystemDirectory, { withFileTypes: true })
  .filter((entry) => entry.isFile() && entry.name.endsWith(".module.css"))
  .map((entry) => {
    const path = resolve(designSystemDirectory, entry.name);
    return { path: relative(root, path), content: readFileSync(path, "utf8") };
  });
for (const name of ["CatalogMaintenanceOverview", "CatalogUnmatchedView", "CatalogVersionsView", "CatalogReadFailure", "CatalogImportSectionTable", "CatalogPendingItems", "CatalogImportHistoryView", "CatalogExportView", "CatalogIssueSummary", "CatalogEvidencePanel", "CatalogImportReview", "CatalogProductList", "CatalogProductDrawer", "CatalogStyleView", "CatalogSetupView", "CatalogChangeReview", "CatalogCategoryEditor", "CatalogOperations"]) {
  const path = resolve(root, `src/features/catalog/${name}.module.css`);
  sources.push({ path: relative(root, path), content: readFileSync(path, "utf8") });
}

const dailyViewPath = resolve(root, "src/features/dashboard/PublishedDailyView.module.css");
sources.push({ path: relative(root, dailyViewPath), content: readFileSync(dailyViewPath, "utf8") });

const dayViewPath = resolve(root, "src/features/published/PublishedDayView.module.css");
sources.push({ path: relative(root, dayViewPath), content: readFileSync(dayViewPath, "utf8") });

for (const name of ["PublishedDetailLedgerView", "PublishedDateSummaries"]) {
  const path = resolve(root, `src/features/published-details/${name}.module.css`);
  sources.push({ path: relative(root, path), content: readFileSync(path, "utf8") });
}

const workbenchViewPath = resolve(root, "src/features/workbench/DateWorkbenchView.module.css");
sources.push({ path: relative(root, workbenchViewPath), content: readFileSync(workbenchViewPath, "utf8") });

for (const file of ["src/features/import-review/ImportIntakeView.module.css", "src/features/batch-review/BatchReviewPage.module.css", "src/features/versions/VersionHistoryView.module.css", "src/features/versions/VersionRowsView.module.css", "src/features/batch-review/BatchReviewHistoryView.module.css"]) {
  sources.push({ path: file, content: readFileSync(resolve(root, file), "utf8") });
}

const draftViewPath = "src/features/import-review/DraftReviewView.module.css";
sources.push({ path: draftViewPath, content: readFileSync(resolve(root, draftViewPath), "utf8") });
const evidenceViewPath = "src/features/import-review/ImportEvidence.module.css";
sources.push({ path: evidenceViewPath, content: readFileSync(resolve(root, evidenceViewPath), "utf8") });

const accountsViewPath = "src/features/admin/AdminAccountsView.module.css";
sources.push({ path: accountsViewPath, content: readFileSync(resolve(root, accountsViewPath), "utf8") });
const siteViewPath = "src/features/admin/SiteConfigurationView.module.css";
sources.push({ path: siteViewPath, content: readFileSync(resolve(root, siteViewPath), "utf8") });

const auditViewPath = "src/features/admin/AdminAuditView.module.css";
sources.push({ path: auditViewPath, content: readFileSync(resolve(root, auditViewPath), "utf8") });

const maintenanceViewPath = "src/features/admin/AdminMaintenanceView.module.css";
sources.push({ path: maintenanceViewPath, content: readFileSync(resolve(root, maintenanceViewPath), "utf8") });

const recoveryViewPath = "src/features/admin/AdminRecoveryView.module.css";
sources.push({ path: recoveryViewPath, content: readFileSync(resolve(root, recoveryViewPath), "utf8") });

const sessionViewPath = "src/app/SessionEntryView.module.css";
sources.push({ path: sessionViewPath, content: readFileSync(resolve(root, sessionViewPath), "utf8") });

const productLedgerViewPath = "src/features/products/ProductLedgerView.module.css";
sources.push({ path: productLedgerViewPath, content: readFileSync(resolve(root, productLedgerViewPath), "utf8") });

const productDetailViewPath = "src/features/products/ProductDetailAnalysisView.module.css";
sources.push({ path: productDetailViewPath, content: readFileSync(resolve(root, productDetailViewPath), "utf8") });

const shellPath = "src/app/AppShell.module.css";
sources.push({ path: shellPath, content: readFileSync(resolve(root, shellPath), "utf8") });

const advancedReviewPath = "src/app/AdvancedReviewWorkspaceView.module.css";
sources.push({ path: advancedReviewPath, content: readFileSync(resolve(root, advancedReviewPath), "utf8") });

const commandViewPath = "src/features/versions/VersionCommandViews.module.css";
sources.push({ path: commandViewPath, content: readFileSync(resolve(root, commandViewPath), "utf8") });

const mergeMatrixPath = "src/features/import-review/MergeDecisionMatrix.module.css";
sources.push({ path: mergeMatrixPath, content: readFileSync(resolve(root, mergeMatrixPath), "utf8") });

const publicationDialogPath = "src/features/import-review/DraftPublicationDialog.module.css";
sources.push({ path: publicationDialogPath, content: readFileSync(resolve(root, publicationDialogPath), "utf8") });

const cellReviewPath = "src/features/import-review/CellReviewDrawer.module.css";
sources.push({ path: cellReviewPath, content: readFileSync(resolve(root, cellReviewPath), "utf8") });

const rowReviewPath = "src/features/import-review/RowReviewDrawer.module.css";
sources.push({ path: rowReviewPath, content: readFileSync(resolve(root, rowReviewPath), "utf8") });

const issueReviewPath = "src/features/import-review/IssueReviewPanel.module.css";
sources.push({ path: issueReviewPath, content: readFileSync(resolve(root, issueReviewPath), "utf8") });

const noteRevisionPath = "src/features/import-review/NoteRevisionEditor.module.css";
sources.push({ path: noteRevisionPath, content: readFileSync(resolve(root, noteRevisionPath), "utf8") });

const dataTablePath = "src/features/import-review/ReviewDataTable.module.css";
sources.push({ path: dataTablePath, content: readFileSync(resolve(root, dataTablePath), "utf8") });
const cellPath = "src/features/workbench/WorkbenchCell.module.css";
sources.push({ path: cellPath, content: readFileSync(resolve(root, cellPath), "utf8") });
const workflowFormPath = "src/features/catalog/CatalogWorkflowActions.module.css";
sources.push({ path: workflowFormPath, content: readFileSync(resolve(root, workflowFormPath), "utf8") });
const identityOwnerPath = "src/features/catalog/CatalogIdentityOwners.module.css";
sources.push({ path: identityOwnerPath, content: readFileSync(resolve(root, identityOwnerPath), "utf8") });
const columnSettingsPath = "src/components/data-table/ColumnSettingsPanel.module.css";
sources.push({ path: columnSettingsPath, content: readFileSync(resolve(root, columnSettingsPath), "utf8") });
const tableHeaderPath = "src/components/data-table/DataTableHeader.module.css";
sources.push({ path: tableHeaderPath, content: readFileSync(resolve(root, tableHeaderPath), "utf8") });
const sourceReferencePath = "src/components/source-reference/SafeSourceRefView.module.css";
sources.push({ path: sourceReferencePath, content: readFileSync(resolve(root, sourceReferencePath), "utf8") });
const metricValuePath = "src/features/products/MetricValueView.module.css";
sources.push({ path: metricValuePath, content: readFileSync(resolve(root, metricValuePath), "utf8") });
const matrixPath = "src/features/products/TrendPointMatrix.module.css";
sources.push({ path: matrixPath, content: readFileSync(resolve(root, matrixPath), "utf8") });
for (const name of ["CoverageReconciliation", "LedgerMetricHelp"]) {
  const path = resolve(root, `src/features/products/${name}.module.css`);
  sources.push({ path: relative(root, path), content: readFileSync(path, "utf8") });
}

const violations = checkTokenPolicy(sources, allowlist);
if (violations.length > 0) {
  for (const violation of violations) {
    console.error(`${violation.file}:${violation.line} ${violation.rule}: ${violation.value}`);
  }
  process.exit(1);
}

console.log(`Token policy passed (${sources.length} CSS Modules, ${allowlist.exceptions.length} approved exceptions).`);
