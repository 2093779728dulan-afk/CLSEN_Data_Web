import { act, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { createMemoryRouter, RouterProvider } from "react-router-dom";
import { beforeEach, expect, it, vi } from "vitest";
import { AuthzGenerationProvider } from "../../app/AuthzGenerationContext";
import { DestinationReceiptDialog } from "./DestinationReceiptDialog";
import { ArrivalVerificationWindow } from "./ArrivalVerification";
import { SkuAcrossWarehouses } from "./SkuAcrossWarehouses";
import type { TransitItem } from "./WarehouseTransit";
const api=vi.hoisted(()=>({read:vi.fn<typeof import("../../api/client").requestApi>(),write:vi.fn<typeof import("../../api/client").writeApi>()}));
vi.mock("../../api/client",async original=>({...await original<typeof import("../../api/client")>(),requestApi:api.read,writeApi:api.write}));
const scope={warehouse_id:"3",warehouse_name:"海外仓A",owner_id:"1",owner_name:"公司自有"};
const warehouse={id:"3",name:"海外仓A",status:"ACTIVE",type:"THIRD_PARTY",scopes:[scope]};
const source={id:"1",sku_id:"11",sku_label:"1112 Black L",actual_units:"4",received_units:"2",unreceived_units:"2",bindings:[],allocations:[]};
const item={id:"77",business_number:"SIM-77",system_number:"SH-77",destination_id:"3",destination_kind:"THIRD_PARTY",source_name:"广州成品仓",destination_name:"海外仓A",owner_id:"1",stage:"ARRIVAL_CHECK",sources:[source],shipped_units:"4",received_units:"2",unreceived_units:"2",settled_units:"0",receipt_dates:[],departed:null,arrived:null,duration_hours:null,transport:{record:null,events:[]}} as unknown as TransitItem;
const shipment={id:"77",revision:"5",destination_id:"3",owner_id:"1",destination:"海外仓A",business_number:"SIM-77",sources:[source],cartons:[]};
const binding={id:"7",source_line_id:"1",carton_id:"6",sku_id:"11",sku_label:"1112 Black L",catalog_version:"v1",identity_status:"active",units:"4",received_units:"2",settled_units:"0"};
let receipt:Record<string,unknown>;
beforeEach(()=>{
 Object.defineProperties(HTMLDialogElement.prototype,{showModal:{configurable:true,value:function(this:HTMLDialogElement){this.setAttribute("open","");}},close:{configurable:true,value:function(this:HTMLDialogElement){this.removeAttribute("open");}}});
 vi.stubGlobal("ResizeObserver",class{observe=vi.fn();disconnect=vi.fn();});
 const NativeRequest=globalThis.Request;vi.stubGlobal("Request",class extends NativeRequest{constructor(input:RequestInfo|URL,init?:RequestInit){const{signal,...options}=init??{};super(input,options);if(signal)Object.defineProperty(this,"signal",{value:signal});}});
 receipt={id:"50",shipment_id:"77",warehouse_id:"3",owner_id:"1",revision:"1",status:"DRAFT",business_date:"2026-10-30",reason:"QA receipt",lines:[{binding_id:"7",sku_id:"11",catalog_version:"v1",qualified_units:"1",pending_units:"0",defective_units:"0"}]};
 api.read.mockReset();api.write.mockReset();api.read.mockImplementation(async path=>{
  await Promise.resolve();
  if(path==="/api/production/warehouses/3")return warehouse;
  if(path==="/api/production/shipments/77")return shipment;
  if(path.includes("destination-state"))return{shipment:{id:"77",revision:"5",destination_id:"3"},bindings:[binding],receipts:[],settlements:[]};
  if(path.includes("destination-receipts/50"))return receipt;
  if(path.includes("availability"))return{scopes:[scope],items:[]};
  if(path.includes("/skus?"))return{items:[{sku_id:"11",style_id:"1",style_code:"1112",code:"1112-Black-L",label:"1112 Black L",standard_color:"Black",standard_size:"L"}]};
  if(path.includes("transport-summary"))return{full_scope:true,totals:{in_transit_units:"0",arrival_check_units:"2"}};
  if(path.includes("transit-batches"))return{detail_scope:"whole_batch",items:[item],page:1,page_size:5,total:1,as_of:"2026-10-30"};
  throw new Error(path);
 });
 api.write.mockImplementation(async path=>{await Promise.resolve();if(path.endsWith("/confirm"))receipt={...receipt,status:"POSTED",revision:"2"};return receipt;});
});
function mount(board=false,canWrite=true,legacy=false,completed=()=>undefined){const router=createMemoryRouter([{path:"/production/stock",element:<AuthzGenerationProvider boundary={{principalId:1,roles:[canWrite?"data_manager":"viewer"],siteId:1,siteConfigVersionId:1}} onRevoked={()=>undefined}>{legacy?<DestinationReceiptDialog shipmentId="77" warehouseId="3" ownerId="1" canWrite={canWrite} close={()=>undefined} saved={()=>undefined}/>:board?<SkuAcrossWarehouses canWrite={canWrite}/>:<ArrivalVerificationWindow item={item} canWrite={canWrite} refresh={0} saved={completed} close={()=>undefined} returnFocus={null}/>}</AuthzGenerationProvider>},{path:"/elsewhere",element:<p>Elsewhere</p>}],{initialEntries:["/production/stock"]});render(<RouterProvider router={router}/>);return router;}
async function fill(){await screen.findByLabelText("7 qualified_units");await userEvent.clear(screen.getByLabelText("7 qualified_units"));await userEvent.type(screen.getByLabelText("7 qualified_units"),"1");await userEvent.type(screen.getByLabelText("实际接收日期"),"2026-10-30");await userEvent.type(screen.getByLabelText("依据与差异说明"),"QA receipt");}
it("starts the selected batch in one window without leaving the overview or choosing its source again",async()=>{
 const router=mount(true);await userEvent.click(await screen.findByRole("button",{name:"开始到仓核验 SIM-77"}));await screen.findByLabelText("7 qualified_units");expect(router.state.location.pathname).toBe("/production/stock");expect(screen.getAllByRole("dialog")).toHaveLength(1);expect(screen.getByLabelText("实际接收日期")).toBeVisible();expect(screen.getByText(/本次接收：海外仓A/)).toBeVisible();expect(screen.queryByRole("combobox",{name:"目的仓及货权"})).not.toBeInTheDocument();expect(screen.queryByRole("button",{name:"下一步"})).not.toBeInTheDocument();expect(screen.queryByRole("button",{name:/刷新/})).not.toBeInTheDocument();expect(api.write).not.toHaveBeenCalled();
});
it("retains explicit draft and final confirmation with the exact original binding and revision",async()=>{
 mount();await fill();expect(screen.getByRole("button",{name:"确认目的仓入库"})).toBeDisabled();await userEvent.click(screen.getByRole("button",{name:"保存核验草稿"}));await waitFor(()=>expect(api.write).toHaveBeenCalledTimes(1));expect(api.write.mock.calls[0]![0]).toBe("/api/production/inventory/destination-receipts");expect(api.write.mock.calls[0]![1]?.body).toMatchObject({shipment_id:"77",expected_shipment_revision:"5",warehouse_id:"3",owner_id:"1",lines:[{binding_id:"7",sku_id:"11",catalog_version:"v1",qualified_units:"1"}]});await waitFor(()=>expect(screen.getByRole("button",{name:"确认目的仓入库"})).toBeEnabled());await userEvent.click(screen.getByRole("button",{name:"确认目的仓入库"}));await waitFor(()=>expect(api.write).toHaveBeenCalledTimes(2));expect(api.write.mock.calls[1]![0]).toBe("/api/production/inventory/destination-receipts/50/confirm");expect(api.write.mock.calls[1]![1]?.body).toMatchObject({expected_revision:"1"});
});
it("keeps unsaved input in the same window when closing and when navigating away",async()=>{
 const router=mount();await fill();await userEvent.click(screen.getByRole("button",{name:"关闭收货入库"}));expect(await screen.findByText("还有未保存的核验内容")).toBeVisible();expect(screen.getByRole("dialog",{name:"还有未保存的核验内容"})).toBeVisible();expect(screen.getByLabelText("依据与差异说明")).toHaveValue("QA receipt");expect(screen.getByRole("dialog",{name:"还有未保存的核验内容"}).closest("dialog")).not.toBeNull();await userEvent.click(screen.getByRole("button",{name:"继续核验"}));expect(screen.getByLabelText("依据与差异说明")).toHaveValue("QA receipt");await act(async()=>{await router.navigate("/elsewhere");});await screen.findByText("还有未保存的内容");await userEvent.click(screen.getByRole("button",{name:"继续填写"}));expect(router.state.location.pathname).toBe("/production/stock");expect(api.write).not.toHaveBeenCalled();
});
it("locks the same window after an unknown result and keeps recovery controls",async()=>{
 api.write.mockRejectedValue(new Error("SIM lost reply"));mount();await fill();await userEvent.click(screen.getByRole("button",{name:"保存核验草稿"}));await screen.findByText("保存结果待核实，已锁定当前输入");await waitFor(()=>expect(screen.getByRole("button",{name:"关闭收货入库"})).toBeDisabled());expect(screen.getByRole("button",{name:"查询原操作结果"})).toBeEnabled();expect(screen.getByLabelText("依据与差异说明")).toHaveValue("QA receipt");
});
it("does not open an ordinary receipt form for a wrong owner",async()=>{
 const original=api.read.getMockImplementation()!;api.read.mockImplementation((path,options)=>path==="/api/production/warehouses/3"?Promise.resolve({...warehouse,scopes:[{...scope,owner_id:"9"}]}):original(path,options));mount();await screen.findByText("目的仓范围尚未就绪");expect(screen.queryByRole("button",{name:"保存核验草稿"})).not.toBeInTheDocument();expect(api.write).not.toHaveBeenCalled();
});
it("loads the FBA event workflow with the shipment already fixed and preserves upload uncertainty",async()=>{
 configureFba();
 api.write.mockRejectedValue(new Error("SIM upload response lost"));
 mount();
 const input=await screen.findByLabelText("FBA收货表");
 expect(screen.getAllByLabelText("FBA收货表")).toHaveLength(1);
 expect(api.read.mock.calls.some(([path])=>path==="/api/production/shipments?page_size=100")).toBe(false);
 await userEvent.upload(input,new File(["SIM"],"receipt.csv",{type:"text/csv"}));
 await userEvent.click(screen.getByRole("button",{name:"导入收货表"}));
 await screen.findByText("上传结果待核实");
 await waitFor(()=>expect(screen.getByRole("button",{name:"关闭收货入库"})).toBeDisabled());
 expect(api.write.mock.calls[0]![0]).toBe("/api/production/fba/uploads?scope_id=8&shipment_id=77");
 expect(screen.getByRole("button",{name:"查询原上传结果"})).toBeEnabled();
});

it("keeps the original standalone receipt wizard for existing consumers",async()=>{mount(false,true,true);await screen.findByRole("button",{name:"下一步"});expect(screen.queryByLabelText("7 qualified_units")).not.toBeInTheDocument();expect(screen.getByRole("dialog",{name:"目的仓实收"})).toBeInTheDocument();});
it("does not expose a verification form to a read-only account",async()=>{mount(false,false);await screen.findByText("当前账号只读");expect(screen.queryByRole("button",{name:"保存核验草稿"})).not.toBeInTheDocument();expect(api.write).not.toHaveBeenCalled();});
it("retains every row of a multi-shipment FBA report and prevents replacing an unsaved review",async()=>{
 const report={id:"9",scope_id:"8",revision:"1",status:"DRAFT",filename:"SIM-multiple-shipments.csv",decisions:[],resolved:[],issues:[],history:[],rows:[{source_row:2,raw:{MSKU:"SIM-SKU-A"},quantity:"1",identity:{sku_id:"11",tracked:true},existing_candidates:[],same_file_candidates:[],bindings:[{id:"1",shipment_id:"77",units:"4",received_units:"0"}]},{source_row:3,raw:{MSKU:"SIM-SKU-B"},quantity:"2",identity:{sku_id:"12",tracked:true},existing_candidates:[],same_file_candidates:[],bindings:[{id:"2",shipment_id:"99",units:"4",received_units:"0"}]}]};
 configureFba([report]);
 api.write.mockResolvedValue(report);
 mount();
 await userEvent.click(await screen.findByRole("button",{name:"更多"}));
 await userEvent.click(screen.getByRole("menuitem",{name:"来源与原件"}));
 await userEvent.click(screen.getByRole("button",{name:/SIM-multiple-shipments.csv/}));
 await screen.findByText("SIM-SKU-A",{exact:true});
 await userEvent.click(screen.getByText("逐行核对与更正",{exact:true}));
 await screen.findByText("第2行 · SIM-SKU-A");
 expect(screen.getByText("第3行 · SIM-SKU-B")).toBeInTheDocument();
 await userEvent.type(screen.getByLabelText(/本批核对依据/),"QA unsaved review");
 await waitFor(()=>expect(screen.getByLabelText("FBA收货表")).toBeDisabled());
 await userEvent.click(screen.getByRole("button",{name:"关闭收货入库"}));
 await screen.findByText("还有未保存的核验内容");
 expect(api.write).not.toHaveBeenCalled();
});

function configureFba(batches: {id:string}[] = []) {
 const original=api.read.getMockImplementation()!;
 api.read.mockImplementation((path,options)=>{
  if(path==="/api/production/warehouses/3")return Promise.resolve({...warehouse,type:"FBA"});
  if(path==="/api/production/shipments/77")return Promise.resolve({...shipment,status:"CONFIRMED"});
  if(path.includes("/fba/state"))return Promise.resolve({enabled:true,initialized:true,scopes:[{id:"8",warehouse_id:"3",owner_id:"1"}],references:[{id:"31",scope_id:"8",shipment_id:"77",shipment_revision:"5",reference_id:"SIM-REF",evidence:"SIM"}],batches,events:[],identities:[{scope_id:"8",sku_id:"11",tracked:true}],actions:[],history:[],stock:{items:[]}});
  const report=batches.find(value=>path.endsWith(`/fba/batches/${value.id}`));
  return report?Promise.resolve(report):original(path,options);
 });
}

it("keeps imports and saved drafts in the arrival window and completes only after receipt confirmation",async()=>{
 const report={id:"9",scope_id:"8",source_kind:"REPORT",revision:"1",status:"DRAFT",filename:"SIM-arrival.csv",decisions:[],resolved:[],issues:[],history:[],rows:[{source_row:2,business_date:"2026-10-30",raw:{MSKU:"1112-Black-L","Reference ID":"SIM-REF","Event Type":"Receipts"},quantity:"2",identity:{sku_id:"11",tracked:true},existing_candidates:[],same_file_candidates:[],bindings:[{...binding,shipment_id:"77"}]}]};
 configureFba([report]);
 let draft:Record<string,unknown>;
 const completed=vi.fn();
 api.write.mockImplementation(async(path,options)=>{
  await Promise.resolve();
  if(path.includes("/uploads"))return report;
  if(path.endsWith("unified-confirm"))return {...draft,status:"POSTED",added_units:"1",linked_units:"0"};
  draft={id:"30",scope_id:"8",source_kind:"MANUAL",shipment_id:"77",status:"DRAFT",revision:"1",draft_payload:(options?.body as {draft_payload:unknown}).draft_payload,history:[]};
  return draft;
 });
 const router=mount(false,true,false,completed);
 await userEvent.upload(await screen.findByLabelText("FBA收货表"),new File(["SIM"],"receipts.csv",{type:"text/csv"}));
 await userEvent.click(screen.getByRole("button",{name:"导入收货表"}));
 const preview=await screen.findByRole("table",{name:"导入接收预览"});
 expect(preview).toHaveTextContent("1112-Black-L");
 expect(completed).not.toHaveBeenCalled();
 expect(router.state.location.pathname).toBe("/production/stock");
 await userEvent.click(screen.getByRole("button",{name:"填入收货表"}));
 const input=screen.getByRole("textbox",{name:"1112-Black-L第2行本次收货"});
 expect(input).toHaveValue("2");
 await userEvent.clear(input);await userEvent.type(input,"1");
 await userEvent.type(screen.getByRole("textbox",{name:"第2行调整说明"}),"实际只收到1件");
 await userEvent.type(screen.getByRole("textbox",{name:/^收货依据/}),"虚构验收回归");
 await userEvent.click(screen.getByRole("button",{name:"保存草稿"}));
 await waitFor(()=>expect(screen.getByRole("button",{name:"保存草稿"})).toBeDisabled());
 expect(completed).not.toHaveBeenCalled();
 expect(screen.getByRole("textbox",{name:"1112-Black-L第2行本次收货"})).toHaveValue("1");
 await userEvent.click(screen.getByRole("button",{name:"核对收货 1 件"}));
 expect(await screen.findByRole("region",{name:"确认接收摘要"})).toHaveTextContent("原表 2 → 1");
 await userEvent.click(screen.getByRole("button",{name:"确认收货 1 件"}));
 await waitFor(()=>expect(completed).toHaveBeenCalledOnce());
 expect(report.rows[0]!.quantity).toBe("2");
});
