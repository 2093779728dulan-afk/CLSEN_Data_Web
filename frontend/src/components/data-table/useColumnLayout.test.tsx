import { act, render } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import type { PresentableColumn } from "../../features/workbench/workbenchTypes";
import { preferenceKey } from "./columnPreferences";
import { useColumnLayout } from "./useColumnLayout";

const identity = { namespace: "workbench" as const, userId: 9, siteId: 8, reportType: "business_report" as const };
const columns: PresentableColumn[] = [
  { column_id: "sku", source_header: "SKU", standard_field_name: "sku", is_key: true, display_order: 1 },
  { column_id: "sessions", source_header: "Sessions", standard_field_name: "sessions", is_key: false, display_order: 2 },
];

afterEach(() => {
  localStorage.clear();
  vi.unstubAllGlobals();
});

describe("useColumnLayout", () => {
  it("persists completed commands across remounts and disconnects its ResizeObserver", () => {
    const disconnect = vi.fn();
    let callback: ResizeObserverCallback | undefined;
    class TestResizeObserver {
      constructor(next: ResizeObserverCallback) { callback = next; }
      observe() {}
      unobserve() {}
      disconnect = disconnect;
    }
    vi.stubGlobal("ResizeObserver", TestResizeObserver);
    let current = undefined as unknown as ReturnType<typeof useColumnLayout>;
    const Harness = () => {
      current = useColumnLayout({ columns, identity, viewportWidth: 1280 });
      return <div ref={current.containerRef} />;
    };
    const first = render(<Harness />);

    act(() => current.resize("sku", 212));
    const stored = JSON.parse(localStorage.getItem(preferenceKey(identity)) ?? "{}") as { widths: Record<string, number> };
    expect(stored.widths.sku).toBe(212);
    act(() => callback?.([{ contentRect: { width: 640 } } as ResizeObserverEntry], {} as ResizeObserver));
    expect(current.viewportWidth).toBe(640);
    first.unmount();
    expect(disconnect).toHaveBeenCalledOnce();

    render(<Harness />);
    expect(current.widths.sku).toBe(212);
  });
});
