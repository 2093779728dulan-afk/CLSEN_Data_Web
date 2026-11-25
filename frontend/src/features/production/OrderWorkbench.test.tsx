import { act, cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { createMemoryRouter, RouterProvider } from "react-router-dom";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { AuthzGenerationProvider } from "../../app/AuthzGenerationContext";
import { ApiRequestError } from "../../api/client";
import { ProductionWorkspace } from "./ProductionWorkspace";
import type { Document } from "./types";
import { orderProductName, progressChanges, progressNumber } from "./orderProgress";
import { orderPending } from "./orderPending";
import { isBusinessWrite, productionDataChanged } from "../../api/productionReadCache";
type WriteOptions = { body: Record<string, unknown>; operationKey: string };
const api = vi.hoisted(() => ({ read: vi.fn<(path: string) => Promise<unknown>>(), write: vi.fn<(path: string, options: WriteOptions) => Promise<unknown>>() }));
vi.mock("../../api/client", async original => ({ ...await original<typeof import("../../api/client")>(), requestApi: api.read, writeApi: async (path:string,options:WriteOptions) => { const result=await api.write(path,options); if(isBusinessWrite(path,"POST"))productionDataChanged(); return result; } }));
const order: Document = { id: "10", system_number: "PO-QA-10", business_number: "虚构工作台订单", business_date: "2026-10-22", factory_id: "3", factory_name: "青禾示例厂", receipt_warehouse_id: "900", receipt_owner_id: "1", destination: "虚构集货点", notes: "", status: "CONFIRMED", revision: "2", expected_units: "100", actual_units: "20", received_units: "60", lines: [{ id: "101", sku_id: "1001", sku_label: "QA-Blue-M", expected_units: "100", actual_units: "20", difference_units: "80", produced_units: "80", received_units: "60" }], shipments: [], history: [] };
beforeEach(() => {
  api.read.mockReset(); api.write.mockReset();
  const NativeRequest = globalThis.Request;
  vi.stubGlobal("Request", class extends NativeRequest { constructor(input: RequestInfo | URL, init?: RequestInit) { const { signal, ...options } = init || {}; super(input, options); if (signal) Object.defineProperty(this, "signal", { value: signal }); } });
  api.read.mockImplementation(async (path: string) => {
    await Promise.resolve();
    if (path === "/api/production/workbench") return { version: 1 };
    if (path.startsWith("/api/production/warehouses?")) return {items:[{id:"900",name:"虚构仓900",type:"FACTORY",status:"ACTIVE"}],total:1,page:1,page_size:50};
    if (path.startsWith("/api/production/factories?")) return { items: [{ id: "3", name: "青禾示例厂", order_count: "1" }], total: 1 };
    if (path.startsWith("/api/production/orders?")) return { items: [order], page: 1, page_size: 20, total: 1 };
    if (path === "/api/production/orders/10") return order;
    if (path.includes("inventory/availability?") && !path.includes("projection=")) return { state: "ready", dispatch_allowed_units: "40", own_reserved_units: "0" };
    if (path.endsWith("inventory/availability") || path.endsWith("inventory/availability?projection=scopes")) return { writes_enabled: true, scopes: [{ warehouse_id: "900", owner_id: "1", warehouse_name: "虚构仓900", owner_name: "本公司", warehouse_type: "FACTORY", warehouse_status: "ACTIVE" }], items: [] };
    if (path.includes("/skus?")) return { items: [{ sku_id: "1001", label: "QA-Blue-M", status: "active", code: "QA-Blue-M", catalog_version: "DEMO_LOCAL_ONLY-v1" }] };
    throw Error(`Unexpected QA path ${path}`);
  });
});
afterEach(() => { cleanup(); vi.unstubAllGlobals(); });
function mount(entry = "/production/orders/10", canWrite = true) {
  const router = createMemoryRouter([{ path: "/production/*", element: <AuthzGenerationProvider boundary={{ principalId: 1, roles: canWrite ? ["admin"] : ["viewer"], siteId: 1, siteConfigVersionId: 1 }} onRevoked={() => undefined}><ProductionWorkspace canWrite={canWrite} /></AuthzGenerationProvider> }], { initialEntries: [entry] });
  render(<RouterProvider router={router} />); return router;
}
async function openOperation(tab: string) {
  if (tab === "ship") return screen.findByRole("dialog", { name: "新建出货单" });
  await userEvent.click(await screen.findByRole("button", { name: tab === "receive" ? "新建入库" : "新建出货单" }));
  return screen.findByRole("dialog", { name: tab === "receive" ? "入库" : "新建出货单" });
}
it("saves a user-created production status without submitting quantity changes", async () => {
  api.write.mockResolvedValue({ ...order, revision: "3", lines: order.lines!.map(line => ({ ...line, production_status: "面料待到厂" })) });
  mount();
  await openProgress();
  expect(screen.queryByText("填写说明")).not.toBeInTheDocument();
  expect(screen.getByRole("button", { name: "核对并保存进度" })).toHaveTextContent("保存");
  expect(screen.getByText("批量填写", { exact: true }).closest("details")).not.toHaveAttribute("open");
  const status = screen.getByLabelText("QA-Blue-M 生产状态");
  await userEvent.type(status, "面料待到厂");
  expect(screen.getByText("修改 1 项")).toBeVisible();
  expect(screen.queryByText(/累计生产 80 → 80/)).not.toBeInTheDocument();
  await userEvent.click(screen.getByRole("button", { name: "核对并保存进度" }));
  await waitFor(() => expect(api.write).toHaveBeenCalled());
  expect(api.write.mock.calls[0]![1].body.lines).toEqual([{ order_line_id: "101", production_status: "面料待到厂" }]);
});

it("can clear a manual production status while retaining unknown production", () => {
  const input = { ...order, lines: order.lines!.map(line => ({ ...line, produced_units: null, production_status: "车缝" })) };
  expect(progressChanges(input, { "101": "" }, { "101": "" })).toEqual([{ order_line_id: "101", production_status: "" }]);
});

async function openProgress() {
  await userEvent.click(await screen.findByRole("button", { name: "更新生产进度" }));
  return screen.findByLabelText(/累计实际生产数量/);
}
async function enterInlineImport() {
  await waitFor(()=>expect(screen.queryByLabelText(/本次导入的XLSX文件/) || screen.queryByLabelText(/下单XLSX文件/) || screen.queryByRole("button",{name:"下一步"})).toBeTruthy());
  if (!screen.queryByLabelText(/本次导入的XLSX文件/) && !screen.queryByLabelText(/下单XLSX文件/)) await userEvent.click(screen.getByRole("button",{name:"下一步"}));
}
describe("unified production workbench", () => {
  it("offers the four-field template and keeps unknown source rows visible without creating a draft", async () => {
    api.write.mockResolvedValue({ preview_id: "qa-v4", filename: "qa.xlsx", rows: [], issues: [{ row: 9, message: "SKU尚未唯一关联" }], command: { business_date: "2026-10-30" }, source_check: { candidates: [] }, source_table: { sheet: "11月-12月", source_units: "7", excluded_rows: [10], excluded_sheets: ["Sheet1"], rows: [{ source_row: 9, order_date: "2026-10-30", style_code: "0012", sku_code: "0012-sand beige-M", expected_units: "7", mapping_status: "UNRESOLVED" }] } });
    mount("/production/orders/new?method=table");
    expect(await screen.findByRole("link", { name: "下载下单模板" })).toHaveAttribute("href", "/api/production/files/orders/template?version=v4");
    expect(screen.queryByRole("button", { name: "表格导入" })).not.toBeInTheDocument();
    await screen.findByRole("option",{name:"青禾示例厂"});
    await userEvent.selectOptions(screen.getByLabelText(/生产工厂（一单一家）/), "3");
    await userEvent.selectOptions(screen.getByLabelText(/生产完成后入库仓库/), "900:1");
    await userEvent.upload(screen.getByLabelText("下单XLSX文件（不超过2MB）"), new File(["fictional table"], "qa.xlsx"));
    
    expect(await screen.findByRole("table", { name: "原下单表四字段核对" })).toHaveTextContent("0012-sand beige-M");
    expect(screen.getByText("未唯一关联，请先核对商品资料")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "生成订单草稿" })).not.toBeInTheDocument();
    expect(api.write).toHaveBeenCalledTimes(1);
  });
  it("exports all lines of the current order even for a viewer", async () => {
    mount("/production/orders/10?line=101", false);
    expect(await screen.findByRole("link", { name: "导出下单表" })).toHaveAttribute("href", "/api/production/orders/10/table");
    expect(api.write).not.toHaveBeenCalled();
  });
  it.each(["receive", "ship"])("imports %s into the shared wizard, edits the same data and saves only a draft", async tab => {
    const kind = tab === "receive" ? "receipt" : "packing";
    api.write.mockImplementation(path => Promise.resolve(path.includes("/tables/") ? {
      table_baseline:{id:`table-baseline-${"b".repeat(64)}`,kind,filename:"qa.xlsx",rows:[{key:tab==="receive"?"101":"1001",label:"QA-Blue-M",row:2,values:tab==="receive"?{"合格":"4","待检":"2","次品":"0"}:{"出货数量":"6","装箱分配":"QA-BOX：6"}}]},
      kind, filename: "qa.xlsx", source_digest: "qa-digest", order_id: "10", order_revision: "2", total_units: "6", box_count: tab === "ship" ? 1 : 0, issues: [],
      rows: [{ row: 2, sku_id: "1001", order_line_id: "101", sku_label: "QA-Blue-M", qualified_units: "4", pending_units: "2", defective_units: "0", box_number: "QA-BOX", units: "6" }],
      cartons: tab === "ship" ? [{ number: "QA-BOX", items: [{ sku_id: "1001", units: "6" }] }] : [],
    } : path.endsWith("/preview") ? { id: "22", preview_hash: "qa-preview", impacts: [] } : tab === "receive" ? { id: "22", status: "DRAFT", revision: "1" } : { ...order, id: "23", status: "DRAFT" }));
    mount(`/production/orders/10?tab=${tab}${tab === "ship" ? "&operation=guided" : ""}`);
    await openOperation(tab);
    if (tab === "ship") await userEvent.click(screen.getByRole("button", { name: "下一步" }));
    expect(screen.getByRole("dialog", { name: tab === "receive" ? "入库" : "新建出货单" })).toBeInTheDocument();
    await enterInlineImport();
    const template = screen.getByRole("link", { name: tab === "receive" ? "下载入库模板" : "下载装箱模板" });
    expect(template.getAttribute("href")).toContain(`/orders/10/tables/${kind}/template?expected_revision=2`);
    expect(template).toHaveAttribute("download");
    if (tab === "receive") {
      const fileInput = screen.getByLabelText(/本次导入的XLSX文件/);
      expect(fileInput).not.toBeVisible();
      const chooseFile = vi.spyOn(fileInput, "click");
      await userEvent.click(screen.getByRole("button", { name: "导入表格" }));
      expect(chooseFile).toHaveBeenCalledTimes(1);
      chooseFile.mockRestore();
    }
    await userEvent.upload(screen.getByLabelText(/本次导入的XLSX文件/), new File(["fictional workbook"], "qa.xlsx"));
    
    const amount = await screen.findByLabelText(tab === "receive" ? "QA-Blue-M本次合格" : "QA-Blue-M本次出货");
    expect(amount).toHaveValue(tab === "receive" ? "4" : "6");
    expect(screen.queryByRole("button", { name: "应用表格到当前表单" })).not.toBeInTheDocument();
    expect(api.write).toHaveBeenCalledTimes(1);
    if (tab === "receive") {
      expect(screen.getByLabelText("QA-Blue-M本次待检")).toHaveValue("2");
      await userEvent.clear(amount); await userEvent.type(amount, "5");
      await userEvent.click(screen.getByRole("button", { name: "下一步" }));
      expect(screen.getByLabelText(/入库依据 \/ 备注/)).toHaveValue("表格导入：qa.xlsx");
    } else {
      await userEvent.click(screen.getByRole("button", { name: "下一步" }));
      expect(screen.getByLabelText("第1箱箱号")).toHaveValue("QA-BOX");
      expect(screen.getByLabelText("第1箱QA-Blue-M装箱数")).toHaveValue("6");
      await userEvent.clear(screen.getByLabelText("第1箱箱号"));
      await userEvent.type(screen.getByLabelText("第1箱箱号"), "QA-EDITED");
    }
    await userEvent.click(screen.getByRole("button", { name: "下一步" }));
    expect(screen.getByRole("table",{name:"原表与当前填写对照"})).toHaveTextContent(tab==="receive"?"合格":"装箱分配");
    await userEvent.click(screen.getByRole("button", { name: tab === "receive" ? "保存草稿并预览" : "保存装箱草稿" }));
    await waitFor(() => expect(api.write.mock.calls.some(([url]) => url === (tab === "receive" ? "/api/production/inventory/documents" : "/api/production/shipments"))).toBe(true));
    const [, options] = api.write.mock.calls[1]!;
    if (tab === "receive") expect(options.body.lines).toEqual(expect.arrayContaining([expect.objectContaining({ quality: "QUALIFIED", units: "5", production_allocations: [{ order_line_id: "101", units: "5" }] }), expect.objectContaining({ quality: "PENDING", units: "2" })]));
    else expect(options.body).toMatchObject({ save_mode: "draft", cartons: [{ number: "QA-EDITED", items: [{ sku_id: "1001", units: "6" }] }] });
    expect(api.write.mock.calls.some(([url]) => url.endsWith("/confirm"))).toBe(false);
  });
  it.each(["receive", "ship"])("retains manual %s quantities after an invalid import", async tab => {
    api.write.mockResolvedValue({ kind: tab === "receive" ? "receipt" : "packing", filename: "qa.xlsx", order_id: "10", order_revision: "2", total_units: "0", box_count: 0, rows: [], cartons: [], issues: [{ row: 3, message: "数量不能为负数" }] });
    mount(`/production/orders/10?tab=${tab}${tab === "ship" ? "&operation=guided" : ""}`);
    await openOperation(tab);
    await userEvent.click(screen.getByRole("button", { name: "下一步" }));
    await userEvent.type(screen.getByLabelText(tab === "receive" ? "QA-Blue-M本次合格" : "QA-Blue-M本次出货"), "3");
    
    await enterInlineImport();
    await userEvent.upload(screen.getByLabelText(/本次导入的XLSX文件/), new File(["fictional"], "qa.xlsx"));
    
    expect(await screen.findByText("第3行 数量不能为负数")).toBeInTheDocument();
    
    expect(screen.getByLabelText(tab === "receive" ? "QA-Blue-M本次合格" : "QA-Blue-M本次出货")).toHaveValue("3");
    expect(api.write).toHaveBeenCalledTimes(1);
  });
  it("synchronizes the order search draft with applied filters on back and forward", async () => {
    const router = mount("/production/orders?q=first");
    const search = await screen.findByLabelText("搜索工厂、订单或SKU");
    await userEvent.clear(search);
    await userEvent.type(search, "second");
    await userEvent.keyboard("{Enter}");
    expect(new URLSearchParams(router.state.location.search).get("q")).toBe("second");
    await act(async () => { await router.navigate("/production/orders?q=third"); });
    expect(search).toHaveValue("third");
    await act(async () => { await router.navigate(-1); });
    expect(search).toHaveValue("second");
    await act(async () => { await router.navigate(1); });
    expect(search).toHaveValue("third");
    expect(api.write).not.toHaveBeenCalled();
  });
  it.each([
    "/production/orders",
    "/production/orders?factory=3&page=1&tab=history&new=&edit=",
    "/production/orders/10?factory=3&page=1&tab=history",
  ])("keeps URL, selected tab and displayed operation in sync from %s", async entry => {
    const router = mount(entry);
    await screen.findByRole("heading", { name: new RegExp(order.business_number) });
    if (!new URL(entry, "http://localhost").pathname.match(/orders\/10$/)) await userEvent.click(screen.getByRole("link", { name: order.business_number }));
    const initial = new URL(router.state.location.pathname + router.state.location.search, "http://localhost");
    for (const [key, label, heading] of [
      ["progress", "生产跟进", "更新生产进度"],
      ["receive", "入库", "入库"],
      ["ship", "历史出货", "历史出货关联"],
      ["history", "操作记录", "操作记录"],
    ]) {
      await userEvent.click(screen.getByRole("link", { name: label }));
      expect(await screen.findByRole(key === "progress" ? "button" : "heading", { name: heading })).toBeInTheDocument();
      expect(screen.getByRole("link", { name: label })).toHaveAttribute("aria-current", "page");
      expect(router.state.location.pathname).toBe(initial.pathname);
      const query = new URLSearchParams(router.state.location.search);
      expect(query.get("tab")).toBe(key);
      for (const filter of ["factory", "page"]) expect(query.get(filter)).toBe(initial.searchParams.get(filter));
      expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
    }
    await act(async () => { await router.navigate(-1); });
    expect(await screen.findByRole("heading", { name: "历史出货关联" })).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "历史出货" })).toHaveAttribute("aria-current", "page");
    expect(api.write).not.toHaveBeenCalled();
  });
  it.each([
    ["progress", "累计实际生产数量", "81"],
    ["receive", "QA-Blue-M本次合格", "1"],
    ["ship", "QA-Blue-M本次出货", "1"],
  ])("shows the leave prompt for unsaved %s input and only switches after consent", async (tab, label, value) => {
    const router = mount(`/production/orders/10?tab=${tab}${tab === "ship" ? "&operation=guided" : ""}`);
    if (tab !== "progress") { await openOperation(tab); await userEvent.click(screen.getByRole("button", { name: "下一步" })); }
    if (tab === "progress") await openProgress();
    const input = await screen.findByLabelText(new RegExp(label));
    await userEvent.clear(input);
    await userEvent.type(input, value);
    await userEvent.click(tab === "progress" ? screen.getByRole("button", { name: "关闭生产进度编辑" }) : screen.getByRole("button", { name: tab === "receive" ? "关闭入库" : "关闭新建出货单" }));
    expect(await screen.findByText(tab === "progress" ? "放弃未保存的修改？" : "还有未保存的内容")).toBeInTheDocument();
    expect(new URLSearchParams(router.state.location.search).get("tab")).toBe(tab);
    await userEvent.click(screen.getByRole("button", { name: tab === "progress" ? "继续填写进度" : "继续填写" }));
    expect(input).toHaveValue(value);
    expect(screen.queryByRole("dialog", { name: "还有未保存的内容" })).not.toBeInTheDocument();
    await userEvent.click(tab === "progress" ? screen.getByRole("button", { name: "关闭生产进度编辑" }) : screen.getByRole("button", { name: tab === "receive" ? "关闭入库" : "关闭新建出货单" }));
    await userEvent.click(await screen.findByRole("button", { name: tab === "progress" ? "放弃并关闭进度" : "放弃并离开" }));
    await userEvent.click(screen.getByRole("link", { name: "操作记录" }));
    expect(await screen.findByRole("heading", { name: "操作记录" })).toBeInTheDocument();
    expect(new URLSearchParams(router.state.location.search).get("tab")).toBe("history");
    expect(api.write).not.toHaveBeenCalled();
  });
  it("keeps the order detail mounted during refresh and locks writes until a successful read", async () => {
    const original = api.read.getMockImplementation()!;
    let rejectRefresh!: (reason: Error) => void;
    const pending = new Promise<unknown>((_resolve, reject) => { rejectRefresh = reject; });
    let reads = 0;
    api.read.mockImplementation(path => path === "/api/production/orders/10" && ++reads === 2 ? pending : original(path));
    const router = mount();
    const header = await screen.findByRole("heading", { name: new RegExp(order.business_number) });
    expect(screen.getByRole("navigation", { name: "订单操作" }).closest("fieldset")).toBeNull();
    const amount = await openProgress();
    const save = screen.getByRole("button", { name: "核对并保存进度" });
    await act(() => router.navigate("/production/orders/10?reload=qa"));
    expect(header).toBeInTheDocument();
    expect(screen.getByLabelText(/累计实际生产数量/)).toBe(amount);
    expect(save).toBeDisabled();
    await act(async () => { rejectRefresh(new Error("虚构断线")); await pending.catch(() => undefined); });
    expect(await screen.findByText(/更新失败，旧内容仅供参考/)).toBeInTheDocument();
    expect(amount).toHaveValue("80"); expect(save).toBeDisabled();
    await act(() => router.navigate("/production/orders/10?reload=qa2"));
    await waitFor(() => expect(api.read.mock.calls.filter(([path]) => path === "/api/production/orders/10")).toHaveLength(3));
    fireEvent.change(amount, { target: { value: "81" } });
    await waitFor(() => expect(save).toBeEnabled());
    expect(header).toBeInTheDocument();
    expect(api.write).not.toHaveBeenCalled();
  });
  it("does not flash an empty-order guide while the first list is still loading", async () => {
    const original = api.read.getMockImplementation()!;
    let resolveList!: (value: { items: Document[]; page: number; total: number }) => void;
    const pending = new Promise<{ items: Document[]; page: number; total: number }>(resolve => { resolveList = resolve; });
    api.read.mockImplementation(path => path.startsWith("/api/production/orders?") ? pending : original(path));
    mount("/production/orders", false);
    await screen.findByLabelText("搜索工厂、订单或SKU");
    expect(screen.queryByRole("heading", { name: "从工厂或订单开始" })).not.toBeInTheDocument();
    await act(async () => { resolveList({ items: [], page: 1, total: 0 }); await pending; });
    expect(await screen.findByText(/没有匹配的订单/)).toBeInTheDocument();
  });
  it("keeps the order chooser mounted and never shows the previous order while loading a selection", async () => {
    const nextOrder = { ...order, id: "11", business_number: "虚构第二张订单" };
    const original = api.read.getMockImplementation()!;
    let resolveDetail!: (value: Document) => void;
    const pending = new Promise<Document>(resolve => { resolveDetail = resolve; });
    api.read.mockImplementation(path => path.startsWith("/api/production/orders?") ? Promise.resolve({ items: [order, nextOrder], page: 1, total: 2 }) : path === "/api/production/orders/11" ? pending : original(path));
    mount("/production/orders/10", false);
    await screen.findByRole("heading", { name: new RegExp(order.business_number) });
    await userEvent.click(screen.getByRole("button", { name: "选择其他订单" }));
    const chooser = screen.getByRole("button", { name: new RegExp(nextOrder.business_number) });
    const search = screen.getByLabelText("搜索工厂、订单或SKU");
    await userEvent.type(search, "未提交的查找");
    await userEvent.click(chooser);
    expect(screen.getByRole("button", { name: new RegExp(nextOrder.business_number), hidden: true })).toBe(chooser);
    expect(screen.getByLabelText("搜索工厂、订单或SKU")).toBe(search);
    expect(search).toHaveValue("未提交的查找");
    expect(screen.queryByRole("heading", { name: new RegExp(order.business_number) })).not.toBeInTheDocument();
    for (const path of ["/api/production/workbench", "/api/production/inventory/availability?projection=scopes", "/api/production/skus?contract_version=2"]) expect(api.read.mock.calls.filter(([url]) => url === path)).toHaveLength(1);
    expect(api.read.mock.calls.filter(([path]) => path.startsWith("/api/production/orders?"))).toHaveLength(1);
    await act(async () => { resolveDetail(nextOrder); await pending; });
    expect(await screen.findByRole("heading", { name: new RegExp(nextOrder.business_number) })).toBeInTheDocument();
    expect(api.write).not.toHaveBeenCalled();
  });
  it("guards unsaved bulk progress when navigating to another order", async () => {
    const nextOrder = { ...order, id: "11", business_number: "虚构第二张订单", lines: order.lines!.map(line => ({ ...line, id: "102", produced_units: "7" })) };
    const original = api.read.getMockImplementation()!;
    api.read.mockImplementation(path => path === "/api/production/orders/11" ? Promise.resolve(nextOrder) : original(path));
    const router = mount(); const amount = await openProgress();
    fireEvent.change(amount, { target: { value: "81" } });
    await act(() => router.navigate("/production/orders/11"));
    expect(await screen.findByText("还有未保存的内容")).toBeInTheDocument();
    expect(screen.getAllByRole("dialog")).toHaveLength(1);
    await userEvent.click(screen.getByRole("button", { name: "继续填写" }));
    expect(amount).toHaveValue("81");
    await act(() => router.navigate("/production/orders/11"));
    await userEvent.click(screen.getByRole("button", { name: "放弃并离开" }));
    expect(await openProgress()).toHaveValue("7");
    expect(api.write).not.toHaveBeenCalled();
  });
  it("fills and edits one order table while retaining original source identity", async () => {
    const preview = { preview_id:"qa-preview",filename:"fictional.xlsx",rows:[{sku_id:"1001",sku_label:"QA-Blue-M",expected_units:"12"}],issues:[],command:{business_number:"QA-TABLE",business_date:"2026-10-23",source_system:"SIM",external_event_id:"EV-1",source_event_kind:"ORDER",_source_digest:"a".repeat(64)},source_check:{candidates:[]} };
    api.write.mockImplementation(path=>Promise.resolve(path.includes("/preview?")?preview:{...order,status:"DRAFT"}));
    mount("/production/orders/10?new=1");
    await screen.findByRole("option", { name: "青禾示例厂" });
    await userEvent.selectOptions(await screen.findByLabelText(/生产工厂（一单一家）/),"3");
    await userEvent.selectOptions(screen.getByLabelText(/生产完成后入库仓库/),"900:1");
    await userEvent.upload(screen.getByLabelText(/下单XLSX文件/),new File(["fictional"],"fictional.xlsx"));
    await waitFor(()=>expect(screen.getByLabelText("产品1下单数量")).toHaveValue("12"));
    await userEvent.clear(screen.getByLabelText("产品1下单数量"));await userEvent.type(screen.getByLabelText("产品1下单数量"),"15");
    await userEvent.click(screen.getByRole("button",{name:"保存草稿"}));
    await waitFor(()=>expect(api.write.mock.calls.some(([path])=>path==="/api/production/orders")).toBe(true));
    expect(api.write.mock.calls.find(([path])=>path==="/api/production/orders")![1].body).toMatchObject({save_mode:"draft",source_system:"SIM",external_event_id:"EV-1",_source_digest:"a".repeat(64),lines:[{sku_id:"1001",expected_units:"15"}]});
  });
  it.each(["issues", "duplicate"])("does not create another order when table preview has %s", async state => {
    api.write.mockResolvedValue({ preview_id: "qa-preview", filename: "fictional.xlsx", rows: [], issues: state === "issues" ? [{ row: 2, message: "SKU未匹配" }] : [], command: {}, duplicate_document: state === "duplicate" ? order : undefined, source_check: { candidates: [] } });
    mount("/production/orders/10?new=1");
    await enterInlineImport();
    await screen.findByRole("option", { name: "青禾示例厂" });
    await userEvent.selectOptions(screen.getByLabelText(/生产工厂（一单一家）/), "3");
    await userEvent.selectOptions(screen.getByLabelText(/生产完成后入库仓库/), "900:1");
    await userEvent.upload(screen.getByLabelText("下单XLSX文件（不超过2MB）"), new File(["fictional"], "fictional.xlsx"));
    
    await screen.findByText(state === "issues" ? /SKU未匹配/ : /此来源已登记/);
    expect(screen.queryByRole("button", { name: "生成订单草稿" })).not.toBeInTheDocument();
    expect(api.write).toHaveBeenCalledTimes(1);
  });
  it("selects a newly registered factory without saving or clearing the order", async () => {
    api.write.mockResolvedValue({ id: "9", name: "虚构新厂" });
    mount("/production/orders/10?new=1");
    const factory = await screen.findByLabelText(/生产工厂（一单一家）/);
    await screen.findByRole("option", { name: "青禾示例厂" });
    expect(screen.queryByLabelText("查找生产工厂")).not.toBeInTheDocument();
    await userEvent.selectOptions(factory, "3");
    await userEvent.type(screen.getByLabelText("业务订单号（可选）"), "KEEP-ORDER");
    await userEvent.click(screen.getByRole("button", { name: "登记新工厂" }));
    expect(screen.getByRole("button", { name: "登记并选择" })).toBeDisabled();
    await userEvent.type(screen.getByLabelText("新工厂全名"), "  虚构新厂  ");
    await userEvent.click(screen.getByRole("button", { name: "登记并选择" }));
    await waitFor(() => expect(factory).toHaveValue("9"));
    expect(screen.getByLabelText("业务订单号（可选）")).toHaveValue("KEEP-ORDER");
    expect(api.write).toHaveBeenCalledTimes(1);
    expect(api.write.mock.calls[0]![0]).toBe("/api/production/factories");
    expect(api.write.mock.calls[0]![1].body).toMatchObject({ name: "虚构新厂" });
  });
  it("shows factory registration errors inside the dialog and allows cancelling without an order write", async () => {
    api.write.mockRejectedValue(new ApiRequestError(409, "directory_name_conflict", "工厂名称已存在"));
    mount("/production/orders/10?new=1");
    await userEvent.click(await screen.findByRole("button", { name: "登记新工厂" }));
    await userEvent.type(screen.getByLabelText("新工厂全名"), "青禾示例厂");
    await userEvent.click(screen.getByRole("button", { name: "登记并选择" }));
    const error = await screen.findByText("工厂名称已存在");
    expect(error.closest('[role="dialog"]')).not.toBeNull();
    await userEvent.click(screen.getByRole("button", { name: "取消登记" }));
    expect(screen.queryByLabelText("新工厂全名")).not.toBeInTheDocument();
    expect(api.write).toHaveBeenCalledTimes(1);
  });
  it("shows separate facts and saves cumulative progress with the current revision", async () => {
    api.write.mockResolvedValue({ ...order, revision: "3" }); mount();
    const amount = await openProgress(); expect(amount).toHaveValue("80");
    fireEvent.change(amount, { target: { value: "90" } });
    await userEvent.click(screen.getByRole("button", { name: "核对并保存进度" }));
    await waitFor(() => expect(api.write).toHaveBeenCalled());
    const [path, options] = api.write.mock.calls[0]!;
    expect(path).toBe("/api/production/orders/10/production-progress");
    expect(options.body).toMatchObject({ expected_revision: "2", lines: [{ order_line_id: "101", produced_units: "90" }], operation_token: options.operationKey });
  });
  it("filters factories on the server, before paging", async () => {
    mount(); await screen.findByRole("heading", { name: /虚构工作台订单/ });
    await userEvent.click(screen.getByRole("button", { name: "选择其他订单" }));
    await userEvent.click(screen.getByText("全部工厂", { selector: "summary" }));
    await userEvent.click(screen.getByRole("button", { name: "筛选工厂：青禾示例厂" }));
    await waitFor(() => expect(api.read.mock.calls.some(([path]) => path.includes("factory=3"))).toBe(true));
  });
  it("keeps an ambiguous write locked and retries the same operation", async () => {
    api.write.mockRejectedValueOnce(new TypeError("network interrupted")).mockResolvedValueOnce(order); mount();
    const amount = await openProgress(); fireEvent.change(amount, { target: { value: "81" } }); await userEvent.click(screen.getByRole("button", { name: "核对并保存进度" }));
    expect(await screen.findByText("保存结果待核实，已锁定当前输入")).toBeInTheDocument(); expect(screen.getByLabelText(/累计实际生产数量/)).toBeDisabled();
    await userEvent.click(screen.getByRole("button", { name: "重发原操作" }));
    await waitFor(() => expect(api.write).toHaveBeenCalledTimes(2)); expect(api.write.mock.calls[1]![1].operationKey).toBe(api.write.mock.calls[0]![1].operationKey);
  });
  it("receives in quality splits and requires preview before posting", async () => {
    api.write.mockImplementation((path: string) => Promise.resolve(path.endsWith("/preview") ? { id: "22", expected_revision: "1", preview_hash: "preview-qa", impacts: [] } : path.endsWith("/confirm") ? { id: "22", status: "POSTED", revision: "2" } : { id: "22", status: "DRAFT", revision: "1" }));
    const router = mount("/production/orders/10?tab=receive"); await openOperation("receive"); await userEvent.click(screen.getByRole("button", { name: "下一步" }));
    await userEvent.click(screen.getByRole("checkbox", { name: "填写待检或次品" })); fireEvent.change(screen.getByLabelText("QA-Blue-M本次合格"), { target: { value: "18" } }); fireEvent.change(screen.getByLabelText("QA-Blue-M本次待检"), { target: { value: "2" } });
    await userEvent.click(screen.getByRole("button", { name: "下一步" })); fireEvent.change(screen.getByLabelText(/入库依据 \/ 备注/), { target: { value: "fictional arrival" } });
    await userEvent.click(screen.getByRole("button", { name: "下一步" }));
    await userEvent.click(screen.getByRole("button", { name: "保存草稿并预览" })); await screen.findByRole("button", { name: "确认本次入库" });
    expect(new URLSearchParams(router.state.location.search).get("receipt_draft")).toBe("22");
    expect(api.write.mock.calls[0]![1].body.lines).toEqual(expect.arrayContaining([expect.objectContaining({ units: "18", quality: "QUALIFIED", production_allocations: [{ order_line_id: "101", units: "18" }] }), expect.objectContaining({ units: "2", quality: "PENDING" })]));
    expect(api.write.mock.calls.some(([path]) => path.endsWith("/confirm"))).toBe(false); await userEvent.click(screen.getByRole("button", { name: "确认本次入库" }));
    await waitFor(() => expect(api.write.mock.calls.some(([path, options]) => path.endsWith("/confirm") && options.body.preview_hash === "preview-qa")).toBe(true));
    expect(await screen.findByText("本批入库已确认")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "核对并确认入库" })).not.toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "登记下一批入库" }));
    await userEvent.click(screen.getByRole("button", { name: "下一步" }));
    const nextAmount = await screen.findByLabelText("QA-Blue-M本次合格");
    expect(nextAmount).toHaveValue("");
    await userEvent.type(nextAmount, "1");
    await userEvent.click(screen.getByRole("button", { name: "关闭入库" }));
    expect(await screen.findByRole("dialog", { name: "还有未保存的内容" })).toBeInTheDocument();
  }, 15_000);
  it("does not advance incomplete packing, and saves a complete draft without confirming stock effects", async () => {
    api.write.mockResolvedValue(order); mount("/production/orders/10?tab=ship&operation=guided"); await openOperation("ship"); expect(screen.getByLabelText(/发货仓库/)).toHaveValue("900:1"); expect(screen.getByRole("option",{name:"虚构仓900"})).toHaveValue("900:1"); expect(screen.queryByRole("option",{name:/本公司/})).not.toBeInTheDocument(); await userEvent.click(screen.getByRole("button", { name: "下一步" }));
    fireEvent.change(screen.getByLabelText("QA-Blue-M本次出货"), { target: { value: "20" } }); await userEvent.click(screen.getByRole("button", { name: "下一步" })); await userEvent.click(screen.getByRole("button", { name: "下一步" }));
    expect(await screen.findByText(/每个产品的装箱合计须等于/)).toBeInTheDocument(); expect(api.write).not.toHaveBeenCalled();
    fireEvent.change(screen.getByLabelText("第1箱箱号"), { target: { value: "A001" } }); fireEvent.change(screen.getByLabelText("第1箱QA-Blue-M装箱数"), { target: { value: "20" } });
    await userEvent.click(screen.getByRole("button", { name: "下一步" }));
    await userEvent.click(screen.getByRole("button", { name: "保存装箱草稿" }));
    await waitFor(() => expect(api.write).toHaveBeenCalled()); expect(api.write.mock.calls[0]![1].body).toMatchObject({ save_mode: "draft", destination: "虚构集货点", cartons: [{ number: "A001", items: [{ sku_id: "1001", units: "20" }] }] });
  });
  it.each(["receive", "ship"])("never opens the %s wizard for a viewer, including direct URLs", async tab => {
    mount(`/production/orders/10?tab=${tab}&operation=guided`, false);
    await screen.findByText("当前账号只读");
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /新建入库|新建出货/ })).not.toBeInTheDocument();
    expect(api.write).not.toHaveBeenCalled();
  });
  it("keeps partially packed drafts usable in the shared shipment wizard", async () => {
    api.write.mockResolvedValue({ ...order, id: "23", status: "DRAFT" });
    mount("/production/orders/10?tab=ship&operation=guided"); await openOperation("ship");
    await userEvent.click(screen.getByRole("button", { name: "下一步" }));
    await userEvent.type(screen.getByLabelText("QA-Blue-M本次出货"), "20");
    await userEvent.click(screen.getByRole("button", { name: "下一步" }));
    await userEvent.type(screen.getByLabelText("第1箱箱号"), "PARTIAL");
    await userEvent.type(screen.getByLabelText("第1箱QA-Blue-M装箱数"), "10");
    await userEvent.click(screen.getByRole("button", { name: "保存装箱草稿" }));
    await waitFor(() => expect(api.write).toHaveBeenCalledTimes(1));
    expect(api.write.mock.calls[0]![1].body).toMatchObject({ save_mode: "draft", sources: [{ actual_units: "20" }], cartons: [{ number: "PARTIAL", items: [{ units: "10" }] }] });
  });
  it("retains the saved receipt draft entry after closing and revisiting the tab", async () => {
    const router = mount("/production/orders/10?tab=receive&receipt_draft=22");
    expect(await screen.findByRole("link", { name: "继续处理入库草稿 22" })).toHaveAttribute("href", expect.stringContaining("operation=guided"));
    await userEvent.click(screen.getByRole("link", { name: "生产跟进" }));
    await userEvent.click(screen.getByRole("link", { name: "入库" }));
    expect(screen.getByRole("link", { name: "继续处理入库草稿 22" })).toBeInTheDocument();
    expect(new URLSearchParams(router.state.location.search).get("operation")).not.toBe("guided");
    expect(api.write).not.toHaveBeenCalled();
  });
  it("resumes a receipt draft in the same wizard and previews the existing revision without recreating it", async () => {
    const original = api.read.getMockImplementation()!;
    api.read.mockImplementation(path => path === "/api/production/inventory/documents/22" ? Promise.resolve({ id: "22", revision: "4", status: "DRAFT", kind: "IN", warehouse_id: "900", owner_id: "1", business_date: "2026-10-25", reason: "saved receipt", lines: [{ sku_id: "1001", quality: "QUALIFIED", purpose: "PRODUCTION_RECEIPT", units: "6", production_allocations: [{ order_line_id: "101", units: "6" }] }] }) : original(path));
    api.write.mockResolvedValue({ id: "22", preview_hash: "restored-preview", impacts: [] });
    mount("/production/orders/10?tab=receive&receipt_draft=22");
    await userEvent.click(await screen.findByRole("link", { name: "继续处理入库草稿 22" }));
    await userEvent.click(await screen.findByRole("button", { name: "下一步" }));
    expect(screen.getByLabelText("QA-Blue-M本次合格")).toHaveValue("6");
    await userEvent.click(screen.getByRole("button", { name: "下一步" }));
    expect(screen.getByLabelText(/入库依据 \/ 备注/)).toHaveValue("saved receipt");
    await userEvent.click(screen.getByRole("button", { name: "下一步" }));
    await userEvent.click(screen.getByRole("button", { name: "生成库存预览" }));
    await screen.findByRole("button", { name: "确认本次入库" });
    expect(api.write.mock.calls[0]?.[0]).toBe("/api/production/inventory/documents/22/preview");
    expect(api.write.mock.calls[0]?.[1].body).toMatchObject({ expected_revision: "4" });
    expect(api.write).toHaveBeenCalledTimes(1);
  }, 15_000);
  it.each(["owner", "source"])("does not rewrite a receipt draft with a different %s", async mismatch => {
    const original = api.read.getMockImplementation()!;
    api.read.mockImplementation(path => path === "/api/production/inventory/documents/22" ? Promise.resolve({ id: "22", revision: "4", status: "DRAFT", kind: "IN", warehouse_id: "900", owner_id: mismatch === "owner" ? "9" : "1", business_date: "2026-10-25", reason: "original", lines: [{ sku_id: "1001", quality: "QUALIFIED", purpose: "PRODUCTION_RECEIPT", units: "6", production_allocations: [{ order_line_id: mismatch === "source" ? "999" : "101", units: "6" }] }] }) : original(path));
    mount("/production/orders/10?tab=receive&receipt_draft=22&operation=guided");
    expect(await screen.findByText(mismatch === "owner" ? "入库草稿不属于当前仓库及货主" : "此记录保留完整来源关系")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "下一步" })).not.toBeInTheDocument();
    expect(api.write).not.toHaveBeenCalled();
  });
  it("opens an existing shipment draft from its original URL in the shared wizard", async () => {
    const original = api.read.getMockImplementation()!;
    api.read.mockImplementation(path => path === "/api/production/shipments/23" ? Promise.resolve({ ...order, id: "23", status: "DRAFT", warehouse_id: "900", owner_id: "1", sources: [{ sku_id: "1001", actual_units: "6", fulfillment_mode: "WAREHOUSE_STOCK", allocations: [{ order_line_id: "101", units: "6" }] }], cartons: [{ number: "SAVED", items: [{ sku_id: "1001", units: "6" }] }] }) : original(path));
    mount("/production/orders/10?tab=ship&shipment=23");
    await screen.findByRole("dialog", { name: "出货装箱" });
    await userEvent.click(await screen.findByRole("button", { name: "下一步" }));
    expect(await screen.findByLabelText("QA-Blue-M本次出货")).toHaveValue("6");
    await userEvent.click(screen.getByRole("button", { name: "下一步" }));
    expect(screen.getByLabelText("第1箱箱号")).toHaveValue("SAVED");
    expect(api.write).not.toHaveBeenCalled();
  });
  it("rebinds an edited shipment draft to its saved revision before confirmation", async () => {
    const draft = { ...order, id: "23", status: "DRAFT", revision: "1", warehouse_id: "900", owner_id: "1", notes: "", sources: [{ sku_id: "1001", actual_units: "6", fulfillment_mode: "WAREHOUSE_STOCK", allocations: [{ order_line_id: "101", units: "6" }] }], cartons: [{ number: "SAVED", items: [{ sku_id: "1001", units: "6" }] }] };
    const original = api.read.getMockImplementation()!;
    api.read.mockImplementation(path => path === "/api/production/shipments/23" ? Promise.resolve(draft) : original(path));
    api.write.mockResolvedValue({ ...draft, revision: "2", notes: "saved revision two" });
    mount("/production/orders/10?tab=ship&operation=guided&shipment=23");
    await screen.findByRole("dialog", { name: "出货装箱" });
    await userEvent.click(await screen.findByRole("button", { name: "下一步" }));
    await userEvent.click(screen.getByRole("button", { name: "下一步" }));
    await userEvent.click(screen.getByRole("button", { name: "下一步" }));
    await userEvent.type(screen.getByLabelText("出货备注（可选）"), "saved revision two");
    await userEvent.click(screen.getByRole("button", { name: "保存草稿修改" }));
    expect(await screen.findByRole("heading", { name: "来源与目的地" })).toBeInTheDocument();
    expect(api.write.mock.calls[0]?.[0]).toBe("/api/production/shipments/23");
    expect(api.write.mock.calls[0]?.[1].body).toMatchObject({ expected_revision: "1", notes: "saved revision two" });
    await userEvent.click(screen.getByRole("button", { name: "下一步" }));
    await userEvent.click(screen.getByRole("button", { name: "下一步" }));
    await userEvent.click(screen.getByRole("button", { name: "下一步" }));
    expect(screen.getByLabelText("出货备注（可选）")).toHaveValue("saved revision two");
    expect(screen.getByRole("button", { name: "核对并确认本出货草稿" })).toBeEnabled();
    api.write.mockResolvedValue({ ...draft, status: "CONFIRMED", revision: "3" });
    await userEvent.click(screen.getByRole("button", { name: "核对并确认本出货草稿" }));
    await userEvent.click(screen.getByRole("button", { name: "确认本草稿已实际发货" }));
    expect(await screen.findByText("本批已确认发货")).toBeInTheDocument();
    expect(api.write.mock.calls[1]?.[1].body).toMatchObject({ expected_revision: "2" });
    expect(screen.queryByRole("button", { name: "确认本草稿已实际发货" })).not.toBeInTheDocument();
  }, 15_000);
  it("clears the previous order's receipt draft when choosing another order", async () => {
    const nextOrder = { ...order, id: "11", business_number: "虚构第二张订单" };
    const original = api.read.getMockImplementation()!;
    api.read.mockImplementation(path => path.startsWith("/api/production/orders?") ? Promise.resolve({ items: [order, nextOrder], page: 1, total: 2 }) : path === "/api/production/orders/11" ? Promise.resolve(nextOrder) : original(path));
    const router = mount("/production/orders/10?tab=receive&receipt_draft=22");
    await screen.findByRole("link", { name: "继续处理入库草稿 22" });
    await userEvent.click(screen.getByRole("button", { name: "选择其他订单" }));
    await userEvent.click(screen.getByRole("button", { name: new RegExp(nextOrder.business_number) }));
    await screen.findByRole("heading", { name: new RegExp(nextOrder.business_number) });
    expect(new URLSearchParams(router.state.location.search).has("receipt_draft")).toBe(false);
    expect(api.write).not.toHaveBeenCalled();
  });
  it("never gives a viewer write controls", async () => { mount("/production/orders/10", false); await screen.findByText("当前账号只读"); expect(screen.queryByRole("button", { name: "下单" })).not.toBeInTheDocument(); expect(screen.queryByRole("button", { name: "核对并保存进度" })).not.toBeInTheDocument(); });
  it("preserves a revision conflict instead of reporting saved", async () => { api.write.mockRejectedValue(new ApiRequestError(409, "revision_conflict", "记录已被修改")); mount(); const amount = await openProgress(); fireEvent.change(amount, { target: { value: "81" } }); await userEvent.click(screen.getByRole("button", { name: "核对并保存进度" })); expect(await screen.findByText("记录已被修改")).toBeInTheDocument(); expect(screen.getByLabelText(/累计实际生产数量/)).toHaveValue("81"); expect(screen.queryByText("已保存，数量已重新读取。")).not.toBeInTheDocument(); });
});

it("keeps remaining work per SKU, preserves unknown production and excludes closed lines", () => {
  const first = order.lines![0]!;
  const mixed: Document = { ...order, lines: [
    { ...first, expected_units: "10", produced_units: "20", received_units: "20", actual_units: "20" },
    { ...first, id: "102", expected_units: "10", produced_units: "0", received_units: "0", actual_units: "0" },
    { ...first, id: "103", expected_units: "8", produced_units: null, received_units: "0", actual_units: "0", tracking_state: "CLOSED" },
  ] };
  expect(orderPending(mixed, "produced_units")).toBe("10");
  expect(orderPending(mixed, "received_units")).toBe("10");
  expect(orderPending(mixed, "actual_units")).toBe("10");
  expect(orderPending({ ...order, lines: [{ ...first, produced_units: null }] }, "produced_units")).toBe("待登记");
  expect(orderPending({ ...order, lines: undefined }, "actual_units")).toBe("待核");
});
it("applies todo filters on the server across pages and includes them in export", async () => {
  const router = mount("/production/orders?factory=3&page=2");
  await screen.findByRole("button",{name:"选择工厂"});
  await userEvent.click(screen.getByRole("button",{name:"筛选"}));
  const filter = await screen.findByRole("dialog",{name:"筛选订单"});
  await userEvent.click(within(filter).getByRole("button",{name:"待入库"}));
  await userEvent.click(within(filter).getByRole("button",{name:"应用筛选"}));
  await waitFor(() => expect(api.read.mock.calls.some(([url]) => url.startsWith("/api/production/orders?") && new URL(url, "http://qa").searchParams.get("tracking") === "WAIT_RECEIPT")).toBe(true));
  expect(router.state.location.search).toContain("page=1");
  expect(router.state.location.search).toContain("factory=3");
  await userEvent.click(screen.getByRole("button", { name: "更多" }));
  expect(screen.getByRole("menuitem", { name: "导出订单" }).getAttribute("href")).toContain("tracking=WAIT_RECEIPT");
  await act(() => router.navigate(-1));
  await waitFor(() => expect(new URLSearchParams(router.state.location.search).get("todo")).toBeNull());
  expect(api.write).not.toHaveBeenCalled();
});

it("clears only the chosen order filter and can clear all without writing", async () => {
  const router = mount("/production/orders?factory=3&status=CONFIRMED&todo=WAIT_RECEIPT&q=QA&page=2");
  await userEvent.click(await screen.findByRole("button", { name: "清除待办筛选" }));
  let p = new URLSearchParams(router.state.location.search);
  expect(p.get("todo")).toBeNull();
  expect(p.get("factory")).toBe("3");
  expect(p.get("q")).toBe("QA");
  expect(p.get("page")).toBe("1");
  await userEvent.click(screen.getByRole("button", { name: "清空订单筛选" }));
  p = new URLSearchParams(router.state.location.search);
  for (const key of ["q", "factory", "status", "todo"]) expect(p.get(key)).toBeNull();
  expect(screen.getByRole("searchbox", { name: "搜索工厂、订单或SKU" })).toHaveValue("");
  expect(api.write).not.toHaveBeenCalled();
});
it.each(["/production/orders/10"])("keeps a collapsed chooser closed across tabs and refresh from %s", async entry => {
  const router = mount(entry);
  await screen.findByRole("heading", { name: new RegExp(order.business_number) });
  if (entry === "/production/orders") await userEvent.click(screen.getByText("收起订单列表"));
  const expectCollapsed = () => expect(screen.getByText("选择其他订单").closest("button")).toHaveAttribute("aria-expanded", "false");
  expectCollapsed();
  for (const name of ["入库", "历史出货", "操作记录", "生产跟进"]) {
    await userEvent.click(screen.getByRole("link", { name }));
    expectCollapsed();
  }
  await userEvent.click(screen.getByRole("button", { name: "刷新" }));
  expect(router.state.location.pathname).toBe(entry);
  await waitFor(() => expect(screen.getByRole("button", { name: "更新生产进度" })).toBeEnabled());
  expectCollapsed();
  await act(() => router.navigate(-1));
  expectCollapsed();
  expect(api.write).not.toHaveBeenCalled();
});
it("opens a selected factory order directly and places the operation switch before product progress", async () => {
  mount("/production/orders/10?factory=3");
  await screen.findByRole("heading", { name: new RegExp(order.business_number) });
  expect(screen.getByRole("button", { name: "选择其他订单" })).toHaveAttribute("aria-expanded", "false");
  expect(screen.getByRole("link", { name: "查看生产工厂" })).toHaveAttribute("href", `/production/factories/${order.factory_id}`);
  const tabs = screen.getByRole("navigation", { name: "订单操作" });
  const table = screen.getByRole("table");
  expect(tabs.compareDocumentPosition(table) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
  expect(screen.getAllByRole("heading", { level: 1 })).toHaveLength(1);
  expect(api.write).not.toHaveBeenCalled();
});
it("returns from an order to the factory overview and restores filters", async () => {
  const router = mount("/production/orders?factory=3&q=QA");
  await userEvent.click(await screen.findByRole("link", { name: order.business_number }));
  expect((await screen.findByText("选择其他订单")).closest("button")).toHaveAttribute("aria-expanded", "false");
  await userEvent.click(screen.getByRole("link", { name: "工厂订单总览" }));
  expect(await screen.findByRole("region", { name: "工厂订单跟进总览" })).toBeInTheDocument();
  expect(router.state.location.search).toContain("factory=3");
  expect(screen.getByRole("searchbox", { name: "搜索工厂、订单或SKU" })).toHaveValue("QA");
  expect(api.write).not.toHaveBeenCalled();
});

describe("factory overview and bulk cumulative production", () => {
  const skuCatalog = [
    { sku_id: "1001", label: "old-opaque", code: "0012-沙色-M", status: "active", catalog_version: "qa", style_code: "0012", standard_color: "沙色", standard_size: "M" },
    { sku_id: "1002", label: "other-opaque", code: "0013-黑色-L", status: "active", catalog_version: "qa", style_code: "0013", standard_color: "黑色", standard_size: "L" },
  ];
  const multi: Document = { ...order, lines: [order.lines![0]!, { ...order.lines![0]!, id: "102", sku_id: "1002", sku_label: "0013-old-snapshot", produced_units: null }, { ...order.lines![0]!, id: "103", sku_id: "1003", tracking_state: "CLOSED" }] };
  function setup() { const original = api.read.getMockImplementation()!; api.read.mockImplementation(path => path.startsWith("/api/production/orders?") ? Promise.resolve({ items: [multi, { ...order, id: "11", business_number: "第二张单" }], page: 1, page_size: 20, total: 22 }) : path.includes("/skus?") ? Promise.resolve({ items: skuCatalog }) : original(path)); }
  it("shows both orders and standardized SKU names without detail N+1, and retains scoped paging and tools", async () => {
    setup(); mount("/production/orders?factory=3");
    expect(await screen.findByRole("article", { name: "订单 第二张单" })).toBeInTheDocument();
    expect(screen.getByRole("article", { name: `订单 ${order.business_number}` })).toHaveTextContent("0012-沙色-M");
    expect(screen.getByText("22 单")).toBeInTheDocument();
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
    expect(api.read.mock.calls.some(([path]) => /orders\/\d+$/.test(path))).toBe(false);
    await userEvent.click(screen.getByRole("button", { name: "更多" }));
    for (const label of ["从表格下单", "订单原表与整理记录", "全部出货", "历史订单出货汇总", "导出订单"]) expect(within(screen.getByRole("menu")).getByRole("menuitem", { name: label })).toBeInTheDocument();
  });
  it("limits matching product rows while retaining whole-order totals and passes search to the server", async () => {
    setup(); const router = mount("/production/orders?factory=3&q=0013");
    const card = await screen.findByRole("article", { name: `订单 ${order.business_number}` });
    expect(within(card).getByRole("table")).toHaveTextContent("0013-黑色-L");
    expect(within(card).getByRole("table")).not.toHaveTextContent("0012-沙色-M");
    expect(card).toHaveTextContent("1个规格，全单共3个");
    await userEvent.clear(screen.getByLabelText("搜索工厂、订单或SKU"));
    await userEvent.type(screen.getByLabelText("搜索工厂、订单或SKU"), "0012");
    await userEvent.keyboard("{Enter}");
    expect(router.state.location.search).toContain("q=0012");
    expect(api.read.mock.calls.some(([path]) => path.includes("q=0012") && path.includes("factory=3"))).toBe(true);
  });
  it("lets a viewer see unknown and zero quantities without production write controls", async () => {
    setup(); mount("/production/orders", false);
    const card = await screen.findByRole("article", { name: `订单 ${order.business_number}` });
    expect(card).toHaveTextContent("未登记");
    expect(screen.queryByRole("button", { name: "批量更新生产进度" })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /更新 .* 生产进度/ })).not.toBeInTheDocument();
  });
  it("submits multiple changed lines including zero in one revision-controlled command, excluding blank and closed rows", async () => {
    setup(); api.write.mockResolvedValue({ ...multi, revision: "3" }); mount("/production/orders");
    await userEvent.click((await screen.findAllByRole("button", { name: "批量更新生产进度" }))[0]!);
    const dialog = screen.getByRole("dialog");
    const inputs = within(dialog).getAllByLabelText(/累计实际生产数量/);
    fireEvent.change(inputs[0]!, { target: { value: "0" } }); fireEvent.change(inputs[1]!, { target: { value: "12" } });
    expect(inputs[2]).toBeDisabled();
    fireEvent.change(screen.getByLabelText(/本次备注 \/ 更正原因/), { target: { value: "实盘更正" } });
    await userEvent.click(screen.getByRole("button", { name: "核对并保存进度" }));
    await waitFor(() => expect(api.write).toHaveBeenCalledTimes(1));
    expect(api.write.mock.calls[0]![0]).toBe("/api/production/orders/10/production-progress");
    expect(api.write.mock.calls[0]![1].body).toMatchObject({ expected_revision: "2", lines: [{ order_line_id: "101", produced_units: "0" }, { order_line_id: "102", produced_units: "12" }] });
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
  });
  it("quick-fills selected rows and preserves dirty input in a single close-confirmation window", async () => {
    setup(); mount("/production/orders");
    const trigger = (await screen.findAllByRole("button", { name: "批量更新生产进度" }))[0]!;
    await userEvent.click(trigger);
    await userEvent.click(screen.getByRole("checkbox", { name: "批量填写 0013-黑色-L" }));
    await userEvent.click(screen.getByText("批量填写", { exact: true }));
    await userEvent.type(screen.getByLabelText("给已选规格填写同一累计数"), "90");
    await userEvent.click(screen.getByRole("button", { name: "应用到已选规格" }));
    expect(screen.getByLabelText("0012-沙色-M 累计实际生产数量")).toHaveValue("90");
    expect(screen.getByLabelText("0013-黑色-L 累计实际生产数量")).toHaveValue("");
    await userEvent.click(screen.getByRole("button", { name: "关闭生产进度编辑" }));
    expect(screen.getAllByRole("dialog")).toHaveLength(1);
    await userEvent.click(screen.getByRole("button", { name: "继续填写进度" }));
    expect(screen.getByLabelText("0012-沙色-M 累计实际生产数量")).toHaveValue("90");
    await userEvent.click(screen.getByRole("button", { name: "取消编辑" }));
    await userEvent.click(screen.getByRole("button", { name: "放弃并关闭进度" }));
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
    expect(trigger).toHaveFocus(); expect(api.write).not.toHaveBeenCalled();
  });
  it("rejects invalid integers and requires a reason for decreases and over-plan production", async () => {
    mount(); const input = await openProgress(); const save = screen.getByRole("button", { name: "核对并保存进度" });
    for (const value of ["-1", "1.5", "9223372036854775808"]) { fireEvent.change(input, { target: { value } }); expect(save).toBeDisabled(); }
    fireEvent.change(input, { target: { value: "101" } }); expect(save).toBeDisabled();
    fireEvent.change(screen.getByLabelText(/本次备注 \/ 更正原因/), { target: { value: "实际超产" } }); expect(save).toBeEnabled();
    fireEvent.change(input, { target: { value: "70" } }); fireEvent.change(screen.getByLabelText(/本次备注 \/ 更正原因/), { target: { value: "" } }); expect(save).toBeDisabled();
    expect(api.write).not.toHaveBeenCalled();
  });
  it("blocks dismissal while saving and while an uncertain result is checked with the original operation key", async () => {
    let reject!: (error: Error) => void; api.write.mockReturnValue(new Promise((_resolve, fail) => { reject = fail; }));
    mount(); const input = await openProgress(); fireEvent.change(input, { target: { value: "81" } });
    await userEvent.click(screen.getByRole("button", { name: "核对并保存进度" }));
    expect(screen.getByRole("button", { name: "关闭生产进度编辑" })).toBeDisabled(); expect(input).toBeDisabled();
    await act(async () => { reject(new TypeError("结果未返回")); await Promise.resolve(); });
    expect(await screen.findByRole("button", { name: "查询原操作结果" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "关闭生产进度编辑" })).toBeDisabled();
    const key = api.write.mock.calls[0]![1].operationKey;
    const original = api.read.getMockImplementation()!; api.read.mockImplementation(path => path === `/api/production/commands/${key}` ? Promise.resolve(order) : original(path));
    await userEvent.click(screen.getByRole("button", { name: "查询原操作结果" }));
    await waitFor(() => expect(screen.queryByRole("dialog")).not.toBeInTheDocument()); expect(api.write).toHaveBeenCalledTimes(1);
  });
  it("keeps the open editor and its original revision when a background reread finishes", async () => {
    const original = api.read.getMockImplementation()!; let reads = 0; let resolve!: (order: Document) => void;
    const pending = new Promise<Document>(done => { resolve = done; });
    api.read.mockImplementation(path => path === "/api/production/orders/10" && ++reads === 2 ? pending : original(path));
    const router = mount(); const input = await openProgress();
    await act(() => router.navigate("/production/orders/10?reload=qa"));
    fireEvent.change(input, { target: { value: "81" } });
    await act(async () => { resolve({ ...order, revision: "3", lines: order.lines!.map(line => ({ ...line, produced_units: "99" })) }); await pending; });
    expect(screen.getByLabelText(/累计实际生产数量/)).toBe(input); expect(input).toHaveValue("81");
    api.write.mockResolvedValue(order); await userEvent.click(screen.getByRole("button", { name: "核对并保存进度" }));
    await waitFor(() => expect(api.write).toHaveBeenCalled()); expect(api.write.mock.calls[0]![1].body.expected_revision).toBe("2");
  });
  it("offers recovery after a failed overview read without inventing empty data", async () => {
    const original = api.read.getMockImplementation()!; let fail = true;
    api.read.mockImplementation(path => path.startsWith("/api/production/orders?") && fail ? Promise.reject(new Error("订单读取失败")) : original(path));
    mount("/production/orders");
    expect(await screen.findByText("订单读取失败")).toBeInTheDocument();
    expect(screen.queryByText(/没有匹配的订单/)).not.toBeInTheDocument();
    fail = false; await userEvent.click(screen.getByRole("button", { name: "重试读取订单" }));
    expect(await screen.findByRole("article", { name: `订单 ${order.business_number}` })).toBeInTheDocument();
    expect(api.write).not.toHaveBeenCalled();
  });
  it("groups by factory id even when names match and retains zero, unknown, and closed progress", async () => {
    const original = api.read.getMockImplementation()!;
    const lines = [{ ...order.lines![0]!, produced_units: "0", received_units: "0", actual_units: "0" }, { ...order.lines![0]!, id: "102", produced_units: null, tracking_state: "CLOSED" as const }];
    api.read.mockImplementation(path => path.startsWith("/api/production/orders?") ? Promise.resolve({ items: [{ ...order, lines }, { ...order, id: "11", factory_id: "4", status: "DRAFT", business_number: "草稿单" }], page: 1, page_size: 20, total: 2 }) : original(path));
    mount("/production/orders");
    await screen.findByRole("article", { name: "订单 草稿单" });
    expect(screen.getAllByRole("region", { name: "青禾示例厂订单" })).toHaveLength(2);
    const table = screen.getByRole("table", { name: `${order.business_number}逐产品进度` });
    expect(within(table).getByRole("button", { name: "更新 QA-Blue-M 生产进度" })).toHaveTextContent("0");
    expect(table).toHaveTextContent("未登记"); expect(table).toHaveTextContent("跟进已关闭");
    expect(within(screen.getByRole("article", { name: "订单 草稿单" })).queryByRole("button", { name: "批量更新生产进度" })).not.toBeInTheDocument();
  });
  it("keeps empty and unchanged values out of changes and never splits a SellerSKU", () => {
    expect(progressChanges(multi, { "101": "80", "102": "", "103": "1" })).toEqual([]);
    expect(progressNumber("0")).toBe(true); expect(progressNumber("9223372036854775808")).toBe(false);
    expect(orderProductName(order.lines![0]!, skuCatalog)).toBe("0012-沙色-M");
    expect(orderProductName(order.lines![0]!, [])).toBe("QA-Blue-M");
  });
});

it("shows only ordered, produced and received quantities and starts shipment independently",async()=>{
 mount("/production/orders");await screen.findByRole("columnheader",{name:"下单 / 计划生产"});const overview=screen.getByRole("region",{name:"工厂订单跟进总览"});
 expect(within(overview).queryByRole("columnheader",{name:"已出货"})).not.toBeInTheDocument();
 expect(overview).not.toHaveTextContent("已出货");expect(within(overview).queryByRole("link",{name:"本单出货"})).not.toBeInTheDocument();
 expect(within(overview).getByRole("link",{name:"仓库出货"})).toHaveAttribute("href","/production/shipments/intake");
 for(const name of ["下单 / 计划生产","已生产","已入库"])expect(within(overview).getByRole("columnheader",{name})).toBeInTheDocument();
});

it("offers contextual shared actions after an explicit row selection and preserves it after returning",async()=>{
 const second={...order,id:"11",business_number:"第二张操作订单"};const original=api.read.getMockImplementation()!;
 api.read.mockImplementation(path=>path.startsWith("/api/production/orders?")?Promise.resolve({items:[order,second],page:1,page_size:20,total:2}):path==="/api/production/orders/11"?Promise.resolve(second):original(path));
 const router=mount("/production/orders?factory=3");await screen.findByRole("radio",{name:"选择订单 第二张操作订单"});
 expect(screen.queryByRole("region",{name:"订单统一操作"})).not.toBeInTheDocument();
 for(const card of screen.getAllByRole("article"))for(const name of ["入库","操作记录","导出下单表"])expect(within(card).queryByRole("link",{name})).not.toBeInTheDocument();
 await userEvent.click(screen.getByRole("radio",{name:"选择订单 第二张操作订单"}));
 const actions=screen.getByRole("region",{name:"订单统一操作"});
 expect(router.state.location.search).toContain("action_order=11");
 expect(within(actions).getByRole("link",{name:"导出下单表"})).toHaveAttribute("href","/api/production/orders/11/table");
 expect(within(actions).getByRole("link",{name:"入库"}).getAttribute("href")).toContain("/orders/11?factory=3&action_order=11&tab=receive");
 await userEvent.click(within(actions).getByRole("link",{name:"操作记录"}));
 expect(await screen.findByRole("heading",{name:"操作记录"})).toBeInTheDocument();
 await act(()=>router.navigate(-1));
 expect(await screen.findByRole("radio",{name:"选择订单 第二张操作订单"})).toBeChecked();
 expect(screen.getAllByRole("region",{name:"订单统一操作"})).toHaveLength(1);expect(api.write).not.toHaveBeenCalled();
});
it("does not substitute another order when the selected order leaves the filtered result",async()=>{
 const original=api.read.getMockImplementation()!;const second={...order,id:"11",business_number:"另一张操作单"};
 api.read.mockImplementation(path=>path.startsWith("/api/production/orders?")?Promise.resolve({items:path.includes("q=first")?[order]:[order,second],page:1,page_size:20,total:2}):original(path));
 const router=mount("/production/orders?action_order=11");await screen.findByRole("radio",{name:"选择订单 另一张操作单"});
 expect(screen.getByRole("link",{name:"导出下单表"})).toHaveAttribute("href","/api/production/orders/11/table");
 await act(()=>router.navigate("/production/orders?action_order=11&q=first"));
 await screen.findByText("所选订单不在当前结果中");
 expect(screen.queryByRole("region",{name:"订单统一操作"})).not.toBeInTheDocument();
 expect(screen.queryByRole("link",{name:"入库"})).not.toBeInTheDocument();
});
it("retains shared history and export for viewers without exposing receipt entry",async()=>{
 mount("/production/orders?action_order=10",false);
 const exportLink=await screen.findByRole("link",{name:"导出下单表"});expect(exportLink).toHaveAttribute("href","/api/production/orders/10/table");
 const actions=screen.getByRole("region",{name:"订单统一操作"});expect(within(actions).queryByRole("link",{name:"入库"})).not.toBeInTheDocument();expect(within(actions).queryByRole("button",{name:"入库"})).not.toBeInTheDocument();expect(within(actions).getByRole("link",{name:"操作记录"})).toBeInTheDocument();expect(api.write).not.toHaveBeenCalled();
});

describe("multi-order receipt batch", () => {
  const second: Document = { ...order, id: "11", revision: "4", business_number: "第二张生产单", lines: [{ ...order.lines![0]!, id: "102", received_units: "0" }] };
  const batchSource = { id: "receipt-batch", revision: "10:2,11:4", status: "CONFIRMED", lines: [{ ...order.lines![0]!, order_label: order.business_number }, { ...second.lines![0]!, order_label: second.business_number }] };
  function setup() {
    const base = api.read.getMockImplementation()!;
    api.read.mockImplementation(async path => {
      if (path.startsWith("/api/production/receipt-batches/sources?")) return batchSource;
      if (path.startsWith("/api/production/orders?")) return { items: [order, second], page: 1, page_size: 20, total: 2 };
      return base(path);
    });
  }
  const entry = "/production/orders/receipts/new?orders=10:2,11:4";
  const firstLabel = `${order.business_number} / QA-Blue-M本次合格`;
  const secondLabel = `${second.business_number} / QA-Blue-M本次合格`;
  it("starts with explicit multi-order selection and a batch-bound import template", async () => {
    setup(); const router = mount("/production/orders/receipts/new");
    expect(await screen.findByRole("button", { name: "开始本批入库" })).toBeDisabled();
    await userEvent.click(await screen.findByLabelText(`选择 ${order.business_number}`));
    await userEvent.click(screen.getByLabelText(`选择 ${second.business_number}`));
    await userEvent.click(screen.getByRole("button", { name: "开始本批入库" }));
    await enterInlineImport();
    expect(router.state.location.search).toContain("orders=10%3A2%2C11%3A4");
    expect(screen.getByRole("link", { name: "下载入库模板" })).toHaveAttribute("href", "/api/production/receipt-batches/table/template?orders=10%3A2%2C11%3A4");
    expect(api.write).not.toHaveBeenCalled();
  });
  it("imports one batch and preserves separate source allocations through one confirmation", async () => {
    setup();
    api.write.mockImplementation(async (path) => {
      await Promise.resolve();
      if (path.includes("/table/preview")) return { kind: "receipt", filename: "batch.xlsx", source_digest: "digest", order_id: "receipt-batch", order_revision: "10:2,11:4", total_units: "7", box_count: 0, issues: [], cartons: [], rows: [{ row: 2, sku_id: "1001", order_line_id: "101", sku_label: "QA-Blue-M", qualified_units: "3", pending_units: "1", defective_units: "0" }, { row: 3, sku_id: "1001", order_line_id: "102", sku_label: "QA-Blue-M", qualified_units: "2", pending_units: "0", defective_units: "1" }] };
      if (path.endsWith("/confirm")) return { id: "501", revision: "2", status: "POSTED" };
      if (path.endsWith("/preview")) return { id: "501", revision: "1", status: "DRAFT", preview_hash: "qa-preview", impacts: [] };
      return { id: "501", revision: "1", status: "DRAFT" };
    });
    const router = mount(entry);
    await userEvent.selectOptions(await screen.findByLabelText(/本次实收入库仓库/), "900:1");
    await enterInlineImport();
    await userEvent.upload(screen.getByLabelText(/本次导入的XLSX文件/), new File(["fictional"], "batch.xlsx"));
    
    expect(await screen.findByLabelText(firstLabel)).toHaveValue("3");
    expect(screen.getByLabelText(secondLabel)).toHaveValue("2");
    expect(api.write).toHaveBeenCalledTimes(1);
    await userEvent.click(screen.getByRole("button", { name: "下一步" }));
    expect(screen.getByLabelText(/入库依据 \/ 备注/)).toHaveValue("表格导入：batch.xlsx");
    await userEvent.click(screen.getByRole("button", { name: "下一步" }));
    await userEvent.click(screen.getByRole("button", { name: "保存草稿并预览" }));
    await screen.findByRole("button", { name: "确认本次入库" });
    const draftCall = api.write.mock.calls.find(([path]) => path === "/api/production/inventory/documents")!;
    expect(draftCall[1].body).toMatchObject({ kind: "IN", warehouse_id: "900", owner_id: "1" });
    expect(draftCall[1].body.lines).toEqual(expect.arrayContaining([
      expect.objectContaining({ sku_id: "1001", quality: "QUALIFIED", units: "3", production_allocations: [{ order_line_id: "101", units: "3" }] }),
      expect.objectContaining({ sku_id: "1001", quality: "PENDING", units: "1", production_allocations: [{ order_line_id: "101", units: "1" }] }),
      expect.objectContaining({ sku_id: "1001", quality: "QUALIFIED", units: "2", production_allocations: [{ order_line_id: "102", units: "2" }] }),
      expect.objectContaining({ sku_id: "1001", quality: "DEFECTIVE", units: "1", production_allocations: [{ order_line_id: "102", units: "1" }] }),
    ]));
    expect(router.state.location.search).toContain("receipt_draft=501");
    await userEvent.click(screen.getByRole("button", { name: "确认本次入库" }));
    expect(await screen.findByText("本批入库已确认")).toBeInTheDocument();
    expect(api.write.mock.calls.filter(([path]) => path.endsWith("/confirm"))).toHaveLength(1);
    expect(api.write.mock.calls.some(([path]) => path.includes("production-progress"))).toBe(false);
  });
  it("preserves manual quantities after invalid imports and on attempted navigation", async () => {
    setup();
    api.write.mockResolvedValue({ kind: "receipt", filename: "bad.xlsx", order_id: "receipt-batch", order_revision: "10:2,11:4", rows: [], issues: [{ row: 2, message: "订单明细ID不在本批所选订单内" }], cartons: [], total_units: "0" });
    mount(entry);
    await userEvent.selectOptions(await screen.findByLabelText(/本次实收入库仓库/), "900:1");
    await userEvent.click(screen.getByRole("button", { name: "下一步" }));
    await userEvent.type(screen.getByLabelText(firstLabel), "3");
    await enterInlineImport();
    await userEvent.upload(screen.getByLabelText(/本次导入的XLSX文件/), new File(["fictional"], "bad.xlsx"));
    
    await screen.findByText("第2行 订单明细ID不在本批所选订单内");
    expect(screen.getByLabelText(firstLabel)).toHaveValue("3");
    await userEvent.click(screen.getByRole("link", { name: "返回订单跟进" }));
    await userEvent.click(await screen.findByRole("button", { name: "继续填写" }));
    expect(screen.getByLabelText(firstLabel)).toHaveValue("3");
    expect(api.write).toHaveBeenCalledTimes(1);
  });
  it("rejects an import assigning a valid SKU to a foreign order line", async () => {
    setup(); mount(entry);
    api.write.mockResolvedValue({ kind: "receipt", order_id: "receipt-batch", order_revision: "10:2,11:4", rows: [{ sku_id: "1001", order_line_id: "999", qualified_units: "9" }], issues: [] });
    await userEvent.selectOptions(await screen.findByLabelText(/本次实收入库仓库/),"900:1");
    await enterInlineImport();
    await userEvent.upload(screen.getByLabelText(/本次导入的XLSX文件/), new File(["fictional"], "wrong-line.xlsx"));
    
    expect(await screen.findByText("预览来源或可操作商品范围已改变，请重新核对当前操作范围。")).toBeInTheDocument();
    expect(screen.getByLabelText(firstLabel)).toHaveValue("");
    expect(api.write).toHaveBeenCalledTimes(1);
  });
  it("resumes one saved multi-order draft without flattening its allocations", async () => {
    setup(); const base = api.read.getMockImplementation()!;
    api.read.mockImplementation(path => path === "/api/production/inventory/documents/501" ? Promise.resolve({ id: "501", kind: "IN", revision: "2", status: "DRAFT", warehouse_id: "900", owner_id: "1", business_date: "2026-10-30", reason: "多单实际送货", lines: [{ sku_id: "1001", quality: "QUALIFIED", units: "5", purpose: "PRODUCTION_RECEIPT", production_allocations: [{ order_line_id: "101", units: "3" }, { order_line_id: "102", units: "2" }] }] }) : base(path));
    mount(`${entry}&receipt_draft=501`);
    await userEvent.click(await screen.findByRole("button", { name: "下一步" }));
    expect(screen.getByLabelText(firstLabel)).toHaveValue("3");
    expect(screen.getByLabelText(secondLabel)).toHaveValue("2");
    await userEvent.click(screen.getByRole("button", { name: "下一步" }));
    expect(screen.getByLabelText(/入库依据 \/ 备注/)).toHaveValue("多单实际送货");
    expect(api.write).not.toHaveBeenCalled();
  });
  it("keeps uncertain batch saves locked and queries the original operation", async () => {
    setup(); mount(entry);
    await userEvent.selectOptions(await screen.findByLabelText(/本次实收入库仓库/), "900:1");
    await userEvent.click(screen.getByRole("button", { name: "下一步" }));
    await userEvent.type(screen.getByLabelText(firstLabel), "2");
    await userEvent.click(screen.getByRole("button", { name: "下一步" }));
    await userEvent.type(screen.getByLabelText(/入库依据 \/ 备注/), "实际送货");
    await userEvent.click(screen.getByRole("button", { name: "下一步" }));
    api.write.mockRejectedValue(new Error("QA response lost"));
    await userEvent.click(screen.getByRole("button", { name: "保存草稿并预览" }));
    await screen.findByRole("button", { name: "查询原操作结果" });
    expect(screen.getByRole("button", { name: "返回修改" })).toBeDisabled();
    await userEvent.click(screen.getByRole("link", { name: "返回订单跟进" }));
    expect(await screen.findByText("先核实保存结果")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "放弃并离开" })).not.toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "继续核实" }));
    const key = api.write.mock.calls[0]![1].operationKey;
    await userEvent.click(screen.getByRole("button", { name: "查询原操作结果" }));
    expect(api.read).toHaveBeenCalledWith(`/api/production/commands/${key}`);
    expect(api.write).toHaveBeenCalledTimes(1);
  });
  it("blocks viewer entry before reading source orders", async () => {
    setup(); mount(entry, false);
    expect(await screen.findByText("当前账号只读")).toBeInTheDocument();
    expect(api.read.mock.calls.some(([path]) => path.includes("receipt-batches"))).toBe(false);
    expect(api.write).not.toHaveBeenCalled();
  });
});


describe("overview tools and factory overlays", () => {
  it("keeps secondary tools together and reuses the order dialog for table intake", async () => {
    mount("/production/orders?factory=3&todo=WAIT_RECEIPT");
    const trigger = await screen.findByRole("button", { name: "更多" });
    const overview = screen.getByRole("region", { name: "工厂订单跟进总览" });
    expect(overview.querySelector("header details")).toBeNull();
    await userEvent.click(trigger);
    const menu = screen.getByRole("menu");
    expect(overview).not.toContainElement(menu);
    expect(within(menu).getAllByRole("menuitem")).toHaveLength(5);
    const paths = { "订单原表与整理记录": "/production/orders/materials", "全部出货": "/production/shipments", "历史订单出货汇总": "/production/summary" };
    for (const [name, href] of Object.entries(paths)) expect(within(menu).getByRole("menuitem", { name })).toHaveAttribute("href", href);
    await userEvent.click(within(menu).getByRole("menuitem",{name:"从表格下单"}));
    const dialog=await screen.findByRole("dialog",{name:"下单与生产计划"});
    expect(within(dialog).queryByRole("button",{name:"表格导入"})).not.toBeInTheDocument();
    expect(within(dialog).getByRole("link",{name:"下载下单模板"})).toBeInTheDocument();
    expect(within(menu).getByRole("menuitem", { name: "导出订单" })).toHaveAttribute("href", expect.stringContaining("tracking=WAIT_RECEIPT"));
    await userEvent.keyboard("{Escape}");
    await waitFor(() => expect(trigger).toHaveFocus());
    expect(screen.queryByRole("menu")).not.toBeInTheDocument();
    expect(api.write).not.toHaveBeenCalled();
  });
  it("opens a searchable factory dialog and applies a selection without losing other filters", async () => {
    const router = mount("/production/orders?q=QA&status=CONFIRMED&page=2&action_order=10");
    const trigger = await screen.findByRole("button", { name: "选择工厂" });
    expect(trigger).toHaveTextContent("全部工厂");
    await userEvent.click(trigger);
    const dialog = screen.getByRole("dialog", { name: "选择工厂" });
    expect(screen.getByRole("region", { name: "工厂订单跟进总览", hidden: true })).not.toContainElement(dialog);
    await userEvent.type(within(dialog).getByLabelText("搜索工厂"), "青禾");
    await waitFor(() => expect(api.read.mock.calls.some(([path]) => path.startsWith("/api/production/factories?") && new URL(path, "http://qa").searchParams.get("q") === "青禾")).toBe(true));
    await userEvent.click(await within(dialog).findByRole("button", { name: "筛选工厂：青禾示例厂" }));
    expect(screen.queryByRole("dialog", { name: "选择工厂" })).not.toBeInTheDocument();
    const params = new URLSearchParams(router.state.location.search);
    expect(Object.fromEntries(params)).toMatchObject({ q: "QA", status: "CONFIRMED", page: "1", factory: "3", action_order: "10" });
    await waitFor(() => expect(trigger).toHaveFocus());
    expect(trigger).toHaveTextContent("青禾示例厂");
    expect(api.write).not.toHaveBeenCalled();
  });
  it("supports escape without changing a filter and shows factory empty results", async () => {
    const base = api.read.getMockImplementation()!;
    api.read.mockImplementation(path => path.startsWith("/api/production/factories?") && new URL(path, "http://qa").searchParams.get("q") ? Promise.resolve({ items: [], total: 0 }) : base(path));
    const router = mount("/production/orders?factory=3");
    const trigger = await screen.findByRole("button", { name: "选择工厂" });
    await userEvent.click(trigger);
    await userEvent.type(screen.getByLabelText("搜索工厂"), "不存在");
    expect(await screen.findByText("没有匹配的工厂，请调整名称。")).toBeInTheDocument();
    await userEvent.keyboard("{Escape}");
    await waitFor(() => expect(trigger).toHaveFocus());
    expect(new URLSearchParams(router.state.location.search).get("factory")).toBe("3");
    expect(api.write).not.toHaveBeenCalled();
  });
});

it("keeps an uninitialized planned warehouse selected across directory searches",async()=>{
 const base=api.read.getMockImplementation()!;
 api.read.mockImplementation(path=>path.startsWith('/api/production/warehouses?')&&new URL(path,'http://qa').searchParams.get('q')?Promise.resolve({items:[],total:0,page:1,page_size:50}):path.endsWith('/inventory/availability')?Promise.resolve({scopes:[],items:[]}):base(path));
 mount('/production/orders/new');const warehouse=await screen.findByLabelText(/生产完成后入库仓库/);
 await screen.findByRole('option',{name:'虚构仓900'});await userEvent.selectOptions(warehouse,'900:1');
 await userEvent.type(screen.getByRole('searchbox',{name:'查找计划入库仓'}),'无匹配仓');
 await waitFor(()=>expect(api.read.mock.calls.some(([path])=>path.includes('q=%E6%97%A0'))).toBe(true));
 expect(warehouse).toHaveValue('900:1');expect(within(warehouse).getByRole('option',{name:'虚构仓900'})).toBeInTheDocument();expect(api.write).not.toHaveBeenCalled();
});


describe("same-page order creation and streamlined search",()=>{
  it("opens one order dialog, retains both input methods, and preserves filters and focus on close",async()=>{
    const router=mount("/production/orders?factory=3&q=QA&page=2");
    const trigger=await screen.findByRole("button",{name:"下单"});
    await userEvent.click(trigger);
    const dialog=await screen.findByRole("dialog",{name:"下单与生产计划"});
    expect(router.state.location.pathname).toBe("/production/orders");
    expect(router.state.location.search).toContain("new=1");
    await userEvent.type(within(dialog).getByLabelText("业务订单号（可选）"),"QA local draft");
    expect(within(dialog).getByLabelText(/下单XLSX文件/)).toBeInTheDocument();
    
    expect(within(dialog).getByLabelText("业务订单号（可选）")).toHaveValue("QA local draft");
    const closeButton = within(dialog).getByRole("button",{name:"关闭下单"});
    await userEvent.click(closeButton);
    const confirmation = screen.getByRole("dialog",{name:"保留当前填写，还是放弃？"});
    expect(dialog.contains(confirmation)).toBe(false);
    await userEvent.keyboard("{Escape}");
    await waitFor(()=>expect(closeButton).toHaveFocus());
    expect(within(dialog).getByLabelText("业务订单号（可选）")).toHaveValue("QA local draft");
    await userEvent.click(closeButton);
    await userEvent.click(within(screen.getByRole("dialog",{name:"保留当前填写，还是放弃？"})).getByRole("button",{name:"继续填写"}));
    expect(within(dialog).getByLabelText("业务订单号（可选）")).toHaveValue("QA local draft");
    await userEvent.click(within(dialog).getByRole("button",{name:"关闭下单"}));
    await userEvent.click(within(screen.getByRole("dialog",{name:"保留当前填写，还是放弃？"})).getByRole("button",{name:"放弃并关闭"}));
    await waitFor(()=>expect(screen.queryByRole("dialog",{name:"下单与生产计划"})).not.toBeInTheDocument());
    expect(router.state.location.search).toBe("?factory=3&q=QA&page=2");
    await waitFor(()=>expect(trigger).toHaveFocus());
    expect(api.write).not.toHaveBeenCalled();
  });
  it("saves a manual draft inside the dialog, closes it and retains the filtered list",async()=>{
    api.write.mockResolvedValue({...order,id:"11",business_number:"QA modal draft",status:"DRAFT"});
    const router=mount("/production/orders?factory=3&q=QA&page=2");
    await userEvent.click(await screen.findByRole("button",{name:"下单"}));
    const dialog=await screen.findByRole("dialog",{name:"下单与生产计划"});
    await userEvent.selectOptions(within(dialog).getByLabelText(/生产完成后入库仓库/),"900:1");
    await userEvent.selectOptions(within(dialog).getByLabelText("产品1"),"1001");
    await userEvent.type(within(dialog).getByLabelText("产品1下单数量"),"3");
    await userEvent.click(within(dialog).getByRole("button",{name:"保存草稿"}));
    expect(await screen.findByText("订单草稿已保存")).toBeVisible();
    await waitFor(()=>expect(screen.queryByRole("dialog",{name:"下单与生产计划"})).not.toBeInTheDocument());
    expect(router.state.location.pathname).toBe("/production/orders");
    expect(router.state.location.search).toBe("?factory=3&q=QA&page=2");
    expect(screen.getByRole("link",{name:"查看新订单"})).toHaveAttribute("href","/production/orders/11?factory=3&q=QA&page=2");
    expect(api.write.mock.calls[0]?.[1].body).toMatchObject({save_mode:"draft",factory_id:"3",lines:[{sku_id:"1001",expected_units:"3"}]});
  });
  it("retains a selected import file behind the close guard on a direct new-order link",async()=>{
    const router=mount("/production/orders/new?method=table&factory=3");
    const dialog=await screen.findByRole("dialog",{name:"下单与生产计划"});
    await screen.findByRole("option", { name: "虚构仓900" });
    await userEvent.selectOptions(await screen.findByLabelText(/生产完成后入库仓库/),"900:1");
    api.write.mockResolvedValue({issues:[{row:2,message:"样例错误"}],rows:[],command:{},filename:"qa.xlsx"});
    const file=new File(["fictional"],"qa.xlsx");
    await userEvent.upload(within(dialog).getByLabelText("下单XLSX文件（不超过2MB）"),file);
    await userEvent.click(within(dialog).getByRole("button",{name:"关闭下单"}));
    expect(within(screen.getByRole("dialog",{name:"保留当前填写，还是放弃？"})).getByRole("button",{name:"放弃并关闭"})).toBeVisible();
    await userEvent.click(within(screen.getByRole("dialog",{name:"保留当前填写，还是放弃？"})).getByRole("button",{name:"继续填写"}));
    expect(within(dialog).getByText("第2行 样例错误")).toBeInTheDocument();
    expect(router.state.location.pathname).toBe("/production/orders/new");
  });
  it("does not let a pending search dismiss an open order dialog",async()=>{
    const router=mount("/production/orders?factory=3");
    const input=await screen.findByRole("searchbox",{name:"搜索工厂、订单或SKU"});
    fireEvent.change(input,{target:{value:"QA"}});
    fireEvent.click(screen.getByRole("button",{name:"下单"}));
    const dialog=await screen.findByRole("dialog",{name:"下单与生产计划"});
    await act(()=>new Promise(resolve=>setTimeout(resolve,350)));
    expect(dialog).toBeVisible();
    expect(new URLSearchParams(router.state.location.search).get("new")).toBe("1");
    await userEvent.click(within(dialog).getByRole("button",{name:"关闭下单"}));
    await waitFor(()=>expect(new URLSearchParams(router.state.location.search).get("q")).toBe("QA"));
    expect(api.write).not.toHaveBeenCalled();
  });
  it("queries the server after a pause, defers Chinese composition, and clears in one click",async()=>{
    const router=mount("/production/orders?factory=3&page=2");
    const input=await screen.findByRole("searchbox",{name:"搜索工厂、订单或SKU"});
    expect(screen.queryByRole("button",{name:"查找"})).not.toBeInTheDocument();
    fireEvent.compositionStart(input);fireEvent.change(input,{target:{value:"青禾"}});
    await act(()=>new Promise(resolve=>setTimeout(resolve,350)));
    expect(router.state.location.search).not.toContain("q=");
    fireEvent.compositionEnd(input);
    await waitFor(()=>expect(new URLSearchParams(router.state.location.search).get("q")).toBe("青禾"));
    expect(router.state.location.search).toContain("factory=3");
    expect(router.state.location.search).toContain("page=1");
    await userEvent.click(screen.getByRole("button",{name:"清除搜索"}));
    expect(input).toHaveValue("");expect(new URLSearchParams(router.state.location.search).get("q")).toBeNull();
    expect(api.write).not.toHaveBeenCalled();
  });
});


it("confirms a new order only after the existing source check and returns to the same list",async()=>{
  api.write.mockImplementation(path=>Promise.resolve(path === "/api/production/sources/orders/check" ? {candidates:[]} : {...order,id:"11",status:"CONFIRMED"}));
  const router=mount("/production/orders?factory=3");
  await userEvent.click(await screen.findByRole("button",{name:"下单"}));
  const dialog=await screen.findByRole("dialog",{name:"下单与生产计划"});
  await userEvent.selectOptions(within(dialog).getByLabelText(/生产完成后入库仓库/),"900:1");
  await userEvent.selectOptions(within(dialog).getByLabelText("产品1"),"1001");
  await userEvent.type(within(dialog).getByLabelText("产品1下单数量"),"3");
  await userEvent.click(within(dialog).getByRole("button",{name:"核对并确认下单"}));
  await screen.findByText("生产单已下达");
  await waitFor(()=>expect(screen.queryByRole("dialog",{name:"下单与生产计划"})).not.toBeInTheDocument());
  expect(api.write.mock.calls.map(([path])=>path)).toEqual(["/api/production/sources/orders/check","/api/production/orders"]);
  expect(api.write.mock.calls[1]?.[1].body).toMatchObject({save_mode:"confirm",factory_id:"3"});
  expect(router.state.location.search).toBe("?factory=3");
});

it("locks an uncertain order save and recovers its original operation before closing",async()=>{
  api.write.mockRejectedValue(new Error("network result unknown"));
  const original=api.read.getMockImplementation()!;
  api.read.mockImplementation(path=>path.startsWith("/api/production/commands/") ? Promise.resolve({...order,id:"11",status:"DRAFT"}) : original(path));
  mount("/production/orders?factory=3");
  await userEvent.click(await screen.findByRole("button",{name:"下单"}));
  const dialog=await screen.findByRole("dialog",{name:"下单与生产计划"});
  await userEvent.selectOptions(within(dialog).getByLabelText(/生产完成后入库仓库/),"900:1");
  await userEvent.selectOptions(within(dialog).getByLabelText("产品1"),"1001");
  await userEvent.type(within(dialog).getByLabelText("产品1下单数量"),"3");
  await userEvent.click(within(dialog).getByRole("button",{name:"保存草稿"}));
  await within(dialog).findByText("保存结果待核实，已锁定当前输入");
  expect(within(dialog).getByRole("button",{name:"关闭下单"})).toBeDisabled();
  expect(within(dialog).getByLabelText("产品1下单数量")).toBeDisabled();
  await userEvent.click(within(dialog).getByRole("button",{name:"查询原操作结果"}));
  await screen.findByText("订单草稿已保存");
  await waitFor(()=>expect(screen.queryByRole("dialog",{name:"下单与生产计划"})).not.toBeInTheDocument());
  expect(api.write).toHaveBeenCalledTimes(1);
  expect(api.read.mock.calls.some(([path])=>path === `/api/production/commands/${api.write.mock.calls[0]?.[1].operationKey}`)).toBe(true);
});

it("switches shared manual completion on the server and keeps export in the same scope",async()=>{
 const previous=api.read.getMockImplementation()!;
 let completed=false;
 api.read.mockImplementation(path=>{
  if(path.startsWith("/api/production/orders?")){
   const progress=new URL(path,"http://qa").searchParams.get("progress");
   const current={...order,production_completion_state:completed?"COMPLETED":"OPEN",production_completion_ready:true};
   const visible=progress==="all" || (progress==="completed")===completed;
   return Promise.resolve({items:visible?[current]:[],total:visible?1:0,page:1,page_size:20,progress_counts:{active:completed?0:1,completed:completed?1:0,all:1}});
  }
  return previous(path);
 });
 api.write.mockImplementation(path=>{completed=path.endsWith("/complete-production");return Promise.resolve({...order,production_completion_state:completed?"COMPLETED":"OPEN",production_completion_ready:true});});
 const router=mount("/production/orders");
 expect(await screen.findByRole("button",{name:"进行中 1"})).toHaveAttribute("aria-pressed","true");
 expect(screen.getByRole("button",{name:"确认完成"})).toBeVisible();expect(api.write).not.toHaveBeenCalled();
 await userEvent.click(screen.getByRole("button",{name:"确认完成"}));
 await screen.findByRole("button",{name:"进行中 0"});expect(screen.queryByRole("article")).not.toBeInTheDocument();
 await userEvent.click(screen.getByRole("button",{name:"已完成 1"}));
 await screen.findByRole("button",{name:"恢复进行中"});expect(router.state.location.search).toContain("progress=completed");
 await userEvent.click(screen.getByRole("button",{name:"更多"}));
 expect(screen.getByRole("menuitem",{name:"导出订单"})).toHaveAttribute("href",expect.stringContaining("progress=completed"));
 await userEvent.keyboard("{Escape}");
 await userEvent.click(screen.getByRole("button",{name:"恢复进行中"}));
 await screen.findByRole("button",{name:"已完成 0"});
 await userEvent.click(screen.getByRole("button",{name:"进行中 1"}));expect(await screen.findByRole("button",{name:"确认完成"})).toBeVisible();
});
it("applies filter chips once and supports cancel, reset, and clearing while preserving completion",async()=>{
 const router=mount("/production/orders?progress=all&factory=3");
 const trigger=await screen.findByRole("button",{name:"筛选"});
 await userEvent.click(trigger);let dialog=screen.getByRole("dialog",{name:"筛选订单"});
 await userEvent.click(within(dialog).getByRole("button",{name:"草稿"}));
 expect(router.state.location.search).not.toContain("status=");
 await userEvent.click(within(dialog).getByRole("button",{name:"取消"}));await waitFor(()=>expect(trigger).toHaveFocus());
 await userEvent.click(trigger);dialog=screen.getByRole("dialog",{name:"筛选订单"});
 expect(within(dialog).getByRole("button",{name:"全部状态"})).toHaveAttribute("aria-pressed","true");
 await userEvent.click(within(dialog).getByRole("button",{name:"草稿"}));
 await userEvent.click(within(dialog).getByRole("button",{name:"应用筛选"}));
 expect(await screen.findByRole("button",{name:"清除状态筛选"})).toHaveTextContent("草稿");
 expect(router.state.location.search).toContain("progress=all");
 await userEvent.click(screen.getByRole("button",{name:"筛选 · 1"}));dialog=screen.getByRole("dialog",{name:"筛选订单"});
 await userEvent.click(within(dialog).getByRole("button",{name:"重置"}));
 expect(within(dialog).getByRole("button",{name:"全部状态"})).toHaveAttribute("aria-pressed","true");
 await userEvent.click(within(dialog).getByRole("button",{name:"应用筛选"}));
 await waitFor(()=>expect(new URLSearchParams(router.state.location.search).get("status")).toBeNull());
 expect(router.state.location.search).toContain("factory=3");expect(router.state.location.search).toContain("progress=all");
 expect(api.write).not.toHaveBeenCalled();
});

it("reopens an imported order draft and retains the baseline when saving edits without confirming",async()=>{
  const id=`table-baseline-${"c".repeat(64)}`;
  const base=api.read.getMockImplementation()!;
  api.read.mockImplementation(path=>path==="/api/production/orders/10"?Promise.resolve({...order,status:"DRAFT",notes:`表格基准=${id}`}):path===`/api/production/table-baselines/${id}`?Promise.resolve({id,kind:"orders",filename:"sim.xlsx",rows:[{key:"document",label:"订单信息",values:{"下单日期":order.business_date,"业务订单号":order.business_number}},{key:"1001",label:"QA-Blue-M",row:2,values:{"下单数量":"100"}}]}):base(path));
  api.write.mockResolvedValue({...order,status:"DRAFT",notes:`表格基准=${id}`});
  mount("/production/orders/10?edit=1");
  await waitFor(()=>expect(screen.getByRole("button",{name:"保存草稿修改"})).toBeEnabled());
  await userEvent.click(screen.getByRole("button",{name:"保存草稿修改"}));
  expect(screen.getByRole("region",{name:"原表修改核对"})).toBeInTheDocument();
  expect(api.write).not.toHaveBeenCalled();
  await userEvent.click(screen.getByRole("button",{name:"保存草稿修改"}));
  await waitFor(()=>expect(api.write).toHaveBeenCalled());
  expect(api.write.mock.calls[0]![1].body).toMatchObject({save_mode:"draft",_table_baseline_id:id});
  expect(api.write.mock.calls[0]![1].body).toHaveProperty("notes",expect.stringContaining(id));
});

it("previews cumulative receipts compactly and expands imported quality quantities without losing them", async () => {
 mount("/production/orders/10?tab=receive");
 await openOperation("receive");
 await userEvent.click(screen.getByRole("button", { name:"下一步" }));
 const table=screen.getByRole("table", { name:"本次入库产品" });
 expect(within(table).getAllByRole("columnheader").map(cell=>cell.textContent)).toEqual(["商品规格","下单","已生产","累计入库","本次入库"]);
 expect(screen.queryByLabelText("QA-Blue-M本次待检")).not.toBeInTheDocument();
 await userEvent.type(screen.getByLabelText("QA-Blue-M本次合格"),"10");
 expect(within(table).getByLabelText("QA-Blue-M已入库60件，确认后70件")).toBeVisible();
 await userEvent.clear(screen.getByLabelText("QA-Blue-M本次合格"));
 expect(within(table).queryByLabelText(/确认后/)).not.toBeInTheDocument();
 await userEvent.click(screen.getByRole("checkbox", { name:"填写待检或次品" }));
 await userEvent.type(screen.getByLabelText("QA-Blue-M本次待检"),"2");
 expect(within(table).getByLabelText("QA-Blue-M已入库60件，确认后62件")).toBeVisible();
 expect(screen.getByRole("checkbox", { name:"填写待检或次品" })).toBeDisabled();
 expect(api.write).not.toHaveBeenCalled();
});

it("defaults production to demand, preserves an adjusted plan and submits its reason",async()=>{
  api.write.mockImplementation(path=>Promise.resolve(path === "/api/production/sources/orders/check" ? {candidates:[]} : {...order,id:"11",status:"CONFIRMED"}));
  mount("/production/orders?factory=3"); await userEvent.click(await screen.findByRole("button",{name:"下单"}));
  const dialog=await screen.findByRole("dialog",{name:"下单与生产计划"});
  await userEvent.selectOptions(within(dialog).getByLabelText(/生产完成后入库仓库/),"900:1");
  await userEvent.selectOptions(within(dialog).getByLabelText("产品1"),"1001");
  await userEvent.type(within(dialog).getByLabelText("产品1下单数量"),"100");
  const target=within(dialog).getByLabelText("产品1计划生产数量"); expect(target).toHaveValue("100");
  await userEvent.clear(target);await userEvent.type(target,"70");
  const demand=within(dialog).getByLabelText("产品1下单数量"); await userEvent.clear(demand);await userEvent.type(demand,"110");
  expect(target).toHaveValue("70");
  await userEvent.type(within(dialog).getByLabelText(/生产计划调整原因/),"使用现有库存");
  await userEvent.click(within(dialog).getByRole("button",{name:"核对并确认下单"}));
  await within(dialog).findByRole("table",{name:"生产计划变更"});
  await userEvent.click(within(dialog).getByRole("button",{name:"确认下单"}));
  await screen.findByText("生产单已下达");
  expect(api.write.mock.calls.at(-1)?.[1].body).toMatchObject({production_plan_reason:"使用现有库存",lines:[{sku_id:"1001",expected_units:"110",planned_production_units:"70"}]});
});
