import { describe, expect, it } from "vitest";

import { styleCardRequestKey, styleLedgerRequestKey } from "./analyticsRequestKeys";

describe("analytics request keys", () => {
  it("uses the complete canonical ledger tuple", () => {
    expect(
      styleLedgerRequestKey({
        from: "2026-08-01",
        to: "2026-08-24",
        search: "coat",
        sort: "conversion",
        direction: "asc",
        page: 3,
        page_size: 25,
        catalog_version: "7",
        fact_basis: "catalog_snapshot",
        return_basis: "report_date",
      }),
    ).toEqual([
      "style-ledger",
      "2026-08-01",
      "2026-08-24",
      "coat",
      "conversion",
      "asc",
      3,
      25,
      "7",
      "catalog_snapshot",
      "report_date",
    ]);
  });

  it("distinguishes omitted values and every card selector", () => {
    const base = styleCardRequestKey("2301", {});
    const selected = styleCardRequestKey("2301", {
      metric: "sales",
      dimension: "size",
      color_key: "black",
      series: ["a", "b"],
    });
    expect(base).not.toEqual(selected);
    expect(selected).toEqual([
      "style-card",
      "2301",
      null,
      null,
      "sales",
      "size",
      "black",
      ["a", "b"],
      null,
      "current",
      "event_date",
    ]);
  });
});
