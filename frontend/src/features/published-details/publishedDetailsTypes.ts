import type {
  PublishedRangeResponse as GeneratedPublishedRangeResponse,
  PublishedRowsResponse as GeneratedPublishedRowsResponse,
  PublishedSummaryResponse as GeneratedPublishedSummaryResponse,
  ReportType,
  SortDirection,
} from "../../api/generated";

export type PublishedDetailsMode = "summary" | "rows";

/** Shareable state for the published-details URL. */
export type PublishedDetailsViewState = {
  reportType: ReportType;
  from: string;
  to: string;
  mode: PublishedDetailsMode;
  search: string;
  sortColumnId?: string;
  direction: SortDirection;
  page: number;
  expandedDate?: string;
};

type PublishedDetailsScopedQuery = {
  reportType: ReportType;
  from: string;
  to: string;
  search?: string;
  scopeToken?: string;
};

export type PublishedSummaryQuery = PublishedDetailsScopedQuery & {
  page?: number;
  pageSize?: number;
};

export type PublishedRowsQuery = PublishedSummaryQuery & {
  sortColumnId?: string;
  direction?: SortDirection;
  reportDate?: string;
};

export type PublishedExportQuery = PublishedDetailsScopedQuery & {
  scopeToken: string;
  columnIds: readonly string[];
  sortColumnId?: string;
  direction?: SortDirection;
  reportDate?: string;
};

export type PublishedRangeResponse = GeneratedPublishedRangeResponse;
export type PublishedSummaryResponse = GeneratedPublishedSummaryResponse;
export type PublishedRowsResponse = GeneratedPublishedRowsResponse;
