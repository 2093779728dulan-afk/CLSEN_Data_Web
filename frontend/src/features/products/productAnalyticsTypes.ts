import type { components, operations } from "../../api/generated";

export type PlatformIdentityReview = { state: string; message: string; pending_metrics?: { units: number; sales: string; returns: number; business_rows: number; return_rows: number }; ordinary_unmatched_rows?: { business: number; returns: number } };
export type StyleLedgerResponse =
  operations["style_ledger_api_dashboard_style_ledger_get"]["responses"][200] & { platform_identity_review?: PlatformIdentityReview | null };
export type StyleCardResponse =
  operations["style_card_api_dashboard_styles__style_id__card_get"]["responses"][200] & { platform_identity_review?: PlatformIdentityReview | null };
export type StyleLedgerQuery =
  operations["style_ledger_api_dashboard_style_ledger_get"]["query"];
export type GeneratedStyleCardQuery =
  operations["style_card_api_dashboard_styles__style_id__card_get"]["query"];
export type StyleCardQuery = Omit<GeneratedStyleCardQuery, "series"> & {
  series?: readonly string[] | null;
};
export type MetricValue = components["schemas"]["MetricValue"];
export type CoverageBlock = components["schemas"]["CoverageBlock"];

export function hasP0CatalogIdentity(
  value: StyleLedgerResponse | StyleCardResponse,
): boolean {
  return value.provenance.identity_source === "p0_catalog"
    && value.provenance.identity_version_id === value.provenance.catalog_version_id;
}
