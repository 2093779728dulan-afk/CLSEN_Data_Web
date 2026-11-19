import { act, cleanup, fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { createMemoryRouter, RouterProvider } from 'react-router-dom';
import { afterEach, beforeEach, expect, it, vi } from 'vitest';
import { requestApi } from '../../../api/client';
import { AuthzGenerationProvider } from '../../../app/AuthzGenerationContext';
import { InventoryOverviewSheet } from './InventoryOverviewSheet';
import type { Quantity, SheetResponse } from './model';

vi.mock('../../../api/client', async importOriginal => ({
  ...await importOriginal<typeof import('../../../api/client')>(),
  requestApi: vi.fn(),
}));

const options = {
  today: '2026-11-11', reporting_timezone: 'America/Los_Angeles',
  domestic: [{ warehouse_id: '1', owner_id: '1', warehouse_name: '模拟广州仓', owner_name: '模拟自有', type: 'FACTORY' }],
  fba: [{ id: '1', warehouse_name: '模拟FBA', store_evidence: 'SIMULATED' }],
};

function sheet(date: string, units: string): SheetResponse {
  const values: Record<string, Quantity> = {};
  for (const key of ['production.pending', 'production.pendingReceipt', 'domestic', 'available', 'transit', 'units', 'returns', 'net', 'week.units', 'week.previous.units', 'week.returns', 'week.previous.returns']) {
    values[key] = { value: units, state: 'ready', partial: false, reason: '' };
  }
  return {
    version: date, today: options.today, as_of: date, reporting_timezone: options.reporting_timezone, cumulative_from: date,
    rows: [{ sku_id: '1', style_id: '1', style_code: '1202', sku: '1202-Sand-M', standard_color: 'Sand', standard_size: 'M', values, alert: { level: 'normal', configurable: true } }],
    totals: values, issues: [], resolved_scope: { domestic: { warehouse_id: '1', owner_id: '1' }, fba: { id: '1' } },
    settings: { revision: '1', style_ids: [], sku_alert_settings: {}, can_manage: true },
    display_styles: [{ id: '1', style_code: '1202', sku_count: 1 }],
  };
}

function open(entry = '/home') {
  const router = createMemoryRouter([{ path: '/home', element: <AuthzGenerationProvider boundary={{ principalId: 1, siteId: 1, siteConfigVersionId: 1, roles: ['admin'] }} onRevoked={vi.fn()}><InventoryOverviewSheet /></AuthzGenerationProvider> }], { initialEntries: [entry] });
  return render(<RouterProvider router={router} />);
}

beforeEach(() => {
  vi.clearAllMocks();
  const NativeRequest = globalThis.Request;
  vi.stubGlobal('Request', class extends NativeRequest {
    constructor(input: RequestInfo | URL, init?: RequestInit) {
      const { signal, ...options } = init ?? {};
      super(input, options);
      if (signal) Object.defineProperty(this, 'signal', { value: signal });
    }
  });
  vi.stubGlobal('ResizeObserver', class { observe() {} disconnect() {} });
  vi.stubGlobal('requestIdleCallback', vi.fn().mockReturnValue(1));
  vi.stubGlobal('cancelIdleCallback', vi.fn());
  HTMLElement.prototype.scrollTo = vi.fn();
  window.matchMedia = vi.fn().mockReturnValue({ matches: true });
});
afterEach(() => { cleanup(); vi.unstubAllGlobals(); });

it('shows manual production labels only after expanding the style', async () => {
  const value = sheet(options.today, '21');
  value.rows[0]!.production_statuses = [{ order_id: '5', order_number: 'TEST-5', status: '等待面料' }];
  vi.mocked(requestApi).mockImplementation(url => Promise.resolve(url.endsWith('/options') ? options : value));
  open();
  const expand = await screen.findByRole('button', { name: '展开款号1202' });
  expect(screen.queryByText('等待面料')).not.toBeInTheDocument();
  await userEvent.click(expand);
  const label = await screen.findByText('等待面料');
  expect(label).toHaveAttribute('title', 'TEST-5：等待面料');
  expect(label.closest('tr')).toHaveStyle({ height: '46px' });
});

it('requires an explicit scope when multiple warehouses are available', async () => {
  vi.mocked(requestApi).mockImplementation(url => url.endsWith('/options')
    ? Promise.resolve({ ...options, domestic: [...options.domestic, { ...options.domestic[0], warehouse_id: '2' }] })
    : Promise.resolve(sheet(options.today, '21')));
  const first = open();
  await screen.findByText('查看范围待确定');
  expect(vi.mocked(requestApi).mock.calls.filter(([url]) => url.includes('overview-sheet?'))).toHaveLength(0);
  first.unmount();
  open('/home?domestic_warehouse_id=1&domestic_owner_id=1&fba_scope_id=1');
  await screen.findByRole('button', { name: '展开款号1202' });
  expect(vi.mocked(requestApi).mock.calls.filter(([url]) => url.includes('overview-sheet?'))).toHaveLength(1);
});

it('keeps the previous date and values together until the latest request succeeds', async () => {
  const pending: { date: string; signal?: AbortSignal; resolve: (value: SheetResponse) => void }[] = [];
  vi.mocked(requestApi).mockImplementation((url, init) => {
    if (url.endsWith('/options')) return Promise.resolve(options);
    const date = new URL(url, 'http://localhost').searchParams.get('as_of')!;
    if (date === options.today) return Promise.resolve(sheet(date, '9007199254740993'));
    return new Promise(resolve => pending.push({ date, signal: init?.signal ?? undefined, resolve }));
  });
  open();
  await screen.findByRole('button', { name: '展开款号1202' });
  expect(document.querySelector('.sheet')).toHaveStyle({ '--available-width': '200px' });
  const date = screen.getByLabelText('统计截止日期');
  fireEvent.change(date, { target: { value: '2026-11-09' } });
  await waitFor(() => expect(pending).toHaveLength(1));
  expect(screen.getByRole('button', { name: '库存明细' })).toHaveTextContent('2026/11/11');
  expect(screen.getByRole('button', { name: '导出 Excel' })).toBeDisabled();
  fireEvent.change(date, { target: { value: '2026-11-08' } });
  await waitFor(() => expect(pending).toHaveLength(2));
  await act(async () => { pending[1]!.resolve(sheet('2026-11-08', '19')); await Promise.resolve(); });
  expect(screen.getByRole('button', { name: '库存明细' })).toHaveTextContent('2026/11/08');
  await act(async () => { pending[0]!.resolve(sheet('2026-11-09', '20')); await Promise.resolve(); });
  expect(pending[0]!.signal?.aborted).toBe(true);
  expect(screen.getByRole('button', { name: '库存明细' })).toHaveTextContent('2026/11/08');
  expect(screen.getByRole('button', { name: '导出 Excel' })).toBeEnabled();
});

it('debounces search and renders evidence quantities without explanatory cell text', async () => {
  vi.mocked(requestApi).mockImplementation(url => {
    if (url.endsWith('/options')) return Promise.resolve(options);
    const value = sheet(options.today, '21');
    value.rows[0]!.values.transit = { value: null, state: 'unknown', partial: true, reason: '验收待补', evidence: { label: '待核接收', units: '152' } };
    return Promise.resolve(value);
  });
  open();
  await screen.findByRole('button', { name: '展开款号1202' });
  const input = screen.getByRole('textbox', { name: '搜索SKU或款号' });
  await userEvent.type(input, '1202');
  await waitFor(() => expect(vi.mocked(requestApi).mock.calls.filter(([url]) => url.includes('q=1202'))).toHaveLength(1));
  expect(within(screen.getByRole('table', { name: '完整库存销售退货总表' })).getAllByRole('button', { name: /待核接收明细/ })[0]).toHaveTextContent('152');
  expect(document.querySelector('.sheet-source')).toBeNull();
  expect(screen.queryByRole('combobox', { name: '总表成品仓与货主' })).not.toBeInTheDocument();
});

it('keeps only pending production columns and leaves missing quantities blank without stars', async () => {
  vi.mocked(requestApi).mockImplementation(url => {
    if (url.endsWith('/options')) return Promise.resolve(options);
    const value = sheet(options.today, '21');
    value.rows[0]!.values.domestic = { value: null, state: 'not_ready', partial: true, reason: '此规格未建账' };
    value.rows[0]!.values['week.units'] = { value: '21', state: 'partial', partial: true, reason: '期间缺报' };
    value.rows[0]!.values['week.previous.units'] = { value: '19', state: 'partial', partial: true, reason: '期间缺报' };
    return Promise.resolve(value);
  });
  open();
  await screen.findByRole('button', { name: '展开款号1202' });
  const table = screen.getByRole('table', { name: '完整库存销售退货总表' });
  expect(within(table).getByRole('button', { name: '按待生产排序' })).toBeVisible();
  expect(within(table).getByRole('button', { name: '按待入库排序' })).toBeVisible();
  expect(within(table).queryByRole('button', { name: '按下单数量排序' })).toBeNull();
  expect(within(table).queryByRole('button', { name: '按已生产排序' })).toBeNull();
  expect(within(table).queryByRole('button', { name: '按已入库排序' })).toBeNull();
  expect(table.textContent).not.toMatch(/[∗*—]/);
  expect(within(table).getByRole('button', { name: /查看1202广州成品仓/ })).toHaveTextContent('');
  expect(within(table).getByRole('button', { name: '查看1202销量2026-11-09至2026-11-11' })).toHaveAttribute('title', '期间缺报');
  expect(vi.mocked(requestApi).mock.calls.some(([url]) => url.includes('summary=1'))).toBe(true);
});

it('restores displayed controls after a failed update and retries the failed conditions', async () => {
  let fail = true;
  vi.mocked(requestApi).mockImplementation(url => {
    if (url.endsWith('/options')) return Promise.resolve(options);
    const date = new URL(url, 'http://localhost').searchParams.get('as_of')!;
    if (date !== options.today && fail) return Promise.reject(new Error('模拟读取失败'));
    return Promise.resolve(sheet(date, '21'));
  });
  open();
  await screen.findByRole('button', { name: '展开款号1202' });
  const date = screen.getByLabelText('统计截止日期');
  fireEvent.change(date, { target: { value: '2026-11-09' } });
  await screen.findByText('更新失败');
  expect(date).toHaveValue(options.today);
  expect(screen.getByRole('button', { name: '库存明细' })).toHaveTextContent('2026/11/11');
  fail = false;
  await userEvent.click(screen.getByRole('button', { name: '重试' }));
  await waitFor(() => expect(date).toHaveValue('2026-11-09'));
  expect(screen.getByRole('button', { name: '库存明细' })).toHaveTextContent('2026/11/09');
});

it('uses color-only alerts for styles and SKUs, leaves totals plain and opens zero-stock details', async () => {
  const value = sheet(options.today, '0');
  const base = value.rows[0]!;
  value.rows = ['0', '5', '50', '0', '5'].map((available, index) => ({
    ...base, sku_id: String(index + 1), sku: `1202-Sand-${['M', 'L', 'XL', 'S', 'XS'][index]}`,
    standard_size: ['M', 'L', 'XL', 'S', 'XS'][index]!,
    values: { ...base.values, available: { value: available, state: 'ready', partial: false, reason: '模拟库存依据' } },
  }));
  value.settings.sku_alert_settings = { '1': { '4': { threshold: '20', replenish: false }, '5': { threshold: '20', replenish: false } } };
  vi.mocked(requestApi).mockImplementation(url => {
    if (url.endsWith('/options')) return Promise.resolve(options);
    if (url.includes('/details?')) return Promise.resolve({ grouped: false, columns: ['日期', '数量'], rows: [], total: base.values.available, total_rows: 0, page_size: 20, report_provenance: {} });
    return Promise.resolve(value);
  });
  open();
  await userEvent.click(await screen.findByRole('button', { name: '展开款号1202' }));
  const cells = [...document.querySelectorAll('.inventory-sheet > tbody > tr:not(.expanded-row) > td[data-column="available"]')];
  expect(cells[0]).toHaveAttribute('data-alert', 'empty');
  expect(cells[0]).toHaveTextContent('60');
  for (const [size, level, quantity] of [['M', 'empty', ''], ['L', 'low', '5'], ['XL', 'normal', '50'], ['S', 'sold-out', ''], ['XS', 'normal', '5']]) {
    const cell = screen.getByRole('button', { name: new RegExp(`^查看1202-Sand-${size}可售库存明细`) }).closest('td')!;
    expect(cell).toHaveAttribute('data-alert', level);
    expect(cell.textContent).toBe(quantity);
  }
  expect(cells.every(cell => cell.querySelectorAll('button').length === 1 && !cell.querySelector('svg'))).toBe(true);
  const footer = document.querySelector('.inventory-sheet tfoot td[data-column="available"]')!;
  expect(footer).not.toHaveAttribute('data-alert');
  expect(footer.querySelector('button,svg')).toBeNull();
  const zero = screen.getByRole('button', { name: '查看1202-Sand-M可售库存明细，缺货' });
  expect(zero).toHaveAttribute('title', expect.stringContaining('提醒值20件'));
  expect(zero).toHaveAttribute('title', expect.stringContaining('模拟库存依据'));
  await userEvent.click(zero);
  await screen.findByRole('table', { name: '美国FBA可售对应记录' });
  expect(vi.mocked(requestApi).mock.calls.some(([url]) => url.includes('/details?') && url.includes('metric=available') && url.includes('sku_id=1') && url.includes('version=2026-11-11'))).toBe(true);
  await userEvent.click(screen.getByRole('button', { name: '库存提醒设置' }));
  expect(await screen.findByRole('table', { name: 'SKU库存提醒设置' })).toBeVisible();
});

it('shows a visited date immediately, validates it before export and restores confirmed data on failure', async () => {
  let calls = 0;
  let reject: (error: Error) => void = () => {};
  vi.mocked(requestApi).mockImplementation(url => {
    if (url.endsWith('/options')) return Promise.resolve(options);
    calls++;
    const date = new URL(url, 'http://localhost').searchParams.get('as_of')!;
    if (calls <= 2) return Promise.resolve(sheet(date, date === options.today ? '21' : '19'));
    return new Promise((_, fail) => { reject = fail; });
  });
  open();
  await screen.findByRole('button', { name: '展开款号1202' });
  fireEvent.change(screen.getByLabelText('统计截止日期'), { target: { value: '2026-11-09' } });
  await waitFor(() => expect(document.querySelector('.sheet')).toHaveAttribute('aria-busy', 'false'));
  expect(screen.getByRole('button', { name: '库存明细' })).toHaveTextContent('2026/11/09');
  fireEvent.change(screen.getByLabelText('统计截止日期'), { target: { value: options.today } });
  await waitFor(() => expect(calls).toBe(3));
  expect(screen.getByRole('button', { name: '库存明细' })).toHaveTextContent('2026/11/11');
  expect(screen.getByRole('button', { name: '查看1202广州成品仓2026-11-11至2026-11-11' })).toHaveTextContent('21');
  expect(screen.getByRole('button', { name: '导出 Excel' })).toBeDisabled();
  await act(async () => { reject(new Error('缓存核对失败')); await Promise.resolve(); });
  await screen.findByText('更新失败');
  expect(screen.getByRole('button', { name: '库存明细' })).toHaveTextContent('2026/11/09');
  expect(screen.getByLabelText('统计截止日期')).toHaveValue('2026-11-09');
});

it.each(['focus', 'visibilitychange'])('replaces cached quantities and clears visited dates on %s', async event => {
  let calls = 0;
  const pending: ((value: SheetResponse) => void)[] = [];
  vi.mocked(requestApi).mockImplementation(url => {
    if (url.endsWith('/options')) return Promise.resolve(options);
    const date = new URL(url, 'http://localhost').searchParams.get('as_of')!;
    return ++calls <= 2 ? Promise.resolve(sheet(date, '21')) : new Promise(resolve => pending.push(resolve));
  });
  open();
  await screen.findByRole('button', { name: '展开款号1202' });
  fireEvent.change(screen.getByLabelText('统计截止日期'), { target: { value: '2026-11-09' } });
  await waitFor(() => expect(document.querySelector('.sheet')).toHaveAttribute('aria-busy', 'false'));
  fireEvent.change(screen.getByLabelText('统计截止日期'), { target: { value: options.today } });
  await waitFor(() => expect(pending).toHaveLength(1));
  const fresh = { ...sheet(options.today, '99'), version: 'updated-after-stock-or-report-change' };
  await act(async () => { pending[0]!(fresh); await Promise.resolve(); });
  expect(screen.getByRole('button', { name: '查看1202广州成品仓2026-11-11至2026-11-11' })).toHaveTextContent('99');
  expect(screen.getByRole('button', { name: '导出 Excel' })).toBeEnabled();
  fireEvent(event === 'focus' ? window : document, new Event(event));
  await waitFor(() => expect(pending).toHaveLength(2));
  await act(async () => { pending[1]!(fresh); await Promise.resolve(); });
  fireEvent.change(screen.getByLabelText('统计截止日期'), { target: { value: '2026-11-09' } });
  await waitFor(() => expect(pending).toHaveLength(3));
  expect(screen.getByRole('button', { name: '库存明细' })).toHaveTextContent('2026/11/11');
  expect(screen.getByRole('button', { name: '导出 Excel' })).toBeDisabled();
});

it('prepares the previous period while idle and promotes the same request when clicked', async () => {
  const idle: (() => void)[] = [];
  let finish: (value: SheetResponse) => void = () => {};
  vi.stubGlobal('requestIdleCallback', vi.fn((callback: () => void) => { idle.push(callback); return idle.length; }));
  vi.mocked(requestApi).mockImplementation(url => {
    if (url.endsWith('/options')) return Promise.resolve(options);
    const date = new URL(url, 'http://localhost').searchParams.get('as_of')!;
    return date === options.today ? Promise.resolve(sheet(date, '21')) : new Promise(resolve => { finish = resolve; });
  });
  open();
  await screen.findByRole('button', { name: '展开款号1202' });
  act(() => { idle.at(-1)!(); });
  await waitFor(() => expect(vi.mocked(requestApi).mock.calls.some(([url]) => url.includes('as_of=2026-11-08'))).toBe(true));
  await userEvent.click(screen.getByRole('button', { name: '上一周' }));
  expect(vi.mocked(requestApi).mock.calls.filter(([url]) => url.includes('as_of=2026-11-08'))).toHaveLength(1);
  expect(screen.getByRole('button', { name: '导出 Excel' })).toBeDisabled();
  await act(async () => { finish(sheet('2026-11-08', '19')); await Promise.resolve(); });
  expect(screen.getByRole('button', { name: '库存明细' })).toHaveTextContent('2026/11/08');
  expect(screen.getByRole('button', { name: '导出 Excel' })).toBeEnabled();
});

it('keeps the same sheet in fullscreen, restores its background on Escape and on unmount', async () => {
  vi.mocked(requestApi).mockImplementation(url => Promise.resolve(url.endsWith('/options') ? options : sheet(options.today, '21')));
  const background = document.createElement('button'); background.textContent = '模拟外部导航'; document.body.append(background);
  const overflow = document.body.style.overflow;
  try {
    document.body.style.overflow = 'scroll';
    const view = open('/home?q=1202');
    await screen.findByRole('button', { name: '收起款号1202' });
    const table = screen.getByRole('table', { name: '完整库存销售退货总表' });
    const calls = vi.mocked(requestApi).mock.calls.length;
    await userEvent.click(screen.getByRole('button', { name: '全屏查看' }));
    expect(table.closest('.sheet')).toHaveClass('is-fullscreen');
    expect(table.closest('main')).not.toHaveClass('is-fullscreen');
    expect(screen.getByRole('heading', { name: '库存变动总表' }).closest('header')?.inert).toBe(true);
    expect(screen.getByRole('search', { name: '筛选总表' }).inert).toBe(true);
    expect(screen.getByRole('button', { name: '退出全屏' })).toHaveFocus();
    expect(screen.getByRole('textbox', { name: '搜索SKU或款号' })).toHaveValue('1202');
    expect(screen.getByRole('table', { name: '完整库存销售退货总表' })).toBe(table);
    expect(document.body.style.overflow).toBe('hidden'); expect(background.inert).toBe(true);
    expect(vi.mocked(requestApi).mock.calls).toHaveLength(calls);
    fireEvent.keyDown(window, { key: 'Escape' });
    expect(table.closest('.sheet')).not.toHaveClass('is-fullscreen');
    expect(screen.getByRole('search', { name: '筛选总表' }).inert).not.toBe(true);
    expect(screen.getByRole('button', { name: '全屏查看' })).toHaveFocus();
    expect(document.body.style.overflow).toBe('scroll'); expect(background.inert).not.toBe(true);
    await userEvent.click(screen.getByRole('button', { name: '全屏查看' }));
    await userEvent.click(screen.getByRole('button', { name: '退出全屏' }));
    expect(table.closest('.sheet')).not.toHaveClass('is-fullscreen');
    expect(screen.getByRole('table', { name: '完整库存销售退货总表' })).toBe(table);
    await userEvent.click(screen.getByRole('button', { name: '全屏查看' })); view.unmount();
    expect(document.body.style.overflow).toBe('scroll'); expect(background.inert).not.toBe(true);
  } finally { background.remove(); document.body.style.overflow = overflow; }
});
