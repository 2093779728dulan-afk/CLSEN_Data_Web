vi.mock("../../app/AuthzGenerationContext", () => ({ useAuthzGeneration: () => ({ generation: 0 }) }));
import { render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { afterEach, expect, it, vi } from "vitest";
import { CatalogMaintenancePage } from "./CatalogMaintenancePage";

afterEach(() => vi.unstubAllGlobals());
it("keeps a usable first catalog path and explains the published-source prerequisite", async () => {
  vi.stubGlobal("fetch", vi.fn((input: RequestInfo | URL) => {
    const url = typeof input === "string" ? input : input instanceof URL ? input.href : input.url;
    const body = url.includes("/style-readiness") ? { published_reports: 74, source_scope_confirmed: false, catalog_approved: false, return_snapshot_present: false, prerequisites_present: false } : url.includes("/source-scope") ? { status: "unconfirmed", permissions: { can_confirm: false } } : url.endsWith("/latest") ? { export: null } : url.includes("/api/catalog/imports") ? { items: [], has_next: false } : { catalog: null };
    return Promise.resolve(new Response(JSON.stringify(body), { status: 200 }));
  }));
  render(<MemoryRouter><CatalogMaintenancePage /></MemoryRouter>);
  expect(await screen.findByText(/先在每日核验中导入、审核并发布来源报告/)).toBeVisible();
  expect(screen.getByRole("button", { name: "生成候选" })).toBeDisabled();
  expect(screen.getByText("直接检查候选，不需要下载或重新上传。")).toBeVisible();
});
