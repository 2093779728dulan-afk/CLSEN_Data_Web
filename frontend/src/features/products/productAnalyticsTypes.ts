import type { components, operations } from "../../api/generated";

export type StyleLedgerResponse =
  operations["style_ledger_api_dashboard_style_ledger_get"]["responses"][200];
export type StyleCardResponse =
  operations["style_card_api_dashboard_styles__style_id__card_get"]["responses"][200];
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
