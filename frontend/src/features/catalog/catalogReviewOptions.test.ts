import { describe, expect, it } from "vitest";

import type { CatalogImportRow, CatalogSection } from "./catalogTypes";
import { buildCatalogReviewOptions } from "./catalogReviewOptions";

function row(
  section: CatalogSection,
  rowKey: string,
  payload: Record<string, string | number | null>,
): CatalogImportRow {
  return {
    payload,
    projection_state: "included",
    row_key: rowKey,
    row_origin: "system",
    section,
  };
}

describe("buildCatalogReviewOptions", () => {
  it("associates report suggestions with the exact style, color, and size", () => {
    const options = buildCatalogReviewOptions({
      evidence: [
        row("evidence", "evidence-exact", {
          latest_title_preview: "Classic Tee",
          report_type: "business_report",
          seller_sku_preview: "2201-Black-M",
        }),
        row("evidence", "evidence-wrong-size", {
          latest_title_preview: "Classic Tee Large",
          report_type: "return_report",
          seller_sku_preview: "2201-Black-L",
        }),
      ],
      exceptions: [],
      mappings: [],
      skus: [
        row("skus", "sku-black-m", {
          source_color_preview: JSON.stringify(["Black"]),
          source_size_preview: JSON.stringify(["M"]),
          standard_color: null,
          standard_size: null,
          style_row_key: "style-2201",
        }),
      ],
      styles: [
        row("styles", "style-2201", {
          standard_name: null,
          style_code: "2201",
        }),
      ],
    });

    expect(options["style-2201"]?.standard_name).toEqual([
      { label: "经营报告 · Classic Tee", source: "经营报告", value: "Classic Tee" },
      { label: "退货报告 · Classic Tee Large", source: "退货报告", value: "Classic Tee Large" },
    ]);
    expect(options["sku-black-m"]?.internal_display_sku).toEqual([
      { label: "经营报告 · 2201-Black-M", source: "经营报告", value: "2201-Black-M" },
    ]);
  });

  it("treats malformed candidate-set previews as having no suggestions", () => {
    const options = buildCatalogReviewOptions({
      evidence: [],
      exceptions: [],
      mappings: [],
      skus: [
        row("skus", "sku-invalid", {
          source_color_preview: "not-json",
          source_size_preview: "not-json",
          style_row_key: "style-2201",
        }),
      ],
      styles: [row("styles", "style-2201", { style_code: "2201" })],
    });

    expect(options["sku-invalid"]?.standard_color).toBeUndefined();
    expect(options["sku-invalid"]?.standard_size).toBeUndefined();
  });
});
