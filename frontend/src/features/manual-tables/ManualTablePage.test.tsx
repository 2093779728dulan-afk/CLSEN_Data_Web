import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { createMemoryRouter, RouterProvider } from "react-router-dom";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import { AuthzGenerationProvider } from "../../app/AuthzGenerationContext";
import { ApiRequestError } from "../../api/client";
import { ManualTablePage } from "./ManualTablePage";
import type { ManualBatch, ManualResult, ManualRow } from "./manualTablesApi";

const api = vi.hoisted(() => ({ read: vi.fn(), write: vi.fn() }));
vi.mock("../../api/client", async importOriginal => ({ ...(await importOriginal<object>()), requestApi: api.read, writeApi: api.write }));
const result: ManualResult = { rows: [], issues: [{ code: "missing_columns", message: "商品编码列尚未对应", suggestion: "请选择原商品编码列", source_ref: { sheet: "Sheet1", row: 1, cell: "A1" }, blocking: true }], total_units: "0", state: "NEEDS_MAPPING", columns: {}, sheet: "Sheet1", header_row: 1, sheets: [{ name: "Sheet1", rows: 3, columns: 2 }], samples: [[{ cell: "A1", column: 1, value: "" }, { cell: "B1", column: 2, value: "数量" }]], excluded_rows: [] };
const batch: ManualBatch = { id: "batch", kind: "packing", filename: "虚构装箱.xlsx", source_digest: "a".repeat(64), revision: 0, options: { sheet: "", header_row: null, start_row: null, end_row: null, columns: {}, context: {}, zero_policy: "unknown", decisions: {} }, result, target: null, owner_id: "1", updated_at: "2026-10-16T00:00:00Z" };
function mount() { const router = createMemoryRouter([{ path: "/production/manual-tables/:batch_id", element: <ManualTablePage /> }], { initialEntries: ["/production/manual-tables/batch"] }); return render(<AuthzGenerationProvider boundary={{ principalId: 1, siteId: 1, siteConfigVersionId: 1, roles: ["admin"] }} onRevoked={vi.fn()}><RouterProvider router={router} /></AuthzGenerationProvider>); }
beforeEach(() => { api.read.mockReset(); api.write.mockReset(); api.read.mockImplementation((path: string) => Promise.resolve(path.endsWith("capabilities") ? { enabled: true } : path.endsWith("/batch") ? structuredClone(batch) : { items: [], total: 0 })); });
afterEach(cleanup);

it("shows a disabled environment without fetching manual batches", async () => {
  api.read.mockResolvedValue({ enabled: false }); mount();
  expect(await screen.findByText("当前未启用人工表格整理")).toBeInTheDocument();
  expect(api.read).toHaveBeenCalledTimes(1);
});

it("selects missing fields, previews, saves and shows the saved revision", async () => {
  const user = userEvent.setup(); mount();
  await screen.findByText(/商品编码列尚未对应/);
  await user.selectOptions(screen.getByRole("combobox", { name: "原商品编码对应列" }), "1");
  const preview = { ...result, state: "READY", issues: [], total_units: "4" };
  api.write.mockResolvedValueOnce({ result: preview, preview_hash: "hash" });
  await user.click(screen.getByRole("button", { name: "重新提取并预览" }));
  await waitFor(() => expect(screen.getByRole("button", { name: "保存本次整理" })).toBeEnabled());
  const request = api.write.mock.calls[0]?.[1] as { body: { options: ManualBatch["options"] } };
  expect(request.body.options.columns.code).toBe(1);
  api.write.mockResolvedValueOnce({ ...batch, revision: 1, options: request.body.options, result: preview });
  await user.click(screen.getByRole("button", { name: "保存本次整理" }));
  expect(await screen.findByText("整理资料已保存，当前尚未入账。")).toBeInTheDocument();
  expect(screen.getByText(/修订1/)).toBeInTheDocument();
});

it("keeps an explicit ignored column as zero in the request", async () => {
  const user = userEvent.setup(); mount(); await screen.findByText(/商品编码列尚未对应/);
  await user.selectOptions(screen.getByRole("combobox", { name: "原商品编码对应列" }), "1");
  await user.selectOptions(screen.getByRole("combobox", { name: "原商品编码对应列" }), "0");
  api.write.mockResolvedValue({ result, preview_hash: "hash" });
  await user.click(screen.getByRole("button", { name: "重新提取并预览" }));
  const request = api.write.mock.calls[0]?.[1] as { body: { options: ManualBatch["options"] } };
  expect(request.body.options.columns.code).toBe(0);
});

const detail: ManualRow = { source_line_key: "Sheet1!3:M", source_ref: { sheet: "Sheet1", row: 3, cell: "C3" }, style: "99001", color: "Blue", size: "M", code: "RAW-01", units: "10", boxes: {}, excluded: false, raw: { quantity: "10" }, issues: [], match: { status: "unmatched", sku_id: null, catalog_version: null } };
function showDetails(rows = [detail], extra: Partial<ManualBatch> = {}, handoffEnabled = true, inventoryHandoffEnabled = true) {
  const value = { ...structuredClone(batch), kind: "inventory" as const, result: { ...structuredClone(result), state: "READY", issues: [], rows: structuredClone(rows), total_units: "10" }, ...extra };
  api.read.mockImplementation((path: string) => Promise.resolve(path.endsWith("capabilities") ? { enabled: true, handoff_enabled: handoffEnabled, inventory_handoff_enabled: inventoryHandoffEnabled } : path.endsWith("/batch") ? value : path.endsWith("/catalog") ? { items: [{ sku_id: "sku1", style: "99001", color: "Blue", size: "M", code: "99001-Blue-M", active: true }] } : path === "/api/production/inventory/availability" ? { scopes: [{ warehouse_id: "1", owner_id: "1", warehouse_name: "虚构库存仓" }] } : path === "/api/production/orders" ? { items: [], total: 0, page: 1, page_size: 20 } : { items: [], total: 0 }));
  mount(); return value;
}

it.each(["inventory", "orders", "packing"] as const)("keeps %s preparation usable while business handoff is disabled", async kind => {
  const user = userEvent.setup();
  showDetails([detail], {kind}, false);
  await screen.findByRole("button", {name: "核对第3行M"});
  expect(screen.getByText("当前仅开放资料整理")).toBeInTheDocument();
  expect(screen.queryByRole("button", {name: /创建库存资料核对|转为预计订单草稿|转为实际出货草稿/})).not.toBeInTheDocument();
  expect(screen.getByRole("button", {name: "预览核对结果"})).toBeEnabled();
  await user.click(screen.getByText("导出资料及保存字段方案"));
  expect(screen.getByRole("button", {name: "导出标准明细"})).toBeEnabled();
});

it.each(["inventory", "orders", "packing"] as const)("separates inventory handoff from %s business draft entry", async kind => {
  showDetails([detail], {kind}, true, false);
  await screen.findByRole("button", {name: "核对第3行M"});
  if (kind === "inventory") {
    expect(screen.getByText("当前仅开放资料整理")).toBeInTheDocument();
    expect(screen.queryByRole("button", {name: "预览业务衔接"})).not.toBeInTheDocument();
    expect(screen.queryByRole("button", {name: "创建库存资料核对"})).not.toBeInTheDocument();
  } else {
    expect(screen.getByRole("button", {name: "预览业务衔接"})).toBeInTheDocument();
    expect(screen.getByRole("button", {name: kind === "orders" ? "转为预计订单草稿" : "转为实际出货草稿"})).toBeDisabled();
  }
  expect(api.write).not.toHaveBeenCalled();
});

it("previews business quantities and similar records before creating a draft", async () => {
  const user = userEvent.setup();
  showDetails([{ ...detail, match: { status: "matched", sku_id: "sku1", catalog_version: "7:2" } }], {
    kind: "orders", options: { ...batch.options, context: { date: "2026-10-19", source_note: "另一笔独立虚构订单" } },
  });
  const create = await screen.findByRole("button", { name: "转为预计订单草稿" });
  expect(create).toBeDisabled();
  api.write.mockResolvedValueOnce({ target_kind: "order", total_units: "10", sku_count: 1, source_row_count: 1,
    excluded_row_count: 0, inventory_effect_units: "0", business_date: "2026-10-19", source_revision: 0,
    handoff_preview_hash: "a".repeat(64), candidates: [{ id: "9", system_number: "PO-QA-9", url: "/production/orders/9" }] });
  await user.click(screen.getByRole("button", { name: "预览业务衔接" }));
  expect(await screen.findByRole("link", { name: "查看相似单据 PO-QA-9" })).toHaveAttribute("href", "/production/orders/9");
  expect(screen.getByText(/本次只生成草稿或资料关联，库存不变/)).toBeInTheDocument();
  expect(create).toBeEnabled();
  expect(api.write.mock.calls[0]?.[0]).toBe("/api/manual-tables/batches/batch/handoff-preview");
  api.write.mockImplementationOnce(() => new Promise(() => {}));
  await user.click(create);
  const sent = api.write.mock.calls[1]?.[1] as { body: { handoff_preview_hash: string } };
  expect(sent.body.handoff_preview_hash).toBe("a".repeat(64));
});

it("invalidates business preview after a stale response or an unsaved context change", async () => {
  const user = userEvent.setup();
  showDetails([{ ...detail, match: { status: "matched", sku_id: "sku1", catalog_version: "7:2" } }], {
    kind: "orders", options: { ...batch.options, context: { date: "2026-10-19", source_note: "独立虚构订单" } },
  });
  const preview = { target_kind: "order", total_units: "10", sku_count: 1, source_row_count: 1, excluded_row_count: 0,
    inventory_effect_units: "0", business_date: "2026-10-19", source_revision: 0, handoff_preview_hash: "a".repeat(64), candidates: [] };
  api.write.mockResolvedValueOnce(preview);
  await user.click(await screen.findByRole("button", { name: "预览业务衔接" }));
  const create = screen.getByRole("button", { name: "转为预计订单草稿" });
  await waitFor(() => expect(create).toBeEnabled());
  api.write.mockRejectedValueOnce(new ApiRequestError(409, "manual_handoff_preview_stale", "相似单据已有变化，请重新预览。"));
  await user.click(create);
  expect(await screen.findByText("相似单据已有变化，请重新预览。")).toBeInTheDocument();
  expect(create).toBeDisabled();
  api.write.mockResolvedValueOnce(preview);
  await user.click(screen.getByRole("button", { name: "预览业务衔接" }));
  await waitFor(() => expect(create).toBeEnabled());
  await user.type(screen.getByLabelText("来源说明（业务草稿必填）"), "补充来源");
  expect(create).toBeDisabled();
  expect(screen.queryByText("业务衔接预览（尚未创建目标）")).not.toBeInTheDocument();
});

it("keeps original formatting visible beside normalized product values after loading saved data", async () => {
  showDetails([{ ...detail, format_adjustments: [{ field: "color", before: " BLUE ", after: "Blue", reason: "仅整理格式" }] }]);
  await screen.findByRole("button", { name: "核对第3行M" });
  expect(screen.getByText('" BLUE "')).toBeInTheDocument();
  expect(screen.getByText('"Blue"')).toBeInTheDocument();
  expect(screen.getByText("RAW-01")).toBeInTheDocument();
});

it("expands one row and preserves quantity, reason, product and exclusion decisions through preview and save", async () => {
  const user = userEvent.setup(); const value = showDetails();
  await screen.findByRole("button", { name: "核对第3行M" });
  expect(screen.queryByRole("textbox", { name: "第3行M核对数量" })).not.toBeInTheDocument();
  await user.click(screen.getByRole("button", { name: "核对第3行M" }));
  await user.clear(screen.getByRole("textbox", { name: "第3行M核对数量" }));
  await user.type(screen.getByRole("textbox", { name: "第3行M核对数量" }), "11");
  await user.clear(screen.getByRole("textbox", { name: "第3行M修改原因" }));
  await user.type(screen.getByRole("textbox", { name: "第3行M修改原因" }), "复核实物为11件");
  await user.click(screen.getByRole("button", { name: "排除本行" }));
  expect(screen.getByText("已排除")).toBeInTheDocument();
  await user.click(screen.getByRole("button", { name: "恢复明细" }));
  await user.click(screen.getByRole("button", { name: "收起第3行M" }));
  await user.click(screen.getByRole("button", { name: "核对第3行M" }));
  expect(screen.getByRole("textbox", { name: "第3行M核对数量" })).toHaveValue("11");
  expect(screen.getByRole("textbox", { name: "第3行M修改原因" })).toHaveValue("复核实物为11件");
  await user.click(screen.getByRole("button", { name: "选择商品" }));
  await user.click(screen.getByRole("button", { name: "99001 · Blue / M · 99001-Blue-M" }));
  expect(screen.getByText("已对应")).toBeInTheDocument();
  const nextResult = { ...value.result, rows: [{ ...detail, units: "11", match: { status: "matched", sku_id: "sku1", catalog_version: "1" } }], total_units: "11" };
  api.write.mockResolvedValueOnce({ result: nextResult, preview_hash: "hash" });
  await user.click(screen.getByRole("button", { name: "预览核对结果" }));
  const request = api.write.mock.calls[0]?.[1] as { body: { options: ManualBatch["options"] } };
  expect(request.body.options.decisions[detail.source_line_key]).toMatchObject({ units: "11", sku_id: "sku1", excluded: false, reason: "复核实物为11件" });
  api.write.mockResolvedValueOnce({ ...value, revision: 1, options: request.body.options, result: nextResult });
  await user.click(screen.getByRole("button", { name: "保存整理结果" }));
  expect(await screen.findByText("整理资料已保存，当前尚未入账。")).toBeInTheDocument();
  expect(screen.queryByText(/已改 ·/)).not.toBeInTheDocument();
});

it("edits packing quantities by box without replacing them with a single quantity", async () => {
  const user = userEvent.setup(); showDetails([{ ...detail, boxes: { 箱1: "6", 箱2: "4" } }], { kind: "packing" });
  await user.click(await screen.findByRole("button", { name: "核对第3行M" }));
  await user.clear(screen.getByRole("textbox", { name: "第3行M箱1数量" }));
  await user.type(screen.getByRole("textbox", { name: "第3行M箱1数量" }), "7");
  expect(screen.getByRole("textbox", { name: "第3行M箱2数量" })).toHaveValue("4");
  api.write.mockResolvedValueOnce({ result, preview_hash: "hash" });
  await user.click(screen.getByRole("button", { name: "预览核对结果" }));
  const request = api.write.mock.calls[0]?.[1] as { body: { options: ManualBatch["options"] } };
  expect(request.body.options.decisions[detail.source_line_key]?.boxes).toEqual({ 箱1: "7", 箱2: "4" });
  expect(request.body.options.decisions[detail.source_line_key]?.units).toBeUndefined();
});

it("keeps handed-off row details available to inspect with editing disabled", async () => {
  const user = userEvent.setup(); showDetails([detail], { target: { kind: "inventory_review", token: "token", state: "HANDED_OFF", url: "/production/inventory" } });
  await user.click(await screen.findByRole("button", { name: "核对第3行M" }));
  expect(screen.getByRole("textbox", { name: "第3行M核对数量" })).toBeDisabled();
  expect(screen.getByRole("button", { name: "选择商品" })).toBeDisabled();
  expect(screen.getByRole("button", { name: "排除本行" })).toBeDisabled();
  expect(screen.getByRole("button", { name: "预览核对结果" })).toBeDisabled();
  expect(screen.getByText("已移交的资料仅供查看，请到原业务流程继续处理。")).toBeInTheDocument();
  expect(api.write).not.toHaveBeenCalled();
});

it("filters to actionable rows and shows a clear empty search result", async () => {
  const user = userEvent.setup(); showDetails([detail, { ...detail, source_line_key: "zero", size: "XS", units: "0" }]);
  await screen.findByRole("button", { name: "核对第3行XS" });
  await user.click(screen.getByRole("checkbox", { name: "只看待核明细" }));
  expect(screen.queryByRole("button", { name: "核对第3行XS" })).not.toBeInTheDocument();
  expect(screen.getByRole("button", { name: "核对第3行M" })).toBeInTheDocument();
  await user.type(screen.getByRole("textbox", { name: "查找款号、颜色、尺码" }), "没有的款号");
  expect(screen.getByText("没有符合条件的明细，请调整搜索或关闭待核筛选。")).toBeInTheDocument();
});

it("groups repeated product issues by style and color while keeping the affected sizes visible", async () => {
  const user = userEvent.setup();
  const second = { ...detail, source_line_key: "Sheet1!3:L", source_ref: { sheet: "Sheet1", row: 3, cell: "D3" }, size: "L", units: "5" };
  const issues = [detail, second].map(row => ({ code: "sku_unresolved", message: "商品尚未唯一对应当前主档，请从商品列表选择，或先在商品建档处理。", suggestion: "请核对原表并补充明确值。", source_ref: row.source_ref, blocking: true }));
  showDetails([detail, second], { result: { ...structuredClone(result), state: "NEEDS_REVIEW", rows: [detail, second], issues, total_units: "15" } });
  expect(await screen.findByText("2个规格待对应商品")).toBeInTheDocument();
  expect(screen.queryByText("2组待核（涉及2个规格或单元格）")).not.toBeInTheDocument();
  expect(screen.getByText(/1组待核（涉及2个规格或单元格）/)).toBeInTheDocument();
  expect(screen.getByText("尺码：M、L")).toBeInTheDocument();
  expect(screen.getByText("原表：C3、D3")).toBeInTheDocument();
  expect(screen.getAllByRole("button", { name: "查看这组明细" })).toHaveLength(1);
  await user.click(screen.getByRole("button", { name: "查看这组明细" }));
  expect(screen.getByRole("textbox", { name: "查找款号、颜色、尺码" })).toHaveValue("99001 Blue");
  expect(screen.getByRole("checkbox", { name: "只看待核明细" })).toBeChecked();
  expect(screen.getByRole("textbox", { name: "第3行M核对数量" })).toBeInTheDocument();
});

it("keeps a matched row visible when opening a total mismatch issue", async () => {
  const user = userEvent.setup();
  const matched = { ...detail, match: { status: "matched" as const, sku_id: "sku1", catalog_version: "1" } };
  const totalIssue = { code: "total_mismatch", message: "本行明细合计与原合计99不一致，请核对原表或修改依据。", suggestion: "若原合计有误，可明确采用明细重算并填写原因。", source_ref: matched.source_ref, blocking: true };
  showDetails([matched], { result: { ...structuredClone(result), state: "NEEDS_REVIEW", rows: [matched], issues: [totalIssue], total_units: "10" } });
  await user.click(await screen.findByRole("button", { name: "查看这组明细" }));
  expect(screen.getByRole("checkbox", { name: "只看待核明细" })).toBeChecked();
  expect(screen.getByRole("button", { name: "收起第3行M" })).toBeInTheDocument();
});

it("offers one explicit blank-as-zero preview instead of repeating each empty size", async () => {
  const user = userEvent.setup();
  const empty = { ...detail, units: null, raw: { quantity: "" } };
  const quantityIssue = { code: "quantity_unknown", message: "数量需要明确的非负整数，当前值为“空白”。", suggestion: "核对实际数量；空白及斜杠为0的来源可选择明确的零值规则。", source_ref: empty.source_ref, blocking: true };
  const unresolvedIssue = { code: "sku_unresolved", message: "商品尚未唯一对应当前主档，请从商品列表选择，或先在商品建档处理。", suggestion: "请核对原表并补充明确值。", source_ref: empty.source_ref, blocking: true };
  const value = showDetails([empty], { result: { ...structuredClone(result), state: "NEEDS_REVIEW", rows: [empty], issues: [quantityIssue, unresolvedIssue], total_units: "0" } });
  expect(await screen.findByText(/当前有1条规格明细/)).toHaveTextContent("1组待核（涉及1个规格或单元格）");
  expect(screen.queryByText("1个规格待对应商品")).not.toBeInTheDocument();
  api.write.mockResolvedValueOnce({ result: { ...value.result, rows: [{ ...empty, units: "0", issues: [] }], issues: [], state: "READY" }, preview_hash: "hash" });
  await user.click(await screen.findByRole("button", { name: "空白和斜杠按0重新预览" }));
  await waitFor(() => expect(api.write).toHaveBeenCalledTimes(1));
  const request = api.write.mock.calls[0]?.[1] as { body: { options: ManualBatch["options"] } };
  expect(request.body.options.zero_policy).toBe("blank_slash_zero");
  expect(await screen.findByText("当前提取和商品对应没有待核问题；业务日期及入账前置在原流程继续检查。")).toBeInTheDocument();
});

it("explains missing business context before handoff and never invents a date", async () => {
  const user = userEvent.setup(); const value = showDetails([detail], { kind: "orders" });
  expect(await screen.findByText("还需补充：业务日期、来源说明")).toBeInTheDocument();
  expect(screen.getByRole("button", { name: "转为预计订单草稿" })).toBeDisabled();
  expect(screen.getByLabelText("业务日期", { exact: true, selector: "input" })).toHaveValue("");
  fireEvent.change(screen.getByLabelText("业务日期", { exact: true, selector: "input" }), { target: { value: "2026-10-16" } });
  await user.type(screen.getByLabelText("来源说明（业务草稿必填）"), "虚构原表已核实");
  expect(screen.queryByText(/还需补充：/)).not.toBeInTheDocument();
  expect(screen.getByRole("button", { name: "转为预计订单草稿" })).toBeDisabled();
  api.write.mockResolvedValueOnce({ result: value.result, preview_hash: "hash" });
  await user.click(screen.getByRole("button", { name: "预览核对结果" }));
  const request = api.write.mock.calls[0]?.[1] as { body: { options: ManualBatch["options"] } };
  expect(request.body.options.context.date).toBe("2026-10-16");
  expect(request.body.options.context.source_note).toBe("虚构原表已核实");
  api.write.mockResolvedValueOnce({ ...value, revision: 1, options: request.body.options });
  await user.click(screen.getByRole("button", { name: "保存整理结果" }));
  await waitFor(() => expect(screen.getByRole("button", { name: "预览业务衔接" })).toBeEnabled());
  expect(screen.getByRole("button", { name: "转为预计订单草稿" })).toBeDisabled();
});

it("lets a packing sheet default remaining SKUs to warehouse stock and mark one SKU as production direct", async () => {
  const user = userEvent.setup();
  const row = { ...detail, style: "2305", color: "Ivory White", units: "30", match: { status: "matched", sku_id: "sku1", catalog_version: "1" } };
  const value = showDetails([row], { kind: "packing", options: { ...batch.options, context: { date: "2026-10-16", source_note: "虚构广州装箱资料" } } });
  await user.click(await screen.findByText("实际出货前置与订单归属"));
  await user.click(screen.getByRole("button", { name: "未选择项全部设为仓库库存出货" }));
  const selector = screen.getByLabelText("出货来源 1 2305 · Ivory White / M");
  expect(selector).toHaveValue("WAREHOUSE_STOCK");
  expect(screen.getByText("仓库库存出货所用仓库")).toBeInTheDocument();
  await user.selectOptions(selector, "PRODUCTION_DIRECT");
  expect(screen.queryByText("仓库库存出货所用仓库")).not.toBeInTheDocument();
  api.write.mockResolvedValueOnce({ result: value.result, preview_hash: "hash" });
  await user.click(screen.getByRole("button", { name: "预览核对结果" }));
  const request = api.write.mock.calls[0]?.[1] as { body: { options: ManualBatch["options"] } };
  expect(JSON.parse(request.body.options.context.fulfillment_modes!)).toEqual({ sku1: "PRODUCTION_DIRECT" });
});

it("keeps generated inventory reviews visible from the inventory material record", async () => {
  const record = { ...batch, id: "stock-source", kind: "inventory", filename: "虚构库存结存.xlsx", target: { state: "HANDED_OFF", url: "/production/inventory?review=qa-review" } };
  api.read.mockImplementation((path: string) => path.endsWith("capabilities") ? Promise.resolve({ enabled: true }) : path.includes("/batches?") ? Promise.resolve({ items: [record], total: 1 }) : Promise.resolve({ items: [], total: 0 }));
  const router = createMemoryRouter([{ path: "/production/stock/materials", element: <ManualTablePage view="records" initialKind="inventory" /> }], { initialEntries: ["/production/stock/materials"] });
  render(<AuthzGenerationProvider boundary={{ principalId: 1, siteId: 1, siteConfigVersionId: 1, roles: ["admin"] }} onRevoked={vi.fn()}><RouterProvider router={router} /></AuthzGenerationProvider>);
  expect(await screen.findByRole("table", { name: "资料记录" })).toBeInTheDocument();
  expect(screen.getByRole("link", { name: "打开库存核对：虚构库存结存.xlsx" })).toHaveAttribute("href", "/production/inventory?review=qa-review");
  expect(screen.getByRole("link", { name: "查看整理资料：虚构库存结存.xlsx" })).toHaveAttribute("href", "/production/stock/materials/stock-source");
});

it("stops the loading state when material records cannot be read", async () => {
  api.read.mockImplementation((path: string) => path.endsWith("capabilities") ? Promise.resolve({ enabled: true }) : path.includes("/batches?") ? Promise.reject(new Error("资料存储暂不可用，请稍后重试。")) : Promise.resolve({ items: [], total: 0 }));
  const router = createMemoryRouter([{ path: "/production/stock/materials", element: <ManualTablePage view="records" initialKind="inventory" /> }], { initialEntries: ["/production/stock/materials"] });
  render(<AuthzGenerationProvider boundary={{ principalId: 1, siteId: 1, siteConfigVersionId: 1, roles: ["admin"] }} onRevoked={vi.fn()}><RouterProvider router={router} /></AuthzGenerationProvider>);
  expect(await screen.findByText("资料存储暂不可用，请稍后重试。")).toBeInTheDocument();
  expect(screen.queryByText("正在读取资料记录…")).not.toBeInTheDocument();
  expect(screen.queryByText("还没有人工资料")).not.toBeInTheDocument();
});


it("keeps business and target filters across record pages without showing a premature empty result", async () => {
  const user = userEvent.setup();
  const record = { ...batch, id: "source", kind: "orders", filename: "仅本订单原表.xlsx", target: { state: "HANDED_OFF", url: "/production/orders/4" } };
  let finishListing: ((value: unknown) => void) | undefined;
  api.read.mockImplementation((path: string) => path.endsWith("capabilities") ? Promise.resolve({ enabled: true }) : path.includes("/batches?") ? new Promise(resolve => { finishListing = resolve; }) : Promise.resolve({ items: [], total: 0 }));
  const router = createMemoryRouter([{ path: "/production/orders/4", element: <ManualTablePage view="records" initialKind="orders" targetUrl="/production/orders/4" /> }], { initialEntries: ["/production/orders/4"] });
  render(<AuthzGenerationProvider boundary={{ principalId: 1, siteId: 1, siteConfigVersionId: 1, roles: ["admin"] }} onRevoked={vi.fn()}><RouterProvider router={router} /></AuthzGenerationProvider>);
  await waitFor(() => expect(finishListing).toBeDefined());
  expect(screen.queryByText("还没有人工资料")).not.toBeInTheDocument();
  finishListing!({ items: [record], total: 31 });
  await screen.findByText("仅本订单原表.xlsx");
  expect(screen.queryByRole("link", { name: "继续业务处理" })).not.toBeInTheDocument();
  expect(screen.getByRole("link", { name: "查看整理资料：仅本订单原表.xlsx" })).toHaveAttribute("href", "/production/orders/materials/source");
  await user.click(screen.getByRole("button", { name: "下一页" }));
  await waitFor(() => expect(api.read).toHaveBeenCalledWith("/api/manual-tables/batches?page=2&kind=orders&target_url=%2Fproduction%2Forders%2F4"));
  finishListing!({ items: [], total: 31 });
  await screen.findByText("此单据没有人工整理来源");
  expect(api.write).not.toHaveBeenCalled();
});
