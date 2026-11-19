import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { createMemoryRouter, RouterProvider } from "react-router-dom";
import type { ReactNode } from "react";
function TestRouter({children}:{children:ReactNode}){const router=createMemoryRouter([{path:"*",element:children}],{initialEntries:["/catalog/unmatched"]});return <RouterProvider router={router}/>;}
import { afterEach, expect, it, vi } from "vitest";
import { setSessionCsrfToken } from "../../api/client";
import { AuthzGenerationProvider } from "../../app/AuthzGenerationContext";
import { CatalogSourceSelection } from "./CatalogSourceSelection";
import type { CatalogUnmatchedItem } from "./catalogApi";

vi.mock('./CatalogImportPage',()=>({CatalogImportPage:({embeddedId,onCompleted}:{embeddedId:number;onCompleted:()=>void})=><><p>审核候选{embeddedId}</p><button onClick={onCompleted}>测试批准</button></>}));
const item = { source_identity: { seller_sku_match: `match_${"a".repeat(64)}`, report_source_scope_id: 3 }, published_version_ids: ["17"] } as CatalogUnmatchedItem;
const context = { source: "QA-SOURCE-M", scope_id: 3, catalog_publication_revision: 5, mapped_sku_id: null, excluded: false, skus: [{ sku_id: 14, style_id: 13, style_code: "QA", internal_display_sku: "QA-ORIGINAL-M", standard_color: "Olive", standard_size: "M" }], candidates: [], evidence: { scopes: [{ seller_account_display_name: "QA店", marketplace_scope_code: "amazon_us" }], observations: [{ report_type: "business_report", report_date: "2026-10-12", source_row_id: 8, version_id: 17 }] } };
afterEach(() => { vi.unstubAllGlobals(); setSessionCsrfToken(undefined); });

it("previews only the chosen source and recovers an uncertain save with the same command", async () => {
  setSessionCsrfToken("qa-session-token");
  const commands: RequestInit[] = [];
  vi.stubGlobal("fetch", vi.fn((input: string, init: RequestInit) => {
    if (input.endsWith("selection-context")) return Promise.resolve(new Response(JSON.stringify(context)));
    if (input.endsWith("selection-preview")) {
      expect(JSON.parse(init.body as string)).toMatchObject({ source_key: item.source_identity.seller_sku_match, scope_id: 3, version_ids: [17], selected_sku_id: 14 });
      return Promise.resolve(new Response(JSON.stringify({ preview_digest: "b".repeat(64), source: context.source, created_style_count: 0, created_sku_count: 0, mapping_count: 1, excluded_count: 0, kept_sku_count: 12 })));
    }
    commands.push(init);
    return commands.length === 1 ? Promise.reject(new TypeError("network interrupted")) : Promise.resolve(new Response(JSON.stringify({ import_id: 87 })));
  }));
  const user = userEvent.setup(); const close = vi.fn();
  render(<TestRouter><AuthzGenerationProvider boundary={{ principalId: 1, roles: ["admin"], siteConfigVersionId: 1, siteId: 1 }} onRevoked={() => undefined}><CatalogSourceSelection item={item} onClose={close} /></AuthzGenerationProvider></TestRouter>);
  const select = await screen.findByRole("combobox", { name: "实际商品规格（必选）" });
  expect(select).toHaveValue("");
  await user.selectOptions(select, "14");
  await user.click(screen.getByRole("checkbox",{name:"已核对以上商品信息与处理方式"}));
  await user.click(screen.getByRole("button", { name: "生成候选并审核" }));
  await user.click(await screen.findByRole("button", { name: "查询本次保存结果" }));
  expect(commands).toHaveLength(2);
  expect(commands[0]!.body).toBe(commands[1]!.body);
  expect(new Headers(commands[0]!.headers).get("Idempotency-Key")).toBe(new Headers(commands[1]!.headers).get("Idempotency-Key"));
  await screen.findByText("审核候选87");expect(screen.getAllByRole("dialog")).toHaveLength(1);expect(close).not.toHaveBeenCalled();await user.click(screen.getByRole("button",{name:"测试批准"}));await user.click(screen.getByRole("button",{name:"完成并返回清单"}));expect(close).toHaveBeenCalled();
});

it("offers the existing candidate rather than silently creating another", async () => {
  setSessionCsrfToken("qa-session-token");
  vi.stubGlobal("fetch", vi.fn(() => Promise.resolve(new Response(JSON.stringify({ ...context, candidates: [{ import_id: 88, workflow_revision: 2, status: "validated", review_path: "/catalog/imports/88", source_name: "原候选" }] })))));
  render(<TestRouter><AuthzGenerationProvider boundary={{ principalId: 1, roles: ["admin"], siteConfigVersionId: 1, siteId: 1 }} onRevoked={() => undefined}><CatalogSourceSelection item={item} onClose={vi.fn()} /></AuthzGenerationProvider></TestRouter>);
  expect(await screen.findByRole("button", { name: /继续审核 · 批次88/ })).toBeEnabled();
  expect(screen.getByRole("button", { name: "生成候选并审核" })).toBeDisabled();
  expect(screen.getByText(/已有候选，请从上方继续审核/)).toBeVisible();
});

it('prefills a strict source suggestion but requires human confirmation before generating anything',async()=>{
 setSessionCsrfToken('qa-session-token');const fetcher=vi.fn(()=>Promise.resolve(new Response(JSON.stringify({...context,source:'3104-White-S',skus:[]}))));vi.stubGlobal('fetch',fetcher);
 render(<TestRouter><AuthzGenerationProvider boundary={{principalId:1,roles:['admin'],siteConfigVersionId:1,siteId:1}} onRevoked={()=>undefined}><CatalogSourceSelection item={item} onClose={vi.fn()}/></AuthzGenerationProvider></TestRouter>);
 expect(await screen.findByLabelText('款号（必填）')).toHaveValue('3104');expect(screen.getByLabelText('颜色（必填）')).toHaveValue('White');expect(screen.getByLabelText('尺码（必填）')).toHaveValue('S');expect(screen.getByRole('button',{name:'生成候选并审核'})).toBeDisabled();expect(fetcher).toHaveBeenCalledTimes(1);
});

it('protects the human confirmation draft when closing the source workflow',async()=>{
 setSessionCsrfToken('qa-session-token');vi.stubGlobal('fetch',vi.fn(()=>Promise.resolve(new Response(JSON.stringify({...context,source:'3104-White-S',skus:[]})))));
 const close=vi.fn();render(<TestRouter><AuthzGenerationProvider boundary={{principalId:1,roles:['admin'],siteConfigVersionId:1,siteId:1}} onRevoked={()=>undefined}><CatalogSourceSelection item={item} onClose={close}/></AuthzGenerationProvider></TestRouter>);
 await screen.findByLabelText('款号（必填）');await userEvent.click(screen.getByRole('checkbox',{name:'已核对以上商品信息与处理方式'}));await userEvent.click(screen.getByRole('button',{name:'关闭对话框'}));
 expect(screen.getByRole('dialog',{name:'还有未保存的内容'})).toBeVisible();expect(close).not.toHaveBeenCalled();await userEvent.click(screen.getByRole('button',{name:'继续处理'}));expect(screen.getByLabelText('款号（必填）')).toHaveValue('3104');
});
