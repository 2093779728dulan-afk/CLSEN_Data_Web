import { expect, test, type Page, type Route } from "@playwright/test";

const csrfToken = "batch-review-e2e-csrf";
const runId = 42;

type Item = {
  attempt_count: number; batch_id: number; dataset_id: number | null; encoding: string | null;
  filename: string; id: number; manual_review_url: string | null; operation_token: string | null;
  outcome_unknown: boolean; reason_code: string | null; reason_message: string | null;
  recognition_status: string; recovery_available: boolean; report_date: string | null; report_type: string | null;
  retry_allowed: boolean; selected: boolean; status: string; validation_run_id: number | null;
  version_id: number | null;
};

function json(route: Route, payload: unknown, status = 200) {
  return route.fulfill({ body: JSON.stringify(payload), contentType: "application/json", status });
}

function operationKey(route: Route) {
  const headers = route.request().headers();
  expect(headers["x-csrf-token"]).toBe(csrfToken);
  expect(headers["idempotency-key"]).toMatch(/^[0-9a-f-]{36}$/i);
  return headers["idempotency-key"] ?? "";
}

function makeItem(index: number): Item {
  return {
    attempt_count: 0, batch_id: 100 + index, dataset_id: null, encoding: "utf-8-sig",
    filename: `synthetic-${String(index).padStart(3, "0")}.csv`, id: 200 + index,
    manual_review_url: `/review/2026-08-${String(index).padStart(2, "0")}?report_type=business_report`,
    operation_token: null, outcome_unknown: false, reason_code: null,
    reason_message: "可安全推进至待发布。", recognition_status: "recognized",
    recovery_available: false,
    report_date: `2026-08-${String(index).padStart(2, "0")}`, report_type: "business_report",
    retry_allowed: false, selected: true, status: "eligible", validation_run_id: null, version_id: null,
  };
}

async function installBatchReviewApi(page: Page, rejectFirstAdvance = false) {
  const items = Array.from({ length: 6 }, (_, index) => makeItem(index + 1));
  let status = "preview";
  let revision = 0;
  let active = 0;
  let maximumActive = 0;
  let acceptedAdvanceRequests = 0;
  let publicationWrites = 0;
  let failedOnce = false;
  let rejectedAdvance = false;
  const advanceCalls = new Map<number, number>();

  const snapshot = () => {
    const summary = {
      active: items.filter((item) => ["queued", "parsing", "materializing", "validating"].includes(item.status)).length,
      eligible: items.filter((item) => item.status === "eligible").length,
      failed: items.filter((item) => item.status === "failed").length,
      manual_review: items.filter((item) => item.status === "manual_review").length,
      ready_for_publish: items.filter((item) => item.status === "ready_for_publish").length,
      skipped: items.filter((item) => item.status === "skipped").length,
      total: items.length,
    };
    const allowed_actions = status === "preview" ? ["confirm"] : status === "running" ? ["pause"] : status === "paused" ? ["resume"] : [];
    if (summary.failed > 0) allowed_actions.push("retry");
    return { allowed_actions, id: runId, items, revision, status, summary };
  };

  const recompute = () => {
    if (status === "paused") return;
    if (items.some((item) => ["queued", "parsing", "materializing", "validating"].includes(item.status))) return;
    status = items.some((item) => ["manual_review", "failed"].includes(item.status)) ? "completed_with_exceptions" : "completed";
  };

  await page.context().addCookies([{ name: "clsen_csrf", sameSite: "Lax", url: "http://127.0.0.1:5173", value: csrfToken }]);
  await page.route((url) => url.pathname.startsWith("/api/"), async (route) => {
    const request = route.request();
    const url = new URL(request.url());
    const path = url.pathname;
    const method = request.method();
    if (path === "/api/auth/me" && method === "GET") return json(route, { id: 3, username: "batch-manager", display_name: "批量审核员", roles: ["data_manager"] });
    if (path === "/api/data-calendar/site-context" && method === "GET") return json(route, { site_id: 1, site_code: "amazon_us", display_name: "Amazon US", site_config_version_id: 1, source_timezone: "America/Los_Angeles", reporting_timezone: "America/Los_Angeles", currency_code: "USD" });
    if (path === `/api/imports/batch-reviews/${runId}` && method === "GET") return json(route, snapshot());
    if (path === `/api/imports/batch-reviews/${runId}/confirm` && method === "POST") {
      operationKey(route);
      const body = request.postDataJSON() as { confirmation_accepted: boolean; confirmation_statement_version: string; expected_revision: number; selected_item_ids: number[] };
      expect(body).toMatchObject({ confirmation_accepted: true, confirmation_statement_version: "batch-review-confirmation-v1", expected_revision: 0 });
      for (const item of items) {
        item.recovery_available = body.selected_item_ids.includes(item.id);
        item.status = item.recovery_available ? "queued" : "skipped";
      }
      status = "running"; revision += 1;
      return json(route, snapshot());
    }
    if (path === `/api/imports/batch-reviews/${runId}/pause` && method === "POST") {
      operationKey(route); status = "paused"; revision += 1; return json(route, snapshot());
    }
    if (path === `/api/imports/batch-reviews/${runId}/resume` && method === "POST") {
      operationKey(route); status = "running"; revision += 1; return json(route, snapshot());
    }
    const advance = path.match(new RegExp(`^/api/imports/batch-reviews/${runId}/items/(\\d+)/advance$`));
    if (advance && method === "POST") {
      const key = operationKey(route); const item = items.find((candidate) => candidate.id === Number(advance[1]));
      if (!item || item.status !== "queued") return json(route, { error: { code: "batch_review_state_conflict", message: "Item is not queued.", request_id: "e2e" } }, 409);
      advanceCalls.set(item.id, (advanceCalls.get(item.id) ?? 0) + 1);
      if (rejectFirstAdvance && item.id === 201 && !rejectedAdvance) {
        rejectedAdvance = true;
        return json(route, { error: { code: "advance_unavailable", message: "示例推进服务暂不可用，任务状态未改变。", request_id: "e2e-rejected-advance" } }, 503);
      }
      acceptedAdvanceRequests += 1;
      item.operation_token = key; item.recovery_available = false; item.status = "validating"; active += 1; maximumActive = Math.max(maximumActive, active);
      await new Promise((resolve) => setTimeout(resolve, 180));
      active -= 1; item.attempt_count += 1;
      if (item.id === 203) {
        item.status = "manual_review"; item.reason_code = "validation_warning"; item.reason_message = "完整校验包含 1 项警告。"; item.dataset_id = 303; item.version_id = 403;
      } else if (item.id === 204 && !failedOnce) {
        failedOnce = true; item.status = "failed"; item.retry_allowed = true; item.reason_message = "临时数据库繁忙，可安全重试。";
      } else {
        item.status = "ready_for_publish"; item.reason_message = null; item.dataset_id = 300 + item.id; item.version_id = 400 + item.id;
      }
      recompute(); return json(route, item);
    }
    const retry = path.match(new RegExp(`^/api/imports/batch-reviews/${runId}/items/(\\d+)/retry$`));
    if (retry && method === "POST") {
      operationKey(route); const item = items.find((candidate) => candidate.id === Number(retry[1]));
      if (!item?.retry_allowed) return json(route, { error: { code: "batch_review_state_conflict", message: "Item is not retryable.", request_id: "e2e" } }, 409);
      item.recovery_available = true; item.status = "queued"; item.retry_allowed = false; item.reason_message = null; status = "running"; revision += 1;
      return json(route, snapshot());
    }
    if (path === "/api/versions" && url.searchParams.get("batch_review_run_id") === String(runId)) {
      const versions = items.filter((item) => item.status === "ready_for_publish").map((item, index) => ({ dataset_id: item.dataset_id, version_id: item.version_id, report_date: item.report_date, report_type: item.report_type, version_no: 1, status: "ready_for_publish", data_revision: 0, review_revision: 1, created_at: "2026-08-18T01:00:00Z", sealed_at: null, is_current_publication: false, published_at: null, is_active_draft: true, draft_pointed_at: `2026-08-18T01:00:0${index}Z` }));
      return json(route, versions);
    }
    const detail = path.match(/^\/api\/versions\/(\d+)$/);
    if (detail) {
      const item = items.find((candidate) => candidate.version_id === Number(detail[1]));
      return json(route, { dataset_id: item?.dataset_id, version_id: item?.version_id, report_date: item?.report_date, report_type: item?.report_type, version_no: 1, status: "ready_for_publish", data_revision: 0, review_revision: 1, created_at: "2026-08-18T01:00:00Z", sealed_at: null, is_current_publication: false, published_at: null, is_active_draft: true, draft_pointed_at: "2026-08-18T01:00:00Z", parents: [], children: [], viewer_visible_notes: [] });
    }
    if (path.includes("publish") && method !== "GET") publicationWrites += 1;
    return json(route, { error: { code: "unhandled_e2e_request", message: `${method} ${path}`, request_id: "e2e" } }, 500);
  });
  return { advanceCalls, get acceptedAdvanceRequests() { return acceptedAdvanceRequests; }, get active() { return active; }, get maximumActive() { return maximumActive; }, get publicationWrites() { return publicationWrites; } };
}

test("confirms once, pauses, refreshes, resumes and isolates exceptions without publishing", async ({ page }) => {
  const fixture = await installBatchReviewApi(page);
  await page.goto(`/review/batch/${runId}`);
  await expect(page.getByRole("heading", { name: "核对文件清单" })).toBeVisible();
  await page.getByRole("checkbox", { name: "选择 synthetic-006.csv" }).uncheck();
  await page.getByText("我已核对所选文件的报告日期和报表类型。").click();
  await page.getByRole("button", { name: "开始批量审核（5 项）" }).click();

  await expect.poll(() => fixture.maximumActive).toBe(3);
  await page.getByRole("button", { name: "暂停批量处理" }).click();
  await expect(page.getByText("已暂停", { exact: true })).toBeVisible();
  await page.reload();
  await expect(page.getByRole("button", { name: "恢复批量处理" })).toBeVisible();
  await expect.poll(() => fixture.active).toBe(0);
  await page.getByRole("button", { name: "恢复批量处理" }).click();

  await expect(page.getByText("完整校验包含 1 项警告。")).toBeVisible();
  await expect(page.getByRole("button", { name: "重试" })).toBeVisible();
  await page.getByRole("button", { name: "重试" }).click();
  await expect(page.getByText("临时数据库繁忙，可安全重试。")).toHaveCount(0);
  await expect(page.getByRole("link", { name: "查看全部待发布草稿" })).toBeVisible();
  await expect.poll(() => fixture.acceptedAdvanceRequests).toBe(6);
  expect(fixture.maximumActive).toBe(3);
  expect(fixture.publicationWrites).toBe(0);

  await page.setViewportSize({ width: 390, height: 844 });
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true);
  await page.getByRole("link", { name: "查看全部待发布草稿" }).click();
  await expect(page.getByRole("heading", { name: `批量任务 #${runId} · 待发布草稿` })).toBeVisible();
});

for (const width of [1280, 390]) {
  test(`rejected advance preserves authoritative state and requires explicit recovery at ${width}px`, async ({ page }, testInfo) => {
    await page.setViewportSize({ width, height: 900 });
    await page.emulateMedia({ reducedMotion: width === 390 ? "reduce" : "no-preference" });
    const runtimeEvents: { action?: string; execution_outcome?: string; failed_count?: number }[] = [];
    page.on("console", message => {
      if (message.args().length === 2 && message.text().startsWith("batch_review_runtime")) {
        void message.args()[1]!.jsonValue().then((event: unknown) => runtimeEvents.push(event as (typeof runtimeEvents)[number]));
      }
    });
    const fixture = await installBatchReviewApi(page, true);
    await page.goto(`/review/batch/${runId}`);
    await expect(page.getByRole("heading", { name: "核对文件清单", exact: true })).toBeVisible();
    await page.getByRole("checkbox", { name: "我已核对所选文件的报告日期和报表类型。", exact: true }).check();
    await page.getByRole("button", { name: "开始批量审核（6 项）", exact: true }).click();
    await expect.poll(() => runtimeEvents.some(event => event.action === "complete_pass" && event.execution_outcome === "completed_with_failure" && event.failed_count === 1)).toBe(true);
    await expect(page.getByRole("alert")).toContainText("示例推进服务暂不可用，任务状态未改变。");
    const firstRow = page.getByRole("row").filter({ has: page.getByRole("rowheader", { name: "synthetic-001.csv", exact: true }) });
    await expect(firstRow.getByText("排队中", { exact: true })).toBeVisible();
    expect(fixture.advanceCalls.get(201)).toBe(1);
    expect(fixture.acceptedAdvanceRequests).toBe(5);
    await page.screenshot({ path: testInfo.outputPath(`integrated-batch-failure-${width}.png`), fullPage: true });

    await page.getByRole("button", { name: "重新读取任务", exact: true }).click();
    await expect(page.getByRole("alert")).toHaveCount(0);
    await expect(firstRow.getByText("排队中", { exact: true })).toBeVisible();
    expect(fixture.advanceCalls.get(201)).toBe(1);
    await page.getByRole("button", { name: "暂停批量处理", exact: true }).click();
    await expect(page.getByRole("button", { name: "恢复批量处理", exact: true })).toBeVisible();
    await page.reload();
    await expect(page.getByRole("button", { name: "恢复批量处理", exact: true })).toBeVisible();
    expect(fixture.advanceCalls.get(201)).toBe(1);
    await page.getByRole("button", { name: "恢复批量处理", exact: true }).click();
    await expect(firstRow.getByText("待发布", { exact: true })).toBeVisible();
    expect(fixture.advanceCalls.get(201)).toBe(2);
    expect(fixture.acceptedAdvanceRequests).toBe(6);
    expect(fixture.maximumActive).toBeLessThanOrEqual(3);
    await page.reload();
    await expect(firstRow.getByText("待发布", { exact: true })).toBeVisible();
    expect(fixture.advanceCalls.get(201)).toBe(2);
    await expect(page.getByRole("alert")).toHaveCount(0);
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
    await page.screenshot({ path: testInfo.outputPath(`integrated-batch-recovered-${width}.png`), fullPage: true });
    await page.getByRole("link", { name: "查看全部待发布草稿", exact: true }).click();
    await expect(page.getByRole("heading", { name: `批量任务 #${runId} · 待发布草稿`, exact: true })).toBeVisible();
    await page.goBack();
    await expect(firstRow.getByText("待发布", { exact: true })).toBeVisible();
    expect(fixture.publicationWrites).toBe(0);
  });
}
