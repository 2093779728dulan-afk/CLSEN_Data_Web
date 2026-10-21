import { expect, test, type Page } from "@playwright/test";
import { accountPrincipal, accountRoles, accountUsers } from "../../src/features/admin/AdminAccountsView.fixtures";

async function install(page: Page, role = "admin") {
  let users = structuredClone(accountUsers);
  const state = { readFailure: true, createFailure: true, updateFailure: true, conflict: false };
  const writes: { path: string; method: string; body: Record<string, unknown>; key?: string }[] = []; const unexpected: string[] = []; const adminReads: string[] = [];
  await page.context().addCookies([{ name: "clsen_csrf", value: "synthetic-accounts", url: test.info().project.use.baseURL! }]);
  await page.context().route(url => url.pathname.startsWith("/api/"), async route => {
    const request = route.request(); const url = new URL(request.url()); const path = url.pathname;
    const failure = (code: string, message: string, status = 503) => route.fulfill({ status, json: { error: { code, message } } });
    if (path.startsWith("/api/admin/") && request.method() === "GET") { expect(role).toBe("admin"); adminReads.push(path); }
    if (!["GET", "HEAD"].includes(request.method())) {
      expect(role).toBe("admin"); expect(request.headers()["x-csrf-token"]).toBe("synthetic-accounts");
      const key = request.headers()["idempotency-key"]; expect(key).toMatch(/^[0-9a-f-]{36}$/);
      writes.push({ path, method: request.method(), body: request.postDataJSON() as Record<string, unknown>, key });
    }
    if (path === "/api/auth/me") return route.fulfill({ json: { ...accountPrincipal, roles: [role] } });
    if (path === "/api/data-calendar/site-context") return route.fulfill({ json: { site_id: 1, site_code: "DEMO", display_name: "虚构站点", site_config_version_id: 2, source_timezone: "UTC", reporting_timezone: "UTC", currency_code: "USD" } });
    if (path === "/api/admin/roles") return state.readFailure ? failure("synthetic_unavailable", "虚构管理资料读取失败") : route.fulfill({ json: accountRoles });
    if (path === "/api/admin/site-config-versions") return route.fulfill({ json: [] });
    if (path === "/api/admin/audit-events") return route.fulfill({ json: { items: [], total: 0, limit: 20, offset: 0, next_offset: null } });
    if (path === "/api/admin/users" && request.method() === "GET") return route.fulfill({ json: users });
    if (path === "/api/admin/users" && request.method() === "POST") {
      const command = writes.at(-1)!; expect(command.body).toMatchObject({ username: "fictional-colleague", display_name: "虚构同事", roles: ["viewer"], status: "disabled", email: null });
      if (state.createFailure) return failure("admin_operation_outcome_unknown", "虚构创建结果暂时无法确认");
      const created = { ...accountUsers[2]!, id: 100, username: "fictional-colleague", display_name: "虚构同事" }; users = [...users, created]; return route.fulfill({ status: 201, json: created });
    }
    if (path === "/api/admin/users/100") {
      const command = writes.at(-1)!; expect(command.method).toBe("PATCH"); expect(command.body.expected_updated_at).toBe(users.find(user => user.id === 100)!.updated_at); expect(command.body).not.toHaveProperty("new_password");
      if (state.conflict) { users = users.map(user => user.id === 100 ? { ...user, display_name: "虚构其他管理员已修改", updated_at: "2026-09-12T08:00:00Z" } : user); state.conflict = false; return failure("user_version_conflict", "账号已被其他管理员修改", 409); }
      if (state.updateFailure) return failure("admin_operation_outcome_unknown", "虚构修改结果暂时无法确认");
      const updated = { ...users.find(user => user.id === 100)!, display_name: String(command.body.display_name), roles: command.body.roles as string[], status: command.body.status as "active" | "disabled" | "locked", email: command.body.email as string | null, updated_at: "2026-09-12T07:00:00Z" };
      users = users.map(user => user.id === 100 ? updated : user); return route.fulfill({ json: updated });
    }
    if (path === "/api/dashboard/daily-ledger") return route.fulfill({ json: { publications: [], site_config_versions: [], rows: [], range: { from_date: "2026-10-01", to_date: "2026-10-31" } } });
    if (path === "/api/data-calendar/days" || path === "/api/data-calendar") return route.fulfill({ json: [] });
    unexpected.push(`${request.method()} ${path}`); return failure("unexpected", "未定义测试请求");
  });
  return { state, writes, unexpected, adminReads };
}
for (const width of [1280, 390]) {
  test(`actual admin account creates, retries role edit and refreshes conflict at ${width}px`, async ({ page }) => {
    await page.setViewportSize({ width, height: 900 }); const { state, writes, unexpected } = await install(page);
    const errors: string[] = []; page.on("pageerror", error => errors.push(error.message));
    await page.goto("/admin"); await expect(page.getByRole("alert")).toContainText("虚构管理资料读取失败"); await expect(page.getByRole("button", { name: "新建账号", exact: true })).toBeDisabled();
    state.readFailure = false; await page.getByRole("button", { name: "重新载入管理资料", exact: true }).click(); await page.getByRole("button", { name: "新建账号", exact: true }).click();
    const create = page.getByRole("form", { name: "创建账号", exact: true });
    await create.getByRole("textbox", { name: "账号", exact: true }).fill("fictional-colleague"); await create.getByRole("textbox", { name: "显示名", exact: true }).fill("虚构同事"); await create.getByLabel(/^临时密码/).fill("Synthetic-only-123!");
    await create.getByRole("combobox", { name: "账号状态", exact: true }).selectOption("disabled"); await create.getByRole("checkbox", { name: "查看人员", exact: true }).check();
    await create.getByRole("button", { name: "创建账号", exact: true }).click(); await expect(page.getByRole("alert")).toContainText("虚构创建结果暂时无法确认");
    state.createFailure = false; await create.getByRole("button", { name: "创建账号", exact: true }).click(); await expect(page.getByText("账号 fictional-colleague 已创建。", { exact: true })).toBeVisible();
    const creates = writes.filter(write => write.method === "POST"); expect(creates).toHaveLength(2); expect(creates[1]?.key).toBe(creates[0]?.key);
    await page.getByRole("button", { name: "收起创建表单", exact: true }).click(); const opener = page.getByRole("button", { name: "编辑 fictional-colleague", exact: true }); await opener.click();
    const dialog = page.getByRole("dialog", { name: "编辑 @fictional-colleague", exact: true }); await dialog.getByRole("checkbox", { name: "数据管理员", exact: true }).check(); await dialog.getByRole("checkbox", { name: "查看人员", exact: true }).uncheck();
    await dialog.getByRole("button", { name: "保存账号修改", exact: true }).click(); await expect(dialog.getByRole("alert")).toContainText("虚构修改结果暂时无法确认"); await expect(dialog.getByRole("checkbox", { name: "数据管理员", exact: true })).toBeChecked();
    state.updateFailure = false; await dialog.getByRole("button", { name: "保存账号修改", exact: true }).click(); await expect(dialog).toHaveCount(0); await expect(opener).toBeFocused();
    const patches = writes.filter(write => write.method === "PATCH"); expect(patches).toHaveLength(2); expect(patches[1]?.key).toBe(patches[0]?.key); expect(patches[1]?.body.roles).toEqual(["data_manager"]);
    await page.reload(); await opener.click(); await expect(dialog.getByRole("checkbox", { name: "数据管理员", exact: true })).toBeChecked(); await expect(dialog.getByLabel("新密码（留空则不修改）", { exact: true })).toHaveValue("");
    state.conflict = true; await dialog.getByRole("textbox", { name: "显示名", exact: true }).fill("虚构待保存显示名"); await dialog.getByRole("button", { name: "保存账号修改", exact: true }).click(); await expect(dialog).toHaveCount(0);
    await expect(page.getByRole("alert")).toContainText("已载入最新值"); await expect(page.getByText("虚构其他管理员已修改", { exact: true })).toBeVisible();
    await opener.click(); await page.keyboard.press("Escape"); await expect(opener).toBeFocused();
    await page.getByRole("button", { name: "站点配置", exact: true }).click(); await expect(page.getByRole("heading", { name: "站点配置版本", exact: true })).toBeVisible(); await page.getByRole("button", { name: "账号与角色", exact: true }).click(); await expect(opener).toBeVisible();
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true); expect(unexpected).toEqual([]); expect(errors).toEqual([]);
  });
}
test("non-admin actual route redirects without reading administrator APIs", async ({ page }) => {
  const { writes, adminReads, unexpected } = await install(page, "viewer"); await page.goto("/admin"); await expect(page).toHaveURL(/\/$/); await expect(page.getByRole("heading", { name: "管理员控制台", exact: true })).toHaveCount(0);
  expect(adminReads).toEqual([]); expect(writes).toEqual([]); expect(unexpected).toEqual([]);
});
