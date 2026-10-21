import type { Meta, StoryObj } from "@storybook/react-vite";
import { MetricValueView, type MetricKind } from "./MetricValueView";
import type { MetricValue } from "./productAnalyticsTypes";
import styles from "./MetricValueView.module.css";

type Scenario = "reference" | "zero-values" | "missing-report" | "undefined-denominator" | "partial" | "compact" | "percentage" | "long-values";
const base: MetricValue = { denominator: null, expected_days: 31, is_partial: false, null_reason: null, numerator: null, observed_days: 31, source_completeness: "complete", value: 12, value_state: "observed" };
type Sample = { label: string; kind: MetricKind; metric: MetricValue; percentage?: boolean };
const reference: Sample[] = [
  { label: "销量（件）", kind: "units", metric: { ...base, value: 12345 } },
  { label: "销售额（原币）", kind: "sales", metric: { ...base, value: "1234.50" } },
  { label: "退货（件）", kind: "returns", metric: { ...base, value: 0, value_state: "zero" } },
  { label: "会话（次）", kind: "sessions", metric: { ...base, value: 123456 } },
  { label: "转化率（比率）", kind: "conversion", metric: { ...base, value: "0.200000", numerator: 2, denominator: 10 } },
];
function MetricReadoutStory({ scenario = "reference" }: { scenario?: Scenario }) {
  let samples = reference;
  if (scenario === "zero-values") samples = reference.map(item => ({ ...item, metric: { ...item.metric, value: item.kind === "sales" ? "0.00" : item.kind === "conversion" ? "0.000000" : 0, value_state: "zero" } }));
  if (scenario === "missing-report") samples = reference.map(item => ({ ...item, metric: { ...item.metric, value: null, value_state: "missing_report", null_reason: "no_observed_reports", observed_days: 0, source_completeness: "indeterminate", numerator: null, denominator: null } }));
  if (scenario === "undefined-denominator") samples = [{ ...reference[4]!, metric: { ...base, value: null, value_state: "undefined_denominator", null_reason: "undefined_denominator", denominator: 0, numerator: 0 } }];
  if (scenario === "partial" || scenario === "compact") samples = reference.map(item => ({ ...item, metric: { ...item.metric, is_partial: true, source_completeness: "partial", observed_days: 30 } }));
  if (scenario === "percentage") samples = [{ ...reference[4]!, label: "比率原值" }, { ...reference[4]!, label: "百分比展示", percentage: true }];
  if (scenario === "long-values") samples = [
    { label: "最长支持金额（虚构）", kind: "sales", metric: { ...base, value: "123456789012345678901234567890.12" } },
    { label: "负金额（虚构）", kind: "sales", metric: { ...base, value: "-1234.50" } },
  ];
  return <main className={styles.story}>
    <h1>经营指标读数</h1>
    <p>零值表示已观测为零；没有报表或分母为零时不显示伪造的数字。部分数据保留当前读数，并说明覆盖状态。</p>
    <ul className={styles.samples} aria-label="经营指标示例">{samples.map(item => <li className={styles.sample} key={item.label}><strong>{item.label}</strong><div className={scenario === "compact" ? undefined : styles.large}><MetricValueView metric={item.metric} kind={item.kind} compact={scenario === "compact"} percentage={item.percentage} /></div></li>)}</ul>
    <p>全部数值与覆盖天数均为虚构数据。金额沿用精确十进制字符串；比率和百分比沿用原计算方式。紧凑视图保留部分数据提示，详细读数补充已发布天数。</p>
  </main>;
}
const meta = { title: "Patterns/Metric Value", component: MetricReadoutStory, parameters: { layout: "fullscreen" } } satisfies Meta<typeof MetricReadoutStory>;
export default meta;
type Story = StoryObj<typeof meta>;
export const Reference: Story = { args: { scenario: "reference" } };
export const ZeroValues: Story = { args: { scenario: "zero-values" } };
export const MissingReport: Story = { args: { scenario: "missing-report" } };
export const UndefinedDenominator: Story = { args: { scenario: "undefined-denominator" } };
export const Partial: Story = { args: { scenario: "partial" } };
export const Compact: Story = { args: { scenario: "compact" } };
export const Percentage: Story = { args: { scenario: "percentage" } };
export const LongValues: Story = { args: { scenario: "long-values" } };
