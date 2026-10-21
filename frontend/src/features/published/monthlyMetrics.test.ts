import { describe, expect, it } from "vitest";
import type { DailyLedgerRow } from "../../api/generated";
import { comparePrevious, formatMetric, monthlyPoints, total } from "./monthlyMetrics";

function row(date: string, sales: string | null, overrides: Partial<DailyLedgerRow> = {}): DailyLedgerRow {
  return { report_date: date, business_status: "published", return_status: "missing", sales, units_ordered: 1, sessions: 5, conversion_rate: "0.2", return_quantity: null, counts_as_incomplete: true, overall_status: "partial", pending_summary: null, reasons: [], ...overrides };
}

describe("published month metrics", () => {
  it("uses calendar dates through the selected day, keeping gaps and real zeros", () => {
    const points = monthlyPoints([row("2025-07-01", "0.00"), row("2025-07-03", "1.00"), row("2025-07-04", "999.00"), row("2025-06-30", "999.00")], "2025-07-03", "sales");
    expect(points.map((point) => point.value)).toEqual([0n, null, 10n ** 30n]);
    expect(formatMetric(total(points), "sales", "USD")).toBe("US$1.00");
  });
  it("does not count unpublished report values or borrow business coverage for returns", () => {
    const rows = [row("2025-07-01", "20.00", { business_status: "draft", return_quantity: 7 })];
    expect(total(monthlyPoints(rows, "2025-07-01", "sales"))).toBeNull();
    expect(total(monthlyPoints(rows, "2025-07-01", "return_quantity"))).toBeNull();
  });
  it("sums large decimal amounts without floating-point loss", () => {
    const points = monthlyPoints([row("2025-07-01", "9007199254740992.01"), row("2025-07-02", "0.02")], "2025-07-02", "sales");
    expect(formatMetric(total(points), "sales", "USD")).toBe("US$9,007,199,254,740,992.03");
  });
  it("compares adjacent dates and refuses to bridge missing days", () => {
    const points = monthlyPoints([row("2025-07-01", "100.00"), row("2025-07-02", "80.00")], "2025-07-02", "sales");
    expect(comparePrevious(points, "sales", "USD")).toMatchObject({ direction: "down", amount: "减少 US$20.00", detail: "变化幅度 −20.00%。" });
    expect(comparePrevious([points[0]!, { date: "2025-07-02", value: null }, { date: "2025-07-03", value: 1n }], "sales", "USD").direction).toBe("unavailable");
  });
  it("handles zero baselines without an infinite growth percentage", () => {
    const points = monthlyPoints([row("2025-07-01", "0.00"), row("2025-07-02", "10.00")], "2025-07-02", "sales");
    expect(comparePrevious(points, "sales", "USD")).toMatchObject({ amount: "增加 US$10.00", detail: "前一日为 0，无可比百分比基数。" });
  });
  it("compares conversion rate in percentage points and keeps all-missing totals unknown", () => {
    const points = monthlyPoints([row("2025-07-01", "1.00", { conversion_rate: "0.10" }), row("2025-07-02", "1.00", { conversion_rate: "0.20" })], "2025-07-02", "conversion_rate");
    expect(comparePrevious(points, "conversion_rate", "USD").amount).toBe("增加 10.00 个百分点");
    expect(total(monthlyPoints([], "2025-07-02", "sales"))).toBeNull();
  });
});

it("accepts the API's 28-place conversion ratio without turning it into a missing day", () => {
  const points = monthlyPoints([row("2025-07-01", "1.00", { conversion_rate: "0.1022556390977443609022556391" }), row("2025-07-02", "1.00", { conversion_rate: "0.2" })], "2025-07-02", "conversion_rate");
  expect(formatMetric(points[0]!.value, "conversion_rate", "USD")).toBe("10.23%");
  expect(comparePrevious(points, "conversion_rate", "USD").amount).toBe("增加 9.77 个百分点");
});
