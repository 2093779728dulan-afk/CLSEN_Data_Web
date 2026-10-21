import type { Meta, StoryObj } from "@storybook/react-vite";
import { useState } from "react";
import { Link, MemoryRouter, Route, Routes, useNavigate } from "react-router-dom";
import { StatusMessage } from "../../design-system";
import { CatalogReadFailurePanel } from "./CatalogReadFailure";
import { CatalogLayout } from "./CatalogLayout";
import { CatalogVersionsView } from "./CatalogVersionsView";
import { CatalogUnmatchedView, type PendingStyle } from "./CatalogUnmatchedView";
import { CatalogMaintenanceOverview } from "./CatalogMaintenanceOverview";
import { CatalogImportHistoryView } from "./CatalogImportHistoryView";
import { CatalogExportView } from "./CatalogExportView";
import type { CatalogExportStatus, CatalogUnmatchedResponse, CurrentCatalog } from "./catalogApi";

type Scenario = "versions" | "versions-empty" | "versions-loading" | "versions-failure" | "unmatched" | "unmatched-loading" | "no-evidence" | "unmatched-empty" | "pending-failure" | "maintenance" | "uninitialized" | "building" | "failed" | "stale" | "capacity";
const catalog: CurrentCatalog = { catalog_version_id: 4, version_number: 4, catalog_publication_revision: 7, styles: [], skus: [] };
const versions = [{ id: 4, version_number: 4, risk: "normal", approved_at: "2026-09-30 14:20", base_catalog_version_id: 3 }, { id: 3, version_number: 3, risk: "needs_review", approved_at: "2026-09-20 09:40", base_catalog_version_id: 2 }, { id: 2, version_number: 2, risk: "normal", approved_at: "2026-09-02 16:10", base_catalog_version_id: null }];
const sources: CatalogUnmatchedResponse = {
  page: 1, page_size: 25, total_items: 26,
  range: { from_date: "2026-09-01", to_date: "2026-09-30", return_basis: "event_date" },
  baseline: { catalog_version_id: 4, catalog_publication_revision: 7, consistent_as_of: "2026-09-30T18:00:00Z", fact_basis: "current", publication_refs: [{ version_id: 1 }] },
  impact: { business_fact_rows: 38, units: 42, sales_by_currency: [{ currency_code: "USD", value: "1258.40" }, { currency_code: "EUR", value: "87.20" }], return_fact_rows: 3, return_quantity: 3, unresolved_return_rows: 1 },
  items: [1, 2, 3].map(i => ({ source_identity: { report_source_scope_id: 1, seller_sku_match: `demo-source-${i}`, seller_sku_sha256: `fictional-${i}` }, source_ref_id: null, preview: `DEMO-${i}-Light-Blue-XL`, digest: `fictional-${i}`, is_unsafe: false, is_truncated: false, report_types: i === 2 ? ["business_report", "return_report"] : ["business_report"], first_seen_date: "2026-09-01", latest_seen_date: "2026-09-30", published_version_ids: ["1"], business: { rows: 12, units: 14, sales_by_currency: [{ currency_code: "USD", value: "419.46" }] }, returns: { rows: 1, quantity: 1, unresolved_rows: 0 }, candidate: { status: i === 1 ? "in_review" : "not_started", review_path: i === 1 ? "/catalog/imports/901" : null } })),
};
const pending: PendingStyle[] = [{ style: { style_id: 1001, style_code: "DEMO-01", standard_name: "示例浅蓝衬衫", category_id: 1, category_code: "SHIRT", category_name: "衬衫", category_recorded: true, status: "enabled", revision: 1, seller_sku_count: 2, variant_count: 1, source_summary: { first_seen_date: null, latest_seen_date: null, observation_count: 0, source_report_count: 0 } }, items: [{ import_id: 901, review_path: "/catalog/imports/901", status: "ready_for_approval", workflow_revision: 3, variant_count: 2, seller_sku_count: 3, seller_sku_previews: ["DEMO-01-Blue-XL"], updated_at: "2026-09-30" }] }];
const ready: CatalogExportStatus = { export_id: 8001, base_catalog_version_id: 4, catalog_publication_revision: 7, export_status: "ready", job_status: "succeeded", job_revision: 2, execution_phase: "completed", attempt_count: 1, max_attempts: 3, next_attempt_at: null, retry_allowed: false, worker_available: true, workbook_status: "ready", permissions: { can_download: false, can_resume: false }, capacity_violations: [], failure_reason_code: null };

function Workspace({ scenario }: { scenario: Scenario }) {
  const navigate = useNavigate();
  const [recovered, setRecovered] = useState(false);
  const [page, setPage] = useState(1);
  const [file, setFile] = useState<File>();
  const [exported, setExported] = useState<CatalogExportStatus | undefined>(() => scenario === "uninitialized" ? undefined : scenario === "building" ? { ...ready, export_status: "building", job_status: "running", execution_phase: "materializing", workbook_status: null } : scenario === "failed" ? { ...ready, export_status: "failed", job_status: "failed", execution_phase: "awaiting_manual_recovery", workbook_status: null, failure_reason_code: "demo_worker_unavailable", permissions: { can_download: false, can_resume: true } } : scenario === "stale" ? { ...ready, catalog_publication_revision: 6 } : scenario === "capacity" ? { ...ready, workbook_status: "capacity_exceeded" } : ready);
  const failure = <CatalogReadFailurePanel failure={{ message: "示例：连接暂时不可用，原目录数据未被修改。", retry: true, setup: false }} onRetry={() => setRecovered(true)} />;
  const empty = scenario === "unmatched-empty" || scenario === "no-evidence";
  const value = empty ? { ...sources, total_items: 0, items: [], impact: { ...sources.impact, business_fact_rows: 0, return_fact_rows: 0, units: 0, return_quantity: 0, unresolved_return_rows: 0, sales_by_currency: [] }, baseline: { ...sources.baseline, publication_refs: scenario === "no-evidence" ? [] : sources.baseline.publication_refs } } : { ...sources, page, items: page === 1 ? sources.items : sources.items.slice(0, 1) };
  return <CatalogLayout canManage><Routes>
    <Route path="/catalog/versions" element={scenario === "versions-failure" && !recovered ? failure : <CatalogVersionsView versions={scenario === "versions-loading" ? undefined : scenario === "versions-empty" ? [] : versions} onReload={() => setRecovered(true)} />} />
    <Route path="/catalog/unmatched" element={<CatalogUnmatchedView unmatched={scenario === "unmatched-loading" ? undefined : value} pending={pending} pendingError={scenario === "pending-failure" && !recovered ? { message: "示例：审核候选读取失败，来源清单仍可使用。", retry: true, setup: false } : undefined} onRetry={() => setRecovered(true)} onOpenStyle={() => undefined} page={page} returnBasis="event_date" maintenancePath="/catalog/maintenance?return_to=%2Fcatalog%2Funmatched" changePage={setPage} />} />
    <Route path="/catalog/maintenance" element={<div className="catalog-stack">
      <CatalogMaintenanceOverview catalog={scenario === "uninitialized" ? null : catalog} />
      <StatusMessage kind={scenario === "uninitialized" ? "warning" : "info"} title="来源准备状态样例">此处仅展示虚构前置状态。实际页面的来源账号确认与退货快照操作沿用 CatalogSetup；故事不执行这些写入。</StatusMessage>
      <CatalogImportHistoryView result={{ items: page === 1 ? [{ import_id: 901, source_kind: "online", status: "ready_for_approval", workflow_revision: 3 }, { import_id: 902, source_kind: "xlsx", status: "approved", workflow_revision: 6 }, { import_id: 903, source_kind: "xlsx", status: "parse_failed", workflow_revision: 1 }] : [], has_next: page === 1 }} page={page} onPageChange={setPage} onReload={() => setPage(1)} onOpenReview={() => undefined} />
      <CatalogExportView current={exported} catalogPublicationRevision={7} generationReady={scenario !== "uninitialized"} busy={false} selectedFile={file} onFileChange={setFile} onCreate={() => setExported(ready)} onResume={() => setExported(ready)} onStartOnline={() => { void navigate("/catalog/imports/901"); }} onUpload={() => { void navigate("/catalog/imports/904"); }} />
    </div>} />
    <Route path="*" element={<section><h2>虚构导航结果</h2><p>仅确认导航，不模拟真实商品维护、批准或文件写入。</p><Link to="/catalog/unmatched">返回待处理</Link><br /><Link to="/catalog/maintenance">返回批量维护</Link></section>} />
  </Routes><p>所有身份、批次、文件与数据均为虚构样例，不发送实际 API 请求。</p></CatalogLayout>;
}
function Reference({ scenario = "versions" }: { scenario?: Scenario }) {
  const route = scenario.startsWith("versions") ? "/catalog/versions" : ["unmatched", "unmatched-loading", "no-evidence", "unmatched-empty", "pending-failure"].includes(scenario) ? "/catalog/unmatched" : "/catalog/maintenance";
  return <MemoryRouter initialEntries={[route]}><Workspace scenario={scenario} /></MemoryRouter>;
}
const meta = { title: "Pages/Catalog Operations", component: Reference, parameters: { layout: "fullscreen" } } satisfies Meta<typeof Reference>;
export default meta;
type Story = StoryObj<typeof meta>;
export const Versions: Story = { args: { scenario: "versions" } };
export const VersionsEmpty: Story = { args: { scenario: "versions-empty" } };
export const VersionsLoading: Story = { args: { scenario: "versions-loading" } };
export const VersionsFailure: Story = { args: { scenario: "versions-failure" } };
export const Unmatched: Story = { args: { scenario: "unmatched" } };
export const UnmatchedLoading: Story = { args: { scenario: "unmatched-loading" } };
export const NoPublicationEvidence: Story = { args: { scenario: "no-evidence" } };
export const UnmatchedEmpty: Story = { args: { scenario: "unmatched-empty" } };
export const PendingFailure: Story = { args: { scenario: "pending-failure" } };
export const Maintenance: Story = { args: { scenario: "maintenance" } };
export const Uninitialized: Story = { args: { scenario: "uninitialized" } };
export const Building: Story = { args: { scenario: "building" } };
export const GenerationFailed: Story = { args: { scenario: "failed" } };
export const StaleCandidate: Story = { args: { scenario: "stale" } };
export const CapacityExceeded: Story = { args: { scenario: "capacity" } };
