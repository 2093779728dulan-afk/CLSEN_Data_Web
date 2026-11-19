import { describe, expect, it } from "vitest";
import { compareDraftQuantity } from "./draftQuantity";

describe("source draft quantity differences", () => {
  it("preserves changes beyond JavaScript number precision", () => {
    expect(compareDraftQuantity("999999999999999998", "999999999999999999").difference).toBe("1");
  });
  it("keeps signed reductions and unchanged rows distinct", () => {
    expect(compareDraftQuantity("15", "10")).toMatchObject({ changed: true, difference: "-5" });
    expect(compareDraftQuantity("10", "10")).toMatchObject({ changed: false, difference: "0" });
  });
  it("does not turn an incomplete or out-of-range value into a zero difference", () => {
    for (const value of ["", "-1", "1.5", "010", "1000000000000000000"]) {
      expect(compareDraftQuantity("10", value)).toMatchObject({ changed: true, currentValid: false, difference: undefined });
    }
  });
  it("supports zero in packing drafts while retaining positive order quantities", () => {
    expect(compareDraftQuantity("5", "0", true)).toMatchObject({ currentValid: true, difference: "-5" });
    expect(compareDraftQuantity("5", "0")).toMatchObject({ currentValid: false, difference: undefined });
  });
  it("keeps unresolved original quantities visible", () => {
    expect(compareDraftQuantity("=SUM(A1:A2)", "10")).toMatchObject({ originalValid: false, difference: undefined });
  });
});
