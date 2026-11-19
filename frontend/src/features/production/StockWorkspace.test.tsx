import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { act, cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { createMemoryRouter, RouterProvider } from "react-router-dom";
import { AuthzGenerationProvider } from "../../app/AuthzGenerationContext";
import { ApiRequestError } from "../../api/client";
import { StockWorkspace } from "./StockWorkspace";

const display = vi.hoisted(() => ({read: vi.fn<() => Promise<{style_ids: string[]; revision: string; can_manage: boolean}>>()}));
const api = vi.hoisted(() => ({ read: vi.fn<(path: string, options?: unknown) => Promise<unknown>>(), write: vi.fn<(path: string, options: { body: Record<string, unknown>; operationKey?: string }) => Promise<Record<string, unknown>>>() }));
vi.mock("../../api/client", async original => ({ ...await original<typeof import("../../api/client")>(), requestApi: (path: string, options?: unknown) => path.includes("/display-settings") ? display.read() : api.read(path, options), writeApi: api.write }));
const balance = { warehouse_id: "1", owner_id: "1", sku_id: "1001", sku_label: "虚构蓝色 M", style_code: "QA-1101", display_sku: "DEMO-BLUE-M", standard_color: "Blue", standard_size: "M", state: "ready", on_hand_units: "3", free_available_units: "3", qualified_units: "3", pending_units: "0", defective_units: "0", held_units: "0", reserved_units: "0", loan_outstanding_units: "7", revision: "2" };
const doc = { id: "81", kind: "OUT", warehouse_id: "1", owner_id: "1", status: "DRAFT", revision: "1", business_date: "2026-10-14", reason: "借出演练", lines: [{ sku_id: "1001", units: "7", quality: "QUALIFIED", purpose: "BORROW", borrower: "虚构借用人" }] };
async function openTools(kind = "source") { await userEvent.click(await screen.findByRole("button",{name:"更多"})); await userEvent.click(await screen.findByRole("menuitem",{name:kind === "reserve" ? "预留或冻结库存（全范围）" : "原始库存记录与来源"})); }

function mount(path: string, canWrite = true) {
  const roles = canWrite ? ["admin"] : ["viewer"];
  const router = createMemoryRouter([{ path: "/production/stock/*", element: <AuthzGenerationProvider boundary={{ principalId: 1, roles, siteId: 1, siteConfigVersionId: 1 }} onRevoked={() => undefined}><StockWorkspace canWrite={canWrite} /></AuthzGenerationProvider> }], { initialEntries: [path] });
  render(<RouterProvider router={router} />); return router;
}
beforeEach(() => { display.read.mockResolvedValue({style_ids:["1","2"],revision:"1",can_manage:true}); localStorage.setItem("clsen:stock-styles:1:1",JSON.stringify(["1","2"])); Object.defineProperties(HTMLDialogElement.prototype, { showModal: {configurable:true,value:function(this:HTMLDialogElement){this.setAttribute("open","");}}, close: {configurable:true,value:function(this:HTMLDialogElement){this.removeAttribute("open");}} }); vi.stubGlobal("ResizeObserver", class { observe = vi.fn(); disconnect = vi.fn(); });
  api.read.mockReset(); api.write.mockReset(); const NativeRequest = globalThis.Request;
  vi.stubGlobal("Request", class extends NativeRequest { constructor(input: RequestInfo | URL, init?: RequestInit) { const { signal, ...options } = init ?? {}; super(input, options); if (signal) Object.defineProperty(this, "signal", { value: signal }); } });
  api.read.mockImplementation(async (path: string) => {
    await Promise.resolve();
    if (path === "/api/production/skus?contract_version=2") return { items: [{ sku_id: "1001", style_id: "1", style_code: "QA-1101", code: "DEMO-BLUE-M", label: "虚构蓝色 M", standard_color: "Blue", standard_size: "M", status: "active", catalog_version: "DEMO_LOCAL_ONLY-v1" }] };
    if (path.split("?")[0] === "/api/production/inventory/availability") return { items: [balance], scopes: [{ warehouse_id: "1", warehouse_name: "虚构库存仓1", owner_id:"1", owner_name:"自有" }] };
    if (path === "/api/production/inventory/documents/81") return doc;
    if (path.startsWith("/api/production/inventory/forecast?")) return { items: [{ ...balance, projected_on_hand_units: "10" }], excluded_pending: [] };
    if (path.startsWith("/api/production/inventory/history?")) return { actors: [{ actor_id: "1", actor_name: "qa.admin · 虚构管理员" }], items: [{ document_kind: "stock", document_id: "81", revision: "2", actor_id: "1", actor_name: "qa.admin · 虚构管理员", operation_kind: "CONFIRM", reason: "借出演练", created_at: "2026-10-14T01:00:00Z", before_value: { status: "DRAFT" }, after_value: { status: "POSTED", lines: doc.lines } }] };
    if (path.startsWith("/api/production/orders?")) return { items: [] };
    if (path.includes("transit-batches")) return {detail_scope:"whole_batch",items:[],total:0,page:1,page_size:5,as_of:"2026-10-30T12:00:00Z"};
    if (path.startsWith("/api/production/inventory/")) return { items: [] };
    throw new Error(`Unexpected request: ${path}`);
  });
});
afterEach(() => { cleanup(); vi.unstubAllGlobals(); });
describe("independent stock workflows", () => {
  it("keeps posted record essentials visible and moves reversal into a dialog", async () => {
    const original = api.read.getMockImplementation()!;
    api.read.mockImplementation((path, options) => path.endsWith("/documents/81") ? Promise.resolve({ ...doc, status: "POSTED", revision: "2" }) : original(path, options));
    const user = userEvent.setup();
    mount("/production/stock/movements/81");
    await screen.findByRole("heading", { name: "出库记录 #81" });
    expect(screen.getByText("已出库")).toBeInTheDocument();
    expect(screen.getByRole("table", { name: "库存商品明细" })).toHaveTextContent("虚构借用人");
    expect(screen.queryByRole("textbox", { name: "冲销原因" })).not.toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "更多" }));
    expect(screen.getByRole("menuitem", { name: "更正录入错误" })).toHaveAttribute("href", "/production/stock/movements/81/edit");
    await user.click(screen.getByRole("menuitem", { name: "冲销错误记录" }));
    const dialog = await screen.findByRole("dialog", { name: "冲销错误记录" });
    expect(within(dialog).getByRole("button", { name: "确认冲销" })).toBeDisabled();
    await user.type(within(dialog).getByRole("textbox", { name: /冲销原因/ }), "误记借出");
    await user.click(within(dialog).getByRole("button", { name: "取消" }));
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
    expect(api.write).not.toHaveBeenCalled();
  });
  it("retains reversal reason and current revision after a rejected reversal", async () => {
    const original = api.read.getMockImplementation()!;
    api.read.mockImplementation((path, options) => path.endsWith("/documents/81") ? Promise.resolve({ ...doc, status: "POSTED", revision: "2" }) : original(path, options));
    api.write.mockRejectedValue(new ApiRequestError(409, "downstream_loan_exists", "已有归还，请先核对下游"));
    const user = userEvent.setup();
    mount("/production/stock/movements/81");
    await user.click(await screen.findByRole("button", { name: "更多" }));
    await user.click(screen.getByRole("menuitem", { name: "冲销错误记录" }));
    const dialog = await screen.findByRole("dialog", { name: "冲销错误记录" });
    await user.type(within(dialog).getByRole("textbox", { name: /冲销原因/ }), "原记录录错");
    await user.click(within(dialog).getByRole("button", { name: "确认冲销" }));
    expect(await within(dialog).findByText("已有归还，请先核对下游")).toBeInTheDocument();
    expect(within(dialog).getByRole("textbox", { name: /冲销原因/ })).toHaveValue("原记录录错");
    expect(api.write.mock.calls[0]?.[0]).toBe("/api/production/inventory/documents/81/reverse");
    expect(api.write.mock.calls[0]?.[1].body).toMatchObject({ expected_revision: "2", reason: "原记录录错" });
  });
  it("keeps unknown reversal recovery inside its dialog without a second operation", async () => {
    const original = api.read.getMockImplementation()!;
    api.read.mockImplementation((path, options) => path.endsWith("/documents/81") ? Promise.resolve({ ...doc, status: "POSTED", revision: "2" }) : original(path, options));
    api.write.mockRejectedValue(new Error("模拟连接中断"));
    const user = userEvent.setup();
    mount("/production/stock/movements/81");
    await user.click(await screen.findByRole("button", { name: "更多" }));
    await user.click(screen.getByRole("menuitem", { name: "冲销错误记录" }));
    const dialog = await screen.findByRole("dialog", { name: "冲销错误记录" });
    await user.type(within(dialog).getByRole("textbox", { name: /冲销原因/ }), "原记录录错");
    await user.click(within(dialog).getByRole("button", { name: "确认冲销" }));
    await within(dialog).findByText("保存结果未知，先核实原操作");
    expect(within(dialog).getByRole("button", { name: "取消" })).toBeDisabled();
    await user.click(within(dialog).getByRole("button", { name: "重发原操作" }));
    await waitFor(() => expect(api.write).toHaveBeenCalledTimes(2));
    expect(api.write.mock.calls[1]?.[1].operationKey).toBe(api.write.mock.calls[0]?.[1].operationKey);
  });
  it.each([false, true])("keeps read-only or reversed record actions restricted (reversed=%s)", async reversed => {
    const original = api.read.getMockImplementation()!;
    api.read.mockImplementation((path, options) => path.endsWith("/documents/81") ? Promise.resolve({ ...doc, status: reversed ? "REVERSED" : "POSTED" }) : original(path, options));
    const user = userEvent.setup();
    mount("/production/stock/movements/81", reversed);
    await user.click(await screen.findByRole("button", { name: "更多" }));
    expect(screen.queryByRole("menuitem", { name: "冲销错误记录" })).not.toBeInTheDocument();
    expect(screen.queryByRole("menuitem", { name: "更正录入错误" })).not.toBeInTheDocument();
    expect(screen.getByRole("menuitem", { name: "查看操作历史" })).toHaveAttribute("href", "/production/stock/history");
  });
  it("shows receipt quantities and short source links while retaining full order identity", async () => {
    const original = api.read.getMockImplementation()!;
    const reference = "PO-very-long-order-reference-20261106";
    api.read.mockImplementation((path, options) => path.endsWith("/documents/81") ? Promise.resolve({ ...doc, kind: "IN", status: "POSTED", lines: [{ sku_id: "1001", units: "2", quality: "QUALIFIED", purpose: "PRODUCTION_RECEIPT", production_allocations: [{ order_line_id: "5", units: "2" }] }], production_sources: [{ order_line_id: "5", order_id: "11", order_number: reference }] }) : original(path, options));
    mount("/production/stock/movements/81");
    const table = await screen.findByRole("table", { name: "库存商品明细" });
    const source = within(table).getByRole("link", { name: "订单 #11 2 件" });
    expect(source).toHaveAttribute("title", reference);
    expect(source).toHaveAttribute("href", "/production/orders/11");
    expect(within(table).getByText("生产入库")).toBeInTheDocument();
  });
  it("shows quantities and business status in the inventory record list", async () => {
    const original = api.read.getMockImplementation()!;
    api.read.mockImplementation((path, options) => path === "/api/production/inventory/documents" ? Promise.resolve({ items: [{ ...doc, status: "POSTED" }] }) : original(path, options));
    mount("/production/stock/movements");
    const table = await screen.findByRole("table", { name: "库存记录" });
    expect(within(table).getByRole("link", { name: "出库 #81" })).toHaveAttribute("href", "/production/stock/movements/81");
    expect(within(table).getByText("7 件")).toBeInTheDocument();
    expect(within(table).getByText("已出库")).toBeInTheDocument();
  });

  it("changing a quality-movement product clears the previous product's quantities and states", async () => {
    const original = api.read.getMockImplementation()!;
    api.read.mockImplementation((path, options) => path === "/api/production/skus?contract_version=2" ? Promise.resolve({ items: ["1001", "1002"].map(sku_id => ({ sku_id, label: `虚构规格${sku_id}`, status: "active" })) }) : original(path, options));
    const user = userEvent.setup(); mount("/production/stock/movements/new?kind=MOVE&sku_id=1001");
    await screen.findByRole("option", { name: "虚构规格1002" });
    await user.selectOptions(screen.getByLabelText(/^货品状态/), "QUALIFIED");
    await user.selectOptions(screen.getByLabelText(/^目标货品状态/), "PENDING");
    await user.type(screen.getByLabelText(/^本次件数/), "2");
    await user.selectOptions(screen.getByLabelText(/^商品颜色与尺码/), "1002");
    expect(screen.getByLabelText(/^本次件数/)).toHaveValue("");
    expect(screen.getByLabelText(/^货品状态/)).toHaveValue("");
    expect(screen.getByLabelText(/^目标货品状态/)).toHaveValue("");
    expect(api.write).not.toHaveBeenCalled();
  });
  it("preserves location details on an existing same-quality movement", async () => {
    const original = api.read.getMockImplementation()!;
    const lines = [{ sku_id: "1001", purpose: "QUALITY", quality: "QUALIFIED", target_quality: "QUALIFIED", units: "1", location_from: "A1", location_to: "B1" }];
    api.read.mockImplementation((path, options) => path === "/api/production/inventory/documents/81" ? Promise.resolve({ ...doc, kind: "MOVE", lines }) : original(path, options));
    const user = userEvent.setup(); mount("/production/stock/movements/81/edit");
    expect(await screen.findByLabelText(/^来源库位/)).toHaveValue("A1");
    expect(screen.getByLabelText(/^目标库位/)).toHaveValue("B1");
    api.write.mockRejectedValue(new ApiRequestError(409, "test_stop", "保留原库位记录"));
    await user.click(screen.getByRole("button", { name: "保存库存草稿" }));
    await screen.findByText("保留原库位记录");
    expect(api.write.mock.calls[0]?.[1].body.lines).toEqual(lines);
  });
  it("quality changes use no bins and discard location-only input when changing purpose", async () => {
    const user = userEvent.setup(); mount("/production/stock/movements/new?kind=MOVE&intent=MOVE&sku_id=1001");
    await screen.findByRole("option", { name: "虚构蓝色 M" });
    expect(screen.queryByLabelText(/^来源库位/)).not.toBeInTheDocument();
    await user.selectOptions(screen.getByLabelText(/^货品状态/), "QUALIFIED");
    await user.click(screen.getByRole("button", { name: "移动库位" }));
    expect(screen.getByLabelText(/^来源库位/)).toBeRequired();
    await user.type(screen.getByLabelText(/^来源库位/), "A1");
    await user.type(screen.getByLabelText(/^目标库位/), "B1");
    await user.click(screen.getByRole("button", { name: "质量处理" }));
    expect(screen.queryByLabelText(/^来源库位/)).not.toBeInTheDocument();
    const target = screen.getByLabelText(/^目标货品状态/);
    expect(target).toHaveValue("");
    expect(within(target).queryByRole("option", { name: "合格" })).not.toBeInTheDocument();
    await user.selectOptions(target, "PENDING");
    await user.type(screen.getByLabelText(/^本次件数/), "2");
    await user.type(screen.getByLabelText(/^来源依据/), "虚构：重新检验2件");
    api.write.mockRejectedValue(new ApiRequestError(409, "test_stop", "保留质量输入"));
    await user.click(screen.getByRole("button", { name: "保存库存草稿" }));
    await screen.findByText("保留质量输入");
    expect(api.write.mock.calls[0]?.[1].body.lines).toEqual([{ sku_id: "1001", quality: "QUALIFIED", target_quality: "PENDING", units: "2", purpose: "QUALITY" }]);
  });
  it("same-warehouse bin moves keep quality and reject identical bins before writing", async () => {
    const user = userEvent.setup(); mount("/production/stock/movements/new?kind=MOVE&sku_id=1001");
    await screen.findByRole("option", { name: "虚构蓝色 M" });
    await user.click(screen.getByRole("button", { name: "移动库位" }));
    await user.selectOptions(screen.getByLabelText(/^货品状态/), "QUALIFIED");
    await user.type(screen.getByLabelText(/^来源库位/), "A1");
    await user.type(screen.getByLabelText(/^目标库位/), "A1");
    await user.type(screen.getByLabelText(/^本次件数/), "1");
    await user.type(screen.getByLabelText(/^来源依据/), "虚构移库");
    await user.click(screen.getByRole("button", { name: "保存库存草稿" }));
    expect(api.write).not.toHaveBeenCalled();
    expect(screen.getByText("来源与目标库位不能相同，请核对实际移动位置。")).toBeInTheDocument();
    await user.clear(screen.getByLabelText(/^目标库位/)); await user.type(screen.getByLabelText(/^目标库位/), "B1");
    api.write.mockRejectedValue(new ApiRequestError(409, "test_stop", "保留移库输入"));
    await user.click(screen.getByRole("button", { name: "保存库存草稿" }));
    await screen.findByText("保留移库输入");
    expect(api.write.mock.calls[0]?.[1].body.lines).toEqual([{ sku_id: "1001", quality: "QUALIFIED", target_quality: "QUALIFIED", units: "1", purpose: "LOCATION", location_from: "A1", location_to: "B1" }]);
  });
  it("keeps warehouse owner context for inspection display and command", async () => {
    const original = api.read.getMockImplementation()!;
    api.read.mockImplementation((path, options) => path.split("?")[0] === "/api/production/inventory/availability" ? Promise.resolve({ items: [{ ...balance, pending_units: "0" }, { ...balance, owner_id: "2", pending_units: "3" }], scopes: [{ warehouse_id: "1", warehouse_name: "虚构库存仓1", owner_id:"1", owner_name:"自有" }], writes_enabled: true }) : original(path, options));
    const user = userEvent.setup(); mount("/production/stock/movements/new?intent=INSPECT&sku_id=1001&warehouse_id=1&owner_id=2");
    await screen.findByText(/当前待检 3 件/);
    await user.selectOptions(screen.getByLabelText(/^检验结果/), "QUALIFIED");
    await user.type(screen.getByLabelText(/^本次件数/), "2");
    await user.type(screen.getByLabelText(/^来源依据/), "核对当前货权，不能串用货主1余额");
    api.write.mockRejectedValue(new ApiRequestError(409, "test_stop", "保留货权输入"));
    await user.click(screen.getByRole("button", { name: "保存库存草稿" }));
    await screen.findByText("保留货权输入");
    expect(api.write.mock.calls[0]?.[1].body).toMatchObject({ warehouse_id: "1", owner_id: "2", lines: [{ sku_id: "1001", units: "2" }] });
  });
  it("pending inspection starts from a posted receipt without assuming its batch is still pending", async () => {
    const original = api.read.getMockImplementation()!;
    api.read.mockImplementation((path, options) => path === "/api/production/inventory/documents/81" ? Promise.resolve({ ...doc, kind: "IN", status: "POSTED", lines: [{ sku_id: "1001", quality: "PENDING", purpose: "RECEIPT", units: "5" }] }) : path.split("?")[0] === "/api/production/inventory/availability" ? Promise.resolve({ items: [{ ...balance, qualified_units: "0", pending_units: "3", on_hand_units: "3", free_available_units: "0" }], scopes: [{ warehouse_id: "1", warehouse_name: "虚构库存仓1", owner_id:"1", owner_name:"自有" }] }) : original(path, options));
    const user = userEvent.setup(); mount("/production/stock/movements/81");
    await user.click(await screen.findByRole("link", { name: "处理此商品待检库存" }));
    await screen.findByRole("heading", { name: "登记待检处理" });
    expect(screen.getByLabelText(/^来源货品状态/)).toHaveValue("PENDING");
    expect(screen.getByLabelText(/^来源货品状态/)).toBeDisabled();
    expect(screen.getByLabelText(/^检验结果/)).toHaveValue("");
    expect(screen.getByLabelText(/^本次件数/)).toHaveValue("");
    expect(screen.getByText(/当前待检 3 件/)).toBeInTheDocument();
    expect(screen.getByText(/不是本次入库批次的剩余量/)).toBeInTheDocument();
    expect(screen.queryByLabelText(/^来源库位/)).not.toBeInTheDocument();
    await user.selectOptions(screen.getByLabelText(/^检验结果/), "QUALIFIED");
    await user.type(screen.getByLabelText(/^本次件数/), "4");
    expect(screen.getByText("同商品本次处理合计4件，当前待检仅3件，请核对。")).toBeInTheDocument();
    await user.type(screen.getByLabelText(/^来源依据/), "实际已检验，不按原入库量推算");
    await user.click(screen.getByRole("button", { name: "保存库存草稿" }));
    expect(api.write).not.toHaveBeenCalled();
    await user.clear(screen.getByLabelText(/^本次件数/)); await user.type(screen.getByLabelText(/^本次件数/), "2");
    api.write.mockRejectedValue(new ApiRequestError(409, "test_stop", "保留检验输入"));
    await user.click(screen.getByRole("button", { name: "保存库存草稿" }));
    await screen.findByText("保留检验输入");
    expect(api.write.mock.calls[0]?.[1].body).toMatchObject({ kind: "MOVE", warehouse_id: "1", lines: [{ sku_id: "1001", quality: "PENDING", target_quality: "QUALIFIED", units: "2", purpose: "QUALITY" }] });
  });
  it("pending inspection checks combined qualified and defective quantities against current pending stock", async () => {
    const original = api.read.getMockImplementation()!;
    api.read.mockImplementation((path, options) => path.split("?")[0] === "/api/production/inventory/availability" ? Promise.resolve({ items: [{ ...balance, pending_units: "3" }], scopes: [{ warehouse_id: "1", warehouse_name: "虚构库存仓1", owner_id:"1", owner_name:"自有" }] }) : original(path, options));
    const user = userEvent.setup(); mount("/production/stock/movements/new?intent=INSPECT&kind=OUT&sku_id=1001&warehouse_id=1");
    await screen.findByRole("heading", { name: "登记待检处理" });
    await user.selectOptions(screen.getByLabelText(/^检验结果/), "QUALIFIED");
    await user.type(screen.getByLabelText(/^本次件数/), "2");
    await user.type(screen.getByLabelText(/^来源依据/), "部分合格，部分次品");
    await user.click(screen.getByRole("button", { name: "增加明细" }));
    const second = screen.getByRole("region", { name: "变动明细2" });
    await user.selectOptions(within(second).getByLabelText(/^商品颜色与尺码/), "1001");
    await user.selectOptions(within(second).getByLabelText(/^检验结果/), "DEFECTIVE");
    await user.type(within(second).getByLabelText(/^本次件数/), "2");
    expect(screen.getAllByText("同商品本次处理合计4件，当前待检仅3件，请核对。")).toHaveLength(2);
    await user.click(screen.getByRole("button", { name: "保存库存草稿" }));
    expect(api.write).not.toHaveBeenCalled();
    await user.clear(within(second).getByLabelText(/^本次件数/)); await user.type(within(second).getByLabelText(/^本次件数/), "1");
    api.write.mockRejectedValue(new ApiRequestError(409, "test_stop", "保留分拆处理输入"));
    await user.click(screen.getByRole("button", { name: "保存库存草稿" }));
    await screen.findByText("保留分拆处理输入");
    expect(api.write.mock.calls[0]?.[1].body).toMatchObject({ kind: "MOVE", lines: [{ quality: "PENDING", target_quality: "QUALIFIED", units: "2", purpose: "QUALITY" }, { quality: "PENDING", target_quality: "DEFECTIVE", units: "1", purpose: "QUALITY" }] });
  });
  it.each([undefined, "0"])("pending inspection does not invent a pending quantity: %s", async pending_units => {
    const original = api.read.getMockImplementation()!;
    api.read.mockImplementation((path, options) => path.split("?")[0] === "/api/production/inventory/availability" ? Promise.resolve({ items: [{ ...balance, pending_units }], scopes: [{ warehouse_id: "1", warehouse_name: "虚构库存仓1", owner_id:"1", owner_name:"自有" }] }) : original(path, options));
    const user = userEvent.setup(); mount("/production/stock/movements/new?intent=INSPECT&sku_id=1001");
    await screen.findByRole("heading", { name: "登记待检处理" });
    await user.selectOptions(screen.getByLabelText(/^检验结果/), "DEFECTIVE");
    await user.type(screen.getByLabelText(/^本次件数/), "1");
    await user.type(screen.getByLabelText(/^来源依据/), "无确认数量不放行");
    await user.click(screen.getByRole("button", { name: "保存库存草稿" }));
    expect(screen.getByText(pending_units === undefined ? "当前待检数量尚未核实，不能保存处理草稿。" : "当前没有待检库存，无需重复处理。")).toBeInTheDocument();
    expect(api.write).not.toHaveBeenCalled();
  });
  it.each([["DRAFT", true], ["REVERSED", true], ["POSTED", false]] as const)("pending inspection receipt link respects status=%s and manager=%s", async (status, manager) => {
    const original = api.read.getMockImplementation()!;
    api.read.mockImplementation((path, options) => path === "/api/production/inventory/documents/81" ? Promise.resolve({ ...doc, kind: "IN", status, lines: [{ sku_id: "1001", quality: "PENDING", purpose: "RECEIPT", units: "2" }] }) : original(path, options));
    mount("/production/stock/movements/81", manager);
    await screen.findByRole("heading", { name: "入库记录 #81" });
    expect(screen.queryByRole("link", { name: "处理此商品待检库存" })).not.toBeInTheDocument();
  });
  it("pending inspection is reachable from current inventory details", async () => {
    const original = api.read.getMockImplementation()!;
    api.read.mockImplementation((path, options) => path.split("?")[0] === "/api/production/inventory/availability" ? Promise.resolve({ items: [{ ...balance, pending_units: "2" }], scopes: [{ warehouse_id: "1", warehouse_name: "虚构库存仓1", owner_id:"1", owner_name:"自有" }] }) : original(path, options));
    const user = userEvent.setup(); mount("/production/stock"); await openTools();
    await user.click(await screen.findByRole("button", { name: "查看QA-1101 Blue M库存明细" }));
    const dialog = screen.getByRole("region", { name: "库存明细" });
    await user.click(within(dialog).getByRole("button", { name: "处理当前待检库存" }));
    expect(await screen.findByRole("heading", {name:"登记待检处理"})).toBeInTheDocument();
    expect(screen.getAllByRole("dialog")).toHaveLength(1);
  });
  it("order receipt entry binds each chosen product to its source and uses actual quantity once", async () => {
    const original = api.read.getMockImplementation()!;
    api.read.mockImplementation((path, options) => path === "/api/production/orders/91" ? Promise.resolve({ id: "91", status: "CONFIRMED", business_number: "虚构来源订单91", lines: [{ id: "92", sku_id: "1001", expected_units: "20", received_units: "3" }, { id: "93", sku_id: "1002", expected_units: "15", received_units: "0" }] }) : path === "/api/production/skus?contract_version=2" ? Promise.resolve({ items: ["1001", "1002", "1003"].map(sku_id => ({ sku_id, label: "虚构规格" + sku_id, status: "active" })) }) : path.split("?")[0] === "/api/production/inventory/availability" ? Promise.resolve({ items: [balance], scopes: [{ warehouse_id: "1", warehouse_name: "虚构库存仓1", owner_id:"1", owner_name:"自有" }], production_receipts_supported: true, writes_enabled: true }) : original(path, options));
    const user = userEvent.setup();
    mount("/production/stock/movements/new?order_id=91&kind=OUT&sku_id=1003&loan_id=999");
    await screen.findByRole("heading", { name: "从订单登记生产实收" });
    expect(screen.getByRole("link", { name: "虚构来源订单91" })).toHaveAttribute("href", "/production/orders/91");
    expect(screen.getByLabelText(/^商品颜色与尺码/)).toHaveValue("");
    expect(screen.queryByRole("option", { name: "虚构规格1003" })).not.toBeInTheDocument();
    expect(screen.queryByLabelText(/^订单分配件数/)).not.toBeInTheDocument();
    await screen.findByRole("option", { name: "虚构规格1001" });
    await user.selectOptions(screen.getByLabelText(/^商品颜色与尺码/), "1001");
    expect(screen.getByLabelText(/^本次件数/)).toHaveValue("");
    expect(screen.getByLabelText(/^货品状态/)).toHaveValue("");
    await user.type(screen.getByLabelText(/^本次件数/), "2");
    await user.selectOptions(screen.getByLabelText(/^商品颜色与尺码/), "1002");
    await user.clear(screen.getByLabelText(/^本次件数/)); await user.type(screen.getByLabelText(/^本次件数/), "3");
    await user.selectOptions(screen.getByLabelText(/^货品状态/), "PENDING");
    await user.type(screen.getByLabelText(/^来源依据/), "虚构订单实收，不按预计自动填量");
    api.write.mockRejectedValue(new ApiRequestError(409, "test_stop", "保留本次输入"));
    await user.click(screen.getByRole("button", { name: "保存库存草稿" }));
    await screen.findByText("保留本次输入");
    expect(api.write.mock.calls[0]?.[1].body).toMatchObject({ kind: "IN", lines: [{ sku_id: "1002", units: "3", quality: "PENDING", purpose: "PRODUCTION_RECEIPT", production_allocations: [{ order_line_id: "93", units: "3" }] }] });
    expect((api.write.mock.calls[0]?.[1].body.lines as Record<string, unknown>[])[0]).not.toHaveProperty("loan_id");
    await user.click(screen.getByRole("button", { name: "增加明细" }));
    const second = screen.getByRole("region", { name: "变动明细2" });
    await user.selectOptions(within(second).getByLabelText(/^商品颜色与尺码/), "1001");
    await user.type(within(second).getByLabelText(/^本次件数/), "1");
    await user.selectOptions(within(second).getByLabelText(/^货品状态/), "QUALIFIED");
    await user.click(screen.getByRole("button", { name: "保存库存草稿" }));
    expect(api.write.mock.calls[1]?.[1].body).toMatchObject({ lines: [{ sku_id: "1002", production_allocations: [{ order_line_id: "93", units: "3" }] }, { sku_id: "1001", units: "1", purpose: "PRODUCTION_RECEIPT", production_allocations: [{ order_line_id: "92", units: "1" }] }] });
  });
  it("order receipt entry refuses an empty source instead of changing to independent receipt", async () => {
    mount("/production/stock/movements/new?order_id=");
    await screen.findByText("来源订单编号无效，请返回订单核对。");
    expect(screen.queryByRole("button", { name: "保存库存草稿" })).not.toBeInTheDocument();
    expect(api.write).not.toHaveBeenCalled();
  });
  it.each(["DRAFT", "VOID"])("order receipt entry refuses an unavailable source, status=%s", async status => {
    const original = api.read.getMockImplementation()!;
    api.read.mockImplementation((path, options) => path === "/api/production/orders/91" ? Promise.resolve({ id: "91", status, lines: [] }) : path.split("?")[0] === "/api/production/inventory/availability" ? Promise.resolve({ items: [balance], scopes: [], writes_enabled: true, production_receipts_supported: true }) : original(path, options));
    mount("/production/stock/movements/new?order_id=91");
    await screen.findByText("来源订单尚未确认或已作废，不能从此订单登记生产实收。");
    expect(screen.queryByRole("button", { name: "保存库存草稿" })).not.toBeInTheDocument();
    expect(api.write).not.toHaveBeenCalled();
  });
  it("order receipt entry does not fall back to independent receipt when source lookup fails", async () => {
    const original = api.read.getMockImplementation()!;
    api.read.mockImplementation((path, options) => path === "/api/production/orders/91" ? Promise.reject(new ApiRequestError(404, "not_found", "来源订单不存在或不在当前站点")) : path.split("?")[0] === "/api/production/inventory/availability" ? Promise.resolve({ items: [balance], scopes: [], writes_enabled: true, production_receipts_supported: true }) : original(path, options));
    mount("/production/stock/movements/new?order_id=91");
    await screen.findByText("来源订单不存在或不在当前站点");
    expect(screen.queryByRole("button", { name: "保存库存草稿" })).not.toBeInTheDocument();
  });
  it("order receipt entry stays closed on an older service and to viewers", async () => {
    mount("/production/stock/movements/new?order_id=91");
    await screen.findByText("当前服务尚未支持订单生产实收入口，请返回订单核对。");
    expect(screen.queryByRole("button", { name: "保存库存草稿" })).not.toBeInTheDocument();
    cleanup(); mount("/production/stock/movements/new?order_id=91", false);
    await screen.findByText("查看人员不能登记库存变动");
    expect(screen.queryByRole("button", { name: "保存库存草稿" })).not.toBeInTheDocument();
  });
  it("production receipt stays hidden on older services", async () => {
    mount("/production/stock/movements/new?kind=IN");
    await screen.findByRole("option", { name: "实际入库" });
    expect(screen.queryByRole("option", { name: "生产实收入库（关联订单）" })).not.toBeInTheDocument();
  });
  it("production receipt allocates quantities to explicit orders and clears them on purpose change", async () => {
    const original = api.read.getMockImplementation()!;
    api.read.mockImplementation((path, options) => path.split("?")[0] === "/api/production/inventory/availability" ? Promise.resolve({ items: [balance], scopes: [{ warehouse_id: "1", warehouse_name: "虚构库存仓1", owner_id:"1", owner_name:"自有" }], production_receipts_supported: true }) : path.startsWith("/api/production/orders?") ? Promise.resolve({ items: [{ id: "91", business_number: "虚构生产来源", system_number: "PO-91", revision: "1", lines: [{ id: "92", sku_id: "1001", expected_units: "20" }] }], total: 1, page: 1, page_size: 20 }) : original(path, options));
    const user = userEvent.setup(); mount("/production/stock/movements/new?kind=IN&sku_id=1001");
    await screen.findByRole("option", {name:"生产实收入库（关联订单）"});
    await user.selectOptions(await screen.findByLabelText(/^用途/), "PRODUCTION_RECEIPT");
    await user.selectOptions(await screen.findByLabelText(/^来源订单行1/), "92");
    await user.type(screen.getByLabelText(/^订单分配件数1/), "2");
    await user.type(screen.getByLabelText(/^本次件数/), "3");
    expect(screen.getByText("订单分配合计必须等于本次件数。")).toBeInTheDocument();
    await user.clear(screen.getByLabelText(/^本次件数/)); await user.type(screen.getByLabelText(/^本次件数/), "2");
    await user.selectOptions(screen.getByLabelText(/^货品状态/), "QUALIFIED");
    await user.type(screen.getByLabelText(/^来源依据/), "虚构工厂实收");
    api.write.mockRejectedValue(new ApiRequestError(409, "test_stop", "保留输入用于核对"));
    await user.click(screen.getByRole("button", { name: "保存库存草稿" }));
    await screen.findByText("保留输入用于核对");
    expect(api.write.mock.calls[0]?.[1].body).toMatchObject({ lines: [{ purpose: "PRODUCTION_RECEIPT", production_allocations: [{ order_line_id: "92", units: "2" }] }] });
    await user.selectOptions(screen.getByLabelText(/^用途/), "RECEIPT");
    expect(screen.queryByLabelText(/^来源订单行1/)).not.toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "保存库存草稿" }));
    expect((api.write.mock.calls[1]?.[1].body.lines as Record<string, unknown>[])[0]).not.toHaveProperty("production_allocations");
  });
  it.each([true, false])("keeps opening closed while daily inventory is enabled, manager=%s", async manager => {
    const original = api.read.getMockImplementation()!;
    api.read.mockImplementation((path, options) => path.split("?")[0] === "/api/production/inventory/availability" ? Promise.resolve({ items: [balance], scopes: [{ warehouse_id: "1", warehouse_name: "独立虚构验证仓" }], writes_enabled: true, opening_enabled: false }) : original(path, options));
    mount("/production/stock/opening", manager);
    expect(await screen.findByRole("heading", { name: "库存总览" })).toBeInTheDocument();
    expect(screen.queryByRole("link", { name: "登记虚构期初" })).not.toBeInTheDocument();
    expect(screen.getByText(manager ? "库存日常登记已开放" : "当前账号仅可查看库存")).toBeInTheDocument();
    expect(screen.getByText(manager ? /订单和出货请到对应单据页面操作/ : /需要登记时请由有权限的账号操作/)).toBeInTheDocument();
    expect(screen.queryByText(/订单和出货写入暂未开放/)).not.toBeInTheDocument();
    if (manager) {
      await userEvent.click(screen.getByRole("button",{name:"更多"})); expect(screen.getByRole("menuitem", { name: "更新库存" })).toBeInTheDocument();
      expect(screen.getByRole("menuitem", { name: "库存资料核对" })).toBeInTheDocument();
      expect(screen.queryByRole("link", { name: "入库" })).not.toBeInTheDocument();
      await userEvent.click(await screen.findByRole("menuitem", { name: "手工登记库存" }));
      await userEvent.click(await screen.findByRole("button", { name: /^入库/ }));
      expect(await screen.findByRole("option", { name: "独立虚构验证仓" })).toBeInTheDocument();
    } else expect(screen.queryByRole("link", { name: "更新库存" })).not.toBeInTheDocument();
    expect(api.write).not.toHaveBeenCalled();
  });
  it("shows a direct empty state instead of an empty wide loans table", async () => {
    mount("/production/stock/loans");
    expect(await screen.findByRole("heading", { name: "目前没有借出记录" })).toBeInTheDocument();
    expect(screen.queryByRole("table", { name: "借还记录" })).not.toBeInTheDocument();
    expect(screen.getAllByRole("link", { name: "登记借出" })[0]).toHaveAttribute("href", "/production/stock/movements/new?kind=OUT&intent=BORROW");
  });

  it.each([["WAREHOUSE_CONVENTION", "采用仓库库存口径"], ["OPENING_EXTEND", "补齐期初规格"], ["OPENING_SUPERSEDE", "更正版期初接替"]])("shows the agreed warehouse basis and names %s in history", async (operationKind, actionLabel) => {
    const original = api.read.getMockImplementation()!;
    api.read.mockImplementation((path, options) => {
      if (path.split("?")[0] === "/api/production/inventory/availability") return Promise.resolve({ items: [{ ...balance, on_hand_units: "4", qualified_units: "3", pending_units: "1", held_units: "1", free_available_units: "2", unassessed_units: "0", opening_metadata: { quantity_basis: "NORMAL_DISPATCHABLE_V1" } }], scopes: [{ warehouse_id: "1", warehouse_name: "虚构库存仓1", owner_id:"1", owner_name:"自有" }], writes_enabled: false });
      if (path.startsWith("/api/production/inventory/history?")) return Promise.resolve({ items: [{ document_kind: "opening", document_id: "1", revision: "2", actor_name: "qa.manager", operation_kind: operationKind, created_at: "2026-10-16T05:00:00Z", reason: "仓库表正常可发，异常另记", after_value: { lines: [{ sku_id: "1001", quality: "QUALIFIED", purpose: "QUALITY", units: "4" }] } }] });
      return original(path, options);
    });
    mount("/production/stock"); await openTools();
    const table = await screen.findByRole("table", { name: "原始库存记录" });
    const cell = within(table).getByRole("button", { name: "查看QA-1101 Blue M库存明细" });
    expect(cell.closest("tr")).toHaveTextContent("4 / 2");
    
    await userEvent.click(cell);
    const detail = screen.getByRole("region", { name: "库存明细" });
    expect(within(detail).getByText(/仓库表按正常可发库存登记/)).toBeInTheDocument();
    expect(within(detail).getByText("已确认待检")).toBeInTheDocument();
    await userEvent.click(within(detail).getByRole("link", { name: "查看操作历史" }));
    expect(await screen.findByText(new RegExp(`qa.manager.*${actionLabel}`))).toBeInTheDocument();
    expect(api.write).not.toHaveBeenCalled();
  });
  it("keeps unknown totals separate from a confirmed zero and links details to the saved review", async () => {
    const original = api.read.getMockImplementation()!;
    api.read.mockImplementation((path, options) => path.split("?")[0] === "/api/production/inventory/availability" ? Promise.resolve({ items: [{ ...balance, on_hand_units: "0", free_available_units: "0" }, { ...balance, sku_id: "1002", style_code: "QA-1102", display_sku: "DEMO-RED-L", standard_color: "Red", standard_size: "L", state: "not_ready", on_hand_units: null, free_available_units: null, opening_metadata: { review_id: "7fa34135-5e2a-4dbc-94fa-c08427b13966" } }], scopes: [{ warehouse_id: "1", warehouse_name: "虚构库存仓1", owner_id:"1", owner_name:"自有" }], writes_enabled: false }) : original(path, options));
    mount("/production/stock"); await userEvent.click(await screen.findByRole("button",{name:"更多"})); await userEvent.click(screen.getByRole("menuitem",{name:"查看库存汇总"}));
    const summary = await screen.findByRole("region", { name: "展示范围库存与整批运输汇总" });
    expect(within(summary).getAllByText("待核").length).toBeGreaterThan(0);await openTools();
    const table = screen.getByRole("table", { name: "原始库存记录" });
    expect(within(table).getByRole("button", { name: "查看QA-1101 Blue M库存明细" }).closest("tr")).toHaveTextContent("0 / 0");
    await userEvent.click(screen.getByRole("button", { name: "查看QA-1102 Red L库存明细" }));
    const dialog = screen.getByRole("region", { name: "库存明细" });
    expect(within(dialog).getByRole("link", { name: "查看来源资料" })).toHaveAttribute("href", "/production/inventory?review=7fa34135-5e2a-4dbc-94fa-c08427b13966");
    expect(api.write).not.toHaveBeenCalled();
  });
  it("explains the quantities and keeps empty occupancy records available on demand", async () => {
    mount("/production/stock", false); await openTools();
    await screen.findByRole("table", { name: "原始库存记录" });
    expect(screen.getByText(/在途不计在库/)).toBeInTheDocument();
    const occupancy = screen.getByText("暂无占用记录").closest("details")!;
    expect(occupancy).not.toHaveAttribute("open");
    await userEvent.click(screen.getByText("预留与冻结", { exact: false }));
    expect(occupancy).toHaveAttribute("open");
    expect(screen.getAllByText("没有占用记录")).toHaveLength(2);
    expect(api.write).not.toHaveBeenCalled();
  });

  it("describes new multi-product openings without claiming missing historical identity", async () => {
    const original = api.read.getMockImplementation()!;
    api.read.mockImplementation((path, options) => path.startsWith("/api/production/inventory/history?") ? Promise.resolve({ items: [{ document_kind: "opening", document_id: "1", revision: "1", actor_name: "qa.opening", operation_kind: "OPENING", created_at: "2026-10-16T05:00:00Z", after_value: { lines: [{ sku_id: "1001", quality: "UNASSESSED", purpose: "OPENING", units: "17" }, { sku_id: "1002", quality: "UNASSESSED", purpose: "OPENING", units: "4" }] } }] }) : original(path, options));
    mount("/production/stock/history");
    await userEvent.click(await screen.findByText(/qa.opening.*登记期初/));
    expect(screen.getByRole("table", { name: "变更后明细" })).toHaveTextContent("质量未核 · 登记期初");
    expect(screen.queryByText(/旧记录没有可证明的逐行身份/)).not.toBeInTheDocument();
  });
  it("shows registered physical stock separately from unresolved quality and availability", async () => {
    const original = api.read.getMockImplementation()!;
    api.read.mockImplementation((path, options) => path.split("?")[0] === "/api/production/inventory/availability" ? Promise.resolve({ items: [{ ...balance, state: "not_ready", on_hand_units: "17", unassessed_units: "17", qualified_units: "0", free_available_units: null, missing: "期初数量已登记，货主及货品状态待核，当前可发尚未就绪。" }], scopes: [{ warehouse_id: "1", warehouse_name: "花都仓库1号" }], writes_enabled: false }) : original(path, options));
    mount("/production/stock"); await openTools();
    const detailButton = await screen.findByRole("button", { name: "查看QA-1101 Blue M库存明细" });
    expect(detailButton.closest("tr")).toHaveTextContent("17 / 未就绪");
    
    await userEvent.click(detailButton);
    const detail = await screen.findByRole("region", { name: "库存明细" });
    expect(detail).toHaveTextContent("其中17件尚未划分质量");
    expect(within(detail).getByText(/期初数量已登记，货主及货品状态待核/)).toBeInTheDocument();
    await userEvent.click(within(detail).getByRole("button", { name: "返回记录" }));
    await waitFor(() => expect(detailButton).toHaveFocus());
    expect(screen.queryByText(/尚未登记期初，不代表库存为0/)).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "确认占用" })).not.toBeInTheDocument();
  });
  it("keeps unmatched historical stock visible but excludes it from dispatchable totals and controls", async () => {
    const original = api.read.getMockImplementation()!;
    api.read.mockImplementation((path, options) => path.split("?")[0] === "/api/production/inventory/availability" ? Promise.resolve({ items: [
      { ...balance, identity_status: "mapped", on_hand_units: "13", free_available_units: "13" },
      { ...balance, sku_id: "900000000209", sku_label: "待核商品 · 2205 Black / L", style_code: "2205", display_sku: "正式SKU待补", standard_color: "Black", standard_size: "L", identity_status: "pending", state: "not_ready", on_hand_units: "3", free_available_units: null, missing: "历史库存已保留，但尚未与当前服务器商品目录建立唯一对应；当前禁止发货或继续过账。" },
    ], scopes: [{ warehouse_id: "1", warehouse_name: "花都仓库1号" }], writes_enabled: true }) : original(path, options));
    mount("/production/stock"); await userEvent.click(await screen.findByRole("button",{name:"更多"})); await userEvent.click(screen.getByRole("menuitem",{name:"查看库存汇总"}));
    const summary = await screen.findByRole("region", { name: "展示范围库存与整批运输汇总" });
    expect(within(summary).getByText("16")).toBeInTheDocument();
    expect(within(summary).getByText("13")).toBeInTheDocument();await openTools();
    await userEvent.click(screen.getByRole("button", { name: "查看2205 Black L库存明细" }));
    expect(screen.getByRole("region", { name: "库存明细" })).toHaveTextContent("商品身份待核，禁止过账");
    await userEvent.click(screen.getByRole("button", { name: "返回记录" }));
    await openTools("reserve");
    expect(screen.queryByRole("option", { name: /待核商品.*2205 Black/ })).not.toBeInTheDocument();
  });
  it("keeps multiple styles, optional filters and source records in one workspace",async()=>{
    const original=api.read.getMockImplementation()!;const skus=[{sku_id:"1001",style_id:"1",style_code:"STYLE-1",code:"STYLE-1-BLUE-M",label:"Blue M",standard_color:"Blue",standard_size:"M"},{sku_id:"1003",style_id:"2",style_code:"STYLE-2",code:"STYLE-2-BLACK-M",label:"Black M",standard_color:"Black",standard_size:"M"}];
    api.read.mockImplementation((path,options)=>path.includes("/skus?")?Promise.resolve({items:skus}):path.split("?")[0]!.endsWith("/availability")?Promise.resolve({items:skus.map(sku=>({...balance,...sku})),scopes:[{warehouse_id:"1",owner_id:"1",warehouse_name:"矩阵仓"}],writes_enabled:true}):original(path,options));
    mount("/production/stock");await userEvent.click(await screen.findByRole("button",{name:"展开款号STYLE-1"}));await userEvent.click(screen.getByRole("button",{name:"展开款号STYLE-2"}));expect(screen.getByRole("table",{name:"多款库存总表"})).toHaveTextContent("Black");
    await userEvent.click(screen.getByRole("button",{name:"筛选"}));await userEvent.type(screen.getByLabelText("筛选款号、颜色或SKU（可选）"),"Blue");expect(screen.getByRole("table",{name:"多款库存总表"})).not.toHaveTextContent("Black");await userEvent.click(screen.getByRole("button",{name:"清除筛选"}));expect(screen.getByRole("button",{name:"收起款号STYLE-2"})).toBeInTheDocument();
  });
  it("normalizes color display while retaining the exact saved spelling in matrix details",async()=>{
    const original=api.read.getMockImplementation()!;
    api.read.mockImplementation((path,options)=>path.split("?")[0]!.endsWith("/availability")?Promise.resolve({items:[{...balance,standard_color:" ivory   WHITE "}],scopes:[{warehouse_id:"1",warehouse_name:"颜色仓",owner_id:"1"}],writes_enabled:true}):original(path,options));
    mount("/production/stock");await openTools();await userEvent.click(screen.getByRole("button",{name:"查看QA-1101 ivory WHITE M库存明细"}));expect(screen.getByRole("region",{name:"库存明细"})).toHaveTextContent("来源颜色： ivory WHITE");expect(api.write).not.toHaveBeenCalled();
  });
  it("keeps records of separate owners accessible within the same style and size",async()=>{
    const original=api.read.getMockImplementation()!;
    api.read.mockImplementation((path,options)=>path.split("?")[0]!.endsWith("/availability")?Promise.resolve({items:[balance,{...balance,owner_id:"2",standard_color:"blue",on_hand_units:"2",source_reference:"second owner",opening_metadata:{review_id:"color-review"}}],scopes:[{warehouse_id:"1",owner_id:"1",warehouse_name:"颜色仓"}],writes_enabled:true}):original(path,options));
    mount("/production/stock");await openTools();await userEvent.click(screen.getByRole("button",{name:"查看QA-1101 Blue M库存明细"}));const dialog=screen.getByRole("region",{name:"库存明细"});expect(dialog).toHaveTextContent("本格包含2条库存记录，合计5件");await userEvent.click(within(dialog).getByRole("button",{name:/记录2/}));expect(within(dialog).getByRole("link",{name:"查看来源资料"})).toHaveAttribute("href","/production/inventory?review=color-review");expect(api.write).not.toHaveBeenCalled();
  });
  it("shows the server read-only state without fictional labels or stock write controls", async () => {
    const original = api.read.getMockImplementation()!;
    api.read.mockImplementation((path, options) => path.split("?")[0] === "/api/production/inventory/availability" ? Promise.resolve({ items: [], scopes: [], writes_enabled: false }) : original(path, options));
    mount("/production/stock"); await openTools();
    await screen.findByText("库存仅开放查询");
    expect(screen.getByText(/尚未登记期初，不代表库存为0/)).toBeInTheDocument();
    expect(screen.queryByText(/本轮为独立虚构库存/)).not.toBeInTheDocument();
    expect(screen.queryByRole("link", { name: "登记虚构期初" })).not.toBeInTheDocument();
    expect(screen.queryByRole("link", { name: "更新库存" })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "确认占用" })).not.toBeInTheDocument();
    expect(api.write).not.toHaveBeenCalled();
  });
  it("keeps direct write URLs in read-only stock viewing", async () => {
    const original = api.read.getMockImplementation()!;
    api.read.mockImplementation((path, options) => path.split("?")[0] === "/api/production/inventory/availability" ? Promise.resolve({ items: [], scopes: [], writes_enabled: false }) : original(path, options));
    const router = mount("/production/stock/movements/new");
    await screen.findByRole("heading", { name: "库存总览" });
    expect(router.state.location.pathname).toBe("/production/stock");
    expect(screen.queryByRole("button", { name: "保存库存草稿" })).not.toBeInTheDocument();
    expect(api.write).not.toHaveBeenCalled();
  });
  it("clears incompatible relationships when changing product or warehouse without choosing a default SKU", async () => {
    const original = api.read.getMockImplementation()!;
    api.read.mockImplementation((path, options) => {
      if (path === "/api/production/skus?contract_version=2") return Promise.resolve({ items: [
        { sku_id: "1001", label: "QA-1101 · Blue / M", standard_color: "Blue", status: "active" },
        { sku_id: "1002", label: "QA-1101 · Blue / L", standard_color: "Blue", status: "active" },
        { sku_id: "1003", label: "QA-2202 · Red / M", standard_color: "Red", status: "active" },
      ] });
      if (path.split("?")[0]!.endsWith("/availability")) return Promise.resolve({ items: [balance], scopes: [{ warehouse_id: "1", warehouse_name: "虚构仓1" }, { warehouse_id: "2", warehouse_name: "虚构仓2" }] });
      if (path.endsWith("/plans")) return Promise.resolve({ items: [{ id: "91", warehouse_id: "1", owner_id: "1", sku_id: "1001", direction: "IN", remaining_units: "3", source_reference: "虚构实收安排" }, { id: "92", warehouse_id: "1", owner_id: "2", sku_id: "1001", direction: "IN", remaining_units: "9", source_reference: "其他货主不可选" }] });
      return original(path, options);
    });
    const user = userEvent.setup(); mount("/production/stock/movements/new");
    expect(await screen.findByRole("button", { name: /^入库/ })).toHaveAttribute("aria-pressed", "false");
    expect(screen.queryByRole("button", { name: "保存库存草稿" })).not.toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: /^入库/ }));
    await user.type(screen.getByLabelText("搜索款号或 SKU"), "QA-1101");
    expect(screen.getByLabelText(/^商品颜色与尺码/)).toHaveValue("");
    expect(screen.queryByRole("option", { name: "QA-2202 · Red / M" })).not.toBeInTheDocument();
    await user.selectOptions(screen.getByLabelText(/^商品颜色与尺码/), "1001");
    expect(screen.queryByRole("option", { name: /其他货主不可选/ })).not.toBeInTheDocument();
    await user.selectOptions(screen.getByLabelText("关联收发安排（可选）"), "91");
    await user.selectOptions(screen.getByLabelText(/^商品颜色与尺码/), "1002");
    expect(screen.getByLabelText("关联收发安排（可选）")).toHaveValue("");
    expect(screen.getByText(/期初未就绪/)).toBeInTheDocument();
    await user.selectOptions(screen.getByLabelText(/^商品颜色与尺码/), "1001");
    await user.selectOptions(screen.getByLabelText("关联收发安排（可选）"), "91");
    await user.selectOptions(screen.getByLabelText(/^仓库/), "2");
    expect(screen.getByLabelText("关联收发安排（可选）")).toHaveValue("");
    expect(api.write).not.toHaveBeenCalled();
  });
  it("locks a linked return to its original product and shows over-return beside quantity", async () => {
    const original = api.read.getMockImplementation()!;
    api.read.mockImplementation((path, options) => path.endsWith("/loans") ? Promise.resolve({ items: [{ id: "7", warehouse_id: "1", owner_id: "1", sku_id: "1001", outstanding_units: "3", borrower: "虚构借用人" }] }) : original(path, options));
    const user = userEvent.setup(); mount("/production/stock/movements/new?loan_id=7&sku_id=1001&warehouse_id=1");
    await screen.findByRole("option", { name: /虚构借用人.*待归还3件/ });
    expect(screen.getByLabelText(/^商品颜色与尺码/)).toBeDisabled();
    expect(screen.getByLabelText(/^仓库/)).toBeDisabled();
    expect(screen.getByLabelText(/^本次操作/)).toHaveValue("RETURN");
    await user.selectOptions(screen.getByLabelText(/^货品状态/), "PENDING");
    await user.type(screen.getByLabelText(/^本次件数/), "4");
    await user.type(screen.getByLabelText(/^来源依据\/更正原因/), "FICTIONAL 归还");
    await user.click(screen.getByRole("button", { name: "保存库存草稿" }));
    expect(screen.getByLabelText(/^本次件数/)).toHaveAttribute("aria-invalid", "true");
    expect(screen.getByText(/本次最多归还 3 件/)).toBeInTheDocument();
    expect(api.write).not.toHaveBeenCalled();
    await user.clear(screen.getByLabelText(/^本次件数/)); await user.type(screen.getByLabelText(/^本次件数/), "2");
    api.write.mockResolvedValue({ id: "81" });
    await user.click(screen.getByRole("button", { name: "保存库存草稿" }));
    await waitFor(() => expect(api.write).toHaveBeenCalledTimes(1));
    expect(api.write.mock.calls[0]?.[1].body).toMatchObject({ kind: "IN", warehouse_id: "1", lines: [{ sku_id: "1001", units: "2", quality: "PENDING", loan_id: "7" }] });
  });
  it("shows server-calculated stock changes and invalidates a rejected confirmation", async () => {
    const user = userEvent.setup();
    api.write.mockImplementation(async path => {
      await Promise.resolve();
      if (path.endsWith("/preview")) return { preview_hash: "current", changes: [{ sku_id: "1001", quality: "QUALIFIED", delta_units: "-7" }], impacts: [{ warehouse_id: "1", sku_id: "1001", on_hand_before: "10", on_hand_after: "3", free_before: "8", free_after: "1" }] };
      throw new ApiRequestError(409, "inventory_revision_conflict", "库存已变化，请重新预览");
    });
    mount("/production/stock/movements/81");
    await user.click(await screen.findByRole("button", { name: "预览库存影响" }));
    const summary = await screen.findByRole("table", { name: "确认后的库存变化" });
    expect(within(summary).getByText("10 → 3 件")).toBeInTheDocument();
    expect(within(summary).getByText("8 件 → 1 件")).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "确认借出需归还 7 件" }));
    await screen.findByText("库存已变化，请重新预览");
    expect(screen.queryByRole("button", { name: "确认借出需归还 7 件" })).not.toBeInTheDocument();
  });
  it("distinguishes names still loading from identities that remain unknown", async () => {
    let resolveSku!: (value: unknown) => void;
    let resolveScopes!: (value: unknown) => void;
    const pendingSku = new Promise<unknown>(resolve => { resolveSku = resolve; });
    const pendingScopes = new Promise<unknown>(resolve => { resolveScopes = resolve; });
    const original = api.read.getMockImplementation()!;
    api.read.mockImplementation((path: string, options?: unknown) => {
      if (path === "/api/production/skus?contract_version=2") return pendingSku;
      if (path.split("?")[0] === "/api/production/inventory/availability") return pendingScopes;
      if (path === "/api/production/inventory/documents") return Promise.resolve({ items: [doc] });
      return original(path, options);
    });
    mount("/production/stock/movements");
    await screen.findByText(/SKU 1001（商品名称读取中）/);
    expect(screen.getByText(/仓库 1（名称读取中）/)).toBeInTheDocument();
    await act(async () => {
      resolveSku({ items: [{ sku_id: "1001", label: "虚构蓝色 M" }] });
      resolveScopes({ scopes: [{ warehouse_id: "1", warehouse_name: "虚构库存仓1", owner_id:"1", owner_name:"自有" }] });
      await Promise.resolve();
    });
    expect(screen.getByText(/虚构蓝色 M/)).toBeInTheDocument();
    expect(screen.queryByText(/身份待核|名称待核/)).not.toBeInTheDocument();

    cleanup();
    api.read.mockImplementation((path: string, options?: unknown) => {
      if (path === "/api/production/inventory/documents") return Promise.resolve({ items: [{ ...doc, warehouse_id: "9", lines: [{ ...doc.lines[0], sku_id: "999" }] }] });
      return original(path, options);
    });
    mount("/production/stock/movements");
    await screen.findByText(/SKU 999（身份待核）/);
    expect(screen.getByText(/仓库 9（名称待核）/)).toBeInTheDocument();
  });
  it("separates current stock, loans and future forecast and keeps viewers read-only", async () => {
    mount("/production/stock", false); await openTools(); await screen.findByRole("table", { name: "原始库存记录" });
    const detailButton=within(screen.getByRole("table", { name: "原始库存记录" })).getByRole("button",{name:"查看QA-1101 Blue M库存明细"}); expect(detailButton.closest("tr")).toHaveTextContent("3 / 3"); await userEvent.click(detailButton); expect(screen.getByRole("region",{name:"库存明细"})).toHaveTextContent("借出未还7 件"); await userEvent.click(screen.getByRole("button",{name:"返回记录"}));
    expect(screen.queryByRole("link", { name: "登记虚构期初" })).not.toBeInTheDocument(); expect(screen.queryByRole("button", { name: "确认占用" })).not.toBeInTheDocument();
    await userEvent.click(screen.getByRole("button",{name:"更多"})); await userEvent.click(screen.getByRole("menuitem",{name:"预计库存"})); await screen.findByText("10"); expect(screen.queryByRole("link", { name: "登记实际入库" })).not.toBeInTheDocument(); expect(api.write).not.toHaveBeenCalled();
  });
  it("previews before confirmation and refreshes the saved document", async () => {
    const user = userEvent.setup(); let saved = false;
    api.write.mockImplementation(async (path: string) => { await Promise.resolve(); if (path.endsWith("/preview")) return { id: "81", preview_hash: "preview-current", changes: [{ sku_id: "1001", quality: "QUALIFIED", delta_units: "-7" }] }; saved = true; return { ...doc, status: "POSTED", revision: "2" }; });
    const original = api.read.getMockImplementation()!; api.read.mockImplementation((path: string) => path.endsWith("/documents/81") ? Promise.resolve({ ...doc, status: saved ? "POSTED" : "DRAFT", revision: saved ? "2" : "1" }) : original(path));
    mount("/production/stock/movements/81"); await screen.findByText(/草稿，不影响库存/); expect(screen.queryByRole("button", { name: "确认借出需归还 7 件" })).not.toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "预览库存影响" })); await user.click(await screen.findByRole("button", { name: "确认借出需归还 7 件" })); await screen.findByText("已出库");
    expect(api.write.mock.calls[1]?.[1].body).toMatchObject({ expected_revision: "1", preview_hash: "preview-current" });
  });
  it("previews the net correction of a posted record and confirms without a draft stage", async () => {
    const user = userEvent.setup(); let saved = false;
    const posted = { ...doc, status: "POSTED", revision: "2", lines: [{ sku_id: "1001", units: "7", quality: "QUALIFIED", purpose: "CONSUME" }] };
    const original = api.read.getMockImplementation()!;
    api.read.mockImplementation((path: string) => path.endsWith("/documents/81") ? Promise.resolve(saved ? { ...posted, revision: "3", lines: [{ ...posted.lines[0], units: "6" }] } : posted) : original(path));
    let rejected = false;
    api.write.mockImplementation(async (path: string) => { await Promise.resolve(); if (path.endsWith("/preview")) return { id: "81", preview_hash: "posted-net-preview", changes: [{ sku_id: "1001", quality: "QUALIFIED", delta_units: "1" }] }; if (!rejected) { rejected = true; throw new ApiRequestError(409, "inventory_revision_conflict", "预览后库存已变化，请重新预览"); } saved = true; return { ...posted, revision: "3" }; });
    mount("/production/stock/movements/81/edit"); await screen.findByLabelText(/^本次件数/);
    await user.clear(screen.getByLabelText(/^本次件数/)); await user.type(screen.getByLabelText(/^本次件数/), "6"); await user.type(screen.getByLabelText(/^来源依据\/更正原因/), "原七件录错，实际六件");
    expect(screen.queryByRole("button", { name: "确认库存更正" })).not.toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "预览库存更正" })); const table = await screen.findByRole("table", { name: "更正净变化（尚未保存）" }); expect(within(table).getByText("+1")).toBeInTheDocument();
    expect(saved).toBe(false); expect(api.write.mock.calls[0]?.[0]).toBe("/api/production/inventory/documents/81/preview"); expect(api.write.mock.calls[0]?.[1].body).toMatchObject({ mode: "correct", expected_revision: "2", lines: [{ sku_id: "1001", units: "6" }] });
    await user.click(screen.getByRole("button", { name: "确认库存更正" })); await screen.findByText("预览后库存已变化，请重新预览"); expect(screen.getByLabelText(/^本次件数/)).toHaveValue("6"); expect(screen.queryByRole("button", { name: "确认库存更正" })).not.toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "预览库存更正" })); await user.click(await screen.findByRole("button", { name: "确认库存更正" })); await screen.findByText("已出库");
    expect(api.write.mock.calls[3]?.[0]).toBe("/api/production/inventory/documents/81/correct"); expect(api.write.mock.calls[3]?.[1].body).toMatchObject({ expected_revision: "2", preview_hash: "posted-net-preview" }); expect(api.write).toHaveBeenCalledTimes(4);
  });
  it("requires real borrower details, preserves unsaved input and uses one operation after an unknown result", async () => {
    const user = userEvent.setup(); const router = mount("/production/stock/movements/new");
    await user.click(await screen.findByRole("button", { name: /离开仓库并继续跟踪归还/ }));
    await user.selectOptions(screen.getByLabelText(/^货品状态/), "QUALIFIED");
    await screen.findByRole("option", { name: "虚构蓝色 M" });
    await user.selectOptions(screen.getByLabelText(/^商品颜色与尺码/), "1001");
    expect(screen.getByLabelText(/^实际借用人\/对象/)).toBeRequired(); await user.type(screen.getByLabelText(/^实际借用人\/对象/), "借用人甲"); await user.type(screen.getByLabelText(/^本次件数/), "7"); await user.type(screen.getByLabelText(/^来源依据\/更正原因/), "独立虚构借出");
    void router.navigate("/production/stock/loans"); await screen.findByText("还有未保存的内容"); await user.click(screen.getByRole("button", { name: "继续填写" })); expect(screen.getByLabelText(/^本次件数/)).toHaveValue("7");
    api.write.mockRejectedValueOnce(new Error("connection lost")); await user.click(screen.getByRole("button", { name: "保存库存草稿" })); await screen.findByText("保存结果未知，先核实原操作"); expect(screen.getByLabelText(/^本次件数/)).toBeDisabled();
    api.write.mockResolvedValueOnce({ ...doc }); await user.click(screen.getByRole("button", { name: "重发原操作" })); await screen.findByText("出库记录 #81"); expect(api.write.mock.calls[0]?.[1].operationKey).toBe(api.write.mock.calls[1]?.[1].operationKey);
  });
  it("keeps a rejected quantity editable and displays readable actor history", async () => {
    const user = userEvent.setup(); mount("/production/stock/movements/81"); await screen.findByRole("button", { name: "预览库存影响" });
    api.write.mockRejectedValueOnce(new ApiRequestError(409, "insufficient_available_stock", "只允许3件")); await user.click(screen.getByRole("button", { name: "预览库存影响" })); await screen.findByText("只允许3件"); expect(screen.getByRole("link", { name: "编辑草稿" })).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "更多" })); await user.click(screen.getByRole("menuitem", { name: "查看操作历史" })); await screen.findByText(/qa.admin · 虚构管理员.*确认过账/); expect(screen.getByText(/实际借用人 虚构借用人/)).toBeInTheDocument();
    await user.selectOptions(screen.getByLabelText("操作人员"), "1"); await user.click(screen.getByRole("button", { name: "查询用户操作" })); await waitFor(() => expect(api.read).toHaveBeenCalledWith("/api/production/inventory/history?actor_id=1", expect.anything()));
  });
  it("does not convert missing quality counts to zero and previews opening before confirmation", async () => {
    const original = api.read.getMockImplementation()!;
    api.read.mockImplementation((path, options) => path.split("?")[0] === "/api/production/inventory/availability" ? Promise.resolve({ items: [], scopes: [], opening_enabled: true, writes_enabled: true }) : original(path, options));
    const user = userEvent.setup(); mount("/production/stock/opening"); await screen.findByLabelText("DEMO-BLUE-M合格期初");
    fireEvent.change(screen.getByLabelText(/^期初截止日期/), { target: { value: "2026-10-01" } }); await user.type(screen.getByLabelText(/^来源编号/), "FICTIONAL-OPEN-UI"); await user.type(screen.getByLabelText(/^期初依据/), "独立虚构期初"); await user.type(screen.getByLabelText("DEMO-BLUE-M合格期初"), "10");
    await user.click(screen.getByRole("button", { name: "预览期初库存" })); await screen.findByText(/请明确填写所选SKU的三类数量/); expect(api.write).not.toHaveBeenCalled();
    await user.type(screen.getByLabelText("DEMO-BLUE-M待检期初"), "0"); await user.type(screen.getByLabelText("DEMO-BLUE-M次品期初"), "0"); api.write.mockResolvedValueOnce({ posting_enabled: true, lines: [] }); await user.click(screen.getByRole("button", { name: "预览期初库存" })); await screen.findByRole("button", { name: "确认期初库存" });
    expect(api.write.mock.calls[0]?.[0]).toBe("/api/production/inventory/openings/preview"); expect(api.write.mock.calls[0]?.[1].body.lines).toEqual([{ sku_id: "1001", quality: "QUALIFIED", units: "10" }, { sku_id: "1001", quality: "PENDING", units: "0" }, { sku_id: "1001", quality: "DEFECTIVE", units: "0" }]);
  });
  it("can cancel only part of a plan and retains the original plan identity", async () => {
    const user = userEvent.setup(); const original = api.read.getMockImplementation()!;
    api.read.mockImplementation((path: string) => path === "/api/production/inventory/plans" ? Promise.resolve({ items: [{ id: "91", warehouse_id: "1", owner_id: "1", sku_id: "1001", direction: "IN", units: "4", completed_units: "1", cancelled_units: "0", remaining_units: "3", planned_on: "2026-10-20", source_reference: "虚构收货安排", loan_id: null, revision: "2" }] }) : original(path));
    mount("/production/stock/plans"); await user.click(await screen.findByRole("button", { name: "修改日期/数量" })); await user.selectOptions(screen.getByLabelText("安排处理方式"), "cancel"); await user.clear(screen.getByLabelText("本次取消件数")); await user.type(screen.getByLabelText("本次取消件数"), "1"); await user.type(screen.getByLabelText("安排说明/处理原因"), "取消其中一件"); api.write.mockResolvedValueOnce({ id: "91" }); await user.click(screen.getByRole("button", { name: "核对取消影响" })); expect(api.write).not.toHaveBeenCalled(); await user.click(screen.getByRole("button", { name: "确认取消" }));
    await waitFor(() => expect(api.write).toHaveBeenCalled()); expect(api.write.mock.calls[0]?.[0]).toBe("/api/production/inventory/plans/91/cancel"); expect(api.write.mock.calls[0]?.[1].body).toMatchObject({ units: "1", expected_revision: "2", reason: "取消其中一件" });
  });
  it("explains the forecast and carries a plan into an actual movement without assuming the quantity", async () => {
    const original = api.read.getMockImplementation()!;
    const plan = { id: "91", warehouse_id: "1", owner_id: "1", sku_id: "1001", direction: "IN", units: "7", completed_units: "0", cancelled_units: "0", remaining_units: "7", planned_on: "2026-10-20", source_reference: "虚构归还安排", loan_id: null, revision: "1" };
    api.read.mockImplementation((path: string) => path.includes("/forecast?") ? Promise.resolve({ items: [{ ...balance, plans: [plan], projected_on_hand_units: "10" }], excluded_pending: [{ ...plan, id: "92", planned_on: null }] }) : path.endsWith("/plans") ? Promise.resolve({ items: [plan] }) : original(path));
    mount("/production/stock/plans?as_of=2026-10-20");
    const forecast = await screen.findByRole("table", { name: "截至 2026-10-20 的预计库存" });
    expect(within(forecast).getByText("+7")).toBeInTheDocument(); expect(within(forecast).getByText("10")).toBeInTheDocument();
    expect(await screen.findByRole("table", { name: "无日期或逾期待核" })).toBeInTheDocument();
    await userEvent.click(screen.getByRole("link", { name: "登记实际入库" }));
    expect(screen.getByLabelText(/^本次操作/)).toHaveValue("IN"); expect(screen.getByLabelText(/^商品颜色与尺码/)).toHaveValue("1001");
    expect(screen.getByLabelText("关联收发安排（可选）")).toHaveValue("91"); expect(screen.getByLabelText(/^本次件数/)).toHaveValue("");
    expect(api.write).not.toHaveBeenCalled();
  });
  it("requires an explicit partial release with a reason and keeps opening the dialog read-only", async () => {
    const original = api.read.getMockImplementation()!;
    api.read.mockImplementation((path: string) => path.endsWith("/reservations") ? Promise.resolve({ items: [{ id: "55", warehouse_id: "1", sku_id: "1001", order_business_number: "虚构订单", units: "5", consumed_units: "1", released_units: "0", revision: "2", reason: "原预留" }] }) : original(path));
    api.write.mockResolvedValue({ id: "55", revision: "3", released_units: "2" });
    mount("/production/stock"); await openTools(); const user = userEvent.setup();
    await user.click(await screen.findByRole("button", { name: "核对释放" })); expect(api.write).not.toHaveBeenCalled();
    expect(screen.getByText(/当前有效占用 4 件/)).toBeInTheDocument();
    expect(screen.getAllByRole("dialog")).toHaveLength(1);
    expect(screen.getByRole("region",{name:"确认释放订单预留"})).toBeInTheDocument();
    await user.clear(screen.getByLabelText("本次释放件数")); await user.type(screen.getByLabelText("本次释放件数"), "2");
    await user.type(screen.getByLabelText("实际释放原因"), "订单取消两件");
    await user.click(screen.getByRole("button", { name: "确认释放" }));
    await waitFor(() => expect(api.write).toHaveBeenCalledTimes(1));
    expect(api.write.mock.calls[0]?.[1].body).toMatchObject({ expected_revision: "2", units: "2", reason: "订单取消两件" });
    expect(await screen.findByText(/已按本次数量保存/)).toBeInTheDocument();
  });
  it("warns on a product-only unsaved plan and shows a one-line correction before and after", async () => {
    const original = api.read.getMockImplementation()!;
    api.read.mockImplementation((path: string) => path.startsWith("/api/production/inventory/history?") ? Promise.resolve({ items: [{ document_kind: "stock", document_id: "81", revision: "3", actor_id: "1", actor_name: "虚构管理员", operation_kind: "CORRECT", reason: "原七件录错", created_at: "2026-10-14T06:04:00Z", before_value: { lines: [{ sku_id: "1001", quality: "QUALIFIED", purpose: "CONSUME", units: "7" }] }, after_value: { lines: [{ sku_id: "1001", quality: "QUALIFIED", purpose: "CONSUME", units: "6" }] } }] }) : original(path));
    const router = mount("/production/stock/plans"); const user = userEvent.setup();
    await user.selectOptions(await screen.findByLabelText(/^商品颜色与尺码/), "1001");
    void router.navigate("/production/stock/history"); await screen.findByText("还有未保存的内容"); await user.click(screen.getByRole("button", { name: "放弃并离开" }));
    await user.click(await screen.findByText(/虚构管理员 · 更正原记录/));
    const lines = screen.getByRole("table", { name: "逐行数量变化" });
    expect(within(lines).getByText("7 件")).toBeInTheDocument(); expect(within(lines).getByText("6 件")).toBeInTheDocument();
  });
  it("warns after selecting only an inventory product", async () => {
    const router = mount("/production/stock"); await openTools("reserve");
    await screen.findByRole("option", { name: /虚构蓝色 M（虚构库存仓1）/ });
    await userEvent.selectOptions(screen.getByLabelText("库存SKU"), "1:1:1001");
    await act(async () => { await router.navigate("/production/stock/plans"); });
    expect(await screen.findByText("还有未保存的内容")).toBeInTheDocument();
    expect(api.write).not.toHaveBeenCalled();
  });
  it("warns after entering only an opening basis", async () => {
    const original = api.read.getMockImplementation()!;
    api.read.mockImplementation((path, options) => path.split("?")[0] === "/api/production/inventory/availability" ? Promise.resolve({ items: [], scopes: [], opening_enabled: true, writes_enabled: true }) : original(path, options));
    const router = mount("/production/stock/opening");
    await userEvent.type(await screen.findByLabelText(/^期初依据/), "虚构期初待核");
    await act(async () => { await router.navigate("/production/stock"); });
    expect(await screen.findByText("还有未保存的内容")).toBeInTheDocument();
    expect(api.write).not.toHaveBeenCalled();
  });
  it("allows viewing a loan without warning, then warns when its date changes", async () => {
    const loan = { id: "7", document_id: "81", sku_id: "1001", warehouse_id: "1", borrower: "虚构借用人", purpose: "样衣", borrowed_units: "7", returned_units: "0", settled_units: "0", outstanding_units: "7", due_on: "2026-10-20", revision: "1" };
    const original = api.read.getMockImplementation()!;
    api.read.mockImplementation(path => path === "/api/production/inventory/loans" ? Promise.resolve({ items: [loan] }) : original(path));
    const router = mount("/production/stock/loans");
    await screen.findByRole("button", { name: "安排/结清" });
    await act(async () => { await router.navigate("/production/stock/plans"); });
    expect(screen.queryByText("还有未保存的内容")).not.toBeInTheDocument();
    await act(async () => { await router.navigate("/production/stock/loans"); });
    await userEvent.click(await screen.findByRole("button", { name: "安排/结清" }));
    fireEvent.change(screen.getByLabelText("预计归还日（可未知）"), { target: { value: "2026-10-21" } });
    await act(async () => { await router.navigate("/production/stock/plans"); });
    expect(await screen.findByText("还有未保存的内容")).toBeInTheDocument();
    expect(api.write).not.toHaveBeenCalled();
  });
  it("marks conditional stock fields and keeps a location-only move in the same quality", async () => {
    const user = userEvent.setup(); mount("/production/stock/movements/new");
    expect(screen.queryByLabelText(/^本次件数/)).not.toBeInTheDocument();
    await user.click(await screen.findByRole("button", { name: /^取走或消耗/ }));
    expect(screen.getByLabelText(/^货品状态/)).toHaveValue("");
    expect(screen.getByRole("note")).toHaveTextContent("带 * 的字段必填");
    expect(screen.getByLabelText(/^实际发生日期/)).toBeRequired();
    expect(screen.getByLabelText(/^实际发生日期/).closest("div")?.querySelector("label")).toHaveTextContent("*");
    expect(screen.getByLabelText(/^来源依据\/更正原因/)).toBeRequired();
    expect(screen.getByLabelText(/^本次件数/)).toBeRequired();
    expect(screen.getByLabelText("来源/实际领用对象（可选）")).not.toBeRequired();

    await user.click(screen.getByRole("button", { name: /^状态或库位/ }));
    await user.selectOptions(screen.getByLabelText(/^商品颜色与尺码/), "1001");
    await user.selectOptions(screen.getByLabelText(/^货品状态/), "QUALIFIED");
    expect(screen.queryByLabelText(/^来源库位/)).not.toBeInTheDocument();
    expect(screen.queryByLabelText(/^目标库位/)).not.toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "移动库位" }));
    expect(screen.queryByLabelText(/^目标货品状态/)).not.toBeInTheDocument();
    expect(screen.getByLabelText(/^来源库位/)).toBeRequired();
    expect(screen.getByLabelText(/^目标库位/)).toBeRequired();
    expect(screen.getByLabelText(/^目标库位/).closest("div")?.querySelector("label")).toHaveTextContent("*");
    await user.selectOptions(screen.getByLabelText(/^货品状态/), "DEFECTIVE");
    expect(screen.getByLabelText(/^货品状态/)).toHaveValue("DEFECTIVE");

    await user.click(screen.getByRole("button", { name: /^盘点调整/ }));
    expect(screen.getByLabelText("盘点商品1实盘总数")).toBeRequired();
    expect(screen.getByRole("link",{name:"下载盘点模板"})).toBeInTheDocument();
    expect(screen.getByLabelText("盘点商品1截止日期")).toBeRequired();
    expect(screen.getByLabelText("盘点商品1证据")).toBeRequired();
    expect(api.write).not.toHaveBeenCalled();
  });
  it("uses the count purpose when opening the adjustment URL directly", async () => {
    const user = userEvent.setup(); api.write.mockResolvedValue({ id: "90" });
    const original = api.read.getMockImplementation()!;
    api.read.mockImplementation((path, options) => path === "/api/production/inventory/documents/90" ? Promise.resolve({ ...doc, id: "90", kind: "ADJUST", reason: "虚构盘点调整", lines: [{ sku_id: "1001", units: "3", quality: "QUALIFIED", purpose: "COUNT", counted_on: "2026-10-14", evidence: "虚构盘点依据" }] }) : original(path, options));
    mount("/production/stock/movements/new?kind=ADJUST");
    await screen.findByRole("option", { name: /虚构蓝色 M/ });
    await user.selectOptions(await screen.findByLabelText("盘点商品1"), "1001");
    await user.selectOptions(screen.getByLabelText("盘点商品1状态"), "QUALIFIED");
    await user.type(screen.getByLabelText("盘点商品1实盘总数"), "3");
    fireEvent.change(screen.getByLabelText("盘点商品1截止日期"), { target: { value: "2026-10-14" } });
    await user.type(screen.getByLabelText("盘点商品1证据"), "虚构盘点依据");
    await user.type(screen.getByLabelText(/^来源依据\/更正原因/), "虚构盘点调整");
    await user.click(screen.getByRole("button", { name: "保存库存草稿" }));
    await waitFor(() => expect(api.write).toHaveBeenCalled());
    expect(api.write.mock.calls[0]?.[1].body.lines).toEqual([{ sku_id: "1001", units: "3", quality: "QUALIFIED", purpose: "COUNT", target_quality: "", counted_on: "2026-10-14", evidence: "虚构盘点依据" }]);
    expect(await screen.findByRole("heading", { name: "盘点调整记录 #90" })).toBeInTheDocument();
  });
});

it("uses the current catalog label after code assignment while keeping stock unchanged", async () => {
  const original = api.read.getMockImplementation()!;
  api.read.mockImplementation((path: string, options?: unknown) => {
    if (path === "/api/production/skus?contract_version=2") return Promise.resolve({items:[{sku_id:"1001",code:"QA-AMAZON-CONFIRMED",label:"QA-AMAZON-CONFIRMED · Blue / M",standard_color:"Blue",standard_size:"M"}]});
    if (path.split("?")[0] === "/api/production/inventory/availability") return Promise.resolve({items:[{...balance,sku_label:"正式SKU待补"}],scopes:[{warehouse_id:"1",warehouse_name:"虚构库存仓1"}]});
    return original(path, options);
  });
  mount("/production/stock"); await openTools();
  const table = await screen.findByRole("table",{name:"原始库存记录"});

  expect(within(table).getByRole("button",{name:"查看QA-1101 Blue M库存明细"})).toBeInTheDocument();
  expect(table).toHaveTextContent("3 / 3");
  await openTools("reserve");
  expect(screen.getByRole("option",{name:"QA-AMAZON-CONFIRMED · Blue / M（虚构库存仓1） · 货权 1"})).toBeInTheDocument();
  expect(screen.queryByText("正式SKU待补")).not.toBeInTheDocument();
  expect(api.write).not.toHaveBeenCalled();
});

it("preserves an unsaved occupancy form across collapsing a style and the action panel",async()=>{
  mount("/production/stock");await openTools("reserve");await userEvent.selectOptions(screen.getByLabelText("库存SKU"),"1:1:1001");
  await userEvent.click(screen.getByRole("button",{name:"展开款号QA-1101"}));await userEvent.click(screen.getByRole("button",{name:"收起款号QA-1101"}));await userEvent.click(screen.getByRole("button",{name:"收起办理"}));await userEvent.click(screen.getByRole("button",{name:"更多"}));await userEvent.click(screen.getByRole("menuitem",{name:"继续当前办理"}));expect(screen.getByLabelText("库存SKU")).toHaveValue("1:1:1001");expect(api.write).not.toHaveBeenCalled();
});
it("shares availability and recovers its failed root policy from refresh",async()=>{
  const original=api.read.getMockImplementation()!;let fail=true;api.read.mockImplementation((path,options)=>path.split("?")[0]!.endsWith("/availability")&&fail?Promise.reject(new Error("SIM stock unavailable")):original(path,options));
  mount("/production/stock");await screen.findByText("库存读取未完成");expect(api.read.mock.calls.filter(([path])=>path.split("?")[0]!.endsWith("/availability"))).toHaveLength(1);expect(screen.queryByRole("link",{name:"登记库存业务"})).not.toBeInTheDocument();await userEvent.click(screen.getByRole("button",{name:"更多"}));expect(screen.queryByRole("menuitem",{name:"更新库存"})).not.toBeInTheDocument();await userEvent.keyboard("{Escape}");fail=false;await userEvent.click(screen.getByRole("button",{name:"重试库存读取"}));await waitFor(()=>expect(screen.queryByText("库存读取未完成")).not.toBeInTheDocument());await userEvent.click(screen.getByRole("button",{name:"更多"}));expect(await screen.findByRole("menuitem",{name:"更新库存"})).toBeInTheDocument();expect(screen.queryByRole("link",{name:"登记库存业务"})).not.toBeInTheDocument();
});
it("uses scoped quantity details and retains all original record evidence without a duplicate matrix",async()=>{
  mount("/production/stock?sku_id=1001&sku_detail=1");expect(await screen.findByRole("region",{name:"当前SKU质量与占用"})).toHaveTextContent("借出未还7件");await userEvent.click(screen.getByRole("button",{name:"关闭数量明细"}));await openTools();await userEvent.click(screen.getByRole("button",{name:"查看QA-1101 Blue M库存明细"}));expect(screen.getByRole("region",{name:"库存明细"})).toHaveTextContent("借出未还7 件");expect(screen.queryByRole("table",{name:/颜色尺码/})).not.toBeInTheDocument();expect(api.write).not.toHaveBeenCalled();
});
it("guards replacing an unsaved action and true page navigation while allowing table presentation",async()=>{
  const router=mount("/production/stock");await openTools("reserve");await userEvent.selectOptions(screen.getByLabelText("库存SKU"),"1:1:1001");await userEvent.click(screen.getByRole("button",{name:"展开款号QA-1101"}));expect(screen.queryByText("还有未保存的内容")).not.toBeInTheDocument();
  await openTools();expect(await screen.findByText("还有未保存的办理内容")).toBeInTheDocument();await userEvent.click(screen.getByRole("button",{name:"继续当前办理"}));expect(screen.getByLabelText("库存SKU")).toHaveValue("1:1:1001");await act(async()=>{await router.navigate("/production/stock/plans");});expect(await screen.findByText("还有未保存的内容")).toBeInTheDocument();expect(screen.getByRole("dialog",{name:"还有未保存的内容"}).closest("dialog")).not.toBeNull();expect(api.write).not.toHaveBeenCalled();await userEvent.click(screen.getByRole("button",{name:"继续填写"}));expect(screen.getByLabelText("库存SKU")).toHaveValue("1:1:1001");
});
it("seeds scoped occupancy and submits the selected owner and balance revision through the original command",async()=>{
  const original=api.read.getMockImplementation()!;
  api.read.mockImplementation((path,options)=>path.split('?')[0]!.endsWith('/availability')?Promise.resolve({items:[{...balance,owner_id:'2'}],scopes:[{warehouse_id:'1',owner_id:'2',owner_name:'第二货权',warehouse_name:'虚构库存仓1'}],writes_enabled:true}):original(path,options));
  api.write.mockRejectedValue(new ApiRequestError(409,'test_stop','本次不保存'));
  mount('/production/stock?sku_id=1001&sku_detail=1&stock_scope=1&stock_owner=2');
  await userEvent.click(await screen.findByRole('button',{name:'办理'}));await userEvent.click(screen.getByRole('menuitem',{name:'预留或冻结库存'}));
  expect(await screen.findByLabelText('库存SKU')).toHaveValue('1:2:1001');expect(screen.getByLabelText('货权')).toHaveValue('2');expect(api.write).not.toHaveBeenCalled();
  await userEvent.selectOptions(screen.getByLabelText('占用类型'),'holds');await userEvent.type(screen.getByLabelText('占用数量'),'1');await userEvent.type(screen.getByLabelText('占用原因'),'虚构范围核对');await userEvent.click(screen.getByRole('button',{name:'确认占用'}));await screen.findByText('本次不保存');
  expect(api.write.mock.calls[0]?.[1].body).toMatchObject({warehouse_id:'1',owner_id:'2',sku_id:'1001',expected_balance_revision:'2'});
});
it("keeps an unknown occupancy command mounted while browsing and refuses to discard it for another action",async()=>{
  api.write.mockRejectedValue(new ApiRequestError(500,'test_unknown','虚构未知结果'));mount('/production/stock');await openTools('reserve');await userEvent.selectOptions(screen.getByLabelText('库存SKU'),'1:1:1001');await userEvent.selectOptions(screen.getByLabelText('占用类型'),'holds');await userEvent.type(screen.getByLabelText('占用数量'),'1');await userEvent.type(screen.getByLabelText('占用原因'),'虚构核对');await userEvent.click(screen.getByRole('button',{name:'确认占用'}));await screen.findByText('保存结果未知，先核实原操作');
  await userEvent.click(screen.getByRole('button',{name:'展开款号QA-1101'}));await openTools();expect(await screen.findByText('先核实保存结果')).toBeInTheDocument();expect(screen.queryByRole('button',{name:'放弃并更换'})).not.toBeInTheDocument();expect(api.write).toHaveBeenCalledTimes(1);
});
it("opens the original borrow form inline and retains it while the style is collapsed",async()=>{
  mount('/production/stock?sku_id=1001&sku_detail=1&stock_scope=1&stock_owner=1');await userEvent.click(await screen.findByRole('button',{name:'办理'}));await userEvent.click(screen.getByRole('menuitem',{name:'借出库存'}));
  const borrower=await screen.findByLabelText(/^实际借用人/);await userEvent.type(borrower,'虚构借用人');expect(screen.getAllByRole('dialog')).toHaveLength(1);await userEvent.click(screen.getByRole('button',{name:'收起款号QA-1101'}));expect(borrower).toHaveValue('虚构借用人');expect(api.write).not.toHaveBeenCalled();
});
it("opens partial return through scoped loan records using the original inline return form",async()=>{
  const original=api.read.getMockImplementation()!;api.read.mockImplementation((path,options)=>path.endsWith('/loans')?Promise.resolve({items:[{id:'71',document_id:'81',warehouse_id:'1',owner_id:'1',sku_id:'1001',borrower:'虚构借用人',borrowed_units:'7',returned_units:'0',settled_units:'0',outstanding_units:'7',revision:'2'}]}):original(path,options));
  mount('/production/stock?sku_id=1001&sku_detail=1&stock_scope=1&stock_owner=1');await userEvent.click(await screen.findByRole('button',{name:'办理'}));await userEvent.click(screen.getByRole('menuitem',{name:'借出与归还'}));await userEvent.click(await screen.findByRole('button',{name:'登记部分归还'}));expect(await screen.findByLabelText(/^货品状态/)).toBeInTheDocument();expect(screen.getAllByRole('dialog')).toHaveLength(1);expect(api.write).not.toHaveBeenCalled();
});
it.each([['取走或消耗','登记取走或消耗'],['质量或库位变更','登记质量或位置变化'],['盘点调整','登记盘点调整'],['处理当前待检库存','登记待检处理']])('opens the original scoped %s form inline',async(label,title)=>{
  if(label === '处理当前待检库存'){const original=api.read.getMockImplementation()!;api.read.mockImplementation((path,options)=>path.split('?')[0]!.endsWith('/availability')?Promise.resolve({items:[{...balance,pending_units:'2'}],scopes:[{warehouse_id:'1',owner_id:'1',warehouse_name:'虚构库存仓1'}],writes_enabled:true}):original(path,options));}
  mount('/production/stock?sku_id=1001&sku_detail=1&stock_scope=1&stock_owner=1');await userEvent.click(await screen.findByRole('button',{name:'办理'}));await userEvent.click(screen.getByRole('menuitem',{name:label}));expect(await screen.findByRole('heading',{name:title})).toBeInTheDocument();expect(screen.getAllByRole('dialog')).toHaveLength(1);expect(api.write).not.toHaveBeenCalled();
});
it('keeps quantity details and handling inside the same persistent window',async()=>{
  mount('/production/stock?sku_id=1001&sku_detail=1&stock_scope=1&stock_owner=1');
  const window = await screen.findByRole('dialog');
  await userEvent.click(screen.getByRole('button',{name:'办理'}));
  expect(screen.getByRole('menu').closest('dialog')).toBe(window);
  await userEvent.click(screen.getByRole('menuitem',{name:'预留或冻结库存'}));
  const reason = await screen.findByLabelText('占用原因');
  expect(screen.getAllByRole('dialog')).toEqual([window]);
  await userEvent.type(reason,'保留在同一窗口');
  await userEvent.click(screen.getByRole('button',{name:/^库存明细$/}));
  await userEvent.click(screen.getByRole('button',{name:/^当前办理$/}));
  expect(reason).toHaveValue('保留在同一窗口');
  await userEvent.click(screen.getByRole('button',{name:'收起办理'}));
  expect(screen.queryByRole('dialog')).not.toBeInTheDocument();
  await userEvent.click(screen.getByRole('button',{name:'更多'}));
  await userEvent.click(screen.getByRole('menuitem',{name:'继续当前办理'}));
  expect(screen.getByLabelText('占用原因')).toHaveValue('保留在同一窗口');
  expect(screen.getAllByRole('dialog')).toHaveLength(1);
  expect(api.write).not.toHaveBeenCalled();
});
it('explains a mismatched occupancy scope instead of silently ignoring confirmation',async()=>{
  const original=api.read.getMockImplementation()!;api.read.mockImplementation((path,options)=>path.split('?')[0]!.endsWith('/availability')?Promise.resolve({items:[balance],scopes:[{warehouse_id:'1',owner_id:'1',warehouse_name:'虚构库存仓1'},{warehouse_id:'2',owner_id:'1',warehouse_name:'未建账仓'}],writes_enabled:true}):original(path,options));
  mount('/production/stock');await openTools('reserve');await userEvent.selectOptions(screen.getByLabelText('库存SKU'),'1:1:1001');await userEvent.selectOptions(screen.getByLabelText('仓库'),'2');await userEvent.selectOptions(screen.getByLabelText('占用类型'),'holds');await userEvent.type(screen.getByLabelText('占用数量'),'1');await userEvent.type(screen.getByLabelText('占用原因'),'虚构范围核对');
  // Native required validation normally blocks this stale selection; also check the submit handler itself.
  fireEvent.submit(screen.getByRole('button',{name:'确认占用'}).closest('form')!);expect(await screen.findByText('请选择有效的库存范围')).toBeInTheDocument();expect(api.write).not.toHaveBeenCalled();
  await userEvent.selectOptions(screen.getByLabelText('库存SKU'),'1:1:1001');expect(screen.queryByText('请选择有效的库存范围')).not.toBeInTheDocument();expect(api.write).not.toHaveBeenCalled();
});


it("carries the exact warehouse and owner of an outbound arrangement into the unified shipment flow", async () => {
  const original=api.read.getMockImplementation()!;
  const plan={id:"91",warehouse_id:"1",owner_id:"7",sku_id:"1001",direction:"OUT",units:"1",remaining_units:"1",completed_units:"0",cancelled_units:"0",revision:"1",source_reference:"SIM-PLAN"};
  api.read.mockImplementation(path=>path.endsWith("/plans")?Promise.resolve({items:[plan]}):original(path));
  mount("/production/stock/plans");
  const link=await screen.findByRole("link",{name:"登记销售发货"});
  const query=new URLSearchParams(link.getAttribute("href")!.split("?")[1]);
  expect(Object.fromEntries(query)).toMatchObject({plan_id:"91",warehouse_id:"1",owner_id:"7",sku_id:"1001",flow:"guided",purpose:"WAREHOUSE_DISPATCH"});
  expect(api.write).not.toHaveBeenCalled();
});
