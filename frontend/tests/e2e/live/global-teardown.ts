import { rm, writeFile } from "node:fs/promises";
import { resolve } from "node:path";

function required(name: string): string {
  const value = process.env[name];
  if (!value) throw new Error(`${name} is required by the catalog live runner.`);
  return value;
}

function assertOwned(pathValue: string): string {
  const root = resolve(required("CATALOG_LIVE_RUNTIME_ROOT"));
  const candidate = resolve(pathValue);
  if (candidate === root || !candidate.startsWith(`${root}\\`)) {
    throw new Error("Catalog live teardown path is outside the runner-owned root.");
  }
  return candidate;
}

export default async function globalTeardown() {
  if (process.env.CATALOG_LIVE_KEEP_STATES === "1") return;
  for (const name of ["CATALOG_LIVE_ADMIN_STATE", "CATALOG_LIVE_MANAGER_STATE", "CATALOG_LIVE_VIEWER_STATE"]) {
    await rm(assertOwned(required(name)), { force: true });
  }
  await writeFile(
    assertOwned(required("CATALOG_LIVE_TEARDOWN_MARKER")),
    JSON.stringify({ cleanup: "storage_states_removed", run_id: required("CATALOG_LIVE_RUN_ID") }),
    { encoding: "utf8", mode: 0o600 },
  );
}
