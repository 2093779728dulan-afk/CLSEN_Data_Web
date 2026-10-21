import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { requestApi, commandApi } from "../../api/client";
import { CatalogSetup } from "./CatalogSetup";
vi.mock("../../app/AuthzGenerationContext", () => ({ useAuthzGeneration: () => ({ generation: 0 }) }));
vi.mock("../../api/client", async importOriginal => ({ ...await importOriginal<typeof import("../../api/client")>(), requestApi: vi.fn(), commandApi: vi.fn() }));
const preview = { dataset_id: 74, proposed_version_id: 93, expected_publication_revision: 0, expected_dedup_publication_revision: 0, initialization_revision: 3, expected_set_digest: "a".repeat(64), published_return_reports: 37, coverage_from: "2026-07-01", coverage_to: "2026-08-06", existing_job_id: null };
describe("CatalogSetup first snapshot", () => {
  let ready: boolean;
  let reports: number;
  beforeEach(() => {
    vi.clearAllMocks(); ready = false; reports = 37;
    vi.mocked(requestApi).mockImplementation(async path => {
      await Promise.resolve();
      if (path === "/api/dashboard/style-readiness") return { published_reports: 74, published_business_reports: 37, published_return_reports: reports, coverage_from: "2026-07-01", coverage_to: "2026-08-06", return_snapshot_present: ready, catalog_approved: false } as never;
      if (path === "/api/catalog/source-scope") return { status: "confirmed", seller_account_display_name: "CLSEN", permissions: { can_confirm: false } } as never;
      if (path === "/api/publications/return-initialization") return preview as never;
      if (path === "/api/publications/return-dedup-staging/8") { ready = true; return { job_id: 8, status: "ready", result_snapshot_id: 9 } as never; }
      throw new Error("Unexpected request");
    });
    vi.mocked(commandApi).mockResolvedValue({ job_id: 8, status: "building" });
  });
  it("previews and initializes without publishing or approving mappings, then refreshes readiness", async () => {
    const onReady = vi.fn();
    render(<MemoryRouter><CatalogSetup editable onGenerationReady={onReady} /></MemoryRouter>);
    await userEvent.click(await screen.findByRole("button", { name: "准备首次退货快照" }));
    expect(commandApi).not.toHaveBeenCalled();
    expect(screen.getByText(/经营报告将在生成商品候选时一并使用/)).toBeVisible();
    await userEvent.click(screen.getByRole("button", { name: "确认建立首次快照" }));
    expect(await screen.findByText(/首次退货快照已建立/)).toBeVisible();
    await waitFor(() => expect(onReady).toHaveBeenLastCalledWith(true));
    expect(commandApi).toHaveBeenCalledTimes(1);
    expect(commandApi).toHaveBeenCalledWith("/api/publications/return-initialization", expect.objectContaining({ expected_set_digest: preview.expected_set_digest, initialization_revision: 3 }), expect.any(String));
    expect(screen.getByText(/商品主档：待生成候选、审核并批准/)).toBeVisible();
  });
  it("does not turn missing return reports into zero returns", async () => {
    reports = 0;
    render(<MemoryRouter><CatalogSetup editable /></MemoryRouter>);
    expect(await screen.findByRole("button", { name: "准备首次退货快照" })).toBeDisabled();
    expect(commandApi).not.toHaveBeenCalled();
  });
  it("keeps failed initialization actionable without claiming readiness", async () => {
    vi.mocked(commandApi).mockRejectedValue(new Error("conflict"));
    render(<MemoryRouter><CatalogSetup editable /></MemoryRouter>);
    await userEvent.click(await screen.findByRole("button", { name: "准备首次退货快照" }));
    await userEvent.click(screen.getByRole("button", { name: "确认建立首次快照" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("首次快照尚未完成");
    expect(screen.queryByText(/首次退货快照已建立/)).not.toBeInTheDocument();
  });
});
