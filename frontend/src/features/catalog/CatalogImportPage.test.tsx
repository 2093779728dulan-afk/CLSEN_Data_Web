import userEvent from "@testing-library/user-event";
import {useState} from "react";
import {setSessionCsrfToken} from "../../api/client";
import type {CatalogDraftSaveAction} from "./catalogTypes";
import { act, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { afterEach, expect, it, vi } from "vitest";

import { CatalogImportPage } from "./CatalogImportPage";

afterEach(() => { vi.unstubAllGlobals(); setSessionCsrfToken(undefined); });
it("waits for same-revision rows before enabling workflow commands", async () => {
  setSessionCsrfToken("test-csrf");
  const commands: string[] = [];
  let checked = false;
  const pending: Array<(response: Response) => void> = [];
  vi.stubGlobal("fetch", vi.fn((input: RequestInfo | URL) => {
    const url = typeof input === "string" ? input : input instanceof URL ? input.href : input.url;
    if (url.endsWith("/validate")) { commands.push("validate"); checked = true; return Promise.resolve(new Response(JSON.stringify({ safe_result: { workflow_revision: 2 } }))); }
    if (url.includes("/rows/")) return checked ? Promise.resolve(new Response(JSON.stringify({ rows: [], total_rows: 0 }))) : new Promise<Response>(resolve => pending.push(resolve));
    return Promise.resolve(new Response(JSON.stringify({ import_id: 2, status: "needs_attention", workflow_revision: checked ? 2 : 1, validation_run_id: checked ? 1 : null, permissions: { can_validate: true }, source_kind: "online" }), { status: 200 }));
  }));
  render(<MemoryRouter initialEntries={["/catalog/imports/2"]}><Routes><Route path="/catalog/imports/:import_id" element={<CatalogImportPage />} /></Routes></MemoryRouter>);
  await waitFor(() => expect(pending).toHaveLength(5));
  expect(screen.getByRole("heading", { name: "商品主档审核" })).toBeVisible();
  expect(screen.getByRole("progressbar", { name: "审核明细加载进度" })).toHaveAttribute("value", "0");
  expect(screen.queryByText("待处理 0 项")).not.toBeInTheDocument();
  expect(screen.queryByRole("button", { name: "重新校验" })).not.toBeInTheDocument();
  expect(commands).toEqual([]);
  await act(async () => { pending.forEach(resolve => resolve(new Response(JSON.stringify({ rows: [], total_rows: 0 }), { status: 200 }))); await Promise.resolve(); });
  await waitFor(() => expect(commands).toEqual(["validate"]));
  expect(screen.queryByRole("button", { name: "重新校验" })).not.toBeInTheDocument();
  setSessionCsrfToken(undefined);
});
it("renders five review sections from the server revision", async () => {
  vi.stubGlobal("fetch", vi.fn((input: RequestInfo | URL) => {
    const raw = typeof input === "string" ? input : input instanceof URL ? input.href : input.url;
    const path = new URL(raw, "http://local").pathname;
    if (path.includes("/rows/")) return Promise.resolve(new Response(JSON.stringify({ rows: [] }), { status: 200 }));
    return Promise.resolve(new Response(JSON.stringify({ catalog_publication_revision: 0, base_catalog_version_id: null, export_id: 1, failure_reason_code: null, has_original_file: false, import_id: 2, parse_attempt_revision: 0, permissions: { can_approve_high_risk: false, can_approve_normal: false, can_download_original: false, can_edit: true, can_preview: false, can_rebase: false, can_reject: false, can_resume: false, can_submit: false, can_validate: true, can_view: true, can_withdraw: false }, source_kind: "online", status: "needs_attention", submitted_by_user_id: null, validation_run_id: null, workflow_revision: 1 }), { status: 200 }));
  }));
  render(<MemoryRouter initialEntries={["/catalog/imports/2"]}><Routes><Route element={<CatalogImportPage />} path="/catalog/imports/:import_id" /></Routes></MemoryRouter>);
  expect(await screen.findByRole("heading", { name: "商品主档审核" })).toBeVisible();
  expect(await screen.findAllByRole("tab")).toHaveLength(5);
});

it('saves a changed mapping through the fixed action, reads it back, and checks the new revision automatically',async()=>{
 setSessionCsrfToken('test-csrf');let revision=1;let decision:string|null=null;let validation:number|null=1;const commands:string[]=[];
 const row=(section:string,payload:Record<string,string|null>)=>({section,row_key:section==='mappings'?'m':section==='skus'?'s':'st',row_origin:'system',projection_state:'included',payload});
 vi.stubGlobal('fetch',vi.fn((input:RequestInfo|URL,init?:RequestInit)=>{
  const raw=typeof input==='string'?input:input instanceof URL?input.href:input.url;const url=new URL(raw,'http://local');
  if(url.pathname.endsWith('/decisions')){const body=JSON.parse(init?.body as string) as {expected_workflow_revision:number;mutations:{payload:{identity_decision:string;target_sku_row_key:string}}[]};expect(body.expected_workflow_revision).toBe(1);expect(body.mutations[0]?.payload.target_sku_row_key).toBe('s');decision=body.mutations[0]!.payload.identity_decision;revision=2;validation=null;commands.push('save');return Promise.resolve(new Response(JSON.stringify({safe_result:{workflow_revision:revision}})));}
  if(url.pathname.endsWith('/validate')){expect(JSON.parse(init?.body as string)).toMatchObject({expected_workflow_revision:2});commands.push('validate');revision=3;validation=2;return Promise.resolve(new Response(JSON.stringify({safe_result:{workflow_revision:revision}})));}
  if(url.pathname.includes('/rows/')){const section=url.pathname.split('/rows/')[1];const rows=section==='styles'?[row('styles',{style_code:'2301',standard_name:'演练商品'})]:section==='skus'?[row('skus',{style_row_key:'st',internal_display_sku:'2301-Hot Pink-L',code_status:'confirmed',code_evidence:'原资料已核对',standard_color:'Hot Pink',standard_size:'L'})]:section==='mappings'?[row('mappings',{seller_sku_preview:'2301-Hot Pink-L',identity_decision:decision,target_sku_row_key:'s'})]:[];return Promise.resolve(new Response(JSON.stringify({rows,total_rows:rows.length})));}
  return Promise.resolve(new Response(JSON.stringify({import_id:2,source_kind:'online',status:decision?'validated':'needs_attention',workflow_revision:revision,validation_run_id:validation,permissions:{can_validate:true,can_edit:true},issues:decision?[]:[{section:'mappings',row_key:'m',field:'/identity_decision',severity:'blocking',reason_code:'required'}]})));
 }));
 function Workspace(){const[action,setAction]=useState<CatalogDraftSaveAction>();return <><CatalogImportPage onSaveAction={setAction}/>{action&&<button disabled={action.disabled} onClick={action.run}>固定操作保存</button>}</>;}
 render(<MemoryRouter initialEntries={['/catalog/imports/2']}><Routes><Route path="/catalog/imports/:import_id" element={<Workspace/>}/></Routes></MemoryRouter>);
 await screen.findByRole('radio',{name:'纳入目录'});fireEvent.click(screen.getByRole('radio',{name:'纳入目录'}));
 await screen.findByRole('button',{name:'固定操作保存'});
 await userEvent.click(screen.getByRole('tab',{name:/SKU 标准化/}));
 expect(screen.queryByRole('button',{name:'固定操作保存'})).not.toBeInTheDocument();
 await userEvent.click(screen.getByRole('tab',{name:/SKU 映射/}));
 expect(screen.getByRole('radio',{name:'纳入目录'})).toBeChecked();
 fireEvent.click(await screen.findByRole('button',{name:'固定操作保存'}));
 await waitFor(()=>expect(commands).toEqual(['save','validate']));
 await waitFor(()=>expect(screen.queryByText('尚未填写或确认；修改后请重新校验。')).not.toBeInTheDocument());
 expect(screen.queryByRole('button',{name:'固定操作保存'})).not.toBeInTheDocument();setSessionCsrfToken(undefined);
});


it.each(['unchanged', 'changed', 'locked', 'identity'] as const)('recovers a revision conflict safely when the latest projection is %s', async mode => {
  setSessionCsrfToken('csrf');
  let revision = 1; let saved = false; let validation: number | null = 1;
  const writes: { expected_workflow_revision: number; mutations: { payload: Record<string, unknown> }[] }[] = [];
  const makeRow = (section: string, row_key: string, payload: Record<string, unknown>) => ({section, row_key, row_origin:'system', projection_state:'included', payload});
  vi.stubGlobal('fetch', vi.fn((input: RequestInfo | URL, init?: RequestInit) => {
    const path = new URL(typeof input === 'string' ? input : input instanceof URL ? input.href : input.url, 'http://local').pathname;
    if (path.endsWith('/decisions')) {
      const body = JSON.parse(init?.body as string) as (typeof writes)[number]; writes.push(body);
      if (writes.length === 1) { revision = 2; return Promise.resolve(new Response(JSON.stringify({error:{code:'catalog_workflow_revision_conflict',message:'旧修订'}}),{status:409})); }
      expect(body.expected_workflow_revision).toBe(2); saved = true; revision = 3; validation = null;
      return Promise.resolve(new Response(JSON.stringify({safe_result:{workflow_revision:revision}})));
    }
    if (path.endsWith('/validate')) { expect(writes).toHaveLength(2); revision = 4; validation = 2; return Promise.resolve(new Response(JSON.stringify({safe_result:{workflow_revision:revision}}))); }
    if (path.includes('/rows/')) {
      const section = path.split('/rows/')[1];
      const rows = section === 'mappings' ? [makeRow(section,'m',{seller_sku_preview:revision>=2&&mode==='identity'?'2301-Black-L':'2301-Navy-L',target_sku_row_key:'s',identity_decision:saved?'mapped':null,change_reason:revision >= 2 && mode === 'changed'?'其他窗口的说明':null})] : section === 'skus' ? [makeRow(section,'s',{internal_display_sku:'2301-Navy-L',code_status:'confirmed',code_evidence:'来源已核对',standard_color:'Navy',standard_size:'L'})] : [];
      return Promise.resolve(new Response(JSON.stringify({rows,total_rows:rows.length})));
    }
    return Promise.resolve(new Response(JSON.stringify({import_id:2,source_kind:'online',status:mode === 'locked' && revision>=2?'approved':'needs_attention',workflow_revision:revision,validation_run_id:validation,permissions:{can_edit:!(mode==='locked'&&revision>=2),can_validate:true}})));
  }));
  render(<MemoryRouter><CatalogImportPage embeddedId={2}/></MemoryRouter>);
  fireEvent.click(await screen.findByRole('radio',{name:'纳入目录'}));
  fireEvent.click(screen.getByRole('button',{name:'保存当前分类修改（1行）'}));
  if (mode === 'unchanged') {
    await waitFor(()=>expect(revision).toBe(4)); expect(writes).toHaveLength(2);
  } else {
    await screen.findByText(mode === 'locked' ? /批次已结束或当前账号无权编辑/ : /最新草稿已读回/);
    expect(writes).toHaveLength(1);
    if (mode === 'identity') { expect(screen.queryByRole('button',{name:'保留我的修改'})).not.toBeInTheDocument(); expect(screen.getByRole('radio',{name:'纳入目录'})).toBeChecked(); }
    if (mode === 'changed') {
      expect(screen.getByRole('radio',{name:'纳入目录'})).toBeChecked();
      fireEvent.click(screen.getByRole('button',{name:'保留我的修改'}));
      fireEvent.click(screen.getByRole('button',{name:'保存当前分类修改（1行）'}));
      await waitFor(()=>expect(revision).toBe(4));
      expect(writes[1]?.mutations[0]?.payload).toMatchObject({identity_decision:'mapped',change_reason:'其他窗口的说明'});
    }
  }
  setSessionCsrfToken(undefined);
});
