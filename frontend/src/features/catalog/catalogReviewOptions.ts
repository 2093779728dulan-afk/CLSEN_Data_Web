import type { CatalogImportRow, CatalogSection } from "./catalogTypes";

export type CatalogReviewOption = { label: string; source?: string; value: string };
export type CatalogReviewOptionIndex = Partial<Record<string, Partial<Record<string, CatalogReviewOption[]>>>>;

function text(value: unknown): string | undefined {
  return typeof value === "string" && value.trim() ? value.trim() : undefined;
}

function sourceLabel(value: unknown): string {
  return value === "return_report" || value === "returns" ? "退货报告" : "经营报告";
}

function list(value: unknown): string[] {
  if (typeof value !== "string") return [];
  try {
    const parsed: unknown = JSON.parse(value);
    return Array.isArray(parsed) ? parsed.filter((item): item is string => typeof item === "string" && Boolean(item.trim())) : [];
  } catch { return []; }
}

function unique(options: CatalogReviewOption[]): CatalogReviewOption[] {
  const seen = new Set<string>();
  return options.filter((option) => !seen.has(option.value) && Boolean(seen.add(option.value)));
}

function sourceSku(value: unknown): string | undefined {
  const candidate = text(value);
  return candidate && !candidate.startsWith("<") ? candidate : undefined;
}

export function buildCatalogReviewOptions(rowsBySection: Record<CatalogSection, CatalogImportRow[]>): CatalogReviewOptionIndex {
  const stylesByKey = new Map(rowsBySection.styles.map((row) => [row.row_key, text(row.payload.style_code) ?? "未命名款式"]));
  const evidence = rowsBySection.evidence.flatMap((row) => {
    const sellerSku = sourceSku(row.payload.seller_sku_preview);
    return sellerSku ? [{ report: sourceLabel(row.payload.report_type), sellerSku, title: text(row.payload.latest_title_preview) }] : [];
  });
  const byRow: CatalogReviewOptionIndex = {};
  const set = (row: CatalogImportRow, field: string, options: CatalogReviewOption[]) => {
    if (!options.length) return;
    byRow[row.row_key] = { ...byRow[row.row_key], [field]: unique(options) };
  };

  for (const row of rowsBySection.styles) {
    const styleCode = text(row.payload.style_code);
    if (!styleCode) continue;
    set(row, "standard_name", evidence
      .filter((item) => item.sellerSku.split("-")[0] === styleCode && item.title)
      .map((item) => ({ label: `${item.report} · ${item.title}`, source: item.report, value: item.title ?? "" })));
  }
  for (const row of rowsBySection.skus) {
    const styleCode = stylesByKey.get(text(row.payload.style_row_key) ?? "") ?? "";
    const colors = list(row.payload.source_color_preview);
    const sizes = list(row.payload.source_size_preview);
    const sourceSellers = evidence.filter((item) => {
      const parts = item.sellerSku.split("-");
      const [sourceStyle = "", sourceColor = "", sourceSize = ""] = parts;
      return parts.length === 3 && sourceStyle === styleCode && colors.includes(sourceColor) && sizes.includes(sourceSize);
    });
    set(row, "internal_display_sku", sourceSellers.map((item) => ({ label: `${item.report} · ${item.sellerSku}`, source: item.report, value: item.sellerSku })));
    set(row, "standard_color", colors.map((value) => ({ label: `报告候选 · ${value}`, source: "报告候选", value })));
    set(row, "standard_size", sizes.map((value) => ({ label: `报告候选 · ${value}`, source: "报告候选", value })));
  }
  const targetSkus = rowsBySection.skus.map((row) => {
    const styleCode = stylesByKey.get(text(row.payload.style_row_key) ?? "") ?? "未命名款式";
    const color = text(row.payload.standard_color) ?? list(row.payload.source_color_preview)[0] ?? "未识别颜色";
    const size = text(row.payload.standard_size) ?? list(row.payload.source_size_preview)[0] ?? "未识别尺码";
    return { label: `${styleCode} · ${color} · ${size}`, source: "当前审核候选", value: row.row_key };
  });
  for (const row of rowsBySection.mappings) set(row, "target_sku_row_key", targetSkus);
  for (const row of rowsBySection.exceptions) {
    set(row, "target_sku_row_key", targetSkus);
    set(row, "corrected_style_code", rowsBySection.styles.map((style) => ({ label: text(style.payload.style_code) ?? "未命名款式", source: "当前审核候选", value: text(style.payload.style_code) ?? "" })));
    set(row, "corrected_standard_color", unique(targetSkus.map((option) => { const [, color = ""] = option.label.split(" · "); return { label: color, source: "报告候选", value: color }; }).filter((option) => Boolean(option.value))));
    set(row, "corrected_standard_size", unique(targetSkus.map((option) => { const [, , size = ""] = option.label.split(" · "); return { label: size, source: "报告候选", value: size }; }).filter((option) => Boolean(option.value))));
  }
  return byRow;
}
