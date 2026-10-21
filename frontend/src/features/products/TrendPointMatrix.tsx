import { useId } from "react";
import { EmptyState, StatusBadge } from "../../design-system";
import css from "./TrendPointMatrix.module.css";
import type { components } from "../../api/generated";
import type { MetricKind } from "./MetricValueView";
import { formatMoney, formatSixPlaceDecimal, trendMetricLabels } from "./metricFormatting";

type TrendSeries = components["schemas"]["TrendSeries"];
function valueText(value: number | string | null, state: string, metric: MetricKind) { if (state === "missing_report") return "无报表"; if (state === "undefined_denominator") return "分母为 0"; if (value === null) return "不可计算"; if (metric === "sales") return formatMoney(String(value)); if (metric === "conversion") return formatSixPlaceDecimal(String(value)); return String(value); }
export function TrendPointMatrix({ series, labels, metric }: { series: readonly TrendSeries[]; labels: ReadonlyMap<string,string>; metric: MetricKind }) {
  const hintId = useId();
  const dates = [...new Set(series.flatMap((item) => item.points.map((point) => point.date)))].sort();
  const maps = new Map(series.map((item) => [item.key, new Map(item.points.map((point) => [point.date, point]))]));
  return <section className={css.frame}>
    <header className={css.heading}><h3>{trendMetricLabels[metric]} · 每日明细</h3><span>{dates.length} 天 · {series.length} 个系列</span></header>
    {dates.length === 0 ? <EmptyState title="暂无每日明细" description="当前响应没有日期读数；不会补齐日期或用零替代缺失。" /> : <>
      <p className={css.hint} id={hintId}>日期与表头固定，横向滚动可核对更多系列；聚焦表格区域后可用方向键滚动。缺失读数保留原状态。</p>
      <div className={css.scroller} role="region" aria-label="趋势每日点矩阵" aria-describedby={hintId} tabIndex={0}>
        <table className={css.table}><caption className={css.caption}>{trendMetricLabels[metric]} · 每日明细</caption>
          <thead><tr><th scope="col">日期</th>{series.map((item) => <th scope="col" key={item.key}><span className={css.label}>{labels.get(item.key) ?? item.key}</span></th>)}</tr></thead>
          <tbody>{dates.map((date) => <tr key={date}><th scope="row"><time dateTime={date}>{date}</time></th>{series.map((item) => {
            const point = maps.get(item.key)?.get(date);
            const text = point ? valueText(point.value, point.value_state, metric) : "无报表";
            const numeric = point && point.value !== null && (point.value_state === "observed" || point.value_state === "zero");
            return <td key={item.key}>{numeric ? <span className={css.number}>{text}</span> : <StatusBadge tone="quiet" label={text} />}
              {point?.source_completeness === "partial" && <span className={css.quality}><StatusBadge tone="warn" label="部分数据" /></span>}
              {point?.source_completeness === "indeterminate" && <span className={css.quality}><StatusBadge tone="quiet" label="完整性未定" /></span>}
            </td>;
          })}</tr>)}</tbody>
        </table>
      </div>
    </>}
  </section>;
}
