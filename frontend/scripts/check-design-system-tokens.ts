import { readFileSync, readdirSync } from "node:fs";
import { relative, resolve } from "node:path";

import { checkTokenPolicy, type TokenPolicyAllowlist } from "./tokenPolicy.ts";

const root = process.cwd();
const designSystemDirectory = resolve(root, "src/design-system");
const allowlistPath = resolve(designSystemDirectory, "token-policy-allowlist.json");
const allowlist = JSON.parse(readFileSync(allowlistPath, "utf8")) as TokenPolicyAllowlist;
const sources = readdirSync(designSystemDirectory, { withFileTypes: true })
  .filter((entry) => entry.isFile() && entry.name.endsWith(".module.css"))
  .map((entry) => {
    const path = resolve(designSystemDirectory, entry.name);
    return { path: relative(root, path), content: readFileSync(path, "utf8") };
  });

const violations = checkTokenPolicy(sources, allowlist);
if (violations.length > 0) {
  for (const violation of violations) {
    console.error(`${violation.file}:${violation.line} ${violation.rule}: ${violation.value}`);
  }
  process.exit(1);
}

console.log(`Token policy passed (${sources.length} CSS Modules, ${allowlist.exceptions.length} approved exceptions).`);
