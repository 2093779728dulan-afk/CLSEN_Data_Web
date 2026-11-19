import { cleanup, render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, expect, it } from "vitest";
import { CatalogCandidateCell, CatalogReferencePanel, type CatalogReferenceResult, type ProductCandidate } from "./CatalogReference";

const product: ProductCandidate = { style_id: "9007199254740995", style_revision: "2", code: "QA-100", name: "虚构产品", status: "disabled",
  skus: [{ sku_id: "9007199254740993", sku_revision: "3", code: "QA-BLUE-M", color: "Blue", size: "M", status: "disabled" }] };
const reference: CatalogReferenceResult = { status: "CHECKED_SNAPSHOT", confirmation_enabled: false,
  source: { site_id: "1", site_code: "QA_ONLY", catalog_version_id: "2", catalog_publication_revision: "2", version_number: "2", checked_at: "2026-10-13T00:00:00Z" },
  products: { "QA-100": [product], "QA-MISSING": [] }, counts: { UNMATCHED: 1 },
  rows: [{ source_row: 2, source_sku: "QA-UNKNOWN", status: "UNMATCHED", candidates: [], excluded_scopes: [], product_lookup: { code: "QA-100", basis: "SOURCE_COLUMN", checked: true, candidates: [product] } }] };
afterEach(cleanup);

it("looks up a product without binding and retains disabled variants and large IDs", async () => {
  const user = userEvent.setup();
  render(<CatalogReferencePanel reference={reference} />);
  await user.type(screen.getByRole("searchbox", { name: "按产品号查询主档" }), "QA-100");
  const table = screen.getByRole("table", { name: "QA-100主档颜色与尺码" });
  expect(within(table).getByText("9007199254740993")).toBeVisible();
  expect(within(table).getByText("已停用")).toBeVisible();
  expect(screen.getByText(/尚未绑定SKU。$/)).toBeVisible();
  expect(screen.queryByRole("button", { name: /绑定|确认/ })).not.toBeInTheDocument();
});

it("distinguishes a checked missing product from a product outside the read scope", async () => {
  const user = userEvent.setup();
  render(<CatalogReferencePanel reference={reference} />);
  const input = screen.getByRole("searchbox", { name: "按产品号查询主档" });
  await user.type(input, "QA-MISSING");
  expect(screen.getByText("此款号在当前主档快照中未找到产品。")).toBeVisible();
  await user.clear(input); await user.type(input, "QA-OUTSIDE");
  expect(screen.getByText("本批尚未核对此产品号，不代表主档中没有商品。")).toBeVisible();
  await user.clear(input);
  expect(screen.queryByRole("table")).not.toBeInTheDocument();
});

it("shows product evidence separately from an unresolved source SKU", async () => {
  const user = userEvent.setup();
  render(<CatalogCandidateCell reference={reference} sourceRow={2} />);
  expect(screen.getByText("找到产品 · SKU待核")).toBeVisible();
  await user.click(screen.getByText("查看产品候选（1）"));
  expect(screen.getByText(/A款式ID 9007199254740995/)).toBeVisible();
  expect(screen.getByText("尚未正式绑定")).toBeVisible();
});
