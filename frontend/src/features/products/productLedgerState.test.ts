import { describe, expect, it } from "vitest";
import { defaultProductLedgerView, parseProductLedgerSearch, serializeProductLedgerSearch, updateProductLedgerView } from "./productLedgerState";

describe("product ledger URL state", () => {
  it("uses an inclusive 31-day business-date default", () => {
    expect(defaultProductLedgerView("2026-08-24")).toMatchObject({ from: "2026-07-25", to: "2026-08-24", page: 1, page_size: 50, sort: "units", direction: "desc" });
  });

  it("accepts 366 days and rejects a 367-day or future range", () => {
    expect(parseProductLedgerSearch(new URLSearchParams("from=2025-08-24&to=2026-08-24"), "2026-08-24").from).toBe("2025-08-24");
    expect(parseProductLedgerSearch(new URLSearchParams("from=2025-08-23&to=2026-08-24"), "2026-08-24").from).toBe("2026-07-25");
    expect(parseProductLedgerSearch(new URLSearchParams("from=2026-08-01&to=2026-08-25"), "2026-08-24").to).toBe("2026-08-24");
  });

  it("drops unknown keys, bounds search, and canonicalizes enums and pagination", () => {
    const view = parseProductLedgerSearch(new URLSearchParams(`unknown=1&search=${"x".repeat(101)}&sort=no&page=0&page_size=12&return_basis=no`), "2026-08-24");
    expect(view.search).toHaveLength(100);
    expect(view).toMatchObject({ sort: "units", page: 1, page_size: 50, return_basis: "event_date" });
    expect(serializeProductLedgerSearch(view).has("unknown")).toBe(false);
  });

  it("resets page for scope and order changes but not direct pagination", () => {
    const view = { ...defaultProductLedgerView("2026-08-24"), page: 4 };
    expect(updateProductLedgerView(view, { search: "coat" }).page).toBe(1);
    expect(updateProductLedgerView(view, { direction: "asc" }).page).toBe(1);
    expect(updateProductLedgerView(view, { page: 3 }).page).toBe(3);
  });
});

it("keeps category scope in the URL and resets pagination on category change", () => {
  const view = parseProductLedgerSearch(new URLSearchParams("category_id=12&page=3"), "2026-07-31");
  expect(view.category_id).toBe(12);
  expect(serializeProductLedgerSearch(view).get("category_id")).toBe("12");
  expect(updateProductLedgerView(view, { category_id: 14 }).page).toBe(1);
});
