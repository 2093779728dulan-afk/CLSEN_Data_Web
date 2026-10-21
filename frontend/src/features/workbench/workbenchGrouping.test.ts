import { describe, expect, it } from "vitest";

import type { WorkbenchColumn, WorkbenchRow } from "./workbenchTypes";
import { groupKey, rowGroupBoundaries } from "./workbenchGrouping";

const columns: WorkbenchColumn[] = [
  { column_id: "parent_asin", source_header: "Parent ASIN", standard_field_name: "parent_asin", is_key: true, display_order: 1, editable: false, participates_in_statistics: false, value_kind: "text" },
  { column_id: "sku", source_header: "Seller SKU", standard_field_name: "sku", is_key: true, display_order: 2, editable: false, participates_in_statistics: false, value_kind: "text" },
  { column_id: "asin", source_header: "ASIN", standard_field_name: "asin", is_key: true, display_order: 3, editable: false, participates_in_statistics: false, value_kind: "text" },
];

function row(row_id: number, values: Record<string, string | null>): WorkbenchRow {
  return {
    row_id,
    row_ordinal: row_id,
    row_state: "active",
    cells: columns.map((column) => ({
      base: null,
      cell_revision: 0,
      changed: false,
      column_id: column.column_id,
      current: values[column.column_id] ?? null,
      editable: false,
    })),
  };
}

describe("workbench product grouping", () => {
  it("uses parent ASIN then a strict numeric three-segment SKU prefix without reordering rows", () => {
    const rows = [
      row(1, { parent_asin: "B000-PARENT", sku: "2401-Black-M" }),
      row(2, { parent_asin: "B000-PARENT", sku: "2401-White-L" }),
      row(3, { sku: "2401-Black-XL" }),
    ];

    expect(rowGroupBoundaries("business_report", rows, columns)).toEqual([
      { key: "B000-PARENT", startsGroup: true },
      { key: "B000-PARENT", startsGroup: false },
      { key: "2401", startsGroup: true },
    ]);
    expect(rows.map((item) => item.row_id)).toEqual([1, 2, 3]);
  });

  it("does not merge uncertain business SKUs and leaves missing identities ungrouped", () => {
    expect(groupKey("business_report", row(1, { sku: "not-a-style" }), columns)).toBe("not-a-style");
    expect(groupKey("business_report", row(2, {}), columns)).toBeNull();
    expect(rowGroupBoundaries("business_report", [row(1, {}), row(2, { sku: "2401-Black-M" })], columns)).toEqual([
      { key: null, startsGroup: false },
      { key: "2401", startsGroup: true },
    ]);
  });

  it("uses return-report SKU first and ASIN only as its fallback", () => {
    expect(groupKey("return_report", row(1, { sku: "RETURN-1", asin: "B0FIRST" }), columns)).toBe("RETURN-1");
    expect(groupKey("return_report", row(2, { asin: "B0SECOND" }), columns)).toBe("B0SECOND");
  });

  it("marks the first reliable row on this page as a local group boundary", () => {
    expect(rowGroupBoundaries("business_report", [row(9, { parent_asin: "B0PAGEFIRST" })], columns)).toEqual([
      { key: "B0PAGEFIRST", startsGroup: true },
    ]);
  });
});
