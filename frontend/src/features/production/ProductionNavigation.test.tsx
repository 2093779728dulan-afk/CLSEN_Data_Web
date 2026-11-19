import { act, cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { createMemoryRouter, Route, RouterProvider, Routes, useLocation } from "react-router-dom";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { AuthzGenerationProvider } from "../../app/AuthzGenerationContext";
import { ApiRequestError } from "../../api/client";
import { WorkspaceShell } from "../../app/WorkspaceShell";
import { ProductionWorkspace } from "./ProductionWorkspace";
import { ProductionNavigation } from "./ProductionNavigation";
import type { InventorySnapshot } from "./InventorySnapshotPage";
import type { Document } from "./types";

const api = vi.hoisted(() => ({ read: vi.fn(), write: vi.fn() }));
vi.mock("../../api/client", async importOriginal => ({
  ...await importOriginal<typeof import("../../api/client")>(), requestApi: api.read, writeApi: api.write,
}));

const order: Document = {
  id: "101", system_number: "PO-QA-101", business_number: "虚构导航订单", business_date: "2026-10-14",
  notes: "", status: "CONFIRMED", revision: "1", expected_units: "100", actual_units: "70", difference_units: "30",
  lines: [{ id: "501", sku_id: "1001", sku_label: "QA-BLUE-M", expected_units: "100", actual_units: "70", difference_units: "30" }],
  shipments: [], history: [],
};
const stock: InventorySnapshot = {
  filename: "虚构导航库存.txt", source_digest: "a".repeat(64), source_kind: "FICTIONAL", source_format: "pasted_table",
  organized_on: null, stocktaken_on: null, warehouse_note: "独立虚构夹具", scope: "WAREHOUSE_1", quantity_basis: "DECLARED_TOTAL",
  read_only: true, posting_enabled: false, historical_shipments_deducted: false,
  summary: { source_row_count: 0, row_count: 0, product_count: 0, warehouse_1_units: "0", location_unconfirmed_units: "0",
    literal_units: "0", warehouse_1_literal_units: "0", location_unconfirmed_literal_units: "0", formula_units: "0",
    unknown_cells: 0, defect_literal_units: "0", additional_note_rows: 0 },
  rows: [], unconfirmed_rows: [], defect_period_note: "", defects: [],
};

function Harness({ canWrite = true, enabled = true }: { canWrite?: boolean; enabled?: boolean }) {
  const location = useLocation();
  const roles = canWrite ? ["data_manager" as const] : ["viewer" as const];
  return <AuthzGenerationProvider boundary={{ principalId: 88, roles, siteConfigVersionId: 1, siteId: 1 }} onRevoked={() => undefined}>
    <WorkspaceShell analyticsSource="p0_catalog" productionEnabled={enabled} principal={{ id: 88, username: "qa.navigation", display_name: "虚构操作人员", roles }}
      siteContext={{ site_id: 1, site_code: "QA", display_name: "虚构站点", site_config_version_id: 1, source_timezone: "Asia/Shanghai", reporting_timezone: "Asia/Shanghai", currency_code: "USD" }}
      today="2026-10-14" online logoutBusy={false} onLogout={() => undefined}>
      <Routes><Route path="/production/*" element={<ProductionWorkspace canWrite={canWrite} />} /></Routes>
      <output data-testid="location">{location.pathname}{location.search}{location.hash}</output>
    </WorkspaceShell>
  </AuthzGenerationProvider>;
}
function mount(entry: string, canWrite = true, enabled = true) {
  const router = createMemoryRouter([{ path: "*", element: <Harness canWrite={canWrite} enabled={enabled} /> }], { initialEntries: [entry] });
  render(<RouterProvider router={router} />);
  return router;
}
const primary = () => screen.getByRole("navigation", { name: "工作区" });
const currentLink = () => within(primary()).getAllByRole("link").filter(link => link.getAttribute("aria-current") === "page");

beforeEach(() => {
  window.localStorage.clear(); api.read.mockReset(); api.write.mockReset();
  // JSDOM supplies the router's AbortSignal; Node's Request expects a different realm.
  // Keep the router's actual signal on these local navigation requests (no fetch).
  const NativeRequest = globalThis.Request;
  vi.stubGlobal("Request", class extends NativeRequest {
    constructor(input: RequestInfo | URL, init?: RequestInit) {
      const { signal, ...options } = init ?? {};
      super(input, options);
      if (signal) Object.defineProperty(this, "signal", { value: signal });
    }
  });
  api.read.mockImplementation(async (path: string) => {
    await Promise.resolve();
    if (path === "/api/production/workbench") return { directory_supported: true };
    if (path.startsWith("/api/production/warehouses?")) return { items: [], total: 0, page: 1, page_size: 50 };
    if (path === "/api/production/skus?contract_version=2") return { items: [{ sku_id: "1001", label: "QA-BLUE-M" }], demo: true };
    if (path === "/api/production/source-drafts") return { items: [
      { source_id: "qa-order", kind: "orders", filename: "虚构下单表.xlsx", origin: "SAMPLE", available: true, saved: false, uploaded_at: "2026-10-14T00:00:00Z" },
      { source_id: "qa-shipment", kind: "shipments", filename: "虚构装箱单.xlsx", origin: "SAMPLE", available: true, saved: false, uploaded_at: "2026-10-14T00:00:00Z" },
    ] };
    if (path === "/api/production/order-source-drafts") return { items: [{ sample_id: "qa-order", filename: "虚构下单表.xlsx" }] };
    if (path.startsWith("/api/production/order-source-drafts/")) return { sample_id: path.split("/").pop(), filename: "虚构下单表.xlsx", source_digest: "a".repeat(64), business_date: "2026-10-14", sheet: "QA", source_units: "0", excluded_sheets: [], excluded_rows: [], issues: [], rows: [], saved_draft: null };
    if (path.startsWith("/api/production/shipment-source-drafts/")) return { sample_id: path.split("/").pop(), filename: "虚构装箱单.xlsx", source_digest: "b".repeat(64), box1_units: "0", box2_units: "0", source_units: "0", filename_date_hint: "2026-10-14", excluded_rows: [], excluded_sheets: [], issues: [], rows: [], saved_draft: null };
    if (path === "/api/production/inventory-reviews/current") return { review_id: null, source: stock, source_identity: "qa", can_manage: false };
    if (path.startsWith("/api/production/inventory-reviews/")) return { review_id: "qa-review", revision: 1, source: stock, effective: stock, can_manage: false };
    if (path.startsWith("/api/production/summary?")) return { expected_units: "100", actual_units: "70", difference_units: "30", shipment_period_filtered: false, items: [], skus: [] };
    if (path === "/api/production/orders/101") return order;
    if (path.startsWith("/api/production/orders?") || path.startsWith("/api/production/shipments?")) return { items: [], page: 1, page_size: 20, total: 0 };
    if (path === "/api/production/inventory/availability") return { items: [], scopes: [] };
    if (path.startsWith("/api/production/inventory/forecast?")) return { items: [], excluded_pending: [] };
    if (path.startsWith("/api/production/inventory/")) return { items: [] };
    throw new Error(`Unexpected fictional request: ${path}`);
  });
});
afterEach(() => { cleanup(); vi.unstubAllGlobals(); vi.unstubAllEnvs(); });

describe("independent production pages", () => {
  it("keeps the overview return in the same navigation position for direct and contextual entries", async () => {
    const router = mount("/production/orders");
    const direct = screen.getByRole("link", { name: "返回业务总览" });
    expect(direct).toHaveAttribute("href", "/production/overview");
    const navigationClass = direct.parentElement!.className;
    expect(navigationClass).not.toBe("");
    expect(direct.closest("p")).toBeNull();

    await act(() => router.navigate("/production/orders", { state: { overviewReturn: "/production/overview?q=P4-ORDER-2&warehouse=2" } }));
    const contextual = screen.getByRole("link", { name: "返回业务总览" });
    expect(contextual.parentElement).toHaveClass(navigationClass);
    expect(contextual).toHaveAttribute("href", "/production/overview?q=P4-ORDER-2&warehouse=2");
    expect(contextual.closest("p")).toBeNull();
    await act(() => router.navigate("/production/shipments"));
    expect(screen.getByRole("link", { name: "返回业务总览" })).toHaveAttribute("href", "/production/overview?q=P4-ORDER-2&warehouse=2");
  });

  it("uses the standard overview destination when an entry supplies an invalid return path", () => {
    const router = createMemoryRouter([{ path: "*", element: <Harness /> }], { initialEntries: [{ pathname: "/production/orders", state: { overviewReturn: "https://example.com/production/overview" } }] });
    render(<RouterProvider router={router} />);
    expect(screen.getByRole("link", { name: "返回业务总览" })).toHaveAttribute("href", "/production/overview");
  });

  it("omits the redundant factory-only navigation while retaining the order and shipment switch", async () => {
    const router = createMemoryRouter([{ path: "*", element: <ProductionNavigation /> }], { initialEntries: ["/production/factories/7"] });
    render(<RouterProvider router={router} />);
    expect(screen.queryByRole("navigation", { name: "工厂管理功能" })).not.toBeInTheDocument();
    await act(() => router.navigate("/production/orders/10"));
    expect(await screen.findByRole("navigation", { name: "订单与出货功能" })).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "全部出货" })).toHaveAttribute("href", "/production/shipments");
  });
  it("order receipt entry starts from the confirmed order without an independent order search", async () => {
    const original = api.read.getMockImplementation()!;
    api.read.mockImplementation((path: string) => path === "/api/production/orders/101" ? Promise.resolve({ ...order, received_units: "0" }) : path === "/api/production/inventory/availability" ? Promise.resolve({ items: [], scopes: [], writes_enabled: true, production_receipts_supported: true }) : original(path) as Promise<unknown>);
    const user = userEvent.setup(); mount("/production/orders/101");
    await user.click(await screen.findByRole("button", { name: "登记生产实收" }));
    await screen.findByRole("heading", { name: "从订单登记生产实收" });
    expect(screen.getByTestId("location")).toHaveTextContent("/production/stock/movements/new?order_id=101");
    expect(screen.queryByLabelText("查找来源订单")).not.toBeInTheDocument();
    expect(api.write).not.toHaveBeenCalled();
  });
  it.each([
    { canWrite: false, supported: true, writes: true, status: "CONFIRMED" },
    { canWrite: true, supported: false, writes: true, status: "CONFIRMED" },
    { canWrite: true, supported: true, writes: false, status: "CONFIRMED" },
    { canWrite: true, supported: true, writes: true, status: "VOID" },
  ])("order receipt entry respects role, capability, write policy and source status: %j", async ({ canWrite, supported, writes, status }) => {
    const original = api.read.getMockImplementation()!;
    api.read.mockImplementation((path: string) => path === "/api/production/orders/101" ? Promise.resolve({ ...order, status, received_units: "0" }) : path === "/api/production/inventory/availability" ? Promise.resolve({ items: [], scopes: [], writes_enabled: writes, production_receipts_supported: supported }) : original(path) as Promise<unknown>);
    mount("/production/orders/101", canWrite);
    await screen.findByRole("heading", { name: order.business_number, level: 1 });
    expect(screen.queryByRole("button", { name: "登记生产实收" })).not.toBeInTheDocument();
    expect(api.write).not.toHaveBeenCalled();
  });
  it.each([
    ["/production/orders/intake", "/production/orders/new"],
    ["/production/stock/intake", "/production/stock/movements/new?kind=ADJUST"],
    ["/production/shipments/intake?method=table", "/production/shipments/new?method=table&flow=guided&purpose=WAREHOUSE_DISPATCH"],
  ])("keeps the default intake on its unified business form: %s", async (entry, destination) => {
    mount(entry);
    await waitFor(() => expect(screen.getByTestId("location")).toHaveTextContent(destination));
    expect(screen.queryByRole("group", { name: "这份表用于什么业务" })).not.toBeInTheDocument();
    expect(api.write).not.toHaveBeenCalled();
  });

  it.each(["orders", "shipments", "stock"])("keeps legacy %s intake in business context without a second purpose selector", async business => {
    vi.stubEnv("VITE_MANUAL_TABLES_ENABLED", "true");
    const original = api.read.getMockImplementation()!;
    api.read.mockImplementation((path: string) => path === "/api/manual-tables/capabilities" ? Promise.resolve({ enabled: false }) : original(path) as Promise<unknown>);
    const user = userEvent.setup(); mount(`/production/${business}/intake?layout=raw&method=manual`);
    expect(screen.queryByRole("group", { name: "这份表用于什么业务" })).not.toBeInTheDocument();
    expect(screen.getByRole("link", { name: business === "stock" ? /手工盘点调整/ : /手工填写/ })).toHaveAttribute("href", business === "stock" ? "/production/stock/movements/new?kind=ADJUST" : `/production/${business}/new`);
    const tableImport = screen.getByRole("button", { name: /从表格导入/ });
    expect(tableImport).toHaveAttribute("aria-expanded", "false");
    await user.click(tableImport);
    if (business === "shipments") {
      await waitFor(() => expect(screen.getByTestId("location")).toHaveTextContent("/production/shipments/new?"));
      expect(screen.getByTestId("location")).toHaveTextContent("flow=guided&purpose=WAREHOUSE_DISPATCH");
      expect(api.write).not.toHaveBeenCalled();
      return;
    }
    expect(tableImport).toHaveAttribute("aria-expanded", "true");
    await user.click(screen.getByText("标准模板与已适配格式", { exact: true }));
    if (business !== "stock") expect(screen.getByRole("link", { name: "使用标准模板导入" })).toHaveAttribute("href", `/production/${business}/import`);
    else expect(screen.getByRole("link", { name: "查看已有库存原表" })).toHaveAttribute("href", "/production/inventory/source");
    expect(currentLink()[0]).toHaveAccessibleName(business === "stock" ? "仓库中心" : "订单与出货");
    expect(api.write).not.toHaveBeenCalled();
  });

  it("shows saved legacy sources in processing records without introducing another upload form", async () => {
    const user = userEvent.setup(); mount("/production/orders/materials?source=legacy");
    await screen.findByText("虚构下单表.xlsx");
    expect(screen.queryByLabelText("XLSX原表")).not.toBeInTheDocument();
    await user.click(screen.getByRole("link", { name: "预览原表：虚构下单表.xlsx" }));
    expect(screen.getByTestId("location")).toHaveTextContent("/production/source-drafts/orders?sample=qa-order");
    expect(currentLink()[0]).toHaveAccessibleName("订单与出货");
    expect(api.write).not.toHaveBeenCalled();
  });

  it("keeps legacy shipment filters inside shipment records", async () => {
    const user = userEvent.setup(); mount("/production/shipments/materials?source=legacy&kind=packing");
    await screen.findByText("虚构装箱单.xlsx");
    expect(screen.queryByText("虚构下单表.xlsx")).not.toBeInTheDocument();
    await user.type(screen.getByRole("textbox", { name: "查找文件或业务单号" }), "装箱");
    await user.click(screen.getByRole("button", { name: "查找草稿" }));
    expect(screen.getByTestId("location")).toHaveTextContent("source=legacy");
    expect(screen.getByRole("heading", { name: "出货资料", level: 1 })).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "清空条件" }));
    expect(screen.getByTestId("location")).toHaveTextContent("/production/shipments/materials?source=legacy");
    expect(screen.getByText("虚构装箱单.xlsx")).toBeInTheDocument();
    expect(api.write).not.toHaveBeenCalled();
  });

  it("keeps unrecognized old import purposes at the business chooser", () => {
    mount("/production/imports?kind=__proto__");
    expect(screen.getByRole("heading", { name: "选择要办理的业务", level: 1 })).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "新增订单" })).toHaveAttribute("href", "/production/orders/intake");
    expect(api.write).not.toHaveBeenCalled();
  });

  it("keeps central upload unavailable to viewers", async () => {
    vi.stubEnv("VITE_MANUAL_TABLES_ENABLED", "true"); mount("/production/imports?kind=orders&layout=raw", false);
    expect(await screen.findByText("当前账号只读")).toBeInTheDocument();
    expect(screen.queryByLabelText("人工表格文件")).not.toBeInTheDocument();
    expect(screen.queryByRole("link", { name: "使用标准模板导入" })).not.toBeInTheDocument();
    expect(api.write).not.toHaveBeenCalled();
  });

  it("opens the quantity summary inside order tracking without losing the list URL", async () => {
    const user = userEvent.setup(); mount("/production/orders?q=QA");
    await user.click(await screen.findByText("查看订单数量汇总", { exact: true }));
    await screen.findByRole("link", { name: "高级汇总查询" });
    expect(api.read).toHaveBeenCalledWith("/api/production/summary?", expect.anything());
    expect(screen.getByTestId("location")).toHaveTextContent("/production/orders?q=QA");
    expect(api.write).not.toHaveBeenCalled();
  });

  it("shows current availability for the order's stable SKU and keeps unknown stock explicit", async () => {
    const original = api.read.getMockImplementation()!;
    api.read.mockImplementation((path: string) => path === "/api/production/inventory/availability" ? Promise.resolve({ items: [
      { warehouse_id: "1", sku_id: "1001", state: "not_ready", free_available_units: null },
      { warehouse_id: "1", sku_id: "9999", state: "ready", free_available_units: "999" },
    ], scopes: [{ warehouse_id: "1", warehouse_name: "虚构仓" }] }) : original(path) as Promise<unknown>);
    const user = userEvent.setup(); mount("/production/orders/101");
    await user.click(await screen.findByText("发货前查看当前可发库存", { exact: true }));
    const table = await screen.findByRole("table", { name: "当前自由可发" });
    expect(table).toHaveTextContent("QA-BLUE-M"); expect(table).toHaveTextContent("可发待核");
    expect(table).not.toHaveTextContent("999"); expect(api.write).not.toHaveBeenCalled();
  });
  it.each(["orders", "shipments"] as const)("preserves common and collapsed advanced filters for %s", async page => {
    const user = userEvent.setup(); mount(`/production/${page}?sku=1001`);
    await screen.findByRole("option", { name: "QA-BLUE-M" });
    await user.type(screen.getByLabelText("单号搜索"), "QA");
    await user.selectOptions(screen.getByLabelText("状态"), "CONFIRMED");
    expect(screen.getByLabelText("业务日期从")).not.toBeVisible();
    await user.click(screen.getByText("更多筛选", { exact: true }));
    expect(screen.getByLabelText("业务日期从")).toBeVisible();
    fireEvent.change(screen.getByLabelText("业务日期从"), { target: { value: "2026-10-14" } });
    await user.type(screen.getByLabelText("关联系统订单号（可选）"), "PO-QA-101");
    if (page === "orders") await user.selectOptions(screen.getByLabelText("跟进筛选"), "CLOSED");
    await user.click(screen.getByText("更多筛选", { exact: true }));
    await user.click(screen.getByRole("button", { name: "应用筛选" }));
    const query = new URL(`http://fixture${screen.getByTestId("location").textContent}`).searchParams;
    expect(query.get("sku")).toBe("1001"); expect(query.get("q")).toBe("QA");
    expect(query.get("status")).toBe("CONFIRMED"); expect(query.get("from")).toBe("2026-10-14");
    expect(query.get("order")).toBe("PO-QA-101"); expect(query.get("page")).toBe("1");
    if (page === "orders") expect(query.get("tracking")).toBe("CLOSED");
    expect(screen.getByLabelText("业务日期从")).toBeVisible();
    expect(screen.getByRole("combobox", { name: "SKU" })).toHaveValue("1001");
    await user.click(screen.getByRole("button", { name: "清空筛选" }));
    expect(screen.getByTestId("location").textContent).toBe(`/production/${page}`);
    expect(screen.getByLabelText("业务日期从")).not.toBeVisible();
    expect(api.write).not.toHaveBeenCalled();
  });

  it.each(["orders", "shipments"] as const)("keeps %s creation and import links role-bound while export retains the current query", async page => {
    mount(`/production/${page}?q=QA`);
    await screen.findByRole("heading", { name: page === "orders" ? "预计订单" : "仓库出货", level: 1 });
    expect(screen.getByRole("link", { name: page === "orders" ? "新增订单" : "新建仓库出货" })).toHaveAttribute("href", `/production/${page}/intake`);
    expect(screen.queryByRole("link", { name: `导入${page === "orders" ? "订单" : "出货"}资料` })).not.toBeInTheDocument();
    cleanup(); mount(`/production/${page}?q=QA`, false);
    expect(screen.queryByRole("link", { name: /^(新增订单|新建仓库出货)$/ })).not.toBeInTheDocument();
    expect(screen.queryByRole("link", { name: `导入${page === "orders" ? "订单" : "出货"}资料` })).not.toBeInTheDocument();
    expect(await screen.findByRole("link", { name: "导出查询结果" })).toHaveAttribute("href", `/api/production/files/${page}/export?q=QA`);
    await waitFor(() => expect(screen.queryByText("正在读取…")).not.toBeInTheDocument());
    expect(api.write).not.toHaveBeenCalled();
  });

  it.each(["orders", "shipments", "summary"])("keeps the linked SKU selected in %s after async options load and preserves it when applying filters", async page => {
    const user = userEvent.setup(); mount(`/production/${page}?sku=1001`);
    await screen.findByRole("option", { name: "QA-BLUE-M" });
    expect(screen.getByRole("combobox", { name: "SKU" })).toHaveValue("1001");
    await user.click(screen.getByRole("button", { name: "应用筛选" }));
    expect(screen.getByTestId("location")).toHaveTextContent("sku=1001");
    expect(api.write).not.toHaveBeenCalled();
  });

  it("keeps a stock rejection understandable with the selected product identity", async () => {
    const user = userEvent.setup();
    const original = api.read.getMockImplementation()!;
    api.read.mockImplementation((path: string, options?: unknown) => {
      if (path === "/api/production/inventory/availability") return Promise.resolve({ items: [], scopes: [{ warehouse_id: "1", warehouse_name: "虚构库存仓1" }] });
      if (path === "/api/production/inventory/plans") return Promise.resolve({ items: [] });
      if (path.startsWith("/api/production/inventory/availability?")) return Promise.resolve({ state: "ready", on_hand_units: "3", free_available_units: "3", dispatch_allowed_units: "3" });
      if (path.startsWith("/api/production/orders?status=CONFIRMED")) return Promise.resolve({ items: [order] });
      return original(path, options) as Promise<unknown>;
    });
    api.write.mockImplementation((path: string) => {
      if (path === "/api/production/sources/shipments/check") return Promise.resolve({ candidates: [], duplicate_document: false });
      return Promise.reject(new ApiRequestError(409, "insufficient_available_stock", "SKU 1001 请求7件，当前允许3件"));
    });
    mount("/production/shipments/new?order_id=101");
    await screen.findByRole("heading", { name: "创建实际出货", level: 1 });
    await screen.findByLabelText(/本次实际数量 1/);
    await user.type(screen.getByLabelText(/本次实际数量 1/), "7");
    await user.type(screen.getByLabelText(/分配数量 1-1/), "7");
    await user.type(screen.getByLabelText("人工来源及区别说明"), "独立虚构发货核对");
    await user.click(screen.getByRole("button", { name: "保存并确认" }));
    await screen.findByText("SKU 1001 请求7件，当前允许3件");
    expect(screen.getByText(/仓库库存出货商品：QA-BLUE-M（SKU 1001）/)).toBeInTheDocument();
    expect(screen.getByLabelText(/本次实际数量 1/)).toHaveValue("7");
  });
  it("dispatch stock refresh keeps shipment inputs and separates pending and defective stock from allowed units", async () => {
    const user = userEvent.setup(); const original = api.read.getMockImplementation()!;
    let available = "3";
    api.read.mockImplementation((path: string, options?: unknown) => {
      if (path.startsWith("/api/production/inventory/availability?")) return Promise.resolve({ state: "ready", on_hand_units: "6", qualified_units: available, pending_units: "2", defective_units: "1", unassessed_units: "0", free_available_units: available, dispatch_allowed_units: available });
      return original(path, options) as Promise<unknown>;
    });
    mount("/production/shipments/new?order_id=101&warehouse_id=1");
    await screen.findByText("本次当前允许 3 件");
    expect(screen.getByText(/合格 3 · 待检 2 · 次品 1 · 质量未核 0 件/)).toBeInTheDocument();
    expect(screen.getByText(/待检、次品和质量未核数量不计入当前可发/)).toBeInTheDocument();
    await user.type(screen.getByLabelText(/本次实际数量 1/), "2");
    await user.type(screen.getByLabelText(/分配数量 1-1/), "2");
    await user.type(screen.getByLabelText("人工来源及区别说明"), "虚构检验后出货");
    available = "1";
    await user.click(screen.getByRole("button", { name: "刷新当前可发量" }));
    await screen.findByText("本次当前允许 1 件");
    expect(screen.getByLabelText(/本次实际数量 1/)).toHaveValue("2");
    expect(screen.getByLabelText(/分配数量 1-1/)).toHaveValue("2");
    expect(screen.getByLabelText("人工来源及区别说明")).toHaveValue("虚构检验后出货");
    expect(api.write).not.toHaveBeenCalled();
  });
  it("dispatch stock refresh can recover a failed read without inventing zero quality quantities", async () => {
    const user = userEvent.setup(); const original = api.read.getMockImplementation()!;
    let failed = true;
    api.read.mockImplementation((path: string, options?: unknown) => {
      if (path.startsWith("/api/production/inventory/availability?")) return failed ? Promise.reject(new Error("虚构库存读取中断")) : Promise.resolve({ state: "not_ready", on_hand_units: "6", dispatch_allowed_units: null, free_available_units: null, missing: "货品状态待核，当前不能发货。" });
      return original(path, options) as Promise<unknown>;
    });
    mount("/production/shipments/new?order_id=101&warehouse_id=1");
    await screen.findByText("虚构库存读取中断");
    failed = false;
    await user.click(screen.getByRole("button", { name: "刷新当前可发量" }));
    await screen.findByText("当前可发尚未就绪");
    expect(screen.getByText(/货品状态待核，当前不能发货。/)).toBeInTheDocument();
    expect(screen.getByText(/合格 未核实 · 待检 未核实 · 次品 未核实 · 质量未核 未核实 件/)).toBeInTheDocument();
    expect(screen.queryByText(/本次当前允许 0 件/)).not.toBeInTheDocument();
    expect(api.write).not.toHaveBeenCalled();
  });
  it("prefills the selected sales plan without inventing a shipment quantity", async () => {
    const original = api.read.getMockImplementation()!;
    api.read.mockImplementation((path: string) => {
      if (path === "/api/production/inventory/availability") return Promise.resolve({ items: [], scopes: [{ warehouse_id: "1", warehouse_name: "虚构库存仓1" }] });
      if (path === "/api/production/inventory/plans") return Promise.resolve({ items: [{ id: "91", warehouse_id: "1", sku_id: "1001", direction: "OUT", source_reference: "虚构销售安排", planned_on: "2026-10-20", remaining_units: "4" }] });
      return original(path) as Promise<unknown>;
    });
    mount("/production/shipments/new?plan_id=91&sku_id=1001&warehouse_id=1");
    expect(await screen.findByLabelText("来源 1 的预计出库安排（可选）")).toHaveValue("91");
    expect(screen.getByLabelText(/本次实际数量 1/)).toHaveValue("");
    expect(screen.getByRole("link", { name: "查看关联安排" })).toHaveAttribute("href", "/production/stock/plans#plan-91");
    expect(api.write).not.toHaveBeenCalled();
  });
  it("marks a shipment line as production direct without requesting warehouse stock or a sales plan", async () => {
    const user = userEvent.setup();
    const original = api.read.getMockImplementation()!;
    api.read.mockImplementation((path: string) => {
      if (path === "/api/production/inventory/availability") return Promise.resolve({ items: [], scopes: [{ warehouse_id: "1", warehouse_name: "虚构库存仓1" }] });
      if (path === "/api/production/inventory/plans") return Promise.resolve({ items: [{ id: "91", warehouse_id: "1", sku_id: "1001", direction: "OUT", source_reference: "虚构销售安排", planned_on: "2026-10-20", remaining_units: "4" }] });
      if (path.startsWith("/api/production/inventory/availability?")) return Promise.resolve({ state: "not_ready", on_hand_units: null, free_available_units: null, dispatch_allowed_units: null });
      return original(path) as Promise<unknown>;
    });
    api.write.mockImplementation((path: string, options?: { body?: unknown }) => path === "/api/production/sources/shipments/check" ? Promise.resolve({ candidates: [] }) : Promise.resolve({ id: "201", system_number: "SH-QA-201", status: "CONFIRMED", revision: "1", ...(options?.body as object) }));
    mount("/production/shipments/new?order_id=101");
    await screen.findByRole("heading", { name: "创建实际出货", level: 1 });
    await user.selectOptions(screen.getByLabelText("货物来源 1"), "PRODUCTION_DIRECT");
    expect(screen.getByText("生产直发，不影响仓库库存")).toBeInTheDocument();
    expect(screen.queryByLabelText("来源 1 的预计出库安排（可选）")).not.toBeInTheDocument();
    expect(screen.queryByText(/本次当前允许|当前可发尚未就绪/)).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "刷新当前可发量" })).not.toBeInTheDocument();
    await user.type(screen.getByLabelText(/本次实际数量 1/), "30");
    await user.type(screen.getByLabelText(/分配数量 1-1/), "30");
    await user.type(screen.getByLabelText("人工来源及区别说明"), "虚构生产直发核对");
    await user.click(screen.getByRole("button", { name: "保存并确认" }));
    await waitFor(() => expect(api.write.mock.calls.some(call => call[0] === "/api/production/shipments")).toBe(true));
    const saved = api.write.mock.calls.find(call => call[0] === "/api/production/shipments")?.[1] as { body: { sources: { fulfillment_mode: string; plan_id: string | null; actual_units: string }[] } };
    expect(saved.body.sources[0]).toMatchObject({ fulfillment_mode: "PRODUCTION_DIRECT", plan_id: null, actual_units: "30" });
  });
  it("keeps the original source viewer read-only alongside the fictional review", async () => {
    const user = userEvent.setup();
    api.read.mockImplementation(async (path: string) => {
      await Promise.resolve();
      if (path === "/api/production/inventory-reviews/current") return { review_id: "qa-review", source: stock, source_identity: "qa", can_manage: true, writes_enabled: true, source_view_available: true };
      if (path === "/api/production/inventory-reviews/qa-review") return { review_id: "qa-review", source_identity: "qa", revision: 10, source: stock, effective: stock, overrides: {}, can_manage: true, writes_enabled: true, source_view_available: true };
      if (path === "/api/production/inventory-snapshot") return { ...stock, source_kind: "REAL_SOURCE" };
      throw new Error(`Unexpected source request: ${path}`);
    });
    mount("/production/inventory");
    await screen.findByRole("button", { name: "查看核对历史" });
    await user.click(screen.getByRole("link", { name: "查看真实库存资料（只读）" }));
    expect(screen.getByTestId("location").textContent).toBe("/production/inventory/source");
    await waitFor(() => expect(api.read).toHaveBeenCalledWith("/api/production/inventory-snapshot", expect.anything()));
    await screen.findByText(/真实库存资料仅供查看/);
    expect(screen.getByTestId("location")).toHaveTextContent("/production/inventory/source");
    expect(currentLink()[0]).toHaveAccessibleName("仓库中心");
    expect(screen.queryByRole("button", { name: "开始资料核对" })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "核对盘点日期与截止" })).not.toBeInTheDocument();
    await user.click(screen.getByRole("link", { name: "返回库存资料核对" }));
    await screen.findByRole("button", { name: "查看核对历史" });
    expect(api.write).not.toHaveBeenCalled();
  });

  it("guides a direct inventory visit to the available material records when no default snapshot exists", async () => {
    api.read.mockRejectedValue(new Error("当前本地环境尚未配置库存快照。"));
    mount("/production/inventory");
    expect(await screen.findByRole("heading", { name: "选择库存资料", level: 1 })).toBeVisible();
    expect(screen.getByText("当前环境没有默认库存表，请从已有资料中选择要查看的固定核对单。")).toBeVisible();
    expect(screen.getByRole("link", { name: "打开库存资料记录" })).toHaveAttribute("href", "/production/stock/materials");
    expect(screen.queryByText("核对未就绪或操作未完成")).not.toBeInTheDocument();
  });

  it("opens a manual inventory review without reading an unrelated configured source", async () => {
    const manual = { ...stock, source_kind: "MANUAL", source_format: "manual_table_v1", manual_batch_id: "manual-batch", warehouse_note: "独立虚构仓" };
    api.read.mockResolvedValue({ review_id: "manual-review", source_identity: "manual", revision: 0, source: manual, effective: manual, can_manage: true, writes_enabled: true, source_view_available: true });
    mount("/production/inventory?review=manual-review");
    await screen.findByRole("heading", { name: "产品库存", level: 1 });
    expect(screen.getByRole("link", { name: "返回人工整理来源与操作历史" })).toHaveAttribute("href", "/production/stock/materials/manual-batch");
    expect(screen.queryByRole("link", { name: "查看真实库存资料（只读）" })).not.toBeInTheDocument();
    expect(api.read.mock.calls.some(call => call[0] === "/api/production/inventory-reviews/current")).toBe(false);
  });

  it.each([false, true])("uses the environment's review write activation (%s)", async writesEnabled => {
    api.read.mockResolvedValue({ review_id: null, source: stock, source_identity: "qa", can_manage: writesEnabled, writes_enabled: writesEnabled });
    mount("/production/inventory");
    await screen.findByRole("heading", { name: "产品库存", level: 1 });
    if (writesEnabled) expect(screen.getByRole("button", { name: "开始资料核对" })).toBeVisible();
    else {
      expect(screen.queryByRole("button", { name: "开始资料核对" })).not.toBeInTheDocument();
      expect(screen.getByText("此环境仅查看库存资料，资料核对写入尚未启用。")).toBeVisible();
    }
    expect(api.write).not.toHaveBeenCalled();
  });

  it("keeps warehouse and factory navigation while retaining historic stock links", async () => {
    const user = userEvent.setup(); mount("/production/orders?q=QA&page=2");
    expect(within(primary()).getAllByRole("link").filter(link => link.getAttribute("href")?.startsWith("/production/"))).toHaveLength(4);
    expect(within(primary()).getByRole("link", { name: "业务总览" })).toHaveAttribute("href", "/production/overview");
    for (const [group, items] of [
      ["订单与出货", [["订单跟进", "预计订单", "/production/orders"], ["全部出货", "仓库出货", "/production/shipments"]]],
      ["仓库中心", [["仓库中心", "仓库中心", "/production/warehouses"], ["库存总览", "库存总览", "/production/stock"], ["库存记录", "库存记录", "/production/stock/movements"]]],
    ] as const) {
      await user.click(within(primary()).getByRole("link", { name: group }));
      for (const [label, title, path] of items) {
        if (path === "/production/warehouses") {
          // Stock discovery remains visible in the main warehouse workspace.
          expect(within(screen.getByRole("navigation", { name: "仓库中心功能" })).getByRole("link", { name: "库存总览" })).toHaveAttribute("href", "/production/stock");
        } else if (path === "/production/stock") {
          await user.click(within(screen.getByRole("navigation", { name: "仓库中心功能" })).getByRole("link", { name: "库存总览" }));
        } else {
          const local = screen.getByRole("navigation", { name: `${group}功能` });
          expect(within(local).getAllByRole("link")).toHaveLength(group === "仓库中心" ? 3 : 2);
          await user.click(within(local).getByRole("link", { name: label }));
        }
        await screen.findByRole("heading", { name: title, level: 1 });
        expect(screen.getByTestId("location").textContent).toBe(path);
        expect(currentLink()).toHaveLength(1); expect(currentLink()[0]).toHaveAccessibleName(group);
        if (path !== "/production/warehouses") expect(within(screen.getByRole("navigation", { name: `${group}功能` })).getByRole("link", { name: label })).toHaveAttribute("aria-current", "page");
      }
    }
    expect(api.write).not.toHaveBeenCalled();
  });

  it.each([
    ["/production/summary?sku=1001", "预计与实际汇总", "订单与出货"],
    ["/production/products", "生产商品基础", "订单与出货"],
    ["/production/stock/loans", "借出与归还", "仓库中心"],
    ["/production/stock/plans", "预计库存与收发安排", "仓库中心"],
    ["/production/stock/history", "库存操作历史", "仓库中心"],
    ["/production/inventory", "产品库存", "仓库中心"],
    ["/production/source-drafts", "原表与导入草稿", "订单与出货"],
  ])("preserves the historic address and functionality at %s", async (entry, title, group) => {
    mount(entry); await screen.findByRole("heading", { name: title, level: 1 });
    expect(currentLink()[0]).toHaveAccessibleName(group);
    expect(screen.getByTestId("location").textContent).toBe(entry);
    expect(api.write).not.toHaveBeenCalled();
  });

  it.each([
    ["/production/orders/101", "订单与出货", "订单跟进"],
    ["/production/stock/movements/new", "仓库中心", "库存记录"],
    ["/production/stock/opening", "仓库中心", "库存总览"],
  ])("keeps the right group and local section active for a direct detail or form URL %s", async (entry, group, label) => {
    mount(entry);
    expect(currentLink()).toHaveLength(1); expect(currentLink()[0]).toHaveAccessibleName(group);
    const local = screen.getByRole("navigation", { name: `${group}功能` });
    expect(within(local).getByRole("link", { name: label })).toHaveAttribute("aria-current", "page");
    await waitFor(() => expect(screen.queryByText("正在读取…")).not.toBeInTheDocument());
    expect(screen.getByTestId("location").textContent).toBe(entry);
    expect(api.write).not.toHaveBeenCalled();
  });

  it.each(["orders", "shipments"])("keeps %s source bookmarks, query and anchor while opening the source page", async kind => {
    mount(`/production/${kind}/source-drafts?sample=qa-${kind}&q=QA#source-catalog-reference`);
    await waitFor(() => expect(screen.getByTestId("location")).toHaveTextContent(`/production/source-drafts/${kind}?sample=qa-${kind}&q=QA#source-catalog-reference`));
    expect(currentLink()[0]).toHaveAccessibleName("订单与出货");
    await screen.findByRole("heading", { name: kind === "orders" ? "下单表 · 预览与导入草稿" : "装箱单体验 · 假设已发", level: 1 });
    expect(api.write).not.toHaveBeenCalled();
  });

  it("opens an existing inventory review without changing its URL or creating a new review", async () => {
    const entry = "/production/inventory?review=qa-review&product=%5B%22style%22%2C%22QA-1101%22%5D";
    mount(entry); await screen.findByRole("heading", { name: "产品库存", level: 1 });
    expect(screen.getByTestId("location").textContent).toBe(entry);
    expect(currentLink()[0]).toHaveAccessibleName("仓库中心"); expect(api.write).not.toHaveBeenCalled();
  });

  it("keeps unsaved order input when local navigation is cancelled, then allows explicit departure", async () => {
    const user = userEvent.setup(); mount("/production/orders/new");
    await screen.findByRole("heading", { name: "创建预计订单", level: 1 });
    await user.type(screen.getByRole("textbox", { name: "业务单号（可选）" }), "QA-unsaved");
    await user.click(within(screen.getByRole("navigation", { name: "订单与出货功能" })).getByRole("link", { name: "全部出货" }));
    const dialog = await screen.findByRole("dialog", { name: "还有未保存的内容" });
    await user.click(within(dialog).getByRole("button", { name: "继续填写" }));
    expect(screen.getByRole("textbox", { name: "业务单号（可选）" })).toHaveValue("QA-unsaved");
    expect(currentLink()[0]).toHaveAccessibleName("订单与出货");
    await user.click(within(screen.getByRole("navigation", { name: "订单与出货功能" })).getByRole("link", { name: "全部出货" }));
    await user.click(within(await screen.findByRole("dialog", { name: "还有未保存的内容" })).getByRole("button", { name: "放弃并离开" }));
    await screen.findByRole("heading", { name: "仓库出货", level: 1 }); expect(api.write).not.toHaveBeenCalled();
  });

  it("uses source-manager links to open source pages in their own navigation context", async () => {
    const user = userEvent.setup(); mount("/production/source-drafts");
    const link = await screen.findByRole("link", { name: "预览原表：虚构下单表.xlsx" });
    expect(link).toHaveAttribute("href", expect.stringContaining("/production/source-drafts/"));
    await user.click(link); await waitFor(() => expect(currentLink()[0]).toHaveAccessibleName("订单与出货"));
  });

  it("keeps the drawer entries accessible and closes the drawer when changing pages", async () => {
    const user = userEvent.setup(); mount("/production/orders");
    // JSDOM does not lay out responsive media queries; test the drawer interaction itself.
    await user.click(screen.getByLabelText("打开主导航"));
    const drawer = await screen.findByRole("dialog", { name: "工作区导航" });
    await user.click(within(drawer).getByRole("link", { name: "仓库中心" }));
    await screen.findByRole("heading", { name: "仓库中心", level: 1 });
    await waitFor(() => expect(screen.queryByRole("dialog", { name: "工作区导航" })).not.toBeInTheDocument());
  });

  it("keeps read-only accounts unable to create orders and hides disabled production navigation", async () => {
    mount("/production/orders/new", false);
    await screen.findByText("查看人员不能创建单据"); expect(screen.queryByRole("textbox")).not.toBeInTheDocument();
    cleanup(); mount("/production/orders", false, false);
    for (const name of ["订单与出货", "仓库中心", "导入资料"]) expect(within(primary()).queryByRole("link", { name })).not.toBeInTheDocument();
    await waitFor(() => expect(screen.queryByText("正在读取…")).not.toBeInTheDocument());
    expect(api.write).not.toHaveBeenCalled();
  });
});
