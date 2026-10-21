import { afterEach, describe, expect, it, vi } from "vitest";

import {
  closeSessionBoundary,
  establishSessionBoundary,
  onSessionRevoked,
  revokeSessionBoundary,
} from "./sessionRevocation";

describe("session revocation boundary", () => {
  afterEach(() => closeSessionBoundary());

  it("notifies once for concurrent 401 responses in one authenticated boundary", () => {
    const listener = vi.fn();
    const unsubscribe = onSessionRevoked(listener);
    establishSessionBoundary();

    expect(revokeSessionBoundary()).toBe(true);
    expect(revokeSessionBoundary()).toBe(false);
    expect(listener).toHaveBeenCalledTimes(1);

    unsubscribe();
  });
});
