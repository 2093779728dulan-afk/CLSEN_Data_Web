import { conversionPercent } from "./ledgerInsights";
import css from "./ProductAnalytics.module.css";
import type { MetricValue } from "./productAnalyticsTypes";
import { formatMoney, formatSixPlaceDecimal } from "./metricFormatting";

export type MetricKind = "units" | "sales" | "returns" | "sessions" | "conversion";

function observedValue(metric: MetricValue, kind: MetricKind): string {
  if (metric.value === null) return "—";
  if (kind === "sales") return formatMoney(String(metric.value));
  if (kind === "conversion") return formatSixPlaceDecimal(String(metric.value));
  return typeof metric.value === "number" ? metric.value.toLocaleString("zh-CN") : String(metric.value);
}

export function MetricValueView({ metric, kind, compact = false, percentage = false }: {
  compact?: boolean;
  percentage?: boolean;
  kind: MetricKind;
  metric: MetricValue;
}) {
  let value = observedValue(metric, kind);
  let detail: string | undefined;
  if (metric.value_state === "missing_report" || metric.null_reason === "no_observed_reports") {
    value = "无报表";
    detail = `已发布 ${metric.observed_days}/${metric.expected_days} 天`;
  } else if (metric.value_state === "undefined_denominator" || metric.null_reason === "undefined_denominator") {
    value = "分母为 0";
    detail = "转化率未定义";
  } else if (metric.value_state === "zero") {
    value = kind === "sales" ? "0.00" : kind === "conversion" ? "0.000000" : "0";
    detail = "已观测为零";
  }
  if (percentage && kind === "conversion" && (metric.value_state === "observed" || metric.value_state === "zero") && metric.value !== null) value = conversionPercent(String(metric.value));
  return <span className={css["metric-value"] + " " + (css[`metric-value--${metric.value_state}`] ?? "")}>
    <span className={css["metric-value__number"]}>{value}</span>
    {!compact && detail && <small>{detail}</small>}
    {metric.is_partial && <small className={css["metric-value__partial"]}>部分数据</small>}
  </span>;
}
