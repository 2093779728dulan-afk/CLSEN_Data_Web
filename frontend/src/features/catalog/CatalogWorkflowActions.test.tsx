import { MemoryRouter } from "react-router-dom";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, expect, it, vi } from "vitest";

import { setSessionCsrfToken } from "../../api/client";
import { CatalogWorkflowActions } from "./CatalogWorkflowActions";
import type { CatalogImportSummary } from "./catalogTypes";

beforeEach(() => setSessionCsrfToken("csrf"));
afterEach(() => { setSessionCsrfToken(undefined); vi.unstubAllGlobals(); });

it("shows the approved version and no further approval action", () => {
  render(<MemoryRouter><CatalogWorkflowActions imported={{ status: "approved", approved_catalog_version_number: 3, permissions: {}, workflow_revision: 4 } as CatalogImportSummary} onChanged={vi.fn()} /></MemoryRouter>);
  expect(screen.getByRole("heading", { name: "已批准生效" })).toBeVisible();
  expect(screen.getByRole("status")).toHaveTextContent("V3");
  expect(screen.getByRole("link", { name: "查看当前商品主档" })).toHaveAttribute("href", "/catalog");
  expect(screen.getByRole("link", { name: "查看目录版本" })).toHaveAttribute("href", "/catalog/versions");
  expect(screen.queryByRole("button", { name: "确认批准目录" })).not.toBeInTheDocument();
});

it("invalidates a preview when the workflow revision changes and respects high risk permission", async () => {
  vi.stubGlobal("fetch", vi.fn(() => Promise.resolve(new Response(JSON.stringify({ safe_result: { risk: "high", included_row_count: 5, audit_only_row_count: 1, catalog_publication_revision: 2 } }), { status: 200 }))));
  const imported = { import_id: 1, workflow_revision: 2, permissions: { can_preview: true, can_approve_normal: true, can_approve_high_risk: false } } as CatalogImportSummary;
  const result = render(<CatalogWorkflowActions imported={imported} onChanged={vi.fn()} />);
  fireEvent.click(screen.getByRole("button", { name: "生成批准预览" }));
  expect(await screen.findByText("风险：高风险（仅管理员可批准）")).toBeVisible();
  expect(screen.queryByRole("button", { name: "确认批准目录" })).not.toBeInTheDocument();
  result.rerender(<CatalogWorkflowActions imported={{ ...imported, workflow_revision: 3 }} onChanged={vi.fn()} />);
  expect(screen.queryByText("风险：高风险（仅管理员可批准）")).not.toBeInTheDocument();
});

it("uses server permissions and the latest workflow counter", async () => {
  const fetchMock = vi.fn(() => Promise.resolve(new Response(JSON.stringify({ safe_result: { workflow_revision: 3 } }), { status: 200 })));
  vi.stubGlobal("fetch", fetchMock);
  const imported = { catalog_publication_revision: 0, import_id: 1, parse_attempt_revision: 0, permissions: { can_approve_high_risk: false, can_approve_normal: false, can_download_original: false, can_edit: true, can_preview: false, can_rebase: false, can_reject: false, can_resume: false, can_submit: false, can_validate: true, can_view: true, can_withdraw: false }, workflow_revision: 2 } as CatalogImportSummary;
  render(<CatalogWorkflowActions imported={imported} onChanged={vi.fn()} />);
  fireEvent.click(screen.getByRole("button", { name: "重新校验" }));
  await waitFor(() => expect(fetchMock).toHaveBeenCalled());
  expect(screen.queryByRole("button", { name: "确认批准目录" })).not.toBeInTheDocument();
});
