import { describe, expect, it } from "vitest";
import { averagePrice, conversionPercent, returnSalesRatio, salesShare } from "./ledgerInsights";
import type { MetricValue } from "./productAnalyticsTypes";

const metric = (value: string | number | null): MetricValue => ({ value, value_state: "observed", is_partial: false } as MetricValue);
describe("ledger insights", () => {
  it("uses the server filtered total rather than the visible row sum", () => {
    expect(salesShare(metric("25.00"), "100.00")).toBe("25.00%");
    expect(salesShare(metric("25.00"), "25.00")).toBe("100.00%");
    expect(salesShare(metric("25.00"), undefined)).toBe("—");
  });
  it("rounds money and ratios exactly and preserves a return ratio above 100%", () => {
    expect(averagePrice(metric("100.00"), metric(3))).toBe("33.33");
    expect(conversionPercent("0.032655")).toBe("3.27%");
    expect(returnSalesRatio(metric(3), metric(2))).toBe("150.00%");
  });
  it("does not turn missing values or zero denominators into zero rates", () => {
    expect(averagePrice(metric(null), metric(2))).toBe("—");
    expect(averagePrice(metric("20.00"), metric(0))).toBe("—");
    expect(returnSalesRatio(metric(0), metric(2))).toBe("0.00%");
    expect(returnSalesRatio({ ...metric(2), value_state: "missing_report" }, metric(2))).toBe("—");
    expect(salesShare(metric("0.00"), "0.00")).toBe("—");
  });
});
