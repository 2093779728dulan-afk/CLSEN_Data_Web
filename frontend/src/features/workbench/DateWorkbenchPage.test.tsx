import css from "./DateWorkbenchPage.module.css";
import cellCss from "./WorkbenchCell.module.css";
import { act, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { MemoryRouter, useLocation, useNavigate } from "react-router-dom";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { ApiRequestError } from "../../api/client";
import type { DateWorkbenchResponse, SetWorkbenchCellRequest, WorkbenchImportResponse } from "../../api/generated";

const api = vi.hoisted(() => ({
  confirmWorkbenchImport: vi.fn(),
  createWorkbenchRevision: vi.fn(),
  loadWorkbench: vi.fn(),
  undoWorkbench: vi.fn(),
  uploadWorkbenchImport: vi.fn(),
  writeWorkbenchCell: vi.fn(),
}));

vi.mock("./workbenchApi", () => api);

import { DateWorkbenchPage } from "./DateWorkbenchPage";

const parentAsinId = "3e2d27a9-f565-4fc8-a8d2-cbd94d8f3594";
const skuId = "4e2d27a9-f565-4fc8-a8d2-cbd94d8f3594";
const columnId = "5e2d27a9-f565-4fc8-a8d2-cbd94d8f3594";
const sessionsId = "6e2d27a9-f565-4fc8-a8d2-cbd94d8f3594";
const salesId = "7e2d27a9-f565-4fc8-a8d2-cbd94d8f3594";
const extensionId = "8e2d27a9-f565-4fc8-a8d2-cbd94d8f3594";

const draftColumns = [
  { column_id: parentAsinId, display_order: 0, editable: false, is_key: true, participates_in_statistics: false, source_header: "Parent ASIN", standard_field_name: "parent_asin", value_kind: "text" as const },
  { column_id: skuId, display_order: 1, editable: true, is_key: true, participates_in_statistics: false, source_header: "SKU", standard_field_name: "sku", value_kind: "text" as const },
  { column_id: columnId, display_order: 2, editable: true, is_key: false, participates_in_statistics: true, source_header: "Title", standard_field_name: "title", value_kind: "text" as const },
  { column_id: sessionsId, display_order: 3, editable: true, is_key: false, participates_in_statistics: true, source_header: "Sessions", standard_field_name: "sessions", value_kind: "integer" as const },
  { column_id: salesId, display_order: 4, editable: true, is_key: false, participates_in_statistics: true, source_header: "Sales", standard_field_name: "sales", value_kind: "decimal" as const },
  { column_id: extensionId, display_order: 5, editable: true, is_key: false, participates_in_statistics: false, source_header: "Marketplace extension", standard_field_name: null, value_kind: "text" as const },
];

function page(source: "empty" | "draft" = "empty"): DateWorkbenchResponse {
  const hasDraft = source === "draft";
  return {
    actions: hasDraft ? ["edit", "undo", "validate", "publish"] : ["upload"],
    columns: hasDraft ? draftColumns : [],
    head: hasDraft ? {
      data_revision: 0,
      dataset_id: 91,
      pointed_at: "2026-08-14T08:00:00Z",
      review_revision: 0,
      ruleset_version: "test-v1",
      status: "draft",
      version_id: 92,
      version_no: 1,
    } : null,
    pagination: {
      page: 1,
      page_size: 50,
      total_pages: hasDraft ? 1 : 0,
      total_rows: hasDraft ? 1 : 0,
    },
    pending_upload_count: 0,
    permissions: {
      can_create_revision: false,
      can_edit: hasDraft,
      can_publish: hasDraft,
      can_undo: hasDraft,
      can_upload: !hasDraft,
      can_validate: hasDraft,
    },
    report_date: "2026-08-14",
    report_type: "business_report",
    rows: hasDraft ? [{
      cells: [
        { base: "B0TEST", cell_revision: 0, changed: false, column_id: parentAsinId, current: "B0TEST", editable: false },
        { base: "2401-Black-M", cell_revision: 0, changed: false, column_id: skuId, current: "2401-Black-M", editable: true },
        { base: "Original", cell_revision: 0, changed: false, column_id: columnId, current: "Original", editable: true },
        { base: 12, cell_revision: 0, changed: false, column_id: sessionsId, current: 12, editable: true },
        { base: "34.50", cell_revision: 0, changed: false, column_id: salesId, current: "34.50", editable: true },
        { base: "Legacy value", cell_revision: 0, changed: false, column_id: extensionId, current: "Legacy value", editable: true },
      ],
      row_id: 93,
      row_ordinal: 1,
      row_state: "active",
    }] : [],
    source,
    tabs: [
      { report_type: "business_report", source },
      { report_type: "return_report", source: "empty" },
    ],
    validation: null,
  };
}

function contextualDraftPage(
  reportDate: string,
  reportType: "business_report" | "return_report",
  title: string,
): DateWorkbenchResponse {
  const result = page("draft");
  result.report_date = reportDate;
  result.report_type = reportType;
  result.rows[0]!.cells.find((cell) => cell.column_id === columnId)!.current = title;
  result.tabs = [
    { report_type: "business_report", source: reportType === "business_report" ? "draft" : "empty" },
    { report_type: "return_report", source: reportType === "return_report" ? "draft" : "empty" },
  ];
  return result;
}

function deferred<T>() {
  let resolve!: (value: T | PromiseLike<T>) => void;
  let reject!: (reason?: unknown) => void;
  const promise = new Promise<T>((nextResolve, nextReject) => {
    resolve = nextResolve;
    reject = nextReject;
  });
  return { promise, reject, resolve };
}

function mutationResult(current: string, revision: number) {
  return {
    cell: {
      base: "Original",
      cell_revision: revision,
      changed: true,
      column_id: columnId,
      current,
      row_id: 93,
    },
    change_id: revision,
    head: {
      data_revision: revision,
      dataset_id: 91,
      pointed_at: "2026-08-14T08:00:00Z",
      review_revision: 0,
      status: "draft" as const,
      version_id: 92,
    },
    operation_token: `operation-${revision}`,
  };
}

function workspaceReadyImport() {
  return {
    batch_id: 44,
    dataset_id: 91,
    duplicate: false,
    encoding: "utf-8-sig" as const,
    issue_codes: [],
    message: null,
    report_date: "2026-08-14",
    report_type: "business_report" as const,
    stage: "draft" as const,
    status: "workspace_ready" as const,
    version_id: 92,
    workspace_url: "/review/2026-08-14?report_type=business_report",
  };
}

function ReportContextControls({ reportDate, siteId = 9, userId = 88 }: { reportDate: string; siteId?: number; userId?: number }) {
  const navigate = useNavigate();
  return <>
    <button onClick={() => { void navigate(`/review/${reportDate}?report_type=business_report`); }} type="button">测试经营上下文</button>
    <button onClick={() => { void navigate(`/review/${reportDate}?report_type=return_report`); }} type="button">测试退货上下文</button>
    <DateWorkbenchPage canWrite reportDate={reportDate} siteId={siteId} userId={userId} />
  </>;
}

function renderPage({ initialEntry = "/review/2026-08-14?report_type=business_report", siteId = 9, userId = 88 } = {}) {
  return render(
    <MemoryRouter initialEntries={[initialEntry]}>
      <DateWorkbenchPage canWrite reportDate="2026-08-14" siteId={siteId} userId={userId} />
    </MemoryRouter>,
  );
}

describe("DateWorkbenchPage", () => {
  beforeEach(() => {
    api.confirmWorkbenchImport.mockReset();
    api.createWorkbenchRevision.mockReset();
    api.loadWorkbench.mockReset();
    api.undoWorkbench.mockReset();
    api.uploadWorkbenchImport.mockReset();
    api.writeWorkbenchCell.mockReset();
    window.localStorage.clear();
  });

  it.each(["duplicate", "conflict_required", "failed", "processing"] as const)("continues the exact uploaded source for %s instead of reopening the old table", async (status) => {
    api.loadWorkbench.mockResolvedValue(page("empty"));
    api.uploadWorkbenchImport.mockResolvedValue({ ...workspaceReadyImport(), status });
    render(<MemoryRouter initialEntries={["/review/2026-08-14"]}><DateWorkbenchPage canWrite reportDate="2026-08-14" siteId={9} userId={88} /><LocationProbe /></MemoryRouter>);
    fireEvent.change(await screen.findByLabelText("选择 CSV 文件"), { target: { files: [new File(["corrected"], "corrected.csv", { type: "text/csv" })] } });
    const continueButton = await screen.findByRole("button", { name: "核对文件并继续审核" });
    await act(async () => { fireEvent.click(continueButton); await Promise.resolve(); });
    const location = JSON.parse(screen.getByTestId("location").textContent ?? "") as { pathname: string; search: string };
    expect(location.pathname).toBe("/review-advanced/2026-08-14");
    expect(new URLSearchParams(location.search).get("batch_id")).toBe("44");
  });

  it("keeps a business CSV uploaded from the return tab pending explicit confirmation", async () => {
    api.loadWorkbench.mockResolvedValue({ ...page("empty"), report_type: "return_report" });
    api.uploadWorkbenchImport.mockResolvedValue({ ...workspaceReadyImport(), status: "confirmation_required", stage: "recognition", issue_codes: ["selected_type_conflict"] });
    render(<MemoryRouter initialEntries={["/review/2026-08-14?report_type=return_report"]}><DateWorkbenchPage canWrite reportDate="2026-08-14" siteId={9} userId={88} /></MemoryRouter>);
    const file = new File(["SKU,Sessions\nSYNTHETIC,2"], "business.csv", { type: "text/csv" });
    fireEvent.change(await screen.findByLabelText("选择 CSV 文件"), { target: { files: [file] } });
    expect(await screen.findByText("文件类型与当前入口不一致")).toBeVisible();
    expect(screen.getByText("文件类型与所选报表不一致")).toBeVisible();
    expect(api.uploadWorkbenchImport).toHaveBeenCalledWith("2026-08-14", file, expect.any(String), "return_report");
    expect(api.confirmWorkbenchImport).not.toHaveBeenCalled();
    expect(screen.getByText("所选文件：business.csv")).toBeVisible();
    expect(screen.getByRole("button", { name: "按经营报告继续" })).toBeVisible();
    const replacement = new File(["return-date,sku\n2026-08-14,SYNTHETIC"], "returns.csv", { type: "text/csv" });
    api.uploadWorkbenchImport.mockResolvedValue({ ...workspaceReadyImport(), report_type: "return_report", workspace_url: "/review/2026-08-14?report_type=return_report" });
    fireEvent.change(screen.getByLabelText("重新选择退货报告 CSV"), { target: { files: [replacement] } });
    await waitFor(() => expect(screen.queryByText("文件类型与当前入口不一致")).not.toBeInTheDocument());
    expect(api.uploadWorkbenchImport).toHaveBeenLastCalledWith("2026-08-14", replacement, expect.any(String), "return_report");
    expect(api.confirmWorkbenchImport).not.toHaveBeenCalled();
  });

  it("uploads an empty report day and opens the generated table", async () => {
    api.loadWorkbench.mockResolvedValueOnce(page("empty")).mockResolvedValue(page("draft"));
    api.uploadWorkbenchImport.mockResolvedValue({
      batch_id: 44,
      dataset_id: 91,
      duplicate: false,
      encoding: "utf-8-sig",
      issue_codes: [],
      message: null,
      report_date: "2026-08-14",
      report_type: "business_report",
      stage: "draft",
      status: "workspace_ready",
      version_id: 92,
      workspace_url: "/review/2026-08-14?report_type=business_report",
    });

    renderPage();
    const input = await screen.findByLabelText("选择 CSV 文件");
    const file = new File(["Title\r\nOriginal\r\n"], "20260814-BusinessReport-test.csv", { type: "text/csv" });
    fireEvent.change(input, { target: { files: [file] } });

    await screen.findByRole("columnheader", { name: /Title/ });
    expect(api.uploadWorkbenchImport).toHaveBeenCalledWith(
      "2026-08-14",
      file,
      expect.any(String),
      "business_report",
    );
    expect(api.loadWorkbench).toHaveBeenCalledTimes(2);
  });

  it("autosaves an edited cell with the visible head and cell revision", async () => {
    api.loadWorkbench.mockResolvedValue(page("draft"));
    api.writeWorkbenchCell.mockResolvedValue({
      cell: {
        base: "Original",
        cell_revision: 1,
        changed: true,
        column_id: columnId,
        current: "Updated",
        row_id: 93,
      },
      change_id: 1,
      head: {
        data_revision: 1,
        dataset_id: 91,
        pointed_at: "2026-08-14T08:00:00Z",
        review_revision: 0,
        status: "draft",
        version_id: 92,
      },
      operation_token: "ba6ce953-488c-4db3-a45f-77b3eca4c573",
    });

    renderPage();
    const cell = await screen.findByRole("textbox", { name: "Title，第 1 行" });
    fireEvent.change(cell, { target: { value: "Updated" } });
    fireEvent.blur(cell);

    await waitFor(() => expect(api.writeWorkbenchCell).toHaveBeenCalledTimes(1));
    const call = api.writeWorkbenchCell.mock.calls[0] as [
      number,
      number,
      string,
      SetWorkbenchCellRequest,
      string,
    ];
    expect(call.slice(0, 3)).toEqual([92, 93, columnId]);
    expect(call[3]).toMatchObject({
      expected_cell_revision: 0,
      head: { data_revision: 0, dataset_id: 91 },
      value: { type: "text", value: "Updated" },
    });
    expect(call[4]).toEqual(expect.any(String));
    await screen.findByText("服务器已同步");
  });

  it("keeps a newer date authoritative when an aborted older response resolves last", async () => {
    const older = deferred<DateWorkbenchResponse>();
    const newer = deferred<DateWorkbenchResponse>();
    api.loadWorkbench.mockImplementationOnce(() => older.promise).mockImplementationOnce(() => newer.promise);
    const workbench = (reportDate: string) => <MemoryRouter initialEntries={[`/review/${reportDate}?report_type=business_report`]}>
      <DateWorkbenchPage canWrite reportDate={reportDate} siteId={9} userId={88} />
    </MemoryRouter>;

    const view = render(workbench("2026-08-13"));
    await waitFor(() => expect(api.loadWorkbench).toHaveBeenCalledTimes(1));
    const olderSignal = api.loadWorkbench.mock.calls[0]?.[3] as AbortSignal | undefined;
    view.rerender(workbench("2026-08-14"));
    await waitFor(() => expect(api.loadWorkbench).toHaveBeenCalledTimes(2));
    expect(olderSignal?.aborted).toBe(true);

    await act(async () => {
      newer.resolve(contextualDraftPage("2026-08-14", "business_report", "Newer date"));
      await Promise.resolve();
    });
    expect(await screen.findByRole("heading", { name: "2026-08-14 日期数据工作台" })).toBeVisible();
    expect(screen.getByRole("textbox", { name: "Title，第 1 行" })).toHaveValue("Newer date");

    await act(async () => {
      older.resolve(contextualDraftPage("2026-08-13", "business_report", "Stale date"));
      await Promise.resolve();
    });
    expect(screen.getByRole("heading", { name: "2026-08-14 日期数据工作台" })).toBeVisible();
    expect(screen.getByRole("textbox", { name: "Title，第 1 行" })).toHaveValue("Newer date");
  });

  it("does not let a stale report response expose its page or clear the newer busy state", async () => {
    const staleReturn = deferred<DateWorkbenchResponse>();
    const latestBusiness = deferred<DateWorkbenchResponse>();
    api.loadWorkbench
      .mockResolvedValueOnce(contextualDraftPage("2026-08-14", "business_report", "Initial business"))
      .mockImplementationOnce(() => staleReturn.promise)
      .mockImplementationOnce(() => latestBusiness.promise);
    const user = userEvent.setup();
    render(<MemoryRouter initialEntries={["/review/2026-08-14?report_type=business_report"]}>
      <ReportContextControls reportDate="2026-08-14" />
    </MemoryRouter>);

    expect(await screen.findByRole("textbox", { name: "Title，第 1 行" })).toHaveValue("Initial business");
    await user.click(screen.getByRole("button", { name: "测试退货上下文" }));
    await waitFor(() => expect(api.loadWorkbench).toHaveBeenCalledTimes(2));
    expect(screen.queryByRole("textbox", { name: "Title，第 1 行" })).not.toBeInTheDocument();
    const staleSignal = api.loadWorkbench.mock.calls[1]?.[3] as AbortSignal | undefined;
    await user.click(screen.getByRole("button", { name: "测试经营上下文" }));
    await waitFor(() => expect(api.loadWorkbench).toHaveBeenCalledTimes(3));
    expect(staleSignal?.aborted).toBe(true);

    await act(async () => {
      staleReturn.resolve(contextualDraftPage("2026-08-14", "return_report", "Stale return"));
      await Promise.resolve();
    });
    expect(screen.getByText("正在加载日期表格…")).toBeVisible();
    expect(screen.queryByRole("table", { name: "退货报告原始数据" })).not.toBeInTheDocument();

    await act(async () => {
      latestBusiness.resolve(contextualDraftPage("2026-08-14", "business_report", "Latest business"));
      await Promise.resolve();
    });
    expect(await screen.findByRole("textbox", { name: "Title，第 1 行" })).toHaveValue("Latest business");
  });

  it("does not let delayed import completion reload or abort the current report context", async () => {
    const delayedImport = deferred<WorkbenchImportResponse>();
    const currentLoad = deferred<DateWorkbenchResponse>();
    api.loadWorkbench.mockResolvedValueOnce(page("empty")).mockImplementationOnce(() => currentLoad.promise);
    api.uploadWorkbenchImport.mockImplementationOnce(() => delayedImport.promise);
    const user = userEvent.setup();
    render(<MemoryRouter initialEntries={["/review/2026-08-14?report_type=business_report"]}>
      <ReportContextControls reportDate="2026-08-14" />
    </MemoryRouter>);

    const fileInput = await screen.findByLabelText("选择 CSV 文件");
    fireEvent.change(fileInput, { target: { files: [new File(["Title\r\nOriginal\r\n"], "delayed.csv", { type: "text/csv" })] } });
    await waitFor(() => expect(api.uploadWorkbenchImport).toHaveBeenCalledTimes(1));
    await user.click(screen.getByRole("button", { name: "测试退货上下文" }));
    await waitFor(() => expect(api.loadWorkbench).toHaveBeenCalledTimes(2));
    const currentSignal = api.loadWorkbench.mock.calls[1]?.[3] as AbortSignal | undefined;

    await act(async () => {
      delayedImport.resolve(workspaceReadyImport());
      await Promise.resolve();
    });
    expect(api.loadWorkbench).toHaveBeenCalledTimes(2);
    expect(currentSignal?.aborted).toBe(false);

    await act(async () => {
      currentLoad.resolve(contextualDraftPage("2026-08-14", "return_report", "Current return"));
      await Promise.resolve();
    });
    expect(await screen.findByRole("textbox", { name: "Title，第 1 行" })).toHaveValue("Current return");
  });

  it("does not let delayed revision completion reload or abort the current report context", async () => {
    const published = page("draft");
    published.source = "published";
    const delayedRevision = deferred<object>();
    const currentLoad = deferred<DateWorkbenchResponse>();
    api.loadWorkbench.mockResolvedValueOnce(published).mockImplementationOnce(() => currentLoad.promise);
    api.createWorkbenchRevision.mockImplementationOnce(() => delayedRevision.promise);
    const user = userEvent.setup();
    render(<MemoryRouter initialEntries={["/review/2026-08-14?report_type=business_report"]}>
      <ReportContextControls reportDate="2026-08-14" />
    </MemoryRouter>);

    await user.click(await screen.findByRole("button", { name: "开始修改" }));
    await user.click(screen.getByRole("button", { name: "测试退货上下文" }));
    await waitFor(() => expect(api.loadWorkbench).toHaveBeenCalledTimes(2));
    const currentSignal = api.loadWorkbench.mock.calls[1]?.[3] as AbortSignal | undefined;

    await act(async () => {
      delayedRevision.resolve({});
      await Promise.resolve();
    });
    expect(api.loadWorkbench).toHaveBeenCalledTimes(2);
    expect(currentSignal?.aborted).toBe(false);

    await act(async () => {
      currentLoad.resolve(contextualDraftPage("2026-08-14", "return_report", "Current return"));
      await Promise.resolve();
    });
    expect(await screen.findByRole("textbox", { name: "Title，第 1 行" })).toHaveValue("Current return");
  });

  it("does not let delayed undo completion reload or release the current load owner", async () => {
    const delayedUndo = deferred<object>();
    const currentLoad = deferred<DateWorkbenchResponse>();
    api.loadWorkbench.mockResolvedValueOnce(page("draft")).mockImplementationOnce(() => currentLoad.promise);
    api.undoWorkbench.mockImplementationOnce(() => delayedUndo.promise);
    const user = userEvent.setup();
    render(<MemoryRouter initialEntries={["/review/2026-08-14?report_type=business_report"]}>
      <ReportContextControls reportDate="2026-08-14" />
    </MemoryRouter>);

    await user.click(await screen.findByRole("button", { name: "撤销上次修改" }));
    await user.click(screen.getByRole("button", { name: "测试退货上下文" }));
    await waitFor(() => expect(api.loadWorkbench).toHaveBeenCalledTimes(2));
    const currentSignal = api.loadWorkbench.mock.calls[1]?.[3] as AbortSignal | undefined;

    await act(async () => {
      delayedUndo.resolve({});
      await Promise.resolve();
    });
    expect(api.loadWorkbench).toHaveBeenCalledTimes(2);
    expect(currentSignal?.aborted).toBe(false);
    expect(screen.getByText("正在加载日期表格…")).toBeVisible();

    await act(async () => {
      currentLoad.resolve(contextualDraftPage("2026-08-14", "return_report", "Current return"));
      await Promise.resolve();
    });
    expect(await screen.findByRole("textbox", { name: "Title，第 1 行" })).toHaveValue("Current return");
  });

  it("keeps the current loading owner busy when an old import finishes without reloading", async () => {
    const delayedImport = deferred<WorkbenchImportResponse>();
    const currentLoad = deferred<DateWorkbenchResponse>();
    api.loadWorkbench.mockResolvedValueOnce(page("empty")).mockImplementationOnce(() => currentLoad.promise);
    api.uploadWorkbenchImport.mockImplementationOnce(() => delayedImport.promise);
    const user = userEvent.setup();
    render(<MemoryRouter initialEntries={["/review/2026-08-14?report_type=business_report"]}>
      <ReportContextControls reportDate="2026-08-14" />
    </MemoryRouter>);

    const fileInput = await screen.findByLabelText("选择 CSV 文件");
    fireEvent.change(fileInput, { target: { files: [new File(["Title\r\nOriginal\r\n"], "delayed.csv", { type: "text/csv" })] } });
    await waitFor(() => expect(api.uploadWorkbenchImport).toHaveBeenCalledTimes(1));
    await user.click(screen.getByRole("button", { name: "测试退货上下文" }));
    await waitFor(() => expect(api.loadWorkbench).toHaveBeenCalledTimes(2));

    await act(async () => {
      delayedImport.resolve({ ...workspaceReadyImport(), status: "duplicate" });
      await Promise.resolve();
    });
    expect(screen.getByText("正在加载日期表格…")).toBeVisible();

    await act(async () => {
      currentLoad.resolve(contextualDraftPage("2026-08-14", "return_report", "Current return"));
      await Promise.resolve();
    });
    expect(await screen.findByRole("textbox", { name: "Title，第 1 行" })).toHaveValue("Current return");
  });

  it("shows the authoritative original after save and undo without patching again on blur", async () => {
    const authoritative = page("draft");
    authoritative.permissions.can_undo = false;
    authoritative.head!.data_revision = 2;
    const authoritativeCell = authoritative.rows[0]!.cells.find((cell) => cell.column_id === columnId)!;
    authoritativeCell.cell_revision = 2;
    authoritativeCell.current = "Original";
    authoritativeCell.changed = false;
    const initial = page("draft");
    initial.permissions.can_undo = false;
    api.loadWorkbench.mockResolvedValueOnce(initial).mockResolvedValueOnce(authoritative);
    api.writeWorkbenchCell.mockResolvedValue({
      cell: {
        base: "Original",
        cell_revision: 1,
        changed: true,
        column_id: columnId,
        current: "Updated",
        row_id: 93,
      },
      change_id: 1,
      head: {
        data_revision: 1,
        dataset_id: 91,
        pointed_at: "2026-08-14T08:00:00Z",
        review_revision: 0,
        status: "draft",
        version_id: 92,
      },
      operation_token: "ba6ce953-488c-4db3-a45f-77b3eca4c573",
    });
    api.undoWorkbench.mockResolvedValue({});
    const user = userEvent.setup();

    renderPage();
    const cell = await screen.findByRole("textbox", { name: "Title，第 1 行" });
    expect(screen.getByRole("button", { name: "撤销上次修改" })).toBeDisabled();
    fireEvent.change(cell, { target: { value: "Updated" } });
    fireEvent.blur(cell);
    await waitFor(() => expect(api.writeWorkbenchCell).toHaveBeenCalledTimes(1));
    expect(cell).toHaveValue("Updated");
    await waitFor(() => expect(screen.getByRole("button", { name: "撤销上次修改" })).toBeEnabled());

    await user.click(screen.getByRole("button", { name: "撤销上次修改" }));
    const revertedCell = await screen.findByRole("textbox", { name: "Title，第 1 行" });
    expect(revertedCell).toHaveValue("Original");
    expect(screen.getByRole("button", { name: "撤销上次修改" })).toBeDisabled();
    fireEvent.blur(revertedCell);
    expect(api.writeWorkbenchCell).toHaveBeenCalledTimes(1);
  });

  it("disables stale undo availability with Chinese feedback and enables it after a new save", async () => {
    api.loadWorkbench.mockResolvedValue(page("draft"));
    api.undoWorkbench.mockRejectedValue(new ApiRequestError(409, "nothing_to_undo", "There is no still-current workbench change to undo."));
    api.writeWorkbenchCell.mockResolvedValue(mutationResult("New edit", 1));
    const user = userEvent.setup();
    renderPage();
    const cell = await screen.findByRole("textbox", { name: "Title，第 1 行" });
    await user.click(screen.getByRole("button", { name: "撤销上次修改" }));
    expect(await screen.findByText("当前没有可撤销的修改；已撤销或被后续修改覆盖的记录不能再次撤销。" )).toBeVisible();
    expect(screen.getByRole("button", { name: "撤销上次修改" })).toBeDisabled();
    expect(screen.queryByText("There is no still-current workbench change to undo.")).not.toBeInTheDocument();
    fireEvent.change(cell, { target: { value: "New edit" } });
    fireEvent.blur(cell);
    await waitFor(() => expect(screen.getByRole("button", { name: "撤销上次修改" })).toBeEnabled());
    expect(screen.queryByText("当前没有可撤销的修改；已撤销或被后续修改覆盖的记录不能再次撤销。" )).not.toBeInTheDocument();
  });

  it("contains long read-only values inside their cells and exposes the full text", async () => {
    const workbench = page("draft");
    const longValue = "US, Alpha, Medium, Regular, Adjustable Waist Tabs Tapered Leg";
    workbench.permissions.can_edit = false;
    workbench.rows[0]!.cells[0]!.editable = false;
    workbench.rows[0]!.cells[0]!.current = longValue;
    api.loadWorkbench.mockResolvedValue(workbench);

    renderPage();

    const value = await screen.findByText(longValue, { selector: `.${css["workbench-cell-value"]!}` });
    expect(value).toHaveClass(css["workbench-cell-value"]!);
    expect(value).toHaveAttribute("title", longValue);
  });

  it("keeps failed cell-save feedback on the scoped error class", async () => {
    api.loadWorkbench.mockResolvedValue(page("draft"));
    api.writeWorkbenchCell.mockRejectedValue(new Error("保存失败"));

    renderPage();
    const cell = await screen.findByRole("textbox", { name: "Title，第 1 行" });
    fireEvent.change(cell, { target: { value: "Updated" } });
    fireEvent.blur(cell);

    expect((await screen.findByText("保存失败")).closest('[role="alert"]')).toHaveClass(cellCss.error!);
  });

  it.each([
    { failure: new Error("保存失败"), label: "failed save", message: "保存失败", trigger: "sort" },
    { failure: new ApiRequestError(409, "cell_conflict", "单元格已被更新"), label: "conflict", message: "单元格已被更新", trigger: "search" },
  ])("preserves a $label draft and feedback through an ordinary $trigger reload", async ({ failure, message, trigger }) => {
    api.loadWorkbench.mockResolvedValue(page("draft"));
    api.writeWorkbenchCell.mockRejectedValueOnce(failure);
    const user = userEvent.setup();
    renderPage();

    const cell = await screen.findByRole("textbox", { name: "Title，第 1 行" });
    fireEvent.change(cell, { target: { value: "Unsaved draft" } });
    fireEvent.blur(cell);
    expect(await screen.findByText(message)).toBeVisible();

    if (trigger === "sort") {
      await user.click(screen.getByRole("columnheader", { name: /Sessions/ }));
    } else {
      const search = screen.getByRole("textbox", { name: "搜索表格" });
      await user.type(search, "coat{Enter}");
    }

    await waitFor(() => expect(api.loadWorkbench).toHaveBeenCalledTimes(2));
    expect(await screen.findByRole("textbox", { name: "Title，第 1 行" })).toHaveValue("Unsaved draft");
    expect(screen.getByText(message)).toBeVisible();
  });

  it("keeps a newer same-cell draft through an older PATCH response and saves it separately", async () => {
    const firstPatch = deferred<ReturnType<typeof mutationResult>>();
    api.loadWorkbench.mockResolvedValue(page("draft"));
    api.writeWorkbenchCell.mockImplementationOnce(() => firstPatch.promise).mockResolvedValueOnce(mutationResult("Draft 2", 2));
    renderPage();

    const cell = await screen.findByRole("textbox", { name: "Title，第 1 行" });
    fireEvent.change(cell, { target: { value: "Draft 1" } });
    fireEvent.blur(cell);
    await waitFor(() => expect(api.writeWorkbenchCell).toHaveBeenCalledTimes(1));

    fireEvent.focus(cell);
    fireEvent.change(cell, { target: { value: "Draft 2" } });
    await act(async () => {
      firstPatch.resolve(mutationResult("Draft 1", 1));
      await Promise.resolve();
    });

    expect(cell).toHaveValue("Draft 2");
    expect(screen.queryByText("已保存")).not.toBeInTheDocument();
    fireEvent.blur(cell);
    await waitFor(() => expect(api.writeWorkbenchCell).toHaveBeenCalledTimes(2));
    const secondCall = api.writeWorkbenchCell.mock.calls[1] as [number, number, string, SetWorkbenchCellRequest, string];
    expect(secondCall[3]).toMatchObject({
      expected_cell_revision: 1,
      head: { data_revision: 1 },
      value: { type: "text", value: "Draft 2" },
    });
  });

  it("settles PATCH success after a same-scope sort and reconciles the current query", async () => {
    const firstPatch = deferred<ReturnType<typeof mutationResult>>();
    const sortedOld = page("draft");
    sortedOld.rows[0]!.cells.find((cell) => cell.column_id === sessionsId)!.current = 99;
    const sortedAuthoritative = page("draft");
    sortedAuthoritative.head!.data_revision = 1;
    sortedAuthoritative.rows[0]!.cells.find((cell) => cell.column_id === sessionsId)!.current = 99;
    const authoritativeTitle = sortedAuthoritative.rows[0]!.cells.find((cell) => cell.column_id === columnId)!;
    authoritativeTitle.current = "Draft 1";
    authoritativeTitle.cell_revision = 1;
    authoritativeTitle.changed = true;
    api.loadWorkbench
      .mockResolvedValueOnce(page("draft"))
      .mockResolvedValueOnce(sortedOld)
      .mockResolvedValueOnce(sortedAuthoritative);
    api.writeWorkbenchCell.mockImplementationOnce(() => firstPatch.promise);
    const user = userEvent.setup();
    renderPage();

    const cell = await screen.findByRole("textbox", { name: "Title，第 1 行" });
    fireEvent.change(cell, { target: { value: "Draft 1" } });
    fireEvent.blur(cell);
    await waitFor(() => expect(api.writeWorkbenchCell).toHaveBeenCalledTimes(1));
    await user.click(screen.getByRole("columnheader", { name: /Sessions/ }));
    await waitFor(() => expect(api.loadWorkbench).toHaveBeenCalledTimes(2));
    expect(await screen.findByRole("textbox", { name: "Sessions，第 1 行" })).toHaveValue("99");
    expect(screen.getByText("正在保存…")).toBeVisible();

    await act(async () => {
      firstPatch.resolve(mutationResult("Draft 1", 1));
      await Promise.resolve();
    });

    await waitFor(() => expect(api.loadWorkbench).toHaveBeenCalledTimes(3));
    const lastLoad = api.loadWorkbench.mock.calls[2] as [string, string, URLSearchParams] | undefined;
    expect(lastLoad?.[2].get("sort_column_id")).toBe(sessionsId);
    expect(await screen.findByRole("textbox", { name: "Sessions，第 1 行" })).toHaveValue("99");
    const settledCell = screen.getByRole("textbox", { name: "Title，第 1 行" });
    expect(settledCell).toHaveValue("Draft 1");
    expect(screen.queryByText("正在保存…")).not.toBeInTheDocument();
    fireEvent.blur(settledCell);
    expect(api.writeWorkbenchCell).toHaveBeenCalledTimes(1);
  });

  it.each([
    { failure: new Error("延迟保存失败"), label: "failure", message: "延迟保存失败", trigger: "sort" },
    { failure: new ApiRequestError(409, "cell_conflict", "延迟单元格冲突"), label: "conflict", message: "延迟单元格冲突", trigger: "search" },
  ])("settles a delayed PATCH $label after a same-scope $trigger reload", async ({ failure, message, trigger }) => {
    const delayedPatch = deferred<ReturnType<typeof mutationResult>>();
    api.loadWorkbench.mockResolvedValue(page("draft"));
    api.writeWorkbenchCell.mockImplementationOnce(() => delayedPatch.promise);
    const user = userEvent.setup();
    renderPage();

    const cell = await screen.findByRole("textbox", { name: "Title，第 1 行" });
    fireEvent.change(cell, { target: { value: "Pending draft" } });
    fireEvent.blur(cell);
    await waitFor(() => expect(api.writeWorkbenchCell).toHaveBeenCalledTimes(1));
    if (trigger === "sort") {
      await user.click(screen.getByRole("columnheader", { name: /Sessions/ }));
    } else {
      await user.type(screen.getByRole("textbox", { name: "搜索表格" }), "coat{Enter}");
    }
    await waitFor(() => expect(api.loadWorkbench).toHaveBeenCalledTimes(2));
    expect(await screen.findByRole("textbox", { name: "Title，第 1 行" })).toHaveValue("Pending draft");

    await act(async () => {
      delayedPatch.reject(failure);
      await Promise.resolve();
    });

    expect(await screen.findByText(message)).toBeVisible();
    expect(screen.getByRole("textbox", { name: "Title，第 1 行" })).toHaveValue("Pending draft");
    expect(screen.getByRole("button", { name: "前往发布" })).toBeDisabled();
    expect(api.loadWorkbench).toHaveBeenCalledTimes(2);
  });

  it("does not settle an old-report PATCH into the current editor scope", async () => {
    const delayedPatch = deferred<ReturnType<typeof mutationResult>>();
    api.loadWorkbench
      .mockResolvedValueOnce(page("draft"))
      .mockResolvedValueOnce(contextualDraftPage("2026-08-14", "return_report", "Current return"));
    api.writeWorkbenchCell.mockImplementationOnce(() => delayedPatch.promise);
    const user = userEvent.setup();
    render(<MemoryRouter initialEntries={["/review/2026-08-14?report_type=business_report"]}>
      <ReportContextControls reportDate="2026-08-14" />
    </MemoryRouter>);

    const cell = await screen.findByRole("textbox", { name: "Title，第 1 行" });
    fireEvent.change(cell, { target: { value: "Old report draft" } });
    fireEvent.blur(cell);
    await waitFor(() => expect(api.writeWorkbenchCell).toHaveBeenCalledTimes(1));
    await user.click(screen.getByRole("button", { name: "测试退货上下文" }));
    expect(await screen.findByRole("textbox", { name: "Title，第 1 行" })).toHaveValue("Current return");

    await act(async () => {
      delayedPatch.reject(new Error("旧报表保存失败"));
      await Promise.resolve();
    });

    expect(screen.getByRole("textbox", { name: "Title，第 1 行" })).toHaveValue("Current return");
    expect(screen.queryByText("旧报表保存失败")).not.toBeInTheDocument();
  });

  it("renders the shared structural grid while preserving server column order and local layout preferences", async () => {
    api.loadWorkbench.mockResolvedValue(page("draft"));
    const user = userEvent.setup();

    renderPage();

    const table = await screen.findByRole("table", { name: "经营报告原始数据" });
    await within(table).findByRole("columnheader", { name: /Title/ });
    expect(within(table).getAllByRole("row").slice(0, 2)).toHaveLength(2);
    expect(within(table).getByRole("columnheader", { name: /Title/ })).toHaveStyle({ width: "300px" });
    expect(within(table).getByRole("columnheader", { name: /Sales/ })).toHaveStyle({ width: "104px" });
    expect(within(table).getByRole("columnheader", { name: /Parent ASIN/ })).toHaveStyle({ left: "52px" });
    expect(within(table).getByRole("columnheader", { name: /SKU/ })).toHaveStyle({ left: "196px" });
    expect(within(table).getAllByRole("button", { name: /按 .* 排序/ }).map((button) => button.getAttribute("aria-label"))).toEqual([
      "按 Parent ASIN 排序", "按 SKU 排序", "按 Title 排序", "按 Sessions 排序", "按 Sales 排序", "按 Marketplace extension 排序",
    ]);

    await user.click(screen.getByRole("button", { name: "列设置" }));
    await user.click(screen.getByRole("checkbox", { name: "Marketplace extension" }));
    expect(window.localStorage.getItem("clsen:data-table:v1:workbench:user:88:site:9:report:business_report")).toContain(extensionId);
  });

  it("exposes column settings as a labelled disclosure and restores focus on close", async () => {
    api.loadWorkbench.mockResolvedValue(page("draft"));
    const user = userEvent.setup();

    renderPage();

    const trigger = await screen.findByRole("button", { name: "列设置" });
    await user.click(trigger);
    expect(trigger).toHaveAttribute("aria-expanded", "true");
    expect(trigger).toHaveAttribute("aria-controls", "workbench-column-settings");
    expect(trigger).not.toHaveAttribute("aria-haspopup");
    expect(screen.getByRole("region", { name: "列设置" })).toHaveAttribute("id", "workbench-column-settings");

    await user.click(screen.getByRole("button", { name: "关闭列设置" }));
    expect(trigger).toHaveFocus();
    expect(trigger).toHaveAttribute("aria-expanded", "false");
  });

  it("requests server sorting through URL query parameters", async () => {
    api.loadWorkbench.mockResolvedValue(page("draft"));
    const user = userEvent.setup();

    renderPage();
    await user.click(await screen.findByRole("columnheader", { name: /Sessions/ }));

    await waitFor(() => expect(api.loadWorkbench).toHaveBeenCalledTimes(2));
    const lastLoad = api.loadWorkbench.mock.calls.at(-1) as [string, string, URLSearchParams] | undefined;
    if (!lastLoad) throw new Error("Expected a sorted workbench request.");
    const [date, type, query] = lastLoad;
    expect([date, type]).toEqual(["2026-08-14", "business_report"]);
    expect(Object.fromEntries(query.entries())).toMatchObject({
      page: "1", page_size: "50", sort_column_id: sessionsId, direction: "asc",
    });
  });

  it("clears a stale invalid server sort while retaining the report and search query", async () => {
    api.loadWorkbench
      .mockRejectedValueOnce(new ApiRequestError(422, "invalid_sort_column", "排序列不可用"))
      .mockResolvedValue(page("draft"));

    renderPage({ initialEntry: `/review/2026-08-14?report_type=business_report&search=coat&page=4&sort_column_id=${sessionsId}&direction=desc` });

    await screen.findByRole("table", { name: "经营报告原始数据" });
    await waitFor(() => expect(api.loadWorkbench).toHaveBeenCalledTimes(2));
    const lastLoad = api.loadWorkbench.mock.calls.at(-1) as [string, string, URLSearchParams] | undefined;
    if (!lastLoad) throw new Error("Expected a recovered workbench request.");
    const [date, type, query] = lastLoad;
    expect([date, type]).toEqual(["2026-08-14", "business_report"]);
    expect(Object.fromEntries(query.entries())).toMatchObject({
      page: "1", page_size: "50", search: "coat",
    });
    expect(query.has("sort_column_id")).toBe(false);
    expect(query.has("direction")).toBe(false);
  });
});

function LocationProbe() {
  const location = useLocation();
  return <output data-testid="location">{JSON.stringify({pathname:location.pathname,search:location.search,state:location.state as unknown})}</output>;
}
it("hands the exact report and version from published workbench to review", async () => {
  api.loadWorkbench.mockResolvedValue(page("draft"));
  const origin = "/published/2026-08-14?report_type=return_report&search=coat";
  render(<MemoryRouter initialEntries={[origin]}><DateWorkbenchPage canWrite reportDate="2026-08-14" siteId={9} userId={88}/><LocationProbe/></MemoryRouter>);
  const control = await screen.findByRole("button",{name:"运行检查"});
  await act(async () => { fireEvent.click(control); await Promise.resolve(); });
  expect(screen.getByTestId("location")).toHaveTextContent(JSON.stringify({pathname:"/review-advanced/2026-08-14",search:"?report_type=return_report&version_id=92",state:{workbenchReturn:origin}}));
});
it("pages through server rows and resets the changed-only filter to page one", async () => {
  api.loadWorkbench.mockImplementation((_date: string, _type: string, query: URLSearchParams) => Promise.resolve({...page("draft"),pagination:{page:Number(query.get("page")),page_size:50,total_pages:3,total_rows:120}}));
  renderPage({initialEntry:"/review/2026-08-14?search=coat&sort_column_id=sku&direction=desc"});
  fireEvent.click(await screen.findByRole("button",{name:"下一页"}));
  await waitFor(()=>expect((api.loadWorkbench.mock.lastCall?.[2] as URLSearchParams).get("page")).toBe("2"));
  fireEvent.click(await screen.findByRole("checkbox",{name:"只看修改"}));
  await waitFor(()=>expect((api.loadWorkbench.mock.lastCall?.[2] as URLSearchParams).get("page")).toBe("1"));
  const query = api.loadWorkbench.mock.lastCall?.[2] as URLSearchParams;
  expect(query.get("search")).toBe("coat");
  expect(query.get("sort_column_id")).toBe("sku");
  expect(query.get("changed_only")).toBe("true");
});
it("retries a failed initial read with the original report context", async () => {
  api.loadWorkbench.mockRejectedValueOnce(new Error("读取失败")).mockResolvedValue(page("draft"));
  renderPage();
  fireEvent.click(await screen.findByRole("button",{name:"重新读取"}));
  expect(await screen.findByRole("textbox",{name:"Title，第 1 行"})).toBeVisible();
});
