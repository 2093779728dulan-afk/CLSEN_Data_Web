import { existsSync, readFileSync } from "node:fs";
import path from "node:path";
import { mergeConfig } from "vitest/config";
import base from "../vitest.config";

const source = path.resolve("src").replaceAll("\\", "/") + "/";
const before = "D:/CLSEN_DeploymentPrep_20260914/order-warehouse-unify-20261026/blank-full-flow-20261106/verification/packing-full-flow-20261110/date-transport-fix-20261113/before/B/frontend/src";
export default mergeConfig(base, { plugins: [{ name: "task-before-source", enforce: "pre", load(id: string) {
  const filename = id.replaceAll("\\", "/").split("?")[0]!;
  if (!filename.startsWith(source)) return null;
  const snapshot = path.join(before, filename.slice(source.length));
  return existsSync(snapshot) ? readFileSync(snapshot, "utf8") : null;
} }] });
