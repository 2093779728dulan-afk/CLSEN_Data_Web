import type { StyleLedgerQuery } from "./productAnalyticsTypes";

export const PRODUCT_LEDGER_KEYS = [
  "from", "to", "category_id", "search", "sort", "direction", "page", "page_size",
  "return_basis", "catalog_version", "fact_basis",
] as const;

export type ProductLedgerView = {
  category_id?: number | null;
  catalog_version: string | null;
  direction: NonNullable<StyleLedgerQuery["direction"]>;
  fact_basis: NonNullable<StyleLedgerQuery["fact_basis"]>;
  from: string;
  page: number;
  page_size: number;
  return_basis: NonNullable<StyleLedgerQuery["return_basis"]>;
  search: string;
  sort: NonNullable<StyleLedgerQuery["sort"]>;
  to: string;
};

const SORTS = new Set(["style_code", "standard_name", "units", "sales", "returns", "sessions", "conversion"]);
const DIRECTIONS = new Set(["asc", "desc"]);
const RETURN_BASES = new Set(["event_date", "report_date"]);
const FACT_BASES = new Set(["current", "catalog_snapshot"]);
const ISO_DATE = /^\d{4}-\d{2}-\d{2}$/;

function isDate(value: string): boolean {
  if (!ISO_DATE.test(value)) return false;
  const date = new Date(`${value}T00:00:00Z`);
  return !Number.isNaN(date.valueOf()) && date.toISOString().slice(0, 10) === value;
}

function addDays(value: string, days: number): string {
  const date = new Date(`${value}T00:00:00Z`);
  date.setUTCDate(date.getUTCDate() + days);
  return date.toISOString().slice(0, 10);
}

function positiveInt(value: string | null, fallback: number, allowed?: readonly number[]): number {
  if (!value || !/^[1-9]\d*$/.test(value)) return fallback;
  const parsed = Number(value);
  if (!Number.isSafeInteger(parsed) || (allowed && !allowed.includes(parsed))) return fallback;
  return parsed;
}

export function defaultProductLedgerView(today: string): ProductLedgerView {
  if (!isDate(today)) throw new Error("A valid business date is required.");
  return {
    from: addDays(today, -30), to: today, search: "", sort: "units", direction: "desc",
    page: 1, page_size: 50, return_basis: "event_date", fact_basis: "current",
    catalog_version: null,
  };
}

export function parseProductLedgerSearch(parameters: URLSearchParams, today: string): ProductLedgerView {
  const fallback = defaultProductLedgerView(today);
  const from = parameters.get("from");
  const to = parameters.get("to");
  const validRange = Boolean(from && to && isDate(from) && isDate(to) && from <= to && to <= today
    && addDays(from, 365) >= to);
  const search = parameters.get("search") ?? "";
  const sort = parameters.get("sort") ?? "";
  const direction = parameters.get("direction") ?? "";
  const returnBasis = parameters.get("return_basis") ?? "";
  const factBasis = parameters.get("fact_basis") ?? "";
  const catalogVersion = parameters.get("catalog_version");
  return {
    ...fallback,
    category_id: positiveInt(parameters.get("category_id"), 0) || null,
    from: validRange ? (from as string) : fallback.from,
    to: validRange ? (to as string) : fallback.to,
    search: search.length <= 100 ? search : search.slice(0, 100),
    sort: (SORTS.has(sort) ? sort : fallback.sort) as ProductLedgerView["sort"],
    direction: (DIRECTIONS.has(direction) ? direction : fallback.direction) as ProductLedgerView["direction"],
    page: positiveInt(parameters.get("page"), 1),
    page_size: positiveInt(parameters.get("page_size"), 50, [25, 50, 100]),
    return_basis: (RETURN_BASES.has(returnBasis) ? returnBasis : fallback.return_basis) as ProductLedgerView["return_basis"],
    fact_basis: (FACT_BASES.has(factBasis) ? factBasis : fallback.fact_basis) as ProductLedgerView["fact_basis"],
    catalog_version: catalogVersion && /^\d+$/.test(catalogVersion) ? catalogVersion : null,
  };
}

export function serializeProductLedgerSearch(view: ProductLedgerView): URLSearchParams {
  const parameters = new URLSearchParams();
  parameters.set("from", view.from);
  parameters.set("to", view.to);
  if (view.category_id) parameters.set("category_id", String(view.category_id));
  if (view.search) parameters.set("search", view.search);
  parameters.set("sort", view.sort);
  parameters.set("direction", view.direction);
  parameters.set("page", String(view.page));
  parameters.set("page_size", String(view.page_size));
  parameters.set("return_basis", view.return_basis);
  if (view.catalog_version) parameters.set("catalog_version", String(view.catalog_version));
  parameters.set("fact_basis", view.fact_basis);
  return parameters;
}

export function updateProductLedgerView(
  current: ProductLedgerView,
  change: Partial<ProductLedgerView>,
): ProductLedgerView {
  const resetsPage = ["from", "to", "category_id", "search", "sort", "direction", "page_size", "return_basis", "catalog_version", "fact_basis"]
    .some((key) => key in change && change[key as keyof ProductLedgerView] !== current[key as keyof ProductLedgerView]);
  return { ...current, ...change, page: resetsPage ? 1 : (change.page ?? current.page) };
}
