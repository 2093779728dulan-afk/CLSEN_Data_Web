import {afterEach,beforeEach,expect,it,vi} from "vitest";
import {cleanup,render,screen,waitFor} from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import {createMemoryRouter,RouterProvider} from "react-router-dom";
import {AuthzGenerationProvider} from "../../app/AuthzGenerationContext";
import {DestinationReceiptDialog} from "./DestinationReceiptDialog";
const api=vi.hoisted(()=>({read:vi.fn<(path:string)=>Promise<unknown>>(),write:vi.fn<(path:string,options:{body:Record<string,unknown>})=>Promise<Record<string,unknown>>>()}));
vi.mock("../../api/client",async original=>({...await original<typeof import("../../api/client")>(),requestApi:api.read,writeApi:api.write}));
beforeEach(()=>{
 api.read.mockReset();api.write.mockReset();
 api.read.mockImplementation(async(path:string)=>{
  await Promise.resolve();
  if(path==="/api/production/shipments/4")return {id:"4",system_number:"SIM-4",business_number:"SIM-GOODS",revision:"2",status:"CONFIRMED",dispatch_purpose:"WAREHOUSE_DISPATCH",destination_id:"2",owner_id:"1",cartons:null,sources:[{id:"12",sku_id:"9",sku_label:"1112-Black-S",actual_units:"4",allocations:[]}]};
  if(path.includes("destination-state"))return {shipment:{id:"4",revision:"2",destination_id:"2"},bindings:[{id:"7",source_line_id:"12",allocation_id:null,carton_id:"",sku_id:"9",sku_label:"1112-Black-S",catalog_version:"V2",identity_status:"active",units:"4",received_units:"1",settled_units:"0"}],receipts:[],settlements:[]};
  if(path.endsWith("/availability"))return {writes_enabled:true,scopes:[{warehouse_id:"2",owner_id:"1",warehouse_name:"目的仓",owner_name:"自有"}],items:[]};
  throw Error(path);
 });
 api.write.mockResolvedValue({id:"30",revision:"1",status:"DRAFT",warehouse_id:"2",owner_id:"1",lines:[]});
});
afterEach(cleanup);
it("opens batch receipt directly at goods quantities without asking for cartons",async()=>{
 render(<RouterProvider router={createMemoryRouter([{path:"/",element:<AuthzGenerationProvider boundary={{principalId:1,roles:["admin"],siteId:1,siteConfigVersionId:1}} onRevoked={()=>undefined}><DestinationReceiptDialog shipmentId="4" warehouseId="2" ownerId="1" close={()=>undefined} saved={()=>undefined}/></AuthzGenerationProvider>}])}/>);
 const table=await screen.findByRole("table",{name:"本次实收明细"});
 expect(table).toHaveTextContent("1112-Black-S · 发出4 / 已收1 / 已结案0");
 expect(screen.queryByRole("columnheader",{name:/箱/})).not.toBeInTheDocument();
 expect(screen.queryByRole("button",{name:"保存来源对应"})).not.toBeInTheDocument();
 expect(api.write).not.toHaveBeenCalled();
 await userEvent.clear(screen.getByLabelText("7 qualified_units"));await userEvent.type(screen.getByLabelText("7 qualified_units"),"3");
 await userEvent.click(screen.getByRole("button",{name:"下一步"}));
 await userEvent.type(screen.getByLabelText("实际接收日期"),"2026-11-02");
 await userEvent.type(screen.getByLabelText("依据与差异说明"),"SIM partial batch arrival");
 await userEvent.click(screen.getByRole("button",{name:"下一步"}));
 await userEvent.click(screen.getByRole("button",{name:"保存草稿"}));
 await waitFor(()=>expect(api.write).toHaveBeenCalledTimes(1));
 expect(api.write.mock.calls[0]?.[1].body).toMatchObject({shipment_id:"4",warehouse_id:"2",owner_id:"1",lines:[{binding_id:"7",sku_id:"9",qualified_units:"3"}]});
});
