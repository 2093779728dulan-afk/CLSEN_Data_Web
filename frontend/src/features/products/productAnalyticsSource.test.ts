import { describe, expect, it } from "vitest";
import { parseProductAnalyticsSource, productAnalyticsBundleMarker } from "./productAnalyticsSource";

describe("product analytics release source",()=>{
  it.each([undefined,"","P0_catalog","mixed","legacy_parser "])("fails closed for %s",value=>{expect(()=>parseProductAnalyticsSource(value)).toThrow(/VITE_PRODUCT_ANALYTICS_SOURCE/);});
  it("accepts only the two whole-application modes",()=>{expect(parseProductAnalyticsSource("legacy_parser")).toBe("legacy_parser");expect(parseProductAnalyticsSource("p0_catalog")).toBe("p0_catalog");});
  it("embeds a deterministic bundle marker",()=>{expect(productAnalyticsBundleMarker("p0_catalog")).toBe("product-analytics-source:p0_catalog");});
});
