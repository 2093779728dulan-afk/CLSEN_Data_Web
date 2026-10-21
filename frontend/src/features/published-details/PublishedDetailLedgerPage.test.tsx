import { act, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { useLayoutEffect } from "react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { MemoryRouter, Route, Routes, useLocation, useNavigate } from "react-router-dom";

import type { Principal } from "../../api/types";
import type { PublishedRowsResponse, PublishedSummaryResponse } from "./publishedDetailsTypes";
import * as api from "./publishedDetailsApi";
import { PublishedDetailLedgerPage } from "./PublishedDetailLedgerPage";

vi.mock("./publishedDetailsApi", () => ({
  isPublicationScopeChangedError: vi.fn((error: unknown) => (
    typeof error === "object" && error !== null && "code" in error
    && (error as { code?: string }).code === "publication_scope_changed"
  )),
  loadPublishedRange: vi.fn(),
  loadPublishedRows: vi.fn(),
  loadPublishedSummaries: vi.fn(),
  publishedCsvUrl: vi.fn((query: { scopeToken: string }) => `/api/published-details/export.csv?scope_token=${query.scopeToken}`),
}));

const viewer: Principal = {
  display_name: "查看人员",
  id: 7,
  roles: ["viewer"],
  username: "viewer",
};

function summaryItem(reportDate: string, overrides: Partial<PublishedSummaryResponse["summaries"][number]> = {}) {
  return {
    matching_row_count: 12,
    metric_scope: "full_day" as const,
    publication: {
      dataset_id: Number(reportDate.slice(-2)),
      published_at: `${reportDate}T08:30:00Z`,
      report_date: reportDate,
      report_type: "business_report" as const,
      site_id: 1,
      version_id: Number(reportDate.slice(-2)) + 100,
    },
    published_at: `${reportDate}T08:30:00Z`,
    report_date: reportDate,
    return_quantity: null,
    sales: "1200.50",
    sessions: 300,
    total_row_count: 80,
    units_ordered: 24,
    version_id: Number(reportDate.slice(-2)) + 100,
    version_no: 3,
    ...overrides,
  };
}

function summaryResponse(
  from = "2026-07-16",
  to = "2026-08-14",
  summaries = [summaryItem("2026-08-14")],
): PublishedSummaryResponse {
  return {
    pagination: { page: 1, page_size: 25, total_items: summaries.length, total_pages: 1 },
    permissions: { can_export: false },
    publications: [],
    range: { from_date: from, to_date: to },
    scope_token: "scope-one",
    summaries,
  };
}

function rowsResponse(reportDate = "2026-08-14"): PublishedRowsResponse {
  return {
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
    range: { from_date: "2026-07-16", to_date: "2026-08-14" },
    rows: [{
      cells: [{ column_id: "8e4555a0-5397-4b36-b165-0af347ba05b9", value: "2401-WHITE-S" }],
      published_at: `${reportDate}T08:30:00Z`,
      report_date: reportDate,
      row_ordinal: 1,
      version_id: 114,
      version_no: 3,
    }],
    scope_token: "scope-one",
  };
}

type Deferred<T> = {
  promise: Promise<T>;
  reject: (reason?: unknown) => void;
  resolve: (value: T) => void;
};

function deferred<T>(): Deferred<T> {
  let resolve!: (value: T) => void;
  let reject!: (reason?: unknown) => void;
  const promise = new Promise<T>((resolvePromise, rejectPromise) => {
    resolve = resolvePromise;
    reject = rejectPromise;
  });
  return { promise, reject, resolve };
}

function immediateDeferred<T>(): Deferred<T> {
  let fulfilled: ((value: T) => unknown) | undefined;
  let rejected: ((reason: unknown) => unknown) | undefined;
  let finished: (() => unknown) | undefined;
  const finallyChain = {
    finally(callback: () => unknown) {
      finished = callback;
      return Promise.resolve();
    },
  };
  const catchChain = {
    catch(callback: (reason: unknown) => unknown) {
      rejected = callback;
      return finallyChain;
    },
  };
  const promise = {
    then(callback: (value: T) => unknown) {
      fulfilled = callback;
      return catchChain;
    },
  } as unknown as Promise<T>;
  return {
    promise,
    reject(reason?: unknown) {
      try {
        rejected?.(reason);
      } finally {
        finished?.();
      }
    },
    resolve(value: T) {
      try {
        fulfilled?.(value);
      } catch (error) {
        rejected?.(error);
      } finally {
        finished?.();
      }
    },
  };
}

let onLocationLayout: ((search: string) => void) | undefined;

function LocationProbe() {
  const location = useLocation();
  const navigate = useNavigate();
  useLayoutEffect(() => {
    onLocationLayout?.(location.search);
  }, [location.search]);
  return <div>
    <output aria-label="当前地址参数">{location.search}</output>
    <button onClick={() => void navigate(-1)} type="button">返回上一地址</button>
    <button onClick={() => void navigate(1)} type="button">前往下一地址</button>
  </div>;
}

function renderPage(initialEntry: string | { entries: string[]; index: number } = "/ledger/published-details") {
  const entries = typeof initialEntry === "string" ? [initialEntry] : initialEntry.entries;
  const initialIndex = typeof initialEntry === "string" ? 0 : initialEntry.index;
  return render(
    <MemoryRouter initialEntries={entries} initialIndex={initialIndex}>
      <Routes>
        <Route
          element={<><PublishedDetailLedgerPage
            principal={viewer}
            reportingTimezone="Asia/Shanghai"
            siteId={1}
            today="2026-08-14"
          /><LocationProbe /></>}
          path="/ledger/published-details"
        />
      </Routes>
    </MemoryRouter>,
  );
}

beforeEach(() => {
  onLocationLayout = undefined;
  vi.clearAllMocks();
  vi.mocked(api.loadPublishedRange).mockResolvedValue({
    from_date: "2026-07-01",
    to_date: "2026-08-14",
  });
  vi.mocked(api.loadPublishedRows).mockResolvedValue(rowsResponse());
  vi.mocked(api.loadPublishedSummaries).mockImplementation((query) => (
    Promise.resolve(summaryResponse(query.from, query.to))
  ));
});

describe("PublishedDetailLedgerPage", () => {
  it("loads the default range, restores search, owns the token, and expands with inherited scope", async () => {
    const user = userEvent.setup();
    renderPage("/ledger/published-details?search=2401");

    expect(await screen.findByText("经营明细")).toHaveAttribute("aria-selected", "true");
    expect(screen.getByText("12 / 80 行")).toBeVisible();
    expect(screen.getByText(/销售额.*全日/)).toBeVisible();
    expect(api.loadPublishedSummaries).toHaveBeenCalledWith(expect.objectContaining({
      from: "2026-07-16",
      page: 1,
      reportType: "business_report",
      search: "2401",
      to: "2026-08-14",
    }), expect.any(AbortSignal));

    await user.click(screen.getByRole("button", { name: "展开 2026-08-14 明细" }));
    await waitFor(() => expect(api.loadPublishedRows).toHaveBeenCalledWith(expect.objectContaining({
      from: "2026-07-16",
      reportDate: "2026-08-14",
      reportType: "business_report",
      scopeToken: "scope-one",
      search: "2401",
      to: "2026-08-14",
    }), expect.any(AbortSignal)));
    expect(await screen.findByText("2401-WHITE-S")).toBeVisible();
    expect(screen.getByLabelText("当前地址参数")).toHaveTextContent("from=2026-07-16");
    expect(screen.getByLabelText("当前地址参数")).not.toHaveTextContent("scope_token");
  });

  it("mounts the all-row read-only grid and keeps server sort and page state in the URL", async () => {
    const user = userEvent.setup();
    vi.mocked(api.loadPublishedRows).mockImplementation((query) => Promise.resolve({
      ...rowsResponse(),
      pagination: { page: query.page ?? 1, page_size: 25, total_items: 76, total_pages: 4 },
      permissions: { can_export: true },
    }));
    renderPage(`/ledger/published-details?from=2026-07-16&to=2026-08-14&mode=rows&sort_column_id=8e4555a0-5397-4b36-b165-0af347ba05b9&page=2`);

    expect(await screen.findByRole("table", { name: "经营报告已发布原始明细" })).toBeVisible();
    expect(api.loadPublishedRows).toHaveBeenCalledWith(expect.objectContaining({
      direction: "asc",
      page: 2,
      scopeToken: undefined,
      sortColumnId: "8e4555a0-5397-4b36-b165-0af347ba05b9",
    }), expect.any(AbortSignal));
    expect(api.loadPublishedSummaries).not.toHaveBeenCalled();
    expect(await screen.findByRole("link", { name: "导出 CSV" })).toHaveAttribute("download");

    await user.click(screen.getByRole("button", { name: "按 Seller SKU 排序" }));
    await waitFor(() => expect(screen.getByLabelText("当前地址参数")).toHaveTextContent("direction=desc"));
    await waitFor(() => expect(api.loadPublishedRows).toHaveBeenLastCalledWith(expect.objectContaining({
      direction: "desc",
      page: 1,
      scopeToken: "scope-one",
    }), expect.any(AbortSignal)));
    expect(screen.getByLabelText("当前地址参数")).not.toHaveTextContent("page=2");
  });

  it("keeps the summary page and expanded date when sorting the expanded grid", async () => {
    const user = userEvent.setup();
    vi.mocked(api.loadPublishedSummaries).mockImplementation((query) => Promise.resolve({
      ...summaryResponse(query.from, query.to, [summaryItem("2026-08-13")]),
      pagination: { page: query.page ?? 1, page_size: 25, total_items: 30, total_pages: 2 },
    }));
    vi.mocked(api.loadPublishedRows).mockImplementation((query) => Promise.resolve(rowsResponse(query.reportDate)));
    renderPage("/ledger/published-details?from=2026-07-16&to=2026-08-14&page=2");

    expect(await screen.findByText("2026-08-13")).toBeVisible();
    await user.click(screen.getByRole("button", { name: "展开 2026-08-13 明细" }));
    expect(await screen.findByRole("table", { name: "2026-08-13 已发布原始明细" })).toBeVisible();
    await user.click(screen.getByRole("button", { name: "按 Seller SKU 排序" }));

    await waitFor(() => expect(api.loadPublishedRows).toHaveBeenLastCalledWith(expect.objectContaining({
      direction: "asc",
      page: 1,
      reportDate: "2026-08-13",
      scopeToken: "scope-one",
      sortColumnId: "8e4555a0-5397-4b36-b165-0af347ba05b9",
    }), expect.any(AbortSignal)));
    expect(api.loadPublishedSummaries).toHaveBeenCalledTimes(1);
    expect(screen.getByRole("region", { name: "2026-08-13 展开明细" })).toBeVisible();
    const currentAddress = screen.getByLabelText("当前地址参数");
    expect(currentAddress).toHaveTextContent("page=2");
    expect(currentAddress).toHaveTextContent("report_date=2026-08-13");
    expect(currentAddress).toHaveTextContent("sort_column_id=8e4555a0-5397-4b36-b165-0af347ba05b9");
    expect(currentAddress).not.toHaveTextContent("mode=rows");
  });

  it("retries an all-row publication conflict once with a fresh token owner", async () => {
    vi.mocked(api.loadPublishedRows)
      .mockRejectedValueOnce({ code: "publication_scope_changed" })
      .mockResolvedValueOnce(rowsResponse());
    renderPage("/ledger/published-details?from=2026-07-16&to=2026-08-14&mode=rows&page=3");

    expect(await screen.findByText("发布数据已更新，正在重新读取")).toBeVisible();
    await waitFor(() => expect(api.loadPublishedRows).toHaveBeenCalledTimes(2));
    expect(vi.mocked(api.loadPublishedRows).mock.calls[1]?.[0]).toEqual(expect.objectContaining({
      page: 1,
      scopeToken: undefined,
    }));
    expect(await screen.findByText("2401-WHITE-S")).toBeVisible();
    expect(screen.getByLabelText("当前地址参数")).not.toHaveTextContent("page=3");
  });

  it("ignores stale all-row success after a new URL search owner renders", async () => {
    const stale = immediateDeferred<PublishedRowsResponse>();
    const fresh = deferred<PublishedRowsResponse>();
    vi.mocked(api.loadPublishedRows)
      .mockReturnValueOnce(stale.promise)
      .mockReturnValueOnce(fresh.promise);
    const user = userEvent.setup();
    renderPage("/ledger/published-details?from=2026-07-16&to=2026-08-14&mode=rows&search=old");
    await waitFor(() => expect(api.loadPublishedRows).toHaveBeenCalledTimes(1));

    onLocationLayout = (search) => {
      if (!search.includes("search=new")) return;
      onLocationLayout = undefined;
      stale.resolve({
        ...rowsResponse("2026-01-31"),
        range: { from_date: "2026-01-01", to_date: "2026-01-31" },
        scope_token: "stale-scope",
      });
    };
    const search = screen.getByLabelText("搜索已发布原始字段和报告日期");
    await user.clear(search);
    await user.type(search, "new");
    await user.click(screen.getByRole("button", { name: "搜索" }));

    await waitFor(() => expect(api.loadPublishedRows).toHaveBeenCalledTimes(2));
    expect(screen.getByLabelText("当前地址参数")).toHaveTextContent("search=new");
    expect(screen.getByLabelText("当前地址参数")).not.toHaveTextContent("2026-01-01");
    expect(screen.queryByText("2026-01-31")).not.toBeInTheDocument();

    await act(() => {
      fresh.resolve(rowsResponse("2026-08-13"));
      return fresh.promise;
    });
    expect(await screen.findByText("2026-08-13")).toBeVisible();
  });

  it("restores custom URL state and applies report, date, and normalized search controls", async () => {
    const user = userEvent.setup();
    vi.mocked(api.loadPublishedSummaries).mockImplementation((query) => (
      Promise.resolve(summaryResponse(query.from, query.to, [summaryItem(query.to, {
        publication: { ...summaryItem(query.to).publication, report_type: query.reportType },
      })]))
    ));
    renderPage("/ledger/published-details?report_type=return_report&from=2026-08-01&to=2026-08-10&search=old&page=2");

    expect(await screen.findByText("退货明细")).toHaveAttribute("aria-selected", "true");
    expect(screen.getByLabelText("开始日期")).toHaveValue("2026-08-01");
    expect(screen.getByLabelText("结束日期")).toHaveValue("2026-08-10");
    expect(screen.getByLabelText("搜索已发布原始字段和报告日期")).toHaveValue("old");

    await user.click(screen.getByRole("tab", { name: "经营明细" }));
    await waitFor(() => expect(api.loadPublishedSummaries).toHaveBeenLastCalledWith(
      expect.objectContaining({ page: 1, reportType: "business_report" }),
      expect.any(AbortSignal),
    ));

    await user.clear(screen.getByLabelText("开始日期"));
    await user.type(screen.getByLabelText("开始日期"), "2026-08-05");
    await user.clear(screen.getByLabelText("结束日期"));
    await user.type(screen.getByLabelText("结束日期"), "2026-08-12");
    await user.click(screen.getByRole("button", { name: "应用日期范围" }));
    await waitFor(() => expect(api.loadPublishedSummaries).toHaveBeenLastCalledWith(
      expect.objectContaining({ from: "2026-08-05", page: 1, to: "2026-08-12" }),
      expect.any(AbortSignal),
    ));

    const search = screen.getByLabelText("搜索已发布原始字段和报告日期");
    await user.clear(search);
    await user.type(search, " 2401 ");
    await user.click(screen.getByRole("button", { name: "搜索" }));
    await waitFor(() => expect(api.loadPublishedSummaries).toHaveBeenLastCalledWith(
      expect.objectContaining({ page: 1, search: " 2401 " }),
      expect.any(AbortSignal),
    ));
    expect(search).toHaveAttribute("maxLength", "200");
  });

  it("uses the successful server range as canonical and does not loop", async () => {
    vi.mocked(api.loadPublishedSummaries)
      .mockResolvedValueOnce(summaryResponse("2026-08-01", "2026-08-10", [summaryItem("2026-08-10")]))
      .mockResolvedValueOnce(summaryResponse("2026-08-01", "2026-08-10", [summaryItem("2026-08-10")]));
    renderPage("/ledger/published-details?from=2026-07-01&to=2026-08-14&page=4");

    expect(await screen.findByText("2026-08-10")).toBeVisible();
    await waitFor(() => expect(api.loadPublishedSummaries).toHaveBeenCalledTimes(2));
    expect(screen.getByLabelText("当前地址参数")).toHaveTextContent("from=2026-08-01");
    expect(screen.getByLabelText("当前地址参数")).toHaveTextContent("to=2026-08-10");
    expect(screen.getByLabelText("当前地址参数")).not.toHaveTextContent("page=4");
    await new Promise((resolve) => window.setTimeout(resolve, 0));
    expect(api.loadPublishedSummaries).toHaveBeenCalledTimes(2);
  });

  it("resolves all-published first and exposes an explicit empty result", async () => {
    const user = userEvent.setup();
    renderPage();
    await screen.findByText("2026-08-14");

    await user.click(screen.getByRole("button", { name: "全部已发布" }));
    await waitFor(() => expect(api.loadPublishedRange).toHaveBeenCalledWith(
      "business_report",
      expect.any(AbortSignal),
    ));
    await waitFor(() => expect(api.loadPublishedSummaries).toHaveBeenLastCalledWith(
      expect.objectContaining({ from: "2026-07-01", to: "2026-08-14" }),
      expect.any(AbortSignal),
    ));
    expect(vi.mocked(api.loadPublishedRange).mock.invocationCallOrder[0]).toBeLessThan(
      vi.mocked(api.loadPublishedSummaries).mock.invocationCallOrder.at(-1) ?? 0,
    );

    vi.mocked(api.loadPublishedRange).mockResolvedValueOnce({ from_date: null, to_date: null });
    const summaryCallCount = vi.mocked(api.loadPublishedSummaries).mock.calls.length;
    await user.click(screen.getByRole("button", { name: "全部已发布" }));
    expect(await screen.findByText("当前报表类型还没有任何已发布明细。")).toBeVisible();
    expect(api.loadPublishedSummaries).toHaveBeenCalledTimes(summaryCallCount);
  });

  it("shows an all-published empty state in rows mode without issuing another rows request", async () => {
    const user = userEvent.setup();
    vi.mocked(api.loadPublishedRange).mockResolvedValueOnce({ from_date: null, to_date: null });
    renderPage("/ledger/published-details?from=2026-07-16&to=2026-08-14&mode=rows");

    expect(await screen.findByRole("table", { name: "经营报告已发布原始明细" })).toBeVisible();
    vi.mocked(api.loadPublishedRows).mockClear();
    await user.click(screen.getByRole("button", { name: "全部已发布" }));

    expect(await screen.findByText("当前报表类型还没有任何已发布明细。")).toBeVisible();
    expect(api.loadPublishedRows).not.toHaveBeenCalled();
    expect(screen.queryByText("正在读取只读明细和列结构…")).not.toBeInTheDocument();
    expect(screen.queryByRole("table", { name: "经营报告已发布原始明细" })).not.toBeInTheDocument();
  });

  it("keeps ordinary failures in place, preserves URL filters, and retries", async () => {
    const user = userEvent.setup();
    vi.mocked(api.loadPublishedSummaries)
      .mockRejectedValueOnce(new Error("do not expose backend details"))
      .mockResolvedValueOnce(summaryResponse("2026-08-01", "2026-08-14"));
    renderPage("/ledger/published-details?from=2026-08-01&to=2026-08-14&search=2401");

    expect(await screen.findByRole("alert")).toHaveTextContent("无法读取已发布明细，请稍后重试。");
    expect(screen.queryByText(/do not expose/)).not.toBeInTheDocument();
    expect(screen.getByLabelText("当前地址参数")).toHaveTextContent("search=2401");
    await user.click(screen.getByRole("button", { name: "重新读取日期摘要" }));
    expect(await screen.findByText("12 / 80 行")).toBeVisible();
    expect(api.loadPublishedSummaries).toHaveBeenCalledTimes(2);
  });

  it("reloads exactly once on a publication conflict and stops a repeated conflict", async () => {
    const second = deferred<PublishedSummaryResponse>();
    const conflict = { code: "publication_scope_changed" };
    vi.mocked(api.loadPublishedSummaries)
      .mockRejectedValueOnce(conflict)
      .mockReturnValueOnce(second.promise);
    renderPage("/ledger/published-details?from=2026-08-01&to=2026-08-14&page=3");

    expect(await screen.findByText("发布数据已更新，正在重新读取")).toBeVisible();
    await waitFor(() => expect(api.loadPublishedSummaries).toHaveBeenCalledTimes(2));
    await waitFor(() => expect(screen.getByLabelText("当前地址参数")).not.toHaveTextContent("page=3"));
    await act(() => {
      second.resolve(summaryResponse("2026-08-01", "2026-08-14"));
      return second.promise;
    });
    expect(await screen.findByText("12 / 80 行")).toBeVisible();
    expect(api.loadPublishedSummaries).toHaveBeenCalledTimes(2);

    vi.mocked(api.loadPublishedSummaries)
      .mockRejectedValueOnce(conflict)
      .mockRejectedValueOnce(conflict);
    const user = userEvent.setup();
    await user.click(screen.getByRole("button", { name: "7 天" }));
    await waitFor(() => expect(api.loadPublishedSummaries).toHaveBeenCalledTimes(4));
    expect(await screen.findByRole("alert")).toHaveTextContent("自动重新读取未完成");
    await new Promise((resolve) => window.setTimeout(resolve, 0));
    expect(api.loadPublishedSummaries).toHaveBeenCalledTimes(4);
  });

  it("drops an expanded scope conflict and reloads the summary exactly once", async () => {
    const refreshed = deferred<PublishedSummaryResponse>();
    vi.mocked(api.loadPublishedSummaries)
      .mockResolvedValueOnce(summaryResponse())
      .mockReturnValueOnce(refreshed.promise);
    vi.mocked(api.loadPublishedRows).mockRejectedValueOnce({ code: "publication_scope_changed" });
    const user = userEvent.setup();
    renderPage();
    await screen.findByText("12 / 80 行");

    await user.click(screen.getByRole("button", { name: "展开 2026-08-14 明细" }));
    expect(await screen.findByText("发布数据已更新，正在重新读取")).toBeVisible();
    await waitFor(() => expect(api.loadPublishedSummaries).toHaveBeenCalledTimes(2));
    expect(api.loadPublishedRows).toHaveBeenCalledTimes(1);
    expect(screen.queryByRole("region", { name: "2026-08-14 展开明细" })).not.toBeInTheDocument();
    await waitFor(() => expect(screen.getByLabelText("当前地址参数")).not.toHaveTextContent("report_date"));

    await act(() => {
      refreshed.resolve(summaryResponse());
      return refreshed.promise;
    });
    expect(await screen.findByText("12 / 80 行")).toBeVisible();
    expect(api.loadPublishedSummaries).toHaveBeenCalledTimes(2);
  });

  it("allows only one expansion and aborts on switch, collapse, and unmount", async () => {
    const first = deferred<PublishedRowsResponse>();
    const second = deferred<PublishedRowsResponse>();
    vi.mocked(api.loadPublishedSummaries).mockResolvedValue(summaryResponse(
      "2026-07-16",
      "2026-08-14",
      [summaryItem("2026-08-14"), summaryItem("2026-08-13")],
    ));
    vi.mocked(api.loadPublishedRows)
      .mockReturnValueOnce(first.promise)
      .mockReturnValueOnce(second.promise);
    const user = userEvent.setup();
    const rendered = renderPage();
    await screen.findByText("2026-08-13");

    await user.click(screen.getByRole("button", { name: "展开 2026-08-14 明细" }));
    await waitFor(() => expect(api.loadPublishedRows).toHaveBeenCalledTimes(1));
    const firstSignal = vi.mocked(api.loadPublishedRows).mock.calls[0]?.[1] as AbortSignal;
    await user.click(screen.getByRole("button", { name: "展开 2026-08-13 明细" }));
    expect(firstSignal.aborted).toBe(true);
    expect(screen.queryByRole("region", { name: "2026-08-14 展开明细" })).not.toBeInTheDocument();
    await waitFor(() => expect(api.loadPublishedRows).toHaveBeenCalledTimes(2));
    const secondSignal = vi.mocked(api.loadPublishedRows).mock.calls[1]?.[1] as AbortSignal;
    await user.click(screen.getByRole("button", { name: "收起 2026-08-13 明细" }));
    expect(secondSignal.aborted).toBe(true);

    const third = deferred<PublishedRowsResponse>();
    vi.mocked(api.loadPublishedRows).mockReturnValueOnce(third.promise);
    await user.click(screen.getByRole("button", { name: "展开 2026-08-14 明细" }));
    await waitFor(() => expect(api.loadPublishedRows).toHaveBeenCalledTimes(3));
    const thirdSignal = vi.mocked(api.loadPublishedRows).mock.calls[2]?.[1] as AbortSignal;
    rendered.unmount();
    expect(thirdSignal.aborted).toBe(true);
  });

  it("keeps the viewer surface read-only and enables only real grid controls", async () => {
    const user = userEvent.setup();
    renderPage();
    await screen.findByText("12 / 80 行");

    expect(screen.queryByRole("button", { name: /^(上传|编辑|发布)$/ })).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: "列设置" })).toBeDisabled();
    expect(screen.getByRole("button", { name: "导出 CSV" })).toBeDisabled();
    expect(screen.getByText(/当前账号无导出权限.*列设置将在全部明细列结构加载后可用/)).toBeVisible();
    expect(screen.getByText(/查看人员.*只读/)).toBeVisible();

    await user.click(screen.getByRole("tab", { name: "全部明细" }));
    expect(await screen.findByRole("table", { name: "经营报告已发布原始明细" })).toBeVisible();
    expect(screen.getByRole("button", { name: "列设置" })).toBeEnabled();
    expect(screen.getByRole("button", { name: "导出 CSV" })).toBeDisabled();
    expect(screen.getByText("当前账号没有已发布明细导出权限。" )).toBeVisible();
    expect(screen.getByLabelText("当前地址参数")).toHaveTextContent("mode=rows");
  });

  it("ignores an old summary success after a search owner renders", async () => {
    const stale = immediateDeferred<PublishedSummaryResponse>();
    const fresh = deferred<PublishedSummaryResponse>();
    vi.mocked(api.loadPublishedSummaries)
      .mockReturnValueOnce(stale.promise)
      .mockReturnValueOnce(fresh.promise);
    const user = userEvent.setup();
    renderPage("/ledger/published-details?from=2026-08-01&to=2026-08-14&search=old");
    await waitFor(() => expect(api.loadPublishedSummaries).toHaveBeenCalledTimes(1));

    onLocationLayout = (search) => {
      if (!search.includes("search=new")) return;
      onLocationLayout = undefined;
      stale.resolve({
        ...summaryResponse("2026-01-01", "2026-01-31", [summaryItem("2026-01-31")]),
        scope_token: "stale-scope",
      });
    };
    const search = screen.getByLabelText("搜索已发布原始字段和报告日期");
    await user.clear(search);
    await user.type(search, "new");
    await user.click(screen.getByRole("button", { name: "搜索" }));

    await waitFor(() => expect(api.loadPublishedSummaries).toHaveBeenCalledTimes(2));
    expect(screen.getByLabelText("当前地址参数")).toHaveTextContent("search=new");
    expect(screen.getByLabelText("当前地址参数")).toHaveTextContent("from=2026-08-01");
    expect(screen.getByLabelText("当前地址参数")).not.toHaveTextContent("2026-01-01");
    expect(screen.queryByText("2026-01-31")).not.toBeInTheDocument();
    expect(vi.mocked(api.loadPublishedSummaries).mock.calls[1]?.[0].scopeToken).toBeUndefined();

    await act(() => {
      fresh.resolve({ ...summaryResponse("2026-08-01", "2026-08-14", [summaryItem("2026-08-13")]), scope_token: "fresh-scope" });
      return fresh.promise;
    });
    expect(await screen.findByText("2026-08-13")).toBeVisible();
  });

  it("ignores an old summary rejection after rows mode renders", async () => {
    const stale = immediateDeferred<PublishedSummaryResponse>();
    vi.mocked(api.loadPublishedSummaries).mockReturnValueOnce(stale.promise);
    const user = userEvent.setup();
    renderPage("/ledger/published-details?from=2026-08-01&to=2026-08-14");
    await waitFor(() => expect(api.loadPublishedSummaries).toHaveBeenCalledTimes(1));

    onLocationLayout = (search) => {
      if (!search.includes("mode=rows")) return;
      onLocationLayout = undefined;
      stale.reject(new Error("stale summary failure"));
    };
    await user.click(screen.getByRole("tab", { name: "全部明细" }));

    expect(await screen.findByRole("table", { name: "经营报告已发布原始明细" })).toBeVisible();
    expect(screen.queryByText("无法读取已发布明细，请稍后重试。")).not.toBeInTheDocument();
    expect(screen.getByLabelText("当前地址参数")).toHaveTextContent("mode=rows");
    expect(api.loadPublishedSummaries).toHaveBeenCalledTimes(1);
  });

  it("ignores an old summary conflict during browser history navigation", async () => {
    const stale = immediateDeferred<PublishedSummaryResponse>();
    const fresh = deferred<PublishedSummaryResponse>();
    vi.mocked(api.loadPublishedSummaries)
      .mockReturnValueOnce(stale.promise)
      .mockReturnValueOnce(fresh.promise);
    const user = userEvent.setup();
    renderPage({
      entries: [
        "/ledger/published-details?from=2026-08-01&to=2026-08-14&search=old",
        "/ledger/published-details?from=2026-08-01&to=2026-08-14&search=new",
      ],
      index: 1,
    });
    await waitFor(() => expect(api.loadPublishedSummaries).toHaveBeenCalledTimes(1));

    onLocationLayout = (search) => {
      if (!search.includes("search=old")) return;
      onLocationLayout = undefined;
      stale.reject({ code: "publication_scope_changed" });
    };
    await user.click(screen.getByRole("button", { name: "返回上一地址" }));

    await waitFor(() => expect(api.loadPublishedSummaries).toHaveBeenCalledTimes(2));
    expect(screen.queryByText("发布数据已更新，正在重新读取")).not.toBeInTheDocument();
    expect(screen.getByLabelText("当前地址参数")).toHaveTextContent("search=old");
    expect(api.loadPublishedSummaries).toHaveBeenCalledTimes(2);

    await act(() => {
      fresh.resolve(summaryResponse("2026-08-01", "2026-08-14"));
      return fresh.promise;
    });
  });

  it("ignores an old expansion success when history selects another date", async () => {
    const stale = immediateDeferred<PublishedRowsResponse>();
    const fresh = deferred<PublishedRowsResponse>();
    vi.mocked(api.loadPublishedSummaries).mockResolvedValue(summaryResponse(
      "2026-08-01",
      "2026-08-14",
      [summaryItem("2026-08-14"), summaryItem("2026-08-13")],
    ));
    vi.mocked(api.loadPublishedRows)
      .mockReturnValueOnce(stale.promise)
      .mockReturnValueOnce(fresh.promise);
    const user = userEvent.setup();
    renderPage({
      entries: [
        "/ledger/published-details?from=2026-08-01&to=2026-08-14&report_date=2026-08-13",
        "/ledger/published-details?from=2026-08-01&to=2026-08-14&report_date=2026-08-14",
      ],
      index: 1,
    });
    await waitFor(() => expect(api.loadPublishedRows).toHaveBeenCalledTimes(1));

    onLocationLayout = (search) => {
      if (!search.includes("report_date=2026-08-13")) return;
      onLocationLayout = undefined;
      stale.resolve({
        ...rowsResponse("2026-08-14"),
        range: { from_date: "2026-01-01", to_date: "2026-01-31" },
        scope_token: "stale-expansion-scope",
      });
    };
    await user.click(screen.getByRole("button", { name: "返回上一地址" }));

    await waitFor(() => expect(api.loadPublishedRows).toHaveBeenCalledTimes(2));
    expect(screen.getByLabelText("当前地址参数")).toHaveTextContent("report_date=2026-08-13");
    expect(screen.getByLabelText("当前地址参数")).toHaveTextContent("from=2026-08-01");
    expect(screen.getByLabelText("当前地址参数")).not.toHaveTextContent("2026-01-01");

    await act(() => {
      fresh.resolve({
        ...rowsResponse("2026-08-13"),
        range: { from_date: "2026-08-01", to_date: "2026-08-14" },
      });
      return fresh.promise;
    });
  });

  it("ignores old expansion rejection and conflict after history collapse or switch", async () => {
    const staleFailure = immediateDeferred<PublishedRowsResponse>();
    vi.mocked(api.loadPublishedSummaries).mockResolvedValue(summaryResponse(
      "2026-08-01",
      "2026-08-14",
    ));
    vi.mocked(api.loadPublishedRows).mockReturnValueOnce(staleFailure.promise);
    const user = userEvent.setup();
    const firstRender = renderPage({
      entries: [
        "/ledger/published-details?from=2026-08-01&to=2026-08-14",
        "/ledger/published-details?from=2026-08-01&to=2026-08-14&report_date=2026-08-14",
      ],
      index: 1,
    });
    await waitFor(() => expect(api.loadPublishedRows).toHaveBeenCalledTimes(1));
    onLocationLayout = (search) => {
      if (search.includes("report_date")) return;
      onLocationLayout = undefined;
      staleFailure.reject(new Error("stale expansion failure"));
    };
    await user.click(screen.getByRole("button", { name: "返回上一地址" }));
    expect(screen.queryByText("无法读取该日期的展开明细，请重试。")).not.toBeInTheDocument();
    expect(screen.getByLabelText("当前地址参数")).not.toHaveTextContent("report_date");
    firstRender.unmount();

    vi.clearAllMocks();
    const staleConflict = immediateDeferred<PublishedRowsResponse>();
    const fresh = deferred<PublishedRowsResponse>();
    vi.mocked(api.loadPublishedSummaries).mockResolvedValue(summaryResponse(
      "2026-08-01",
      "2026-08-14",
      [summaryItem("2026-08-14"), summaryItem("2026-08-13")],
    ));
    vi.mocked(api.loadPublishedRows)
      .mockReturnValueOnce(staleConflict.promise)
      .mockReturnValueOnce(fresh.promise);
    renderPage({
      entries: [
        "/ledger/published-details?from=2026-08-01&to=2026-08-14&report_date=2026-08-13",
        "/ledger/published-details?from=2026-08-01&to=2026-08-14&report_date=2026-08-14",
      ],
      index: 1,
    });
    await waitFor(() => expect(api.loadPublishedRows).toHaveBeenCalledTimes(1));
    onLocationLayout = (search) => {
      if (!search.includes("report_date=2026-08-13")) return;
      onLocationLayout = undefined;
      staleConflict.reject({ code: "publication_scope_changed" });
    };
    await user.click(screen.getByRole("button", { name: "返回上一地址" }));
    await waitFor(() => expect(api.loadPublishedRows).toHaveBeenCalledTimes(2));
    expect(screen.queryByText("发布数据已更新，正在重新读取")).not.toBeInTheDocument();
    expect(screen.getByLabelText("当前地址参数")).toHaveTextContent("report_date=2026-08-13");

    await act(() => {
      fresh.resolve({
        ...rowsResponse("2026-08-13"),
        range: { from_date: "2026-08-01", to_date: "2026-08-14" },
      });
      return fresh.promise;
    });
  });

  it("ignores an old all-published success after its history owner changes", async () => {
    const stale = immediateDeferred<{ from_date: string | null; to_date: string | null }>();
    vi.mocked(api.loadPublishedRange).mockReturnValueOnce(stale.promise);
    const user = userEvent.setup();
    renderPage({
      entries: [
        "/ledger/published-details?report_type=return_report&from=2026-08-01&to=2026-08-14",
        "/ledger/published-details?from=2026-08-01&to=2026-08-14",
      ],
      index: 1,
    });
    await screen.findByText("12 / 80 行");
    await user.click(screen.getByRole("button", { name: "全部已发布" }));
    await waitFor(() => expect(api.loadPublishedRange).toHaveBeenCalledTimes(1));
    onLocationLayout = (search) => {
      if (!search.includes("report_type=return_report")) return;
      onLocationLayout = undefined;
      stale.resolve({ from_date: "2026-01-01", to_date: "2026-01-31" });
    };
    await user.click(screen.getByRole("button", { name: "返回上一地址" }));

    expect(screen.getByLabelText("当前地址参数")).toHaveTextContent("report_type=return_report");
    expect(screen.getByLabelText("当前地址参数")).toHaveTextContent("from=2026-08-01");
    expect(screen.getByLabelText("当前地址参数")).not.toHaveTextContent("2026-01-01");
  });

  it("ignores an old all-published rejection after its history owner changes", async () => {
    const stale = immediateDeferred<{ from_date: string | null; to_date: string | null }>();
    vi.mocked(api.loadPublishedRange).mockReturnValueOnce(stale.promise);
    const user = userEvent.setup();
    renderPage({
      entries: [
        "/ledger/published-details?report_type=return_report&from=2026-08-01&to=2026-08-14",
        "/ledger/published-details?from=2026-08-01&to=2026-08-14",
      ],
      index: 1,
    });
    await screen.findByText("12 / 80 行");
    await user.click(screen.getByRole("button", { name: "全部已发布" }));
    await waitFor(() => expect(api.loadPublishedRange).toHaveBeenCalledTimes(1));
    onLocationLayout = (search) => {
      if (!search.includes("report_type=return_report")) return;
      onLocationLayout = undefined;
      stale.reject(new Error("stale range failure"));
    };
    await user.click(screen.getByRole("button", { name: "返回上一地址" }));
    expect(screen.queryByText("无法解析全部已发布日期范围，请重试。")).not.toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: "前往下一地址" }));
    expect(screen.queryByRole("button", { name: "重试全部已发布范围" })).not.toBeInTheDocument();
  });
});
