import { ProductionReadCache } from '../../../api/productionReadCache';
import { beforeEach, expect, it, vi } from 'vitest';
import { requestApi } from '../../../api/client';
import type { SheetResponse } from './model';
import { SheetReads } from './SheetReads';

vi.mock('../../../api/client', () => ({ requestApi: vi.fn() }));
const value = (version: string) => ({ version, today: '2026-11-11' }) as SheetResponse;
beforeEach(() => vi.clearAllMocks());

it('promotes an in-flight neighbor read without a duplicate request and revalidates completed reads', async () => {
  let resolve: (value: SheetResponse) => void = () => {};
  vi.mocked(requestApi).mockImplementation(() => new Promise(done => { resolve = done; }));
  const reads = new SheetReads(); reads.prefetch('as_of=2026-11-03');
  const foreground = reads.read('as_of=2026-11-03');
  expect(vi.mocked(requestApi)).toHaveBeenCalledTimes(1);
  resolve(value('first')); await foreground.promise;
  expect(reads.peek('as_of=2026-11-03')?.version).toBe('first');
  const next = reads.read('as_of=2026-11-03');
  expect(vi.mocked(requestApi)).toHaveBeenCalledTimes(2);
  resolve(value('changed')); await next.promise;
  expect(reads.peek('as_of=2026-11-03')?.version).toBe('changed');
});

it('does not store failures or cancelled reads after invalidation', async () => {
  let resolve: (value: SheetResponse) => void = () => {};
  vi.mocked(requestApi).mockImplementationOnce(() => Promise.reject(new Error('unavailable')))
    .mockImplementation(() => new Promise(done => { resolve = done; }));
  const reads = new SheetReads();
  await expect(reads.read('failed').promise).rejects.toThrow('unavailable');
  expect(reads.peek('failed')).toBeUndefined();
  const pending = reads.read('pending'); reads.clear();
  expect(pending.controller.signal.aborted).toBe(true);
  resolve(value('late')); await pending.promise;
  expect(reads.peek('pending')).toBeUndefined();
});

it('bounds snapshots and cancels unrelated speculative requests on navigation', async () => {
  vi.mocked(requestApi).mockImplementation(() => Promise.resolve(value('same')));
  const reads = new SheetReads();
  for (let n = 0; n < 7; n++) await reads.read(String(n)).promise;
  expect(reads.peek('0')).toBeUndefined(); expect(reads.peek('1')).toBeUndefined();
  expect(reads.peek('6')).toBeDefined();
  vi.mocked(requestApi).mockImplementation(() => new Promise(() => {}));
  const wanted = reads.read('wanted'), other = reads.read('other'); reads.retain(['wanted']);
  expect(wanted.controller.signal.aborted).toBe(false); expect(other.controller.signal.aborted).toBe(true);
  reads.clear(); expect(reads.peek('6')).toBeUndefined();
});

it('unpacks pooled quantities without losing nulls, provenance or integer precision', async () => {
  const pool = [{ value: '0', state: 'ready', partial: false, reason: '' }, { value: null, state: 'missing_report', partial: true, reason: '缺报' }, { value: '9007199254740993', state: 'partial', partial: true, reason: '来源', evidence: { label: '装箱', units: '15' } }];
  vi.mocked(requestApi).mockResolvedValue({ ...value('original-version'), quantity_pool: pool, rows: [{ sku_id: '1', values: { zero: 0, missing: 1, large: 2 } }], totals: { large: 2 } });
  const decoded = await new SheetReads().read('scope=1').promise;
  expect(decoded.rows[0]!.values).toEqual({ zero: pool[0], missing: pool[1], large: pool[2] });
  expect(decoded.totals.large).toEqual(pool[2]); expect(decoded.version).toBe('original-version');
});


it('retains a completed sheet across page mounts and discards it after a business write', async () => {
  const cache = new ProductionReadCache();
  vi.mocked(requestApi).mockResolvedValue(value('before'));
  const first = new SheetReads(cache); await first.read('scope=1').promise; first.clear();
  expect(new SheetReads(cache).peek('scope=1')?.version).toBe('before');
  cache.invalidate(); expect(new SheetReads(cache).peek('scope=1')).toBeUndefined();
  let resolve: (value: SheetResponse) => void = () => {};
  vi.mocked(requestApi).mockImplementation(() => new Promise(done => {resolve=done;}));
  const pending = new SheetReads(cache).read('scope=1'); cache.invalidate();
  resolve(value('late')); await pending.promise;
  expect(new SheetReads(cache).peek('scope=1')).toBeUndefined();
});

it('reuses a fresh shared total on return without repeating the full request', async () => {
  const cache = new ProductionReadCache(); vi.mocked(requestApi).mockResolvedValue(value('same'));
  const first = new SheetReads(cache); await first.read('scope=1').promise; first.clear();
  await new SheetReads(cache).read('scope=1').promise;
  expect(requestApi).toHaveBeenCalledTimes(1);
  cache.invalidate(); await new SheetReads(cache).read('scope=1').promise;
  expect(requestApi).toHaveBeenCalledTimes(2);
});
