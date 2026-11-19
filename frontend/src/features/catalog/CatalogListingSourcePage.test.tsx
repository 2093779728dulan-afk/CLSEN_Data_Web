import { beforeEach, describe, expect, it, vi } from "vitest";
import { act, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { ApiRequestError, requestApi } from "../../api/client";
import { CatalogListingSourcePage } from "./CatalogListingSourcePage";

vi.mock("../../api/client", async () => {
  const request = vi.fn<(path: string, options?: unknown) => Promise<unknown>>();
  return { ...await vi.importActual("../../api/client"), requestApi: request, writeApi: (path: string, options: object) => request(path, { ...options, method: "POST" }), commandApi: (path: string, body: object, key: string) => request(path, { body, method: "POST", headers: { "Idempotency-Key": key } }) };
});
const auth = vi.hoisted(() => ({ purge: () => undefined as void, registerSensitivePurge: (purge: () => void) => { auth.purge = purge; return () => undefined; } }));
vi.mock("../../app/AuthzGenerationContext", () => ({ useAuthzGeneration: () => ({ generation: 1, registerSensitivePurge: auth.registerSensitivePurge }) }));
const request = vi.mocked(requestApi);
const variant = { row_id: "s1-r4", sheet: "QA甲", row: 4, seller_sku: "0012-Olive-M", asin: "B000000001", fnsku: "XQA1", cell_types: { seller_sku: "s" }, suggestion: { style_code: "0012", color: "Olive", size: "M" }, suggested_type: "variant", issues: [] };
const parent = { ...variant, row_id: "s1-r5", row: 5, seller_sku: "0012", suggestion: null, suggested_type: "unknown" };
const selected = { row_id: "s1-r4", include: true, record_type: "variant", style_code: "0012", color: "Olive", size: "M", selected_sku_id: 14, use_official: true, confirm_raw_parent: false, note: "QA checked", scope_id: 1, platform_mapping: true, sku_row_key: "sku-14", seller_sku: variant.seller_sku };
function result(selections: object[] = []) { return { import_id: 42, status: "approved", workflow_revision: 4, catalog_publication_revision: 28, source: { source_name: "QA.xlsx", sheets: [{ name: "QA甲", count: 2 }], listing_rows: [variant, parent], selections, bindings: { QA甲: 1 } }, assessments: [variant, parent].map(row => ({ row_id: row.row_id, state: row === variant ? "source_difference" : "no_official", message: "QA中文核对结果", scope_id: 1, official_asins: ["B0SYNTH001"], official_fnskus: [], official_parent_asins: [], observations: [], duplicate_rows: [row.row_id], primary_row: row.row_id, can_map: true })), inventory: [{ sku_id: 14, style_code: "0012", standard_color: "Olive", standard_size: "M", internal_display_sku: variant.seller_sku, status: "enabled" }], mappings: [], stale: false, check_id: "123", coverage: { message: "仅比较已发布的官方报告", members: [] } }; }
let current = result();
let save: (body: Record<string, unknown>) => unknown;
beforeEach(() => {
  current = result(); request.mockReset(); save = () => ({ import_id: 43 });
  request.mockImplementation(async (path, options) => {
    if (path.endsWith("/capabilities")) return { enabled: true, can_manage: true, scopes: [{ id: 1, seller_account_display_name: "QA账号", marketplace_scope_code: "amazon_us" }] } as never;
    if (path.endsWith("/preview")) return await save(options?.body as unknown as Record<string, unknown>) as never;
    if (path.endsWith("/compare")) return current as never;
    if (path === "/api/catalog/production-sources") return { items: [] } as never;
    return current as never;
  });
});
function mount() { return render(<MemoryRouter initialEntries={["/catalog/production-sources?entry=amazon-listing&listing=42"]}><Routes><Route path="/catalog/production-sources" element={<CatalogListingSourcePage />} /><Route path="/catalog/imports/:id" element={<p>QA审核页面</p>} /></Routes></MemoryRouter>); }

describe("listing reconciliation", () => {
  it("continues an approved batch using only request fields and persists a parent-only result", async () => {
    current = result([selected]); const user = userEvent.setup();
    let saved: Record<string, unknown> | undefined;
    save = body => { saved = body; current = result(body.selections as object[]); return { import_id: 42, source_only: true }; };
    const view = mount();
    const row = within(await screen.findByRole("article", { name: "QA甲第4行 0012-Olive-M" }));
    await user.click(row.getByRole("checkbox", { name: "本次处理" }));
    const father = within(screen.getByRole("article", { name: "QA甲第5行 0012" }));
    await user.click(father.getByRole("checkbox", { name: "本次处理" }));
    await user.selectOptions(father.getByRole("combobox", { name: "记录类型" }), "parent");
    await user.click(father.getByRole("checkbox", { name: /已核实父级类型/ }));
    await user.click(screen.getByRole("button", { name: "保存父级核对" }));
    await screen.findByText(/父级核对已保存，原始行和操作依据已保留/);
    for (const selection of saved!.selections as Record<string, unknown>[]) {
      expect(selection).not.toHaveProperty("platform_mapping"); expect(selection).not.toHaveProperty("scope_id"); expect(selection).not.toHaveProperty("sku_row_key"); expect(selection).not.toHaveProperty("seller_sku");
    }
    view.unmount(); mount();
    expect(await screen.findByRole("checkbox", { name: /已核实父级类型/ })).toBeChecked();
    expect(screen.queryByText("QA审核页面")).not.toBeInTheDocument();
  });
  it("shows row-specific Chinese rejection and retains input", async () => {
    const user = userEvent.setup(); save = () => { throw new ApiRequestError(422, "listing_official_confirmation", "工作表QA甲，第4行：请核对差异并明确采用官方依据。"); };
    mount(); const row = within(await screen.findByRole("article", { name: "QA甲第4行 0012-Olive-M" }));
    await user.click(row.getByRole("checkbox", { name: "本次处理" }));
    await user.click(screen.getByRole("button", { name: "保存所选候选并进入审核" }));
    await screen.findByText(/第4行：请核对差异/);
    expect(row.getByRole("textbox", { name: "款号（必填）" })).toHaveValue("0012");
    expect(row.getByRole("checkbox", { name: "本次处理" })).toBeChecked();
  });
  it("replays an uncertain save with the same token and body while locking edits", async () => {
    current = result([selected]); const attempts: object[] = []; const user = userEvent.setup();
    save = body => { attempts.push(body); if (attempts.length === 1) throw new TypeError("Failed to fetch"); return { import_id: 43 }; };
    mount(); await screen.findByRole("article", { name: "QA甲第4行 0012-Olive-M" });
    await user.click(screen.getByRole("button", { name: "保存所选候选并进入审核" }));
    await screen.findByText("保存结果尚不确定");
    expect(screen.getAllByRole("combobox", { name: "记录类型" })[0]).toBeDisabled();
    expect(screen.queryByText(/Failed to fetch/)).not.toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "查询或重发原保存" }));
    await screen.findByText("QA审核页面"); expect(attempts[1]).toEqual(attempts[0]);
  });
  it("requires rechecking after a known conflict and clears row choices when scope changes", async () => {
    current = result([selected]); const user = userEvent.setup();
    save = () => { throw new ApiRequestError(409, "listing_stale", "官方报表或目录已更新，请重新核对。"); };
    mount(); await screen.findByRole("article", { name: "QA甲第4行 0012-Olive-M" });
    await user.click(screen.getByRole("button", { name: "保存所选候选并进入审核" }));
    await screen.findByText(/官方报表或目录已更新/);
    expect(screen.getByRole("button", { name: "保存所选候选并进入审核" })).toBeDisabled();
    await user.selectOptions(screen.getByRole("combobox", { name: "QA甲 的店铺账号和站点（必选）" }), "");
    expect(screen.getAllByRole("checkbox", { name: "本次处理" })[0]).not.toBeChecked();
    expect(screen.getByRole("button", { name: "核对官方报表" })).toBeDisabled();
  });
  it("does not render a late response after permissions are purged", async () => {
    let resolve: (value: unknown) => void = () => undefined;
    const original = request.getMockImplementation()!;
    request.mockImplementation(async (path, options) => path === "/api/catalog/listing-sources/42" ? await new Promise<unknown>(r => { resolve = r; }) as never : original(path, options));
    mount(); await screen.findByLabelText("上传亚马逊商品清单");
    await act(async () => { auth.purge(); resolve(current); await Promise.resolve(); });
    await waitFor(() => expect(screen.queryByRole("article")).not.toBeInTheDocument());
    expect(screen.queryByText("QA.xlsx · 批次42")).not.toBeInTheDocument();
  });
});
