import { render, screen, within, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter, useSearchParams } from "react-router-dom";
import { beforeEach, expect, it, vi } from "vitest";
import { AuthzGenerationProvider } from "../../app/AuthzGenerationContext";
import { TransitBatchBoard, TransitBatchDetail } from "./TransitBatchBoard";
const api = vi.hoisted(() => ({ read: vi.fn<(path: string) => Promise<unknown>>() }));
vi.mock("../../api/client", async original => ({ ...await original<typeof import("../../api/client")>(), requestApi: api.read }));
const batch = { id:"77", business_number:"SIM-BATCH", system_number:"S-77", owner_id:"1", destination_id:"2", source_name:"广州成品仓", destination_name:"美国FBA", shipped_units:"5", received_units:"2", unreceived_units:"3", settled_units:"0", stage:"ARRIVAL_CHECK", departed:null, arrived:null, duration_hours:null, receipt_dates:[], transport:{record:null,events:[]}, sources:[{id:"1",sku_id:"11",sku_label:"Black-L",actual_units:"2",received_units:"2",unreceived_units:"0",bindings:[],allocations:[]},{id:"2",sku_id:"12",sku_label:"Black-M",actual_units:"3",received_units:null,unreceived_units:null,bindings:[],allocations:[]}] };
const page = {items:[batch],detail_scope:"whole_batch",total:7,page:1,page_size:5,as_of:"2026-10-30T12:00:00Z"};
function mount(search = "", detail = false, canWrite = false) {
  function View() {
    const [params,setParams]=useSearchParams();
    return <>{detail ? <TransitBatchDetail id={params.get("stock_batch") || "77"} refresh={0} canWrite={canWrite} verify={vi.fn()} /> : <TransitBatchBoard refresh={0} legacySku={params.get("legacy")||undefined} change={values=>{const next=new URLSearchParams(params);for(const [key,value]of Object.entries(values)){if(value)next.set(key,value);else next.delete(key);}setParams(next);}} open={vi.fn()} />}<output data-testid="url">{params.toString()}</output></>;
  }
  render(<MemoryRouter initialEntries={["/production/stock?"+search]}><AuthzGenerationProvider boundary={{principalId:1,roles:[canWrite?"admin":"viewer"],siteId:1,siteConfigVersionId:1}} onRevoked={()=>undefined}><View/></AuthzGenerationProvider></MemoryRouter>);
}
beforeEach(()=>{api.read.mockReset();api.read.mockResolvedValue(page);});
it("keeps whole batches independent of inventory filters and pages all results",async()=>{
  mount("stock_q=Camel&sku_id=99&stock_styles=2");await screen.findByRole("button",{name:"查看整批运输 SIM-BATCH"});
  expect(screen.getByRole("complementary")).toHaveTextContent("2个SKU · 已发5件 · 实收2件 · 未收3件");
  expect(new URLSearchParams(api.read.mock.calls[0]![0].split("?")[1]).get("sku_id")).toBeNull();
  await userEvent.click(screen.getByRole("button",{name:"下一页"}));await waitFor(()=>expect(api.read.mock.calls.at(-1)![0]).toContain("page=2"));expect(screen.getByTestId("url")).toHaveTextContent("stock_styles=2");
});
it("limits legacy lookup to batches containing the SKU while keeping whole-batch response",async()=>{
  mount("legacy=11");await screen.findByText("旧SKU运输链接已转为整批查询");await screen.findByRole("button",{name:"查看整批运输 SIM-BATCH"});expect(api.read.mock.calls[0]![0]).toContain("sku_id=11");expect(screen.getByRole("complementary")).toHaveTextContent("2个SKU");
});
it("filters logistics independently and rejects unconfirmed response scope",async()=>{
  api.read.mockResolvedValue({...page,detail_scope:"single_sku"});mount();await screen.findByText("运输批次范围未确认");expect(screen.queryByRole("button",{name:"查看整批运输 SIM-BATCH"})).not.toBeInTheDocument();
  await userEvent.click(screen.getByText("筛选运输批次"));await userEvent.type(screen.getByLabelText("运输批次或SKU"),"SIM");await userEvent.click(screen.getByRole("button",{name:"查找批次"}));await waitFor(()=>expect(api.read.mock.calls.at(-1)![0]).toContain("q=SIM"));
});
it("distinguishes read failure and an empty result and supports retry",async()=>{
  api.read.mockRejectedValueOnce(new Error("SIM offline"));mount();await screen.findByText("运输看板读取未完成");expect(screen.queryByText("当前没有匹配的运输批次")).not.toBeInTheDocument();api.read.mockResolvedValue({...page,items:[],total:0});await userEvent.click(screen.getByRole("button",{name:"重试运输"}));await screen.findByText("当前没有匹配的运输批次");
});
it.each([false,true])("reads every SKU of the explicit batch and preserves role capability %s",async canWrite=>{
  mount("stock_batch=77",true,canWrite);const table=await screen.findByRole("table",{name:"整批SKU明细"});expect(within(table).getByText("Black-L")).toBeInTheDocument();expect(within(table).getByText("Black-M")).toBeInTheDocument();expect(table).toHaveTextContent("待核");expect(table).toHaveTextContent("0");
  expect(api.read.mock.calls[0]![0]).toContain("shipment_id=77");expect(screen.getByRole("link",{name:"查看原出货与运输"})).toHaveAttribute("href","/production/shipments/77#transport");
  expect(screen.queryByRole("link",{name:"打开目的仓接收"})).not.toBeInTheDocument();if(canWrite)expect(screen.getByRole("button",{name:"开始到仓核验"})).toBeEnabled();else expect(screen.queryByRole("button",{name:"开始到仓核验"})).not.toBeInTheDocument();expect(screen.getAllByText("查看发货来源")).toHaveLength(2);expect(screen.queryByRole("button",{name:/刷新/})).not.toBeInTheDocument();
});
it("does not substitute a different shipment for a missing or invalid deep link",async()=>{
  mount("stock_batch=78",true);await screen.findByText("当前范围没有这笔完整批次");expect(screen.queryByRole("table")).not.toBeInTheDocument();
});
