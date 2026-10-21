import { expect, test, type Page } from "@playwright/test";
import { fieldReviewWorkspace } from "../../src/features/import-review/CellReviewDrawer.fixtures";
const target = "/review-advanced/2026-08-10?report_type=business_report&version_id=51";
async function install(page: Page) {
  const workspace = fieldReviewWorkspace();
  workspace.rows[0]!.notes = [{ ...workspace.rows[0]!.cells[1]!.notes[0]!, note_id: 811, note_key: "fictional-row-note", target_type: "row", field_name: null, body: "虚构行说明" }];
  const state = { fail: true }; const writes: { path: string; body: Record<string, unknown>; key: string }[] = []; const unexpected: string[] = [];
  await page.context().addCookies([{ name: "clsen_csrf", value: "synthetic-note", url: test.info().project.use.baseURL! }]);
  await page.context().route(url => url.pathname.startsWith("/api/"), async route => {
    const request = route.request(); const path = new URL(request.url()).pathname;
    const json = (value: unknown) => route.fulfill({ contentType: "application/json", body: JSON.stringify(value) });
    if (request.method() === "GET") {
      if (path === "/api/auth/me") return json({ id: 88, username: "fictional-reviewer", display_name: "虚构审核员", roles: ["data_manager"] });
      if (path === "/api/data-calendar/site-context") return json({ site_id: 1, site_code: "US", display_name: "虚构站点", site_config_version_id: 2, source_timezone: "UTC", reporting_timezone: "UTC", currency_code: "USD" });
      if (path === "/api/data-calendar") return json([{ report_date: "2026-08-10", report_type: "business_report", dataset_id: 41, version_id: 51, version_no: 2, status: "draft" }]);
      if (["/api/data-calendar/days", "/api/versions", "/api/imports/11/notes"].includes(path)) return json([]);
      if (path === "/api/drafts/51/review-workspace") return json(workspace);
    }
    if (request.method() === "POST" && path.startsWith("/api/drafts/51/notes/") && path.endsWith("/revisions")) {
      expect(request.headers()["x-csrf-token"]).toBe("synthetic-note");
      const key = request.headers()["idempotency-key"]; expect(key).toMatch(/^[0-9a-f-]{36}$/); if (!key) throw new Error("Missing command key");
      const body = request.postDataJSON() as Record<string, unknown>; writes.push({ path, body, key });
      const note = [...workspace.version_notes, ...workspace.rows[0]!.notes, ...workspace.rows[0]!.cells[1]!.notes].find(note => path.includes(`/${note.note_key}/`));
      if (!note) throw new Error("Unexpected note identity");
      expect(body).toEqual({ expected_review_revision: workspace.head.review_revision, target_type: note.target_type, row_id: note.row_id, field_name: note.field_name, body: `  虚构${note.target_type}新修订  `, visibility: "viewer_visible", expected_note_id: note.note_id, expected_revision_number: note.revision_number });
      if (state.fail) return route.fulfill({ status: 503, json: { error: { code: "outcome_unknown", message: "虚构修订响应未确认" } } });
      note.body = String(body.body); note.visibility = "viewer_visible"; note.note_id += 100; note.revision_number += 1; workspace.head.review_revision += 1;
      return json({ result: {} });
    }
    unexpected.push(`${request.method()} ${path}`); return route.fulfill({ status: 500, body: "Unexpected fictional API" });
  });
  return { state, writes, unexpected };
}
for (const width of [1280, 390]) {
  test(`actual version/row/field note revision retry, visibility and reload at ${width}px`, async ({ page }) => {
    await page.setViewportSize({ width, height: 900 }); const { state, writes, unexpected } = await install(page); const errors: string[] = []; page.on("pageerror", error => errors.push(error.message));
    await page.goto(target);
    for (const scope of ["version", "row", "field"] as const) {
      if (scope === "row") await page.getByRole("button", { name: "管理第 1 行状态，当前 active", exact: true }).click();
      if (scope === "field") await page.getByRole("button", { name: /sales，当前值 42.50/ }).click();
      const key = scope === "version" ? "version-note-1" : scope === "row" ? "fictional-row-note" : "fictional-field-note";
      const host = scope === "version" ? page.locator(".version-note-list li").first() : page.getByRole("dialog").locator("li").filter({ has: page.getByRole("button", { name: "修订备注", exact: true }) }).first();
      const trigger = host.getByRole("button", { name: "修订备注", exact: true }); await trigger.click();
      const form = page.getByRole("form", { name: `备注修订 ${key}`, exact: true });
      await expect(form.getByRole("textbox")).toBeFocused();
      await form.getByRole("textbox").fill(`  虚构${scope}新修订  `); await form.getByRole("combobox").selectOption("viewer_visible");
      state.fail = true; const first = writes.length; await form.getByRole("button", { name: "保存新修订", exact: true }).click();
      await expect(form.getByRole("alert")).toContainText("虚构修订响应未确认");
      await expect(form.getByRole("textbox")).toHaveValue(`  虚构${scope}新修订  `); await expect(form.getByRole("combobox")).toHaveValue("viewer_visible"); expect(writes).toHaveLength(first + 1);
      state.fail = false; await form.getByRole("button", { name: "保存新修订", exact: true }).click(); await expect(form).toHaveCount(0); await expect(trigger).toBeFocused(); expect(writes[first]).toEqual(writes[first + 1]);
      await expect(host).toContainText(`虚构${scope}新修订`); await expect(host).toContainText("查看人员可见"); await expect(host).toContainText("第 2 版");
      await page.reload();
      if (scope === "row") await page.getByRole("button", { name: "管理第 1 行状态，当前 active", exact: true }).click();
      if (scope === "field") await page.getByRole("button", { name: /sales，当前值 42.50/ }).click();
      await expect(host).toContainText(`虚构${scope}新修订`); await trigger.click();
      await expect(form.getByRole("textbox")).toHaveValue(`  虚构${scope}新修订  `); await expect(form.getByRole("combobox")).toHaveValue("viewer_visible");
      await form.getByRole("button", { name: "取消修订", exact: true }).click(); await expect(trigger).toBeFocused();
      if (scope !== "version") { await page.keyboard.press("Escape"); await expect(page.getByRole("dialog")).toHaveCount(0); }
    }
    expect(writes).toHaveLength(6); expect(unexpected).toEqual([]); expect(errors).toEqual([]);
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
  });
}
