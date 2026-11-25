type Read<T> = { controller: AbortController; promise: Promise<T> };

// Owned by one authorization provider. No persistence or shared user data.
export class ProductionReadCache {
  constructor(readonly boundary = "") {}
  private readonly values = new Map<string, unknown>();
  private readonly savedAt = new Map<string, number>();
  private readonly pending = new Map<string, Read<unknown>>();
  private readonly listeners = new Set<() => void>();
  private revision = 0;

  subscribe = (listener: () => void) => { this.listeners.add(listener); return () => { this.listeners.delete(listener); }; };
  version = () => this.revision;
  peek<T>(key: string) { return this.values.get(key) as T | undefined; }
  put(key: string, value: unknown) {
    this.values.delete(key); this.values.set(key, value); this.savedAt.set(key, Date.now());
    if (this.values.size > 24) this.forget(this.values.keys().next().value!);
  }
  isFresh(key: string, maxAge = 30_000) { return this.values.has(key) && Date.now() - (this.savedAt.get(key) ?? 0) < maxAge; }
  forget(key: string) { this.values.delete(key); this.savedAt.delete(key); }
  forgetPrefix(prefix: string) { for (const key of this.values.keys()) if (key.startsWith(prefix)) this.forget(key); }

  read<T>(key: string, load: (signal: AbortSignal) => Promise<T>, maxAge = 0): Read<T> {
    if (maxAge > 0 && this.isFresh(key, maxAge)) return { controller: new AbortController(), promise: Promise.resolve(this.peek<T>(key)!) };
    const previous = this.pending.get(key);
    if (previous) return previous as Read<T>;
    const controller = new AbortController();
    const job = { controller, promise: load(controller.signal).then(value => {
      if (!controller.signal.aborted) this.put(key, value);
      return value;
    }).catch((error: unknown) => {
      if (this.pending.get(key) === job) this.forget(key);
      throw error;
    }).finally(() => { if (this.pending.get(key) === job) this.pending.delete(key); }) };
    this.pending.set(key, job);
    return job;
  }
  clear() {
    for (const job of this.pending.values()) job.controller.abort();
    this.pending.clear(); this.values.clear(); this.savedAt.clear();
  }
  invalidate() {
    this.clear(); this.revision++;
    for (const listener of this.listeners) listener();
  }
}

const listeners = new Set<() => void>();
export function onProductionDataChanged(listener: () => void) {
  listeners.add(listener); return () => { listeners.delete(listener); };
}
export function productionDataChanged() { for (const listener of listeners) listener(); }

export function isBusinessWrite(path: string, method: string) {
  if (["GET", "HEAD", "OPTIONS"].includes(method.toUpperCase())) return false;
  const pathname = path.split("?")[0]!;
  if (!/^\/api\/(?:production|catalog|review|batch-reviews|publications|imports|drafts|workbench)(?:\/|$)/.test(pathname)) return false;
  return !/(?:\/preview|\/mapping-preview|\/source-check|\/validate)$/.test(pathname);
}
