import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";
import { beforeEach, expect, it, vi } from "vitest";

import { CatalogExportPanel } from "./CatalogExportPanel";

const { getLatestCatalogExport, resumeCatalogExport } = vi.hoisted(() => ({
  getLatestCatalogExport: vi.fn(),
  resumeCatalogExport: vi.fn(),
}));

vi.mock("./catalogApi", async (importOriginal) => {
  const actual = await importOriginal<typeof import("./catalogApi")>();
  return { ...actual, getLatestCatalogExport, resumeCatalogExport };
});

beforeEach(() => {
  getLatestCatalogExport.mockResolvedValue(undefined);
});

it("does not offer online review or download from an obsolete candidate", () => {
  render(<MemoryRouter><CatalogExportPanel catalogPublicationRevision={2} initialExport={{ export_id: 1, catalog_publication_revision: 1, export_status: "ready", job_status: "succeeded", workbook_status: "ready", execution_phase: "completed", permissions: { can_download: true, can_resume: false } } as import("./catalogApi").CatalogExportStatus} /></MemoryRouter>);
  expect(screen.getByRole("button", { name: "开始在线审核" })).toBeDisabled();
  expect(screen.queryByRole("link", { name: "下载兼容 XLSX" })).not.toBeInTheDocument();
  expect(screen.getByRole("button", { name: "重新生成候选" })).toBeEnabled();
});

it("offers candidate generation and a clearly separated compatible XLSX path", () => {
  render(<MemoryRouter><CatalogExportPanel catalogPublicationRevision={0} /></MemoryRouter>);
  expect(screen.getByRole("button", { name: "生成候选" })).toBeVisible();
  expect(screen.getByRole("heading", { name: "选择审核方式" })).toBeVisible();
  expect(screen.getByLabelText("上传已修改的兼容 XLSX")).toHaveAttribute("accept", ".xlsx");
});

it("shows real failed-job details and resumes only when allowed", async () => {
  resumeCatalogExport.mockResolvedValue({
    export_id: 41,
    export_status: "building",
    workbook_status: null,
    catalog_publication_revision: 0,
    base_catalog_version_id: null,
    capacity_violations: [],
    failure_reason_code: "catalog_export_worker_error",
    job_status: "queued",
    job_revision: 8,
    execution_phase: "waiting_for_worker",
    attempt_count: 3,
    max_attempts: 3,
    next_attempt_at: null,
    retry_allowed: false,
    worker_available: true,
    permissions: { can_download: false, can_resume: false },
  });
  render(
    <MemoryRouter>
      <CatalogExportPanel
        catalogPublicationRevision={0}
        initialExport={{
          export_id: 41,
          export_status: "building",
          workbook_status: null,
          catalog_publication_revision: 0,
          base_catalog_version_id: null,
          capacity_violations: [],
          failure_reason_code: "catalog_export_worker_error",
          job_status: "failed",
          job_revision: 7,
          execution_phase: "awaiting_manual_recovery",
          attempt_count: 3,
          max_attempts: 3,
          next_attempt_at: null,
          retry_allowed: true,
          worker_available: false,
          permissions: { can_download: false, can_resume: true },
        }}
      />
    </MemoryRouter>,
  );

  expect(screen.getByText("等待人工恢复")).toBeVisible();
  expect(screen.getByText("已尝试 3 / 3 次")).toBeVisible();
  expect(screen.getByText("Worker 当前不可用")).toBeVisible();
  expect(screen.queryByRole("link", { name: "下载兼容 XLSX" })).not.toBeInTheDocument();
  expect(screen.queryByRole("button", { name: "开始在线审核" })).not.toBeInTheDocument();
  await userEvent.click(screen.getByRole("button", { name: "恢复生成" }));
  expect(resumeCatalogExport).toHaveBeenCalledWith(41, 7);
});
