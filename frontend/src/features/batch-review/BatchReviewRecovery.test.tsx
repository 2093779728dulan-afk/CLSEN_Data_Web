import { render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";

import type { BatchReviewRun } from "./batchReviewTypes";

const mocks = vi.hoisted(() => ({
  advance: vi.fn(), confirm: vi.fn(), getRun: vi.fn(), pause: vi.fn(), resume: vi.fn(), retry: vi.fn(),
  execute: vi.fn(),
}));
vi.mock("./batchReviewApi", () => ({ BatchReviewApi: class {
  advance = mocks.advance; confirm = mocks.confirm; getRun = mocks.getRun;
  pause = mocks.pause; resume = mocks.resume; retry = mocks.retry;
} }));
vi.mock("./batchReviewExecutor", () => ({ runBatchReviewExecutor: mocks.execute }));

import { BatchReviewPage } from "./BatchReviewPage";

function recoveredRun(status: string, itemStatus: string, outcomeUnknown = false, recoveryAvailable = itemStatus === "queued"): BatchReviewRun {
  return {
    allowed_actions: status === "paused" ? ["resume"] : status === "running" ? ["pause"] : [],
    id: 9,
    items: [{
      attempt_count: 1, batch_id: 21, dataset_id: itemStatus === "validating" ? 31 : null,
      encoding: "utf-8", filename: "recovered.csv", id: 91, manual_review_url: "/review/2026-08-02?report_type=return_report",
      operation_token: "8b90d72f-69f8-42a7-b122-d691e9ad9001", outcome_unknown: outcomeUnknown,
      reason_code: null, reason_message: outcomeUnknown ? "正在确认服务器结果。" : null,
      recognition_status: "recognized", report_date: "2026-08-02", report_type: "return_report",
      recovery_available: recoveryAvailable, retry_allowed: false, selected: true, status: itemStatus, validation_run_id: null, version_id: null,
    }],
    revision: 4, status,
    summary: { active: ["queued", "parsing", "materializing", "validating"].includes(itemStatus) ? 1 : 0, eligible: 0, failed: itemStatus === "failed" ? 1 : 0, manual_review: 0, ready_for_publish: 0, skipped: 0, total: 1 },
  };
}

describe("BatchReviewPage recovery", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mocks.execute.mockImplementation((snapshot: BatchReviewRun) => Promise.resolve(snapshot));
  });

  it.each([
    ["running", "queued", false, true],
    ["paused", "queued", false, false],
    ["running", "validating", false, true],
    ["completed_with_exceptions", "failed", false, false],
    ["running", "validating", true, true],
  ])("restores %s / %s from GET without repeating confirmation", async (runStatus, itemStatus, outcomeUnknown, executes) => {
    const snapshot = recoveredRun(runStatus, itemStatus, outcomeUnknown, executes && runStatus === "running");
    mocks.getRun.mockResolvedValue(snapshot);
    render(<MemoryRouter><BatchReviewPage runId={9} /></MemoryRouter>);

    expect(await screen.findByText("recovered.csv")).toBeVisible();
    expect(mocks.getRun).toHaveBeenCalledWith(9);
    expect(mocks.confirm).not.toHaveBeenCalled();
    await waitFor(() => expect(mocks.execute.mock.calls.length > 0).toBe(executes));
    if (outcomeUnknown) expect(screen.getByText("正在确认服务器结果，请勿重复提交。")).toBeVisible();
  });
});
