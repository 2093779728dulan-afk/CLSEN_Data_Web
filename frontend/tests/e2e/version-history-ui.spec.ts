import { expect, test, type Page } from "@playwright/test";
import { current, historical, draft, detailFor } from "../../src/features/versions/VersionHistoryView.fixtures";
import { sampleWorkbench } from "../../src/features/workbench/DateWorkbenchView.fixtures";

const returnVersions = [current, historical, draft].map(version => ({ ...version, dataset_id: 61, version_id: version.version_id + 100, report_type: "return_report" as const }));

async function install(page: Page, role = "viewer") {
  const state = { readFailure: false, detailFailure: false, rowsFailure: false, activeDraft: false };
  const requests: { path: string; method: string }[] = [];
  await page.context().route(url => url.pathname.startsWith("/api/"), async route => {
    const url = new URL(route.request().url()); const method = route.request().method();
    requests.push({ path: url.pathname + url.search, method });
    expect(method).toBe("GET");
    if (url.pathname === "/api/auth/me") return route.fulfill({ json: { id: 88, username: "synthetic-version", display_name: "虚构版本账号", roles: [role] } });
    if (url.pathname === "/api/data-calendar/site-context") return route.fulfill({ json: { site_id: 1, site_code: "US", display_name: "虚构站点", site_config_version_id: 2, source_timezone: "UTC", reporting_timezone: "UTC", currency_code: "USD" } });
    if (url.pathname === "/api/admin/published-moves/undoable") { expect(role).toBe("admin"); return route.fulfill({ json: [] }); }
    if (url.pathname === "/api/imports/batch-reviews") { expect(role).not.toBe("viewer"); const second = url.searchParams.get("page") === "2"; return route.fulfill({ json: { items: [{ id: second ? 82 : 81, status: "completed", revision: 4 }], has_next: !second } }); }
    if (url.pathname === "/api/versions") {
      if (state.readFailure) return route.fulfill({ status: 503, json: { error: { code: "UNAVAILABLE", message: "虚构版本读取失败" } } });
      const values = url.searchParams.has("batch_review_run_id") ? [draft] : url.searchParams.get("report_date") === "2026-09-13" ? [] : [current, historical, ...(state.activeDraft || role === "viewer" ? [draft] : [])];
      return route.fulfill({ json: url.searchParams.get("report_type") === "return_report" ? values.map(v => returnVersions.find(r => r.version_id === v.version_id + 100)) : values });
    }
    if (/^\/api\/versions\/\d+\/rows$/.test(url.pathname)) {
      if (state.rowsFailure) return route.fulfill({ status: 503, json: { error: { code: "UNAVAILABLE", message: "虚构版本行读取失败" } } });
      const workbench = sampleWorkbench("published"); const pageNo = Number(url.searchParams.get("page"));
      return route.fulfill({ json: { version_id: Number(url.pathname.split("/")[3]), columns: workbench.columns, rows: [{ ...workbench.rows[0]!, row_ordinal: pageNo === 1 ? 1 : 51 }], pagination: { page: pageNo, total_rows: 51, total_pages: 2 } } });
    }
    if (/^\/api\/versions\/\d+$/.test(url.pathname)) {
      if (state.detailFailure) return route.fulfill({ status: 503, json: { error: { code: "UNAVAILABLE", message: "虚构详情读取失败" } } });
      const id = Number(url.pathname.split("/").at(-1)); const version = [current, historical, draft, ...returnVersions].find(v => v.version_id === id)!;
      return route.fulfill({ json: { ...detailFor(version), children: [{ ...(version.report_type === "return_report" ? returnVersions[2] : draft), lineage_type: "draft_predecessor", lineage_ordinal: 0 }] } });
    }
    throw new Error(`Unexpected synthetic request: ${method} ${url.pathname}`);
  });
  return { state, requests };
}

for (const width of [1280, 390]) {
  test(`actual viewer version history recovery, fixed ID reads and refreshed scope at ${width}px`, async ({ page }) => {
    await page.setViewportSize({ width, height: 900 }); const { state, requests } = await install(page); state.readFailure = true;
    await page.goto("/versions?report_date=2026-09-12&report_type=business_report");
    await expect(page.getByRole("alert")).toContainText("虚构版本读取失败"); state.readFailure = false;
    await page.getByRole("button", { name: "重新读取版本记录", exact: true }).click();
    await expect(page.getByRole("heading", { name: "v3 · 当前发布", exact: true })).toBeVisible();
    await expect(page.getByRole("button", { name: /查看版本 v4/ })).toHaveCount(0);
    await expect(page.getByRole("button", { name: "创建修订", exact: true })).toHaveCount(0);
    state.detailFailure = true; await page.getByRole("button", { name: "查看版本 v1，历史发布" }).click();
    await expect(page.getByRole("alert")).toContainText("虚构详情读取失败"); state.detailFailure = false;
    await page.getByRole("button", { name: "查看版本 v1，历史发布" }).click();
    await expect(page.getByRole("heading", { name: "v1 · 历史发布", exact: true })).toBeVisible();
    state.rowsFailure = true; await page.getByRole("button", { name: "查看此版本数据", exact: true }).click();
    await expect(page.getByRole("alert")).toContainText("虚构版本行读取失败"); state.rowsFailure = false;
    await page.getByRole("button", { name: "重新读取", exact: true }).click();
    const rows = page.getByRole("region", { name: "v1 数据明细", exact: true });
    await expect(rows.getByRole("table")).toBeVisible();
    await rows.getByRole("button", { name: "下一页", exact: true }).click(); await expect(rows.getByRole("rowheader", { name: "51", exact: true })).toBeVisible();
    expect(requests.some(r => r.path === "/api/versions/51/rows?page=2&page_size=50")).toBe(true);
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
    await page.getByRole("combobox", { name: "报表类型", exact: true }).selectOption("return_report");
    await expect(page).toHaveURL(/report_type=return_report/); await page.reload();
    await expect(page.getByRole("combobox", { name: "报表类型", exact: true })).toHaveValue("return_report");
    await expect(page.getByRole("link", { name: "返回日期工作台", exact: true }).last()).toHaveAttribute("href", "/published/2026-09-12?report_type=return_report");
    await page.getByLabel("报告日期", { exact: true }).fill("2026-09-13"); await expect(page).toHaveURL(/report_date=2026-09-13/);
    await expect(page.getByText("该日期的退货报告还没有版本。", { exact: true })).toBeVisible(); await page.reload();
    await expect(page.getByLabel("报告日期", { exact: true })).toHaveValue("2026-09-13");
    await page.goBack();
    await expect(page.getByLabel("报告日期", { exact: true })).toHaveValue("2026-09-12");
    await expect(page.getByRole("heading", { name: "v3 · 当前发布", exact: true })).toBeVisible();
    await page.goForward();
    await expect(page.getByText("该日期的退货报告还没有版本。", { exact: true })).toBeVisible();
    expect(requests.every(r => r.method === "GET")).toBe(true);
  });
}

test("actual management opens and cancels original commands and preserves draft and batch scope", async ({ page }) => {
  const manager = await install(page, "data_manager");
  await page.goto("/versions?report_date=2026-09-12&report_type=business_report");
  await page.getByRole("button", { name: "创建修订", exact: true }).click();
  const revision = page.getByRole("dialog", { name: "创建发布修订", exact: true });
  await expect(revision.getByRole("button", { name: "确认创建修订", exact: true })).toBeDisabled();
  await revision.getByLabel("修订原因").fill("虚构演练，取消不写入");
  await expect(revision.getByRole("button", { name: "确认创建修订", exact: true })).toBeEnabled();
  await revision.getByRole("button", { name: "取消", exact: true }).click(); await expect(revision).toHaveCount(0);
  manager.state.activeDraft = true; await page.reload();
  await expect(page.getByRole("button", { name: "创建修订", exact: true })).toBeDisabled();
  await page.goto("/versions?batch_review_run_id=81");
  await expect(page.getByRole("button", { name: "查看版本 v4，活动草稿" })).toBeVisible();
  await expect(page.getByRole("link", { name: "返回批量任务", exact: true })).toHaveAttribute("href", "/review/batch/81");
  await expect(page.getByLabel("报告日期", { exact: true })).toHaveCount(0);
  await page.context().unrouteAll(); const admin = await install(page, "admin");
  await page.goto("/versions?report_date=2026-09-12&report_type=business_report");
  await page.getByRole("button", { name: "回滚到 v1", exact: true }).click();
  const rollback = page.getByRole("dialog", { name: "管理员回滚确认", exact: true });
  await expect(rollback.getByRole("button", { name: "确认回滚到 v1", exact: true })).toBeDisabled();
  await rollback.getByRole("button", { name: "取消", exact: true }).click();
  await page.getByRole("button", { name: "移动到其他日期", exact: true }).click();
  const move = page.getByRole("dialog", { name: "已发布数据跨日期移动", exact: true });
  await expect(move).toBeVisible();
  await move.getByRole("button", { name: "返回版本记录", exact: true }).click();
  await expect(move).toHaveCount(0);
  expect(admin.requests.every(r => r.method === "GET")).toBe(true);
});
