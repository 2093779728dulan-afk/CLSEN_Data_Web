import {
  commandApi,
  createOperationKey,
  requestApi,
  writeApi,
  type SafeErrorField,
} from "../../api/client";
import type {
  CatalogImportRow,
  CatalogImportSummary,
  CatalogSection,
} from "./catalogTypes";
import type { SafeSourceRef } from "../../components/source-reference/SafeSourceRefView";

export type CatalogSourceSummary = {
  first_seen_date: string | null;
  latest_seen_date: string | null;
  observation_count: number;
  source_report_count: number;
};

export type CatalogStyle = {
  category_parent?: { id: number; code: string; display_name: string } | null;
  category_code: string | null;
  category_id: number | null;
  category_name: string | null;
  category_recorded: boolean;
  revision: number;
  standard_name: string;
  status: string;
  style_code: string;
  style_id: number;
  variant_count: number;
  seller_sku_count: number;
  source_summary: CatalogSourceSummary;
};

export type CatalogCategory = {
  parent_category_id?: number | null;
  aliases: string[];
  category_id: number;
  code: string;
  display_name: string;
  status: "enabled" | "disabled";
};

export type CatalogStyleChangePreview = {
  after: { standard_name: string; category: { category_id: number | null; code: string | null; display_name: string | null; parent_name?: string | null } };
  base_catalog_publication_revision: number;
  before: { standard_name: string; category: { category_id: number | null; code: string | null; display_name: string | null; parent_name?: string | null } };
  draft_id: number;
  draft_revision: number;
  status: "draft" | "approved";
  style_code: string;
  style_id: number;
};

export type CatalogSku = {
  internal_display_sku: string;
  revision: number;
  sku_id: number;
  standard_color: string;
  standard_size: string;
  status: string;
  style_id: number;
  seller_sku_count: number;
  source_summary: CatalogSourceSummary;
};

export type CatalogPendingItem = {
  import_id: number;
  review_path: string;
  seller_sku_count: number;
  seller_sku_previews: string[];
  status: "needs_attention" | "validated" | "ready_for_approval";
  updated_at: string;
  variant_count: number;
  workflow_revision: number;
};

export type CatalogSellerSkuAlias = {
  mapping_id: number;
  mapping_status: "mapped";
  marketplace: string;
  seller_account: string;
  seller_sku: SafeSourceRef;
  source_summary: CatalogSourceSummary;
};

export type CatalogEvidenceItem = {
  child_asin: SafeSourceRef | null;
  dataset_id: number;
  event_date: string | null;
  evidence_digest: string;
  evidence_id: number;
  fnsku: SafeSourceRef | null;
  parent_asin: SafeSourceRef | null;
  published_version_id: number;
  report_date: string;
  report_type: "business_report" | "return_report";
  seller_sku: SafeSourceRef;
  source_row_id: number;
  source_filename?: string | null;
  source_record_number?: number | null;
  source_event_timestamp?: string | null;
  source_timezone?: string | null;
  title: SafeSourceRef | null;
};

export type CatalogPage<T> = {
  items: T[];
  page: number;
  page_size: number;
  total_items: number;
};

export type CatalogUnmatchedItem = {
  source_identity: { report_source_scope_id: number; seller_sku_sha256: string; seller_sku_match: string };
  source_ref_id: null;
  preview: string;
  digest: string;
  is_unsafe: boolean;
  is_truncated: boolean;
  report_types: Array<"business_report" | "return_report">;
  first_seen_date: string;
  latest_seen_date: string;
  published_version_ids: string[];
  business: { rows: number; units: number; sales_by_currency: Array<{ currency_code: string; value: string }> };
  returns: { rows: number; quantity: number; unresolved_rows: number };
  candidate: { status: "not_started" | "draft" | "in_review" | "completed"; workflow_status?: string; review_path: string | null };
};

export type CatalogUnmatchedResponse = CatalogPage<CatalogUnmatchedItem> & {
  range: { from_date: string; to_date: string; return_basis: "event_date" | "report_date" };
  baseline: { catalog_version_id: number | null; catalog_publication_revision: number; fact_basis: "current"; consistent_as_of: string; publication_refs: Array<Record<string, unknown>> };
  impact: { business_fact_rows: number; units: number; sales_by_currency: Array<{ currency_code: string; value: string }>; return_fact_rows: number; return_quantity: number; unresolved_return_rows: number };
};

export type CurrentCatalog = {
  catalog_publication_revision: number;
  catalog_version_id: number;
  skus: CatalogSku[];
  styles: CatalogStyle[];
  version_number: number;
};

export type CatalogExportStatus = {
  base_catalog_version_id: number | null;
  capacity_violations: unknown[];
  catalog_publication_revision: number;
  export_id: number;
  export_status: "building" | "failed" | "ready";
  failure_reason_code: string | null;
  job_status: "failed" | "queued" | "running" | "succeeded";
  job_revision: number;
  execution_phase: "awaiting_manual_recovery" | "completed" | "failed" | "materializing" | "retry_scheduled" | "waiting_for_worker";
  attempt_count: number;
  max_attempts: number;
  next_attempt_at: string | null;
  retry_allowed: boolean;
  worker_available: boolean;
  permissions: { can_download: boolean; can_resume: boolean };
  workbook_status: "capacity_exceeded" | "ready" | null;
};

export type CatalogRowsPage = {
  import_id: number;
  page: number;
  page_size: number;
  parse_attempt_revision: number;
  rows: CatalogImportRow[];
  section: CatalogSection;
  total_rows: number;
  workflow_revision: number;
};

export type CommandResult = Record<string, unknown> & {
  workflow_revision?: number;
};

const CATALOG_SAFE_ERRORS: readonly SafeErrorField[] = [
  "catalog_publication_revision",
  "issues",
  "parse_attempt_revision",
  "workflow_revision",
];

function resultPayload(value: unknown): CommandResult {
  if (!value || typeof value !== "object") throw new Error("Catalog response is invalid.");
  const record = value as Record<string, unknown>;
  const payload = record.safe_result;
  return payload && typeof payload === "object" ? payload as CommandResult : record;
}
export async function getCurrentCatalog(): Promise<CurrentCatalog | null> {
  const response = await requestApi<{ catalog: CurrentCatalog | null }>("/api/catalog/styles");
  return response.catalog;
}

export function getCatalogStyle(styleId: number) {
  return requestApi<{ catalog_version_id: number; catalog_publication_revision: number; permissions: { can_edit: boolean; can_manage_categories: boolean }; skus: CatalogSku[]; style: CatalogStyle }>(
    `/api/catalog/styles/${styleId}`,
  );
}

export async function createCatalogExport(catalogPublicationRevision: number) {
  const operationKey = createOperationKey();
  return commandApi<CatalogExportStatus>(
    "/api/catalog/exports",
    { expected_catalog_publication_revision: catalogPublicationRevision, operation_token: operationKey },
    operationKey,
    CATALOG_SAFE_ERRORS,
  );
}

export function getCatalogExport(exportId: number) {
  return requestApi<CatalogExportStatus>(`/api/catalog/exports/${exportId}`);
}

export async function listCatalogCategories() {
  const value = await requestApi<{ categories: CatalogCategory[] }>("/api/catalog/categories");
  return value.categories;
}

export async function createCatalogCategory(code: string, displayName: string, aliases: string[], parentCategoryId: number | null = null) {
  const operationKey = createOperationKey();
  return commandApi<CatalogCategory>("/api/catalog/categories", { operation_token: operationKey, code, display_name: displayName, aliases, parent_category_id: parentCategoryId }, operationKey, CATALOG_SAFE_ERRORS);
}

export async function updateCatalogCategory(category: CatalogCategory) {
  const operationKey = createOperationKey();
  return writeApi<CatalogCategory>(`/api/catalog/categories/${category.category_id}`, {
    body: { operation_token: operationKey, code: category.code, parent_category_id: category.parent_category_id ?? null, display_name: category.display_name, aliases: category.aliases, status: category.status },
    method: "PUT", operationKey,
  });
}

export async function createStyleChangeDraft(style: CatalogStyle, catalogPublicationRevision: number, standardName: string, categoryId: number | null) {
  const operationKey = createOperationKey();
  const categoryAction = categoryId === style.category_id ? "keep" : categoryId === null ? "clear" : "set";
  const result = await commandApi<{ draft_id: number }>(`/api/catalog/styles/${style.style_id}/change-drafts`, {
    operation_token: operationKey, expected_catalog_publication_revision: catalogPublicationRevision,
    expected_style_revision: style.revision, standard_name: standardName,
    category_action: categoryAction, category_id: categoryAction === "set" ? categoryId : null,
  }, operationKey, CATALOG_SAFE_ERRORS);
  return getStyleChangePreview(result.draft_id);
}

export function getStyleChangePreview(draftId: number) {
  return requestApi<CatalogStyleChangePreview>(`/api/catalog/style-change-drafts/${draftId}`);
}

export async function approveStyleChange(preview: CatalogStyleChangePreview, reason: string) {
  const operationKey = createOperationKey();
  return commandApi<{ catalog_version_id: number; catalog_publication_revision: number }>(`/api/catalog/style-change-drafts/${preview.draft_id}/approve`, {
    operation_token: operationKey, expected_draft_revision: preview.draft_revision,
    expected_catalog_publication_revision: preview.base_catalog_publication_revision, reason,
  }, operationKey, CATALOG_SAFE_ERRORS);
}

export function getCatalogVariantSellerSkus(skuId: number, page = 1) {
  return requestApi<CatalogPage<CatalogSellerSkuAlias>>(
    `/api/catalog/variants/${skuId}/seller-skus?page=${page}&page_size=50`,
  );
}

export function getCatalogStylePendingItems(styleId: number) {
  return requestApi<{ items: CatalogPendingItem[]; permissions: { can_review: boolean } }>(
    `/api/catalog/styles/${styleId}/pending-items`,
  );
}

export function getCatalogVariantEvidence(skuId: number, page = 1) {
  return requestApi<CatalogPage<CatalogEvidenceItem>>(
    `/api/catalog/variants/${skuId}/evidence?page=${page}&page_size=50`,
  );
}

export async function getLatestCatalogExport() {
  const response = await requestApi<{ export: CatalogExportStatus | null }>(
    "/api/catalog/exports/latest",
  );
  return response.export ?? undefined;
}

export async function resumeCatalogExport(exportId: number, expectedJobRevision: number) {
  const operationKey = createOperationKey();
  await commandApi<{ export_id: number; job_revision: number; job_status: "queued" }>(
    `/api/catalog/exports/${exportId}/resume`,
    { expected_job_revision: expectedJobRevision, operation_token: operationKey },
    operationKey,
    CATALOG_SAFE_ERRORS,
  );
  return getCatalogExport(exportId);
}

export async function createImportFromExport(exportId: number, catalogPublicationRevision: number) {
  const operationKey = createOperationKey();
  return commandApi<CatalogImportSummary>(
    "/api/catalog/imports/from-export",
    {
      expected_catalog_publication_revision: catalogPublicationRevision,
      export_id: exportId,
      operation_token: operationKey,
    },
    operationKey,
    CATALOG_SAFE_ERRORS,
  );
}

export async function uploadCatalogWorkbook(file: File, operationKey: string) {
  return writeApi<{ catalog_import_id: number }>("/api/catalog/imports", {
    headers: {
      "Content-Type": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
      "X-Original-Filename": encodeURIComponent(file.name),
    },
    operationKey,
    rawBody: file,
  });
}

export function getCatalogImport(importId: number) {
  return requestApi<CatalogImportSummary>(`/api/catalog/imports/${importId}`);
}

export function getCatalogRows(importId: number, section: CatalogSection, workflowRevision: number, page = 1) {
  const query = new URLSearchParams({
    page: String(page),
    page_size: "200",
    workflow_revision: String(workflowRevision),
  });
  return requestApi<CatalogRowsPage>(
    `/api/catalog/imports/${importId}/rows/${section}?${query.toString()}`,
  );
}

export async function catalogCommand(
  importId: number,
  command: string,
  workflowRevision: number,
  extra: Record<string, unknown> = {},
) {
  const operationKey = createOperationKey();
  const response = await commandApi<unknown>(
    `/api/catalog/imports/${importId}/${command}`,
    {
      expected_workflow_revision: workflowRevision,
      operation_token: operationKey,
      ...extra,
    },
    operationKey,
    CATALOG_SAFE_ERRORS,
  );
  return resultPayload(response);
}

export async function saveCatalogMutation(
  importId: number,
  workflowRevision: number,
  mutation: Omit<Record<string, unknown>, "mutation_id">,
) {
  return saveCatalogMutations(importId, workflowRevision, [mutation]);
}

export async function saveCatalogMutations(
  importId: number,
  workflowRevision: number,
  mutations: Array<Omit<Record<string, unknown>, "mutation_id">>,
) {
  const operationKey = createOperationKey();
  const response = await commandApi<unknown>(
    `/api/catalog/imports/${importId}/decisions`,
    {
      expected_workflow_revision: workflowRevision,
      mutations: mutations.map(mutation => ({ mutation_id: createOperationKey(), ...mutation })),
      operation_token: operationKey,
    },
    operationKey,
    CATALOG_SAFE_ERRORS,
  );
  return resultPayload(response);
}

export function listCatalogVersions() {
  return requestApi<{ versions: Array<Record<string, unknown>> }>("/api/catalog/versions");
}

export function listCatalogUnmatched(options: { from?: string; to?: string; returnBasis?: "event_date" | "report_date"; page?: number; pageSize?: number } = {}) {
  const query = new URLSearchParams({ page: String(options.page ?? 1), page_size: String(options.pageSize ?? 25), return_basis: options.returnBasis ?? "event_date" });
  if (options.from) query.set("from", options.from);
  if (options.to) query.set("to", options.to);
  return requestApi<CatalogUnmatchedResponse>(`/api/catalog/unmatched?${query.toString()}`);
}
