import type { Meta, StoryObj } from "@storybook/react-vite";
import { expect, userEvent, within } from "storybook/test";
import { MemoryRouter } from "react-router-dom";
import { CatalogCandidateCell, CatalogReferencePanel, type CatalogReferenceResult } from "./CatalogReference";
import { InventorySnapshotView, type InventorySnapshot, type StockRow } from "./InventorySnapshotPage";
import styles from "./Production.module.css";

// All source, quantity and candidate values below are fictional Storybook fixtures.
function stock(source_row: number, style_code: string, color: string, quantity: string, overrides: Partial<StockRow> = {}): StockRow {
  const quantities: StockRow["quantities"] = Object.fromEntries(["XS", "S", "M", "L", "XL", "XXL", "3XL"].map((size, i) => [size, { cell: String.fromCharCode(67 + i) + source_row, raw: size === "S" ? quantity : "/", state: size === "S" ? "LITERAL" as const : "UNKNOWN" as const, units: size === "S" ? quantity : null }]));
  if (source_row === 3 || source_row === 4) quantities.M = { cell: "E" + source_row, raw: "0", state: "LITERAL", units: "0" };
  return { source_key: "虚构核对表!" + source_row, sheet: "虚构核对表", source_row, style_code, color, old_style_code: "", source_sku: "", color_note: "", location: "新仓库", location_group: "WAREHOUSE_1",
    quantities, stock_units: quantity, literal_units: quantity, formula_units: "0", unknown_cells: source_row === 3 || source_row === 4 ? 5 : 6, source_total: { cell: "J" + source_row, raw: quantity, state: "LITERAL", units: quantity }, notes: [], issues: ["空白或斜杠尺码待核对。"], sku_id: null, ...overrides };
}
const snapshot: InventorySnapshot = {
  filename: "虚构库存核对样例.txt", source_digest: "a".repeat(64), source_format: "pasted_table", organized_on: null, stocktaken_on: null,
  scope: "WAREHOUSE_1", quantity_basis: "DECLARED_TOTAL", warehouse_note: "虚构样例：仅核对仓库1号，空库位另列待确认。", read_only: true, posting_enabled: false, historical_shipments_deducted: false,
  summary: { source_row_count: 5, row_count: 4, product_count: 2, warehouse_1_units: "33", location_unconfirmed_units: "99", literal_units: "33", warehouse_1_literal_units: "33", location_unconfirmed_literal_units: "99", formula_units: "0", unknown_cells: 22, defect_literal_units: "0", additional_note_rows: 0 },
  rows: [stock(2, "QA-100", "navy", "5"), stock(3, "QA-100", "NAVY", "7"), stock(4, "QA-100", "Black", "9"), stock(5, "QA-200", "Olive White Stripe · 虚构长颜色名称", "12")],
  unconfirmed_rows: [stock(6, "QA-100", "navy", "99", { location: "", location_group: "UNCONFIRMED", issues: ["库位归属未提供。"] })],
  defect_period_note: "", defects: [],
};
const candidate = { sku_id: "9007199254740993", style_id: "9007199254740995", sku_revision: "2", code: "QA-BLUE-M", color: "蓝色", size: "M", status: "enabled" as const, style_status: "enabled" as const, match_routes: ["SELLER_MAPPING" as const], source_scopes: [{ report_source_scope_id: "2", marketplace_scope_code: "QA" }] };
const product = { style_id: candidate.style_id, style_revision: "2", code: "QA-100", name: "虚构产品", status: "enabled" as const,
  skus: [candidate, { ...candidate, sku_id: "9007199254740994", code: "QA-BLUE-L", size: "L", status: "disabled" as const }] };
const reference: CatalogReferenceResult = {
  status: "CHECKED_SNAPSHOT", confirmation_enabled: false,
  source: { site_id: "1", site_code: "QA_ONLY", catalog_version_id: "35", catalog_publication_revision: "35", version_number: "35", checked_at: "2026-10-12T06:00:00Z" },
  counts: { UNIQUE_CANDIDATE: 1, AMBIGUOUS: 1, DISABLED: 1, EXCLUDED: 1, UNMATCHED: 2 },
  products: { "QA-100": [product], "QA-MISSING": [] }, products_checked_at: "2026-10-13T00:00:00Z",
  rows: [
    { source_row: 2, source_sku: "QA-BLUE-M", status: "UNIQUE_CANDIDATE", candidates: [candidate], excluded_scopes: [] },
    { source_row: 3, source_sku: "QA-CONFLICT", status: "AMBIGUOUS", candidates: [candidate, { ...candidate, sku_id: "9007199254740994" }], excluded_scopes: [] },
    { source_row: 4, source_sku: "QA-DISABLED", status: "DISABLED", candidates: [{ ...candidate, status: "disabled" }], excluded_scopes: [] },
    { source_row: 5, source_sku: "QA-EXCLUDED", status: "EXCLUDED", candidates: [], excluded_scopes: [{ report_source_scope_id: "2", marketplace_scope_code: "QA" }] },
    { source_row: 6, source_sku: "QA-UNMATCHED", status: "UNMATCHED", candidates: [], excluded_scopes: [] },
    { source_row: 7, source_sku: "QA-100-UNRESOLVED", status: "UNMATCHED", candidates: [], excluded_scopes: [], product_lookup: { code: "QA-100", basis: "SOURCE_COLUMN", checked: true, candidates: [product] } },
  ],
};
function ReadOnlyStory({ scenario }: { scenario: "inventory" | "empty-filter" | "catalog" | "catalog-outside-scope" }) {
  return <MemoryRouter initialEntries={[scenario === "empty-filter" ? "/?q=NO-SUCH-ROW" : "/"]}><main className={styles.workspace}>
    {scenario === "catalog" ? <><h1>商品核对 · 虚构状态样例</h1><CatalogReferencePanel reference={reference} /><section className={styles.panel} aria-label="候选核对状态">{reference.rows?.map(row => <div key={row.source_row}><h2>{row.source_sku}</h2><CatalogCandidateCell reference={reference} sourceRow={row.source_row} /></div>)}</section></> : scenario === "catalog-outside-scope" ? <><h1>商品核对 · 范围外虚构样例</h1><CatalogReferencePanel reference={{ status: "OUTSIDE_SCOPE", confirmation_enabled: false }} /></> : <InventorySnapshotView snapshot={snapshot} />}
  </main></MemoryRouter>;
}
const meta = { title: "Pages/Production Read Only", component: ReadOnlyStory, parameters: { layout: "fullscreen" }, args: { scenario: "inventory" } } satisfies Meta<typeof ReadOnlyStory>;
export default meta;
type Story = StoryObj<typeof meta>;
export const InventoryReference: Story = {};
export const InventoryFilteredEmpty: Story = { args: { scenario: "empty-filter" } };
export const CatalogReference: Story = { args: { scenario: "catalog" }, play: async ({ canvasElement }) => {
  const canvas = within(canvasElement);
  await userEvent.type(canvas.getByRole("searchbox", { name: "按产品号查询主档" }), "QA-100");
  await expect(canvas.getByRole("table", { name: "QA-100主档颜色与尺码" })).toBeInTheDocument();
} };
export const CatalogOutsideScope: Story = { args: { scenario: "catalog-outside-scope" } };
