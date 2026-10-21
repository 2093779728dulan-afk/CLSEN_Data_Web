import { describe, expect, it } from "vitest";

import type { PresentableColumn } from "../../features/workbench/workbenchTypes";
import {
  clampColumnWidth,
  classifyColumn,
  frozenColumnIds,
  groupVisibleColumns,
  recommendedWidth,
  ROW_NUMBER_WIDTH,
} from "./columnPresentation";

function column(
  columnId: string,
  sourceHeader: string,
  overrides: Partial<PresentableColumn> = {},
): PresentableColumn {
  return {
    column_id: columnId,
    display_order: 0,
    is_key: columnId === "sku",
    source_header: sourceHeader,
    standard_field_name: null,
    ...overrides,
  };
}

describe("columnPresentation", () => {
  it("classifies columns and splits a group after view reordering", () => {
    const columns = [column("sku", "SKU"), column("sessions", "Sessions"), column("title", "Title")];

    expect(groupVisibleColumns("business_report", columns).map((item) => item.label))
      .toEqual(["商品信息", "流量", "商品信息"]);
    expect(recommendedWidth(column("title", "商品标题"))).toBe(300);
    expect(clampColumnWidth(30)).toBe(72);
    expect(clampColumnWidth(800)).toBe(480);
  });

  it("normalizes headers, uses report-specific groups, and preserves contiguous spans", () => {
    expect(classifyColumn("business_report", column("orders", "Conversion Rate (Cafe\u0301)"))).toBe("conversion");
    expect(groupVisibleColumns("return_report", [
      column("sku", "SKU"),
      column("return_reason", "Return Reason"),
      column("refund_amount", "Refund Amount"),
    ]).map((item) => [item.label, item.columnIds]))
      .toEqual([
        ["商品信息", ["sku"]],
        ["退货信息", ["return_reason"]],
        ["金额", ["refund_amount"]],
      ]);
  });

  it("keeps desktop frozen width within 45 percent at 1280px", () => {
    const columns = [column("sku", "SKU", { is_key: true })];
    const widths = { sku: 480 };
    const frozen = frozenColumnIds("business_report", columns, widths, 1280);
    const frozenWidth = ROW_NUMBER_WIDTH + frozen.reduce((total, id) => total + widths[id as keyof typeof widths], 0);

    expect(frozen).toEqual(["sku"]);
    expect(frozenWidth).toBeLessThanOrEqual(1280 * 0.45);
  });

  it("retains an identity column on a 390px viewport even when it exceeds 45 percent", () => {
    const columns = [column("sku", "SKU", { is_key: true })];

    expect(frozenColumnIds("business_report", columns, { sku: 144 }, 390)).toEqual(["sku"]);
  });

  it("reduces supplemental frozen columns while retaining an identity column", () => {
    const columns = [
      column("sessions", "Sessions", { is_key: false }),
      column("sku", "SKU", { is_key: true }),
      column("title", "Title", { is_key: true }),
    ];

    expect(frozenColumnIds("business_report", columns, { sessions: 104, sku: 144, title: 300 }, 800))
      .toEqual(["sku", "sessions"]);
  });

  it("uses the rendered row-number width at the exact desktop freeze boundary", () => {
    const columns = [
      column("sku", "SKU", { is_key: true }),
      column("sessions", "Sessions", { is_key: false }),
    ];
    const viewportWidth = 1280;
    const atBoundary = { sku: 448, sessions: 76 };
    const beyondBoundary = { sku: 448, sessions: 77 };

    const frozen = frozenColumnIds("business_report", columns, atBoundary, viewportWidth);
    expect(frozen).toEqual(["sku", "sessions"]);
    expect(ROW_NUMBER_WIDTH + frozen.reduce((total, id) => total + atBoundary[id as keyof typeof atBoundary], 0))
      .toBe(viewportWidth * 0.45);
    expect(frozenColumnIds("business_report", columns, beyondBoundary, viewportWidth)).toEqual(["sku"]);
  });
});
