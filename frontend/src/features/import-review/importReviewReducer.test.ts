import { describe, expect, it } from "vitest";

import type { ImportQueueItem } from "./workflowTypes";
import {
  importQueueItemStage,
  importReviewReducer,
  initialImportReviewState,
  selectActiveQueueItem,
} from "./importReviewReducer";

const inspection = {
  encoding: "utf-8-sig" as const,
  issue_codes: [],
  report_date: "2026-08-10",
  report_type: "business_report" as const,
  ruleset_version: "business_report_v1",
  status: "recognized" as const,
};

function item(id: string, batchId: number): ImportQueueItem {
  return {
    assignedDate: "2026-08-10",
    encoding: "utf-8-sig",
    id,
    inspection,
    reportType: "business_report",
    status: "ready",
    upload: { fileName: `${id}.csv`, upload: { batch_id: batchId } },
  };
}

describe("importReviewReducer", () => {
  it("keeps upload, inspection, and parse state on the target queue item", () => {
    let state = importReviewReducer(initialImportReviewState("2026-08-10"), {
      type: "replace-queue",
      items: [item("one", 11), item("two", 12)],
      activeQueueId: "one",
    });
    state = importReviewReducer(state, {
      type: "patch-active",
      changes: {
        parsed: {
          batch_id: 11,
          confirmation_revision: 1,
          parse_attempt_id: 21,
          parse_baseline_id: 31,
          report_type: "business_report",
          source_row_count: 2,
        },
      },
    });
    expect(importQueueItemStage(selectActiveQueueItem(state))).toBe("parsed");

    state = importReviewReducer(state, { type: "activate", id: "two" });
    expect(importQueueItemStage(selectActiveQueueItem(state))).toBe("inspection");
    expect(selectActiveQueueItem(state)?.parsed).toBeUndefined();
    expect(state.importQueue[0]?.parsed?.parse_baseline_id).toBe(31);
  });

  it("covers failed and published transitions without changing sibling items", () => {
    let state = importReviewReducer(initialImportReviewState("2026-08-10"), {
      type: "replace-queue",
      items: [item("one", 11), item("two", 12)],
      activeQueueId: "one",
    });
    state = importReviewReducer(state, { type: "patch-active", changes: { status: "failed" } });
    expect(importQueueItemStage(selectActiveQueueItem(state))).toBe("failed");
    state = importReviewReducer(state, { type: "patch-active", changes: { status: "completed" } });
    expect(importQueueItemStage(selectActiveQueueItem(state))).toBe("published");
    expect(state.importQueue[1]?.status).toBe("ready");
  });

  it("distinguishes an existing server batch from a failed upload", () => {
    const existing: ImportQueueItem = {
      assignedDate: "2026-07-05",
      encoding: "utf-8-sig",
      existing: {
        batchId: 92,
        reportDate: "2026-07-05",
        reportType: "return_report",
        stage: "uploaded",
        workspaceUrl: "/review/2026-07-05?report_type=return_report",
      },
      id: "existing",
      reportType: "return_report",
      status: "existing",
      upload: { fileName: "return.csv", upload: { batch_id: 92 } },
    };
    const state = importReviewReducer(initialImportReviewState("2026-08-16"), {
      type: "replace-queue",
      items: [existing],
    });

    expect(importQueueItemStage(state.importQueue[0])).toBe("existing");
  });
});
