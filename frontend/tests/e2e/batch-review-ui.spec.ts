import { expect, test, type Page } from "@playwright/test";
import { recompute, sampleRun } from "../../src/features/batch-review/BatchReviewView.fixtures";
import { current, detailFor } from "../../src/features/versions/VersionHistoryView.fixtures";

async function install(page: Page, status = "preview", role = "data_manager") {
  const state = { run: sampleRun(status), failure: 0 };
  const writes: { path: string; body: Record<string, unknown> | null }[] = [];
  const reads: string[] = [];
  await page.context().addCookies([{ name: "clsen_csrf", value: "synthetic-batch", url: test.info().project.use.baseURL! }]);
  await page.context().route(url => url.pathname.startsWith("/api/"), async route => {
    const request = route.request(); const url = new URL(request.url()); const path = url.pathname; const method = request.method();
    if (method === "GET") reads.push(path);
    else {
      expect(role).toBe("data_manager"); expect(request.headers()["x-csrf-token"]).toBe("synthetic-batch");
      expect(request.headers()["idempotency-key"]).toMatch(/^[0-9a-f-]{36}$/);
      writes.push({ path, body: request.postData() ? request.postDataJSON() as Record<string, unknown> : null });
    }
    if (path === "/api/auth/me") return route.fulfill({ json: { id: 88, username: "synthetic-batch", display_name: "虚构批量审核账号", roles: [role] } });
    if (path === "/api/data-calendar/site-context") return route.fulfill({ json: { site_id: 1, site_code: "US", display_name: "虚构站点", site_config_version_id: 2, source_timezone: "UTC", reporting_timezone: "UTC", currency_code: "USD" } });
    if (path === "/api/dashboard/daily-ledger") return route.fulfill({ json: { publications: [], site_config_versions: [], rows: [], range: { from_date: "2026-09-01", to_date: "2026-09-30" } } });
    if (path === "/api/imports/batch-reviews/81" && method === "GET") {
      if (state.failure) return route.fulfill({ status: state.failure, json: { error: { code: "synthetic_error", message: "虚构任务读取失败" } } });
      return route.fulfill({ json: state.run });
    }
    if (path === "/api/imports/batch-reviews") return route.fulfill({ json: { items: [{ id: 81, status: state.run.status, revision: state.run.revision }], has_next: false } });
    if (path === "/api/versions") { expect(url.searchParams.get("batch_review_run_id")).toBe("81"); return route.fulfill({ json: state.run.items.filter(i => i.status === "ready_for_publish").map(i => ({ ...current, dataset_id: i.dataset_id, version_id: i.version_id, report_date: i.report_date, report_type: i.report_type, status: "ready_for_publish", is_current_publication: false, is_active_draft: true, published_at: null, draft_pointed_at: "2026-09-12T04:00:00Z" })) }); }
    if (/^\/api\/versions\/\d+$/.test(path)) {
      const item = state.run.items.find(i => i.version_id === Number(path.split("/").at(-1)))!;
      return route.fulfill({ json: { ...detailFor(), dataset_id: item.dataset_id, version_id: item.version_id, report_date: item.report_date, report_type: item.report_type, status: "ready_for_publish", is_current_publication: false, is_active_draft: true, published_at: null, parents: [], children: [] } });
    }
    const command = writes.at(-1)?.body;
    if (path.endsWith("/confirm")) {
      expect(command).toMatchObject({ expected_revision: state.run.revision, confirmation_accepted: true, confirmation_statement_version: "batch-review-confirmation-v1" });
      const ids = command!.selected_item_ids as number[];
      state.run = recompute({ ...state.run, revision: state.run.revision + 1, status: "running", allowed_actions: ["pause"], items: state.run.items.map(i => i.status === "eligible" ? { ...i, selected: ids.includes(i.id), status: ids.includes(i.id) ? "queued" : "skipped", recovery_available: ids.includes(i.id) } : i) });
      return route.fulfill({ json: state.run });
    }
    if (path.endsWith("/resume") || path.endsWith("/pause")) {
      expect(command).toEqual({ expected_revision: state.run.revision }); const paused = path.endsWith("/pause");
      state.run = { ...state.run, revision: state.run.revision + 1, status: paused ? "paused" : "running", allowed_actions: [paused ? "resume" : "pause"], items: state.run.items.map(i => ({ ...i, recovery_available: !paused && i.status === "queued" })) };
      return route.fulfill({ json: state.run });
    }
    if (path.endsWith("/retry")) {
      expect(command).toEqual({ expected_revision: state.run.revision }); const id = Number(path.split("/").at(-2));
      state.run = recompute({ ...state.run, revision: state.run.revision + 1, status: "running", allowed_actions: ["pause"], items: state.run.items.map(i => i.id === id ? { ...i, status: "queued", recovery_available: true, retry_allowed: false, reason_message: null } : i) });
      return route.fulfill({ json: state.run });
    }
    if (path.endsWith("/advance")) {
      const id = Number(path.split("/").at(-2)); const item = state.run.items.find(i => i.id === id)!;
      expect(item.recovery_available).toBe(true);
      state.run = recompute({ ...state.run, revision: state.run.revision + 1, items: state.run.items.map(i => i.id === id ? { ...i, status: "ready_for_publish", recovery_available: false, retry_allowed: false, reason_message: null, dataset_id: i.id + 200, version_id: i.id + 100 } : i) });
      if (!state.run.summary.active) state.run = { ...state.run, status: state.run.summary.manual_review || state.run.summary.failed ? "completed_with_exceptions" : "completed", allowed_actions: [] };
      return route.fulfill({ json: state.run.items.find(i => i.id === id) });
    }
    throw new Error(`Unexpected synthetic request: ${method} ${path}`);
  });
  return { state, writes, reads };
}

test("actual batch preflight confirms only selected items and hands results to version history", async ({ page }) => {
  const { state, writes } = await install(page); state.failure = 503;
  await page.goto("/review/batch/81"); await expect(page.getByText("虚构任务读取失败", { exact: true })).toBeVisible();
  state.failure = 0; await page.getByRole("button", { name: "重新读取", exact: true }).click();
  await page.getByRole("checkbox", { name: "选择 returns-2026-09-13.csv", exact: true }).uncheck();
  await page.getByRole("checkbox", { name: "我已核对所选文件的报告日期和报表类型。", exact: true }).check();
  await page.getByRole("button", { name: "开始批量审核（1 项）", exact: true }).click();
  await expect(page.getByText("已完成（有异常）", { exact: true })).toBeVisible();
  expect(writes.filter(w => w.path.endsWith("/confirm"))).toHaveLength(1);
  expect(writes.find(w => w.path.endsWith("/confirm"))!.body!.selected_item_ids).toEqual([101]);
  expect(writes.filter(w => w.path.endsWith("/advance"))).toHaveLength(1);
  await page.reload(); await expect(page.getByText("已完成（有异常）", { exact: true })).toBeVisible();
  expect(writes.filter(w => w.path.endsWith("/confirm"))).toHaveLength(1);
  await page.getByRole("link", { name: "查看全部待发布草稿", exact: true }).click();
  await expect(page).toHaveURL(/versions\?batch_review_run_id=81/);
  await expect(page.getByRole("link", { name: "继续审核草稿", exact: true })).toHaveAttribute("href", "/review/2026-09-12?report_type=business_report");
});

test("actual paused task resumes without confirmation; failed item retries and refresh persists", async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 }); const first = await install(page, "paused");
  await page.goto("/review/batch/81"); await expect(page.getByRole("button", { name: "恢复批量处理", exact: true })).toBeVisible();
  await page.reload(); await page.getByRole("button", { name: "恢复批量处理", exact: true }).click();
  await expect(page.getByText("已完成（有异常）", { exact: true })).toBeVisible();
  expect(first.writes.map(w => w.path)).toEqual(["/api/imports/batch-reviews/81/resume", "/api/imports/batch-reviews/81/items/102/advance"]);
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
  await page.context().unrouteAll(); const second = await install(page, "completed_with_exceptions");
  await page.reload(); await page.getByRole("button", { name: "重试", exact: true }).click();
  await expect(page.getByRole("button", { name: "重试", exact: true })).toHaveCount(0);
  await expect(page.getByText("已完成（有异常）", { exact: true })).toBeVisible();
  expect(second.writes.filter(w => w.path.endsWith("/retry"))).toHaveLength(1);
  expect(second.writes.filter(w => w.path.endsWith("/advance"))).toHaveLength(1);
  await page.reload(); await expect(page.getByRole("button", { name: "重试", exact: true })).toHaveCount(0);
  expect(second.writes.filter(w => w.path.endsWith("/retry"))).toHaveLength(1);
});

test("actual task permission failure, unknown outcome and viewer route enforce original boundaries", async ({ page, baseURL }) => {
  const { state, writes } = await install(page, "running"); state.failure = 403;
  await page.goto("/review/batch/81"); await expect(page.getByText("你没有查看或操作此批量任务的权限。", { exact: true })).toBeVisible();
  state.failure = 0; state.run.items[1] = { ...state.run.items[1]!, status: "validating", recovery_available: false, outcome_unknown: true };
  await page.getByRole("button", { name: "重新读取", exact: true }).click();
  await expect(page.getByText("正在确认服务器结果，请勿重复提交。", { exact: true })).toBeVisible();
  await page.getByRole("button", { name: "刷新状态", exact: true }).click();
  await expect(page.getByText("正在确认服务器结果，请勿重复提交。", { exact: true })).toBeVisible(); expect(writes).toHaveLength(0);
  await page.context().unrouteAll(); const viewer = await install(page, "preview", "viewer"); await page.reload();
  await expect(page).toHaveURL(url => url.origin === new URL(baseURL!).origin && url.pathname === "/" && /^\d{4}-\d{2}$/.test(url.searchParams.get("month") ?? ""));
  expect(viewer.reads).not.toContain("/api/imports/batch-reviews/81"); expect(viewer.writes).toHaveLength(0);
});
