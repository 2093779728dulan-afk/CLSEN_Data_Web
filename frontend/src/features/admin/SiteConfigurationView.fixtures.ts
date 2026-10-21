import type { SiteConfigVersionResponse } from "../../api/generated";
import type { SiteFormState } from "./SiteConfigurationView";

export const siteConfigs: SiteConfigVersionResponse[] = [
  { id: 702, site_id: 71, site_code: "demo-us", site_display_name: "示例美国站点", version_number: 2, source_timezone: "America/Los_Angeles", reporting_timezone: "Asia/Shanghai", currency_code: "USD", effective_at: "2026-09-12T00:00:00Z", change_reason: "示例：统一每日统计的日期口径", created_by_user_id: 88, created_at: "2026-09-12T00:30:00Z", is_current: true },
  { id: 701, site_id: 71, site_code: "demo-us", site_display_name: "示例美国站点", version_number: 1, source_timezone: "America/Los_Angeles", reporting_timezone: "America/Los_Angeles", currency_code: "USD", effective_at: "2026-09-01T00:00:00Z", change_reason: "示例：创建站点初始口径", created_by_user_id: 88, created_at: "2026-09-01T00:30:00Z", is_current: false },
];
export const siteForm: SiteFormState = { changeReason: "", currencyCode: "USD", effectiveAt: "2026-09-13T08:00", reportingTimezone: "Asia/Shanghai", siteId: "71", sourceTimezone: "America/Los_Angeles" };
