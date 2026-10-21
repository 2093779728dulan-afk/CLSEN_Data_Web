import type { CoverageBlock, MetricValue, StyleLedgerResponse } from "./productAnalyticsTypes";
import type { CatalogCategory } from "../catalog/catalogApi";

const metric=(value:number|string|null,state: MetricValue["value_state"]="observed",partial=false): MetricValue=>({denominator:null,expected_days:31,is_partial:partial,null_reason:state==="missing_report"?"no_observed_reports":null,numerator:null,observed_days:state==="missing_report"?0:31,source_completeness:partial?"partial":"complete",value,value_state:state});
const block=(report_type:CoverageBlock["report_type"]): CoverageBlock=>({confirmed_distinct_rows:1,coverage_from:"2026-07-25",coverage_to:"2026-08-24",dedup_decision_rate:"1.000000",dedup_status:"complete",duplicate_of_rows:0,eligible_rows:1,excluded_rows:0,expected_days:31,identity_decision_rate:"1.000000",identity_status:"complete",mapped_rows:1,mapping_rate:"1.000000",missing_days:0,published_days:31,report_coverage_rate:"1.000000",report_type,unique_rows:1,unmatched_rows:0,unresolved_rows:0});
const totals={conversion_denominator:10,conversion_numerator:2,returns:0,sales:"120.00",sessions:10,units:2};
export const productLedgerFixture: StyleLedgerResponse = {filtered_sales_total:"120.00",coverage:{scope:"site",business:block("business_report"),returns:block("return_report")},direction:"desc",page:1,page_size:50,permissions:{can_approve_high_risk:false,can_approve_normal:false,can_download_original:false,can_manage_catalog:false,can_submit:false,can_view_catalog_history:true,can_view_evidence_history:true},provenance:{catalog_version:7,catalog_version_id:"7",consistent_as_of:"2026-08-24T10:00:00Z",effective_return_basis:"event_date",fact_basis:"current",fact_cutoff_at:"2026-08-24T09:00:00Z",from:"2026-07-25",identity_source:"p0_catalog",identity_version_id:"7",publication_refs:{members:[],members_digest:"sha256:x",members_digest_version:"publication_refs_jcs_v1",mode:"current",snapshot_id:null},reporting_timezone:"America/Los_Angeles",return_basis:"event_date",return_dedup_snapshot_id:"1",site_config_version_id:"2",to:"2026-08-24",trend_effective_return_basis:null},reconciliation:{scope:"site",metric_status:{conversion:"evaluable",returns:"evaluable",sales:"evaluable",sessions:"evaluable",units:"evaluable"},source_totals:totals,mapped_totals:totals,unmatched_totals:totals,excluded_totals:totals,duplicate_totals:totals,unresolved_duplicate_totals:{...totals,units:null}},rows:[{color_count:3,latest_report_date:"2026-08-24",metrics:{units:metric(2),sales:metric("120.00"),returns:metric(0,"zero"),sessions:metric(10),conversion:metric("0.200000")},size_count:9,sku_count:10,source_title_count:3,standard_name:"标准轻量夹克",status:"enabled",style_code:"10001",style_id:"501"}],sort:"units",total_rows:1};
const zeroTotals = { conversion_denominator: 0, conversion_numerator: 0, returns: 0, sales: "0.00", sessions: 0, units: 0 };
for (const bucket of ["unmatched_totals", "excluded_totals", "duplicate_totals", "unresolved_duplicate_totals"] as const) productLedgerFixture.reconciliation[bucket] = { ...zeroTotals };
export const ledgerCategories: CatalogCategory[] = [
  { category_id: 1, code: "demo-outer", display_name: "示例外套", aliases: [], status: "enabled", parent_category_id: null },
  { category_id: 2, code: "demo-jacket", display_name: "示例夹克", aliases: [], status: "enabled", parent_category_id: 1 },
];
export function ledgerFixture(scenario = "reference"): StyleLedgerResponse {
  const data = structuredClone(productLedgerFixture);
  if (scenario === "partial") {
    data.coverage.business.published_days = 30; data.coverage.business.missing_days = 1; data.coverage.business.report_coverage_rate = "0.967742";
    for (const key of ["units", "sales", "sessions", "conversion"] as const) Object.assign(data.rows[0]!.metrics[key], { is_partial: true, observed_days: 30, source_completeness: "partial" });
  }
  if (scenario === "empty" || scenario === "no-reports") { data.rows = []; data.total_rows = 0; data.filtered_sales_total = "0.00"; }
  if (scenario === "no-reports") {
    for (const key of ["business", "returns"] as const) Object.assign(data.coverage[key], {
      published_days: 0, missing_days: 31, report_coverage_rate: "0.000000",
      confirmed_distinct_rows: 0, eligible_rows: 0, mapped_rows: 0, unique_rows: 0,
      dedup_decision_rate: null, identity_decision_rate: null, mapping_rate: null,
      dedup_status: "not_applicable", identity_status: "not_applicable",
    });
    for (const key of ["conversion", "returns", "sales", "sessions", "units"] as const) data.reconciliation.metric_status[key] = "not_evaluable";
  }
  if (scenario === "zero-values") for (const key of ["units", "sales", "sessions", "returns", "conversion"] as const) {
    data.rows[0]!.metrics[key] = metric(key === "sales" ? "0.00" : key === "conversion" ? null : 0, key === "conversion" ? "undefined_denominator" : "zero");
    data.rows[0]!.metrics[key].null_reason = key === "conversion" ? "undefined_denominator" : null;
  }
  if (scenario === "zero-values") {
    data.filtered_sales_total = "0.00"; data.reconciliation.source_totals = { ...zeroTotals }; data.reconciliation.mapped_totals = { ...zeroTotals };
  }
  if (scenario === "no-reports") for (const bucket of ["source_totals", "mapped_totals", "unmatched_totals", "excluded_totals", "duplicate_totals", "unresolved_duplicate_totals"] as const) data.reconciliation[bucket] = { conversion_denominator: null, conversion_numerator: null, returns: null, sales: null, sessions: null, units: null };
  return data;
}
