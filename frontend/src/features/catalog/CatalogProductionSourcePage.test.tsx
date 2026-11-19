import { beforeEach, describe, expect, it, vi } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter, Route, Routes, useLocation } from "react-router-dom";
import { ApiRequestError, requestApi } from "../../api/client";
import { CatalogProductionSourcePage, CatalogSpecificationSourcePage } from "./CatalogProductionSourcePage";

vi.mock("../../api/client", async () => { const mock = vi.fn<(path: string, options?: unknown) => Promise<unknown>>(); return { ...await vi.importActual("../../api/client"), requestApi: mock, writeApi: (path: string, options: object) => mock(path, { ...options, method: "POST" }), commandApi: (path: string, body: object, key: string) => mock(path, { body, method: "POST", headers: { "Idempotency-Key": key } }) }; });
const auth = vi.hoisted(() => ({ registerSensitivePurge: () => () => undefined }));
vi.mock("../../app/AuthzGenerationContext", () => ({ useAuthzGeneration: () => ({ generation: 1, registerSensitivePurge: auth.registerSensitivePurge }) }));
const parsed = { source_name: "QA factory", rows: [{ style_code: "QA-01", color: "Olive", size: "M", formal_sku: "00-AbC-M" }] };
const preview = { catalog_publication_revision: 0, counts: { REVIEW_NEW_PRODUCT: 1 }, blocking_fields: 2, observations: [{ source_row: 1, ...parsed.rows[0], action: "REVIEW_NEW_PRODUCT" }] };
const request = vi.mocked(requestApi);
let create: (options: unknown) => unknown;

beforeEach(() => {
  request.mockReset(); create = () => ({ import_id: 7 });
  request.mockImplementation(async (url, options) => {
    if (url.endsWith("/capabilities")) return { enabled: true, can_manage: true } as never;
    if (url.endsWith("/parse")) return parsed as never;
    if (url.endsWith("/preview")) return preview as never;
    if (options?.method === "POST") return await create(options) as never;
    return { items: [] } as never;
  });
});
function mount() { render(<MemoryRouter initialEntries={["/catalog/production-sources?entry=specification"]}><Routes><Route path="/catalog/production-sources" element={<CatalogProductionSourcePage />} /><Route path="/catalog/imports/:id" element={<p>QA existing review</p>} /></Routes></MemoryRouter>); }
async function prepare() {
  const user = userEvent.setup();
  await user.click(await screen.findByRole("button",{name:"分列填写或导入"}));
  await user.type(await screen.findByLabelText("资料名称（必填）"), "QA factory");
  await user.clear(screen.getByLabelText("资料内容（必填）"));
  await user.type(screen.getByLabelText("资料内容（必填）"), "款号\t颜色\t尺码\nQA-01\tOlive\tM");
  await user.click(screen.getByRole("button", { name: "预览商品候选" }));
  await screen.findByRole("region", { name: "候选范围预览" });
  return user;
}
describe("production source entry", () => {
  it("shows formatting before and after while submitting original source evidence", async () => {
    const raw = { ...parsed, rows: [{ ...parsed.rows[0], color: " OLIVE " }] };
    const original = request.getMockImplementation()!;
    request.mockImplementation(async (url, options) => {
      if (url.endsWith("/parse")) return raw as never;
      if (url.endsWith("/preview")) return { ...preview, format_adjustments: [{ source_row: 1, location: "工作表规格，第2行", field: "color", before: " OLIVE ", after: "Olive", reason: "格式整理" }] } as never;
      return original(url, options);
    });
    let saved: unknown;
    create = options => { saved = options; return { import_id: 7 }; };
    mount();
    const user = await prepare();
    expect(screen.getByRole("table", { name: "格式整理对照" })).toHaveTextContent('" OLIVE "');
    expect(screen.getByRole("table", { name: "格式整理对照" })).toHaveTextContent('"Olive"');
    await user.click(screen.getByRole("button", { name: "保存候选并进入审核" }));
    await screen.findByText("QA existing review");
    expect((saved as { body: { source: typeof raw } }).body.source.rows[0]?.color).toBe(" OLIVE ");
  });
  it("checks selected files immediately and lets a corrected same-name file recover", async () => {
    const user = userEvent.setup();
    let attempts = 0;
    const original = request.getMockImplementation()!;
    request.mockImplementation(async (url, options) => {
      if (url.endsWith("/parse")) {
        if (++attempts === 1) throw new ApiRequestError(422, "production_source_invalid", "表格检查未通过\n工作表规格，第2行B列（颜色）：请使用Olive。");
        return { ...parsed, preview } as never;
      }
      return original(url, options);
    });
    mount();
    await user.click(await screen.findByRole("button",{name:"分列填写或导入"}));
    const input = await screen.findByLabelText("选择规格表（选填）");
    const badFile = new File(["bad"], "QA.csv", { type: "text/csv" });
    Object.defineProperty(badFile, "text", { value: () => Promise.resolve("bad") });
    await user.upload(input, badFile);
    await screen.findByText(/第2行B列/);
    expect(screen.queryByRole("button", { name: "保存候选并进入审核" })).not.toBeInTheDocument();
    const goodFile = new File(["corrected"], "QA.csv", { type: "text/csv" });
    Object.defineProperty(goodFile, "text", { value: () => Promise.resolve("corrected") });
    await user.upload(input, goodFile);
    await screen.findByRole("region", { name: "候选范围预览" });
    expect(screen.queryByText(/第2行B列/)).not.toBeInTheDocument();
    expect(request.mock.calls.filter(([url]) => url.endsWith("/preview"))).toHaveLength(0);
    expect(attempts).toBe(2);
  });
  it("replaces network exception text with Chinese and keeps entered data", async () => {
    const user = userEvent.setup();
    const original = request.getMockImplementation()!;
    request.mockImplementation(async (url, options) => {
      if (url.endsWith("/parse")) throw new TypeError("Failed to fetch");
      return original(url, options);
    });
    mount();
    await user.click(await screen.findByRole("button",{name:"分列填写或导入"}));
    await user.type(await screen.findByLabelText("资料名称（必填）"), "QA");
    await user.click(screen.getByRole("button", { name: "预览商品候选" }));
    await screen.findByText(/表格检查未完成/);
    expect(screen.queryByText(/Failed to fetch/)).not.toBeInTheDocument();
    expect(screen.getByLabelText("资料名称（必填）")).toHaveValue("QA");
  });
  it("keeps the source preview separate from saving an existing review", async () => {
    mount(); const user = await prepare();
    expect(screen.getByText("新产品待核")).toBeInTheDocument();
    expect(screen.getByRole("columnheader", { name: "本表正式SKU" })).toBeInTheDocument();
    expect(screen.getByRole("cell", { name: "00-AbC-M" })).toBeInTheDocument();
    expect(request.mock.calls.filter(([, options]) => options?.method === "POST")).toHaveLength(2);
    await user.click(screen.getByRole("button", { name: "保存候选并进入审核" }));
    await screen.findByText("QA existing review");
  });
  it("locks uncertain results and reuses the exact command on retry", async () => {
    const attempts: unknown[] = [];
    create = options => { attempts.push(options); if (attempts.length === 1) throw new TypeError("network interrupted"); return { import_id: 7 }; };
    mount(); const user = await prepare();
    await user.click(screen.getByRole("button", { name: "保存候选并进入审核" }));
    await screen.findByText("保存结果尚不确定");
    expect(screen.getByLabelText("资料内容（必填）")).toBeDisabled();
    await user.click(screen.getByRole("button", { name: "查询或重发原保存" }));
    await screen.findByText("QA existing review");
    expect(attempts[1]).toEqual(attempts[0]);
  });
  it("requires a fresh preview after a known publication conflict", async () => {
    create = () => { throw new ApiRequestError(409, "catalog_publication_revision_conflict", "QA catalog changed"); };
    mount(); const user = await prepare();
    await user.click(screen.getByRole("button", { name: "保存候选并进入审核" }));
    await waitFor(() => expect(screen.queryByRole("region", { name: "候选范围预览" })).not.toBeInTheDocument());
    expect(screen.getByLabelText("资料内容（必填）")).toHaveValue("款号\t颜色\t尺码\nQA-01\tOlive\tM");
    expect(screen.getByLabelText("资料内容（必填）")).toBeEnabled();
  });
  it("does not offer writes when the environment has not enabled this source", async () => {
    request.mockResolvedValue({ enabled: false, can_manage: true } as never);
    mount(); await screen.findByText("当前环境尚未启用商品建档");
    expect(screen.queryByRole("button", { name: "预览商品候选" })).not.toBeInTheDocument();
  });
});

function UnifiedLocation(){const location=useLocation();return <output data-testid="unified-location">{location.pathname+location.search}</output>;}
it.each(['','?entry=product-intake&listing=8&history_page=2'])('keeps old intake URLs as contextual aliases without opening a dialog: %s',async query=>{
 render(<MemoryRouter initialEntries={['/catalog/production-sources'+query]}><Routes><Route path="/catalog/production-sources" element={<CatalogProductionSourcePage/>}/><Route path="/catalog/maintenance" element={<UnifiedLocation/>}/></Routes></MemoryRouter>);
 expect(await screen.findByTestId('unified-location')).toHaveTextContent('/catalog/maintenance'+query);expect(screen.queryByRole('dialog')).not.toBeInTheDocument();
});


it('embeds manual entry with an unsaved guard and returns its candidate without navigation',async()=>{
 const guard=vi.fn();const review=vi.fn();
 render(<MemoryRouter><CatalogSpecificationSourcePage embedded onGuardChange={guard} onReview={review}/></MemoryRouter>);
 const user=await prepare();
 expect(guard).toHaveBeenLastCalledWith({dirty:true,busy:false,unknown:false});
 await user.click(screen.getByRole('button',{name:'保存候选并进入审核'}));
 await waitFor(()=>expect(review).toHaveBeenCalledWith(7));
 expect(screen.queryByRole('link',{name:'导入亚马逊商品清单（Seller SKU／ASIN／FNSKU）'})).not.toBeInTheDocument();
});

it('uses an optional channel checkbox for a sole store and still requires channel evidence',async()=>{
 const original=request.getMockImplementation()!;
 request.mockImplementation(async(path,options)=>path.endsWith('/capabilities')?{enabled:true,can_manage:true,scopes:[{id:7,seller_account_display_name:'广州店',marketplace_scope_code:'amazon_us'}]} as never:original(path,options));
 mount();await screen.findByRole('checkbox',{name:'关联平台商品资料（选填）'});
 expect(screen.queryByRole('combobox',{name:'渠道账号/站点（选填）'})).not.toBeInTheDocument();
 expect(screen.queryByText('广州店')).not.toBeInTheDocument();expect(screen.queryByLabelText('渠道关联依据（必填）')).not.toBeInTheDocument();
 await userEvent.click(screen.getByRole('checkbox',{name:'关联平台商品资料（选填）'}));
 expect(screen.getByLabelText('渠道关联依据（必填）')).toBeVisible();
 expect(screen.getByRole('button',{name:'检查并进入审核'})).toBeDisabled();
 expect(request.mock.calls.filter(([,opts])=>opts?.method==='POST')).toHaveLength(0);
});

it('prepares a simple SKU list and enters the original review without redundant metadata input',async()=>{
 let saved:unknown;create=options=>{saved=options;return {import_id:7};};const original=request.getMockImplementation()!;
 request.mockImplementation(async(path,options)=>path.endsWith('/parse')?{source_name:'自动资料',rows:[{style_code:'1101',color:'Navy',size:'L',formal_sku:'1101-Navy-L'}]} as never:original(path,options));
 mount();await userEvent.type(await screen.findByLabelText('SKU清单（每行一个）'),'1101-Navy-L');await userEvent.click(screen.getByRole('button',{name:'检查并进入审核'}));await screen.findByText('QA existing review');
 expect((saved as {body:{source:{rows:unknown[]}}}).body.source.rows[0]).toMatchObject({style_code:'1101',color:'Navy',size:'L',formal_sku:'1101-Navy-L'});
});
it('locates an invalid SKU line before sending its content',async()=>{
 mount();await userEvent.type(await screen.findByLabelText('SKU清单（每行一个）'),'1101-navy-L');await userEvent.click(screen.getByRole('button',{name:'检查并进入审核'}));await screen.findByText(/第1行：SKU须按/);expect(request.mock.calls.filter(([,opts])=>opts?.method==='POST')).toHaveLength(0);
});

it('keeps a disabled or uncertain existing identity for human review before candidate creation',async()=>{
 const original=request.getMockImplementation()!;request.mockImplementation(async(path,options)=>path.endsWith('/preview')?{...preview,observations:[{...preview.observations[0],sku_id:'14',action:'REVIEW_DISABLED'}]} as never:original(path,options));
 mount();await userEvent.type(await screen.findByLabelText('SKU清单（每行一个）'),'1101-Navy-L');await userEvent.click(screen.getByRole('button',{name:'检查并进入审核'}));await screen.findByText('有规格需要核对已有商品，请在下方预览中确认后继续。');expect(request.mock.calls.some(([path,options])=>path==='/api/catalog/production-sources'&&options?.method==='POST')).toBe(false);
});

it('reuses the confirmed sole shop for explicit Seller SKU manual registration',async()=>{
 const original=request.getMockImplementation()!;
 request.mockImplementation(async(path,options)=>path.endsWith('/capabilities')?{enabled:true,can_manage:true,scopes:[{id:7,seller_account_display_name:'广州店',marketplace_scope_code:'amazon_us'}]} as never:original(path,options));
 const review=vi.fn();render(<MemoryRouter><CatalogSpecificationSourcePage embedded onReview={review}/></MemoryRouter>);
 await userEvent.type(await screen.findByLabelText('Seller SKU清单（每行一个）'),'1101-Navy-L');await userEvent.click(screen.getByRole('button',{name:'检查并进入审核'}));await waitFor(()=>expect(review).toHaveBeenCalledWith(7));
 const body=request.mock.calls.find(([path,options])=>path==='/api/catalog/production-sources'&&options?.method==='POST')?.[1]?.body as unknown as {source:{report_source_scope_id:number;channel_evidence:string}};
 expect(body.source.report_source_scope_id).toBe(7);expect(body.source.channel_evidence).toContain('Seller SKU');
});
