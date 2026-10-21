import { afterEach, describe, expect, it, vi } from "vitest";

import { ApiRequestError } from "../../api/client";
import { loadStyleCard, loadStyleLedger } from "./productAnalyticsApi";

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("product analytics API", () => {
  it("calls only the stable style ledger path with the complete query", async () => {
    const fetchMock = vi.fn().mockResolvedValue(
      new Response(JSON.stringify({ rows: [] }), {
        headers: { "Content-Type": "application/json" },
        status: 200,
      }),
    );
    vi.stubGlobal("fetch", fetchMock);

    await loadStyleLedger({
      from: "2026-08-01",
      to: "2026-08-24",
      search: "2301",
      sort: "sales",
      direction: "asc",
      page: 2,
      page_size: 100,
      catalog_version: "19",
      fact_basis: "catalog_snapshot",
      return_basis: "report_date",
    });

    expect(fetchMock).toHaveBeenCalledTimes(1);
    expect(fetchMock.mock.calls[0]?.[0]).toBe(
      "/api/dashboard/style-ledger?from=2026-08-01&to=2026-08-24&search=2301&sort=sales&direction=asc&page=2&page_size=100&catalog_version=19&fact_basis=catalog_snapshot&return_basis=report_date",
    );
  });

  it("encodes stable card keys and never guesses a legacy route", async () => {
    const fetchMock = vi.fn().mockResolvedValue(
      new Response(JSON.stringify({ style: { style_id: "2301" } }), {
        headers: { "Content-Type": "application/json" },
        status: 200,
      }),
    );
    vi.stubGlobal("fetch", fetchMock);

    await loadStyleCard("2301", {
      from: "2026-08-01",
      to: "2026-08-24",
      metric: "conversion",
      dimension: "size",
      color_key: "black/key",
      series: ["series+a", "系列二"],
      return_basis: "event_date",
    });

    const path = String(fetchMock.mock.calls[0]?.[0]);
    expect(path).toContain("/api/dashboard/styles/2301/card?");
    expect(path).toContain("color_key=black%2Fkey");
    expect(path).toContain("series=series%2Ba%2C%E7%B3%BB%E5%88%97%E4%BA%8C");
    expect(path).not.toContain("product-card");
    expect(fetchMock).toHaveBeenCalledTimes(1);
  });

  it("omits an empty series list so the service can apply its default", async () => {
    const fetchMock = vi.fn().mockResolvedValue(new Response(JSON.stringify({}), { headers: { "Content-Type": "application/json" }, status: 200 }));
    vi.stubGlobal("fetch", fetchMock);
    await loadStyleCard("2301", { dimension: "color", series: [] });
    expect(String(fetchMock.mock.calls[0]?.[0])).not.toContain("series=");
  });

  it.each([
    [404, "catalog_style_not_found"],
    [409, "analytics_identity_fact_combination_invalid"],
    [422, "analytics_series_invalid"],
  ])("does not fallback after HTTP %i", async (status, code) => {
    const fetchMock = vi.fn().mockResolvedValue(
      new Response(JSON.stringify({ error: { code, message: "failed" } }), {
        headers: { "Content-Type": "application/json" },
        status,
      }),
    );
    vi.stubGlobal("fetch", fetchMock);

    await expect(loadStyleCard("2301", {})).rejects.toBeInstanceOf(ApiRequestError);
    expect(fetchMock).toHaveBeenCalledTimes(1);
    expect(fetchMock.mock.calls[0]?.[0]).not.toContain("product-card");
  });
});
