import { expect, test, type Page } from "@playwright/test";
import { draftWorkspace, readyDraftWorkspace, validationFor } from "../../src/features/import-review/DraftReviewView.fixtures";

const target = "/review-advanced/2026-08-10?report_type=business_report&version_id=51";
async function install(page: Page, role = "data_manager", failRead = false) {
  let workspace = structuredClone(draftWorkspace);
  let reads = 0;
  const state = { publishFailure: true, published: false };
  const writes: { path: string; body: Record<string, unknown>; key: string }[] = [];
  const unexpected: string[] = [];
  await page.context().addCookies([{ name: "clsen_csrf", value: "synthetic-draft", url: test.info().project.use.baseURL! }]);
  await page.context().route(url => url.pathname.startsWith("/api/"), async route => {
    const r = route.request(); const path = new URL(r.url()).pathname; const method = r.method();
    if (method !== "GET") {
      expect(role).toBe("data_manager"); expect(r.headers()["x-csrf-token"]).toBe("synthetic-draft");
      const key = r.headers()["idempotency-key"];
      expect(key).toMatch(/^[0-9a-f-]{36}$/);
      if (!key) throw new Error("Command must include an idempotency key.");
      writes.push({ path, body: r.postDataJSON() as Record<string, unknown>, key });
    }
    if (path === "/api/auth/me") return route.fulfill({ json: { id: 88, username: "fictional-reviewer", display_name: "虚构审核员", roles: [role] } });
    if (path === "/api/data-calendar/site-context") return route.fulfill({ json: { site_id: 1, site_code: "US", display_name: "虚构站点", site_config_version_id: 2, source_timezone: "UTC", reporting_timezone: "UTC", currency_code: "USD" } });
    if (path === "/api/data-calendar") return route.fulfill({ json: [{ report_date: "2026-08-10", report_type: "business_report", dataset_id: 41, version_id: 51, version_no: 2, status: workspace.head.status }] });
    if (path === "/api/data-calendar/days" || path === "/api/versions" || path === "/api/imports/11/notes") return route.fulfill({ json: [] });
    if (path === "/api/drafts/51/review-workspace") {
      reads += 1;
      // React StrictMode reads the resume context twice, then mounts the gate with two reads.
      if (failRead && reads >= 3 && reads <= 4) return route.fulfill({ status: 503, json: { error: { code: "synthetic_unavailable", message: "虚构草稿读取失败" } } });
      return route.fulfill({ json: workspace });
    }
    if (path === "/api/validation-runs/51") {
      expect(writes.at(-1)?.body).toEqual({ dataset_id: 41, data_revision: 3, ruleset_version: "business_report_v1" });
      workspace = structuredClone(readyDraftWorkspace()); workspace.head.status = "draft"; workspace.head.review_revision = 1;
      return route.fulfill({ json: validationFor(workspace) });
    }
    if (path === "/api/drafts/51/mark-ready") {
      expect(writes.at(-1)?.body).toEqual({ dataset_id: 41, status: "draft", data_revision: 3, review_revision: 1, pointed_at: draftWorkspace.head.pointed_at, validation_run_id: 901, validation_data_digest: "d".repeat(64), ruleset_version: "business_report_v1", confirmed_report_date: "2026-08-10", confirmed_report_type: "business_report", confirmed_row_count: 1, confirmed_totals: { sales: "42.50" }, reason: "已核对虚构源表与合计" });
      workspace = structuredClone(readyDraftWorkspace()); return route.fulfill({ json: workspace.head });
    }
    if (path === "/api/datasets/41/publish") {
      expect(writes.at(-1)?.body).toEqual({ expected_draft: { version_id: 51, status: "ready_for_publish", data_revision: 3, review_revision: 2, pointed_at: draftWorkspace.head.pointed_at }, expected_publication: { version_id: null, published_at: null }, validation: { run_id: 901, version_id: 51, data_revision: 3, ruleset_version: "business_report_v1", data_digest: "d".repeat(64) }, confirmation: { confirmed_report_date: "2026-08-10", report_type: "business_report", row_count: 1, totals: [{ field_name: "sales", value: "42.50" }] }, reason: "虚构发布核验" });
      if (state.publishFailure) return route.fulfill({ status: 503, json: { error: { code: "synthetic_unavailable", message: "虚构发布暂不可用" } } });
      state.published = true;
      return route.fulfill({ json: { dataset_id: 41, version_id: 51, published_at: "2026-08-10T04:00:00Z" } });
    }
    if (role === "viewer" && path === "/api/dashboard/daily-ledger") return route.fulfill({ json: { publications: [], site_config_versions: [], rows: [], range: { from_date: "2026-08-10", to_date: "2026-08-10" } } });
    if (role === "viewer" && path.includes("workbench")) return route.fulfill({ status: 404, json: { error: { code: "synthetic_no_data", message: "虚构日期无发布数据" } } });
    unexpected.push(`${method} ${path}`); return route.fulfill({ status: 500, json: { error: { code: "unexpected", message: "测试未定义该请求" } } });
  });
  return { state, writes, unexpected };
}

for (const width of [1280, 390]) {
  test(`actual draft validates, refreshes confirmation, preserves publication retry at ${width}px`, async ({ page }) => {
    await page.setViewportSize({ width, height: 900 }); const { state, writes, unexpected } = await install(page, "data_manager", true);
    const errors: string[] = []; page.on("pageerror", error => errors.push(error.message));
    await page.goto(target);
    await expect(page.getByRole("heading", { name: "无法读取草稿", exact: true })).toBeVisible();
    await page.getByRole("button", { name: "重新读取草稿", exact: true }).click();
    await expect(page.getByText("初次审核说明", { exact: true })).toBeVisible();
    await page.getByRole("button", { name: "运行草稿校验", exact: true }).click();
    await page.getByRole("textbox", { name: "审核确认说明", exact: true }).fill("已核对虚构源表与合计");
    await page.getByRole("button", { name: "确认结果并标记待发布", exact: true }).click();
    await expect(page.getByRole("button", { name: "打开发布确认", exact: true })).toBeVisible();
    await page.reload();
    await page.getByRole("button", { name: "打开发布确认", exact: true }).click();
    let dialog = page.getByRole("dialog", { name: "发布确认", exact: true });
    await dialog.getByRole("button", { name: "返回审核", exact: true }).last().click();
    expect(writes.filter(w => w.path.endsWith("/publish"))).toHaveLength(0);
    await page.getByRole("button", { name: "打开发布确认", exact: true }).click();
    dialog = page.getByRole("dialog", { name: "发布确认", exact: true });
    await dialog.getByRole("textbox", { name: "发布说明", exact: true }).fill("虚构发布核验");
    await dialog.getByRole("button", { name: "确认发布", exact: true }).click();
    await expect(dialog.getByRole("alert")).toContainText("虚构发布暂不可用");
    await expect(dialog.getByRole("textbox", { name: "发布说明", exact: true })).toHaveValue("虚构发布核验");
    state.publishFailure = false;
    await dialog.getByRole("button", { name: "确认发布", exact: true }).click();
    await expect(page.getByRole("heading", { name: "版本 v2 已发布", exact: true })).toBeVisible();
    const publications = writes.filter(w => w.path.endsWith("/publish"));
    expect(publications).toHaveLength(2); expect(publications[0]).toEqual(publications[1]); expect(state.published).toBe(true);
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
    expect(errors).toEqual([]); expect(unexpected).toEqual([]);
  });
}

test("actual viewer cannot open draft or trigger commands", async ({ page }) => {
  const { writes, unexpected } = await install(page, "viewer"); await page.goto(target);
  await expect(page).toHaveURL(/\/published\/2026-08-10/);
  await expect(page.getByRole("region", { name: "单日只读发布详情", exact: true })).toBeVisible();
  await expect(page.getByRole("button", { name: "运行草稿校验", exact: true })).toHaveCount(0);
  expect(writes).toEqual([]); expect(unexpected).toEqual([]);
});
