import { act, cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { createMemoryRouter, RouterProvider } from "react-router-dom";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import { AuthzGenerationProvider } from "../../app/AuthzGenerationContext";
import { ProductionWorkspace } from "./ProductionWorkspace";
import { packingError } from "./shipmentPacking";
import type { Document } from "./types";

const api = vi.hoisted(() => ({ read: vi.fn<(path: string) => Promise<unknown>>(), write: vi.fn<(path: string, options: { body: Record<string, unknown>; method?: string }) => Promise<unknown>>() }));
vi.mock("../../api/client", async original => ({ ...await original<typeof import("../../api/client")>(), requestApi: api.read, writeApi: api.write }));
const order: Document = { id: "10", business_number: "虚构生产单A", system_number: "PO-QA-A", business_date: "2026-10-27", status: "CONFIRMED", revision: "2", notes: "", actual_units: "0", destination: "虚构海外仓", receipt_warehouse_id: "900", receipt_owner_id: "1", lines: [{ id: "101", sku_id: "1001", sku_label: "QA Blue M", expected_units: "20", actual_units: "0", difference_units: "20" }] };
const draft: Document = { id: "20", business_number: "虚构混合来源草稿", system_number: "SH-QA-20", business_date: "2026-10-27", status: "DRAFT", revision: "4", notes: "保留原来源", actual_units: "5", warehouse_id: "900", owner_id: "1", destination: "虚构海外仓", cartons: [{ number: "QA-MIX", items: [{ sku_id: "1001", units: "5" }] }], sources: [{ id: "301", sku_id: "1001", plan_id: "91", fulfillment_mode: "WAREHOUSE_STOCK", actual_units: "3", allocations: [{ order_line_id: "101", order_number: "PO-QA-A", units: "3" }] }, { id: "302", sku_id: "1001", fulfillment_mode: "PRODUCTION_DIRECT", actual_units: "2", allocations: [{ order_line_id: "102", order_number: "PO-QA-B", units: "2" }] }] };

beforeEach(() => {
  Object.defineProperties(HTMLDialogElement.prototype, { showModal: { configurable: true, value: function(this: HTMLDialogElement) { this.setAttribute("open", ""); } }, close: { configurable: true, value: function(this: HTMLDialogElement) { this.removeAttribute("open"); } } });
  api.read.mockReset(); api.write.mockReset();
  const NativeRequest = globalThis.Request;
  vi.stubGlobal("Request", class extends NativeRequest { constructor(input: RequestInfo | URL, init?: RequestInit) { const { signal, ...options } = init || {}; super(input, options); if (signal) Object.defineProperty(this, "signal", { value: signal }); } });
  api.read.mockImplementation(async (path: string) => {
    await Promise.resolve();
    if (path === "/api/production/workbench") return { version: 1, directory_supported: false };
    if (path.startsWith("/api/production/orders?")) return { items: [order], total: 1, page: 1, page_size: 20 };
    if (path === "/api/production/orders/10") return order;
    if (path === "/api/production/skus?contract_version=2") return { items: [{ sku_id: "1001", label: "QA Blue M", code: "QA", status: "active", catalog_version: "fictional" }] };
    if (path === "/api/production/inventory/availability") return { writes_enabled: true, scopes: [{ warehouse_id: "900", owner_id: "1", warehouse_name: "虚构仓900", owner_name: "公司自有" }], items: [] };
    if (path.startsWith("/api/production/inventory/availability?")) return { state: "ready", on_hand_units: "50", free_available_units: "40", dispatch_allowed_units: "40", qualified_units: "40", pending_units: "10", own_reserved_units: "0" };
    if (path === "/api/production/inventory/plans") return { items: [{ id: "91", sku_id: "1001", warehouse_id: "900", direction: "OUT", source_reference: "虚构安排91", remaining_units: "10", planned_on: null }] };
    if (path.startsWith("/api/production/shipments?")) return { items: [], total: 0, page: 1, page_size: 20 };
    if (path === "/api/production/shipments/20") return draft;
    if (path.startsWith("/api/production/manual-tables")) return { items: [] };
    throw Error(`Unexpected fictional path ${path}`);
  });
  api.write.mockImplementation(path => Promise.resolve(path === "/api/production/shipments/table/reviews" ? {review_id:"dispatch-review-"+"b".repeat(64)} : draft));
});
afterEach(() => { cleanup(); vi.unstubAllGlobals(); });

it("fills unmatched imports into the shared editable grid and reviews edits without business writes", async () => {
 warehouseStock(); destinationDirectory();
 mount("/production/shipments/new?flow=guided&purpose=WAREHOUSE_DISPATCH&warehouse_id=900&owner_id=1&plan_id=91");
 await waitFor(()=>expect(screen.getByLabelText(/^本批实际发货目的地/)).toHaveValue("美国FBA"));
 await userEvent.click(screen.getByRole("button",{name:"下一步"}));
 expect(screen.queryByRole("button",{name:"手工填写"})).not.toBeInTheDocument();
 expect(screen.getByRole("table",{name:"本批商品出货表"})).toBeVisible();
 const preview = {kind:"packing",warehouse_id:"900",owner_id:"1",source_id:"upload-shipments-"+"a".repeat(64),source_digest:"a".repeat(64),filename:"original.xlsx",source_layout:"packing_totals",source_row_count:2,source_total_units:"14",rows:[],cartons:[],issues:[{row:2,message:"未建账",stage:"business"}],source_rows:[{row:2,sku_code:"RAW-A",sku_id:"",units:"8"},{row:3,sku_code:"RAW-B",sku_id:"",units:"6"}]};
 api.write.mockResolvedValueOnce(preview);
 await userEvent.selectOptions(screen.getByLabelText("表格格式"),"packing_totals");
 await userEvent.upload(screen.getByLabelText(/本次导入的XLSX文件/),new File(["fixture"],"original.xlsx"));
 const first = await screen.findByRole("textbox",{name:"本次实际数量 1"});
 await waitFor(()=>expect(first).toHaveValue("8"));
 expect(screen.getByRole("option",{name:"RAW-A（待匹配）"})).toBeInTheDocument();
 expect(screen.getAllByText("待核",{exact:true})).toHaveLength(2);
 await userEvent.click(screen.getByRole("button",{name:"查看商品1详情"}));
 expect(screen.getByLabelText("来源 1 的预计出库安排（可选）")).toHaveValue("");
 await userEvent.click(screen.getByRole("button",{name:"查看商品1详情"}));
 await userEvent.clear(first); await userEvent.type(first,"5");
 await userEvent.click(screen.getByRole("button",{name:"移除商品2"}));
 await userEvent.click(screen.getByRole("button",{name:"添加商品"}));
 await userEvent.type(screen.getByRole("textbox",{name:"本次实际数量 2"}),"1");
 await userEvent.click(screen.getByRole("button",{name:"下一步"}));
 const changes = await screen.findByRole("table",{name:"原表与当前填写对照"});
 expect(changes).toHaveTextContent("RAW-A · 8件");expect(changes).toHaveTextContent("RAW-A · 5件");
 expect(changes).toHaveTextContent("移除商品");expect(changes).toHaveTextContent("新增商品");
 expect(screen.getByRole("button",{name:"保存草稿"})).toBeDisabled();
 expect(screen.getByRole("button",{name:"确认已实际发货"})).toBeDisabled();
 expect(api.write).toHaveBeenCalledTimes(1);
 await userEvent.click(screen.getByRole("button",{name:"上一步"}));
 expect(screen.getByRole("textbox",{name:"本次实际数量 1"})).toHaveValue("5");
 expect(screen.getByLabelText("表格格式")).toHaveValue("packing_totals");
 api.write.mockResolvedValueOnce(preview).mockRejectedValueOnce(new Error("同一份装箱单已导入，请移除重复文件。"));
 await userEvent.upload(screen.getByLabelText(/本次导入的XLSX文件/),new File(["fixture"],"original.xlsx"));
 await screen.findByText("同一份装箱单已导入，请移除重复文件。");
 expect(screen.getByRole("textbox",{name:"本次实际数量 1"})).toHaveValue("5");
 await userEvent.click(screen.getByRole("button",{name:"下一步"}));
 expect(screen.getByRole("table",{name:"原表与当前填写对照"})).toHaveTextContent("RAW-A · 5件");
}, 15_000);

it("restores the original comparison from a saved draft without changing its input baseline", async () => {
 warehouseStock();
 const original = api.read.getMockImplementation()!;
 const reference = "dispatch-review-"+"c".repeat(64);
 const baseline = {kind:"packing",filename:"saved.xlsx",warehouse_id:"900",owner_id:"1",source_id:"upload-shipments-"+"a".repeat(64),source_digest:"a".repeat(64),source_layout:"standard",rows:[],source_rows:[{row:2,sku_code:"QA",sku_id:"1001",units:"8"},{row:3,sku_code:"RAW-X",sku_id:"",units:"4"}],issues:[],cartons:[]};
 api.read.mockImplementation(path => path===`/api/production/shipments/table/reviews/${reference}` ? Promise.resolve({baseline,rows:[{source_row:3,line_id:"302",sku_id:"1001",actual_units:"3"},{source_row:2,line_id:"301",sku_id:"1001",actual_units:"5"}]}) : path==="/api/production/shipments/20" ? Promise.resolve({...draft,dispatch_purpose:"WAREHOUSE_DISPATCH",cartons:null,manual_source_note:`出货校对=${reference}`,sources:[{...draft.sources![0]!,actual_units:"5",allocations:[]},{...draft.sources![0]!,id:"302",actual_units:"3",allocations:[]}]}) : original(path));
 mount("/production/shipments/20/edit?flow=guided");
 await screen.findByRole("heading",{name:"来源与目的地"});
 await userEvent.click(screen.getByRole("button",{name:"下一步"}));
 await waitFor(()=>expect(screen.getByRole("textbox",{name:"本次实际数量 1"})).toHaveValue("5"));
 await userEvent.click(screen.getByRole("button",{name:"下一步"}));
 const changes = await screen.findByRole("table",{name:"原表与当前填写对照"});
 expect(changes).toHaveTextContent("QA · 8件");expect(changes).toHaveTextContent("QA · 5件");
 expect(changes).toHaveTextContent("RAW-X · 4件");expect(changes).toHaveTextContent("QA · 3件");
 expect(api.write).not.toHaveBeenCalled();
});
function mount(path: string, canWrite = true) {
  const router = createMemoryRouter([{ path: "/production/*", element: <AuthzGenerationProvider boundary={{ principalId: 1, roles: canWrite ? ["admin"] : ["viewer"], siteId: 1, siteConfigVersionId: 1 }} onRevoked={() => undefined}><ProductionWorkspace canWrite={canWrite} /></AuthzGenerationProvider> }], { initialEntries: [path] });
  render(<RouterProvider router={router} />); return router;
}

it("opens the same shipment wizard from the shipment list entry and cancels without writing", async () => {
  const router = mount("/production/shipments/intake?mode=order");
  await screen.findByRole("option", { name: /虚构生产单A/ });
  expect(screen.getByRole("link", { name: "多订单或混合来源出货" })).toHaveAttribute("href", "/production/shipments/new?flow=guided&purpose=OUTWARD_ORDER");
  expect(screen.getByRole("link", { name: "其他表格与原资料" })).toHaveAttribute("href", "/production/shipments/intake?method=table");
  await userEvent.selectOptions(screen.getByLabelText("关联生产单"), "10");
  const dialog = await screen.findByRole("dialog", { name: "新建出货单" });
  expect(within(dialog).getByLabelText(/^本批实际发货目的地/)).toHaveValue("虚构海外仓");
  await userEvent.click(within(dialog).getByRole("button", { name: "下一步" }));
  expect(within(dialog).getByLabelText(/本次导入的XLSX文件/)).toBeVisible();
  expect(within(dialog).getByRole("link", { name: "下载装箱模板" })).toHaveAttribute("href", "/api/production/orders/10/tables/packing/template?expected_revision=2");
  await userEvent.click(within(dialog).getByRole("button", { name: "关闭新建出货单" }));
  await waitFor(() => expect(router.state.location.pathname).toBe("/production/shipments"));
  expect(api.write).not.toHaveBeenCalled();
});

it("prevents read-only accounts from entering either shipment editing flow", async () => {
  mount("/production/shipments/intake?source_order=10", false);
  await screen.findByText("当前账号只读");
  expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
  expect(screen.queryByRole("link", { name: "多订单或混合来源出货" })).not.toBeInTheDocument();
  expect(api.read.mock.calls.some(([path]) => path === "/api/production/orders/10")).toBe(false);
});

it("returns structured shipment drafts to the review flow instead of confirming directly from their details", async () => {
  mount("/production/shipments/20");
  const review = await screen.findByRole("link", { name: "核对并确认出货" });
  expect(review).toHaveAttribute("href", "/production/shipments/20/edit");
  expect(screen.queryByRole("button", { name: "确认单据" })).not.toBeInTheDocument();
  expect(screen.getByRole("table", { name: "本批装箱明细" })).toHaveTextContent("QA-MIX");
  expect(api.write).not.toHaveBeenCalled();
});

it("saves destination and carton data from the multi-order guide while retaining mixed sources and plan allocations", async () => {
  mount("/production/shipments/20/edit?flow=guided");
  const dialog = await screen.findByRole("dialog", { name: "出货装箱" });
  await userEvent.click(within(dialog).getByRole("button", { name: "下一步" }));
  expect(within(dialog).getByLabelText(/^本次实际数量 1/)).toHaveValue("3");
  expect(within(dialog).getByLabelText(/^本次实际数量 2/)).toHaveValue("2");
  expect(within(dialog).getByLabelText("来源 1 的预计出库安排（可选）")).toHaveValue("91");
  expect(within(dialog).getByLabelText("货物来源 2")).toHaveValue("PRODUCTION_DIRECT");
  await userEvent.click(within(dialog).getByRole("button", { name: "下一步" }));
  expect(within(dialog).getByLabelText("第1箱QA装箱数")).toHaveValue("5");
  await userEvent.clear(within(dialog).getByLabelText("第1箱箱号"));
  await userEvent.type(within(dialog).getByLabelText("第1箱箱号"), "QA-EDITED");
  await userEvent.click(within(dialog).getByRole("button", { name: "下一步" }));
  expect(within(dialog).getByRole("button", { name: "核对并确认本出货草稿" })).toBeDisabled();
  await userEvent.click(within(dialog).getByRole("button", { name: "保存草稿修改" }));
  await waitFor(() => expect(api.write).toHaveBeenCalled());
  const [path, options] = api.write.mock.calls[0]!;
  expect(path).toBe("/api/production/shipments/20");
  expect(options.method).toBe("PUT");
  expect(options.body).toMatchObject({ expected_revision: "4", destination: "虚构海外仓", cartons: [{ number: "QA-EDITED", items: [{ sku_id: "1001", units: "5" }] }], sources: [{ id: "301", plan_id: "91", fulfillment_mode: "WAREHOUSE_STOCK", actual_units: "3", allocations: [{ order_line_id: "101", units: "3" }] }, { id: "302", fulfillment_mode: "PRODUCTION_DIRECT", actual_units: "2", allocations: [{ order_line_id: "102", units: "2" }] }] });
  expect(api.write.mock.calls.some(([url]) => url.endsWith("/confirm"))).toBe(false);
});

it("uses the current draft revision and a separate confirmation request after the review step", async () => {
  api.write.mockResolvedValue({ ...draft, status: "CONFIRMED", revision: "5" });
  mount("/production/shipments/20/edit?flow=guided");
  const dialog = await screen.findByRole("dialog", { name: "出货装箱" });
  for (let index = 0; index < 3; index++) await userEvent.click(within(dialog).getByRole("button", { name: "下一步" }));
  await userEvent.click(within(dialog).getByRole("button", { name: "核对并确认本出货草稿" }));
  expect(api.write).not.toHaveBeenCalled();
  await userEvent.click(within(dialog).getByRole("button", { name: "确认本草稿已实际发货" }));
  await waitFor(() => expect(api.write).toHaveBeenCalledTimes(1));
  expect(api.write.mock.calls[0]?.[0]).toBe("/api/production/shipments/20/confirm");
  expect(api.write.mock.calls[0]?.[1].body).toMatchObject({ expected_revision: "4" });
  expect(typeof api.write.mock.calls[0]?.[1].body.operation_token).toBe("string");
});

it("rejects mismatched packing, duplicate box numbers and products outside the shipment", () => {
  const products = [{ sku_id: "1001", label: "QA Blue M", units: "5" }];
  expect(packingError(products, [{ number: "A", items: [{ sku_id: "1001", units: "6" }] }])).toMatch(/装箱合计/);
  expect(packingError(products, [{ number: "A", items: [{ sku_id: "1001", units: "2" }] }, { number: "A", items: [{ sku_id: "1001", units: "3" }] }])).toMatch(/箱号不能重复/);
  expect(packingError(products, [{ number: "A", items: [{ sku_id: "9999", units: "5" }] }])).toMatch(/不在本次出货/);
});

it("selects a product and its order inside the modal before advancing to packing", async () => {
  mount("/production/shipments/new?flow=guided");
  const dialog = await screen.findByRole("dialog", { name: "新建出货单" });
  await waitFor(() => expect(within(dialog).getByRole("button", { name: "下一步" })).toBeEnabled());
  await userEvent.type(within(dialog).getByLabelText(/^本批实际发货目的地/), "虚构验证点");
  await userEvent.click(within(dialog).getByRole("button", { name: "下一步" }));
  await userEvent.selectOptions(within(dialog).getByRole("combobox", { name: "出货SKU 1" }), "1001");
  expect(within(dialog).getByRole("combobox", { name: "出货SKU 1" })).toHaveValue("1001");
  await userEvent.type(within(dialog).getByLabelText(/^本次实际数量 1/), "1");
  await userEvent.click(within(dialog).getByRole("button", { name: "添加订单分配" }));
  await userEvent.click(within(dialog).getByRole("button", { name: /来源 1 的订单分配 1/ }));
  const picker = await screen.findByRole("dialog", { name: "选择已确认订单明细" });
  await userEvent.click(await within(picker).findByRole("button", { name: /虚构生产单A/ }));
  await userEvent.click(within(dialog).getByRole("button", { name: "下一步" }));
  expect(within(dialog).getByRole("heading", { name: "完成装箱" })).toBeInTheDocument();
  expect(within(dialog).getByLabelText("第1箱QA装箱数")).toHaveValue("");
  expect(api.write).not.toHaveBeenCalled();
});

it("retains cartons in a confirmed-shipment correction and requires a correction reason", async () => {
  const original = api.read.getMockImplementation()!;
  api.read.mockImplementation(path => path === "/api/production/shipments/20" ? Promise.resolve({ ...draft, status: "CONFIRMED" }) : original(path));
  mount("/production/shipments/20/edit");
  const dialog = await screen.findByRole("dialog", { name: "出货装箱" });
  for (let index = 0; index < 3; index++) await userEvent.click(within(dialog).getByRole("button", { name: "下一步" }));
  await userEvent.click(within(dialog).getByRole("button", { name: "确认保存出货更正" }));
  expect(api.write).not.toHaveBeenCalled();
  expect(within(dialog).getByRole("heading", { name: "核对更正" })).toBeInTheDocument();
  expect(within(dialog).queryByRole("button", { name: "保存草稿修改" })).not.toBeInTheDocument();
  await userEvent.type(within(dialog).getByLabelText(/^更正原因/), "虚构资料核对");
  await userEvent.click(within(dialog).getByRole("button", { name: "确认保存出货更正" }));
  await waitFor(() => expect(api.write).toHaveBeenCalled());
  expect(api.write.mock.calls[0]?.[0]).toBe("/api/production/shipments/20/correct");
  expect(api.write.mock.calls[0]?.[1].body).toMatchObject({ expected_revision: "4", reason: "虚构资料核对", destination: "虚构海外仓", cartons: draft.cartons });
});

function warehouseStock() { const original=api.read.getMockImplementation()!; api.read.mockImplementation(path=>path==="/api/production/inventory/availability" ? Promise.resolve({writes_enabled:true,scopes:[{warehouse_id:"900",owner_id:"1",warehouse_name:"广州成品仓",owner_name:"自有",warehouse_type:"OWN",warehouse_status:"ACTIVE"},{warehouse_id:"901",owner_id:"1",warehouse_name:"美国FBA",warehouse_type:"FBA",warehouse_status:"ACTIVE"}],items:[{warehouse_id:"900",owner_id:"1",sku_id:"1001",state:"ready",free_available_units:"40"}]}) : original(path)); }
it("starts ordinary shipment from warehouse inventory without loading or selecting a production order",async()=>{
  destinationDirectory();const router=mount("/production/shipments/intake");
  const dialog=await screen.findByRole("dialog",{name:"新建仓库出货"});
  await screen.findByRole("option",{name:"广州成品仓"});
  expect(router.state.location.search).toContain("purpose=WAREHOUSE_DISPATCH");
  expect(within(dialog).queryByRole("combobox",{name:"关联生产单"})).not.toBeInTheDocument();
  expect(within(within(dialog).getByLabelText(/^来源仓库/)).queryByRole("option",{name:"美国FBA"})).not.toBeInTheDocument();
  expect(api.read.mock.calls.some(([path])=>path.startsWith("/api/production/orders"))).toBe(false);
  await userEvent.selectOptions(within(dialog).getByLabelText(/^来源仓库/),"900:1");
  await waitFor(()=>expect(within(dialog).getByLabelText(/^本批实际发货目的地/)).toHaveValue("美国FBA"));
  await userEvent.click(within(dialog).getByRole("button",{name:"下一步"}));
  await userEvent.selectOptions(within(dialog).getByLabelText("出货SKU 1"),"1001");
  await userEvent.type(within(dialog).getByLabelText(/^本次实际数量 1/),"4");
  expect(within(dialog).queryByRole("button",{name:"添加订单分配"})).not.toBeInTheDocument();
  await userEvent.click(within(dialog).getByRole("button",{name:"下一步"}));
  expect(within(dialog).queryByLabelText("第1箱箱号")).not.toBeInTheDocument();
  await userEvent.click(within(dialog).getByText("补充资料（选填）"));
  await userEvent.type(within(dialog).getByLabelText("人工来源及区别说明"),"SIMULATED warehouse dispatch");
  await userEvent.click(within(dialog).getByRole("button",{name:"保存草稿"}));
  await waitFor(()=>expect(api.write).toHaveBeenCalledTimes(1));
  expect(api.write.mock.calls[0]![1].body).toMatchObject({save_mode:"draft",dispatch_purpose:"WAREHOUSE_DISPATCH",destination:"美国FBA",destination_id:"901",destination_type:"WAREHOUSE",warehouse_id:"900",owner_id:"1",sources:[{sku_id:"1001",fulfillment_mode:"WAREHOUSE_STOCK",actual_units:"4",allocations:[]}],cartons:null});
});
it("opens a modal leave prompt for warehouse shipment input and requires explicit abandon",async()=>{
  warehouseStock();const router=mount("/production/shipments/intake");
  await screen.findByRole("dialog",{name:"新建仓库出货"});
  const input=screen.getByLabelText(/^本批实际发货目的地/);fireEvent.change(input,{target:{value:"未保存地点"}});
  await act(()=>router.navigate("/production/orders"));
  const prompt=await screen.findByRole("dialog",{name:"还有未保存的内容"});
  expect(within(prompt).getByText("离开后，本页尚未保存的输入将被放弃。")).toBeVisible();
  await userEvent.click(within(prompt).getByRole("button",{name:"继续填写"}));expect(input).toHaveValue("未保存地点");
  expect(router.state.location.pathname).toBe("/production/shipments/new");
  await userEvent.click(screen.getByRole("button",{name:"关闭新建仓库出货"}));
  await userEvent.keyboard("{Escape}");
  await waitFor(()=>expect(screen.queryByRole("dialog",{name:"还有未保存的内容"})).not.toBeInTheDocument());
  expect(input).toHaveValue("未保存地点");
  await userEvent.click(screen.getByRole("button",{name:"关闭新建仓库出货"}));
  await userEvent.click(within(await screen.findByRole("dialog",{name:"还有未保存的内容"})).getByRole("button",{name:"放弃并离开"}));
  await waitFor(()=>expect(router.state.location.pathname).toBe("/production/shipments"));
  expect(api.write).not.toHaveBeenCalled();
});
it("recovers a failed source inventory read and never substitutes a default warehouse",async()=>{
  const original=api.read.getMockImplementation()!;let fail=true;
  api.read.mockImplementation(path=>path==="/api/production/inventory/availability"&&fail?Promise.reject(new Error("库存暂不可读")):original(path));
  mount("/production/shipments/intake");
  expect(await screen.findByText("库存暂不可读")).toBeInTheDocument();
  expect(screen.getByLabelText(/^来源仓库/)).toHaveValue("");
  fail=false;warehouseStock();await userEvent.click(screen.getByRole("button",{name:"重新读取来源库存"}));
  await screen.findByRole("option",{name:"广州成品仓"});expect(api.write).not.toHaveBeenCalled();
});

it("shows an independent warehouse batch without a misleading order-allocation requirement",async()=>{
 warehouseStock();const original=api.read.getMockImplementation()!;
 api.read.mockImplementation(path=>path==="/api/production/shipments/20"?Promise.resolve({...draft,dispatch_purpose:"WAREHOUSE_DISPATCH",sources:[{...draft.sources![0]!,sku_label:"QA Blue M",actual_units:"5",allocations:[]}]}):path.startsWith("/api/production/inventory/availability?")&&!path.includes("sku_id=")?Promise.resolve({scopes:[{warehouse_name:"广州成品仓"}]}):original(path));
 mount("/production/shipments/20");expect(await screen.findByRole("table",{name:"本批商品数量"})).toHaveTextContent("QA");
 expect(await screen.findByText(/来源仓库：广州成品仓/)).toBeInTheDocument();expect(screen.queryByRole("columnheader",{name:"系统订单"})).not.toBeInTheDocument();
 expect(screen.queryByText("未分配，确认前需要完成订单归属。")).not.toBeInTheDocument();expect(api.write).not.toHaveBeenCalled();
});

const destinationFba={id:"901",name:"美国FBA",type:"FBA",status:"ACTIVE"};
const destinationOverseas={id:"902",name:"海外仓A",type:"THIRD_PARTY",status:"ACTIVE"};
function destinationDirectory(fbaItems=[destinationFba]) {
 warehouseStock();const original=api.read.getMockImplementation()!;
 api.read.mockImplementation(path=>path==="/api/production/workbench"?Promise.resolve({version:1,directory_supported:true}):path.includes("/warehouses?")?Promise.resolve({items:path.includes("type=FBA")?fbaItems:[destinationOverseas],total:path.includes("type=FBA")?fbaItems.length:51,page:1,page_size:50}):original(path));
}
it("defaults only a new warehouse dispatch to the unique active FBA and does not dirty an untouched form",async()=>{
 destinationDirectory();const router=mount("/production/shipments/new?flow=guided&purpose=WAREHOUSE_DISPATCH");
 const field=await screen.findByLabelText("选择收货仓或地点");await waitFor(()=>expect(field).toHaveValue("901"));expect(screen.getByLabelText(/^本批实际发货目的地/)).toHaveValue("美国FBA");expect(screen.getByLabelText(/^来源仓库/)).toHaveValue("");expect(screen.getByLabelText(/^本批实际发货目的地/)).not.toBeVisible();expect(screen.getByRole("searchbox",{name:"查找收货仓或地点",hidden:true})).not.toBeVisible();await userEvent.click(screen.getByText("查找或管理地点"));expect(screen.getByRole("searchbox",{name:"查找收货仓或地点"})).toBeVisible();expect(screen.getByRole("link",{name:"管理仓库及地点"})).toBeVisible();
 await userEvent.click(screen.getByRole("button",{name:"关闭新建仓库出货"}));await waitFor(()=>expect(router.state.location.pathname).toBe("/production/shipments"));expect(screen.queryByText("还有未保存的内容")).not.toBeInTheDocument();expect(api.write).not.toHaveBeenCalled();
});
it("lets the user replace or clear the default FBA destination",async()=>{
 destinationDirectory();mount("/production/shipments/new?flow=guided&purpose=WAREHOUSE_DISPATCH");const field=await screen.findByLabelText("选择收货仓或地点");await waitFor(()=>expect(field).toHaveValue("901"));
 await userEvent.selectOptions(field,"902");expect(screen.getByLabelText(/^本批实际发货目的地/)).toHaveValue("海外仓A");await userEvent.selectOptions(field,"");await userEvent.type(screen.getByLabelText(/^本批实际发货目的地/),"本次其他地点");expect(field).toHaveValue("");expect(screen.getByLabelText(/^本批实际发货目的地/)).toHaveValue("本次其他地点");expect(api.write).not.toHaveBeenCalled();
});
it("does not overwrite a manual destination when the FBA directory arrives late",async()=>{
 destinationDirectory();const original=api.read.getMockImplementation()!;let resolve:(value:unknown)=>void=()=>undefined;const pending=new Promise(ready=>{resolve=ready;});api.read.mockImplementation(path=>path.includes("type=FBA")?pending:original(path));
 mount("/production/shipments/new?flow=guided&purpose=WAREHOUSE_DISPATCH");const field=await screen.findByLabelText("选择收货仓或地点");await screen.findByRole("option",{name:"海外仓A"});await userEvent.selectOptions(field,"902");
 await act(async()=>{resolve({items:[destinationFba],total:1,page:1,page_size:50});await pending;});expect(field).toHaveValue("902");expect(screen.getByLabelText(/^本批实际发货目的地/)).toHaveValue("海外仓A");
});
it.each([{candidates:[]},{candidates:[destinationFba,{...destinationFba,id:"903",name:"美国FBA二号"}]},{candidates:[{...destinationFba,status:"INACTIVE"}]}])("does not guess a destination for an absent, ambiguous or inactive FBA directory: %j",async ({candidates})=>{
 destinationDirectory(candidates);mount("/production/shipments/new?flow=guided&purpose=WAREHOUSE_DISPATCH");const field=await screen.findByLabelText("选择收货仓或地点");await screen.findByRole("option",{name:"海外仓A"});expect(field).toHaveValue("");expect(screen.getByLabelText(/^本批实际发货目的地/)).toHaveValue("");expect(api.write).not.toHaveBeenCalled();
});
it("retries a failed FBA directory without dropping a manually selected destination",async()=>{
 destinationDirectory();const original=api.read.getMockImplementation()!;let fail=true;api.read.mockImplementation(path=>path.includes("type=FBA")&&fail?Promise.reject(new Error("FBA目录读取失败")):original(path));mount("/production/shipments/new?flow=guided&purpose=WAREHOUSE_DISPATCH");
 await screen.findByText("FBA目录读取失败");const field=screen.getByLabelText("选择收货仓或地点");await userEvent.selectOptions(field,"902");fail=false;await userEvent.click(screen.getByRole("button",{name:"重新读取FBA仓库"}));await screen.findByRole("option",{name:"美国FBA"});expect(field).toHaveValue("902");
});
it("keeps the saved warehouse-dispatch destination instead of applying the new default",async()=>{
 destinationDirectory();const original=api.read.getMockImplementation()!;api.read.mockImplementation(path=>path==="/api/production/shipments/20"?Promise.resolve({...draft,dispatch_purpose:"WAREHOUSE_DISPATCH",destination:"海外仓A",destination_id:"902",destination_type:"WAREHOUSE"}):original(path));mount("/production/shipments/20/edit?flow=guided");
 expect(await screen.findByLabelText("选择收货仓或地点")).toHaveValue("902");expect(screen.getByLabelText(/^本批实际发货目的地/)).toHaveValue("海外仓A");expect(api.read.mock.calls.some(([path])=>path.includes("type=FBA"))).toBe(false);expect(api.write).not.toHaveBeenCalled();
});

it("imports batch goods without a packing step while retaining scope destination and plans",async()=>{
 destinationDirectory();const router=mount("/production/shipments/intake?method=table&warehouse_id=900&owner_id=1&plan_id=91&sku_id=1001");const dialog=await screen.findByRole("dialog",{name:"新建仓库出货"});await waitFor(()=>expect(within(dialog).getByLabelText(/^本批实际发货目的地/)).toHaveValue("美国FBA"));await userEvent.click(within(dialog).getByText("单号与备注（选填）"));await userEvent.type(within(dialog).getByLabelText(/^业务单号/),"SIM-TABLE");await userEvent.click(within(dialog).getByRole("button",{name:"下一步"}));
 expect(router.state.location.search).toContain("warehouse_id=900");expect(within(dialog).getByRole("link",{name:"下载出货模板"})).toHaveAttribute("href","/api/production/shipments/table/template?warehouse_id=900&owner_id=1");
 const preview={kind:"packing",warehouse_id:"900",owner_id:"1",order_id:"",order_revision:"",filename:"dispatch.xlsx",source_digest:"a".repeat(64),source_id:"upload-shipments-"+"a".repeat(64),rows:[{row:2,sku_id:"1001",order_line_id:"",units:"2"}],cartons:[{number:"TABLE-C1",items:[{sku_id:"1001",units:"2"}]}],box_count:1,total_units:"2",issues:[]};api.write.mockResolvedValueOnce(preview);
 await userEvent.upload(within(dialog).getByLabelText(/本次导入的XLSX文件/),new File(["fixture"],"dispatch.xlsx"));expect(await within(dialog).findByLabelText(/^本次实际数量 1/)).toHaveValue("2");expect(api.write).toHaveBeenCalledTimes(1);expect(api.write.mock.calls[0]?.[0]).toContain("/shipments/table/preview");expect(within(dialog).queryByRole("button",{name:"手工填写"})).not.toBeInTheDocument();expect(within(dialog).getByRole("region",{name:"仓库出货表格导入"})).toBeInTheDocument();
 expect(within(dialog).getByLabelText(/^本次实际数量 1/)).toHaveValue("2");await userEvent.click(within(dialog).getByRole("button",{name:"下一步"}));expect(within(dialog).getByRole("heading",{name:"本批出货核对"})).toBeVisible();expect(within(dialog).queryByLabelText("第1箱箱号")).not.toBeInTheDocument();await userEvent.click(within(dialog).getByRole("button",{name:"保存草稿"}));await waitFor(()=>expect(api.write).toHaveBeenCalledTimes(3));expect(api.write.mock.calls[2]?.[1].body).toMatchObject({business_number:"SIM-TABLE",warehouse_id:"900",owner_id:"1",destination:"美国FBA",dispatch_purpose:"WAREHOUSE_DISPATCH",sources:[{sku_id:"1001",plan_id:"91",actual_units:"2",allocations:[]}],cartons:null});expect(api.write.mock.calls[2]?.[1].body.manual_source_note).toContain(preview.source_id);expect(api.write.mock.calls[2]?.[1].body.manual_source_note).toContain("出货校对=dispatch-review-");
});


it("preserves warehouse, owner and arrangement context from the ordinary shipment intake", async () => {
  const router=mount("/production/shipments/intake?warehouse_id=900&owner_id=1&plan_id=91&sku_id=1001");
  await screen.findByRole("dialog",{name:"新建仓库出货"});
  expect(router.state.location.pathname).toBe("/production/shipments/new");
  const query=new URLSearchParams(router.state.location.search);
  expect(Object.fromEntries(query)).toMatchObject({warehouse_id:"900",owner_id:"1",plan_id:"91",sku_id:"1001",flow:"guided",purpose:"WAREHOUSE_DISPATCH"});
});


it("restores a saved batch goods draft into a three-step review without requiring cartons",async()=>{
 warehouseStock();const original=api.read.getMockImplementation()!;
 api.read.mockImplementation(path=>path==="/api/production/shipments/20"?Promise.resolve({...draft,dispatch_purpose:"WAREHOUSE_DISPATCH",cartons:null,sources:[{...draft.sources![0]!,allocations:[],actual_units:"5"}]}):original(path));
 mount("/production/shipments/20/edit");const dialog=await screen.findByRole("dialog",{name:"仓库出货明细"});
 await waitFor(()=>expect(within(dialog).getByLabelText(/^来源仓库/)).toHaveValue("900:1"));
 await userEvent.click(within(dialog).getByRole("button",{name:"下一步"}));
 await userEvent.click(within(dialog).getByRole("button",{name:"下一步"}));
 expect(within(dialog).getByRole("heading",{name:"本批出货核对"})).toBeVisible();
 expect(within(dialog).getByRole("button",{name:"核对并确认本出货草稿"})).toBeEnabled();
 expect(within(dialog).queryByRole("heading",{name:"装箱明细"})).not.toBeInTheDocument();
 expect(api.write).not.toHaveBeenCalled();
});


it.each(["取消", "关闭新建仓库出货"])("returns to the original warehouse on %s without creating a shipment", async label => {
  const back = "/production/warehouses/900?tab=records&mode=ship&owner=1";
  const router = mount(`/production/shipments/new?flow=guided&purpose=WAREHOUSE_DISPATCH&warehouse_id=900&owner_id=1&return_to=${encodeURIComponent(back)}`);
  await userEvent.click(await screen.findByRole("button", { name: label }));
  await waitFor(() => expect(router.state.location.pathname + router.state.location.search).toBe(back));
  expect(api.write).not.toHaveBeenCalled();
});

it("opens the shared FBA arrival workflow from shipment details and returns focus on close", async () => {
  const original = api.read.getMockImplementation()!;
  api.read.mockImplementation(async path => {
    if (path === "/api/production/shipments/20") return {...draft, status: "CONFIRMED", destination_id: "901"};
    if (path.includes("destination-state?shipment_id=20")) return {bindings:[{id:"701",sku_id:"1001",source_line_id:"301",allocation_id:null,units:"3",received_units:"0"},{id:"702",sku_id:"1001",source_line_id:"302",allocation_id:null,units:"2",received_units:"0"}]};
    if (path.includes("transport-state")) return {registered:false,shipment_status:"CONFIRMED",record:null,events:[],history:[],shipment_units:"5",destination_received_units:"0"};
    if (path === "/api/production/warehouses/901") return {id:"901",name:"虚构FBA",type:"FBA",status:"ACTIVE",scopes:[{warehouse_id:"901",owner_id:"1"}]};
    if (path.includes("/fba/state")) return {enabled:true,initialized:true,scopes:[{id:"8",warehouse_id:"901",owner_id:"1"}],references:[],batches:[],events:[],identities:[{scope_id:"8",sku_id:"1001",tracked:true}],actions:[],history:[],stock:{items:[]}};
    return original(path);
  });
  mount("/production/shipments/20");
  const trigger = await screen.findByRole("button", {name:"核对本批到仓入库"});
  await userEvent.click(trigger);
  await screen.findByLabelText("FBA收货表");
  expect(screen.getAllByRole("dialog")).toHaveLength(1);
  expect(screen.queryByRole("table", {name:"本次实收明细"})).not.toBeInTheDocument();
  await userEvent.click(screen.getByRole("button", {name:"关闭收货入库"}));
  await waitFor(() => expect(trigger).toHaveFocus());
  expect(api.write).not.toHaveBeenCalled();
});

it("keeps the warehouse or overview return context through saving, draft review and shipment details",async()=>{
 const back="/production/overview?chain_progress=all&trace_kind=order&trace_id=10&trace_stage=receipt";
 destinationDirectory();
 const original=api.read.getMockImplementation()!;api.read.mockImplementation(path=>path.includes("availability?")?Promise.resolve({scopes:[{warehouse_id:"900",owner_id:"1",warehouse_name:"虚构仓900"}],items:[]}):path.includes("transport-state")?Promise.resolve({registered:false,events:[],history:[],shipment_status:"DRAFT",shipment_units:"5",destination_received_units:"0"}):path==="/api/production/shipments/20"?Promise.resolve({...draft,dispatch_purpose:"WAREHOUSE_DISPATCH",cartons:null,sources:[{...draft.sources![0]!,allocations:[]}]}):original(path));
 const router=mount(`/production/shipments/20?return_to=${encodeURIComponent(back)}`);
 const link=await screen.findByRole("link",{name:"返回业务总览"});expect(link).toHaveAttribute("href",back);
 const review=screen.getByRole("link",{name:"核对并确认出货"});expect(review).toHaveAttribute("href",`/production/shipments/20/edit?${new URLSearchParams({return_to:back})}`);
 await userEvent.click(link);await waitFor(()=>expect(router.state.location.pathname+router.state.location.search).toBe(back));expect(api.write).not.toHaveBeenCalled();
});

async function openEditableDispatch(allowed:string|null) {
 destinationDirectory();const original=api.read.getMockImplementation()!;
 api.read.mockImplementation(path=>path.includes("inventory/availability?")?Promise.resolve({state:"ready",on_hand_units:"2",free_available_units:allowed,dispatch_allowed_units:allowed,qualified_units:"2",pending_units:"0",own_reserved_units:"0"}):original(path));
 mount("/production/shipments/new?flow=guided&purpose=WAREHOUSE_DISPATCH&warehouse_id=900&owner_id=1");await waitFor(()=>expect(screen.getByLabelText(/^本批实际发货目的地/)).toHaveValue("美国FBA"));await userEvent.click(screen.getByRole("button",{name:"下一步"}));
 return screen.findByRole("table",{name:"本批商品出货表"});
}
it("editable dispatch grid marks shortages and keeps quantities editable before review",async()=>{
 const table=await openEditableDispatch("2");await userEvent.selectOptions(within(table).getByRole("combobox",{name:"出货SKU 1"}),"1001");await within(table).findByText("2",{exact:true});const field=within(table).getByRole("textbox",{name:"本次实际数量 1"});await userEvent.type(field,"3");await waitFor(()=>expect(field).toHaveAttribute("aria-invalid","true"));expect(within(table).getByText("不足1件")).toBeVisible();await userEvent.click(screen.getByRole("button",{name:"下一步"}));expect(screen.getByRole("heading",{name:"本批出货明细"})).toBeVisible();await waitFor(()=>expect(field).toHaveFocus());await userEvent.clear(field);await userEvent.type(field,"2");await waitFor(()=>expect(field).not.toHaveAttribute("aria-invalid","true"));expect(screen.queryByText(/^商品本批合计超过当前可发量/)).not.toBeInTheDocument();await userEvent.click(screen.getByRole("button",{name:"下一步"}));expect(screen.getByRole("heading",{name:"本批出货核对"})).toBeVisible();expect(screen.getByText("来源仓库",{selector:"dt"})).toBeVisible();expect(screen.getByText("已选1个规格 · 合计2件")).toBeVisible();expect(api.write).not.toHaveBeenCalled();
});
it("editable dispatch grid checks the combined quantity for repeated SKUs",async()=>{
 const table=await openEditableDispatch("2");await userEvent.selectOptions(within(table).getByRole("combobox",{name:"出货SKU 1"}),"1001");await userEvent.type(within(table).getByRole("textbox",{name:"本次实际数量 1"}),"1");await userEvent.click(screen.getByRole("button",{name:"添加商品"}));await userEvent.type(within(table).getByRole("textbox",{name:"本次实际数量 2"}),"2");await waitFor(()=>expect(within(table).getByRole("textbox",{name:"本次实际数量 1"})).toHaveAttribute("aria-invalid","true"));expect(within(table).getByRole("textbox",{name:"本次实际数量 2"})).toHaveAttribute("aria-invalid","true");expect(within(table).getAllByText("不足1件")).toHaveLength(2);expect(api.write).not.toHaveBeenCalled();
});
it("editable dispatch grid keeps unknown availability distinct from zero",async()=>{
 const table=await openEditableDispatch(null);await userEvent.selectOptions(within(table).getByRole("combobox",{name:"出货SKU 1"}),"1001");await userEvent.type(within(table).getByRole("textbox",{name:"本次实际数量 1"}),"1");expect(await within(table).findByText("待核",{exact:true})).toBeVisible();await userEvent.click(screen.getByRole("button",{name:"下一步"}));expect(screen.getByRole("heading",{name:"本批出货明细"})).toBeVisible();expect(api.write).not.toHaveBeenCalled();
});

it("dispatch grid locates missing quantities and marks invalid integer formats immediately",async()=>{
 const table=await openEditableDispatch("2");await userEvent.selectOptions(within(table).getByRole("combobox",{name:"出货SKU 1"}),"1001");
 await userEvent.click(screen.getByRole("button",{name:"添加商品"}));
 const first=within(table).getByRole("textbox",{name:"本次实际数量 1"});const second=within(table).getByRole("textbox",{name:"本次实际数量 2"});
 await userEvent.type(first,"1");await userEvent.click(screen.getByRole("button",{name:"下一步"}));
 await waitFor(()=>expect(second).toHaveFocus());expect(second).toHaveAttribute("aria-invalid","true");
 await userEvent.type(second,"01");expect(second).toHaveAttribute("aria-invalid","true");
 await userEvent.clear(second);await userEvent.type(second,"1");expect(second).toHaveAttribute("aria-invalid","false");
 await userEvent.click(screen.getByRole("button",{name:"下一步"}));expect(screen.getByRole("heading",{name:"本批出货核对"})).toBeVisible();expect(api.write).not.toHaveBeenCalled();
});

it("keeps imports in goods step and shows the actual warehouse before optional evidence",async()=>{
 destinationDirectory();mount("/production/shipments/new?flow=guided&purpose=WAREHOUSE_DISPATCH&warehouse_id=900&owner_id=1");
 await waitFor(()=>expect(screen.getByLabelText(/^本批实际发货目的地/)).toHaveValue("美国FBA"));
 expect(screen.queryByRole("button",{name:"表格导入"})).not.toBeInTheDocument();
 expect(screen.getByLabelText(/^业务单号/)).not.toBeVisible();
 await userEvent.click(screen.getByText("单号与备注（选填）"));await userEvent.type(screen.getByLabelText(/^业务单号/),"SIM-REVIEW");
 await userEvent.click(screen.getByRole("button",{name:"下一步"}));
 expect(screen.getByRole("link",{name:"下载出货模板"})).toBeVisible();

 await userEvent.selectOptions(screen.getByLabelText("出货SKU 1"),"1001");await userEvent.type(screen.getByLabelText("本次实际数量 1"),"2");
 await userEvent.click(screen.getByRole("button",{name:"下一步"}));
 const review=screen.getByRole("region",{name:"本批出货核对"});const table=within(review).getByRole("table",{name:"出货商品核对"});
 expect(within(table).getByRole("columnheader",{name:"来源仓库"})).toBeVisible();expect(table).not.toHaveTextContent("仓库库存出货");
 expect(within(table).getByRole("cell",{name:"广州成品仓"})).toBeVisible();
 expect(screen.getByLabelText("人工来源及区别说明")).not.toBeVisible();await userEvent.click(screen.getByText("补充资料（选填）"));expect(screen.getByLabelText("人工来源及区别说明")).toBeVisible();
 await userEvent.click(screen.getByRole("button",{name:"上一步"}));await userEvent.click(screen.getByRole("button",{name:"上一步"}));
 expect(screen.getByLabelText(/^业务单号/)).toHaveValue("SIM-REVIEW");expect(api.write).not.toHaveBeenCalled();
});

it("uses an explicit details action and keeps optional plan selection through collapse and draft save",async()=>{
 const table=await openEditableDispatch("2");await userEvent.selectOptions(within(table).getByRole("combobox",{name:"出货SKU 1"}),"1001");await userEvent.type(within(table).getByRole("textbox",{name:"本次实际数量 1"}),"1");
 const toggle=within(table).getByRole("button",{name:"查看商品1详情"});expect(toggle).toHaveTextContent("详情");expect(toggle).toHaveAttribute("aria-expanded","false");
 toggle.focus();await userEvent.keyboard("{Enter}");expect(toggle).toHaveAttribute("aria-expanded","true");
 const plan=within(table).getByLabelText("来源 1 的预计出库安排（可选）");expect(plan).not.toBeVisible();
 await userEvent.click(within(table).getByText("出库安排（可选）"));expect(plan).toBeVisible();await userEvent.selectOptions(plan,"91");
 await userEvent.click(toggle);expect(toggle).toHaveAttribute("aria-expanded","false");await userEvent.click(toggle);
 expect(within(table).getByLabelText("来源 1 的预计出库安排（可选）")).toHaveValue("91");expect(within(table).getByText("出库安排（已关联）")).toBeVisible();
 await userEvent.click(screen.getByRole("button",{name:"保存草稿"}));await waitFor(()=>expect(api.write).toHaveBeenCalledTimes(1));expect(api.write.mock.calls[0]![1].body).toMatchObject({save_mode:"draft",sources:[{sku_id:"1001",actual_units:"1",plan_id:"91"}]});
});

it("removes collapsed rows directly and preserves the remaining quantities and expanded plan",async()=>{
 const table=await openEditableDispatch("40");await userEvent.selectOptions(within(table).getByRole("combobox",{name:"出货SKU 1"}),"1001");await userEvent.type(within(table).getByRole("textbox",{name:"本次实际数量 1"}),"1");
 for(const n of [2,3]){await userEvent.click(screen.getByRole("button",{name:"添加商品"}));await userEvent.type(within(table).getByRole("textbox",{name:`本次实际数量 ${n}`}),String(n));}
 expect(within(table).getByRole("button",{name:"查看商品2详情"})).toHaveAttribute("aria-expanded","false");expect(within(table).getByRole("button",{name:"移除商品2"})).toBeVisible();
 await userEvent.click(within(table).getByRole("button",{name:"查看商品3详情"}));await userEvent.click(within(table).getByText("出库安排（可选）"));await userEvent.selectOptions(within(table).getByLabelText("来源 3 的预计出库安排（可选）"),"91");
 await userEvent.click(within(table).getByRole("button",{name:"移除商品2"}));
 expect(within(table).getByRole("textbox",{name:"本次实际数量 1"})).toHaveValue("1");expect(within(table).getByRole("textbox",{name:"本次实际数量 2"})).toHaveValue("3");expect(within(table).getByRole("button",{name:"查看商品2详情"})).toHaveAttribute("aria-expanded","true");expect(within(table).getByLabelText("来源 2 的预计出库安排（可选）")).toHaveValue("91");
 await userEvent.click(within(table).getByRole("button",{name:"移除商品1"}));expect(within(table).getByRole("textbox",{name:"本次实际数量 1"})).toHaveValue("3");expect(within(table).getByRole("button",{name:"查看商品1详情"})).toHaveAttribute("aria-expanded","true");expect(within(table).queryByRole("button",{name:/移除商品/})).not.toBeInTheDocument();expect(api.write).not.toHaveBeenCalled();
});


it("appends packing lists to the same batch while retaining manual edits and file positions", async () => {
 await openEditableDispatch("50");
 const files = ["a","b","c"].map((letter,index)=>({kind:"packing",warehouse_id:"900",owner_id:"1",source_id:"upload-shipments-"+letter.repeat(64),source_digest:letter.repeat(64),filename:`${letter}.xlsx`,source_layout:"standard",order_id:"",order_revision:"",rows:[],cartons:[],box_count:0,total_units:"2",issues:[],source_rows:[{row:2,sku_code:"QA",sku_id:"1001",units:String(index+2),source_cell:"B2"}]}));
 api.write.mockImplementation((path,options)=>{
  if(path.includes("/preview?")) return Promise.resolve(files.find(file=>path.includes(`filename=${file.filename}`)));
  if(path.endsWith("/combine")) {
   const count=(options.body.sources as unknown[]).length;
   const selected=files.slice(0,count);
   return Promise.resolve({...files[0],filename:`${count}份装箱单`,source_files:selected,source_rows:selected.map((file,index)=>({...file.source_rows[0],row:index+2,source_filename:file.filename,source_row:2}))});
  }
  return Promise.resolve(draft);
 });
 const upload=screen.getByLabelText(/本次导入的XLSX文件/);
 await userEvent.upload(upload,[new File(["a"],"a.xlsx"),new File(["b"],"b.xlsx")]);
 await waitFor(()=>expect(screen.getByRole("textbox",{name:"本次实际数量 2"})).toHaveValue("3"));
 const first=screen.getByRole("textbox",{name:"本次实际数量 1"});
 await userEvent.clear(first);await userEvent.type(first,"1");
 await userEvent.upload(upload,new File(["c"],"c.xlsx"));
 await waitFor(()=>expect(screen.getByRole("textbox",{name:"本次实际数量 3"})).toHaveValue("4"));
 expect(first).toHaveValue("1");
 await userEvent.click(screen.getByRole("button",{name:"下一步"}));
 const changes=screen.getByRole("table",{name:"原表与当前填写对照"});
 expect(changes).toHaveTextContent("a.xlsx 第2行");
 expect(changes).toHaveTextContent("QA · 2件");expect(changes).toHaveTextContent("QA · 1件");
 expect(api.write.mock.calls.filter(([path])=>path==="/api/production/shipments")).toHaveLength(0);
});

it("imports repeated SKUs into a manual draft without reusing a saved source ID",async()=>{
 warehouseStock();destinationDirectory();
 const original=api.read.getMockImplementation()!;
 api.read.mockImplementation(path=>path==="/api/production/shipments/20"?Promise.resolve({...draft,dispatch_purpose:"WAREHOUSE_DISPATCH",cartons:null,sources:[{id:"301",sku_id:"1001",actual_units:"5",fulfillment_mode:"WAREHOUSE_STOCK",allocations:[]}]}):original(path));
 mount("/production/shipments/20/edit");
 await waitFor(()=>expect(screen.getByLabelText(/^来源仓库/)).toHaveValue("900:1"));
 await userEvent.click(screen.getByRole("button",{name:"下一步"}));
 const preview={kind:"packing",warehouse_id:"900",owner_id:"1",order_id:"",order_revision:"",filename:"a.xlsx",source_id:"upload-shipments-"+"a".repeat(64),source_digest:"a".repeat(64),source_layout:"standard",rows:[],issues:[],cartons:[],source_rows:[{row:2,sku_id:"1001",sku_code:"QA",units:"2",source_cell:"B2"}]};
 const second={...preview,filename:"b.xlsx",source_id:"upload-shipments-"+"b".repeat(64)};
 api.write.mockResolvedValueOnce(preview).mockResolvedValueOnce(second).mockResolvedValueOnce({...preview,source_files:[preview,second],source_rows:[...preview.source_rows,{...preview.source_rows[0],row:3}]});
 await userEvent.upload(screen.getByLabelText(/本次导入的XLSX文件/),[new File(["a"],"a.xlsx"),new File(["b"],"b.xlsx")]);
 await waitFor(()=>expect(screen.getByRole("textbox",{name:"本次实际数量 2"})).toHaveValue("2"));
 await userEvent.click(screen.getByRole("button",{name:"保存草稿修改"}));
 await waitFor(()=>expect(api.write.mock.calls.some(([path])=>path==="/api/production/shipments/20")).toBe(true));
 const body=api.write.mock.calls.find(([path])=>path==="/api/production/shipments/20")![1].body;
 expect(body.sources).toMatchObject([{id:"301",actual_units:"2"},{actual_units:"2"}]);
 expect((body.sources as {id?:string}[])[1]?.id).toBeUndefined();
});

it("prefers outstanding warehouse order attribution and provides the genuine overage reason only for an explicit excess",async()=>{
 warehouseStock();destinationDirectory();
 const original=api.read.getMockImplementation()!;
 const fresh={...order,id:"5",business_number:"SIM-NEW-5",destination_id:"901",lines:[{...order.lines![0]!,id:"501",expected_units:"20",actual_units:"0"}]};
 const spent={...order,id:"1",business_number:"SIM-OLD-1",destination_id:"901",lines:[{...order.lines![0]!,id:"201",expected_units:"2",actual_units:"2"}]};
 api.read.mockImplementation(path=>path==="/api/production/orders/5"?Promise.resolve(fresh):path==="/api/production/orders/1"?Promise.resolve(spent):original(path));
 mount("/production/shipments/new?flow=guided&purpose=WAREHOUSE_DISPATCH&warehouse_id=900&owner_id=1&source_orders=5,1");
 await waitFor(()=>expect(screen.getByLabelText(/^本批实际发货目的地/)).toHaveValue("美国FBA"));
 await userEvent.click(screen.getByRole("button",{name:"下一步"}));await userEvent.selectOptions(screen.getByLabelText("出货SKU 1"),"1001");await userEvent.type(screen.getByLabelText("本次实际数量 1"),"12");
 await userEvent.click(screen.getByRole("button",{name:"下一步"}));
 await waitFor(()=>expect(screen.getByLabelText("商品1来源订单1")).toHaveValue("501"));
 expect(screen.queryByLabelText(/超发说明/)).not.toBeInTheDocument();expect(screen.queryByRole("option",{name:/SIM-OLD-1/})).not.toBeInTheDocument();
 await userEvent.click(screen.getByRole("button",{name:"显示已发完订单"}));await userEvent.selectOptions(screen.getByLabelText("商品1来源订单1"),"201");
 const reason=await screen.findByLabelText(/超发说明/);await userEvent.type(reason,"SIM-真实额外补发12件");
 api.write.mockImplementation(path=>Promise.resolve(path.includes("/sources/shipments/check")?{candidates:[],duplicate_document:null}:{...draft,status:"CONFIRMED"}));
 await userEvent.click(screen.getByRole("button",{name:"确认已实际发货"}));
 await waitFor(()=>expect(api.write.mock.calls.some(([path])=>path==="/api/production/shipments")).toBe(true));
 expect(api.write.mock.calls.find(([path])=>path==="/api/production/shipments")?.[1].body).toMatchObject({save_mode:"confirm",dispatch_purpose:"WAREHOUSE_DISPATCH",overage_reason:"SIM-真实额外补发12件",sources:[{sku_id:"1001",actual_units:"12",allocations:[{order_line_id:"201",units:"12"}]}]});
});

it("keeps the orders context through warehouse dispatch and cancellation",async()=>{
 warehouseStock();const back="/production/orders?factory=3&q=QA&page=2&action_order=10";
 const router=mount(`/production/shipments/intake?return_to=${encodeURIComponent(back)}`);
 await userEvent.click(await screen.findByRole("button",{name:"取消"}));
 await waitFor(()=>expect(router.state.location.pathname+router.state.location.search).toBe(back));
 expect(api.write).not.toHaveBeenCalled();
});
