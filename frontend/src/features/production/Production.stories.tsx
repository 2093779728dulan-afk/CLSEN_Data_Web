import type { Meta, StoryObj } from "@storybook/react-vite";
import { MemoryRouter } from "react-router-dom";
import { PageHeader, StatusMessage } from "../../design-system";
import { DocumentContent, DocumentTable, SummaryContent } from "./ProductionViews";
import type { Document, Summary as ProductionSummary } from "./types";
import styles from "./Production.module.css";

const order: Document = {
  id: "101", system_number: "PO-DEMO-001", business_number: "虚构订单 · 蓝色基础款", business_date: "2026-10-12", notes: "仅虚构演练", status: "CONFIRMED", revision: "1",
  tracking_state: "OPEN", pending_units: "30", closed_units: "0", overage_units: "0", expected_units: "100", actual_units: "70", difference_units: "30",
  lines: [{ id: "501", sku_id: "1001", sku_label: "DEMO-SKU-BLUE-M · 蓝色 / M", tracking_state: "OPEN", pending_units: "30", closed_units: "0", overage_units: "0", expected_units: "100", actual_units: "70", difference_units: "30" }],
  shipments: [{ id: "201", system_number: "SH-DEMO-001", status: "CONFIRMED", business_date: "2026-10-12" }, { id: "202", system_number: "SH-DEMO-002", status: "CONFIRMED", business_date: "2026-10-13" }],
};
const summary: ProductionSummary = { expected_units: "100", actual_units: "70", difference_units: "30", shipment_period_filtered: false,
  items: [{ ...order.lines![0]!, order_id: "101", order_number: "PO-DEMO-001" }], skus: [{ sku_id: "1001", sku_label: "DEMO-SKU-BLUE-M · 蓝色 / M", expected_units: "100", actual_units: "70", difference_units: "30" }] };
function ProductionStory({ scenario }: { scenario: "order-list" | "order-detail" | "shipment-detail" | "summary" | "period-summary" | "filtered-empty" | "long-values" | "empty" | "result-unknown" | "closed-tracking" | "demand-history" | "allocation-history" }) {
  return <main className={styles.workspace}><PageHeader eyebrow="PRODUCTION · DEMO" title="预计订单与实际出货" description="预计与实际分别保存，草稿不计入有效汇总。" />
    {scenario === "order-list" && <DocumentTable kind="orders" items={[order, { ...order, id: "102", status: "DRAFT", actual_units: "0", difference_units: "100" }]} />}
    {scenario === "order-detail" && <DocumentContent kind="orders" document={order} />}
    {scenario === "shipment-detail" && <DocumentContent kind="shipments" document={{ ...order, expected_units: undefined, difference_units: undefined, shipments: undefined, sources: [{ id: "601", sku_id: "1001", sku_label: "DEMO-SKU-BLUE-M · 蓝色 / M", actual_units: "70", allocations: [{ order_line_id: "501", order_id: "101", order_number: "PO-DEMO-001", units: "40" }, { order_line_id: "502", order_id: "102", order_number: "PO-DEMO-002", units: "30" }] }] }} />}
    {scenario === "closed-tracking" && <DocumentContent kind="orders" document={{ ...order, revision: "4", tracking_state: "CLOSED", closed_units: "30", pending_units: "0", lines: order.lines?.map(l => ({ ...l, tracking_state: "CLOSED", closed_units: "30", pending_units: "0" })), history: [{ revision: "4", actor_id: "1", created_at: "2026-10-12T03:00:00Z", reason: "剩余30不再跟进（虚构）", operation_kind: "CLOSE_TRACKING", before_value: order, after_value: { ...order, closed_units: "30", pending_units: "0" } }] }} />}
    {scenario === "demand-history" && <DocumentContent kind="orders" document={{ ...order, expected_units: "150", difference_units: "80", pending_units: "80", history: [{ revision: "5", actor_id: "2", created_at: "2026-10-12T03:00:00Z", effective_date: "2026-10-14", reason: "正式追加50（虚构）", operation_kind: "DEMAND_CHANGE", before_value: order, after_value: { ...order, expected_units: "150", difference_units: "80", pending_units: "80" } }], lines: order.lines?.map(l => ({ ...l, expected_units: "150", difference_units: "80", pending_units: "80" })) }} />}
    {scenario === "allocation-history" && <DocumentContent kind="shipments" document={{ ...order, expected_units: undefined, difference_units: undefined, shipments: undefined, actual_units: "40", dispatch_purpose: "OUTWARD_ORDER", source_system: "FICTIONAL-FACTORY", source_event_kind: "OUTWARD_DISPATCH", external_event_id: "DEMO-HANDOVER-001", sources: [{ id: "601", sku_id: "1001", sku_label: "虚构蓝色M", actual_units: "40", allocations: [{ order_line_id: "501", order_id: "101", order_number: "PO-DEMO-001", units: "25" }, { order_line_id: "502", order_id: "102", order_number: "PO-DEMO-002", units: "15" }] }], history: [{ revision: "2", actor_id: "1", created_at: "2026-10-12T03:00:00Z", reason: "原40件属于A25+B15（虚构）", operation_kind: "ALLOCATION_CORRECTION", before_value: { sources: [{ id: "601", sku_label: "虚构蓝色M", actual_units: "40", allocations: [{ order_number: "PO-DEMO-001", units: "40" }] }] }, after_value: { sources: [{ id: "601", sku_label: "虚构蓝色M", actual_units: "40", allocations: [{ order_number: "PO-DEMO-001", units: "25" }, { order_number: "PO-DEMO-002", units: "15" }] }] } }] }} />}
    {scenario === "summary" && <SummaryContent summary={summary} />}
    {scenario === "period-summary" && <SummaryContent summary={{ ...summary, shipment_period_filtered: true, actual_units: "30", difference_units: "70", cumulative_actual_units: "70", cumulative_difference_units: "30", pending_units: "30", closed_units: "0", overage_units: "0", items: summary.items.map(l => ({ ...l, actual_units: "30", difference_units: "70" })), skus: summary.skus.map(s => ({ ...s, actual_units: "30", difference_units: "70" })) }} />}
    {scenario === "long-values" && <DocumentTable kind="orders" items={[{ ...order, business_number: "虚构超长业务说明用于确认窄屏和完整身份文字不会被固定表格宽度裁切".repeat(3), expected_units: "9007199254740993", actual_units: "9007199254741003", difference_units: "-10" }]} />}
    {scenario === "empty" && <DocumentTable kind="orders" items={[]} />}
    {scenario === "filtered-empty" && <DocumentTable kind="orders" items={[]} filtered />}
    {scenario === "result-unknown" && <StatusMessage kind="warning" title="保存结果待核实，已锁定当前输入">保留原操作ID，查询结果或重发原操作。不能再次创建一笔出货。</StatusMessage>}
  </main>;
}
const meta = { title: "Pages/Production", component: ProductionStory, parameters: { layout: "fullscreen" }, args: { scenario: "order-list" }, decorators: [(Story) => <MemoryRouter><Story /></MemoryRouter>] } satisfies Meta<typeof ProductionStory>;
export default meta;
type Story = StoryObj<typeof meta>;
export const OrderList: Story = {};
export const OrderDetail: Story = { args: { scenario: "order-detail" } };
export const ShipmentDetail: Story = { args: { scenario: "shipment-detail" } };
export const Summary: Story = { args: { scenario: "summary" } };
export const LongValues: Story = { args: { scenario: "long-values" } };
export const Empty: Story = { args: { scenario: "empty" } };
export const ResultUnknown: Story = { args: { scenario: "result-unknown" } };

export const ClosedTracking: Story = { args: { scenario: "closed-tracking" } };
export const DemandHistory: Story = { args: { scenario: "demand-history" } };
export const AllocationHistory: Story = { args: { scenario: "allocation-history" } };
export const PeriodSummary: Story = { args: { scenario: "period-summary" } };
export const FilteredEmpty: Story = { args: { scenario: "filtered-empty" } };
