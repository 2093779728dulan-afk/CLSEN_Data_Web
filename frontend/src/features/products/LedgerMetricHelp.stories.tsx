import type { Meta, StoryObj } from "@storybook/react-vite";
import { LedgerMetricHelp, type LedgerHelpKey } from "./LedgerMetricHelp";

// Synthetic context only; no report files, API calls, or business fixtures.
const meta = {
  title: "Patterns/Product Ledger Metric Help",
  component: LedgerMetricHelp,
  parameters: { layout: "padded" },
  args: { metric: "sales", from: "2026-01-01", to: "2026-01-31", returnBasis: "event_date", factBasis: "current", catalogVersion: 3 },
  argTypes: {
    metric: { control: "select", options: ["identity", "variants", "units", "sales", "returns", "sessions", "conversion", "average"] },
    returnBasis: { control: "select", options: ["event_date", "report_date"] },
    factBasis: { control: "select", options: ["current", "catalog_snapshot"] },
  },
} satisfies Meta<typeof LedgerMetricHelp>;
export default meta;
type Story = StoryObj<typeof meta>;

export const Sales: Story = { name: "销售额与占比" };
export const Returns: Story = { name: "退货事件日期", args: { metric: "returns" } };
export const ReportDate: Story = { name: "退货报表日期与目录快照", args: { metric: "returns", returnBasis: "report_date", factBasis: "catalog_snapshot" } };
export const NarrowScreen: Story = { name: "窄屏（调整预览宽度后点击）", globals: { viewport: { value: "mobile1", isRotated: false } } };

const labels: Array<[LedgerHelpKey, string]> = [["identity", "款式"], ["variants", "实际变体"], ["units", "销量"], ["sales", "销售额与占比"], ["returns", "本期退货量与同期退销比"], ["sessions", "会话"], ["conversion", "转化率"], ["average", "平均单价"]];
export const AllMetrics: Story = {
  name: "全部八项指标",
  render: (args) => <div style={{ maxWidth: 600, fontFamily: "var(--font-body)" }}>
    <h2>产品总表 · 指标说明</h2>
    <p>点击说明按钮。支持 Esc 关闭、焦点返回及减少动态效果设置。</p>
    {labels.map(([metric, label]) => <div key={metric} style={{ display: "flex", alignItems: "center", justifyContent: "space-between", padding: "12px 0", borderBottom: "1px solid var(--color-border-subtle)" }}><span>{label}</span><LedgerMetricHelp {...args} metric={metric} /></div>)}
  </div>,
};
