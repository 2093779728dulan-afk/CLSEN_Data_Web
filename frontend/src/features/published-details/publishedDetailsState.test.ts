import { describe, expect, it } from "vitest";

import {
  parsePublishedDetailsSearch,
  serializePublishedDetailsSearch,
  updatePublishedDetailsViewState,
} from "./publishedDetailsState";

describe("published details URL state", () => {
  it("uses an explicit rolling 30-calendar-day range by default", () => {
    expect(parsePublishedDetailsSearch(new URLSearchParams(), "2026-08-14")).toMatchObject({
      from: "2026-07-16",
      to: "2026-08-14",
      mode: "summary",
      reportType: "business_report",
      page: 1,
      direction: "asc",
    });
  });

  it("uses ISO calendar arithmetic across month and leap-year boundaries", () => {
    expect(parsePublishedDetailsSearch(new URLSearchParams(), "2024-03-01")).toMatchObject({
      from: "2024-02-01",
      to: "2024-03-01",
    });
    expect(parsePublishedDetailsSearch(new URLSearchParams(), "2024-03-29")).toMatchObject({
      from: "2024-02-29",
      to: "2024-03-29",
    });
  });

  it("normalizes invalid and reversed date, enum, page, and sort values", () => {
    const state = parsePublishedDetailsSearch(
      new URLSearchParams({
        report_type: "not-a-report",
        from: "2026-02-30",
        to: "2026-02-01",
        mode: "table",
        page: "0",
        direction: "sideways",
        sort_column_id: "not-a-uuid",
        report_date: "2026-02-30",
      }),
      "2026-08-14",
    );

    expect(state).toMatchObject({
      reportType: "business_report",
      from: "2026-07-16",
      to: "2026-08-14",
      mode: "summary",
      direction: "asc",
      page: 1,
    });
    expect(state.sortColumnId).toBeUndefined();
    expect(state.expandedDate).toBeUndefined();
  });

  it("keeps only shareable filters in a stable canonical query string", () => {
    const state = parsePublishedDetailsSearch(
      new URLSearchParams({
        report_type: "return_report",
        from: "2024-02-01",
        to: "2024-02-29",
        mode: "rows",
        search: "sku-10",
        sort_column_id: "8E4555A0-5397-4B36-B165-0AF347BA05B9",
        direction: "desc",
        page: "3",
        report_date: "2024-02-14",
        scope_token: "must-not-be-shared",
        column_widths: "also-not-shared",
        hidden_columns: "also-not-shared",
      }),
      "2024-02-29",
    );

    expect(serializePublishedDetailsSearch(state).toString()).toBe(
      "report_type=return_report&from=2024-02-01&to=2024-02-29&mode=rows&search=sku-10&sort_column_id=8e4555a0-5397-4b36-b165-0af347ba05b9&direction=desc&page=3&report_date=2024-02-14",
    );
  });

  it("drops a direction that has no stable UUID sort column", () => {
    const state = parsePublishedDetailsSearch(
      new URLSearchParams({
        from: "2026-08-01",
        to: "2026-08-14",
        direction: "desc",
      }),
      "2026-08-14",
    );

    expect(state.direction).toBe("asc");
    expect(serializePublishedDetailsSearch(state).toString()).toBe(
      "from=2026-08-01&to=2026-08-14",
    );
  });

  it("resets pagination when a mode, report tab, or filter changes", () => {
    const current = parsePublishedDetailsSearch(
      new URLSearchParams({
        from: "2026-08-01",
        to: "2026-08-14",
        mode: "rows",
        search: "old",
        page: "4",
      }),
      "2026-08-14",
    );

    expect(updatePublishedDetailsViewState(current, { mode: "summary" }).page).toBe(1);
    expect(updatePublishedDetailsViewState(current, { reportType: "return_report" }).page).toBe(1);
    expect(updatePublishedDetailsViewState(current, { search: "new" }).page).toBe(1);
    expect(updatePublishedDetailsViewState(current, { page: 5 }).page).toBe(5);
  });
});
