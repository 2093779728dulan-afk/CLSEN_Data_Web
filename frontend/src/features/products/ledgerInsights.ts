import type { MetricValue } from "./productAnalyticsTypes";
import { decimalStringToScaledBigInt } from "./metricFormatting";

function usable(metric: MetricValue): boolean {
  return metric.value !== null && (metric.value_state === "observed" || metric.value_state === "zero");
}

function divided(numerator: bigint, denominator: bigint, percent = false): string {
  if (denominator <= 0n || numerator < 0n) return "—";
  const rounded = (numerator * (percent ? 10000n : 1n) + denominator / 2n) / denominator;
  return `${(rounded / 100n).toLocaleString("en-US")}.${String(rounded % 100n).padStart(2, "0")}${percent ? "%" : ""}`;
}

export function salesShare(sales: MetricValue, total: string | null | undefined): string {
  if (!usable(sales) || total == null) return "—";
  return divided(decimalStringToScaledBigInt(String(sales.value), 2), decimalStringToScaledBigInt(total, 2), true);
}

export function averagePrice(sales: MetricValue, units: MetricValue): string {
  if (!usable(sales) || !usable(units)) return "—";
  return divided(decimalStringToScaledBigInt(String(sales.value), 2), BigInt(units.value!));
}

export function returnSalesRatio(returns: MetricValue, units: MetricValue): string {
  if (!usable(returns) || !usable(units)) return "—";
  return divided(BigInt(returns.value!), BigInt(units.value!), true);
}

export function conversionPercent(value: string): string {
  return divided(decimalStringToScaledBigInt(value, 6), 1000000n, true);
}
