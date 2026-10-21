import type { DailyLedgerRow } from "../../api/generated";

export const METRICS = [
  { key: "sales", label: "销售额" },
  { key: "units_ordered", label: "订购数" },
  { key: "sessions", label: "会话数" },
  { key: "conversion_rate", label: "转化率" },
  { key: "return_quantity", label: "退货数" },
] as const;
export type MonthlyMetric = typeof METRICS[number]["key"];
export type MonthlyPoint = { date: string; value: bigint | null };
const DECIMAL_PLACES = 30;
const SCALE = 10n ** BigInt(DECIMAL_PLACES);

// Preserve the API Decimal context (28 digits) before projecting to screen coordinates.
function decimal(value: string | number | null): bigint | null {
  if (value === null || (typeof value === "number" && !Number.isSafeInteger(value))) return null;
  const match = /^(-?)(\d+)(?:\.(\d+))?$/.exec(String(value));
  if (!match) return null;
  const fraction = match[3] ?? "";
  const scaledFraction = BigInt(fraction.padEnd(DECIMAL_PLACES, "0").slice(0, DECIMAL_PLACES));
  const rounding = Number(fraction[DECIMAL_PLACES] ?? "0") >= 5 ? 1n : 0n;
  return (match[1] ? -1n : 1n) * (BigInt(match[2]!) * SCALE + scaledFraction + rounding);
}

export function monthlyPoints(rows: readonly DailyLedgerRow[], reportDate: string, metric: MonthlyMetric): MonthlyPoint[] {
  const byDate = new Map(rows.map((row) => [row.report_date, row]));
  return Array.from({ length: Number(reportDate.slice(8, 10)) }, (_, index) => {
    const date = `${reportDate.slice(0, 8)}${String(index + 1).padStart(2, "0")}`;
    const row = byDate.get(date);
    const published = metric === "return_quantity" ? row?.return_status === "published" : row?.business_status === "published";
    return { date, value: row && published ? decimal(row[metric]) : null };
  });
}

export function total(points: readonly MonthlyPoint[]): bigint | null {
  const values = points.flatMap((point) => point.value === null ? [] : [point.value]);
  return values.length ? values.reduce((sum, value) => sum + value, 0n) : null;
}

function fixed(value: bigint, places: number): string {
  const divisor = 10n ** BigInt(DECIMAL_PLACES - places);
  const magnitude = value < 0n ? -value : value;
  const rounded = (magnitude + divisor / 2n) / divisor;
  const unit = 10n ** BigInt(places);
  const integer = new Intl.NumberFormat("zh-CN").format(rounded / unit);
  return `${value < 0n && rounded !== 0n ? "−" : ""}${integer}${places ? `.${String(rounded % unit).padStart(places, "0")}` : ""}`;
}

export function formatMetric(value: bigint | null, metric: MonthlyMetric, currencyCode: string): string {
  if (value === null) return "暂无可用数据";
  if (metric === "conversion_rate") return `${fixed(value * 100n, 2)}%`;
  if (metric === "sales") {
    const symbol = new Intl.NumberFormat("zh-CN", { style: "currency", currency: currencyCode }).formatToParts(0).find((part) => part.type === "currency")?.value ?? currencyCode;
    return `${symbol}${fixed(value, 2)}`;
  }
  return fixed(value, 0);
}

export function comparePrevious(points: readonly MonthlyPoint[], metric: MonthlyMetric, currencyCode: string): { direction: "up" | "down" | "flat" | "unavailable"; amount: string; detail: string } {
  const current = points.at(-1)?.value;
  const previous = points.at(-2)?.value;
  if (current == null) return { direction: "unavailable", amount: "当日暂无可比数据", detail: "报告未发布或指标暂无值，不能计算增减。" };
  if (previous == null) return { direction: "unavailable", amount: "前一日暂无可比数据", detail: points.length === 1 ? "本月首日，当前月内没有前一日。" : "前一日数据缺失，不跨过缺报日期比较。" };
  const difference = current - previous;
  const direction = difference > 0n ? "up" : difference < 0n ? "down" : "flat";
  const prefix = direction === "up" ? "增加 " : direction === "down" ? "减少 " : "持平 ";
  const magnitude = difference < 0n ? -difference : difference;
  const amount = metric === "conversion_rate" ? `${prefix}${fixed(magnitude * 100n, 2)} 个百分点` : `${prefix}${formatMetric(magnitude, metric, currencyCode)}`;
  const percent = previous === 0n ? (current === 0n ? "两日均为 0。" : "前一日为 0，无可比百分比基数。") : `变化幅度 ${difference > 0n ? "+" : ""}${fixed(difference * 100n * SCALE / (previous < 0n ? -previous : previous), 2)}%。`;
  return { direction, amount, detail: metric === "conversion_rate" ? "转化率按百分点比较。" : percent };
}
