import { spawnSync } from "node:child_process";
import { createHash } from "node:crypto";
import { closeSync, openSync, readdirSync, realpathSync, rmSync, statSync, writeFileSync } from "node:fs";
import path from "node:path";
import { performance } from "node:perf_hooks";
import { fileURLToPath } from "node:url";

const runDirectory = process.env.APP_PROJECT_OPTIMIZATION_RUN_DIR;
const sourceSha = process.env.APP_RELEASE_SOURCE_SHA;
if (!runDirectory || !path.isAbsolute(runDirectory) || !/^[0-9a-f]{40}$/.test(sourceSha ?? "")) throw new Error("external run directory and exact source SHA are required");

const repositoryRoot = realpathSync.native(path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..", ".."));
const resolvedRunDirectory = realpathSync.native(runDirectory);
const comparable = (value) => process.platform === "win32" ? value.toLowerCase() : value;
const relativeRunDirectory = path.relative(comparable(repositoryRoot), comparable(resolvedRunDirectory));
if (relativeRunDirectory === "" || (!relativeRunDirectory.startsWith(`..${path.sep}`) && relativeRunDirectory !== ".." && !path.isAbsolute(relativeRunDirectory))) throw new Error("run directory must be outside the repository");

const pnpm = process.platform === "win32" ? "pnpm.cmd" : "pnpm";

function files(root) {
  return readdirSync(root, { withFileTypes: true }).flatMap((entry) => {
    const value = path.join(root, entry.name);
    return entry.isDirectory() ? files(value) : [value];
  });
}

function build(source) {
  rmSync("dist", { recursive: true, force: true });
  const started = performance.now();
  const result = spawnSync(pnpm, ["build"], {
    encoding: "utf8",
    env: { ...process.env, VITE_PRODUCT_ANALYTICS_SOURCE: source },
    shell: process.platform === "win32",
  });
  const build_ms = performance.now() - started;
  if (result.status !== 0) throw new Error(`bundle build failed for ${source}: ${result.stderr ?? result.error?.message ?? "unknown error"}`);
  const artifacts = files("dist").filter((file) => /\.(js|css)$/.test(file));
  return {
    build_ms,
    bundle_bytes: artifacts.reduce((total, file) => total + statSync(file).size, 0),
    artifact_digest: createHash("sha256").update(artifacts.sort().map((file) => `${path.relative("dist", file)}:${statSync(file).size}`).join("\n")).digest("hex"),
  };
}

function summarize(values) {
  const ordered = [...values].sort((a, b) => a - b);
  return { sample_count: 20, samples: values, p50: (ordered[9] + ordered[10]) / 2, p95: ordered[18], max: ordered[19] };
}

for (const source of ["legacy_parser", "p0_catalog"]) {
  const rounds = [];
  for (let round = 0; round < 3; round += 1) {
    for (let warmup = 0; warmup < 3; warmup += 1) build(source);
    const measurements = Array.from({ length: 20 }, () => build(source));
    rounds.push({
      ...summarize(measurements.map((row) => row.bundle_bytes)),
      build_ms_samples: measurements.map((row) => row.build_ms),
      artifact_digests: [...new Set(measurements.map((row) => row.artifact_digest))],
    });
  }
  const payload = { schema_version: 1, source_sha: sourceSha, scenario_id: `frontend-bundle-${source}`, unit: "bytes", warmup_samples: 3, measured_samples: 20, round_count: 3, rounds };
  const output = path.join(resolvedRunDirectory, `bundle-${source}.json`);
  const descriptor = openSync(output, "wx", 0o600);
  try { writeFileSync(descriptor, JSON.stringify(payload, null, 2) + "\n", "utf8"); } finally { closeSync(descriptor); }
}
