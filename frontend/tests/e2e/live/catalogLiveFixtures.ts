import { execFile } from "node:child_process";
import { createHash } from "node:crypto";
import { readFile, writeFile } from "node:fs/promises";
import { resolve } from "node:path";
import { promisify } from "node:util";

import { test as base, type APIRequestContext, type Page } from "@playwright/test";

const execFileAsync = promisify(execFile);

export function requiredEnv(name: string): string {
  const value = process.env[name];
  if (!value) throw new Error(`${name} is required by the catalog live runner.`);
  return value;
}

function ownedPath(pathValue: string): string {
  const root = resolve(requiredEnv("CATALOG_LIVE_RUNTIME_ROOT"));
  const candidate = resolve(pathValue);
  if (candidate === root || !candidate.startsWith(`${root}\\`)) {
    throw new Error("Catalog live fixture path is outside the runner-owned root.");
  }
  return candidate;
}

export async function sha256File(pathValue: string): Promise<string> {
  return createHash("sha256").update(await readFile(pathValue)).digest("hex");
}

export async function mutateWorkbookEField(inputPath: string, outputPath: string) {
  const python = requiredEnv("CATALOG_LIVE_PYTHON");
  const backend = requiredEnv("CATALOG_LIVE_BACKEND_DIR");
  await execFileAsync(python, [
    "-m",
    "tests.live.product_catalog_live_harness",
    "--run-id",
    requiredEnv("CATALOG_LIVE_RUN_ID"),
    "--manifest",
    requiredEnv("CATALOG_LIVE_MANIFEST"),
    "mutate-workbook",
    "--input",
    ownedPath(inputPath),
    "--output",
    ownedPath(outputPath),
  ], { cwd: backend, windowsHide: true });
}

export async function saveLiveResult(value: Record<string, unknown>) {
  await writeFile(
    ownedPath(requiredEnv("CATALOG_LIVE_RESULT_PATH")),
    JSON.stringify(value, null, 2),
    { encoding: "utf8", mode: 0o600 },
  );
}

type CatalogLiveFixtures = {
  adminPage: Page;
  viewerPage: Page;
  viewerRequest: APIRequestContext;
};

export const test = base.extend<CatalogLiveFixtures>({
  adminPage: async ({ browser }, provide) => {
    const context = await browser.newContext({
      baseURL: requiredEnv("CATALOG_LIVE_FRONTEND_URL"),
      storageState: requiredEnv("CATALOG_LIVE_ADMIN_STATE"),
    });
    try {
      await provide(await context.newPage());
    } finally {
      await context.close();
    }
  },
  viewerPage: async ({ browser }, provide) => {
    const context = await browser.newContext({
      baseURL: requiredEnv("CATALOG_LIVE_FRONTEND_URL"),
      storageState: requiredEnv("CATALOG_LIVE_VIEWER_STATE"),
    });
    try {
      await provide(await context.newPage());
    } finally {
      await context.close();
    }
  },
  viewerRequest: async ({ playwright }, provide) => {
    const context = await playwright.request.newContext({
      baseURL: requiredEnv("CATALOG_LIVE_FRONTEND_URL"),
      storageState: requiredEnv("CATALOG_LIVE_VIEWER_STATE"),
    });
    try {
      await provide(context);
    } finally {
      await context.dispose();
    }
  },
});

export { expect } from "@playwright/test";
