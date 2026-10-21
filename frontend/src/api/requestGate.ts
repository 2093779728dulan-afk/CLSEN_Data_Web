export type RequestTupleValue = string | number | boolean | null;
export type RequestTuple = readonly RequestTupleValue[];

type GateEntry = {
  authzGeneration: number;
  controller: AbortController;
  sequence: number;
};

export type RequestTicket = {
  authzGeneration: number;
  key: string;
  sequence: number;
  signal: AbortSignal;
  isCurrent: () => boolean;
};

const allGates = new Set<RequestGate>();

export function canonicalRequestKey(tuple: RequestTuple): string {
  return JSON.stringify(tuple);
}
export class RequestGate {
  #entries = new Map<string, GateEntry>();
  #sequence = 0;

  constructor() {
    allGates.add(this);
  }

  begin(tuple: RequestTuple, authzGeneration: number): RequestTicket {
    if (!Number.isSafeInteger(authzGeneration) || authzGeneration < 0) {
      throw new Error("Authorization generation must be a non-negative integer.");
    }
    const key = canonicalRequestKey(tuple);
    this.#entries.get(key)?.controller.abort();
    const entry: GateEntry = {
      authzGeneration,
      controller: new AbortController(),
      sequence: ++this.#sequence,
    };
    this.#entries.set(key, entry);
    return {
      authzGeneration,
      key,
      sequence: entry.sequence,
      signal: entry.controller.signal,
      isCurrent: () =>
        !entry.controller.signal.aborted &&
        this.#entries.get(key) === entry &&
        entry.authzGeneration === authzGeneration,
    };
  }

  abortAll(): void {
    for (const entry of this.#entries.values()) entry.controller.abort();
    this.#entries.clear();
  }

  dispose(): void {
    this.abortAll();
    allGates.delete(this);
  }
}

export function abortAllRequestGates(): void {
  for (const gate of allGates) gate.abortAll();
}
