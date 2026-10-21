export type VisualBaselineApproval = {
  approvedBy: string;
  reason: string;
};

type ApprovalEnvironment = Record<string, string | undefined>;

export function requireVisualBaselineApproval(environment: ApprovalEnvironment): VisualBaselineApproval {
  if (environment.CI?.trim().toLowerCase() === "true") {
    throw new Error("Visual baseline updates must not run in CI.");
  }

  const approvedBy = environment.VISUAL_BASELINE_APPROVED_BY?.trim();
  if (!approvedBy) throw new Error("VISUAL_BASELINE_APPROVED_BY is required.");

  const reason = environment.VISUAL_BASELINE_REASON?.trim();
  if (!reason) throw new Error("VISUAL_BASELINE_REASON is required.");
  if ([...reason].length < 8) throw new Error("VISUAL_BASELINE_REASON must be at least 8 characters.");

  return { approvedBy, reason };
}
