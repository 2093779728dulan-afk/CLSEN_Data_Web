import type { MetricKind } from "./MetricValueView";
import type { ProductDetailView } from "./productDetailState";
import type { MetricValue, StyleCardResponse } from "./productAnalyticsTypes";
import { productLedgerFixture } from "./ProductLedgerView.fixtures";

const metric = (value: number | string | null): MetricValue => ({ value, value_state: value === 0 || value === "0.00" ? "zero" : "observed", null_reason: null, denominator: null, numerator: null, expected_days: 3, observed_days: 3, is_partial: false, source_completeness: "complete" });
export const detailColors = ["red-key", "blue-key"];
const allMetrics = { units: metric(18), sales: metric("360.00"), returns: metric(2), sessions: metric(90), conversion: { ...metric("0.200000"), numerator: 18, denominator: 90 } };
const totals = { units: 18, sales: "360.00", returns: 2, sessions: 90, conversion_numerator: 18, conversion_denominator: 90 };

// Entirely fictional; same typed response as actual /products/:style_id.
export function detailFixture(view: ProductDetailView, scenario = "reference"): StyleCardResponse {
  const names = view.dimension === "total" ? ["款式合计"] : view.dimension === "size" ? [view.color_key === "blue-key" ? "M" : "S"] : view.dimension === "sku" ? ["DEMO-RED-S", "DEMO-BLUE-M"] : ["红色", "蓝色"];
  const keys = view.dimension === "color" ? detailColors : names.map((_, i) => `${view.dimension}-${i}`);
  const missing = scenario === "no-reports" || scenario === "empty-variants";
  const amount = (kind: MetricKind, n: number, returned = 0) => kind === "sales" ? `${n * 20}.00` : kind === "conversion" ? "0.200000" : kind === "sessions" ? n * 5 : kind === "returns" ? returned : n;
  const available_series = keys.map((key, i) => ({ active: true, dimension: view.dimension, key, label: names[i]!, sort_order: i, total: metric(amount(view.metric, view.dimension === "total" ? scenario === "partial" ? 12 : 18 : scenario === "partial" ? 6 : 9, view.dimension === "total" ? 2 : 1)) }));
  const summary = structuredClone(allMetrics);
  if (missing) for (const value of Object.values(summary)) Object.assign(value, { value: null, value_state: "missing_report", null_reason: "no_observed_reports", observed_days: 0, source_completeness: "partial", is_partial: true, numerator: null, denominator: null });
  if (scenario === "partial") for (const value of Object.values(summary)) Object.assign(value, { observed_days: 2, source_completeness: "partial", is_partial: true });
  const metrics = () => ({ units: metric(scenario === "partial" ? 6 : 9), sales: metric(scenario === "partial" ? "120.00" : "180.00"), returns: metric(1), sessions: metric(scenario === "partial" ? 30 : 45), conversion: { ...metric("0.200000"), numerator: scenario === "partial" ? 6 : 9, denominator: scenario === "partial" ? 30 : 45 } });
  if (scenario === "partial") { summary.units.value = 12; summary.sales.value = "240.00"; summary.sessions.value = 60; summary.conversion.numerator = 12; summary.conversion.denominator = 60; }
  if (missing) for (const value of available_series) value.total = { ...summary[view.metric] };
  if (scenario === "partial") for (const value of available_series) Object.assign(value.total, { observed_days: 2, is_partial: true, source_completeness: "partial" });
  const observedTotals = missing ? { units: null, sales: null, returns: null, sessions: null, conversion_numerator: null, conversion_denominator: null } : scenario === "partial" ? { ...totals, units: 12, sales: "240.00", sessions: 60, conversion_numerator: 12, conversion_denominator: 60 } : { ...totals };
  const colorTotals = missing ? { ...observedTotals } : { units: Number(observedTotals.units) / 2, sales: scenario === "partial" ? "120.00" : "180.00", returns: 1, sessions: Number(observedTotals.sessions) / 2, conversion_numerator: Number(observedTotals.conversion_numerator) / 2, conversion_denominator: Number(observedTotals.conversion_denominator) / 2 };
  const unitsAt = (key: string, d: number) => view.dimension === "total" ? 6 : key === "blue-key" || key === "sku-1" || view.dimension === "size" && view.color_key === "blue-key" ? 4 - d : 2 + d;
  const data: StyleCardResponse = {
    style: { style_id: "501", style_code: "10001", standard_name: "标准轻量夹克", status: "enabled", color_count: scenario === "empty-variants" ? 0 : 2, size_count: scenario === "empty-variants" ? 0 : 2, sku_count: scenario === "empty-variants" ? 0 : 2 },
    provenance: { ...structuredClone(productLedgerFixture.provenance), from: view.from, to: view.to, fact_basis: view.fact_basis, return_basis: view.return_basis, effective_return_basis: view.return_basis },
    permissions: { ...productLedgerFixture.permissions, can_manage_catalog: scenario !== "read-only" },
    effective_return_basis: view.return_basis, trend_effective_return_basis: view.return_basis,
    summary: { metrics: summary }, available_series,
    series: scenario === "empty-variants" ? [] : available_series.filter(item => !view.series.length || view.series.includes(item.key)).map(item => ({ key: item.key, points: Array.from({ length: 3 }, (_, d) => ({ date: `2026-08-${22 + d}`, value: missing || scenario === "partial" && d === 1 ? null : amount(view.metric, unitsAt(item.key, d), d === 2 ? view.dimension === "total" ? 2 : 1 : 0), value_state: missing || scenario === "partial" && d === 1 ? "missing_report" as const : view.metric === "returns" && d !== 2 ? "zero" as const : "observed" as const, null_reason: missing ? "no_observed_reports" : scenario === "partial" && d === 1 ? "missing_report" : null, source_completeness: missing || scenario === "partial" ? "partial" as const : "complete" as const, numerator: view.metric === "conversion" && !missing && !(scenario === "partial" && d === 1) ? unitsAt(item.key, d) : null, denominator: view.metric === "conversion" && !missing && !(scenario === "partial" && d === 1) ? unitsAt(item.key, d) * 5 : null })) })),
    variants: scenario === "empty-variants" ? [] : ["红色", "蓝色"].map((color, i) => ({ sku_id: `demo-sku-${i}`, internal_display_sku: i ? "DEMO-BLUE-M" : "DEMO-RED-S", standard_color: color, standard_size: i ? "M" : "S", status: "enabled", metrics: missing ? structuredClone(summary) : metrics(), seller_sku_aliases: [{ is_truncated: false, is_unsafe: false, preview: i ? "DEMO-SOURCE-BLUE-M" : "DEMO-SOURCE-RED-S", sha256: "sha256:" + "a".repeat(64), source_ref_id: `demo-ref-${i}` }] })),
    source_report_coverage: { contributing_report_date_from: missing ? null : "2026-08-22", contributing_report_date_to: missing ? null : "2026-08-24", coverage_from: view.from, coverage_to: view.to, days: [] },
    style_reconciliation: { scope: "style", series_scope: view.dimension === "size" ? "selected_color" : "style", selected_color_totals: view.dimension === "size" ? { ...colorTotals } : null, metric_status: { units: missing ? "not_evaluable" : "evaluable", sales: missing ? "not_evaluable" : "evaluable", sessions: missing ? "not_evaluable" : "evaluable", returns: missing ? "not_evaluable" : "evaluable", conversion: missing ? "not_evaluable" : "evaluable" }, series_scope_totals: { ...(view.dimension === "size" ? colorTotals : observedTotals) }, summary_totals: { ...observedTotals }, variant_totals: { ...observedTotals } },
  };
  if (scenario === "empty-variants") data.available_series = [];
  if (scenario === "partial") for (const row of data.variants) for (const value of Object.values(row.metrics)) Object.assign(value, { observed_days: 2, is_partial: true, source_completeness: "partial" });
  return data;
}
