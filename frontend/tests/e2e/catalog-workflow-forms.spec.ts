import { expect, test, type Page } from "@playwright/test";
import type { CatalogImportSummary } from "../../src/features/catalog/catalogTypes";

async function fixture(page: Page, baseURL: string, highRisk = false) {
  await page.context().addCookies([{ name: "clsen_csrf", value: "fictional-catalog-csrf", url: baseURL }]);
  const imported: CatalogImportSummary = {
    import_id: 42, workflow_revision: 3, catalog_publication_revision: 7, base_catalog_version_id: 4, export_id: 8001,
    parse_attempt_revision: 1, source_kind: "online", status: "ready_for_approval", failure_reason_code: null, has_original_file: false,
    submitted_by_user_id: 88, validation_run_id: 12,
    permissions: { can_view: true, can_edit: true, can_preview: true, can_approve_normal: true, can_approve_high_risk: false,
      can_rebase: true, can_reject: true, can_withdraw: false, can_resume: false, can_validate: false, can_submit: false, can_download_original: false },
  };
  const row = { row_key: "demo-style-1", row_origin: "system", projection_state: "included", section: "styles", payload: { style_code: "DEMO-01", standard_name: "", status: "active" } };
  const commands: { action: string; body: Record<string, unknown>; key: string }[] = [];
  let failRebase = true;
  await page.route(url => url.pathname.startsWith("/api/"), async route => {
    const req = route.request(); const path = new URL(req.url()).pathname;
    if (path === "/api/auth/me") return route.fulfill({ json: { id: 88, username: "fictional-review-manager", display_name: "虚构审核员", roles: ["data_manager"] } });
    if (path === "/api/data-calendar/site-context") return route.fulfill({ json: { site_id: 1, site_code: "US", display_name: "虚构站点", site_config_version_id: 2, source_timezone: "UTC", reporting_timezone: "UTC", currency_code: "USD" } });
    if (path === "/api/dashboard/style-readiness") return route.fulfill({ json: { published_reports: 0, prerequisites_present: false } });
    if (path === "/api/catalog/imports/42" && req.method() === "GET") return route.fulfill({ json: imported });
    if (path.includes("/rows/")) return route.fulfill({ json: { rows: highRisk && path.endsWith("/styles") ? [row] : [], total_rows: highRisk && path.endsWith("/styles") ? 1 : 0, workflow_revision: imported.workflow_revision } });
    if (path.startsWith("/api/catalog/imports/42/") && req.method() === "POST") {
      const action = path.split("/").at(-1)!; const body = req.postDataJSON() as Record<string, unknown>; const key = req.headers()["idempotency-key"]!;
      expect(req.headers()["x-csrf-token"]).toBe("fictional-catalog-csrf"); expect(key).toMatch(/^[0-9a-f-]{36}$/);
      expect(body.expected_workflow_revision).toBe(imported.workflow_revision); commands.push({ action, body, key });
      if (action === "approval-preview") return route.fulfill({ json: { safe_result: { risk: highRisk ? "high" : "normal", included_row_count: 18, audit_only_row_count: 2, catalog_publication_revision: imported.catalog_publication_revision, projection_id: 901, projection_digest: "fictional-digest" } } });
      if (action === "rebase") {
        expect(body).toMatchObject({ replacement_export_id: 8002, expected_catalog_publication_revision: imported.catalog_publication_revision });
        if (failRebase) { failRebase = false; return route.fulfill({ status: 503, json: { error: { code: "UNAVAILABLE", message: "示例传输失败，本次调整尚未提交。" } } }); }
        imported.workflow_revision++; imported.catalog_publication_revision++;
        return route.fulfill({ json: { safe_result: { workflow_revision: imported.workflow_revision } } });
      }
      if (action === "approve") {
        expect(body).toMatchObject({ expected_catalog_publication_revision: 8, projection_id: 901, projection_digest: "fictional-digest", reason: "虚构批准依据" });
        imported.status = "approved"; imported.approved_catalog_version_number = 5; imported.workflow_revision++;
        return route.fulfill({ json: { safe_result: { catalog_version_number: 5, workflow_revision: imported.workflow_revision } } });
      }
      if (action === "reject" || action === "withdraw") {
        expect(body.reason).toBe("虚构拒绝与撤回依据");
        imported.workflow_revision++;
        return route.fulfill({ json: { safe_result: { workflow_revision: imported.workflow_revision } } });
      }
      throw new Error(`Unexpected fictional command ${action}`);
    }
    throw new Error(`Unexpected fictional route ${req.method()} ${path}`);
  });
  await page.goto("/catalog/imports/42");
  await expect(page.getByRole("heading", { name: "商品主档审核", exact: true })).toBeVisible();
  return { commands, imported };
}

for (const width of [1280, 390]) {
  test(`actual catalog workflow failure, rebase, preview, approval and reload at ${width}px`, async ({ page, baseURL }) => {
    await page.setViewportSize({ width, height: 900 }); const { commands } = await fixture(page, baseURL!);
    await page.getByRole("button", { name: "生成批准预览", exact: true }).click();
    const reason = page.getByRole("textbox", { name: "批准原因", exact: true });
    await reason.fill("ab"); await expect(page.getByRole("button", { name: "确认批准目录", exact: true })).toBeDisabled();
    await reason.fill("虚构批准依据"); await page.getByText("高级操作 · 调整目录基准", { exact: true }).click();
    const id = page.getByRole("textbox", { name: "替代导出编号（export ID）", exact: true });
    await id.fill("8002"); await page.getByRole("button", { name: "调整到新基准", exact: true }).click();
    await expect(page.getByRole("alert")).toContainText("输入内容已保留"); await expect(id).toHaveValue("8002"); await expect(reason).toHaveValue("虚构批准依据");
    expect(commands.filter(c => c.action === "rebase")).toHaveLength(1);
    await page.getByRole("button", { name: "调整到新基准", exact: true }).click();
    await expect(page.getByText("当前修订 4", { exact: true })).toBeVisible();
    await expect(reason).toHaveCount(0); await page.reload();
    await page.getByRole("button", { name: "生成批准预览", exact: true }).click();
    await reason.fill("虚构批准依据"); await page.getByRole("button", { name: "确认批准目录", exact: true }).click();
    await expect(page.getByRole("heading", { name: "已批准生效", exact: true })).toBeVisible(); await page.reload();
    await expect(page.getByRole("heading", { name: "已批准生效", exact: true })).toBeVisible();
    await expect(page.getByRole("button", { name: "确认批准目录", exact: true })).toHaveCount(0);
    await expect(page.getByRole("link", { name: "查看目录版本", exact: true })).toHaveAttribute("href", "/catalog/versions");
    const rebases = commands.filter(c => c.action === "rebase"); expect(rebases).toHaveLength(2); expect(rebases[0]!.key).not.toBe(rebases[1]!.key);
    expect(commands.filter(c => c.action === "approve")).toHaveLength(1);
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
  });
}

test("actual unsaved draft blocks workflow fields and high risk cannot approve", async ({ page, baseURL }) => {
  const { commands, imported } = await fixture(page, baseURL!, true);
  await page.getByRole("button", { name: "生成批准预览", exact: true }).click();
  await expect(page.getByText("风险：高风险（仅管理员可批准）", { exact: true })).toBeVisible();
  await expect(page.getByRole("button", { name: "确认批准目录", exact: true })).toHaveCount(0);
  await page.getByLabel("demo-style-1 standard_name", { exact: true }).fill("虚构新名称");
  await expect(page.getByRole("textbox", { name: "批准原因", exact: true })).toBeDisabled();
  await expect(page.getByRole("button", { name: "生成批准预览", exact: true })).toBeDisabled();
  await page.getByText("高级操作 · 调整目录基准", { exact: true }).click();
  await expect(page.getByRole("textbox", { name: "替代导出编号（export ID）", exact: true })).toBeDisabled();
  await page.getByRole("button", { name: "撤销本行修改", exact: true }).click();
  await expect(page.getByRole("button", { name: "生成批准预览", exact: true })).toBeEnabled();
  imported.workflow_revision++;
  await page.getByRole("button", { name: "重新读取草稿", exact: true }).click();
  await expect(page.getByRole("textbox", { name: "批准原因", exact: true })).toHaveCount(0);
  expect(commands.every(c => c.action === "approval-preview")).toBe(true);
});

test("actual rejection and withdrawal use the shared entered reason and latest revision", async ({ page, baseURL }) => {
  const { commands, imported } = await fixture(page, baseURL!);
  imported.permissions.can_withdraw = true; await page.reload();
  await page.getByRole("textbox", { name: "操作原因", exact: true }).fill("虚构拒绝与撤回依据");
  await page.getByRole("button", { name: "拒绝", exact: true }).click();
  await expect(page.getByText("当前修订 4", { exact: true })).toBeVisible();
  await page.getByRole("button", { name: "撤回", exact: true }).click();
  await expect(page.getByText("当前修订 5", { exact: true })).toBeVisible();
  expect(commands.map(c => [c.action, c.body.expected_workflow_revision])).toEqual([["reject", 3], ["withdraw", 4]]);
  await page.reload(); await expect(page.getByText("当前修订 5", { exact: true })).toBeVisible();
});
