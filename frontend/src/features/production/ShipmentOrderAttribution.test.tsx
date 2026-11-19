import { useState } from "react";
import { cleanup, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import { ShipmentOrderAttribution } from "./ShipmentOrderAttribution";
import type { Document, Source, Sku } from "./types";

const api = vi.hoisted(() => ({read:vi.fn()}));
vi.mock("../../api/client", () => ({requestApi:api.read}));
const order = {id:"1",business_number:"PO-TEST-1",status:"CONFIRMED",receipt_warehouse_id:"3",receipt_owner_id:"1",destination_id:"7",lines:[{id:"101",sku_id:"11",tracking_state:"OPEN",expected_units:"20",actual_units:"0"}]} as Document;
const catalog = [{sku_id:"11",code:"1112-Black-S"}] as Sku[];
const search = vi.fn();
function Harness({autoFill=true,locked=false,initialSources,originalSources}:{autoFill?:boolean;locked?:boolean;initialSources?:Source[];originalSources?:Source[]}) {
 const [sources,setSources]=useState<Source[]>(initialSources || [{sku_id:"11",actual_units:"20",allocations:[]}]);
 const [visible,setVisible]=useState(true);
 return <><button onClick={()=>setSources(rows=>rows.map(row=>({...row,actual_units:"12"})))}>改为12件</button><button onClick={()=>setVisible(value=>!value)}>切换步骤</button>{visible&&<ShipmentOrderAttribution compact confirmedSources={originalSources} autoFill={autoFill} sources={sources} shipment={{warehouse_id:"3",owner_id:"1",destination_id:"7"}} catalog={catalog} locked={locked} change={(index,patch)=>setSources(rows=>rows.map((row,number)=>number===index?{...row,...patch}:row))} search={search}/>}</>;
}
beforeEach(()=>{api.read.mockReset();search.mockReset();api.read.mockResolvedValue({items:[order],total:1,page_size:100});});
afterEach(cleanup);

it("automatically selects the unique order and keeps its quantity aligned until edited",async()=>{
 render(<Harness/>);
 await waitFor(()=>expect(screen.getByLabelText("商品1来源订单1")).toHaveValue("101"));
 expect(screen.queryByRole("button",{name:"填入唯一订单候选"})).not.toBeInTheDocument();
 const table=screen.getByRole("table",{name:"出货订单归属汇总"});
 expect(within(table).getAllByRole("button")).toHaveLength(1);
 expect(within(table).getByRole("button",{name:"移除商品1来源订单1"})).toBeEnabled();
 await userEvent.click(screen.getByRole("button",{name:"改为12件"}));
 await waitFor(()=>expect(screen.getByLabelText("商品1分配数量1")).toHaveValue("12"));
 await userEvent.clear(screen.getByLabelText("商品1分配数量1"));await userEvent.type(screen.getByLabelText("商品1分配数量1"),"10");
 expect(screen.getByLabelText("商品1分配数量1")).toHaveValue("10");
});

it("keeps a removed automatic association empty when returning to the step",async()=>{
 render(<Harness/>);
 await waitFor(()=>expect(screen.getByLabelText("商品1来源订单1")).toHaveValue("101"));
 await userEvent.click(screen.getByRole("button",{name:"移除商品1来源订单1"}));
 expect(screen.getByLabelText("商品1来源订单1")).toHaveValue("");
 await userEvent.click(screen.getByRole("button",{name:"切换步骤"}));await userEvent.click(screen.getByRole("button",{name:"切换步骤"}));
 await waitFor(()=>expect(api.read).toHaveBeenCalledTimes(2));
 expect(screen.getByLabelText("商品1来源订单1")).toHaveValue("");
});

it("leaves ambiguous orders for explicit selection and retains splitting in the selector",async()=>{
 api.read.mockResolvedValue({items:[order,{...order,id:"2",business_number:"PO-TEST-2",lines:[{...order.lines![0]!,id:"102"}]}],total:2,page_size:100});
 render(<Harness/>);await screen.findByRole("option",{name:/PO-TEST-2/});
 const select=screen.getByLabelText("商品1来源订单1");expect(select).toHaveValue("");
 await userEvent.selectOptions(select,"102");
 await userEvent.selectOptions(select,"__split__");
 expect(screen.getByLabelText("商品1来源订单1")).toHaveValue("102");
 expect(screen.getByLabelText("商品1来源订单2")).toHaveValue("");
 expect(within(screen.getByRole("table")).getAllByRole("button")).toHaveLength(2);
 await userEvent.selectOptions(screen.getByLabelText("商品1来源订单2"),"__search__");
 expect(search).toHaveBeenCalledWith(0,1);
});

it.each(["historical","locked","incomplete"])("does not automatically change %s input",async mode=>{
 if(mode==="incomplete")api.read.mockResolvedValue({items:[order],total:2,page_size:1});
 render(<Harness autoFill={mode!=="historical"} locked={mode==="locked"}/>);
 await screen.findAllByRole("option",{name:/PO-TEST-1/});
 expect(screen.getByLabelText("商品1来源订单1")).toHaveValue("");
});


it("prefers the sole outstanding order and keeps fully shipped orders behind an explicit choice",async()=>{
 const spent={...order,id:"2",business_number:"OLD-FULLY-SHIPPED",lines:[{...order.lines![0]!,id:"102",expected_units:"2",actual_units:"2"}]};
 api.read.mockResolvedValue({items:[spent,order],total:2,page_size:100});render(<Harness/>);
 await waitFor(()=>expect(screen.getByLabelText("商品1来源订单1")).toHaveValue("101"));
 expect(screen.queryByRole("option",{name:/OLD-FULLY-SHIPPED/})).not.toBeInTheDocument();
 await userEvent.click(screen.getByRole("button",{name:"显示已发完订单"}));
 expect(screen.getByRole("option",{name:/OLD-FULLY-SHIPPED/})).toBeInTheDocument();
 await userEvent.selectOptions(screen.getByLabelText("商品1来源订单1"),"102");
 expect(screen.getByLabelText("商品1来源订单1")).toHaveValue("102");
});
it("does not auto-attribute two carton rows whose combined quantity exceeds the same order remainder",async()=>{
 api.read.mockResolvedValue({items:[{...order,lines:[{...order.lines![0]!,expected_units:"12"}]}],total:1,page_size:100});
 render(<Harness initialSources={[{sku_id:"11",actual_units:"8",allocations:[]},{sku_id:"11",actual_units:"8",allocations:[]}]}/>);
 await screen.findAllByRole("option",{name:/PO-TEST-1/});
 expect(screen.getByLabelText("商品1来源订单1")).toHaveValue("");expect(screen.getByLabelText("商品2来源订单1")).toHaveValue("");
});
it("attributes repeated carton rows when their total fits, without double-counting its own automatic allocations",async()=>{
 render(<Harness initialSources={[{sku_id:"11",actual_units:"8",allocations:[]},{sku_id:"11",actual_units:"8",allocations:[]}]}/>);
 await waitFor(()=>expect(screen.getByLabelText("商品2来源订单1")).toHaveValue("101"));
 expect(screen.getByLabelText("商品1来源订单1")).toHaveValue("101");
 expect(screen.getByLabelText("商品1分配数量1")).toHaveValue("8");expect(screen.getByLabelText("商品2分配数量1")).toHaveValue("8");
});
it("accounts for manual allocations before suggesting the remaining rows",async()=>{
 api.read.mockResolvedValue({items:[{...order,lines:[{...order.lines![0]!,expected_units:"15"}]}],total:1,page_size:100});
 render(<Harness initialSources={[{sku_id:"11",actual_units:"10",order_attribution:"manual",allocations:[{order_line_id:"101",units:"10"}]},{sku_id:"11",actual_units:"8",allocations:[]}]}/>);
 await screen.findAllByRole("option",{name:/PO-TEST-1/});
 expect(screen.getByLabelText("商品1来源订单1")).toHaveValue("101");expect(screen.getByLabelText("商品2来源订单1")).toHaveValue("");
});
it("leaves unknown shipped quantities for explicit selection",async()=>{
 api.read.mockResolvedValue({items:[{...order,lines:[{...order.lines![0]!,actual_units:undefined}]}],total:1,page_size:100});
 render(<Harness/>);await screen.findAllByRole("option",{name:/PO-TEST-1/});expect(screen.getByLabelText("商品1来源订单1")).toHaveValue("");
});

it("retains saved explicit associations and credits only the current confirmed shipment when editing",async()=>{
 const saved:Source={sku_id:"11",actual_units:"20",allocations:[{order_line_id:"101",units:"20"}]};
 api.read.mockResolvedValue({items:[{...order,lines:[{...order.lines![0]!,actual_units:"20"}]}],total:1,page_size:100});
 render(<Harness autoFill={false} initialSources={[saved]} originalSources={[saved]}/>);
 await screen.findByRole("option",{name:/PO-TEST-1.*可关联20件/});
 expect(screen.getByLabelText("商品1来源订单1")).toHaveValue("101");expect(screen.queryByRole("button",{name:"显示已发完订单"})).not.toBeInTheDocument();
});
