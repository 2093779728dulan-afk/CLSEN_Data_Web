import { expect, test, type Page } from "@playwright/test";

async function fixture(page: Page, baseURL: string, mode: "normal" | "save-failure" | "refresh-failure" | "readonly" | "issues" | "global-style" = "normal") {
  await page.context().addCookies([{ name: "clsen_csrf", url: baseURL, value: "synthetic-review-csrf" }]);
  let revision = 1;
  let failSave = mode === "save-failure";
  let failRead = false;
  const commands: Array<{ expected_workflow_revision: number; mutations: Array<{ mutation_id: string; row_key: string; payload: Record<string, string> }> }> = [];
  const rows = [
    { row_key: "demo-style-1", row_origin: "system", projection_state: "included", section: "styles", payload: { style_code: "DEMO-01", standard_name: "", status: "active", change_reason: null } },
    { row_key: "demo-style-2", row_origin: "system", projection_state: "included", section: "styles", payload: { style_code: "DEMO-02", standard_name: "", status: "active", change_reason: null } },
  ];
  await page.route(/^https?:\/\/[^/]+\/api\//, async route => {
    const path = new URL(route.request().url()).pathname;
    if (path === "/api/auth/me") return route.fulfill({ json: { id: 77, username: "synthetic-manager", display_name: "示例审核员", roles: [mode === "readonly" ? "viewer" : "data_manager"] } });
    if (path === "/api/data-calendar/site-context") return route.fulfill({ json: { site_id: 1, site_code: "US", display_name: "示例站点", site_config_version_id: 2, source_timezone: "America/Los_Angeles", reporting_timezone: "America/Los_Angeles", currency_code: "USD" } });
    if (path === "/api/dashboard/style-readiness") return route.fulfill({ json: { published_reports: 0, prerequisites_present: false } });
    if (path === "/api/catalog/imports/42/decisions") {
      const body = route.request().postDataJSON() as typeof commands[number];
      commands.push(body);
      await new Promise(resolve => setTimeout(resolve, 150));
      if (failSave) { failSave = false; return route.fulfill({ status: 409, json: { error: { code: "REVISION_CONFLICT", message: "示例版本冲突，请核对后保存。", workflow_revision: revision } } }); }
      if (body.expected_workflow_revision !== revision) return route.fulfill({ status: 409, json: { error: { code: "REVISION_CONFLICT", message: "修订号不匹配。" } } });
      for (const mutation of body.mutations) {
        const row = rows.find(value => value.row_key === mutation.row_key);
        if (row) row.payload = { ...row.payload, ...mutation.payload };
      }
      ++revision; failRead = mode === "refresh-failure";
      return route.fulfill({ json: { safe_result: { workflow_revision: revision } } });
    }
    if (path === "/api/catalog/imports/42") {
      if (failRead) { failRead = false; return route.fulfill({ status: 503, json: { error: { code: "UNAVAILABLE", message: "示例明细暂不可用。" } } }); }
      return route.fulfill({ json: { issues: mode === "issues" && revision === 1 ? [{ section: "styles", row_key: "demo-style-2", field: "/standard_name", severity: "error", reason_code: "required" }] : [], import_id: 42, base_catalog_version_id: null, catalog_publication_revision: 0, export_id: 1, failure_reason_code: null, has_original_file: false, parse_attempt_revision: 1, source_kind: "online", status: "needs_attention", submitted_by_user_id: null, validation_run_id: null, workflow_revision: revision,
        permissions: { can_view: true, can_edit: mode !== "readonly", can_validate: mode !== "readonly", can_submit: false, can_preview: false, can_approve_normal: false, can_approve_high_risk: false, can_reject: false, can_withdraw: false, can_resume: false, can_rebase: mode === "global-style", can_download_original: false } } });
    }
    if (path.includes("/rows/")) return route.fulfill({ json: { rows: path.endsWith("/styles") ? rows : [], total_rows: path.endsWith("/styles") ? rows.length : 0, workflow_revision: revision } });
    return route.fulfill({ json: {} });
  });
  await page.goto("/catalog/imports/42");
  if (mode === "readonly") await expect(page).toHaveURL(/\/catalog$/);
  else await expect(page.getByRole("heading", { name: "商品主档审核", exact: true })).toBeVisible();
  return commands;
}

test("routed review preserves filtered and cross-tab drafts and saves one revision-bound batch", async ({ page, baseURL }) => {
  const commands = await fixture(page, baseURL!);
  await page.getByLabel("demo-style-1 standard_name", { exact: true }).fill("示例衬衫");
  await page.getByLabel("demo-style-2 standard_name", { exact: true }).fill("示例外套");
  await expect(page.getByRole("button", { name: "重新校验", exact: true })).toBeDisabled();
  await page.getByRole("searchbox", { name: "搜索当前审核项" }).fill("DEMO-01");
  await page.getByRole("tab", { name: /^SKU 标准化/ }).click();
  await page.getByRole("tab", { name: /^款式命名/ }).click();
  await expect(page.getByLabel("demo-style-1 standard_name", { exact: true })).toHaveValue("示例衬衫");
  await page.getByText("核对本次修改 · 2 行（含筛选隐藏的修改）").click();
  await expect(page.locator("details[open] ins").filter({ hasText: "示例外套" })).toBeVisible();
  await page.getByRole("button", { name: "保存当前分类修改（2行）", exact: true }).click();
  await expect(page.getByText("已保存 2 行草稿。目录尚未批准生效。", { exact: true })).toBeVisible();
  expect(commands).toHaveLength(1);
  const command = commands[0];
  if (!command) throw new Error("Expected a saved batch command.");
  expect(command.expected_workflow_revision).toBe(1);
  expect(command.mutations.map(row => row.row_key)).toEqual(["demo-style-1", "demo-style-2"]);
  expect(new Set(command.mutations.map(row => row.mutation_id)).size).toBe(2);
  await expect(page.getByRole("searchbox", { name: "搜索当前审核项" })).toHaveValue("DEMO-01");
  await page.getByRole("checkbox", { name: "仅看待处理" }).uncheck();
  await expect(page.getByLabel("demo-style-1 standard_name", { exact: true })).toHaveValue("示例衬衫");
  await expect(page.getByRole("button", { name: "重新校验", exact: true })).toBeEnabled();
  await page.reload();
  await page.getByRole("checkbox", { name: "仅看待处理" }).uncheck();
  await expect(page.getByLabel("demo-style-2 standard_name", { exact: true })).toHaveValue("示例外套");
});

test("failed batch preserves edits and only retries after an explicit user action", async ({ page, baseURL }) => {
  const commands = await fixture(page, baseURL!, "save-failure");
  await page.getByLabel("demo-style-1 standard_name", { exact: true }).fill("失败后保留的示例名称");
  await page.getByRole("searchbox", { name: "搜索当前审核项" }).fill("没有匹配项");
  await page.getByRole("button", { name: "保存当前分类修改（1行）", exact: true }).click();
  await expect(page.getByText(/编辑内容已保留/)).toBeVisible();
  await expect(page.getByRole("status").filter({ hasText: "已保存，已移到" })).toHaveCount(0);
  await page.getByRole("button", { name: "返回修改行" }).click();
  await expect(page.getByLabel("demo-style-1 style_code", { exact: true })).toBeFocused();
  await expect(page.getByLabel("demo-style-1 standard_name", { exact: true })).toHaveValue("失败后保留的示例名称");
  expect(commands).toHaveLength(1);
  await page.getByRole("button", { name: "保存当前分类修改（1行）", exact: true }).click();
  await expect(page.getByText("已保存 1 行草稿。目录尚未批准生效。", { exact: true })).toBeVisible();
  expect(commands).toHaveLength(2);
});

test("single-row save keeps another row's unsaved edit through projection refresh", async ({ page, baseURL }) => {
  const commands = await fixture(page, baseURL!);
  await page.getByLabel("demo-style-1 standard_name", { exact: true }).fill("已保存示例");
  await page.getByLabel("demo-style-2 standard_name", { exact: true }).fill("尚未保存示例");
  await page.getByRole("button", { name: "保存此行", exact: true }).first().click();
  await expect(page.getByLabel("demo-style-2 standard_name", { exact: true })).toHaveValue("尚未保存示例");
  await expect(page.getByRole("button", { name: "保存当前分类修改（1行）", exact: true })).toBeEnabled();
  await page.getByRole("button", { name: "保存当前分类修改（1行）", exact: true }).click();
  await expect(page.getByText("已保存 1 行草稿。目录尚未批准生效。", { exact: true })).toBeVisible();
  expect(commands.map(command => command.expected_workflow_revision)).toEqual([1, 2]);
});

test("acknowledged save with failed read blocks writes until a read-only recovery", async ({ page, baseURL }) => {
  const commands = await fixture(page, baseURL!, "refresh-failure");
  await page.getByLabel("demo-style-1 standard_name", { exact: true }).fill("已经写入的示例");
  await page.getByRole("button", { name: "保存当前分类修改（1行）", exact: true }).click();
  await expect(page.getByText(/草稿已保存，但最新明细读取失败/)).toBeVisible();
  await expect(page.getByRole("button", { name: "保存此行", exact: true }).first()).toBeDisabled();
  await page.getByRole("button", { name: "重新读取草稿", exact: true }).click();
  await expect(page.getByText("当前修订 2", { exact: true }).first()).toBeVisible();
  expect(commands).toHaveLength(1);
});

test("readonly account has no draft mutation controls", async ({ page, baseURL }) => {
  const commands = await fixture(page, baseURL!, "readonly");
  await expect(page).toHaveURL(/\/catalog$/);
  await expect(page.getByRole("button", { name: "保存此行", exact: true })).toHaveCount(0);
  await expect(page.getByRole("button", { name: /保存当前分类修改/ })).toHaveCount(0);
  expect(commands).toHaveLength(0);
});

for (const width of [1280, 390]) {
  test(`continuous editing, undo and keyboard save at ${width}px`, async ({ page, baseURL }, testInfo) => {
    await page.setViewportSize({ width, height: 900 });
    const commands = await fixture(page, baseURL!);
    const first = page.getByLabel("demo-style-1 standard_name", { exact: true });
    const second = page.getByLabel("demo-style-2 standard_name", { exact: true });
    await first.fill("先撤销这个字段");
    await first.press("Escape");
    await expect(first).toHaveValue("");
    await expect(first).toBeFocused();
    await first.fill("最终保留的名称");
    await first.press("Alt+ArrowDown");
    await expect(second).toBeFocused();
    await second.fill("撤销此行");
    await page.locator('[data-review-row="demo-style-2"]').getByRole("button", { name: "撤销本行修改" }).click();
    await expect(second).toHaveValue("");
    await expect(first).toHaveValue("最终保留的名称");
    expect(commands).toHaveLength(0);
    await first.focus();
    await first.press("Control+Enter");
    await expect(page.getByText("已保存 1 行草稿。目录尚未批准生效。", { exact: true })).toBeVisible();
    await expect(second).toBeFocused();
    expect(commands).toHaveLength(1);
    await second.fill("连续完成的名称");
    await second.press("Control+Enter");
    await expect(page.getByText("当前分类已没有待处理项，或搜索条件没有匹配。")).toBeVisible();
    await expect(page.getByRole("region", { name: "当前分类编辑区", exact: true }).filter({ visible: true })).toBeFocused();
    expect(commands).toHaveLength(2);
    await page.getByRole("checkbox", { name: "仅看待处理" }).uncheck();
    await expect(first).toHaveValue("最终保留的名称");
    await expect(second).toHaveValue("连续完成的名称");
    await page.screenshot({ path: testInfo.outputPath(`continuous-${width}.png`), fullPage: true });
    await page.reload();
    await page.getByRole("checkbox", { name: "仅看待处理" }).uncheck();
    await expect(second).toHaveValue("连续完成的名称");
  });
}

test("keyboard save restores field, selection and scroll; a category change wins", async ({ page, baseURL }) => {
  const commands = await fixture(page, baseURL!);
  await page.getByRole("checkbox", { name: "仅看待处理" }).uncheck();
  const field = page.getByLabel("demo-style-2 standard_name", { exact: true });
  await field.fill("保持位置的示例");
  await field.evaluate((element: HTMLTextAreaElement) => element.setSelectionRange(2, 4));
  const before = await page.evaluate(() => ({ y: scrollY, x: scrollX }));
  const region = page.getByRole("region", { name: "当前分类审核表格", exact: true });
  await region.evaluate(element => { element.scrollLeft = 60; });
  const left = await region.evaluate(element => element.scrollLeft);
  await field.press("Control+Enter");
  await expect(page.getByText("已保存 1 行草稿。目录尚未批准生效。", { exact: true })).toBeVisible();
  await expect(field).toBeFocused();
  expect(await field.evaluate((element: HTMLTextAreaElement) => [element.selectionStart, element.selectionEnd])).toEqual([2, 4]);
  expect(await region.evaluate(element => element.scrollLeft)).toBe(left);
  expect(await page.evaluate(() => ({ y: scrollY, x: scrollX }))).toEqual(before);
  await field.fill("切换分类时不抢焦点");
  await field.press("Control+Enter");
  const tab = page.getByRole("tab", { name: /^SKU 标准化/ });
  await tab.click();
  await expect(tab).toBeFocused();
  await expect(page.getByRole("button", { name: "重新读取草稿", exact: true })).toBeEnabled();
  expect(commands).toHaveLength(2);
  await expect(tab).toBeFocused();
});

test("server issue locates its exact field and the refreshed revision clears old issues", async ({ page, baseURL }, testInfo) => {
  const commands = await fixture(page, baseURL!, "issues");
  await page.getByRole("button", { name: "定位问题 1" }).click();
  const field = page.getByLabel("demo-style-2 standard_name", { exact: true });
  await expect(field).toBeFocused();
  await expect(field).toHaveAttribute("aria-invalid", "true");
  await expect(page.getByRole("searchbox", { name: "搜索当前审核项" })).toHaveValue("demo-style-2");
  await field.fill("已处理问题的名称");
  await page.screenshot({ path: testInfo.outputPath("located-issue.png"), fullPage: true });
  await field.press("Control+Enter");
  await expect(page.getByText("已保存 1 行草稿。目录尚未批准生效。", { exact: true })).toBeVisible();
  await expect(field).toHaveAttribute("aria-invalid", "false");
  await expect(page.getByRole("button", { name: "定位问题 1" })).toHaveCount(0);
  expect(commands).toHaveLength(1);
});


test("global defaults preserve component focus and native disclosure focus in the routed app", async ({ page, baseURL }, testInfo) => {
  const commands = await fixture(page, baseURL!, "global-style");
  const search = page.getByRole("searchbox", { name: "搜索当前审核项" });
  await search.focus();
  expect(await search.evaluate(element => getComputedStyle(element).outlineStyle)).toBe("none");
  expect(await search.locator("..").evaluate(element => getComputedStyle(element).boxShadow)).not.toBe("none");
  await search.fill("DEMO");
  await page.getByRole("button", { name: "清空搜索", exact: true }).click();
  await expect(search).toBeFocused();
  const button = page.getByRole("button", { name: "重新读取草稿", exact: true });
  await page.keyboard.press("Tab");
  await button.focus();
  expect(await button.evaluate(element => element.matches(":focus-visible"))).toBe(true);
  expect(await button.evaluate(element => getComputedStyle(element).outlineOffset)).toBe("2px");
  const disclosure = page.getByText("高级操作 · 调整目录基准", { exact: true });
  await disclosure.focus();
  expect(await disclosure.evaluate(element => getComputedStyle(element).outlineWidth)).toBe("2px");
  await disclosure.press("Enter");
  await expect(page.getByRole("textbox", { name: "替代导出编号（export ID）" })).toBeVisible();
  await page.screenshot({ path: testInfo.outputPath("routed-global-style.png") });
  expect(commands).toHaveLength(0);
});
