import { cleanup, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter, useLocation } from "react-router-dom";
import { afterEach, describe, expect, it } from "vitest";
import { InventorySnapshotView, type InventorySnapshot, type StockRow } from "./InventorySnapshotPage";
import type { Review } from "./InventoryReviewDialog";

// Fictional quantities and identities only; real source tables stay outside the repository.
function stock(sourceRow: number, style: string, color: string, quantity: string, unconfirmed = false): StockRow {
  return { source_key: "QA!" + sourceRow, sheet: "虚构核对表", source_row: sourceRow, style_code: style, color, color_note: "", old_style_code: "", source_sku: "", location: unconfirmed ? "" : "新仓库", location_group: unconfirmed ? "UNCONFIRMED" : "WAREHOUSE_1",
    quantities: { S: { cell: "D" + sourceRow, raw: quantity, state: "LITERAL", units: quantity }, M: { cell: "E" + sourceRow, raw: "0", state: "LITERAL", units: "0" }, L: { cell: "F" + sourceRow, raw: "/", state: "UNKNOWN", units: null } },
    stock_units: quantity, literal_units: quantity, formula_units: "0", unknown_cells: 5, source_total: { cell: "J" + sourceRow, raw: quantity, state: "LITERAL", units: quantity }, notes: [], issues: [], sku_id: null };
}
const rows = [stock(2, "QA-100", "Navy", "8"), stock(3, "QA-100", "Black", "4"), ...Array.from({ length: 6 }, (_, index) => stock(index + 4, "QA-" + (index + 2) + "00", "Olive", "3"))];
const snapshot: InventorySnapshot = { filename: "虚构库存.txt", source_digest: "a".repeat(64), source_format: "pasted_table", organized_on: null, stocktaken_on: null, warehouse_note: "虚构仓库范围", scope: "WAREHOUSE_1", quantity_basis: "DECLARED_TOTAL", read_only: true, posting_enabled: false, historical_shipments_deducted: false,
  summary: { source_row_count: 9, row_count: 8, product_count: 7, warehouse_1_units: "30", location_unconfirmed_units: "99", literal_units: "30", warehouse_1_literal_units: "30", location_unconfirmed_literal_units: "99", formula_units: "0", unknown_cells: 40, defect_literal_units: "0", additional_note_rows: 0 }, rows, unconfirmed_rows: [stock(10, "QA-800", "Navy", "99", true)], defect_period_note: "", defects: [] };
function LocationProbe() { const location = useLocation(); return <output data-testid="query">{location.search}</output>; }
function mount(entry = "/") { return render(<MemoryRouter initialEntries={[entry]}><InventorySnapshotView snapshot={snapshot} /><LocationProbe /></MemoryRouter>); }
afterEach(cleanup);

describe("inventory card and size-matrix flow", () => {
  it("exports all pages or the current product filter, using the saved revision", async () => {
    const user = userEvent.setup();
    const review = { review_id: "qa-review", revision: 2 } as Review;
    render(<MemoryRouter initialEntries={["/?page=2&product=obsolete"]}><InventorySnapshotView snapshot={snapshot} review={review} /></MemoryRouter>);
    const all = new URL(screen.getByRole("link", { name: "导出 Excel" }).getAttribute("href")!, "http://localhost");
    expect(all.searchParams.get("revision")).toBe("2");
    expect(all.searchParams.get("review_id")).toBe("qa-review");
    expect(all.searchParams.has("page")).toBe(false);
    expect(all.searchParams.has("product")).toBe(false);
    expect(screen.queryByRole("link", { name: "导出筛选结果" })).not.toBeInTheDocument();
    await user.type(screen.getByRole("searchbox"), "Navy");
    const filtered = new URL(screen.getByRole("link", { name: "导出筛选结果" }).getAttribute("href")!, "http://localhost");
    expect(filtered.searchParams.get("q")).toBe("Navy");
    expect(screen.getByRole("link", { name: "导出 Excel" })).toHaveAttribute("href", all.pathname + all.search);
  });

  it("switches cards, keeps the full matrix, and restores selection from the URL", async () => {
    const user = userEvent.setup();
    mount();
    const matrix = screen.getByRole("table", { name: "QA-100颜色与尺码数量" });
    expect(within(matrix).getAllByRole("columnheader").map(cell => cell.textContent)).toEqual(["颜色", "XS", "S", "M", "L", "XL", "XXL", "3XL", "合计（件）"]);
    const navy = within(matrix).getByRole("row", { name: /^Navy / });
    expect(within(navy).getAllByRole("cell").map(cell => cell.textContent)).toEqual(["待核", "8", "0", "待核", "待核", "待核", "待核", "8"]);
    expect(screen.queryByRole("button", { name: /^查看QA-800库存/ })).not.toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: /^查看QA-200库存/ }));
    expect(screen.getByRole("table", { name: "QA-200颜色与尺码数量" })).toBeVisible();
    expect(screen.queryByRole("table", { name: "QA-100颜色与尺码数量" })).not.toBeInTheDocument();
    const query = screen.getByTestId("query").textContent || "";
    expect(new URLSearchParams(query).get("product")).toBe('["style","QA-200"]');
    cleanup(); mount("/" + query);
    expect(screen.getByRole("button", { name: /^查看QA-200库存/ })).toHaveAttribute("aria-pressed", "true");
    expect(screen.getByRole("table", { name: "QA-200颜色与尺码数量" })).toBeVisible();
  });

  it("filters whole products and prevents stale details after filtering and paging", async () => {
    const user = userEvent.setup();
    mount();
    await user.click(screen.getByRole("button", { name: /^查看QA-200库存/ }));
    await user.type(screen.getByRole("searchbox", { name: "查找款号或颜色" }), "Navy");
    expect(screen.getByRole("button", { name: "查看QA-100库存，2种颜色，12件" })).toHaveAttribute("aria-pressed", "true");
    expect(within(screen.getByRole("table", { name: "QA-100颜色与尺码数量" })).getAllByRole("rowheader").map(cell => cell.textContent)).toEqual(["Navy", "Black"]);
    await user.clear(screen.getByRole("searchbox")); await user.type(screen.getByRole("searchbox"), "no-match");
    expect(screen.getByText("本仓没有符合筛选的产品")).toBeVisible();
    expect(screen.queryByRole("table")).not.toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "清除筛选" }));
    await user.click(screen.getByRole("button", { name: "下一页" }));
    expect(screen.getByRole("button", { name: /^查看QA-700库存/ })).toHaveAttribute("aria-pressed", "true");
    expect(screen.getByRole("table", { name: "QA-700颜色与尺码数量" })).toBeVisible();
    expect(screen.getByRole("button", { name: "下一页" })).toBeDisabled();
  });

  it("opens all selected-product sources and returns focus after Escape", async () => {
    const user = userEvent.setup();
    mount();
    const opener = screen.getByRole("button", { name: "查看来源依据" });
    await user.click(opener);
    const dialog = screen.getByRole("dialog", { name: "库存核对依据" });
    expect(within(dialog).getByRole("heading", { name: "Navy · 8件" })).toBeVisible();
    expect(within(dialog).getByRole("heading", { name: "Black · 4件" })).toBeVisible();
    expect(within(dialog).getAllByRole("table", { name: "尺码数量依据" })).toHaveLength(2);
    await user.keyboard("{Escape}");
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
    await waitFor(() => expect(opener).toHaveFocus());
  });
});
