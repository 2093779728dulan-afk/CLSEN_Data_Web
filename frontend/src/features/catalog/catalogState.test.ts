import { describe, expect, it } from "vitest";

import { exportViewState } from "./catalogState";

describe("catalog export state", () => {
  it("requires both export and workbook readiness", () => {
    expect(exportViewState().kind).toBe("idle");
    expect(exportViewState({
      base_catalog_version_id: null,
      capacity_violations: [],
      catalog_publication_revision: 0,
      export_id: 1,
      export_status: "ready",
      failure_reason_code: null,
      job_status: "succeeded",
      job_revision: 2,
      execution_phase: "completed",
      attempt_count: 1,
      max_attempts: 3,
      next_attempt_at: null,
      retry_allowed: false,
      worker_available: true,
      permissions: { can_download: true, can_resume: false },
      workbook_status: "ready",
    }).kind).toBe("ready");
  });
});
