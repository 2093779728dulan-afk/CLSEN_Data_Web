export const CATALOG_MAINTENANCE_OVERVIEW_STORY_IDS = [
  "patterns-catalog-maintenance-overview--reference", "patterns-catalog-maintenance-overview--uninitialized",
  "patterns-catalog-maintenance-overview--first-version", "patterns-catalog-maintenance-overview--long-identifiers",
] as const;

export const CATALOG_UNMATCHED_STORY_IDS = [
  "patterns-catalog-unmatched-sources--reference", "patterns-catalog-unmatched-sources--multi-currency",
  "patterns-catalog-unmatched-sources--long-preview", "patterns-catalog-unmatched-sources--loading",
  "patterns-catalog-unmatched-sources--empty", "patterns-catalog-unmatched-sources--no-evidence",
  "patterns-catalog-unmatched-sources--future-range", "patterns-catalog-unmatched-sources--empty-page",
  "patterns-catalog-unmatched-sources--pending-loading", "patterns-catalog-unmatched-sources--pending-failure",
] as const;

export const CATALOG_VERSION_STORY_IDS = [
  "patterns-catalog-versions--reference",
  "patterns-catalog-versions--empty",
  "patterns-catalog-versions--loading",
  "patterns-catalog-versions--first-version",
  "patterns-catalog-versions--unknown-risk",
  "patterns-catalog-versions--missing-fields",
  "patterns-catalog-versions--long-values",
  "patterns-catalog-versions--refresh-failure",
] as const;

export const CATALOG_READ_FEEDBACK_STORY_IDS = [
  "patterns-catalog-read-feedback--reference",
  "patterns-catalog-read-feedback--repeat-failure",
  "patterns-catalog-read-feedback--rate-limited",
  "patterns-catalog-read-feedback--forbidden",
  "patterns-catalog-read-feedback--not-found",
  "patterns-catalog-read-feedback--invalid-query",
  "patterns-catalog-read-feedback--setup",
  "patterns-catalog-read-feedback--long-message",
] as const;

export const CATALOG_SECTION_EDITOR_STORY_IDS = [
  "patterns-catalog-section-editors--reference", "patterns-catalog-section-editors--skus",
  "patterns-catalog-section-editors--mappings", "patterns-catalog-section-editors--exceptions",
  "patterns-catalog-section-editors--read-only", "patterns-catalog-section-editors--field-issues",
  "patterns-catalog-section-editors--busy", "patterns-catalog-section-editors--empty",
  "patterns-catalog-section-editors--filtered-empty", "patterns-catalog-section-editors--save-failure",
  "patterns-catalog-section-editors--refresh-failure", "patterns-catalog-section-editors--long-values",
] as const;

export const CATALOG_PENDING_CANDIDATE_STORY_IDS = [
  "patterns-catalog-pending-candidates--reference", "patterns-catalog-pending-candidates--read-only",
  "patterns-catalog-pending-candidates--empty", "patterns-catalog-pending-candidates--no-previews",
  "patterns-catalog-pending-candidates--zero-counts", "patterns-catalog-pending-candidates--long-previews",
  "patterns-catalog-pending-candidates--many-batches",
] as const;

export const CATALOG_IMPORT_HISTORY_STORY_IDS = [
  "patterns-catalog-import-history--reference", "patterns-catalog-import-history--empty",
  "patterns-catalog-import-history--loading", "patterns-catalog-import-history--read-failure",
  "patterns-catalog-import-history--second-page", "patterns-catalog-import-history--archived",
  "patterns-catalog-import-history--long-values", "patterns-catalog-import-history--unknown-status",
] as const;

export const CATALOG_WORKBOOK_STORY_IDS = [
  "patterns-catalog-workbook--reference", "patterns-catalog-workbook--idle", "patterns-catalog-workbook--unready",
  "patterns-catalog-workbook--building", "patterns-catalog-workbook--failed", "patterns-catalog-workbook--no-resume",
  "patterns-catalog-workbook--stale", "patterns-catalog-workbook--capacity", "patterns-catalog-workbook--no-download",
  "patterns-catalog-workbook--upload-failure", "patterns-catalog-workbook--busy",
] as const;

export const CATALOG_ISSUE_SUMMARY_STORY_IDS = [
  "patterns-catalog-issue-summary--reference", "patterns-catalog-issue-summary--warning",
  "patterns-catalog-issue-summary--blocking", "patterns-catalog-issue-summary--unlocatable",
  "patterns-catalog-issue-summary--long-values", "patterns-catalog-issue-summary--many-issues",
  "patterns-catalog-issue-summary--parse-failed", "patterns-catalog-issue-summary--empty",
  "patterns-catalog-issue-summary--read-only", "patterns-catalog-issue-summary--unknown-code",
] as const;

export const CATALOG_SOURCE_EVIDENCE_STORY_IDS = [
  "patterns-catalog-source-evidence--reference", "patterns-catalog-source-evidence--empty",
  "patterns-catalog-source-evidence--loading", "patterns-catalog-source-evidence--read-failure",
  "patterns-catalog-source-evidence--revealing", "patterns-catalog-source-evidence--reveal-failure",
  "patterns-catalog-source-evidence--revealed", "patterns-catalog-source-evidence--long-preview",
  "patterns-catalog-source-evidence--boundary-change", "patterns-catalog-source-evidence--long-identifier",
] as const;

export const DRAFT_DATA_TABLE_STORY_IDS = [
  "patterns-draft-data-table--reference", "patterns-draft-data-table--long-values", "patterns-draft-data-table--unchanged",
  "patterns-draft-data-table--empty", "patterns-draft-data-table--filter-empty", "patterns-draft-data-table--busy", "patterns-draft-data-table--second-page",
] as const;

export const NOTE_REVISION_STORY_IDS = [
  "patterns-note-revision--reference",
  "patterns-note-revision--batch",
  "patterns-note-revision--row",
  "patterns-note-revision--field",
  "patterns-note-revision--viewer-visible",
  "patterns-note-revision--long-content",
  "patterns-note-revision--empty",
  "patterns-note-revision--saving",
  "patterns-note-revision--save-failure",
] as const;

export const ISSUE_REVIEW_STORY_IDS = [
  "patterns-issue-review--reference",
  "patterns-issue-review--warning",
  "patterns-issue-review--blocking",
  "patterns-issue-review--handled",
  "patterns-issue-review--optional-note",
  "patterns-issue-review--long-values",
  "patterns-issue-review--saving",
  "patterns-issue-review--save-failure",
] as const;

export const ROW_REVIEW_STORY_IDS = [
  "patterns-row-review--reference",
  "patterns-row-review--nullable",
  "patterns-row-review--no-source",
  "patterns-row-review--add-saving",
  "patterns-row-review--add-failure",
  "patterns-row-review--exclude",
  "patterns-row-review--restore",
  "patterns-row-review--source-deleted",
  "patterns-row-review--manual-deleted",
  "patterns-row-review--empty-records",
  "patterns-row-review--state-saving",
  "patterns-row-review--state-failure",
  "patterns-row-review--note-editing",
  "patterns-row-review--note-failure",
] as const;

export const FIELD_REVIEW_STORY_IDS = [
  "patterns-field-review--reference",
  "patterns-field-review--nullable",
  "patterns-field-review--readonly",
  "patterns-field-review--integer",
  "patterns-field-review--empty-records",
  "patterns-field-review--long-text",
  "patterns-field-review--saving",
  "patterns-field-review--save-failure",
  "patterns-field-review--note-editing",
  "patterns-field-review--note-failure",
] as const;

export const PUBLICATION_CONFIRMATION_STORY_IDS = [
  "patterns-publication-confirmation--reference",
  "patterns-publication-confirmation--no-operator",
  "patterns-publication-confirmation--warnings",
  "patterns-publication-confirmation--cross-date",
  "patterns-publication-confirmation--return-report",
  "patterns-publication-confirmation--return-building",
  "patterns-publication-confirmation--return-retrying",
  "patterns-publication-confirmation--return-ready",
  "patterns-publication-confirmation--return-superseded",
  "patterns-publication-confirmation--submitting",
  "patterns-publication-confirmation--failure",
] as const;

export const MERGE_DECISION_STORY_IDS = [
  "patterns-merge-decision-matrix--reference",
  "patterns-merge-decision-matrix--identical",
  "patterns-merge-decision-matrix--hidden-fields",
  "patterns-merge-decision-matrix--return-report",
  "patterns-merge-decision-matrix--empty",
  "patterns-merge-decision-matrix--loading",
  "patterns-merge-decision-matrix--read-failure",
  "patterns-merge-decision-matrix--disabled",
  "patterns-merge-decision-matrix--in-dialog",
] as const;

export const VERSION_COMMAND_STORY_IDS = [
  "pages-version-commands--revision",
  "pages-version-commands--revision-submitting",
  "pages-version-commands--revision-failure",
  "pages-version-commands--move",
  "pages-version-commands--move-checking",
  "pages-version-commands--move-published",
  "pages-version-commands--move-draft",
  "pages-version-commands--move-blocked",
  "pages-version-commands--move-failure",
  "pages-version-commands--undo",
  "pages-version-commands--undo-failure",
  "pages-version-commands--rollback",
  "pages-version-commands--rollback-failure",
] as const;

export const ADVANCED_REVIEW_WORKSPACE_STORY_IDS = [
  "pages-advanced-review-workspace--reference", "pages-advanced-review-workspace--empty", "pages-advanced-review-workspace--loading",
  "pages-advanced-review-workspace--read-failure", "pages-advanced-review-workspace--refreshing", "pages-advanced-review-workspace--read-only",
  "pages-advanced-review-workspace--published", "pages-advanced-review-workspace--source-batch",
] as const;

export const WORKSPACE_SHELL_STORY_IDS = [
  "pages-workspace-shell--reference", "pages-workspace-shell--manager", "pages-workspace-shell--viewer",
  "pages-workspace-shell--collapsed", "pages-workspace-shell--offline", "pages-workspace-shell--logout-busy",
  "pages-workspace-shell--logout-failure", "pages-workspace-shell--navigation", "pages-workspace-shell--navigation-failure",
] as const;

export const PRODUCT_DETAIL_STORY_IDS = [
  "pages-product-detail--reference",
  "pages-product-detail--read-only",
  "pages-product-detail--partial",
  "pages-product-detail--no-reports",
  "pages-product-detail--empty-variants",
  "pages-product-detail--loading",
  "pages-product-detail--refreshing",
  "pages-product-detail--read-failure",
  "pages-product-detail--access-denied",
  "pages-product-detail--color-failure",
] as const;

export const CATALOG_SETUP_STORY_IDS = [
  "pages-catalog-setup--reference",
  "pages-catalog-setup--source-submitting",
  "pages-catalog-setup--source-failure",
  "pages-catalog-setup--confirmed",
  "pages-catalog-setup--preview",
  "pages-catalog-setup--initializing",
  "pages-catalog-setup--initialization-failure",
  "pages-catalog-setup--missing-reports",
  "pages-catalog-setup--ready",
  "pages-catalog-setup--read-only",
  "pages-catalog-setup--loading",
  "pages-catalog-setup--read-failure",
] as const;

export const CATALOG_EDITORS_STORY_IDS = [
  "pages-catalog-editors--editing",
  "pages-catalog-editors--preview",
  "pages-catalog-editors--preparing",
  "pages-catalog-editors--prepare-failure",
  "pages-catalog-editors--approval-failure",
  "pages-catalog-editors--refresh-failure",
  "pages-catalog-editors--categories",
  "pages-catalog-editors--unsaved",
  "pages-catalog-editors--loading",
  "pages-catalog-editors--read-failure",
  "pages-catalog-editors--empty",
  "pages-catalog-editors--save-failure",
  "pages-catalog-editors--saved",
] as const;

export const CATALOG_STYLE_DETAIL_STORY_IDS = [
  "pages-catalog-style-detail--reference",
  "pages-catalog-style-detail--loading",
  "pages-catalog-style-detail--empty",
  "pages-catalog-style-detail--read-failure",
  "pages-catalog-style-detail--read-only",
  "pages-catalog-style-detail--aliases-loading",
  "pages-catalog-style-detail--aliases-failure",
  "pages-catalog-style-detail--evidence",
  "pages-catalog-style-detail--evidence-failure",
  "pages-catalog-style-detail--pending-candidates",
] as const;

export const CATALOG_OPERATIONS_STORY_IDS = [
  "pages-catalog-operations--versions",
  "pages-catalog-operations--versions-empty",
  "pages-catalog-operations--versions-loading",
  "pages-catalog-operations--versions-failure",
  "pages-catalog-operations--unmatched",
  "pages-catalog-operations--unmatched-loading",
  "pages-catalog-operations--no-publication-evidence",
  "pages-catalog-operations--unmatched-empty",
  "pages-catalog-operations--pending-failure",
  "pages-catalog-operations--maintenance",
  "pages-catalog-operations--uninitialized",
  "pages-catalog-operations--building",
  "pages-catalog-operations--generation-failed",
  "pages-catalog-operations--stale-candidate",
  "pages-catalog-operations--capacity-exceeded",
] as const;

export const CATALOG_PRODUCT_LIST_STORY_IDS = [
  "pages-catalog-product-list--quick-view",
  "pages-catalog-product-list--quick-view-loading",
  "pages-catalog-product-list--quick-view-failure",
  "pages-catalog-product-list--refreshing",
  "pages-catalog-product-list--refresh-failure",
  "pages-catalog-product-list--reference",
  "pages-catalog-product-list--batch-table",
  "pages-catalog-product-list--loading",
  "pages-catalog-product-list--empty",
  "pages-catalog-product-list--uninitialized",
  "pages-catalog-product-list--no-results",
  "pages-catalog-product-list--read-failure",
  "pages-catalog-product-list--read-only",
] as const;

// Existing product-list reference, opened in place; these are not additional demo pages.
export const CATALOG_PRODUCT_LIST_MENU_CASES = [
  { label: "商品状态", snapshotId: "pages-catalog-product-list--status-menu" },
  { label: "排序", snapshotId: "pages-catalog-product-list--sort-menu" },
] as const;

export const CATALOG_IDENTITY_OWNER_STORY_IDS = [
  "patterns-catalog-identity-owners--reference",
  "patterns-catalog-identity-owners--empty",
  "patterns-catalog-identity-owners--loading",
  "patterns-catalog-identity-owners--read-failure",
  "patterns-catalog-identity-owners--restore-saving",
  "patterns-catalog-identity-owners--restore-failure",
  "patterns-catalog-identity-owners--refresh-failure",
  "patterns-catalog-identity-owners--restored",
  "patterns-catalog-identity-owners--read-only",
  "patterns-catalog-identity-owners--long-reason",
] as const;

export const CATALOG_WORKFLOW_FORM_STORY_IDS = [
  "patterns-catalog-workflow-forms--reference",
  "patterns-catalog-workflow-forms--high-risk",
  "patterns-catalog-workflow-forms--rebase",
  "patterns-catalog-workflow-forms--saving",
  "patterns-catalog-workflow-forms--failure",
  "patterns-catalog-workflow-forms--blocked",
  "patterns-catalog-workflow-forms--read-only",
  "patterns-catalog-workflow-forms--approved",
] as const;

export const CATALOG_REVIEW_STORY_IDS = [
  "pages-catalog-import-review--reference",
  "pages-catalog-import-review--validation-issues",
  "pages-catalog-import-review--pending-changes",
  "pages-catalog-import-review--loading",
  "pages-catalog-import-review--empty",
  "pages-catalog-import-review--read-only",
  "pages-catalog-import-review--save-failure",
  "pages-catalog-import-review--refresh-failure",
] as const;

export const STORY_IDS = [
  "design-system-interaction-feedback--click-spark-states",
  "design-system-actions-and-status--button-states",
  "design-system-actions-and-status--save-feedback",
  "design-system-actions-and-status--status-states",
  "design-system-form-controls--global-defaults",
  "design-system-form-controls--field-states",
  "design-system-form-controls--review-controls",
  "design-system-structure-and-navigation--header",
  "design-system-structure-and-navigation--dialog-interaction",
  "design-system-structure-and-navigation--pagination-states",
  "design-system-selection-and-navigation--selection-states",
  "design-system-selection-and-navigation--composite-interactions",
  "design-system-selection-and-navigation--narrow-and-long-chinese",
  "design-system-feedback-and-data--toast-kinds",
  "design-system-feedback-and-data--loading-empty-and-error",
  "design-system-feedback-and-data--basic-table",
] as const;

export const RESPONSIVE_STORY_IDS = [
  "design-system-interaction-feedback--click-spark-states",
  "design-system-actions-and-status--save-feedback",
  "design-system-form-controls--global-defaults",
  "design-system-form-controls--field-states",
  "design-system-form-controls--review-controls",
  "design-system-structure-and-navigation--pagination-states",
  "design-system-selection-and-navigation--selection-states",
  "design-system-actions-and-status--status-states",
  "design-system-structure-and-navigation--header",
  "design-system-selection-and-navigation--narrow-and-long-chinese",
  "design-system-feedback-and-data--loading-empty-and-error",
  "design-system-feedback-and-data--basic-table",
] as const;

export const PUBLISHED_DAILY_STORY_IDS = [
  "pages-published-daily-ledger--reference", "pages-published-daily-ledger--manager",
  "pages-published-daily-ledger--filtered", "pages-published-daily-ledger--filter-empty",
  "pages-published-daily-ledger--no-records", "pages-published-daily-ledger--loading",
  "pages-published-daily-ledger--read-failure", "pages-published-daily-ledger--zero-values",
] as const;

export const PUBLISHED_DAY_STORY_IDS = [
  "pages-published-day-detail--reference", "pages-published-day-detail--partial",
  "pages-published-day-detail--zero-values", "pages-published-day-detail--loading",
  "pages-published-day-detail--read-failure", "pages-published-day-detail--empty",
  "pages-published-day-detail--single-day", "pages-published-day-detail--embedded",
] as const;

export const PUBLISHED_DETAIL_LEDGER_STORY_IDS = [
  "pages-published-detail-ledger--column-settings",
  "pages-published-detail-ledger--reference", "pages-published-detail-ledger--all-rows", "pages-published-detail-ledger--return-report",
  "pages-published-detail-ledger--loading", "pages-published-detail-ledger--read-failure", "pages-published-detail-ledger--empty",
  "pages-published-detail-ledger--expansion-failure", "pages-published-detail-ledger--expansion-loading", "pages-published-detail-ledger--scope-changed",
] as const;

export const DATE_WORKBENCH_STORY_IDS = [
  "pages-date-workbench--column-settings",
  "pages-date-workbench--reference", "pages-date-workbench--manager", "pages-date-workbench--draft", "pages-date-workbench--save-failure",
  "pages-date-workbench--empty", "pages-date-workbench--read-only-empty", "pages-date-workbench--loading", "pages-date-workbench--read-failure",
  "pages-date-workbench--import-confirmation", "pages-date-workbench--import-conflict",
  "pages-date-workbench--cell-editing", "pages-date-workbench--cell-saving", "pages-date-workbench--cell-saved", "pages-date-workbench--cell-conflict", "pages-date-workbench--cell-long-error",
] as const;

export const VERSION_HISTORY_STORY_IDS = [
  "pages-version-history--reference",
  "pages-version-history--manager",
  "pages-version-history--active-draft",
  "pages-version-history--batch-drafts",
  "pages-version-history--empty",
  "pages-version-history--loading",
  "pages-version-history--read-failure",
  "pages-version-history--detail-loading",
  "pages-version-history--detail-failure",
  "pages-version-history--rows-open",
  "pages-version-history--rows-loading",
  "pages-version-history--rows-failure",
  "pages-version-history--rows-empty",
] as const;

export const BATCH_REVIEW_STORY_IDS = [
  "pages-batch-review--reference", "pages-batch-review--running", "pages-batch-review--paused", "pages-batch-review--completed",
  "pages-batch-review--exceptions", "pages-batch-review--outcome-unknown", "pages-batch-review--confirming", "pages-batch-review--retrying",
  "pages-batch-review--empty", "pages-batch-review--loading", "pages-batch-review--read-failure", "pages-batch-review--action-failure",
] as const;

export const IMPORT_INTAKE_STORY_IDS = [
  "pages-import-intake--reference", "pages-import-intake--recognition", "pages-import-intake--date-mismatch", "pages-import-intake--baseline",
  "pages-import-intake--target-conflict", "pages-import-intake--active-draft-conflict", "pages-import-intake--uploading", "pages-import-intake--parsing",
  "pages-import-intake--restoring", "pages-import-intake--read-failure", "pages-import-intake--parse-failure",
] as const;

export const DRAFT_REVIEW_STORY_IDS = [
  "pages-draft-review--reference", "pages-draft-review--validated", "pages-draft-review--blocking", "pages-draft-review--warning",
  "pages-draft-review--ready-for-publish", "pages-draft-review--publish-dialog", "pages-draft-review--publication-failure",
  "pages-draft-review--validating", "pages-draft-review--loading", "pages-draft-review--read-failure", "pages-draft-review--action-failure",
  "pages-draft-review--admin-required", "pages-draft-review--published",
] as const;

export const IMPORT_EVIDENCE_STORY_IDS = [
  "pages-import-evidence--reference", "pages-import-evidence--source-collapsed", "pages-import-evidence--source-loading",
  "pages-import-evidence--source-read-failure", "pages-import-evidence--source-empty", "pages-import-evidence--notes-collapsed",
  "pages-import-evidence--notes-loading", "pages-import-evidence--notes-read-failure", "pages-import-evidence--notes-empty",
  "pages-import-evidence--append-failure", "pages-import-evidence--revision-editing", "pages-import-evidence--revision-failure", "pages-import-evidence--revision-saving",
] as const;

export const ADMIN_ACCOUNTS_STORY_IDS = [
  "pages-admin-accounts--reference", "pages-admin-accounts--create", "pages-admin-accounts--creating", "pages-admin-accounts--create-failure",
  "pages-admin-accounts--editing", "pages-admin-accounts--saving", "pages-admin-accounts--edit-failure", "pages-admin-accounts--conflict",
  "pages-admin-accounts--last-admin-protected", "pages-admin-accounts--loading", "pages-admin-accounts--read-failure",
  "pages-admin-accounts--empty", "pages-admin-accounts--access-denied", "pages-admin-accounts--updated",
] as const;

export const ADMIN_SITE_CONFIG_STORY_IDS = [
  "pages-admin-site-configuration--reference", "pages-admin-site-configuration--create", "pages-admin-site-configuration--creating",
  "pages-admin-site-configuration--create-failure", "pages-admin-site-configuration--loading", "pages-admin-site-configuration--read-failure",
  "pages-admin-site-configuration--empty", "pages-admin-site-configuration--access-denied", "pages-admin-site-configuration--multi-site",
] as const;

export const ADMIN_AUDIT_STORY_IDS = [
  "pages-admin-audit--reference", "pages-admin-audit--filtered", "pages-admin-audit--details",
  "pages-admin-audit--loading", "pages-admin-audit--read-failure", "pages-admin-audit--filter-failure",
  "pages-admin-audit--empty", "pages-admin-audit--busy", "pages-admin-audit--access-denied",
] as const;

export const ADMIN_MAINTENANCE_STORY_IDS = [
  "pages-admin-maintenance--reference", "pages-admin-maintenance--diagnostics", "pages-admin-maintenance--refreshing",
  "pages-admin-maintenance--refresh-failure", "pages-admin-maintenance--loading", "pages-admin-maintenance--read-failure",
  "pages-admin-maintenance--empty", "pages-admin-maintenance--consumer-failure", "pages-admin-maintenance--query-unknown",
  "pages-admin-maintenance--heartbeat-delayed", "pages-admin-maintenance--backup-failure", "pages-admin-maintenance--access-denied",
] as const;

export const ADMIN_RECOVERY_STORY_IDS = [
  "pages-admin-recovery--reference", "pages-admin-recovery--context", "pages-admin-recovery--confirmed",
  "pages-admin-recovery--submitting", "pages-admin-recovery--failure", "pages-admin-recovery--success",
  "pages-admin-recovery--unpublished", "pages-admin-recovery--loading", "pages-admin-recovery--read-failure", "pages-admin-recovery--access-denied",
] as const;

export const SESSION_ENTRY_STORY_IDS = [
  "pages-session-entry--reference", "pages-session-entry--filled", "pages-session-entry--login-failure", "pages-session-entry--submitting",
  "pages-session-entry--checking", "pages-session-entry--site-loading", "pages-session-entry--site-failure",
] as const;

export const PRODUCT_LEDGER_STORY_IDS = [
  "pages-product-ledger--reference", "pages-product-ledger--partial", "pages-product-ledger--empty", "pages-product-ledger--no-reports",
  "pages-product-ledger--zero-values", "pages-product-ledger--loading", "pages-product-ledger--refreshing", "pages-product-ledger--read-failure",
  "pages-product-ledger--access-denied", "pages-product-ledger--setup-required",
] as const;

export const COLUMN_SETTINGS_STORY_IDS = [
  "patterns-column-settings--reference", "patterns-column-settings--filtered-empty", "patterns-column-settings--identity-only",
  "patterns-column-settings--long-columns", "patterns-column-settings--many-columns", "patterns-column-settings--empty",
] as const;

export const COVERAGE_RECONCILIATION_STORY_IDS = [
  "patterns-coverage-reconciliation--reference", "patterns-coverage-reconciliation--partial", "patterns-coverage-reconciliation--no-reports",
  "patterns-coverage-reconciliation--zero-values", "patterns-coverage-reconciliation--unmatched", "patterns-coverage-reconciliation--long-values",
] as const;
export const LEDGER_METRIC_HELP_STORY_IDS = [
  "patterns-product-ledger-metric-help--sales", "patterns-product-ledger-metric-help--returns", "patterns-product-ledger-metric-help--report-date",
  "patterns-product-ledger-metric-help--narrow-screen", "patterns-product-ledger-metric-help--all-metrics",
] as const;

export const TREND_MATRIX_STORY_IDS = [
  "patterns-trend-point-matrix--reference", "patterns-trend-point-matrix--missing-and-partial", "patterns-trend-point-matrix--conversion-ratio",
  "patterns-trend-point-matrix--wide", "patterns-trend-point-matrix--long-values", "patterns-trend-point-matrix--empty",
] as const;
export const PRODUCT_TREND_CHART_STORY_IDS = [
  "patterns-product-trend-chart--reference", "patterns-product-trend-chart--single-series", "patterns-product-trend-chart--coincident-points",
  "patterns-product-trend-chart--missing-and-partial", "patterns-product-trend-chart--conversion-ratio", "patterns-product-trend-chart--selection-limit",
  "patterns-product-trend-chart--narrow", "patterns-product-trend-chart--empty", "patterns-product-trend-chart--single-day",
] as const;

export const METRIC_VALUE_STORY_IDS = [
  "patterns-metric-value--reference", "patterns-metric-value--zero-values", "patterns-metric-value--missing-report", "patterns-metric-value--undefined-denominator",
  "patterns-metric-value--partial", "patterns-metric-value--compact", "patterns-metric-value--percentage", "patterns-metric-value--long-values",
] as const;

export const SAFE_SOURCE_REFERENCE_STORY_IDS = [
  "patterns-safe-source-reference--reference", "patterns-safe-source-reference--long-preview", "patterns-safe-source-reference--truncated",
  "patterns-safe-source-reference--unsafe", "patterns-safe-source-reference--structural-characters", "patterns-safe-source-reference--combined",
] as const;

export const TABLE_HEADER_STORY_IDS = [
  "patterns-table-header--reference", "patterns-table-header--ascending", "patterns-table-header--descending",
  "patterns-table-header--return-report", "patterns-table-header--long-headers", "patterns-table-header--split-groups",
] as const;

export const VISUAL_STORY_IDS = [
  ...COVERAGE_RECONCILIATION_STORY_IDS,
  ...LEDGER_METRIC_HELP_STORY_IDS,
  ...TREND_MATRIX_STORY_IDS,
  ...PRODUCT_TREND_CHART_STORY_IDS,
  ...METRIC_VALUE_STORY_IDS,
  ...SAFE_SOURCE_REFERENCE_STORY_IDS,
  ...TABLE_HEADER_STORY_IDS,
  ...COLUMN_SETTINGS_STORY_IDS,
  ...CATALOG_MAINTENANCE_OVERVIEW_STORY_IDS,
  ...CATALOG_UNMATCHED_STORY_IDS,
  ...CATALOG_VERSION_STORY_IDS,
  ...CATALOG_READ_FEEDBACK_STORY_IDS,
  ...CATALOG_SECTION_EDITOR_STORY_IDS,
  ...CATALOG_PENDING_CANDIDATE_STORY_IDS,
  ...CATALOG_IMPORT_HISTORY_STORY_IDS,
  ...CATALOG_WORKBOOK_STORY_IDS,
  ...CATALOG_ISSUE_SUMMARY_STORY_IDS,
  ...CATALOG_SOURCE_EVIDENCE_STORY_IDS,
  ...CATALOG_IDENTITY_OWNER_STORY_IDS,
  ...CATALOG_WORKFLOW_FORM_STORY_IDS,
  ...DRAFT_DATA_TABLE_STORY_IDS,
  ...NOTE_REVISION_STORY_IDS,
  ...ISSUE_REVIEW_STORY_IDS,
  ...ROW_REVIEW_STORY_IDS,
  ...FIELD_REVIEW_STORY_IDS,
  ...PUBLICATION_CONFIRMATION_STORY_IDS,
  ...MERGE_DECISION_STORY_IDS,
  ...VERSION_COMMAND_STORY_IDS,
  ...ADVANCED_REVIEW_WORKSPACE_STORY_IDS,
  ...WORKSPACE_SHELL_STORY_IDS,
  ...PRODUCT_DETAIL_STORY_IDS,
  ...PRODUCT_LEDGER_STORY_IDS,
  ...SESSION_ENTRY_STORY_IDS,
  ...ADMIN_RECOVERY_STORY_IDS,
  ...ADMIN_MAINTENANCE_STORY_IDS,
  ...ADMIN_AUDIT_STORY_IDS,
  ...ADMIN_SITE_CONFIG_STORY_IDS,
  ...ADMIN_ACCOUNTS_STORY_IDS,
  ...IMPORT_EVIDENCE_STORY_IDS,
  ...DRAFT_REVIEW_STORY_IDS,
  ...IMPORT_INTAKE_STORY_IDS,
  ...BATCH_REVIEW_STORY_IDS,
  ...VERSION_HISTORY_STORY_IDS,
  ...DATE_WORKBENCH_STORY_IDS,
  ...PUBLISHED_DETAIL_LEDGER_STORY_IDS,
  ...PUBLISHED_DAY_STORY_IDS,
  ...PUBLISHED_DAILY_STORY_IDS,
  ...CATALOG_SETUP_STORY_IDS,
  ...CATALOG_EDITORS_STORY_IDS,
  ...CATALOG_STYLE_DETAIL_STORY_IDS,
  "design-system-interaction-feedback--click-spark-states",
  ...CATALOG_OPERATIONS_STORY_IDS,
  "design-system-actions-and-status--save-feedback",
  ...CATALOG_REVIEW_STORY_IDS,
  ...CATALOG_PRODUCT_LIST_STORY_IDS,
  "design-system-actions-and-status--button-states",
  "design-system-form-controls--global-defaults",
  "design-system-form-controls--field-states",
  "design-system-form-controls--review-controls",
  "design-system-actions-and-status--status-states",
  "design-system-structure-and-navigation--pagination-states",
  "design-system-structure-and-navigation--header",
  "design-system-structure-and-navigation--dialog-interaction",
  "design-system-selection-and-navigation--selection-states",
  "design-system-selection-and-navigation--composite-interactions",
  "design-system-selection-and-navigation--narrow-and-long-chinese",
  "design-system-feedback-and-data--toast-kinds",
  "design-system-feedback-and-data--loading-empty-and-error",
  "design-system-feedback-and-data--basic-table",
] as const;

export const VIEWPORTS = [
  { height: 900, name: "desktop", width: 1280 },
  { height: 900, name: "tablet", width: 768 },
  { height: 844, name: "mobile", width: 390 },
] as const;
