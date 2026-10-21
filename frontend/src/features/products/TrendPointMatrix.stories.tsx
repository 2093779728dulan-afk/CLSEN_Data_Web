import type { Meta, StoryObj } from "@storybook/react-vite";
import { useState } from "react";
import type { TrendPoint, TrendSeries } from "../../api/generated";
import { Select } from "../../design-system";
import { SeriesSelector } from "./SeriesSelector";
import { TrendPointMatrix } from "./TrendPointMatrix";
import type { MetricKind } from "./MetricValueView";
import { trendMetricLabels } from "./metricFormatting";
import css from "./TrendPointMatrix.module.css";

type Scenario = "reference" | "missing-and-partial" | "conversion-ratio" | "wide" | "long-values" | "empty";
function fixtures(metric: MetricKind, scenario: Scenario): TrendSeries[] {
  if (scenario === "empty") return [];
  const count = scenario === "wide" ? 8 : scenario === "long-values" ? 1 : 3;
  const days = scenario === "wide" ? 31 : 3;
  return Array.from({ length: count }, (_, index) => ({ key: `fictional-${index}`, points: Array.from({ length: days }, (_, day): TrendPoint => {
    const zero = day === 0 && index === 0;
    const undefinedRatio = metric === "conversion" && day === 1 && index === 1;
    const missing = scenario === "missing-and-partial" && day === 1 && index === 0;
    return { date: `2026-08-${String(day + 1).padStart(2, "0")}`, value: missing || undefinedRatio ? null : metric === "sales" ? scenario === "long-values" ? day === 0 ? "123456789012345678901234567890.12" : "-1234.50" : zero ? "0.00" : "1234.50" : metric === "conversion" ? zero ? "0.000000" : "0.200000" : zero ? 0 : 1234,
      value_state: missing ? "missing_report" : undefinedRatio ? "undefined_denominator" : scenario !== "long-values" && zero ? "zero" : "observed", null_reason: missing ? "missing_report" : undefinedRatio ? "undefined_denominator" : null,
      source_completeness: missing ? "indeterminate" : scenario === "missing-and-partial" && day === 2 && index === 1 ? "partial" : "complete", numerator: metric === "conversion" && !missing ? zero || undefinedRatio ? 0 : 2 : null, denominator: metric === "conversion" && !missing ? undefinedRatio ? 0 : 10 : null };
  }).reverse().filter(point => !(scenario === "missing-and-partial" && index === 2 && point.date === "2026-08-02")) }));
}
function MatrixStory({ scenario = "reference" }: { scenario?: Scenario }) {
  const [metric, setMetric] = useState<MetricKind>(scenario === "conversion-ratio" ? "conversion" : "sales");
  const all = fixtures(metric, scenario);
  const [selected, setSelected] = useState<readonly string[]>(all.map(item => item.key));
  const labels = new Map(all.map((item, index) => [item.key, scenario === "wide" ? `示例系列 ${index + 1} · 较长的颜色与尺码名称用于核对表头换行` : ["海蓝 / M", "米白 / S", "墨黑 / L"][index]!]));
  const available = all.map((item, index) => ({ key: item.key, label: labels.get(item.key)!, active: true, dimension: "color" as const, sort_order: index, total: { value: null, value_state: "missing_report" as const, null_reason: "no_observed_reports" as const, source_completeness: "indeterminate" as const, denominator: null, numerator: null, expected_days: item.points.length, observed_days: 0, is_partial: false } }));
  return <main className={css.story}>
    <h1>趋势每日明细</h1><p>按响应中的日期和系列核对原始读数，不插值、不补零。全部数据均为虚构示例。</p>
    <div className={css.storyControls}><label>明细指标<Select value={metric} disabled={scenario === "long-values"} onChange={event => setMetric(event.target.value as MetricKind)}>{(Object.entries(trendMetricLabels) as [MetricKind, string][]).map(([key, label]) => <option key={key} value={key}>{label}</option>)}</Select></label></div>
    {available.length > 0 && <SeriesSelector available={available} selected={selected} onChange={setSelected} />}
    <TrendPointMatrix series={all.filter(item => selected.includes(item.key))} labels={labels} metric={metric} />
    <p>切换指标或系列仅改变这个样板；刷新恢复初始状态。不请求实际 API，也不代表真实经营数据。</p>
  </main>;
}
const meta = { title: "Patterns/Trend Point Matrix", component: MatrixStory, parameters: { layout: "fullscreen" } } satisfies Meta<typeof MatrixStory>;
export default meta;
type Story = StoryObj<typeof meta>;
export const Reference: Story = { args: { scenario: "reference" } };
export const MissingAndPartial: Story = { args: { scenario: "missing-and-partial" } };
export const ConversionRatio: Story = { args: { scenario: "conversion-ratio" } };
export const Wide: Story = { args: { scenario: "wide" } };
export const LongValues: Story = { args: { scenario: "long-values" } };
export const Empty: Story = { args: { scenario: "empty" } };
