import { afterEach, describe, expect, it } from "vitest";

import type { PresentableColumn } from "../../features/workbench/workbenchTypes";
import {
  loadColumnPreferences,
  preferenceKey,
  saveColumnPreferences,
} from "./columnPreferences";

const identity = { namespace: "workbench" as const, userId: 7, siteId: 3, reportType: "business_report" as const };

const columns: PresentableColumn[] = [
  { column_id: "sku", source_header: "SKU", standard_field_name: "sku", is_key: true, display_order: 1 },
  { column_id: "sessions", source_header: "Sessions", standard_field_name: "sessions", is_key: false, display_order: 2 },
  { column_id: "title", source_header: "Title", standard_field_name: "title", is_key: true, display_order: 3 },
];

afterEach(() => localStorage.clear());

describe("columnPreferences", () => {
  it("merges new columns and isolates identities", () => {
    expect(preferenceKey(identity))
      .toBe("clsen:data-table:v1:workbench:user:7:site:3:report:business_report");
    localStorage.setItem(preferenceKey(identity), "broken-json");
    expect(loadColumnPreferences(preferenceKey(identity), columns).visibleIds)
      .toEqual(columns.map((item) => item.column_id));

    saveColumnPreferences(preferenceKey(identity), {
      version: 1,
      order: ["title", "sku", "removed"],
      hidden: ["sku", "title", "removed"],
      widths: { sku: 20, title: 600, removed: 160 },
    });
    expect(loadColumnPreferences(preferenceKey(identity), columns)).toEqual({
      orderedIds: ["title", "sessions", "sku"],
      visibleIds: ["sessions", "sku"],
      widths: { sku: 72, sessions: 168, title: 480 },
    });
    expect(loadColumnPreferences(preferenceKey({ ...identity, userId: 8 }), columns).orderedIds)
      .toEqual(columns.map((item) => item.column_id));
  });

  it("inserts a newly introduced server column at its one-based display order", () => {
    saveColumnPreferences(preferenceKey(identity), {
      version: 1,
      order: ["title", "sku"],
      hidden: [],
      widths: {},
    });

    expect(loadColumnPreferences(preferenceKey(identity), columns).orderedIds)
      .toEqual(["title", "sessions", "sku"]);
  });

  it("falls back atomically for unsupported or malformed payloads", () => {
    for (const raw of [
      JSON.stringify({ version: 2, order: [], hidden: [], widths: {} }),
      JSON.stringify({ version: 1, order: ["sku"], hidden: "sku", widths: {} }),
      JSON.stringify({ version: 1, order: ["sku"], hidden: [], widths: { sku: "wide" } }),
    ]) {
      localStorage.setItem(preferenceKey(identity), raw);
      expect(loadColumnPreferences(preferenceKey(identity), columns)).toEqual({
        orderedIds: ["sku", "sessions", "title"],
        visibleIds: ["sku", "sessions", "title"],
        widths: { sku: 144, sessions: 168, title: 300 },
      });
    }
  });
});
