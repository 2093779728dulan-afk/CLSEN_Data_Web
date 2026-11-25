import { act, cleanup, render, screen, within, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter, useLocation } from "react-router-dom";
import { beforeEach, expect, it, vi } from "vitest";
import { AuthzGenerationProvider } from "../../app/AuthzGenerationContext";
import { SkuAcrossWarehouses } from "./SkuAcrossWarehouses";
import { ApiRequestError } from "../../api/client";
const display = vi.hoisted(() => ({ read: vi.fn<() => Promise<{style_ids: string[]; revision: string; can_manage: boolean}>>(), write: vi.fn<(path: string, options: {body: {style_ids: string[]; expected_revision: string}; operationKey?: string}) => Promise<{style_ids: string[]; revision: string; can_manage: boolean}>>() }));
const api = vi.hoisted(() => ({ read: vi.fn<(path: string) => Promise<unknown>>() }));
vi.mock("../../api/client", async original => ({ ...await original<typeof import("../../api/client")>(), requestApi: (path: string) => path.includes("/display-settings") ? display.read() : api.read(path), writeApi: display.write }));
const catalog = { items: [
  { sku_id: "11", style_id: "1", style_code: "1112", code: "1112-Black-L", label: "1112 Black L", standard_color: "Black", standard_size: "L" },
  { sku_id: "12", style_id: "1", style_code: "1112", code: "1112-Black-M", label: "1112 Black M", standard_color: "Black", standard_size: "M" },
  { sku_id: "13", style_id: "2", style_code: "2121", code: "2121-Camel-S", label: "2121 Camel S", standard_color: "Camel", standard_size: "S" },
] };
const summary = {full_scope:true,items:[],totals:{in_transit_units:"0",arrival_check_units:"0",unregistered_units:"0",exception_units:"0"}};
const batches = { detail_scope:"whole_batch",items:[],total:0,page:1,page_size:5,as_of:"2026-10-30T12:00:00Z" };
const empty = { items: [], total: 0 };
const scopes = [{ warehouse_id: "1", warehouse_name: "SIM factory", owner_id: "1", owner_name: "SIM owner" }, { warehouse_id: "2", warehouse_name: "SIM FBA", owner_id: "1", owner_name: "SIM owner" }];
const stock = { scopes, items: [
  { warehouse_id: "1", owner_id: "1", sku_id: "11", on_hand_units: "2", free_available_units: "2", pending_units: "0", defective_units: "0", state: "ready" },
  { warehouse_id: "2", owner_id: "1", sku_id: "11", on_hand_units: "16", free_available_units: "15", pending_units: "0", defective_units: "1", state: "ready" },
  { warehouse_id: "1", owner_id: "1", sku_id: "12", on_hand_units: "0", free_available_units: "0", pending_units: "0", defective_units: "0", state: "ready" },
  { warehouse_id: "1", owner_id: "1", sku_id: "13", on_hand_units: "3", free_available_units: "3", pending_units: "0", defective_units: "0", state: "ready" },
  { warehouse_id: "2", owner_id: "1", sku_id: "13", on_hand_units: "5", free_available_units: "5", pending_units: "0", defective_units: "0", state: "ready" },
] };
const data = { sku_id: "11", page: 1, page_size: 20, total: 3, as_of: "2026-10-29T06:00:00Z", items: [
  { warehouse_id: "1", warehouse_name: "SIM factory", type: "FACTORY", status: "ACTIVE", owner_id: "1", owner_name: "SIM owner", balance: stock.items[0], incoming: empty, outgoing: empty },
  { warehouse_id: "2", warehouse_name: "SIM FBA", type: "FBA", status: "ACTIVE", owner_id: "1", owner_name: "SIM owner", balance: stock.items[1], incoming: empty, outgoing: empty },
  { warehouse_id: "3", warehouse_name: "SIM not initialized", type: "THIRD_PARTY", status: "ACTIVE", owner_id: null, balance: null, incoming: empty, outgoing: empty },
] };
function mount(path = "/production/stock?view=sku", canWrite = false) {
  function Location() { return <output data-testid="sku-location">{useLocation().search}</output>; }
  render(<MemoryRouter initialEntries={[{pathname:path.split("?")[0],search:path.includes("?")?`?${path.split("?")[1]}`:""}]}><AuthzGenerationProvider boundary={{ principalId: 1, roles: ["viewer"], siteId: 1, siteConfigVersionId: 1 }} onRevoked={() => undefined}><SkuAcrossWarehouses canWrite={canWrite} /><Location /></AuthzGenerationProvider></MemoryRouter>);
}
beforeEach(() => { display.read.mockReset(); display.read.mockResolvedValue({style_ids:["1","2"],revision:"1",can_manage:false}); display.write.mockReset(); localStorage.setItem("clsen:stock-styles:1:1",JSON.stringify(["1","2"])); Object.defineProperties(HTMLDialogElement.prototype, { showModal: {configurable:true,value:function(this:HTMLDialogElement){this.setAttribute("open","");}}, close: {configurable:true,value:function(this:HTMLDialogElement){this.removeAttribute("open");}} }); vi.stubGlobal("ResizeObserver", class { observe = vi.fn(); disconnect = vi.fn(); }); api.read.mockReset(); api.read.mockImplementation(path => Promise.resolve(path.includes("transit-batches") ? batches : path.includes("/skus?") ? catalog : path.includes("/sku-locations?") ? data : path.includes("transport-summary") ? summary : stock)); });
it.each(['','?view=summary','?view=sku','?stock_layout=matrix'])('uses one multi-style table and defaults collapsed for %s',async search=>{
  mount('/production/stock'+search);const table=await screen.findByRole('table',{name:'多款库存总表'});
  await screen.findByRole('button',{name:'展开款号1112'});expect(within(table).getAllByRole('row')).toHaveLength(3);expect(screen.queryByRole('region',{name:'展示范围库存与整批运输汇总'})).not.toBeInTheDocument();expect(screen.queryByRole('link',{name:'登记库存业务'})).not.toBeInTheDocument();expect(within(table).queryByRole('button',{name:'更多'})).not.toBeInTheDocument();expect(screen.getByRole('button',{name:'筛选'})).toBeInTheDocument();
  expect(screen.getByRole('button',{name:'展开款号2121'})).toHaveAttribute('aria-expanded','false');
  expect(screen.queryByRole('button',{name:'SKU清单'})).not.toBeInTheDocument();expect(api.read.mock.calls.some(([path])=>path.includes('sku-locations'))).toBe(false);
});
it('independently opens multiple styles by SVG and keyboard without blank detail rows',async()=>{
  mount();const first=await screen.findByRole('button',{name:'展开款号1112'});await userEvent.click(first.querySelector('svg')!);
  await userEvent.click(screen.getByRole('button',{name:'展开款号2121'}));expect(screen.getByRole('table')).toHaveTextContent('Black');expect(screen.getByRole('table')).toHaveTextContent('Camel');
  const rows=within(screen.getByRole('table')).getAllByRole('row').length;
  const cell=screen.getByRole('button',{name:'1112-Black-L · SIM FBA · SIM owner · 查看明细'});expect(cell).toHaveTextContent(/^16$/);expect(screen.queryByRole('columnheader',{name:'在库合计'})).not.toBeInTheDocument();expect(screen.getByRole('button',{name:'收起款号1112'})).not.toHaveTextContent('SKU');const detailRow=cell.closest('tr')!;expect(within(detailRow).getByRole('rowheader',{name:'1112'})).toBeInTheDocument();expect(within(detailRow).getByText('Black')).toBeInTheDocument();expect(within(detailRow).getByRole('cell',{name:'L'})).toBeInTheDocument();expect(screen.getByRole('table').querySelector('[rowspan]')).toBeNull();await userEvent.click(cell);
  expect(await screen.findByRole('dialog',{name:'1112-Black-L'})).toHaveTextContent('可发15件');expect(within(screen.getByRole('table')).getAllByRole('row')).toHaveLength(rows);
  await userEvent.click(screen.getByRole('button',{name:'关闭数量明细'}));await waitFor(()=>expect(cell).toHaveFocus());
  await userEvent.tab();await userEvent.click(screen.getByRole('button',{name:'收起款号1112'}));
  expect(screen.getByRole('button',{name:'收起款号2121'})).toHaveAttribute('aria-expanded','true');expect(screen.queryByText('Black')).not.toBeInTheDocument();
  await userEvent.keyboard(' ');expect(screen.getByRole('button',{name:'收起款号1112'})).toHaveAttribute('aria-expanded','true');
});
it('uses stable SKU scope for a warehouse cell and requires a scope before handling totals',async()=>{
  mount('/production/stock?sku_id=11',true);await userEvent.click(await screen.findByRole('button',{name:'1112-Black-L · SIM FBA · SIM owner · 查看明细'}));
  const dialog=await screen.findByRole('dialog',{name:'1112-Black-L'});expect(dialog).toHaveTextContent('在库16件');expect(dialog).toHaveTextContent('可发15件');
  expect(screen.getByTestId('sku-location')).toHaveTextContent('stock_scope=2');await userEvent.click(screen.getByRole('button',{name:'关闭数量明细'}));
  await userEvent.click(screen.getByRole('button',{name:'1112-Black-L · 全部仓库 · 查看明细'}));expect(await screen.findByRole('dialog')).toHaveTextContent('在库18件');
  await userEvent.click(screen.getByRole('button',{name:'办理'}));expect(screen.getByRole('menuitem',{name:'入库'})).toHaveAttribute('data-disabled');
});
it('retains zero, absent records and catalog-only SKUs without assuming missing warehouses are zero',async()=>{
  api.read.mockImplementation(path=>Promise.resolve(path.includes('/skus?')?{items:[...catalog.items,{...catalog.items[0],sku_id:'14',code:'1112-Black-S',standard_size:'S'}]}:path.includes('transport-summary')?summary:stock));
  mount('/production/stock?sku_id=12');const zero=await screen.findByRole('button',{name:'1112-Black-M · SIM factory · SIM owner · 查看明细'});expect(zero).toHaveTextContent(/^0$/);
  expect(screen.getByRole('button',{name:'1112-Black-M · SIM FBA · SIM owner · 查看明细'})).toHaveTextContent(/^待核$/);expect(screen.getByRole('button',{name:'1112-Black-S · 全部仓库 · 查看明细'})).toHaveTextContent('未登记');
});
it('restores old SKU detail links to the correct expanded style and remains read only',async()=>{
  mount('/production/stock?view=sku&sku_id=13&sku_detail=1');expect(await screen.findByRole('dialog',{name:'2121-Camel-S'})).toBeVisible();expect(screen.getByRole('button',{name:'收起款号2121'})).toBeInTheDocument();
  expect(screen.getByRole('button',{name:'展开款号1112'})).toBeInTheDocument();expect(screen.queryByRole('button',{name:'办理'})).not.toBeInTheDocument();
});
it('honors explicit multi-style expansion on refresh and collapse overrides legacy selection',async()=>{
  mount('/production/stock?style_id=1&sku_id=11&stock_styles=-');expect(await screen.findByRole('button',{name:'展开款号1112'})).toBeInTheDocument();
  await userEvent.click(screen.getByRole('button',{name:'展开款号2121'}));expect(screen.getByTestId('sku-location')).toHaveTextContent('stock_styles=-%2C2');
  expect(screen.queryByRole('button',{name:/1112-Black-L · 全部仓库/})).not.toBeInTheDocument();
});
it('opens whole batches from the independent board and restores focus without changing expanded styles',async()=>{
  const leg={id:'77',stage:'IN_TRANSIT',source_name:'广州成品仓',destination_name:'美国FBA',business_number:'SIM-77',shipped_units:'5',received_units:'2',unreceived_units:'3',settled_units:'0',receipt_dates:[],sources:[{id:'1',sku_id:'11',sku_label:'Black-L',actual_units:'2',received_units:'2',unreceived_units:'0',bindings:[],allocations:[]},{id:'2',sku_id:'12',sku_label:'Black-M',actual_units:'3',received_units:'0',unreceived_units:'3',bindings:[],allocations:[]}],transport:{record:null,events:[]}};
  const original=api.read.getMockImplementation()!;api.read.mockImplementation(path=>path.includes('transit-batches')?Promise.resolve({...batches,items:[leg],total:1}):original(path));
  mount('/production/stock?stock_styles=1,2&stock_q=Black&stock_batch=77');const button=await screen.findByRole('button',{name:'查看整批运输 SIM-77'});
  expect(screen.queryByRole('columnheader',{name:'运输中 / 到仓待核'})).not.toBeInTheDocument();
  const dialog=await screen.findByRole('dialog',{name:'运输批次'});await within(dialog).findByText('Black-M');expect(within(dialog).getByText('Black-L')).toBeInTheDocument();expect(screen.getAllByRole('dialog')).toHaveLength(1);
  expect(api.read.mock.calls.filter(([path])=>path.includes('transit-batches')).every(([path])=>!path.includes('stock_q')&&!path.includes('sku_id'))).toBe(true);
  await userEvent.click(screen.getByRole('button',{name:'关闭运输批次'}));await waitFor(()=>expect(button).toHaveFocus());expect(screen.getByTestId('sku-location')).toHaveTextContent('stock_styles=1%2C2');
});
it('converts legacy SKU transport deep links to whole batches instead of opening a single SKU modal',async()=>{
  mount('/production/stock?sku_id=11&sku_detail=1&stock_detail=transport');await screen.findByText('旧SKU运输链接已转为整批查询');expect(screen.queryByRole('dialog')).not.toBeInTheDocument();
  await waitFor(()=>expect(api.read.mock.calls.some(([path])=>path.includes('transit-batches')&&path.includes('sku_id=11'))).toBe(true));expect(api.read.mock.calls.some(([path])=>path.includes('sku-locations'))).toBe(false);
});
it('restores the batch trigger when its board loads after the deep-link window closes',async()=>{
  const original=api.read.getMockImplementation()!;let finish!: (value:unknown)=>void;
  const delayed=new Promise(resolve=>{finish=resolve;});
  api.read.mockImplementation(path=>path.includes('transit-batches')&&!path.includes('shipment_id=')?delayed:original(path));
  mount('/production/stock?stock_batch=77');await screen.findByRole('dialog',{name:'运输批次'});
  await userEvent.click(screen.getByRole('button',{name:'关闭运输批次'}));
  await act(async()=>{finish({...batches,items:[{id:'77',business_number:'SIM-LATE',stage:'IN_TRANSIT',sources:[],transport:{record:null}}],total:1});await delayed;});
  await waitFor(()=>expect(screen.getByRole('button',{name:'查看整批运输 SIM-LATE'})).toHaveFocus());
});
it('keeps historical identity separate and never links its transport or enables handling',async()=>{
  api.read.mockImplementation(path=>Promise.resolve(path.includes('/skus?')?catalog:path.includes('transport-summary')?summary:{...stock,items:[...stock.items,{...stock.items[0],sku_id:'99',sku_label:'SIM historical',identity_status:'pending',on_hand_units:'4',free_available_units:null}]}));
  display.read.mockResolvedValue({style_ids:['1','2','history:99'],revision:'1',can_manage:false});mount('/production/stock?sku_id=99&sku_detail=1',true);expect(await screen.findByText('历史商品身份待核')).toBeInTheDocument();expect(screen.queryByRole('button',{name:'办理'})).not.toBeInTheDocument();expect(api.read.mock.calls.some(([path])=>path.includes('sku-locations'))).toBe(false);
});
it('preserves catalog on a failed stock read and refreshes quantities without treating failure as zero',async()=>{
  let fail=true;api.read.mockImplementation(path=>path.includes('/skus?')?Promise.resolve(catalog):path.includes('transport-summary')?Promise.resolve(summary):fail?Promise.reject(new Error('SIM unavailable')):Promise.resolve(stock));
  mount('/production/stock?sku_id=11');await screen.findByText('库存读取未完成');expect(screen.getByRole('button',{name:'1112-Black-L · 全部仓库 · 查看明细'})).toHaveTextContent('Black');fail=false;
  await userEvent.click(screen.getByRole('button',{name:'重试库存读取'}));await waitFor(()=>expect(screen.getByRole('button',{name:'1112-Black-L · SIM FBA · SIM owner · 查看明细'})).toHaveTextContent(/^16$/));
});
it('does not invent full transport totals without full-scope projection',async()=>{
  api.read.mockImplementation(path=>Promise.resolve(path.includes('/skus?')?catalog:path.includes('transport-summary')?{items:[]}:stock));mount();await screen.findByRole('button',{name:'展开款号1112'});expect(screen.queryByRole('region',{name:'展示范围库存与整批运输汇总'})).not.toBeInTheDocument();await userEvent.click(screen.getByRole('button',{name:'更多'}));await userEvent.click(screen.getByRole('menuitem',{name:'查看库存汇总'}));expect(screen.getByRole('region',{name:'展示范围库存与整批运输汇总'})).toHaveTextContent('运输中待核');
});
it.each([['style_id=999','原链接不在当前展示范围'],['sku_id=999','原链接不在当前展示范围']])('keeps all styles and warns about an invalid deep link %s',async(query,title)=>{
  mount('/production/stock?'+query);await screen.findByText(title);expect(screen.getByRole('button',{name:'展开款号1112'})).toBeInTheDocument();expect(screen.getByRole('button',{name:'展开款号2121'})).toBeInTheDocument();
});

it('filters above the table and keeps every matching variant in a separate identity row',async()=>{
  mount('/production/stock?stock_styles=1,2');await screen.findByRole('button',{name:'收起款号1112'});await userEvent.click(screen.getByRole('button',{name:'筛选'}));const panel=screen.getByRole('region',{name:'库存筛选'});expect(panel.compareDocumentPosition(screen.getByRole('table'))&Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();await userEvent.type(screen.getByLabelText('筛选款号、颜色或SKU（可选）'),'Camel');expect(screen.getByRole('table')).toHaveTextContent('2121');expect(screen.queryByRole('button',{name:'收起款号1112'})).not.toBeInTheDocument();expect(screen.getByRole('cell',{name:'Camel'})).toBeInTheDocument();await userEvent.click(screen.getByRole('button',{name:'清除筛选'}));expect(screen.getByRole('button',{name:'收起款号1112'})).toBeInTheDocument();
});

it('shares manager selection with viewers and ignores browser and URL preferences', async () => {
  let ids: string[] = [];
  display.read.mockImplementation(() => Promise.resolve({style_ids:ids,revision:ids.length ? "1" : "0",can_manage:true}));
  display.write.mockImplementation((_path, options) => {
    ids=options.body.style_ids;
    return Promise.resolve({style_ids:ids,revision:"1",can_manage:true});
  });
  mount('/production/stock?stock_watch=2');
  await screen.findByText('管理员尚未设置展示款号');
  await userEvent.click(screen.getByRole('button',{name:'设置展示款号'}));
  const dialog=screen.getByRole('dialog',{name:'设置展示款号'});
  await userEvent.click(within(dialog).getByRole('checkbox',{name:'选择款号1112'}));
  await userEvent.click(within(dialog).getByRole('button',{name:'保存展示范围'}));
  await screen.findByRole('button',{name:'展开款号1112'});
  expect(display.write.mock.calls[0]?.[1].body).toMatchObject({expected_revision:'0',style_ids:['1']});
  cleanup();
  display.read.mockResolvedValue({style_ids:ids,revision:'1',can_manage:false});
  mount('/production/stock?stock_watch=2&style_id=2&sku_id=13&sku_detail=1');
  await screen.findByRole('button',{name:'展开款号1112'});
  expect(screen.queryByRole('button',{name:'设置展示款号'})).not.toBeInTheDocument();
  expect(screen.queryByRole('button',{name:/款号2121/})).not.toBeInTheDocument();
  expect(screen.queryByRole('dialog')).not.toBeInTheDocument();
  expect(screen.getByText('原链接不在当前展示范围')).toBeInTheDocument();
});
it('retains the saved display and unsaved choices when saving fails', async () => {
  const {ApiRequestError}=await import('../../api/client');
  display.read.mockResolvedValue({style_ids:['1'],revision:'1',can_manage:true});
  display.write.mockRejectedValue(new ApiRequestError(409,'display_revision_conflict','展示款号已更新'));
  mount();
  await userEvent.click(await screen.findByRole('button',{name:'设置展示款号'}));
  const dialog=screen.getByRole('dialog',{name:'设置展示款号'});
  await userEvent.click(within(dialog).getByRole('checkbox',{name:'选择款号2121'}));
  await userEvent.click(within(dialog).getByRole('button',{name:'保存展示范围'}));
  await within(dialog).findByText('展示款号已更新');
  expect(within(dialog).getByRole('checkbox',{name:'选择款号2121'})).toBeChecked();
  expect(screen.queryByRole('button',{name:'展开款号2121'})).not.toBeInTheDocument();
  expect(within(dialog).getByRole('button',{name:'重新读取展示清单'})).toBeInTheDocument();
});
it('supports clearing the shared list and explains empty scope to viewers', async () => {
  display.read.mockResolvedValue({style_ids:[],revision:'3',can_manage:false});
  mount('/production/stock?stock_watch=1,2');
  await screen.findByText('管理员尚未设置展示款号');
  expect(screen.queryByRole('button',{name:'设置展示款号'})).not.toBeInTheDocument();
  expect(screen.queryByRole('button',{name:'展开款号1112'})).not.toBeInTheDocument();
});
it('does not enable selection after a settings read failure', async () => {
  display.read.mockRejectedValue(new Error('SIM settings unavailable'));
  mount();
  await screen.findByText('展示范围读取未完成');
  expect(screen.queryByRole('button',{name:'设置展示款号'})).not.toBeInTheDocument();
  expect(screen.queryByRole('button',{name:'展开款号1112'})).not.toBeInTheDocument();
});
it.each([{principalId:2,siteId:1},{principalId:1,siteId:2}])('reads the server selection for the current boundary: %j',async boundary=>{
 render(<MemoryRouter><AuthzGenerationProvider boundary={{...boundary,roles:['viewer'],siteConfigVersionId:1}} onRevoked={()=>undefined}><SkuAcrossWarehouses/></AuthzGenerationProvider></MemoryRouter>);
 expect(await screen.findByRole('button',{name:'展开款号1112'})).toBeInTheDocument();
 expect(display.read).toHaveBeenCalled();
});

it('keeps selected styles and explains disabled writes, then saves and restores the shared table', async () => {
  let ids: string[] = [];
  display.read.mockImplementation(() => Promise.resolve({style_ids:ids,revision:ids.length ? '1' : '0',can_manage:true}));
  display.write.mockRejectedValueOnce(new ApiRequestError(403,'production_read_only','库存写入尚未启用。')).mockImplementation((_path, options) => {
    ids = options.body.style_ids;
    return Promise.resolve({style_ids:ids,revision:'1',can_manage:true});
  });
  mount('/production/stock');
  await screen.findByText('管理员尚未设置展示款号');
  await userEvent.click(screen.getByRole('button',{name:'设置展示款号'}));
  const dialog = screen.getByRole('dialog',{name:'设置展示款号'});
  await userEvent.click(within(dialog).getByRole('checkbox',{name:'选择款号1112'}));
  await userEvent.click(within(dialog).getByRole('button',{name:'保存展示范围'}));
  await within(dialog).findByText('库存写入尚未启用。');
  expect(within(dialog).getByRole('checkbox',{name:'选择款号1112'})).toBeChecked();
  expect(within(dialog).getByRole('button',{name:'保存展示范围'})).toBeEnabled();
  expect(screen.queryByRole('button',{name:'展开款号1112'})).not.toBeInTheDocument();
  await userEvent.click(within(dialog).getByRole('button',{name:'保存展示范围'}));
  await screen.findByRole('button',{name:'展开款号1112'});
  expect(screen.queryByRole('dialog',{name:'设置展示款号'})).not.toBeInTheDocument();
  expect(display.write).toHaveBeenCalledTimes(2);
  cleanup();
  mount('/production/stock');
  await screen.findByRole('button',{name:'展开款号1112'});
});
