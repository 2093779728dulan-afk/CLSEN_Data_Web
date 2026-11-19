export const CATALOG_SECTIONS = ["styles", "skus", "mappings", "exceptions", "evidence"] as const;
export type CatalogSection = (typeof CATALOG_SECTIONS)[number];

export type CatalogPermissionSet = {
  can_approve_high_risk: boolean;
  can_approve_normal: boolean;
  can_download_original: boolean;
  can_edit: boolean;
  can_preview: boolean;
  can_rebase: boolean;
  can_reject: boolean;
  can_resume: boolean;
  can_submit: boolean;
  can_validate: boolean;
  can_view: boolean;
  can_withdraw: boolean;
};

export type CatalogImportSummary = {
  registration_summary?: { products: number; reused: number; created: number; mappings: number } | null;
  record_kind?: "listing_source" | "catalog_review";
  review_path?: string;
  source_path?: string | null;
  issues?: CatalogRowIssue[];
  approved_catalog_version_number?: number | null;
  base_catalog_version_id: number | null;
  catalog_publication_revision: number;
  export_id: number;
  failure_reason_code: string | null;
  has_original_file: boolean;
  import_id: number;
  parse_attempt_revision: number;
  permissions: CatalogPermissionSet;
  source_kind: "online" | "xlsx" | "production";
  production_source?: { sku_format_policy?: string; format_adjustments?: { field: string; location: string; before: string; after: string; reason: string }[]; report_selection?: { version: number; request: { source_key: string; scope_id: number; version_ids: number[] }; source_rows: { seller_sku: string }[] }; source_schema?: string; parent_import_id?: number; source_name: string; digest: string; recorded_at: string; rows: { style_code: string; color: string; size: string }[] } | null;
  status: string;
  submitted_by_user_id: number | null;
  validation_run_id: number | null;
  workflow_revision: number;
};

export type CatalogImportRow = {
  display_sku_choice?: { options: { value: string; label: string }[]; message: string };
  payload: Record<string, string | number | null>;
  projection_state: "audit_only" | "included";
  row_key: string;
  row_origin: "system" | "user_created";
  section: CatalogSection;
};

export type CatalogRowIssue = {
  section: CatalogSection;
  row_key: string | null;
  severity: string;
  reason_code: string;
  field: string | null;
};

export type CatalogStatusDisplay = {
  label: string;
  tone: "bad" | "good" | "quiet" | "warn";
};

export type CatalogNameSuggestion = { name: string; source: string };

/** Display only: keep the persisted name empty until a name is confirmed. */
export function catalogNameDisplay(name: string | null | undefined): string {
  return name?.trim() || "名称待补";
}

export function catalogStatusDisplay(status: string): CatalogStatusDisplay {
  switch (status.trim().toLowerCase()) {
    case "active":
    case "enabled":
      return { label: "已启用", tone: "good" };
    case "disabled":
    case "inactive":
      return { label: "已停用", tone: "quiet" };
    case "failed":
      return { label: "失败", tone: "bad" };
    case "needs_attention":
      return { label: "待处理", tone: "warn" };
    default:
      return { label: status, tone: "quiet" };
  }
}

export function nextCatalogPath(importId: number): string {
  if (!Number.isSafeInteger(importId) || importId < 1) throw new Error("Invalid import ID.");
  return `/catalog/imports/${importId}`;
}

export function isEditableSection(section: CatalogSection): boolean {
  return section !== "evidence";
}

export type CatalogDraftSaveAction = { label: string; disabled: boolean; run: () => void };

export type CatalogSaveRecovery = { workflowRevision: number; canEdit: boolean; unchanged: boolean };
