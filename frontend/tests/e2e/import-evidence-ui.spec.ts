import { expect, test, type Page } from "@playwright/test";
import { evidenceNote, evidencePreview } from "../../src/features/import-review/ImportEvidence.fixtures";
import { intakeInspection } from "../../src/features/import-review/ImportIntakeView.fixtures";
import { draftWorkspace } from "../../src/features/import-review/DraftReviewView.fixtures";

async function install(page: Page) {
  const state = { sourceFailure: true, notesFailure: true, appendFailure: true, revisionFailure: true, sourceReads: 0 };
  let notes = [structuredClone(evidenceNote)];
  const writes: { path: string; body: Record<string, unknown>; key?: string }[] = [];
  const unexpected: string[] = [];
  await page.context().addCookies([{ name: "clsen_csrf", value: "synthetic-evidence", url: test.info().project.use.baseURL! }]);
  await page.context().route(url => url.pathname.startsWith("/api/"), async route => {
    const request = route.request(); const url = new URL(request.url()); const path = url.pathname;
    const fail = (message: string) => route.fulfill({ status: 503, json: { error: { code: "synthetic_unavailable", message } } });
    if (!["GET", "HEAD"].includes(request.method())) {
      expect(request.headers()["x-csrf-token"]).toBe("synthetic-evidence");
      writes.push({ path, body: request.postDataJSON() as Record<string, unknown>, key: request.headers()["idempotency-key"] });
    }
    if (path === "/api/auth/me") return route.fulfill({ json: { id: 88, username: "fictional-reviewer", display_name: "虚构审核员", roles: ["data_manager"] } });
    if (path === "/api/data-calendar/site-context") return route.fulfill({ json: { site_id: 1, site_code: "US", display_name: "虚构站点", site_config_version_id: 2, source_timezone: "UTC", reporting_timezone: "UTC", currency_code: "USD" } });
    if (path === "/api/data-calendar") return route.fulfill({ json: [{ report_date: "2026-08-10", report_type: "business_report", dataset_id: 41, version_id: 51, version_no: 2, status: "draft" }] });
    if (["/api/data-calendar/days", "/api/versions"].includes(path)) return route.fulfill({ json: [] });
    if (path === "/api/imports/81/inspect") return route.fulfill({ json: intakeInspection });
    if (path === "/api/imports/81/raw-file") return route.fulfill({ body: "sku,units\nDEMO-001,1" });
    if (path === "/api/imports/81/raw-file/preview") {
      state.sourceReads++; expect(url.searchParams.get("encoding")).toBe("utf-8-sig"); expect(url.searchParams.get("row_limit")).toBe("200");
      return state.sourceFailure ? fail("虚构源表读取失败") : route.fulfill({ json: evidencePreview });
    }
    if (path === "/api/imports/81/notes") {
      if (request.method() === "GET") return state.notesFailure ? fail("虚构备注读取失败") : route.fulfill({ json: notes });
      const command = writes.at(-1)!; expect(command.body.visibility).toBe("internal"); expect(command.key).toMatch(/^[0-9a-f-]{36}$/);
      if (state.appendFailure) return fail("虚构追加未完成");
      notes = [...notes, { ...evidenceNote, body: String(command.body.body), note_key: "demo-batch-note-2", note_id: 802 }];
      return route.fulfill({ json: { result: { note_key: "demo-batch-note-2" } } });
    }
    if (path === "/api/imports/81/notes/demo-batch-note-1/revisions") {
      const command = writes.at(-1)!; expect(command.body).toEqual({ body: "虚构复核后的说明", visibility: "internal", expected_note_id: 801, expected_revision_number: 1 }); expect(command.key).toMatch(/^[0-9a-f-]{36}$/);
      if (state.revisionFailure) return fail("虚构修订未完成");
      notes = notes.map(note => note.note_key === "demo-batch-note-1" ? { ...note, body: String(command.body.body), note_id: 803, revision_number: 2 } : note);
      return route.fulfill({ json: { result: { note_key: "demo-batch-note-1" } } });
    }
    if (path === "/api/drafts/51/review-workspace") return route.fulfill({ json: { ...draftWorkspace, source_batches: [{ batch_id: 81 }] } });
    unexpected.push(`${request.method()} ${path}`); return fail("未定义的测试请求");
  });
  return { state, writes, unexpected };
}

for (const width of [1280, 390]) {
  test(`actual source read, note writes, retries and reload at ${width}px`, async ({ page }) => {
    await page.setViewportSize({ width, height: 900 });
    const { state, writes, unexpected } = await install(page);
    const errors: string[] = []; page.on("pageerror", error => errors.push(error.message));
    await page.goto("/review-advanced/2026-09-12?report_type=business_report&batch_id=81");
    const source = page.getByRole("region", { name: "上传源表预览", exact: true });
    await source.getByRole("button", { name: "查看上传源表", exact: true }).click(); await expect(source.getByRole("alert")).toContainText("虚构源表读取失败");
    state.sourceFailure = false; await source.getByRole("button", { name: "重试", exact: true }).click();
    await expect(source.getByRole("table", { name: "上传源表数据", exact: true })).toBeVisible();
    const search = source.getByRole("searchbox", { name: "搜索预览行", exact: true }); await search.fill("DEMO-003");
    await expect(source.getByRole("rowheader", { name: "3", exact: true })).toBeVisible(); await search.fill("missing-row"); await expect(source.getByText("没有找到符合条件的预览记录。", { exact: true })).toBeVisible();
    await search.fill(""); await source.getByRole("button", { name: "下一页", exact: true }).click(); await expect(source.getByRole("rowheader", { name: "51", exact: true })).toBeVisible();
    await source.getByRole("button", { name: "收起源表", exact: true }).click(); await source.getByRole("button", { name: "查看上传源表", exact: true }).click(); expect(state.sourceReads).toBe(2);
    const panel = page.getByRole("region", { name: "导入批次 #81 备注", exact: true });
    await panel.getByRole("button", { name: "管理批次备注", exact: true }).click(); await expect(panel.getByRole("alert")).toContainText("虚构备注读取失败");
    await expect(panel.getByRole("button", { name: "追加批次备注", exact: true })).toBeDisabled(); state.notesFailure = false;
    await panel.getByRole("button", { name: "重新加载批次备注", exact: true }).click(); await expect(panel.getByText(evidenceNote.body, { exact: true })).toBeVisible();
    await panel.getByRole("textbox", { name: "批次备注内容", exact: true }).fill("虚构追加说明"); await panel.getByRole("button", { name: "追加批次备注", exact: true }).click();
    await expect(panel.getByRole("alert")).toContainText("虚构追加未完成"); await expect(panel.getByRole("textbox", { name: "批次备注内容", exact: true })).toHaveValue("虚构追加说明");
    state.appendFailure = false; await panel.getByRole("button", { name: "追加批次备注", exact: true }).click(); await expect(panel.getByText("虚构追加说明", { exact: true })).toBeVisible();
    const append = writes.filter(write => write.path === "/api/imports/81/notes"); expect(append).toHaveLength(2); expect(append[1]?.key).toBe(append[0]?.key); expect(append[1]?.body).toEqual({ body: "虚构追加说明", visibility: "internal" });
    await panel.getByRole("button", { name: "修订备注", exact: true }).first().click(); const editor = panel.getByRole("textbox", { name: "修订备注 demo-batch-note-1", exact: true });
    await editor.fill("虚构复核后的说明"); await expect(panel.getByRole("combobox")).toHaveCount(0); await panel.getByRole("button", { name: "保存新修订", exact: true }).click();
    await expect(editor).toHaveValue("虚构复核后的说明"); await expect(panel.getByText("备注修订未保存", { exact: true })).toBeVisible();
    state.revisionFailure = false; await panel.getByRole("button", { name: "保存新修订", exact: true }).click(); await expect(panel.getByText("虚构复核后的说明", { exact: true })).toBeVisible(); await expect(panel.getByText("第 2 版", { exact: true })).toBeVisible();
    const revisions = writes.filter(write => write.path.endsWith("/revisions")); expect(revisions).toHaveLength(2); expect(revisions[1]?.key).toBe(revisions[0]?.key);
    await page.reload(); await panel.getByRole("button", { name: "管理批次备注", exact: true }).click(); await expect(panel.getByText("虚构复核后的说明", { exact: true })).toBeVisible(); await expect(panel.getByText("虚构追加说明", { exact: true })).toBeVisible();
    // The same shared controller is also mounted in the actual draft evidence sidebar.
    await page.goto("/review-advanced/2026-08-10?report_type=business_report&version_id=51"); await panel.getByRole("button", { name: "管理批次备注", exact: true }).click(); await expect(panel.getByText("虚构复核后的说明", { exact: true })).toBeVisible();
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
    expect(errors).toEqual([]); expect(unexpected).toEqual([]);
  });
}
