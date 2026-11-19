import { afterEach, expect, it, vi } from "vitest";
import { today } from "./workbenchDate";
import { renderHook } from "@testing-library/react";
import { ProductionTimezoneContext, useBusinessToday } from "./workbenchDate";

afterEach(() => vi.useRealTimers());

it("defaults business forms to the US site date across the UTC and China midnight boundary", () => {
  vi.useFakeTimers();
  vi.setSystemTime(new Date("2026-11-13T01:00:00Z"));
  expect(today()).toBe("2026-11-12");
});

it("takes the active site timezone from the production boundary", () => {
  vi.useFakeTimers();
  vi.setSystemTime(new Date("2026-11-13T01:00:00Z"));
  const { result } = renderHook(() => useBusinessToday(), { wrapper: ({ children }) =>
    <ProductionTimezoneContext.Provider value="Asia/Shanghai">{children}</ProductionTimezoneContext.Provider> });
  expect(result.current()).toBe("2026-11-13");
  expect(today()).toBe("2026-11-12");
  vi.setSystemTime(new Date("2026-11-13T08:00:00Z"));
  expect(today()).toBe("2026-11-13");
});
