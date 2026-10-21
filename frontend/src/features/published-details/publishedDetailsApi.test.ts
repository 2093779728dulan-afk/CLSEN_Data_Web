import { afterEach, describe, expect, it, vi } from "vitest";

import { ApiRequestError } from "../../api/client";
import {
  isPublicationScopeChangedError,
  loadPublishedRows,
  loadPublishedSummaries,
  publishedCsvUrl,
} from "./publishedDetailsApi";

const sortColumnId = "8e4555a0-5397-4b36-b165-0af347ba05b9";
const secondColumnId = "33a2a0be-b232-47f0-9bd7-d6a9b26d2411";

afterEach(() => vi.unstubAllGlobals());

describe("published details API", () => {
  it("carries the returned scope token on subsequent summary pages", async () => {
    const fetchMock = vi.fn()
      .mockResolvedValueOnce(new Response(JSON.stringify({ scope_token: "scope-one" })))
      .mockResolvedValueOnce(new Response(JSON.stringify({ scope_token: "scope-one" })));
    vi.stubGlobal("fetch", fetchMock);

    const first = await loadPublishedSummaries({
      reportType: "business_report",
      from: "2026-07-16",
      to: "2026-08-14",
    });
    await loadPublishedSummaries({
      reportType: "business_report",
      from: "2026-07-16",
      to: "2026-08-14",
      page: 2,
      scopeToken: first.scope_token,
    });

    expect(fetchMock.mock.calls[1]?.[0]).toBe(
      "/api/published-details/summaries?report_type=business_report&from=2026-07-16&to=2026-08-14&page=2&scope_token=scope-one",
    );
  });

  it("passes one caller-owned signal and scope token to rows and date expansion", async () => {
    const signal = new AbortController().signal;
    const fetchMock = vi.fn().mockResolvedValue(
      new Response(JSON.stringify({ scope_token: "scope-one" })),
    );
    vi.stubGlobal("fetch", fetchMock);

    await loadPublishedRows({
      reportType: "return_report",
      from: "2026-07-16",
      to: "2026-08-14",
      page: 2,
      pageSize: 25,
      scopeToken: "scope-one",
      sortColumnId,
      direction: "desc",
      reportDate: "2026-08-12",
    }, signal);

    expect(fetchMock.mock.calls[0]?.[0]).toBe(
      `/api/published-details/rows?report_type=return_report&from=2026-07-16&to=2026-08-14&sort_column_id=${sortColumnId}&direction=desc&page=2&page_size=25&scope_token=scope-one&report_date=2026-08-12`,
    );
    expect(fetchMock.mock.calls[0]?.[1]).toMatchObject({ signal });
  });

  it("builds a same-origin CSV URL with its visible columns in order", () => {
    const fetchMock = vi.fn();
    vi.stubGlobal("fetch", fetchMock);

    expect(publishedCsvUrl({
      reportType: "business_report",
      from: "2026-07-16",
      to: "2026-08-14",
      scopeToken: "scope-one",
      columnIds: [sortColumnId, secondColumnId],
      search: "sku-10",
      sortColumnId,
      direction: "desc",
      reportDate: "2026-08-12",
    })).toBe(
      `/api/published-details/export.csv?report_type=business_report&from=2026-07-16&to=2026-08-14&scope_token=scope-one&column_id=${sortColumnId}&column_id=${secondColumnId}&search=sku-10&sort_column_id=${sortColumnId}&direction=desc&report_date=2026-08-12`,
    );
    expect(fetchMock).not.toHaveBeenCalled();
  });

  it("preserves publication-scope conflicts as the client error code", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(new Response(JSON.stringify({
      error: {
        code: "publication_scope_changed",
        message: "The published scope changed.",
        request_id: "request-1",
      },
    }), { status: 409 })));

    await expect(loadPublishedRows({
      reportType: "business_report",
      from: "2026-07-16",
      to: "2026-08-14",
    })).rejects.toMatchObject({
      code: "publication_scope_changed",
    });

    const conflict = new ApiRequestError(409, "publication_scope_changed", "changed");
    expect(isPublicationScopeChangedError(conflict)).toBe(true);
    expect(isPublicationScopeChangedError(new Error("changed"))).toBe(false);
  });
});
