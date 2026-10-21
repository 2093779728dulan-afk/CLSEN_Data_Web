import { resolve } from "node:path";

export function createVisualBaselineCommand(
  nodeExecutable = process.execPath,
  workingDirectory = process.cwd(),
  storyFilter?: string,
) {
  return {
    executable: nodeExecutable,
    args: [
      resolve(workingDirectory, "node_modules/@playwright/test/cli.js"),
      "test",
      "--config",
      "playwright.storybook.config.ts",
      "tests/storybook/visual.spec.ts",
      "--update-snapshots",
      ...(storyFilter ? ["--grep", storyFilter] : []),
    ],
  };
}
