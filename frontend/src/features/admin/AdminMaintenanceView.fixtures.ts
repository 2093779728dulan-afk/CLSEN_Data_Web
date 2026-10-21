import type { MaintenanceStatusResponse, QueueStatusResponse } from "../../api/generated";

const queueNames: QueueStatusResponse["queue_name"][] = ["return_dedup", "publication_outbox", "catalog_export", "catalog_import"];
export const maintenanceStatus: MaintenanceStatusResponse = {
  observed_at: "2026-09-13T10:30:00Z", maintenance_active: false,
  write_lock: { held: false, owner_connection_id: null, observed_seconds: 0, warning: false },
  outbox: { pending: 2, processing: 1, failed: 0, completed: 12, oldest_pending_at: "2026-09-13T10:29:00Z" },
  worker: { query_health: "healthy", failure_code: null, thresholds: { heartbeat_seconds: 10, stale_seconds: 30, offline_seconds: 60, refresh_seconds: 15 }, instances: [{
    instance_id: "demo-worker-01-abcdef", build_id: "demo-local-build", role: "local_worker", supported_queues: queueNames,
    lifecycle_status: "running", heartbeat_status: "online", heartbeat_sequence: 42, last_heartbeat_at: "2026-09-13T10:29:55Z", heartbeat_age_seconds: 5, last_result_code: "heartbeat_succeeded",
    consumers: queueNames.map(queue_name => ({ queue_name, consumer_health: "healthy", consecutive_failures: 0, failure_code: null, last_poll_started_at: "2026-09-13T10:29:50Z", last_poll_completed_at: "2026-09-13T10:29:52Z", last_poll_succeeded_at: "2026-09-13T10:29:52Z", last_poll_failed_at: null })),
  }] },
  queues: queueNames.map(queue_name => {
    const caps = { actionable: queue_name !== "catalog_export", in_flight: queue_name !== "catalog_export", retry_wait: queue_name === "publication_outbox", stale: queue_name === "return_dedup" || queue_name === "publication_outbox", stuck: queue_name === "catalog_import" };
    return { queue_name, capabilities: caps, query_health: "healthy", consumer_health: "healthy", consecutive_failures: 0, failure_code: null, actionable: caps.actionable ? 0 : null, in_flight: caps.in_flight ? 0 : null, retry_wait: caps.retry_wait ? 0 : null, stale: caps.stale ? 0 : null, stuck: caps.stuck ? 0 : null, failed: 0, unresolved_building: queue_name === "catalog_export" ? 0 : null, native_status_counts: { ready: 2, failed: 0 }, oldest_work_at: null, next_retry_at: null, last_succeeded_at: "2026-09-13T10:29:52Z", last_failed_at: null };
  }),
  backups: [{ id: 501, backup_uuid: "demo-backup-01-abcdef", database_name: "demo_database", key_id: "demo-key-reference", schema_revision: "0022", status: "succeeded", raw_file_count: 4, publication_count: 2, version_count: 8, audit_event_count: 12, started_at: "2026-09-13T02:00:00Z", sealed_at: "2026-09-13T02:01:00Z", completed_at: "2026-09-13T02:02:00Z", restore_verified_at: "2026-09-13T03:00:00Z", failure_code: null }],
  restores: [{ id: 601, backup_uuid: "demo-backup-01-abcdef", verification_uuid: "demo-restore-01-abcdef", status: "succeeded", target_database_name: "demo_restore_isolated", started_at: "2026-09-13T02:30:00Z", completed_at: "2026-09-13T03:00:00Z", failure_code: null }],
};

export type MaintenanceScenario = "reference" | "diagnostics" | "refreshing" | "refresh-failure" | "loading" | "read-failure" | "empty" | "consumer-failure" | "query-unknown" | "heartbeat-delayed" | "backup-failure" | "access-denied";
export function statusFor(scenario: MaintenanceScenario) {
  const status = structuredClone(maintenanceStatus);
  if (scenario === "empty") { status.backups = []; status.restores = []; status.worker.instances = []; status.queues.forEach(q => { q.consumer_health = "not_observed"; }); }
  if (scenario === "consumer-failure") {
    const q = status.queues[3]!; q.consumer_health = "failing"; q.failure_code = "demo_catalog_import_error"; q.consecutive_failures = 3; q.stuck = 1; q.failed = 1;
    const c = status.worker.instances[0]!.consumers[3]!; c.consumer_health = "failing"; c.failure_code = q.failure_code; c.consecutive_failures = 3;
    status.queues[2]!.unresolved_building = 2;
  }
  if (scenario === "query-unknown") {
    status.worker.query_health = "unknown"; status.worker.failure_code = "demo_worker_query_failed"; status.worker.instances = [];
    const q = status.queues[1]!; q.query_health = "unknown"; q.consumer_health = "unknown"; q.failure_code = "demo_queue_query_failed";
    q.actionable = q.in_flight = q.retry_wait = q.stale = q.stuck = q.failed = null; q.native_status_counts = null;
  }
  if (scenario === "heartbeat-delayed") {
    const first = status.worker.instances[0]!; first.heartbeat_status = "stale"; first.heartbeat_age_seconds = 40;
    status.worker.instances.push({ ...structuredClone(first), instance_id: "demo-worker-offline", heartbeat_status: "offline", heartbeat_age_seconds: 80 });
    status.maintenance_active = true; status.write_lock = { held: true, warning: true, observed_seconds: 120, owner_connection_id: 42 };
  }
  if (scenario === "backup-failure") {
    const backup = status.backups[0]!; backup.status = "failed"; backup.failure_code = "demo_backup_failed"; backup.restore_verified_at = null;
    const restore = status.restores[0]!; restore.status = "failed"; restore.failure_code = "demo_restore_failed";
    status.backups.push({ ...structuredClone(backup), id: 502, backup_uuid: "demo-backup-running", status: "running", completed_at: null, failure_code: null });
  }
  return status;
}
