import type { Meta, StoryObj } from "@storybook/react-vite";
import { Link, MemoryRouter, Route, Routes, useLocation } from "react-router-dom";
import { StatusMessage } from "../../design-system";
import { CatalogNavigationProvider, useCatalogNavigation } from "./CatalogNavigationContext";
import { CatalogPendingItems } from "./CatalogPendingItems";
import type { CatalogPendingItem } from "./catalogApi";
import "./CatalogWorkspace.css";

type Scenario = "reference" | "read-only" | "empty" | "no-previews" | "zero-counts" | "long-previews" | "many-batches";
const items: CatalogPendingItem[] = ["needs_attention", "validated", "ready_for_approval"].map((status, index) => ({ import_id: 42 + index, review_path: `/catalog/imports/${42 + index}`, seller_sku_count: index + 2, seller_sku_previews: [`DEMO-${index + 1}-NAVY-L`, `DEMO-${index + 1}-BLUE-M`], status: status as CatalogPendingItem["status"], updated_at: "2099-01-01", variant_count: index + 1, workflow_revision: 3 + index }));
function Destination() {
  const { reviewReturn } = useCatalogNavigation(); const location = useLocation();
  return <StatusMessage kind="info" title="虚构审核导航"><p>目标路径：{location.pathname}；返回路径：{reviewReturn}。不读取或批准真实批次。</p><Link to={reviewReturn}>返回商品详情</Link></StatusMessage>;
}
function Sample({ scenario = "reference" }: { scenario?: Scenario }) {
  const values = scenario === "empty" ? [] : scenario === "no-previews" ? [{ ...items[0]!, seller_sku_previews: [] }] : scenario === "zero-counts" ? [{ ...items[0]!, variant_count: 0, seller_sku_count: 0, seller_sku_previews: [] }] : scenario === "long-previews" ? [{ ...items[0]!, import_id: 9007199254740991, review_path: "/catalog/imports/9007199254740991", seller_sku_previews: ["DEMO-長编码-".repeat(24), "<fictional-preview-only>"], workflow_revision: 123456 }] : scenario === "many-batches" ? Array.from({ length: 6 }, (_, index) => ({ ...items[index % 3]!, import_id: 100 + index, review_path: `/catalog/imports/${100 + index}` })) : items;
  return <MemoryRouter initialEntries={["/catalog/styles/1001"]}><CatalogNavigationProvider><main className="catalog-workspace" id="main-content"><Routes><Route path="/catalog/styles/1001" element={<><CatalogPendingItems canReview={scenario !== "read-only"} items={values} />{values.length === 0 && <StatusMessage kind="info" title="当前商品没有候选批次">空数组保持实际组件不显示候选面板的行为。</StatusMessage>}</>} /><Route path="*" element={<Destination />} /></Routes><p>全部批次、预览、数量与修订均为虚构示例。样板不请求实际 API；刷新重置，不创建候选或执行批准。</p></main></CatalogNavigationProvider></MemoryRouter>;
}
const meta = { title: "Patterns/Catalog Pending Candidates", component: Sample, parameters: { layout: "fullscreen" } } satisfies Meta<typeof Sample>;
export default meta;
type Story = StoryObj<typeof meta>;
export const Reference: Story = { args: { scenario: "reference" } };
export const ReadOnly: Story = { args: { scenario: "read-only" } };
export const Empty: Story = { args: { scenario: "empty" } };
export const NoPreviews: Story = { args: { scenario: "no-previews" } };
export const ZeroCounts: Story = { args: { scenario: "zero-counts" } };
export const LongPreviews: Story = { args: { scenario: "long-previews" } };
export const ManyBatches: Story = { args: { scenario: "many-batches" } };
