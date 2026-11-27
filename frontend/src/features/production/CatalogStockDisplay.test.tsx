import userEvent from '@testing-library/user-event';
import { render, screen, within } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import { expect, it } from 'vitest';
import { WarehouseInventory, type WarehouseStock } from './WarehouseCenter';
import { FbaInventoryOverview } from './FbaInventoryOverview';
import type { DirectoryRecord } from './directoryTypes';
import type { FbaInventoryView, FbaScope } from './fbaTypes';
import type { Sku } from './types';
const catalog: Sku[] = [
  { sku_id: '1', style_id: '10', style_code: '1101', code: '1101-Navy-L', label: '1101-Navy-L', standard_color: 'Navy', standard_size: 'L', status: 'active', catalog_version: '1:1' },
  { sku_id: '2', style_id: '10', style_code: '1101', code: '1101-Navy-S', label: '1101-Navy-S', standard_color: 'Navy', standard_size: 'S', status: 'active', catalog_version: '1:1' },
];
it('joins catalog-only domestic SKUs as zero without modifying warehouse facts', () => {
  const stock: WarehouseStock = { scopes: [], items: [{ warehouse_id: '1', owner_id: '1', sku_id: '1', state: 'ready', on_hand_units: '4', free_available_units: '4', qualified_units: '4', pending_units: '0', defective_units: '0', held_units: '0', reserved_units: '0' }] };
  render(<MemoryRouter><WarehouseInventory stock={stock} catalog={catalog} record={{ id: '1' } as DirectoryRecord} owner="1" writable={false} /></MemoryRouter>);
  expect(screen.getByRole('button', { name: '1101 Navy S 库存明细 SKU 2' })).toHaveTextContent('');
  expect(stock.items).toHaveLength(1);
});
it('joins catalog-only FBA SKUs as zero without creating platform identities or movements', () => {
  const view: FbaInventoryView = { on_hand: '4', available: '4', latest_movement_at: null, stock_effect: false, groups: [{ style_id: '10', on_hand: '4', items: [{ sku_id: '1', style_id: '10', seller_sku: '1101-Navy-L', on_hand: '4', available: '4', received: '4', fulfilled: '0', returned: '0' }] }], movements: [], issues: [] };
  render(<MemoryRouter><FbaInventoryOverview view={view} catalog={catalog} scope={{ warehouse_id: '2', owner_id: '1' } as FbaScope} /></MemoryRouter>);
  expect(screen.queryByRole('button', { name: '查看1101-Navy-S库存变动' })).not.toBeInTheDocument();
  expect(view.groups[0]!.items).toHaveLength(1);
  expect(view.movements).toHaveLength(0);
});


it('keeps zero SKU operations and cross-shop stock while distinguishing absent sizes from a filtered zero', async () => {
 const extra:Sku={...catalog[0]!,sku_id:'3',style_id:'20',style_code:'2201',code:'2201-White-M',label:'2201-White-M',standard_color:'White',standard_size:'M'};
 const base={warehouse_id:'1',owner_id:'1',state:'ready',free_available_units:'4',qualified_units:'4',pending_units:'0',defective_units:'0',held_units:'0',reserved_units:'0'};
 const stock:WarehouseStock={scopes:[],items:[{...base,sku_id:'1',on_hand_units:'4'},{...base,sku_id:'99',style_code:'OTHER',standard_color:'Black',standard_size:'XXXL',on_hand_units:'270'}]};
 const tree=(value:WarehouseStock)=><MemoryRouter><WarehouseInventory stock={value} catalog={[...catalog,extra]} record={{id:'1'} as DirectoryRecord} owner="1" writable /></MemoryRouter>;
 const view=render(tree(stock));
 const table=screen.getByRole('table',{name:'本仓款色尺码库存'});
 expect(within(table).getByRole('button',{name:/^OTHER · (?:查看|收起)$/})).toBeVisible();
 expect(within(table).getByRole('columnheader',{name:'XXXL'})).toBeVisible();
 expect(screen.queryByRole('button',{name:/^2201 · (?:查看|收起)$/})).not.toBeInTheDocument();
 const zero=within(table).getByRole('button',{name:'1101 Navy S 库存明细 SKU 2'});
 expect(zero).toHaveTextContent('');expect(zero.closest('td')).not.toHaveAttribute('title');
 expect(within(table).getByRole('cell',{name:'1101 Navy M：未建档此尺码'})).toHaveAttribute('title','未建档此尺码');
 expect(screen.queryByText('点击数量，查看状态明细')).not.toBeInTheDocument();
 await userEvent.click(zero);
 const detail=screen.getByRole('region',{name:'规格库存明细'});
 expect(within(detail).getByRole('link',{name:'盘点此规格'})).toHaveAttribute('href',expect.stringContaining('sku_id=2'));
 expect(within(detail).getByRole('link',{name:'出货此规格'})).toHaveAttribute('href',expect.stringContaining('sku_id=2'));
 expect(screen.getByRole('link',{name:'入库'})).toBeVisible();
 expect(screen.getByRole('link',{name:'出货'})).toBeVisible();
 await userEvent.type(screen.getByRole('searchbox',{name:'搜索本仓款号、颜色或尺码'}),'L');
 const blankS=within(table).getAllByRole('row').find(row=>row.textContent?.includes('Navy'))!.children[2];
 expect(blankS).not.toHaveAttribute('title');
 await userEvent.clear(screen.getByRole('searchbox',{name:'搜索本仓款号、颜色或尺码'}));
 view.rerender(tree({...stock,items:[...stock.items,{...base,sku_id:'2',on_hand_units:'5'}]}));
 expect(screen.getByRole('button',{name:'1101 Navy S 库存明细 SKU 2'})).toHaveTextContent('5');
 expect(stock.items).toHaveLength(2);
});


it('hides a fully zero style and restores it when stock arrives, while retaining unknown balances', () => {
 const extra:Sku={...catalog[0]!,sku_id:'3',style_id:'20',style_code:'2201',code:'2201-White-M',label:'2201-White-M',standard_color:'White',standard_size:'M'};
 const base={warehouse_id:'1',owner_id:'1',state:'ready',free_available_units:'0',qualified_units:'0',pending_units:'0',defective_units:'0',held_units:'0',reserved_units:'0'};
 const stock:WarehouseStock={scopes:[],items:[{...base,sku_id:'1',on_hand_units:'0'},{...base,sku_id:'3',on_hand_units:null}]};
 const tree=(value:WarehouseStock)=><MemoryRouter><WarehouseInventory stock={value} catalog={[...catalog,extra]} record={{id:'1'} as DirectoryRecord} owner="1" writable /></MemoryRouter>;
 const view=render(tree(stock));
 expect(screen.queryByRole('button',{name:/^1101 · (?:查看|收起)$/})).not.toBeInTheDocument();
 expect(screen.getByRole('button',{name:/^2201 · (?:查看|收起)$/})).toBeVisible();
 expect(screen.getByRole('link',{name:'入库'})).toBeVisible();
 view.rerender(tree({...stock,items:[{...stock.items[0]!,on_hand_units:'3'},stock.items[1]!]}));
 expect(screen.getByRole('button',{name:/^1101 · (?:查看|收起)$/})).toBeVisible();
 expect(screen.getByRole('button',{name:'1101 Navy L 库存明细 SKU 1'})).toHaveTextContent('3');
 expect(screen.getByRole('button',{name:'1101 Navy S 库存明细 SKU 2'})).toHaveTextContent('');
 view.rerender(tree({...stock,items:[{...stock.items[0]!,on_hand_units:'0'},stock.items[1]!]}));
 expect(screen.queryByRole('button',{name:/^1101 · (?:查看|收起)$/})).not.toBeInTheDocument();
 expect(stock.items[0]!.on_hand_units).toBe('0');
});
