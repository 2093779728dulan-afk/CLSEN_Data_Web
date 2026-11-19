import { cleanup, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";
import { createRef } from "react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { ApiRequestError, requestApi } from "../../api/client";
import { AuthzGenerationProvider } from "../../app/AuthzGenerationContext";
import type { Review } from "./InventoryReviewDialog";
import type { StockRow } from "./InventorySnapshotPage";
import { InventoryProductMatchDialog } from "./InventoryProductMatchDialog";

vi.mock("../../api/client", async importOriginal => ({ ...await importOriginal<typeof import("../../api/client")>(), requestApi: vi.fn() }));
const rows: StockRow[] = [2, 3].map(number => ({ source_key: "QA!" + number, source_row: number, style_code: "QA-12", color: number === 2 ? "Navy" : "Olive", color_note: "", sheet: "QA", old_style_code: "", source_sku: "", location: "新仓库", location_group: "WAREHOUSE_1", quantities: { M: { cell: "E" + number, raw: "0", state: "LITERAL", units: "0" } }, stock_units: "0", literal_units: "0", formula_units: "0", unknown_cells: 0, source_total: { cell: "J" + number, raw: "0", state: "LITERAL", units: "0" }, notes: [], issues: [], sku_id: null }));
const review = { review_id: "review-qa", revision: 2 } as Review;
const match = { status: "matched", review_id: "review-qa", review_revision: 2, catalog_version_id: "3", catalog_publication_revision: "3", source: { source_key: "QA!2", cell: "E2", style_code: "QA-12", color: "Navy", size: "M", units: "0" }, association_saved: false, posting_enabled: false, candidates: [{ style_id: "11", sku_id: "21", style_code: "QA-12", standard_name: "", standard_color: "Navy", standard_size: "M", code: "QA-SELLER-12", active: true }] };
function mount(onClose = vi.fn(), onRefresh = vi.fn(), onEdit?: ReturnType<typeof vi.fn>) {
  render(<MemoryRouter><AuthzGenerationProvider boundary={{ principalId: 1, siteId: 1, siteConfigVersionId: 1, roles: ["viewer"] }} onRevoked={vi.fn()}><InventoryProductMatchDialog review={onEdit ? { ...review, can_manage: true } : review} rows={rows} onEdit={onEdit} onClose={onClose} onRefresh={onRefresh} returnFocusTarget={createRef<HTMLButtonElement>()} /></AuthzGenerationProvider></MemoryRouter>);
  return { onClose, onRefresh };
}
beforeEach(() => vi.mocked(requestApi).mockReset());
afterEach(cleanup);

describe("inventory product correspondence preview", () => {
  it("shows the stable product, zero quantity and unsaved state to a reader", async () => {
    vi.mocked(requestApi).mockResolvedValue(match);
    mount();
    expect(await screen.findByText("已找到相同规格的商品")).toBeVisible();
    expect(screen.getByText(/数量0件/)).toBeVisible();
    expect(screen.getByText(/尚未保存正式关联/)).toBeVisible();
    expect(screen.getByRole("link", { name: "查看商品详情" })).toHaveAttribute("href", "/catalog/styles/11");
    const params = new URL(String(vi.mocked(requestApi).mock.calls[0]![0]), "http://localhost").searchParams;
    expect(params.get("expected_revision")).toBe("2");
    expect(params.get("source_key")).toBe("QA!2");
    expect(screen.queryByRole("button", { name: /保存|确认/ })).not.toBeInTheDocument();
  });

  it("clears the old result when selecting another color", async () => {
    vi.mocked(requestApi).mockResolvedValueOnce(match);
    const user = userEvent.setup();
    mount();
    await screen.findByText("QA-SELLER-12");
    let resolve: (value: unknown) => void = () => undefined;
    vi.mocked(requestApi).mockImplementationOnce(() => new Promise(value => { resolve = value; }));
    await user.selectOptions(screen.getByLabelText("来源颜色"), "QA!3");
    expect(screen.queryByText("QA-SELLER-12")).not.toBeInTheDocument();
    resolve({ ...match, status: "not_found", source: { ...match.source, source_key: "QA!3", color: "Olive" }, candidates: [] });
    expect(await screen.findByText("当前本地商品中未找到相同规格")).toBeVisible();
  });

  it("explains network failure in Chinese and permits a read retry", async () => {
    vi.mocked(requestApi).mockRejectedValueOnce(new Error("Failed to fetch")).mockResolvedValueOnce(match);
    const user = userEvent.setup(); mount();
    expect(await screen.findByText("商品对应暂时无法读取，请稍后重试。")).toBeVisible();
    expect(screen.queryByText("Failed to fetch")).not.toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "重新读取" }));
    expect(await screen.findByText("已找到相同规格的商品")).toBeVisible();
  });

  it("refreshes the inventory instead of retrying a stale saved revision", async () => {
    vi.mocked(requestApi).mockRejectedValueOnce(new ApiRequestError(409, "inventory_match_stale", "库存资料已有更新。"));
    const user = userEvent.setup(); const callbacks = mount();
    await user.click(await screen.findByRole("button", { name: "刷新库存资料" }));
    await waitFor(() => expect(callbacks.onRefresh).toHaveBeenCalledOnce());
    expect(callbacks.onClose).toHaveBeenCalledOnce();
    expect(requestApi).toHaveBeenCalledOnce();
  });
});


describe("product correspondence management", () => {
  it("passes the exact cell and server IDs to the existing preview-save flow", async () => {
    vi.mocked(requestApi).mockResolvedValue(match);
    const edit = vi.fn(); const user = userEvent.setup(); mount(vi.fn(), vi.fn(), edit);
    await user.click(await screen.findByRole("button", { name: "确认此尺码商品对应" }));
    expect(edit).toHaveBeenCalledWith(expect.objectContaining({mode: "product", rows: [rows[0]], product: {size: "M", value: {sku_id: "21", catalog_version_id: "3", catalog_publication_revision: "3"}, label: "QA-SELLER-12 · Navy / M"}}));
  });

  it("shows the stored identity and permits explicit unlink without automatic rebinding", async () => {
    vi.mocked(requestApi).mockResolvedValue({...match, association_saved: true, association_current: false, saved_association: {...match.candidates[0], catalog_version_id: "2"}});
    const edit = vi.fn(); const user = userEvent.setup(); mount(vi.fn(), vi.fn(), edit);
    expect(await screen.findByText("已保存商品对应")).toBeVisible();
    expect(screen.getByText(/原对应不会自动改绑/)).toBeVisible();
    await user.click(screen.getByRole("button", {name: "解除此尺码对应"}));
    expect(edit).toHaveBeenCalledWith(expect.objectContaining({mode: "product", product: {size: "M", value: null, label: "解除对应"}}));
  });

  it("keeps a saved link read-only for the viewer", async () => {
    vi.mocked(requestApi).mockResolvedValue({...match, association_saved: true, association_current: true, saved_association: {...match.candidates[0], catalog_version_id: "3"}});
    mount(); expect(await screen.findByText("已保存商品对应")).toBeVisible();
    expect(screen.queryByRole("button", {name: /确认此尺码|解除此尺码/})).not.toBeInTheDocument();
  });
});
