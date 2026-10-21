import { afterEach, describe, expect, it } from "vitest";

import { initialImportReviewState } from "./importReviewReducer";
import {
  REVIEW_RECOVERY_SCHEMA_VERSION,
  clearReviewRecoveryForIdentity,
  decodeReviewRecovery,
  loadReviewRecovery,
  reviewRecoveryKey,
  saveReviewRecovery,
} from "./reviewRecovery";

const identity = { reportDate: "2026-08-10", siteId: 7, userId: 9 };
const recovery = {
  materializeReason: "核对后生成",
  noteBatchIds: [],
  reviewState: initialImportReviewState(identity.reportDate),
};

afterEach(() => sessionStorage.clear());

describe("reviewRecovery", () => {
  it("includes schema, site, user, and report date in the storage key", () => {
    expect(reviewRecoveryKey(identity)).toBe(
      `clsen:review-flow:v${REVIEW_RECOVERY_SCHEMA_VERSION}:site:7:user:9:date:2026-08-10`,
    );
  });

  it("round-trips only deeply valid state for the same identity", () => {
    saveReviewRecovery(identity, recovery);
    expect(loadReviewRecovery(identity)).toEqual(recovery);
    const raw = sessionStorage.getItem(reviewRecoveryKey(identity));
    expect(raw).not.toBeNull();
    expect(decodeReviewRecovery(raw as string, { ...identity, userId: 10 })).toBeUndefined();
  });

  it("round-trips an existing server batch with safe continuation metadata", () => {
    const withExisting = {
      ...recovery,
      reviewState: {
        ...recovery.reviewState,
        importQueue: [{
          assignedDate: "2026-07-05",
          encoding: "utf-8-sig" as const,
          existing: {
            batchId: 92,
            reportDate: "2026-07-05",
            reportType: "return_report" as const,
            stage: "uploaded",
            workspaceUrl: "/review/2026-07-05?report_type=return_report",
          },
          id: "existing-92",
          reportType: "return_report" as const,
          status: "existing" as const,
          upload: { fileName: "return.csv", upload: { batch_id: 92 } },
        }],
      },
    };

    saveReviewRecovery(identity, withExisting);
    expect(loadReviewRecovery(identity)).toEqual(withExisting);
  });

  it.each([
    "not-json",
    JSON.stringify({ ...recovery, ...identity, schemaVersion: 2 }),
    JSON.stringify({ ...recovery, ...identity, schemaVersion: REVIEW_RECOVERY_SCHEMA_VERSION, reviewState: { ...recovery.reviewState, intake: { ...recovery.reviewState.intake, encoding: "bad" } } }),
    JSON.stringify({ ...recovery, ...identity, schemaVersion: REVIEW_RECOVERY_SCHEMA_VERSION, reviewState: { ...recovery.reviewState, activeQueueId: "missing" } }),
    JSON.stringify({ ...recovery, ...identity, schemaVersion: REVIEW_RECOVERY_SCHEMA_VERSION, reviewState: { ...recovery.reviewState, importQueue: [{ id: "same" }, { id: "same" }] } }),
  ])("rejects corrupt, old, or incomplete recovery payloads", (raw) => {
    expect(decodeReviewRecovery(raw, identity)).toBeUndefined();
  });

  it("clears only recovery keys for the current site and user", () => {
    saveReviewRecovery(identity, recovery);
    saveReviewRecovery({ ...identity, reportDate: "2026-08-11" }, recovery);
    saveReviewRecovery({ ...identity, userId: 10 }, recovery);
    sessionStorage.setItem("another-app", "keep");

    clearReviewRecoveryForIdentity(7, 9);

    expect(sessionStorage.getItem(reviewRecoveryKey(identity))).toBeNull();
    expect(sessionStorage.getItem(reviewRecoveryKey({ ...identity, userId: 10 }))).not.toBeNull();
    expect(sessionStorage.getItem("another-app")).toBe("keep");
  });
});
