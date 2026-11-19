import { requestApi } from '../../../api/client';
import type { ProductionReadCache } from '../../../api/productionReadCache';
import type { Quantity, SheetResponse, SheetSku } from './model';

type PackedSheet = Omit<SheetResponse, 'rows' | 'totals'> & {
  quantity_pool: Quantity[];
  rows: (Omit<SheetSku, 'values'> & { values: Record<string, number> })[];
  totals: Record<string, number>;
};

function unpack(value: SheetResponse | PackedSheet): SheetResponse {
  if (!('quantity_pool' in value)) return value;
  const { quantity_pool: pool, rows, totals, ...rest } = value;
  const quantities = (items: Record<string, number>) => Object.fromEntries(Object.entries(items).map(([key, index]) => [key, pool[index]!]));
  return { ...rest, rows: rows.map(row => ({ ...row, values: quantities(row.values) })), totals: quantities(totals) };
}

type Read = { controller: AbortController; promise: Promise<SheetResponse> };

// One instance belongs to one mounted authorization/scope boundary.
export class SheetReads {
  constructor(private readonly shared?: ProductionReadCache) {}
  private key(key: string) { return `/api/production/inventory/overview-sheet?${key}&summary=1&compact=1`; }
  private readonly values = new Map<string, SheetResponse>();
  private readonly pending = new Map<string, Read>();

  peek(key: string) { return this.values.get(key) ?? this.shared?.peek<SheetResponse>(this.key(key)); }

  read(key: string, prefetch = false): Read {
    const existing = this.pending.get(key);
    if (existing) return existing;
    const controller = new AbortController();
    const revision = this.shared?.version();
    const job: Read = { controller, promise: requestApi<SheetResponse | PackedSheet>(`/api/production/inventory/overview-sheet?${key}&summary=1&compact=1`, {
      signal: controller.signal, priority: prefetch ? 'low' : 'auto',
    }).then(packed => {
      const value = unpack(packed);
      if (controller.signal.aborted) return value;
      const cached = this.values.get(key);
      const next = cached?.version === value.version && cached.today === value.today ? cached : value;
      this.values.delete(key); this.values.set(key, next);
      if (revision === this.shared?.version()) this.shared?.put(this.key(key), next);
      if (this.values.size > 5) this.values.delete(this.values.keys().next().value!);
      return next;
    }).catch((error: unknown) => {
      if (!controller.signal.aborted && revision === this.shared?.version()) this.forget(key);
      throw error;
    }).finally(() => { if (this.pending.get(key) === job) this.pending.delete(key); }) };
    this.pending.set(key, job);
    return job;
  }

  prefetch(key: string) {
    if (!this.peek(key)) void this.read(key, true).promise.catch(() => undefined);
  }

  retain(keys: readonly string[]) {
    for (const [other, job] of this.pending) {
      if (keys.includes(other)) continue;
      job.controller.abort(); this.pending.delete(other);
    }
  }

  forget(key: string) { this.values.delete(key); this.shared?.forget(this.key(key)); }

  clear(shared = false) {
    for (const job of this.pending.values()) job.controller.abort();
    this.pending.clear(); this.values.clear();
    if (shared) this.shared?.forgetPrefix('/api/production/inventory/overview-sheet?');
  }
}
