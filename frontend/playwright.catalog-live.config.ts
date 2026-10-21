import { defineConfig, devices } from "@playwright/test";

const baseURL = process.env.CATALOG_LIVE_FRONTEND_URL ?? "http://127.0.0.1:1";
const outputDir = process.env.CATALOG_LIVE_PLAYWRIGHT_OUTPUT ?? "test-results/catalog-live";
const managerState = process.env.CATALOG_LIVE_MANAGER_STATE ?? "test-results/catalog-live-manager.json";

export default defineConfig({
  testDir: "./tests/e2e/live",
  fullyParallel: false,
  forbidOnly: true,
  globalSetup: "./tests/e2e/live/global-setup.ts",
  globalTeardown: "./tests/e2e/live/global-teardown.ts",
  outputDir,
  reporter: "list",
  retries: 0,
  workers: 1,
  use: {
    baseURL,
    screenshot: "only-on-failure",
    storageState: managerState,
    trace: "retain-on-failure",
  },
  projects: [
    {
      name: "catalog-milestone-a",
      testMatch: "catalog-milestone-a.live.spec.ts",
      use: { ...devices["Desktop Chrome"] },
    },
    {
      dependencies: ["catalog-milestone-a"],
      name: "product-milestone-b",
      testMatch: "product-analytics-milestone-b.live.spec.ts",
      use: { ...devices["Desktop Chrome"] },
    },
    {
      dependencies: ["product-milestone-b"],
      name: "product-cutover",
      testMatch: "product-analytics-cutover.live.spec.ts",
      use: { ...devices["Desktop Chrome"] },
    },
    {
      dependencies: ["product-cutover"],
      name: "product-release",
      testMatch: "product-catalog-release.live.spec.ts",
      use: { ...devices["Desktop Chrome"] },
    },
    {
      name: "product-cutover-legacy-before",
      testMatch: "product-analytics-cutover.live.spec.ts",
      use: { ...devices["Desktop Chrome"] },
    },
    {
      name: "product-cutover-legacy-rollback",
      testMatch: "product-analytics-cutover.live.spec.ts",
      use: { ...devices["Desktop Chrome"] },
    },
  ],
});
