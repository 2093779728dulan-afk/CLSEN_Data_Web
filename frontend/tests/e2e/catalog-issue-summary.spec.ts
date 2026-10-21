import { expect, test } from "@playwright/test";

for (const width of [1280, 390]) {
  test(`actual issue locate, cross-section correction, save, revalidate and reload at ${width}px`, async ({ page, context, baseURL }, testInfo) => {
    await page.setViewportSize({ width, height: 900 });
    await context.addCookies([{ name: "clsen_csrf", url: baseURL!, value: "fictional-issue-csrf" }]);
    let revision = 3; let validated = false; const calls: string[] = [];
    const style = { row_key: "fictional-style:1", row_origin: "system", projection_state: "included", section: "styles", payload: { style_code: "DEMO-01", standard_name: "", status: "active", change_reason: null } };
    const sku = { row_key: "fictional-sku:2", row_origin: "system", projection_state: "included", section: "skus", payload: { style_row_key: "fictional-style:1", internal_display_sku: "DEMO-01-Blue", standard_color: "Blue", standard_size: "", status: "active", change_reason: null } };
    const issues = [{ section: "styles", row_key: style.row_key, field: "/standard_name", severity: "error", reason_code: "required" }, { section: "skus", row_key: sku.row_key, field: "/standard_size", severity: "error", reason_code: "required" }];
    await page.route(url => url.pathname.startsWith("/api/"), async route => {
      const req = route.request(); const path = new URL(req.url()).pathname;
      if (path === "/api/auth/me") return route.fulfill({ json: { id: 88, username: "fictional-issue-manager", display_name: "虚构审核账号", roles: ["data_manager"] } });
      if (path === "/api/data-calendar/site-context") return route.fulfill({ json: { site_id: 1, site_code: "US", display_name: "虚构站点", site_config_version_id: 2, source_timezone: "UTC", reporting_timezone: "UTC", currency_code: "USD" } });
      if (path === "/api/dashboard/style-readiness") return route.fulfill({ json: { published_reports: 0, prerequisites_present: false } });
      if (path === "/api/catalog/imports/42") return route.fulfill({ json: { import_id: 42, workflow_revision: revision, issues: validated ? [] : issues, catalog_publication_revision: 7, base_catalog_version_id: 4, export_id: 8001, parse_attempt_revision: 1, source_kind: "online", status: validated ? "validated" : "needs_attention", failure_reason_code: null, has_original_file: false, submitted_by_user_id: 88, validation_run_id: validated ? 1 : null, permissions: { can_view: true, can_edit: true, can_preview: false, can_approve_normal: false, can_approve_high_risk: false, can_rebase: false, can_reject: false, can_withdraw: false, can_resume: false, can_validate: true, can_submit: false, can_download_original: false } } });
      if (path.includes("/rows/")) {
        expect(new URL(req.url()).searchParams.get("workflow_revision")).toBe(String(revision));
        const rows = path.endsWith("/styles") ? [style] : path.endsWith("/skus") ? [sku] : [];
        return route.fulfill({ json: { rows, total_rows: rows.length, workflow_revision: revision } });
      }
      if (req.method() === "POST") {
        expect(req.headers()["x-csrf-token"]).toBe("fictional-issue-csrf"); expect(req.headers()["idempotency-key"]).toMatch(/^[0-9a-f-]{36}$/);
        const body = req.postDataJSON() as { expected_workflow_revision: number; mutations?: { row_key: string; type: string; payload: Record<string, string | null> }[] };
        expect(body.expected_workflow_revision).toBe(revision);
        if (path.endsWith("/decisions")) {
          const mutation = body.mutations![0]!;
          if (mutation.row_key === sku.row_key) { expect(mutation.type).toBe("update_sku"); expect(mutation.payload.standard_size).toBe("XL"); sku.payload.standard_size = "XL"; calls.push("sku"); }
          else { expect(mutation.row_key).toBe(style.row_key); expect(mutation.type).toBe("update_style"); expect(mutation.payload.standard_name).toBe("虚构标准商品名称"); style.payload.standard_name = "虚构标准商品名称"; calls.push("style"); }
        } else if (path.endsWith("/validate")) { expect(style.payload.standard_name).toBe("虚构标准商品名称"); expect(sku.payload.standard_size).toBe("XL"); validated = true; calls.push("validate"); }
        else throw new Error(`Unexpected fixture write: ${path}`);
        revision++; return route.fulfill({ json: { safe_result: { workflow_revision: revision } } });
      }
      throw new Error(`Unexpected fictional request: ${path}`);
    });
    await page.goto("/catalog/imports/42"); await expect(page.getByRole("heading", { name: "商品主档审核", exact: true })).toBeVisible();
    const panel = page.getByRole("complementary", { name: "商品审核问题", exact: true });
    await page.getByRole("searchbox", { name: "搜索当前审核项", exact: true }).fill("fictional-hidden-filter");
    await panel.getByRole("button", { name: "定位问题 2", exact: true }).click();
    await expect(page.getByRole("tab", { name: /^SKU 标准化/ })).toHaveAttribute("aria-selected", "true");
    const size = page.getByLabel("fictional-sku:2 standard_size", { exact: true }); await expect(size).toBeFocused();
    await expect(page.getByRole("checkbox", { name: "仅看待处理", exact: true })).not.toBeChecked();
    await expect(page.getByRole("searchbox", { name: "搜索当前审核项", exact: true })).toHaveValue(sku.row_key);
    await panel.screenshot({ path: testInfo.outputPath(`issues-${width}.png`) });
    await size.fill("XL"); await expect(page.getByRole("button", { name: "重新校验", exact: true })).toBeDisabled(); await page.getByRole("button", { name: "保存此行", exact: true }).click(); await expect(page.getByText("当前修订 4", { exact: true })).toBeVisible();
    await panel.getByRole("button", { name: "定位问题 1", exact: true }).click();
    const name = page.getByLabel("fictional-style:1 standard_name", { exact: true }); await expect(name).toBeFocused(); await name.fill("虚构标准商品名称"); await page.getByRole("button", { name: "保存此行", exact: true }).click(); await expect(page.getByText("当前修订 5", { exact: true })).toBeVisible();
    await page.getByRole("button", { name: "重新校验", exact: true }).click(); await expect(page.getByText("当前修订 6", { exact: true })).toBeVisible(); await expect(panel).toHaveCount(0);
    await page.reload(); await expect(page.getByText("当前修订 6", { exact: true })).toBeVisible(); await expect(panel).toHaveCount(0);
    await page.getByRole("checkbox", { name: "仅看待处理", exact: true }).uncheck(); await expect(name).toHaveValue("虚构标准商品名称"); await page.getByRole("tab", { name: /^SKU 标准化/ }).click(); await expect(size).toHaveValue("XL");
    expect(calls).toEqual(["sku", "style", "validate"]); expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
  });
}
