import { MemoryRouter } from "react-router-dom";
import { fireEvent, render, screen, waitFor, cleanup, act } from "@testing-library/react";
import { afterEach, beforeEach, expect, it, vi } from "vitest";

import { setSessionCsrfToken } from "../../api/client";
import { CatalogWorkflowActions } from "./CatalogWorkflowActions";
import type { CatalogImportSummary } from "./catalogTypes";

beforeEach(() => setSessionCsrfToken("csrf"));
afterEach(() => { cleanup();setSessionCsrfToken(undefined); vi.unstubAllGlobals(); });

it("shows the approved version and no further approval action", () => {
  render(<MemoryRouter><CatalogWorkflowActions imported={{ status: "approved", approved_catalog_version_number: 3, permissions: {}, workflow_revision: 4 } as CatalogImportSummary} onChanged={vi.fn()} /></MemoryRouter>);
  expect(screen.getByRole("heading", { name: "已批准生效" })).toBeVisible();
  expect(screen.getByRole("status")).toHaveTextContent("V3");
  expect(screen.getByRole("link", { name: "查看当前商品主档" })).toHaveAttribute("href", "/catalog");
  expect(screen.getByRole("link", { name: "查看目录版本" })).toHaveAttribute("href", "/catalog/versions");
  expect(screen.queryByRole("button", { name: "确认批准目录" })).not.toBeInTheDocument();
});

it("returns an approved Amazon listing batch to the listing workspace", () => {
  render(<MemoryRouter><CatalogWorkflowActions imported={{
    import_id: 8,
    status: "approved",
    source_kind: "production",
    approved_catalog_version_number: 5,
    permissions: {},
    production_source: { source_schema: "amazon_listing_v1" },
    workflow_revision: 8,
  } as CatalogImportSummary} onChanged={vi.fn()} /></MemoryRouter>);
  expect(screen.getByRole("link", { name: "返回亚马逊商品清单" })).toHaveAttribute("href", "/catalog/production-sources?entry=amazon-listing");
});

it("invalidates a preview when the workflow revision changes and respects high risk permission", async () => {
  vi.stubGlobal("fetch", vi.fn(() => Promise.resolve(new Response(JSON.stringify({ safe_result: { risk: "high", included_row_count: 5, audit_only_row_count: 1, catalog_publication_revision: 2 } }), { status: 200 }))));
  const imported = { import_id: 1, workflow_revision: 2, permissions: { can_preview: true, can_approve_normal: true, can_approve_high_risk: false } } as CatalogImportSummary;
  const result = render(<MemoryRouter><CatalogWorkflowActions imported={imported} onChanged={vi.fn()} /></MemoryRouter>);
  fireEvent.click(screen.getByRole("button", { name: "生成批准预览" }));
  expect(await screen.findByText("风险：高风险（仅管理员可批准）")).toBeVisible();
  expect(screen.queryByRole("button", { name: "确认批准目录" })).not.toBeInTheDocument();
  result.rerender(<MemoryRouter><CatalogWorkflowActions imported={{ ...imported, workflow_revision: 3 }} onChanged={vi.fn()} /></MemoryRouter>);
  expect(screen.queryByText("风险：高风险（仅管理员可批准）")).not.toBeInTheDocument();
});

it("uses server permissions and the latest workflow counter", async () => {
  const fetchMock = vi.fn(() => Promise.resolve(new Response(JSON.stringify({ safe_result: { workflow_revision: 3 } }), { status: 200 })));
  vi.stubGlobal("fetch", fetchMock);
  const imported = { catalog_publication_revision: 0, import_id: 1, parse_attempt_revision: 0, permissions: { can_approve_high_risk: false, can_approve_normal: false, can_download_original: false, can_edit: true, can_preview: false, can_rebase: false, can_reject: false, can_resume: false, can_submit: false, can_validate: true, can_view: true, can_withdraw: false }, workflow_revision: 2 } as CatalogImportSummary;
  render(<MemoryRouter><CatalogWorkflowActions imported={imported} onChanged={vi.fn()} /></MemoryRouter>);
  fireEvent.click(screen.getByRole("button", { name: "重新校验" }));
  await waitFor(() => expect(fetchMock).toHaveBeenCalled());
  expect(screen.queryByRole("button", { name: "确认批准目录" })).not.toBeInTheDocument();
});

it('reports workflow writes and unsaved decision text to the enclosing dialog',async()=>{
 const guard=vi.fn();let complete!:(value:Record<string,unknown>)=>void;const execute=vi.fn(()=>new Promise<Record<string,unknown>>(resolve=>{complete=resolve;}));
 const imported={import_id:1,status:'in_review',workflow_revision:2,permissions:{can_validate:true,can_reject:true}} as CatalogImportSummary;
 render(<MemoryRouter><CatalogWorkflowActions imported={imported} onChanged={vi.fn()} command={execute} onGuardChange={guard}/></MemoryRouter>);
 fireEvent.change(screen.getByLabelText(/操作原因/),{target:{value:'补充本次人工核对的原因'}});await waitFor(()=>expect(guard).toHaveBeenLastCalledWith(expect.objectContaining({dirty:true})));
 fireEvent.click(screen.getByRole('button',{name:'重新校验'}));await waitFor(()=>expect(guard).toHaveBeenLastCalledWith(expect.objectContaining({busy:true})));
 act(()=>{complete({workflow_revision:3});});await waitFor(()=>expect(guard).toHaveBeenLastCalledWith(expect.objectContaining({busy:false})));
});
it('retries an uncertain workflow command with its original operation key',async()=>{
 const guard=vi.fn();const execute=vi.fn().mockRejectedValueOnce(Error('响应中断')).mockResolvedValueOnce({workflow_revision:3});
 const imported={import_id:1,status:'in_review',workflow_revision:2,permissions:{can_validate:true}} as CatalogImportSummary;
 render(<MemoryRouter><CatalogWorkflowActions imported={imported} onChanged={vi.fn()} command={execute} onGuardChange={guard}/></MemoryRouter>);
 fireEvent.click(screen.getByRole('button',{name:'重新校验'}));await screen.findByRole('button',{name:'核实原操作结果'});
 expect(guard).toHaveBeenLastCalledWith(expect.objectContaining({unknown:true}));expect(screen.getByRole('button',{name:'重新校验'})).toBeDisabled();
 fireEvent.click(screen.getByRole('button',{name:'核实原操作结果'}));await waitFor(()=>expect(execute).toHaveBeenCalledTimes(2));
 expect(execute.mock.calls[0]?.[4]).toEqual(expect.any(String));expect(execute.mock.calls[1]).toEqual(execute.mock.calls[0]);await waitFor(()=>expect(guard).toHaveBeenLastCalledWith(expect.objectContaining({unknown:false})));
});

it('rereads an acknowledged operation without submitting it again',async()=>{
 const guard=vi.fn();const execute=vi.fn().mockResolvedValue({workflow_revision:3});const changed=vi.fn().mockRejectedValueOnce(Error('读取结果中断')).mockResolvedValueOnce(undefined);
 const imported={import_id:1,status:'in_review',workflow_revision:2,permissions:{can_validate:true}} as CatalogImportSummary;
 render(<MemoryRouter><CatalogWorkflowActions imported={imported} onChanged={changed} command={execute} onGuardChange={guard}/></MemoryRouter>);
 fireEvent.click(screen.getByRole('button',{name:'重新校验'}));fireEvent.click(await screen.findByRole('button',{name:'核实原操作结果'}));
 await waitFor(()=>expect(changed).toHaveBeenCalledTimes(2));expect(execute).toHaveBeenCalledTimes(1);await waitFor(()=>expect(guard).toHaveBeenLastCalledWith(expect.objectContaining({unknown:false})));
});

it('sends the same token in header and body when recovering a lost HTTP response',async()=>{
 const fetchMock=vi.fn().mockRejectedValueOnce(Error('response lost')).mockResolvedValueOnce(new Response(JSON.stringify({safe_result:{workflow_revision:3}}),{status:200}));vi.stubGlobal('fetch',fetchMock);
 const imported={import_id:1,status:'in_review',workflow_revision:2,permissions:{can_validate:true}} as CatalogImportSummary;
 render(<MemoryRouter><CatalogWorkflowActions imported={imported} onChanged={vi.fn()}/></MemoryRouter>);
 fireEvent.click(screen.getByRole('button',{name:'重新校验'}));fireEvent.click(await screen.findByRole('button',{name:'核实原操作结果'}));await waitFor(()=>expect(fetchMock).toHaveBeenCalledTimes(2));
 const first=fetchMock.mock.calls[0]![1] as RequestInit;const second=fetchMock.mock.calls[1]![1] as RequestInit;const token=new Headers(first.headers).get('Idempotency-Key');
 expect(token).toEqual(expect.any(String));expect(new Headers(second.headers).get('Idempotency-Key')).toBe(token);if(typeof first.body!=='string')throw new Error('expected JSON body');const payload=JSON.parse(first.body) as {operation_token:string};expect(payload.operation_token).toBe(token);expect(second.body).toBe(first.body);
});


it('automatically validates, submits and previews once while reserving final approval for the user',async()=>{
 const execute=vi.fn().mockResolvedValue({workflow_revision:3,risk:'normal',projection_id:99,projection_digest:'digest',catalog_publication_revision:2,included_row_count:2,audit_only_row_count:0});
 const changed=vi.fn();const base={import_id:1,status:'needs_attention',workflow_revision:2,validation_run_id:null,permissions:{can_validate:true,can_approve_normal:true}} as CatalogImportSummary;
 const view=render(<MemoryRouter><CatalogWorkflowActions automatic imported={base} command={execute} onChanged={changed}/></MemoryRouter>);
 await waitFor(()=>expect(execute).toHaveBeenCalledTimes(1));expect(execute.mock.calls[0]?.[1]).toBe('validate');
 view.rerender(<MemoryRouter><CatalogWorkflowActions automatic imported={{...base,status:'validated',workflow_revision:3,validation_run_id:1,permissions:{...base.permissions,can_validate:true,can_submit:true}}} command={execute} onChanged={changed}/></MemoryRouter>);
 await waitFor(()=>expect(execute).toHaveBeenCalledTimes(2));expect(execute.mock.calls[1]?.[1]).toBe('submit');
 view.rerender(<MemoryRouter><CatalogWorkflowActions automatic imported={{...base,status:'ready_for_approval',workflow_revision:4,validation_run_id:1,permissions:{...base.permissions,can_validate:true,can_preview:true}}} command={execute} onChanged={changed}/></MemoryRouter>);
 await screen.findByRole('button',{name:'确认批准目录'});expect(execute.mock.calls.map(call=>String(call[1]))).toEqual(['validate','submit','approval-preview']);
 expect(screen.queryByRole('button',{name:'重新校验'})).not.toBeInTheDocument();
 fireEvent.click(screen.getByRole('button',{name:'确认批准目录'}));await waitFor(()=>expect(execute.mock.calls.at(-1)?.[1]).toBe('approve'));
});
it('stops an automatic failed check until an explicit retry reuses the original operation',async()=>{
 const execute=vi.fn().mockRejectedValueOnce(new TypeError('响应中断')).mockResolvedValueOnce({workflow_revision:3});
 render(<MemoryRouter><CatalogWorkflowActions automatic imported={{import_id:1,status:'needs_attention',workflow_revision:2,validation_run_id:null,permissions:{can_validate:true}} as CatalogImportSummary} command={execute} onChanged={vi.fn()}/></MemoryRouter>);
 await screen.findByRole('button',{name:'核实原操作结果'});expect(execute).toHaveBeenCalledTimes(1);
 fireEvent.click(screen.getByRole('button',{name:'核实原操作结果'}));await waitFor(()=>expect(execute).toHaveBeenCalledTimes(2));expect(execute.mock.calls[1]).toEqual(execute.mock.calls[0]);
});
