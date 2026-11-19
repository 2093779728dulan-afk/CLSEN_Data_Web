import { render, screen, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { expect, it, vi } from 'vitest';
import { requestApi } from '../../../api/client';
import { DetailPanel } from './DetailPanel';
import type { SheetSku } from './model';
vi.mock('../../../api/client', () => ({ requestApi: vi.fn() }));
it('shows zero stock without status/version UI and keeps the version-bound detail request', async () => {
  const items = ['1101-Navy-L', '1101-Navy-S'].map((sku, index): SheetSku => ({ sku_id: String(index + 1), style_id: '1', style_code: '1101', sku, standard_color: 'Navy', standard_size: index ? 'S' : 'L', values: {}, alert: { level: 'normal', configurable: false } }));
  vi.mocked(requestApi).mockImplementation(url => Promise.resolve({ grouped: !url.includes('sku_id='), columns: ['SKU', '数量', '状态', '说明'], rows: items.map((item, index) => ({ sku_id: item.sku_id, cells: [item.sku, index ? '0' : '4', '完整', '内部模拟记录说明'] })), stock_explanation: { on_hand_units: { value: '4', state: 'ready' }, free_available_units: { value: '4', state: 'ready' }, defective_units: { value: '0', state: 'ready' } }, total: { value: '4', state: 'ready', partial: false, reason: '无记录按0' }, total_rows: 2, page_size: 20, report_provenance: { version: 'internal' } }));
  render(<DetailPanel row={{ sku: '1101', grouped: true, items }} request={{ type: 'stock', key: 'domestic', label: '广州成品仓库存', range: { start: '2026-11-10', end: '2026-11-10' } }} cutoff="2026-11-10" query="domestic_warehouse_id=1&domestic_owner_id=1&fba_scope_id=1&as_of=2026-11-10" version="frozen-version" close={vi.fn()} openSettings={vi.fn()} />);
  const table = await screen.findByRole('table', { name: '广州成品仓库存对应记录' });
  expect(within(table).getAllByRole('columnheader').map(c => c.textContent)).toEqual(['SKU', '数量']);
  expect(within(table).getByRole('row', { name: '1101-Navy-S 0' })).toBeVisible();
  expect(screen.queryByText('版本', { selector: 'summary' })).toBeNull();
  expect(screen.queryByText('状态', { selector: 'summary' })).toBeNull();
  expect(vi.mocked(requestApi).mock.calls[0]![0]).toContain('version=frozen-version');
  await userEvent.click(within(table).getByRole('button', { name: '1101-Navy-S' }));
  expect(await screen.findByRole('button', { name: '返回整款' })).toBeVisible();
  expect(screen.queryByRole('columnheader', { name: '说明' })).not.toBeInTheDocument();
  expect(screen.queryByText('内部模拟记录说明')).not.toBeInTheDocument();
  expect(screen.queryByText(/实际在库|本地账面可售|不可售/)).not.toBeInTheDocument();
  expect(screen.getByText('合计 4')).toBeVisible();
});


it('shows a compact comparison with period columns and complete totals, without repeated explanations', async () => {
 const items=[{sku_id:'1',style_id:'1',style_code:'2305',sku:'2305-Black-M',standard_color:'Black',standard_size:'M',values:{},alert:{level:'normal',configurable:false}}] as SheetSku[];
 const quantity=(value:string)=>({value,state:'ready',partial:false,reason:'internal evidence'});
 vi.mocked(requestApi).mockResolvedValue({grouped:true,columns:['SKU','本期','上期','增减'],rows:[{sku_id:'1',cells:['2305-Black-M','5','3','2']}],comparison_totals:[quantity('5'),quantity('3'),quantity('2')],total:quantity('2'),total_rows:1,page_size:20,report_provenance:{}});
 render(<DetailPanel row={{sku:'2305',items,grouped:true}} request={{type:'comparison',key:'week.returnsMom',label:'退货 · 对比上周',range:{start:'2026-10-26',end:'2026-11-01'},comparison:{metric:'returns',current:{start:'2026-10-26',end:'2026-11-01'},previous:{start:'2026-10-19',end:'2026-10-25'}}}} cutoff="2026-11-01" query="as_of=2026-11-01" version="frozen-version" close={vi.fn()} openSettings={vi.fn()}/>);
 const table=await screen.findByRole('table',{name:'退货 · 对比上周对应记录'});
 expect(within(table).getAllByRole('columnheader').map(c=>c.textContent)).toEqual(['SKU','本期10/26—11/01','上期10/19—10/25','增减']);
 expect(within(table).getByRole('row',{name:'2305-Black-M 5 3 +2'})).toBeVisible();
 expect(within(table).getByRole('row',{name:'合计 5 3 +2'})).toBeVisible();
 expect(screen.queryByText('合计 2',{exact:true})).not.toBeInTheDocument();
 expect(screen.queryByText('internal evidence',{exact:true})).not.toBeInTheDocument();
 await userEvent.click(within(table).getByRole('button',{name:'2305-Black-M'}));
 expect(vi.mocked(requestApi).mock.calls.at(-1)![0]).toContain('metric=week.returnsMom');
 expect(vi.mocked(requestApi).mock.calls.at(-1)![0]).toContain('sku_id=1');
});


it('shows user production labels while hiding internal tracking metadata', async () => {
 const item={sku_id:'1',style_id:'1',style_code:'2305',sku:'2305-Black-M',standard_color:'Black',standard_size:'M',values:{},alert:{level:'normal',configurable:false}} as SheetSku;
 vi.mocked(requestApi).mockResolvedValue({grouped:false,columns:['订单','工厂直发','待生产','待入库','跟进','生产状态','修订','说明'],rows:[{sku_id:'1',cells:['TEST-1','4','30','6','OPEN','车缝中','2','内部说明']}],total:{value:'30',state:'ready',partial:false,reason:''},total_rows:1,page_size:20});
 render(<DetailPanel row={{sku:item.sku,items:[item],grouped:false}} request={{type:'production',key:'production.pending',label:'待生产',range:{start:'2026-11-13',end:'2026-11-13'}}} cutoff="2026-11-13" query="as_of=2026-11-13" version="frozen-version" close={vi.fn()} openSettings={vi.fn()}/>);
 const table=await screen.findByRole('table',{name:'待生产对应记录'});
 expect(within(table).getAllByRole('columnheader').map(cell=>cell.textContent)).toEqual(['订单','待生产','待入库','生产状态']);
 expect(within(table).getByRole('row',{name:'TEST-1 30 6 车缝中'})).toBeVisible();
 expect(within(table).queryByRole('columnheader',{name:'工厂直发'})).not.toBeInTheDocument();
 expect(screen.getByText('合计')).toHaveTextContent('合计 30');
 expect(screen.getByText('2026/11/13')).toBeVisible();
 expect(within(table).getByText('车缝中')).toBeVisible();
 expect(within(table).queryByText('OPEN')).not.toBeInTheDocument();
});

it('keeps dated daily quantities while removing repeated report-basis copy', async () => {
 const item={sku_id:'1',style_id:'1',style_code:'2305',sku:'2305-Black-M',standard_color:'Black',standard_size:'M',values:{},alert:{level:'normal',configurable:false}} as SheetSku;
 vi.mocked(requestApi).mockResolvedValue({grouped:false,columns:['发生日','退货','口径'],rows:[{sku_id:'1',cells:['2026-10-27','2','重复的报表口径说明']}],total:{value:'2',state:'partial',partial:true,reason:'coverage evidence retained'},total_rows:1,page_size:20,report_provenance:{}});
 render(<DetailPanel row={{sku:item.sku,items:[item],grouped:false}} request={{type:'returns',key:'week.returns',label:'退货',range:{start:'2026-10-26',end:'2026-11-01'}}} cutoff="2026-11-01" query="as_of=2026-11-01" version="frozen-version" close={vi.fn()} openSettings={vi.fn()}/>);
 const table=await screen.findByRole('table',{name:'退货对应记录'});
 expect(within(table).getAllByRole('columnheader').map(c=>c.textContent)).toEqual(['发生日','退货']);
 expect(within(table).getByRole('row',{name:'2026-10-27 2'})).toBeVisible();
 expect(screen.queryByText('重复的报表口径说明')).not.toBeInTheDocument();
 expect(screen.getByText('合计 2')).toHaveAttribute('title','coverage evidence retained');
});
