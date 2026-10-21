import { expect, test } from "@playwright/test";

test("return intake preserves context and requires explicit confirmation of a business CSV", async ({ page, baseURL }) => {
  await page.context().addCookies([{ name: "clsen_csrf", value: "synthetic-token", url: baseURL! }]);
  const date = "2026-08-13";
  let confirmed = false;
  let uploadCount = 0;
  let confirmCount = 0;
  const result = {
    batch_id: 44, dataset_id: 21, duplicate: false, encoding: "utf-8-sig",
    report_date: date, report_type: "business_report", version_id: 31,
    workspace_url: `/review/${date}?report_type=business_report`,
  };
  await page.route((url) => url.pathname.startsWith("/api/"), async (route) => {
    const url = new URL(route.request().url());
    const path = url.pathname;
    let body: unknown;
    if (path === "/api/auth/me") body = { id: 1, username: "synthetic-admin", display_name: "测试管理员", roles: ["admin"] };
    else if (path === "/api/auth/csrf") body = { csrf_token: "synthetic-token" };
    else if (path === "/api/data-calendar/site-context") body = { site_id: 1, site_config_version_id: 1, site_code: "amazon_us", display_name: "Amazon US", reporting_timezone: "America/Los_Angeles", source_timezone: "America/Los_Angeles", currency_code: "USD" };
    else if (path === "/api/data-calendar" || path === "/api/data-calendar/days") body = [];
    else if (path === `/api/workbench/dates/${date}`) {
      const type = url.searchParams.get("report_type");
      const draft = confirmed && type === "business_report";
      body = {
        report_date: date, report_type: type, source: draft ? "draft" : "empty",
        head: draft ? { version_id: 31, version_no: 1, dataset_id: 21, status: "draft", data_revision: 0, review_revision: 0 } : null,
        columns: [], rows: [], actions: [], validation: null, pending_upload_count: 0,
        tabs: [{ report_type: "business_report", source: confirmed ? "draft" : "empty" }, { report_type: "return_report", source: "empty" }],
        pagination: { page: 1, page_size: 50, total_pages: 1, total_rows: 0 },
        permissions: { can_upload: true, can_validate: draft, can_publish: false, can_edit: draft, can_undo: false, can_create_revision: false },
      };
    } else if (path === "/api/workbench/imports") {
      uploadCount += 1;
      expect(url.searchParams.get("expected_report_type")).toBe("return_report");
      body = { ...result, status: "confirmation_required", stage: "recognition", issue_codes: ["selected_type_conflict"] };
    } else if (path === "/api/workbench/imports/44/confirm") {
      expect(route.request().postDataJSON()).toMatchObject({ report_type: "business_report", report_date: date });
      confirmed = true;
      confirmCount += 1;
      body = { ...result, status: "workspace_ready", stage: "draft", issue_codes: [] };
    } else {
      return route.fulfill({ status: 500, json: { error: { code: "unexpected_synthetic_request", message: path } } });
    }
    return route.fulfill({ json: body });
  });
  await page.goto(`/review/${date}?report_type=return_report&page=1`);
  await expect(page.getByRole("button", { name: /^退货报告\s*未导入$/ })).toHaveAttribute("aria-current", "page");
  await expect(page.getByText(`${date} · 退货报告`, { exact: true })).toBeVisible();
  await page.reload();
  await expect(page).toHaveURL(/report_type=return_report/);
  await page.getByLabel("选择 CSV 文件", { exact: true }).setInputFiles({ name: "synthetic-business.csv", mimeType: "text/csv", buffer: Buffer.from("SKU,Sessions\nSYNTHETIC,2\n") });
  await expect(page.getByText("文件类型与当前入口不一致", { exact: true })).toBeVisible();
  await expect(page.getByLabel("重新选择退货报告 CSV", { exact: true })).toBeVisible();
  await expect(page.getByText("所选文件：synthetic-business.csv", { exact: true })).toBeVisible();
  expect(uploadCount).toBe(1);
  expect(confirmCount).toBe(0);
  await expect(page).toHaveURL(/report_type=return_report/);
  await page.getByRole("button", { name: "按经营报告继续", exact: true }).click();
  await expect(page).toHaveURL(/report_type=business_report/);
  await expect(page.getByText("草稿自动保存，但不会进入总表；检查并发布后才会显示", { exact: true })).toBeVisible();
  expect(confirmCount).toBe(1);
  await page.reload();
  await expect(page.getByText("草稿自动保存，但不会进入总表；检查并发布后才会显示", { exact: true })).toBeVisible();
});
