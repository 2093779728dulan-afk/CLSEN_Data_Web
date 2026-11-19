import { act, cleanup, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import { createMemoryRouter, RouterProvider } from "react-router-dom";
import { AuthzGenerationProvider } from "../../app/AuthzGenerationContext";
import { DirectoryWorkspace } from "./DirectoryWorkspace";
import { ProductionWorkspace } from "./ProductionWorkspace";
import { ApiRequestError } from "../../api/client";
import type { DirectoryRecord } from "./directoryTypes";

const api = vi.hoisted(() => ({ read: vi.fn<(path: string) => Promise<unknown>>(), write: vi.fn<(path: string, options: { body: Record<string, unknown> }) => Promise<unknown>>() }));
vi.mock("../../api/client", async original => ({ ...await original<typeof import("../../api/client")>(), requestApi: api.read, writeApi: api.write }));
const warehouse: DirectoryRecord = { id: "900", name: "虚构青禾仓", type: "FACTORY", country: "中国", status: "ACTIVE", revision: "1", region: "", address: "", operator: "", contact: "", phone: "", timezone: "", seller_account: "", marketplace: "", inventory_state: "UNINITIALIZED", scopes: [], factory_ids: [], history: [] };
const readyWarehouse: DirectoryRecord = { ...warehouse, id: "1", name: "虚构广州仓", inventory_state: "READY", scopes: [{ warehouse_id: "1", owner_id: "1", warehouse_name: "虚构广州仓", owner_name: "公司自有（虚构）", warehouse_status: "ACTIVE", warehouse_type: "FACTORY" }] };
const stockItems = [
  { warehouse_id: "1", owner_id: "1", sku_id: "1001", style_code: "2301", standard_color: "Blue", standard_size: "M", on_hand_units: "4", free_available_units: "3", qualified_units: "4", pending_units: "0", defective_units: "0", held_units: "0", reserved_units: "1", state: "ready" },
  { warehouse_id: "1", owner_id: "1", sku_id: "1002", style_code: "2301", standard_color: "Blue", standard_size: "L", on_hand_units: "2", free_available_units: "1", qualified_units: "2", pending_units: "0", defective_units: "0", held_units: "0", reserved_units: "1", state: "ready" },
  { warehouse_id: "1", owner_id: "1", sku_id: "1003", style_code: "2301", standard_color: "White", standard_size: "M", on_hand_units: "1", free_available_units: "1", qualified_units: "1", pending_units: "0", defective_units: "0", held_units: "0", reserved_units: "0", state: "ready" },
];
const catalogItems = stockItems.map((item, index) => ({ sku_id: item.sku_id, style_id: "23", style_code: "2301", standard_color: item.standard_color, standard_size: item.standard_size, code: `2301-${item.standard_color}-${item.standard_size}`, label: `短袖T恤 ${item.standard_color} ${item.standard_size}`, status: "active", catalog_version: String(index + 1) }));
function installWarehouseCenterMocks(options: { warehouses?: DirectoryRecord[]; documents?: unknown[]; shipments?: unknown[]; loans?: Record<string, unknown>[] } = {}) {
  const original = api.read.getMockImplementation()!;
  const warehouses = options.warehouses || [readyWarehouse];
  api.read.mockImplementation(async path => {
    await Promise.resolve();
    if (path.startsWith("/api/production/warehouses?")) return { items: warehouses, total: warehouses.length, page: 1, page_size: 50 };
    const warehouseMatch = path.match(/^\/api\/production\/warehouses\/(\d+)$/);
    if (warehouseMatch) return warehouses.find(item => item.id === warehouseMatch[1]) || readyWarehouse;
    if (path.startsWith("/api/production/inventory/availability?")) return { items: stockItems, scopes: readyWarehouse.scopes, writes_enabled: true, opening_enabled: false, production_receipts_supported: true };
    if (path === "/api/production/inventory/availability") return { items: stockItems, scopes: readyWarehouse.scopes, writes_enabled: true, production_receipts_supported: true };
    if (path === "/api/production/skus?contract_version=2") return { items: catalogItems };
    if (path.startsWith("/api/production/inventory/documents?")) return { items: options.documents || [], limit: 200 };
    const movementMatch = path.match(/^\/api\/production\/inventory\/documents\/(\d+)$/);
    if (movementMatch) return (options.documents || []).find(item => (item as { id: string }).id === movementMatch[1]);
    if (path.startsWith("/api/production/shipments?")) return { items: options.shipments || [], total: options.shipments?.length || 0, page: 1 };
    if (path === "/api/production/inventory/plans") return { items: [] };
    if (path === "/api/production/inventory/loans") return { items: options.loans || [] };
    return original(path);
  });
}
function installShopStock(catalogVersion = "5:5", memberIds = ["1001", "1002"]) {
  installWarehouseCenterMocks({ warehouses: [{ ...readyWarehouse, inventory_product_scope: { state: "ready", warehouse_id: "1", report_source_scope_id: "7", catalog_version: "5:5", sku_ids: memberIds } }] });
  const original = api.read.getMockImplementation()!;
  api.read.mockImplementation(path => path === "/api/production/skus?contract_version=2"
    ? Promise.resolve({ items: catalogItems.map(sku => ({ ...sku, catalog_version: catalogVersion })) }) : original(path));
}
it("partitions shop stock without new reads and preserves filters, detail and operation returns", async () => {
  installShopStock();
  const router = mount("warehouses", "/production/warehouses/1?owner=1");
  const table = await screen.findByRole("table", { name: "本仓款色尺码库存" });
  expect(screen.getByRole("button", { name: "广州店商品" })).toHaveAttribute("aria-pressed", "true");
  expect(screen.getByText("在库", { selector: "span" }).parentElement).toHaveTextContent("6");
  expect(within(table).queryByText("White")).not.toBeInTheDocument();
  await userEvent.click(within(table).getByRole("button", { name: /Blue M 库存明细/ }));
  expect(screen.getByRole("region", { name: "规格库存明细" })).toBeInTheDocument();
  const reads = api.read.mock.calls.length;
  await userEvent.click(screen.getByRole("button", { name: "其他成品" }));
  expect(screen.queryByRole("region", { name: "规格库存明细" })).not.toBeInTheDocument();
  expect(within(table).getByText("White")).toBeInTheDocument();
  expect(within(table).queryByText("Blue")).not.toBeInTheDocument();
  expect(screen.getByText("在库", { selector: "span" }).parentElement).toHaveTextContent("1");
  expect(api.read).toHaveBeenCalledTimes(reads);
  expect(api.write).not.toHaveBeenCalled();
  expect(new URLSearchParams(router.state.location.search).get("stock_goods")).toBe("other");
  for (const label of ["入库", "出货"]) {
    const url = new URL(screen.getByRole("link", { name: label }).getAttribute("href")!, "http://localhost");
    expect(url.searchParams.get("return_to")).toContain("stock_goods=other");
  }
  await userEvent.type(screen.getByLabelText("搜索本仓款号、颜色或尺码"), "White");
  await userEvent.click(screen.getByRole("button", { name: "广州店商品" }));
  expect(screen.getByLabelText("搜索本仓款号、颜色或尺码")).toHaveValue("White");
  expect(within(table).getByText("没有匹配的商品")).toBeInTheDocument();
  expect(screen.getByText("在库", { selector: "span" }).parentElement).toHaveTextContent("0");
  await act(async () => { await router.navigate(-1); });
  expect(screen.getByRole("button", { name: "其他成品" })).toHaveAttribute("aria-pressed", "true");
});
it("keeps read-only filtering and treats an approved empty shop as a valid complement", async () => {
  installShopStock("5:5", []);
  mount("warehouses", "/production/warehouses/1?stock_goods=other", false);
  const table = await screen.findByRole("table", { name: "本仓款色尺码库存" });
  expect(within(table).getByText("White")).toBeInTheDocument();
  expect(screen.getByText("在库", { selector: "span" }).parentElement).toHaveTextContent("7");
  expect(screen.queryByRole("link", { name: "入库" })).not.toBeInTheDocument();
  await userEvent.click(screen.getByRole("button", { name: "广州店商品" }));
  expect(within(table).getByText("没有匹配的商品")).toBeInTheDocument();
  expect(api.write).not.toHaveBeenCalled();
});
it("does not classify a mismatched catalog publication as other goods", async () => {
  installShopStock("6:6");
  mount("warehouses", "/production/warehouses/1?stock_goods=other");
  expect(await screen.findByText("商品目录已变化，请刷新仓库。")).toBeInTheDocument();
  expect(screen.queryByRole("table", { name: "本仓款色尺码库存" })).not.toBeInTheDocument();
  expect(screen.queryByRole("link", { name: "入库" })).not.toBeInTheDocument();
});
function mount(kind: "factories" | "warehouses", path: string, canWrite = true) {
  const roles = canWrite ? ["admin" as const] : ["viewer" as const];
  const router = createMemoryRouter([{ path: "/production/" + kind + "/:directoryId?", element: <AuthzGenerationProvider boundary={{ principalId: 88, roles, siteConfigVersionId: 1, siteId: 1 }} onRevoked={() => undefined}><DirectoryWorkspace kind={kind} canWrite={canWrite} /></AuthzGenerationProvider> }, {path:"/production/shipments/new",element:<p>统一仓库出货</p>}, {path:"/production/orders/receipts/new",element:<p>统一批量入库</p>}], { initialEntries: [path] });
  render(<RouterProvider router={router} />); return router;
}
beforeEach(() => {
  const NativeRequest = globalThis.Request;
  vi.stubGlobal("Request", class extends NativeRequest { constructor(input: RequestInfo | URL, init?: RequestInit) { const { signal, ...options } = init ?? {}; super(input, options); if (signal) Object.defineProperty(this, "signal", { value: signal }); } });
  api.read.mockReset(); api.write.mockReset();
  api.read.mockImplementation(async (path: string) => {
    await Promise.resolve();
    if (path.endsWith("/capabilities")) return {scopes:[{id:7,seller_account_display_name:"示例卖家",marketplace_scope_code:"amazon_us"}]};
    if (path.endsWith("/workbench")) return { directory_supported: true };
    if (path === "/api/production/warehouses/900") return warehouse;
    if (path.startsWith("/api/production/warehouses?")) return { items: [warehouse], total: 1, page: 1, page_size: 50 };
    if (path.startsWith("/api/production/factories?")) return { items: [], total: 0, page: 1, page_size: 50 };
    if (path.includes("inventory/availability")) return { items: [], scopes: [], writes_enabled: true, opening_enabled: false };
    if (path.includes("/skus")) return { items: [] };
    throw Error("Unexpected request " + path);
  });
});
afterEach(() => { cleanup(); vi.unstubAllGlobals(); });
async function fillQualityWizard() {
  installWarehouseCenterMocks();
  const router = mount("warehouses", "/production/warehouses/1?owner=1&q=广州&tab=adjust&adjust_view=quality&operation=new&editor=1&sku_id=1001");
  const dialog = await screen.findByRole("dialog", { name: "登记质量变化" });
  await within(dialog).findByRole("option", { name: "短袖T恤 Blue M" });
  await userEvent.click(within(dialog).getByRole("button", { name: "下一步" }));
  await userEvent.selectOptions(within(dialog).getByLabelText(/^货品状态/), "QUALIFIED");
  await userEvent.selectOptions(within(dialog).getByLabelText(/^目标货品状态/), "PENDING");
  await userEvent.type(within(dialog).getByLabelText(/^本次件数/), "1");
  await userEvent.click(within(dialog).getByRole("button", { name: "下一步" }));
  await userEvent.type(within(dialog).getByLabelText(/^来源依据/), "虚构：重新检验1件");
  return { dialog, router };
}
it("quality wizard saves, previews, invalidates an edited preview and confirms exactly once", async () => {
  const { dialog, router } = await fillQualityWizard();
  let revision = 0;
  api.write.mockImplementation(path => Promise.resolve(path.endsWith("/preview") ? { id: "51", revision: String(revision), preview_hash: `preview-${revision}`, impacts: [{ warehouse_id: "1", sku_id: "1001", on_hand_before: "4", on_hand_after: "4", free_before: "3", free_after: "2" }], changes: [{ sku_id: "1001", quality: "QUALIFIED", delta_units: "-1" }, { sku_id: "1001", quality: "PENDING", delta_units: "1" }] } : path.endsWith("/confirm") ? { id: "51", status: "POSTED", revision: "3" } : { id: "51", status: "DRAFT", revision: String(++revision) }));
  await userEvent.click(within(dialog).getByRole("button", { name: "保存草稿并核对" }));
  await within(dialog).findByRole("table", { name: "库存变化预览" });
  await waitFor(() => expect(new URLSearchParams(router.state.location.search).get("wizard_draft")).toBe("51"));
  expect(api.write.mock.calls.map(([path]) => path)).toEqual(["/api/production/inventory/documents", "/api/production/inventory/documents/51/preview"]);
  await userEvent.click(within(dialog).getByRole("button", { name: "返回修改" }));
  expect(within(dialog).getByLabelText(/^本次件数/)).toHaveValue("1");
  await userEvent.clear(within(dialog).getByLabelText(/^本次件数/)); await userEvent.type(within(dialog).getByLabelText(/^本次件数/), "2");
  expect(within(dialog).queryByRole("table", { name: "库存变化预览" })).not.toBeInTheDocument();
  await userEvent.click(within(dialog).getByRole("button", { name: "下一步" }));
  await userEvent.click(within(dialog).getByRole("button", { name: "保存草稿并核对" }));
  await within(dialog).findByRole("table", { name: "库存变化预览" });
  expect(api.write.mock.calls[2]?.[0]).toBe("/api/production/inventory/documents/51/update");
  expect(api.write.mock.calls[2]?.[1].body).toMatchObject({ expected_revision: "1", lines: [{ units: "2" }] });
  await userEvent.click(within(dialog).getByRole("button", { name: "确认将2件合格转为待检" }));
  await waitFor(() => expect(screen.queryByRole("dialog", { name: "登记质量变化" })).not.toBeInTheDocument());
  expect(api.write.mock.calls.filter(([path]) => path.endsWith("/confirm"))).toHaveLength(1);
  expect(api.write.mock.calls.at(-1)?.[1].body).toMatchObject({ expected_revision: "2", preview_hash: "preview-2" });
  expect(new URLSearchParams(router.state.location.search).get("q")).toBe("广州");
});
it("quality wizard keeps unsaved input when closing is declined", async () => {
  const { dialog } = await fillQualityWizard();
  await userEvent.click(within(dialog).getByRole("button", { name: "关闭质量登记" }));
  const guard = await screen.findByRole("dialog", { name: "还有未保存的内容" });
  await userEvent.click(within(guard).getByRole("button", { name: "继续填写" }));
  expect(within(dialog).getByLabelText(/^来源依据/)).toHaveValue("虚构：重新检验1件");
  expect(api.write).not.toHaveBeenCalled();
});
it("quality wizard shows scoped stock states and blocks a quantity above the selected source", async () => {
  installWarehouseCenterMocks();
  mount("warehouses", "/production/warehouses/1?tab=adjust&adjust_view=quality&operation=new&editor=1&sku_id=1001");
  const dialog = await screen.findByRole("dialog", { name: "登记质量变化" });
  await within(dialog).findByRole("option", { name: "短袖T恤 Blue M" });
  await userEvent.click(within(dialog).getByRole("button", { name: "下一步" }));
  const inventory = within(dialog).getByRole("region", { name: "当前库存状态" });
  expect(inventory).toHaveTextContent("实际在库4件");
  expect(inventory).toHaveTextContent("当前可发3件");
  expect(inventory).toHaveTextContent("合格4件");
  expect(inventory).toHaveTextContent("待检0件");
  await userEvent.selectOptions(within(dialog).getByLabelText(/^货品状态/), "PENDING");
  await userEvent.selectOptions(within(dialog).getByLabelText(/^目标货品状态/), "QUALIFIED");
  await userEvent.type(within(dialog).getByLabelText(/^本次件数/), "2");
  expect(within(dialog).getByLabelText(/^本次件数/)).toHaveAttribute("aria-invalid", "true");
  expect(within(dialog).getByText(/当前待检仅0件/)).toBeInTheDocument();
  await userEvent.click(within(dialog).getByRole("button", { name: "下一步" }));
  expect(within(dialog).getByRole("heading", { name: "填写状态与数量" })).toBeInTheDocument();
  expect(within(dialog).getByLabelText(/^本次件数/)).toHaveFocus();
  expect(api.write).not.toHaveBeenCalled();
  await userEvent.selectOptions(within(dialog).getByLabelText(/^货品状态/), "QUALIFIED");
  await userEvent.selectOptions(within(dialog).getByLabelText(/^目标货品状态/), "PENDING");
  expect(within(dialog).getByLabelText(/^本次件数/)).not.toHaveAttribute("aria-invalid", "true");
  await userEvent.click(within(dialog).getByRole("button", { name: "上一步" }));
  await userEvent.selectOptions(within(dialog).getByLabelText(/^商品颜色与尺码/), "1002");
  expect(within(dialog).getByRole("region", { name: "当前库存状态" })).toHaveTextContent("实际在库2件");
  expect(within(dialog).getByRole("region", { name: "当前库存状态" })).not.toHaveTextContent("合格4件");
});
it("quality wizard checks combined source changes across lines before saving", async () => {
  installWarehouseCenterMocks();
  mount("warehouses", "/production/warehouses/1?tab=adjust&adjust_view=quality&operation=new&editor=1&sku_id=1001");
  const dialog = await screen.findByRole("dialog", { name: "登记质量变化" });
  await within(dialog).findByRole("option", { name: "短袖T恤 Blue M" });
  await userEvent.click(within(dialog).getByRole("button", { name: "增加商品" }));
  await userEvent.selectOptions(within(dialog).getAllByLabelText(/^商品颜色与尺码/)[1]!, "1001");
  await userEvent.click(within(dialog).getByRole("button", { name: "下一步" }));
  const sources = within(dialog).getAllByLabelText(/^货品状态/);
  const targets = within(dialog).getAllByLabelText(/^目标货品状态/);
  const amounts = within(dialog).getAllByLabelText(/^本次件数/);
  for (let i = 0; i < 2; i++) { await userEvent.selectOptions(sources[i]!, "QUALIFIED"); await userEvent.selectOptions(targets[i]!, i ? "DEFECTIVE" : "PENDING"); await userEvent.type(amounts[i]!, "3"); }
  expect(within(dialog).getAllByText(/同商品本次从合格净转出6件，当前仅4件/)).toHaveLength(2);
  await userEvent.click(within(dialog).getByRole("button", { name: "下一步" }));
  expect(api.write).not.toHaveBeenCalled();
  await userEvent.clear(amounts[1]!); await userEvent.type(amounts[1]!, "1");
  await userEvent.click(within(dialog).getByRole("button", { name: "下一步" }));
  expect(within(dialog).getByRole("heading", { name: "日期与依据" })).toBeInTheDocument();
});
it("quality wizard refreshes stock without losing quantities and distinguishes read failures", async () => {
  const { dialog } = await fillQualityWizard();
  await userEvent.click(within(dialog).getByRole("button", { name: "上一步" }));
  const original = api.read.getMockImplementation()!;
  let mode = "error";
  api.read.mockImplementation(async path => {
    if (path === "/api/production/inventory/availability") {
      if (mode === "error") throw Error("虚构库存读取暂时失败");
      return { items: [{ ...stockItems[0], qualified_units: "0", pending_units: "4" }, { ...stockItems[0], owner_id: "9", qualified_units: "99" }], scopes: readyWarehouse.scopes };
    }
    return original(path);
  });
  await userEvent.click(within(dialog).getByRole("button", { name: "刷新库存" }));
  await within(dialog).findByText("库存读取失败，请刷新后核对；未将未知数量当作0。");
  expect(within(dialog).getByLabelText(/^本次件数/)).toHaveValue("1");
  expect(within(dialog).getByRole("region", { name: "当前库存状态" })).not.toHaveTextContent("合格0件");
  mode = "ready";
  await userEvent.click(within(dialog).getByRole("button", { name: "刷新库存" }));
  await within(dialog).findByText(/当前合格仅0件/);
  expect(within(dialog).getByRole("region", { name: "当前库存状态" })).not.toHaveTextContent("99件");
  expect(within(dialog).getByLabelText(/^本次件数/)).toHaveValue("1");
  expect(api.write).not.toHaveBeenCalled();
});
it("quality wizard resumes the saved draft after reload and checks its owner", async () => {
  const draft = { id: "51", kind: "MOVE", warehouse_id: "1", owner_id: "1", status: "DRAFT", revision: "2", business_date: "2026-10-26", reason: "已保存的虚构依据", lines: [{ sku_id: "1001", quality: "QUALIFIED", target_quality: "PENDING", purpose: "QUALITY", units: "2" }] };
  installWarehouseCenterMocks({ documents: [draft] });
  mount("warehouses", "/production/warehouses/1?tab=adjust&adjust_view=quality&operation=new&editor=1&wizard_draft=51");
  const dialog = await screen.findByRole("dialog", { name: "登记质量变化" });
  await userEvent.click(within(dialog).getByRole("button", { name: "下一步" }));
  expect(within(dialog).getByLabelText(/^本次件数/)).toHaveValue("2");
  await userEvent.click(within(dialog).getByRole("button", { name: "下一步" }));
  expect(within(dialog).getByLabelText(/^来源依据/)).toHaveValue("已保存的虚构依据");
  api.write.mockRejectedValueOnce(new ApiRequestError(409, "test_stop", "保留草稿修订"));
  await userEvent.click(within(dialog).getByRole("button", { name: "保存草稿并核对" }));
  await within(dialog).findByText("保留草稿修订");
  expect(api.write.mock.calls[0]?.[0]).toBe("/api/production/inventory/documents/51/update");
  expect(api.write.mock.calls[0]?.[1].body.expected_revision).toBe("2");
  await userEvent.click(within(dialog).getByRole("button", { name: "关闭质量登记" }));
  await waitFor(() => expect(screen.queryByRole("dialog", { name: "登记质量变化" })).not.toBeInTheDocument());
  await userEvent.click(screen.getByRole("button", { name: "登记变化" }));
  const fresh = await screen.findByRole("dialog", { name: "登记质量变化" });
  expect(within(fresh).getByLabelText(/^商品颜色与尺码/)).toHaveValue("");
});
it("quality wizard never opens a resumed draft from another owner", async () => {
  installWarehouseCenterMocks({ documents: [{ id: "51", kind: "MOVE", warehouse_id: "1", owner_id: "9", status: "POSTED", revision: "2", business_date: "2026-10-26", reason: "其他货权", lines: [] }] });
  mount("warehouses", "/production/warehouses/1?tab=adjust&adjust_view=quality&operation=new&editor=1&wizard_draft=51");
  await screen.findByText("单据不属于当前仓库及货主");
  expect(screen.queryByRole("dialog", { name: "登记质量变化" })).not.toBeInTheDocument();
  expect(api.write).not.toHaveBeenCalled();
});
it("quality wizard retries only a failed preview and locks dismissal for an unknown save", async () => {
  const { dialog } = await fillQualityWizard();
  api.write.mockResolvedValueOnce({ id: "51", status: "DRAFT", revision: "1" }).mockRejectedValueOnce(new ApiRequestError(409, "stale_preview", "库存已变化，请重新核对"));
  await userEvent.click(within(dialog).getByRole("button", { name: "保存草稿并核对" }));
  await within(dialog).findByText("库存已变化，请重新核对");
  expect(within(dialog).queryByRole("button", { name: /^确认将/ })).not.toBeInTheDocument();
  api.write.mockRejectedValueOnce(new ApiRequestError(503, "unavailable", "预览结果未知"));
  await userEvent.click(within(dialog).getByRole("button", { name: "重新预览" }));
  await within(dialog).findByText("预览结果未知");
  expect(api.write.mock.calls.filter(([path]) => path === "/api/production/inventory/documents")).toHaveLength(1);
  expect(within(dialog).getByRole("button", { name: "关闭质量登记" })).toBeDisabled();
  expect(within(dialog).getByRole("button", { name: "查询原操作结果" })).toBeEnabled();
});
it("keeps receipt completion while the same source order refreshes in the warehouse panel", async () => {
  installWarehouseCenterMocks();
  const source = { id: "10", revision: "2", status: "CONFIRMED", business_number: "QA-RECEIPT", receipt_warehouse_id: "1", receipt_owner_id: "1", lines: [{ id: "101", sku_id: "1001", sku_label: "QA-M", expected_units: "4", received_units: "0" }] };
  const original = api.read.getMockImplementation()!;
  let resolveSource!: (value: typeof source) => void;
  const pending = new Promise<typeof source>(resolve => { resolveSource = resolve; });
  let reads = 0;
  api.read.mockImplementation(path => path === "/api/production/orders/10" ? ++reads === 2 ? pending : Promise.resolve(source) : path.startsWith("/api/production/orders?") ? Promise.resolve({ items: [source], total: 1, page: 1 }) : original(path));
  api.write.mockImplementation(path => Promise.resolve(path.endsWith("/confirm") ? { id: "52", revision: "2", status: "POSTED" } : path.endsWith("/preview") ? { id: "52", revision: "1", preview_hash: "qa-preview", impacts: [] } : { id: "52", revision: "1", status: "DRAFT" }));
  mount("warehouses", "/production/warehouses/1?tab=records&receive=1&mode=receive&source_order=10");
  const dialog = await screen.findByRole("dialog", { name: "入库" });
  const receiptSteps = await within(dialog).findByRole("list", { name: "操作步骤" });
  for (const label of ["核对入库仓库", "填写实收明细", "日期与依据", "核对并确认"]) expect(within(receiptSteps).getByText(label)).toBeInTheDocument();
  await userEvent.click(within(dialog).getByRole("button", { name: "下一步" }));
  await userEvent.type(await screen.findByLabelText("QA-M本次合格"), "1");
  await userEvent.click(within(dialog).getByRole("button", { name: "下一步" }));
  await userEvent.type(screen.getByLabelText(/入库依据 \/ 备注/), "虚构收货");
  await userEvent.click(within(dialog).getByRole("button", { name: "下一步" }));
  await userEvent.click(within(dialog).getByRole("button", { name: "保存草稿并预览" }));
  await userEvent.click(await within(dialog).findByRole("button", { name: "确认本次入库" }));
  expect(await screen.findByText("本批入库已确认")).toBeInTheDocument();
  await act(async () => { resolveSource({ ...source, revision: "3" }); await pending; });
  await waitFor(() => expect(screen.getByRole("button", { name: "登记下一批入库" })).toBeEnabled());
  expect(screen.queryByRole("button", { name: "确认本次入库" })).not.toBeInTheDocument();
});
it("keeps production and receipt facts visible without turning unknown production into zero", async () => {
  installWarehouseCenterMocks();
  const source = { id: "10", revision: "2", status: "CONFIRMED", business_number: "QA-RECEIPT-REFERENCE", factory_name: "虚构制衣厂", receipt_warehouse_id: "1", receipt_owner_id: "1", expected_units: "4", received_units: "1", actual_units: "0", lines: [{ id: "101", sku_id: "1001", sku_label: "QA-M", expected_units: "4", produced_units: null, received_units: "1", actual_units: "0", difference_units: "4" }] };
  const original = api.read.getMockImplementation()!;
  api.read.mockImplementation(path => path === "/api/production/orders/10" ? Promise.resolve(source) : path.startsWith("/api/production/orders?") ? Promise.resolve({ items: [source], total: 1, page: 1 }) : path.includes("inventory/availability?") && path.includes("sku_id=") ? Promise.resolve({ state: "ready", on_hand_units: "10", dispatch_allowed_units: "8", own_reserved_units: "0" }) : original(path));
  mount("warehouses", "/production/warehouses/1?tab=records&receive=1&mode=receive&source_order=10");
  const dialog = await screen.findByRole("dialog", { name: "入库" });
  expect(await within(dialog).findByRole("link", { name: "查看生产单" })).toHaveAttribute("href", "/production/orders/10");
  expect(within(dialog).getByRole("button", { name: "更换生产单" })).toBeInTheDocument();
  const reference = within(dialog).getByRole("region", { name: "入库业务参照" });
  expect(reference).toHaveTextContent("下单计划4件");
  expect(reference).toHaveTextContent("累计生产未登记");
  expect(reference).toHaveTextContent("累计已入库1件");
  expect(reference).toHaveTextContent("订单未交数量3件");
  expect(reference).not.toHaveTextContent("累计生产0件");
  await userEvent.click(within(dialog).getByRole("button", { name: "下一步" }));
  expect(within(dialog).getByRole("button", { name: "导入表格" })).toBeInTheDocument();
  expect(within(dialog).getByRole("region", { name: "入库业务参照" })).toHaveTextContent("累计已入库1件");
  const row = within(dialog).getByRole("row", { name: /QA-M/ });
  expect(row).toHaveTextContent("QA-M4未登记1");
  await userEvent.click(within(dialog).getByText("库存参照", { exact: true }));
  const inventory = await within(dialog).findByRole("table", { name: "本仓当前库存" });
  await userEvent.type(within(dialog).getByLabelText("QA-M本次合格"), "1");
  expect(within(inventory).getByRole("row", { name: /QA-M/ })).toHaveTextContent("QA-M10");
  expect(within(dialog).getByLabelText("QA-M已入库1件，确认后2件")).toBeInTheDocument();
});
it("shows over-receipt against the order before and after the current receipt", async () => {
  installWarehouseCenterMocks();
  const source = { id: "10", revision: "2", status: "CONFIRMED", business_number: "QA-RECEIPT-OVER", factory_name: "虚构制衣厂", receipt_warehouse_id: "1", receipt_owner_id: "1", expected_units: "2", received_units: "7", actual_units: "0", lines: [{ id: "101", sku_id: "1001", sku_label: "QA-M", expected_units: "2", produced_units: "2", received_units: "7", actual_units: "0", difference_units: "0" }] };
  const original = api.read.getMockImplementation()!;
  api.read.mockImplementation(path => path === "/api/production/orders/10" ? Promise.resolve(source) : path.startsWith("/api/production/orders?") ? Promise.resolve({ items: [source], total: 1, page: 1 }) : original(path));
  mount("warehouses", "/production/warehouses/1?tab=records&receive=1&mode=receive&source_order=10");
  const dialog = await screen.findByRole("dialog", { name: "入库" });
  expect(await within(dialog).findByRole("region", { name: "入库业务参照" })).toHaveTextContent("订单未交数量超额入库 5件");
  await userEvent.click(within(dialog).getByRole("button", { name: "下一步" }));
  await userEvent.type(within(dialog).getByLabelText("QA-M本次合格"), "1");
  await userEvent.click(within(dialog).getByRole("button", { name: "下一步" }));
  await userEvent.type(within(dialog).getByLabelText(/入库依据 \/ 备注/), "虚构超收核对");
  await userEvent.click(within(dialog).getByRole("button", { name: "下一步" }));
  expect(within(within(dialog).getByRole("table", { name: "本次实收核对" })).getByRole("row", { name: /QA-M/ })).toHaveTextContent("超额入库 6件");
});
it("guides a warehouse shipment through destination, quantity and cartons before saving a draft", async () => {
  installWarehouseCenterMocks();
  const source = { id: "10", revision: "2", status: "CONFIRMED", business_number: "QA-SHIP", receipt_warehouse_id: "1", receipt_owner_id: "1", destination: "虚构海外仓", lines: [{ id: "101", sku_id: "1001", sku_label: "QA-M", expected_units: "4", actual_units: "0", tracking_state: "OPEN" }] };
  const original = api.read.getMockImplementation()!;
  api.read.mockImplementation(path => path === "/api/production/orders/10" ? Promise.resolve(source) : path.startsWith("/api/production/orders?") ? Promise.resolve({ items: [source], total: 1, page: 1 }) : path.includes("inventory/availability?") && path.includes("sku_id=") ? Promise.resolve({ state: "ready", dispatch_allowed_units: "4", own_reserved_units: "0" }) : original(path));
  api.write.mockResolvedValue({ id: "70", revision: "1", status: "DRAFT", business_number: "S-QA", system_number: "S-QA", business_date: "2026-10-26", warehouse_id: "1", owner_id: "1", destination: "虚构海外仓", sources: [{ sku_id: "1001", actual_units: "2", fulfillment_mode: "WAREHOUSE_STOCK", allocations: [{ order_line_id: "101", units: "2" }] }], cartons: [{ number: "QA-BOX", items: [{ sku_id: "1001", units: "2" }] }] });
  mount("warehouses", "/production/warehouses/1?tab=records&ship=1&mode=ship&source_order=10");
  const dialog = await screen.findByRole("dialog", { name: "新建出货单" });
  const shipmentSteps = await within(dialog).findByRole("list", { name: "操作步骤" });
  for (const label of ["来源与目的地", "填写出货数量", "完成装箱", "核对并发货"]) expect(within(shipmentSteps).getByText(label)).toBeInTheDocument();
  await userEvent.click(within(dialog).getByRole("button", { name: "下一步" }));
  await userEvent.type(await screen.findByLabelText("QA-M本次出货"), "2");
  await userEvent.click(within(dialog).getByRole("button", { name: "下一步" }));
  await userEvent.type(screen.getByLabelText("第1箱箱号"), "QA-BOX");
  await userEvent.type(screen.getByLabelText("第1箱QA-M装箱数"), "2");
  await userEvent.click(within(dialog).getByRole("button", { name: "下一步" }));
  expect(within(within(dialog).getByRole("table", { name: "本次出货与装箱核对" })).getByRole("row", { name: /QA-M/ })).toHaveTextContent("QA-M0件2件2件2件2件 · 一致");
  await userEvent.click(within(dialog).getByRole("button", { name: "保存装箱草稿" }));
  await waitFor(() => expect(api.write).toHaveBeenCalledTimes(1));
  expect(api.write.mock.calls[0]![0]).toBe("/api/production/shipments");
  expect(api.write.mock.calls[0]![1].body).toMatchObject({ save_mode: "draft", destination: "虚构海外仓", cartons: [{ number: "QA-BOX", items: [{ sku_id: "1001", units: "2" }] }] });
  expect(api.write.mock.calls.some(([path]) => path.endsWith("/confirm"))).toBe(false);
});
it("shows shipment progress, current stock and the result after this shipment", async () => {
  installWarehouseCenterMocks();
  const source = { id: "10", revision: "2", status: "CONFIRMED", business_number: "QA-SHIP-REFERENCE", receipt_warehouse_id: "1", receipt_owner_id: "1", destination: "虚构海外仓", expected_units: "10", actual_units: "3", difference_units: "7", lines: [{ id: "101", sku_id: "1001", sku_label: "QA-M", expected_units: "10", actual_units: "3", difference_units: "7", produced_units: "9", received_units: "8", tracking_state: "OPEN" }] };
  const original = api.read.getMockImplementation()!;
  api.read.mockImplementation(path => path === "/api/production/orders/10" ? Promise.resolve(source) : path.startsWith("/api/production/orders?") ? Promise.resolve({ items: [source], total: 1, page: 1 }) : path.includes("inventory/availability?") && path.includes("sku_id=") ? Promise.resolve({ state: "ready", on_hand_units: "12", dispatch_allowed_units: "8", own_reserved_units: "1" }) : original(path));
  mount("warehouses", "/production/warehouses/1?tab=records&ship=1&mode=ship&source_order=10");
  const dialog = await screen.findByRole("dialog", { name: "新建出货单" });
  const reference = within(dialog).getByRole("region", { name: "出货业务参照" });
  expect(reference).toHaveTextContent("下单计划10件");
  expect(reference).toHaveTextContent("累计已发3件");
  expect(reference).toHaveTextContent("订单差额7件");
  expect(reference).toHaveTextContent("计划目的地虚构海外仓");
  await userEvent.click(within(dialog).getByRole("button", { name: "下一步" }));
  const row = within(dialog).getByRole("row", { name: /QA-M/ });
  expect(row).toHaveTextContent("计划10件已发3件差额7件");
  const inventory = within(row).getByLabelText("本仓库存参照");
  expect(inventory).toHaveTextContent("实际在库12件");
  expect(inventory).toHaveTextContent("当前可发8件");
  await userEvent.type(within(dialog).getByLabelText("QA-M本次出货"), "2");
  expect(inventory).toHaveTextContent("本次后可发 6件");
  expect(row).toHaveTextContent("本次后差额5件");
});
it("does not show zero when the shipment stock reference failed to load", async () => {
  installWarehouseCenterMocks();
  const source = { id: "10", revision: "2", status: "CONFIRMED", business_number: "QA-SHIP-STOCK-ERROR", receipt_warehouse_id: "1", receipt_owner_id: "1", destination: "虚构海外仓", lines: [{ id: "101", sku_id: "1001", sku_label: "QA-M", expected_units: "4", actual_units: "0", difference_units: "4", tracking_state: "OPEN" }] };
  const original = api.read.getMockImplementation()!;
  api.read.mockImplementation(path => path === "/api/production/orders/10" ? Promise.resolve(source) : path.startsWith("/api/production/orders?") ? Promise.resolve({ items: [source], total: 1, page: 1 }) : path.includes("inventory/availability?") && path.includes("sku_id=") ? Promise.reject(Error("虚构库存读取失败")) : original(path));
  mount("warehouses", "/production/warehouses/1?tab=records&ship=1&mode=ship&source_order=10");
  const dialog = await screen.findByRole("dialog", { name: "新建出货单" });
  await userEvent.click(await within(dialog).findByRole("button", { name: "下一步" }));
  expect(await within(dialog).findByText("库存读取失败，未显示为0。虚构库存读取失败")).toBeInTheDocument();
});
it.each(["factories", "warehouses"] as const)("synchronizes the %s search with applied filters on back and forward", async kind => {
  const label = kind === "factories" ? "搜索工厂名称或编号" : "搜索仓库名称或编号";
  const router = mount(kind, `/production/${kind}?q=first`);
  const search = await screen.findByLabelText(label);
  await userEvent.clear(search);
  await userEvent.type(search, "second");
  if (kind === "warehouses") await userEvent.type(search, "{Enter}");
  else await userEvent.click(screen.getByRole("button", { name: "查找" }));
  expect(new URLSearchParams(router.state.location.search).get("q")).toBe("second");
  await act(async () => { await router.navigate(-1); });
  expect(search).toHaveValue("first");
  await act(async () => { await router.navigate(1); });
  expect(search).toHaveValue("second");
  expect(api.write).not.toHaveBeenCalled();
});
it("clears an unfinished stocktake operation when leaving the adjustment tab", async () => {
  installWarehouseCenterMocks();
  const router = mount("warehouses", "/production/warehouses/1?owner=1&tab=adjust&adjust_view=count&operation=new&editor=1");
  const dialog = await screen.findByRole("dialog", { name: "登记盘点" });
  await within(dialog).findByRole("option", { name: "短袖T恤 Blue M" });
  const product = within(dialog).getByLabelText("盘点商品1", { exact: true });
  await userEvent.selectOptions(product, "1001");
  await userEvent.click(within(dialog).getByRole("button", { name: "关闭盘点登记" }));
  expect(await screen.findByRole("dialog", { name: "还有未保存的内容" })).toBeInTheDocument();
  await userEvent.click(screen.getByRole("button", { name: "继续填写" }));
  expect(product).toHaveValue("1001");
  await userEvent.click(within(dialog).getByRole("button", { name: "关闭盘点登记" }));
  await userEvent.click(await screen.findByRole("button", { name: "放弃并离开" }));
  expect(new URLSearchParams(router.state.location.search).has("operation")).toBe(false);
  expect(screen.queryByRole("dialog", { name: "登记盘点" })).not.toBeInTheDocument();
  await userEvent.click(screen.getByRole("button", { name: "收发记录" }));
  expect(await screen.findByRole("heading", { name: "选择入库记录或新建入库" })).toBeInTheDocument();
  expect(api.write).not.toHaveBeenCalled();
});
it("does not interpret a stale stocktake URL flag as a new receipt operation", async () => {
  installWarehouseCenterMocks();
  mount("warehouses", "/production/warehouses/1?owner=1&tab=records&operation=new");
  expect(await screen.findByRole("heading", { name: "选择入库记录或新建入库" })).toBeInTheDocument();
  expect(screen.queryByRole("button", { name: "保存库存草稿" })).not.toBeInTheDocument();
  expect(api.write).not.toHaveBeenCalled();
});
it("reinitializes an empty editor when the stocktake context changes to quality movement", async () => {
  installWarehouseCenterMocks();
  const router = mount("warehouses", "/production/warehouses/1?owner=1&tab=adjust&adjust_view=count&operation=new&editor=1");
  await screen.findByRole("dialog", { name: "登记盘点" });
  await act(async () => { await router.navigate("/production/warehouses/1?owner=1&tab=adjust&adjust_view=quality&operation=new&editor=1"); });
  expect(await screen.findByRole("dialog", { name: "登记质量变化" })).toBeInTheDocument();
  expect(screen.queryByLabelText(/^本次操作/)).not.toBeInTheDocument();
  expect(screen.queryByLabelText(/^来源库位/)).not.toBeInTheDocument();
  expect(screen.queryByLabelText(/实际盘点件数/)).not.toBeInTheDocument();
  expect(api.write).not.toHaveBeenCalled();
});
it("does not flash an empty-factory guide until the first list has completed", async () => {
  const original = api.read.getMockImplementation()!;
  let resolveList!: (value: { items: DirectoryRecord[]; total: number; page: number }) => void;
  const pending = new Promise<{ items: DirectoryRecord[]; total: number; page: number }>(resolve => { resolveList = resolve; });
  api.read.mockImplementation(path => path.startsWith("/api/production/factories?") ? pending : original(path));
  mount("factories", "/production/factories", false);
  await screen.findByLabelText("搜索工厂名称或编号");
  expect(screen.queryByRole("heading", { name: "从一家工厂开始" })).not.toBeInTheDocument();
  await act(async () => { resolveList({ items: [], total: 0, page: 1 }); await pending; });
  expect(await screen.findByRole("heading", { name: "从一家工厂开始" })).toBeInTheDocument();
});
it.each(["warehouses", "factories"] as const)("keeps the %s chooser mounted while loading a different record", async kind => {
  const records = kind === "warehouses" ? [readyWarehouse, warehouse] : [
    { ...warehouse, id: "7", name: "虚构甲厂", type: undefined, warehouse_ids: [] },
    { ...warehouse, id: "8", name: "虚构乙厂", type: undefined, warehouse_ids: [] },
  ];
  const original = api.read.getMockImplementation()!;
  let resolveDetail!: (value: DirectoryRecord) => void;
  const nextDetail = new Promise<DirectoryRecord>(resolve => { resolveDetail = resolve; });
  api.read.mockImplementation(path => {
    if (path.startsWith(`/api/production/${kind}?`)) return Promise.resolve({ items: records, total: 2, page: 1 });
    if (path === `/api/production/${kind}/${records[0]!.id}`) return Promise.resolve(records[0]);
    if (path === `/api/production/${kind}/${records[1]!.id}`) return nextDetail;
    if (path.startsWith("/api/production/orders?")) return Promise.resolve({ items: [], total: 0, page: 1 });
    return original(path);
  });
  const router = createMemoryRouter([{ path: "/production/*", element: <AuthzGenerationProvider boundary={{ principalId: 88, roles: ["viewer"], siteConfigVersionId: 1, siteId: 1 }} onRevoked={() => undefined}><ProductionWorkspace canWrite={false} /></AuthzGenerationProvider> }], { initialEntries: [`/production/${kind}`] });
  render(<RouterProvider router={router} />);
  await screen.findByRole("heading", { name: new RegExp(records[0]!.name) });
  const chooser = screen.getByRole("link", { name: new RegExp(records[1]!.name) });
  const searchLabel = kind === "warehouses" ? "搜索仓库名称或编号" : "搜索工厂名称或编号";
  const search = screen.getByLabelText(searchLabel);
  await userEvent.type(search, "未提交的查找");
  await userEvent.click(chooser);
  expect(screen.getByRole("link", { name: new RegExp(records[1]!.name) })).toBe(chooser);
  expect(screen.getByLabelText(searchLabel)).toBe(search);
  expect(search).toHaveValue("未提交的查找");
  expect(screen.queryByRole("heading", { name: new RegExp(records[0]!.name) })).not.toBeInTheDocument();
  expect(api.read.mock.calls.filter(([path]) => path === "/api/production/workbench")).toHaveLength(1);
  expect(api.read.mock.calls.filter(([path]) => path.startsWith(`/api/production/${kind}?`))).toHaveLength(1);
  await act(async () => { resolveDetail(records[1]!); await nextDetail; });
  expect(await screen.findByRole("heading", { name: new RegExp(records[1]!.name) })).toBeInTheDocument();
  expect(api.write).not.toHaveBeenCalled();
});
it("new warehouse remains uninitialized, not zero or receivable stock", async () => {
  mount("warehouses", "/production/warehouses/900");
  expect(await screen.findByRole("heading", { name: "虚构青禾仓" })).toBeInTheDocument();
  expect(within(screen.getByRole("status")).getByText("库存尚未建立")).toBeInTheDocument();
  expect(screen.queryByRole("button", { name: "入库" })).not.toBeInTheDocument();
  expect(screen.queryByText("在库实物")).not.toBeInTheDocument();
  expect(api.write).not.toHaveBeenCalled();
});
it("viewer can inspect warehouse profiles but cannot create or edit", async () => {
  mount("warehouses", "/production/warehouses", false);
  await screen.findByRole("link", { name: "虚构青禾仓" });
  await screen.findByRole("heading", { name: "虚构青禾仓" });
  expect(screen.getByLabelText("仓库状态")).toHaveTextContent("启用中");
  expect(screen.getByLabelText("仓库状态")).toHaveAttribute("data-status-tone", "success");
  expect(screen.queryByRole("button", { name: "新建仓库" })).not.toBeInTheDocument();
  expect(screen.queryByRole("button", { name: "编辑资料" })).not.toBeInTheDocument();
  expect(api.write).not.toHaveBeenCalled();
});
it("uses a danger state for inactive warehouse profiles", async () => {
  const inactive = { ...readyWarehouse, id: "5", name: "虚构停用仓", status: "INACTIVE" };
  installWarehouseCenterMocks({ warehouses: [inactive] });
  mount("warehouses", "/production/warehouses/5?owner=1&tab=profile");
  expect(await screen.findByLabelText("仓库状态")).toHaveTextContent("已停用");
  expect(screen.getByLabelText("仓库状态")).toHaveAttribute("data-status-tone", "danger");
});
it("groups warehouse states and keeps owner context across the four workspace tabs", async () => {
  const records: DirectoryRecord[] = [
    readyWarehouse,
    { ...warehouse, id: "2", name: "虚构待建账仓" },
    { ...warehouse, id: "3", name: "虚构FBA仓", type: "FBA", inventory_state: "NOT_CONNECTED" },
    { ...warehouse, id: "4", name: "虚构收货地点", type: "LOCATION", inventory_state: "NOT_APPLICABLE" },
    { ...warehouse, id: "5", name: "虚构停用仓", status: "INACTIVE", inventory_state: "READY" },
  ];
  installWarehouseCenterMocks({ warehouses: records });
  mount("warehouses", "/production/warehouses/1?owner=1");
  await screen.findByRole("link", { name: "虚构广州仓" });
  const list = await screen.findByRole("navigation", { name: "仓库列表" });
  for (const group of ["已建账", "未建账", "平台未接入", "非库存地点", "已停用"]) expect(within(list).getByRole("heading", { name: new RegExp(group) })).toBeInTheDocument();
  cleanup();
  for (const [key, tab] of [["records", "收发记录"], ["adjust", "盘点与异常"], ["profile", "资料"], ["stock", "库存"]]) {
    mount("warehouses", `/production/warehouses/1?owner=1&tab=${key}`);
    await screen.findByRole("heading", { name: "虚构广州仓" });
    expect(screen.getByRole("button", { name: tab })).toHaveAttribute("aria-pressed", "true");
    expect(screen.getByLabelText("货主")).toHaveValue("1");
    cleanup();
  }
  expect(api.write).not.toHaveBeenCalled();
});

it("shows only on-hand quantities in the warehouse matrix and keeps availability in detail", async () => {
  installWarehouseCenterMocks(); mount("warehouses", "/production/warehouses/1?owner=1");
  const table = await screen.findByRole("table", { name: "本仓款色尺码库存" });
  expect(within(table).getByRole("button", { name: "2301" })).toBeInTheDocument();
  expect(within(table).getByRole("columnheader", { name: "款号" })).toBeInTheDocument();
  expect(within(table).getByRole("columnheader", { name: "颜色" })).toBeInTheDocument();
  expect(screen.queryByText(/短袖T恤/)).not.toBeInTheDocument();
  expect(screen.getByText("在库", { selector: "span" }).parentElement).toHaveTextContent("7");
  expect(screen.queryByText("当前可发")).not.toBeInTheDocument();
  expect(within(table).queryByText("可发")).not.toBeInTheDocument();
  expect(within(table).queryAllByText("—")).toHaveLength(0);
  expect(screen.queryByText(/“—”为未登记，0为明确零库存/)).not.toBeInTheDocument();
  await userEvent.click(within(table).getByRole("button", { name: "2301 Blue M 库存明细 SKU 1001" }));
  expect(screen.getByRole("region", { name: "规格库存明细" })).toHaveTextContent("在库4当前可发3合格4待检0次品0预留1冻结0");
  await userEvent.click(within(table).getByRole("button", { name: "2301" }));
  expect(within(table).getByText("2种颜色 · 已收起")).toBeInTheDocument();
  expect(within(table).getAllByLabelText("在库7件")).toHaveLength(2);
  expect(screen.queryByRole("region", { name: "规格库存明细" })).not.toBeInTheDocument();
  await userEvent.type(screen.getByRole("searchbox", { name: "搜索本仓款号、颜色或尺码" }), "White");
  expect(within(table).getByText("筛选合计")).toBeInTheDocument();
  expect(within(table).getAllByLabelText("在库1件").length).toBeGreaterThan(0);
});

it("keeps receive and shipment records inside the current warehouse and owner", async () => {
  installWarehouseCenterMocks({
    documents: [
      { id: "11", warehouse_id: "1", owner_id: "1", kind: "IN", status: "POSTED", business_date: "2026-10-20", reason: "本仓收货", lines: [{ sku_id: "1001", units: "4", quality: "QUALIFIED", purpose: "RECEIPT" }] },
      { id: "12", warehouse_id: "1", owner_id: "1", kind: "IN", status: "DRAFT", business_date: "2026-10-21", reason: "数量待核" },
      { id: "13", warehouse_id: "1", owner_id: "1", kind: "OUT", status: "POSTED", business_date: "2026-10-22", reason: "本仓出库", lines: [{ sku_id: "1001", units: "1", quality: "QUALIFIED", purpose: "TAKE" }] },
      { id: "99", warehouse_id: "9", owner_id: "1", kind: "IN", status: "POSTED", business_date: "2026-10-20", reason: "其他仓记录", lines: [{ sku_id: "1001", units: "9", quality: "QUALIFIED", purpose: "RECEIPT" }] },
    ],
    shipments: [
      { id: "21", warehouse_id: "1", owner_id: "1", business_number: "SHIP-CURRENT", system_number: "S-21", status: "CONFIRMED", destination: "虚构海外仓", actual_units: "1" },
      { id: "22", warehouse_id: "9", owner_id: "1", business_number: "SHIP-OTHER", system_number: "S-22", status: "CONFIRMED", destination: "其他地点", actual_units: "9" },
    ],
  });
  mount("warehouses", "/production/warehouses/1?owner=1&tab=records");
  const receive = await screen.findByRole("table", { name: "入库记录" });
  expect(within(receive).getByText("本仓收货")).toBeInTheDocument();
  expect(within(receive).getByText("数量待核").closest("tr")).toHaveTextContent("待核");
  expect(screen.queryByText("其他仓记录")).not.toBeInTheDocument();
  cleanup();
  mount("warehouses", "/production/warehouses/1?owner=1&tab=records&mode=ship");
  const outgoing = await screen.findByRole("table", { name: "出库记录" });
  expect(within(outgoing).getByText("本仓出库")).toBeInTheDocument();
  expect(screen.queryByText("本仓收货")).not.toBeInTheDocument();
  expect(await screen.findByRole("button", { name: "SHIP-CURRENT" })).toBeInTheDocument();
  expect(screen.queryByRole("button", { name: "SHIP-OTHER" })).not.toBeInTheDocument();
});

it("filters loaded records by status and date and previews a draft before confirming", async () => {
  const draft = { id: "31", warehouse_id: "1", owner_id: "1", kind: "IN", status: "DRAFT", revision: "1", business_date: "2026-10-23", reason: "虚构22件收货", lines: [{ sku_id: "1001", units: "20", quality: "QUALIFIED", purpose: "RECEIPT" }, { sku_id: "1001", units: "2", quality: "PENDING", purpose: "RECEIPT" }] };
  const posted = { ...draft, id: "30", status: "POSTED", business_date: "2026-10-22", reason: "已入库记录" };
  const otherOwner = { ...draft, id: "99", owner_id: "9", reason: "其他货主不显示" };
  installWarehouseCenterMocks({ documents: [draft, posted, otherOwner] });
  const user = userEvent.setup();
  mount("warehouses", "/production/warehouses/1?owner=1&tab=records");
  await screen.findByRole("heading", { name: "核对入库草稿" });
  expect(screen.queryByText("其他货主不显示")).not.toBeInTheDocument();
  expect(screen.queryByRole("button", { name: "确认入库" })).not.toBeInTheDocument();
  await user.selectOptions(screen.getByLabelText("记录状态"), "complete");
  const table = screen.getByRole("table", { name: "入库记录" });
  expect(within(table).getByText("已入库记录")).toBeInTheDocument();
  expect(within(table).queryByText("虚构22件收货")).not.toBeInTheDocument();
  await user.click(screen.getByRole("button", { name: "清空" }));
  await user.type(screen.getByLabelText("记录日期"), "2026-10-23");
  expect(within(table).queryByText("已入库记录")).not.toBeInTheDocument();
  api.write.mockResolvedValueOnce({ preview_hash: "fixture-preview", impacts: [{ warehouse_id: "1", sku_id: "1001", on_hand_before: "4", on_hand_after: "26", free_before: "3", free_after: "23" }] });
  await user.click(await screen.findByRole("button", { name: "预览库存影响" }));
  expect(await screen.findByText("+22")).toBeInTheDocument();
  expect(screen.getByText("+20")).toBeInTheDocument();
  expect(screen.getByRole("list", { name: "单据处理步骤" }).querySelector('[aria-current="step"]')).toHaveTextContent("核对预览");
  expect(api.write).toHaveBeenCalledTimes(1);
  expect(api.write.mock.calls[0]?.[0]).toBe("/api/production/inventory/documents/31/preview");
  expect(screen.getByRole("button", { name: "确认入库" })).toBeInTheDocument();
});

it("opens stocktake through the existing inventory draft workflow with a locked scope", async () => {
  installWarehouseCenterMocks(); mount("warehouses", "/production/warehouses/1?owner=1&tab=adjust&adjust_view=count&operation=new&editor=1");
  const dialog = await screen.findByRole("dialog", { name: "登记盘点" });
  await waitFor(() => expect(dialog).toHaveTextContent("虚构广州仓 · 公司自有（虚构）"));
  expect(within(dialog).queryByLabelText(/^仓库/)).not.toBeInTheDocument();
  expect(within(dialog).getByRole("button", { name: "下一步" })).toBeInTheDocument();
  expect(api.write).not.toHaveBeenCalled();
});
it("stocktake wizard saves an explicit zero total, previews and confirms separately", async () => {
  installWarehouseCenterMocks();
  const router = mount("warehouses", "/production/warehouses/1?tab=adjust&adjust_view=count&operation=new&editor=1&sku_id=1001");
  const dialog = await screen.findByRole("dialog", { name: "登记盘点" });
  await within(dialog).findByRole("option", { name: "短袖T恤 Blue M" });
  await userEvent.selectOptions(within(dialog).getByLabelText("盘点商品1状态"), "QUALIFIED");
  await userEvent.type(within(dialog).getByLabelText("盘点商品1实盘总数"), "0");
  await userEvent.click(within(dialog).getByRole("button", { name: "下一步" }));
  await userEvent.type(within(dialog).getByLabelText(/^来源依据/), "虚构盘点");
  await userEvent.type(within(dialog).getByLabelText(/^盘点证据/), "虚构复核表");
  const today = within(dialog).getByLabelText<HTMLInputElement>(/^实盘截止日期/).value;
  api.write.mockImplementation(path => Promise.resolve(path.endsWith("/preview") ? { preview_hash: "count-preview", impacts: [{ sku_id: "1001", warehouse_id: "1", on_hand_before: "4", on_hand_after: "0", free_before: "3", free_after: null }] } : path.endsWith("/confirm") ? { id: "61", status: "POSTED", revision: "2" } : { id: "61", status: "DRAFT", revision: "1" }));
  await userEvent.click(within(dialog).getByRole("button", { name: "保存草稿并核对" }));
  await within(dialog).findByRole("table", { name: "确认后的库存变化" });
  expect(api.write.mock.calls[0]?.[1].body).toMatchObject({ kind: "ADJUST", warehouse_id: "1", owner_id: "1", business_date: today, lines: [{ sku_id: "1001", quality: "QUALIFIED", units: "0", purpose: "COUNT", counted_on: today, evidence: "虚构复核表" }] });
  expect(api.write.mock.calls.map(([path]) => path)).toEqual(["/api/production/inventory/documents", "/api/production/inventory/documents/61/preview"]);
  expect(new URLSearchParams(router.state.location.search).get("wizard_draft")).toBe("61");
  await userEvent.click(within(dialog).getByRole("button", { name: "确认本次盘点" }));
  await waitFor(() => expect(screen.queryByRole("dialog", { name: "登记盘点" })).not.toBeInTheDocument());
  expect(api.write.mock.calls.at(-1)?.[1].body).toMatchObject({ expected_revision: "1", preview_hash: "count-preview" });
});
it("borrowing wizard checks current free stock and clears quantities when changing the SKU", async () => {
  installWarehouseCenterMocks();
  mount("warehouses", "/production/warehouses/1?tab=adjust&adjust_view=loan&operation=new&editor=1&sku_id=1001");
  const dialog = await screen.findByRole("dialog", { name: "登记借出" });
  await within(dialog).findByRole("option", { name: "短袖T恤 Blue M" });
  await userEvent.click(within(dialog).getByRole("button", { name: "下一步" }));
  await userEvent.type(within(dialog).getByLabelText(/^本次借出件数/), "4");
  await userEvent.type(within(dialog).getByLabelText(/^实际借用人/), "虚构试衣组");
  expect(within(dialog).getByText(/当前可发仅3件/)).toBeInTheDocument();
  await userEvent.click(within(dialog).getByRole("button", { name: "下一步" }));
  expect(within(dialog).getByLabelText(/^本次借出件数/)).toHaveFocus();
  expect(api.write).not.toHaveBeenCalled();
  await userEvent.click(within(dialog).getByRole("button", { name: "上一步" }));
  await userEvent.selectOptions(within(dialog).getByLabelText(/^商品颜色与尺码/), "1002");
  await userEvent.click(within(dialog).getByRole("button", { name: "下一步" }));
  expect(within(dialog).getByLabelText(/^本次借出件数/)).toHaveValue("");
  expect(within(dialog).getByRole("region", { name: "当前库存状态" })).toHaveTextContent("当前可发1件");
});
it("warehouse return entry locks the original loan and supports partial pending returns", async () => {
  const loan = { id: "7", warehouse_id: "1", owner_id: "1", sku_id: "1001", borrower: "虚构试衣组", borrowed_units: "3", returned_units: "0", settled_units: "0", outstanding_units: "3", is_active: true };
  installWarehouseCenterMocks({ loans: [loan, { ...loan, id: "9", owner_id: "9", borrower: "其他货主" }] });
  mount("warehouses", "/production/warehouses/1?tab=adjust&adjust_view=loan");
  expect(await screen.findByRole("table", { name: "本仓未还借出" })).toHaveTextContent("2301-Blue-M");
  await userEvent.click(await screen.findByRole("button", { name: "登记归还：借出7" }));
  const dialog = await screen.findByRole("dialog", { name: "登记归还" });
  expect(dialog).toHaveTextContent("未还3件");
  expect(within(dialog).getByLabelText(/^商品颜色与尺码/)).toBeDisabled();
  expect(dialog).not.toHaveTextContent("其他货主");
  await userEvent.click(within(dialog).getByRole("button", { name: "下一步" }));
  await userEvent.selectOptions(within(dialog).getByLabelText(/^归还货品状态/), "PENDING");
  await userEvent.type(within(dialog).getByLabelText(/^本次归还件数/), "4");
  expect(within(dialog).getByText(/本次最多归还 3 件/)).toBeInTheDocument();
  await userEvent.clear(within(dialog).getByLabelText(/^本次归还件数/)); await userEvent.type(within(dialog).getByLabelText(/^本次归还件数/), "2");
  await userEvent.click(within(dialog).getByRole("button", { name: "下一步" }));
  await userEvent.type(within(dialog).getByLabelText(/^来源依据/), "虚构归还待检2件");
  api.write.mockImplementation(path => Promise.resolve(path.endsWith("/preview") ? { preview_hash: "return-preview", impacts: [{ sku_id: "1001", warehouse_id: "1", on_hand_before: "4", on_hand_after: "6", free_before: "3", free_after: "3" }] } : path.endsWith("/confirm") ? { id: "62", status: "POSTED", revision: "2" } : { id: "62", status: "DRAFT", revision: "1" }));
  await userEvent.click(within(dialog).getByRole("button", { name: "保存草稿并核对" }));
  await within(dialog).findByRole("table", { name: "确认后的库存变化" });
  expect(api.write.mock.calls[0]?.[1].body).toMatchObject({ kind: "IN", lines: [{ sku_id: "1001", purpose: "RETURN", loan_id: "7", quality: "PENDING", units: "2" }] });
  await userEvent.click(within(dialog).getByRole("button", { name: "确认本次归还" }));
  await waitFor(() => expect(screen.queryByRole("dialog", { name: "登记归还" })).not.toBeInTheDocument());
  expect(api.write.mock.calls.filter(([path]) => path.endsWith("/confirm"))).toHaveLength(1);
});
it("stocktake wizard resumes the same revision and opens a clean new operation after closing", async () => {
  const draft = { id: "63", kind: "ADJUST", status: "DRAFT", revision: "3", warehouse_id: "1", owner_id: "1", business_date: "2026-10-26", reason: "已保存盘点依据", lines: [{ sku_id: "1001", quality: "QUALIFIED", units: "4", purpose: "COUNT", counted_on: "2026-10-26", evidence: "已保存盘点证据" }] };
  installWarehouseCenterMocks({ documents: [draft] });
  mount("warehouses", "/production/warehouses/1?tab=adjust&adjust_view=count&operation=new&editor=1&wizard_draft=63");
  const dialog = await screen.findByRole("dialog", { name: "登记盘点" });
  await within(dialog).findByRole("option", { name: "短袖T恤 Blue M" });
  expect(within(dialog).getByLabelText("盘点商品1实盘总数")).toHaveValue("4");
  await userEvent.click(within(dialog).getByRole("button", { name: "下一步" }));
  expect(within(dialog).getByLabelText(/^盘点证据/)).toHaveValue("已保存盘点证据");
  api.write.mockRejectedValueOnce(new ApiRequestError(409, "test_stop", "保留盘点原修订"));
  await userEvent.click(within(dialog).getByRole("button", { name: "保存草稿并核对" }));
  await within(dialog).findByText("保留盘点原修订");
  expect(api.write.mock.calls[0]?.[0]).toBe("/api/production/inventory/documents/63/update");
  expect(api.write.mock.calls[0]?.[1].body.expected_revision).toBe("3");
  await userEvent.click(within(dialog).getByRole("button", { name: "关闭盘点登记" }));
  await userEvent.click(await screen.findByRole("button", { name: "新建盘点" }));
  const fresh = await screen.findByRole("dialog", { name: "登记盘点" });
  expect(within(fresh).getByLabelText("盘点商品1", { exact: true })).toHaveValue("");
});
it("return wizard refuses an original loan from a different owner and viewers cannot register returns", async () => {
  const otherLoan = { id: "9", warehouse_id: "1", owner_id: "9", sku_id: "1001", borrower: "其他货主", outstanding_units: "3", is_active: true };
  installWarehouseCenterMocks({ loans: [otherLoan] });
  mount("warehouses", "/production/warehouses/1?tab=adjust&adjust_view=loan&operation=new&editor=1&loan_id=9&sku_id=1001");
  const dialog = await screen.findByRole("dialog", { name: "登记归还" });
  await within(dialog).findByText("原借出不存在、已停用或不属于当前范围");
  expect(within(dialog).getByRole("button", { name: "下一步" })).toBeDisabled();
  expect(api.write).not.toHaveBeenCalled();
  cleanup(); installWarehouseCenterMocks({ loans: [{ ...otherLoan, owner_id: "1" }] });
  mount("warehouses", "/production/warehouses/1?tab=adjust&adjust_view=loan", false);
  await screen.findByRole("table", { name: "本仓未还借出" });
  expect(screen.queryByRole("button", { name: /登记归还/ })).not.toBeInTheDocument();
  expect(screen.queryByRole("button", { name: "登记借出" })).not.toBeInTheDocument();
});
it("shows the shipment destination and cartons without posting until explicit confirmation", async () => {
  const shipment = { id: "21", warehouse_id: "1", owner_id: "1", business_number: "DEMO-PACK", system_number: "S-21", business_date: "2026-10-23", status: "DRAFT", revision: "1", destination: "虚构海外仓", actual_units: "4", sources: [{ sku_id: "1001", sku_label: "2301-Blue-M", actual_units: "4", allocations: [] }], cartons: [{ number: "DEMO-A001", items: [{ sku_id: "1001", units: "4" }] }] };
  installWarehouseCenterMocks({ shipments: [shipment] });
  const original = api.read.getMockImplementation()!;
  api.read.mockImplementation(path => path === "/api/production/shipments/21" ? Promise.resolve(shipment) : original(path));
  const user = userEvent.setup(); mount("warehouses", "/production/warehouses/1?owner=1&tab=records&mode=ship&shipment=21");
  expect(await screen.findByRole("heading", { name: "核对装箱草稿" })).toBeInTheDocument();
  expect(screen.getByRole("table", { name: "发货装箱明细" })).toHaveTextContent("DEMO-A001");
  expect(screen.getByText("发货记录表示本仓交接，不表示目的仓已签收。")).toBeInTheDocument();
  expect(api.write).not.toHaveBeenCalled();
  await user.click(screen.getByRole("button", { name: "核对并确认本出货草稿" }));
  expect(api.write).not.toHaveBeenCalled();
  expect(screen.getByRole("list", { name: "单据处理步骤" }).querySelector('[aria-current="step"]')).toHaveTextContent("核对预览");
  api.write.mockResolvedValue({ ...shipment, status: "CONFIRMED", revision: "2" });
  await user.click(screen.getByRole("button", { name: "确认本草稿已实际发货" }));
  expect(api.write.mock.calls[0]?.[0]).toBe("/api/production/shipments/21/confirm");
  expect(api.write.mock.calls[0]?.[1].body).toMatchObject({ expected_revision: "1" });
});
it("rejects a shipment from another owner in the shared warehouse wizard", async () => {
  installWarehouseCenterMocks();
  const source = { id: "10", revision: "2", status: "CONFIRMED", business_number: "QA-OWNER", receipt_warehouse_id: "1", receipt_owner_id: "1", lines: [{ id: "101", sku_id: "1001", sku_label: "QA-M", expected_units: "4", actual_units: "0" }] };
  const original = api.read.getMockImplementation()!;
  api.read.mockImplementation(path => path === "/api/production/orders/10" ? Promise.resolve(source) : path === "/api/production/shipments/21" ? Promise.resolve({ id: "21", status: "DRAFT", revision: "1", warehouse_id: "1", owner_id: "9" }) : original(path));
  mount("warehouses", "/production/warehouses/1?owner=1&tab=records&mode=ship&ship=1&source_order=10&shipment=21");
  expect(await screen.findByText("发货批次不属于当前仓库及货主")).toBeInTheDocument();
  expect(screen.queryByRole("button", { name: "下一步" })).not.toBeInTheDocument();
  expect(api.write).not.toHaveBeenCalled();
});
it("does not expose confirmation for a shipment from another owner", async () => {
  const shipment = { id: "21", warehouse_id: "1", owner_id: "9", business_number: "OTHER", status: "DRAFT", revision: "1", actual_units: "4" };
  installWarehouseCenterMocks({ shipments: [shipment] });
  const original = api.read.getMockImplementation()!;
  api.read.mockImplementation(path => path === "/api/production/shipments/21" ? Promise.resolve(shipment) : original(path));
  mount("warehouses", "/production/warehouses/1?owner=1&tab=records&mode=ship&shipment=21");
  expect(await screen.findByText("发货批次不属于当前仓库及货主")).toBeInTheDocument();
  expect(screen.queryByRole("button", { name: "核对并确认本出货草稿" })).not.toBeInTheDocument();
  expect(api.write).not.toHaveBeenCalled();
});
it("warehouse unsaved confirmation is a dialog and preserves edits on escape or continue", async () => {
  const user = userEvent.setup(); mount("warehouses", "/production/warehouses/900");
  await user.click(await screen.findByRole("button", { name: "编辑资料" }));
  const editor = screen.getByRole("dialog", { name: "编辑仓库 / 地点" });
  await user.type(within(editor).getByLabelText("联系人"), "测试联系人");
  await user.click(within(editor).getByRole("button", { name: "取消" }));
  const confirmation = screen.getByRole("dialog", { name: "资料尚未保存，是否放弃？" });
  await user.click(within(confirmation).getByRole("button", { name: "继续编辑" }));
  expect(within(editor).getByLabelText("联系人")).toHaveValue("测试联系人");
  await user.click(within(editor).getByRole("button", { name: "取消" }));
  await user.keyboard("{Escape}");
  expect(screen.queryByRole("dialog", { name: "资料尚未保存，是否放弃？" })).not.toBeInTheDocument();
  expect(within(editor).getByLabelText("联系人")).toHaveValue("测试联系人");
  await user.click(within(editor).getByRole("button", { name: "取消" }));
  await user.click(within(screen.getByRole("dialog", { name: "资料尚未保存，是否放弃？" })).getByRole("button", { name: "放弃并关闭" }));
  expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
  expect(api.write).not.toHaveBeenCalled();
});
it("factory profile creation sends associations but never opens stock", async () => {
  const user = userEvent.setup(); mount("factories", "/production/factories");
  await user.click(await screen.findByRole("button", { name: "新建工厂" }));
  const dialog = screen.getByRole("dialog");
  await user.type(within(dialog).getByLabelText(/工厂全名/), "虚构新厂");
  await user.selectOptions(within(dialog).getByLabelText("国家 / 地区"), "中国");
  await user.selectOptions(within(dialog).getByLabelText("省 / 直辖市 / 自治区"), "广东省");
  await user.selectOptions(within(dialog).getByLabelText("城市 / 区县"), "广州市");
  await user.click(within(dialog).getByText(/常用仓库（选填）/));
  await user.click(await within(dialog).findByLabelText(/虚构青禾仓/));
  // Keep a pending response to inspect the exact single command.
  api.write.mockImplementation(() => new Promise(() => undefined));
  await user.click(within(dialog).getByRole("button", { name: "创建档案" }));
  expect(api.write).toHaveBeenCalledTimes(1);
  expect(api.write.mock.calls[0]?.[0]).toBe("/api/production/factories");
  expect(api.write.mock.calls[0]?.[1].body).toMatchObject({ name: "虚构新厂", region: "中国 / 广东省 / 广州市", warehouse_ids: ["900"] });
  expect(api.write.mock.calls[0]?.[1].body).not.toHaveProperty("lines");
});

it("changing province clears the previous city and warehouse selection stays optional", async () => {
  const user = userEvent.setup(); mount("factories", "/production/factories");
  await user.click(await screen.findByRole("button", { name: "新建工厂" }));
  const form = within(screen.getByRole("dialog"));
  await user.type(form.getByLabelText(/工厂全名/), "虚构联动厂");
  await user.selectOptions(form.getByLabelText("国家 / 地区"), "中国");
  await user.selectOptions(form.getByLabelText("省 / 直辖市 / 自治区"), "广东省");
  await user.selectOptions(form.getByLabelText("城市 / 区县"), "广州市");
  await user.selectOptions(form.getByLabelText("省 / 直辖市 / 自治区"), "浙江省");
  expect(form.getByLabelText("城市 / 区县")).toHaveValue("");
  expect(form.queryByRole("option", { name: "广州市" })).not.toBeInTheDocument();
  api.write.mockImplementation(() => new Promise(() => undefined));
  await user.click(form.getByRole("button", { name: "创建档案" }));
  expect(api.write.mock.calls[0]?.[1].body).toMatchObject({ region: "中国 / 浙江省", warehouse_ids: [] });
});

it("country changes clear domestic selections and region can be left unset", async () => {
  const user = userEvent.setup(); mount("factories", "/production/factories");
  await user.click(await screen.findByRole("button", { name: "新建工厂" }));
  const form = within(screen.getByRole("dialog"));
  await user.type(form.getByLabelText(/工厂全名/), "虚构海外厂");
  await user.selectOptions(form.getByLabelText("国家 / 地区"), "中国");
  await user.selectOptions(form.getByLabelText("省 / 直辖市 / 自治区"), "广东省");
  await user.selectOptions(form.getByLabelText("国家 / 地区"), "越南");
  expect(form.queryByLabelText("省 / 直辖市 / 自治区")).not.toBeInTheDocument();
  await user.selectOptions(form.getByLabelText("国家 / 地区"), "");
  api.write.mockImplementation(() => new Promise(() => undefined));
  await user.click(form.getByRole("button", { name: "创建档案" }));
  expect(api.write.mock.calls[0]?.[1].body).toMatchObject({ region: "", warehouse_ids: [] });
});

it("editing unrelated fields preserves legacy region and selected warehouses", async () => {
  const factory = { ...warehouse, id: "3", name: "虚构旧厂", type: undefined, region: "广东·东莞", warehouse_ids: ["900", "901"] };
  const originalRead = api.read.getMockImplementation()!;
  api.read.mockImplementation(async path => {
    if (path === "/api/production/factories/3") return factory;
    if (path.includes("/orders?")) return { items: [], total: 0, page: 1 };
    return originalRead(path);
  });
  const user = userEvent.setup(); mount("factories", "/production/factories/3");
  await user.click(await screen.findByRole("button", { name: "编辑资料 / 停用" }));
  const form = within(screen.getByRole("dialog"));
  expect(form.getByRole("button",{name:"重新选择地区（当前：广东·东莞）"})).toBeInTheDocument();
  await user.type(form.getByLabelText("联系人"), "虚构联系人");
  await user.type(form.getByLabelText(/修改 \/ 停用原因/), "补充联系资料");
  api.write.mockImplementation(() => new Promise(() => undefined));
  await user.click(form.getByRole("button", { name: "保存资料修改" }));
  expect(api.write.mock.calls[0]?.[1].body).toMatchObject({ region: "广东·东莞", warehouse_ids: ["900", "901"], expected_revision: "1" });
});

it("foreign country selection persists through the existing region contract", async () => {
  const user = userEvent.setup(); mount("factories", "/production/factories");
  await user.click(await screen.findByRole("button", { name: "新建工厂" }));
  const form = within(screen.getByRole("dialog"));
  await user.type(form.getByLabelText(/工厂全名/), "虚构越南厂");
  await user.selectOptions(form.getByLabelText("国家 / 地区"), "越南");
  api.write.mockImplementation(() => new Promise(() => undefined));
  await user.click(form.getByRole("button", { name: "创建档案" }));
  expect(api.write.mock.calls[0]?.[1].body).toMatchObject({ region: "越南" });
});

it("warehouse profile editor retains its original country and region fields", async () => {
  const user = userEvent.setup(); mount("warehouses", "/production/warehouses/900");
  await user.click(await screen.findByRole("button", { name: "编辑资料" }));
  const form = within(screen.getByRole("dialog"));
  expect(form.getAllByRole("option", { name: "成品仓" })).toHaveLength(1);
  expect(form.getByLabelText(/类型/)).toHaveValue("FACTORY");
  expect(form.getByLabelText(/国家 \/ 地区/)).toBeDisabled();
  await user.selectOptions(form.getByLabelText("省 / 直辖市 / 自治区"), "广东省");
  await user.type(form.getByLabelText(/修改 \/ 停用原因/), "补充地区");
  api.write.mockImplementation(() => new Promise(() => undefined));
  await user.click(form.getByRole("button", { name: "保存资料修改" }));
  expect(api.write.mock.calls[0]?.[0]).toBe("/api/production/warehouses/900");
  expect(api.write.mock.calls[0]?.[1].body).toMatchObject({ type: "FACTORY", country: "中国", region: "广东省", factory_ids: [], expected_revision: "1" });
});

it("warehouse disclosures preserve optional inputs and keep FBA identity required", async () => {
  const user = userEvent.setup(); mount("warehouses", "/production/warehouses");
  await user.click(await screen.findByRole("button", { name: "新建仓库" }));
  const form = within(screen.getByRole("dialog"));
  await user.type(form.getByLabelText(/仓库 \/ 地点名称/), "虚构FBA资料");
  await user.selectOptions(form.getByLabelText(/类型/), "FBA");
  expect(form.getByLabelText(/卖家店铺/)).toBeRequired();
  expect(form.getByLabelText(/站点/)).toBeRequired();
  await user.selectOptions(form.getByLabelText(/国家 \/ 地区/), "美国");
  await user.selectOptions(form.getByLabelText(/卖家店铺/), "scope:7");
  await user.selectOptions(form.getByLabelText(/站点/), "US");
  await user.click(form.getByText(/更多资料（选填）/));
  await user.type(form.getByLabelText("备注"), "虚构资料说明");
  await user.click(form.getByText(/更多资料（选填）/));
  api.write.mockImplementation(() => new Promise(() => undefined));
  await user.click(form.getByRole("button", { name: "创建档案" }));
  expect(api.write).toHaveBeenCalledTimes(1);
  expect(api.write.mock.calls[0]?.[1].body).toMatchObject({ type: "FBA", country: "美国", seller_account: "scope:7", marketplace: "US", notes: "虚构资料说明", factory_ids: [] });
});

it("filters stock reasons and restores scope without changing inventory", async () => {
  installWarehouseCenterMocks(); mount("warehouses", "/production/warehouses/1?owner=1");
  const table = await screen.findByRole("table", { name: "本仓款色尺码库存" });
  await userEvent.click(screen.getByRole("button", { name: "预留 2" }));
  expect(within(table).getByText("筛选合计")).toBeInTheDocument();
  expect(within(table).queryByText("White")).not.toBeInTheDocument();
  expect(within(table).getAllByLabelText("在库6件")).toHaveLength(2);
  expect(screen.getByText("在库", { selector: "span" }).parentElement).toHaveTextContent("6");
  await userEvent.click(screen.getByRole("button", { name: "全部规格" }));
  expect(within(table).getByText("White")).toBeInTheDocument();
  expect(screen.getByText("在库", { selector: "span" }).parentElement).toHaveTextContent("7");
  expect(api.write).not.toHaveBeenCalled();
});
it("queries older warehouse records with scope, pagination, filters and URL restoration", async () => {
  installWarehouseCenterMocks();
  const original = api.read.getMockImplementation()!;
  api.read.mockImplementation(async url => {
    if (url.startsWith("/api/production/inventory/documents?")) {
      const p = new URL(url, "http://qa").searchParams;
      return { items: [], total: p.get("q") ? 0 : 41, page: Number(p.get("page") || 1), page_size: 20 };
    }
    return original(url);
  });
  const router = mount("warehouses", "/production/warehouses/1?owner=1&tab=records");
  await screen.findByRole("table", { name: "入库记录" });
  await userEvent.click(await screen.findByRole("button", { name: "下一页" }));
  await waitFor(() => expect(router.state.location.search).toContain("record_page=2"));
  await userEvent.type(screen.getByRole("searchbox", { name: "搜索本仓记录" }), "旧依据");
  await userEvent.click(screen.getByRole("button", { name: "查询" }));
  await waitFor(() => expect(api.read.mock.calls.some(([url]) => {
    const p = new URL(url, "http://qa").searchParams;
    return url.startsWith("/api/production/inventory/documents?") && p.get("warehouse_id") === "1" && p.get("owner_id") === "1" && p.get("page") === "1" && p.get("q") === "旧依据" && p.get("kind") === "IN";
  })).toBe(true));
  await act(() => router.navigate(-1));
  await waitFor(() => expect(screen.getByRole("searchbox", { name: "搜索本仓记录" })).toHaveValue(""));
  expect(api.write).not.toHaveBeenCalled();
});

it("retains warehouse inventory search and state filters when returning from records", async () => {
  installWarehouseCenterMocks();
  const router = mount("warehouses", "/production/warehouses/1?owner=1");
  const search = await screen.findByRole("searchbox", { name: "搜索本仓款号、颜色或尺码" });
  await userEvent.type(search, "Blue");
  await userEvent.click(screen.getByRole("button", { name: "预留 2" }));
  await userEvent.click(screen.getByRole("button", { name: "收发记录" }));
  await userEvent.click(screen.getByRole("button", { name: "库存" }));
  expect(screen.getByRole("searchbox", { name: "搜索本仓款号、颜色或尺码" })).toHaveValue("Blue");
  expect(screen.getByRole("button", { name: "预留 2" })).toHaveAttribute("aria-pressed", "true");
  expect(new URLSearchParams(router.state.location.search).get("stock_q")).toBe("Blue");
  await userEvent.click(screen.getByRole("button", { name: "清除库存筛选" }));
  expect(screen.getByRole("searchbox", { name: "搜索本仓款号、颜色或尺码" })).toHaveValue("");
  expect(screen.getByRole("button", { name: "全部规格" })).toHaveAttribute("aria-pressed", "true");
  expect(api.write).not.toHaveBeenCalled();
});
it("restores the record list after browser back from a selected record", async () => {
  const doc = { id: "61", warehouse_id: "1", owner_id: "1", kind: "IN", status: "DRAFT", business_date: "2026-10-27", reason: "虚构返回检查", lines: [] };
  installWarehouseCenterMocks({ documents: [doc] });
  const router = mount("warehouses", "/production/warehouses/1?owner=1&tab=records");
  const row = await screen.findByRole("button", { name: "库存单 61" });
  await waitFor(() => expect(row).toBeEnabled());
  await userEvent.click(row);
  await waitFor(() => expect(router.state.location.search).toContain("document=61"));
  expect((await screen.findByText("返回记录列表")).closest("button")).toHaveAttribute("aria-expanded", "false");
  await act(() => router.navigate(-1));
  await waitFor(() => expect(screen.getByText("收起记录列表").closest("button")).toHaveAttribute("aria-expanded", "true"));
  expect(new URLSearchParams(router.state.location.search).has("document")).toBe(false);
  expect(api.write).not.toHaveBeenCalled();
});

it("opens pending inspection from inventory with scoped stock and returns to the same filter", async () => {
  installWarehouseCenterMocks();
  const original = api.read.getMockImplementation()!;
  api.read.mockImplementation(async url => {
    const result = await original(url);
    if (url.includes("inventory/availability")) {
      const value = result as { items: Record<string, unknown>[] };
      return { ...value, items: value.items.map(item => item.sku_id === "1001" ? { ...item, pending_units: "2" } : item) };
    }
    return result;
  });
  const router = mount("warehouses", "/production/warehouses/1?owner=1&tab=stock&stock_q=Blue&stock_state=pending_units");
  await userEvent.click(await screen.findByRole("button", { name: "2301 Blue M 库存明细 SKU 1001" }));
  await userEvent.click(screen.getByRole("link", { name: "处理待检" }));
  const dialog = await screen.findByRole("dialog", { name: "登记质量变化" });
  expect(within(dialog).getByLabelText(/^商品颜色与尺码/)).toHaveValue("1001");
  expect(router.state.location.search).toContain("source_quality=PENDING");
  expect(router.state.location.search).toContain("sku_id=1001");
  await userEvent.click(within(dialog).getByRole("button", { name: "下一步" }));
  expect(within(dialog).getByLabelText(/^货品状态/)).toHaveValue("PENDING");
  expect(within(dialog).getByLabelText(/^目标货品状态/)).toHaveValue("");
  expect(within(dialog).getByLabelText(/^本次件数/)).toHaveValue("");

  await userEvent.click(within(dialog).getByRole("button", { name: "关闭质量登记" }));
  await screen.findByRole("table", { name: "本仓款色尺码库存" });
  expect(new URLSearchParams(router.state.location.search).get("tab")).toBe("stock");
  expect(screen.getByRole("searchbox", { name: "搜索本仓款号、颜色或尺码" })).toHaveValue("Blue");
  expect(screen.getByRole("button", { name: "待检 2" })).toHaveAttribute("aria-pressed", "true");
  expect(api.write).not.toHaveBeenCalled();
});
it("offers a direct stocktake for the selected SKU without inventing a quality result", async () => {
  installWarehouseCenterMocks();
  const router = mount("warehouses", "/production/warehouses/1?owner=1&tab=stock");
  await userEvent.click(await screen.findByRole("button", { name: "2301 Blue M 库存明细 SKU 1001" }));
  expect(screen.queryByRole("link", { name: "处理待检" })).not.toBeInTheDocument();
  await userEvent.click(screen.getByRole("link", { name: "盘点此规格" }));
  const dialog = await screen.findByRole("dialog", { name: "登记盘点" });
  expect(router.state.location.search).toContain("sku_id=1001");
  await userEvent.click(within(dialog).getByRole("button", { name: "关闭盘点登记" }));
  await screen.findByRole("table", { name: "本仓款色尺码库存" });
  expect(api.write).not.toHaveBeenCalled();
});

it("continues a new domestic warehouse into its opening dialog without posting inventory", async () => {
 const base=api.read.getMockImplementation()!;
 api.read.mockImplementation(path=>path.endsWith('/inventory/availability')?Promise.resolve({items:[],scopes:[],opening_enabled:true}):base(path));
 api.write.mockResolvedValue(warehouse);mount('warehouses','/production/warehouses');
 await userEvent.click(await screen.findByRole('button',{name:'新建仓库'}));
 const form=within(screen.getByRole('dialog'));
 expect(form.getAllByRole('option',{name:'成品仓'})).toHaveLength(1);
 expect(form.getByLabelText(/类型/)).toHaveValue('OWN');
 await userEvent.type(form.getByLabelText(/仓库 \/ 地点名称/),'虚构青禾仓');
 await userEvent.selectOptions(form.getByLabelText(/国家 \/ 地区/),'中国');
 await userEvent.click(form.getByRole('checkbox',{name:'创建后导入期初库存'}));
 await userEvent.click(form.getByRole('button',{name:'创建档案'}));
 expect(await screen.findByRole('dialog',{name:'虚构青禾仓 · 期初库存'})).toBeInTheDocument();
 expect(api.write.mock.calls.map(([path])=>path)).toEqual(['/api/production/warehouses']);
});
it("does not carry domestic opening selection into an FBA warehouse",async()=>{
 api.write.mockResolvedValue({...warehouse,type:'FBA',country:'美国'});mount('warehouses','/production/warehouses');
 await userEvent.click(await screen.findByRole('button',{name:'新建仓库'}));const form=within(screen.getByRole('dialog'));
 await userEvent.type(form.getByLabelText(/仓库 \/ 地点名称/),'虚构FBA');
 await userEvent.selectOptions(form.getByLabelText(/国家 \/ 地区/),'中国');await userEvent.click(form.getByRole('checkbox',{name:'创建后导入期初库存'}));
 await userEvent.selectOptions(form.getByLabelText(/^类型/),'FBA');await userEvent.selectOptions(form.getByLabelText(/国家 \/ 地区/),'美国');
 await userEvent.selectOptions(form.getByLabelText(/卖家店铺/),'scope:7');await userEvent.selectOptions(form.getByLabelText(/^站点/),'US');
 await userEvent.click(form.getByRole('button',{name:'创建档案'}));
 await waitFor(()=>expect(screen.queryByRole('dialog')).not.toBeInTheDocument());expect(api.write).toHaveBeenCalledTimes(1);
});

it.each(["stock","records"])("routes the %s warehouse receipt entry to multi-order intake with scope and return preserved",async tab=>{
 installWarehouseCenterMocks();const router=mount("warehouses",`/production/warehouses/1?tab=${tab}&mode=receive`);await screen.findByRole("heading",{name:/虚构广州仓/});const entry=await screen.findByRole("link",{name:tab==="stock"?"入库":"新建入库"});await userEvent.click(entry);expect(await screen.findByText("统一批量入库")).toBeVisible();expect(router.state.location.pathname).toBe("/production/orders/receipts/new");const query=new URLSearchParams(router.state.location.search);expect(query.get("warehouse_id")).toBe("1");expect(query.get("owner_id")).toBe("1");expect(query.get("return_to")).toContain("/production/warehouses/1");expect(api.write).not.toHaveBeenCalled();
});
it("routes warehouse record dispatch to the same order-free warehouse flow",async()=>{
 installWarehouseCenterMocks();const router=mount("warehouses","/production/warehouses/1?tab=records&mode=ship");await userEvent.click(await screen.findByRole("link",{name:"新建出货单"}));expect(await screen.findByText("统一仓库出货")).toBeVisible();const query=new URLSearchParams(router.state.location.search);expect(query.get("purpose")).toBe("WAREHOUSE_DISPATCH");expect(query.get("warehouse_id")).toBe("1");expect(query.get("owner_id")).toBe("1");expect(api.write).not.toHaveBeenCalled();
});

it("opens warehouse multi-order receipt with the current warehouse preselected and keeps the return route",async()=>{
 installWarehouseCenterMocks();const original=api.read.getMockImplementation()!;api.read.mockImplementation(path=>path.startsWith("/api/production/receipt-batches/sources?")?Promise.resolve({id:"receipt-batch",revision:"10:2,11:3",status:"CONFIRMED",receipt_warehouse_id:"9",receipt_owner_id:"9",lines:[{id:"101",sku_id:"1001",sku_label:"old label",order_label:"PO10",expected_units:"4",received_units:"0",actual_units:"0",tracking_state:"OPEN"}]}):original(path));
 const back="/production/warehouses/1?tab=records&mode=receive&owner=1";const path=`/production/orders/receipts/new?${new URLSearchParams({orders:"10:2,11:3",warehouse_id:"1",owner_id:"1",return_to:back})}`;
 const router=createMemoryRouter([{path:"/production/*",element:<AuthzGenerationProvider boundary={{principalId:88,roles:["admin"],siteConfigVersionId:1,siteId:1}} onRevoked={()=>undefined}><ProductionWorkspace canWrite/></AuthzGenerationProvider>}],{initialEntries:[path]});render(<RouterProvider router={router}/>);expect(await screen.findByLabelText(/^本次实收入库仓库/)).toHaveValue("1:1");for(const link of screen.getAllByRole("link",{name:"返回仓库"}))expect(link).toHaveAttribute("href",back);await userEvent.click(screen.getByRole("button",{name:"下一步"}));expect(screen.getByRole("button",{name:"导入表格"})).toBeInTheDocument();expect(screen.getByRole("link",{name:"下载入库模板"})).toHaveAttribute("href","/api/production/receipt-batches/table/template?orders=10%3A2%2C11%3A3");expect(api.write).not.toHaveBeenCalled();
});
