import { render, screen, waitFor, within, fireEvent } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";
import { beforeEach, expect, it, vi } from "vitest";
import { AuthzGenerationProvider } from "../../app/AuthzGenerationContext";
import { FbaUnifiedReceipt } from "./FbaUnifiedReceipt";
import type { FbaBatch, FbaScope, FbaState } from "./fbaTypes";
import type { Sku } from "./types";

const api = vi.hoisted(() => ({ read: vi.fn(), write: vi.fn() }));
vi.mock("../../api/client", async original => ({
  ...await original<typeof import("../../api/client")>(), requestApi: api.read, writeApi: api.write,
}));
const scope = { id: "1", warehouse_id: "3", owner_id: "1", revision: "1", simulated: true, report_source_scope_id: "1", store_evidence: "SIM store", cutoff_on: "2026-10-01" } as FbaScope;
const data = { batches: [], references: [{id:"31",scope_id:"1",shipment_id:"4",shipment_revision:"1",reference_id:"SIM-REF",evidence:"SIM"}], events: [], identities: [{ scope_id: "1", sku_id: "11", tracked: true }] } as unknown as FbaState;
const catalog = [{ sku_id: "11", code: "1112-Black-L", style_code: "1112", label: "1112 Black L" }] as Sku[];
const binding = { id: "8", sku_id: "11", source_line_id: "1", allocation_id: null, carton_id: "", units: "100", received_units: "0", shipment_id: "4" };
const shipment = { id: "4", revision: "1", status: "CONFIRMED", destination_id: "3", owner_id: "1" };
const saved = vi.fn();

function renderEditor(canWrite = true, overrides: Partial<FbaState> = {}) {
  return render(<AuthzGenerationProvider boundary={{ principalId: 1, roles: ["data_manager"], siteId: 1, siteConfigVersionId: 1 }} onRevoked={() => undefined}>
    <MemoryRouter><FbaUnifiedReceipt data={{ ...data, ...overrides }} scope={scope} catalog={catalog} shipmentId="4" refresh={0} canWrite={canWrite} saved={saved} onGuardChange={() => undefined} onReport={() => undefined} /></MemoryRouter>
  </AuthzGenerationProvider>);
}
function report(quantity = "10", received = "0"): FbaBatch {
  return {
    id: "7", revision: "1", scope_id: "1", status: "DRAFT", filename: "SIM-receipts.csv", digest: "a".repeat(64), source_kind: "REPORT", decisions: [], resolved: [], issues: [], history: [],
    rows: [{ source_row: 2, quantity, fingerprint: "SIM", occurred_at: "2026-11-05T10:00:00-08:00", business_date: "2026-11-05", raw: { "Reference ID":"SIM-REF","Event Type":"Receipts",MSKU: "1112-Black-L", "Date and Time": "2026-11-05T10:00:00-08:00" }, identity: { sku_id: "11", tracked: true }, bindings: [{ ...binding, received_units: received }], same_file_candidates: [], existing_candidates: [], receipt_candidates: received === "0" ? [] : [{ id: "9", shipment_id: "4", units: received, uncovered_units: received, business_date: "2026-11-05", evidence: "SIM manual receipt", quality: "QUALIFIED", source_kind: "MANUAL" }] }],
  };
}
beforeEach(() => {
  Element.prototype.scrollIntoView = vi.fn();
  Object.defineProperties(HTMLDialogElement.prototype, {
    showModal: { configurable: true, value: function(this: HTMLDialogElement) { this.setAttribute("open", ""); } },
    close: { configurable: true, value: function(this: HTMLDialogElement) { this.removeAttribute("open"); } },
  });
  saved.mockReset(); api.read.mockReset(); api.write.mockReset();
  api.read.mockImplementation((path: string) => Promise.resolve(path.includes("catalog-products") ? {identities:[],issues:[],store:"SIM store",catalog_version:"1:1"} : path.includes("destination-state") ? { bindings: [binding] } : shipment));
  api.write.mockImplementation((path: string, options: { body: Record<string, unknown> }) => Promise.resolve(path.endsWith("unified-save") ? {
    id: "20", revision: "1", status: "DRAFT", source_kind: "MANUAL", draft_payload: options.body.draft_payload, history: [],
  } : { id: "20", revision: "2", status: "POSTED", added_units: "60", linked_units: "0", history: [] }));
});

it("saves manual quantities with the selected shipment reference before final confirmation", async () => {
  renderEditor();
  const quantity = await screen.findByRole("textbox", { name: "1112-Black-L第1行本次收货" });
  const table = screen.getByRole("table", { name: "本批可编辑接收商品" });
  expect(table.compareDocumentPosition(screen.getByLabelText(/^收货日期/)) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
  expect(screen.getByRole("button",{name:"更多"})).toBeVisible();
  expect(screen.getByLabelText("收货时间（选填，含洛杉矶UTC偏移）")).not.toBeVisible();
  expect(screen.queryByRole("button", { name: "查看已收齐商品" })).not.toBeInTheDocument();
  await userEvent.type(quantity, "60");
  await userEvent.type(screen.getByRole("textbox", { name: /^收货依据/ }), "SIM warehouse receipt");
  await userEvent.click(screen.getByRole("button", { name: "核对收货 60 件" }));
  expect(await screen.findByRole("region", { name: "确认接收摘要" })).toBeVisible();
  expect(api.write).toHaveBeenCalledTimes(1);
  expect(api.write.mock.calls[0]![0]).toBe("/api/production/fba/commands/unified-save");
  expect(api.write.mock.calls[0]![1]).toMatchObject({ body: { shipment_id: "4", draft_payload: { lines: [{ quantity: "60", allocations: [{ binding_id: "8", units: "60" }] }] } } });
  await userEvent.click(screen.getByRole("button", { name: "确认收货 60 件" }));
  await waitFor(() => expect(saved).toHaveBeenCalledOnce());
  expect(api.write.mock.calls[1]![0]).toBe("/api/production/fba/commands/unified-confirm");
  expect(screen.getByText("已接收 60 件")).toBeVisible();
});

it("applies an imported report only after explicit conflict selection and reviews original edits", async () => {
  const source = report();
  api.write.mockImplementation((path: string, options: { body: Record<string, unknown> }) => Promise.resolve(path.includes("/uploads") ? source : { id: "20", revision: "1", status: "DRAFT", draft_payload: options.body.draft_payload, history: [] }));
  renderEditor();
  await userEvent.type(await screen.findByRole("textbox", { name: "1112-Black-L第1行本次收货" }), "3");

  await userEvent.upload(screen.getByLabelText("FBA收货表"), new File(["SIM original"], "SIM.csv", { type: "text/csv" }));
  await userEvent.click(screen.getByRole("button", { name: "导入收货表" }));
  const conflict = await screen.findByRole("checkbox", { name: /已填 3 件，报告 10 件/ });
  expect(screen.getByLabelText("1112-Black-L第1行本次收货")).toHaveValue("3");
  await userEvent.click(conflict);
  await userEvent.click(screen.getByRole("button", { name: "填入收货表" }));
  const imported = screen.getByRole("textbox", { name: "1112-Black-L第2行本次收货" });
  expect(imported).toHaveValue("10");
  await userEvent.clear(imported); await userEvent.type(imported, "8");
  await userEvent.type(screen.getByRole("textbox", { name: "第2行调整说明" }), "SIM counted eight");
  await userEvent.type(screen.getByRole("textbox", { name: /^收货依据/ }), "SIM platform receipt");
  await userEvent.click(screen.getByRole("button", { name: "核对收货 8 件" }));
  expect(await screen.findByRole("region", { name: "确认接收摘要" })).toHaveTextContent("原表 10 → 8");
  expect(screen.getByRole("region", { name: "确认接收摘要" })).toHaveTextContent("报告接收日期 2026-11-05");
  expect(source.rows[0]!.quantity).toBe("10");
  expect(api.write.mock.calls[1]![1]).toMatchObject({ body: { draft_payload: { lines: [{ batch_id: "7", source_row: "2", quantity: "8", adjustment_reason: "SIM counted eight" }] } } });
});

it("links sixty manual units and allocates only the forty new units of a hundred-unit report", async () => {
  api.read.mockImplementation((path: string) => Promise.resolve(path.includes("catalog-products") ? {identities:[],issues:[],store:"SIM store",catalog_version:"1:1"} : path.includes("destination-state") ? { bindings: [{ ...binding, received_units: "60" }] } : shipment));
  api.write.mockImplementation((path: string, options: { body: Record<string, unknown> }) => Promise.resolve(path.includes("/uploads") ? report("100", "60") : { id: "20", revision: "1", status: "DRAFT", draft_payload: options.body.draft_payload, history: [] }));
  renderEditor();
  await screen.findByRole("table", { name: "本批可编辑接收商品" });

  await userEvent.upload(screen.getByLabelText("FBA收货表"), new File(["SIM"], "SIM.csv", { type: "text/csv" }));
  await userEvent.click(screen.getByRole("button", { name: "导入收货表" }));
  await userEvent.click(await screen.findByRole("button", { name: "填入收货表" }));
  await userEvent.selectOptions(screen.getByLabelText("第2行接收关系"), "LINK");
  await userEvent.type(screen.getByRole("textbox", { name: /^收货依据/ }), "SIM report covers manual receipt");
  await userEvent.click(screen.getByRole("button", { name: "核对收货 100 件" }));
  expect(await screen.findByRole("region", { name: "确认接收摘要" })).toHaveTextContent("新增入库 40 件，关联已有接收 60 件");
  expect(api.write.mock.calls[1]![1]).toMatchObject({ body: { draft_payload: { lines: [{ quantity: "100", receipt_links: [{ event_id: "9", units: "60" }], allocations: [{ binding_id: "8", units: "40" }] }] } } });
});

it("marks quantities exceeding the remaining shipment capacity", async () => {
  renderEditor();
  const input = await screen.findByRole("textbox", { name: "1112-Black-L第1行本次收货" });
  await userEvent.type(input, "101");
  expect(input).toHaveAttribute("aria-invalid", "true");
  expect(screen.getByText("超过待收")).toBeVisible();
  expect(api.write).not.toHaveBeenCalled();
});

it("clears a previous import warning when a usable report is selected next", async () => {
  api.write.mockResolvedValue({ ...report(), resolved: [{ source_row: "2" }] });
  renderEditor();
  await userEvent.upload(await screen.findByLabelText("FBA收货表"), new File(["SIM processed"], "processed.csv", { type: "text/csv" }));
  await userEvent.click(screen.getByRole("button", { name: "导入收货表" }));
  await screen.findByText(/当前没有可填入本批的正数接收行/);
  api.write.mockResolvedValue(report());
  await userEvent.upload(screen.getByLabelText("FBA收货表"), new File(["SIM pending"], "pending.csv", { type: "text/csv" }));
  await userEvent.click(screen.getByRole("button", { name: "导入收货表" }));
  await userEvent.click(await screen.findByRole("button", { name: "填入收货表" }));
  expect(screen.getByRole("textbox", { name: "1112-Black-L第2行本次收货" })).toHaveValue("10");
  expect(screen.queryByText(/当前没有可填入本批的正数接收行/)).not.toBeInTheDocument();
});

it("keeps read-only users from writing", async () => {
  renderEditor(false);
  expect(await screen.findByRole("textbox", { name: "1112-Black-L第1行本次收货" })).toBeDisabled();
  expect(screen.getByRole("button", { name: "核对收货" })).toBeDisabled();
  expect(api.write).not.toHaveBeenCalled();
});

it("adds a separate manual line and asks for explicit quantities when a SKU has multiple events", async () => {
  renderEditor();
  await userEvent.type(await screen.findByRole("textbox", { name: "1112-Black-L第1行本次收货" }), "2");
  await userEvent.click(screen.getByRole("button",{name:"更多"}));
  await userEvent.click(screen.getByRole("menuitem",{name:"添加收货明细"}));
  await userEvent.selectOptions(screen.getByLabelText("选择收货商品"), "11");
  await userEvent.click(screen.getByRole("button", { name: "添加一行" }));
  expect(screen.getByRole("textbox", { name: "1112-Black-L第2行本次收货" })).toBeVisible();
  await userEvent.click(screen.getByRole("button", { name: /^填入待入库数$/ }));
  const dialog = screen.getByRole("dialog", { name: "覆盖已选商品数量？" });
  await userEvent.click(within(dialog).getByRole("button", { name: /^填入待入库数$/ }));
  expect(screen.getByText("同一规格有多条手工记录，请逐条填写本次数量。")).toBeVisible();
  expect(screen.getByRole("textbox", { name: "1112-Black-L第1行本次收货" })).toHaveValue("2");
});

it("restores the explicitly requested draft when another newer draft exists", async () => {
  const older: FbaBatch = { id: "19", scope_id: "1", shipment_id: "4", source_kind: "MANUAL", status: "DRAFT", revision: "2", filename: "SIM.json", digest: "a".repeat(64), rows: [], decisions: [], resolved: [], issues: [], history: [], draft_payload: { business_date: "2026-11-05", reason: "SIM older saved draft", lines: [{ line_id: "1", sku_id: "11", selected: true, quantity: "3", allocations: [{ binding_id: "8", units: "3" }] }] } };
  api.read.mockImplementation((path: string) => Promise.resolve(path.endsWith("/batches/19") ? older : path.includes("destination-state") ? { bindings: [binding] } : shipment));
  render(<AuthzGenerationProvider boundary={{ principalId: 1, roles: ["data_manager"], siteId: 1, siteConfigVersionId: 1 }} onRevoked={() => undefined}><MemoryRouter><FbaUnifiedReceipt data={{ ...data, batches: [{ ...older, id: "20" }, older] }} scope={scope} catalog={catalog} shipmentId="4" draftId="19" refresh={0} canWrite saved={saved} onGuardChange={() => undefined} onReport={() => undefined} /></MemoryRouter></AuthzGenerationProvider>);
  expect(await screen.findByRole("textbox", { name: "1112-Black-L第1行本次收货" })).toHaveValue("3");
  expect(screen.getByRole("textbox", { name: /^收货依据/ })).toHaveValue("SIM older saved draft");
});

it("previews only additional stock in the unified table", async () => {
 api.read.mockImplementation((path:string)=>Promise.resolve(path.includes("destination-state")?{bindings:[{...binding,received_units:"20"}]}:shipment));
 renderEditor();
 const quantity=await screen.findByRole("textbox",{name:"1112-Black-L第1行本次收货"});
 await userEvent.type(quantity,"10");
 expect(screen.getByLabelText("1112-Black-L已入库20件，确认后30件")).toBeVisible();
 await userEvent.clear(quantity);
 expect(screen.queryByLabelText(/确认后30件/)).not.toBeInTheDocument();
 expect(api.write).not.toHaveBeenCalled();
});


it("identifies an existing master SKU missing from FBA before attempting confirmation", async () => {
  renderEditor(true, { identities: [] });
  const quantity = await screen.findByRole("textbox", { name: "1112-Black-L第1行本次收货" });
  expect(await screen.findByText("补齐首次到货商品资料")).toBeVisible();
  expect(screen.getByRole("region", { name: "核对FBA商品资料" })).toBeVisible();
  expect(screen.queryByRole("link", { name: "接入已有商品" })).not.toBeInTheDocument();
  await userEvent.type(quantity, "4");
  await userEvent.type(screen.getByRole("textbox", { name: /^收货依据/ }), "SIM receipt");
  await userEvent.click(screen.getByRole("button", { name: "核对收货 4 件" }));
  expect(quantity).toHaveAttribute("aria-invalid", "true");
  expect(api.write).not.toHaveBeenCalled();
});

it("receives a reviewed new product without asking for another identity file", async () => {
 const original=api.read.getMockImplementation()! as (path:string)=>Promise<unknown>;
 api.read.mockImplementation((path:string)=>path.includes("catalog-products")?Promise.resolve({identities:[{sku_id:"11",seller_sku:"1112-Black-L",asin:"B000000001",fnsku:"X000000001",store:"SIM store"}],issues:[],catalog_version:"1:1"}):original(path));
 renderEditor(true,{identities:[]});
 const quantity=await screen.findByRole("textbox",{name:"1112-Black-L第1行本次收货"});
 await userEvent.type(quantity,"4");
 await userEvent.type(screen.getByRole("textbox",{name:/^收货依据/}),"SIM receipt");
 expect(screen.queryByLabelText("FBA商品资料CSV")).not.toBeInTheDocument();
 await userEvent.click(screen.getByRole("button",{name:"核对收货 4 件"}));
 expect(await screen.findByRole("region",{name:"确认接收摘要"})).toBeVisible();
 await userEvent.click(screen.getByRole("button",{name:"确认收货 4 件"}));
 await waitFor(()=>expect(saved).toHaveBeenCalledOnce());
 expect(api.write.mock.calls.map((call:unknown[])=>call[0])).toEqual(["/api/production/fba/commands/unified-save","/api/production/fba/commands/unified-confirm"]);
});

it("confirms a new product in place and keeps the entered receipt quantity", async () => {
  const original = api.write.getMockImplementation()! as (path: string, options: { body: Record<string, unknown> }) => Promise<FbaBatch>;
  api.write.mockImplementation((path: string, options: { body: Record<string, unknown> }) => {
    if (path.includes("mapping-preview")) return Promise.resolve({ identities: [{ sku_id: "11", seller_sku: "1112-Black-L", asin: "B000000001", fnsku: "X000000001", store: "SIM store" }], source_id: "a".repeat(64), report_source_scope_id: "1" });
    if (path.endsWith("extend-identities")) return Promise.resolve({ ...data, scopes: [{ ...scope, revision: "2" }] });
    return original(path, options);
  });
  renderEditor(true, { identities: [] });
  const quantity = await screen.findByRole("textbox", { name: "1112-Black-L第1行本次收货" });
  await userEvent.type(quantity, "4");
  await userEvent.type(screen.getByRole("textbox", { name: /^收货依据/ }), "SIM receipt");
  await userEvent.upload(screen.getByLabelText("FBA商品资料CSV"), new File(["SIM identity"], "SIM.csv", { type: "text/csv" }));
  await userEvent.click(screen.getByRole("button", { name: "读取商品资料" }));
  await userEvent.click(await screen.findByRole("checkbox", { name: /已核对平台资料/ }));
  await userEvent.click(screen.getByRole("button", { name: "确认并启用商品" }));
  expect(await screen.findByText("商品资料已核对并启用，可继续验收")).toBeVisible();
  expect(quantity).toHaveValue("4");
  expect(screen.getByRole("textbox", { name: /^收货依据/ })).toHaveValue("SIM receipt");
  expect(saved).not.toHaveBeenCalled();
  await userEvent.click(screen.getByRole("button", { name: "核对收货 4 件" }));
  expect(await screen.findByRole("region", { name: "确认接收摘要" })).toBeVisible();
  expect(api.write.mock.calls.map((call: unknown[]) => call[0])).toEqual([
    "/api/production/fba/mapping-preview?report_source_scope_id=1",
    "/api/production/fba/commands/extend-identities",
    "/api/production/fba/commands/unified-save",
  ]);
});

it("restores only stopped products in this shipment while retaining other enabled products", async () => {
  const identities = [{ scope_id: "1", sku_id: "11", tracked: false }, { scope_id: "1", sku_id: "12", tracked: true }, { scope_id: "1", sku_id: "13", tracked: false }];
  api.write.mockResolvedValueOnce({ ...data, scopes: [{ ...scope, revision: "2" }], identities: identities.map(identity => identity.sku_id === "11" ? { ...identity, tracked: true } : identity) });
  renderEditor(true, { identities: identities as FbaState["identities"] });
  await userEvent.type(await screen.findByRole("textbox", { name: "1112-Black-L第1行本次收货" }), "4");
  await userEvent.click(screen.getByRole("button", { name: "恢复本批商品" }));
  await screen.findByText("商品资料已核对并启用，可继续验收");
  expect(api.write.mock.calls[0]![1]).toMatchObject({ body: { scope_id: "1", expected_revision: "1", sku_ids: ["12", "11"] } });
  expect(screen.getByRole("textbox", { name: "1112-Black-L第1行本次收货" })).toHaveValue("4");
});


it("keeps a manual receipt date conflict visible through review with the source correction link", async () => {
 const original=api.read.getMockImplementation()!;
 api.read.mockImplementation((path:string)=>path==="/api/production/shipments/4"?Promise.resolve({...shipment,business_date:"2026-11-09"}):original(path) as Promise<unknown>);
 renderEditor();
 await userEvent.type(await screen.findByRole("textbox",{name:"1112-Black-L第1行本次收货"}),"10");
 fireEvent.change(screen.getByLabelText(/^收货日期/),{target:{value:"2026-10-28"}});
 await userEvent.type(screen.getByRole("textbox",{name:/^收货依据/}),"QA backfill to verify source date");
 expect(screen.getByText("收货日期早于发货日期")).toBeVisible();
 expect(screen.getByRole("link",{name:"更正出货日期"})).toHaveAttribute("href",expect.stringContaining("/production/shipments/4/edit"));
 await userEvent.click(screen.getByRole("button",{name:"核对收货 10 件"}));
 expect(await screen.findByRole("region",{name:"确认接收摘要"})).toBeVisible();
 expect(screen.getByText("收货日期早于发货日期")).toBeVisible();
 expect(api.write).toHaveBeenCalledTimes(1);
});

it("keeps a missing-reference draft but prevents acceptance",async()=>{
  renderEditor(true,{references:[]});
  await userEvent.type(await screen.findByRole("textbox",{name:"1112-Black-L第1行本次收货"}),"5");
  await userEvent.type(screen.getByRole("textbox",{name:/^收货依据/}),"SIM receipt");
  await userEvent.click(screen.getByRole("button",{name:"核对收货 5 件"}));
  expect(screen.getByText("请先填写或选择FBA货件号。")).toBeVisible();expect(api.write).not.toHaveBeenCalled();
  await userEvent.click(screen.getByRole("button",{name:"保存草稿"}));
  await waitFor(()=>expect(api.write).toHaveBeenCalledOnce());
});
it("requires an explicit choice when a shipment has multiple references",async()=>{
  renderEditor(true,{references:[...data.references,{...data.references[0]!,id:"32",reference_id:"SIM-SECOND"}]});
  const select=await screen.findByLabelText("FBA货件号");expect(select).toHaveValue("");
  await userEvent.selectOptions(select,"32");
  await userEvent.type(screen.getByRole("textbox",{name:"1112-Black-L第1行本次收货"}),"5");
  await userEvent.type(screen.getByRole("textbox",{name:/^收货依据/}),"SIM selected second");
  await userEvent.click(screen.getByRole("button",{name:"核对收货 5 件"}));
  expect(await screen.findByRole("region",{name:"确认接收摘要"})).toHaveTextContent("SIM-SECOND");
  expect(api.write.mock.calls[0]![1]).toMatchObject({body:{draft_payload:{reference_link_id:"32"}}});
});
it("retains snapshot-covered report rows without filling them as new receipts",async()=>{
  const source=report();source.rows[0]!.posting_block="SNAPSHOT_COVERED";source.rows[0]!.snapshot_on="2026-11-14";
  api.write.mockResolvedValue(source);renderEditor();
  await screen.findByRole("table",{name:"本批可编辑接收商品"});
  await userEvent.upload(screen.getByLabelText("FBA收货表"),new File(["SIM"],"SIM-covered.csv",{type:"text/csv"}));
  await userEvent.click(screen.getByRole("button",{name:"导入收货表"}));
  expect(await screen.findByText(/当前没有可填入本批的正数接收行/)).toBeVisible();
  expect(screen.queryByRole("button",{name:"填入收货表"})).not.toBeInTheDocument();
  expect(screen.getByRole("textbox",{name:"1112-Black-L第1行本次收货"})).toHaveValue("");
});

it("adds a reference inline, keeps entered quantities and clears the missing-reference error",async()=>{
  api.write.mockImplementation((path:string,options:{body:Record<string,unknown>})=>Promise.resolve(path.endsWith("/references")?{...data,references:[...data.references]}:{id:"20",revision:"1",status:"DRAFT",draft_payload:options.body.draft_payload,history:[]}));
  renderEditor(true,{references:[]});
  await userEvent.type(await screen.findByRole("textbox",{name:"1112-Black-L第1行本次收货"}),"5");
  await userEvent.type(screen.getByRole("textbox",{name:/^收货依据/}),"SIM receipt");
  await userEvent.click(screen.getByRole("button",{name:"核对收货 5 件"}));
  expect(screen.getByText("请先填写或选择FBA货件号。")).toBeVisible();
  await userEvent.type(screen.getByRole("textbox",{name:"FBA货件号"}),"SIM-REF");
  await userEvent.click(screen.getByRole("button",{name:"保存货件号"}));
  expect(await screen.findByRole("textbox",{name:"FBA货件号"})).toHaveValue("SIM-REF");
  expect(screen.getByRole("textbox",{name:"1112-Black-L第1行本次收货"})).toHaveValue("5");
  expect(screen.queryByText("请先填写或选择FBA货件号。")).not.toBeInTheDocument();
});

it("requires reselecting a corrected reference without losing a restored draft",async()=>{
 const original=api.read.getMockImplementation()!;
 const draft={id:"20",scope_id:"1",shipment_id:"4",source_kind:"MANUAL" as const,status:"DRAFT",revision:"1",draft_payload:{business_date:"2026-11-05",reason:"SIM old draft",reference_link_id:"31",reference_number:"SIM-REF",shipment_revision:"1",lines:[{line_id:"1",sku_id:"11",quantity:"5",selected:true,allocations:[{binding_id:"8",units:"5"}]}]},history:[]};
 api.read.mockImplementation((path:string)=>path.includes("/batches/20")?Promise.resolve(draft):original(path) as Promise<unknown>);
 renderEditor(true,{references:[{...data.references[0]!,reference_id:"SIM-CORRECTED"}],batches:[{...draft,filename:"SIM.json",digest:"a".repeat(64)}]});
 const select=await screen.findByRole("combobox",{name:"FBA货件号"});expect(select).toHaveValue("");
 expect(screen.getByRole("textbox",{name:"1112-Black-L第1行本次收货"})).toHaveValue("5");
 await userEvent.selectOptions(select,"31");await userEvent.click(screen.getByRole("button",{name:"核对收货 5 件"}));
 expect(await screen.findByRole("region",{name:"确认接收摘要"})).toHaveTextContent("SIM-CORRECTED");
 expect(api.write.mock.calls[0]![1]).toMatchObject({body:{draft_payload:{reference_number:"SIM-CORRECTED",reference_link_id:"31"}}});
});

it("shows a completed receipt result instead of an empty editable form",async()=>{
 const original=api.read.getMockImplementation()!;
 api.read.mockImplementation((path:string)=>path.includes("destination-state")?Promise.resolve({bindings:[{...binding,received_units:"100"}]}):original(path) as Promise<unknown>);
 renderEditor();
 expect(await screen.findByRole("heading",{name:"本批已收齐"})).toBeVisible();
 expect(screen.getByRole("table",{name:"本批验收结果"})).toHaveTextContent("1112-Black-L100100");
 expect(screen.queryByRole("table",{name:"本批可编辑接收商品"})).not.toBeInTheDocument();
 expect(screen.queryByRole("button",{name:/核对收货/})).not.toBeInTheDocument();
 expect(screen.queryByRole("textbox",{name:"收货依据"})).not.toBeInTheDocument();
 expect(screen.getByRole("textbox",{name:"FBA货件号"})).toHaveAttribute("readonly");
 expect(screen.queryByRole("alert")).not.toBeInTheDocument();expect(api.write).not.toHaveBeenCalled();
});
it("keeps a pending receipt while switching to records and back",async()=>{
 renderEditor();await userEvent.type(await screen.findByRole("textbox",{name:"1112-Black-L第1行本次收货"}),"5");
 await userEvent.click(screen.getByRole("button",{name:"接收记录"}));
 expect(screen.getByRole("table",{name:"本批已确认接收"})).toBeVisible();
 expect(screen.queryByRole("textbox",{name:"1112-Black-L第1行本次收货"})).not.toBeInTheDocument();
 await userEvent.click(screen.getByRole("button",{name:"返回验收"}));
 expect(screen.getByRole("textbox",{name:"1112-Black-L第1行本次收货"})).toHaveValue("5");expect(api.write).not.toHaveBeenCalled();
});
it("keeps late report association accessible after the shipment is fully received",async()=>{
 const original=api.read.getMockImplementation()!;
 api.read.mockImplementation((path:string)=>path.includes("destination-state")?Promise.resolve({bindings:[{...binding,received_units:"100"}]}):original(path) as Promise<unknown>);
 api.write.mockResolvedValue(report("100","100"));renderEditor();
 await screen.findByRole("heading",{name:"本批已收齐"});
 await userEvent.click(screen.getByRole("button",{name:"更多"}));await userEvent.click(screen.getByRole("menuitem",{name:"关联后续验收单"}));
 expect(screen.getByLabelText("FBA收货表")).toBeVisible();expect(screen.queryByRole("button",{name:/核对收货/})).not.toBeInTheDocument();
 await userEvent.upload(screen.getByLabelText("FBA收货表"),new File(["SIM"],"SIM-late.csv",{type:"text/csv"}));
 await userEvent.click(screen.getByRole("button",{name:"导入收货表"}));await userEvent.click(await screen.findByRole("button",{name:"填入收货表"}));
 expect(screen.getByRole("textbox",{name:"1112-Black-L第2行本次收货"})).toHaveValue("100");
 await userEvent.selectOptions(screen.getByLabelText("第2行接收关系"),"LINK");expect(within(screen.getByRole("table",{name:"本批可编辑接收商品"}).querySelector("tfoot")!).getByText("新增 0")).toBeVisible();
});
it("clears a prior success before showing a new validation error",async()=>{
 renderEditor();const input=await screen.findByRole("textbox",{name:"1112-Black-L第1行本次收货"});await userEvent.type(input,"60");
 await userEvent.type(screen.getByRole("textbox",{name:/^收货依据/}),"SIM receipt");await userEvent.click(screen.getByRole("button",{name:"核对收货 60 件"}));
 await userEvent.click(await screen.findByRole("button",{name:"确认收货 60 件"}));expect(await screen.findByText("已接收 60 件")).toBeVisible();
 await userEvent.type(screen.getByRole("textbox",{name:"1112-Black-L第1行本次收货"}),"5");await userEvent.click(screen.getByRole("button",{name:"核对收货 5 件"}));
 expect(screen.getByRole("alert")).toHaveTextContent("请填写收货日期与收货依据");expect(screen.queryByText("已接收 60 件")).not.toBeInTheDocument();
});

it("keeps receipt records accessible to a read-only account",async()=>{
 renderEditor(false);await screen.findByRole("table",{name:"本批可编辑接收商品"});
 await userEvent.click(screen.getByRole("button",{name:"接收记录"}));
 expect(screen.getByRole("table",{name:"本批已确认接收"})).toBeVisible();
 expect(screen.queryByRole("menuitem",{name:"添加收货明细"})).not.toBeInTheDocument();
 expect(api.write).not.toHaveBeenCalled();
});
