import { cleanup, render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { createMemoryRouter, RouterProvider } from "react-router-dom";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import { AuthzGenerationProvider } from "../../app/AuthzGenerationContext";
import { ReceiptPanel } from "./WorkbenchOperations";
import type { Document } from "./types";
const api = vi.hoisted(() => ({ read: vi.fn(), write: vi.fn() }));
vi.mock("../../api/client", async original => ({ ...await original<typeof import("../../api/client")>(), requestApi: api.read, writeApi: api.write }));
const normal = { warehouse_id: "1", owner_id: "1", warehouse_name: "普通仓", owner_name: "自有", warehouse_type: "OWN", warehouse_status: "ACTIVE" };
const fba = { ...normal, warehouse_id: "2", warehouse_name: "FBA仓", warehouse_type: "FBA" };
const order: Document = { id: "10", revision: "2", system_number: "SIM-10", business_number: "SIM", status: "CONFIRMED", business_date: null, notes: "", actual_units: "0", lines: [{ id: "11", sku_id: "9", sku_label: "1112-Black-S", expected_units: "10", actual_units: "0", difference_units: "10" }] };
beforeEach(() => { api.read.mockReset(); api.write.mockReset(); });
afterEach(cleanup);
function mount(prefilled = false, draft = false) {
  render(<RouterProvider router={createMemoryRouter([{ path: "/", element: <AuthzGenerationProvider boundary={{ principalId: 1, roles: ["admin"], siteId: 1, siteConfigVersionId: 1 }} onRevoked={() => undefined}><ReceiptPanel receiptBatch guided order={{ ...order, ...(prefilled ? { receipt_warehouse_id: "2", receipt_owner_id: "1" } : {}) }} stock={{ writes_enabled: true, items: [], scopes: [normal, fba, { ...normal, warehouse_id: "3", warehouse_name: "停用仓", warehouse_status: "INACTIVE" }, { ...normal, warehouse_id: "4", warehouse_name: "未知仓", warehouse_type: undefined }] }} canWrite saved={() => undefined} resumeDraftId={draft ? "22" : undefined} /></AuthzGenerationProvider> }])} />);
}
it("only offers active ordinary scopes for both manual and imported production receipts", async () => {
  mount();
  const selector = screen.getByRole("combobox", { name: "本次实收入库仓库" });
  expect(within(selector).getAllByRole("option").map(option => option.textContent)).toEqual(["请选择已登记仓库", "普通仓"]);
  await userEvent.selectOptions(selector,"1:1");
  await userEvent.click(screen.getByRole("button",{name:"下一步"}));
  expect(screen.getByRole("link", { name: "下载入库模板" })).toBeVisible();
  expect(within(selector).queryByRole("option", { name: "FBA仓" })).not.toBeInTheDocument();
  expect(api.write).not.toHaveBeenCalled();
});
it("does not silently replace an FBA URL preselection and lets the user choose a valid scope", async () => {
  mount(true);
  expect(screen.getByText("请选择可办理生产入库的普通仓库")).toBeVisible();
  await userEvent.click(screen.getByRole("button", { name: "下一步" }));
  expect(screen.queryByRole("table", { name: "本次入库产品" })).not.toBeInTheDocument();
  expect(api.write).not.toHaveBeenCalled();
  await userEvent.selectOptions(screen.getByRole("combobox", { name: "本次实收入库仓库" }), "1:1");
  await userEvent.click(screen.getByRole("button", { name: "下一步" }));
  expect(screen.getByRole("table", { name: "本次入库产品" })).toBeVisible();
});
it("preserves an unsupported saved draft as a readable record without opening a replacement editor", async () => {
  api.read.mockResolvedValue({ id: "22", revision: "1", status: "DRAFT", kind: "IN", warehouse_id: "2", owner_id: "1", lines: [{ sku_id: "9", units: "1", quality: "QUALIFIED", purpose: "PRODUCTION_RECEIPT", production_allocations: [{ order_line_id: "11", units: "1" }] }] });
  mount(false, true);
  expect(await screen.findByRole("link", { name: "查看原入库草稿" })).toHaveAttribute("href", "/production/stock/movements/22");
  expect(screen.queryByRole("button", { name: "下一步" })).not.toBeInTheDocument();
  expect(api.write).not.toHaveBeenCalled();
});
