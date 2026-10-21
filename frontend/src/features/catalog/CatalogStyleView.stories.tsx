import type { Meta, StoryObj } from "@storybook/react-vite";
import { useCallback, useRef, useState } from "react";
import { Link, MemoryRouter, Route, Routes } from "react-router-dom";
import { CatalogLayout } from "./CatalogLayout";
import { CatalogPendingItems } from "./CatalogPendingItems";
import { CatalogStyleView, type CatalogStyleDetail, type CatalogVariantReaders } from "./CatalogStyleView";
import type { CatalogEvidenceItem } from "./catalogApi";

type Scenario = "reference" | "loading" | "empty" | "failure" | "readonly" | "aliases-loading" | "aliases-failure" | "evidence" | "evidence-failure" | "pending";
const summary = { source_report_count: 3, observation_count: 26, first_seen_date: "2026-07-01", latest_seen_date: "2026-09-30" };
const safeRef = (id: string, preview: string, truncated = false, unsafe = false) => ({ source_ref_id: id, preview, digest: `sha256:${"a".repeat(64)}`, is_truncated: truncated, is_unsafe: unsafe });
const detail: CatalogStyleDetail = { catalog_version_id: 4, catalog_publication_revision: 7, permissions: { can_edit: false, can_manage_categories: false },
  style: { style_id: 1001, style_code: "DEMO-01", standard_name: "浅蓝府绸衬衫", category_id: 2, category_code: "SHIRT", category_name: "衬衫", category_parent: { id: 1, code: "TOPS", display_name: "上装" }, category_recorded: true, status: "enabled", revision: 3, variant_count: 3, seller_sku_count: 6, source_summary: summary },
  skus: ["浅蓝 / S", "浅蓝 / M", "米白 / M"].map((text, i) => ({ sku_id: 2001 + i, style_id: 1001, internal_display_sku: `DEMO-01-${i === 2 ? "WHITE" : "BLUE"}-${i === 0 ? "S" : "M"}`, standard_color: text.split(" / ")[0]!, standard_size: text.split(" / ")[1]!, status: i === 2 ? "disabled" : "enabled", revision: 1, seller_sku_count: 2, source_summary: summary })),
};
const evidence: CatalogEvidenceItem[] = [
  { evidence_id: 1, dataset_id: 5, report_type: "business_report", report_date: "2026-07-02", event_date: "2026-07-01", published_version_id: 7, source_row_id: 44, source_filename: "demo-business.csv", source_record_number: 5, seller_sku: safeRef("demo:1", "DEMO-BLUE-S-OLD"), title: safeRef("demo:title", "示例浅蓝府绸衬衫"), child_asin: null, fnsku: null, parent_asin: null, evidence_digest: `sha256:${"b".repeat(64)}` },
  { evidence_id: 2, dataset_id: 6, report_type: "return_report", report_date: "2026-07-03", event_date: "2026-07-02", published_version_id: 8, source_row_id: 90, source_filename: "demo-returns.csv", source_record_number: 12, source_event_timestamp: "2026-07-02T23:00:00-07:00", source_timezone: "America/Los_Angeles", seller_sku: safeRef("demo:2", "较长的销售编码示例…", true), title: safeRef("demo:title2", "含需安全处理字符的示例标题", false, true), child_asin: null, fnsku: null, parent_asin: null, evidence_digest: `sha256:${"c".repeat(64)}` },
];

function ReferencePage({ scenario = "reference" }: { scenario?: Scenario }) {
  const [ready, setReady] = useState(scenario !== "loading" && scenario !== "failure");
  const [reading, setReading] = useState(scenario === "loading");
  const [failed, setFailed] = useState(scenario === "failure");
  const aliasReads = useRef(0);
  const evidenceReads = useRef(0);
  const loadAliases = useCallback<CatalogVariantReaders["aliases"]>(async skuId => {
    const first = aliasReads.current++ === 0;
    if (scenario === "aliases-loading") return new Promise(() => undefined);
    await new Promise(resolve => window.setTimeout(resolve, 300));
    if (scenario === "aliases-failure" && first) throw new Error("Synthetic alias read failure");
    return { page: 1, page_size: 50, total_items: 2, items: ["OLD", "NEW"].map((suffix, i) => ({ mapping_id: skuId * 10 + i, mapping_status: "mapped", marketplace: "amazon_us", seller_account: "示例美国账号", seller_sku: safeRef(`demo:${skuId}:${i}`, `DEMO-BLUE-S-${suffix}`), source_summary: summary })) };
  }, [scenario]);
  const loadEvidence = useCallback<CatalogVariantReaders["evidence"]>(async () => {
    const first = evidenceReads.current++ === 0;
    await new Promise(resolve => window.setTimeout(resolve, 300));
    if (scenario === "evidence-failure" && first) throw new Error("Synthetic evidence read failure");
    return { page: 1, page_size: 50, total_items: evidence.length, items: evidence };
  }, [scenario]);
  const refresh = () => { setReading(true); setFailed(false); window.setTimeout(() => { setReady(true); setReading(false); }, 400); };
  const value = ready ? scenario === "empty" ? { ...detail, skus: [], style: { ...detail.style, variant_count: 0 } } : detail : undefined;
  const pending = scenario === "pending" ? <CatalogPendingItems canReview items={[{ import_id: 42, review_path: "/catalog/imports/42", seller_sku_count: 1, seller_sku_previews: ["DEMO-NAVY-L"], status: "needs_attention", updated_at: "2026-10-06T08:00:00Z", variant_count: 1, workflow_revision: 2 }]} /> : undefined;
  return <MemoryRouter initialEntries={["/catalog/styles/1001"]}><CatalogLayout canManage={scenario !== "readonly"}><Routes>
    <Route path="/catalog/styles/1001" element={<CatalogStyleView value={value} reading={reading} failure={failed ? { message: "示例：连接暂时不可用，请重新读取商品。", retry: true, setup: false } : undefined} onRefresh={refresh} readers={{ aliases: loadAliases, evidence: loadEvidence }} pending={pending} />} />
    <Route path="*" element={<section><h2>虚构导航结果</h2><p>仅演示返回、审核入口及报告版本链接，不执行实际维护或批准。</p><Link to="/catalog/styles/1001">返回示例商品</Link></section>} />
  </Routes><p>商品、变体、账号和来源均为虚构样例；不会请求实际 API。修改与批准仍由实际页面原有权限和草稿流程提供。</p></CatalogLayout></MemoryRouter>;
}

const meta = { title: "Pages/Catalog Style Detail", component: ReferencePage, parameters: { layout: "fullscreen" } } satisfies Meta<typeof ReferencePage>;
export default meta;
type Story = StoryObj<typeof meta>;
export const Reference: Story = { args: { scenario: "reference" } };
export const Loading: Story = { args: { scenario: "loading" } };
export const Empty: Story = { args: { scenario: "empty" } };
export const ReadFailure: Story = { args: { scenario: "failure" } };
export const ReadOnly: Story = { args: { scenario: "readonly" } };
export const AliasesLoading: Story = { args: { scenario: "aliases-loading" } };
export const AliasesFailure: Story = { args: { scenario: "aliases-failure" } };
export const Evidence: Story = { args: { scenario: "evidence" } };
export const EvidenceFailure: Story = { args: { scenario: "evidence-failure" } };
export const PendingCandidates: Story = { args: { scenario: "pending" } };
