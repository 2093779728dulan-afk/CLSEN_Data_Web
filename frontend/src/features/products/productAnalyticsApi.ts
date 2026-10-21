import { requestApi } from "../../api/client";
import type {
  StyleCardQuery,
  StyleCardResponse,
  StyleLedgerQuery,
  StyleLedgerResponse,
} from "./productAnalyticsTypes";

type QueryValue = string | number | null | undefined;

function append(
  parameters: URLSearchParams,
  name: string,
  value: QueryValue,
): void {
  if (value !== null && value !== undefined) parameters.set(name, String(value));
}

function ledgerParameters(query: StyleLedgerQuery): URLSearchParams {
  const parameters = new URLSearchParams();
  append(parameters, "from", query.from);
  append(parameters, "to", query.to);
  append(parameters, "search", query.search);
  append(parameters, "category_id", query.category_id);
  append(parameters, "sort", query.sort);
  append(parameters, "direction", query.direction);
  append(parameters, "page", query.page);
  append(parameters, "page_size", query.page_size);
  append(parameters, "catalog_version", query.catalog_version);
  append(parameters, "fact_basis", query.fact_basis);
  append(parameters, "return_basis", query.return_basis);
  return parameters;
}

function cardParameters(query: StyleCardQuery): URLSearchParams {
  const parameters = new URLSearchParams();
  append(parameters, "from", query.from);
  append(parameters, "to", query.to);
  append(parameters, "metric", query.metric);
  append(parameters, "dimension", query.dimension);
  append(parameters, "color_key", query.color_key);
  append(parameters, "series", query.series && query.series.length > 0 ? query.series.join(",") : undefined);
  append(parameters, "catalog_version", query.catalog_version);
  append(parameters, "fact_basis", query.fact_basis);
  append(parameters, "return_basis", query.return_basis);
  return parameters;
}

function withQuery(path: string, parameters: URLSearchParams): string {
  const query = parameters.toString();
  return query ? `${path}?${query}` : path;
}

export function loadStyleLedger(
  query: StyleLedgerQuery,
  signal?: AbortSignal,
): Promise<StyleLedgerResponse> {
  return requestApi<StyleLedgerResponse>(
    withQuery("/api/dashboard/style-ledger", ledgerParameters(query)),
    { signal },
  );
}

export function loadStyleCard(
  styleId: string,
  query: StyleCardQuery,
  signal?: AbortSignal,
): Promise<StyleCardResponse> {
  return requestApi<StyleCardResponse>(
    withQuery(
      `/api/dashboard/styles/${encodeURIComponent(styleId)}/card`,
      cardParameters(query),
    ),
    { signal },
  );
}
