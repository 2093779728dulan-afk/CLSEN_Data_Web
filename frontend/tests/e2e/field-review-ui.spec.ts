import { expect, test, type Page } from "@playwright/test";
import { fieldReviewWorkspace } from "../../src/features/import-review/CellReviewDrawer.fixtures";
const target = "/review-advanced/2026-08-10?report_type=business_report&version_id=51";
async function install(page: Page) {
  const workspace = fieldReviewWorkspace();
  const state = { failSave: true }; const unexpected: string[] = [];
  const writes: { path: string; body: Record<string, unknown>; key: string }[] = [];
  await page.context().addCookies([{ name: "clsen_csrf", value: "synthetic-field", url: test.info().project.use.baseURL! }]);
  await page.context().route(url => url.pathname.startsWith("/api/"), async route => {
    const r = route.request(); const path = new URL(r.url()).pathname;
    if (r.method() !== "GET") {
      expect(r.headers()["x-csrf-token"]).toBe("synthetic-field");
      const key = r.headers()["idempotency-key"]; expect(key).toMatch(/^[0-9a-f-]{36}$/);
      if (!key) throw new Error("Missing command key");
      writes.push({ path, body: r.postDataJSON() as Record<string, unknown>, key });
    }
    const json = (value: unknown) => route.fulfill({ contentType: "application/json", body: JSON.stringify(value) });
    if (path === "/api/auth/me") return json({ id: 88, username: "fictional-reviewer", display_name: "虚构审核员", roles: ["data_manager"] });
    if (path === "/api/data-calendar/site-context") return json({ site_id: 1, site_code: "US", display_name: "虚构站点", site_config_version_id: 2, source_timezone: "UTC", reporting_timezone: "UTC", currency_code: "USD" });
    if (path === "/api/data-calendar") return json([{ report_date: "2026-08-10", report_type: "business_report", dataset_id: 41, version_id: 51, version_no: 2, status: workspace.head.status }]);
    if (["/api/data-calendar/days", "/api/versions", "/api/imports/11/notes"].includes(path)) return json([]);
    if (path === "/api/drafts/51/review-workspace") return json(workspace);
    const command = writes.at(-1)?.body;
    if (path === "/api/drafts/51/fields") {
      expect(command).toEqual({ dataset_id: 41, status: "draft", data_revision: workspace.head.data_revision, review_revision: workspace.head.review_revision, pointed_at: workspace.head.pointed_at, row_id: 101, field_name: "sales", value: { type: "decimal", value: "44.20" }, reason: "虚构字段核对" });
      if (state.failSave) return route.fulfill({ status: 503, contentType: "application/json", body: JSON.stringify({ error: { code: "outcome_unknown", message: "虚构响应未确认" } }) });
      workspace.rows[0]!.cells[1]!.current = { type: "decimal", value: "44.20" }; workspace.head.data_revision += 1;
      return json({ result: {} });
    }
    if (path === "/api/drafts/51/fields/sales/restore") {
      expect(command).toMatchObject({ dataset_id: 41, status: "draft", data_revision: workspace.head.data_revision, review_revision: workspace.head.review_revision, pointed_at: workspace.head.pointed_at, row_id: 101, reason: "虚构字段核对" });
      const cell = workspace.rows[0]!.cells[1]!;
      if (command?.source_kind === "parent") { expect(command.parent_version_id).toBe(49); cell.current = cell.parent_restore_options[0]!.value; }
      else if (command?.source_kind === "source") { expect(command).toMatchObject({ source_batch_id: 11, parsed_source_row_id: 301 }); cell.current = cell.source_restore_option!.value; }
      else { expect(command).toMatchObject({ source_kind: "previous", field_change_id: 501 }); cell.current = cell.history[0]!.before; }
      workspace.head.data_revision += 1; return json({ result: {} });
    }
    if (path === "/api/drafts/51/notes") {
      expect(command).toEqual({ expected_review_revision: workspace.head.review_revision, target_type: "field", row_id: 101, field_name: "sales", body: "虚构追加说明", visibility: "viewer_visible" });
      workspace.head.review_revision += 1;
      workspace.rows[0]!.cells[1]!.notes.push({ ...workspace.rows[0]!.cells[1]!.notes[0]!, note_key: "fictional-added-note", note_id: 802, body: "虚构追加说明", visibility: "viewer_visible", review_revision: workspace.head.review_revision });
      return json({ result: {} });
    }
    if (path === "/api/drafts/51/notes/fictional-field-note/revisions") {
      expect(command).toEqual({ expected_review_revision: workspace.head.review_revision, target_type: "field", row_id: 101, field_name: "sales", body: "虚构新修订", visibility: "internal", expected_note_id: 801, expected_revision_number: 1 });
      const note = workspace.rows[0]!.cells[1]!.notes[0]!; note.body = "虚构新修订"; note.revision_number += 1; note.note_id = 803; workspace.head.review_revision += 1;
      return json({ result: {} });
    }
    unexpected.push(`${r.method()} ${path}`); return route.fulfill({ status: 500, body: "Unexpected fictional request" });
  });
  return { state, writes, unexpected };
}
for (const width of [1280, 390]) {
  test(`actual field edit retry, stable restore identifiers, notes and reload at ${width}px`, async ({ page }) => {
    await page.setViewportSize({ width, height: 900 }); const { state, writes, unexpected } = await install(page);
    const errors: string[] = []; page.on("pageerror", error => errors.push(error.message));
    await page.goto(target); await page.getByRole("button", { name: /sales，当前值 42.50/ }).click();
    const drawer = page.getByRole("dialog", { name: "字段对照", exact: true });
    await drawer.getByRole("textbox", { name: "当前值", exact: true }).fill("44.20");
    await drawer.getByRole("textbox", { name: "修改原因", exact: true }).fill("虚构字段核对");
    await drawer.getByRole("button", { name: "保存字段修改", exact: true }).click();
    await expect(drawer.getByRole("alert")).toContainText("虚构响应未确认");
    await expect(drawer.getByRole("textbox", { name: "当前值", exact: true })).toHaveValue("44.20");
    await expect(drawer.getByRole("textbox", { name: "修改原因", exact: true })).toHaveValue("虚构字段核对");
    state.failSave = false; await drawer.getByRole("button", { name: "保存字段修改", exact: true }).click();
    await expect(drawer.getByText("当前草稿值", { exact: true }).locator("..")).toContainText("44.20");
    expect(writes.filter(w => w.path.endsWith("/fields"))).toHaveLength(2); expect(writes[0]).toEqual(writes[1]);
    for (const [label, value] of [["恢复父版本值", "40.00"], ["恢复源文件值", "39.00"], ["撤销本次修改", "40.00"]] as const) {
      await drawer.getByRole("textbox", { name: "恢复原因", exact: true }).fill("虚构字段核对");
      await drawer.getByRole("button", { name: label, exact: true }).click();
      await expect(drawer.getByRole("textbox", { name: "当前值", exact: true })).toHaveValue(value);
    }
    await drawer.getByRole("textbox", { name: "备注内容", exact: true }).fill("虚构追加说明");
    await drawer.getByRole("combobox", { name: "可见范围", exact: true }).selectOption("viewer_visible");
    await drawer.getByRole("button", { name: "追加字段备注", exact: true }).click();
    await expect(drawer.getByText("虚构追加说明", { exact: true })).toBeVisible();
    await drawer.getByRole("button", { name: "修订备注", exact: true }).first().click();
    await drawer.getByRole("textbox", { name: "修订备注 fictional-field-note", exact: true }).fill("虚构新修订");
    await drawer.getByRole("button", { name: "保存新修订", exact: true }).click();
    await expect(drawer.getByText("虚构新修订", { exact: true })).toBeVisible();
    const close = drawer.getByRole("button", { name: "关闭字段对照", exact: true });
    await expect(close).toBeEnabled();
    await close.focus(); await close.press("Escape"); await expect(drawer).toHaveCount(0);
    await expect(page.getByRole("button", { name: /sales，当前值 40.00/ })).toBeFocused();
    await page.reload(); await page.getByRole("button", { name: /sales，当前值 40.00/ }).click();
    await expect(drawer.getByText("虚构新修订", { exact: true })).toBeVisible();
    await expect(drawer.getByText("虚构追加说明", { exact: true })).toBeVisible();
    await expect(drawer.getByRole("textbox", { name: "当前值", exact: true })).toHaveValue("40.00");
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
    expect(writes).toHaveLength(7); expect(errors).toEqual([]); expect(unexpected).toEqual([]);
  });
}
