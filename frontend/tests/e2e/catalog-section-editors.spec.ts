import { expect, test } from "@playwright/test";

for (const width of [1280, 390]) {
  test(`all category fields retain candidate values and revision-bound mutations at ${width}px`, async ({ page, baseURL }, info) => {
    await page.setViewportSize({ width, height: 900 });
    await page.context().addCookies([{ name: "clsen_csrf", url: baseURL!, value: "fictional-editor-csrf" }]);
    let revision = 3;
    const commands: Array<{ expected_workflow_revision: number; mutations: Array<{ type: string; row_key: string | null; decision_group_key: string | null; payload: Record<string, string | number | null> }> }> = [];
    const rows = [
      { section: "styles", row_key: "style-1", row_origin: "system", projection_state: "included", payload: { style_code: "DEMO01", standard_name: null, status: "active" } },
      { section: "skus", row_key: "sku-1", row_origin: "system", projection_state: "included", payload: { style_row_key: "style-1", internal_display_sku: null, standard_color: null, standard_size: null, source_color_preview: '["藏青","浅蓝"]', source_size_preview: '["M","L"]', status: "active" } },
      { section: "mappings", row_key: "mapping-1", row_origin: "system", projection_state: "included", payload: { seller_sku_preview: "DEMO01-藏青-M", identity_decision: null, target_sku_row_key: null, business_occurrences: 12, return_occurrences: 1 } },
      { section: "exceptions", row_key: "exception-1", row_origin: "system", projection_state: "included", payload: { seller_sku_preview: "DEMO01-待确认", action: null, reason_code: "unparsed" } },
      { section: "evidence", row_key: "evidence-1", row_origin: "system", projection_state: "audit_only", payload: { seller_sku_preview: "DEMO01-藏青-M", latest_title_preview: "虚构报告名称", report_type: "business_report" } },
    ];
    await page.route(/^https?:\/\/[^/]+\/api\//, async route => {
      const path = new URL(route.request().url()).pathname;
      const method = route.request().method();
      if (path === "/api/catalog/imports/42/decisions" && method === "POST") {
        const command = route.request().postDataJSON() as typeof commands[number];
        expect(command.expected_workflow_revision).toBe(revision); commands.push(command);
        for (const mutation of command.mutations) {
          const row = rows.find(row => row.row_key === (mutation.row_key ?? mutation.decision_group_key));
          if (!row) throw new Error("Unexpected mutation identity");
          row.payload = { ...row.payload, ...mutation.payload };
        }
        revision++;
        return route.fulfill({ json: { safe_result: { workflow_revision: revision } } });
      }
      if (method !== "GET") throw new Error(`Unexpected write ${method} ${path}`);
      if (path === "/api/auth/me") return route.fulfill({ json: { id: 88, username: "fictional-category-manager", display_name: "虚构审核账号", roles: ["data_manager"] } });
      if (path === "/api/data-calendar/site-context") return route.fulfill({ json: { site_id: 1, site_code: "US", display_name: "虚构站点", site_config_version_id: 2, source_timezone: "UTC", reporting_timezone: "UTC", currency_code: "USD" } });
      if (path === "/api/dashboard/style-readiness") return route.fulfill({ json: { published_reports: 0, prerequisites_present: false } });
      if (path === "/api/catalog/imports/42") return route.fulfill({ json: { import_id: 42, workflow_revision: revision, catalog_publication_revision: 7, base_catalog_version_id: 4, export_id: 8001, parse_attempt_revision: 1, source_kind: "online", status: "needs_attention", issues: [], failure_reason_code: null, has_original_file: false, submitted_by_user_id: 88, validation_run_id: null,
        permissions: { can_view: true, can_edit: true, can_preview: false, can_approve_normal: false, can_approve_high_risk: false, can_rebase: false, can_reject: false, can_withdraw: false, can_resume: false, can_validate: false, can_submit: false, can_download_original: false } } });
      if (path.startsWith("/api/catalog/imports/42/rows/")) {
        const values = rows.filter(row => row.section === path.split("/").at(-1));
        return route.fulfill({ json: { rows: values, total_rows: values.length, workflow_revision: revision } });
      }
      throw new Error(`Unexpected API ${path}`);
    });
    await page.goto("/catalog/imports/42");
    const name = "style-1 standard_name";
    await page.getByRole("combobox", { name, exact: true }).selectOption("__manual__");
    await page.getByRole("textbox", { name, exact: true }).fill("手工核对名称");
    await page.getByRole("button", { name: "清空标准商品名称", exact: true }).click();
    await expect(page.getByRole("textbox", { name, exact: true })).toBeFocused();
    await page.getByRole("button", { name: "从报告候选中选择 标准商品名称", exact: true }).click();
    await expect(page.getByRole("combobox", { name, exact: true })).toHaveValue("虚构报告名称");
    await page.getByRole("button", { name: "保存当前分类修改（1行）", exact: true }).click();
    await expect(page.getByText("当前修订 4", { exact: true }).first()).toBeVisible();
    await page.getByRole("tab", { name: /^SKU 标准化/ }).click();
    await page.getByLabel("sku-1 internal_display_sku", { exact: true }).selectOption("DEMO01-藏青-M");
    await page.getByLabel("sku-1 standard_color", { exact: true }).selectOption("藏青");
    await page.getByLabel("sku-1 standard_size", { exact: true }).selectOption("M");
    await page.getByRole("button", { name: "保存当前分类修改（1行）", exact: true }).click();
    await expect(page.getByText("当前修订 5", { exact: true }).first()).toBeVisible();
    await page.getByRole("tab", { name: /^SKU 映射/ }).click();
    await page.getByRole("radiogroup", { name: "DEMO01-藏青-M 映射决定", exact: true }).getByRole("radio", { name: "纳入目录", exact: true }).check();
    await page.getByLabel("mapping-1 target_sku_row_key", { exact: true }).selectOption("sku-1");
    await page.getByRole("button", { name: "保存当前分类修改（1行）", exact: true }).click();
    await expect(page.getByText("当前修订 6", { exact: true }).first()).toBeVisible();
    await page.getByRole("tab", { name: /^解析异常/ }).click();
    await page.getByLabel("exception-1 action", { exact: true }).selectOption("exclude");
    await page.getByLabel("exception-1 exclusion_reason", { exact: true }).fill("虚构排除依据");
    await page.screenshot({ path: info.outputPath(`actual-exceptions-${width}.png`), fullPage: true });
    await page.getByRole("button", { name: "保存当前分类修改（1行）", exact: true }).click();
    await expect(page.getByText("当前修订 7", { exact: true }).first()).toBeVisible();
    expect(commands.map(command => command.expected_workflow_revision)).toEqual([3, 4, 5, 6]);
    expect(commands.flatMap(command => command.mutations.map(value => value.type))).toEqual(["update_style", "update_sku", "map_seller_sku", "resolve_exception_exclude"]);
    expect(commands[2]?.mutations[0]?.payload.target_sku_row_key).toBe("sku-1");
    expect(commands[2]?.mutations[0]?.decision_group_key).toBe("mapping-1");
    await page.reload();
    await page.getByRole("checkbox", { name: "仅看待处理", exact: true }).uncheck();
    await expect(page.getByRole("combobox", { name, exact: true })).toHaveValue("虚构报告名称");
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
  });
}
