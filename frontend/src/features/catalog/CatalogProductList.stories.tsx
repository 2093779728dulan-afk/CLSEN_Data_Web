import type { Meta, StoryObj } from "@storybook/react-vite";
import { useCallback, useRef, useState } from "react";
import { Link, MemoryRouter, Route, Routes, useParams } from "react-router-dom";
import { CatalogStyleView } from "./CatalogStyleView";
import { CatalogLayout } from "./CatalogLayout";
import { CatalogProductList } from "./CatalogProductList";
import type { CatalogStyleLoader } from "./CatalogProductDrawer";
import type { CurrentCatalog } from "./catalogApi";
import type { CatalogListState } from "./CatalogNavigationContext";

type Scenario = "reference" | "table" | "loading" | "empty" | "uninitialized" | "no-results" | "failure" | "readonly" | "quick-view" | "quick-view-loading" | "quick-view-failure" | "refreshing" | "refresh-failure";
const names = ["暖灰直筒长裤", "浅蓝府绸衬衫", "米白针织开衫", "薄荷绿短袖衬衫", "深蓝棉质外套", "较长的示例商品名称用于核对窄屏换行与商品身份可读性"];
const catalog: CurrentCatalog = { catalog_publication_revision: 7, catalog_version_id: 4, version_number: 4, skus: [], styles: Array.from({ length: 18 }, (_, i) => ({
  style_id: 1001 + i, style_code: `DEMO-${String(i + 1).padStart(2, "0")}`, standard_name: names[i % names.length]! + (i >= 6 ? ` · 示例 ${i + 1}` : ""),
  category_id: i % 3, category_code: ["PANTS", "SHIRT", "KNIT"][i % 3]!, category_name: ["长裤", "衬衫", "针织"][i % 3]!, category_recorded: true,
  revision: 1, status: i % 4 === 0 ? "disabled" : i % 4 === 1 ? "active" : "enabled", variant_count: 2 + i % 3, seller_sku_count: 3 + i % 4,
  source_summary: { first_seen_date: "2026-07-01", latest_seen_date: i % 3 === 0 ? null : "2026-09-30", source_report_count: 3, observation_count: 12 + i },
})) };

function DemoDetail() {
  const { id } = useParams(); const item = catalog.styles.find(style => String(style.style_id) === id);
  const [reading, setReading] = useState(false);
  if (!item) return <p>未找到示例商品。</p>;
  return <CatalogStyleView onRefresh={() => { setReading(true); window.setTimeout(() => setReading(false), 400); }} reading={reading}
    value={{ catalog_version_id: catalog.catalog_version_id, catalog_publication_revision: catalog.catalog_publication_revision, permissions: { can_edit: false, can_manage_categories: false }, style: item, skus: Array.from({ length: item.variant_count }, (_, i) => ({ sku_id: item.style_id * 10 + i, style_id: item.style_id, internal_display_sku: `${item.style_code}-${i + 1}`, standard_color: i % 2 ? "浅蓝" : "暖灰", standard_size: i % 2 ? "M" : "S", status: "enabled", revision: 1, seller_sku_count: 1, source_summary: item.source_summary })) }}
    readers={{ aliases: skuId => Promise.resolve({ page: 1, page_size: 50, total_items: 1, items: [{ mapping_id: skuId, mapping_status: "mapped", seller_account: "虚构账号", marketplace: "amazon_us", seller_sku: { source_ref_id: `demo:${skuId}`, preview: `DEMO-${skuId}`, digest: `sha256:${"a".repeat(64)}`, is_truncated: false, is_unsafe: false }, source_summary: item.source_summary }] }), evidence: () => Promise.resolve({ page: 1, page_size: 50, total_items: 0, items: [] }) }} />;
}

function DemoDestination({ title }: { title: string }) {
  return <section><h2>{title}</h2><p>仅演示导航与路由位置；业务数据和维护操作请在实际应用中查看。</p><Link to="/catalog">返回商品主档</Link></section>;
}

function ReferencePage({ scenario = "reference" }: { scenario?: Scenario }) {
  const [list, setList] = useState<CatalogListState>({ query: scenario === "no-results" ? "不存在的示例款式" : "", status: "all", sort: "code", page: 1, view: scenario === "table" ? "table" : "cards" });
  const [loading, setLoading] = useState(scenario === "loading" || scenario === "refreshing");
  const [ready, setReady] = useState(scenario !== "loading" && scenario !== "failure");
  const reads = useRef(0);
  const loadStyle = useCallback<CatalogStyleLoader>(async id => {
    const first = reads.current++ === 0;
    if (scenario === "quick-view-loading") return new Promise(() => undefined);
    await new Promise(resolve => window.setTimeout(resolve, 350));
    if (scenario === "quick-view-failure" && first) throw new Error("Synthetic read failure");
    const style = catalog.styles.find(item => item.style_id === id)!;
    return { catalog_version_id: catalog.catalog_version_id, catalog_publication_revision: catalog.catalog_publication_revision, permissions: { can_edit: false, can_manage_categories: false }, style, skus: Array.from({ length: style.variant_count }, (_, i) => ({ sku_id: id * 10 + i, style_id: id, internal_display_sku: `${style.style_code}-${i + 1}`, revision: 1, standard_color: i % 2 ? "浅蓝" : "暖灰", standard_size: i % 2 ? "M" : "S", status: "enabled", seller_sku_count: 1, source_summary: style.source_summary })) };
  }, [scenario]);
  const [failed, setFailed] = useState(scenario === "failure" || scenario === "refresh-failure");
  const canManage = scenario !== "readonly";
  const value = scenario === "uninitialized" ? null : scenario === "empty" ? { ...catalog, styles: [] } : catalog;
  const reload = () => { setLoading(true); setFailed(false); window.setTimeout(() => { setReady(true); setLoading(false); }, 450); };
  return <MemoryRouter initialEntries={["/catalog"]}><CatalogLayout canManage={canManage}><Routes><Route path="/catalog" element={<CatalogProductList catalog={ready ? value : undefined} refreshing={ready && loading} loadStyle={loadStyle} failure={failed ? { message: "示例：连接暂时不可用。筛选设置已保留，请重新读取。", retry: true, setup: false } : undefined} canManage={canManage} list={list} onListChange={setList} onReload={reload} onOpenStyle={() => undefined} />} /><Route path="/catalog/styles/:id" element={<DemoDetail />} />{canManage && <><Route path="/catalog/unmatched" element={<DemoDestination title="待处理" />} /><Route path="/catalog/versions" element={<DemoDestination title="目录版本" />} /><Route path="/catalog/maintenance" element={<DemoDestination title="批量维护" />} /></>}</Routes><p>演示账号与商品均为虚构数据，不发送实际 API 请求。</p></CatalogLayout></MemoryRouter>;
}

const meta = { title: "Pages/Catalog Product List", component: ReferencePage, parameters: { layout: "fullscreen" } } satisfies Meta<typeof ReferencePage>;
export default meta;
type Story = StoryObj<typeof meta>;
export const Reference: Story = { args: { scenario: "reference" } };
export const BatchTable: Story = { args: { scenario: "table" } };
export const Loading: Story = { args: { scenario: "loading" } };
export const Empty: Story = { args: { scenario: "empty" } };
export const Uninitialized: Story = { args: { scenario: "uninitialized" } };
export const NoResults: Story = { args: { scenario: "no-results" } };
export const ReadFailure: Story = { args: { scenario: "failure" } };
export const ReadOnly: Story = { args: { scenario: "readonly" } };

export const QuickView: Story = { args: { scenario: "quick-view" } };
export const QuickViewLoading: Story = { args: { scenario: "quick-view-loading" } };
export const QuickViewFailure: Story = { args: { scenario: "quick-view-failure" } };
export const Refreshing: Story = { args: { scenario: "refreshing" } };
export const RefreshFailure: Story = { args: { scenario: "refresh-failure" } };
