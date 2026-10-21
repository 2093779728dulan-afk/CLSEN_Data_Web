import type {
  PublishedDetailsMode,
  PublishedDetailsViewState,
} from "./publishedDetailsTypes";

const ISO_DATE_PATTERN = /^(\d{4})-(\d{2})-(\d{2})$/;
const UUID_PATTERN = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;
const MAX_SEARCH_LENGTH = 200;

type CalendarDate = {
  year: number;
  month: number;
  day: number;
};

export function defaultPublishedDetailsRange(today: string): { from: string; to: string } {
  const current = parseIsoDate(today);
  if (!current) {
    throw new Error("Published-details today must be an ISO calendar date.");
  }
  return { from: formatIsoDate(subtractCalendarDays(current, 29)), to: today };
}

export function parsePublishedDetailsSearch(
  params: URLSearchParams,
  today: string,
): PublishedDetailsViewState {
  const fallbackRange = defaultPublishedDetailsRange(today);
  const requestedFrom = params.get("from");
  const requestedTo = params.get("to");
  const from = parseIsoDate(requestedFrom ?? "");
  const to = parseIsoDate(requestedTo ?? "");
  const validRange = from && to && compareIsoDates(from, to) <= 0;
  const range = validRange
    ? { from: requestedFrom as string, to: requestedTo as string }
    : fallbackRange;
  const reportType = params.get("report_type") === "return_report"
    ? "return_report"
    : "business_report";
  const mode: PublishedDetailsMode = params.get("mode") === "rows" ? "rows" : "summary";
  const expandedDate = params.get("report_date");
  const parsedExpandedDate = parseIsoDate(expandedDate ?? "");
  const sortColumnId = normalizeUuid(params.get("sort_column_id"));

  return {
    reportType,
    ...range,
    mode,
    search: normalizeSearch(params.get("search")),
    sortColumnId,
    direction: sortColumnId && params.get("direction") === "desc" ? "desc" : "asc",
    page: parsePage(params.get("page")),
    expandedDate: parsedExpandedDate && expandedDate && isDateInRange(expandedDate, range)
      ? expandedDate
      : undefined,
  };
}

export function serializePublishedDetailsSearch(
  state: PublishedDetailsViewState,
): URLSearchParams {
  const parameters = new URLSearchParams();
  if (state.reportType === "return_report") parameters.set("report_type", state.reportType);
  parameters.set("from", state.from);
  parameters.set("to", state.to);
  if (state.mode === "rows") parameters.set("mode", state.mode);
  if (state.search) parameters.set("search", state.search);
  const sortColumnId = normalizeUuid(state.sortColumnId);
  if (sortColumnId) parameters.set("sort_column_id", sortColumnId);
  if (sortColumnId && state.direction === "desc") parameters.set("direction", state.direction);
  if (isSafePage(state.page) && state.page > 1) parameters.set("page", String(state.page));
  if (state.expandedDate && isDateInRange(state.expandedDate, state)) {
    parameters.set("report_date", state.expandedDate);
  }
  return parameters;
}

/**
 * Applies one URL-state update. Changing a tab, mode, or query filter always
 * starts from the first page; selection-only changes keep the current page.
 */
export function updatePublishedDetailsViewState(
  current: PublishedDetailsViewState,
  updates: Partial<PublishedDetailsViewState>,
): PublishedDetailsViewState {
  const next = { ...current, ...updates };
  const sortColumnId = normalizeUuid(next.sortColumnId);
  const direction = sortColumnId && next.direction === "desc" ? "desc" : "asc";
  const resetsPage = (
    next.reportType !== current.reportType
    || next.from !== current.from
    || next.to !== current.to
    || next.mode !== current.mode
    || next.search !== current.search
    || sortColumnId !== current.sortColumnId
    || direction !== current.direction
  );
  return {
    ...next,
    sortColumnId,
    direction,
    page: resetsPage ? 1 : parsePage(String(next.page)),
  };
}

function normalizeSearch(value: string | null): string {
  return value?.slice(0, MAX_SEARCH_LENGTH) ?? "";
}

function normalizeUuid(value: string | null | undefined): string | undefined {
  return value && UUID_PATTERN.test(value) ? value.toLowerCase() : undefined;
}

function parsePage(value: string | null): number {
  if (!value || !/^\d+$/.test(value)) return 1;
  const page = Number(value);
  return isSafePage(page) ? page : 1;
}

function isSafePage(value: number): boolean {
  return Number.isSafeInteger(value) && value >= 1;
}

function parseIsoDate(value: string): CalendarDate | undefined {
  const match = ISO_DATE_PATTERN.exec(value);
  if (!match) return undefined;
  const year = Number(match[1]);
  const month = Number(match[2]);
  const day = Number(match[3]);
  return year >= 1 && month >= 1 && month <= 12 && day >= 1 && day <= daysInMonth(year, month)
    ? { year, month, day }
    : undefined;
}

function isDateInRange(value: string, range: Pick<PublishedDetailsViewState, "from" | "to">): boolean {
  const date = parseIsoDate(value);
  const from = parseIsoDate(range.from);
  const to = parseIsoDate(range.to);
  return Boolean(date && from && to && compareIsoDates(from, date) <= 0 && compareIsoDates(date, to) <= 0);
}

function compareIsoDates(left: CalendarDate, right: CalendarDate): number {
  if (left.year !== right.year) return left.year - right.year;
  if (left.month !== right.month) return left.month - right.month;
  return left.day - right.day;
}

function subtractCalendarDays(date: CalendarDate, count: number): CalendarDate {
  let { year, month, day } = date;
  for (let remaining = count; remaining > 0; remaining -= 1) {
    if (day > 1) {
      day -= 1;
      continue;
    }
    if (month > 1) {
      month -= 1;
    } else {
      year -= 1;
      month = 12;
    }
    day = daysInMonth(year, month);
  }
  return { year, month, day };
}

function daysInMonth(year: number, month: number): number {
  if (month === 2) return isLeapYear(year) ? 29 : 28;
  return month === 4 || month === 6 || month === 9 || month === 11 ? 30 : 31;
}

function isLeapYear(year: number): boolean {
  return year % 4 === 0 && (year % 100 !== 0 || year % 400 === 0);
}

function formatIsoDate(date: CalendarDate): string {
  return `${String(date.year).padStart(4, "0")}-${String(date.month).padStart(2, "0")}-${String(date.day).padStart(2, "0")}`;
}
