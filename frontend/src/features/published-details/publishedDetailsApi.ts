import { ApiRequestError, requestApi } from "../../api/client";
import type {
  PublishedExportQuery,
  PublishedRangeResponse,
  PublishedRowsQuery,
  PublishedRowsResponse,
  PublishedSummaryQuery,
  PublishedSummaryResponse,
} from "./publishedDetailsTypes";

export function loadPublishedRange(reportType: PublishedSummaryQuery["reportType"], signal?: AbortSignal) {
  const parameters = new URLSearchParams({ report_type: reportType });
  return requestApi<PublishedRangeResponse>(`/api/published-details/range?${parameters}`, { signal });
}

export function loadPublishedSummaries(query: PublishedSummaryQuery, signal?: AbortSignal) {
  return requestApi<PublishedSummaryResponse>(
    `/api/published-details/summaries?${summaryParams(query)}`,
    { signal },
  );
}

export function loadPublishedRows(query: PublishedRowsQuery, signal?: AbortSignal) {
  return requestApi<PublishedRowsResponse>(
    `/api/published-details/rows?${rowsParams(query)}`,
    { signal },
  );
}

/** Returns a same-origin download URL; callers navigate to it rather than fetching it. */
export function publishedCsvUrl(query: PublishedExportQuery): string {
  return `/api/published-details/export.csv?${exportParams(query)}`;
}

export function isPublicationScopeChangedError(error: unknown): error is ApiRequestError {
  return error instanceof ApiRequestError && error.code === "publication_scope_changed";
}

function summaryParams(query: PublishedSummaryQuery): URLSearchParams {
  const parameters = baseParams(query);
  appendPagination(parameters, query);
  appendScopeToken(parameters, query.scopeToken);
  return parameters;
}

function rowsParams(query: PublishedRowsQuery): URLSearchParams {
  const parameters = baseParams(query);
  if (query.sortColumnId) parameters.set("sort_column_id", query.sortColumnId);
  if (query.direction) parameters.set("direction", query.direction);
  appendPagination(parameters, query);
  appendScopeToken(parameters, query.scopeToken);
  if (query.reportDate) parameters.set("report_date", query.reportDate);
  return parameters;
}

function exportParams(query: PublishedExportQuery): URLSearchParams {
  if (!query.scopeToken) throw new Error("Published CSV exports require a scope token.");
  const parameters = new URLSearchParams({
    report_type: query.reportType,
    from: query.from,
    to: query.to,
  });
  parameters.set("scope_token", query.scopeToken);
  for (const columnId of query.columnIds) parameters.append("column_id", columnId);
  if (query.search) parameters.set("search", query.search);
  if (query.sortColumnId) parameters.set("sort_column_id", query.sortColumnId);
  if (query.direction) parameters.set("direction", query.direction);
  if (query.reportDate) parameters.set("report_date", query.reportDate);
  return parameters;
}

function baseParams(query: Pick<PublishedSummaryQuery, "reportType" | "from" | "to" | "search">): URLSearchParams {
  const parameters = new URLSearchParams({
    report_type: query.reportType,
    from: query.from,
    to: query.to,
  });
  if (query.search) parameters.set("search", query.search);
  return parameters;
}

function appendPagination(parameters: URLSearchParams, query: Pick<PublishedSummaryQuery, "page" | "pageSize">): void {
  if (query.page !== undefined) parameters.set("page", String(query.page));
  if (query.pageSize !== undefined) parameters.set("page_size", String(query.pageSize));
}

function appendScopeToken(parameters: URLSearchParams, scopeToken: string | undefined): void {
  if (scopeToken) parameters.set("scope_token", scopeToken);
}
