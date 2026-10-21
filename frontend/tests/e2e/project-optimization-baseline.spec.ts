import { promises as fs } from "node:fs";
import path from "node:path";
import { performance } from "node:perf_hooks";
import { expect, test, type Page, type Route, type TestInfo } from "@playwright/test";

type UiScenarioId = "dashboard-load" | "batch-review-confirm" | "admin-maintenance-load" | "product-chart-load";
type SampleRound = { samples_ms: number[]; p50_ms: number; p95_ms: number; max_ms: number };
type Role = "admin" | "data_manager" | "viewer";

const csrfToken = "baseline-csrf-token";
const batchReviewId = 42;
const sourceSha = process.env.APP_RELEASE_SOURCE_SHA;

if (!/^[0-9a-f]{40}$/.test(sourceSha ?? "")) throw new Error("APP_RELEASE_SOURCE_SHA must be an exact lowercase SHA");

const percentile = (samples: number[], ratio: number) => [...samples].sort((a, b) => a - b)[Math.max(0, Math.ceil(samples.length * ratio) - 1)]!;
const summarize = (samples_ms: number[]): SampleRound => {
  const ordered = [...samples_ms].sort((a, b) => a - b);
  return { samples_ms, p50_ms: (ordered[9]! + ordered[10]!) / 2, p95_ms: percentile(samples_ms, 0.95), max_ms: Math.max(...samples_ms) };
};

function json(route: Route, payload: unknown, status = 200): Promise<void> {
  return route.fulfill({ body: JSON.stringify(payload), contentType: "application/json", status });
}

function unhandledBaselineRequest(route: Route): Promise<void> {
  const { pathname } = new URL(route.request().url());
  return json(route, { error: { code: "unhandled_baseline_request", message: `${route.request().method()} ${pathname}`, request_id: "baseline" } }, 500);
}

async function measureUiScenario(page: Page, scenarioId: UiScenarioId, operation: () => Promise<void>): Promise<SampleRound[]> {
  void page;
  const rounds: SampleRound[] = [];
  for (let round = 0; round < 3; round += 1) {
    for (let warmup = 0; warmup < 3; warmup += 1) await operation();
    const samples: number[] = [];
    for (let sample = 0; sample < 20; sample += 1) {
      const started = performance.now();
      await operation();
      const finished = performance.now();
      samples.push(finished - started);
    }
    rounds.push(summarize(samples));
  }
  test.info().annotations.push({ type: "scenario", description: scenarioId });
  return rounds;
}

async function writeUiEvidence(testInfo: TestInfo, scenarioId: UiScenarioId, rounds: SampleRound[], browserVersion: string): Promise<void> {
  const runDir = process.env.APP_PROJECT_OPTIMIZATION_RUN_DIR!;
  const target = path.join(runDir, `ui-${scenarioId}.json`);
  const handle = await fs.open(target, "wx", 0o600);
  try {
    const serializedRounds = rounds.map((round) => {
      const samples = round.samples_ms;
      const ordered = [...samples].sort((a, b) => a - b);
      return { sample_count: samples.length, samples, p50: (ordered[9]! + ordered[10]!) / 2, p95: percentile(samples, 0.95), max: Math.max(...samples) };
    });
    await handle.writeFile(JSON.stringify({ schema_version: 1, source_sha: sourceSha, scenario_id: `ui-${scenarioId}`, unit: "ms", warmup_samples: 3, measured_samples: 20, round_count: 3, rounds: serializedRounds, browser_name: "chromium", browser_version: browserVersion, viewport: { width: 1440, height: 900 }, locale: "zh-CN", timezone: "Asia/Shanghai", retries: 0 }, null, 2) + "\n", "utf8");
  } finally {
    await handle.close();
  }
  await testInfo.attach(`${scenarioId}-summary`, { body: Buffer.from(JSON.stringify(rounds)), contentType: "application/json" });
}

async function installSyntheticBootstrap(page: Page, roles: Role[]): Promise<void> {
  await page.context().route((url) => url.hostname !== "127.0.0.1", (route) => route.abort());
  await page.route((url) => url.pathname.startsWith("/api/"), async (route) => {
    const { pathname } = new URL(route.request().url());
    if (pathname === "/api/auth/me" && route.request().method() === "GET") return json(route, { id: 3, username: "baseline-user", display_name: "基线用户", roles });
    if (pathname === "/api/data-calendar/site-context" && route.request().method() === "GET") return json(route, { site_id: 1, site_code: "amazon_us", display_name: "Amazon US", site_config_version_id: 1, source_timezone: "America/Los_Angeles", reporting_timezone: "America/Los_Angeles", currency_code: "USD" });
    return unhandledBaselineRequest(route);
  });
}

async function installDashboardApi(page: Page): Promise<void> {
  const daily = { publications: [], range: { from_date: "2026-08-01", to_date: "2026-08-31" }, rows: [{ business_status: "published", conversion_rate: "0.1", counts_as_incomplete: true, overall_status: "partial", pending_summary: "退货报告缺失", reasons: [], report_date: "2026-08-24", return_quantity: null, return_status: "missing", sales: "120.25", sessions: 60, units_ordered: 6 }], site_config_versions: [] };
  await page.route((url) => url.pathname.startsWith("/api/dashboard/daily-ledger"), (route) => route.request().method() === "GET" ? json(route, daily) : unhandledBaselineRequest(route));
}

function makeBatchItem(index: number) {
  return { attempt_count: 0, batch_id: 100 + index, dataset_id: null, encoding: "utf-8-sig", filename: `synthetic-${String(index).padStart(3, "0")}.csv`, id: 200 + index, manual_review_url: `/review/2026-08-${String(index).padStart(2, "0")}?report_type=business_report`, operation_token: null, outcome_unknown: false, reason_code: null, reason_message: "可安全推进至待发布。", recognition_status: "recognized", report_date: `2026-08-${String(index).padStart(2, "0")}`, report_type: "business_report", retry_allowed: false, selected: true, status: "eligible", validation_run_id: null, version_id: null };
}

async function installSyntheticBatchReview(page: Page): Promise<{ reset(): void }> {
  let items = Array.from({ length: 6 }, (_, index) => makeBatchItem(index + 1));
  let status = "preview";
  let revision = 0;
  const reset = () => { items = Array.from({ length: 6 }, (_, index) => makeBatchItem(index + 1)); status = "preview"; revision = 0; };
  const snapshot = () => ({ allowed_actions: status === "preview" ? ["confirm"] : status === "running" ? ["pause"] : [], id: batchReviewId, items, revision, status, summary: { active: items.filter((item) => ["queued", "parsing", "materializing", "validating"].includes(item.status)).length, eligible: items.filter((item) => item.status === "eligible").length, failed: 0, manual_review: 0, ready_for_publish: 0, skipped: 0, total: items.length } });
  await page.context().addCookies([{ name: "clsen_csrf", sameSite: "Lax", url: "http://127.0.0.1:5173", value: csrfToken }]);
  await page.route((url) => url.pathname.startsWith(`/api/imports/batch-reviews/${batchReviewId}`) || (url.pathname === "/api/versions" && url.searchParams.get("batch_review_run_id") === String(batchReviewId)), async (route) => {
    const request = route.request();
    const { pathname } = new URL(request.url());
    if (pathname === `/api/imports/batch-reviews/${batchReviewId}` && request.method() === "GET") return json(route, snapshot());
    if (pathname === `/api/imports/batch-reviews/${batchReviewId}/confirm` && request.method() === "POST") {
      expect(request.headers()["x-csrf-token"]).toBe(csrfToken);
      expect(request.headers()["idempotency-key"]).toMatch(/^[0-9a-f-]{36}$/i);
      const body = request.postDataJSON() as { confirmation_accepted: boolean; confirmation_statement_version: string; expected_revision: number; selected_item_ids: number[] };
      expect(body).toMatchObject({ confirmation_accepted: true, confirmation_statement_version: "batch-review-confirmation-v1", expected_revision: 0 });
      items = items.map((item) => ({ ...item, status: body.selected_item_ids.includes(item.id) ? "queued" : "skipped" }));
      status = "running"; revision += 1;
      return json(route, snapshot());
    }
    if (pathname === `/api/imports/batch-reviews/${batchReviewId}/pause` && request.method() === "POST") { status = "paused"; revision += 1; return json(route, snapshot()); }
    if (pathname === "/api/versions" && request.method() === "GET") return json(route, []);
    return unhandledBaselineRequest(route);
  });
  return { reset };
}

async function installMaintenanceApi(page: Page): Promise<void> {
  const userRecord = { id: 2, username: "operator", display_name: "数据审核员", email: "operator@example.com", status: "active", roles: ["data_manager"], last_login_at: null, created_at: "2026-08-01T01:00:00Z", updated_at: "2026-08-10T01:00:00Z" };
  const siteConfig = { id: 1, site_id: 1, site_code: "amazon_us", site_display_name: "Amazon US", version_number: 1, source_timezone: "America/Los_Angeles", reporting_timezone: "America/Los_Angeles", currency_code: "USD", effective_at: "2026-08-01T00:00:00Z", change_reason: "初始配置", created_by_user_id: 1, created_at: "2026-08-01T00:00:00Z", is_current: true };
  const queueBase = { query_health: "healthy", consumer_health: "not_observed", failure_code: null, native_status_counts: {}, actionable: 0, in_flight: 0, retry_wait: null, stale: null, stuck: null, failed: 0, unresolved_building: null, oldest_work_at: null, next_retry_at: null, last_succeeded_at: null, last_failed_at: null, consecutive_failures: null };
  const maintenance = { backups: [{ id: 7, backup_uuid: "0123456789abcdef0123456789abcdef", status: "succeeded", database_name: "clsen_data_test", schema_revision: "0018", key_id: "local-20260811", raw_file_count: 4, publication_count: 2, version_count: 8, audit_event_count: 12, started_at: "2026-08-11T05:00:00Z", sealed_at: "2026-08-11T05:00:01Z", completed_at: "2026-08-11T05:00:02Z", failure_code: null, restore_verified_at: "2026-08-11T05:10:00Z" }], restores: [], outbox: { pending: 1, processing: 0, completed: 3, failed: 0, oldest_pending_at: "2026-08-11T05:11:00Z" }, write_lock: { held: false, owner_connection_id: null, observed_seconds: 0, warning: false }, observed_at: "2026-09-04T08:00:00Z", maintenance_active: false, worker: { query_health: "healthy", failure_code: null, thresholds: { heartbeat_seconds: 10, stale_seconds: 30, offline_seconds: 60, refresh_seconds: 15 }, instances: [] }, queues: [{ ...queueBase, queue_name: "return_dedup", capabilities: { actionable: true, in_flight: true, retry_wait: false, stale: true, stuck: false } }, { ...queueBase, queue_name: "publication_outbox", retry_wait: 0, stale: 0, capabilities: { actionable: true, in_flight: true, retry_wait: true, stale: true, stuck: false } }, { ...queueBase, queue_name: "catalog_export", actionable: null, in_flight: null, unresolved_building: 0, capabilities: { actionable: false, in_flight: false, retry_wait: false, stale: false, stuck: false } }, { ...queueBase, queue_name: "catalog_import", stuck: 0, capabilities: { actionable: true, in_flight: true, retry_wait: false, stale: false, stuck: true } }] };
  await page.route((url) => url.pathname.startsWith("/api/admin/"), async (route) => {
    const { pathname, search } = new URL(route.request().url());
    if (pathname === "/api/admin/roles" && route.request().method() === "GET") return json(route, [{ code: "admin", description: "全部管理权限" }, { code: "data_manager", description: "导入、审核与发布" }, { code: "viewer", description: "查看已发布数据" }]);
    if (pathname === "/api/admin/users" && route.request().method() === "GET") return json(route, [userRecord]);
    if (pathname === "/api/admin/site-config-versions" && route.request().method() === "GET") return json(route, [siteConfig]);
    if (`${pathname}${search}`.startsWith("/api/admin/audit-events?") && route.request().method() === "GET") return json(route, { items: [], total: 0, limit: 20, offset: 0, next_offset: null });
    if (pathname === "/api/admin/maintenance" && route.request().method() === "GET") return json(route, maintenance);
    return unhandledBaselineRequest(route);
  });
}

async function installProductChartApi(page: Page): Promise<void> {
  const metric = { denominator: null, expected_days: 31, is_partial: false, null_reason: null, numerator: null, observed_days: 31, source_completeness: "complete", value: 1, value_state: "observed" };
  const response = { available_series: [{ active: true, dimension: "color", key: "red-key", label: "红色", sort_order: 0, total: metric }], effective_return_basis: "event_date", permissions: {}, provenance: { catalog_version: 8, consistent_as_of: "2026-08-24T10:00:00Z", fact_basis: "current" }, series: [{ key: "red-key", points: [{ date: "2026-08-24", denominator: null, null_reason: null, numerator: null, source_completeness: "complete", value: 1, value_state: "observed" }] }], source_report_coverage: { contributing_report_date_from: "2026-08-24", contributing_report_date_to: "2026-08-24" }, style: { color_count: 1, size_count: 1, sku_count: 1, standard_name: "标准夹克", status: "enabled", style_code: "J-1", style_id: "88" }, style_reconciliation: { metric_status: { conversion: "evaluable", returns: "evaluable", sales: "evaluable", sessions: "evaluable", units: "evaluable" } }, summary: { metrics: { units: metric, sales: { ...metric, value: "10.00" }, returns: metric, sessions: metric, conversion: { ...metric, value: "1.000000" } } }, trend_effective_return_basis: null, variants: [{ internal_display_sku: "SKU-DISPLAY-1", metrics: { units: metric, sales: { ...metric, value: "10.00" }, returns: metric, sessions: metric, conversion: { ...metric, value: "1.000000" } }, seller_sku_aliases: [{ is_truncated: false, is_unsafe: true, preview: "<unsafe>", sha256: "sha256:1234567890abcdef", source_ref_id: "ref-1" }], sku_id: "sku-1", standard_color: "红色", standard_size: "M", status: "enabled" }] };
  await page.route((url) => url.pathname === "/api/dashboard/styles/88/card", (route) => route.request().method() === "GET" ? json(route, response) : unhandledBaselineRequest(route));
}

test("records dashboard load", async ({ page }, testInfo) => {
  expect(sourceSha).toMatch(/^[0-9a-f]{40}$/);
  await installSyntheticBootstrap(page, ["viewer"]); await installDashboardApi(page);
  const rounds = await measureUiScenario(page, "dashboard-load", async () => { await page.goto("/"); await expect(page.getByRole("heading", { name: /发布数据总表/ })).toBeVisible(); });
  await writeUiEvidence(testInfo, "dashboard-load", rounds, page.context().browser()?.version() ?? "unavailable");
});

test("records batch review confirmation", async ({ page }, testInfo) => {
  await installSyntheticBootstrap(page, ["data_manager"]); const fixture = await installSyntheticBatchReview(page);
  const rounds = await measureUiScenario(page, "batch-review-confirm", async () => { fixture.reset(); await page.goto("/review/batch/42"); await page.getByText("我已核对所选文件的报告日期和报表类型。").click(); await page.getByRole("button", { name: /开始批量审核/ }).click(); await expect(page.getByRole("button", { name: "暂停批量处理" })).toBeVisible(); });
  await writeUiEvidence(testInfo, "batch-review-confirm", rounds, page.context().browser()?.version() ?? "unavailable");
});

test("records admin maintenance load", async ({ page }, testInfo) => {
  await installSyntheticBootstrap(page, ["admin"]); await installMaintenanceApi(page);
  const rounds = await measureUiScenario(page, "admin-maintenance-load", async () => { await page.goto("/admin"); await page.getByRole("button", { name: "备份与任务" }).click(); await expect(page.getByRole("heading", { name: "备份与后台任务" })).toBeVisible(); });
  await writeUiEvidence(testInfo, "admin-maintenance-load", rounds, page.context().browser()?.version() ?? "unavailable");
});

test("records product chart load", async ({ page }, testInfo) => {
  await installSyntheticBootstrap(page, ["viewer"]); await installProductChartApi(page);
  const rounds = await measureUiScenario(page, "product-chart-load", async () => { await page.goto("/products/88"); await expect(page.getByRole("img", { name: /产品每日趋势/ })).toBeVisible(); });
  await writeUiEvidence(testInfo, "product-chart-load", rounds, page.context().browser()?.version() ?? "unavailable");
});
