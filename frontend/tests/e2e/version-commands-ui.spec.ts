import { expect, test, type Page } from "@playwright/test";
import { current, historical, detailFor } from "../../src/features/versions/VersionHistoryView.fixtures";
import { sampleWorkbench } from "../../src/features/workbench/DateWorkbenchView.fixtures";
import { draftWorkspace } from "../../src/features/import-review/DraftReviewView.fixtures";

const initial = "/versions?report_date=2026-09-12&report_type=business_report";
const candidate = { move_command_id: 77, source_dataset_id: 40, source_report_date: "2026-09-11", restore_source_version_id: 47,
  source_current_publication: { version_id: null, published_at: null }, target_dataset_id: 41, target_report_date: "2026-09-12", restore_target_version_id: 51,
  target_current_publication: { version_id: 53, published_at: current.published_at }, moved_target_version_id: 53, completed_at: current.published_at, report_type: "business_report" };
async function install(page: Page) {
  const state = { rollback: false, undone: false, targetDate: "2026-09-12", fail: true, role: "admin" };
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
  test(`actual command failure, retry, handoff and refreshed results at ${width}px`, async ({ page }) => {
    await page.setViewportSize({ width, height: 900 }); const f = await install(page); const errors: string[] = []; page.on("pageerror", e => errors.push(e.message));
    // Revision failure keeps reason and existing idempotency key; retry hands off the fixed new version.
    await page.goto(initial); await page.getByRole("button", { name: "创建修订", exact: true }).click();
    let dialog = page.getByRole("dialog", { name: "创建发布修订", exact: true });
    await dialog.getByRole("textbox", { name: "修订原因" }).fill("虚构修订原因");
    await dialog.getByRole("button", { name: "确认创建修订", exact: true }).click();
    await expect(dialog.getByRole("alert")).toContainText("虚构提交结果暂时无法确认");
    await expect(dialog.getByRole("textbox", { name: "修订原因" })).toHaveValue("虚构修订原因");
    await dialog.getByRole("button", { name: "确认创建修订", exact: true }).click();
    await expect(page).toHaveURL(/\/review\/2026-09-12/);
    await expect(page.getByRole("button", { name: "经营报告 · 草稿 v4", exact: true })).toBeVisible();
    // Move creates a review draft, rather than publishing immediately.
    f.state.fail = true; await page.goto(initial); await page.getByRole("button", { name: "移动到其他日期", exact: true }).click();
    dialog = page.getByRole("dialog", { name: "已发布数据跨日期移动", exact: true });
    await dialog.getByLabel("目标报告日", { exact: true }).fill("2026-09-13"); await dialog.getByRole("button", { name: "检查目标日期", exact: true }).click();
    await expect(dialog.getByText("目标日期尚无数据", { exact: true })).toBeVisible(); await dialog.getByRole("textbox", { name: "移动原因" }).fill("虚构移动原因");
    await dialog.getByRole("button", { name: "创建跨日期审核草稿", exact: true }).click(); await expect(dialog.getByRole("alert")).toContainText("虚构提交结果暂时无法确认");
    await dialog.getByRole("button", { name: "创建跨日期审核草稿", exact: true }).click();
    await expect(page).toHaveURL(/\/review\/2026-09-13/); await expect(page.getByRole("button", { name: "经营报告 · 草稿 v4", exact: true })).toBeVisible();
    // Rollback error must be visible within the dialog; result survives reread and refresh.
    f.state.fail = true; await page.goto(initial); await page.getByRole("button", { name: "回滚到 v1", exact: true }).click();
    dialog = page.getByRole("dialog", { name: "管理员回滚确认", exact: true });
    await dialog.getByRole("textbox", { name: "回滚原因" }).fill("虚构回滚原因"); await dialog.getByRole("button", { name: "确认回滚到 v1", exact: true }).click();
    await expect(dialog.getByRole("alert")).toContainText("虚构提交结果暂时无法确认");
    await dialog.getByRole("button", { name: "确认回滚到 v1", exact: true }).click();
    await expect(dialog).toHaveCount(0); await expect(page.getByRole("heading", { name: "v1 · 当前发布", exact: true })).toBeVisible();
    await page.reload(); await expect(page.getByRole("heading", { name: "v1 · 当前发布", exact: true })).toBeVisible();
    // Restore the fixture to the existing moved publication, then undo both pointers using the supplied recovery versions.
    f.state.rollback = false; f.state.fail = true; await page.reload();
    await page.getByRole("button", { name: "撤销跨日期移动", exact: true }).click(); dialog = page.getByRole("dialog", { name: "撤销跨日期移动确认", exact: true });
    await dialog.getByRole("textbox", { name: "撤销原因" }).fill("虚构两侧恢复原因");
    await dialog.getByRole("button", { name: "确认撤销跨日期移动", exact: true }).click(); await expect(dialog.getByRole("alert")).toContainText("虚构提交结果暂时无法确认");
    await dialog.getByRole("button", { name: "确认撤销跨日期移动", exact: true }).click(); await expect(dialog).toHaveCount(0);
    await expect(page.getByRole("button", { name: "撤销跨日期移动", exact: true })).toHaveCount(0); await page.reload();
    await expect(page.getByRole("heading", { name: "v1 · 当前发布", exact: true })).toBeVisible();
    for (const path of ["/api/datasets/41/revisions", "/api/admin/versions/53/move-date", "/api/admin/datasets/41/rollback", "/api/admin/published-moves/77/undo"]) {
      const calls = f.writes.filter(w => w.path === path); expect(calls).toHaveLength(2); expect(calls[0]!.key).toBe(calls[1]!.key);
    }
    expect(f.writes[0]!.body).toMatchObject({ expected_publication: { version_id: 53, published_at: current.published_at }, reason: "虚构修订原因" });
    expect(f.writes.find(w => w.path.endsWith("move-date"))!.body).toMatchObject({ target_report_date: "2026-09-13", target: { target_kind: "empty", dataset_id: null }, source_dataset_id: 41 });
    expect(f.writes.find(w => w.path.endsWith("/undo"))!.body).toMatchObject({ restore_source_version_id: 47, restore_target_version_id: 51, source_dataset_id: 40, target_dataset_id: 41 });
    f.state.role = "viewer"; await page.reload(); await expect(page.getByRole("heading", { name: "v1 · 当前发布", exact: true })).toBeVisible();
    for (const name of ["创建修订", "移动到其他日期", "撤销跨日期移动", "回滚到 v3"]) await expect(page.getByRole("button", { name, exact: true })).toHaveCount(0);
    expect(f.unexpected).toEqual([]); expect(errors).toEqual([]); expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
  });
}
