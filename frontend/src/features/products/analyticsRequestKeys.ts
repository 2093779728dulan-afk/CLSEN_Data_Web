import type { StyleCardQuery, StyleLedgerQuery } from "./productAnalyticsTypes";

function canonical(value: string | number | null | undefined): string | number | null {
  return value ?? null;
}

export function styleLedgerRequestKey(query: StyleLedgerQuery) {
  return [
    "style-ledger",
    canonical(query.from),
    canonical(query.to),
    canonical(query.search),
    query.sort ?? "units",
    query.direction ?? "desc",
    query.page ?? 1,
    query.page_size ?? 50,
    canonical(query.catalog_version),
    query.fact_basis ?? "current",
    query.return_basis ?? "event_date",
  ] as const;
}

export function styleCardRequestKey(styleId: string, query: StyleCardQuery) {
  return [
    "style-card",
    styleId,
    canonical(query.from),
    canonical(query.to),
    query.metric ?? "units",
    query.dimension ?? "color",
    canonical(query.color_key),
    query.series === undefined || query.series === null ? null : [...query.series],
    canonical(query.catalog_version),
    query.fact_basis ?? "current",
    query.return_basis ?? "event_date",
  ] as const;
}
