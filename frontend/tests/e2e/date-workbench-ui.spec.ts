import { expect, test, type Page } from "@playwright/test";
import { sampleWorkbench } from "../../src/features/workbench/DateWorkbenchView.fixtures";
import type { SetWorkbenchCellRequest } from "../../src/api/generated";

async function install(page: Page, manager = true, empty = false) {
  const state = { data: sampleWorkbench(empty ? "empty" : "published", manager), readFailure: false, cellFailure: false, holdCell: false, releaseCell: () => {} };
  const requests: { url: URL; method: string; body: unknown; key?: string }[] = [];
  await page.context().addCookies([{ name: "clsen_csrf", value: "synthetic-csrf", url: test.info().project.use.baseURL! }]);
  await page.context().route(url => url.pathname.startsWith("/api/"), async route => {
    const req = route.request(); const url = new URL(req.url()); const method = req.method();
    const body: unknown = method !== "GET" && req.headers()["content-type"]?.includes("json") ? req.postDataJSON() : req.postData();
    requests.push({ url, method, body, key: req.headers()["idempotency-key"] });
    if (method !== "GET") { expect(manager).toBe(true); expect(req.headers()["x-csrf-token"]).toBe("synthetic-csrf"); expect(req.headers()["idempotency-key"]).toMatch(/^[0-9a-f-]{36}$/); }
    if (url.pathname === "/api/auth/me") return route.fulfill({ json: { id: 88, username: "synthetic-workbench", display_name: "虚构工作台账号", roles: [manager ? "data_manager" : "viewer"] } });
    if (url.pathname === "/api/data-calendar/site-context") return route.fulfill({ json: { site_id: 1, site_code: "US", display_name: "虚构站点", site_config_version_id: 2, source_timezone: "UTC", reporting_timezone: "UTC", currency_code: "USD" } });
    if (url.pathname === "/api/dashboard/daily-ledger") return route.fulfill({ json: { publications: [], site_config_versions: [], rows: [], range: { from_date: "2026-09-12", to_date: "2026-09-12" } } });
    if (url.pathname === "/api/workbench/dates/2026-09-12" && method === "GET") {
      if (state.readFailure) return route.fulfill({ status: 503, json: { error: { code: "UNAVAILABLE", message: "虚构网络读取失败" } } });
      const data = structuredClone(state.data); data.report_type = url.searchParams.get("report_type") === "return_report" ? "return_report" : "business_report";
      data.pagination = { page: Number(url.searchParams.get("page") ?? "1"), page_size: 50, total_rows: 51, total_pages: 2 };
      if (data.pagination.page === 2) data.rows = [{ ...data.rows[0]!, row_ordinal: 51 }];
      const search = url.searchParams.get("search"); if (search) data.rows = data.rows.filter(row => row.cells.some(cell => String(cell.current).includes(search)));
      if (url.searchParams.get("changed_only") === "true") data.rows = data.rows.filter(row => row.cells.some(cell => cell.changed));
      return route.fulfill({ json: data });
    }
    if (url.pathname.endsWith("/revision")) { expect(body).toMatchObject({ published_version_id: 92 }); state.data = sampleWorkbench("draft", manager); return route.fulfill({ json: { dataset_id: 91, version_id: 92 } }); }
    if (url.pathname.includes("/cells/") && method === "PATCH") {
      if (state.holdCell) { state.holdCell = false; await new Promise<void>(resolve => { state.releaseCell = resolve; }); }
      if (state.cellFailure) return route.fulfill({ status: 409, json: { error: { code: "cell_revision_conflict", message: "示例：单元格已变化，你的输入已保留。" } } });
      const command = body as SetWorkbenchCellRequest;
      expect(command.head.dataset_id).toBe(91); expect(command.expected_cell_revision).toBeGreaterThanOrEqual(0);
      const columnId = url.pathname.split("/").at(-1)!; const rowId = Number(url.pathname.split("/")[6]);
      const cell = state.data.rows.find(row => row.row_id === rowId)!.cells.find(cell => cell.column_id === columnId)!;
      cell.current = command.value.value; cell.changed = cell.current !== cell.base; cell.cell_revision += 1;
      state.data.head!.data_revision += 1;
      return route.fulfill({ json: { cell: { ...cell, row_id: rowId }, head: state.data.head, change_id: 1, operation_token: req.headers()["idempotency-key"] } });
    }
    if (url.pathname.endsWith("/undo")) { state.data = sampleWorkbench("draft", manager); return route.fulfill({ json: {} }); }
    if (url.pathname === "/api/workbench/imports") return route.fulfill({ json: { batch_id: 44, dataset_id: null, duplicate: false, encoding: "utf-8-sig", issue_codes: ["selected_type_conflict"], message: null, report_date: "2026-09-12", report_type: "return_report", stage: "uploaded", status: "confirmation_required", version_id: null, workspace_url: null } });
    if (url.pathname.endsWith("/44/confirm")) { expect(body).toMatchObject({ report_date: "2026-09-12", report_type: "return_report", encoding: "utf-8-sig" }); state.data = sampleWorkbench("draft", manager, "return_report"); return route.fulfill({ json: { batch_id: 44, dataset_id: 91, duplicate: false, encoding: "utf-8-sig", issue_codes: [], message: null, report_date: "2026-09-12", report_type: "return_report", stage: "draft", status: "workspace_ready", version_id: 92, workspace_url: "/review/2026-09-12?report_type=return_report" } }); }
    throw new Error(`Unexpected synthetic request: ${method} ${url.pathname}`);
  });
  return { state, requests };
}
for (const width of [1280, 390]) {
  test(`actual manager date workbench saves, recovers, refreshes, filters and undoes at ${width}px`, async ({ page }) => {
    await page.setViewportSize({ width, height: 900 }); const { state, requests } = await install(page); state.readFailure = true;
    await page.goto("/published/2026-09-12?report_type=business_report");
    await expect(page.getByRole("alert")).toContainText("虚构网络读取失败"); state.readFailure = false;
    await page.getByRole("button", { name: "重新读取", exact: true }).click();
    await page.getByRole("button", { name: "开始修改", exact: true }).click();
    const cell = page.getByRole("textbox", { name: "Title，第 1 行", exact: true });
    await cell.click();
    await cell.fill("取消输入"); await cell.press("Escape"); await expect(cell).toHaveValue("示例蓝色衬衫 · 中码");
    expect(requests.filter(req => req.method === "PATCH")).toHaveLength(0);
    state.cellFailure = true; await cell.fill("浏览器修改示例"); await cell.press("Enter");
    await expect(page.getByRole("alert")).toContainText("输入已保留"); await expect(cell).toHaveValue("浏览器修改示例");
    await expect(page.getByRole("button", { name: "前往发布", exact: true })).toBeDisabled();
    state.cellFailure = false; await cell.focus(); await cell.press("Enter");
    await expect(page.getByText("已保存", { exact: true })).toBeVisible();
    const writes = requests.filter(req => req.method === "PATCH"); expect(writes).toHaveLength(2);
    await page.reload(); await expect(cell).toHaveValue("浏览器修改示例");
    await page.getByRole("checkbox", { name: "只看修改", exact: true }).click(); await expect(page).toHaveURL(/changed_only=true/);
    await expect(page.locator("tbody tr")).toHaveCount(1);
    await page.getByRole("checkbox", { name: "只看修改", exact: true }).click(); await expect(page).not.toHaveURL(/changed_only/);
    await expect(page.locator("tbody tr")).toHaveCount(state.data.rows.length);
    const search = page.getByRole("textbox", { name: "搜索表格", exact: true }); await search.fill("浏览器"); await search.press("Enter");
    await expect(page).toHaveURL(/search=/); await page.reload(); await expect(search).toHaveValue("浏览器");
    await search.fill(""); await search.press("Enter"); await expect(page).not.toHaveURL(/search=/);
    await page.getByRole("button", { name: "按 Sales 排序", exact: true }).click(); await expect(page).toHaveURL(/sort_column_id=7e2d27a9/);
    await page.getByRole("button", { name: "列设置", exact: true }).click(); await page.getByRole("checkbox", { name: "Sales", exact: true }).uncheck();
    await page.getByRole("button", { name: "关闭列设置", exact: true }).click(); await expect(page.getByRole("button", { name: "列设置", exact: true })).toBeFocused();
    await page.reload(); await expect(page.getByRole("button", { name: "按 Sales 排序", exact: true })).toHaveCount(0);
    await page.getByRole("button", { name: "下一页", exact: true }).click(); await expect(page).toHaveURL(/page=2/); await expect(page.getByRole("rowheader", { name: /^51/ })).toBeVisible();
    await page.getByRole("button", { name: "上一页", exact: true }).click(); await expect(page).toHaveURL(/page=1/);
    await page.getByRole("button", { name: "撤销上次修改", exact: true }).click(); await expect(cell).toHaveValue("示例蓝色衬衫 · 中码");
    await page.reload(); await expect(cell).toHaveValue("示例蓝色衬衫 · 中码");
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
    await expect(page.getByRole("link", { name: "查看版本记录", exact: true })).toHaveAttribute("href", "/versions?report_date=2026-09-12&report_type=business_report");
  });
}
test("actual viewer is read-only and empty-day import needs explicit type confirmation", async ({ page }) => {
  const viewer = await install(page, false);
  await page.goto("/published/2026-09-12?report_type=business_report"); await expect(page.getByRole("table", { name: "经营报告原始数据" })).toBeVisible();
  await expect(page.getByRole("button", { name: "开始修改", exact: true })).toHaveCount(0); await expect(page.getByRole("textbox", { name: "Title，第 1 行", exact: true })).toHaveCount(0);
  await expect(page.getByText("当前为只读发布数据，筛选和列设置不会修改报表。", { exact: true })).toBeVisible();
  expect(viewer.requests.every(req => req.method === "GET")).toBe(true);
  await page.context().unrouteAll(); const { requests } = await install(page, true, true);
  await page.reload(); await expect(page.getByText("这个报表日还没有数据", { exact: true })).toBeVisible();
  await page.locator('input[type="file"]').setInputFiles({ name: "fictional.csv", mimeType: "text/csv", buffer: Buffer.from("Title\nExample\n") });
  await expect(page.getByRole("alert")).toContainText("文件类型与当前入口不一致");
  expect(requests.some(req => req.url.pathname.endsWith("/confirm"))).toBe(false);
  await page.getByRole("button", { name: "按退货报告继续", exact: true }).click(); await expect(page).toHaveURL(/report_type=return_report/);
  await expect(page.getByRole("table", { name: "退货报告原始数据" })).toBeVisible(); await page.reload(); await expect(page.getByRole("table", { name: "退货报告原始数据" })).toBeVisible();
  expect(requests.filter(req => req.url.pathname.endsWith("/confirm"))).toHaveLength(1);
});

for (const width of [1280, 390]) {
  test(`actual pending cell retains newer input and binds the next revision at ${width}px`, async ({ page }) => {
    await page.setViewportSize({ width, height: 900 });
    const { state, requests } = await install(page);
    const errors: string[] = []; page.on("pageerror", error => errors.push(error.message));
    await page.goto("/published/2026-09-12?report_type=business_report");
    await page.getByRole("button", { name: "开始修改", exact: true }).click();
    const cell = page.getByRole("textbox", { name: "Title，第 1 行", exact: true });
    await cell.click();
    state.holdCell = true;
    await cell.fill("Draft 1"); await cell.press("Enter");
    await expect(cell).toHaveAttribute("aria-busy", "true"); await expect(cell).toBeEditable();
    await expect(page.getByText("1 个正在保存", { exact: true })).toBeVisible();
    await cell.fill("Draft 2");
    await expect(page.getByText("1 个待保存", { exact: true })).toBeVisible();
    state.releaseCell();
    await expect(cell).toHaveAttribute("title", "Draft 1");
    await expect(cell).toHaveValue("Draft 2");
    await expect(page.getByText("已保存", { exact: true })).toHaveCount(0);
    await cell.press("Enter");
    await expect(page.getByText("已保存", { exact: true })).toBeVisible();
    const writes = requests.filter(r => r.method === "PATCH");
    expect(writes).toHaveLength(2);
    expect(writes[0]!.body).toMatchObject({ expected_cell_revision: 0, value: { type: "text", value: "Draft 1" }, head: { dataset_id: 91, data_revision: 0 } });
    expect(writes[1]!.body).toMatchObject({ expected_cell_revision: 1, value: { type: "text", value: "Draft 2" }, head: { dataset_id: 91, data_revision: 1 } });
    expect(writes[1]!.key).not.toBe(writes[0]!.key);
    await page.reload(); await expect(cell).toHaveValue("Draft 2");
    expect(errors).toEqual([]);
  });
}
