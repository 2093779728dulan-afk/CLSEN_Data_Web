import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { ApiRequestError } from "../../api/client";
import type { StyleLedgerResponse } from "./productAnalyticsTypes";

vi.mock("../catalog/CatalogSetup", () => ({ CatalogSetup: () => <div>商品分析准备状态</div> }));
const loadStyleLedger = vi.fn();
vi.mock("./productAnalyticsApi", () => ({ loadStyleLedger: (...args: unknown[]): Promise<StyleLedgerResponse> => loadStyleLedger(...args) as Promise<StyleLedgerResponse> }));
vi.mock("../../app/AuthzGenerationContext", () => ({ useAuthzGeneration: () => ({ generation: 0 }) }));
import { ProductLedgerPage } from "./ProductLedgerPage";

const metric = { denominator: null, expected_days: 31, is_partial: false, null_reason: null, numerator: null, observed_days: 31, source_completeness: "complete" as const, value: 2, value_state: "observed" as const };
const response = {
  coverage: { scope: "site", business: { confirmed_distinct_rows: 1, coverage_from: "2026-07-25", coverage_to: "2026-08-24", dedup_decision_rate: "1.000000", dedup_status: "complete", duplicate_of_rows: 0, eligible_rows: 1, excluded_rows: 0, expected_days: 31, identity_decision_rate: "1.000000", identity_status: "complete", mapped_rows: 1, mapping_rate: "1.000000", missing_days: 0, published_days: 31, report_coverage_rate: "1.000000", report_type: "business_report", unique_rows: 1, unmatched_rows: 0, unresolved_rows: 0 }, returns: {} },
  direction: "desc", page: 1, page_size: 50, permissions: {}, provenance: { catalog_version: 7, catalog_version_id: "7", consistent_as_of: "2026-08-24T10:00:00Z", fact_basis: "current", identity_source: "p0_catalog", identity_version_id: "7", reporting_timezone: "Asia/Shanghai" },
  reconciliation: { scope: "site", metric_status: {}, source_totals: {}, mapped_totals: {}, unmatched_totals: {}, excluded_totals: {}, duplicate_totals: {}, unresolved_duplicate_totals: {} },
  rows: [{ color_count: 2, latest_report_date: "2026-08-24", metrics: { units: metric, sales: { ...metric, value: "20.00" }, returns: metric, sessions: metric, conversion: { ...metric, value: "1.000000" } }, size_count: 3, sku_count: 4, source_title_count: 2, standard_name: "标准外套", status: "enabled", style_code: "ST-1", style_id: "101" }], sort: "units", total_rows: 1,
} as unknown as StyleLedgerResponse;
(response.coverage.returns as unknown) = { ...response.coverage.business, report_type: "return_report" };
for (const key of ["source_totals", "mapped_totals", "unmatched_totals", "excluded_totals", "duplicate_totals", "unresolved_duplicate_totals"] as const) (response.reconciliation[key] as unknown) = { conversion_denominator: 2, conversion_numerator: 2, returns: 2, sales: "20.00", sessions: 2, units: 2 };
(response.reconciliation.metric_status as unknown) = { conversion: "evaluable", returns: "evaluable", sales: "evaluable", sessions: "evaluable", units: "evaluable" };

describe("ProductLedgerPage", () => {
  it("guides an uninitialized site instead of offering a futile retry", async () => {
    loadStyleLedger.mockRejectedValue(new ApiRequestError(409, "analytics_source_scope_required", "detail"));
    render(<MemoryRouter><ProductLedgerPage today="2026-09-22" /></MemoryRouter>);
    expect(await screen.findByRole("link", { name: "查看初始化与处理步骤" })).toHaveAttribute("href", "/catalog");
    expect(screen.queryByRole("button", { name: "按原条件重试" })).not.toBeInTheDocument();
    expect(loadStyleLedger).toHaveBeenCalledTimes(1);
  });
  it("distinguishes a report-free date range from zero sales", async () => {
    loadStyleLedger.mockResolvedValue({ ...response, rows: [], total_rows: 0, coverage: { ...response.coverage, business: { ...response.coverage.business, published_days: 0 }, returns: { ...response.coverage.returns, published_days: 0 } } });
    render(<MemoryRouter><ProductLedgerPage today="2026-09-22" /></MemoryRouter>);
    expect(await screen.findByText("所选日期没有已发布报表")).toBeVisible();
    expect(screen.getByText(/缺失数据不代表销量为零/)).toBeVisible();
  });
  beforeEach(() => { loadStyleLedger.mockReset().mockResolvedValue(response); });
  it("loads only the stable-style endpoint adapter and renders standard identity", async () => {
    render(<MemoryRouter initialEntries={["/products?unknown=1"]}><ProductLedgerPage today="2026-08-24" /></MemoryRouter>);
    const trigger = await screen.findByRole("button", { name: "查看款号 ST-1 商品信息" });
    expect(screen.queryByText("标准外套")).not.toBeInTheDocument();
    fireEvent.click(trigger);
    expect(screen.getByRole("dialog")).toBeVisible();
    expect(screen.getByText("标准外套")).toBeVisible();
    expect(screen.getByRole("link", { name: "进入款式详情" })).toHaveAttribute("href", expect.stringContaining("/products/101"));
    fireEvent.click(screen.getByRole("button", { name: "关闭商品信息" }));
    await waitFor(() => expect(screen.queryByRole("dialog")).not.toBeInTheDocument());
    await waitFor(() => expect(trigger).toHaveFocus());
    fireEvent.click(screen.getByRole("checkbox", { name: "显示商品名称" }));
    expect(screen.getAllByText("标准外套")[0]).toBeVisible();
    expect(loadStyleLedger).toHaveBeenCalledTimes(1);
  });
  it("keeps the same table mounted during sorting and replaces results when ready", async () => {
    let complete!: (value: StyleLedgerResponse) => void;
    loadStyleLedger.mockResolvedValueOnce(response).mockImplementationOnce(() => new Promise((resolve) => { complete = resolve; }));
    render(<MemoryRouter initialEntries={["/products"]}><ProductLedgerPage today="2026-08-24" /></MemoryRouter>);
    const trigger = await screen.findByRole("button", { name: "查看款号 ST-1 商品信息" });
    const table = trigger.closest("table");
    fireEvent.click(screen.getByRole("button", { name: "销售贡献" }));
    expect(screen.getByRole("button", { name: "查看款号 ST-1 商品信息" }).closest("table")).toBe(table);
    expect(table).toHaveAttribute("aria-busy", "true");
    expect(screen.queryByRole("region", { name: "正在读取产品总表" })).not.toBeInTheDocument();
    complete({ ...response, sort: "sales" });
    await waitFor(() => expect(table).toHaveAttribute("aria-busy", "false"));
    expect(loadStyleLedger).toHaveBeenCalledTimes(2);
  });
  it("removes stale rows if sorting fails instead of presenting them as current", async () => {
    let fail!: (error: Error) => void;
    loadStyleLedger.mockResolvedValueOnce(response).mockImplementationOnce(() => new Promise((_resolve, reject) => { fail = reject; }));
    render(<MemoryRouter initialEntries={["/products"]}><ProductLedgerPage today="2026-08-24" /></MemoryRouter>);
    await screen.findByRole("button", { name: "查看款号 ST-1 商品信息" });
    fireEvent.click(screen.getByRole("button", { name: "退货关注" }));
    fail(new Error("offline"));
    await screen.findByText("产品总表读取失败");
    expect(screen.queryByRole("button", { name: "查看款号 ST-1 商品信息" })).not.toBeInTheDocument();
  });
  it("opens metric definitions without sorting and restores focus on close", async () => {
    render(<MemoryRouter initialEntries={["/products?from=2026-07-01&to=2026-07-31&return_basis=event_date"]}><ProductLedgerPage today="2026-08-24" /></MemoryRouter>);
    const help = await screen.findByRole("button", { name: "销售额与占比说明" });
    fireEvent.click(help);
    expect(screen.getByRole("dialog", { name: "销售额与占比" })).toBeVisible();
    expect(screen.getByText(/分母在分页前计算/)).toBeVisible();
    expect(loadStyleLedger).toHaveBeenCalledTimes(1);
    fireEvent.click(screen.getByRole("button", { name: "关闭指标说明" }));
    await waitFor(() => expect(help).toHaveFocus());
    fireEvent.click(screen.getByRole("button", { name: "本期退货量与同期退销比说明" }));
    expect(screen.getByText(/退货按事件日期筛选/)).toBeVisible();
    expect(screen.getByText(/不是订单退货率/)).toBeVisible();
  });
  it("sorts by clicking headers and highlights only the returned ordering", async () => {
    loadStyleLedger.mockImplementation((query: { sort: string; direction: string } = { sort: "units", direction: "desc" }) => Promise.resolve({ ...response, sort: query.sort, direction: query.direction }));
    render(<MemoryRouter initialEntries={["/products"]}><ProductLedgerPage today="2026-08-24" /></MemoryRouter>);
    await screen.findByRole("button", { name: "查看款号 ST-1 商品信息" });
    fireEvent.click(screen.getByRole("button", { name: "款号" }));
    await waitFor(() => expect(screen.getByRole("button", { name: "款号" }).closest("th")).toHaveAttribute("aria-sort", "ascending"));
    expect(loadStyleLedger.mock.calls.at(-1)?.[0]).toMatchObject({ sort: "style_code", direction: "asc" });
    fireEvent.click(screen.getByRole("button", { name: "款号" }));
    await waitFor(() => expect(screen.getByRole("button", { name: "款号" }).closest("th")).toHaveAttribute("aria-sort", "descending"));
    fireEvent.click(screen.getByRole("button", { name: "销售额 US$" }));
    await waitFor(() => expect(screen.getByRole("button", { name: "销售额 US$" }).closest("th")).toHaveAttribute("aria-sort", "descending"));
    expect(screen.getByRole("button", { name: "款号" }).closest("th")).toHaveAttribute("aria-sort", "none");
  });
  it("hides previous data immediately while a new key is loading", async () => {
    let resolveSecond!: (value: StyleLedgerResponse) => void;
    loadStyleLedger.mockResolvedValueOnce(response).mockImplementationOnce(() => new Promise((resolve) => { resolveSecond = resolve; }));
    render(<MemoryRouter initialEntries={["/products"]}><ProductLedgerPage today="2026-08-24" /></MemoryRouter>);
    expect(await screen.findByRole("button", { name: "查看款号 ST-1 商品信息" })).toBeVisible();
    fireEvent.change(screen.getByPlaceholderText("输入款号或标准名称"), { target: { value: "next" } });
    fireEvent.click(screen.getByRole("button", { name: "应用筛选" }));
    await waitFor(() => expect(screen.queryByRole("button", { name: "查看款号 ST-1 商品信息" })).not.toBeInTheDocument());
    resolveSecond(response);
    expect(await screen.findByRole("button", { name: "查看款号 ST-1 商品信息" })).toBeVisible();
  });
});

it("restores focus to the returned style after its list data has loaded", async () => {
  loadStyleLedger.mockResolvedValue(response);
  render(<MemoryRouter initialEntries={[{ pathname: "/products", search: "?search=ST-1", state: { restoreFocus: "style-101" } }]}><ProductLedgerPage today="2026-08-24" /></MemoryRouter>);
  const link = await screen.findByRole("button", { name: "查看款号 ST-1 商品信息" });
  await waitFor(() => expect(link).toHaveFocus());
});
