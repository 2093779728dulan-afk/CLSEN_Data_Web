import { expect, test, type Page } from "@playwright/test";
import { intakeInspection, intakeParse, intakeTarget } from "../../src/features/import-review/ImportIntakeView.fixtures";
import type { DraftHead, ReviewWorkspace } from "../../src/api/types";

const head: DraftHead = { dataset_id: 41, version_id: 52, version_no: 5, status: "draft", data_revision: 0, review_revision: 0, pointed_at: "2026-09-12T06:00:00Z" };
const workspace: ReviewWorkspace = { head, report_date: "2026-09-12", report_type: "business_report", ruleset_version: "business_report_v1", publication_mode: "ordinary", published_move: null, source_batches: [{ batch_id: 81 }], fields: [], rows: [], version_notes: [], latest_full_validation: null, pagination: { page: 1, page_size: 50, total_rows: 0, total_pages: 0 } };
async function install(page: Page, role = "data_manager") {
  const state = { inspectFailure: false, parseFailure: false, draft: false, sourceFailure: false };
  const writes: { path: string; body: Record<string, unknown> | null; key?: string }[] = [];
  const unexpected: string[] = [];
  await page.context().addCookies([{ name: "clsen_csrf", value: "synthetic-intake", url: test.info().project.use.baseURL! }]);
  await page.context().route(url => url.pathname.startsWith("/api/"), async route => {
    const r = route.request(); const url = new URL(r.url()); const path = url.pathname; const method = r.method();
    if (!["GET", "HEAD"].includes(method)) {
      expect(role).toBe("data_manager"); expect(r.headers()["x-csrf-token"]).toBe("synthetic-intake");
      const body = r.headers()["content-type"]?.includes("application/json") && r.postData() ? r.postDataJSON() as Record<string, unknown> : null;
      writes.push({ path, body, key: r.headers()["idempotency-key"] });
      if (path.endsWith("/confirm-parse") || path === "/api/datasets/materialize") expect(r.headers()["idempotency-key"]).toMatch(/^[0-9a-f-]{36}$/);
    }
    if (path === "/api/auth/me") return route.fulfill({ json: { id: 88, username: "synthetic-intake", display_name: "虚构审核账号", roles: [role] } });
    if (path === "/api/data-calendar/site-context") return route.fulfill({ json: { site_id: 1, site_code: "US", display_name: "虚构站点", site_config_version_id: 2, source_timezone: "UTC", reporting_timezone: "UTC", currency_code: "USD" } });
    if (path === "/api/data-calendar") return route.fulfill({ json: state.draft ? [{ report_date: "2026-09-12", report_type: "business_report", dataset_id: 41, version_id: 52, version_no: 5, status: "draft" }] : [] });
    if (path === "/api/data-calendar/days") return route.fulfill({ json: [] });
    if (path === "/api/imports") { expect(url.searchParams.get("report_date")).toBe("2026-09-12"); expect(r.headers()["x-original-filename"]).toBe("fictional.csv"); return route.fulfill({ status: 201, json: { batch_id: 81, raw_file_id: 71, sha256_hex: "a".repeat(64), content_reused: false, duplicate: false } }); }
    if (path === "/api/imports/81/inspect") return state.inspectFailure ? route.fulfill({ status: 503, json: { error: { code: "synthetic_error", message: "虚构识别失败" } } }) : route.fulfill({ json: intakeInspection });
    if (path === "/api/imports/81/raw-file") return route.fulfill({ status: 200, body: "sku,units\nfictional,2" });
    if (path.endsWith("/raw-file/preview")) return state.sourceFailure ? route.fulfill({ status: 503, json: { error: { code: "synthetic_error", message: "虚构源表暂不可读" } } }) : route.fulfill({ json: { headers: ["sku", "units"], rows: [["fictional", "2"]], encoding: "utf-8-sig", total_rows: 2, row_limit: 200, truncated: false } });
    if (path.endsWith("/confirm-parse")) {
      expect(writes.at(-1)?.body).toEqual({ report_date: "2026-09-12", report_type: "business_report", encoding: "utf-8-sig" });
      return route.fulfill({ json: { result: state.parseFailure ? { batch_id: 81, parse_attempt_id: 90, confirmation_revision: 1, error_code: "synthetic_parse_failure" } : intakeParse } });
    }
    if (path === "/api/versions") return route.fulfill({ json: [intakeTarget] });
    if (path === "/api/datasets/materialize") {
      const body = writes.at(-1)?.body; expect(body).toMatchObject({ batch_id: 81, parse_baseline_id: 101, report_date: "2026-09-12", strategy: "replace", expected_active_draft: null, expected_publication_version_id: 51, merge_decisions: [] });
      expect(String(body?.reason)).toContain("虚构审核账号"); state.draft = true; return route.fulfill({ json: { dataset_id: 41, version_id: 52 } });
    }
    if (path === "/api/drafts/52") return route.fulfill({ json: head });
    if (path === "/api/drafts/52/review-workspace") return route.fulfill({ json: workspace });
    if (path.endsWith("/notes")) return route.fulfill({ json: [] });
    if (path === "/api/dashboard/daily-ledger") return route.fulfill({ json: { publications: [], site_config_versions: [], rows: [], range: { from_date: "2026-09-01", to_date: "2026-09-30" } } });
    if (path.includes("workbench")) return route.fulfill({ status: 404, json: { error: { code: "synthetic_no_data", message: "虚构日期无数据" } } });
    unexpected.push(`${method} ${path}`); return route.fulfill({ status: 404, json: { error: { code: "unexpected", message: "测试未定义该请求" } } });
  });
  return { state, writes, unexpected };
}

test("actual intake uploads once, retries inspection and parse, preserves baseline on reload and hands off draft", async ({ page }) => {
  const { state, writes, unexpected } = await install(page); state.inspectFailure = true;
  await page.goto("/review-advanced/2026-09-12?report_type=business_report");
  await page.getByLabel("CSV 文件", { exact: true }).setInputFiles({ name: "fictional.csv", mimeType: "text/csv", buffer: Buffer.from("sku,units\nfictional,2") });
  await page.getByRole("button", { name: "保存并检查文件", exact: true }).click();
  await expect(page.getByText("虚构识别失败", { exact: true })).toBeVisible(); state.inspectFailure = false;
  await page.getByRole("button", { name: "重新识别", exact: true }).click(); await expect(page.getByRole("heading", { name: "人工确认识别结果" })).toBeVisible();
  state.sourceFailure = true; await page.getByRole("button", { name: "查看上传源表", exact: true }).click(); await expect(page.getByRole("alert")).toContainText("虚构源表暂不可读");
  state.sourceFailure = false; await page.getByRole("button", { name: "重试", exact: true }).click(); await expect(page.getByRole("cell", { name: "fictional", exact: true })).toBeVisible();
  state.parseFailure = true; await page.getByRole("button", { name: "确认并解析", exact: true }).click(); await expect(page.getByRole("alert")).toContainText("synthetic_parse_failure");
  state.parseFailure = false; await page.getByRole("button", { name: "确认并解析", exact: true }).click(); await expect(page.getByRole("heading", { name: "已解析 2 行源数据" })).toBeVisible();
  expect(writes.filter(w => w.path === "/api/imports")).toHaveLength(1);
  await page.reload(); await expect(page.getByRole("heading", { name: "已解析 2 行源数据" })).toBeVisible();
  await page.getByRole("button", { name: "生成审核草稿", exact: true }).click();
  await page.getByRole("radio", { name: "取消，不生成草稿", exact: true }).check(); await page.getByRole("button", { name: "确认取消", exact: true }).click();
  expect(writes.filter(w => w.path === "/api/datasets/materialize")).toHaveLength(0);
  await page.getByRole("button", { name: "生成审核草稿", exact: true }).click(); await page.getByRole("radio", { name: "替换当前发布版本", exact: true }).check(); await page.getByRole("button", { name: "按所选方式生成草稿", exact: true }).click();
  await expect(page.getByRole("heading", { name: "草稿审核 · v5", exact: true })).toBeVisible();
  await page.reload(); await expect(page.getByRole("heading", { name: "草稿审核 · v5", exact: true })).toBeVisible();
  expect(writes.filter(w => w.path === "/api/datasets/materialize")).toHaveLength(1); expect(unexpected).toEqual([]);
});

test("actual mobile intake date choice retains original confirmation body", async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 }); const { writes, unexpected } = await install(page);
  await page.goto("/review-advanced/2026-09-12?report_type=business_report");
  await page.getByLabel("CSV 文件", { exact: true }).setInputFiles({ name: "fictional.csv", mimeType: "text/csv", buffer: Buffer.from("sku,units\nfictional,2") });
  await page.getByRole("button", { name: "保存并检查文件", exact: true }).click();
  await page.getByLabel("所属报告日", { exact: true }).fill("2026-09-13"); await page.getByRole("button", { name: "采用识别日期", exact: true }).click();
  await page.getByRole("button", { name: "确认并解析", exact: true }).click(); await expect(page.getByRole("heading", { name: "已解析 2 行源数据" })).toBeVisible();
  expect(writes.filter(w => w.path.endsWith("/confirm-parse"))).toHaveLength(1); expect(unexpected).toEqual([]);
});
