import { CatalogReadError } from "./CatalogReadFailure";
import { catalogReadError } from "./catalogReadError";
import { useEffect, useMemo, useState } from "react";
import { Link, useSearchParams } from "react-router-dom";
import { AlertTriangle, ArrowLeft, ArrowRight, FileSearch } from "lucide-react";

import { Button } from "../../design-system";
import {
  getCurrentCatalog,
  getCatalogStylePendingItems,
  listCatalogUnmatched,
  type CatalogPendingItem,
  type CatalogStyle,
  type CatalogUnmatchedResponse,
} from "./catalogApi";
import { CatalogPendingItems } from "./CatalogPendingItems";
import { useCatalogNavigation } from "./CatalogNavigationContext";

type PendingStyle = { style: CatalogStyle; items: CatalogPendingItem[] };

function money(values: Array<{ currency_code: string; value: string }>): string {
  if (!values.length) return "—";
  return values.map((item) => `${item.currency_code === "USD" ? "US$" : `${item.currency_code} `}${Number(item.value).toLocaleString("zh-CN", { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`).join(" · ");
}

export function CatalogUnmatchedPage() {
  const { setStyleReturn } = useCatalogNavigation();
  const [parameters, setParameters] = useSearchParams();
  const page = Math.max(1, Number(parameters.get("page")) || 1);
  const from = parameters.get("from") ?? undefined;
  const to = parameters.get("to") ?? undefined;
  const returnBasis = parameters.get("return_basis") === "report_date" ? "report_date" : "event_date";
  const returnTo = parameters.get("return_to") ?? undefined;
  const [pending, setPending] = useState<PendingStyle[]>();
  const [pendingError, setPendingError] = useState<ReturnType<typeof catalogReadError>>();
  const [unmatched, setUnmatched] = useState<CatalogUnmatchedResponse>();
  const [error, setError] = useState<ReturnType<typeof catalogReadError>>();
  const [attempt, setAttempt] = useState(0);

  useEffect(() => {
    let active = true;
    setError(undefined);
    setPendingError(undefined);
    setPending(undefined);
    setUnmatched(undefined);
    async function load() {
      try {
        const sources = await listCatalogUnmatched({ from, to, returnBasis, page, pageSize: 25 });
        if (!active) return;
        setUnmatched(sources);
      } catch (reason: unknown) {
        if (active) setError(catalogReadError(reason, "无法读取待归属来源，请检查连接后重试。"));
        return;
      }
      try {
        const catalog = await getCurrentCatalog();
      const results: PendingStyle[] = [];
      const styles = catalog?.styles ?? [];
      for (let index = 0; index < styles.length && active; index += 4) {
        const batch = await Promise.all(styles.slice(index, index + 4).map(async (style) => ({ style, summary: await getCatalogStylePendingItems(style.style_id) })));
        for (const { style, summary } of batch) {
          if (summary.permissions.can_review && summary.items.length) results.push({ style, items: summary.items });
        }
      }
        if (active) setPending(results);
      } catch (reason: unknown) {
        if (active) setPendingError(catalogReadError(reason, "无法读取已有审核候选，请稍后刷新。"));
      }
    }
    void load();
    return () => { active = false; };
  }, [attempt, from, page, returnBasis, to]);

  const maintenancePath = useMemo(() => {
    const query = new URLSearchParams();
    query.set("return_to", `/catalog/unmatched?${parameters.toString()}`);
    return `/catalog/maintenance?${query.toString()}`;
  }, [parameters]);
  const changePage = (next: number) => {
    const query = new URLSearchParams(parameters);
    query.set("page", String(next));
    setParameters(query);
  };

  if (error) return <CatalogReadError failure={error} onRetry={() => setAttempt(value => value + 1)} />;
  if (!unmatched) return <p role="status">正在核对当前发布事实与商品归属…</p>;
  const noPublicationEvidence = unmatched.baseline.publication_refs.length === 0 && unmatched.total_items === 0 && unmatched.impact.business_fact_rows === 0 && unmatched.impact.return_fact_rows === 0;
  const futureRange = unmatched.range.from_date > unmatched.baseline.consistent_as_of.slice(0, 10);
  const pageCount = Math.max(1, Math.ceil(unmatched.total_items / unmatched.page_size));
  return <div className="catalog-stack catalog-unmatched">
    {returnTo && <Link className="catalog-back-link" to={returnTo}><ArrowLeft aria-hidden="true" />返回产品分析</Link>}
    <section className="catalog-panel catalog-unmatched__summary">
      <div><p className="section-kicker">CURRENT PUBLISHED FACTS</p><h2>待归属 Seller SKU</h2><p>直接核对当前有效发布报表，不需要先下载或重新上传目录工作簿。只有审核批准新目录版本后，数据才会计入对应商品。</p></div>
      {noPublicationEvidence ? <div role="status"><h3>{futureRange ? "所选日期尚未到达" : "当前范围没有可用的发布依据"}</h3><p>{futureRange ? "待归属核对仅包含截至当前日期的有效发布报表。未来日期即使已经发布，也不会进入此次核对，请选择已到达的报告日期。" : "本次查询没有返回范围内发布依据或待归属事实，不能据此判断所有 SKU 已完成归属。请核对报告日期与发布状态。"}</p><Link to={`/review/${unmatched.range.from_date}`}>查看该日发布状态</Link></div> : <dl><div><dt>待归属</dt><dd>{unmatched.total_items}</dd></div><div><dt>少计销量</dt><dd>{unmatched.impact.units.toLocaleString("zh-CN")} 件</dd></div><div><dt>少计销售额</dt><dd>{money(unmatched.impact.sales_by_currency)}</dd></div><div><dt>待核退货</dt><dd>{unmatched.impact.return_quantity.toLocaleString("zh-CN")} 件</dd></div></dl>}
      <p className="catalog-unmatched__baseline">范围 {unmatched.range.from_date} 至 {unmatched.range.to_date} · 目录 {unmatched.baseline.catalog_version_id ? `V${unmatched.baseline.catalog_version_id}` : "尚未初始化"} · 当前事实 · 退货按{returnBasis === "event_date" ? "事件日期" : "报表日期"}</p>
    </section>
    {unmatched.impact.unresolved_return_rows > 0 && <p className="catalog-issues"><AlertTriangle aria-hidden="true" />另有 {unmatched.impact.unresolved_return_rows} 条退货记录仍待去重判定，未计入上方退货量。</p>}
    {!noPublicationEvidence && <section className="catalog-panel">
      <div className="catalog-panel__heading"><div><h2>来源清单</h2><p>共 {unmatched.total_items} 个去重身份，第 {unmatched.page} / {pageCount} 页。金额按币种分别汇总。</p></div><Link className="catalog-action-primary" to={maintenancePath}><FileSearch aria-hidden="true" />生成或继续审核候选</Link></div>
      {unmatched.items.length === 0 ? <p>当前范围没有未归属来源。</p> : <ol className="catalog-unmatched__list">
        {unmatched.items.map((item) => <li key={item.source_identity.seller_sku_match}>
          <div className="catalog-unmatched__identity"><strong>{item.preview}</strong><span>{item.report_types.map((value) => value === "business_report" ? "经营" : "退货").join(" + ")}</span></div>
          <dl><div><dt>首次 / 最近</dt><dd>{item.first_seen_date} / {item.latest_seen_date}</dd></div><div><dt>销量影响</dt><dd>{item.business.units} 件 · {money(item.business.sales_by_currency)}</dd></div><div><dt>退货影响</dt><dd>{item.returns.quantity} 件{item.returns.unresolved_rows ? ` · ${item.returns.unresolved_rows} 条待去重` : ""}</dd></div></dl>
          <div className="catalog-unmatched__action">{item.candidate.review_path ? <Link to={item.candidate.review_path}>{item.candidate.status === "in_review" ? "继续审核" : "查看候选"}<ArrowRight aria-hidden="true" /></Link> : <span>尚未生成候选</span>}</div>
        </li>)}
      </ol>}
      <div className="catalog-evidence-pagination"><Button disabled={page <= 1} onClick={() => changePage(page - 1)}>上一页</Button><span>第 {page} / {pageCount} 页</span><Button disabled={page >= pageCount} onClick={() => changePage(page + 1)}>下一页</Button></div>
    </section>}
    <section className="catalog-panel"><h2>已有审核候选</h2>
      {pendingError ? <CatalogReadError failure={pendingError} onRetry={() => setAttempt(value => value + 1)} />
        : !pending ? <p role="status">正在读取已有审核候选，来源清单可以先处理。</p>
        : <><p>当前有 {pending.length} 款已生效商品存在待审核候选。草稿不会改变正式目录。</p>{pending.length === 0 ? <p>当前没有关联到已生效商品的审核候选。</p> : pending.map(({ style, items }) => <div key={style.style_id}><h3><Link onClick={() => setStyleReturn(`/catalog/unmatched?${parameters.toString()}`)} to={`/catalog/styles/${style.style_id}`}>{style.style_code} · {style.standard_name}</Link></h3><CatalogPendingItems canReview items={items} /></div>)}</>}
    </section>
  </div>;
}
