import { useState } from "react";
import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { createMemoryRouter, RouterProvider, MemoryRouter } from "react-router-dom";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import { ApiRequestError } from "../../api/client";
import { AuthzGenerationProvider } from "../../app/AuthzGenerationContext";
import { FbaStocktake } from "./FbaStocktake";
import { FbaWorkspace } from "./FbaWorkspace";
import { FbaInventoryOverview } from "./FbaInventoryOverview";
import { FbaFileUpload } from "./FbaFileUpload";
import type { FbaState } from "./fbaTypes";
import type { DirectoryRecord } from "./directoryTypes";
const api=vi.hoisted(()=>({read:vi.fn<typeof import("../../api/client").requestApi>(),write:vi.fn<typeof import("../../api/client").writeApi>()}));
const NativeRequest = globalThis.Request;
beforeEach(() => { vi.stubGlobal("Request", class extends NativeRequest { constructor(input: RequestInfo | URL, init?: RequestInit) { const { signal, ...options } = init ?? {}; super(input, options); if (signal) Object.defineProperty(this, "signal", { value: signal }); } }); });
afterEach(() => vi.unstubAllGlobals());
vi.mock("../../api/client",async original=>({...await original<typeof import("../../api/client")>(),requestApi:api.read,writeApi:api.write}));
const record={id:"2",name:"SIM FBA",type:"FBA",status:"ACTIVE",revision:"1",seller_account:"SIM",marketplace:"US"} as DirectoryRecord;
const state: FbaState={enabled:true,initialized:true,scopes:[{id:"7",warehouse_id:"2",owner_id:"1",seller_account:"SIM",marketplace:"US",report_source_scope_id:"3",store_evidence:"SIM",cutoff_on:"2026-09-30",opening_basis:"Explicit simulated zero",revision:"2",catalog_version:"1:1",simulated:true}],identities:[{scope_id:"7",sku_id:"11",style_id:"4",seller_sku:"SIM-S",asin:"AS",fnsku:"FN",tracked:true,sellable:"15",unsellable:"1",pending_units:"0",unassessed_units:"0",catalog_version:"1:1",evidence:"SIM"},{scope_id:"7",sku_id:"12",style_id:"4",seller_sku:"SIM-M",asin:"AS2",fnsku:"FN2",tracked:false,sellable:"5",unsellable:"0",pending_units:"0",unassessed_units:"0",catalog_version:"1:1",evidence:"SIM"}],references:[],batches:[],events:[{id:"1",scope_id:"7",sku_id:"11",event_key:"receipt",units:"18",occurred_local:"2026-10-25T10:00:00-07:00",fulfillment_center:"TEST",correction_of:null,evidence:"SIM"},{id:"2",scope_id:"7",sku_id:"12",event_key:"receipt-other",units:"5",occurred_local:"2026-10-25T10:00:00-07:00",fulfillment_center:"TEST",correction_of:null,evidence:"SIM"}],actions:[{id:"4",scope_id:"7",kind:"FULFILLMENT",event_key:"physical",occurred_at:"2026-10-27T17:00:00Z",status:"POSTED",revision:"1",related_action_id:null,payload:{reason:"SIMULATED actual fulfillment",lines:[{sku_id:"11",units:"3"}]}},{id:"5",scope_id:"7",kind:"RETURN",event_key:"physical-return",occurred_at:"2026-10-28T17:00:00Z",status:"POSTED",revision:"1",related_action_id:"4",payload:{reason:"SIMULATED damaged physical return",lines:[{sku_id:"11",units:"1",quality:"DEFECTIVE"}]}}],history:[],stock:{items:[{sku_id:"11",owner_id:"1",on_hand_units:"16",free_available_units:"15",reserved_units:"0",held_units:"0",state:"ready"},{sku_id:"12",owner_id:"1",on_hand_units:"5",free_available_units:"5",reserved_units:"0",held_units:"0",state:"ready"}]},platform_observation_state:"UNKNOWN"};
state.inventory_view={"7":{on_hand:"21",available:"20",latest_movement_at:"2026-10-28T17:00:00Z",stock_effect:false,groups:[{style_id:"4",on_hand:"21",items:[{sku_id:"11",style_id:"4",seller_sku:"SIM-S",on_hand:"16",available:"15",received:"18",fulfilled:"3",returned:"1"},{sku_id:"12",style_id:"4",seller_sku:"SIM-M",on_hand:"5",available:"5",received:"5",fulfilled:"0",returned:"0"}]}],issues:[],movements:[{id:"return:5",sku_id:"11",kind:"RETURN",units:"1",occurred_at:"2026-10-28T17:00:00Z",reference:"physical-return",reason:"Damaged return",quality:"DEFECTIVE",batch_id:null,report_version_ids:[]},{id:"action:4",sku_id:"11",kind:"FULFILLMENT",units:"-3",occurred_at:"2026-10-27T17:00:00Z",reference:"physical",reason:"Physical fulfillment",quality:null,batch_id:null,report_version_ids:[]}]}};
async function openView(name:string){await userEvent.click(await screen.findByRole("button",{name:"更多办理"}));await userEvent.click(screen.getByRole("menuitem",{name}));}
it("shows imported evidence with unknown opening and preserves negative receipt corrections", async () => {
 const read = api.read.getMockImplementation()!;
 api.read.mockImplementation((path, options) => path.includes("fba/state") ? Promise.resolve({enabled:true,initialized:false,scopes:[]}) : read(path, options));
 mount(<FbaWorkspace record={{...record,source_evidence:{kind:"fba",packings:[],receipts:[{source:"fictional.csv!2",sku:"TEST-S",units:"-1",status:"更正"}],excluded_receipt_rows:2}}} owner="" canWrite refresh={0} reload={()=>undefined}/>);
 expect(await screen.findByRole("heading",{name:"已导入装箱与验收资料"})).toBeVisible();
 expect(screen.getByText(/FBA期初、当前在库和可售未知/)).toBeVisible();
 expect(screen.queryByRole("button",{name:"确认零期初并启用"})).not.toBeInTheDocument();
 await userEvent.click(screen.getByText("已确认货件接收原始流水（1条）",{selector:"summary"}));
 expect(within(screen.getByRole("table",{name:"已确认货件接收流水"})).getByText("-1",{exact:true})).toBeVisible();
 expect(api.write).not.toHaveBeenCalled();
});
function mount(element:React.ReactNode,canWrite=true,entry="/production/warehouses/2"){return render(<AuthzGenerationProvider boundary={{principalId:1,roles:[canWrite?"data_manager":"viewer"],siteId:1,siteConfigVersionId:1}} onRevoked={()=>undefined}><RouterProvider router={createMemoryRouter([{path:"*",element}],{initialEntries:[entry]})}/></AuthzGenerationProvider>);}
beforeEach(()=>{api.read.mockReset();api.write.mockReset();api.read.mockImplementation((path:string)=>{if(path.includes("catalog-products"))return Promise.resolve({identities:[],issues:[],store:"SIM scope",catalog_version:"1:1"});if(path.includes("fba/state"))return Promise.resolve(state);if(path.includes("skus"))return Promise.resolve({items:[{sku_id:"11",style_id:"4",style_code:"1112",label:"SIM S",code:"SIM-S",catalog_version:"1:1"},{sku_id:"12",style_id:"4",style_code:"1112",label:"SIM M",code:"SIM-M",catalog_version:"1:1"}]});if(path.includes("source-scope"))return Promise.resolve({report_source_scope_id:3,seller_account_display_name:"SIM scope"});throw new Error(path);});api.write.mockResolvedValue(state);});
it("uses the existing report entry without offering a second daily upload", async () => {
  mount(<FbaWorkspace record={record} owner="1" canWrite refresh={0} reload={() => undefined} />);
  expect(await screen.findByRole("button", { name: "调整可售状态" })).toBeEnabled();
  expect(screen.queryByRole("button", { name: "更新今日库存" })).not.toBeInTheDocument();
  expect(screen.queryByLabelText("上传运营日报或退货日报")).not.toBeInTheDocument();
  expect(screen.getByRole("link", { name: "发布总表" })).toHaveAttribute("href", "/");
  expect(api.write).not.toHaveBeenCalled();
});
it("reads the selected FBA shop catalog and omits other-shop zero balances", async () => {
  const read = api.read.getMockImplementation()!;
  api.read.mockImplementation((path, options) => path.includes('fba/state')
    ? Promise.resolve({ ...state, inventory_view: { '7': { ...state.inventory_view!['7']!, groups: [
      ...state.inventory_view!['7']!.groups,
      { style_id: '99', on_hand: '0', items: [{ sku_id: '999', style_id: '99', seller_sku: 'OTHER-XXXL', on_hand: '0', available: '0', received: '0', fulfilled: '0', returned: '0' }] },
    ] } } }) : read(path, options));
  mount(<FbaWorkspace record={record} owner="1" canWrite={false} refresh={0} reload={() => undefined} />, false);
  await screen.findByRole('table', { name: 'FBA在库库存' });
  expect(api.read.mock.calls.some(([path]) => path === '/api/production/skus?contract_version=2&report_source_scope_id=3')).toBe(true);
  expect(screen.queryByRole('button', { name: '查看OTHER-XXXL库存变动' })).not.toBeInTheDocument();
  expect(screen.getByLabelText('FBA账面库存汇总')).toHaveTextContent('21');
  expect(api.write).not.toHaveBeenCalled();
});

it("retains business actions and moves update recovery into More and keeps product stop and restore settings collapsed", async () => {
 mount(<FbaWorkspace record={record} owner="1" canWrite refresh={0} reload={()=>undefined}/>);
 await userEvent.click(await screen.findByRole("button",{name:"更多办理"}));
 expect(screen.getAllByRole("menuitem").map(item=>item.textContent)).toEqual(["库存更新","到货验收","销售与退货","FBA 商品管理","操作记录"]);
 await userEvent.click(screen.getByRole("menuitem",{name:"FBA 商品管理"}));
 expect(screen.getByRole("table",{name:"FBA商品列表"})).toBeVisible();
 expect(screen.queryByRole("button",{name:"调整可售状态"})).not.toBeInTheDocument();
 expect(screen.getByRole("button",{name:"保存商品设置",hidden:true})).not.toBeVisible();
 await userEvent.click(screen.getByText("停用、恢复或更新商品资料",{selector:"summary"}));
 expect(screen.getByRole("button",{name:"保存商品设置"})).toBeVisible();
 expect(api.write).not.toHaveBeenCalled();
});

it("groups manual sales and returns below the existing daily report flow", async () => {
 mount(<FbaWorkspace record={record} owner="1" canWrite refresh={0} reload={()=>undefined}/>);
 await openView("销售与退货");
 expect(screen.getByRole("heading",{name:"销售与退货"})).toBeVisible();
 expect(screen.getByLabelText(/^业务单号或发货编号/)).not.toBeVisible();
 await userEvent.click(screen.getByText("手工登记销售或退货",{selector:"summary"}));
 expect(screen.getByLabelText(/^业务单号或发货编号/)).toBeVisible();
 await userEvent.click(screen.getByRole("button",{name:"退货入库"}));
 expect(screen.getByLabelText(/^对应的销售出库记录/)).toBeVisible();
 expect(api.write).not.toHaveBeenCalled();
});

it("shows product setting history with readable operations and expandable reasons", async () => {
 const historyState = {...state,history:[{document_kind:"FBA_SCOPE",document_id:"7",operation_kind:"TRACKING",actor_name:"模拟管理员",reason:"恢复本批商品",created_at:"2026-11-06T10:00:00Z"}]};
 api.read.mockImplementation((path:string)=>Promise.resolve(path.includes("fba/state")?historyState:{items:[]}));
 mount(<FbaWorkspace record={record} owner="1" canWrite refresh={0} reload={()=>undefined}/>);
 await openView("操作记录");
 const table=screen.getByRole("table",{name:"FBA操作记录"});
 expect(within(table).getByText("更新商品设置")).toBeVisible();
 expect(within(table).getByText("模拟管理员")).toBeVisible();
 expect(within(table).getByText("恢复本批商品")).not.toBeVisible();
 await userEvent.click(within(table).getByText("查看",{selector:"summary"}));
 expect(within(table).getByText("恢复本批商品")).toBeVisible();
 expect(screen.getByText("physical",{exact:true})).not.toBeVisible();
 await userEvent.click(screen.getByText("查看或撤销收发记录",{selector:"summary"}));
 await userEvent.click(screen.getByText("2026-10-27 · 销售出库 · 已登记",{selector:"summary"}));
 expect(screen.getByText("physical",{exact:true})).toBeVisible();
 await userEvent.type(screen.getByLabelText("撤销原因"),"模拟更正");
 await userEvent.click(within(screen.getByText("physical",{exact:true}).closest("details")!).getByRole("button",{name:"撤销这条记录"}));
 await waitFor(()=>expect(api.write).toHaveBeenCalledOnce());
 expect(api.write.mock.calls[0]?.[0]).toBe("/api/production/fba/commands/action-reverse");
 expect(api.write.mock.calls[0]?.[1]?.body).toMatchObject({action_id:"4",expected_revision:"1",reason:"模拟更正"});
});

it.each([["returns","退货入库"],["observation","Amazon库存核对"],["tracking","FBA 商品管理"]])("keeps the existing %s link usable", async (view,title) => {
 mount(<FbaWorkspace record={record} owner="1" canWrite={false} refresh={0} reload={()=>undefined}/>,false,`/production/warehouses/2?fba_view=${view}`);
 expect(await screen.findByRole("heading",{name:title})).toBeVisible();
 expect(api.write).not.toHaveBeenCalled();
});
it("converts inventory quality in one batch with the observed scope revision",async()=>{
 mount(<FbaWorkspace record={record} owner="1" canWrite refresh={0} reload={()=>undefined}/>);
 await userEvent.click(await screen.findByRole("button",{name:"调整可售状态"}));
 const dialog=screen.getByRole("dialog",{name:"调整可售状态"});
 expect(within(dialog).getByLabelText("统一原因")).toHaveValue("WAREHOUSE_DAMAGED");
 expect(within(dialog).getAllByRole("columnheader").map(cell=>cell.textContent)).toEqual(["商品规格","可售","不可售","本次标记数量","原因"]);
 const quantity=within(dialog).getByRole("textbox",{name:"SIM-S 本次标记数量"});
 await userEvent.type(quantity,"16");
 expect(within(dialog).getByText("最多可标记15件")).toBeVisible();
 expect(within(dialog).getByRole("button",{name:/确认标记/})).toBeDisabled();
 expect(api.write).not.toHaveBeenCalled();
 await userEvent.clear(quantity);await userEvent.type(quantity,"1");
 expect(within(dialog).getByText("调整后 可售14 · 不可售2")).toBeVisible();
 await userEvent.click(within(dialog).getByRole("button",{name:"确认标记1件不可售"}));
 await waitFor(()=>expect(api.write).toHaveBeenCalledTimes(1));
 expect(api.write.mock.calls[0]).toEqual(["/api/production/fba/commands/quality",expect.objectContaining<Partial<NonNullable<Parameters<typeof api.write>[1]>>>({body:expect.objectContaining<Record<string,unknown>>({scope_id:"7",expected_revision:"2",from_quality:"QUALIFIED",target_quality:"DEFECTIVE",lines:[{sku_id:"11",units:"1",reason_code:"WAREHOUSE_DAMAGED"}]})})]);
 await waitFor(()=>expect(screen.queryByRole("heading",{name:"调整可售状态"})).not.toBeInTheDocument());
 await userEvent.click(screen.getByRole("button",{name:"调整可售状态"}));
 expect(screen.queryByText("请至少填写一个规格的大于零整数数量")).not.toBeInTheDocument();

});
it("explains restoring sellability and keeps entered rows when searching",async()=>{
 mount(<FbaWorkspace record={record} owner="1" canWrite refresh={0} reload={()=>undefined}/>);
 await userEvent.click(await screen.findByRole("button",{name:"调整可售状态"}));
 const dialog=screen.getByRole("dialog",{name:"调整可售状态"});
 await userEvent.click(within(dialog).getByRole("button",{name:/^恢复可售$/}));
 expect(within(dialog).getByText("历史未分类")).toBeVisible();
 expect(within(dialog).queryByRole("textbox",{name:"SIM-M 本次恢复数量"})).not.toBeInTheDocument();
 await userEvent.type(within(dialog).getByRole("textbox",{name:"SIM-S 本次恢复数量"}),"1");
 expect(within(dialog).getByText("调整后 可售16 · 不可售0")).toBeVisible();
 const search=within(dialog).getByRole("searchbox",{name:"查找要调整的商品"});
 await userEvent.type(search,"NOT-FOUND");
 expect(within(dialog).getByText("没有匹配的商品规格")).toBeVisible();
 expect(within(dialog).getByRole("button",{name:"确认恢复1件可售"})).toBeEnabled();
 await userEvent.clear(search);
 expect(within(dialog).getByRole("textbox",{name:"SIM-S 本次恢复数量"})).toHaveValue("1");
 await userEvent.click(within(dialog).getByRole("button",{name:"确认恢复1件可售"}));
 await waitFor(()=>expect(api.write).toHaveBeenCalledTimes(1));
 expect(api.write.mock.calls[0]).toEqual(["/api/production/fba/commands/quality",expect.objectContaining<Partial<NonNullable<Parameters<typeof api.write>[1]>>>({body:expect.objectContaining<Record<string,unknown>>({scope_id:"7",expected_revision:"2",from_quality:"DEFECTIVE",target_quality:"QUALIFIED",lines:[{sku_id:"11",units:"1",reason_allocations:[{reason_code:"UNCLASSIFIED",units:"1"}]}]})})]);
});
it("retains untracked balances and unknown platform observation for viewers",async()=>{
 mount(<FbaWorkspace record={record} owner="1" canWrite={false} refresh={0} reload={()=>undefined}/>,false);
 await screen.findByRole("button",{name:/^1112 · (?:查看|收起)$/});expect(screen.getByRole("table",{name:"FBA在库库存"})).toBeVisible();const primary=screen.getByRole("table",{name:"FBA在库库存"});expect(within(primary).getAllByRole("columnheader").map(cell=>cell.textContent)).toEqual(["款号","颜色","尺码待核","合计"]);expect(within(primary).getByRole("button",{name:"查看SIM-M库存变动"})).toHaveTextContent("5");expect(within(primary).getByRole("button",{name:"查看SIM-S库存变动"})).toHaveTextContent("16");expect(within(primary).getByRole("cell",{name:"SIM-M"})).toBeVisible();expect(screen.getByLabelText("FBA账面库存汇总")).toHaveTextContent("21");expect(screen.getByRole("table",{name:"FBA库存对账",hidden:true})).not.toBeVisible();
 await userEvent.click(screen.getByText("库存记录与对账"));await userEvent.click(screen.getByText("查看详细对账"));
 const table=screen.getByRole("table",{name:"FBA库存对账"});expect(within(table).getByText("SIM-M")).toBeVisible();expect(within(table).getByText(/未跟踪 · 保留余额/)).not.toBeVisible();expect(within(table).getAllByText("未知，未填零")).toHaveLength(2);expect(screen.getByText(/不能宣称与Amazon实时余额相符/)).not.toBeVisible();
 await openView("销售与退货");expect(screen.queryByRole("button",{name:"确认销售出库"})).not.toBeInTheDocument();expect(api.write).not.toHaveBeenCalled();
});
it.each(["unknown","missing","zero"] as const)("keeps %s on-hand distinct from a known zero",async mode=>{
 const original=api.read.getMockImplementation()!;
 api.read.mockImplementation((path,options)=>path.includes("fba/state")?Promise.resolve({...state,inventory_view:{"7":{...state.inventory_view!["7"]!,on_hand:mode==="zero"?"16":null,groups:state.inventory_view!["7"]!.groups.map(g=>({...g,on_hand:mode==="zero"?"16":null,items:g.items.map(i=>i.sku_id==="12"?{...i,on_hand:mode==="zero"?"0":null}:i)}))}},stock:{items:mode==="missing"?state.stock.items.slice(0,1):state.stock.items.map(item=>item.sku_id==="12"?{...item,on_hand_units:mode==="zero"?"0":null}:item)}}):original(path,options));
 mount(<FbaWorkspace record={record} owner="1" canWrite={false} refresh={0} reload={()=>undefined}/>,false);
 await screen.findByRole("button",{name:/^1112 · (?:查看|收起)$/});const table=screen.getByRole("table",{name:"FBA在库库存"});if(mode==="zero") expect(within(table).queryByRole("button",{name:"查看SIM-M库存变动"})).not.toBeInTheDocument(); else expect(within(table).getByRole("button",{name:"查看SIM-M库存变动"})).toHaveTextContent("待核");expect(within(table).getByRole("row",{name:new RegExp(`本仓合计.*${mode==="zero"?"16":"待核"}`)})).toBeVisible();expect(screen.getByLabelText("FBA账面库存汇总")).toHaveTextContent(mode==="zero"?"16":"待核");expect(api.write).not.toHaveBeenCalled();
});
it("lets a manager select a whole style without sending stock or opening quantities",async()=>{
 mount(<FbaWorkspace record={record} owner="1" canWrite refresh={0} reload={()=>undefined}/>);
 await openView("FBA 商品管理");await userEvent.click(screen.getByText("停用、恢复或更新商品资料",{selector:"summary"}));await userEvent.click(screen.getByRole("checkbox",{name:"启用款号 1112"}));await userEvent.type(screen.getByLabelText(/调整原因/),"SIMULATED select complete style");await userEvent.click(screen.getByRole("button",{name:"保存商品设置"}));
 await waitFor(()=>expect(api.write).toHaveBeenCalledOnce());expect(api.write.mock.calls[0]?.[0]).toBe("/api/production/fba/commands/tracking");expect(api.write.mock.calls[0]?.[1]?.body).toMatchObject({scope_id:"7",expected_revision:"2",sku_ids:["11","12"]});expect(api.write.mock.calls[0]?.[1]?.body).not.toHaveProperty("opening_units");
});
it("locks an uncertain file upload and queries the same operation receipt",async()=>{
 const saved=vi.fn();api.write.mockRejectedValueOnce(new ApiRequestError(503,"production_result_unknown","结果未知"));api.read.mockResolvedValue({id:"9",rows:[]});mount(<FbaFileUpload path="/api/production/fba/uploads?scope_id=7" label="FBA source" saved={saved}/>);
 await userEvent.upload(screen.getByLabelText("FBA source"),new File(["SIMULATED"],"receipts.csv",{type:"text/csv"}));await userEvent.click(screen.getByRole("button",{name:"上传并预览接收明细"}));expect(await screen.findByText("上传结果待核实")).toBeVisible();expect(screen.getByLabelText("FBA source")).toBeDisabled();const key=api.write.mock.calls[0]?.[1]?.operationKey;
 await userEvent.click(screen.getByRole("button",{name:"查询原上传结果"}));await waitFor(()=>expect(saved).toHaveBeenCalledOnce());expect(api.read).toHaveBeenCalledWith(`/api/production/commands/${key}`);expect(api.write).toHaveBeenCalledOnce();
});
it("confirms from a retained identity source without requiring business reports and keeps input on failure",async()=>{
 const original=api.read.getMockImplementation()!;
 api.read.mockImplementation((path,options)=>path.includes("source-scope")?Promise.resolve({report_source_scope_id:3,seller_account_display_name:"SIM store"}):path.includes("fba/state")?Promise.resolve({...state,initialized:false}):original(path,options));
 api.write.mockResolvedValueOnce({identities:[{source_row:2,seller_sku:"SIM-S",sku_id:"11",asin:"B000000001",fnsku:"X000000001",store:"SIM store",reason:"CSV row2"}],source_id:"abc",sha256:"abc",report_source_scope_id:"3",stock_effect:false});
 const saved=vi.fn();const user=userEvent.setup();mount(<FbaWorkspace record={record} owner="1" canWrite refresh={0} reload={saved}/>);
 const confirm=await screen.findByRole("button",{name:"确认零期初并启用"});expect(confirm).toBeEnabled();
 await user.type(screen.getByLabelText(/^期初截止日期/),"2026-10-01");
 await user.type(screen.getByLabelText(/^货主编号/),"1");await user.type(screen.getByLabelText(/^货主名称/),"SIM owner");
 await user.type(screen.getByLabelText(/^期初依据/),"SIM empty warehouse");
 await user.click(screen.getByText("补充商品资料",{selector:"summary"}));await user.upload(screen.getByLabelText("FBA商品资料CSV"),new File(["SIMULATED"],"identity.csv",{type:"text/csv"}));
 await user.click(screen.getByRole("button",{name:"读取商品资料"}));await screen.findByText("已读取 1 个规格");
 
 expect(screen.getByRole("link",{name:"查看身份原表"})).toHaveAttribute("href","/api/production/fba/mapping-source/abc?report_source_scope_id=3");
 await user.click(screen.getByRole("checkbox",{name:/确认截止日期各商品库存为0/}));await user.click(screen.getByRole("checkbox",{name:/已核对补充文件/}));expect(confirm).toBeEnabled();
 api.write.mockRejectedValueOnce(new ApiRequestError(409,"fba_identity_conflict","CSV第2行存在冲突"));await user.click(confirm);await screen.findByText("CSV第2行存在冲突");
 expect(screen.getByLabelText(/^货主名称/)).toHaveValue("SIM owner");expect(screen.getByLabelText(/^期初截止日期/)).toHaveValue("2026-10-01");expect(saved).not.toHaveBeenCalled();
 expect(api.write.mock.calls[1]?.[1]?.body).toMatchObject({identity_source:{source_id:"abc",report_source_scope_id:"3"},identities_confirmed:true,explicit_zero_opening:true});
 await user.click(confirm);await waitFor(()=>expect(saved).toHaveBeenCalledOnce());
 expect(api.read.mock.calls.some(([path])=>path.includes("business")||path.includes("reports"))).toBe(false);
});

it("focuses an omitted opening date and keeps the confirmed store selected",async()=>{
 const original=api.read.getMockImplementation()!;
 api.read.mockImplementation((path,options)=>path.includes("fba/state")?Promise.resolve({...state,initialized:false}):original(path,options));
 mount(<FbaWorkspace record={record} owner="1" canWrite refresh={0} reload={()=>undefined}/>);
 const confirm=await screen.findByRole("button",{name:"确认零期初并启用"});
 await userEvent.click(confirm);
 const date=screen.getByLabelText(/^期初截止日期/);
 expect(date).toHaveFocus();expect(date).toHaveAttribute("aria-invalid","true");
 expect(screen.getByText("请选择期初截止日期")).toBeVisible();
 expect(screen.getByText("SIM scope · 美国站")).toBeVisible();
 expect(api.write).not.toHaveBeenCalled();
 await userEvent.type(date,"2026-10-01");expect(screen.queryByText("请选择期初截止日期")).not.toBeInTheDocument();
});

it("opens FBA with reviewed product data and a single zero-opening confirmation",async()=>{
 const original=api.read.getMockImplementation()!;
 api.read.mockImplementation((path,options)=>path.includes("fba/state")?Promise.resolve({...state,initialized:false}):path.includes("catalog-products")?Promise.resolve({identities:[{sku_id:"11",seller_sku:"SIM-S",asin:"B000000001",fnsku:"X000000001",store:"SIM scope"}],issues:[{sku_id:"12",label:"SIM-M",message:"请补齐平台编码"}],store:"SIM scope",catalog_version:"1:1"}):original(path,options));
 const saved=vi.fn();mount(<FbaWorkspace record={record} owner="1" canWrite refresh={0} reload={saved}/>);
 expect(await screen.findByText("已自动带入 1 个商品规格")).toBeVisible();
 expect(screen.getByText("1 个规格待补充，可在首次到货时处理")).toBeVisible();
 expect(screen.getByLabelText("FBA商品资料CSV")).not.toBeVisible();
 expect(screen.getAllByRole("checkbox")).toHaveLength(1);
 await userEvent.click(screen.getByText("补充商品资料",{selector:"summary"}));
 await userEvent.upload(screen.getByLabelText("FBA商品资料CSV"),new File(["SIM"],"unused.csv",{type:"text/csv"}));
 await userEvent.click(screen.getByRole("button",{name:"使用已审核商品资料"}));
 expect(screen.getByLabelText("FBA商品资料CSV")).toHaveValue("");
 expect(api.write).not.toHaveBeenCalled();
 await userEvent.type(screen.getByLabelText(/^期初截止日期/),"2026-10-01");
 await userEvent.type(screen.getByLabelText(/^货主编号/),"1");
 await userEvent.type(screen.getByLabelText(/^货主名称/),"SIM owner");
 await userEvent.type(screen.getByLabelText(/^期初依据/),"SIM zero opening");
 await userEvent.click(screen.getByRole("checkbox"));
 await userEvent.click(screen.getByRole("button",{name:"确认零期初并启用"}));
 await waitFor(()=>expect(saved).toHaveBeenCalledOnce());
 expect(api.write).toHaveBeenCalledOnce();
 expect(api.write.mock.calls[0]?.[1]?.body).toMatchObject({identity_mode:"catalog",catalog_version:"1:1",explicit_zero_opening:true,identities:[{sku_id:"11"}]});
 expect(api.write.mock.calls[0]?.[1]?.body).not.toHaveProperty("identity_source");
});

it("keeps unchecked receipt rows unchanged during bulk review",async()=>{
 const original=api.read.getMockImplementation()!;
 const batch={id:"9",scope_id:"7",filename:"selection.csv",revision:"1",status:"DRAFT",digest:"sim",issues:[],decisions:[],resolved:[],history:[],rows:[2,3].map(source_row=>({source_row,raw:{MSKU:"SIM-S","Date and Time":"2026-10-25T10:00:00-07:00"},quantity:"1",business_date:"2026-10-25",identity:{sku_id:"11",tracked:true},fingerprint:String(source_row),same_file_candidates:[],existing_candidates:[],bindings:[]}))};
 api.write.mockResolvedValue({...batch,revision:"2"});
 api.read.mockImplementation((path,options)=>path.includes("fba/state")?Promise.resolve({...state,batches:[batch]}):path.includes("fba/batches/9")?Promise.resolve(batch):(path.includes("shipments?page_size")||path.includes("inventory/destination-shipments"))?Promise.resolve({items:[]}):original(path,options));
 mount(<FbaWorkspace record={record} owner="1" canWrite refresh={0} reload={()=>undefined}/>);
 const user=userEvent.setup();await openView("到货验收");
 expect(screen.queryByLabelText("日报库存更新结果")).not.toBeInTheDocument();
 expect(screen.queryByRole("button",{name:"调整可售状态"})).not.toBeInTheDocument();
 expect(screen.getByText(/模拟账簿，真实账号未绑定/)).not.toBeVisible();
 await user.click(screen.getByText("店铺信息（模拟）",{selector:"summary"}));
 expect(screen.getByText(/模拟账簿，真实账号未绑定/)).toBeVisible();
 await user.click(screen.getByText(/已上传收货表/));await user.click(await screen.findByRole("button",{name:"selection.csv · 草稿"}));
 await user.click(await screen.findByText("逐行核对与更正",{exact:true}));
 await user.click(await screen.findByRole("checkbox",{name:"选择原表第3行"}));await user.type(screen.getByLabelText("本批人工事件核对前缀"),"SIM");await user.type(screen.getByLabelText(/^本批核对依据/),"SIM explicit rows");await user.click(screen.getByRole("button",{name:"标为新增待确认"}));await user.click(screen.getByRole("button",{name:"保存核对草稿"}));
 await waitFor(()=>expect(api.write).toHaveBeenCalledOnce());expect(api.write.mock.calls[0]?.[1]?.body).toMatchObject({decisions:[{source_row:"2",decision:"NEW",event_key:"SIM-行2"},{source_row:"3",decision:"PENDING"}]});
});

it("requires explicit identity reaffirmation after a catalog update",async()=>{
 const original=api.read.getMockImplementation()!;api.read.mockImplementation(async(path,options)=>{const value=await original(path,options);return path.includes("skus")?{items:(value as {items:Record<string,unknown>[]}).items.map(i=>({...i,catalog_version:"2:2"}))}:value;});
 mount(<FbaWorkspace record={record} owner="1" canWrite refresh={0} reload={()=>undefined}/>);const user=userEvent.setup();await openView("FBA 商品管理");await userEvent.click(screen.getByText("停用、恢复或更新商品资料",{selector:"summary"}));expect(screen.getByRole("table",{name:"FBA当前目录身份核对"})).toBeVisible();await user.type(screen.getByLabelText(/^调整原因/),"SIM current identities unchanged");const save=screen.getByRole("button",{name:"保存商品设置"});expect(save).toBeDisabled();await user.click(screen.getByRole("checkbox",{name:"已核对原FBA商品身份未变，确认使用当前目录"}));await user.click(save);await waitFor(()=>expect(api.write).toHaveBeenCalledOnce());expect(api.write.mock.calls[0]?.[1]?.body).toMatchObject({reconfirm_catalog:true,sku_ids:["11"]});
});

it("opens backend movement facts from stock and reuses the report import entry without writes",async()=>{
 mount(<FbaWorkspace record={record} owner="1" canWrite={false} refresh={0} reload={()=>undefined}/>,false);
 await screen.findByRole("button",{name:/^1112 · (?:查看|收起)$/});await userEvent.click(screen.getByRole("button",{name:"查看SIM-S库存变动"}));
 const detail=screen.getByRole("region",{name:"SIM-S库存变动"});
 expect(within(detail).getByText("销售出库")).not.toBeVisible();
 await userEvent.click(within(detail).getByText("变动记录"));
 expect(within(detail).getByText("销售出库")).toBeVisible();
 expect(within(detail).getByText("-3")).toBeVisible();
 expect(within(detail).getByText("实物退回 · 不可售")).toBeVisible();
 expect(within(detail).getByText("+1")).toBeVisible();
 expect(within(detail).getByText("Physical fulfillment")).not.toBeVisible();
 await userEvent.click(within(detail).getByLabelText("销售出库 -3件 · 2026-10-27"));
 expect(within(detail).getByText("Physical fulfillment")).toBeVisible();
 await userEvent.click(screen.getByText("库存记录与对账"));expect(screen.getByRole("link",{name:"发布总表"})).toHaveAttribute("href","/");expect(api.write).not.toHaveBeenCalled();
});

it("keeps individual receipt sources inside the compact movement history", async () => {
 const original=api.read.getMockImplementation()!;
 const inventory=state.inventory_view!["7"]!;
 api.read.mockImplementation((path,options)=>path.includes("fba/state") ? Promise.resolve({ ...state, inventory_view: { "7": { ...inventory, movements: [...inventory.movements,
   { id:"receipt:9", sku_id:"11", kind:"RECEIPT", units:"8", occurred_at:"2026-10-25T17:00:00Z", reference:"first", reason:"First receipt", quality:null, batch_id:"9", report_version_ids:["31"] },
   { id:"receipt:10", sku_id:"11", kind:"RECEIPT", units:"10", occurred_at:"2026-10-25T18:00:00Z", reference:"second", reason:"Second receipt", quality:null, batch_id:"10", report_version_ids:[] },
 ] } } }) : original(path,options));
 mount(<FbaWorkspace record={record} owner="1" canWrite={false} refresh={0} reload={()=>undefined}/>,false);
 await userEvent.click(await screen.findByRole("button", {name:"查看SIM-S库存变动"}));
 const detail=screen.getByRole("region",{name:"SIM-S库存变动"});
 expect(within(detail).getByText("变动记录").parentElement).toHaveTextContent("4");
 await userEvent.click(within(detail).getByText("变动记录"));
 expect(within(detail).getAllByText("FBA入库")).toHaveLength(2);
 expect(within(detail).getByText("+8")).toBeVisible();
 expect(within(detail).getByText("+10")).toBeVisible();
 const firstReceipt=within(detail).getByLabelText("FBA入库 8件 · 2026-10-25");
 await userEvent.click(firstReceipt);
 const receiptDetail=within(firstReceipt.closest("details")!);
 expect(receiptDetail.getByRole("link",{name:"查看接收原件"})).toHaveAttribute("href","/production/warehouses/2?owner=1&tab=stock&fba_view=receipts&fba_batch=9");
 expect(receiptDetail.getByRole("link",{name:"查看报告记录"})).toHaveAttribute("href","/ledger/published-details");
 expect(within(detail).getByText("Second receipt")).not.toBeVisible();
 await userEvent.click(within(detail).getByText("变动记录"));
 expect(within(detail).getByText("+8")).not.toBeVisible();
 expect(api.write).not.toHaveBeenCalled();
});

it("shows only backend exceptions and sends their review link to the same warehouse and owner",async()=>{
 const original=api.read.getMockImplementation()!;api.read.mockImplementation((path,options)=>path.includes("fba/state")?Promise.resolve({...state,inventory_view:{"7":{...state.inventory_view!["7"]!,issues:[{id:"batch:9",sku_id:null,label:"接收报告待处理",view:"receipts",batch_id:"9"}]}}}):original(path,options));
 mount(<FbaWorkspace record={record} owner="1" canWrite={false} refresh={0} reload={()=>undefined}/>,false);await userEvent.click(await screen.findByText("待核 1 项"));expect(screen.getByRole("link",{name:"接收报告待处理"})).toHaveAttribute("href","/production/warehouses/2?owner=1&tab=stock&fba_view=receipts&fba_batch=9");expect(api.write).not.toHaveBeenCalled();
});

it("shows the style-color-size matrix expanded and retains collapse, search and drill-down", async () => {
  const original = api.read.getMockImplementation()!;
  api.read.mockImplementation(async (path, options) => {
    const value = await original(path, options);
    return path.includes("skus") ? { items: (value as { items: Record<string, unknown>[] }).items.map((sku, index) => ({
      ...sku, standard_color: index === 0 ? "Black" : "Brown", standard_size: index === 0 ? "S" : "M",
    })) } : value;
  });
  mount(<FbaWorkspace record={record} owner="1" canWrite={false} refresh={0} reload={() => undefined} />, false);
  await screen.findByRole("button", { name:/^1112 · (?:查看|收起)$/ });
  const table = screen.getByRole("table", { name: "FBA在库库存" });
  expect(within(table).getAllByRole("columnheader").map(header => header.textContent)).toEqual(["款号", "颜色", "S", "M", "合计"]);
  const black = within(table).getByRole("row", { name: /1112 · 收起 Black 16 .*16/ });
  const brown = within(table).getByRole("row", { name: /1112(?: · 查看| · 收起)? Brown .*5 5/ });
  expect(black).toBeVisible();
  expect(brown).toBeVisible();
  expect(within(table).getByRole("row", { name: "本仓合计 16 5 21" })).toBeVisible();
  expect(within(black).getAllByRole("button")).toHaveLength(2);
  expect(within(brown).getAllByRole("button")).toHaveLength(1);
  await userEvent.click(within(black).getByRole("button", { name: "查看SIM-S库存变动" }));
  const detail = screen.getByRole("region", { name: "SIM-S库存变动" });
  expect(detail.closest("tr")?.previousElementSibling).toBe(black);
  expect(detail).toHaveTextContent("已出库3");
  await userEvent.click(screen.getByRole("button", { name:/^1112 · (?:查看|收起)$/ }));
  expect(screen.getByText("2种颜色 · 已收起")).toBeVisible();
  expect(within(table).queryByRole("button", { name: "查看SIM-S库存变动" })).not.toBeInTheDocument();
  expect(within(table).getByRole("row", { name: /1112 · 查看 2种颜色 · 已收起 16 5 21/ })).toBeVisible();
  await userEvent.type(screen.getByRole("searchbox", { name: "查找FBA款号或规格" }), "Brown");
  expect(within(table).getByRole("row", { name: /1112(?: · 查看| · 收起)? Brown .*5 5/ })).toBeVisible();
  expect(within(table).getByRole("row", { name: "筛选合计 5 5" })).toBeVisible();
  expect(screen.getByLabelText("FBA账面库存汇总")).toHaveTextContent("21");
  expect(within(table).queryByRole("button", { name: "查看SIM-S库存变动" })).not.toBeInTheDocument();
  await userEvent.clear(screen.getByRole("searchbox", { name: "查找FBA款号或规格" }));
  await userEvent.type(screen.getByRole("searchbox", { name: "查找FBA款号或规格" }), "no-such-style");
  expect(screen.getByText("没有匹配的款号或规格")).toBeVisible();
  expect(screen.queryByRole("table", { name: "FBA在库库存" })).not.toBeInTheDocument();
  await userEvent.clear(screen.getByRole("searchbox", { name: "查找FBA款号或规格" }));
  expect(screen.getByRole("row", { name: "本仓合计 16 5 21" })).toBeVisible();
  expect(api.write).not.toHaveBeenCalled();
});

it.each([true,false])("shows compact published daily results with write access %s", async canWrite => {
  const original = api.read.getMockImplementation()!;
  const daily = { report_count: 2, business_report_count: 1, return_report_count: 1, latest_report_on: "2026-11-04", return_units: "1", sales_units: "54", issues: [{ label: "第2行实物退回状态待核" }] };
  api.read.mockImplementation((path, options) => path.includes("fba/state") ? Promise.resolve({ ...state, daily: { "7": daily } }) : original(path, options));
  mount(<FbaWorkspace record={record} owner="1" canWrite={canWrite} refresh={0} reload={() => undefined} />,canWrite);
  expect(await screen.findByLabelText("FBA库存简览")).toBeVisible();
  expect(screen.queryByText("预计在库")).not.toBeInTheDocument();
  expect(screen.queryByText(/最近报告 2026-11-04/)).not.toBeInTheDocument();
  expect(screen.queryByText("待核 1 项")).not.toBeInTheDocument();
  expect(screen.queryByRole("heading",{name:"款色尺码库存"})).not.toBeInTheDocument();
  expect(screen.queryByText("点击数量，查看库存变动")).not.toBeInTheDocument();
  expect(screen.queryByText("库存说明（模拟）")).not.toBeInTheDocument();
  await openView("库存更新");
  expect(screen.getByText(/最近报告 2026-11-04/)).toBeVisible();
  expect(screen.queryByText("第2行实物退回状态待核")).not.toBeInTheDocument();
  await userEvent.click(screen.getByText("待处理 1 条 · 1 组", {selector:"summary"}));
  expect(screen.getByRole("table", {name:"日报待处理项目"})).toBeVisible();
  expect(screen.getByRole("link", { name: "查看已发布日报" })).toHaveAttribute("href", "/ledger/published-details");
  expect(screen.queryByRole("button", { name: "重试库存更新" }) !== null).toBe(canWrite);
  expect(api.write).not.toHaveBeenCalled();
});

it("resolves an uncertain daily sync from the original inventory command receipt", async () => {
  api.write.mockRejectedValueOnce(new Error("connection lost"));
  const original = api.read.getMockImplementation()!;
  api.read.mockImplementation((path, options) => path.startsWith("/api/production/commands/") ? Promise.resolve(state) : original(path, options));
  const saved = vi.fn();
  mount(<FbaWorkspace record={record} owner="1" canWrite refresh={0} reload={saved} />);
  await openView("库存更新");
  await userEvent.click(screen.getByRole("button", { name: "重试库存更新" }));
  await userEvent.click(await screen.findByRole("button", { name: "查询原操作结果" }));
  await waitFor(() => expect(saved).toHaveBeenCalledOnce());
  expect(await screen.findByText("库存同步已完成")).toBeVisible();
  expect(api.write).toHaveBeenCalledOnce();
  expect(screen.queryByRole("button", { name: "查询原操作结果" })).not.toBeInTheDocument();
});

it("keeps separate SKU balances and detail targets when display coordinates coincide", async () => {
  const original = api.read.getMockImplementation()!;
  api.read.mockImplementation(async (path, options) => {
    const value = await original(path, options);
    return path.includes("skus") ? { items: (value as { items: Record<string, unknown>[] }).items.map(sku => ({
      ...sku, standard_color: "Black", standard_size: "M",
    })) } : value;
  });
  mount(<FbaWorkspace record={record} owner="1" canWrite={false} refresh={0} reload={() => undefined} />, false);
  const first = await screen.findByRole("button", { name: "查看SIM-S库存变动" });
  const second = screen.getByRole("button", { name: "查看SIM-M库存变动" });
  expect(first).toHaveTextContent("16");
  expect(second).toHaveTextContent("5");
  expect(first.closest("td")).toBe(second.closest("td"));
  expect(screen.getByRole("row", { name: "本仓合计 21 21" })).toBeVisible();
  await userEvent.click(first);
  expect(screen.getByRole("region", { name: "SIM-S库存变动" })).toHaveTextContent("已出库3");
  await userEvent.click(second);
  expect(screen.queryByRole("region", { name: "SIM-S库存变动" })).not.toBeInTheDocument();
  expect(screen.getByRole("region", { name: "SIM-M库存变动" })).toHaveTextContent("暂无已确认变动");
  expect(api.write).not.toHaveBeenCalled();
});


function classifiedState():FbaState {
 return {...state,identities:state.identities.map(item=>item.sku_id==="11"?{...item,unsellable:"5"}:item),classification_summary:{"7":{scope_id:"7",revision:"2",ready:true,issue:null,totals:{WAREHOUSE_DAMAGED:"3",CUSTOMER_DAMAGED:"2",CARRIER_DAMAGED:"0",DEFECTIVE:"0",OTHER:"0",UNCLASSIFIED:"0"},pending:[],items:[
  {id:"origin:11:1:WAREHOUSE_DAMAGED",sku_id:"11",origin_event_id:"1",reason_code:"WAREHOUSE_DAMAGED",units:"3",business_date:"2026-11-06",occurred_at:"2026-11-06",actor_name:"QA",source_kind:"MANUAL",raw_disposition:"",note:"QA",operation_kind:"ASSIGN"},
  {id:"origin:11:2:CUSTOMER_DAMAGED",sku_id:"11",origin_event_id:"2",reason_code:"CUSTOMER_DAMAGED",units:"2",business_date:"2026-11-06",occurred_at:"2026-11-06",actor_name:"QA",source_kind:"REPORT",raw_disposition:"CUSTOMER_DAMAGED",note:"QA",operation_kind:"ASSIGN"},
 ]}}};
}
function mockClassification(value=classifiedState()) {
 const original=api.read.getMockImplementation()!;
 api.read.mockImplementation((path,options)=>path.includes("fba/state")?Promise.resolve(value):path.includes("fba/classifications")?Promise.resolve({items:value.classification_summary!["7"]!.items,total:2}):original(path,options));
}
it("retains row reason overrides and all entered quantities across searches and default changes",async()=>{
 mockClassification();mount(<FbaWorkspace record={record} owner="1" canWrite refresh={0} reload={()=>undefined}/>);
 await userEvent.click(await screen.findByRole("button",{name:"调整可售状态"}));const dialog=screen.getByRole("dialog");
 await userEvent.type(within(dialog).getByLabelText("SIM-S 本次标记数量"),"2");
 await userEvent.selectOptions(within(dialog).getByLabelText("SIM-S 不可售原因"),"CUSTOMER_DAMAGED");
 await userEvent.type(within(dialog).getByLabelText("查找要调整的商品"),"SIM-M");
 expect(within(dialog).getByText(/筛选外已填1项/)).toBeVisible();
 await userEvent.selectOptions(within(dialog).getByLabelText("统一原因"),"DEFECTIVE");
 await userEvent.type(within(dialog).getByLabelText("SIM-M 本次标记数量"),"1");
 await userEvent.click(within(dialog).getByRole("button",{name:"确认标记3件不可售"}));
 await waitFor(()=>expect(api.write).toHaveBeenCalledOnce());
 expect(api.write.mock.calls[0]?.[1]?.body).toMatchObject({lines:[{sku_id:"11",units:"2",reason_code:"CUSTOMER_DAMAGED"},{sku_id:"12",units:"1",reason_code:"DEFECTIVE"}]});
});
it("restores selected causes and blocks over-allocation within a cause",async()=>{
 mockClassification();mount(<FbaWorkspace record={record} owner="1" canWrite refresh={0} reload={()=>undefined}/>);
 await userEvent.click(await screen.findByRole("button",{name:"调整可售状态"}));const dialog=screen.getByRole("dialog");
 await userEvent.click(within(dialog).getByRole("button",{name:"恢复可售"}));
 const quantity=within(dialog).getByLabelText("SIM-S 客户损坏恢复数量");await userEvent.type(quantity,"3");
 expect(within(dialog).getByText("最多可恢复2件")).toBeVisible();expect(within(dialog).getByRole("button",{name:/确认恢复/})).toBeDisabled();
 await userEvent.clear(quantity);await userEvent.type(quantity,"1");await userEvent.click(within(dialog).getByRole("button",{name:"确认恢复1件可售"}));
 await waitFor(()=>expect(api.write).toHaveBeenCalledOnce());expect(api.write.mock.calls[0]?.[1]?.body).toMatchObject({lines:[{sku_id:"11",units:"1",reason_allocations:[{reason_code:"CUSTOMER_DAMAGED",units:"1"}]}]});
});
it("shows current classifications, keeps viewer read only and submits metadata-only corrections",async()=>{
 mockClassification();mount(<FbaWorkspace record={record} owner="1" canWrite refresh={0} reload={()=>undefined}/>);
 await userEvent.click(await screen.findByRole("button",{name:/仓库损坏\s*3/}));
 const table=await screen.findByRole("table",{name:"不可售分类明细"});
 await userEvent.click(within(table).getAllByRole("button",{name:"更正分类"})[0]!);
 const dialog=screen.getByRole("dialog",{name:"更正不可售原因"});
 await userEvent.selectOptions(within(dialog).getByLabelText("更正为"),"CUSTOMER_DAMAGED");
 await userEvent.type(within(dialog).getByLabelText("核对说明"),"已核对退货原件");
 await userEvent.click(within(dialog).getByRole("button",{name:"保存分类"}));
 await waitFor(()=>expect(api.write).toHaveBeenCalledOnce());expect(api.write.mock.calls[0]?.[0]).toBe("/api/production/fba/commands/classification-correct");expect(api.write.mock.calls[0]?.[1]?.body).toMatchObject({sku_id:"11",origin_event_id:"1",from_reason:"WAREHOUSE_DAMAGED",reason_code:"CUSTOMER_DAMAGED",units:"3",expected_revision:"2"});
});
it("requires a note for other causes and retains input on validation errors",async()=>{
 mockClassification();mount(<FbaWorkspace record={record} owner="1" canWrite refresh={0} reload={()=>undefined}/>);
 await userEvent.click(await screen.findByRole("button",{name:"调整可售状态"}));const dialog=screen.getByRole("dialog");
 await userEvent.selectOptions(within(dialog).getByLabelText("统一原因"),"OTHER");await userEvent.type(within(dialog).getByLabelText("SIM-S 本次标记数量"),"1");
 await userEvent.click(within(dialog).getByRole("button",{name:"确认标记1件不可售"}));expect(api.write).not.toHaveBeenCalled();expect(within(dialog).getByText("请填写其他原因说明")).toBeVisible();expect(within(dialog).getByLabelText("SIM-S 本次标记数量")).toHaveValue("1");
});
it("lets viewers read cause details without exposing correction or quality writes",async()=>{
 mockClassification();mount(<FbaWorkspace record={record} owner="1" canWrite={false} refresh={0} reload={()=>undefined}/>,false);
 await userEvent.click(await screen.findByRole("button",{name:/仓库损坏\s*3/}));await screen.findByRole("table",{name:"不可售分类明细"});
 expect(screen.queryByRole("button",{name:"更正分类"})).not.toBeInTheDocument();expect(screen.queryByRole("button",{name:"调整可售状态"})).not.toBeInTheDocument();expect(api.write).not.toHaveBeenCalled();
});


it("keeps report sales on their report date and directs corrections to the report", async () => {
 const reportState: FbaState = {...state, actions:[{...state.actions[0]!, id:"99", occurred_at:"2026-10-30T06:59:59Z", payload:{reason:"经营日报发布后自动扣减销售数量", report_sales_key:"report-sales:2026-10-29:11", report_sales:{business_date:"2026-10-29"}, lines:[{sku_id:"11",units:"1"}]}}]};
 api.read.mockImplementation((path:string)=>Promise.resolve(path.includes("fba/state")?reportState:{items:[]}));
 mount(<FbaWorkspace record={record} owner="1" canWrite refresh={0} reload={()=>undefined}/>);
 await openView("操作记录");
 await userEvent.click(screen.getByText("查看或撤销收发记录",{selector:"summary"}));
 expect(screen.getByText("2026-10-29 · 销售出库 · 已登记",{selector:"summary"})).toBeVisible();
 expect(screen.queryByRole("button",{name:"撤销这条记录"})).not.toBeInTheDocument();
 expect(api.write).not.toHaveBeenCalled();
});

it("hides zero stock rows without losing later nonzero or unknown stock updates", () => {
 const base = state.inventory_view!["7"]!;
 const zero = { sku_id: "99", style_id: "9", seller_sku: "ZERO-M", on_hand: "0", available: "0", received: "0", fulfilled: "0", returned: "0" };
 const items = [{sku_id:"11",style_id:"4",style_code:"1112",standard_color:"Black",standard_size:"S",status:"active" as const,catalog_version:"1:1",label:"SIM-S",code:"SIM-S"}, {sku_id:"12",style_id:"4",style_code:"1112",standard_color:"White",standard_size:"M",status:"active" as const,catalog_version:"1:1",label:"SIM-M",code:"SIM-M"}, {sku_id:"99",style_id:"9",style_code:"9999",standard_color:"Navy",standard_size:"M",status:"active" as const,catalog_version:"1:1",label:"ZERO-M",code:"ZERO-M"}];
 const view = { ...base, groups: [{...base.groups[0]!, items:[base.groups[0]!.items[0]!, {...base.groups[0]!.items[1]!,on_hand:"0",available:"0"}]}, {style_id:"9",on_hand:"0",items:[zero]}] };
 const tree = (quantity: string | null) => <MemoryRouter><FbaInventoryOverview scope={state.scopes[0]!} catalog={items} view={{...view,groups:[view.groups[0]!,{...view.groups[1]!,items:[{...zero,on_hand:quantity}]}]}}/></MemoryRouter>;
 const mounted=render(tree("0"));
 expect(screen.queryByRole('button',{name:/^9999 · (?:查看|收起)$/})).not.toBeInTheDocument();
 expect(within(screen.getByRole('table',{name:'FBA在库库存'})).queryByText('White')).not.toBeInTheDocument();
 expect(within(screen.getByRole('table',{name:'FBA在库库存'})).queryByText('0',{exact:true})).not.toBeInTheDocument();
 mounted.rerender(tree("5"));expect(screen.getByRole('button',{name:/^9999 · (?:查看|收起)$/})).toBeVisible();
 expect(screen.getByRole('button',{name:'查看ZERO-M库存变动'})).toHaveTextContent('5');
 mounted.rerender(tree("0"));expect(screen.queryByRole('button',{name:/^9999 · (?:查看|收起)$/})).not.toBeInTheDocument();
 mounted.rerender(tree(null));expect(screen.getByRole('button',{name:/^9999 · (?:查看|收起)$/})).toBeVisible();
 expect(screen.getByRole('button',{name:'查看ZERO-M库存变动'})).toHaveTextContent('待核');
});


it.each([false, true])("submits a hidden zero balance as an absolute count and recovers unknown results %s", async uncertain => {
  const saved = vi.fn(), close = vi.fn(), guard = vi.fn();
  const countState = { ...state, stock: { items: [{ ...state.stock.items[0]!, on_hand_units: "0", qualified_units: "0", revision: "7" }] } };
  if (uncertain) { api.write.mockRejectedValueOnce(new Error("SIM connection lost")); api.read.mockResolvedValue(countState); }
  mount(<FbaStocktake open close={close} saved={saved} onGuard={guard} data={countState} scope={state.scopes[0]!} catalog={[{sku_id:"11",style_id:"4",code:"SIM-S",label:"SIM S",status:"active",catalog_version:"1:1"}]} />);
  await userEvent.selectOptions(screen.getByLabelText("商品规格"), "11");
  const input = screen.getByLabelText("盘点后合格品数量");
  expect(input).toHaveValue("0");
  await userEvent.clear(input); await userEvent.type(input, "5");
  await userEvent.type(screen.getByLabelText("调整原因"), "SIMULATED zero to five");
  await userEvent.click(screen.getByRole("button", {name:"确认调整"}));
  await waitFor(() => expect(api.write).toHaveBeenCalledOnce());
  expect(api.write.mock.calls[0]?.[0]).toBe("/api/production/fba/commands/stocktake");
  expect(api.write.mock.calls[0]?.[1]?.body).toMatchObject({ scope_id:"7", expected_revision:"2", lines:[{sku_id:"11",units:"5",balance_revision:"7"}],reason:"SIMULATED zero to five" });
  if (uncertain) {
    expect(input).toHaveValue("5"); expect(input).toBeDisabled();
    const key = api.write.mock.calls[0]?.[1]?.operationKey;
    await userEvent.click(await screen.findByRole("button", {name:"查询原操作结果"}));
    expect(api.read).toHaveBeenCalledWith(`/api/production/commands/${key}`);
    expect(api.write).toHaveBeenCalledOnce();
  }
  await waitFor(() => expect(saved).toHaveBeenCalledOnce());
  expect(close).toHaveBeenCalledOnce();
});

it("retains a count target across a balance change and requires explicit reconfirmation", async () => {
  const guard=vi.fn();
  function UpdatedCount() {
    const [revision,setRevision]=useState("7");
    const value={...state,stock:{items:[{...state.stock.items[0]!,qualified_units:revision==="7"?"0":"2",revision}]}};
    return <><button onClick={()=>setRevision("8")}>SIM external update</button><FbaStocktake open close={()=>undefined} saved={()=>undefined} onGuard={guard} data={value} scope={state.scopes[0]!} catalog={[{sku_id:"11",style_id:"4",code:"SIM-S",label:"SIM S",status:"active",catalog_version:"1:1"}]} /></>;
  }
  mount(<UpdatedCount />);
  await userEvent.selectOptions(screen.getByLabelText("商品规格"),"11");
  await userEvent.clear(screen.getByLabelText("盘点后合格品数量"));
  await userEvent.type(screen.getByLabelText("盘点后合格品数量"),"5");
  await userEvent.type(screen.getByLabelText("调整原因"),"SIM count");
  // Simulate the refresh delivered while the modal remains mounted.
  fireEvent.click(screen.getByText("SIM external update"));
  await waitFor(()=>expect(screen.getByRole("button",{name:"确认调整"})).toBeDisabled());
  expect(screen.getByLabelText("盘点后合格品数量")).toHaveValue("5");
  await userEvent.click(screen.getByRole("button",{name:"核对最新库存"}));
  await userEvent.click(screen.getByRole("button",{name:"确认调整"}));
  await waitFor(()=>expect(api.write).toHaveBeenCalledOnce());
  expect(api.write.mock.calls[0]?.[1]?.body).toMatchObject({lines:[{sku_id:"11",units:"5",balance_revision:"8"}]});
});


it("distinguishes an existing zero size from an absent catalog size and keeps style totals unshaded", async () => {
 const base = state.inventory_view!["7"]!;
 const catalog=[{sku_id:"11",style_id:"4",style_code:"1112",standard_color:"Black",standard_size:"S",status:"active",catalog_version:"1:1",label:"SIM S",code:"SIM-S"},{sku_id:"12",style_id:"4",style_code:"1112",standard_color:"Black",standard_size:"M",status:"active",catalog_version:"1:1",label:"SIM M",code:"SIM-M"},{sku_id:"99",style_id:"4",style_code:"1112",standard_color:"White",standard_size:"L",status:"active",catalog_version:"1:1",label:"SIM L",code:"SIM-L"}];
 const view={...base,groups:[{...base.groups[0]!,items:[base.groups[0]!.items[0]!,{...base.groups[0]!.items[1]!,on_hand:"0",available:"0"}]}]};
 render(<MemoryRouter><FbaInventoryOverview scope={state.scopes[0]!} catalog={catalog} view={view}/></MemoryRouter>);
 const row=screen.getByText("Black",{exact:true}).closest("tr")!;
 const cells=within(row).getAllByRole("cell");
 expect(cells[2]).toHaveTextContent(""); expect(cells[2]).not.toHaveAttribute("title");
 expect(cells[3]).toHaveAttribute("title","未建档此尺码");
 expect(cells[3]).toHaveTextContent("");
 expect(screen.queryByRole("button",{name:"查看SIM-M库存变动"})).not.toBeInTheDocument();
 await userEvent.click(screen.getByRole("button",{name:/^1112 · (?:查看|收起)$/}));
 expect(screen.queryByTitle("未建档此尺码")).not.toBeInTheDocument();
 expect(screen.getByRole("row",{name:/本仓合计/}).querySelector('[title="未建档此尺码"]')).toBeNull();
});


it("groups daily issues, searches and pages without mounting every original record", async () => {
  const issues=Array.from({length:45},(_,index)=>({code:"return_status",message:"实物退回状态待核",seller_sku:`SKU-${String(index%23).padStart(2,"0")}`,sku_id:String(index%23),label:`原始记录${index}`,source_row:index+2}));
  const original=api.read.getMockImplementation()!;
  api.read.mockImplementation((path,options)=>path.includes("fba/state")?Promise.resolve({...state,daily:{"7":{report_count:1,sales_units:"3",latest_report_on:"2026-11-04",issues}}}):original(path,options));
  mount(<FbaWorkspace record={record} owner="1" canWrite={false} refresh={0} reload={()=>undefined}/>,false);
  await openView("库存更新");
  expect(screen.queryByText("原始记录0")).not.toBeInTheDocument();
  await userEvent.click(screen.getByText("待处理 45 条 · 23 组",{selector:"summary"}));
  const table=screen.getByRole("table",{name:"日报待处理项目"});
  expect(within(table).getAllByRole("row")).toHaveLength(21);
  await userEvent.click(within(table).getAllByText("记录",{selector:"summary"})[0]!);
  expect(await screen.findByText("原始记录0")).toBeVisible();
  expect(screen.getByText("原始记录23")).toBeVisible();
  await userEvent.click(screen.getByRole("button",{name:"下一页"}));
  expect(within(table).getAllByRole("row")).toHaveLength(4);
  await userEvent.type(screen.getByRole("searchbox",{name:"查找待处理SKU或问题"}),"SKU-22");
  expect(within(table).getAllByRole("row")).toHaveLength(2);
  expect(within(table).getByText("SKU-22")).toBeVisible();
  expect(screen.queryByRole("button",{name:"重试库存更新"})).not.toBeInTheDocument();
  expect(api.write).not.toHaveBeenCalled();
});

it("opens real snapshot without marking it simulated",async()=>{
 const {FbaOpening}=await import("./FbaOpening");
 const original=api.read.getMockImplementation()!;api.read.mockImplementation((path,options)=>path.includes("catalog-products")?Promise.resolve({identities:[{sku_id:"11",seller_sku:"SKU-A",asin:"B000000001",fnsku:"X000000001",store:"SIM store"}],issues:[],store:"SIM store",catalog_version:"1:1"}):original(path,options));
 const saved=vi.fn();mount(<FbaOpening record={record} catalog={[]} sourceId={3} sourceName="SIM store" saved={saved}/>);
 await screen.findByText(/已自动带入/);await userEvent.click(screen.getByRole("button",{name:"导入库存快照"}));
 api.write.mockResolvedValueOnce({identities:[{sku_id:"11"}],source_id:"a".repeat(64),report_source_scope_id:"3",snapshot_on:"2026-11-04",available_units:"10",transit_units:"7",excluded_rows:[{source_row:"9",seller_sku:"OUTSIDE",reason:"不属于本店铺"}]});
 await userEvent.upload(screen.getByLabelText("亚马逊物流库存CSV"),new File(["original report"],"inventory.csv",{type:"text/csv"}));await userEvent.click(screen.getByRole("button",{name:"读取库存快照"}));await screen.findByText("可售 10");await userEvent.click(screen.getByText("1 条待核"));expect(screen.getByRole("table",{name:"库存快照待核记录"})).toHaveTextContent("OUTSIDE");
 await userEvent.type(screen.getByLabelText(/^货主编号/),"1");await userEvent.type(screen.getByLabelText(/^货主名称/),"Owner");await userEvent.click(screen.getByRole("checkbox",{name:"按快照登记，未列规格按0计"}));await userEvent.click(screen.getByRole("button",{name:"确认快照并启用"}));
 await waitFor(()=>expect(api.write.mock.calls.length).toBe(2));expect(api.write.mock.calls[1]?.[1]?.body).toMatchObject({opening_mode:"snapshot",simulated:false,cutoff_on:"2026-11-04",missing_skus_zero_confirmed:true,snapshot_source:{source_id:"a".repeat(64),report_source_scope_id:"3"},identity_mode:"catalog"});
});
