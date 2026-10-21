import { act, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import type { Principal } from "../../api/types";
import { AdminConsole } from "./AdminConsole";

const administrator: Principal = {
  id: 1,
  username: "tcj",
  display_name: "平台管理员",
  roles: ["admin"],
};

const viewer: Principal = {
  id: 9,
  username: "viewer",
  display_name: "查看人员",
  roles: ["viewer"],
};

const userRecord = {
  id: 2,
  username: "operator",
  display_name: "数据审核员",
  email: "operator@example.com",
  status: "active",
  roles: ["data_manager"],
  last_login_at: null,
  created_at: "2026-08-01T01:00:00Z",
  updated_at: "2026-08-10T01:00:00Z",
} as const;

const siteConfig = {
  id: 1,
  site_id: 1,
  site_code: "amazon_us",
  site_display_name: "Amazon US",
  version_number: 1,
  source_timezone: "America/Los_Angeles",
  reporting_timezone: "America/Los_Angeles",
  currency_code: "USD",
  effective_at: "2026-08-01T00:00:00Z",
  change_reason: "初始配置",
  created_by_user_id: 1,
  created_at: "2026-08-01T00:00:00Z",
  is_current: true,
} as const;

function jsonResponse(payload: unknown, status = 200) {
  return new Response(JSON.stringify(payload), {
    headers: { "Content-Type": "application/json" },
    status,
  });
}

function pathOf(input: string | URL | Request) {
  return typeof input === "string" ? input : input instanceof URL ? input.href : input.url;
}

function requestBody(init?: RequestInit) {
  if (typeof init?.body !== "string") throw new Error("Expected a JSON body.");
  return JSON.parse(init.body) as Record<string, unknown>;
}

function baseAdminFetch(
  extension?: (path: string, init?: RequestInit) => Promise<Response> | undefined,
) {
  return vi.fn((input: string | URL | Request, init?: RequestInit) => {
    const path = pathOf(input);
    const extended = extension?.(path, init);
    if (extended) return extended;
    if (path === "/api/admin/roles") {
      return Promise.resolve(jsonResponse([
        { code: "admin", description: "全部管理权限" },
        { code: "data_manager", description: "导入、审核与发布" },
        { code: "viewer", description: "查看已发布数据" },
      ]));
    }
    if (path === "/api/admin/users") return Promise.resolve(jsonResponse([userRecord]));
    if (path === "/api/admin/site-config-versions") return Promise.resolve(jsonResponse([siteConfig]));
    if (path.startsWith("/api/admin/audit-events?")) {
      return Promise.resolve(jsonResponse({ items: [], total: 0, limit: 20, offset: 0, next_offset: null }));
    }
    if (path === "/api/admin/maintenance") {
      return Promise.resolve(jsonResponse({
        backups: [{
          id: 7,
          backup_uuid: "0123456789abcdef0123456789abcdef",
          status: "succeeded",
          database_name: "clsen_data_test",
          schema_revision: "0018",
          key_id: "local-20260811",
          raw_file_count: 4,
          publication_count: 2,
          version_count: 8,
          audit_event_count: 12,
          started_at: "2026-08-11T05:00:00Z",
          sealed_at: "2026-08-11T05:00:01Z",
          completed_at: "2026-08-11T05:00:02Z",
          failure_code: null,
          restore_verified_at: "2026-08-11T05:10:00Z",
        }],
        restores: [],
        outbox: { pending: 1, processing: 0, completed: 3, failed: 0, oldest_pending_at: "2026-08-11T05:11:00Z" },
        write_lock: { held: false, owner_connection_id: null, observed_seconds: 0, warning: false },
        observed_at: "2026-09-04T08:00:00Z",
        maintenance_active: false,
        worker: {
          query_health: "healthy",
          failure_code: null,
          thresholds: {
            heartbeat_seconds: 10,
            stale_seconds: 30,
            offline_seconds: 60,
            refresh_seconds: 15,
          },
          instances: [{
            instance_id: "fedcba9876543210fedcba9876543210",
            role: "local_worker",
            build_id: "stage2-test",
            supported_queues: ["return_dedup", "publication_outbox", "catalog_export", "catalog_import"],
            lifecycle_status: "running",
            heartbeat_status: "online",
            heartbeat_sequence: 8,
            last_heartbeat_at: "2026-09-04T07:59:55Z",
            heartbeat_age_seconds: 5,
            last_result_code: "heartbeat_succeeded",
            consumers: [],
          }],
        },
        queues: [
          ["return_dedup", true, true, false, true, false],
          ["publication_outbox", true, true, true, true, false],
          ["catalog_export", false, false, false, false, false],
          ["catalog_import", true, true, false, false, true],
        ].map(([queue_name, actionable, in_flight, retry_wait, stale, stuck]) => ({
          queue_name,
          query_health: "healthy",
          consumer_health: "not_observed",
          failure_code: null,
          native_status_counts: {},
          actionable: actionable ? 0 : null,
          in_flight: in_flight ? 0 : null,
          retry_wait: retry_wait ? 0 : null,
          stale: stale ? 0 : null,
          stuck: stuck ? 0 : null,
          failed: 0,
          unresolved_building: queue_name === "catalog_export" ? 0 : null,
          oldest_work_at: null,
          next_retry_at: null,
          last_succeeded_at: null,
          last_failed_at: null,
          consecutive_failures: null,
          capabilities: { actionable, in_flight, retry_wait, stale, stuck },
        })),
      }));
    }
    throw new Error(`Unhandled request: ${path}`);
  });
}

describe("AdminConsole", () => {
  beforeEach(() => {
    document.cookie = "clsen_csrf=csrf-admin-token; path=/";
  });

  afterEach(() => {
    document.cookie = "clsen_csrf=; expires=Thu, 01 Jan 1970 00:00:00 GMT; path=/";
    vi.useRealTimers();
    vi.unstubAllGlobals();
  });

  it("keeps the administrator APIs completely outside the viewer boundary", async () => {
    const fetchMock = vi.fn();
    vi.stubGlobal("fetch", fetchMock);

    render(<AdminConsole principal={viewer} />);

    expect(screen.getByRole("heading", { name: "管理员权限边界" })).toBeVisible();
    expect(screen.getByText("当前账号不能读取用户、站点配置或内部审计。" )).toBeVisible();
    await waitFor(() => expect(fetchMock).not.toHaveBeenCalled());
  });

  it("creates an account and reuses the same UUID after an uncertain response", async () => {
    const operationKeys: string[] = [];
    let attempts = 0;
    const fetchMock = baseAdminFetch((path, init) => {
      if (path !== "/api/admin/users" || init?.method !== "POST") return undefined;
      operationKeys.push(new Headers(init.headers).get("Idempotency-Key") ?? "");
      attempts += 1;
      if (attempts === 1) {
        return Promise.resolve(jsonResponse({
          error: { code: "admin_operation_outcome_unknown", message: "结果暂时无法确认", request_id: "r1" },
        }, 503));
      }
      expect(requestBody(init)).toMatchObject({
        username: "reviewer",
        display_name: "每日审核员",
        email: "reviewer@example.com",
        roles: ["data_manager"],
        status: "active",
        password: "Temporary-Password-42",
      });
      return Promise.resolve(jsonResponse({
        ...userRecord,
        id: 3,
        username: "reviewer",
        display_name: "每日审核员",
        email: "reviewer@example.com",
      }, 201));
    });
    vi.stubGlobal("fetch", fetchMock);
    const user = userEvent.setup();

    render(<AdminConsole principal={administrator} />);
    await screen.findByRole("heading", { name: "账号与角色" });
    await user.click(screen.getByRole("button", { name: "新建账号" }));
    const form = screen.getByRole("form", { name: "创建账号" });
    await user.type(within(form).getByLabelText("账号"), "reviewer");
    await user.type(within(form).getByLabelText("显示名"), "每日审核员");
    await user.type(within(form).getByLabelText("邮箱（可选）"), "reviewer@example.com");
    await user.type(within(form).getByLabelText("临时密码"), "Temporary-Password-42");
    await user.click(within(form).getByLabelText("数据管理员"));
    await user.click(within(form).getByRole("button", { name: "创建账号" }));

    expect(await screen.findByText("结果暂时无法确认")).toBeVisible();
    await user.click(within(form).getByRole("button", { name: "创建账号" }));
    expect(await screen.findByText("账号 reviewer 已创建。" )).toBeVisible();
    expect(operationKeys).toHaveLength(2);
    expect(operationKeys[0]).toMatch(/^[0-9a-f-]{36}$/i);
    expect(operationKeys[1]).toBe(operationKeys[0]);
    expect(within(form).getByLabelText("临时密码")).toHaveValue("");
  });

  it("uses a new UUID when the creation password changes after an uncertain response", async () => {
    const operationKeys: string[] = [];
    const requestBodies: Record<string, unknown>[] = [];
    let attempts = 0;
    const fetchMock = baseAdminFetch((path, init) => {
      if (path !== "/api/admin/users" || init?.method !== "POST") return undefined;
      operationKeys.push(new Headers(init.headers).get("Idempotency-Key") ?? "");
      requestBodies.push(requestBody(init));
      attempts += 1;
      if (attempts === 1) {
        return Promise.resolve(jsonResponse({
          error: { code: "admin_operation_outcome_unknown", message: "结果暂时无法确认", request_id: "r-password-create" },
        }, 503));
      }
      return Promise.resolve(jsonResponse({
        ...userRecord,
        id: 3,
        username: "reviewer",
        display_name: "每日审核员",
      }, 201));
    });
    vi.stubGlobal("fetch", fetchMock);
    const user = userEvent.setup();

    render(<AdminConsole principal={administrator} />);
    await screen.findByRole("heading", { name: "账号与角色" });
    await user.click(screen.getByRole("button", { name: "新建账号" }));
    const form = screen.getByRole("form", { name: "创建账号" });
    await user.type(within(form).getByLabelText("账号"), "reviewer");
    await user.type(within(form).getByLabelText("显示名"), "每日审核员");
    const password = within(form).getByLabelText("临时密码");
    await user.type(password, "Temporary-Password-42");
    await user.click(within(form).getByLabelText("数据管理员"));
    await user.click(within(form).getByRole("button", { name: "创建账号" }));

    expect(await screen.findByText("结果暂时无法确认")).toBeVisible();
    await user.clear(password);
    await user.type(password, "Changed-Password-43");
    await user.click(within(form).getByRole("button", { name: "创建账号" }));

    expect(await screen.findByText("账号 reviewer 已创建。" )).toBeVisible();
    expect(operationKeys).toHaveLength(2);
    expect(operationKeys[0]).toMatch(/^[0-9a-f-]{36}$/i);
    expect(operationKeys[1]).toMatch(/^[0-9a-f-]{36}$/i);
    expect(operationKeys[1]).not.toBe(operationKeys[0]);
    expect(requestBodies.map((body) => body.password)).toEqual([
      "Temporary-Password-42",
      "Changed-Password-43",
    ]);
  });

  it("updates mutable account fields with expected_updated_at and refreshes on conflict", async () => {
    let userLoads = 0;
    const patchBodies: Record<string, unknown>[] = [];
    const fetchMock = baseAdminFetch((path, init) => {
      if (path === "/api/admin/users" && !init?.method) {
        userLoads += 1;
        return Promise.resolve(jsonResponse([userLoads === 1 ? userRecord : {
          ...userRecord,
          display_name: "其他管理员已更新",
          updated_at: "2026-08-10T02:00:00Z",
        }]));
      }
      if (path === "/api/admin/users/2" && init?.method === "PATCH") {
        patchBodies.push(requestBody(init));
        return Promise.resolve(jsonResponse({
          error: { code: "user_version_conflict", message: "账号已被其他管理员修改", request_id: "r2" },
        }, 409));
      }
      return undefined;
    });
    vi.stubGlobal("fetch", fetchMock);
    const user = userEvent.setup();

    render(<AdminConsole principal={administrator} />);
    await screen.findByText("数据审核员");
    await user.click(screen.getByRole("button", { name: "编辑 operator" }));
    const form = screen.getByRole("form", { name: "编辑 operator" });
    await user.clear(within(form).getByLabelText("显示名"));
    await user.type(within(form).getByLabelText("显示名"), "审核负责人");
    await user.selectOptions(within(form).getByLabelText("账号状态"), "disabled");
    await user.type(within(form).getByLabelText("新密码（留空则不修改）"), "Another-Password-42");
    await user.click(within(form).getByRole("button", { name: "保存账号修改" }));

    await screen.findByText("账号已被其他管理员修改；已载入最新值，请重新确认后再保存。" );
    expect(patchBodies[0]).toMatchObject({
      expected_updated_at: userRecord.updated_at,
      display_name: "审核负责人",
      status: "disabled",
      roles: ["data_manager"],
      new_password: "Another-Password-42",
    });
    expect(await screen.findByText("其他管理员已更新")).toBeVisible();
    expect(screen.queryByLabelText("新密码（留空则不修改）")).not.toBeInTheDocument();
  });

  it("saves an account update without sending a password when the password field is blank", async () => {
    let patchBody: Record<string, unknown> | undefined;
    const fetchMock = baseAdminFetch((path, init) => {
      if (path === "/api/admin/users/2" && init?.method === "PATCH") {
        patchBody = requestBody(init);
        return Promise.resolve(jsonResponse({
          ...userRecord,
          display_name: "审核负责人",
          email: null,
          roles: ["viewer"],
          updated_at: "2026-08-10T02:00:00Z",
        }));
      }
      return undefined;
    });
    vi.stubGlobal("fetch", fetchMock);
    const user = userEvent.setup();

    render(<AdminConsole principal={administrator} />);
    await user.click(await screen.findByRole("button", { name: "编辑 operator" }));
    const form = screen.getByRole("form", { name: "编辑 operator" });
    await user.clear(within(form).getByLabelText("显示名"));
    await user.type(within(form).getByLabelText("显示名"), "审核负责人");
    await user.clear(within(form).getByLabelText("邮箱（可选）"));
    await user.click(within(form).getByLabelText("数据管理员"));
    await user.click(within(form).getByLabelText("查看人员"));
    await user.click(within(form).getByRole("button", { name: "保存账号修改" }));

    expect(await screen.findByText("账号 operator 已更新。" )).toBeVisible();
    expect(patchBody).toMatchObject({
      display_name: "审核负责人",
      email: null,
      expected_updated_at: userRecord.updated_at,
      roles: ["viewer"],
      status: "active",
    });
    expect(patchBody).not.toHaveProperty("new_password");
  });

  it("uses a new UUID when the edited password changes after an uncertain response", async () => {
    const operationKeys: string[] = [];
    const requestBodies: Record<string, unknown>[] = [];
    let attempts = 0;
    const fetchMock = baseAdminFetch((path, init) => {
      if (path !== "/api/admin/users/2" || init?.method !== "PATCH") return undefined;
      operationKeys.push(new Headers(init.headers).get("Idempotency-Key") ?? "");
      requestBodies.push(requestBody(init));
      attempts += 1;
      if (attempts <= 2) {
        return Promise.resolve(jsonResponse({
          error: { code: "admin_operation_outcome_unknown", message: "结果暂时无法确认", request_id: "r-password-edit" },
        }, 503));
      }
      return Promise.resolve(jsonResponse({
        ...userRecord,
        updated_at: "2026-08-10T02:00:00Z",
      }));
    });
    vi.stubGlobal("fetch", fetchMock);
    const user = userEvent.setup();

    render(<AdminConsole principal={administrator} />);
    await user.click(await screen.findByRole("button", { name: "编辑 operator" }));
    const form = screen.getByRole("form", { name: "编辑 operator" });
    const password = within(form).getByLabelText("新密码（留空则不修改）");
    const saveButton = within(form).getByRole("button", { name: "保存账号修改" });
    await user.type(password, "Another-Password-42");
    await user.click(saveButton);

    expect(await screen.findByText("结果暂时无法确认")).toBeVisible();
    await user.clear(password);
    await user.type(password, "Changed-Password-43");
    await user.click(saveButton);

    await waitFor(() => expect(operationKeys).toHaveLength(2));
    await waitFor(() => expect(saveButton).toBeEnabled());
    await user.click(saveButton);

    expect(await screen.findByText("账号 operator 已更新。现有会话已撤销。" )).toBeVisible();
    expect(operationKeys).toHaveLength(3);
    expect(operationKeys[0]).toMatch(/^[0-9a-f-]{36}$/i);
    expect(operationKeys[1]).toMatch(/^[0-9a-f-]{36}$/i);
    expect(operationKeys[1]).not.toBe(operationKeys[0]);
    expect(operationKeys[2]).toBe(operationKeys[1]);
    expect(requestBodies.map((body) => body.new_password)).toEqual([
      "Another-Password-42",
      "Changed-Password-43",
      "Changed-Password-43",
    ]);
  });

  it("creates a versioned site configuration and pages the redacted audit ledger", async () => {
    const auditOffsets: number[] = [];
    const fetchMock = baseAdminFetch((path, init) => {
      if (path === "/api/admin/site-config-versions" && init?.method === "POST") {
        expect(requestBody(init)).toMatchObject({
          site_id: 1,
          source_timezone: "America/Los_Angeles",
          reporting_timezone: "Asia/Shanghai",
          currency_code: "USD",
          change_reason: "调整事件日统计口径",
        });
        return Promise.resolve(jsonResponse({
          ...siteConfig,
          id: 2,
          version_number: 2,
          reporting_timezone: "Asia/Shanghai",
          change_reason: "调整事件日统计口径",
        }, 201));
      }
      if (path.startsWith("/api/admin/audit-events?")) {
        const url = new URL(path, "http://localhost");
        const offset = Number(url.searchParams.get("offset"));
        auditOffsets.push(offset);
        return Promise.resolve(jsonResponse({
          items: [{
            id: offset + 1,
            site_id: 1,
            actor_user_id: 1,
            actor_username: "tcj",
            event_type: "admin.site_config_created",
            object_type: "site_config_version",
            object_id: "2",
            request_id: "request-visible",
            redacted_payload: {
              reporting_timezone: "Asia/Shanghai",
              order_id: "SENSITIVE-ORDER-123",
              customer_message: "SENSITIVE-CUSTOMER-MESSAGE",
            },
            occurred_at: "2026-08-10T03:00:00Z",
          }],
          total: 21,
          limit: 20,
          offset,
          next_offset: offset === 0 ? 20 : null,
        }));
      }
      return undefined;
    });
    vi.stubGlobal("fetch", fetchMock);
    const user = userEvent.setup();

    render(<AdminConsole principal={administrator} />);
    await user.click(await screen.findByRole("button", { name: "站点配置" }));
    expect(await screen.findByRole("heading", { name: "站点配置版本" })).toBeVisible();
    await user.click(screen.getByRole("button", { name: "新建配置版本" }));
    const form = screen.getByRole("form", { name: "创建站点配置版本" });
    await user.clear(within(form).getByLabelText("统计时区"));
    await user.type(within(form).getByLabelText("统计时区"), "Asia/Shanghai");
    await user.type(within(form).getByLabelText("变更原因"), "调整事件日统计口径");
    await user.click(within(form).getByRole("button", { name: "创建配置版本" }));
    expect(await screen.findByText("站点配置 v2 已创建并设为当前版本。" )).toBeVisible();

    await user.click(screen.getByRole("button", { name: "内部审计" }));
    expect(await screen.findByText("admin.site_config_created")).toBeVisible();
    await user.click(screen.getByRole("button", { name: "下一页" }));
    await waitFor(() => expect(auditOffsets).toContain(20));
    expect(screen.queryByText(/SENSITIVE-ORDER-123|SENSITIVE-CUSTOMER-MESSAGE/)).not.toBeInTheDocument();
  });

  it("loads backup and worker status only when the maintenance tab opens", async () => {
    const fetchMock = baseAdminFetch();
    vi.stubGlobal("fetch", fetchMock);
    const user = userEvent.setup();

    render(<AdminConsole principal={administrator} />);
    await screen.findByRole("heading", { name: "账号与角色" });
    expect(fetchMock.mock.calls.map(([input]) => pathOf(input))).not.toContain("/api/admin/maintenance");

    await user.click(screen.getByRole("button", { name: "备份与任务" }));

    expect(await screen.findByRole("heading", { name: "备份与后台任务" })).toBeVisible();
    expect(await screen.findByText("0123456789ab")).toBeVisible();
    expect(screen.getByText("4 个原始对象 · 2 个发布指针 · schema 0018")).toBeVisible();
    expect(screen.getByText("待处理 1 · 失败 0")).toBeVisible();
  });

  it("refreshes only on the active maintenance tab and prevents overlap", async () => {
    let maintenanceCalls = 0;
    let rejectPending: ((reason: Error) => void) | undefined;
    const fetchMock = baseAdminFetch((path) => {
      if (path !== "/api/admin/maintenance") return undefined;
      maintenanceCalls += 1;
      if (maintenanceCalls !== 2) return undefined;
      return new Promise<Response>((_resolve, reject) => {
        rejectPending = reject;
      });
    });
    vi.stubGlobal("fetch", fetchMock);
    const user = userEvent.setup();

    render(<AdminConsole principal={administrator} />);
    await screen.findByRole("heading", { name: "账号与角色" });
    await user.click(screen.getByRole("button", { name: "备份与任务" }));
    expect(await screen.findByText("stage2-test")).toBeVisible();
    expect(maintenanceCalls).toBe(1);

    await user.click(screen.getByRole("button", { name: "账号与角色" }));
    vi.useFakeTimers();
    fireEvent.click(screen.getByRole("button", { name: "备份与任务" }));

    await act(async () => { await vi.advanceTimersByTimeAsync(15_000); });
    expect(maintenanceCalls).toBe(2);
    await act(async () => { await vi.advanceTimersByTimeAsync(15_000); });
    expect(maintenanceCalls).toBe(2);

    await act(async () => {
      rejectPending?.(new Error("网络暂时不可用"));
      await Promise.resolve();
    });
    expect(screen.getByText("状态可能已过期：网络暂时不可用")).toBeVisible();
    expect(screen.getByText("stage2-test")).toBeVisible();

    await act(async () => { await vi.advanceTimersByTimeAsync(15_000); });
    expect(maintenanceCalls).toBe(3);
    fireEvent.click(screen.getByRole("button", { name: "账号与角色" }));
    await act(async () => { await vi.advanceTimersByTimeAsync(30_000); });
    expect(maintenanceCalls).toBe(3);
  });

  it("only exposes force rebuild when the review route supplies immutable source context", async () => {
    const rebuilt = vi.fn();
    let rebuildBody: Record<string, unknown> | undefined;
    const fetchMock = baseAdminFetch((path, init) => {
      if (path === "/api/admin/drafts/51/force-rebuild" && init?.method === "POST") {
        rebuildBody = requestBody(init);
        return Promise.resolve(jsonResponse({
          operation_token: new Headers(init.headers).get("Idempotency-Key"),
          dataset_id: 41,
          version_id: 52,
          version_no: 3,
          status: "draft",
          data_revision: 0,
          review_revision: 0,
          superseded_version_ids: [51],
          source_dataset_id: 41,
          source_version_id: 51,
        }, 201));
      }
      return undefined;
    });
    vi.stubGlobal("fetch", fetchMock);
    const user = userEvent.setup();

    render(
      <AdminConsole
        forceRebuildContext={{
          batchId: 11,
          expectedActiveDraft: { version_id: 51, data_revision: 2, review_revision: 3 },
          expectedPublicationVersionId: 49,
          parseBaselineId: 31,
          reportDate: "2026-08-10",
          versionId: 51,
        }}
        onForceRebuilt={rebuilt}
        principal={administrator}
      />,
    );
    await user.click(await screen.findByRole("button", { name: "草稿恢复" }));
    const form = screen.getByRole("form", { name: "强制重建草稿" });
    await user.type(within(form).getByLabelText("重建原因"), "解析基线已由人工确认，需要重新构建草稿");
    await user.click(within(form).getByLabelText("我确认不会绕过校验，也不会覆盖已发布版本。"));
    await user.click(within(form).getByRole("button", { name: "强制重建草稿" }));

    expect(await screen.findByText("草稿已重建为 v3；新草稿仍需重新校验。" )).toBeVisible();
    expect(rebuildBody).toEqual({
      batch_id: 11,
      expected_active_draft: { version_id: 51, data_revision: 2, review_revision: 3 },
      expected_publication_version_id: 49,
      parse_baseline_id: 31,
      reason: "解析基线已由人工确认，需要重新构建草稿",
      report_date: "2026-08-10",
    });
    expect(rebuilt).toHaveBeenCalledWith(expect.objectContaining({ version_id: 52 }));
  });
});
