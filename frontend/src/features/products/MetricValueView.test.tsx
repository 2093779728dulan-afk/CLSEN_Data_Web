import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import type { MetricValue } from "./productAnalyticsTypes";
import { MetricValueView } from "./MetricValueView";

const base: MetricValue = { denominator: null, expected_days: 31, is_partial: false, null_reason: null, numerator: null, observed_days: 31, source_completeness: "complete", value: 12, value_state: "observed" };

describe("MetricValueView", () => {
  it("distinguishes observed zero from missing and undefined", () => {
    const { rerender } = render(<MetricValueView kind="units" metric={{ ...base, value: 0, value_state: "zero" }} />);
    expect(screen.getByText("0")).toBeVisible(); expect(screen.getByText("已观测为零")).toBeVisible();
    rerender(<MetricValueView kind="units" metric={{ ...base, observed_days: 0, value: null, value_state: "missing_report", null_reason: "no_observed_reports" }} />);
    expect(screen.getByText("无报表")).toBeVisible();
    rerender(<MetricValueView kind="conversion" metric={{ ...base, denominator: 0, value: null, value_state: "undefined_denominator", null_reason: "undefined_denominator" }} />);
    expect(screen.getByText("分母为 0")).toBeVisible();
  });

  it("formats exact decimal strings and announces partial data", () => {
    render(<MetricValueView kind="sales" metric={{ ...base, is_partial: true, source_completeness: "partial", value: "1234.50" }} />);
    expect(screen.getByText("1,234.50")).toBeVisible(); expect(screen.getByText("部分数据")).toBeVisible();
  });
});
