import { render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { describe, expect, it, vi } from "vitest";
import { ApiRequestError } from "../../api/client";
import { analyticsError } from "./analyticsError";
import { AnalyticsErrorState } from "./AnalyticsErrorState";

describe("product analytics recovery", () => {
  it.each(["analytics_source_scope_required", "analytics_catalog_required", "analytics_return_snapshot_required", "analytics_snapshot_stale", "style_analytics_unavailable"])("routes %s to setup without a futile retry", code => {
    const failure = analyticsError(new ApiRequestError(409, code, "private server text"), "读取失败");
    render(<MemoryRouter><AnalyticsErrorState failure={failure} title="失败" onRetry={vi.fn()} /></MemoryRouter>);
    expect(screen.getByRole("link", { name: "查看初始化与处理步骤" })).toHaveAttribute("href", "/catalog");
    expect(screen.queryByRole("button", { name: "按原条件重试" })).not.toBeInTheDocument();
    expect(screen.queryByText("private server text")).not.toBeInTheDocument();
  });
  it("does not call an unknown 409 a changed snapshot", () => {
    expect(analyticsError(new ApiRequestError(409, "unknown", "detail"), "读取失败").message).toBe("读取失败");
  });
  it("keeps network errors retryable", () => {
    expect(analyticsError(new Error("offline"), "读取失败").retry).toBe(true);
  });
  it("explains a snapshot link without a catalog record instead of blaming date filters", () => {
    const failure = analyticsError(new ApiRequestError(422, "analytics_catalog_version_required", "detail"), "读取失败");
    expect(failure.message).toContain("目录快照需要指定目录记录");
    expect(failure.retry).toBe(false);
    expect(failure.setup).toBe(false);
  });
  it("describes a snapshot range error without suggesting initialization", () => {
    const failure = analyticsError(new ApiRequestError(409, "catalog_snapshot_range_out_of_bounds", "detail"), "读取失败");
    expect(failure.message).toContain("超出目录快照覆盖范围");
    expect(failure.setup).toBe(false);
  });
});
