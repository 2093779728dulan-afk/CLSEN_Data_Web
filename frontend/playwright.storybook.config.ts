import { defineConfig, devices } from "@playwright/test";

const port = process.env.STORYBOOK_TEST_PORT ?? "6006";
const baseURL = `http://127.0.0.1:${port}`;

export default defineConfig({
  testDir: "./tests/storybook",
  fullyParallel: false,
  forbidOnly: Boolean(process.env.CI),
  retries: 0,
  workers: 1,
  reporter: process.env.CI ? "github" : "list",
  snapshotPathTemplate: "{testDir}/__screenshots__/{arg}{ext}",
  expect: {
    toHaveScreenshot: {
      animations: "disabled",
      caret: "hide",
      maxDiffPixelRatio: 0.01,
      scale: "css",
      threshold: 0.2,
    },
  },
  use: {
    ...devices["Desktop Chrome"],
    baseURL,
    colorScheme: "light",
    deviceScaleFactor: 1,
    locale: "zh-CN",
    screenshot: "only-on-failure",
    timezoneId: "Asia/Shanghai",
    trace: "retain-on-failure",
    viewport: { width: 1280, height: 900 },
  },
  projects: [{ name: "chromium" }],
  webServer: {
    command: `pnpm exec storybook dev --ci --host 127.0.0.1 --port ${port}`,
    env: {
      ...process.env,
      VITE_PRODUCT_ANALYTICS_SOURCE: process.env.VITE_PRODUCT_ANALYTICS_SOURCE ?? "legacy_parser",
    },
    reuseExistingServer: !process.env.CI,
    timeout: 120_000,
    url: baseURL,
  },
});
