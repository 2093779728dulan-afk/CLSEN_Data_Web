import { defineConfig, devices } from "@playwright/test";

const port = process.env.PLAYWRIGHT_PORT ?? "5173";
const baseURL = `http://127.0.0.1:${port}`;

export default defineConfig({
  testDir: "./tests/e2e",
  testIgnore: ["**/live/**", "**/*.live.spec.ts", "**/project-optimization-baseline.spec.ts"],
  fullyParallel: false,
  forbidOnly: Boolean(process.env.CI),
  retries: process.env.CI ? 2 : 0,
  reporter: process.env.CI ? "github" : "list",
  use: {
    baseURL,
    screenshot: "only-on-failure",
    trace: "retain-on-failure",
  },
  projects: [
    {
      name: "chromium",
      use: { ...devices["Desktop Chrome"] },
    },
  ],
  webServer: {
    command: `pnpm dev --host 127.0.0.1 --port ${port} --strictPort`,
    env: {
      ...process.env,
      VITE_PRODUCT_ANALYTICS_SOURCE: process.env.VITE_PRODUCT_ANALYTICS_SOURCE ?? "p0_catalog",
    },
    reuseExistingServer: !process.env.CI && process.env.PLAYWRIGHT_CUTOVER_RUN !== "1",
    timeout: 120_000,
    url: baseURL,
  },
});
