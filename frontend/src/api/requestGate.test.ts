import { describe, expect, it } from "vitest";

import { RequestGate, canonicalRequestKey } from "./requestGate";

describe("canonical request gate", () => {
  it("uses collision-safe tuple encoding for punctuation, NUL, and Unicode", () => {
    expect(canonicalRequestKey(["a,b", "c\n\0危险"])).not.toBe(
      canonicalRequestKey(["a", "b,c\n\0危险"]),
    );
  });

  it("rejects late tickets and aborts all authorization generations", () => {
    const gate = new RequestGate();
    const first = gate.begin(["catalog", 1], 2);
    const second = gate.begin(["catalog", 1], 2);
    expect(first.signal.aborted).toBe(true);
    expect(first.isCurrent()).toBe(false);
    expect(second.isCurrent()).toBe(true);
    gate.abortAll();
    expect(second.isCurrent()).toBe(false);
    gate.dispose();
  });
});
