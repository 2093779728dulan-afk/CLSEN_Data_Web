import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { createMemoryRouter, RouterProvider } from "react-router-dom";
import { beforeEach, expect, it, vi } from "vitest";
import type { ReactNode } from "react";
import { AuthzGenerationProvider } from "../../app/AuthzGenerationContext";
import { FbaReceipts } from "./FbaReceipts";
import type { FbaBatch, FbaScope, FbaState } from "./fbaTypes";
import type { Sku } from "./types";

function ReceiptRouter({ children, initialEntries }: { children: ReactNode; initialEntries: string[] }) {
  return <RouterProvider router={createMemoryRouter([{ path: "/", element: children }], { initialEntries })} />;
}

const api = vi.hoisted(() => ({ read: vi.fn(), write: vi.fn() }));
vi.mock("../../api/client", async original => ({ ...await original<typeof import("../../api/client")>(), requestApi: api.read, writeApi: api.write }));
beforeEach(() => {
  Object.defineProperties(HTMLDialogElement.prototype, {
    showModal: { configurable: true, value: function(this: HTMLDialogElement) { this.setAttribute("open", ""); } },
    close: { configurable: true, value: function(this: HTMLDialogElement) { this.removeAttribute("open"); } },
  });
});

it("confirms matched normal rows once and leaves correction rows visible for explicit review", async () => {
  const scope = {id:"1",warehouse_id:"3",owner_id:"1"} as FbaScope;
  const row = {source_row:2,quantity:"10",fingerprint:"SIM",occurred_at:"2026-11-04T03:00:00-08:00",identity:{sku_id:"11",tracked:true},raw:{MSKU:"1112-Black-L"},bindings:[],existing_candidates:[],same_file_candidates:[],business_date:"2026-11-04"};
  const batch: FbaBatch = {id:"7",scope_id:"1",filename:"SIM-receipts.csv",digest:"a".repeat(64),revision:"2",status:"DRAFT",rows:[row,{...row,source_row:3,quantity:"-1"}],resolved:[],issues:[],history:[],decisions:[{source_row:"2",decision:"NEW",event_key:"receipt-review:7:2",reason:"SIM explicit source",allocations:[{binding_id:"1",units:"10"}]}]};
  const data = {references:[],batches:[batch]} as unknown as FbaState;
  const catalog = [{sku_id:"11",style_code:"1112"}] as Sku[];
  api.read.mockImplementation((path:string) => Promise.resolve(path.includes("/batches/7") ? batch : {items:[]}));
  api.write.mockResolvedValue({...batch,status:"PARTIAL",revision:"3"});
  const saved=vi.fn();
  render(<AuthzGenerationProvider boundary={{principalId:1,roles:["data_manager"],siteId:1,siteConfigVersionId:1}} onRevoked={()=>undefined}><ReceiptRouter initialEntries={["/?fba_batch=7"]}><FbaReceipts data={data} scope={scope} catalog={catalog} canWrite refresh={0} reload={saved}/></ReceiptRouter></AuthzGenerationProvider>);
  const confirm=await screen.findByRole("button",{name:"确认本次入库 10 件"});
  expect(screen.getByRole("table",{name:"1112 本批接收核对"})).toBeVisible();
  await userEvent.click(confirm);
  await waitFor(()=>expect(saved).toHaveBeenCalledTimes(1));
  expect(api.write.mock.calls[0]?.[0]).toBe("/api/production/fba/commands/batch-confirm");
  expect(api.write.mock.calls[0]?.[1]).toMatchObject({body:{batch_id:"7",expected_revision:"2",source_rows:["2"]}});
});


it.each([false, true])("shows matched products immediately and blocks over-receipt across normal rows (split=%s)", async split => {
  const scope = { id: "1", warehouse_id: "3", owner_id: "1" } as FbaScope;
  const binding = { id: "8", source_line_id: "11", allocation_id: null, carton_id: "", units: "4", received_units: "2", shipment_id: "3" };
  const rows = (split ? ["2", "1"] : ["3"]).map((quantity, index) => ({ source_row: index + 2, quantity, fingerprint: `SIM-${index}`, occurred_at: "2026-11-05T04:00:00-08:00", identity: { sku_id: "11", tracked: true }, raw: { MSKU: "1112-Black-L", "Reference ID":"SIM-REF", "Event Type":"Receipts" }, bindings: [binding], existing_candidates: [], same_file_candidates: [], business_date: "2026-11-05" }));
  const batch: FbaBatch = { id: "7", scope_id: "1", filename: "SIM-over.csv", digest: "a".repeat(64), revision: "2", status: "DRAFT", rows, resolved: [], issues: [], history: [], decisions: rows.map(row => ({ source_row: String(row.source_row), decision: "NEW", event_key: `SIM-${row.source_row}`, reason: "SIM explicit source", allocations: [{ binding_id: "8", units: row.quantity }] })) };
  api.read.mockImplementation((path: string) => Promise.resolve(path.includes("/batches/7") ? batch : { items: [] }));
  api.write.mockReset();
  render(<AuthzGenerationProvider boundary={{ principalId: 1, roles: ["data_manager"], siteId: 1, siteConfigVersionId: 1 }} onRevoked={() => undefined}><ReceiptRouter initialEntries={["/?fba_batch=7"]}><FbaReceipts data={{ references: [], batches: [batch], events: [] } as unknown as FbaState} scope={scope} catalog={[{ sku_id: "11", style_code: "1112" }] as Sku[]} canWrite refresh={0} reload={() => undefined} /></ReceiptRouter></AuthzGenerationProvider>);
  expect(await screen.findByRole("table", { name: "1112 本批接收核对" })).toBeVisible();
  expect(screen.getByText("超出1件")).toBeVisible();
  expect(screen.queryByRole("button", { name: "确认本次入库 3 件" })).not.toBeInTheDocument();
  expect(screen.getByRole("button", { name: "处理异常" })).toBeEnabled();
  expect(api.write).not.toHaveBeenCalled();
  expect(screen.getByLabelText("FBA接收审核").closest("details")).toBeNull();
  expect(screen.getByLabelText("收货表记录")).not.toBeVisible();
  expect(screen.getByText("原文件与操作记录").closest("details")).not.toHaveAttribute("open");
  Element.prototype.scrollIntoView = vi.fn();
  await userEvent.click(screen.getByRole("button", { name: "处理异常" }));
  expect(screen.getByText("逐行核对与更正").closest("details")).toHaveAttribute("open");
  expect(screen.getByText("逐行核对与更正").closest("details")).toHaveFocus();
  await userEvent.click(screen.getByRole("button", { name: "更换文件" }));
  expect(screen.getByRole("region",{name:"收货表记录"})).toBeVisible();
  expect(screen.getByLabelText("FBA收货表")).toHaveFocus();
});

it("shows only the newly posted quantity in report history after linking manual receipts", async () => {
  const scope = { id: "1", warehouse_id: "3", owner_id: "1" } as FbaScope;
  const batch: FbaBatch = { id: "7", scope_id: "1", filename: "SIM-covered.csv", digest: "a".repeat(64), revision: "2", status: "POSTED", rows: [{ source_row: 2, quantity: "100", fingerprint: "SIM", occurred_at: "2026-11-05T10:00:00-08:00", business_date: "2026-11-05", raw: { MSKU: "1112-Black-L", "Reference ID":"SIM-REF", "Event Type":"Receipts" }, identity: { sku_id: "11", tracked: true }, bindings: [{ id: "8", source_line_id: "1", allocation_id: null, carton_id: "", shipment_id: "4", units: "100", received_units: "100" }], existing_candidates: [], same_file_candidates: [] }], decisions: [{ source_row: "2", decision: "NEW", quantity: "100", receipt_links: [{ event_id: "9", units: "60" }] }], resolved: [{ source_row: "2", event_id: "10", decision: "NEW", evidence: "SIM coverage", confirmed_units: "100", linked_units: "60" }], issues: [], history: [] };
  api.read.mockImplementation((path: string) => Promise.resolve(path.includes("/batches/7") ? batch : { items: [] }));
  render(<AuthzGenerationProvider boundary={{ principalId: 1, roles: ["data_manager"], siteId: 1, siteConfigVersionId: 1 }} onRevoked={() => undefined}><ReceiptRouter initialEntries={["/?fba_batch=7"]}><FbaReceipts data={{ references: [], batches: [batch], events: [] } as unknown as FbaState} scope={scope} catalog={[{ sku_id: "11", style_code: "1112" }] as Sku[]} canWrite refresh={0} reload={() => undefined} /></ReceiptRouter></AuthzGenerationProvider>);
  const table = await screen.findByRole("table", { name: "1112 本批接收核对" });
  expect(within(within(table).getAllByRole("row")[1]!).getAllByRole("cell").map(cell => cell.textContent)).toEqual(["100", "0", "已处理"]);
  await userEvent.click(screen.getByText("已入库记录", { exact: true }));
  expect(screen.getByText("本报告新增入库40件")).toBeVisible();
});

it("opens the shipment and exact saved draft from the standalone restore URL", async () => {
  const scope = { id: "1", warehouse_id: "3", owner_id: "1" } as FbaScope;
  const draft: FbaBatch = { id: "19", scope_id: "1", shipment_id: "4", source_kind: "MANUAL", status: "DRAFT", revision: "2", filename: "SIM.json", digest: "a".repeat(64), rows: [], decisions: [], resolved: [], issues: [], history: [], draft_payload: { shipment_revision: "1", business_date: "2026-11-05", reason: "SIM restored exact draft", lines: [{ line_id: "1", sku_id: "11", selected: true, quantity: "3", allocations: [{ binding_id: "8", units: "3" }] }] } };
  api.read.mockImplementation((path: string) => Promise.resolve(path.endsWith("/batches/19") ? draft : path.endsWith("/shipments/4") ? { id: "4", revision: "1", status: "CONFIRMED", destination_id: "3", owner_id: "1" } : path.includes("destination-state") ? { bindings: [{ id: "8", sku_id: "11", source_line_id: "1", units: "100", received_units: "0" }] } : { items: [{ id: "4", business_number: "SIM draft shipment" }] }));
  const router = createMemoryRouter([{ path: "/", element: <FbaReceipts data={{ references: [], batches: [draft], events: [] } as unknown as FbaState} scope={scope} catalog={[{ sku_id: "11", code: "1112-Black-L", style_code: "1112" }] as Sku[]} canWrite refresh={0} reload={() => undefined} /> }], { initialEntries: ["/?fba_draft=19"] });
  render(<AuthzGenerationProvider boundary={{ principalId: 1, roles: ["data_manager"], siteId: 1, siteConfigVersionId: 1 }} onRevoked={() => undefined}><RouterProvider router={router} /></AuthzGenerationProvider>);
  expect(await screen.findByRole("textbox", { name: "1112-Black-L第1行本次收货" })).toHaveValue("3");
  expect(screen.getByRole("combobox", { name: "接收出货批次" })).toHaveValue("4");
});

it("keeps shipment balances separate when one report contains the same SKU in two shipments",async()=>{
 const scope={id:"1",warehouse_id:"3",owner_id:"1"} as FbaScope;
 const binding={id:"8",source_line_id:"11",allocation_id:null,carton_id:"",units:"4",received_units:"2",shipment_id:"3"};
 const rows=[{source_row:2,quantity:"1",bindings:[binding]},{source_row:3,quantity:"3",bindings:[{...binding,id:"9",shipment_id:"4",units:"6",received_units:"0"}]}].map(row=>({...row,fingerprint:`SIM-${row.source_row}`,occurred_at:"2026-11-05T04:00:00-08:00",identity:{sku_id:"11",tracked:true},raw:{MSKU:"1112-Black-L"},existing_candidates:[],same_file_candidates:[],business_date:"2026-11-05"}));
 const batch:FbaBatch={id:"7",scope_id:"1",filename:"SIM-two-shipments.csv",digest:"a".repeat(64),revision:"2",status:"DRAFT",rows,resolved:[],issues:[],history:[],decisions:rows.map(row=>({source_row:String(row.source_row),decision:"NEW",event_key:`SIM-${row.source_row}`,reason:"SIM explicit allocation",allocations:[{binding_id:row.bindings[0]!.id,units:row.quantity}]}))};
 api.read.mockImplementation((path:string)=>Promise.resolve(path.includes("/batches/7")?batch:{items:[]}));
 render(<AuthzGenerationProvider boundary={{principalId:1,roles:["data_manager"],siteId:1,siteConfigVersionId:1}} onRevoked={()=>undefined}><ReceiptRouter initialEntries={["/?fba_batch=7"]}><FbaReceipts data={{references:[],batches:[batch],events:[]} as unknown as FbaState} scope={scope} catalog={[{sku_id:"11",style_code:"1112"}] as Sku[]} canWrite refresh={0} reload={()=>undefined}/></ReceiptRouter></AuthzGenerationProvider>);
 const first=await screen.findByRole("table",{name:"出货 #3 1112 本批接收核对"});
 const second=screen.getByRole("table",{name:"出货 #4 1112 本批接收核对"});
 expect(within(first).getByLabelText("1112-Black-L已入库2件，确认后3件")).toBeVisible();
 expect(within(second).getByLabelText("1112-Black-L已入库0件，确认后3件")).toBeVisible();
 expect(screen.getByText("出货 #3 · 已发4件 · 累计接收2件 · 本批待收2件")).toBeVisible();
 expect(screen.getByText("出货 #4 · 已发6件 · 累计接收0件 · 本批待收6件")).toBeVisible();
});

it("keeps report imports in the shared editable receipt table", async () => {
  const scope = { id: "1", warehouse_id: "3", owner_id: "1" } as FbaScope;
  const binding = { id: "8", sku_id: "11", source_line_id: "1", allocation_id: null, carton_id: "", units: "20", received_units: "0", shipment_id: "4" };
  const report: FbaBatch = { id: "7", scope_id: "1", filename: "SIM-import.csv", source_kind: "REPORT", status: "DRAFT", revision: "1", digest: "a".repeat(64), rows: [{ source_row: 2, quantity: "3", fingerprint: "SIM", occurred_at: "2026-11-05T10:00:00-08:00", business_date: "2026-11-05", raw: { MSKU: "1112-Black-L", "Reference ID":"SIM-REF", "Event Type":"Receipts" }, identity: { sku_id: "11", tracked: true }, bindings: [binding], same_file_candidates: [], existing_candidates: [] }], decisions: [], resolved: [], issues: [], history: [] };
  api.read.mockImplementation((path: string) => Promise.resolve(path.endsWith("/shipments/4") ? { id: "4", revision: "1", status: "CONFIRMED", destination_id: "3", owner_id: "1" } : path.includes("destination-state") ? { bindings: [binding] } : { items: [] }));
  api.write.mockResolvedValue(report);
  render(<AuthzGenerationProvider boundary={{ principalId: 1, roles: ["data_manager"], siteId: 1, siteConfigVersionId: 1 }} onRevoked={() => undefined}><ReceiptRouter initialEntries={["/"]}><FbaReceipts data={{ references: [{id:"31",scope_id:"1",shipment_id:"4",shipment_revision:"1",reference_id:"SIM-REF",evidence:"SIM"}], batches: [], events: [] } as unknown as FbaState} scope={scope} catalog={[{ sku_id: "11", code: "1112-Black-L", style_code: "1112" }] as Sku[]} shipmentId="4" canWrite refresh={0} reload={() => undefined} /></ReceiptRouter></AuthzGenerationProvider>);
  const editor = await screen.findByRole("region", { name: "统一到仓接收表" });

  await userEvent.upload(within(editor).getByLabelText("FBA收货表"), new File(["SIM"], "SIM-import.csv", { type: "text/csv" }));
  await userEvent.click(within(editor).getByRole("button", { name: "导入收货表" }));
  await userEvent.click(await screen.findByRole("button", { name: "填入收货表" }));
  const input = within(editor).getByRole("textbox", { name: "1112-Black-L第2行本次收货" });
  expect(input).toHaveValue("3");
  await userEvent.clear(input);
  await userEvent.type(input, "2");
  expect(input).toHaveValue("2");
  expect(screen.queryByLabelText("FBA接收审核")).not.toBeInTheDocument();
});


it("keeps snapshot-covered corrections and ledger returns visible without receipt actions", async () => {
  const scope = { id:"1", warehouse_id:"3", owner_id:"1" } as FbaScope;
  const base = { source_row:2, quantity:"-1", fingerprint:"SIM", occurred_at:"2026-11-05T10:00:00-08:00",
    identity:{sku_id:"11",tracked:true},raw:{MSKU:"1112-Black-L"},bindings:[],existing_candidates:[],same_file_candidates:[],business_date:"2026-11-05" };
  const batch:FbaBatch={id:"7",scope_id:"1",filename:"SIM-ledger.csv",digest:"a".repeat(64),revision:"1",status:"DRAFT",
    rows:[{...base,ledger_kind:"CORRECTION",posting_block:"SNAPSHOT_COVERED",snapshot_on:"2026-11-14"},
      {...base,source_row:3,quantity:"2",ledger_kind:"CUSTOMER_RETURN",posting_block:"REVIEW_REQUIRED"}],
    resolved:[],issues:[],history:[],decisions:[]};
  api.read.mockImplementation((path:string)=>Promise.resolve(path.includes("/batches/7") ? batch : {items:[]}));api.write.mockReset();
  render(<AuthzGenerationProvider boundary={{principalId:1,roles:["data_manager"],siteId:1,siteConfigVersionId:1}} onRevoked={()=>undefined}><ReceiptRouter initialEntries={["/?fba_batch=7"]}><FbaReceipts data={{references:[],batches:[batch],events:[]} as unknown as FbaState} scope={scope} catalog={[{sku_id:"11",style_code:"1112"}] as Sku[]} canWrite refresh={0} reload={()=>undefined}/></ReceiptRouter></AuthzGenerationProvider>);
  const table=await screen.findByRole("table",{name:"分类账核对"});
  expect(within(table).getByText("冲销更正")).toBeVisible();
  expect(within(table).getByText("-1")).toBeVisible();
  expect(within(table).getByText("客户实物退回")).toBeVisible();
  expect(within(table).getByText("快照已覆盖 · 2026-11-14")).toBeVisible();
  expect(screen.queryByRole("button",{name:"匹配本批接收来源"})).not.toBeInTheDocument();
  await userEvent.click(screen.getByText("逐行核对与更正"));
  expect(screen.getByRole("checkbox",{name:"选择原表第2行"})).toBeDisabled();
  expect(screen.getByRole("checkbox",{name:"选择原表第3行"})).toBeDisabled();
  await userEvent.click(screen.getByRole("button",{name:"选择所有未处理行"}));
  expect(screen.getByRole("button",{name:"确认所选0行接收"})).toBeDisabled();
  expect(api.write).not.toHaveBeenCalled();
});
