import {render,screen,within,waitFor} from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import {createMemoryRouter,RouterProvider,useLocation} from "react-router-dom";
import {afterEach,beforeEach,it,expect,vi} from "vitest";
import {AuthzGenerationProvider} from "../../app/AuthzGenerationContext";
import ProductionProgressOverview from "./ProductionProgressOverview";
import type {TraceGraph,TraceNode} from "./productionTrace";
const scrollToChain=vi.fn();
it("keeps transit read errors visible and recovers without a zero balance",async()=>{
 const original=api.read.getMockImplementation()!;let fail=true;
 api.read.mockImplementation((p:string)=>p==="/api/production/inventory/transport-summary"?(fail?Promise.reject(new Error("运输来源暂不可用")):Promise.resolve({opening_scope:{warehouse_id:"8",owner_id:"1"},opening_balances:[{sku_id:"10",sku_label:"2205-White-M",units:"151",snapshot_on:"2026-11-04",source_filename:"source.csv"}]})):original(p) as Promise<unknown>);
 mount();expect(await screen.findByText("历史在途读取失败")).toBeVisible();
 expect(screen.queryByRole("region",{name:"历史在途"})).not.toBeInTheDocument();
 fail=false;await userEvent.click(screen.getByRole("button",{name:"重试历史在途"}));
 expect(within(await screen.findByRole("region",{name:"历史在途"})).getByText("151 件")).toBeVisible();
 expect(api.write).not.toHaveBeenCalled();
});
it("shows historical transit outside order chains and excludes it from completed chains",async()=>{
 const original=api.read.getMockImplementation()!;
 api.read.mockImplementation((p:string)=>p==="/api/production/inventory/transport-summary"?Promise.resolve({opening_scope:{warehouse_id:"8",owner_id:"1"},opening_balances:[{sku_id:"10",sku_label:"2205-White-M",units:"151",snapshot_on:"2026-11-04",source_filename:"source.csv"}]}):original(p) as Promise<unknown>);
 mount();const opening=await screen.findByRole("region",{name:"历史在途"});
 expect(within(opening).getByText("151 件")).toBeVisible();
 expect(within(screen.getByRole("region",{name:"完整业务链路"})).getAllByRole("article")).toHaveLength(5);
 await userEvent.click(within(opening).getByText("历史在途"));
 expect(within(opening).getByRole("table",{name:"期初在途明细"})).toBeVisible();
 await userEvent.click(within(screen.getByRole("group",{name:"总链路完成状态"})).getByRole("button",{name:/已完成/}));
 expect(screen.queryByRole("region",{name:"历史在途"})).not.toBeInTheDocument();
 expect(api.write).not.toHaveBeenCalled();
});
const api=vi.hoisted(()=>({read:vi.fn(),write:vi.fn()}));
vi.mock("../../api/client",async original=>({...await original<typeof import("../../api/client")>(),requestApi:api.read,writeApi:api.write}));
vi.mock("./ProductionProgressFlow",()=>({ProductionProgressFlow:({graph,onOpen}:{graph:TraceGraph;onOpen:(n:TraceNode,t:HTMLElement)=>void})=><div>{graph.nodes.map(n=><button key={n.id} onClick={e=>onOpen(n,e.currentTarget)}>{n.title} {n.quantity}</button>)}</div>}));
const orders=Array.from({length:100},(_,i)=>({id:String(i+1),business_number:`PO${i+1}`,system_number:`PO${i+1}`,status:"CONFIRMED",revision:"1",production_completion_state:"OPEN",expected_units:"100",received_units:"60",fulfillment_lines:[{id:String(i+101),sku_id:"1",expected_units:"100",shipped_units:"0",received_units:"0"}],lines:[{id:String(i+101),sku_id:"1",sku_label:"款1",expected_units:"100",produced_units:"80",received_units:"60"}]}));
function Location(){return <output aria-label="当前URL">{useLocation().search}</output>;}
function mount(entry="/production/overview"){return render(<AuthzGenerationProvider boundary={{principalId:1,roles:["admin"],siteId:1,siteConfigVersionId:1}} onRevoked={()=>undefined}><RouterProvider router={createMemoryRouter([{path:"*",element:<><ProductionProgressOverview canWrite/><Location/></>}],{initialEntries:[entry]})}/></AuthzGenerationProvider>);}
afterEach(()=>vi.unstubAllGlobals());
beforeEach(()=>{scrollToChain.mockClear();Object.defineProperty(HTMLElement.prototype,"scrollIntoView",{configurable:true,value:scrollToChain});const NativeRequest=globalThis.Request;vi.stubGlobal("Request",class extends NativeRequest {constructor(input:RequestInfo|URL,init?:RequestInit){const {signal,...options}=init||{};super(input,options);if(signal)Object.defineProperty(this,"signal",{value:signal});}});api.read.mockReset();api.write.mockReset();api.read.mockImplementation((path:string)=>{const u=new URL(path,"http://local");if(u.pathname==="/api/production/inventory/progress-chains"){const target=u.searchParams.get("trace_id"),page=Number(u.searchParams.get("page")||1);const selected=target?orders.filter(o=>o.id===target):orders.slice((page-1)*5,page*5);return Promise.resolve({items:selected.map(o=>({id:`order-${o.id}`,orders:[o],shipments:[],completed:false})),total:target?selected.length:100,page,page_size:5,chain_counts:{active:100,completed:0,all:100},detail_scope:"complete_chain_groups"});}if(u.pathname==="/api/production/orders"){const page=Number(u.searchParams.get("page"));return Promise.resolve({items:orders.slice((page-1)*5,page*5),total:100,page,page_size:5,progress_counts:{active:100,completed:0,all:100}});}if(u.pathname.startsWith("/api/production/orders/"))return Promise.resolve({...orders.find(o=>o.id===u.pathname.split("/").at(-1)),receipts:[],shipments:[],history:[]});if(path.includes("destination-state"))return Promise.resolve({bindings:[],receipts:[]});if(path.includes("transit-batches"))return Promise.resolve({items:[],total:0,page:1,page_size:5,detail_scope:"whole_batch"});if(path.includes("availability"))return Promise.resolve({items:[],scopes:[]});return Promise.resolve({items:[],total:0});});});
it("paginates 100 fictional roots and only reads details after a node is opened",async()=>{mount();await screen.findByText("订单 PO1");expect(screen.getAllByRole("article")).toHaveLength(5);expect(api.read.mock.calls.some(([p])=>/^\/api\/production\/orders\/[0-9]/.test(p as string))).toBe(false);expect(api.read.mock.calls.filter(([p])=>(p as string).startsWith("/api/production/inventory/progress-chains?"))).toHaveLength(1);await userEvent.click(within(screen.getByRole("region",{name:"完整业务链路"})).getByRole("button",{name:"下一页"}));await screen.findByText("订单 PO6");expect(screen.queryByText("订单 PO1")).not.toBeInTheDocument();});
it("opens stage details without automatic completion and preserves URL on close",async()=>{mount("/production/overview?warehouse=8");await screen.findByText("订单 PO1");const root=screen.getByRole("article",{name:"订单 PO1"});await userEvent.click(within(root).getByRole("button",{name:/工厂生产/}));expect(within(await screen.findByRole("dialog")).getByRole("cell",{name:"80"})).toBeVisible();await userEvent.click(screen.getByRole("button",{name:"关闭对话框"}));expect(screen.getByLabelText("当前URL")).toHaveTextContent("warehouse=8");expect(api.write).not.toHaveBeenCalled();});
it("loads a completed target directly without fetching all pages",async()=>{mount("/production/overview?trace_kind=order&trace_id=99");expect(await screen.findByText("订单 PO99")).toBeVisible();expect(screen.queryByText("订单 PO1")).not.toBeInTheDocument();expect(api.read.mock.calls.some(([p])=>(p as string).includes("trace_id=99"))).toBe(true);});
it("shows all stages immediately, preserves server filters and expands original order controls",async()=>{mount("/production/overview?warehouse=8&q=款1");await screen.findByText("订单 PO1");expect(api.read.mock.calls.some(([p])=>(p as string).includes("warehouse_id=8"))).toBe(true);const root=screen.getByRole("article",{name:"订单 PO1"});expect(within(root).getByRole("button",{name:/目的仓实收/})).toBeVisible();await userEvent.click(within(root).getByRole("button",{name:"展开订单与批次"}));expect(await screen.findByRole("article",{name:"订单明细 PO1"})).toBeVisible();expect(api.read.mock.calls.some(([p])=>(p as string).includes("order_id="))).toBe(false);});
it("shows chain failure without pretending there are zero results",async()=>{const original=api.read.getMockImplementation()!;api.read.mockImplementation((p:string)=>p.includes("progress-chains")?Promise.reject(new Error("完整链路读取暂不可用")):original(p) as Promise<unknown>);mount();expect(await screen.findByText("完整链路读取暂不可用")).toBeVisible();expect(screen.queryByText("0 条链路")).not.toBeInTheDocument();});

it("keeps unknown completion results locked across view navigation and queries the original operation",async()=>{const original=api.read.getMockImplementation()!;api.read.mockImplementation(async(p:string)=>{if(p.startsWith("/api/production/commands/"))return {...orders[0],production_completion_state:"COMPLETED"};const result=await original(p) as {items?:{orders:typeof orders}[]};if(p.startsWith("/api/production/inventory/progress-chains?"))return {...result,items:result.items?.map(g=>({...g,orders:g.orders.map(o=>({...o,production_completion_ready:true}))}))};return result;});api.write.mockRejectedValue(new Error("result unknown"));mount();await screen.findByText("订单 PO1");await userEvent.click(within(screen.getByRole("article",{name:"订单 PO1"})).getByRole("button",{name:"展开订单与批次"}));await userEvent.click(within(screen.getByRole("article",{name:"订单明细 PO1"})).getByRole("button",{name:"确认完成"}));await screen.findByText("保存结果待核实，已锁定当前输入");await userEvent.click(screen.getByRole("button",{name:"更多"}));await userEvent.click(screen.getByRole("menuitem",{name:"表格与导出"}));expect(await screen.findByText("先核实保存结果")).toBeVisible();expect(screen.getByLabelText("当前URL")).not.toHaveTextContent("overview_view=table");await userEvent.click(screen.getByRole("button",{name:"继续核实"}));await userEvent.click(screen.getByRole("button",{name:"查询原操作结果"}));expect(await screen.findByText(/完成状态已更新/)).toBeVisible();expect(api.write).toHaveBeenCalledTimes(1);});

it("saves through the original production editor and rereads the current node facts",async()=>{let produced="80";const original=api.read.getMockImplementation()!;api.read.mockImplementation(async(p:string)=>{const result=await original(p) as {items?:{orders:typeof orders}[];id?:string};if(p.startsWith("/api/production/inventory/progress-chains?"))return {...result,items:result.items?.map(g=>({...g,orders:g.orders.map(o=>({...o,lines:o.lines.map(l=>({...l,produced_units:produced}))}))}))};if(p==="/api/production/orders/1")return {...orders[0],lines:orders[0]!.lines.map(l=>({...l,produced_units:produced})),receipts:[],shipments:[],history:[]};return result;});api.write.mockImplementation(()=>{produced="81";return Promise.resolve({...orders[0],revision:"2",lines:orders[0]!.lines.map(l=>({...l,produced_units:produced}))});});mount();await screen.findByText("订单 PO1");await userEvent.click(within(screen.getByRole("article",{name:"订单 PO1"})).getByRole("button",{name:/工厂生产/}));await userEvent.click(await screen.findByRole("button",{name:"批量更新生产进度"}));const field=await screen.findByLabelText("款1 累计实际生产数量");await userEvent.clear(field);await userEvent.type(field,"81");await userEvent.click(screen.getByRole("button",{name:"核对并保存进度"}));expect(await within(await screen.findByRole("table",{name:"本单逐规格进度"})).findByRole("cell",{name:"81"})).toBeVisible();expect(screen.queryByRole("heading",{name:"81 件 · 部分完成"})).not.toBeInTheDocument();expect(api.write.mock.calls[0]?.[0]).toBe("/api/production/orders/1/production-progress");});
it("recovers a failed root read using the original retry while keeping filters",async()=>{const original=api.read.getMockImplementation()!;let failed=false;api.read.mockImplementation((p:string)=>{if(p.startsWith("/api/production/inventory/progress-chains?")&&!failed){failed=true;return Promise.reject(new Error("订单读取暂不可用"));}return original(p) as Promise<unknown>;});mount("/production/overview?warehouse=8");expect(await screen.findByText("订单读取暂不可用")).toBeVisible();await userEvent.click(screen.getByRole("button",{name:"重试链路"}));expect(await screen.findByText("订单 PO1")).toBeVisible();expect(screen.getByLabelText("当前URL")).toHaveTextContent("warehouse=8");});

it("merges three orders into one full route, focuses one order and opens each batch from the summary",async()=>{
 const original=api.read.getMockImplementation()!;
 api.read.mockImplementation((p:string)=>p.includes("progress-chains")?Promise.resolve({items:[{id:"order-1",orders:orders.slice(0,3),shipments:[],completed:false}],total:1,page:1,page_size:5,chain_counts:{active:1,completed:0,all:1},detail_scope:"complete_chain_groups"}):original(p) as Promise<unknown>);
 mount();const root=await screen.findByRole("article",{name:"3 笔订单 · 同路径履约"});expect(screen.getAllByRole("article")).toHaveLength(1);expect(within(root).getByRole("button",{name:/下单 · 3 单/})).toBeVisible();
 expect(screen.getByRole("button",{name:"PO2",hidden:true})).not.toBeVisible();await userEvent.click(screen.getByText("按订单查看"));
 await userEvent.click(screen.getByRole("button",{name:"PO2"}));expect(within(root).getByRole("button",{name:/下单 · 1 单/})).toBeVisible();expect(screen.getByLabelText("当前URL")).toHaveTextContent("focus_order=2");
 await userEvent.click(screen.getByRole("button",{name:"整组"}));await userEvent.click(within(root).getByRole("button",{name:/工厂生产/}));expect(await screen.findByRole("table",{name:"整组订单履约进度"})).toBeVisible();
 expect(within(screen.getByRole("dialog")).getByRole("button",{name:"PO3"})).toHaveAttribute("title","PO3");await userEvent.click(within(screen.getByRole("dialog")).getByRole("button",{name:"PO3"}));expect(await screen.findByRole("table",{name:"本单逐规格进度"})).toBeVisible();expect(screen.getByLabelText("当前URL")).toHaveTextContent("trace_id=3");
});
it.each([1,2])("keeps focused order transport within its %i related shipments",async(count)=>{
 const original=api.read.getMockImplementation()!;
 const batch=(id:string,order:typeof orders[number])=>({id,business_number:`BATCH${id}`,system_number:`SH${id}`,owner_id:"1",warehouse_id:"8",destination_id:"9",source_name:"成品仓",destination_name:"FBA",shipped_units:"2",received_units:"0",unreceived_units:"2",settled_units:"0",stage:"UNREGISTERED",transport:{registered:false,status:"UNREGISTERED",record:null,events:[],source_revision_current:true},sources:[{id:`${id}1`,sku_id:"1",sku_label:"款1",actual_units:"2",received_units:"0",allocations:[{order_id:order.id,order_line_id:order.lines[0]!.id,units:"2"}],bindings:[]}],receipt_dates:[]});
 const batches=[batch("61",orders[0]!),batch("62",orders[1]!),...(count===2?[batch("63",orders[1]!)]:[])];
 api.read.mockImplementation((p:string)=>{
  if(p.includes("progress-chains"))return Promise.resolve({items:[{id:"order-1",orders:orders.slice(0,2),shipments:batches,completed:false}],total:1,page:1,page_size:5,chain_counts:{active:1,completed:0,all:1},detail_scope:"complete_chain_groups"});
  if(p.includes("transport-state"))return Promise.resolve({registered:false,shipment_id:"62",shipment_revision:"1",shipment_status:"CONFIRMED",warehouse_id:"8",owner_id:"1",destination_id:"9",status:"UNREGISTERED",record:null,events:[],history:[],shipment_units:"2",destination_received_units:"0",latest_event:null,source_revision_current:true});
  return original(p) as Promise<unknown>;
 });
 mount("/production/overview?focus_order=2");
 const root=await screen.findByRole("article",{name:"2 笔订单 · 同路径履约"});
 await userEvent.click(within(root).getByRole("button",{name:/运输/}));
 if(count===1){
  expect(await screen.findByRole("heading",{name:"运输跟踪"})).toBeVisible();
  expect(screen.getByLabelText("当前URL")).toHaveTextContent("trace_kind=shipment&trace_id=62");
 }else{
  const dialog=await screen.findByRole("dialog");
  expect(within(dialog).getByRole("button",{name:/运输办理 · BATCH62/})).toBeVisible();
  expect(within(dialog).getByRole("button",{name:/运输办理 · BATCH63/})).toBeVisible();
  expect(within(dialog).queryByRole("button",{name:/运输办理 · BATCH61/})).not.toBeInTheDocument();
  expect(within(dialog).queryByRole("button",{name:"PO1"})).not.toBeInTheDocument();
 }
 expect(api.write).not.toHaveBeenCalled();
});

it("uses total-chain completion independently from the production decision and preserves completed routes",async()=>{
 const original=api.read.getMockImplementation()!;api.read.mockImplementation((p:string)=>{
  if(!p.includes("progress-chains"))return original(p) as Promise<unknown>;
  const u=new URL(p,"http://local"),done=u.searchParams.get("chain_progress")==="completed";return Promise.resolve({items:[{id:"order-1",orders:[{...orders[0],production_completion_state:"OPEN"}],shipments:[],completed:done}],total:1,page:1,page_size:5,chain_counts:{active:1,completed:1,all:2},detail_scope:"complete_chain_groups"});
 });mount();await screen.findByText("订单 PO1");await userEvent.click(within(screen.getByRole("group",{name:"总链路完成状态"})).getByRole("button",{name:"已完成 1"}));expect(await screen.findByText("总链路已完成")).toBeVisible();expect(screen.getByLabelText("当前URL")).toHaveTextContent("chain_progress=completed");expect(api.write).not.toHaveBeenCalled();
});

it("shows production and receipt facts by stage and opens the original multi-order receipt in the same drawer",async()=>{
 const original=api.read.getMockImplementation()!;const grouped=orders.slice(0,3).map(o=>({...o,receipt_warehouse_id:"8",receipt_owner_id:"1"}));
 api.read.mockImplementation((p:string)=>{
  if(p.includes("progress-chains"))return Promise.resolve({items:[{id:"order-1",orders:grouped,shipments:[],completed:false}],total:1,page:1,page_size:5,chain_counts:{active:1,completed:0,all:1},detail_scope:"complete_chain_groups"});
  if(p.includes("receipt-batches/sources"))return Promise.resolve({id:"receipt-batch",revision:"1:1,2:1,3:1",status:"CONFIRMED",receipt_batch:true,lines:grouped.flatMap(o=>o.lines.map(l=>({...l,order_id:o.id,order_label:o.business_number})))});
  if(p.includes("availability"))return Promise.resolve({writes_enabled:true,production_receipts_supported:true,items:[],scopes:[{warehouse_id:"8",owner_id:"1",warehouse_name:"成品仓",owner_name:"自有",warehouse_status:"ACTIVE",warehouse_type:"OWN"}]});
  if(p==="/api/production/warehouses?page=1")return Promise.resolve({items:[{id:"8",name:"成品仓",status:"ACTIVE",type:"OWN"}],total:1,page_size:20});return original(p) as Promise<unknown>;
 });
 mount();const root=await screen.findByRole("article",{name:"3 笔订单 · 同路径履约"});await userEvent.click(within(root).getByRole("button",{name:/成品入库/}));
 const dialog=await screen.findByRole("dialog");expect(within(dialog).getByRole("columnheader",{name:"累计生产"})).toBeVisible();expect(within(dialog).getByRole("columnheader",{name:"成品实收"})).toBeVisible();expect(within(dialog).queryByRole("link",{name:"从成品仓出货"})).not.toBeInTheDocument();
 await userEvent.click(within(dialog).getByRole("button",{name:"本批成品入库"}));expect(await screen.findByRole("combobox",{name:"本次实收入库仓库"})).toHaveValue("8:1");expect(screen.getAllByRole("dialog")).toHaveLength(1);
 await userEvent.click(screen.getByRole("button",{name:"下一步"}));expect(screen.getByRole("button",{name:"导入表格"})).toBeVisible();expect(screen.getByRole("link",{name:"下载入库模板"})).toHaveAttribute("href",expect.stringContaining("receipt-batches/table/template"));expect(api.write).not.toHaveBeenCalled();
});
it("opens a single shipment directly at transport and composes dirty and unknown-result protection",async()=>{
 const original=api.read.getMockImplementation()!;let transport={registered:false,shipment_id:"6",shipment_revision:"1",shipment_status:"CONFIRMED",warehouse_id:"8",owner_id:"1",destination_id:"9",status:"UNREGISTERED",record:null as unknown,events:[],history:[],shipment_units:"2",destination_received_units:"0",latest_event:null,source_revision_current:true};
 const batch={id:"6",business_number:"SIM-BATCH",system_number:"SH6",owner_id:"1",warehouse_id:"8",destination_id:"9",source_name:"成品仓",destination_name:"FBA",shipped_units:"2",received_units:"0",unreceived_units:"2",settled_units:"0",stage:"UNREGISTERED",transport,sources:[{id:"61",sku_id:"1",sku_label:"款1",actual_units:"2",received_units:"0",allocations:[],bindings:[]}],receipt_dates:[]};
 api.read.mockImplementation((p:string)=>{
  if(p.includes("progress-chains"))return Promise.resolve({items:[{id:"shipment-6",orders:[],shipments:[batch],completed:false}],total:1,page:1,page_size:5,chain_counts:{active:1,completed:0,all:1},detail_scope:"complete_chain_groups"});
  if(p.includes("transport-state"))return Promise.resolve(transport);if(p.includes("destination-state"))return Promise.resolve({bindings:[],receipts:[]});
  if(p.startsWith("/api/production/commands/")){transport={...transport,registered:true,status:"REGISTERED",record:{id:"7",revision:"1",carrier:"测试运输",tracking_number:"SIM-1",source_reference:"自有样例",arrival_local:"",arrival_timezone:"Asia/Shanghai"}};return Promise.resolve(transport);}return original(p) as Promise<unknown>;
 });
 mount();const root=await screen.findByRole("article",{name:"独立出货 · 1 批"});await userEvent.click(within(root).getByRole("button",{name:/运输/}));
 await userEvent.click(await screen.findByRole("button",{name:"登记运输资料"}));await userEvent.type(screen.getByRole("textbox",{name:"承运商"}),"测试运输");
 await userEvent.click(screen.getByRole("button",{name:"关闭对话框"}));expect(await screen.findByText("还有未保存的内容")).toBeVisible();await userEvent.click(screen.getByRole("button",{name:"继续填写"}));expect(screen.getByRole("textbox",{name:"承运商"})).toHaveValue("测试运输");
 await userEvent.type(screen.getByRole("textbox",{name:"运单号"}),"SIM-1");await userEvent.type(screen.getByRole("textbox",{name:"来源依据（人工登记，请注明凭据）"}),"自有样例");api.write.mockRejectedValueOnce(new TypeError("response lost"));await userEvent.click(screen.getByRole("button",{name:"保存运输资料"}));expect(await screen.findByText("保存结果待核实，已锁定当前输入")).toBeVisible();expect(screen.getByRole("button",{name:"关闭对话框"})).toBeDisabled();await userEvent.click(screen.getByRole("button",{name:"查询原操作结果"}));expect(await within(await screen.findByRole("dialog")).findByText("运输记录已保存，物流与实收入库分别显示。")).toBeVisible();expect(api.write).toHaveBeenCalledTimes(1);
});

it("consolidates actions, keeps filters collapsed and locates orders from the independent stage board",async()=>{
 mount();await screen.findByRole("table",{name:"订单当前阶段"});expect(screen.queryByRole("heading",{name:"待办与异常"})).not.toBeInTheDocument();expect(screen.queryByRole("link",{name:"订单办理"})).not.toBeInTheDocument();expect(screen.getByLabelText("生产人工完成状态")).not.toBeVisible();await userEvent.click(screen.getByText("筛选",{exact:true}));expect(screen.getByLabelText("生产人工完成状态")).toBeVisible();
 await userEvent.click(within(screen.getByRole("region",{name:"订单阶段看板"})).getByRole("button",{name:"下一页"}));await screen.findByRole("button",{name:"查看订单阶段 PO6"});await userEvent.click(screen.getByRole("button",{name:"查看订单阶段 PO6"}));expect(await screen.findByText("订单 PO6")).toBeVisible();expect(screen.getByLabelText("当前URL")).toHaveTextContent("trace_id=6");expect(scrollToChain).toHaveBeenCalledWith({block:"start"});expect(api.write).not.toHaveBeenCalled();
});
it("hides inactive warehouses from current stock while preserving history filters and the scoped inventory drawer",async()=>{
 const original=api.read.getMockImplementation()!;const scopes=[{warehouse_id:"8",owner_id:"1",warehouse_name:"成品仓",owner_name:"自有"}];
 const item={warehouse_id:"8",owner_id:"1",sku_id:"1",style_code:"A001",standard_color:"黑色",standard_size:"M",on_hand_units:"5",free_available_units:"3",state:"ready"};
 api.read.mockImplementation((p:string)=>{
  if(p==="/api/production/warehouses?page=1")return Promise.resolve({items:[{id:"8",name:"成品仓",type:"OWN",status:"ACTIVE"},{id:"9",name:"停用仓",type:"OWN",status:"INACTIVE"}],total:2,page_size:20});
  if(p==="/api/production/warehouses/8")return Promise.resolve({id:"8",name:"成品仓",type:"OWN",status:"ACTIVE",inventory_state:"READY",scopes});
  if(p.includes("availability"))return Promise.resolve({items:[item,{...item,warehouse_id:"9",on_hand_units:"900"},{...item,owner_id:"2",on_hand_units:"800"}],scopes,writes_enabled:true});
  return original(p) as Promise<unknown>;
 });
 mount("/production/overview?q=keep");await screen.findByRole("button",{name:"查看成品仓库存"});expect(screen.queryByRole("button",{name:"查看停用仓库存"})).not.toBeInTheDocument();expect(screen.getByRole("option",{name:"停用仓",hidden:true})).toBeInTheDocument();await userEvent.click(screen.getByRole("button",{name:"查看成品仓库存"}));const dialog=await screen.findByRole("dialog");expect(await within(dialog).findByRole("table",{name:"本仓款色尺码库存"})).toBeVisible();expect(within(dialog).queryByText("900")).not.toBeInTheDocument();expect(within(dialog).queryByText("800")).not.toBeInTheDocument();expect(within(dialog).queryByRole("link",{name:"出货"})).not.toBeInTheDocument();expect(screen.getByLabelText("当前URL")).toHaveTextContent("stock_warehouse=8");await userEvent.click(within(dialog).getByRole("button",{name:"关闭对话框"}));expect(screen.getByLabelText("当前URL")).toHaveTextContent("q=keep");expect(screen.getByLabelText("当前URL")).not.toHaveTextContent("stock_warehouse");await waitFor(()=>expect(screen.getByRole("button",{name:"查看成品仓库存"})).toHaveFocus());expect(api.write).not.toHaveBeenCalled();
});


it.each([false, true])("keeps the receipt drawer focused on receiving, summary %s", async summary => {
  const original = api.read.getMockImplementation()!;
  const order = { ...orders[0]!, receipt_warehouse_id: "8", receipt_owner_id: "1" };
  api.read.mockImplementation((path: string) => {
    if (path.includes("progress-chains")) return Promise.resolve({ items: [{ id: "order-1", orders: [order, ...(summary ? [orders[1]!] : [])], shipments: [], completed: false }], total: 1, page: 1, page_size: 5, chain_counts: { active: 1, completed: 0, all: 1 }, detail_scope: "complete_chain_groups" });
    if (path === "/api/production/orders/1") return Promise.resolve({ ...order, receipts: [], shipments: [{ id: "6", status: "CONFIRMED", business_number: "SHIP-6" }], history: [] });
    if (path.startsWith("/api/production/warehouses?")) return Promise.resolve({ items: [{ id: "8", name: "成品仓", type: "OWN", status: "ACTIVE" }], total: 1 });
    return original(path) as Promise<unknown>;
  });
  mount(`/production/overview?trace_kind=order&trace_id=1&trace_stage=receipt${summary ? "&trace_summary=1" : ""}`);
  const dialog = await screen.findByRole("dialog");
  expect(await within(dialog).findByRole("button", { name: summary ? "本批成品入库" : "本单成品入库" })).toBeVisible();
  expect(within(dialog).queryByRole("link", { name: "从成品仓出货" })).not.toBeInTheDocument();
  expect(within(dialog).queryByRole("heading", { name: "成品仓出货" })).not.toBeInTheDocument();
  expect(within(dialog).queryByText(/明确关联的历史出货/)).not.toBeInTheDocument();
  expect(within(dialog).queryByRole("heading", { name: "关联出货与到仓" })).not.toBeInTheDocument();
  expect(dialog).not.toHaveTextContent("上方成品仓直接独立出货");
  expect(api.write).not.toHaveBeenCalled();
});

it("keeps the warehouse dispatch entry in the dispatch stage", async () => {
  const original = api.read.getMockImplementation()!;
  api.read.mockImplementation((path: string) => {
    if (path.includes("progress-chains")) return Promise.resolve({ items: [{ id: "order-1", orders: [{ ...orders[0]!, receipt_warehouse_id: "8", receipt_owner_id: "1" }], shipments: [], completed: false }], total: 1, page: 1, page_size: 5, chain_counts: { active: 1, completed: 0, all: 1 }, detail_scope: "complete_chain_groups" });
    if (path.startsWith("/api/production/warehouses?")) return Promise.resolve({ items: [{ id: "8", name: "成品仓", type: "OWN", status: "ACTIVE" }], total: 1 });
    return original(path) as Promise<unknown>;
  });
  mount("/production/overview?trace_kind=order&trace_id=1&trace_stage=dispatch&trace_summary=1");
  const dialog = await screen.findByRole("dialog");
  expect(within(dialog).getByRole("heading", { name: "成品仓出货" })).toBeVisible();
  expect(within(dialog).getByRole("link", { name: "从成品仓出货" })).toHaveAttribute("href", expect.stringContaining("purpose=WAREHOUSE_DISPATCH&warehouse_id=8&owner_id=1"));
  expect(api.write).not.toHaveBeenCalled();
});

it("keeps warehouse dispatch available after the previous batch has shipped", async () => {
  const original = api.read.getMockImplementation()!;
  const shipment = { id: "6", sources: [], shipped_units: "100", received_units: "0", transport: { status: "UNREGISTERED", record: null, latest_event: null, events: [] }, stage: "UNREGISTERED", receipt_dates: [] };
  api.read.mockImplementation((path: string) => path.includes("progress-chains") ? Promise.resolve({ items: [{ id: "order-1", orders: [{ ...orders[0], receipt_warehouse_id: "8", receipt_owner_id: "1", fulfillment_lines: orders[0]!.lines.map(line => ({ id: line.id, sku_id: line.sku_id, expected_units: line.expected_units, shipped_units: line.expected_units, received_units: "0" })) }], shipments: [shipment], completed: false }], total: 1, page: 1, page_size: 5, chain_counts: { active: 1, completed: 0, all: 1 }, detail_scope: "complete_chain_groups" }) : original(path) as Promise<unknown>);
  mount();
  const root = await screen.findByRole("article", { name: "订单 PO1" });
  await userEvent.click(within(root).getByRole("button", { name: /出货记录/ }));
  const dialog = await screen.findByRole("dialog");
  expect(within(dialog).getByRole("heading", { name: "成品仓出货" })).toBeVisible();
  expect(within(dialog).getByRole("link", { name: /成品仓出货/ })).toBeVisible();
  expect(within(dialog).getByRole("table", { name: "整组订单履约进度" })).toBeVisible();
  expect(api.write).not.toHaveBeenCalled();
});


it("shows an explicitly located void order as history without active production stages",async()=>{
 const original=api.read.getMockImplementation()!;
 api.read.mockImplementation((path:string)=>path.includes("progress-chains")?Promise.resolve({items:[{id:"order-9",orders:[{...orders[0],id:"9",status:"VOID",business_number:"VOID-QA"}],shipments:[],completed:false}],total:1,page:1,page_size:5,chain_counts:{active:0,completed:1,all:1},detail_scope:"complete_chain_groups"}):original(path) as Promise<unknown>);
 mount("/production/overview?trace_kind=order&trace_id=9&trace_stage=production");
 expect(await screen.findByText("订单已作废")).toBeVisible();
 expect(screen.getByRole("link",{name:"查看订单记录"})).toHaveAttribute("href","/production/orders/9");
 expect(screen.queryByText("总链路进行中")).not.toBeInTheDocument();
 expect(screen.queryByRole("article",{name:"订单 VOID-QA"})).not.toBeInTheDocument();
 expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
 expect(api.write).not.toHaveBeenCalled();
});

it.each([true, false])("aligns located and clicked orders with their actual chain completion: %s", async completed => {
 const original = api.read.getMockImplementation()!;
 const active = {...orders[0]!,lines:orders[0]!.lines.map(line=>({...line,received_units:"0"}))};
 const done = {...orders[1]!, business_number:"PO-72733292-30a2-41f9-8fb8-cd16e6bd2c3d", lines:orders[1]!.lines.map(line=>({...line,produced_units:"100",received_units:"100"})), fulfillment_lines:orders[1]!.fulfillment_lines.map(line=>({...line,shipped_units:"100",received_units:"100"}))};
 const group = (isDone:boolean) => ({id:isDone?"order-2":"order-1",orders:[isDone?done:active],shipments:[],completed:isDone});
 api.read.mockImplementation((path:string)=>{
  const url = new URL(path,"http://local");
  if(url.pathname==="/api/production/orders")return Promise.resolve({items:[active,done],total:2,page:1,page_size:5});
  if(url.pathname==="/api/production/inventory/progress-chains") {
   const isDone=url.searchParams.has("trace_id")?url.searchParams.get("trace_id")==="2":url.searchParams.get("chain_progress")==="completed";
   return Promise.resolve({items:[group(isDone)],total:1,page:1,page_size:5,chain_counts:{active:1,completed:1,all:2},detail_scope:"complete_chain_groups"});
  }
  return original(path) as Promise<unknown>;
 });
 mount(`/production/overview?chain_progress=${completed?"active":"completed"}&trace_kind=order&trace_id=${completed?"2":"1"}&focus_order=${completed?"2":"1"}`);
 const switches=screen.getByRole("group",{name:"总链路完成状态"});
 await waitFor(()=>expect(within(switches).getByRole("button",{name:completed?"已完成 1":"进行中 1"})).toHaveAttribute("aria-pressed","true"));
 expect(screen.getByLabelText("当前URL")).toHaveTextContent(`chain_progress=${completed?"completed":"active"}`);
 const board=screen.getByRole("table",{name:"订单当前阶段"});
 expect(within(board).getAllByRole("columnheader").map(cell=>cell.textContent)).toEqual(["款号","订单","当前阶段","生产状态","节点进度"]);
 const doneButton=within(board).getByRole("button",{name:`查看订单阶段 ${done.business_number}`});
 expect(doneButton).toHaveAttribute("title",done.business_number);
 expect(doneButton).toHaveTextContent("#2");
 expect(within(board).getByRole("progressbar",{name:"订单 PO1 生产中"})).toHaveValue(80);
 const other=completed?active:done;
 await userEvent.click(within(board).getByRole("button",{name:`查看订单阶段 ${other.business_number}`}));
 await waitFor(()=>expect(within(switches).getByRole("button",{name:completed?"进行中 1":"已完成 1"})).toHaveAttribute("aria-pressed","true"));
 expect(screen.getByLabelText("当前URL")).toHaveTextContent(`trace_id=${other.id}`);
 expect(within(board).getByRole("button",{name:`查看订单阶段 ${other.business_number}`})).toHaveAttribute("aria-current","true");
 expect(api.write).not.toHaveBeenCalled();
});

it("allows another warehouse dispatch from an existing standalone shipment",async()=>{
 const original=api.read.getMockImplementation()!;
 const shipment={id:"6",warehouse_id:"8",owner_id:"1",source_name:"成品仓",business_number:"SHIP-6",sources:[],shipped_units:"10",received_units:"0",unreceived_units:"10",settled_units:"0",transport:{status:"UNREGISTERED",record:null,latest_event:null,events:[],history:[]},stage:"UNREGISTERED",receipt_dates:[],dispatch_purpose:"WAREHOUSE_DISPATCH"};
 api.read.mockImplementation((path:string)=>path.includes("progress-chains")?Promise.resolve({items:[{id:"shipment-6",orders:[],shipments:[shipment],completed:false}],total:1,page:1,page_size:5,chain_counts:{active:1,completed:0,all:1},detail_scope:"complete_chain_groups"}):path.startsWith("/api/production/warehouses?")?Promise.resolve({items:[{id:"8",name:"成品仓",type:"OWN",status:"ACTIVE"}],total:1}):original(path) as Promise<unknown>);
 mount("/production/overview?trace_kind=shipment&trace_id=6&trace_stage=dispatch");
 const dialog=await screen.findByRole("dialog");
 expect(within(dialog).getByRole("link",{name:"从成品仓出货"})).toHaveAttribute("href",expect.stringContaining("warehouse_id=8&owner_id=1"));
 expect(api.write).not.toHaveBeenCalled();
});


it.each([1,2])("opens grouped transport with %s shipment using the matching detail level", async count => {
 const original=api.read.getMockImplementation()!;
 const transport={registered:true,shipment_id:"6",shipment_revision:"1",shipment_status:"CONFIRMED",warehouse_id:"8",owner_id:"1",destination_id:"9",status:"REGISTERED",record:{id:"7",revision:"1",carrier:"测试运输",tracking_number:"SIM-1",source_reference:"自有样例",arrival_local:"",arrival_timezone:"Asia/Shanghai"},events:[],history:[],shipment_units:"20",destination_received_units:"20",latest_event:null,source_revision_current:true};
 const batch={id:"6",business_number:"",system_number:"SH-long-original-number",business_date:"2026-11-09",owner_id:"1",warehouse_id:"8",destination_id:"9",source_name:"成品仓",destination_name:"FBA",shipped_units:"20",received_units:"20",unreceived_units:"0",settled_units:"0",stage:"RECEIVED",transport,sources:[],receipt_dates:["2026-10-28"]};
 api.read.mockImplementation((path:string)=>{
  if(path.includes("progress-chains"))return Promise.resolve({items:[{id:"order-1",orders:orders.slice(0,2),shipments:count===1?[batch]:[batch,{...batch,id:"7"}],completed:false}],total:1,page:1,page_size:5,chain_counts:{active:1,completed:0,all:1},detail_scope:"complete_chain_groups"});
  if(path.includes("transport-state"))return Promise.resolve(transport);
  return original(path) as Promise<unknown>;
 });
 mount();
 await userEvent.click(await screen.findByRole("button",{name:new RegExp(`^运输 ${count} 批`)}));
 const dialog=await screen.findByRole("dialog");
 if(count===1){
  expect(await within(dialog).findByLabelText("本批收货进度")).toBeVisible();
  expect(within(dialog).queryByText("订单发运归属")).not.toBeInTheDocument();
  expect(within(dialog).getByText("SH-long-original-number")).not.toBeVisible();
  expect(within(dialog).getByText("收货日期早于发货日期")).toBeVisible();
  expect(within(dialog).getByRole("link",{name:"更正出货日期"})).toHaveAttribute("href",expect.stringContaining("/production/shipments/6/edit"));
  expect(within(dialog).queryByRole("button",{name:"追加运输节点"})).not.toBeInTheDocument();
  expect(screen.getByLabelText("当前URL")).toHaveTextContent("trace_kind=shipment");
 }else{
  expect(within(dialog).getByText("订单发运归属")).toBeVisible();
  expect(within(dialog).getAllByRole("button",{name:/运输办理/})).toHaveLength(2);
  expect(within(dialog).queryByLabelText("本批收货进度")).not.toBeInTheDocument();
 }
 expect(api.write).not.toHaveBeenCalled();
});
