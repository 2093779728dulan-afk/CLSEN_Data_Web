import { cleanup, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { createMemoryRouter, RouterProvider } from "react-router-dom";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import { ApiRequestError, requestApi, writeApi } from "../../api/client";
import { AuthzGenerationProvider } from "../../app/AuthzGenerationContext";
import { InventoryReviewDialog, type Review } from "./InventoryReviewDialog";
import type { StockRow } from "./InventorySnapshotPage";

vi.mock("../../api/client", async original => ({...await original<typeof import("../../api/client")>(), requestApi: vi.fn(), writeApi: vi.fn()}));
const row = {source_key: "QA!2", style_code: "QA-1", color: "Olive", color_note: "", quantities: {}, source_total: {state: "LITERAL", units: "0", raw: "0", cell: "J2"}} as StockRow;
const review = {review_id: "qa", revision: 2, source_identity: "a".repeat(64), source: {filename: "虚构表"}, effective: {stocktaken_on: "2026-10-14", cutoff_note: ""}} as Review;
const reference = {sku_id: "24", catalog_version_id: "48", catalog_publication_revision: "48"};
const preview = {preview_hash: "b".repeat(64), before: {warehouse_1_units: "4"}, after: {warehouse_1_units: "4"}, stocktaken_on: "2026-10-14", cutoff_note: ""};
function mount() {
  const close = vi.fn(); const reload = vi.fn().mockResolvedValue({...review, revision: 3});
  render(<RouterProvider router={createMemoryRouter([{path: "/", element: <AuthzGenerationProvider boundary={{principalId: 1, siteId: 1, siteConfigVersionId: 1, roles: ["admin"]}} onRevoked={vi.fn()}><InventoryReviewDialog review={review} edit={{mode: "product", rows: [row], product: {size: "M", value: reference, label: "QA-1-M"}}} onClose={close} onReload={reload} onForbidden={vi.fn()} /></AuthzGenerationProvider>}])} />);
  return {close, reload};
}
beforeEach(() => { vi.mocked(requestApi).mockReset(); vi.mocked(writeApi).mockReset(); });
afterEach(cleanup);

it("previews and saves only the selected product reference, then reloads", async () => {
  vi.mocked(writeApi).mockResolvedValueOnce(preview).mockResolvedValueOnce({saved_revision: 3, operation_id: "qa-operation", replayed: false});
  const callbacks=mount(); const user=userEvent.setup();
  await user.click(screen.getByRole("button", {name: "预览核对影响"}));
  await user.click(await screen.findByRole("button", {name: "保存核对结果"}));
  expect(await screen.findByText("已保存核对修订 3")).toBeVisible();
  const call=vi.mocked(writeApi).mock.calls[1]!;
  expect(call[1]?.body).toEqual(expect.objectContaining({expected_revision: 2, changes: [{type: "set_product", source_key: "QA!2", size: "M", value: reference}], preview_hash: preview.preview_hash}));
  expect(call[1]?.operationKey).toMatch(/^[a-f0-9-]{36}$/);
  expect(callbacks.reload).toHaveBeenCalledOnce();
});

it("requires a fresh product choice after a catalog conflict", async () => {
  vi.mocked(writeApi).mockRejectedValueOnce(new ApiRequestError(409,"inventory_product_catalog_stale","商品目录已变化，请重新查看商品对应后预览。"));
  const callbacks=mount(); const user=userEvent.setup();
  await user.click(screen.getByRole("button", {name: "预览核对影响"}));
  await user.click(await screen.findByRole("button", {name: "返回重新核对商品"}));
  expect(callbacks.close).toHaveBeenCalledOnce();
  expect(screen.queryByRole("button", {name: "预览核对影响"})).not.toBeInTheDocument();
});

it("locks a lost-response command and retrieves its original receipt", async () => {
  vi.mocked(writeApi).mockResolvedValueOnce(preview).mockRejectedValueOnce(new TypeError("Failed to fetch"));
  vi.mocked(requestApi).mockResolvedValueOnce({saved_revision: 3, operation_id: "qa-operation"});
  mount(); const user=userEvent.setup();
  await user.click(screen.getByRole("button", {name: "预览核对影响"}));
  await user.click(await screen.findByRole("button", {name: "保存核对结果"}));
  await screen.findByText("保存结果待确认");
  expect(screen.queryByText("Failed to fetch")).not.toBeInTheDocument();
  expect(screen.getByLabelText("核对依据 / 更正原因")).toBeDisabled();
  const id=vi.mocked(writeApi).mock.calls[1]![1]!.operationKey;
  await user.click(screen.getByRole("button", {name: "查询原操作结果"}));
  expect(await screen.findByText("已保存核对修订 3")).toBeVisible();
  expect(vi.mocked(requestApi).mock.calls[0]![0]).toBe("/api/production/inventory-reviews/qa/operations/"+id);
  expect(writeApi).toHaveBeenCalledTimes(2);
});
