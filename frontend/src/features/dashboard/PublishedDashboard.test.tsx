import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";
import { MemoryRouter, Route, Routes } from "react-router-dom";

import type {
  DailyLedgerResponse,
  ProductCardResponse,
  ProductLedgerResponse,
} from "../../api/generated";
import type { Principal } from "../../api/types";
import { PublishedDashboard } from "./PublishedDashboard";

const daily: DailyLedgerResponse = {
  publications: [],
  range: { from_date: "2026-08-01", to_date: "2026-08-31" },
  rows: [{
    business_status: "published",
    conversion_rate: "0.1",
    counts_as_incomplete: true,
    overall_status: "partial",
    pending_summary: "退货报告缺失",
    reasons: [],
    report_date: "2026-08-10",
    return_quantity: null,
    return_status: "missing",
    sales: "120.25",
    sessions: 60,
    units_ordered: 6,
  }, {
    business_status: "published",
    conversion_rate: "0.08",
    counts_as_incomplete: false,
    overall_status: "complete",
    pending_summary: null,
    reasons: [],
    report_date: "2026-08-09",
    return_quantity: 2,
    return_status: "published",
    sales: "98.50",
    sessions: 50,
    units_ordered: 4,
  }],
  site_config_versions: [],
};

const products: ProductLedgerResponse = {
  direction: "desc",
  page: 1,
  page_size: 25,
  publications: [],
  range: daily.range,
  rows: [{
    color_count: 2,
    conversion_rate: "0.1",
    latest_published_date: "2026-08-10",
    name_status: "available",
    product_name: "基础款衬衫",
    published_days: 10,
    return_quantity: 1,
    row_kind: "product",
    sales: "120.25",
    sessions: 60,
    size_count: 3,
    style_code: "2301",
    unclassified_sku: null,
    units_ordered: 6,
    variant_count: 4,
  }, {
    color_count: 0,
    conversion_rate: null,
    latest_published_date: "2026-08-10",
    name_status: "missing",
    product_name: null,
    published_days: 1,
    return_quantity: 0,
    row_kind: "unclassified",
    sales: "1.00",
    sessions: 1,
    size_count: 0,
    style_code: null,
    unclassified_sku: "BAD-SKU",
    units_ordered: 1,
    variant_count: 1,
  }],
  site_config_versions: [],
  sort: "sales",
  total_rows: 2,
};

const productCard: ProductCardResponse = {
  latest_published_date: "2026-08-10",
  name_status: "available",
  product_name: "基础款衬衫",
  publications: [],
  range: daily.range,
  site_config_versions: [],
  style_code: "2301",
  summary: {
    conversion_rate: "0.1",
    published_days: 10,
    return_quantity: 1,
    sales: "120.25",
    sessions: 60,
    units_ordered: 6,
  },
  trend: [{
    conversion_rate: "0.1",
    report_date: "2026-08-10",
    return_quantity: 1,
    sales: "120.25",
    sessions: 60,
    units_ordered: 6,
  }],
  variants: [{
    asins: ["B0TEST2301"],
    color: "White",
    fnskus: ["XTEST2301"],
    product_name: "基础款衬衫 白色 S",
    seller_sku: "2301-White-S",
    size: "S",
  }],
};

const viewer: Principal = { display_name: "查看人员", id: 1, roles: ["viewer"], username: "viewer" };
const manager: Principal = { display_name: "数据人员", id: 2, roles: ["data_manager"], username: "manager" };

function response(body: unknown): Response {
  return { json: () => Promise.resolve(body), ok: true, status: 200 } as Response;
}

function requestPath(input: RequestInfo | URL): string {
  if (typeof input === "string") return input;
  if (input instanceof URL) return input.toString();
  return input.url;
}

function installApi() {
  const fetchMock = vi.fn((input: RequestInfo | URL) => {
    const path = requestPath(input);
    if (path.startsWith("/api/dashboard/daily-ledger")) return Promise.resolve(response(daily));
    if (path.startsWith("/api/dashboard/product-ledger")) return Promise.resolve(response(products));
    if (path.startsWith("/api/dashboard/product-card/2301")) return Promise.resolve(response(productCard));
    return Promise.reject(new Error(`Unexpected API request: ${path}`));
  });
  vi.stubGlobal("fetch", fetchMock);
  return fetchMock;
}

function renderDashboard(options?: { initialEntry?: string; principal?: Principal; productAnalyticsSource?: "legacy_parser" | "p0_catalog" }) {
  return render(
    <MemoryRouter initialEntries={[options?.initialEntry ?? "/?month=2026-08"]}>
      <Routes>
        <Route path="/" element={<PublishedDashboard principal={options?.principal ?? viewer} productAnalyticsSource={options?.productAnalyticsSource} />} />
        <Route path="/published/:date" element={<h1>已发布日期详情</h1>} />
        <Route path="/review/:date" element={<h1>审核日期详情</h1>} />
      </Routes>
    </MemoryRouter>,
  );
}

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("PublishedDashboard", () => {
  it("defaults to the current month's daily ledger", async () => {
    const fetchMock = installApi();
    renderDashboard();

    expect(await screen.findByText("2026-08-10")).toBeInTheDocument();
    expect(screen.getAllByText("部分发布")).toHaveLength(2);
    expect(screen.getByText("退货报告缺失")).toBeInTheDocument();
    expect(screen.getByText("1 个日期待补齐")).toBeInTheDocument();
    expect(screen.getByText("无需处理")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "发布明细" })).toHaveAttribute("href", "/ledger/published-details?from=2026-08-01&to=2026-08-31");
    await waitFor(() => expect(fetchMock).toHaveBeenCalled());
    expect(requestPath(fetchMock.mock.calls[0]?.[0] as RequestInfo)).toBe(
      "/api/dashboard/daily-ledger?from=2026-08-01&to=2026-08-31",
    );
  });

  it("sends viewers to the read-only published day", async () => {
    installApi();
    const user = userEvent.setup();
    renderDashboard();

    await user.click(await screen.findByText("2026-08-10"));
    expect(await screen.findByRole("heading", { name: "已发布日期详情" })).toBeInTheDocument();
  });

  it("sends data managers to the independent review day", async () => {
    installApi();
    const user = userEvent.setup();
    renderDashboard({ principal: manager });

    await user.click(await screen.findByText("2026-08-10"));
    expect(await screen.findByRole("heading", { name: "审核日期详情" })).toBeInTheDocument();
  });

  it("loads the product ledger and opens one product-level information card", async () => {
    const fetchMock = installApi();
    const user = userEvent.setup();
    renderDashboard();

    await user.click(screen.getByRole("tab", { name: "产品总表" }));
    expect(await screen.findByText("基础款衬衫")).toBeInTheDocument();
    await user.click(screen.getByRole("row", { name: "打开款号 2301 商品信息" }));

    expect(await screen.findByRole("heading", { name: "基础款衬衫", hidden: true })).toBeInTheDocument();
    expect(screen.getByText("峰值").parentElement).toHaveTextContent("US$120.25");
    expect(screen.getByText("最近发布 2026-08-10")).toBeInTheDocument();
    expect(screen.getByText("2301-White-S", { selector: "strong" })).toBeInTheDocument();
    expect(screen.getByText("B0TEST2301")).toBeInTheDocument();
    expect(fetchMock.mock.calls.map(([input]) => requestPath(input)).some((path) =>
      path === "/api/dashboard/product-card/2301?from=2026-08-01&to=2026-08-31"
    )).toBe(true);
  });

  it("removes the complete legacy product surface in p0 mode", async () => {
    const fetchMock = installApi();
    renderDashboard({ productAnalyticsSource: "p0_catalog" });
    expect(await screen.findByRole("tab", { name: "每日总表" })).toBeVisible();
    expect(screen.queryByRole("tab", { name: "产品总表" })).not.toBeInTheDocument();
    await waitFor(() => expect(fetchMock).toHaveBeenCalled());
    expect(fetchMock.mock.calls.map((call) => requestPath(call[0] as RequestInfo)).some((path) => path.includes("product-ledger") || path.includes("product-card"))).toBe(false);
  });

  it("keeps malformed Seller SKUs separate and non-interactive", async () => {
    const fetchMock = installApi();
    const user = userEvent.setup();
    renderDashboard({ initialEntry: "/?month=2026-08&tab=products" });

    const malformed = await screen.findByRole("row", { name: "未归类 Seller SKU" });
    await user.click(malformed);
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
    expect(fetchMock.mock.calls.map(([input]) => requestPath(input)).every((path) =>
      !path.includes("product-card/BAD-SKU")
    )).toBe(true);
  });

  it("restores product filters, sorting, and pagination from the URL", async () => {
    const fetchMock = installApi();
    renderDashboard({
      initialEntry: "/?month=2026-02&tab=products&search=2301&sort=units_ordered&direction=asc&page=2",
    });

    expect(await screen.findByDisplayValue("2301")).toBeInTheDocument();
    expect(screen.getByLabelText("统计月份")).toHaveValue("2026-02");
    await waitFor(() => {
      expect(fetchMock.mock.calls.map(([input]) => requestPath(input))).toContain(
        "/api/dashboard/product-ledger?from=2026-02-01&to=2026-02-28&search=2301&sort=units_ordered&direction=asc&page=2&page_size=25",
      );
    });
    expect(screen.getByRole("columnheader", { name: "订购数" })).toHaveAttribute("aria-sort", "ascending");
  });
});

it("clears previous month values while the next month loads and rejects late responses", async () => {
  let finishOld!: (value: Response) => void;
  const fetchMock = vi.fn().mockResolvedValueOnce(response(daily)).mockImplementationOnce(() => new Promise<Response>((resolve) => { finishOld = resolve; })).mockResolvedValueOnce(response({ ...daily, rows: [] }));
  vi.stubGlobal("fetch", fetchMock);
  renderDashboard();
  expect(await screen.findByText("2026-08-10")).toBeInTheDocument();
  const { fireEvent, act } = await import("@testing-library/react");
  fireEvent.change(screen.getByLabelText("统计月份"), { target: { value: "2026-07" } });
  expect(screen.queryByText("2026-08-10")).not.toBeInTheDocument();
  expect(screen.getByText("正在核对本月数据")).toBeInTheDocument();
  fireEvent.change(screen.getByLabelText("统计月份"), { target: { value: "2026-06" } });
  expect(await screen.findByText("这个月份没有符合条件的日期记录")).toBeInTheDocument();
  await act(async () => { finishOld(response(daily)); await Promise.resolve(); });
  expect(screen.queryByText("2026-08-10")).not.toBeInTheDocument();
});
