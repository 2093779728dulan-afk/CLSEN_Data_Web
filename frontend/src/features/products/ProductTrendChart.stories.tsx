import { useState } from "react";
import type { Meta, StoryObj } from "@storybook/react-vite";
import type { AvailableSeries, TrendPoint, TrendSeries } from "../../api/generated";
import type { MetricKind } from "./MetricValueView";
import { ProductTrendChart } from "./ProductTrendChart";
import { SeriesSelector } from "./SeriesSelector";
import { TrendPointMatrix } from "./TrendPointMatrix";
import css from "./ProductAnalytics.module.css";

type Scenario = "reference" | "single" | "overlap" | "missing" | "limit" | "empty" | "singleDay";
type GalleryProps = { metric: MetricKind; scenario: Scenario; width: number };
const names = ["海蓝", "墨黑", "玫红", "米白", "松绿", "琥珀", "烟紫", "石灰", "珊瑚"];

// Synthetic fixtures only. Keep the production decimal-string contract intact.
function fixture(metric: MetricKind, scenario: Scenario): TrendSeries[] {
  const count = scenario === "single" || scenario === "singleDay" ? 1 : scenario === "limit" ? 9 : 4;
  return Array.from({ length: count }, (_, seriesIndex) => ({
    key: `demo-${seriesIndex}`,
    points: Array.from({ length: scenario === "singleDay" ? 1 : 7 }, (_, day): TrendPoint => {
      const amount = 10 + seriesIndex * 7 + [4, 12, 2, 17, 9, 20, 14][day]!;
      const absent = scenario === "empty" || (scenario === "missing" && day === 2);
      const undefinedRatio = metric === "conversion" && day === 4 && seriesIndex === 0;
      const zero = day === 0 && seriesIndex === 0;
      const value = scenario === "overlap" && day === 3 ? 30 : zero ? 0 : amount;
      return {
        date: `2026-01-${String(day + 1).padStart(2, "0")}`,
        value: absent || undefinedRatio ? null : metric === "sales" ? `${value}.00`
          : metric === "conversion" ? `0.${String(value * 1000).padStart(6, "0")}` : value,
        value_state: absent ? "missing_report" : undefinedRatio ? "undefined_denominator" : zero ? "zero" : "observed",
        null_reason: absent ? "missing_report" : undefinedRatio ? "undefined_denominator" : null,
        source_completeness: absent || (scenario === "missing" && day === 4) ? "partial" : "complete",
        numerator: metric === "conversion" && !absent ? value : null,
        denominator: metric === "conversion" && !absent ? undefinedRatio ? 0 : 1000 : null,
      };
    }),
  }));
}

function ChartExample({ metric, scenario, width }: GalleryProps) {
  const allSeries = fixture(metric, scenario);
  const [selected, setSelected] = useState<readonly string[]>(allSeries.slice(0, 8).map(item => item.key));
  const labels = new Map(allSeries.map((item, index) => [item.key, allSeries.length === 1 ? "款式合计" : names[index]!]));
  const available: AvailableSeries[] = allSeries.map((item, index) => ({
    key: item.key, label: labels.get(item.key)!, active: true, dimension: allSeries.length === 1 ? "total" : "color", sort_order: index,
    total: { value: null, value_state: "missing_report", null_reason: "missing_report", numerator: null, denominator: null,
      expected_days: item.points.length, observed_days: 0, source_completeness: "partial", is_partial: true },
  }));
  const series = allSeries.filter(item => selected.includes(item.key));
  return <section className={css["product-analytics"]} style={{ maxWidth: width, marginInline: "auto" }} aria-label="款式详情折线图参考">
    <h1>款式详情 · 折线图参考</h1>
    <p>虚构示例数据。悬停数据点查看读数，点击图例聚焦，拖动日期逐日核对。{scenario === "overlap" && " 1 月 4 日四条曲线同值，可查看重合组。"}</p>
    <SeriesSelector available={available} selected={selected} onChange={setSelected} />
    <ProductTrendChart series={series} labels={labels} metric={metric} />
    <TrendPointMatrix series={series} labels={labels} metric={metric} />
  </section>;
}

const meta = {
  title: "Patterns/Product Trend Chart",
  component: ChartExample,
  parameters: { layout: "fullscreen" },
  args: { metric: "sales", scenario: "reference", width: 1100 },
  argTypes: {
    metric: { control: "select", options: ["sales", "units", "returns", "sessions", "conversion"] },
    scenario: { control: false },
    width: { control: { type: "range", min: 320, max: 1440, step: 10 } },
  },
  render: args => <ChartExample key={args.scenario} {...args} />,
} satisfies Meta<typeof ChartExample>;
export default meta;
type Story = StoryObj<typeof meta>;

export const Reference: Story = { name: "参考款式 · 多系列与交互" };
export const SingleSeries: Story = { name: "款式合计 · 单条曲线", args: { scenario: "single" } };
export const CoincidentPoints: Story = { name: "重合点 · 同值分组提示", args: { scenario: "overlap" } };
export const MissingAndPartial: Story = { name: "缺失、零值与部分数据", args: { scenario: "missing", metric: "units" } };
export const ConversionRatio: Story = { name: "转化率 · 比率与分母为零", args: { metric: "conversion" } };
export const SelectionLimit: Story = { name: "九个候选 · 同时最多八项", args: { scenario: "limit" } };
export const Narrow: Story = { name: "窄屏 · 390 像素", args: { width: 390 } };
export const Empty: Story = { name: "无可绘制数据", args: { scenario: "empty" } };
export const SingleDay: Story = { name: "单日 · 孤立数据点", args: { scenario: "singleDay" } };
