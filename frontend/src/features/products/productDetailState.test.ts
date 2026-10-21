import { describe, expect, it } from "vitest";
import { parseProductDetailSearch, serializeProductDetailSearch, updateProductDetailView } from "./productDetailState";

describe("product detail URL state", () => {
  it("keeps only the exact whitelist and repairs invalid series syntax", () => {
    const parsed=parseProductDetailSearch(new URLSearchParams("from=2026-08-01&to=2026-08-24&metric=returns&dimension=sku&series=a,a&unknown=1"),"2026-08-24");
    expect(parsed).toMatchObject({metric:"returns",dimension:"sku",series:[]}); expect(serializeProductDetailSearch(parsed).has("unknown")).toBe(false);
  });
  it("limits series to eight and requires color only for size", () => {
    const eight=Array.from({length:8},(_,i)=>`系列-${i}`).join(",");
    expect(parseProductDetailSearch(new URLSearchParams(`dimension=size&color_key=color-x&series=${encodeURIComponent(eight)}`),"2026-08-24").series).toHaveLength(8);
    expect(parseProductDetailSearch(new URLSearchParams("dimension=size&series=1,2,3,4,5,6,7,8,9"),"2026-08-24").series).toEqual([]);
    expect(parseProductDetailSearch(new URLSearchParams("dimension=color&color_key=stale"),"2026-08-24").color_key).toBeNull();
  });
  it("clears dependent color and series on dimension changes",()=>{const base=parseProductDetailSearch(new URLSearchParams("dimension=size&color_key=c&series=s"),"2026-08-24");expect(updateProductDetailView(base,{dimension:"color"})).toMatchObject({color_key:null,series:[]});});
});
