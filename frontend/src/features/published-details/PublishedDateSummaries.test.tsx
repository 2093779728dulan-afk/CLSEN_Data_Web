import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import { MemoryRouter } from "react-router-dom";

import type { PublishedRowsResponse, PublishedSummaryResponse } from "./publishedDetailsTypes";
import {
  PublishedDateSummaries,
  type PublishedDateExpansion,
} from "./PublishedDateSummaries";

const summaryResponse: PublishedSummaryResponse = {
  pagination: { page: 1, page_size: 25, total_items: 1, total_pages: 1 },
  permissions: { can_export: false },
  publications: [],
  range: { from_date: "2026-08-01", to_date: "2026-08-14" },
  scope_token: "scope-one",
  summaries: [{
    matching_row_count: 12,
    metric_scope: "full_day",
    publication: {
      dataset_id: 11,
      published_at: "2026-08-14T08:30:00Z",
      report_date: "2026-08-14",
      report_type: "business_report",
      site_id: 1,
      version_id: 31,
    },
    published_at: "2026-08-14T08:30:00Z",
    report_date: "2026-08-14",
    return_quantity: null,
    sales: "1234.50",
    sessions: 320,
    total_row_count: 80,
    units_ordered: 24,
    version_id: 31,
    version_no: 4,
  }],
};

const rowsResponse: PublishedRowsResponse = {
  columns: [{
    column_id: "8e4555a0-5397-4b36-b165-0af347ba05b9",
    display_order: 0,
    is_key: true,
    participates_in_statistics: false,
    source_header: "Seller SKU",
    standard_field_name: "seller_sku",
    value_kind: "text",
  }],
  pagination: { page: 1, page_size: 25, total_items: 1, total_pages: 1 },
  permissions: { can_export: false },
  publications: [],
  range: { from_date: "2026-08-01", to_date: "2026-08-14" },
  rows: [{
    cells: [{ column_id: "8e4555a0-5397-4b36-b165-0af347ba05b9", value: "2401-WHITE-S" }],
    published_at: "2026-08-14T08:30:00Z",
    report_date: "2026-08-14",
    row_ordinal: 7,
    version_id: 31,
    version_no: 4,
  }],
  scope_token: "scope-one",
};

function renderSummaries(options: {
  expandedDate?: string;
  expansion?: PublishedDateExpansion;
  response?: PublishedSummaryResponse;
} = {}) {
  const onPageChange = vi.fn();
  const onRetry = vi.fn();
  const onRetryExpansion = vi.fn();
  const onToggleExpanded = vi.fn();
  render(
    <MemoryRouter>
      <PublishedDateSummaries
        expandedDate={options.expandedDate}
        expansion={options.expansion}
        loading={false}
        onPageChange={onPageChange}
        onRetry={onRetry}
        onRetryExpansion={onRetryExpansion}
        onToggleExpanded={onToggleExpanded}
        reportType="business_report"
        reportingTimezone="Asia/Shanghai"
        response={options.response ?? summaryResponse}
      />
    </MemoryRouter>,
  );
  return { onPageChange, onRetry, onRetryExpansion, onToggleExpanded };
}

describe("PublishedDateSummaries", () => {
  it("renders dense full-day metrics, publication metadata, and required destinations", () => {
    renderSummaries();

    expect(screen.getByText("12 / 80 行")).toBeVisible();
    expect(screen.getByText(/销售额.*全日/)).toBeVisible();
    expect(screen.getByText(/订购数.*全日/)).toBeVisible();
    expect(screen.getByText(/会话数.*全日/)).toBeVisible();
    expect(screen.getByText(/当前发布 v4/)).toBeVisible();
    expect(screen.getByRole("link", { name: "打开 2026-08-14 日期工作台" })).toHaveAttribute(
      "href",
      "/published/2026-08-14?report_type=business_report",
    );
    expect(screen.getByRole("link", { name: "查看 2026-08-14 版本记录" })).toHaveAttribute(
      "href",
      "/versions?report_date=2026-08-14&report_type=business_report",
    );
  });

  it("exposes the expansion action and renders a local read-only row table", async () => {
    const user = userEvent.setup();
    const callbacks = renderSummaries({
      expandedDate: "2026-08-14",
      expansion: { date: "2026-08-14", response: rowsResponse, status: "ready" },
    });

    const toggle = screen.getByRole("button", { name: "收起 2026-08-14 明细" });
    expect(toggle).toHaveAttribute("aria-expanded", "true");
    expect(screen.getByRole("region", { name: "2026-08-14 展开明细" })).toBeVisible();
    expect(screen.getByRole("columnheader", { name: "Seller SKU" })).toBeVisible();
    expect(screen.getByText("2401-WHITE-S")).toBeVisible();

    await user.click(toggle);
    expect(callbacks.onToggleExpanded).toHaveBeenCalledWith("2026-08-14");
  });

  it("keeps expansion loading, empty, and retryable errors local to the selected date", async () => {
    const user = userEvent.setup();
    const { rerender } = render(
      <MemoryRouter>
        <PublishedDateSummaries
          expandedDate="2026-08-14"
          expansion={{ date: "2026-08-14", status: "loading" }}
          loading={false}
          onPageChange={vi.fn()}
          onRetry={vi.fn()}
          onRetryExpansion={vi.fn()}
          onToggleExpanded={vi.fn()}
          reportType="business_report"
          reportingTimezone="Asia/Shanghai"
          response={summaryResponse}
        />
      </MemoryRouter>,
    );
    expect(screen.getByText("正在读取 2026-08-14 的匹配明细…")).toBeVisible();

    const retry = vi.fn();
    rerender(
      <MemoryRouter>
        <PublishedDateSummaries
          expandedDate="2026-08-14"
          expansion={{ date: "2026-08-14", message: "无法读取该日期的展开明细。", status: "error" }}
          loading={false}
          onPageChange={vi.fn()}
          onRetry={vi.fn()}
          onRetryExpansion={retry}
          onToggleExpanded={vi.fn()}
          reportType="business_report"
          reportingTimezone="Asia/Shanghai"
          response={summaryResponse}
        />
      </MemoryRouter>,
    );
    await user.click(screen.getByRole("button", { name: "重试 2026-08-14 展开明细" }));
    expect(retry).toHaveBeenCalledWith("2026-08-14");

    rerender(
      <MemoryRouter>
        <PublishedDateSummaries
          expandedDate="2026-08-14"
          expansion={{
            date: "2026-08-14",
            response: { ...rowsResponse, rows: [], pagination: { ...rowsResponse.pagination, total_items: 0 } },
            status: "ready",
          }}
          loading={false}
          onPageChange={vi.fn()}
          onRetry={vi.fn()}
          onRetryExpansion={vi.fn()}
          onToggleExpanded={vi.fn()}
          reportType="business_report"
          reportingTimezone="Asia/Shanghai"
          response={summaryResponse}
        />
      </MemoryRouter>,
    );
    expect(screen.getByText("这个日期没有匹配当前搜索的明细行。")).toBeVisible();
  });

  it("renders reachable summary loading, empty, error, and pagination states", async () => {
    const user = userEvent.setup();
    const retry = vi.fn();
    const page = vi.fn();
    const { rerender } = render(
      <MemoryRouter>
        <PublishedDateSummaries
          loading
          onPageChange={page}
          onRetry={retry}
          onRetryExpansion={vi.fn()}
          onToggleExpanded={vi.fn()}
          reportType="business_report"
          reportingTimezone="Asia/Shanghai"
        />
      </MemoryRouter>,
    );
    expect(screen.getByRole("status", { name: "正在读取日期摘要" })).toBeVisible();

    rerender(
      <MemoryRouter>
        <PublishedDateSummaries
          error="无法读取已发布明细，请稍后重试。"
          loading={false}
          onPageChange={page}
          onRetry={retry}
          onRetryExpansion={vi.fn()}
          onToggleExpanded={vi.fn()}
          reportType="business_report"
          reportingTimezone="Asia/Shanghai"
        />
      </MemoryRouter>,
    );
    await user.click(screen.getByRole("button", { name: "重新读取日期摘要" }));
    expect(retry).toHaveBeenCalledTimes(1);

    rerender(
      <MemoryRouter>
        <PublishedDateSummaries
          loading={false}
          onPageChange={page}
          onRetry={retry}
          onRetryExpansion={vi.fn()}
          onToggleExpanded={vi.fn()}
          reportType="business_report"
          reportingTimezone="Asia/Shanghai"
          response={{
            ...summaryResponse,
            pagination: { page: 2, page_size: 25, total_items: 28, total_pages: 3 },
            summaries: [],
          }}
        />
      </MemoryRouter>,
    );
    expect(screen.getByText("所选范围内没有当前已发布明细。")).toBeVisible();
    await user.click(screen.getByRole("button", { name: "上一页" }));
    await user.click(screen.getByRole("button", { name: "下一页" }));
    expect(page).toHaveBeenNthCalledWith(1, 1);
    expect(page).toHaveBeenNthCalledWith(2, 3);
  });
});
