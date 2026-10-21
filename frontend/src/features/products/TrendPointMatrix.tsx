import css from "./ProductAnalytics.module.css";
import type { components } from "../../api/generated";
import type { MetricKind } from "./MetricValueView";
import { formatMoney, formatSixPlaceDecimal, trendMetricLabels } from "./metricFormatting";

type TrendSeries = components["schemas"]["TrendSeries"];
function valueText(value: number | string | null, state: string, metric: MetricKind) { if (state === "missing_report") return "无报表"; if (state === "undefined_denominator") return "分母为 0"; if (value === null) return "不可计算"; if (metric === "sales") return formatMoney(String(value)); if (metric === "conversion") return formatSixPlaceDecimal(String(value)); return String(value); }
export function TrendPointMatrix({ series, labels, metric }: { series: readonly TrendSeries[]; labels: ReadonlyMap<string,string>; metric: MetricKind }) {
  const dates = [...new Set(series.flatMap((item) => item.points.map((point) => point.date)))].sort();
  const maps = new Map(series.map((item) => [item.key, new Map(item.points.map((point) => [point.date, point]))]));
  return <div className={css["analytics-table-scroll"]} role="region" aria-label="趋势每日点矩阵" tabIndex={0}><table className={css["analytics-table"] + " " + css["trend-matrix"]}><caption className={css["trend-matrix__caption"]}>{trendMetricLabels[metric]} · 每日明细</caption><thead><tr><th>日期</th>{series.map((item) => <th key={item.key}>{labels.get(item.key) ?? item.key}</th>)}</tr></thead><tbody>{dates.map((date) => <tr key={date}><th scope="row"><time dateTime={date}>{date}</time></th>{series.map((item) => { const point=maps.get(item.key)?.get(date); return <td key={item.key}>{point ? valueText(point.value,point.value_state,metric) : "无报表"}</td>; })}</tr>)}</tbody></table></div>;
}
