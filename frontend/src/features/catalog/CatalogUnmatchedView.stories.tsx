import type { Meta, StoryObj } from "@storybook/react-vite";
import { useState } from "react";
import { Link, MemoryRouter, Route, Routes, useLocation, useSearchParams } from "react-router-dom";
import { CatalogLayout } from "./CatalogLayout";
import { CatalogUnmatchedView, type PendingStyle } from "./CatalogUnmatchedView";
import type { CatalogUnmatchedResponse } from "./catalogApi";

type Scenario = "reference" | "multi-currency" | "long-preview" | "loading" | "empty" | "no-evidence" | "future-range" | "empty-page" | "pending-loading" | "pending-failure";
const query = "from=2026-09-01&to=2026-09-30&return_basis=event_date&return_to=%2Fproducts%3Fmonth%3D2026-09";
const sources: CatalogUnmatchedResponse = {
  page: 1, page_size: 2, total_items: 3,
  range: { from_date: "2026-09-01", to_date: "2026-09-30", return_basis: "event_date" },
  baseline: { catalog_version_id: 104, catalog_publication_revision: 7, consistent_as_of: "2026-09-30T18:00:00Z", fact_basis: "current", publication_refs: [{ version_id: "fictional-publication" }] },
  impact: { business_fact_rows: 3, units: 12, sales_by_currency: [{ currency_code: "USD", value: "119.90" }], return_fact_rows: 1, return_quantity: 1, unresolved_return_rows: 1 },
  items: [1, 2, 3].map(i => ({ source_identity: { report_source_scope_id: 1, seller_sku_match: `fictional-source-${i}`, seller_sku_sha256: `fictional-${i}` }, source_ref_id: null, preview: `DEMO-${i}-Blue-XL`, digest: `fictional-${i}`, is_unsafe: false, is_truncated: false, report_types: i === 2 ? ["business_report", "return_report"] : ["business_report"], first_seen_date: "2026-09-01", latest_seen_date: "2026-09-30", published_version_ids: ["fictional-publication"], business: { rows: 1, units: i === 1 ? 10 : i === 2 ? 2 : 0, sales_by_currency: [{ currency_code: "USD", value: i === 1 ? "99.90" : i === 2 ? "20.00" : "0.00" }] }, returns: { rows: i === 2 ? 1 : 0, quantity: i === 2 ? 1 : 0, unresolved_rows: i === 2 ? 1 : 0 }, candidate: { status: i === 1 ? "in_review" : i === 3 ? "draft" : "not_started", review_path: i === 2 ? null : `/catalog/imports/${900 + i}` } })),
};
const pending: PendingStyle[] = [{ style: { style_id: 1001, style_code: "DEMO-01", standard_name: "示例蓝色衬衫", category_id: 1, category_code: "SHIRT", category_name: "衬衫", category_recorded: true, status: "enabled", revision: 1, seller_sku_count: 2, variant_count: 1, source_summary: { first_seen_date: null, latest_seen_date: null, observation_count: 0, source_report_count: 0 } }, items: [{ import_id: 901, review_path: "/catalog/imports/901", status: "ready_for_approval", workflow_revision: 3, variant_count: 2, seller_sku_count: 3, seller_sku_previews: ["DEMO-01-Blue-XL"], updated_at: "2026-09-30" }] }];

function Workspace({ scenario }: { scenario: Scenario }) {
  const [parameters, setParameters] = useSearchParams();
  const location = useLocation();
  const page = Number(parameters.get("page")) || 1;
  const [recovered, setRecovered] = useState(false);
  const [styleReturn, setStyleReturn] = useState(`/catalog/unmatched?${query}`);
  const [sourceReturn, setSourceReturn] = useState(`/catalog/unmatched?${query}${scenario === "empty-page" ? "&page=2" : ""}`);
  const noFacts = ["empty", "no-evidence", "future-range"].includes(scenario);
  const items = sources.items.map(item => scenario === "long-preview" ? { ...item, preview: "DEMO-安全预览-".repeat(24), is_truncated: true, is_unsafe: true } : scenario === "multi-currency" && item.preview.startsWith("DEMO-2") ? { ...item, business: { ...item.business, sales_by_currency: [{ currency_code: "EUR", value: "20.00" }] } } : item);
  const value: CatalogUnmatchedResponse = { ...sources, page, total_items: noFacts ? 0 : 3, items: noFacts || scenario === "empty-page" && page === 2 ? [] : items.slice((page - 1) * 2, page * 2),
    range: scenario === "future-range" ? { ...sources.range, from_date: "2099-01-01", to_date: "2099-01-31" } : sources.range,
    baseline: { ...sources.baseline, publication_refs: ["no-evidence", "future-range"].includes(scenario) ? [] : sources.baseline.publication_refs },
    impact: noFacts ? { business_fact_rows: 0, units: 0, sales_by_currency: [], return_fact_rows: 0, return_quantity: 0, unresolved_return_rows: 0 } : { ...sources.impact, sales_by_currency: scenario === "multi-currency" ? [{ currency_code: "USD", value: "99.90" }, { currency_code: "EUR", value: "20.00" }] : sources.impact.sales_by_currency },
  };
  const current = `/catalog/unmatched?${parameters.toString()}`;
  return <CatalogLayout canManage><Routes>
    <Route path="/catalog/unmatched" element={<CatalogUnmatchedView unmatched={scenario === "loading" ? undefined : value} pending={scenario === "pending-loading" ? undefined : noFacts ? [] : pending} pendingError={scenario === "pending-failure" && !recovered ? { message: "示例：审核候选读取失败，来源清单仍可使用。", retry: true, setup: false } : undefined} onRetry={() => setRecovered(true)} onOpenStyle={() => setStyleReturn(current)} page={page} returnBasis="event_date" returnTo={parameters.get("return_to") ?? undefined} maintenancePath={`/catalog/maintenance?return_to=${encodeURIComponent(current)}`} changePage={next => { const p = new URLSearchParams(parameters); p.set("page", String(next)); setSourceReturn(`/catalog/unmatched?${p.toString()}`); setParameters(p); }} />} />
    <Route path="*" element={<section><h2>虚构关联结果</h2><p>目标路径：{location.pathname}{location.search}</p><Link to={location.pathname.startsWith("/catalog/styles/") ? styleReturn : parameters.get("return_to") ?? sourceReturn}>返回待归属来源</Link></section>} />
  </Routes><p>所有来源、商品与金额均为虚构数据；不请求实际 API、不生成或批准候选，刷新重置。</p></CatalogLayout>;
}
function UnmatchedStory({ scenario = "reference" }: { scenario?: Scenario }) { return <MemoryRouter initialEntries={[`/catalog/unmatched?${query}${scenario === "empty-page" ? "&page=2" : ""}`]}><Workspace scenario={scenario} /></MemoryRouter>; }
const meta = { title: "Patterns/Catalog Unmatched Sources", component: UnmatchedStory, parameters: { layout: "fullscreen" } } satisfies Meta<typeof UnmatchedStory>;
export default meta;
type Story = StoryObj<typeof meta>;
export const Reference: Story = { args: { scenario: "reference" } };
export const MultiCurrency: Story = { args: { scenario: "multi-currency" } };
export const LongPreview: Story = { args: { scenario: "long-preview" } };
export const Loading: Story = { args: { scenario: "loading" } };
export const Empty: Story = { args: { scenario: "empty" } };
export const NoEvidence: Story = { args: { scenario: "no-evidence" } };
export const FutureRange: Story = { args: { scenario: "future-range" } };
export const EmptyPage: Story = { args: { scenario: "empty-page" } };
export const PendingLoading: Story = { args: { scenario: "pending-loading" } };
export const PendingFailure: Story = { args: { scenario: "pending-failure" } };
