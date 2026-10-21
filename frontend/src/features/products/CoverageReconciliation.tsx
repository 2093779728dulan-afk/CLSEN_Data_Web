import css from "./CoverageReconciliation.module.css";
import type { components } from "../../api/generated";
import { formatCoverage, formatMoney } from "./metricFormatting";
import { LinkButton, StatusBadge } from "../../design-system";

type SiteCoverage = components["schemas"]["SiteCoverage"];
type SiteReconciliation = components["schemas"]["SiteReconciliation"];
type MetricTotals = components["schemas"]["MetricTotals"];

const bucketLabels = {
  source: "来源总量", mapped: "已映射", unmatched: "未匹配", excluded: "已排除",
  duplicate: "已确认重复", unresolved: "待判定重复",
};

function CoverageLine({ label, block }: { label: string; block: SiteCoverage["business"] }) {
  const identityLabels = { complete: "已完成", partial: "部分完成", not_applicable: "不适用" };
  return <div className={css.coverageCard}>
    <div className={css.cardHeading}><h3>{label}</h3><span>{block.published_days}/{block.expected_days} 天</span></div>
    <dl className={css.rates}>
      <div><dt>报表覆盖比率</dt><dd>{formatCoverage(block.report_coverage_rate)}</dd></div>
      <div><dt>映射比率</dt><dd>{formatCoverage(block.mapping_rate)}</dd></div>
      <div><dt>身份判定比率</dt><dd>{formatCoverage(block.identity_decision_rate)}</dd></div>
      <div><dt>去重判定比率</dt><dd>{formatCoverage(block.dedup_decision_rate)}</dd></div>
    </dl>
    <div className={css.identity}><span>身份判定</span><StatusBadge tone={block.identity_status === "complete" ? "good" : block.identity_status === "partial" ? "warn" : "quiet"} label={identityLabels[block.identity_status]} /></div>
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
  return <section className={css.frame} aria-labelledby="analytics-reconciliation-title">
    <div className={css.heading}><h2 id="analytics-reconciliation-title">覆盖与六桶对账</h2>
      <p>六桶来自同一一致性快照；不可计算与数值零分别显示。</p></div>
    <div className={css.coverage} role="group" aria-label="站点报表覆盖">
      <CoverageLine block={coverage.business} label="经营报表" />
      <CoverageLine block={coverage.returns} label="退货报表" />
    </div>
    <p className={css.hint}>比率沿用响应中的小数读数，— 表示无可用比率。横向滚动可核对完整指标，转化分子/分母保留原值。</p>
    <div className={css.scroller} role="region" aria-label="六桶指标对账" tabIndex={0}>
      <table className={css.table} aria-label="六桶指标对账"><thead><tr><th scope="col">桶</th><th scope="col">销量</th><th scope="col">销售额</th><th scope="col">退货</th><th scope="col">会话</th><th scope="col">转化分子/分母</th></tr></thead><tbody>
        <BucketRow label={bucketLabels.source} totals={reconciliation.source_totals} />
        <BucketRow label={bucketLabels.mapped} totals={reconciliation.mapped_totals} />
        <BucketRow label={bucketLabels.unmatched} totals={reconciliation.unmatched_totals} />
        <BucketRow label={bucketLabels.excluded} totals={reconciliation.excluded_totals} />
        <BucketRow label={bucketLabels.duplicate} totals={reconciliation.duplicate_totals} />
        <BucketRow label={bucketLabels.unresolved} totals={reconciliation.unresolved_duplicate_totals} />
      </tbody></table>
    </div>
    {from && to && (Number(reconciliation.unmatched_totals.units ?? 0) > 0 || Number(reconciliation.unmatched_totals.returns ?? 0) > 0) && <div className={css.callout}>
      <div><strong>商品汇总尚未覆盖全部来源</strong><span>当前范围仍有未归属 Seller SKU；它们保留在来源总量中，但不会伪装成某个商品。</span></div>
      <LinkButton to={`/catalog/unmatched?from=${encodeURIComponent(from)}&to=${encodeURIComponent(to)}&return_basis=${returnBasis ?? "event_date"}&return_to=${encodeURIComponent(`/products?from=${from}&to=${to}&return_basis=${returnBasis ?? "event_date"}&fact_basis=current`)}`}>查看待归属及影响</LinkButton>
    </div>}
  </section>;
}
