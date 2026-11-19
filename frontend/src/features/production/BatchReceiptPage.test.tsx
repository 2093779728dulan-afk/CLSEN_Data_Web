import {render,screen,waitFor} from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import {createMemoryRouter,RouterProvider} from "react-router-dom";
import {afterEach,beforeEach,it,expect,vi} from "vitest";
import {AuthzGenerationProvider} from "../../app/AuthzGenerationContext";
import {BatchReceiptPage} from "./BatchReceiptPage";
const api=vi.hoisted(()=>({read:vi.fn(),write:vi.fn()}));
vi.mock("../../api/client",async original=>({...await original<typeof import("../../api/client")>(),requestApi:api.read,writeApi:api.write}));
afterEach(()=>vi.unstubAllGlobals());
let mixed=false;
const orders=()=>["1","2"].map(id=>({id,business_number:`PO${id}`,system_number:`PO${id}`,revision:"3",status:"CONFIRMED",receipt_warehouse_id:mixed&&id==="2"?"2":"1",receipt_owner_id:"1",expected_units:"20",received_units:"20",lines:[{id:`${id}1`,sku_id:id,sku_label:`款${id}`,expected_units:"20",received_units:"20",actual_units:"0",difference_units:"20"}]}));
beforeEach(()=>{const NativeRequest=globalThis.Request;vi.stubGlobal("Request",class extends NativeRequest {constructor(input:RequestInfo|URL,init?:RequestInit){const {signal,...options}=init||{};super(input,options);if(signal)Object.defineProperty(this,"signal",{value:signal});}});mixed=false;api.read.mockReset();api.write.mockReset();api.read.mockImplementation((path:string)=>{
 if(path.includes("receipt-batches/sources"))return Promise.resolve({id:"receipt-batch",revision:"1:3,2:3",status:"CONFIRMED",receipt_batch:true,lines:orders().flatMap(o=>o.lines.map(l=>({...l,order_label:o.business_number})))});
 if(path.startsWith("/api/production/orders?"))return Promise.resolve({items:orders(),total:2,page:1,page_size:20});
 if(path.includes("availability"))return Promise.resolve({writes_enabled:true,items:[],scopes:["1","2"].map(id=>({warehouse_id:id,owner_id:"1",warehouse_name:`成品仓${id}`,warehouse_type:"OWN",warehouse_status:"ACTIVE"}))});
 return Promise.resolve({items:[],total:0});
});});
function mount(){const router=createMemoryRouter([{path:"/production/orders/receipts/new",element:<BatchReceiptPage canWrite/>},{path:"*",element:<p>来源页面</p>}],{initialEntries:[`/production/orders/receipts/new?return_to=${encodeURIComponent("/production/overview?chain_progress=all")}`]});render(<AuthzGenerationProvider boundary={{principalId:1,roles:["admin"],siteId:1,siteConfigVersionId:1}} onRevoked={()=>undefined}><RouterProvider router={router}/></AuthzGenerationProvider>);return router;}
async function choose(){await userEvent.click(await screen.findByLabelText("选择 PO1"));await userEvent.click(screen.getByLabelText("选择 PO2"));await userEvent.click(screen.getByRole("button",{name:"开始本批入库"}));}
it("prefills the shared explicit active plan scope, keeps it editable and returns to the source",async()=>{
 const router=mount();await choose();expect(await screen.findByRole("heading",{name:"2 笔订单"})).toBeVisible();expect(screen.getByText("PO1",{exact:true})).not.toBeVisible();await userEvent.click(screen.getByText("查看完整订单编号"));expect(screen.getByText("PO1",{exact:true})).toBeVisible();expect(screen.getByText("PO2",{exact:true})).toBeVisible();const scope=await screen.findByRole("combobox",{name:"本次实收入库仓库"});expect(scope).toHaveValue("1:1");expect(router.state.location.search).toContain("warehouse_id=1");await userEvent.selectOptions(scope,"2:1");expect(scope).toHaveValue("2:1");await userEvent.click(screen.getByRole("button",{name:"取消"}));await screen.findByRole("button",{name:"放弃并离开"}).then(button=>userEvent.click(button));await waitFor(()=>expect(router.state.location.pathname+router.state.location.search).toBe("/production/overview?chain_progress=all"));expect(api.write).not.toHaveBeenCalled();
});
it("requires a scope decision for mixed planned warehouses instead of selecting the only name match",async()=>{
 mixed=true;mount();await choose();expect(await screen.findByRole("combobox",{name:"本次实收入库仓库"})).toHaveValue("");expect(api.write).not.toHaveBeenCalled();
});
