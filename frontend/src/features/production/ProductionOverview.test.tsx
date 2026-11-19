import { act, fireEvent, render, screen, within, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { AuthzGenerationProvider } from "../../app/AuthzGenerationContext";
import { ProductionOverview } from "./ProductionOverview";
const api = vi.hoisted(() => ({ read: vi.fn(), write: vi.fn() }));
vi.mock("../../api/client", async importOriginal => ({ ...await importOriginal<typeof import("../../api/client")>(), requestApi: api.read, writeApi: api.write }));
const base = { notes: "", status: "CONFIRMED", revision: "1", business_date: "2025-02-01", received_units: "0" };
const one = { ...base, id: "1", system_number: "PO-1", business_number: "", factory_id: "1", factory_name: "甲厂", expected_units: "60", actual_units: "60", lines: [{ id: "11", sku_id: "1", sku_label: "款甲 M", expected_units: "60", actual_units: "60", difference_units: "0", produced_units: "55", received_units: "0" }], shipments: [{ id: "9", status: "CONFIRMED" }] };
const two = { ...base, id: "2", system_number: "PO-2", business_number: "", factory_id: "2", factory_name: "乙厂", expected_units: "40", actual_units: "40", lines: [{ id: "12", sku_id: "1", sku_label: "款甲 M", expected_units: "40", actual_units: "40", difference_units: "0", produced_units: null, received_units: "0" }], shipments: [{ id: "9", status: "CONFIRMED" }] };
const shipment = { ...base, id: "9", system_number: "SH-9", actual_units: "100", destination_id: "8", sources: [{ sku_id: "1", actual_units: "100", allocations: [{ id: "21", order_line_id: "11", units: "60" }, { id: "22", order_line_id: "12", units: "40" }] }] };
const state = { bindings: [{ allocation_id: "21", units: "60", received_units: "60", settled_units: "0" }, { allocation_id: "22", units: "40", received_units: "38", settled_units: "0" }] };
function mount(entry = "/production/overview", canWrite = false) { return render(<AuthzGenerationProvider boundary={{ principalId: 1, roles: ["viewer"], siteConfigVersionId: 1, siteId: 1 }} onRevoked={() => undefined}><MemoryRouter initialEntries={[`${entry}${entry.includes("?") ? "&" : "?"}overview_view=table`]}><ProductionOverview canWrite={canWrite} /></MemoryRouter></AuthzGenerationProvider>); }
beforeEach(() => { api.read.mockReset(); api.write.mockReset(); api.read.mockImplementation((path: string) => {
 if (path.startsWith("/api/production/inventory/transit-batches?")) return Promise.resolve({items:[],total:0,page_size:100,detail_scope:"whole_batch"});
 if (path.includes("/skus?")) return Promise.resolve({items:[]});
 if (path.startsWith("/api/production/orders?")) return Promise.resolve({ items: [one, two], total: 2, page_size: 100 });
 if (path === "/api/production/orders/1") return Promise.resolve(one); if (path === "/api/production/orders/2") return Promise.resolve(two);
 if (path.startsWith("/api/production/inventory/transport-state")) return Promise.resolve({ registered: false, record: null, events: [], status: "UNREGISTERED" });
 if (path === "/api/production/shipments/9") return Promise.resolve(shipment); if (path.startsWith("/api/production/inventory/destination-state")) return Promise.resolve(state);
 if (path.includes("factories?status=INACTIVE")) return Promise.resolve({ items: [], total: 0, page_size: 50 });
 if (path.startsWith("/api/production/factories?")) return Promise.resolve({ items: [{ id: "1", name: "甲厂" }, { id: "2", name: "乙厂" }], total: 2, page_size: 50 });
 if (path.startsWith("/api/production/warehouses?")) return Promise.resolve({ items: [{ id: "8", name: "虚构仓", status: "ACTIVE" }, { id: "9", name: "停用仓", status: "INACTIVE" }], total: 2, page_size: 50 });
 if (path === "/api/production/inventory/availability") return Promise.resolve({ scopes: [], items: [] });
 if (path === "/api/production/inventory/loans") return Promise.resolve({ items: [], limit: 200 });
 if (path.startsWith("/api/production/inventory/documents?")) return Promise.resolve({ total: 0 });
 return Promise.reject(new Error(`unexpected ${path}`)); }); });
it.each([
 {name:"new unproduced order", lines:[{produced_units:"0",received_units:"0",production_direct_units:"0"}],pending:null},
 {name:"partial receipts and direct dispatch",lines:[{produced_units:"55",received_units:"10",production_direct_units:"5"}],pending:"待入库 40 件"},
 {name:"over receipts clamped per SKU",lines:[{produced_units:"10",received_units:"0",production_direct_units:"0"},{produced_units:"0",received_units:"10",production_direct_units:"0"}],pending:"待入库 10 件"},
 {name:"unknown production",lines:[{produced_units:null,received_units:"0",production_direct_units:"0"}],pending:"待入库未登记"},
])("uses produced stock for pending receipt: $name",async testCase=>{
 const previous=api.read.getMockImplementation()!;
 api.read.mockImplementation((path:string)=>path==="/api/production/orders/1"?Promise.resolve({...one,lines:testCase.lines.map((line,index)=>({...one.lines[0],id:String(11+index),...line}))}):previous(path) as Promise<unknown>);
 mount();const row=(await screen.findByText("PO-1")).closest("tbody")!;
 if(testCase.pending)expect(within(row).getByText(testCase.pending)).toBeVisible();
 else expect(within(row).queryByText(/^待入库/)).not.toBeInTheDocument();
 expect(api.write).not.toHaveBeenCalled();
});

it("shows historical transit separately from system batches and filters by warehouse and SKU",async()=>{
 const previous=api.read.getMockImplementation()!;
 api.read.mockImplementation((path:string)=>path==="/api/production/inventory/transport-summary"?Promise.resolve({opening_scope:{warehouse_id:"8",owner_id:"1"},opening_balances:[{sku_id:"10",sku_label:"2205-White-M",units:"11",snapshot_on:"2026-11-04",source_filename:"source.csv"},{sku_id:"20",sku_label:"3104-Black-M",units:"140",snapshot_on:"2026-11-04",source_filename:"source.csv"}]}):previous(path) as Promise<unknown>);
 mount();const opening=await screen.findByRole("region",{name:"历史在途"});
 expect(within(opening).getByText("151 件")).toBeVisible();
 await userEvent.click(within(opening).getByText("历史在途"));
 expect(within(opening).getByRole("table",{name:"期初在途明细"})).toBeVisible();
 expect(within(opening).queryByRole("button",{name:/核验|确认/})).not.toBeInTheDocument();
 await userEvent.selectOptions(screen.getByRole("combobox",{name:"仓库"}),"9");
 expect(screen.queryByRole("region",{name:"历史在途"})).not.toBeInTheDocument();
 await userEvent.selectOptions(screen.getByRole("combobox",{name:"仓库"}),"8");
 expect(await screen.findByRole("region",{name:"历史在途"})).toBeVisible();
 await userEvent.type(screen.getByRole("textbox",{name:"订单号 / 款号"}),"2205");
 await userEvent.click(screen.getByRole("button",{name:"搜索"}));
 expect(within(screen.getByRole("region",{name:"历史在途"})).getByText("11 件")).toBeVisible();
 await userEvent.selectOptions(screen.getByRole("combobox",{name:"生产工厂"}),"1");
 expect(screen.queryByRole("region",{name:"历史在途"})).not.toBeInTheDocument();
 expect(api.write).not.toHaveBeenCalled();
});

describe("business overview", () => {
 it("keeps only production quantities on orders while preserving legacy shipment attribution", async () => {
  mount(); const oneCard = (await screen.findByText("PO-1")).closest("tbody")!; const twoCard = screen.getByText("PO-2").closest("tbody")!;
  expect(within(oneCard).queryByText("已出货")).not.toBeInTheDocument();
  expect(within(twoCard).queryByText(/待出 40/)).not.toBeInTheDocument();
  expect(screen.getByRole("link", {name:"查看出货批次"})).toHaveAttribute("href", "/production/shipments");
  expect(within(twoCard).getByText("未登记", {selector:"b"})).toBeInTheDocument();
  expect(within(oneCard).getByRole("progressbar", {name:"工厂生产占计划比例"})).toHaveValue(91.7);
  expect(api.read.mock.calls.filter(([path]) => path === "/api/production/shipments/9")).toHaveLength(1);
  await userEvent.click(within(twoCard).getByLabelText("展开规格与出货批次"));
  expect(within(twoCard).getByText(/历史订单分配 40 · 实收 38/)).toBeVisible();
  expect(within(twoCard).getAllByRole("columnheader").map(cell => cell.textContent)).toEqual(["商品规格","计划","生产","生产入库"]);
 });
 it("keeps each expanded trace in its own labeled panel and can close it", async () => {
  mount();
  const first = (await screen.findByText("PO-1")).closest("tbody")!;
  const second = screen.getByText("PO-2").closest("tbody")!;
  await userEvent.click(within(first).getByRole("button", { name: "展开规格与出货批次" }));
  const firstPanel = within(first).getByRole("region", { name: "PO-1规格与出货批次" });
  expect(within(firstPanel).getByRole("table")).toBeVisible();
  expect(within(first).getByRole("button", { name: "收起规格与出货批次" })).toHaveAttribute("aria-expanded", "true");
  await userEvent.click(within(second).getByRole("button", { name: "展开规格与出货批次" }));
  expect(within(second).getByRole("region", { name: "PO-2规格与出货批次" })).toBeVisible();
  await userEvent.click(within(first).getByRole("button", { name: "收起规格与出货批次" }));
  expect(within(first).queryByRole("region")).not.toBeInTheDocument();
  expect(within(second).getByRole("region")).toBeVisible();
 });
 it("shows the no-shipment state independently of the specification table", async () => {
  const previous = api.read.getMockImplementation()!;
  api.read.mockImplementation((path: string) => path === "/api/production/orders/1" ? Promise.resolve({ ...one, actual_units: "0", shipments: [] }) : path === "/api/production/shipments/9" ? Promise.resolve({ ...shipment, sources: shipment.sources.map(source => ({ ...source, allocations: source.allocations.filter(a => a.order_line_id !== "11") })) }) : previous(path) as Promise<unknown>);
  mount(); const card = (await screen.findByText("PO-1")).closest("tbody")!;
  await userEvent.click(within(card).getByRole("button", { name: "展开规格与出货批次" }));
  const panel = within(card).getByRole("region", { name: "PO-1规格与出货批次" });
  expect(within(panel).getByRole("table")).toBeVisible();
  expect(within(panel).getByText("本单暂无明确的出货关联，仓库出货请在下方“出货与到仓进度”查看。")).toBeVisible();
 });
 it("preserves multiple specification rows and the allocated shipment trace", async () => {
  const previous = api.read.getMockImplementation()!;
  api.read.mockImplementation((path: string) => path === "/api/production/orders/1" ? Promise.resolve({ ...one, expected_units: "65", lines: [...one.lines, { ...one.lines[0], id: "13", sku_id: "2", sku_label: "款乙 L", expected_units: "5", actual_units: "0", produced_units: null }] }) : previous(path) as Promise<unknown>);
  mount(); const card = (await screen.findByText("PO-1")).closest("tbody")!;
  await userEvent.click(within(card).getByRole("button", { name: "展开规格与出货批次" }));
  const panel = within(card).getByRole("region", { name: "PO-1规格与出货批次" });
  expect(within(panel).getByRole("table").querySelectorAll(":scope > tbody > tr")).toHaveLength(2);
  expect(within(panel).getByText("款甲 M")).toBeVisible();
  expect(within(panel).getByText("款乙 L")).toBeVisible();
  expect(within(panel).getByText(/历史订单分配 60 · 实收 60/)).toBeVisible();
 });
 it("preserves unknown legacy receipt totals without using them as order progress", async () => {
  const previous=api.read.getMockImplementation()!; api.read.mockImplementation((path:string)=>path.startsWith("/api/production/inventory/destination-state")?Promise.resolve({bindings:[state.bindings[0]]}):previous(path) as Promise<unknown>);
  mount(); const card=(await screen.findByText("PO-2")).closest("tbody")!;
  await userEvent.click(within(card).getByLabelText("展开规格与出货批次"));
  expect(within(card).getByText(/历史订单分配 40 · 实收 待核/)).toBeVisible();
  expect(within(card).queryByRole("progressbar",{name:"目的仓实收占计划比例"})).not.toBeInTheDocument();
 });
 it("exposes read failure and retry without fabricating zero totals", async () => { api.read.mockRejectedValueOnce(new Error("服务不可用")); mount(); expect(await screen.findByText("服务不可用")).toBeVisible(); expect(screen.queryByText("PO-1")).not.toBeInTheDocument(); await userEvent.click(screen.getByRole("button", { name: "重试" })); expect(await screen.findByText("PO-1")).toBeVisible(); });
 it.each([false, true])("shows one on-hand balance per warehouse and preserves unknown scopes: %s", async missing => {
  const previous = api.read.getMockImplementation()!;
  api.read.mockImplementation((path: string) => path === "/api/production/inventory/availability" ? Promise.resolve({ scopes: [{ warehouse_id: "8", owner_id: "1", warehouse_name: "虚构仓", owner_name: "货权甲" }, { warehouse_id: "8", owner_id: "2", warehouse_name: "虚构仓", owner_name: "货权乙" }, { warehouse_id: "8", owner_id: "3", warehouse_name: "虚构仓", owner_name: "货权丙" }].slice(0, missing ? 3 : 2), items: [{ warehouse_id: "8", owner_id: "1", sku_id: "1", on_hand_units: "30", free_available_units: "30", pending_units: "0", defective_units: "0" }, { warehouse_id: "8", owner_id: "2", sku_id: "1", on_hand_units: "7", free_available_units: null, pending_units: "0", defective_units: "0" }] }) : previous(path) as Promise<unknown>);
  mount(); await screen.findByText("PO-1");
  const table = screen.getByRole("table", { name: "仓库当前状态" });
  expect(within(table).getAllByRole("columnheader").map(c => c.textContent)).toEqual(["仓库", "在库", "操作"]);
  expect(table.querySelectorAll("tbody tr")).toHaveLength(1);
  expect(within(table).queryByText("停用仓")).not.toBeInTheDocument();
  expect(screen.getByRole("option", { name: "停用仓" })).toBeInTheDocument();
  expect(within(table).getAllByRole("cell").map(c => c.textContent)).toEqual(["虚构仓", missing ? "待核" : "37", ""]);
  expect(within(table).getByRole("link", { name: "查看仓库" })).toHaveAttribute("href", "/production/warehouses/8");
 });

 it("does not show an older site response after the site changes", async () => {
  let finish: (value: unknown) => void = () => undefined; let calls = 0; const original = api.read.getMockImplementation()!;
  api.read.mockImplementation((path: string) => { if (path.startsWith("/api/production/orders?")) { calls++; if (calls === 1) return new Promise(resolve => { finish = resolve; }); return Promise.resolve({ items: [two], total: 1, page_size: 100 }); } return original(path) as Promise<unknown>; });
  const wrap = (siteId: number) => <AuthzGenerationProvider boundary={{ principalId: 1, roles: ["viewer"], siteConfigVersionId: siteId, siteId }} onRevoked={() => undefined}><MemoryRouter initialEntries={["/production/overview?overview_view=table"]}><ProductionOverview /></MemoryRouter></AuthzGenerationProvider>;
  const view = render(wrap(1)); view.rerender(wrap(2)); expect(await screen.findByText("PO-2")).toBeVisible(); finish({ items: [one], total: 1, page_size: 100 }); expect(screen.queryByText("PO-1")).not.toBeInTheDocument();
 });

});

it("clears applied search, factory, and warehouse together while retaining both orders", async () => {
  mount("/production/overview?q=款甲&factory=1&warehouse=8");
  await screen.findByText("PO-1");
  expect(screen.queryByText("PO-2")).not.toBeInTheDocument();
  await userEvent.click(screen.getByRole("button", {name:"清空筛选"}));
  expect(await screen.findByText("PO-2")).toBeVisible();
  expect(screen.getByRole("textbox", {name:"订单号 / 款号"})).toHaveValue("");
  expect(screen.getByRole("combobox", {name:"生产工厂"})).toHaveValue("");
  expect(screen.getByRole("combobox", {name:"仓库"})).toHaveValue("");
});


it("keeps quantity-complete orders active until a human confirms, then permits manual reopening", async () => {
  const original = api.read.getMockImplementation()!;
  let current = { ...one, production_completion_ready: true, production_completion_state: "OPEN" };
  api.read.mockImplementation((path:string) => path === "/api/production/orders/1" ? Promise.resolve(current) : original(path) as Promise<unknown>);
  api.write.mockImplementation((path:string) => { current={...current,production_completion_state:path.endsWith("/complete-production") ? "COMPLETED" : "OPEN"}; return Promise.resolve(current); });
  mount("/production/overview",true);
  const card=(await screen.findByText("PO-1")).closest("tbody")!;
  expect(within(card).getByRole("button",{name:"确认完成"})).toBeVisible();
  expect(api.write).not.toHaveBeenCalled();
  await userEvent.click(within(card).getByRole("button",{name:"确认完成"}));
  await screen.findByRole("button",{name:"已完成 1"});
  expect(screen.queryByText("PO-1")).not.toBeInTheDocument();
  expect(api.write.mock.calls[0]?.[0]).toBe("/api/production/orders/1/complete-production");
  expect(api.write.mock.calls[0]?.[1]).toMatchObject({body:{expected_revision:"1"}});
  await userEvent.click(screen.getByRole("button",{name:"已完成 1"}));
  expect(await screen.findByText("PO-1")).toBeVisible();
  await userEvent.click(screen.getByRole("button",{name:"恢复进行中"}));
  await screen.findByText("还没有人工确认完成的订单。");
  await userEvent.click(screen.getByRole("button",{name:"进行中 2"}));
  expect(await screen.findByText("PO-1")).toBeVisible();
});

it("keeps an earlier human completion after a quantity correction and exposes it read-only", async () => {
  const original=api.read.getMockImplementation()!;
  api.read.mockImplementation((path:string)=>path === "/api/production/orders/1" ? Promise.resolve({...one,production_completion_state:"COMPLETED",production_completion_ready:false}) : original(path) as Promise<unknown>);
  mount("/production/overview?progress=completed");
  expect(await screen.findByText("PO-1")).toBeVisible();
  expect(screen.getByText("数量已变更")).toBeVisible();
  expect(screen.queryByText("PO-2")).not.toBeInTheDocument();
  expect(screen.queryByRole("button",{name:"确认完成"})).not.toBeInTheDocument();
  expect(screen.queryByRole("button",{name:"恢复进行中"})).not.toBeInTheDocument();
  expect(api.write).not.toHaveBeenCalled();
});

const batch = { id:"71",business_number:"独立批次-71",system_number:"SH-71",business_date:"2026-10-02",warehouse_id:"7",destination_id:"8",owner_id:"1",source_name:"广州成品仓",destination_name:"美国FBA",destination_kind:"FBA",dispatch_purpose:"WAREHOUSE_DISPATCH",shipped_units:"10",received_units:"3",unreceived_units:"7",settled_units:"0",stage:"IN_TRANSIT",eta_overdue:false,receipt_dates:[],sources:[{id:"701",sku_id:"1",sku_label:"1101-Navy-L",actual_units:"10",received_units:"3",unreceived_units:"7",allocations:[],bindings:[]}],transport:{status:"IN_TRANSIT",record:null,latest_event:{location:"上海港"},events:[]},departed:null,arrived:null };
it("shows independent shipment location and receipts even when the production orders are completed",async()=>{
 const original=api.read.getMockImplementation()!;
 api.read.mockImplementation((path:string)=>path.includes("/transit-batches?")?Promise.resolve({items:[batch],total:1,page_size:100,detail_scope:"whole_batch"}):path==="/api/production/orders/1"?Promise.resolve({...one,shipments:[],production_completion_state:"COMPLETED",receipt_warehouse_id:"8",received_units:"60"}):original(path) as Promise<unknown>);
 mount("/production/overview?progress=completed");
 const production=(await screen.findByText("PO-1")).closest("tbody")!;
 expect(within(production).getByText("虚构仓")).toBeVisible();
 const row=screen.getByRole("rowgroup",{name:"出货批次 独立批次-71"});
 expect(within(row).getByText("上海港")).toBeVisible();
 expect(within(row).getByText("运输中")).toBeVisible();
 expect(within(row).getAllByRole("cell").map(cell=>cell.textContent)).toContain("3");
 await userEvent.click(within(row).getByRole("button",{name:"展开批次 独立批次-71"}));
 const detail=within(row).getByRole("region",{name:"独立批次-71流转明细"});
 expect(within(detail).getByRole("table",{name:"独立批次-71商品进度"})).toHaveTextContent("1101-Navy-L");
 expect(within(detail).getByRole("link",{name:"查看运输记录"})).toHaveAttribute("href","/production/shipments/71#transport");
 expect(within(detail).queryByRole("button",{name:"开始到仓核验"})).not.toBeInTheDocument();
 expect(within(production).queryByText("独立批次-71")).not.toBeInTheDocument();
 expect(api.write).not.toHaveBeenCalled();
});
it("keeps production readable when whole-batch data fails or has the wrong granularity",async()=>{
 const original=api.read.getMockImplementation()!;
 api.read.mockImplementation((path:string)=>path.includes("/transit-batches?")?Promise.resolve({items:[batch],total:1,page_size:100,detail_scope:"single_sku"}):original(path) as Promise<unknown>);
 mount();expect(await screen.findByText("PO-1")).toBeVisible();
 expect(screen.getByText("出货进度读取未完成")).toBeVisible();
 expect(screen.queryByText("独立批次-71")).not.toBeInTheDocument();
});
it("retains unknown receipt quantities and all batch pages without guessing order attribution",async()=>{
 const original=api.read.getMockImplementation()!;
 api.read.mockImplementation((path:string)=>path.includes("/transit-batches?")?Promise.resolve({items:[{...batch,id:path.endsWith("page=1")?"71":"72",business_number:path.endsWith("page=1")?"独立批次-71":"独立批次-72",received_units:null,unreceived_units:null,stage:"UNREGISTERED"}],total:2,page_size:1,detail_scope:"whole_batch"}):original(path) as Promise<unknown>);
 mount();const row=await screen.findByRole("rowgroup",{name:"出货批次 独立批次-72"});
 expect(within(row).getAllByText("待核")).toHaveLength(2);
 expect(within(row).getByText("运输未登记")).toBeVisible();
 expect(screen.getByRole("rowgroup",{name:"出货批次 独立批次-71"})).toBeVisible();
 expect(api.write).not.toHaveBeenCalled();
});

it("filters batch routes and numbers without letting the production factory filter hide them",async()=>{
 const original=api.read.getMockImplementation()!;
 api.read.mockImplementation((path:string)=>path.includes("/transit-batches?")?Promise.resolve({items:[batch,{...batch,id:"72",business_number:"独立批次-72",warehouse_id:"9",destination_id:"10"}],total:2,page_size:100,detail_scope:"whole_batch"}):original(path) as Promise<unknown>);
 mount("/production/overview?progress=completed&factory=2&warehouse=8&q=独立批次");
 expect(await screen.findByRole("rowgroup",{name:"出货批次 独立批次-71"})).toBeVisible();
 expect(screen.queryByRole("rowgroup",{name:"出货批次 独立批次-72"})).not.toBeInTheDocument();
 expect(screen.getByText("还没有人工确认完成的订单。")).toBeVisible();
});
it("keeps received batches visible with receipt dates and no duplicate receiving action",async()=>{
 const original=api.read.getMockImplementation()!;
 api.read.mockImplementation((path:string)=>path.includes("/transit-batches?")?Promise.resolve({items:[{...batch,stage:"RECEIVED",received_units:"10",unreceived_units:"0",receipt_dates:["2026-10-12"]}],total:1,page_size:100,detail_scope:"whole_batch"}):original(path) as Promise<unknown>);
 mount("/production/overview",true);
 const row=await screen.findByRole("rowgroup",{name:"出货批次 独立批次-71"});
 expect(within(row).getByText("美国FBA",{selector:"span"})).toBeVisible();
 await userEvent.click(within(row).getByRole("button",{name:"展开批次 独立批次-71"}));
 expect(within(row).getByText("2026-10-12")).toBeVisible();
 expect(within(row).queryByRole("button",{name:"开始到仓核验"})).not.toBeInTheDocument();
 expect(api.write).not.toHaveBeenCalled();
});


it("keeps expanded overview mounted while revalidating after returning to the page", async () => {
  mount(); const card=(await screen.findByText("PO-1")).closest("tbody")!;
  await userEvent.click(within(card).getByRole("button",{name:"展开规格与出货批次"}));
  const panel=within(card).getByRole("region",{name:"PO-1规格与出货批次"});
  const original=api.read.getMockImplementation()!;
  let resolve!: (value:unknown)=>void;
  api.read.mockImplementation((path:string)=>path==="/api/production/orders/1"?new Promise(yes=>{resolve=yes;}):original(path) as Promise<unknown>);
  fireEvent.focus(window);
  await waitFor(()=>expect(resolve).toBeDefined());
  expect(panel).toBeVisible(); expect(screen.getByRole("button",{name:"导出概览"})).toBeDisabled();
  await act(async()=>{resolve(one);await Promise.resolve();});
  await waitFor(()=>expect(screen.getByRole("button",{name:"导出概览"})).toBeEnabled());
  expect(panel).toBeVisible();
});
