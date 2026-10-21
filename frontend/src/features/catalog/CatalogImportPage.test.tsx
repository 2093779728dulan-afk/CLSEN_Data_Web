import { act, render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { afterEach, expect, it, vi } from "vitest";

import { CatalogImportPage } from "./CatalogImportPage";

afterEach(() => vi.unstubAllGlobals());
it("waits for same-revision rows before enabling workflow commands", async () => {
  const pending: Array<(response: Response) => void> = [];
  vi.stubGlobal("fetch", vi.fn((input: RequestInfo | URL) => {
    const url = typeof input === "string" ? input : input instanceof URL ? input.href : input.url;
    if (url.includes("/rows/")) return new Promise<Response>(resolve => pending.push(resolve));
    return Promise.resolve(new Response(JSON.stringify({ import_id: 2, status: "needs_attention", workflow_revision: 1, permissions: { can_validate: true }, source_kind: "online" }), { status: 200 }));
  }));
  render(<MemoryRouter initialEntries={["/catalog/imports/2"]}><Routes><Route path="/catalog/imports/:import_id" element={<CatalogImportPage />} /></Routes></MemoryRouter>);
  await waitFor(() => expect(pending).toHaveLength(5));
  expect(screen.getByRole("heading", { name: "商品主档审核" })).toBeVisible();
  expect(screen.getByRole("progressbar", { name: "审核明细加载进度" })).toHaveAttribute("value", "0");
  expect(screen.queryByText("待处理 0 项")).not.toBeInTheDocument();
  expect(screen.queryByRole("button", { name: "重新校验" })).not.toBeInTheDocument();
  await act(async () => { pending.forEach(resolve => resolve(new Response(JSON.stringify({ rows: [], total_rows: 0 }), { status: 200 }))); await Promise.resolve(); });
  expect(await screen.findByRole("button", { name: "重新校验" })).toBeEnabled();
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
