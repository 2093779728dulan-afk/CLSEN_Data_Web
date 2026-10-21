import { expect, test, type Page } from "@playwright/test";
import { rowReviewWorkspace } from "../../src/features/import-review/RowReviewDrawer.fixtures";
const target = "/review-advanced/2026-08-10?report_type=business_report&version_id=51";
async function install(page: Page) {
  const workspace = rowReviewWorkspace("exclude"); const state = { failAdd: true, failState: true };
  const unexpected: string[] = []; const writes: { path: string; body: Record<string, unknown>; key: string }[] = [];
  await page.context().addCookies([{ name: "clsen_csrf", value: "synthetic-row", url: test.info().project.use.baseURL! }]);
  await page.context().route(url => url.pathname.startsWith("/api/"), async route => {
    const r = route.request(); const path = new URL(r.url()).pathname;
    if (r.method() !== "GET") {
      expect(r.headers()["x-csrf-token"]).toBe("synthetic-row"); const key = r.headers()["idempotency-key"]; expect(key).toMatch(/^[0-9a-f-]{36}$/);
      if (!key) throw new Error("Missing command key"); writes.push({ path, body: r.postDataJSON() as Record<string, unknown>, key });
    }
    const json = (value: unknown) => route.fulfill({ contentType: "application/json", body: JSON.stringify(value) });
    const fail = () => route.fulfill({ status: 503, contentType: "application/json", body: JSON.stringify({ error: { code: "outcome_unknown", message: "虚构响应未确认" } }) });
    if (path === "/api/auth/me") return json({ id: 88, username: "fictional-reviewer", display_name: "虚构审核员", roles: ["data_manager"] });
    if (path === "/api/data-calendar/site-context") return json({ site_id: 1, site_code: "US", display_name: "虚构站点", site_config_version_id: 2, source_timezone: "UTC", reporting_timezone: "UTC", currency_code: "USD" });
    if (path === "/api/data-calendar") return json([{ report_date: "2026-08-10", report_type: "business_report", dataset_id: 41, version_id: 51, version_no: 2, status: workspace.head.status }]);
    if (["/api/data-calendar/days", "/api/versions", "/api/imports/11/notes"].includes(path)) return json([]);
    if (path === "/api/drafts/51/review-workspace") return json(workspace);
    const command = writes.at(-1)?.body;
    const pointer = { dataset_id: 41, status: "draft", data_revision: workspace.head.data_revision, review_revision: workspace.head.review_revision, pointed_at: workspace.head.pointed_at };
    if (path === "/api/drafts/51/rows") {
      expect(command).toEqual({ ...pointer, source_batch_id: 11, values: { sku: { type: "text", value: "A-02" }, sales: { type: "decimal", value: "55.10" } }, reason: "虚构补录核对" });
      if (state.failAdd) return fail();
      workspace.head.data_revision += 1;
      workspace.rows.push({ row_id: 102, row_ordinal: 2, logical_row_id: "22222222-2222-4222-8222-222222222222", row_state: "active", base_row_id: null, original_parsed_source_row_id: null, history: [], notes: [], cells: workspace.fields.map(f => ({ field_name: f.name, current: f.name === "sku" ? { type: "text", value: "A-02" } : { type: "decimal", value: "55.10" }, base: null, source: null, changed_from_source: true, changed_from_base: true, history: [], notes: [], parent_restore_options: [], source_restore_option: null })) }); workspace.pagination.total_rows = 2;
      return json({ result: {} });
    }
    if (path === "/api/drafts/51/rows/101/state") {
      const operation = command?.operation; expect(["exclude", "restore"]).toContain(operation);
      expect(command).toEqual({ ...pointer, operation, reason: operation === "exclude" ? "虚构排除核对" : "虚构恢复核对" });
      if (state.failState) return fail();
      workspace.rows[0]!.row_state = operation === "exclude" ? "excluded" : "active"; workspace.head.data_revision += 1; return json({ result: {} });
    }
    if (path === "/api/drafts/51/notes") {
      expect(command).toEqual({ expected_review_revision: workspace.head.review_revision, target_type: "row", row_id: 101, field_name: null, body: "虚构行追加说明", visibility: "viewer_visible" });
      workspace.head.review_revision += 1; workspace.rows[0]!.notes.push({ ...workspace.rows[0]!.notes[0]!, note_key: "fictional-added-row-note", note_id: 812, body: "虚构行追加说明", visibility: "viewer_visible", review_revision: workspace.head.review_revision }); return json({ result: {} });
    }
    if (path === "/api/drafts/51/notes/fictional-row-note/revisions") {
      expect(command).toEqual({ expected_review_revision: workspace.head.review_revision, target_type: "row", row_id: 101, field_name: null, body: "虚构行新修订", visibility: "internal", expected_note_id: 811, expected_revision_number: 1 });
      const note = workspace.rows[0]!.notes[0]!; note.body = "虚构行新修订"; note.note_id = 813; note.revision_number += 1; workspace.head.review_revision += 1; return json({ result: {} });
    }
    unexpected.push(`${r.method()} ${path}`); return route.fulfill({ status: 500, body: "Unexpected fictional API" });
  });
  return { state, writes, unexpected };
}
for (const width of [1280, 390]) {
  test(`actual row add/retry, exclusion/recovery, notes and reload at ${width}px`, async ({ page }) => {
    await page.setViewportSize({ width, height: 900 }); const { state, writes, unexpected } = await install(page); const errors: string[] = []; page.on("pageerror", e => errors.push(e.message));
    await page.goto(target); const add = page.getByRole("button", { name: "新增纠错行", exact: true }); await add.click();
    let drawer = page.getByRole("dialog", { name: "新增纠错行", exact: true });
    await drawer.getByRole("textbox", { name: "新增行字段 sku", exact: true }).fill("A-02"); await drawer.getByRole("textbox", { name: "新增行字段 sales", exact: true }).fill("55.10"); await drawer.getByRole("textbox", { name: "新增原因", exact: true }).fill("虚构补录核对");
    await drawer.getByRole("button", { name: "保存新增行", exact: true }).click(); await expect(drawer.getByRole("alert")).toContainText("虚构响应未确认");
    await expect(drawer.getByRole("textbox", { name: "新增行字段 sales", exact: true })).toHaveValue("55.10"); state.failAdd = false;
    await drawer.getByRole("button", { name: "保存新增行", exact: true }).click(); await expect(drawer).toHaveCount(0); await expect(add).toBeFocused(); expect(writes[0]).toEqual(writes[1]);
    await expect(page.getByRole("button", { name: /sku，当前值 A-02/ })).toBeVisible(); await page.reload(); await expect(page.getByRole("button", { name: /sku，当前值 A-02/ })).toBeVisible();
    await page.getByRole("button", { name: "管理第 1 行状态，当前 active", exact: true }).click(); drawer = page.getByRole("dialog", { name: "行状态操作", exact: true });
    await drawer.getByRole("textbox", { name: "处理原因", exact: true }).fill("虚构排除核对"); await drawer.getByRole("button", { name: "排除这一行", exact: true }).click(); await expect(drawer.getByRole("alert")).toContainText("虚构响应未确认");
    await expect(drawer.getByRole("textbox", { name: "处理原因", exact: true })).toHaveValue("虚构排除核对"); state.failState = false;
    await drawer.getByRole("button", { name: "排除这一行", exact: true }).click(); await expect(drawer).toHaveCount(0); expect(writes[2]).toEqual(writes[3]);
    await page.reload(); await page.getByRole("button", { name: "管理第 1 行状态，当前 excluded", exact: true }).click();
    await drawer.getByRole("textbox", { name: "行备注内容", exact: true }).fill("虚构行追加说明"); await drawer.getByRole("combobox", { name: "行备注可见范围", exact: true }).selectOption("viewer_visible"); await drawer.getByRole("button", { name: "追加行备注", exact: true }).click(); await expect(drawer.getByText("虚构行追加说明", { exact: true })).toBeVisible();
    await drawer.getByRole("button", { name: "修订备注", exact: true }).first().click(); await drawer.getByRole("textbox", { name: "修订备注 fictional-row-note", exact: true }).fill("虚构行新修订"); await drawer.getByRole("button", { name: "保存新修订", exact: true }).click(); await expect(drawer.getByText("虚构行新修订", { exact: true })).toBeVisible();
    await drawer.getByRole("textbox", { name: "处理原因", exact: true }).fill("虚构恢复核对"); await drawer.getByRole("button", { name: "恢复这一行", exact: true }).click(); await expect(drawer).toHaveCount(0);
    const trigger = page.getByRole("button", { name: "管理第 1 行状态，当前 active", exact: true }); await expect(trigger).toBeFocused(); await page.reload(); await trigger.click();
    await expect(drawer.getByText("虚构行新修订", { exact: true })).toBeVisible(); await expect(drawer.getByText("虚构行追加说明", { exact: true })).toBeVisible();
    await page.keyboard.press("Escape"); await expect(drawer).toHaveCount(0); await expect(trigger).toBeFocused();
    expect(writes).toHaveLength(7); expect(errors).toEqual([]); expect(unexpected).toEqual([]); expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
  });
}
