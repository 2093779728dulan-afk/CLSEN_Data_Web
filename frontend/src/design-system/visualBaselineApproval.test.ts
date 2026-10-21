import { describe, expect, it } from "vitest";

import { requireVisualBaselineApproval } from "../../scripts/visualBaselineApproval";
import { createVisualBaselineCommand } from "../../scripts/visualBaselineCommand";

describe("visual baseline approval", () => {
  it("rejects automated baseline acceptance", () => {
    expect(() => requireVisualBaselineApproval({
      CI: "true",
      VISUAL_BASELINE_APPROVED_BY: "项目负责人",
      VISUAL_BASELINE_REASON: "批准初始组件基线",
    })).toThrow("must not run in CI");
  });

  it("requires both a reviewer and a meaningful reason", () => {
    expect(() => requireVisualBaselineApproval({ VISUAL_BASELINE_APPROVED_BY: "项目负责人" }))
      .toThrow("VISUAL_BASELINE_REASON");
    expect(() => requireVisualBaselineApproval({
      VISUAL_BASELINE_APPROVED_BY: "项目负责人",
      VISUAL_BASELINE_REASON: "短",
    })).toThrow("at least 8 characters");
  });

  it("returns normalized approval metadata", () => {
    expect(requireVisualBaselineApproval({
      VISUAL_BASELINE_APPROVED_BY: "  项目负责人  ",
      VISUAL_BASELINE_REASON: "  批准初始组件视觉基线  ",
    })).toEqual({ approvedBy: "项目负责人", reason: "批准初始组件视觉基线" });
  });
});

describe("visual baseline command", () => {
  it("limits an incremental update to the selected stories", () => {
    expect(createVisualBaselineCommand("node", ".", "pages-catalog-import-review").args.slice(-2))
      .toEqual(["--grep", "pages-catalog-import-review"]);
  });
  it("uses the current Node runtime instead of spawning a Windows command shim", () => {
    const command = createVisualBaselineCommand("C:\\runtime\\node.exe", "C:\\project\\frontend");

    expect(command.executable).toBe("C:\\runtime\\node.exe");
    expect(command.args[0]).toMatch(/@playwright[\\/]test[\\/]cli\.js$/);
    expect(command.args).not.toContain("pnpm.cmd");
  });
});
