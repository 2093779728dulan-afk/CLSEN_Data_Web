import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { CoverageReconciliation } from "./CoverageReconciliation";

const block = { confirmed_distinct_rows: 3, coverage_from: "2026-08-01", coverage_to: "2026-08-31", dedup_decision_rate: "1.000000", dedup_status: "complete" as const, duplicate_of_rows: 1, eligible_rows: 10, excluded_rows: 1, expected_days: 31, identity_decision_rate: "0.800000", identity_status: "partial" as const, mapped_rows: 8, mapping_rate: "0.800000", missing_days: 1, published_days: 30, report_coverage_rate: "0.967742", report_type: "business_report" as const, unique_rows: 7, unmatched_rows: 1, unresolved_rows: 0 };
const totals = { conversion_denominator: 10, conversion_numerator: 2, returns: 0, sales: "12.00", sessions: 10, units: 2 };

describe("CoverageReconciliation", () => {
  it("renders both report coverages and all six reconciliation buckets", () => {
    render(<CoverageReconciliation coverage={{ scope: "site", business: block, returns: { ...block, report_type: "return_report" } }} reconciliation={{ scope: "site", metric_status: { units: "evaluable", sales: "evaluable", returns: "evaluable", sessions: "evaluable", conversion: "evaluable" }, source_totals: totals, mapped_totals: totals, unmatched_totals: totals, excluded_totals: totals, duplicate_totals: totals, unresolved_duplicate_totals: { ...totals, units: null } }} />);
    expect(screen.getByText("经营报表")).toBeVisible(); expect(screen.getByText("退货报表")).toBeVisible();
    expect(screen.getByRole("rowheader", { name: "待判定重复" })).toBeVisible();
    expect(screen.getByText("不可计算")).toBeVisible();
  });
});
