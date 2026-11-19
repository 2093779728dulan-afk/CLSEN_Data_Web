import { act, cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { createMemoryRouter, RouterProvider } from "react-router-dom";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import { ApiRequestError } from "../../api/client";
import { CatalogListingSourcePage } from "./CatalogListingSourcePage";
import type { Result, SourceRow } from "./CatalogListingSourcePage";

type WriteOptions = { body?: Record<string, unknown>; operationKey?: string; rawBody?: File; headers?: Record<string, string> };
const api = vi.hoisted(() => ({ read: vi.fn<(path: string, options?: unknown) => Promise<unknown>>(), write: vi.fn<(path: string, options?: WriteOptions) => Promise<unknown>>() }));
vi.mock("../../api/client", async original => ({ ...await original<typeof import("../../api/client")>(), requestApi: api.read, writeApi: api.write, commandApi: (path: string, body: Record<string, unknown>, token: string) => api.write(path, { body, operationKey: token }) }));
vi.mock("../../app/AuthzGenerationContext", () => ({ useAuthzGeneration: () => ({ generation: 1, registerSensitivePurge: () => () => undefined }) }));

const sourceRow = (id: string, sku: string, state: string, row: number): SourceRow => ({ row_id: id, sheet: "示例店", row, seller_sku: sku, asin: "B000000001", fnsku: "XQA0000001", cell_types: { seller_sku: "s" }, cell_locations: { seller_sku: `B${row}` }, registration: { state, sku_id: state === "registered" ? 14 : null }, suggested_type: state === "parent" ? "parent" : "variant", suggestion: state === "parent" ? null : { style_code: sku.split("-")[0]!, color: sku.split("-")[1]!, size: sku.split("-")[2]! }, issues: [] });
const existing = sourceRow("r1", "0012-Olive-M", "registered", 4);
const missing = sourceRow("r2", "1101-Navy-L", "missing", 5);
const parent = sourceRow("r3", "1101", "parent", 6);
let data: Result;
function result(rows = [existing, missing, parent]): Result { return { import_id: 42, status: "parsed_ready", workflow_revision: 0, catalog_publication_revision: 1, source: { sku_format_policy: "style-color-size-v1", source_name: "示例产品.xlsx", sheets: [{ name: "示例店", count: rows.length }], listing_rows: rows, selections: [], bindings: { 示例店: 7 } }, assessments: rows.map(row => ({ row_id: row.row_id, state: "no_official", message: "缺少官方来源，渠道暂待核", scope_id: 7, official_asins: [], official_parent_asins: [], official_fnskus: [], observations: [], duplicate_rows: [row.row_id], primary_row: row.row_id, can_map: true })), inventory: [{ sku_id: 14, style_id: 3, style_code: "0012", standard_color: "Olive", standard_size: "M", internal_display_sku: "0012-Olive-M", status: "enabled" }], mappings: [], stale: false, coverage: { message: "示例", members: [] } }; }
beforeEach(() => {
  data = result(); api.read.mockReset(); api.write.mockReset();
  const NativeRequest = globalThis.Request;
  vi.stubGlobal("Request", class extends NativeRequest { constructor(input: RequestInfo | URL, init?: RequestInit) { const { signal, ...options } = init || {}; super(input, options); if (signal) Object.defineProperty(this, "signal", { value: signal }); } });
  api.read.mockImplementation((path: string) => Promise.resolve(path.endsWith("/capabilities") ? { enabled: true, can_manage: true, scopes: [{ id: 7, seller_account_display_name: "示例账号", marketplace_scope_code: "amazon_us" }] } : path === "/api/catalog/production-sources" ? { items: [] } : data));
  api.write.mockImplementation((path: string) => Promise.resolve(path.endsWith("/compare") ? data : { import_id: 43 }));
});
afterEach(() => { cleanup(); vi.unstubAllGlobals(); });
function mount(entry = "/catalog/production-sources?entry=product-intake&listing=42") {
  const router = createMemoryRouter([{ path: "/catalog/production-sources", element: <CatalogListingSourcePage simplified/> }, { path: "/catalog/imports/:id", element: <p>原审核页面</p> }], { initialEntries: [entry] });
  render(<RouterProvider router={router} />); return router;
}

it("uses one simple default upload entry with the old manual path retained", async () => {
  mount("/catalog/production-sources");
  expect(await screen.findByLabelText("选择产品信息表")).toBeEnabled();
  expect(screen.getByRole("link", { name: "手工建档" })).toHaveAttribute("href", "/catalog/production-sources?entry=specification");
  expect(screen.queryByLabelText("资料内容（必填）")).not.toBeInTheDocument();
});

it("shows exact existing status and prefills missing variants and parent evidence without exposing platform values", async () => {
  mount(); await screen.findByRole("table", { name: "商品建档检查结果" });
  expect(screen.getByLabelText("选择 示例店 0012-Olive-M")).toBeChecked();
  expect(screen.getByLabelText("选择 示例店 1101-Navy-L")).toBeChecked();
  expect(screen.getByLabelText("选择 示例店 1101")).toBeChecked();
  expect(screen.queryByText(/B000000001/)).not.toBeInTheDocument();
  await userEvent.click(screen.getByRole("button", { name: "核对无误，保存候选" }));
  await screen.findByText("原审核页面");
  const body = api.write.mock.calls[0]![1]!.body as { selections: object[] };
  expect(body.selections).toEqual(expect.arrayContaining([expect.objectContaining({ row_id: "r2", style_code: "1101", color: "Navy", size: "L", include: true }), expect.objectContaining({ row_id: "r3", record_type: "parent", confirm_raw_parent: true })]));
  expect(api.write.mock.calls[0]![0]).toBe("/api/catalog/listing-sources/42/preview");
});

it("locates hard errors by sheet/cell/type and prevents saving the batch without editing source codes", async () => {
  const bad = { ...sourceRow("r4", "1203-khaki-L", "error", 179), format_issues: [{ sheet: "示例店", row: 179, cell: "B179", code: "SKU_COLOR_CASE", severity: "error" as const, original: "1203-khaki-L", message: "颜色首字母须大写" }] };
  data = result([existing, missing, bad]); mount();
  expect(await screen.findByText("1行有问题，请修改原表后重新上传")).toBeInTheDocument();
  expect(screen.getByText(/B179 · 颜色大小写/)).toBeInTheDocument();
  expect(screen.getByRole("button", { name: "核对无误，保存候选" })).toBeDisabled();
  expect(screen.getByLabelText("选择 示例店 1203-khaki-L")).toBeDisabled();
  await userEvent.click(screen.getByRole("button", { name: "定位问题行" }));
  expect(screen.getByRole("table", { name: "商品建档检查结果" })).toHaveTextContent("1203-khaki-L");
  expect(screen.getByRole("table", { name: "商品建档检查结果" })).not.toHaveTextContent("1101-Navy-L");
  expect(api.write).not.toHaveBeenCalled();
});

it("edits a review note on demand, retains it when reopened, and protects a real departure", async () => {
  const router = mount();
  const row = await screen.findByRole("row", { name: /1101-Navy-L/ });
  await userEvent.click(within(row).getByRole("button", { name: "查看 / 核对" }));
  await userEvent.type(screen.getByLabelText("人工核对备注"), "已逐项核对原表");
  await userEvent.click(screen.getByRole("button", { name: "保留本次核对" }));
  await userEvent.click(within(row).getByRole("button", { name: "查看 / 核对" }));
  expect(screen.getByLabelText("人工核对备注")).toHaveValue("已逐项核对原表");
  await userEvent.click(screen.getByRole("button", { name: "取消" }));
  await act(async () => { await router.navigate("/catalog/production-sources?entry=specification"); });
  expect(await screen.findByText("还有未保存的内容")).toBeInTheDocument();
  await userEvent.click(screen.getByRole("button", { name: "继续填写" }));
  expect(screen.getByRole("table", { name: "商品建档检查结果" })).toBeInTheDocument();
  expect(api.write).not.toHaveBeenCalled();
});

it("retries an uncertain candidate save with the original key and body", async () => {
  api.write.mockRejectedValueOnce(new TypeError("response lost")).mockResolvedValueOnce({ import_id: 43 });
  mount(); await userEvent.click(await screen.findByRole("button", { name: "核对无误，保存候选" }));
  await screen.findByText("请先核实原操作结果");
  expect(screen.getByLabelText("选择产品信息表")).toBeDisabled();
  await userEvent.click(screen.getByRole("button", { name: "查询或重发原操作" }));
  await screen.findByText("原审核页面");
  expect(api.write.mock.calls[0]![1]!.operationKey).toBe(api.write.mock.calls[1]![1]!.operationKey);
  expect(api.write.mock.calls[0]![1]!.body).toEqual(api.write.mock.calls[1]![1]!.body);
});


it("uploads through the strict route and automatically rechecks after explicit store selection", async () => {
  data = { ...result(), source: { ...result().source, bindings: {} } };
  api.write.mockImplementation((path, options) => {
    if (path.includes("/uploads?")) return Promise.resolve({ import_id: 42 });
    if (path.endsWith("/compare")) { data = { ...data, source: { ...data.source, bindings: options?.body as Record<string, number> } }; return Promise.resolve(data); }
    return Promise.resolve({ import_id: 43 });
  });
  const readMultiple=api.read.getMockImplementation()!;
  api.read.mockImplementation((path,options)=>path.endsWith('/capabilities')?Promise.resolve({enabled:true,can_manage:true,scopes:[{id:7,seller_account_display_name:'示例账号',marketplace_scope_code:'amazon_us'},{id:8,seller_account_display_name:'另一账号',marketplace_scope_code:'amazon_us'}]}):readMultiple(path,options));
  mount("/catalog/production-sources");
  await userEvent.upload(await screen.findByLabelText("选择产品信息表"), new File([new Uint8Array([0x50, 0x4b, 0x03, 0x04])], "同名产品.xlsx"));
  await screen.findByRole("table", { name: "商品建档检查结果" });
  expect(api.write.mock.calls[0]![0]).toBe("/api/catalog/listing-sources/uploads?sku_policy=style-color-size-v1");
  expect(screen.getByRole("button", { name: "核对无误，保存候选" })).toBeDisabled();
  await userEvent.selectOptions(screen.getByLabelText("示例店 对应店铺"), "7");
  await waitFor(() => expect(api.write.mock.calls.some(([path]) => path.endsWith("/compare"))).toBe(true));
  expect(screen.getByRole("button", { name: "核对无误，保存候选" })).toBeEnabled();
});

it("requires a fresh comparison after a known revision conflict", async () => {
  let attempts = 0;
  api.write.mockImplementation(path => {
    if (path.endsWith("/compare")) return Promise.resolve(data);
    if (++attempts === 1) return Promise.reject(new ApiRequestError(409, "listing_stale", "目录已更新，请重新核对。"));
    return Promise.resolve({ import_id: 43 });
  });
  mount(); await userEvent.click(await screen.findByRole("button", { name: "核对无误，保存候选" }));
  await screen.findByText("目录已更新，请重新核对。");
  expect(screen.getByRole("button", { name: "核对无误，保存候选" })).toBeDisabled();
  await userEvent.click(screen.getByRole("button", { name: "重新核对当前目录" }));
  await waitFor(() => expect(screen.getByRole("button", { name: "核对无误，保存候选" })).toBeEnabled());
});

it("keeps a suspected color unchanged and records explicit human confirmation", async () => {
  const warning = { ...sourceRow("r4", "2301-Bluw-XL", "needs_review", 418), format_issues: [{ sheet: "示例店", row: 418, cell: "B418", code: "SKU_COLOR_SPELLING_REVIEW", severity: "warning" as const, original: "2301-Bluw-XL", message: "颜色拼写疑似错误" }] };
  data = result([warning]); mount();
  const row = await screen.findByRole("row", { name: /2301-Bluw-XL/ });
  expect(screen.getByLabelText("选择 示例店 2301-Bluw-XL")).not.toBeChecked();
  await userEvent.click(within(row).getByRole("button", { name: "查看 / 核对" }));
  await userEvent.click(screen.getByLabelText("已核对原表和商品，确认此拼写无误，保留原SKU"));
  await userEvent.click(screen.getByRole("button", { name: "保留本次核对" }));
  await userEvent.click(screen.getByRole("button", { name: "核对无误，保存候选" }));
  await screen.findByText("原审核页面");
  const selections = api.write.mock.calls[0]![1]!.body!.selections as Record<string, unknown>[];
  expect(selections[0]).toMatchObject({ color: "Bluw", note: "已核对原表与商品，确认拼写无误，保留原SKU。", include: true });
});


it("keeps historical batches available through their old path and requires reupload for the new strict checks", async () => {
  data.source.sku_format_policy = undefined;
  mount();
  expect(await screen.findByText("这是历史清单，原记录继续保留")).toBeInTheDocument();
  expect(screen.getByRole("link", { name: "继续原核对流程" })).toHaveAttribute("href", "/catalog/production-sources?entry=amazon-listing&listing=42");
  expect(screen.getByRole("button", { name: "核对无误，保存候选" })).toBeDisabled();
  expect(api.write).not.toHaveBeenCalled();
});

it("clears the previous batch when returning to the unparameterized upload entry", async () => {
  const router = mount();
  await screen.findByRole("table", { name: "商品建档检查结果" });
  await act(async () => { await router.navigate("/catalog/production-sources"); });
  await screen.findByRole("heading", { name: "继续已有资料" });
  expect(screen.queryByRole("table", { name: "商品建档检查结果" })).not.toBeInTheDocument();
  expect(screen.getByLabelText("选择产品信息表")).toBeEnabled();
  expect(api.write).not.toHaveBeenCalled();
});

it("accepts one dropped file through the strict upload and blocks multi-file drops", async () => {
  mount("/catalog/production-sources");
  await waitFor(() => expect(screen.getByLabelText("选择产品信息表")).toBeEnabled());
  const zone = screen.getByRole("region", { name: "产品表上传区" });
  const file = new File([new Uint8Array([0x50, 0x4b, 0x03, 0x04])], "拖拽产品.xlsx");
  fireEvent.drop(zone, { dataTransfer: { files: [file, file] } });
  expect(screen.getByText(/每次请上传一个本地XLSX文件/)).toBeInTheDocument();
  expect(api.write).not.toHaveBeenCalled();
  fireEvent.dragEnter(zone, { dataTransfer: { types: ["Files"] } });
  expect(screen.getByText("松开以上传产品表")).toBeInTheDocument();
  fireEvent.drop(zone, { dataTransfer: { files: [file] } });
  await waitFor(() => expect(api.write).toHaveBeenCalledWith("/api/catalog/listing-sources/uploads?sku_policy=style-color-size-v1", expect.objectContaining({ rawBody: file })));
});

it.each(["csv", "empty", "disguised", "mime"])("rejects an invalid file without sending or locking an uncertain operation: %s", async kind => {
  const [file, expected] = ({
    csv: [new File(["text"], "不是表格.csv"), /不支持旧版/],
    empty: [new File([], "空.xlsx"), /文件为空/],
    disguised: [new File(["<script>alert(1)</script>"], "伪装.xlsx"), /不能只修改扩展名/],
    mime: [new File(["PK\x03\x04"], "网页.xlsx", { type: "text/html" }), /声明的类型与XLSX不符/],
  } satisfies Record<string, [File, RegExp]>)[kind as "csv" | "empty" | "disguised" | "mime"];
  mount("/catalog/production-sources");
  await waitFor(() => expect(screen.getByLabelText("选择产品信息表")).toBeEnabled());
  fireEvent.drop(screen.getByRole("region", { name: "产品表上传区" }), { dataTransfer: { files: [file] } });
  await screen.findByText(expected);
  expect(api.write).not.toHaveBeenCalled();
  await waitFor(() => expect(screen.getByRole("button", { name: "选择文件" })).toBeEnabled());
  expect(screen.queryByText("请先核实原操作结果")).not.toBeInTheDocument();
});

it("rejects oversized metadata before reading bytes and ignores drops during unsaved review", async () => {
  const file = new File(["tiny"], "超限.xlsx"); Object.defineProperty(file, "size", { value: 64 * 1024 * 1024 + 1 });
  const read = vi.spyOn(FileReader.prototype, "readAsArrayBuffer");
  const router = mount("/catalog/production-sources");
  await waitFor(() => expect(screen.getByLabelText("选择产品信息表")).toBeEnabled());
  fireEvent.drop(screen.getByRole("region", { name: "产品表上传区" }), { dataTransfer: { files: [file] } });
  await screen.findByText(/文件超过64MiB/);
  expect(read).not.toHaveBeenCalled(); read.mockRestore();
  await act(async () => { await router.navigate("/catalog/production-sources?listing=42"); });
  await userEvent.click(await screen.findByLabelText("选择 示例店 1101-Navy-L"));
  fireEvent.drop(screen.getByRole("region", { name: "产品表上传区" }), { dataTransfer: { files: [file] } });
  expect(screen.getByRole("button", { name: "选择文件" })).toBeDisabled();
  expect(api.write).not.toHaveBeenCalled();
});

it("keeps an uncertain file upload locked and retries the same file and operation key", async () => {
  api.write.mockRejectedValueOnce(new TypeError("response lost")).mockResolvedValueOnce({ import_id: 42 });
  mount("/catalog/production-sources");
  const file = new File(["PK\x03\x04"], "原上传.xlsx");
  await waitFor(() => expect(screen.getByLabelText("选择产品信息表")).toBeEnabled());
  fireEvent.drop(screen.getByRole("region", { name: "产品表上传区" }), { dataTransfer: { files: [file] } });
  await screen.findByText("请先核实原操作结果");
  expect(screen.getByRole("button", { name: "选择文件" })).toBeDisabled();
  fireEvent.drop(screen.getByRole("region", { name: "产品表上传区" }), { dataTransfer: { files: [new File(["bad"], "新上传.xlsx")] } });
  expect(api.write).toHaveBeenCalledTimes(1);
  await userEvent.click(screen.getByRole("button", { name: "查询或重发原操作" }));
  await screen.findByRole("table", { name: "商品建档检查结果" });
  expect(api.write.mock.calls[0]![1]!.operationKey).toBe(api.write.mock.calls[1]![1]!.operationKey);
  expect(api.write.mock.calls[0]![1]!.rawBody).toBe(api.write.mock.calls[1]![1]!.rawBody);
});

it("reloads an identical source returned by duplicate upload without losing its result table", async () => {
  api.write.mockResolvedValue({ import_id: 42, duplicate: true });
  mount(); await screen.findByRole("table", { name: "商品建档检查结果" });
  const file = new File(["PK\x03\x04"], "同一份.xlsx");
  fireEvent.drop(screen.getByRole("region", { name: "产品表上传区" }), { dataTransfer: { files: [file] } });
  await waitFor(() => expect(api.write).toHaveBeenCalledTimes(1));
  await waitFor(() => expect(api.read.mock.calls.filter(([path]) => path.startsWith("/api/catalog/listing-sources/42?")).length).toBe(2));
  expect(await screen.findByRole("table", { name: "商品建档检查结果" })).toHaveTextContent("1101-Navy-L");
});


it("reports unretained inline note edits to the outer workflow and opens a focused review screen", async () => {
  const guard=vi.fn();
  const router=createMemoryRouter([{path:'*',element:<CatalogListingSourcePage simplified onReview={vi.fn()} onGuardChange={guard}/>}],{initialEntries:['/catalog/maintenance?listing=42']});
  render(<RouterProvider router={router}/>);
  const row=await screen.findByRole('row',{name:/1101-Navy-L/});
  await userEvent.click(within(row).getByRole('button',{name:'查看 / 核对'}));
  expect(screen.queryByRole('table',{name:'商品建档检查结果'})).not.toBeInTheDocument();
  const note=screen.getByLabelText('人工核对备注');expect(note).toHaveFocus();
  await userEvent.type(note,'尚未保留的核对说明');
  await waitFor(()=>expect(guard).toHaveBeenLastCalledWith({dirty:true,busy:false,unknown:false}));
  await userEvent.click(screen.getByRole('button',{name:/^取消$/}));
  expect(screen.getByText('放弃本行未保留的修改？')).toBeVisible();
  await userEvent.click(screen.getByRole('button',{name:/^继续核对$/}));
  expect(note).toHaveValue('尚未保留的核对说明');
  await userEvent.click(screen.getByRole('button',{name:'保留本次核对'}));
  expect(screen.getByRole('table',{name:'商品建档检查结果'})).toBeVisible();
  expect(within(screen.getByRole('row',{name:/1101-Navy-L/})).getByRole('button',{name:'查看 / 核对'})).toHaveFocus();
  expect(api.write).not.toHaveBeenCalled();
});

it("distinguishes same-name existing source batches", async()=>{
  const original=api.read.getMockImplementation()!;
  api.read.mockImplementation((path,options)=>path==='/api/catalog/production-sources'?Promise.resolve({items:[{import_id:42,source_schema:'amazon_listing_v1',source_name:'同名表.xlsx'},{import_id:41,source_schema:'amazon_listing_v1',source_name:'同名表.xlsx'}]}):original(path,options));
  mount('/catalog/production-sources');
  expect(await screen.findByRole('link',{name:/同名表.xlsx.*42/})).toBeVisible();
  expect(screen.getByRole('link',{name:/同名表.xlsx.*41/})).toBeVisible();
});


it('shows the sole already-bound store and keeps its stable scope in the candidate',async()=>{
 mount();await screen.findByRole('table',{name:'商品建档检查结果'});
 expect(screen.getByRole('combobox',{name:'示例店 对应店铺'})).toHaveValue('7');
 await userEvent.click(screen.getByRole('button',{name:'核对无误，保存候选'}));await screen.findByText('原审核页面');
 expect(api.write.mock.calls[0]?.[1]?.body?.bindings).toEqual({示例店:7});
});
it('requires an explicit binding even for a single available store',async()=>{
 data.source.bindings={};const checked={...data,source:{...data.source,bindings:{示例店:7}}};
 api.write.mockImplementation(path=>Promise.resolve(path.endsWith('/compare')?checked:{import_id:43}));
 mount();
 await screen.findByRole('table',{name:'本次导入店铺'});
 expect(api.write).not.toHaveBeenCalled();
 expect(screen.getByRole('button',{name:'核对无误，保存候选'})).toBeDisabled();
 await userEvent.selectOptions(screen.getByRole('combobox',{name:'示例店 对应店铺'}),'7');
 await waitFor(()=>expect(api.write).toHaveBeenCalledWith('/api/catalog/listing-sources/42/compare',expect.objectContaining({body:{示例店:7}})));
 await waitFor(()=>expect(screen.getByRole('button',{name:'核对无误，保存候选'})).toBeEnabled());
 expect(screen.getByRole('combobox',{name:'示例店 对应店铺'})).toHaveValue('7');
});
it('requires an explicit shop choice for each imported sheet and leaves other sheets out', async () => {
  const first = sourceRow('shop-a', '0012-Olive-M', 'missing', 4);
  const second = { ...sourceRow('shop-b', '0013-Navy-L', 'missing', 4), sheet: '另一店' };
  data = result([first, second]);
  data.source.sheets = [{ name: '示例店', count: 1 }, { name: '另一店', count: 1 }];
  data.source.bindings = {};
  api.write.mockImplementation((path, options) => {
    if (path.endsWith('/compare')) {
      data = { ...data, source: { ...data.source, bindings: options?.body as Record<string, number> } };
      return Promise.resolve(data);
    }
    return Promise.resolve({ import_id: 43 });
  });
  mount();
  await screen.findByRole('table', { name: '商品建档检查结果' });
  expect(api.write).not.toHaveBeenCalled();
  expect(screen.getByRole('combobox', { name: '示例店 对应店铺' })).toHaveValue('');
  expect(screen.getByRole('combobox', { name: '另一店 对应店铺' })).toHaveValue('');
  expect(screen.getByLabelText('选择 另一店 0013-Navy-L')).not.toBeChecked();
  const user = userEvent.setup();
  await user.selectOptions(screen.getByRole('combobox', { name: '示例店 对应店铺' }), '7');
  await waitFor(() => expect(screen.getByRole('button', { name: '核对无误，保存候选' })).toBeEnabled());
  expect(screen.getByLabelText('选择 另一店 0013-Navy-L')).toBeDisabled();
  await user.click(screen.getByRole('button', { name: '核对无误，保存候选' }));
  await screen.findByText('原审核页面');
  const body = api.write.mock.calls.find(([path]) => path.endsWith('/preview'))?.[1]?.body as unknown as { bindings: object; selections: { row_id: string; include: boolean }[] };
  expect(body.bindings).toEqual({ 示例店: 7 });
  expect(body.selections.filter(row => row.include).map(row => row.row_id)).toEqual(['shop-a']);
});
it('retains a mismatched source binding for explicit correction instead of replacing it',async()=>{
 data.source.bindings={示例店:99};mount();await screen.findByRole('table',{name:'商品建档检查结果'});
 expect(screen.getByRole('combobox',{name:'示例店 对应店铺'})).toBeVisible();
 expect(screen.getByText('原资料的店铺归属与当前设置不一致，请核对后再继续。')).toBeVisible();
 expect(screen.getByRole('button',{name:'核对无误，保存候选'})).toBeDisabled();expect(api.write).not.toHaveBeenCalled();
});

it('preserves a failed explicit scope check for explicit retry without saving a candidate',async()=>{
 data.source.bindings={};const checked={...data,source:{...data.source,bindings:{示例店:7}}};
 api.write.mockRejectedValueOnce(new ApiRequestError(503,'unavailable','本次核对未完成')).mockResolvedValueOnce(checked);
 mount();await screen.findByRole('table',{name:'本次导入店铺'});
 await userEvent.selectOptions(screen.getByRole('combobox',{name:'示例店 对应店铺'}),'7');
 await screen.findByText('本次核对未完成');
 expect(screen.getByRole('button',{name:'核对无误，保存候选'})).toBeDisabled();
 await userEvent.click(screen.getByRole('button',{name:'重新核对当前目录'}));
 await waitFor(()=>expect(screen.getByRole('button',{name:'核对无误，保存候选'})).toBeEnabled());
 expect(api.write.mock.calls).toHaveLength(2);expect(api.write.mock.calls.every(([path])=>path.endsWith('/compare'))).toBe(true);
});


it("does not select an existing approved shop mapping for another confirmation", async () => {
  data = result([existing]);
  data.mappings = [{ report_source_scope_id: 7, seller_sku: existing.seller_sku, sku_id: 14 }];
  mount();
  expect(await screen.findByLabelText("选择 示例店 0012-Olive-M")).not.toBeChecked();
  expect(screen.getByText("已关联本店商品")).toBeVisible();
});


it("shows the canonical standard size beside the unchanged source SKU", async () => {
  const row = sourceRow("size-alias", "1115-Navy-XXXL", "missing", 4);
  row.suggestion = {style_code:"1115",color:"Navy",size:"3XL"};
  data = result([row]);
  mount();
  const table = await screen.findByRole("table",{name:"商品建档检查结果"});
  const record = within(table).getByRole("row",{name:/1115-Navy-XXXL/});
  expect(within(record).getByRole("cell",{name:"3XL"})).toBeVisible();
  expect(within(record).getByText("1115-Navy-XXXL")).toBeVisible();
});


it("routes prior candidates to review and original files to source checks",async()=>{
  const original=api.read.getMockImplementation()!;
  api.read.mockImplementation((path,options)=>path==='/api/catalog/production-sources'?Promise.resolve({items:[
    {import_id:43,source_schema:'amazon_listing_v1',source_name:'已批准.xlsx',review_path:'/catalog/imports/43'},
    {import_id:42,source_schema:'amazon_listing_v1',source_name:'原始表.xlsx',review_path:'/catalog/production-sources?entry=amazon-listing&listing=42'}
  ]}):original(path,options));
  const review=vi.fn();const source=vi.fn();
  render(<RouterProvider router={createMemoryRouter([{path:'*',element:<CatalogListingSourcePage simplified onReview={review} onListingSelected={source}/>}],{initialEntries:['/catalog/production-sources']})}/>);
  await userEvent.click(await screen.findByRole('button',{name:'已批准.xlsx · 批次 #43'}));
  expect(review).toHaveBeenCalledWith(43);
  expect(api.read.mock.calls.some(([path])=>path.includes('/listing-sources/43'))).toBe(false);
  await userEvent.click(screen.getByRole('button',{name:'原始表.xlsx · 批次 #42'}));
  await screen.findByRole('table',{name:'商品建档检查结果'});expect(source).toHaveBeenCalledWith(42);
});
