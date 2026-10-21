import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { defineConfig, devices } from "@playwright/test";

const outputDir = process.env.APP_PROJECT_OPTIMIZATION_RUN_DIR;
const sourceSha = process.env.APP_RELEASE_SOURCE_SHA;
const repositoryRoot = fs.realpathSync.native(path.resolve(path.dirname(fileURLToPath(import.meta.url)), ".."));

function isRepositoryPath(candidate: string): boolean {
  const root = process.platform === "win32" ? repositoryRoot.toLowerCase() : repositoryRoot;
  const target = process.platform === "win32" ? candidate.toLowerCase() : candidate;
  const relative = path.relative(root, target);
  return relative === "" || (!relative.startsWith(`..${path.sep}`) && relative !== ".." && !path.isAbsolute(relative));
}

if (!outputDir || !path.isAbsolute(outputDir)) throw new Error("APP_PROJECT_OPTIMIZATION_RUN_DIR must be an absolute external path");
const resolvedOutputDir = fs.realpathSync.native(outputDir);
if (isRepositoryPath(resolvedOutputDir)) throw new Error("APP_PROJECT_OPTIMIZATION_RUN_DIR must be outside the repository");
if (!/^[0-9a-f]{40}$/.test(sourceSha ?? "")) throw new Error("APP_RELEASE_SOURCE_SHA must be an exact lowercase SHA");
const port = process.env.PLAYWRIGHT_PORT ?? "5173";

export default defineConfig({
  testDir: "./tests/e2e",
  testMatch: "project-optimization-baseline.spec.ts",
  fullyParallel: false,
  forbidOnly: true,
  retries: 0,
  workers: 1,
  reporter: [["list"], ["json", { outputFile: path.join(resolvedOutputDir, "playwright-report.json") }]],
  outputDir: path.join(resolvedOutputDir, "playwright-artifacts"),
  use: {
    ...devices["Desktop Chrome"],
    baseURL: `http://127.0.0.1:${port}`,
    locale: "zh-CN",
    timezoneId: "Asia/Shanghai",
    viewport: { width: 1440, height: 900 },
    deviceScaleFactor: 1,
    colorScheme: "light",
    reducedMotion: "reduce",
    screenshot: "off",
    trace: "off",
    video: "off",
  },
  webServer: {
    command: `pnpm dev --host 127.0.0.1 --port ${port} --strictPort`,
    env: { ...process.env, VITE_PRODUCT_ANALYTICS_SOURCE: "p0_catalog" },
    reuseExistingServer: false,
    timeout: 120_000,
    url: `http://127.0.0.1:${port}`,
  },
});
