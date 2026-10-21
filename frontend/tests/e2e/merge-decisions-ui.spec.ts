import { mergePreview } from "../../src/features/import-review/MergeDecisionMatrix.fixtures";
import { expect, test, type Page } from "@playwright/test";
import { current, historical, detailFor } from "../../src/features/versions/VersionHistoryView.fixtures";
import { sampleWorkbench } from "../../src/features/workbench/DateWorkbenchView.fixtures";
import { draftWorkspace } from "../../src/features/import-review/DraftReviewView.fixtures";

const targetPublication = { ...current, dataset_id: 61, version_id: 153, report_date: "2026-09-13", published_at: "2026-09-13T03:00:00Z" };
const initial = "/versions?report_date=2026-09-12&report_type=business_report";
const candidate = { move_command_id: 77, source_dataset_id: 40, source_report_date: "2026-09-11", restore_source_version_id: 47,
  source_current_publication: { version_id: null, published_at: null }, target_dataset_id: 41, target_report_date: "2026-09-12", restore_target_version_id: 51,
  target_current_publication: { version_id: 53, published_at: current.published_at }, moved_target_version_id: 53, completed_at: current.published_at, report_type: "business_report" };
async function install(page: Page) {
  const state = { rollback: false, undone: false, targetDate: "2026-09-12", previewFail: true, previewReads: [] as string[], fail: true, role: "admin" };
  const writes: { path: string; key: string; body: Record<string, unknown> }[] = []; const unexpected: string[] = [];
  await page.context().addCookies([{ name: "clsen_csrf", value: "fictional-command", url: test.info().project.use.baseURL! }]);
  await page.route(url => url.pathname.startsWith("/api/"), async route => {
    const request = route.request(); const url = new URL(request.url()); const path = url.pathname;
    if (request.method() === "POST") {
      const allowed = ["/api/datasets/41/revisions", "/api/admin/versions/53/move-date", "/api/admin/datasets/41/rollback", "/api/admin/published-moves/77/undo"];
      expect(allowed).toContain(path); expect(request.headers()["x-csrf-token"]).toBe("fictional-command");
      const key = request.headers()["idempotency-key"]!; expect(key).toMatch(/^[0-9a-f-]{36}$/i);
      const body = request.postDataJSON() as Record<string, unknown>; writes.push({ path, key, body });
      if (state.fail) { state.fail = false; return route.fulfill({ status: 503, json: { error: { code: "publication_outcome_unknown", message: "虚构提交结果暂时无法确认" } } }); }
      if (path.includes("rollback") || path.endsWith("/undo")) {
        if (path.includes("rollback")) state.rollback = true; else { state.undone = true; state.rollback = true; }
        return route.fulfill({ json: { operation_token: key, command_id: 78, command_type: path.endsWith("/undo") ? "reverse_move" : "rollback", transitions: [], completed_at: "2026-09-12T05:00:00Z" } });
      }
      state.targetDate = path.endsWith("move-date") ? "2026-09-13" : "2026-09-12";
      return route.fulfill({ status: 201, json: { completed_at: "2026-09-12T05:00:00Z", data_revision: 2, dataset_id: 41, operation_token: key,
        result_kind: path.endsWith("move-date") ? "published_move_revision_created" : "revision_created", review_revision: 3,
        source_dataset_id: 41, source_version_id: 53, status: "draft", version_id: 54, version_no: 4 } });
    }
    if (request.method() !== "GET") { unexpected.push(`${request.method()} ${path}`); return route.fulfill({ status: 405 }); }
    if (path === "/api/auth/me") return route.fulfill({ json: { id: 88, username: "fictional-commands", display_name: "虚构管理账号", roles: [state.role] } });
    if (path === "/api/data-calendar/site-context") return route.fulfill({ json: { site_id: 1, site_code: "DEMO", display_name: "虚构站点", site_config_version_id: 2, source_timezone: "UTC", reporting_timezone: "UTC", currency_code: "USD" } });
    if (path === "/api/admin/published-moves/undoable") return route.fulfill({ json: state.undone ? [] : [candidate] });
    if (path === "/api/imports/batch-reviews") return route.fulfill({ json: { items: [], has_next: false } });
    const publication = state.rollback ? { ...historical, is_current_publication: true, published_at: "2026-09-12T05:00:00Z" } : current;
    if (path === "/api/datasets/merge-preview") {
      expect(url.searchParams.get("target_version_id")).toBe("153"); expect(url.searchParams.get("source_kind")).toBe("dataset_version"); expect(url.searchParams.get("source_id")).toBe("53"); state.previewReads.push(url.search);
      if (state.previewFail) { return route.fulfill({ status: 503, json: { error: { code: "fictional_preview_failure", message: "虚构重复记录读取失败" } } }); }
      return route.fulfill({ contentType: "application/json", body: JSON.stringify({ ...mergePreview(), target_version_id: 153, source_id: 53, source_kind: "dataset_version" }) });
    }
    if (path === "/api/versions" && url.searchParams.get("report_date") === "2026-09-13") return route.fulfill({ json: [targetPublication] });
    if (path === "/api/versions") return route.fulfill({ json: url.searchParams.get("report_date") === "2026-09-13" ? [] : state.rollback ? [publication, { ...current, is_current_publication: false }] : [current, historical] });
    if (/^\/api\/versions\/\d+$/.test(path)) return route.fulfill({ json: detailFor(path.endsWith("/51") ? publication : current) });
    if (path === "/api/data-calendar") return route.fulfill({ json: [{ report_date: state.targetDate, dataset_id: 41, report_type: "business_report", status: "draft", version_id: 54, version_no: 4 }] });
    if (path === "/api/data-calendar/days") return route.fulfill({ json: [] });
    if (path.startsWith("/api/workbench/dates/")) { const workbench = structuredClone(sampleWorkbench("draft")); workbench.report_date = state.targetDate; return route.fulfill({ json: workbench }); }
    if (path === "/api/drafts/54/review-workspace") { const data = structuredClone(draftWorkspace); data.head.version_id = 54; data.head.dataset_id = 41; data.head.version_no = 4; data.report_date = state.targetDate; return route.fulfill({ json: data }); }
    if (path === "/api/dashboard/daily-ledger") return route.fulfill({ json: { publications: [], site_config_versions: [], rows: [], range: { from_date: state.targetDate, to_date: state.targetDate } } });
    unexpected.push(path); return route.fulfill({ status: 404, json: { error: { code: "fixture_unhandled", message: "未配置的虚构请求" } } });
  });
  return { state, writes, unexpected };
}

for (const width of [1280, 390]) {
  test(`actual merged move blocks incomplete pairs and carries complete decisions at ${width}px`, async ({ page }) => {
    await page.setViewportSize({ width, height: 900 }); const f = await install(page);
    const errors: string[] = []; page.on("pageerror", e => errors.push(e.message));
    await page.goto(initial); await page.getByRole("button", { name: "移动到其他日期", exact: true }).click();
    const dialog = page.getByRole("dialog", { name: "已发布数据跨日期移动", exact: true });
    await dialog.getByLabel("目标报告日", { exact: true }).fill("2026-09-13");
    await dialog.getByRole("button", { name: "检查目标日期", exact: true }).click();
    await expect(dialog.getByRole("alert")).toContainText("虚构重复记录读取失败");
    await dialog.getByRole("textbox", { name: "移动原因", exact: true }).fill("虚构核对两侧业务记录");
    const submit = dialog.getByRole("button", { name: "创建跨日期审核草稿", exact: true }); await expect(submit).toBeDisabled();
    const initialReads = f.state.previewReads.length; f.state.previewFail = false;
    await dialog.getByRole("button", { name: "重新读取重复记录", exact: true }).click();
    const matrix = dialog.getByRole("region", { name: "重复记录合并决定", exact: true });
    await expect(matrix.getByText("6 组重复记录 · 已处理 1/6", { exact: true })).toBeVisible();
    await matrix.getByLabel("当前页统一处理方式", { exact: true }).selectOption("keep_source");
    await matrix.getByRole("button", { name: "应用到当前页未处理项", exact: true }).click(); await expect(submit).toBeDisabled();
    for (const n of [2, 3, 4]) await matrix.getByLabel(`重复记录 ${n} 决定依据`, { exact: true }).fill(`核对原表：采用来源记录 ${n}`);
    await matrix.getByRole("button", { name: "下一页", exact: true }).click();
    await matrix.getByLabel("当前页统一处理方式", { exact: true }).selectOption("keep_both");
    await matrix.getByRole("button", { name: "应用到当前页未处理项", exact: true }).click();
    for (const n of [5, 6]) await matrix.getByLabel(`重复记录 ${n} 决定依据`, { exact: true }).fill(`核对原表：两行均保留 ${n}`);
    await expect(submit).toBeEnabled();
    const reason = matrix.getByLabel("重复记录 6 决定依据", { exact: true }); await reason.fill(""); await expect(submit).toBeDisabled();
    await reason.fill("核对原表：两行均保留"); await expect(submit).toBeEnabled(); await submit.click();
    await expect(dialog.getByRole("alert")).toContainText("虚构提交结果暂时无法确认");
    await expect(reason).toHaveValue("核对原表：两行均保留"); await submit.click();
    await expect(page).toHaveURL(/\/review\/2026-09-13/); await expect(page.getByRole("button", { name: "经营报告 · 草稿 v4", exact: true })).toBeVisible();
    await page.reload(); await expect(page.getByRole("button", { name: "经营报告 · 草稿 v4", exact: true })).toBeVisible();
    expect(f.state.previewReads).toHaveLength(initialReads + 1); expect(f.state.previewReads.every(query => query === f.state.previewReads[0])).toBe(true);
    const calls = f.writes.filter(w => w.path === "/api/admin/versions/53/move-date"); expect(calls).toHaveLength(2); expect(calls[0]!.key).toBe(calls[1]!.key);
    expect(calls[0]!.body).toEqual(calls[1]!.body);
    const body = calls[0]!.body;
    expect(body).toMatchObject({ source_dataset_id: 41, target_report_date: "2026-09-13", target: { dataset_id: 61, target_kind: "published", strategy: "merge", publication: { version_id: 153, published_at: targetPublication.published_at } } });
    const decisions = body.merge_decisions as { target_row_id: number; source_row_id: number; action: string; reason: string }[];
    expect(decisions).toHaveLength(6);
    expect(decisions.map(d => [d.target_row_id, d.source_row_id])).toEqual(Array.from({ length: 6 }, (_, i) => [101 + i, 201 + i]));
    expect(decisions.map(d => d.action)).toEqual(["keep_target", "keep_source", "keep_source", "keep_source", "keep_both", "keep_both"]);
    expect(decisions[0]!.reason).toContain("两侧全部字段完全相同"); expect(decisions[5]!.reason).toBe("核对原表：两行均保留");
    expect(f.unexpected).toEqual([]); expect(errors).toEqual([]); expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
  });
}
