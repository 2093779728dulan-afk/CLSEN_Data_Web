import { expect, test, type Page } from "@playwright/test";
import { reviewDays, reviewEntries } from "../../src/app/AdvancedReviewWorkspaceView.fixtures";
import { draftWorkspace } from "../../src/features/import-review/DraftReviewView.fixtures";
import { intakeInspection } from "../../src/features/import-review/ImportIntakeView.fixtures";

const target = "/review-advanced/2026-08-10?report_type=business_report&version_id=51";
async function install(page: Page) {
  const state = { failCalendar: true }; const unexpected: string[] = []; const writes: string[] = []; const calendarQueries: string[] = []; const draftIds: number[] = [];
  await page.context().addCookies([{ name: "clsen_csrf", value: "fictional-review", url: test.info().project.use.baseURL! }]);
  await page.route(url => url.pathname.startsWith("/api/"), async route => {
    const r = route.request(); const url = new URL(r.url()); const path = url.pathname;
    if (path === "/api/imports/11/inspect" && r.method() === "POST") { writes.push(path); expect(r.headers()["x-csrf-token"]).toBe("fictional-review"); return route.fulfill({ json: { ...intakeInspection, report_date: "2026-08-10" } }); }
    if (!["GET", "HEAD"].includes(r.method())) { unexpected.push(`${r.method()} ${path}`); return route.fulfill({ status: 405 }); }
    if (path === "/api/auth/me") return route.fulfill({ json: { id: 88, username: "fictional-reviewer", display_name: "示例数据管理员", roles: ["data_manager"] } });
    if (path === "/api/data-calendar/site-context") return route.fulfill({ json: { site_id: 1, site_code: "DEMO", display_name: "虚构站点", site_config_version_id: 2, source_timezone: "UTC", reporting_timezone: "UTC", currency_code: "USD" } });
    if (path === "/api/data-calendar") { calendarQueries.push(url.search); return state.failCalendar ? route.fulfill({ status: 503, json: { error: { code: "fictional_failure", message: "示例日历读取失败" } } }) : route.fulfill({ json: reviewEntries }); }
    if (path === "/api/data-calendar/days") return route.fulfill({ json: reviewDays });
    const draft = /^\/api\/drafts\/(51|62)\/review-workspace$/.exec(path);
    if (draft) { const id = Number(draft[1]); draftIds.push(id); const response = structuredClone(draftWorkspace); if (id === 62) { response.head.version_id = 62; response.head.version_no = 3; response.head.dataset_id = 61; response.report_type = "return_report"; response.ruleset_version = "return_report_v1"; } return route.fulfill({ json: response }); }
    if (path === "/api/versions" || path === "/api/imports/11/notes") return route.fulfill({ json: [] });
    if (path === "/api/imports/11/raw-file") return route.fulfill({ headers: { "Content-Type": "text/csv; charset=utf-8", "Content-Length": "21" }, body: r.method() === "HEAD" ? "" : "sku,sales\nA-01,40.00\n" });
    unexpected.push(`${r.method()} ${path}`); return route.fulfill({ status: 500, json: {} });
  });
  return { state, unexpected, writes, calendarQueries, draftIds };
}

for (const width of [1280, 390]) test(`actual advanced date retry, draft URL, refresh and source at ${width}px`, async ({ page }) => {
  await page.setViewportSize({ width, height: 900 }); const fixture = await install(page); const errors: string[] = []; page.on("pageerror", e => errors.push(e.message));
  await page.goto(target); await expect(page.getByRole("alert")).toContainText("示例日历读取失败"); await expect(page.getByText("尚未导入", { exact: true })).toHaveCount(0);
  fixture.state.failCalendar = false; await page.getByRole("button", { name: "重新读取日期状态", exact: true }).click();
  await expect(page.getByRole("region", { name: "可横向滚动的草稿数据表", exact: true }).getByRole("table")).toBeVisible(); expect(fixture.draftIds).toContain(51);
  const returns = page.getByRole("group", { name: "选择待审核报表", exact: true }).getByRole("button", { name: "退货报告 · 草稿 v3", exact: true }); await returns.click();
  await expect(page).toHaveURL(/report_type=return_report&version_id=62/); await expect(returns).toHaveAttribute("aria-pressed", "true"); await expect.poll(() => fixture.draftIds.includes(62)).toBe(true);
  await page.reload(); await expect(page.getByRole("group", { name: "选择待审核报表", exact: true }).getByRole("button", { name: "退货报告 · 草稿 v3", exact: true })).toHaveAttribute("aria-pressed", "true");
  const day11 = page.getByRole("button", { name: "选择 8 月 11 日，部分发布：仅一类报表已发布", exact: true }); await day11.focus(); await day11.press("Enter");
  await expect(page).toHaveURL(/review-advanced\/2026-08-11/); await expect(day11).toHaveAttribute("aria-current", "date"); await expect(page.getByRole("heading", { name: "批量文件逐份识别，再进入各自工作日", exact: true })).toBeVisible();
  await expect(page.getByRole("link", { name: "返回日期表格", exact: true })).toHaveAttribute("href", /\/review\/2026-08-11\?report_type=business_report/);
  expect(fixture.calendarQueries.every(q => q.includes("from=2026-08-01&to=2026-08-31"))).toBe(true);
  await page.goto("/review-advanced/2026-08-10?batch_id=11"); await expect(page.getByRole("heading", { name: "从指定文件重新审核", exact: true })).toBeVisible();
  await expect(page.getByText("当前处理文件批次 #11。", { exact: false })).toBeVisible(); expect(fixture.writes.every(path => path === "/api/imports/11/inspect")).toBe(true); expect(fixture.writes.length).toBeGreaterThan(0);
  expect(fixture.unexpected).toEqual([]); expect(errors).toEqual([]); expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
});
