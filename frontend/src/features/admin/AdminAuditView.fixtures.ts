import type { AuditEventResponse } from "../../api/generated";

export const auditEvents: AuditEventResponse[] = Array.from({ length: 23 }, (_, i) => ({
  id: 900 - i,
  actor_user_id: i % 3 === 0 ? null : 42,
  actor_username: i % 3 === 0 ? null : "demo.admin",
  event_type: i % 2 === 0 ? "admin.user_updated" : "admin.site_config_created",
  object_type: i % 2 === 0 ? "user" : "site_config_version",
  object_id: String(i % 2 === 0 ? 45 : 702),
  occurred_at: new Date(Date.UTC(2026, 8, 13, 10, 30 - i)).toISOString(),
  site_id: 71,
  request_id: `demo-request-${900 - i}`,
  redacted_payload: i % 2 === 0 ? { roles: ["viewer"], status: "disabled", previous: { roles: ["data_manager"] } } : { version_number: 2, reporting_timezone: "Asia/Shanghai" },
}));
