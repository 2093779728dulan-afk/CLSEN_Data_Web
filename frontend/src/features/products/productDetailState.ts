import type { StyleCardQuery } from "./productAnalyticsTypes";

export type ProductDetailView = {
  catalog_version: string | null;
  color_key: string | null;
  dimension: NonNullable<StyleCardQuery["dimension"]>;
  fact_basis: NonNullable<StyleCardQuery["fact_basis"]>;
  from: string;
  metric: NonNullable<StyleCardQuery["metric"]>;
  return_basis: NonNullable<StyleCardQuery["return_basis"]>;
  series: readonly string[];
  to: string;
};

const METRICS = new Set(["units", "sales", "returns", "sessions", "conversion"]);
const DIMENSIONS = new Set(["total", "color", "size", "sku"]);
const ISO_DATE = /^\d{4}-\d{2}-\d{2}$/;
function date(value: string) { const parsed = new Date(`${value}T00:00:00Z`); return ISO_DATE.test(value) && !Number.isNaN(parsed.valueOf()) && parsed.toISOString().slice(0, 10) === value; }
function shift(value: string, days: number) { const parsed = new Date(`${value}T00:00:00Z`); parsed.setUTCDate(parsed.getUTCDate() + days); return parsed.toISOString().slice(0, 10); }

export function defaultProductDetailView(today: string): ProductDetailView {
  if (!date(today)) throw new Error("A valid business date is required.");
  return { catalog_version: null, color_key: null, dimension: "color", fact_basis: "current", from: shift(today, -30), metric: "units", return_basis: "event_date", series: [], to: today };
}

export function parseProductDetailSearch(parameters: URLSearchParams, today: string): ProductDetailView {
  const base = defaultProductDetailView(today);
  const from = parameters.get("from"); const to = parameters.get("to");
  const validRange = Boolean(from && to && date(from) && date(to) && from <= to && to <= today && shift(from, 365) >= to);
  const dimension = DIMENSIONS.has(parameters.get("dimension") ?? "") ? parameters.get("dimension")! : base.dimension;
  const rawSeries = parameters.get("series");
  const members = rawSeries === null ? [] : rawSeries.split(",");
  const series = members.length <= 8 && members.every((value) => value.length > 0 && value.length <= 200) && new Set(members).size === members.length ? members : [];
  const colorKey = parameters.get("color_key");
  return {
    ...base,
    from: validRange ? from! : base.from,
    to: validRange ? to! : base.to,
    metric: (METRICS.has(parameters.get("metric") ?? "") ? parameters.get("metric") : base.metric) as ProductDetailView["metric"],
    dimension: dimension as ProductDetailView["dimension"],
    color_key: dimension === "size" && colorKey ? colorKey : null,
    series,
    return_basis: (parameters.get("return_basis") === "report_date" ? "report_date" : "event_date"),
    fact_basis: (parameters.get("fact_basis") === "catalog_snapshot" ? "catalog_snapshot" : "current"),
    catalog_version: /^\d+$/.test(parameters.get("catalog_version") ?? "") ? parameters.get("catalog_version") : null,
  };
}

export function serializeProductDetailSearch(view: ProductDetailView): URLSearchParams {
  const p = new URLSearchParams(); p.set("from", view.from); p.set("to", view.to); p.set("metric", view.metric); p.set("dimension", view.dimension);
  if (view.dimension === "size" && view.color_key) p.set("color_key", view.color_key);
  if (view.series.length) p.set("series", view.series.join(","));
  p.set("return_basis", view.return_basis); if (view.catalog_version) p.set("catalog_version", view.catalog_version); p.set("fact_basis", view.fact_basis); return p;
}

export function updateProductDetailView(current: ProductDetailView, change: Partial<ProductDetailView>): ProductDetailView {
  const next = { ...current, ...change };
  if (next.dimension !== "size") next.color_key = null;
  if (change.dimension !== undefined || change.color_key !== undefined || change.metric !== undefined) next.series = change.series ?? [];
  return next;
}
