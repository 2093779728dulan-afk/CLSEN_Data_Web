import { act, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";

import type { BatchReviewItem, BatchReviewRun } from "./batchReviewTypes";

const mocks = vi.hoisted(() => ({
  advance: vi.fn(), confirm: vi.fn(), getRun: vi.fn(), pause: vi.fn(), resume: vi.fn(), retry: vi.fn(),
  execute: vi.fn(),
}));

vi.mock("./batchReviewApi", () => ({ BatchReviewApi: class {
  advance = mocks.advance; confirm = mocks.confirm; getRun = mocks.getRun;
  pause = mocks.pause; resume = mocks.resume; retry = mocks.retry;
} }));
vi.mock("./batchReviewExecutor", () => ({
  runBatchReviewExecutor: mocks.execute,
}));

import { BatchReviewPage } from "./BatchReviewPage";

function item(changes: Partial<BatchReviewItem> = {}): BatchReviewItem {
  return {
    attempt_count: 0, batch_id: 11, dataset_id: null, encoding: "utf-8-sig",
    filename: "business-2026-08-01.csv", id: 101, manual_review_url: "/review/2026-08-01?report_type=business_report",
    operation_token: null, outcome_unknown: false, reason_code: null, recovery_available: false,
    reason_message: "可安全推进至待发布。", recognition_status: "recognized",
    report_date: "2026-08-01", report_type: "business_report", retry_allowed: false,
    selected: true, status: "eligible", validation_run_id: null, version_id: null,
    ...changes,
  };
}

function run(changes: Partial<BatchReviewRun> = {}): BatchReviewRun {
  return {
    allowed_actions: ["confirm"], id: 7,
    items: [item(), item({ batch_id: 12, filename: "duplicate.csv", id: 102, reason_code: "duplicate_target_in_run", reason_message: "本任务中已有文件指向相同日期和报表类型。", selected: false, status: "manual_review" })],
    revision: 3, status: "preview",
    summary: { active: 0, eligible: 1, failed: 0, manual_review: 1, ready_for_publish: 0, skipped: 0, total: 2 },
    ...changes,
  };
}

function renderPage() {
  return render(<MemoryRouter initialEntries={["/review/batch/7"]}><Routes><Route element={<BatchReviewPage />} path="/review/batch/:runId" /></Routes></MemoryRouter>);
}

describe("BatchReviewPage", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mocks.getRun.mockResolvedValue(run());
    mocks.confirm.mockResolvedValue(run({ allowed_actions: ["pause"], status: "running" }));
    mocks.execute.mockImplementation((snapshot: BatchReviewRun) => Promise.resolve(snapshot));
  });

  it("shows the authoritative preflight fields and default eligible selection", async () => {
    renderPage();
    expect(await screen.findByRole("heading", { name: "批量审核" })).toBeInTheDocument();
    expect(screen.getByText("business-2026-08-01.csv")).toBeInTheDocument();
    expect(screen.getAllByText("2026-08-01").length).toBeGreaterThan(0);
    expect(screen.getAllByText("经营报告").length).toBeGreaterThan(0);
    expect(screen.getAllByText("utf-8-sig").length).toBeGreaterThan(0);
    expect(screen.getByRole("checkbox", { name: "选择 business-2026-08-01.csv" })).toBeChecked();
    expect(screen.getByRole("checkbox", { name: "选择 duplicate.csv" })).toBeDisabled();
    expect(screen.getByText("本任务中已有文件指向相同日期和报表类型。")).toBeInTheDocument();
    expect(screen.getByText("任务内目标重复")).toBeInTheDocument();
  });

  it("does not label an already materialized source as an empty target", async () => {
    mocks.getRun.mockResolvedValue(run({ items: [item({
      reason_code: "already_materialized", reason_message: "该批次已经生成过数据版本。",
      selected: false, status: "manual_review",
    })] }));
    renderPage();
    expect(await screen.findByText("已生成数据版本")).toBeInTheDocument();
    expect(screen.queryByText("目标为空")).not.toBeInTheDocument();
    expect(screen.getByRole("checkbox", { name: "选择 business-2026-08-01.csv" })).toBeDisabled();
  });

  it("requires the confirmation statement and submits only selected item IDs", async () => {
    const user = userEvent.setup(); renderPage();
    const start = await screen.findByRole("button", { name: "开始批量审核（1 项）" });
    expect(start).toBeDisabled();
    await user.click(screen.getByText("我已核对所选文件的报告日期和报表类型。"));
    await user.click(start);
    expect(mocks.confirm).toHaveBeenCalledWith(7, 3, [101]);
  });

  it("renders progress, pause, retry, manual review and ready-version actions", async () => {
    const progress = run({
      allowed_actions: ["pause", "retry"], status: "running", revision: 4,
      items: [
        item({ id: 101, status: "ready_for_publish", version_id: 51 }),
        item({ batch_id: 12, filename: "warning.csv", id: 102, reason_message: "完整校验包含警告。", status: "manual_review", version_id: 52 }),
        item({ batch_id: 13, filename: "retry.csv", id: 103, reason_message: "临时数据库繁忙。", retry_allowed: true, status: "failed" }),
      ],
      summary: { active: 0, eligible: 0, failed: 1, manual_review: 1, ready_for_publish: 1, skipped: 0, total: 3 },
    });
    mocks.getRun.mockResolvedValue(progress); mocks.retry.mockResolvedValue({ ...progress, revision: 5 });
    const user = userEvent.setup(); renderPage();
    expect(await screen.findByText("完整校验包含警告。")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "暂停批量处理" })).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "查看全部待发布草稿" })).toHaveAttribute("href", "/versions?batch_review_run_id=7");
    expect(screen.getByRole("link", { name: "处理异常" })).toHaveAttribute("href", "/review/2026-08-01?report_type=business_report&version_id=52");
    await user.click(screen.getByRole("button", { name: "重试" }));
    await waitFor(() => expect(mocks.retry).toHaveBeenCalledWith(7, 103, 4));
  });

  it.each([false, true])("restarts a retry without a status change after draining the previous pass (pending=%s)", async (pending) => {
    const failed = run({
      allowed_actions: ["pause", "retry"], status: "running", revision: 4,
      items: [item({ status: "failed", retry_allowed: true, reason_message: "可安全重试。" })],
    });
    const queued = { ...failed, revision: 5, items: [item({ status: "queued", recovery_available: true })] };
    let finishPrevious!: (snapshot: BatchReviewRun) => void;
    mocks.getRun.mockResolvedValue(failed);
    mocks.retry.mockImplementation(() => {
      mocks.getRun.mockResolvedValue(queued);
      return Promise.resolve(queued);
    });
    mocks.execute.mockImplementationOnce(() => pending
      ? new Promise<BatchReviewRun>((resolve) => { finishPrevious = resolve; })
      : Promise.resolve(failed));
    const user = userEvent.setup();
    renderPage();
    await user.click(await screen.findByRole("button", { name: "重试" }));
    await waitFor(() => expect(mocks.retry).toHaveBeenCalledWith(7, 101, 4));

    if (pending) {
      expect(mocks.execute).toHaveBeenCalledTimes(1);
      const options = mocks.execute.mock.calls[0]![3] as {
        signal: AbortSignal; onSnapshot: (snapshot: BatchReviewRun) => void;
        onItemResult: (result: { outcome: string; error: unknown }) => void;
      };
      expect(options.signal.aborted).toBe(true);
      await act(async () => {
        options.onSnapshot(failed);
        options.onItemResult({ outcome: "failed", error: new Error("stopped pass failure") });
        finishPrevious(failed);
        await Promise.resolve();
      });
    }

    await waitFor(() => expect(mocks.execute).toHaveBeenCalledTimes(2));
    expect(mocks.execute.mock.calls[1]![0]).toMatchObject({
      status: "running", revision: 5,
      items: [expect.objectContaining({ status: "queued", recovery_available: true })],
    });
    expect(screen.queryByRole("button", { name: "重试" })).not.toBeInTheDocument();
    expect(screen.queryByRole("alert")).not.toBeInTheDocument();
  });

  it("drains active work before resuming and ignores the stopped pass snapshot", async () => {
    const running = run({ allowed_actions: ["pause"], status: "running", revision: 4 });
    const paused = { ...running, allowed_actions: ["resume"], status: "paused", revision: 5 };
    const resumed = { ...running, revision: 6 };
    let finishPrevious!: (snapshot: BatchReviewRun) => void;
    mocks.getRun.mockResolvedValue(running);
    mocks.execute.mockImplementationOnce(() => new Promise<BatchReviewRun>((resolve) => { finishPrevious = resolve; }));
    mocks.pause.mockResolvedValue(paused);
    mocks.resume.mockImplementation(() => {
      mocks.getRun.mockResolvedValue(resumed);
      return Promise.resolve(resumed);
    });
    const user = userEvent.setup();
    renderPage();
    await waitFor(() => expect(mocks.execute).toHaveBeenCalledTimes(1));
    await user.click(screen.getByRole("button", { name: "暂停批量处理" }));
    await user.click(await screen.findByRole("button", { name: "恢复批量处理" }));
    await waitFor(() => expect(mocks.resume).toHaveBeenCalledWith(7, 5));
    expect(mocks.execute).toHaveBeenCalledTimes(1);
    await act(async () => {
      finishPrevious(paused);
      await Promise.resolve();
    });
    await waitFor(() => expect(mocks.execute).toHaveBeenCalledTimes(2));
    expect(mocks.execute.mock.calls[1]![0]).toMatchObject({ status: "running", revision: 6 });
    expect(screen.getByRole("button", { name: "暂停批量处理" })).toBeVisible();
  });

  it("shows executor failure while retaining the authoritative item state", async () => {
    const runtimeLog = vi.spyOn(console, "info").mockImplementation(() => undefined);
    const progress = run({ status: "running", items: [item({
      status: "queued", recovery_available: true,
    })] });
    mocks.getRun.mockResolvedValue(progress);
    mocks.execute.mockImplementation((
      snapshot: BatchReviewRun, _advance: unknown, _reload: unknown,
      options: { onItemResult: (result: { outcome: string; error: unknown }) => void; onEvent: (event: unknown) => void },
    ) => {
      options.onItemResult({ outcome: "failed", error: new Error("advance rejected") });
      options.onEvent({ component: "batch_review_executor", run_id: snapshot.id,
        stage: "pass", action: "complete_pass", execution_outcome: "completed_with_failure" });
      return Promise.resolve(snapshot);
    });

    renderPage();

    expect(await screen.findByRole("alert")).toHaveTextContent("advance rejected");
    expect(screen.getByText("business-2026-08-01.csv")).toBeVisible();
    expect(mocks.execute).toHaveBeenCalledTimes(1);
    expect(runtimeLog).toHaveBeenCalledWith("batch_review_runtime", expect.objectContaining({
      execution_outcome: "completed_with_failure", run_id: progress.id,
    }));
    runtimeLog.mockRestore();
  });
});

it("clears confirmation and ignores old responses when the task changes", async () => {
  let resolveOld!: (value: BatchReviewRun) => void;
  mocks.getRun.mockImplementation((id: number) => id === 8 ? new Promise<BatchReviewRun>(resolve=>{resolveOld=resolve;}) : Promise.resolve(run({id})));
  const user=userEvent.setup();
  const tree=(id: number)=><MemoryRouter><BatchReviewPage runId={id}/></MemoryRouter>;
  const view=render(tree(7));
  await user.click(await screen.findByText("我已核对所选文件的报告日期和报表类型。"));
  expect(screen.getByRole("button",{name:"开始批量审核（1 项）"})).toBeEnabled();
  view.rerender(tree(8));
  expect(screen.queryByRole("button",{name:"开始批量审核（1 项）"})).not.toBeInTheDocument();
  view.rerender(tree(9));
  expect(await screen.findByRole("button",{name:"开始批量审核（1 项）"})).toBeDisabled();
  await act(async()=>{resolveOld(run({id:8})); await Promise.resolve();});
  expect(screen.getByText("批量任务 #9")).toBeVisible();
  expect(screen.queryByText("批量任务 #8")).not.toBeInTheDocument();
});
