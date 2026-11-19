import { render, screen, fireEvent, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter, useLocation } from "react-router-dom";
import { beforeEach, expect, it, vi } from "vitest";
import { AuthzGenerationProvider } from "../../app/AuthzGenerationContext";
import { WarehouseTransit } from "./WarehouseTransit";
const api=vi.hoisted(()=>({read:vi.fn<(path:string)=>Promise<unknown>>()}));
vi.mock("../../api/client",async original=>({...await original<typeof import("../../api/client")>(),requestApi:api.read}));
beforeEach(()=>{api.read.mockReset();api.read.mockResolvedValue({items:[],page:1,page_size:20,total:0,as_of:"2026-10-29T00:00:00Z"});});
function CurrentLocation(){return <output aria-label="当前运输URL">{useLocation().search}</output>;}
function mount(query:string,owner:string,canWrite=false){render(<MemoryRouter initialEntries={[`/production/warehouses/2?tab=transit${query}`]}><AuthzGenerationProvider boundary={{principalId:1,roles:[canWrite?"data_manager":"viewer"],siteId:1,siteConfigVersionId:1}} onRevoked={()=>undefined}><WarehouseTransit record={{id:"2",name:"SIM FBA",type:"FBA",status:"ACTIVE",revision:"1",region:"",address:"",operator:"",contact:"",phone:"",country:"US",notes:"",timezone:"",seller_account:"",marketplace:"",factory_ids:[]}} owner={owner} canWrite={canWrite} refresh={0}/><CurrentLocation/></AuthzGenerationProvider></MemoryRouter>);}
it("shows report-backed opening transit without inventing shipment batches",async()=>{
  api.read.mockImplementation(path=>Promise.resolve(path.includes("/skus?")?{items:[]}:{items:[],page:1,page_size:20,total:0,as_of:"2026-11-08",opening_balances:[{sku_id:"10",sku_label:"SKU-A",units:"11",snapshot_on:"2026-11-04",source_filename:"source.csv"},{sku_id:"20",sku_label:"SKU-B",units:"140",snapshot_on:"2026-11-04",source_filename:"source.csv"}]}));
  mount("","1");
  const table=await screen.findByRole("table",{name:"期初在途明细"});
  expect(within(table).getByRole("row",{name:"合计 151"})).toBeVisible();
  expect(screen.queryByText("当前范围没有匹配批次")).not.toBeInTheDocument();
  expect(screen.queryByRole("button",{name:"开始到仓核验"})).not.toBeInTheDocument();
});
it("omits absent optional numeric filters so an unfiltered warehouse request passes API validation",async()=>{
  mount("","");await screen.findByText("当前范围没有匹配批次");const path=api.read.mock.calls[0]![0];const query=new URL(path,"http://localhost").searchParams;expect(query.has("sku_id")).toBe(false);expect(query.has("owner_id")).toBe(false);expect(query.get("warehouse_id")).toBe("2");expect(screen.queryByRole("link",{name:"登记仓间发运"})).not.toBeInTheDocument();
});
it("preserves exact SKU and owner when following a cross-warehouse query",async()=>{
  mount("&sku_id=3","1");await screen.findByText("当前范围没有匹配批次");const query=new URL(api.read.mock.calls[0]![0],"http://localhost").searchParams;expect(query.get("sku_id")).toBe("3");expect(query.get("owner_id")).toBe("1");expect(screen.getByText("当前按稳定SKU 3筛选")).toBeVisible();
});

it("displays the official SKU by stable identity while keeping the shipment source unchanged", async () => {
  const source = {id:"21",sku_id:"9",sku_label:"1112 · old-seller-code · Black / S",actual_units:"1",received_units:"0",unreceived_units:"1",bindings:[],allocations:[]};
  api.read.mockImplementation(path => Promise.resolve(path.includes("/skus?") ? {items:[{sku_id:"9",code:"1112-Black-S",label:"old label"}]} : {items:[{id:"5",business_number:"SIM",system_number:"SH-SIM",owner_id:"1",source_name:"普通仓",destination_name:"FBA仓",shipped_units:"1",received_units:"0",unreceived_units:"1",settled_units:"0",stage:"UNREGISTERED",receipt_dates:[],duration_hours:null,transport:{record:null},sources:[source]}],page:1,page_size:20,total:1,as_of:"2026-11-02"}));
  mount("","1");
  expect(await screen.findByRole("rowheader", {name:"1112-Black-S"})).toBeVisible();
  expect(screen.queryByRole("rowheader", {name:/old-seller-code/})).not.toBeInTheDocument();
  expect(source.sku_label).toBe("1112 · old-seller-code · Black / S");
});

const lastTransitQuery=()=>new URL(api.read.mock.calls.filter(([path])=>path.includes("warehouse-transit")).at(-1)![0],"http://localhost").searchParams;
it("searches automatically without an extra button and preserves scope while resetting pagination",async()=>{
 mount("&transit_page=3&fba_view=balance&sku_id=3","1");await screen.findByText("当前范围没有匹配批次");expect(screen.queryByRole("button",{name:"查找运输"})).not.toBeInTheDocument();const input=screen.getByRole("searchbox",{name:"查找批次或SKU"});await userEvent.type(input,"1112");expect(screen.getByRole("button",{name:"导出当前页"})).toBeDisabled();await waitFor(()=>expect(lastTransitQuery().get("q")).toBe("1112"));expect(lastTransitQuery().get("page")).toBe("1");expect(lastTransitQuery().get("sku_id")).toBe("3");expect(lastTransitQuery().get("owner_id")).toBe("1");expect(screen.getByLabelText("当前运输URL")).toHaveTextContent("fba_view=balance");await userEvent.selectOptions(screen.getByRole("combobox",{name:"最新物流节点筛选"}),"EXCEPTION");await waitFor(()=>expect(lastTransitQuery().get("node")).toBe("EXCEPTION"));await userEvent.clear(input);await waitFor(()=>expect(lastTransitQuery().get("q")).toBe(""));expect(lastTransitQuery().get("node")).toBe("EXCEPTION");
});
it("waits for Chinese composition to finish before applying a search",async()=>{
 mount("", "1");await screen.findByText("当前范围没有匹配批次");const input=screen.getByRole("searchbox",{name:"查找批次或SKU"});fireEvent.compositionStart(input);fireEvent.change(input,{target:{value:"工厂"}});fireEvent.submit(screen.getByRole("search",{name:"查找运输批次"}));await new Promise(resolve=>setTimeout(resolve,350));expect(lastTransitQuery().get("q")).toBe("");fireEvent.compositionEnd(input);await waitFor(()=>expect(lastTransitQuery().get("q")).toBe("工厂"));
});
it("consolidates batch links and only presents receipt verification for unfinished batches",async()=>{
 const batch={id:"5",business_number:"SIM-OPEN",system_number:"SH-SIM",owner_id:"1",source_name:"普通仓",destination_name:"FBA仓",destination_kind:"FBA",shipped_units:"1",received_units:"0",unreceived_units:"1",settled_units:"0",stage:"UNREGISTERED",receipt_dates:[],duration_hours:null,transport:{record:null},sources:[]};api.read.mockImplementation(path=>Promise.resolve(path.includes("/skus?")?{items:[]}:{items:[batch,{...batch,id:"6",business_number:"SIM-DONE",stage:"RECEIVED"}],total:2,page:1,page_size:20,as_of:"2026-11-03"}));mount("","1",true);const open=await screen.findByRole("article",{name:"运输批次 SIM-OPEN"});expect(within(open).getByRole("button",{name:"开始到仓核验"})).toBeEnabled();const done=screen.getByRole("article",{name:"运输批次 SIM-DONE"});expect(within(done).queryByRole("button",{name:"开始到仓核验"})).not.toBeInTheDocument();expect(screen.queryByRole("button",{name:"下一页"})).not.toBeInTheDocument();await userEvent.click(within(open).getByRole("button",{name:"更多"}));expect(screen.getByRole("menuitem",{name:"查看原出货"})).toHaveAttribute("href","/production/shipments/5");expect(screen.getByRole("menuitem",{name:"运输时间与更正"})).toHaveAttribute("href","/production/shipments/5#transport");
});
