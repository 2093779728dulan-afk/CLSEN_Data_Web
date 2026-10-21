import { expect, test, type Page } from "@playwright/test";
import { issueReviewWorkspace } from "../../src/features/import-review/IssueReviewPanel.fixtures";
const target = "/review-advanced/2026-08-10?report_type=business_report&version_id=51";
async function install(page: Page) {
  const workspace = issueReviewWorkspace(); const state = { fail: true };
  const unexpected: string[] = []; const writes: { path: string; body: Record<string, unknown>; key: string }[] = [];
  await page.context().addCookies([{ name: "clsen_csrf", value: "synthetic-issue", url: test.info().project.use.baseURL! }]);
  await page.context().route(url => url.pathname.startsWith("/api/"), async route => {
    const request = route.request(); const path = new URL(request.url()).pathname;
    const json = (value: unknown) => route.fulfill({ contentType: "application/json", body: JSON.stringify(value) });
    if (request.method() === "GET") {
      if (path === "/api/auth/me") return json({ id: 88, username: "fictional-reviewer", display_name: "虚构审核员", roles: ["data_manager"] });
      if (path === "/api/data-calendar/site-context") return json({ site_id: 1, site_code: "US", display_name: "虚构站点", site_config_version_id: 2, source_timezone: "UTC", reporting_timezone: "UTC", currency_code: "USD" });
      if (path === "/api/data-calendar") return json([{ report_date: "2026-08-10", report_type: "business_report", dataset_id: 41, version_id: 51, version_no: 2, status: workspace.head.status }]);
      if (["/api/data-calendar/days", "/api/versions", "/api/imports/11/notes"].includes(path)) return json([]);
      if (path === "/api/drafts/51/review-workspace") return json(workspace);
    }
    if (request.method() === "POST" && /^\/api\/drafts\/51\/issues\/70[12]\/review$/.test(path)) {
      expect(request.headers()["x-csrf-token"]).toBe("synthetic-issue");
      const key = request.headers()["idempotency-key"]; expect(key).toMatch(/^[0-9a-f-]{36}$/);
      if (!key) throw new Error("Missing command key");
      const body = request.postDataJSON() as Record<string, unknown>; writes.push({ path, body, key });
      const issue = workspace.latest_full_validation!.issues.find(item => path.includes(`/issues/${item.id}/`))!;
      const action = body.action; expect(["acknowledge", "resolve", "reopen"]).toContain(action);
      if (action !== "acknowledge" && action !== "resolve" && action !== "reopen") throw new Error("Unexpected review action");
      expect(body).toEqual({ dataset_id: 41, status: "draft", data_revision: 3, review_revision: workspace.head.review_revision, pointed_at: workspace.head.pointed_at,
        validation_run_id: 901, issue_severity: issue.severity, issue_requires_note: true, action,
        comment: action === "acknowledge" ? "虚构差异核对" : action === "resolve" ? "虚构合计核对" : "虚构重新核对",
      });
      if (state.fail) return route.fulfill({ status: 503, contentType: "application/json", body: JSON.stringify({ error: { code: "outcome_unknown", message: "虚构响应未确认" } }) });
      issue.review = { state: action === "acknowledge" ? "acknowledged" : action === "resolve" ? "resolved" : "open", actor_user_id: 88, actor_username: "fictional-reviewer", comment: String(body.comment), event_id: 801 + writes.length, event_type: action, occurred_at: "2026-08-10T04:00:00Z" };
      workspace.head.review_revision += 1; return json({ result: {} });
    }
    unexpected.push(`${request.method()} ${path}`); return route.fulfill({ status: 500, body: "Unexpected fictional API" });
  });
  return { state, writes, unexpected };
}
for (const width of [1280, 390]) {
  test(`actual issue review failure/retry, warning, resolution, reopen and reload at ${width}px`, async ({ page }) => {
    await page.setViewportSize({ width, height: 900 }); const { state, writes, unexpected } = await install(page);
    const errors: string[] = []; page.on("pageerror", error => errors.push(error.message));
    await page.goto(target);
    const panel = page.getByRole("region", { name: "校验问题", exact: true });
    const warning = panel.getByRole("article", { name: /警告.*销售额与源文件不同/ });
    const blocking = panel.getByRole("article", { name: /阻断项.*报表合计与明细不一致/ });
    await expect(warning.getByRole("button", { name: "确认警告", exact: true })).toBeDisabled();
    await warning.getByRole("textbox", { name: "审核说明", exact: true }).fill("  虚构差异核对  ");
    await warning.getByRole("button", { name: "确认警告", exact: true }).click();
    await expect(warning.getByRole("alert")).toContainText("虚构响应未确认");
    await expect(warning.getByRole("textbox")).toHaveValue("  虚构差异核对  "); expect(writes).toHaveLength(1);
    state.fail = false; await warning.getByRole("button", { name: "确认警告", exact: true }).click();
    await expect(warning.getByText("已确认", { exact: true })).toBeVisible(); expect(writes[0]).toEqual(writes[1]);
    await page.reload(); await expect(warning.getByText("虚构差异核对", { exact: true })).toBeVisible();
    await blocking.getByRole("textbox", { name: "审核说明", exact: true }).fill("虚构合计核对");
    await blocking.getByRole("button", { name: "标记已解决", exact: true }).click();
    await expect(blocking.getByText("已解决", { exact: true })).toBeVisible(); await page.reload();
    await expect(blocking.getByText("虚构合计核对", { exact: true })).toBeVisible();
    await blocking.getByRole("textbox", { name: "审核说明", exact: true }).fill("虚构重新核对");
    await blocking.getByRole("button", { name: "重新打开", exact: true }).focus(); await page.keyboard.press("Enter");
    await expect(blocking.getByText("待处理", { exact: true })).toBeVisible(); await page.reload();
    await expect(blocking.getByText("虚构重新核对", { exact: true })).toBeVisible();
    await expect(blocking.getByRole("button", { name: "标记已解决", exact: true })).toBeDisabled();
    expect(writes).toHaveLength(4); expect(errors).toEqual([]); expect(unexpected).toEqual([]);
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
  });
}
