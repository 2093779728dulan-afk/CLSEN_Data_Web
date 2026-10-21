export type ProductAnalyticsSource = "legacy_parser" | "p0_catalog";

export function parseProductAnalyticsSource(value: string | undefined): ProductAnalyticsSource {
  if (value !== "legacy_parser" && value !== "p0_catalog") {
    throw new Error("VITE_PRODUCT_ANALYTICS_SOURCE must be legacy_parser or p0_catalog.");
  }
  return value;
}

declare const __PRODUCT_ANALYTICS_SOURCE__: string | undefined;

export const PRODUCT_ANALYTICS_SOURCE: ProductAnalyticsSource = parseProductAnalyticsSource(
  typeof __PRODUCT_ANALYTICS_SOURCE__ === "undefined"
    ? process.env.VITE_PRODUCT_ANALYTICS_SOURCE ?? "legacy_parser"
    : __PRODUCT_ANALYTICS_SOURCE__,
);

export function productAnalyticsBundleMarker(source = PRODUCT_ANALYTICS_SOURCE): string {
  return `product-analytics-source:${source}`;
}
