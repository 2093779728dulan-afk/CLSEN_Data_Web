import css from "./ProductAnalytics.module.css";
import type { components } from "../../api/generated";
import { formatCoverage, formatMoney } from "./metricFormatting";
import { Link } from "react-router-dom";

type SiteCoverage = components["schemas"]["SiteCoverage"];
type SiteReconciliation = components["schemas"]["SiteReconciliation"];
type MetricTotals = components["schemas"]["MetricTotals"];

const bucketLabels = {
  source: "来源总量", mapped: "已映射", unmatched: "未匹配", excluded: "已排除",
  duplicate: "已确认重复", unresolved: "待判定重复",
};

function CoverageLine({ label, block }: { label: string; block: SiteCoverage["business"] }) {
  return <div className={css["analytics-coverage__row"]}>
    <strong>{label}</strong>
    <span>{block.published_days}/{block.expected_days} 天</span>
    <span>报表 {formatCoverage(block.report_coverage_rate)}</span>
    <span>映射 {formatCoverage(block.mapping_rate)}</span>
    <span>身份 {formatCoverage(block.identity_decision_rate)}</span>
    <span>去重 {formatCoverage(block.dedup_decision_rate)}</span>
    <span className={css["analytics-status"] + " " + (css[`analytics-status--${block.identity_status}`] ?? "")}>{block.identity_status}</span>
  </div>;
}

function totalCell(value: number | string | null, money = false) {
  if (value === null) return "不可计算";
  return money ? formatMoney(String(value)) : typeof value === "number" ? value.toLocaleString("zh-CN") : value;
}

function BucketRow({ label, totals }: { label: string; totals: MetricTotals }) {
  const conversion = totals.conversion_numerator === null || totals.conversion_denominator === null
    ? "不可计算" : `${totals.conversion_numerator}/${totals.conversion_denominator}`;
  return <tr><th scope="row">{label}</th><td>{totalCell(totals.units)}</td><td>{totalCell(totals.sales, true)}</td>
    <td>{totalCell(totals.returns)}</td><td>{totalCell(totals.sessions)}</td><td>{conversion}</td></tr>;
}

export function CoverageReconciliation({ coverage, reconciliation, from, to, returnBasis }: {
  coverage: SiteCoverage;
  reconciliation: SiteReconciliation;
  from?: string;
  to?: string;
  returnBasis?: "event_date" | "report_date";
}) {
  return <section className={css["analytics-reconciliation"]} aria-labelledby="analytics-reconciliation-title">
    <div className={css["analytics-section-heading"]}><div><p className={css["analytics-eyebrow"]}>DATA QUALITY</p><h2 id="analytics-reconciliation-title">覆盖与六桶对账</h2></div>
      <p>六桶来自同一一致性快照；不可计算与数值零分别显示。</p></div>
    <div className={css["analytics-coverage"]} aria-label="站点报表覆盖">
      <CoverageLine block={coverage.business} label="经营报表" />
      <CoverageLine block={coverage.returns} label="退货报表" />
    </div>
    <div className={css["analytics-table-scroll"]} role="region" aria-label="六桶指标对账" tabIndex={0}>
      <table className={css["analytics-table"]}><thead><tr><th>桶</th><th>销量</th><th>销售额</th><th>退货</th><th>会话</th><th>转化分子/分母</th></tr></thead><tbody>
        <BucketRow label={bucketLabels.source} totals={reconciliation.source_totals} />
        <BucketRow label={bucketLabels.mapped} totals={reconciliation.mapped_totals} />
        <BucketRow label={bucketLabels.unmatched} totals={reconciliation.unmatched_totals} />
        <BucketRow label={bucketLabels.excluded} totals={reconciliation.excluded_totals} />
        <BucketRow label={bucketLabels.duplicate} totals={reconciliation.duplicate_totals} />
        <BucketRow label={bucketLabels.unresolved} totals={reconciliation.unresolved_duplicate_totals} />
      </tbody></table>
    </div>
    {from && to && (Number(reconciliation.unmatched_totals.units ?? 0) > 0 || Number(reconciliation.unmatched_totals.returns ?? 0) > 0) && <div className={css["analytics-unmatched-callout"]}>
      <div><strong>商品汇总尚未覆盖全部来源</strong><span>当前范围仍有未归属 Seller SKU；它们保留在来源总量中，但不会伪装成某个商品。</span></div>
      <Link to={`/catalog/unmatched?from=${encodeURIComponent(from)}&to=${encodeURIComponent(to)}&return_basis=${returnBasis ?? "event_date"}&return_to=${encodeURIComponent(`/products?from=${from}&to=${to}&return_basis=${returnBasis ?? "event_date"}&fact_basis=current`)}`}>查看待归属及影响</Link>
    </div>}
  </section>;
}
