import { describe, expect, it } from "vitest";

import { workflowLabel } from "./catalogImportState";

describe("catalog workflow labels", () => {
  it("labels approval and attention states", () => {
    const base = { status: "ready_for_approval" } as Parameters<typeof workflowLabel>[0];
    expect(workflowLabel(base)).toBe("等待批准");
    expect(workflowLabel({ ...base, status: "needs_attention" })).toBe("需要处理");
  });
});
