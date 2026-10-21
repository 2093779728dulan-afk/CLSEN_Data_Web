import { spawnSync } from "node:child_process";
import { writeFileSync } from "node:fs";
import { fileURLToPath } from "node:url";

import { requireVisualBaselineApproval } from "./visualBaselineApproval.ts";
import { createVisualBaselineCommand } from "./visualBaselineCommand.ts";

const approval = requireVisualBaselineApproval(process.env);
const command = createVisualBaselineCommand();
const result = spawnSync(command.executable, command.args, {
  env: { ...process.env, STORYBOOK_VISUAL_BASELINE_UPDATE: "approved" },
  stdio: "inherit",
});

if (result.error) {
  console.error(`Unable to start the visual baseline runner: ${result.error.message}`);
  process.exit(1);
}
if (result.status !== 0) process.exit(result.status ?? 1);

const recordPath = fileURLToPath(new URL("../tests/storybook/visual-baseline-approval.json", import.meta.url));
writeFileSync(recordPath, `${JSON.stringify({
  approved_by: approval.approvedBy,
  reason: approval.reason,
  generated_at: new Date().toISOString(),
  font: "Noto Sans SC Variable 5.3.0",
  playwright: "1.62.1",
}, null, 2)}\n`, { encoding: "utf8" });
