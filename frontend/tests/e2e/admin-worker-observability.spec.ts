import path from "node:path";
import { expect, test, type Route } from "@playwright/test";

function json(route: Route, payload: unknown, status = 200) {
  return route.fulfill({
    body: JSON.stringify(payload),
    contentType: "application/json",
    status,
  });
}

const capabilities = {
  actionable: true,
  in_flight: true,
  retry_wait: false,
  stale: false,
  stuck: true,
};

const queueBase = {
  query_health: "healthy",
  consumer_health: "healthy",
  failure_code: null,
  native_status_counts: {},
  actionable: 0,
  in_flight: 0,
  retry_wait: null,
  stale: null,
  stuck: 0,
  failed: 0,
  unresolved_building: null,
  oldest_work_at: null,
  next_retry_at: null,
  last_succeeded_at: "2026-09-04T07:59:58Z",
  last_failed_at: null,
  consecutive_failures: 0,
  capabilities,
};

test("shows Worker status and refreshes only while the maintenance tab is active", async ({ page }) => {
  let maintenanceRequests = 0;
  await page.clock.install();
  await page.context().route((url) => url.hostname !== "127.0.0.1", (route) => route.abort());
  await page.route((url) => url.pathname.startsWith("/api/"), async (route) => {
    const { pathname } = new URL(route.request().url());
    if (pathname === "/api/auth/me") {
      return json(route, {
        id: 1,
        username: "admin",
        display_name: "平台管理员",
        roles: ["admin"],
      });
    }
    if (pathname === "/api/data-calendar/site-context") {
      return json(route, {
        site_id: 1,
        site_code: "amazon_us",
        display_name: "Amazon US",
        site_config_version_id: 1,
        source_timezone: "America/Los_Angeles",
        reporting_timezone: "America/Los_Angeles",
        currency_code: "USD",
      });
    }
    if (pathname === "/api/admin/roles") return json(route, []);
    if (pathname === "/api/admin/users") return json(route, []);
    if (pathname === "/api/admin/site-config-versions") return json(route, []);
    if (pathname === "/api/admin/audit-events") {
      return json(route, { items: [], total: 0, limit: 20, offset: 0, next_offset: null });
    }
    if (pathname === "/api/admin/maintenance") {
      maintenanceRequests += 1;
      return json(route, {
        backups: [],
        restores: [],
        outbox: { pending: 0, processing: 0, completed: 0, failed: 0, oldest_pending_at: null },
        write_lock: { held: true, owner_connection_id: 42, observed_seconds: 5, warning: false },
        observed_at: "2026-09-04T08:00:00Z",
        maintenance_active: true,
        worker: {
          query_health: "healthy",
          failure_code: null,
          thresholds: { heartbeat_seconds: 10, stale_seconds: 30, offline_seconds: 60, refresh_seconds: 15 },
          instances: [{
            instance_id: "0123456789abcdef0123456789abcdef",
            role: "local_worker",
            build_id: "stage2-e2e",
            supported_queues: ["return_dedup", "publication_outbox", "catalog_export", "catalog_import"],
            lifecycle_status: "running",
            heartbeat_status: "online",
            heartbeat_sequence: 9,
            last_heartbeat_at: "2026-09-04T07:59:55Z",
            heartbeat_age_seconds: 5,
            last_result_code: "heartbeat_succeeded",
            consumers: [],
          }],
        },
        queues: [
          { ...queueBase, queue_name: "return_dedup", capabilities: { ...capabilities, stale: true, stuck: false } },
          { ...queueBase, queue_name: "publication_outbox", capabilities: { ...capabilities, retry_wait: true, stale: true, stuck: false } },
          { ...queueBase, queue_name: "catalog_export", actionable: null, in_flight: null, stuck: null, unresolved_building: 2, capabilities: { actionable: false, in_flight: false, retry_wait: false, stale: false, stuck: false } },
          { ...queueBase, queue_name: "catalog_import", consumer_health: "failing", failure_code: "catalog_import_error", stuck: 1, failed: 1, last_succeeded_at: null, last_failed_at: "2026-09-04T07:59:51Z", consecutive_failures: 3 },
        ],
      });
    }
    return json(route, { error: { code: "unhandled", message: pathname } }, 500);
  });

  await page.goto("/admin");
  await page.getByRole("button", { name: "备份与任务" }).click();

  await expect(page.getByRole("heading", { name: "Worker 运行状态" })).toBeVisible();
  await expect(page.getByText("在线仅表示最近成功写入数据库心跳")).toBeVisible();
  await expect(page.getByText("进程在线，catalog_import 消费者失败")).toBeVisible();
  await expect(page.getByText(/维护模式已开启/)).toBeVisible();
  expect(maintenanceRequests).toBe(1);

  await page.clock.fastForward(15_000);
  await expect.poll(() => maintenanceRequests).toBe(2);
  const screenshotPath = process.env.APP_STAGE2_ADMIN_SCREENSHOT_PATH;
  if (screenshotPath) {
    if (!path.isAbsolute(screenshotPath)) {
      throw new Error("APP_STAGE2_ADMIN_SCREENSHOT_PATH must be absolute");
    }
    await page.screenshot({ path: screenshotPath, fullPage: true });
  }
  await page.getByRole("button", { name: "账号与角色" }).click();
  await page.clock.fastForward(30_000);
  expect(maintenanceRequests).toBe(2);
});
