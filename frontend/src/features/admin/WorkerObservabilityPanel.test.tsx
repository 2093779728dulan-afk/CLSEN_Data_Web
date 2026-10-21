import { render, screen } from "@testing-library/react";
import { expect, it, vi } from "vitest";

import type { MaintenanceStatusResponse } from "../../api/generated";
import { WorkerObservabilityPanel } from "./WorkerObservabilityPanel";

const status: MaintenanceStatusResponse = {
  backups: [],
  restores: [],
  outbox: {
    pending: 0,
    processing: 0,
    completed: 0,
    failed: 0,
    oldest_pending_at: null,
  },
  write_lock: {
    held: true,
    owner_connection_id: 42,
    observed_seconds: 4,
    warning: false,
  },
  observed_at: "2026-09-04T08:00:00Z",
  maintenance_active: true,
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
      instance_id: "0123456789abcdef0123456789abcdef",
      role: "local_worker",
      build_id: "stage2-test",
      supported_queues: [
        "return_dedup",
        "publication_outbox",
        "catalog_export",
        "catalog_import",
      ],
      lifecycle_status: "running",
      heartbeat_status: "online",
      heartbeat_sequence: 7,
      last_heartbeat_at: "2026-09-04T07:59:55Z",
      heartbeat_age_seconds: 5,
      last_result_code: "heartbeat_succeeded",
      consumers: [{
        queue_name: "catalog_import",
        consumer_health: "failing",
        last_poll_started_at: "2026-09-04T07:59:50Z",
        last_poll_completed_at: "2026-09-04T07:59:51Z",
        last_poll_succeeded_at: null,
        last_poll_failed_at: "2026-09-04T07:59:51Z",
        consecutive_failures: 3,
        failure_code: "catalog_import_error",
      }],
    }],
  },
  queues: [
    {
      queue_name: "return_dedup",
      query_health: "healthy",
      consumer_health: "healthy",
      failure_code: null,
      native_status_counts: { building: 0, ready: 2, failed: 0, superseded: 0 },
      actionable: 0,
      in_flight: 0,
      retry_wait: null,
      stale: 0,
      stuck: null,
      failed: 0,
      unresolved_building: null,
      oldest_work_at: null,
      next_retry_at: null,
      last_succeeded_at: "2026-09-04T07:59:58Z",
      last_failed_at: null,
      consecutive_failures: 0,
      capabilities: {
        actionable: true,
        in_flight: true,
        retry_wait: false,
        stale: true,
        stuck: false,
      },
    },
    {
      queue_name: "publication_outbox",
      query_health: "unknown",
      consumer_health: "unknown",
      failure_code: "publication_outbox_query_failed",
      native_status_counts: null,
      actionable: null,
      in_flight: null,
      retry_wait: null,
      stale: null,
      stuck: null,
      failed: null,
      unresolved_building: null,
      oldest_work_at: null,
      next_retry_at: null,
      last_succeeded_at: null,
      last_failed_at: null,
      consecutive_failures: null,
      capabilities: {
        actionable: true,
        in_flight: true,
        retry_wait: true,
        stale: true,
        stuck: false,
      },
    },
    {
      queue_name: "catalog_export",
      query_health: "healthy",
      consumer_health: "healthy",
      failure_code: null,
      native_status_counts: { building: 2, ready: 1, failed: 0 },
      actionable: null,
      in_flight: null,
      retry_wait: null,
      stale: null,
      stuck: null,
      failed: 0,
      unresolved_building: 2,
      oldest_work_at: "2026-09-04T07:55:00Z",
      next_retry_at: null,
      last_succeeded_at: "2026-09-04T07:59:57Z",
      last_failed_at: null,
      consecutive_failures: 0,
      capabilities: {
        actionable: false,
        in_flight: false,
        retry_wait: false,
        stale: false,
        stuck: false,
      },
    },
    {
      queue_name: "catalog_import",
      query_health: "healthy",
      consumer_health: "failing",
      failure_code: "catalog_import_error",
      native_status_counts: { uploaded: 0, parsing: 1, parse_failed: 1 },
      actionable: 0,
      in_flight: 0,
      retry_wait: null,
      stale: null,
      stuck: 1,
      failed: 1,
      unresolved_building: null,
      oldest_work_at: "2026-09-04T07:50:00Z",
      next_retry_at: null,
      last_succeeded_at: null,
      last_failed_at: "2026-09-04T07:59:51Z",
      consecutive_failures: 3,
      capabilities: {
        actionable: true,
        in_flight: true,
        retry_wait: false,
        stale: false,
        stuck: true,
      },
    },
  ],
};

it("renders database heartbeat, queue capability, and maintenance semantics", () => {
  render(
    <WorkerObservabilityPanel
      onRefresh={vi.fn()}
      pageRefreshedAt={new Date("2026-09-04T08:00:03Z")}
      refreshError={null}
      refreshing={false}
      status={status}
    />,
  );

  expect(screen.getByRole("heading", { name: "Worker 运行状态" })).toBeVisible();
  expect(screen.getByText("在线仅表示最近成功写入数据库心跳")).toBeVisible();
  expect(screen.getByText("进程在线，catalog_import 消费者失败")).toBeVisible();
  expect(screen.getByText("连续失败 3 次 · catalog_import_error")).toBeVisible();
  expect(screen.getByText("未决构建 2")).toBeVisible();
  expect(screen.getByText("卡住 1")).toBeVisible();
  expect(screen.getAllByText("不适用").length).toBeGreaterThan(0);
  expect(screen.getAllByText("无法确认").length).toBeGreaterThan(0);
  expect(screen.getByText(/维护模式已开启/)).toBeVisible();
  expect(screen.getByText(/页面最后刷新/)).toBeVisible();
});

it("keeps the last response visible while a refresh fails", () => {
  render(
    <WorkerObservabilityPanel
      onRefresh={vi.fn()}
      pageRefreshedAt={new Date("2026-09-04T08:00:03Z")}
      refreshError="网络暂时不可用"
      refreshing={false}
      status={status}
    />,
  );

  expect(screen.getByText("状态可能已过期：网络暂时不可用")).toBeVisible();
  expect(screen.getByText("stage2-test")).toBeVisible();
});
