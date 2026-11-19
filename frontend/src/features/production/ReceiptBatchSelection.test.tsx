import { afterEach, beforeEach, expect, it, vi } from "vitest";
import { cleanup, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { createMemoryRouter, RouterProvider } from "react-router-dom";
import { AuthzGenerationProvider } from "../../app/AuthzGenerationContext";
import { ReceiptPanel } from "./WorkbenchOperations";
import { receiptOrderGroups, type ReceiptSourceLine } from "./orderProgress";
import type { Document } from "./types";

const api = vi.hoisted(() => ({ read: vi.fn(), write: vi.fn<(path: string, options: { body: Record<string, unknown> }) => Promise<Record<string, unknown>>>() }));
vi.mock("../../api/client", async original => ({ ...await original<typeof import("../../api/client")>(), requestApi: api.read, writeApi: api.write }));
const line = (id: string, order: string, expected: string, received: string, direct = "0"): ReceiptSourceLine => ({ id, order_id: order, order_label: `PO${order}`, order_reference: `PO${order}`, receipt_factory_name: "测试工厂", sku_id: "9", sku_label: `${order}-${id}`, expected_units: expected, received_units: received, produced_units: expected, production_direct_units: direct, actual_units: "0", difference_units: "0" });
const lines = [line("11", "1", "10", "10"), line("12", "1", "20", "5", "5"), line("21", "2", "10", "10"), line("31", "3", "10", "0", "10"), line("41", "4", "10", "20"), line("42", "4", "10", "0")];
const order: Document = { id: "receipt-batch", revision: "1:3,2:3,3:3,4:3", system_number: "本批入库", business_number: "PO1、PO2、PO3、PO4", status: "CONFIRMED", business_date: null, notes: "", actual_units: "0", receipt_warehouse_id: "1", receipt_owner_id: "1", lines };
const stock = { writes_enabled: true, scopes: [{ warehouse_id: "1", owner_id: "1", warehouse_name: "成品仓", owner_name: "自有", warehouse_type: "OWN", warehouse_status: "ACTIVE" }], items: [] };

beforeEach(() => { api.read.mockReset(); api.write.mockReset(); api.read.mockResolvedValue({ items: [] }); });
afterEach(cleanup);
function mount({ scoped = true, draft = false } = {}) {
  const router = createMemoryRouter([{ path: "/", element: <AuthzGenerationProvider boundary={{ principalId: 1, roles: ["admin"], siteId: 1, siteConfigVersionId: 1 }} onRevoked={() => undefined}><ReceiptPanel receiptBatch selectBatchOrders={scoped} guided order={order} stock={stock} canWrite saved={() => undefined} resumeDraftId={draft ? "90" : undefined} /></AuthzGenerationProvider> }]);
  render(<RouterProvider router={router} />);
}
async function openSelection() { const text = screen.getByText(/选择订单 · 已选/); if (!text.closest("details")?.open) await userEvent.click(text); }
async function choose(id: string) { await openSelection(); const details = screen.getByText(/已收齐 · \d+ 单/); if (["2", "3"].includes(id) && !details.closest("details")?.open) await userEvent.click(details); await userEvent.click(screen.getByLabelText(`选择订单${id} PO${id}`)); }

it("defaults to incomplete orders by individual line and counts factory direct shipments without treating them as receipts", async () => {
  const groups = receiptOrderGroups(lines);
  expect(groups.map(g => [g.id, g.complete, g.remaining?.toString()])).toEqual([["1", false, "10"], ["2", true, "0"], ["3", true, "0"], ["4", false, "10"]]);
  mount(); await openSelection();
  expect(screen.getByLabelText("选择订单1 PO1")).toBeChecked(); expect(screen.getByLabelText("选择订单4 PO4")).toBeChecked();
  await userEvent.click(screen.getByText("已收齐 · 2 单")); expect(screen.getByLabelText("选择订单2 PO2")).not.toBeChecked(); expect(screen.getByLabelText("选择订单3 PO3")).not.toBeChecked();
  await userEvent.click(screen.getByRole("button", { name: "下一步" }));
  expect(screen.getByLabelText("1-12本次合格")).toBeVisible(); expect(screen.getByLabelText("4-42本次合格")).toBeVisible();
  expect(screen.queryByLabelText("1-11本次合格")).not.toBeInTheDocument();
  expect(screen.queryByText(/所选订单含已完成或超额/)).not.toBeInTheDocument();
  expect(screen.getByRole("link", { name: "下载入库模板" })).toHaveAttribute("href", expect.stringContaining("orders=1%3A3%2C4%3A3"));
});

it("preserves entered values across selection changes and only submits selected stable order lines", async () => {
  mount(); await userEvent.click(screen.getByRole("button", { name: "下一步" }));
  await userEvent.type(screen.getByLabelText("1-12本次合格"), "3"); await userEvent.type(screen.getByLabelText("4-42本次合格"), "2");
  await choose("1"); expect(screen.queryByLabelText("1-12本次合格")).not.toBeInTheDocument();
  expect(within(screen.getByRole("region", { name: "入库业务参照" })).getByRole("heading", { name: "1 笔订单" })).toBeVisible();
  await choose("1"); expect(screen.getByLabelText("1-12本次合格")).toHaveValue("3"); await choose("1");
  await userEvent.click(screen.getByRole("button", { name: "下一步" })); await userEvent.type(screen.getByRole("textbox", { name: /入库依据 \/ 备注/ }), "模拟分次实收"); await userEvent.click(screen.getByRole("button", { name: "下一步" }));
  api.write.mockResolvedValueOnce({ id: "91", revision: "1", status: "DRAFT" }).mockResolvedValueOnce({ id: "91", revision: "1", status: "DRAFT", preview_hash: "hash", impacts: [] });
  await userEvent.click(screen.getByRole("button", { name: "保存草稿并预览" }));
  await waitFor(() => expect(api.write).toHaveBeenCalledTimes(2));
  expect(api.write.mock.calls[0]?.[1].body.lines).toEqual([{ sku_id: "9", units: "2", quality: "QUALIFIED", purpose: "PRODUCTION_RECEIPT", counterparty: "测试工厂", production_allocations: [{ order_line_id: "42", units: "2" }] }]);
  expect(screen.getByLabelText("选择订单1 PO1")).toBeDisabled();
  api.write.mockResolvedValueOnce({ id: "91", revision: "2", status: "POSTED" });
  await userEvent.click(await screen.findByRole("button", { name: "确认本次入库" }));
  expect(await screen.findByText("本批入库已确认")).toBeVisible();
  expect(api.write.mock.calls[2]?.[0]).toBe("/api/production/inventory/documents/91/confirm");
});

it("keeps fully received products collapsed and warns only after an actual excess is entered", async () => {
  mount(); await userEvent.click(screen.getByRole("button", { name: "下一步" }));
  await userEvent.click(screen.getByText("已收齐 · 2 项"));
  const input = screen.getByLabelText("1-11本次合格"); expect(input).toBeVisible();
  expect(screen.queryByText("本次有超收，请在日期与依据填写原因")).not.toBeInTheDocument();
  await userEvent.type(input, "1"); expect(screen.getByText("本次有超收，请在日期与依据填写原因")).toBeVisible();
  await userEvent.clear(input); expect(screen.queryByText("本次有超收，请在日期与依据填写原因")).not.toBeInTheDocument();
});

it("restores the saved draft order selection even when that order is already fully received", async () => {
  api.read.mockResolvedValue({ id: "90", revision: "2", status: "DRAFT", kind: "IN", warehouse_id: "1", owner_id: "1", business_date: "2026-11-12", reason: "模拟补收", lines: [{ sku_id: "9", units: "1", quality: "QUALIFIED", purpose: "PRODUCTION_RECEIPT", production_allocations: [{ order_line_id: "21", units: "1" }] }] });
  mount({ draft: true }); await screen.findByRole("heading", { name: "1 笔订单" }); await openSelection(); await userEvent.click(screen.getByText("已收齐 · 2 单"));
  expect(screen.getByLabelText("选择订单2 PO2")).toBeChecked(); expect(screen.getByLabelText("选择订单1 PO1")).not.toBeChecked();
  await userEvent.click(screen.getByRole("button", { name: "下一步" })); expect(screen.getByLabelText("2-21本次合格")).toHaveValue("1");
});

it("does not add selection or folding to the original non-opted-in receipt path", async () => {
  mount({ scoped: false }); expect(screen.queryByText(/选择订单 · 已选/)).not.toBeInTheDocument(); await userEvent.click(screen.getByRole("button", { name: "下一步" })); expect(screen.getByLabelText("1-11本次合格")).toBeVisible(); expect(screen.getByLabelText("3-31本次合格")).toBeVisible();
});

it("blocks advancing with no selected orders and never treats missing receipt facts as fully received", async () => {
  expect(receiptOrderGroups([{ ...lines[0]!, received_units: undefined }])[0]?.complete).toBe(false);
  mount(); await choose("1"); await choose("4");
  expect(screen.getByRole("button", { name: "下一步" })).toBeDisabled();
  expect(within(screen.getByRole("region", { name: "入库业务参照" })).getByRole("heading", { name: "0 笔订单" })).toBeVisible();
  expect(api.write).not.toHaveBeenCalled();
});

it("imports within the selected revision scope and reveals received rows that have imported quantities", async () => {
  mount(); await choose("2"); await userEvent.click(screen.getByRole("button", { name: "下一步" }));
  api.write.mockResolvedValueOnce({ kind: "receipt", filename: "模拟.xlsx", source_digest: "sim", order_id: "receipt-batch", order_revision: "1:3,2:3,4:3", total_units: "1", box_count: 0, issues: [], rows: [{ row: 2, sku_id: "9", order_line_id: "21", sku_label: "2-21", qualified_units: "1" }], cartons: [] });
  await userEvent.upload(screen.getByLabelText("本次导入的XLSX文件（不超过2MB）"), new File(["simulated"], "模拟.xlsx", { type: "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet" }));
  await waitFor(() => expect(screen.getByLabelText("2-21本次合格")).toHaveValue("1"));
  expect(api.write.mock.calls[0]?.[0]).toContain("orders=1%3A3%2C2%3A3%2C4%3A3");
  expect(screen.getByText("本次有超收，请在日期与依据填写原因")).toBeVisible();
});
